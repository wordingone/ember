#!/usr/bin/env python3
"""compute_mde.py -- C8 pre-launch obligation O2 (issue #582; spec: the F1-F4 fill
amendment on issue #123, comment 4928342201, sections 0 and 9 item 2). CPU-only:
no model loads, no GPU, no torch import.

Publishes the Minimum Detectable Effect (MDE) for the C8 governed-run terminal
design (n=5 cheap-rung seeds per arm, cluster bootstrap over seed x row) BEFORE
any governed arm launches. This is a PRE-LAUNCH POWER ESTIMATE, not the frozen
terminal analysis itself -- the terminal verdict still uses the amendment's own
paired cluster-BCa-bootstrap machinery. The MDE only answers "could an effect of
this size even be detected at n=5", using variance evidence that already exists.

INPUT ENUMERATION (the "receipt-enumeration half")
---------------------------------------------------
Scans --receipts-dir (default: receipts/) for JSON files whose FILENAME contains
one of the KEYWORD_MARKERS below (case-insensitive substring match) -- these are
the "existing rung-2 dev receipts carrying per-seed eval-loss spreads (b-series
remeasure + stabilize dev receipts)" the issue names as the variance source.
Every one of these receipts is PRE-FREEZE / development-only under A1 (quarantined
for any CLAIM purpose) -- but computing power (this tool), not a claim, is exactly
what the amendment authorizes reading them for.

A matched filename is checked against the "usable variance receipt" schema this
tool defines (no such schema existed in the repo before this issue; it is fixed
here and any future dev receipt wanting to feed the MDE must conform to it):

    {
      "comparison_class": <str>,             # e.g. "f1_mechanism", "f2_criterion", "f3_deletion"
      "per_seed_eval_loss": [<float>, ...]    # >=2 finite values, nats, one per training seed
      ... (any other fields ignored)
    }

A file matching a filename marker but failing the schema (missing field, <2 seed
values, non-finite values, non-numeric values) is recorded as SKIPPED with a
reason and does NOT count toward the usable total.

If fewer than 2 usable variance receipts remain, this script prints a specific
error to stderr, writes NO mde-*.json receipt, and exits 1. The missing-variance
outcome is itself the designed, receipted result (via the exit code + stderr text
captured by the caller) -- it forces fresh variance runs before any governed
launch. Never fabricate sigma_seed from fewer than 2 sources.

MDE FORMULA
-----------
Per usable receipt: sigma_seed = sample standard deviation (ddof=1) of its
per_seed_eval_loss array. sigma_seed_per_class pools receipts sharing the same
comparison_class using the standard pooled-variance formula:

    sigma_pooled = sqrt( sum_i[(n_i - 1) * sigma_i^2] / sum_i[n_i - 1] )

The terminal design MDE at n (default 5, the amendment's fixed cheap-rung seed
count) is the standard closed-form minimum detectable effect for a one-sample /
paired mean test (the F1/F2 terminal grammar tests the mean of n per-seed paired
deltas against 0), Student-t based, two-sided alpha (default 0.05, matching the
amendment's CI95) and power (default 0.80, the field-standard convention),
df = n - 1:

    SE  = sigma_seed / sqrt(n)
    MDE = SE * ( t.ppf(1 - alpha/2, df) + t.ppf(power, df) )

This is a pre-launch POWER estimate, distinct from -- and never a substitute for
-- the amendment's frozen terminal CI procedure (cluster-resampled paired BCa
bootstrap, B=10000, rng_seed=20260709), which is what actually scores F1/F2/F3.
The formula, and every input that fed it, is receipted so a hostile reviewer can
recompute sigma_seed_per_class and mde_at_n5 from the receipt alone.

USAGE
-----
    python compute_mde.py [--receipts-dir DIR] [--out-dir DIR] [--n N]
                           [--alpha A] [--power P]
    python compute_mde.py --selftest
"""
import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent  # scripts/
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from receipt_write import checked_write  # noqa: E402

# Constitutional invariant hash (issue #281 genesis) -- required on every
# receipt with ts after GENESIS_TS by receipt_check.py's schema floor.
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

# Filename markers identifying candidate rung-2 dev variance receipts.
KEYWORD_MARKERS = ("remeasure", "stabilize", "b-series", "bseries")

DEFAULT_N = 5
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.80


def _code_sha256() -> str:
    """sha256 of this script's own source bytes (self-hash for the receipt)."""
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _is_finite_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _extract_variance_source(path: Path):
    """Parse one candidate file and return (usable_entry, skip_reason).

    Exactly one of the two return values is non-None.
    usable_entry: {"file", "comparison_class", "n_seeds", "sigma_seed", "seeds"}
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"parse error: {e}"

    if not isinstance(d, dict):
        return None, "not a JSON object"

    cls = d.get("comparison_class")
    if not isinstance(cls, str) or not cls:
        return None, "missing/invalid 'comparison_class'"

    seeds = d.get("per_seed_eval_loss")
    if not isinstance(seeds, list):
        return None, "missing/invalid 'per_seed_eval_loss' (not a list)"

    if not all(_is_finite_number(v) for v in seeds):
        return None, "'per_seed_eval_loss' contains non-finite/non-numeric values"

    if len(seeds) < 2:
        return None, f"'per_seed_eval_loss' has {len(seeds)} value(s), need >=2 to compute sd"

    sigma_seed = statistics.stdev(seeds)  # sample sd, ddof=1
    return {
        "file": str(path),
        "comparison_class": cls,
        "n_seeds": len(seeds),
        "sigma_seed": sigma_seed,
        "seeds": list(seeds),
    }, None


def scan_receipts(receipts_dir: str):
    """Enumerate KEYWORD_MARKERS-matched *.json under receipts_dir (recursive).

    Returns (usable: list[dict], skipped: list[dict]).
    """
    usable, skipped = [], []
    root = Path(receipts_dir)
    if not root.is_dir():
        return usable, skipped

    for path in sorted(root.rglob("*.json")):
        name_lower = path.name.lower()
        if not any(marker in name_lower for marker in KEYWORD_MARKERS):
            continue
        entry, reason = _extract_variance_source(path)
        if entry is not None:
            usable.append(entry)
        else:
            skipped.append({"file": str(path), "reason": reason})
    return usable, skipped


def pooled_sigma_per_class(usable):
    """Pool sigma_seed across usable receipts sharing the same comparison_class.

    Returns {class: {"sigma_seed": float, "n_seeds_total": int, "n_receipts": int}}.
    """
    by_class = {}
    for e in usable:
        by_class.setdefault(e["comparison_class"], []).append(e)

    out = {}
    for cls, entries in by_class.items():
        num = sum((e["n_seeds"] - 1) * (e["sigma_seed"] ** 2) for e in entries)
        den = sum((e["n_seeds"] - 1) for e in entries)
        sigma_pooled = math.sqrt(num / den) if den > 0 else entries[0]["sigma_seed"]
        out[cls] = {
            "sigma_seed": sigma_pooled,
            "n_seeds_total": sum(e["n_seeds"] for e in entries),
            "n_receipts": len(entries),
        }
    return out


def mde_one_sample(sigma_seed: float, n: int, alpha: float, power: float) -> float:
    """Closed-form MDE for a one-sample/paired t-test at fixed n, alpha, power.

    SE = sigma_seed / sqrt(n); MDE = SE * (t_(1-alpha/2, df) + t_(power, df)),
    df = n - 1. Requires scipy.stats.t (stdlib has no t-quantile function).
    """
    from scipy.stats import t as student_t

    if n < 2:
        raise ValueError("mde_one_sample: n must be >= 2 (need df = n-1 >= 1)")
    df = n - 1
    se = sigma_seed / math.sqrt(n)
    t_alpha2 = student_t.ppf(1 - alpha / 2, df)
    t_power = student_t.ppf(power, df)
    return se * (t_alpha2 + t_power)


FORMULA_TEXT = (
    "SE = sigma_seed / sqrt(n); "
    "MDE = SE * (t.ppf(1 - alpha/2, df) + t.ppf(power, df)), df = n - 1; "
    "sigma_seed pooled across same-class receipts via "
    "sqrt(sum((n_i-1)*sigma_i^2) / sum(n_i-1))."
)


def run(receipts_dir: str, out_dir: str, n: int, alpha: float, power: float):
    """Core obligation logic. Returns (exit_code, receipt_or_None, message)."""
    usable, skipped = scan_receipts(receipts_dir)

    if len(usable) < 2:
        msg = (
            f"compute_mde: ERROR -- only {len(usable)} usable variance receipt(s) "
            f"found under '{receipts_dir}' (need >=2). Matched-but-unusable "
            f"filenames: {[s['file'] for s in skipped]}. This is the designed "
            f"outcome, not a bug: fresh post-freeze variance runs are required "
            f"before any governed launch. No mde-*.json receipt written."
        )
        return 1, None, msg

    sigma_seed_per_class = pooled_sigma_per_class(usable)
    mde_at_n5 = {
        cls: {
            "sigma_seed": v["sigma_seed"],
            "n_seeds_total": v["n_seeds_total"],
            "n_receipts": v["n_receipts"],
            "mde": mde_one_sample(v["sigma_seed"], n, alpha, power),
        }
        for cls, v in sigma_seed_per_class.items()
    }

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    receipt = {
        "ticket": "C8-PRELAUNCH-O2-MDE",
        "ts": ts,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "code_sha": _code_sha256(),
        "issue": 582,
        "refs": [123, 487, 449],
        "design": {"n": n, "alpha": alpha, "power": power},
        "formula": FORMULA_TEXT,
        "inputs": usable,
        "skipped": skipped,
        "sigma_seed_per_class": sigma_seed_per_class,
        "mde_at_n5": mde_at_n5,
    }

    fname = f"mde-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, fname)
    checked_write(out_path, receipt)
    return 0, receipt, f"COMPUTE_MDE_DONE {out_path}"


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f)


def _selftest() -> int:
    failures = []

    # --- RED 1: fewer than 2 usable receipts (a single matched, valid receipt) -> ERROR ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "cbase-grow-rung2-event-remeasure-b1.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0, 1.02, 0.99]},
        )
        code, receipt, msg = run(td, os.path.join(td, "out"), DEFAULT_N, DEFAULT_ALPHA, DEFAULT_POWER)
        if code != 1 or receipt is not None:
            failures.append(f"RED1 FAIL: expected error exit with no receipt, got code={code} receipt={receipt}")
        out_dir = os.path.join(td, "out")
        if os.path.isdir(out_dir) and os.listdir(out_dir):
            failures.append("RED1 FAIL: an mde-*.json was written despite <2 usable receipts")

    # --- RED 2: matched filename but schema-invalid (only 1 seed value) does NOT count ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "remeasure-good.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0, 1.02]},
        )
        _write_json(
            os.path.join(td, "remeasure-bad-single-seed.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0]},  # only 1 value
        )
        code, receipt, msg = run(td, os.path.join(td, "out"), DEFAULT_N, DEFAULT_ALPHA, DEFAULT_POWER)
        if code != 1 or receipt is not None:
            failures.append(f"RED2 FAIL: expected error (1 good + 1 invalid = 1 usable), got code={code}")

    # --- RED 3: non-matching filenames are never enumerated at all ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "unrelated-receipt.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0, 1.02, 1.05]},
        )
        usable, skipped = scan_receipts(td)
        if usable or skipped:
            failures.append(f"RED3 FAIL: non-marker filename should never be enumerated, got usable={usable} skipped={skipped}")

    # --- GREEN: synthetic two-receipt fixture reproduces hand-computed MDE ---
    with tempfile.TemporaryDirectory() as td:
        # Receipt A: class f1_mechanism, values [1.0, 3.0] -> mean=2.0, sample var=2.0, sd=sqrt(2)
        _write_json(
            os.path.join(td, "cbase-grow-rung2-remeasure-b-series-a.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0, 3.0]},
        )
        # Receipt B: class f2_criterion, values [5.0, 5.0, 5.0, 8.0] -> sd hand-computable too,
        # but distinct class so it must NOT be pooled with A.
        _write_json(
            os.path.join(td, "cbase-grow-rung2-stabilize-dev-b.json"),
            {"comparison_class": "f2_criterion", "per_seed_eval_loss": [5.0, 5.0, 5.0, 8.0]},
        )
        out_dir = os.path.join(td, "out")
        code, receipt, msg = run(td, out_dir, DEFAULT_N, DEFAULT_ALPHA, DEFAULT_POWER)
        if code != 0 or receipt is None:
            failures.append(f"GREEN FAIL: expected success with 2 usable receipts, got code={code} msg={msg}")
        else:
            sigma_a = receipt["sigma_seed_per_class"]["f1_mechanism"]["sigma_seed"]
            expected_sigma_a = math.sqrt(2.0)  # hand-computed: mean=2, var=((1-2)^2+(3-2)^2)/1=2
            if abs(sigma_a - expected_sigma_a) > 1e-9:
                failures.append(f"GREEN FAIL: sigma_a expected {expected_sigma_a}, got {sigma_a}")

            # Hand-computed sd for class B: values [5,5,5,8], mean=5.75,
            # sq devs: 0.5625*3 + 5.0625 = 1.6875+5.0625=6.75, /(4-1)=2.25, sd=1.5
            sigma_b = receipt["sigma_seed_per_class"]["f2_criterion"]["sigma_seed"]
            expected_sigma_b = 1.5
            if abs(sigma_b - expected_sigma_b) > 1e-9:
                failures.append(f"GREEN FAIL: sigma_b expected {expected_sigma_b}, got {sigma_b}")

            # MDE at n=5, alpha=0.05, power=0.80, df=4: standard t-table values
            # (hand/table lookup, not re-derived from scipy): t_(0.975,4)=2.776445105,
            # t_(0.80,4)=0.940965. Tolerance is loose (1e-2) since these are widely
            # published rounded table constants, not the exact scipy float.
            t_alpha2_df4 = 2.776445105
            t_power_df4 = 0.940965
            expected_mde_a = (expected_sigma_a / math.sqrt(5)) * (t_alpha2_df4 + t_power_df4)
            got_mde_a = receipt["mde_at_n5"]["f1_mechanism"]["mde"]
            if abs(got_mde_a - expected_mde_a) > 1e-2:
                failures.append(f"GREEN FAIL: mde_a expected ~{expected_mde_a}, got {got_mde_a}")

            if receipt["mde_at_n5"]["f1_mechanism"]["n_receipts"] != 1:
                failures.append("GREEN FAIL: f1_mechanism should pool exactly 1 receipt (not merged with f2_criterion)")

    # --- GREEN: two receipts of the SAME class get pooled (n_receipts=2) ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "remeasure-x1.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0, 1.02, 0.99]},
        )
        _write_json(
            os.path.join(td, "stabilize-x2.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.01, 0.98, 1.03, 1.0]},
        )
        out_dir = os.path.join(td, "out")
        code, receipt, msg = run(td, out_dir, DEFAULT_N, DEFAULT_ALPHA, DEFAULT_POWER)
        if code != 0 or receipt is None:
            failures.append(f"GREEN-POOL FAIL: expected success, got code={code} msg={msg}")
        elif receipt["sigma_seed_per_class"]["f1_mechanism"]["n_receipts"] != 2:
            failures.append("GREEN-POOL FAIL: same-class receipts across 2 files should pool to n_receipts=2")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("COMPUTE_MDE_SELFTEST_PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description="C8 pre-launch O2: publish the MDE from dev variance receipts.")
    ap.add_argument("--receipts-dir", default="receipts")
    ap.add_argument("--out-dir", default="receipts/c8-prelaunch")
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--power", type=float, default=DEFAULT_POWER)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())

    code, receipt, msg = run(args.receipts_dir, args.out_dir, args.n, args.alpha, args.power)
    print(msg, file=sys.stderr if code != 0 else sys.stdout)
    if receipt is not None:
        print(json.dumps(receipt, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
