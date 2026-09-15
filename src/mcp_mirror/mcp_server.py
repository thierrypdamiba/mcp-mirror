"""Read-only MCP server for querying mcp-mirror compatibility evidence."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

SUPPORT_LABELS = {
    "y": "preserved at the declared capture boundary",
    "a": "changed or retained at another boundary",
    "n": "not exposed at the declared capture boundary",
    "x": "adapter could not negotiate this protocol revision",
    "u": "not measured",
}

RESULT_CAPTURE_BOUNDARIES = {
    "crewai": {
        "capture_api": "crewai.tools.BaseTool.run",
        "capture_object": "direct tool return before surrounding agent event/message handling",
    },
    "langchain": {
        "capture_api": "langchain_core.tools.StructuredTool.ainvoke",
        "capture_object": "direct tool return before ToolNode creates the agent ToolMessage",
    },
    "openai-agents": {
        "capture_api": "agents.mcp.util.MCPUtil.invoke_mcp_tool",
        "capture_object": "Agents SDK ToolOutput produced for model-visible output",
    },
    "pydantic-ai": {
        "capture_api": "pydantic_ai.mcp.MCPToolset.direct_call_tool",
        "capture_object": "direct toolset result before model-request serialization",
    },
    "mastra": {
        "capture_api": "@mastra/mcp tool action execute",
        "capture_object": "tool action return before agent-message serialization",
    },
}


def _data_directories() -> list[Path]:
    directories: list[Path] = []
    if configured := os.environ.get("MCP_MIRROR_DATA"):
        directories.append(Path(configured).expanduser())
    directories.extend(
        [
            Path(__file__).resolve().parents[2] / "data" / "fulldata",
            Path(__file__).resolve().parent / "data",
        ]
    )
    return directories


@lru_cache(maxsize=1)
def load_snapshots() -> dict[str, dict[str, Any]]:
    """Load every bundled compatibility snapshot, keyed by MCP revision."""

    snapshots: dict[str, dict[str, Any]] = {}
    for directory in _data_directories():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("data-*.json")):
            if path.name == "data-1.0.json":
                continue
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            revision = payload.get("mcp_spec")
            if isinstance(revision, str) and revision:
                snapshots.setdefault(revision, payload)
    if not snapshots:
        searched = ", ".join(str(path) for path in _data_directories())
        raise RuntimeError(f"no mcp-mirror snapshots found; searched: {searched}")
    return snapshots


def _resolve_snapshot(revision: str | None) -> tuple[str, dict[str, Any]]:
    snapshots = load_snapshots()
    if revision in (None, "", "latest"):
        selected = sorted(snapshots)[-1]
        return selected, snapshots[selected]
    if revision not in snapshots:
        available = ", ".join(sorted(snapshots))
        raise ValueError(f"unknown MCP revision {revision!r}; available: {available}")
    return revision, snapshots[revision]


def list_snapshots_data() -> dict[str, Any]:
    rows = []
    for revision, snapshot in sorted(load_snapshots().items(), reverse=True):
        coverage = snapshot.get("coverage", {})
        rows.append(
            {
                "revision": revision,
                "measured_features": coverage.get("measured_features"),
                "total_features": coverage.get("total_features"),
                "frameworks": [
                    {
                        "id": framework_id,
                        "name": framework.get("name", framework_id),
                        "version": framework.get("current_version"),
                    }
                    for framework_id, framework in snapshot.get("agents", {}).items()
                ],
            }
        )
    return {"snapshots": rows}


def _cell_detail(
    capability: dict[str, Any],
    snapshot: dict[str, Any],
    framework_id: str,
) -> dict[str, Any]:
    framework = snapshot["agents"][framework_id]
    version = framework.get("current_version")
    raw = capability.get("stats", {}).get(framework_id, {}).get(version, "u")
    code = str(raw).split()[0]
    note = None
    match = re.search(r"#(\d+)", str(raw))
    if match:
        note = capability.get("notes_by_num", {}).get(match.group(1))
    if "Tool results" in capability.get("categories", []):
        result_boundary = RESULT_CAPTURE_BOUNDARIES[framework_id]
        capture_boundary = {
            **result_boundary,
            "capture_stage": "framework_tool_result",
            "provider_request_captured": False,
        }
    else:
        capture_boundary = framework.get("capture_boundary")
    return {
        "framework_id": framework_id,
        "framework": framework.get("name", framework_id),
        "version": version,
        "code": code,
        "meaning": SUPPORT_LABELS.get(code, "unknown support code"),
        "mechanism": note,
        "capture_boundary": capture_boundary,
    }


def capability_data(
    capability_id: str,
    revision: str | None = None,
    frameworks: list[str] | None = None,
) -> dict[str, Any]:
    selected_revision, snapshot = _resolve_snapshot(revision)
    capabilities = snapshot.get("data", {})
    if capability_id not in capabilities:
        matches = [
            item["id"]
            for item in _search_rows(snapshot, capability_id)
        ][:8]
        suffix = f"; close matches: {', '.join(matches)}" if matches else ""
        raise ValueError(f"unknown capability {capability_id!r}{suffix}")
    capability = capabilities[capability_id]
    selected_frameworks = frameworks or list(snapshot.get("agents", {}))
    unknown = [item for item in selected_frameworks if item not in snapshot.get("agents", {})]
    if unknown:
        raise ValueError(f"unknown framework id(s): {', '.join(unknown)}")
    return {
        "revision": selected_revision,
        "id": capability["id"],
        "title": capability.get("title"),
        "question": capability.get("question"),
        "description": capability.get("description"),
        "observations": [
            _cell_detail(capability, snapshot, framework_id)
            for framework_id in selected_frameworks
        ],
        "summary": capability.get("notes"),
        "limitations": capability.get("known_issues", []),
        "source": capability.get("docs_url") or capability.get("spec"),
        "reproduce": capability.get("reproduce"),
        "measured": capability.get("measured"),
    }


def _search_rows(snapshot: dict[str, Any], query: str) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in query.split() if term]
    scored: list[tuple[int, dict[str, Any]]] = []
    for capability in snapshot.get("data", {}).values():
        haystack = " ".join(
            str(capability.get(key, ""))
            for key in ("id", "title", "description", "question", "keywords")
        ).casefold()
        if not terms or not all(term in haystack for term in terms):
            continue
        score = sum(
            3 if term in str(capability.get("id", "")).casefold() else 1
            for term in terms
        )
        scored.append(
            (
                score,
                {
                    "id": capability["id"],
                    "title": capability.get("title"),
                    "question": capability.get("question"),
                    "categories": capability.get("categories", []),
                    "measured": capability.get("measured"),
                },
            )
        )
    return [row for _, row in sorted(scored, key=lambda item: (-item[0], item[1]["id"]))]


def search_capabilities_data(query: str, revision: str | None = None) -> dict[str, Any]:
    selected_revision, snapshot = _resolve_snapshot(revision)
    return {
        "revision": selected_revision,
        "query": query,
        "matches": _search_rows(snapshot, query)[:20],
    }


def _schema_capabilities(schema: Any) -> set[str]:
    found: set[str] = set()
    if not isinstance(schema, dict):
        return found
    if "required" in schema:
        found.add("required")
    if "enum" in schema:
        found.add("enum")
    if "format" in schema:
        found.add("format")
    if "default" in schema:
        found.add("default-value")
    if "additionalProperties" in schema:
        found.add("additional-properties")
    if "oneOf" in schema or "anyOf" in schema:
        found.add("one-of-any-of")
    if any(key in schema for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")):
        found.add("numeric-range")
    schema_type = schema.get("type")
    if schema_type == "object" and isinstance(schema.get("properties"), dict):
        if any(isinstance(value, dict) and value.get("description") for value in schema["properties"].values()):
            found.add("property-descriptions")
        if any(isinstance(value, dict) and value.get("type") == "object" for value in schema["properties"].values()):
            found.add("nested-objects")
        for child in schema["properties"].values():
            found.update(_schema_capabilities(child))
    if schema_type == "array":
        if isinstance(schema.get("items"), dict) and schema["items"].get("type") == "object":
            found.add("arrays-of-objects")
        found.update(_schema_capabilities(schema.get("items")))
    if isinstance(schema_type, list) and "null" in schema_type:
        found.add("null-acceptance")
    return found


def inspect_tool_definition_data(
    tool: dict[str, Any],
    revision: str | None = None,
    frameworks: list[str] | None = None,
) -> dict[str, Any]:
    identified = {"tool-name"}
    description = tool.get("description")
    if isinstance(description, str) and description:
        identified.add("description-fidelity")
        if len(description) >= 512:
            identified.add("long-descriptions")
    annotations = tool.get("annotations")
    if isinstance(annotations, dict):
        mapping = {
            "title": "title-annotation",
            "readOnlyHint": "read-only-hint",
            "destructiveHint": "destructive-hint",
            "idempotentHint": "idempotent-hint",
            "openWorldHint": "open-world-hint",
        }
        identified.update(mapping[key] for key in mapping.keys() & annotations.keys())
    if tool.get("icons"):
        identified.add("tool-icons")
    identified.update(_schema_capabilities(tool.get("inputSchema")))
    selected_revision, snapshot = _resolve_snapshot(revision)
    published = set(snapshot.get("data", {}))
    capabilities = [
        capability_data(capability_id, selected_revision, frameworks)
        for capability_id in sorted(identified & published)
    ]
    return {
        "revision": selected_revision,
        "tool": tool.get("name"),
        "identified_capabilities": [item["id"] for item in capabilities],
        "compatibility": capabilities,
        "note": "Results describe published capture boundaries, not overall framework quality.",
    }


def inspect_tool_result_data(
    result: dict[str, Any],
    revision: str | None = None,
    frameworks: list[str] | None = None,
) -> dict[str, Any]:
    identified = {"tools-call"}
    if result.get("isError") is True:
        identified.add("tool-execution-errors")
    if "structuredContent" in result:
        identified.add("structured-content")
    for block in result.get("content", []) if isinstance(result.get("content"), list) else []:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        mapping = {
            "text": "tool-text-content",
            "image": "tool-image-content",
            "audio": "tool-audio-content",
            "resource": "embedded-resource-content",
            "resource_link": "resource-link-content",
        }
        if block_type in mapping:
            identified.add(mapping[block_type])
        if block.get("annotations"):
            identified.add("content-annotations")
    selected_revision, snapshot = _resolve_snapshot(revision)
    published = set(snapshot.get("data", {}))
    capabilities = [
        capability_data(capability_id, selected_revision, frameworks)
        for capability_id in sorted(identified & published)
    ]
    return {
        "revision": selected_revision,
        "identified_capabilities": [item["id"] for item in capabilities],
        "compatibility": capabilities,
        "note": "Results describe published capture boundaries, not model behavior.",
    }


def create_server() -> FastMCP:
    server = FastMCP(
        "mcp-mirror",
        instructions=(
            "Use mcp-mirror while designing MCP tools and results. It reports "
            "versioned observations at explicitly named framework capture boundaries; "
            "it does not rank frameworks or predict model behavior."
        ),
        log_level="ERROR",
    )

    @server.tool()
    def list_snapshots() -> dict[str, Any]:
        """List MCP revisions, framework versions, and measurement coverage."""

        return list_snapshots_data()

    @server.tool()
    def search_capabilities(query: str, revision: str = "latest") -> dict[str, Any]:
        """Search the published MCP and JSON Schema capability catalog."""

        return search_capabilities_data(query, revision)

    @server.tool()
    def lookup_capability(
        capability_id: str,
        revision: str = "latest",
        frameworks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return versioned framework observations and evidence for one capability."""

        return capability_data(capability_id, revision, frameworks)

    @server.tool()
    def inspect_tool_definition(
        tool: dict[str, Any],
        revision: str = "latest",
        frameworks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Identify features used by an MCP tool definition and return known adapter observations."""

        return inspect_tool_definition_data(tool, revision, frameworks)

    @server.tool()
    def inspect_tool_result(
        result: dict[str, Any],
        revision: str = "latest",
        frameworks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Identify features used by an MCP CallToolResult and return known adapter observations."""

        return inspect_tool_result_data(result, revision, frameworks)

    @server.resource("mcp-mirror://snapshots")
    def snapshots_resource() -> str:
        """Machine-readable snapshot index."""

        return json.dumps(list_snapshots_data(), indent=2)

    @server.resource("mcp-mirror://capabilities/{revision}")
    def capabilities_resource(revision: str) -> str:
        """Machine-readable capability index for one MCP revision."""

        selected_revision, snapshot = _resolve_snapshot(revision)
        rows = [
            {
                "id": capability["id"],
                "title": capability.get("title"),
                "question": capability.get("question"),
                "categories": capability.get("categories", []),
            }
            for capability in snapshot.get("data", {}).values()
        ]
        return json.dumps({"revision": selected_revision, "capabilities": rows}, indent=2)

    return server


def run_server() -> None:
    """Run the read-only mcp-mirror server over stdio."""

    create_server().run(transport="stdio")


__all__ = [
    "capability_data",
    "create_server",
    "inspect_tool_definition_data",
    "inspect_tool_result_data",
    "list_snapshots_data",
    "load_snapshots",
    "run_server",
    "search_capabilities_data",
]
