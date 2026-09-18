"""Capture every framework's tool-result boundaries, not just one per framework.

``measure_results.py`` asks each adapter for a result once, at whichever boundary the
renderer captures by default. That is enough when a framework has one answer, and
misleading when it has two: LangChain returns the same failed call as plain content
blocks through a direct invocation and as a ``ToolMessage`` with ``status="error"``
through the invocation an agent makes.

This script asks every renderer at every boundary it declares, so a published cell can
cite what was observed at each one rather than at whichever was measured first. Each
renderer runs in its pinned managed environment, exactly as the definition scan does.

    uv run python scripts/measure_result_boundaries.py

Writes the full capture to ``--out`` (default ``data/result-boundaries.json``) and
prints one line per framework, boundary and call.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp_mirror.cli import _managed_import_root  # noqa: E402
from mcp_mirror.models import ResultRep  # noqa: E402
from mcp_mirror.runner_manifests import build_managed_worker_command  # noqa: E402

# The two calls that separate a successful result from a failed one on the fixture:
# `search_records` returns one of every content block plus structuredContent, and
# `delete_account` with `confirm: false` is the tool-reported error path.
CALLS = [
    {
        "tool": "search_records",
        "arguments": {
            "query": "x",
            "status": "active",
            "owner_email": "a@b.com",
            "created_after": "2026-01-01T00:00:00Z",
            "limit": 5,
        },
    },
    {
        "tool": "delete_account",
        "arguments": {"account_id": "a", "confirm": False},
    },
]

PYTHON_RENDERERS = ("crewai", "langchain", "openai_agents", "pydantic_ai")


def _fixture_command(fixture_python: str) -> str:
    return f"{fixture_python} fixtures/tricky_server.py"


def capture_python(renderer_id: str, server: str) -> dict:
    """Run one Python renderer in its manifest environment at every boundary."""

    handle, out_path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    command = build_managed_worker_command(renderer_id, Path(out_path))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = _managed_import_root()
    request = json.dumps(
        {"server": server, "headers": {}, "calls": CALLS, "result_boundaries": ["*"]}
    )

    proc = subprocess.run(
        command, input=request, capture_output=True, text=True, timeout=900, env=environment
    )
    raw = Path(out_path).read_text()
    Path(out_path).unlink(missing_ok=True)
    if not raw.strip():
        raise SystemExit(f"{renderer_id}: worker wrote nothing\n{proc.stderr[-1500:]}")
    payload = json.loads(raw)
    if not payload.get("ok"):
        raise SystemExit(f"{renderer_id}: {payload.get('error')}")
    return payload


def capture_mastra(server: str) -> dict:
    """Run the Mastra renderer in-process; its pinned environment is its node_modules."""

    from mcp_mirror.renderers import available_renderers
    from mcp_mirror.source import parse_server

    renderer = available_renderers().get("mastra")
    if renderer is None:
        return {"ok": False, "error": "mastra renderer is not installed"}

    handle = parse_server(server)
    results = []
    for boundary in renderer.result_boundaries():
        for call in CALLS:
            entry = {"tool": call["tool"], "boundary": boundary.id}
            try:
                rep = renderer.render_result(
                    handle, call["tool"], call["arguments"], boundary.id
                )
                entry.update({"ok": True, "rep": rep.model_dump(mode="json")})
            except Exception as exc:  # noqa: BLE001 - a failed call is an observation
                entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            results.append(entry)
    return {
        "ok": True,
        "versions": renderer.versions(),
        "result_boundaries": [b.model_dump(mode="json") for b in renderer.result_boundaries()],
        "results": results,
    }


def describe(entry: dict) -> str:
    if not entry.get("ok"):
        # Spelled the way scripts/check_reproduce_commands.py greps for it, so a
        # capture that dies still fails the published-command gate.
        return f"FAILED: {entry.get('error')}"
    rep = ResultRep(**entry["rep"])
    return (
        f"kinds={rep.block_kinds} structured={rep.structured_content is not None} "
        f"isError={rep.is_error} text={(rep.text or '')[:60]!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-python",
        default=os.environ.get("MCP_MIRROR_FIXTURE_PYTHON", sys.executable),
        help="interpreter that runs fixtures/tricky_server.py, which fixes the "
        "protocol revision the adapters negotiate against",
    )
    parser.add_argument(
        "--renderers",
        default=",".join((*PYTHON_RENDERERS, "mastra")),
        help="comma-separated renderer ids to capture",
    )
    parser.add_argument("--out", default=str(ROOT / "data" / "result-boundaries.json"))
    args = parser.parse_args()

    requested = [r for r in args.renderers.replace(" ", "").split(",") if r]
    server = _fixture_command(args.fixture_python)
    print(f"fixture: {server}")

    captured: dict[str, dict] = {}
    for renderer_id in requested:
        print(f"\n=== {renderer_id} ===")
        payload = (
            capture_mastra(server)
            if renderer_id == "mastra"
            else capture_python(renderer_id, server)
        )
        captured[renderer_id] = payload
        if not payload.get("ok"):
            print(f"  unavailable: {payload.get('error')}")
            continue
        print(f"  version {(payload.get('versions') or {}).get('framework', '?')}")
        for boundary in payload.get("result_boundaries") or []:
            marker = "agent path" if boundary["agent_path"] else "not the agent path"
            print(f"  boundary {boundary['id']:<28} {boundary['capture_api']}  [{marker}]")
        for entry in payload.get("results") or []:
            label = f"{entry['tool']} @ {entry.get('boundary', 'default')}"
            print(f"    {label:<52} {describe(entry)}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "schema": "mcp-mirror/result-boundaries@1",
                "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fixture": "fixtures/tricky_server.py",
                "fixture_python": args.fixture_python,
                "calls": CALLS,
                "frameworks": captured,
            },
            indent=2,
        )
        + "\n"
    )
    try:
        shown = out_path.resolve().relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"\nwrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
