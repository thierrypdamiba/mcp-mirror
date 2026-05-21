# 0009 — Live Arcade gateway, real cross-framework results

**Date:** 2026-05-21
**Status:** Done. The talk's anchor data exists.

## What this captures

End-to-end live run against a dedicated Arcade gateway, with real OAuth 2.1 + PKCE + Dynamic Client Registration. All five framework adapters loading 100 real production tools across GitHub, Gmail, Linear, Notion, Slack. Five real frameworks (LangChain, LlamaIndex, CrewAI, Pydantic AI, AG2) introspected at the layer they hand to the LLM. Result: a 500-row diff dataset (100 tools × 5 frameworks).

Sample runs snapshotted in `docs/sample-runs/arcade-mcp-mirror-gateway.{json,txt}` so the talk has reproducible reference data.

## The flow that actually works

1. **Gateway creation** — `arcade connect windsurf --server github --server gmail --server linear --server slack --server notiontoolkit --slug mcp-mirror --config /tmp/mcp-mirror.json`. Created `https://api.arcade.dev/mcp/mcp-mirror` with 122 tools. The `windsurf` client choice is incidental — `--config` redirects the side-effect client config to a throwaway path so no real client is touched.
2. **Discovery** — mcp-mirror probes the gateway, gets `401 WWW-Authenticate: Bearer resource_metadata="..."`, fetches the resource metadata, then the authorization server metadata. Endpoints are cached at `~/.cache/mcp-mirror/<hash>/discovery.json`.
3. **DCR** — POST to `https://cloud.arcade.dev/oauth2/register` with `redirect_uris=["http://127.0.0.1:8765/callback"]`, `token_endpoint_auth_method=none`. Arcade returns a fresh client_id. Cached at `client.json`.
4. **PKCE + browser** — authorize URL constructed with our client_id, S256 code_challenge, gateway as the `resource` indicator. Loopback at 127.0.0.1:8765 catches the code. Token exchange POSTs to `/oauth2/token` with the verifier. Token cached at `token.json`.
5. **HTTP MCP** — each framework's adapter connects to the gateway via streamable-HTTP with `Authorization: Bearer <token>`. mcp-mirror introspects each adapter's tool views and diffs against the server announcement.

## Findings (top 5 most-mangled tools)

| Tool | Pydantic AI | LangChain | AG2 | LlamaIndex | CrewAI |
|---|---|---|---|---|---|
| Linear_CreateIssue | 1 | 2 | 5 | 59 | **62** |
| Gmail_SearchThreads | 1 | 2 | 4 | 45 | **48** |
| Github_ListProjectItems | 1 | 2 | 5 | 44 | **47** |
| Linear_ListIssues | 1 | 2 | 4 | 44 | **47** |
| Github_ListRepositoryActivities | 1 | 2 | 5 | 40 | **43** |

Numbers are total field-level deltas (lossy + additive + transformative) against the server's MCP announcement. **CrewAI does 62× the schema work Pydantic AI does on Linear_CreateIssue.**

## Consistent per-framework patterns across all 100 tools

- **Pydantic AI**: `+1` everywhere. Returns the raw `mcp.types.Tool`; only adds an internal class-name marker. Most faithful.
- **LangChain**: `-1 +1` everywhere. Drops the protocol-level `_meta` field, adds a `__lc_tool_class` marker. Predictable.
- **AG2**: `-3` to `-4` `+1`. Drops more (`outputSchema`, `_meta`, `icons`, `annotations`), adds the AG2 class marker.
- **LlamaIndex**: highly variable. Goes through Pydantic v2 schema generation, which introduces `$defs` blocks and reorganizes properties. Simple tools see `-1 ~2 +4`; complex tools see `-16 +43`.
- **CrewAI**: most invasive. Wraps in mcpadapt + CrewAI Pydantic generation, *extends descriptions* with usage-guidance text (typical 5–6× longer), restructures schemas heavily.

## Two fixes that surfaced during the live run

### Tool-name canonicalization

CrewAI renames `Github_AssignPullRequestUser` to `github_assign_pull_request_user` (CamelCase → snake_case). The CLI's strict name match silently dropped all CrewAI tools from the scorecard. Fix: `_canonical(name)` lowercases and strips separators on both sides before lookup, then the diff still preserves the original names and flags the rename as a TRANSFORMATIVE delta on the `name` field.

### MCP SDK session-termination noise

`mcp.client.streamable_http` emits `logger.warning("Session termination failed: 202")` during cleanup when the server returns 202 Accepted on session DELETE. Harmless, but it clutters the scorecard output. Suppressed via a logging filter scoped to the `mcp.client.streamable_http` logger.

## Reproducing this

```bash
# .env (1Password references resolved at runtime by `op run`)
OPENAI_API_KEY=op://Engineering - Shared/Engine Local Dev/AI/OPENAI_API_KEY
ARCADE_API_KEY=op://Private/td arcade/credential
ARCADE_USER_ID=thierry@arcade.dev
ARCADE_GATEWAY_URL=https://api.arcade.dev/mcp/mcp-mirror

# Run
op run --env-file=.env -- mcp-mirror --arcade
op run --env-file=.env -- mcp-mirror --arcade --detail > breakdown.txt
op run --env-file=.env -- mcp-mirror --arcade --json    > scorecard.json
```

## What's left

`0010-openai-validation.md` — wire-level OpenAI request inspection. The introspection captures show what each framework *intends* to send to the LLM; the wire-level capture would prove the introspected view equals the bytes that actually leave the framework. Open task; not blocking the talk.
