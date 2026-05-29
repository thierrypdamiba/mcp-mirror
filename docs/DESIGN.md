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

The adapter diff tells you *what changed and where*; the model eval tells you *whether it matters*. Build both. Compose them. Same MCP server, every framework, side by side.

mcp-mirror captures one MCP server through each framework's *actual* published MCP integration — no simulators, no recorded fixtures. Each capture produces a normalized `ToolView`. Two layers consume those views:

- **Layer 1: Adapter diff.** Recursively compare each framework's `ToolView` to the server's announcement; record every dropped, added, and rewritten field. Microseconds per tool. Pure stdlib. This is a deterministic regression detector and localizer, not a severity classifier.
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

### 2. Adapter diff engine (Layer 1)

`src/mcp_mirror/diff.py` — recursive JSON-Schema walker. The per-tool overall category is the *worst* category across all field diffs (severity: `faithful` < `additive` < `transformative` < `lossy`), so one dropped `enum` makes the whole tool `lossy` even if every other field is preserved.

That overall category is notation, not the finding. On the live Arcade gateway, four of five frameworks are `lossy` on every tool, so the verdict alone saturates. The useful signal is the exact path and pattern: LangChain drops the same `metadata.arcade` block on all 100 tools (`-1 +1`), while CrewAI and LlamaIndex rewrite complex schemas heavily (for `Linear_CreateIssue`, `-16 ~1 +45` and `-16 +43`). Layer 1 is the map and regression signal; Layer 2 supplies impact.

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

What the user actually sees, today, against the live Arcade gateway:

### Scorecard excerpt

```
tool                ag2       crewai        langchain  llamaindex  pydantic-ai
----------------------------------------------------------------------------
Linear_CreateIssue  -4 +1     -16 ~1 +45    -1 +1      -16 +43     +1
legend:  = faithful   + additive   - lossy   ~ transformative
         counts are field-level deltas vs. the server announcement
```

The full committed sample run covers 100 Arcade gateway tools across five frameworks. The aggregate pattern is the real finding: Pydantic AI adds one metadata field and drops nothing; LangChain always drops only `metadata.arcade` and adds one LangChain class marker; AG2 does a mild, uniform schema simplification; CrewAI and LlamaIndex perform large schema rewrites that worsen on complex tools.

### Drill-down (`--detail`)

```
=== Linear_CreateIssue @ crewai ===
overall: lossy
deltas: lossy=16, transformative=1, additive=45

  ~ name
      Tool name was rewritten by the framework.
  + description
      Description extended by framework (312 -> 3136 chars).
  - parameters.properties.priority.enum
      Framework dropped `enum`.
  - parameters.properties.labels_to_add.items
      Framework dropped `items`.
  - parameters.properties.estimate.type
      Framework dropped `type`.
  + parameters.properties.priority.anyOf
      Framework added `anyOf` not present on server.
  + metadata.__crewai_tool_class
      Framework added metadata `__crewai_tool_class`.
```

### Layer 2 summary (bundled fixture)

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

The `rejected` track is the interesting one: a representation can look structurally close and still be unusable if the provider refuses the schema. Layer 1 cannot tell you that; Layer 2 surfaces it explicitly. The live gateway Layer 2 run is Phase 2 because it needs golden cases for real Arcade tools rather than the bundled fixtures.

## Project layout

```
src/mcp_mirror/
  arcade_auth.py     # RFC 9728/7591/7636/8707 OAuth client
  capture.py         # 6 captures (server + 5 frameworks) + ALL_CAPTURES registry
  cli.py             # `mcp-mirror` entrypoint + zero-dep .env loader
  diff.py            # Layer 1 — recursive adapter diff
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
| **Two layers — deterministic and behavioral** | A complete adapter diff plus a prompt-based behavioral eval | The diff is deterministic and localizes changes across every tool; the eval is partial and slower but supplies impact. Neither answer substitutes for the other. | Diff-only (rejected: false equivalence between harmless and breaking deltas); behavioral-only (rejected: too slow and expensive to run across every tool, and weak at root cause). |
| **Score against per-case ground truth, not the framework's schema** | Layer 2 critics check generated arguments against `expected_args` written for each case | The target failure is a framework relaxing a constraint and the model emitting a value the framework accepts but the real tool rejects — caught only by scoring against ground truth. | Validate against framework schema (rejected: hides the exact bug we're looking for); validate against the server's JSON Schema only (rejected: structural-only, misses semantic correctness). |
| **Per-track suite, not a single comparative suite** | Each framework's view runs in its own `EvalSuite`; results are aggregated after | A provider that refuses one framework's schema (e.g., OpenAI rejecting `oneOf`) would sink a single comparative suite; per-track isolation turns that refusal into `rejected=True` for one track instead of an error for all. | `add_comparative_case` across one suite (rejected: schema rejections are suite-fatal, not local). |
| **MCP surface of `arcade_evals`, not the catalog surface** | Use `MCPToolDefinition` + `ExpectedMCPToolCall` instead of `@tool_eval` + `ExpectedToolCall` | mcp-mirror's input is raw MCP tool definitions, not registered Arcade tools — the catalog surface needs a `ToolCatalog` populated from Python modules we don't have. | `ToolCatalog` + `@tool_eval` (rejected: would require wrapping every captured view in a fake catalog entry just to satisfy the decorator). |
| **Spec-correct OAuth via Dynamic Client Registration** | RFC 9728 discovery → RFC 7591 DCR → RFC 7636 PKCE → RFC 8707 resource | A raw API key as a Bearer is rejected (401) by the gateway — this is the flow a real MCP client uses, so captures reflect production. | API-key bearer (rejected: 401); static client_id (rejected: not portable across gateways without prior coordination). |

## Benefits

1. **Adapter regression signal in seconds.** Capture + diff a gateway across five frameworks and see exactly which fields changed since the last run.
2. **Complete structural coverage.** Layer 1 covers every announced tool without golden cases; on the live gateway that is 100 tools x 5 frameworks.
3. **Behavior, not just structure.** Field-level critics score generated arguments against the server's contract — catches framework-relaxed constraints the deterministic diff cannot rank by impact.
4. **Root cause for behavioral failures.** Layer 2 says "the model omitted `priority`"; Layer 1 says "the adapter dropped `priority.enum` and rewrote the field shape."
5. **Provider rejection is a finding, not an error.** When OpenAI refuses a representation's schema, that's `rejected=True` for that track, not a crash for the whole run.
6. **No bespoke harness.** Reuses `arcade_evals` (engine, critics, rubrics) and Arcade's gateway OAuth — mcp-mirror adds the framework loop, not the eval engine.
7. **Public artifact, runnable today.** Open-source repo (`github.com/thierrypdamiba/mcp-mirror`), sample run against the live Arcade gateway committed at `docs/sample-runs/`.

## Migration Path

### Phase 1 — both layers built (today)
- 5 framework captures + server ground-truth, transport-agnostic.
- Layer 1 adapter diff + scorecard + drill-down.
- Layer 2 on `arcade_evals` with per-track isolation and `SafeNumericCritic`.
- Golden case set for the bundled reference tools (`send_message`, `search_records`).
- Sample run against the live Arcade gateway committed at `docs/sample-runs/arcade-mcp-mirror-gateway.json`.
- RFC 9728/7591/7636/8707 OAuth against the production gateway.

### Phase 2 — real-tool eval coverage
- Golden cases for high-traffic Arcade toolkits (`Github_*`, `Linear_*`, `Gmail_*`, `Slack_*`). One case per tool that probes a schema feature the adapter diff flags as risky (`enum`, `required`, `oneOf`, numeric bounds).
- Stretch: per-toolkit summary view in the scorecard ("LangChain is lossy on 11/52 Linear tools, faithful on Gmail").

### Phase 3 — distractor + per-model studies
- Distractor-tool set sizing for selection tests (currently undefined; today's eval uses a small fixed catalog).
- Run Layer 2 across `gpt-4o`, Claude, Gemini, Llama and report where the same framework view scores differently per model. Cost-gated; not every PR runs all four.

### Phase 4 — scorecard service (optional)
- CI hook + JSON scorecard format so framework maintainers can run mcp-mirror on PR and surface regressions.
- Conditional on whether the manual run pattern proves insufficient — defer until there is real demand from a framework maintainer.

## Related Work

mcp-mirror's axis is adapter fidelity: hold one MCP server constant, vary the framework adapter, and inspect the tool representation that reaches the model.

| Work | What it measures | Why mcp-mirror is different |
| ---- | ---------------- | --------------------------- |
| **Arcade ToolBench** | MCP server quality: definition quality, protocol compliance, security, supportability | Grades the server before any framework consumes it; mcp-mirror measures what adapters do after consumption. |
| **MCP conformance suites** | Whether clients, servers, and SDKs implement the MCP specification correctly | Protocol conformance can pass while a framework still rewrites the model-facing tool schema. |
| **BFCL / tau-bench** | Model or agent tool-use ability | Vary the model/agent; mcp-mirror varies the adapter over a fixed server. |
| **MCP-Bench / MCP-Atlas / MCPVerse** | Tool-use competency over real MCP servers and larger tool spaces | Benchmark end-task success; mcp-mirror diagnoses adapter transformation before task execution. |
| **Fan et al., information-fidelity martingale analysis** | Theoretical error accumulation across sequential MCP tool calls | Useful background for fidelity as a reliability concern; not an empirical cross-framework adapter study. |

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
- Related-work anchors: Arcade ToolBench (`https://www.arcade.dev/blog/introducing-toolbench-quality-benchmark-mcp-servers/`), MCP conformance (`https://github.com/modelcontextprotocol/conformance`), BFCL (`https://www2.eecs.berkeley.edu/Pubs/TechRpts/2025/EECS-2025-184.html`), MCP-Bench (`https://openreview.net/pdf?id=fe8mzHwMxN`), MCP-Atlas (`https://arxiv.org/abs/2602.00933`), MCPVerse (`https://arxiv.org/abs/2508.16260`), Fan et al. information fidelity (`https://arxiv.org/abs/2602.13320`).
