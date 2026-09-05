"""Map raw payloads into the common ``ToolRep`` (DESIGN.md section 5.3).

This module is deliberately dependency-free: it works on plain dicts so the core
engine and its unit tests never need the MCP SDK or any framework installed.
"""

from __future__ import annotations

from typing import Any

from .models import ToolRep


def normalize_source_tool(raw: dict[str, Any], origin: str = "source") -> ToolRep:
    """Build a source ``ToolRep`` from an MCP ``tools/list`` entry.

    Accepts the MCP field names (``inputSchema``, ``annotations``) and tolerates a
    couple of aliases so callers can pass either the SDK ``model_dump`` shape or a
    hand-built dict.
    """

    params = raw.get("inputSchema")
    if params is None:
        params = raw.get("input_schema") or raw.get("parameters") or {}
    annotations = raw.get("annotations") or {}
    if not isinstance(annotations, dict):
        annotations = _as_dict(annotations)
    return ToolRep(
        name=raw.get("name") or "",
        description=_clean_description(raw.get("description")),
        params=params if isinstance(params, dict) else {},
        annotations={k: v for k, v in annotations.items() if v is not None},
        origin=origin,
        raw=raw,
    )


def normalize_function_tool(
    fn: dict[str, Any],
    origin: str,
    framework_metadata: dict[str, Any] | None = None,
) -> ToolRep:
    """Build a rendered ``ToolRep`` from the standard function-tool spec.

    The canonical LLM-facing shape (DESIGN.md section 8) is
    ``{name, description, parameters}``, the OpenAI/Anthropic function-tool format.
    Some libraries wrap it as ``{"type": "function", "function": {...}}``; unwrap it.
    This format has no slot for MCP annotations, so ``annotations`` (what the model
    sees) is empty; pass ``framework_metadata`` to record what the framework retains
    out-of-band (e.g. ``{"annotations": {...}}`` kept on the tool object).
    """

    inner = fn
    if isinstance(fn.get("function"), dict) and (fn.get("type") == "function" or "name" not in fn):
        inner = fn["function"]

    params = inner.get("parameters")
    if params is None:
        params = inner.get("input_schema") or inner.get("inputSchema") or {}
    return ToolRep(
        name=inner.get("name") or "",
        description=_clean_description(inner.get("description")),
        params=params if isinstance(params, dict) else {},
        annotations={},
        framework_metadata=framework_metadata or {},
        origin=origin,
        raw=fn,
    )


def _clean_description(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _as_dict(value: Any) -> dict[str, Any]:
    """Best-effort conversion of an annotations object into a plain dict."""

    for attr in ("model_dump", "dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                dumped = method()
                if isinstance(dumped, dict):
                    return dumped
            except TypeError:
                continue
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {}
