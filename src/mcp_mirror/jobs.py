"""Per-provider Jobs-To-Be-Done (DESIGN.md section 10, team-review revision).

A job declares what a real task *needs* from the tools. mcp-mirror then checks,
deterministically, whether each framework's rendering still exposes it. This is the
"does the job still work" layer on top of the raw diff:

- ``pass``     the job's needs survived (even if the framework dropped other things).
- ``degraded`` something aiding correctness or safety was weakened (a lost constraint,
               a risk hint retained outside the captured definition).
- ``fail``     a needed tool or param did not survive to the capture boundary.

It is deterministic and compliance-flavored: it measures whether the rendering *exposes*
what the job requires, never whether the result is "better" (intent is not measured).
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Job, JobFinding, JobSpec, ToolRep
from .schema import effective_schema

_SPEC_DIR = Path(__file__).parent / "job_specs"
_EXTS = (".yaml", ".yml", ".json")


def list_bundled_providers() -> list[str]:
    if not _SPEC_DIR.exists():
        return []
    return sorted({p.stem for p in _SPEC_DIR.iterdir() if p.suffix in _EXTS and p.stem != "example"})


def load_jobs(spec: str) -> JobSpec:
    """Load a job spec from a file path, or by bundled provider name (e.g. ``filesystem``)."""

    path = Path(spec)
    if not path.exists():
        for ext in _EXTS:
            candidate = _SPEC_DIR / f"{spec}{ext}"
            if candidate.exists():
                path = candidate
                break
        else:
            providers = ", ".join(list_bundled_providers()) or "none"
            raise FileNotFoundError(
                f"no job spec at {spec!r} and no bundled provider by that name "
                f"(bundled: {providers})"
            )

    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("pyyaml is required to read YAML job specs") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return JobSpec.model_validate(data)


def _match(tool_name: str, reps: list[ToolRep]) -> ToolRep | None:
    """Find the rendered tool for a source tool name, tolerating namespacing/prefixing."""

    for rep in reps:
        if rep.name == tool_name:
            return rep
    candidates = [
        rep for rep in reps
        if rep.name and (rep.name.endswith(tool_name) or tool_name in rep.name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _properties(rep: ToolRep) -> dict:
    props = (rep.params or {}).get("properties")
    return props if isinstance(props, dict) else {}


def _required(rep: ToolRep) -> set:
    return set((rep.params or {}).get("required") or [])


def evaluate_job(job: Job, reps: list[ToolRep]) -> tuple[str, list[str]]:
    """Evaluate one job against one set of rendered tools. Returns (verdict, reasons)."""

    fails: list[str] = []
    degrades: list[str] = []

    for req in job.requires:
        rep = _match(req.tool, reps)
        if rep is None:
            fails.append(f"tool {req.tool!r} absent at the capture boundary")
            continue

        props = _properties(rep)
        for param in req.params:
            if param not in props:
                fails.append(
                    f"{req.tool}: required param {param!r} absent at the capture boundary"
                )

        req_set = _required(rep)
        for param in req.required_params:
            if param not in req_set:
                degrades.append(f"{req.tool}: {param!r} is no longer marked required")

        for param, keys in req.constraints.items():
            sub = props.get(param)
            # Normalize optional (anyOf:[X, null]) and $ref wrappers so a constraint one
            # level down (as a framework's Pydantic schema serializes it) is not falsely
            # reported as lost.
            sub = effective_schema(sub, rep.params or {}) if isinstance(sub, dict) else {}
            sub = sub if isinstance(sub, dict) else {}
            for key in keys:
                if key not in sub:
                    degrades.append(f"{req.tool}: constraint {key!r} on {param!r} was lost")

        # Three fates for a required safety signal, mirroring the diff engine:
        #   present at capture boundary -> requirement met
        #   retained elsewhere          -> degraded (a policy layer could still gate)
        #   destroyed (no trace)        -> fail
        captured = rep.annotations or {}
        retained = (rep.framework_metadata or {}).get("annotations") or {}
        for ann in req.annotations:
            if ann in captured:
                continue
            if ann in retained:
                degrades.append(
                    f"{req.tool}: {ann!r} is retained in framework metadata but absent "
                    "from the captured tool definition (a policy layer could still gate on it)"
                )
            else:
                fails.append(
                    f"{req.tool}: {ann!r} is destroyed; neither the captured definition "
                    "nor retained framework metadata contains it"
                )

    if fails:
        return "fail", fails + degrades
    if degrades:
        return "degraded", degrades
    return "pass", []


def evaluate_jobs(
    spec: JobSpec,
    source_reps: list[ToolRep],
    runs: dict[str, list[ToolRep]],
) -> tuple[list[JobFinding], list[str]]:
    """Evaluate every job against the source (spec sanity) and each framework's reps.

    ``runs`` maps framework id -> rendered ToolReps. Returns (findings, spec_warnings).
    A job that the *source* server cannot satisfy is a spec problem (wrong tool/param
    name), surfaced as a warning rather than blamed on a framework.
    """

    findings: list[JobFinding] = []
    warnings: list[str] = []

    for job in spec.jobs:
        src_verdict, src_reasons = evaluate_job(job, source_reps)
        if src_verdict == "fail":
            warnings.append(
                f"job {job.id!r} does not match the source server, likely a spec issue: "
                + "; ".join(src_reasons)
            )
        for framework, reps in runs.items():
            verdict, reasons = evaluate_job(job, reps)
            findings.append(
                JobFinding(
                    job_id=job.id,
                    title=job.title,
                    framework=framework,
                    verdict=verdict,
                    reasons=reasons,
                )
            )

    return findings, warnings
