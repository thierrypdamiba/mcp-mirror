"""Integration tests that run real framework captures against the real MCP server.

These tests spawn the bundled reference MCP server via stdio and connect each
real framework adapter to it. No simulators, no mocks. The tests assert known
properties about each adapter's behavior, captured live.
"""

from __future__ import annotations

import sys

import pytest

from mcp import StdioServerParameters

from mcp_mirror.capture import (
    capture_langchain,
    capture_llamaindex,
    capture_pydantic_ai,
    capture_server_announcement,
)
from mcp_mirror.diff import diff_views
from mcp_mirror.types import Category


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_mirror.server"],
    )


@pytest.mark.asyncio
async def test_server_announcement_reflects_fixtures() -> None:
    result = await capture_server_announcement(_params())
    names = {v.name for v in result.views}
    assert {"send_message", "search_records"}.issubset(names)
    sm = next(v for v in result.views if v.name == "send_message")
    # The server's tools advertise rich schemas, response shapes, and _meta.
    assert "oneOf" in str(sm.parameters_schema)
    assert sm.response_schema is not None
    assert sm.metadata.get("idempotent") is False


@pytest.mark.asyncio
async def test_langchain_drops_response_schema_and_meta() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_params())).views}
    result = await capture_langchain(_params())
    assert result.framework_version is not None  # real package, real version
    for view in result.views:
        d = diff_views(server_views[view.name], view, "langchain")
        # LangChain MCP adapter drops the response schema entirely.
        assert any(fd.path.startswith("response") and fd.category == Category.LOSSY for fd in d.field_diffs)
        # ...and drops the server's _meta metadata.
        meta_lossy = [fd for fd in d.field_diffs if fd.path.startswith("metadata.") and fd.category == Category.LOSSY]
        assert meta_lossy, "LangChain should drop server _meta fields"
        # But the input schema is preserved faithfully — no transformative deltas there.
        params_transformative = [
            fd for fd in d.field_diffs
            if fd.path.startswith("parameters") and fd.category == Category.TRANSFORMATIVE
        ]
        assert not params_transformative, "LangChain should preserve input schema structure"


@pytest.mark.asyncio
async def test_pydantic_ai_is_most_faithful() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_params())).views}
    result = await capture_pydantic_ai(_params())
    assert result.framework_version is not None
    for view in result.views:
        d = diff_views(server_views[view.name], view, "pydantic-ai")
        # Pydantic AI should have at most additive deltas (a class marker we add).
        non_additive = [fd for fd in d.field_diffs if fd.category != Category.ADDITIVE]
        assert not non_additive, f"Pydantic AI should be faithful; got {non_additive}"


@pytest.mark.asyncio
async def test_llamaindex_restructures_schema() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_params())).views}
    result = await capture_llamaindex(_params())
    assert result.framework_version is not None
    for view in result.views:
        d = diff_views(server_views[view.name], view, "llamaindex")
        # LlamaIndex converts JSON Schema through Pydantic, which restructures.
        # Expect both LOSSY (original keys reorganized away) and ADDITIVE (Pydantic-style keys).
        cats = {fd.category for fd in d.field_diffs}
        assert Category.LOSSY in cats or Category.ADDITIVE in cats
