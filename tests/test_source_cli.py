"""Transport and CLI contract tests.

The stdio source path is exercised by ``test_renderers``. These tests cover the
other public source transport and the documented process exit codes without
using an external server.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import warnings
from pathlib import Path

from typer.testing import CliRunner

from mcp_mirror.cli import app
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
    def fail_to_load(_handle):
        raise SourceConnectionError("fixture unavailable")

    monkeypatch.setattr("mcp_mirror.cli.load_source", fail_to_load)
    result = RUNNER.invoke(app, ["scan", "missing-command"])

    assert result.exit_code == 2
    assert "connection/handshake error" in result.stderr


def test_cli_returns_3_for_spec_version_mismatch(monkeypatch):
    monkeypatch.setattr(
        "mcp_mirror.cli.load_source",
        lambda _handle: ("2025-11-25", []),
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
