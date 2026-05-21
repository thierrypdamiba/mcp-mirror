"""Live framework captures, transport-agnostic (stdio or streamable HTTP).

Each capture connects to a *real* MCP server, loads its tools through the real
framework adapter, introspects what the adapter exposes to the LLM, and returns
a ToolView. No simulation: this is the framework's actual behavior on its
actual code path.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import metadata
from typing import AsyncIterator, Awaitable, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from mcp_mirror.spec import ServerSpec
from mcp_mirror.types import ToolView


def _pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _normalize_schema(schema) -> dict:
    """Accept dict / Pydantic model / None and return a JSON Schema dict."""
    if schema is None:
        return {}
    if isinstance(schema, dict):
        return dict(schema)
    if hasattr(schema, "model_json_schema"):
        return schema.model_json_schema()
    if hasattr(schema, "schema"):
        return schema.schema()
    return {}


@asynccontextmanager
async def _session(spec: ServerSpec) -> AsyncIterator[ClientSession]:
    """Yield a connected ClientSession for any ServerSpec kind."""
    if spec.kind == "stdio":
        params = StdioServerParameters(command=spec.command or "", args=list(spec.args))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session
    elif spec.kind == "http":
        async with streamablehttp_client(spec.url or "", headers=spec.headers_dict) as (
            r,
            w,
            _,
        ):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session
    else:
        raise ValueError(f"Unknown ServerSpec kind: {spec.kind}")


@dataclass
class CaptureResult:
    framework: str
    framework_version: str | None
    views: list[ToolView]
    notes: str = ""


CaptureFn = Callable[[ServerSpec], Awaitable[CaptureResult]]


async def capture_server_announcement(spec: ServerSpec) -> CaptureResult:
    """The ground-truth: what the MCP server itself announces over the protocol."""
    async with _session(spec) as session:
        result = await session.list_tools()
        views: list[ToolView] = []
        for t in result.tools:
            meta = dict(getattr(t, "meta", None) or {})
            views.append(
                ToolView(
                    name=t.name,
                    description=t.description or "",
                    parameters_schema=dict(t.inputSchema or {}),
                    response_schema=dict(t.outputSchema) if getattr(t, "outputSchema", None) else None,
                    metadata=meta,
                )
            )
        return CaptureResult(
            framework="mcp-server",
            framework_version=_pkg_version("mcp"),
            views=views,
            notes="Direct MCP server announcement via the official Python SDK.",
        )


async def capture_langchain(spec: ServerSpec) -> CaptureResult:
    """LangChain via `langchain-mcp-adapters.load_mcp_tools(session)`.

    Session-based, so it works identically for stdio and HTTP transports.
    """
    from langchain_mcp_adapters.tools import load_mcp_tools

    version = _pkg_version("langchain-mcp-adapters")

    async with _session(spec) as session:
        lc_tools = await load_mcp_tools(session)
        views: list[ToolView] = []
        for tool in lc_tools:
            schema = _normalize_schema(tool.args_schema)
            views.append(
                ToolView(
                    name=tool.name,
                    description=tool.description or "",
                    parameters_schema=schema,
                    response_schema=None,
                    metadata={"__lc_tool_class": type(tool).__name__},
                )
            )
        return CaptureResult(
            framework="langchain",
            framework_version=version,
            views=views,
            notes="StructuredTool via langchain_mcp_adapters.load_mcp_tools.",
        )


async def capture_llamaindex(spec: ServerSpec) -> CaptureResult:
    """LlamaIndex via `llama-index-tools-mcp` (`BasicMCPClient` + `McpToolSpec`)."""
    from llama_index.tools.mcp import BasicMCPClient, McpToolSpec

    version = _pkg_version("llama-index-tools-mcp")

    if spec.kind == "stdio":
        client = BasicMCPClient(spec.command or "", args=list(spec.args))
    else:
        # BasicMCPClient supports HTTP by passing a URL. Headers are not in the
        # public signature on every version — pass via headers kwarg when available.
        try:
            client = BasicMCPClient(spec.url, headers=spec.headers_dict)
        except TypeError:
            client = BasicMCPClient(spec.url)
    li_tools = await McpToolSpec(client=client).to_tool_list_async()
    views: list[ToolView] = []
    for tool in li_tools:
        meta = tool.metadata
        params_schema = _normalize_schema(meta.fn_schema)
        views.append(
            ToolView(
                name=meta.name,
                description=meta.description or "",
                parameters_schema=params_schema,
                response_schema=None,
                metadata={"__li_tool_class": type(tool).__name__},
            )
        )
    return CaptureResult(
        framework="llamaindex",
        framework_version=version,
        views=views,
        notes="FunctionTool via llama_index.tools.mcp.McpToolSpec.",
    )


async def capture_pydantic_ai(spec: ServerSpec) -> CaptureResult:
    """Pydantic AI via `pydantic_ai.mcp.MCPServerStdio` or `MCPServerStreamableHTTP`."""
    import warnings

    version = _pkg_version("pydantic-ai-slim") or _pkg_version("pydantic-ai")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        if spec.kind == "stdio":
            from pydantic_ai.mcp import MCPServerStdio

            mcp_server = MCPServerStdio(spec.command or "", args=list(spec.args))
        else:
            from pydantic_ai.mcp import MCPServerStreamableHTTP

            mcp_server = MCPServerStreamableHTTP(url=spec.url, headers=spec.headers_dict)

        async with mcp_server:
            tools = await mcp_server.list_tools()
            views: list[ToolView] = []
            for tool in tools:
                input_schema = _normalize_schema(getattr(tool, "inputSchema", None))
                output_schema_raw = getattr(tool, "outputSchema", None)
                output_schema = _normalize_schema(output_schema_raw) if output_schema_raw else None
                meta = dict(getattr(tool, "meta", None) or {})
                meta["__pa_tool_class"] = type(tool).__name__
                views.append(
                    ToolView(
                        name=tool.name,
                        description=tool.description or "",
                        parameters_schema=input_schema,
                        response_schema=output_schema,
                        metadata=meta,
                    )
                )
            return CaptureResult(
                framework="pydantic-ai",
                framework_version=version,
                views=views,
                notes="mcp.types.Tool via pydantic_ai.mcp.MCPServer*.list_tools().",
            )


async def capture_ag2(spec: ServerSpec) -> CaptureResult:
    """AG2 (formerly AutoGen) via `autogen.mcp.MCPClient.load_mcp_toolkit(session)`."""
    from autogen.mcp.mcp_client import MCPClient

    version = _pkg_version("ag2")

    async with _session(spec) as session:
        toolkit = await MCPClient.load_mcp_toolkit(
            session,
            use_mcp_tools=True,
            use_mcp_resources=False,
            resource_download_folder=None,
        )
        views: list[ToolView] = []
        for tool in toolkit.tools:
            schema = _normalize_schema(getattr(tool, "parameters_json_schema", None))
            description = getattr(tool, "description", "") or ""
            if not description and getattr(tool, "func", None):
                description = getattr(tool.func, "__doc__", "") or ""
            views.append(
                ToolView(
                    name=tool.name,
                    description=description,
                    parameters_schema=schema,
                    response_schema=None,
                    metadata={"__ag2_tool_class": type(tool).__name__},
                )
            )
        return CaptureResult(
            framework="ag2",
            framework_version=version,
            views=views,
            notes="AG2 Tool via autogen.mcp.MCPClient.load_mcp_toolkit.",
        )


async def capture_crewai(spec: ServerSpec) -> CaptureResult:
    """CrewAI via `crewai-tools.MCPServerAdapter`.

    The adapter is synchronous; we run it in a thread to keep an async surface.
    """
    from crewai_tools import MCPServerAdapter

    version = _pkg_version("crewai-tools")

    def _collect() -> list[ToolView]:
        if spec.kind == "stdio":
            params = StdioServerParameters(command=spec.command or "", args=list(spec.args))
            adapter_input = params
        else:
            adapter_input = {
                "url": spec.url,
                "transport": "streamable-http",
                "headers": spec.headers_dict,
            }
        adapter = MCPServerAdapter(adapter_input)
        try:
            views: list[ToolView] = []
            for tool in adapter.tools:
                schema = _normalize_schema(tool.args_schema)
                views.append(
                    ToolView(
                        name=tool.name,
                        description=tool.description or "",
                        parameters_schema=schema,
                        response_schema=None,
                        metadata={"__crewai_tool_class": type(tool).__name__},
                    )
                )
            return views
        finally:
            adapter.stop()

    views = await asyncio.to_thread(_collect)
    return CaptureResult(
        framework="crewai",
        framework_version=version,
        views=views,
        notes="CrewAIMCPTool via crewai_tools.MCPServerAdapter.",
    )


ALL_CAPTURES: dict[str, CaptureFn] = {
    "mcp-server": capture_server_announcement,
    "langchain": capture_langchain,
    "llamaindex": capture_llamaindex,
    "pydantic-ai": capture_pydantic_ai,
    "ag2": capture_ag2,
    "crewai": capture_crewai,
}
