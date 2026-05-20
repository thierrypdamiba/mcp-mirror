# 0001 — Project bootstrap

**Date:** 2026-05-20
**Status:** Done

## Goal

Set up a Python project that can grow into a cross-framework MCP diff tool. The artifact backs Thierry's MCP Dev Summit talk *"Your Tool Is in Another Castle: A Cross-Framework Field Guide to MCP."*

## Decisions

- **Language: Python**. Every major agent framework's MCP integration is Python first. Going Python-native means we use each framework's real code path, not a re-implementation.
- **Python 3.13** minimum at the venv level, 3.10+ supported. Newer agent framework versions are dropping 3.9.
- **Layout: src/**. Standard `src/mcp_mirror/` layout so importing works the same whether installed or run from the repo.
- **No production deps in core**. The diff engine, types, scorecard, fixtures, and CLI use only the standard library plus `mcp` (the official SDK). Framework adapters are loaded lazily so the tool runs even when only a subset of frameworks is installed.
- **Tests with pytest + pytest-asyncio**. Already established as the agent-framework community's default.

## Why these decisions matter

- Lazy framework imports keep the install footprint small for users who only care about, say, LangChain. They don't get forced to install CrewAI's dependency tree.
- Standard-library-only core means the diff engine and types are reliable across Python versions and easy to vendor if needed.
- `src/` layout prevents the classic "tests pass locally but fail when installed" bug.

## File scaffold

- `pyproject.toml` — declares package, scripts, optional deps.
- `.gitignore` — Python defaults plus `.venv/`, `.env`.
- `src/mcp_mirror/__init__.py` — re-exports the public surface.
- `tests/__init__.py` — empty, so pytest finds it.

## Next

`0002-simulators-out-real-captures-in.md` — the first major architectural shift.
