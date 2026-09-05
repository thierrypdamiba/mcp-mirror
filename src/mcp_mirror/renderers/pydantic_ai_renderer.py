"""Pydantic AI renderer (DESIGN.md section 8).

Connects through the supported ``pydantic_ai.mcp.MCPToolset`` API and reads the
tool definitions the agent would expose. Each Pydantic AI
``ToolDefinition`` carries ``name``, ``description`` and ``parameters_json_schema`` -
that schema is what the model receives.

Pydantic AI's MCP API has moved across releases; this renderer tries the documented
entry points in order and raises ``RenderError`` if none are available, so a version
skew is reported cleanly rather than crashing the scan.
"""

from __future__ import annotations

from importlib import util
from typing import Any

import anyio

from ..models import ToolRep
from ..normalize import normalize_function_tool
from ..source import ServerHandle
from . import RenderError
from ._common import dist_version

ID = "pydantic_ai"
REQUIRES = ("pydantic_ai",)


def available() -> bool:
    return util.find_spec("pydantic_ai") is not None and util.find_spec("pydantic_ai.mcp") is not None


def get_renderer() -> "PydanticAIRenderer":
    return PydanticAIRenderer()


class PydanticAIRenderer:
    id = ID

    def versions(self) -> dict:
        version = dist_version("pydantic-ai-slim")
        if version == "unknown":
            version = dist_version("pydantic-ai")
        return {"framework": version, "adapter": version}

    def render(self, server: ServerHandle) -> list[ToolRep]:
        try:
            return anyio.run(self._render_async, server)
        except RenderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RenderError(f"pydantic_ai renderer failed: {exc}") from exc

    async def _render_async(self, server: ServerHandle) -> list[ToolRep]:
        toolset = self._build_server(server)
        async with toolset:
            tools = await self._list_tools(toolset)
        return [self._to_rep(t) for t in tools]

    def _build_server(self, server: ServerHandle):
        from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
        from pydantic_ai.mcp import MCPToolset

        if server.transport == "http":
            transport = StreamableHttpTransport(
                url=server.url,
                headers=dict(server.headers) or None,
            )
        else:
            transport = StdioTransport(
                command=server.command,
                args=list(server.args),
            )
        return MCPToolset(transport)

    async def _list_tools(self, mcp_server) -> list[Any]:
        # Preferred: get_tools() reports the exact ToolDefinitions the agent exposes,
        # including the metadata where Pydantic AI retains MCP annotations. The MCP
        # toolset does not use the RunContext, so None is accepted; if a future version
        # does, fall back to the raw tool list (which still carries inputSchema + annotations).
        get_tools = getattr(mcp_server, "get_tools", None)
        if callable(get_tools):
            try:
                result = await get_tools(None)
                tools = list(result.values()) if isinstance(result, dict) else list(result)
                if tools:
                    return tools
            except (TypeError, AttributeError):
                pass

        list_tools = getattr(mcp_server, "list_tools", None)
        if callable(list_tools):
            return list(await list_tools())

        raise RenderError("pydantic_ai MCP server exposes no known tool-listing method")

    def _to_rep(self, tool: Any) -> ToolRep:
        tool_def = getattr(tool, "tool_def", None)
        if tool_def is not None:
            name = getattr(tool_def, "name", None)
            description = getattr(tool_def, "description", None)
            parameters = getattr(tool_def, "parameters_json_schema", None) or {}
            metadata = getattr(tool_def, "metadata", None) or {}
            retained = metadata.get("annotations") or {}
        else:
            # Fallback: a raw MCP types.Tool.
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", None)
            parameters = getattr(tool, "inputSchema", None) or {}
            retained = self._annotations_of(getattr(tool, "annotations", None))

        retained = {k: v for k, v in (retained or {}).items() if v is not None}
        framework_metadata = {"annotations": retained} if retained else {}
        payload = {"name": name, "description": description, "parameters": parameters}
        return normalize_function_tool(payload, origin=self.id, framework_metadata=framework_metadata)

    @staticmethod
    def _annotations_of(annotations: Any) -> dict:
        if annotations is None:
            return {}
        dump = getattr(annotations, "model_dump", None)
        if callable(dump):
            return dump()
        return annotations if isinstance(annotations, dict) else {}
