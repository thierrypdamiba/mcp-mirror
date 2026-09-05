"""OpenAI Agents SDK renderer (DESIGN.md section 8).

Drives the SDK's real MCP conversion: ``MCPUtil.to_function_tool`` is exactly what the
Agent uses to turn an MCP tool into the ``FunctionTool`` it sends the model, so its
``params_json_schema`` is what the LLM receives. The SDK keeps the MCP ``title`` (as
``_mcp_title``) on the tool but does not carry the behavioral hints (destructiveHint,
readOnlyHint, …), so, like CrewAI, those are not retained on the tool you register.
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
        # The SDK keeps only the MCP title on the FunctionTool; the behavioral hints are
        # not carried on the object you hand to the Agent, so they are not "retained".
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
