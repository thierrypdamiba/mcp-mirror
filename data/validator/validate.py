#!/usr/bin/env python3
"""Validate the mcp-mirror support data (caniuse-shaped).

Data model mirrors caniuse: `agents` carry a `version_list` with an `era` index and
a registry release date; each capability carries `stats` as an
``agent -> {version: support-code}`` map. Support codes are single letters with
optional note references, e.g. ``"a #1"``.

The data is the product, so it is machine-checked: a contributor, including a
framework maintainer correcting their own row, opens a PR and CI rejects a
malformed or unsourced cell rather than publishing it.

Usage:  python3 data/validator/validate.py [data_dir]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED_KEYS = {
    "schema", "id", "title", "description", "spec", "docs_url", "docs_label",
    "status", "categories",
    "stats", "notes_by_num", "verdict", "why", "reproduce", "measured",
}
CODES = {"y", "a", "n", "u"}
# Codes that assert something happened to the value, and therefore owe an explanation.
CODES_NEEDING_NOTE = {"a", "n"}
CODE_RE = re.compile(r"^(?P<code>[yanu])(?P<rest>(?:\s+#\d+)*)$")
GENERIC_DOC_ROOTS = {
    "https://modelcontextprotocol.io/specification",
    "https://json-schema.org/draft/2020-12/json-schema-validation",
}
CANONICAL_TITLES = {
    "read-only-hint": "`readOnlyHint`",
    "destructive-hint": "`destructiveHint`",
    "idempotent-hint": "`idempotentHint`",
    "open-world-hint": "`openWorldHint`",
    "format": "`format`",
    "enum": "`enum`",
    "required": "`required`",
    "one-of-any-of": "`oneOf` / `anyOf`",
    "tool-name": "`name`",
    "title-annotation": "`title`",
    "description-fidelity": "`description`",
    "arrays-of-objects": "Arrays of Objects",
    "nested-objects": "Nested Objects",
    "numeric-range": "Numeric Ranges",
    "long-descriptions": "Long Descriptions",
}


def _err(errors: list[str], where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def parse_code(raw: str) -> tuple[str | None, list[int]]:
    """'a #1 #3' -> ('a', [1, 3]). Returns (None, []) if unparseable."""
    match = CODE_RE.match(raw.strip())
    if not match:
        return None, []
    refs = [int(n) for n in re.findall(r"#(\d+)", match.group("rest"))]
    return match.group("code"), refs


def validate_capability(path: Path, agents: dict, statuses: dict, errors: list[str]) -> dict | None:
    where = path.name
    try:
        cap = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        _err(errors, where, f"invalid JSON ({exc})")
        return None

    missing = REQUIRED_KEYS - set(cap)
    if missing:
        _err(errors, where, f"missing required keys: {sorted(missing)}")
        return None

    if cap["id"] != path.stem:
        _err(errors, where, f"id {cap['id']!r} does not match filename {path.stem!r}")
    expected_title = CANONICAL_TITLES.get(cap["id"])
    if expected_title and cap["title"] != expected_title:
        _err(
            errors,
            where,
            f"title must preserve canonical field spelling or intentional concept casing: {expected_title!r}",
        )
    if cap["status"] not in statuses:
        _err(errors, where, f"status {cap['status']!r} not in {sorted(statuses)}")
    if cap.get("docs_url", "").rstrip("/") in GENERIC_DOC_ROOTS:
        _err(errors, where, "docs_url must target the exact capability section")
    if not str(cap.get("docs_label", "")).strip():
        _err(errors, where, "docs_label must be non-empty")
    for link in cap.get("links", []):
        if str(link.get("url", "")).rstrip("/") in GENERIC_DOC_ROOTS:
            _err(errors, where, "resource link retains a generic documentation root")

    notes_by_num = cap.get("notes_by_num") or {}
    known_refs = {int(k) for k in notes_by_num if str(k).isdigit()}

    stats = cap.get("stats") or {}
    if not stats:
        _err(errors, where, "stats is empty")

    for agent_id, versions in stats.items():
        agent = agents.get(agent_id)
        if agent is None:
            _err(errors, where, f"unknown agent id {agent_id!r} (not in frameworks.json)")
            continue
        if not isinstance(versions, dict) or not versions:
            _err(errors, where, f"{agent_id}: stats must be a non-empty version -> code map")
            continue

        known_versions = {entry["version"] for entry in agent.get("version_list", [])}
        for version, raw in versions.items():
            cell = f"{agent_id} {version}"
            if version not in known_versions:
                _err(errors, where, f"{cell}: version not in that agent's version_list")
            code, refs = parse_code(str(raw))
            if code is None:
                _err(errors, where, f"{cell}: cannot parse support code {raw!r} (expected e.g. 'y', 'a #1')")
                continue
            # The core rule: a changed or dropped value must name its mechanism.
            if code in CODES_NEEDING_NOTE and not refs:
                _err(errors, where, f"{cell}: code {code!r} requires at least one #n note reference")
            for ref in refs:
                if ref not in known_refs:
                    _err(errors, where, f"{cell}: note #{ref} does not exist in notes_by_num")

        current = agent.get("current_version")
        if current and current not in versions:
            _err(errors, where, f"{agent_id}: no entry for current_version {current!r}")

    current_refs: list[int] = []
    for agent_id, agent in agents.items():
        current = agent.get("current_version")
        raw = (stats.get(agent_id) or {}).get(current)
        if raw is None:
            continue
        _, refs = parse_code(str(raw))
        if refs != sorted(refs):
            _err(
                errors,
                where,
                f"{agent_id} {current}: note references must increase within the cell",
            )
        current_refs.extend(refs)
    expected_refs = list(range(1, len(current_refs) + 1))
    if current_refs != expected_refs:
        _err(
            errors,
            where,
            "current-version note references must be contiguous in framework "
            f"reading order (found {current_refs}, expected {expected_refs})",
        )

    verdict = cap.get("verdict") or {}
    if verdict.get("code") not in CODES:
        _err(errors, where, f"verdict.code {verdict.get('code')!r} not in {sorted(CODES)}")

    example = cap.get("example")
    if example is not None:
        for key in ("before", "after"):
            if not isinstance(example.get(key), list):
                _err(errors, where, f"example.{key} must be a list of lines")

    return cap


def validate_all(data_dir: Path) -> tuple[dict, list[dict], list[str]]:
    errors: list[str] = []
    root = json.loads((data_dir / "frameworks.json").read_text())
    agents = root["agents"]

    for agent_id, agent in agents.items():
        eras = [e.get("era") for e in agent.get("version_list", [])]
        versions = {e.get("version") for e in agent.get("version_list", [])}
        if 0 not in eras:
            _err(errors, "frameworks.json", f"{agent_id}: version_list needs one entry at era 0 (current)")
        if len(eras) != len(set(eras)):
            _err(errors, "frameworks.json", f"{agent_id}: duplicate era values in version_list")
        if agent.get("stable_version") not in versions:
            _err(errors, "frameworks.json", f"{agent_id}: stable_version must exist in version_list")
        dev_version = agent.get("dev_version")
        if dev_version is not None:
            if dev_version not in versions:
                _err(errors, "frameworks.json", f"{agent_id}: dev_version must exist in version_list")
            if not re.search(r"(?:dev|alpha|beta|rc|next|canary)", str(dev_version), re.I):
                _err(errors, "frameworks.json", f"{agent_id}: dev_version is not an explicit prerelease channel")

    capabilities = []
    for path in sorted((data_dir / "capabilities").glob("*.json")):
        cap = validate_capability(path, agents, root["statuses"], errors)
        if cap is not None:
            capabilities.append(cap)

    if not capabilities:
        errors.append("capabilities/: no capability files found")
    popularity_path = data_dir / "popularity.mock.json"
    if popularity_path.exists():
        popularity = json.loads(popularity_path.read_text())
        known_ids = {capability["id"] for capability in capabilities}
        windows = popularity.get("windows", [])
        if popularity.get("mode") != "mock":
            _err(errors, popularity_path.name, "checked-in fixture must declare mode 'mock'")
        for entry in popularity.get("entries", []):
            capability_id = entry.get("capability_id")
            if capability_id not in known_ids:
                _err(errors, popularity_path.name, f"unknown capability id {capability_id!r}")
            counts = entry.get("counts", {})
            if set(counts) != set(windows):
                _err(errors, popularity_path.name, f"{capability_id}: counts must cover every window")
            for window, pair in counts.items():
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(not isinstance(value, int) or value < 0 for value in pair)
                ):
                    _err(errors, popularity_path.name, f"{capability_id} {window}: expected two nonnegative integers")
        root["popularity"] = popularity
    return root, capabilities, errors


def main() -> int:
    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    root, capabilities, errors = validate_all(data_dir)
    for error in errors:
        print(f"  ✗ {error}")
    if errors:
        print(f"\n{len(errors)} problem(s) found.")
        return 1
    print(f"  ✓ {len(capabilities)} capability file(s) valid across {len(root['agents'])} agents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
