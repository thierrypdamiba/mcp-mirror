"""Typer CLI (DESIGN.md section 15).

Exit codes: 0 success, 1 drift detected (regression mode), 2 connection/handshake
error, 3 spec-version assertion failed, 4 requested scan incomplete.
"""

from __future__ import annotations

import atexit
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import typer
from rich.console import Console
from rich.markup import escape

from . import __version__
from .diff import diff_reps
from .evidence import observe_tools, scan_provenance
from .jobs import evaluate_jobs, load_jobs
from .models import (
    FrameworkRun,
    RendererEvidence,
    Report,
    ScanConfiguration,
    ToolRep,
)
from .renderers import (
    RenderError,
    all_renderer_ids,
    available_renderers,
    canonical_id,
    install_hint,
    select_renderers,
)
from .report import compare_baseline, render_markdown, render_table, report_to_dict
from .runner_manifests import (
    ManagedRunnerUnavailable,
    build_managed_source_command,
    build_managed_worker_command,
    load_runner_manifests,
    managed_source_digest,
)
from .source import (
    ServerHandle,
    SourceConnectionError,
    load_source,
    parse_server,
)

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONN = 2
EXIT_SPEC = 3
EXIT_INCOMPLETE = 4

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Diff MCP tool definitions at declared agent-framework capture boundaries.",
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
    seen_names: set[str] = set()
    for item in values or []:
        name, sep, value = item.partition(":")
        name = name.strip()
        value = value.strip()
        if not sep or not name or not value:
            raise typer.BadParameter(
                "expected Name: Value",
                param_hint="--header",
            )
        folded_name = name.casefold()
        if folded_name in seen_names:
            raise typer.BadParameter(
                f"duplicate header name {name!r}",
                param_hint="--header",
            )
        seen_names.add(folded_name)

        references = {
            braced or bare
            for braced, bare in re.findall(
                r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
                value,
            )
        }
        missing = sorted(reference for reference in references if reference not in os.environ)
        if missing:
            raise typer.BadParameter(
                "environment variable"
                f"{'s' if len(missing) != 1 else ''} {', '.join(missing)} "
                "not set",
                param_hint="--header",
            )
        headers[name] = os.path.expandvars(value)
    return headers


def _redact_header_values(text: str, headers: dict[str, str]) -> str:
    """Remove known header values from diagnostics before printing or storing."""

    redacted = text
    secrets: set[str] = set()
    for value in headers.values():
        if len(value) >= 4:
            secrets.add(value)
        _, separator, credential = value.partition(" ")
        if separator and len(credential) >= 4:
            secrets.add(credential)
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _is_sensitive_credential_name(name: str) -> bool:
    return bool(
        re.search(
            r"(?:^|[_-])(?:api[_-]?key|access[_-]?token|token|secret|"
            r"password|passwd|signature|credential|authorization|auth|key)"
            r"(?:[_-]|$)",
            name.lstrip("-"),
            flags=re.IGNORECASE,
        )
    )


def _report_server_spec(
    handle: ServerHandle,
    headers: dict[str, str],
) -> str:
    """Return a citable server identifier without common credential forms."""

    spec = handle.spec
    if handle.transport == "http":
        parts = urlsplit(spec)
        hostname = parts.hostname or ""
        host = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = f":{parts.port}" if parts.port is not None else ""
        except ValueError:
            port = ""

        query: list[tuple[str, str]] = []
        for name, value in parse_qsl(
            parts.query,
            keep_blank_values=True,
        ):
            if _is_sensitive_credential_name(name):
                value = "<redacted>"
            query.append((name, value))
        spec = urlunsplit(
            (
                parts.scheme,
                f"{host}{port}",
                parts.path,
                urlencode(query, doseq=True, safe="<>"),
                "",
            )
        )
    else:
        command = [handle.command or "", *handle.args]
        redacted_command: list[str] = []
        redact_next = False
        for argument in command:
            if redact_next:
                redacted_command.append("<redacted>")
                redact_next = False
                continue
            name, separator, _value = argument.partition("=")
            if _is_sensitive_credential_name(name):
                if separator:
                    redacted_command.append(f"{name}=<redacted>")
                else:
                    redacted_command.append(argument)
                    redact_next = True
                continue
            redacted_command.append(argument)
        spec = shlex.join(redacted_command)
    return _redact_header_values(spec, headers)


def _observation_secrets(
    handle: ServerHandle,
    headers: dict[str, str],
) -> list[str]:
    """Collect the credential strings a server could echo back into tool metadata."""

    secrets: list[str] = [value for value in headers.values() if value]
    for value in list(secrets):
        scheme, separator, token = value.partition(" ")
        if separator and token and scheme.lower() in {"bearer", "basic", "token"}:
            secrets.append(token)

    if handle.transport == "http":
        parts = urlsplit(handle.spec)
        if parts.password:
            secrets.append(parts.password)
        for name, value in parse_qsl(parts.query, keep_blank_values=True):
            if _is_sensitive_credential_name(name):
                secrets.append(value)
    else:
        redact_next = False
        for argument in [handle.command or "", *handle.args]:
            if redact_next:
                secrets.append(argument)
                redact_next = False
                continue
            name, separator, value = argument.partition("=")
            if _is_sensitive_credential_name(name):
                if separator:
                    secrets.append(value)
                else:
                    redact_next = True

    # Longest first, so a bearer header is replaced before its bare token would
    # split it into a half-redacted string.
    return sorted({secret for secret in secrets if secret}, key=len, reverse=True)


def _redact_diagnostic(
    text: str,
    handle: ServerHandle,
    headers: dict[str, str],
) -> str:
    redacted = text.replace(
        handle.spec,
        _report_server_spec(handle, headers),
    )
    return _redact_header_values(redacted, headers)


@lru_cache(maxsize=1)
def _managed_import_root() -> str:
    """Stage this package alone on a directory the managed interpreter can import.

    The worker needs ``mcp_mirror`` on ``PYTHONPATH``, but the installed parent
    directory is ``site-packages`` under a wheel install, which would hand the
    runner every host dependency and silently outrank the versions uv pinned for
    it. Linking the package into an otherwise empty directory puts exactly one
    importable name on the path, so the manifest still owns everything else.
    """

    package = Path(__file__).resolve().parent
    staging = Path(tempfile.mkdtemp(prefix="mcp-mirror-managed-"))
    atexit.register(shutil.rmtree, staging, True)
    link = staging / package.name
    try:
        link.symlink_to(package, target_is_directory=True)
    except OSError:
        shutil.copytree(package, link, ignore=shutil.ignore_patterns("__pycache__"))
    return str(staging)


def _managed_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = _managed_import_root()
    return environment


def _load_source_managed(
    handle: ServerHandle,
    expected_spec_version: str | None,
) -> tuple[str, list[ToolRep]]:
    """Load source tools through a protocol-compatible disposable uv environment."""

    fd, output_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    output = Path(output_path)
    request = json.dumps(
        {
            "server": handle.spec,
            "headers": handle.headers,
        }
    )
    try:
        try:
            command = build_managed_source_command(
                expected_spec_version,
                output,
            )
            process = subprocess.run(
                command,
                input=request,
                capture_output=True,
                text=True,
                timeout=300,
                env=_managed_environment(),
            )
        except ManagedRunnerUnavailable as exc:
            raise SourceConnectionError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise SourceConnectionError(
                "managed source connection timed out after 300s"
            ) from exc
        except OSError as exc:
            raise SourceConnectionError(
                f"managed source runner could not start: {exc}"
            ) from exc

        raw = output.read_text()
        if not raw.strip():
            tail = " | ".join(
                (process.stderr or "").strip().splitlines()[-3:]
            )
            raise SourceConnectionError(
                "managed source runner produced no output "
                f"(exit {process.returncode}); {tail}"
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SourceConnectionError(
                "managed source runner produced invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise SourceConnectionError(
                "managed source runner returned an invalid result"
            )
        if not payload.get("ok"):
            raise SourceConnectionError(
                payload.get("error", "unknown managed source error")
            )
        try:
            return (
                str(payload["spec_version"]),
                [ToolRep.model_validate(rep) for rep in payload["reps"]],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceConnectionError(
                "managed source runner returned an invalid result"
            ) from exc
    finally:
        output.unlink(missing_ok=True)


def _render_isolated(
    rid: str,
    server: str,
    headers: dict,
    runner_mode: str = "local_subprocess",
) -> tuple[dict, RendererEvidence, list[ToolRep]]:
    """Render one framework in its own subprocess so frameworks cannot interfere.

    Returns ``(versions, evidence, reps)`` or raises ``RenderError``. The worker writes
    JSON to a temp file (never stdout) so framework and server log noise cannot corrupt
    the result.
    """

    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    request = json.dumps({"server": server, "headers": headers})
    environment = None
    if runner_mode == "managed":
        try:
            command = build_managed_worker_command(rid, Path(out_path))
        except ManagedRunnerUnavailable as exc:
            Path(out_path).unlink(missing_ok=True)
            raise RenderError(str(exc)) from exc
        environment = _managed_environment()
    else:
        command = [
            sys.executable,
            "-m",
            "mcp_mirror._render_worker",
            rid,
            out_path,
        ]
    try:
        try:
            proc = subprocess.run(
                command,
                input=request,
                capture_output=True,
                text=True,
                timeout=300,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            raise RenderError("render timed out after 300s")
        except OSError as exc:
            raise RenderError(f"render worker could not start: {exc}") from exc

        raw = Path(out_path).read_text()
        if not raw.strip():
            tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
            raise RenderError(f"worker produced no output (exit {proc.returncode}); {tail}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RenderError("render worker produced invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RenderError("render worker returned an invalid result")
        if not payload.get("ok"):
            raise RenderError(payload.get("error", "unknown render error"))
        try:
            reps = [
                ToolRep.model_validate(rep)
                for rep in payload["reps"]
            ]
            evidence = RendererEvidence.model_validate(payload["evidence"])
        except (KeyError, ValueError, TypeError) as exc:
            raise RenderError(
                f"renderer returned an invalid result: {exc}"
            ) from exc
        versions = payload.get("versions") or {}
        if not isinstance(versions, dict):
            raise RenderError(
                "renderer returned an invalid result: "
                f"expected a versions mapping, got {type(versions).__name__}"
            )
        return versions, evidence, reps
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
        help=(
            "Comma-separated renderers (default: all installed locally, or all "
            "managed Python renderers). e.g. langchain,pydantic_ai,crewai"
        ),
    ),
    spec_version: Optional[str] = typer.Option(
        None, "--spec-version", help="Assert the negotiated MCP spec version; error if it differs."
    ),
    runner: str = typer.Option(
        "local",
        "--runner",
        help="Runner environment: local|managed. Managed uses manifest-pinned uv environments.",
    ),
    output: str = typer.Option("table", "--output", help="Output format: table|json|md."),
    job: Optional[str] = typer.Option(
        None,
        "--job",
        help="Filter scorecard columns, e.g. J1,J2. J5 is always included.",
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
    fail_on_incomplete: bool = typer.Option(
        False,
        "--fail-on-incomplete",
        help="Exit nonzero (4) if any requested framework is unsupported or fails.",
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", help="Write the full JSON report (baseline format) to this file."
    ),
    header: Optional[list[str]] = typer.Option(
        None,
        "--header",
        help="HTTP header for the MCP connection (repeatable), e.g. "
        "--header 'Authorization: Bearer ${MCP_API_KEY}'. Values expand ${ENV}.",
    ),
) -> None:
    """Scan a server through one or more frameworks and emit a scorecard."""

    if runner not in {"local", "managed"}:
        raise typer.BadParameter(
            "expected local or managed",
            param_hint="--runner",
        )
    if output not in {"table", "json", "md"}:
        raise typer.BadParameter(
            "expected table, json, or md",
            param_hint="--output",
        )
    if fail_on_drift and baseline is None:
        raise typer.BadParameter(
            "--fail-on-drift requires --baseline",
            param_hint="--fail-on-drift",
        )

    handle = parse_server(server)
    headers = _parse_headers(header)
    handle.headers = headers

    try:
        if runner == "managed":
            err_console.print(
                "[dim]managed source: resolving the protocol SDK "
                "(first run may download and cache packages)[/dim]"
            )
            negotiated_version, source_reps = _load_source_managed(
                handle,
                spec_version,
            )
        else:
            negotiated_version, source_reps = load_source(
                handle,
                spec_version,
            )
    except SourceConnectionError as exc:
        detail = _redact_diagnostic(str(exc), handle, headers)
        err_console.print(
            f"[red]connection/handshake error:[/red] {escape(detail)}"
        )
        raise typer.Exit(EXIT_CONN)

    observation_secrets = _observation_secrets(handle, headers)
    source_observation = observe_tools(
        stage="source",
        capture_api=(
            "mcp.Client.list_tools"
            if negotiated_version >= "2026-07-28"
            else "mcp.ClientSession.list_tools"
        ),
        capture_object="ListToolsResult.tools",
        tools=source_reps,
        secrets=observation_secrets,
    )

    source_spec_mismatch = bool(spec_version and negotiated_version != spec_version)
    if source_spec_mismatch:
        err_console.print(
            f"[red]spec-version assertion failed:[/red] expected {spec_version!r}, "
            f"server negotiated {negotiated_version!r}"
        )

    requested = _split_csv(frameworks)
    runner_manifests = load_runner_manifests()
    if runner == "managed":
        requested_ids = (
            [canonical_id(renderer_id) for renderer_id in requested]
            if requested is not None
            else [
                renderer_id
                for renderer_id, manifest in runner_manifests.items()
                if manifest.runtime == "python"
            ]
        )
        selected = {
            renderer_id: runner_manifests[renderer_id]
            for renderer_id in requested_ids
            if renderer_id in runner_manifests
        }
        missing = [
            renderer_id
            for renderer_id in requested_ids
            if renderer_id not in runner_manifests
        ]
    else:
        selected, missing = select_renderers(requested)
    runs: list[FrameworkRun] = []
    for rid in missing:
        detail = f"renderer {rid!r} is not installed; run {install_hint(rid)}"
        err_console.print(
            f"[yellow]warning:[/yellow] {escape(detail)}"
        )
        runs.append(
            FrameworkRun(
                framework=rid,
                framework_version="unknown",
                status="unsupported",
                status_detail=detail,
            )
        )
    if not selected:
        err_console.print(
            "[yellow]warning:[/yellow] no renderers available; run "
            "'mcp-mirror frameworks' for local setup, or select a known "
            "framework with --runner managed"
        )

    runs_reps: dict[str, list] = {}
    scan_exit_code = EXIT_OK
    if source_spec_mismatch:
        # Diffing adapters against a source that negotiated the wrong protocol
        # would produce findings nobody can act on, but the run still has to
        # reach the report so the assertion failure ships with its evidence.
        scan_exit_code = EXIT_SPEC
        selected = {}
        err_console.print(
            "[dim]skipping renderers: the source did not negotiate the "
            "asserted spec version[/dim]"
        )
    for rid in selected:
        runner_digest = (
            runner_manifests[rid].digest
            if runner == "managed"
            else None
        )
        try:
            if runner == "managed":
                err_console.print(
                    f"[dim]managed renderer: running {rid} in its manifest "
                    "environment[/dim]"
                )
                versions, evidence, rendered_reps = _render_isolated(
                    rid,
                    server,
                    headers,
                    runner_mode="managed",
                )
            else:
                versions, evidence, rendered_reps = _render_isolated(
                    rid,
                    server,
                    headers,
                )
        except RenderError as exc:
            detail = _redact_diagnostic(str(exc), handle, headers)
            err_console.print(
                f"[yellow]skipping {rid}:[/yellow] {escape(detail)}"
            )
            runs.append(
                FrameworkRun(
                    framework=rid,
                    framework_version="unknown",
                    runner_digest=runner_digest,
                    status="adapter_error",
                    status_detail=detail,
                )
            )
            continue
        observation = observe_tools(
            stage=evidence.capture_stage,
            capture_api=evidence.capture_api,
            capture_object=evidence.capture_object,
            tools=rendered_reps,
            limitation=evidence.limitation,
            secrets=observation_secrets,
        )
        renderer_spec_version = evidence.negotiated_mcp_spec_version
        if renderer_spec_version != negotiated_version:
            detail = (
                f"renderer negotiated {renderer_spec_version!r}, while the direct "
                f"source connection negotiated {negotiated_version!r}"
            )
            err_console.print(
                f"[red]renderer spec-version mismatch:[/red] {rid!r} negotiated "
                f"{renderer_spec_version!r}, while the direct source connection "
                f"negotiated {negotiated_version!r}; refusing a cross-version diff"
            )
            runs.append(
                FrameworkRun(
                    framework=rid,
                    framework_version=str(versions.get("framework", "unknown")),
                    adapter_version=(
                        str(versions["adapter"])
                        if versions.get("adapter")
                        else None
                    ),
                    runner_digest=runner_digest,
                    status="protocol_mismatch",
                    status_detail=detail,
                    evidence=evidence,
                    observations=[observation],
                )
            )
            scan_exit_code = EXIT_SPEC
            continue
        differences = diff_reps(source_reps, rendered_reps)
        runs.append(
            FrameworkRun(
                framework=rid,
                framework_version=str(versions.get("framework", "unknown")),
                adapter_version=(str(versions["adapter"]) if versions.get("adapter") else None),
                runner_digest=runner_digest,
                evidence=evidence,
                observations=[observation],
                differences=differences,
            )
        )
        runs_reps[rid] = rendered_reps

    jobs_filter = _split_csv(job)
    provenance = scan_provenance(__version__)
    if runner == "managed":
        provenance.runner_digest = managed_source_digest(spec_version)
    report = Report(
        mcp_server=_report_server_spec(handle, headers),
        mcp_spec_version=negotiated_version,
        mcp_spec_version_evidence=(
            "direct source connection server/discover result"
            if negotiated_version >= "2026-07-28"
            else "direct source connection initialize result"
        ),
        generated_with=f"mcp-mirror/{__version__}",
        provenance=provenance,
        scan=ScanConfiguration(
            transport=handle.transport,
            frameworks=[run.framework for run in runs],
            spec_version_assertion=spec_version,
            jobs=jobs_filter or [],
            jtbd=jtbd,
            header_names=sorted(headers),
            runner_mode=(
                "managed"
                if runner == "managed"
                else "local_subprocess"
            ),
        ),
        source_observation=source_observation,
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

    if out is not None:
        try:
            out.write_text(
                json.dumps(
                    report_to_dict(report, jobs_filter),
                    indent=2,
                )
            )
        except OSError as exc:
            err_console.print(
                f"[red]could not write {escape(str(out))}:[/red] "
                f"{escape(str(exc))}"
            )
            raise typer.Exit(EXIT_CONN)
        err_console.print(
            f"[dim]wrote report to {escape(str(out))}[/dim]"
        )

    drift = False
    if baseline is not None:
        drift = _run_baseline_compare(report, baseline)

    if output == "json":
        console.print_json(json.dumps(report_to_dict(report, jobs_filter)))
    elif output == "md":
        console.print(
            render_markdown(report, jobs_filter),
            markup=False,
            soft_wrap=True,
        )
    else:
        render_table(report, console, jobs_filter)

    if scan_exit_code != EXIT_OK:
        raise typer.Exit(scan_exit_code)
    # Incompleteness outranks drift: a diff computed from a partial scan is not a
    # trustworthy drift signal, so callers running both gates should see the
    # reason the scan cannot be believed rather than its conclusion.
    if fail_on_incomplete and any(run.status != "measured" for run in runs):
        raise typer.Exit(EXIT_INCOMPLETE)
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
def show(
    report_path: Path = typer.Argument(
        ...,
        help="Saved mcp-mirror JSON report.",
    ),
    output: str = typer.Option(
        "table",
        "--output",
        help="Output format: table|json|md.",
    ),
    job: Optional[str] = typer.Option(
        None,
        "--job",
        help="Filter scorecard columns, e.g. J1,J2. J5 is always included.",
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Write the rendered report to this file.",
    ),
) -> None:
    """Render a saved report without reconnecting to its MCP server."""

    if output not in {"table", "json", "md"}:
        raise typer.BadParameter(
            "expected table, json, or md",
            param_hint="--output",
        )
    try:
        report = Report.model_validate_json(report_path.read_text())
    except Exception as exc:  # noqa: BLE001 - present one stable CLI error
        err_console.print(
            f"[red]could not read report {escape(str(report_path))}:[/red] "
            f"{escape(str(exc))}"
        )
        raise typer.Exit(EXIT_CONN)

    jobs_filter = _split_csv(job)
    if output == "json":
        rendered = json.dumps(
            report_to_dict(report, jobs_filter),
            indent=2,
        )
    elif output == "md":
        rendered = render_markdown(report, jobs_filter)
    else:
        buffer = io.StringIO()
        plain_console = Console(
            file=buffer,
            color_system=None,
            width=120,
        )
        render_table(report, plain_console, jobs_filter)
        rendered = buffer.getvalue().rstrip()

    if out is not None:
        try:
            out.write_text(f"{rendered}\n")
        except OSError as exc:
            err_console.print(
                f"[red]could not write {escape(str(out))}:[/red] "
                f"{escape(str(exc))}"
            )
            raise typer.Exit(EXIT_CONN)
        err_console.print(f"[dim]wrote report to {escape(str(out))}[/dim]")
    elif output == "json":
        console.print_json(rendered)
    else:
        console.print(
            rendered,
            markup=False,
            soft_wrap=True,
        )


@app.command()
def frameworks() -> None:
    """List installed renderers and their versions."""

    available = available_renderers()
    manifests = load_runner_manifests()
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
            console.print(
                f"            {install_hint(rid)}",
                style="dim",
                markup=False,
            )
            if manifests[rid].runtime == "python":
                console.print(
                    "            or select it with --runner managed",
                    style="dim",
                )


@app.command()
def version() -> None:
    """Print the mcp-mirror version."""

    console.print(f"mcp-mirror {__version__}")


@app.command()
def serve() -> None:
    """Serve compatibility evidence as a read-only MCP server over stdio."""

    from .mcp_server import run_server

    run_server()


if __name__ == "__main__":
    app()
