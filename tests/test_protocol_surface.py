"""The protocol surface is the denominator behind every coverage claim the site makes.

These tests exist because coverage is the one number on the site that can be improved
without measuring anything, simply by forgetting a feature. They pin the catalogue to the
capability files in both directions: a published row must map to something the
specification defines, and a defined feature must show up as a row.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "specs" / "2026-07-28"

sys.path.insert(0, str(ROOT / "data" / "validator"))
from validate import validate_all  # noqa: E402


def _load_build_data():
    spec = importlib.util.spec_from_file_location(
        "build_data", ROOT / "scripts" / "build_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_data = _load_build_data()


def _unmeasured_feature_ids(snapshot: Path, count: int = 1) -> list[str]:
    """Feature ids with no capability file yet, chosen from the data.

    These tests are about how an unmeasured row behaves, not about any particular
    feature. Naming one turns every new measurement into a false failure, which is
    exactly the wrong incentive for a suite whose job is to protect the denominator.
    """

    _root, capabilities, _errors = validate_all(snapshot)
    published = {capability["id"] for capability in capabilities}
    ids = [
        feature["id"]
        for feature in json.loads((snapshot / "surface.json").read_text())["features"]
        if feature["id"] not in published
    ]
    if len(ids) < count:
        raise AssertionError(
            f"need {count} unmeasured feature(s); the snapshot has {len(ids)}. "
            "Full coverage means these tests need a different subject."
        )
    return ids[:count]


@pytest.fixture()
def snapshot(tmp_path: Path) -> Path:
    target = tmp_path / "2026-07-28"
    shutil.copytree(SNAPSHOT, target)
    return target


def _surface(directory: Path) -> dict:
    return json.loads((directory / "surface.json").read_text())


def _write_surface(directory: Path, surface: dict) -> None:
    (directory / "surface.json").write_text(json.dumps(surface, indent=2))


def test_the_published_snapshot_is_internally_consistent() -> None:
    _root, capabilities, errors = validate_all(SNAPSHOT)
    assert errors == []
    surface = _surface(SNAPSHOT)
    feature_ids = [feature["id"] for feature in surface["features"]]

    assert len(feature_ids) == len(set(feature_ids))
    assert {capability["id"] for capability in capabilities} <= set(feature_ids)
    assert {feature["area"] for feature in surface["features"]} <= set(surface["areas"])


def test_every_catalogued_feature_cites_a_specific_specification_section() -> None:
    """A link to the specification root would make a row unauditable."""
    for feature in _surface(SNAPSHOT)["features"]:
        docs_url = feature.get("docs_url")
        if docs_url is None:
            continue  # Measured features carry their link in the capability file.
        assert docs_url.rstrip("/") not in {
            "https://modelcontextprotocol.io/specification",
            "https://modelcontextprotocol.io/specification/2026-07-28",
        }, feature["id"]


def test_a_feature_status_must_exist_in_the_snapshot_status_vocabulary() -> None:
    frameworks = json.loads((SNAPSHOT / "frameworks.json").read_text())
    statuses = set(frameworks["statuses"])
    used = {feature["status"] for feature in _surface(SNAPSHOT)["features"]}

    assert used <= statuses
    # The 2026-07-28 revision deprecated sampling, roots and logging rather than removing
    # them, so the vocabulary has to be able to say so.
    assert "deprecated" in used


def test_a_published_row_without_a_catalogued_feature_is_rejected(snapshot: Path) -> None:
    surface = _surface(snapshot)
    surface["features"] = [
        feature for feature in surface["features"] if feature["id"] != "enum"
    ]
    _write_surface(snapshot, surface)

    _root, _capabilities, errors = validate_all(snapshot)

    assert any("enum" in error and "no entry in the protocol surface" in error for error in errors)


def test_an_uncatalogued_feature_must_explain_itself(snapshot: Path) -> None:
    subject = _unmeasured_feature_ids(snapshot)[0]
    surface = _surface(snapshot)
    for feature in surface["features"]:
        if feature["id"] == subject:
            del feature["probe"]
    _write_surface(snapshot, surface)

    _root, _capabilities, errors = validate_all(snapshot)

    assert any(subject in error and "probe" in error for error in errors)


def test_the_catalogue_and_the_capability_file_must_agree_on_a_title(snapshot: Path) -> None:
    surface = _surface(snapshot)
    for feature in surface["features"]:
        if feature["id"] == "enum":
            feature["title"] = "`enumeration`"
    _write_surface(snapshot, surface)

    _root, _capabilities, errors = validate_all(snapshot)

    assert any("enum" in error and "does not match" in error for error in errors)


def test_the_revision_must_match_the_snapshot_it_sits_in(snapshot: Path) -> None:
    surface = _surface(snapshot)
    surface["revision"] = "2025-11-25"
    _write_surface(snapshot, surface)

    _root, _capabilities, errors = validate_all(snapshot)

    assert any("does not match frameworks.json mcp_spec" in error for error in errors)


def test_an_unmeasured_feature_is_published_as_a_row_with_no_verdict() -> None:
    root, capabilities, errors = validate_all(SNAPSHOT)
    assert errors == []
    rows, coverage = build_data.merge_surface(root, capabilities)
    by_id = {row["id"]: row for row in rows}

    unmeasured = by_id[_unmeasured_feature_ids(SNAPSHOT)[0]]
    assert unmeasured["measurement_state"] == "not_measured"
    assert unmeasured["verdict"]["code"] == "u"
    assert unmeasured["measured"]["run_date"] is None
    # No command is offered, because no command would produce this row.
    assert unmeasured["reproduce"] == ""
    assert unmeasured["probe"]

    # Not probing a feature leaves us ignorant only about adapters that could have
    # reached it. An adapter that cannot negotiate the revision reaches nothing in
    # it, which is an answer, so its cell is 'x' and carries the evidence.
    blocked = build_data.incompatible_agents(root["agents"])
    assert blocked
    codes = {
        agent_id: next(iter(versions.values()))
        for agent_id, versions in unmeasured["stats"].items()
    }
    for agent_id, code in codes.items():
        if agent_id in blocked:
            assert code.startswith("x #"), agent_id
            note = unmeasured["notes_by_num"][code.split("#")[1]]
            assert note == blocked[agent_id]
        else:
            assert code == "u", agent_id

    measured = by_id["enum"]
    assert measured["measurement_state"] == "measured"
    assert measured["measured"]["run_date"]
    assert measured["reproduce"]
    assert coverage is not None


def test_coverage_counts_capability_files_against_the_specification() -> None:
    root, capabilities, errors = validate_all(SNAPSHOT)
    assert errors == []
    rows, coverage = build_data.merge_surface(root, capabilities)

    assert coverage["total"] == len(_surface(SNAPSHOT)["features"])
    assert coverage["measured"] == len(capabilities)
    assert coverage["measured"] < coverage["total"], (
        "this assertion is meant to fail once the whole protocol surface is measured, "
        "which is the point at which the coverage panel stops being interesting"
    )
    assert len(rows) == coverage["total"]
    assert sum(area["total"] for area in coverage["by_area"]) == coverage["total"]
    assert sum(area["measured"] for area in coverage["by_area"]) == coverage["measured"]


def test_the_denominator_can_only_shrink_by_editing_the_catalogue(snapshot: Path) -> None:
    """Where the trust boundary actually sits, stated rather than implied.

    Deleting an unmeasured feature raises the coverage percentage without measuring
    anything, and no check here prevents that. What the design buys is that it cannot
    happen quietly: the denominator lives in one reviewable file, so the only way to do it
    is a diff that deletes a named feature of the published specification.
    """
    root, capabilities, errors = validate_all(snapshot)
    assert errors == []
    _rows, before = build_data.merge_surface(root, capabilities)

    surface = _surface(snapshot)
    dropped = set(_unmeasured_feature_ids(snapshot, 2))
    surface["features"] = [
        feature for feature in surface["features"] if feature["id"] not in dropped
    ]
    _write_surface(snapshot, surface)

    root_after, capabilities_after, errors_after = validate_all(snapshot)
    _rows_after, after = build_data.merge_surface(root_after, capabilities_after)

    assert errors_after == []
    assert after["total"] == before["total"] - 2
    assert after["measured"] == before["measured"]
    assert after["measured"] / after["total"] > before["measured"] / before["total"]
