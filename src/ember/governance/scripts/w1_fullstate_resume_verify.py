# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""w1_fullstate_resume_verify.py -- W1 leg-A full-state resume verifier
(#735 supplementary; coordinator erratum, issue #735 comment 4942417647).

REPLAY, NEVER REIMPLEMENTATION: model/optimizer/checkpoint construction is
imported from w1_collapse_control_run.py and timeshare_pretrain.py -- the
SAME historical modules src/ember/governance/scripts/w1_baseline_replay_closure.py (#738) and
the original live run used. Tiny-fixture sizing (_tiny_real_arch,
PHASE2_SEED_HISTORICAL) and path defaults are imported from
w1_baseline_replay_closure itself (its sibling, same issue #735 toolchain)
rather than duplicated. This file adds NO new model/optimizer/RNG code
path -- it adds a recursive, value-level hash comparison the closure
verifier never performed.

WHY: PR #755's landed closure receipt (w1-baseline-replay-closure-
20260711T025650Z.json, verdict REPLAY_TRUSTWORTHY) was narrowed post-merge
by an external falsifier + coordinator adjudication. Two named defects in
the closure verifier's resumability leg:

  (a) optimizer_state_shape_parity (w1_collapse_control_run.py) compares
      state KEYS + tensor SHAPES only, never VALUES -- a same-shape
      corrupted optimizer-state tensor passes silently. Named
      counterexample: momentum [1,2] vs [999,-7] both report
      shapes_match: True.
  (b) reload_bit_exact_vs_pre_save_bf16 compares ONE primary BF16
      eval-loss float via eval_loss_fn, which computes cross-entropy over
      the model's PRIMARY logits only -- RealW1Model.forward's mtp_heads
      are never touched by that path, so a same-shape corruption of
      mtp_heads.<k>.weight preserves eval loss identically while silently
      changing resumable training state.

This script closes both gaps directly: it fresh-loads the exact same
checkpoint files via load_checkpoint() -- never any in-memory object a
prior process held -- which IS the exact pre-save state (save_checkpoint
torch.saves these objects with no transformation; load_checkpoint
torch.loads them back with no transformation). It then recursively hashes
EVERY model state_dict tensor (mtp_heads included), EVERY optimizer state
scalar/tensor (dtype+shape+device-normalized bytes, never shape alone),
and the RNG state -- and requires exact hash equality between that raw
on-disk state and a POST-APPLY state: a freshly built model/optimizer/RNG,
loaded via load_state_dict/load_optimizers_state/restore_rng (the SAME
resume path production code uses), then re-extracted via
state_dict()/save_optimizers_state()/capture_rng() and re-hashed.

No GPU re-run needed: device="cpu" throughout -- this is a pure
state-application + hash comparison, no forward/backward pass required.

--selftest: CPU-only synthetic fixtures (tiny real_arch, no real corpus
beyond an in-memory synthetic shard, no real checkpoints):
  (a) positive -- a saved tiny checkpoint (model+optimizer+RNG, one real
      train step so optimizer momentum state is populated) hashes
      bit-identical end to end; verdict FULLSTATE_RESUME_EXACT.
  (b) negative -- same-shape altered mtp_heads tensor: perturbs ONE
      mtp_heads weight on disk after save. Per-tensor hash comparison
      flips (model.exact False); the OLD eval-loss-based check
      (eval_loss_fn) is shown UNCHANGED on the same corrupted checkpoint,
      demonstrating the exact silent-pass this verifier closes.
  (c) negative -- same-shape altered optimizer tensor: perturbs ONE
      optimizer momentum/exp_avg buffer's bytes on disk after save.
      Per-key hash comparison flips (optimizer.exact False); the OLD
      optimizer_state_shape_parity check is shown STILL reporting
      shapes_match: True on the same corrupted checkpoint.

--live: loads the REAL custody-pinned leg-A checkpoint (default: the
#735 leg-A custody dir) and, before the resume-hash comparison, asserts
the checkpoint's 4 files independently re-hash to the EXPECTED_CUSTODY_
SHA256 pins below (never trusting the checkpoint's own manifest.json as
ground truth -- same discipline as the closure script's preflight leg).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import torch  # noqa: E402

# issue2015 exact-local-import:src/ember/governance/scripts/w1_collapse_control_run.py
import importlib.util as _ember_85e76a5cb35a8ea2_importlib
import sys as _ember_85e76a5cb35a8ea2_sys
from pathlib import Path as _ember_85e76a5cb35a8ea2_Path
_ember_85e76a5cb35a8ea2_path = _ember_85e76a5cb35a8ea2_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'w1_collapse_control_run.py')
if not _ember_85e76a5cb35a8ea2_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w1_collapse_control_run.py')
_ember_85e76a5cb35a8ea2_aliases = ('_ember_issue2015_85e76a5cb35a8ea2', 'scripts.w1_collapse_control_run', 'w1_collapse_control_run')
_ember_85e76a5cb35a8ea2_existing = []
for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
    _ember_85e76a5cb35a8ea2_candidate = _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias)
    if _ember_85e76a5cb35a8ea2_candidate is not None and all(_ember_85e76a5cb35a8ea2_candidate is not item for item in _ember_85e76a5cb35a8ea2_existing):
        _ember_85e76a5cb35a8ea2_existing.append(_ember_85e76a5cb35a8ea2_candidate)
if len(_ember_85e76a5cb35a8ea2_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w1_collapse_control_run.py')
if _ember_85e76a5cb35a8ea2_existing:
    _ember_85e76a5cb35a8ea2_module = _ember_85e76a5cb35a8ea2_existing[0]
    _ember_85e76a5cb35a8ea2_observed = getattr(_ember_85e76a5cb35a8ea2_module, '__file__', None)
    if _ember_85e76a5cb35a8ea2_observed is None or _ember_85e76a5cb35a8ea2_Path(_ember_85e76a5cb35a8ea2_observed).resolve() != _ember_85e76a5cb35a8ea2_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w1_collapse_control_run.py')
else:
    _ember_85e76a5cb35a8ea2_spec = _ember_85e76a5cb35a8ea2_importlib.spec_from_file_location('_ember_issue2015_85e76a5cb35a8ea2', _ember_85e76a5cb35a8ea2_path)
    if _ember_85e76a5cb35a8ea2_spec is None or _ember_85e76a5cb35a8ea2_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w1_collapse_control_run.py')
    _ember_85e76a5cb35a8ea2_module = _ember_85e76a5cb35a8ea2_importlib.module_from_spec(_ember_85e76a5cb35a8ea2_spec)
    for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
        _ember_85e76a5cb35a8ea2_prior = _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias)
        if _ember_85e76a5cb35a8ea2_prior is not None and _ember_85e76a5cb35a8ea2_prior is not _ember_85e76a5cb35a8ea2_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_collapse_control_run.py')
        _ember_85e76a5cb35a8ea2_sys.modules[_ember_85e76a5cb35a8ea2_alias] = _ember_85e76a5cb35a8ea2_module
    try:
        _ember_85e76a5cb35a8ea2_spec.loader.exec_module(_ember_85e76a5cb35a8ea2_module)
    except BaseException:
        for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
            if _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias) is _ember_85e76a5cb35a8ea2_module:
                _ember_85e76a5cb35a8ea2_sys.modules.pop(_ember_85e76a5cb35a8ea2_alias, None)
        raise
for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
    _ember_85e76a5cb35a8ea2_prior = _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias)
    if _ember_85e76a5cb35a8ea2_prior is not None and _ember_85e76a5cb35a8ea2_prior is not _ember_85e76a5cb35a8ea2_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_collapse_control_run.py')
    _ember_85e76a5cb35a8ea2_sys.modules[_ember_85e76a5cb35a8ea2_alias] = _ember_85e76a5cb35a8ea2_module
load_json = getattr(_ember_85e76a5cb35a8ea2_module, 'load_json')
sha256_file = getattr(_ember_85e76a5cb35a8ea2_module, 'sha256_file')
build_real_model = getattr(_ember_85e76a5cb35a8ea2_module, 'build_real_model')
verify_checkpoint_key_shape_parity = getattr(_ember_85e76a5cb35a8ea2_module, 'verify_checkpoint_key_shape_parity')
eval_loss_fn = getattr(_ember_85e76a5cb35a8ea2_module, 'eval_loss_fn')
optimizer_state_shape_parity = getattr(_ember_85e76a5cb35a8ea2_module, 'optimizer_state_shape_parity')
derive_real_arch_config = getattr(_ember_85e76a5cb35a8ea2_module, 'derive_real_arch_config')
derive_rung_receipt_from_manifest = getattr(_ember_85e76a5cb35a8ea2_module, 'derive_rung_receipt_from_manifest')
apply_cosine_warmup = getattr(_ember_85e76a5cb35a8ea2_module, 'apply_cosine_warmup')
train_step_matched_recipe = getattr(_ember_85e76a5cb35a8ea2_module, 'train_step_matched_recipe')
resolve_ce_impl = getattr(_ember_85e76a5cb35a8ea2_module, 'resolve_ce_impl')
DEFAULT_PRICING_RECEIPT = getattr(_ember_85e76a5cb35a8ea2_module, 'DEFAULT_PRICING_RECEIPT')
config_sha = getattr(_ember_85e76a5cb35a8ea2_module, 'config_sha')
real_config_dict = getattr(_ember_85e76a5cb35a8ea2_module, 'real_config_dict')
# issue2015 exact-local-import-end:src/ember/governance/scripts/w1_collapse_control_run.py
from timeshare_pretrain import (  # noqa: E402 -- reused, never edited
    load_checkpoint, save_checkpoint, capture_rng, restore_rng,
    PackedShardLoader, build_split_optimizer, save_optimizers_state,
    load_optimizers_state, CONTRACT_PATH as PRETRAIN_CONTRACT_PATH,
)
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

# Sibling import (same #735 toolchain, never duplicated): tiny-fixture
# sizing + path/seed defaults the closure script already established.
# issue2015 exact-local-import:src/ember/governance/scripts/w1_baseline_replay_closure.py
import importlib.util as _ember_f47a2689ff219dfc_importlib
import sys as _ember_f47a2689ff219dfc_sys
from pathlib import Path as _ember_f47a2689ff219dfc_Path
_ember_f47a2689ff219dfc_path = _ember_f47a2689ff219dfc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'w1_baseline_replay_closure.py')
if not _ember_f47a2689ff219dfc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w1_baseline_replay_closure.py')
_ember_f47a2689ff219dfc_aliases = ('_ember_issue2015_f47a2689ff219dfc', 'scripts.w1_baseline_replay_closure', 'w1_baseline_replay_closure')
_ember_f47a2689ff219dfc_existing = []
for _ember_f47a2689ff219dfc_alias in _ember_f47a2689ff219dfc_aliases:
    _ember_f47a2689ff219dfc_candidate = _ember_f47a2689ff219dfc_sys.modules.get(_ember_f47a2689ff219dfc_alias)
    if _ember_f47a2689ff219dfc_candidate is not None and all(_ember_f47a2689ff219dfc_candidate is not item for item in _ember_f47a2689ff219dfc_existing):
        _ember_f47a2689ff219dfc_existing.append(_ember_f47a2689ff219dfc_candidate)
if len(_ember_f47a2689ff219dfc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w1_baseline_replay_closure.py')
if _ember_f47a2689ff219dfc_existing:
    _ember_f47a2689ff219dfc_module = _ember_f47a2689ff219dfc_existing[0]
    _ember_f47a2689ff219dfc_observed = getattr(_ember_f47a2689ff219dfc_module, '__file__', None)
    if _ember_f47a2689ff219dfc_observed is None or _ember_f47a2689ff219dfc_Path(_ember_f47a2689ff219dfc_observed).resolve() != _ember_f47a2689ff219dfc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w1_baseline_replay_closure.py')
else:
    _ember_f47a2689ff219dfc_spec = _ember_f47a2689ff219dfc_importlib.spec_from_file_location('_ember_issue2015_f47a2689ff219dfc', _ember_f47a2689ff219dfc_path)
    if _ember_f47a2689ff219dfc_spec is None or _ember_f47a2689ff219dfc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w1_baseline_replay_closure.py')
    _ember_f47a2689ff219dfc_module = _ember_f47a2689ff219dfc_importlib.module_from_spec(_ember_f47a2689ff219dfc_spec)
    for _ember_f47a2689ff219dfc_alias in _ember_f47a2689ff219dfc_aliases:
        _ember_f47a2689ff219dfc_prior = _ember_f47a2689ff219dfc_sys.modules.get(_ember_f47a2689ff219dfc_alias)
        if _ember_f47a2689ff219dfc_prior is not None and _ember_f47a2689ff219dfc_prior is not _ember_f47a2689ff219dfc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_baseline_replay_closure.py')
        _ember_f47a2689ff219dfc_sys.modules[_ember_f47a2689ff219dfc_alias] = _ember_f47a2689ff219dfc_module
    try:
        _ember_f47a2689ff219dfc_spec.loader.exec_module(_ember_f47a2689ff219dfc_module)
    except BaseException:
        for _ember_f47a2689ff219dfc_alias in _ember_f47a2689ff219dfc_aliases:
            if _ember_f47a2689ff219dfc_sys.modules.get(_ember_f47a2689ff219dfc_alias) is _ember_f47a2689ff219dfc_module:
                _ember_f47a2689ff219dfc_sys.modules.pop(_ember_f47a2689ff219dfc_alias, None)
        raise
for _ember_f47a2689ff219dfc_alias in _ember_f47a2689ff219dfc_aliases:
    _ember_f47a2689ff219dfc_prior = _ember_f47a2689ff219dfc_sys.modules.get(_ember_f47a2689ff219dfc_alias)
    if _ember_f47a2689ff219dfc_prior is not None and _ember_f47a2689ff219dfc_prior is not _ember_f47a2689ff219dfc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_baseline_replay_closure.py')
    _ember_f47a2689ff219dfc_sys.modules[_ember_f47a2689ff219dfc_alias] = _ember_f47a2689ff219dfc_module
_tiny_real_arch = getattr(_ember_f47a2689ff219dfc_module, '_tiny_real_arch')
_build_tiny_shard_dir = getattr(_ember_f47a2689ff219dfc_module, '_build_tiny_shard_dir')
closure_resolve = getattr(_ember_f47a2689ff219dfc_module, 'resolve')
PHASE2_SEED_HISTORICAL = getattr(_ember_f47a2689ff219dfc_module, 'PHASE2_SEED_HISTORICAL')
DEFAULT_RUNG_MANIFEST = getattr(_ember_f47a2689ff219dfc_module, 'DEFAULT_RUNG_MANIFEST')
EXPECTED_CONFIG_SHA256 = getattr(_ember_f47a2689ff219dfc_module, 'EXPECTED_CONFIG_SHA256')
# issue2015 exact-local-import-end:src/ember/governance/scripts/w1_baseline_replay_closure.py

ISSUE_REF = "#735"
SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint files; sha256 over device-normalized "
    "(cpu, contiguous, bitcast-to-uint8) tensor bytes prefixed with shape+"
    "dtype for every model/optimizer state tensor and RNG buffer hashed "
    "below (the tensor_hash convention used throughout this receipt)")

# --- #735 leg-A custody pins (receipts/ember-c-scale/w1-baseline-replay-
# closure-20260711T025650Z.json's own "custody" section, files_sha256_
# post_move -- re-cited here, never re-derived from the checkpoint's own
# manifest.json, so a tampered custody copy cannot self-certify). ---
DEFAULT_CUSTODY_DIR = os.path.join(
    "models", "w1-baseline-replay-custody",
    "w1-baseline-replay-step50-20260711T025650Z")
EXPECTED_CUSTODY_SHA256 = {
    "model.pt": "8055a9f4b67711b8f1103dcf76228c5f303ba6d6170af17243b17b7c5289ea54",
    "optimizer.pt": "324b988f73b8741bc3b04c4a18bf0823ec271d56ecc1c6608b269121524da250",
    "rng.pt": "c9ca61ab0e5fb9661e54dc9bb2df294f3828390829c997330f9290a02aabc379",
    "manifest.json": "af828fd6388c7d0c00ec688bf291f474b0158c308a022f3d19fffc58b6b68504",
}
# The landed, git-tracked closure receipt (#755) -- the AUTHORITATIVE prior
# artifact this run's pricing-receipt/rung-manifest binds are equality-
# gated against (round-2 repair: round-1's bind was a bare readability
# check, never a comparison -- this cures that).
DEFAULT_CLOSURE_RECEIPT = os.path.join(
    "receipts", "ember-c-scale",
    "w1-baseline-replay-closure-20260711T025650Z-redacted-edition.json")


def resolve(repo_root: str, path: str) -> str:
    return closure_resolve(repo_root, path)


# ---------------------------------------------------------------------------
# Custody pin check -- never trusts the checkpoint's own manifest.json as
# ground truth (same discipline as the closure script's
# _verify_checkpoint_manifest).
# ---------------------------------------------------------------------------

def verify_custody_pins(ckpt_dir: str, expected: dict) -> dict:
    measured = {fname: sha256_file(os.path.join(ckpt_dir, fname)) for fname in expected}
    per_file_match = {fname: measured[fname] == expected[fname] for fname in expected}
    return {"dir": ckpt_dir, "measured_sha256": measured, "expected_sha256": expected,
            "per_file_match": per_file_match, "pass": all(per_file_match.values())}


# ---------------------------------------------------------------------------
# Runtime-reconstruction-input binding (coordinator repair round, issue #758
# review comment on this file's PR) -- the --live path reconstructs
# real_arch/pretrain_contract from THREE external files (pricing receipt,
# rung manifest, v0-pretrain-config/contract). Without binding this run to
# their exact content, a silently substituted file could change what
# "real_arch" means between the checkpoint's own closure receipt and this
# supplementary receipt while still reporting the strongest verdict. Two
# independent binds, both required for --live (never for --selftest, which
# has no external reconstruction inputs to bind against -- see
# runtime_inputs_bound=None / config_sha_bound=None handling below):
#
#   1. bind_runtime_reconstruction_inputs -- exact source path + measured
#      sha256 for each of the three files, EQUALITY-GATED against the
#      landed, git-tracked closure receipt's own preflight.pricing_
#      receipt_sha256 / preflight.rung_manifest_sha256 (an INDEPENDENT
#      prior artifact -- round-2 repair: round-1's version only checked
#      "was the file readable", never compared to anything, so bound=True
#      for ANY readable file regardless of content). The v0-pretrain-
#      config/contract has NO corresponding field in the closure receipt
#      -- disclosed as a NEWLY-ESTABLISHED supplemental pin, never
#      presented as an original closure pin.
#   2. bind_real_arch_config_sha -- proves THIS run's reconstructed
#      real_arch maps to the SAME config_sha the closure script (#738)
#      already froze and pinned (EXPECTED_CONFIG_SHA256) -- the "original
#      closure config SHA plus a proved mapping" bind: even though
#      layers=20/heads=16 are ASSUMED (real_arch["layers_heads_source"]
#      discloses this -- not independently present in the grow-rung
#      receipt chain), this equality check proves the assumption is
#      IDENTICAL to the one the already-landed closure receipt's own
#      verifier independently derived and pinned.
# ---------------------------------------------------------------------------

def _measure_and_pin(path: str, expected_sha256: "str | None",
                      pin_source: str) -> dict:
    """Measures path's sha256 and, when an authoritative expected_sha256 is
    supplied, equality-gates against it. match is None (never silently
    True) when there is nothing authoritative to compare against -- the
    round-1 defect this cures was treating "file is readable" as "bound"
    with no comparison at all."""
    try:
        measured = sha256_file(path)
        bound = True
        error = None
    except OSError as exc:
        measured, bound, error = None, False, str(exc)
    out = {
        "path": path, "sha256": measured, "bound": bound,
        "pin_source": pin_source, "expected_sha256": expected_sha256,
        "match": ((measured == expected_sha256)
                  if (bound and expected_sha256 is not None) else None),
    }
    if error is not None:
        out["error"] = error
    return out


def bind_runtime_reconstruction_inputs(pricing_receipt_path: str,
                                        rung_manifest_path: str,
                                        contract_path: str,
                                        closure_receipt: dict,
                                        closure_receipt_path: str) -> dict:
    closure_pf = closure_receipt.get("preflight", {})
    closure_basename = os.path.basename(closure_receipt_path)
    out = {
        "pricing_receipt": _measure_and_pin(
            pricing_receipt_path, closure_pf.get("pricing_receipt_sha256"),
            f"closure receipt {closure_basename} "
            "preflight.pricing_receipt_sha256 (landed, git-tracked, "
            "authoritative)"),
        "rung_manifest": _measure_and_pin(
            rung_manifest_path, closure_pf.get("rung_manifest_sha256"),
            f"closure receipt {closure_basename} "
            "preflight.rung_manifest_sha256 (landed, git-tracked, "
            "authoritative)"),
        "pretrain_contract": _measure_and_pin(
            contract_path, None,
            "NEWLY-ESTABLISHED supplemental pin -- the landed closure "
            "receipt's preflight never recorded a v0-pretrain-config/"
            "contract hash; this is the first time this exact file's "
            "sha256 is pinned by any receipt in this toolchain, disclosed "
            "as such, never presented as an original closure pin."),
    }
    out["closure_receipt_path"] = closure_receipt_path
    out["all_bound"] = all(v["bound"] for v in out.values() if isinstance(v, dict))
    out["any_pin_mismatch"] = any(
        v.get("match") is False for v in out.values() if isinstance(v, dict))
    return out


def bind_contract_consumed_fields(pretrain_contract: dict,
                                   closure_receipt: dict) -> dict:
    """Structural check on the ONE contract field real_arch actually
    consumes (objective.mtp_aux_heads.n_heads) -- team-lead's named
    alternative to a whole-file pin, applied IN ADDITION to the newly-
    established whole-file pin above (defense in depth, not a
    substitute). Expected value is read from the closure receipt's own
    INDEPENDENTLY-LANDED preflight.real_arch.n_mtp, never from this run's
    own derive_real_arch_config output -- comparing against a value this
    run itself derived would be self-referential (the verifier deriving
    its own expectation), the exact class this check exists to avoid."""
    n_heads = (pretrain_contract.get("objective", {})
               .get("mtp_aux_heads", {}).get("n_heads"))
    expected_n_heads = (closure_receipt.get("preflight", {})
                         .get("real_arch", {}).get("n_mtp"))
    return {
        "field": "objective.mtp_aux_heads.n_heads", "measured": n_heads,
        "expected_source": ("closure receipt preflight.real_arch.n_mtp "
                             "(independently landed, not derived by this "
                             "run)"),
        "expected": expected_n_heads,
        "pass": expected_n_heads is not None and n_heads == expected_n_heads,
    }


def bind_real_arch_config_sha(real_arch: dict, expected_config_sha256: str) -> dict:
    cfg = real_config_dict(real_arch)
    measured = config_sha(cfg)
    return {
        "real_config_dict": cfg,
        "measured_config_sha256": measured,
        "expected_config_sha256": expected_config_sha256,
        "source": (
            "src/ember/governance/scripts/w1_baseline_replay_closure.py EXPECTED_CONFIG_SHA256 "
            "-- frozen at the #735/#738 closure landing, independently "
            "derived there via the SAME config_sha(real_config_dict("
            "real_arch)) call over that receipt's own real_arch"),
        "pass": measured == expected_config_sha256,
    }


def _git_source_commit(repo_root: str) -> dict:
    """Captures the git commit this verification ran against, so a reader
    knows exactly which version of derive_real_arch_config/RealW1Model/etc
    produced real_arch. Never raises -- a git failure is disclosed, not
    fatal to the verification run.

    Round-2 repair (dirty-tree binding): a claim-bearing run against a
    dirty working tree does not refuse outright (that would block normal
    edit-then-verify iteration), but a dirty tree ALSO never qualifies for
    the strongest verdict (see verify_fullstate_resume's source_top_claim_
    ok gate) -- and when dirty, the exact `git diff HEAD` bytes are
    sha256'd and disclosed here, so the receipt is auditable against the
    precise uncommitted code that produced it rather than only the parent
    commit."""
    try:
        sha = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True, check=True, text=True).stdout.strip()
        # --untracked-files=no: dirtiness here means "does the TRACKED,
        # versioned content differ from HEAD" (what actually determines
        # which code ran) -- an unrelated untracked scratch file sitting
        # in the worktree is not a code-provenance concern and must never
        # force every run to report dirty. `git diff HEAD` below already
        # only ever considers tracked files, so this keeps the two checks
        # consistent with each other.
        status_out = subprocess.run(
            ["git", "-C", repo_root, "status", "--porcelain",
             "--untracked-files=no"],
            capture_output=True, check=True, text=True).stdout.strip()
        dirty = bool(status_out)
        dirty_diff_sha256 = None
        if dirty:
            diff_bytes = subprocess.run(
                ["git", "-C", repo_root, "diff", "HEAD"],
                capture_output=True, check=True).stdout
            dirty_diff_sha256 = hashlib.sha256(diff_bytes).hexdigest()
        return {"sha": sha, "working_tree_dirty": dirty,
                "dirty_diff_sha256": dirty_diff_sha256, "available": True}
    except Exception as exc:  # noqa: BLE001 -- disclosure, never fatal
        return {"sha": None, "working_tree_dirty": None,
                "dirty_diff_sha256": None, "available": False,
                "error": str(exc)}


def _relpath_or_abs(path: str, start: str) -> str:
    """os.path.relpath has no defined answer across Windows drive letters
    and raises ValueError rather than guessing (the --out-dir cross-drive
    crash this repair fixes -- e.g. receipt on C: relative to a repo_root
    on B:). Falls back to the absolute path for display only; never
    changes what gets written to disk."""
    try:
        return os.path.relpath(path, start)
    except ValueError:
        return path


# ---------------------------------------------------------------------------
# Device-normalized recursive hashing -- the load-bearing addition. A
# tensor's hash is dtype+shape+raw-bytes after moving to CPU, making
# contiguous, and bitcasting to uint8 (Tensor.view(dtype) reinterprets
# bits without value conversion, so this covers bf16/fp32/fp16/int* alike
# without a numpy dtype-support special case). A non-tensor optimizer-
# state leaf (e.g. a plain-int "step" counter, version-dependent) is
# type-tagged and repr-hashed rather than silently skipped -- this is
# exactly the class optimizer_state_shape_parity's `if not
# isinstance(orig_t, torch.Tensor): continue` drops.
# ---------------------------------------------------------------------------

def _tensor_hash(t: "torch.Tensor") -> str:
    t_cpu = t.detach().to("cpu").contiguous().reshape(-1)
    raw = t_cpu.view(torch.uint8).numpy().tobytes()
    h = hashlib.sha256()
    h.update(str(tuple(t.shape)).encode())
    h.update(str(t.dtype).encode())
    h.update(raw)
    return h.hexdigest()


def _hash_value(v) -> str:
    if torch.is_tensor(v):
        return "tensor:" + _tensor_hash(v)
    return f"{type(v).__name__}:{v!r}"


def _hash_model_state(state: dict) -> dict:
    return {k: _tensor_hash(state[k]) for k in sorted(state.keys())}


def _hash_optimizer_state(bundle: dict) -> dict:
    """Recursively hashes EVERY optimizer-state leaf (state + param_groups
    hyperparameters, params-list excluded since it is an index list, not
    a value) for every optimizer key in a save_optimizers_state() bundle."""
    out = {}
    for opt_key in sorted(bundle.keys()):
        opt_sd = bundle[opt_key]
        state = opt_sd.get("state", {})
        per_param = {}
        for pidx in sorted(state.keys(), key=str):
            pstate = state[pidx]
            per_param[str(pidx)] = {
                buf: _hash_value(val) for buf, val in sorted(pstate.items())}
        pg_repr = json.dumps(
            [{k: v for k, v in g.items() if k != "params"}
             for g in opt_sd.get("param_groups", [])],
            sort_keys=True, default=str)
        out[opt_key] = {
            "n_params": len(state),
            "per_param_hashes": per_param,
            "param_groups_hash": hashlib.sha256(pg_repr.encode()).hexdigest(),
        }
    return out


def _hash_rng_state(state: dict) -> str:
    h = hashlib.sha256()
    h.update(repr(state["py_random"]).encode())
    h.update(_tensor_hash(state["torch_cpu"]).encode())
    if "np_random" in state:
        a0, a1, a2, a3, a4 = state["np_random"]
        h.update(repr(a0).encode())
        h.update(np.ascontiguousarray(a1).tobytes())
        h.update(repr((a2, a3, a4)).encode())
    if "torch_cuda" in state:
        for t in state["torch_cuda"]:
            h.update(_tensor_hash(t).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Comparison primitives -- pure functions over two hash-dicts, reused for
# BOTH gates below (never duplicated logic between them).
# ---------------------------------------------------------------------------

def _compare_model_hashes(hashes_a: dict, hashes_b: dict) -> dict:
    keys_a, keys_b = set(hashes_a), set(hashes_b)
    key_mismatch = sorted(keys_a ^ keys_b)
    tensor_mismatches = sorted(
        k for k in (keys_a & keys_b) if hashes_a[k] != hashes_b[k])
    mtp_keys = sorted(k for k in hashes_a if "mtp_heads." in k)
    return {
        "n_tensors_checked": len(keys_a),
        "n_mtp_head_tensors_checked": len(mtp_keys),
        "mtp_head_keys": mtp_keys,
        "key_set_mismatch": key_mismatch,
        "tensor_hash_mismatches": tensor_mismatches,
        "exact": not key_mismatch and not tensor_mismatches,
    }


def _compare_optimizer_hashes(hashes_a: dict, hashes_b: dict) -> dict:
    mismatches: list = []
    for opt_key in sorted(set(hashes_a) | set(hashes_b)):
        a, b = hashes_a.get(opt_key), hashes_b.get(opt_key)
        if a is None or b is None:
            mismatches.append(f"{opt_key}: missing on one side "
                               f"(a={a is not None} b={b is not None})")
            continue
        if a["param_groups_hash"] != b["param_groups_hash"]:
            mismatches.append(f"{opt_key}: param_groups_hash differs")
        a_params, b_params = a["per_param_hashes"], b["per_param_hashes"]
        for pidx in sorted(set(a_params) | set(b_params)):
            ap, bp = a_params.get(pidx, {}), b_params.get(pidx, {})
            for buf in sorted(set(ap) | set(bp)):
                if ap.get(buf) != bp.get(buf):
                    mismatches.append(f"{opt_key}[{pidx}].{buf}: hash differs")
    return {
        "n_optimizer_keys_checked": len(hashes_a),
        "n_params_per_key": {k: v["n_params"] for k, v in hashes_a.items()},
        "mismatches": mismatches,
        "exact": len(mismatches) == 0,
    }


# ---------------------------------------------------------------------------
# Core verifier -- fresh-load the checkpoint, apply it to a NEW model/
# optimizer/RNG via the SAME resume path production code uses, re-extract,
# re-hash. Two independent gates:
#
#   1. LOAD-PATH FIDELITY (always run): raw on-disk state (what
#      load_checkpoint() returns directly -- a straight torch.load with no
#      transformation) vs the load_state_dict/load_optimizers_state/
#      restore_rng -> re-extract round trip. Proves resuming from this
#      checkpoint via the production apply path does not silently drop,
#      truncate, misalign, or coerce ANY tensor/scalar -- covering every
#      model tensor (mtp_heads included) and every optimizer value (not
#      shape alone), which is what the landed closure receipt's verifier
#      never checked.
#
#   2. SAVE FIDELITY (only when pre_save_hashes is supplied): the raw
#      on-disk state vs a hash captured DIRECTLY from the in-memory
#      objects immediately before save_checkpoint wrote them, in the SAME
#      process. This is the literal "compare against the exact pre-save
#      state" the erratum names -- catches corruption introduced at
#      save time or by post-write tampering, which gate 1 (a purely
#      self-referential comparison against the same file) cannot see by
#      construction. Only available where the pre-save objects still
#      exist to hash (selftest fixtures, same process); the real --live
#      leg-A checkpoint was produced by an already-finished process, so
#      no such in-memory reference survives for it -- main()'s
#      independent custody-sha pin check (verify_custody_pins, comparing
#      against hashes recorded in a SEPARATE receipt at save time) is the
#      achievable equivalent for that case, disclosed as such in the
#      receipt rather than silently substituted.
# ---------------------------------------------------------------------------

def verify_fullstate_resume(*, real_arch: dict, pretrain_contract: dict,
                             ckpt_dir: str, seed: int, device: str = "cpu",
                             pre_save_hashes: "dict | None" = None,
                             runtime_inputs_bound: "dict | None" = None,
                             config_sha_bound: "dict | None" = None,
                             source_commit: "dict | None" = None) -> dict:
    m_state, o_state, r_state, manifest = load_checkpoint(ckpt_dir)

    model_hashes_saved = _hash_model_state(m_state)
    optimizer_hashes_saved = _hash_optimizer_state(o_state)
    rng_hash_saved = _hash_rng_state(r_state)

    model = build_real_model(real_arch, device, seed=seed)
    verify_checkpoint_key_shape_parity(m_state, model)
    model.load_state_dict(m_state, strict=True)
    optimizers, _base_lrs, _routing = build_split_optimizer(
        model, pretrain_contract, force_fallback=False)
    load_optimizers_state(optimizers, o_state)
    restore_rng(r_state)

    model_hashes_applied = _hash_model_state(model.state_dict())
    optimizer_hashes_applied = _hash_optimizer_state(save_optimizers_state(optimizers))
    rng_hash_applied = _hash_rng_state(capture_rng())
    del model, optimizers
    if device == "cuda":
        torch.cuda.empty_cache()

    load_path_fidelity = {
        "model": _compare_model_hashes(model_hashes_saved, model_hashes_applied),
        "optimizer": _compare_optimizer_hashes(optimizer_hashes_saved, optimizer_hashes_applied),
        "rng": {"hash_on_disk": rng_hash_saved, "hash_after_apply": rng_hash_applied,
                "exact": rng_hash_saved == rng_hash_applied},
    }
    load_path_exact = (load_path_fidelity["model"]["exact"]
                        and load_path_fidelity["optimizer"]["exact"]
                        and load_path_fidelity["rng"]["exact"])

    # save_fidelity_exact is None (never True) when unchecked -- a bare
    # default of True here would be a VACUOUS pass indistinguishable in
    # the receipt from "checked and matched", exactly the kind of silent
    # trivial-pass this whole supplementary verifier exists to eliminate
    # elsewhere.
    save_fidelity = None
    save_fidelity_exact = None
    if pre_save_hashes is not None:
        save_fidelity = {
            "model": _compare_model_hashes(pre_save_hashes["model"], model_hashes_saved),
            "optimizer": _compare_optimizer_hashes(pre_save_hashes["optimizer"], optimizer_hashes_saved),
            "rng": {"hash_pre_save": pre_save_hashes["rng"], "hash_on_disk": rng_hash_saved,
                    "exact": pre_save_hashes["rng"] == rng_hash_saved},
        }
        save_fidelity_exact = (save_fidelity["model"]["exact"]
                                and save_fidelity["optimizer"]["exact"]
                                and save_fidelity["rng"]["exact"])
        save_fidelity_disclosure = (
            "save_fidelity_checked=true: hashes were captured directly "
            "from the exact in-memory objects immediately before "
            "save_checkpoint wrote them (same process, no gap) and "
            f"compared bit-exact against the on-disk file (exact="
            f"{save_fidelity_exact}) -- the strongest fidelity claim this "
            "verifier can make, only achievable when the process that "
            "wrote the checkpoint is the same process running "
            "verification.")
    else:
        save_fidelity_disclosure = (
            "save_fidelity_checked=false: no in-memory pre-save reference "
            "exists for this checkpoint -- the process that wrote it has "
            "already exited, so the literal 'exact pre-save in-memory "
            "state' this gate tests is UNAVAILABLE, not merely skipped. "
            "The achievable substitute is verify_custody_pins: an "
            "independent re-hash of the 4 on-disk files against "
            "EXPECTED_CUSTODY_SHA256 pins recorded in a SEPARATE receipt "
            "at save time, which proves this checkpoint's raw bytes are "
            "byte-identical to what was pinned then. It does NOT prove "
            "those pinned bytes equal the true in-memory state at the "
            "instant save_checkpoint was called in the original process -- "
            "only a same-process selftest (this script's --selftest legs "
            "(a)/(b)/(c)) can check that. A null save_fidelity field means "
            "UNAVAILABLE here, never a silent pass.")

    # Gate 3: runtime-reconstruction-input binding. Only applicable when
    # the caller supplies real binds (the --live path, always) -- a
    # --selftest synthetic tiny fixture has no external pricing-receipt/
    # rung-manifest/contract provenance chain to bind against at all
    # (inapplicable, vacuously OK for the top claim -- NOT the same as
    # "measured and wrong", which is a genuine divergence, see below).
    runtime_binds_applicable = (runtime_inputs_bound is not None
                                 or config_sha_bound is not None)
    runtime_binds_measured_and_failed = bool(
        (runtime_inputs_bound is not None and runtime_inputs_bound["any_pin_mismatch"])
        or (config_sha_bound is not None and not config_sha_bound["pass"]))
    runtime_binds_top_claim_ok = (
        (runtime_inputs_bound is None or (runtime_inputs_bound["all_bound"]
                                           and not runtime_inputs_bound["any_pin_mismatch"]))
        and (config_sha_bound is None or config_sha_bound["pass"]))

    # Gate 4 (round-2 repair, DIRTY SOURCE): a claim-bearing run against a
    # dirty tree never qualifies for the strongest verdict -- inapplicable
    # (source_commit=None, e.g. --selftest) is vacuously OK, same
    # convention as gate 3 above; MEASURED-dirty is not.
    source_applicable = source_commit is not None
    source_clean_and_bound = bool(
        source_applicable and source_commit.get("available")
        and source_commit.get("working_tree_dirty") is False)
    source_top_claim_ok = (not source_applicable) or source_clean_and_bound

    # save_fidelity_top_claim_ok is True ONLY when checked AND exact --
    # unlike round-1 (save_fidelity_gate_satisfied defaulted True when
    # UNCHECKED, so an unmeasured save-fidelity gate silently satisfied
    # the strongest claim: the exact vacuous-pass bug an external
    # falsifier caught live -- exit 0 / FULLSTATE_RESUME_EXACT with
    # save_fidelity_checked=false). "Unchecked" here means NOT satisfied
    # for the strongest claim, but never DIVERGED on its own (nothing was
    # measured wrong) -- it caps the verdict at FULLSTATE_LOAD_PATH_EXACT
    # instead, REGARDLESS of how the input binds came out (team-lead's
    # round-2 grammar, encoded here rather than left as prose).
    save_fidelity_checked = pre_save_hashes is not None
    save_fidelity_top_claim_ok = bool(save_fidelity_checked and save_fidelity_exact)
    save_fidelity_measured_and_failed = bool(save_fidelity_checked and not save_fidelity_exact)

    # Verdict grammar (round-2, three tiers, monotonic in evidentiary
    # strength): DIVERGED = something MEASURED came back wrong (worst).
    # LOAD_PATH_EXACT = everything measured is exact, but at least one
    # precondition for the strongest claim is unmet (unmeasured/
    # inapplicable/dirty -- middle). RESUME_EXACT = load-path exact AND
    # same-process pre-save hashes exact AND canonical input pins exact
    # AND clean/bound source (best, and structurally UNREACHABLE for
    # --live, which never has a same-process pre-save reference to check
    # -- see save_fidelity's own disclosure text).
    if not load_path_exact:
        verdict = "FULLSTATE_RESUME_DIVERGED"
    elif save_fidelity_measured_and_failed or runtime_binds_measured_and_failed:
        verdict = "FULLSTATE_RESUME_DIVERGED"
    elif save_fidelity_top_claim_ok and runtime_binds_top_claim_ok and source_top_claim_ok:
        verdict = "FULLSTATE_RESUME_EXACT"
    else:
        verdict = "FULLSTATE_LOAD_PATH_EXACT"

    return {
        "ckpt_dir": ckpt_dir,
        "manifest_step": manifest.get("step"),
        "load_path_fidelity": load_path_fidelity,
        "load_path_exact": load_path_exact,
        "save_fidelity": save_fidelity,
        "save_fidelity_checked": save_fidelity_checked,
        "save_fidelity_exact": save_fidelity_exact,
        "save_fidelity_disclosure": save_fidelity_disclosure,
        "save_fidelity_top_claim_ok": save_fidelity_top_claim_ok,
        "runtime_inputs_bound": runtime_inputs_bound,
        "config_sha_bound": config_sha_bound,
        "runtime_binds_applicable": runtime_binds_applicable,
        "runtime_binds_satisfied": (runtime_binds_top_claim_ok
                                     if runtime_binds_applicable else None),
        "runtime_binds_measured_and_failed": runtime_binds_measured_and_failed,
        "source_commit": source_commit,
        "source_applicable": source_applicable,
        "source_top_claim_ok": source_top_claim_ok,
        "model": load_path_fidelity["model"],
        "optimizer": load_path_fidelity["optimizer"],
        "rng": load_path_fidelity["rng"],
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Negative-fixture corruption helpers (TEST-ONLY, never called from the
# real --live path). Generic key-substring targeting -- never a hardcoded
# key name that could drift if the model/optimizer internals change.
# ---------------------------------------------------------------------------

def _corrupt_model_tensor_by_key_substring(ckpt_dir: str, substring: str) -> str:
    """Perturbs the FIRST float tensor in model.pt whose key contains
    `substring`, same shape, and rewrites manifest.json's model.pt sha so
    load_checkpoint's own sha-integrity check still passes. Returns the
    corrupted key name."""
    model_pt_path = os.path.join(ckpt_dir, "model.pt")
    state = torch.load(model_pt_path, map_location="cpu")
    target_key = None
    for key, tensor in state.items():
        if substring in key and torch.is_tensor(tensor) and tensor.is_floating_point():
            state[key] = tensor + 1.0
            target_key = key
            break
    if target_key is None:
        raise AssertionError(
            f"W1_FULLSTATE_TEST_CORRUPT_NO_MATCH: substring={substring!r} "
            f"keys={list(state.keys())!r}")
    torch.save(state, model_pt_path)
    _rewrite_manifest_sha(ckpt_dir, "model.pt")
    return target_key


def _corrupt_optimizer_tensor(ckpt_dir: str) -> str:
    """Perturbs the FIRST float tensor found anywhere inside optimizer.pt's
    per-param 'state' dicts (any optimizer key, any buffer name), same
    shape, and rewrites manifest.json's optimizer.pt sha. Returns a
    'opt_key[pidx].buf_name' descriptor of the corrupted leaf."""
    optimizer_pt_path = os.path.join(ckpt_dir, "optimizer.pt")
    bundle = torch.load(optimizer_pt_path, map_location="cpu")
    target_desc = None
    for opt_key, opt_sd in bundle.items():
        state = opt_sd.get("state", {})
        for pidx, pstate in state.items():
            for buf, val in pstate.items():
                if torch.is_tensor(val) and val.is_floating_point():
                    pstate[buf] = val + 1.0
                    target_desc = f"{opt_key}[{pidx}].{buf}"
                    break
            if target_desc:
                break
        if target_desc:
            break
    if target_desc is None:
        raise AssertionError(
            "W1_FULLSTATE_TEST_CORRUPT_OPTIMIZER_NO_FLOAT_TENSOR_FOUND: "
            f"bundle_keys={list(bundle.keys())!r}")
    torch.save(bundle, optimizer_pt_path)
    _rewrite_manifest_sha(ckpt_dir, "optimizer.pt")
    return target_desc


def _rewrite_manifest_sha(ckpt_dir: str, fname: str) -> None:
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    new_sha = sha256_file(os.path.join(ckpt_dir, fname))
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["files"][fname] = new_sha
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, sort_keys=True, separators=(",", ": "), indent=2)


# ---------------------------------------------------------------------------
# --selftest
# ---------------------------------------------------------------------------

def _build_tiny_stepped_checkpoint(tmp: str, *, real_arch: dict,
                                    pretrain_contract: dict, seed: int) -> tuple:
    """Builds a tiny model+optimizer, runs ONE real train step (so
    optimizer momentum/exp_avg state is actually populated -- an
    unstepped optimizer's state_dict()['state'] is empty, which would
    make the optimizer-corruption negative fixture vacuous), saves a
    checkpoint, and returns (ckpt_dir, eval_x, eval_y) for the caller's
    own eval_loss_fn contrast check), plus pre_save_hashes captured
    DIRECTLY from the exact same in-memory objects handed to
    save_checkpoint (never a second, separately-computed read) -- the
    "exact pre-save state" reference the erratum names, only obtainable
    because this selftest controls the whole process end to end."""
    shard_dir = _build_tiny_shard_dir(tmp, vocab=real_arch["vocab"])
    loader = PackedShardLoader(
        shard_dir, real_arch["seq"], n_mtp=real_arch["n_mtp"],
        excluded_ranges=None)
    device = "cpu"
    model = build_real_model(real_arch, device, seed=seed)
    optimizers, base_lrs, _routing = build_split_optimizer(
        model, pretrain_contract, force_fallback=False,
        deviation_dir=os.path.join(tmp, "deviations"))
    _ce_impl, ce_fn = resolve_ce_impl(prefer_liger=False)
    x, y0, y_mtp = loader.batch(0, real_arch["batch"])
    apply_cosine_warmup(optimizers, base_lrs, 0, 40)
    mtp_cfg = pretrain_contract["objective"]["mtp_aux_heads"]
    train_step_matched_recipe(
        model, optimizers, ce_fn, x=x, y0=y0, y_mtp=y_mtp,
        mtp_enabled=bool(mtp_cfg["enabled"]), mtp_weight=mtp_cfg["weight"])

    xs_np, ys_np = [], []
    for j in range(real_arch["batch"]):
        xw, yw, _ = loader.window_np(1000 + j)
        xs_np.append(xw)
        ys_np.append(yw)
    eval_x = torch.as_tensor(np.stack(xs_np), dtype=torch.long, device=device)
    eval_y = torch.as_tensor(np.stack(ys_np), dtype=torch.long, device=device)

    model_state_pre_save = model.state_dict()
    optimizer_bundle_pre_save = save_optimizers_state(optimizers)
    rng_pre_save = capture_rng()
    pre_save_hashes = {
        "model": _hash_model_state(model_state_pre_save),
        "optimizer": _hash_optimizer_state(optimizer_bundle_pre_save),
        "rng": _hash_rng_state(rng_pre_save),
    }
    ckpt_dir = save_checkpoint(
        os.path.join(tmp, "run"), 10, model_state_pre_save,
        optimizer_bundle_pre_save, rng_pre_save,
        extra={"segment_id": "fullstate-verify-selftest"})
    return (ckpt_dir, eval_x, eval_y, model, eval_loss_fn(model, eval_x, eval_y),
            pre_save_hashes)


def _selftest() -> None:
    import shutil
    import tempfile
    print("[w1-fullstate-resume-verify-selftest] starting CPU-only synthetic-fixture selftest")
    with tempfile.TemporaryDirectory(prefix="w1fullstate-selftest-") as tmp:
        real_arch = _tiny_real_arch()
        pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)
        seed = 1234

        (ckpt_dir, eval_x, eval_y, _model, eval_loss_clean,
         pre_save_hashes) = _build_tiny_stepped_checkpoint(
            tmp, real_arch=real_arch, pretrain_contract=pretrain_contract, seed=seed)

        # --- (a) positive: unmodified fresh checkpoint hashes bit-exact
        # end to end, BOTH gates (load-path fidelity AND save fidelity
        # against the true pre-save in-memory state). ---
        result_pos = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=ckpt_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes)
        assert result_pos["verdict"] == "FULLSTATE_RESUME_EXACT", (
            f"W1_FULLSTATE_SELFTEST_POSITIVE_UNEXPECTED_VERDICT: {result_pos}")
        assert result_pos["load_path_exact"], result_pos["load_path_fidelity"]
        assert result_pos["save_fidelity_checked"] and result_pos["save_fidelity_exact"], (
            result_pos["save_fidelity"])
        assert result_pos["save_fidelity_disclosure"].startswith(
            "save_fidelity_checked=true"), result_pos["save_fidelity_disclosure"]
        assert result_pos["save_fidelity_top_claim_ok"] is True
        assert result_pos["source_top_claim_ok"] is True
        # runtime-input binds are inapplicable for a synthetic tiny
        # fixture (no external reconstruction-input files exist for it) --
        # this must be disclosed as None, never silently treated as pass.
        assert result_pos["runtime_binds_applicable"] is False
        assert result_pos["runtime_binds_satisfied"] is None
        assert result_pos["model"]["n_mtp_head_tensors_checked"] == real_arch["n_mtp"], (
            f"W1_FULLSTATE_SELFTEST_MTP_KEY_COUNT_MISMATCH: "
            f"expected {real_arch['n_mtp']} got {result_pos['model']}")
        assert result_pos["optimizer"]["n_optimizer_keys_checked"] >= 1
        print(f"[selftest] (a) POSITIVE leg PASS -- verdict={result_pos['verdict']} "
              f"n_tensors={result_pos['model']['n_tensors_checked']} "
              f"n_mtp_heads={result_pos['model']['n_mtp_head_tensors_checked']} "
              f"n_optimizer_keys={result_pos['optimizer']['n_optimizer_keys_checked']} "
              "-- load-path fidelity AND save fidelity (vs true pre-save "
              "in-memory state) both exact")

        # --- (b) negative: same-shape altered mtp_heads tensor, applied to
        # the ON-DISK FILE after save (simulating save-time/post-write
        # corruption -- the class the erratum names). Copy the clean
        # checkpoint (never mutate the fixture (a) verified) into a fresh
        # dir, corrupt one mtp_heads weight there, re-verify against the
        # SAME pre_save_hashes captured before any corruption existed. ---
        neg_mtp_dir = os.path.join(tmp, "ckpt-neg-mtp")
        shutil.copytree(ckpt_dir, neg_mtp_dir)
        corrupted_key = _corrupt_model_tensor_by_key_substring(neg_mtp_dir, "mtp_heads.")
        result_neg_mtp = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=neg_mtp_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes)
        assert result_neg_mtp["verdict"] == "FULLSTATE_RESUME_DIVERGED", (
            f"W1_FULLSTATE_SELFTEST_NEG_MTP_DID_NOT_FLIP: {result_neg_mtp}")
        assert not result_neg_mtp["save_fidelity_exact"]
        assert not result_neg_mtp["save_fidelity"]["model"]["exact"]
        assert corrupted_key in result_neg_mtp["save_fidelity"]["model"]["tensor_hash_mismatches"], (
            f"W1_FULLSTATE_SELFTEST_NEG_MTP_WRONG_KEY: corrupted={corrupted_key} "
            f"mismatches={result_neg_mtp['save_fidelity']['model']['tensor_hash_mismatches']}")
        # load-path fidelity ALONE (raw-on-disk vs load-apply-re-extract,
        # no pre-save reference) does NOT see this corruption -- both
        # sides of that comparison read the SAME already-corrupted file.
        # This is the honest limit of gate 1 and precisely why gate 2
        # (save fidelity against the true pre-save state) exists.
        assert result_neg_mtp["load_path_exact"], (
            "W1_FULLSTATE_SELFTEST_NEG_MTP_LOAD_PATH_UNEXPECTEDLY_FLIPPED: "
            f"{result_neg_mtp['load_path_fidelity']}")
        # Contrast proof: the OLD eval-loss-based check (what the landed
        # closure receipt actually gated on) is ALSO unchanged by this
        # exact corruption -- eval_loss_fn's forward path never touches
        # mtp_heads, so it silently passes the same defect this verifier
        # catches via the save-fidelity gate.
        m_state_corrupt, _o, _r, _mf = load_checkpoint(neg_mtp_dir)
        model_reload = build_real_model(real_arch, "cpu", seed=seed)
        model_reload.load_state_dict(m_state_corrupt, strict=True)
        eval_loss_corrupted = eval_loss_fn(model_reload, eval_x, eval_y)
        assert eval_loss_corrupted == eval_loss_clean, (
            "W1_FULLSTATE_SELFTEST_NEG_MTP_CONTRAST_UNEXPECTED: eval_loss_fn "
            "changed on an mtp_heads-only corruption -- contrast fixture invalid "
            f"(clean={eval_loss_clean} corrupted={eval_loss_corrupted})")
        print(f"[selftest] (b) NEGATIVE mtp_heads leg PASS -- verdict="
              f"{result_neg_mtp['verdict']} corrupted_key={corrupted_key} -- "
              f"save-fidelity gate FLIPPED (caught it); load-path-fidelity "
              "gate alone stayed exact (self-referential, cannot see it); "
              f"OLD eval_loss_fn check ALSO unchanged ({eval_loss_clean}) -- "
              "both prior checks silently pass this exact corruption")

        # --- (c) negative: same-shape altered optimizer tensor, same
        # post-save-corruption shape as (b). ---
        neg_opt_dir = os.path.join(tmp, "ckpt-neg-opt")
        shutil.copytree(ckpt_dir, neg_opt_dir)
        corrupted_desc = _corrupt_optimizer_tensor(neg_opt_dir)
        result_neg_opt = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=neg_opt_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes)
        assert result_neg_opt["verdict"] == "FULLSTATE_RESUME_DIVERGED", (
            f"W1_FULLSTATE_SELFTEST_NEG_OPT_DID_NOT_FLIP: {result_neg_opt}")
        assert not result_neg_opt["save_fidelity_exact"]
        assert not result_neg_opt["save_fidelity"]["optimizer"]["exact"]
        assert result_neg_opt["save_fidelity"]["optimizer"]["mismatches"], (
            result_neg_opt["save_fidelity"]["optimizer"])
        assert result_neg_opt["load_path_exact"], (
            "W1_FULLSTATE_SELFTEST_NEG_OPT_LOAD_PATH_UNEXPECTEDLY_FLIPPED: "
            f"{result_neg_opt['load_path_fidelity']}")
        # Contrast proof: the OLD optimizer_state_shape_parity check
        # (shape-only) is UNCHANGED (still reports shapes_match: True) on
        # this exact same-shape corruption.
        _m2, o_state_clean, _r2, _mf2 = load_checkpoint(ckpt_dir)
        _m3, o_state_corrupt, _r3, _mf3 = load_checkpoint(neg_opt_dir)
        old_parity = optimizer_state_shape_parity(o_state_corrupt, o_state_clean)
        assert old_parity["shapes_match"], (
            "W1_FULLSTATE_SELFTEST_NEG_OPT_CONTRAST_UNEXPECTED: "
            "optimizer_state_shape_parity flipped on a same-shape-only "
            f"corruption -- contrast fixture invalid ({old_parity})")
        print(f"[selftest] (c) NEGATIVE optimizer leg PASS -- verdict="
              f"{result_neg_opt['verdict']} corrupted={corrupted_desc} -- "
              "save-fidelity gate FLIPPED (caught it); load-path-fidelity "
              "gate alone stayed exact; OLD optimizer_state_shape_parity "
              f"check ALSO UNCHANGED (shapes_match={old_parity['shapes_match']}) "
              "on this exact same-shape corruption")

        # --- (d) REGRESSION: save_fidelity UNCHECKED (pre_save_hashes
        # omitted -- exactly what --live always does, since no same-
        # process pre-save reference exists for an already-completed
        # external process) on an otherwise-clean checkpoint must cap the
        # verdict at FULLSTATE_LOAD_PATH_EXACT, NEVER FULLSTATE_RESUME_
        # EXACT. This is the exact defect an external falsifier caught
        # live in the round-1 candidate (exit 0 / FULLSTATE_RESUME_EXACT
        # with save_fidelity_checked=false, source dirty) -- locked here
        # so the vacuous-default class cannot silently reappear. ---
        result_unchecked = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=ckpt_dir, seed=seed, device="cpu")
        assert result_unchecked["load_path_exact"], result_unchecked["load_path_fidelity"]
        assert not result_unchecked["save_fidelity_checked"]
        assert result_unchecked["save_fidelity_exact"] is None
        assert result_unchecked["verdict"] == "FULLSTATE_LOAD_PATH_EXACT", (
            "W1_FULLSTATE_SELFTEST_UNCHECKED_SAVE_FIDELITY_VACUOUS_PASS_"
            f"REGRESSION: expected FULLSTATE_LOAD_PATH_EXACT (round-1's "
            f"bug reached FULLSTATE_RESUME_EXACT here), got {result_unchecked}")
        print(f"[selftest] (d) REGRESSION unchecked-save-fidelity leg PASS "
              f"-- verdict={result_unchecked['verdict']} (capped, never "
              "the top claim, on an otherwise-clean checkpoint with no "
              "pre-save reference supplied -- reproduces and locks the "
              "round-1 falsifier finding)")

        # --- (e) REGRESSION: a MEASURED pin mismatch (this run's input
        # sha256 does not equal an independent closure receipt's
        # authoritative pin) must DIVERGE the verdict, never merely cap it
        # at LOAD_PATH_EXACT -- "measured and wrong" is worse evidence
        # than "not measured", and the two must not collapse together. ---
        fake_closure_receipt = {"preflight": {
            "pricing_receipt_sha256": "0" * 64,  # deliberately wrong pin
            "rung_manifest_sha256": "0" * 64,
            "real_arch": {"n_mtp": real_arch["n_mtp"]},
        }}
        pricing_receipt_stub = os.path.join(tmp, "pricing-stub.json")
        rung_manifest_stub = os.path.join(tmp, "rung-manifest-stub.json")
        with open(pricing_receipt_stub, "w", encoding="utf-8") as f:
            json.dump({"stub": True}, f)
        with open(rung_manifest_stub, "w", encoding="utf-8") as f:
            json.dump({"stub": True}, f)
        mismatched_binds = bind_runtime_reconstruction_inputs(
            pricing_receipt_stub, rung_manifest_stub, PRETRAIN_CONTRACT_PATH,
            fake_closure_receipt, "fake-closure.json")
        assert mismatched_binds["any_pin_mismatch"], mismatched_binds
        result_pin_mismatch = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=ckpt_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes,
            runtime_inputs_bound=mismatched_binds)
        assert result_pin_mismatch["verdict"] == "FULLSTATE_RESUME_DIVERGED", (
            f"W1_FULLSTATE_SELFTEST_PIN_MISMATCH_DID_NOT_DIVERGE: {result_pin_mismatch}")
        print(f"[selftest] (e) REGRESSION pin-mismatch leg PASS -- verdict="
              f"{result_pin_mismatch['verdict']} (measured-and-wrong input "
              "pin correctly DIVERGES, distinct from the merely-unmeasured "
              "case in leg (d))")

    print("W1_FULLSTATE_RESUME_VERIFY_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only synthetic-fixture selftest; never touches "
                         "the real checkpoint/GPU.")
    ap.add_argument("--live", action="store_true",
                    help="Verify the real #735 leg-A custody checkpoint. "
                         "CPU-only, no GPU, no training -- pure state-load "
                         "+ hash comparison.")
    ap.add_argument("--ckpt-dir", default=DEFAULT_CUSTODY_DIR)
    ap.add_argument("--pricing-receipt", default=DEFAULT_PRICING_RECEIPT)
    ap.add_argument("--rung-manifest", default=DEFAULT_RUNG_MANIFEST)
    ap.add_argument("--closure-receipt", default=DEFAULT_CLOSURE_RECEIPT,
                    help="landed closure receipt whose preflight.pricing_"
                         "receipt_sha256/rung_manifest_sha256 are the "
                         "authoritative pins this run's inputs are "
                         "equality-gated against.")
    ap.add_argument("--phase2-seed", type=int, default=PHASE2_SEED_HISTORICAL)
    ap.add_argument("--out-dir", default=None,
                    help="defaults to receipts/ember-c-scale/")
    return ap


def main(argv: "list[str] | None" = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        print("W1_FULLSTATE_RESUME_VERIFY_SELFTEST_PASS")
        return 0

    if not args.live:
        print("Nothing to do: pass --selftest or --live.")
        return 0

    repo_root = REPO_ROOT
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ckpt_dir = resolve(repo_root, args.ckpt_dir)
    pricing_receipt_path = resolve(repo_root, args.pricing_receipt)
    rung_manifest_path = resolve(repo_root, args.rung_manifest)

    custody_check = verify_custody_pins(ckpt_dir, EXPECTED_CUSTODY_SHA256)
    if not custody_check["pass"]:
        raise SystemExit(
            f"W1_FULLSTATE_CUSTODY_PIN_MISMATCH: {ckpt_dir!r} -- "
            f"{custody_check!r}")

    pricing_receipt = load_json(pricing_receipt_path)
    rung_receipt = derive_rung_receipt_from_manifest(rung_manifest_path)
    real_arch = derive_real_arch_config(pricing_receipt, rung_receipt)
    pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)

    # Repair-round binds (issue #758 review, round 2): the --live path
    # always computes all of these. Note the resulting verdict is
    # structurally capped at FULLSTATE_LOAD_PATH_EXACT for --live no
    # matter how these come out (see verify_fullstate_resume's grammar) --
    # --live never has a same-process pre-save reference to check, which
    # is the one precondition FULLSTATE_RESUME_EXACT cannot waive.
    source_commit = _git_source_commit(repo_root)
    closure_receipt_path = resolve(repo_root, args.closure_receipt)
    closure_receipt = load_json(closure_receipt_path)
    runtime_inputs_bound = bind_runtime_reconstruction_inputs(
        pricing_receipt_path, rung_manifest_path, PRETRAIN_CONTRACT_PATH,
        closure_receipt, closure_receipt_path)
    contract_consumed_fields_check = bind_contract_consumed_fields(
        pretrain_contract, closure_receipt)
    config_sha_bound = bind_real_arch_config_sha(real_arch, EXPECTED_CONFIG_SHA256)

    result = verify_fullstate_resume(
        real_arch=real_arch, pretrain_contract=pretrain_contract,
        ckpt_dir=ckpt_dir, seed=args.phase2_seed, device="cpu",
        runtime_inputs_bound=runtime_inputs_bound,
        config_sha_bound=config_sha_bound,
        source_commit=source_commit)

    receipt = {
        "ticket": "W1-FULLSTATE-RESUME-VERIFY", "ts": ts, "issue": ISSUE_REF,
        "schema": "w1-fullstate-resume-verify/v3",
        "sha_convention": SHA_CONVENTION,
        "ref": "issue #735 comment 4942417647 (coordinator erratum + "
               "scope-narrowing on the landed w1-baseline-replay-closure-"
               "20260711T025650Z.json receipt); supplements, never "
               "retro-edits, that receipt -- append-only evidence. v3 "
               "repair round 2: PR #758 external falsifier live run BLOCK "
               "(exit 0 / FULLSTATE_RESUME_EXACT with save_fidelity_"
               "checked=false, source dirty -- a round-1 vacuous-default "
               "verdict bug). Fixes: (1) verdict grammar now encodes "
               "'pre-save state unavailable => max claim is "
               "FULLSTATE_LOAD_PATH_EXACT, regardless of input binds' in "
               "code (save_fidelity_top_claim_ok requires CHECKED+exact, "
               "never defaults true when unchecked); (2) runtime-"
               "reconstruction-input pins are now equality-gated against "
               "the landed closure receipt's own preflight.pricing_"
               "receipt_sha256/rung_manifest_sha256 (round-1 only checked "
               "file-readability, never compared to anything); (3) a "
               "dirty source tree is bound via its exact diff sha256 and "
               "never qualifies for the top verdict.",
        "source_commit": source_commit,
        "real_arch": real_arch,
        "runtime_reconstruction_inputs": runtime_inputs_bound,
        "contract_consumed_fields_check": contract_consumed_fields_check,
        "real_arch_config_sha_check": config_sha_bound,
        "custody_pin_check": custody_check,
        "verification": result,
        "verdict": result["verdict"],
        "verdict_language": (
            f"{result['verdict']}. Both named defects in the landed "
            "closure receipt's resumability leg are closed regardless of "
            "verdict scope: (a) optimizer state is compared by VALUE "
            "(device-normalized tensor hash), never shape alone; (b) "
            "EVERY model state_dict tensor including mtp_heads is hashed, "
            "never only the primary-logits eval-loss path. "
            "FULLSTATE_RESUME_EXACT additionally REQUIRES ALL of: "
            "same-process pre-save hashes checked and exact "
            "(save_fidelity_top_claim_ok), canonical input pins exact "
            "(runtime_reconstruction_inputs equality-gated against the "
            "landed closure receipt's own preflight pins + real_arch_"
            "config_sha_check.pass), and a clean/bound source tree "
            "(source_top_claim_ok) -- pre-save state unavailable ALONE "
            "caps the claim at FULLSTATE_LOAD_PATH_EXACT regardless of "
            "how the input binds come out; a MEASURED mismatch on any of "
            "these (not merely an unmeasured one) instead DIVERGES the "
            "verdict entirely. This run's own evidence: "
            f"{result['save_fidelity_disclosure']} This receipt does not "
            "re-assert or widen the closure receipt's REPLAY_TRUSTWORTHY "
            "language (model BF16/FP32 replay + eval identity) -- it "
            "verifies the checkpoint IS a genuine bit-exact resume point, "
            "the claim the closure receipt's verdict string implied but "
            "its verifier did not check."),
        "api_spend_usd": 0.0, "paid_api_surface_used": False,
    }
    out_dir = (resolve(repo_root, args.out_dir) if args.out_dir else
               os.path.join(repo_root, "receipts", "ember-c-scale"))
    os.makedirs(out_dir, exist_ok=True)
    receipt_path = os.path.join(out_dir, f"w1-fullstate-resume-verify-{ts}.json")
    checked_write(receipt_path, receipt)
    print(json.dumps({
        "receipt": _relpath_or_abs(receipt_path, repo_root),
        "verdict": receipt["verdict"],
        "model_exact": result["model"]["exact"],
        "optimizer_exact": result["optimizer"]["exact"],
        "rng_exact": result["rng"]["exact"],
        "runtime_inputs_all_bound": runtime_inputs_bound["all_bound"],
        "runtime_inputs_any_pin_mismatch": runtime_inputs_bound["any_pin_mismatch"],
        "contract_consumed_fields_pass": contract_consumed_fields_check["pass"],
        "config_sha_pass": config_sha_bound["pass"],
        "source_working_tree_dirty": source_commit.get("working_tree_dirty"),
    }, indent=2))
    # Exit code reflects whether verification found a DEFECT (DIVERGED),
    # never whether it reached the theoretically-strongest possible claim.
    # --live is structurally incapable of reaching FULLSTATE_RESUME_EXACT
    # (no same-process pre-save reference ever exists for it) -- gating
    # exit 0 on that verdict specifically would make a fully clean --live
    # run always "fail", which is its own defect-in-disguise.
    return 0 if result["verdict"] != "FULLSTATE_RESUME_DIVERGED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
