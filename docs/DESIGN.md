# mcp-mirror — Design Document

**Author:** Thierry Damiba (thierry@arcade.dev)
**Status:** Draft
**Last updated:** 2026-05-26

---

## Summary

`mcp-mirror` is a diagnostic tool that reveals how different AI agent frameworks transform a tool definition before an LLM sees it. It connects one MCP server to several real frameworks simultaneously, captures the tool representation each framework produces, and reports the differences — both structurally (what changed in the schema) and behaviorally (whether the change alters how the model uses the tool). The goal is to make a normally invisible translation layer measurable, so developers can understand why the same tool behaves differently across frameworks.

## Background

### Model Context Protocol (MCP)

MCP is an open protocol that standardizes how AI applications connect to external tools and data. An **MCP server** exposes a set of **tools**. Each tool definition includes a name, a natural-language description, a JSON Schema for its inputs, an optional schema for its outputs, and optional metadata. When an AI application wants to use a tool, it reads these definitions and passes them to a language model so the model can decide which tool to call and with what arguments.

### Agent frameworks

Most production AI agents are not written directly against a model API. They are built on **agent frameworks** — libraries such as LangChain, LlamaIndex, CrewAI, Pydantic AI, and AG2 (formerly AutoGen) — that handle orchestration, memory, and tool integration. Each of these frameworks ships an MCP integration: code that connects to an MCP server, reads its tool definitions, and converts them into the framework's own internal tool representation. That internal representation is what eventually becomes the function-calling payload sent to the language model.

### The gap

The conversion from "what the MCP server announced" to "what the language model receives" is performed entirely inside the framework's adapter. These adapters make independent, undocumented decisions:

- Some preserve the input schema exactly; others convert it through an intermediate type system that reorganizes or expands it.
- Some carry the output schema and metadata forward; others discard them.
- Some rewrite the tool's name or extend its description.

The result is that the *same* MCP server produces *different* tool definitions in the model's context depending on which framework loaded it. This is rarely visible to the developer. When an agent selects the wrong tool or supplies bad arguments, the natural instinct is to blame the model or the server — not the adapter sitting between them. There is no standard way to inspect this layer, no shared vocabulary for the kinds of changes it makes, and no way to compare frameworks against one another.

## Problem statement

Developers building agents on top of MCP have no way to answer two questions:

1. **What does each framework actually hand to the model for a given tool?**
2. **Do those differences change the agent's behavior — and if so, how badly?**

`mcp-mirror` answers both.

## Goals

- For any MCP server, capture what each major agent framework hands to the model — from the framework's real integration code, not a reimplementation or simulation.
- Quantify the difference between the server's tool definition and each framework's version, at the level of individual schema fields.
- Determine whether those differences change the model's tool-selection and argument-construction behavior, not merely whether the schema shape changed.
- Be reproducible: anyone pointing the tool at the same server gets the same result.
- Support running as a continuous-integration check, so that a framework upgrade that silently changes tool handling is caught as a regression.

## Non-goals

- This is not a framework ranking. Every framework's transformation is coherent for its own runtime. The tool measures fidelity to the server definition and impact on model behavior; it does not declare a winner.
- This is not a general agent-evaluation platform. Several mature products already evaluate agent quality broadly. `mcp-mirror` measures one narrow thing: what the adapter layer does to a tool and whether it matters.
- This does not modify the frameworks. It uses their published integration code unchanged.

## Approach

`mcp-mirror` measures the adapter layer in two distinct layers, because a single measurement cannot answer both questions in the problem statement.

### Layer 1 — Structural diff

A deterministic, fast comparison that requires no language model. For each tool and each framework, it walks the framework's tool representation against the server's original announcement and classifies every field-level difference into one of four categories:

- **faithful** — no difference.
- **lossy** — a field the server provided that the framework dropped. The model never sees it.
- **additive** — a field the framework introduced that the server did not provide. It consumes space in the model's context.
- **transformative** — a field whose value changed without being added or removed (for example, a tool name rewritten from one casing convention to another).

This layer answers *what changed*. It is fast enough to run across hundreds of tools and is the right tool for pointing at where differences exist. It is necessary but not sufficient, for the reason described in the next section.

### Layer 2 — Behavioral evaluation

A measurement that uses a real language model. For each tool and framework, it runs a set of test prompts and observes whether the model, given that framework's version of the tool:

- selects the tool when it should and avoids it when it shouldn't (**selection accuracy**), and
- constructs arguments that are valid against the *server's* original schema (**argument accuracy**).

It then compares these results against a control run that uses the server's own tool definition. The difference between the two is the **behavioral delta**: the degree to which the framework's transformation changed how the model uses the tool.

This layer answers *whether the change matters*.

## Why two layers are necessary

The central design decision is that structural counts cannot, by themselves, tell you whether a transformation is harmful. A count measures the quantity of change, not its consequence. Consider two differences that both register as "one dropped field":

| Difference | Consequence for the model |
|---|---|
| The framework drops a cosmetic `title` field. | None. The model never used it. |
| The framework drops the list of allowed values (`enum`) on a status argument. | Severe. The model now produces values the real tool rejects. |

Both score identically in Layer 1. To distinguish them, you must observe the model's actual behavior, which requires running prompts through it. This is why Layer 2 exists, and why it cannot be replaced by a more clever structural metric.

The two layers compose. Layer 1 ranks tools by how much they change and is cheap to run everywhere. Layer 2 confirms which of those changes actually degrade behavior and is expensive, so it is run selectively. A tool with a large structural delta but no behavioral delta is cosmetic noise. A tool with a small structural delta but a real behavioral delta is a hidden hazard. Both are useful findings, and only the combination surfaces both.

## Detailed design

### System overview

```
                    MCP server (real)
                  ┌────────────────────┐
                  │ bundled fixtures    │  (local, stdio transport)
                  │ or Arcade gateway   │  (remote, HTTP transport, OAuth)
                  └─────────┬───────────┘
                            │ MCP protocol
     ┌───────────┬──────────┼──────────┬───────────┐
     ▼           ▼          ▼          ▼           ▼
 LangChain  LlamaIndex   CrewAI   Pydantic AI    AG2     (real framework adapters)
     │           │          │          │           │
     ▼           ▼          ▼          ▼           ▼
  the tool representation each framework hands to the model
     └───────────┴──────────┼──────────┴───────────┘
                  ┌──────────┴───────────┐
                  ▼                      ▼
          Layer 1: structural    Layer 2: behavioral
          diff (deterministic)   eval (prompts + model)
                  └──────────┬───────────┘
                             ▼
                     scorecard / report
```

### Source abstraction

The MCP server under test can be either a local process (stdio transport) or a remote service (HTTP transport). A single source abstraction represents both, so every capture works identically regardless of where the server runs. The tool ships with a bundled reference server exposing deliberately rich tool schemas, so it produces meaningful results with no external dependencies.

### Capture

For each framework, a dedicated capture routine connects to the server through that framework's real MCP integration and reads back the tool representation the framework would expose to its agent. The captured representation is normalized into a common shape so the diff engine can compare them uniformly. Crucially, no framework behavior is simulated — each capture exercises the framework's actual published code path, so the results reflect real behavior and stay accurate as frameworks evolve.

### Structural diff

The diff engine recursively compares two normalized tool representations and emits a list of categorized field-level differences. The overall category for a tool is the most severe difference it contains, ordered lossy > transformative > additive > faithful.

### Behavioral evaluation

Behavioral evaluation needs test prompts for each tool. Hand-authoring prompts for every tool does not scale, so prompts come from three tiers:

1. **Generated** — for each tool, a generator model synthesizes positive prompts (a user who wants exactly this tool) and hard-negative prompts (a user who wants a similar but different tool), derived from the tool's own description. These are cached.
2. **Golden** — a small, hand-written set for the highest-traffic tools, used to anchor and validate the generated prompts.
3. **Replay** — optionally, real anonymized prompts from production usage (future work).

For each test, the tool under evaluation is presented to the model alongside a fixed set of distractor tools, so that selecting it is a genuine decision rather than the only option. The model's response is scored for selection correctness and for argument validity against the server's schema. The same prompt is run against the server's own tool definition as a control, and the difference is reported.

Argument validity is deliberately checked against the **server's** schema, never the framework's. The most important failure this tool hunts for is the case where a framework relaxes or drops a constraint, the model then produces a value the framework accepts but the real tool rejects, and the failure surfaces only at execution time. Scoring against the server schema catches this directly.

### Self-correctness check

Independently of measuring the frameworks, the tool verifies its own introspection. During a real model call, it intercepts the outgoing request to the model provider and compares the tool definitions actually on the wire against the representation the capture step reported. If they diverge, the tool's own introspection is wrong and its structural numbers cannot be trusted. This guards against the tool silently measuring the wrong thing.

## Security and credentials

- All secrets are supplied through environment variables and are never stored on disk in plaintext. The recommended workflow resolves secret references from a secrets manager at runtime, so configuration files contain references rather than secrets.
- Connecting to a remote MCP gateway uses the standard authorization flow that any compliant MCP client would use: the tool discovers the gateway's authorization server from its metadata, registers itself dynamically as a client, and completes a browser-based authorization with proof-key protection. Tokens are cached locally per gateway and refreshed automatically. No static API key is used as a bearer credential against the gateway.
- The model-provider key used for behavioral evaluation is read from the environment only when needed and is never logged.

## Testing and reproducibility

- Framework versions are detected at runtime and recorded with every result, so a result can always be tied to the exact framework versions that produced it.
- Reference runs are stored as canonical snapshots, so changes in output over time can be attributed either to a framework change or to a tool change.
- A continuous-integration mode compares the current scorecard against a pinned baseline and fails the build if a new lossy or transformative difference appears, converting "a dependency changed our tool handling" from a production surprise into a caught regression.

## Alternatives considered

- **Static analysis of each framework's adapter source.** Rejected: encodes assumptions about framework behavior that drift out of date as frameworks change, and cannot observe runtime behavior. Running the real code is the only reliable source of truth.
- **Structural diff only.** Rejected as incomplete: as argued above, a structural count cannot distinguish a harmless change from a harmful one. The behavioral layer is required to answer the question that actually matters.
- **A full agent-evaluation harness.** Rejected as out of scope: mature products already evaluate agent quality broadly. This tool deliberately measures one narrow, currently-unmeasured thing.

## Open questions

1. **Distractor set for behavioral evaluation.** How many and which distractor tools should accompany the tool under test? Too few makes selection trivial; too many measures tool-overload rather than adapter fidelity. Current proposal: a fixed, representative set held constant across all tests.
2. **Model choice.** Behavior is model-specific. Should results be reported per model, or against one canonical model? Current proposal: default to one fast model, allow an override, and always record which model produced a result.
3. **Trust in generated prompts.** Generated prompts are themselves model output and may be wrong. How much hand-validation does the golden set need before the generated battery is trustworthy?
4. **Non-determinism.** Model responses vary between runs. Current proposal: run each prompt several times at temperature zero and report a rate rather than a single outcome.

## Status

Built:

- Structural diff across five real frameworks, over both local and remote transports.
- Remote gateway connection using the standard authorization flow.
- A live reference dataset of one hundred production tools across five frameworks.
- A presentation site rendering the live results.

Planned:

- The self-correctness wire-level check.
- The behavioral evaluation layer.
- The continuous-integration regression mode.
- A public package release.
