#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_stabilize.py — issue #480 LAUNCH SPEC: first stabilize leg
for the rung-2 grown (ff=32768) model, Config C (micro_batch=1 + memmap
optstate offload, MEASURED_PASS per receipts/cbase-grow-rung2-gpu-offload-
probe-20260709T092042Z.json), against the REAL verified 26-shard corpus
(external-corpus/shards-v0, #77: 6,977,868,758 tokens, 26/26 shas
re-verified).

100 optimizer steps in 10-step blocks. Per-block receipt: loss, VRAM peak,
s/step, watts (nvidia-smi power.draw sample) + running kWh. Boundary policy:
Branch A momentum transplant (src/ember/governance/scripts/rung_boundary_momentum_transplant.py,
adjudicated law per receipts/cbase-grow-rung2-event-b513-b4rerun-b3.json,
transplant cos_alignment=0.9536 >= 0.82) -- NOT reset_optimizer_on_resume
(Branch B), which is what cbase_grow_live.py's post-grow segment currently
hardcodes for the GROW step (a different boundary than this STABILIZE leg).

CORRECTION (2026-07-30, issue #580 PR B): the historical disclosure below
is retained as provenance, not current truth. The asserted 45-tensor gap was
a GLOBAL-model-id versus optimizer-local-id comparison artifact. The shared
checker now resolves each parameter through build_optimizer_id_maps; the
corrected result is zero missing optimizer slots, and the 20-layer transplant
ruling is established by the dated sibling evidence. This historical launcher
is execution-denied by current policy; no path may revive its partial-hybrid
claim or emit a new receipt under that superseded interpretation.

DISCLOSED DEVIATION (team-lead ruling, 2026-07-09, receipts/cbase-grow-
rung2-stabilize-transplant-wall-diagnostic-20260709T130000Z.json): the seed
optimizer.pt (models/.../rung1-20260703T155447Z/stabilize/checkpoints/
step-00000766) carries a real, historical, write-time truncation -- global
param ids 140-184 (45 of 185 tensors: layer 15's FF gate/up/down_proj, all
of layers 16-19, and the tail norm/head/mtp_heads params) have ZERO
optimizer state anywhere (neither muon nor adamw), in EVERY surviving
checkpoint (cross-checked against step-00000730, same gap). Routing code
(split_param_groups, this file's import of timeshare_pretrain, lines
801-821) is confirmed unconditional over all layers -- this is not a
routing exclusion, the data was simply never captured (most likely: commit
2445c4b "file-backed optimizer state to eliminate commit exhaustion",
landed 2026-07-08, one day AFTER this checkpoint was written 2026-07-03).
Branch A cannot be made whole; per team-lead's ruling this script applies
Branch A exactly where verified momentum exists (rung_boundary_momentum_
transplant.transplant_muon_ff_momentum called with n_layers=15, the
UNMODIFIED shared module -- see N_LAYERS_VERIFIED_MOMENTUM below) and lets
the genuinely-empty tail (TRUNCATED_PARAM_ID_START..end) fall through to a
natural optimizer-state reset (absent state = fresh init at first step,
standard torch optimizer semantics) -- never a general "skip missing data"
behavior: build_transplanted_resume_checkpoint hard-asserts the missing-id
set equals EXACTLY this incident's enumerated range before proceeding, and
raises (fail-closed, not silently) on any deviation from that exact shape.

Reuse discipline (no duplicated math): timeshare_pretrain.run_v0_segment /
save_checkpoint / load_checkpoint / load_optimizers_state (the real pretrain
loop, checkpoint format, resume path -- never reimplemented);
rung_boundary_momentum_transplant.transplant_muon_ff_momentum (the tested
Branch-A wiring PR #532 built but explicitly left un-wired to a live call
site -- "Wiring this module as a live call site inside the actual stabilize
launcher is explicitly out of scope here" -- this script is that wiring);
cpu_offload_adamw.estimate_required_gib_offloaded / vram_preflight /
nvidia_smi_vram (the DEV-002 cure's own preflight math, reused for g1);
receipt_write.checked_write.

Kill conditions (in-run asserts, checked between blocks -- a block always
completes and checkpoints before this script evaluates it, so an abort here
never interrupts run_v0_segment mid-block; the just-completed block's own
checkpoint IS the abort-point checkpoint receipt):
  k1: any block's measured VRAM peak > 20.5 GiB -> abort (estimator invalidated)
  k2: block-mean loss > 14.359 on 3 consecutive blocks -> abort (divergence)
  k3: measured s/step > 160 (2x the 81.2 s/step measured baseline) -> abort
      (offload thrash)

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

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
# issue2015 exact-local-import-end:scripts/timeshare_pretrain.py                                       # noqa: E402
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
nvidia_smi_vram = getattr(_ember_af5148f80571f78d_module, 'nvidia_smi_vram')
# issue2015 exact-local-import-end:src/ember/governance/scripts/cpu_offload_adamw.py
from rung_boundary_momentum_transplant import (                       # noqa: E402
    transplant_muon_ff_momentum, BOUNDARY_POLICY,
)
# issue2015 exact-local-import:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py
import importlib.util as _ember_ba82af0721d80c9f_importlib
import sys as _ember_ba82af0721d80c9f_sys
from pathlib import Path as _ember_ba82af0721d80c9f_Path
_ember_ba82af0721d80c9f_path = _ember_ba82af0721d80c9f_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'p5_ratio_audit', 'run_p5_audit.py')
if not _ember_ba82af0721d80c9f_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
_ember_ba82af0721d80c9f_aliases = ('_ember_issue2015_ba82af0721d80c9f', 'p5_ratio_audit.run_p5_audit', 'run_p5_audit', 'scripts.p5_ratio_audit.run_p5_audit')
_ember_ba82af0721d80c9f_existing = []
for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
    _ember_ba82af0721d80c9f_candidate = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
    if _ember_ba82af0721d80c9f_candidate is not None and all(_ember_ba82af0721d80c9f_candidate is not item for item in _ember_ba82af0721d80c9f_existing):
        _ember_ba82af0721d80c9f_existing.append(_ember_ba82af0721d80c9f_candidate)
if len(_ember_ba82af0721d80c9f_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
if _ember_ba82af0721d80c9f_existing:
    _ember_ba82af0721d80c9f_module = _ember_ba82af0721d80c9f_existing[0]
    _ember_ba82af0721d80c9f_observed = getattr(_ember_ba82af0721d80c9f_module, '__file__', None)
    if _ember_ba82af0721d80c9f_observed is None or _ember_ba82af0721d80c9f_Path(_ember_ba82af0721d80c9f_observed).resolve() != _ember_ba82af0721d80c9f_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
else:
    _ember_ba82af0721d80c9f_spec = _ember_ba82af0721d80c9f_importlib.spec_from_file_location('_ember_issue2015_ba82af0721d80c9f', _ember_ba82af0721d80c9f_path)
    if _ember_ba82af0721d80c9f_spec is None or _ember_ba82af0721d80c9f_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
    _ember_ba82af0721d80c9f_module = _ember_ba82af0721d80c9f_importlib.module_from_spec(_ember_ba82af0721d80c9f_spec)
    for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
        _ember_ba82af0721d80c9f_prior = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
        if _ember_ba82af0721d80c9f_prior is not None and _ember_ba82af0721d80c9f_prior is not _ember_ba82af0721d80c9f_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
        _ember_ba82af0721d80c9f_sys.modules[_ember_ba82af0721d80c9f_alias] = _ember_ba82af0721d80c9f_module
    try:
        _ember_ba82af0721d80c9f_spec.loader.exec_module(_ember_ba82af0721d80c9f_module)
    except BaseException:
        for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
            if _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias) is _ember_ba82af0721d80c9f_module:
                _ember_ba82af0721d80c9f_sys.modules.pop(_ember_ba82af0721d80c9f_alias, None)
        raise
for _ember_ba82af0721d80c9f_alias in _ember_ba82af0721d80c9f_aliases:
    _ember_ba82af0721d80c9f_prior = _ember_ba82af0721d80c9f_sys.modules.get(_ember_ba82af0721d80c9f_alias)
    if _ember_ba82af0721d80c9f_prior is not None and _ember_ba82af0721d80c9f_prior is not _ember_ba82af0721d80c9f_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py')
    _ember_ba82af0721d80c9f_sys.modules[_ember_ba82af0721d80c9f_alias] = _ember_ba82af0721d80c9f_module
EngagementFailure = getattr(_ember_ba82af0721d80c9f_module, 'EngagementFailure')
enumerate_missing_optimizer_state_ids = getattr(_ember_ba82af0721d80c9f_module, 'enumerate_missing_optimizer_state_ids')
# issue2015 exact-local-import-end:src/ember/governance/scripts/p5_ratio_audit/run_p5_audit.py
from receipt_write import checked_write                                # noqa: E402
from optimizer_transplant_provenance import (                           # noqa: E402
    build_transplant_provenance,
    checkpoint_bundle_sha256,
    load_transplant_provenance,
    load_verified_custody_checkpoint,
    publish_checkpoint_to_custody,
    sha256_file as provenance_sha256_file,
    verify_destination_optimizer_binding,
    verify_transplant_provenance,
    write_transplant_provenance_atomic,
)

REPO = Path(__file__).resolve().parents[4]
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

# ---- shard-loader memmap opt-in, wired at THIS caller only (2026-07-09) ----
# run_v0_segment's own PackedShardLoader(shard_dir, seq, n_mtp) call (line
# ~1581 in timeshare_pretrain.py) never forwards mmap_cache_dir, so every
# run_v0_segment caller is hardcoded onto the LEGACY np.fromfile+concatenate
# path -- documented in PackedShardLoader's own docstring as already having
# raised numpy._core._exceptions._ArrayMemoryError at BOTH 17.5GB and 30.6GB
# free RAM (issue #118 P1 sweep, 2026-07-08 tracebacks): a contiguous-address-
# -space/fragmentation ceiling, not a capacity one. This leg hit the identical
# error at ~16GB free (RUN retry 1, 20260709T152049Z log). The fix already
# EXISTS and is tested (_build_or_open_memmap_cache + the opt-in mmap_cache_dir
# kwarg PackedShardLoader.__init__ already accepts) -- it is simply never
# reached by run_v0_segment's hardcoded call. Rather than edit the SHARED
# timeshare_pretrain.py (out of scope here, same discipline as the BUILD-stage
# staged-save fix), monkeypatch PackedShardLoader.__init__ from THIS script
# only so every caller (including the one inside run_v0_segment) transparently
# gets mmap_cache_dir set -- zero bytes of the shared module change, zero
# duplicated math (reuses _build_or_open_memmap_cache verbatim), fully
# reversible (delete these 12 lines, behavior reverts exactly).
_ORIG_PACKED_SHARD_LOADER_INIT = ts.PackedShardLoader.__init__


COMMIT_MARGIN_FLOOR_GB = 6.0  # team-lead ruling 2026-07-09 (v8 launch spec, v7 death cure)


# ---- v8 governed-abort receipt (ember #627 comment 4936627594, point 1) ---
# "Governed abort writes NO receipt file." Pre-cure, a GOVERNOR_COMMIT_FAIL
# left only the tee'd stdout log and the last checkpoint -- a clean abort with
# no receipt forces log archaeology and checkpoint-guessing (the AC2 pace-
# smoke run's completion was misread as success from the checkpoint alone
# before the log surfaced). Fail-closed fix: _commit_margin_assert's refusal
# branch below writes a structured receipt to the run's receipt dir BEFORE
# SystemExit propagates. Two tiny module-level trackers (both own-script,
# set by main()/_run_block, never by the shared timeshare_pretrain.py) give
# the assert -- a low-level helper with no run-context args -- somewhere to
# write and something to cite as the last known-good checkpoint without
# threading extra parameters through every one of its many call sites
# (front-load memmap creation, every stage marker).
_RECEIPT_DIR_STATE: dict[str, str | None] = {"path": None}
_LAST_KNOWN_CHECKPOINT: dict[str, str | None] = {"path": None}


def _set_abort_receipt_dir(path: str) -> None:
    _RECEIPT_DIR_STATE["path"] = str(path)


def _note_last_checkpoint(path: str | None) -> None:
    """Record the most recently known-good checkpoint dir, if any. Called at
    every point one becomes known (BUILD output, a block's incoming resume
    checkpoint, a block's own freshly-written checkpoint) so a governed abort
    firing ANYWHERE in this process can cite the true last checkpoint. A None/
    falsy path is a no-op -- never overwrites a real path with unknown."""
    if path:
        _LAST_KNOWN_CHECKPOINT["path"] = str(path)


# ---- R2 (ember #627 point 1): in-process commit read ----------------------
# The v9 audit's R2 finding: _read_commit_gb launched a powershell/Get-Counter
# SUBPROCESS, and the governed `.grad.f32` wrapper called it before EVERY lazy
# grad re-create -- 2.4-2.6 s per spawn x ~140 re-creates/step (#594 M1), the
# dominant regression term. R3 (cpu_offload_adamw.zero_grad) removes the
# per-step re-creates; R2 removes the subprocess itself so that ANY remaining
# governed read (front-load, stage/block boundaries, or a lazy fallback that
# should now never fire) costs microseconds and NO subprocess exists anywhere
# in the step path.
#
# GlobalMemoryStatusEx is the exact in-process equivalent of the two perf
# counters this replaces (verified equal on this host: ullTotalPageFile ==
# `\Memory\Commit Limit`; ullTotalPageFile - ullAvailPageFile ==
# `\Memory\Committed Bytes`). Windows-native, same platform assumption the
# powershell call already carried (the whole commit-exhaustion failure class
# is Windows pagefile/commit physics) -- on any non-Windows interpreter the
# ctypes.windll attribute simply does not exist and the function returns None,
# preserving the never-raises-on-read-failure contract unchanged.
COUNTERS = {"governor_reads": 0}


def get_governor_reads() -> int:
    return int(COUNTERS.get("governor_reads", 0))


def reset_governor_reads() -> None:
    COUNTERS["governor_reads"] = 0


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_COMMIT_GB = 1024.0 ** 3  # commit counters are bytes; /2^30 == PowerShell's /1GB


def _read_commit_gb() -> dict | None:
    """Ground-truth Windows commit (committed + limit), ONE in-process
    GlobalMemoryStatusEx call for both counters -- same measurement source
    _stage_marker already used for its printed committed_gb, so the printed
    number and the commit-margin governor's pass/fail decision remain the SAME
    measurement, never two independent reads that could disagree. NO
    subprocess (R2 cure, ember #627 point 1). Every call increments the
    governor_reads counter so the number of governor reads per block is
    observable in the log (falsifiable against the prereg's prediction).
    Returns None (never raises) on any read failure -- a counter read failing
    must never itself crash the run; see _commit_margin_assert for what a
    failed read means to the governor."""
    COUNTERS["governor_reads"] += 1
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if not ok:
            return None
        limit_gb = round(stat.ullTotalPageFile / _COMMIT_GB, 3)
        free_gb = round(stat.ullAvailPageFile / _COMMIT_GB, 3)
        committed_gb = round((stat.ullTotalPageFile - stat.ullAvailPageFile) / _COMMIT_GB, 3)
        return {"committed_gb": committed_gb, "limit_gb": limit_gb, "free_gb": free_gb}
    except Exception:
        return None


def _commit_margin_assert(label: str, *, floor_gb: float = COMMIT_MARGIN_FLOOR_GB,
                           reading: dict | None = None) -> dict | None:
    """abort-not-degrade Windows-commit governor (team-lead ruling 2026-07-09,
    v7 death: OSError WinError 1450 inside cpu_offload_adamw._memmap_zeros at
    the FIRST optimizer step, system commit measured 78.93/~81GB two stage
    markers earlier with no check in between -- the checkpoint-load phase's
    ~13.4GB jump, 65.8->79.17GB at POST_CHECKPOINT_LOAD, was the real spike;
    the memmap creation was merely the next allocation attempted after it).
    Same "hold, report numbers, no fix-forward" contract as cpu_offload_adamw.
    vram_preflight's REFUSE_TO_LAUNCH, extended from VRAM to Windows commit --
    checked at every stage/block boundary (via _stage_marker below) and
    immediately before every `.grad.f32` memmap creation (front-load +
    step()'s lazy fallback, see the _memmap_zeros wrap further down).

    `reading` lets a caller that already took a fresh measurement this same
    call (namely _stage_marker) pass it in instead of a second powershell
    round-trip. A FAILED read (reading is None and none supplied) is never
    treated as a violation -- it only prints GOVERNOR_COMMIT_READ_FAILED so a
    silent measurement failure stays visible in the log, consistent with
    _read_commit_gb's own never-raises-on-read-failure contract. A measured
    violation prints GOVERNOR_COMMIT_FAIL with the numbers and raises
    SystemExit -- clean nonzero exit, never a fix-forward, never a widened
    floor. The block loop's checkpoint_every semantics mean the most
    recently COMPLETED block's checkpoint is already on disk whenever this
    fires, so "last checkpoint intact" holds without this function doing
    anything checkpoint-specific itself."""
    r = reading if reading is not None else _read_commit_gb()
    if r is None:
        print(f"GOVERNOR_COMMIT_READ_FAILED label={label}", flush=True)
        return None
    if r["free_gb"] < floor_gb:
        print(f"GOVERNOR_COMMIT_FAIL label={label} committed_gb={r['committed_gb']} "
              f"limit_gb={r['limit_gb']} free_gb={r['free_gb']} floor_gb={floor_gb}",
              flush=True)
        _write_governed_abort_receipt(label, r, floor_gb)
        raise SystemExit(
            f"GOVERNOR_COMMIT_FAIL: free commit {r['free_gb']}GB < floor {floor_gb}GB "
            f"at {label} (committed={r['committed_gb']}GB, limit={r['limit_gb']}GB) -- "
            f"abort-not-degrade, no fix-forward, no widened floor")
    return r


def _write_governed_abort_receipt(label: str, r: dict, floor_gb: float) -> None:
    """Fail-closed receipt for a MEASURED commit-margin violation (ember #627
    comment 4936627594, point 1) -- written BEFORE the caller's SystemExit
    propagates, so a governed abort is never receipt-less. Never raises: a
    receipt-write failure must not mask the real abort it is documenting
    (the SystemExit above still fires unconditionally either way)."""
    receipt = {
        "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1-GOVERNED-ABORT",
        "ts": datetime.now(timezone.utc).isoformat(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "label": label,
        "committed_gb": r["committed_gb"], "limit_gb": r["limit_gb"],
        "free_gb": r["free_gb"], "floor_gb": floor_gb,
        "phase": label,
        "last_checkpoint": _LAST_KNOWN_CHECKPOINT["path"],
        "verdict": "GOVERNOR_COMMIT_FAIL",
        "api_spend_usd": 0, "paid_api_surface_used": False,
    }
    receipt_dir = _RECEIPT_DIR_STATE["path"] or str(REPO / "receipts")
    try:
        Path(receipt_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(receipt_dir) / f"governed-abort-{_ts()}.json"
        checked_write(str(out_path), receipt)
        print(f"GOVERNED_ABORT_RECEIPT_WRITTEN path={out_path}", flush=True)
    except Exception as e:
        print(f"GOVERNED_ABORT_RECEIPT_WRITE_FAILED {type(e).__name__}: {e}", flush=True)


def _stage_marker(label: str) -> None:
    """Flushed stdout stage marker (team-lead ruling 2026-07-09, RUN-death #2:
    silent process death with a truncated, unbuffered-would-have-helped log).
    Cheap host-commit + VRAM read at every phase boundary so a native death
    with no traceback still localizes to one narrow window. Print only --
    never raises on a counter READ failure; a marker failing to read a
    counter must never abort the run it is instrumenting.

    AMENDED 2026-07-09 (v8, commit-margin governor, RUN-death #4/v7 cure):
    also asserts the commit-margin floor via _commit_margin_assert, reusing
    THIS call's own committed_gb reading (no second powershell round-trip).
    This DOES deliberately raise SystemExit on a genuinely MEASURED margin
    violation -- new, intentional behavior (every stage/block boundary is
    now a governed checkpoint, not just a diagnostic print) that does not
    contradict the "never raises" line above, which covers only a failed
    counter READ, still true unchanged."""
    reading = _read_commit_gb()
    committed_gb = reading["committed_gb"] if reading else "?"
    vram = "?"
    try:
        vram = nvidia_smi_vram()["used_gib"]
    except Exception:
        pass
    print(f"STAGE_MARKER {label} ts={datetime.now(timezone.utc).isoformat()} "
          f"committed_gb={committed_gb} vram_used_gib={vram}", flush=True)
    _commit_margin_assert(label, reading=reading)


def _memmap_patched_shard_loader_init(self, shard_dir, seq, n_mtp, *,
                                       mmap_cache_dir=None,
                                       expected_manifest_sha256=None):
    _stage_marker("PRE_SHARD_LOAD")
    if mmap_cache_dir is None:
        mmap_cache_dir = str(REPO / "models" / "cbase-grow-rung" /
                              "rung2-stabilize-leg1" / "shard-memmap-cache")
    _ORIG_PACKED_SHARD_LOADER_INIT(
        self, shard_dir, seq, n_mtp,
        mmap_cache_dir=mmap_cache_dir,
        expected_manifest_sha256=expected_manifest_sha256)
    _stage_marker("POST_SHARD_CACHE")


ts.PackedShardLoader.__init__ = _memmap_patched_shard_loader_init

# ---- stage markers around the remaining RUN-death #2 suspects (team-lead
# ruling 2026-07-09: "one relaunch, ALL of ... stage-marker prints with flush
# at every phase boundary"). Same monkeypatch discipline as the shard-loader
# patch above -- run_v0_segment calls these six names via its own module's
# global namespace (plain unqualified calls), so replacing the name on the
# `ts` module object is picked up transparently by run_v0_segment's internal
# calls with ZERO edits to timeshare_pretrain.py. Reversible: delete this
# block, behavior reverts exactly. Diagnostic-only -- every wrapper is a thin
# pre/post print around the untouched original callable.
for _fname, _pre, _post in [
    ("build_v0_model", "PRE_MODEL_BUILD", "POST_MODEL_BUILD"),
    ("build_split_optimizer", "PRE_OPTIMIZER_INIT", "POST_OPTIMIZER_INIT"),
    ("load_checkpoint", "PRE_CHECKPOINT_LOAD", "POST_CHECKPOINT_LOAD"),
    ("load_optimizers_state", "PRE_LOAD_OPTIMIZERS_STATE", "POST_LOAD_OPTIMIZERS_STATE"),
    ("restore_rng", "PRE_RESTORE_RNG", "POST_RESTORE_RNG"),
]:
    def _make_wrapper(_orig, _pre=_pre, _post=_post):
        def _wrapped(*args, **kwargs):
            _stage_marker(_pre)
            result = _orig(*args, **kwargs)
            _stage_marker(_post)
            return result
        return _wrapped
    setattr(ts, _fname, _make_wrapper(getattr(ts, _fname)))

# model.load_state_dict is a bound method on a freshly-constructed nn.Module
# instance local to run_v0_segment -- not a module-level name, so the class
# method itself is wrapped (process-local, diagnostic-only, reverted by
# deleting this block; every nn.Module in-process gets the same thin print
# wrapper for the duration of this run, behavior unchanged).
import torch as _torch_for_patch  # noqa: E402
_ORIG_LOAD_STATE_DICT = _torch_for_patch.nn.Module.load_state_dict


def _patched_load_state_dict(self, *args, **kwargs):
    _stage_marker("PRE_LOAD_STATE_DICT")
    result = _ORIG_LOAD_STATE_DICT(self, *args, **kwargs)
    _stage_marker("POST_LOAD_STATE_DICT")
    return result


_torch_for_patch.nn.Module.load_state_dict = _patched_load_state_dict

# ---- CPUOffloadOptimizer.load_state_dict: stream, never cast (team-lead
# ruling 2026-07-09, RUN-death #3, killer NAMED with a faulthandler traceback
# from the stage-marker instrumentation above): `Windows fatal exception:
# access violation` inside torch/optim/optimizer.py's
# _process_value_according_to_param_policy `_cast` dictcomp, reached via
# torch.optim.Optimizer.load_state_dict <- cpu_offload_adamw.py:231
# CPUOffloadOptimizer.load_state_dict (`self._inner.load_state_dict(state_dict)`,
# a plain delegate to the wrapped real optimizer -- AdamW OR this repo's own
# _Muon(torch.optim.Optimizer), which does not override load_state_dict
# either, so BOTH optimizer families hit the same cast). Markers: committed_gb
# 90.46 (PRE_CHECKPOINT_LOAD) -> 93.6 (POST_CHECKPOINT_LOAD) -> 93.66
# (PRE_LOAD_OPTIMIZERS_STATE), died mid-cast. torch's cast dictcomp
# materializes a SECOND full copy of the entire optimizer state on top of the
# one already resident from load_checkpoint's torch.load -- exactly defeating
# the memmap-offload design at RESTORE time (the design doc's own words,
# cpu_offload_adamw.py:101-112, describe this exact failure class at OTHER
# call sites; this is that same physics at a THIRD site the redesign never
# reached).
#
# Fix (own-script scope, same discipline as the shard-loader and stage-marker
# patches): override CPUOffloadOptimizer.load_state_dict entirely -- never
# call self._inner.load_state_dict (never touch torch's cast path at all).
# Stream each param's saved per-key tensor directly into the ALREADY-
# ALLOCATED memmap-backed buffer (self._inner.state[shadow_p], built in
# __init__) via an in-place copy_() -- writes land in the memmap's shared
# numpy-backed storage, so they are file-backed pages, never a fresh
# pagefile-committed allocation -- then drop the source reference immediately
# so refcounting frees it as we go (bounded to one tensor at a time, same
# shape as _memmap_from_tensor's existing per-parameter fp32 cast, never the
# whole-state-at-once shape that killed this). Index alignment: bundle["state"]
# is keyed by the flattened param_groups position (torch.optim.Optimizer's own
# convention); self._shadow is built in that exact same order in __init__ and
# passed as the single param group to opt_factory, so shadow index i IS
# state_dict position i (load_optimizers_state's own docstring: "same param
# order... state indices align, so the resume is bit-exact" -- reused here,
# not reinvented). Shape asserted (fail-closed); dtype reconciled with a
# per-tensor .to() only (bounded, not the whole-state cast this replaces).
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
_coa = _ember_af5148f80571f78d_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/cpu_offload_adamw.py  # noqa: E402


def _streamed_cpu_offload_load_state_dict(self, state_dict: dict) -> None:
    import torch

    loaded_state = state_dict.get("state", {}) or {}
    for idx, shadow_p in enumerate(self._shadow):
        if idx not in loaded_state:
            continue  # legitimately-absent tail (Branch-A disclosed reset range) -- leave the zero-seeded memmap as-is
        src = loaded_state[idx]
        dst = self._inner.state.get(shadow_p)
        if dst is None:
            raise RuntimeError(
                f"CPUOffloadOptimizer.load_state_dict: no pre-seeded memmap state "
                f"for shadow idx={idx} ({self._names[idx]}) -- __init__ must run first.")
        for key, dst_tensor in dst.items():
            if key not in src or not torch.is_tensor(dst_tensor):
                continue
            src_tensor = src[key]
            if not torch.is_tensor(src_tensor):
                continue
            if tuple(dst_tensor.shape) != tuple(src_tensor.shape):
                raise RuntimeError(
                    f"CPUOffloadOptimizer.load_state_dict shape mismatch idx={idx} "
                    f"name={self._names[idx]} key={key}: dst={tuple(dst_tensor.shape)} "
                    f"src={tuple(src_tensor.shape)}")
            with torch.no_grad():
                dst_tensor.copy_(src_tensor.detach().to(dst_tensor.dtype))
            src[key] = None  # drop this tensor's reference in the source bundle now
            del src_tensor
        del src
        loaded_state[idx] = None  # drop the per-param dict itself now that every key landed
    if state_dict.get("param_groups"):
        for g_dst, g_src in zip(self._inner.param_groups, state_dict["param_groups"]):
            for k, v in g_src.items():
                if k != "params":
                    g_dst[k] = v


_coa.CPUOffloadOptimizer.load_state_dict = _streamed_cpu_offload_load_state_dict

# ---- commit-margin governor extended to `.grad.f32` memmap creation, PLUS
# front-loading it during optimizer construction (team-lead ruling
# 2026-07-09, v7 death: WinError 1450 inside _memmap_zeros creating the
# FIRST `.grad.f32` shadow-grad file, at the FIRST optimizer step, with
# commit already at 78.93/~81GB from the checkpoint-load phase). Every OTHER
# per-parameter memmap (`.shadow.f32`, `.exp_avg(.sq)?.f32` / `.momentum.f32`)
# is already created eagerly inside __init__ at low commit (~65GB,
# PRE/POST_OPTIMIZER_INIT in the v7 log) -- `.grad.f32` was the ONLY
# lazily-created one, deferred to first touch inside step() (line ~212).
# Two changes, both own-script monkeypatches (same discipline as every other
# patch in this file -- zero edits to cpu_offload_adamw.py, so every OTHER
# caller of CPUOffloadOptimizer, e.g. the probe scripts, is unaffected):
#
#  1. `_memmap_zeros` is wrapped so any call creating a `.grad.f32` path
#     (front-load's own calls below, OR step()'s lazy-create fallback if
#     front-load ever misses a parameter) is preceded by a commit-margin
#     assert. Scoped to `.grad.f32` only -- the exp_avg/exp_avg_sq/momentum/
#     shadow creations are left unwrapped (already proven safe at ~65GB
#     commit in the v7 log; gating all ~550-740 of those calls too would add
#     tens of seconds of powershell round-trips for no safety benefit).
#  2. `CPUOffloadOptimizer.__init__` is wrapped to, immediately after the
#     original constructor finishes (shadow + exp_avg/exp_avg_sq/momentum
#     already seeded), pre-create every parameter's `.grad.f32` memmap and
#     assign it directly onto `shadow_p.grad` -- so step()'s own
#     `if shadow_p.grad is None:` lazy-create branch is skipped entirely in
#     the normal case, and the allocation happens at optimizer-construction
#     time (low commit) instead of first-optimizer-step time (peak commit,
#     right after checkpoint load).
_ORIG_MEMMAP_ZEROS = _coa._memmap_zeros


def _memmap_zeros_governed(path, shape, dtype=None):
    if str(path).endswith(".grad.f32"):
        _commit_margin_assert(f"PRE_MEMMAP_ZEROS_GRAD:{Path(path).stem}")
    return _ORIG_MEMMAP_ZEROS(path, shape, dtype=dtype)


_coa._memmap_zeros = _memmap_zeros_governed

_ORIG_CPU_OFFLOAD_INIT = _coa.CPUOffloadOptimizer.__init__


def _cpu_offload_init_with_frontloaded_grads(self, *args, **kwargs):
    _ORIG_CPU_OFFLOAD_INIT(self, *args, **kwargs)
    n_created = 0
    for name, shadow_p in zip(self._names, self._shadow):
        if shadow_p.grad is not None:
            continue
        stem = self._optstate_dir / _coa._sanitize_name(name)
        shadow_p.grad = _coa._memmap_zeros(Path(str(stem) + ".grad.f32"), tuple(shadow_p.shape))
        n_created += 1
    reading = _read_commit_gb()
    committed_gb = reading["committed_gb"] if reading else "?"
    print(f"STAGE_MARKER PRE_CREATED_OPT_MEMMAPS n={n_created} "
          f"ts={datetime.now(timezone.utc).isoformat()} committed_gb={committed_gb}",
          flush=True)


_coa.CPUOffloadOptimizer.__init__ = _cpu_offload_init_with_frontloaded_grads

# ---- governor VRAM-measurement fix (team-lead ruling 2026-07-09: v5's
# between-block TIMESHARE_GOVERNOR_FAIL hold at block01->block02, "3.52 GiB
# free < 4.0 GiB floor", is CORRECT abort-not-degrade behavior, not a bug --
# the floor does NOT move, never widen a cap. The gap is measurement
# honesty: _apply_governor() (timeshare_pretrain.py:141) reads free VRAM via
# torch.cuda.mem_get_info() -- the real CUDA driver query, not nvidia-smi --
# and torch's own caching allocator retains block01's freed-but-not-returned
# blocks (activations, optimizer-step scratch), so the driver still sees
# them as reserved to this process, undercounting what block02 can actually
# allocate. Fix: torch.cuda.empty_cache() + gc.collect() BEFORE the governor
# reads free VRAM, releasing held-but-unused blocks back to the driver so
# the SAME unchanged 4.0 GiB floor is checked against an honest number. If
# the check still fails after empty_cache, that is a genuine capacity
# verdict -- the wrapped SystemExit propagates unchanged, no retry-loop, no
# floor change. Same monkeypatch discipline as the five functions above:
# run_v0_segment calls `_apply_governor()` via its own module's global
# namespace (unqualified), so replacing the name on the `ts` module object
# is picked up transparently -- zero edits to timeshare_pretrain.py.
_ORIG_APPLY_GOVERNOR = ts._apply_governor


def _governor_with_honest_vram(*args, **kwargs):
    import gc
    import torch
    torch.cuda.empty_cache()
    gc.collect()
    _stage_marker("PRE_GOVERNOR_EMPTY_CACHE_APPLIED")
    return _ORIG_APPLY_GOVERNOR(*args, **kwargs)


ts._apply_governor = _governor_with_honest_vram

# ---- v8 per-step trace file (ember #627 comment 4936662156, point 2, root-
# cause amendment) -------------------------------------------------------
# The run log itself carries the tell: "torch.distributed.elastic.
# multiprocessing.redirects ... NOTE: Redirects are currently not supported
# in Windows or MacOs" -- the worker's stdout (where any per-step print would
# originate) never reliably reaches the parent-process tee on this platform,
# so ANY stdout-based loss trace is structurally unreliable here regardless
# of what the training loop prints. Requirement (b) is upgraded: write a
# structured per-step trace (step, loss, ts) to a JSONL file in the run's
# receipt directory FROM THIS WORKER PROCESS, as each optimizer step's loss
# is finalized -- never relying on stdout, and never waiting for the whole
# block (or the whole run_v0_segment call) to return before anything is
# banked, so even a mid-block crash leaves the steps that DID complete on
# disk.
#
# No duplicated math: run_v0_segment (timeshare_pretrain.py, out of scope --
# shared module, same discipline as every other patch in this file) computes
# the accumulated step loss as sum(micro_losses)/len(micro_losses), one
# mtp_total_loss(...) call per micro-batch, exactly grad_accum_steps calls
# per optimizer step, in order, with NO other call to that name on the RUN
# path (verified: its only other call sites are inside a selftest, never
# reached by run_v0_segment). Wrapping mtp_total_loss and replaying that same
# sum/len arithmetic over its own return values reconstructs the identical
# per-step loss run_v0_segment itself will append to `losses` -- without
# reading run_v0_segment's local variables or editing the shared module.
# _run_block arms the trace (path + grad_accum_steps + starting global step)
# immediately before each ts.run_v0_segment call; when unarmed (path is None,
# e.g. the OTHER call site of _pace_record's sibling functions, or any
# caller that never armed it) this is a pure passthrough, zero behavior
# change.
_ORIG_MTP_TOTAL_LOSS = ts.mtp_total_loss

_STEP_TRACE_STATE: dict = {
    "path": None,              # Path | None -- None means untraced (passthrough)
    "grad_accum_steps": 1,
    "global_step_start": 0,
    "micro_buf": [],           # this in-flight step's micro-batch losses, call order
    "n_steps_written": 0,
}


def _reset_step_trace(path, *, grad_accum_steps: int, global_step_start: int) -> None:
    """Arm (or re-arm, e.g. for the next block) the per-step trace. Truncates
    any pre-existing file at `path` -- each block owns its own trace file
    (segment_id-suffixed), so this only ever starts a fresh file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    _STEP_TRACE_STATE["path"] = path
    _STEP_TRACE_STATE["grad_accum_steps"] = max(1, int(grad_accum_steps))
    _STEP_TRACE_STATE["global_step_start"] = int(global_step_start)
    _STEP_TRACE_STATE["micro_buf"] = []
    _STEP_TRACE_STATE["n_steps_written"] = 0


def _disarm_step_trace() -> None:
    _STEP_TRACE_STATE["path"] = None
    _STEP_TRACE_STATE["micro_buf"] = []


def _mtp_total_loss_traced(primary_ce, mtp_ces, weight):
    micro_loss = _ORIG_MTP_TOTAL_LOSS(primary_ce, mtp_ces, weight)
    path = _STEP_TRACE_STATE["path"]
    if path is not None:
        buf = _STEP_TRACE_STATE["micro_buf"]
        buf.append(float(micro_loss.detach()))
        if len(buf) >= _STEP_TRACE_STATE["grad_accum_steps"]:
            step = _STEP_TRACE_STATE["global_step_start"] + _STEP_TRACE_STATE["n_steps_written"]
            row = {"step": step, "loss": round(sum(buf) / len(buf), 6),
                   "ts": datetime.now(timezone.utc).isoformat()}
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(row) + "\n")
                f.flush()
            _STEP_TRACE_STATE["n_steps_written"] += 1
            _STEP_TRACE_STATE["micro_buf"] = []
    return micro_loss


ts.mtp_total_loss = _mtp_total_loss_traced

# ---- Config C (frozen table, issue #480 LAUNCH SPEC) -----------------------
MICRO_BATCH = 1
MARGIN_GIB_FLOOR = 2.0
LR_MUON = 0.02  # event convention per b1m lr_used; NO eta/sqrt(r_n) correction (P-482 ruling)
N_LAYERS = 20  # true model depth -- unchanged, net2net FF-widening never touches layer count
FF_GROWN = 32768

# ---- superseded historical partition retained for receipt comparison only ---
# (receipts/cbase-grow-rung2-stabilize-transplant-wall-diagnostic-20260709T130000Z.json)
N_LAYERS_VERIFIED_MOMENTUM = 15  # layers 0-14: real pre-grow muon FF momentum, transplant applies
TRUNCATED_PARAM_ID_START = 140   # layer 15's FF + layers 16-19 + tail: zero optimizer state anywhere
TRUNCATED_PARAM_COUNT = 45       # 185 total tensors - 140 = 45; asserted exactly, never approximated

# ---- kill conditions (frozen table) ----------------------------------------
K1_VRAM_PEAK_GIB = 20.5
K2_LOSS_CEILING = 14.359
K2_CONSECUTIVE = 3
K3_S_PER_STEP = 160.0

STEPS_PER_BLOCK_DEFAULT = 10
N_BLOCKS_DEFAULT = 10

# ---- R4 (ember #627 point 4): in-run 27-min pace gate ----------------------
# The first governed block must complete in <=27 min or the block cleanly
# self-aborts (checkpoint + PACE_GATE_ABORT receipt) -- abort-not-degrade, the
# same contract as the commit-margin governor. The v8 death mode was a block
# that never returned; _run_block only computed wall_s AFTER run_v0_segment
# returned, so no in-run gate could ever fire. A watchdog THREAD now arms
# before the block and, on deadline, sets a cooperative abort_event that
# run_v0_segment checks each step -- the block checkpoints its completed steps
# and returns, rather than the process being force-killed mid-step.
PACE_GATE_S = 27 * 60  # 1620 s

# ---- Lineage pin (ember #627 point 7): block-04 step-806 -------------------
# The frozen resume point for this leg is block-04's checkpoint at step-806
# (#480 comment 4929823617: banked blocks 1-4, losses
# 12.436/12.710/12.695/12.136; seed step 766 + 4 blocks x 10 steps = 806). The
# withdrawn prereg SILENTLY rolled the resume point back to block-3 (step 796).
# This leg = blocks 5-10. assert_lineage_resume() below makes the pin
# structural: a resume whose step is not exactly 806 fails closed (unless a
# dated deviation entry is supplied), so a silent rollback can never recur.
LINEAGE_LEG_START_BLOCK = 5
LINEAGE_LEG_END_BLOCK = 10
LINEAGE_RESUME_STEP = 806
LINEAGE_RESUME_BLOCK = 4


class LineageResumeMismatch(RuntimeError):
    """Raised (fail-closed) when a blocks-5-10 resume does not resume from the
    frozen block-04 step-806 checkpoint and no dated deviation is declared."""


_DEVIATION_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _deviation_dated(deviation: str) -> bool:
    """ember #665 audit cure -- a deviation entry only counts as "declared" if
    it starts with a real calendar date (YYYY-MM-DD). `not deviation` alone
    let any non-empty string (x, not-a-date, 2026-99-99 nonsense) through as
    LINEAGE_DEVIATION_DECLARED; this parses the leading date prefix and
    requires it to construct as an actual datetime.date, so an impossible
    date (e.g. month 99) is rejected the same as a missing one."""
    m = _DEVIATION_DATE_PREFIX_RE.match(deviation)
    if not m:
        return False
    try:
        datetime.strptime(m.group(1), "%Y-%m-%d")
    except ValueError:
        return False
    return True


def assert_lineage_resume(resume_step: int, start_block: int,
                          *, deviation: str | None = None) -> dict:
    """ember #627 point 7 -- structural lineage pin. When the RUN loop starts
    at the frozen leg boundary (block 5), the resume checkpoint's own manifest
    step MUST equal LINEAGE_RESUME_STEP (806, the end of block-04). A mismatch
    is either the silent-rollback defect the audit caught (step 796 = block-3)
    or a genuine re-plan; the latter is allowed ONLY with an explicit dated
    `deviation` string (recorded in the receipt), never silently. Returns a
    provenance dict for the receipt; raises LineageResumeMismatch otherwise.

    A start_block other than the frozen leg boundary (e.g. a fresh blocks-1-N
    run, or a mid-leg operator resume) is not lineage-pinned by this function
    -- it only guards the one frozen boundary the audit named."""
    pinned = (start_block == LINEAGE_LEG_START_BLOCK)
    ok = (resume_step == LINEAGE_RESUME_STEP)
    dated = bool(deviation) and _deviation_dated(deviation)
    if pinned and not ok and not deviation:
        raise LineageResumeMismatch(
            f"blocks-{LINEAGE_LEG_START_BLOCK}-{LINEAGE_LEG_END_BLOCK} resume must "
            f"start from the frozen block-{LINEAGE_RESUME_BLOCK:02d} step-{LINEAGE_RESUME_STEP} "
            f"checkpoint, got resume_step={resume_step} (step-796 == block-3, the "
            f"withdrawn prereg's silent rollback). Supply a dated deviation entry to "
            f"resume from a different step. Stopping fail-closed.")
    if pinned and not ok and deviation and not dated:
        raise LineageResumeMismatch(
            f"blocks-{LINEAGE_LEG_START_BLOCK}-{LINEAGE_LEG_END_BLOCK} resume deviation "
            f"entry {deviation!r} does not start with a valid calendar date "
            f"(YYYY-MM-DD); a malformed or impossible date is not a declared "
            f"deviation. Stopping fail-closed.")
    return {
        "lineage_pinned": pinned,
        "expected_resume_step": LINEAGE_RESUME_STEP,
        "expected_resume_block": LINEAGE_RESUME_BLOCK,
        "actual_resume_step": resume_step,
        "leg_blocks": [LINEAGE_LEG_START_BLOCK, LINEAGE_LEG_END_BLOCK],
        "deviation": deviation,
        "verdict": "LINEAGE_OK" if (ok or not pinned) else "LINEAGE_DEVIATION_DECLARED",
    }


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _nvidia_smi_power_watts() -> float | None:
    """power.draw sample, same ground-truth-via-nvidia-smi discipline as
    cpu_offload_adamw.nvidia_smi_vram() (not merged into that function --
    it has a stable, separately-relied-on contract elsewhere; this script's
    own watts need is additive, not a modification)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().splitlines()[0]
        return float(out)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# g1: preflight assert (same fail-closed shape as the B1/Config-C probe)
# ---------------------------------------------------------------------------

def preflight(param_count_after: int) -> dict:
    nvsmi = nvidia_smi_vram()
    required = estimate_required_gib_offloaded(param_count_after, micro_batch=MICRO_BATCH)
    pf = vram_preflight(required["total_estimate_gib"], margin_gib_floor=MARGIN_GIB_FLOOR, nvsmi=nvsmi)
    return {"nvsmi": nvsmi, "required_estimate": required, "preflight": pf,
            "sufficient": bool(pf["sufficient"])}


# ---------------------------------------------------------------------------
# BUILD: Branch-A transplanted resume checkpoint
# ---------------------------------------------------------------------------

class TruncationShapeMismatch(RuntimeError):
    """Raised when the checkpoint's missing-optimizer-state id set does not
    exactly match the enumerated 2026-07-09 truncation (TRUNCATED_PARAM_ID_
    START..end). This hybrid is pinned to THIS incident's exact shape, not a
    general 'skip whatever is missing' tool -- any deviation stops fail-closed
    rather than silently reset a different, unreviewed set of tensors."""


def _enumerate_missing_optimizer_state_ids(m_state: dict, o_state: dict) -> set[int]:
    """Return missing global IDs after checking each optimizer's local IDs."""
    return enumerate_missing_optimizer_state_ids(m_state, o_state)


def _write_transplanted_muon_buffers(
    model_state: dict,
    muon_state: dict,
    post_grow_momentum_state: dict,
) -> list[dict]:
    """Write transplanted buffers into Muon's local on-disk ID space."""
    id_maps = ts.build_optimizer_id_maps(model_state=model_state)
    written = []
    for key, tensor in post_grow_momentum_state.items():
        muon_local_id = id_maps["muon_name_to_id"].get(key)
        if muon_local_id is None:
            raise StagedCheckpointVerificationFailure(
                f"transplanted tensor {key!r} is not Muon-routed")
        entry = muon_state.get(muon_local_id)
        if entry is None:
            raise StagedCheckpointVerificationFailure(
                f"Muon-local optimizer slot {muon_local_id} for {key!r} is missing")
        entry["momentum_buffer"] = tensor
        written.append({"key": key, "muon_local_id": muon_local_id})
    return written


def build_transplanted_resume_checkpoint(seed_ckpt_dir: str, grown_cache_path: str,
                                          out_dir: str, n_layers: int, lr_muon: float) -> dict:
    """Assembles the resume checkpoint this stabilize leg actually needs:
    grown (ff=32768) model weights (already produced + cached, issue #446
    build-once) + a FULL optimizer.pt at the grown shape whose Muon-routed FF
    momentum buffers (gate/up/down_proj x n_layers) are the Branch-A
    transplant (rung_boundary_momentum_transplant.transplant_muon_ff_momentum,
    reused verbatim, UNMODIFIED module) and whose AdamW-routed buffers
    (embed/norm/head/mtp_heads) carry over UNCHANGED from the pre-grow
    optimizer (shape-invariant across net2net FF-widening -- no pushforward
    needed, per that module's own MOMENTUM_PUSHFORWARD_RULE_DECLARED).

    DISCLOSED HYBRID (team-lead ruling, 2026-07-09): `n_layers` here is
    N_LAYERS_VERIFIED_MOMENTUM (15), NOT the model's true depth (20) --
    the shared transplant module is called only over the layers that have
    a real pre-grow momentum buffer, so it fails closed exactly as designed
    for every other caller (its own law, untouched). The genuinely-empty
    tail (TRUNCATED_PARAM_ID_START..184, this checkpoint's own write-time
    truncation) is never passed to the transplant function at all; those
    param ids are simply absent from the resumed optimizer state, which is
    the natural Branch-B behavior (torch optimizers init fresh state for any
    param id with no recorded entry) -- not a code path this function
    invents. Pinned: the missing-id set is asserted to equal EXACTLY the
    enumerated 45-tensor tail before this proceeds; any other shape raises
    TruncationShapeMismatch, fail-closed, same spirit as EngagementFailure.

    Fails closed (EngagementFailure propagates, never caught) on any missing
    or near-zero pre-grow momentum buffer WITHIN the n_layers=15 verified
    range -- the caller decides Branch-B fallback for that range, this
    function never silently substitutes there.
    """
    raise RuntimeError(
        "UNRECEIPTED_TRANSPLANT_BUILD_DISABLED: issue #677 requires "
        "materialize_optimizer_grown_bundle plus verified durable custody; "
        "the historical BUILD path cannot emit or resume an optimizer "
        "transplant"
    )
    import torch

    m_state, o_state, r_state, manifest = ts.load_checkpoint(seed_ckpt_dir)
    # NOTE: grown_cache_path (the grown model weights) is deliberately NOT
    # loaded here. Team-lead ruling 2026-07-09 (ember #457, Windows commit-
    # exhaustion class -- fixed-size pagefile, free-RAM reads ~17GB while
    # commit-available is far lower, reserve-then-commit-on-touch allocations
    # die native/SIGSEGV instead of raising): holding grown_opt_state AND the
    # grown model state simultaneously (what the shared ts.save_checkpoint
    # requires, since both are live arguments for its whole call) exceeded
    # headroom 7/7 times. Staged below: optimizer.pt is built+written+freed
    # FIRST, model.pt is loaded+written+freed SECOND -- at most one of the
    # two big pieces is resident at once. Scope: this function only, the
    # shared save_checkpoint/load_checkpoint stay untouched; output is
    # byte-compatible (same dir layout, filenames, manifest schema) and is
    # round-trip-verified in a fresh subprocess by the caller (main()).

    # -- pin the deviation to THIS incident's exact shape before doing anything --
    missing_ids = _enumerate_missing_optimizer_state_ids(m_state, o_state)
    total_params = len(m_state)
    expected_missing = set(range(TRUNCATED_PARAM_ID_START, total_params))
    if missing_ids != expected_missing:
        raise TruncationShapeMismatch(
            f"missing-optimizer-state id set does not match the enumerated 2026-07-09 "
            f"truncation. expected {len(expected_missing)} ids "
            f"[{TRUNCATED_PARAM_ID_START}..{total_params - 1}], got {len(missing_ids)} ids "
            f"(sample={sorted(missing_ids)[:10]}). This hybrid is pinned to one incident's "
            f"exact shape -- a different gap requires a fresh, reviewed disclosure, not this "
            f"code path. Stopping fail-closed.")

    transplant = transplant_muon_ff_momentum(
        m_state, o_state, n_layers=n_layers, lr_muon=lr_muon, eps_sigma=0.0, eps_seed=0)

    # peak-memory reduction (this function's own scope, no shared-module change):
    # o_state is not read again after this point, so mutate it in place instead of
    # copy.deepcopy(o_state) -- avoids briefly holding two full optimizer-state
    # copies at once. m_state's tensors are likewise unused past param_names
    # (the save below uses grown_sd_bf16, not m_state) -- freed immediately.
    grown_opt_state = o_state
    muon_state = grown_opt_state.get("muon", {}).get("state")
    if muon_state is None:
        muon_state = grown_opt_state.setdefault("state", {})
    written = _write_transplanted_muon_buffers(
        m_state,
        muon_state,
        transplant["post_grow_momentum_state_dict"],
    )
    del m_state

    # drop transplant's own metadata refs to the now-copied tensors + force a
    # collection before the staged save below -- headroom is thin on this
    # host (~17.6GB free); this-function-only mitigation.
    import gc
    n_tensors_transplanted = transplant["n_tensors_transplanted"]
    pre_buffer_rms_consumed = transplant["pre_buffer_rms_consumed"]
    resolved_lr_muon = transplant["resolved_lr_muon"]
    n_layers_transplanted = transplant["n_layers_transplanted"]
    boundary_policy_resolved = transplant["boundary_policy"]
    del transplant
    gc.collect()

    extra = {
        "segment_id": "cbase-grow-rung2-stabilize-transplant",
        "mechanism": "branch_a_partial_hybrid_disclosed_deviation",
        "grown_from_step": manifest["step"],
        "ff_grown": FF_GROWN,
        "boundary_policy": BOUNDARY_POLICY,
        "n_tensors_transplanted": n_tensors_transplanted,
        "pre_buffer_rms_consumed": pre_buffer_rms_consumed,
        "resolved_lr_muon": resolved_lr_muon,
        "disclosed_deviation": {
            "cause": "write-time optimizer.pt truncation predating commit 2445c4b "
                     "(file-backed optimizer state, landed 2026-07-08); checkpoint "
                     "written 2026-07-03",
            "reset_param_id_range": [TRUNCATED_PARAM_ID_START, total_params - 1],
            "reset_param_count": len(missing_ids),
            "transplanted_layers": f"0-{N_LAYERS_VERIFIED_MOMENTUM - 1}",
            "diagnostic_receipt": "receipts/cbase-grow-rung2-stabilize-transplant-wall-"
                                   "diagnostic-20260709T130000Z.json",
        },
    }

    # ---- STAGED SAVE (team-lead ruling 2026-07-09, commit-exhaustion cure) --
    # byte-compatible with timeshare_pretrain.save_checkpoint's on-disk format
    # (same dir layout, filenames, atomic tmp+rename, manifest schema) but
    # writes optimizer.pt FIRST from grown_opt_state (already in memory, built
    # above) and frees it, THEN loads the grown model weights and writes
    # model.pt SECOND, freeing that -- at most one of the two big pieces is
    # resident at once, instead of both for the whole call as the shared
    # save_checkpoint requires. Everything after this point uses only names
    # local to this staging block; grown_opt_state is deleted the moment
    # optimizer.pt is on disk.
    import os
    import shutil

    step = manifest["step"]
    ckpt_dir = os.path.join(out_dir, "checkpoints", f"step-{step:08d}")
    tmp_dir = ckpt_dir + ".tmp"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    op_path = os.path.join(tmp_dir, "optimizer.pt")
    mp_path = os.path.join(tmp_dir, "model.pt")
    rp_path = os.path.join(tmp_dir, "rng.pt")

    torch.save(grown_opt_state, op_path)
    del grown_opt_state
    gc.collect()

    grown_sd_bf16 = torch.load(grown_cache_path, map_location="cpu", weights_only=True, mmap=True)
    torch.save(grown_sd_bf16, mp_path)
    del grown_sd_bf16
    gc.collect()

    torch.save(r_state, rp_path)

    save_manifest = {
        "ticket": "TIMESHARE-CHECKPOINT",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "step": step,
        "sha_convention": SHA_CONVENTION,
        "files": {
            "model.pt": ts._sha256_file(mp_path),
            "optimizer.pt": ts._sha256_file(op_path),
            "rng.pt": ts._sha256_file(rp_path),
        },
        "extra": extra,
    }
    with open(os.path.join(tmp_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(save_manifest, f, sort_keys=True, separators=(",", ": "), indent=2)

    if os.path.exists(ckpt_dir):
        shutil.rmtree(ckpt_dir)
    os.rename(tmp_dir, ckpt_dir)
    new_ckpt_dir = ckpt_dir

    return {
        "checkpoint_dir": new_ckpt_dir,
        "seed_ckpt_dir": seed_ckpt_dir,
        "seed_step": manifest["step"],
        "written_param_ids": written,
        "reset_param_ids": sorted(missing_ids),
        "transplant_meta": {
            "pre_buffer_rms_consumed": pre_buffer_rms_consumed,
            "resolved_lr_muon": resolved_lr_muon,
            "n_layers_transplanted": n_layers_transplanted,
            "n_tensors_transplanted": n_tensors_transplanted,
            "boundary_policy": boundary_policy_resolved,
        },
    }


class StagedCheckpointVerificationFailure(RuntimeError):
    """Raised (fail-closed) when a staged-saved checkpoint does not round-trip
    cleanly: a staged save that can't be re-loaded and re-asserted is a
    corrupt bundle, never a checkpoint to train from."""


def verify_staged_checkpoint(ckpt_dir: str) -> dict:
    """Mandatory post-save integrity check (team-lead ruling 2026-07-09): run
    in a FRESH SUBPROCESS (see main()'s --verify-checkpoint entrypoint below),
    never in the same process that did the staged save -- this both proves
    the on-disk bundle is genuinely byte-compatible with what load_checkpoint
    expects (sha256 verification is inside load_checkpoint itself) and gives
    the check a clean allocation state, independent of whatever the save
    process's memory looked like at the moment it finished.

    Checks: (1) load_checkpoint succeeds (internal sha256 verify); (2) the
    missing-optimizer-state id set is STILL exactly the disclosed 45-tensor
    tail (TRUNCATED_PARAM_ID_START..end) -- confirms the reset stayed a clean
    "absent", not some corrupted/garbage value; (3) a grown-shape spot check
    on a transplanted-range FF tensor (layer 0 gate_proj) confirms the model
    weights are actually at FF_GROWN, not still pre-grow shape.
    """
    m_state, o_state, _r_state, manifest = ts.load_checkpoint(ckpt_dir)

    missing_ids = _enumerate_missing_optimizer_state_ids(m_state, o_state)
    total_params = len(m_state)
    expected_missing = set(range(TRUNCATED_PARAM_ID_START, total_params))
    if missing_ids != expected_missing:
        raise StagedCheckpointVerificationFailure(
            f"post-save missing-id set does not match the disclosed tail: "
            f"expected {sorted(expected_missing)[:5]}..{sorted(expected_missing)[-1]} "
            f"({len(expected_missing)} ids), got {len(missing_ids)} ids "
            f"(sample={sorted(missing_ids)[:10]})")

    gate0_key = "backbone_model.layers.0.mlp.gate_proj.weight"
    if gate0_key not in m_state:
        raise StagedCheckpointVerificationFailure(f"expected key missing from saved model_state: {gate0_key}")
    gate0_shape = tuple(m_state[gate0_key].shape)
    if FF_GROWN not in gate0_shape:
        raise StagedCheckpointVerificationFailure(
            f"grown-shape assertion failed: {gate0_key} shape={gate0_shape}, expected FF_GROWN={FF_GROWN} "
            f"to appear in it -- saved model weights do not look grown.")

    return {
        "verdict": "STAGED_CHECKPOINT_VERIFIED",
        "ckpt_dir": ckpt_dir,
        "step": manifest["step"],
        "missing_ids_count": len(missing_ids),
        "missing_ids_range": [min(missing_ids), max(missing_ids)],
        "gate0_shape": list(gate0_shape),
    }


def materialize_optimizer_grown_bundle(seed_ckpt_dir: str, staged_ckpt_dir: str,
                                        out_dir: str, custody_root: str,
                                        lr_muon: float, cfg: dict) -> dict:
    """Issue #577 cure (team-lead ruling): the staged optimizer.pt at
    staged_ckpt_dir declares mechanism branch_a_partial_hybrid_disclosed_
    deviation but never actually implements it -- run-v4's fail-closed
    assert caught momentum still at pre-grow shape.

    Root cause (this cure's own investigation, reported #577): resolve_
    gate_momentum_buffer / _enumerate_missing_optimizer_state_ids both key
    against the GLOBAL model-state parameter index (list(model_state.
    keys()).index(name)), but this checkpoint's on-disk muon/adamw state
    dicts are keyed by LOCAL split_param_groups ordinal position -- verified
    by constructing the real model and calling split_param_groups directly
    (muon_state has exactly 140 keys 0-139, adamw_state exactly 44 keys
    0-43, matching split_param_groups's counts exactly). The declared
    "missing 45-tensor tail" (TRUNCATED_PARAM_ID_START=140..184) is a
    MECHANICAL ARTIFACT of that index-space mismatch -- it fires for ANY
    split-optimizer checkpoint of this shape, real truncation or not
    (140 == n_muon, 184 == total_params-1, by construction). Direct probe
    of the SOURCE checkpoint's real per-tensor momentum, at the verified
    LOCAL index, shows all 60 FF tensors (all 20 layers, not just 0-14)
    carry real, nonzero, physically sensible momentum (rms smoothly
    decreasing with depth). There is no genuinely-truncated tensor.

    Builds a NEW checkpoint directory: model.pt/rng.pt copied byte-
    identical from staged_ckpt_dir (already verified grown-shape by
    verify_staged_checkpoint's gate0_shape check -- untouched here);
    optimizer.pt freshly materialized, sourced from seed_ckpt_dir via the
    UNMODIFIED rung_boundary_momentum_transplant.transplant_muon_ff_momentum
    (n_layers=20, its own docstring's full "60 = n_layers*3" scope), fed
    directly in the checkpoint's Muon-local convention so the shared,
    already-adjudicated resolver reads the right source tensor per name. Per-
    tensor rule per the #577 ruling: probe source RMS; RMS==0 -> Branch-B
    reset at grown shape; RMS>0 -> Branch-A pushforward -- executed
    uniformly (transplant_muon_ff_momentum's own EngagementFailure fires,
    unhandled, if any of the 60 turns out missing/near-zero after all;
    this function never substitutes silently).

    Neither seed_ckpt_dir nor staged_ckpt_dir is mutated -- both read-only.
    """
    import torch
    import shutil
    import os

    seed_m, seed_o, _seed_r, seed_manifest = ts.load_checkpoint(seed_ckpt_dir)
    staged_m, _staged_o_unused, _staged_r, staged_manifest = ts.load_checkpoint(staged_ckpt_dir)

    # ground-truth LOCAL ordering: build the real (grown) model once, split_param_groups
    model, _vocab, _hidden, _n_mtp = ts.build_v0_model(
        cfg, live=True, device="cpu", intermediate_override=FF_GROWN)
    muon_named, adamw_named = ts.split_param_groups(model)
    muon_local_names = [n for n, _ in muon_named]
    adamw_local_names = [n for n, _ in adamw_named]

    seed_muon_state = seed_o.get("muon", {}).get("state") or {}
    seed_adamw_state = seed_o.get("adamw", {}).get("state") or {}

    if len(seed_muon_state) != len(muon_local_names) or len(seed_adamw_state) != len(adamw_local_names):
        raise RuntimeError(
            f"seed optimizer state size does not match split_param_groups -- refusing to "
            f"proceed with an unverified index assumption: muon {len(seed_muon_state)} vs "
            f"{len(muon_local_names)}, adamw {len(seed_adamw_state)} vs {len(adamw_local_names)}")

    transplant = transplant_muon_ff_momentum(
        seed_m, seed_o, n_layers=20, lr_muon=lr_muon,
        eps_sigma=0.0, eps_seed=0)

    grown_muon_state = dict(seed_muon_state)  # bitwise carry, all 140 local entries as a start
    pushforward_names = list(transplant["post_grow_momentum_state_dict"].keys())
    for name, grown_tensor in transplant["post_grow_momentum_state_dict"].items():
        local_idx = muon_local_names.index(name)
        grown_muon_state[local_idx] = {"momentum_buffer": grown_tensor}

    grown_opt_state = {
        "muon": {"state": grown_muon_state, "param_groups": seed_o["muon"]["param_groups"]},
        "adamw": seed_o["adamw"],  # carried bitwise unchanged -- shape-invariant across the grow
    }

    # Issue #677: RMS remains diagnostic only.  A second independent replay
    # must reproduce every transformed destination tensor before the sidecar
    # can be written or a resume can consume this checkpoint.
    build_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    param_names = {"muon": muon_local_names, "adamw": adamw_local_names}
    transforms = {}
    transform_errors = {}
    replay_tensors = {}
    replay = transplant_muon_ff_momentum(
        seed_m, seed_o, n_layers=20, lr_muon=lr_muon,
        eps_sigma=0.0, eps_seed=0)
    for name, replay_tensor in replay["post_grow_momentum_state_dict"].items():
        local_idx = muon_local_names.index(name)
        mapping_key = f"muon:{name}:momentum_buffer"
        destination_tensor = grown_muon_state[local_idx]["momentum_buffer"]
        transforms[mapping_key] = "momentum-pushforward-v1"
        transform_errors[mapping_key] = float(
            torch.max(torch.abs(
                replay_tensor.to(torch.float64)
                - destination_tensor.to(torch.float64)
            )).item()
        )
        replay_tensors[mapping_key] = replay_tensor
    provenance = build_transplant_provenance(
        source_checkpoint_sha256=checkpoint_bundle_sha256(seed_ckpt_dir),
        transplant_method="branch-a-momentum-pushforward-v1",
        cure_version="issue-577-cure-with-issue-677-binding-v1",
        build_timestamp=build_timestamp,
        source_optimizer_state=seed_o,
        destination_optimizer_state=grown_opt_state,
        param_names=param_names,
        transforms=transforms,
        transform_errors=transform_errors,
        authorized_fresh={},
        dropped={},
        global_step=int(staged_manifest["step"]),
        scheduler_provenance={
            "source": "source-checkpoint-manifest",
            "value": seed_manifest.get("extra", {}).get("scheduler"),
        },
        scaler_provenance={
            "source": "source-checkpoint-manifest",
            "value": seed_manifest.get("extra", {}).get("scaler"),
        },
    )
    provenance = verify_transplant_provenance(
        provenance,
        source_optimizer_state=seed_o,
        destination_optimizer_state=grown_opt_state,
        param_names=param_names,
        replay_tensors=replay_tensors,
    )

    out_ckpt_dir = os.path.join(out_dir, "checkpoints", f"step-{staged_manifest['step']:08d}")
    os.makedirs(out_ckpt_dir, exist_ok=True)

    # model.pt / rng.pt: byte-identical copies of the already-verified-grown staged files.
    shutil.copyfile(os.path.join(staged_ckpt_dir, "model.pt"), os.path.join(out_ckpt_dir, "model.pt"))
    shutil.copyfile(os.path.join(staged_ckpt_dir, "rng.pt"), os.path.join(out_ckpt_dir, "rng.pt"))

    op_path = os.path.join(out_ckpt_dir, "optimizer.pt")
    torch.save(grown_opt_state, op_path)

    # #577's audit copy belongs to the NEW checkpoint, never beside or inside
    # either source checkpoint.  The old path mutated staged_ckpt_dir.
    grown_only_path = os.path.join(out_ckpt_dir, "optimizer-grown.pt")
    try:
        os.link(op_path, grown_only_path)
    except OSError:
        shutil.copyfile(op_path, grown_only_path)

    provenance_name = "transplant-provenance.json"
    provenance_path = os.path.join(out_ckpt_dir, provenance_name)
    write_transplant_provenance_atomic(provenance_path, provenance)
    provenance_file_sha256 = provenance_sha256_file(provenance_path)

    n_pushforward = len(pushforward_names)
    n_carried_muon_non_ff = len(muon_local_names) - n_pushforward
    n_carried_adamw = len(adamw_local_names)

    manifest_out = {
        "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1-OPTIMIZER-CURE",
        "ts": build_timestamp,
        "issue": "wordingone/ember#677",
        "refs": [577, 677],
        "root_cause": (
            "resolve_gate_momentum_buffer / _enumerate_missing_optimizer_state_ids key by "
            "GLOBAL model-state index; this checkpoint's on-disk muon/adamw state is keyed "
            "by LOCAL split_param_groups position. The declared 45-tensor 'truncation' "
            "(TRUNCATED_PARAM_ID_START=140..184) is a mechanical artifact of that mismatch, "
            "not real data loss -- direct probe confirmed all 60 FF tensors (layers 0-19) "
            "hold real nonzero source momentum."
        ),
        "sha_convention": SHA_CONVENTION,
        "files": {
            "model.pt": ts._sha256_file(os.path.join(out_ckpt_dir, "model.pt")),
            "optimizer.pt": ts._sha256_file(op_path),
            "optimizer-grown.pt": ts._sha256_file(grown_only_path),
            "rng.pt": ts._sha256_file(os.path.join(out_ckpt_dir, "rng.pt")),
            provenance_name: provenance_file_sha256,
        },
        "source_checkpoint_sha256": provenance["source_checkpoint_sha256"],
        "source_staged_checkpoint_sha256": checkpoint_bundle_sha256(staged_ckpt_dir),
        "momentum_provenance": {
            "carried_muon_non_ff": n_carried_muon_non_ff,
            "carried_adamw": n_carried_adamw,
            "reset": 0,
            "pushforward": n_pushforward,
        },
        "transplant_provenance_path": provenance_name,
        "transplant_provenance_file_sha256": provenance_file_sha256,
        "transplant_provenance": provenance,
        "transplant_note": (
            "issue #677 verified transplant provenance is inline and in "
            f"{provenance_name}; both are hash-bound by this manifest"
        ),
        "pre_buffer_rms_consumed": transplant["pre_buffer_rms_consumed"],
        "per_tensor_pre_buffer_rms": transplant["per_tensor_pre_buffer_rms"],
        "resolved_lr_muon": transplant["resolved_lr_muon"],
        "n_layers_transplanted": transplant["n_layers_transplanted"],
        "boundary_policy": transplant["boundary_policy"],
        "step": staged_manifest["step"],
    }
    manifest_path = os.path.join(out_ckpt_dir, "manifest.json")
    manifest_fd, manifest_tmp = tempfile.mkstemp(
        dir=out_ckpt_dir, prefix=".manifest.", suffix=".tmp")
    try:
        with os.fdopen(manifest_fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest_out, stream, sort_keys=True, separators=(",", ":"), indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(manifest_tmp, manifest_path)
    finally:
        if os.path.exists(manifest_tmp):
            os.unlink(manifest_tmp)

    custody = publish_checkpoint_to_custody(out_ckpt_dir, custody_root)
    custody_checkpoint_dir = custody["destination_path"]
    custody_manifest = json.loads(
        Path(custody_checkpoint_dir, "manifest.json").read_text(
            encoding="utf-8", errors="strict"))
    loaded_provenance = load_transplant_provenance(
        Path(custody_checkpoint_dir, provenance_name),
        expected_sha256=custody_manifest["transplant_provenance_file_sha256"],
        expected_build_timestamp=custody_manifest["ts"],
    )
    if loaded_provenance != custody_manifest["transplant_provenance"]:
        raise RuntimeError("custody manifest and transplant sidecar disagree")
    custody_optimizer = torch.load(
        Path(custody_checkpoint_dir, "optimizer.pt"), map_location="cpu",
        weights_only=True, mmap=True)
    verify_destination_optimizer_binding(loaded_provenance, custody_optimizer)

    return {
        "checkpoint_dir": custody_checkpoint_dir,
        "transient_checkpoint_dir": out_ckpt_dir,
        "grown_optimizer_audit_copy": str(Path(custody_checkpoint_dir, "optimizer-grown.pt")),
        "manifest": custody_manifest,
        "transplant_provenance": loaded_provenance,
        "custody": custody,
    }


def load_verified_transplant_checkpoint(ckpt_dir: str) -> dict:
    """Archived launcher shim for the reusable #677 consumer."""
    return load_verified_custody_checkpoint(ckpt_dir)


def verify_optimizer_shapes(ckpt_dir: str, cfg: dict) -> dict:
    """#577 ruling item 4 (class extraction, binding on every future grow-
    boundary staging): 'a manifest's declared mechanism must be verified
    against the bundle bytes at STAGE time.' Walks EVERY optimizer-state
    tensor's shape against the live model's expected shape for that
    parameter, at the REAL (split_param_groups-verified) local index -- the
    check the original verify_staged_checkpoint never did (it asserted
    model shapes only, plus the mechanically-meaningless missing-id count).
    Run in a FRESH SUBPROCESS like verify_staged_checkpoint, same reasoning
    (byte-compatibility + clean allocation state)."""
    m_state, o_state, _r, manifest = ts.load_checkpoint(ckpt_dir)

    model, _vocab, _hidden, _n_mtp = ts.build_v0_model(
        cfg, live=True, device="cpu", intermediate_override=FF_GROWN)
    muon_named, adamw_named = ts.split_param_groups(model)
    muon_local_names = [n for n, _ in muon_named]
    adamw_local_names = [n for n, _ in adamw_named]

    muon_state = o_state.get("muon", {}).get("state") or {}
    adamw_state = o_state.get("adamw", {}).get("state") or {}

    mismatches = []
    for local_idx, name in enumerate(muon_local_names):
        expected = tuple(m_state[name].shape)
        entry = muon_state.get(local_idx)
        if entry is None or "momentum_buffer" not in entry:
            mismatches.append({"optimizer": "muon", "local_idx": local_idx, "name": name,
                                "expected": list(expected), "got": None})
            continue
        got = tuple(entry["momentum_buffer"].shape)
        if got != expected:
            mismatches.append({"optimizer": "muon", "local_idx": local_idx, "name": name,
                                "expected": list(expected), "got": list(got)})

    for local_idx, name in enumerate(adamw_local_names):
        expected = tuple(m_state[name].shape)
        entry = adamw_state.get(local_idx)
        if entry is None:
            mismatches.append({"optimizer": "adamw", "local_idx": local_idx, "name": name,
                                "expected": list(expected), "got": None})
            continue
        for key in ("exp_avg", "exp_avg_sq"):
            if key not in entry:
                continue
            got = tuple(entry[key].shape)
            if got != expected:
                mismatches.append({"optimizer": "adamw", "local_idx": local_idx, "name": name,
                                    "key": key, "expected": list(expected), "got": list(got)})

    if mismatches:
        raise StagedCheckpointVerificationFailure(
            f"optimizer-shape verify found {len(mismatches)} mismatch(es) "
            f"(showing up to 10): {mismatches[:10]}")

    return {
        "verdict": "OPTIMIZER_SHAPES_VERIFIED",
        "ckpt_dir": ckpt_dir,
        "n_muon_checked": len(muon_local_names),
        "n_adamw_checked": len(adamw_local_names),
        "step": manifest["step"],
    }


def momentum_norm_by_group(ckpt_dir: str) -> dict:
    """Post-hoc, read-only per-layer-group momentum-norm split -- proves the
    reset tail's warm-up in-run without touching run_v0_segment/timeshare_
    pretrain at all (team-lead rail 3: 'observable in-run, cheap'). Reads the
    just-written block checkpoint's own optimizer.pt."""
    import torch
    m_state, o_state, _r, _manifest = ts.load_checkpoint(ckpt_dir)
    id_maps = ts.build_optimizer_id_maps(model_state=m_state)
    muon_state = o_state.get("muon", {}).get("state") or o_state.get("state", {})
    transplanted_norm_sq, transplanted_n = 0.0, 0
    reset_norm_sq, reset_n = 0.0, 0
    for muon_local_id, st in muon_state.items():
        name = id_maps["muon_id_to_name"].get(muon_local_id)
        if name is None:
            raise StagedCheckpointVerificationFailure(
                f"unknown Muon-local optimizer slot {muon_local_id!r}")
        if not st or "momentum_buffer" not in st or st["momentum_buffer"] is None:
            continue
        n = float(st["momentum_buffer"].float().norm().item())
        global_id = id_maps["global_name_to_id"][name]
        if global_id < TRUNCATED_PARAM_ID_START:
            transplanted_norm_sq += n * n
            transplanted_n += 1
        else:
            reset_norm_sq += n * n
            reset_n += 1
    return {
        "transplanted_group_momentum_norm": round(transplanted_norm_sq ** 0.5, 6),
        "transplanted_group_n_tensors": transplanted_n,
        "reset_group_momentum_norm": round(reset_norm_sq ** 0.5, 6),
        "reset_group_n_tensors": reset_n,
    }


# ---------------------------------------------------------------------------
# RUN: 10-step blocks, per-block receipt, kill-condition asserts
# ---------------------------------------------------------------------------

def _run_block(cfg: dict, run_dir: str, resume_ckpt_dir: str, *, global_step_start: int,
               total_steps: int, shard_dir: str, grad_accum_steps: int, block_idx: int,
               sample_interval_s: float = 2.0,
               pace_gate_s: float | None = None,
               receipt_dir: str | None = None,
               transplant_provenance: dict | None = None) -> tuple[dict, dict]:
    # v8 (ember #627 point 1): the incoming checkpoint is the last known-good
    # one until this block writes its own -- note it now so a governed abort
    # anywhere before run_v0_segment returns (front-load memmap creation, any
    # PRE_* stage marker) can still cite a real checkpoint, not null.
    _note_last_checkpoint(resume_ckpt_dir)

    segment_id = f"cbase-grow-rung2-stabilize-leg1-block{block_idx:02d}"
    if receipt_dir is not None:
        _reset_step_trace(
            Path(receipt_dir) / f"step-trace-{segment_id}.jsonl",
            grad_accum_steps=grad_accum_steps, global_step_start=global_step_start)

    samples: list[dict] = []
    stop_flag = threading.Event()

    def _sampler():
        while not stop_flag.is_set():
            try:
                v = nvidia_smi_vram()
                w = _nvidia_smi_power_watts()
                samples.append({**v, "power_draw_w": w, "t": time.time()})
            except Exception as e:
                samples.append({"error": str(e), "t": time.time()})
            stop_flag.wait(sample_interval_s)

    th = threading.Thread(target=_sampler, daemon=True)
    th.start()

    # ---- R4 in-run pace gate (ember #627 point 4) ----
    # A cooperative abort_event checked each step inside run_v0_segment, driven
    # by a watchdog thread that fires at pace_gate_s. When armed and the block
    # runs past the deadline, the watchdog sets the event; run_v0_segment
    # checkpoints its completed steps and returns with aborted_by_pace_gate=True
    # (abort-not-degrade -- never a force-kill mid-step). The watchdog is
    # cancelled the instant the block returns on its own (block_done set below),
    # so a block that finishes inside the window incurs zero gate effect.
    abort_event = threading.Event()
    block_done = threading.Event()
    pace_gate = {"armed": pace_gate_s is not None, "deadline_s": pace_gate_s, "fired": False}

    def _pace_watchdog():
        if not block_done.wait(pace_gate_s):
            pace_gate["fired"] = True
            print(f"PACE_GATE_ABORT block{block_idx:02d} deadline_s={pace_gate_s} "
                  f"ts={datetime.now(timezone.utc).isoformat()} -- first governed block "
                  f"exceeded the pace gate; signalling clean self-abort (abort-not-degrade)",
                  flush=True)
            abort_event.set()

    pace_th = None
    if pace_gate["armed"]:
        pace_th = threading.Thread(target=_pace_watchdog, daemon=True)
        pace_th.start()

    t0 = time.monotonic()
    requested_run = {
        "source": "cbase_grow_rung2_stabilize:block",
        "total_steps": STEPS_PER_BLOCK_DEFAULT,
        "flops_per_step": 6.0 * 2228265984 * grad_accum_steps * MICRO_BATCH * cfg["model"]["seq"],
    }
    _stage_marker(f"PRE_RUN_V0_SEGMENT_block{block_idx:02d}")
    try:
        receipt = ts.run_v0_segment(
            run_dir, cfg, n_steps=STEPS_PER_BLOCK_DEFAULT, total_steps=total_steps, live=True,
            real_arch=True, device="cuda", resume_ckpt_dir=resume_ckpt_dir,
            shard_dir=shard_dir, checkpoint_every=STEPS_PER_BLOCK_DEFAULT,
            segment_id=segment_id,
            intermediate_override=FF_GROWN, batch_size=MICRO_BATCH,
            grad_accum_steps=grad_accum_steps, offload_optimizer_state=True,
            reset_optimizer_on_resume=False, requested_run=requested_run,
            abort_event=abort_event,
        )
    finally:
        # v8: disarm regardless of outcome -- on a mid-block governed abort
        # (SystemExit) the rows written so far stay on disk exactly as they
        # are; disarming only prevents a stale armed trace from leaking into
        # whatever runs next in this process (matters for a test harness that
        # catches the exception and continues; irrelevant to a real process
        # exit, where nothing runs next).
        _disarm_step_trace()
    block_done.set()  # cancel the pace watchdog -- block returned on its own
    if pace_th is not None:
        pace_th.join(timeout=5)
    _stage_marker(f"POST_RUN_V0_SEGMENT_BLOCK_DONE_block{block_idx:02d}")
    # v8 (ember #627 point 1): this block's own checkpoint is now the last
    # known-good one for any LATER governed abort to cite.
    _note_last_checkpoint(receipt.get("last_checkpoint"))
    wall_s = round(time.monotonic() - t0, 3)
    stop_flag.set()
    th.join(timeout=5)

    valid = [s for s in samples if "error" not in s]
    vram_peak_gib = round(max((s["used_gib"] for s in valid), default=0.0), 4)
    watts_vals = [s["power_draw_w"] for s in valid if s.get("power_draw_w") is not None]
    watts_avg = round(sum(watts_vals) / len(watts_vals), 2) if watts_vals else None
    kwh_block = round((watts_avg * wall_s / 3600.0 / 1000.0), 6) if watts_avg is not None else None
    # #637 review A1: step counts derive from len(losses) -- the number of steps
    # that ACTUALLY completed -- never the requested STEPS_PER_BLOCK_DEFAULT. A
    # zero-step pace-gate abort (watchdog fires during the setup phase: model
    # build + checkpoint load + shard cache, the v7 measured failure mode)
    # returns losses=[]; the block must still produce its COUNTERS line and
    # receipts (loss/pace stats None), never a ZeroDivisionError traceback.
    n_steps_completed = len(receipt["losses"])
    s_per_step = round(wall_s / n_steps_completed, 3) if n_steps_completed else None
    loss_mean = round(sum(receipt["losses"]) / n_steps_completed, 6) if n_steps_completed else None

    # per-layer-group momentum-norm line (team-lead rail 3: reset tail's
    # warm-up observable in-run) -- read-only, off the block's own checkpoint,
    # never touches run_v0_segment/timeshare_pretrain.
    try:
        momentum_split = momentum_norm_by_group(receipt["last_checkpoint"])
    except Exception as e:
        momentum_split = {"error": str(e)}

    # ember #627 point 3: emit observability counters on the SUCCESS path
    # (per-block stage marker line). grad_lazy_creates == 0 in the cured steady
    # state; governor_reads should be small (stage/block boundaries + one-time
    # front-load), NOT ~140/step. Cumulative, so the prereg's prediction is
    # falsifiable by the log rather than vacuously true.
    grad_lazy_creates = _coa.get_counter("grad_lazy_creates")
    governor_reads = get_governor_reads()
    # The receipt is authoritative: run_v0_segment sets aborted_by_pace_gate only
    # if it actually broke on the abort_event at a step boundary. The watchdog's
    # `fired` flag is a secondary signal (deadline elapsed) used only if the
    # receipt omits the field -- this avoids a benign race where a block that
    # returns cleanly at exactly the deadline is mislabelled aborted.
    pace_gate_aborted = bool(receipt.get("aborted_by_pace_gate", pace_gate["fired"]))
    print(f"COUNTERS block{block_idx:02d} grad_lazy_creates={grad_lazy_creates} "
          f"governor_reads={governor_reads} pace_gate_aborted={pace_gate_aborted} "
          f"ts={datetime.now(timezone.utc).isoformat()}", flush=True)

    block_receipt = {
        "block_idx": block_idx,
        "global_step_start": global_step_start,
        "global_step_end": receipt["global_step_end"],
        "n_steps_completed": n_steps_completed,
        "loss_mean": loss_mean,
        "loss_first": receipt["loss_first"],
        "loss_last": receipt["loss_last"],
        "vram_peak_gib": vram_peak_gib,
        "wall_s": wall_s,
        "s_per_step": s_per_step,
        "watts_avg": watts_avg,
        "kwh_this_block": kwh_block,
        "checkpoint": receipt["last_checkpoint"],
        "n_samples": len(valid),
        "momentum_by_group": momentum_split,
        "grad_lazy_creates": grad_lazy_creates,
        "governor_reads": governor_reads,
        "pace_gate": {"armed": pace_gate["armed"], "deadline_s": pace_gate["deadline_s"],
                      "aborted": pace_gate_aborted},
    }
    return block_receipt, receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-ckpt", help="pre-grow (ff=16384) checkpoint dir, real optimizer.pt")
    ap.add_argument("--grown-cache", help="cached grown (ff=32768) bf16 state dict (.pt)")
    ap.add_argument("--shard-dir", help="real packed uint16 corpus shard dir")
    ap.add_argument("--out-dir", default=str(REPO / "models" / "cbase-grow-rung" / "rung2-stabilize-leg1"))
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts"))
    ap.add_argument("--custody-root",
                     help="durable checkpoint root outside the disposable build worktree; "
                          "required for --materialize-optimizer-grown")
    ap.add_argument("--n-blocks", type=int, default=N_BLOCKS_DEFAULT)
    ap.add_argument("--start-block", type=int, default=1,
                     help="issue #480 mid-leg resume (v5 TIMESHARE_GOVERNOR_FAIL hold, block01->"
                          "block02): when >1, skip block_idx 1..start_block-1 entirely and begin "
                          "the RUN loop at this block, reading global_step from "
                          "--resume-ckpt-dir-override's OWN manifest.json (that block's real "
                          "step, e.g. 776) rather than --seed-ckpt's manifest (which would "
                          "wrongly re-seed the original pre-block1 step, e.g. 766). Always "
                          "combined with --resume-ckpt-dir-override pointed at the checkpoint "
                          "of the block immediately before start_block.")
    ap.add_argument("--lineage-deviation", default=None,
                     help="ember #627 point 7: a DATED deviation string authorizing a blocks-5-10 "
                          "resume from a step other than the frozen block-04 step-806 pin (e.g. the "
                          "checkpoint failed verification). Recorded in the receipt; without it a "
                          "non-806 resume at start-block 5 fails closed (never a silent rollback).")
    ap.add_argument("--preflight-only", action="store_true",
                     help="run g1 preflight + BUILD (transplant checkpoint assembly) only, no GPU training")
    ap.add_argument("--verify-checkpoint", metavar="CKPT_DIR",
                     help="FRESH-SUBPROCESS entrypoint (team-lead ruling 2026-07-09): round-trip-verify "
                          "a staged-saved checkpoint dir and exit. Never combined with the other args.")
    ap.add_argument("--verify-optimizer-shapes", metavar="CKPT_DIR",
                     help="FRESH-SUBPROCESS entrypoint (issue #577 ruling item 4): walk optimizer state "
                          "shapes against live model shapes for CKPT_DIR and exit. Never combined with "
                          "the other args.")
    ap.add_argument("--materialize-optimizer-grown", action="store_true",
                     help="issue #577 cure: materialize optimizer-grown.pt (+ new cured checkpoint dir) "
                          "from --seed-ckpt into --staged-ckpt, verify it, print the new checkpoint dir, "
                          "and exit -- no RUN. Requires --seed-ckpt and --staged-ckpt.")
    ap.add_argument("--staged-ckpt", metavar="CKPT_DIR",
                     help="the already-staged (buggy) BUILD checkpoint dir, for --materialize-optimizer-grown")
    ap.add_argument("--resume-ckpt-dir-override", metavar="CKPT_DIR",
                     help="issue #577 cure: skip BUILD (and its verify) entirely and resume-train "
                          "directly from CKPT_DIR (e.g. the --materialize-optimizer-grown output) -- "
                          "go straight to g1 preflight + RUN. Requires --seed-ckpt (for the resume "
                          "manifest/step) and --shard-dir; --grown-cache is not read in this mode.")
    args = ap.parse_args()

    if args.verify_checkpoint:
        try:
            result = verify_staged_checkpoint(args.verify_checkpoint)
            print(f"STAGED_CHECKPOINT_VERIFY_PASS {json.dumps(result)}", flush=True)
            return 0
        except Exception as e:
            print(f"STAGED_CHECKPOINT_VERIFY_FAIL {type(e).__name__}: {e}", flush=True)
            return 4

    if args.verify_optimizer_shapes:
        try:
            cfg = ts.load_contract()
            result = verify_optimizer_shapes(args.verify_optimizer_shapes, cfg)
            print(f"OPTIMIZER_SHAPES_VERIFY_PASS {json.dumps(result)}", flush=True)
            return 0
        except Exception as e:
            print(f"OPTIMIZER_SHAPES_VERIFY_FAIL {type(e).__name__}: {e}", flush=True)
            return 4

    if args.materialize_optimizer_grown:
        if not (args.seed_ckpt and args.staged_ckpt and args.custody_root):
            ap.error("--materialize-optimizer-grown requires --seed-ckpt, --staged-ckpt, and --custody-root")
        cfg = ts.load_contract()
        out_dir = str(Path(args.out_dir) / "transplant-ckpt-cured")
        result = materialize_optimizer_grown_bundle(
            args.seed_ckpt, args.staged_ckpt, out_dir, args.custody_root, LR_MUON, cfg)
        print(f"OPTIMIZER_GROWN_MATERIALIZED checkpoint_dir={result['checkpoint_dir']} "
              f"momentum_provenance={json.dumps(result['manifest']['momentum_provenance'])}",
              flush=True)
        return 0

    if args.resume_ckpt_dir_override:
        if not (args.seed_ckpt and args.shard_dir):
            ap.error("--resume-ckpt-dir-override requires --seed-ckpt and --shard-dir")
    elif not (args.seed_ckpt and args.grown_cache and args.shard_dir):
        ap.error("--seed-ckpt, --grown-cache, and --shard-dir are required unless --verify-checkpoint, "
                 "--verify-optimizer-shapes, --materialize-optimizer-grown, or "
                 "--resume-ckpt-dir-override is used")

    import os
    os.environ["EMBER_GATE_AUTHORIZED"] = "1"

    ts_stamp = _ts()
    receipt_dir = Path(args.receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    _set_abort_receipt_dir(str(receipt_dir))  # v8: governed-abort receipts land here
    cfg = ts.load_contract()
    prod_batch = cfg["throughput"]["batch"] if cfg["throughput"]["batch"] >= 16 else 16
    grad_accum_steps = prod_batch // MICRO_BATCH if prod_batch % MICRO_BATCH == 0 else prod_batch

    import torch

    if args.resume_ckpt_dir_override:
        # issue #577 cure path: BUILD (and its verify) already ran via
        # --materialize-optimizer-grown + --verify-optimizer-shapes; skip
        # straight to g1 preflight + RUN against the cured checkpoint dir.
        verified_transplant = load_verified_transplant_checkpoint(
            args.resume_ckpt_dir_override)
        build = {
            "checkpoint_dir": args.resume_ckpt_dir_override,
            "transplant_meta": verified_transplant,
            "transplant_provenance": verified_transplant["transplant_provenance"],
            "custody": verified_transplant["custody"],
        }
        verify_proc = None
        cured_model_sd = torch.load(
            str(Path(args.resume_ckpt_dir_override) / "model.pt"),
            map_location="cpu", weights_only=True, mmap=True)
        param_count_after = int(sum(v.numel() for v in cured_model_sd.values()))
        cured_model_sd = None
    else:
        # ---- BUILD: transplanted resume checkpoint (Branch A, disclosed partial hybrid) ----
        try:
            build = build_transplanted_resume_checkpoint(
                args.seed_ckpt, args.grown_cache, str(Path(args.out_dir) / "transplant-ckpt"),
                n_layers=N_LAYERS_VERIFIED_MOMENTUM, lr_muon=LR_MUON)
        except EngagementFailure as e:
            refusal = {
                "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1", "ts": datetime.now(timezone.utc).isoformat(),
                "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
                "verdict": "BRANCH_A_ENGAGEMENT_FAILURE", "error": str(e),
                "note": "Branch-A transplant fail-closed WITHIN the n_layers=15 verified range "
                        "(unexpected -- the 2026-07-09 diagnostic found layers 0-14 fully intact). "
                        "NOT auto-falling-back; caller (coordinator) decides.",
            }
            checked_write(str(receipt_dir / f"cbase-grow-rung2-stabilize-leg1-REFUSED-{ts_stamp}.json"), refusal)
            print(f"CBASE_GROW_RUNG2_STABILIZE_BRANCH_A_ENGAGEMENT_FAILURE: {e}")
            return 2
        except TruncationShapeMismatch as e:
            refusal = {
                "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1", "ts": datetime.now(timezone.utc).isoformat(),
                "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
                "verdict": "TRUNCATION_SHAPE_MISMATCH", "error": str(e),
                "note": "the checkpoint's missing-optimizer-state shape no longer matches the "
                        "2026-07-09 enumerated incident -- this hybrid is pinned to that exact "
                        "shape and refuses rather than silently reset a different, unreviewed set.",
            }
            checked_write(str(receipt_dir / f"cbase-grow-rung2-stabilize-leg1-REFUSED-{ts_stamp}.json"), refusal)
            print(f"CBASE_GROW_RUNG2_STABILIZE_TRUNCATION_SHAPE_MISMATCH: {e}")
            return 2

        # ---- mandatory fresh-subprocess round-trip verify (team-lead ruling 2026-07-09) ----
        # a staged save that can't round-trip is a corrupt bundle; running this in a
        # SEPARATE process (not this one) both proves byte-compatibility with the
        # shared load_checkpoint and gives the check a clean allocation state,
        # independent of whatever this process's memory looks like post-save.
        verify_proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--verify-checkpoint", build["checkpoint_dir"]],
            capture_output=True, text=True, timeout=120)
        verify_ok = verify_proc.returncode == 0
        print(f"[{ts_stamp}] staged-checkpoint verify (fresh subprocess): "
              f"returncode={verify_proc.returncode} stdout={verify_proc.stdout.strip()!r} "
              f"stderr_tail={verify_proc.stderr.strip()[-500:]!r}")
        if not verify_ok:
            refusal = {
                "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1", "ts": datetime.now(timezone.utc).isoformat(),
                "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
                "verdict": "STAGED_CHECKPOINT_VERIFY_FAILED",
                "checkpoint_dir": build["checkpoint_dir"],
                "verify_returncode": verify_proc.returncode,
                "verify_stdout": verify_proc.stdout, "verify_stderr": verify_proc.stderr,
                "note": "the staged-saved BUILD checkpoint did not round-trip cleanly in a fresh "
                        "subprocess -- treating it as a corrupt bundle, refusing to proceed to g1/RUN.",
            }
            checked_write(str(receipt_dir / f"cbase-grow-rung2-stabilize-leg1-REFUSED-{ts_stamp}.json"), refusal)
            print(f"CBASE_GROW_RUNG2_STABILIZE_STAGED_CHECKPOINT_VERIFY_FAILED")
            return 2

        grown_sd = torch.load(args.grown_cache, map_location="cpu", weights_only=True, mmap=True)
        param_count_after = int(sum(v.numel() for v in grown_sd.values()))
        grown_sd = None

    # ---- g1: preflight ----
    pf = preflight(param_count_after)
    if not pf["sufficient"]:
        refusal = {
            "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1", "ts": datetime.now(timezone.utc).isoformat(),
            "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
            "verdict": "REFUSE_TO_LAUNCH", "preflight": pf, "attempted": False,
        }
        checked_write(str(receipt_dir / f"cbase-grow-rung2-stabilize-leg1-REFUSED-{ts_stamp}.json"), refusal)
        print(f"CBASE_GROW_RUNG2_STABILIZE_PREFLIGHT_REFUSED preflight={pf}")
        return 2

    print(f"[{ts_stamp}] g1 PASS: preflight={pf['preflight']}")
    print(f"[{ts_stamp}] BUILD done: transplanted checkpoint={build['checkpoint_dir']} "
          f"transplant_meta={build['transplant_meta']}")
    _note_last_checkpoint(build["checkpoint_dir"])  # v8: earliest known-good for a pre-RUN abort

    if args.preflight_only:
        out = {
            "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1-PREFLIGHT", "ts": datetime.now(timezone.utc).isoformat(),
            "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
            "preflight": pf, "build": build, "param_count_after": param_count_after,
            "grad_accum_steps": grad_accum_steps, "micro_batch": MICRO_BATCH,
            "staged_save_verify": ({"returncode": verify_proc.returncode, "stdout": verify_proc.stdout.strip()}
                                    if verify_proc is not None else
                                    {"note": "skipped -- issue #577 cure path, verified separately via "
                                             "--verify-optimizer-shapes before this run"}),
            "verdict": "PREFLIGHT_AND_BUILD_ONLY_PASS",
        }
        checked_write(str(receipt_dir / f"cbase-grow-rung2-stabilize-leg1-preflight-{ts_stamp}.json"), out)
        print(f"CBASE_GROW_RUNG2_STABILIZE_PREFLIGHT_ONLY_DONE receipt written")
        return 0

    # ---- RUN: n_blocks x 10-step blocks ----
    resume_ckpt_dir = build["checkpoint_dir"]
    manifest = json.loads((Path(args.seed_ckpt) / "manifest.json").read_text(encoding="utf-8"))
    total_steps = manifest.get("extra", {}).get("total_steps") or \
        (cfg["data"]["token_budget"]["compute_optimal"] // (prod_batch * cfg["model"]["seq"]))
    if args.start_block > 1:
        # Mid-leg resume: global_step must come from the block we are actually
        # resuming FROM (resume_ckpt_dir's own manifest), never from the
        # original seed's manifest -- the seed's step (766) predates block 1
        # entirely and would silently rewind the step counter.
        resume_manifest = json.loads((Path(resume_ckpt_dir) / "manifest.json").read_text(encoding="utf-8"))
        global_step = resume_manifest["step"]
    else:
        global_step = manifest["step"]

    # ---- lineage pin (ember #627 point 7): block-04 step-806 ----
    # Fail closed if a blocks-5-10 resume does not resume from the frozen
    # block-04 step-806 checkpoint (the silent-rollback-to-block-3 defect the
    # audit caught), unless a dated deviation entry is declared.
    try:
        lineage = assert_lineage_resume(global_step, args.start_block,
                                        deviation=args.lineage_deviation)
    except LineageResumeMismatch as e:
        refusal = {
            "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1", "ts": datetime.now(timezone.utc).isoformat(),
            "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
            "verdict": "LINEAGE_RESUME_MISMATCH", "error": str(e),
            "resume_ckpt_dir": resume_ckpt_dir, "resume_step": global_step,
            "start_block": args.start_block,
            "note": "resume point is not the frozen block-04 step-806 lineage pin and no dated "
                    "deviation was declared -- refusing to launch on a silently-rolled-back lineage.",
        }
        checked_write(str(receipt_dir / f"cbase-grow-rung2-stabilize-leg1-REFUSED-{ts_stamp}.json"), refusal)
        print(f"CBASE_GROW_RUNG2_STABILIZE_LINEAGE_RESUME_MISMATCH: {e}")
        return 2
    print(f"[{ts_stamp}] lineage pin: {json.dumps(lineage)}")

    block_receipts: list[dict] = []
    kwh_running = 0.0
    verdict = "MEASURED_PASS"
    abort_reason = None
    for block_idx in range(args.start_block, args.n_blocks + 1):
        run_dir = str(Path(args.out_dir) / f"block-{block_idx:02d}")
        # R4: arm the 27-min pace gate on the FIRST governed block of this leg only.
        pace_gate_s = PACE_GATE_S if block_idx == args.start_block else None
        block_receipt, raw_receipt = _run_block(
            cfg, run_dir, resume_ckpt_dir, global_step_start=global_step,
            total_steps=total_steps, shard_dir=args.shard_dir,
            grad_accum_steps=grad_accum_steps, block_idx=block_idx,
            pace_gate_s=pace_gate_s, receipt_dir=receipt_dir,
            transplant_provenance=build.get("transplant_provenance"))
        kwh_running += (block_receipt["kwh_this_block"] or 0.0)
        block_receipt["kwh_running_total"] = round(kwh_running, 6)
        block_receipt["transplant_provenance"] = build.get("transplant_provenance")
        block_receipts.append(block_receipt)
        print(f"BLOCK {block_idx}/{args.n_blocks} step={block_receipt['global_step_end']} "
              f"loss_mean={block_receipt['loss_mean']} vram_peak_gib={block_receipt['vram_peak_gib']} "
              f"s_per_step={block_receipt['s_per_step']} watts_avg={block_receipt['watts_avg']} "
              f"kwh_running={block_receipt['kwh_running_total']}", flush=True)

        # -- R4 pace gate: a clean self-abort is abort-not-degrade -- stop the
        # leg, the block's completed-step checkpoint is already on disk.
        if block_receipt["pace_gate"]["aborted"]:
            verdict, abort_reason = "ABORTED", (
                f"r4_pace_gate (first governed block exceeded {PACE_GATE_S}s / "
                f"{PACE_GATE_S // 60} min -- clean self-abort at "
                f"step={block_receipt['global_step_end']})")
            break

        # -- kill conditions (checked AFTER a clean block; its own checkpoint
        # already exists via run_v0_segment's checkpoint_every=STEPS_PER_BLOCK --
        if block_receipt["vram_peak_gib"] > K1_VRAM_PEAK_GIB:
            verdict, abort_reason = "ABORTED", f"k1_vram_peak_exceeded ({block_receipt['vram_peak_gib']} > {K1_VRAM_PEAK_GIB})"
            break
        last_losses = [b["loss_mean"] for b in block_receipts[-K2_CONSECUTIVE:]]
        if len(last_losses) >= K2_CONSECUTIVE and all(v > K2_LOSS_CEILING for v in last_losses):
            verdict, abort_reason = "ABORTED", f"k2_divergence (last {K2_CONSECUTIVE} block losses > {K2_LOSS_CEILING}: {last_losses})"
            break
        if block_receipt["s_per_step"] > K3_S_PER_STEP:
            verdict, abort_reason = "ABORTED", f"k3_offload_thrash ({block_receipt['s_per_step']} > {K3_S_PER_STEP} s/step)"
            break

        resume_ckpt_dir = block_receipt["checkpoint"]
        global_step = block_receipt["global_step_end"]

    final = {
        "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1",
        "ts": datetime.now(timezone.utc).isoformat(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 480, "refs": [452, 449, 482, 513, 524, 118],
        "config": {"micro_batch": MICRO_BATCH, "grad_accum_steps": grad_accum_steps,
                   "effective_batch": MICRO_BATCH * grad_accum_steps, "ff_grown": FF_GROWN,
                   "n_layers": N_LAYERS, "lr_muon": LR_MUON},
        "preflight": pf,
        "build": build,
        # #637 review A2: an aborted block contributes the steps it ACTUALLY
        # completed (len(losses), carried as n_steps_completed), never a flat
        # 10 -- the relaunch decision reads this receipt.
        "steps_completed": sum(b["n_steps_completed"] for b in block_receipts),
        "steps_requested": args.n_blocks * STEPS_PER_BLOCK_DEFAULT,
        "block_receipts": block_receipts,
        "kwh_total": round(kwh_running, 6),
        "step_100_loss_preregistered_expectation": "< 13.30 (continuing 14.359 -> 13.625)",
        "verdict": verdict,
        "abort_reason": abort_reason,
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
    }
    out_path = receipt_dir / f"cbase-grow-rung2-stabilize-leg1-{ts_stamp}.json"
    checked_write(str(out_path), final)
    print(f"CBASE_GROW_RUNG2_STABILIZE_LEG1_{verdict} receipt={out_path} "
          f"steps_completed={final['steps_completed']} kwh_total={final['kwh_total']}", flush=True)
    return 0 if verdict == "MEASURED_PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
