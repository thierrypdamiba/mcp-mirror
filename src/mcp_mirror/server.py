"""A real MCP server exposing rich-schema reference tools.

This is the *source of truth* mcp-mirror compares against. The schemas here
are intentionally rich (oneOf, enums, formats, nested objects, response shapes,
metadata) so that each framework's adapter has plenty to drop, mangle, or pass
through.

Run as a subprocess via stdio:
    python -m mcp_mirror.server

The framework adapters connect to this process via stdio MCP transport and
report what they hand to the LLM. The diff engine compares.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as mcp_types

from mcp_mirror import fixtures

server: Server = Server("mcp-mirror-reference")


def _tool_to_mcp(view) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=view.name,
        description=view.description,
        inputSchema=view.parameters_schema,
        outputSchema=view.response_schema,
        _meta=view.metadata or None,
    )


@server.list_tools()
async def list_tools() -> list[mcp_types.Tool]:
    return [_tool_to_mcp(t) for t in fixtures.all_tools()]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[mcp_types.TextContent]:
    """Echo the call back as a structured payload so framework runtimes can ingest it."""
    payload = {
        "name": name,
        "arguments": arguments or {},
        "note": "mcp-mirror reference server: echoing the call for inspection.",
    }
    return [mcp_types.TextContent(type="text", text=json.dumps(payload, indent=2))]


async def amain() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> int:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # pragma: no cover
        print(f"mcp-mirror server error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
