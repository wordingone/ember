#!/usr/bin/env python3
"""Validate the materialized C1 targeted near-duplicate exclusion manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPANSION_RECEIPT = "receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json"
MANIFEST_RECEIPT = "receipts/4090-near-duplicate-targeted-exclusion-manifest-2026-06-30.json"
MANIFEST = "fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line"] = line_no
                rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    expansion = read_json(root / EXPANSION_RECEIPT) if (root / EXPANSION_RECEIPT).exists() else {}
    receipt = read_json(root / MANIFEST_RECEIPT) if (root / MANIFEST_RECEIPT).exists() else {}
    manifest_path = root / MANIFEST
    rows = read_jsonl(manifest_path) if manifest_path.exists() else []

    if receipt.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_READY":
        failures.append({"code": "manifest_receipt_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("source_receipt") != EXPANSION_RECEIPT:
        failures.append({"code": "source_receipt_mismatch", "actual": receipt.get("source_receipt")})
    if not manifest_path.exists():
        failures.append({"code": "manifest_missing", "path": MANIFEST})
    else:
        manifest_meta = receipt.get("manifest", {})
        if manifest_meta.get("repo_path") != MANIFEST:
            failures.append({"code": "manifest_repo_path_mismatch", "actual": manifest_meta.get("repo_path")})
        if manifest_meta.get("sha256") != sha256_file(manifest_path):
            failures.append({"code": "manifest_hash_mismatch", "recorded": manifest_meta.get("sha256"), "actual": sha256_file(manifest_path)})
        if manifest_meta.get("line_count") != len(rows):
            failures.append({"code": "manifest_line_count_mismatch", "recorded": manifest_meta.get("line_count"), "actual": len(rows)})

    expansion_keys = {(int(row["doc_index"]), str(row["doc_sha256"])) for row in expansion.get("exclusions", [])}
    manifest_keys = set()
    last_key: tuple[int, str] | None = None
    token_floor = 0
    target_indices = {int(row["target_doc_index"]) for row in expansion.get("target_summaries", [])}
    for ordinal, row in enumerate(rows):
        key = (int(row.get("doc_index", -1)), str(row.get("doc_sha256", "")))
        if row.get("ordinal") != ordinal:
            failures.append({"code": "ordinal_mismatch", "line": row.get("_line"), "expected": ordinal, "actual": row.get("ordinal")})
        if key in manifest_keys:
            failures.append({"code": "duplicate_manifest_exclusion", "key": key})
        if last_key is not None and key < last_key:
            failures.append({"code": "manifest_not_sorted", "line": row.get("_line"), "key": key, "previous": last_key})
        last_key = key
        manifest_keys.add(key)
        if key[0] in target_indices:
            failures.append({"code": "target_representative_excluded", "key": key})
        if row.get("source_receipt") != EXPANSION_RECEIPT or row.get("action") != "exclude_from_c1_targeted_near_duplicate_clusters":
            failures.append({"code": "manifest_row_contract_mismatch", "line": row.get("_line"), "row": row})
        if row.get("exact_jaccard_to_target", 0) < 0.8:
            failures.append({"code": "manifest_row_below_threshold", "line": row.get("_line"), "actual": row.get("exact_jaccard_to_target")})
        token_floor += int(row.get("token_len", 0))

    if manifest_keys != expansion_keys:
        failures.append({"code": "manifest_does_not_match_expansion", "missing": len(expansion_keys - manifest_keys), "extra": len(manifest_keys - expansion_keys)})
    if len(rows) != expansion.get("expanded_exclusion_document_count") or receipt.get("exclusion_document_count") != len(rows):
        failures.append({"code": "exclusion_count_mismatch", "rows": len(rows), "expansion": expansion.get("expanded_exclusion_document_count"), "receipt": receipt.get("exclusion_document_count")})
    if token_floor != expansion.get("expanded_exclusion_token_floor") or receipt.get("exclusion_token_floor") != token_floor:
        failures.append({"code": "token_floor_mismatch", "rows": token_floor, "expansion": expansion.get("expanded_exclusion_token_floor"), "receipt": receipt.get("exclusion_token_floor")})
    if "not an all-pairs near-duplicate PASS" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "manifest_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_VALIDATED" if not failures else "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": MANIFEST_RECEIPT,
        "manifest_path": MANIFEST,
        "exclusion_document_count": len(rows),
        "exclusion_token_floor": token_floor,
        "completion_limit": "This validates materialization of targeted discovered-cluster exclusions only. It is not an all-pairs near-duplicate PASS, not a rebuilt filtered corpus, not eval-contamination evidence, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
