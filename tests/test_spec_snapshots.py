from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "specs" / "2026-07-28"
BEHAVIOR_ANNOTATIONS = {
    "destructive-hint",
    "idempotent-hint",
    "open-world-hint",
    "read-only-hint",
}


def test_2026_snapshot_keeps_same_protocol_evidence_separate() -> None:
    frameworks = json.loads((SNAPSHOT / "frameworks.json").read_text())
    report = json.loads((SNAPSHOT / "report.json").read_text())
    attempts = json.loads((SNAPSHOT / "attempts.json").read_text())

    assert frameworks["mcp_spec"] == report["mcp_spec_version"] == "2026-07-28"
    assert report["mcp_spec_version_evidence"] == (
        "direct source connection server/discover result"
    )

    runs = {run["framework"]: run for run in report["runs"]}
    assert set(runs) == {"pydantic_ai", "openai_agents"}
    assert {
        run["evidence"]["negotiated_mcp_spec_version"]
        for run in runs.values()
    } == {"2026-07-28"}
    assert all(
        difference["dimension"] == "annotation"
        for run in runs.values()
        for difference in run["differences"]
    )

    agents = frameworks["agents"]
    assert agents["pydantic-ai"]["current_version"] == "2.40.0"
    assert agents["openai-agents"]["current_version"] == "0.22.0"
    assert {
        agent_id
        for agent_id, agent in agents.items()
        if agent["measurement_status"] != "measured"
    } == {"crewai", "langchain", "mastra"}
    assert set(attempts["attempts"]) == {"crewai", "langchain", "mastra"}
    for agent_id, attempt in attempts["attempts"].items():
        assert attempt["status"] == agents[agent_id]["measurement_status"]
        assert attempt["framework_version"] == agents[agent_id]["current_version"]
        assert attempt["evidence"]


def test_2026_capability_cells_match_the_saved_report() -> None:
    agents = json.loads((SNAPSHOT / "frameworks.json").read_text())["agents"]
    blocked = {
        agent_id: (agent["current_version"], agent["measurement_note"])
        for agent_id, agent in agents.items()
        if agent["measurement_status"] != "measured"
    }

    for path in sorted((SNAPSHOT / "capabilities").glob("*.json")):
        capability = json.loads(path.read_text())
        capability_id = capability["id"]
        stats = capability["stats"]

        # The revision and fixture are fixed for this snapshot; the run date is not,
        # because features are measured on different days as coverage grows.
        measured = capability["measured"]
        assert measured["mcp_spec"] == "2026-07-28"
        assert measured["fixture"] == "fixtures/tricky_server.py"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", measured["run_date"] or ""), (
            capability_id,
            measured["run_date"],
        )

        # An adapter that cannot open a session at this revision reaches none of its
        # features. That is a measured outcome carrying the evidence for it, not the
        # 'u' we owe a feature nobody has probed.
        for agent_id, (version, note) in blocked.items():
            cell = stats[agent_id][version]
            assert cell.startswith("x #"), (capability_id, agent_id, cell)
            assert capability["notes_by_num"][cell.split("#")[1]] == note

        openai_code = stats["openai-agents"]["0.22.0"].split()[0]
        pydantic_code = stats["pydantic-ai"]["2.40.0"].split()[0]

        # Only the rows derived from the saved tool-definition scan are pinned to exact
        # codes; that report is what they are a transcription of. Features measured by
        # other means (result capture, adapter surface probes) have their own evidence,
        # so this check holds them to the vocabulary and the note requirement instead.
        if not capability["reproduce"].startswith("uvx mcp-mirror scan"):
            for agent_id, code in (
                ("openai-agents", openai_code),
                ("pydantic-ai", pydantic_code),
            ):
                assert code in {"y", "a", "n"}, (capability_id, agent_id, code)
                if code != "y":
                    cell = stats[agent_id][agents[agent_id]["current_version"]]
                    assert "#" in cell, (capability_id, agent_id, cell)
                    assert capability["notes_by_num"][cell.split("#")[1]].strip()
            continue

        if capability_id in BEHAVIOR_ANNOTATIONS:
            assert (openai_code, pydantic_code) == ("n", "a")
        elif capability_id == "title-annotation":
            assert (openai_code, pydantic_code) == ("a", "a")
        elif capability_id == "tool-icons":
            # The only part of a tool definition aimed at a human, and the only one
            # neither adapter carries.
            assert (openai_code, pydantic_code) == ("n", "n")
        else:
            assert (openai_code, pydantic_code) == ("y", "y")
