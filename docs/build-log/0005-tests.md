# 0005 — Tests

**Date:** 2026-05-20
**Status:** Done. 16 passing.

## What we test

### Unit: `tests/test_diff.py`

Validates the diff engine independent of any framework. Constructs synthetic `ToolView`s with known differences and asserts the engine categorizes correctly.

Covers:
- Identical views → `FAITHFUL`, no field diffs.
- Dropped fields → `LOSSY`.
- Added metadata → `ADDITIVE`.
- Type changes → `TRANSFORMATIVE`.
- Truncated description → `LOSSY` with a substring detection.
- Overall-category = worst-of (lossy > transformative > additive > faithful).

These tests are deterministic, fast, and don't touch any framework code.

### Integration: `tests/test_capture.py`

Runs every real framework capture against the bundled MCP server. Asserts framework-specific properties that should be true given each adapter's documented behavior.

Covers:
- Server announcement: rich-schema fixtures flow through MCP correctly.
- LangChain: drops response schema and `_meta`, preserves input schema.
- Pydantic AI: faithful (only additive deltas allowed).
- LlamaIndex: produces either lossy or additive deltas (signals restructuring).

These tests spawn `python -m mcp_mirror.server` as a subprocess via the real MCP stdio transport. They will catch real regressions in either our code or the upstream frameworks.

### Smoke: `tests/test_cli.py`

End-to-end CLI runs. Captures stdout and asserts on the rendered scorecard.

Covers:
- Default run includes all installed frameworks.
- `--framework` filter restricts output.
- `--tool` filter restricts output.
- `--json` produces parseable JSON with the expected schema.
- `--detail` produces per-tool blocks.

## Test runtime

The full suite runs in ~11 seconds. Most of that is the four integration tests each spawning the MCP server subprocess and loading framework adapters.

## What we don't test (yet)

- **Live LLM calls.** Once `OPENAI_API_KEY` wiring lands (build-log/0007), we'll add tests that capture the actual OpenAI request payload from each framework and diff it against the introspected view. This will catch cases where introspection-time and inference-time representations diverge.
- **Arcade as MCP source.** When the `ARCADE_API_KEY` path lands, tests that point at Arcade's real MCP server and assert on the actual tool catalog.
- **Framework version drift.** A future CI-mode test that snapshots the scorecard against pinned framework versions and asserts no new regressions.

## Next

`0006-github-setup.md` — getting the repo on GitHub.
