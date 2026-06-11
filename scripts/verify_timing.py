"""verify_timing.py — receipted verification-vs-generation timing (Kai S2-A).

The fp-2 audit (§8.10) claimed sandbox verification is ~100x cheaper than
generation WITHOUT a timing receipt — Kai checkpoint 14444 flagged it. This
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

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import execute_batch  # noqa: E402
from w1_mbpp import SOLVE_STUB, load_split  # noqa: E402
from receipt_write import checked_write  # noqa: E402

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
        "flag_origin": "kai checkpoint 14444 S2-A on "
                       "research/first-principles-audit-2026-06-10.md:279",
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
