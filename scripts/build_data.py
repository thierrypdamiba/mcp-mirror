#!/usr/bin/env python3
"""Validate the support data and generate the caniuse-shaped aggregate.

Same split caniuse uses: per-entry files are the source of truth (so `git log` on
one file is that capability's changelog), a single aggregate is generated for
consumers, and the website is just one consumer of that aggregate.

    data/frameworks.json      -┐
    data/capabilities/*.json  -┴-> data/fulldata/data-1.0.json
                                      site/public/data/data-1.0.json
                                      docs/data/data-1.0.json   (published copy)

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


def main() -> int:
    data_dir = ROOT / "data"
    root, capabilities, errors = validate_all(data_dir)
    if errors:
        for error in errors:
            print(f"  ✗ {error}")
        print(f"\nrefusing to build: {len(errors)} problem(s) in data/")
        return 1

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
        "cats": cats,
        "data": {cap["id"]: cap for cap in capabilities},
    }

    payload = json.dumps(aggregate, indent=2) + "\n"
    for target in (
        data_dir / "fulldata" / f"data-{SCHEMA_VERSION}.json",
        ROOT / "site" / "public" / "data" / f"data-{SCHEMA_VERSION}.json",
        ROOT / "docs" / "data" / f"data-{SCHEMA_VERSION}.json",
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload)
        print(f"  ✓ wrote {target.relative_to(ROOT)} ({len(payload):,} bytes)")

    sample = dict(aggregate, data={capabilities[0]["id"]: capabilities[0]})
    (data_dir / "sample-data.json").write_text(json.dumps(sample, indent=2) + "\n")
    print("  ✓ wrote data/sample-data.json")

    print(f"\n{len(capabilities)} capability file(s), {len(agents)} agents, eras {sorted(era_values)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
