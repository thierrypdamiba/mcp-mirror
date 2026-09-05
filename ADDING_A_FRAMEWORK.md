# Adding an agent framework

`mcp-mirror` is designed so a framework contribution plugs into the existing
source loader, differ, Jobs-To-Be-Done scorecard, reporters, and regression
harness. The contributor still has to prove one framework-specific fact: which
tool definition the framework's real adapter presents at the model boundary.

Once that renderer is registered, the shared engine provides the rest:

- stdio and streamable-HTTP server configuration;
- process isolation from the other framework packages;
- normalization into `ToolRep`;
- field-level differences and J1-J5 aggregation;
- terminal, JSON, and markdown reports;
- baseline comparison; and
- the common fixture integration test.

This is a multi-file contribution, not an external plug-in API. The checklist
below names every required surface so adding a framework does not depend on
repository folklore.

## 1. Establish and declare the capture boundary

Find the published framework or adapter API that performs the MCP-to-tool
conversion. Drive that API directly. Do not copy its implementation or write an
equivalent converter inside `mcp-mirror`. Name the exact API and object inspected;
do not silently describe an intermediate framework object as a provider request.

The renderer must extract the tool definition produced at that path:

```text
name
description
parameters  (JSON Schema)
```

Use the strongest deterministic boundary the framework exposes without making a
model call. Classify it as:

- `framework_tool_definition` for an adapted framework object;
- `provider_format` for a provider-shaped tool dictionary that has not been
  serialized into a request; or
- `provider_request` only when the test actually intercepts the serialized
  request body.

`provider_request_captured` may be true only for the last case. If the adapter
does not expose its independently negotiated MCP protocol version, record
`None` and explain that limitation. Never copy the direct source connection's
version into a framework run as an assumption.

Also inspect what happens to MCP annotations:

- put annotations in `ToolRep.annotations` only when the declared capture
  object contains them;
- put annotations in
  `framework_metadata={"annotations": ...}` when the framework retains them
  outside the captured object; and
- leave both empty when the adapted object no longer carries them.

That distinction drives J5. Treating retained metadata as dropped, or treating
model-blind metadata as surfaced, produces a false authorization result.

## 2. Choose the implementation route

### Python framework

Add `src/mcp_mirror/renderers/<id>_renderer.py`. Follow an existing renderer and
provide this module interface:

```python
ID = "framework_id"

def available() -> bool:
    ...

def get_renderer():
    return FrameworkRenderer()

class FrameworkRenderer:
    id = ID

    def versions(self) -> dict:
        return {"framework": "...", "adapter": "..."}

    def evidence(self) -> RendererEvidence:
        return RendererEvidence(
            capture_api="package.module.Adapter.method",
            capture_object="package.TypeName",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=None,
            protocol_version_evidence="the adapter does not expose it",
            limitation="no serialized provider request was captured",
        )

    def render(self, server: ServerHandle) -> list[ToolRep]:
        ...
```

Import the heavy framework package inside `render()`, not at module import
time. `mcp-mirror frameworks` must continue to work when the optional
dependency is absent. Wrap adapter failures in `RenderError`.

Use `normalize_function_tool()` after the real adapter has produced its tool
shape. Do not import MCP in the differ, scorecard, or reporter.

### TypeScript or JavaScript framework

Follow the Mastra bridge:

```text
src/mcp_mirror/renderers/<id>_renderer.py
src/mcp_mirror/renderers/<id>_node/package.json
src/mcp_mirror/renderers/<id>_node/package-lock.json
src/mcp_mirror/renderers/<id>_node/_worker.mjs
```

The Node worker drives the published adapter and emits JSON. The Python wrapper
handles availability, subprocess isolation, timeout and error translation,
version reporting, evidence declaration, and conversion to `ToolRep`.

Commit the worker lockfile. Do not commit `node_modules/`.

For example, a Vercel AI SDK contribution would use this route. The PR must
identify and call the current AI SDK MCP/tool conversion API; the framework
name alone is not evidence that a hand-built OpenAI-style schema matches its
tool object or any provider-bound payload.

## 3. Register installation and discovery

1. Add the renderer id and module to `_RENDERER_MODULES` in
   `src/mcp_mirror/renderers/__init__.py`.
2. Add only useful spelling variants to `_ALIASES`.
3. For Python, add a same-named optional dependency in `pyproject.toml` and add
   it to the `all` extra.
4. For a Node worker, commit both `package.json` and `package-lock.json` and
   document its `npm ci --prefix ...` command.
5. Make `versions()` report the installed framework and adapter distributions,
   not versions copied from documentation.

After registration, `available_renderers()` automatically includes the
framework when its dependency is present, the CLI runs it in an isolated
process, and the shared integration test parametrizes it.

## 4. Prove the renderer against the fixture

Install the complete locked development environment:

```bash
uv sync --locked --extra dev --extra all
npm ci
npm ci --prefix src/mcp_mirror/renderers/mastra_node
```

Add the new framework's equivalent npm installation when applicable, then run:

```bash
uv run pytest tests -q
uv run mcp-mirror frameworks
uv run mcp-mirror scan "python fixtures/tricky_server.py" \
  --frameworks framework_id
```

The shared test verifies that the renderer:

- connects through the real adapter;
- returns tools from the fixture; and
- reports `destructiveHint` as present at the boundary, retained elsewhere, or
  dropped.

Add framework-specific assertions for transformations that the generic test
cannot establish. At minimum cover the framework's expected handling of:

- names, tool descriptions, and per-property descriptions;
- required parameters, enums, formats, defaults, numeric constraints, and
  whether optional wrappers newly accept `null`;
- nested objects, arrays of objects, `additionalProperties`, and every
  `oneOf` / `anyOf` branch;
- injected wrapper text or fields; and
- `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint`.

An integration test may not replace the adapter with a mock converter. Missing
optional dependencies may skip local tests, but CI installs all declared
Python adapters and the checked-in Mastra worker before running the suite. CI
also fails if any registered renderer is unavailable or reports an unknown
framework or adapter version, preventing a broken registration from silently
skipping its own tests.

## 5. Add the framework to the compatibility data

The scanner and site are separate public surfaces. A renderer makes scans
possible; it does not silently publish support claims.

1. Add the framework to `data/frameworks.json` with its package, registry,
   language, renderer path, exact tested version, release history, and current
   era.
2. Add an entry for the framework to every applicable
   `data/capabilities/*.json` file.
3. Use `u` for an unmeasured release. Do not omit known releases to make the
   row look complete.
4. Every `a` or `n` cell must cite a numbered note describing the observable
   mechanism.
5. Keep framework ordering alphabetical within language group. There is no
   aggregate framework score.

Validate and regenerate the published aggregate:

```bash
python3 data/validator/validate.py data
python3 scripts/build_data.py
npm run build
```

## 6. Pull request evidence

Include the following in the PR description:

- framework and adapter package names;
- exact versions tested;
- the real adapter/conversion API called by the renderer;
- the exact extracted object and capture-stage classification;
- whether a serialized provider request was actually captured;
- whether the adapter-negotiated MCP version is observed or unknown;
- the fate of MCP annotations and the object fields that prove it;
- fixture command and test output;
- data files changed; and
- any transport not exercised.

Do not describe a framework as better or worse. Describe what the adapter
preserved, retained elsewhere, changed, added, or dropped.

## Current limits

The registry is internal and explicit; third-party packages cannot register a
renderer through Python entry points. Non-Python adapters need a small process
bridge. Compatibility cells are reviewed and committed rather than generated
directly from an arbitrary scan.

Those limits are intentional for the current census: every published framework
and result remains auditable in this repository. A future external plug-in API
would need an owner decision about trust, packaging, and whether third-party
renderers can produce publishable support data.
