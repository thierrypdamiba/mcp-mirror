"""Publish the tool-result boundary at 2025-11-25 from the five-framework measurement.

Every code here comes from ``data/result-boundaries.json``: two calls against
``fixtures/tricky_server.py`` -- ``search_records``, which returns one of every content
block plus structuredContent, and ``delete_account``, which returns ``isError`` -- run
against every result boundary each adapter declares, not just the first one.

Asking at more than one boundary is the point. A tool definition has one obvious place
to read it; a tool result does not. The value an adapter hands back when its tool object
is invoked directly and the value the framework's own agent path produces can disagree,
and publishing only the first is how a row ends up describing something no agent does.
LangChain is where that bites: the same failed call reads as ordinary content blocks
through a direct invocation and as a ``ToolMessage`` with ``status="error"`` through the
invocation an agent makes.

One measurement limit is recorded rather than papered over. LangChain raises on the
audio block, so the whole ``search_records`` call fails and nothing reaches the agent.
That is a determinate answer about audio, and it is determinate at both boundaries: the
exception is not a ``ToolException``, so the tool's error handler never sees it. But it
means the image, embedded-resource and resource-link blocks in the same result were
never independently observed. Those cells stay 'u'; a single-block fixture would settle
them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from author_capability import write_capability  # noqa: E402

RUN_DATE = "2026-09-18"
SPEC = "2025-11-25"
REPRODUCE = "uv run python scripts/measure_result_boundaries.py"

# LangChain never delivered these blocks, but the reason was a sibling audio block that
# aborted the call, so the blocks themselves went unobserved.
CONFOUNDED = (
    "LangChain is unmeasured here: its audio conversion raises on the same result, so "
    "the call aborts before this block can be observed. Isolating it needs a fixture "
    "that returns one block at a time."
)

CAPABILITIES = [
    {
        "feature_id": "tool-execution-errors",
        "codes": {"crewai": "n", "langchain": "a", "openai-agents": "n", "pydantic-ai": "a", "mastra": "a"},
        "boundary_dependent": ["langchain"],
        "notes": {
            "crewai": (
                "CrewAI: the adapter's tool reads only `result.content` and never "
                "`result.isError`, so a failed call returns the same bare string a "
                "successful one does. Identical at `BaseTool.run` and at "
                "`CrewStructuredTool.invoke`, which is the path a crew run takes."
            ),
            "langchain": (
                "LangChain: the answer depends on the boundary. `load_mcp_tools` builds the "
                "tool with `handle_tool_error=_handle_mcp_tool_error`, so an `isError` result "
                "raises an internal `ToolException` subclass that the handler turns back into "
                "tool output. Invoked with a plain argument dict the call returns those content "
                "blocks and nothing marks them as a failure. Invoked with a `ToolCall`, which is "
                "what an agent and `ToolNode` send, the same call returns a `ToolMessage` with "
                "`status=\"error\"`."
            ),
            "openai-agents": (
                "OpenAI Agents: `invoke_mcp_tool` reads `isError` only to decide whether "
                "`structuredContent` may be preferred, then emits the error text as an ordinary "
                "text output item. Identical at `MCPUtil.invoke_mcp_tool` and at "
                "`FunctionTool.on_invoke_tool`, which is what the agent loop calls."
            ),
            "pydantic-ai": (
                "Pydantic AI: the toolset's `tool_error_behavior` defaults to `'retry'`, which "
                "raises `ModelRetry` carrying the error text. Identical at `direct_call_tool` "
                "and at `call_tool`, which delegates to it; an agent run records that raise as a "
                "typed `RetryPromptPart` rather than as a tool return."
            ),
            "mastra": (
                "Mastra: the per-server `onToolError` option defaults to `'throw'`, so the tool "
                "action throws a `MastraError` carrying the error text. Set to `'return'` the "
                "same action resolves with the server's `CallToolResult`, `isError: true` "
                "included."
            ),
        },
        "summary": (
            "Measured at every result boundary each adapter exposes: the value a direct "
            "invocation returns, and the value the framework's own agent path returns. No "
            "adapter delivers the specification's boolean on its default path. Three make the "
            "failure distinguishable, each through a different mechanism, and two return it as "
            "ordinary output an agent cannot tell from success. LangChain is the one adapter "
            "whose answer changes with the boundary, which is why its cell is marked as "
            "boundary-dependent rather than dropped."
        ),
        "verdict_code": "a",
        "verdict_headline": "Distinguishable at three adapters of five, through three different mechanisms.",
        "verdict_detail": (
            "LangChain marks the tool message `status=\"error\"`, Pydantic AI raises "
            "`ModelRetry`, and Mastra throws a `MastraError`; Mastra alone can be configured to "
            "hand back the flag itself, through its `onToolError: 'return'` server option. "
            "CrewAI and the OpenAI Agents SDK return the error text as ordinary output, so an "
            "agent reading the result cannot tell the call failed. One flag, five mechanisms, "
            "and the one an adapter gives you is not something the protocol lets you assume."
        ),
    },
    {
        "feature_id": "structured-content",
        "codes": {"crewai": "n", "langchain": "n", "openai-agents": "n", "pydantic-ai": "n", "mastra": "y"},
        "notes": {
            "crewai": "CrewAI: structuredContent is dropped; only the text mirror reaches the agent.",
            "langchain": "LangChain: structuredContent is dropped; only the text mirror reaches the agent.",
            "openai-agents": "OpenAI Agents: structuredContent is dropped; only the text mirror reaches the agent.",
            "pydantic-ai": "Pydantic AI: structuredContent is dropped; only the text mirror reaches the agent.",
        },
        "summary": (
            "Four of five drop the typed value and pass the agent the text mirror the server sent "
            "alongside it, which is the copy meant for humans. Mastra is the exception and keeps "
            "structuredContent intact, but it does so by dropping every content block in the same "
            "result, so no adapter delivers both halves of the response."
        ),
        "verdict_code": "n",
        "verdict_headline": "Reaches the agent at one boundary of five, and there by dropping all other content.",
        "verdict_detail": (
            "structuredContent exists so an agent can consume a result without parsing prose. "
            "Where it is dropped, the typed value a server carefully produced is replaced by its "
            "own human-readable summary."
        ),
    },
    {
        "feature_id": "content-annotations",
        "codes": {"crewai": "n", "langchain": "u", "openai-agents": "n", "pydantic-ai": "n", "mastra": "n"},
        "notes": {
            "crewai": "CrewAI: every content block is dropped, annotations with them.",
            "openai-agents": "OpenAI Agents: the text block survives; its annotations do not.",
            "pydantic-ai": "Pydantic AI: the text block survives; its annotations do not.",
            "mastra": "Mastra: every content block is dropped, annotations with them.",
        },
        "summary": (
            "Annotations say who a block is for and how much it matters. No adapter that delivered "
            "the block delivered its annotations. " + CONFOUNDED
        ),
        "verdict_code": "n",
        "verdict_headline": "Absent at every boundary where the block itself survived.",
        "verdict_detail": (
            "audience and priority are the server's only way to say 'this part is for the model, "
            "this part is for the user'. Nothing downstream can recover them."
        ),
    },
    {
        "feature_id": "tool-text-content",
        "codes": {"crewai": "a", "langchain": "y", "openai-agents": "y", "pydantic-ai": "y", "mastra": "n"},
        "notes": {
            "crewai": "CrewAI: the text arrives stringified inside a Python list repr, as \"['SENTINEL_TEXT_BLOCK']\" rather than the block's text.",
            "mastra": "Mastra: all content blocks are dropped, text included; only structuredContent reaches the agent.",
        },
        "summary": (
            "The one content type almost everything survives. Three adapters pass it through "
            "unchanged. CrewAI delivers the characters but wraps them in the repr of the list that "
            "held them, so the agent reads brackets and quotes as part of the text. Mastra drops it."
        ),
        "verdict_code": "a",
        "verdict_headline": "Unchanged at three boundaries, reshaped at one, dropped at one.",
        "verdict_detail": (
            "Text is the one content kind every adapter attempts to carry. Two of five change "
            "it anyway: CrewAI returns the repr of the list that held the block, so the agent "
            "reads brackets and quotes as characters, and Mastra returns structuredContent in "
            "place of any content block."
        ),
    },
    {
        "feature_id": "tool-image-content",
        "codes": {"crewai": "n", "langchain": "u", "openai-agents": "y", "pydantic-ai": "y", "mastra": "n"},
        "notes": {
            "crewai": "CrewAI: the image block is dropped from the result.",
            "mastra": "Mastra: all content blocks are dropped, images included.",
        },
        "summary": (
            "The two adapters built around multimodal model APIs pass images through; the two that "
            "flatten results to text or to structured data drop them. " + CONFOUNDED
        ),
        "verdict_code": "a",
        "verdict_headline": "Delivered by two, dropped by two, unmeasured at one.",
        "verdict_detail": (
            "A tool that returns a chart or a screenshot is only useful if the image reaches a "
            "model that can see it."
        ),
    },
    {
        "feature_id": "tool-audio-content",
        "codes": {"crewai": "n", "langchain": "n", "openai-agents": "a", "pydantic-ai": "y", "mastra": "n"},
        "notes": {
            "crewai": "CrewAI: the audio block is dropped from the result.",
            "langchain": (
                "LangChain: `_convert_mcp_content_to_lc_block` raises NotImplementedError -- "
                "'AudioContent conversion to LangChain content blocks is not yet supported' -- "
                "while building the result, so the whole call aborts and no part of it reaches "
                "the agent. Re-measured at both of LangChain's result boundaries and identical "
                "at each: the exception is not a `ToolException`, so the tool's "
                "`handle_tool_error` callback never sees it and the `ToolCall` invocation an "
                "agent makes raises exactly as the direct one does."
            ),
            "openai-agents": "OpenAI Agents: the block is serialized into a text block containing its JSON, base64 payload and all, so the audio reaches the agent only as characters.",
            "mastra": "Mastra: all content blocks are dropped, audio included.",
        },
        "summary": (
            "The least survivable content type measured. One adapter passes it through as audio. "
            "One turns it into a JSON string. Two drop it. LangChain raises instead of "
            "degrading, and the exception takes the rest of the result with it, so a server that "
            "returns audio alongside text returns nothing usable at all. That one was checked at "
            "both of LangChain's result boundaries in case it was an artifact of where the "
            "measurement looked; it is not, and the reason is that the exception is not the type "
            "the adapter's error handler is wired to catch."
        ),
        "verdict_code": "n",
        "verdict_headline": "Delivered as audio by one of five; aborts the call at one.",
        "verdict_detail": (
            "An unsupported content type that raises rather than degrades turns a partially "
            "supported result into a failed call."
        ),
    },
    {
        "feature_id": "embedded-resource-content",
        "codes": {"crewai": "n", "langchain": "u", "openai-agents": "a", "pydantic-ai": "n", "mastra": "n"},
        "notes": {
            "crewai": "CrewAI: the embedded resource is dropped from the result.",
            "openai-agents": "OpenAI Agents: serialized into a text block holding the resource's JSON, so uri and mimeType survive as characters rather than as fields.",
            "pydantic-ai": "Pydantic AI: reduced to a bare text block containing the resource's text. The uri and mimeType that identify it are gone.",
            "mastra": "Mastra: all content blocks are dropped, embedded resources included.",
        },
        "summary": (
            "An embedded resource carries its own identity: a uri, a mime type, and contents. No "
            "adapter delivers it as a resource. One preserves the fields by stringifying them, one "
            "keeps the contents and discards the identity, two drop it. " + CONFOUNDED
        ),
        "verdict_code": "n",
        "verdict_headline": "Delivered as a resource by none of the five.",
        "verdict_detail": (
            "Once the uri is gone the agent cannot cite, re-read, or refer to what it was given."
        ),
    },
    {
        "feature_id": "resource-link-content",
        "codes": {"crewai": "n", "langchain": "u", "openai-agents": "a", "pydantic-ai": "a", "mastra": "n"},
        "notes": {
            "crewai": "CrewAI: the resource link is dropped from the result.",
            "openai-agents": "OpenAI Agents: serialized into a text block holding the link's JSON, so name, uri and description survive as characters rather than as fields.",
            "pydantic-ai": "Pydantic AI: reduced to a bare text block containing only the uri. The link's name and description are gone.",
            "mastra": "Mastra: all content blocks are dropped, resource links included.",
        },
        "summary": (
            "A resource_link is a pointer the agent is meant to be able to follow. Two adapters "
            "keep the pointer but not its type, one of them shedding the name and description on "
            "the way. Two drop it entirely. " + CONFOUNDED
        ),
        "verdict_code": "a",
        "verdict_headline": "Survives as text at two boundaries, dropped at two.",
        "verdict_detail": (
            "A link flattened into prose still tells the agent where to look, which is more than "
            "the alternatives here manage."
        ),
    },
    {
        "feature_id": "tools-call",
        "codes": {"crewai": "y", "langchain": "y", "openai-agents": "y", "pydantic-ai": "y", "mastra": "y"},
        "notes": {},
        "summary": (
            "Every adapter can invoke a tool and return something to the agent. What arrives varies "
            "enormously, and the rest of this category is where that shows up: the call mechanism "
            "works everywhere, the result contract does not."
        ),
        "verdict_code": "y",
        "verdict_headline": "Supported by all five.",
        "verdict_detail": (
            "Every adapter completes the call and returns a value to the agent. What that value "
            "still contains is measured by the other rows in this category."
        ),
    },
]


if __name__ == "__main__":
    for spec in CAPABILITIES:
        path = write_capability(
            spec["feature_id"],
            codes=spec["codes"],
            notes=spec["notes"],
            summary=spec["summary"],
            verdict_code=spec["verdict_code"],
            verdict_headline=spec["verdict_headline"],
            verdict_detail=spec["verdict_detail"],
            run_date=RUN_DATE,
            spec=SPEC,
            reproduce=REPRODUCE,
            boundary_dependent=spec.get("boundary_dependent"),
        )
        print(f"  wrote {path.relative_to(Path(__file__).resolve().parent.parent)}")
    print(f"published {len(CAPABILITIES)} tool-result capabilities at {SPEC}")
