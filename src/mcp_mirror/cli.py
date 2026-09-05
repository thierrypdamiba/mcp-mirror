"""Typer CLI (DESIGN.md section 15).

Exit codes: 0 success, 1 drift detected (regression mode), 2 connection/handshake
error, 3 spec-version assertion failed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import __version__
from .diff import diff_reps
from .jobs import evaluate_jobs, load_jobs
from .models import FrameworkRun, Report, ToolRep
from .renderers import (
    RenderError,
    all_renderer_ids,
    available_renderers,
    select_renderers,
)
from .report import compare_baseline, render_markdown, render_table, report_to_dict
from .source import SourceConnectionError, load_source, parse_server

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONN = 2
EXIT_SPEC = 3

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Diff what an LLM receives from an MCP server across agent frameworks.",
)
console = Console()
err_console = Console(stderr=True)


def _split_csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_headers(values: Optional[list[str]]) -> dict[str, str]:
    """Parse repeated ``--header 'Name: Value'`` flags. Values support ``${ENV}``
    expansion, so a secret can be supplied via the environment, not the command line."""

    headers: dict[str, str] = {}
    for item in values or []:
        name, sep, value = item.partition(":")
        if not sep:
            continue
        headers[name.strip()] = os.path.expandvars(value.strip())
    return headers


def _render_isolated(rid: str, server: str, headers: dict) -> tuple[dict, list[ToolRep]]:
    """Render one framework in its own subprocess so frameworks cannot interfere.

    Returns ``(versions, reps)`` or raises ``RenderError``. The worker writes JSON to a
    temp file (never stdout) so framework and server log noise cannot corrupt the result.
    """

    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    request = json.dumps({"server": server, "headers": headers})
    try:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "mcp_mirror._render_worker", rid, out_path],
                input=request,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            raise RenderError("render timed out after 300s")

        raw = Path(out_path).read_text()
        if not raw.strip():
            tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
            raise RenderError(f"worker produced no output (exit {proc.returncode}); {tail}")
        payload = json.loads(raw)
        if not payload.get("ok"):
            raise RenderError(payload.get("error", "unknown render error"))
        reps = [ToolRep.model_validate(r) for r in payload["reps"]]
        return payload.get("versions", {}), reps
    finally:
        Path(out_path).unlink(missing_ok=True)


@app.command()
def scan(
    server: str = typer.Argument(
        ..., help="MCP server: an HTTP(S) URL or a stdio command string."
    ),
    frameworks: Optional[str] = typer.Option(
        None,
        "--frameworks",
        help="Comma-separated renderers (default: all installed). e.g. langchain,pydantic_ai,crewai",
    ),
    spec_version: Optional[str] = typer.Option(
        None, "--spec-version", help="Assert the negotiated MCP spec version; error if it differs."
    ),
    output: str = typer.Option("table", "--output", help="Output format: table|json|md."),
    job: Optional[str] = typer.Option(
        None, "--job", help="Filter the scorecard to specific job columns, e.g. J1,J5."
    ),
    jtbd: Optional[str] = typer.Option(
        None,
        "--jtbd",
        help="Run a Jobs-To-Be-Done spec: a file path or a bundled provider name (e.g. filesystem).",
    ),
    baseline: Optional[Path] = typer.Option(
        None, "--baseline", help="Baseline report JSON to compare against (regression mode)."
    ),
    fail_on_drift: bool = typer.Option(
        False, "--fail-on-drift", help="Exit nonzero (1) if drift is detected vs the baseline."
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", help="Write the full JSON report (baseline format) to this file."
    ),
    header: Optional[list[str]] = typer.Option(
        None,
        "--header",
        help="HTTP header for the MCP connection (repeatable), e.g. "
        "--header 'Authorization: Bearer ${ARCADE_API_KEY}'. Values expand ${ENV}.",
    ),
) -> None:
    """Scan a server through one or more frameworks and emit a scorecard."""

    handle = parse_server(server)
    headers = _parse_headers(header)
    handle.headers = headers

    try:
        negotiated_version, source_reps = load_source(handle)
    except SourceConnectionError as exc:
        err_console.print(f"[red]connection/handshake error:[/red] {exc}")
        raise typer.Exit(EXIT_CONN)

    if spec_version and negotiated_version != spec_version:
        err_console.print(
            f"[red]spec-version assertion failed:[/red] expected {spec_version!r}, "
            f"server negotiated {negotiated_version!r}"
        )
        raise typer.Exit(EXIT_SPEC)

    requested = _split_csv(frameworks)
    selected, missing = select_renderers(requested)
    for rid in missing:
        err_console.print(
            f"[yellow]warning:[/yellow] renderer {rid!r} not installed; "
            f"install it (e.g. pip install 'mcp-mirror[{rid.replace('_', '-')}]')"
        )
    if not selected:
        err_console.print(
            "[yellow]warning:[/yellow] no renderers available; install extras, "
            "e.g. pip install 'mcp-mirror[all]'"
        )

    runs: list[FrameworkRun] = []
    runs_reps: dict[str, list] = {}
    for rid in selected:
        try:
            versions, rendered_reps = _render_isolated(rid, server, headers)
        except RenderError as exc:
            err_console.print(f"[yellow]skipping {rid}:[/yellow] {exc}")
            continue
        differences = diff_reps(source_reps, rendered_reps)
        runs.append(
            FrameworkRun(
                framework=rid,
                framework_version=str(versions.get("framework", "unknown")),
                adapter_version=(str(versions["adapter"]) if versions.get("adapter") else None),
                differences=differences,
            )
        )
        runs_reps[rid] = rendered_reps

    report = Report(
        mcp_server=handle.spec,
        mcp_spec_version=negotiated_version,
        generated_with=f"mcp-mirror/{__version__}",
        tools=[rep.name for rep in source_reps],
        runs=runs,
    )

    if jtbd:
        try:
            spec = load_jobs(jtbd)
        except (FileNotFoundError, RuntimeError) as exc:
            err_console.print(f"[red]could not load JTBD spec:[/red] {exc}")
            raise typer.Exit(EXIT_CONN)
        findings, spec_warnings = evaluate_jobs(spec, source_reps, runs_reps)
        report.job_findings = findings
        for warning in spec_warnings:
            err_console.print(f"[yellow]job spec:[/yellow] {warning}")

    jobs_filter = _split_csv(job)

    drift = False
    if baseline is not None:
        drift = _run_baseline_compare(report, baseline)

    if out is not None:
        out.write_text(json.dumps(report_to_dict(report, jobs_filter), indent=2))
        err_console.print(f"[dim]wrote report to {out}[/dim]")

    if output == "json":
        console.print_json(json.dumps(report_to_dict(report, jobs_filter)))
    elif output == "md":
        console.print(render_markdown(report, jobs_filter))
    else:
        render_table(report, console, jobs_filter)

    if baseline is not None and fail_on_drift and drift:
        raise typer.Exit(EXIT_DRIFT)
    raise typer.Exit(EXIT_OK)


def _run_baseline_compare(report: Report, baseline: Path) -> bool:
    try:
        baseline_report = Report.model_validate_json(baseline.read_text())
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]could not read baseline {baseline}:[/red] {exc}")
        raise typer.Exit(EXIT_CONN)

    drift, messages = compare_baseline(report, baseline_report)
    style = "red" if drift else "green"
    err_console.print(f"[{style}]baseline comparison ({'DRIFT' if drift else 'clean'}):[/{style}]")
    for message in messages:
        err_console.print(f"  {message}")
    return drift


@app.command()
def frameworks() -> None:
    """List installed renderers and their versions."""

    available = available_renderers()
    console.print("[bold]renderers[/bold]")
    for rid in all_renderer_ids():
        if rid in available:
            versions = available[rid].versions()
            console.print(
                f"  [green]installed[/green] {rid} "
                f"(framework {versions.get('framework', '?')}, adapter {versions.get('adapter', '?')})"
            )
        else:
            console.print(f"  [dim]missing[/dim]   {rid}")


@app.command()
def version() -> None:
    """Print the mcp-mirror version."""

    console.print(f"mcp-mirror {__version__}")


if __name__ == "__main__":
    app()
