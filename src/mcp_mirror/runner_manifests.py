"""Validated manifests for reproducible framework runner environments."""

from __future__ import annotations

import json
import shutil
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import canonical_sha256
from .models import CaptureStage


class ManagedRunnerUnavailable(RuntimeError):
    """Raised when a manifest cannot run through the local managed-runner path."""


class RunnerManifest(BaseModel):
    """One versioned adapter environment and its evidence contract."""

    model_config = ConfigDict(frozen=True)

    id: str
    module: str
    runtime: Literal["python", "node"]
    python: str | None = None
    node: str | None = None
    packages: tuple[str, ...] = Field(min_length=1)
    protocols: tuple[str, ...] = Field(min_length=1)
    capture_stage: CaptureStage
    provider_request_captured: bool

    @model_validator(mode="after")
    def validate_runtime_version(self) -> "RunnerManifest":
        if self.runtime == "python" and not self.python:
            raise ValueError("Python runner requires a python version")
        if self.runtime == "node" and not self.node:
            raise ValueError("Node runner requires a node version")
        return self

    @property
    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


@lru_cache(maxsize=1)
def load_runner_manifests() -> dict[str, RunnerManifest]:
    """Load and validate the package's runner manifest registry."""

    manifest_path = files("mcp_mirror").joinpath("runner-manifests.json")
    payload = json.loads(manifest_path.read_text())
    if payload.get("schema") != "mcp-mirror/runner-manifests@1":
        raise ValueError("unsupported runner manifest schema")
    raw_runners = payload.get("runners")
    if not isinstance(raw_runners, dict) or not raw_runners:
        raise ValueError("runner manifest registry is empty")

    return {
        renderer_id: RunnerManifest.model_validate(
            {"id": renderer_id, **runner}
        )
        for renderer_id, runner in raw_runners.items()
    }


def build_managed_worker_command(
    renderer_id: str,
    output_path: Path,
    *,
    uv_executable: str | None = None,
) -> list[str]:
    """Build an argument-safe ``uv`` command for one Python runner."""

    manifest = load_runner_manifests().get(renderer_id)
    if manifest is None:
        raise ManagedRunnerUnavailable(
            f"no managed runner manifest for {renderer_id!r}"
        )
    if manifest.runtime != "python":
        raise ManagedRunnerUnavailable(
            f"managed Node runner for {renderer_id!r} is not implemented"
        )

    uv = uv_executable or shutil.which("uv")
    if not uv:
        raise ManagedRunnerUnavailable(
            "managed Python runners require uv: https://docs.astral.sh/uv/"
        )

    command = [
        uv,
        "run",
        "--isolated",
        "--no-project",
        "--python",
        manifest.python or "3.11",
    ]
    for package in manifest.packages:
        command.extend(["--with", package])
    command.extend(
        [
            "python",
            "-m",
            "mcp_mirror._render_worker",
            renderer_id,
            str(output_path),
        ]
    )
    return command


def build_managed_source_command(
    expected_spec_version: str | None,
    output_path: Path,
    *,
    uv_executable: str | None = None,
) -> list[str]:
    """Build the direct-source command in a protocol-compatible SDK environment."""

    uv = uv_executable or shutil.which("uv")
    if not uv:
        raise ManagedRunnerUnavailable(
            "managed source connections require uv: https://docs.astral.sh/uv/"
        )

    profile = managed_source_profile(expected_spec_version)
    mcp_package = profile["packages"][0]
    protocol_hint = (
        expected_spec_version
        if expected_spec_version is not None
        else "2026-07-28"
    )
    return [
        uv,
        "run",
        "--isolated",
        "--no-project",
        "--python",
        profile["python"],
        "--with",
        mcp_package,
        "python",
        "-m",
        "mcp_mirror._source_worker",
        str(output_path),
        protocol_hint,
    ]


def managed_source_profile(
    expected_spec_version: str | None,
) -> dict[str, object]:
    """Return the canonical managed direct-source environment."""

    modern = (
        expected_spec_version is None
        or expected_spec_version >= "2026-07-28"
    )
    return {
        "runtime": "python",
        "python": "3.11",
        "packages": [
            "mcp==2.0.0" if modern else "mcp==1.26.0",
        ],
    }


def managed_source_digest(expected_spec_version: str | None) -> str:
    return canonical_sha256(managed_source_profile(expected_spec_version))
