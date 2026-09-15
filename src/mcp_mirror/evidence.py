"""Canonical evidence helpers shared by CLI and hosted runners."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CaptureObservation, ObservationStage, ScanProvenance, ToolRep


def canonical_sha256(value: Any) -> str:
    """Hash a JSON value after stable, whitespace-free serialization."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


REDACTION_PLACEHOLDER = "<redacted>"


def scrub_secrets(value: Any, secrets: Sequence[str]) -> Any:
    """Replace every occurrence of ``secrets`` in any nested string."""

    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTION_PLACEHOLDER)
        return value
    if isinstance(value, dict):
        return {key: scrub_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_secrets(item, secrets) for item in value]
    return value


def observe_tools(
    *,
    stage: ObservationStage,
    capture_api: str,
    capture_object: str,
    tools: list[ToolRep],
    artifact: Any | None = None,
    limitation: str | None = None,
    secrets: Sequence[str] = (),
) -> CaptureObservation:
    """Build a normalized observation and bind it to a content hash.

    A server controls its own tool metadata, so anything we send it can come back
    inside a description or a raw payload. Scrubbing here keeps a credential from
    reaching the stored observation on the success path, where no error-message
    redaction runs, and hashes what we actually persist.
    """

    usable = [secret for secret in secrets if secret]
    normalized = [tool.model_dump(mode="json") for tool in tools]
    scrubbed = scrub_secrets(normalized, usable) if usable else normalized
    redacted = scrubbed != normalized
    if redacted:
        tools = [ToolRep.model_validate(rep) for rep in scrubbed]

    if artifact is not None and usable:
        scrubbed_artifact = scrub_secrets(artifact, usable)
        redacted = redacted or scrubbed_artifact != artifact
        artifact = scrubbed_artifact

    evidence_artifact = artifact if artifact is not None else scrubbed
    return CaptureObservation(
        stage=stage,
        capture_api=capture_api,
        capture_object=capture_object,
        tools=tools,
        artifact_sha256=canonical_sha256(evidence_artifact),
        artifact=artifact,
        limitation=limitation,
        redacted=redacted,
    )


def scan_provenance(scanner_version: str) -> ScanProvenance:
    """Capture reproducibility metadata without making Git a hard dependency."""

    return ScanProvenance(
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        scanner_version=scanner_version,
        scanner_commit=_git_commit(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        runner_digest=os.environ.get("MCP_MIRROR_RUNNER_DIGEST"),
    )


def _git_commit() -> str | None:
    root = Path(__file__).resolve().parents[2]
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None
