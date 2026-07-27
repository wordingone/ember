#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""vram_ground_truth.py -- cross-process-honest free-VRAM read (gh issue #244).

Windows WDDM virtualizes GPU memory: `torch.cuda.mem_get_info()` and the
`total_memory - memory_reserved(0)` idiom both report only what THIS
process can see, which on a WDDM box is the oversubscribable pool, not
physical occupancy. Measured trigger (EXP-B bandwidth soak, 2026-07-06):
at the same instant, torch self-reported ~17.9 GiB free while `nvidia-smi`
(which queries the driver directly, cross-process) reported ~0.8-1.3 GiB
free -- resident inference servers were holding ~22.8 GiB torch could not
see. A preflight or margin gate sized from the torch number fails OPEN:
it launches into an occupied GPU, and WDDM oversubscription then pages
against whatever else is resident.

Fix contract (issue #244): every preflight/gating read of free VRAM goes
through this module's `nvidia_smi_free_mib()`, never a bare torch
self-report. `torch.cuda.memory_allocated()` / `memory_reserved()` remain
valid ONLY for self-accounting (this process's own deltas, governor
fractions that intentionally cap only this process's own reservation) --
`eval_vram_fraction` in run_accumulation.py is exactly that shape and is
NOT part of this fix's scope.
"""
from __future__ import annotations

import subprocess


class VramGroundTruthError(RuntimeError):
    """nvidia-smi could not be queried -- caller must not fall back to a
    torch self-report silently; the whole point of this module is that a
    torch-only number is not ground truth on WDDM."""


def nvidia_smi_query(gpu_index: int = 0, timeout: float = 30.0) -> dict:
    """Return {"total_mib": float, "used_mib": float, "free_mib": float}
    for one GPU, queried cross-process via `nvidia-smi`, in MiB."""
    try:
        r = subprocess.run(
            ["nvidia-smi",
             f"--id={gpu_index}",
             "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        raise VramGroundTruthError(f"nvidia-smi query failed: {e}") from e
    line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 3:
        raise VramGroundTruthError(f"unexpected nvidia-smi output: {r.stdout!r}")
    total_mib, used_mib, free_mib = (float(p) for p in parts)
    return {"total_mib": total_mib, "used_mib": used_mib, "free_mib": free_mib}


def nvidia_smi_free_mib(gpu_index: int = 0, timeout: float = 30.0) -> float:
    """Ground-truth free VRAM in MiB, per the driver, across ALL processes.
    Raises VramGroundTruthError rather than returning a fabricated number
    if nvidia-smi cannot be queried -- a preflight gate must fail closed on
    a missing ground-truth read, not silently fall back to the WDDM-blind
    torch number this module exists to replace."""
    return nvidia_smi_query(gpu_index=gpu_index, timeout=timeout)["free_mib"]


def torch_self_report_free_mib(gpu_index: int = 0) -> float:
    """The WDDM-blind number, for labeled side-by-side receipting ONLY
    (fix contract: 'receipts should record BOTH numbers labeled ... so the
    discrepancy is visible instead of silent'). Never gate on this alone."""
    import torch  # local import: this module must stay importable CPU-only

    free_b, _total_b = torch.cuda.mem_get_info(gpu_index)
    return free_b / (1024 ** 2)


if __name__ == "__main__":
    import json
    import sys

    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    out = nvidia_smi_query(idx)
    try:
        out["free_torch_wddm_mib"] = round(torch_self_report_free_mib(idx), 1)
    except Exception as e:  # pragma: no cover -- CPU-only box / no torch cuda
        out["free_torch_wddm_mib"] = None
        out["torch_read_error"] = str(e)
    print(json.dumps(out, indent=2))
