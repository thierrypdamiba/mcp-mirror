"""A server that asks the client for things, to measure the client features.

`tricky_server.py` answers "what does the adapter do with what the server sends".
This one answers the opposite question: when the server initiates a request, does the
framework let the client respond at all? Sampling, elicitation and roots are all
server-to-client calls, so none of them are observable from a server that only replies.

It is a separate file rather than more tools on the tricky fixture because every
published measurement is taken against that fixture's five tools, and changing its
tool list would perturb results that have nothing to do with these features.

Run it over stdio, under an MCP 2.x SDK::

    python fixtures/probe_server.py
"""

from __future__ import annotations

import json

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server

# Each probe names the back-channel method it attempts and the parameters to send.
# The measurement is what comes back: a result, a protocol error, or no back channel.
PROBES: dict[str, tuple[str, dict]] = {
    "probe_sampling": (
        "sampling/createMessage",
        {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "SENTINEL_SAMPLING_PROMPT"}}
            ],
            "maxTokens": 16,
        },
    ),
    "probe_elicitation": (
        "elicitation/create",
        {
            "message": "SENTINEL_ELICITATION_PROMPT",
            "requestedSchema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    ),
    "probe_roots": ("roots/list", {}),
}

TOOLS: list[types.Tool] = [
    types.Tool(
        name=name,
        description=f"Ask the client to service {method!r} and report what happened.",
        inputSchema={"type": "object", "properties": {}},
    )
    for name, (method, _params) in PROBES.items()
]


async def _run_probe(context, name: str) -> dict:
    """Attempt one back-channel request and describe the outcome.

    The back channel is the connection-scoped `ServerSession` on the request context,
    not the request context itself. Every failure mode is recorded as a result rather
    than raised: a client that declines the request, or never answers it, is exactly
    what "the framework does not support this" looks like from the server's side.
    """

    method, _params = PROBES[name]
    session = getattr(context, "session", None)
    if session is None:
        return {"method": method, "outcome": "no_session"}

    try:
        if name == "probe_sampling":
            result = await session.create_message(
                messages=[
                    types.SamplingMessage(
                        role="user",
                        content=types.TextContent(
                            type="text", text="SENTINEL_SAMPLING_PROMPT"
                        ),
                    )
                ],
                max_tokens=16,
                # A server-initiated request rides the response stream of the request
                # that triggered it, so it has to name the call it belongs to. Without
                # this the transport reports no back channel at all.
                related_request_id=context.request_id,
            )
        elif name == "probe_elicitation":
            result = await session.elicit_form(
                message="SENTINEL_ELICITATION_PROMPT",
                requested_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                related_request_id=context.request_id,
            )
        else:
            result = await session.list_roots()
    except Exception as exc:  # noqa: BLE001 - the failure is the measurement
        return {
            "method": method,
            "outcome": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
    return {"method": method, "outcome": "ok", "result": str(result)[:400]}


def build_server() -> Server:
    async def _list_tools(_context, _params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def _call_tool(context, params) -> types.CallToolResult:
        report = await _run_probe(context, params.name)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(report))],
            structuredContent=report,
        )

    return Server("probe-mcp", on_list_tools=_list_tools, on_call_tool=_call_tool)


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
