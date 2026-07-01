#!/usr/bin/env python3
"""Validate the governed C5 nanoGPT deterministic patch comparator."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/c5-nanogpt-deterministic-patch-comparator-2026-06-30.json"
BASELINE = "receipts/c5-nanogpt-governed-baseline-control-2026-06-29.json"
FORBIDDEN_PATH_MARKERS = ["C:" + "/" + "tmp", "C:" + "\\" + "tmp", "B:" + "/" + "M", "B:" + "\\" + "M", "C:" + "/" + "Users" + "/" + "Admin", "C:" + "\\" + "Users" + "\\" + "Admin"]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def best_val_loss(receipt: dict[str, Any], dataset: str = "shakespeare_char") -> float | None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    baseline = read_json(root / BASELINE) if (root / BASELINE).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "PASS" or receipt.get("governed_run") is not True:
        failures.append({"code": "comparator_not_governed_pass", "verdict": receipt.get("verdict"), "governed_run": receipt.get("governed_run")})
    if receipt.get("candidate_kind") != "deterministic_patch_comparator":
        failures.append({"code": "candidate_kind_mismatch", "actual": receipt.get("candidate_kind")})
    budget = receipt.get("budget", {})
    if budget.get("profile") != "bounded_non_smoke_equal_budget" or budget.get("max_iters") != 20 or budget.get("eval_iters") != 10:
        failures.append({"code": "budget_mismatch", "budget": budget})
    if budget.get("model_shape_preserved") is not True or budget.get("batch_size_preserved") is not True or budget.get("block_size_preserved") is not True:
        failures.append({"code": "shape_or_batch_not_preserved", "budget": budget})
    patch_groups = [row.get("group") for row in receipt.get("patches", []) if row.get("status") == "applied"]
    if patch_groups.count("deterministic_comparator") != 2:
        failures.append({"code": "deterministic_patches_not_applied", "patch_groups": patch_groups})
    if patch_groups.count("budget") != 8:
        failures.append({"code": "budget_patches_not_applied", "patch_groups": patch_groups})
    outputs = receipt.get("outputs", {})
    if outputs.get("final_info_json_exists") is not True or outputs.get("per_seed_json_exists") != [True, True] or not outputs.get("final_info_json_sha256"):
        failures.append({"code": "outputs_not_pinned", "outputs": outputs})
    text = json.dumps(receipt, sort_keys=True)
    found_forbidden = [marker for marker in FORBIDDEN_PATH_MARKERS if marker in text]
    if found_forbidden:
        failures.append({"code": "receipt_contains_local_path_marker", "markers": found_forbidden})
    if "smoke" in text.lower() and "non_smoke" not in text.lower():
        failures.append({"code": "receipt_contains_smoke_marker"})

    baseline_loss = best_val_loss(baseline)
    comparator_loss = best_val_loss(receipt)
    delta_pct = None
    if baseline_loss is None:
        failures.append({"code": "baseline_metric_missing"})
    if comparator_loss is None:
        failures.append({"code": "comparator_metric_missing"})
    if baseline_loss is not None and comparator_loss is not None and baseline_loss > 0:
        delta_pct = ((baseline_loss - comparator_loss) / baseline_loss) * 100.0

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C5_NANOGPT_DETERMINISTIC_PATCH_COMPARATOR_VALIDATED" if not failures else "C5_NANOGPT_DETERMINISTIC_PATCH_COMPARATOR_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "baseline_receipt_path": BASELINE,
        "baseline_best_val_loss_mean": baseline_loss,
        "comparator_best_val_loss_mean": comparator_loss,
        "delta_vs_upstream_pct": delta_pct,
        "completion_limit": "This validates a deterministic same-budget nanoGPT comparator only. It is not an Ember improvement, not a full C5 governed trial, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
