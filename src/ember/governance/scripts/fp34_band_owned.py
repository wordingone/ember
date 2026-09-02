# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp34_band_owned.py — owned-core band freeze + prong-A verdict (#264, fp-34).

Prereg: docs/domains/governance/archive/pre-restart/fp34-owned-band-prereg-v1.md (FROZEN before round-1 receipts
exist). Predicate: band_owned(t) = s_r1>0 AND laplace_phat(s_r1,n_r1) <= 0.5.
Bars: ratio 1.5 / perm p<0.05 / 10k shuffles / seed 19. Estimator machinery
imported from fp15_bandtransfer — shared code, never reimplemented.

Verbs:
  python fp34_band_owned.py freeze --r1 <round1-stats.json>
      round-1 per-task stats {task: {"s": int, "n": int}} -> band manifest
      receipt (sha-pinned inputs). Refuses to overwrite an existing manifest
      (the freeze rule) unless --force-deviation NAME is given.
  python fp34_band_owned.py verdict --sampling <round2-receipt.json> \
      --manifest <fp34-band-manifest-*.json>
      round-2 rows {task, k_sampled, new_verified} + frozen band -> prong-A
      receipt (PREDICTIVE / REFUTED-direction / INCONCLUSIVE).
  python fp34_band_owned.py --selftest
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vbits import laplace_phat  # noqa: E402
import fp15_bandtransfer as f15  # noqa: E402 — shared estimator machinery
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

NC_WIN = "<local-path>"
RECEIPTS = f"{NC_WIN}/receipts"
PHAT_BAR = 0.5
RATIO_BAR = 1.5
PERM_N = 10_000
SEED = 19  # fresh by prereg declaration (16/17/18 taken)


def band_owned(s, n):
    """Verified-but-hard: episodes exist AND posterior solve-rate <= 0.5."""
    return s > 0 and laplace_phat(s, n) <= PHAT_BAR


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze(r1_path, force_deviation=None):
    existing = glob.glob(f"{RECEIPTS}/fp34-band-manifest-*.json")
    if existing and not force_deviation:
        print(f"FP34_FREEZE REFUSED: manifest exists ({existing[0]}); "
              "the band is computed once. Re-freeze requires "
              "--force-deviation <registered-deviation-name>.")
        return 1
    stats = json.load(open(r1_path, encoding="utf-8"))
    members = sorted(t for t, c in stats.items() if band_owned(c["s"], c["n"]))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP34-BAND-MANIFEST", "ts": ts,
        "predicate": f"s>0 AND laplace_phat(s,n) <= {PHAT_BAR}",
        "r1_input": {"path": r1_path, "sha256": sha256(r1_path)},
        "n_tasks": len(stats), "n_band": len(members),
        "band": members,
        "deviation": force_deviation,
    }
    out = f"{RECEIPTS}/fp34-band-manifest-{ts}.json"
    checked_write(out, receipt)
    print(f"FP34_FREEZE_DONE {out} ({len(members)}/{len(stats)} in band)")
    return 0


def verdict(sampling_path, manifest_path):
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    band = set(manifest["band"])
    rows = json.load(open(sampling_path, encoding="utf-8"))["tasks"]
    tasks = [{"task": r["task"], "band": r["task"] in band,
              "k_sampled": r["k_sampled"], "new_verified": r["new_verified"]}
             for r in rows]
    p, obs = f15.perm_pvalue(tasks, seed=SEED, n=PERM_N)
    v = f15.verdict(obs, p)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP34-BANDTRANSFER", "ts": ts, "prong": "A",
        "bars": {"ratio": RATIO_BAR, "p": 0.05, "perm_n": PERM_N,
                 "seed": SEED},
        "inputs": {"sampling": {"path": sampling_path,
                                "sha256": sha256(sampling_path)},
                   "manifest": {"path": manifest_path,
                                "sha256": sha256(manifest_path)}},
        "split": obs, "perm_p_one_sided": p, **v,
        "prong_b_trigger": "fires ONLY on PREDICTIVE (prereg)",
    }
    out = f"{RECEIPTS}/fp34-bandtransfer-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(v))
    print(f"FP34_VERDICT_DONE {out}")
    return 0


def _selftest():
    # predicate boundary cases
    assert band_owned(1, 8)                  # rare verified -> in band
    assert not band_owned(0, 8)              # no verified episodes
    assert not band_owned(8, 8)              # saturated
    assert band_owned(3, 8)                  # phat (4/10) <= 0.5
    assert not band_owned(5, 8)              # phat (6/10) > 0.5
    # boundary exactness: laplace_phat(4,8) = 5/10 = 0.5 -> in band (<=)
    assert laplace_phat(4, 8) == 0.5 and band_owned(4, 8)
    # shared machinery: seed-19 determinism + a separating fixture
    fix = ([{"task": f"b{i}", "band": True, "k_sampled": 8, "new_verified": 4}
            for i in range(12)] +
           [{"task": f"n{i}", "band": False, "k_sampled": 8, "new_verified": 1}
            for i in range(12)])
    p1, o1 = f15.perm_pvalue(fix, seed=SEED, n=2000)
    p2, _ = f15.perm_pvalue(fix, seed=SEED, n=2000)
    assert p1 == p2, "seed-19 determinism"
    ratio = o1["band"]["yield"] / o1["nonband"]["yield"]
    assert ratio == 4.0 and p1 < 0.05, (ratio, p1)
    assert f15.verdict(o1, p1)["verdict"] == "PREDICTIVE"
    # null fixture -> not PREDICTIVE
    null = [{**t, "new_verified": 2} for t in fix]
    pn, on = f15.perm_pvalue(null, seed=SEED, n=2000)
    assert f15.verdict(on, pn)["verdict"] == "INCONCLUSIVE"
    print("FP34_BAND_OWNED_SELFTEST_PASS")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return 0
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--r1", required=True)
    f.add_argument("--force-deviation")
    v = sub.add_parser("verdict")
    v.add_argument("--sampling", required=True)
    v.add_argument("--manifest", required=True)
    args = ap.parse_args()
    if args.verb == "freeze":
        return freeze(args.r1, args.force_deviation)
    return verdict(args.sampling, args.manifest)


if __name__ == "__main__":
    sys.exit(main())
