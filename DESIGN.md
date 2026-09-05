# mcp-mirror, Design Document

> An open compatibility tracker and deterministic scanner that compares MCP tool definitions at explicit agent-framework adaptation boundaries.

This document describes the shipped v0.1 architecture. A developer with no prior context should be able to understand, verify, and extend it.

---

## 1. What this is and why it exists

An MCP (Model Context Protocol) server publishes tools. Each tool has a name, a description, an input JSON Schema, and optional annotations. That is "what the server sends."

An agent framework (LangChain, Pydantic AI, CrewAI, OpenAI Agents SDK, Mastra, and others) has an **adapter layer** that converts MCP tool definitions into framework tool objects or provider-shaped dictionaries. v0.1 captures a declared object at that adapter boundary. It does not claim to capture a serialized provider request.

The two are not the same. In practice, adapters drop fields, truncate descriptions, flatten nested schemas, rename tools, lose enum and format constraints, and sometimes inject extra text. Today this divergence is undocumented. It lives in private Slack threads and one-off debugging sessions. There is no tool that captures and compares it.

mcp-mirror is that tool. Point it at one MCP server, run it through N frameworks, and it shows, per tool and per field, what each declared framework boundary contains, diffed against the source and categorized. Every report names the API, object, evidence stage, provider-request status, limitation, and independently negotiated MCP version.

**Why it matters beyond ergonomics.** When a framework drops a tool's description or risk annotations, downstream policy and model integrations may lose information used to decide whether a tool is safe to call. A schema that says "this tool is destructive and requires elevated scope" is an authorization signal. Adapter fidelity is therefore an **authorization-legibility** issue. v0.1 proves whether that signal is present at the declared capture boundary, retained elsewhere by the framework, or destroyed. It does not infer final provider-request contents.

**The citable contribution.** The four-word vocabulary, **faithful / lossy / additive / transformative**, is a shared language for adapter behavior that does not exist yet. If the community adopts it, the project owns the vocabulary.

**Important property: no model and no API key are required.** The captured tool object is produced deterministically by the framework's own MCP conversion code. mcp-mirror never calls a model. Runs are deterministic and free.

---

## 2. Goals and non-goals

**Goals (v0.1)**
- Capture the exact tool definition at a declared framework adaptation boundary.
- Diff it against the source MCP definition, field by field.
- Categorize every difference as faithful, lossy, additive, or transformative.
- Aggregate into a compatibility scorecard organized by Jobs-To-Be-Done.
- Be runnable as a regression suite (a framework maintainer can catch fidelity regressions in CI).
- Record both the direct-source and each renderer's independently negotiated MCP spec version; never compare across versions.

**Non-goals (v0.1)**
- Do not call or evaluate a model. We compare representations, not model behavior.
- Do not claim a provider request unless a renderer actually captures its serialized request body. No v0.1 renderer does.
- Do not capture runtime error/response semantics (hard, framework-specific). Request-side tool spec only for v0.1.
- Do not rank "best framework" globally. Output is per-job; the developer judges fit.
- Do not compare protocols against each other yet (MCP only in v0.1; architecture stays protocol-agnostic for UTCP later).

---

## 3. Core concepts and vocabulary

- **Source representation**: the tool as the MCP server publishes it (`tools/list` response). The ground truth.
- **Rendering**: the normalized tool definition captured from a specific framework for the same source tool.
- **Capture boundary**: the exact adapter API and object a renderer inspects, classified as `framework_tool_definition`, `provider_format`, or `provider_request`.
- **ToolRep**: the normalized internal model both source and renderings are mapped into, so they diff apples-to-apples.
- **Difference**: one categorized delta at one JSON path between source and a rendering.
- **Categories** (applied per difference):
  - **faithful**: rendering preserves the source meaning at this point.
  - **lossy**: rendering drops or weakens something present in the source (field removed, description truncated, constraint or enum lost, structure flattened).
  - **additive**: rendering introduces something not in the source (injected text, extra fields, wrapper instructions).
  - **transformative**: rendering changes the representation in a way that is neither pure loss nor pure addition (renamed, retyped, restructured, reworded).
- **Job (JTBD)**: a developer-facing question ("will my parameter constraints survive?"). Each job maps to a subset of difference checks. The scorecard is organized by jobs, not raw fields.
- **Spec version**: the MCP protocol version negotiated independently by the source loader and a framework adapter. A diff is computed only when those versions match; baselines require matching source and renderer versions.

---

## 4. How it works (data flow)

```
                         ┌─────────────────────────┐
   MCP server  ─────────▶│  Source loader (MCP)     │──▶ source ToolReps  ─┐
   (stdio/HTTP)          │  records spec version    │                     │
                         └─────────────────────────┘                     │
                                                                          ▼
   ┌──────────────┐   real adapter   ┌───────────────┐             ┌────────────┐
   │ LangChain    │◀────────────────▶│  Renderer     │──rendered──▶│            │
   ├──────────────┤                  │  (one per     │   ToolReps  │   Differ   │──▶ Differences
   │ Pydantic AI  │◀────────────────▶│  framework)   │             │ +categorize│
   ├──────────────┤                  └───────────────┘             └────────────┘
   │ CrewAI       │                                                       │
   ├──────────────┤                                                       ▼
   │ OpenAI Agents│                                                ┌────────────┐
   ├──────────────┤                                                │ Scorecard  │──▶ JSON / table / markdown
   │ Mastra       │                                                │ (JTBD agg) │     (+ regression compare)
   └──────────────┘                                                └────────────┘
```

---

## 5. Architecture and components

1. **Source loader** (`source.py`): an MCP client. Connects to a server (stdio or streamable-HTTP), runs the handshake, records the negotiated protocol version, calls `list_tools()`, returns raw source tools.
2. **Renderers** (`renderers/*.py`): one per framework. Each drives the framework's **real** MCP adapter, captures one declared framework object, and records `RendererEvidence`. Never reimplement an adapter (see Decision D1).
3. **Normalizer** (`normalize.py`): maps source tools and each rendering into the common `ToolRep` model.
4. **Differ** (`diff.py`): compares a source `ToolRep` against a framework `ToolRep`, emits categorized `Difference` records.
5. **Scorecard** (`scorecard.py`): aggregates differences into per-tool and per-framework verdicts, grouped by Job.
6. **Reporters** (`report.py`): serialize a `Report` to JSON, a rich terminal table, or markdown.
7. **Regression harness**: save a baseline `Report`, later compare and exit nonzero on drift; reject source- or renderer-level MCP version mismatches.
8. **Isolated renderer worker** (`_render_worker.py`): prevents heavyweight framework imports and event-loop state from contaminating one another.
9. **CLI** (`cli.py`): orchestrates the above.

---

## 6. Data model (concrete)

Use Pydantic models.

```python
class ToolRep(BaseModel):
    name: str
    description: str | None
    params: dict            # the input JSON Schema (object schema)
    annotations: dict = {}  # annotations present at this capture boundary
    framework_metadata: dict = {}  # values retained elsewhere by a framework
    origin: str             # "source" or a framework id, e.g. "langchain"
    raw: dict               # the untouched payload this ToolRep was built from

Category = Literal["faithful", "lossy", "additive", "transformative"]

class Difference(BaseModel):
    tool: str               # source tool name
    framework: str          # framework id
    path: str               # JSON path, e.g. "params.properties.limit.enum"
    category: Category
    dimension: str          # name | description | param_type | constraint |
                            # structure | annotation | injection | required | authz
    detail: str             # human-readable explanation
    source_value: Any | None
    rendered_value: Any | None

class RendererEvidence(BaseModel):
    capture_api: str
    capture_object: str
    capture_stage: Literal[
        "framework_tool_definition", "provider_format", "provider_request"
    ]
    provider_request_captured: bool
    negotiated_mcp_spec_version: str | None
    protocol_version_evidence: str
    limitation: str | None

class FrameworkRun(BaseModel):
    framework: str
    framework_version: str
    adapter_version: str | None
    evidence: RendererEvidence | None
    differences: list[Difference]

class Report(BaseModel):
    mcp_server: str
    mcp_spec_version: str    # direct source handshake; NON-NEGOTIABLE
    mcp_spec_version_evidence: str
    generated_with: str      # mcp-mirror version
    tools: list[str]
    runs: list[FrameworkRun]
    # scorecard is derived, not stored
```

`JobRequirement`, `Job`, `JobSpec`, and `JobFinding` are also first-class
models. Jobs can require tools, parameters, required-set membership,
constraints, and annotations; findings use `pass`, `degraded`, or `fail`.
The scorecard remains derived and contains no overall framework verdict.

---

## 7. Source loader (MCP)

Use the official `mcp` Python SDK. Support two transports:
- **stdio**: `--server "python my_server.py"` (command launched as a subprocess).
- **HTTP**: `--server https://host/mcp` (streamable-HTTP).

Steps: open the client session, complete the initialize handshake, **capture
`protocolVersion` from the handshake result** and store it as
`Report.mcp_spec_version`, call `list_tools()`, and for each tool build a source
`ToolRep` from `name`, `description`, `inputSchema`, and `annotations`.
Streamable HTTP uses the current `streamable_http_client` API with an explicit
`httpx.AsyncClient`. Local tests exercise both transports and assert CLI exit
codes `2` and `3`.

---

## 8. Framework renderers (the crux)

A renderer turns a live MCP server into normalized tool definitions from one
explicit framework boundary. This is where the real engineering is:

```python
class Renderer(Protocol):
    id: str
    def versions(self) -> dict: ...                 # {framework, adapter}
    def evidence(self) -> RendererEvidence: ...
    def render(self, server: ServerHandle) -> list[ToolRep]: ...
```

**The cardinal rule (Decision D1): always drive the framework's real adapter,
never reimplement it.** Pin framework versions, record exact installed versions,
and state the evidence boundary without promotion. A provider-shaped dictionary
is not a captured provider request.

Every renderer normalizes its captured object into
`{name, description, parameters: <JSON Schema>}`. That common shape is a
comparison interface, not a claim that all providers serialize identically.
`ToolRep.annotations` contains values present on the captured definition;
`framework_metadata["annotations"]` contains values retained elsewhere.

**Shipped v0.1 renderers:**

- **LangChain**: opens a `langchain-mcp-adapters` session, records the
  `ClientSession.initialize()` protocol version, converts the adapter's tools
  with `convert_to_openai_tool`, and captures the resulting OpenAI-compatible
  dictionary (`provider_format`; no provider request).
- **Pydantic AI**: uses the supported `MCPToolset` with FastMCP stdio or
  streamable-HTTP transports, captures `ToolDefinition` objects from
  `get_tools`, and reads the version from `toolset.client.initialize_result`.
- **CrewAI**: uses `crewai_tools.MCPServerAdapter`, captures the yielded
  `BaseTool` name, description, and `args_schema`, and instruments the
  `ClientSession.initialize` return value because MCPServerAdapter does not
  otherwise expose it.
- **OpenAI Agents SDK**: uses `MCPUtil.to_function_tool`, captures the SDK
  `FunctionTool`, and reads `MCPServer.server_initialize_result`.
- **Mastra**: a pinned Node worker drives `@mastra/mcp`
  `MCPClient.listTools`, extracts JSON Schema from Mastra's Standard Schema
  wrapper, and records the underlying pinned MCP client's negotiated version.
  The worker fails closed if that private evidence seam moves.

Renderers live behind optional Python extras. Mastra additionally requires
`npm ci --prefix src/mcp_mirror/renderers/mastra_node`. All run in isolated
subprocesses from the CLI. The full contribution contract is in
`ADDING_A_FRAMEWORK.md`.

---

## 9. The diff and categorization algorithm

For a source `ToolRep` S and a framework `ToolRep` F of the same tool, walk these dimensions and emit `Difference` records.

| Dimension | Rule | Category |
|---|---|---|
| name | identical | faithful |
| name | namespaced/prefixed (e.g. `server__tool`) or renamed | transformative |
| name | missing | lossy |
| description | identical | faithful |
| description | F is a prefix of S, or materially shorter | lossy (truncated) |
| description | dropped/empty while S had one | lossy |
| description | reworded, similar length | transformative |
| description | F longer / contains text not in S | additive (injected) |
| param: property in S, absent in F | | lossy |
| param: property in F, absent in S | | additive |
| param: type changed (e.g. string→object) | | transformative |
| param: enum present in S, absent in F | | lossy |
| param: constraint (min/max, format, pattern) in S, absent in F | | lossy |
| param: per-property description in S, absent in F | | lossy |
| param: required set shrinks vs S | | lossy |
| param: equivalent local `$ref` | resolve before comparison | faithful |
| param: rendered wrapper newly accepts `null` | compare before unwrapping | additive |
| param: nested object flattened or `oneOf`/`anyOf` collapsed | | transformative |
| annotation preserved on captured definition | | faithful |
| annotation absent from capture but retained in framework metadata | | transformative |
| annotation absent everywhere after adaptation | | lossy |

Implementation: recursively walk JSON Schema over `params`, resolve local
`$ref` values, report null-acceptance changes, then unwrap optional-null wrappers
only to inspect their non-null branch. Match and recurse through genuine
combinator branches, compare constraint values as well as presence, and keep
`path` precise (`params.properties.x.enum`). When in doubt between
transformative and lossy, prefer lossy if information capacity decreased,
additive if it increased, and transformative if it merely changed shape. A tool
with zero differences is fully faithful.

---

## 10. Jobs-To-Be-Done mapping

Jobs are the organizing lens. Each maps to a set of dimensions. A framework gets
a per-job verdict (the highest-severity category inside that job, plus a count).
No cross-job or overall framework verdict is computed.

- **J1, "My tool identity and purpose survive the declared capture boundary intact."** dimensions: name, description.
- **J2, "My parameter contract survives (types, required, enums, formats)."** dimensions: param_type, constraint, required.
- **J3, "My nested and structured inputs survive."** dimensions: structure.
- **J4, "The captured definition contains nothing I did not author."** dimensions: injection (additive on name/description/params).
- **J5, "Authorization-relevant signals survive."** dimensions: annotation (`destructiveHint`, `readOnlyHint`, etc.) and scope/risk language in descriptions. This connects adapter fidelity to authorization while remaining precise about the measured boundary.

J5 is mandatory in every report and every writeup. `--job` may narrow the other
columns but cannot remove J5. Terminal and markdown reports include dedicated
authorization findings. (See Decision D4.)

---

## 11. Scorecard and output formats

**Terminal scorecard** (default): frameworks as rows, jobs as columns, each cell
the highest-severity category inside that job with a count, color-coded. Example:

```
mcp-mirror, server: tricky-mcp, source-negotiated MCP spec: 2025-11-25, 5 tools

framework      J1 identity  J2 params     J3 struct    J4 inject    J5 authz
LangChain      faithful     faithful      faithful     faithful     transform(7)
Pydantic AI    faithful     faithful      faithful     faithful     transform(7)
CrewAI         faithful     lossy (21)    transform(1) additive(5)  lossy (7)
OpenAI Agents  faithful     faithful      faithful     faithful     lossy (7)
Mastra         transform(5) faithful      faithful     faithful     lossy (7)
```

Before the scorecard, the terminal report prints each framework's capture API,
object, stage, provider-request status, adapter-negotiated MCP version, and
limitation.

**JSON** (`--output json`): the full `Report`, including `RendererEvidence`, plus
a derived `scorecard` block. It is the machine-readable regression baseline
format.

**Markdown** (`--output md`): evidence boundaries, the scorecard, mandatory J5
authorization findings, and a per-tool/per-framework difference list.

---

## 12. Spec-version tagging (non-negotiable)

Every `Report` records `mcp_spec_version` from mcp-mirror's direct source
handshake and labels that evidence explicitly. Every `FrameworkRun` records the
version negotiated by its own adapter connection. The CLI refuses to compute a
diff when those versions differ or the renderer cannot establish its version.
`--spec-version X` asserts the expected direct-source version. Regression
baselines require matching direct-source and per-renderer versions and fail
closed on mixed old/new evidence.

Rationale: a protocol revision can change the source representation or adapter
path. Without independent version evidence, a spec change can masquerade as
adapter drift. The compatibility data is currently a single MCP `2025-11-25`
snapshot. A second revision must be measured and published separately rather
than merged into those cells.

---

## 13. Regression / CI mode

```
mcp-mirror scan <server> --frameworks langchain --baseline baseline.json --fail-on-drift
```
Compute the current `Report`, compare it to the saved baseline (matching source
and renderer MCP versions required), and exit nonzero if any new difference
appears or any category worsens. This lets a framework maintainer wire
mcp-mirror into CI to catch fidelity regressions in an adapter.

---

## 14. Test fixtures

Ship `fixtures/tricky_server.py`: a minimal MCP server whose tools deliberately exercise every diff path, so the tool's own behavior is reproducible and testable without an external server. Include tools with:
- a long description (> 1024 chars), to detect truncation
- an enum parameter and a `format` (date-time, email) constraint
- a nested object parameter and an array-of-objects parameter
- a `oneOf`/`anyOf` schema (JSON Schema 2020-12), to detect collapse
- a mix of required and optional params, with per-property descriptions
- unicode and special characters in a description
- a tool carrying `destructiveHint: true` and scope language, to exercise J5

`tests/` runs all five renderers against this fixture and asserts tool count and
names, description fidelity, required sets, enums, formats, numeric constraints,
nested objects, arrays of objects, `oneOf`/`anyOf`, injected wrappers, and all
annotation fates. Published current-version cells and framework evidence must
match those goldens. `fixtures/http_server.py` separately proves local
streamable-HTTP loading and negotiated-version capture without an external
service.

---

## 15. CLI reference

```
mcp-mirror scan <server>
    --frameworks langchain,pydantic_ai,crewai,openai_agents,mastra
                                                  # default: all installed
    --spec-version 2025-11-25                    # optional source assertion
    --output table|json|md                       # default: table
    --job J1,J2                                  # optional; J5 always remains
    --baseline baseline.json --fail-on-drift      # regression mode
    --out report.json                             # write report to file

mcp-mirror frameworks       # list installed renderers and their versions
mcp-mirror version
```
`<server>` is either an HTTP(S) URL or a command string for stdio.
Exit codes: `0` success, `1` drift detected (regression mode), `2`
connection/handshake error, and `3` source assertion or source/renderer protocol
version mismatch.

---

## 16. Tech stack and repo layout

- Python 3.11+. `mcp` SDK (source client), `pydantic` (models), `typer`
  (CLI), `rich` (tables), and `httpx` (explicit HTTP client). Framework
  packages are optional extras.
- React 19, HeroUI v3, Tailwind CSS 4, and Vite for the compatibility site.
- Code license: MIT. Compatibility data: CC BY 4.0.

```
mcp-mirror/
  README.md            # product contract, evidence boundaries, and quickstart
  DESIGN.md            # this file
  ADDING_A_FRAMEWORK.md
  pyproject.toml       # extras: [langchain] [pydantic-ai] [crewai]
                       #         [openai-agents] [all]
  src/mcp_mirror/
    __init__.py
    models.py          # ToolRep, Difference, RendererEvidence, runs/reports/jobs
    source.py          # MCP source loader (+ spec-version capture)
    normalize.py       # payload -> ToolRep
    diff.py            # differ + categorizer (section 9 rules)
    scorecard.py       # JTBD aggregation (section 10)
    report.py          # table / json / md reporters; baseline compare
    cli.py             # typer app (section 15)
    renderers/
      __init__.py      # Renderer protocol + registry of installed renderers
      langchain_renderer.py
      pydantic_ai_renderer.py
      crewai_renderer.py
      openai_agents_renderer.py
      mastra_renderer.py
      mastra_node/     # pinned @mastra/mcp worker
  fixtures/
    tricky_server.py   # section 14
    http_server.py     # local streamable-HTTP fixture
  tests/
    test_diff.py       # unit: each rule -> expected category
    test_renderers.py  # integration: each renderer vs the fixture
    test_source_cli.py # transport and exit-code contracts
    test_report.py     # evidence and mandatory-J5 output contracts
```

---

## 17. v0.1 scope, milestones, definition of done

**Shipped milestones**

1. Pydantic models, stdio and streamable-HTTP source loading, direct-source
   version capture, and CLI exit contracts.
2. Recursive differ and categorizer with `$ref` and optional-wrapper
   normalization, authorization-language checks, and unit coverage.
3. Tricky stdio fixture plus a local HTTP fixture.
4. Real-adapter renderers for LangChain, Pydantic AI, CrewAI, OpenAI Agents
   SDK, and Mastra.
5. Exact `RendererEvidence`, including independently negotiated MCP versions,
   in JSON, terminal, and markdown reports.
6. Per-renderer fixture goldens across identity, descriptions, schemas,
   structures, wrappers, and annotation fates.
7. J1-J5 scorecard and user-supplied JTBD specs, with J5 mandatory and no
   overall framework verdict.
8. Source- and renderer-version-aware regression baselines.
9. Versioned compatibility data, validator, React site, standalone build,
   contribution runbook, CI workflow, and PR evidence template.

**Definition of done (v0.1):** `mcp-mirror scan <fixture>` runs all five
installed real adapters, refuses cross-protocol comparisons, prints explicit
capture evidence and J1-J5, categorizes every difference, round-trips JSON as a
same-version regression baseline, and passes the locked test/data/site/wheel
builds without a model or API key.

The old "ship before 2026-07-28" deadline and launch hook are historical, not
current acceptance criteria. A replacement launch narrative remains an owner
and marketing decision; this design does not invent one.

---

## 18. Key design decisions and risks

- **D1, Drive real adapters, never reimplement.** The findings must reflect actual framework behavior or the tool is worthless. Pin and record versions.
- **D2, Protocol-agnostic core.** The differ and scorecard operate on `ToolRep`, not on MCP. MCP is one source loader. UTCP or another protocol can be added as another loader without touching the engine.
- **D3, Capture and enforce protocol versions independently.** Non-negotiable, see section 12. A source tag alone is insufficient because each framework opens its own MCP connection.
- **D4, Authorization legibility (J5) is first-class.** The single biggest risk is that this reads only as a schema-ergonomics tool. Mitigation: J5 cannot be filtered out, reports include dedicated authorization findings, and wording states whether evidence is present at the capture boundary, retained elsewhere, or destroyed. Final model visibility is not claimed without provider-request evidence.
- **D5, Census, not leaderboard.** Frameworks are ordered alphabetically within language group. No overall framework verdict, winner, adoption weighting, or aggregate score is computed.
- **D6, Evidence strength is public data.** Every renderer and published framework record names the capture API, object, stage, provider-request status, protocol evidence, and limitation. An intermediate object is never promoted to a provider request.
- **R1, A major framework ships its own schema-diff tooling.** Mitigation: remain neutral, reproducible infrastructure with versioned data, cross-framework fixtures, and explicit evidence boundaries.
- **R2, Spec churn pollutes findings.** Mitigated by D3.

---

## 19. Out of scope (future tracks)

- Error and response-structure capture (frameworks differ widely; needs live calls).
- Additional frameworks (Vercel AI SDK, LlamaIndex, AG2, and community
  contributions following `ADDING_A_FRAMEWORK.md`).
- Provider-request capture using deterministic local fake transports, where a
  framework exposes a stable interception seam.
- UTCP and other protocols as additional source loaders.
- Separately versioned compatibility datasets for MCP revisions beyond
  `2025-11-25`.
- A hosted, continuously updated public census across popular servers.

---

## Appendix: unresolved launch framing

The original plan was tied to shipping before the 2026-07-28 MCP transition.
That date has passed, and the current public dataset measures MCP 2025-11-25.
No replacement launch hook has been approved. Before publishing a transition
story, produce a separate 2026-07-28 dataset and verify every renderer's
independent negotiation evidence. Marketing framing is an owner decision, not a
scanner implementation detail.
