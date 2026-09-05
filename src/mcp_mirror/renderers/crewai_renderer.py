"""CrewAI renderer (DESIGN.md section 8).

Loads tools through ``crewai_tools``' ``MCPServerAdapter`` (the real adapter) and
captures each adapted CrewAI tool's name, description, and ``args_schema`` serialized
to JSON Schema. This is a framework tool object, not a captured provider request.
"""

from __future__ import annotations

from importlib import util
from typing import Any

from ..models import RendererEvidence, ToolRep
from ..normalize import normalize_function_tool
from ..source import ServerHandle
from . import RenderError
from ._common import dist_version

ID = "crewai"
REQUIRES = ("crewai_tools",)


def available() -> bool:
    return util.find_spec("crewai_tools") is not None


def get_renderer() -> "CrewAIRenderer":
    return CrewAIRenderer()


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
