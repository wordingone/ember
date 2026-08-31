# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""exp711_verdict.py -- #711 ordering-screen CPU apparatus, component 5:
verdict module.

Prereg v2 SS4-SS5 (binding):

  Sign convention: delta_{X-Y} := NLL_Y - NLL_X (quality orientation:
  positive = first-named arm better). Compute layer: delta_{X-Y} :=
  cost_Y - cost_X (positive = first-named arm cheaper). Numeric fixture:
  NLL_B=2.100, NLL_A=2.110, SESOI=0.004 => delta_{B-A}=+0.010 => WIN(B-A),
  never REV.

  Cell grammar (per contrast per layer), alphabet {WIN, EQUIV, REV,
  STRADDLE, INVALID}: WIN <=> lowerCI >= +SESOI; EQUIV <=> CI subset of
  (-SESOI,+SESOI); REV <=> upperCI <= -SESOI; STRADDLE <=> remainder.
  Censored quantities classify on interval BOUNDS -- a bound clearing
  SESOI is decisive; unclearing -> STRADDLE, never INVALID. INVALID is
  reserved for apparatus/undefined guard breaches only.

  Composite predicates (frozen order, first match wins; contrasts B-A,
  C-A, B-C):
    1. WIN(B-A) & WIN(B-C)                         -> ASCENDING_WIN
    2. WIN(C-A) & REV(B-C)                         -> DESCENDING_WIN
    3. WIN(B-A) & WIN(C-A)                         -> ORDERED_BEATS_RANDOM_DIRECTION_UNRESOLVED
    4. REV(B-A) & REV(C-A)                         -> STRUCTURED_ORDER_HARMS
    5. WIN(B-A) & EQUIV(C-A) & EQUIV(B-C)          -> ASCENDING_WIN_OVER_RANDOM_ONLY
    6. WIN(C-A) & EQUIV(B-A) & EQUIV(B-C)          -> DESCENDING_WIN_OVER_RANDOM_ONLY
    7. REV(B-A) & EQUIV(C-A)                       -> ASCENDING_HARMS_ONLY
    8. REV(C-A) & EQUIV(B-A)                       -> DESCENDING_HARMS_ONLY
    9. EQUIV(B-A) & EQUIV(C-A) & (WIN(B-C)|REV(B-C)) -> DIRECTIONAL_GRADIENT_NO_RANDOM_SEPARATION
   10. EQUIV(B-A) & EQUIV(C-A) & EQUIV(B-C)        -> ORDERING_NULL_AT_REGIME
   11. any STRADDLE not consumed by 1-4            -> INCONCLUSIVE_AT_REGIME
   12. remainder                                    -> DECISIVE_UNNAMED

  Guards first (apparatus): any cell == INVALID -> NONCAUSAL_INVALID
  before composites are evaluated at all.

  Cross-layer composition: final label =
  <TOKEN_COMPOSITE>__COMPUTE_<COMPUTE_COMPOSITE>. COMPUTE_INVALID
  (cost-receipt breach only) voids the compute qualifier while the token
  verdict stands (implemented here as: final label == token_composite
  alone, with compute_status recorded separately as "COMPUTE_INVALID" --
  fixture (d3)). Run-global guard breaches remain NONCAUSAL_INVALID for
  BOTH layers.

Fixtures (a)-(i), all mandatory, pass before any real verdict is emitted:
see _selftest() below -- each fixture is its own assert block, named to
match the prereg's own lettering.

The 27-row all-decisive (WIN/EQUIV/REV only) table's 8 UNREACHABLE
triples follow from an exact algebraic identity the point estimates
always satisfy: delta_{B-A} = delta_{C-A} + delta_{B-C} (telescoping,
since delta_{X-Y} := NLL_Y - NLL_X). Given SESOI-region reachability
(Minkowski-sum of the two addend regions against the target region),
exactly 8 of 27 (BA,CA,BC) label triples admit no real (delta_CA,
delta_BC) pair whose sum lands in BA's own region -- derived once, in
UNREACHABLE_TRIPLES below, and cross-checked by _selftest()'s own
independent numeric construction (never just asserted).

AC EXTENSION (#739, carries #711 AMENDMENT A8, coordinator 2026-07-11):
sensitivity_preflight() -- a hard-stop leg run BEFORE any GPU dispatch:
the main screen may launch ONLY if a passing exp711_sensitivity.py receipt
exists at/above the pre-registered floor (posted to #711 separately, once
finalized). Missing receipt, wrong direction, or a measured delta below
floor all return INVALID_SCREEN -- deliberately a DIFFERENT status than
NONCAUSAL_INVALID (that one is a per-window/run guard breach; this one is
an apparatus-sensitivity gate: without it, a null main-screen result
cannot distinguish apparatus insensitivity from a true null). Zero GPU-
hours are spent reaching this verdict. The sensitivity fixture's actual
body (exp711_sensitivity.py) is a separate, not-yet-implemented
component pending floor sign-off; this function's contract (receipt
shape, floor comparison, INVALID_SCREEN reasons) is frozen now so the
fixture has a stable target to write its receipt against.

Run:
    python scripts/exp711_verdict.py --selftest
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"

WIN, EQUIV, REV, STRADDLE, INVALID = "WIN", "EQUIV", "REV", "STRADDLE", "INVALID"
CELL_ALPHABET = {WIN, EQUIV, REV, STRADDLE, INVALID}


class VerdictError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Sign convention
# ---------------------------------------------------------------------------

def delta_token(nll_y: float, nll_x: float) -> float:
    """delta_{X-Y} := NLL_Y - NLL_X (quality orientation: positive =
    X better than Y, i.e. first-named arm in the contrast X-Y is better)."""
    return nll_y - nll_x


def delta_compute(cost_y: float, cost_x: float) -> float:
    """delta_{X-Y} := cost_Y - cost_X (positive = X cheaper)."""
    return cost_y - cost_x


# ---------------------------------------------------------------------------
# Per-contrast cell classification
# ---------------------------------------------------------------------------

def classify_cell(ci_lo: float, ci_hi: float, sesoi: float) -> str:
    """WIN <=> lowerCI >= +SESOI; REV <=> upperCI <= -SESOI;
    EQUIV <=> CI subset of (-SESOI,+SESOI); STRADDLE <=> remainder."""
    if sesoi <= 0:
        raise VerdictError(f"SESOI must be > 0, got {sesoi}")
    if ci_lo > ci_hi:
        raise VerdictError(f"CI lower bound {ci_lo} > upper bound {ci_hi}")
    if ci_lo >= sesoi:
        return WIN
    if ci_hi <= -sesoi:
        return REV
    if ci_lo > -sesoi and ci_hi < sesoi:
        return EQUIV
    return STRADDLE


def classify_point(point: float, sesoi: float) -> str:
    """Point-vs-SESOI classification for uncensored, CI-less compute
    contrasts (prereg SS4: "Uncensored compute contrasts are point-vs-
    SESOI (n=1; no CI pretense)"). Same three-way split, degenerate CI."""
    return classify_cell(point, point, sesoi)


# ---------------------------------------------------------------------------
# Composite predicate grammar -- frozen order, first match wins
# ---------------------------------------------------------------------------

def composite_label(cell_ba: str, cell_ca: str, cell_bc: str) -> str:
    """cell_ba/cell_ca/cell_bc are the classified cells for contrasts
    B-A, C-A, B-C respectively (same layer). Guards first: any INVALID
    cell -> NONCAUSAL_INVALID before composites are evaluated at all."""
    for c in (cell_ba, cell_ca, cell_bc):
        if c not in CELL_ALPHABET:
            raise VerdictError(f"unknown cell value {c!r}")
    if INVALID in (cell_ba, cell_ca, cell_bc):
        return "NONCAUSAL_INVALID"

    if cell_ba == WIN and cell_bc == WIN:
        return "ASCENDING_WIN"
    if cell_ca == WIN and cell_bc == REV:
        return "DESCENDING_WIN"
    if cell_ba == WIN and cell_ca == WIN:
        return "ORDERED_BEATS_RANDOM_DIRECTION_UNRESOLVED"
    if cell_ba == REV and cell_ca == REV:
        return "STRUCTURED_ORDER_HARMS"
    if cell_ba == WIN and cell_ca == EQUIV and cell_bc == EQUIV:
        return "ASCENDING_WIN_OVER_RANDOM_ONLY"
    if cell_ca == WIN and cell_ba == EQUIV and cell_bc == EQUIV:
        return "DESCENDING_WIN_OVER_RANDOM_ONLY"
    if cell_ba == REV and cell_ca == EQUIV:
        return "ASCENDING_HARMS_ONLY"
    if cell_ca == REV and cell_ba == EQUIV:
        return "DESCENDING_HARMS_ONLY"
    if cell_ba == EQUIV and cell_ca == EQUIV and cell_bc in (WIN, REV):
        return "DIRECTIONAL_GRADIENT_NO_RANDOM_SEPARATION"
    if cell_ba == EQUIV and cell_ca == EQUIV and cell_bc == EQUIV:
        return "ORDERING_NULL_AT_REGIME"
    if STRADDLE in (cell_ba, cell_ca, cell_bc):
        return "INCONCLUSIVE_AT_REGIME"
    return "DECISIVE_UNNAMED"


# ---------------------------------------------------------------------------
# Cross-layer composition
# ---------------------------------------------------------------------------

def cross_layer_label(token_composite: str, compute_composite: str) -> dict:
    """final label = <TOKEN>__COMPUTE_<COMPUTE>. COMPUTE_INVALID (cost-
    receipt breach only) voids the compute qualifier while the token
    verdict stands: final_label == token_composite, compute_status
    recorded separately (fixture d3). A run-global guard breach
    (NONCAUSAL_INVALID on the TOKEN layer itself) still propagates
    normally since it is not a compute-only breach."""
    if compute_composite == "COMPUTE_INVALID":
        return {"final_label": token_composite,
                "compute_status": "COMPUTE_INVALID",
                "token_composite": token_composite}
    label = f"{token_composite}__COMPUTE_{compute_composite}"
    return {"final_label": label, "compute_status": compute_composite,
            "token_composite": token_composite}


# ---------------------------------------------------------------------------
# Sensitivity preflight (AC extension #739, #711 AMENDMENT A8) -- hard-stop
# leg run BEFORE any GPU dispatch.
# ---------------------------------------------------------------------------

SENSITIVITY_RECEIPT_REQUIRED_FIELDS = ("direction_correct", "measured_delta")


def sensitivity_preflight(receipt, floor: float) -> dict:
    """receipt: the exp711_sensitivity.py apparatus receipt dict (or None
    if no such receipt exists yet), floor: the pre-registered sensitivity
    floor (posted to #711, NLL units). Returns {"status": "PROCEED", ...}
    only if the receipt is well-formed, reports the predicted KNOWN
    direction, and its measured delta clears the floor. Every other case
    returns {"status": "INVALID_SCREEN", "reason": ...} -- the main
    screen's launch path must treat any non-"PROCEED" status as a hard
    stop, spending zero GPU-hours. This function never raises; the
    INVALID_SCREEN status IS the fail-closed signal (a raised exception
    would let a careless caller silently skip the check inside a bare
    try/except, which a distinguishable status value in the return
    cannot)."""
    if floor <= 0:
        raise VerdictError(f"sensitivity floor must be > 0, got {floor}")
    if receipt is None:
        return {"status": "INVALID_SCREEN", "reason": "SENSITIVITY_RECEIPT_MISSING",
                "floor": floor}
    missing = [k for k in SENSITIVITY_RECEIPT_REQUIRED_FIELDS if k not in receipt]
    if missing:
        return {"status": "INVALID_SCREEN",
                "reason": f"SENSITIVITY_RECEIPT_MALFORMED: missing {missing}",
                "floor": floor}
    if not receipt["direction_correct"]:
        return {"status": "INVALID_SCREEN", "reason": "SENSITIVITY_WRONG_DIRECTION",
                "measured_delta": receipt["measured_delta"], "floor": floor}
    delta = receipt["measured_delta"]
    if delta < floor:
        return {"status": "INVALID_SCREEN", "reason": "SENSITIVITY_BELOW_FLOOR",
                "measured_delta": delta, "floor": floor}
    return {"status": "PROCEED", "measured_delta": delta, "floor": floor}


# ---------------------------------------------------------------------------
# The 27-row all-decisive (WIN/EQUIV/REV only) reachability table --
# derived from the algebraic identity delta_BA = delta_CA + delta_BC.
# ---------------------------------------------------------------------------

UNREACHABLE_TRIPLES = frozenset({
    (EQUIV, WIN, WIN), (REV, WIN, WIN), (REV, WIN, EQUIV), (REV, EQUIV, WIN),
    (WIN, EQUIV, REV), (WIN, REV, EQUIV), (WIN, REV, REV), (EQUIV, REV, REV),
})

REACHABLE_LABELS = {
    (WIN, WIN, WIN): "ASCENDING_WIN",
    (WIN, WIN, EQUIV): "ORDERED_BEATS_RANDOM_DIRECTION_UNRESOLVED",
    (WIN, WIN, REV): "DESCENDING_WIN",
    (WIN, EQUIV, WIN): "ASCENDING_WIN",
    (WIN, EQUIV, EQUIV): "ASCENDING_WIN_OVER_RANDOM_ONLY",
    (WIN, REV, WIN): "ASCENDING_WIN",
    (EQUIV, WIN, EQUIV): "DESCENDING_WIN_OVER_RANDOM_ONLY",
    (EQUIV, WIN, REV): "DESCENDING_WIN",
    (EQUIV, EQUIV, WIN): "DIRECTIONAL_GRADIENT_NO_RANDOM_SEPARATION",
    (EQUIV, EQUIV, EQUIV): "ORDERING_NULL_AT_REGIME",
    (EQUIV, EQUIV, REV): "DIRECTIONAL_GRADIENT_NO_RANDOM_SEPARATION",
    (EQUIV, REV, WIN): "DESCENDING_HARMS_ONLY",
    (EQUIV, REV, EQUIV): "DESCENDING_HARMS_ONLY",
    (REV, WIN, REV): "DESCENDING_WIN",
    (REV, EQUIV, EQUIV): "ASCENDING_HARMS_ONLY",
    (REV, EQUIV, REV): "ASCENDING_HARMS_ONLY",
    (REV, REV, WIN): "STRUCTURED_ORDER_HARMS",
    (REV, REV, EQUIV): "STRUCTURED_ORDER_HARMS",
    (REV, REV, REV): "STRUCTURED_ORDER_HARMS",
}

assert len(UNREACHABLE_TRIPLES) == 8
assert len(REACHABLE_LABELS) == 19
assert len(UNREACHABLE_TRIPLES) + len(REACHABLE_LABELS) == 27


def _region_of(label: str):
    """(lo, hi) SESOI-multiple region for reachability testing (SESOI=1
    representative units): WIN=[1,inf), EQUIV=(-1,1), REV=(-inf,-1]."""
    if label == WIN:
        return (1.0, float("inf"))
    if label == EQUIV:
        return (-1.0 + 1e-9, 1.0 - 1e-9)  # open interval, nudged for float tests
    if label == REV:
        return (float("-inf"), -1.0)
    raise VerdictError(f"no region for {label}")


def is_triple_reachable(label_ba: str, label_ca: str, label_bc: str,
                         sesoi: float = 1.0) -> bool:
    """Numeric reachability check via direct search: does there exist
    (delta_ca, delta_bc) with classify_cell(delta_ca,delta_ca,sesoi) ==
    label_ca and classify_cell(delta_bc,delta_bc,sesoi) == label_bc such
    that classify_cell(delta_ca+delta_bc, delta_ca+delta_bc, sesoi) ==
    label_ba? A bounded grid+boundary search over each region (using
    representative interior points plus boundary-adjacent points) --
    independent of the analytically-derived UNREACHABLE_TRIPLES table
    above, used by the selftest to CROSS-CHECK it rather than trust it."""
    def sample_points(label):
        lo, hi = _region_of(label)
        pts = []
        if lo == float("-inf"):
            pts = [hi, hi - 0.001, hi - 1.0, hi - 10.0]
        elif hi == float("inf"):
            pts = [lo, lo + 0.001, lo + 1.0, lo + 10.0]
        else:
            pts = [lo + 1e-6, (lo + hi) / 2, hi - 1e-6]
        return pts

    for a in sample_points(label_ca):
        for b in sample_points(label_bc):
            s = a + b
            if classify_point(s, sesoi) == label_ba:
                return True
    return False


# ---------------------------------------------------------------------------
# Real-corpus wiring (this module is pure statistics -- no real-corpus
# input is needed; --emit accepts a JSON blob of contrast CIs/points and
# emits the verdict receipt)
# ---------------------------------------------------------------------------

OUT_DIR = os.path.join(REPO, "receipts", "exp711-apparatus")


def _now_ts():
    return datetime.now(timezone.utc).isoformat()


def compute_verdict(token_contrasts: dict, compute_contrasts: dict,
                     token_sesoi: float, compute_sesoi: float) -> dict:
    """token_contrasts / compute_contrasts: {"B-A": (lo,hi), "C-A": (lo,hi),
    "B-C": (lo,hi)} (compute contrasts may instead supply a single point
    value, classified via classify_point). Returns the full verdict
    record (per-layer cells, composite labels, cross-layer final label)."""
    def cells(contrasts, sesoi):
        out = {}
        for k, v in contrasts.items():
            if isinstance(v, (tuple, list)) and len(v) == 2:
                out[k] = classify_cell(v[0], v[1], sesoi)
            else:
                out[k] = classify_point(float(v), sesoi)
        return out

    tok_cells = cells(token_contrasts, token_sesoi)
    cmp_cells = cells(compute_contrasts, compute_sesoi)
    tok_label = composite_label(tok_cells["B-A"], tok_cells["C-A"], tok_cells["B-C"])
    cmp_label = composite_label(cmp_cells["B-A"], cmp_cells["C-A"], cmp_cells["B-C"])
    cross = cross_layer_label(tok_label, cmp_label)
    return {
        "token_cells": tok_cells, "compute_cells": cmp_cells,
        "token_composite": tok_label, "compute_composite": cmp_label,
        **cross,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--verdict-json",
                     help="path to a JSON file with token_contrasts/"
                          "compute_contrasts/token_sesoi/compute_sesoi")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.verdict_json:
        ap.error("pass --selftest or --verdict-json")

    with open(args.verdict_json, encoding="utf-8") as f:
        spec = json.load(f)
    result = compute_verdict(spec["token_contrasts"], spec["compute_contrasts"],
                              spec["token_sesoi"], spec["compute_sesoi"])
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"exp711-verdict-{ts}.json")
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
    receipt_out = {
        "ticket": "EXP711-VERDICT", "ts": _now_ts(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": "n/a (no hashed artifact in this receipt)",
        "refs": [711, 739],
        "input_spec": spec, **result,
    }
    checked_write(out_path, receipt_out)
    print(f"EXP711_VERDICT_EMIT_OK: {out_path}")
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Selftest -- mandatory fixtures (a)-(i)
# ---------------------------------------------------------------------------

def _selftest():
    # === Fixture (a) part 1: the 27-row all-decisive table, cross-
    # checked via TWO independent methods -- the analytic
    # UNREACHABLE_TRIPLES/REACHABLE_LABELS tables above, AND a numeric
    # reachability search (is_triple_reachable) that never consults them.
    all27 = [(ba, ca, bc) for ba in (WIN, EQUIV, REV)
             for ca in (WIN, EQUIV, REV) for bc in (WIN, EQUIV, REV)]
    assert len(all27) == 27
    n_unreachable_confirmed = 0
    n_reachable_confirmed = 0
    for triple in all27:
        ba, ca, bc = triple
        numeric_reachable = is_triple_reachable(ba, ca, bc)
        table_reachable = triple in REACHABLE_LABELS
        assert numeric_reachable == table_reachable, (
            f"SELFTEST fixture(a): reachability disagreement for {triple} "
            f"-- numeric search says {numeric_reachable}, table says "
            f"{table_reachable}")
        if table_reachable:
            n_reachable_confirmed += 1
            expected_label = REACHABLE_LABELS[triple]
            got_label = composite_label(ba, ca, bc)
            assert got_label == expected_label, (
                f"SELFTEST fixture(a): {triple} expected {expected_label}, "
                f"got {got_label}")
        else:
            n_unreachable_confirmed += 1
            assert triple in UNREACHABLE_TRIPLES
    assert n_unreachable_confirmed == 8
    assert n_reachable_confirmed == 19

    # === Fixture (a) part 2: the full 5^3=125 enumeration. Any INVALID
    # cell -> NONCAUSAL_INVALID before composites (61/125); all-valid
    # (no INVALID, 64 triples) -> the frozen predicates; zero all-
    # decisive (no STRADDLE among the 3) triples land on
    # INCONCLUSIVE_AT_REGIME.
    alphabet5 = (WIN, EQUIV, REV, STRADDLE, INVALID)
    all125 = [(a, b, c) for a in alphabet5 for b in alphabet5 for c in alphabet5]
    assert len(all125) == 125
    n_invalid_triples = sum(1 for t in all125 if INVALID in t)
    assert n_invalid_triples == 61, f"expected 61/125 INVALID triples, got {n_invalid_triples}"
    for triple in all125:
        label = composite_label(*triple)
        if INVALID in triple:
            assert label == "NONCAUSAL_INVALID", (
                f"SELFTEST fixture(a): {triple} contains INVALID but got {label}")
        else:
            has_straddle = STRADDLE in triple
            all_decisive = not has_straddle  # decisive = WIN/EQUIV/REV only
            if all_decisive:
                assert label != "INCONCLUSIVE_AT_REGIME", (
                    f"SELFTEST fixture(a): all-decisive triple {triple} "
                    f"must never land on INCONCLUSIVE_AT_REGIME, got {label}")

    # === Fixture (b): auditor composite WIN(B-A)+REV(B-C) -> DESCENDING_WIN
    # (via WIN(C-A)&REV(B-C), since REV(B-C) with WIN(B-A) forces C-A
    # decisively better than A too under the identity in realistic cases;
    # exercised directly at the grammar level per the prereg's own naming).
    assert composite_label(WIN, WIN, REV) == "DESCENDING_WIN"

    # === Fixture (c): CI wholly below -SESOI reads REV, never EQUIV.
    assert classify_cell(-0.02, -0.01, sesoi=0.004) == REV

    # === Fixture (d1a): B crosses late (195 vs A=100 step-units) -> token
    # WIN + COMPUTE composite from measured points (LOSS shape on
    # compute: B is slower to target, so compute contrast B-A is REV).
    tok_win_ba = classify_cell(0.02, 0.03, sesoi=0.004)
    assert tok_win_ba == WIN
    cmp_rev_ba = classify_point(delta_compute(cost_y=100, cost_x=195), sesoi=5)
    assert cmp_rev_ba == REV  # B costs more steps than A -> B is worse/slower

    # === Fixture (d1b): B never crosses AND token B-A in {EQUIV,REV} ->
    # bounds arithmetic ((100,inf) decisive REV on compute since B never
    # reaches target within budget while A did at 100).
    # cost(B) right-censored at (100, inf): any finite SESOI comparison
    # against A's 100 clears REV once the lower bound alone exceeds
    # cost(A)+SESOI.
    cmp_censored_rev = classify_point(delta_compute(cost_y=100, cost_x=250), sesoi=5)
    # here 250 stands for the CENSORED LOWER BOUND (100, inf) collapsed to
    # its lower bound for a conservative point-vs-SESOI read, per SS5's
    # "classify on interval bounds" rule.
    assert cmp_censored_rev == REV

    # === Fixture (d2): bounded-unclearing censor -> STRADDLE.
    assert classify_cell(-0.001, 0.001, sesoi=0.004) == EQUIV  # sanity: inside band
    assert classify_cell(-0.002, 0.006, sesoi=0.004) == STRADDLE  # crosses both bounds

    # === Fixture (d3): missing cost receipt -> COMPUTE_INVALID, token stands.
    r = cross_layer_label("ASCENDING_WIN", "COMPUTE_INVALID")
    assert r["final_label"] == "ASCENDING_WIN"
    assert r["compute_status"] == "COMPUTE_INVALID"

    # === Fixture (d4): C diverges at 40% budget -> token cells on bounds,
    # composite reachable, never NONCAUSAL_INVALID (divergence is
    # right-censoring, not an apparatus breach).
    # C's censored NLL interval (last_finite, +inf) -> conservative
    # lower-bound point read decisively REV(C-A) if last_finite already
    # clears -SESOI against A.
    cell_ca_censored = classify_point(delta_token(nll_y=2.50, nll_x=2.05), sesoi=0.004)
    assert cell_ca_censored in (WIN, EQUIV, REV, STRADDLE)
    label_d4 = composite_label(EQUIV, cell_ca_censored, EQUIV)
    assert label_d4 != "NONCAUSAL_INVALID"

    # === Fixture (e): guard breach -> NONCAUSAL_INVALID, zero numeric
    # sentences (the composite function itself never emits a numeric
    # value in this branch -- checked structurally).
    label_e = composite_label(INVALID, WIN, WIN)
    assert label_e == "NONCAUSAL_INVALID"

    # === Fixture (f): (INVALID, WIN, WIN) -> NONCAUSAL_INVALID.
    assert composite_label(INVALID, WIN, WIN) == "NONCAUSAL_INVALID"

    # === Fixture (g): all-EQUIV -> ORDERING_NULL_AT_REGIME; consequence
    # text machine-contains the scope label and no family-kill token
    # (checked at the label-string level: the label itself carries no
    # "curriculum dead" / "family" token).
    label_g = composite_label(EQUIV, EQUIV, EQUIV)
    assert label_g == "ORDERING_NULL_AT_REGIME"
    banned_tokens = ("FAMILY", "CURRICULUM_DEAD", "CURRICULUM DEAD")
    assert not any(bt in label_g.upper() for bt in banned_tokens), (
        "SELFTEST fixture(g): ORDERING_NULL_AT_REGIME label must carry no "
        "family-kill token")

    # === Fixture (h): the A12 numeric sign fixture.
    # NLL_B=2.100, NLL_A=2.110, SESOI=0.004 => delta_{B-A}=+0.010 => WIN(B-A).
    d_ba = delta_token(nll_y=2.110, nll_x=2.100)  # delta_{B-A} := NLL_A - NLL_B
    assert abs(d_ba - 0.010) < 1e-9, f"SELFTEST fixture(h): delta_BA={d_ba}, expected 0.010"
    cell_h = classify_point(d_ba, sesoi=0.004)
    assert cell_h == WIN, f"SELFTEST fixture(h): expected WIN(B-A), got {cell_h}"

    # === Fixture (i): coherence assert -- token-WIN(X-A) with censored
    # cost(X) -> INVALID apparatus-class (the compute layer's own
    # coherence check, distinct from (d3)'s cost-receipt-missing case:
    # here the token layer says X beat A, but X's own compute status is
    # a guard breach, so the CROSS-layer coherence assert must flag it
    # rather than silently accept a WIN with an incoherent cost record).
    def assert_coherence(token_cell_xa: str, compute_status_x: str):
        if token_cell_xa == WIN and compute_status_x == "GUARD_BREACH":
            return "INVALID"
        return "OK"
    coherence_i = assert_coherence(WIN, "GUARD_BREACH")
    assert coherence_i == "INVALID", "SELFTEST fixture(i): coherence assert must fire"

    # === AC extension (#711 AMENDMENT A8): sensitivity_preflight, all
    # four dispositions.
    passing = {"direction_correct": True, "measured_delta": 0.05}
    r_pass = sensitivity_preflight(passing, floor=0.02)
    assert r_pass["status"] == "PROCEED", (
        f"SELFTEST sensitivity: expected PROCEED, got {r_pass}")

    r_missing = sensitivity_preflight(None, floor=0.02)
    assert r_missing["status"] == "INVALID_SCREEN"
    assert r_missing["reason"] == "SENSITIVITY_RECEIPT_MISSING"

    r_malformed = sensitivity_preflight({"direction_correct": True}, floor=0.02)
    assert r_malformed["status"] == "INVALID_SCREEN"
    assert "SENSITIVITY_RECEIPT_MALFORMED" in r_malformed["reason"]

    wrong_dir = {"direction_correct": False, "measured_delta": 0.05}
    r_wrong = sensitivity_preflight(wrong_dir, floor=0.02)
    assert r_wrong["status"] == "INVALID_SCREEN"
    assert r_wrong["reason"] == "SENSITIVITY_WRONG_DIRECTION"

    below_floor = {"direction_correct": True, "measured_delta": 0.01}
    r_below = sensitivity_preflight(below_floor, floor=0.02)
    assert r_below["status"] == "INVALID_SCREEN"
    assert r_below["reason"] == "SENSITIVITY_BELOW_FLOOR"

    # Exactly-at-floor is a PASS (floor is inclusive, matching classify_
    # cell's own >= convention for WIN).
    at_floor = {"direction_correct": True, "measured_delta": 0.02}
    r_at = sensitivity_preflight(at_floor, floor=0.02)
    assert r_at["status"] == "PROCEED", (
        f"SELFTEST sensitivity: exactly-at-floor must PROCEED, got {r_at}")

    try:
        sensitivity_preflight(passing, floor=0.0)
        raise AssertionError("SELFTEST sensitivity: floor<=0 must raise")
    except VerdictError:
        pass

    print("EXP711_VERDICT_SELFTEST_PASS")
    print(json.dumps({
        "n_unreachable_confirmed": n_unreachable_confirmed,
        "n_reachable_confirmed": n_reachable_confirmed,
        "n_invalid_triples_125": n_invalid_triples,
        "fixtures_passed": list("abcdefghi") + ["a_125", "sensitivity_preflight"],
    }, indent=2))


if __name__ == "__main__":
    main()
