#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Behavioral self-provenance regressions for issue #1383."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = (
    ROOT / "scripts" / "worktree_lifecycle.py",
    ROOT / "scripts" / "verify_authority_conservation.py",
    ROOT / "scripts" / "check_changed_receipts.py",
)
PROVENANCE = re.compile(
    r"^EMBER_GATE_PROVENANCE path=(?P<path>\S+) sha256=(?P<sha>[0-9a-f]{64}) head=(?P<head>\S+)$"
)
# worktree_lifecycle.py's own banner additionally carries dirty=true/false (#1696):
# whether ITS OWN on-disk bytes are modified vs the committed HEAD version. That field
# is composed onto the banner by worktree_lifecycle.py itself, not by
# gate_provenance.py's shared render_gate_provenance() -- so the other two direct gate
# entrypoints below are unaffected and keep matching the plain PROVENANCE form.
SELF_INTEGRITY_PROVENANCE = re.compile(
    r"^EMBER_GATE_PROVENANCE path=(?P<path>\S+) sha256=(?P<sha>[0-9a-f]{64}) "
    r"head=(?P<head>\S+) dirty=(?P<dirty>true|false)$"
)


def _banner(tool: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-B", str(tool), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stderr.splitlines()[0] if result.stderr else ""


def test_direct_gate_entrypoints_emit_matching_self_provenance() -> None:
    expected_head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    for tool in TOOLS:
        banner = _banner(tool)
        pattern = (
            SELF_INTEGRITY_PROVENANCE if tool.name == "worktree_lifecycle.py" else PROVENANCE
        )
        match = pattern.fullmatch(banner)
        assert match, (tool, banner)
        assert match.group("path") == tool.relative_to(ROOT).as_posix()
        assert match.group("sha") == hashlib.sha256(tool.read_bytes()).hexdigest()
        assert match.group("head") == expected_head
        if tool.name == "worktree_lifecycle.py":
            assert match.group("dirty") == "false", (
                "the checked-out worktree_lifecycle.py must match its own committed "
                "HEAD in a clean test/CI run"
            )


def test_different_tool_bytes_have_visibly_different_first_line(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from scripts.gate_provenance import render_gate_provenance

    first = tmp_path / "gate-a.py"
    second = tmp_path / "gate-b.py"
    first.write_bytes(b"print('a')\n")
    second.write_bytes(b"print('b')\n")

    first_line = render_gate_provenance(first, repo_root=tmp_path)
    second_line = render_gate_provenance(second, repo_root=tmp_path)
    assert first_line != second_line
    assert "path=gate-a.py" in first_line
    assert "path=gate-b.py" in second_line
    assert hashlib.sha256(first.read_bytes()).hexdigest() in first_line
    assert hashlib.sha256(second.read_bytes()).hexdigest() in second_line
    assert first_line.endswith(" head=UNAVAILABLE")
    assert second_line.endswith(" head=UNAVAILABLE")
