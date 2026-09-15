"""Transport and CLI contract tests.

The stdio source path is exercised by ``test_renderers``. These tests cover the
other public source transport and the documented process exit codes without
using an external server.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import warnings
from pathlib import Path

from typer.testing import CliRunner

from mcp_mirror import __version__
from mcp_mirror.cli import _managed_environment, _render_isolated, app
from mcp_mirror.models import RendererEvidence, Report, ToolRep
from mcp_mirror.renderers import RenderError
from mcp_mirror.runner_manifests import load_runner_manifests
from mcp_mirror.source import SourceConnectionError, load_source, parse_server


ROOT = Path(__file__).resolve().parents[1]
HTTP_FIXTURE = ROOT / "fixtures" / "http_server.py"
RUNNER = CliRunner()


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"HTTP fixture exited {process.returncode}: {stdout}\n{stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("HTTP fixture did not start within 10 seconds")


def test_http_source_loader_reads_local_fixture():
    assert HTTP_FIXTURE.exists(), "the local streamable-HTTP fixture is required"
    port = _unused_port()
    process = subprocess.Popen(
        [sys.executable, str(HTTP_FIXTURE), "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(port, process)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            spec_version, reps = load_source(
                parse_server(f"http://127.0.0.1:{port}/mcp")
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    assert spec_version and spec_version != "unknown"
    assert [rep.name for rep in reps] == ["http_ping"]
    assert reps[0].annotations["readOnlyHint"] is True
    assert not any(
        "streamable_http_client" in str(warning.message) for warning in caught
    )


def test_cli_returns_2_for_connection_failure(monkeypatch):
    def fail_to_load(_handle, _expected_spec_version=None):
        raise SourceConnectionError("fixture unavailable")

    monkeypatch.setattr("mcp_mirror.cli.load_source", fail_to_load)
    result = RUNNER.invoke(app, ["scan", "missing-command"])

    assert result.exit_code == 2
    assert "connection/handshake error" in result.stderr


def test_cli_rejects_malformed_headers_before_connecting(monkeypatch):
    connected = False

    def load(_handle, _expected_spec_version=None):
        nonlocal connected
        connected = True
        return "2025-11-25", []

    monkeypatch.setattr("mcp_mirror.cli.load_source", load)
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        ["scan", "unused-command", "--header", "Authorization"],
    )

    assert result.exit_code == 2
    assert "Name: Value" in result.stderr
    assert connected is False


def test_cli_rejects_an_unset_header_environment_variable(
    monkeypatch,
):
    monkeypatch.delenv("MCP_MIRROR_MISSING_TOKEN", raising=False)
    connected = False

    def load(_handle, _expected_spec_version=None):
        nonlocal connected
        connected = True
        return "2025-11-25", []

    monkeypatch.setattr("mcp_mirror.cli.load_source", load)
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--header",
            "Authorization: Bearer ${MCP_MIRROR_MISSING_TOKEN}",
        ],
    )

    assert result.exit_code == 2
    assert "MCP_MIRROR_MISSING_TOKEN" in result.stderr
    assert "not set" in result.stderr
    assert connected is False


def test_cli_rejects_ci_drift_flag_without_a_baseline(monkeypatch):
    connected = False

    def load(_handle, _expected_spec_version=None):
        nonlocal connected
        connected = True
        return "2025-11-25", []

    monkeypatch.setattr("mcp_mirror.cli.load_source", load)
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        ["scan", "unused-command", "--fail-on-drift"],
    )

    assert result.exit_code == 2
    assert "--fail-on-drift requires --baseline" in result.stderr
    assert connected is False


def test_cli_returns_3_for_spec_version_mismatch(monkeypatch):
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", []),
    )
    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--spec-version",
            "2026-07-28",
        ],
    )

    assert result.exit_code == 3
    assert "spec-version assertion failed" in result.stderr


def test_cli_returns_3_when_renderer_negotiates_another_spec(monkeypatch):
    source = ToolRep(name="example", origin="mcp")
    rendered = ToolRep(name="example", origin="framework")
    evidence = RendererEvidence(
        capture_api="framework.list_tools",
        capture_object="Tool",
        capture_stage="framework_tool_definition",
        provider_request_captured=False,
        negotiated_mcp_spec_version="2026-07-28",
        protocol_version_evidence="initialize result",
    )

    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"framework": object()}, []),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli._render_isolated",
        lambda _rid, _server, _headers: (
            {"framework": "1.0", "adapter": "1.0"},
            evidence,
            [rendered],
        ),
    )

    result = RUNNER.invoke(app, ["scan", "unused-command"])

    assert result.exit_code == 3
    assert "renderer spec-version mismatch" in result.stderr


def test_cli_writes_protocol_mismatch_evidence_before_exiting(
    monkeypatch,
    tmp_path,
):
    source = ToolRep(name="example", origin="mcp")
    rendered = ToolRep(name="example", origin="framework")
    evidence = RendererEvidence(
        capture_api="framework.list_tools",
        capture_object="FrameworkTool",
        capture_stage="framework_tool_definition",
        provider_request_captured=False,
        negotiated_mcp_spec_version="2026-07-28",
        protocol_version_evidence="initialize result",
    )
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"framework": object()}, []),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli._render_isolated",
        lambda _rid, _server, _headers: (
            {"framework": "1.0", "adapter": "2.0"},
            evidence,
            [rendered],
        ),
    )

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--output",
            "json",
            "--out",
            str(report_path),
        ],
    )

    assert result.exit_code == 3
    report = json.loads(report_path.read_text())
    run = report["runs"][0]
    assert run["status"] == "protocol_mismatch"
    assert "2026-07-28" in run["status_detail"]
    assert run["observations"][0]["stage"] == "framework_tool_definition"


def test_cli_writes_current_report_before_rejecting_bad_baseline(
    monkeypatch,
    tmp_path,
):
    source = ToolRep(name="example", origin="mcp")
    baseline_path = tmp_path / "bad-baseline.json"
    report_path = tmp_path / "current-report.json"
    baseline_path.write_text("not json")

    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--baseline",
            str(baseline_path),
            "--out",
            str(report_path),
        ],
    )

    assert result.exit_code == 2
    assert json.loads(report_path.read_text())["tools"] == ["example"]


def test_cli_json_report_includes_reproducible_observations(monkeypatch):
    source = ToolRep(
        name="example",
        description="Source definition",
        params={"type": "object", "properties": {}},
        origin="mcp",
        raw={"name": "example", "description": "Source definition"},
    )
    rendered = ToolRep(
        name="example",
        description="Rendered definition",
        params={"type": "object", "properties": {}},
        origin="framework",
        raw={"type": "function", "function": {"name": "example"}},
    )
    evidence = RendererEvidence(
        capture_api="framework.list_tools",
        capture_object="FrameworkTool",
        capture_stage="framework_tool_definition",
        provider_request_captured=False,
        negotiated_mcp_spec_version="2025-11-25",
        protocol_version_evidence="initialize result",
        limitation="provider request not captured",
    )

    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"framework": object()}, []),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli._render_isolated",
        lambda _rid, _server, _headers: (
            {"framework": "1.2.3", "adapter": "4.5.6"},
            evidence,
            [rendered],
        ),
    )

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--frameworks",
            "framework",
            "--header",
            "Authorization: Bearer super-secret",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["schema"] == "mcp-mirror/report@2"
    assert report["attestation"] == "local"
    assert report["provenance"]["scanner_version"] == __version__
    assert report["scan"] == {
        "transport": "stdio",
        "frameworks": ["framework"],
        "spec_version_assertion": None,
        "jobs": [],
        "jtbd": None,
        "header_names": ["Authorization"],
        "runner_mode": "local_subprocess",
    }
    assert "super-secret" not in json.dumps(report)
    assert report["source_observation"]["stage"] == "source"
    assert report["source_observation"]["redacted"] is False
    assert len(report["source_observation"]["artifact_sha256"]) == 64

    observation = report["runs"][0]["observations"][0]
    assert observation["stage"] == "framework_tool_definition"
    assert observation["capture_api"] == "framework.list_tools"
    assert observation["capture_object"] == "FrameworkTool"
    assert observation["limitation"] == "provider request not captured"
    assert len(observation["artifact_sha256"]) == 64


def test_cli_records_requested_missing_framework_and_can_fail_on_it(monkeypatch):
    source = ToolRep(name="example", origin="mcp")
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, ["missing_framework"]),
    )

    advisory = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--frameworks",
            "missing_framework",
            "--output",
            "json",
        ],
    )

    assert advisory.exit_code == 0
    report = json.loads(advisory.stdout)
    run = report["runs"][0]
    assert run["framework"] == "missing_framework"
    assert run["status"] == "unsupported"
    assert "not installed" in run["status_detail"]
    scorecard = report["scorecard"]["frameworks"]["missing_framework"]
    assert scorecard["status"] == "unsupported"
    assert {
        cell["verdict"]
        for cell in scorecard["jobs"].values()
    } == {"unmeasured"}

    strict = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--frameworks",
            "missing_framework",
            "--output",
            "json",
            "--fail-on-incomplete",
        ],
    )

    assert strict.exit_code == 4
    assert json.loads(strict.stdout)["runs"][0]["status"] == "unsupported"


def test_cli_records_adapter_error_instead_of_silently_skipping(monkeypatch):
    source = ToolRep(name="example", origin="mcp")
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"broken_framework": object()}, []),
    )

    def fail_to_render(_rid, _server, _headers):
        raise RenderError("adapter exploded")

    monkeypatch.setattr("mcp_mirror.cli._render_isolated", fail_to_render)

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--frameworks",
            "broken_framework",
            "--output",
            "json",
            "--fail-on-incomplete",
        ],
    )

    assert result.exit_code == 4
    report = json.loads(result.stdout)
    run = report["runs"][0]
    assert run["framework"] == "broken_framework"
    assert run["status"] == "adapter_error"
    assert run["status_detail"] == "adapter exploded"
    assert (
        report["scorecard"]["frameworks"]["broken_framework"]["jobs"]["J1"][
            "verdict"
        ]
        == "unmeasured"
    )


def test_cli_redacts_header_secrets_from_adapter_errors(monkeypatch):
    source = ToolRep(name="example", origin="mcp")
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"broken_framework": object()}, []),
    )

    def fail_to_render(_rid, _server, _headers):
        raise RenderError(
            "request failed with Authorization: Bearer leaked-secret"
        )

    monkeypatch.setattr("mcp_mirror.cli._render_isolated", fail_to_render)

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--frameworks",
            "broken_framework",
            "--header",
            "Authorization: Bearer leaked-secret",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    rendered = f"{result.stdout}\n{result.stderr}"
    assert "leaked-secret" not in rendered
    assert "<redacted>" in rendered


def test_cli_redacts_url_credentials_from_reports(monkeypatch):
    original_url = (
        "https://user:password@example.com/mcp"
        "?transport=stream&access_token=leaked-token#client-state"
    )
    source = ToolRep(name="example", origin="mcp")

    def load(handle, _expected_spec_version=None):
        assert handle.spec == original_url
        return "2025-11-25", [source]

    monkeypatch.setattr("mcp_mirror.cli.load_source", load)
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        ["scan", original_url, "--output", "json"],
    )

    assert result.exit_code == 0
    assert "password" not in result.stdout
    assert "leaked-token" not in result.stdout
    assert "client-state" not in result.stdout
    report = json.loads(result.stdout)
    assert report["mcp_server"] == (
        "https://example.com/mcp"
        "?transport=stream&access_token=<redacted>"
    )


def test_cli_redacts_stdio_secret_arguments_from_reports(monkeypatch):
    original_command = (
        "python server.py --token leaked-token "
        "--mode safe --api-key=also-leaked"
    )
    source = ToolRep(name="example", origin="mcp")

    def load(handle, _expected_spec_version=None):
        assert handle.spec == original_command
        return "2025-11-25", [source]

    monkeypatch.setattr("mcp_mirror.cli.load_source", load)
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        ["scan", original_command, "--output", "json"],
    )

    assert result.exit_code == 0
    assert "leaked-token" not in result.stdout
    assert "also-leaked" not in result.stdout
    report = json.loads(result.stdout)
    assert report["mcp_server"] == (
        "python server.py --token '<redacted>' "
        "--mode safe '--api-key=<redacted>'"
    )


def test_cli_managed_runner_needs_no_preinstalled_framework(monkeypatch):
    source = ToolRep(name="example", origin="mcp")
    rendered = ToolRep(name="example", origin="framework")
    evidence = RendererEvidence(
        capture_api="pydantic_ai.mcp.MCPToolset.get_tools",
        capture_object="ToolDefinition",
        capture_stage="framework_tool_definition",
        provider_request_captured=False,
        negotiated_mcp_spec_version="2026-07-28",
        protocol_version_evidence="client protocol_version",
    )
    seen_modes: list[str] = []

    monkeypatch.setattr(
        "mcp_mirror.cli._load_source_managed",
        lambda _handle, _expected_spec_version=None: ("2026-07-28", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("managed mode used the host MCP SDK")
        ),
    )

    def render(_rid, _server, _headers, runner_mode="local_subprocess"):
        seen_modes.append(runner_mode)
        return (
            {"framework": "2.40.0", "adapter": "2.40.0"},
            evidence,
            [rendered],
        )

    monkeypatch.setattr("mcp_mirror.cli._render_isolated", render)

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--frameworks",
            "pydantic_ai",
            "--runner",
            "managed",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert seen_modes == ["managed"]
    report = json.loads(result.stdout)
    assert report["scan"]["runner_mode"] == "managed"
    assert len(report["provenance"]["runner_digest"]) == 64
    run = report["runs"][0]
    assert run["status"] == "measured"
    assert (
        run["runner_digest"]
        == load_runner_manifests()["pydantic_ai"].digest
    )


def test_cli_writes_source_spec_mismatch_evidence_before_exiting(
    monkeypatch,
    tmp_path,
):
    """A failed --spec-version assertion still owes the caller its evidence.

    Exiting straight from the assertion produced no report at all, so the one
    artifact showing what the server actually negotiated never reached disk.
    """

    source = ToolRep(name="example", origin="mcp")
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"framework": object()}, []),
    )

    def unreachable(*_args, **_kwargs):
        raise AssertionError("renderers must not run against a mismatched source")

    monkeypatch.setattr("mcp_mirror.cli._render_isolated", unreachable)

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--spec-version",
            "2026-07-28",
            "--output",
            "json",
            "--out",
            str(report_path),
        ],
    )

    assert result.exit_code == 3
    report = json.loads(report_path.read_text())
    assert report["mcp_spec_version"] == "2025-11-25"
    assert report["scan"]["spec_version_assertion"] == "2026-07-28"
    assert report["source_observation"]["tools"][0]["name"] == "example"


def test_cli_redacts_header_secrets_reflected_in_tool_metadata(monkeypatch):
    """A server writes its own tool metadata, so it can echo our token back.

    Error-path redaction never runs on a successful scan, which let a reflected
    credential land in the stored observation.
    """

    source = ToolRep(
        name="example",
        origin="mcp",
        description="authenticate with Bearer leaked-secret",
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({}, []),
    )

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--header",
            "Authorization: Bearer leaked-secret",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert "leaked-secret" not in result.stdout
    report = json.loads(result.stdout)
    assert report["source_observation"]["redacted"] is True
    assert "<redacted>" in report["source_observation"]["tools"][0]["description"]


def test_render_isolated_survives_a_worker_that_reports_no_versions(monkeypatch):
    """``payload.get("versions", {})`` returns None when the key holds null.

    The default never fired, so a None reached the scan loop and only failed
    later, outside the RenderError handler that would have recorded it.
    """

    payload = {
        "ok": True,
        "versions": None,
        "evidence": {
            "capture_api": "framework.list_tools",
            "capture_object": "FrameworkTool",
            "capture_stage": "framework_tool_definition",
            "provider_request_captured": False,
            "negotiated_mcp_spec_version": "2025-11-25",
            "protocol_version_evidence": "initialize result",
        },
        "reps": [{"name": "example", "origin": "framework"}],
    }

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("mcp_mirror.cli.subprocess.run", fake_run)

    versions, _evidence, reps = _render_isolated("framework", "unused", {})

    assert versions == {}
    assert [rep.name for rep in reps] == ["example"]


def test_incomplete_scan_outranks_drift_in_the_exit_code(monkeypatch, tmp_path):
    """Drift measured from a partial scan is not a trustworthy drift signal.

    With both gates on, the caller should learn the scan cannot be believed
    rather than read its conclusion.
    """

    source = ToolRep(name="example", origin="mcp")
    rendered = ToolRep(name="example", origin="framework")
    evidence = RendererEvidence(
        capture_api="framework.list_tools",
        capture_object="FrameworkTool",
        capture_stage="framework_tool_definition",
        provider_request_captured=False,
        negotiated_mcp_spec_version="2025-11-25",
        protocol_version_evidence="initialize result",
    )
    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle, _expected_spec_version=None: ("2025-11-25", [source]),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli.select_renderers",
        lambda _requested: ({"framework": object()}, []),
    )
    monkeypatch.setattr(
        "mcp_mirror.cli._render_isolated",
        lambda _rid, _server, _headers: (
            {"framework": "1.0"},
            evidence,
            [rendered],
        ),
    )

    baseline_result = RUNNER.invoke(
        app,
        ["scan", "unused-command", "--out", str(baseline_path)],
    )
    assert baseline_result.exit_code == 0

    def fail_to_render(_rid, _server, _headers):
        raise RenderError("adapter exploded")

    monkeypatch.setattr("mcp_mirror.cli._render_isolated", fail_to_render)

    result = RUNNER.invoke(
        app,
        [
            "scan",
            "unused-command",
            "--baseline",
            str(baseline_path),
            "--fail-on-drift",
            "--fail-on-incomplete",
        ],
    )

    assert result.exit_code == 4


def test_managed_environment_does_not_inherit_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/tmp/host-environment-packages")

    environment = _managed_environment()

    assert "/tmp/host-environment-packages" not in environment["PYTHONPATH"]


def test_managed_environment_exposes_only_this_package():
    """A wheel install must not put its whole site-packages on the runner path.

    ``mcp_mirror`` sits directly in ``site-packages`` once installed from a
    wheel, so handing the managed interpreter its parent directory would
    override every dependency the manifest pinned.
    """

    environment = _managed_environment()

    roots = environment["PYTHONPATH"].split(os.pathsep)
    assert len(roots) == 1
    assert [entry.name for entry in Path(roots[0]).iterdir()] == ["mcp_mirror"]
    assert (Path(roots[0]) / "mcp_mirror" / "cli.py").exists()


def test_frameworks_command_prints_actionable_setup_commands(monkeypatch):
    monkeypatch.setattr("mcp_mirror.cli.available_renderers", lambda: {})

    result = RUNNER.invoke(app, ["frameworks"])

    assert result.exit_code == 0
    assert "mcp-mirror[langchain]" in result.stdout
    assert "mcp-mirror[pydantic-ai]" in result.stdout
    assert "mcp-mirror[openai-agents]" in result.stdout
    assert "Mastra Node runner" in result.stdout
    assert "--runner managed" in result.stdout


def test_show_renders_a_saved_report_without_rescanning(tmp_path):
    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    report = Report(
        mcp_server="python server.py",
        mcp_spec_version="2025-11-25",
        generated_with="mcp-mirror/test",
        tools=["example"],
    )
    report_path.write_text(report.model_dump_json(by_alias=True))

    result = RUNNER.invoke(
        app,
        [
            "show",
            str(report_path),
            "--output",
            "md",
            "--out",
            str(markdown_path),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    markdown = markdown_path.read_text()
    assert "source-negotiated MCP spec: 2025-11-25" in markdown
    assert "**The job:**" in markdown
