# Design: mcp-mirror

**Author**: Thierry Damiba (thierry@arcade.dev)
**Status**: Draft

**Related**: README: `../README.md` | Build log: `build-log/` | Sample data: `sample-runs/`

## Architecture

mcp-mirror connects one MCP server to several real agent frameworks at once and reports how each framework transforms a tool before the LLM sees it. A single source (stdio or streamable-HTTP) feeds N framework adapters; each adapter's real integration code produces a normalized `ToolView`; a diff engine compares each view to the server's announcement and a behavioral layer measures whether the differences change model behavior.

The design rests on one principle: a structural diff tells you *what* changed, but only running prompts through a model tells you *whether the change matters*. The tool therefore has two layers — a cheap deterministic diff (built) and an expensive behavioral eval (planned) — that compose.

**Diagram:**

```
source (stdio | HTTP+OAuth) → [5 framework adapters] → ToolView ×5
                                                          ├→ Layer 1: structural diff   (built)
                                                          └→ Layer 2: behavioral eval   (planned)
```

## Components

### Component 1: Capture

**What**: Load a server's tools through one framework's real MCP integration and normalize what it exposes to the LLM.
**Where**: `src/mcp_mirror/capture.py`
**Interface**:

```python
async def capture_langchain(spec: ServerSpec) -> CaptureResult: ...
# one per framework: langchain, llamaindex, crewai, pydantic_ai, ag2
# all transport-agnostic via the _session(spec) context manager

@dataclass
class CaptureResult:
    framework: str
    framework_version: str | None   # from importlib.metadata, recorded per run
    views: list[ToolView]
```

**Dependencies**: the five framework packages (optional extras), `mcp` SDK, `ServerSpec`.
**Tests**: `tests/test_capture.py` — asserts each adapter's known behavior against the bundled server.

### Component 2: Diff engine (Layer 1)

**What**: Recursively compare a framework `ToolView` to the server's and categorize every field-level delta.
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
**Tests**: `tests/test_diff.py` — synthetic views with known deltas; overall = worst category.

### Component 3: Behavioral eval (Layer 2, planned)

**What**: Run a prompt battery through a real model against each framework view; score selection + argument accuracy vs. a server-view control.
**Where**: `src/mcp_mirror/llm_eval.py` (planned)
**Interface**:

```python
async def eval_tool(server: ToolView, framework: ToolView, prompts: list[Prompt],
                    model: str) -> BehavioralDelta: ...

@dataclass
class BehavioralDelta:
    selection_accuracy: float   # vs. server-view control
    argument_validity: float    # validated against the SERVER schema, not the framework's
```

**Dependencies**: OpenAI SDK, a generated+golden prompt battery.
**Tests**: golden-set prompts with fixed expected selections.

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

## Key Decisions

### Decision 1: Real captures, never simulators

**What**: Each capture exercises the framework's published MCP integration, not a model of its behavior.
**Why**: An early simulator encoded assumptions that the live run disproved (e.g., LangChain was assumed to collapse `oneOf`; it actually preserves the full input schema). Framework behavior drifts faster than docs.
**Trade-off**: Requires installing five framework dependency trees; captures are slower than static analysis.

### Decision 2: Two layers — structural and behavioral

**What**: A deterministic diff plus a prompt-based behavioral eval.
**Why**: A field count can't distinguish a dropped `title` (harmless) from a dropped `enum` (the model now emits invalid values). Both score `-1 lossy`. Only observed model behavior separates them.
**Trade-off**: Layer 2 needs a model, a prompt battery, and cost controls; it runs selectively on high-delta tools, not everywhere.

### Decision 3: Validate arguments against the server schema

**What**: In Layer 2, generated arguments are checked against the *server's* schema, not the framework's.
**Why**: The target failure is a framework relaxing a constraint, the model emitting a value the framework accepts but the real tool rejects — caught only by scoring against ground truth.
**Trade-off**: Requires keeping the server schema around through the eval; more bookkeeping.

### Decision 4: Spec-correct OAuth via Dynamic Client Registration

**What**: Discover the auth server from the gateway's `WWW-Authenticate`, register a client via DCR, run PKCE with the gateway as the RFC 8707 `resource`.
**Why**: A raw API key as a Bearer is rejected (401) by the gateway; this is the flow a real MCP client uses, so captures reflect production.
**Trade-off**: A browser step on first auth; one client record registered per machine.

## Implementation Notes

**Constraints**:
- Python 3.10+ (3.13 dev). Core diff has no third-party dependencies.
- Each framework is an optional extra so the tool runs with any subset installed.

**Error Handling**:
- A framework whose capture raises is skipped with a stderr warning, not fatal — the scorecard degrades gracefully.
- Framework tool-name rewrites (CrewAI → snake_case) are matched by a canonical key, then surfaced as a `transformative` delta on `name`.

**Gotchas**:
- The MCP SDK logs `Session termination failed: 202` on HTTP cleanup; harmless, suppressed via a scoped log filter.
- LlamaIndex routes schemas through Pydantic regeneration, producing large `$defs`-driven additive deltas that are structural, not semantic — exactly why Layer 2 matters.

**Open Questions**:
- [ ] Distractor-tool set size for Layer 2 selection tests (too few = trivial, too many = measures overload).
- [ ] Per-model vs. single canonical model for behavioral results.
- [ ] Ephemeral DCR per machine vs. one registered mcp-mirror client for release.

## References

- MCP authorization: RFC 9728 (protected-resource metadata), RFC 7591 (DCR), RFC 8707 (resource indicators), RFC 7636 (PKCE).
- Live reference dataset: `sample-runs/arcade-mcp-mirror-gateway.json`.
