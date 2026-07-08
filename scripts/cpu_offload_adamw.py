#!/usr/bin/env python3
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
measured discrepancy) as scripts/cbase_grow_rung2_dryrun.py's own preflight.

No git commits from this module. No founder/user names. api_spend_usd
implications: none (CPU-only module; no paid API surface).
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable, Iterable

BYTES_PER_PARAM_WEIGHTS_BF16 = 2
BYTES_PER_PARAM_GRAD_BF16 = 2
BYTES_PER_PARAM_OPTIMIZER_FP32 = 4 * 2  # 2 fp32 moment buffers/param (host RAM now, not VRAM)


class CPUOffloadOptimizer:
    """Wraps an existing torch.optim.Optimizer-shaped constructor so its
    per-parameter state lives in host RAM (pinned, when CUDA is present) and
    its step() arithmetic executes on CPU tensors, while the real params it
    updates may live anywhere (GPU or CPU).

    named_params: iterable of (name, real_param) -- the actual model
        parameters (as built by the harness; may be bf16/CUDA in production).
    opt_factory: callable(list[torch.nn.Parameter]) -> torch.optim.Optimizer.
        Called ONCE with the shadow CPU fp32 parameter list; must construct
        the REAL optimizer class (e.g. `lambda ps: torch.optim.AdamW(ps,
        lr=lr, weight_decay=wd)`) with the SAME hyperparameters the
        VRAM-resident path would have used. This is where "same optimizer
        math" is enforced -- the class is never reimplemented here.
    pin_memory: None (default) pins the shadow buffers iff CUDA is available
        (matches the DEV-002 framing: pinning only matters for a real
        host<->device transfer; a pure-CPU probe environment gets ordinary
        CPU tensors, functionally identical for the update-rule math this
        module is responsible for).
    """

    def __init__(self, named_params: Iterable[tuple[str, Any]],
                 opt_factory: Callable[[list], Any], *,
                 pin_memory: bool | None = None) -> None:
        import torch

        self._names: list[str] = []
        self._real_params: list[Any] = []
        for name, p in named_params:
            self._names.append(name)
            self._real_params.append(p)

        pin = torch.cuda.is_available() if pin_memory is None else pin_memory
        self._shadow: list[Any] = []
        for p in self._real_params:
            shadow = p.detach().to("cpu", dtype=torch.float32).clone()
            if pin:
                try:
                    shadow = shadow.pin_memory()
                except RuntimeError:
                    pass  # no CUDA context available to pin against; plain CPU tensor is correct still
            shadow.requires_grad_(True)
            self._shadow.append(shadow)

        self._inner = opt_factory(self._shadow)

    def step(self, closure=None) -> None:
        import torch

        assert closure is None, "CPUOffloadOptimizer does not support closures"
        with torch.no_grad():
            for real_p, shadow_p in zip(self._real_params, self._shadow):
                if real_p.grad is None:
                    shadow_p.grad = None
                    continue
                g = real_p.grad.detach().to("cpu", dtype=torch.float32, non_blocking=True)
                if shadow_p.grad is None:
                    shadow_p.grad = g.clone()
                else:
                    shadow_p.grad.copy_(g)
        self._inner.step()
        with torch.no_grad():
            for real_p, shadow_p in zip(self._real_params, self._shadow):
                real_p.data.copy_(shadow_p.data.to(real_p.device, dtype=real_p.dtype))

    def zero_grad(self, set_to_none: bool = True) -> None:
        for p in self._real_params:
            if set_to_none:
                p.grad = None
            elif p.grad is not None:
                p.grad.detach_().zero_()
        self._inner.zero_grad(set_to_none=set_to_none)

    def state_dict(self) -> dict:
        return self._inner.state_dict()

    def load_state_dict(self, state_dict: dict) -> None:
        self._inner.load_state_dict(state_dict)

    @property
    def param_groups(self):
        # apply_wsd() (timeshare_pretrain.py) only reads/writes group["lr"];
        # the shadow-bound inner optimizer's groups are the correct target.
        return self._inner.param_groups


def estimate_required_gib_offloaded(n_params: int, *, micro_batch: int,
                                     activation_estimate_gib_at_prod_shape: float = 6.0,
                                     prod_batch: int = 16,
                                     staging_overhead_gib: float = 0.25) -> dict:
    """VRAM estimate for the CPU-offloaded strategy: weights (2N) + grad (2N)
    stay VRAM-resident; the 8N optimizer-state term is removed entirely (host
    RAM now); activations are scaled by micro_batch/prod_batch (linear in
    batch size, same coarse convention the VRAM-resident estimate used) plus
    a small fixed overhead for the grad/param staging tensors this module's
    to("cpu")/to(device) copies transiently allocate.

    Returns the same field shape as cbase_grow_rung2_dryrun.py's
    _estimate_required_gib() (VRAM-resident convention) so the two can be
    compared side by side in a receipt, plus an extra `optimizer_state_host_ram_gib`
    field disclosing where the removed 8N term now lives."""
    weights = n_params * BYTES_PER_PARAM_WEIGHTS_BF16
    grad = n_params * BYTES_PER_PARAM_GRAD_BF16
    optimizer_host_ram = n_params * BYTES_PER_PARAM_OPTIMIZER_FP32
    activation_scale = micro_batch / prod_batch
    activation_gib = round(activation_estimate_gib_at_prod_shape * activation_scale, 4)
    fixed_gib = (weights + grad) / (1 << 30)
    total_gib = fixed_gib + activation_gib + staging_overhead_gib
    return {
        "weights_gib": round(weights / (1 << 30), 3),
        "grad_gib": round(grad / (1 << 30), 3),
        "optimizer_state_gib_vram_resident": 0.0,
        "optimizer_state_host_ram_gib": round(optimizer_host_ram / (1 << 30), 3),
        "activation_estimate_gib": activation_gib,
        "staging_overhead_gib": staging_overhead_gib,
        "total_estimate_gib": round(total_gib, 3),
        "method": ("bf16 weights (2B/param) + bf16 grad (2B/param) VRAM-resident, "
                   "UNCHANGED from the VRAM-resident-AdamW estimate; the 8B/param "
                   "conservative AdamW-equivalent optimizer-state term moves OFF "
                   "VRAM entirely (host RAM, disclosed separately) per DEV-002 "
                   "candidate 3; activation estimate scaled linearly by "
                   f"micro_batch/prod_batch ({micro_batch}/{prod_batch}) per DEV-002 "
                   "candidate 2 (micro-batch + grad accumulation, effective batch "
                   "unchanged); a fixed staging-buffer overhead covers the transient "
                   "grad/param copies this module's host<->device shuttling "
                   "allocates. An ESTIMATE (labeled), not a measured peak."),
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
