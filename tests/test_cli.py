"""Smoke tests for the CLI."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from mcp_mirror.cli import main


def _run(*args: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(args)
    assert rc == 0, f"CLI exited with {rc}"
    return buf.getvalue()


def test_cli_default_summary_includes_all_frameworks() -> None:
    out = _run()
    # The frameworks that are installed and supported at this version of mcp-mirror.
    for fw in ("langchain", "llamaindex", "crewai", "pydantic-ai"):
        assert fw in out, f"expected {fw} in scorecard output, got:\n{out}"


def test_cli_filter_framework() -> None:
    out = _run("--framework", "pydantic-ai")
    assert "pydantic-ai" in out
    assert "langchain" not in out


def test_cli_filter_tool() -> None:
    out = _run("--tool", "send_message")
    assert "send_message" in out
    assert "search_records" not in out


def test_cli_json_output_is_valid() -> None:
    out = _run("--json")
    parsed = json.loads(out)
    assert "diffs" in parsed
    assert len(parsed["diffs"]) > 0
    sample = parsed["diffs"][0]
    assert "tool" in sample
    assert "framework" in sample
    assert "overall" in sample


def test_cli_detail_includes_breakdown() -> None:
    out = _run("--detail")
    assert "===" in out  # detail section headers
    assert "deltas:" in out or "(no differences detected)" in out
