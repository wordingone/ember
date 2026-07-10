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

SCHEMA v2 (issue #585 cure; coordinator disposition comment 4931087645 on #585,
points 1-3, SIGN-CORRECTED by the coordinator's tighten-only amendment comments
4931112873 / 4931141583 / 4931147752, same thread, same day) -- BREAKING,
replaces the raw-only v1 schema
--------------------------------------------------------------------------------
Independent audit finding (CONFIRMED): the v1 schema stored a single raw-loss
array per receipt with no pairing structure, so sigma_seed was computed from
the ARM'S MARGINAL distribution -- order-invariant, hence blind to how each
treatment seed paired with its control seed. Two datasets with identical
marginal distributions but different pairing structure produced IDENTICAL
MDEs, because SD(delta) = sqrt(SD_A^2 + SD_B^2 - 2*Cov(A,B)) and the covariance
term is not recoverable from marginals alone. Counterexample (reproduced in
test_mde_paired_covariance.py): A=[0,1,2,3,4], B+=A+0.1, B-=reverse(B+) --
identical marginal SD (~1.5811388) for B+ and B-, yet paired-delta SD is
~0 (aligned pairing) vs ~3.1622777 (reversed pairing). SD/MDE magnitude is
negation-invariant, so this covariance finding is unaffected by the sign
amendment below.

Sign-correction amendment (2026-07-10, same-day tighten-only, comment
4931147752): the #123 falsifier-fill registration (comment 4928342201) fixes
the terminal paired statistic as delta_i = L_control(i) - L_treatment(i),
positive = treatment better. The original disposition (4931087645) wrote the
opposite sign (treatment - control); the amendment corrects it before any
implementation, adds a mandatory 'delta_convention' field so the sign is a
checked field, not a comment, and requires the consumer to recompute the
SIGNED delta (sign included) from the paired arms.

INPUT ENUMERATION (the "receipt-enumeration half")
---------------------------------------------------
Scans --receipts-dir (default: receipts/) for JSON files whose FILENAME contains
one of the KEYWORD_MARKERS below (case-insensitive substring match) -- these are
the "existing rung-2 dev receipts carrying per-seed eval-loss spreads (b-series
remeasure + stabilize dev receipts)" the issue names as the variance source.
Every one of these receipts is PRE-FREEZE / development-only under A1 (quarantined
for any CLAIM purpose) -- but computing power (this tool), not a claim, is exactly
what the amendment authorizes reading them for.

A matched filename is checked against the schema v2 "usable variance receipt"
shape (replaces the v1 raw-only shape; any future dev receipt wanting to feed
the MDE must conform to this):

    {
      "comparison_class": <str>,                 # e.g. "f1_mechanism", "f2_criterion", "f3_deletion"
      "seed_id": [<str|int>, ...],                # >=2 stable per-seed identifiers
      "control_eval_loss": [<float>, ...],        # same length as seed_id, nats
      "treatment_eval_loss": [<float>, ...],       # same length as seed_id, nats, paired to control by index
      "delta_convention": "control_minus_treatment",  # required literal; the sign is a checked field
      "per_seed_delta_nats": [<float>, ...]        # = control_eval_loss[i] - treatment_eval_loss[i]; recomputed and checked, sign included
      ... (any other fields, including a legacy per_seed_eval_loss marginal, ignored)
    }

A file matching a filename marker but failing schema v2 is recorded as SKIPPED
with a reason and does NOT count toward the usable total, in every one of these
cases (points 2 + 3 of the disposition, sign-corrected):

  - raw-only: carries 'per_seed_eval_loss' but none of the schema v2 pairing
    fields -- covariance is not recoverable from a marginal alone, so this
    receipt can NEVER be made usable regardless of how many seeds it has.
  - missing/invalid 'seed_id' / 'control_eval_loss' / 'treatment_eval_loss' /
    'per_seed_delta_nats', non-finite values, or unequal array lengths.
  - missing/invalid 'delta_convention' (must equal the literal string
    'control_minus_treatment' -- any other value, including the pre-amendment
    'treatment_minus_control', is rejected).
  - fewer than 2 seeds.
  - 'per_seed_delta_nats' does not match the SIGNED value recomputed as
    control_eval_loss[i] - treatment_eval_loss[i] (within float tolerance,
    sign included) -- the tool never trusts an emitted delta it cannot itself
    reproduce from the paired fields, and a sign-flipped delta is exactly as
    unusable as a magnitude mismatch.

If fewer than 2 usable variance receipts remain, this script prints a specific
error to stderr, writes NO mde-*.json receipt, and exits 1. The missing-variance
outcome is itself the designed, receipted result (via the exit code + stderr text
captured by the caller) -- it forces fresh variance runs before any governed
launch. Never fabricate sigma_seed from fewer than 2 sources.

MDE FORMULA
-----------
Per usable receipt: sigma_seed = sample standard deviation (ddof=1) of its
per_seed_delta_nats array (the SIGNED PAIRED DELTAS, control - treatment, per
issue #585's cure -- never the raw marginal arrays). sigma_seed_per_class
pools receipts sharing the same
comparison_class using the standard pooled-variance formula, unchanged in form,
now applied over delta-SDs:

    sigma_pooled = sqrt( sum_i[(n_i - 1) * sigma_i^2] / sum_i[n_i - 1] )

The terminal design MDE at n (default 5, the amendment's fixed cheap-rung seed
count) is the EXACT minimum detectable effect for a one-sample / paired mean
test (the F1/F2 terminal grammar tests the mean of n per-seed paired deltas
against 0), two-sided alpha (default 0.05, matching the amendment's CI95) and
power (default 0.80, the field-standard convention), df = n - 1:

    SE        = sigma_seed / sqrt(n)
    t_crit    = t.ppf(1 - alpha/2, df)
    ncp_exact = root of  nct.cdf(-t_crit, df, ncp) + nct.sf(t_crit, df, ncp) = power
    MDE       = SE * ncp_exact

Exact-power addendum (issue #585, independent-audit comment 4931301214): the
central-t shortcut MDE = SE * (t.ppf(1-alpha/2,df) + t.ppf(power,df)) is
anti-conservative -- at n=5/alpha=0.05/power=0.80 it achieves only ~0.7913
power (ncp 3.7174096824423772 vs the exact 3.761059553825027, MDE understated
by ~1.17%). Exact power of a t-test with estimated variance follows the
noncentral-t distribution, so the noncentrality is obtained by an exact root
solve; the tool never labels an anti-conservative approximation as the named
power.

This is a pre-launch POWER estimate, distinct from -- and never a substitute for
-- the amendment's frozen terminal CI procedure (cluster-resampled paired BCa
bootstrap, B=10000, rng_seed=20260709), which is what actually scores F1/F2/F3.
The formula, and every input that fed it, is receipted so a hostile reviewer can
recompute sigma_seed_per_class and mde_at_n5 from the receipt alone.

POST-CURE REPLAY (binding, disposition on #585): the MDE obligation, and any
output of the raw-schema (v1) tool, was BLOCKED as C8 launch/power evidence
until this cure landed. Post-cure replay by the independent-audit-lane is
BINDING before MDE output regains evidence status -- this cure PR does not
itself restore that status.

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
    usable_entry: {"file", "comparison_class", "n_seeds", "sigma_seed",
                   "seed_id", "per_seed_delta_nats"}

    Schema v2 (issue #585 cure, disposition points 1-3, sign-corrected by
    the coordinator's 2026-07-10 tighten-only amendment, comment 4931147752):
    sigma_seed is the sample sd of the SIGNED PAIRED DELTAS (control minus
    treatment per seed, positive = treatment better -- matching the #123
    terminal grammar's delta_i = L_control(i) - L_treatment(i)), never a raw
    marginal array -- SD(delta) = sqrt(SD_A^2 + SD_B^2 - 2*Cov(A,B)) is not
    recoverable from marginals, so a schema that only stores one marginal
    array cannot support a paired MDE regardless of how it is consumed.
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

    # Point 3: raw-only receipts (v1 shape: a marginal 'per_seed_eval_loss'
    # array with NO pairing structure) are never usable -- the rejection is
    # itself the receipted outcome (this reason string lands in `skipped`).
    _PAIR_FIELDS = ("control_eval_loss", "treatment_eval_loss", "per_seed_delta_nats")
    if "per_seed_eval_loss" in d and not any(f in d for f in _PAIR_FIELDS):
        return None, (
            "schema v2 rejection: raw-only 'per_seed_eval_loss' carries no pairing "
            "structure (control_eval_loss/treatment_eval_loss/per_seed_delta_nats "
            "all absent) -- paired covariance is not recoverable from a marginal "
            "array; this receipt can never be usable for MDE (issue #585, point 3)"
        )

    seed_ids = d.get("seed_id")
    if not isinstance(seed_ids, list) or not seed_ids:
        return None, "missing/invalid 'seed_id' (schema v2 requires a stable seed_id list)"

    control = d.get("control_eval_loss")
    if not isinstance(control, list) or not all(_is_finite_number(v) for v in control):
        return None, "missing/invalid 'control_eval_loss' (schema v2 requires a finite paired array)"

    treatment = d.get("treatment_eval_loss")
    if not isinstance(treatment, list) or not all(_is_finite_number(v) for v in treatment):
        return None, "missing/invalid 'treatment_eval_loss' (schema v2 requires a finite paired array)"

    deltas = d.get("per_seed_delta_nats")
    if not isinstance(deltas, list) or not all(_is_finite_number(v) for v in deltas):
        return None, "missing/invalid 'per_seed_delta_nats' (schema v2 requires a finite paired-delta array)"

    # Sign-correction amendment (2026-07-10, comment 4931147752, point 2):
    # the delta_convention field is required and checked -- the sign is a
    # field, not a comment. Only the exact literal is accepted; the
    # pre-amendment 'treatment_minus_control' sign is explicitly rejected.
    convention = d.get("delta_convention")
    if convention != "control_minus_treatment":
        return None, (
            "missing/invalid 'delta_convention': schema v2 requires the exact "
            f"literal 'control_minus_treatment' (issue #585 sign-correction "
            f"amendment, comment 4931147752); got {convention!r}"
        )

    n = len(seed_ids)
    if not (len(control) == n and len(treatment) == n and len(deltas) == n):
        return None, (
            f"schema v2 length mismatch: seed_id={n} control_eval_loss={len(control)} "
            f"treatment_eval_loss={len(treatment)} per_seed_delta_nats={len(deltas)} "
            f"(all four arrays must be equal length)"
        )

    if n < 2:
        return None, f"'seed_id' has {n} value(s), need >=2 to compute sd"

    # Point 2 (sign-corrected): recompute the SIGNED delta from the paired
    # fields as control - treatment (positive = treatment better, matching
    # #123's registered delta_i = L_control - L_treatment). A mismatch --
    # sign included -- means the receipt's own delta field cannot be
    # trusted, so it is SKIPPED rather than silently accepted.
    recomputed = [c - t for c, t in zip(control, treatment)]
    for i, (r, e) in enumerate(zip(recomputed, deltas)):
        if not math.isclose(r, e, rel_tol=1e-9, abs_tol=1e-9):
            return None, (
                f"per_seed_delta_nats mismatch at seed index {i}: recomputed "
                f"control-treatment={r!r} != emitted value={e!r} (issue #585, "
                f"point 2, sign per #123 terminal grammar / comment 4931147752)"
            )

    sigma_seed = statistics.stdev(deltas)  # sample sd (ddof=1) of SIGNED PAIRED DELTAS
    return {
        "file": str(path),
        "comparison_class": cls,
        "n_seeds": n,
        "sigma_seed": sigma_seed,
        "seed_id": list(seed_ids),
        "delta_convention": "control_minus_treatment",
        "per_seed_delta_nats": list(deltas),
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


def two_sided_power_at_ncp(ncp: float, df: int, t_crit: float) -> float:
    """Exact achieved two-sided power of a t-test at noncentrality ncp:
    P(T < -t_crit) + P(T > t_crit) where T ~ noncentral-t(df, ncp)."""
    from scipy.stats import nct

    return float(nct.cdf(-t_crit, df, ncp) + nct.sf(t_crit, df, ncp))


def mde_one_sample(sigma_seed: float, n: int, alpha: float, power: float) -> float:
    """Exact MDE for a one-sample/paired t-test at fixed n, alpha, power.

    Exact-power addendum (issue #585, independent-audit comment 4931301214):
    the central-t shortcut ncp ~= t_(1-alpha/2, df) + t_(power, df) is
    ANTI-CONSERVATIVE -- at n=5/alpha=0.05/power=0.80 it achieves only
    ~0.7913 power (understating the MDE by ~1.17%), because exact power of
    a t-test with estimated variance follows the NONCENTRAL-t distribution.
    The consumer must not label an anti-conservative approximation as exact
    80% power, so the noncentrality is obtained by an exact root solve of

        power_achieved(ncp) = nct.cdf(-t_crit, df, ncp) + nct.sf(t_crit, df, ncp)

    for power_achieved(ncp) = power (brentq; power_achieved is monotone
    increasing in ncp >= 0, and power_achieved(0) = alpha < power gives a
    valid lower bracket). MDE = SE * ncp_exact with SE = sigma_seed / sqrt(n),
    df = n - 1. Requires scipy (stdlib has no t / noncentral-t machinery).
    """
    from scipy.optimize import brentq
    from scipy.stats import t as student_t

    if n < 2:
        raise ValueError("mde_one_sample: n must be >= 2 (need df = n-1 >= 1)")
    if not (0.0 < alpha < 1.0 and 0.0 < power < 1.0 and power > alpha):
        raise ValueError("mde_one_sample: require 0 < alpha < power < 1")
    df = n - 1
    se = sigma_seed / math.sqrt(n)
    t_crit = student_t.ppf(1 - alpha / 2, df)

    # Bracket: at ncp=0 achieved power = alpha < power (f(lo) < 0). The
    # central-t shortcut understates ncp, so shortcut + margin is expanded
    # geometrically until it over-achieves (f(hi) > 0) -- robust for any
    # (alpha, power, df), never trusting the shortcut as an upper bound.
    lo = 0.0
    hi = t_crit + student_t.ppf(power, df) + 1.0
    while two_sided_power_at_ncp(hi, df, t_crit) < power:
        hi *= 2.0
        if hi > 1e6:
            raise RuntimeError("mde_one_sample: could not bracket the noncentral-t root")
    ncp_exact = brentq(
        lambda x: two_sided_power_at_ncp(x, df, t_crit) - power, lo, hi,
        xtol=1e-12, rtol=8.881784197001252e-16,
    )
    return se * float(ncp_exact)


FORMULA_TEXT = (
    "SE = sigma_seed / sqrt(n); t_crit = t.ppf(1 - alpha/2, df), df = n - 1; "
    "ncp_exact = the root of nct.cdf(-t_crit, df, ncp) + nct.sf(t_crit, df, ncp) = power "
    "(exact noncentral-t two-sided power, solved by brentq -- never the "
    "anti-conservative central-t shortcut t.ppf(1-alpha/2,df)+t.ppf(power,df); "
    "issue #585 exact-power addendum, comment 4931301214); "
    "MDE = SE * ncp_exact; "
    "sigma_seed = sample sd (ddof=1) of per_seed_delta_nats (signed paired deltas, "
    "control - treatment), pooled across same-class receipts via "
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


def _v2(cls, control, treatment, seed_id=None):
    """Build a schema-v2 receipt dict with the correctly SIGNED delta
    (control - treatment, per the 2026-07-10 sign-correction amendment,
    comment 4931147752) and delta_convention pre-filled -- every fixture in
    this selftest is arithmetic-consistent by construction, never hand-typed."""
    if seed_id is None:
        seed_id = [f"s{i + 1}" for i in range(len(control))]
    delta = [c - t for c, t in zip(control, treatment)]
    return {
        "comparison_class": cls,
        "seed_id": list(seed_id),
        "control_eval_loss": list(control),
        "treatment_eval_loss": list(treatment),
        "delta_convention": "control_minus_treatment",
        "per_seed_delta_nats": delta,
    }


def _selftest() -> int:
    failures = []

    # --- RED 1: fewer than 2 usable receipts (a single matched, valid receipt) -> ERROR ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "cbase-grow-rung2-event-remeasure-b1.json"),
            _v2("f1_mechanism", [0.0, 0.0, 0.0], [1.0, 1.02, 0.99]),
        )
        code, receipt, msg = run(td, os.path.join(td, "out"), DEFAULT_N, DEFAULT_ALPHA, DEFAULT_POWER)
        if code != 1 or receipt is not None:
            failures.append(f"RED1 FAIL: expected error exit with no receipt, got code={code} receipt={receipt}")
        out_dir = os.path.join(td, "out")
        if os.path.isdir(out_dir) and os.listdir(out_dir):
            failures.append("RED1 FAIL: an mde-*.json was written despite <2 usable receipts")

    # --- RED 2: matched filename but schema-invalid (only 1 seed value) does NOT count ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(os.path.join(td, "remeasure-good.json"), _v2("f1_mechanism", [0.0, 0.0], [1.0, 1.02]))
        _write_json(os.path.join(td, "remeasure-bad-single-seed.json"), _v2("f1_mechanism", [0.0], [1.0]))  # only 1 value
        code, receipt, msg = run(td, os.path.join(td, "out"), DEFAULT_N, DEFAULT_ALPHA, DEFAULT_POWER)
        if code != 1 or receipt is not None:
            failures.append(f"RED2 FAIL: expected error (1 good + 1 invalid = 1 usable), got code={code}")

    # --- RED 3: non-matching filenames are never enumerated at all ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(os.path.join(td, "unrelated-receipt.json"), _v2("f1_mechanism", [0.0, 0.0, 0.0], [1.0, 1.02, 1.05]))
        usable, skipped = scan_receipts(td)
        if usable or skipped:
            failures.append(f"RED3 FAIL: non-marker filename should never be enumerated, got usable={usable} skipped={skipped}")

    # --- RED 4 (issue #585, point 3): raw-only per_seed_eval_loss with NO pairing fields is NEVER usable ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "remeasure-rawonly.json"),
            {"comparison_class": "f1_mechanism", "per_seed_eval_loss": [1.0, 1.02, 0.99]},
        )
        usable, skipped = scan_receipts(td)
        if usable:
            failures.append(f"RED4 FAIL: raw-only per_seed_eval_loss (no pairing) was accepted as usable: {usable}")
        if len(skipped) != 1 or "raw-only" not in skipped[0]["reason"]:
            failures.append(f"RED4 FAIL: expected a raw-only skip reason, got {skipped}")

    # --- RED 5 (sign-correction amendment, comment 4931147752 point 2): wrong/missing
    # delta_convention literal is rejected even when the numeric values are correct ---
    with tempfile.TemporaryDirectory() as td:
        bad_conv = _v2("f1_mechanism", [0.0, 0.0], [1.0, 2.0])
        bad_conv["delta_convention"] = "treatment_minus_control"  # pre-amendment sign label -- rejected
        _write_json(os.path.join(td, "remeasure-badconv.json"), bad_conv)
        usable, skipped = scan_receipts(td)
        if usable:
            failures.append(f"RED5 FAIL: wrong delta_convention literal was accepted as usable: {usable}")
        if len(skipped) != 1 or "delta_convention" not in skipped[0]["reason"]:
            failures.append(f"RED5 FAIL: expected a delta_convention skip reason, got {skipped}")

    # --- RED 6 (sign-correction amendment point 3): a SIGN-FLIPPED per_seed_delta_nats
    # (treatment - control emitted under a correctly-labeled 'control_minus_treatment'
    # convention) must be caught by the signed-recompute mismatch check ---
    with tempfile.TemporaryDirectory() as td:
        wrong_sign = {
            "comparison_class": "f1_mechanism",
            "seed_id": ["s1", "s2"],
            "control_eval_loss": [0.0, 0.0],
            "treatment_eval_loss": [1.0, 2.0],
            "delta_convention": "control_minus_treatment",
            "per_seed_delta_nats": [1.0, 2.0],  # WRONG: this is treatment-control, not control-treatment
        }
        _write_json(os.path.join(td, "remeasure-wrongsign.json"), wrong_sign)
        usable, skipped = scan_receipts(td)
        if usable:
            failures.append(f"RED6 FAIL: sign-flipped per_seed_delta_nats was accepted as usable: {usable}")
        if len(skipped) != 1 or "mismatch" not in skipped[0]["reason"]:
            failures.append(f"RED6 FAIL: expected a signed-mismatch skip reason, got {skipped}")

    # --- GREEN: synthetic two-receipt fixture reproduces hand-computed MDE ---
    # control=0 arrays throughout so delta = -treatment; SD is sign-flip-invariant,
    # so the hand-computed sd values below match the treatment array directly.
    with tempfile.TemporaryDirectory() as td:
        # Receipt A: class f1_mechanism, treatment [1.0, 3.0] (control 0) -> delta
        # mean=-2.0, sample var=2.0, sd=sqrt(2) (same magnitude as sd([1,3])).
        _write_json(
            os.path.join(td, "cbase-grow-rung2-remeasure-b-series-a.json"),
            _v2("f1_mechanism", [0.0, 0.0], [1.0, 3.0]),
        )
        # Receipt B: class f2_criterion, treatment [5.0, 5.0, 5.0, 8.0] (control 0) --
        # distinct class so it must NOT be pooled with A.
        _write_json(
            os.path.join(td, "cbase-grow-rung2-stabilize-dev-b.json"),
            _v2("f2_criterion", [0.0, 0.0, 0.0, 0.0], [5.0, 5.0, 5.0, 8.0]),
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

            # MDE at n=5, alpha=0.05, power=0.80, df=4: exact noncentral-t
            # noncentrality (issue #585 exact-power addendum, comment
            # 4931301214; independently replayed against scipy nct+brentq):
            # ncp_exact = 3.761059553825027. NOT the central-t shortcut
            # 3.7174096824423772, which achieves only ~0.7913 power.
            ncp_exact_df4 = 3.761059553825027
            expected_mde_a = (expected_sigma_a / math.sqrt(5)) * ncp_exact_df4
            got_mde_a = receipt["mde_at_n5"]["f1_mechanism"]["mde"]
            if abs(got_mde_a - expected_mde_a) > 1e-6:
                failures.append(f"GREEN FAIL: mde_a expected ~{expected_mde_a}, got {got_mde_a}")

            # Exact-power addendum regression (comment 4931301214): the
            # achieved two-sided power at the published MDE must be >= the
            # labeled target -- never anti-conservative.
            from scipy.stats import t as _t
            _tcrit = _t.ppf(1 - DEFAULT_ALPHA / 2, DEFAULT_N - 1)
            _se_a = expected_sigma_a / math.sqrt(DEFAULT_N)
            achieved = two_sided_power_at_ncp(got_mde_a / _se_a, DEFAULT_N - 1, _tcrit)
            if achieved < DEFAULT_POWER - 1e-9:
                failures.append(
                    f"GREEN FAIL: achieved power {achieved} at the published MDE is below "
                    f"the labeled target {DEFAULT_POWER} (anti-conservative)"
                )

            if receipt["mde_at_n5"]["f1_mechanism"]["n_receipts"] != 1:
                failures.append("GREEN FAIL: f1_mechanism should pool exactly 1 receipt (not merged with f2_criterion)")

    # --- GREEN: two receipts of the SAME class get pooled (n_receipts=2) ---
    with tempfile.TemporaryDirectory() as td:
        _write_json(
            os.path.join(td, "remeasure-x1.json"),
            _v2("f1_mechanism", [0.0, 0.0, 0.0], [1.0, 1.02, 0.99]),
        )
        _write_json(
            os.path.join(td, "stabilize-x2.json"),
            _v2("f1_mechanism", [0.0, 0.0, 0.0, 0.0], [1.01, 0.98, 1.03, 1.0]),
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
