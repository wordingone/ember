#!/usr/bin/env python3
"""cbase_grow_rung2_attribution_702.py -- barrier axis-3 (memory traffic)
step-time attribution + PCIe throughput profiling runner, issue #702.

Authoritative spec: the #702 comment thread (wordingone/ember), not this
docstring. Three comments there compose the FROZEN spec this runner
implements; where this file and the thread ever disagree, the thread wins:

  1. Amendment (comment id 4938595840) -- the original 25%-single-phase kill
     is INVALID (a flat wall-percentage profile does not prove the axis is
     balanced: four phases can share one memory bottleneck). Replaces it
     with SUBPHASE decomposition -- fwd / loss / bwd, PLUS four named sites
     inside cpu_offload_adamw.py's CPUOffloadOptimizer.step():
       grad_to_cpu_fp32      (L228: real_p.grad.detach().to("cpu", fp32))
       grad_heap_to_memmap   (L248: shadow_p.grad.copy_(g))
       inner_optimizer_step  (L249: self._inner.step())
       updated_param_to_gpu  (L252: real_p.data.copy_(shadow_p.data...))
     Validity gates (ALL mandatory): 2 warmup + >=10 active profiled steps;
     a matched UNPROFILED block within 10% median step-wall (instrumentation
     overhead bound); subphase-sum-to-wall closure within 5%; exact bytes
     bound to realized non-null-grad numel; pinned-vs-pageable D2H/H2D
     calibration. Verdict grammar (replaces the 25% kill): DIRECT_COPY_FIRST
     / FACTOR1_FIRST / BOTH_COMPOSE / GPU_COMPUTE_BOUND / INCONCLUSIVE --
     only a POSITIVE finding of GPU-compute dominance with low host movement
     demotes axis-3; absence of a dominant phase does not.
  2. "PREREG FROZEN" comment -- freezes the amended prereg verbatim; any
     post-freeze design change requires a disclosed un-freeze/re-freeze
     cycle on the issue.
  3. Pre-run amendment (tied-tensor erratum) -- the exact-bytes gate binds
     to REALIZED non-null-grad numel from the LIVE param groups at runtime,
     never a raw/theoretical checkpoint param count. Corrected reference
     point (disclosed, cross-checked, not the gate's source of truth):
     N=2,195,497,984 across 184 deduped tensors (140 Muon / 44 AdamW).
  4. Second pre-run amendment (comment id 4939674864) -- the five verdict
     labels get EXECUTABLE numeric predicates (an independent consumer
     audit found the label grammar underdefined: the same profile could be
     labeled DIRECT_COPY_FIRST, FACTOR1_FIRST, or BOTH_COMPOSE post hoc).
     Spans are EXCLUSIVE and counterfactual-removable, never summed as
     overlapping inclusive spans:
       T_stage            = grad_heap_to_memmap ONLY (the staging copy a
                             direct-copy implementation deletes; a future
                             pinned-buffer staging hop would fold in here
                             too -- none exists in this implementation).
       T_host_unavoidable = grad_to_cpu_fp32 + updated_param_to_gpu (the
                             grad D2H and updated-param H2D are UNAVOIDABLE
                             for offload, never counted as T_stage).
       T_inner            = inner_optimizer_step.
       T_gpu              = fwd + loss + bwd.
     Per-step ratios (over the >=10 active profiled steps) get bootstrap
     95% CIs (10,000 resamples, percentile method, on the mean). SESOI
     frozen at 0.10 of step wall, symmetric for both cure families.
     Predicates: D = lowerCI95(T_stage/T_step) >= 0.10; F =
     lowerCI95(T_inner/T_step) >= 0.10. D&&!F -> DIRECT_COPY_FIRST;
     F&&!D -> FACTOR1_FIRST; D&&F -> BOTH_COMPOSE; !D&&!F &&
     lowerCI95(T_gpu/T_step) >= 0.50 && upperCI95((T_stage+
     T_host_unavoidable)/T_step) <= 0.15 -> GPU_COMPUTE_BOUND; else
     INCONCLUSIVE. The receipt records every ratio, both CI bounds per
     span, the SESOI constants, and which predicate fired. This amendment
     SUPERSEDES this runner's own prior share-based verdict heuristic
     (the very ambiguity the first PR revision flagged for review) -- the
     predicate table below is the frozen spec now, not a formalization
     of a gap.

Reuse discipline (same as every other runner in this tree touching the
offload path): this script does NOT reimplement Muon/AdamW/CE/WSD math. It
builds the model/optimizer/loader via the SAME production functions
run_v0_segment calls (build_v0_model, build_split_optimizer, split_param_
groups, resolve_ce_impl, mtp_total_loss, apply_wsd, PackedShardLoader,
write_packed_shard, load_contract) against the same frozen contract cfg.
The outer step loop is necessarily its own (run_v0_segment exposes no
per-subphase timing hooks and none should be added to the production
training path just to profile it once) -- same precedent as
cbase_grow_rung2_gpu_offload_probe.py, which documents the identical
reasoning for the same reuse boundary.

Subphase attribution mechanism: CPUOffloadOptimizer.step() is monkeypatched
for the duration of the PROFILED block only (installed/uninstalled around
that block, restored to the pristine class method immediately after) with
an instrumented reimplementation that is structurally identical to the real
method -- same lines, same order, same lazy-create/persistence semantics --
with time.perf_counter() (+ torch.cuda.synchronize() boundaries when the
device is cuda, since host<->device copies are dispatched async) inserted
at exactly the four named subphase boundaries. The matched UNPROFILED block
runs immediately after with the ORIGINAL uninstalled method and zero added
instrumentation calls in the outer loop, so its step-wall is the true
uninstrumented baseline the overhead gate compares against.

Verdict-grammar decision procedure: EXECUTABLE per the second pre-run
amendment (comment id 4939674864) -- see `_bootstrap_ci95`, `_per_step_
ratios`, and `_classify_verdict_predicates` below. Every threshold (SESOI
=0.10, GPU_COMPUTE_BOUND's 0.50 lower-CI floor and 0.15 upper-CI ceiling,
10,000 bootstrap resamples) is the frozen thread's own number, not a
runner-authored formalization -- there is no remaining ambiguity in this
grammar.

No git commits from this module. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false. This module launches NO GPU run by default;
--live requires EMBER_GATE_AUTHORIZED=1 (same interlock convention as every
other live-dispatch entrypoint in this tree) and a real --shard-dir.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timeshare_pretrain as ts                                       # noqa: E402
import cpu_offload_adamw as _coa                                      # noqa: E402
from cpu_offload_adamw import nvidia_smi_vram                         # noqa: E402

_REPO = Path(__file__).resolve().parent.parent

# ---- subphase names (exact order = the frozen decomposition) --------------
FWD_LOSS_BWD_PHASES = ("fwd", "loss", "bwd")
OPTIMIZER_SUBPHASES = (
    "grad_to_cpu_fp32", "grad_heap_to_memmap", "inner_optimizer_step",
    "updated_param_to_gpu",
)
ALL_PHASES = FWD_LOSS_BWD_PHASES + OPTIMIZER_SUBPHASES

# ---- validity-gate thresholds (frozen spec's own numbers) -----------------
MIN_WARMUP_STEPS = 2
MIN_ACTIVE_STEPS = 10
OVERHEAD_BOUND_FRAC = 0.10          # matched unprofiled block, median step wall
CLOSURE_BOUND_FRAC = 0.05           # subphase-sum vs measured step wall

# ---- pre-run amendment reference point (disclosed cross-check only; the
# gate itself binds to the LIVE realized numel, never this constant) -------
REFERENCE_REALIZED_N_PARAMS = 2_195_497_984
REFERENCE_N_TENSORS = 184
REFERENCE_N_MUON = 140
REFERENCE_N_ADAMW = 44

# ---- verdict-grammar decision procedure (second pre-run amendment, comment
# id 4939674864 -- EXECUTABLE numeric predicates, frozen; every number below
# is the thread's own, not a runner-authored formalization) ----------------
SESOI_DIRECT = 0.10                 # T_stage/T_step lower-CI95 floor (D)
SESOI_FACTOR = 0.10                 # T_inner/T_step lower-CI95 floor (F)
GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR = 0.50    # T_gpu/T_step lower-CI95 floor
GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL = 0.15    # (T_stage+T_host_unavoidable)/T_step upper-CI95 ceiling
N_BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 0                  # fixed seed -- verdicts are reproducible, not resample-noise-dependent
VERDICT_GRAMMAR = (
    "DIRECT_COPY_FIRST", "FACTOR1_FIRST", "BOTH_COMPOSE",
    "GPU_COMPUTE_BOUND", "INCONCLUSIVE",
)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Subphase collector
# ---------------------------------------------------------------------------

class SubphaseCollector:
    """Per-step subphase wall-time + byte accumulator. `begin_step()` /
    `end_step(step_wall)` bracket one optimizer step; `add(phase, dt)` and
    `add_bytes(phase, n)` are called from inside the profiled fwd/loss/bwd
    block and from the instrumented CPUOffloadOptimizer.step() while a step
    is open. One collector instance is used for exactly one profiled block
    (a fresh instance per block keeps blocks from ever mixing samples)."""

    def __init__(self) -> None:
        self.step_records: list[dict] = []
        self._cur: dict | None = None
        self.realized_numel_total = 0

    def begin_step(self) -> None:
        self._cur = {p: 0.0 for p in ALL_PHASES}
        self._cur["_bytes"] = {p: 0 for p in OPTIMIZER_SUBPHASES}
        self._cur["_realized_numel"] = 0

    def add(self, phase: str, dt: float) -> None:
        assert self._cur is not None, "add() called outside begin_step/end_step"
        self._cur[phase] += dt

    def add_bytes(self, phase: str, n: int) -> None:
        assert self._cur is not None, "add_bytes() called outside begin_step/end_step"
        self._cur["_bytes"][phase] += n

    def add_realized_numel(self, n: int) -> None:
        assert self._cur is not None, "add_realized_numel() called outside begin_step/end_step"
        self._cur["_realized_numel"] += n
        self.realized_numel_total += n

    def end_step(self, step_wall: float) -> None:
        assert self._cur is not None, "end_step() called without a matching begin_step()"
        self._cur["_wall"] = step_wall
        self.step_records.append(self._cur)
        self._cur = None

    # ---- aggregate views -----------------------------------------------

    def phase_totals(self) -> dict:
        totals = {p: 0.0 for p in ALL_PHASES}
        for rec in self.step_records:
            for p in ALL_PHASES:
                totals[p] += rec[p]
        return totals

    def byte_totals(self) -> dict:
        totals = {p: 0 for p in OPTIMIZER_SUBPHASES}
        for rec in self.step_records:
            for p in OPTIMIZER_SUBPHASES:
                totals[p] += rec["_bytes"][p]
        return totals

    def step_walls(self) -> list:
        return [rec["_wall"] for rec in self.step_records]


# ---------------------------------------------------------------------------
# Instrumented CPUOffloadOptimizer.step() -- monkeypatch, install/uninstall
# bracketed around the profiled block only.
# ---------------------------------------------------------------------------

_ORIG_CPU_OFFLOAD_STEP = _coa.CPUOffloadOptimizer.step


def _make_instrumented_step(collector: SubphaseCollector, sync):
    """Structurally identical to CPUOffloadOptimizer.step() (cpu_offload_
    adamw.py L211-252) -- same per-parameter loops, same lazy-create-once/
    persist-forever shadow-grad semantics (R3), same final param writeback
    -- with perf_counter + device-sync boundaries at the four named
    subphase sites and byte/realized-numel accounting folded in. The real
    class is never modified; this closure is installed onto the class only
    for the lifetime of the profiled block (see attribution_run)."""
    import torch

    def _instrumented_step(self, closure=None) -> None:
        assert closure is None, "CPUOffloadOptimizer does not support closures"
        with torch.no_grad():
            for name, real_p, shadow_p in zip(self._names, self._real_params, self._shadow):
                if real_p.grad is None:
                    shadow_p.grad = None
                    continue
                sync(); t0 = time.perf_counter()
                g = real_p.grad.detach().to("cpu", dtype=torch.float32)   # L228
                sync(); t1 = time.perf_counter()
                collector.add("grad_to_cpu_fp32", t1 - t0)
                collector.add_bytes("grad_to_cpu_fp32", g.numel() * g.element_size())
                collector.add_realized_numel(g.numel())
                if shadow_p.grad is None:
                    self.grad_lazy_creates += 1
                    _coa._COUNTERS["grad_lazy_creates"] += 1
                    stem = self._optstate_dir / _coa._sanitize_name(name)
                    shadow_p.grad = _coa._memmap_zeros(
                        Path(str(stem) + ".grad.f32"), tuple(g.shape))
                sync(); t2 = time.perf_counter()
                shadow_p.grad.copy_(g)                                    # L248
                sync(); t3 = time.perf_counter()
                collector.add("grad_heap_to_memmap", t3 - t2)
                collector.add_bytes("grad_heap_to_memmap", g.numel() * g.element_size())
        sync(); t4 = time.perf_counter()
        self._inner.step()                                                # L249
        sync(); t5 = time.perf_counter()
        collector.add("inner_optimizer_step", t5 - t4)
        with torch.no_grad():
            for real_p, shadow_p in zip(self._real_params, self._shadow):
                sync(); t6 = time.perf_counter()
                real_p.data.copy_(shadow_p.data.to(real_p.device, dtype=real_p.dtype))  # L252
                sync(); t7 = time.perf_counter()
                collector.add("updated_param_to_gpu", t7 - t6)
                collector.add_bytes(
                    "updated_param_to_gpu", shadow_p.data.numel() * real_p.element_size())

    return _instrumented_step


def install_instrumented_step(collector: SubphaseCollector, *, device: str):
    import torch
    sync = (torch.cuda.synchronize if device == "cuda" and torch.cuda.is_available()
            else (lambda: None))
    _coa.CPUOffloadOptimizer.step = _make_instrumented_step(collector, sync)


def uninstall_instrumented_step() -> None:
    _coa.CPUOffloadOptimizer.step = _ORIG_CPU_OFFLOAD_STEP


# ---------------------------------------------------------------------------
# Pinned-vs-pageable D2H/H2D calibration
# ---------------------------------------------------------------------------

def calibrate_pinned_vs_pageable(*, device: str, n_elems: int = 1 << 22,
                                  n_trials: int = 5) -> dict:
    """H2D/D2H throughput for pinned vs pageable host buffers, at n_elems
    fp32 elements (16 MiB default -- large enough that kernel-launch fixed
    cost is a small fraction of transfer time, small enough for a fast
    calibration pass). CPU-only mode (no CUDA device) cannot measure a real
    PCIe number and reports that plainly (skipped=True) rather than
    fabricating one -- callers must fail the calibration gate closed on a
    skip, never treat a skip as a pass."""
    import torch
    if device != "cuda" or not torch.cuda.is_available():
        return {"skipped": True, "reason": f"device={device!r} / cuda_available="
                f"{torch.cuda.is_available()} -- pinned-vs-pageable calibration "
                "requires a real CUDA device"}

    n_bytes = n_elems * 4
    gpu_buf = torch.empty(n_elems, dtype=torch.float32, device="cuda")
    pageable = torch.empty(n_elems, dtype=torch.float32)
    pinned = torch.empty(n_elems, dtype=torch.float32).pin_memory()

    def _time_h2d(host_buf) -> float:
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_trials):
            gpu_buf.copy_(host_buf, non_blocking=host_buf.is_pinned())
        torch.cuda.synchronize()
        return (time.perf_counter() - t0) / n_trials

    def _time_d2h(host_buf) -> float:
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_trials):
            host_buf.copy_(gpu_buf, non_blocking=host_buf.is_pinned())
        torch.cuda.synchronize()
        return (time.perf_counter() - t0) / n_trials

    # warmup (excluded from timing) -- first-touch page fault / cuBLAS-style
    # lazy init should not bias the measured steady-state throughput.
    gpu_buf.copy_(pageable); gpu_buf.copy_(pinned)
    torch.cuda.synchronize()

    h2d_pageable_s = _time_h2d(pageable)
    h2d_pinned_s = _time_h2d(pinned)
    d2h_pageable_s = _time_d2h(pageable)
    d2h_pinned_s = _time_d2h(pinned)

    def _gbps(s: float) -> float:
        return round((n_bytes / s) / 1e9, 4) if s > 0 else None

    return {
        "skipped": False,
        "n_bytes_per_trial": n_bytes,
        "n_trials": n_trials,
        "h2d_pageable_gbps": _gbps(h2d_pageable_s),
        "h2d_pinned_gbps": _gbps(h2d_pinned_s),
        "d2h_pageable_gbps": _gbps(d2h_pageable_s),
        "d2h_pinned_gbps": _gbps(d2h_pinned_s),
        "pcie4_x16_peak_gbps": 31.508,
        "h2d_pinned_vs_pageable_speedup": (
            round(h2d_pageable_s / h2d_pinned_s, 3) if h2d_pinned_s > 0 else None),
        "d2h_pinned_vs_pageable_speedup": (
            round(d2h_pageable_s / d2h_pinned_s, 3) if d2h_pinned_s > 0 else None),
    }


# ---------------------------------------------------------------------------
# Profiled / unprofiled block loop -- reuses the production primitives,
# forks only the outer step loop (see module docstring for why).
# ---------------------------------------------------------------------------

def _run_block(*, model, loader, optimizers, base_lrs, cfg, ce_fn, mtp_enabled,
                mtp_weight, ce_chunk_tokens, n_steps: int, global_step_start: int,
                total_steps: int, device: str, batch_size: int,
                profile: bool, collector: "SubphaseCollector | None") -> list:
    """Runs n_steps optimizer steps. profile=True instruments fwd/loss/bwd
    boundaries into `collector` (subphase attribution for the optimizer
    internals is captured by the installed instrumented step, if any, not
    by this function). profile=False adds ZERO extra instrumentation calls
    -- the matched-unprofiled-block baseline. Returns the list of measured
    step-wall times (perf_counter, device-synced)."""
    import torch
    sync = (torch.cuda.synchronize if device == "cuda" and torch.cuda.is_available()
            else (lambda: None))
    step_walls: list = []
    for local_step in range(n_steps):
        global_step = global_step_start + local_step
        if profile:
            collector.begin_step()
        sync(); t_step0 = time.perf_counter()

        x, y0, y_mtp = loader.batch(global_step, batch_size)
        if device == "cuda":
            x = x.cuda(); y0 = y0.cuda(); y_mtp = [t.cuda() for t in y_mtp]

        if profile:
            sync(); t0 = time.perf_counter()
        hidden_out = model.backbone(x)
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        if profile:
            sync(); t1 = time.perf_counter()
            collector.add("fwd", t1 - t0)
            t0 = time.perf_counter()

        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1),
                              chunk_tokens=ce_chunk_tokens)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1),
                                chunk_tokens=ce_chunk_tokens)
                mtp_ces.append(ce_k)
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
        if profile:
            sync(); t1 = time.perf_counter()
            collector.add("loss", t1 - t0)

        ts.apply_wsd(optimizers, base_lrs, global_step, total_steps, cfg["schedule"])

        if profile:
            sync(); t0 = time.perf_counter()
        loss.backward()
        if profile:
            sync(); t1 = time.perf_counter()
            collector.add("bwd", t1 - t0)

        for opt in optimizers.values():
            opt.step()
        for opt in optimizers.values():
            opt.zero_grad(set_to_none=True)

        sync(); step_wall = time.perf_counter() - t_step0
        step_walls.append(step_wall)
        if profile:
            collector.end_step(step_wall)
    return step_walls


# ---------------------------------------------------------------------------
# Validity gates + verdict grammar
# ---------------------------------------------------------------------------

def _evaluate_gates(*, n_warmup: int, n_active: int, profiled_walls: list,
                    unprofiled_walls: list, collector: SubphaseCollector,
                    expected_full_numel: int, calibration: dict) -> dict:
    gates: dict = {}

    gates["step_count"] = {
        "passed": n_warmup >= MIN_WARMUP_STEPS and n_active >= MIN_ACTIVE_STEPS,
        "n_warmup": n_warmup, "n_active": n_active,
        "floor_warmup": MIN_WARMUP_STEPS, "floor_active": MIN_ACTIVE_STEPS,
    }

    prof_med = statistics.median(profiled_walls) if profiled_walls else None
    unprof_med = statistics.median(unprofiled_walls) if unprofiled_walls else None
    overhead_frac = (abs(prof_med - unprof_med) / unprof_med
                     if prof_med is not None and unprof_med else None)
    gates["overhead"] = {
        "passed": overhead_frac is not None and overhead_frac <= OVERHEAD_BOUND_FRAC,
        "profiled_median_wall_s": prof_med, "unprofiled_median_wall_s": unprof_med,
        "overhead_frac": overhead_frac, "bound_frac": OVERHEAD_BOUND_FRAC,
    }

    totals = collector.phase_totals()
    sum_subphases = sum(totals.values())
    sum_wall = sum(collector.step_walls())
    closure_frac = (abs(sum_subphases - sum_wall) / sum_wall) if sum_wall else None
    gates["closure"] = {
        "passed": closure_frac is not None and closure_frac <= CLOSURE_BOUND_FRAC,
        "sum_subphases_s": sum_subphases, "sum_measured_wall_s": sum_wall,
        "closure_frac": closure_frac, "bound_frac": CLOSURE_BOUND_FRAC,
    }

    byte_totals = collector.byte_totals()
    realized_numel_per_step = (collector.realized_numel_total / len(collector.step_records)
                               if collector.step_records else 0)
    bytes_self_consistent = (
        byte_totals["grad_to_cpu_fp32"] == byte_totals["grad_heap_to_memmap"] == (
            collector.realized_numel_total * 4))
    numel_matches_live_param_groups = (
        round(realized_numel_per_step) == expected_full_numel)
    gates["exact_bytes"] = {
        "passed": bytes_self_consistent and numel_matches_live_param_groups,
        "realized_numel_per_step": realized_numel_per_step,
        "expected_full_numel_from_split_param_groups": expected_full_numel,
        "byte_totals": byte_totals,
        "bytes_self_consistent": bytes_self_consistent,
        "numel_matches_live_param_groups": numel_matches_live_param_groups,
        "rule": ("bound to REALIZED non-null-grad numel measured at runtime "
                 "from the live param groups -- never a raw/theoretical "
                 "checkpoint param count (pre-run amendment)"),
    }

    gates["pinned_pageable_calibration"] = {
        "passed": bool(calibration.get("skipped") is False),
        "calibration": calibration,
    }

    return gates


def _bootstrap_ci95(values: list, *, n_resamples: int = N_BOOTSTRAP_RESAMPLES,
                    rng=None) -> dict:
    """Bootstrap 95% CI of the MEAN of `values` (percentile method,
    2.5/97.5 percentiles of the resampled-mean distribution). `rng` is a
    numpy Generator shared across calls in one verdict classification so
    every span's CI in a receipt derives from one seeded, reproducible
    resample stream (never per-call reseeded, which would make different
    spans' CIs independently noisy for no reason)."""
    import numpy as np
    rng = rng if rng is not None else np.random.default_rng(BOOTSTRAP_SEED)
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return {"lower": None, "upper": None, "mean": None,
                "n_samples": 0, "n_resamples": n_resamples}
    idx = rng.integers(0, n, size=(n_resamples, n))
    resample_means = arr[idx].mean(axis=1)
    return {
        "lower": round(float(np.percentile(resample_means, 2.5)), 6),
        "upper": round(float(np.percentile(resample_means, 97.5)), 6),
        "mean": round(float(arr.mean()), 6),
        "n_samples": n, "n_resamples": n_resamples,
    }


def _per_step_ratios(collector: "SubphaseCollector") -> dict:
    """Per-step EXCLUSIVE, counterfactual-removable span ratios (second
    pre-run amendment, comment id 4939674864) -- one scalar per active
    profiled step, never an aggregate-first ratio (aggregating first would
    silently reweight steps of different wall time and break the per-step
    bootstrap the amendment specifies)."""
    stage, inner, gpu, host_unavoidable, stage_plus_host = [], [], [], [], []
    for rec in collector.step_records:
        w = rec["_wall"]
        t_stage = rec["grad_heap_to_memmap"]
        t_inner = rec["inner_optimizer_step"]
        t_host = rec["grad_to_cpu_fp32"] + rec["updated_param_to_gpu"]
        t_gpu = rec["fwd"] + rec["loss"] + rec["bwd"]
        if w <= 0:
            stage.append(0.0); inner.append(0.0); gpu.append(0.0)
            host_unavoidable.append(0.0); stage_plus_host.append(0.0)
            continue
        stage.append(t_stage / w)
        inner.append(t_inner / w)
        gpu.append(t_gpu / w)
        host_unavoidable.append(t_host / w)
        stage_plus_host.append((t_stage + t_host) / w)
    return {
        "stage_ratio": stage, "inner_ratio": inner, "gpu_ratio": gpu,
        "host_unavoidable_ratio": host_unavoidable,
        "stage_plus_host_unavoidable_ratio": stage_plus_host,
    }


def _classify_verdict_predicates(ratios: dict, *, seed: int = BOOTSTRAP_SEED) -> dict:
    """The frozen, EXECUTABLE decision grammar (second pre-run amendment,
    comment id 4939674864). Every threshold is the thread's own number.
    Reached only when every validity gate has already passed (see
    attribution_run) -- this function has no fail-closed logic of its own,
    it classifies whatever ratios it is given."""
    import numpy as np
    rng = np.random.default_rng(seed)

    ci_stage = _bootstrap_ci95(ratios["stage_ratio"], rng=rng)
    ci_inner = _bootstrap_ci95(ratios["inner_ratio"], rng=rng)
    ci_gpu = _bootstrap_ci95(ratios["gpu_ratio"], rng=rng)
    ci_host_unavoidable = _bootstrap_ci95(ratios["host_unavoidable_ratio"], rng=rng)
    ci_stage_plus_host = _bootstrap_ci95(ratios["stage_plus_host_unavoidable_ratio"], rng=rng)

    D = ci_stage["lower"] is not None and ci_stage["lower"] >= SESOI_DIRECT
    F = ci_inner["lower"] is not None and ci_inner["lower"] >= SESOI_FACTOR

    if D and not F:
        verdict, reason = "DIRECT_COPY_FIRST", (
            f"D=True (lowerCI95(T_stage/T_step)={ci_stage['lower']} >= {SESOI_DIRECT}), "
            f"F=False (lowerCI95(T_inner/T_step)={ci_inner['lower']} < {SESOI_FACTOR})")
    elif F and not D:
        verdict, reason = "FACTOR1_FIRST", (
            f"F=True (lowerCI95(T_inner/T_step)={ci_inner['lower']} >= {SESOI_FACTOR}), "
            f"D=False (lowerCI95(T_stage/T_step)={ci_stage['lower']} < {SESOI_DIRECT})")
    elif D and F:
        verdict, reason = "BOTH_COMPOSE", (
            f"D=True and F=True (lowerCI95(T_stage/T_step)={ci_stage['lower']}, "
            f"lowerCI95(T_inner/T_step)={ci_inner['lower']}, both >= 0.10)")
    elif (ci_gpu["lower"] is not None and ci_gpu["lower"] >= GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR
          and ci_stage_plus_host["upper"] is not None
          and ci_stage_plus_host["upper"] <= GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL):
        verdict, reason = "GPU_COMPUTE_BOUND", (
            f"D=False, F=False, lowerCI95(T_gpu/T_step)={ci_gpu['lower']} >= "
            f"{GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR} and "
            f"upperCI95((T_stage+T_host_unavoidable)/T_step)={ci_stage_plus_host['upper']} "
            f"<= {GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL} (positive GPU-compute dominance, "
            "low host movement)")
    else:
        verdict, reason = "INCONCLUSIVE", (
            f"D=False, F=False, and the GPU_COMPUTE_BOUND predicate did not fire "
            f"(lowerCI95(T_gpu/T_step)={ci_gpu['lower']}, "
            f"upperCI95((T_stage+T_host_unavoidable)/T_step)={ci_stage_plus_host['upper']})")

    return {
        "verdict": verdict,
        "reason": reason,
        "predicates": {"D_direct_copy": D, "F_factor1": F},
        "sesoi": {
            "SESOI_direct": SESOI_DIRECT, "SESOI_factor": SESOI_FACTOR,
            "gpu_compute_bound_gpu_lower_ci_floor": GPU_COMPUTE_BOUND_GPU_LOWER_CI_FLOOR,
            "gpu_compute_bound_host_upper_ci_ceil": GPU_COMPUTE_BOUND_HOST_UPPER_CI_CEIL,
        },
        "ci95": {
            "T_stage_over_T_step": ci_stage,
            "T_inner_over_T_step": ci_inner,
            "T_gpu_over_T_step": ci_gpu,
            "T_host_unavoidable_over_T_step": ci_host_unavoidable,
            "T_stage_plus_T_host_unavoidable_over_T_step": ci_stage_plus_host,
        },
        "n_bootstrap_resamples": N_BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": seed,
    }


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

def attribution_run(*, live: bool, cfg: dict, shard_dir: str | None,
                    run_dir: str, device: str, tiny_dims: dict | None = None,
                    intermediate_override: int | None = None,
                    batch_size: int | None = None, n_warmup: int = MIN_WARMUP_STEPS,
                    n_active: int = MIN_ACTIVE_STEPS, ce_chunk_tokens: int = 256,
                    total_steps: int | None = None) -> dict:
    """Runs warmup -> profiled block -> matched unprofiled block -> pinned/
    pageable calibration, evaluates every validity gate FAIL-CLOSED, and
    returns the receipt dict (not yet written to disk -- see main())."""
    import os
    import torch

    os.makedirs(run_dir, exist_ok=True)
    seq = cfg["model"]["seq"] if live else (tiny_dims or {}).get("seq", 16)
    batch_size = batch_size or (cfg["throughput"]["batch"] if live else 2)

    model, vocab, hidden, n_mtp = ts.build_v0_model(
        cfg, live=live, tiny_dims=tiny_dims,
        intermediate_override=intermediate_override, device=device)

    if shard_dir is None:
        assert not live, "live dispatch must supply a real --shard-dir"
        import numpy as np
        shard_dir = os.path.join(run_dir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        rng = np.random.default_rng(0)
        n_probe_steps = n_warmup + 2 * n_active + 4
        need = n_probe_steps * batch_size * seq + seq + n_mtp + 8
        toks = rng.integers(1, vocab, size=int(need), dtype=np.int64)
        toks[:: max(1, seq * 3)] = 0
        ts.write_packed_shard(
            os.path.join(shard_dir, "synthetic-00000.bin"), toks.astype("uint16").tolist())
    loader = ts.PackedShardLoader(shard_dir, seq, n_mtp,
                                  mmap_cache_dir=os.path.join(run_dir, "mmap_cache"))

    optimizers, base_lrs, routing = ts.build_split_optimizer(
        model, cfg, offload_optimizer_state=True,
        deviation_dir=os.path.join(run_dir, "deviations"))
    muon_named, adamw_named = ts.split_param_groups(model)
    expected_full_numel = sum(p.numel() for _, p in muon_named) + \
        sum(p.numel() for _, p in adamw_named)

    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=live)
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_enabled = mtp_cfg["enabled"]
    mtp_weight = mtp_cfg["weight"]
    total_steps = total_steps or (n_warmup + 2 * n_active)

    common = dict(model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
                 cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
                 ce_chunk_tokens=ce_chunk_tokens, device=device, batch_size=batch_size,
                 total_steps=total_steps)

    # ---- warmup (uninstrumented) ----
    step = 0
    _run_block(global_step_start=step, n_steps=n_warmup, profile=False,
              collector=None, **common)
    step += n_warmup

    # ---- profiled block ----
    collector = SubphaseCollector()
    install_instrumented_step(collector, device=device)
    try:
        profiled_walls = _run_block(global_step_start=step, n_steps=n_active,
                                    profile=True, collector=collector, **common)
    finally:
        uninstall_instrumented_step()
    step += n_active

    # ---- matched unprofiled block (baseline for the overhead gate) ----
    unprofiled_walls = _run_block(global_step_start=step, n_steps=n_active,
                                  profile=False, collector=None, **common)
    step += n_active

    calibration = calibrate_pinned_vs_pageable(device=device)

    gates = _evaluate_gates(
        n_warmup=n_warmup, n_active=n_active, profiled_walls=profiled_walls,
        unprofiled_walls=unprofiled_walls, collector=collector,
        expected_full_numel=expected_full_numel, calibration=calibration)
    all_passed = all(g["passed"] for g in gates.values())
    failing = [name for name, g in gates.items() if not g["passed"]]

    totals = collector.phase_totals()
    ratios = _per_step_ratios(collector)
    if all_passed:
        verdict_result = _classify_verdict_predicates(ratios)
    else:
        verdict_result = {"verdict": "INVALID", "reason": "one or more validity "
                          f"gates failed (fail-closed, no partial credit): {failing}"}

    vram = None
    if device == "cuda" and torch.cuda.is_available():
        try:
            vram = nvidia_smi_vram()
        except Exception as e:
            vram = {"error": str(e)}

    receipt = {
        "ticket": "EMBER-702-ATTRIBUTION",
        "ts": _ts(),
        "issue": "wordingone/ember#702",
        "prereg": {
            "amendment_comment_id": 4938595840,
            "status": "PREREG_FROZEN",
            "pre_run_amendments": [
                "4939491354: tied-tensor erratum (realized-numel binding)",
                "4939674864: executable verdict-grammar predicates (SESOI, "
                "bootstrap CIs, D/F predicate table)",
            ],
        },
        "mode": {"live": live, "device": device, "n_warmup": n_warmup, "n_active": n_active},
        "optimizer_routing": routing,
        "expected_full_numel_from_split_param_groups": expected_full_numel,
        "reference_pre_run_amendment": {
            "n_params": REFERENCE_REALIZED_N_PARAMS, "n_tensors": REFERENCE_N_TENSORS,
            "n_muon": REFERENCE_N_MUON, "n_adamw": REFERENCE_N_ADAMW,
            "matches_this_run": expected_full_numel == REFERENCE_REALIZED_N_PARAMS,
            "note": ("disclosed cross-check only -- the exact_bytes gate binds to "
                     "THIS run's live-measured realized numel, never this constant"),
        },
        "subphase_totals_s": totals,
        "subphase_byte_totals": collector.byte_totals(),
        "per_step_span_ratios": ratios,
        "profiled_step_walls_s": collector.step_walls(),
        "unprofiled_step_walls_s": unprofiled_walls,
        "gates": gates,
        "gates_all_passed": all_passed,
        "failing_gates": failing,
        "verdict_grammar": list(VERDICT_GRAMMAR),
        "calibration_pinned_vs_pageable": calibration,
        "vram_at_end": vram,
        "ce_impl": ce_impl,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        **verdict_result,
    }
    return receipt


# ---------------------------------------------------------------------------
# Verdict-predicate selftest -- one synthetic profile per verdict class.
# The real attribution_run() CPU selftest below can NEVER exercise
# _classify_verdict_predicates (gates never all-pass without a CUDA device,
# so the verdict grammar is unreachable from that path on this box). This
# is the second pre-run amendment's own requirement (comment id
# 4939674864: "the runner's selftest must include one synthetic profile
# per verdict class") -- tests the predicate table directly and
# independently of the gate pipeline.
# ---------------------------------------------------------------------------

def _synthetic_ratio_fixture(*, stage: float, inner: float, gpu: float,
                             host_unavoidable: float, n_steps: int = 10,
                             jitter: float = 0.01, seed: int = 0) -> dict:
    """n_steps per-step ratio samples, each target +/- a small seeded
    jitter (bootstrap CI must see real per-step variance, not a point
    mass). stage_plus_host is DERIVED per step from the jittered stage/host
    values, not independently jittered -- the real per-step data has the
    same relationship (see _per_step_ratios)."""
    import random
    rnd = random.Random(seed)

    def _jseries(target: float) -> list:
        return [max(0.0, target + rnd.uniform(-jitter, jitter)) for _ in range(n_steps)]

    stage_s, inner_s, gpu_s, host_s = (
        _jseries(stage), _jseries(inner), _jseries(gpu), _jseries(host_unavoidable))
    return {
        "stage_ratio": stage_s, "inner_ratio": inner_s, "gpu_ratio": gpu_s,
        "host_unavoidable_ratio": host_s,
        "stage_plus_host_unavoidable_ratio": [s + h for s, h in zip(stage_s, host_s)],
    }


# Targets are chosen with generous margin (>=0.07) from every threshold
# (0.10 SESOI, 0.50 GPU floor, 0.15 host ceiling) so +/-0.01 per-step
# jitter and bootstrap resample noise can never flip the classification --
# these fixtures test the PREDICATE LOGIC, not threshold-boundary
# sensitivity.
_VERDICT_FIXTURES = {
    "DIRECT_COPY_FIRST": dict(stage=0.30, inner=0.02, gpu=0.40, host_unavoidable=0.28),
    "FACTOR1_FIRST": dict(stage=0.02, inner=0.35, gpu=0.40, host_unavoidable=0.23),
    "BOTH_COMPOSE": dict(stage=0.20, inner=0.20, gpu=0.30, host_unavoidable=0.30),
    "GPU_COMPUTE_BOUND": dict(stage=0.03, inner=0.03, gpu=0.86, host_unavoidable=0.08),
    "INCONCLUSIVE": dict(stage=0.05, inner=0.05, gpu=0.40, host_unavoidable=0.50),
}


def _selftest_verdict_predicates() -> None:
    for i, (expected_verdict, targets) in enumerate(_VERDICT_FIXTURES.items()):
        ratios = _synthetic_ratio_fixture(seed=100 + i, **targets)
        result = _classify_verdict_predicates(ratios)
        assert result["verdict"] == expected_verdict, (
            f"predicate-table fixture {expected_verdict!r} classified as "
            f"{result['verdict']!r} instead -- reason: {result['reason']}")
        # every ratio + both CI bounds per span + SESOI constants + fired
        # predicate must be present (amendment's own receipt requirement).
        for span_key in ("T_stage_over_T_step", "T_inner_over_T_step",
                         "T_gpu_over_T_step", "T_host_unavoidable_over_T_step",
                         "T_stage_plus_T_host_unavoidable_over_T_step"):
            ci = result["ci95"][span_key]
            assert ci["lower"] is not None and ci["upper"] is not None, (expected_verdict, span_key)
        assert set(result["sesoi"]) == {
            "SESOI_direct", "SESOI_factor", "gpu_compute_bound_gpu_lower_ci_floor",
            "gpu_compute_bound_host_upper_ci_ceil"}
        assert "D_direct_copy" in result["predicates"] and "F_factor1" in result["predicates"]
    print("ATTRIBUTION_702_VERDICT_PREDICATES_SELFTEST_PASS "
          f"fixtures={list(_VERDICT_FIXTURES.keys())} "
          f"n_bootstrap_resamples={N_BOOTSTRAP_RESAMPLES}", flush=True)


# ---------------------------------------------------------------------------
# CPU-only selftest -- exercises the FULL instrumentation + gate + verdict
# path with tiny fixture dims, no GPU, no daemon, < 30s.
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import random
    import tempfile
    import torch

    torch.manual_seed(0)
    random.seed(0)

    cfg = {
        "model": {"seq": 16, "vocab": 64, "hidden": 32, "tied_embeddings": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"warmup_frac": 0.1, "stable_until_frac": 0.8, "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 2},
    }
    tiny_dims = {"vocab": 64, "hidden": 32, "depth": 2, "seq": 16}
    run_dir = tempfile.mkdtemp(prefix="attribution702_selftest_")

    receipt = attribution_run(
        live=False, cfg=cfg, shard_dir=None, run_dir=run_dir, device="cpu",
        tiny_dims=tiny_dims, batch_size=2, n_warmup=2, n_active=10, ce_chunk_tokens=32)

    # ---- assertions: the mechanism, not a fabricated production verdict ----
    gates = receipt["gates"]
    assert receipt["gates_all_passed"] is False, (
        "CPU selftest must NOT produce a gates-all-passed run: there is no CUDA "
        "device, so pinned_pageable_calibration is expected (and required) to "
        "fail closed. A CPU run reporting all gates passed is the failure mode "
        "this selftest exists to catch (silent, ungated verdict fabrication).")
    assert gates["pinned_pageable_calibration"]["passed"] is False, (
        "pinned_pageable_calibration must fail closed on CPU (no CUDA device)")
    assert receipt["verdict"] == "INVALID", (
        f"expected fail-closed INVALID verdict on CPU, got {receipt['verdict']!r}")
    assert "pinned_pageable_calibration" in receipt["failing_gates"]

    # step-count gate: 2 warmup + 10 active IS the floor, must independently pass.
    assert gates["step_count"]["passed"] is True, gates["step_count"]

    # subphase decomposition actually fired for all four optimizer sites plus
    # fwd/loss/bwd, with nonzero wall time and nonzero realized-numel bytes.
    totals = receipt["subphase_totals_s"]
    for phase in ALL_PHASES:
        assert phase in totals and totals[phase] >= 0.0, f"missing/negative phase: {phase}"
    assert sum(totals[p] for p in OPTIMIZER_SUBPHASES) > 0.0, (
        "optimizer subphase instrumentation never fired")
    assert sum(totals[p] for p in FWD_LOSS_BWD_PHASES) > 0.0, (
        "fwd/loss/bwd instrumentation never fired")
    byte_totals = receipt["subphase_byte_totals"]
    assert byte_totals["grad_to_cpu_fp32"] > 0, "zero bytes attributed to grad_to_cpu_fp32"
    assert byte_totals["updated_param_to_gpu"] > 0, "zero bytes attributed to updated_param_to_gpu"

    # exact_bytes self-consistency must hold even though the calibration gate
    # (a DIFFERENT, CUDA-only gate) fails -- gates are independent.
    assert gates["exact_bytes"]["bytes_self_consistent"] is True, gates["exact_bytes"]
    assert gates["exact_bytes"]["numel_matches_live_param_groups"] is True, gates["exact_bytes"]

    # matched unprofiled block ran and is a real, independent measurement.
    assert len(receipt["unprofiled_step_walls_s"]) == 10
    assert len(receipt["profiled_step_walls_s"]) == 10

    # instrumented step is restored to the pristine class method after use --
    # a later, unrelated caller must never see the profiled closure.
    assert _coa.CPUOffloadOptimizer.step is _ORIG_CPU_OFFLOAD_STEP, (
        "instrumented step leaked past the profiled block -- uninstall failed")

    # per_step_span_ratios is populated even on a gates-failed (INVALID) run
    # -- the amendment's ratios/CI machinery is independent of the gate
    # pipeline; only the LABEL (verdict) is gated.
    assert set(receipt["per_step_span_ratios"]) == {
        "stage_ratio", "inner_ratio", "gpu_ratio", "host_unavoidable_ratio",
        "stage_plus_host_unavoidable_ratio"}
    assert len(receipt["per_step_span_ratios"]["stage_ratio"]) == 10

    print("ATTRIBUTION_702_SELFTEST_PASS "
          f"verdict={receipt['verdict']} failing_gates={receipt['failing_gates']} "
          f"n_optimizer_subphase_s={sum(totals[p] for p in OPTIMIZER_SUBPHASES):.6f} "
          f"n_fwd_loss_bwd_s={sum(totals[p] for p in FWD_LOSS_BWD_PHASES):.6f} "
          f"realized_numel_per_step={gates['exact_bytes']['realized_numel_per_step']} "
          f"closure_frac={gates['closure']['closure_frac']}", flush=True)

    _selftest_verdict_predicates()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="Run the CPU-only selftest (tiny fixture dims, < 30s, no GPU)")
    ap.add_argument("--live", action="store_true",
                    help="Real 2.2B-arch CUDA dispatch. Requires EMBER_GATE_AUTHORIZED=1 "
                         "and --shard-dir. Refused otherwise.")
    ap.add_argument("--shard-dir", default=None, help="real packed uint16 corpus shard dir")
    ap.add_argument("--out-dir", default=None, help="run/scratch dir (defaults to a tempdir)")
    ap.add_argument("--receipt-dir", default=str(_REPO / "receipts"))
    ap.add_argument("--n-warmup", type=int, default=MIN_WARMUP_STEPS)
    ap.add_argument("--n-active", type=int, default=MIN_ACTIVE_STEPS)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    import os
    import tempfile
    if args.live:
        if os.environ.get("EMBER_GATE_AUTHORIZED") != "1":
            print("ATTRIBUTION_702_REFUSED: --live requires EMBER_GATE_AUTHORIZED=1 "
                  "(same interlock convention as every other live-dispatch entrypoint "
                  "in this tree). No GPU run launched.", flush=True)
            return 3
        if not args.shard_dir:
            print("ATTRIBUTION_702_REFUSED: --live requires --shard-dir "
                  "(no synthetic tokens on the live path).", flush=True)
            return 3
        if args.n_warmup < MIN_WARMUP_STEPS or args.n_active < MIN_ACTIVE_STEPS:
            print(f"ATTRIBUTION_702_REFUSED: --n-warmup>={MIN_WARMUP_STEPS} and "
                  f"--n-active>={MIN_ACTIVE_STEPS} are validity-gate floors, not "
                  "tunable below them.", flush=True)
            return 3

    cfg = ts.load_contract()
    run_dir = args.out_dir or tempfile.mkdtemp(prefix="attribution702_")
    Path(args.receipt_dir).mkdir(parents=True, exist_ok=True)

    receipt = attribution_run(
        live=args.live, cfg=cfg, shard_dir=args.shard_dir, run_dir=run_dir,
        device=args.device if args.live else "cpu",
        tiny_dims=None if args.live else {"vocab": 64, "hidden": 32, "depth": 2, "seq": 16},
        n_warmup=args.n_warmup, n_active=args.n_active)

    from receipt_write import checked_write
    receipt_path = Path(args.receipt_dir) / f"attribution-702-{receipt['ts']}.json"
    checked_write(str(receipt_path), receipt)
    print(f"ATTRIBUTION_702_DONE receipt={receipt_path} verdict={receipt['verdict']} "
          f"gates_all_passed={receipt['gates_all_passed']} "
          f"failing_gates={receipt['failing_gates']}", flush=True)
    return 0 if receipt["gates_all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
