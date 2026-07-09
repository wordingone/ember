#!/usr/bin/env python3
"""a1_exclusion_amendment.py -- exclusion AMENDMENT to the A1 freeze
declaration, per the coordinator ruling on issue #593 (comment 4930531475,
dated 2026-07-09; the binding text).

Ruling applied: suite (b) pre-exclusion = 147 contaminated ITEMS under the
refs #193 v2 convention -> cure = EXCLUSION WITH DISCLOSURE. The hashed
declaration is NEVER edited (append-only custody, refs #482 shape); this
amendment chains to it by sha256 and the frozen suite definition becomes
declaration + amendment.

The amendment:
  - re-derives the 147 excluded items MECHANICALLY from the committed
    per-item JSONL (rows with v2a or v2b true), never from a hand-kept list;
  - maps each excluded row to its dataset-native item id by re-reading the
    sha-verified test splits in the exact row order the scan used;
  - records the declaration's path + sha256 (chain);
  - records the adopted convention verbatim (thresholds, window, tokenizer);
  - carries the FINAL contamination_recheck field: suite (a) 0 / suite (b)
    0 post-exclusion, pre-exclusion 147 disclosed inline;
  - states AC4 anchoring: the held-out selection binds to the v1
    declaration hash at first derivation -- an amendment NEVER re-rolls it.

A file cannot contain its own sha256; the amendment's hash is computed
post-write, printed by this script, and recorded in PR #603 + the lane
report (the chain's second half lives outside the file by necessity).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import receipt_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

# dataset name -> (on-disk dir, native id field(s) in row order of preference)
DATASET_ID_FIELDS = {
    "MMLU-Pro": ("MMLU-Pro", ["question_id"]),
    "GSM8K": ("GSM8K", []),
    "MATH-500": ("MATH-500", []),
    "ARC-Challenge": ("ARC-Challenge", ["id"]),
    "HumanEval+": ("HumanEvalplus", ["task_id"]),
    "MBPP": ("MBPP", ["task_id"]),
    "HellaSwag": ("HellaSwag", ["ind", "source_id"]),
}


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--declaration", required=True)
    ap.add_argument("--scan-receipt", required=True)
    ap.add_argument("--per-item-jsonl", required=True)
    ap.add_argument("--eval-suite-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    decl_path = os.path.join(REPO, args.declaration)
    decl = json.load(open(decl_path, encoding="utf-8"))
    decl_sha = file_sha256(decl_path)
    scan_path = os.path.join(REPO, args.scan_receipt)
    scan = json.load(open(scan_path, encoding="utf-8"))
    scan_sha = file_sha256(scan_path)

    # --- select excluded rows mechanically from the per-item JSONL ---
    per_item_path = os.path.join(REPO, args.per_item_jsonl)
    per_item_sha = file_sha256(per_item_path)
    excluded_rows = []
    with open(per_item_path, "r", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("v2a") or r.get("v2b"):
                excluded_rows.append(r)

    # --- rebuild row_idx -> (dataset, dataset_line, native_id) mapping by
    #     re-reading the sha-verified splits in the scan's exact row order ---
    suite_b_order = [ds["name"] for ds in decl["suite_b"]["datasets"]]
    sha_by_name = {ds["name"]: ds["test_split_sha256"] for ds in decl["suite_b"]["datasets"]}
    n_suite_a = decl["suite_a"]["n_rows"]

    row_map: dict[int, dict] = {}
    row_idx = n_suite_a
    for name in suite_b_order:
        dirn, id_fields = DATASET_ID_FIELDS[name]
        p = Path(args.eval_suite_dir) / dirn / "test.jsonl"
        actual = file_sha256(str(p))
        if actual != sha_by_name[name]:
            raise SystemExit(f"A1_AMENDMENT_SHA_DRIFT: {name} {actual} != {sha_by_name[name]}")
        with open(p, "r", encoding="utf-8") as fh:
            ds_line = 0
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                native = {f: obj[f] for f in id_fields if f in obj}
                row_map[row_idx] = {"dataset": name, "dataset_line": ds_line,
                                     "native_id": native if native else {"line_index": ds_line}}
                row_idx += 1
                ds_line += 1

    exclusions = []
    per_dataset_counts: dict[str, int] = {}
    for r in excluded_rows:
        m = row_map[r["row_idx"]]
        per_dataset_counts[m["dataset"]] = per_dataset_counts.get(m["dataset"], 0) + 1
        exclusions.append({
            "dataset": m["dataset"],
            "dataset_line": m["dataset_line"],
            "native_id": m["native_id"],
            "v2a_run_ge50tok": bool(r["v2a"]),
            "v2b_frac_gt10pct": bool(r["v2b"]),
            "window_frac": r["window_frac"],
            "max_run_tokens": r["max_run_tokens"],
            "evidence": {
                "per_item_jsonl": args.per_item_jsonl.replace(os.sep, "/"),
                "row_idx": r["row_idx"],
                "jsonl_line": r["row_idx"] + 1,
            },
        })

    n_excluded = len(exclusions)

    receipt = {
        "ticket": "A1-FREEZE-EXCLUSION-AMENDMENT",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-freeze-exclusion-amendment/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#593", "#193", "#440", "#591", "#123"],
        "ruling": {
            "source": "issue #593 coordinator ruling comment 4930531475 (dated, binding)",
            "verdict": "suite (b) pre-exclusion = 147 contaminated items under the "
                       "refs #193 v2 convention; cure = exclusion with disclosure; "
                       "post-exclusion suite (b) = 0; A1 gate passes on these "
                       "receipts once this amendment lands",
        },
        "chain": {
            "declaration": {
                "path": args.declaration.replace(os.sep, "/"),
                "sha256": decl_sha,
                "note": "NEVER edited (append-only custody, refs #482 shape); the "
                        "frozen suite definition = declaration + this amendment",
            },
            "scan_receipt": {
                "path": args.scan_receipt.replace(os.sep, "/"),
                "sha256": scan_sha,
            },
            "per_item_jsonl": {
                "path": args.per_item_jsonl.replace(os.sep, "/"),
                "sha256": per_item_sha,
            },
            "amendment_sha256_note": "a file cannot contain its own hash; this "
                                      "amendment's sha256 is computed over its "
                                      "on-disk bytes post-write and recorded in "
                                      "PR #603 and the lane report",
        },
        "adopted_convention": {
            "name": "refs #193 v2 (ADOPTED AS SPEC via #593 / PR #603)",
            "window_tokens": 13,
            "tokenizer": {
                "path": "tokenizer/tokenizer.json",
                "sha256": "6923a52304637f48eb4cc421b58e6cdce29c1f5da860abaea5d57baa6ad6d97d",
                "encode_semantics": "added-token-matching-disabled-v1; 21/31755 "
                                     "vocab-absent merges dropped in-memory "
                                     "(disclosed in the scan receipt)",
            },
            "item_contaminated_iff": "(a) max_run_tokens >= 50 (longest consecutive "
                                      "matched-window run + 12, the upper-bound proxy "
                                      "defined in the scan receipt) OR (b) matched "
                                      "13-gram window fraction > 0.10",
            "applied_per_dataset": True,
        },
        "exclusions": {
            "n_excluded": n_excluded,
            "per_dataset": per_dataset_counts,
            "items": exclusions,
        },
        "post_exclusion_suite_b": {
            "definition": "the declaration's seven pinned datasets MINUS the "
                          "items enumerated above; scoring runs must skip these "
                          "items and cite this amendment",
            "contaminated_items_remaining": 0,
        },
        "final_contamination_recheck": {
            "suite_a": 0,
            "suite_b_post_exclusion": 0,
            "suite_b_pre_exclusion_items": n_excluded,
            "suite_b_raw_any_match_13gram": 848857,
            "note": "pre-exclusion figure disclosed inline per the ruling; raw "
                    "any-match total is the transparency figure, not the gate",
        },
        "ac4_anchoring": {
            "statement": "the AC4 held-out selection stays anchored to the v1 "
                         "declaration hash ccde4a676085e633b69d8ba1b501b80f49e2e907 "
                         "consumed at first derivation (index 7 -> SciQ); an "
                         "amendment NEVER re-rolls AC4 -- the selection binds once, "
                         "at first derivation, dated (ruling point 3)",
        },
    }

    out_abs = os.path.join(REPO, args.out)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    receipt_write.checked_write(out_abs, receipt)
    amendment_sha = file_sha256(out_abs)
    print(f"A1_AMENDMENT: excluded={n_excluded} per_dataset={per_dataset_counts}")
    print(f"A1_AMENDMENT_CHAIN: declaration_sha256={decl_sha}")
    print(f"A1_AMENDMENT_SHA256: {amendment_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
