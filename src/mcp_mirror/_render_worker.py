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


def _result_boundary_ids(renderer, requested: list[str] | None) -> list[str | None]:
    """Which result boundaries this run should capture.

    ``None`` means "whatever the renderer captures by default", which keeps every
    existing caller that never mentions boundaries on exactly its old behaviour.
    """

    declare = getattr(renderer, "result_boundaries", None)
    if not callable(declare):
        return [None]
    declared = [boundary.id for boundary in declare()]
    if requested is None:
        return [None]
    if requested == ["*"]:
        return list(declared) or [None]
    return [boundary for boundary in requested if boundary in declared] or [None]


def _capture_results(
    renderer, handle, calls: list[dict], boundaries: list[str] | None = None
) -> list[dict]:
    """Invoke each requested tool through the adapter and record what came back.

    A renderer without ``render_result`` has no result boundary implemented yet, which
    is reported per call rather than failing the whole render: the tool definitions in
    the same response are still a valid measurement.

    A renderer that declares more than one result boundary is asked at each one it was
    told to capture, because which boundary a caller looks at can change the answer.
    """

    render_result = getattr(renderer, "render_result", None)
    boundary_ids = _result_boundary_ids(renderer, boundaries)
    captured = []
    for call in calls:
        tool = call.get("tool", "")
        arguments = call.get("arguments") or {}
        if not callable(render_result):
            captured.append(
                {"tool": tool, "ok": False, "error": "renderer has no render_result"}
            )
            continue
        for boundary in boundary_ids:
            entry: dict = {"tool": tool}
            if boundary is not None:
                entry["boundary"] = boundary
            try:
                rep = (
                    render_result(handle, tool, arguments)
                    if boundary is None
                    else render_result(handle, tool, arguments, boundary)
                )
                entry.update({"ok": True, "rep": rep.model_dump(mode="json")})
            except Exception as exc:  # noqa: BLE001 - a failed call is an observation
                entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            captured.append(entry)
    return captured


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
            declare = getattr(renderer, "result_boundaries", None)
            result = {
                "ok": True,
                "versions": versions,
                "evidence": evidence.model_dump(mode="json"),
                "result_boundaries": (
                    [boundary.model_dump(mode="json") for boundary in declare()]
                    if callable(declare)
                    else []
                ),
                "reps": [rep.model_dump() for rep in reps],
            }
            calls = request.get("calls") or []
            if calls:
                result["results"] = _capture_results(
                    renderer, handle, calls, request.get("result_boundaries")
                )
    except Exception as exc:  # noqa: BLE001 - report any failure back to the parent
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    out_path.write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
