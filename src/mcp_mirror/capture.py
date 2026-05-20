"""Live framework captures.

Each capture connects to a *real* MCP server via stdio, loads its tools through
the real framework adapter, introspects what the adapter would expose to the
LLM, and returns a ToolView. No simulation: this is the framework's actual
behavior on the framework's actual code path.

Captures are pure-introspection — they don't need LLM credentials. To validate
that the captured view matches what an LLM API receives at the wire level,
see `llm_validate.py` (requires OPENAI_API_KEY).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from importlib import metadata
from typing import Awaitable, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_mirror.types import ToolView


def _pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@dataclass
class CaptureResult:
    framework: str
    framework_version: str | None
    views: list[ToolView]
    notes: str = ""


CaptureFn = Callable[[StdioServerParameters], Awaitable[CaptureResult]]


async def capture_server_announcement(params: StdioServerParameters) -> CaptureResult:
    """The ground-truth view: what the MCP server itself announces."""
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.list_tools()
            views: list[ToolView] = []
            for t in result.tools:
                meta = dict(t.meta) if getattr(t, "meta", None) else {}
                # _meta lives at the protocol level; surface it on the ToolView
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
                framework_version=None,
                views=views,
                notes="Direct MCP server announcement via the official Python SDK.",
            )


async def capture_langchain(params: StdioServerParameters) -> CaptureResult:
    """What langchain-mcp-adapters hands to a LangChain agent.

    LangChain's MCP adapter (as of langchain-mcp-adapters 0.1+) preserves the
    raw JSON Schema on `tool.args_schema` as a dict — not a Pydantic model.
    The `tool_call_schema` is the same dict with the description embedded.
    """
    from langchain_mcp_adapters.tools import load_mcp_tools

    version = _pkg_version("langchain-mcp-adapters")

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            lc_tools = await load_mcp_tools(session)
            views: list[ToolView] = []
            for tool in lc_tools:
                schema = _normalize_schema(tool.args_schema)
                views.append(
                    ToolView(
                        name=tool.name,
                        description=tool.description or "",
                        parameters_schema=schema,
                        response_schema=None,  # LangChain has no response schema concept
                        metadata={"__lc_tool_class": type(tool).__name__},
                    )
                )
            return CaptureResult(
                framework="langchain",
                framework_version=version,
                views=views,
                notes="StructuredTool via langchain_mcp_adapters.load_mcp_tools.",
            )


async def capture_llamaindex(params: StdioServerParameters) -> CaptureResult:
    """What llama-index-tools-mcp hands to a LlamaIndex agent."""
    from llama_index.tools.mcp import McpToolSpec, BasicMCPClient

    version = _pkg_version("llama-index-tools-mcp")

    # BasicMCPClient takes the command + args to launch a stdio MCP server.
    client = BasicMCPClient(params.command, args=list(params.args or []))
    spec = McpToolSpec(client=client)
    li_tools = await spec.to_tool_list_async()

    views: list[ToolView] = []
    for tool in li_tools:
        meta = tool.metadata
        fn_schema_cls = meta.fn_schema
        params_schema = _normalize_schema(fn_schema_cls)
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


async def capture_pydantic_ai(params: StdioServerParameters) -> CaptureResult:
    """What pydantic-ai presents to its agent for an MCP-backed toolset.

    Pydantic AI's MCP integration returns `mcp.types.Tool` objects verbatim —
    the raw MCP tool definitions with `inputSchema` and `outputSchema` intact.
    This is the most faithful of the four framework adapters.
    """
    import warnings
    from pydantic_ai.mcp import MCPServerStdio

    version = _pkg_version("pydantic-ai-slim") or _pkg_version("pydantic-ai")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        mcp_server = MCPServerStdio(params.command, args=list(params.args or []))
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
                notes="mcp.types.Tool via pydantic_ai.mcp.MCPServerStdio.list_tools() — raw passthrough.",
            )


def _normalize_schema(schema) -> dict:
    """Accept dict / Pydantic model / None and return a JSON Schema dict."""
    if schema is None:
        return {}
    if isinstance(schema, dict):
        return dict(schema)
    if hasattr(schema, "model_json_schema"):  # Pydantic v2
        return schema.model_json_schema()
    if hasattr(schema, "schema"):  # Pydantic v1
        return schema.schema()
    return {}


async def capture_ag2(params: StdioServerParameters) -> CaptureResult:
    """What AG2 (formerly AutoGen) hands to an agent for an MCP toolset.

    AG2's `MCPClient.load_mcp_toolkit` calls `convert_tool` for each MCP tool,
    creating an AG2 `Tool` with `parameters_json_schema = mcp_tool.inputSchema`.
    The input schema is passed through; outputSchema and _meta are not preserved.
    """
    from autogen.mcp.mcp_client import MCPClient

    version = _pkg_version("ag2")

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            toolkit = await MCPClient.load_mcp_toolkit(
                session,
                use_mcp_tools=True,
                use_mcp_resources=False,
                resource_download_folder=None,
            )
            views: list[ToolView] = []
            for tool in toolkit.tools:
                schema = _normalize_schema(getattr(tool, "parameters_json_schema", None))
                # AG2's Tool wraps a name/description/func; description is on the func or on the Tool itself.
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


async def capture_crewai(params: StdioServerParameters) -> CaptureResult:
    """What crewai-tools hands to a CrewAI agent.

    CrewAI's MCPServerAdapter wraps each MCP tool in a CrewAIMCPTool. The schema
    goes through mcpadapt + Pydantic model generation, which introduces $defs
    blocks and structural reorganization. CrewAI also extends the tool
    description with usage guidance text — sometimes 5x the original length.

    Note: MCPServerAdapter is sync, not async, so we run it in a thread to keep
    a uniform async surface in this module.
    """
    from crewai_tools import MCPServerAdapter

    version = _pkg_version("crewai-tools")

    def _collect() -> list[ToolView]:
        adapter = MCPServerAdapter(params)
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
        notes="CrewAIMCPTool via crewai_tools.MCPServerAdapter (sync, run in thread).",
    )


ALL_CAPTURES: dict[str, CaptureFn] = {
    "mcp-server": capture_server_announcement,
    "langchain": capture_langchain,
    "llamaindex": capture_llamaindex,
    "pydantic-ai": capture_pydantic_ai,
    "ag2": capture_ag2,
    "crewai": capture_crewai,
}


def run(framework: str, params: StdioServerParameters) -> CaptureResult:
    """Synchronous wrapper for convenience."""
    fn = ALL_CAPTURES[framework]
    return asyncio.run(fn(params))
