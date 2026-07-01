#!/usr/bin/env python3
"""Validate the public-safe C5 nanoGPT Ember-vs-external trial receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRIAL = "receipts/c5-ember-vs-nanogpt-governed-trial-2026-06-30.json"
BASELINE = "receipts/c5-nanogpt-governed-baseline-control-2026-06-29.json"
COMPARATOR_VALIDATION = "receipts/c5-nanogpt-deterministic-patch-comparator-validation-2026-06-30.json"
FORBIDDEN_PATH_MARKERS = ["C:" + "/" + "tmp", "C:" + "\\" + "tmp", "B:" + "/" + "M", "B:" + "\\" + "M", "C:" + "/" + "Users" + "/" + "Admin", "C:" + "\\" + "Users" + "\\" + "Admin"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    trial_path = root / TRIAL
    baseline_path = root / BASELINE
    comparator_path = root / COMPARATOR_VALIDATION
    trial = read_json(trial_path) if trial_path.exists() else {}
    baseline = read_json(baseline_path) if baseline_path.exists() else {}
    comparator = read_json(comparator_path) if comparator_path.exists() else {}
    failures: list[dict[str, Any]] = []

    if trial.get("schema") != "c5.nanogpt.ember_vs_external_trial.v1":
        failures.append({"code": "trial_schema_missing_or_wrong", "actual": trial.get("schema")})
    if trial.get("verdict") != "FAIL":
        failures.append({"code": "trial_must_be_explicit_fail_until_ember_candidate_exists", "actual": trial.get("verdict")})
    metric = trial.get("metric", {}) if isinstance(trial.get("metric"), dict) else {}
    if metric.get("external_baseline_best_val_loss_mean") is None:
        failures.append({"code": "external_baseline_metric_missing"})
    if metric.get("deterministic_patch_delta_vs_upstream_pct") is None or metric.get("deterministic_patch_delta_vs_upstream_pct", 0) <= 0:
        failures.append({"code": "deterministic_patch_delta_missing_or_nonpositive", "actual": metric.get("deterministic_patch_delta_vs_upstream_pct")})
    if metric.get("ember_candidate_best_val_loss_mean") is not None or metric.get("ember_improvement_vs_external_pct") is not None:
        failures.append({"code": "unexpected_ember_metric_without_candidate", "metric": metric})
    evidence = trial.get("evidence", {}) if isinstance(trial.get("evidence"), dict) else {}
    errors = evidence.get("errors", []) if isinstance(evidence.get("errors"), list) else []
    if "ember_candidate_receipt_missing" not in errors:
        failures.append({"code": "missing_candidate_error_not_recorded", "errors": errors})
    if evidence.get("external_baseline_receipt") != BASELINE:
        failures.append({"code": "baseline_receipt_path_not_repo_relative", "actual": evidence.get("external_baseline_receipt")})
    if evidence.get("deterministic_comparator_validation_receipt") != COMPARATOR_VALIDATION:
        failures.append({"code": "comparator_validation_path_not_repo_relative", "actual": evidence.get("deterministic_comparator_validation_receipt")})
    if evidence.get("external_baseline_receipt_sha256") != sha256_file(baseline_path):
        failures.append({"code": "baseline_receipt_hash_mismatch"})
    if evidence.get("deterministic_comparator_validation_receipt_sha256") != sha256_file(comparator_path):
        failures.append({"code": "comparator_validation_hash_mismatch"})
    if baseline.get("governed_run") is not True or baseline.get("verdict") != "PASS":
        failures.append({"code": "baseline_receipt_not_governed_pass", "actual": baseline.get("verdict")})
    if comparator.get("verdict") != "C5_NANOGPT_DETERMINISTIC_PATCH_COMPARATOR_VALIDATED":
        failures.append({"code": "comparator_validation_not_pass", "actual": comparator.get("verdict")})
    text = json.dumps(trial, sort_keys=True)
    markers = [marker for marker in FORBIDDEN_PATH_MARKERS if marker in text]
    if markers:
        failures.append({"code": "trial_contains_local_path_marker", "marker_count": len(markers)})
    limit = trial.get("completion_limit", "")
    if "not an Ember result" not in limit or "not overall baseline completion" not in limit:
        failures.append({"code": "completion_limit_missing_anti_cheat_text", "actual": limit})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C5_EMBER_VS_NANOGPT_TRIAL_NEGATIVE_EVIDENCE_VALIDATED" if not failures else "C5_EMBER_VS_NANOGPT_TRIAL_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "trial_receipt_path": TRIAL,
        "baseline_receipt_path": BASELINE,
        "comparator_validation_receipt_path": COMPARATOR_VALIDATION,
        "completion_limit": "This validates a public-safe negative Ember-vs-nanoGPT trial surface. It is not an Ember win and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
