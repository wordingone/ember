#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Field-level contribution proof protocol for Ember's connected cycle.

This receipt is intentionally fail-closed. It distinguishes three things that
were previously conflated:
1. external task progress,
2. contribution-method load-bearing evidence, and
3. an ML/AI field-level breakthrough claim.
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

TICKET = "EMBER-FIELD-LEVEL-CONTRIBUTION-PROOF"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_CONNECTED_AUDIT = Path("receipts/ember-post-resident-discovery/connected-cycle-field-level-audit-20260622T221500Z.json")
DEFAULT_PRE_NATIVE_AUDIT = Path("receipts/ember-post-resident-discovery/connected-cycle-field-level-audit-20260622T212500Z.json")
DEFAULT_NATIVE_LINK = Path("receipts/ember-post-resident-discovery/native-operator-external-transfer-link-20260622T221000Z.json")
DEFAULT_TRANSFER = Path("receipts/ember-post-resident-discovery/scienceagentbench-stronger-transfer-loop-20260622T204000Z.json")
DEFAULT_D3_NATIVE = Path("receipts/ember-d3-native-loop/native-link-task57-62-20260622T221000Z/d3-generalized-candidate-receipt.json")
DEFAULT_FRESH_ROWS = Path("receipts/ember-d3-native-loop/d3-gym-fresh-rows-offset54-len12-20260622T190000Z.json")
DEFAULT_TASK_IDS = ["task_57", "task_62"]


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


def rel(repo: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo))
    except ValueError:
        return str(path)


def receipt_summary(repo: Path, path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": rel(repo, path),
        "sha256": sha256_file(path),
        "verdict": data.get("verdict"),
        "aggregate_scores": data.get("aggregate_scores"),
        "blocked_reasons": data.get("blocked_reasons"),
    }


def write_deleted_method_audit(repo: Path, source_audit: Path, out_dir: Path) -> Path:
    """Create an audit input with the native-operator selection need removed.

    This deletes the claimed contribution's selection trigger while preserving the
    external task files, D3 runner, Docker evaluator, and candidate generator
    plumbing. A valid contribution-level ablation should block the native-link
    proof even if low-level external Docker execution still runs.
    """
    data = load_json(source_audit)
    reasons = [r for r in data.get("blocked_reasons", []) if r != "native_operator_to_external_transfer_link_missing"]
    if not reasons:
        reasons = ["field_level_contribution_claim_not_proven"]
    data["blocked_reasons"] = reasons
    data["ablation_note"] = "native_operator_to_external_transfer_link_missing removed to delete the claimed method trigger while preserving task files and runner plumbing"
    data["ticket"] = data.get("ticket", "EMBER-CONNECTED-CYCLE-FIELD-LEVEL-AUDIT")
    out = out_dir / "deleted-method-connected-audit.json"
    write_json(out, data)
    return out


def run_deleted_method_ablation(repo: Path, args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    deleted_audit = write_deleted_method_audit(repo, repo / args.pre_native_audit, out_dir)
    native_out_dir = out_dir / "deleted-method-native-link"
    native_receipt = out_dir / "deleted-method-native-link-receipt.json"
    cmd = [
        sys.executable,
        "src/ember/governance/scripts/ember_native_operator_external_transfer_link.py",
        "--audit",
        rel(repo, deleted_audit),
        "--native-goal-receipt",
        args.native_goal_receipt,
        "--resident-gate-receipt",
        args.resident_gate_receipt,
        "--fresh-rows",
        args.fresh_rows,
        "--out-dir",
        rel(repo, native_out_dir),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--out",
        rel(repo, native_receipt),
    ]
    for task_id in (args.task_id or DEFAULT_TASK_IDS):
        cmd.extend(["--task-id", task_id])
    if args.execute:
        cmd.append("--execute")
    proc = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=max(args.timeout_seconds * 12, 300))
    native = load_json(native_receipt) if native_receipt.exists() else {}
    delegate_path = native.get("delegate_result", {}).get("receipt_path")
    delegate = load_json(Path(delegate_path)) if delegate_path and Path(delegate_path).exists() else {}
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "deleted_audit_path": rel(repo, deleted_audit),
        "deleted_audit_sha256": sha256_file(deleted_audit),
        "native_link_receipt_path": rel(repo, native_receipt),
        "native_link_receipt_sha256": sha256_file(native_receipt) if native_receipt.exists() else None,
        "native_link_verdict": native.get("verdict"),
        "native_link_blocked_reasons": native.get("blocked_reasons"),
        "external_delegate_receipt_path": rel(repo, Path(delegate_path)) if delegate_path else None,
        "external_delegate_verdict": delegate.get("verdict"),
        "external_delegate_scores": delegate.get("aggregate_scores"),
        "external_delegate_positive_delta": delegate.get("positive_delta"),
        "external_delegate_deletion_sensitive": delegate.get("deletion_sensitive"),
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path.cwd().resolve()
    out_dir = repo / args.out_dir
    paths = {
        "connected_cycle_audit": repo / args.connected_audit,
        "pre_native_connected_cycle_audit": repo / args.pre_native_audit,
        "native_operator_external_transfer_link": repo / args.native_link,
        "scienceagentbench_stronger_transfer": repo / args.transfer,
        "d3_native_link_delegate": repo / args.d3_native,
    }
    receipts = {k: load_json(p) for k, p in paths.items()}
    evidence = {k: receipt_summary(repo, p) for k, p in paths.items()}

    closest_prior = {
        "name": "pre-native connected-cycle audit plus D3-Gym equal-budget A/B/Deleted controls",
        "why_closest": "It is the immediately preceding Ember evidence surface: same repo, same goal, same D3-Gym official evaluator family, same equal-budget A/B/C/Deleted harness, but without the native operator selecting the blocker and preserving a linked external-transfer receipt.",
        "receipt_paths": [
            rel(repo, paths["pre_native_connected_cycle_audit"]),
            rel(repo, paths["d3_native_link_delegate"]),
        ],
        "baseline_result": {
            "pre_native_audit_blocked_reasons": receipts["pre_native_connected_cycle_audit"].get("blocked_reasons"),
            "d3_controls": receipts["d3_native_link_delegate"].get("aggregate_scores"),
            "interpretation": "The official D3 controls prove the task-output compiler is load-bearing, but by themselves do not prove a connected native self-improvement method or field-level ML/AI contribution.",
        },
    }

    material_difference = {
        "claim": "A native goal organ reads the current receipt blocker, selects a fresh disjoint external held-out action surface, delegates an equal-budget A/B/C/Deleted run, writes a linked receipt chain, and then refuses field-level overclaim until a contribution-level ablation passes.",
        "falsifiable_predictions": [
            "With the native-operator selection trigger present, the native-link proof receipt must pass and point to external D3 rows with C greater than A/B/Deleted.",
            "With the native-operator selection trigger deleted while task files and runner plumbing remain, the native-link proof must block even if the low-level D3 Docker delegate can still execute.",
            "If the same result is achievable as an unlinked task candidate or static per-task answer table, the contribution claim fails.",
        ],
        "ml_ai_contribution_scope": "agent self-improvement evaluation method, not a new model architecture or benchmark SOTA result",
    }

    full_native_link_ok = receipts["native_operator_external_transfer_link"].get("verdict") == "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_PASS"
    d3_scores = receipts["d3_native_link_delegate"].get("aggregate_scores") or {}
    external_rows_ok = d3_scores.get("C", 0) > max(d3_scores.get("A", 0), d3_scores.get("B", 0), d3_scores.get("Deleted", 0))

    ablation = None
    if args.run_ablation:
        ablation = run_deleted_method_ablation(repo, args, out_dir)
    blockers: list[str] = []
    if not closest_prior:
        blockers.append("closest_known_prior_comparison_missing")
    if not material_difference:
        blockers.append("material_difference_over_prior_not_formalized")
    if not full_native_link_ok:
        blockers.append("native_link_full_method_not_passed")
    if not external_rows_ok:
        blockers.append("external_disjoint_validation_not_positive_delta")
    if ablation is None:
        blockers.append("contribution_level_deletion_ablation_not_run")
    else:
        method_blocked = ablation.get("native_link_verdict") == "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_BLOCKED"
        ordinary_runner_intact = ablation.get("external_delegate_verdict") == "D3_MULTI_TASK_GENERALIZATION_PASS"
        if not method_blocked:
            blockers.append("deleted_method_native_link_did_not_block")
        if not ordinary_runner_intact:
            blockers.append("deleted_method_did_not_preserve_external_runner_plumbing")

    # This protocol can prove a load-bearing connected-cycle contribution method.
    # It still cannot honestly claim an ML/AI field-level breakthrough unless the
    # result demonstrates field adoption, benchmark-leading novelty, or a named
    # prior-superiority result beyond this local proof harness.
    field_breakthrough_proven = False
    if not field_breakthrough_proven:
        blockers.append("field_level_breakthrough_not_proven_over_named_prior")

    verdict = "FIELD_LEVEL_CONTRIBUTION_PROOF_PASS" if not blockers else "FIELD_LEVEL_CONTRIBUTION_PROOF_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/domains/governance/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/domains/governance/authority/GOAL.md"),
        "audited_evidence": evidence,
        "closest_known_prior_comparison": closest_prior,
        "material_difference_over_prior": material_difference,
        "candidate_claim": {
            "primary_contribution_class": "agent self-improvement evaluation method",
            "candidate_name": "zero-cost native-operator external-transfer link with connected-cycle audit",
            "reusable_artifacts": [
                "src/ember/governance/scripts/ember_connected_cycle_audit.py",
                "src/ember/governance/scripts/ember_native_operator_external_transfer_link.py",
                "src/ember/governance/scripts/ember_field_level_contribution_proof.py",
                "src/ember/governance/scripts/ember_d3_generalized_candidate_exec.py",
            ],
            "external_disjoint_validation": [
                "ScienceAgentBench stronger transfer C=1.0 on four disjoint deterministic rows",
                "D3 native-link task57/task62 C=1.0 with A/B/Deleted=0.0",
            ],
        },
        "contribution_level_deletion_ablation": ablation,
        "required_goal_fields": {
            "primary_contribution_class_present": True,
            "closest_known_prior_or_baseline_present": bool(closest_prior),
            "material_difference_defined": bool(material_difference),
            "reusable_artifact_present": all((repo / p).exists() for p in [
                "src/ember/governance/scripts/ember_connected_cycle_audit.py",
                "src/ember/governance/scripts/ember_native_operator_external_transfer_link.py",
                "src/ember/governance/scripts/ember_field_level_contribution_proof.py",
                "src/ember/governance/scripts/ember_d3_generalized_candidate_exec.py",
            ]),
            "external_disjoint_validation_present": external_rows_ok,
            "contribution_level_deletion_ablation_present": ablation is not None and ablation.get("native_link_verdict") == "NATIVE_OPERATOR_EXTERNAL_TRANSFER_LINK_BLOCKED",
            "zero_cost": True,
        },
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "leaderboard_dependency": False,
        "field_level_claim_proven": verdict.endswith("_PASS"),
        "blocked_reasons": sorted(set(blockers)),
        "next_executable_command": "If only field_level_breakthrough_not_proven_over_named_prior remains, run a stricter named-prior superiority protocol on a broader external/disjoint benchmark or produce a new reusable ML/AI method artifact whose deletion degrades that broader benchmark; otherwise fix the exact protocol gap named here and rerun this script with --run-ablation --execute.",
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--connected-audit", default=str(DEFAULT_CONNECTED_AUDIT))
    ap.add_argument("--pre-native-audit", default=str(DEFAULT_PRE_NATIVE_AUDIT))
    ap.add_argument("--native-link", default=str(DEFAULT_NATIVE_LINK))
    ap.add_argument("--transfer", default=str(DEFAULT_TRANSFER))
    ap.add_argument("--d3-native", default=str(DEFAULT_D3_NATIVE))
    ap.add_argument("--fresh-rows", default=str(DEFAULT_FRESH_ROWS))
    ap.add_argument("--native-goal-receipt", default="receipts/ember-preloop-resident-gate/native-goal-organ-20260621T195504Z.json")
    ap.add_argument("--resident-gate-receipt", default="receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-real-reference-observed.json")
    ap.add_argument("--task-id", action="append", default=[])
    ap.add_argument("--timeout-seconds", type=int, default=180)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--run-ablation", action="store_true")
    ap.add_argument("--out-dir", default="receipts/ember-post-resident-discovery/field-level-contribution-protocol-20260622T223500Z")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = build(args)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    write_json(out, receipt)
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
