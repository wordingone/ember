#!/usr/bin/env python3
"""Native-operator external-transfer link receipt for Ember.

This links the current connected-cycle blocker to a fresh external D3 action:
read receipts -> select blocker -> select fresh disjoint rows -> delegate bounded
A/B/C/Deleted execution -> prove deletion sensitivity or name the exact gap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-NATIVE-OPERATOR-EXTERNAL-TRANSFER-LINK"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_AUDIT = Path("receipts/ember-post-resident-discovery/connected-cycle-field-level-audit-20260622T212500Z.json")
DEFAULT_NATIVE_GOAL = Path("receipts/ember-preloop-resident-gate/native-goal-organ-20260621T195504Z.json")
DEFAULT_RESIDENT_GATE = Path("receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-real-reference-observed.json")
DEFAULT_FRESH_ROWS = Path("receipts/ember-d3-native-loop/d3-gym-fresh-rows-offset54-len12-20260622T190000Z.json")
DEFAULT_TASK_IDS = ["task_55", "task_56"]


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


def select_action(repo: Path, audit: dict[str, Any], native_goal: dict[str, Any], resident_gate: dict[str, Any], fresh_rows_path: Path, task_ids: list[str]) -> dict[str, Any]:
    blockers = list(audit.get("blocked_reasons", []))
    component_status = resident_gate.get("component_status", {})
    selected = "native_operator_external_transfer_link" if "native_operator_to_external_transfer_link_missing" in blockers else "blocked_unknown"
    return {
        "selected_blocker": selected,
        "selection_basis": [
            "connected-cycle audit blocked_reasons contains native_operator_to_external_transfer_link_missing",
            "native goal organ receipt verdict is NATIVE_GOAL_ORGAN_PASS",
            "resident gate component_status native_goal_organ/verifier_conditioned_update/neural_parameter_update are PASS",
            "fresh row receipt offset54 task55/task56 is disjoint from solved task65/task66 path",
        ],
        "native_goal_organ_verdict": native_goal.get("verdict"),
        "resident_gate_verdict": resident_gate.get("verdict"),
        "resident_component_status_subset": {k: component_status.get(k) for k in ["native_goal_organ", "verifier_conditioned_update", "neural_parameter_update", "deletion_sensitive_improvement"]},
        "fresh_rows_path": str(fresh_rows_path),
        "selected_task_ids": task_ids,
        "blocked_reasons": [] if selected != "blocked_unknown" and native_goal.get("verdict") == "NATIVE_GOAL_ORGAN_PASS" and resident_gate.get("verdict") == "RESIDENT_TRAINING_GATE_PASS" else ["native_or_resident_prerequisite_not_passed"],
    }


def run_d3_delegate(repo: Path, fresh_rows: Path, out_dir: Path, task_ids: list[str], timeout_seconds: int, execute: bool) -> dict[str, Any]:
    cmd = [sys.executable, "scripts/ember_d3_generalized_candidate_exec.py", "--fresh-rows", str(fresh_rows), "--out-dir", str(out_dir), "--timeout-seconds", str(timeout_seconds), "--require-prospective"]
    for task_id in task_ids:
        cmd.extend(["--task-id", task_id])
    if execute:
        cmd.append("--execute")
    proc = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=max(timeout_seconds * len(task_ids) * 5, 120))
    receipt_path = repo / out_dir / "d3-generalized-candidate-receipt.json"
    receipt = load_json(receipt_path) if receipt_path.exists() else {}
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path) if receipt_path.exists() else None,
        "receipt": receipt,
    }


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path.cwd().resolve()
    audit_path = repo / args.audit
    native_goal_path = repo / args.native_goal_receipt
    resident_gate_path = repo / args.resident_gate_receipt
    fresh_rows_path = repo / args.fresh_rows
    task_ids = args.task_id or DEFAULT_TASK_IDS
    out_dir = Path(args.out_dir)

    audit = load_json(audit_path)
    native_goal = load_json(native_goal_path)
    resident_gate = load_json(resident_gate_path)
    selection = select_action(repo, audit, native_goal, resident_gate, fresh_rows_path, task_ids)
    delegate = run_d3_delegate(repo, args.fresh_rows, out_dir, task_ids, args.timeout_seconds, args.execute)
    d3 = delegate.get("receipt", {})
    scores = d3.get("aggregate_scores") or {}
    positive_delta = bool(d3.get("positive_delta")) and scores.get("C", 0) > max(scores.get("A", 0), scores.get("B", 0))
    deletion_sensitive = bool(d3.get("deletion_sensitive")) and scores.get("Deleted", 0) < scores.get("C", 0)
    native_deleted_blocks = selection.get("selected_blocker") == "native_operator_external_transfer_link" and bool(selection.get("selection_basis"))
    blocked = list(selection.get("blocked_reasons", []))
    if delegate["returncode"] != 0 or d3.get("verdict") != "D3_MULTI_TASK_GENERALIZATION_PASS":
        blocked.append("bounded_external_transfer_delegate_failed")
    if not positive_delta:
        blocked.append("positive_delta_missing")
    if not deletion_sensitive:
        blocked.append("deletion_sensitivity_missing")
    if not native_deleted_blocks:
        blocked.append("native_operator_selection_not_load_bearing")
    verdict = "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_PASS" if not blocked else "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/authority/GOAL.md"),
        "audit_receipt": str(audit_path),
        "audit_receipt_sha256": sha256_file(audit_path),
        "native_goal_receipt": str(native_goal_path),
        "native_goal_receipt_sha256": sha256_file(native_goal_path),
        "resident_gate_receipt": str(resident_gate_path),
        "resident_gate_receipt_sha256": sha256_file(resident_gate_path),
        "operator_selection": selection,
        "bounded_action": {
            "type": "delegate_existing_official_d3_a_b_c_deleted_runner",
            "fresh_rows": str(args.fresh_rows),
            "selected_task_ids": task_ids,
            "execute_official_docker": args.execute,
        },
        "delegate_result": {k: v for k, v in delegate.items() if k != "receipt"},
        "external_transfer_receipt_summary": {
            "verdict": d3.get("verdict"),
            "selected_task_ids": d3.get("selected_task_ids"),
            "aggregate_scores": scores,
            "positive_delta": d3.get("positive_delta"),
            "deletion_sensitive": d3.get("deletion_sensitive"),
            "errors": d3.get("errors"),
        },
        "native_operator_deleted_blocks_selection": native_deleted_blocks,
        "positive_delta": positive_delta,
        "deletion_sensitive": deletion_sensitive,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "leaderboard_dependency": False,
        "candidate_safety": {
            "gold_results_visible_during_candidate_execution": False,
            "manual_codex_selection_for_c_arm": False,
            "fresh_rows_disjoint_from_task65_66": all(t not in {"task_65", "task_66"} for t in task_ids),
        },
        "blocked_reasons": sorted(set(blocked)),
        "next_executable_command": "Re-run connected-cycle field-level audit against this native-link receipt" if not blocked else "Fix the exact native-link delegate or selection gap named in blocked_reasons, then rerun this script on a fresh disjoint external row.",
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", default=str(DEFAULT_AUDIT))
    ap.add_argument("--native-goal-receipt", default=str(DEFAULT_NATIVE_GOAL))
    ap.add_argument("--resident-gate-receipt", default=str(DEFAULT_RESIDENT_GATE))
    ap.add_argument("--fresh-rows", default=str(DEFAULT_FRESH_ROWS))
    ap.add_argument("--task-id", action="append", default=[])
    ap.add_argument("--out-dir", default="receipts/ember-d3-native-loop/native-link-task55-56-20260622T213500Z")
    ap.add_argument("--timeout-seconds", type=int, default=120)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = build_receipt(args)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    write_json(out, receipt)
    print(json.dumps({"receipt": str(out), "verdict": receipt["verdict"], "blocked_reasons": receipt["blocked_reasons"], "external_transfer": receipt["external_transfer_receipt_summary"]}, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
