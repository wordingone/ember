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

Verdict-grammar decision procedure: the frozen spec names the five
verdicts and the one hard constraint (positive GPU-compute dominance with
low host movement is the only path to demoting the axis) but does not fix
exact numeric thresholds for classifying DIRECT_COPY_FIRST vs FACTOR1_FIRST
vs BOTH_COMPOSE vs INCONCLUSIVE. The thresholds below (DOMINANCE_RATIO,
SUBSTANTIAL_SHARE, COMPUTE_DOMINANT_SHARE, LOW_HOST_MOVEMENT_SHARE) are
this runner's own disclosed, named, revisable formalization of that gap --
flagged for coordinator review in the PR, not asserted as pre-negotiated.

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

# ---- verdict-grammar decision procedure (runner-authored formalization of
# an underspecified gap in the frozen thread -- see module docstring) ------
COMPUTE_DOMINANT_SHARE = 0.50       # fwd+loss+bwd share of step wall
LOW_HOST_MOVEMENT_SHARE = 0.25      # host-movement share of step wall
SUBSTANTIAL_SHARE = 0.25            # "large enough to matter" floor
DOMINANCE_RATIO = 2.0               # one driver must beat the other by this
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


def _classify_verdict(totals: dict, sum_wall: float) -> dict:
    if sum_wall <= 0:
        return {"verdict": "INCONCLUSIVE", "reason": "zero measured wall time"}
    compute_share = (totals["fwd"] + totals["loss"] + totals["bwd"]) / sum_wall
    host_movement_share = (
        totals["grad_to_cpu_fp32"] + totals["grad_heap_to_memmap"]
        + totals["updated_param_to_gpu"]) / sum_wall
    optimizer_math_share = totals["inner_optimizer_step"] / sum_wall
    shares = {
        "gpu_compute_share": round(compute_share, 4),
        "host_movement_share": round(host_movement_share, 4),
        "optimizer_math_share": round(optimizer_math_share, 4),
    }

    if compute_share >= COMPUTE_DOMINANT_SHARE and host_movement_share < LOW_HOST_MOVEMENT_SHARE:
        return {"verdict": "GPU_COMPUTE_BOUND", "shares": shares,
                "reason": (f"gpu_compute_share={compute_share:.3f} >= "
                           f"{COMPUTE_DOMINANT_SHARE} and host_movement_share="
                           f"{host_movement_share:.3f} < {LOW_HOST_MOVEMENT_SHARE} "
                           "(positive GPU-compute dominance, low host movement)")}

    host_dominant = (host_movement_share >= optimizer_math_share * DOMINANCE_RATIO
                     and host_movement_share >= SUBSTANTIAL_SHARE)
    opt_dominant = (optimizer_math_share >= host_movement_share * DOMINANCE_RATIO
                    and optimizer_math_share >= SUBSTANTIAL_SHARE)
    both_substantial = (host_movement_share >= SUBSTANTIAL_SHARE
                        and optimizer_math_share >= SUBSTANTIAL_SHARE
                        and not host_dominant and not opt_dominant)

    if host_dominant:
        return {"verdict": "DIRECT_COPY_FIRST", "shares": shares,
                "reason": (f"host_movement_share={host_movement_share:.3f} "
                           f">= {DOMINANCE_RATIO}x optimizer_math_share="
                           f"{optimizer_math_share:.3f} and substantial")}
    if opt_dominant:
        return {"verdict": "FACTOR1_FIRST", "shares": shares,
                "reason": (f"optimizer_math_share={optimizer_math_share:.3f} "
                           f">= {DOMINANCE_RATIO}x host_movement_share="
                           f"{host_movement_share:.3f} and substantial")}
    if both_substantial:
        return {"verdict": "BOTH_COMPOSE", "shares": shares,
                "reason": (f"host_movement_share={host_movement_share:.3f} and "
                           f"optimizer_math_share={optimizer_math_share:.3f} both "
                           f">= {SUBSTANTIAL_SHARE}, neither dominant")}
    return {"verdict": "INCONCLUSIVE", "shares": shares,
            "reason": "no phase grouping reaches a decisive share under the "
                      "configured thresholds"}


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
    sum_wall = sum(collector.step_walls())
    if all_passed:
        verdict_result = _classify_verdict(totals, sum_wall)
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
            "pre_run_amendment": "tied-tensor erratum (realized-numel binding)",
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
        "profiled_step_walls_s": collector.step_walls(),
        "unprofiled_step_walls_s": unprofiled_walls,
        "gates": gates,
        "gates_all_passed": all_passed,
        "failing_gates": failing,
        "verdict_grammar": list(VERDICT_GRAMMAR),
        "verdict_decision_thresholds": {
            "COMPUTE_DOMINANT_SHARE": COMPUTE_DOMINANT_SHARE,
            "LOW_HOST_MOVEMENT_SHARE": LOW_HOST_MOVEMENT_SHARE,
            "SUBSTANTIAL_SHARE": SUBSTANTIAL_SHARE,
            "DOMINANCE_RATIO": DOMINANCE_RATIO,
            "disclosed": "runner-authored formalization; not in the frozen thread text",
        },
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

    print("ATTRIBUTION_702_SELFTEST_PASS "
          f"verdict={receipt['verdict']} failing_gates={receipt['failing_gates']} "
          f"n_optimizer_subphase_s={sum(totals[p] for p in OPTIMIZER_SUBPHASES):.6f} "
          f"n_fwd_loss_bwd_s={sum(totals[p] for p in FWD_LOSS_BWD_PHASES):.6f} "
          f"realized_numel_per_step={gates['exact_bytes']['realized_numel_per_step']} "
          f"closure_frac={gates['closure']['closure_frac']}", flush=True)
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
