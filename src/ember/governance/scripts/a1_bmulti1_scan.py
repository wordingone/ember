#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_bmulti1_scan.py -- ember #631 deliverable 3a: scan manifests/corpus/b-multi-1
(the image-caption multimodal corpus PR #603 left DISCLOSED-but-unscanned) against
the frozen eval suites (a)+(b).

Cures the "unscanned owned corpus" half of A1 machinery defect #3 (refs #123
finding 3): #603's scan explicitly left b-multi-1 out of the predicate universe.
b-multi-1 is 500 image-caption rows; the caption text is the only natural-language
content that could contaminate a text eval, so this scan tokenizes each caption
(doc-separated, id 0, matching the production shard writer convention) into a
synthesized in-memory uint16 shard and runs the SAME production matcher
(contamination_recheck_mp) that the main predicate scan uses.

Tokenizer: the recovered shard-generation tokenizer (sha256 2c557e7...), same as
the #631 corrected main scan, so the two scans' encodings compose. b-multi-1's
captions are web image captions (no proper nouns from the scrubbed set are expected;
the tokenizer bytes are read from a local archive, never committed).

The synthesized b-multi-1 shard is written to a throwaway temp dir OUTSIDE any repo
and removed after the scan (nothing committed but the receipt).

Usage:
  python src/ember/governance/scripts/a1_bmulti1_scan.py \\
      --bmulti1-manifest manifests/corpus/b-multi-1/raw/manifest.jsonl \\
      --shard-dir <shards-v0 dir, for suite-(a) reconstruction only> \\
      --eval-suite-dir <sha-verified eval-suite-v1 copy> \\
      --heldout-receipt receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --tokenizer-json <local original tokenizer> --tokenizer-sha 2c557e7... \\
      --out receipts/a1-predicate-scan/a1-bmulti1-scan-<UTCts>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "w2_heldout"))

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
import build_decontam_batch_mp as bdbm  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/a1_predicate_scan.py
import importlib.util as _ember_376b57c2d601539f_importlib
import sys as _ember_376b57c2d601539f_sys
from pathlib import Path as _ember_376b57c2d601539f_Path
_ember_376b57c2d601539f_path = _ember_376b57c2d601539f_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'a1_predicate_scan.py')
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

SEP_ID = 0  # writer-inserted doc-boundary separator (token-shards-v0 convention)


def build_bmulti1_shard(manifest_path: str, tk, out_bin: str) -> dict:
    """Tokenize each b-multi-1 caption, join with the doc separator, write a
    uint16 shard. Returns corpus stats."""
    n_captions = 0
    n_content_tokens = 0
    max_caption_tokens = 0
    stream: list[int] = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cap = row.get("caption", "")
            if not isinstance(cap, str) or not cap:
                continue
            ids = tk.encode(cap, add_special_tokens=False).ids
            n_captions += 1
            n_content_tokens += len(ids)
            max_caption_tokens = max(max_caption_tokens, len(ids))
            stream.extend(ids)
            stream.append(SEP_ID)  # doc boundary
    arr = np.asarray(stream, dtype="<u2")
    with open(out_bin, "wb") as fh:
        fh.write(arr.tobytes())
    n_windows = max(0, len(arr) - bdbm.CONTAMINATION_WINDOW_TOKENS + 1)
    return {
        "field_scanned": "caption",
        "n_captions": n_captions,
        "n_content_tokens": n_content_tokens,
        "n_stream_tokens_with_separators": int(len(arr)),
        "max_caption_tokens": max_caption_tokens,
        "n_13gram_windows": n_windows,
        "separator_id": SEP_ID,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bmulti1-manifest", required=True)
    ap.add_argument("--shard-dir", required=True)
    ap.add_argument("--eval-suite-dir", required=True)
    ap.add_argument("--heldout-receipt", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--tokenizer-json", required=True)
    ap.add_argument("--tokenizer-sha", default=None)
    ap.add_argument("--tokenizer-label", default="recovered-shard-generation-tokenizer")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    t0 = time.perf_counter()
    commit_total_gb, commit_free_gb = bdbm._preflight_check_commit()
    tk, tok_sha, dropped, _ = scan.load_stripped_tokenizer(args.tokenizer_json, args.tokenizer_sha)

    tmpdir = tempfile.mkdtemp(prefix="a1_bmulti1_")
    try:
        corpus_stats = build_bmulti1_shard(
            args.bmulti1_manifest, tk, os.path.join(tmpdir, "b-multi-1-00000.bin"))

        # suite (a): reconstructed from the REAL shards-v0 (sha-verified inside)
        suite_a_rows, suite_a_sha, heldout = scan.load_suite_a_rows(
            args.heldout_receipt, args.shard_dir)
        seq = heldout["seq"]
        block_len = seq + 1 + heldout["n_mtp"]
        suite_a_source_ranges = [(int(i) * seq, int(i) * seq + block_len)
                                 for i in heldout["selected_window_indices"]]

        # suite (b): tokenized with the same tokenizer
        freeze_receipt = json.load(open(args.freeze_receipt, encoding="utf-8"))
        suite_b_rows, suite_b_summary, suite_b_row_datasets = scan.load_suite_b_rows(
            args.eval_suite_dir, freeze_receipt, tk)

        eval_rows = list(suite_a_rows) + list(suite_b_rows)
        n_suite_a = len(suite_a_rows)
        row_to_dataset = [None] * n_suite_a + list(suite_b_row_datasets)

        t_scan = time.perf_counter()
        result = bdbm.contamination_recheck_mp(eval_rows, tmpdir, n_workers=1)
        wall_s = time.perf_counter() - t_scan

        files = bdbm.cheap_shard_sizes(tmpdir)
        cum = bdbm._cumulative_token_offsets(files)
        classified = scan.classify_matches(
            result.get("confirmed_matches", []), eval_rows, n_suite_a,
            suite_a_source_ranges, row_to_dataset, files, cum,
            bdbm.CONTAMINATION_WINDOW_TOKENS)
    finally:
        try:
            for fn in os.listdir(tmpdir):
                os.unlink(os.path.join(tmpdir, fn))
            os.rmdir(tmpdir)
        except OSError:
            pass

    receipt = {
        "ticket": "A1-BMULTI1-SCAN",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-bmulti1-scan/v1",
        "invariant_sha256": scan.INVARIANT_SHA256,
        "sha_convention": scan.SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#440"],
        "purpose": "scan the previously-DISCLOSED-but-unscanned owned corpus "
                   "manifests/corpus/b-multi-1 (image-caption multimodal) against frozen "
                   "suites (a)+(b), closing the corpus universe (refs #123 finding 3)",
        "corpus": {
            "artifact": "manifests/corpus/b-multi-1",
            "manifest": args.bmulti1_manifest.replace(os.sep, "/"),
            "consumed_by_completed_training_run": False,
            "consumed_note": "no completed training run has consumed b-multi-1 (acquire/smoke/"
                             "scope receipts only, none carry training fields); scanned "
                             "defensively to close the universe, not because it is in a lineage",
            **corpus_stats,
        },
        "tokenizer": {
            "path": args.tokenizer_label,
            "sha256": tok_sha,
            "custody": "recovered shard-generation tokenizer (sha 2c557e7); bytes not committed; "
                       "same encoding as the #631 corrected main scan so results compose",
            "n_orphan_merges_dropped_in_memory": dropped,
        },
        "matcher": {"method": result.get("method"), "n_workers": result.get("n_workers"),
                    "reused_from": "src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py:contamination_recheck_mp"},
        "memory_preflight": {"commit_total_gb": round(commit_total_gb, 1),
                             "commit_free_gb": round(commit_free_gb, 1),
                             "min_required_gb": bdbm.MIN_COMMIT_FREE_GB},
        "n_eval_rows": len(eval_rows),
        "n_suite_a_rows": n_suite_a,
        "windows_hashed": result.get("windows_hashed"),
        "contamination_recheck": {
            "suite_a_nonself": classified["suite_a_nonself"],
            "suite_b_matches": classified["suite_b_matches"],
            "suite_b_per_dataset_matches": classified["suite_b_per_dataset_matches"],
            "self_matches_excluded": classified["self_matches_excluded"],
            "raw_confirmed_matches": len(result.get("confirmed_matches", [])),
            "verdict": ("CLEAN: b-multi-1 shares no 13-token window with any eval item"
                        if classified["suite_a_nonself"] == 0 and classified["suite_b_matches"] == 0
                        else "MATCHES FOUND -- see per-dataset"),
        },
        "wall_s": round(wall_s, 3),
        "total_wall_s": round(time.perf_counter() - t0, 3),
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)
    print(f"A1_BMULTI1_SCAN: captions={corpus_stats['n_captions']} "
          f"windows={corpus_stats['n_13gram_windows']} suite_a_nonself={classified['suite_a_nonself']} "
          f"suite_b_matches={classified['suite_b_matches']} "
          f"verdict={receipt['contamination_recheck']['verdict'][:40]} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
