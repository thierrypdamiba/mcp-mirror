"""JSON Schema normalization shared by the differ and the JTBD evaluator.

Frameworks that build their tool schema from a Pydantic model (CrewAI, and any
``args_schema``-based adapter) serialize an *optional* field ``x: T | None`` as
``{"anyOf": [<T>, {"type": "null"}]}`` and nest objects via ``$defs`` + ``$ref``.
The information is fully present, just one level down. Without normalizing that, a
shallow diff reports enums, formats and nested structure as "lost" when they are not -
which would unfairly malign a framework. These helpers collapse those two patterns so
comparisons see the effective schema.
"""

from __future__ import annotations

from typing import Any

_COMBINATORS = ("anyOf", "oneOf")


def resolve_ref(node: Any, root: dict[str, Any]) -> Any:
    """Follow a single local ``$ref`` (e.g. ``#/$defs/Config``) against ``root``.

    Sibling keys on the referring node (like ``description``) are preserved. A ref that
    cannot be resolved is returned unchanged.
    """

    if not isinstance(node, dict) or not isinstance(node.get("$ref"), str):
        return node
    ref = node["$ref"]
    if not ref.startswith("#/"):
        return node

    target: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and part in target:
            target = target[part]
        else:
            return node
    if not isinstance(target, dict):
        return node

    merged = dict(target)
    for key, value in node.items():
        if key != "$ref":
            merged.setdefault(key, value)
    return merged


def effective_schema(node: Any, root: dict[str, Any]) -> Any:
    """Resolve ``$ref`` and collapse an ``Optional[X]`` wrapper down to ``X``.

    ``{"anyOf": [<X>, {"type": "null"}]}`` (or ``oneOf``) with exactly one non-null
    branch becomes that branch, merged with the wrapper's sibling keys. A genuine union
    (two or more non-null branches) is left intact, so a real ``anyOf`` collapse is still
    detectable by the differ.
    """

    node = resolve_ref(node, root)
    if not isinstance(node, dict):
        return node

    for combinator in _COMBINATORS:
        branches = node.get(combinator)
        if not isinstance(branches, list):
            continue
        non_null = [
            resolve_ref(branch, root)
            for branch in branches
            if not (isinstance(branch, dict) and branch.get("type") == "null")
        ]
        if len(non_null) == 1 and isinstance(non_null[0], dict):
            merged = dict(non_null[0])
            for key, value in node.items():
                if key != combinator:
                    merged.setdefault(key, value)
            return merged
    return node
