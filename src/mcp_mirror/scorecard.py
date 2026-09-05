"""Jobs-To-Be-Done aggregation (DESIGN.md sections 10-11).

The scorecard is the organizing lens: frameworks as rows, Jobs as columns. Each
cell is the worst category seen across that job's dimensions plus a count. It is
*derived* from a ``Report`` (DESIGN.md section 6) and never stored on it.
"""

from __future__ import annotations

from typing import Any

from .models import Category, Difference, Dimension, Report

# The overarching job mcp-mirror serves. Every column below is one measurable
# outcome under it. Jobs-To-Be-Done done properly: the job is stated in its
# circumstance, and the technical dimensions are how we measure whether it is met.
MAIN_JOB = (
    "When I publish one MCP server and developers reach it through different agent "
    "frameworks, my tools should survive each framework's published adaptation "
    "faithfully, so the server's contract does not silently change."
)

# IMPORTANT framing (from the team review): these categories measure what each framework
# CHANGED, not whether it got worse. A lossy or transformative rendering can still serve
# the agent better (less context, tighter schema). Read the scorecard as "what differs
# across frameworks," and reserve judgement for genuine compliance failures: a dropped
# required arg, a lost enum, a destroyed authorization signal. Fidelity is the spine.
# Authorization (J5) is the single highest-stakes job, not the whole story.
JOB_ORDER = ["J1", "J2", "J3", "J4", "J5"]

JOBS: dict[str, dict[str, Any]] = {
    "J5": {
        "label": "authz",
        "title": (
            "When a tool is adapted, structured danger and scope signals remain at the "
            "declared capture boundary or in explicit retained metadata."
        ),
        "dimensions": {Dimension.ANNOTATION, Dimension.AUTHZ},
    },
    "J1": {
        "label": "desc",
        "title": (
            "When a tool is adapted, its full description remains in the captured "
            "definition so downstream consumers retain the author's intent."
        ),
        "dimensions": {Dimension.DESCRIPTION},
    },
    "J2": {
        "label": "params",
        "title": (
            "When a tool is adapted, its parameter contract (types, required, enums, "
            "formats) remains intact at the capture boundary."
        ),
        "dimensions": {Dimension.PARAM_TYPE, Dimension.CONSTRAINT, Dimension.REQUIRED},
    },
    "J3": {
        "label": "struct",
        "title": (
            "When a tool takes nested or structured input, that structure survives "
            "adaptation so complex calls do not silently degrade."
        ),
        "dimensions": {Dimension.STRUCTURE},
    },
    "J4": {
        "label": "inject",
        "title": (
            "At the capture boundary, a tool carries nothing the author did not write, "
            "so framework-injected text and phantom tools stay visible as changes."
        ),
        "dimensions": {Dimension.INJECTION},
    },
}

# "Worst" ordering used to pick a cell verdict. Lossy outranks transformative
# outranks additive outranks faithful. For J4 the only category present is
# additive by construction, so this ordering never mislabels an injection job.
SEVERITY: dict[Category, int] = {
    "faithful": 0,
    "additive": 1,
    "transformative": 2,
    "lossy": 3,
}

# Annotation keys that carry authorization meaning (title is a display hint, not one).
AUTHZ_ANNOTATION_KEYS = {"destructiveHint", "readOnlyHint", "openWorldHint", "idempotentHint"}


def _dimension_to_job(dimension: str) -> str | None:
    for job_id, spec in JOBS.items():
        if dimension in spec["dimensions"]:
            return job_id
    return None


def _cell(differences: list[Difference]) -> dict[str, Any]:
    if not differences:
        return {"verdict": "faithful", "count": 0, "details": []}
    verdict = max((d.category for d in differences), key=lambda c: SEVERITY[c])
    return {
        "verdict": verdict,
        "count": len(differences),
        "details": [d.detail for d in differences],
    }


def build_scorecard(report: Report) -> dict[str, Any]:
    """Aggregate a report into per-framework, per-job verdicts.

    Returns a JSON-serializable structure with a ``frameworks`` map and the list of
    jobs (so reporters and regression baselines share one shape).
    """

    frameworks: dict[str, Any] = {}
    for run in report.runs:
        by_job: dict[str, list[Difference]] = {job_id: [] for job_id in JOB_ORDER}
        for diff in run.differences:
            job_id = _dimension_to_job(diff.dimension)
            if job_id is None:
                continue
            # title (and any other display-only annotation) is a real annotation
            # difference, but it is not an authorization signal, so it must not pad J5.
            if job_id == "J5" and diff.dimension == Dimension.ANNOTATION:
                key = diff.path.rsplit(".", 1)[-1]
                if key not in AUTHZ_ANNOTATION_KEYS:
                    continue
            by_job[job_id].append(diff)

        job_cells = {job_id: _cell(by_job[job_id]) for job_id in JOB_ORDER}
        worst = max(
            (cell["verdict"] for cell in job_cells.values()),
            key=lambda c: SEVERITY[c],
            default="faithful",
        )
        frameworks[run.framework] = {
            "framework_version": run.framework_version,
            "adapter_version": run.adapter_version,
            "jobs": job_cells,
            "worst": worst,
            "total_differences": len(run.differences),
            "authz_flags": _authz_flags(run.differences),
        }

    return {
        "jobs": [
            {"id": job_id, "label": JOBS[job_id]["label"], "title": JOBS[job_id]["title"]}
            for job_id in JOB_ORDER
        ],
        "frameworks": frameworks,
    }


def _authz_flags(differences: list[Difference]) -> list[str]:
    """Human-readable J5 notes for the scorecard, limited to authorization signals.

    Filters out non-authz annotation noise (e.g. ``title``) and surfaces both the
    dangerous case (destroyed) and the retained-but-absent case.
    """

    flags: list[str] = []
    for diff in differences:
        if diff.category == "faithful":
            continue
        if diff.dimension == Dimension.AUTHZ:
            flags.append(f"{diff.tool}: {diff.detail}")
        elif diff.dimension == Dimension.ANNOTATION:
            key = diff.path.rsplit(".", 1)[-1]
            if key in AUTHZ_ANNOTATION_KEYS:
                flags.append(f"{diff.tool}: {diff.detail}")
    return flags
