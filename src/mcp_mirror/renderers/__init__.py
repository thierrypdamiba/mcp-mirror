"""Renderer protocol + registry of installed renderers (DESIGN.md section 8).

A renderer turns a live MCP server into the tool definitions exposed at one precise
framework boundary. The cardinal rule (decision D1) is to always drive the
framework's *real* adapter and never reimplement it. Each renderer declares whether
that boundary is a framework object, a provider-shaped format, or a captured request.

Renderers live behind optional extras. Importing a renderer module must not import
its heavy framework at module load time; availability is checked with
``importlib.util.find_spec`` so ``mcp-mirror frameworks`` works with nothing installed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Protocol, runtime_checkable

from ..models import RendererEvidence, ToolRep
from ..runner_manifests import load_runner_manifests
from ..source import ServerHandle


@runtime_checkable
class Renderer(Protocol):
    id: str

    def versions(self) -> dict: ...

    def evidence(self) -> RendererEvidence: ...

    def render(self, server: ServerHandle) -> list[ToolRep]: ...


class RenderError(RuntimeError):
    """Raised when a framework adapter fails to render the server's tools."""


# The manifest registry is the single source of truth for runner IDs and modules.
_RENDERER_MODULES: dict[str, str] = {
    renderer_id: manifest.module
    for renderer_id, manifest in load_runner_manifests().items()
}

# Friendly aliases users might pass on the CLI.
_ALIASES = {
    "pydantic-ai": "pydantic_ai",
    "pydanticai": "pydantic_ai",
    "lc": "langchain",
    "openai": "openai_agents",
    "openai-agents": "openai_agents",
    "openai_agents_sdk": "openai_agents",
    "agents": "openai_agents",
}

_EXTRAS = {
    "langchain": "langchain",
    "pydantic_ai": "pydantic-ai",
    "crewai": "crewai",
    "openai_agents": "openai-agents",
}


def canonical_id(name: str) -> str:
    name = name.strip().lower()
    return _ALIASES.get(name, name)


def all_renderer_ids() -> list[str]:
    return list(_RENDERER_MODULES)


def install_hint(renderer_id: str) -> str:
    """Return the shortest supported setup path for one renderer."""

    renderer_id = canonical_id(renderer_id)
    extra = _EXTRAS.get(renderer_id)
    if extra:
        return f"python -m pip install 'mcp-mirror[{extra}]'"
    if renderer_id == "mastra":
        return (
            "set up the bundled Mastra Node runner from a source checkout "
            "(src/mcp_mirror/renderers/mastra_node)"
        )
    return f"unknown renderer {renderer_id!r}"


def available_renderers() -> dict[str, Renderer]:
    """Return ``{id: Renderer}`` for every framework that is actually installed."""

    found: dict[str, Renderer] = {}
    for rid, module_suffix in _RENDERER_MODULES.items():
        try:
            module = import_module(module_suffix, __name__)
        except Exception:
            continue
        try:
            if module.available():
                found[rid] = module.get_renderer()
        except Exception:
            continue
    return found


def select_renderers(requested: list[str] | None) -> tuple[dict[str, Renderer], list[str]]:
    """Resolve a requested id list against installed renderers.

    Returns ``(selected, missing)`` where ``missing`` are requested ids that are not
    installed. When ``requested`` is ``None`` every installed renderer is selected.
    """

    available = available_renderers()
    if requested is None:
        return available, []

    selected: dict[str, Renderer] = {}
    missing: list[str] = []
    for raw in requested:
        rid = canonical_id(raw)
        if rid in available:
            selected[rid] = available[rid]
        else:
            missing.append(rid)
    return selected, missing
