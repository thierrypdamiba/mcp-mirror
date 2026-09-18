#!/usr/bin/env python3
"""Validate the support data and generate the caniuse-shaped aggregate.

Same split caniuse uses: per-entry files are the source of truth (so `git log` on
one file is that capability's changelog), a single aggregate is generated for
consumers, and the website is just one consumer of that aggregate.

    data/frameworks.json                  legacy source snapshot
    data/capabilities/*.json
    data/specs/<revision>/frameworks.json separate protocol snapshots
    data/specs/<revision>/capabilities/*

Each source snapshot produces ``data-<revision>.json``. The newest revision is
also written to ``data-1.0.json`` for backwards-compatible consumers, and
``specs.json`` tells the site which complete dataset to load.

Usage:  python3 scripts/build_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "validator"))

from validate import validate_all  # noqa: E402

SCHEMA_VERSION = "1.0"


def to_unix(iso: str | None) -> int | None:
    """caniuse stores release dates as unix seconds; keep the ISO string too."""
    if not iso:
        return None
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def incompatible_agents(agents: dict) -> dict[str, str]:
    """Agents that cannot negotiate this revision, mapped to the evidence for that.

    An adapter whose SDK pin or negotiated version rules out the revision reaches none
    of its features. That is a determinate result, not a gap in our measuring, so its
    cells carry 'x' rather than 'u' whether or not the feature itself has been probed.
    """
    return {
        agent_id: agent.get("measurement_note", "")
        for agent_id, agent in agents.items()
        if agent.get("measurement_status", "measured") != "measured"
    }


def unmeasured_capability(feature: dict, agents: dict, revision: str) -> dict:
    """Render a protocol feature nobody has measured yet as a full, honest row.

    The row is published rather than hidden so that the gap between what MCP defines and
    what we have measured is visible on the site instead of being implied by absence.
    Frameworks that cannot reach the revision are still answered here: their cells are
    'x', because the feature being unprobed does not make their outcome unknown.
    """
    blocked = incompatible_agents(agents)
    numbering = {
        agent_id: str(index + 1)
        for index, agent_id in enumerate(a for a in agents if a in blocked)
    }
    return {
        "schema": "mcp-mirror/capability@3",
        "id": feature["id"],
        "title": feature["title"],
        "description": feature["description"],
        "question": feature["question"],
        "spec": feature["spec"],
        "status": feature["status"],
        "categories": feature["categories"],
        "keywords": feature["keywords"],
        "stats": {
            agent_id: {
                agent["current_version"]: (
                    f"x #{numbering[agent_id]}" if agent_id in blocked else "u"
                )
            }
            for agent_id, agent in agents.items()
        },
        "notes": (
            (
                f"No scan probes this feature yet, so the {len(agents) - len(blocked)} "
                "adapters that can reach this revision are unmeasured. The rest cannot "
                "negotiate the revision at all, so they reach none of it."
            )
            if blocked
            else (
                "No scan produces this row yet, so every cell is unmeasured. It is "
                "published because the specification defines the feature, not because "
                "anything is known about how these frameworks handle it."
            )
        ),
        "notes_by_num": {
            numbering[agent_id]: note for agent_id, note in blocked.items()
        },
        # Nothing has been measured here, so nothing can depend on a boundary yet.
        "boundary_dependent": [],
        "verdict": {
            "code": "u",
            "headline": (
                f"Not yet probed; {len(blocked)} of {len(agents)} adapters cannot "
                "reach this revision."
            )
            if blocked
            else "Not yet measured.",
            "detail": feature["probe"],
        },
        "usage_perc_y": None,
        "usage_perc_a": None,
        "usage_note": None,
        "why": feature["why"],
        "reproduce": "",
        "measured": {"run_date": None, "mcp_spec": revision, "fixture": None},
        "shown": True,
        "spec_label": f"MCP {revision}",
        "docs_url": feature["docs_url"],
        "docs_label": feature["docs_label"],
    }


def merge_surface(root: dict, capabilities: list[dict]) -> tuple[list[dict], dict | None]:
    """Combine measured capability files with the protocol surface they are measured against.

    Returns the published rows in specification order, plus the coverage figures the site
    reports. Coverage is computed here rather than written down anywhere, so it cannot
    disagree with the data.
    """
    surface = root.get("surface")
    if not surface:
        return capabilities, None

    revision = surface["revision"]
    agents = root["agents"]
    by_id = {cap["id"]: cap for cap in capabilities}

    rows: list[dict] = []
    counts = {area: [0, 0] for area in surface["areas"]}
    for feature in surface["features"]:
        measured = by_id.get(feature["id"])
        total, done = counts[feature["area"]]
        if measured is not None:
            rows.append({**measured, "area": feature["area"], "measurement_state": "measured"})
            counts[feature["area"]] = [total + 1, done + 1]
        else:
            rows.append({
                **unmeasured_capability(feature, agents, revision),
                "area": feature["area"],
                "measurement_state": "not_measured",
                "probe": feature["probe"],
            })
            counts[feature["area"]] = [total + 1, done]
        if "wire" in feature:
            rows[-1]["wire"] = feature["wire"]

    coverage = {
        "revision": revision,
        "catalogued": surface["catalogued"],
        "source": surface.get("source", ""),
        "measured": sum(done for _total, done in counts.values()),
        "total": len(surface["features"]),
        "by_area": [
            {"area": area, "measured": done, "total": total}
            for area, (total, done) in counts.items()
        ],
        "note": surface.get("note", ""),
        "omissions": surface.get("omissions", []),
    }
    return rows, coverage


def build_aggregate(source_dir: Path) -> tuple[dict, list[dict], list[int]] | None:
    root, capabilities, errors = validate_all(source_dir)
    if errors:
        for error in errors:
            print(f"  ✗ {source_dir.relative_to(ROOT)}: {error}")
        return None
    capabilities, coverage = merge_surface(root, capabilities)

    agents = {}
    era_values = set()
    for agent_id, agent in root["agents"].items():
        version_list = []
        for entry in agent["version_list"]:
            era_values.add(entry["era"])
            version_list.append({
                **entry,
                "release_date_unix": to_unix(entry.get("release_date")),
            })
        agents[agent_id] = {**agent, "version_list": version_list}

    # eras index the grid rows: 0 is the current release, negative older, positive newer.
    eras = {f"e{e}": ("current release" if e == 0 else f"{abs(e)} release(s) {'before' if e < 0 else 'after'} current")
            for e in sorted(era_values)}

    cats: dict[str, list[str]] = {}
    for cap in capabilities:
        for category in cap.get("categories", []):
            cats.setdefault(category, []).append(cap["id"])

    aggregate = {
        "schema": f"mcp-mirror/data@{SCHEMA_VERSION}",
        "updated": root["updated"],
        "mcp_spec": root["mcp_spec"],
        "repo": root.get("repo", ""),
        "eras": eras,
        "agents": agents,
        "statuses": root["statuses"],
        "support_codes": root["support_codes"],
        "defaults": root["defaults"],
        "popularity": root.get("popularity"),
        "coverage": coverage,
        "cats": cats,
        "data": {cap["id"]: cap for cap in capabilities},
    }
    return aggregate, capabilities, sorted(era_values)


def write_payload(payload: str, targets: tuple[Path, ...]) -> None:
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload)
        print(f"  ✓ wrote {target.relative_to(ROOT)} ({len(payload):,} bytes)")


def main() -> int:
    data_dir = ROOT / "data"
    source_dirs = [data_dir]
    specs_dir = data_dir / "specs"
    if specs_dir.exists():
        source_dirs.extend(
            path
            for path in sorted(specs_dir.iterdir())
            if path.is_dir() and (path / "frameworks.json").exists()
        )

    built: list[tuple[dict, list[dict], list[int]]] = []
    for source_dir in source_dirs:
        result = build_aggregate(source_dir)
        if result is not None:
            built.append(result)

    if len(built) != len(source_dirs):
        print("\nrefusing to build because one or more source snapshots are invalid")
        return 1

    output_roots = (
        data_dir / "fulldata",
        ROOT / "site" / "public" / "data",
        ROOT / "docs" / "data",
    )
    for aggregate, _capabilities, _eras in built:
        spec = aggregate["mcp_spec"]
        payload = json.dumps(aggregate, indent=2) + "\n"
        write_payload(
            payload,
            tuple(root / f"data-{spec}.json" for root in output_roots),
        )

    default_aggregate, default_capabilities, default_eras = max(
        built,
        key=lambda item: item[0]["mcp_spec"],
    )
    default_payload = json.dumps(default_aggregate, indent=2) + "\n"
    write_payload(
        default_payload,
        tuple(root / f"data-{SCHEMA_VERSION}.json" for root in output_roots),
    )

    spec_index = {
        "schema": "mcp-mirror/spec-index@1",
        "default_spec": default_aggregate["mcp_spec"],
        "specs": [
            {
                "id": aggregate["mcp_spec"],
                "label": f"MCP {aggregate['mcp_spec']}",
                "file": f"data-{aggregate['mcp_spec']}.json",
                "updated": aggregate["updated"],
                "measured_frameworks": sum(
                    1
                    for agent in aggregate["agents"].values()
                    if agent.get("measurement_status", "measured") == "measured"
                ),
                "total_frameworks": len(aggregate["agents"]),
                "coverage": aggregate.get("coverage"),
            }
            for aggregate, _capabilities, _eras in sorted(
                built,
                key=lambda item: item[0]["mcp_spec"],
                reverse=True,
            )
        ],
    }
    index_payload = json.dumps(spec_index, indent=2) + "\n"
    write_payload(
        index_payload,
        tuple(root / "specs.json" for root in output_roots),
    )

    sample = dict(
        default_aggregate,
        data={default_capabilities[0]["id"]: default_capabilities[0]},
    )
    (data_dir / "sample-data.json").write_text(json.dumps(sample, indent=2) + "\n")
    print("  ✓ wrote data/sample-data.json")

    coverage = default_aggregate.get("coverage")
    coverage_line = (
        f", {coverage['measured']}/{coverage['total']} measured"
        if coverage
        else ", no protocol surface catalogued"
    )
    print(
        f"\n{len(built)} protocol snapshot(s); default "
        f"{default_aggregate['mcp_spec']} has {len(default_capabilities)} "
        f"capabilities{coverage_line}, {len(default_aggregate['agents'])} agents, eras "
        f"{default_eras}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
