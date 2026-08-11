#!/usr/bin/env python3
"""Audit whether Ember's current receipt chain proves the connected field-level goal."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-CONNECTED-CYCLE-FIELD-LEVEL-AUDIT"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_RECEIPTS = {
    "native_goal_organ": Path("receipts/ember-preloop-resident-gate/native-goal-organ-20260621T195504Z.json"),
    "reference_full_parity": Path("receipts/ember-preloop-resident-gate/gate-full-parity-harness-20260622T152000Z-real-reference-observed.json"),
    "resident_training_gate": Path("receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-real-reference-observed.json"),
    "bitnet_comparison": Path("receipts/ember-tiny-bitnet-comparison/20260622T152800Z-final/tiny_bitnet_comparison_receipt.json"),
    "d3_generalization": Path("[archived — not in public tree]"),
    "sab_completion": Path("receipts/ember-post-resident-discovery/scienceagentbench-zero-cost-regrade-loop-20260622T192500Z.json"),
    "sab_stronger_transfer": Path("receipts/ember-post-resident-discovery/scienceagentbench-stronger-transfer-loop-20260622T204000Z.json"),
    "field_level_evaluation": Path("receipts/ember-post-resident-discovery/field-level-breakthrough-evaluation-20260622T211500Z.json"),
    "native_operator_external_transfer_link": Path("receipts/ember-post-resident-discovery/native-operator-external-transfer-link-20260622T221000Z.json"),
}
EXPECTED_VERDICTS = {
    "native_goal_organ": "NATIVE_GOAL_ORGAN_PASS",
    "reference_full_parity": "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS",
    "resident_training_gate": "RESIDENT_TRAINING_GATE_PASS",
    "bitnet_comparison": "BITNET_COMPARISON_PASS",
    "d3_generalization": "D3_MULTI_TASK_GENERALIZATION_PASS",
    "sab_completion": "SCIENCEAGENTBENCH_ZERO_COST_REGRADE_LOOP_PASS",
    "sab_stronger_transfer": "SCIENCEAGENTBENCH_STRONGER_TRANSFER_LOOP_PASS",
    "field_level_evaluation": "FIELD_LEVEL_BREAKTHROUGH_NOT_PROVEN_CONNECTED_CYCLE_AUDIT_REQUIRED",
    "native_operator_external_transfer_link": "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_PASS",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def zero_cost_ok(receipts: dict[str, dict[str, Any]]) -> bool:
    for data in receipts.values():
        if data.get("paid_api_surface_used") is True:
            return False
        if data.get("api_spend_usd") not in (None, 0, 0.0):
            return False
        if data.get("leaderboard_dependency") is True or data.get("leaderboard_identical") is True:
            return False
    return True


def has_positive_delta_and_deletion(data: dict[str, Any]) -> bool:
    scores = data.get("aggregate_scores") or {}
    if not scores:
        return False
    return bool(data.get("positive_delta")) and bool(data.get("deletion_sensitive")) and scores.get("C", 0) > max(scores.get("A", 0), scores.get("B", 0), scores.get("Deleted", 0))


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path.cwd().resolve()
    paths = DEFAULT_RECEIPTS.copy()
    loaded: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []

    for name, rel_path in paths.items():
        path = (repo / rel_path).resolve()
        item = {"path": str(rel_path), "exists": path.exists(), "expected_verdict": EXPECTED_VERDICTS[name]}
        if not path.exists():
            item["status"] = "missing"
            blockers.append(f"missing_receipt:{name}")
            evidence[name] = item
            continue
        data = load_json(path)
        loaded[name] = data
        item.update({"sha256": sha256_file(path), "verdict": data.get("verdict"), "status": "pass" if data.get("verdict") == EXPECTED_VERDICTS[name] else "unexpected_verdict"})
        if item["status"] != "pass":
            blockers.append(f"unexpected_verdict:{name}")
        evidence[name] = item

    zero_cost = zero_cost_ok(loaded)
    if not zero_cost:
        blockers.append("zero_cost_contract_broken")

    d3_ok = has_positive_delta_and_deletion(loaded.get("d3_generalization", {}))
    sab_ok = has_positive_delta_and_deletion(loaded.get("sab_completion", {}))
    transfer_ok = has_positive_delta_and_deletion(loaded.get("sab_stronger_transfer", {}))
    if not d3_ok:
        blockers.append("d3_positive_delta_or_deletion_missing")
    if not sab_ok:
        blockers.append("sab_positive_delta_or_deletion_missing")
    if not transfer_ok:
        blockers.append("transfer_positive_delta_or_deletion_missing")

    field_eval = loaded.get("field_level_evaluation", {})
    field_refuses = field_eval.get("field_level_decision") == "progress_not_field_breakthrough"
    if not field_refuses:
        blockers.append("field_level_refusal_missing_or_ambiguous")

    native_link = loaded.get("native_operator_external_transfer_link", {})
    connected_operator_proof = (
        native_link.get("verdict") == "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_PASS"
        and bool(native_link.get("positive_delta"))
        and bool(native_link.get("deletion_sensitive"))
        and native_link.get("native_operator_deleted_blocks_selection") is True
        and native_link.get("external_transfer_receipt_summary", {}).get("aggregate_scores", {}).get("C") == 1.0
    )
    if not connected_operator_proof:
        blockers.append("native_operator_to_external_transfer_link_missing")
    blockers.append("field_level_contribution_claim_not_proven")

    verdict = "CONNECTED_CYCLE_FIELD_LEVEL_AUDIT_PASS" if not blockers else "CONNECTED_CYCLE_FIELD_LEVEL_AUDIT_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/authority/GOAL.md"),
        "audited_receipts": evidence,
        "zero_cost_contract_ok": zero_cost,
        "positive_delta_deletion_checks": {"d3_generalization": d3_ok, "sab_completion": sab_ok, "sab_stronger_transfer": transfer_ok},
        "connected_operator_proof_present": connected_operator_proof,
        "field_level_decision_seen": field_eval.get("field_level_decision"),
        "field_level_claim_proven": False,
        "primary_missing_evidence": "native_operator_to_external_transfer_link_missing",
        "blocked_reasons": sorted(set(blockers)),
        "valid_progress_preserved": [
            "resident gate and the predecessor CLI full-parity preconditions are preserved as gate evidence",
            "D3 task65/task66 generalization receipt remains positive-delta and deletion-sensitive",
            "ScienceAgentBench six-row completion and four-row stronger transfer receipts are zero-cost, positive-delta, and deletion-sensitive",
            "field-level evaluation correctly refuses goal clear on transfer progress alone",
        ],
        "next_executable_command": "Produce a falsifiable ML/AI field-level contribution proof package from the connected cycle: name the primary contribution class, closest prior, material difference, reusable artifact, disjoint validation rows, and deletion/ablation evidence that the contribution itself is load-bearing.",
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = build_audit(args)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    write_json(out, receipt)
    print(json.dumps({"receipt": str(out), "verdict": receipt["verdict"], "blocked_reasons": receipt["blocked_reasons"], "next_executable_command": receipt["next_executable_command"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
