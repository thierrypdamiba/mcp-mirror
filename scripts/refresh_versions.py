"""Refresh each framework's published release window from PyPI and npm.

`current_version` is the release a scan actually ran against, so it is never touched
here: moving it would re-label evidence as belonging to a version nobody measured. What
does go stale is everything around it. `stable_version` and the releases after era 0 are
registry facts with a shelf life, and when they lag the registry the grid quietly
implies the measurement sits at the frontier when it is twenty-one releases behind.

    uv run python scripts/refresh_versions.py          # write
    uv run python scripts/refresh_versions.py --check  # report drift, change nothing

Entries at or before era 0 are left alone. Each snapshot chose how much history to
publish, and that is an editorial decision rather than something a registry can answer.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_FILES = (
    ROOT / "data" / "frameworks.json",
    ROOT / "data" / "specs" / "2026-07-28" / "frameworks.json",
)

# Only final releases are published. A prerelease would sit in the middle of the window
# and shift every era after it, and @mastra/mcp 2.0.0-alpha.4 is exactly that case.
STABLE_VERSION = re.compile(r"^\d+(?:\.\d+)*$")
TIMEOUT = 30


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def pypi_releases(package: str) -> list[tuple[str, str]]:
    document = _fetch(f"https://pypi.org/pypi/{package}/json")
    return [
        (version, min(file["upload_time_iso_8601"] for file in files))
        for version, files in document["releases"].items()
        if files and STABLE_VERSION.match(version)
    ]


def npm_releases(package: str) -> list[tuple[str, str]]:
    document = _fetch(f"https://registry.npmjs.org/{package}")
    times = document["time"]
    return [
        (version, times[version])
        for version in document["versions"]
        if STABLE_VERSION.match(version) and version in times
    ]


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def releases_for(agent: dict) -> list[tuple[str, str]]:
    """Every final release of one agent's package, in version order.

    Ordering by upload date would be wrong: pydantic-ai still ships 1.107.x patches,
    and the newest of those went out after 2.44.0. A maintenance backport is not a
    release after the 2.40.0 this project measured, so era offsets follow the version
    line rather than the calendar.
    """

    registry = agent["registry"]
    releases = (
        pypi_releases(agent["package"])
        if registry == "pypi"
        else npm_releases(agent["package"])
    )
    if not releases:
        raise SystemExit(f"{agent['package']}: no stable releases found on {registry}")
    return sorted(releases, key=lambda entry: _as_tuple(entry[0]))


def _iso(timestamp: str) -> str:
    """Second-precision UTC, which is the format already published and parsed.

    PyPI reports fractional seconds and npm does not, so both are trimmed to the one
    shape scripts/build_data.py can read back.
    """

    return re.sub(r"\.\d+", "", timestamp).replace("+00:00", "Z")


def refresh_agent(agent_id: str, agent: dict) -> list[str]:
    """Rewrite one agent's forward release window. Returns human-readable changes."""

    releases = releases_for(agent)
    current = agent["current_version"]
    versions = [version for version, _ in releases]
    if current not in versions:
        raise SystemExit(
            f"{agent_id}: measured version {current} is not a final release of "
            f"{agent['package']}; refusing to guess an era offset"
        )

    index = versions.index(current)
    history = [entry for entry in agent["version_list"] if entry["era"] <= 0]
    forward = [
        {"version": version, "release_date": _iso(uploaded), "era": offset}
        for offset, (version, uploaded) in enumerate(releases[index + 1 :], start=1)
    ]
    latest = versions[-1]

    changes = []
    if agent.get("stable_version") != latest:
        changes.append(f"stable_version {agent.get('stable_version')} -> {latest}")
    published = [entry["version"] for entry in agent["version_list"] if entry["era"] > 0]
    if published != [entry["version"] for entry in forward]:
        behind = len(forward)
        changes.append(
            f"version_list now carries {behind} release(s) after the measured {current}"
            + (f", newest {latest}" if behind else "")
        )

    agent["version_list"] = history + forward
    agent["stable_version"] = latest
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit nonzero instead of writing",
    )
    arguments = parser.parse_args()

    drifted = False
    for path in FRAMEWORK_FILES:
        document = json.loads(path.read_text())
        print(f"\n{path.relative_to(ROOT)}")
        file_changes = False
        for agent_id, agent in document["agents"].items():
            changes = refresh_agent(agent_id, agent)
            if changes:
                file_changes = True
                for change in changes:
                    print(f"  {agent_id}: {change}")
            else:
                print(f"  {agent_id}: current")
        if not file_changes:
            continue
        drifted = True
        if arguments.check:
            continue
        document["updated"] = date.today().isoformat()
        path.write_text(json.dumps(document, indent=2) + "\n")
        print(f"  wrote {path.relative_to(ROOT)}")

    if arguments.check and drifted:
        print("\nversion metadata is behind the registries")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
