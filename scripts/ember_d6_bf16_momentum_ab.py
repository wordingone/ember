#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_d6_bf16_momentum_ab.py — D6 VRAM-route pricing A/B (issue #29,
docs/domains/governance/spec/c-scale-s1-growth-chain-DRAFT.md §9 D6).

D6 (quoted in full): "VRAM route: reduced-precision optimizer state (bf16
momentum) is the single authorized route for rung 2+, priced by receipt
BEFORE rung-2 open; host-RAM streaming is the registered fallback;
parameter-efficient deltas are BANNED for S1 pretrain... The pricing
obligation: before rung 2 opens, a receipted A/B at the CURRENT shape
(718.3M, where both arms fit comfortably) proving bf16-momentum loss-
trajectory equivalence under protocol-v2-style conjuncts (max-abs delta
bound at bf16 granularity + trajectory equality + an optimizer-state-health
check), then the same guard re-run as a smoke at each rung before its
stabilization segment counts. If the priced route still cannot fit a rung,
D2's fallback fires for that rung."

ARM A (production optimizer AS-IS, ts.build_split_optimizer UNMODIFIED) vs
ARM B (momentum states forced bf16 via a post-.step() downcast hook — no
production code touched) — SAME model-init seed, SAME synthetic batch
sequence (dedicated Generator, decoupled from the model-init seed), at the
CURRENT landed shape (intermediate_size=8192, 718,316,544 params — the
cbase-grow-live-live-20260703T053225Z.json landed point, NOT the module's
stale intermediate=4096 default).

HONEST PRE-FLIGHT FINDING (measured on CPU, this file's own --selftest,
zero torch.cuda.* calls) — read before assuming what "arm A" naturally is:
this repo's ENTIRE production model is `.to(torch.bfloat16)` with no
autocast / GradScaler / fp32-master-weight copy anywhere
(timeshare_pretrain.py build_v0_model / build_split_optimizer / _muon_class
— read directly, not assumed). torch.optim.AdamW's and _Muon's own state
init (`torch.zeros_like(g)` / `torch.zeros_like(p)`) inherits whatever
dtype the gradient/parameter already is — bfloat16 here, since nothing
promotes to fp32 anywhere in the training step. Verified empirically (CPU,
no GPU, this file's --selftest step 5): a bf16 torch.nn.Linear + a plain
torch.optim.AdamW step already produces bf16 exp_avg/exp_avg_sq; the same
holds for _Muon's momentum_buffer by the identical zeros_like(g) mechanism.
So ARM A's "production optimizer as-is" measured state dtype is ALREADY
bfloat16 — NOT the fp32-momentum convention this dossier's own §3.2/§3.3
VRAM-feasibility table assumes (8 B/param Muon = 2 bf16 weight + 2 bf16
grad + 4 FP32 momentum; 16 B/param AdamW = bf16 weight/grad + fp32 master +
fp32 m + fp32 v). This is a genuine, previously-unflagged discrepancy
between that DESIGN-INTENT planning convention and the AS-CODED reality.
Consequence, stated plainly: if arm A measures bf16-native (this file
measures it every run, never assumes either direction), arm A and arm B
are bit-identical by construction — the downcast hook is a no-op on an
already-bf16 tensor — so the conjuncts trivially pass at ~zero delta, and
the REAL VRAM headroom at every rung is BETTER than spec §3.3's table
computed (that table priced 4 B/param Muon momentum; measured reality is
2 B/param, since it is already bf16). Every receipt this file writes
carries the measured dtype fields regardless of which way the measurement
turns out — this docstring is evidence, not a substitute for the receipt.

Conjuncts (protocol-v2-style, mirroring ember_ceff_composition_ab.py's own
quality_guard / ns5_equiv machinery — read directly, thresholds reused
literally where the same question is being asked, never reimplemented):
  (a) max-abs weight-delta bound at bf16 granularity: after the TIMED
      window, for every model parameter, |W_A - W_B| / max(|W_A|.max(), eps)
      — the GLOBAL max of that ratio across all params must be
      <= WEIGHT_DELTA_REL_TOL_BF16 = 7.8e-3 (== ember_ceff_composition_ab.py
      NS5_EQUIV_TOL_BF16 — "2x bf16 unit-scale eps", identical derivation,
      reused literally: both are "how far can two representations diverge
      before it is more than bf16's own rounding").
  (b) loss-trajectory equality: max_i |loss_B,i - loss_A,i| / |loss_A,i|
      over the TIMED window <= QUALITY_ENVELOPE = 0.02 (2%) — reused
      LITERALLY from ember_ceff_composition_ab.py's own QUALITY_ENVELOPE
      (its citation: "quality within bf16 granularity of the fp32 run",
      the bf16-NS5 lever's own receipted precedent, 2.1% relative).
  (c) optimizer-state-health: every momentum-bearing state tensor (both
      arms) is all-finite (no inf/nan) AND the global momentum-norm ratio
      ||state_B|| / ||state_A|| falls within MOMENTUM_NORM_RATIO_BAND =
      (0.90, 1.10) — double ember_ceff_composition_ab.py's own 5%
      ORTHOGONALITY_REL_TOL (momentum norm is a coarser, less curvature-
      loaded quantity than an orthogonality residual — a looser band is the
      honest choice for THIS quantity, not a loosened copy of that one).

Verdict: D6_ROUTE_PRICED_OK (all three conjuncts pass) / D6_ROUTE_FAIL —
literal strings per the team-lead's own brief, an intentionally asymmetric
pair (not "harmonized" to D6_ROUTE_PRICED_FAIL here).

Only MOMENTUM-bearing state is forced bf16 (Muon's momentum_buffer; AdamW's
exp_avg — the FIRST moment) — NOT exp_avg_sq (the "v"/second-moment term),
matching spec §3.3's own "no v" qualifier for the Muon route, generalized
sensibly to "momentum" broadly since D6 names "momentum states", not "all
optimizer state".

GOVERNOR / LAUNCH-GATE (never loosened; --dry-run touches neither)
  EMBER_GATE_AUTHORIZED=1 (env) is checked directly — the same guard
  timeshare_pretrain._check_launch_interlock uses, applied here explicitly
  since this harness is a standalone microbench (like
  ember_ceff_composition_ab.py) and never calls run_v0_segment itself.
  ts._apply_governor() — VRAM fraction <=0.80, margin assert >=1.5 GiB,
  inter-step pace sleep >=0.05s — fail-closed SystemExit on violation.
  v0_pretrain_launch_gate.g_budget() consulted with a requested_run
  descriptor (source/total_steps/params/batch/seq) at the CURRENT shape —
  refuses (status BLOCKED, receipt WRITTEN but bench NOT executed) unless
  GREEN. ONE GPU JOB AT A TIME.

MODES (mirrors ember_ceff_composition_ab.py's 3-tier convention):
  --selftest   Pure Python/math + ONE lazily-torch-CPU-only check (no CUDA
               import anywhere) reproducing the "arm A is already bf16"
               empirical finding directly, mechanically re-verified every
               run rather than merely asserted in this docstring. Prints
               D6_BF16_MOMENTUM_AB_SELFTEST_PASS.
  --dry-run    CPU only, tiny stand-in (ts.build_v0_model(cfg, live=False))
               — both arms run end-to-end on CPU, proving the downcast-hook
               mechanism, conjunct computation, and receipt shape. VRAM
               high-water fields are null (CPU has none), self-declared.
               Receipt -> scratch/ember-d6-bf16-momentum-ab-dryrun/.
  (no flag)    The real GPU run at the CURRENT 718.3M shape
               (intermediate_override=8192). NOT fired by this authoring
               session — see BANKED GPU COMMAND below.

No git commits. No downloads. No founder/user names anywhere in this file
or its receipts.

BANKED GPU COMMAND (fire once the current GPU job has freed the card —
attempt 18 / C14 holds first claim; per D6's own dispatch order this runs
before or alongside rung 1's window):

  python scripts/ember_d6_bf16_momentum_ab.py

Dispatch via the train MCP (WSL2/CUDA).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
SCRATCH_DRYRUN = os.path.join(NC, "scratch", "ember-d6-bf16-momentum-ab-dryrun")
sys.path.insert(0, HERE)

from receipt_write import checked_write  # noqa: E402  (light; no torch)

# ── The CURRENT landed shape (cbase-grow-live-live-20260703T053225Z.json) ──
CURRENT_SHAPE_FF = 8192
CURRENT_SHAPE_PARAMS = 718_316_544

# ── Harness window (live) — matches ember_ceff_composition_ab.py's own ──
WARMUP = 5
TIMED = 20
BATCH = 16
CE_CHUNK_TOKENS = 256
TOTAL_STEPS_NOMINAL = 449651   # WSD denominator — affects lr scalar only

# ── CPU dry-run window — tiny, fast, no CUDA ──
DRYRUN_WARMUP = 2
DRYRUN_TIMED = 3
DRYRUN_BATCH = 4
DRYRUN_SEQ = 16
DRYRUN_SEQ = 16

# ── Reproducibility seeds — IDENTICAL across both arms ──
MODEL_SEED = 42
BATCH_GEN_SEED = 20260703

# ── Conjunct thresholds — (a)/(b) reused LITERALLY from
#    ember_ceff_composition_ab.py's own protocol-v2 bars; (c) is NEW to
#    this file, derived (not copied) from that script's 5% orthogonality
#    band, doubled for a coarser quantity. ──
WEIGHT_DELTA_REL_TOL_BF16 = 7.8e-3    # == ember_ceff_composition_ab.NS5_EQUIV_TOL_BF16
QUALITY_ENVELOPE = 0.02               # == ember_ceff_composition_ab.QUALITY_ENVELOPE
MOMENTUM_NORM_RATIO_BAND = (0.90, 1.10)

MOMENTUM_STATE_KEYS = ("momentum_buffer", "exp_avg")   # NOT exp_avg_sq (the "v" term)
ARM_NAMES = ["A_production_as_is", "B_bf16_momentum"]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Momentum-state manipulation — the ONLY thing that differs between arms.
# ---------------------------------------------------------------------------

def _measure_momentum_dtypes(optimizers: dict) -> dict:
    """Non-mutating: record the FIRST-seen dtype per momentum key, across
    every optimizer's state. Pure introspection, no cast."""
    found: dict[str, str] = {}
    for opt in optimizers.values():
        for state in opt.state.values():
            for k in MOMENTUM_STATE_KEYS:
                if k in state and hasattr(state[k], "dtype") and k not in found:
                    found[k] = str(state[k].dtype)
    return found


def _downcast_momentum_states_(optimizers: dict, dtype) -> None:
    """In-place: cast every momentum-bearing optimizer state tensor
    (Muon's momentum_buffer; AdamW's exp_avg — NOT exp_avg_sq/the "v" term)
    to dtype. A no-op for any tensor already at that dtype. Called after
    every .step() for arm B only; never called for arm A."""
    for opt in optimizers.values():
        for state in opt.state.values():
            for k in MOMENTUM_STATE_KEYS:
                if k in state and hasattr(state[k], "to"):
                    state[k] = state[k].to(dtype)


def _momentum_health(optimizers: dict) -> dict:
    """Conjunct (c) raw ingredients for ONE arm: all-finite + global norm
    over every momentum-bearing state tensor."""
    import torch
    finite_ok = True
    norm_sq = 0.0
    n_tensors = 0
    for opt in optimizers.values():
        for state in opt.state.values():
            for k in MOMENTUM_STATE_KEYS:
                if k in state and hasattr(state[k], "isfinite"):
                    t = state[k]
                    if not bool(torch.isfinite(t).all()):
                        finite_ok = False
                    norm_sq += float((t.float() ** 2).sum())
                    n_tensors += 1
    return {"all_finite": finite_ok, "momentum_global_norm": norm_sq ** 0.5, "n_tensors": n_tensors}


# ---------------------------------------------------------------------------
# Per-arm measurement.
# ---------------------------------------------------------------------------

def measure_arm(ts_mod, arm_name: str, cfg: dict, *, live: bool, force_bf16_momentum: bool,
                 warmup: int, timed: int, batch: int, seq: int,
                 intermediate_override: int | None, pace_s: float,
                 margin_gib: float | None):
    import torch

    model = None
    weights_snapshot = None
    try:
        torch.manual_seed(MODEL_SEED)
        free_before = None
        if live:
            torch.cuda.manual_seed(MODEL_SEED)
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            free_before, _ = torch.cuda.mem_get_info()

        try:
            if live:
                model, vocab, hidden, n_mtp = ts_mod.build_v0_model(
                    cfg, live=True, intermediate_override=intermediate_override, device="cuda")
            else:
                model, vocab, hidden, n_mtp = ts_mod.build_v0_model(
                    cfg, live=False, tiny_dims={"vocab": 64, "hidden": 32, "depth": 2})
                # The tiny CPU stand-in (_tiny_v0_model) is fp32 by convention (no
                # .to(bfloat16) call, unlike the real production _V0Real). Cast it
                # here — self-contained, no production code touched — so grad
                # dtype matches state dtype exactly like the REAL model's bf16-
                # native reality, at tiny CPU scale. Without this, forcing
                # momentum state to bf16 while grad stays fp32 breaks AdamW's
                # in-place update math on the NEXT step (RuntimeError: dtype
                # mismatch in exp_avg.lerp_(grad, ...)) — a real finding about
                # WHY the live path's arm-B downcast is safe only because arm A
                # is already bf16-native (see module docstring's HONEST
                # PRE-FLIGHT FINDING), not a dry-run-only workaround.
                model = model.to(torch.bfloat16)
        except RuntimeError as e:
            if live and "out of memory" in str(e).lower():
                torch.cuda.empty_cache()
                return {"arm": arm_name, "status": "OOM_AT_BUILD", "error": str(e)}, None

        optimizers, base_lrs, routing = ts_mod.build_split_optimizer(model, cfg)
        ce_impl, ce_fn = ts_mod.resolve_ce_impl(prefer_liger=live)

        mtp_cfg = cfg["objective"]["mtp_aux_heads"]
        mtp_weight = mtp_cfg["weight"]
        mtp_enabled = bool(mtp_cfg["enabled"]) and n_mtp > 0
        device = "cuda" if live else "cpu"

        gen = torch.Generator(device="cpu")
        gen.manual_seed(BATCH_GEN_SEED)

        def make_batch():
            x = torch.randint(1, vocab, (batch, seq), generator=gen).to(device)
            y0 = torch.randint(1, vocab, (batch, seq), generator=gen).to(device)
            ym = [torch.randint(1, vocab, (batch, seq), generator=gen).to(device)
                  for _ in range(n_mtp)]
            return x, y0, ym

        def step(global_step: int) -> float:
            x, y0, y_mtp = make_batch()
            h = model.backbone(x)
            hf = h.reshape(-1, h.shape[-1])
            pce, _ = ce_fn(hf, model.head.weight, y0.reshape(-1), chunk_tokens=CE_CHUNK_TOKENS)
            mces = []
            if mtp_enabled:
                for k in range(n_mtp):
                    ce_k, _ = ce_fn(hf, model.mtp_heads[k].weight, y_mtp[k].reshape(-1),
                                    chunk_tokens=CE_CHUNK_TOKENS)
                    mces.append(ce_k)
            loss = ts_mod.mtp_total_loss(pce, mces, mtp_weight)
            ts_mod.apply_wsd(optimizers, base_lrs, global_step, TOTAL_STEPS_NOMINAL, cfg["schedule"])
            loss.backward()
            for opt in optimizers.values():
                opt.step()
            if force_bf16_momentum:
                _downcast_momentum_states_(optimizers, torch.bfloat16)
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
            return float(loss.detach().item())

        for i in range(warmup):
            step(i)

        measured_dtypes = _measure_momentum_dtypes(optimizers)

        if live:
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            free_b, _total_b = torch.cuda.mem_get_info()
            free_gib = free_b / (1 << 30)
            if margin_gib is not None and free_gib < margin_gib:
                return {"arm": arm_name, "status": "SKIPPED-MARGIN",
                        "free_vram_gib": round(free_gib, 3)}, None

        step_times, losses = [], []
        t0 = time.perf_counter()
        for i in range(timed):
            t_s = time.perf_counter()
            loss_val = step(warmup + i)
            if live:
                torch.cuda.synchronize()
            dt = time.perf_counter() - t_s
            step_times.append(dt)
            losses.append(loss_val)
            if live:
                time.sleep(pace_s)
        total_dt = time.perf_counter() - t0

        toks = timed * batch * seq
        tok_s_paced = toks / total_dt
        tok_s_raw = toks / (total_dt - timed * pace_s) if live else tok_s_paced

        health = _momentum_health(optimizers)
        weights_snapshot = {n: p.detach().float().cpu().clone() for n, p in model.named_parameters()}

        result = {
            "arm": arm_name, "status": "OK",
            "force_bf16_momentum": force_bf16_momentum,
            "measured_momentum_dtypes_after_warmup": measured_dtypes,
            "tok_s_paced": round(tok_s_paced, 2), "tok_s_raw": round(tok_s_raw, 2),
            "mean_step_ms": round(sum(step_times) / len(step_times) * 1000, 3),
            "loss_trajectory": [round(l, 6) for l in losses],
            "first_loss": round(losses[0], 6), "last_loss": round(losses[-1], 6),
            "n_muon": routing.get("n_muon"), "n_adamw": routing.get("n_adamw"),
            "ce_impl": ce_impl, "routing_mode": routing.get("mode"),
            "optimizer_state_health": health,
            "vram_high_water_gib": None, "vram_used_delta_gib": None,
        }
        if live:
            torch.cuda.synchronize()
            vram_high_water_gib = torch.cuda.max_memory_allocated() / (1 << 30)
            free_after, _ = torch.cuda.mem_get_info()
            result["vram_high_water_gib"] = round(vram_high_water_gib, 4)
            result["vram_used_delta_gib"] = round((free_before - free_after) / (1 << 30), 3)
        return result, weights_snapshot
    finally:
        if model is not None:
            del model
        if live:
            import torch as _t
            _t.cuda.empty_cache()


# ---------------------------------------------------------------------------
# Conjuncts + verdict.
# ---------------------------------------------------------------------------

def weight_delta_conjunct(weights_a: dict, weights_b: dict, rel_tol: float) -> dict:
    max_rel = 0.0
    max_abs = 0.0
    worst_param = None
    if not weights_a or not weights_b:
        return {"max_abs_delta": None, "max_rel_delta": None, "worst_param": None,
                "rel_tolerance": rel_tol, "pass": False, "reason": "missing weight snapshot"}
    for name, wa in weights_a.items():
        wb = weights_b.get(name)
        if wb is None or wa.shape != wb.shape:
            continue
        diff = (wa - wb).abs()
        d_max = float(diff.max())
        scale = max(float(wa.abs().max()), 1e-12)
        rel = d_max / scale
        if rel > max_rel:
            max_rel, max_abs, worst_param = rel, d_max, name
    return {"max_abs_delta": round(max_abs, 10), "max_rel_delta": round(max_rel, 8),
            "worst_param": worst_param, "rel_tolerance": rel_tol,
            "pass": bool(max_rel <= rel_tol)}


def loss_trajectory_conjunct(arm_a: dict, arm_b: dict, envelope: float) -> dict:
    la, lb = arm_a.get("loss_trajectory"), arm_b.get("loss_trajectory")
    if not la or not lb:
        return {"max_abs_rel_loss_delta": None, "envelope": envelope, "pass": False,
                "reason": "missing loss trajectory"}
    n = min(len(la), len(lb))
    deltas = [abs(lb[i] - la[i]) / max(abs(la[i]), 1e-9) for i in range(n)]
    max_delta = max(deltas) if deltas else None
    return {"max_abs_rel_loss_delta": round(max_delta, 6) if max_delta is not None else None,
            "envelope": envelope, "pass": bool(max_delta is not None and max_delta <= envelope)}


def optimizer_state_health_conjunct(arm_a: dict, arm_b: dict, band: tuple) -> dict:
    ha = arm_a.get("optimizer_state_health") or {}
    hb = arm_b.get("optimizer_state_health") or {}
    finite_ok = bool(ha.get("all_finite") and hb.get("all_finite"))
    na, nb = ha.get("momentum_global_norm"), hb.get("momentum_global_norm")
    ratio = (nb / na) if (na and na > 0 and nb is not None) else None
    ratio_ok = bool(ratio is not None and band[0] <= ratio <= band[1])
    return {
        "all_finite_both_arms": finite_ok,
        "momentum_global_norm_a": na, "momentum_global_norm_b": nb,
        "ratio_b_over_a": round(ratio, 6) if ratio is not None else None,
        "ratio_band": list(band),
        "pass": bool(finite_ok and ratio_ok),
    }


def compute_verdict(conjuncts: dict) -> str:
    all_pass = bool(conjuncts) and all(c.get("pass") for c in conjuncts.values())
    return "D6_ROUTE_PRICED_OK" if all_pass else "D6_ROUTE_FAIL"


# ---------------------------------------------------------------------------
# Live GPU run.
# ---------------------------------------------------------------------------

def _run_bench_live() -> dict:
    import timeshare_pretrain as ts_mod
    import v0_pretrain_launch_gate as gate_mod

    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not authorized:
        msg = ("D6_BF16_MOMENTUM_AB_INTERLOCK_REFUSED: requires EMBER_GATE_AUTHORIZED=1 (env) — "
               "the same guard timeshare_pretrain._check_launch_interlock uses, applied directly "
               "since this harness never calls run_v0_segment itself.")
        return {"status": "BLOCKED", "interlock": {"authorized": False, "detail": msg}}

    cfg = ts_mod.load_contract()
    seq = cfg["model"]["seq"]

    total_steps = len(ARM_NAMES) * (WARMUP + TIMED)
    requested_run = {
        "source": "ember_d6_bf16_momentum_ab--live",
        "total_steps": total_steps, "params": CURRENT_SHAPE_PARAMS, "batch": BATCH, "seq": seq,
    }
    st, dt = gate_mod.g_budget(date.today(), requested_run=requested_run)
    if st != "GREEN":
        return {"status": "BLOCKED", "g_budget": {"status": st, "detail": dt},
                "requested_run": requested_run}

    gov = ts_mod._apply_governor()
    pace_s = ts_mod.FP19_PACE_S
    margin_gib = ts_mod.FP19_MARGIN_GIB

    print(f"[d6-bf16-momentum-ab] g_budget: {st} - {dt}", flush=True)
    print(f"[d6-bf16-momentum-ab] shape: ff={CURRENT_SHAPE_FF} params={CURRENT_SHAPE_PARAMS} "
          f"batch={BATCH} seq={seq} warmup={WARMUP} timed={TIMED}", flush=True)

    arm_a, weights_a = measure_arm(
        ts_mod, "A_production_as_is", cfg, live=True, force_bf16_momentum=False,
        warmup=WARMUP, timed=TIMED, batch=BATCH, seq=seq,
        intermediate_override=CURRENT_SHAPE_FF, pace_s=pace_s, margin_gib=margin_gib)
    print(f"[d6-bf16-momentum-ab] arm A: {arm_a.get('status')} "
          f"dtypes={arm_a.get('measured_momentum_dtypes_after_warmup')} "
          f"vram_hw={arm_a.get('vram_high_water_gib')}", flush=True)

    arm_b, weights_b = measure_arm(
        ts_mod, "B_bf16_momentum", cfg, live=True, force_bf16_momentum=True,
        warmup=WARMUP, timed=TIMED, batch=BATCH, seq=seq,
        intermediate_override=CURRENT_SHAPE_FF, pace_s=pace_s, margin_gib=margin_gib)
    print(f"[d6-bf16-momentum-ab] arm B: {arm_b.get('status')} "
          f"dtypes={arm_b.get('measured_momentum_dtypes_after_warmup')} "
          f"vram_hw={arm_b.get('vram_high_water_gib')}", flush=True)

    conjuncts = {}
    if arm_a.get("status") == "OK" and arm_b.get("status") == "OK":
        conjuncts["a_weight_delta_bf16_granularity"] = weight_delta_conjunct(
            weights_a, weights_b, WEIGHT_DELTA_REL_TOL_BF16)
        conjuncts["b_loss_trajectory_equality"] = loss_trajectory_conjunct(arm_a, arm_b, QUALITY_ENVELOPE)
        conjuncts["c_optimizer_state_health"] = optimizer_state_health_conjunct(
            arm_a, arm_b, MOMENTUM_NORM_RATIO_BAND)
    else:
        conjuncts["arm_status_fail"] = {
            "pass": False, "reason": f"arm_a={arm_a.get('status')} arm_b={arm_b.get('status')}"}

    verdict = compute_verdict(conjuncts)

    return {
        "status": "OK", "governor": gov, "g_budget": {"status": st, "detail": dt},
        "requested_run": requested_run,
        "current_shape": {"ff": CURRENT_SHAPE_FF, "params_state_dict_sum": CURRENT_SHAPE_PARAMS},
        "recipe": {
            "source": "timeshare_pretrain production builders (build_v0_model/build_split_optimizer/"
                      "resolve_ce_impl) — UNMODIFIED for arm A; arm B differs ONLY by the post-.step() "
                      "momentum downcast hook",
            "batch": BATCH, "seq": seq, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "warmup": WARMUP, "timed": TIMED, "pace_s": pace_s,
            "model_seed": MODEL_SEED, "batch_gen_seed": BATCH_GEN_SEED,
            "data": "synthetic (torch.randint, dedicated fixed-seed Generator, IDENTICAL sequence "
                    "across both arms)",
        },
        "arms": {"A_production_as_is": arm_a, "B_bf16_momentum": arm_b},
        "conjuncts": conjuncts,
        "kill_criteria": {k: v.get("pass") for k, v in conjuncts.items()},
        "verdict": verdict,
    }


def run_and_emit_live() -> Path:
    result = _run_bench_live()
    ts = _ts()
    receipt = {
        "ticket": "D6-BF16-MOMENTUM-AB",
        "ts": ts,
        "mode": "live",
        "issue": "#29",
        "spec_ref": "docs/domains/governance/spec/c-scale-s1-growth-chain-DRAFT.md §9 D6",
        "scope": "reduced-precision (bf16) momentum optimizer-state VRAM route, pre-registered "
                 "authorized route for S1 rung 2+, priced by A/B at the CURRENT 718.3M shape "
                 "before rung 2 opens",
        "harness_sha": _harness_sha(),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "flags": ["ONE GPU job at a time", "governor rails HOLD — never loosened",
                  "no git commits, no downloads, no founder/user names",
                  "arm A UNMODIFIED production optimizer; arm B differs ONLY by a post-.step() "
                  "momentum-state downcast hook (Muon momentum_buffer + AdamW exp_avg, NOT "
                  "exp_avg_sq/the v term)"],
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    if result.get("status") == "BLOCKED":
        path = os.path.join(RECEIPTS, f"d6-bf16-momentum-ab-BLOCKED-{ts}.json")
        checked_write(path, receipt)
        print(f"[d6-bf16-momentum-ab] LAUNCH_BLOCKED: {result}", flush=True)
        print(f"D6_BF16_MOMENTUM_AB_DONE status=BLOCKED receipt={path}", flush=True)
        return Path(path)

    path = os.path.join(RECEIPTS, f"d6-bf16-momentum-ab-{ts}.json")
    checked_write(path, receipt)
    print(f"[d6-bf16-momentum-ab] receipt: {path}", flush=True)
    print(f"[d6-bf16-momentum-ab] VERDICT: {result['verdict']}", flush=True)
    print(f"D6_BF16_MOMENTUM_AB_DONE verdict={result['verdict']} receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# CPU dry-run — NO CUDA anywhere.
# ---------------------------------------------------------------------------

def _run_bench_dry() -> dict:
    import timeshare_pretrain as ts_mod

    cfg = ts_mod.load_contract()
    seq = DRYRUN_SEQ
    pace_s = 0.0

    arm_a, weights_a = measure_arm(
        ts_mod, "A_production_as_is", cfg, live=False, force_bf16_momentum=False,
        warmup=DRYRUN_WARMUP, timed=DRYRUN_TIMED, batch=DRYRUN_BATCH, seq=seq,
        intermediate_override=None, pace_s=pace_s, margin_gib=None)
    arm_b, weights_b = measure_arm(
        ts_mod, "B_bf16_momentum", cfg, live=False, force_bf16_momentum=True,
        warmup=DRYRUN_WARMUP, timed=DRYRUN_TIMED, batch=DRYRUN_BATCH, seq=seq,
        intermediate_override=None, pace_s=pace_s, margin_gib=None)

    conjuncts = {
        "a_weight_delta_bf16_granularity": weight_delta_conjunct(weights_a, weights_b, WEIGHT_DELTA_REL_TOL_BF16),
        "b_loss_trajectory_equality": loss_trajectory_conjunct(arm_a, arm_b, QUALITY_ENVELOPE),
        "c_optimizer_state_health": optimizer_state_health_conjunct(arm_a, arm_b, MOMENTUM_NORM_RATIO_BAND),
    }
    verdict = compute_verdict(conjuncts)

    return {
        "status": "OK",
        "current_shape_note": "dry-run uses the tiny CPU stand-in dims, NOT the real "
                              f"ff={CURRENT_SHAPE_FF}/params={CURRENT_SHAPE_PARAMS} shape — that "
                              "shape is exercised only on the live path",
        "recipe": {
            "source": "timeshare_pretrain production builders, tiny CPU stand-in "
                      "(build_v0_model(live=False))",
            "batch": DRYRUN_BATCH, "seq": seq, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "warmup": DRYRUN_WARMUP, "timed": DRYRUN_TIMED,
            "model_seed": MODEL_SEED, "batch_gen_seed": BATCH_GEN_SEED,
        },
        "arms": {"A_production_as_is": arm_a, "B_bf16_momentum": arm_b},
        "conjuncts": conjuncts,
        "kill_criteria": {k: v.get("pass") for k, v in conjuncts.items()},
        "verdict": verdict,
    }


def run_and_emit_dry() -> Path:
    result = _run_bench_dry()
    ts = _ts()
    receipt = {
        "ticket": "D6-BF16-MOMENTUM-AB",
        "ts": ts,
        "mode": "dry-run",
        "dry_run": True,
        "issue": "#29",
        "spec_ref": "docs/domains/governance/spec/c-scale-s1-growth-chain-DRAFT.md §9 D6",
        "scope": "CPU plumbing proof only — NOT the real 718.3M-shape pricing evidence; no "
                 "receipts/d6-bf16-momentum-ab-*.json evidence-search glob match, self-declared dry_run",
        "harness_sha": _harness_sha(),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "flags": ["NO torch.cuda.* call anywhere in this mode",
                  "tiny CPU stand-in model — same .backbone()/.head/.mtp_heads interface as real c03",
                  "proves: momentum-downcast-hook mechanism, all three conjuncts, verdict logic, "
                  "receipt shape — all end-to-end on CPU"],
        **result,
    }
    Path(SCRATCH_DRYRUN).mkdir(parents=True, exist_ok=True)
    path = os.path.join(SCRATCH_DRYRUN, f"dry-run-{ts}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"[d6-bf16-momentum-ab] dry-run receipt: {path}", flush=True)
    print(f"[d6-bf16-momentum-ab] VERDICT: {result['verdict']}", flush=True)
    print(f"D6_BF16_MOMENTUM_AB_DRYRUN_DONE verdict={result['verdict']} receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# Selftest — pure Python/math + ONE lazily-imported, CPU-only torch check
# (no CUDA import anywhere in this mode).
# ---------------------------------------------------------------------------

def selftest() -> None:
    print("[ember_d6_bf16_momentum_ab] selftest: conjunct math + verdict logic + schema "
          "+ empirical bf16-momentum finding (CPU-only torch, no CUDA)", flush=True)

    # 1. Thresholds reused LITERALLY from ember_ceff_composition_ab.py — cross-checked
    #    against that module's own constants, not just asserted by comment.
    import ember_ceff_composition_ab as ceff
    assert WEIGHT_DELTA_REL_TOL_BF16 == ceff.NS5_EQUIV_TOL_BF16, (WEIGHT_DELTA_REL_TOL_BF16, ceff.NS5_EQUIV_TOL_BF16)
    assert QUALITY_ENVELOPE == ceff.QUALITY_ENVELOPE, (QUALITY_ENVELOPE, ceff.QUALITY_ENVELOPE)
    assert abs((1.0 - MOMENTUM_NORM_RATIO_BAND[0]) - 2 * ceff.ORTHOGONALITY_REL_TOL) < 1e-9
    assert abs((MOMENTUM_NORM_RATIO_BAND[1] - 1.0) - 2 * ceff.ORTHOGONALITY_REL_TOL) < 1e-9
    print(f"  WEIGHT_DELTA_REL_TOL_BF16={WEIGHT_DELTA_REL_TOL_BF16} == ceff.NS5_EQUIV_TOL_BF16; "
          f"QUALITY_ENVELOPE={QUALITY_ENVELOPE} == ceff.QUALITY_ENVELOPE  PASS")

    # 2. weight_delta_conjunct pure logic.
    class _T:
        def __init__(self, vals): self.vals = vals
        def __sub__(self, other): return _T([a - b for a, b in zip(self.vals, other.vals)])
        def abs(self): return _T([abs(v) for v in self.vals])
        def max(self): return max(self.vals)
        @property
        def shape(self): return (len(self.vals),)

    wa = {"p1": _T([1.0, 2.0, -3.0])}
    wb_close = {"p1": _T([1.001, 2.0, -3.0])}   # rel delta ~0.00033 -> within 7.8e-3
    r = weight_delta_conjunct(wa, wb_close, WEIGHT_DELTA_REL_TOL_BF16)
    assert r["pass"] is True, r
    wb_far = {"p1": _T([1.5, 2.0, -3.0])}   # rel delta 0.5/3 ~0.1667 -> exceeds 7.8e-3
    r2 = weight_delta_conjunct(wa, wb_far, WEIGHT_DELTA_REL_TOL_BF16)
    assert r2["pass"] is False, r2
    print("  weight_delta_conjunct: close->PASS, far->FAIL  PASS")

    # 3. loss_trajectory_conjunct pure logic.
    a = {"loss_trajectory": [10.0, 9.9, 9.8]}
    b_close = {"loss_trajectory": [10.0, 9.905, 9.79]}
    b_far = {"loss_trajectory": [10.0, 12.0, 9.8]}
    assert loss_trajectory_conjunct(a, b_close, QUALITY_ENVELOPE)["pass"] is True
    assert loss_trajectory_conjunct(a, b_far, QUALITY_ENVELOPE)["pass"] is False
    print("  loss_trajectory_conjunct: close->PASS, far(loss[1] blows envelope)->FAIL  PASS")

    # 4. optimizer_state_health_conjunct pure logic.
    ha = {"optimizer_state_health": {"all_finite": True, "momentum_global_norm": 10.0}}
    hb_ok = {"optimizer_state_health": {"all_finite": True, "momentum_global_norm": 10.5}}   # ratio 1.05
    hb_bad_ratio = {"optimizer_state_health": {"all_finite": True, "momentum_global_norm": 20.0}}  # ratio 2.0
    hb_nan = {"optimizer_state_health": {"all_finite": False, "momentum_global_norm": 10.5}}
    assert optimizer_state_health_conjunct(ha, hb_ok, MOMENTUM_NORM_RATIO_BAND)["pass"] is True
    assert optimizer_state_health_conjunct(ha, hb_bad_ratio, MOMENTUM_NORM_RATIO_BAND)["pass"] is False
    assert optimizer_state_health_conjunct(ha, hb_nan, MOMENTUM_NORM_RATIO_BAND)["pass"] is False
    print("  optimizer_state_health_conjunct: in-band+finite->PASS, out-of-band->FAIL, "
          "non-finite->FAIL  PASS")

    # 5. compute_verdict — literal strings, asymmetric per the team-lead's own brief.
    all_pass = {"a": {"pass": True}, "b": {"pass": True}, "c": {"pass": True}}
    one_fail = {"a": {"pass": True}, "b": {"pass": False}, "c": {"pass": True}}
    assert compute_verdict(all_pass) == "D6_ROUTE_PRICED_OK"
    assert compute_verdict(one_fail) == "D6_ROUTE_FAIL"
    assert compute_verdict({}) == "D6_ROUTE_FAIL"
    print("  compute_verdict: all-pass->D6_ROUTE_PRICED_OK, any-fail->D6_ROUTE_FAIL, "
          "empty->D6_ROUTE_FAIL  PASS")

    # 6. HONEST PRE-FLIGHT FINDING, mechanically re-verified (CPU only, lazy import,
    #    zero torch.cuda.* calls anywhere in this step): a bf16 Linear + plain AdamW
    #    step already produces bf16 exp_avg/exp_avg_sq, and _Muon's momentum_buffer
    #    (torch.zeros_like(g)) follows the identical mechanism.
    import torch
    torch.manual_seed(0)
    lin = torch.nn.Linear(4, 4, bias=False).to(torch.bfloat16)
    x = torch.randn(2, 4, dtype=torch.bfloat16)
    y = lin(x).sum()
    y.backward()
    assert lin.weight.grad.dtype == torch.bfloat16, lin.weight.grad.dtype
    opt = torch.optim.AdamW([lin.weight], lr=1e-3)
    opt.step()
    st = opt.state[lin.weight]
    assert st["exp_avg"].dtype == torch.bfloat16, st["exp_avg"].dtype
    assert st["exp_avg_sq"].dtype == torch.bfloat16, st["exp_avg_sq"].dtype
    print("  EMPIRICAL: bf16 param -> bf16 grad -> bf16 AdamW exp_avg/exp_avg_sq "
          "(no fp32 anywhere by default) -- reproduces the HONEST PRE-FLIGHT FINDING "
          "mechanically, not by assertion  PASS")

    # 6b. _downcast_momentum_states_ is a correctly-scoped no-op when state is
    #    already at the target dtype, and DOES cast exp_avg (momentum) while
    #    leaving exp_avg_sq (the "v" term) untouched when state starts as fp32.
    opt2 = torch.optim.AdamW([torch.nn.Parameter(torch.randn(3, 3))], lr=1e-3)
    p2 = opt2.param_groups[0]["params"][0]
    p2.grad = torch.randn(3, 3)
    opt2.step()
    assert opt2.state[p2]["exp_avg"].dtype == torch.float32
    _downcast_momentum_states_({"adamw": opt2}, torch.bfloat16)
    assert opt2.state[p2]["exp_avg"].dtype == torch.bfloat16
    assert opt2.state[p2]["exp_avg_sq"].dtype == torch.float32, (
        "exp_avg_sq (the v term) must NOT be touched by the momentum-only downcast hook")
    print("  _downcast_momentum_states_ casts exp_avg (momentum) only, leaves exp_avg_sq "
          "(the v term) at its original dtype  PASS")

    # 7. Receipt-shape round trip via receipt_check schema floor.
    import receipt_check
    synth = {
        "ticket": "D6-BF16-MOMENTUM-AB", "ts": "20260703T000000Z", "mode": "dry-run",
        "sha_convention": "bytes on disk as-is",
        "verdict": "D6_ROUTE_PRICED_OK", "conjuncts": all_pass,
        "harness_sha": "a" * 64,
    }
    findings = receipt_check.validate_receipt(synth)
    assert findings == [], findings
    print("  receipt-shape round trip passes receipt_check schema floor  PASS")

    print("D6_BF16_MOMENTUM_AB_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="D6 VRAM-route pricing A/B: production optimizer as-is vs momentum "
                    "states forced bf16, at the CURRENT 718.3M shape (issue #29 spec §9 D6)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, no CUDA — tiny stand-in model, proves plumbing + receipt shape")
    ap.add_argument("--selftest", action="store_true",
                    help="pure math/schema checks + one CPU-only torch empirical check")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
        return 0
    if args.dry_run:
        run_and_emit_dry()
        return 0
    run_and_emit_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
