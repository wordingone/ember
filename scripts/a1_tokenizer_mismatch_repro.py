#!/usr/bin/env python3
"""a1_tokenizer_mismatch_repro.py -- ember #631 deliverable 1, REPRODUCE-FIRST.

Demonstrates the A1 machinery defect #1 (refs #123 comment finding 1): PR #603's
predicate scan (receipts/a1-predicate-scan/a1-predicate-scan-20260709T231932Z.json)
tokenized the shards-v0 corpus under the shard-generation tokenizer
(sha256 2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97, recorded
as the shard tokenizer in receipts/token-shards-v0-20260611T170047Z.json
provenance_230.old.tokenizer_json.sha256) but re-tokenized the eval rows under the
POST-CONSOLIDATION scrubbed tokenizer (sha256 6923a5...). When the two tokenizers
disagree on a row's token ids, an identical shared substring no longer produces the
same 13-token-id window, so an exact-id match can be a FALSE NEGATIVE.

This script encodes every suite-(b) eval row under BOTH tokenizers (identical
"added-token-matching-disabled-v1" load semantics) and counts the rows whose token
ids differ. A nonzero differ-count is the defect: the checked-in scan's suite-(b)
zero is not false-negative-safe against the actual shard bytes.

Output is COUNTS and row indices only -- never token strings (the scrubbed vocab is
proper-noun content removed by the 58ddf8d public-root consolidation scrub; this
script never emits it, and the original tokenizer bytes are read from a caller-
supplied path, never committed).

Usage:
  python scripts/a1_tokenizer_mismatch_repro.py \\
      --scrubbed-tokenizer domains/model/tokenizer/tokenizer.json \\
      --original-tokenizer <local-archive path to the 2c557e7 tokenizer.json> \\
      --eval-suite-dir <sha-verified eval-suite-v1 copy> \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --published-amendment receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-20260709T234148Z.json \\
      --out receipts/eval-suite-freeze/a1-tokenizer-mismatch-repro-<UTCts>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "w2_heldout"))

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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
# issue2015 exact-local-import:src/ember/governance/scripts/a1_predicate_scan.py
import importlib.util as _ember_376b57c2d601539f_importlib
import sys as _ember_376b57c2d601539f_sys
from pathlib import Path as _ember_376b57c2d601539f_Path
_ember_376b57c2d601539f_path = _ember_376b57c2d601539f_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'a1_predicate_scan.py')
if not _ember_376b57c2d601539f_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/a1_predicate_scan.py')
_ember_376b57c2d601539f_aliases = ('_ember_issue2015_376b57c2d601539f', 'a1_predicate_scan', 'scripts.a1_predicate_scan')
_ember_376b57c2d601539f_existing = []
for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
    _ember_376b57c2d601539f_candidate = _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias)
    if _ember_376b57c2d601539f_candidate is not None and all(_ember_376b57c2d601539f_candidate is not item for item in _ember_376b57c2d601539f_existing):
        _ember_376b57c2d601539f_existing.append(_ember_376b57c2d601539f_candidate)
if len(_ember_376b57c2d601539f_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/a1_predicate_scan.py')
if _ember_376b57c2d601539f_existing:
    _ember_376b57c2d601539f_module = _ember_376b57c2d601539f_existing[0]
    _ember_376b57c2d601539f_observed = getattr(_ember_376b57c2d601539f_module, '__file__', None)
    if _ember_376b57c2d601539f_observed is None or _ember_376b57c2d601539f_Path(_ember_376b57c2d601539f_observed).resolve() != _ember_376b57c2d601539f_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/a1_predicate_scan.py')
else:
    _ember_376b57c2d601539f_spec = _ember_376b57c2d601539f_importlib.spec_from_file_location('_ember_issue2015_376b57c2d601539f', _ember_376b57c2d601539f_path)
    if _ember_376b57c2d601539f_spec is None or _ember_376b57c2d601539f_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/a1_predicate_scan.py')
    _ember_376b57c2d601539f_module = _ember_376b57c2d601539f_importlib.module_from_spec(_ember_376b57c2d601539f_spec)
    for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
        _ember_376b57c2d601539f_prior = _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias)
        if _ember_376b57c2d601539f_prior is not None and _ember_376b57c2d601539f_prior is not _ember_376b57c2d601539f_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/a1_predicate_scan.py')
        _ember_376b57c2d601539f_sys.modules[_ember_376b57c2d601539f_alias] = _ember_376b57c2d601539f_module
    try:
        _ember_376b57c2d601539f_spec.loader.exec_module(_ember_376b57c2d601539f_module)
    except BaseException:
        for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
            if _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias) is _ember_376b57c2d601539f_module:
                _ember_376b57c2d601539f_sys.modules.pop(_ember_376b57c2d601539f_alias, None)
        raise
for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
    _ember_376b57c2d601539f_prior = _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias)
    if _ember_376b57c2d601539f_prior is not None and _ember_376b57c2d601539f_prior is not _ember_376b57c2d601539f_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/a1_predicate_scan.py')
    _ember_376b57c2d601539f_sys.modules[_ember_376b57c2d601539f_alias] = _ember_376b57c2d601539f_module
scan = _ember_376b57c2d601539f_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/a1_predicate_scan.py  # noqa: E402

SCRUB_SHA = "6923a52304637f48eb4cc421b58e6cdce29c1f5da860abaea5d57baa6ad6d97d"
ORIG_SHA = "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scrubbed-tokenizer", default="domains/model/tokenizer/tokenizer.json")
    ap.add_argument("--original-tokenizer", required=True)
    ap.add_argument("--eval-suite-dir", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--published-amendment", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tk_scrub, sha_scrub, dropped_scrub, _ = scan.load_stripped_tokenizer(
        args.scrubbed_tokenizer, SCRUB_SHA)
    tk_orig, sha_orig, dropped_orig, _ = scan.load_stripped_tokenizer(
        args.original_tokenizer, ORIG_SHA)

    freeze_receipt = json.load(open(args.freeze_receipt, encoding="utf-8"))

    # published-amendment excluded row_idx set (suite-b indices in the published
    # scan's eval_rows ordering; suite-b begins after the 16 suite-a rows).
    amend = json.load(open(args.published_amendment, encoding="utf-8"))
    excluded_row_idx = {it["evidence"]["row_idx"] for it in amend["exclusions"]["items"]}

    # Walk the seven pinned splits in freeze order, encoding each row's
    # extract_text under both tokenizers. Row index space matches the published
    # scan: suite-a occupies [0,16); suite-b rows begin at 16.
    N_SUITE_A = 16
    row_idx = N_SUITE_A
    n_rows = 0
    n_differ = 0
    n_differ_retained = 0  # differing AND not in the published 147 exclusion set
    per_dataset = {}
    differ_first_20 = []

    for ds in freeze_receipt["datasets"]:
        name = ds["name"]
        if ds.get("test_split_sha256") in (None, "PIN-PENDING"):
            continue
        dirn = scan.DIR_NAME_MAP[name]
        p = os.path.join(args.eval_suite_dir, dirn, "test.jsonl")
        d_rows = d_diff = 0
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                text = scan.extract_text(json.loads(line))
                a = tk_scrub.encode(text, add_special_tokens=False).ids
                b = tk_orig.encode(text, add_special_tokens=False).ids
                differ = (a != b)
                n_rows += 1
                d_rows += 1
                if differ:
                    n_differ += 1
                    d_diff += 1
                    if row_idx not in excluded_row_idx:
                        n_differ_retained += 1
                    if len(differ_first_20) < 20:
                        differ_first_20.append({"row_idx": row_idx, "dataset": name,
                                                "len_scrubbed": len(a), "len_original": len(b)})
                row_idx += 1
        per_dataset[name] = {"n_rows": d_rows, "n_differ": d_diff}

    receipt = {
        "ticket": "A1-TOKENIZER-MISMATCH-REPRO",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-tokenizer-mismatch-repro/v1",
        "invariant_sha256": scan.INVARIANT_SHA256,
        "sha_convention": scan.SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#440"],
        "defect": "PR #603 predicate scan re-tokenized eval rows under the scrubbed "
                  "tokenizer (sha 6923a5...) while shards-v0 was tokenized under the "
                  "shard-generation tokenizer (sha 2c557e7...); token-id disagreement "
                  "on a row makes exact 13-id-window matching a possible FALSE NEGATIVE",
        "tokenizers": {
            "scrubbed_on_disk": {"path": "domains/model/tokenizer/tokenizer.json", "sha256": sha_scrub,
                                  "n_orphan_merges_dropped_in_memory": dropped_scrub},
            "original_shardgen": {"sha256": sha_orig,
                                   "n_orphan_merges_dropped_in_memory": dropped_orig,
                                   "custody": "read from a local pre-consolidation archive; "
                                              "bytes NOT committed (carry pre-scrub proper-noun "
                                              "vocab removed by the 58ddf8d public-root scrub); "
                                              "sha is the public token-shards receipt's "
                                              "provenance_230.old.tokenizer_json.sha256"},
        },
        "n_suite_b_rows": n_rows,
        "n_rows_differ": n_differ,
        "frac_differ": round(n_differ / n_rows, 8) if n_rows else 0.0,
        "n_rows_differ_and_retained_by_pr603": n_differ_retained,
        "per_dataset": per_dataset,
        "differ_first_20": differ_first_20,
        "verdict": ("DEFECT REPRODUCED: eval rows tokenize differently under the shard "
                    "tokenizer; PR #603's scan is not false-negative-safe"
                    if n_differ else "NO DIFFERENCE (unexpected)"),
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)
    print(f"A1_TOKENIZER_MISMATCH_REPRO: {n_differ}/{n_rows} suite-b rows differ "
          f"({100.0 * n_differ / n_rows:.6f}%), {n_differ_retained} of them retained by "
          f"PR #603 (not in the 147 exclusion set); orphan_drops scrubbed={dropped_scrub} "
          f"original={dropped_orig} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
