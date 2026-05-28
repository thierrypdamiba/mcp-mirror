# Design: mcp-mirror

**Author**: Thierry Damiba (thierry@arcade.dev)
**Status**: Draft

**Related**: README: `../README.md` | Build log: `build-log/` | Sample data: `sample-runs/`

> Same MCP server, five real agent frameworks (LangChain, LlamaIndex, CrewAI, Pydantic AI, AG2), side-by-side view of what each one hands to the LLM. Open-source artifact + methodology. Both layers built today.

## Intent

The same MCP server behaves differently in LangChain than in CrewAI than in Pydantic AI. The framework adapter layer between MCP and the LLM is real and you've debugged it — what's missing is the map. mcp-mirror builds it by running your server through every framework's actual integration code path, capturing what each one would hand to the LLM, and reporting the differences in a categorical vocabulary the team can share.

The whole tool rests on one principle: **a structural diff tells you *what* changed, but only running prompts through a model tells you *whether the change matters*.** Two layers compose accordingly — Layer 1 is a deterministic field-level diff (microseconds per tool); Layer 2 is a behavioral eval built on `arcade_evals` that scores selection and argument accuracy against per-case ground truth. Layer 1 gives you the map of where each framework differs; Layer 2 gives you the evidence for which of those differences actually change model behavior.

## Personas

- **Framework maintainer** wants a deterministic answer to "did our last release change how MCP tools surface to the LLM?" Reads scorecards and field-level diffs.
- **Arcade engineer triaging a customer report** wants to see "is this customer's tool behaving differently because of LangChain, or because of our gateway?" Uses Layer 2 to compare a representation across frameworks under the same prompt.
- **MCP server author** wants to know "will my schema survive the trip to the model intact in every framework I claim to support?" Uses the scorecard to find dropped enums, truncated descriptions, additive bloat.

## Architecture

A single source (stdio or streamable-HTTP) feeds N framework adapters; each adapter's real integration code produces a normalized `ToolView`; a diff engine compares each view to the server's announcement; a behavioral layer measures whether the differences change model behavior.

```
source (stdio | HTTP+OAuth) → [5 framework adapters] → ToolView ×5
                                                          ├→ Layer 1: structural diff   (built)
                                                          └→ Layer 2: behavioral eval   (built)
```

## Components

### Component 1: Capture

**What**: Load a server's tools through one framework's real MCP integration and normalize what it exposes to the LLM.
**Where**: `src/mcp_mirror/capture.py`
**Interface**:

```python
async def capture_server_announcement(spec: ServerSpec) -> CaptureResult: ...
async def capture_langchain(spec: ServerSpec) -> CaptureResult: ...
# plus capture_llamaindex / capture_crewai / capture_pydantic_ai / capture_ag2
# all transport-agnostic via the _session(spec) context manager

ALL_CAPTURES: dict[str, CaptureFn] = {
    "mcp-server":  capture_server_announcement,
    "langchain":   capture_langchain,
    "llamaindex":  capture_llamaindex,
    "pydantic-ai": capture_pydantic_ai,
    "ag2":         capture_ag2,
    "crewai":      capture_crewai,
}

@dataclass
class CaptureResult:
    framework: str
    framework_version: str | None   # from importlib.metadata, recorded per run
    views: list[ToolView]
    notes: str = ""
```

`capture_server_announcement` is the ground-truth view (the server's `tools/list` response via the official MCP Python SDK). Every framework view is diffed against this one. Layer 2 calls into `ALL_CAPTURES` directly to materialize per-track tool definitions.

**Dependencies**: the five framework packages (optional extras), `mcp` SDK, `ServerSpec`.
**Tests**: `tests/test_capture.py` — asserts each adapter's known behavior against the bundled server.

### Component 2: Diff engine (Layer 1)

**What**: Recursively compare a framework `ToolView` to the server's and categorize every field-level delta. The per-tool overall category is the *worst* category across all field diffs (severity order: faithful < additive < transformative < lossy), so any single dropped `enum` makes the whole tool "lossy" even if every other field is preserved.
**Where**: `src/mcp_mirror/diff.py`, `src/mcp_mirror/types.py`
**Interface**:

```python
def diff_views(server: ToolView, framework: ToolView, framework_name: str) -> ToolDiff: ...

class Category(str, Enum):
    FAITHFUL = "faithful"   # no change
    LOSSY = "lossy"         # server field dropped
    ADDITIVE = "additive"   # framework field added
    TRANSFORMATIVE = "transformative"  # value changed in place
```

**Dependencies**: none beyond stdlib.
**Tests**: `tests/test_diff.py` — synthetic views with known deltas verify both the per-field categories and the worst-wins overall.

### Component 3: Behavioral eval (Layer 2)

**What**: Run the same eval cases against each framework's transformed tool view and compare selection + argument scores. Built on Arcade's existing `arcade_evals` library — not a bespoke harness.
**Where**: `src/mcp_mirror/llm_eval.py`, `src/mcp_mirror/eval_cases.py`
**Interface**:

```python
from arcade_evals import EvalRubric, EvalSuite, ExpectedMCPToolCall, MCPToolDefinition

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

Each track (server view + every framework view) runs in its **own** `EvalSuite` — not a single suite with comparative cases. This is deliberate: if OpenAI rejects a representation's schema outright (e.g., `oneOf` in function parameters), that's recorded as `{"rejected": True, "reason": ...}` for *that track only*, instead of aborting the run.

mcp-mirror uses the MCP-tool surface of `arcade_evals` (`MCPToolDefinition`, `ExpectedMCPToolCall`) rather than the catalog surface (`@tool_eval`, `ExpectedToolCall`) that the worker toolkit evals use — because the inputs here are raw MCP tool definitions, not registered Arcade tools. Critics score generated arguments field-by-field against per-case ground-truth values derived from the server's contract.

A small subclass, `SafeNumericCritic`, treats a missing argument as a clean score-0 miss rather than letting the underlying `NumericCritic` raise. The framework dropping a numeric field and the model then omitting it is a legitimate behavioral failure to report, not an error to crash on.

**Dependencies**: `arcade-ai` (provides `arcade_evals`), `openai`, `pytz`, `scipy`, `scikit-learn`, a model provider key. Reuses Arcade's eval engine and critics rather than reinventing scoring.
**Tests**: `tests/test_llm_eval.py` exercises tool-name resolution across renames and the rejected-track path; `eval_cases.py` defines a golden case set for the bundled reference tools.

### Component 4: Arcade auth

**What**: Authenticate to an Arcade MCP gateway exactly as a production client would.
**Where**: `src/mcp_mirror/arcade_auth.py`
**Interface**:

```python
def get_access_token(gateway_url: str, *, force_reauth: bool = False) -> str: ...
# discovery (RFC 9728) → dynamic client registration (RFC 7591) → PKCE → token cache
```

**Dependencies**: `httpx`, stdlib `http.server` (loopback), 1Password-resolved env.
**Tests**: discovery + DCR against the live gateway (manual; interactive auth).

## User Flow

1. Developer writes `.env` with `ARCADE_GATEWAY_URL` + secret references, runs `op run --env-file=.env -- mcp-mirror --arcade`.
2. First run opens a browser once for OAuth; the token caches under `~/.cache/mcp-mirror/`.
3. System captures all five frameworks against the gateway, diffs each against the server announcement, and prints a scorecard (one row per tool, one column per framework).
4. Developer reads a cell like `-11 ~1 +28`, then drills in: `mcp-mirror --arcade --tool Linear_CreateIssue --detail` to see each dropped/added/changed field.
5. For high-delta tools, the developer runs Layer 2 with a golden case set and reads the per-track pass/warn/fail/rejected summary.

## Key Decisions

| Decision | Choice | Rationale | Alternatives considered |
| -------- | ------ | --------- | ----------------------- |
| **Real captures, never simulators** | Each capture exercises the framework's published MCP integration | An early simulator encoded assumptions the live run disproved (LangChain was *assumed* to collapse `oneOf`; it actually preserves the full input schema) — framework behavior drifts faster than docs. | Static schema analysis (rejected: misses runtime adapter transforms); recorded fixtures (rejected: rot the moment the adapter updates). |
| **Two layers — structural and behavioral** | A deterministic diff plus a prompt-based behavioral eval | A field count can't distinguish a dropped `title` (harmless) from a dropped `enum` (the model now emits invalid values) — both score `-1 lossy`; only observed behavior separates them. | Structural-only (rejected: false equivalence between harmless and breaking deltas); behavioral-only (rejected: too slow and expensive to run across every tool). |
| **Score against per-case ground truth, not the framework's schema** | Layer 2 critics check generated arguments against `expected_args` written for each case, not against the framework's own (possibly relaxed) schema | The target failure is a framework relaxing a constraint and the model emitting a value the framework accepts but the real tool rejects — caught only by scoring against ground truth. | Validate against framework schema (rejected: hides the exact bug we're looking for); validate against the server's JSON Schema only (rejected: structural-only, misses semantic correctness). |
| **Per-track suite, not a single comparative suite** | Each framework's view runs in its own `EvalSuite`; results are aggregated after | A provider that refuses one framework's schema (e.g., OpenAI rejecting `oneOf`) would sink a single comparative suite; per-track isolation turns that refusal into `rejected=True` for one track instead of an error for all. | `add_comparative_case` across one suite (rejected: schema rejections are suite-fatal, not local). |
| **MCP surface of `arcade_evals`, not the catalog surface** | Use `MCPToolDefinition` + `ExpectedMCPToolCall` instead of `@tool_eval` + `ExpectedToolCall` | mcp-mirror's input is raw MCP tool definitions, not registered Arcade tools — the catalog surface needs a `ToolCatalog` populated from Python modules we don't have. | `ToolCatalog` + `@tool_eval` (rejected: would require wrapping every captured view in a fake catalog entry just to satisfy the decorator). |
| **Spec-correct OAuth via Dynamic Client Registration** | Discover the auth server from the gateway's `WWW-Authenticate`, register a client via DCR, run PKCE with the gateway as the RFC 8707 `resource` | A raw API key as a Bearer is rejected (401) by the gateway — this is the flow a real MCP client uses, so captures reflect production. | API-key bearer (rejected: 401); static client_id (rejected: not portable across gateways without prior coordination). |

## Non-Goals

- **Not a conformance test.** mcp-mirror reports what each framework does, not what the spec says it should do.
- **Not a fuzzer.** It diffs the *tools the server announces*, not arbitrary or adversarial schemas.
- **Not an alerting / CI gate.** It produces scorecards for humans, not pass/fail signals for pipelines (though Layer 2's summary could be wired into one).
- **Not a framework benchmark.** "Lossy" vs. "faithful" measures preservation of the server's announcement, not the framework's overall quality.
- **Not a generic MCP client library.** The capture code is intentionally narrow to the few methods each framework needs to surface tools to an LLM.

## Outcomes

- **Layer 1 latency**: Full capture + diff of a 50-tool gateway across all five frameworks in under 30 seconds on a developer laptop. Captures are I/O-bound; the diff itself is microseconds.
- **Behavioral validity of structural findings**: For every tool that scores `lossy` on a meaningful field (`enum`, `required` list, numeric `minimum`/`maximum`), ≥1 golden case demonstrates a measurable behavioral delta against the server-control track. If a structural finding can't be argued to matter, Layer 2 says so explicitly.
- **No silent failures**: Every capture produces either a `ToolView` or a structured failure record; every Layer 2 track produces either `passed/warned/failed` counts or an explicit `rejected=True` / `errored=True` with reason. Nothing is silently dropped or coerced.
- **Shared vocabulary**: The four-category lexicon (`faithful`/`lossy`/`additive`/`transformative`) lands well enough that team conversations and customer reports start using it without prompting — measured informally by adoption in Slack/issues over the next quarter.

## Implementation Notes

**Constraints**:
- Python 3.10+ (3.13 dev). Core diff has no third-party dependencies.
- Each framework is an optional extra so the tool runs with any subset installed.
- Layer 2 requires `arcade-ai` (provides `arcade_evals`), `openai`, `pytz`, `scipy`, `scikit-learn`.

**Error Handling**:
- A framework whose capture raises is skipped with a stderr warning, not fatal — the scorecard degrades gracefully.
- Framework tool-name rewrites (CrewAI → snake_case) are matched by a canonical key, then surfaced as a `transformative` delta on `name`.
- In Layer 2, an `openai.BadRequestError` for a given track is recorded as `{"rejected": True, "reason": ...}` for that track only; any other exception is recorded as `{"errored": True, "reason": ...}`. Neither aborts other tracks.

**Gotchas**:
- The MCP SDK logs `Session termination failed: 202` on HTTP cleanup; harmless, suppressed via a scoped log filter.
- LlamaIndex routes schemas through Pydantic regeneration, producing large `$defs`-driven additive deltas that are structural, not semantic — exactly why Layer 2 matters.
- `SafeNumericCritic` exists because stock `NumericCritic` raises on a missing argument; the omission is a legitimate behavioral signal here, not an error.

**Open Questions**:
- [ ] **Distractor-tool set size for Layer 2 selection tests.** Too few = trivial pass rates; too many = measures context-overload, not adapter behavior. Need a defensible default.
- [ ] **Per-model vs. canonical model for behavioral results.** Default today is `gpt-4o`. Adapter findings may differ under Claude, Gemini, Llama; running all four explodes cost but per-model results sharpen claims.

## Where this sits in Arcade

mcp-mirror lives outside `arcade/monorepo` and has no canonical ADRs to align against. It complements the Arcade product without overlapping: the gateway is the *server-side* layer Arcade owns; mcp-mirror measures the *client-side* layer (framework adapters) that Arcade does not own but customers run every day. If Arcade ever needs to publish a framework-compatibility statement — "the Arcade gateway is high-fidelity in LangChain and Pydantic AI, lossy in CrewAI" — mcp-mirror is the tool that produces the evidence.

## Assessment triggers

Conditions that should prompt re-evaluation of these implementation decisions:

- [ ] A sixth framework is added — review whether the per-framework capture pattern scales or whether a shared adapter base is now worth the abstraction.
- [ ] The MCP protocol revises tool announcement (e.g., a v2 `tools/list` shape) — Layer 1 `ToolView` and the diff walker assume today's schema.
- [ ] A model provider deprecates the function-calling format `arcade_evals` targets — Layer 2's `MCPToolDefinition`/`ExpectedMCPToolCall` surface depends on it.
- [ ] Capture wall-time exceeds the 30-second Outcomes target on a 50-tool gateway — likely means an adapter regressed into per-tool network calls.
- [ ] A customer or framework maintainer disputes a finding the scorecard surfaced — re-evaluate the diff's category assignments and whether Layer 2 cases discriminated correctly.

## References

- MCP authorization: RFC 9728 (protected-resource metadata), RFC 7591 (DCR), RFC 8707 (resource indicators), RFC 7636 (PKCE).
- Live reference dataset: `sample-runs/arcade-mcp-mirror-gateway.json`.
- Behavioral layer builds on Arcade's `arcade_evals` library (`EvalSuite`, critics, `add_tool_definitions`, `add_case`). Layer 2 wraps it rather than reimplementing tool-call scoring.
- Arcade house templates referenced for structure: `monorepo/.claude/rules/spec-format.md` (Personas / Non-Goals / Outcomes), `monorepo/.claude/rules/impl-format.md` (Decisions table / Arch alignment / Assessment triggers).
