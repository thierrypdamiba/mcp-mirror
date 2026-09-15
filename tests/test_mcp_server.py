"""Tests for the read-only mcp-mirror MCP server."""

from __future__ import annotations

import json
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_mirror.mcp_server import (
    capability_data,
    inspect_tool_definition_data,
    inspect_tool_result_data,
    list_snapshots_data,
)


def test_snapshot_and_capability_queries_return_versioned_evidence():
    snapshots = list_snapshots_data()["snapshots"]
    assert [item["revision"] for item in snapshots] == ["2026-07-28", "2025-11-25"]

    result = capability_data(
        "tool-execution-errors",
        "2025-11-25",
        ["langchain", "pydantic-ai"],
    )
    assert result["revision"] == "2025-11-25"
    assert result["id"] == "tool-execution-errors"
    assert [item["framework_id"] for item in result["observations"]] == [
        "langchain",
        "pydantic-ai",
    ]
    assert all(item["version"] for item in result["observations"])
    assert all(item["capture_boundary"] for item in result["observations"])
    assert (
        result["observations"][0]["capture_boundary"]["capture_object"]
        == "direct tool return before ToolNode creates the agent ToolMessage"
    )


def test_definition_inspection_identifies_fixture_features():
    result = inspect_tool_definition_data(
        {
            "name": "delete_account",
            "description": "Permanently deletes an account.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "Account identifier.",
                    },
                    "confirm": {"type": "boolean"},
                },
                "required": ["account_id", "confirm"],
                "additionalProperties": False,
            },
            "annotations": {
                "destructiveHint": True,
                "readOnlyHint": False,
            },
        },
        "2025-11-25",
    )

    assert {
        "additional-properties",
        "description-fidelity",
        "destructive-hint",
        "property-descriptions",
        "read-only-hint",
        "required",
        "tool-name",
    } <= set(result["identified_capabilities"])


def test_result_inspection_identifies_error_and_rich_content():
    result = inspect_tool_result_data(
        {
            "content": [
                {"type": "text", "text": "confirm was not set"},
                {"type": "image", "data": "AA==", "mimeType": "image/png"},
            ],
            "structuredContent": {"deleted": False},
            "isError": True,
        },
        "2025-11-25",
    )

    assert {
        "structured-content",
        "tool-execution-errors",
        "tool-image-content",
        "tool-text-content",
        "tools-call",
    } <= set(result["identified_capabilities"])


def test_stdio_server_exposes_query_and_inspection_tools():
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_mirror.cli", "serve"],
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {
                    "inspect_tool_definition",
                    "inspect_tool_result",
                    "list_snapshots",
                    "lookup_capability",
                    "search_capabilities",
                } <= names

                response = await session.call_tool(
                    "lookup_capability",
                    {
                        "capability_id": "destructive-hint",
                        "revision": "2025-11-25",
                        "frameworks": ["langchain"],
                    },
                )
                assert response.isError is not True
                serialized = json.dumps(
                    response.structuredContent
                    if response.structuredContent is not None
                    else [item.model_dump() for item in response.content]
                )
                assert "destructive-hint" in serialized
                assert "langchain" in serialized

    anyio.run(exercise)
