# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""w2_ingest.py — W-code ledger ingest: w1 sample rows -> ledger episodes.

Wires docs/domains/governance/research/teacher-system-2026-06-10.md S1 + the W-code world into the
existing round machinery. Reads w1-floor *-samples.jsonl rows
({"task": "mbpp:<id>", "verified", "error", "src", "prompt", "sampler"}),
converts them to t2_round ledger records (same key scheme `task:sha(src)`,
same append_jsonl dedup), and appends:
  verified rows           -> receipts/ledger/episodes.jsonl
  failed rows WITH src    -> receipts/ledger/control_pool.jsonl  (G2 control material)
  rows without src        -> skipped (extraction failures carry no program)

Records carry "prompt" inline so build_dataset renders the EXACT user text the
sampler saw (mbpp:* keys are not in ARC_TRAIN — without an inline prompt they
would be silently skipped), and "sampler" for per-teacher G3 leave-set-out.

Receipt: receipts/w2-ingest-<ts>.json. Pure conversion logic is import-light
(stdlib + the stdlib-only ledger_license/fp6_provenance siblings) so it
unit-tests anywhere; t2_round (-> t1_probe -> torch) is imported inside
main() only.
"""

import argparse
import glob as globlib
import hashlib
import json
import os
from datetime import datetime, timezone

from ledger_license import census as license_census, stamp  # eng #70
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
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

NC = "<local-path>"
RECEIPTS = f"{NC}/receipts"


def sha(s):
    # Identical to t2_round.sha (sha1 hex, 16 chars) — duplicated only to keep
    # this module importable without the t1_probe/torch chain for unit tests.
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def samples_to_records(rows, round_n, ts="", receipt=""):
    """w1 sample rows -> (verified_records, failed_records). Pure.

    Emits ledger schema v3 (docs/domains/governance/charter/ledger-schema-v3.md): explicit verified/ts/
    origin/receipt on every record — origin absorbs the w1 sampler identity
    (one provenance field; sampler kept as passthrough for leave-set-out
    tooling). "solved" mirrors "verified" for W-code: the MBPP harness'
    asserts ARE the task's full test, there is no separate held-back pair.
    """
    verified, failed = [], []
    for row in rows:
        src = row.get("src")
        if not src:
            continue
        rec = {"key": f"{row['task']}:{sha(src)}",
               "task": row["task"], "src": src,
               "verified": bool(row.get("verified")),
               "ts": ts, "receipt": receipt,
               "origin": row.get("sampler") or "w1-floor",
               "round": round_n, "solved": bool(row.get("verified"))}
        for field in ("prompt", "sampler"):
            if row.get(field):
                rec[field] = row[field]
        stamp(rec)  # eng #70: license_class/license_basis at ingest
        (verified if row.get("verified") else failed).append(rec)
    return verified, failed


def load_rows(patterns):
    rows, files = [], []
    for pat in patterns:
        for path in sorted(globlib.glob(pat)):
            files.append(os.path.basename(path))
            with open(path) as f:
                rows.extend(json.loads(line) for line in f if line.strip())
    return rows, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="+", required=True,
                    help="w1 *-samples.jsonl path(s) or glob(s)")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="report counts; write nothing")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    rows, files = load_rows(args.samples)
    if not rows:
        raise SystemExit(f"w2_ingest: no rows matched {args.samples}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    verified, failed = samples_to_records(
        rows, args.round, ts=ts, receipt=f"w2-ingest-{ts}.json")

    # Frontier annotation (eng #5): per-task solve-rate posterior pooled
    # over ALL loaded sample rows -> phat/bits/stratum on every record.
    # The ledger keeps every verified episode; the easy-mass discount is
    # applied at DATASET build via frontier.caps_from_records.
    from frontier import annotate_records, outcome_stats, report_block
    stats = outcome_stats(rows)
    annotate_records(verified, stats)
    annotate_records(failed, stats)

    receipt = {"ticket": "W2-INGEST",
               "ts": ts,
               "args": vars(args), "files": files, "rows_read": len(rows),
               "verified_records": len(verified),
               "control_records": len(failed),
               "samplers": sorted({r.get("sampler", "?") for r in
                                   verified + failed}),
               "by_license": license_census(verified + failed),  # eng #70
               "frontier": report_block(verified),
               "dry_run": args.dry_run}
    if not args.dry_run:
        from t2_round import CONTROL_POOL, LEDGER, append_jsonl
        receipt["episodes_added"] = append_jsonl(LEDGER, verified)
        receipt["control_added"] = append_jsonl(CONTROL_POOL, failed)
        # eng #97: dedup-cluster sidecar stamps — sidecar-only writes;
        # LEDGER and CONTROL_POOL bytes above are completely untouched.
        # issue2015 exact-local-import:src/ember/governance/scripts/ledger_dedup.py
        import importlib.util as _ember_341a7292e44a83b4_importlib
        import sys as _ember_341a7292e44a83b4_sys
        from pathlib import Path as _ember_341a7292e44a83b4_Path
        _ember_341a7292e44a83b4_path = _ember_341a7292e44a83b4_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ledger_dedup.py')
        if not _ember_341a7292e44a83b4_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ledger_dedup.py')
        _ember_341a7292e44a83b4_aliases = ('_ember_issue2015_341a7292e44a83b4', 'ledger_dedup', 'scripts.ledger_dedup')
        _ember_341a7292e44a83b4_existing = []
        for _ember_341a7292e44a83b4_alias in _ember_341a7292e44a83b4_aliases:
            _ember_341a7292e44a83b4_candidate = _ember_341a7292e44a83b4_sys.modules.get(_ember_341a7292e44a83b4_alias)
            if _ember_341a7292e44a83b4_candidate is not None and all(_ember_341a7292e44a83b4_candidate is not item for item in _ember_341a7292e44a83b4_existing):
                _ember_341a7292e44a83b4_existing.append(_ember_341a7292e44a83b4_candidate)
        if len(_ember_341a7292e44a83b4_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ledger_dedup.py')
        if _ember_341a7292e44a83b4_existing:
            _ember_341a7292e44a83b4_module = _ember_341a7292e44a83b4_existing[0]
            _ember_341a7292e44a83b4_observed = getattr(_ember_341a7292e44a83b4_module, '__file__', None)
            if _ember_341a7292e44a83b4_observed is None or _ember_341a7292e44a83b4_Path(_ember_341a7292e44a83b4_observed).resolve() != _ember_341a7292e44a83b4_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ledger_dedup.py')
        else:
            _ember_341a7292e44a83b4_spec = _ember_341a7292e44a83b4_importlib.spec_from_file_location('_ember_issue2015_341a7292e44a83b4', _ember_341a7292e44a83b4_path)
            if _ember_341a7292e44a83b4_spec is None or _ember_341a7292e44a83b4_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ledger_dedup.py')
            _ember_341a7292e44a83b4_module = _ember_341a7292e44a83b4_importlib.module_from_spec(_ember_341a7292e44a83b4_spec)
            for _ember_341a7292e44a83b4_alias in _ember_341a7292e44a83b4_aliases:
                _ember_341a7292e44a83b4_prior = _ember_341a7292e44a83b4_sys.modules.get(_ember_341a7292e44a83b4_alias)
                if _ember_341a7292e44a83b4_prior is not None and _ember_341a7292e44a83b4_prior is not _ember_341a7292e44a83b4_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ledger_dedup.py')
                _ember_341a7292e44a83b4_sys.modules[_ember_341a7292e44a83b4_alias] = _ember_341a7292e44a83b4_module
            try:
                _ember_341a7292e44a83b4_spec.loader.exec_module(_ember_341a7292e44a83b4_module)
            except BaseException:
                for _ember_341a7292e44a83b4_alias in _ember_341a7292e44a83b4_aliases:
                    if _ember_341a7292e44a83b4_sys.modules.get(_ember_341a7292e44a83b4_alias) is _ember_341a7292e44a83b4_module:
                        _ember_341a7292e44a83b4_sys.modules.pop(_ember_341a7292e44a83b4_alias, None)
                raise
        for _ember_341a7292e44a83b4_alias in _ember_341a7292e44a83b4_aliases:
            _ember_341a7292e44a83b4_prior = _ember_341a7292e44a83b4_sys.modules.get(_ember_341a7292e44a83b4_alias)
            if _ember_341a7292e44a83b4_prior is not None and _ember_341a7292e44a83b4_prior is not _ember_341a7292e44a83b4_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ledger_dedup.py')
            _ember_341a7292e44a83b4_sys.modules[_ember_341a7292e44a83b4_alias] = _ember_341a7292e44a83b4_module
        stamp_dedup_sidecar = getattr(_ember_341a7292e44a83b4_module, 'stamp_dedup_sidecar')
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ledger_dedup.py
        NC_VIEWS = f"{NC}/receipts/ledger/views"
        stamp_dedup_sidecar(LEDGER, f"{NC_VIEWS}/dedup-cluster.jsonl", verified)
        stamp_dedup_sidecar(CONTROL_POOL,
                            f"{NC_VIEWS}/dedup-cluster-control.jsonl", failed)

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/w2-ingest-{receipt['ts']}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print("W2_INGEST_DONE")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, f"{NC}/scripts")
    main()
