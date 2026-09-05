"""Renderer protocol + registry of installed renderers (DESIGN.md section 8).

A renderer turns a live MCP server into the list of LLM-facing tool specs that one
framework would send to a model. The cardinal rule (decision D1) is to always drive
the framework's *real* adapter and never reimplement it.

Renderers live behind optional extras. Importing a renderer module must not import
its heavy framework at module load time; availability is checked with
``importlib.util.find_spec`` so ``mcp-mirror frameworks`` works with nothing installed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Protocol, runtime_checkable

from ..models import ToolRep
from ..source import ServerHandle


@runtime_checkable
class Renderer(Protocol):
    id: str

    def versions(self) -> dict: ...

    def render(self, server: ServerHandle) -> list[ToolRep]: ...


class RenderError(RuntimeError):
    """Raised when a framework adapter fails to render the server's tools."""


# id -> (module suffix, callable name returning a Renderer)
_RENDERER_MODULES: dict[str, str] = {
    "langchain": ".langchain_renderer",
    "pydantic_ai": ".pydantic_ai_renderer",
    "crewai": ".crewai_renderer",
    "openai_agents": ".openai_agents_renderer",
    "mastra": ".mastra_renderer",
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


def canonical_id(name: str) -> str:
    name = name.strip().lower()
    return _ALIASES.get(name, name)


def all_renderer_ids() -> list[str]:
    return list(_RENDERER_MODULES)


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
