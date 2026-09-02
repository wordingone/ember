# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""verify_timing.py — receipted verification-vs-generation timing (an agent S2-A).

The fp-2 audit (§8.10) claimed sandbox verification is ~100x cheaper than
generation WITHOUT a timing receipt — an agent checkpoint 14444 flagged it. This
script produces the receipt: it rebuilds the EXACT production harnesses
(w1_mbpp line-184 semantics: imports + src + asserts + SOLVE_STUB) from a
receipted samples.jsonl, times t1_probe.execute_batch over them (pooled =
as-production, plus a serial subsample for a per-sample number without pool
parallelism), and compares against the SAME run's receipted gen_secs.

Internal check: re-executed verified counts are cross-tallied against the
samples file's recorded verified flags; the agreement rate rides the
receipt (timeouts/nondeterminism can move single samples — a low agreement
rate invalidates the timing receipt's denominator, fail-closed assert at
0.95). Receipt: receipts/verify-timing-<ts>.json. WSL/daemon only
(execute_batch fork-pool); AST-checked on Windows, exercised at dispatch.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

NC = "<local-path>"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import execute_batch  # noqa: E402
from w1_mbpp import SOLVE_STUB, load_split  # noqa: E402
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

RECEIPTS = f"{NC}/receipts"


def build_jobs(samples_path, split):
    """Rebuild production harnesses; returns (jobs, recorded_flags, skipped)."""
    probs = {p["id"]: p for p in load_split(split)}
    jobs, flags, skipped = [], [], 0
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            pid = int(str(r["task"]).split(":")[1])
            src = r.get("src")
            if src is None or pid not in probs:
                skipped += 1
                continue
            p = probs[pid]
            harness = "\n".join(p["imports"]) + "\n" + src + "\n" + \
                "\n".join(p["tests"]) + SOLVE_STUB
            jobs.append((harness, [], []))
            flags.append(1 if r.get("verified") else 0)
    return jobs, flags, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=f"{RECEIPTS}/"
                    "w1-floor-g1-base-20260610T215814Z-samples.jsonl")
    ap.add_argument("--gen-receipt", default=f"{RECEIPTS}/"
                    "w1-floor-g1-base-20260610T215814Z.json")
    ap.add_argument("--split", default="validation")
    ap.add_argument("--serial-n", type=int, default=64)
    args, _unknown = ap.parse_known_args()

    jobs, flags, skipped = build_jobs(args.samples, args.split)
    print(f"[vt] {len(jobs)} harnesses rebuilt ({skipped} skipped)",
          flush=True)

    t0 = time.time()
    res_pool = execute_batch(jobs)
    pool_secs = time.time() - t0
    t0 = time.time()
    res_serial = execute_batch(jobs[:args.serial_n], workers=1)
    serial_secs = time.time() - t0

    re_flags = [1 if r.get("verified") else 0 for r in res_pool]
    agree = sum(1 for a, b in zip(flags, re_flags) if a == b) / len(jobs)
    assert agree >= 0.95, f"verify agreement {agree:.3f} < 0.95 — invalid"

    with open(args.gen_receipt, encoding="utf-8") as f:
        gen = json.load(f)
    n_gen = gen["n_tasks"] * gen["k"]
    gen_secs = gen["gen_secs"]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "VERIFY-TIMING", "ts": ts,
        "flag_origin": "an agent checkpoint 14444 S2-A on "
                       "docs/domains/governance/research/first-principles-audit-2026-06-10.md:279",
        "samples_file": args.samples.split("/")[-1],
        "gen_receipt": args.gen_receipt.split("/")[-1],
        "n_jobs": len(jobs), "skipped": skipped,
        "verify_agreement": round(agree, 4),
        "pool": {"secs": round(pool_secs, 2),
                 "per_sample_ms": round(1000 * pool_secs / len(jobs), 2)},
        "serial": {"n": len(res_serial), "secs": round(serial_secs, 2),
                   "per_sample_ms": round(
                       1000 * serial_secs / len(res_serial), 2)},
        "generation": {"secs": gen_secs, "n_samples": n_gen,
                       "per_sample_ms": round(1000 * gen_secs / n_gen, 2)},
        "ratio_gen_over_verify_pool": round(
            (gen_secs / n_gen) / (pool_secs / len(jobs)), 1),
        "ratio_gen_over_verify_serial": round(
            (gen_secs / n_gen) / (serial_secs / len(res_serial)), 1),
    }
    out = f"{RECEIPTS}/verify-timing-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"VERIFY_TIMING_DONE {out}", flush=True)


if __name__ == "__main__":
    main()
