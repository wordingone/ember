#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cpu_offload_adamw.py — CPU-offloaded optimizer-state wrapper (DEV-002 cure
candidate 3/4: "CPU-offloaded optimizer states (8N in host RAM, step on CPU
or paged)").

Reuse discipline (no duplicated optimizer math): `CPUOffloadOptimizer` does
NOT reimplement AdamW/Muon's update rule. It shuttles grads/params between
the real (possibly VRAM-resident) parameter tensors and a shadow fp32 copy
held in host RAM, then delegates the actual step to a REAL instance of the
caller's own optimizer class (torch.optim.AdamW, or timeshare_pretrain's
Muon) bound to that shadow copy. Same optimizer class, same defaults, same
math -- DEV-002's own framing ("Training semantics are UNCHANGED: same
tokens, same effective batch, same optimizer math. The deviation is a
memory-strategy substitution.") is enforced by construction here, not by
promise: the wrapper never touches the arithmetic, only where it executes
and where its state tensors live.

Cost model this removes from VRAM (DEV-002 wall, receipts/grow-operator-
dryrun-20260708T060841Z.json): the 8N-byte-per-param optimizer-state term
(2 fp32 moment buffers/param at the conservative AdamW-equivalent bound) --
the dominant term in the 30.903GiB estimate against a 23.988GiB card. This
module also prices the SMALLER footprint the offloaded strategy leaves in
VRAM (weights + grad + activations only) and the host-RAM cost it now
carries, using the same ground-truth-over-estimate discipline (nvidia-smi
over torch.cuda.mem_get_info on this WDDM host, per the dry-run receipt's
measured discrepancy) as src/ember/governance/scripts/cbase_grow_rung2_dryrun.py's own preflight.

No git commits from this module. No founder/user names. api_spend_usd
implications: none (CPU-only module; no paid API surface).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

BYTES_PER_PARAM_WEIGHTS_BF16 = 2
BYTES_PER_PARAM_GRAD_BF16 = 2
BYTES_PER_PARAM_OPTIMIZER_FP32 = 4 * 2  # 2 fp32 moment buffers/param (host RAM now, not VRAM)

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_OPTSTATE_DIR = _REPO / "scratch" / "rung2-optstate"


# ---- observability counters (ember #627 point 3) --------------------------
# Process-global counters so a consumer across the run_v0_segment call
# boundary (cbase_grow_rung2_stabilize._run_block, which does NOT hold the
# optimizer instance) can read them at a block boundary. grad_lazy_creates is
# THE falsifier the withdrawn prereg's P2 prediction lacked: it counts every
# time step() re-creates a `.grad.f32` memmap through the lazy fallback -- the
# exact M1 term (governed subprocess re-fire per re-create per step) the v9
# cure eliminates. In the cured steady state it stays 0; a positive-control
# test (tests/test_stabilize_v9_cure.py) forces one and asserts it fires, so
# the counter is proven able to detect the failure it guards, never vacuously
# green. Instance mirrors (self.grad_lazy_creates) exist for single-optimizer
# unit assertions; the module counter is the cross-boundary observability
# surface.
_COUNTERS = {"grad_lazy_creates": 0}


def get_counter(name: str) -> int:
    return int(_COUNTERS.get(name, 0))


def reset_counters() -> None:
    for k in list(_COUNTERS):
        _COUNTERS[k] = 0


def _sanitize_name(name: str) -> str:
    return name.replace(".", "_")


def _memmap_zeros(path: Path, shape: tuple, dtype=None):
    """A fresh, zero-initialized, file-backed CPU tensor. File-backed pages
    charge no Windows commit (vs the pagefile-backed regular heap allocations
    this replaces) -- root cause of 2026-07-08's crash sites, see module
    docstring. mode='w+' always creates/truncates fresh.

    arr[:] = 0 is an INFORMED CHOICE, not a defensive habit: NTFS already
    guarantees zeros for unwritten extents of a fresh file, so this line buys
    nothing for correctness. What it buys is reliability ordering -- writing
    the full ~shape*4 bytes now forces the OS to actually allocate those disk
    blocks at construction time, so a disk-full condition surfaces HERE
    (upfront, at optimizer-init, cheap to recover from) instead of mid-step
    deep inside an optimizer update (expensive, opaque, potentially mid-
    training-run). The cost is a full write pass over ~25GiB of buffers at
    construction -- traded deliberately for turning a potential mid-run
    failure into a pre-flight one, same abort-not-degrade discipline as the
    rest of this module."""
    import numpy as np
    import torch

    dtype = dtype or np.float32
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.memmap(str(path), dtype=dtype, mode="w+", shape=shape)
    arr[:] = 0
    arr.flush()
    return torch.from_numpy(arr)


def _memmap_from_tensor(path: Path, src):
    """Same as _memmap_zeros but seeded with src's real values (for the
    shadow parameter copy, which must start at the real weight, not zero).
    Casts to fp32 CPU BEFORE .numpy() -- a bf16 tensor (the real params, in
    production) has no native numpy dtype and .numpy() raises on it."""
    import numpy as np
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    src_f32_cpu = src.detach().to("cpu", dtype=torch.float32)
    arr = np.memmap(str(path), dtype=np.float32, mode="w+", shape=tuple(src_f32_cpu.shape))
    arr[:] = src_f32_cpu.numpy()
    arr.flush()
    return torch.from_numpy(arr)


class CPUOffloadOptimizer:
    """Wraps an existing torch.optim.Optimizer-shaped constructor so its
    per-parameter state (shadow weight, grad, and the inner optimizer's own
    moment/momentum buffers) lives in FILE-BACKED host storage and its
    step() arithmetic executes on CPU tensors, while the real params it
    updates may live anywhere (GPU or CPU).

    File-backed, not just "host RAM" (redesigned 2026-07-08, issue #446
    follow-up): a regular CPU tensor's backing pages charge Windows COMMIT
    (physical RAM + pagefile), and this box's pagefile is a small fixed
    16GiB -- the real, unifying cause of every native crash (ACCESS_VIOLATION/
    SIGSEGV) hit across widen_state_dict, this class's own grad-clone, and
    the CPU-side probe launches that day, per the measured commit-exhaustion
    receipt (commit available ~19GiB while free-PHYSICAL read ~31GiB -- free-
    physical is the wrong, and dangerously reassuring, metric). Memory-mapped
    (file-backed) tensors are paged via the filesystem cache, not the
    pagefile, and charge zero commit. Fresh-each-construction, never resumed
    here -- a future consumer (e.g. a rung-3 momentum-transplant workflow)
    can read the same files for that; this wrapper's job is memory strategy.

    named_params: iterable of (name, real_param) -- the actual model
        parameters (as built by the harness; may be bf16/CUDA in production).
    opt_factory: callable(list[torch.nn.Parameter]) -> torch.optim.Optimizer.
        Called ONCE with the shadow CPU fp32 parameter list; must construct
        the REAL optimizer class (e.g. `lambda ps: torch.optim.AdamW(ps,
        lr=lr, weight_decay=wd)`) with the SAME hyperparameters the
        VRAM-resident path would have used. This is where "same optimizer
        math" is enforced -- the class is never reimplemented here. Its
        per-parameter state (exp_avg/exp_avg_sq for an Adam-family optimizer,
        momentum_buffer for this repo's own Muon) is PRE-SEEDED with
        file-backed zero buffers before the optimizer's own lazy-init runs,
        so the real class's zero-tensor creation is skipped in favor of
        these -- confirmed against torch.optim.adam.Adam._init_group and
        timeshare_pretrain.py's _Muon.step(), not assumed.
    optstate_dir: where the per-parameter files live. Defaults to a shared,
        non-unique directory under the repo's scratch/ -- safe because every
        file here is named by (sanitized) parameter name, and muon/adamw
        param names never collide (split_param_groups partitions them), and
        every file is mode='w+' (truncate+recreate) on each construction, so
        stale files from a prior run are simply overwritten, never resumed.
    """

    def __init__(self, named_params: Iterable[tuple[str, Any]],
                 opt_factory: Callable[[list], Any], *,
                 optstate_dir: str | Path | None = None) -> None:
        import torch

        self._names: list[str] = []
        self._real_params: list[Any] = []
        self.grad_lazy_creates = 0  # instance mirror of the module counter (#627)
        # Optional per-instance span-instrumentation hooks (issue #702 axis-3
        # attribution profiling; ember #702 comment id ...BLOCK_721... repair
        # item (a)). None by default -- attach_span_collector()/
        # detach_span_collector() are the ONLY sanctioned way to observe this
        # method from outside. When unattached (the default for every caller
        # except the #702 profiling runner), every `if self._span_add is not
        # None:` check below is the ONLY difference from the pristine method:
        # zero extra tensor ops, zero extra syncs, zero extra allocations --
        # step()'s own arithmetic, control flow, and side effects (grad_lazy_
        # creates counting, memmap creation, param writeback order) are
        # byte-identical to before this instrumentation existed.
        self._span_add = None
        self._span_add_bytes = None
        self._span_add_numel = None
        self._span_sync = None
        for name, p in named_params:
            self._names.append(name)
            self._real_params.append(p)

        self._optstate_dir = Path(optstate_dir) if optstate_dir is not None else _DEFAULT_OPTSTATE_DIR
        self._optstate_dir.mkdir(parents=True, exist_ok=True)

        self._shadow: list[Any] = []
        for name, p in zip(self._names, self._real_params):
            stem = self._optstate_dir / _sanitize_name(name)
            shadow = _memmap_from_tensor(Path(str(stem) + ".shadow.f32"), p)
            shadow.requires_grad_(True)
            self._shadow.append(shadow)

        self._inner = opt_factory(self._shadow)

        # Pre-seed BEFORE any step() -- both real optimizer classes this repo
        # uses do `if <lazy-init check>: allocate zeros` on first touch, so
        # seeding first means their own init is skipped and these file-backed
        # tensors are what the class actually operates on, with zero changes
        # to either optimizer's own code.
        for name, p, shadow_p in zip(self._names, self._real_params, self._shadow):
            stem = self._optstate_dir / _sanitize_name(name)
            if isinstance(self._inner, torch.optim.Adam):  # covers AdamW (subclass)
                group = self._inner.param_groups[0]
                state = {
                    "step": torch.tensor(0.0, dtype=torch.float32),
                    "exp_avg": _memmap_zeros(Path(str(stem) + ".exp_avg.f32"), tuple(shadow_p.shape)),
                    "exp_avg_sq": _memmap_zeros(Path(str(stem) + ".exp_avg_sq.f32"), tuple(shadow_p.shape)),
                }
                if group.get("amsgrad", False):
                    state["max_exp_avg_sq"] = _memmap_zeros(
                        Path(str(stem) + ".max_exp_avg_sq.f32"), tuple(shadow_p.shape))
                self._inner.state[shadow_p] = state
            else:
                # This repo's own Muon (timeshare_pretrain.py:_Muon): single
                # key, matches its `if "momentum_buffer" not in state`.
                self._inner.state[shadow_p] = {
                    "momentum_buffer": _memmap_zeros(
                        Path(str(stem) + ".momentum.f32"), tuple(shadow_p.shape)),
                }

    def attach_span_collector(self, *, add, add_bytes, add_numel, sync) -> None:
        """Attach optional per-step subphase timing hooks to THIS instance
        (never a class-level patch -- no other CPUOffloadOptimizer instance,
        and no later caller of this same instance after detach, is affected).
        add(phase: str, dt: float), add_bytes(phase: str, n: int), and
        add_numel(n: int) are called at exactly the four named subphase
        boundaries (grad_to_cpu_fp32 / grad_heap_to_memmap /
        inner_optimizer_step / updated_param_to_gpu) inside step(); sync() is
        called immediately before/after each measured span (device-accurate
        wall time for async host<->device copies; pass a no-op for CPU).
        step()'s own tensor operations, their order, and every non-
        instrumentation side effect are unchanged whether or not a collector
        is attached -- this is the SAME method, not a reimplementation of it
        (ember #702 BLOCK_721_PRODUCTION_ATTRIBUTION repair item (a))."""
        self._span_add = add
        self._span_add_bytes = add_bytes
        self._span_add_numel = add_numel
        self._span_sync = sync

    def detach_span_collector(self) -> None:
        self._span_add = None
        self._span_add_bytes = None
        self._span_add_numel = None
        self._span_sync = None

    def step(self, closure=None) -> None:
        import time

        import torch

        assert closure is None, "CPUOffloadOptimizer does not support closures"
        _add = self._span_add
        _add_bytes = self._span_add_bytes
        _add_numel = self._span_add_numel
        _sync = self._span_sync
        with torch.no_grad():
            for name, real_p, shadow_p in zip(self._names, self._real_params, self._shadow):
                if real_p.grad is None:
                    shadow_p.grad = None
                    continue
                # non_blocking=True removed here (was the trigger for a real
                # cudaErrorAlreadyMapped hit on this call's FIRST-EVER real
                # GPU execution, 2026-07-08): the destination is a freshly
                # allocated CPU tensor each call, never pre-pinned, so async
                # semantics were never actually in effect as intended and the
                # per-parameter loop's overlapping unsynchronized copies raced
                # against the caching host allocator. Synchronous transfer is
                # slower but identical math -- no optimizer semantics change.
                if _add is not None:
                    _sync(); _t0 = time.perf_counter()
                g = real_p.grad.detach().to("cpu", dtype=torch.float32)
                if _add is not None:
                    _sync(); _add("grad_to_cpu_fp32", time.perf_counter() - _t0)
                    _add_bytes("grad_to_cpu_fp32", g.numel() * g.element_size())
                    _add_numel(g.numel())
                if shadow_p.grad is None:
                    # File-backed, not a regular clone() (2026-07-08 redesign):
                    # this buffer PERSISTS for the optimizer's lifetime once
                    # created (reused via copy_ below on every later call).
                    #
                    # ember #627 R3: with the zero_grad fix below this branch is
                    # structurally UNREACHABLE in steady state -- zero_grad no
                    # longer tears the shadow `.grad` down to None, so once a
                    # param's grad memmap exists (front-loaded at construction,
                    # or created here on the very first step) it is reused via
                    # copy_ forever. Reaching this branch AFTER step 1 means the
                    # M1 regression (per-step re-create + its governed
                    # subprocess) has returned -- so it is COUNTED (module +
                    # instance), making the prereg's "zero re-creates" claim
                    # falsifiable by the log instead of vacuously true.
                    _COUNTERS["grad_lazy_creates"] += 1
                    self.grad_lazy_creates += 1
                    stem = self._optstate_dir / _sanitize_name(name)
                    shadow_p.grad = _memmap_zeros(Path(str(stem) + ".grad.f32"), tuple(g.shape))
                if _add is not None:
                    _sync(); _t0 = time.perf_counter()
                shadow_p.grad.copy_(g)
                if _add is not None:
                    _sync(); _add("grad_heap_to_memmap", time.perf_counter() - _t0)
                    _add_bytes("grad_heap_to_memmap", g.numel() * g.element_size())
        if _add is not None:
            _sync(); _t0 = time.perf_counter()
        self._inner.step()
        if _add is not None:
            _sync(); _add("inner_optimizer_step", time.perf_counter() - _t0)
        with torch.no_grad():
            for real_p, shadow_p in zip(self._real_params, self._shadow):
                if _add is not None:
                    _sync(); _t0 = time.perf_counter()
                real_p.data.copy_(shadow_p.data.to(real_p.device, dtype=real_p.dtype))
                if _add is not None:
                    _sync(); _add("updated_param_to_gpu", time.perf_counter() - _t0)
                    _add_bytes("updated_param_to_gpu", shadow_p.data.numel() * real_p.element_size())

    def zero_grad(self, set_to_none: bool = True) -> None:
        """ember #627 R3 -- shadow-grad persistence.

        Two grad populations, two policies:

          * REAL (GPU) params -- keep set_to_none semantics unchanged. Nulling
            p.grad here frees the GPU-resident gradient every step, which the
            VRAM budget depends on; that behavior is preserved exactly.

          * SHADOW (file-backed) params -- NEVER torn down. The previous
            implementation forwarded to self._inner.zero_grad(set_to_none=True),
            which set every shadow_p.grad to None (the inner optimizer's params
            ARE the shadow params). The next step() then hit the lazy-create
            branch and re-created all ~184 `.grad.f32` memmaps through the
            governed wrapper -- one governor subprocess per re-create per step,
            the M1 term the component benchmark (#594) measured as dominant
            (2.4-2.6 s x140/step). #619's front-load created the memmaps once at
            construction but this teardown re-emptied them every step, so the
            cure never actually held (the audit's finding).

        DESIGN CHOICE (documented in-file per the spec): SKIP the shadow side
        entirely rather than zero-in-place. step()'s `shadow_p.grad.copy_(g)`
        fully overwrites each grad memmap every step, so its prior contents are
        never read -- zeroing them would be a redundant full pass over ~8 GB of
        fp32 state (a self-inflicted mapped-dirty-write cost, the M3 term)
        purchasing nothing. Skipping keeps the memmap objects alive and their
        identity stable, which is exactly what makes the lazy-create branch
        unreachable in steady state. We therefore deliberately do NOT call
        self._inner.zero_grad(): its only effect on this wrapper's state is to
        null the shadow grads (the inner optimizer's momentum / exp_avg buffers
        are untouched by zero_grad), which is the precise behavior R3 removes.
        """
        for p in self._real_params:
            if set_to_none:
                p.grad = None
            elif p.grad is not None:
                p.grad.detach_().zero_()
        # Shadow grads intentionally persist -- see docstring. (No call to
        # self._inner.zero_grad(); that would re-null shadow_p.grad and
        # re-arm the per-step lazy-create / governor-spawn regression.)

    def state_dict(self) -> dict:
        return self._inner.state_dict()

    def load_state_dict(self, state_dict: dict) -> None:
        self._inner.load_state_dict(state_dict)

    @property
    def param_groups(self):
        # apply_wsd() (timeshare_pretrain.py) only reads/writes group["lr"];
        # the shadow-bound inner optimizer's groups are the correct target.
        return self._inner.param_groups



# Issue #459 follow-up (2026-07-08): the two constants below REPLACE the old
# `activation_estimate_gib_at_prod_shape=6.0 @ prod_batch=16` guess, which
# predicted 9.301GiB total at micro_batch=2 -- measured peak was 20.605GiB
# over baseline (verdict OOM_ESTIMATE_WRONG, receipt
# cbase-grow-rung2-gpu-offload-probe-20260708T171259Z.json), an 86-121%
# understatement depending on which delta is compared. Per-phase attribution
# (torch.cuda.reset_peak_memory_stats + max_memory_allocated around each
# training-loop phase, gs=0/mi=0) found the estimator was missing/wrong in
# TWO places, not one:
#
# 1. A QAT fake-quant clone term was MISSING ENTIRELY. `_apply_fake_quant`
#    clones every Linear weight for the STE round-trip; measured delta during
#    that phase was 4.2125GiB, and it releases cleanly at `_restore_weights`
#    (confirmed: resident memory drops back down every microstep) -- so it is
#    a real, recurring, per-microstep transient cost, not a leak, but the old
#    estimator never had a line for it at all.
# 2. The activation term was undercounted by ~14.6x. Measured backbone_forward
#    delta (gradient checkpointing genuinely OFF, per the #459 fix -- the OLD
#    9.301GiB estimate was implicitly measured against a run where
#    checkpointing was silently ON) was 10.9797GiB at micro_batch=2, vs the
#    old formula's 0.75GiB (6.0GiB @ prod_batch=16, linearly scaled to
#    micro_batch=2). The prior "6.0GiB @ batch16" constant was never itself
#    measured on THIS architecture (2.2B grown, MTP+QAT, seq=1024) -- it was
#    inherited from a different bench.
#
# The weights+grad VRAM-resident term was NOT wrong -- 8.2994GiB predicted
# vs ~8.20-8.24GiB measured resident after a full microstep cycle (model_
# build_and_load + qat_restore phases) -- so that part of the original
# design is kept unchanged below.
QAT_CLONE_GIB_MEASURED = 4.2125
ACTIVATION_GIB_MEASURED_AT_MICRO_BATCH = 10.9797
ACTIVATION_CALIBRATION_MICRO_BATCH = 2
ACTIVATION_CALIBRATION_RECEIPT = "receipts/cbase-grow-rung2-gpu-offload-probe-20260708T171259Z.json"


def estimate_required_gib_offloaded(n_params: int, *, micro_batch: int,
                                     qat_clone_gib: float = QAT_CLONE_GIB_MEASURED,
                                     activation_gib_at_calibration_batch: float = ACTIVATION_GIB_MEASURED_AT_MICRO_BATCH,
                                     activation_calibration_micro_batch: int = ACTIVATION_CALIBRATION_MICRO_BATCH,
                                     staging_overhead_gib: float = 0.25) -> dict:
    """VRAM estimate for the CPU-offloaded strategy: weights (2N) + grad (2N)
    stay VRAM-resident (unchanged, validated against measurement -- see
    module-level comment above); the 8N optimizer-state term is removed
    entirely (host RAM now); PLUS a QAT fake-quant clone term and an
    activation term, both now anchored to a REAL measured calibration point
    (issue #459 follow-up) instead of an unverified constant borrowed from a
    different bench.

    Calibration point: micro_batch=2, seq=1024, MTP+QAT enabled, gradient
    checkpointing genuinely OFF (per the #459 fix), on the 2.2B grown
    architecture -- see ACTIVATION_CALIBRATION_RECEIPT for the full per-phase
    attribution this is sourced from.

    qat_clone_gib is treated as roughly CONSTANT across micro_batch (it is a
    function of Linear-layer parameter count, not batch size -- confirmed by
    reading _apply_fake_quant, which clones per-weight-tensor regardless of
    any activation/batch dimension). activation_gib scales LINEARLY with
    micro_batch relative to the calibration point -- the same linear-in-batch
    assumption the OLD estimator used (kept, not new), now anchored to a real
    measurement instead of an unverified constant. This is a ONE-DATA-POINT
    calibration: the linear-scaling assumption for a DIFFERENT micro_batch
    (e.g. 1) is not yet independently verified and should be treated as a
    falsifiable prediction, not a second measurement, until a probe at that
    micro_batch confirms it.

    Returns the same field shape as cbase_grow_rung2_dryrun.py's
    _estimate_required_gib() (VRAM-resident convention) so the two can be
    compared side by side in a receipt, plus `optimizer_state_host_ram_gib`
    (where the removed 8N term now lives) and `qat_clone_gib` (the newly
    added term)."""
    weights = n_params * BYTES_PER_PARAM_WEIGHTS_BF16
    grad = n_params * BYTES_PER_PARAM_GRAD_BF16
    optimizer_host_ram = n_params * BYTES_PER_PARAM_OPTIMIZER_FP32
    activation_gib = round(
        activation_gib_at_calibration_batch * (micro_batch / activation_calibration_micro_batch), 4)
    fixed_gib = (weights + grad) / (1 << 30)
    total_gib = fixed_gib + qat_clone_gib + activation_gib + staging_overhead_gib
    return {
        "weights_gib": round(weights / (1 << 30), 3),
        "grad_gib": round(grad / (1 << 30), 3),
        "optimizer_state_gib_vram_resident": 0.0,
        "optimizer_state_host_ram_gib": round(optimizer_host_ram / (1 << 30), 3),
        "qat_clone_gib": qat_clone_gib,
        "activation_estimate_gib": activation_gib,
        "staging_overhead_gib": staging_overhead_gib,
        "total_estimate_gib": round(total_gib, 3),
        "calibration_receipt": ACTIVATION_CALIBRATION_RECEIPT,
        "method": ("bf16 weights (2B/param) + bf16 grad (2B/param) VRAM-resident, "
                   "UNCHANGED from the VRAM-resident-AdamW estimate (validated against "
                   "measurement); the 8B/param conservative AdamW-equivalent optimizer-state "
                   "term moves OFF VRAM entirely (host RAM, disclosed separately) per DEV-002 "
                   "candidate 3; qat_clone_gib and activation_estimate_gib are BOTH now "
                   f"anchored to one real measured calibration point (micro_batch="
                   f"{activation_calibration_micro_batch}, see calibration_receipt) instead of "
                   "an unverified borrowed constant (issue #459 follow-up -- the prior estimate "
                   "was 9.301GiB vs a measured 20.605GiB delta, an OOM). qat_clone_gib treated "
                   "as constant across micro_batch (function of param count, confirmed by "
                   "reading _apply_fake_quant); activation_estimate_gib scales LINEARLY with "
                   f"micro_batch/{activation_calibration_micro_batch} (same assumption "
                   "structure as before, now anchored to real data) -- this linear-scaling "
                   "assumption is UNVERIFIED for any micro_batch other than the calibration "
                   "point until a probe at that micro_batch confirms it. An ESTIMATE (labeled), "
                   "not a measured peak."),
    }


def nvidia_smi_vram() -> dict:
    """Ground-truth VRAM free/total via nvidia-smi -- same ground-truth-over-
    estimate discipline as cbase_grow_rung2_dryrun.py's _nvidia_smi_vram()
    (torch.cuda.mem_get_info() diverged from nvidia-smi twice on this WDDM
    host, receipted; nvidia-smi is treated as ground truth). Duplicated here
    (not imported) because cbase_grow_rung2_dryrun.py's copy is a leading-
    underscore module-private helper; this module's copy is the reusable
    public one going forward -- the dry-run script's PART B1 preflight is
    updated to call this one instead of re-deriving its own."""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15, check=True,
    ).stdout.strip()
    total_mib, used_mib, free_mib = (int(x.strip()) for x in out.split(","))
    return {
        "total_mib": total_mib, "used_mib": used_mib, "free_mib": free_mib,
        "total_gib": round(total_mib / 1024, 3),
        "used_gib": round(used_mib / 1024, 3),
        "free_gib": round(free_mib / 1024, 3),
    }


def vram_preflight(required_gib: float, *, margin_gib_floor: float = 2.0,
                    nvsmi: dict | None = None) -> dict:
    """DEV-002 acceptance #3: nvidia-smi free-VRAM assert with a margin
    floor, refuse-to-launch (never fix-forward) on failure. Pure function of
    a measured nvsmi dict (or measures one itself) and a required-gib number
    -- the caller decides which estimate (VRAM-resident-AdamW vs offloaded)
    to price against this."""
    nvsmi = nvsmi if nvsmi is not None else nvidia_smi_vram()
    margin_gib = round(nvsmi["free_gib"] - required_gib, 3)
    sufficient = margin_gib >= margin_gib_floor
    return {
        "nvidia_smi_vram": nvsmi,
        "required_gib": required_gib,
        "margin_gib_floor": margin_gib_floor,
        "margin_gib": margin_gib,
        "sufficient": sufficient,
        "verdict": "LAUNCH_PERMITTED" if sufficient else "REFUSE_TO_LAUNCH",
        "rule": ("abort-not-degrade: VRAM margin assert fails -> hold, report "
                 "numbers, no launch into contention; no fix-forward on a "
                 "failed assert (DEV-002 acceptance #3)"),
    }
