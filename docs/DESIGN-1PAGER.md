# mcp-mirror — One-Page Design

**Thierry Damiba** · thierry@arcade.dev · [repo](https://github.com/thierrypdamiba/mcp-mirror) · full design: [`DESIGN.md`](./DESIGN.md)

> Same MCP server, five real agent frameworks (LangChain, LlamaIndex, CrewAI, Pydantic AI, AG2). Capture what each hands to the LLM; report what differs structurally **and** behaviorally. Open-source, runs in under a minute. Both layers built.

## Problem

The adapter layer between an MCP server and the LLM is real, and every framework lands somewhere different: `oneOf` survives in one, flattens in another; LlamaIndex explodes schemas into `$defs`; CrewAI snake-cases names; descriptions truncate; response schemas drop; OpenAI rejects `oneOf` outright so the tool never reaches the model. The only way to know what *your* framework does today is to integrate it and read the bytes. No scorecard, no shared vocabulary, no measurement.

## Key insight

**A structural diff tells you *what* changed; only running prompts through a model tells you *whether it matters*.** Build both, compose them.

- **Layer 1 — structural diff.** Recursively compare each framework's tool view to the server's; categorize every field delta as `faithful` / `lossy` / `additive` / `transformative`. Microseconds, zero deps, deterministic, 100% of tools. *A change localizer, not a severity classifier.*
- **Layer 2 — behavioral eval.** Run the same cases against each framework's view via `arcade_evals`; score selection + arguments against the server's ground truth. One `EvalSuite` per framework, so a schema OpenAI refuses is recorded as `rejected`, not a fatal error. *Supplies the severity Layer 1 can't.*

## What you see

```
tool                  ag2        crewai       langchain   llamaindex   pydantic-ai
send_message          -10 +1     -11 ~1 +12   -6 +1       -12 +9       +1
   legend:  + additive   - lossy   ~ transformative   (field-level deltas vs. server)

Layer 2:  langchain {pass 3, warn 1}   ag2 {rejected: "oneOf is not permitted"}
```

The `rejected` track is the point: Layer 1 says AG2 is *mostly faithful*; Layer 2 reveals the model **never sees the tool**. Neither layer alone tells you that.

## Key decisions

| Choice | Why |
| ------ | --- |
| **Real captures, never simulators** | An early simulator *assumed* LangChain collapses `oneOf`; the live run disproved it. Behavior drifts faster than docs. |
| **Two layers** | A dropped `title` (harmless) and a dropped `enum` (breaking) both score `-1 lossy` — only behavior separates them. |
| **Score vs. server ground truth** | The target bug is a framework relaxing a constraint; caught only by scoring against the real tool's contract, not the framework's. |

## Where it sits / why now

Every benchmark in this space holds the framework constant and varies the model (BFCL, τ-bench, MCP-Bench) or grades the server (Arcade ToolBench). **mcp-mirror does the opposite — holds the server constant, varies the framework, measures the adapter.** That axis is empty. The AAMAS 2026 fidelity paper proves information degrades through MCP *in theory*; mcp-mirror measures *where*, empirically, per framework. MCP is becoming the default protocol across frameworks, which will shrink the divergence over time — the argument for mapping it **now**, while it's large, and tracking the convergence.

## Status & ownership

Both layers built; sample run against the live Arcade gateway committed. Thierry research artifact in a public repo, complementary to (not inside) the Arcade product: the gateway is the server-side layer Arcade owns; mcp-mirror measures the client-side adapter layer customers run every day. **Next:** golden cases for real Arcade toolkits (Phase 2) → per-model + distractor studies (Phase 3).
