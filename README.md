# mcp-mirror

> An open compatibility tracker and deterministic scanner for MCP tool definitions across agent frameworks.

An MCP server publishes a tool name, description, input schema, and optional
annotations. An agent framework adapts that definition into its own tool object
or provider-shaped format. `mcp-mirror` records the source and one declared
framework boundary, then shows what stayed present, what moved to retained
metadata, and what disappeared.

The project has two public surfaces:

- **The compatibility site** answers, "Can I rely on this MCP capability?" Each
  result names the tested framework version, the exact mechanism, and a command
  that reproduces the measurement.
- **The scanner** runs the same deterministic comparison against your own MCP
  server, with no model call and no model API key.

The support data is versioned separately from the presentation so other sites,
framework docs, and CI checks can consume it directly.

## Read a result

Every framework-version cell has one of four factual states:

- **Present at the capture boundary**: the value survives in the exact adapted
  tool definition named by that framework's measurement.
- **Changed or retained elsewhere**: a numbered note says whether the value was
  transformed at the boundary, partly preserved, or retained only in framework
  metadata.
- **Dropped during adaptation**: the value is not recoverable from the adapted
  tool object.
- **Not yet measured**: the release exists in PyPI or npm, but no scan has
  covered it.

Every retained or dropped result cites a numbered note that names the mechanism.
Untested releases stay visible instead of disappearing from the history.

This is a compatibility census, not a leaderboard. Frameworks are included when
they ship a first-party or officially documented MCP adapter. They are ordered
alphabetically within language group, and no overall score is computed.

## Why it matters

A valid JSON Schema can become weaker after adaptation. A long description can
be truncated. A nested object can be flattened. A risk annotation can be kept
for application policy while remaining absent from the captured definition, or it can be
dropped entirely.

`destructiveHint` shows why those distinctions matter. In the currently measured
releases, the hint is absent from every declared capture boundary. LangChain and
Pydantic AI retain it in framework metadata. CrewAI, OpenAI Agents SDK, and
Mastra do not retain that behavioral hint on the captured tool object. Those are
different integration facts even when their normalized definitions look alike.

## Evidence boundaries

Every scanner run records the API and object it inspected:

- LangChain: the OpenAI-compatible dictionary returned by
  `convert_to_openai_tool`.
- Pydantic AI: `ToolDefinition` objects returned by `MCPToolset.get_tools`.
- CrewAI: adapted `BaseTool` name, description, and `args_schema` from
  `MCPServerAdapter`.
- OpenAI Agents SDK: the SDK `FunctionTool` returned by
  `MCPUtil.to_function_tool`.
- Mastra: tool actions returned by `MCPClient.listTools`, with JSON Schema
  extracted from Mastra's Standard Schema wrapper.

None of the v0.1 renderers captures a serialized provider request. Reports say
that explicitly. A result therefore proves behavior at the named framework
boundary, not the final bytes sent to OpenAI, Anthropic, or another provider.

## Install

```bash
pip install mcp-mirror
pip install "mcp-mirror[langchain]"
pip install "mcp-mirror[pydantic-ai]"
pip install "mcp-mirror[crewai]"
pip install "mcp-mirror[openai-agents]"
pip install "mcp-mirror[all]"
```

Renderers are optional so a scan installs only the frameworks it needs.
Python 3.11 or newer is required.

Mastra is a TypeScript framework. Its renderer drives the real `@mastra/mcp`
client through the included Node worker:

```bash
npm ci --prefix src/mcp_mirror/renderers/mastra_node
```

## Quickstart

The fixture server exercises description fidelity, enum and format constraints,
nested structures, unions, authorization annotations, and Unicode.

```bash
# Scan the fixture through every installed renderer.
mcp-mirror scan "python fixtures/tricky_server.py"

# Scan an HTTP MCP server through selected frameworks.
mcp-mirror scan https://example.com/mcp \
  --frameworks langchain,pydantic_ai \
  --output md

# Focus on parameter and authorization jobs.
mcp-mirror scan "python fixtures/tricky_server.py" --job J2,J5
```

`<server>` may be an HTTP(S) URL or a command string for a stdio server.

## Jobs to be done

Field-level differences are grouped by the production job a tool author needs
to complete:

- **J1, description**: the full tool purpose remains at the capture boundary.
- **J2, parameters**: types, required fields, enums, formats, and constraints
  remain available after adaptation.
- **J3, structure**: nested and structured input survives adaptation.
- **J4, injection**: the adapted definition contains nothing the tool author did
  not write.
- **J5, authorization**: dangerous or out-of-scope behavior remains legible,
  reported as present at the boundary, retained elsewhere, or destroyed.

Jobs return `pass`, `degraded`, or `fail`. Numerical difference counts are
diagnostic detail, not intent scores. J5 is always present in JSON, terminal,
and markdown scorecards even when `--job` narrows the other columns. No overall
framework verdict is computed.

## Regression checks

Save a baseline and fail CI when an adapter introduces new drift:

```bash
mcp-mirror scan "python fixtures/tricky_server.py" \
  --frameworks langchain \
  --out baseline.json

mcp-mirror scan "python fixtures/tricky_server.py" \
  --frameworks langchain \
  --baseline baseline.json \
  --fail-on-drift
```

Reports include the MCP protocol version negotiated by mcp-mirror's direct
source connection. Baselines are compared only within that same protocol
version. Each framework run also records the version negotiated by that
adapter's own connection. Four renderers read an initialization result exposed
by their client path; CrewAI instruments the `ClientSession.initialize` result,
and the pinned Mastra worker reads the underlying MCP client's negotiated
version. If one of those evidence seams disappears, the renderer fails instead
of copying the source connection's version by assumption. Baseline comparison
also rejects per-renderer protocol mismatches and unknown mixed-version evidence.
A live scan exits with code `3` rather than diffing a renderer response negotiated
under a different MCP revision from the source snapshot.

The compatibility site is currently one explicitly tagged MCP `2025-11-25`
snapshot. Comparing another MCP revision requires a separately measured dataset;
the project does not merge cells from different protocol revisions.

## CLI

```text
mcp-mirror scan <server>
    --frameworks langchain,pydantic_ai,crewai
    --spec-version 2025-11-25
    --output table|json|md
    --job J1,J5
    --baseline baseline.json --fail-on-drift
    --out report.json

mcp-mirror frameworks
mcp-mirror version
```

Exit codes are `0` for success, `1` for detected drift, `2` for a connection or
handshake failure, and `3` for a protocol-version mismatch.

## Data and site architecture

The repository uses the same useful separation as caniuse:

```text
data/frameworks.json
data/capabilities/*.json
        |
        +--> data/fulldata/data-1.0.json
        +--> site/public/data/data-1.0.json
        +--> docs/data/data-1.0.json
        +--> docs/standalone.html
```

Per-capability files are the source of truth, so `git log` on one file is that
capability's changelog. `scripts/build_data.py` validates and aggregates them.
The React site is a consumer of the generated data.

The site uses React 19, HeroUI v3, Tailwind CSS 4, and Vite. The production build
is written to `docs/` for static hosting. The build also inlines the compiled
CSS, JavaScript, and support data into `docs/standalone.html`, which opens
directly from `file://` without a server.

```bash
npm install
npm run dev       # http://127.0.0.1:8900
npm run build     # validate data, type-check, and build docs/
npm run preview
```

## Development

```bash
uv sync --locked --extra dev --extra all
npm ci --prefix src/mcp_mirror/renderers/mastra_node
uv run pytest tests -q
```

Run the data validator directly when editing support records:

```bash
python3 data/validator/validate.py data
python3 scripts/build_data.py
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for correction and tone rules. The
complete [`ADDING_A_FRAMEWORK.md`](ADDING_A_FRAMEWORK.md) runbook covers
framework inclusion, Python and Node renderer patterns, J5 handling, tests,
compatibility data, and PR evidence. Renderers must drive the framework's real
adapter rather than a reimplementation.

## License

Code is licensed under MIT. Files in `data/` are licensed under CC BY 4.0.
