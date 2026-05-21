"""Integration tests that run real framework captures against the real MCP server.

These tests spawn the bundled reference MCP server via stdio and connect each
real framework adapter to it. No simulators, no mocks.
"""

from __future__ import annotations

import sys

import pytest

from mcp_mirror.capture import (
    capture_ag2,
    capture_crewai,
    capture_langchain,
    capture_llamaindex,
    capture_pydantic_ai,
    capture_server_announcement,
)
from mcp_mirror.diff import diff_views
from mcp_mirror.spec import ServerSpec
from mcp_mirror.types import Category


def _spec() -> ServerSpec:
    return ServerSpec.stdio(sys.executable, ["-m", "mcp_mirror.server"])


@pytest.mark.asyncio
async def test_server_announcement_reflects_fixtures() -> None:
    result = await capture_server_announcement(_spec())
    names = {v.name for v in result.views}
    assert {"send_message", "search_records"}.issubset(names)
    sm = next(v for v in result.views if v.name == "send_message")
    assert "oneOf" in str(sm.parameters_schema)
    assert sm.response_schema is not None
    assert sm.metadata.get("idempotent") is False


@pytest.mark.asyncio
async def test_langchain_drops_response_schema_and_meta() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_spec())).views}
    result = await capture_langchain(_spec())
    assert result.framework_version is not None
    for view in result.views:
        d = diff_views(server_views[view.name], view, "langchain")
        assert any(fd.path.startswith("response") and fd.category == Category.LOSSY for fd in d.field_diffs)
        meta_lossy = [fd for fd in d.field_diffs if fd.path.startswith("metadata.") and fd.category == Category.LOSSY]
        assert meta_lossy, "LangChain should drop server _meta fields"
        params_transformative = [
            fd for fd in d.field_diffs
            if fd.path.startswith("parameters") and fd.category == Category.TRANSFORMATIVE
        ]
        assert not params_transformative, "LangChain should preserve input schema structure"


@pytest.mark.asyncio
async def test_pydantic_ai_is_most_faithful() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_spec())).views}
    result = await capture_pydantic_ai(_spec())
    assert result.framework_version is not None
    for view in result.views:
        d = diff_views(server_views[view.name], view, "pydantic-ai")
        non_additive = [fd for fd in d.field_diffs if fd.category != Category.ADDITIVE]
        assert not non_additive, f"Pydantic AI should be faithful; got {non_additive}"


@pytest.mark.asyncio
async def test_llamaindex_restructures_schema() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_spec())).views}
    result = await capture_llamaindex(_spec())
    assert result.framework_version is not None
    for view in result.views:
        d = diff_views(server_views[view.name], view, "llamaindex")
        cats = {fd.category for fd in d.field_diffs}
        assert Category.LOSSY in cats or Category.ADDITIVE in cats


@pytest.mark.asyncio
async def test_crewai_extends_description() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_spec())).views}
    result = await capture_crewai(_spec())
    assert result.framework_version is not None
    for view in result.views:
        sv = server_views[view.name]
        # CrewAI extends the description with usage guidance — meaningfully longer.
        assert len(view.description) >= len(sv.description)


@pytest.mark.asyncio
async def test_ag2_preserves_input_schema() -> None:
    server_views = {v.name: v for v in (await capture_server_announcement(_spec())).views}
    result = await capture_ag2(_spec())
    assert result.framework_version is not None
    for view in result.views:
        d = diff_views(server_views[view.name], view, "ag2")
        # AG2 passes inputSchema through; should not transform structure within parameters.
        params_transformative = [
            fd for fd in d.field_diffs
            if fd.path.startswith("parameters") and fd.category == Category.TRANSFORMATIVE
        ]
        assert not params_transformative
