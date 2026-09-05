"""LangChain renderer (DESIGN.md section 8).

Loads tools with ``langchain-mcp-adapters`` (the real adapter) and then runs each
through ``langchain_core.utils.function_calling.convert_to_openai_tool``, the exact
function object ``bind_tools`` would send to the model. That payload is what the LLM
receives, so we map it straight into a ``ToolRep``.
"""

from __future__ import annotations

from importlib import util

import anyio

from ..models import ToolRep
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

    def render(self, server: ServerHandle) -> list[ToolRep]:
        try:
            return anyio.run(self._render_async, server)
        except Exception as exc:  # noqa: BLE001
            raise RenderError(f"langchain renderer failed: {exc}") from exc

    async def _render_async(self, server: ServerHandle) -> list[ToolRep]:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({"src": _connection(server)})
        tools = await client.get_tools()

        reps: list[ToolRep] = []
        for tool in tools:
            # convert_to_openai_tool is exactly the model-facing payload bind_tools sends.
            oai_tool = convert_to_openai_tool(tool)
            # langchain-mcp-adapters keeps the MCP annotations on StructuredTool.metadata,
            # so they are retained by the framework even though they never reach the model.
            retained = {k: v for k, v in (getattr(tool, "metadata", None) or {}).items() if v is not None}
            metadata = {"annotations": retained} if retained else {}
            reps.append(normalize_function_tool(oai_tool, origin=self.id, framework_metadata=metadata))
        return reps
