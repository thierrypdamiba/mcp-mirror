"""MCP source loader (DESIGN.md section 7).

Connects to one MCP server (stdio or streamable-HTTP), completes the initialize
handshake, **captures the negotiated protocol version** (non-negotiable, section 12),
lists tools, and returns source ``ToolRep`` objects.

This is the only place in the engine that imports the ``mcp`` SDK. The parsed
``ServerHandle`` is reused by framework renderers so each framework opens its own
connection through its own real adapter (DESIGN.md decision D1).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

import anyio

from .models import ToolRep
from .normalize import normalize_source_tool


class SourceConnectionError(RuntimeError):
    """Raised when the server cannot be reached or the handshake fails (exit code 2)."""


@dataclass
class ServerHandle:
    """A parsed server specification, transport-agnostic for downstream renderers."""

    spec: str
    transport: str  # "stdio" | "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)  # HTTP auth headers (e.g. Arcade)


def parse_server(spec: str) -> ServerHandle:
    """Parse a CLI ``<server>`` argument into a ``ServerHandle``.

    ``<server>`` is either an HTTP(S) URL (streamable-HTTP transport) or a command
    string launched as a subprocess (stdio transport).
    """

    spec = spec.strip()
    if spec.startswith("http://") or spec.startswith("https://"):
        return ServerHandle(spec=spec, transport="http", url=spec)
    parts = shlex.split(spec)
    if not parts:
        raise SourceConnectionError("empty server specification")
    return ServerHandle(spec=spec, transport="stdio", command=parts[0], args=parts[1:])


def load_source(handle: ServerHandle) -> tuple[str, list[ToolRep]]:
    """Synchronous entry point: returns ``(spec_version, source_tool_reps)``."""

    try:
        return anyio.run(_load_async, handle)
    except SourceConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any transport/handshake failure uniformly
        raise SourceConnectionError(f"failed to load MCP server {handle.spec!r}: {exc}") from exc


async def _load_async(handle: ServerHandle) -> tuple[str, list[ToolRep]]:
    from mcp import ClientSession

    async def run(read, write) -> tuple[str, list[ToolRep]]:
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            spec_version = str(getattr(init_result, "protocolVersion", "unknown"))
            tools_result = await session.list_tools()
            reps = [normalize_source_tool(_tool_to_dict(tool)) for tool in tools_result.tools]
            return spec_version, reps

    if handle.transport == "http":
        import httpx
        from mcp.client.streamable_http import streamable_http_client

        timeout = httpx.Timeout(30, read=300)
        async with httpx.AsyncClient(
            headers=handle.headers or None,
            follow_redirects=True,
            timeout=timeout,
        ) as http_client:
            async with streamable_http_client(
                handle.url,
                http_client=http_client,
            ) as streams:
                read, write = streams[0], streams[1]
                return await run(read, write)

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=handle.command, args=handle.args)
    async with stdio_client(params) as (read, write):
        return await run(read, write)


def _tool_to_dict(tool) -> dict:
    """Convert an MCP SDK ``Tool`` into the dict shape the normalizer expects."""

    annotations = getattr(tool, "annotations", None)
    annotations_dict: dict = {}
    if annotations is not None:
        dump = getattr(annotations, "model_dump", None)
        if callable(dump):
            annotations_dict = {k: v for k, v in dump().items() if v is not None}
        elif isinstance(annotations, dict):
            annotations_dict = {k: v for k, v in annotations.items() if v is not None}
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", None),
        "inputSchema": getattr(tool, "inputSchema", None) or {},
        "annotations": annotations_dict,
    }
