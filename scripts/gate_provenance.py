#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Visible self-provenance for directly executed repository gates."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


def render_gate_provenance(
    tool_path: str | Path, *, repo_root: str | Path | None = None
) -> str:
    """Return a path-free identity for the exact gate bytes and checkout."""

    tool = Path(tool_path).resolve(strict=True)
    root = (
        Path(repo_root).resolve(strict=False)
        if repo_root is not None
        else tool.parents[1]
    )
    try:
        display_path = tool.relative_to(root).as_posix()
    except ValueError:
        display_path = tool.name

    digest = hashlib.sha256(tool.read_bytes()).hexdigest()
    head = "UNAVAILABLE"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        candidate = result.stdout.strip()
        if result.returncode == 0 and candidate:
            head = candidate
    except (OSError, subprocess.SubprocessError):
        pass
    return f"EMBER_GATE_PROVENANCE path={display_path} sha256={digest} head={head}"


def emit_gate_provenance(
    tool_path: str | Path, *, repo_root: str | Path | None = None
) -> None:
    """Write the banner to stderr without changing JSON/stdout contracts."""

    print(
        render_gate_provenance(tool_path, repo_root=repo_root),
        file=sys.stderr,
        flush=True,
    )
