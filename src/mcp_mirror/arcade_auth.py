"""Spec-correct OAuth 2.1 authentication for Arcade MCP gateways.

Follows the MCP 2025-06-18 authorization spec: discover the protected-resource
metadata from the WWW-Authenticate header, fetch the authorization server
metadata, dynamically register as a public OAuth client (DCR), then run a
PKCE-protected authorization code flow with the gateway URL as the
RFC 8707 resource indicator.

No hardcoded client_id, no impersonation of other apps, no shortcuts. mcp-mirror
identifies itself to Arcade as `mcp-mirror` and gets its own client record.

Tokens, registered client metadata, and discovered endpoints are all cached
under `~/.cache/mcp-mirror/<gateway-hash>/` so subsequent runs are fast and
silent.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

DEFAULT_REDIRECT_PORT = 8765
DEFAULT_REDIRECT_PATH = "/callback"
HTTP_TIMEOUT = 30.0


# ---- cache layout -----------------------------------------------------------


def _cache_dir(gateway_url: str) -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    h = hashlib.sha256(gateway_url.encode()).hexdigest()[:16]
    d = base / "mcp-mirror" / h
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(p: Path) -> dict | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, indent=2))
    os.chmod(p, 0o600)


# ---- types ------------------------------------------------------------------


@dataclass
class Discovery:
    resource: str
    authorization_servers: list[str]
    scopes_supported: list[str]
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    code_challenge_methods_supported: list[str]

    @property
    def supports_pkce_s256(self) -> bool:
        return "S256" in self.code_challenge_methods_supported


@dataclass
class RegisteredClient:
    client_id: str
    redirect_uri: str
    registration_endpoint: str
    raw: dict = field(default_factory=dict)


@dataclass
class CachedToken:
    access_token: str
    token_type: str
    expires_at: float
    refresh_token: Optional[str]
    gateway_url: str

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60


# ---- discovery (RFC 9728 + RFC 8414) ----------------------------------------


def _discover_resource_metadata_url(gateway_url: str) -> str:
    """Probe the gateway, parse WWW-Authenticate, return the resource_metadata URL.

    Per RFC 9728, an unauthenticated request returns 401 with a Bearer challenge
    pointing at the protected-resource metadata document.
    """
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        response = client.post(
            gateway_url,
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-mirror", "version": "0.1.0"},
                },
            },
        )
    challenge = response.headers.get("www-authenticate", "")
    match = re.search(r'resource_metadata="([^"]+)"', challenge)
    if not match:
        # Fall back to the standard well-known location.
        parsed = urllib.parse.urlparse(gateway_url)
        return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{parsed.path}"
    return match.group(1)


def discover(gateway_url: str) -> Discovery:
    """Discover the OAuth endpoints that protect a given MCP gateway URL."""
    cache = _cache_dir(gateway_url) / "discovery.json"
    cached = _read_json(cache)
    if cached:
        return Discovery(**cached)

    resource_metadata_url = _discover_resource_metadata_url(gateway_url)
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        rm = client.get(resource_metadata_url).raise_for_status().json()
    auth_servers = rm.get("authorization_servers") or []
    if not auth_servers:
        raise RuntimeError(
            f"No authorization_servers advertised at {resource_metadata_url}"
        )
    issuer = auth_servers[0]
    # Per RFC 8414, the metadata path interleaves /.well-known/ between host and path.
    issuer_parts = urllib.parse.urlparse(issuer)
    metadata_url = (
        f"{issuer_parts.scheme}://{issuer_parts.netloc}"
        f"/.well-known/oauth-authorization-server"
        f"{issuer_parts.path}"
    )
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        asm = client.get(metadata_url).raise_for_status().json()

    discovery = Discovery(
        resource=rm.get("resource", gateway_url),
        authorization_servers=auth_servers,
        scopes_supported=rm.get("scopes_supported") or ["mcp"],
        issuer=asm["issuer"],
        authorization_endpoint=asm["authorization_endpoint"],
        token_endpoint=asm["token_endpoint"],
        registration_endpoint=asm.get("registration_endpoint"),
        code_challenge_methods_supported=asm.get("code_challenge_methods_supported", []),
    )
    _write_json(cache, discovery.__dict__)
    return discovery


# ---- dynamic client registration (RFC 7591) ---------------------------------


def register_client(
    discovery: Discovery,
    gateway_url: str,
    redirect_uri: str,
) -> RegisteredClient:
    """Register mcp-mirror as a public OAuth client. Cached per gateway."""
    cache = _cache_dir(gateway_url) / "client.json"
    cached = _read_json(cache)
    if cached and cached.get("redirect_uri") == redirect_uri:
        return RegisteredClient(
            client_id=cached["client_id"],
            redirect_uri=cached["redirect_uri"],
            registration_endpoint=cached["registration_endpoint"],
            raw=cached.get("raw", {}),
        )
    if not discovery.registration_endpoint:
        raise RuntimeError(
            "Authorization server does not advertise a registration_endpoint; "
            "Dynamic Client Registration is required for mcp-mirror."
        )
    payload = {
        "client_name": "mcp-mirror",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": " ".join(discovery.scopes_supported),
        "token_endpoint_auth_method": "none",
        "application_type": "native",
    }
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        response = client.post(
            discovery.registration_endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        body = response.json()
    registered = RegisteredClient(
        client_id=body["client_id"],
        redirect_uri=redirect_uri,
        registration_endpoint=discovery.registration_endpoint,
        raw=body,
    )
    _write_json(
        cache,
        {
            "client_id": registered.client_id,
            "redirect_uri": registered.redirect_uri,
            "registration_endpoint": registered.registration_endpoint,
            "raw": registered.raw,
        },
    )
    return registered


# ---- PKCE flow ---------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _bind_port(preferred: int) -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", preferred))
        return preferred
    except OSError:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _await_callback(port: int, redirect_path: str, state: str, timeout_s: float = 300) -> str:
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args, **_kwargs):  # noqa: ARG002
            return

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != redirect_path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if (qs.get("state") or [""])[0] != state:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"state mismatch")
                return
            if "error" in qs:
                received["error"] = (qs.get("error") or [""])[0]
                received["error_description"] = (qs.get("error_description") or [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"OAuth error: {received['error']}".encode())
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
                b"<p>You can close this tab and return to mcp-mirror.</p></body>"
            )

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if "code" in received:
                return received["code"]
            if "error" in received:
                raise RuntimeError(
                    f"OAuth error: {received['error']} ({received.get('error_description','')})"
                )
            time.sleep(0.1)
        raise RuntimeError(f"Timed out after {int(timeout_s)}s waiting for OAuth callback.")
    finally:
        server.shutdown()


# ---- public entry point ------------------------------------------------------


def authenticate(gateway_url: str, *, open_browser: bool = True) -> CachedToken:
    """Full discovery + DCR + PKCE flow. Caches everything for next time."""
    discovery = discover(gateway_url)
    if not discovery.supports_pkce_s256:
        raise RuntimeError(
            f"Authorization server {discovery.issuer} does not advertise S256 PKCE."
        )

    port = _bind_port(DEFAULT_REDIRECT_PORT)
    redirect_uri = f"http://127.0.0.1:{port}{DEFAULT_REDIRECT_PATH}"
    client = register_client(discovery, gateway_url, redirect_uri)

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = (
        f"{discovery.authorization_endpoint}?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client.client_id,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "redirect_uri": redirect_uri,
                "scope": " ".join(discovery.scopes_supported),
                "resource": gateway_url,
                "state": state,
            }
        )
    )

    print(
        f"mcp-mirror: opening browser to authenticate with Arcade.\n"
        f"  authorization server: {discovery.issuer}\n"
        f"  client_id (DCR):      {client.client_id}\n"
        f"  resource (gateway):   {gateway_url}\n"
        f"\n"
        f"  If a browser does not open, visit:\n"
        f"  {auth_url}\n",
        flush=True,
    )
    if open_browser:
        webbrowser.open(auth_url)

    code = _await_callback(port, DEFAULT_REDIRECT_PATH, state)

    with httpx.Client(timeout=HTTP_TIMEOUT) as http_client:
        response = http_client.post(
            discovery.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client.client_id,
                "code_verifier": verifier,
                "resource": gateway_url,
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed ({response.status_code}): {response.text}"
            )
        payload = response.json()

    expires_in = float(payload.get("expires_in", 3600))
    token = CachedToken(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "Bearer"),
        expires_at=time.time() + expires_in,
        refresh_token=payload.get("refresh_token"),
        gateway_url=gateway_url,
    )
    _write_json(
        _cache_dir(gateway_url) / "token.json",
        {
            "access_token": token.access_token,
            "token_type": token.token_type,
            "expires_at": token.expires_at,
            "refresh_token": token.refresh_token,
            "gateway_url": token.gateway_url,
        },
    )
    return token


def _load_token(gateway_url: str) -> CachedToken | None:
    data = _read_json(_cache_dir(gateway_url) / "token.json")
    if not data:
        return None
    return CachedToken(
        access_token=data["access_token"],
        token_type=data.get("token_type", "Bearer"),
        expires_at=data["expires_at"],
        refresh_token=data.get("refresh_token"),
        gateway_url=data["gateway_url"],
    )


def _refresh(token: CachedToken, gateway_url: str) -> CachedToken | None:
    if not token.refresh_token:
        return None
    discovery = discover(gateway_url)
    client_meta = _read_json(_cache_dir(gateway_url) / "client.json")
    if not client_meta:
        return None
    with httpx.Client(timeout=HTTP_TIMEOUT) as http_client:
        response = http_client.post(
            discovery.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": client_meta["client_id"],
                "resource": gateway_url,
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
        gateway_url=gateway_url,
    )
    _write_json(
        _cache_dir(gateway_url) / "token.json",
        {
            "access_token": refreshed.access_token,
            "token_type": refreshed.token_type,
            "expires_at": refreshed.expires_at,
            "refresh_token": refreshed.refresh_token,
            "gateway_url": refreshed.gateway_url,
        },
    )
    return refreshed


def get_access_token(gateway_url: str, *, force_reauth: bool = False) -> str:
    if not force_reauth:
        cached = _load_token(gateway_url)
        if cached and not cached.is_expired:
            return cached.access_token
        if cached and cached.is_expired:
            refreshed = _refresh(cached, gateway_url)
            if refreshed:
                return refreshed.access_token
    token = authenticate(gateway_url)
    return token.access_token


def clear_cached(gateway_url: str) -> bool:
    d = _cache_dir(gateway_url)
    cleared = False
    for name in ("token.json", "client.json", "discovery.json"):
        p = d / name
        if p.is_file():
            p.unlink()
            cleared = True
    return cleared
