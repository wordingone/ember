#!/usr/bin/env python3
"""Build deterministic remediation for the targeted-filtered C1 challenge."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHALLENGE_RECEIPT = "receipts/4090-targeted-filtered-near-duplicate-sample-2026-06-30.json"
TARGETED_EXCLUSIONS = "fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_targeted_exclusion_keys(path: Path) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    if not path.exists():
        return keys
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        keys.add((int(row["doc_index"]), str(row["doc_sha256"])))
    return keys


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
    challenge = read_json(root / CHALLENGE_RECEIPT)
    targeted_keys = read_targeted_exclusion_keys(root / TARGETED_EXCLUSIONS)
    threshold = float(challenge.get("threshold", 0.8))

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

    for pair in challenge.get("crossing_samples", []):
        if float(pair.get("exact_jaccard", 0.0)) < threshold:
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
    component_id = 0
    for members in sorted(grouped.values(), key=lambda rows: min(doc_key(row) for row in rows)):
        ordered = sorted(members, key=doc_key)
        keep = {**ordered[0], "component_id": component_id, "kept": True}
        remove = []
        for row in ordered[1:]:
            annotated = {
                **row,
                "component_id": component_id,
                "kept": False,
                "reason": "targeted_filtered_challenge_near_duplicate_component",
            }
            remove.append(annotated)
            exclusions.append(annotated)
        if remove:
            token_exclusion_floor += sum(int(row["token_len"]) for row in remove)
            clusters.append(
                {
                    "component_id": component_id,
                    "keep": keep,
                    "remove": remove,
                    "member_count": len(ordered),
                    "remove_count": len(remove),
                }
            )
            component_id += 1

    exclusions = sorted(exclusions, key=doc_key)
    overlap = [row for row in exclusions if doc_key(row) in targeted_keys]
    result = {
        "kind": "single_4090_c1_targeted_filtered_challenge_remediation",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_TARGETED_FILTERED_CHALLENGE_REMEDIATION_PACKET_READY",
        "source_receipt": CHALLENGE_RECEIPT,
        "targeted_exclusion_manifest": TARGETED_EXCLUSIONS,
        "threshold": challenge.get("threshold"),
        "input_crossing_pair_count": challenge.get("crossing_pair_count"),
        "input_max_exact_jaccard_observed": challenge.get("max_exact_jaccard_observed"),
        "sampled_excluded_document_count": challenge.get("sampled_excluded_document_count"),
        "cluster_count": len(clusters),
        "unique_crossing_documents": len(docs),
        "challenge_exclusion_document_count": len(exclusions),
        "challenge_exclusion_token_floor": token_exclusion_floor,
        "existing_targeted_manifest_overlap_count": len(overlap),
        "rule": "Within each connected component of above-threshold targeted-filtered challenge pairs, keep the lowest doc_index/doc_sha256 document and exclude the remaining documents before any C1 pass attempt.",
        "clusters": clusters,
        "exclusions": exclusions,
        "scope_limit": "This is challenge-sample remediation only for the targeted-filtered near-duplicate challenge receipt. It does not rewrite token shards and does not claim corpus-wide hygiene.",
        "completion_limit": "This is deterministic challenge-sample remediation only; all-pairs/full-corpus PASS remains required before C1 data hygiene or the overall baseline can complete.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
