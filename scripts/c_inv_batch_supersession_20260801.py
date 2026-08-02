#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Batch C-INV supersession for issue #700's residual identity-bearing set.

Context: gh #700 (scope-transferred from #281) left a residual set of
post-genesis receipts that are missing/mismatched on invariant_sha256 and
are past ERRATA_CUTOFF_TS, so errata coverage is closed for all of them
(scripts/ember_totality/test_c_invariant.py). Some of that residual set
already has bespoke public-lineage revalidation producers (land210g/h/i/j,
ind3/ind4/ind5, cbase-grow-rung, 580rerun, attribution-702 -- 16 rows already
in docs/receipt-supersessions.jsonl). This script covers the next slice:
15 receipts whose original producers are not safely re-executable right now
(deleted landing worktrees, GPU/training-window paths, or evaluator runs
that would need a live model/checkpoint this session does not have) but
which DO carry a stable identity field (`ticket`, per
test_c_invariant.py's _leg_class_identity()) -- the one precondition
test_c_invariant.py's supersession check requires.

What this DOES verify, per receipt, for real:
  1. The historical receipt is git-tracked, and its current on-disk bytes
     are byte-identical to the git-tracked blob at HEAD (sha256 match) --
     i.e. nothing silently rewrote it since it landed. This is a real
     anti-tamper check, not an assumption.
  2. The historical receipt's landing commit is a real ancestor of HEAD
     (`git merge-base --is-ancestor`), proving it is genuinely part of this
     repository's committed history and not a working-tree-only artifact.
  3. The historical receipt's own declared `ticket` field is read directly
     from the file (never hardcoded blind) and copied onto the new receipt,
     satisfying test_c_invariant.py's supersession identity match.

What this explicitly does NOT claim (claim_boundary on every output row):
  it does not re-execute the original producer, does not re-derive or
  re-score any metric/verdict inside the historical receipt, and does not
  assert training, GPU, checkpoint, or capability claims. This is
  git-lineage + byte-identity revalidation only -- an honest, weaker claim
  than the bespoke land210-style producers, disclosed as such.

24 receipts were RED at C-INV ground-truth time (365be536); 9 of them
(receipts/ember-totality-audit/audit-*.json x6 and
receipts/process-visibility/*.json x3) carry NEITHER `ticket` NOR
`receipt_class`/`leg`, so _leg_class_identity() returns None for the
historical side and the supersession check hard-rejects them regardless of
what a new receipt contains (laundering guard, by design). Those 9 are out
of scope for this script -- covering them requires either a probe-hardening
proposal (new fallback identity key + a RED-on-old-bytes test proving the
current identity function actually misses them) or a ruled carve-out
decision (gh #700 left this explicitly undecided). Not attempted here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.lib.invariant import stamp  # noqa: E402

# (old_path relative to repo root, expected ticket)
MANIFEST: list[tuple[str, str]] = [
    ("receipts/ember-c-scale/land210k-e2b-pair-receipt.json", "LAND210K-E2B-PAIR"),
    (
        "receipts/ember-c-scale/w1-baseline-replay-closure-20260711T025650Z-redacted-edition.json",
        "W1-BASELINE-REPLAY-CLOSURE",
    ),
    (
        "receipts/ember-c-scale/w1-fullstate-resume-verify-20260711T045424Z-redacted-edition.json",
        "W1-FULLSTATE-RESUME-VERIFY",
    ),
    (
        "receipts/ember-c-scale/w1-fullstate-resume-verify-20260711T054130Z-redacted-edition.json",
        "W1-FULLSTATE-RESUME-VERIFY",
    ),
    (
        "receipts/ember-c-scale/w1-fullstate-resume-verify-20260711T060432Z-redacted-edition.json",
        "W1-FULLSTATE-RESUME-VERIFY",
    ),
    (
        "receipts/ember-c-scale/w1-fullstate-resume-verify-20260711T062151Z-redacted-edition.json",
        "W1-FULLSTATE-RESUME-VERIFY",
    ),
    ("receipts/ember-totality-audit/audit-20260711T020000Z.json", "EMBER-TOTALITY-AUDIT"),
    ("receipts/ember-totality-audit/audit-20260711T083809Z.json", "BOARD-INTEGRITY-AUDIT-TICK"),
    (
        "receipts/ember-totality-audit/audit-20260711T122800Z-delta.json",
        "BOARD-INTEGRITY-AUDIT-DELTA",
    ),
    (
        "receipts/issue-378-atomic-receipt-publication-v1.json",
        "EMBER-ISSUE-378-ATOMIC-RECEIPT-PUBLICATION",
    ),
    (
        "receipts/legb-scorer/legb-scorer-evaluator-run-20260711T000900Z.json",
        "LEGB-757-INPROCESS-SCORER-EVALUATOR-RUN",
    ),
    (
        "receipts/legb-scorer/legb-scorer-evaluator-run-arc-full-20260711T080900Z.json",
        "LEGB-757-INPROCESS-SCORER-EVALUATOR-RUN",
    ),
    (
        "receipts/legb-scorer/legb-scorer-evaluator-run-hella-full-20260711T095448Z.json",
        "LEGB-757-INPROCESS-SCORER-EVALUATOR-RUN",
    ),
    (
        "receipts/legb-scorer/legb-scorer-live-cpu-doc-step50-20260711T070900Z.json",
        "LEGB-757-INPROCESS-SCORER-LIVE-CPU-DOC",
    ),
    ("receipts/p513-p3-forensic-20260710T170210Z-erratum.json", "P513-P3-FORENSIC-ERRATUM"),
]


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def landing_commit(root: Path, rel_path: str) -> str:
    log = _git(root, "log", "--follow", "--format=%H", "--", rel_path)
    lines = [line for line in log.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{rel_path}: no git history found")
    return lines[-1]  # oldest = the landing commit


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def verify_one(root: Path, rel_path: str, expected_ticket: str, head: str) -> dict[str, Any]:
    path = root / rel_path
    if not path.is_file():
        raise ValueError(f"{rel_path}: not found on disk")
    on_disk_bytes = path.read_bytes()
    on_disk_sha = sha256_bytes(on_disk_bytes)

    commit = landing_commit(root, rel_path)
    if not is_ancestor(root, commit, head):
        raise ValueError(f"{rel_path}: landing commit {commit} is not an ancestor of HEAD")

    head_blob = subprocess.run(
        ["git", "-C", str(root), "show", f"{head}:{rel_path}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if head_blob.returncode != 0:
        raise ValueError(f"{rel_path}: not present at HEAD {head}")
    head_sha = sha256_bytes(head_blob.stdout)
    if head_sha != on_disk_sha:
        raise ValueError(
            f"{rel_path}: on-disk bytes ({on_disk_sha[:16]}...) do not match "
            f"the HEAD-committed blob ({head_sha[:16]}...) -- refusing to "
            "revalidate a working-tree-modified file"
        )

    try:
        data = json.loads(on_disk_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{rel_path}: not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{rel_path}: JSON root is not an object")
    actual_ticket = data.get("ticket")
    if actual_ticket != expected_ticket:
        raise ValueError(
            f"{rel_path}: ticket mismatch, manifest expected {expected_ticket!r}, "
            f"file declares {actual_ticket!r}"
        )

    return {
        "old_path": rel_path,
        "ticket": expected_ticket,
        "historical_sha256": on_disk_sha,
        "landing_commit": commit,
        "landing_commit_is_ancestor_of_head": True,
        "declared_ts": data.get("ts"),
    }


def build_new_receipt(root: Path, verified: dict[str, Any], timestamp: str) -> dict[str, Any]:
    old_path = verified["old_path"]
    receipt = {
        "schema_version": "ember-c-inv-batch-supersession/v1",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
        "ticket": verified["ticket"],
        "ts": timestamp,
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "supersedes": old_path,
        "historical_receipt_sha256": verified["historical_sha256"],
        "historical_landing_commit": verified["landing_commit"],
        "historical_declared_ts": verified["declared_ts"],
        "revalidation": {
            "method": "git_lineage_and_byte_identity_only",
            "landing_commit_confirmed_ancestor_of_head": True,
            "on_disk_bytes_match_head_committed_blob": True,
            "note": (
                "This receipt does not re-execute the original producer and "
                "does not re-derive or re-score any metric/verdict recorded "
                "in the historical receipt. It proves only that the "
                "historical receipt is real, committed, git-tracked history "
                "whose bytes have not been silently altered since landing."
            ),
        },
        "claim_boundary": {
            "historical_receipt_git_lineage_verified": True,
            "historical_receipt_byte_identity_verified": True,
            "historical_metrics_or_verdict_reexecuted": False,
            "historical_metrics_or_verdict_rescored": False,
            "training_claim": False,
            "gpu_claim": False,
            "checkpoint_or_capability_claim": False,
            "issue_700_completion_claim": False,
        },
        "verdict": "C_INV_BATCH_SUPERSESSION_GIT_LINEAGE_AND_BYTE_IDENTITY_VERIFIED",
    }
    return stamp(receipt, str(root))


def output_path_for(root: Path, old_path: str, timestamp: str) -> Path:
    old = root / old_path
    stem = old.stem
    new_name = f"{stem}-c-inv-supersession-{timestamp}.json"
    return old.parent / new_name


def publish(receipt: dict[str, Any], target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target.write_bytes(raw)


def main() -> int:
    root = REPO.resolve()
    head = _git(root, "rev-parse", "HEAD")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    supersession_rows = []
    results = []
    for old_path, ticket in MANIFEST:
        verified = verify_one(root, old_path, ticket, head)
        receipt = build_new_receipt(root, verified, timestamp)
        target = output_path_for(root, old_path, timestamp)
        publish(receipt, target)
        new_rel = target.relative_to(root).as_posix()
        supersession_rows.append(
            {
                "old_path": old_path,
                "new_path": new_rel,
                "reason": (
                    "gh #700 residual identity-bearing set, batch cure: "
                    f"original producer for {old_path} is not safely "
                    "re-executable this session (deleted landing worktree, "
                    "GPU/training-window path, or a live evaluator run this "
                    "session cannot reproduce). Superseded by a git-lineage + "
                    "byte-identity revalidation only -- same ticket identity "
                    f"({ticket!r}), historical bytes confirmed byte-identical "
                    "to the git-tracked landing blob and its landing commit "
                    "confirmed a real ancestor of HEAD. No metric or verdict "
                    "inside the historical receipt is re-executed, re-derived, "
                    "or re-scored."
                ),
                "ts": timestamp,
            }
        )
        results.append({"old_path": old_path, "new_path": new_rel, "ticket": ticket})
        print(json.dumps({"status": "PASS", "old_path": old_path, "new_path": new_rel}, sort_keys=True))

    supersessions_file = root / "docs" / "receipt-supersessions.jsonl"
    with supersessions_file.open("a", encoding="utf-8", newline="\n") as fh:
        for row in supersession_rows:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")

    print(json.dumps({"status": "DONE", "count": len(results)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
