"""Integration tests: each installed renderer vs the tricky fixture (DESIGN.md section 14).

These spawn ``fixtures/tricky_server.py`` over stdio and drive each framework's real
adapter. Renderers whose framework is not installed are skipped automatically, so the
suite is green whether you installed ``[langchain]``, ``[all]``, or nothing.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from mcp_mirror.cli import _render_isolated
from mcp_mirror.diff import diff_reps
from mcp_mirror.models import Dimension
from mcp_mirror.renderers import available_renderers
from mcp_mirror.source import load_source, parse_server

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tricky_server.py"
FRAMEWORK_DATA = (
    Path(__file__).resolve().parents[1] / "data" / "frameworks.json"
)
RENDERERS = available_renderers()

EXPECTED_BOUNDARIES = {
    "langchain": {
        "capture_api": "langchain_core.utils.function_calling.convert_to_openai_tool",
        "capture_object": "OpenAI-compatible function-tool dictionary",
        "capture_stage": "provider_format",
    },
    "pydantic_ai": {
        "capture_api": "pydantic_ai.mcp.MCPToolset.get_tools",
        "capture_object": "pydantic_ai.tools.ToolDefinition",
        "capture_stage": "framework_tool_definition",
    },
    "crewai": {
        "capture_api": "crewai_tools.MCPServerAdapter",
        "capture_object": "CrewAI BaseTool name, description, and args_schema",
        "capture_stage": "framework_tool_definition",
    },
    "openai_agents": {
        "capture_api": "agents.mcp.util.MCPUtil.to_function_tool",
        "capture_object": "agents.tool.FunctionTool",
        "capture_stage": "framework_tool_definition",
    },
    "mastra": {
        "capture_api": "@mastra/mcp MCPClient.listTools",
        "capture_object": "Mastra Tool action returned by listTools",
        "capture_stage": "framework_tool_definition",
    },
}

PUBLISHED_CODE_OVERRIDES = {
    "crewai": {
        "description-fidelity": "a",
        "one-of-any-of": "a",
        "destructive-hint": "n",
        "idempotent-hint": "n",
        "open-world-hint": "n",
        "read-only-hint": "n",
        "title-annotation": "n",
    },
    "langchain": {
        "destructive-hint": "a",
        "idempotent-hint": "a",
        "open-world-hint": "a",
        "read-only-hint": "a",
        "title-annotation": "a",
    },
    "openai-agents": {
        "destructive-hint": "n",
        "idempotent-hint": "n",
        "open-world-hint": "n",
        "read-only-hint": "n",
        "title-annotation": "a",
    },
    "pydantic-ai": {
        "destructive-hint": "a",
        "idempotent-hint": "a",
        "open-world-hint": "a",
        "read-only-hint": "a",
        "title-annotation": "a",
    },
    "mastra": {
        "destructive-hint": "n",
        "idempotent-hint": "n",
        "open-world-hint": "n",
        "read-only-hint": "n",
        "title-annotation": "n",
        "tool-name": "a",
    },
}


def _handle():
    command = shlex.join([sys.executable, str(FIXTURE)])
    return parse_server(command)


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture server missing")
def test_source_loader_reads_fixture():
    spec_version, source_reps = load_source(_handle())
    assert spec_version and spec_version != "unknown"
    by_name = {rep.name: rep for rep in source_reps}
    assert set(by_name) == {
        "search_records",
        "create_report",
        "deliver_payload",
        "delete_account",
        "explain_topic",
    }

    search = by_name["search_records"].params
    assert search["required"] == ["query"]
    assert search["properties"]["status"]["enum"] == [
        "active",
        "archived",
        "pending",
        "deleted",
    ]
    assert search["properties"]["owner_email"]["format"] == "email"
    assert search["properties"]["created_after"]["format"] == "date-time"
    assert search["properties"]["limit"]["minimum"] == 1
    assert search["properties"]["limit"]["maximum"] == 100

    report = by_name["create_report"].params
    assert report["properties"]["config"]["type"] == "object"
    assert report["properties"]["sections"]["items"]["type"] == "object"

    delivery = by_name["deliver_payload"].params
    assert len(delivery["properties"]["destination"]["anyOf"]) == 2
    assert len(delivery["properties"]["mode"]["oneOf"]) == 2

    assert by_name["explain_topic"].description.endswith(
        "SENTINEL_END_OF_LONG_DESCRIPTION."
    )
    delete = by_name["delete_account"]
    assert delete.annotations.get("destructiveHint") is True


@pytest.mark.skipif(not RENDERERS, reason="no framework renderers installed")
@pytest.mark.parametrize("renderer_id", sorted(RENDERERS))
def test_renderer_declares_exact_capture_boundary(renderer_id):
    evidence = type(RENDERERS[renderer_id])().evidence()
    expected = EXPECTED_BOUNDARIES[renderer_id]

    assert evidence.capture_api == expected["capture_api"]
    assert evidence.capture_object == expected["capture_object"]
    assert evidence.capture_stage == expected["capture_stage"]
    assert evidence.provider_request_captured is False
    assert evidence.negotiated_mcp_spec_version is None
    assert evidence.protocol_version_evidence


@pytest.mark.skipif(
    "langchain" not in RENDERERS,
    reason="langchain renderer not installed",
)
def test_isolated_worker_returns_renderer_evidence():
    versions, evidence, reps = _render_isolated(
        "langchain",
        _handle().spec,
        {},
    )

    assert versions["framework"] != "unknown"
    assert evidence.capture_api == EXPECTED_BOUNDARIES["langchain"]["capture_api"]
    assert evidence.provider_request_captured is False
    assert evidence.negotiated_mcp_spec_version == "2025-11-25"
    assert reps


@pytest.mark.skipif(not RENDERERS, reason="no framework renderers installed")
def test_published_framework_versions_and_boundaries_match_installed_renderers():
    published = json.loads(FRAMEWORK_DATA.read_text())["agents"]
    published_ids = {
        "langchain": "langchain",
        "pydantic_ai": "pydantic-ai",
        "crewai": "crewai",
        "openai_agents": "openai-agents",
        "mastra": "mastra",
    }

    for renderer_id, renderer in RENDERERS.items():
        renderer.render(_handle())
        record = published[published_ids[renderer_id]]
        assert record["current_version"] == renderer.versions()["framework"]
        assert record["capture_boundary"] == renderer.evidence().model_dump(
            mode="json",
            exclude={"limitation"},
        )


def test_published_current_cells_match_fixture_goldens():
    published = json.loads(FRAMEWORK_DATA.read_text())["agents"]
    capability_dir = FRAMEWORK_DATA.parent / "capabilities"

    for path in sorted(capability_dir.glob("*.json")):
        capability = json.loads(path.read_text())
        capability_id = capability["id"]
        for framework_id, agent in published.items():
            current_version = agent["current_version"]
            raw_code = capability["stats"][framework_id][current_version]
            expected = PUBLISHED_CODE_OVERRIDES.get(framework_id, {}).get(
                capability_id,
                "y",
            )
            assert raw_code.split()[0] == expected, (
                f"{capability_id} / {framework_id} {current_version}: "
                f"expected {expected!r}, found {raw_code!r}"
            )


@pytest.mark.skipif(not RENDERERS, reason="no framework renderers installed")
@pytest.mark.parametrize("renderer_id", sorted(RENDERERS))
def test_renderer_fixture_contract(renderer_id):
    handle = _handle()
    source_spec_version, source_reps = load_source(handle)
    rendered_reps = RENDERERS[renderer_id].render(handle)

    assert len(rendered_reps) == len(source_reps) == 5
    assert (
        RENDERERS[renderer_id].evidence().negotiated_mcp_spec_version
        == source_spec_version
    )
    source_by_name = {rep.name: rep for rep in source_reps}
    rendered_by_source_name = {
        (
            rep.name.removeprefix("src_")
            if renderer_id == "mastra"
            else rep.name
        ): rep
        for rep in rendered_reps
    }
    assert set(rendered_by_source_name) == set(source_by_name)
    assert rendered_by_source_name["explain_topic"].description.endswith(
        "SENTINEL_END_OF_LONG_DESCRIPTION."
    )

    diffs = diff_reps(source_reps, rendered_reps)

    # Every enum, format, numeric bound, required set, nested object, array item,
    # and destination anyOf in the fixture survives. CrewAI alone collapses mode.oneOf.
    assert not [
        diff
        for diff in diffs
        if diff.dimension
        in {Dimension.PARAM_TYPE, Dimension.CONSTRAINT, Dimension.REQUIRED}
    ]
    structure = [diff for diff in diffs if diff.dimension == Dimension.STRUCTURE]
    if renderer_id == "crewai":
        assert [(diff.path, diff.category) for diff in structure] == [
            ("params.properties.mode.oneOf", "transformative")
        ]
    else:
        assert structure == []

    descriptions = [
        diff for diff in diffs if diff.dimension in {Dimension.DESCRIPTION, Dimension.INJECTION}
    ]
    if renderer_id == "crewai":
        assert len(descriptions) == 5
        assert all(diff.category == "additive" for diff in descriptions)
        assert all(
            source_by_name[name].description in rendered_by_source_name[name].description
            for name in source_by_name
        )
    else:
        assert descriptions == []

    names = [diff for diff in diffs if diff.dimension == Dimension.NAME]
    if renderer_id == "mastra":
        assert len(names) == 5
        assert all(diff.category == "transformative" for diff in names)
        assert all(rep.name.startswith("src_") for rep in rendered_reps)
    else:
        assert names == []

    annotations = {
        diff.path.rsplit(".", 1)[-1]: diff
        for diff in diffs
        if diff.tool == "delete_account" and diff.dimension == Dimension.ANNOTATION
    }
    assert set(annotations) == {
        "title",
        "readOnlyHint",
        "destructiveHint",
        "idempotentHint",
        "openWorldHint",
    }
    behavior_hints = {
        key: annotations[key]
        for key in (
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
        )
    }
    expected_hint_category = (
        "transformative"
        if renderer_id in {"langchain", "pydantic_ai"}
        else "lossy"
    )
    assert {
        diff.category for diff in behavior_hints.values()
    } == {expected_hint_category}

    expected_title_category = (
        "transformative"
        if renderer_id in {"langchain", "pydantic_ai", "openai_agents"}
        else "lossy"
    )
    assert annotations["title"].category == expected_title_category


@pytest.mark.skipif(
    "pydantic_ai" not in RENDERERS,
    reason="pydantic_ai renderer not installed",
)
def test_pydantic_ai_renderer_uses_current_mcp_toolset():
    from pydantic_ai.mcp import MCPToolset

    renderer = RENDERERS["pydantic_ai"]
    toolset = renderer._build_server(_handle())

    assert isinstance(toolset, MCPToolset)
