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
CODES = {"y", "a", "n", "x", "u"}
# Codes that assert something happened to the value, and therefore owe an explanation.
# 'x' asserts the adapter cannot reach the revision at all, which is a claim about
# the framework rather than the feature, so it owes the same evidence.
CODES_NEEDING_NOTE = {"a", "n", "x"}
CODE_RE = re.compile(r"^(?P<code>[yanxu])(?P<rest>(?:\s+#\d+)*)$")
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

    # A cell whose answer depends on where you look must say so on the cell, not only
    # in prose. 'a' is the code for that: the capability is not present unchanged, and
    # the note has to name the mechanism at each boundary.
    boundary_dependent = cap.get("boundary_dependent") or []
    if not isinstance(boundary_dependent, list):
        _err(errors, where, "boundary_dependent must be a list of agent ids")
    else:
        for agent_id in boundary_dependent:
            agent = agents.get(agent_id)
            if agent is None:
                _err(errors, where, f"boundary_dependent names unknown agent {agent_id!r}")
                continue
            if len(agent.get("result_boundaries") or []) < 2:
                _err(
                    errors,
                    where,
                    f"boundary_dependent names {agent_id!r}, which publishes fewer "
                    "than two result boundaries to depend on",
                )
            current = agent.get("current_version")
            code, refs = parse_code(str((stats.get(agent_id) or {}).get(current, "")))
            if code != "a":
                _err(
                    errors,
                    where,
                    f"{agent_id} {current}: a boundary-dependent cell must be 'a' "
                    f"(the value is not present unchanged), found {code!r}",
                )
            if not refs:
                _err(
                    errors,
                    where,
                    f"{agent_id} {current}: a boundary-dependent cell must cite a note "
                    "naming what each boundary yields",
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


SURFACE_REQUIRED_KEYS = {"schema", "revision", "catalogued", "areas", "features"}
# A feature nobody has measured still has to explain itself, because the site publishes it
# as a row. These are the fields that row is rendered from.
SURFACE_UNMEASURED_KEYS = (
    "description", "question", "why", "categories", "keywords", "spec",
    "docs_url", "docs_label", "probe",
)


def validate_surface(
    data_dir: Path,
    root: dict,
    capabilities: list[dict],
    errors: list[str],
) -> dict | None:
    """Check the protocol feature catalogue against the measured capability files.

    surface.json is the denominator: what the specification defines. capabilities/ is the
    numerator: what we measured. Keeping them in one directory and cross-checking here is
    what stops coverage from being improved by quietly forgetting a feature.
    """
    path = data_dir / "surface.json"
    if not path.exists():
        return None
    where = path.name
    try:
        surface = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        _err(errors, where, f"invalid JSON ({exc})")
        return None

    missing = SURFACE_REQUIRED_KEYS - set(surface)
    if missing:
        _err(errors, where, f"missing required keys: {sorted(missing)}")
        return None
    if surface["revision"] != root.get("mcp_spec"):
        _err(
            errors,
            where,
            f"revision {surface['revision']!r} does not match frameworks.json mcp_spec "
            f"{root.get('mcp_spec')!r}",
        )

    areas = surface["areas"]
    statuses = root["statuses"]
    by_id = {cap["id"]: cap for cap in capabilities}

    seen: set[str] = set()
    for feature in surface["features"]:
        feature_id = feature.get("id")
        if not feature_id:
            _err(errors, where, "feature is missing an id")
            continue
        if feature_id in seen:
            _err(errors, where, f"{feature_id}: duplicate feature id")
        seen.add(feature_id)
        if feature.get("area") not in areas:
            _err(errors, where, f"{feature_id}: area {feature.get('area')!r} not in areas")
        if feature.get("status") not in statuses:
            _err(errors, where, f"{feature_id}: status {feature.get('status')!r} not in {sorted(statuses)}")
        if not str(feature.get("title", "")).strip():
            _err(errors, where, f"{feature_id}: title must be non-empty")

        measured = by_id.get(feature_id)
        if measured is not None:
            # Both files describe the same row, so they must agree on what it is called.
            if measured["title"] != feature.get("title"):
                _err(
                    errors,
                    where,
                    f"{feature_id}: title {feature.get('title')!r} does not match the "
                    f"capability file's {measured['title']!r}",
                )
            continue

        # No capability file, so the build synthesises the row entirely from this entry.
        for key in SURFACE_UNMEASURED_KEYS:
            if not str(feature.get(key, "")).strip() and not feature.get(key):
                _err(errors, where, f"{feature_id}: unmeasured feature requires a non-empty {key!r}")
        if str(feature.get("docs_url", "")).rstrip("/") in GENERIC_DOC_ROOTS:
            _err(errors, where, f"{feature_id}: docs_url must target the exact specification section")
        categories = feature.get("categories")
        if not isinstance(categories, list) or not categories:
            _err(errors, where, f"{feature_id}: categories must be a non-empty list")

    for capability_id in sorted(by_id):
        if capability_id not in seen:
            _err(
                errors,
                where,
                f"capability {capability_id!r} has no entry in the protocol surface; every "
                "published row must map to a feature the specification defines",
            )

    return surface


def validate_all(data_dir: Path) -> tuple[dict, list[dict], list[str]]:
    errors: list[str] = []
    root = json.loads((data_dir / "frameworks.json").read_text())
    agents = root["agents"]

    for agent_id, agent in agents.items():
        eras = [e.get("era") for e in agent.get("version_list", [])]
        versions = {e.get("version") for e in agent.get("version_list", [])}
        measurement_status = agent.get("measurement_status", "measured")
        if measurement_status not in {
            "measured",
            "sdk_incompatible",
            "protocol_mismatch",
        }:
            _err(
                errors,
                "frameworks.json",
                f"{agent_id}: invalid measurement_status {measurement_status!r}",
            )
        if measurement_status != "measured" and not str(
            agent.get("measurement_note", "")
        ).strip():
            _err(
                errors,
                "frameworks.json",
                f"{agent_id}: unmeasured framework requires measurement_note",
            )
        capture = agent.get("capture_boundary")
        required_capture_keys = {
            "capture_api",
            "capture_object",
            "capture_stage",
            "provider_request_captured",
            "negotiated_mcp_spec_version",
            "protocol_version_evidence",
        }
        if not isinstance(capture, dict):
            _err(errors, "frameworks.json", f"{agent_id}: capture_boundary must be an object")
        else:
            missing_capture = required_capture_keys - set(capture)
            if missing_capture:
                _err(
                    errors,
                    "frameworks.json",
                    f"{agent_id}: capture_boundary missing {sorted(missing_capture)}",
                )
            stage = capture.get("capture_stage")
            if stage not in {
                "framework_tool_definition",
                "provider_format",
                "provider_request",
            }:
                _err(
                    errors,
                    "frameworks.json",
                    f"{agent_id}: invalid capture_stage {stage!r}",
                )
            if capture.get("provider_request_captured") and stage != "provider_request":
                _err(
                    errors,
                    "frameworks.json",
                    f"{agent_id}: provider request can be captured only at provider_request stage",
                )
            if (
                measurement_status == "measured"
                and capture.get("negotiated_mcp_spec_version") != root.get("mcp_spec")
            ):
                _err(
                    errors,
                    "frameworks.json",
                    f"{agent_id}: measured adapter MCP version must match root mcp_spec",
                )
        # capture_boundary is where a tool *definition* was read. A tool *result* can
        # have more than one boundary, and publishing only one of them is how a cell
        # ends up describing something no agent does, so every result boundary the
        # renderer can be asked at is published and exactly one is the agent's.
        result_boundaries = agent.get("result_boundaries")
        required_result_keys = {
            "id",
            "label",
            "capture_api",
            "capture_object",
            "agent_path",
        }
        if not isinstance(result_boundaries, list) or not result_boundaries:
            _err(
                errors,
                "frameworks.json",
                f"{agent_id}: result_boundaries must be a non-empty list",
            )
        else:
            seen_ids: set[str] = set()
            agent_paths = 0
            for index, boundary in enumerate(result_boundaries):
                label = f"{agent_id}: result_boundaries[{index}]"
                if not isinstance(boundary, dict):
                    _err(errors, "frameworks.json", f"{label} must be an object")
                    continue
                missing_result = required_result_keys - set(boundary)
                if missing_result:
                    _err(
                        errors,
                        "frameworks.json",
                        f"{label} missing {sorted(missing_result)}",
                    )
                    continue
                if boundary["id"] in seen_ids:
                    _err(errors, "frameworks.json", f"{label}: duplicate id {boundary['id']!r}")
                seen_ids.add(boundary["id"])
                if not isinstance(boundary["agent_path"], bool):
                    _err(errors, "frameworks.json", f"{label}: agent_path must be a boolean")
                elif boundary["agent_path"]:
                    agent_paths += 1
                for key in ("label", "capture_api", "capture_object"):
                    if not str(boundary.get(key, "")).strip():
                        _err(errors, "frameworks.json", f"{label}: {key} must be non-empty")
            if agent_paths != 1:
                _err(
                    errors,
                    "frameworks.json",
                    f"{agent_id}: exactly one result boundary must be the agent path "
                    f"(found {agent_paths})",
                )
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
    root["surface"] = validate_surface(data_dir, root, capabilities, errors)
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
    surface = root.get("surface")
    if surface:
        total = len(surface["features"])
        print(
            f"  ✓ protocol surface for {surface['revision']}: {len(capabilities)} of "
            f"{total} feature(s) measured, {total - len(capabilities)} published unmeasured."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
