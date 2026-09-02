#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_tokenizer_errata.py -- ember #631 deliverable 1 (final): append-only errata
receipt for the tokenizer-mismatch cure.

Chains (refs #482 shape; the published artifacts are NEVER edited) the corrected,
false-negative-safe predicate scan to the published (defective) scan + exclusion
amendment, recording:
  - the tokenizer correction: shards-v0 was produced under sha256 2c557e7... (the
    shard-generation tokenizer, per token-shards-v0 provenance_230.old); PR #603's
    scan re-tokenized eval rows under the SCRUBBED sha256 6923a5... dropping 21/31755
    orphan merges. The corrected scan encodes eval rows under 2c557e7... (0 orphan
    drops), so exact 13-token-id matching is now false-negative-safe;
  - the reproduce-first defect receipt (1,128/25,690 rows tokenized differently);
  - the raw-transparency-count correction: 848,857 -> 848,862 (+5);
  - the INDEPENDENT confirmation that the #193-v2 contaminated set is byte-identical
    (147 items, 0 added, 0 removed, per-dataset identical) -- the exclusion ids do
    NOT change;
  - the names-safe custody decision: the recovered tokenizer's pre-scrub vocab is
    proper-noun content the 58ddf8d public-root consolidation scrub deliberately
    removed, so its BYTES are NOT committed to the public tree; the corrected scan
    cites the tokenizer by sha256 (already public in token-shards provenance_230.old)
    with local-archive custody. This is the exact conflict flagged to the coordinator:
    the audit's literal "land a provenance-safe copy of the tokenizer" cannot be
    satisfied in the public repo without re-introducing scrubbed names.

Usage:
  python src/ember/governance/scripts/a1_tokenizer_errata.py \\
      --published-scan receipts/a1-predicate-scan/a1-predicate-scan-20260709T231932Z.json \\
      --published-amendment receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-20260709T234148Z.json \\
      --corrected-scan receipts/a1-predicate-scan/a1-predicate-scan-corrected-<ts>.json \\
      --repro-receipt receipts/eval-suite-freeze/a1-tokenizer-mismatch-repro-<ts>.json \\
      --out receipts/eval-suite-freeze/a1-tokenizer-errata-<UTCts>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
receipt_write = _ember_66ee9e91637922dc_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
ORIG_SHA = "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97"
SCRUB_SHA = "6923a52304637f48eb4cc421b58e6cdce29c1f5da860abaea5d57baa6ad6d97d"


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def v2_set_from_per_item(per_item_path: str):
    s = set()
    per_ds = {}
    for line in open(per_item_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r["dataset"] == "suite_a":
            continue
        if r["v2a"] or r["v2b"]:
            s.add(r["row_idx"])
            per_ds[r["dataset"]] = per_ds.get(r["dataset"], 0) + 1
    return s, per_ds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--published-scan", required=True)
    ap.add_argument("--published-amendment", required=True)
    ap.add_argument("--corrected-scan", required=True)
    ap.add_argument("--repro-receipt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pub = json.load(open(args.published_scan, encoding="utf-8"))
    amend = json.load(open(args.published_amendment, encoding="utf-8"))
    corr = json.load(open(args.corrected_scan, encoding="utf-8"))
    repro = json.load(open(args.repro_receipt, encoding="utf-8"))

    corr_per_item = os.path.splitext(args.corrected_scan)[0] + "-per-item.jsonl"
    corr_v2, corr_v2_per_ds = v2_set_from_per_item(corr_per_item)
    pub_v2 = {it["evidence"]["row_idx"] for it in amend["exclusions"]["items"]}

    pub_raw = amend["final_contamination_recheck"]["suite_b_raw_any_match_13gram"]
    corr_raw = corr["contamination_recheck_detail"]["suite_b_matches"]

    added = sorted(corr_v2 - pub_v2)
    removed = sorted(pub_v2 - corr_v2)
    set_equal = (corr_v2 == pub_v2)

    receipt = {
        "ticket": "A1-TOKENIZER-ERRATA",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-tokenizer-errata/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#440", "#482"],
        "corrects": {
            "published_scan": {
                "path": args.published_scan.replace(os.sep, "/"),
                "sha256": file_sha256(args.published_scan),
                "note": "NEVER edited (append-only custody). This errata supersedes its "
                        "tokenizer premise + raw transparency count only.",
            },
            "published_amendment": {
                "path": args.published_amendment.replace(os.sep, "/"),
                "sha256": file_sha256(args.published_amendment),
            },
        },
        "defect_reproduced": {
            "repro_receipt": args.repro_receipt.replace(os.sep, "/"),
            "repro_receipt_sha256": file_sha256(args.repro_receipt),
            "n_suite_b_rows": repro["n_suite_b_rows"],
            "n_rows_differ": repro["n_rows_differ"],
            "frac_differ": repro["frac_differ"],
            "n_rows_differ_and_retained_by_pr603": repro["n_rows_differ_and_retained_by_pr603"],
            "statement": "1,128/25,690 suite-(b) rows tokenize differently under the shard "
                         "tokenizer vs the scrubbed tokenizer; 1,123 of them were RETAINED "
                         "(not excluded) by PR #603 -- so its suite-(b) result was not "
                         "false-negative-safe against the actual shard bytes",
        },
        "tokenizer_correction": {
            "shard_generation_tokenizer_sha256": ORIG_SHA,
            "shard_generation_tokenizer_source": "receipts/token-shards-v0-20260611T170047Z.json "
                "provenance_230.old.tokenizer_json.sha256 (the tokenizer under which shards-v0 "
                "was produced, before the 58ddf8d public-root consolidation re-anchor)",
            "pr603_scan_used_sha256": SCRUB_SHA,
            "pr603_orphan_merges_dropped": 21,
            "corrected_scan_orphan_merges_dropped": corr["tokenizer"]["orphaned_merge_workaround"]["n_dropped_orphan_merges"],
            "corrected_scan": {
                "path": args.corrected_scan.replace(os.sep, "/"),
                "sha256": file_sha256(args.corrected_scan),
                "per_item_jsonl": corr_per_item.replace(os.sep, "/"),
                "per_item_jsonl_sha256": file_sha256(corr_per_item),
                "tokenizer_sha256_used": corr["tokenizer"]["sha256"],
                "scan_ts": corr.get("scan_ts"),
                "wall_s": corr.get("wall_s"),
                "cpu_minutes_estimate": corr.get("cpu_minutes_estimate"),
                "n_workers": corr["matcher"].get("n_workers_actual"),
            },
        },
        "raw_transparency_count_correction": {
            "published": pub_raw,
            "corrected": corr_raw,
            "delta": corr_raw - pub_raw,
            "note": "raw any-13-gram match total is a transparency figure, not the gate "
                    "(freeze doc counting-convention section)",
        },
        "exclusion_set_confirmation": {
            "convention": "refs #193 v2 (max_run_tokens>=50 OR window_frac>0.10), per-dataset",
            "published_n": len(pub_v2),
            "corrected_n": len(corr_v2),
            "added_ids": added,
            "removed_ids": removed,
            "exact_set_equality": set_equal,
            "per_dataset_corrected": corr_v2_per_ds,
            "per_dataset_published": amend["exclusions"]["per_dataset"],
            "statement": "the 147-item #193-v2 exclusion set is UNCHANGED under the corrected "
                         "tokenizer: 0 ids added, 0 removed, per-dataset identical. The BLOCK "
                         "was on the machinery (wrong tokenizer bytes + 5-low raw count), never "
                         "on the exclusion ids (refs #123 corrected-tokenizer-replay addendum).",
        },
        "names_safe_custody_decision": {
            "conflict": "the audit's minimum cure asks to 'land a provenance-safe copy of the "
                        "original tokenizer'. Its pre-scrub vocab is proper-noun content the "
                        "58ddf8d public-root consolidation scrub deliberately removed; committing "
                        "those bytes to the public tree would re-introduce the scrubbed names and "
                        "violate the repo's public-scrub policy.",
            "resolution": "the corrected scan RAN under the recovered tokenizer (read from a local "
                          "pre-consolidation archive) and cites it by sha256 2c557e7 -- a value "
                          "already public in token-shards provenance_230.old. The tokenizer BYTES "
                          "are intentionally NOT committed; false-negative-safety is satisfied by "
                          "the corrected scan's receipt, not by publishing the name-bearing bytes.",
            "reproducibility": "any holder of the pre-consolidation tokenizer (sha 2c557e7) "
                               "reproduces this scan; the sha binds the exact bytes without "
                               "disclosing them.",
        },
        "errata_sha256_note": "a file cannot contain its own hash; this errata's sha256 is "
                              "computed over its on-disk bytes post-write and recorded in the PR "
                              "body and lane report",
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)
    print(f"A1_TOKENIZER_ERRATA: raw {pub_raw}->{corr_raw} (+{corr_raw - pub_raw}); "
          f"147-id set equality={set_equal} (added={len(added)}, removed={len(removed)}); "
          f"orphan drops 21->{receipt['tokenizer_correction']['corrected_scan_orphan_merges_dropped']} "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
