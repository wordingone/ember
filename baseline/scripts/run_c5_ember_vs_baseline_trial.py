#!/usr/bin/env python3
"""Materialize a public-safe governed Ember-vs-nanoGPT C5 trial receipt.

This script does not create an Ember improvement. It binds the current AI
Scientist nanoGPT_lite upstream control, the same-budget deterministic patch
comparator, and an optional Ember candidate receipt into one mechanically
checkable trial surface. If the Ember candidate is missing, the trial receipt is
an explicit FAIL with metrics preserved for the external ceiling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

LOCAL_MARKERS = [
    "C:" + "/" + "tmp",
    "C:" + "\\" + "tmp",
    "B:" + "/" + "M",
    "B:" + "\\" + "M",
    "C:" + "/" + "Users" + "/" + "Admin",
    "C:" + "\\" + "Users" + "\\" + "Admin",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def rel_to_root(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.name


def best_val_loss(receipt: dict[str, Any], dataset: str) -> float | None:
    parsed = receipt.get("parsed_final_info")
    if not isinstance(parsed, dict):
        return None
    row = parsed.get(dataset)
    if not isinstance(row, dict):
        return None
    means = row.get("means")
    if not isinstance(means, dict):
        return None
    value = means.get("best_val_loss_mean")
    return float(value) if isinstance(value, (int, float)) else None


def validation_delta(validation: dict[str, Any]) -> float | None:
    value = validation.get("delta_vs_upstream_pct")
    return float(value) if isinstance(value, (int, float)) else None


def git_head(repo: Path) -> str | None:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return proc.stdout.strip()
    except Exception:
        return None


def public_safe_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    text = json.dumps(payload, sort_keys=True)
    found = [marker for marker in LOCAL_MARKERS if marker in text]
    return not found, found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ember-repo", type=Path, required=True)
    parser.add_argument("--baseline-receipt", type=Path, required=True)
    parser.add_argument("--deterministic-comparator-validation", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset", default="shakespeare_char")
    parser.add_argument("--min-improvement-pct", type=float, default=1.0)
    parser.add_argument("--protocol", default="protocols/c5-zero-spend-subset-v0.md")
    args = parser.parse_args()

    started = time.time()
    root = args.root.resolve()
    ember_repo = args.ember_repo.resolve()
    baseline_receipt = args.baseline_receipt.resolve()
    comparator_validation_path = args.deterministic_comparator_validation.resolve()
    baseline = load_json(baseline_receipt)
    comparator_validation = load_json(comparator_validation_path)
    baseline_loss = best_val_loss(baseline, args.dataset)
    comparator_delta = validation_delta(comparator_validation)
    errors: list[str] = []
    candidate_loss = None
    improvement_pct = None
    candidate_sha = None

    if baseline.get("governed_run") is not True or baseline.get("verdict") != "PASS":
        errors.append("external_baseline_receipt_not_governed_PASS")
    if baseline_loss is None:
        errors.append("external_baseline_metric_missing")
    if comparator_validation.get("verdict") != "C5_NANOGPT_DETERMINISTIC_PATCH_COMPARATOR_VALIDATED":
        errors.append("deterministic_patch_comparator_not_validated")
    if comparator_delta is None or comparator_delta <= 0:
        errors.append("deterministic_patch_comparator_no_positive_delta")

    candidate_path = args.candidate_receipt.resolve() if args.candidate_receipt else None
    if candidate_path is None or not candidate_path.exists():
        errors.append("ember_candidate_receipt_missing")
    else:
        candidate_sha = sha256_file(candidate_path)
        candidate = load_json(candidate_path)
        if candidate.get("governed_run") is not True or candidate.get("verdict") != "PASS":
            errors.append("ember_candidate_receipt_not_governed_PASS")
        text = json.dumps(candidate, sort_keys=True).lower()
        if "smoke_reduced" in text or "smoke-reduced" in text or "smoke run" in text:
            errors.append("ember_candidate_receipt_is_smoke")
        candidate_loss = best_val_loss(candidate, args.dataset)
        if candidate_loss is None:
            errors.append("ember_candidate_metric_missing")

    if baseline_loss is not None and candidate_loss is not None and baseline_loss > 0:
        improvement_pct = ((baseline_loss - candidate_loss) / baseline_loss) * 100.0

    if errors:
        verdict = "FAIL"
    elif improvement_pct is not None and improvement_pct >= args.min_improvement_pct:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    receipt = {
        "claim_id": "C5-0B-AI-Scientist-nanoGPT-lite",
        "trial_type": "ember_vs_external_baseline",
        "schema": "c5.nanogpt.ember_vs_external_trial.v1",
        "verdict": verdict,
        "contract": "Run current Ember against the AI Scientist nanoGPT_lite C5-0B external baseline under a governed non-smoke receipt contract.",
        "protocol": args.protocol,
        "comparator": "AI Scientist nanoGPT_lite governed bounded baseline-control plus same-budget deterministic patch comparator",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": time.time() - started,
        "ember_repo_commit": git_head(ember_repo),
        "metric": {
            "name": "best_val_loss_mean_improvement_pct",
            "dataset": args.dataset,
            "external_baseline_best_val_loss_mean": baseline_loss,
            "deterministic_patch_delta_vs_upstream_pct": comparator_delta,
            "ember_candidate_best_val_loss_mean": candidate_loss,
            "ember_improvement_vs_external_pct": improvement_pct,
        },
        "threshold": {
            "min_improvement_pct": args.min_improvement_pct,
            "direction": "PASS requires Ember candidate validation loss to improve over external baseline by the threshold under a governed non-smoke receipt.",
        },
        "evidence": {
            "external_baseline_receipt": rel_to_root(baseline_receipt, root),
            "external_baseline_receipt_sha256": sha256_file(baseline_receipt),
            "deterministic_comparator_validation_receipt": rel_to_root(comparator_validation_path, root),
            "deterministic_comparator_validation_receipt_sha256": sha256_file(comparator_validation_path),
            "ember_candidate_receipt": rel_to_root(candidate_path, root) if candidate_path else None,
            "ember_candidate_receipt_sha256": candidate_sha,
            "errors": errors,
            "failure_interpretation": "Current Ember did not supply a governed non-smoke candidate receipt for this locked comparison." if errors else None,
        },
        "completion_limit": "This is a governed C5 nanoGPT trial receipt only. PASS would require a real Ember candidate receipt; deterministic patch gains are an external comparator, not an Ember result and not overall baseline completion.",
    }
    safe, markers = public_safe_payload(receipt)
    if not safe:
        receipt["verdict"] = "INVALID-RUN"
        receipt["evidence"]["errors"].append("public_safety_local_path_marker_detected")
        receipt["evidence"]["local_path_marker_count"] = len(markers)
    write_json(args.out, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"PASS", "FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
