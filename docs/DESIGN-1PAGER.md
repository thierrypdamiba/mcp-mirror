# mcp-mirror — One-Page Design

**Thierry Damiba** · thierry@arcade.dev · [repo](https://github.com/thierrypdamiba/mcp-mirror) · full design: [`DESIGN.md`](./DESIGN.md)

> Same MCP server, five real agent frameworks (LangChain, LlamaIndex, CrewAI, Pydantic AI, AG2). Capture what each hands to the LLM; show adapter drift deterministically, then test the risky cases behaviorally. Open-source, runs in under a minute. Both layers built.

## Problem

The adapter layer between an MCP server and the LLM is real, and every framework lands somewhere different: `oneOf` survives in one, flattens in another; LlamaIndex explodes schemas into `$defs`; CrewAI snake-cases names; descriptions truncate; response schemas drop; OpenAI rejects `oneOf` outright so the tool never reaches the model. The only way to know what *your* framework does today is to integrate it and read the bytes. No scorecard, no shared vocabulary, no measurement.

## Key insight

**The adapter diff tells you *what changed and where*; the model eval tells you *whether it matters*.** Build both, compose them.

- **Layer 1 — adapter diff.** Recursively compare each framework's tool view to the server's; record dropped, added, and rewritten fields. Microseconds, zero deps, deterministic, 100% of tools. *A regression detector and localizer, not a severity classifier.*
- **Layer 2 — behavioral eval.** Run the same cases against each framework's view via `arcade_evals`; score selection + arguments against the server's ground truth. One `EvalSuite` per framework, so a schema OpenAI refuses is recorded as `rejected`, not a fatal error. *Supplies the severity Layer 1 can't.*

## What you see

Layer 1 — real Arcade gateway data for `Linear_CreateIssue` (field-level deltas vs. what the server announced):

| Framework | Delta | Overall |
| --------- | ----- | ------- |
| Pydantic AI | `+1` | additive only |
| LangChain | `-1 +1` | systematic metadata strip |
| AG2 | `-4 +1` | mild schema simplification |
| LlamaIndex | `-16 +43` | heavy schema rewrite |
| CrewAI | `-16 ~1 +45` | heavy schema rewrite + name change |

`−` dropped a server field · `~` changed one in place · `+` added a framework field.

The important thing is not the word "lossy" — that label saturates. The signal is the pattern: LangChain's `-1 +1` is one stable metadata behavior across all 100 tools; CrewAI and LlamaIndex degrade sharply on complex schemas. Layer 2 then tests whether those structural changes alter tool selection or arguments. A framework that preserves a schema feature the provider rejects can still be behaviorally worst: the model never receives the tool. *(Behavioral gateway run still Phase 2.)*

## Key decisions

| Choice | Why |
| ------ | --- |
| **Real captures, never simulators** | An early simulator *assumed* LangChain collapses `oneOf`; the live run disproved it. Behavior drifts faster than docs. |
| **Two layers** | The diff is deterministic and complete; the eval is partial but tells you impact. Neither substitutes for the other. |
| **Score vs. server ground truth** | The target bug is a framework relaxing a constraint; caught only by scoring against the real tool's contract, not the framework's. |

## Where it sits / why now

Every benchmark in this space holds the framework constant and varies the model (BFCL, tau-bench, MCP-Bench, MCP-Atlas, MCPVerse) or grades the server (Arcade ToolBench, MCP conformance). **mcp-mirror does the opposite — holds the server constant, varies the framework, measures the adapter.** That axis is unmeasured. Fan et al.'s martingale analysis of MCP is useful background for information fidelity, but it targets error accumulation across *sequential* tool calls, not empirical adapter drift. MCP is becoming the default protocol across frameworks, which should shrink divergence over time — the argument for mapping it **now**, while it's large, and tracking convergence.

## Status & ownership

Both layers built; sample run against the live Arcade gateway committed. Thierry research artifact in a public repo, complementary to (not inside) the Arcade product: the gateway is the server-side layer Arcade owns; mcp-mirror measures the client-side adapter layer customers run every day. **Next:** golden cases for real Arcade toolkits (Phase 2) → per-model + distractor studies (Phase 3).
