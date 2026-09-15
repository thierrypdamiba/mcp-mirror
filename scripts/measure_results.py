"""Capture tool-call results from the adapters that reach MCP 2026-07-28.

The scan pipeline diffs tool *definitions*. This drives the same managed runner
environments to diff tool *results*, which is a second capture per renderer and needs
the pinned framework versions rather than whatever happens to be in the local venv.

    python scripts/measure_results.py

Prints one section per tool call: the source result, each adapter's rendering, and the
differences between them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp_mirror.cli import _managed_import_root  # noqa: E402
from mcp_mirror.diff import diff_result  # noqa: E402
from mcp_mirror.models import ResultRep  # noqa: E402
from mcp_mirror.runner_manifests import build_managed_worker_command  # noqa: E402

# The fixture must speak the same revision as the adapters under test. 2026-07-28 needs
# MCP SDK 2.x, which is not what the project venv is pinned to, so that run supplies its
# own interpreter. Pointing both variables at the 1.26 venv measures 2025-11-25 instead,
# where all five adapters can negotiate.
FIXTURE_PYTHON = os.environ.get("MCP_MIRROR_FIXTURE_PYTHON", "/tmp/fixture-v2/bin/python")
SERVER = f"{FIXTURE_PYTHON} fixtures/tricky_server.py"

LIVE_RENDERERS = (
    os.environ.get("MCP_MIRROR_RENDERERS", "openai_agents,pydantic_ai").replace(" ", "").split(",")
)

CALLS = json.loads(
    os.environ.get(
        "MCP_MIRROR_CALLS",
        json.dumps(
            [
                {"tool": "search_records", "arguments": {"query": "x"}},
                {"tool": "delete_account", "arguments": {"account_id": "a", "confirm": False}},
            ]
        ),
    )
)


def source_results() -> dict[str, ResultRep]:
    """Call each tool directly on the server, through the protocol-matched SDK."""

    script = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from mcp_mirror.source import parse_server, call_source_tool;"
        "h=parse_server(%r);"
        "print(json.dumps({c['tool']: call_source_tool(h, c['tool'], c['arguments']).model_dump(mode='json')"
        " for c in %r}))" % (str(ROOT / "src"), SERVER, CALLS)
    )
    proc = subprocess.run(
        [FIXTURE_PYTHON, "-c", script], capture_output=True, text=True, timeout=300
    )
    if proc.returncode != 0:
        raise SystemExit(f"source capture failed:\n{proc.stderr[-1500:]}")
    return {k: ResultRep(**v) for k, v in json.loads(proc.stdout).items()}


def rendered_results(renderer_id: str) -> dict[str, ResultRep | str]:
    """Run one renderer in its manifest environment and collect its result captures."""

    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    command = build_managed_worker_command(renderer_id, Path(out_path))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = _managed_import_root()
    request = json.dumps({"server": SERVER, "headers": {}, "calls": CALLS})

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

    version = (payload.get("versions") or {}).get("framework", "?")
    print(f"  {renderer_id} @ {version}")
    out: dict[str, ResultRep | str] = {}
    for entry in payload.get("results") or []:
        out[entry["tool"]] = (
            ResultRep(**entry["rep"]) if entry.get("ok") else entry.get("error", "failed")
        )
    return out


def main() -> int:
    print("capturing source results ...")
    sources = source_results()
    print("running renderers in their manifest environments ...")
    rendered = {rid: rendered_results(rid) for rid in LIVE_RENDERERS}

    for call in CALLS:
        tool = call["tool"]
        source = sources[tool]
        print(f"\n=== {tool} ===")
        print(
            f"  source        kinds={source.block_kinds} "
            f"structured={source.structured_content is not None} isError={source.is_error}"
        )
        for renderer_id in LIVE_RENDERERS:
            result = rendered[renderer_id].get(tool)
            if not isinstance(result, ResultRep):
                print(f"  {renderer_id:<13} FAILED: {result}")
                continue
            print(
                f"  {renderer_id:<13} kinds={result.block_kinds} "
                f"structured={result.structured_content is not None} isError={result.is_error}"
            )
            for index, block in enumerate(result.blocks):
                source_kind = (
                    source.block_kinds[index] if index < len(source.block_kinds) else "?"
                )
                print(f"      {source_kind:>14} -> {json.dumps(block)[:150]}")
            if not result.blocks and result.text:
                print(f"      {'(text only)':>14} -> {result.text[:150]!r}")
            for difference in diff_result(source, result):
                print(f"      [{difference.category}] {difference.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
