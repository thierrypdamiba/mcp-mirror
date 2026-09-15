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

from ..models import RendererEvidence, ResultRep, ToolRep
from ..normalize import normalize_framework_result, normalize_function_tool
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
        negotiated_version = getattr(
            self,
            "_negotiated_mcp_spec_version",
            None,
        )
        return RendererEvidence(
            capture_api="pydantic_ai.mcp.MCPToolset.get_tools",
            capture_object="pydantic_ai.tools.ToolDefinition",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=negotiated_version,
            protocol_version_evidence=(
                "protocol version exposed by MCPToolset.client"
                if negotiated_version and negotiated_version >= "2026-07-28"
                else "protocolVersion exposed by MCPToolset.client.initialize_result"
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
            client = toolset.client
            initialize_result = getattr(client, "initialize_result", None)
            self._negotiated_mcp_spec_version = (
                getattr(initialize_result, "protocolVersion", None)
                or getattr(client, "protocol_version", None)
            )
            if not self._negotiated_mcp_spec_version:
                raise RenderError(
                    "pydantic_ai renderer could not establish the negotiated "
                    "MCP protocol version"
                )
        return [self._to_rep(t) for t in tools]

    # Result capture boundary: direct MCPToolset invocation before the surrounding
    # agent serializes a model request. The exact API is recorded so this is not
    # confused with provider-payload capture.
    result_capture_api = "pydantic_ai.mcp.MCPToolset.direct_call_tool"
    result_capture_object = "direct toolset result before model-request serialization"

    def render_result(
        self, server: ServerHandle, tool: str, arguments: dict[str, Any]
    ) -> ResultRep:
        """Invoke one tool and capture the declared framework-result boundary."""

        return anyio.run(self._render_result_async, server, tool, arguments)

    async def _render_result_async(
        self, server: ServerHandle, tool: str, arguments: dict[str, Any]
    ) -> ResultRep:
        toolset = self._build_server(server)
        try:
            returned = await toolset.direct_call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001 - the failure mode is the observation
            # A tool that reported failure through `isError` may surface here as a
            # raised exception instead, which is a different contract for the agent
            # rather than a scanner error, so it is recorded rather than propagated.
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                is_error=True,
                text=f"{type(exc).__name__}: {exc}",
                raw=repr(exc),
            )
        return self._result_to_rep(tool, returned)

    def _result_to_rep(self, tool: str, returned: Any) -> ResultRep:
        """Map whatever the adapter returned onto the common result shape.

        Pydantic AI returns the structured content when every content part is text and
        the mapped content blocks otherwise, so the same tool can hand the agent either
        a typed value or a list. Both shapes are recorded rather than normalized away.
        """

        if isinstance(returned, list):
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                blocks=[self._block_of(item) for item in returned],
                raw=repr(returned)[:2000],
            )
        if isinstance(returned, dict):
            return normalize_framework_result(
                tool=tool, origin=self.id, structured_content=returned, raw=returned
            )
        return normalize_framework_result(
            tool=tool, origin=self.id, text=str(returned), raw=repr(returned)[:2000]
        )

    @staticmethod
    def _block_of(item: Any) -> dict[str, Any]:
        """Classify one returned item by what the agent can actually tell it is.

        Pydantic AI maps several MCP content kinds onto a bare ``str``. Recording those
        as ``text`` is not a guess about the adapter's intent, it is the agent's view:
        nothing in a plain string distinguishes an embedded resource or a resource link
        from an ordinary text block, so the original kind is genuinely gone.
        """

        if isinstance(item, str):
            return {"type": "text", "text": item}

        media_type = getattr(item, "media_type", None) or ""
        if media_type.startswith("image/") or type(item).__name__ == "BinaryImage":
            return {"type": "image", "mimeType": media_type or None}
        if media_type.startswith("audio/"):
            return {"type": "audio", "mimeType": media_type}
        return {"type": type(item).__name__, "mimeType": media_type or None}

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
