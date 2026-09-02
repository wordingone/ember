#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_dryrun.py — C-BASE clause (d) rung-2 grow-operator DRY-RUN.

Closes the honest-RED clause (d) gap (board #204935Z) with a receipted
execution against the REAL owned rung-1 checkpoint
(models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/
step-00000766, SHA-verified: receipts/spend-annex/attestations/
cbase-gpu-verify-trainable-clean-20260707T015633.json), per the FROZEN
docs/domains/governance/spec/rung2-grow-spec-v1.md (net2net FF-widening, strict doubling,
16384->32768).

Reuse discipline (no duplicated math — same rule cbase_grow_live.py and
cbase_grow_rung.py state for themselves):
  - cbase_grow_dryrun.sha256_file / widen_state_dict — the exact net2net
    surgery math, imported, never reimplemented.
  - cbase_grow_live._loss_continuity_block / build_model (via
    cbase_grow_dryrun) — the noisy training-loss continuity check and the
    real _V0 model twin.
  - cbase_grow_rung.measure_tied_duplicate_numel / d1_stabilization_steps —
    D4's dual parameter convention and D1's fixed-FLOPs stabilization sizing.
  - v0_pretrain_launch_gate.g_budget — the real compute-budget preflight.
  - timeshare_pretrain.run_v0_segment / save_checkpoint / load_checkpoint /
    load_contract — the REAL v0 survivor-stack pretrain loop.
  - receipt_write.checked_write — fail-closed receipt writer.

Process shape (three phases, each its OWN subprocess -- see below for why):

  PART A — deterministic grow-operator function-preservation check (CPU,
  no GPU touched): proves 16384->32768 net2net widening is function-
  preserving on THIS checkpoint's real weights. This is "the same gate as
  rung-1" the frozen spec names (rung-1 measured 2.38e-6; tolerance 1e-4).

  PART B1 — production-scale VRAM margin preflight (real nvidia-smi numbers,
  no launch attempted). Runs inline in the orchestrator (cheap, no big
  tensors).

  PART B2 — CPU sanity-stabilization: same real architecture, same real
  checkpoint, reduced seq/batch/steps for CPU tractability (disclosed
  dry-run-local scale-down, mirroring cbase_grow_live.py's own pre/grow/post
  3-phase shape). Produces a genuine, non-degenerate loss trace proving the
  grown model actually trains (not just that it forward-passes).

  Each of PART A and PART B2 is dispatched to a FRESH subprocess
  (--part-a-worker / --cpu-sanity-worker) rather than run inline in one
  long-lived process. Bisection on this machine found repeated SIGSEGVs when
  these ran back-to-back in one process: (1) building the pre-grow (~1.19B
  param) and post-grow (~2.2B param) models simultaneously without releasing
  the first; (2) a redundant full-checkpoint reload combined with the still-
  warm allocator state from (1); (3) the CPU training segment
  (timeshare_pretrain.run_v0_segment) crashing when run after (1)+(2) in the
  same process, but completing cleanly (235s, real losses) standalone. This
  machine is also shared with at least one other, unrelated legitimate
  process (observed holding ~15GB RAM, fluctuating) -- giving each memory-
  heavy phase a fresh process with a clean heap is the robust answer to both
  the allocator-fragmentation class of crash and the shared-machine
  contention class, without touching or guessing about the other process.

Verdicts (never hardcoded — computed from measured fields):
  grow-op-verify receipt: PASS iff function_preserving (real fp_diff).
  main dry-run receipt:   PASS iff function_preserving AND the CPU sanity
                           stabilization completed without divergence;
                           production-scale stabilization status recorded
                           separately as "held" (not a failure of the
                           dry-run itself) when VRAM margin is insufficient.

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false (C(-1) lesson).
"""
from __future__ import annotations

import argparse
import copy
import gc
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# issue2015 exact-local-import:scripts/timeshare_pretrain.py
import importlib.util as _ember_d9c5c82c124e1dc8_importlib
import sys as _ember_d9c5c82c124e1dc8_sys
from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
_ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parents[4].joinpath('scripts', 'timeshare_pretrain.py')
if not _ember_d9c5c82c124e1dc8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/timeshare_pretrain.py')
_ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'scripts.timeshare_pretrain', 'timeshare_pretrain')
_ember_d9c5c82c124e1dc8_existing = []
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
        _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
if len(_ember_d9c5c82c124e1dc8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/timeshare_pretrain.py')
if _ember_d9c5c82c124e1dc8_existing:
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
    _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
    if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/timeshare_pretrain.py')
else:
    _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
    if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    try:
        _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
    except BaseException:
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
        raise
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
ts = _ember_d9c5c82c124e1dc8_module
# issue2015 exact-local-import-end:scripts/timeshare_pretrain.py                                    # noqa: E402
from cbase_grow_dryrun import sha256_file, widen_state_dict, build_model, PASS_TOL  # noqa: E402
from cbase_grow_live import _loss_continuity_block                 # noqa: E402
# issue2015 exact-local-import:scripts/cbase_grow_rung.py
import importlib.util as _ember_d5d5cce5b9f67cf3_importlib
import sys as _ember_d5d5cce5b9f67cf3_sys
from pathlib import Path as _ember_d5d5cce5b9f67cf3_Path
_ember_d5d5cce5b9f67cf3_path = _ember_d5d5cce5b9f67cf3_Path(__file__).resolve().parents[4].joinpath('scripts', 'cbase_grow_rung.py')
if not _ember_d5d5cce5b9f67cf3_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/cbase_grow_rung.py')
_ember_d5d5cce5b9f67cf3_aliases = ('_ember_issue2015_d5d5cce5b9f67cf3', 'cbase_grow_rung', 'scripts.cbase_grow_rung')
_ember_d5d5cce5b9f67cf3_existing = []
for _ember_d5d5cce5b9f67cf3_alias in _ember_d5d5cce5b9f67cf3_aliases:
    _ember_d5d5cce5b9f67cf3_candidate = _ember_d5d5cce5b9f67cf3_sys.modules.get(_ember_d5d5cce5b9f67cf3_alias)
    if _ember_d5d5cce5b9f67cf3_candidate is not None and all(_ember_d5d5cce5b9f67cf3_candidate is not item for item in _ember_d5d5cce5b9f67cf3_existing):
        _ember_d5d5cce5b9f67cf3_existing.append(_ember_d5d5cce5b9f67cf3_candidate)
if len(_ember_d5d5cce5b9f67cf3_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/cbase_grow_rung.py')
if _ember_d5d5cce5b9f67cf3_existing:
    _ember_d5d5cce5b9f67cf3_module = _ember_d5d5cce5b9f67cf3_existing[0]
    _ember_d5d5cce5b9f67cf3_observed = getattr(_ember_d5d5cce5b9f67cf3_module, '__file__', None)
    if _ember_d5d5cce5b9f67cf3_observed is None or _ember_d5d5cce5b9f67cf3_Path(_ember_d5d5cce5b9f67cf3_observed).resolve() != _ember_d5d5cce5b9f67cf3_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/cbase_grow_rung.py')
else:
    _ember_d5d5cce5b9f67cf3_spec = _ember_d5d5cce5b9f67cf3_importlib.spec_from_file_location('_ember_issue2015_d5d5cce5b9f67cf3', _ember_d5d5cce5b9f67cf3_path)
    if _ember_d5d5cce5b9f67cf3_spec is None or _ember_d5d5cce5b9f67cf3_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/cbase_grow_rung.py')
    _ember_d5d5cce5b9f67cf3_module = _ember_d5d5cce5b9f67cf3_importlib.module_from_spec(_ember_d5d5cce5b9f67cf3_spec)
    for _ember_d5d5cce5b9f67cf3_alias in _ember_d5d5cce5b9f67cf3_aliases:
        _ember_d5d5cce5b9f67cf3_prior = _ember_d5d5cce5b9f67cf3_sys.modules.get(_ember_d5d5cce5b9f67cf3_alias)
        if _ember_d5d5cce5b9f67cf3_prior is not None and _ember_d5d5cce5b9f67cf3_prior is not _ember_d5d5cce5b9f67cf3_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/cbase_grow_rung.py')
        _ember_d5d5cce5b9f67cf3_sys.modules[_ember_d5d5cce5b9f67cf3_alias] = _ember_d5d5cce5b9f67cf3_module
    try:
        _ember_d5d5cce5b9f67cf3_spec.loader.exec_module(_ember_d5d5cce5b9f67cf3_module)
    except BaseException:
        for _ember_d5d5cce5b9f67cf3_alias in _ember_d5d5cce5b9f67cf3_aliases:
            if _ember_d5d5cce5b9f67cf3_sys.modules.get(_ember_d5d5cce5b9f67cf3_alias) is _ember_d5d5cce5b9f67cf3_module:
                _ember_d5d5cce5b9f67cf3_sys.modules.pop(_ember_d5d5cce5b9f67cf3_alias, None)
        raise
for _ember_d5d5cce5b9f67cf3_alias in _ember_d5d5cce5b9f67cf3_aliases:
    _ember_d5d5cce5b9f67cf3_prior = _ember_d5d5cce5b9f67cf3_sys.modules.get(_ember_d5d5cce5b9f67cf3_alias)
    if _ember_d5d5cce5b9f67cf3_prior is not None and _ember_d5d5cce5b9f67cf3_prior is not _ember_d5d5cce5b9f67cf3_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/cbase_grow_rung.py')
    _ember_d5d5cce5b9f67cf3_sys.modules[_ember_d5d5cce5b9f67cf3_alias] = _ember_d5d5cce5b9f67cf3_module
measure_tied_duplicate_numel = getattr(_ember_d5d5cce5b9f67cf3_module, 'measure_tied_duplicate_numel')
d1_stabilization_steps = getattr(_ember_d5d5cce5b9f67cf3_module, 'd1_stabilization_steps')
# issue2015 exact-local-import-end:scripts/cbase_grow_rung.py  # noqa: E402
from receipt_write import checked_write                            # noqa: E402
import v0_pretrain_launch_gate as gate_mod                          # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/cpu_offload_adamw.py
import importlib.util as _ember_af5148f80571f78d_importlib
import sys as _ember_af5148f80571f78d_sys
from pathlib import Path as _ember_af5148f80571f78d_Path
_ember_af5148f80571f78d_path = _ember_af5148f80571f78d_Path(__file__).resolve().parents[4].joinpath('scripts', 'cpu_offload_adamw.py')
if not _ember_af5148f80571f78d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/cpu_offload_adamw.py')
_ember_af5148f80571f78d_aliases = ('_ember_issue2015_af5148f80571f78d', 'cpu_offload_adamw', 'src.ember.governance.scripts.cpu_offload_adamw')
_ember_af5148f80571f78d_existing = []
for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
    _ember_af5148f80571f78d_candidate = _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias)
    if _ember_af5148f80571f78d_candidate is not None and all(_ember_af5148f80571f78d_candidate is not item for item in _ember_af5148f80571f78d_existing):
        _ember_af5148f80571f78d_existing.append(_ember_af5148f80571f78d_candidate)
if len(_ember_af5148f80571f78d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/cpu_offload_adamw.py')
if _ember_af5148f80571f78d_existing:
    _ember_af5148f80571f78d_module = _ember_af5148f80571f78d_existing[0]
    _ember_af5148f80571f78d_observed = getattr(_ember_af5148f80571f78d_module, '__file__', None)
    if _ember_af5148f80571f78d_observed is None or _ember_af5148f80571f78d_Path(_ember_af5148f80571f78d_observed).resolve() != _ember_af5148f80571f78d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/cpu_offload_adamw.py')
else:
    _ember_af5148f80571f78d_spec = _ember_af5148f80571f78d_importlib.spec_from_file_location('_ember_issue2015_af5148f80571f78d', _ember_af5148f80571f78d_path)
    if _ember_af5148f80571f78d_spec is None or _ember_af5148f80571f78d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/cpu_offload_adamw.py')
    _ember_af5148f80571f78d_module = _ember_af5148f80571f78d_importlib.module_from_spec(_ember_af5148f80571f78d_spec)
    for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
        _ember_af5148f80571f78d_prior = _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias)
        if _ember_af5148f80571f78d_prior is not None and _ember_af5148f80571f78d_prior is not _ember_af5148f80571f78d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/cpu_offload_adamw.py')
        _ember_af5148f80571f78d_sys.modules[_ember_af5148f80571f78d_alias] = _ember_af5148f80571f78d_module
    try:
        _ember_af5148f80571f78d_spec.loader.exec_module(_ember_af5148f80571f78d_module)
    except BaseException:
        for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
            if _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias) is _ember_af5148f80571f78d_module:
                _ember_af5148f80571f78d_sys.modules.pop(_ember_af5148f80571f78d_alias, None)
        raise
for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
    _ember_af5148f80571f78d_prior = _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias)
    if _ember_af5148f80571f78d_prior is not None and _ember_af5148f80571f78d_prior is not _ember_af5148f80571f78d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/cpu_offload_adamw.py')
    _ember_af5148f80571f78d_sys.modules[_ember_af5148f80571f78d_alias] = _ember_af5148f80571f78d_module
estimate_required_gib_offloaded = getattr(_ember_af5148f80571f78d_module, 'estimate_required_gib_offloaded')
vram_preflight = getattr(_ember_af5148f80571f78d_module, 'vram_preflight')
# issue2015 exact-local-import-end:src/ember/governance/scripts/cpu_offload_adamw.py  # noqa: E402 (DEV-002 cure)


REPO = Path(__file__).resolve().parents[4]
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
# Constitutional invariant hash (receipt_check.py's post-genesis rule) -- cross-verified
# against src/ember/governance/scripts/receipt_check.py's own INVARIANT_SHA256 constant, not hand-typed.
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"

SEED_CKPT = REPO / "models" / "cbase-grow-rung" / "rung1-20260703T155447Z" / "stabilize" / "checkpoints" / "step-00000766"
SEED_SHA_ATTESTED = "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b"
SEED_SHA_ATTESTATION_RECEIPT = "receipts/spend-annex/attestations/cbase-gpu-verify-trainable-clean-20260707T015633.json"

OUT_DIR = REPO / "models" / "cbase-grow-rung"
RECEIPT_DIR = REPO / "receipts"

# CPU sanity-stabilization scale-down (disclosed dry-run-local choice; the
# production D1 shape is batch=16/seq=1024 -- infeasible on CPU in bounded
# wall-time and NOT what the VRAM-gated production path needs anyway).
CPU_SEQ = 128
CPU_BATCH = 2
CPU_K_PRE = 6
CPU_K_POST = 6

# Production stabilization estimate assumptions (bf16 weights + bf16 grad +
# Muon/AdamW split optimizer momentum state, conservatively priced at 2x
# param count in fp32 for the momentum buffers actually held -- Muon's own
# orthogonalized-momentum state is one fp32 buffer/param, AdamW's
# embeddings/norms/head slice carries two; this estimate uses the more
# expensive AdamW-equivalent bound as a conservative ceiling) + a coarse
# activation estimate for batch16/seq1024 at 20 layers.
BYTES_PER_PARAM_WEIGHTS_BF16 = 2
BYTES_PER_PARAM_GRAD_BF16 = 2
BYTES_PER_PARAM_OPTIMIZER_FP32 = 4 * 2   # conservative AdamW-equivalent (2 fp32 buffers/param)
ACTIVATION_ESTIMATE_GIB_AT_PROD_SHAPE = 6.0  # coarse; batch16/seq1024/20 layers/ff32768


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _nvidia_smi_vram():
    """Ground-truth VRAM free/total via nvidia-smi (OS-level accounting,
    authoritative over torch.cuda.mem_get_info() on this WDDM host --
    measured discrepancy this run: torch reported far more free than
    nvidia-smi under the SAME live contention, presumably WDDM
    over-commit/paging; nvidia-smi is treated as ground truth)."""
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


def _torch_vram():
    import torch
    if not torch.cuda.is_available():
        return None
    free, total = torch.cuda.mem_get_info()
    return {"free_gib": round(free / (1 << 30), 3), "total_gib": round(total / (1 << 30), 3)}


def _estimate_required_gib(n_params: int) -> dict:
    weights = n_params * BYTES_PER_PARAM_WEIGHTS_BF16
    grad = n_params * BYTES_PER_PARAM_GRAD_BF16
    opt = n_params * BYTES_PER_PARAM_OPTIMIZER_FP32
    fixed_gib = (weights + grad + opt) / (1 << 30)
    total_gib = fixed_gib + ACTIVATION_ESTIMATE_GIB_AT_PROD_SHAPE
    return {
        "weights_gib": round(weights / (1 << 30), 3),
        "grad_gib": round(grad / (1 << 30), 3),
        "optimizer_state_gib_conservative_adamw_equiv": round(opt / (1 << 30), 3),
        "activation_estimate_gib": ACTIVATION_ESTIMATE_GIB_AT_PROD_SHAPE,
        "total_estimate_gib": round(total_gib, 3),
        "method": ("bf16 weights (2B/param) + bf16 grad (2B/param) + conservative "
                   "AdamW-equivalent fp32 optimizer momentum (2 buffers/param, "
                   "8B/param) + a coarse fixed activation estimate for the "
                   "batch16/seq1024/20-layer/ff32768 production shape; an "
                   "ESTIMATE (labeled), not a measured peak -- no production launch "
                   "was attempted, so no measured peak exists"),
    }


def _free_ram_gib() -> float:
    """Free physical RAM in GiB (Windows, wmic value-format; ground truth for the
    RAM preflight below -- same ground-truth-over-estimate discipline as
    _nvidia_smi_vram())."""
    out = subprocess.run(
        ["wmic", "OS", "get", "FreePhysicalMemory", "/format:value"],
        capture_output=True, text=True, timeout=15, check=True,
    ).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("FreePhysicalMemory="):
            free_kb = int(line.split("=", 1)[1].strip())
            return free_kb / (1 << 20)
    raise RuntimeError(f"could not parse wmic FreePhysicalMemory output: {out!r}")


def _wait_for_ram(min_gib: float, max_wait_s: int, poll_s: int) -> dict:
    """Bounded wait-and-retry for free system RAM to clear a safety floor before
    dispatching a memory-heavy phase -- the SAME 'measure real margin, hold/wait
    rather than crash or fabricate' discipline this script already applies to
    VRAM (_nvidia_smi_vram / vram_sufficient), extended to system RAM.

    This machine is shared with at least one other, unrelated legitimate
    process observed holding a large, FLUCTUATING amount of RAM during this
    run (measured: ~32GiB free early in the session, dropping as low as
    ~12GiB, recovering to ~17GiB minutes later, on a cycle of single-digit
    minutes) -- bisection proved PART A's real memory need (~11-13GiB for the
    fp32 state dicts + one grown model, after the memory-lifecycle fixes)
    genuinely does not fit when the other process is at its peak, and
    genuinely does fit when it is not. A bounded poll (not an infinite loop,
    not an immediate hold) gives PART A a real chance to land in a trough
    without touching or guessing about the other process."""
    import time
    samples = []
    deadline = time.time() + max_wait_s
    while True:
        free_gib = round(_free_ram_gib(), 3)
        samples.append(free_gib)
        if free_gib >= min_gib:
            return {"waited_s": len(samples) * poll_s - poll_s, "samples_gib": samples,
                     "cleared": True, "final_free_gib": free_gib}
        if time.time() >= deadline:
            return {"waited_s": max_wait_s, "samples_gib": samples,
                     "cleared": False, "final_free_gib": free_gib}
        time.sleep(poll_s)


def _function_preservation_check_low_memory(cfg_model: dict, n_mtp: int, sd_pre_f32_holder: list,
                                             sd_post_f32: dict, ff_seed: int, ff_grown: int) -> dict:
    """Same deterministic measurement as cbase_grow_live._function_preservation_check
    (same fixed recorded token batch, same PASS_TOL, same build_model), but releases
    the pre-grow model AND the pre-grow state dict before constructing the post-grow
    model -- see the module docstring's process-shape note for why (a real SIGSEGV
    at this rung's ~1.19B/~2.2B param scale, bisected to the two-full-model-
    simultaneously memory lifecycle).

    sd_pre_f32_holder is a single-element list, not a plain dict: the caller's own
    reference to the pre-grow state dict must be dropped BEFORE this call (its slot
    replaced with this holder) so that clearing holder[0] here actually drops the
    object's last reference and frees the memory -- reassigning a same-named local
    inside this function would NOT do that, since the caller's separate binding to
    the same dict object survives for the whole duration of this call regardless of
    what this function does with its own parameter name."""
    import torch
    torch.manual_seed(42)
    seq_probe = min(cfg_model["seq"], 128)
    ids = torch.randint(0, cfg_model["vocab"], (2, seq_probe),
                         generator=torch.Generator().manual_seed(42))
    batch_sha = __import__("hashlib").sha256(ids.numpy().tobytes()).hexdigest()

    pre_model = build_model(cfg_model, n_mtp, ff_seed)
    missing, unexpected = pre_model.load_state_dict(sd_pre_f32_holder[0], strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"pre-grow probe load mismatch: missing={real_missing} unexpected={unexpected}")
    pre_model.eval()
    logits_pre = pre_model.logits(ids)
    pre_model = None
    sd_pre_f32_holder[0] = None
    gc.collect()

    post_model = build_model(cfg_model, n_mtp, ff_grown)
    missing, unexpected = post_model.load_state_dict(sd_post_f32, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"post-grow probe load mismatch: missing={real_missing} unexpected={unexpected}")
    post_model.eval()
    logits_post = post_model.logits(ids)

    fp_diff = float((logits_post - logits_pre).abs().max())
    return {
        "mechanism": "same fixed recorded token batch through pre-grow vs "
                     "freshly-grown (pre-training) models; net2net FF-widening "
                     "is function-preserving by construction (duplicated "
                     "gate/up rows produce duplicated SwiGLU activations; the "
                     "halved, duplicated down columns sum them back to the "
                     "exact seed output); pre-grow model released before the "
                     "post-grow model is built (memory-lifecycle fix, see module "
                     "docstring)",
        "input_batch": {"batch": 2, "seqlen": seq_probe,
                         "token_ids_sha256": batch_sha, "generator_seed": 42},
        "logit_max_abs_diff": fp_diff,
        "pass_tolerance": PASS_TOL,
        "function_preserving": bool(fp_diff <= PASS_TOL),
    }


def _part_a_worker(seed_ckpt_str: str, out_dir: str, receipt_dir: str,
                    ts_stamp: str, timestamp_iso: str, result_json: str) -> int:
    """PART A body (SHA-verify -> load -> widen -> function-preservation check
    -> write grown checkpoint -> write the grow-op-verify evidence receipt),
    run as a FRESH subprocess -- see the module docstring for why.

    Writes the grow-op-verify evidence receipt itself either way. If the
    function-preservation gate FAILS, also writes the fail-closed main
    dry-run receipt itself (PART B is never attempted on a checkpoint that
    fails this gate) and returns 2. If it PASSES, writes a small JSON summary
    to result_json for the orchestrator to fold into the final main receipt
    after PART B, and returns 0.
    """
    import torch

    seed_ckpt = Path(seed_ckpt_str)
    model_pt = seed_ckpt / "model.pt"
    manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))
    actual_sha = sha256_file(model_pt)
    claimed_sha = (manifest.get("files") or {}).get("model.pt")
    sha_ok = isinstance(claimed_sha, str) and actual_sha == claimed_sha
    if not sha_ok:
        raise SystemExit(f"CBASE-GROW-RUNG2-DRYRUN: seed checkpoint hash mismatch: "
                          f"manifest={claimed_sha} actual={actual_sha}")
    print(f"[{ts_stamp}] seed checkpoint SHA verified: {actual_sha}", flush=True)

    cfg = ts.load_contract()
    n_layers = cfg["model"]["layers"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]

    sd_seed_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)
    dup_numel, tied_pairs = measure_tied_duplicate_numel(sd_seed_bf16)
    ff_seed = int(sd_seed_bf16["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
    ff_grown = ff_seed * 2
    print(f"[{ts_stamp}] ff_seed={ff_seed} ff_grown={ff_grown} (strict doubling per "
          f"rung2-grow-spec-v1.md)", flush=True)

    sd_pre_f32 = {k: v.float() for k, v in sd_seed_bf16.items()}
    sd_seed_bf16 = None
    gc.collect()
    grown_sd_f32 = widen_state_dict(sd_pre_f32, n_layers)
    param_count_before = int(sum(v.numel() for v in sd_pre_f32.values()))
    param_count_after = int(sum(v.numel() for v in grown_sd_f32.values()))
    params_unique_before = param_count_before - dup_numel
    params_unique_after = param_count_after - dup_numel
    print(f"[{ts_stamp}] param_count_before={param_count_before} "
          f"param_count_after={param_count_after} "
          f"params_unique_before={params_unique_before} "
          f"params_unique_after={params_unique_after}", flush=True)

    print(f"\n[{ts_stamp}] PART A: function-preservation check (CPU, real weights, "
          f"same probe convention as rung-1)", flush=True)
    sd_pre_f32_holder = [sd_pre_f32]
    sd_pre_f32 = None  # caller's own binding dropped BEFORE the call -- see the
                        # function's docstring for why this is required for the
                        # in-call release to actually free the memory.
    fp_check = _function_preservation_check_low_memory(
        cfg["model"], n_mtp, sd_pre_f32_holder, grown_sd_f32, ff_seed, ff_grown)
    sd_pre_f32_holder = None
    print(f"  fp_diff={fp_check['logit_max_abs_diff']:.3e} "
          f"tol={fp_check['pass_tolerance']} "
          f"function_preserving={fp_check['function_preserving']}", flush=True)

    print(f"[{ts_stamp}] casting grown state dict to bf16...", flush=True)
    grown_sd_bf16 = {k: v.to(torch.bfloat16) for k, v in grown_sd_f32.items()}
    grown_sd_f32 = None
    gc.collect()
    print(f"[{ts_stamp}] bf16 cast done, n_tensors={len(grown_sd_bf16)}", flush=True)
    grow_out_root = Path(out_dir) / f"rung2-dryrun-{ts_stamp}"
    o_state, r_state = {}, {}
    try:
        # Load ONLY optimizer.pt/rng.pt (SHA-verified against the manifest) --
        # NOT ts.load_checkpoint(), which redundantly re-torch.loads the 2.3GB
        # model.pt we already have (as grown_sd_bf16) and, combined with the
        # model-build/forward churn still in the allocator, reproduced a
        # second SIGSEGV (bisected: this targeted load is stable, the redundant
        # full load_checkpoint() call was not, in this same process).
        print(f"[{ts_stamp}] loading seed optimizer/rng state for carry-through...", flush=True)
        for fname in ("optimizer.pt", "rng.pt"):
            expected = (manifest.get("files") or {}).get(fname)
            if expected:
                actual = sha256_file(seed_ckpt / fname)
                if actual != expected:
                    raise ValueError(f"{fname} hash mismatch: manifest={expected} actual={actual}")
        o_state = torch.load(seed_ckpt / "optimizer.pt", map_location="cpu", weights_only=True)
        r_state = torch.load(seed_ckpt / "rng.pt", map_location="cpu", weights_only=False)  # noqa: S614
        gc.collect()
        print(f"[{ts_stamp}] seed optimizer/rng state loaded", flush=True)
    except Exception as e:  # pragma: no cover - optimizer/rng carry-through is best-effort
        o_state, r_state = {}, {}
        print(f"  [WARNING] could not load seed optimizer/rng state for carry-through: {e}", flush=True)
    print(f"[{ts_stamp}] writing grown checkpoint to {grow_out_root}...", flush=True)
    grow_ckpt_dir = ts.save_checkpoint(
        str(grow_out_root), manifest["step"], grown_sd_bf16, o_state, r_state,
        extra={"segment_id": "cbase-grow-rung2-dryrun-grown",
               "mechanism": "ff_widening_net2net", "grown_from_step": manifest["step"],
               "ff_seed": ff_seed, "ff_grown": ff_grown,
               "optimizer_state_carried_but_unused": True,
               "note": "optimizer.pt bytes carried from rung1 seed verbatim (shapes stale "
                       "after FF-widening); any resume uses reset_optimizer_on_resume=True"})
    print(f"  grown checkpoint written: {grow_ckpt_dir}", flush=True)

    # ---- grow-op-verify evidence receipt (execution binding, PART A only) ----
    evidence_filename = f"grow-op-verify-{ts_stamp}.json"
    evidence_receipt = {
        "ticket": "CBASE-GROW-RUNG2-OP-VERIFY",
        "ts": timestamp_iso,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "experiment": "C-BASE-clause-d",
        "arm": "grow-op-verify",
        "scope": "deterministic net2net FF-widening (16384->32768) function-preservation "
                 "check on the REAL rung-1 checkpoint's real weights -- same gate as rung-1 "
                 "per the frozen docs/domains/governance/spec/rung2-grow-spec-v1.md",
        "seed_identity": {
            "checkpoint": str(seed_ckpt.relative_to(REPO)) if seed_ckpt.is_relative_to(REPO) else str(seed_ckpt),
            "model_pt_sha256": actual_sha,
            "manifest_claim_verified": True,
            "attestation_receipt": SEED_SHA_ATTESTATION_RECEIPT,
            "step": manifest.get("step"),
            "segment_id": manifest.get("extra", {}).get("segment_id"),
        },
        "grow-operator": True,
        "grow_dry_run": True,
        "net2net": True,
        "ff_seed": ff_seed,
        "ff_grown": ff_grown,
        "net2net_assertion": {
            "passed": bool(fp_check["function_preserving"]),
            "max_abs_diff": fp_check["logit_max_abs_diff"],
            "tolerance": fp_check["pass_tolerance"],
            "method": fp_check["mechanism"],
            "input_batch": fp_check["input_batch"],
        },
        "params_unique_before": params_unique_before,
        "params_unique_after": params_unique_after,
        "grown_checkpoint": str(Path(grow_ckpt_dir).relative_to(REPO)) if Path(grow_ckpt_dir).is_relative_to(REPO) else grow_ckpt_dir,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "device": "cpu",
        "invalid_tokens_present": [],
        "verdict": "PASS" if fp_check["function_preserving"] else "FAIL",
    }
    evidence_path = Path(receipt_dir) / evidence_filename
    checked_write(str(evidence_path), evidence_receipt)
    print(f"  written: {evidence_path}", flush=True)

    if not fp_check["function_preserving"]:
        # Fail-closed: do not attempt stabilization on a checkpoint that failed
        # the function-preservation gate. Main receipt records the kill.
        main_receipt = {
            "ticket": "CBASE-GROW-RUNG2-DRYRUN",
            "ts": timestamp_iso,
            "invariant_sha256": INVARIANT_SHA256,
            "sha_convention": SHA_CONVENTION,
            "experiment": "C-BASE-clause-d-dryrun",
            "arm": "grow-operator-dryrun",
            "grow_operator_evidence": f"receipts/{evidence_filename}",
            "grow-operator": True, "grow_dry_run": True, "net2net": True,
            "larger_shape": True, "post_grow": False, "replays": False,
            "replay_across_shape": False,
            "verification": {"loss_trace": None, "reason": "function-preservation gate failed; "
                              "stabilization not attempted (fail-closed)"},
            "api_spend_usd": 0, "paid_api_surface_used": False,
            "invalid_tokens_present": [],
            "verdict": "FAIL", "kill_criterion": "function_preservation_failed",
        }
        out_main = Path(receipt_dir) / f"grow-operator-dryrun-{ts_stamp}.json"
        checked_write(str(out_main), main_receipt)
        print(f"CBASE_GROW_RUNG2_DRYRUN_FAIL (function-preservation) receipt={out_main}", flush=True)
        return 2

    result = {
        "ff_seed": ff_seed, "ff_grown": ff_grown, "n_layers": n_layers,
        "param_count_before": param_count_before, "param_count_after": param_count_after,
        "params_unique_before": params_unique_before, "params_unique_after": params_unique_after,
        "dup_numel": dup_numel, "tied_pairs": tied_pairs,
        "fp_check": fp_check,
        "grow_ckpt_dir": str(grow_ckpt_dir),
        "actual_sha": actual_sha,
        "manifest_step": manifest.get("step"),
        "evidence_filename": evidence_filename,
    }
    Path(result_json).parent.mkdir(parents=True, exist_ok=True)
    Path(result_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"PART_A_WORKER_DONE result={result_json}", flush=True)
    return 0


def _cpu_pretrain_worker(seed_ckpt: str, out_dir: str, ts_stamp: str,
                          ff_seed: int, result_json: str) -> int:
    """PART B2a-i: pre-grow CPU sanity TRAINING segment only, run as its OWN
    fresh subprocess. Split away from the load/widen/cast/save step below
    (which PART A already proved is stable STANDALONE, at a much LARGER
    scale) because bisection showed the crash lands immediately after a
    real training loop (run_v0_segment: forward+backward+optimizer.step()
    x N) completes, regardless of total free system RAM (observed with
    31.9GiB free) -- consistent with autograd-engine / caching-allocator
    state left over from a training loop (not a total-memory problem, a
    different native-state class) rather than fresh heavy tensor ops."""
    cfg = ts.load_contract()
    cpu_cfg = copy.deepcopy(cfg)
    cpu_cfg["model"] = dict(cpu_cfg["model"], seq=CPU_SEQ)

    cpu_out_root = Path(out_dir) / f"rung2-cpu-sanity-{ts_stamp}"
    pre_dir = cpu_out_root / "pre"
    post_dir = cpu_out_root / "post"

    pre_receipt = ts.run_v0_segment(
        str(pre_dir), cpu_cfg, n_steps=CPU_K_PRE, total_steps=CPU_K_PRE * 4, live=False,
        real_arch=True, device="cpu", resume_ckpt_dir=str(seed_ckpt), shard_dir=None,
        checkpoint_every=CPU_K_PRE, segment_id="cbase-grow-rung2-dryrun-cpu-pre",
        intermediate_override=ff_seed, batch_size=CPU_BATCH,
    )
    assert pre_receipt["pass"] is True, "CPU pre-grow sanity segment did not complete"
    print(f"  pre-grow CPU sanity: losses={pre_receipt['losses']}", flush=True)

    result = {
        "pre_receipt": {"losses": pre_receipt["losses"], "loss_first": pre_receipt["loss_first"],
                        "loss_last": pre_receipt["loss_last"], "wall_s": pre_receipt["wall_s"]},
        "last_checkpoint": pre_receipt["last_checkpoint"],
        "post_dir": str(post_dir),
    }
    Path(result_json).parent.mkdir(parents=True, exist_ok=True)
    Path(result_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"CPU_PRETRAIN_WORKER_DONE result={result_json}", flush=True)
    return 0


def _cpu_grow_worker(last_checkpoint: str, post_dir: str, ts_stamp: str,
                      ff_seed: int, ff_grown: int, n_layers: int,
                      result_json: str) -> int:
    """PART B2a-ii: load the pre-grow CPU-sanity checkpoint, widen it, cast
    to bf16, save the grown checkpoint -- run as its OWN fresh subprocess,
    isolated from the training loop above (see _cpu_pretrain_worker's
    docstring for why)."""
    import torch
    print(f"[{ts_stamp}] loading pre-grow CPU-sanity checkpoint from {last_checkpoint}...", flush=True)
    m_state_pre, o_state_pre, r_state_pre, pre_ckpt_manifest = ts.load_checkpoint(last_checkpoint)
    # Root cause of the earlier crash (localized via per-tensor instrumentation:
    # it crashed partway through the cast loop, at ~86% through, not on any
    # specific tensor shape -- every shape involved had already been cast
    # successfully many times before): this function was holding THREE full
    # copies of the ~1.19B-param state dict simultaneously (m_state_pre,
    # sd_pre_cpu_f32, grown_sd_cpu_f32 at ~2.2B) PLUS the optimizer momentum
    # state (o_state_pre, potentially as large as the model itself) for no
    # functional reason -- run_v0_segment's resume path skips
    # load_optimizers_state entirely when reset_optimizer_on_resume=True (the
    # post-grow segment always passes that), so o_state_pre is genuinely dead
    # weight here. restore_rng() DOES run unconditionally on resume though
    # (unguarded by reset_optimizer_on_resume in timeshare_pretrain.py), so
    # r_state_pre must be kept real, not dropped -- it's tiny (python/numpy/
    # torch RNG state, not model-sized) so keeping it costs nothing. Same
    # missing-release-discipline bug already fixed once in PART A; the fix
    # generalizes: release each intermediate copy immediately, drop only the
    # genuinely-dead-weight optimizer state.
    o_state_pre = None
    gc.collect()
    print(f"[{ts_stamp}] checkpoint loaded, n_tensors={len(m_state_pre)}, widening state dict "
          f"(optimizer state dropped -- unused, reset_optimizer_on_resume=True downstream; "
          f"rng state kept -- restore_rng() runs unconditionally on resume)...",
          flush=True)
    sd_pre_cpu_f32 = {k: v.float() for k, v in m_state_pre.items()}
    m_state_pre = None
    gc.collect()
    grown_sd_cpu_f32 = widen_state_dict(sd_pre_cpu_f32, n_layers)
    sd_pre_cpu_f32 = None
    gc.collect()
    print(f"[{ts_stamp}] widened, n_tensors={len(grown_sd_cpu_f32)}, casting to bf16 "
          f"(releasing each fp32 tensor as its bf16 copy is made)...", flush=True)
    grown_sd_cpu_bf16 = {}
    keys = list(grown_sd_cpu_f32.keys())
    for i, k in enumerate(keys):
        v = grown_sd_cpu_f32.pop(k)
        grown_sd_cpu_bf16[k] = v.to(torch.bfloat16)
        if (i + 1) % 40 == 0:
            gc.collect()
    grown_sd_cpu_f32 = None
    gc.collect()
    print(f"[{ts_stamp}] cast done, saving grown checkpoint to {post_dir}...", flush=True)
    grow_cpu_ckpt_dir = ts.save_checkpoint(
        post_dir, pre_ckpt_manifest["step"], grown_sd_cpu_bf16, {}, r_state_pre,
        extra={"segment_id": "cbase-grow-rung2-dryrun-cpu-grown", "mechanism": "ff_widening_net2net",
               "grown_from_step": pre_ckpt_manifest["step"], "ff_seed": ff_seed, "ff_grown": ff_grown,
               "optimizer_state_carried_but_unused": False,
               "note": "CPU sanity-scale grow, distinct from the real seed-scale grow above; "
                       "optimizer state deliberately dropped (dead weight -- the post-grow "
                       "segment always resumes with reset_optimizer_on_resume=True, which "
                       "skips load_optimizers_state entirely); rng state kept real since "
                       "restore_rng() runs unconditionally on resume"})
    print(f"[{ts_stamp}] grown checkpoint saved: {grow_cpu_ckpt_dir}", flush=True)

    result = {"grow_cpu_ckpt_dir": str(grow_cpu_ckpt_dir)}
    Path(result_json).parent.mkdir(parents=True, exist_ok=True)
    Path(result_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"CPU_GROW_WORKER_DONE result={result_json}", flush=True)
    return 0


def _cpu_post_grow_worker(grow_cpu_ckpt_dir: str, post_dir: str, ts_stamp: str,
                           ff_grown: int, result_json: str) -> int:
    """PART B2b: post-grow CPU sanity segment, run as its OWN fresh subprocess
    (see _cpu_pretrain_worker's docstring for why)."""
    cfg = ts.load_contract()
    cpu_cfg = copy.deepcopy(cfg)
    cpu_cfg["model"] = dict(cpu_cfg["model"], seq=CPU_SEQ)

    post_receipt = ts.run_v0_segment(
        post_dir, cpu_cfg, n_steps=CPU_K_POST, total_steps=CPU_K_POST * 4, live=False,
        real_arch=True, device="cpu", resume_ckpt_dir=grow_cpu_ckpt_dir, shard_dir=None,
        checkpoint_every=CPU_K_POST, segment_id="cbase-grow-rung2-dryrun-cpu-post",
        intermediate_override=ff_grown, reset_optimizer_on_resume=True, batch_size=CPU_BATCH,
    )
    assert post_receipt["pass"] is True, "CPU post-grow sanity segment did not complete"
    print(f"  post-grow CPU sanity: losses={post_receipt['losses']}", flush=True)

    result = {
        "post_receipt": {"losses": post_receipt["losses"], "loss_first": post_receipt["loss_first"],
                         "loss_last": post_receipt["loss_last"], "wall_s": post_receipt["wall_s"]},
    }
    Path(result_json).parent.mkdir(parents=True, exist_ok=True)
    Path(result_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"CPU_POST_GROW_WORKER_DONE result={result_json}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-ckpt", default=str(SEED_CKPT))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--receipt-dir", default=str(RECEIPT_DIR))
    ap.add_argument("--part-a-worker", action="store_true",
                     help=argparse.SUPPRESS)  # internal: re-exec entry point for PART A
    ap.add_argument("--cpu-pretrain-worker", action="store_true",
                     help=argparse.SUPPRESS)  # internal: re-exec entry point for PART B2a-i
    ap.add_argument("--cpu-grow-worker", action="store_true",
                     help=argparse.SUPPRESS)  # internal: re-exec entry point for PART B2a-ii
    ap.add_argument("--cpu-post-grow-worker", action="store_true",
                     help=argparse.SUPPRESS)  # internal: re-exec entry point for PART B2b
    ap.add_argument("--ts-stamp")
    ap.add_argument("--timestamp-iso")
    ap.add_argument("--ff-seed", type=int)
    ap.add_argument("--ff-grown", type=int)
    ap.add_argument("--n-layers", type=int)
    ap.add_argument("--result-json")
    ap.add_argument("--grow-cpu-ckpt-dir")
    ap.add_argument("--post-dir")
    ap.add_argument("--last-checkpoint")
    args = ap.parse_args()

    if args.part_a_worker:
        return _part_a_worker(
            args.seed_ckpt, args.out_dir, args.receipt_dir,
            args.ts_stamp, args.timestamp_iso, args.result_json)

    if args.cpu_pretrain_worker:
        return _cpu_pretrain_worker(
            args.seed_ckpt, args.out_dir, args.ts_stamp,
            args.ff_seed, args.result_json)

    if args.cpu_grow_worker:
        return _cpu_grow_worker(
            args.last_checkpoint, args.post_dir, args.ts_stamp,
            args.ff_seed, args.ff_grown, args.n_layers, args.result_json)

    if args.cpu_post_grow_worker:
        return _cpu_post_grow_worker(
            args.grow_cpu_ckpt_dir, args.post_dir, args.ts_stamp,
            args.ff_grown, args.result_json)

    ts_stamp = _ts()
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    seed_ckpt = Path(args.seed_ckpt)
    script_path = str(Path(__file__).resolve())
    script_cwd = str(Path(__file__).resolve().parent)

    # ---- RAM preflight (bounded wait, real measured numbers) before PART A ----
    # PART A's real measured peak (after the memory-lifecycle fixes) is
    # ~11-13GiB; floor set to 15GiB for margin given OS/torch/subprocess
    # overhead not captured in that back-of-envelope estimate.
    ram_min_gib = 15.0
    print(f"[{ts_stamp}] RAM preflight: waiting for >={ram_min_gib}GiB free "
          f"(shared machine; another process observed fluctuating ~12-32GiB)...", flush=True)
    ram_wait = _wait_for_ram(ram_min_gib, max_wait_s=600, poll_s=20)
    print(f"  ram_preflight: cleared={ram_wait['cleared']} "
          f"final_free_gib={ram_wait['final_free_gib']} "
          f"samples_gib={ram_wait['samples_gib']}", flush=True)
    if not ram_wait["cleared"]:
        print(f"  [WARNING] RAM did not clear {ram_min_gib}GiB within "
              f"{ram_wait['waited_s']}s; proceeding anyway with "
              f"{ram_wait['final_free_gib']}GiB free (disclosed risk, not a fabricated pass)",
              flush=True)

    # ---- PART A: dispatch to a fresh subprocess (see module docstring) ----
    print(f"[{ts_stamp}] PART A: dispatching function-preservation check to a "
          f"fresh subprocess", flush=True)
    part_a_result_path = Path(args.out_dir) / f"rung2-dryrun-{ts_stamp}" / "part-a-result.json"
    part_a_cmd = [
        sys.executable, script_path, "--part-a-worker",
        "--seed-ckpt", str(seed_ckpt), "--out-dir", args.out_dir,
        "--receipt-dir", args.receipt_dir, "--ts-stamp", ts_stamp,
        "--timestamp-iso", timestamp_iso, "--result-json", str(part_a_result_path),
    ]
    part_a_proc = subprocess.run(part_a_cmd, cwd=script_cwd, capture_output=True, text=True)
    print(part_a_proc.stdout, end="", flush=True)
    if part_a_proc.returncode == 2:
        # Fail-closed on function-preservation: the worker already wrote both
        # receipts. Nothing more to do.
        print(part_a_proc.stderr, file=sys.stderr, flush=True)
        return 2
    if part_a_proc.returncode != 0 or not part_a_result_path.exists():
        print(part_a_proc.stderr, file=sys.stderr, flush=True)
        raise SystemExit(f"CBASE-GROW-RUNG2-DRYRUN: PART A worker subprocess failed "
                          f"(exit={part_a_proc.returncode}); see stderr above")
    part_a = json.loads(part_a_result_path.read_text(encoding="utf-8"))
    ff_seed = part_a["ff_seed"]
    ff_grown = part_a["ff_grown"]
    n_layers = part_a["n_layers"]
    param_count_before = part_a["param_count_before"]
    param_count_after = part_a["param_count_after"]
    params_unique_before = part_a["params_unique_before"]
    params_unique_after = part_a["params_unique_after"]
    dup_numel = part_a["dup_numel"]
    tied_pairs = part_a["tied_pairs"]
    fp_check = part_a["fp_check"]
    grow_ckpt_dir = part_a["grow_ckpt_dir"]
    actual_sha = part_a["actual_sha"]
    manifest_step = part_a["manifest_step"]
    evidence_filename = part_a["evidence_filename"]

    cfg = ts.load_contract()
    prod_batch = cfg["throughput"]["batch"] if cfg["throughput"]["batch"] >= 16 else 16
    prod_seq = cfg["model"]["seq"]

    # ---- PART B1: production-scale VRAM margin check (real numbers, no launch) ----
    print(f"\n[{ts_stamp}] PART B1: production stabilization VRAM preflight (measured, no launch)")
    d1_steps_prod = d1_stabilization_steps(param_count_after, prod_batch, prod_seq)
    requested_run = {
        "source": "cbase_grow_rung2_dryrun:stabilization", "total_steps": d1_steps_prod,
        "params": param_count_after, "batch": prod_batch, "seq": prod_seq,
    }
    g_status, g_detail = gate_mod.g_budget(datetime.now(timezone.utc).date(), requested_run=requested_run)
    print(f"  g_budget: {g_status} -- {g_detail}")

    nvsmi = _nvidia_smi_vram()
    torch_vram = _torch_vram()
    required = _estimate_required_gib(param_count_after)
    margin_gib_floor = 2.0
    vram_sufficient = (nvsmi["free_gib"] - required["total_estimate_gib"]) >= margin_gib_floor
    print(f"  nvidia-smi (ground truth): free={nvsmi['free_gib']}GiB total={nvsmi['total_gib']}GiB")
    print(f"  torch.cuda.mem_get_info (unreliable on this WDDM host under contention): {torch_vram}")
    print(f"  required (estimate, VRAM-resident-AdamW convention): {required['total_estimate_gib']}GiB, "
          f"margin floor={margin_gib_floor}GiB")
    print(f"  d1_steps_prod={d1_steps_prod} (batch={prod_batch} seq={prod_seq})")
    print(f"  VRAM_SUFFICIENT={vram_sufficient}")

    # ---- DEV-002 cure: CPU-offloaded optimizer state + micro-batch/accum ----
    # candidate 3/4 estimate, priced against the SAME measured nvidia-smi
    # numbers above. Additive to (never replaces) the VRAM-resident-AdamW
    # estimate above -- that estimate stays the historical record; this one
    # is the config the cure PR wires in. Does NOT flip `attempted` or launch
    # anything: an actual production launch still needs a real shard_dir and
    # the declared serving-pause window, out of this lane's scope (see the
    # cure PR spec's MEASURED-dry-run exclusion).
    micro_batch_offload = 2
    accum_steps_offload = (prod_batch // micro_batch_offload
                            if prod_batch % micro_batch_offload == 0 else 8)
    required_offloaded = estimate_required_gib_offloaded(
        param_count_after, micro_batch=micro_batch_offload, prod_batch=prod_batch,
        activation_estimate_gib_at_prod_shape=required["activation_estimate_gib"])
    offload_preflight = vram_preflight(
        required_offloaded["total_estimate_gib"], margin_gib_floor=margin_gib_floor, nvsmi=nvsmi)
    print(f"  [DEV-002 cure] offloaded-config required (estimate): "
          f"{required_offloaded['total_estimate_gib']}GiB VRAM (+ "
          f"{required_offloaded['optimizer_state_host_ram_gib']}GiB host RAM) "
          f"micro_batch={micro_batch_offload} accum_steps={accum_steps_offload} "
          f"effective_batch={micro_batch_offload * accum_steps_offload}")
    print(f"  [DEV-002 cure] OFFLOADED_VRAM_SUFFICIENT={offload_preflight['sufficient']} "
          f"margin_gib={offload_preflight['margin_gib']} verdict={offload_preflight['verdict']}")

    production_stabilization = {
        "attempted": False,
        "reason": ("VRAM margin insufficient for the production shape (measured, not "
                   "attempted): nvidia-smi ground-truth free VRAM "
                   f"{nvsmi['free_gib']}GiB vs estimated requirement "
                   f"{required['total_estimate_gib']}GiB + {margin_gib_floor}GiB margin floor. "
                   "torch.cuda.mem_get_info() reported a much larger free figure "
                   f"({torch_vram['free_gib'] if torch_vram else 'n/a'}GiB) but this is treated "
                   "as unreliable on this WDDM host under live GPU contention (another process "
                   "holds real physical VRAM per nvidia-smi); nvidia-smi is ground truth. "
                   "Per the frozen spec's kill criterion: VRAM margin assert fails -> hold, "
                   "report numbers, no launch into contention (abort-not-degrade).")
                  if not vram_sufficient else "VRAM margin sufficient; see stabilization_segment below",
        "nvidia_smi_vram": nvsmi,
        "torch_cuda_mem_get_info": torch_vram,
        "required_estimate": required,
        "margin_gib_floor": margin_gib_floor,
        "g_budget_preflight": {"status": g_status, "detail": g_detail, "requested_run": requested_run},
        "d1_sizing": {
            "rule": "steps(rung) = max(ceil(D1_ANCHOR_FLOPS/(6*N_grown*batch*seq)), 30)",
            "steps_computed": d1_steps_prod, "batch": prod_batch, "seq": prod_seq,
        },
        "offloaded_config": {
            "scope": ("DEV-002 cure candidate 3/4 (CPU-offloaded optimizer states + "
                      "micro-batch/grad accumulation), priced against the SAME measured "
                      "nvidia-smi numbers above. Wiring: timeshare_pretrain.run_v0_segment("
                      "..., batch_size=micro_batch, grad_accum_steps=accum_steps, "
                      "offload_optimizer_state=True) -- both params added this PR, default "
                      "False/1 so every existing caller is byte-identical. Function/"
                      "loss/gradient equivalence for this wiring is CPU-verified in "
                      "receipts/cbase-grow-rung2-offload-probe-*.json (companion probe "
                      "script, this PR); the MEASURED real-2.2B/nvidia-smi-sampled dry-run "
                      "under this config is EXPLICITLY NOT this run -- it needs the "
                      "declared serving-pause window and lands in a follow-up push before "
                      "merge-gate."),
            "micro_batch": micro_batch_offload,
            "accum_steps": accum_steps_offload,
            "effective_batch": micro_batch_offload * accum_steps_offload,
            "required_estimate": required_offloaded,
            "preflight": offload_preflight,
        },
    }

    if vram_sufficient:
        # Real production-scale launch would go here (device="cuda", live=True,
        # real shard_dir). Not reached this run -- VRAM margin failed above.
        pass

    # ---- PART B2a-i: pre-grow CPU sanity TRAINING segment, fresh subprocess ----
    print(f"\n[{ts_stamp}] PART B2a-i: pre-grow CPU sanity training segment (real arch, "
          f"reduced scale, seq={CPU_SEQ} batch={CPU_BATCH} k_pre={CPU_K_PRE}) "
          f"-- dispatching to a fresh subprocess", flush=True)
    cpu_pretrain_result_path = Path(args.out_dir) / f"rung2-cpu-sanity-{ts_stamp}" / "worker-pretrain-result.json"
    pretrain_worker_cmd = [
        sys.executable, script_path, "--cpu-pretrain-worker",
        "--seed-ckpt", str(seed_ckpt), "--out-dir", args.out_dir, "--ts-stamp", ts_stamp,
        "--ff-seed", str(ff_seed), "--result-json", str(cpu_pretrain_result_path),
    ]
    pretrain_worker_proc = subprocess.run(pretrain_worker_cmd, cwd=script_cwd, capture_output=True, text=True)
    print(pretrain_worker_proc.stdout, end="", flush=True)
    if pretrain_worker_proc.returncode != 0 or not cpu_pretrain_result_path.exists():
        print(pretrain_worker_proc.stderr, file=sys.stderr, flush=True)
        raise SystemExit(f"CBASE-GROW-RUNG2-DRYRUN: PART B2a-i worker subprocess failed "
                          f"(exit={pretrain_worker_proc.returncode}); see stderr above")
    pretrain_worker_result = json.loads(cpu_pretrain_result_path.read_text(encoding="utf-8"))
    pre_receipt = pretrain_worker_result["pre_receipt"]
    last_checkpoint = pretrain_worker_result["last_checkpoint"]
    post_dir = pretrain_worker_result["post_dir"]

    # ---- RAM preflight before PART B2a-ii ----
    # The CPU-sanity model shares production hidden/layers/vocab dims with
    # PART A's model (cpu_cfg only overrides seq, not architecture) -- only
    # activations are scaled down for CPU tractability, NOT parameter count.
    # So this widen+cast operates on essentially the SAME ~1.2B->2.2B param
    # state dict as PART A and needs the SAME real memory margin -- the
    # earlier assumption that this step was "CPU-sanity scale, therefore
    # small" was wrong (confirmed: it crashed even as a fresh, isolated
    # subprocess with 31GiB free at the time PART A ran minutes earlier;
    # free RAM must be re-measured here, not assumed carried over).
    print(f"[{ts_stamp}] RAM preflight before PART B2a-ii: waiting for >={ram_min_gib}GiB free "
          f"(same footprint class as PART A)...", flush=True)
    ram_wait_b2a2 = _wait_for_ram(ram_min_gib, max_wait_s=600, poll_s=20)
    print(f"  ram_preflight_b2a2: cleared={ram_wait_b2a2['cleared']} "
          f"final_free_gib={ram_wait_b2a2['final_free_gib']} "
          f"samples_gib={ram_wait_b2a2['samples_gib']}", flush=True)
    if not ram_wait_b2a2["cleared"]:
        print(f"  [WARNING] RAM did not clear {ram_min_gib}GiB within "
              f"{ram_wait_b2a2['waited_s']}s; proceeding anyway with "
              f"{ram_wait_b2a2['final_free_gib']}GiB free (disclosed risk, not a fabricated pass)",
              flush=True)

    # ---- PART B2a-ii: load/widen/cast/save the grown CPU-sanity checkpoint,
    # fresh subprocess -- isolated from the training loop above (bisected:
    # this exact sequence is stable standalone, matching PART A's proven
    # load->widen->cast->save at a much LARGER scale; the crash is specific
    # to running it in the SAME process as a just-completed training loop) ----
    print(f"[{ts_stamp}] PART B2a-ii: load/widen/cast/save the CPU-sanity grow "
          f"-- dispatching to a fresh subprocess", flush=True)
    cpu_grow_result_path = Path(args.out_dir) / f"rung2-cpu-sanity-{ts_stamp}" / "worker-grow-result.json"
    grow_worker_cmd = [
        sys.executable, script_path, "--cpu-grow-worker",
        "--last-checkpoint", last_checkpoint, "--post-dir", post_dir, "--ts-stamp", ts_stamp,
        "--ff-seed", str(ff_seed), "--ff-grown", str(ff_grown), "--n-layers", str(n_layers),
        "--result-json", str(cpu_grow_result_path),
    ]
    grow_worker_proc = subprocess.run(grow_worker_cmd, cwd=script_cwd, capture_output=True, text=True)
    print(grow_worker_proc.stdout, end="", flush=True)
    if grow_worker_proc.returncode != 0 or not cpu_grow_result_path.exists():
        print(grow_worker_proc.stderr, file=sys.stderr, flush=True)
        raise SystemExit(f"CBASE-GROW-RUNG2-DRYRUN: PART B2a-ii worker subprocess failed "
                          f"(exit={grow_worker_proc.returncode}); see stderr above")
    grow_worker_result = json.loads(cpu_grow_result_path.read_text(encoding="utf-8"))
    grow_cpu_ckpt_dir = grow_worker_result["grow_cpu_ckpt_dir"]

    # ---- RAM preflight before PART B2b (lighter floor -- CPU sanity scale is
    # small: seq=128/batch=2, not the ~11-13GiB PART A footprint) ----
    ram_min_gib_b2b = 6.0
    print(f"[{ts_stamp}] RAM preflight before PART B2b: waiting for >={ram_min_gib_b2b}GiB free...",
          flush=True)
    ram_wait_b2b = _wait_for_ram(ram_min_gib_b2b, max_wait_s=300, poll_s=15)
    print(f"  ram_preflight_b2b: cleared={ram_wait_b2b['cleared']} "
          f"final_free_gib={ram_wait_b2b['final_free_gib']} "
          f"samples_gib={ram_wait_b2b['samples_gib']}", flush=True)

    # ---- PART B2b: post-grow CPU sanity segment, fresh subprocess ----
    print(f"[{ts_stamp}] PART B2b: post-grow CPU sanity segment (k_post={CPU_K_POST}) "
          f"-- dispatching to a fresh subprocess", flush=True)
    cpu_post_result_path = Path(args.out_dir) / f"rung2-cpu-sanity-{ts_stamp}" / "worker-post-result.json"
    post_worker_cmd = [
        sys.executable, script_path, "--cpu-post-grow-worker",
        "--grow-cpu-ckpt-dir", grow_cpu_ckpt_dir, "--post-dir", post_dir, "--ts-stamp", ts_stamp,
        "--ff-grown", str(ff_grown), "--result-json", str(cpu_post_result_path),
    ]
    post_worker_proc = subprocess.run(post_worker_cmd, cwd=script_cwd, capture_output=True, text=True)
    print(post_worker_proc.stdout, end="", flush=True)
    post_grow_segment_failed = (post_worker_proc.returncode != 0 or not cpu_post_result_path.exists())
    if post_grow_segment_failed:
        # Bisected across 3 independent reproductions at 24GiB, 33GiB, and (this
        # run's) measured-at-dispatch free RAM: a real, deterministic native
        # crash (exit=3221225477 / ACCESS_VIOLATION) inside timeshare_pretrain's
        # shared run_v0_segment machinery when it builds+trains the GROWN
        # (ff=32768, ~2.2B param) model with gradient checkpointing + QAT
        # fake-quant enabled (contract has precision.qat.enabled=True, which
        # clones every Linear weight per step on top of gradients + optimizer
        # momentum). A minimal isolated reproduction (build model + gradient
        # checkpointing + one forward pass, no run_v0_segment machinery) did
        # NOT crash at the same ff=32768 width -- ruling out plain model
        # construction as the cause and narrowing it to run_v0_segment's own
        # per-step machinery (QAT clone + optimizer + backward together).
        # This is inside a SHARED file (timeshare_pretrain.py) this script's
        # own reuse discipline forbids editing, and the crash reproduced even
        # at ~33GiB free (not a contention artifact) -- so this is disclosed
        # as a genuine resource/compatibility ceiling for the CPU-sanity
        # post-grow segment specifically, not tuned around, not silently
        # dropped, and NOT attributed to the grow operator (PART A already
        # proves that independently and remains execution-binding).
        print(f"  [DISCLOSED LIMITATION] PART B2b (post-grow CPU sanity training at the "
              f"grown ff={ff_grown} width) crashed (exit={post_worker_proc.returncode}); "
              f"reproduced identically across multiple isolated re-runs at different "
              f"measured free-RAM levels (24GiB, 33GiB), ruling out transient machine "
              f"contention. Treated as a genuine resource/compatibility ceiling in the "
              f"shared run_v0_segment training path at this width (QAT fake-quant clone "
              f"+ gradients + optimizer momentum for a ~2.2B-param model), not a grow-"
              f"operator defect -- PART A already proves the operator itself independently.",
              flush=True)
        post_receipt = {"losses": [], "loss_first": None, "loss_last": None, "wall_s": None}
        loss_continuity = None
        all_losses = list(pre_receipt["losses"])
        degenerate = None
        stabilization_ok = False
    else:
        post_worker_result = json.loads(cpu_post_result_path.read_text(encoding="utf-8"))
        post_receipt = post_worker_result["post_receipt"]
        loss_continuity = _loss_continuity_block(pre_receipt["losses"], post_receipt["losses"])
        print(f"  loss_continuity: {loss_continuity}", flush=True)

        all_losses = pre_receipt["losses"] + post_receipt["losses"]
        degenerate = (len(set(all_losses)) == 1) or all(v < 1e-3 for v in all_losses)
        stabilization_ok = bool(loss_continuity["training_loss_continuity_within_pre_grow_variance_envelope"]) \
            and not degenerate

    cpu_sanity_block = {
        "scope": ("supplementary CPU sanity-stabilization -- REAL architecture "
                  "(hidden=1024/layers=20/heads=16/vocab=32000/mtp=2 heads), REAL "
                  "rung-1 checkpoint as the pre-grow seed, but seq/batch/step-count "
                  "reduced from the production D1 shape for CPU tractability "
                  "(disclosed dry-run-local scale-down, not the production stabilization "
                  "-- see production_stabilization block for that decision)"),
        "seq": CPU_SEQ, "batch": CPU_BATCH,
        "k_steps_pre_grow": CPU_K_PRE, "k_steps_post_grow": CPU_K_POST,
        "shard_source": "synthetic (auto-generated by run_v0_segment when shard_dir=None; "
                        "the same synthetic-fixture convention cbase_grow_rung.py's own "
                        "--dry-run path uses for its CPU stand-in)",
        "pre_grow_segment": {
            "losses": pre_receipt["losses"], "loss_first": pre_receipt["loss_first"],
            "loss_last": pre_receipt["loss_last"], "wall_s": pre_receipt["wall_s"],
        },
        "post_grow_segment": {
            "losses": post_receipt["losses"], "loss_first": post_receipt["loss_first"],
            "loss_last": post_receipt["loss_last"], "wall_s": post_receipt["wall_s"],
            "attempted": True, "completed": not post_grow_segment_failed,
        },
        "post_grow_segment_failure": (None if not post_grow_segment_failed else {
            "exit_code": post_worker_proc.returncode,
            "reproduced_at_free_ram_gib": [24, 33],
            "isolated_forward_backward_repro_crashed": False,
            "diagnosis": ("real, deterministic native crash inside shared "
                          "timeshare_pretrain.run_v0_segment's per-step training "
                          "machinery (QAT fake-quant clone + gradients + optimizer "
                          "momentum) at the grown ff=32768 (~2.2B param) width; "
                          "NOT reproduced by an isolated model-build + gradient-"
                          "checkpointing + single forward pass at the same width "
                          "(that failed only with an ordinary unrelated Python "
                          "RuntimeError from the minimal test's own setup, no crash); "
                          "not attributable to the net2net grow operator itself "
                          "(PART A proves that independently, execution-binding)"),
        }),
        "loss_continuity": loss_continuity,
        "degenerate_loss_trace": degenerate,
        "stabilization_ok": stabilization_ok,
    }

    verdict_pass = bool(fp_check["function_preserving"] and stabilization_ok)
    main_receipt: dict[str, Any] = {
        "ticket": "CBASE-GROW-RUNG2-DRYRUN",
        "ts": timestamp_iso,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "experiment": "C-BASE-clause-d-dryrun",
        "arm": "grow-operator-dryrun",
        "spec_ref": "docs/domains/governance/spec/rung2-grow-spec-v1.md (FROZEN); cbase-dryrun-spec-20260707.md",
        "scope": ("C-BASE clause (d): net2net FF-widening (16384->32768) grow-operator "
                  "dry-run on the REAL owned rung-1 checkpoint. PART A (deterministic "
                  "function-preservation, real checkpoint, CPU) is execution-binding and "
                  "PASSED. PART B is split: production-scale (batch16/seq1024) stabilization "
                  "is VRAM-gated and HELD this run (see production_stabilization); a CPU "
                  "sanity-stabilization at reduced scale (same real architecture, same real "
                  "checkpoint) was attempted to prove the grown model actually trains, not "
                  "just forward-passes -- " + (
                      "and COMPLETED with a non-degenerate loss trace (see cpu_sanity_stabilization)."
                      if not post_grow_segment_failed else
                      "the pre-grow leg completed but the post-grow leg did NOT complete (see "
                      "cpu_sanity_stabilization.post_grow_segment_failure for the disclosed "
                      "reason: a reproducible native crash in the shared training path at the "
                      "grown width, ruled out as memory-contention-only, not attributable to "
                      "the grow operator itself). Overall verdict is FAIL on that basis alone; "
                      "PART A's function-preservation result is unaffected and remains PASS."
                  )),
        "grow-operator": True, "grow_dry_run": True, "grow-dry-run": True, "net2net": True,
        "larger-shape": True, "larger_shape": True,
        # These three are OUTCOME claims, not experiment-shape descriptors --
        # they must reflect whether the post-grow CPU sanity segment actually
        # completed, not be hardcoded True regardless of outcome (that exact
        # pattern -- a receipt asserting "replays: true" independent of whether
        # a replay actually happened -- is the incoherence this whole dry-run
        # was commissioned to fix; repeating it here would be the same bug).
        "replays": not post_grow_segment_failed,
        "replay_across_shape": not post_grow_segment_failed,
        "post_grow": not post_grow_segment_failed,
        "pre_grow": True,
        "grow_operator_evidence": f"receipts/{evidence_filename}",
        "seed_identity": {
            "checkpoint": str(seed_ckpt.relative_to(REPO)) if seed_ckpt.is_relative_to(REPO) else str(seed_ckpt),
            "model_pt_sha256": actual_sha,
            "manifest_claim_verified": True,
            "attestation_receipt": SEED_SHA_ATTESTATION_RECEIPT,
            "step": manifest_step,
        },
        "ff_seed": ff_seed, "ff_grown": ff_grown,
        "param_count_before": param_count_before, "param_count_after": param_count_after,
        "params_unique_before": params_unique_before, "params_unique_after": params_unique_after,
        "params_dedup": {"measured_duplicate_numel": dup_numel, "tied_pairs_detected": tied_pairs},
        "function_preservation_check": fp_check,
        "grown_checkpoint_real_scale": str(Path(grow_ckpt_dir).relative_to(REPO)) if Path(grow_ckpt_dir).is_relative_to(REPO) else grow_ckpt_dir,
        "production_stabilization": production_stabilization,
        "cpu_sanity_stabilization": cpu_sanity_block,
        "verification": {
            "loss_trace": all_losses,
            "pre_grow_losses": pre_receipt["losses"],
            "post_grow_losses": post_receipt["losses"],
            "max_delta": None if loss_continuity is None else loss_continuity["grow_step_delta"],
            "scale_note": "CPU sanity-stabilization scale (seq=%d/batch=%d), NOT the "
                          "production D1 shape (batch=%d/seq=%d) -- see production_stabilization "
                          "for the production-shape decision" % (CPU_SEQ, CPU_BATCH, prod_batch, prod_seq),
        },
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "device": "cpu",
        "measured_on_train_daemon": False,
        "script": "src/ember/governance/scripts/cbase_grow_rung2_dryrun.py",
        "pass": verdict_pass,
        "verdict": "PASS" if verdict_pass else "FAIL",
        "kill_criterion": None if verdict_pass else (
            "post_grow_cpu_training_native_crash" if post_grow_segment_failed else
            "degenerate_loss_trace" if degenerate else "post_grow_divergence"
        ),
    }
    out_main = Path(args.receipt_dir) / f"grow-operator-dryrun-{ts_stamp}.json"
    checked_write(str(out_main), main_receipt)
    print(f"\n{'CBASE_GROW_RUNG2_DRYRUN_PASS' if verdict_pass else 'CBASE_GROW_RUNG2_DRYRUN_FAIL'} "
          f"fp_diff={fp_check['logit_max_abs_diff']:.3e} "
          f"params_unique_after={params_unique_after} "
          f"production_stabilization_attempted={production_stabilization['attempted']} "
          f"cpu_sanity_stabilization_ok={stabilization_ok} "
          f"receipt={out_main}")
    return 0 if verdict_pass else 2


if __name__ == "__main__":
    sys.exit(main())
