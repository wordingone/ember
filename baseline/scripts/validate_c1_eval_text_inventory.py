#!/usr/bin/env python3
"""Validate C1 available-eval normalized-span inventory and local-surface scan.

This validator intentionally does not permit the available local/imported eval
inventory to become a full external eval-suite contamination PASS. It requires
the receipt to preserve that blocker explicitly.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-eval-text-inventory-normalized-span-scan-2026-06-30.json"
EXPECTED_VERDICT = "C1_AVAILABLE_EVAL_TEXT_NORMALIZED_SPAN_LOCAL_SURFACE_SCAN_PASS_WITH_BLOCKING_FULL_SUITE_GAP"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def contains_forbidden_local_path(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True)
    forbidden = ("C:" + "\\", "C" + ":/", "B:" + "\\", "B" + ":/", "Users" + "\\Admin", "Users" + "/Admin")
    return any(term in text for term in forbidden)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_path = root / RECEIPT
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "eval_text_inventory_bad_verdict", "actual": receipt.get("verdict")})
    if contains_forbidden_local_path(receipt):
        failures.append({"code": "receipt_contains_local_absolute_path"})
    if receipt.get("normalized_span_min_chars") != 200:
        failures.append({"code": "normalized_span_threshold_mismatch", "actual": receipt.get("normalized_span_min_chars")})
    if receipt.get("exact_normalized_span_hits") != 0:
        failures.append({"code": "normalized_span_hits_present", "actual": receipt.get("exact_normalized_span_hits")})

    inventory = receipt.get("eval_text_inventory", {})
    local = inventory.get("local_ember_heldout", {})
    if local.get("item_count") != 20 or local.get("normalized_doc_count") != 20:
        failures.append({"code": "local_heldout_inventory_scope_mismatch", "actual": local})
    if local.get("span_count", 0) < 20:
        failures.append({"code": "local_heldout_normalized_spans_missing", "actual": local})
    external = inventory.get("external_benchmark_import_receipts", {})
    if external.get("receipt_count", 0) < 3:
        failures.append({"code": "external_import_receipts_not_indexed", "actual": external})
    if external.get("raw_eval_text_available_count") != 0:
        failures.append({"code": "external_raw_eval_text_unexpectedly_available", "actual": external})
    if external.get("metadata_only_receipt_count", 0) < 3:
        failures.append({"code": "external_metadata_only_gap_not_preserved", "actual": external})

    surfaces = receipt.get("checked_in_training_text_surfaces_scanned", [])
    surface_paths = {row.get("repo_path") for row in surfaces}
    if "data/ember_avir_tasks/train.jsonl" not in surface_paths:
        failures.append({"code": "train_jsonl_surface_not_scanned", "actual": surfaces})
    if receipt.get("blocks_full_eval_suite_pass") is not True:
        failures.append({"code": "blocking_full_suite_gap_not_preserved", "actual": receipt.get("blocks_full_eval_suite_pass")})
    limit = str(receipt.get("completion_limit", ""))
    for phrase in (
        "not a full external eval-suite contamination PASS",
        "not a token-shard or full-corpus normalized-span PASS",
        "not overall baseline completion",
    ):
        if phrase not in limit:
            failures.append({"code": "completion_limit_missing_phrase", "phrase": phrase})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_EVAL_TEXT_INVENTORY_VALIDATED_WITH_BLOCKING_FULL_SUITE_GAP" if not failures else "C1_EVAL_TEXT_INVENTORY_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "completion_limit": "This validates available local/imported eval text inventory and a checked-in local-surface normalized-span scan only. It is not full external eval-suite contamination PASS, not token-shard/full-corpus normalized-span PASS, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
