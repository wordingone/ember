#!/usr/bin/env python3
"""Build a deterministic remediation packet for the C1 near-duplicate sample."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAMPLE_RECEIPT = "receipts/4090-near-duplicate-minhash-sample-2026-06-30.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def doc_key(row: dict[str, Any]) -> tuple[int, str]:
    return (int(row["doc_index"]), str(row["doc_sha256"]))


def make_doc(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_index": int(row["doc_index"]),
        "doc_sha256": str(row["doc_sha256"]),
        "shard": str(row["shard"]),
        "token_len": int(row["token_len"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    sample = read_json(root / SAMPLE_RECEIPT)
    threshold = sample.get("threshold")

    parent: dict[tuple[int, str], tuple[int, str]] = {}
    docs: dict[tuple[int, str], dict[str, Any]] = {}

    def find(x: tuple[int, str]) -> tuple[int, str]:
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: tuple[int, str], b: tuple[int, str]) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for pair in sample.get("crossing_samples", []):
        if float(pair.get("exact_jaccard", 0.0)) < float(threshold):
            continue
        left = make_doc(pair["left"])
        right = make_doc(pair["right"])
        lk = doc_key(left)
        rk = doc_key(right)
        docs[lk] = left
        docs[rk] = right
        union(lk, rk)

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for key, row in docs.items():
        grouped[find(key)].append(row)

    clusters = []
    exclusions = []
    token_exclusion_floor = 0
    for members in grouped.values():
        ordered = sorted(members, key=lambda row: (row["doc_index"], row["doc_sha256"]))
        keep = ordered[0]
        remove = ordered[1:]
        if not remove:
            continue
        token_exclusion_floor += sum(int(row["token_len"]) for row in remove)
        clusters.append(
            {
                "keep": keep,
                "remove": remove,
                "member_count": len(ordered),
                "remove_count": len(remove),
            }
        )
        exclusions.extend(remove)

    exclusions = sorted(exclusions, key=lambda row: (row["doc_index"], row["doc_sha256"]))
    result = {
        "kind": "single_4090_c1_near_duplicate_sample_remediation",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_PACKET_READY",
        "source_receipt": SAMPLE_RECEIPT,
        "threshold": threshold,
        "input_crossing_pair_count": sample.get("crossing_pair_count"),
        "input_max_exact_jaccard_observed": sample.get("max_exact_jaccard_observed"),
        "cluster_count": len(clusters),
        "unique_crossing_documents": len(docs),
        "sample_exclusion_document_count": len(exclusions),
        "sample_exclusion_token_floor": token_exclusion_floor,
        "rule": "Within each connected component of above-threshold sample pairs, keep the lowest doc_index/doc_sha256 document and exclude the remaining documents before any C1 pass attempt.",
        "clusters": clusters,
        "exclusions": exclusions,
        "scope_limit": "This remediates only the checked-in bounded sample crossing pairs. It is not a full-corpus near-duplicate remediation list and cannot complete C1 data hygiene by itself.",
        "completion_limit": "This is a deterministic sample remediation packet only. Full-corpus MinHash scan, full-corpus exclusion materialization, and post-remediation PASS validation remain required.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
