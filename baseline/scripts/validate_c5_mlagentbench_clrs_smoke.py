#!/usr/bin/env python3
"""Validate the MLAgentBench CLRS smoke receipt."""

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
    receipt_path = root / "receipts" / "c5-mlagentbench-clrs-smoke-2026-06-30.json"
    failures: list[dict[str, Any]] = []
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    if receipt.get("verdict") != "C5_MLAGENTBENCH_CLRS_SMOKE_PASS":
        failures.append({"code": "clrs_smoke_not_pass", "actual": receipt.get("verdict")})
    source = receipt.get("source", {}) if isinstance(receipt, dict) else {}
    if source.get("source_commit") != EXPECTED_COMMIT:
        failures.append({"code": "source_commit_mismatch", "actual": source.get("source_commit")})
    pass_conditions = receipt.get("pass_conditions", {}) if isinstance(receipt, dict) else {}
    for key in ["returncode_zero", "done_seen", "checkpoint_seen", "restore_seen", "has_test_score", "has_checkpoint_files"]:
        if pass_conditions.get(key) is not True:
            failures.append({"code": "pass_condition_false", "condition": key, "actual": pass_conditions.get(key)})
    parsed = receipt.get("parsed_log", {}) if isinstance(receipt, dict) else {}
    tests = parsed.get("test_events", []) if isinstance(parsed, dict) else []
    if not tests or not isinstance(tests[0].get("score"), (int, float)):
        failures.append({"code": "test_score_missing_or_non_numeric", "actual": tests})
    patches = receipt.get("compatibility_patch", []) if isinstance(receipt, dict) else []
    if len(patches) != 2 or any(p.get("replacement_count", 0) < 1 for p in patches):
        failures.append({"code": "compat_patch_not_recorded", "actual": patches})
    modules = receipt.get("environment", {}).get("module_versions", {}) if isinstance(receipt, dict) else {}
    for module in REQUIRED_MODULES:
        if modules.get(module, {}).get("present") is not True:
            failures.append({"code": "required_module_missing", "module": module, "actual": modules.get(module)})
    if "not a three-seed governed C5 trial" not in receipt.get("completion_limit", ""):
        failures.append({"code": "completion_limit_missing_c5_scope"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C5_MLAGENTBENCH_CLRS_SMOKE_VALIDATED" if not failures else "C5_MLAGENTBENCH_CLRS_SMOKE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt": "receipts/c5-mlagentbench-clrs-smoke-2026-06-30.json",
        "completion_limit": "This validates only the CLRS executable smoke receipt. It is not a C5 governed improvement trial and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
