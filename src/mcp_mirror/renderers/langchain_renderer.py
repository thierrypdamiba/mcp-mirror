"""LangChain renderer (DESIGN.md section 8).

Loads tools with ``langchain-mcp-adapters`` (the real adapter) and then runs each
through ``langchain_core.utils.function_calling.convert_to_openai_tool``. The result
is an OpenAI-compatible tool dictionary. This renderer does not bind a chat model or
capture a serialized provider request, so it reports that boundary without claiming
stronger provider evidence.
"""

from __future__ import annotations

from importlib import util

import anyio

from ..models import RendererEvidence, ToolRep
from ..normalize import normalize_function_tool
from ..source import ServerHandle
from . import RenderError
from ._common import dist_version

ID = "langchain"
REQUIRES = ("langchain_mcp_adapters", "langchain_core")


def available() -> bool:
    return all(util.find_spec(mod) is not None for mod in REQUIRES)


def get_renderer() -> "LangChainRenderer":
    return LangChainRenderer()


def _connection(handle: ServerHandle) -> dict:
    if handle.transport == "http":
        conn = {"url": handle.url, "transport": "streamable_http"}
        if handle.headers:
            conn["headers"] = dict(handle.headers)
        return conn
    return {"command": handle.command, "args": list(handle.args), "transport": "stdio"}


class LangChainRenderer:
    id = ID

    def versions(self) -> dict:
        return {
            "framework": dist_version("langchain-mcp-adapters"),
            "adapter": dist_version("langchain-core"),
        }

    def evidence(self) -> RendererEvidence:
        return RendererEvidence(
            capture_api="langchain_core.utils.function_calling.convert_to_openai_tool",
            capture_object="OpenAI-compatible function-tool dictionary",
            capture_stage="provider_format",
            provider_request_captured=False,
            negotiated_mcp_spec_version=getattr(
                self,
                "_negotiated_mcp_spec_version",
                None,
            ),
            protocol_version_evidence=(
                "protocolVersion returned by ClientSession.initialize inside the "
                "langchain-mcp-adapters session"
            ),
            limitation=(
                "No chat model was bound and no serialized provider request was captured."
            ),
        )

    def render(self, server: ServerHandle) -> list[ToolRep]:
        try:
            return anyio.run(self._render_async, server)
        except Exception as exc:  # noqa: BLE001
            raise RenderError(f"langchain renderer failed: {exc}") from exc

    async def _render_async(self, server: ServerHandle) -> list[ToolRep]:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from langchain_mcp_adapters.client import create_session
        from langchain_mcp_adapters.tools import load_mcp_tools

        connection = _connection(server)
        async with create_session(connection) as session:
            initialize_result = await session.initialize()
            self._negotiated_mcp_spec_version = initialize_result.protocolVersion
            tools = await load_mcp_tools(
                session,
                connection=connection,
                server_name="src",
            )

        reps: list[ToolRep] = []
        for tool in tools:
            # Capture the provider-shaped conversion output, not a provider request.
            oai_tool = convert_to_openai_tool(tool)
            # langchain-mcp-adapters keeps the MCP annotations on StructuredTool.metadata,
            # separate from the provider-shaped dictionary captured above.
            retained = {k: v for k, v in (getattr(tool, "metadata", None) or {}).items() if v is not None}
            metadata = {"annotations": retained} if retained else {}
            reps.append(normalize_function_tool(oai_tool, origin=self.id, framework_metadata=metadata))
        return reps
