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
        # Icons are the one part of a tool definition aimed at a human rather than a
        # model, so an adapter built purely around function-calling has no obvious
        # place to put them. Two entries with different MIME types and sizes make a
        # partial rendering (e.g. keeping only `src`) visible as a change.
        icons=[
            types.Icon(
                src="https://example.com/icons/search.svg",
                mimeType="image/svg+xml",
                sizes=["any"],
            ),
            types.Icon(
                src="https://example.com/icons/search-32.png",
                mimeType="image/png",
                sizes=["32x32"],
            ),
        ],
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


# A 1x1 PNG and a minimal WAV header, small enough to inline and still be real media.
TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_WAV = "UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="

SENTINEL_STRUCTURED = {
    "count": 2,
    "records": [{"id": "rec_1", "status": "active"}, {"id": "rec_2", "status": "archived"}],
    "note": "SENTINEL_STRUCTURED_CONTENT",
}


def _rich_content() -> list:
    """One result carrying every content block a 2025-11-25 tool may return.

    Returning them together means a single invocation observes every content-kind
    feature at once, and an adapter that keeps only text becomes visible as the
    absence of the other blocks rather than as five separate scans.
    """

    return [
        types.TextContent(
            type="text",
            text="SENTINEL_TEXT_BLOCK",
            # Audience and priority are the only content annotations the spec defines,
            # and they are what a client would use to decide what to show a user.
            annotations=types.Annotations(audience=["user"], priority=0.9),
        ),
        types.ImageContent(type="image", data=TINY_PNG, mimeType="image/png"),
        types.AudioContent(type="audio", data=TINY_WAV, mimeType="audio/wav"),
        types.EmbeddedResource(
            type="resource",
            resource=types.TextResourceContents(
                uri="file:///fixtures/embedded.txt",
                mimeType="text/plain",
                text="SENTINEL_EMBEDDED_RESOURCE",
            ),
        ),
        types.ResourceLink(
            type="resource_link",
            uri="file:///fixtures/linked.txt",
            name="linked.txt",
            mimeType="text/plain",
            description="SENTINEL_RESOURCE_LINK",
        ),
    ]


def _call_result(name: str, arguments: dict) -> tuple[list, dict | None, bool]:
    """Build the content, structured content and error flag for one call.

    ``delete_account`` with ``confirm: false`` is the error path: a tool that reports
    failure through ``isError`` rather than a protocol error, which is the distinction
    an adapter can flatten into an ordinary success.
    """

    if name == "delete_account" and not (arguments or {}).get("confirm"):
        return (
            [types.TextContent(type="text", text="SENTINEL_TOOL_ERROR: confirm was not set")],
            None,
            True,
        )
    return _rich_content(), SENTINEL_STRUCTURED, False


RESOURCES: list[types.Resource] = [
    types.Resource(
        uri="file:///fixtures/notes.txt",
        name="notes.txt",
        title="Release notes",
        description="SENTINEL_RESOURCE_DESCRIPTION",
        mimeType="text/plain",
    ),
    types.Resource(
        uri="file:///fixtures/logo.png",
        name="logo.png",
        description="A binary resource, to check base64 survives the round trip.",
        mimeType="image/png",
    ),
]

RESOURCE_TEMPLATES: list[types.ResourceTemplate] = [
    types.ResourceTemplate(
        uriTemplate="file:///fixtures/records/{record_id}",
        name="record",
        description="SENTINEL_TEMPLATE_DESCRIPTION",
        mimeType="application/json",
    ),
]

PROMPTS: list[types.Prompt] = [
    types.Prompt(
        name="summarize_records",
        title="Summarize records",
        description="SENTINEL_PROMPT_DESCRIPTION",
        arguments=[
            types.PromptArgument(
                name="status",
                description="SENTINEL_ARGUMENT_DESCRIPTION",
                required=True,
            ),
            types.PromptArgument(
                name="tone",
                description="Optional writing tone.",
                required=False,
            ),
        ],
    ),
]


def _read_resource(uri: str):
    """Return the contents for one resource URI.

    The binary entry is what distinguishes an adapter that decodes base64 correctly from
    one that hands the agent a mangled string.
    """

    if str(uri).endswith("logo.png"):
        return types.BlobResourceContents(
            uri=uri, mimeType="image/png", blob=TINY_PNG
        )
    return types.TextResourceContents(
        uri=uri, mimeType="text/plain", text="SENTINEL_RESOURCE_TEXT"
    )


def _get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
    status = (arguments or {}).get("status", "<unset>")
    return types.GetPromptResult(
        description="SENTINEL_PROMPT_DESCRIPTION",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text", text=f"SENTINEL_PROMPT_MESSAGE status={status}"
                ),
            )
        ],
    )


def build_server() -> Server:
    server: Server = Server("tricky-mcp")

    # MCP Python SDK 1.x registered low-level handlers through decorators.
    # SDK 2.x takes explicit callbacks so the same fixture can serve both the
    # handshake-era and 2026-07-28 stateless protocols.
    if hasattr(server, "list_tools"):
        @server.list_tools()
        async def _list_tools() -> list[types.Tool]:
            return TOOLS

        @server.call_tool()
        async def _call_tool(name: str, arguments: dict):
            content, structured, is_error = _call_result(name, arguments or {})
            if is_error:
                # The 1.x low-level server maps a raised exception onto isError.
                raise ValueError(content[0].text)
            return (content, structured) if structured is not None else content

        @server.list_resources()
        async def _list_resources() -> list[types.Resource]:
            return RESOURCES

        @server.list_resource_templates()
        async def _list_resource_templates() -> list[types.ResourceTemplate]:
            return RESOURCE_TEMPLATES

        @server.read_resource()
        async def _read_resource_v1(uri):
            return _read_resource(uri)

        @server.list_prompts()
        async def _list_prompts() -> list[types.Prompt]:
            return PROMPTS

        @server.get_prompt()
        async def _get_prompt_v1(name: str, arguments: dict | None) -> types.GetPromptResult:
            return _get_prompt(name, arguments)

        return server

    async def _list_tools_v2(_context, _params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def _call_tool_v2(_context, params) -> types.CallToolResult:
        content, structured, is_error = _call_result(params.name, params.arguments or {})
        return types.CallToolResult(
            content=content,
            structuredContent=structured,
            isError=is_error,
        )

    async def _list_resources_v2(_context, _params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=RESOURCES)

    async def _list_resource_templates_v2(_context, _params) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(resourceTemplates=RESOURCE_TEMPLATES)

    async def _read_resource_v2(_context, params) -> types.ReadResourceResult:
        return types.ReadResourceResult(contents=[_read_resource(params.uri)])

    async def _list_prompts_v2(_context, _params) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=PROMPTS)

    async def _get_prompt_v2(_context, params) -> types.GetPromptResult:
        return _get_prompt(params.name, params.arguments)

    return Server(
        "tricky-mcp",
        on_list_tools=_list_tools_v2,
        on_call_tool=_call_tool_v2,
        on_list_resources=_list_resources_v2,
        on_list_resource_templates=_list_resource_templates_v2,
        on_read_resource=_read_resource_v2,
        on_list_prompts=_list_prompts_v2,
        on_get_prompt=_get_prompt_v2,
    )


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
