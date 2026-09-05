## What changed

Describe the scanner, compatibility-data, or site change.

## Framework evidence

Complete this section for a new or changed renderer. Otherwise write
`Not applicable`.

- Framework package and version:
- Adapter package and version:
- Real MCP adapter/conversion API called:
- Capture object and stage (`framework_tool_definition`, `provider_format`, or
  `provider_request`):
- Serialized provider request captured (`yes` requires interception evidence):
- Adapter-negotiated MCP version observed, or why it is unknown:
- MCP annotations are present at the boundary, retained elsewhere, or dropped:
- Evidence for that annotation fate:
- Transports exercised:

## Compatibility data

- Capability files changed:
- Every retained (`a`) or dropped (`n`) cell cites a mechanism note:
- Known but unmeasured releases remain visible as `u`:

## Verification

List commands actually run and their outcomes. Do not check a command that was
not run.

- [ ] `uv sync --locked --extra dev --extra all`
- [ ] `npm ci --prefix src/mcp_mirror/renderers/mastra_node`
- [ ] `uv run pytest tests -q`
- [ ] `python3 data/validator/validate.py data`
- [ ] `npm run build`

## Deliberately not changed

Name adjacent behavior or cleanup intentionally left out of this PR.
