from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mirror.runner_manifests import (
    ManagedRunnerUnavailable,
    build_managed_source_command,
    build_managed_worker_command,
    load_runner_manifests,
)


def test_runner_manifests_cover_the_launch_renderers_with_pinned_packages():
    manifests = load_runner_manifests()

    assert set(manifests) == {
        "langchain",
        "pydantic_ai",
        "crewai",
        "openai_agents",
        "mastra",
    }
    for renderer_id, manifest in manifests.items():
        assert manifest.module.startswith(".")
        assert manifest.protocols
        assert manifest.packages
        assert len(manifest.digest) == 64
        for package in manifest.packages:
            if manifest.runtime == "python":
                assert "==" in package, (renderer_id, package)
            else:
                assert package.rsplit("@", 1)[-1][0].isdigit(), (
                    renderer_id,
                    package,
                )


def test_managed_python_command_is_argument_safe_and_manifest_driven():
    command = build_managed_worker_command(
        "pydantic_ai",
        Path("/tmp/report worker.json"),
        uv_executable="/opt/homebrew/bin/uv",
    )

    assert command[:6] == [
        "/opt/homebrew/bin/uv",
        "run",
        "--isolated",
        "--no-project",
        "--python",
        "3.11",
    ]
    assert "mcp==2.0.0" in command
    assert "pydantic-ai-slim[mcp]==2.40.0" in command
    assert command[-5:] == [
        "python",
        "-m",
        "mcp_mirror._render_worker",
        "pydantic_ai",
        "/tmp/report worker.json",
    ]


def test_managed_python_command_rejects_node_runner():
    with pytest.raises(ManagedRunnerUnavailable, match="Node"):
        build_managed_worker_command(
            "mastra",
            Path("/tmp/out.json"),
            uv_executable="/usr/bin/uv",
        )


@pytest.mark.parametrize(
    ("spec_version", "mcp_package"),
    [
        ("2025-11-25", "mcp==1.26.0"),
        ("2026-07-28", "mcp==2.0.0"),
        (None, "mcp==2.0.0"),
    ],
)
def test_managed_source_command_selects_the_protocol_sdk(
    spec_version,
    mcp_package,
):
    command = build_managed_source_command(
        spec_version,
        Path("/tmp/source.json"),
        uv_executable="/usr/bin/uv",
    )

    assert mcp_package in command
    assert command[-4:] == [
        "-m",
        "mcp_mirror._source_worker",
        "/tmp/source.json",
        spec_version or "2026-07-28",
    ]
