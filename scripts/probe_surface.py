"""Report which MCP capability surfaces each 2026-07-28 adapter exposes.

Resources, prompts and the client features (sampling, elicitation, roots) are not
measured by diffing a tool definition: the question is whether the adapter offers the
agent any route to them at all. That is answered by inspecting the adapter's own API in
the version the snapshot pins, which is what this does.

    uv run python scripts/probe_surface.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp_mirror.runner_manifests import load_runner_manifests  # noqa: E402

# Substrings that identify each capability on an adapter's public API.
PROBES = {
    "resources": ("resource",),
    "prompts": ("prompt",),
    "sampling": ("sampling", "sample"),
    "elicitation": ("elicit",),
    "roots": ("root",),
    "completion": ("complet",),
    "subscriptions": ("subscribe", "subscription"),
    "logging": ("logging", "set_level", "setlevel"),
    "progress": ("progress",),
    "cancellation": ("cancel",),
    "pagination": ("cursor", "paginate", "next_page"),
}

TARGETS = {
    "openai_agents": [
        ("agents.mcp", "MCPServer"),
        ("agents.mcp", "MCPServerStdio"),
        ("agents.mcp.util", "MCPUtil"),
    ],
    "pydantic_ai": [
        ("pydantic_ai.mcp", "MCPToolset"),
    ],
}

SCRIPT = """
import importlib, json
out = {}
for module_name, attr in %(targets)r:
    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
    except Exception as exc:
        out[attr] = {"error": "%%s: %%s" %% (type(exc).__name__, exc)}
        continue
    names = [n for n in dir(obj) if not n.startswith("__")]
    out[attr] = {
        key: sorted(n for n in names if any(s in n.lower() for s in subs))
        for key, subs in %(probes)r.items()
    }
    out[attr]["_module_members"] = sorted(
        n for n in dir(importlib.import_module(module_name)) if not n.startswith("_")
    )[:60]
print(json.dumps(out))
"""


def run(renderer_id: str) -> dict:
    manifest = load_runner_manifests()[renderer_id]
    command = ["uv", "run", "--isolated", "--no-project", "--python", manifest.python or "3.11"]
    for package in manifest.packages:
        command.extend(["--with", package])
    script = SCRIPT % {"targets": TARGETS[renderer_id], "probes": PROBES}
    command.extend(["python", "-c", script])

    proc = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise SystemExit(f"{renderer_id} probe failed:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout)


def main() -> int:
    for renderer_id in TARGETS:
        print(f"\n########## {renderer_id} ##########")
        for attr, found in run(renderer_id).items():
            print(f"\n--- {attr} ---")
            if "error" in found:
                print("   ", found["error"])
                continue
            for key in PROBES:
                names = found.get(key) or []
                print(f"   {key:<15} {'YES ' if names else 'no  '} {', '.join(names[:6])}")
            print(f"   module members: {', '.join(found['_module_members'][:25])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
