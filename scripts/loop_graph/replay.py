# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic replay check for a CLOSED execution node.

gap-matrix.md distinguishes "replay-by-recompute" (auditor re-derives claimed
numbers -- already real, via RESEARCH_WORKFLOW.md's recount gate) from
"replay-by-re-run" (nothing found re-executes a node's recorded command
against its recorded inputs to reproduce the artifact). This module does not
attempt replay-by-re-run either -- actually invoking `command.argv` is an
engine's job, not this substrate's (see docs/charter/loop-graph-engine-contract.md).
What it verifies is the *precondition* for either kind of replay: that the
command's script, every declared input, and every declared output still
match their recorded content_hash on disk, and that the receipt closing the
node is itself untampered. If any of those drift, replay (of either kind) is
not trustworthy no matter how it's performed.

v1 verifies reconstructibility by content hash; re-execution equivalence is
engine-side and out of scope (lead sign-off 2026-08-02, review-pr1310).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hashing import hash_file
from .lifecycle import CLOSED_STATES


@dataclass
class ReplayResult:
    ok: bool
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems)}


def _resolve(path_str: str, cwd: Path) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else cwd / path


def _verify_ref(ref: dict[str, Any], cwd: Path, problems: list[str], label: str) -> None:
    path = _resolve(ref["path"], cwd)
    if not path.exists():
        problems.append(f"{label} {ref['path']!r} is missing on disk")
        return
    actual = hash_file(path)
    if actual != ref["content_hash"]:
        problems.append(f"{label} {ref['path']!r} content_hash mismatch: recorded {ref['content_hash']}, actual {actual}")


def _find_script(command: dict[str, Any], cwd: Path) -> Path | None:
    """Best-effort: the first argv token beyond the interpreter that resolves
    to an existing file under cwd. `command.content_hash` is defined against
    this file -- it lets a tamper to the harness script itself (not just its
    inputs) be caught, without the schema needing to name which argv index is
    "the script" for every possible interpreter/argv shape."""
    argv = command.get("argv", [])
    for token in argv[1:]:
        candidate = _resolve(token, cwd)
        if candidate.is_file():
            return candidate
    return None


def replay_check(node: dict[str, Any], *, receipt: dict[str, Any] | None = None) -> ReplayResult:
    problems: list[str] = []

    if node.get("state") not in CLOSED_STATES:
        return ReplayResult(False, [f"node {node.get('node_id')!r} is not closed (state={node.get('state')})"])

    command = node.get("command", {})
    cwd = Path(command.get("cwd", "."))

    expected_command_hash = command.get("content_hash")
    if expected_command_hash:
        script = _find_script(command, cwd)
        if script is None:
            problems.append("command.content_hash is set but no argv token resolves to a file under cwd")
        else:
            actual = hash_file(script)
            if actual != expected_command_hash:
                problems.append(
                    f"command script {script} content_hash mismatch: recorded {expected_command_hash}, actual {actual}"
                )

    for ref in node.get("inputs", []):
        _verify_ref(ref, cwd, problems, "input")

    for ref in node.get("outputs", []):
        _verify_ref(ref, cwd, problems, "output")

    if receipt is not None:
        if receipt.get("node_id") != node.get("node_id"):
            problems.append(
                f"receipt.node_id {receipt.get('node_id')!r} does not reference this node {node.get('node_id')!r}"
            )
        receipt_path = Path(receipt.get("path", ""))
        if receipt_path.exists():
            actual = hash_file(receipt_path)
            if actual != receipt.get("content_hash"):
                problems.append(
                    f"receipt file {receipt_path} content_hash mismatch: recorded {receipt.get('content_hash')}, actual {actual}"
                )
        else:
            problems.append(f"receipt path {receipt_path} is missing on disk")

    return ReplayResult(ok=not problems, problems=problems)
