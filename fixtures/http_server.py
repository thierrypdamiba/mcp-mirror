"""Minimal local streamable-HTTP MCP server used by transport tests."""

from __future__ import annotations

import argparse

from mcp import types
from mcp.server.fastmcp import FastMCP


def build_server(port: int) -> FastMCP:
    server = FastMCP(
        "mcp-mirror-http-fixture",
        host="127.0.0.1",
        port=port,
        stateless_http=True,
    )

    @server.tool(
        name="http_ping",
        description="Return a message without changing state.",
        annotations=types.ToolAnnotations(
            title="HTTP ping",
            readOnlyHint=True,
        ),
    )
    def http_ping(message: str = "pong") -> str:
        return message

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    build_server(args.port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
