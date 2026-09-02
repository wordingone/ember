# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""bits_account.py — three-estimator banked-bits receipt (#30).

Compares, on the current mbpp ledger view (post-cap kept set throughout):
  1. naive      — report_block on all verified records (252.2-class number)
  2. ext-clean  — report_block after dropping measured-wrong keys (eng #21)
  3. corrected  — fpr_corrected_bits: exact where measured (flagged -> 0,
                  covered-clean -> full), FPR-discounted on episodes MBPP+
                  cannot measure (uncovered tasks), stratum Wilson CI
                  propagated -> (lo, point, hi) band.

Inputs are receipts: v-ext flags jsonl (wrong-only) + the v-extended
receipt's uncovered task list and per-stratum (wrong, n) counts. Strata
absent from the FPR receipt fall back to the OVERALL rate (stated on the
receipt). Pure stdlib (+ frontier, power). Receipt: receipts/bits-account-<ts>.json.
"""
import glob as globlib
import json
import os
from datetime import datetime, timezone

from receipt_write import checked_write

# issue2015 exact-local-import:src/ember/governance/scripts/frontier.py
import importlib.util as _ember_d8c02810056e6c3d_importlib
import sys as _ember_d8c02810056e6c3d_sys
from pathlib import Path as _ember_d8c02810056e6c3d_Path
_ember_d8c02810056e6c3d_path = _ember_d8c02810056e6c3d_Path(__file__).resolve().parent.joinpath('frontier.py')
if not _ember_d8c02810056e6c3d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/frontier.py')
_ember_d8c02810056e6c3d_aliases = ('_ember_issue2015_d8c02810056e6c3d', 'frontier', 'src.ember.governance.scripts.frontier')
_ember_d8c02810056e6c3d_existing = []
for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
    _ember_d8c02810056e6c3d_candidate = _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias)
    if _ember_d8c02810056e6c3d_candidate is not None and all(_ember_d8c02810056e6c3d_candidate is not item for item in _ember_d8c02810056e6c3d_existing):
        _ember_d8c02810056e6c3d_existing.append(_ember_d8c02810056e6c3d_candidate)
if len(_ember_d8c02810056e6c3d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/frontier.py')
if _ember_d8c02810056e6c3d_existing:
    _ember_d8c02810056e6c3d_module = _ember_d8c02810056e6c3d_existing[0]
    _ember_d8c02810056e6c3d_observed = getattr(_ember_d8c02810056e6c3d_module, '__file__', None)
    if _ember_d8c02810056e6c3d_observed is None or _ember_d8c02810056e6c3d_Path(_ember_d8c02810056e6c3d_observed).resolve() != _ember_d8c02810056e6c3d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/frontier.py')
else:
    _ember_d8c02810056e6c3d_spec = _ember_d8c02810056e6c3d_importlib.spec_from_file_location('_ember_issue2015_d8c02810056e6c3d', _ember_d8c02810056e6c3d_path)
    if _ember_d8c02810056e6c3d_spec is None or _ember_d8c02810056e6c3d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/frontier.py')
    _ember_d8c02810056e6c3d_module = _ember_d8c02810056e6c3d_importlib.module_from_spec(_ember_d8c02810056e6c3d_spec)
    for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
        _ember_d8c02810056e6c3d_prior = _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias)
        if _ember_d8c02810056e6c3d_prior is not None and _ember_d8c02810056e6c3d_prior is not _ember_d8c02810056e6c3d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/frontier.py')
        _ember_d8c02810056e6c3d_sys.modules[_ember_d8c02810056e6c3d_alias] = _ember_d8c02810056e6c3d_module
    try:
        _ember_d8c02810056e6c3d_spec.loader.exec_module(_ember_d8c02810056e6c3d_module)
    except BaseException:
        for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
            if _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias) is _ember_d8c02810056e6c3d_module:
                _ember_d8c02810056e6c3d_sys.modules.pop(_ember_d8c02810056e6c3d_alias, None)
        raise
for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
    _ember_d8c02810056e6c3d_prior = _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias)
    if _ember_d8c02810056e6c3d_prior is not None and _ember_d8c02810056e6c3d_prior is not _ember_d8c02810056e6c3d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/frontier.py')
    _ember_d8c02810056e6c3d_sys.modules[_ember_d8c02810056e6c3d_alias] = _ember_d8c02810056e6c3d_module
ext_clean = getattr(_ember_d8c02810056e6c3d_module, 'ext_clean')
fpr_corrected_bits = getattr(_ember_d8c02810056e6c3d_module, 'fpr_corrected_bits')
load_ext_flags = getattr(_ember_d8c02810056e6c3d_module, 'load_ext_flags')
report_block = getattr(_ember_d8c02810056e6c3d_module, 'report_block')
# issue2015 exact-local-import-end:src/ember/governance/scripts/frontier.py
# issue2015 exact-local-import:src/ember/governance/scripts/power.py
import importlib.util as _ember_41d654a4576ceb0a_importlib
import sys as _ember_41d654a4576ceb0a_sys
from pathlib import Path as _ember_41d654a4576ceb0a_Path
_ember_41d654a4576ceb0a_path = _ember_41d654a4576ceb0a_Path(__file__).resolve().parent.joinpath('power.py')
if not _ember_41d654a4576ceb0a_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/power.py')
_ember_41d654a4576ceb0a_aliases = ('_ember_issue2015_41d654a4576ceb0a', 'power', 'src.ember.governance.scripts.power')
_ember_41d654a4576ceb0a_existing = []
for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
    _ember_41d654a4576ceb0a_candidate = _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias)
    if _ember_41d654a4576ceb0a_candidate is not None and all(_ember_41d654a4576ceb0a_candidate is not item for item in _ember_41d654a4576ceb0a_existing):
        _ember_41d654a4576ceb0a_existing.append(_ember_41d654a4576ceb0a_candidate)
if len(_ember_41d654a4576ceb0a_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/power.py')
if _ember_41d654a4576ceb0a_existing:
    _ember_41d654a4576ceb0a_module = _ember_41d654a4576ceb0a_existing[0]
    _ember_41d654a4576ceb0a_observed = getattr(_ember_41d654a4576ceb0a_module, '__file__', None)
    if _ember_41d654a4576ceb0a_observed is None or _ember_41d654a4576ceb0a_Path(_ember_41d654a4576ceb0a_observed).resolve() != _ember_41d654a4576ceb0a_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/power.py')
else:
    _ember_41d654a4576ceb0a_spec = _ember_41d654a4576ceb0a_importlib.spec_from_file_location('_ember_issue2015_41d654a4576ceb0a', _ember_41d654a4576ceb0a_path)
    if _ember_41d654a4576ceb0a_spec is None or _ember_41d654a4576ceb0a_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/power.py')
    _ember_41d654a4576ceb0a_module = _ember_41d654a4576ceb0a_importlib.module_from_spec(_ember_41d654a4576ceb0a_spec)
    for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
        _ember_41d654a4576ceb0a_prior = _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias)
        if _ember_41d654a4576ceb0a_prior is not None and _ember_41d654a4576ceb0a_prior is not _ember_41d654a4576ceb0a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/power.py')
        _ember_41d654a4576ceb0a_sys.modules[_ember_41d654a4576ceb0a_alias] = _ember_41d654a4576ceb0a_module
    try:
        _ember_41d654a4576ceb0a_spec.loader.exec_module(_ember_41d654a4576ceb0a_module)
    except BaseException:
        for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
            if _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias) is _ember_41d654a4576ceb0a_module:
                _ember_41d654a4576ceb0a_sys.modules.pop(_ember_41d654a4576ceb0a_alias, None)
        raise
for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
    _ember_41d654a4576ceb0a_prior = _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias)
    if _ember_41d654a4576ceb0a_prior is not None and _ember_41d654a4576ceb0a_prior is not _ember_41d654a4576ceb0a_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/power.py')
    _ember_41d654a4576ceb0a_sys.modules[_ember_41d654a4576ceb0a_alias] = _ember_41d654a4576ceb0a_module
wilson = getattr(_ember_41d654a4576ceb0a_module, 'wilson')
# issue2015 exact-local-import-end:src/ember/governance/scripts/power.py

NC = "<local-path>"
RECEIPTS = f"{NC}/receipts"


def main():
    recs = []
    with open(f"{NC}/receipts/ledger/episodes.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["task"].startswith("mbpp:"):
                recs.append(r)

    flags = load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"])
    vext_path = sorted(globlib.glob(f"{RECEIPTS}/v-extended-*.json"))[-1]
    vext = json.load(open(vext_path, encoding="utf-8"))
    uncovered = {f"mbpp:{t}" for t in vext["uncovered_tasks"]}

    overall = vext["fpr"]["overall"]
    fpr_ci, fallback = {}, []
    strata = {r["stratum"] for r in recs}
    for st in strata:
        blk = vext["fpr"].get(st)
        if blk is None or not blk["n"]:
            blk, note = overall, st
            fallback.append(st)
        lo, hi = wilson(blk["ext_wrong"], blk["n"])
        fpr_ci[st] = (round(lo, 4), round(blk["ext_wrong"] / blk["n"], 4),
                      round(hi, 4))

    naive = report_block(recs)
    clean = report_block(ext_clean(recs, flags))
    corrected = fpr_corrected_bits(recs, flags, uncovered, fpr_ci)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "BITS-ACCOUNT", "ts": ts,
        "ledger_mbpp_records": len(recs),
        "flags_wrong_only": len(flags),
        "fpr_source": os.path.basename(vext_path),
        "uncovered_tasks": sorted(uncovered),
        "fpr_ci_by_stratum": fpr_ci,
        "fpr_fallback_to_overall": fallback,
        "estimators": {
            "naive_total": naive["total_bits_banked"],
            "ext_clean_total": clean["total_bits_banked"],
            "fpr_corrected": corrected,
        },
        "reading": "corrected.point is the working B numerator; the "
                   "[lo,hi] band carries MBPP+ non-coverage uncertainty "
                   "only (covered episodes are measured, not estimated)",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/bits-account-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"BITS_ACCOUNT_DONE {out}")


if __name__ == "__main__":
    main()
