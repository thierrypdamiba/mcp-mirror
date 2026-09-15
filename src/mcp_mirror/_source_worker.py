"""Load the direct MCP source inside a protocol-compatible managed environment."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    output_path = Path(sys.argv[1])
    expected_spec_version = sys.argv[2]
    request = json.loads(sys.stdin.read() or "{}")

    from .source import load_source, parse_server

    try:
        handle = parse_server(request.get("server", ""))
        handle.headers = request.get("headers") or {}
        spec_version, reps = load_source(handle, expected_spec_version)
        result = {
            "ok": True,
            "spec_version": spec_version,
            "reps": [
                rep.model_dump(mode="json")
                for rep in reps
            ],
        }
    except Exception as exc:  # noqa: BLE001 - serialize failure to the parent
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    output_path.write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
