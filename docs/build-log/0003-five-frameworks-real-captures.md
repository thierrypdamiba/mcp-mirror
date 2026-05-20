# 0003 — Five frameworks, real captures

**Date:** 2026-05-20
**Status:** Done — all five captures green against the bundled reference server.

## Setup

A real MCP server, `mcp_mirror.server`, exposes the fixtures over stdio using the official `mcp` Python SDK. Each framework adapter connects to it as a subprocess.

## Per-framework integration

### LangChain (`langchain-mcp-adapters` 0.2.2)

```python
async with stdio_client(params) as (r, w):
    async with ClientSession(r, w) as session:
        await session.initialize()
        lc_tools = await load_mcp_tools(session)
```

Key finding: `tool.args_schema` is **already a dict** (raw JSON Schema), not a Pydantic class. The MCP adapter package preserves the server's input schema verbatim. The earlier code path that called `_pydantic_to_jsonschema(tool.args_schema)` returned `{}` because `model_json_schema()` doesn't exist on a dict.

Renamed `_pydantic_to_jsonschema` to `_normalize_schema` to accept dict | Pydantic | None.

### LlamaIndex (`llama-index-tools-mcp` 0.4.8)

```python
client = BasicMCPClient(params.command, args=list(params.args or []))
spec = McpToolSpec(client=client)
li_tools = await spec.to_tool_list_async()
```

`tool.metadata.fn_schema` is a Pydantic v2 model class. Calling `model_json_schema()` on it produces a schema with `$defs` for nested types — that's where the structural transformation comes from.

### Pydantic AI (`pydantic-ai-slim` 1.99.0)

```python
mcp_server = MCPServerStdio(params.command, args=list(params.args or []))
async with mcp_server:
    tools = await mcp_server.list_tools()
```

Returns `mcp.types.Tool` instances directly — `tool.inputSchema`, `tool.outputSchema`, `tool.meta` all preserved. This is the most faithful adapter.

Note: `MCPServerStdio` is deprecated as of recent pydantic-ai versions in favor of `MCPToolset`. Suppress the `DeprecationWarning` to keep test output clean; migration is a future task.

### CrewAI (`crewai-tools` + `mcpadapt` + `pydantic[email]`)

```python
adapter = MCPServerAdapter(params)
tools = adapter.tools
```

Required two extra installs:

- `mcpadapt` — `crewai-tools/adapters/mcp_adapter.py` imports it directly; absent in the base install.
- `pydantic[email]` — CrewAI generates Pydantic models from the schema, and our `format: email` field triggers `email-validator` requirement.

`MCPServerAdapter` is sync (uses an internal thread pool). Wrapped in `asyncio.to_thread` to keep `capture.py`'s async surface uniform.

Big finding: CrewAI *extends* the description. 286 → 1388 chars on `send_message`. This is not documented anywhere I found before running the capture.

### AG2 (`ag2` 0.13.0)

```python
async with stdio_client(params) as (r, w):
    async with ClientSession(r, w) as session:
        await session.initialize()
        toolkit = await MCPClient.load_mcp_toolkit(
            session,
            use_mcp_tools=True,
            use_mcp_resources=False,
            resource_download_folder=None,
        )
```

AG2's `convert_tool` constructs an AG2 `Tool` with `parameters_json_schema = mcp_tool.inputSchema`. Input passes through, output schema and `_meta` don't.

## Live scorecard

```
tool                  ag2           crewai        langchain     llamaindex    pydantic-ai
------------------------------------------------------------------------------------------
send_message          -10 +1        -11 ~1 +12    -6 +1         -12 +9        +1
search_records        -9 +1         -14 ~2 +12    -6 +1         -13 +9        +1
```

## Diff-engine adjustments

None needed. The diff engine handled all five frameworks' output without modification. The data was the surprise, not the algorithm.

## Test coverage

`tests/test_capture.py` runs each capture against the real bundled server and asserts known properties (e.g., LangChain drops response schema, Pydantic AI is faithful). These are integration tests; they spawn the real MCP server subprocess and load real framework code.

All 16 tests pass.

## Next

`0004-cli-and-scorecard.md` — putting it all together at the CLI surface.
