"""Command-line entry point for mcp-mirror.

The default behavior:
  1. Spawn the bundled reference MCP server via stdio.
  2. Connect three real framework adapters (LangChain, LlamaIndex, Pydantic AI)
     to it through their actual MCP integration code paths.
  3. Capture what each framework would hand to the LLM.
  4. Diff against what the server announced.
  5. Render a scorecard.

Other modes:
  --server CMD ...       Use a different MCP server (e.g., Arcade, or your own).
  --framework NAME       Restrict to specific framework(s).
  --json                 Machine-readable output.
  --detail               Per-tool-per-framework field-level breakdown.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from mcp import StdioServerParameters

from mcp_mirror import __version__, diff_views
from mcp_mirror.capture import (
    ALL_CAPTURES,
    capture_server_announcement,
)
from mcp_mirror.scorecard import render_detail, render_summary
from mcp_mirror.types import Category, ToolDiff

FRAMEWORK_CAPTURES = {k: v for k, v in ALL_CAPTURES.items() if k != "mcp-server"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-mirror",
        description=(
            "Compare what your MCP server announces against what each agent "
            "framework's adapter hands to the LLM. Real captures, real frameworks, "
            "real MCP plumbing — no simulators."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mcp-mirror {__version__}",
    )
    parser.add_argument(
        "--server",
        nargs="+",
        help=(
            "MCP server command to launch (default: the bundled reference server). "
            "Example: --server npx -y @some/mcp-server"
        ),
    )
    parser.add_argument(
        "--framework",
        action="append",
        choices=list(FRAMEWORK_CAPTURES.keys()),
        help=(
            "Restrict to one or more frameworks. Default: all installed. "
            f"Available: {', '.join(FRAMEWORK_CAPTURES.keys())}"
        ),
    )
    parser.add_argument(
        "--tool",
        action="append",
        help="Restrict comparison to a specific tool name (repeat for multiple).",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Print full per-tool-per-framework breakdown after the summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human scorecard.",
    )
    args = parser.parse_args(argv)

    if args.server:
        params = StdioServerParameters(command=args.server[0], args=args.server[1:])
    else:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_mirror.server"],
        )

    _load_dotenv()

    frameworks = args.framework or list(FRAMEWORK_CAPTURES.keys())
    try:
        diffs = asyncio.run(_run(params, frameworks, args.tool))
    except Exception as exc:
        print(f"mcp-mirror error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(_to_json(diffs), indent=2))
        return 0

    print(render_summary(diffs))
    if args.detail:
        print()
        for d in diffs:
            print(render_detail(d))
            print()
    return 0


async def _run(
    params: StdioServerParameters,
    frameworks: list[str],
    tool_filter: list[str] | None,
) -> list[ToolDiff]:
    server_result = await capture_server_announcement(params)
    server_views = {v.name: v for v in server_result.views}

    diffs: list[ToolDiff] = []
    for fw in frameworks:
        capture_fn = FRAMEWORK_CAPTURES[fw]
        try:
            result = await capture_fn(params)
        except Exception as exc:
            print(
                f"warning: {fw} capture failed ({type(exc).__name__}: {exc}); "
                f"skipping. Install with: pip install mcp-mirror[{fw}]",
                file=sys.stderr,
            )
            continue
        for view in result.views:
            if tool_filter and view.name not in set(tool_filter):
                continue
            server_view = server_views.get(view.name)
            if server_view is None:
                continue
            diffs.append(diff_views(server_view, view, result.framework))
    return diffs


def _to_json(diffs: list[ToolDiff]) -> dict:
    return {
        "diffs": [
            {
                "tool": d.tool_name,
                "framework": d.framework_name,
                "overall": d.overall_category.value,
                "counts": {c.value: n for c, n in d.counts_by_category().items() if n},
                "fields": [
                    {
                        "path": fd.path,
                        "category": fd.category.value,
                        "note": fd.note,
                        "server_value": _truncate(fd.server_value),
                        "framework_value": _truncate(fd.framework_value),
                    }
                    for fd in d.field_diffs
                ],
            }
            for d in diffs
        ]
    }


def _truncate(value: object, limit: int = 200) -> object:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    return value


def _load_dotenv() -> None:
    """Best-effort .env loader so users can drop OPENAI_API_KEY / ARCADE_API_KEY locally.

    Reads `./.env` and adds any KEY=VALUE pairs to os.environ if not already set.
    Skips comments and blank lines. No third-party dep required.
    """
    import os
    from pathlib import Path

    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return
    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
