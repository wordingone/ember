#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_freeze_declaration.py -- ember issue #593 deliverable 1: the A1
eval-freeze DECLARATION receipt.

Extends the freeze doc's receipt schema (docs/spec/eval-suite-freeze-v1.md
"Freeze Receipt Schema") with the falsifier-fill A1 fields (refs #123 sec.1):
  - eval_freeze_hash: the commit sha pinning suites (a)+(b). Self-reference
    is impossible (a commit cannot contain its own sha), so the declaration
    carries the RESOLUTION RULE and the sha is recorded in the companion
    pointer file receipts/eval-suite-freeze/EVAL-FREEZE-HASH by the PR's
    final commit; consumers MUST verify that commit contains this receipt
    byte-identical.
  - freeze_ts: UTC at declaration. Every governed launch_ts must exceed it.
  - suite (a): the W2 sec.4 decontaminated held-out batch, pinned by sha.
  - suite (b): eval-suite-v1's SEVEN pinned datasets (GPQA-diamond EXCLUDED
    per docs/ledgers/deviations.md DEV-004, battery-14 section).

Usage:
  python scripts/a1_freeze_declaration.py \\
      --heldout-receipt receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --quarantine-receipt receipts/eval-suite-freeze/a1-prefreeze-quarantine-<ts>.json \\
      --scan-receipt receipts/a1-predicate-scan/a1-predicate-scan-<ts>.json \\
      --out receipts/eval-suite-freeze/a1-freeze-declaration-<UTCts>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

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

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--heldout-receipt", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--quarantine-receipt", required=True)
    ap.add_argument("--scan-receipt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    heldout = json.load(open(os.path.join(REPO, args.heldout_receipt), encoding="utf-8"))
    freeze = json.load(open(os.path.join(REPO, args.freeze_receipt), encoding="utf-8"))
    quarantine = json.load(open(os.path.join(REPO, args.quarantine_receipt), encoding="utf-8"))
    scan = json.load(open(os.path.join(REPO, args.scan_receipt), encoding="utf-8"))

    suite_b_datasets = [
        {k: ds[k] for k in ("name", "source", "canonical_url", "revision",
                             "test_split_name", "test_split_sha256", "row_count",
                             "size_bytes")}
        for ds in freeze["datasets"]
        if ds.get("test_split_sha256") and ds["test_split_sha256"] != "PIN-PENDING"
    ]
    if len(suite_b_datasets) != 7:
        raise SystemExit(
            f"A1_DECLARATION_SUITE_B_COUNT: expected exactly 7 pinned datasets, "
            f"got {len(suite_b_datasets)} -- refusing to declare")

    freeze_ts = datetime.now(timezone.utc).isoformat()

    receipt = {
        "ticket": "A1-EVAL-FREEZE-DECLARATION",
        "ts": freeze_ts,
        "schema": "a1-eval-freeze-declaration/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#593", "#123", "#591", "#440", "#582", "#585"],
        "freeze_ts": freeze_ts,
        "freeze_ts_rule": "every governed C8 arm's launch_ts MUST be strictly "
                          "greater than freeze_ts; a receipt violating this is "
                          "inadmissible (refs #123 sec.1)",
        "eval_freeze_hash": None,
        "eval_freeze_hash_rule": (
            "eval_freeze_hash = the sha of the PR head commit carrying this "
            "declaration. A commit cannot contain its own sha, so the value is "
            "null HERE and recorded in the companion pointer file "
            "receipts/eval-suite-freeze/EVAL-FREEZE-HASH (one 40-hex line) added "
            "by the PR's final commit. Consumers MUST verify: (1) the pointed "
            "commit contains this declaration file byte-identical, (2) "
            "freeze_ts here predates their launch_ts, (3) the pointer commit is "
            "an ancestor of the ref they build from."),
        "suite_a": {
            "definition": "the decontaminated held-out batch per "
                          "docs/spec/w2-scale-preregistration-v1.md sec.4",
            "batch_sha256": heldout["batch_sha256"],
            "pin_receipt": args.heldout_receipt.replace(os.sep, "/"),
            "pin_receipt_sha256": file_sha256(os.path.join(REPO, args.heldout_receipt)),
            "seq": heldout["seq"],
            "n_mtp": heldout["n_mtp"],
            "n_rows": len(heldout["selected_window_indices"]),
            "selected_window_indices": heldout["selected_window_indices"],
            "decontam_verdict": heldout["contamination_recheck"]["verdict"],
        },
        "suite_b": {
            "definition": "eval-suite-v1's seven pinned datasets "
                          "(docs/spec/eval-suite-freeze-v1.md, Status: Frozen, "
                          "effective 2026-07-08)",
            "pin_receipt": args.freeze_receipt.replace(os.sep, "/"),
            "pin_receipt_sha256": file_sha256(os.path.join(REPO, args.freeze_receipt)),
            "n_datasets": len(suite_b_datasets),
            "datasets": suite_b_datasets,
            "gpqa_diamond_exclusion": {
                "status": "EXCLUDED from v1",
                "mechanism": "docs/ledgers/deviations.md DEV-004 (battery-14 section) -- "
                             "the freeze doc's own amendment mechanism",
                "rule": "a dataset pinned later joins a future suite VERSION; it "
                        "is never appended to a frozen one",
            },
        },
        "prefreeze_quarantine": {
            "receipt": args.quarantine_receipt.replace(os.sep, "/"),
            "receipt_sha256": file_sha256(os.path.join(REPO, args.quarantine_receipt)),
            "n_quarantined": quarantine["n_quarantined"],
            "rule": "every receipt in the quarantine list is development-only "
                    "(pre_freeze: true) and may never be cited by a capability claim",
        },
        "predicate_scan": {
            "receipt": args.scan_receipt.replace(os.sep, "/"),
            "receipt_sha256": file_sha256(os.path.join(REPO, args.scan_receipt)),
            "scan_ts": scan["scan_ts"],
            "suite_a_contamination_recheck": scan["contamination_recheck"]["suite_a"],
            "suite_b_status": scan["contamination_recheck"]["suite_b"]["status"],
            "first_ever": True,
            "note": "the freeze-spec predicate (refs #440) interlock executed for "
                    "the first time; suite (b)'s counting-convention ruling is the "
                    "coordinator's (see the scan receipt's convention_stats)",
        },
        "postfreeze_heldout_selection": {
            "rule_doc": "docs/spec/a1-postfreeze-heldout-selection-v1.md",
            "rule": "index = int(eval_freeze_hash[:8], 16) mod 8 over the frozen "
                    "8-candidate public pool; resolved alongside the pointer file "
                    "once the freeze hash exists",
        },
    }

    out_abs = os.path.join(REPO, args.out)
    d = os.path.dirname(out_abs)
    if d:
        os.makedirs(d, exist_ok=True)
    receipt_write.checked_write(out_abs, receipt)
    print(f"A1_DECLARATION: freeze_ts={freeze_ts} suite_a={heldout['batch_sha256'][:16]}... "
          f"suite_b=7 datasets, quarantined={quarantine['n_quarantined']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
