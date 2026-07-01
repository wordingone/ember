#!/usr/bin/env python3
"""Build deterministic remediation from v7 LSH candidate-index adjudication crossings."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CUMULATIVE_EXCLUSIONS_V7 = "fragments/c1-near-duplicate-cumulative-exclusions-v7-2026-07-01.jsonl"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_exclusion_keys(path: Path) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
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
    parser.add_argument("--adjudication", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    adjudication_rel = args.adjudication.replace("\\", "/")
    adjudication = read_json(root / adjudication_rel)
    existing_keys = read_exclusion_keys(root / CUMULATIVE_EXCLUSIONS_V7)
    threshold = float(adjudication.get("threshold", 0.8))

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

    for pair in adjudication.get("crossing_samples", []):
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
    token_floor = 0
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
                "reason": "cumulative_filtered_lsh_band48_v7_partial25_adjudication_near_duplicate_component",
            }
            remove.append(annotated)
            exclusions.append(annotated)
        if remove:
            token_floor += sum(int(row["token_len"]) for row in remove)
            clusters.append({
                "component_id": component_id,
                "keep": keep,
                "remove": remove,
                "member_count": len(ordered),
                "remove_count": len(remove),
            })
            component_id += 1
    exclusions = sorted(exclusions, key=doc_key)
    overlap = [row for row in exclusions if doc_key(row) in existing_keys]
    result = {
        "kind": "single_4090_c1_lsh_candidate_adjudication_remediation_v7",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_LSH_CANDIDATE_ADJUDICATION_V7_REMEDIATION_PACKET_READY_NOT_COMPLETION",
        "source_adjudication_receipt": adjudication_rel,
        "source_cumulative_exclusion_manifest": CUMULATIVE_EXCLUSIONS_V7,
        "threshold": adjudication.get("threshold"),
        "input_crossing_pair_count": adjudication.get("crossing_pair_count"),
        "input_max_exact_jaccard_observed": adjudication.get("max_exact_jaccard_observed"),
        "partial_index_adjudication": adjudication.get("partial_index_adjudication"),
        "index_rows_adjudicated": adjudication.get("index_rows_adjudicated"),
        "cluster_count": len(clusters),
        "unique_crossing_documents": len(docs),
        "remediation_exclusion_document_count": len(exclusions),
        "remediation_exclusion_token_floor": token_floor,
        "existing_cumulative_v7_manifest_overlap_count": len(overlap),
        "rule": "Within each connected component of above-threshold v7 band-48 partial candidate-index adjudication pairs, keep the lowest doc_index/doc_sha256 document and exclude the remaining documents before any follow-up C1 pass attempt.",
        "clusters": clusters,
        "exclusions": exclusions,
        "scope_limit": "This remediation packet covers only crossing pairs found in the named v7 partial candidate-index adjudication receipt. It is not a full band-48 remediation, not a full 16-band remediation, not a C1 near-duplicate PASS, and not overall baseline completion.",
        "completion_limit": "This packet is actionable remediation evidence only. Materializing a follow-up cumulative exclusion manifest, rerunning candidate indexing/adjudication, full eval-contamination receipts, and overall verifier PASS remain required.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
