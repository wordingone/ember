#!/usr/bin/env python3
"""Materialize targeted C1 near-duplicate exclusions into a replayable manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPANSION_RECEIPT = "receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json"
MANIFEST = "fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    expansion = read_json(root / EXPANSION_RECEIPT)
    manifest_path = args.manifest or (root / MANIFEST)
    exclusions = sorted(expansion.get("exclusions", []), key=lambda row: (int(row["doc_index"]), str(row["doc_sha256"])))
    target_indices = {int(row["target_doc_index"]) for row in expansion.get("target_summaries", [])}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[int, str]] = set()
    with manifest_path.open("w", encoding="utf-8", newline="\n") as fh:
        for ordinal, row in enumerate(exclusions):
            doc_index = int(row["doc_index"])
            doc_sha256 = str(row["doc_sha256"])
            key = (doc_index, doc_sha256)
            if key in seen:
                raise SystemExit(f"duplicate exclusion {key}")
            if doc_index in target_indices:
                raise SystemExit(f"target representative cannot be excluded: {doc_index}")
            seen.add(key)
            materialized = {
                "ordinal": ordinal,
                "action": "exclude_from_c1_targeted_near_duplicate_clusters",
                "doc_index": doc_index,
                "doc_sha256": doc_sha256,
                "exact_jaccard_to_target": row["exact_jaccard_to_target"],
                "shard": row["shard"],
                "token_len": row["token_len"],
                "source_receipt": EXPANSION_RECEIPT,
            }
            fh.write(json.dumps(materialized, sort_keys=True, separators=(",", ":")) + "\n")
    failures: list[dict[str, Any]] = []
    if len(seen) != expansion.get("expanded_exclusion_document_count"):
        failures.append({"code": "manifest_count_mismatch", "manifest": len(seen), "expansion": expansion.get("expanded_exclusion_document_count")})
    token_floor = sum(int(row["token_len"]) for row in exclusions)
    if token_floor != expansion.get("expanded_exclusion_token_floor"):
        failures.append({"code": "manifest_token_floor_mismatch", "manifest": token_floor, "expansion": expansion.get("expanded_exclusion_token_floor")})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_READY" if not failures else "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_near_duplicate_targeted_exclusion_manifest",
        "source_receipt": EXPANSION_RECEIPT,
        "manifest": {
            "repo_path": MANIFEST,
            "sha256": sha256_file(manifest_path),
            "line_count": len(seen),
            "byte_size": manifest_path.stat().st_size,
        },
        "target_representatives_kept": sorted(target_indices),
        "exclusion_document_count": len(seen),
        "exclusion_token_floor": token_floor,
        "completion_limit": "This materializes exclusions for discovered targeted near-duplicate clusters only. It is not an all-pairs near-duplicate PASS, not a rebuilt filtered training corpus, not an eval-contamination PASS, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
