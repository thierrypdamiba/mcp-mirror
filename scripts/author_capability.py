"""Author a capability file for either protocol snapshot from a measurement.

At 2026-07-28 every capability repeats the same three rows: CrewAI, LangChain and
Mastra cannot negotiate the revision, so their cells are always ``x`` with the same
evidence. Writing those by hand 47 times invites drift in exactly the text that has to
stay identical, and the note numbering has to follow framework reading order or the
markers on the site point at the wrong note.

At 2025-11-25 nothing is blocked, so all five adapters are supplied per feature. Either
way the caller provides only the reachable adapters; everything else is derived from
the surface catalog and, where it exists, the attempts file.

Usage is programmatic; see ``scripts/measure_*.py`` for callers.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Reading order on the site. Note markers are numbered in this order, so a cell's
# ``#n`` matches the position of its note in the rendered list.
FRAMEWORK_ORDER = ["crewai", "langchain", "openai-agents", "pydantic-ai", "mastra"]

CODES_NEEDING_NOTE = {"a", "n", "x"}

# The current snapshot lives under data/specs/<revision>/; the baseline one is the
# repository's default and lives at the top of data/. Which adapters can reach the
# revision is a property of the snapshot, not of any single feature.
SPECS = {
    "2026-07-28": {
        "dir": ROOT / "data" / "specs" / "2026-07-28",
        "live": ("openai-agents", "pydantic-ai"),
    },
    "2025-11-25": {
        "dir": ROOT / "data",
        "live": tuple(FRAMEWORK_ORDER),
    },
}

DEFAULT_SPEC = "2026-07-28"

# Reproduce commands run from a source checkout. There is no published mcp-mirror
# package, and even once there is, `uv run` is what pins the adapter versions a cell
# was measured at: the managed runner reads runner-manifests.json, while a local
# install resolves to whatever uv.lock happens to hold.
MANAGED_FRAMEWORKS = {
    "2025-11-25": "crewai,langchain,openai_agents,pydantic_ai",
    "2026-07-28": "openai_agents,pydantic_ai",
}

# Each renderer spawns the fixture itself, so the server command decides which
# revision gets negotiated. At 2026-07-28 the renderer environments already carry the
# 2.x SDK, so the ambient interpreter is the right one. At 2025-11-25 that same
# interpreter would negotiate 2026-07-28 and the scan would refuse the cross-version
# diff, so the fixture is run in the project environment, whose SDK is 1.x.
FIXTURE_COMMAND = {
    "2025-11-25": "uv run python",
    "2026-07-28": "python",
}


def reproduce_command(
    spec: str,
    job: str,
    fixture: str = "fixtures/tricky_server.py",
) -> str:
    """The from-source scan that reproduces one snapshot's cells for one job."""

    if spec not in MANAGED_FRAMEWORKS:
        raise ValueError(f"unknown spec {spec!r}; expected one of {sorted(MANAGED_FRAMEWORKS)}")
    return (
        f'uv run mcp-mirror scan "{FIXTURE_COMMAND[spec]} {fixture}"'
        f" --runner managed --frameworks {MANAGED_FRAMEWORKS[spec]}"
        f" --spec-version {spec} --job {job}"
    )


def _spec_dir(spec: str) -> Path:
    if spec not in SPECS:
        raise ValueError(f"unknown spec {spec!r}; expected one of {sorted(SPECS)}")
    return SPECS[spec]["dir"]


def _surface(spec: str) -> dict[str, dict]:
    features = json.loads((_spec_dir(spec) / "surface.json").read_text())["features"]
    return {feature["id"]: feature for feature in features}


def _blocked(spec: str) -> dict[str, dict]:
    """The blocked adapters and the evidence for each, from the attempts record.

    A snapshot every adapter can negotiate has no attempts file, and nothing is
    blocked, so the absence is the answer rather than a missing input.
    """

    attempts_path = _spec_dir(spec) / "attempts.json"
    if not attempts_path.exists():
        return {}

    attempts = json.loads(attempts_path.read_text())["attempts"]
    frameworks = json.loads((_spec_dir(spec) / "frameworks.json").read_text())["agents"]
    blocked = {}
    for framework_id, attempt in attempts.items():
        blocked[framework_id] = {
            "version": frameworks[framework_id]["current_version"],
            "note": frameworks[framework_id].get("measurement_note")
            or attempt.get("evidence", ""),
        }
    return blocked


def write_capability(
    feature_id: str,
    *,
    codes: dict[str, str],
    notes: dict[str, str],
    summary: str,
    verdict_code: str,
    verdict_headline: str,
    verdict_detail: str,
    run_date: str,
    spec: str = DEFAULT_SPEC,
    job: str = "J5",
    fixture: str = "fixtures/tricky_server.py",
    reproduce: str | None = None,
    known_issues: list | None = None,
    boundary_dependent: list[str] | None = None,
) -> Path:
    """Write one capability file and return its path.

    ``codes`` and ``notes`` cover only the adapters that can reach ``spec``. A ``y``
    cell needs no note; anything else does, and a missing one is an error rather than a
    silent gap.

    ``boundary_dependent`` names the adapters whose answer here changes with which
    result boundary you look at. Those cells must be ``a``: the value is not present
    unchanged, and the note has to say what each boundary yields.
    """

    spec_dir = _spec_dir(spec)
    feature = _surface(spec)[feature_id]
    blocked = _blocked(spec)

    for framework_id in SPECS[spec]["live"]:
        if framework_id not in codes:
            raise ValueError(f"{feature_id}: no code for {framework_id}")
        if codes[framework_id] in CODES_NEEDING_NOTE and not notes.get(framework_id):
            raise ValueError(f"{feature_id}: {framework_id} is {codes[framework_id]!r} with no note")

    for framework_id in boundary_dependent or []:
        if framework_id not in FRAMEWORK_ORDER:
            raise ValueError(f"{feature_id}: unknown boundary_dependent framework {framework_id!r}")
        if codes.get(framework_id) != "a":
            raise ValueError(
                f"{feature_id}: {framework_id} is boundary-dependent, so its cell must "
                f"be 'a', not {codes.get(framework_id)!r}"
            )

    versions = json.loads((spec_dir / "frameworks.json").read_text())["agents"]
    stats: dict[str, dict[str, str]] = {}
    notes_by_num: dict[str, str] = {}
    counter = 0

    for framework_id in FRAMEWORK_ORDER:
        version = versions[framework_id]["current_version"]
        if framework_id in blocked:
            code, note = "x", blocked[framework_id]["note"]
        else:
            code, note = codes[framework_id], notes.get(framework_id, "")
        if code in CODES_NEEDING_NOTE:
            counter += 1
            notes_by_num[str(counter)] = note
            cell = f"{code} #{counter}"
        else:
            cell = code
        stats[framework_id] = {version: cell}

    payload = {
        "schema": "mcp-mirror/capability@3",
        "id": feature_id,
        "title": feature["title"],
        "description": feature["description"],
        "question": feature["question"],
        "spec": feature["spec"],
        "status": feature["status"],
        "categories": feature["categories"],
        "keywords": feature["keywords"],
        "stats": stats,
        "notes": summary,
        "notes_by_num": notes_by_num,
        "boundary_dependent": list(boundary_dependent or []),
        "verdict": {
            "code": verdict_code,
            "headline": verdict_headline,
            "detail": verdict_detail,
        },
        "usage_perc_y": None,
        "usage_perc_a": None,
        "usage_note": (
            "Not published. Candidate source: count of public MCP servers using this "
            "capability. Not estimated, so the panel stays empty until the corpus is scanned."
        ),
        "links": [{"url": feature["docs_url"], "title": feature["docs_label"]}],
        "known_issues": known_issues or [],
        "why": feature["why"],
        "reproduce": reproduce or reproduce_command(spec, job, fixture),
        "measured": {
            "run_date": run_date,
            "mcp_spec": spec,
            "fixture": fixture,
        },
        "shown": True,
        "spec_label": f"MCP {spec}",
        "docs_url": feature["docs_url"],
        "docs_label": feature["docs_label"],
    }

    path = spec_dir / "capabilities" / f"{feature_id}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path
