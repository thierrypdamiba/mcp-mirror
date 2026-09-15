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

from ..models import RendererEvidence, ResultRep, ToolRep
from ..normalize import normalize_framework_result, normalize_function_tool
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
        negotiated_version = getattr(
            self,
            "_negotiated_mcp_spec_version",
            None,
        )
        return RendererEvidence(
            capture_api="agents.mcp.util.MCPUtil.to_function_tool",
            capture_object="agents.tool.FunctionTool",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=negotiated_version,
            protocol_version_evidence=(
                "protocol version exposed by the MCPServer client session"
                if negotiated_version and negotiated_version >= "2026-07-28"
                else "protocolVersion exposed by MCPServer.server_initialize_result"
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
            session = getattr(mcp_server, "session", None)
            self._negotiated_mcp_spec_version = (
                getattr(initialize_result, "protocolVersion", None)
                or getattr(session, "protocol_version", None)
            )
            if not self._negotiated_mcp_spec_version:
                raise RenderError(
                    "openai_agents renderer could not establish the negotiated "
                    "MCP protocol version"
                )
            mcp_tools = await mcp_server.list_tools()
            reps: list[ToolRep] = []
            for tool in mcp_tools:
                function_tool = MCPUtil.to_function_tool(tool, mcp_server, False)
                reps.append(self._to_rep(function_tool))
            return reps

    # Result capture boundary: `invoke_mcp_tool` returns the SDK's `ToolOutput`, which
    # is exactly what the agent loop feeds back to the model.
    result_capture_api = "agents.mcp.util.MCPUtil.invoke_mcp_tool"
    result_capture_object = "the Agents SDK ToolOutput handed back to the model"

    def render_result(
        self, server: ServerHandle, tool: str, arguments: dict[str, Any]
    ) -> ResultRep:
        """Invoke one tool through the adapter and capture what the agent receives."""

        return anyio.run(self._render_result_async, server, tool, arguments)

    async def _render_result_async(
        self, server: ServerHandle, tool: str, arguments: dict[str, Any]
    ) -> ResultRep:
        import json as _json

        from agents.mcp.util import MCPUtil
        from agents.run_context import RunContextWrapper

        mcp_server = self._build_server(server)
        async with mcp_server:
            mcp_tool = next(
                (t for t in await mcp_server.list_tools() if t.name == tool), None
            )
            if mcp_tool is None:
                raise RenderError(f"openai_agents renderer could not find tool {tool!r}")
            try:
                output = await MCPUtil.invoke_mcp_tool(
                    mcp_server, mcp_tool, RunContextWrapper(context=None), _json.dumps(arguments)
                )
            except Exception as exc:  # noqa: BLE001 - the failure mode is the observation
                # The SDK raises on a tool that reported `isError`, so the agent learns
                # of the failure through an exception rather than a flag on a result.
                return normalize_framework_result(
                    tool=tool,
                    origin=self.id,
                    is_error=True,
                    text=f"{type(exc).__name__}: {exc}",
                    raw=repr(exc)[:2000],
                )
        return self._result_to_rep(tool, output)

    def _result_to_rep(self, tool: str, output: Any) -> ResultRep:
        """Map the SDK's ToolOutput onto the common result shape.

        Every branch of `invoke_mcp_tool` produces text: structured content is
        `json.dumps`-ed into a string, and each non-text content block is re-serialized
        as JSON inside a `type: "text"` item. Nothing that reaches the model retains the
        kind it had on the wire, so every block is recorded as text.
        """

        if isinstance(output, str):
            return normalize_framework_result(
                tool=tool, origin=self.id, text=output, raw=output[:2000]
            )
        items = output if isinstance(output, list) else [output]
        blocks = []
        for item in items:
            entry = item if isinstance(item, dict) else {}
            blocks.append({"type": entry.get("type", "text"), "text": entry.get("text")})
        return normalize_framework_result(
            tool=tool, origin=self.id, blocks=blocks, raw=repr(output)[:2000]
        )

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
