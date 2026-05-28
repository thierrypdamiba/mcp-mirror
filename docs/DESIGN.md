# Design: mcp-mirror

**Author**: Thierry Damiba (thierry@arcade.dev)
**Status**: Draft

**Related**: README: `../README.md` | Build log: `build-log/` | Sample data: `sample-runs/`

## Executive Summary

mcp-mirror connects one MCP server to five real agent frameworks at once (LangChain, LlamaIndex, CrewAI, Pydantic AI, AG2), captures what each one hands to the LLM, and tells you both what differs structurally and what differs *behaviorally*. The work that today lives in scattered Slack threads and private debugging notes becomes a single open-source artifact you can run on your own server in under a minute.

## The Problem

The framework adapter layer between an MCP server and the LLM is real, and every framework lands somewhere different:

- A `oneOf` in an input schema survives in some adapters and gets flattened by others.
- LlamaIndex's Pydantic regeneration explodes a clean schema into `$defs`-driven additive deltas.
- CrewAI snake-cases tool names — the model sees `send_message`, the server announces `SendMessage`.
- Descriptions get truncated. Response schemas get dropped entirely. Server metadata that signals required auth scopes gets rewritten or lost.
- OpenAI rejects `oneOf` in function parameters outright — the tool simply does not reach the model.

Today the only way to know which transformation your framework is doing is to integrate it yourself and read the bytes. There is no public scorecard, no shared vocabulary, no measurement story for the layer that the LLM actually consumes.

## The Solution: Real Captures + Two-Layer Eval

### Key Insight

A structural diff tells you *what* changed, but only running prompts through a model tells you *whether the change matters*. Build both. Compose them. Same MCP server, every framework, side by side.

mcp-mirror captures one MCP server through each framework's *actual* published MCP integration — no simulators, no recorded fixtures. Each capture produces a normalized `ToolView`. Two layers consume those views:

- **Layer 1: Structural diff.** Recursively compare each framework's `ToolView` to the server's announcement; categorize every field-level delta as `faithful`, `lossy`, `additive`, or `transformative`. Microseconds per tool. Pure stdlib.
- **Layer 2: Behavioral eval.** Run the same eval cases against each framework's transformed view via `arcade_evals` and score selection + argument accuracy against per-case ground truth. Per-track `EvalSuite` so a representation OpenAI refuses outright (e.g., `oneOf` in function parameters) is recorded as `rejected=True` for that track, not a fatal error for all.

Both layers ship today.

## Implementation

### 1. Capture

`src/mcp_mirror/capture.py` — one async function per framework, transport-agnostic via a shared `_session(spec)` context manager (stdio or streamable-HTTP behind the same interface).

```python
async def capture_server_announcement(spec: ServerSpec) -> CaptureResult: ...
async def capture_langchain(spec: ServerSpec) -> CaptureResult: ...
# plus capture_llamaindex / capture_crewai / capture_pydantic_ai / capture_ag2

ALL_CAPTURES: dict[str, CaptureFn] = {
    "mcp-server":  capture_server_announcement,  # ground-truth (mcp SDK)
    "langchain":   capture_langchain,             # langchain-mcp-adapters
    "llamaindex":  capture_llamaindex,            # llama-index-tools-mcp
    "pydantic-ai": capture_pydantic_ai,           # pydantic_ai.mcp
    "ag2":         capture_ag2,                   # autogen.mcp.mcp_client
    "crewai":      capture_crewai,                # crewai_tools.MCPServerAdapter
}

@dataclass
class CaptureResult:
    framework: str
    framework_version: str | None   # importlib.metadata, recorded per run
    views: list[ToolView]
    notes: str = ""
```

`capture_server_announcement` is the ground-truth view (the server's `tools/list` response via the official MCP Python SDK). Every framework view is diffed against it.

### 2. Diff engine (Layer 1)

`src/mcp_mirror/diff.py` — recursive JSON-Schema walker. The per-tool overall category is the *worst* category across all field diffs (severity: `faithful` < `additive` < `transformative` < `lossy`), so one dropped `enum` makes the whole tool `lossy` even if every other field is preserved.

```python
def diff_views(server: ToolView, framework: ToolView, framework_name: str) -> ToolDiff: ...

class Category(str, Enum):
    FAITHFUL = "faithful"             # no change
    LOSSY = "lossy"                   # server field dropped
    ADDITIVE = "additive"             # framework field added
    TRANSFORMATIVE = "transformative" # value changed in place
```

### 3. Behavioral eval (Layer 2)

`src/mcp_mirror/llm_eval.py` — wraps `arcade_evals`. One `EvalSuite` per track so a provider's schema rejection isolates to that track instead of aborting the run. Uses the MCP-tool surface of `arcade_evals` (`MCPToolDefinition` + `ExpectedMCPToolCall`) because the inputs are raw MCP tool definitions, not registered Arcade catalog tools.

```python
async def eval_across_frameworks(
    spec: ServerSpec,
    frameworks: list[str],
    cases: list[EvalCase],
    *,
    model: str = "gpt-4o",
    num_runs: int = 1,
) -> dict[str, dict[str, Any]]: ...

def summarize(results) -> dict[str, dict[str, Any]]: ...  # per-track pass/warn/fail/rejected
```

`SafeNumericCritic` subclasses `arcade_evals.NumericCritic` to treat a missing argument as a clean score-0 miss instead of letting the underlying critic raise. A framework dropping a numeric field and the model then omitting it is a legitimate behavioral failure to report, not an error to crash on.

### 4. Arcade OAuth

`src/mcp_mirror/arcade_auth.py` — spec-correct flow against the gateway:

```
RFC 9728 (discovery via WWW-Authenticate)
  → RFC 7591 (Dynamic Client Registration)
  → RFC 7636 (PKCE)
  → RFC 8707 (resource indicator = the gateway URL)
```

Token cached at `~/.cache/mcp-mirror/`. One browser step on first run; silent thereafter. A raw API-key Bearer is rejected (401) by the gateway, so this is the only flow that yields production-fidelity captures.

## Output

What the user actually sees, today, against the bundled reference server with all five frameworks installed:

### Scorecard

```
tool                  ag2           crewai        langchain     llamaindex    pydantic-ai
------------------------------------------------------------------------------------------
send_message          -10 +1        -11 ~1 +12    -6 +1         -12 +9        +1
search_records        -9 +1         -14 ~2 +12    -6 +1         -13 +9        +1
legend:  = faithful   + additive   - lossy   ~ transformative
         counts are field-level deltas vs. the server announcement
```

### Drill-down (`--detail`)

```
=== send_message @ langchain ===
overall: lossy
deltas: lossy=6, additive=1

  - response.type
      Framework dropped `type`.
  - response.properties
      Framework dropped `properties`.
  - parameters.properties.priority.enum
      Framework dropped `enum`.       # <-- the kind of finding Layer 2 promotes
  + metadata.__lc_tool_class
      Framework added `__lc_tool_class` not present on server.
```

### Layer 2 summary

```json
{
  "server":      { "passed": 4, "warned": 0, "failed": 0 },
  "langchain":   { "passed": 3, "warned": 1, "failed": 0 },
  "llamaindex":  { "passed": 2, "warned": 1, "failed": 1 },
  "crewai":      { "passed": 2, "warned": 0, "failed": 2 },
  "pydantic-ai": { "passed": 4, "warned": 0, "failed": 0 },
  "ag2":         { "rejected": true, "reason": "Invalid schema for function 'send_message': oneOf is not permitted." }
}
```

The `rejected` track is the interesting one: the structural diff says AG2 is *mostly faithful*, but the model never sees the tool because OpenAI refuses the schema. Layer 1 cannot tell you that; Layer 2 surfaces it explicitly.

## Project layout

```
src/mcp_mirror/
  arcade_auth.py     # RFC 9728/7591/7636/8707 OAuth client
  capture.py         # 6 captures (server + 5 frameworks) + ALL_CAPTURES registry
  cli.py             # `mcp-mirror` entrypoint + zero-dep .env loader
  diff.py            # Layer 1 — recursive ToolView diff
  eval_cases.py      # Golden behavioral cases for the bundled fixtures
  fixtures.py        # Reference tool surfaces (send_message, search_records)
  llm_eval.py        # Layer 2 — per-track arcade_evals suites + summarize()
  scorecard.py       # ASCII rendering for the per-tool / per-framework matrix
  server.py          # Bundled reference MCP server (stdio + HTTP)
  spec.py            # ServerSpec (stdio | http, command/args/url/headers)
  types.py           # ToolView, ToolDiff, FieldDiff, Category + severity order

docs/
  DESIGN.md
  build-log/         # numbered narrative of how we got here (0001…0010)
  sample-runs/       # captures against the live Arcade gateway, committed

tests/
  test_capture.py    # asserts each adapter's known transforms on the bundled server
  test_diff.py       # synthetic views, per-category + worst-wins overall
  test_llm_eval.py   # tool-name resolution across renames + rejected-track path
  test_cli.py        # argv → ServerSpec, .env loader, scorecard rendering
```

## Key Decisions

| Decision | Choice | Rationale | Alternatives considered |
| -------- | ------ | --------- | ----------------------- |
| **Real captures, never simulators** | Each capture exercises the framework's published MCP integration | An early simulator encoded assumptions the live run disproved (LangChain was *assumed* to collapse `oneOf`; it actually preserves the full input schema) — framework behavior drifts faster than docs. | Static schema analysis (rejected: misses runtime adapter transforms); recorded fixtures (rejected: rot the moment the adapter updates). |
| **Two layers — structural and behavioral** | A deterministic diff plus a prompt-based behavioral eval | A field count can't distinguish a dropped `title` (harmless) from a dropped `enum` (the model now emits invalid values) — both score `-1 lossy`; only observed behavior separates them. | Structural-only (rejected: false equivalence between harmless and breaking deltas); behavioral-only (rejected: too slow and expensive to run across every tool). |
| **Score against per-case ground truth, not the framework's schema** | Layer 2 critics check generated arguments against `expected_args` written for each case | The target failure is a framework relaxing a constraint and the model emitting a value the framework accepts but the real tool rejects — caught only by scoring against ground truth. | Validate against framework schema (rejected: hides the exact bug we're looking for); validate against the server's JSON Schema only (rejected: structural-only, misses semantic correctness). |
| **Per-track suite, not a single comparative suite** | Each framework's view runs in its own `EvalSuite`; results are aggregated after | A provider that refuses one framework's schema (e.g., OpenAI rejecting `oneOf`) would sink a single comparative suite; per-track isolation turns that refusal into `rejected=True` for one track instead of an error for all. | `add_comparative_case` across one suite (rejected: schema rejections are suite-fatal, not local). |
| **MCP surface of `arcade_evals`, not the catalog surface** | Use `MCPToolDefinition` + `ExpectedMCPToolCall` instead of `@tool_eval` + `ExpectedToolCall` | mcp-mirror's input is raw MCP tool definitions, not registered Arcade tools — the catalog surface needs a `ToolCatalog` populated from Python modules we don't have. | `ToolCatalog` + `@tool_eval` (rejected: would require wrapping every captured view in a fake catalog entry just to satisfy the decorator). |
| **Spec-correct OAuth via Dynamic Client Registration** | RFC 9728 discovery → RFC 7591 DCR → RFC 7636 PKCE → RFC 8707 resource | A raw API key as a Bearer is rejected (401) by the gateway — this is the flow a real MCP client uses, so captures reflect production. | API-key bearer (rejected: 401); static client_id (rejected: not portable across gateways without prior coordination). |

## Benefits

1. **Cross-framework parity in seconds.** Capture + diff a 50-tool gateway across 5 frameworks in under 30 seconds end-to-end (I/O-bound; the diff itself is microseconds).
2. **Behavior, not just structure.** Field-level critics score every generated argument against the server's contract — catches framework-relaxed constraints the structural diff cannot.
3. **Provider rejection is a finding, not an error.** When OpenAI refuses a representation's schema, that's `rejected=True` for that track, not a crash for the whole run.
4. **No bespoke harness.** Reuses `arcade_evals` (engine, critics, rubrics) and Arcade's gateway OAuth — mcp-mirror adds the framework loop, not the eval engine.
5. **Vocabulary teams can share.** `faithful` / `lossy` / `additive` / `transformative` — a four-word categorical lexicon that fits in a Slack message.
6. **No silent failures.** Every capture produces either a `ToolView` or a structured failure record; every Layer 2 track produces either pass/warn/fail counts or an explicit `rejected=True` / `errored=True` with reason.
7. **Public artifact, runnable today.** Open-source repo (`github.com/thierrypdamiba/mcp-mirror`), sample run against the live Arcade gateway committed at `docs/sample-runs/`.

## Migration Path

### Phase 1 — both layers built (today)
- 5 framework captures + server ground-truth, transport-agnostic.
- Layer 1 diff + categorical scorecard + drill-down.
- Layer 2 on `arcade_evals` with per-track isolation and `SafeNumericCritic`.
- Golden case set for the bundled reference tools (`send_message`, `search_records`).
- Sample run against the live Arcade gateway committed at `docs/sample-runs/arcade-mcp-mirror-gateway.json`.
- RFC 9728/7591/7636/8707 OAuth against the production gateway.

### Phase 2 — real-tool eval coverage
- Golden cases for high-traffic Arcade toolkits (`Github_*`, `Linear_*`, `Gmail_*`, `Slack_*`). One case per tool that probes a schema feature the structural diff flags as risky (`enum`, `required`, `oneOf`, numeric bounds).
- Stretch: per-toolkit summary view in the scorecard ("LangChain is lossy on 11/52 Linear tools, faithful on Gmail").

### Phase 3 — distractor + per-model studies
- Distractor-tool set sizing for selection tests (currently undefined; today's eval uses a small fixed catalog).
- Run Layer 2 across `gpt-4o`, Claude, Gemini, Llama and report where the same framework view scores differently per model. Cost-gated; not every PR runs all four.

### Phase 4 — scorecard service (optional)
- CI hook + JSON scorecard format so framework maintainers can run mcp-mirror on PR and surface regressions.
- Conditional on whether the manual run pattern proves insufficient — defer until there is real demand from a framework maintainer.

## Ownership

mcp-mirror is a Thierry research artifact today, in a public repo (`github.com/thierrypdamiba/mcp-mirror`). It does **not** ship inside `arcade/monorepo`. It complements Arcade's gateway without overlapping: the gateway is the *server-side* layer Arcade owns; mcp-mirror measures the *client-side* layer (framework adapters) that Arcade does not own but customers run every day.

If Arcade ever needs to publish a framework-compatibility statement — "the Arcade gateway is high-fidelity in LangChain and Pydantic AI, lossy in CrewAI on these specific surfaces" — mcp-mirror is the tool that produces the evidence. Promotion from research artifact to Arcade-maintained tool is a decision to make once the methodology is validated against real customer tool catalogs in Phase 2.

## Technical Details

**Constraints**:
- Python 3.10+ (3.13 dev). Core diff has zero third-party dependencies.
- Each framework is an optional extra (`pip install 'mcp-mirror[langchain]'` etc.), so the tool runs with any subset.
- Layer 2 requires `arcade-ai` (provides `arcade_evals`), `openai`, `pytz`, `scipy`, `scikit-learn`.

**Error handling**:
- A framework whose capture raises is skipped with a stderr warning, not fatal — the scorecard degrades gracefully.
- Framework tool-name rewrites (CrewAI → snake_case) are matched by a canonical key, then surfaced as a `transformative` delta on `name`.
- Layer 2: an `openai.BadRequestError` for a given track is recorded as `{"rejected": True, "reason": ...}` for that track only; any other exception is recorded as `{"errored": True, "reason": ...}`. Neither aborts other tracks.

**Gotchas**:
- The MCP SDK logs `Session termination failed: 202` on HTTP cleanup; harmless, suppressed via a scoped log filter.
- LlamaIndex routes schemas through Pydantic regeneration, producing large `$defs`-driven additive deltas that are structural, not semantic — exactly why Layer 2 matters.
- `SafeNumericCritic` exists because stock `NumericCritic` raises on a missing argument; the omission is a legitimate behavioral signal here, not an error.

## References

- MCP authorization: RFC 9728 (protected-resource metadata), RFC 7591 (DCR), RFC 8707 (resource indicators), RFC 7636 (PKCE).
- Live reference dataset: `docs/sample-runs/arcade-mcp-mirror-gateway.json` (committed; safe — provider metadata + secret *key names* only, no values).
- Behavioral layer built on Arcade's `arcade_evals` library (`EvalSuite`, critics, `add_tool_definitions`, `add_case`).
