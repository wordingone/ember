#!/usr/bin/env python3
"""Local inspectable state substrate for Ember MVP v0.

This is deliberately not GitHub-backed. It models the v0 branch, diff, commit,
replay, rollback, and rejected-branch GC semantics as local receipt objects.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TS = "20260617T000000Z"
ISO_TS = "2026-06-17T00:00:00Z"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


class StateSubstrateError(ValueError):
    pass


@dataclass(frozen=True)
class StateSubstrateRun:
    observation: dict[str, Any]
    branch: dict[str, Any]
    commit: dict[str, Any]
    replay: dict[str, Any]
    rollback: dict[str, Any]
    gc: dict[str, Any]


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hash_tree(root: Path) -> str:
    h = hashlib.sha256()
    if not root.exists():
        return "sha256:" + h.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def write_receipt(path: Path, obj: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), obj)
    return str(path)


def _base(ticket: str) -> dict[str, Any]:
    return {"ticket": ticket, "ts": TS, "sha_convention": SHA_CONVENTION}


def _write_workspace(workspace: Path, text: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "candidate.txt").write_text(text, encoding="utf-8", newline="\n")


def _materialize_diff(diff_path: Path, before: str, after: str) -> str:
    body = (
        "diff --ember-state-substrate a/candidate.txt b/candidate.txt\n"
        "--- a/candidate.txt\n"
        "+++ b/candidate.txt\n"
        "@@\n"
        f"-{before}"
        f"+{after}"
    )
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text(body, encoding="utf-8", newline="\n")
    return sha256_bytes(diff_path.read_bytes())


def _apply_fixture_diff(workspace: Path, diff_path: Path) -> None:
    lines = diff_path.read_text(encoding="utf-8").splitlines()
    additions = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
    if len(additions) != 1:
        raise StateSubstrateError("fixture diff must contain exactly one candidate addition")
    _write_workspace(workspace, additions[0] + "\n")


def run_fixture_state_cycle(root: Path, promotion: str = "accepted") -> StateSubstrateRun:
    if promotion not in {"accepted", "rejected"}:
        raise ValueError("promotion must be accepted or rejected")

    root = Path(root)
    workspace = root / "workspace"
    local_state = root / "local-state"
    receipts = root / "receipts"

    cycle_id = "cycle-20260617T000000Z-0001"
    observation_id = "obs-20260617T000000Z-0001"
    branch_id = "latent-20260617T000000Z-0001"
    commit_id = "statecommit-20260617T000000Z-0001"
    parent_id = "statecommit-parent"
    before_text = "ember-state-baseline\n"
    after_text = "ember-state-candidate\n"

    _write_workspace(workspace, before_text)
    pre_hash = hash_tree(workspace)

    observation = {
        **_base("EMBER-STATE-OBSERVATION"),
        "id": observation_id,
        "cycle_id": cycle_id,
        "created_at": ISO_TS,
        "workspace_root": str(workspace),
        "state_hash": pre_hash,
    }
    observation["receipt_path"] = write_receipt(receipts / "observations" / f"{observation_id}.json", observation)

    _write_workspace(workspace, after_text)
    post_hash = hash_tree(workspace)

    diff_path = local_state / "diffs" / f"{commit_id}.patch"
    diff_sha = _materialize_diff(diff_path, before_text, after_text)
    delta_path = local_state / "deltas" / f"{branch_id}.patch"
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    delta_path.write_bytes(diff_path.read_bytes())
    delta_sha = sha256_bytes(delta_path.read_bytes())

    branch = {
        **_base("EMBER-STATE-LATENT-BRANCH"),
        "id": branch_id,
        "cycle_id": cycle_id,
        "parent_observation_id": observation_id,
        "parent_commit_id": parent_id,
        "produced_deltas": [{"path": str(delta_path), "sha256": delta_sha}],
        "status": "candidate",
    }
    branch["receipt_path"] = write_receipt(receipts / "branches" / f"{branch_id}.json", branch)

    replay = {
        **_base("EMBER-STATE-REPLAY"),
        "cycle_id": cycle_id,
        "commit_id": commit_id,
        "diff_path": str(diff_path),
        "diff_sha256": diff_sha,
        "deterministic": True,
        "replayed_state_hash": post_hash,
    }
    replay["receipt_path"] = write_receipt(receipts / "replay" / f"{commit_id}.json", replay)

    _write_workspace(workspace, before_text)
    restored_hash = hash_tree(workspace)
    rollback = {
        **_base("EMBER-STATE-ROLLBACK"),
        "cycle_id": cycle_id,
        "commit_id": commit_id,
        "pre_cycle_state_hash": pre_hash,
        "post_candidate_state_hash": post_hash,
        "rollback_target": parent_id,
        "restored_state_hash": restored_hash,
        "replay_seed": 123456,
    }
    rollback["receipt_path"] = write_receipt(receipts / "rollback" / f"{commit_id}.json", rollback)

    commit = {
        **_base("EMBER-STATE-COMMIT"),
        "id": commit_id,
        "cycle_id": cycle_id,
        "parent_id": parent_id,
        "latent_branch_id": branch_id,
        "diff": {"path": str(diff_path), "sha256": diff_sha},
        "pre_cycle_state_hash": pre_hash,
        "post_candidate_state_hash": post_hash,
        "receipts": {
            "observation": observation["receipt_path"],
            "branch": branch["receipt_path"],
            "replay": replay["receipt_path"],
            "rollback": rollback["receipt_path"],
        },
        "replay_seed": 123456,
        "rollback_pointer": parent_id,
        "gc_eligible": promotion == "rejected",
        "promotion": promotion,
    }
    commit["receipt_path"] = write_receipt(receipts / "commits" / f"{commit_id}.json", commit)

    deleted = False
    if commit["gc_eligible"]:
        delta_path.unlink()
        deleted = True
    gc = {
        **_base("EMBER-STATE-GC"),
        "cycle_id": cycle_id,
        "commit_id": commit_id,
        "branch_id": branch_id,
        "gc_eligible": commit["gc_eligible"],
        "deleted": deleted,
        "deleted_paths": [str(delta_path)] if deleted else [],
    }
    gc["receipt_path"] = write_receipt(receipts / "gc" / f"{branch_id}.json", gc)

    validate_state_bundle(observation, branch, commit, rollback, replay, gc)
    return StateSubstrateRun(observation, branch, commit, replay, rollback, gc)


def replay_from_commit_receipt(commit_path: Path) -> dict[str, Any]:
    commit = json.loads(Path(commit_path).read_text(encoding="utf-8"))
    workspace = Path(commit_path).parent.parent.parent / "replay-workspace" / commit["id"]
    if workspace.exists():
        for path in sorted((p for p in workspace.rglob("*") if p.is_file()), reverse=True):
            path.unlink()
    workspace.mkdir(parents=True, exist_ok=True)
    _write_workspace(workspace, "ember-state-baseline\n")
    diff_path = Path(commit["diff"]["path"])
    if sha256_bytes(diff_path.read_bytes()) != commit["diff"]["sha256"]:
        raise StateSubstrateError("commit diff hash mismatch")
    _apply_fixture_diff(workspace, diff_path)
    return {
        **_base("EMBER-STATE-REPLAY-FROM-COMMIT"),
        "cycle_id": commit["cycle_id"],
        "commit_id": commit["id"],
        "source_commit_receipt": str(commit_path),
        "diff_sha256": commit["diff"]["sha256"],
        "deterministic": True,
        "replayed_state_hash": hash_tree(workspace),
    }


def validate_state_bundle(
    observation: dict[str, Any],
    branch: dict[str, Any],
    commit: dict[str, Any],
    rollback: dict[str, Any],
    replay: dict[str, Any],
    gc: dict[str, Any],
) -> None:
    errors: list[str] = []
    cycle_id = commit.get("cycle_id")
    for name, obj in (
        ("observation", observation),
        ("branch", branch),
        ("rollback", rollback),
        ("replay", replay),
        ("gc", gc),
    ):
        if obj.get("cycle_id") != cycle_id:
            errors.append(f"{name} cycle_id mismatch")
    if branch.get("parent_observation_id") != observation.get("id"):
        errors.append("branch parent observation mismatch")
    if commit.get("latent_branch_id") != branch.get("id"):
        errors.append("commit latent branch mismatch")
    if rollback.get("restored_state_hash") != rollback.get("pre_cycle_state_hash"):
        errors.append("rollback did not restore pre-cycle hash")
    if replay.get("replayed_state_hash") != commit.get("post_candidate_state_hash"):
        errors.append("replay state hash does not match committed candidate state")
    if replay.get("diff_sha256") != commit.get("diff", {}).get("sha256"):
        errors.append("replay diff hash mismatch")
    if commit.get("promotion") == "rejected":
        if commit.get("gc_eligible") is not True:
            errors.append("rejected commit must be gc eligible")
        if gc.get("deleted") is not True:
            errors.append("rejected branch gc must delete produced delta")
    elif commit.get("promotion") == "accepted":
        if commit.get("gc_eligible") is not False:
            errors.append("accepted commit must not be gc eligible")
    else:
        errors.append("commit promotion must be accepted or rejected")
    if errors:
        raise StateSubstrateError("; ".join(errors))


def main() -> int:
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fixture-out", help="write fixture state-substrate receipts under this directory")
    ap.add_argument("--promotion", choices=["accepted", "rejected"], default="accepted")
    args = ap.parse_args()

    if args.selftest:
        with tempfile.TemporaryDirectory(prefix="ember-state-substrate-") as td:
            run_fixture_state_cycle(Path(td), promotion="accepted")
            run_fixture_state_cycle(Path(td) / "rejected", promotion="rejected")
        print("EMBER_STATE_SUBSTRATE_MODULE_SELFTEST_PASS")
        return 0

    if args.fixture_out:
        run = run_fixture_state_cycle(Path(args.fixture_out), promotion=args.promotion)
        print(json.dumps(run.commit, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
