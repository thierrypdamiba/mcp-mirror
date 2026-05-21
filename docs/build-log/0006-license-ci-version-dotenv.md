# 0006 — LICENSE, CI, --version, .env loader

**Date:** 2026-05-21
**Status:** Done.

## Polish pass for "CTO uses it tomorrow."

### LICENSE

Added MIT LICENSE file at root. `pyproject.toml` already declared `MIT`; this puts the actual file on disk for GitHub's license detection and for downstream packagers.

### CI

`.github/workflows/test.yml` runs `pytest tests/` on push and PR against Python 3.11, 3.12, 3.13. Installs all five framework integrations plus pytest plumbing. Keep this workflow's dep list in sync with the README install instructions when adding frameworks.

### --version

`mcp-mirror --version` now prints `mcp-mirror 0.1.0`, sourced from `mcp_mirror.__version__` (single source of truth — `pyproject.toml`'s version stays in lockstep manually for now; later we can bump via `bumpver` or a release-please workflow).

### .env loader

The CLI now does a zero-dep best-effort load of `./.env` before running. Lets users drop:

```
OPENAI_API_KEY=sk-...
ARCADE_API_KEY=...
```

into a local `.env` (already gitignored) without needing `python-dotenv` as a runtime dep.

The loader:
- Reads `./.env` from the working directory.
- Skips comments and blanks.
- Won't overwrite values already in `os.environ` (preserves explicit `export` values).
- Strips surrounding `'` or `"` from values.

This unblocks the Arcade-source and OpenAI-validation paths without forcing the user to remember the `op read | export` shell incantation every session.

### Test status

16/16 pass.

### Next

When credentials land, `0007-arcade-source.md` and `0008-openai-validation.md` document wiring those code paths. Both are scoped already; they just need the keys.
