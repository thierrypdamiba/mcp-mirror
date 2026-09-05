"""Render one framework in an isolated subprocess (DESIGN.md decision D1, hardened).

Heavyweight agent frameworks pull in conflicting event-loop and global import state.
Running three of them in one process makes one break another (observed: CrewAI's import
leaves async state that makes pydantic_ai's ``anyio.run`` fail with "unhandled errors in
a TaskGroup"). So each render happens in its own process.

Invoked as::

    python -m mcp_mirror._render_worker <renderer_id> <out_path>

with the server spec on stdin. The result is written as JSON to ``<out_path>`` rather
than stdout, so framework and MCP-server log noise on stdout/stderr can never corrupt it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    renderer_id = sys.argv[1]
    out_path = Path(sys.argv[2])
    request = json.loads(sys.stdin.read() or "{}")
    server_spec = request.get("server", "")
    headers = request.get("headers") or {}

    from .renderers import available_renderers
    from .source import parse_server

    try:
        renderer = available_renderers().get(renderer_id)
        if renderer is None:
            result = {"ok": False, "error": f"renderer {renderer_id!r} is not installed"}
        else:
            handle = parse_server(server_spec)
            handle.headers = headers
            versions = renderer.versions()
            reps = renderer.render(handle)
            evidence = renderer.evidence()
            result = {
                "ok": True,
                "versions": versions,
                "evidence": evidence.model_dump(mode="json"),
                "reps": [rep.model_dump() for rep in reps],
            }
    except Exception as exc:  # noqa: BLE001 - report any failure back to the parent
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    out_path.write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
