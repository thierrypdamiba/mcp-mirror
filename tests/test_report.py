"""Human and machine report evidence contracts."""

from __future__ import annotations

from rich.console import Console

from mcp_mirror.evidence import observe_tools
from mcp_mirror.models import (
    FrameworkRun,
    RendererEvidence,
    Report,
    ScanConfiguration,
)
from mcp_mirror.report import render_markdown, render_table, report_to_dict
from mcp_mirror.models import ToolRep


def _report() -> Report:
    return Report(
        mcp_server="python fixture.py",
        mcp_spec_version="2025-11-25",
        generated_with="mcp-mirror/test",
        tools=["example"],
        runs=[
            FrameworkRun(
                framework="example_framework",
                framework_version="1.2.3",
                adapter_version="4.5.6",
                evidence=RendererEvidence(
                    capture_api="example.adapter.list_tools",
                    capture_object="ExampleTool",
                    capture_stage="framework_tool_definition",
                    provider_request_captured=False,
                    negotiated_mcp_spec_version=None,
                    protocol_version_evidence=(
                        "the adapter does not expose the negotiated MCP protocol version"
                    ),
                    limitation="no serialized provider request was captured",
                ),
            )
        ],
    )


def test_json_report_preserves_source_and_renderer_protocol_evidence():
    data = report_to_dict(_report())

    assert data["mcp_spec_version"] == "2025-11-25"
    assert (
        data["mcp_spec_version_evidence"]
        == "direct source connection initialize result"
    )
    evidence = data["runs"][0]["evidence"]
    assert evidence["capture_api"] == "example.adapter.list_tools"
    assert evidence["provider_request_captured"] is False
    assert evidence["negotiated_mcp_spec_version"] is None


def test_report_v2_binds_normalized_observations_to_stable_hashes():
    tool = ToolRep(
        name="example",
        description="Example tool",
        params={"type": "object", "properties": {}},
        origin="source",
    )
    first = observe_tools(
        stage="source",
        capture_api="session.list_tools",
        capture_object="ListToolsResult",
        tools=[tool],
    )
    second = observe_tools(
        stage="source",
        capture_api="session.list_tools",
        capture_object="ListToolsResult",
        tools=[tool],
    )
    report = _report()
    report.source_observation = first

    data = report_to_dict(report)

    assert data["schema"] == "mcp-mirror/report@2"
    assert first.artifact_sha256 == second.artifact_sha256
    assert data["source_observation"]["artifact_sha256"] == first.artifact_sha256


def test_human_reports_label_capture_boundaries_and_protocol_unknowns():
    report = _report()
    markdown = render_markdown(report)
    console = Console(record=True, width=240)
    render_table(report, console)
    terminal = console.export_text()

    for rendered in (markdown, terminal):
        normalized = " ".join(rendered.split())
        assert "source-negotiated MCP spec: 2025-11-25" in normalized
        assert "example.adapter.list_tools" in normalized
        assert "provider request: not captured" in normalized
        assert "adapter-negotiated MCP spec: not exposed" in normalized


def test_job_filter_cannot_remove_mandatory_j5():
    data = report_to_dict(_report(), jobs_filter=["J1"])
    markdown = render_markdown(_report(), jobs_filter=["J1"])

    assert [job["id"] for job in data["scorecard"]["jobs"]] == ["J1", "J5"]
    assert "J1 identity" in markdown
    assert "J5 authz" in markdown
    assert "J2 params" not in markdown
    assert "## J5 authorization findings" in markdown


def test_human_reports_explain_incomplete_runs_without_calling_them_faithful():
    report = _report()
    report.runs[0].status = "adapter_error"
    report.runs[0].status_detail = "adapter exploded"

    markdown = render_markdown(report)
    console = Console(record=True, width=240)
    render_table(report, console)
    terminal = console.export_text()

    for rendered in (markdown, terminal):
        normalized = " ".join(rendered.split()).lower()
        assert "adapter error" in normalized
        assert "adapter exploded" in normalized
        assert "fully faithful" not in normalized


def test_human_reports_include_a_secret_free_reproduction_command():
    report = _report()
    report.runs[0].runner_digest = "a" * 64
    report.scan = ScanConfiguration(
        transport="http",
        frameworks=["example_framework"],
        header_names=["Authorization"],
        runner_mode="managed",
    )

    markdown = render_markdown(report)
    console = Console(record=True, width=400)
    render_table(report, console)
    terminal = console.export_text()

    for rendered in (markdown, terminal):
        normalized = " ".join(rendered.split())
        assert "mcp-mirror scan" in normalized
        assert "--frameworks example_framework" in normalized
        assert "--spec-version 2025-11-25" in normalized
        assert "--runner managed" in normalized
        assert "Authorization: ${AUTHORIZATION}" in normalized
        assert "--fail-on-incomplete" in normalized
        assert f"sha256:{'a' * 64}" in normalized
