"""Reporters and the regression baseline comparison (DESIGN.md sections 11, 13).

Three output formats share one derived scorecard:
- ``table``: a colour-coded Rich table (default, for humans at a terminal).
- ``json``: the full ``Report`` plus a derived ``scorecard`` block (the baseline format).
- ``md``: the scorecard table plus a per-tool, per-framework difference list (for writeups).
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
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

    data = report.model_dump(mode="json")
    scorecard = build_scorecard(report)
    if jobs_filter:
        scorecard = _filter_scorecard(scorecard, jobs_filter)
    data["scorecard"] = scorecard
    return data


def _filter_scorecard(scorecard: dict[str, Any], jobs_filter: list[str]) -> dict[str, Any]:
    keep = {j.upper() for j in jobs_filter}
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


def render_table(report: Report, console: Console, jobs_filter: list[str] | None = None) -> None:
    scorecard = build_scorecard(report)
    if jobs_filter:
        scorecard = _filter_scorecard(scorecard, jobs_filter)

    console.print(Text(_header(report), style="bold"))
    console.print(f"generated with {report.generated_with}", style="dim")
    console.print(Text(MAIN_JOB, style="italic dim"))
    if report.runs:
        console.print(Text("\nCapture boundaries", style="bold"))
        for run in report.runs:
            line = _evidence_line(run)
            if line:
                console.print(f"  {run.framework}: {line}")
                if run.evidence and run.evidence.limitation:
                    console.print(f"    limitation: {run.evidence.limitation}", style="dim")

    table = Table(show_lines=False, header_style="bold")
    table.add_column("framework", style="bold cyan", no_wrap=True)
    for job in scorecard["jobs"]:
        table.add_column(f"{job['id']} {job['label']}", justify="left")

    if not scorecard["frameworks"]:
        console.print(table)
        console.print("no frameworks scanned (install renderers, e.g. pip install 'mcp-mirror[all]')", style="yellow")
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
        evidence_line = _evidence_line(run)
        if evidence_line:
            lines.append(f"**Capture boundary:** {evidence_line}.")
            if run.evidence and run.evidence.limitation:
                lines.append("")
                lines.append(f"**Limitation:** {run.evidence.limitation}")
            lines.append("")
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

    baseline_runs = {run.framework: run for run in baseline.runs}
    current_runs = {run.framework: run for run in current.runs}
    for framework in sorted(set(baseline_runs) & set(current_runs)):
        baseline_evidence = baseline_runs[framework].evidence
        current_evidence = current_runs[framework].evidence
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

    baseline_index = _index(baseline)
    current_index = _index(current)

    drift = False
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
