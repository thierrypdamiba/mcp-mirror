# Changelog

All notable changes to mcp-mirror, in chronological order. Detailed per-decision notes live in `docs/build-log/`.

## [0.1.0] — 2026-05-20

### Added

- Real MCP server (`mcp_mirror.server`) exposing rich-schema reference tools (`send_message`, `search_records`) via the official `mcp` Python SDK over stdio.
- Structural diff engine (`mcp_mirror.diff`) that categorizes field-level deltas as `faithful`, `lossy`, `additive`, or `transformative`.
- Reference fixtures (`mcp_mirror.fixtures`) with `oneOf`, `enum`, `format`, nested objects, response schemas, and `_meta` — deliberately rich to surface adapter behavior.
- Real framework captures (`mcp_mirror.capture`) for:
  - LangChain via `langchain-mcp-adapters`
  - LlamaIndex via `llama-index-tools-mcp` + `BasicMCPClient`
  - Pydantic AI via `pydantic_ai.mcp.MCPServerStdio`
  - CrewAI via `crewai-tools.MCPServerAdapter` (sync, wrapped in `asyncio.to_thread`)
  - AG2 via `autogen.mcp.mcp_client.MCPClient.load_mcp_toolkit`
- CLI (`mcp_mirror.cli`) with `--server`, `--framework`, `--tool`, `--detail`, `--json`.
- Scorecard rendering (`mcp_mirror.scorecard`) producing slide-ready text output.
- Test suite covering the diff engine (unit) and real framework captures (integration).

### Removed

- The original simulator-based adapters (`mcp_mirror.adapters.*`) were removed after live captures showed they encoded materially wrong assumptions about each framework's behavior. See `docs/build-log/0002-simulators-out-real-captures-in.md`.

### Findings (initial run against bundled fixtures)

- **Pydantic AI**: most faithful — returns raw `mcp.types.Tool` verbatim.
- **LangChain**: drops response schema and protocol `_meta`; preserves input schema (including `oneOf`, `format`, `enum`).
- **AG2**: similar to LangChain. Input schema preserved via `parameters_json_schema`.
- **LlamaIndex**: heavy structural transformation. Converts JSON Schema → Pydantic → JSON Schema, introducing `$defs` and reorganizing.
- **CrewAI**: most invasive. *Extends* tool descriptions 5x with usage guidance text; restructures schemas through `mcpadapt` + CrewAI Pydantic generation.

## Unreleased — roadmap

- Arcade as MCP source (requires `ARCADE_API_KEY`).
- OpenAI LLM-payload validation (requires `OPENAI_API_KEY`).
- Wire-level JSON-RPC recording.
- HTML scorecard report.
- CI mode for framework maintainer regression suites.
