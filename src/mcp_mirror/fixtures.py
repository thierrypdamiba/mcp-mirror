"""Reference MCP server views — the ground-truth a server publishes.

These are the rich-schema tools we run through each framework adapter to surface
the differences in how each one represents them to the LLM.
"""

from __future__ import annotations

from mcp_mirror.types import ToolView


def send_message_tool() -> ToolView:
    """A messaging tool with rich schema, enums, oneOf, and structured response."""
    return ToolView(
        name="send_message",
        description=(
            "Send a message to a specific recipient on the configured platform. "
            "Recipient can be referenced by user ID, email, or display name; the "
            "tool will disambiguate when multiple candidates match. Returns a "
            "delivery receipt with timestamp, recipient identity, and platform-"
            "specific message ID."
        ),
        parameters_schema={
            "type": "object",
            "required": ["recipient", "body"],
            "properties": {
                "recipient": {
                    "oneOf": [
                        {
                            "type": "object",
                            "title": "By user ID",
                            "required": ["user_id"],
                            "properties": {"user_id": {"type": "string"}},
                        },
                        {
                            "type": "object",
                            "title": "By email",
                            "required": ["email"],
                            "properties": {
                                "email": {"type": "string", "format": "email"}
                            },
                        },
                        {
                            "type": "object",
                            "title": "By display name",
                            "required": ["display_name"],
                            "properties": {"display_name": {"type": "string"}},
                        },
                    ],
                    "description": "Whom to send the message to.",
                },
                "body": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 5000,
                    "description": "The message content. Plain text; markdown will be rendered platform-side.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                    "default": "normal",
                    "description": (
                        "low: queue for batch delivery. normal: standard. high: "
                        "deliver immediately with notification. urgent: page the "
                        "recipient if their oncall schedule says they are available."
                    ),
                },
                "scheduled_for": {
                    "type": "string",
                    "format": "date-time",
                    "description": "ISO 8601 timestamp. If omitted, send immediately.",
                },
            },
            "additionalProperties": False,
        },
        response_schema={
            "type": "object",
            "required": ["message_id", "delivered_at", "recipient_resolved"],
            "properties": {
                "message_id": {"type": "string"},
                "delivered_at": {"type": "string", "format": "date-time"},
                "recipient_resolved": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "display_name": {"type": "string"},
                    },
                },
                "alternates": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "If multiple recipients matched, the ones not chosen, so "
                        "the caller can disambiguate next time."
                    ),
                },
                "delivery_warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        metadata={
            "stability": "stable",
            "permissions_required": ["messaging:send"],
            "idempotent": False,
        },
    )


def search_records_tool() -> ToolView:
    """A search tool with confidence-scored results and freshness signals."""
    return ToolView(
        name="search_records",
        description=(
            "Full-text search across the records index. Returns ranked matches "
            "with confidence scores and a freshness marker indicating when the "
            "underlying index was last refreshed. Use the confidence threshold "
            "to decide whether to act on a result or ask for human disambiguation."
        ),
        parameters_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Search query. Supports basic boolean operators.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                },
                "confidence_threshold": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.7,
                    "description": (
                        "Only return results scoring at or above this confidence. "
                        "Lowering this returns more results but increases false-positive risk."
                    ),
                },
                "freshness_required_after": {
                    "type": "string",
                    "format": "date-time",
                    "description": (
                        "Reject results from an index older than this timestamp. "
                        "Use for time-sensitive queries where stale data is unsafe."
                    ),
                },
            },
        },
        response_schema={
            "type": "object",
            "required": ["results", "index_freshness", "total_matched"],
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "confidence"],
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "snippet": {"type": "string"},
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "last_modified": {"type": "string", "format": "date-time"},
                        },
                    },
                },
                "index_freshness": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Timestamp of the index this query was served from.",
                },
                "total_matched": {"type": "integer"},
                "below_threshold_count": {
                    "type": "integer",
                    "description": "Matches that existed but fell below confidence_threshold.",
                },
            },
        },
        metadata={
            "stability": "stable",
            "permissions_required": ["records:read"],
            "idempotent": True,
        },
    )


def all_tools() -> list[ToolView]:
    return [send_message_tool(), search_records_tool()]
