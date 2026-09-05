"""A deliberately tricky MCP server (DESIGN.md section 14).

Every tool here exercises one or more diff paths so mcp-mirror's own behavior is
reproducible and testable without an external server. Run it over stdio:

    python fixtures/tricky_server.py

Or point mcp-mirror at it directly:

    mcp-mirror scan "python fixtures/tricky_server.py"
"""

from __future__ import annotations

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server

# A long (> 1024 chars) description containing Unicode and special characters, to
# exercise both truncation detection and Unicode handling.
LONG_UNICODE_DESCRIPTION = (
    "Explain a topic in depth for a curious reader. "
    "This description is deliberately very long (over 1024 characters) so that "
    "adapters which truncate tool descriptions to fit a model's function-description "
    "limit can be detected by mcp-mirror. It also contains Unicode and special "
    "characters to verify they survive the round trip: accented words like café, "
    "naïve, résumé, jalapeño, and Zürich; non-Latin scripts such as 日本語 (Japanese), "
    "Ελληνικά (Greek), and Кириллица (Cyrillic); mathematical symbols ∑ ∫ ≈ ≠ ∞ ⊆ ⊕; "
    "currency signs € £ ¥ ₿; smart punctuation “curly quotes”, ‘single quotes’, an "
    "em-dash, an en–dash, and an ellipsis…; plus a few emoji 🔐 🚀 ✅ for good measure. "
    "The reader should receive a structured, well-paced explanation that starts from "
    "first principles, introduces the key vocabulary, walks through one concrete worked "
    "example, names the most common misconceptions, and then points to where to learn "
    "more. Keep the tone precise and friendly. Prefer short sentences. Define every "
    "term of art the first time it appears, and never assume the reader has seen the "
    "topic before. End with a one-paragraph recap that a busy person could read on its "
    "own and still come away with the single most important idea. SENTINEL_END_OF_LONG_DESCRIPTION."
)

TOOLS: list[types.Tool] = [
    types.Tool(
        name="search_records",
        description="Search records with optional filters. Read-only.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Full-text search query."},
                "status": {
                    "type": "string",
                    "description": "Filter by record status.",
                    "enum": ["active", "archived", "pending", "deleted"],
                },
                "owner_email": {
                    "type": "string",
                    "format": "email",
                    "description": "Restrict to records owned by this email address.",
                },
                "created_after": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Only records created at or after this RFC 3339 timestamp.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return.",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
            },
            "required": ["query"],
        },
        annotations=types.ToolAnnotations(title="Search records", readOnlyHint=True),
    ),
    types.Tool(
        name="create_report",
        description="Create a structured report from sections.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title."},
                "config": {
                    "type": "object",
                    "description": "Rendering configuration.",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["pdf", "html", "csv"],
                            "description": "Output format.",
                        },
                        "include_summary": {
                            "type": "boolean",
                            "description": "Whether to prepend an executive summary.",
                        },
                    },
                    "required": ["format"],
                },
                "sections": {
                    "type": "array",
                    "description": "Ordered report sections.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string", "description": "Section heading."},
                            "body": {"type": "string", "description": "Section body in markdown."},
                        },
                        "required": ["heading"],
                    },
                },
            },
            "required": ["title", "config"],
        },
        annotations=types.ToolAnnotations(title="Create report"),
    ),
    types.Tool(
        name="deliver_payload",
        description="Deliver a payload to a destination.",
        inputSchema={
            "type": "object",
            "properties": {
                "destination": {
                    "description": "Where to deliver the payload.",
                    "anyOf": [
                        {
                            "type": "string",
                            "format": "uri",
                            "description": "A webhook URL.",
                        },
                        {
                            "type": "object",
                            "description": "An object-store location.",
                            "properties": {
                                "bucket": {"type": "string"},
                                "key": {"type": "string"},
                            },
                            "required": ["bucket", "key"],
                        },
                    ],
                },
                "mode": {
                    "description": "Delivery mode.",
                    "oneOf": [{"const": "sync"}, {"const": "async"}],
                },
            },
            "required": ["destination"],
        },
        annotations=types.ToolAnnotations(title="Deliver payload", idempotentHint=False),
    ),
    types.Tool(
        name="delete_account",
        description=(
            "Permanently deletes a user account and all of its associated data. "
            "This action is destructive and irreversible: it cannot be undone, and it "
            "requires elevated admin scope (accounts:delete). Use with extreme caution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The id of the account to delete."},
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to proceed with the deletion.",
                },
            },
            "required": ["account_id", "confirm"],
        },
        annotations=types.ToolAnnotations(
            title="Delete account",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    ),
    types.Tool(
        name="explain_topic",
        description=LONG_UNICODE_DESCRIPTION,
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The subject to explain (supports Unicode: café, naïve, 日本語).",
                },
                "max_words": {
                    "type": "integer",
                    "description": "Soft cap on the explanation length.",
                    "minimum": 1,
                },
            },
            "required": ["topic"],
        },
        annotations=types.ToolAnnotations(title="Explain topic", readOnlyHint=True),
    ),
]


def build_server() -> Server:
    server: Server = Server("tricky-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"called {name} with {arguments!r}")]

    return server


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
