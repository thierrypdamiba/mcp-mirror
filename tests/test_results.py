"""Tool-call result capture and diffing.

``ToolRep`` answers what the agent was told a tool is; ``ResultRep`` answers what the
agent gets back when it calls one. These tests pin the second boundary, because an
adapter can render a definition perfectly and still flatten the result.
"""

from __future__ import annotations

import pytest

from mcp_mirror.diff import diff_result
from mcp_mirror.normalize import normalize_framework_result, normalize_source_result
from mcp_mirror.source import call_source_tool, parse_server

SOURCE_PAYLOAD = {
    "content": [
        {"type": "text", "text": "hello", "annotations": {"audience": ["user"], "priority": 0.9}},
        {"type": "image", "data": "x" * 64, "mimeType": "image/png"},
        {"type": "resource_link", "uri": "file:///a.txt", "name": "a.txt"},
    ],
    "structuredContent": {"count": 2},
    "isError": False,
}


def _source():
    return normalize_source_result(SOURCE_PAYLOAD, tool="t")


def test_source_result_records_kinds_structured_content_and_error_flag():
    rep = _source()

    assert rep.block_kinds == ["text", "image", "resource_link"]
    assert rep.structured_content == {"count": 2}
    assert rep.is_error is False
    assert rep.text == "hello"


def test_large_opaque_payloads_are_fingerprinted_rather_than_compared():
    image = _source().blocks[1]

    assert image["data"] == "<64 chars>"
    assert image["mimeType"] == "image/png"


def test_a_faithful_rendering_produces_no_differences():
    rendered = normalize_framework_result(
        tool="t",
        origin="fw",
        blocks=SOURCE_PAYLOAD["content"],
        structured_content={"count": 2},
        is_error=False,
    )

    assert diff_result(_source(), rendered) == []


def test_dropped_block_kinds_and_structured_content_are_reported():
    rendered = normalize_framework_result(
        tool="t",
        origin="fw",
        blocks=[{"type": "text", "text": "hello"}],
    )

    details = [d.detail for d in diff_result(_source(), rendered)]

    assert any("image" in d and "resource_link" in d for d in details)
    assert any("structuredContent dropped" in d for d in details)
    assert all(d.category == "lossy" for d in diff_result(_source(), rendered))


def test_text_delivered_as_a_bare_string_does_not_count_as_dropped():
    """Most adapters hand back a string rather than a block. The text still arrived."""

    rendered = normalize_framework_result(tool="t", origin="fw", text="hello")

    lost = [d for d in diff_result(_source(), rendered) if "content blocks dropped" in d.detail]

    assert len(lost) == 1
    assert "text" not in lost[0].detail
    assert "image" in lost[0].detail


def test_content_annotations_are_reported_when_the_block_itself_survives():
    rendered = normalize_framework_result(
        tool="t",
        origin="fw",
        blocks=[{"type": "text", "text": "hello"}] + SOURCE_PAYLOAD["content"][1:],
        structured_content={"count": 2},
    )

    details = [d.detail for d in diff_result(_source(), rendered)]

    assert details == ["annotations dropped from the text block"]


def test_a_lost_failure_flag_is_distinguished_from_one_rendered_as_success():
    source = normalize_source_result(
        {"content": [{"type": "text", "text": "boom"}], "isError": True}, tool="t"
    )

    silent = diff_result(source, normalize_framework_result(tool="t", origin="fw", text="boom"))
    flipped = diff_result(
        source, normalize_framework_result(tool="t", origin="fw", text="boom", is_error=False)
    )

    assert "cannot tell this call failed" in silent[0].detail
    assert "rendered as success" in flipped[0].detail


def test_a_framework_that_cannot_invoke_the_tool_is_recorded_rather_than_skipped():
    diffs = diff_result(_source(), None)

    assert len(diffs) == 1
    assert diffs[0].category == "lossy"
    assert "no way to invoke this tool" in diffs[0].detail


def _pydantic_ai_renderer():
    pytest.importorskip("pydantic_ai.mcp")
    from mcp_mirror.renderers.pydantic_ai_renderer import get_renderer

    return get_renderer()


def test_pydantic_ai_flattens_resources_and_drops_structured_content():
    """The live boundary, pinned against the fixture.

    Pydantic AI returns ``structuredContent`` only when every content part is text, so
    a server that mixes an image into the result loses the typed value. Embedded
    resources and resource links arrive as bare strings, which the agent cannot tell
    apart from ordinary text.
    """

    renderer = _pydantic_ai_renderer()
    handle = parse_server(".venv/bin/python fixtures/tricky_server.py")

    source = call_source_tool(handle, "search_records", {"query": "x"})
    rendered = renderer.render_result(handle, "search_records", {"query": "x"})

    assert source.block_kinds == ["text", "image", "audio", "resource", "resource_link"]
    assert rendered.block_kinds == ["text", "image", "audio", "text", "text"]
    assert rendered.structured_content is None

    details = [d.detail for d in diff_result(source, rendered)]
    assert any("resource, resource_link" in d for d in details)
    assert any("structuredContent dropped" in d for d in details)
    assert any("annotations dropped" in d for d in details)


def test_pydantic_ai_surfaces_a_tool_error_even_though_the_channel_changes():
    """``isError`` reaches the agent as a raised exception rather than a flag."""

    renderer = _pydantic_ai_renderer()
    handle = parse_server(".venv/bin/python fixtures/tricky_server.py")
    args = {"account_id": "a", "confirm": False}

    source = call_source_tool(handle, "delete_account", args)
    rendered = renderer.render_result(handle, "delete_account", args)

    assert source.is_error is True
    assert rendered.is_error is True
    assert diff_result(source, rendered) == []
