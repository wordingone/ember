# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""r2_power.py — round-2 G1 power pre-registration runs (#29).

Loads the EMPIRICAL per-task base rates from the G1 base leg samples
(validation 43 x k=8, receipt w1-floor-g1-base-*) and executes the power.py
paired-design extensions on them: MDE-vs-k table + Monte-Carlo power grid
(sample-level normal-proxy test and task-level any-of-k McNemar), so every
number in docs/research/math/r2-power-prereg.md comes from an executed run.

Receipt: receipts/r2-power-prereg-<ts>.json. Pure stdlib.
"""
import glob as globlib
import json
import os
from datetime import datetime, timezone

from g1_paired import load_samples
from power import mde_paired_rates, power_mc_feed, power_mc_paired
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
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

NC = "<local-path>"
RECEIPTS = f"{NC}/receipts"
KS = (8, 16, 24, 32)
DELTAS = (0.03, 0.05, 0.08)
SIMS = 2000


def main():
    hits = sorted(globlib.glob(f"{RECEIPTS}/w1-floor-g1-base-*-samples.jsonl"))
    if not hits:
        raise SystemExit("r2_power: no g1-base samples receipt")
    tab = load_samples(hits[-1])
    rates = [sum(xs) / len(xs) for xs in tab.values()]

    mde = {k: round(mde_paired_rates(rates, k), 4) for k in KS}
    grid_sample = {f"k={k}": {f"+{int(d*100)}pp": round(
        power_mc_paired(rates, d, k, sims=SIMS), 3)
        for d in DELTAS} for k in KS}
    grid_feed = {f"k={k}": {f"+{int(d*100)}pp": round(
        power_mc_feed(rates, d, k, sims=SIMS), 3)
        for d in DELTAS} for k in KS}
    null_rej = {f"k={k}": round(power_mc_paired(rates, 0.0, k, sims=SIMS), 3)
                for k in KS}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "R2-POWER-PREREG", "ts": ts,
        "rates_source": os.path.basename(hits[-1]),
        "n_tasks": len(rates),
        "base_mean_rate": round(sum(rates) / len(rates), 4),
        "assumption": "homogeneous per-sample shift; binomial sampling "
                      "noise only (heterogeneous true effects widen SE — "
                      "MDEs are optimistic lower bounds)",
        "mde_sample_level_by_k": mde,
        "power_sample_level": grid_sample,
        "power_task_feed": grid_feed,
        "null_rejection_rate": null_rej,
        "sims_per_cell": SIMS, "seed": 16,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/r2-power-prereg-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"R2_POWER_DONE {out}")


if __name__ == "__main__":
    main()
