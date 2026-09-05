"""OpenAI Agents SDK renderer (DESIGN.md section 8).

Drives the SDK's real MCP conversion, ``MCPUtil.to_function_tool``, and captures the
resulting SDK ``FunctionTool``. This is the framework's model-tool object, not a
serialized provider request. The SDK keeps the MCP ``title`` (as ``_mcp_title``) on
that object but does not carry the behavioral hints (destructiveHint, readOnlyHint,
etc.).
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

ID = "openai_agents"
# The distribution is ``openai-agents``; it imports as the top-level package ``agents``.
REQUIRES = ("agents", "agents.mcp")


def available() -> bool:
    return all(util.find_spec(mod) is not None for mod in REQUIRES)


def get_renderer() -> "OpenAIAgentsRenderer":
    return OpenAIAgentsRenderer()


class OpenAIAgentsRenderer:
    id = ID

    def versions(self) -> dict:
        version = dist_version("openai-agents")
        return {"framework": version, "adapter": version}

    def evidence(self) -> RendererEvidence:
        return RendererEvidence(
            capture_api="agents.mcp.util.MCPUtil.to_function_tool",
            capture_object="agents.tool.FunctionTool",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=getattr(
                self,
                "_negotiated_mcp_spec_version",
                None,
            ),
            protocol_version_evidence=(
                "protocolVersion exposed by MCPServer.server_initialize_result"
            ),
            limitation=(
                "No Agents SDK model implementation or serialized provider request was captured."
            ),
        )

    def render(self, server: ServerHandle) -> list[ToolRep]:
        try:
            return anyio.run(self._render_async, server)
        except RenderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RenderError(f"openai_agents renderer failed: {exc}") from exc

    async def _render_async(self, server: ServerHandle) -> list[ToolRep]:
        from agents.mcp.util import MCPUtil

        mcp_server = self._build_server(server)
        async with mcp_server:
            initialize_result = mcp_server.server_initialize_result
            self._negotiated_mcp_spec_version = initialize_result.protocolVersion
            mcp_tools = await mcp_server.list_tools()
            reps: list[ToolRep] = []
            for tool in mcp_tools:
                function_tool = MCPUtil.to_function_tool(tool, mcp_server, False)
                reps.append(self._to_rep(function_tool))
            return reps

    def _build_server(self, server: ServerHandle):
        from agents.mcp import MCPServerStdio, MCPServerStreamableHttp

        if server.transport == "http":
            params: dict[str, Any] = {"url": server.url}
            if server.headers:
                params["headers"] = dict(server.headers)
            return MCPServerStreamableHttp(params=params, client_session_timeout_seconds=20)
        return MCPServerStdio(
            params={"command": server.command, "args": list(server.args)},
            client_session_timeout_seconds=20,
        )

    def _to_rep(self, function_tool: Any) -> ToolRep:
        # The SDK keeps only the MCP title on the captured FunctionTool; the
        # behavioral hints are not carried on that object.
        retained: dict[str, Any] = {}
        title = getattr(function_tool, "_mcp_title", None)
        if title:
            retained["title"] = title
        framework_metadata = {"annotations": retained} if retained else {}
        payload = {
            "name": getattr(function_tool, "name", None),
            "description": getattr(function_tool, "description", None),
            "parameters": getattr(function_tool, "params_json_schema", None) or {},
        }
        return normalize_function_tool(payload, origin=self.id, framework_metadata=framework_metadata)
