#!/usr/bin/env python3
"""Validate the deterministic C1 near-duplicate sample remediation packet."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-near-duplicate-sample-remediation-2026-06-30.json"
SOURCE_RECEIPT = "receipts/4090-near-duplicate-minhash-sample-2026-06-30.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    sample = read_json(root / SOURCE_RECEIPT) if (root / SOURCE_RECEIPT).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_PACKET_READY":
        failures.append({"code": "remediation_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("source_receipt") != SOURCE_RECEIPT:
        failures.append({"code": "source_receipt_mismatch", "actual": receipt.get("source_receipt")})
    if receipt.get("threshold") != sample.get("threshold") or receipt.get("threshold") != 0.8:
        failures.append({"code": "threshold_mismatch", "receipt": receipt.get("threshold"), "sample": sample.get("threshold")})
    if receipt.get("input_crossing_pair_count") != sample.get("crossing_pair_count"):
        failures.append({"code": "crossing_pair_count_mismatch", "receipt": receipt.get("input_crossing_pair_count"), "sample": sample.get("crossing_pair_count")})
    if receipt.get("input_crossing_pair_count", 0) < 1:
        failures.append({"code": "no_crossing_pairs_to_remediate", "actual": receipt.get("input_crossing_pair_count")})
    exclusions = receipt.get("exclusions", [])
    clusters = receipt.get("clusters", [])
    if receipt.get("sample_exclusion_document_count") != len(exclusions):
        failures.append({"code": "exclusion_count_mismatch", "declared": receipt.get("sample_exclusion_document_count"), "actual": len(exclusions)})
    if receipt.get("cluster_count") != len(clusters):
        failures.append({"code": "cluster_count_mismatch", "declared": receipt.get("cluster_count"), "actual": len(clusters)})
    if len(exclusions) < 1 or len(clusters) < 1:
        failures.append({"code": "missing_remediation_exclusions"})
    token_floor = sum(int(row.get("token_len", 0)) for row in exclusions)
    if receipt.get("sample_exclusion_token_floor") != token_floor or token_floor < 1:
        failures.append({"code": "token_floor_mismatch", "declared": receipt.get("sample_exclusion_token_floor"), "actual": token_floor})
    seen = set()
    for row in exclusions:
        key = (row.get("doc_index"), row.get("doc_sha256"))
        if key in seen:
            failures.append({"code": "duplicate_exclusion", "key": key})
        seen.add(key)
        if not row.get("shard") or not row.get("doc_sha256") or row.get("token_len", 0) <= 0:
            failures.append({"code": "bad_exclusion_row", "row": row})
    if "not a full-corpus near-duplicate remediation list" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_noncompletion_guard"})
    if "post-remediation PASS validation remain required" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_VALIDATED" if not failures else "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "summary": {
            "cluster_count": receipt.get("cluster_count"),
            "sample_exclusion_document_count": receipt.get("sample_exclusion_document_count"),
            "sample_exclusion_token_floor": receipt.get("sample_exclusion_token_floor"),
            "input_crossing_pair_count": receipt.get("input_crossing_pair_count"),
        },
        "completion_limit": "This validates deterministic sample remediation only. It is not full-corpus near-duplicate remediation, not a C1 hygiene pass, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
