# mcp-mirror, Design Document

> An open-source diff tool that captures what an LLM actually receives from an MCP server after the tool definitions pass through different agent frameworks, and scores each transform as faithful, lossy, additive, or transformative.

This document is written to be self-contained. A developer with no prior context should be able to build v0.1 from it.

---

## 1. What this is and why it exists

An MCP (Model Context Protocol) server publishes tools. Each tool has a name, a description, an input JSON Schema, and optional annotations. That is "what the server sends."

An agent framework (LangChain, Pydantic AI, CrewAI, and others) does not hand those definitions to the model unchanged. Each framework has an **adapter layer** that converts MCP tool definitions into the framework's own tool objects, which are then serialized into the tool list sent to the model API. That serialized tool list is "what the LLM receives."

The two are not the same. In practice, adapters drop fields, truncate descriptions, flatten nested schemas, rename tools, lose enum and format constraints, and sometimes inject extra text. Today this divergence is undocumented. It lives in private Slack threads and one-off debugging sessions. There is no tool that captures and compares it.

mcp-mirror is that tool. Point it at one MCP server, run it through N frameworks, and it shows, per tool and per field, exactly what each framework's LLM sees, diffed against the source, and categorized.

**Why it matters beyond ergonomics.** When a framework drops a tool's description or its risk annotations, the model loses the information it needs to decide whether a tool is safe to call. A schema that says "this tool is destructive and requires elevated scope" is an authorization signal. If the adapter strips it, the model may invoke the tool without that context. So adapter fidelity is not only a developer-convenience issue, it is an **authorization-legibility** issue. That framing is first-class in this tool (see Job J5).

**The citable contribution.** The four-word vocabulary, **faithful / lossy / additive / transformative**, is a shared language for adapter behavior that does not exist yet. If the community adopts it, the project owns the vocabulary.

**Important property: no model and no API key are required.** "What the LLM receives" is the tool-spec payload the framework would put into the model call. That payload is produced deterministically by the framework's own conversion code. mcp-mirror captures and diffs that payload. It never calls a model. Runs are deterministic and free.

---

## 2. Goals and non-goals

**Goals (v0.1)**
- Capture the exact LLM-facing tool spec a framework produces from a given MCP server.
- Diff it against the source MCP definition, field by field.
- Categorize every difference as faithful, lossy, additive, or transformative.
- Aggregate into a framework-selection scorecard organized by Jobs-To-Be-Done.
- Be runnable as a regression suite (a framework maintainer can catch fidelity regressions in CI).
- Tag every result with the MCP spec version it was produced under.

**Non-goals (v0.1)**
- Do not call or evaluate a model. We compare representations, not model behavior.
- Do not capture runtime error/response semantics (hard, framework-specific). Request-side tool spec only for v0.1.
- Do not rank "best framework" globally. Output is per-job; the developer judges fit.
- Do not compare protocols against each other yet (MCP only in v0.1; architecture stays protocol-agnostic for UTCP later).

---

## 3. Core concepts and vocabulary

- **Source representation**: the tool as the MCP server publishes it (`tools/list` response). The ground truth.
- **Rendering**: the LLM-facing tool spec a specific framework produces for the same tool.
- **ToolRep**: the normalized internal model both source and renderings are mapped into, so they diff apples-to-apples.
- **Difference**: one categorized delta at one JSON path between source and a rendering.
- **Categories** (applied per difference):
  - **faithful**: rendering preserves the source meaning at this point.
  - **lossy**: rendering drops or weakens something present in the source (field removed, description truncated, constraint or enum lost, structure flattened).
  - **additive**: rendering introduces something not in the source (injected text, extra fields, wrapper instructions).
  - **transformative**: rendering changes the representation in a way that is neither pure loss nor pure addition (renamed, retyped, restructured, reworded).
- **Job (JTBD)**: a developer-facing question ("will my parameter constraints survive?"). Each job maps to a subset of difference checks. The scorecard is organized by jobs, not raw fields.
- **Spec version**: the MCP protocol version under which a run was produced. Diffs are only comparable within a spec version.

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
   └──────────────┘                                                       ▼
                                                                   ┌────────────┐
                                                                   │ Scorecard  │──▶ JSON / table / markdown
                                                                   │ (JTBD agg) │     (+ regression compare)
                                                                   └────────────┘
```

---

## 5. Architecture and components

1. **Source loader** (`source.py`): an MCP client. Connects to a server (stdio or streamable-HTTP), runs the handshake, records the negotiated protocol version, calls `list_tools()`, returns raw source tools.
2. **Renderers** (`renderers/*.py`): one per framework. Each drives the framework's **real** MCP adapter and extracts the framework's LLM-facing tool spec. Never reimplement an adapter (see Decision D1).
3. **Normalizer** (`normalize.py`): maps source tools and each rendering into the common `ToolRep` model.
4. **Differ** (`diff.py`): compares a source `ToolRep` against a framework `ToolRep`, emits categorized `Difference` records.
5. **Scorecard** (`scorecard.py`): aggregates differences into per-tool and per-framework verdicts, grouped by Job.
6. **Reporters** (`report.py`): serialize a `Report` to JSON, a rich terminal table, or markdown.
7. **Regression harness**: save a baseline `Report`, later compare and exit nonzero on drift.
8. **CLI** (`cli.py`): orchestrates the above.

---

## 6. Data model (concrete)

Use Pydantic models.

```python
class ToolRep(BaseModel):
    name: str
    description: str | None
    params: dict            # the input JSON Schema (object schema)
    annotations: dict = {}  # MCP tool annotations, e.g. readOnlyHint, destructiveHint
    origin: str             # "source" or a framework id, e.g. "langchain"
    raw: dict               # the untouched payload this ToolRep was built from

Category = Literal["faithful", "lossy", "additive", "transformative"]

class Difference(BaseModel):
    tool: str               # source tool name
    framework: str          # framework id
    path: str               # JSON path, e.g. "params.properties.limit.enum"
    category: Category
    dimension: str          # "name" | "description" | "param_type" | "constraint" | "structure" | "annotation" | "injection"
    detail: str             # human-readable explanation
    source_value: Any | None
    rendered_value: Any | None

class FrameworkRun(BaseModel):
    framework: str
    framework_version: str
    adapter_version: str | None
    differences: list[Difference]

class Report(BaseModel):
    mcp_server: str
    mcp_spec_version: str    # from the MCP handshake; NON-NEGOTIABLE
    generated_with: str      # mcp-mirror version
    tools: list[str]
    runs: list[FrameworkRun]
    # scorecard is derived, not stored
```

---

## 7. Source loader (MCP)

Use the official `mcp` Python SDK. Support two transports:
- **stdio**: `--server "python my_server.py"` (command launched as a subprocess).
- **HTTP**: `--server https://host/mcp` (streamable-HTTP).

Steps: open the client session, complete the initialize handshake, **capture `protocolVersion` from the handshake result** and store it as `Report.mcp_spec_version`, call `list_tools()`, and for each tool build a source `ToolRep` from `name`, `description`, `inputSchema`, and `annotations`.

---

## 8. Framework renderers (the crux)

A renderer turns a live MCP server into the list of LLM-facing tool specs that one framework would send to a model. This is where the real engineering is. Define a protocol:

```python
class Renderer(Protocol):
    id: str                  # "langchain" | "pydantic_ai" | "crewai"
    def versions(self) -> dict: ...                 # {framework, adapter}
    def render(self, server: ServerHandle) -> list[ToolRep]: ...
```

**The cardinal rule (Decision D1): always drive the framework's real adapter, never reimplement it.** The whole value is reporting what the framework actually does. Pin framework versions and record them in `FrameworkRun.framework_version`.

The canonical LLM-facing shape every renderer must produce is the standard tool spec `{name, description, parameters: <JSON Schema>}` (the OpenAI/Anthropic function-tool format, which is the common denominator across model APIs). Build the `ToolRep` from that.

**v0.1 renderer notes** (verify entry points against current library docs at build time, these libraries move fast):
- **LangChain**: load tools with `langchain-mcp-adapters` (`MultiServerMCPClient(...).get_tools()`), then for each tool call `langchain_core.utils.function_calling.convert_to_openai_tool(tool)`. The returned `function` object is exactly what `bind_tools` sends to the model. Map it into a `ToolRep`.
- **Pydantic AI**: connect via `pydantic_ai.mcp` (`MCPServerStdio` / `MCPServerStreamableHTTP`), obtain the tool definitions the agent would expose, and read each `ToolDefinition` (`name`, `description`, `parameters_json_schema`).
- **CrewAI**: load via the CrewAI MCP adapter (`crewai_tools`' `MCPServerAdapter`), then render each tool to the spec CrewAI passes to the model (name, description, args schema).

Renderers live behind optional extras so users only install what they test: `pip install mcp-mirror[langchain]`, `[pydantic-ai]`, `[crewai]`, or `[all]`.

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
| param: nested object flattened, `$ref` inlined, `oneOf`/`anyOf` collapsed | | transformative (flag re: JSON Schema 2020-12) |
| annotation (e.g. destructiveHint, readOnlyHint) in S, absent in F | | lossy (authorization-relevant, see J5) |

Implementation: recursive JSON Schema walk over `params`. Keep `path` precise (`params.properties.x.enum`). When in doubt between transformative and lossy, prefer lossy if information capacity decreased, additive if it increased, transformative if it merely changed shape. A tool with zero differences is fully faithful.

---

## 10. Jobs-To-Be-Done mapping

Jobs are the organizing lens. Each maps to a set of dimensions. A framework gets a per-job verdict (the worst category seen in that job's dimensions, plus a count).

- **J1, "My tool description reaches the model intact."** dimensions: description.
- **J2, "My parameter contract survives (types, required, enums, formats)."** dimensions: param_type, constraint, required.
- **J3, "My nested and structured inputs survive."** dimensions: structure.
- **J4, "The model sees nothing I did not author."** dimensions: injection (additive on name/description/params).
- **J5, "Authorization-relevant signals survive."** dimensions: annotation (destructiveHint, readOnlyHint, etc.) and scope/risk language in descriptions. This is the job that connects adapter fidelity to authorization: if a destructive-tool signal is lost, the model can call a dangerous tool without knowing it is dangerous.

J5 is mandatory in every report and every writeup. It is the bridge from "framework comparison tool" to "agent authorization concern." (See Decision D4.)

---

## 11. Scorecard and output formats

**Terminal scorecard** (default): frameworks as rows, jobs as columns, each cell the worst category with a count, color-coded. Example:

```
mcp-mirror, server: weather-mcp, MCP spec: 2026-07-28, 4 tools

framework      J1 desc      J2 params     J3 struct    J4 inject    J5 authz
LangChain      faithful     lossy (3)     faithful     faithful     faithful
Pydantic AI    faithful     faithful      transform(1) faithful     faithful
CrewAI         lossy (2)    lossy (5)     transform(2) faithful     lossy (1)  ← dropped destructiveHint
```

**JSON** (`--output json`): the full `Report` plus a derived `scorecard` block, machine-readable and the regression baseline format.

**Markdown** (`--output md`): the scorecard table plus a per-tool, per-framework difference list. This is what gets pasted into a writeup.

---

## 12. Spec-version tagging (non-negotiable)

Every `Report` records `mcp_spec_version` from the MCP handshake. The scorecard header always prints it. Rationale: the MCP spec changes (the 2026-07-28 release candidate deprecates Roots/Sampling/Logging and adds JSON Schema 2020-12). Without version tagging, a diff caused by a spec change would masquerade as an adapter-fidelity change and the scorecard would be misleading. `--spec-version X` asserts the expected version and errors if the server negotiates a different one. Regression baselines are only compared within the same spec version.

---

## 13. Regression / CI mode

```
mcp-mirror scan <server> --frameworks langchain --baseline baseline.json --fail-on-drift
```
Compute the current `Report`, compare to the saved baseline (same spec version required), and exit nonzero if any new difference appears or any category worsens. This lets a framework maintainer wire mcp-mirror into CI to catch fidelity regressions in their adapter.

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

`tests/` runs each renderer against this fixture and asserts the expected category per dimension.

---

## 15. CLI reference

```
mcp-mirror scan <server>
    --frameworks langchain,pydantic_ai,crewai   # default: all installed renderers
    --spec-version 2026-07-28                    # optional assertion
    --output table|json|md                       # default: table
    --job J1,J5                                   # optional filter
    --baseline baseline.json --fail-on-drift      # regression mode
    --out report.json                             # write report to file

mcp-mirror frameworks       # list installed renderers and their versions
mcp-mirror version
```
`<server>` is either an HTTP(S) URL or a command string for stdio.
Exit codes: 0 success, 1 drift detected (regression mode), 2 connection/handshake error, 3 spec-version assertion failed.

---

## 16. Tech stack and repo layout

- Python 3.11+. `mcp` SDK (source client), `pydantic` (models), `typer` (CLI), `rich` (tables). Framework packages are optional extras.
- License: MIT.

```
mcp-mirror/
  README.md            # what it is, quickstart, the J5 authorization framing, the 2026-07-28 hook
  DESIGN.md            # this file
  pyproject.toml       # extras: [langchain] [pydantic-ai] [crewai] [all]
  src/mcp_mirror/
    __init__.py
    models.py          # ToolRep, Difference, FrameworkRun, Report
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
  fixtures/
    tricky_server.py   # section 14
  tests/
    test_diff.py       # unit: each rule -> expected category
    test_renderers.py  # integration: each renderer vs the fixture
```

---

## 17. v0.1 scope, milestones, definition of done

**Milestones**
1. Models + source loader (stdio and HTTP) with spec-version capture.
2. Differ + categorizer passing unit tests against hand-built ToolReps.
3. The tricky fixture server.
4. LangChain renderer + integration test against the fixture.
5. Pydantic AI renderer. 6. CrewAI renderer.
7. Scorecard (J1-J5) + terminal/JSON/markdown reporters.
8. Regression baseline mode.
9. README with the authorization framing and the launch writeup.

**Definition of done (v0.1):** `mcp-mirror scan <fixture> --frameworks langchain,pydantic_ai,crewai` prints a spec-version-tagged scorecard across J1-J5, every difference is categorized, JSON output round-trips as a regression baseline, and the test suite is green. Ship before the MCP 2026-07-28 spec finalizes.

---

## 18. Key design decisions and risks

- **D1, Drive real adapters, never reimplement.** The findings must reflect actual framework behavior or the tool is worthless. Pin and record versions.
- **D2, Protocol-agnostic core.** The differ and scorecard operate on `ToolRep`, not on MCP. MCP is one source loader. UTCP or another protocol can be added as another loader without touching the engine.
- **D3, Spec-version-tag everything.** Non-negotiable, see section 12.
- **D4, Authorization legibility (J5) is first-class.** The single biggest risk is that this reads as a developer-ergonomics tool and never builds authorship in agent authorization. Mitigation: J5 is in every report, and every writeup leads with what the LLM is allowed to understand about a tool and whether that survives the adapter. Discipline here is the real constraint on the project, not the code.
- **R1, A major framework ships its own schema-diff tooling.** Mitigation: be first, ride the 2026-07-28 spec transition as the launch.
- **R2, Spec churn pollutes findings.** Mitigated by D3.

---

## 19. Out of scope (future tracks)

- Error and response-structure capture (frameworks differ widely; needs live calls).
- Additional frameworks (LlamaIndex, OpenAI Agents SDK, AG2).
- UTCP and other protocols as additional source loaders.
- A hosted, continuously-updated public scorecard across popular servers.

---

## Appendix: launch writeup hook

First rep, timed to the spec transition: "Which frameworks updated their MCP adapters to the 2026-07-28 spec, and what does your LLM actually see when they have not?" Run mcp-mirror across the three frameworks before and after their adapter updates, publish the spec-version-tagged scorecard, and lead with the J5 finding (any dropped risk annotation or scope signal). That is the authorization angle, concrete and on the news hook.
