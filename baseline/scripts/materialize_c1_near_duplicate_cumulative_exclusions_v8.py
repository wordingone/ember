#!/usr/bin/env python3
"""Materialize cumulative C1 near-duplicate exclusions v8 from v7 band-48 partial adjudication remediation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v7-2026-07-01.jsonl"
BASE_RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-2026-07-01.json"
REMEDIATION_RECEIPT = "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-remediation-2026-07-01.json"
OUT_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v8-2026-07-01.jsonl"
VERDICT = "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V8_READY_NOT_COMPLETION"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_rows(rows: list[dict[str, Any]]) -> str:
    payload = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_out = args.manifest_out or (root / OUT_MANIFEST)
    base_rows = read_jsonl(root / BASE_MANIFEST)
    base_receipt = read_json(root / BASE_RECEIPT)
    remediation = read_json(root / REMEDIATION_RECEIPT)
    failures: list[dict[str, Any]] = []
    if remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V7_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "remediation_bad_verdict", "actual": remediation.get("verdict")})
    if remediation.get("existing_cumulative_v7_manifest_overlap_count") != 0:
        failures.append({"code": "remediation_overlap_not_zero", "actual": remediation.get("existing_cumulative_v7_manifest_overlap_count")})

    cumulative: list[dict[str, Any]] = []
    for row in base_rows:
        cumulative.append({
            "doc_index": int(row["doc_index"]),
            "doc_sha256": str(row["doc_sha256"]),
            "shard": str(row["shard"]),
            "token_len": int(row["token_len"]),
            "source": "cumulative_v7",
            "source_receipt": BASE_RECEIPT,
        })
    for row in remediation.get("exclusions", []):
        cumulative.append({
            "doc_index": int(row["doc_index"]),
            "doc_sha256": str(row["doc_sha256"]),
            "shard": str(row["shard"]),
            "token_len": int(row["token_len"]),
            "source": "lsh_band48_v7_partial25_adjudication_remediation",
            "source_receipt": REMEDIATION_RECEIPT,
            "component_id": int(row["component_id"]),
            "reason": str(row.get("reason", "cumulative_filtered_lsh_band48_partial25_adjudication_near_duplicate_component")),
        })
    cumulative = sorted(cumulative, key=lambda row: (row["doc_index"], row["doc_sha256"], row["source"]))

    seen_keys = set()
    seen_indices: dict[int, dict[str, Any]] = {}
    source_overlap_count = 0
    for row in cumulative:
        key = (row["doc_index"], row["doc_sha256"])
        if key in seen_keys:
            failures.append({"code": "duplicate_key", "doc_index": row["doc_index"], "doc_sha256": row["doc_sha256"]})
        seen_keys.add(key)
        existing = seen_indices.get(row["doc_index"])
        if existing is not None:
            source_overlap_count += 1
            if existing["doc_sha256"] != row["doc_sha256"]:
                failures.append({"code": "doc_index_hash_conflict", "doc_index": row["doc_index"], "first": existing["doc_sha256"], "second": row["doc_sha256"]})
        seen_indices[row["doc_index"]] = row

    expected_count = int(base_receipt.get("exclusion_document_count", -1)) + int(remediation.get("remediation_exclusion_document_count", -1))
    expected_tokens = int(base_receipt.get("exclusion_token_floor", -1)) + int(remediation.get("remediation_exclusion_token_floor", -1))
    exclusion_tokens = sum(int(row["token_len"]) for row in cumulative)
    if len(cumulative) != expected_count:
        failures.append({"code": "count_mismatch", "actual": len(cumulative), "expected": expected_count})
    if exclusion_tokens != expected_tokens:
        failures.append({"code": "token_floor_mismatch", "actual": exclusion_tokens, "expected": expected_tokens})

    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in cumulative), encoding="utf-8", newline="\n")
    source_counts: dict[str, int] = {}
    for row in cumulative:
        source_counts[row["source"]] = source_counts.get(row["source"], 0) + 1
    result = {
        "kind": "single_4090_c1_near_duplicate_cumulative_exclusion_manifest_v8",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": VERDICT if not failures else "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V8_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "source_base_exclusion_receipt": BASE_RECEIPT,
        "source_base_manifest": BASE_MANIFEST,
        "source_base_manifest_sha256": sha256_file(root / BASE_MANIFEST),
        "source_lsh_adjudication_remediation_receipt": REMEDIATION_RECEIPT,
        "manifest": {
            "repo_path": OUT_MANIFEST,
            "sha256": sha256_file(manifest_out),
            "line_count": len(cumulative),
            "row_digest_sha256": digest_rows(cumulative),
        },
        "source_counts": source_counts,
        "source_overlap_count": source_overlap_count,
        "exclusion_document_count": len(cumulative),
        "exclusion_token_floor": exclusion_tokens,
        "completion_limit": "This materializes cumulative discovered-cluster exclusions v8 from v7 partial band-48 LSH adjudication remediation only. It is not a full band-48 remediation, not an all-pairs near-duplicate PASS, not eval-contamination evidence, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
