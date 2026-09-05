"""Human and machine report evidence contracts."""

from __future__ import annotations

from rich.console import Console

from mcp_mirror.models import FrameworkRun, RendererEvidence, Report
from mcp_mirror.report import render_markdown, render_table, report_to_dict


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
    assert "J1 desc" in markdown
    assert "J5 authz" in markdown
    assert "J2 params" not in markdown
    assert "## J5 authorization findings" in markdown
