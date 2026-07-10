#!/usr/bin/env python3
"""f2_placement_sweep.py -- C8 pre-launch obligation O4, placement-sweep half
(issue #629; frozen cure adopted from the independent-audit disposition on
issue #123, "Tighten-only clearance" section, refs #582 #592). CPU-only, zero
deps beyond hashlib/json/math (no numpy/scipy -- same posture as
compute_mde.py and f2_schedule_generator.py).

BACKGROUND (issue #123 comment, section 3 "F2 -- criterion", frozen sweep
procedure): "cheap-rung isoFLOP placement sweep over pre-growth FLOP fraction
phi in {0, 0.05, 0.10, 0.20, 0.40} ... 1 seed per grid point, parabola fit in
(log10 d, loss), valley => phi*". The independent audit found this procedure
under-specified for an executable implementation: "the frozen sweep includes
placement fraction zero and requests a parabola in (log10 d, loss), but does
not define d, its mapping from the fraction grid, or zero handling; no
executable sweep/selection artifact is public" -- and named the exact
obligation: "Define and implement the placement sweep's transform,
zero/boundary behavior, fit degree, seed, tie-breaking, and failed-run
handling."

THIS MODULE closes that gap. Design decisions (all frozen HERE, this commit,
and bound into every sweep receipt so a reviewer can audit them without
re-deriving intent):

TRANSFORM (d)
-------------
    d := phi   (identity map onto the pre-growth FLOP fraction itself; no
    G_stack depth-fit constants are imported -- the audit note on issue #123
    explicitly says those "do not transfer to our width operator and are not
    used". This module reuses only the FORM of an isoFLOP valley-via-
    parabola-fit, not any borrowed constant.)

ZERO HANDLING
-------------
    phi=0 is EXCLUDED from the log10(d)-space quadratic fit (log10(0) is
    undefined) and instead treated as a BOUNDARY CANDIDATE: its measured loss
    is compared directly against the fitted parabola's predicted loss at its
    (possibly-clipped) vertex. If loss(phi=0) <= predicted valley loss,
    phi=0 wins (immediate growth beats any delay, or ties toward it -- see
    TIE-BREAKING). Otherwise the fitted vertex governs.

FIT DEGREE
----------
    2 (a parabola, per the frozen spec text verbatim). Fit via ordinary
    least squares over the log10(d)-space nonzero grid points (closed-form
    normal-equations solve, pure Python -- no numpy dependency).

BOUNDARY BEHAVIOR (fit-domain clipping)
----------------------------------------
    The fitted vertex is clipped to [log10(min usable nonzero phi), log10(max
    usable nonzero phi)] before being converted back to a phi value -- the
    fit is never extrapolated past its own sampled support.

DEGENERATE-FIT FALLBACK
-----------------------
    If the fitted quadratic has a <= 0 (no interior minimum: flat or
    concave-down), OR the normal-equations system is singular (e.g. fewer
    than 3 distinct log10(d) values), the valley is NOT taken from the
    (meaningless) vertex; instead phi* falls back to the argmin of the raw
    measured (nonzero, non-failed) grid points -- ties broken by smaller phi.

SEED
----
    SWEEP_SEED = 20260709 (frozen constant, reusing the SAME literal already
    frozen elsewhere in the C8 fill amendment for exactly this purpose --
    issue #123's F1 bootstrap block pins `rng_seed:20260709`). One seed is
    used per grid point (SEEDS_PER_GRID_POINT = 1, matching "1 seed per grid
    point" verbatim) -- the SAME seed value at every point, so the cheap-
    rung sweep is a single fully-reproducible batch, not 5 independently-
    chosen seeds.

TIE-BREAKING
------------
    Any exact tie (boundary loss == predicted valley loss, to float
    precision) resolves to the SMALLER phi -- earlier growth event, the same
    directional bias the endpoint convention already states ("G_stack H.1:
    one-hop >= gradual"). This is why boundary vs vertex uses `<=` rather
    than strict `<`, and why the degenerate-fit argmin fallback breaks ties
    by (loss, phi) lexicographic order.

FAILED-RUN HANDLING
--------------------
    A grid point with `failed: true` or a missing/NaN `loss` is EXCLUDED
    from the fit. If phi=0 itself failed, the boundary check is skipped
    entirely (falls through to the fitted/fallback candidate). The quadratic
    fit requires >=3 usable nonzero-phi points; fewer raises ValueError
    (fail-closed -- no phi_star is ever guessed from an under-determined
    fit).

ZERO GATED-ARM READS
---------------------
    run_sweep() takes already-measured (phi, loss, seed, failed) records as
    plain arguments -- it performs NO file I/O and never reads a real
    training receipt itself, same posture as
    f2_schedule_generator.generate_schedule().

USAGE
-----
    python f2_placement_sweep.py --selftest
    python f2_placement_sweep.py --commit --input records.json [--receipt-dir DIR]
"""
import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from receipt_write import checked_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

# --- Frozen sweep constants (issue #629 deliverable 3) ---------------------
GRID = (0.0, 0.05, 0.10, 0.20, 0.40)   # issue #123 comment, sec.3, verbatim grid
SWEEP_SEED = 20260709                  # reused literal, issue #123 F1 rng_seed convention
SEEDS_PER_GRID_POINT = 1
FIT_DEGREE = 2

TRANSFORM_TEXT = "d := phi (identity map); fit in (log10(d), loss) over nonzero grid points only"
ZERO_HANDLING = (
    "phi=0 excluded from the log10(d) fit (undefined); treated as a boundary "
    "candidate compared directly against the fitted valley's predicted loss "
    "(<=  -> boundary wins, ties included)."
)
TIE_BREAK_RULE = (
    "exact ties resolve to the SMALLER phi (earlier growth event; matches "
    "the frozen endpoint convention's G_stack H.1 one-hop>=gradual bias)."
)
FAILED_RUN_HANDLING = (
    "a grid point with failed=true or loss None/NaN is excluded from the "
    "fit; if phi=0 failed, the boundary check is skipped; the quadratic fit "
    "requires >=3 usable nonzero-phi points, else ValueError (fail-closed)."
)
DEGENERATE_FIT_FALLBACK = (
    "if the fitted quadratic has a<=0 (no interior minimum) or the normal-"
    "equations system is singular, phi* falls back to the argmin of the raw "
    "measured nonzero usable points, ties broken by (loss, phi)."
)

_MIN_FIT_POINTS = 3
_SINGULAR_EPS = 1e-30


def _det3(m) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _replace_col(m, col_idx, new_col):
    out = [row[:] for row in m]
    for i in range(3):
        out[i][col_idx] = new_col[i]
    return out


def _fit_quadratic(xs, ys):
    """Ordinary least squares y = a*x^2 + b*x + c via the closed-form normal
    equations, solved by Cramer's rule (pure Python, no numpy). Returns
    {"a","b","c"} or None if the 3x3 normal-equations system is singular
    (e.g. all xs identical)."""
    n = float(len(xs))
    s1 = sum(xs)
    s2 = sum(x * x for x in xs)
    s3 = sum(x ** 3 for x in xs)
    s4 = sum(x ** 4 for x in xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2y = sum(x * x * y for x, y in zip(xs, ys))

    A = [[s4, s3, s2], [s3, s2, s1], [s2, s1, n]]
    B = [sx2y, sxy, sy]
    det = _det3(A)
    if abs(det) < _SINGULAR_EPS:
        return None

    a = _det3(_replace_col(A, 0, B)) / det
    b = _det3(_replace_col(A, 1, B)) / det
    c = _det3(_replace_col(A, 2, B)) / det
    return {"a": a, "b": b, "c": c}


def _is_bad(loss, failed) -> bool:
    if failed:
        return True
    if loss is None:
        return True
    if isinstance(loss, float) and math.isnan(loss):
        return True
    return False


def run_sweep(records: list) -> dict:
    """Pure function: a list of {"phi","loss","seed","failed"} measurement
    records at the frozen GRID -> the sweep-selection result (phi_star +
    full provenance of the transform/zero-handling/tie-break/failed-run
    decisions applied). Performs NO file I/O.
    """
    by_phi = {}
    for r in records:
        by_phi[r["phi"]] = r

    missing = [g for g in GRID if g not in by_phi]
    if missing:
        raise ValueError(f"run_sweep: missing grid point(s) {missing}; GRID={GRID}")

    excluded = []
    usable_nonzero = []  # (phi, loss)
    for phi in GRID:
        if phi == 0.0:
            continue
        rec = by_phi[phi]
        loss = rec.get("loss")
        failed = bool(rec.get("failed", False))
        if _is_bad(loss, failed):
            excluded.append(phi)
        else:
            usable_nonzero.append((phi, loss))

    if len(usable_nonzero) < _MIN_FIT_POINTS:
        raise ValueError(
            f"run_sweep: need >={_MIN_FIT_POINTS} usable nonzero-phi points for a "
            f"degree-{FIT_DEGREE} fit, got {len(usable_nonzero)} (excluded: {sorted(excluded)})"
        )

    xs = [math.log10(p) for p, _ in usable_nonzero]
    ys = [loss for _, loss in usable_nonzero]
    fit = _fit_quadratic(xs, ys)

    x_min, x_max = min(xs), max(xs)
    if fit is not None and fit["a"] > 0:
        vertex_x = -fit["b"] / (2.0 * fit["a"])
        clipped_x = min(max(vertex_x, x_min), x_max)
        predicted_loss = fit["a"] * clipped_x ** 2 + fit["b"] * clipped_x + fit["c"]
        candidate_phi = 10 ** clipped_x
        candidate_source = "fit_vertex"
    else:
        best = min(usable_nonzero, key=lambda t: (t[1], t[0]))  # tie -> smaller phi
        candidate_phi = best[0]
        predicted_loss = best[1]
        candidate_source = "argmin_fallback"

    zero_rec = by_phi[0.0]
    zero_loss = zero_rec.get("loss")
    zero_failed = bool(zero_rec.get("failed", False))
    boundary_selected = False
    if not _is_bad(zero_loss, zero_failed) and zero_loss <= predicted_loss:
        phi_star = 0.0
        boundary_selected = True
    else:
        phi_star = candidate_phi

    body = {
        "grid": list(GRID),
        "seed": SWEEP_SEED,
        "seeds_per_grid_point": SEEDS_PER_GRID_POINT,
        "fit_degree": FIT_DEGREE,
        "transform": TRANSFORM_TEXT,
        "per_point_loss": {str(phi): by_phi[phi].get("loss") for phi in GRID},
        "excluded_points": sorted(excluded),
        "fit_coefficients": fit,
        "candidate_source": candidate_source,
        "phi_star": phi_star,
        "boundary_selected": boundary_selected,
        "zero_handling": ZERO_HANDLING,
        "tie_break_rule": TIE_BREAK_RULE,
        "failed_run_handling": FAILED_RUN_HANDLING,
        "degenerate_fit_fallback": DEGENERATE_FIT_FALLBACK,
    }
    canonical = json.dumps(body, sort_keys=True)
    sweep_config_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    body["sweep_config_hash"] = sweep_config_hash
    return body


def commit_sweep(records: list, receipt_dir: str = "receipts/c8-prelaunch"):
    """Write the sweep receipt. Its sweep_config_hash is the "placement-
    sweep receipt hash" bound into the F2 instance closure
    (f2_schedule_generator.instance_closure_body)."""
    body = run_sweep(records)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    receipt = {
        "ticket": "C8-PRELAUNCH-O4-F2-PLACEMENT-SWEEP-COMMIT",
        "ts": ts,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 629,
        "refs": [123, 582],
        **body,
    }
    fname = f"f2-placement-sweep-commit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    os.makedirs(receipt_dir, exist_ok=True)
    out_path = os.path.join(receipt_dir, fname)
    checked_write(out_path, receipt)
    return out_path, receipt


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    def _quad_records(points_by_phi, zero_loss=5.0, zero_failed=False):
        recs = [{"phi": 0.0, "loss": zero_loss, "seed": SWEEP_SEED, "failed": zero_failed}]
        for phi in (0.05, 0.10, 0.20, 0.40):
            entry = points_by_phi.get(phi)
            if entry is None:
                continue
            recs.append({"phi": phi, "loss": entry.get("loss"), "seed": SWEEP_SEED,
                         "failed": entry.get("failed", False)})
        return recs

    def _true_quad_loss(phi):
        return (math.log10(phi) + 1.0) ** 2 + 0.5  # true minimum at phi=0.10

    # --- RED 1: missing grid point must raise ---
    try:
        run_sweep([{"phi": 0.05, "loss": 1.0, "seed": SWEEP_SEED, "failed": False}])
        failures.append("RED1 FAIL: missing grid points should raise ValueError")
    except ValueError:
        pass
    except Exception as e:
        failures.append(f"RED1 FAIL: wrong exception type {type(e).__name__}: {e}")

    # --- RED 2: <3 usable nonzero points must fail closed ---
    recs_toofew = [
        {"phi": 0.0, "loss": 1.0, "seed": SWEEP_SEED, "failed": False},
        {"phi": 0.05, "loss": 1.0, "seed": SWEEP_SEED, "failed": True},
        {"phi": 0.10, "loss": 1.0, "seed": SWEEP_SEED, "failed": True},
        {"phi": 0.20, "loss": 1.0, "seed": SWEEP_SEED, "failed": False},
        {"phi": 0.40, "loss": 1.0, "seed": SWEEP_SEED, "failed": True},
    ]
    try:
        run_sweep(recs_toofew)
        failures.append("RED2 FAIL: <3 usable nonzero points should raise ValueError")
    except ValueError:
        pass
    except Exception as e:
        failures.append(f"RED2 FAIL: wrong exception type {type(e).__name__}: {e}")

    # --- GREEN 1: exact quadratic through 4 nonzero points, boundary loses ---
    pts = {p: {"loss": _true_quad_loss(p)} for p in (0.05, 0.10, 0.20, 0.40)}
    result1 = run_sweep(_quad_records(pts, zero_loss=5.0))
    if abs(result1["phi_star"] - 0.10) > 1e-6:
        failures.append(f"GREEN1 FAIL: phi_star expected ~0.10, got {result1['phi_star']}")
    if result1["boundary_selected"] is not False:
        failures.append("GREEN1 FAIL: boundary should NOT win (5.0 > 0.5 valley loss)")
    if result1["excluded_points"] != []:
        failures.append(f"GREEN1 FAIL: no points should be excluded, got {result1['excluded_points']}")

    # --- GREEN 2: zero boundary strictly dominates ---
    result2 = run_sweep(_quad_records(pts, zero_loss=0.01))
    if result2["phi_star"] != 0.0:
        failures.append(f"GREEN2 FAIL: phi_star expected 0.0, got {result2['phi_star']}")
    if result2["boundary_selected"] is not True:
        failures.append("GREEN2 FAIL: boundary_selected should be True")

    # --- GREEN 3: failed point excluded from fit, valley still recovered ---
    pts3 = {0.05: {"loss": _true_quad_loss(0.05)},
            0.10: {"loss": _true_quad_loss(0.10)},
            0.20: {"loss": _true_quad_loss(0.20)},
            0.40: {"loss": None, "failed": True}}
    result3 = run_sweep(_quad_records(pts3, zero_loss=5.0))
    if result3["excluded_points"] != [0.40]:
        failures.append(f"GREEN3 FAIL: excluded_points expected [0.40], got {result3['excluded_points']}")
    if abs(result3["phi_star"] - 0.10) > 1e-6:
        failures.append(f"GREEN3 FAIL: phi_star expected ~0.10 with one point excluded, got {result3['phi_star']}")

    # --- GREEN 4: deterministic -- two independent calls, identical hash ---
    result4a = run_sweep(_quad_records(pts, zero_loss=5.0))
    result4b = run_sweep(_quad_records(pts, zero_loss=5.0))
    if result4a["sweep_config_hash"] != result4b["sweep_config_hash"]:
        failures.append("GREEN4 FAIL: sweep_config_hash not stable across independent calls")

    # --- GREEN 5: degenerate/flat fit falls back to argmin, tie -> smaller phi ---
    flat_pts = {0.05: {"loss": 1.0}, 0.10: {"loss": 1.0}, 0.20: {"loss": 1.0}, 0.40: {"loss": 1.0}}
    result5 = run_sweep(_quad_records(flat_pts, zero_loss=5.0))
    if result5["candidate_source"] != "argmin_fallback":
        failures.append(f"GREEN5 FAIL: flat loss should trigger argmin_fallback, got {result5['candidate_source']}")
    if result5["phi_star"] != 0.05:
        failures.append(f"GREEN5 FAIL: tie among flat points should resolve to smallest phi 0.05, got {result5['phi_star']}")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("F2_PLACEMENT_SWEEP_SELFTEST_PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description="C8 pre-launch O4: F2 placement-sweep selector.")
    ap.add_argument("--input", help="JSON file: list of {phi,loss,seed,failed} records at the frozen GRID")
    ap.add_argument("--commit", action="store_true", help="write the sweep-selection receipt")
    ap.add_argument("--receipt-dir", default="receipts/c8-prelaunch")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())

    if args.commit:
        if not args.input:
            ap.error("--commit requires --input records.json")
        with open(args.input, "r", encoding="utf-8") as f:
            records = json.load(f)
        out_path, receipt = commit_sweep(records, args.receipt_dir)
        print(json.dumps(receipt, indent=2))
        print(f"F2_PLACEMENT_SWEEP_COMMIT_DONE {out_path}")
        sys.exit(0)

    ap.error("nothing to do: pass --selftest or --commit --input FILE")


if __name__ == "__main__":
    main()
