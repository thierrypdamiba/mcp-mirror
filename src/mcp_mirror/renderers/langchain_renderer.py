"""LangChain renderer (DESIGN.md section 8).

Loads tools with ``langchain-mcp-adapters`` (the real adapter) and then runs each
through ``langchain_core.utils.function_calling.convert_to_openai_tool``. The result
is an OpenAI-compatible tool dictionary. This renderer does not bind a chat model or
capture a serialized provider request, so it reports that boundary without claiming
stronger provider evidence.
"""

from __future__ import annotations

from importlib import util
from typing import Any

import anyio

from ..models import RendererEvidence, ResultBoundary, ResultRep, ToolRep
from ..normalize import normalize_framework_result, normalize_function_tool
from ..source import ServerHandle
from . import RenderError
from ._common import dist_version

ID = "langchain"
REQUIRES = ("langchain_mcp_adapters", "langchain_core")


def available() -> bool:
    return all(util.find_spec(mod) is not None for mod in REQUIRES)


def get_renderer() -> "LangChainRenderer":
    return LangChainRenderer()


def _block_of(item: Any) -> dict[str, Any]:
    """Classify one returned item by what the agent can actually tell it is."""

    if isinstance(item, str):
        return {"type": "text", "text": item}
    if isinstance(item, dict):
        return item
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:  # noqa: BLE001
            pass
    return {"type": type(item).__name__}


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

        return self._to_reps(tools)

    # LangChain is the one adapter measured here whose result boundaries disagree.
    # `load_mcp_tools` builds the StructuredTool with
    # `handle_tool_error=_handle_mcp_tool_error`, and an `isError` result raises the
    # internal `_MCPToolExecutionError`. Invoked with a plain argument dict the tool
    # returns the handler's content blocks, so the failure reads as ordinary text.
    # Invoked with a ToolCall, which is the shape an agent and ToolNode use, the same
    # call returns a ToolMessage carrying `status="error"`. Both are published.
    DEFAULT_RESULT_BOUNDARY = "direct"

    def result_boundaries(self) -> list[ResultBoundary]:
        return [
            ResultBoundary(
                id="direct",
                label="Direct tool invocation",
                capture_api="langchain_core.tools.StructuredTool.ainvoke(dict)",
                capture_object="the tool return value, before any ToolMessage is built",
                agent_path=False,
            ),
            ResultBoundary(
                id="agent",
                label="Agent tool invocation",
                capture_api="langchain_core.tools.StructuredTool.ainvoke(ToolCall)",
                capture_object="the ToolMessage an agent or ToolNode puts in the message list",
                agent_path=True,
                limitation=(
                    "The ToolMessage is built by langchain_core from the same call a "
                    "ToolNode makes. No chat model was bound and no provider request "
                    "was captured."
                ),
            ),
        ]

    def render_result(
        self,
        server: ServerHandle,
        tool: str,
        arguments: dict[str, Any],
        boundary: str | None = None,
    ) -> ResultRep:
        """Invoke one tool and capture one declared framework-result boundary."""

        return anyio.run(
            self._render_result_async,
            server,
            tool,
            arguments,
            boundary or self.DEFAULT_RESULT_BOUNDARY,
        )

    async def _render_result_async(
        self, server: ServerHandle, tool: str, arguments: dict[str, Any], boundary: str
    ) -> ResultRep:
        from langchain_mcp_adapters.client import create_session
        from langchain_mcp_adapters.tools import load_mcp_tools

        if boundary not in {"direct", "agent"}:
            raise RenderError(f"langchain renderer has no result boundary {boundary!r}")

        connection = _connection(server)
        async with create_session(connection) as session:
            await session.initialize()
            tools = await load_mcp_tools(session, connection=connection, server_name="src")
            target = next((t for t in tools if getattr(t, "name", None) == tool), None)
            if target is None:
                available = sorted(getattr(t, "name", "?") for t in tools)
                raise RenderError(
                    f"langchain renderer found no tool named {tool!r} (has: {available})"
                )
            # A ToolCall is what makes BaseTool.ainvoke return a ToolMessage, which is
            # the object an agent reads. A plain dict returns the raw tool value.
            payload: Any = (
                arguments
                if boundary == "direct"
                else {
                    "name": tool,
                    "args": dict(arguments),
                    "id": "mcp_mirror_result_capture",
                    "type": "tool_call",
                }
            )
            try:
                returned = await target.ainvoke(payload)
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

        langchain-mcp-adapters declares non-text tools as ``content_and_artifact``, so
        a call can come back as a ``(content, artifact)`` tuple where the artifact
        carries the blocks that did not fit into the content string. Both halves are
        recorded, because which half a block landed in is the finding.
        """

        # At the agent boundary the adapter's content and artifact arrive already
        # assembled into a ToolMessage. `status` is the field that carries MCP's
        # isError across that boundary, so it is read before the shape is unpacked.
        status = getattr(returned, "status", None)
        if status is not None and hasattr(returned, "content"):
            message = returned
            blocks = [_block_of(item) for item in message.content] if isinstance(
                message.content, (list, tuple)
            ) else []
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                blocks=blocks,
                text=message.content if isinstance(message.content, str) else None,
                is_error=status == "error",
                raw=repr(message)[:2000],
            )

        artifact = None
        if isinstance(returned, tuple) and len(returned) == 2:
            returned, artifact = returned

        blocks = []
        if isinstance(artifact, (list, tuple)):
            blocks = [_block_of(item) for item in artifact]
        elif artifact is not None:
            blocks = [_block_of(artifact)]

        if isinstance(returned, str):
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                blocks=blocks,
                text=returned,
                raw=repr((returned, artifact))[:2000],
            )
        if isinstance(returned, dict):
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                blocks=blocks,
                structured_content=returned,
                raw=repr((returned, artifact))[:2000],
            )
        if isinstance(returned, (list, tuple)):
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                blocks=blocks or [_block_of(item) for item in returned],
                raw=repr((returned, artifact))[:2000],
            )
        return normalize_framework_result(
            tool=tool,
            origin=self.id,
            blocks=blocks,
            text=str(returned),
            raw=repr((returned, artifact))[:2000],
        )

    def _to_reps(self, tools) -> list[ToolRep]:
        from langchain_core.utils.function_calling import convert_to_openai_tool

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
