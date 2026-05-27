"""Layer 2 — behavioral evaluation.

Layer 1 (the structural diff) tells you *what* each framework changed about a
tool. Layer 2 tells you *whether the change matters*: does the model still
select the right tool and fill the right arguments when it sees the framework's
transformed version instead of the server's original?

This is built on Arcade's `arcade_evals` library. We use its comparative-track
feature: each framework's transformed tool definitions become a "track," the
same user prompt runs against every track, and field-level critics score the
resulting tool call. The output is a per-framework pass/warn/fail, directly
comparable against the server-view control track.

No bespoke scoring — `arcade_evals` is the engine. mcp-mirror's job is to feed
it each framework's view and line up the results.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from arcade_evals import (
    EvalRubric,
    EvalSuite,
    ExpectedMCPToolCall,
    MCPToolDefinition,
    NumericCritic,
)


class SafeNumericCritic(NumericCritic):
    """NumericCritic that scores a missing (None) argument as a clean miss.

    The stock NumericCritic raises TypeError when the model omits the field
    entirely. For mcp-mirror that omission is a legitimate behavioral failure
    (the framework's representation led the model to drop a numeric arg), not
    an error — so we score it 0 instead of crashing the run.
    """

    def evaluate(self, expected: Any, actual: Any) -> dict[str, Any]:
        if actual is None:
            return {"match": False, "score": 0.0}
        return super().evaluate(expected, actual)

from mcp_mirror.capture import ALL_CAPTURES, capture_server_announcement
from mcp_mirror.spec import ServerSpec
from mcp_mirror.types import ToolView

SERVER_TRACK = "server"


@dataclass
class EvalCase:
    """One behavioral test: a user message and the tool call it should produce.

    `expected_tool` is the tool's name as the *server* announces it. Per track,
    we resolve it to whatever that framework renamed it to (CrewAI snake-cases,
    for example) so each track is scored against its own tool surface.
    """

    name: str
    user_message: str
    expected_tool: str
    expected_args: dict[str, Any] = field(default_factory=dict)
    critics: list[Any] = field(default_factory=list)


def tool_view_to_mcp_definition(view: ToolView) -> MCPToolDefinition:
    """Convert a captured ToolView into the MCPToolDefinition arcade_evals wants."""
    return MCPToolDefinition(
        name=view.name,
        description=view.description,
        inputSchema=view.parameters_schema,
    )


def _canonical(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "").replace(".", "")


def _resolve_tool_name(views: list[ToolView], server_tool: str) -> str | None:
    """Find this track's name for a tool the server calls `server_tool`."""
    target = _canonical(server_tool)
    for v in views:
        if _canonical(v.name) == target:
            return v.name
    return None


async def eval_across_frameworks(
    spec: ServerSpec,
    frameworks: list[str],
    cases: list[EvalCase],
    *,
    model: str = "gpt-4o",
    num_runs: int = 1,
) -> dict[str, dict[str, Any]]:
    """Run the same cases against the server view and each framework view.

    Each track is evaluated in its own suite so that a representation the model
    provider *rejects* (e.g. OpenAI refuses `oneOf` in function parameters) is
    recorded as a finding for that track rather than aborting the whole run.

    Returns a dict keyed by track name. Each value is either:
      - ``{"cases": [...]}`` with per-case ``passed``/``warning``/``score``, or
      - ``{"rejected": True, "reason": "..."}`` if the provider refused the
        track's tool schema outright.
    """
    from openai import AsyncOpenAI, BadRequestError

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (resolve it via `op run` or .env).")

    # 1. Capture the server view and each framework view.
    server_views = (await capture_server_announcement(spec)).views
    track_views: dict[str, list[ToolView]] = {SERVER_TRACK: server_views}
    for fw in frameworks:
        try:
            result = await ALL_CAPTURES[fw](spec)
        except Exception:
            continue
        track_views[fw] = result.views

    results: dict[str, dict[str, Any]] = {}
    async with AsyncOpenAI(api_key=api_key) as client:
        for track, views in track_views.items():
            suite = EvalSuite(
                name=f"mcp-mirror [{track}]",
                system_message=(
                    "You are an agent with access to the provided tools. Choose the "
                    "single best tool for the user's request and call it with correct "
                    "arguments. If no tool fits, do not call one."
                ),
                rubric=EvalRubric(fail_threshold=0.8, warn_threshold=0.9),
            )
            suite.add_tool_definitions([tool_view_to_mcp_definition(v) for v in views])
            for case in cases:
                track_tool = _resolve_tool_name(views, case.expected_tool)
                if track_tool is None:
                    continue
                suite.add_case(
                    name=case.name,
                    user_message=case.user_message,
                    expected_tool_calls=[ExpectedMCPToolCall(track_tool, case.expected_args)],
                    critics=list(case.critics),
                )
            try:
                results[track] = await suite.run(
                    client, model=model, provider="openai", num_runs=num_runs
                )
            except BadRequestError as exc:
                # The provider refused this representation's schema outright.
                # That is itself a result: the model could not be offered the tool.
                msg = exc.message if hasattr(exc, "message") else str(exc)
                results[track] = {"rejected": True, "reason": msg}
            except Exception as exc:  # noqa: BLE001 — a bad track shouldn't sink the run
                results[track] = {"errored": True, "reason": f"{type(exc).__name__}: {exc}"}
    return results


def summarize(results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Reduce raw arcade_evals output to per-track pass/warn/fail counts.

    A track the provider rejected is reported with ``rejected=True`` so callers
    can distinguish "the model used the tool badly" from "the model was never
    able to receive the tool at all."
    """
    summary: dict[str, dict[str, Any]] = {}
    for track, payload in results.items():
        if payload.get("rejected"):
            summary[track] = {"rejected": True, "reason": payload.get("reason", "")}
            continue
        if payload.get("errored"):
            summary[track] = {"errored": True, "reason": payload.get("reason", "")}
            continue
        passed = warned = failed = 0
        for case in payload.get("cases", []):
            if case.get("passed"):
                passed += 1
            elif case.get("warning"):
                warned += 1
            else:
                failed += 1
        summary[track] = {"passed": passed, "warned": warned, "failed": failed}
    return summary
