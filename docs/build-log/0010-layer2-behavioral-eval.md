# 0010 — Layer 2: behavioral eval on arcade_evals

**Date:** 2026-05-27
**Status:** Built and wired. Live run gated only by 1Password Touch ID approval.

## What this is

Layer 1 (the structural diff) counts *what* each framework changed about a tool. Layer 2 answers *whether the change matters*: given a framework's transformed tool view, does the model still select the right tool and fill the right arguments? Built on Arcade's `arcade_evals` — not a bespoke scorer.

## Why arcade_evals

A colleague flagged that "you can't do intent with numbers." Correct: a `-1 lossy` on a `title` field and a `-1 lossy` on an `enum` are identical structurally but opposite in impact. Only running prompts through a model separates them. Arcade already ships the engine for exactly that (`EvalSuite`, field-level critics, comparative tracks), so Layer 2 wraps it rather than reinventing tool-call scoring.

## How it works

- `llm_eval.py`: captures the server view + each framework view, registers each as an `arcade_evals` track via `add_tool_definitions`, runs the golden cases per track, and scores with critics.
- Each track runs in its **own suite** (not one shared `run_comparative`) so a representation the provider *rejects* is recorded as a finding for that track instead of aborting the whole run.
- `eval_cases.py`: 4 hand-written golden cases for the bundled fixtures, deliberately probing the fields frameworks mangle — the `priority` enum on `send_message`, the numeric `confidence_threshold`/`limit` on `search_records`.
- CLI: `mcp-mirror --eval [--model gpt-4o]`.

## Two findings that only Layer 2 could surface

### 1. Faithful isn't always usable

The bundled `send_message` uses `oneOf` on its `recipient` argument. OpenAI's function-calling API **rejects `oneOf` outright** ("'oneOf' is not permitted"). Consequences:

- `server`, `langchain`, `pydantic-ai`, `crewai` tracks → **REJECTED by the provider**. The model can never even be offered the tool.
- `ag2`, `llamaindex` tracks → **accepted**, because they flatten/restructure the `oneOf` away.

Layer 1 calls Pydantic AI the "most faithful" framework. Layer 2 shows that on this tool, faithfulness means passing through a schema the model provider refuses — while the "most invasive" frameworks are the ones that make the tool usable at all. That inversion is the headline argument for why the behavioral layer is necessary.

### 2. Missing-argument handling

When a framework's representation led the model to omit a numeric argument, the stock `NumericCritic` raised `TypeError` on `float(None)`. That omission is a legitimate behavioral failure, not an error. `SafeNumericCritic` scores it `0.0` (clean miss) so the run completes and the failure is counted correctly.

## Robustness decisions

- Per-track isolation: `BadRequestError` → `{"rejected": True}`; any other exception → `{"errored": True}`. One bad track never sinks the run.
- `SafeNumericCritic` subclass handles `None` arguments.
- `summarize()` distinguishes `rejected` / `errored` / `passed-warned-failed` so the three outcomes are never conflated.

## Dependencies

Added a `[eval]` extra: `arcade-ai` (provides `arcade_evals`), `openai`, plus the eval engine's own needs `pytz`, `scipy`, `scikit-learn` (these were missing from the base `arcade-ai` install and are required by the datetime critics, optimal tool-call matching, and TF-IDF similarity respectively).

## Tests

6 offline unit tests (`tests/test_llm_eval.py`): tool-definition conversion, cross-casing tool-name resolution, `SafeNumericCritic` None handling, and the summarizer's three-state output. Skipped cleanly if the eval extra isn't installed. Total suite: 24 passing.

## Open follow-ups

- Generated prompt batteries for real Arcade tools (the golden set only covers the two bundled fixtures).
- The live headline run against the Arcade gateway — Arcade's tools are LLM-ready (no raw `oneOf`), so they exercise the *behavioral-delta* path cleanly rather than the rejection path.
