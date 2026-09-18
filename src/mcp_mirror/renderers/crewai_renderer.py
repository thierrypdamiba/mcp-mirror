"""CrewAI renderer (DESIGN.md section 8).

Loads tools through ``crewai_tools``' ``MCPServerAdapter`` (the real adapter) and
captures each adapted CrewAI tool's name, description, and ``args_schema`` serialized
to JSON Schema. This is a framework tool object, not a captured provider request.
"""

from __future__ import annotations

from importlib import util
from typing import Any

from ..models import RendererEvidence, ResultBoundary, ResultRep, ToolRep
from ..normalize import normalize_framework_result, normalize_function_tool
from ..source import ServerHandle
from . import RenderError
from ._common import dist_version

ID = "crewai"
REQUIRES = ("crewai_tools",)


def available() -> bool:
    return util.find_spec("crewai_tools") is not None


def get_renderer() -> "CrewAIRenderer":
    return CrewAIRenderer()


def _block_of(item: Any) -> dict[str, Any]:
    """Classify one returned item by what the agent can actually tell it is.

    A bare ``str`` is recorded as text even when the server sent an image or an
    embedded resource, because nothing in a plain string distinguishes them: the
    original kind is genuinely gone by the time the agent reads it.
    """

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


class CrewAIRenderer:
    id = ID

    def versions(self) -> dict:
        return {"framework": dist_version("crewai-tools"), "adapter": dist_version("crewai")}

    def evidence(self) -> RendererEvidence:
        return RendererEvidence(
            capture_api="crewai_tools.MCPServerAdapter",
            capture_object="CrewAI BaseTool name, description, and args_schema",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=getattr(
                self,
                "_negotiated_mcp_spec_version",
                None,
            ),
            protocol_version_evidence=(
                "protocolVersion instrumented from ClientSession.initialize inside "
                "MCPServerAdapter"
            ),
            limitation=(
                "No CrewAI LLM serializer or serialized provider request was captured."
            ),
        )

    def render(self, server: ServerHandle) -> list[ToolRep]:
        try:
            return self._render(server)
        except RenderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RenderError(f"crewai renderer failed: {exc}") from exc

    def _render(self, server: ServerHandle) -> list[ToolRep]:
        from crewai_tools import MCPServerAdapter
        from mcp.client.session import ClientSession
        from unittest.mock import patch

        params = self._build_params(server)
        protocol_versions: list[str] = []
        original_initialize = ClientSession.initialize

        async def capture_initialize(session, *args, **kwargs):
            result = await original_initialize(session, *args, **kwargs)
            protocol_versions.append(result.protocolVersion)
            return result

        # MCPServerAdapter is a synchronous context manager yielding CrewAI tools.
        with patch.object(ClientSession, "initialize", capture_initialize):
            with MCPServerAdapter(params) as tools:
                reps = [self._to_rep(tool) for tool in tools]

        observed = set(protocol_versions)
        if len(observed) != 1:
            raise RenderError(
                "crewai renderer could not establish one negotiated MCP protocol "
                f"version (observed: {sorted(observed)})"
            )
        self._negotiated_mcp_spec_version = observed.pop()
        return reps

    # CrewAI's agent runtime reaches a tool through ToolUsage, which calls
    # CrewStructuredTool.invoke rather than BaseTool.run. Both are published because
    # they are genuinely different entry points, even though the adapter's own
    # CrewAIMCPTool._run reads only `result.content` and never `result.isError`, so
    # nothing downstream of it can reconstruct a signal it already discarded.
    DEFAULT_RESULT_BOUNDARY = "direct"

    def result_boundaries(self) -> list[ResultBoundary]:
        return [
            ResultBoundary(
                id="direct",
                label="Direct tool invocation",
                capture_api="crewai.tools.BaseTool.run",
                capture_object="the tool return value",
                agent_path=False,
            ),
            ResultBoundary(
                id="agent",
                label="Agent tool invocation",
                capture_api="crewai.tools.structured_tool.CrewStructuredTool.invoke",
                capture_object="the value ToolUsage hands back during a crew run",
                agent_path=True,
                limitation=(
                    "CrewStructuredTool.invoke is driven directly. No LLM was bound "
                    "and no crew was kicked off."
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

        from crewai_tools import MCPServerAdapter

        boundary = boundary or self.DEFAULT_RESULT_BOUNDARY
        if boundary not in {"direct", "agent"}:
            raise RenderError(f"crewai renderer has no result boundary {boundary!r}")

        params = self._build_params(server)
        with MCPServerAdapter(params) as tools:
            target = next((t for t in tools if getattr(t, "name", None) == tool), None)
            if target is None:
                available = sorted(getattr(t, "name", "?") for t in tools)
                raise RenderError(
                    f"crewai renderer found no tool named {tool!r} (has: {available})"
                )
            try:
                if boundary == "direct":
                    returned = target.run(**arguments)
                else:
                    returned = target.to_structured_tool().invoke(input=dict(arguments))
            except Exception as exc:  # noqa: BLE001 - the failure mode is the observation
                # A tool that reported failure through `isError` may surface here as a
                # raised exception instead. That is a different contract for the agent,
                # not a scanner error, so it is recorded rather than propagated.
                return normalize_framework_result(
                    tool=tool,
                    origin=self.id,
                    is_error=True,
                    text=f"{type(exc).__name__}: {exc}",
                    raw=repr(exc),
                )
        return self._result_to_rep(tool, returned)

    def _result_to_rep(self, tool: str, returned: Any) -> ResultRep:
        """Map whatever the adapter returned onto the common result shape."""

        if isinstance(returned, str):
            return normalize_framework_result(
                tool=tool, origin=self.id, text=returned, raw=returned[:2000]
            )
        if isinstance(returned, dict):
            return normalize_framework_result(
                tool=tool, origin=self.id, structured_content=returned, raw=returned
            )
        if isinstance(returned, (list, tuple)):
            return normalize_framework_result(
                tool=tool,
                origin=self.id,
                blocks=[_block_of(item) for item in returned],
                raw=repr(returned)[:2000],
            )
        return normalize_framework_result(
            tool=tool, origin=self.id, text=str(returned), raw=repr(returned)[:2000]
        )

    def _build_params(self, server: ServerHandle) -> Any:
        if server.transport == "http":
            params = {"url": server.url, "transport": "streamable-http"}
            if server.headers:
                params["headers"] = dict(server.headers)
            return params
        from mcp import StdioServerParameters

        return StdioServerParameters(command=server.command, args=list(server.args))

    def _to_rep(self, tool: Any) -> ToolRep:
        name = getattr(tool, "name", None)
        description = getattr(tool, "description", None)
        parameters = self._schema(tool)
        payload = {"name": name, "description": description, "parameters": parameters}
        return normalize_function_tool(payload, origin=self.id)

    @staticmethod
    def _schema(tool: Any) -> dict:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is None:
            return {}
        model_json_schema = getattr(args_schema, "model_json_schema", None)
        if callable(model_json_schema):
            try:
                return model_json_schema()
            except Exception:
                return {}
        schema_method = getattr(args_schema, "schema", None)
        if callable(schema_method):
            try:
                return schema_method()
            except Exception:
                return {}
        return {}
