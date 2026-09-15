"""Map raw payloads into the common ``ToolRep`` (DESIGN.md section 5.3).

This module is deliberately dependency-free: it works on plain dicts so the core
engine and its unit tests never need the MCP SDK or any framework installed.
"""

from __future__ import annotations

from typing import Any

from .models import ResultRep, ToolRep

# Payload keys reduced to a fingerprint rather than compared byte for byte. Comparing
# whole base64 blobs would make every difference unreadable and would report a
# re-encoded image as a change when the point is only whether the image survived.
_OPAQUE_KEYS = ("data", "blob")


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
        icons=_as_icons(raw.get("icons")),
        origin=origin,
        raw=raw,
    )


def normalize_function_tool(
    fn: dict[str, Any],
    origin: str,
    framework_metadata: dict[str, Any] | None = None,
) -> ToolRep:
    """Build a rendered ``ToolRep`` from the standard function-tool spec.

    The normalized shape is ``{name, description, parameters}``. Some libraries wrap
    it as ``{"type": "function", "function": {...}}``; unwrap it. This shape has no
    slot for MCP annotations, so ``annotations`` is empty at the capture boundary;
    pass ``framework_metadata`` to record what the framework retains elsewhere
    (e.g. ``{"annotations": {...}}`` kept on the tool object). The same applies to
    ``icons``: the function-tool shape has no slot for them, so a framework that keeps
    them at all keeps them under ``framework_metadata["icons"]``.
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


def normalize_source_result(raw: Any, tool: str, origin: str = "source") -> ResultRep:
    """Build a source ``ResultRep`` from an MCP ``tools/call`` result."""

    payload = raw if isinstance(raw, dict) else _as_dict(raw)
    blocks = [_as_block(entry) for entry in (payload.get("content") or [])]
    return ResultRep(
        tool=tool,
        blocks=blocks,
        block_kinds=[block.get("type", "?") for block in blocks],
        structured_content=payload.get("structuredContent"),
        is_error=payload.get("isError"),
        text=_joined_text(blocks),
        origin=origin,
        raw=payload,
    )


def normalize_framework_result(
    *,
    tool: str,
    origin: str,
    blocks: list[Any] | None = None,
    structured_content: Any | None = None,
    is_error: bool | None = None,
    text: str | None = None,
    raw: Any = None,
) -> ResultRep:
    """Build a rendered ``ResultRep`` from whatever the adapter handed the agent.

    Frameworks disagree about what a tool call returns: some yield a list of content
    blocks, most yield a single string. A caller that only has a string passes ``text``
    and leaves ``blocks`` empty, which is itself the finding.
    """

    normalized = [_as_block(entry) for entry in (blocks or [])]
    return ResultRep(
        tool=tool,
        blocks=normalized,
        block_kinds=[block.get("type", "?") for block in normalized],
        structured_content=structured_content,
        is_error=is_error,
        text=text if text is not None else _joined_text(normalized),
        origin=origin,
        raw=raw,
    )


def _as_block(entry: Any) -> dict[str, Any]:
    block = entry if isinstance(entry, dict) else _as_dict(entry)
    block = {k: v for k, v in block.items() if v is not None}
    for key in _OPAQUE_KEYS:
        value = block.get(key)
        if isinstance(value, str) and len(value) > 32:
            block[key] = f"<{len(value)} chars>"
    return block


def _joined_text(blocks: list[dict[str, Any]]) -> str | None:
    parts = [block["text"] for block in blocks if isinstance(block.get("text"), str)]
    return "\n".join(parts) if parts else None


def _clean_description(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _as_icons(value: Any) -> list[dict[str, Any]]:
    """Normalize a tool's ``icons`` into a list of plain dicts.

    Entries arrive as SDK ``Icon`` models or as dicts depending on the caller, and a
    partial rendering may keep only some keys, so unset keys are dropped rather than
    recorded as ``None``. That way a framework keeping ``src`` but discarding
    ``mimeType`` reads as a change to the icon, not as a null someone has to interpret.
    """

    if not isinstance(value, list):
        return []
    icons: list[dict[str, Any]] = []
    for entry in value:
        icon = entry if isinstance(entry, dict) else _as_dict(entry)
        if icon:
            icons.append({k: v for k, v in icon.items() if v is not None})
    return icons


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
