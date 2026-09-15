"""Reproduce the five-framework tool-result measurement for MCP 2025-11-25."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


def run(script: str, environment: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def main() -> int:
    environment = os.environ.copy()
    environment.update(
        {
            "MCP_MIRROR_FIXTURE_PYTHON": sys.executable,
            "MCP_MIRROR_RENDERERS": (
                "crewai,langchain,openai_agents,pydantic_ai"
            ),
            "MCP_MIRROR_CALLS": json.dumps(CALLS),
        }
    )
    run("measure_results.py", environment)
    run("measure_mastra_results.py", environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
