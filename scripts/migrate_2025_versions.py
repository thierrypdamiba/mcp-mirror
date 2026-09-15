"""Move the 2025-11-25 snapshot onto the versions the runner manifests actually pin.

The snapshot's ``current_version`` had drifted behind the manifests: cells were keyed at
crewai 1.14.7 / langchain 0.3.0 / openai-agents 0.20.0 / pydantic-ai 1.107.0 while every
managed run now happens at 1.15.1 / 0.3.2 / 0.22.0 / 2.40.0. The site looks a cell up by
exact ``current_version`` match, so the two have to agree or the grid empties out.

Re-keying alone would have been a lie: a cell measured at 1.14.7 is not evidence about
1.15.1. Each code here was re-derived from a managed scan at the new versions, and one
of them moved -- CrewAI stopped rewriting the ``limit`` default somewhere between 1.14.7
and 1.15.1, so its ``default-value`` cell goes from 'a' to 'y'.

Run once; it is idempotent only in the sense that a second run finds nothing to move.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# version_list windows, with release dates read from the registry rather than guessed.
# era 0 is the version the managed runner pins, which is the version we measured at.
VERSION_LISTS = {
    "crewai": [
        ("1.14.6", "2026-05-28T17:05:44Z", -3),
        ("1.14.7", "2026-06-11T17:14:49Z", -2),
        ("1.15.0", "2026-06-25T23:18:37Z", -1),
        ("1.15.1", "2026-06-27T06:51:32Z", 0),
        ("1.15.2", "2026-07-08T02:06:14Z", 1),
        ("1.15.3", "2026-07-16T19:43:55Z", 2),
    ],
    "langchain": [
        ("0.2.2", "2026-03-16T17:13:29Z", -3),
        ("0.3.0", "2026-06-10T01:10:27Z", -2),
        ("0.3.1", "2026-07-27T18:36:44Z", -1),
        ("0.3.2", "2026-08-06T06:15:02Z", 0),
    ],
    "openai-agents": [
        ("0.20.0", "2026-08-11T03:12:47Z", -3),
        ("0.21.0", "2026-08-15T02:50:08Z", -2),
        ("0.21.1", "2026-08-16T22:29:33Z", -1),
        ("0.22.0", "2026-08-19T13:45:19Z", 0),
        ("0.22.1", "2026-09-08T09:22:16Z", 1),
        ("0.22.2", "2026-09-09T12:37:23Z", 2),
    ],
    "pydantic-ai": [
        ("2.37.0", "2026-09-01T02:07:31Z", -3),
        ("2.38.0", "2026-09-03T07:57:21Z", -2),
        ("2.39.0", "2026-09-04T04:30:14Z", -1),
        ("2.40.0", "2026-09-05T00:19:00Z", 0),
        ("2.41.0", "2026-09-08T04:25:57Z", 1),
        ("2.42.0", "2026-09-09T03:48:43Z", 2),
    ],
}

MOVES = {
    "crewai": ("1.14.7", "1.15.1"),
    "langchain": ("0.3.0", "0.3.2"),
    "openai-agents": ("0.20.0", "0.22.0"),
    "pydantic-ai": ("1.107.0", "2.40.0"),
}


def migrate_frameworks() -> None:
    path = DATA / "frameworks.json"
    doc = json.loads(path.read_text())
    for agent_id, entries in VERSION_LISTS.items():
        agent = doc["agents"][agent_id]
        agent["version_list"] = [
            {"version": version, "release_date": date, "era": era}
            for version, date, era in entries
        ]
        agent["current_version"] = next(v for v, _d, e in entries if e == 0)
        agent["stable_version"] = entries[-1][0]
    path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"  frameworks.json: {', '.join(f'{a}->{n}' for a, (_o, n) in MOVES.items())}")


def rekey_capabilities() -> None:
    """Point every existing cell at the version it is now evidence for."""

    for path in sorted((DATA / "capabilities").glob("*.json")):
        capability = json.loads(path.read_text())
        for agent_id, (old, new) in MOVES.items():
            stats = capability["stats"][agent_id]
            if old not in stats:
                continue
            capability["stats"][agent_id] = {new: stats.pop(old)}
        path.write_text(json.dumps(capability, indent=2) + "\n")
    print(f"  re-keyed {len(list((DATA / 'capabilities').glob('*.json')))} capability files")


def apply_crewai_default_fix() -> None:
    """CrewAI preserves the source default at 1.15.1; it did not at 1.14.7.

    Dropping the only 'a' cell drops the only note with it, so the row becomes an
    unqualified pass and the verdict has to stop describing a change that no longer
    happens.
    """

    path = DATA / "capabilities" / "default-value.json"
    capability = json.loads(path.read_text())
    capability["stats"]["crewai"] = {"1.15.1": "y"}
    capability["notes_by_num"] = {}
    capability["notes"] = (
        "Every adapter now hands the agent the source default of 20. CrewAI rewrote it "
        "as recently as crewai-tools 1.14.7; the generated args_schema preserves it at "
        "1.15.1."
    )
    capability["verdict"] = {
        "code": "y",
        "headline": "Preserved at all five boundaries.",
        "detail": (
            "The default survives every adaptation measured here. This row changed when "
            "CrewAI moved from 1.14.7 to 1.15.1, which is the kind of silent repair that "
            "only shows up if you keep re-measuring."
        ),
    }
    capability["measured"]["run_date"] = "2026-09-14"
    path.write_text(json.dumps(capability, indent=2) + "\n")
    print("  default-value: crewai a -> y (fixed in crewai-tools 1.15.1)")


if __name__ == "__main__":
    print("migrating the 2025-11-25 snapshot to manifest-pinned versions")
    migrate_frameworks()
    rekey_capabilities()
    apply_crewai_default_fix()
    print("done")
