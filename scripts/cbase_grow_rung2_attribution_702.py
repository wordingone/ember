#!/usr/bin/env python3
"""cbase_grow_rung2_attribution_702.py -- barrier axis-3 (memory traffic)
step-time attribution + PCIe throughput profiling runner, issue #702.

Authoritative spec: the #702 comment thread (wordingone/ember), not this
docstring. Where this file and the thread ever disagree, the thread wins.
The prereg (amendment comment id 4938595840, frozen, plus pre-run amendments
4939491354 tied-tensor erratum and 4939674864 executable verdict-grammar
predicates) is summarized below; the FULL summary of those four items lived
in this file's prior revision (PR #721) and is unchanged here -- see that
revision's history for the verbatim recap. This revision implements the
POST-#721 BLOCK comment (disposition BLOCK_721_PRODUCTION_ATTRIBUTION /
CLEAR_PREDICATE_TABLE_ONLY): the #721-merged runner's predicate table and
fail-closed gates stood, but its ATTRIBUTION MECHANISM did not, on three
counts, each repaired here:

  (a) Consumer-identity defect (was: L226-273 installed `_instrumented_step`,
      a hand-copied reimplementation of CPUOffloadOptimizer.step monkey-
      patched onto the CLASS -- production's real step() never executed
      under profiling, and there was no equivalence receipt). REPAIRED by
      moving instrumentation INSIDE the original method: cpu_offload_adamw.
      CPUOffloadOptimizer now exposes attach_span_collector()/
      detach_span_collector(), a per-INSTANCE (never class-level), default-
      OFF hook set checked at exactly the four named subphase boundaries
      inside the real step() body. Unattached, step()'s arithmetic, control
      flow, and every side effect (grad_lazy_creates counting, memmap
      creation, param writeback order) are byte-identical to the pristine
      method -- there is no second implementation to diverge from the real
      one. This is repair option (a) from the block comment ("instrumentation
      lives INSIDE the original step ... record_function/span hooks,
      default-off"), not option (b) (equivalence receipts) -- (a) removes the
      defect by construction rather than by proof-after-the-fact, so no
      separate equivalence-receipt machinery is built here.
  (b) Unmatched overhead gate (was: profiled and unprofiled blocks ran in
      FIXED sequential order on different batches/global-steps/optimizer
      state -- temporal drift could mask a real overhead cost or fabricate a
      violation with zero instrumentation). REPAIRED by a counterbalanced
      AB/BA design: after warmup, the full training state (model params,
      each CPUOffloadOptimizer's shadow params + inner optimizer state, and
      the CPU/CUDA/python RNG streams) is snapshotted once (`_snapshot_fork`).
      Arm A runs profiled-then-unprofiled from that fork; the fork is then
      RESTORED byte-for-byte (`_restore_fork_`) and Arm B runs unprofiled-
      then-profiled from the identical restored state. PackedShardLoader.
      batch(step, batch_size) is a pure function of step (see timeshare_
      pretrain.py's own docstring: "resume re-derives the identical data
      stream"), so "same loader state" reduces to reusing the same starting
      global_step for both arms -- which this design does: both arms
      traverse the SAME absolute step range, just with profiled/unprofiled
      swapped between the first and second half. Every step-slot in that
      range is therefore measured BOTH profiled and unprofiled, from
      matching state, at both temporal positions -- profiled/unprofiled
      trade first/second position 1:1, cancelling any position-order
      confound (thermal drift, page-cache warmth) the #721 design could not
      distinguish from real instrumentation cost. The overhead and closure
      gates, and the verdict-grammar bootstrap, all consume the POOLED
      (arm A + arm B) samples -- 2x the statistical power of a single
      sequential block at no extra wall-clock cost per sample.
  (c) No integration fixture reached gates_all_passed=true (only predicate-
      table unit fixtures existed). REPAIRED by
      `_selftest_integration_all_gates_pass()`: runs the REAL attribution_run
      pipeline end-to-end on a tiny CPU fixture -- real fork/restore, real
      AB/BA blocks, real per-instance instrumented step() calls, real gate
      evaluation, real verdict classification -- with ONLY the fundamentally
      CUDA-only pinned/pageable calibration function stubbed to a disclosed
      synthetic dict (a real PCIe H2D/D2H number has no CPU-only meaning).
      Every other gate (step_count, overhead, closure, exact_bytes) passes or
      fails on its own real CPU-measured merits. The original `_selftest()`
      is unchanged and must still see gates_all_passed=False on an UNSTUBBED
      run -- proving the stub is disclosed and isolated to one fixture, not a
      silent lowering of the real gate.

Reuse discipline (unchanged from #721, restated): this script does NOT
reimplement Muon/AdamW/CE/WSD math. It builds the model/optimizer/loader via
the SAME production functions run_v0_segment calls (build_v0_model,
build_split_optimizer, split_param_groups, resolve_ce_impl, mtp_total_loss,
apply_wsd, PackedShardLoader, write_packed_shard, load_contract) against the
same frozen contract cfg. The outer step loop is necessarily its own
(run_v0_segment exposes no per-subphase timing hooks and none should be added
to the production training path just to profile it once). The ONE change
this revision makes to a production file is cpu_offload_adamw.py's step() --
adding default-off instrumentation hooks INSIDE the real method is exactly
what block-comment repair item (a) specifies; it is not a reimplementation
and every existing caller of CPUOffloadOptimizer.step() (tests/
test_stabilize_v9_cure.py included) sees byte-identical behavior when
unattached (the default).

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
from cpu_offload_adamw import nvidia_smi_vram, vram_preflight          # noqa: E402

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
    block and from the ATTACHED (real, in-place-instrumented) CPUOffload
    Optimizer.step() while a step is open. One collector instance is used
    for exactly one profiled block (a fresh instance per block keeps blocks
    from ever mixing samples); `_merge_collectors` combines multiple blocks'
    finished records (used to pool the AB/BA arms)."""

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


def _merge_collectors(collectors: list) -> SubphaseCollector:
    """Combines finished step_records from multiple SubphaseCollector
    instances (the AB/BA design's two profiled sub-blocks) into one, for
    gate evaluation and verdict classification over the POOLED sample."""
    merged = SubphaseCollector()
    for c in collectors:
        merged.step_records.extend(c.step_records)
        merged.realized_numel_total += c.realized_numel_total
    return merged


# ---------------------------------------------------------------------------
# Per-instance span-collector attach/detach -- ember #702
# BLOCK_721_PRODUCTION_ATTRIBUTION repair item (a). Attaches directly to the
# REAL CPUOffloadOptimizer instances (never a class-level monkeypatch, never
# a reimplementation of step()) -- see cpu_offload_adamw.py's own
# attach_span_collector()/detach_span_collector() for the instrumented sites.
# ---------------------------------------------------------------------------

def install_span_collector(optimizers: dict, collector: SubphaseCollector, *, device: str):
    import torch
    sync = (torch.cuda.synchronize if device == "cuda" and torch.cuda.is_available()
            else (lambda: None))
    for opt in optimizers.values():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            opt.attach_span_collector(
                add=collector.add, add_bytes=collector.add_bytes,
                add_numel=collector.add_realized_numel, sync=sync)


def uninstall_span_collector(optimizers: dict) -> None:
    for opt in optimizers.values():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            opt.detach_span_collector()


# ---------------------------------------------------------------------------
# AB/BA fork snapshot/restore -- ember #702 BLOCK_721_PRODUCTION_ATTRIBUTION
# repair item (b), DISK-BACKED per the mid-build capacity repair (auditor
# prelaunch review, coordinator disposition BLOCK_702_REPAIR_LIVE_AS_WRITTEN
# item 1). The first revision of this section held an IN-MEMORY .clone() of
# the entire fork (model weights + shadow params + optimizer state)
# concurrently with the live run for the whole of Arm A's execution -- on a
# full 2.2B live dispatch that adds ~4.09GiB extra VRAM (model weights, on
# top of a measured ~20GiB peak on a 24GiB card) and ~16.36GiB extra host
# commit (shadow + optimizer state), which the auditor's arithmetic showed
# pushes both resources over their limits. This revision writes the fork to
# DISK instead -- chosen over independently-reconstructed-fork-by-replay
# (the block comment's alternative (b)): this repo's own file-backed-memmap
# convention for CPUOffloadOptimizer state is already exactly "disk instead
# of a second in-memory copy" (cpu_offload_adamw.py's own module docstring),
# so a disk-backed fork snapshot is the SAME established pattern applied one
# level up, not a new one.
#
# model.state_dict() and a CPUOffloadOptimizer's _shadow/_inner.state are
# REFERENCES to the live tensors, not copies -- torch.save serializes their
# CURRENT bytes directly to a file with zero extra concurrent allocation at
# snapshot-write time. Restore loads each component (model, then each
# optimizer's shadow, then its inner state) SEQUENTIALLY, never concurrently,
# in-place copy_()s into the existing live tensors, and drops the loaded
# reference immediately -- bounding peak transient extra memory to the
# single LARGEST component, not the sum of all of them. mmap=True reads
# tensor bytes lazily (page-mapped from the file rather than eagerly
# materialized) -- the same "file-backed, zero pagefile-commit-charge" trick
# cpu_offload_adamw.py's own memmap tensors already rely on. In-place copy_()
# restore (never optimizer.load_state_dict, which reallocates NEW state
# tensors and would silently swap the file-backed memmap tensors this whole
# offload strategy exists to keep -- exactly the memory strategy under
# profiling) so both arms genuinely run against the identical,
# non-reallocated tensor objects the live run uses.
# ---------------------------------------------------------------------------

def _snapshot_rng(device: str) -> dict:
    import random
    import torch
    state = {"torch_cpu": torch.get_rng_state().clone(), "python_random": random.getstate()}
    if device == "cuda" and torch.cuda.is_available():
        state["torch_cuda"] = [t.clone() for t in torch.cuda.get_rng_state_all()]
    return state


def _restore_rng_(state: dict, *, device: str) -> None:
    import random
    import torch
    torch.set_rng_state(state["torch_cpu"])
    random.setstate(state["python_random"])
    if device == "cuda" and torch.cuda.is_available() and "torch_cuda" in state:
        torch.cuda.set_rng_state_all(state["torch_cuda"])


def _snapshot_fork(*, model, optimizers: dict, device: str, global_step: int,
                   fork_dir: Path) -> dict:
    """Writes the fork to fork_dir -- never held in memory as a whole. RNG
    state (a few KB) is the one piece kept in-memory in the returned dict;
    it is not a capacity concern at any scale."""
    import torch
    fork_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), str(fork_dir / "model_state.pt"))

    opt_meta: dict = {}
    for name, opt in optimizers.items():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            shadow_path = fork_dir / f"{name}.shadow.pt"
            state_path = fork_dir / f"{name}.inner_state.pt"
            torch.save(list(opt._shadow), str(shadow_path))
            # Positionally keyed (index i <-> opt._shadow[i]) -- the SAME
            # index-alignment convention timeshare_pretrain.py's
            # load_optimizers_state already documents for this optimizer
            # family ("same param order... state indices align").
            state_list = [dict(opt._inner.state.get(sp, {})) for sp in opt._shadow]
            torch.save(state_list, str(state_path))
            opt_meta[name] = {"kind": "coa", "shadow_path": str(shadow_path),
                              "state_path": str(state_path)}
        else:
            import copy
            path = fork_dir / f"{name}.plain_state.pt"
            torch.save(copy.deepcopy(opt.state_dict()), str(path))
            opt_meta[name] = {"kind": "plain", "path": str(path)}

    return {
        "fork_dir": str(fork_dir),
        "model_path": str(fork_dir / "model_state.pt"),
        "optimizers": opt_meta,
        "rng": _snapshot_rng(device),
        "global_step": global_step,
    }


def _restore_fork_(snapshot: dict, *, model, optimizers: dict, device: str) -> int:
    """Sequential, never-concurrent per-component load: model, then each
    optimizer's shadow, then its inner state -- each loaded, copy_()'d
    in-place into the live tensors, then dropped before the next component
    loads. weights_only=False: this repo's own trusted, same-run data (never
    externally sourced), and the inner-state dicts mix tensors with plain
    step counters -- weights_only=True would reject that structure."""
    import torch

    loaded_model_sd = torch.load(snapshot["model_path"], map_location="cpu",
                                 mmap=True, weights_only=False)
    with torch.no_grad():
        for k, v in model.state_dict().items():
            v.copy_(loaded_model_sd[k])
    del loaded_model_sd

    for name, opt in optimizers.items():
        meta = snapshot["optimizers"][name]
        if meta["kind"] == "coa":
            loaded_shadow = torch.load(meta["shadow_path"], map_location="cpu",
                                       mmap=True, weights_only=False)
            with torch.no_grad():
                for s, saved in zip(opt._shadow, loaded_shadow):
                    s.copy_(saved)
            del loaded_shadow

            loaded_state = torch.load(meta["state_path"], map_location="cpu",
                                      mmap=True, weights_only=False)
            with torch.no_grad():
                for shadow_p, saved_entry in zip(opt._shadow, loaded_state):
                    live_entry = opt._inner.state.get(shadow_p, {})
                    for k, v in saved_entry.items():
                        if isinstance(v, torch.Tensor):
                            if k in live_entry and isinstance(live_entry[k], torch.Tensor):
                                live_entry[k].copy_(v)
                            else:
                                live_entry[k] = v.clone()
                        else:
                            live_entry[k] = v
                    opt._inner.state[shadow_p] = live_entry
            del loaded_state
        else:
            loaded = torch.load(meta["path"], map_location="cpu", weights_only=False)
            opt.load_state_dict(loaded)

    _restore_rng_(snapshot["rng"], device=device)
    return snapshot["global_step"]


# ---------------------------------------------------------------------------
# Fail-closed fork-capacity preflight -- ember #702 mid-build repair item 3.
# abort-not-degrade, same discipline as cpu_offload_adamw.vram_preflight and
# this tree's other Windows-commit governors (cbase_grow_rung2_stabilize.py's
# _commit_margin_assert / _read_commit_gb): hold, report numbers, refuse,
# never proceed into the wall, never widen the floor to make a measurement
# pass. _read_commit_gib below duplicates (rather than imports) that
# module's ctypes read: cbase_grow_rung2_stabilize.py applies PROCESS-WIDE
# monkeypatches at IMPORT TIME (torch.nn.Module.load_state_dict,
# CPUOffloadOptimizer.load_state_dict) that this runner must not silently
# inherit just to reuse a 15-line memory read.
# ---------------------------------------------------------------------------

COMMIT_MARGIN_FLOOR_GIB = 6.0   # same floor value as this tree's other commit governors
VRAM_MARGIN_FLOOR_GIB = 2.0     # same floor as cpu_offload_adamw.vram_preflight's own default
DISK_MARGIN_FLOOR_GIB = 4.0     # spare disk headroom required beyond the snapshot's own bytes

# Bounded, fixed (never model/snapshot-size-scaled) allowances for the
# restore path's genuinely transient overhead -- ember #702 mid-build repair
# round 2 (independent falsifier re-test of the round-1 preflight): the
# round-1 preflight priced model_bytes against free VRAM and the FULL
# model+shadow+state snapshot sum against free host commit, as if the
# restore path materialized all of that a second time. It does not: model/
# shadow/state all restore via mmap=True sequential per-component loads,
# copy_()'d IN-PLACE into already-allocated destination tensors (model
# params on GPU; shadow/state on CPU), never reallocated -- so the true
# added VRAM and added (pagefile-backed) commit from restore are both ~0.
# At the measured real envelope (~19.98-20.04GiB peak VRAM used on a 24GiB
# card, ~4GiB free) the round-1 math required free_vram >= model_bytes
# (~4.09GiB) + 2GiB margin = ~6.09GiB -- a bound the real workload can NEVER
# clear, so the gate was safe-fail but undeliverable, not merely
# conservative. These two constants are the bounded staging-buffer
# allowance kept IN PLACE of the phantom charge, sized to cover the small
# non-mmap .clone() calls in _restore_fork_'s coa inner-state merge and
# Windows' del/GC commit-release lag -- not to price the snapshot itself.
VRAM_STAGING_BUFFER_GIB = 0.5
COMMIT_STAGING_BUFFER_GIB = 1.0


def _read_commit_gib() -> dict | None:
    """Ground-truth Windows commit via ONE in-process GlobalMemoryStatusEx
    call (ullAvailPageFile). Never raises -- returns None on any read
    failure (non-Windows interpreter, API failure), the same
    never-raises-on-read-failure contract every other commit-read helper in
    this tree uses; a failed read is disclosed, never treated as a
    violation."""
    import ctypes

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if not ok:
            return None
        gib = 1024.0 ** 3
        return {
            "committed_gib": round((stat.ullTotalPageFile - stat.ullAvailPageFile) / gib, 3),
            "limit_gib": round(stat.ullTotalPageFile / gib, 3),
            "free_gib": round(stat.ullAvailPageFile / gib, 3),
        }
    except Exception:
        return None


def _read_disk_free_gib(path: str) -> dict | None:
    """Ground-truth free disk space for the volume holding `path` (run_dir --
    already created by the time this fires, see attribution_run's
    os.makedirs). Never raises -- returns None on any read failure
    (nonexistent path, permissions), same never-raises-on-read-failure
    contract as _read_commit_gib; a failed read is disclosed, never treated
    as a violation."""
    import shutil
    try:
        usage = shutil.disk_usage(path)
        gib = 1024.0 ** 3
        return {
            "total_gib": round(usage.total / gib, 3),
            "used_gib": round(usage.used / gib, 3),
            "free_gib": round(usage.free / gib, 3),
        }
    except Exception:
        return None


def _tensor_bytes_in(obj) -> int:
    """Recursively sums .numel()*.element_size() over any torch.Tensor found
    inside obj (dict/list/tuple nesting, the shape torch optimizer
    state_dict()s use). Non-tensor leaves (step counters, etc.) contribute 0.
    Sizes exactly what a PLAIN (non-CPUOffloadOptimizer) optimizer's
    state_dict() would serialize -- mirrors _snapshot_fork's
    copy.deepcopy(opt.state_dict()) write path for that branch."""
    import torch
    if isinstance(obj, torch.Tensor):
        return obj.numel() * obj.element_size()
    if isinstance(obj, dict):
        return sum(_tensor_bytes_in(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_tensor_bytes_in(v) for v in obj)
    return 0


def _realized_fork_bytes(*, model, optimizers: dict) -> dict:
    """Sizes the fork snapshot from REALIZED tensor bytes actually present
    in THIS run (never a config-derived estimate) -- the exact numbers the
    torch.save calls in _snapshot_fork are about to write. model_bytes/
    shadow_bytes/state_bytes/plain_bytes together are the DISK-write sizing
    input (every one of these is written to a file under fork_dir). Only
    plain_bytes matters for the COMMIT preflight (see _preflight_fork_
    capacity): model/shadow/state all restore via mmap=True (file-backed,
    same zero-commit-charge convention this codebase's own CPUOffload
    Optimizer memmap tensors already rely on -- see _restore_fork_), so they
    add ~zero real host commit; a PLAIN optimizer's state_dict() restores via
    an ordinary (non-mmap) torch.load + load_state_dict, which DOES
    materialize real heap bytes -- currently size-0 in this runner's actual
    invocation path (build_split_optimizer is always called with
    offload_optimizer_state=True, so every entry in `optimizers` is a
    CPUOffloadOptimizer), kept as a real measured input rather than an
    assumption so a future caller adding a non-offloaded leg is priced
    correctly instead of silently under-priced."""
    import torch
    model_bytes = sum(v.numel() * v.element_size() for v in model.state_dict().values())
    shadow_bytes = 0
    state_bytes = 0
    plain_bytes = 0
    for opt in optimizers.values():
        if isinstance(opt, _coa.CPUOffloadOptimizer):
            shadow_bytes += sum(s.numel() * s.element_size() for s in opt._shadow)
            for shadow_p in opt._shadow:
                for v in opt._inner.state.get(shadow_p, {}).values():
                    if isinstance(v, torch.Tensor):
                        state_bytes += v.numel() * v.element_size()
        else:
            plain_bytes += _tensor_bytes_in(opt.state_dict())
    return {"model_bytes": model_bytes, "shadow_bytes": shadow_bytes,
            "state_bytes": state_bytes, "plain_bytes": plain_bytes}


def _write_capacity_refusal_receipt(result: dict, *, run_dir: str) -> str:
    import json
    import os
    receipt = {
        "ticket": "EMBER-702-ATTRIBUTION-FORK-CAPACITY-REFUSAL",
        "ts": _ts(),
        "issue": "wordingone/ember#702",
        "verdict": "GOVERNOR_CAPACITY_FAIL",
        **result,
        "api_spend_usd": 0, "paid_api_surface_used": False,
    }
    path = os.path.join(run_dir, f"attribution-702-fork-capacity-refusal-{receipt['ts']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, default=str)
    return path


def _preflight_fork_capacity(*, model, optimizers: dict, device: str, run_dir: str,
                             nvsmi: dict | None = None, commit: dict | None = None,
                             disk: dict | None = None) -> dict:
    """Fail-closed capacity assert BEFORE any fork-snapshot write. Sized from
    REALIZED tensor bytes (_realized_fork_bytes), not config, and from the
    ACTUAL restore path's exposure, not the snapshot's own size:

    - VRAM (device=='cuda' only): restore's real added VRAM is ~0 -- the
      model-state load is map_location=cpu, mmap=True, then copy_()'d
      IN-PLACE into model.state_dict()'s ALREADY-ALLOCATED GPU tensors
      (never reallocated). Priced against a bounded, fixed staging-buffer
      allowance (VRAM_STAGING_BUFFER_GIB), never model_bytes -- charging
      model_bytes here was a phantom cost the real restore path never
      incurs, and at the measured real envelope (~4GiB free on a 24GiB
      card at peak) made the gate permanently unclearable (mid-build repair
      round 2, independent falsifier re-test).
    - Host commit: model/shadow/state all restore via mmap=True (file-
      backed -- the SAME zero-commit-charge convention this codebase's own
      CPUOffloadOptimizer memmap tensors already rely on), so only a PLAIN
      (non-CPUOffloadOptimizer) optimizer's state -- which restores via an
      ordinary non-mmap torch.load -- is real, measured, materializing
      commit; this is currently always 0 bytes in this runner's actual
      invocation path (see _realized_fork_bytes). Priced as plain_gib plus
      a bounded staging-buffer allowance (COMMIT_STAGING_BUFFER_GIB) for
      _restore_fork_'s small non-mmap .clone() calls and Windows' del/GC
      commit-release lag -- never the full model+shadow+state snapshot sum
      (that sum is real DISK bytes, not simultaneous commit; charging it as
      commit was the second phantom cost).
    - Disk (new in this repair round): the fork snapshot's files (model +
      shadow + state + any plain state) ARE written to fork_dir as real,
      simultaneous bytes on disk before any restore happens -- sized
      against the FULL realized-bytes sum, never bounded to one component,
      because unlike restore the write is not sequential-with-drop.

    `nvsmi`/`commit`/`disk` are optional INJECTED measurement dicts (same
    pure-function-of-a-measured-dict pattern as cpu_offload_adamw.
    vram_preflight's own `nvsmi` parameter) -- when omitted each is measured
    for real; production call sites (attribution_run's live path) always
    omit all three. Only _selftest_fork_capacity_preflight() injects
    synthetic envelopes, to prove the PRICING LOGIC against known VRAM/
    disk states rather than depending on today's actual idle GPU/disk on
    whatever box runs the selftest.

    FAIL-CLOSED on an UNAVAILABLE required measurement -- ember #702
    mid-build repair round 3 (post-merge falsifier finding on the round-2
    head): the round-2 version treated a commit-read failure, a disk-read
    failure, or a VRAM-read exception as "disclosed, never a violation" and
    left result["sufficient"]=True -- fail-OPEN on exactly the inputs this
    gate exists to assert. "Disclosed skip" is legitimate ONLY for an
    INAPPLICABLE leg (VRAM when device != 'cuda' -- there is no GPU-side
    restore exposure to measure for a CPU run at all); every leg that IS
    applicable (commit and disk always; VRAM whenever device=='cuda') is
    REQUIRED, and an unmeasured required resource refuses, exactly like an
    insufficient one -- a capacity gate that cannot see a resource has not
    cleared it. Raises SystemExit with a written refusal receipt on
    insufficiency OR unavailability -- abort-not-degrade, no fix-forward,
    no widened floor."""
    sizes = _realized_fork_bytes(model=model, optimizers=optimizers)
    gib = 1024.0 ** 3
    total_write_gib = round(sum(sizes.values()) / gib, 3)
    plain_gib = round(sizes["plain_bytes"] / gib, 3)
    result = {"sizes_bytes": sizes, "total_write_gib": total_write_gib,
             "plain_gib": plain_gib, "vram": None, "commit": None, "disk": None,
             "sufficient": True, "refusal_reasons": []}

    def _refuse(reason: str) -> None:
        result["sufficient"] = False
        result["refusal_reasons"].append(reason)

    if device == "cuda":
        try:
            import torch
            if torch.cuda.is_available():
                vram_check = vram_preflight(VRAM_STAGING_BUFFER_GIB,
                                            margin_gib_floor=VRAM_MARGIN_FLOOR_GIB,
                                            nvsmi=nvsmi)
                result["vram"] = vram_check
                if not vram_check["sufficient"]:
                    _refuse(
                        f"VRAM margin insufficient for the restore path's "
                        f"bounded staging buffer: {vram_check}")
            else:
                # device=='cuda' makes VRAM an APPLICABLE, REQUIRED leg -- no
                # visible CUDA runtime means that required measurement is
                # UNAVAILABLE, not inapplicable.
                result["vram"] = {"error": "torch.cuda.is_available() is "
                                            "False for a device='cuda' preflight"}
                _refuse(
                    "VRAM measurement unavailable: device='cuda' but no CUDA "
                    "runtime visible in this process -- a required, "
                    "applicable measurement that could not be taken is a "
                    "refusal, never a silent pass")
        except Exception as e:
            result["vram"] = {"error": str(e)}
            _refuse(
                f"VRAM measurement raised an exception for a device='cuda' "
                f"preflight -- a required, applicable measurement that "
                f"could not be taken is a refusal, never a silent pass: {e}")
    # device != 'cuda': VRAM is INAPPLICABLE (no GPU-side restore exposure
    # exists to measure on a CPU run) -- result["vram"] stays None, a
    # legitimate disclosed skip, never a violation.

    commit_stat = commit if commit is not None else _read_commit_gib()
    result["commit"] = commit_stat
    if commit_stat is not None:
        commit_required_gib = round(plain_gib + COMMIT_STAGING_BUFFER_GIB, 3)
        commit_margin_gib = round(commit_stat["free_gib"] - commit_required_gib, 3)
        result["commit_required_gib"] = commit_required_gib
        result["commit_margin_gib"] = commit_margin_gib
        if commit_margin_gib < COMMIT_MARGIN_FLOOR_GIB:
            _refuse(
                f"host-commit margin insufficient for the restore path's plain-"
                f"optimizer bytes + staging buffer: free={commit_stat['free_gib']}"
                f"GiB, required={commit_required_gib}GiB, margin="
                f"{commit_margin_gib}GiB < floor={COMMIT_MARGIN_FLOOR_GIB}GiB")
    else:
        # commit is an ALWAYS-APPLICABLE, REQUIRED measurement (every host
        # has a commit limit) -- a read failure is UNAVAILABLE, not
        # inapplicable.
        _refuse(
            "host-commit measurement unavailable (read failure) -- an "
            "unmeasured required resource is a refusal, never a pass")

    disk_stat = disk if disk is not None else _read_disk_free_gib(run_dir)
    result["disk"] = disk_stat
    if disk_stat is not None:
        disk_margin_gib = round(disk_stat["free_gib"] - total_write_gib, 3)
        result["disk_margin_gib"] = disk_margin_gib
        if disk_margin_gib < DISK_MARGIN_FLOOR_GIB:
            _refuse(
                f"free disk insufficient for the fork snapshot write: free="
                f"{disk_stat['free_gib']}GiB, required={total_write_gib}GiB, "
                f"margin={disk_margin_gib}GiB < floor={DISK_MARGIN_FLOOR_GIB}GiB")
    else:
        # disk is an ALWAYS-APPLICABLE, REQUIRED measurement -- a read
        # failure is UNAVAILABLE, not inapplicable.
        _refuse(
            "free-disk measurement unavailable (read failure) -- an "
            "unmeasured required resource is a refusal, never a pass")

    result["refusal"] = " | ".join(result["refusal_reasons"]) or None

    if not result["sufficient"]:
        receipt_path = _write_capacity_refusal_receipt(result, run_dir=run_dir)
        print(f"ATTRIBUTION_702_FORK_CAPACITY_REFUSED receipt={receipt_path} "
              f"refusal={result['refusal']}", flush=True)
        raise SystemExit(
            f"ATTRIBUTION_702_FORK_CAPACITY_REFUSED: {result['refusal']} -- "
            f"abort-not-degrade, no fix-forward, no widened floor (receipt={receipt_path})")
    return result


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
    boundaries into `collector` AND expects the caller to have already
    install_span_collector()'d the SAME collector onto `optimizers` (so the
    real, in-place-instrumented CPUOffloadOptimizer.step() calls land in the
    same open step record) -- this function does not attach/detach the
    optimizer-level hooks itself, the caller brackets a whole profiled block
    with them. profile=False adds ZERO extra instrumentation calls and
    expects the caller to have detached any span collector from
    `optimizers` first -- the matched-unprofiled-block baseline. Returns the
    list of measured step-wall times (perf_counter, device-synced)."""
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


def _run_counterbalanced_ab_ba(*, model, loader, optimizers, base_lrs, cfg, ce_fn,
                                mtp_enabled, mtp_weight, ce_chunk_tokens, device,
                                batch_size, total_steps, n_active: int,
                                fork_global_step: int, run_dir: str) -> dict:
    """AB/BA counterbalanced overhead measurement -- ember #702
    BLOCK_721_PRODUCTION_ATTRIBUTION repair item (b). Both arms fork from the
    IDENTICAL post-warmup snapshot (model + every optimizer's mutable state +
    both RNG streams; loader state reduces to the shared starting global_step
    since PackedShardLoader.batch is a pure function of step). Arm A runs
    profiled-then-unprofiled; the fork is restored byte-for-byte; Arm B runs
    unprofiled-then-profiled from the identical restored state. Both arms
    therefore traverse the SAME absolute step range [fork_global_step,
    fork_global_step + 2*n_active) -- every step-slot in that range is
    measured once profiled and once unprofiled, at swapped temporal
    positions, cancelling any order confound (thermal drift, page-cache
    warmth) a single fixed-order design cannot distinguish from real
    instrumentation cost. Returns pooled wall-time lists, the merged
    subphase collector, and the per-arm breakdown (for receipt disclosure /
    falsifiability of the counterbalancing itself).

    A fail-closed capacity preflight (ember #702 mid-build repair item 3)
    runs BEFORE the fork snapshot is written -- refuses (named receipt under
    run_dir, SystemExit, no fix-forward) rather than writing a snapshot into
    insufficient VRAM/commit margin. The fork itself is DISK-BACKED under
    run_dir/fork_snapshot (mid-build repair item 1, see the section header
    above _snapshot_fork), never an in-memory clone held for the whole of
    Arm A's execution."""
    common = dict(model=model, loader=loader, optimizers=optimizers, base_lrs=base_lrs,
                 cfg=cfg, ce_fn=ce_fn, mtp_enabled=mtp_enabled, mtp_weight=mtp_weight,
                 ce_chunk_tokens=ce_chunk_tokens, device=device, batch_size=batch_size,
                 total_steps=total_steps)

    # ember #702 mid-build repair round 3: the preflight's successful result
    # was previously discarded (call for its side effect only) -- carried
    # into the final receipt below so a claim-bearing output PRESERVES the
    # realized sizes, margins, and all three measurement dicts a downstream
    # reader could recheck, rather than only the fact that SOME preflight
    # ran and did not raise.
    preflight_result = _preflight_fork_capacity(
        model=model, optimizers=optimizers, device=device, run_dir=run_dir)
    fork_dir = Path(run_dir) / "fork_snapshot"
    fork0 = _snapshot_fork(model=model, optimizers=optimizers, device=device,
                           global_step=fork_global_step, fork_dir=fork_dir)

    # ---- Arm A: profiled, then unprofiled ----
    collector_a = SubphaseCollector()
    install_span_collector(optimizers, collector_a, device=device)
    try:
        profiled_walls_a = _run_block(global_step_start=fork_global_step, n_steps=n_active,
                                      profile=True, collector=collector_a, **common)
    finally:
        uninstall_span_collector(optimizers)
    unprofiled_walls_a = _run_block(global_step_start=fork_global_step + n_active,
                                    n_steps=n_active, profile=False, collector=None, **common)

    # ---- restore to the identical fork point ----
    restored_step = _restore_fork_(fork0, model=model, optimizers=optimizers, device=device)
    assert restored_step == fork_global_step, (restored_step, fork_global_step)

    # ---- Arm B: unprofiled, then profiled (from the SAME restored state) ----
    unprofiled_walls_b = _run_block(global_step_start=restored_step, n_steps=n_active,
                                    profile=False, collector=None, **common)
    collector_b = SubphaseCollector()
    install_span_collector(optimizers, collector_b, device=device)
    try:
        profiled_walls_b = _run_block(global_step_start=restored_step + n_active,
                                      n_steps=n_active, profile=True, collector=collector_b,
                                      **common)
    finally:
        uninstall_span_collector(optimizers)

    return {
        "profiled_walls": profiled_walls_a + profiled_walls_b,
        "unprofiled_walls": unprofiled_walls_a + unprofiled_walls_b,
        "collector": _merge_collectors([collector_a, collector_b]),
        "arm_a": {"order": "profiled_first", "profiled_walls_s": profiled_walls_a,
                  "unprofiled_walls_s": unprofiled_walls_a},
        "arm_b": {"order": "unprofiled_first", "profiled_walls_s": profiled_walls_b,
                  "unprofiled_walls_s": unprofiled_walls_b},
        "fork_global_step": fork_global_step,
        "post_run_global_step": fork_global_step + 2 * n_active,
        "preflight": preflight_result,
    }


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
        "n_active_pooled_ab_ba": len(profiled_walls),
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
        "design": "counterbalanced_ab_ba_pooled",
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
    """Runs warmup -> counterbalanced AB/BA blocks (repair item (b)) ->
    pinned/pageable calibration, evaluates every validity gate FAIL-CLOSED
    over the POOLED AB/BA samples, and returns the receipt dict (not yet
    written to disk -- see main())."""
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

    # optstate_dir is ALWAYS a per-invocation-unique path derived from run_dir
    # (itself unique per call -- a fresh tempdir on every selftest/CLI
    # invocation), never omitted -- ember #702 mid-build isolation repair.
    # The shared global default (cpu_offload_adamw._DEFAULT_OPTSTATE_DIR) is
    # therefore unreachable from this runner: a selftest's tiny-model param
    # names (or a live run racing another live run) can never collide with
    # or truncate another invocation's file-backed shadow/state.
    optimizers, base_lrs, routing = ts.build_split_optimizer(
        model, cfg, offload_optimizer_state=True,
        deviation_dir=os.path.join(run_dir, "deviations"),
        optstate_dir=os.path.join(run_dir, "optstate"))
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
    _run_block(global_step_start=0, n_steps=n_warmup, profile=False,
              collector=None, **common)

    # ---- counterbalanced AB/BA blocks (repair item (b)) ----
    ab_ba = _run_counterbalanced_ab_ba(
        n_active=n_active, fork_global_step=n_warmup, run_dir=run_dir, **common)
    collector = ab_ba["collector"]

    calibration = calibrate_pinned_vs_pageable(device=device)

    gates = _evaluate_gates(
        n_warmup=n_warmup, n_active=n_active,
        profiled_walls=ab_ba["profiled_walls"], unprofiled_walls=ab_ba["unprofiled_walls"],
        collector=collector, expected_full_numel=expected_full_numel, calibration=calibration)
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
            "block_comment_repair": {
                "disposition": "BLOCK_721_PRODUCTION_ATTRIBUTION",
                "item_a": "instrumentation moved INSIDE the original "
                          "CPUOffloadOptimizer.step() -- per-instance "
                          "attach_span_collector()/detach_span_collector(), "
                          "default-off; no reimplementation of step() exists "
                          "in this runner",
                "item_b": "overhead gate redesigned as counterbalanced AB/BA "
                          "from an identical forked snapshot (model + "
                          "optimizer state + RNG streams; loader state = "
                          "shared starting global_step, since batch() is a "
                          "pure function of step)",
                "item_c": "_selftest_integration_all_gates_pass() -- real "
                          "pipeline, real gates, gates_all_passed=True on a "
                          "CPU fixture with only the CUDA-only calibration "
                          "function stubbed",
            },
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
        "ab_ba_design": {
            "fork_global_step": ab_ba["fork_global_step"],
            "post_run_global_step": ab_ba["post_run_global_step"],
            "arm_a": {"order": ab_ba["arm_a"]["order"],
                      "profiled_walls_s": ab_ba["arm_a"]["profiled_walls_s"],
                      "unprofiled_walls_s": ab_ba["arm_a"]["unprofiled_walls_s"]},
            "arm_b": {"order": ab_ba["arm_b"]["order"],
                      "profiled_walls_s": ab_ba["arm_b"]["profiled_walls_s"],
                      "unprofiled_walls_s": ab_ba["arm_b"]["unprofiled_walls_s"]},
        },
        # ember #702 mid-build repair round 3: the successful fork-capacity
        # preflight's full record (realized sizes, margins, all three
        # measurement dicts) -- previously discarded once the preflight
        # passed. A claim-bearing receipt PRESERVES what was measured, not
        # just that a check ran.
        "fork_capacity_preflight": ab_ba["preflight"],
        "subphase_totals_s": totals,
        "subphase_byte_totals": collector.byte_totals(),
        "per_step_span_ratios": ratios,
        "profiled_step_walls_s": collector.step_walls(),
        "unprofiled_step_walls_s": ab_ba["unprofiled_walls"],
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
# _classify_verdict_predicates via the UNSTUBBED path (gates never all-pass
# without a CUDA device, so the verdict grammar is unreachable from that path
# on this box -- see _selftest() for why that must stay true). This is the
# second pre-run amendment's own requirement (comment id 4939674864: "the
# runner's selftest must include one synthetic profile per verdict class")
# -- tests the predicate table directly and independently of the gate
# pipeline.
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
# path with tiny fixture dims, no GPU, no daemon, < 30s. UNSTUBBED: this is
# the honest, real-hardware-constrained path and must keep failing closed on
# the calibration gate.
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
    assert gates["step_count"]["n_active_pooled_ab_ba"] == 20, gates["step_count"]

    # subphase decomposition actually fired for all four optimizer sites plus
    # fwd/loss/bwd, with nonzero wall time and nonzero realized-numel bytes,
    # POOLED across both AB/BA profiled sub-blocks.
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

    # AB/BA counterbalanced design: both arms present, orders swapped, each
    # arm contributed n_active profiled + n_active unprofiled samples.
    ab = receipt["ab_ba_design"]
    assert ab["arm_a"]["order"] == "profiled_first" and ab["arm_b"]["order"] == "unprofiled_first"
    assert len(ab["arm_a"]["profiled_walls_s"]) == 10 and len(ab["arm_b"]["profiled_walls_s"]) == 10
    assert len(ab["arm_a"]["unprofiled_walls_s"]) == 10 and len(ab["arm_b"]["unprofiled_walls_s"]) == 10
    assert len(receipt["unprofiled_step_walls_s"]) == 20
    assert len(receipt["profiled_step_walls_s"]) == 20

    # per_step_span_ratios is populated even on a gates-failed (INVALID) run
    # -- the amendment's ratios/CI machinery is independent of the gate
    # pipeline; only the LABEL (verdict) is gated.
    assert set(receipt["per_step_span_ratios"]) == {
        "stage_ratio", "inner_ratio", "gpu_ratio", "host_unavoidable_ratio",
        "stage_plus_host_unavoidable_ratio"}
    assert len(receipt["per_step_span_ratios"]["stage_ratio"]) == 20

    print("ATTRIBUTION_702_SELFTEST_PASS "
          f"verdict={receipt['verdict']} failing_gates={receipt['failing_gates']} "
          f"n_optimizer_subphase_s={sum(totals[p] for p in OPTIMIZER_SUBPHASES):.6f} "
          f"n_fwd_loss_bwd_s={sum(totals[p] for p in FWD_LOSS_BWD_PHASES):.6f} "
          f"realized_numel_per_step={gates['exact_bytes']['realized_numel_per_step']} "
          f"closure_frac={gates['closure']['closure_frac']}", flush=True)

    _selftest_verdict_predicates()
    _selftest_span_collector_attach_detach()
    _selftest_integration_all_gates_pass()
    _selftest_fork_capacity_preflight()
    return 0


def _selftest_span_collector_attach_detach() -> None:
    """Direct unit check of ember #702 repair item (a): attach/detach is
    per-INSTANCE (a second, unattached instance is never affected), step()
    is byte-identical whether attached or not (same tensor values after one
    step from identical starting state, attached vs unattached), and detach
    actually clears the hooks (no leak past the profiled block)."""
    import tempfile

    import torch

    def _make_opt(tag: str):
        p = torch.nn.Parameter(torch.randn(4, 4))
        p.grad = torch.randn(4, 4)
        d = tempfile.mkdtemp(prefix=f"coa_span_selftest_{tag}_")
        opt = _coa.CPUOffloadOptimizer(
            [("w", p)], lambda ps: torch.optim.AdamW(ps, lr=1e-2, weight_decay=0.0),
            optstate_dir=d)
        return p, opt

    # ---- byte-identical step() with vs without an attached collector ----
    torch.manual_seed(1)
    p1, opt1 = _make_opt("unattached")
    torch.manual_seed(1)
    p2, opt2 = _make_opt("attached")
    assert torch.equal(p1.data, p2.data), "fixture setup diverged before any step()"

    events: list = []
    opt2.attach_span_collector(
        add=lambda phase, dt: events.append(("add", phase)),
        add_bytes=lambda phase, n: events.append(("bytes", phase)),
        add_numel=lambda n: events.append(("numel", n)),
        sync=lambda: None)
    assert opt2._span_add is not None

    opt1.step()
    opt2.step()
    assert torch.equal(p1.data, p2.data), (
        "attach_span_collector changed step()'s numerical result -- "
        "instrumentation must be observation-only")
    assert any(name == "add" and phase in OPTIMIZER_SUBPHASES for name, phase in events), (
        "attached collector never received any span -- instrumentation did not fire")
    fired_phases = {phase for name, phase in events if name == "add"}
    assert fired_phases == set(OPTIMIZER_SUBPHASES), fired_phases

    opt2.detach_span_collector()
    assert opt2._span_add is None
    events.clear()
    opt1.step()
    opt2.step()
    assert torch.equal(p1.data, p2.data), "post-detach step() diverged"
    assert events == [], f"detached collector still received spans: {events}"

    print("ATTRIBUTION_702_SPAN_COLLECTOR_ATTACH_DETACH_SELFTEST_PASS", flush=True)


def _selftest_integration_all_gates_pass() -> None:
    """Integration fixture -- ember #702 BLOCK_721_PRODUCTION_ATTRIBUTION
    repair item (c). Runs the REAL attribution_run() pipeline end-to-end on
    CPU: real fork/restore, real AB/BA counterbalanced blocks, real per-
    instance instrumented CPUOffloadOptimizer.step() calls, real gate
    evaluation, real verdict classification. Asserts gates_all_passed=True
    with a genuine (non-INVALID) verdict from VERDICT_GRAMMAR.

    Every gate except pinned_pageable_calibration is measured for real on
    this tiny CPU fixture. That ONE gate is fundamentally CUDA-only (a real
    PCIe H2D/D2H throughput number has no CPU-only meaning) and is STUBBED
    here to a disclosed, structurally valid synthetic dict for the duration
    of this fixture only (module-global monkeypatch, restored in a finally
    block regardless of outcome) -- this is the ONLY thing this fixture
    fakes. It does not touch step_count, overhead, closure, or exact_bytes,
    which all pass or fail on their own real CPU-measured merits; if any of
    those is broken, this fixture fails honestly rather than masking it.

    The production _selftest() above is UNCHANGED and still asserts
    gates_all_passed=False on an unstubbed run -- proving this fixture's
    stub is disclosed and isolated to itself, not a silent lowering of the
    real gate."""
    import random
    import tempfile

    import torch

    torch.manual_seed(7)
    random.seed(7)

    # Dims larger than _selftest()'s (hidden=32/depth=2/seq=16), deliberately:
    # this fixture's overhead/closure gates are REAL timing measurements, and
    # on a too-tiny model the fixed Python-level cost of the instrumentation
    # calls themselves (perf_counter/sync/callback dispatch) is a large
    # enough fraction of each (otherwise near-instant) tensor op to blow the
    # 10%/5% bounds on pure measurement noise. Re-swept at these dims after
    # the fork snapshot/restore went disk-backed (mid-build capacity repair,
    # item 1): the one-time real disk I/O per AB/BA invocation (torch.save/
    # torch.load around the fork, sharing the same disk as
    # CPUOffloadOptimizer's own per-step memmap I/O) adds enough timing
    # jitter that the PRIOR fixture (hidden=256/seq=32/n_active=14, tuned
    # against the in-memory-clone fork) intermittently failed the overhead
    # gate (observed 15.6%/31.9% against the 10% bound, 2 of 10 real CLI
    # invocations) -- a genuine regression the deeper sweep below is chosen
    # to survive, not a fluke. 20 seeds at these dims: overhead 0.2-5.8%,
    # closure 1.3-1.5%, both comfortably inside bound with margin.
    cfg = {
        "model": {"seq": 64, "vocab": 64, "hidden": 384, "tied_embeddings": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 2, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"warmup_frac": 0.1, "stable_until_frac": 0.8, "decay_to_lr_frac": 0.1},
        "throughput": {"batch": 2},
    }
    tiny_dims = {"vocab": 64, "hidden": 384, "depth": 3, "seq": 64}
    run_dir = tempfile.mkdtemp(prefix="attribution702_integration_")

    synthetic_calibration = {
        "skipped": False, "n_bytes_per_trial": 1 << 24, "n_trials": 5,
        "h2d_pageable_gbps": 8.0, "h2d_pinned_gbps": 14.0,
        "d2h_pageable_gbps": 7.5, "d2h_pinned_gbps": 13.0,
        "pcie4_x16_peak_gbps": 31.508,
        "h2d_pinned_vs_pageable_speedup": 1.75, "d2h_pinned_vs_pageable_speedup": 1.733,
        "note": ("SYNTHETIC -- integration-fixture stub, CPU has no real PCIe "
                 "H2D/D2H path to measure. Every other gate in this receipt is "
                 "computed for real from a live CPU run."),
    }

    module = sys.modules[__name__]
    _orig_calibrate = module.calibrate_pinned_vs_pageable

    def _stub_calibrate(*, device: str, **kwargs):
        return dict(synthetic_calibration)

    module.calibrate_pinned_vs_pageable = _stub_calibrate
    try:
        receipt = attribution_run(
            live=False, cfg=cfg, shard_dir=None, run_dir=run_dir, device="cpu",
            tiny_dims=tiny_dims, batch_size=2, n_warmup=2, n_active=24, ce_chunk_tokens=32)
    finally:
        module.calibrate_pinned_vs_pageable = _orig_calibrate

    gates = receipt["gates"]
    assert receipt["gates_all_passed"] is True, (
        "integration fixture must reach gates_all_passed=True with only the "
        f"CUDA-only calibration gate stubbed -- got gates={gates}")
    for gate_name in ("step_count", "overhead", "closure", "exact_bytes"):
        assert gates[gate_name]["passed"] is True, (gate_name, gates[gate_name])
    assert gates["pinned_pageable_calibration"]["calibration"]["note"].startswith("SYNTHETIC"), (
        "the stub must be disclosed IN the receipt, not silently swapped in")
    assert receipt["verdict"] in VERDICT_GRAMMAR, (
        f"integration fixture must classify a real, non-INVALID verdict, "
        f"got {receipt['verdict']!r}")
    assert receipt["failing_gates"] == []

    print("ATTRIBUTION_702_INTEGRATION_ALL_GATES_PASS_SELFTEST_PASS "
          f"verdict={receipt['verdict']} "
          f"gates_all_passed={receipt['gates_all_passed']}", flush=True)


def _selftest_fork_capacity_preflight() -> None:
    """ember #702 mid-build repair rounds 2+3: proves _preflight_fork_
    capacity prices the ACTUAL restore-path exposure (bounded staging
    buffers + any real plain-optimizer bytes), never the phantom full-
    model/full-snapshot charges round 1 used (round 2) -- AND fails CLOSED,
    never open, on an unavailable required measurement (round 3, a post-
    merge falsifier finding on the round-2 head: monkeypatched read
    failures returned sufficient=True). Five assertions:

    1. CLEARS at a simulated 20GiB-VRAM-used envelope (24GiB card, ~4GiB
       free) with ample disk -- the exact real-world peak this repo's own
       measurements put the live 2.2B dispatch at, which the round-1
       preflight (pricing model_bytes~=4.09GiB + 2GiB margin against ~4GiB
       free) could NEVER clear -- safe-fail but undeliverable, not merely
       conservative.
    2. REFUSES under genuinely low free disk -- proves the disk check
       actually fires, not just that it exists.
    3. REFUSES when the commit measurement is UNAVAILABLE (module-level
       _read_commit_gib monkeypatched to return None) -- round 1/2 treated
       this as "disclosed, never a violation" and left sufficient=True;
       commit is an ALWAYS-APPLICABLE, REQUIRED measurement, so an
       unavailable read is a refusal, not a skip.
    4. REFUSES when the disk measurement is UNAVAILABLE (module-level
       _read_disk_free_gib monkeypatched to return None) -- same class of
       fix as #3.
    5. REFUSES when the VRAM measurement RAISES (a malformed nvsmi dict
       missing "free_gib") -- round 1/2 recorded {"error": ...} without
       setting sufficient=False; device=='cuda' makes VRAM an APPLICABLE,
       REQUIRED leg, so an exception during its measurement is a refusal,
       not a silently-absorbed error.

    nvsmi/disk are INJECTED synthetic measurement dicts (same pure-function-
    of-a-measured-dict pattern as vram_preflight's own `nvsmi` param); the
    commit/disk UNAVAILABLE fixtures monkeypatch the module-level read
    functions themselves (the same try/finally-restored pattern
    _selftest_integration_all_gates_pass already uses for
    calibrate_pinned_vs_pageable) since `commit=None`/`disk=None` as
    KEYWORD ARGUMENTS mean "measure for real" by design, not "force a read
    failure" -- the monkeypatch is the only way to inject that state
    deterministically. This proves the PRICING AND FAIL-CLOSED LOGIC
    against known envelopes, not today's actual idle GPU/disk/commit state
    on whatever box happens to run this selftest. Skips (disclosed, never a
    silent pass) if this process has no CUDA device at all -- the VRAM leg
    of this gate is fundamentally CUDA-only, same disclosed-skip discipline
    as calibrate_pinned_vs_pageable."""
    import tempfile

    import torch
    import torch.nn as nn

    if not torch.cuda.is_available():
        print("ATTRIBUTION_702_FORK_CAPACITY_PREFLIGHT_SELFTEST_SKIP "
              "reason=cuda_unavailable_in_this_process -- disclosed skip, "
              "never a silent pass", flush=True)
        return

    # Empty optimizers dict: this selftest targets the PRICING ARITHMETIC
    # itself (already exercised end-to-end against a real CPUOffloadOptimizer
    # by _selftest_integration_all_gates_pass), so model_bytes is the only
    # realized size in play -- and, by design, no longer matters to the VRAM
    # check at all (that's exactly the bug being proven fixed).
    model = nn.Linear(64, 64)
    optimizers: dict = {}
    run_dir = tempfile.mkdtemp(prefix="attribution702_capacity_preflight_")

    simulated_nvsmi_20gib_used = {
        "total_mib": 24576, "used_mib": 20480, "free_mib": 4096,
        "total_gib": 24.0, "used_gib": 20.0, "free_gib": 4.0,
    }
    ample_disk = {"total_gib": 500.0, "used_gib": 100.0, "free_gib": 400.0}

    # ---- 1: CLEARS at the measured real envelope ----
    result_clear = _preflight_fork_capacity(
        model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
        nvsmi=simulated_nvsmi_20gib_used, disk=ample_disk)
    assert result_clear["sufficient"] is True, (
        "gate must CLEAR at the measured real envelope (~4GiB free VRAM on "
        f"a 24GiB card, ample disk) -- got {result_clear}")
    assert result_clear["vram"]["sufficient"] is True, result_clear["vram"]

    # ---- 2: REFUSES under genuinely low free disk ----
    low_disk = {"total_gib": 500.0, "used_gib": 499.99, "free_gib": 0.01}
    low_disk_refused = False
    try:
        _preflight_fork_capacity(
            model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
            nvsmi=simulated_nvsmi_20gib_used, disk=low_disk)
    except SystemExit:
        low_disk_refused = True
    assert low_disk_refused, (
        "gate must REFUSE (SystemExit) under genuinely low free disk")

    module = sys.modules[__name__]

    # ---- 3: REFUSES when commit measurement is UNAVAILABLE (read failure) ----
    _orig_read_commit_gib = module._read_commit_gib
    module._read_commit_gib = lambda: None
    commit_none_refused = False
    try:
        try:
            _preflight_fork_capacity(
                model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
                nvsmi=simulated_nvsmi_20gib_used, disk=ample_disk)
        except SystemExit:
            commit_none_refused = True
    finally:
        module._read_commit_gib = _orig_read_commit_gib
    assert commit_none_refused, (
        "gate must REFUSE when the commit measurement is UNAVAILABLE (read "
        "failure), not silently pass -- this is the exact fail-open the "
        "round-3 post-merge falsifier caught")

    # ---- 4: REFUSES when disk measurement is UNAVAILABLE (read failure) ----
    _orig_read_disk_free_gib = module._read_disk_free_gib
    module._read_disk_free_gib = lambda path: None
    disk_none_refused = False
    try:
        try:
            _preflight_fork_capacity(
                model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
                nvsmi=simulated_nvsmi_20gib_used)
        except SystemExit:
            disk_none_refused = True
    finally:
        module._read_disk_free_gib = _orig_read_disk_free_gib
    assert disk_none_refused, (
        "gate must REFUSE when the disk measurement is UNAVAILABLE (read "
        "failure), not silently pass")

    # ---- 5: REFUSES when VRAM measurement RAISES (malformed nvsmi) ----
    vram_error_refused = False
    try:
        _preflight_fork_capacity(
            model=model, optimizers=optimizers, device="cuda", run_dir=run_dir,
            nvsmi={"bogus": True}, disk=ample_disk)
    except SystemExit:
        vram_error_refused = True
    assert vram_error_refused, (
        "gate must REFUSE when the VRAM measurement raises an exception, "
        "not record {'error': ...} and silently pass")

    print("ATTRIBUTION_702_FORK_CAPACITY_PREFLIGHT_SELFTEST_PASS "
          f"clear_vram_margin_gib={result_clear['vram']['margin_gib']} "
          f"clear_sufficient={result_clear['sufficient']} "
          f"low_disk_refused={low_disk_refused} "
          f"commit_none_refused={commit_none_refused} "
          f"disk_none_refused={disk_none_refused} "
          f"vram_error_refused={vram_error_refused}", flush=True)


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
