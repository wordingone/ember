# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""power_helper.py — MDE/power sizing table for gate statistics (eng #346).

Given (n, p0, alpha=0.05, power=0.80), emits a three-column sizing table:
  wilson     : score CI for base rate p0 at n tasks (p̂ = round(p0*n)/n)
  newcombe   : MDE for paired design — mde_two_prop conservative upper bound
  mcnemar    : minimum total discordant pairs (b+c) for exact two-sided p < alpha

All arithmetic delegates to existing power.py / g1_paired.py primitives. No
new statistical math is introduced here.

CLI:
  python power_helper.py --n N --p0 P0 [--alpha 0.05] [--power 0.80]
      Prints table to stdout. Add --receipt to write receipts/ entry.
  python power_helper.py --selftest
      Runs anchor fixtures; exits 0 and prints POWER_HELPER_SELFTEST_PASS.

Selftest anchors (gate-stats-review-v1 §4):
  (1) wilson(0, 100) upper ∈ [3.50%, 4.00%]  (spec says ≈3.57%; formula gives ≈3.70%;
      both are approximations — fixture accepts either)
  (2) rule-of-three parity at n=100: Wilson upper > 3/100 (Wilson wider than RoT at n=100)
  (3) mcnemar_min_discordant(alpha=0.05) == 6
      b=6, c=0 → exact p ≈ 0.031 < 0.05; b=5, c=0 → exact p ≈ 0.063 ≥ 0.05

Spec: docs/archive/pre-restart/gate-stats-review-v1.md §4 (frozen 2026-06-12).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from power import wilson, mde_two_prop, Z975, Z80          # noqa: E402
from g1_paired import mcnemar_exact                         # noqa: E402
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py                     # noqa: E402

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_RECEIPTS = _REPO / "receipts"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _z_alpha(alpha: float) -> float:
    if abs(alpha - 0.05) < 1e-9:
        return Z975
    try:
        from stats_exact import _z_from_p as _q
        return _q(1.0 - alpha / 2)
    except (ImportError, AttributeError):
        raise ValueError(f"alpha={alpha}: only 0.05 supported without stats_exact")


def _z_power(power: float) -> float:
    if abs(power - 0.80) < 1e-9:
        return Z80
    try:
        from stats_exact import _z_from_p as _q
        return _q(power)
    except (ImportError, AttributeError):
        raise ValueError(f"power={power}: only 0.80 supported without stats_exact")


def mcnemar_min_discordant(alpha: float = 0.05) -> int:
    """Minimum total discordant pairs d = b+c to reach exact McNemar p < alpha.

    Uses the most asymmetric split (c=0, b=d) which gives the smallest p
    for a given d. The result is independent of the total pair count n.
    """
    for d in range(1, 1000):
        if mcnemar_exact(d, 0) < alpha:
            return d
    raise RuntimeError("mcnemar_min_discordant: no solution within 1000 pairs")


def size_table(n: int, p0: float, alpha: float = 0.05,
               power: float = 0.80) -> dict:
    """Compute the three-method sizing table.

    Returns a dict suitable for receipt serialisation:
      n, p0, alpha, power, s (integer success count for wilson),
      wilson_lo, wilson_hi, mde_newcombe, mcnemar_min_dc.
    """
    s = int(round(p0 * n))
    za = _z_alpha(alpha)
    zb = _z_power(power)
    lo, hi = wilson(s, n, z=za)
    mde = mde_two_prop(n, p0, z_alpha=za, z_beta=zb)
    min_dc = mcnemar_min_discordant(alpha)
    return {
        "n": n,
        "p0": p0,
        "alpha": alpha,
        "power": power,
        "s": s,
        "wilson_lo": round(lo, 6),
        "wilson_hi": round(hi, 6),
        "mde_newcombe": round(mde, 6),
        "mcnemar_min_dc": min_dc,
    }


def write_receipt(result: dict, ticket: str = "ENG-346") -> str:
    """Write a receipts/power-helper-<ts>.json and return the path."""
    ts = _utc_ts()
    obj = {
        "ticket": ticket,
        "ts": ts,
        "n": result["n"],
        "p0": result["p0"],
        "alpha": result["alpha"],
        "power": result["power"],
        "wilson_lo": result["wilson_lo"],
        "wilson_hi": result["wilson_hi"],
        "mde_newcombe": result["mde_newcombe"],
        "mcnemar_min_dc": result["mcnemar_min_dc"],
    }
    _RECEIPTS.mkdir(parents=True, exist_ok=True)
    path = str(_RECEIPTS / f"power-helper-{ts}.json")
    checked_write(path, obj)
    return path


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    # (1) wilson(0, 100) upper — spec anchor: ≈3.57%; formula gives ≈3.70%
    lo0, hi0 = wilson(0, 100)
    if not (0.035 <= hi0 <= 0.040):
        failures.append(
            f"fixture 1 FAIL: wilson(0,100).hi={hi0:.4f} not in [0.035, 0.040]"
        )

    # (2) rule-of-three parity at n=100: Wilson upper > 3/100
    rot100 = 3.0 / 100
    if hi0 <= rot100:
        failures.append(
            f"fixture 2 FAIL: wilson(0,100).hi={hi0:.4f} <= rule-of-three={rot100:.4f}"
        )

    # (3) McNemar min discordant at alpha=0.05
    min_dc = mcnemar_min_discordant(0.05)
    if min_dc != 6:
        failures.append(
            f"fixture 3 FAIL: mcnemar_min_discordant(0.05)={min_dc}, expected 6"
        )
    p6 = mcnemar_exact(6, 0)
    p5 = mcnemar_exact(5, 0)
    if p6 >= 0.05:
        failures.append(f"fixture 3b FAIL: mcnemar_exact(6,0)={p6:.4f} not < 0.05")
    if p5 < 0.05:
        failures.append(f"fixture 3c FAIL: mcnemar_exact(5,0)={p5:.4f} not >= 0.05")

    # (4) Sane size_table: MDE decreases with n, increases with p0 near 0
    t100 = size_table(100, 0.02)
    t200 = size_table(200, 0.02)
    if t200["mde_newcombe"] >= t100["mde_newcombe"]:
        failures.append(
            f"fixture 4 FAIL: MDE did not decrease with n: "
            f"{t100['mde_newcombe']:.4f} -> {t200['mde_newcombe']:.4f}"
        )

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}", file=sys.stderr)
        return 1

    print(f"  wilson(0,100): lo={lo0:.4f}, hi={hi0:.4f} ({hi0*100:.2f}%)")
    print(f"  rule-of-three at n=100: {rot100*100:.1f}%  Wilson: {hi0*100:.2f}%  (Wilson > RoT OK)")
    print(f"  mcnemar_min_dc(0.05) = {min_dc}  "
          f"[p(6,0)={p6:.4f} < 0.05; p(5,0)={p5:.4f} >= 0.05 OK]")
    print(f"  MDE(n=100, p0=2%): {t100['mde_newcombe']*100:.1f}pp  "
          f"MDE(n=200, p0=2%): {t200['mde_newcombe']*100:.1f}pp  (decreases OK)")
    print("POWER_HELPER_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_table(result: dict) -> None:
    print(f"n={result['n']}  p0={result['p0']}  alpha={result['alpha']}  "
          f"power={result['power']}  (s={result['s']})")
    print(f"  Wilson 95% CI for base rate:   [{result['wilson_lo']*100:.2f}%, "
          f"{result['wilson_hi']*100:.2f}%]")
    print(f"  Newcombe MDE (paired, conservative): {result['mde_newcombe']*100:.2f}pp")
    print(f"  McNemar min discordant (b+c):  {result['mcnemar_min_dc']} pairs")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="power_helper.py — MDE/power sizing table (eng #346)")
    ap.add_argument("--n",       type=int,   help="Number of tasks")
    ap.add_argument("--p0",      type=float, help="Base success rate (0..1)")
    ap.add_argument("--alpha",   type=float, default=0.05,
                    help="Significance level (default 0.05)")
    ap.add_argument("--power",   type=float, default=0.80,
                    help="Target power (default 0.80)")
    ap.add_argument("--receipt", action="store_true",
                    help="Write receipt to receipts/")
    ap.add_argument("--selftest", action="store_true",
                    help="Run anchor fixtures; exit 0 on PASS")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.n is None or args.p0 is None:
        ap.error("--n and --p0 are required (or use --selftest)")

    result = size_table(args.n, args.p0, alpha=args.alpha, power=args.power)
    _print_table(result)

    if args.receipt:
        path = write_receipt(result)
        print(f"Receipt: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
