# 0004 — CLI and scorecard

**Date:** 2026-05-20
**Status:** Done.

## Goal

A CLI that takes "no arguments" and produces the talk's anchor visual: the cross-framework scorecard. With flags for filtering, JSON output, and pointing at custom MCP servers.

## CLI surface

```
mcp-mirror                          # default: bundled server, all installed frameworks
mcp-mirror --server CMD ARGS...     # point at any MCP server (Arcade, your own, etc.)
mcp-mirror --framework pydantic-ai  # filter to specific framework(s)
mcp-mirror --tool send_message      # filter to specific tool(s)
mcp-mirror --detail                 # per-field breakdown after the summary
mcp-mirror --json                   # machine-readable
```

## Scorecard format

The summary grid is one row per tool, one column per framework. Each cell:

- `=` if the framework is faithful (no field-level deltas)
- `+N` for N added fields
- `-N` for N dropped fields
- `~N` for N transformed fields
- combinations are space-separated (e.g., `-6 +1`)

This is intentionally compact so a wide scorecard fits on a slide.

## Detail format

Per `tool @ framework` block with:
- Overall category (the "worst" delta wins: lossy > transformative > additive > faithful).
- Counts by category.
- Per-field listing with category glyph, path, and human-readable note.

The notes are written to be readable on a slide. Example:

```
- response.required
    Framework dropped `required`.
- metadata.permissions_required
    Server metadata `permissions_required` dropped by framework.
+ metadata.__lc_tool_class
    Framework added metadata `__lc_tool_class`.
```

## Resilience

If a framework's capture raises (e.g., its package isn't installed), the CLI prints a warning to stderr and skips that framework rather than aborting. This means the tool degrades gracefully on machines that only have a subset of frameworks installed.

## JSON output

Used for piping into `jq`, building dashboards, regression tests. Schema:

```json
{
  "diffs": [
    {
      "tool": "send_message",
      "framework": "langchain",
      "overall": "lossy",
      "counts": {"lossy": 6, "additive": 1},
      "fields": [
        {
          "path": "response.type",
          "category": "lossy",
          "note": "Framework dropped `type`.",
          "server_value": "object",
          "framework_value": null
        },
        ...
      ]
    }
  ]
}
```

Long string values truncate at 200 chars in JSON to keep payloads manageable; reading them with `--detail` shows full values.

## Next

`0005-tests.md` — what we test and why.
