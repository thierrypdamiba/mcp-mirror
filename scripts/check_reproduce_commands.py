"""Execute every reproduce command the site publishes, from a clean checkout.

Each measured capability publishes one command that is supposed to re-derive its row.
Nothing checked that the commands ran, so they rotted in two directions at once: they
named a package that was never uploaded to PyPI, and they reached for a virtualenv that
existed on one laptop. Both failures are invisible from inside a developer environment
that already has everything, which is why this runs somewhere that has nothing.

    uv run python scripts/check_reproduce_commands.py

Tracked files are copied to a temporary directory, so the run sees the working tree as
a fresh clone would see it: no .venv, no node_modules, no fixture interpreter, no
uncommitted scratch files. A command passes only if it exits 0 and prints none of the
markers below, because several of these commands report a dead renderer on stdout and
still exit 0.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILT_DATA = ROOT / "data" / "fulldata"

# Exiting 0 is not enough. A renderer that cannot start is reported in the body of the
# output by the measurement scripts, and uv reports an unresolvable package the same
# way, so the text has to be read as well as the status.
FAILURE_MARKERS = (
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "command not found",
    "was not found in the package registry",
    "FAILED:",
    "adapter error:",
    "no frameworks scanned",
)

# Commands that cannot be judged here, with the reason. These are counted and reported
# separately rather than folded into the pass total.
UNRUNNABLE: dict[str, str] = {}

SETUP = (
    # Mastra is a Node framework with no managed runner, so its renderer needs a real
    # install before any command that drives it can work.
    ["npm", "ci", "--prefix", "src/mcp_mirror/renderers/mastra_node"],
)


def published_commands() -> dict[str, list[str]]:
    """Map each published reproduce command to the cells that publish it."""

    commands: dict[str, list[str]] = {}
    for path in sorted(BUILT_DATA.glob("data-2*.json")):
        document = json.loads(path.read_text())
        spec = document.get("mcp_spec", path.stem)
        for capability_id, capability in document["data"].items():
            command = (capability.get("reproduce") or "").strip()
            if command:
                commands.setdefault(command, []).append(f"{spec}/{capability_id}")
    return commands


def clean_checkout(destination: Path) -> None:
    """Copy every tracked file, which is what a fresh clone of this tree would hold."""

    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for name in listing.stdout.split("\0"):
        source = ROOT / name
        # A tracked path can be absent from the working tree: `vite build` empties
        # docs/ and replaces hashed bundles, so the previous ones are staged deletions
        # until the next commit. Copy what is on disk.
        if not name or not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def bare_environment() -> dict[str, str]:
    """Drop the caller's virtualenv, so a published command cannot borrow it.

    Running this through `uv run` puts the project interpreter on PATH, which is how a
    bare `python scripts/...` command passed for months without being installable by
    anyone who had not already activated the environment.
    """

    environment = dict(os.environ)
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    kept = [
        entry
        for entry in environment.get("PATH", "").split(os.pathsep)
        if entry and not Path(entry).is_relative_to(ROOT)
    ]
    environment["PATH"] = os.pathsep.join(kept)
    return environment


def run(command: str, cwd: Path, timeout: int) -> tuple[str, str, float]:
    """Run one published command and classify it as pass, fail, or skip."""

    if command in UNRUNNABLE:
        return "skip", UNRUNNABLE[command], 0.0

    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=bare_environment(),
        )
    except subprocess.TimeoutExpired:
        return "fail", f"timed out after {timeout}s", time.monotonic() - started

    elapsed = time.monotonic() - started
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        tail = output.strip().splitlines()[-1:] or ["no output"]
        return "fail", f"exit {proc.returncode}: {tail[0][:160]}", elapsed
    for marker in FAILURE_MARKERS:
        if marker in output:
            return "fail", f"exit 0 but output contains {marker!r}", elapsed
    return "pass", "", elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=1800, help="per-command seconds")
    parser.add_argument("--no-setup", action="store_true", help="skip the Node install")
    parser.add_argument("--keep", action="store_true", help="keep the temporary checkout")
    arguments = parser.parse_args()

    commands = published_commands()
    cells = sum(len(ids) for ids in commands.values())
    print(f"{cells} published reproduce commands, {len(commands)} distinct")

    workspace = Path(subprocess.run(["mktemp", "-d"], capture_output=True, text=True, check=True).stdout.strip())
    checkout = workspace / "mcp-mirror"
    checkout.mkdir()
    print(f"clean checkout: {checkout}")
    clean_checkout(checkout)

    if not arguments.no_setup:
        for step in SETUP:
            print(f"setup: {' '.join(step)}")
            setup = subprocess.run(step, cwd=checkout, capture_output=True, text=True)
            if setup.returncode != 0:
                print(f"  setup failed: {setup.stderr.strip().splitlines()[-1:]}")

    tally = {"pass": 0, "fail": 0, "skip": 0}
    failures = []
    for command, ids in sorted(commands.items(), key=lambda item: -len(item[1])):
        state, detail, elapsed = run(command, checkout, arguments.timeout)
        tally[state] += len(ids)
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[state]
        print(f"\n{mark}  {len(ids)} cell(s), {elapsed:.0f}s")
        print(f"      {command}")
        if detail:
            print(f"      {detail}")
        if state == "fail":
            failures.append((command, detail, ids))

    if arguments.keep:
        print(f"\nkept {checkout}")
    else:
        shutil.rmtree(workspace, ignore_errors=True)

    print(
        f"\n{tally['pass']}/{cells} published commands run clean, "
        f"{tally['fail']} fail, {tally['skip']} not judged here"
    )
    for command, detail, ids in failures:
        print(f"  {len(ids)} cell(s): {command}\n    {detail}")
    return 1 if tally["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
