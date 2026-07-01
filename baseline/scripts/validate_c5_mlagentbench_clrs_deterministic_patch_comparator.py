#!/usr/bin/env python3
"""Validate the equal-budget deterministic MLAgentBench CLRS patch comparator."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_COMMIT = "5d71205cc20a8e95d43aa7cb7120e89ca3323e31"
EXPECTED_BASELINE_MEAN = 0.01531982421875


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_path = root / "receipts" / "c5-mlagentbench-clrs-deterministic-patch-comparator-2026-06-30.json"
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    failures: list[dict[str, Any]] = []
    if receipt.get("verdict") != "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_PASS":
        failures.append({"code": "deterministic_comparator_not_pass", "actual": receipt.get("verdict")})
    source = receipt.get("source", {}) if isinstance(receipt, dict) else {}
    if source.get("source_commit") != EXPECTED_COMMIT:
        failures.append({"code": "source_commit_mismatch", "actual": source.get("source_commit")})
    run_config = receipt.get("run_config", {}) if isinstance(receipt, dict) else {}
    if run_config.get("variant_id") != "deterministic_lr3x_patch":
        failures.append({"code": "variant_id_mismatch", "actual": run_config.get("variant_id")})
    if "--learning_rate=0.003" not in run_config.get("extra_train_flags", []):
        failures.append({"code": "learning_rate_patch_missing", "actual": run_config.get("extra_train_flags")})
    if run_config.get("seeds") != [42, 43, 44] or run_config.get("train_steps") != 3:
        failures.append({"code": "budget_mismatch", "run_config": run_config})
    aggregate = receipt.get("aggregate", {}) if isinstance(receipt, dict) else {}
    if aggregate.get("seed_count") != 3 or aggregate.get("valid_score_count") != 3:
        failures.append({"code": "seed_score_count_invalid", "aggregate": aggregate})
    if not isinstance(aggregate.get("mean_test_score"), (int, float)):
        failures.append({"code": "mean_test_score_missing", "aggregate": aggregate})
    for run in receipt.get("seed_runs", []):
        if run.get("passed") is not True or not isinstance(run.get("test_score"), (int, float)):
            failures.append({"code": "seed_run_invalid", "seed": run.get("seed"), "passed": run.get("passed"), "score": run.get("test_score")})
    if "not an Ember loop result" not in receipt.get("completion_limit", ""):
        failures.append({"code": "completion_limit_missing_no_ember_scope"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C5_MLAGENTBENCH_CLRS_DETERMINISTIC_PATCH_COMPARATOR_VALIDATED" if not failures else "C5_MLAGENTBENCH_CLRS_DETERMINISTIC_PATCH_COMPARATOR_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt": "receipts/c5-mlagentbench-clrs-deterministic-patch-comparator-2026-06-30.json",
        "upstream_baseline_mean_test_score": EXPECTED_BASELINE_MEAN,
        "deterministic_patch_mean_test_score": aggregate.get("mean_test_score"),
        "delta_vs_upstream_mean": aggregate.get("mean_test_score") - EXPECTED_BASELINE_MEAN if isinstance(aggregate.get("mean_test_score"), (int, float)) else None,
        "completion_limit": "This validates only the equal-budget deterministic CLRS patch comparator. It is not an Ember improvement claim and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
