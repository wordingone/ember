#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Produce a fail-closed C-GROW probe replay across two clean Git snapshots."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.lib.invariant import stamp


GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
PROBE_REL = Path("scripts/ember_totality/test_c_grow.py")
EVIDENCE_RE = re.compile(r"present in ([^ ]+)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def capture_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve()
    probe_path = root / PROBE_REL
    if not probe_path.is_file():
        raise FileNotFoundError(f"probe is missing under snapshot: {PROBE_REL.as_posix()}")
    if git_output(root, "status", "--porcelain"):
        raise RuntimeError("snapshot worktree must be clean")
    head = git_output(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("snapshot HEAD is not a full Git object id")

    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE_REL).replace("\\", "/")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    stdout = completed.stdout.strip()
    if completed.returncode != 0 or not stdout.startswith("GREEN C-GROW:"):
        raise RuntimeError(
            f"C-GROW snapshot refused: exit={completed.returncode}; "
            f"stdout={stdout!r}; stderr={completed.stderr.strip()!r}"
        )
    match = EVIDENCE_RE.search(stdout)
    if match is None:
        raise RuntimeError("C-GROW output does not name its satisfying evidence")
    evidence_rel = match.group(1).replace("\\", "/")
    evidence_path = root / Path(evidence_rel)
    if not evidence_path.is_file():
        raise RuntimeError("C-GROW cited evidence is absent from snapshot")

    return {
        "head_sha": head,
        "probe_sha256": sha256_file(probe_path),
        "evidence_path": evidence_rel,
        "evidence_sha256": sha256_file(evidence_path),
        "stdout": stdout.replace("\\", "/"),
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
        "clean": True,
    }


def build_receipt(
    baseline_root: Path,
    candidate_root: Path,
    historical_receipt: Path,
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    historical_receipt = historical_receipt.resolve()
    historical = json.loads(historical_receipt.read_text(encoding="utf-8"))
    if historical.get("ticket") != "C-GROW-BEFORE-AFTER-PROBE":
        raise ValueError("historical receipt ticket mismatch")

    baseline = capture_snapshot(baseline_root)
    candidate = capture_snapshot(candidate_root)
    if baseline["head_sha"] == candidate["head_sha"]:
        raise RuntimeError("baseline and candidate must be distinct immutable commits")
    for field in ("probe_sha256", "evidence_path", "evidence_sha256", "stdout"):
        if baseline[field] != candidate[field]:
            raise RuntimeError(f"C-GROW before/after drift: {field}")

    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    candidate_root = candidate_root.resolve()
    receipt = {
        "ticket": "C-GROW-BEFORE-AFTER-PROBE",
        "ts": ts,
        "issue": 700,
        "source_issue": 626,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "mode": "CLEAN_IMMUTABLE_SNAPSHOT_REPLAY",
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "supersedes": historical_receipt.relative_to(candidate_root).as_posix(),
        "baseline": baseline,
        "candidate": candidate,
        "verdict_unchanged": True,
        "cited_evidence_path_unchanged": True,
        "producer": {
            "path": Path(__file__).resolve().relative_to(candidate_root).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "historical_receipt_sha256": sha256_file(historical_receipt),
        "claim_boundary": {
            "current_probe_replayed_across_distinct_commits": True,
            "historical_worktree_prose_reasserted": False,
            "rung2_extension_completion_claim": False,
            "training_claim": False,
            "model_capability_claim": False,
        },
        "paid_api_surface_used": False,
    }
    return stamp(receipt, str(candidate_root))


def publish(receipt: dict[str, Any], target: Path, candidate_root: Path) -> None:
    target = target.resolve()
    allowed = (candidate_root.resolve() / "receipts" / "cbase-grow-rung").resolve()
    if target.parent != allowed:
        raise ValueError("output must be under receipts/cbase-grow-rung")
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with target.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--historical-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = build_receipt(
        args.baseline_root,
        args.candidate_root,
        args.historical_receipt,
    )
    publish(receipt, args.output, args.candidate_root)
    print(json.dumps({"status": "PASS", "ticket": receipt["ticket"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
