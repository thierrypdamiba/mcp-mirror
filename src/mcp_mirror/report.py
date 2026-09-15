"""Reporters and the regression baseline comparison (DESIGN.md sections 11, 13).

Three output formats share one derived scorecard:
- ``table``: a colour-coded Rich table (default, for humans at a terminal).
- ``json``: the full ``Report`` plus a derived ``scorecard`` block (the baseline format).
- ``md``: the scorecard table plus a per-tool, per-framework difference list (for writeups).
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .models import Category, Report
from .scorecard import JOBS, MAIN_JOB, SEVERITY, build_scorecard

CATEGORY_COLOR: dict[Category, str] = {
    "faithful": "green",
    "lossy": "red",
    "transformative": "yellow",
    "additive": "magenta",
}

JOB_VERDICT_COLOR = {"pass": "green", "degraded": "yellow", "fail": "red"}


def _job_grid(findings):
    """Return (job_ids, frameworks, cells, titles) for a job x framework grid."""
    job_ids: list[str] = []
    frameworks: list[str] = []
    cells: dict = {}
    titles: dict = {}
    for f in findings:
        if f.job_id not in titles:
            titles[f.job_id] = f.title
            job_ids.append(f.job_id)
        if f.framework not in frameworks:
            frameworks.append(f.framework)
        cells[(f.job_id, f.framework)] = f
    return job_ids, frameworks, cells, titles


def report_to_dict(report: Report, jobs_filter: list[str] | None = None) -> dict[str, Any]:
    """Full report plus derived scorecard, JSON-serializable (the baseline shape)."""

    data = report.model_dump(mode="json", by_alias=True)
    scorecard = build_scorecard(report)
    if jobs_filter:
        scorecard = _filter_scorecard(scorecard, jobs_filter)
    data["scorecard"] = scorecard
    return data


def _filter_scorecard(scorecard: dict[str, Any], jobs_filter: list[str]) -> dict[str, Any]:
    keep = {j.upper() for j in jobs_filter}
    # D4: authorization legibility remains visible even when the caller narrows
    # the other scorecard columns.
    keep.add("J5")
    scorecard = dict(scorecard)
    scorecard["jobs"] = [j for j in scorecard["jobs"] if j["id"] in keep]
    frameworks = {}
    for name, fw in scorecard["frameworks"].items():
        fw = dict(fw)
        fw["jobs"] = {jid: cell for jid, cell in fw["jobs"].items() if jid in keep}
        frameworks[name] = fw
    scorecard["frameworks"] = frameworks
    return scorecard


def _header(report: Report) -> str:
    n = len(report.tools)
    return (
        f"mcp-mirror, server: {report.mcp_server}, "
        f"source-negotiated MCP spec: {report.mcp_spec_version}, "
        f"{n} tool{'s' if n != 1 else ''}"
    )


def _evidence_line(run) -> str | None:
    evidence = run.evidence
    if evidence is None:
        return None
    provider_request = "captured" if evidence.provider_request_captured else "not captured"
    adapter_spec = evidence.negotiated_mcp_spec_version or "not exposed"
    stage = evidence.capture_stage.replace("_", " ")
    return (
        f"{evidence.capture_api} -> {evidence.capture_object} ({stage}); "
        f"provider request: {provider_request}; "
        f"adapter-negotiated MCP spec: {adapter_spec}"
    )


def _observation_hash(run) -> str | None:
    if not run.observations:
        return None
    return run.observations[-1].artifact_sha256


def _status_label(status: str) -> str:
    return status.replace("_", " ")


def _reproduction_command(report: Report) -> str | None:
    if report.scan is None:
        return None

    args = ["mcp-mirror", "scan", report.mcp_server]
    if report.scan.frameworks:
        args.extend(["--frameworks", ",".join(report.scan.frameworks)])
    if report.scan.runner_mode == "managed":
        args.extend(["--runner", "managed"])
    args.extend(
        [
            "--spec-version",
            report.scan.spec_version_assertion or report.mcp_spec_version,
        ]
    )
    if report.scan.jobs:
        args.extend(["--job", ",".join(report.scan.jobs)])
    if report.scan.jtbd:
        args.extend(["--jtbd", report.scan.jtbd])
    for name in report.scan.header_names:
        env_name = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
        args.extend(["--header", f"{name}: ${{{env_name}}}"])
    args.extend(
        [
            "--fail-on-incomplete",
            "--out",
            "mcp-mirror-report.json",
        ]
    )
    return shlex.join(args)


def render_table(report: Report, console: Console, jobs_filter: list[str] | None = None) -> None:
    scorecard = build_scorecard(report)
    if jobs_filter:
        scorecard = _filter_scorecard(scorecard, jobs_filter)

    console.print(Text(_header(report), style="bold"))
    console.print(f"generated with {report.generated_with}", style="dim")
    reproduction_command = _reproduction_command(report)
    if reproduction_command:
        console.print(
            f"reproduce: {reproduction_command}",
            style="dim",
            soft_wrap=True,
        )
    if report.source_observation:
        console.print(
            f"source evidence sha256:{report.source_observation.artifact_sha256}",
            style="dim",
        )
    console.print(Text(MAIN_JOB, style="italic dim"))
    if report.runs:
        console.print(Text("\nCapture boundaries", style="bold"))
        for run in report.runs:
            if run.status != "measured":
                detail = f": {run.status_detail}" if run.status_detail else ""
                console.print(
                    escape(
                        f"  {run.framework}: {_status_label(run.status)}{detail}"
                    ),
                    style="yellow",
                )
            line = _evidence_line(run)
            if line:
                console.print(f"  {run.framework}: {line}")
            if run.runner_digest:
                console.print(
                    f"    runner manifest sha256:{run.runner_digest}",
                    style="dim",
                )
            observation_hash = _observation_hash(run)
            if observation_hash:
                console.print(
                    f"    evidence sha256:{observation_hash}",
                    style="dim",
                )
            if run.evidence and run.evidence.limitation:
                console.print(
                    f"    limitation: {run.evidence.limitation}",
                    style="dim",
                )

    table = Table(show_lines=False, header_style="bold")
    table.add_column("framework", style="bold cyan", no_wrap=True)
    for job in scorecard["jobs"]:
        table.add_column(f"{job['id']} {job['label']}", justify="left")

    if not scorecard["frameworks"]:
        console.print(table)
        console.print(
            "no frameworks scanned; run 'mcp-mirror frameworks' for local "
            "setup, or select frameworks with --runner managed",
            style="yellow",
            markup=False,
        )
        return

    for name, fw in scorecard["frameworks"].items():
        row = [Text(f"{name}\n{fw['framework_version']}", style="bold cyan")]
        for job in scorecard["jobs"]:
            cell = fw["jobs"][job["id"]]
            row.append(_cell_text(cell["verdict"], cell["count"]))
        table.add_row(*row)

    console.print(table)

    flagged = [
        (name, fw["authz_flags"]) for name, fw in scorecard["frameworks"].items() if fw["authz_flags"]
    ]
    if flagged:
        console.print(Text("\nJ5 authorization findings", style="bold red"))
        for name, flags in flagged:
            for flag in flags:
                console.print(f"  {name}: {flag}", style="red")

    if report.job_findings:
        job_ids, fws, cells, titles = _job_grid(report.job_findings)
        console.print(
            Text(
                "\nJobs-To-Be-Done  "
                "(does the captured framework definition still satisfy the job?)",
                style="bold",
            )
        )
        jt = Table(show_lines=False, header_style="bold")
        jt.add_column("job", style="cyan")
        for fw in fws:
            jt.add_column(fw, justify="left")
        for jid in job_ids:
            row = [Text(jid, style="cyan")]
            for fw in fws:
                cell = cells.get((jid, fw))
                verdict = cell.verdict if cell else "-"
                row.append(Text(verdict, style=JOB_VERDICT_COLOR.get(verdict, "white")))
            jt.add_row(*row)
        console.print(jt)
        for jid in job_ids:
            for fw in fws:
                cell = cells.get((jid, fw))
                if cell and cell.verdict != "pass":
                    for reason in cell.reasons:
                        console.print(f"  [{JOB_VERDICT_COLOR[cell.verdict]}]{jid} / {fw}:[/] {reason}")


def _cell_text(verdict: Category, count: int) -> Text:
    label = verdict if count == 0 else f"{verdict} ({count})"
    return Text(label, style=CATEGORY_COLOR.get(verdict, "white"))


def render_markdown(report: Report, jobs_filter: list[str] | None = None) -> str:
    scorecard = build_scorecard(report)
    if jobs_filter:
        scorecard = _filter_scorecard(scorecard, jobs_filter)

    lines: list[str] = []
    lines.append(f"# {_header(report)}")
    lines.append("")
    lines.append(f"_generated with {report.generated_with}_")
    lines.append("")
    reproduction_command = _reproduction_command(report)
    if reproduction_command:
        lines.append(f"**Reproduce:** `{reproduction_command}`")
        lines.append("")
    if report.source_observation:
        lines.append(
            f"**Source evidence:** `sha256:{report.source_observation.artifact_sha256}`"
        )
        lines.append("")
    lines.append(f"**The job:** {MAIN_JOB}")
    lines.append("")
    lines.append(
        "_Categories show what each framework **changed**, not whether it got worse. "
        "Lossy or transformative can still help the agent. Judge genuine compliance "
        "failures: a dropped required arg, a lost enum, a destroyed authorization signal._"
    )
    lines.append("")

    jobs = scorecard["jobs"]
    lines.append("## Scorecard")
    lines.append("")
    lines.append("| framework | version | " + " | ".join(f"{j['id']} {j['label']}" for j in jobs) + " |")
    lines.append("|" + "---|" * (len(jobs) + 2))
    for name, fw in scorecard["frameworks"].items():
        cells = []
        for job in jobs:
            cell = fw["jobs"][job["id"]]
            cells.append(cell["verdict"] if cell["count"] == 0 else f"{cell['verdict']} ({cell['count']})")
        lines.append(f"| {name} | `{fw['framework_version']}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("### Jobs")
    lines.append("")
    for job in jobs:
        lines.append(f"- **{job['id']}** ({job['label']}): {JOBS[job['id']]['title']}")
    lines.append("")

    lines.append("## J5 authorization findings")
    lines.append("")
    authz_findings = [
        (name, flag)
        for name, framework in scorecard["frameworks"].items()
        for flag in framework["authz_flags"]
    ]
    if authz_findings:
        for name, flag in authz_findings:
            lines.append(f"- **{name}:** {flag}")
    else:
        lines.append("_No authorization-signal differences at the declared capture boundaries._")
    lines.append("")

    if report.job_findings:
        job_ids, fws, cells, titles = _job_grid(report.job_findings)
        lines.append("## Jobs-To-Be-Done")
        lines.append("")
        lines.append(
            "_Does the captured framework definition still satisfy the job? "
            "pass = its needs survived, degraded = weakened, "
            "fail = a needed tool or parameter did not survive adaptation._"
        )
        lines.append("")
        lines.append("| job | " + " | ".join(fws) + " |")
        lines.append("|" + "---|" * (len(fws) + 1))
        for jid in job_ids:
            row = [(cells[(jid, fw)].verdict if (jid, fw) in cells else "-") for fw in fws]
            lines.append(f"| {jid} | " + " | ".join(row) + " |")
        lines.append("")
        for jid in job_ids:
            lines.append(f"- **{jid}**, {titles[jid]}")
            for fw in fws:
                cell = cells.get((jid, fw))
                if cell and cell.verdict != "pass":
                    lines.append(f"  - {fw}: **{cell.verdict}**, " + "; ".join(cell.reasons))
        lines.append("")

    lines.append("## Differences by framework")
    lines.append("")
    for run in report.runs:
        lines.append(f"### {run.framework} (`{run.framework_version}`)")
        lines.append("")
        if run.status != "measured":
            lines.append(f"**Status:** {_status_label(run.status)}.")
            if run.status_detail:
                lines.append("")
                lines.append(run.status_detail)
            lines.append("")
        if run.runner_digest:
            lines.append(
                f"**Runner manifest:** `sha256:{run.runner_digest}`"
            )
            lines.append("")
        evidence_line = _evidence_line(run)
        if evidence_line:
            lines.append(f"**Capture boundary:** {evidence_line}.")
            observation_hash = _observation_hash(run)
            if observation_hash:
                lines.append("")
                lines.append(f"**Evidence:** `sha256:{observation_hash}`")
            if run.evidence and run.evidence.limitation:
                lines.append("")
                lines.append(f"**Limitation:** {run.evidence.limitation}")
            lines.append("")
        if run.status != "measured":
            continue
        if not run.differences:
            lines.append("_fully faithful, no differences._")
            lines.append("")
            continue
        by_tool: dict[str, list] = {}
        for diff in run.differences:
            by_tool.setdefault(diff.tool, []).append(diff)
        for tool, diffs in by_tool.items():
            lines.append(f"**{tool}**")
            lines.append("")
            lines.append("| category | dimension | path | detail |")
            lines.append("|---|---|---|---|")
            for d in diffs:
                detail = d.detail.replace("|", "\\|")
                lines.append(f"| {d.category} | {d.dimension} | `{d.path}` | {detail} |")
            lines.append("")
    return "\n".join(lines)


def compare_baseline(current: Report, baseline: Report) -> tuple[bool, list[str]]:
    """Compare a fresh report to a saved baseline (DESIGN.md section 13).

    Returns ``(drift_detected, messages)``. Drift if the spec version differs, a new
    difference appears, or any category worsens for an existing path.
    """

    messages: list[str] = []
    if current.mcp_spec_version != baseline.mcp_spec_version:
        return True, [
            "spec version mismatch: baseline "
            f"{baseline.mcp_spec_version!r} vs current {current.mcp_spec_version!r} "
            "(baselines are only comparable within one spec version)"
        ]

    incomplete_baseline = sorted(
        run.framework for run in baseline.runs if run.status != "measured"
    )
    if incomplete_baseline:
        return True, [
            "baseline is incomplete for "
            f"{', '.join(incomplete_baseline)}; re-record it before comparing, "
            "because a framework that was never measured cannot establish the "
            "equivalence this comparison would claim"
        ]

    baseline_runs = {run.framework: run for run in baseline.runs}
    current_runs = {run.framework: run for run in current.runs}
    drift = False

    # The scanner and its interpreter are part of the capture boundary: a diff
    # taken by different code on a different runtime is not the same experiment.
    for field, label in (
        ("scanner_version", "scanner version"),
        ("python_version", "Python version"),
        ("platform", "platform"),
    ):
        baseline_value = (
            getattr(baseline.provenance, field) if baseline.provenance else None
        )
        current_value = (
            getattr(current.provenance, field) if current.provenance else None
        )
        if baseline_value != current_value and (baseline_value or current_value):
            drift = True
            messages.append(
                f"ENVIRONMENT {label} changed: {baseline_value} -> {current_value}"
            )

    baseline_source_digest = (
        baseline.provenance.runner_digest
        if baseline.provenance is not None
        else None
    )
    current_source_digest = (
        current.provenance.runner_digest
        if current.provenance is not None
        else None
    )
    if (
        current_source_digest != baseline_source_digest
        and (
            baseline_source_digest is not None
            or current_source_digest is not None
        )
    ):
        drift = True
        messages.append(
            "ENVIRONMENT source runner changed: "
            f"{baseline_source_digest} -> {current_source_digest}"
        )

    for framework in sorted(set(baseline_runs) - set(current_runs)):
        drift = True
        messages.append(f"INCOMPLETE [{framework}] missing framework run")

    for framework, run in sorted(current_runs.items()):
        if run.status == "measured":
            continue
        drift = True
        detail = f": {run.status_detail}" if run.status_detail else ""
        messages.append(
            f"INCOMPLETE [{framework}] {run.status}{detail}"
        )

    for framework in sorted(set(baseline_runs) & set(current_runs)):
        if current_runs[framework].status != "measured":
            continue
        baseline_run = baseline_runs[framework]
        current_run = current_runs[framework]
        if current_run.framework_version != baseline_run.framework_version:
            drift = True
            messages.append(
                f"ENVIRONMENT [{framework}] framework version changed: "
                f"{baseline_run.framework_version} -> "
                f"{current_run.framework_version}"
            )
        if current_run.adapter_version != baseline_run.adapter_version and (
            baseline_run.adapter_version is not None
            or current_run.adapter_version is not None
        ):
            drift = True
            messages.append(
                f"ENVIRONMENT [{framework}] adapter version changed: "
                f"{baseline_run.adapter_version} -> "
                f"{current_run.adapter_version}"
            )
        if (
            current_run.runner_digest != baseline_run.runner_digest
            and (
                baseline_run.runner_digest is not None
                or current_run.runner_digest is not None
            )
        ):
            drift = True
            messages.append(
                f"ENVIRONMENT [{framework}] runner manifest changed: "
                f"{baseline_run.runner_digest} -> "
                f"{current_run.runner_digest}"
            )

        baseline_evidence = baseline_run.evidence
        current_evidence = current_run.evidence
        # Two legacy reports without renderer evidence retain the v0.1 baseline
        # behavior. A mixed old/new comparison fails closed because equivalence
        # cannot be established.
        if baseline_evidence is None and current_evidence is None:
            continue
        baseline_version = (
            baseline_evidence.negotiated_mcp_spec_version
            if baseline_evidence
            else None
        )
        current_version = (
            current_evidence.negotiated_mcp_spec_version
            if current_evidence
            else None
        )
        if not baseline_version or not current_version:
            return True, [
                f"renderer MCP spec unavailable for {framework!r}: "
                f"baseline {baseline_version!r} vs current {current_version!r}; "
                "cannot compare adapter outputs across an unknown protocol boundary"
            ]
        if current_version != baseline_version:
            return True, [
                f"renderer MCP spec mismatch for {framework!r}: "
                f"baseline {baseline_version!r} vs current {current_version!r}"
            ]

        # Reaching here means both evidences exist. An adapter that moved to a
        # different capture object, or stopped serializing the provider request,
        # changed what the diff is evidence of even when the diff itself is
        # unchanged.
        for field, label in (
            ("capture_stage", "capture stage"),
            ("capture_api", "capture API"),
            ("capture_object", "capture object"),
            ("provider_request_captured", "provider request capture"),
        ):
            baseline_value = getattr(baseline_evidence, field)
            current_value = getattr(current_evidence, field)
            if baseline_value != current_value:
                drift = True
                messages.append(
                    f"ENVIRONMENT [{framework}] {label} changed: "
                    f"{baseline_value!r} -> {current_value!r}"
                )

    baseline_index = _index(baseline)
    current_index = _index(current)

    for key, category in current_index.items():
        framework, tool, path, dimension = key
        if key not in baseline_index:
            drift = True
            messages.append(f"NEW [{framework}] {tool} {path} ({dimension}): {category}")
        elif SEVERITY[category] > SEVERITY[baseline_index[key]]:
            drift = True
            messages.append(
                f"WORSE [{framework}] {tool} {path} ({dimension}): "
                f"{baseline_index[key]} -> {category}"
            )

    if not drift:
        messages.append("no drift: current report is no worse than baseline")
    return drift, messages


def _index(report: Report) -> dict[tuple[str, str, str, str], Category]:
    index: dict[tuple[str, str, str, str], Category] = {}
    for run in report.runs:
        for diff in run.differences:
            index[(diff.framework, diff.tool, diff.path, diff.dimension)] = diff.category
    return index
