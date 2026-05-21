# 0007 — 1Password `op run` as the canonical credential path

**Date:** 2026-05-21
**Status:** Done.

## Context

Question came up: how do other MCP projects handle credentials? Surveyed:

- 1Password's own [guide for MCP servers](https://1password.com/blog/securing-mcp-servers-with-1password-stop-credential-exposure-in-your-agent)
- arcade-mcp (open source, MIT)
- MCP Inspector
- Various MCP/agent observability tools
- William Callahan's [secure-environment-variables guide](https://williamcallahan.com/blog/secure-environment-variables-1password-doppler-llms-mcps-ai-tools)

Result: the community-standard pattern is `op run --env-file=.env`, where `.env` contains *references* like `op://<vault>/<item>/<field>` rather than the secrets themselves.

## Why this is better than a raw .env

- The `.env` file becomes safe to commit (it doesn't contain secrets).
- Secrets exist only in the subprocess's memory during the run.
- Multiple developers can use the same `.env` — each resolves against their own 1Password account.
- CI can use the 1Password GitHub Action with the same `.env` references.

## What we added

- `.env.example` at the repo root with op:// references for `OPENAI_API_KEY` and `ARCADE_API_KEY`, plus header comments explaining the workflow.
- README "Credentials" section documenting both the recommended `op run` flow and a raw-env fallback.
- The existing built-in `.env` loader (from build-log 0006) remains for users who can't or don't want to use 1Password. It's a fallback path, not the recommendation.

## What this unblocks

Once Thierry has `.env` populated (either with op:// refs or raw values), the next two tasks land cleanly:

- 0008-arcade-source.md — point `--server` at Arcade's MCP server using the resolved `ARCADE_API_KEY`.
- 0009-openai-validation.md — make a real OpenAI call from each framework, intercept the function-schema payload, diff against the introspected view.

Both code paths are scoped; only the credentials gate is blocking.
