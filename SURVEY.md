# v0.1 implementation survey

Surveyed against `DESIGN.md` section 17 on 2026-09-04. The baseline source
snapshot is local commit `533f74c`. Status terms are **Done**, **Partial**,
**Missing**, and **Inferred**. **Inferred** means the repository does not
directly prove the claim.

## Follow-up closure

The findings below are preserved as the sourced baseline survey at `533f74c`.
All gaps it identified as recommended v0.1 follow-up are now closed:

- `85c7ff0` added a local streamable-HTTP fixture, negotiated-version coverage,
  CLI exit-code `2` and `3` contracts, and migration from the deprecated MCP
  HTTP client alias.
- `a9dc5d1` replaced Pydantic AI's deprecated `MCPServerStdio` path with the
  supported `MCPToolset` and explicit FastMCP transports.
- `231b54a` added exact `RendererEvidence`, independent adapter protocol-version
  capture, cross-version scan and baseline refusal, per-renderer fixture
  goldens, and machine/human evidence output. It also removed unsupported
  provider-request claims.
- The evidence pass found and corrected two public-data errors: OpenAI Agents
  SDK `0.20.0` is the locked measured version rather than `0.22.0`, and CrewAI
  preserves the fixture's `anyOf` but collapses its `oneOf`, so the combined
  capability is partial rather than fully present.
- J5 can no longer be filtered out, markdown has a dedicated J5 findings
  section, and the internal cross-job `worst` value has been removed. There is
  no overall framework verdict.
- `DESIGN.md` now describes the five shipped renderers, three-way annotation
  semantics, explicit evidence boundaries, dual source/renderer protocol
  enforcement, current milestones, and the contribution path. The expired
  2026-07-28 launch hook is recorded as historical; replacement framing remains
  an owner/marketing decision.

Current verification passes 63 tests across all five installed renderers, data
validation, the complete site build, the wheel build, and a same-version JSON
baseline round trip. The only Python warning is an upstream CrewAI internal
deprecation. No model or model API key is used.

## Baseline runtime verification (`533f74c`)

The intended development path is the locked `uv` environment, not the system
Python import path.

- `python3 -m pytest tests -q`: **failed during collection** because the
  `src/` package was not installed in that interpreter.
- `uv sync --locked --extra dev --extra all`: **passed**.
- `uv run pytest tests -q -rs`: **passed, 46 tests**, with all five registered
  renderers installed. It emitted deprecation warnings from CrewAI internals
  and the Pydantic AI `MCPServerStdio` API.
- `uv run mcp-mirror frameworks`: reported LangChain 0.3.0, Pydantic AI
  1.107.0, CrewAI 1.14.7, OpenAI Agents SDK 0.20.0, and Mastra 1.17.3.
- The exact definition-of-done scan against `fixtures/tricky_server.py` for
  LangChain, Pydantic AI, and CrewAI exited 0 and printed an
  MCP-2025-11-25-tagged J1-J5 scorecard.
- A JSON report written with `--out` loaded as a baseline on the next run.
  `--fail-on-drift` exited 0 with `no drift`.
- `python3 data/validator/validate.py data`: **passed**, 15 capabilities across
  5 frameworks.
- `npm run build`: **passed** through data aggregation, news validation,
  TypeScript, Vite, and the standalone build. Vite warned that one JavaScript
  chunk exceeds 500 kB after minification.
- `npm ci --prefix src/mcp_mirror/renderers/mastra_node`: **passed**. npm
  reported a deprecated transitive `@modelcontextprotocol/server-legacy`
  package and an unapproved optional `fsevents` install script.
- `uv build --wheel`: **passed**. The wheel contains the Mastra Python wrapper,
  Node worker, and `package.json`. The worker lockfile was not tracked in the
  baseline; this follow-up now tracks it.

No model was called and no model API key was used.

## Milestone 1: models and source loader

**Overall: Done, with Partial test coverage.**

- **Done:** Pydantic models define `ToolRep`, `Difference`, `FrameworkRun`, and
  `Report` in `src/mcp_mirror/models.py:14-66,114-131`.
- **Done:** `ToolRep` is the common source and rendering representation in
  `src/mcp_mirror/models.py:36-53` and
  `src/mcp_mirror/normalize.py:14-67`.
- **Done:** stdio and streamable-HTTP specifications are parsed in
  `src/mcp_mirror/source.py:39-52`; their transports are opened in
  `src/mcp_mirror/source.py:77-89`.
- **Done:** the initialized MCP session supplies `protocolVersion` in
  `src/mcp_mirror/source.py:69-75`, and the CLI records it on the report in
  `src/mcp_mirror/cli.py:190-196`.
- **Done:** `--spec-version` rejects a different negotiated version with exit
  code 3 in `src/mcp_mirror/cli.py:33-36,111-113,151-156`.
- **Partial:** `tests/test_renderers.py:29-36` exercises stdio loading and
  confirms a non-unknown protocol version. There is no HTTP transport test.
- **Missing:** no CLI test asserts the spec-version mismatch exit code.

**Resolved after baseline:** `fixtures/http_server.py` and
`tests/test_source_cli.py` now cover streamable HTTP, direct and per-renderer
protocol capture, connection exit `2`, and both forms of version mismatch exit
`3`.

The implementation extends the section 6 model with framework metadata, JTBD
models, required/authz dimensions, and job findings
(`src/mcp_mirror/models.py:17-33,51,69-111,131`). That is design-document
drift, not missing code.

## Milestone 2: differ and categorizer

**Overall: Done, with intentional semantics beyond section 9.**

- **Done:** source and rendered `ToolRep` values are compared in
  `src/mcp_mirror/diff.py:66-129`.
- **Done:** name and description rules are implemented in
  `src/mcp_mirror/diff.py:149-244`.
- **Done:** recursive schema comparison covers types, properties, required
  fields, constraints, combinators, and precise paths in
  `src/mcp_mirror/diff.py:315-486`.
- **Done:** unit cases for loss, addition, transformation, optional wrappers,
  and `$ref` resolution are in `tests/test_diff.py:49-247`.
- **Partial:** the code handles both `oneOf` and `anyOf`, but the collapse unit
  test directly covers only `anyOf` (`tests/test_diff.py:135-142`).
- **Missing:** empty rendered names are handled by
  `src/mcp_mirror/diff.py:149-162` but have no dedicated test.

Section 9 says an absent annotation is lossy. The implementation intentionally
uses three outcomes in `src/mcp_mirror/diff.py:266-312`: surfaced, retained in
framework metadata but hidden from the model, and destroyed. Tests establish
those outcomes in `tests/test_diff.py:207-229`. The design should be updated
rather than flattening this behavior.

## Milestone 3: tricky fixture

**Overall: Done.**

`fixtures/tricky_server.py` contains:

- a description longer than 1,024 characters and Unicode
  (`fixtures/tricky_server.py:19-37`);
- enum, email, and date-time constraints (`fixtures/tricky_server.py:48-62`);
- nested objects and arrays of objects (`fixtures/tricky_server.py:82-109`);
- `anyOf` and `oneOf` (`fixtures/tricky_server.py:123-143`);
- required and optional properties with descriptions
  (`fixtures/tricky_server.py:46-71,159-165`); and
- destructive and other MCP annotations plus risk/scope language
  (`fixtures/tricky_server.py:149-173`).

The stdio fixture is exercised by `tests/test_renderers.py:20-66`.

## Milestones 4-6: original framework renderers

**Baseline: renderers Done, integration assertions Partial. Current: Done.**

### LangChain

- **Done:** drives `MultiServerMCPClient.get_tools()` and
  `convert_to_openai_tool()` in
  `src/mcp_mirror/renderers/langchain_renderer.py:57-73`.
- **Done:** records the installed adapter and core versions in
  `src/mcp_mirror/renderers/langchain_renderer.py:45-49`.
- **Done:** retains MCP annotations from framework metadata for J5 in
  `src/mcp_mirror/renderers/langchain_renderer.py:68-72`.
- **Inferred:** the comment says `convert_to_openai_tool()` is exactly the
  `bind_tools` payload. No test invokes `bind_tools` or captures a provider
  request.

### Pydantic AI

- **Done:** drives the published Pydantic AI MCP server/toolset path in
  `src/mcp_mirror/renderers/pydantic_ai_renderer.py:47-87`.
- **Done:** maps `ToolDefinition` and retained annotations in
  `src/mcp_mirror/renderers/pydantic_ai_renderer.py:89-107`.
- **Partial:** the current `MCPServerStdio` entry point passes but is deprecated
  and scheduled for removal.
- **Inferred:** no test constructs an Agent and captures its provider request.

### CrewAI

- **Done:** drives the real `MCPServerAdapter` in
  `src/mcp_mirror/renderers/crewai_renderer.py:37-60`.
- **Done:** records installed `crewai-tools` and `crewai` versions in
  `src/mcp_mirror/renderers/crewai_renderer.py:33-35`.
- **Inferred:** model-facing parameters are extracted from the adapted tool's
  `args_schema` in `src/mcp_mirror/renderers/crewai_renderer.py:62-87`.
  No CrewAI-to-provider serializer is invoked.

At baseline, the common integration test parametrized every installed renderer and checked
the fixture plus `destructiveHint` behavior in
`tests/test_renderers.py:39-66`. It does not yet assert the expected
per-dimension fixture result for every framework, as section 14 describes.

The follow-up declares each boundary without a provider-request claim, captures
each adapter's independently negotiated MCP version, and adds per-renderer
goldens across all fixture dimensions. Pydantic AI now captures
`MCPToolset.get_tools` `ToolDefinition` objects through the supported API.

## Additional shipped renderers

At baseline, `DESIGN.md` was behind the code. OpenAI Agents SDK was listed as future work in
section 19, and Mastra was absent from sections 8, 17, and 19. Both were already
registered in `src/mcp_mirror/renderers/__init__.py:35-41` and passed the common
integration test.

### OpenAI Agents SDK

- **Done:** drives `MCPUtil.to_function_tool()` in
  `src/mcp_mirror/renderers/openai_agents_renderer.py:51-61`.
- **Done:** records the installed `openai-agents` version and preserves the MCP
  title metadata in
  `src/mcp_mirror/renderers/openai_agents_renderer.py:39-41,76-89`.
- **Inferred:** the SDK `FunctionTool` is inspected; no provider request is
  captured.

### Mastra

- **Done:** the Node worker drives the real `@mastra/mcp` `MCPClient` and
  `listTools()` in
  `src/mcp_mirror/renderers/mastra_node/_mastra_worker.mjs:9-63`.
- **Done:** the Python wrapper isolates the worker and records installed
  package and Node versions in
  `src/mcp_mirror/renderers/mastra_renderer.py:32-49,51-88`.
- **Partial:** `extractJsonSchema()` is custom glue around the adapted schema
  wrapper (`_mastra_worker.mjs:11-26`).
- **Baseline Inferred, resolved:** the old comment claimed this schema was what
  the AI SDK serializes, but the worker did not call a provider serializer. The
  renderer now declares `MCPClient.listTools` as a framework-tool boundary and
  explicitly records that no provider request was captured.

## Milestone 7: scorecard and reporters

**Overall: Done.**

- **Done:** J1-J5 and their dimension mapping are in
  `src/mcp_mirror/scorecard.py:29-72`.
- **Done:** scorecards are derived from reports in
  `src/mcp_mirror/scorecard.py:106-149`.
- **Done:** JSON, terminal, and markdown share that scorecard through
  `src/mcp_mirror/report.py:46-54,78-224`.
- **Done:** terminal output gives J5 findings a dedicated callout in
  `src/mcp_mirror/report.py:106-113`.
- **Baseline Partial, resolved:** markdown lacked the terminal reporter's
  dedicated J5 block; both now include J5 findings.
- **Baseline Partial, resolved:** `--job` could filter J5 out; J5 is now added
  back unconditionally.

At baseline the scorecard computed an internal cross-job `worst` value. It has
been removed under the census-not-leaderboard rule; only per-job cells remain.

## Milestone 8: regression baselines

**Overall: Done.**

- **Done:** `--out`, `--baseline`, and `--fail-on-drift` are wired in
  `src/mcp_mirror/cli.py:123-130,211-227`.
- **Done:** new and worsening differences cause drift in
  `src/mcp_mirror/report.py:228-261`.
- **Done:** different MCP spec versions cannot be compared
  (`src/mcp_mirror/report.py:236-241`).
- **Done:** unit coverage is in `tests/test_diff.py:292-320`.
- **Partial:** there is no dedicated test that writes the complete JSON output,
  reloads it through the CLI, and preserves its derived scorecard. The runtime
  command recorded above proved the current path.

## Milestone 9: README and launch framing

**Baseline: Partial. Current: Done, with launch framing explicitly unresolved.**

- **Done:** README presents the compatibility site and scanner as separate
  surfaces (`README.md:10-19`).
- **Done:** the four factual result states and census-not-leaderboard policy
  are explicit (`README.md:21-39`).
- **Done:** authorization and J5 are first-class
  (`README.md:41-53,97-113`).
- **Baseline Missing, intentionally not copied:** the old section 17 launch
  writeup and dated 2026-07-28 hook existed only in DESIGN.

The dated hook may be obsolete. Moving it into public documentation is a
product decision, not a mechanical documentation fix.

## Definition of done

**Baseline: met at runtime with evidence-quality gaps. Current: met.**

- The exact LangChain/Pydantic AI/CrewAI fixture scan prints a
  spec-version-tagged J1-J5 scorecard.
- Every emitted `Difference` has a category because
  `Difference.category` is required (`src/mcp_mirror/models.py:56-66`).
- JSON output reloads as a same-spec baseline and reports no drift.
- The full installed-renderer suite passes.

The current definition of done declares the exact boundary for every renderer
and says that no v0.1 renderer captures a final provider request. Independent
adapter protocol evidence is required before a diff is computed.

## Design decisions

- **D1, real adapters: Done.** All five implementations call published
  framework MCP adapters or clients. Every renderer declares its exact capture
  object and provider-request status.
- **D2, protocol-agnostic core: Done.** The differ and scorecard import
  `ToolRep` rather than MCP. MCP is confined to the source and adapter edges
  (`src/mcp_mirror/diff.py:15-16`,
  `src/mcp_mirror/scorecard.py:10-12`,
  `src/mcp_mirror/source.py:66-89`).
- **D3, spec-version tagging: Done.** Direct-source and independent renderer
  negotiation evidence, scan refusal, output, HTTP coverage, and baseline gates
  are implemented.
- **D4, J5 first-class: Done.** Annotation fate, risk-language loss, J5
  aggregation, tests, terminal/markdown findings, and the non-filterable J5
  column are present.

## Contribution readiness

The core is reusable after a renderer is registered. It automatically provides
process isolation, `ToolRep` diffing, J1-J5, reporters, baselines, and the common
fixture test. Adding a framework still requires deliberate work across:

1. a real-adapter renderer;
2. the internal registry and optional dependency or Node worker;
3. exact installed-version reporting;
4. framework-specific boundary and annotation tests; and
5. framework metadata plus measured capability cells.

The complete path is documented in `ADDING_A_FRAMEWORK.md`. CI now installs all
declared Python adapters and the locked Mastra worker, runs tests, validates
data, builds the site, and builds the wheel. A PR template requests the adapter
boundary, version, annotation, transport, and unrun-test evidence.

There is no external entry-point plug-in system. **Inferred:** allowing
third-party packages to publish data without an in-repository registry and
review would weaken the census trust model. That change needs an owner decision.

## Recommended next work

The audited v0.1 blockers are closed. Subsequent work is additive:

1. Measure and publish a separate MCP 2026-07-28 dataset; do not merge it into
   the 2025-11-25 cells.
2. Add Vercel AI SDK through the documented Node-renderer contribution path.
3. Capture serialized provider requests only where a deterministic local fake
   transport provides a stable interception seam.
4. Track the upstream CrewAI deprecation warning and upgrade when its released
   packages remove it.
5. Decide the replacement launch narrative with the owner and marketing; the
   expired transition hook is not an implementation requirement.
