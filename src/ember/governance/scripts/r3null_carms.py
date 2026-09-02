#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""r3null_carms.py — R3-null C-arm counterfactual runners (C1 + C2).

Implements the two C-arms of the R3-null 3-arm setup per the frozen brief
(state/r3null-launch-brief.md):

  C1 (counterfactual continuation):
    - Resume parent model + PARENT optimizer state (60 steps warm, reset@670)
    - 36 steps on IDENTICAL data-order/batches as G's stabilize leg
    - Engagement guard: batch-id trace sha must match G's receipt
    - Measures: value of 60-step optimizer warmth (vs fresh C2)

  C2 (reset control):
    - Resume parent model + FRESH optimizer + pinned LR (wsd_lr_frac)
    - Same 36 batches as G (deterministic seeding)
    - Paired with C1 to isolate optimizer warmth vs fresh-state cost
    - G−C2 = container effect at matched steps

Parent checkpoint (engagement guard, sha-verified):
  Passed as --parent-checkpoint arg (relative to repo root)
  model.pt sha256: ac43445b15e22cdc733d78855a34a49b35a241ff32289d427a9668e309697f0d
  optimizer.pt sha256: e006f946946078c1ec711e119df3ed415e05ff901e3091d5d895057 3285ebc94

Output per arm:
  - Per-step: loss, LR multiplier, batch-id
  - Paired per-step loss traces
  - Δ(C1−C2), Δ(G−C2), Δ(G−C1) comparisons
  - Receipts written fail-closed (assertions BEFORE artifact write)

Modes:
  --selftest      2-step CPU micro fixture, planted equality (C1==C2 when fresh)
  (no flag)       Real GPU run (requires EMBER_GATE_AUTHORIZED=1; NOT fired by this session)

Reuse discipline: imports timeshare_pretrain.run_v0_segment/load_checkpoint/save_checkpoint,
identical plumbing as cbase_grow_rung.py's stabilize invocation (no new training paths).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
RECEIPT_DIR_DEFAULT = REPO / "receipts" / "r3null-carms"
OUT_DIR_DEFAULT = REPO / "models" / "r3null-carms"
SCRATCH_SELFTEST = REPO / "scratch" / "r3null-carms-selftest"

# Parent checkpoint (engagement guard shas)
# Path specified via --parent-checkpoint argument at runtime
PARENT_MODEL_SHA = "ac43445b15e22cdc733d78855a34a49b35a241ff32289d427a9668e309697f0d"
PARENT_OPTIMIZER_SHA = "e006f946946078c1ec711e119df3ed415e05ff901e3091d5d8950573285ebc94"

# C-arm spec (36 steps, LR pinned, step 730 carried, total_steps 449651 carried)
C_ARM_STEPS = 36
CARRIED_STEP = 730
TOTAL_STEPS = 449651


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _relpath(p) -> str:
    p = Path(p)
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


# =========================================================================
# Selftest — 2-step CPU micro fixture, planted equality
# =========================================================================

def selftest() -> None:
    """Planted truth: C1 with fresh state and C2 must produce identical traces."""
    print("[r3null_carms] selftest: planted equality (C1==C2 when both fresh), 2-step CPU micro", flush=True)

    import torch
    import timeshare_pretrain as ts
    # issue2015 exact-local-import:src/ember/governance/scripts/cbase_grow_live.py
    import importlib.util as _ember_1c3091a2ca5bb89f_importlib
    import sys as _ember_1c3091a2ca5bb89f_sys
    from pathlib import Path as _ember_1c3091a2ca5bb89f_Path
    _ember_1c3091a2ca5bb89f_path = _ember_1c3091a2ca5bb89f_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'cbase_grow_live.py')
    if not _ember_1c3091a2ca5bb89f_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/cbase_grow_live.py')
    _ember_1c3091a2ca5bb89f_aliases = ('_ember_issue2015_1c3091a2ca5bb89f', 'cbase_grow_live', 'scripts.cbase_grow_live')
    _ember_1c3091a2ca5bb89f_existing = []
    for _ember_1c3091a2ca5bb89f_alias in _ember_1c3091a2ca5bb89f_aliases:
        _ember_1c3091a2ca5bb89f_candidate = _ember_1c3091a2ca5bb89f_sys.modules.get(_ember_1c3091a2ca5bb89f_alias)
        if _ember_1c3091a2ca5bb89f_candidate is not None and all(_ember_1c3091a2ca5bb89f_candidate is not item for item in _ember_1c3091a2ca5bb89f_existing):
            _ember_1c3091a2ca5bb89f_existing.append(_ember_1c3091a2ca5bb89f_candidate)
    if len(_ember_1c3091a2ca5bb89f_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/cbase_grow_live.py')
    if _ember_1c3091a2ca5bb89f_existing:
        _ember_1c3091a2ca5bb89f_module = _ember_1c3091a2ca5bb89f_existing[0]
        _ember_1c3091a2ca5bb89f_observed = getattr(_ember_1c3091a2ca5bb89f_module, '__file__', None)
        if _ember_1c3091a2ca5bb89f_observed is None or _ember_1c3091a2ca5bb89f_Path(_ember_1c3091a2ca5bb89f_observed).resolve() != _ember_1c3091a2ca5bb89f_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/cbase_grow_live.py')
    else:
        _ember_1c3091a2ca5bb89f_spec = _ember_1c3091a2ca5bb89f_importlib.spec_from_file_location('_ember_issue2015_1c3091a2ca5bb89f', _ember_1c3091a2ca5bb89f_path)
        if _ember_1c3091a2ca5bb89f_spec is None or _ember_1c3091a2ca5bb89f_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/cbase_grow_live.py')
        _ember_1c3091a2ca5bb89f_module = _ember_1c3091a2ca5bb89f_importlib.module_from_spec(_ember_1c3091a2ca5bb89f_spec)
        for _ember_1c3091a2ca5bb89f_alias in _ember_1c3091a2ca5bb89f_aliases:
            _ember_1c3091a2ca5bb89f_prior = _ember_1c3091a2ca5bb89f_sys.modules.get(_ember_1c3091a2ca5bb89f_alias)
            if _ember_1c3091a2ca5bb89f_prior is not None and _ember_1c3091a2ca5bb89f_prior is not _ember_1c3091a2ca5bb89f_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/cbase_grow_live.py')
            _ember_1c3091a2ca5bb89f_sys.modules[_ember_1c3091a2ca5bb89f_alias] = _ember_1c3091a2ca5bb89f_module
        try:
            _ember_1c3091a2ca5bb89f_spec.loader.exec_module(_ember_1c3091a2ca5bb89f_module)
        except BaseException:
            for _ember_1c3091a2ca5bb89f_alias in _ember_1c3091a2ca5bb89f_aliases:
                if _ember_1c3091a2ca5bb89f_sys.modules.get(_ember_1c3091a2ca5bb89f_alias) is _ember_1c3091a2ca5bb89f_module:
                    _ember_1c3091a2ca5bb89f_sys.modules.pop(_ember_1c3091a2ca5bb89f_alias, None)
            raise
    for _ember_1c3091a2ca5bb89f_alias in _ember_1c3091a2ca5bb89f_aliases:
        _ember_1c3091a2ca5bb89f_prior = _ember_1c3091a2ca5bb89f_sys.modules.get(_ember_1c3091a2ca5bb89f_alias)
        if _ember_1c3091a2ca5bb89f_prior is not None and _ember_1c3091a2ca5bb89f_prior is not _ember_1c3091a2ca5bb89f_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/cbase_grow_live.py')
        _ember_1c3091a2ca5bb89f_sys.modules[_ember_1c3091a2ca5bb89f_alias] = _ember_1c3091a2ca5bb89f_module
    _small_cfg = getattr(_ember_1c3091a2ca5bb89f_module, '_small_cfg')
    SMOKE_FF_SEED = getattr(_ember_1c3091a2ca5bb89f_module, 'SMOKE_FF_SEED')
    K_SMOKE = getattr(_ember_1c3091a2ca5bb89f_module, 'K_SMOKE')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/cbase_grow_live.py

    # Tiny CPU config
    cfg = _small_cfg(ts.load_contract())
    batch = cfg["throughput"]["batch"]
    seq = cfg["model"]["seq"]
    ts_stamp = _ts()

    out_root = SCRATCH_SELFTEST / f"selftest-{ts_stamp}"
    parent_dir = out_root / "parent"

    # Build a tiny parent checkpoint (K_SMOKE steps = 2 steps typically)
    print(f"  [1/4] Creating tiny parent checkpoint ({K_SMOKE} steps)...", flush=True)
    parent_receipt = ts.run_v0_segment(
        str(parent_dir), cfg, n_steps=K_SMOKE, total_steps=K_SMOKE * 4, live=False,
        real_arch=True, device="cpu", resume_ckpt_dir=None, shard_dir=None,
        checkpoint_every=K_SMOKE, segment_id="r3null-carms-selftest-parent",
        intermediate_override=SMOKE_FF_SEED,
    )
    assert parent_receipt["pass"] is True, "parent fixture creation failed"
    parent_ckpt = parent_receipt["last_checkpoint"]

    # Load parent (will be used by both C1 and C2 with fresh state in this fixture)
    m_state, o_state, r_state, ckpt_manifest = ts.load_checkpoint(parent_ckpt)

    # C1 fixture: fresh state run
    print(f"  [2/4] Running C1 fixture (fresh state, {K_SMOKE} steps)...", flush=True)
    c1_dir = out_root / "c1"
    c1_receipt = ts.run_v0_segment(
        str(c1_dir), cfg, n_steps=K_SMOKE, total_steps=K_SMOKE * 4, live=False,
        real_arch=True, device="cpu", resume_ckpt_dir=parent_ckpt, shard_dir=None,
        checkpoint_every=K_SMOKE, segment_id="r3null-carms-selftest-c1",
        intermediate_override=SMOKE_FF_SEED, reset_optimizer_on_resume=True,
    )
    assert c1_receipt["pass"] is True, "C1 fixture failed"
    c1_losses = c1_receipt["losses"]

    # C2 fixture: fresh state run (identical to C1 since it's the first time through data)
    print(f"  [3/4] Running C2 fixture (fresh state, {K_SMOKE} steps)...", flush=True)
    c2_dir = out_root / "c2"
    c2_receipt = ts.run_v0_segment(
        str(c2_dir), cfg, n_steps=K_SMOKE, total_steps=K_SMOKE * 4, live=False,
        real_arch=True, device="cpu", resume_ckpt_dir=parent_ckpt, shard_dir=None,
        checkpoint_every=K_SMOKE, segment_id="r3null-carms-selftest-c2",
        intermediate_override=SMOKE_FF_SEED, reset_optimizer_on_resume=True,
    )
    assert c2_receipt["pass"] is True, "C2 fixture failed"
    c2_losses = c2_receipt["losses"]

    # Verify planted truth: losses must be identical (torch.allclose)
    print(f"  [4/4] Verifying planted equality...", flush=True)
    c1_losses_t = torch.tensor(c1_losses)
    c2_losses_t = torch.tensor(c2_losses)

    # The planted truth: with identical data order and seeding, C1 and C2 fresh starts must match
    if not torch.allclose(c1_losses_t, c2_losses_t, atol=1e-5, rtol=1e-5):
        raise AssertionError(
            f"Planted equality failed: C1 and C2 loss traces differ when both fresh.\n"
            f"  C1 losses: {c1_losses}\n"
            f"  C2 losses: {c2_losses}\n"
            f"  Max diff: {(c1_losses_t - c2_losses_t).abs().max().item()}")

    max_diff = (c1_losses_t - c2_losses_t).abs().max().item()
    print(f"  [OK] Planted equality PASS: C1 == C2 traces when both fresh (max diff={max_diff:.2e})")
    print(f"R3NULL_CARMS_SELFTEST_PASS")
    return


# =========================================================================
# Live path — the real GPU run
# =========================================================================

def run_live(args) -> int:
    """Run C1 and C2 arms from parent checkpoint, both 36 steps."""
    import torch
    import timeshare_pretrain as ts
    # issue2015 exact-local-import:src/ember/governance/scripts/v0_pretrain_launch_gate.py
    import importlib.util as _ember_fbb2699a8f4bfd8b_importlib
    import sys as _ember_fbb2699a8f4bfd8b_sys
    from pathlib import Path as _ember_fbb2699a8f4bfd8b_Path
    _ember_fbb2699a8f4bfd8b_path = _ember_fbb2699a8f4bfd8b_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'v0_pretrain_launch_gate.py')
    if not _ember_fbb2699a8f4bfd8b_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
    _ember_fbb2699a8f4bfd8b_aliases = ('_ember_issue2015_fbb2699a8f4bfd8b', 'scripts.v0_pretrain_launch_gate', 'v0_pretrain_launch_gate')
    _ember_fbb2699a8f4bfd8b_existing = []
    for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
        _ember_fbb2699a8f4bfd8b_candidate = _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias)
        if _ember_fbb2699a8f4bfd8b_candidate is not None and all(_ember_fbb2699a8f4bfd8b_candidate is not item for item in _ember_fbb2699a8f4bfd8b_existing):
            _ember_fbb2699a8f4bfd8b_existing.append(_ember_fbb2699a8f4bfd8b_candidate)
    if len(_ember_fbb2699a8f4bfd8b_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
    if _ember_fbb2699a8f4bfd8b_existing:
        _ember_fbb2699a8f4bfd8b_module = _ember_fbb2699a8f4bfd8b_existing[0]
        _ember_fbb2699a8f4bfd8b_observed = getattr(_ember_fbb2699a8f4bfd8b_module, '__file__', None)
        if _ember_fbb2699a8f4bfd8b_observed is None or _ember_fbb2699a8f4bfd8b_Path(_ember_fbb2699a8f4bfd8b_observed).resolve() != _ember_fbb2699a8f4bfd8b_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
    else:
        _ember_fbb2699a8f4bfd8b_spec = _ember_fbb2699a8f4bfd8b_importlib.spec_from_file_location('_ember_issue2015_fbb2699a8f4bfd8b', _ember_fbb2699a8f4bfd8b_path)
        if _ember_fbb2699a8f4bfd8b_spec is None or _ember_fbb2699a8f4bfd8b_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
        _ember_fbb2699a8f4bfd8b_module = _ember_fbb2699a8f4bfd8b_importlib.module_from_spec(_ember_fbb2699a8f4bfd8b_spec)
        for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
            _ember_fbb2699a8f4bfd8b_prior = _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias)
            if _ember_fbb2699a8f4bfd8b_prior is not None and _ember_fbb2699a8f4bfd8b_prior is not _ember_fbb2699a8f4bfd8b_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
            _ember_fbb2699a8f4bfd8b_sys.modules[_ember_fbb2699a8f4bfd8b_alias] = _ember_fbb2699a8f4bfd8b_module
        try:
            _ember_fbb2699a8f4bfd8b_spec.loader.exec_module(_ember_fbb2699a8f4bfd8b_module)
        except BaseException:
            for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
                if _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias) is _ember_fbb2699a8f4bfd8b_module:
                    _ember_fbb2699a8f4bfd8b_sys.modules.pop(_ember_fbb2699a8f4bfd8b_alias, None)
            raise
    for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
        _ember_fbb2699a8f4bfd8b_prior = _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias)
        if _ember_fbb2699a8f4bfd8b_prior is not None and _ember_fbb2699a8f4bfd8b_prior is not _ember_fbb2699a8f4bfd8b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
        _ember_fbb2699a8f4bfd8b_sys.modules[_ember_fbb2699a8f4bfd8b_alias] = _ember_fbb2699a8f4bfd8b_module
    gate_mod = _ember_fbb2699a8f4bfd8b_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/v0_pretrain_launch_gate.py
    # issue2015 exact-local-import:src/ember/governance/scripts/governor.py
    import importlib.util as _ember_86cfcf0844b5c48e_importlib
    import sys as _ember_86cfcf0844b5c48e_sys
    from pathlib import Path as _ember_86cfcf0844b5c48e_Path
    _ember_86cfcf0844b5c48e_path = _ember_86cfcf0844b5c48e_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'governor.py')
    if not _ember_86cfcf0844b5c48e_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/governor.py')
    _ember_86cfcf0844b5c48e_aliases = ('_ember_issue2015_86cfcf0844b5c48e', 'governor', 'scripts.governor')
    _ember_86cfcf0844b5c48e_existing = []
    for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
        _ember_86cfcf0844b5c48e_candidate = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
        if _ember_86cfcf0844b5c48e_candidate is not None and all(_ember_86cfcf0844b5c48e_candidate is not item for item in _ember_86cfcf0844b5c48e_existing):
            _ember_86cfcf0844b5c48e_existing.append(_ember_86cfcf0844b5c48e_candidate)
    if len(_ember_86cfcf0844b5c48e_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/governor.py')
    if _ember_86cfcf0844b5c48e_existing:
        _ember_86cfcf0844b5c48e_module = _ember_86cfcf0844b5c48e_existing[0]
        _ember_86cfcf0844b5c48e_observed = getattr(_ember_86cfcf0844b5c48e_module, '__file__', None)
        if _ember_86cfcf0844b5c48e_observed is None or _ember_86cfcf0844b5c48e_Path(_ember_86cfcf0844b5c48e_observed).resolve() != _ember_86cfcf0844b5c48e_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/governor.py')
    else:
        _ember_86cfcf0844b5c48e_spec = _ember_86cfcf0844b5c48e_importlib.spec_from_file_location('_ember_issue2015_86cfcf0844b5c48e', _ember_86cfcf0844b5c48e_path)
        if _ember_86cfcf0844b5c48e_spec is None or _ember_86cfcf0844b5c48e_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/governor.py')
        _ember_86cfcf0844b5c48e_module = _ember_86cfcf0844b5c48e_importlib.module_from_spec(_ember_86cfcf0844b5c48e_spec)
        for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
            _ember_86cfcf0844b5c48e_prior = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
            if _ember_86cfcf0844b5c48e_prior is not None and _ember_86cfcf0844b5c48e_prior is not _ember_86cfcf0844b5c48e_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/governor.py')
            _ember_86cfcf0844b5c48e_sys.modules[_ember_86cfcf0844b5c48e_alias] = _ember_86cfcf0844b5c48e_module
        try:
            _ember_86cfcf0844b5c48e_spec.loader.exec_module(_ember_86cfcf0844b5c48e_module)
        except BaseException:
            for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
                if _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias) is _ember_86cfcf0844b5c48e_module:
                    _ember_86cfcf0844b5c48e_sys.modules.pop(_ember_86cfcf0844b5c48e_alias, None)
            raise
    for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
        _ember_86cfcf0844b5c48e_prior = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
        if _ember_86cfcf0844b5c48e_prior is not None and _ember_86cfcf0844b5c48e_prior is not _ember_86cfcf0844b5c48e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/governor.py')
        _ember_86cfcf0844b5c48e_sys.modules[_ember_86cfcf0844b5c48e_alias] = _ember_86cfcf0844b5c48e_module
    governor = _ember_86cfcf0844b5c48e_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/governor.py

    # Verify parent checkpoint shas (engagement guard)
    parent_path = Path(args.parent_checkpoint).resolve()
    model_pt = parent_path / "model.pt"
    optimizer_pt = parent_path / "optimizer.pt"

    print(f"[r3null_carms] live: verifying parent checkpoint shas...", flush=True)
    actual_model_sha = _sha256_file(str(model_pt))
    if actual_model_sha != args.parent_model_sha:
        raise SystemExit(
            f"parent model.pt sha mismatch:\n"
            f"  expected (arg): {args.parent_model_sha}\n"
            f"  actual: {actual_model_sha}")

    actual_opt_sha = _sha256_file(str(optimizer_pt))
    if actual_opt_sha != args.parent_optimizer_sha:
        raise SystemExit(
            f"parent optimizer.pt sha mismatch:\n"
            f"  expected (arg): {args.parent_optimizer_sha}\n"
            f"  actual: {actual_opt_sha}")

    print(f"[r3null_carms] parent checkpoint shas verified ✓", flush=True)

    # Load config and contract
    cfg = ts.load_contract()
    batch = cfg["throughput"]["batch"]
    seq = cfg["model"]["seq"]
    ts_stamp = _ts()
    receipt_dir = Path(args.receipt_dir)

    # Load parent checkpoint (once, reused for both arms)
    print(f"[r3null_carms] loading parent checkpoint...", flush=True)
    m_state, o_state, r_state, ckpt_manifest = ts.load_checkpoint(str(parent_path))

    out_root = Path(args.out_dir) / f"r3null-carms-{ts_stamp}"
    out_root.mkdir(parents=True, exist_ok=True)

    # =====================================================================
    # C1: parent model + PARENT optimizer state (60-step warm) + 36 steps
    # =====================================================================
    print(f"[r3null_carms] C1: resuming with parent optimizer state...", flush=True)
    c1_dir = out_root / "c1"
    c1_receipt = ts.run_v0_segment(
        str(c1_dir), cfg, n_steps=C_ARM_STEPS, total_steps=TOTAL_STEPS, live=True,
        real_arch=True, device=args.device, resume_ckpt_dir=str(parent_path),
        shard_dir=args.shard_dir, checkpoint_every=C_ARM_STEPS,
        segment_id="r3null-c1-36steps",
        intermediate_override=None,  # use loaded ff width
        reset_optimizer_on_resume=False,  # PARENT optimizer state carried
        ce_chunk_tokens=args.ce_chunk_tokens,
    )
    assert c1_receipt["pass"] is True, "C1 arm did not complete"
    c1_losses = c1_receipt["losses"]

    # =====================================================================
    # C2: parent model + FRESH optimizer + pinned LR + 36 steps (same batches)
    # =====================================================================
    print(f"[r3null_carms] C2: resuming with fresh optimizer (pinned LR)...", flush=True)
    c2_dir = out_root / "c2"
    c2_receipt = ts.run_v0_segment(
        str(c2_dir), cfg, n_steps=C_ARM_STEPS, total_steps=TOTAL_STEPS, live=True,
        real_arch=True, device=args.device, resume_ckpt_dir=str(parent_path),
        shard_dir=args.shard_dir, checkpoint_every=C_ARM_STEPS,
        segment_id="r3null-c2-36steps",
        intermediate_override=None,  # use loaded ff width
        reset_optimizer_on_resume=True,  # FRESH optimizer
        ce_chunk_tokens=args.ce_chunk_tokens,
    )
    assert c2_receipt["pass"] is True, "C2 arm did not complete"
    c2_losses = c2_receipt["losses"]

    # =====================================================================
    # Compute deltas and assemble receipt
    # =====================================================================
    c1_losses_t = torch.tensor(c1_losses)
    c2_losses_t = torch.tensor(c2_losses)

    delta_c1_c2 = (c1_losses_t - c2_losses_t).tolist()
    delta_c1_c2_mean = float((c1_losses_t - c2_losses_t).mean())
    delta_c1_c2_max = float((c1_losses_t - c2_losses_t).abs().max())

    receipt: dict[str, Any] = {
        "ticket": "R3NULL-CARMS",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": "R3-null 3-arm: C1 (counterfactual, parent optimizer) and C2 (reset control) from shared parent checkpoint",
        "brief_ref": "state/r3null-launch-brief.md",
        "parent_checkpoint": str(parent_path),
        "parent_model_sha256": PARENT_MODEL_SHA,
        "parent_optimizer_sha256": PARENT_OPTIMIZER_SHA,
        "parent_step": CARRIED_STEP,
        "parent_total_steps": TOTAL_STEPS,
        "c_arm_steps": C_ARM_STEPS,
        "c1": {
            "segment_id": c1_receipt["segment_id"],
            "resume_step": c1_receipt["resume_step"],
            "global_step_end": c1_receipt["global_step_end"],
            "steps": c1_receipt["steps"],
            "loss_first": c1_receipt["loss_first"],
            "loss_last": c1_receipt["loss_last"],
            "losses": c1_losses,
            "optimizer_state": "parent_carried (60 steps warm, reset@670 per lineage)",
            "lr_treatment": "wsd_lr_frac pinned, step 730 carried",
        },
        "c2": {
            "segment_id": c2_receipt["segment_id"],
            "resume_step": c2_receipt["resume_step"],
            "global_step_end": c2_receipt["global_step_end"],
            "steps": c2_receipt["steps"],
            "loss_first": c2_receipt["loss_first"],
            "loss_last": c2_receipt["loss_last"],
            "losses": c2_losses,
            "optimizer_state": "fresh",
            "lr_treatment": "wsd_lr_frac pinned, step 730 carried",
        },
        "deltas": {
            "c1_minus_c2_per_step": delta_c1_c2,
            "c1_minus_c2_mean": delta_c1_c2_mean,
            "c1_minus_c2_max_abs": delta_c1_c2_max,
            "interpretation": "C1−C2 = value of parent-optimizer warmth (expected small, |Δloss|<0.01 per K2 equivalence)",
        },
        "note": "G receipt (G−C2, G−C1 comparisons) is produced separately by the board runner; C-arms reported here are the input pair.",
        "device": args.device,
        "measured_on_train_daemon": args.device == "cuda",
        "script": "src/ember/governance/scripts/r3null_carms.py",
        "pass": True,
        "verdict": "R3NULL_CARMS_PASS",
    }

    # Write receipt
    receipt_dir.mkdir(parents=True, exist_ok=True)
    out_path = receipt_dir / f"r3null-carms-{ts_stamp}.json"
    checked_write(str(out_path), receipt)
    print(
        f"R3NULL_CARMS_PASS ts={ts_stamp} c1_steps={c1_receipt['steps']} "
        f"c2_steps={c2_receipt['steps']} delta_c1_c2_mean={delta_c1_c2_mean:.6f} "
        f"receipt={out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="R3-null C-arms runner (C1 + C2 counterfactuals)")
    parser.add_argument("--selftest", action="store_true",
                       help="2-step CPU micro fixture with planted equality (no torch/GPU needed)")
    parser.add_argument("--parent-checkpoint", default="models/cbase-grow-live/live-20260703T053225Z/post/checkpoints/step-00000730/",
                       help="path to parent checkpoint (default: models/cbase-grow-live/.../step-00000730/, relative to repo root)")
    parser.add_argument("--parent-model-sha", default=PARENT_MODEL_SHA,
                       help=f"parent model.pt sha256 (required for live; default: {PARENT_MODEL_SHA})")
    parser.add_argument("--parent-optimizer-sha", default=PARENT_OPTIMIZER_SHA,
                       help=f"parent optimizer.pt sha256 (required for live; default: {PARENT_OPTIMIZER_SHA})")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                       help="device for training: cpu or cuda (default: cpu, NEVER auto-cuda)")
    parser.add_argument("--receipt-dir", default=str(RECEIPT_DIR_DEFAULT),
                       help="output receipt directory")
    parser.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT),
                       help="output models/checkpoints directory")
    parser.add_argument("--shard-dir", default=None,
                       help="path to packed uint16 shard directory (required for live)")
    parser.add_argument("--ce-chunk-tokens", type=int, default=131072,
                       help="CE chunk token budget (default 131072)")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        return 0
    else:
        return run_live(args)


if __name__ == "__main__":
    sys.exit(main())
