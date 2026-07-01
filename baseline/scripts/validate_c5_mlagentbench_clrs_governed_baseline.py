#!/usr/bin/env python3
"""Validate the three-seed MLAgentBench CLRS governed baseline receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_COMMIT = "5d71205cc20a8e95d43aa7cb7120e89ca3323e31"
REQUIRED_MODULES = ["chex", "clrs", "haiku", "jax", "jaxlib", "numpy", "optax", "tensorflow"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_path = root / "receipts" / "c5-mlagentbench-clrs-governed-baseline-2026-06-30.json"
    failures: list[dict[str, Any]] = []
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    if receipt.get("verdict") != "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_PASS":
        failures.append({"code": "governed_baseline_not_pass", "actual": receipt.get("verdict")})
    source = receipt.get("source", {}) if isinstance(receipt, dict) else {}
    if source.get("source_commit") != EXPECTED_COMMIT:
        failures.append({"code": "source_commit_mismatch", "actual": source.get("source_commit")})
    aggregate = receipt.get("aggregate", {}) if isinstance(receipt, dict) else {}
    if aggregate.get("seed_count", 0) < 3 or aggregate.get("valid_score_count") != aggregate.get("seed_count"):
        failures.append({"code": "seed_score_count_invalid", "aggregate": aggregate})
    if not isinstance(aggregate.get("mean_test_score"), (int, float)):
        failures.append({"code": "mean_test_score_missing", "aggregate": aggregate})
    for run in receipt.get("seed_runs", []):
        if run.get("passed") is not True:
            failures.append({"code": "seed_run_not_passed", "seed": run.get("seed"), "conditions": run.get("pass_conditions")})
        if not isinstance(run.get("test_score"), (int, float)):
            failures.append({"code": "seed_test_score_missing", "seed": run.get("seed")})
    modules = receipt.get("environment", {}).get("module_versions", {}) if isinstance(receipt, dict) else {}
    for module in REQUIRED_MODULES:
        if modules.get(module, {}).get("present") is not True:
            failures.append({"code": "required_module_missing", "module": module, "actual": modules.get(module)})
    if "not an Ember loop result" not in receipt.get("completion_limit", ""):
        failures.append({"code": "completion_limit_missing_no_ember_loop_scope"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_VALIDATED" if not failures else "C5_MLAGENTBENCH_CLRS_GOVERNED_BASELINE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt": "receipts/c5-mlagentbench-clrs-governed-baseline-2026-06-30.json",
        "completion_limit": "This validates only the three-seed upstream CLRS baseline comparator receipt. It is not an Ember improvement claim and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
