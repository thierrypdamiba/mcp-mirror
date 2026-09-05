"""Pydantic AI renderer (DESIGN.md section 8).

Connects through the supported ``pydantic_ai.mcp.MCPToolset`` API and reads the
tool definitions the agent would expose. Each Pydantic AI
``ToolDefinition`` carries ``name``, ``description`` and
``parameters_json_schema``. This is the framework tool-definition boundary, before
provider-specific request serialization.
"""

from __future__ import annotations

from importlib import util
from typing import Any

import anyio

from ..models import RendererEvidence, ToolRep
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

    def evidence(self) -> RendererEvidence:
        return RendererEvidence(
            capture_api="pydantic_ai.mcp.MCPToolset.get_tools",
            capture_object="pydantic_ai.tools.ToolDefinition",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=getattr(
                self,
                "_negotiated_mcp_spec_version",
                None,
            ),
            protocol_version_evidence=(
                "protocolVersion exposed by MCPToolset.client.initialize_result"
            ),
            limitation=(
                "No Pydantic AI model adapter or serialized provider request was captured."
            ),
        )

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
            initialize_result = toolset.client.initialize_result
            self._negotiated_mcp_spec_version = initialize_result.protocolVersion
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
        # Setting max_retries avoids constructing an Agent RunContext solely to list
        # the ToolDefinition objects. No model is created or called.
        return MCPToolset(transport, max_retries=0)

    async def _list_tools(self, mcp_server) -> list[Any]:
        # get_tools() constructs the exact ToolDefinition objects declared as this
        # renderer's capture boundary. max_retries is fixed on the toolset, so the
        # RunContext is not consulted and no Agent or model is needed.
        get_tools = getattr(mcp_server, "get_tools", None)
        if not callable(get_tools):
            raise RenderError("pydantic_ai MCPToolset exposes no get_tools method")
        result = await get_tools(None)
        return list(result.values()) if isinstance(result, dict) else list(result)

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
