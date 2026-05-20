# mcp-mirror

**See what your MCP server actually looks like after every framework gets done with it.**

`mcp-mirror` is a cross-framework diff tool for MCP. It points the same MCP server at five real agent frameworks — LangChain, LlamaIndex, CrewAI, Pydantic AI, AG2 — and shows you, side by side, what each framework hands to the LLM. Schema preservation, description fidelity, response handling, metadata propagation, all in one scorecard.

No simulators. No mocks. Real MCP servers, real framework adapters, real captures.

## Why this exists

Every team running MCP in production has hit the same moment: a tool that behaves differently in their framework than it does in a colleague's. The framework adapter layer between MCP and the LLM is real, you've debugged it. What's missing is a shared map.

`mcp-mirror` builds the map. It runs your server through every framework's actual integration code path, captures what each one would send to the LLM, diffs against the server's own announcement, and categorizes every difference as **faithful**, **lossy**, **additive**, or **transformative**.

## Quickstart

```bash
git clone <repo-url> mcp-mirror
cd mcp-mirror
python3.13 -m venv .venv
.venv/bin/pip install -e '.[all]'
.venv/bin/mcp-mirror
```

Default output (against the bundled reference MCP server, with all five frameworks installed):

```
tool                  ag2           crewai        langchain     llamaindex    pydantic-ai
------------------------------------------------------------------------------------------
send_message          -10 +1        -11 ~1 +12    -6 +1         -12 +9        +1
search_records        -9 +1         -14 ~2 +12    -6 +1         -13 +9        +1
legend:  = faithful   + additive   - lossy   ~ transformative
         counts are field-level deltas vs. the server announcement
```

Read row-by-column: *"For `send_message`, the LangChain adapter drops 6 fields the server announced and adds 1 framework-specific field; Pydantic AI adds only 1 field and is otherwise faithful."*

### See the field-level breakdown

```bash
mcp-mirror --detail
```

```
=== send_message @ langchain ===
overall: lossy
deltas: lossy=6, additive=1

  - response.type
      Framework dropped `type`.
  - response.required
      Framework dropped `required`.
  - response.properties
      Framework dropped `properties`.
  - metadata.stability
      Server metadata `stability` dropped by framework.
  - metadata.permissions_required
      Server metadata `permissions_required` dropped by framework.
  - metadata.idempotent
      Server metadata `idempotent` dropped by framework.
  + metadata.__lc_tool_class
      Framework added metadata `__lc_tool_class`.
```

### Point at any MCP server

```bash
mcp-mirror --server npx -y @some/mcp-server
mcp-mirror --server python -m my_company.mcp_server
```

### Filter by framework or tool

```bash
mcp-mirror --framework pydantic-ai --framework langchain
mcp-mirror --tool send_message
```

### Machine-readable output

```bash
mcp-mirror --json | jq '.diffs[] | select(.framework=="crewai")'
```

## How it works

Every capture is a real adapter loading a real MCP server.

1. **Server** — a real MCP server (the bundled reference, or any server you point at) speaks the actual MCP protocol over stdio.
2. **Frameworks** — each framework's actual MCP integration package (`langchain-mcp-adapters`, `llama-index-tools-mcp`, `crewai-tools[mcp]`, `pydantic_ai.mcp`, `autogen.mcp`) loads the server's tools through the same code path it uses in production.
3. **Capture** — each framework's tool representation is introspected: `tool.args_schema` for LangChain, `tool.metadata.fn_schema` for LlamaIndex, `tool.inputSchema` for Pydantic AI's raw MCP Tool, `tool.args_schema.model_json_schema()` for CrewAI, `tool.parameters_json_schema` for AG2.
4. **Diff** — a recursive structural diff against the server's announcement categorizes every delta.

This means `mcp-mirror`'s output is exactly what each framework would feed the LLM at inference time — minus the LLM call itself (which is unnecessary for the comparison; the framework's tool schema is built before the LLM is involved).

## What we found

Real data from real frameworks against the bundled reference tools:

| Framework | Verdict | Notable behavior |
|---|---|---|
| **Pydantic AI** | Faithful | Returns raw `mcp.types.Tool`. Input schema, output schema, and `_meta` all preserved. |
| **LangChain** | Predictably lossy | Preserves the full input schema (including `oneOf`, `format`, `enum`). Drops response schema and protocol-level `_meta`. |
| **AG2** | Predictably lossy | Like LangChain, but more drops in the conversion path. Input schema preserved. |
| **LlamaIndex** | Structurally transformed | Converts JSON Schema → Pydantic → JSON Schema, introducing `$defs` blocks and reorganizing properties. Semantically near-equivalent but structurally different. |
| **CrewAI** | Most invasive | Goes through `mcpadapt` + CrewAI's own Pydantic model generation. *Extends* tool descriptions (5x longer) with usage guidance, restructures schemas, drops response shapes. |

These findings shifted significantly from the assumptions encoded in the initial simulators. That's the value of real captures.

## Installation

`mcp-mirror` requires **Python 3.10+** (3.13 recommended) and at least one framework's MCP integration package installed.

Install everything:

```bash
.venv/bin/pip install -e '.[all]'
```

Install just what you need (this list reflects what we tested on; pin versions in production):

```bash
pip install -e .
pip install mcp                              # the official MCP SDK
pip install langchain-mcp-adapters           # LangChain
pip install llama-index-tools-mcp            # LlamaIndex
pip install 'crewai-tools' mcpadapt 'pydantic[email]'  # CrewAI
pip install pydantic-ai-slim                 # Pydantic AI
pip install ag2                              # AG2 (formerly AutoGen)
```

## Project layout

```
mcp-mirror/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── docs/build-log/              # Detailed per-feature MDs of every build decision
├── src/mcp_mirror/
│   ├── types.py                 # ToolView, ToolDiff, Category, FieldDiff
│   ├── diff.py                  # Structural diff engine
│   ├── fixtures.py              # Rich-schema reference tools
│   ├── server.py                # Real MCP server (run via `python -m mcp_mirror.server`)
│   ├── capture.py               # Real framework captures (one fn per framework)
│   ├── scorecard.py             # Text rendering
│   └── cli.py                   # CLI entry point
└── tests/
    ├── test_diff.py             # Unit tests for the diff engine
    ├── test_capture.py          # Integration tests using real framework captures
    └── test_cli.py              # End-to-end CLI smoke tests
```

## Roadmap

- [ ] **Arcade as MCP source** — point at Arcade's hosted MCP server, comparing real production tools across frameworks
- [ ] **OpenAI LLM-payload validation** — make a real OpenAI call from each framework, intercept the exact function-schema payload sent over the wire, diff against the framework's introspected view (sanity-check that introspection matches reality)
- [ ] **Wire-level recording** — capture the actual JSON-RPC traffic, not just the framework's tool views, for the most paranoid comparison
- [ ] **Web report** — render an HTML scorecard with collapsible field details
- [ ] **CI mode** — run as a regression suite for framework maintainers (assert no new losses since last release)
- [ ] **Additional frameworks** — Goose, Semantic Kernel, DSPy, Magentic, Block's MCP-UI consumers

## Why "mcp-mirror"

A mirror shows you what you actually look like, not what you remember looking like. Same with MCP.

## License

MIT. Open contributions welcome — especially new framework adapters and additional rich-schema fixtures.
