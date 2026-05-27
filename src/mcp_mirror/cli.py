"""Command-line entry point for mcp-mirror."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Sequence

from mcp_mirror import __version__, diff_views
from mcp_mirror.capture import ALL_CAPTURES, capture_server_announcement
from mcp_mirror.scorecard import render_detail, render_summary
from mcp_mirror.spec import ServerSpec
from mcp_mirror.types import ToolDiff

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
    parser.add_argument("--version", action="version", version=f"mcp-mirror {__version__}")

    source = parser.add_argument_group(
        "source",
        description="Where to read the MCP server from. Default: bundled reference server.",
    )
    source.add_argument(
        "--server",
        nargs="+",
        help=(
            "Run a stdio MCP server as a subprocess. "
            "Example: --server npx -y @some/mcp-server"
        ),
    )
    source.add_argument(
        "--http",
        metavar="URL",
        help="Connect to a streamable-HTTP MCP server at the given URL.",
    )
    source.add_argument(
        "--arcade",
        action="store_true",
        help=(
            "Connect to your Arcade MCP gateway (URL from ARCADE_GATEWAY_URL env). "
            "Runs the OAuth2 flow in a browser on first use; caches the token."
        ),
    )
    source.add_argument(
        "--re-auth",
        action="store_true",
        help="Discard cached Arcade token and re-run the OAuth flow.",
    )

    parser.add_argument(
        "--framework",
        action="append",
        choices=list(FRAMEWORK_CAPTURES.keys()),
        help="Restrict to one or more frameworks. Default: all installed.",
    )
    parser.add_argument(
        "--tool",
        action="append",
        help="Restrict to specific tool names. Repeat for multiple.",
    )
    parser.add_argument("--detail", action="store_true", help="Per-field breakdown.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    parser.add_argument(
        "--eval",
        action="store_true",
        help=(
            "Layer 2: run behavioral eval (golden cases) through a real model "
            "against each framework's tool view and compare. Needs OPENAI_API_KEY."
        ),
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --eval (default: gpt-4o).",
    )

    args = parser.parse_args(argv)
    _load_dotenv()
    _suppress_mcp_session_noise()

    try:
        spec = _resolve_spec(args)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"mcp-mirror: {exc}", file=sys.stderr)
        return 2

    frameworks = args.framework or list(FRAMEWORK_CAPTURES.keys())

    if args.eval:
        try:
            return _run_eval(spec, frameworks, args.model, args.json)
        except Exception as exc:
            print(f"mcp-mirror eval error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    try:
        diffs = asyncio.run(_run(spec, frameworks, args.tool))
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


def _resolve_spec(args) -> ServerSpec:
    mode_count = sum(bool(x) for x in (args.server, args.http, args.arcade))
    if mode_count > 1:
        raise ValueError("--server, --http, and --arcade are mutually exclusive.")

    if args.arcade:
        gateway = os.environ.get("ARCADE_GATEWAY_URL")
        if not gateway:
            raise ValueError(
                "ARCADE_GATEWAY_URL is not set. Add it to .env or export it. "
                "Find or create one at https://app.arcade.dev/mcp-gateways."
            )
        # Lazy import: only pull in arcade_auth when explicitly asked.
        from mcp_mirror import arcade_auth

        token = arcade_auth.get_access_token(gateway, force_reauth=args.re_auth)
        return ServerSpec.http(gateway, headers={"Authorization": f"Bearer {token}"})

    if args.http:
        return ServerSpec.http(args.http)

    if args.server:
        return ServerSpec.stdio(args.server[0], args.server[1:])

    return ServerSpec.stdio(sys.executable, ["-m", "mcp_mirror.server"])


def _canonical(name: str) -> str:
    """Frameworks rename tools (CrewAI: CamelCase -> snake_case). Match loosely."""
    return name.lower().replace("_", "").replace("-", "").replace(".", "")


async def _run(
    spec: ServerSpec,
    frameworks: list[str],
    tool_filter: list[str] | None,
) -> list[ToolDiff]:
    server_result = await capture_server_announcement(spec)
    server_by_canon = {_canonical(v.name): v for v in server_result.views}

    diffs: list[ToolDiff] = []
    for fw in frameworks:
        capture_fn = FRAMEWORK_CAPTURES[fw]
        try:
            result = await capture_fn(spec)
        except Exception as exc:
            print(
                f"warning: {fw} capture failed ({type(exc).__name__}: {exc}); skipping.",
                file=sys.stderr,
            )
            continue
        for view in result.views:
            server_view = server_by_canon.get(_canonical(view.name))
            if server_view is None:
                continue
            if tool_filter and server_view.name not in set(tool_filter):
                continue
            diffs.append(diff_views(server_view, view, result.framework))
    return diffs


def _run_eval(spec: ServerSpec, frameworks: list[str], model: str, as_json: bool) -> int:
    """Layer 2: behavioral comparison across frameworks via arcade_evals."""
    from mcp_mirror.eval_cases import golden_cases
    from mcp_mirror.llm_eval import eval_across_frameworks, summarize

    results = asyncio.run(
        eval_across_frameworks(spec, frameworks, golden_cases(), model=model)
    )
    summary = summarize(results)

    if as_json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"LAYER 2 — behavioral eval ({len(golden_cases())} golden cases, model={model})")
    print("-" * 64)
    print("track            result")
    print("-" * 64)
    for track, s in summary.items():
        if s.get("rejected"):
            print(f"{track:16} REJECTED by provider — schema not accepted (e.g. oneOf)")
        elif s.get("errored"):
            print(f"{track:16} ERRORED — {s['reason'][:44]}")
        else:
            print(
                f"{track:16} passed={s['passed']}  warned={s['warned']}  failed={s['failed']}"
            )
    print("-" * 64)
    print("A REJECTED track means the model could never be offered the tool at all.")
    print("Compare against the `server` control to see if a transform helped or hurt.")
    return 0


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


def _suppress_mcp_session_noise() -> None:
    """The MCP SDK prints `Session termination failed: 202` on streamable-HTTP
    cleanup — harmless (the server returns 202 Accepted on session DELETE), but
    visually distracting in the scorecard output. Redirect those specific lines.
    """
    import logging

    class _DropNoisyMessages(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return "Session termination failed" not in msg

    for name in ("mcp", "mcp.client.streamable_http", "httpx"):
        logging.getLogger(name).addFilter(_DropNoisyMessages())


def _load_dotenv() -> None:
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
