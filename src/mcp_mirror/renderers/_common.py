"""Shared helpers for renderers."""

from __future__ import annotations

from importlib import metadata


def dist_version(dist_name: str) -> str:
    try:
        return metadata.version(dist_name)
    except Exception:
        return "unknown"
