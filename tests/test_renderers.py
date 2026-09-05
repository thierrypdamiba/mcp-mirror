"""Integration tests: each installed renderer vs the tricky fixture (DESIGN.md section 14).

These spawn ``fixtures/tricky_server.py`` over stdio and drive each framework's real
adapter. Renderers whose framework is not installed are skipped automatically, so the
suite is green whether you installed ``[langchain]``, ``[all]``, or nothing.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from mcp_mirror.diff import diff_reps
from mcp_mirror.renderers import available_renderers
from mcp_mirror.source import load_source, parse_server

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tricky_server.py"
RENDERERS = available_renderers()


def _handle():
    command = shlex.join([sys.executable, str(FIXTURE)])
    return parse_server(command)


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture server missing")
def test_source_loader_reads_fixture():
    spec_version, source_reps = load_source(_handle())
    assert spec_version and spec_version != "unknown"
    names = {rep.name for rep in source_reps}
    assert {"search_records", "delete_account", "explain_topic"} <= names
    delete = next(rep for rep in source_reps if rep.name == "delete_account")
    assert delete.annotations.get("destructiveHint") is True


@pytest.mark.skipif(not RENDERERS, reason="no framework renderers installed")
@pytest.mark.parametrize("renderer_id", sorted(RENDERERS))
def test_renderer_reports_annotation_not_surfaced_to_model(renderer_id):
    handle = _handle()
    _, source_reps = load_source(handle)
    rendered_reps = RENDERERS[renderer_id].render(handle)

    assert rendered_reps, f"{renderer_id} produced no tools"

    diffs = diff_reps(source_reps, rendered_reps)
    destructive = [
        d for d in diffs if d.tool == "delete_account" and d.path.endswith("destructiveHint")
    ]
    # The function-tool format has no slot for annotations, so destructiveHint never
    # reaches the model. It must therefore be reported as a J5 difference (not faithful).
    assert destructive, f"{renderer_id} did not flag destructiveHint on delete_account"
    d = destructive[0]

    if renderer_id in ("langchain", "pydantic_ai"):
        # Both verified to retain annotations on the tool's metadata: the model is
        # blind to the structured hint, but the framework did not destroy it.
        assert d.category == "transformative", (
            f"{renderer_id}: expected retained-but-not-surfaced, got {d.category}"
        )
        assert "not surfaced" in d.detail
    else:
        # Unknown framework: just assert the signal does not reach the model unchanged.
        assert d.category in ("transformative", "lossy")


@pytest.mark.skipif(
    "pydantic_ai" not in RENDERERS,
    reason="pydantic_ai renderer not installed",
)
def test_pydantic_ai_renderer_uses_current_mcp_toolset():
    from pydantic_ai.mcp import MCPToolset

    renderer = RENDERERS["pydantic_ai"]
    toolset = renderer._build_server(_handle())

    assert isinstance(toolset, MCPToolset)
