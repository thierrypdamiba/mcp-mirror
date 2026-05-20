# 0002 — Simulators out, real captures in

**Date:** 2026-05-20
**Status:** Done — simulator code removed.

## Context

The original `src/mcp_mirror/adapters/` directory held *simulator* adapters: Python classes that encoded what I believed each framework's MCP adapter would do to a tool schema, based on reading docs and source.

Concrete encoded beliefs:

- LangChain would drop `examples` arrays and collapse `oneOf` titles.
- LlamaIndex would drop `format` constraints on strings.
- CrewAI would collapse `oneOf` to the first branch and drop `additionalProperties`.
- AG2 would collapse `oneOf` and drop `format`.
- Pydantic AI would be nearly faithful, only adding a version marker.

## What real captures revealed

When the simulators were replaced with live captures against `langchain-mcp-adapters 0.2.2`, `llama-index-tools-mcp 0.4.8`, `pydantic-ai-slim 1.99.0`, `crewai-tools` (current), and `ag2 0.13.0`:

- **LangChain preserves the *full* input schema** — `oneOf`, `format`, `enum`, `additionalProperties`, all intact. It does drop the response schema and the protocol-level `_meta`, but the input side is faithful.
- **LlamaIndex doesn't just drop `format`** — it converts the whole input schema through Pydantic model generation, which introduces `$defs` blocks, reorganizes properties, and adds Pydantic-style `title` fields throughout. Semantically near-equivalent, structurally very different.
- **CrewAI does much more than collapse oneOf** — it *extends* the tool description with multi-paragraph usage guidance text, ballooning a 286-char description into 1388 chars. The schema goes through `mcpadapt` + CrewAI's own Pydantic generator, producing the most structurally different view in the lineup.
- **AG2 passes `inputSchema` through verbatim** as `parameters_json_schema` — closer to faithful than I'd guessed, like Pydantic AI.
- **Pydantic AI returns the raw `mcp.types.Tool`** — completely faithful at the protocol level.

## Why this matters

The simulator approach was producing *plausible* but *materially wrong* output. The framework world moves faster than docs do. The only reliable signal is running the framework's actual code.

This is also exactly the point of the talk: assumptions about framework behavior don't survive contact with the real adapter. The tool now embodies that lesson — every claim it makes is grounded in a live capture, not a belief.

## Removal log

- Deleted `src/mcp_mirror/adapters/` (six files: `__init__.py`, `base.py`, `langchain.py`, `llamaindex.py`, `crewai.py`, `pydantic_ai.py`, `ag2.py`).
- Deleted `tests/test_adapters.py` — tests asserting on simulated behavior.
- Replaced the CLI's adapter loop with a capture loop in `cli._run()`.

## Replacement: `src/mcp_mirror/capture.py`

One function per framework, each connecting a real adapter to a real MCP server. The diff engine and types are unchanged — the data flowing in is just different (and correct).

## Next

`0003-five-frameworks-real-captures.md` — getting each capture function working against the bundled server.
