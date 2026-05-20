"""Diff engine — compares two ToolViews and produces a structured ToolDiff."""

from __future__ import annotations

from typing import Any

from mcp_mirror.types import Category, FieldDiff, ToolDiff, ToolView


def diff_views(server: ToolView, framework: ToolView, framework_name: str) -> ToolDiff:
    """Compare a server's tool announcement against what a framework hands to the LLM."""
    diffs: list[FieldDiff] = []

    if server.name != framework.name:
        diffs.append(
            FieldDiff(
                path="name",
                server_value=server.name,
                framework_value=framework.name,
                category=Category.TRANSFORMATIVE,
                note="Tool name was rewritten by the framework.",
            )
        )

    diffs.extend(_diff_description(server.description, framework.description))
    diffs.extend(
        _walk(
            "parameters",
            server.parameters_schema,
            framework.parameters_schema,
        )
    )
    diffs.extend(
        _walk(
            "response",
            server.response_schema or {},
            framework.response_schema or {},
        )
    )
    diffs.extend(_diff_metadata(server.metadata, framework.metadata))

    return ToolDiff(
        tool_name=server.name,
        framework_name=framework_name,
        server_view=server,
        framework_view=framework,
        field_diffs=diffs,
    )


def _diff_description(server: str, framework: str) -> list[FieldDiff]:
    if server == framework:
        return []
    if not framework:
        return [
            FieldDiff(
                path="description",
                server_value=server,
                framework_value=framework,
                category=Category.LOSSY,
                note="Description was dropped entirely.",
            )
        ]
    if framework in server and len(framework) < len(server):
        return [
            FieldDiff(
                path="description",
                server_value=server,
                framework_value=framework,
                category=Category.LOSSY,
                note=f"Description truncated ({len(server)} -> {len(framework)} chars).",
            )
        ]
    if server in framework and len(framework) > len(server):
        return [
            FieldDiff(
                path="description",
                server_value=server,
                framework_value=framework,
                category=Category.ADDITIVE,
                note=f"Description extended by framework ({len(server)} -> {len(framework)} chars).",
            )
        ]
    return [
        FieldDiff(
            path="description",
            server_value=server,
            framework_value=framework,
            category=Category.TRANSFORMATIVE,
            note="Description rewritten by framework.",
        )
    ]


def _walk(prefix: str, server: Any, framework: Any) -> list[FieldDiff]:
    """Recursively diff two JSON-Schema-shaped values."""
    if server == framework:
        return []

    if isinstance(server, dict) and isinstance(framework, dict):
        diffs: list[FieldDiff] = []
        for key in server:
            path = f"{prefix}.{key}"
            if key not in framework:
                diffs.append(
                    FieldDiff(
                        path=path,
                        server_value=server[key],
                        framework_value=None,
                        category=Category.LOSSY,
                        note=f"Framework dropped `{key}`.",
                    )
                )
            else:
                diffs.extend(_walk(path, server[key], framework[key]))
        for key in framework:
            if key not in server:
                path = f"{prefix}.{key}"
                diffs.append(
                    FieldDiff(
                        path=path,
                        server_value=None,
                        framework_value=framework[key],
                        category=Category.ADDITIVE,
                        note=f"Framework added `{key}` not present on server.",
                    )
                )
        return diffs

    if isinstance(server, list) and isinstance(framework, list):
        if len(server) != len(framework):
            return [
                FieldDiff(
                    path=prefix,
                    server_value=server,
                    framework_value=framework,
                    category=Category.TRANSFORMATIVE,
                    note=f"List length changed ({len(server)} -> {len(framework)}).",
                )
            ]
        out: list[FieldDiff] = []
        for i, (a, b) in enumerate(zip(server, framework)):
            out.extend(_walk(f"{prefix}[{i}]", a, b))
        return out

    return [
        FieldDiff(
            path=prefix,
            server_value=server,
            framework_value=framework,
            category=Category.TRANSFORMATIVE,
            note=f"Value changed: {server!r} -> {framework!r}.",
        )
    ]


def _diff_metadata(server: dict[str, Any], framework: dict[str, Any]) -> list[FieldDiff]:
    """Metadata diffs default to ADDITIVE if framework adds, LOSSY if server had and framework dropped."""
    diffs: list[FieldDiff] = []
    for key in server:
        if key not in framework:
            diffs.append(
                FieldDiff(
                    path=f"metadata.{key}",
                    server_value=server[key],
                    framework_value=None,
                    category=Category.LOSSY,
                    note=f"Server metadata `{key}` dropped by framework.",
                )
            )
        elif server[key] != framework[key]:
            diffs.append(
                FieldDiff(
                    path=f"metadata.{key}",
                    server_value=server[key],
                    framework_value=framework[key],
                    category=Category.TRANSFORMATIVE,
                    note=f"Metadata `{key}` rewritten.",
                )
            )
    for key in framework:
        if key not in server:
            diffs.append(
                FieldDiff(
                    path=f"metadata.{key}",
                    server_value=None,
                    framework_value=framework[key],
                    category=Category.ADDITIVE,
                    note=f"Framework added metadata `{key}`.",
                )
            )
    return diffs
