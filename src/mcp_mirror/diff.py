"""Differ + categorizer (DESIGN.md section 9).

Given a source ``ToolRep`` and a framework ``ToolRep`` of the same tool, walk every
dimension and emit categorized ``Difference`` records. Only non-faithful deltas are
emitted: a tool with zero differences is fully faithful.

Categorization rule of thumb (section 9): prefer *lossy* if information capacity
decreased, *additive* if it increased, *transformative* if it merely changed shape.
"""

from __future__ import annotations

from typing import Any

from .models import Difference, Dimension, ToolRep
from .schema import effective_schema

# Keywords that, when present in a source description and absent from the rendered
# one, indicate an authorization-relevant signal was lost (feeds J5, section 10).
RISK_KEYWORDS = (
    "destructive",
    "irreversible",
    "cannot be undone",
    "permanent",
    "permanently",
    "delete",
    "deletes",
    "deletion",
    "remove",
    "wipe",
    "overwrite",
    "drop",
    "elevated",
    "scope",
    "permission",
    "admin",
    "danger",
    "dangerous",
)

# JSON Schema constraint keywords whose loss weakens the parameter contract.
CONSTRAINT_KEYS = (
    "enum",
    "const",
    "format",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "multipleOf",
    "minProperties",
    "maxProperties",
    "default",
)

# JSON Schema 2020-12 combinators whose collapse is a structural transform.
COMBINATOR_KEYS = ("oneOf", "anyOf", "allOf", "not")


def diff_tool(source: ToolRep, rendered: ToolRep | None) -> list[Difference]:
    """Diff one source tool against one framework rendering of it.

    ``rendered`` is ``None`` when the framework dropped the tool entirely.
    """

    framework = rendered.origin if rendered is not None else "?"
    tool = source.name

    if rendered is None:
        return [
            Difference(
                tool=tool,
                framework=framework,
                path="name",
                category="lossy",
                dimension=Dimension.NAME,
                detail="tool absent from rendering (the framework did not expose it)",
                source_value=source.name,
                rendered_value=None,
            )
        ]

    diffs: list[Difference] = []
    _diff_name(source, rendered, tool, framework, diffs)
    _diff_description(source, rendered, tool, framework, diffs)
    _walk_schema(
        source.params, rendered.params, "params", tool, framework, diffs,
        source.params, rendered.params,
    )
    _diff_annotations(source, rendered, tool, framework, diffs)
    return diffs


def diff_reps(source_reps: list[ToolRep], rendered_reps: list[ToolRep]) -> list[Difference]:
    """Match source tools to renderings (by name, then namespace) and diff each."""

    diffs: list[Difference] = []
    matched_rendered: set[int] = set()

    for source in source_reps:
        rendered, idx = _match_one(source, rendered_reps, matched_rendered)
        if idx is not None:
            matched_rendered.add(idx)
        diffs.extend(diff_tool(source, rendered))

    # Renderings with no source counterpart are wholesale additions.
    framework = rendered_reps[0].origin if rendered_reps else "?"
    for idx, rendered in enumerate(rendered_reps):
        if idx in matched_rendered:
            continue
        diffs.append(
            Difference(
                tool=rendered.name,
                framework=framework,
                path="name",
                category="additive",
                dimension=Dimension.INJECTION,
                detail="rendering exposes a tool with no source counterpart",
                source_value=None,
                rendered_value=rendered.name,
            )
        )
    return diffs


def _match_one(
    source: ToolRep, rendered_reps: list[ToolRep], used: set[int]
) -> tuple[ToolRep | None, int | None]:
    for idx, rendered in enumerate(rendered_reps):
        if idx not in used and rendered.name == source.name:
            return rendered, idx
    candidates = [
        (idx, r)
        for idx, r in enumerate(rendered_reps)
        if idx not in used and r.name and (r.name.endswith(source.name) or source.name in r.name)
    ]
    if len(candidates) == 1:
        idx, rendered = candidates[0]
        return rendered, idx
    return None, None


def _diff_name(s: ToolRep, r: ToolRep, tool: str, fw: str, diffs: list[Difference]) -> None:
    if not r.name:
        diffs.append(
            Difference(
                tool=tool,
                framework=fw,
                path="name",
                category="lossy",
                dimension=Dimension.NAME,
                detail="tool name missing in rendering",
                source_value=s.name,
                rendered_value=r.name,
            )
        )
        return
    if r.name == s.name:
        return
    if s.name in r.name:
        detail = f"tool name namespaced/prefixed: {s.name!r} -> {r.name!r}"
    else:
        detail = f"tool name renamed: {s.name!r} -> {r.name!r}"
    diffs.append(
        Difference(
            tool=tool,
            framework=fw,
            path="name",
            category="transformative",
            dimension=Dimension.NAME,
            detail=detail,
            source_value=s.name,
            rendered_value=r.name,
        )
    )


def _diff_description(s: ToolRep, r: ToolRep, tool: str, fw: str, diffs: list[Difference]) -> None:
    sd = s.description or ""
    rd = r.description or ""
    if sd == rd:
        return

    if sd and not rd:
        diffs.append(
            _d(tool, fw, "description", "lossy", Dimension.DESCRIPTION, "description dropped", sd, rd)
        )
    elif rd and not sd:
        diffs.append(
            _d(
                tool, fw, "description", "additive", Dimension.INJECTION,
                "description injected (source had none)", sd, rd,
            )
        )
    elif sd.startswith(rd) and len(rd) < len(sd):
        diffs.append(
            _d(
                tool, fw, "description", "lossy", Dimension.DESCRIPTION,
                f"description truncated ({len(rd)} of {len(sd)} chars)", sd, rd,
            )
        )
    elif rd.startswith(sd) and len(rd) > len(sd):
        diffs.append(
            _d(
                tool, fw, "description", "additive", Dimension.INJECTION,
                "description has appended text not in source", sd, rd,
            )
        )
    elif sd in rd and len(rd) > len(sd):
        diffs.append(
            _d(
                tool, fw, "description", "additive", Dimension.INJECTION,
                "description wraps source text with injected content", sd, rd,
            )
        )
    elif len(rd) < len(sd) * 0.9:
        diffs.append(
            _d(
                tool, fw, "description", "lossy", Dimension.DESCRIPTION,
                f"description materially shortened ({len(rd)} of {len(sd)} chars)", sd, rd,
            )
        )
    elif len(rd) > len(sd) * 1.1:
        diffs.append(
            _d(
                tool, fw, "description", "additive", Dimension.INJECTION,
                f"description materially longer ({len(rd)} vs {len(sd)} chars)", sd, rd,
            )
        )
    else:
        diffs.append(
            _d(
                tool, fw, "description", "transformative", Dimension.DESCRIPTION,
                "description reworded (similar length, different text)", sd, rd,
            )
        )

    _check_risk_language(sd, rd, tool, fw, diffs)


def _check_risk_language(sd: str, rd: str, tool: str, fw: str, diffs: list[Difference]) -> None:
    """If risk/scope language present in the source description is gone, flag J5."""

    if not sd or sd == rd:
        return
    sd_l = sd.lower()
    rd_l = rd.lower()
    lost = [kw for kw in RISK_KEYWORDS if kw in sd_l and kw not in rd_l]
    if lost:
        diffs.append(
            _d(
                tool, fw, "description", "lossy", Dimension.AUTHZ,
                "authorization-relevant language lost from description: "
                + ", ".join(repr(kw) for kw in lost),
                sd, rd,
            )
        )


def _diff_annotations(s: ToolRep, r: ToolRep, tool: str, fw: str, diffs: list[Difference]) -> None:
    """Three-way annotation comparison (the J5 core).

    For each source annotation, the rendering can:
    - preserve it at the declared capture boundary (``annotations``) -> faithful / transformative
    - retain it elsewhere (``framework_metadata``)                    -> transformative
    - destroy it (no trace anywhere)                                  -> lossy
    """

    authz_keys = {"destructiveHint", "readOnlyHint", "openWorldHint", "idempotentHint"}
    captured = r.annotations or {}
    retained = (r.framework_metadata or {}).get("annotations") or {}

    for key, value in (s.annotations or {}).items():
        relevant = " (authorization-relevant)" if key in authz_keys else ""
        if key in captured:
            if captured[key] != value:
                diffs.append(
                    Difference(
                        tool=tool, framework=fw, path=f"annotations.{key}",
                        category="transformative", dimension=Dimension.ANNOTATION,
                        detail=f"annotation {key!r}{relevant} changed at the capture boundary",
                        source_value=value, rendered_value=captured[key],
                    )
                )
            continue
        if key in retained:
            diffs.append(
                Difference(
                    tool=tool, framework=fw, path=f"annotations.{key}",
                    category="transformative", dimension=Dimension.ANNOTATION,
                    detail=(
                        f"annotation {key!r}{relevant} retained in framework metadata "
                        "but absent from the captured tool definition"
                    ),
                    source_value=value, rendered_value=retained[key],
                )
            )
        else:
            diffs.append(
                Difference(
                    tool=tool, framework=fw, path=f"annotations.{key}",
                    category="lossy", dimension=Dimension.ANNOTATION,
                    detail=f"annotation {key!r}{relevant} destroyed (not retained by the framework)",
                    source_value=value, rendered_value=None,
                )
            )


def _walk_schema(
    s: Any,
    r: Any,
    path: str,
    tool: str,
    fw: str,
    diffs: list[Difference],
    s_root: dict,
    r_root: dict,
) -> None:
    """Recursive JSON Schema walk comparing source subschema ``s`` to rendered ``r``.

    Both sides are normalized first (``$ref`` resolved, ``Optional[X]`` wrappers
    collapsed) so that a framework serializing optional params as ``anyOf:[X, null]`` or
    nesting via ``$defs`` is not falsely reported as dropping enums, formats or structure.
    """

    if isinstance(s, dict):
        s = effective_schema(s, s_root)
    if isinstance(r, dict):
        r = effective_schema(r, r_root)

    if not isinstance(s, dict):
        return
    if not isinstance(r, dict):
        diffs.append(
            _d(tool, fw, path, "lossy", Dimension.STRUCTURE, "subschema dropped in rendering", s, r)
        )
        return

    for ck in COMBINATOR_KEYS:
        if ck in s and ck not in r:
            diffs.append(
                _d(
                    tool, fw, f"{path}.{ck}", "transformative", Dimension.STRUCTURE,
                    f"{ck} collapsed/flattened (JSON Schema 2020-12 construct lost)",
                    s.get(ck), None,
                )
            )

    if "$ref" in s and "$ref" not in r:
        diffs.append(
            _d(
                tool, fw, f"{path}.$ref", "transformative", Dimension.STRUCTURE,
                "$ref inlined/resolved", s.get("$ref"), None,
            )
        )

    _diff_type(s, r, path, tool, fw, diffs)

    for key in CONSTRAINT_KEYS:
        if key in s and key not in r:
            diffs.append(
                _d(
                    tool, fw, f"{path}.{key}", "lossy", Dimension.CONSTRAINT,
                    f"{key} constraint lost", s.get(key), None,
                )
            )

    # A subschema's own description (not the tool description at "params").
    if path != "params" and s.get("description") and not r.get("description"):
        diffs.append(
            _d(
                tool, fw, f"{path}.description", "lossy", Dimension.CONSTRAINT,
                "per-property description lost", s.get("description"), None,
            )
        )

    _diff_properties(s, r, path, tool, fw, diffs, s_root, r_root)
    _diff_required(s, r, path, tool, fw, diffs)

    s_items = s.get("items")
    if isinstance(s_items, dict):
        r_items = r.get("items")
        if isinstance(r_items, dict):
            _walk_schema(s_items, r_items, f"{path}.items", tool, fw, diffs, s_root, r_root)
        else:
            diffs.append(
                _d(
                    tool, fw, f"{path}.items", "lossy", Dimension.STRUCTURE,
                    "array item schema dropped", s_items, r_items,
                )
            )


def _diff_type(s: dict, r: dict, path: str, tool: str, fw: str, diffs: list[Difference]) -> None:
    s_type = s.get("type")
    if s_type is None:
        return
    r_type = r.get("type")
    if r_type is None:
        if "$ref" in r or any(k in r for k in COMBINATOR_KEYS):
            return
        diffs.append(
            _d(tool, fw, f"{path}.type", "lossy", Dimension.PARAM_TYPE, "type dropped", s_type, None)
        )
    elif r_type != s_type:
        diffs.append(
            _d(
                tool, fw, f"{path}.type", "transformative", Dimension.PARAM_TYPE,
                f"type changed: {s_type!r} -> {r_type!r}", s_type, r_type,
            )
        )


def _diff_properties(
    s: dict, r: dict, path: str, tool: str, fw: str, diffs: list[Difference], s_root: dict, r_root: dict
) -> None:
    s_props = s.get("properties")
    r_props = r.get("properties")

    if isinstance(s_props, dict) and s_props:
        if not isinstance(r_props, dict):
            diffs.append(
                _d(
                    tool, fw, f"{path}.properties", "transformative", Dimension.STRUCTURE,
                    "object properties flattened or dropped", sorted(s_props), None,
                )
            )
            return
        for name, sub in s_props.items():
            sub_path = f"{path}.properties.{name}"
            if name not in r_props:
                diffs.append(
                    _d(
                        tool, fw, sub_path, "lossy", Dimension.STRUCTURE,
                        f"property {name!r} dropped", _summarize(sub), None,
                    )
                )
            else:
                _walk_schema(sub, r_props[name], sub_path, tool, fw, diffs, s_root, r_root)
        for name in r_props:
            if name not in s_props:
                diffs.append(
                    _d(
                        tool, fw, f"{path}.properties.{name}", "additive", Dimension.INJECTION,
                        f"property {name!r} injected (not in source)", None, _summarize(r_props[name]),
                    )
                )
    elif isinstance(r_props, dict) and r_props:
        for name in r_props:
            diffs.append(
                _d(
                    tool, fw, f"{path}.properties.{name}", "additive", Dimension.INJECTION,
                    f"property {name!r} injected (not in source)", None, _summarize(r_props[name]),
                )
            )


def _diff_required(s: dict, r: dict, path: str, tool: str, fw: str, diffs: list[Difference]) -> None:
    s_req = set(s.get("required") or [])
    r_req = set(r.get("required") or [])
    if not s_req and not r_req:
        return
    lost = s_req - r_req
    if lost:
        diffs.append(
            _d(
                tool, fw, f"{path}.required", "lossy", Dimension.REQUIRED,
                f"required set shrank; no longer required: {sorted(lost)}",
                sorted(s_req), sorted(r_req),
            )
        )
    added = r_req - s_req
    if added:
        diffs.append(
            _d(
                tool, fw, f"{path}.required", "transformative", Dimension.REQUIRED,
                f"required set grew; newly required: {sorted(added)}",
                sorted(s_req), sorted(r_req),
            )
        )


def _summarize(schema: Any) -> Any:
    """A compact, JSON-friendly view of a subschema for difference payloads."""

    if isinstance(schema, dict):
        keep = {}
        for key in ("type", "description", "enum", "format"):
            if key in schema:
                keep[key] = schema[key]
        return keep or {"keys": sorted(schema)}
    return schema


def _d(
    tool: str,
    fw: str,
    path: str,
    category: str,
    dimension: str,
    detail: str,
    source_value: Any,
    rendered_value: Any,
) -> Difference:
    return Difference(
        tool=tool,
        framework=fw,
        path=path,
        category=category,  # type: ignore[arg-type]
        dimension=dimension,
        detail=detail,
        source_value=source_value,
        rendered_value=rendered_value,
    )
