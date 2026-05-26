# mcp-mirror — Design Doc

**Author:** Thierry Damiba (thierry@arcade.dev)
**Status:** Draft for review
**Last updated:** 2026-05-26

---

## 1. Problem

An MCP server announces a tool with a name, description, input schema, output schema, and metadata. That announcement is **not** what the LLM ultimately sees. Between the server and the model sits the agent framework's adapter — `langchain-mcp-adapters`, `llama-index-tools-mcp`, `crewai-tools`, `pydantic_ai.mcp`, `autogen.mcp`, etc. Each adapter makes its own decisions about how to translate the tool into the framework's internal representation, and from there into the function-calling payload the LLM receives.

These decisions are undocumented, inconsistent across frameworks, and invisible to the developer. When an agent misbehaves, engineers debug the model or the server — almost never the adapter layer in between. There is no shared vocabulary, no public comparison, and no methodology to make this layer legible.

mcp-mirror exists to make that layer measurable.

## 2. Goals / Non-goals

### Goals

- Show, for any MCP server, exactly what each major agent framework hands to the LLM — captured from the framework's *real* code path, not simulated.
- Quantify the difference between the server's announcement and each framework's representation at the field level.
- **Determine whether those differences actually change agent behavior** — i.e., tool-selection and argument accuracy — not merely whether the schema shape changed.
- Be reproducible: point it at the bundled reference server or a real Arcade gateway and get the same answer anyone else would.
- Run in CI so framework-version drift is caught as a regression.

### Non-goals

- We are not ranking frameworks as "good" or "bad." Each transformation is internally coherent for its own runtime. We measure fidelity to the server announcement and impact on agent behavior; we don't editorialize beyond that.
- We are not building a general-purpose agent eval harness (Arcade Evals, Braintrust, Phoenix already exist). We measure one specific thing: *what the adapter layer does to a tool, and whether it matters.*
- We are not modifying or forking the frameworks. We use their published integration code as-is.

## 3. The core insight: numbers measure change, prompts measure intent

This is the load-bearing design decision, and it came out of internal review.

The structural diff produces counts like `-11 ~1 +28`. But a count is **quantity of change, not semantic impact**. Two `-1 lossy` deltas can mean opposite things:

| Delta | Example | Impact on the LLM |
|---|---|---|
| `-1 lossy` | adapter drops a `title` field | none — the model never needed it |
| `-1 lossy` | adapter drops an `enum` on a status arg | severe — the model now emits invalid values |

The number treats these identically. It cannot tell you whether the agent still selects the right tool, still fills arguments correctly, still fulfills user intent. **You cannot derive intent preservation from a structural count.**

To measure impact, you have to run prompts through an LLM against each framework's representation of the tool and observe behavior. That is a fundamentally different (and more expensive) measurement than a schema diff.

mcp-mirror therefore has **two layers**:

### Layer 1 — Structural diff (implemented)

Deterministic, fast, no LLM required. For each tool × framework, categorize every field-level delta as `faithful`, `lossy`, `additive`, or `transformative`. Answers: *what changed?*

This layer is necessary — it tells you where to look — but not sufficient. It is the "here are the suspects" layer.

### Layer 2 — Behavioral eval (designed here, partially implemented as the OpenAI payload-validation task)

For each tool × framework, run a battery of prompts through a real LLM and measure:

- **Tool-selection accuracy** — given a task the tool is meant for, does the model select it? Given a task it's *not* meant for, does the model correctly avoid it?
- **Argument accuracy** — when the model calls the tool, are the arguments valid against the *server's* schema (not just the framework's degraded one)?
- **Behavioral delta** — does the framework's representation produce different selections/arguments than the server's own representation would?

Answers: *did the change matter?* This is the "here is which suspects are actually guilty" layer.

The two layers compose: Layer 1 ranks tools by how much they change; Layer 2 confirms which of those changes degrade behavior. A tool with a big Layer-1 delta but no Layer-2 behavioral change is cosmetic. A tool with a small Layer-1 delta but a real Layer-2 behavioral change is a landmine. Both are findings.

## 4. Architecture

```
                          ┌──────────────────────────┐
                          │  MCP server (real)        │
                          │  - bundled fixtures (stdio)│
                          │  - Arcade gateway (HTTP)   │
                          └────────────┬──────────────┘
                                       │ MCP protocol
            ┌──────────────┬───────────┼───────────┬──────────────┐
            ▼              ▼           ▼            ▼              ▼
       LangChain      LlamaIndex    CrewAI     Pydantic AI      AG2
       adapter         adapter      adapter      adapter       adapter
            │              │           │            │              │
            ▼              ▼           ▼            ▼              ▼
       ToolView        ToolView    ToolView     ToolView       ToolView    ← what the LLM sees
            └──────────────┴───────────┼───────────┴──────────────┘
                                       │
                  ┌────────────────────┴─────────────────────┐
                  ▼                                           ▼
         Layer 1: structural diff                  Layer 2: behavioral eval
         (diff.py — deterministic)                 (prompt battery + real LLM)
                  │                                           │
                  ▼                                           ▼
            field-level deltas                       selection/argument scores
                  └────────────────────┬──────────────────────┘
                                       ▼
                                  scorecard / report
```

### Module layout (current)

| Module | Responsibility |
|---|---|
| `spec.py` | `ServerSpec` tagged union — stdio or streamable-HTTP source. |
| `server.py` | Bundled reference MCP server (rich-schema fixtures) over stdio. |
| `arcade_auth.py` | OAuth 2.1 + RFC 9728 discovery + RFC 7591 DCR + PKCE for Arcade gateways. |
| `capture.py` | One real capture function per framework; transport-agnostic via `_session()`. |
| `types.py` | `ToolView`, `ToolDiff`, `FieldDiff`, `Category`. |
| `diff.py` | Layer 1 — recursive structural diff + categorization. |
| `scorecard.py` | Text rendering of the diff. |
| `cli.py` | Orchestration, source resolution, canonical name matching, output. |
| `llm_eval.py` | **(planned)** Layer 2 — prompt battery, LLM invocation, behavioral scoring. |

## 5. Layer 2 design (the part that needs building)

### Inputs

- A tool's **server view** (ground truth) and its N **framework views**.
- A **prompt battery** per tool: a set of (user_message, expected_behavior) pairs. Expected behavior is one of: *should-call-this-tool*, *should-not-call-this-tool*, *should-call-with-args(X)*.

### How prompts are sourced

We do not hand-write a battery for every tool — that doesn't scale to 100+ tools. Three tiers:

1. **Generated from the server schema** — for each tool, synthesize positive prompts ("a user who wants exactly this") and hard-negative prompts ("a user who wants a sibling tool") using the tool's own description and a generator LLM. Cache them.
2. **Golden set** — a small hand-curated battery for the highest-traffic tools (e.g., `Github_CreateIssue`, `Gmail_SendEmail`) to anchor the generated ones.
3. **Replay** — optionally, real anonymized prompts from production traces (out of scope for v1).

### The measurement

For each (tool, framework, prompt):

1. Construct a single-turn function-calling request to the LLM with **only that framework's representation** of the tool (plus a few distractor tools to make selection non-trivial).
2. Capture the model's response: did it call the tool? with what arguments?
3. Score:
   - **selection correct?** (matched expected should-call / should-not-call)
   - **arguments valid against the *server* schema?** (not the framework's — the server is ground truth)
4. Repeat with the **server's own representation** as the control.
5. The **behavioral delta** is the difference in scores between the framework view and the server control.

### Why validate arguments against the server schema, not the framework's

If a framework drops an `enum` constraint, the model may emit a value the framework's degraded schema accepts but the *real tool* rejects. Scoring against the server schema catches exactly this class of silent failure — the one the structural diff flags as "lossy" but cannot prove harmful.

### Cost control

Layer 2 is expensive (one LLM call per tool × framework × prompt). Mitigations:

- Run Layer 1 first; only run Layer 2 on tools whose Layer-1 delta exceeds a threshold (cosmetic-only tools skip the expensive layer).
- Use a cheap, fast model for the selection/argument calls; reserve a stronger model for the prompt generator.
- Cache generated prompts and model responses keyed by (tool-hash, framework-version, model).
- Batch where the provider supports it.

### Wire-level cross-check (the original task #26)

Independently of behavior, we validate that mcp-mirror's *introspected* view of each framework equals what the framework actually puts on the wire to the LLM. We do this by intercepting the HTTP request to the model provider (httpx transport hook) during a real agent run and diffing the captured `tools` array against the introspected `ToolView`. If they diverge, our introspection is wrong and Layer 1's numbers are suspect. This is a correctness check on mcp-mirror itself, not on the frameworks.

## 6. Credentials & security

- All secrets via environment, resolved at runtime through `op run --env-file=.env` (1Password references, never raw secrets on disk). Built-in zero-dep `.env` fallback for non-1Password users.
- Arcade gateway auth uses the spec-correct OAuth 2.1 flow (discovery → DCR → PKCE), cached per-gateway under `~/.cache/mcp-mirror/`. No long-lived API key is used as a Bearer against the gateway; mcp-mirror authenticates exactly as a production MCP client would.
- The OpenAI key (Layer 2) is read from env only at eval time and never logged.

## 7. Reproducibility & CI

- Framework versions are resolved at runtime via `importlib.metadata` and recorded in every run.
- Sample runs are snapshotted under `docs/sample-runs/` as the canonical reference dataset.
- A CI mode (planned) snapshots the scorecard against pinned framework versions and fails the build if a new lossy/transformative delta appears since the last release — turning "the adapter changed under us" into a caught regression instead of a production surprise.

## 8. Open questions

1. **Distractor selection for Layer 2.** How many and which distractor tools accompany the tool under test? Too few and selection is trivial; too many and we measure tool-overload, not adapter fidelity. Proposal: a fixed, representative distractor set of ~8 tools held constant across all tests.
2. **Which model(s) for Layer 2?** Behavior is model-specific. Do we report per-model, or pick one canonical model? Proposal: default to one fast model, allow `--model` override, report the model in the output.
3. **Prompt-battery trust.** Generated prompts are themselves LLM output and may be wrong. How much hand-validation does the golden set need before we trust the generated battery? 
4. **Non-determinism.** LLM calls vary run to run. Do we run each prompt k times and report a rate? Proposal: k=3 at temperature 0, report selection rate.
5. **Dedicated OAuth client.** Layer-1 Arcade auth currently uses DCR per run. For a published tool, do we register a single long-lived mcp-mirror client, or keep ephemeral DCR? Ephemeral is cleaner but creates a client record per machine.

## 9. Milestones

- [x] Layer 1 structural diff across 5 real frameworks (stdio + HTTP).
- [x] Real Arcade gateway via spec-correct OAuth.
- [x] Live reference dataset (100 tools × 5 frameworks).
- [x] Presentation site.
- [ ] Wire-level introspection cross-check (task #26 narrow form).
- [ ] Layer 2 behavioral eval (the colleague's point — prompt-based intent measurement).
- [ ] CI regression mode.
- [ ] Dedicated OAuth client + PyPI release.
