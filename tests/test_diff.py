"""Tests for the diff engine."""

from __future__ import annotations

from mcp_mirror import diff_views
from mcp_mirror.types import Category, ToolView


def _server() -> ToolView:
    return ToolView(
        name="t",
        description="the description",
        parameters_schema={
            "type": "object",
            "properties": {
                "x": {"type": "string", "format": "email", "examples": ["a@b.com"]},
                "y": {
                    "oneOf": [
                        {"type": "object", "title": "first"},
                        {"type": "object", "title": "second"},
                    ]
                },
            },
        },
        response_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        metadata={"stable": True},
    )


def test_identical_views_are_faithful() -> None:
    s = _server()
    d = diff_views(s, s, "echo")
    assert d.is_faithful
    assert d.field_diffs == []
    assert d.overall_category == Category.FAITHFUL


def test_dropped_field_is_lossy() -> None:
    s = _server()
    f = ToolView(
        name=s.name,
        description=s.description,
        parameters_schema={
            "type": "object",
            "properties": {
                "x": {"type": "string", "format": "email"},  # dropped examples
                "y": s.parameters_schema["properties"]["y"],
            },
        },
        response_schema=s.response_schema,
        metadata=s.metadata,
    )
    d = diff_views(s, f, "dropper")
    assert d.overall_category == Category.LOSSY
    paths = {fd.path for fd in d.field_diffs}
    assert "parameters.properties.x.examples" in paths


def test_dropped_response_is_lossy() -> None:
    s = _server()
    f = ToolView(
        name=s.name,
        description=s.description,
        parameters_schema=s.parameters_schema,
        response_schema=None,
        metadata=s.metadata,
    )
    d = diff_views(s, f, "no-response")
    assert d.overall_category == Category.LOSSY


def test_added_metadata_is_additive() -> None:
    s = _server()
    f = ToolView(
        name=s.name,
        description=s.description,
        parameters_schema=s.parameters_schema,
        response_schema=s.response_schema,
        metadata={**s.metadata, "extra": 1},
    )
    d = diff_views(s, f, "adder")
    cats = [fd.category for fd in d.field_diffs]
    assert Category.ADDITIVE in cats
    assert Category.LOSSY not in cats


def test_changed_value_is_transformative() -> None:
    s = _server()
    f = ToolView(
        name=s.name,
        description=s.description,
        parameters_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},  # type changed
                "y": s.parameters_schema["properties"]["y"],
            },
        },
        response_schema=s.response_schema,
        metadata=s.metadata,
    )
    d = diff_views(s, f, "transformer")
    cats = {fd.category for fd in d.field_diffs}
    assert Category.TRANSFORMATIVE in cats


def test_truncated_description_is_lossy() -> None:
    s = _server()
    f = ToolView(
        name=s.name,
        description="the desc",
        parameters_schema=s.parameters_schema,
        response_schema=s.response_schema,
        metadata=s.metadata,
    )
    d = diff_views(s, f, "truncator")
    desc_diffs = [fd for fd in d.field_diffs if fd.path == "description"]
    assert len(desc_diffs) == 1
    assert desc_diffs[0].category == Category.LOSSY


def test_overall_category_is_worst() -> None:
    s = _server()
    f = ToolView(
        name=s.name,
        description=s.description,
        parameters_schema=s.parameters_schema,
        response_schema=None,
        metadata={**s.metadata, "extra": 1},
    )
    d = diff_views(s, f, "mixed")
    # lossy beats additive
    assert d.overall_category == Category.LOSSY
