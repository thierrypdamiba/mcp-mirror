"""Offline unit tests for Layer 2 logic (no network / no model calls).

The live behavioral run is exercised manually with OPENAI_API_KEY; these tests
cover the deterministic glue: tool-definition conversion, per-track tool-name
resolution, the None-safe numeric critic, and the summarizer.
"""

from __future__ import annotations

import pytest

pytest.importorskip("arcade_evals")  # skip cleanly if the eval extra isn't installed

from mcp_mirror.llm_eval import (  # noqa: E402
    SafeNumericCritic,
    _resolve_tool_name,
    summarize,
    tool_view_to_mcp_definition,
)
from mcp_mirror.types import ToolView  # noqa: E402


def _view(name: str) -> ToolView:
    return ToolView(
        name=name,
        description="d",
        parameters_schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )


def test_tool_view_to_mcp_definition() -> None:
    d = tool_view_to_mcp_definition(_view("Github_CreateIssue"))
    assert d["name"] == "Github_CreateIssue"
    assert d["inputSchema"]["type"] == "object"
    assert "description" in d


def test_resolve_tool_name_matches_across_casing() -> None:
    views = [_view("github_create_issue")]  # framework renamed to snake_case
    # server announced it as Github_CreateIssue; resolution should still match
    assert _resolve_tool_name(views, "Github_CreateIssue") == "github_create_issue"


def test_resolve_tool_name_returns_none_when_absent() -> None:
    assert _resolve_tool_name([_view("other_tool")], "Github_CreateIssue") is None


def test_safe_numeric_critic_handles_missing_arg() -> None:
    critic = SafeNumericCritic(critic_field="limit", weight=1.0, value_range=(1, 10))
    # Model omitted the field entirely -> clean miss, not a crash.
    result = critic.evaluate(expected=5, actual=None)
    assert result["match"] is False
    assert result["score"] == 0.0


def test_safe_numeric_critic_scores_present_value() -> None:
    critic = SafeNumericCritic(critic_field="limit", weight=1.0, value_range=(1, 10))
    result = critic.evaluate(expected=5, actual=5)
    assert "score" in result


def test_summarize_counts_and_states() -> None:
    raw = {
        "server": {"rejected": True, "reason": "oneOf not permitted"},
        "ag2": {"cases": [{"passed": True}, {"warning": True}, {"passed": False}]},
        "llamaindex": {"errored": True, "reason": "Boom"},
    }
    summ = summarize(raw)
    assert summ["server"]["rejected"] is True
    assert summ["ag2"] == {"passed": 1, "warned": 1, "failed": 1}
    assert summ["llamaindex"]["errored"] is True
