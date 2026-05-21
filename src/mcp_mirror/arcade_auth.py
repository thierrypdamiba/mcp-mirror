"""OAuth2 (PKCE + loopback) authentication for the Arcade MCP gateway.

Real users authenticate to Arcade Cloud via OAuth2 in a browser. mcp-mirror does
the same so its captures reflect the production code path — not a shortcut.

Flow:
  1. Generate PKCE code_verifier + code_challenge.
  2. Open a browser to https://cloud.arcade.dev/oauth2/authorize with the
     `mcp` scope and the gateway URL as the `resource`.
  3. Start a one-shot HTTP server on 127.0.0.1 listening for the redirect.
  4. Exchange the returned code at https://cloud.arcade.dev/oauth2/token.
  5. Cache the access token at ~/.cache/mcp-mirror/<gateway-hash>.json so
     subsequent runs skip the browser step.

The cached token is keyed by gateway URL so multiple gateways can coexist.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

# These match the OAuth client used by the productivity-app/switchboard project.
# For a public release of mcp-mirror, a dedicated client should be registered
# with Arcade. For now we reuse this client on a developer machine, which is
# safe because the token comes back to our own loopback server.
ARCADE_OAUTH_AUTHORIZE = "https://cloud.arcade.dev/oauth2/authorize"
ARCADE_OAUTH_TOKEN = "https://cloud.arcade.dev/oauth2/token"
DEFAULT_CLIENT_ID = "790f9539-f397-4ee7-b94e-3d3b1e812dc6"
DEFAULT_REDIRECT_PATH = "/api/auth/arcade/callback"
DEFAULT_REDIRECT_PORT = 8765
DEFAULT_SCOPE = "mcp"


@dataclass
class CachedToken:
    access_token: str
    token_type: str
    expires_at: float
    refresh_token: Optional[str]
    gateway_url: str

    @property
    def is_expired(self) -> bool:
        # Refresh 60 seconds before the official expiry to avoid edge races.
        return time.time() >= self.expires_at - 60


def _cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    d = base / "mcp-mirror"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(gateway_url: str) -> Path:
    h = hashlib.sha256(gateway_url.encode()).hexdigest()[:16]
    return _cache_dir() / f"arcade-{h}.json"


def _load_cached(gateway_url: str) -> Optional[CachedToken]:
    p = _cache_path(gateway_url)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
        return CachedToken(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=data["expires_at"],
            refresh_token=data.get("refresh_token"),
            gateway_url=data["gateway_url"],
        )
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _save_cached(token: CachedToken) -> None:
    p = _cache_path(token.gateway_url)
    p.write_text(
        json.dumps(
            {
                "access_token": token.access_token,
                "token_type": token.token_type,
                "expires_at": token.expires_at,
                "refresh_token": token.refresh_token,
                "gateway_url": token.gateway_url,
            }
        )
    )
    os.chmod(p, 0o600)


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 with S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _free_port(preferred: int) -> int:
    """Return the preferred port if available, otherwise an OS-assigned one."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", preferred))
        return preferred
    except OSError:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _run_loopback(port: int, redirect_path: str, state: str) -> str:
    """Block until the OAuth provider redirects to our loopback. Return `code`."""
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args, **_kwargs):  # noqa: ARG002 — silence stderr
            return

        def do_GET(self):  # noqa: N802 — http.server convention
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != redirect_path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            received_state = (qs.get("state") or [""])[0]
            if received_state != state:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"state mismatch")
                return
            code = (qs.get("code") or [""])[0]
            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"missing code")
                return
            received["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><meta charset=utf-8><title>mcp-mirror</title>"
                b"<body style='font-family:system-ui;max-width:520px;margin:80px auto'>"
                b"<h1>Authorized.</h1>"
                b"<p>You can close this tab and return to mcp-mirror.</p>"
            )

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Wait up to 5 minutes for the user to authorize.
        deadline = time.time() + 300
        while time.time() < deadline:
            if "code" in received:
                return received["code"]
            time.sleep(0.1)
        raise RuntimeError("Timed out waiting for OAuth callback (5 min).")
    finally:
        server.shutdown()


def authenticate(
    gateway_url: str,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    redirect_path: str = DEFAULT_REDIRECT_PATH,
    redirect_port: int = DEFAULT_REDIRECT_PORT,
    scope: str = DEFAULT_SCOPE,
    open_browser: bool = True,
) -> CachedToken:
    """Run the full PKCE + loopback flow and return a fresh CachedToken.

    Caches the result for future runs. Side effect: opens a browser tab (unless
    open_browser=False, in which case the URL is printed).
    """
    port = _free_port(redirect_port)
    redirect_uri = f"http://127.0.0.1:{port}{redirect_path}"
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{ARCADE_OAUTH_AUTHORIZE}?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "redirect_uri": redirect_uri,
                "scope": scope,
                "resource": gateway_url,
                "state": state,
            }
        )
    )

    print(
        f"mcp-mirror: opening browser to authenticate with Arcade.\n"
        f"  If a browser does not open, visit this URL manually:\n  {auth_url}",
    )
    if open_browser:
        webbrowser.open(auth_url)

    code = _run_loopback(port, redirect_path, state)

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            ARCADE_OAUTH_TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": gateway_url,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()

    expires_in = float(payload.get("expires_in", 3600))
    token = CachedToken(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "Bearer"),
        expires_at=time.time() + expires_in,
        refresh_token=payload.get("refresh_token"),
        gateway_url=gateway_url,
    )
    _save_cached(token)
    return token


def _refresh(token: CachedToken, client_id: str) -> Optional[CachedToken]:
    if not token.refresh_token:
        return None
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            ARCADE_OAUTH_TOKEN,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": client_id,
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    expires_in = float(payload.get("expires_in", 3600))
    refreshed = CachedToken(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "Bearer"),
        expires_at=time.time() + expires_in,
        refresh_token=payload.get("refresh_token", token.refresh_token),
        gateway_url=token.gateway_url,
    )
    _save_cached(refreshed)
    return refreshed


def get_access_token(
    gateway_url: str,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    force_reauth: bool = False,
) -> str:
    """Get a valid access token for `gateway_url`. Re-auths via browser if needed."""
    if not force_reauth:
        cached = _load_cached(gateway_url)
        if cached and not cached.is_expired:
            return cached.access_token
        if cached and cached.is_expired:
            refreshed = _refresh(cached, client_id)
            if refreshed:
                return refreshed.access_token
    token = authenticate(gateway_url, client_id=client_id)
    return token.access_token


def clear_cached(gateway_url: str) -> bool:
    p = _cache_path(gateway_url)
    if p.is_file():
        p.unlink()
        return True
    return False
