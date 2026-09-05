"""Mastra renderer (DESIGN.md section 8).

Mastra is a TypeScript framework, so, to honor the cardinal rule of driving the
framework's *real* adapter (decision D1) rather than reimplementing it, this renderer
shells out to a small Node worker (``mastra_node/_mastra_worker.mjs``) that runs
Mastra's real ``@mastra/mcp`` client and reports the tool actions returned by
``MCPClient.listTools``. It does not run a model provider or capture a request.

Enable it once with:  ``cd src/mcp_mirror/renderers/mastra_node && npm install``
(requires Node on PATH). When the Node project is absent the renderer reports itself
unavailable, exactly like the Python optional extras.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..models import RendererEvidence, ToolRep
from ..normalize import normalize_function_tool
from ..source import ServerHandle
from . import RenderError

ID = "mastra"
_NODE_DIR = Path(__file__).parent / "mastra_node"
_WORKER = _NODE_DIR / "_mastra_worker.mjs"
_MASTRA_PKG = _NODE_DIR / "node_modules" / "@mastra" / "mcp"
_TIMEOUT_SECONDS = 90


def available() -> bool:
    return shutil.which("node") is not None and _WORKER.exists() and _MASTRA_PKG.exists()


def get_renderer() -> "MastraRenderer":
    return MastraRenderer()


class MastraRenderer:
    id = ID

    def versions(self) -> dict:
        version = "unknown"
        try:
            version = json.loads((_MASTRA_PKG / "package.json").read_text()).get("version", "unknown")
        except Exception:
            pass
        return {"framework": version, "adapter": f"node {_node_version()}"}

    def evidence(self) -> RendererEvidence:
        return RendererEvidence(
            capture_api="@mastra/mcp MCPClient.listTools",
            capture_object="Mastra Tool action returned by listTools",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=getattr(
                self,
                "_negotiated_mcp_spec_version",
                None,
            ),
            protocol_version_evidence=(
                "protocolVersion observed from the pinned @modelcontextprotocol/client "
                "instance used by MCPClient.listTools"
            ),
            limitation=(
                "The worker extracts JSON Schema from Mastra's Standard Schema wrapper; "
                "the negotiated protocol field is not a public @mastra/mcp API; no AI "
                "SDK provider adapter or serialized request was captured."
            ),
        )

    def render(self, server: ServerHandle) -> list[ToolRep]:
        config = self._config(server)
        try:
            # Run from the caller's cwd (NOT the node dir) so a stdio server given by a
            # relative command resolves correctly. Node still finds @mastra/mcp because
            # ESM resolves bare imports from the worker file's own directory upward.
            proc = subprocess.run(
                ["node", str(_WORKER), json.dumps(config)],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"mastra worker timed out after {_TIMEOUT_SECONDS}s") from exc
        except Exception as exc:  # noqa: BLE001
            raise RenderError(f"mastra worker failed to start: {exc}") from exc

        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            raise RenderError(f"mastra worker error: {detail}")

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RenderError(
                f"mastra worker returned invalid JSON ({exc}): {proc.stdout[:200]!r}"
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
            raise RenderError("mastra worker returned no tool list")
        protocol_version = payload.get("negotiatedMcpSpecVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise RenderError("mastra worker returned no negotiated MCP protocol version")
        self._negotiated_mcp_spec_version = protocol_version

        reps: list[ToolRep] = []
        for entry in payload["tools"]:
            payload = {
                "name": entry.get("name"),
                "description": entry.get("description"),
                "parameters": entry.get("parameters") or {},
            }
            # Mastra does not carry MCP annotations onto its tools, so none are retained.
            reps.append(normalize_function_tool(payload, origin=self.id))
        return reps

    def _config(self, server: ServerHandle) -> dict:
        if server.transport == "http":
            config: dict = {"transport": "http", "url": server.url}
            if server.headers:
                config["headers"] = dict(server.headers)
            return config
        return {"transport": "stdio", "command": server.command, "args": list(server.args)}


def _node_version() -> str:
    try:
        return subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return "unknown"
