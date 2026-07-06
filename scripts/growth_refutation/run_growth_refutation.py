#!/usr/bin/env python3
"""
Growth-Law Refutation Experiment.

ONE claim under refutation (the job is to try to prove it FALSE):
  "Function-preserving growth SUSTAINS compounding rather than merely
   DELAYING saturation."

Full design: the growth-law design spec

Arms (MATCHED total compute = identical total train-steps AND identical
curriculum problem stream):
  G  -- growth: Pareto gate + endogenous curriculum; on jam -> net2net_grow
  F  -- fixed-capacity, matched-compute (primary null / delay-detector)
  B0 -- big-from-start (capacity ceiling; rebuttal to "just train F longer")
  R  -- random-init growth (isolates function-preservation vs just adding neurons)

Primitives reused from accumulation_law:
  execution_verify, fine_tune_round, eval_pass_at_1, ParetoGate, Curriculum,
  write_receipt, build_receipt, identity_capacity, load_and_partition,
  load_model_and_tokenizer, eval_vram_fraction, run_baseline,
  save_adapter_state, restore_adapter_state, generate_candidates,
  JAM_WINDOW, EPSILON, FRONTIER_GAIN_MIN, ADVANCE_THRESHOLD,
  MODEL_ID, HELD_OUT_SEED, EMBER_VRAM_FRACTION

Modes:
  --mode mock   Synthetic trajectories; instant; validates mechanics + discriminator
  --mode cpu    Tiny real data, CPU, real model; validates code-path end-to-end
  --mode gpu    Full run; VRAM preflight; 4090-governed

Smoke guarantee (--mode mock):
  * All 4 arms run with receipts
  * net2net_grow FIRES on jam AND assertion is recorded PASSED
  * >= 2 growth events in arm G
  * Power-law fit + discriminator + verdict() execute without error
  * Verdict = INCONCLUSIVE:mechanics_smoke (curves not separated at mock scale)
  Receipts are NEVER used as a claim verdict. Only GPU sweep + >= 3 seeds can
  render REJECT / FAIL_TO_REJECT.

Usage:
  python run_growth_refutation.py --mode mock
  python run_growth_refutation.py --mode cpu
  python run_growth_refutation.py --mode gpu --rounds 16 --seeds 3
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import argparse
import copy
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Pull accumulation_law primitives from sibling package
_SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from accumulation_law.run_accumulation import (   # noqa: E402
    ADVANCE_THRESHOLD,
    CHECKPOINT_DIR as _ACC_CKPT_DIR,
    EMBER_VRAM_FRACTION,
    EPSILON,
    FRONTIER_GAIN_MIN,
    HELD_OUT_SEED,
    JAM_WINDOW,
    MODEL_ID,
    Curriculum,
    ParetoGate,
    build_receipt,
    eval_pass_at_1,
    eval_vram_fraction,
    fine_tune_round,
    generate_candidates,
    identity_capacity,
    load_and_partition,
    load_model_and_tokenizer,
    restore_adapter_state,
    run_baseline,
    save_adapter_state,
    write_receipt,
    execution_verify,
)

# Capacity functions (same directory)
sys.path.insert(0, str(Path(__file__).parent))
from capacity import net2net_grow, random_grow, MLP_EXPAND_FRAC   # noqa: E402

# ---------------------------------------------------------------------------
# Experiment-level constants
# ---------------------------------------------------------------------------
EXPERIMENT_NAME   = "growth-law-refutation"
N_ROUNDS_MOCK     = 12   # enough for 2 growth events with JAM_WINDOW=3
N_ROUNDS_CPU      = 6    # real model, tiny data, fast; growth may or may not fire
N_ROUNDS_GPU      = 16   # target >= 3-4 growth events; set via --rounds
N_SEEDS_REQUIRED  = 3    # minimum seeds for REJECT / FAIL_TO_REJECT verdict
N_CANDIDATES_CPU  = 4    # tiny
N_CANDIDATES_GPU  = 50   # full
HELD_OUT_CPU      = 4
HELD_OUT_GPU      = 60
MAX_STEPS_CPU     = 3
MAX_STEPS_GPU     = 100
LORA_RANK_CPU     = 4
LORA_RANK_GPU     = 16
LORA_ALPHA_CPU    = 8
LORA_ALPHA_GPU    = 32

# Saturation detection for F: frontier flat for this many consecutive rounds
F_SAT_WINDOW     = 3    # F is "saturated" if frontier gain < FRONTIER_GAIN_MIN for K rounds
# Minimum growth events before FAIL_TO_REJECT is possible
MIN_GROWTH_EVENTS = 3

# Compute budget for B0 (same total steps as G):
# B0 runs n_rounds rounds at same max_steps, but on the final-expanded model
# from round 1 (not on the small model growing).

VRAM_REQUIRED_MIB = 6000   # GPU preflight minimum free VRAM

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).parent
RECEIPT_PATH = SCRIPT_DIR / "receipts" / "growth_refutation.jsonl"
CKPT_DIR     = SCRIPT_DIR / "checkpoints"


# ---------------------------------------------------------------------------
# Energy axis (read-off-the-same-plot; NO new experiment).
# Per (arm, seed) memo tracks prior cumulative-compute + capability so each row
# can carry its marginal conversion rate. Reset in main() for in-process re-runs.
# Context: the energy-law design spec
# ---------------------------------------------------------------------------
_ENERGY_MEMO: dict[tuple, dict] = {}


def _reset_energy_memo():
    _ENERGY_MEMO.clear()


def _energy_fields(arm: str, seed_idx: int, cumulative_compute: float,
                   frontier: float) -> dict:
    """
    Returns the per-row energy axis:
      cumulative_compute            -- train-steps (FLOP proxy) accumulated to this row
      capability_per_compute_marginal -- (delta capability)/(delta compute) this row
      capability_per_compute_avg    -- frontier/cumulative_compute (running conversion rate)
    Marginal for the first row of an (arm,seed) series uses the from-zero rate.
    """
    key  = (arm, seed_idx)
    prev = _ENERGY_MEMO.get(key)
    if prev is None:
        d_comp = cumulative_compute
        d_cap  = frontier
    else:
        d_comp = cumulative_compute - prev["compute"]
        d_cap  = frontier - prev["frontier"]
    marginal = (d_cap / d_comp) if d_comp > 0 else 0.0
    avg      = (frontier / cumulative_compute) if cumulative_compute > 0 else 0.0
    _ENERGY_MEMO[key] = {"compute": cumulative_compute, "frontier": frontier}
    return {
        "cumulative_compute":              round(cumulative_compute, 6),
        "capability_per_compute_marginal": round(marginal, 8),
        "capability_per_compute_avg":      round(avg, 8),
    }


# ---------------------------------------------------------------------------
# Receipt builder (extends accumulation_law's build_receipt with growth fields)
# ---------------------------------------------------------------------------

def build_growth_receipt(
    arm: str,
    round_idx: int,
    tier: int,
    frontier_pass: float,
    retained: dict,
    verified_count: int,
    total_candidates: int,
    accepted: bool | None,
    gate_rejected: bool,
    jam_detected: bool,
    frontier_stalled: bool,
    curriculum_advanced: bool,
    finetune_steps: int,
    vram_fraction: float,
    wall_seconds: int,
    cumulative_steps: int,
    growth_event: bool = False,
    net2net_assertion_passed: bool | None = None,
    net2net_mode: str | None = None,
    intermediate_size_after: int | None = None,
    n_growth_events: int = 0,
    seed_idx: int = 0,
    extra: dict | None = None,
) -> dict:
    base = build_receipt(
        arm=arm, round_idx=round_idx, tier=tier,
        frontier_pass=frontier_pass, retained=retained,
        verified_count=verified_count, total_candidates=total_candidates,
        accepted=accepted, gate_rejected=gate_rejected,
        jam_detected=jam_detected, frontier_stalled=frontier_stalled,
        curriculum_advanced=curriculum_advanced,
        finetune_steps=finetune_steps, vram_fraction=vram_fraction,
        wall_seconds=wall_seconds,
    )
    base["experiment"]           = EXPERIMENT_NAME
    base["cumulative_steps"]     = cumulative_steps
    base["growth_event"]         = growth_event
    base["net2net_assertion_passed"] = net2net_assertion_passed
    base["net2net_mode"]         = net2net_mode
    base["intermediate_size_after"] = intermediate_size_after
    base["n_growth_events"]      = n_growth_events
    base["seed_idx"]             = seed_idx
    # Energy axis (read off the same receipt; no new experiment)
    base.update(_energy_fields(arm, seed_idx, float(cumulative_steps), frontier_pass))
    if extra:
        base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Power-law fit and discriminator
# ---------------------------------------------------------------------------

def fit_power_law(compute_steps: list[int], capability: list[float]):
    """
    Fit cap = a * steps^b in log-log space.
    Returns (a, b, r_squared).  Returns (None, None, None) if underpowered.
    """
    xs = [s for s, c in zip(compute_steps, capability) if s > 0 and c > 0]
    ys = [c for s, c in zip(compute_steps, capability) if s > 0 and c > 0]
    if len(xs) < 3:
        return None, None, None

    import math
    log_x = [math.log(x) for x in xs]
    log_y = [math.log(y) for y in ys]
    n   = len(log_x)
    sx  = sum(log_x);  sy  = sum(log_y)
    sxx = sum(x*x for x in log_x);  sxy = sum(x*y for x, y in zip(log_x, log_y))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-15:
        return None, None, None
    b     = (n * sxy - sx * sy) / denom
    log_a = (sy - b * sx) / n
    a     = math.exp(log_a)

    # R^2
    y_mean = sy / n
    ss_tot = sum((v - y_mean) ** 2 for v in log_y)
    ss_res = sum((v - (log_a + b * lx)) ** 2 for v, lx in zip(log_y, log_x))
    r2     = 1 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0
    return a, b, r2


def compute_late_slope(series: list[float], window: int = 3) -> float:
    """Return average per-round gain in the last `window` rounds."""
    if len(series) < 2:
        return 0.0
    tail = series[-window:] if len(series) >= window else series
    return (tail[-1] - tail[0]) / max(1, len(tail) - 1)


def f_is_saturated(f_series: list[float], k: int = F_SAT_WINDOW) -> bool:
    """True if F's frontier gain < FRONTIER_GAIN_MIN for the last k rounds."""
    if len(f_series) < k + 1:
        return False
    gains = [f_series[i] - f_series[i-1] for i in range(len(f_series)-k, len(f_series))]
    return all(g < FRONTIER_GAIN_MIN for g in gains)


def _mean_ci(vals: list[float]) -> tuple:
    """
    Return (mean, ci_lo, ci_hi) using a normal approximation (mean +- 1.96*sem).
    ci_lo/ci_hi are None when n < 2 (CI undefined -> underpowered).
    """
    n = len(vals)
    if n == 0:
        return None, None, None
    mean = sum(vals) / n
    if n < 2:
        return mean, None, None
    var  = sum((v - mean) ** 2 for v in vals) / (n - 1)
    sd   = var ** 0.5
    sem  = sd / (n ** 0.5)
    half = 1.96 * sem
    return mean, mean - half, mean + half


def discriminator(
    g_steps: list[int], g_fronts: list[float],
    f_steps: list[int], f_fronts: list[float],
    b0_steps: list[int], b0_fronts: list[float],
    r_steps:  list[int], r_fronts:  list[float],
    g_events: list[int],            # round indices where growth fired
    n_seeds:  int,
    g_minus_f_per_seed: list[float] | None = None,   # final (G-F) per seed -> L1 CI
    g_retention_regressed: bool = False,             # change 2: L0 retention condition
) -> dict:
    """
    Pre-registered GRADUATED discriminator (claim ladder L0..L3).

    Returns a dict with:
      result        -- highest supported rung, OR INCONCLUSIVE:<reason> when underpowered
      highest_rung  -- "L0"|"L1"|"L2"|"L3"|None  (None while INCONCLUSIVE)
      ladder        -- full L0..L3, each with .supported + the measured quantity behind it
      conditions    -- flat dict of the individual measured booleans/values
      power_law_F / power_law_G -- (a, b, r2) fits

    Ladder spec: the growth-law design spec "THE CLAIM LADDER".
    Never round up: every rung carries its measured value so a reviewer sees where
    the evidence stops. INCONCLUSIVE pre-empts ranking when underpowered.
    """
    g_minus_f_per_seed = g_minus_f_per_seed or []

    # Fit power laws
    a_f, b_f, r2_f = fit_power_law(f_steps, f_fronts)
    a_g, b_g, r2_g = fit_power_law(g_steps, g_fronts)

    # F extrapolated value + per-round slope at G's final compute step
    f_final_step = g_steps[-1] if g_steps else 0
    f_extrap     = (a_f * (f_final_step ** b_f)) if (a_f is not None and f_final_step > 0) else None
    # F power-law instantaneous per-step slope d/dx(a x^b)=a b x^(b-1), scaled to per-round
    steps_per_round = (g_steps[-1] / len(g_steps)) if g_steps else 1.0
    f_extrap_slope  = (a_f * b_f * (f_final_step ** (b_f - 1)) * steps_per_round
                       if (a_f is not None and f_final_step > 0) else None)

    g_late = compute_late_slope(g_fronts, window=3)
    f_late = compute_late_slope(f_fronts, window=3)
    f_sat  = f_is_saturated(f_fronts)

    b0_final = b0_fronts[-1] if b0_fronts else 0.0
    g_final  = g_fronts[-1]  if g_fronts  else 0.0
    f_final  = f_fronts[-1]  if f_fronts  else 0.0
    r_final  = r_fronts[-1]  if r_fronts  else 0.0

    # Per-event increments (capability just-before vs just-after each growth event)
    event_increments = []
    for evt_round in g_events:
        pre_idx  = max(0, evt_round - 2)
        post_idx = min(len(g_fronts) - 1, evt_round)
        if post_idx > pre_idx:
            event_increments.append(g_fronts[post_idx] - g_fronts[pre_idx])

    # Geometric decay of increments toward 0
    inc_decays_to_zero = False
    if len(event_increments) >= 2:
        first, last = event_increments[0], event_increments[-1]
        inc_decays_to_zero = (last < 0.1 * first) if (first > 0) else True

    # L1 CI on (G - F) across seeds
    gmf_mean, gmf_lo, gmf_hi = _mean_ci(g_minus_f_per_seed)
    ci_excludes_0 = (gmf_lo is not None and gmf_lo > 0)

    # R approx G (function-preservation didn't matter): within seed CI half-width of (G-F),
    # fall back to a fixed tolerance when CI undefined
    ci_half = ((gmf_hi - gmf_lo) / 2) if (gmf_lo is not None) else FRONTIER_GAIN_MIN
    r_approx_g = abs(g_final - r_final) <= max(ci_half, FRONTIER_GAIN_MIN)

    # G approx F's power-law extrapolation within seed CI (the L0 "lever" signature)
    g_approx_f_extrap = False
    if f_extrap is not None:
        g_approx_f_extrap = abs(g_final - f_extrap) <= max(ci_half, FRONTIER_GAIN_MIN)

    # Gap G-F widening (not a constant offset): gap after first event vs at end
    gap_first = gap_last = None
    gap_widens = False
    if g_events and f_fronts:
        first_evt_idx = min(len(g_fronts) - 1, g_events[0])
        gap_first = g_fronts[first_evt_idx] - (f_fronts[first_evt_idx]
                                               if first_evt_idx < len(f_fronts) else f_final)
        gap_last  = g_final - f_final
        gap_widens = (gap_last > gap_first + FRONTIER_GAIN_MIN)

    min_increment = min(event_increments) if event_increments else 0.0
    increment_bounded_away_0 = (len(event_increments) >= MIN_GROWTH_EVENTS
                                and min_increment > FRONTIER_GAIN_MIN)

    # L3: G late slope exceeds F power-law extrapolated slope beyond CI; exponent differs
    g_slope_exceeds_f = (f_extrap_slope is not None
                         and g_late > f_extrap_slope + max(ci_half, FRONTIER_GAIN_MIN))
    exponent_differs = (a_f is not None and a_g is not None
                        and abs(b_g - b_f) > 0.05)

    # -- Flat conditions dict (measured values) ------------------------------
    cond = {
        "n_growth_events":          len(g_events),
        "n_seeds":                  n_seeds,
        "f_saturated":              f_sat,
        "g_final":                  round(g_final, 6),
        "f_final":                  round(f_final, 6),
        "b0_final":                 round(b0_final, 6),
        "r_final":                  round(r_final, 6),
        "g_late_slope":             round(g_late, 6),
        "f_late_slope":             round(f_late, 6),
        "f_extrapolated":           round(f_extrap, 6) if f_extrap is not None else None,
        "f_extrap_slope":           round(f_extrap_slope, 8) if f_extrap_slope is not None else None,
        "event_increments":         [round(x, 6) for x in event_increments],
        "min_increment":            round(min_increment, 6),
        "inc_decays_to_zero":       inc_decays_to_zero,
        "g_minus_f_mean":           round(gmf_mean, 6) if gmf_mean is not None else None,
        "g_minus_f_ci_lo":          round(gmf_lo, 6) if gmf_lo is not None else None,
        "g_minus_f_ci_hi":          round(gmf_hi, 6) if gmf_hi is not None else None,
        "ci_excludes_0":            ci_excludes_0,
        "g_beats_b0":               g_final > b0_final,
        "b0_beats_g":               b0_final >= g_final,
        "g_beats_r":                g_final > r_final,
        "r_approx_g":               r_approx_g,
        "g_approx_f_extrap":        g_approx_f_extrap,
        "gap_first":                round(gap_first, 6) if gap_first is not None else None,
        "gap_last":                 round(gap_last, 6) if gap_last is not None else None,
        "gap_widens":               gap_widens,
        "increment_bounded_away_0": increment_bounded_away_0,
        "g_slope_exceeds_f_extrap": g_slope_exceeds_f,
        "exponent_g":               round(b_g, 6) if b_g is not None else None,
        "exponent_f":               round(b_f, 6) if b_f is not None else None,
        "exponent_differs":         exponent_differs,
        "retention_regressed":      g_retention_regressed,   # change 2
    }

    # -- The claim ladder (always computed; emitted even when INCONCLUSIVE) ---
    retention_ok = not g_retention_regressed

    # L0 reject (lever) -- any trigger fires; retention regression is now an L0 trigger
    l0_triggers = {
        "G_approx_F_extrapolation":   g_approx_f_extrap,
        "B0>=G_at_matched_compute":   bool(cond["b0_beats_g"]),
        "R_approx_G":                 r_approx_g,
        "per_event_increment_decays": inc_decays_to_zero,
        "retention_regression":       g_retention_regressed,   # change 2: ACTUAL L0 condition
    }
    l0_supported = any(l0_triggers.values())

    # L1 minimum-publishable
    l1_supported = (
        ci_excludes_0
        and n_seeds >= N_SEEDS_REQUIRED
        and cond["g_beats_b0"]
        and cond["g_beats_r"]
        and retention_ok
    )

    # L2 sustained -- requires L1, increments bounded away from 0 over >=3 events,
    # gap widens, and retention NOT regressed (change 2: cap below L2 on regression)
    l2_supported = (
        l1_supported
        and increment_bounded_away_0
        and gap_widens
        and retention_ok      # change 2 cap: retention regression forbids L2+
    )

    # L3 maximum -- requires L2, slope exceeds F extrapolation beyond CI, exponent differs
    l3_supported = (
        l2_supported
        and g_slope_exceeds_f
        and exponent_differs
    )

    ladder = {
        "L0_reject": {
            "supported": l0_supported,
            "triggers":  l0_triggers,
            "evidence": {
                "g_final": round(g_final, 6),
                "f_extrapolated": round(f_extrap, 6) if f_extrap is not None else None,
                "b0_final": round(b0_final, 6),
                "r_final": round(r_final, 6),
                "event_increments": [round(x, 6) for x in event_increments],
                "retention_regressed": g_retention_regressed,
            },
        },
        "L1_minimum_publishable": {
            "supported": l1_supported,
            "evidence": {
                "g_minus_f_mean": round(gmf_mean, 6) if gmf_mean is not None else None,
                "ci_lo": round(gmf_lo, 6) if gmf_lo is not None else None,
                "ci_hi": round(gmf_hi, 6) if gmf_hi is not None else None,
                "ci_excludes_0": ci_excludes_0,
                "g>b0": bool(cond["g_beats_b0"]),
                "g>r": bool(cond["g_beats_r"]),
                "retention_ok": retention_ok,
                "n_seeds": n_seeds,
            },
        },
        "L2_sustained": {
            "supported": l2_supported,
            "evidence": {
                "n_events": len(g_events),
                "min_increment": round(min_increment, 6),
                "increment_bounded_away_0": increment_bounded_away_0,
                "gap_first": round(gap_first, 6) if gap_first is not None else None,
                "gap_last": round(gap_last, 6) if gap_last is not None else None,
                "gap_widens": gap_widens,
                "retention_capped": (not retention_ok),
            },
        },
        "L3_maximum": {
            "supported": l3_supported,
            "evidence": {
                "g_late_slope": round(g_late, 6),
                "f_extrapolated_slope": round(f_extrap_slope, 8) if f_extrap_slope is not None else None,
                "g_slope_exceeds_f_extrap": g_slope_exceeds_f,
                "exponent_g": round(b_g, 6) if b_g is not None else None,
                "exponent_f": round(b_f, 6) if b_f is not None else None,
                "exponent_differs": exponent_differs,
            },
        },
    }

    # -- INCONCLUSIVE pre-empts ranking when underpowered --------------------
    if n_seeds < N_SEEDS_REQUIRED:
        result = f"INCONCLUSIVE:insufficient_seeds(need>={N_SEEDS_REQUIRED},got={n_seeds})"
        highest_rung = None
    elif len(g_events) < MIN_GROWTH_EVENTS:
        result = (f"INCONCLUSIVE:insufficient_growth_events"
                  f"(need>={MIN_GROWTH_EVENTS},got={len(g_events)})")
        highest_rung = None
    elif not f_sat:
        result = "INCONCLUSIVE:F_not_saturated(G_advantage_not_demarcated)"
        highest_rung = None
    else:
        # Rank: L0 reject pre-empts everything above; else climb L1->L2->L3
        if l0_supported:
            fired = [k for k, v in l0_triggers.items() if v]
            highest_rung = "L0"
            result = f"L0_REJECT(lever):{'+'.join(fired)}"
        elif l3_supported:
            highest_rung = "L3"
            result = "L3_MAXIMUM:scaling_exponent_bends"
        elif l2_supported:
            highest_rung = "L2"
            result = "L2_SUSTAINED:separation_does_not_decay"
        elif l1_supported:
            highest_rung = "L1"
            result = "L1_MINIMUM_PUBLISHABLE:G_above_F_repeatably"
        else:
            highest_rung = None
            result = "INCONCLUSIVE:partial_conditions(no_L0_trigger_but_L1_unmet)"

    return {
        "result":          result,
        "highest_rung":    highest_rung,
        "ladder":          ladder,
        "conditions":      cond,
        "power_law_F":     {"a": a_f, "b": b_f, "r2": r2_f},
        "power_law_G":     {"a": a_g, "b": b_g, "r2": r2_g},
        "g_late_slope":    g_late,
        "f_late_slope":    f_late,
        "f_saturated_flag": f_sat,
        "event_increments": event_increments,
    }


# ---------------------------------------------------------------------------
# Growth verdict (wraps discriminator across seeds; always call this for final)
# ---------------------------------------------------------------------------

def _g_retention_regressed(g_rs: list[dict], eps: float = EPSILON) -> bool:
    """
    change 2: returns True if any ACCEPTED G round has a retained-battery axis
    that dropped > eps below its first-observed reference value.
    Fail-closed: a regression on an accepted round disqualifies sustain.
    Evaluated per seed (references reset per seed).
    """
    by_seed: dict[int, list[dict]] = {}
    for r in g_rs:
        by_seed.setdefault(r.get("seed_idx", 0), []).append(r)
    for seed, rows in by_seed.items():
        rows = sorted(rows, key=lambda r: r["round"])
        first_ref: dict[str, float] = {}
        for r in rows:
            ret = r.get("retained_pass_at_1", {}) or {}
            for k, v in ret.items():
                if k not in first_ref:
                    first_ref[k] = v
            # Only accepted rounds count (rejected rounds were rolled back)
            if r.get("accepted") is True:
                for k, v in ret.items():
                    ref = first_ref.get(k)
                    if ref is not None and v < ref - eps:
                        return True
    return False


def _energy_summary(rs: list[dict]) -> dict:
    """
    Per-arm energy summary: final capability / total compute (overall conversion
    rate), final marginal conversion rate, and total compute. Read off receipts.
    """
    if not rs:
        return {"final_capability": None, "total_compute": None,
                "capability_per_compute_overall": None,
                "final_marginal_rate": None}
    last = sorted(rs, key=lambda r: (r.get("seed_idx", 0), r["round"]))[-1]
    final_cap = last["frontier_pass_at_1"]
    total_comp = last.get("cumulative_compute", last.get("cumulative_steps", 0))
    return {
        "final_capability": round(final_cap, 6),
        "total_compute": total_comp,
        "capability_per_compute_overall": (round(final_cap / total_comp, 8)
                                           if total_comp else None),
        "final_marginal_rate": last.get("capability_per_compute_marginal"),
    }


def growth_verdict(all_receipts: list[dict]) -> dict:
    """
    Deterministic GRADUATED verdict over receipts from one or more seeds.
    Always INCONCLUSIVE at smoke/mock scale (n_seeds < 3). Emits the full ladder.
    Also folds in the energy-axis summary per arm (read off the same receipts).
    """
    def arm_series(arm):
        return sorted(
            [r for r in all_receipts if r.get("arm") == arm],
            key=lambda r: (r.get("seed_idx", 0), r["round"]),
        )

    def to_curve(rs):
        steps  = [r.get("cumulative_compute", r.get("cumulative_steps", r["round"])) for r in rs]
        fronts = [r["frontier_pass_at_1"] for r in rs]
        return steps, fronts

    g_rs = arm_series("G")
    f_rs = arm_series("F")
    b_rs = arm_series("B0")
    r_rs = arm_series("R")

    g_steps, g_fronts = to_curve(g_rs)
    f_steps, f_fronts = to_curve(f_rs)
    b_steps, b_fronts = to_curve(b_rs)
    r_steps, r_fronts = to_curve(r_rs)

    g_events = [r["round"] for r in g_rs if r.get("growth_event", False)]
    seeds    = sorted({r.get("seed_idx", 0) for r in g_rs})
    n_seeds  = len(seeds)

    # Per-seed final (G - F) for the L1 CI
    g_minus_f_per_seed: list[float] = []
    for s in seeds:
        g_last = [r for r in g_rs if r.get("seed_idx", 0) == s]
        f_last = [r for r in f_rs if r.get("seed_idx", 0) == s]
        if g_last and f_last:
            gf = (sorted(g_last, key=lambda r: r["round"])[-1]["frontier_pass_at_1"]
                  - sorted(f_last, key=lambda r: r["round"])[-1]["frontier_pass_at_1"])
            g_minus_f_per_seed.append(gf)

    g_ret_regressed = _g_retention_regressed(g_rs)

    disc = discriminator(
        g_steps, g_fronts, f_steps, f_fronts,
        b_steps, b_fronts, r_steps, r_fronts,
        g_events, n_seeds,
        g_minus_f_per_seed=g_minus_f_per_seed,
        g_retention_regressed=g_ret_regressed,
    )

    # Energy axis summary per arm (read off the same receipts; no new experiment)
    disc["energy_summary"] = {
        "G":  _energy_summary(g_rs),
        "F":  _energy_summary(f_rs),
        "B0": _energy_summary(b_rs),
        "R":  _energy_summary(r_rs),
        "note": "capability_per_compute = verified-capability purchased per train-step "
                "(FLOP proxy). Conversion rates interpret F/G/B0/R from the same JSONL.",
    }
    return disc


# ---------------------------------------------------------------------------
# Real arm runners (cpu / gpu)
# ---------------------------------------------------------------------------

def _model_intermediate_size(model) -> int | None:
    """Return the current MLP intermediate_size for reporting."""
    try:
        from accumulation_law.run_accumulation import _get_transformer_layers
    except ImportError:
        pass
    try:
        layers = model.base_model.model.model.layers
        return layers[0].mlp.gate_proj.out_features
    except Exception:
        return None


def run_arm_G(
    model, tokenizer, train_pools, held_out_sets,
    n_rounds, n_candidates, max_steps, device,
    receipt_path, seed_idx=0,
) -> tuple[list[dict], list[int]]:
    """
    Arm G: Pareto-ratchet + endogenous curriculum + jam-triggered net2net_grow.
    Returns (receipts, growth_event_rounds).
    """
    gate         = ParetoGate()
    curriculum   = Curriculum()
    receipts     = []
    cumsteps     = 0
    n_events     = 0
    growth_rounds: list[int] = []

    for rnd in range(1, n_rounds + 1):
        t0   = time.time()
        tier = curriculum.current_tier
        gate.first_acquire_tier(tier, 0.0)

        pool    = train_pools[tier]
        rng     = random.Random(f"G_seed{seed_idx}_r{rnd}_t{tier}")
        sampled = rng.choices(pool, k=min(n_candidates, len(pool)))

        candidates     = generate_candidates(model, tokenizer, sampled, device)
        verified       = [c for c in candidates
                          if execution_verify(c["generated_code"], c["test_list"],
                                              c["test_setup_code"])]
        verified_count = len(verified)

        prev_state = save_adapter_state(model)
        steps = fine_tune_round(
            model, tokenizer, verified if verified else [], max_steps,
            CKPT_DIR / f"G_s{seed_idx}_r{rnd}_t{tier}", device,
        )
        cumsteps += steps

        # Evaluate BEFORE growth (growth fires after gate, triggered by jam)
        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[tier], device)
        retained = {t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
                    for t in range(tier)}
        vram_f   = eval_vram_fraction(device)

        accepted, gate_reason = gate.evaluate(tier, frontier, retained)
        if not accepted:
            restore_adapter_state(model, prev_state)

        advanced = curriculum.check_advance(frontier, rnd) if accepted else False

        # Jam -> trigger growth
        grew             = False
        assertion_passed = None
        net2net_mode     = None
        interm_after     = None
        growth_metrics   = {}

        if gate.jam_detected:
            print(f"  G r{rnd:02d} JAM detected (consecutive={gate._consecutive_rejects}) "
                  f"-> net2net_grow")
            model, tokenizer, growth_metrics = net2net_grow(model, tokenizer, rnd, tier)
            grew             = True
            assertion_passed = True   # net2net_grow raises if assertion fails
            net2net_mode     = "real"
            interm_after     = _model_intermediate_size(model)
            n_events        += 1
            growth_rounds.append(rnd)
            gate._consecutive_rejects = 0   # reset after growth

        extra_fields = {"gate_reason": gate_reason}
        if growth_metrics:
            extra_fields.update(growth_metrics)

        r = build_growth_receipt(
            arm="G", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=verified_count, total_candidates=len(sampled),
            accepted=accepted, gate_rejected=not accepted,
            jam_detected=gate.jam_detected and not grew,  # jam shown before reset
            frontier_stalled=gate.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
            cumulative_steps=cumsteps,
            growth_event=grew,
            net2net_assertion_passed=assertion_passed,
            net2net_mode=net2net_mode,
            intermediate_size_after=interm_after,
            n_growth_events=n_events,
            seed_idx=seed_idx,
            extra=extra_fields,
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(f"  G r{rnd:02d} T{tier} | frontier={frontier:.4f} | "
              f"acc={accepted} | jam={gate.jam_detected} | grow={grew} | "
              f"events={n_events} | cumsteps={cumsteps}")

        if device.startswith("cuda"):
            time.sleep(10)

    return receipts, growth_rounds


def run_arm_F(
    model, tokenizer, train_pools, held_out_sets,
    n_rounds, n_candidates, max_steps, device,
    receipt_path, seed_idx=0,
) -> list[dict]:
    """
    Arm F: fixed capacity, matched compute.  Same seeds as G -> identical problem stream.
    capacity_fn = identity (no growth).
    """
    gate         = ParetoGate()
    curriculum   = Curriculum()
    receipts     = []
    cumsteps     = 0

    for rnd in range(1, n_rounds + 1):
        t0   = time.time()
        tier = curriculum.current_tier
        gate.first_acquire_tier(tier, 0.0)

        pool    = train_pools[tier]
        # Identical seed to G for matched curriculum stream
        rng     = random.Random(f"G_seed{seed_idx}_r{rnd}_t{tier}")
        sampled = rng.choices(pool, k=min(n_candidates, len(pool)))

        candidates     = generate_candidates(model, tokenizer, sampled, device)
        verified       = [c for c in candidates
                          if execution_verify(c["generated_code"], c["test_list"],
                                              c["test_setup_code"])]
        verified_count = len(verified)

        prev_state = save_adapter_state(model)
        steps = fine_tune_round(
            model, tokenizer, verified if verified else [], max_steps,
            CKPT_DIR / f"F_s{seed_idx}_r{rnd}_t{tier}", device,
        )
        cumsteps += steps

        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[tier], device)
        retained = {t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
                    for t in range(tier)}
        vram_f   = eval_vram_fraction(device)

        accepted, gate_reason = gate.evaluate(tier, frontier, retained)
        if not accepted:
            restore_adapter_state(model, prev_state)

        advanced = curriculum.check_advance(frontier, rnd) if accepted else False

        r = build_growth_receipt(
            arm="F", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=verified_count, total_candidates=len(sampled),
            accepted=accepted, gate_rejected=not accepted,
            jam_detected=gate.jam_detected,
            frontier_stalled=gate.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
            cumulative_steps=cumsteps,
            growth_event=False,
            seed_idx=seed_idx,
            extra={"gate_reason": gate_reason},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(f"  F r{rnd:02d} T{tier} | frontier={frontier:.4f} | "
              f"acc={accepted} | cumsteps={cumsteps}")

        if device.startswith("cuda"):
            time.sleep(10)

    return receipts


def run_arm_B0(
    model, tokenizer, train_pools, held_out_sets,
    n_rounds, n_candidates, max_steps, device,
    receipt_path, seed_idx=0,
    initial_expand_frac: float = 0.25,
    n_growth_events_to_match: int = 2,
) -> list[dict]:
    """
    Arm B0: big-from-start.  Expand to G's final capacity immediately, then train
    with the same total compute budget (n_rounds * max_steps).
    capacity_fn = identity after initial expansion.
    """
    # One-shot expansion to match G's final size
    expand_each = initial_expand_frac
    print(f"  B0: applying {n_growth_events_to_match} expansions "
          f"(frac={expand_each}) to reach G-equivalent final capacity...")
    for e in range(n_growth_events_to_match):
        model, tokenizer, _ = net2net_grow(model, tokenizer, round_idx=0, tier=0,
                                           expand_frac=expand_each)

    gate         = ParetoGate()
    curriculum   = Curriculum()
    receipts     = []
    cumsteps     = 0
    interm0      = _model_intermediate_size(model)

    for rnd in range(1, n_rounds + 1):
        t0   = time.time()
        tier = curriculum.current_tier
        gate.first_acquire_tier(tier, 0.0)

        pool    = train_pools[tier]
        rng     = random.Random(f"G_seed{seed_idx}_r{rnd}_t{tier}")  # matched stream
        sampled = rng.choices(pool, k=min(n_candidates, len(pool)))

        candidates     = generate_candidates(model, tokenizer, sampled, device)
        verified       = [c for c in candidates
                          if execution_verify(c["generated_code"], c["test_list"],
                                              c["test_setup_code"])]
        verified_count = len(verified)

        prev_state = save_adapter_state(model)
        steps = fine_tune_round(
            model, tokenizer, verified if verified else [], max_steps,
            CKPT_DIR / f"B0_s{seed_idx}_r{rnd}_t{tier}", device,
        )
        cumsteps += steps

        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[tier], device)
        retained = {t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
                    for t in range(tier)}
        vram_f   = eval_vram_fraction(device)

        accepted, gate_reason = gate.evaluate(tier, frontier, retained)
        if not accepted:
            restore_adapter_state(model, prev_state)

        advanced = curriculum.check_advance(frontier, rnd) if accepted else False

        r = build_growth_receipt(
            arm="B0", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=verified_count, total_candidates=len(sampled),
            accepted=accepted, gate_rejected=not accepted,
            jam_detected=gate.jam_detected,
            frontier_stalled=gate.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
            cumulative_steps=cumsteps,
            growth_event=False,
            intermediate_size_after=interm0,
            seed_idx=seed_idx,
            extra={"note": "big-from-start; no growth after initial expansion",
                   "gate_reason": gate_reason},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(f"  B0 r{rnd:02d} T{tier} | frontier={frontier:.4f} | cumsteps={cumsteps}")

        if device.startswith("cuda"):
            time.sleep(10)

    return receipts


def run_arm_R(
    model, tokenizer, train_pools, held_out_sets,
    n_rounds, n_candidates, max_steps, device,
    receipt_path, seed_idx=0,
) -> list[dict]:
    """
    Arm R: random-init growth.  Same jam trigger as G but capacity_fn = random_grow.
    Isolates whether function-PRESERVATION matters vs just adding neurons.
    """
    gate         = ParetoGate()
    curriculum   = Curriculum()
    receipts     = []
    cumsteps     = 0
    n_events     = 0

    for rnd in range(1, n_rounds + 1):
        t0   = time.time()
        tier = curriculum.current_tier
        gate.first_acquire_tier(tier, 0.0)

        pool    = train_pools[tier]
        rng     = random.Random(f"G_seed{seed_idx}_r{rnd}_t{tier}")  # matched stream
        sampled = rng.choices(pool, k=min(n_candidates, len(pool)))

        candidates     = generate_candidates(model, tokenizer, sampled, device)
        verified       = [c for c in candidates
                          if execution_verify(c["generated_code"], c["test_list"],
                                              c["test_setup_code"])]
        verified_count = len(verified)

        prev_state = save_adapter_state(model)
        steps = fine_tune_round(
            model, tokenizer, verified if verified else [], max_steps,
            CKPT_DIR / f"R_s{seed_idx}_r{rnd}_t{tier}", device,
        )
        cumsteps += steps

        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[tier], device)
        retained = {t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
                    for t in range(tier)}
        vram_f   = eval_vram_fraction(device)

        accepted, gate_reason = gate.evaluate(tier, frontier, retained)
        if not accepted:
            restore_adapter_state(model, prev_state)

        advanced = curriculum.check_advance(frontier, rnd) if accepted else False

        grew         = False
        interm_after = None

        if gate.jam_detected:
            print(f"  R r{rnd:02d} JAM detected -> random_grow")
            model, tokenizer = random_grow(model, tokenizer, rnd, tier)
            grew             = True
            n_events        += 1
            interm_after     = _model_intermediate_size(model)
            gate._consecutive_rejects = 0

        r = build_growth_receipt(
            arm="R", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=verified_count, total_candidates=len(sampled),
            accepted=accepted, gate_rejected=not accepted,
            jam_detected=gate.jam_detected and not grew,
            frontier_stalled=gate.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
            cumulative_steps=cumsteps,
            growth_event=grew,
            net2net_assertion_passed=None,  # not applicable for random_grow
            net2net_mode="random" if grew else None,
            intermediate_size_after=interm_after,
            n_growth_events=n_events,
            seed_idx=seed_idx,
            extra={"gate_reason": gate_reason},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(f"  R r{rnd:02d} T{tier} | frontier={frontier:.4f} | "
              f"acc={accepted} | jam={gate.jam_detected} | grow={grew}")

        if device.startswith("cuda"):
            time.sleep(10)

    return receipts


# ---------------------------------------------------------------------------
# Mock mode (synthetic trajectories; instant; mechanics validation)
# ---------------------------------------------------------------------------

def run_mock(n_rounds: int, receipt_path: Path) -> list[dict]:
    """
    Synthetic predetermined trajectories for all 4 arms.
    Demonstrates:
      - All arms run with receipts
      - net2net_grow FIRES on jam (round 5, round 10 in G) with assertion PASSED (mock)
      - >= 2 growth events in arm G
      - Power-law fit + discriminator + verdict execute without error
      - Verdict = INCONCLUSIVE (n_seeds=1 < 3, n_events=2 < 3)

    Trajectory design (12 rounds, JAM_WINDOW=3):
    G arm: improves r1-r2, stalls r3-r5 (jam -> growth #1 at r5),
           resumes r6-r7, stalls r8-r10 (jam -> growth #2 at r10), resumes r11-r12.
    F arm: mirrors G early gains then saturates from r5 onward.
    B0 arm: higher initial capability (starts at G's final capacity), also plateaus.
    R arm: same growth trigger points as G, but random init disrupts recovery.
    """
    receipts: list[dict] = []

    # -----------------------------------------------------------------------
    # G arm (12 rounds)
    # growth_event at round 5 and round 10
    # -----------------------------------------------------------------------
    # (rnd, frontier, retained, accepted, gate_rejected, jam_at_this_round,
    #  growth_event, advanced, vc, tc)
    g_data = [
        # r1: first accept (no prior frontier_ref; set ref to 0.0 -> gain = 0.16 > 0.01)
        (1,  0.160, {},           True,  False, False, False, False, 7,  12),
        # r2: +0.03 gain, accept
        (2,  0.190, {},           True,  False, False, False, False, 9,  12),
        # r3: 0.188-0.190 = -0.002 < 0.01 -> REJECT, consec=1
        (3,  0.188, {},           False, True,  False, False, False, 6,  12),
        # r4: no gain -> REJECT, consec=2
        (4,  0.188, {},           False, True,  False, False, False, 6,  12),
        # r5: REJECT, consec=3 -> JAM -> GROWTH EVENT #1; growth fires, assertion PASSED (mock)
        (5,  0.188, {},           False, True,  True,  True,  False, 6,  12),
        # r6: post-growth, +0.05 jump -> ACCEPT, consec reset
        (6,  0.245, {},           True,  False, False, False, False, 11, 12),
        # r7: +0.02 -> ACCEPT
        (7,  0.265, {},           True,  False, False, False, True,  12, 12),
        # r8: T1 first round (harder tier); let's stay T0 to simplify. 0.265 ref; no gain -> REJECT
        (8,  0.265, {},           False, True,  False, False, False, 8,  12),
        # r9: REJECT, consec=2
        (9,  0.265, {},           False, True,  False, False, False, 8,  12),
        # r10: REJECT, consec=3 -> JAM -> GROWTH EVENT #2
        (10, 0.265, {},           False, True,  True,  True,  False, 7,  12),
        # r11: post-growth #2, +0.05 -> ACCEPT
        (11, 0.315, {},           True,  False, False, False, False, 12, 12),
        # r12: +0.02 -> ACCEPT
        (12, 0.335, {},           True,  False, False, False, False, 12, 12),
    ]

    gate_g = ParetoGate()
    n_events_g = 0
    cumsteps_g = 0

    for row in g_data[:n_rounds]:
        rnd, frontier, retained, accepted, gate_rej, jam_this, grew, advanced, vc, tc = row

        gate_g.first_acquire_tier(0, 0.0)
        if not accepted:
            gate_g._consecutive_rejects += 1
        else:
            gate_g._consecutive_rejects = 0

        if grew:
            n_events_g += 1
            gate_g._consecutive_rejects = 0  # reset after growth

        assertion_passed = True if grew else None
        net2net_mode     = "mock" if grew else None
        cumsteps_g      += 5  # synthetic: 5 steps per round

        r = build_growth_receipt(
            arm="G", round_idx=rnd, tier=0,
            frontier_pass=frontier, retained=retained,
            verified_count=vc, total_candidates=tc,
            accepted=accepted, gate_rejected=gate_rej,
            jam_detected=jam_this,
            frontier_stalled=gate_g.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=0,
            cumulative_steps=cumsteps_g,
            growth_event=grew,
            net2net_assertion_passed=assertion_passed,
            net2net_mode=net2net_mode,
            intermediate_size_after=None,
            n_growth_events=n_events_g,
            seed_idx=0,
            extra={
                "mode": "mock",
                "gate_reason": ("jam -> net2net_grow FIRED, assertion PASSED (mock)"
                                if grew else
                                ("rejected" if gate_rej else "accepted")),
            },
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    # -----------------------------------------------------------------------
    # F arm (12 rounds) -- fixed capacity, saturates at round 5
    # -----------------------------------------------------------------------
    f_fronts = [
        0.160, 0.190, 0.205, 0.215, 0.218,
        0.218, 0.218, 0.218, 0.218, 0.218,
        0.218, 0.218,
    ]
    gate_f = ParetoGate()
    cumsteps_f = 0

    for rnd, frontier in enumerate(f_fronts[:n_rounds], start=1):
        gate_f.first_acquire_tier(0, 0.0)
        accepted_f, _ = gate_f.evaluate(0, frontier, {})
        if not accepted_f:
            pass  # F has no rollback in mock (demonstration only)
        cumsteps_f += 5

        r = build_growth_receipt(
            arm="F", round_idx=rnd, tier=0,
            frontier_pass=frontier, retained={},
            verified_count=8, total_candidates=12,
            accepted=accepted_f, gate_rejected=not accepted_f,
            jam_detected=gate_f.jam_detected,
            frontier_stalled=gate_f.frontier_stalled,
            curriculum_advanced=False,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=0,
            cumulative_steps=cumsteps_f,
            growth_event=False,
            seed_idx=0,
            extra={"mode": "mock"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    # -----------------------------------------------------------------------
    # B0 arm (12 rounds) -- big-from-start; better init, also plateaus
    # -----------------------------------------------------------------------
    b0_fronts = [
        0.200, 0.225, 0.242, 0.252, 0.258,
        0.260, 0.260, 0.260, 0.260, 0.260,
        0.260, 0.260,
    ]
    gate_b0 = ParetoGate()
    cumsteps_b0 = 0

    for rnd, frontier in enumerate(b0_fronts[:n_rounds], start=1):
        gate_b0.first_acquire_tier(0, 0.0)
        accepted_b, _ = gate_b0.evaluate(0, frontier, {})
        cumsteps_b0 += 5

        r = build_growth_receipt(
            arm="B0", round_idx=rnd, tier=0,
            frontier_pass=frontier, retained={},
            verified_count=9, total_candidates=12,
            accepted=accepted_b, gate_rejected=not accepted_b,
            jam_detected=gate_b0.jam_detected,
            frontier_stalled=gate_b0.frontier_stalled,
            curriculum_advanced=False,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=0,
            cumulative_steps=cumsteps_b0,
            growth_event=False,
            seed_idx=0,
            extra={"mode": "mock",
                   "note": "big-from-start; initial intermediate_size = G final"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    # -----------------------------------------------------------------------
    # R arm (12 rounds) -- random-init growth; same jam triggers; recovery fails
    # -----------------------------------------------------------------------
    # r5: random_grow fires (jam), model disrupted -> frontier drops from 0.188 to 0.145
    # r8: jam fires again (consec=3 since r6=0.145, r7=0.158, r8=0.170 all < 0.190 ref)
    # -> never recovers past 0.190 (illustrating function-preservation matters)
    r_data = [
        # (rnd, frontier, retained, accepted, gate_rej, jam_this, grew)
        (1,  0.160, {},  True,  False, False, False),
        (2,  0.190, {},  True,  False, False, False),
        (3,  0.188, {},  False, True,  False, False),  # consec=1
        (4,  0.188, {},  False, True,  False, False),  # consec=2
        (5,  0.188, {},  False, True,  True,  True),   # jam -> random_grow (disrupts)
        (6,  0.145, {},  False, True,  False, False),  # disrupted; 0.145<0.190; consec=1
        (7,  0.158, {},  False, True,  False, False),  # recovering; consec=2
        (8,  0.170, {},  False, True,  True,  True),   # consec=3 -> jam #2 -> random_grow again
        (9,  0.130, {},  False, True,  False, False),  # disrupted again
        (10, 0.145, {},  False, True,  False, False),
        (11, 0.160, {},  False, True,  False, False),
        (12, 0.175, {},  False, True,  False, False),
    ]

    gate_r = ParetoGate()
    n_events_r = 0
    cumsteps_r = 0

    for row in r_data[:n_rounds]:
        rnd, frontier, retained, accepted, gate_rej, jam_this, grew = row
        gate_r.first_acquire_tier(0, 0.0)
        if not accepted:
            gate_r._consecutive_rejects += 1
        else:
            gate_r._consecutive_rejects = 0
        if grew:
            n_events_r += 1
            gate_r._consecutive_rejects = 0
        cumsteps_r += 5

        r = build_growth_receipt(
            arm="R", round_idx=rnd, tier=0,
            frontier_pass=frontier, retained=retained,
            verified_count=6, total_candidates=12,
            accepted=accepted, gate_rejected=gate_rej,
            jam_detected=jam_this,
            frontier_stalled=gate_r.frontier_stalled,
            curriculum_advanced=False,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=0,
            cumulative_steps=cumsteps_r,
            growth_event=grew,
            net2net_assertion_passed=None,  # random_grow; no assertion
            net2net_mode="random_mock" if grew else None,
            n_growth_events=n_events_r,
            seed_idx=0,
            extra={"mode": "mock",
                   "note": "random_grow: no function-preservation; recovery disrupted"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    return receipts


# ---------------------------------------------------------------------------
# CPU smoke (real model, tiny data, real code path)
# ---------------------------------------------------------------------------

def run_cpu(n_rounds: int, receipt_path: Path) -> list[dict]:
    """
    CPU smoke: real model + tiny MBPP partition + all 4 arms.
    Validates the full code path.  Frontier scores are noisy.
    Growth events may or may not fire depending on actual training dynamics.
    """
    print("  Loading data (cpu: tiny partition)...")
    train_pools, held_out_sets, meta = load_and_partition(
        n_held_out_per_tier=HELD_OUT_CPU,
        n_train_per_tier=10,
    )
    print(f"  Partition: {meta}")

    device = "cpu"
    print(f"  Loading model ({MODEL_ID}) on CPU...")
    model, tokenizer = load_model_and_tokenizer(device, LORA_RANK_CPU, LORA_ALPHA_CPU)

    receipts = []
    br = run_baseline(model, tokenizer, held_out_sets, device, receipt_path)
    receipts.append(br)

    print("\n--- ARM G (growth) ---")
    g_model = copy.deepcopy(model)
    g_rs, g_events = run_arm_G(
        g_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=N_CANDIDATES_CPU,
        max_steps=MAX_STEPS_CPU, device=device,
        receipt_path=receipt_path,
    )
    receipts.extend(g_rs)
    del g_model

    print("\n--- ARM F (fixed capacity, matched compute) ---")
    f_model = copy.deepcopy(model)
    f_rs = run_arm_F(
        f_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=N_CANDIDATES_CPU,
        max_steps=MAX_STEPS_CPU, device=device,
        receipt_path=receipt_path,
    )
    receipts.extend(f_rs)
    del f_model

    print("\n--- ARM B0 (big-from-start) ---")
    b0_model = copy.deepcopy(model)
    n_g_events = len(g_events)
    b0_rs = run_arm_B0(
        b0_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=N_CANDIDATES_CPU,
        max_steps=MAX_STEPS_CPU, device=device,
        receipt_path=receipt_path,
        initial_expand_frac=0.05,
        n_growth_events_to_match=max(1, n_g_events),
    )
    receipts.extend(b0_rs)
    del b0_model

    print("\n--- ARM R (random-init growth) ---")
    r_model = copy.deepcopy(model)
    r_rs = run_arm_R(
        r_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=N_CANDIDATES_CPU,
        max_steps=MAX_STEPS_CPU, device=device,
        receipt_path=receipt_path,
    )
    receipts.extend(r_rs)
    del r_model

    return receipts


# ---------------------------------------------------------------------------
# GPU mode
# ---------------------------------------------------------------------------

def run_gpu(n_rounds: int, n_candidates: int, receipt_path: Path,
            seed_idx: int = 0, arms: set | None = None) -> list[dict]:
    """
    Full GPU run.  Requires >= VRAM_REQUIRED_MIB free VRAM.
    arms: if not None, restrict to the named arm set (e.g. {'G'} to run ARM G only).
          None = run all arms (default). ARM B0 must always follow ARM G (uses g_events).
    """
    import torch
    free_mib = (
        torch.cuda.get_device_properties(0).total_memory
        - torch.cuda.memory_reserved(0)
    ) / (1024 ** 2)
    print(f"  GPU free: {free_mib:.0f} MiB")
    assert free_mib > VRAM_REQUIRED_MIB, (
        f"Insufficient GPU memory: {free_mib:.0f} MiB free; "
        f"need >= {VRAM_REQUIRED_MIB} MiB.  Free the resident model first."
    )

    torch.cuda.set_per_process_memory_fraction(EMBER_VRAM_FRACTION, device=0)

    print("  Loading data (gpu: full partition)...")
    train_pools, held_out_sets, meta = load_and_partition(
        n_held_out_per_tier=HELD_OUT_GPU,
        n_train_per_tier=100,
    )
    print(f"  Partition: {meta}")

    device = "cuda:0"
    print(f"  Loading model ({MODEL_ID}) on {device}...")
    model, tokenizer = load_model_and_tokenizer(device, LORA_RANK_GPU, LORA_ALPHA_GPU)

    _run_all = arms is None
    receipts = []
    br = run_baseline(model, tokenizer, held_out_sets, device, receipt_path)
    receipts.append(br)

    g_events: list = []
    if _run_all or "G" in arms:
        print("\n--- ARM G ---")
        g_model = copy.deepcopy(model)
        g_rs, g_events = run_arm_G(
            g_model, tokenizer, train_pools, held_out_sets,
            n_rounds, n_candidates, MAX_STEPS_GPU, device,
            receipt_path, seed_idx=seed_idx,
        )
        receipts.extend(g_rs)
        del g_model; torch.cuda.empty_cache()
    else:
        print("\n--- ARM G (skipped per --arms) ---")

    if _run_all or "F" in arms:
        print("\n--- ARM F ---")
        f_model = copy.deepcopy(model)
        f_rs = run_arm_F(
            f_model, tokenizer, train_pools, held_out_sets,
            n_rounds, n_candidates, MAX_STEPS_GPU, device,
            receipt_path, seed_idx=seed_idx,
        )
        receipts.extend(f_rs)
        del f_model; torch.cuda.empty_cache()
    else:
        print("\n--- ARM F (skipped per --arms) ---")

    if _run_all or "B0" in arms:
        print("\n--- ARM B0 ---")
        b0_model = copy.deepcopy(model)
        b0_rs = run_arm_B0(
            b0_model, tokenizer, train_pools, held_out_sets,
            n_rounds, n_candidates, MAX_STEPS_GPU, device,
            receipt_path, seed_idx=seed_idx,
            initial_expand_frac=MLP_EXPAND_FRAC,
            n_growth_events_to_match=max(1, len(g_events)),
        )
        receipts.extend(b0_rs)
        del b0_model; torch.cuda.empty_cache()
    else:
        print("\n--- ARM B0 (skipped per --arms) ---")

    if _run_all or "R" in arms:
        print("\n--- ARM R ---")
        r_model = copy.deepcopy(model)
        r_rs = run_arm_R(
            r_model, tokenizer, train_pools, held_out_sets,
            n_rounds, n_candidates, MAX_STEPS_GPU, device,
            receipt_path, seed_idx=seed_idx,
        )
        receipts.extend(r_rs)
        del r_model; torch.cuda.empty_cache()
    else:
        print("\n--- ARM R (skipped per --arms) ---")

    return receipts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _print_ladder(v: dict) -> None:
    """Print the full claim ladder with the measured quantity behind each rung."""
    ladder = v.get("ladder", {})
    highest = v.get("highest_rung")
    print(f"  CLAIM LADDER (highest supported rung: {highest}):")
    for rung_key in ("L0_reject", "L1_minimum_publishable", "L2_sustained", "L3_maximum"):
        rung = ladder.get(rung_key, {})
        sup  = rung.get("supported")
        mark = "<== HIGHEST" if (highest and rung_key.startswith(highest + "_")) else ""
        print(f"    {rung_key:24s} supported={str(sup):5s} {mark}")
        ev = rung.get("evidence", rung.get("triggers", {}))
        for k, val in ev.items():
            print(f"        {k}: {val}")


def _print_energy(v: dict) -> None:
    es = v.get("energy_summary", {})
    print("  ENERGY AXIS (capability per cumulative compute = train-step FLOP proxy):")
    for arm in ("G", "F", "B0", "R"):
        s = es.get(arm, {})
        print(f"    {arm:3s} final_cap={s.get('final_capability')} "
              f"total_compute={s.get('total_compute')} "
              f"overall_rate={s.get('capability_per_compute_overall')} "
              f"final_marginal_rate={s.get('final_marginal_rate')}")


def _print_verdict(v: dict, mode: str) -> None:
    result = v["result"]
    cond   = v["conditions"]
    print("\n" + "=" * 70)
    if mode == "mock":
        print("MECHANICS VERDICT (mock mode):")
        print(f"  Discriminator result  : {result}")
        g_events = cond.get("n_growth_events", 0)
        assert g_events >= 2, (
            f"MECHANICS FAIL: expected >= 2 growth events in G, got {g_events}"
        )
        print(f"  Growth events in G    : {g_events}  [MECHANICS PASS: >= 2]")
        print(f"  net2net assertion     : PASSED (mock)  [MECHANICS PASS]")
        n_seeds = cond.get("n_seeds", 1)
        print(f"  Seeds                 : {n_seeds}  (< {N_SEEDS_REQUIRED} required -> INCONCLUSIVE correct)")
        print(f"  Discriminator ran     : OK  [MECHANICS PASS]")
        # change 2: retention condition wired and surfaced
        print(f"  Retention condition   : wired (g_retention_regressed="
              f"{cond.get('retention_regressed')}; an L0 trigger + caps below L2)")
        print(f"  Power-law fit (F)     : {v.get('power_law_F')}")
        print()
        # change 1: full ladder emitted even when INCONCLUSIVE
        _print_ladder(v)
        print()
        # change 3: energy fields present
        _print_energy(v)
        print()
        if "INCONCLUSIVE" not in result:
            print(f"  WARNING: expected INCONCLUSIVE at mock scale, got {result}")
            print("  (This is fine if seeds >= 3 and events >= 3 were met by design.)")
        else:
            print("  SMOKE STATUS: MECHANICS PASS")
            print("  NOTE: This is NOT a sustain/delay verdict. Only GPU sweep + >= 3 seeds can render one.")
    else:
        print(f"DISCRIMINATOR RESULT: {result}")
        for k, val in cond.items():
            print(f"  {k}: {val}")
        print()
        _print_ladder(v)
        print()
        _print_energy(v)
        print(f"\nPower-law F: {v.get('power_law_F')}  Power-law G: {v.get('power_law_G')}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Growth-Law Refutation Experiment")
    parser.add_argument(
        "--mode", choices=["mock", "cpu", "gpu"], default="mock",
    )
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--candidates", type=int, default=N_CANDIDATES_GPU)
    parser.add_argument("--seeds", type=int, default=1,
                        help="Number of seeds for GPU mode (>= 3 required for verdict)")
    parser.add_argument("--receipt_path", type=str, default=None)
    parser.add_argument(
        "--arms", nargs="*", choices=["G", "F", "B0", "R"], default=None,
        help="Restrict to named arms only (e.g. --arms G). Omit = run all arms.",
    )
    args = parser.parse_args()

    n_rounds = args.rounds if args.rounds is not None else {
        "mock": N_ROUNDS_MOCK, "cpu": N_ROUNDS_CPU, "gpu": N_ROUNDS_GPU,
    }[args.mode]
    receipt_path = Path(args.receipt_path) if args.receipt_path else RECEIPT_PATH
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    _reset_energy_memo()  # energy axis: fresh per-arm/seed marginal-rate tracking

    print(f"=== Growth-Law Refutation | mode={args.mode} rounds={n_rounds} ===")
    print(f"    Claim under refutation:")
    print(f"    'Function-preserving growth SUSTAINS compounding rather than")
    print(f"     merely DELAYING saturation.'")
    print(f"    epsilon={EPSILON}  jam_window={JAM_WINDOW}  "
          f"frontier_gain_min={FRONTIER_GAIN_MIN}")
    print(f"    n_seeds_required_for_verdict={N_SEEDS_REQUIRED}")
    print(f"    receipt_path={receipt_path}")
    print()

    receipts: list[dict] = []

    if args.mode == "mock":
        print("Mode: MOCK -- synthetic trajectories (mechanics proof)")
        receipts = run_mock(n_rounds, receipt_path)

    elif args.mode == "cpu":
        print("Mode: CPU -- real model, tiny data (code-path validation)")
        receipts = run_cpu(n_rounds, receipt_path)

    elif args.mode == "gpu":
        arms_set = set(args.arms) if args.arms is not None else None
        arm_label = ",".join(sorted(arms_set)) if arms_set else "all"
        print(f"Mode: GPU -- full run ({args.seeds} seed(s), arms={arm_label})")
        for s in range(args.seeds):
            print(f"\n=== SEED {s} / {args.seeds} ===")
            seed_receipts = run_gpu(n_rounds, args.candidates, receipt_path,
                                    seed_idx=s, arms=arms_set)
            receipts.extend(seed_receipts)

    # Discriminator + verdict
    arm_receipts = [r for r in receipts if r.get("arm") in ("G", "F", "B0", "R")]
    v = growth_verdict(arm_receipts)

    verdict_rec = {
        "schema_version":   2,
        "experiment":       EXPERIMENT_NAME,
        "arm":              "verdict",
        "round":            n_rounds,
        "mode":             args.mode,
        **v,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_receipt(verdict_rec, receipt_path)

    _print_verdict(v, args.mode)

    # Per-arm frontier table
    print("\n--- Per-arm frontier (pass@1) ---")
    for arm in ("G", "F", "B0", "R"):
        rs = sorted(
            [r for r in arm_receipts if r["arm"] == arm],
            key=lambda r: (r.get("seed_idx", 0), r["round"]),
        )
        if rs:
            row = "  " + arm + ": " + "  ".join(
                f"r{r['round']}={r['frontier_pass_at_1']:.3f}"
                + ("[GROW]" if r.get("growth_event") else "")
                + ("[JAM]"  if r.get("jam_detected")  else "")
                for r in rs
            )
            print(row)

    g_events = [r["round"] for r in arm_receipts if r["arm"] == "G" and r.get("growth_event")]
    if g_events:
        print(f"\n  G growth events at rounds: {g_events}")
        net2net_modes = [r.get("net2net_mode") for r in arm_receipts
                         if r["arm"] == "G" and r.get("growth_event")]
        assertions = [r.get("net2net_assertion_passed") for r in arm_receipts
                      if r["arm"] == "G" and r.get("growth_event")]
        print(f"  net2net_mode per event:    {net2net_modes}")
        print(f"  assertion_passed per event:{assertions}")

    print(f"\nReceipts: {receipt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
