# 0008 — Arcade as MCP source via OAuth2

**Date:** 2026-05-21
**Status:** Implemented. Live verification pending — first run will open a browser for OAuth.

## Why OAuth, not Bearer-with-API-key

Initial attempt was to set `Authorization: Bearer $ARCADE_API_KEY` against `https://api.arcade.dev/mcp/gw_*` and call it done. Result: **401 Unauthorized**. Arcade's gateway endpoints don't accept the raw API key as a Bearer — they require an OAuth2 access token scoped to the gateway.

That's also the right answer for the talk: real Arcade users go through OAuth (browser, authorize page, token exchange). For mcp-mirror's captures to reflect what production agents actually see, we should authenticate the same way. We're not bypassing OAuth — we're embracing it.

## Implementation

`src/mcp_mirror/arcade_auth.py` — full PKCE + loopback flow:

- **PKCE**: random `code_verifier`, S256 `code_challenge` per RFC 7636.
- **Authorization URL**: `https://cloud.arcade.dev/oauth2/authorize` with `response_type=code`, `client_id`, `code_challenge`, `code_challenge_method=S256`, `redirect_uri=http://127.0.0.1:8765/api/auth/arcade/callback`, `scope=mcp`, `resource=<gateway_url>`, `state`.
- **Loopback callback**: `http.server.HTTPServer` on `127.0.0.1:8765` (falls back to OS-assigned port if 8765 is busy). Matches the callback path, validates `state`, captures `code`.
- **Token exchange**: POST to `https://cloud.arcade.dev/oauth2/token` with `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `code_verifier`, `resource`.
- **Cache**: token JSON saved to `~/.cache/mcp-mirror/arcade-<hash>.json`, keyed by gateway URL so multiple gateways coexist. Mode 0600.
- **Refresh**: if cached token is expired and a `refresh_token` was issued, exchange it without bothering the user.

## Client ID choice

Currently reuses `790f9539-f397-4ee7-b94e-3d3b1e812dc6` — the OAuth client from the productivity-app/switchboard project. This works on a developer machine because:

- The token comes back to our own loopback server (we control 127.0.0.1).
- The token is scoped to whoever clicks "authorize" — i.e. Thierry.

For a public release of mcp-mirror this should move to a dedicated OAuth client registered with Arcade. Tracked as a future task.

## ServerSpec refactor

Captures previously took `StdioServerParameters` directly. New `mcp_mirror.spec.ServerSpec` is a tagged union supporting either kind:

```python
ServerSpec.stdio("python", ["-m", "mcp_mirror.server"])
ServerSpec.http("https://api.arcade.dev/mcp/...", headers={"Authorization": "Bearer ..."})
```

Each capture function now uses an `_session(spec)` context manager that picks `stdio_client` or `streamablehttp_client` based on `spec.kind`. Framework-specific HTTP paths:

- **LangChain, AG2** — session-based, no change to capture logic.
- **LlamaIndex** — `BasicMCPClient(url, headers=...)` instead of `BasicMCPClient(command, args=...)`.
- **Pydantic AI** — `MCPServerStreamableHTTP(url=..., headers=...)` instead of `MCPServerStdio`.
- **CrewAI** — `MCPServerAdapter` accepts either `StdioServerParameters` or a dict `{"url": ..., "transport": "streamable-http", "headers": {...}}`.

## CLI

Three mutually-exclusive source modes:

```bash
mcp-mirror                               # default: bundled reference server (stdio)
mcp-mirror --server CMD ARGS...          # any stdio MCP server
mcp-mirror --http URL                    # any streamable-HTTP MCP server, unauthed
mcp-mirror --arcade                      # Arcade gateway from ARCADE_GATEWAY_URL, OAuth-authed
mcp-mirror --arcade --re-auth            # force browser flow even with a cached token
```

## First-run UX

`mcp-mirror --arcade` on a clean machine prints:

```
mcp-mirror: opening browser to authenticate with Arcade.
  If a browser does not open, visit this URL manually:
  https://cloud.arcade.dev/oauth2/authorize?...
```

…then opens the default browser to the Arcade authorize page. User clicks authorize. Loopback receives the code, exchanges for a token, caches it. The capture run proceeds against the Arcade gateway. On subsequent runs the cache hits and the flow is invisible.

## Test status

All 18 existing tests still pass after the refactor. A live Arcade integration test is not in CI by default (it would require interactive auth); local manual verification is `op run --env-file=.env -- mcp-mirror --arcade`.

## Next

`0009-openai-validation.md` — the second remaining task. Now that adapter captures work across both transports, we can layer an OpenAI request interceptor that captures the *actual* function-schema payload each framework sends to the model and diff it against the introspected view.
