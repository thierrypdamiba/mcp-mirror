#!/usr/bin/env python3
"""Interactive, local demonstration of the mcp-mirror MCP server."""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

TOOL = {
    "name": "delete_account",
    "description": "Permanently deletes a user account and all associated data.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "The account to delete.",
            },
            "confirm": {
                "type": "boolean",
                "description": "Must be true to proceed.",
            },
        },
        "required": ["account_id", "confirm"],
        "additionalProperties": False,
    },
    "annotations": {
        "destructiveHint": True,
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
}

RESULT = {
    "content": [{"type": "text", "text": "confirm was not set"}],
    "isError": True,
}

console = Console()


def _pause(message: str, enabled: bool) -> None:
    if enabled:
        console.input(f"\n[bold cyan]{message}[/bold cyan] [dim](press Enter)[/dim] ")


def _structured(response: Any) -> dict[str, Any]:
    if response.structuredContent is not None:
        return dict(response.structuredContent)
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise RuntimeError("mcp-mirror returned no structured result")


def _print_observations(capability: dict[str, Any]) -> None:
    table = Table(title=f"{capability['title']} · {capability['revision']}")
    table.add_column("Framework")
    table.add_column("Version")
    table.add_column("Observed mechanism")
    for observation in capability["observations"]:
        table.add_row(
            observation["framework"],
            observation["version"] or "unknown",
            observation["mechanism"] or observation["meaning"],
        )
    console.print(table)


async def _inspect_definition(session: ClientSession, *, pause: bool) -> None:
    console.print("\n[bold]Proposed tool[/bold]")
    console.print_json(data=TOOL)
    _pause("Ask mcp-mirror to inspect this definition.", pause)

    response = await session.call_tool(
        "inspect_tool_definition",
        {
            "tool": TOOL,
            "revision": "2025-11-25",
        },
    )
    definition = _structured(response)
    console.print(
        "\n[bold green]Detected capabilities[/bold green] "
        + ", ".join(definition["identified_capabilities"])
    )
    destructive = next(
        item
        for item in definition["compatibility"]
        if item["id"] == "destructive-hint"
    )
    _print_observations(destructive)


async def _inspect_result(session: ClientSession, *, pause: bool) -> None:
    console.print("\n[bold]Proposed tool result[/bold]")
    console.print_json(data=RESULT)
    _pause("Ask mcp-mirror to inspect this failure result.", pause)

    response = await session.call_tool(
        "inspect_tool_result",
        {
            "result": RESULT,
            "revision": "2025-11-25",
        },
    )
    inspected_result = _structured(response)
    console.print(
        "\n[bold green]Detected capabilities[/bold green] "
        + ", ".join(inspected_result["identified_capabilities"])
    )
    errors = next(
        item
        for item in inspected_result["compatibility"]
        if item["id"] == "tool-execution-errors"
    )
    _print_observations(errors)


async def run_demo(*, pause: bool, first: str) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_mirror.cli", "serve"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            console.print(
                Panel.fit(
                    "The editor submits a proposed MCP object.\n"
                    "mcp-mirror returns published, versioned boundary evidence.",
                    title="mcp-mirror as a build-time MCP server",
                )
            )
            inspections = {
                "definition": _inspect_definition,
                "result": _inspect_result,
            }
            for name in (first, "result" if first == "definition" else "definition"):
                await inspections[name](session, pause=pause)

            console.print(
                "\n[dim]No tool was executed and no model was called. "
                "Every row came from the published mcp-mirror dataset.[/dim]"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="run without waiting for audience prompts",
    )
    parser.add_argument(
        "--first",
        choices=("result", "definition"),
        default="result",
        help="choose which audience-selected inspection to show first",
    )
    args = parser.parse_args()
    anyio.run(partial(run_demo, pause=not args.no_pause, first=args.first))


if __name__ == "__main__":
    main()
