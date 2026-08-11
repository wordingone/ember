#!/usr/bin/env python3
"""Audit resident-training PASS labels against full resident-harness parity."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def build_receipt(
    *,
    repo: Path,
    resident_receipt_path: Path,
    full_parity_receipt_path: Path,
    out: Path,
) -> dict[str, Any]:
    resident = read_json(resident_receipt_path)
    full_parity = read_json(full_parity_receipt_path)

    resident_verdict = str(resident.get("verdict") or "")
    resident_gate_status = str(resident.get("resident_training_gate_status") or "")
    full_parity_verdict = str(full_parity.get("verdict") or "")
    full_parity_classification = str(full_parity.get("classification") or "")
    full_parity_blocked = full_parity_verdict.endswith("_BLOCKED") or "BLOCKED" in full_parity_classification

    component_status = resident.get("component_status")
    has_component_status = isinstance(component_status, dict)
    candidate = resident.get("resident_training_candidate") if isinstance(resident.get("resident_training_candidate"), dict) else {}
    claimed_neural_candidate = str(candidate.get("candidate_class") or "")
    claimed_clean_room_channel = bool(candidate.get("clean_room_harness_action_channel"))

    blocked_reasons: list[str] = []
    if resident_verdict == "RESIDENT_TRAINING_GATE_PASS" or resident_gate_status == "PASS":
        if full_parity_blocked:
            blocked_reasons.append("resident_pass_label_adjacent_to_blocked_full_parity_harness")
    if full_parity_blocked:
        blocked_reasons.append("the predecessor CLI_full_parity_harness_blocked")
    if not has_component_status:
        blocked_reasons.append("resident_component_status_missing")

    if blocked_reasons:
        interpretation = "RUNNER_OR_PARTIAL_NEURAL_PROGRESS_NOT_RESIDENT_ORGAN_CLEARANCE"
        verdict = "RESIDENT_GATE_CONFLATION_GUARD_BLOCKED"
    else:
        interpretation = "RESIDENT_GATE_CLEARANCE_RECONCILED"
        verdict = "RESIDENT_GATE_CONFLATION_GUARD_PASS"

    receipt = {
        "ticket": "EMBER-RESIDENT-GATE-CONFLATION-AUDIT",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/authority/GOAL.md") if (repo / "docs/authority/GOAL.md").exists() else None,
        "resident_training_receipt_path": str(resident_receipt_path),
        "resident_training_receipt_sha256": sha256_file(resident_receipt_path),
        "resident_training_verdict": resident_verdict,
        "resident_training_gate_status": resident_gate_status,
        "resident_candidate_class": claimed_neural_candidate,
        "resident_claims_clean_room_action_channel": claimed_clean_room_channel,
        "full_parity_receipt_path": str(full_parity_receipt_path),
        "full_parity_receipt_sha256": sha256_file(full_parity_receipt_path),
        "full_parity_verdict": full_parity_verdict,
        "full_parity_classification": full_parity_classification,
        "full_parity_blocked_reasons": full_parity.get("blocked_reasons") or [],
        "full_parity_blocked": full_parity_blocked,
        "resident_pass_interpretation": interpretation,
        "conflation_guard": {
            "neural_update_claim_is_not_sufficient_without_full_resident_harness_parity": True,
            "blocked_full_parity_harness_revokes_gate_clearance_inference": True,
            "d3_benchmark_or_readiness_work_cannot_use_this_pass_label_as_precondition_clearance": True,
        },
        "blocked_reasons": blocked_reasons,
        "next_executable_command": (
            "Return to the full resident-harness parity gate first: rerun "
            "python scripts\\ember_gate_full_parity_harness.py with the latest component receipts, "
            "then rerun the resident-training gate only after that receipt is PASS."
            if blocked_reasons
            else "Continue from the reconciled resident-training gate cursor."
        ),
        "verdict": verdict,
    }
    write_json(out, receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resident-receipt", required=True)
    ap.add_argument("--full-parity-receipt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    repo = Path.cwd().resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo / out
    receipt = build_receipt(
        repo=repo,
        resident_receipt_path=(repo / args.resident_receipt).resolve(),
        full_parity_receipt_path=(repo / args.full_parity_receipt).resolve(),
        out=out,
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "resident_pass_interpretation": receipt["resident_pass_interpretation"],
        "blocked_reasons": receipt["blocked_reasons"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "RESIDENT_GATE_CONFLATION_GUARD_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
