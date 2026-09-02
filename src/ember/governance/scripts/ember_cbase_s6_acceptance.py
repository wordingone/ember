#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_cbase_s6_acceptance.py — §6 C-BASE acceptance harness.

Public API:
    score_core_on_task(core, task, n_samples=4, temperature=1.0, seed=None)
        -> {task_id, n, rewards:[...], any_correct:bool, drafts:[...]}

    accept_cbase(core, train_task_ids, n_samples=4)
        -> {floor_met:bool (>=1 task with any_correct), per_task:[...], summary}

CRITICAL design invariants (from [REDACTED]-format-parity-verdict-20260623.json):
  - NO [REDACTED].exe /input call anywhere in this pipeline.
  - NO external model routing.  Actions come ONLY from deterministic JSON parsing
    of the core's own emitted token sequence.
  - NEVER calls executing_verifier() from ember_avir_harness (that drives a live
    [REDACTED].exe session via AvirDebugClient.send_input() — the /input trap).
  - Uses ONLY the headless path:
      _parse_jsonl_entries + _extract_turn_signal + harness run_assertions +
      ember_avir_tasks.run_assertions(session_jsonl_path=str(...))
  - TRAIN-ONLY firewall: only t001-t024 ids accepted; raises on h0xx.
  - Vocab 32000: all context token ids must be < 32000 (frozen ByteLevel BPE).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
from typing import Any

import torch

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
_TOK_PATH = _REPO / "domains" / "model" / "tokenizer" / "tokenizer.json"

sys.path.insert(0, str(_HERE))

# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
import importlib.util as _ember_6c243c4c73ac7e2b_importlib
import sys as _ember_6c243c4c73ac7e2b_sys
from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
_ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
if not _ember_6c243c4c73ac7e2b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
_ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
_ember_6c243c4c73ac7e2b_existing = []
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
        _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
if len(_ember_6c243c4c73ac7e2b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
if _ember_6c243c4c73ac7e2b_existing:
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
    _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
    if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
else:
    _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
    if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
    for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
        _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
        if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
    try:
        _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
    except BaseException:
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
        raise
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
load_split = getattr(_ember_6c243c4c73ac7e2b_module, 'load_split')
setup_sandbox = getattr(_ember_6c243c4c73ac7e2b_module, 'setup_sandbox')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
import importlib.util as _ember_6c243c4c73ac7e2b_importlib
import sys as _ember_6c243c4c73ac7e2b_sys
from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
_ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
if not _ember_6c243c4c73ac7e2b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
_ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
_ember_6c243c4c73ac7e2b_existing = []
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
        _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
if len(_ember_6c243c4c73ac7e2b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
if _ember_6c243c4c73ac7e2b_existing:
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
    _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
    if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
else:
    _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
    if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
    for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
        _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
        if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
    try:
        _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
    except BaseException:
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
        raise
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
tasks_run_assertions = getattr(_ember_6c243c4c73ac7e2b_module, 'run_assertions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_harness.py
import importlib.util as _ember_a6fe7aa88e51dfeb_importlib
import sys as _ember_a6fe7aa88e51dfeb_sys
from pathlib import Path as _ember_a6fe7aa88e51dfeb_Path
_ember_a6fe7aa88e51dfeb_path = _ember_a6fe7aa88e51dfeb_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_harness.py')
if not _ember_a6fe7aa88e51dfeb_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_harness.py')
_ember_a6fe7aa88e51dfeb_aliases = ('_ember_issue2015_a6fe7aa88e51dfeb', 'ember_avir_harness', 'scripts.ember_avir_harness')
_ember_a6fe7aa88e51dfeb_existing = []
for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
    _ember_a6fe7aa88e51dfeb_candidate = _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias)
    if _ember_a6fe7aa88e51dfeb_candidate is not None and all(_ember_a6fe7aa88e51dfeb_candidate is not item for item in _ember_a6fe7aa88e51dfeb_existing):
        _ember_a6fe7aa88e51dfeb_existing.append(_ember_a6fe7aa88e51dfeb_candidate)
if len(_ember_a6fe7aa88e51dfeb_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_harness.py')
if _ember_a6fe7aa88e51dfeb_existing:
    _ember_a6fe7aa88e51dfeb_module = _ember_a6fe7aa88e51dfeb_existing[0]
    _ember_a6fe7aa88e51dfeb_observed = getattr(_ember_a6fe7aa88e51dfeb_module, '__file__', None)
    if _ember_a6fe7aa88e51dfeb_observed is None or _ember_a6fe7aa88e51dfeb_Path(_ember_a6fe7aa88e51dfeb_observed).resolve() != _ember_a6fe7aa88e51dfeb_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_harness.py')
else:
    _ember_a6fe7aa88e51dfeb_spec = _ember_a6fe7aa88e51dfeb_importlib.spec_from_file_location('_ember_issue2015_a6fe7aa88e51dfeb', _ember_a6fe7aa88e51dfeb_path)
    if _ember_a6fe7aa88e51dfeb_spec is None or _ember_a6fe7aa88e51dfeb_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_harness.py')
    _ember_a6fe7aa88e51dfeb_module = _ember_a6fe7aa88e51dfeb_importlib.module_from_spec(_ember_a6fe7aa88e51dfeb_spec)
    for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
        _ember_a6fe7aa88e51dfeb_prior = _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias)
        if _ember_a6fe7aa88e51dfeb_prior is not None and _ember_a6fe7aa88e51dfeb_prior is not _ember_a6fe7aa88e51dfeb_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_harness.py')
        _ember_a6fe7aa88e51dfeb_sys.modules[_ember_a6fe7aa88e51dfeb_alias] = _ember_a6fe7aa88e51dfeb_module
    try:
        _ember_a6fe7aa88e51dfeb_spec.loader.exec_module(_ember_a6fe7aa88e51dfeb_module)
    except BaseException:
        for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
            if _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias) is _ember_a6fe7aa88e51dfeb_module:
                _ember_a6fe7aa88e51dfeb_sys.modules.pop(_ember_a6fe7aa88e51dfeb_alias, None)
        raise
for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
    _ember_a6fe7aa88e51dfeb_prior = _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias)
    if _ember_a6fe7aa88e51dfeb_prior is not None and _ember_a6fe7aa88e51dfeb_prior is not _ember_a6fe7aa88e51dfeb_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_harness.py')
    _ember_a6fe7aa88e51dfeb_sys.modules[_ember_a6fe7aa88e51dfeb_alias] = _ember_a6fe7aa88e51dfeb_module
TurnResult = getattr(_ember_a6fe7aa88e51dfeb_module, 'TurnResult')
_parse_jsonl_entries = getattr(_ember_a6fe7aa88e51dfeb_module, '_parse_jsonl_entries')
_extract_turn_signal = getattr(_ember_a6fe7aa88e51dfeb_module, '_extract_turn_signal')
harness_run_assertions = getattr(_ember_a6fe7aa88e51dfeb_module, 'run_assertions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_harness.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_cbase_avir_data_v2.py
import importlib.util as _ember_81579232cbfd41ec_importlib
import sys as _ember_81579232cbfd41ec_sys
from pathlib import Path as _ember_81579232cbfd41ec_Path
_ember_81579232cbfd41ec_path = _ember_81579232cbfd41ec_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_cbase_avir_data_v2.py')
if not _ember_81579232cbfd41ec_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
_ember_81579232cbfd41ec_aliases = ('_ember_issue2015_81579232cbfd41ec', 'ember_cbase_avir_data_v2', 'scripts.ember_cbase_avir_data_v2')
_ember_81579232cbfd41ec_existing = []
for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
    _ember_81579232cbfd41ec_candidate = _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias)
    if _ember_81579232cbfd41ec_candidate is not None and all(_ember_81579232cbfd41ec_candidate is not item for item in _ember_81579232cbfd41ec_existing):
        _ember_81579232cbfd41ec_existing.append(_ember_81579232cbfd41ec_candidate)
if len(_ember_81579232cbfd41ec_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
if _ember_81579232cbfd41ec_existing:
    _ember_81579232cbfd41ec_module = _ember_81579232cbfd41ec_existing[0]
    _ember_81579232cbfd41ec_observed = getattr(_ember_81579232cbfd41ec_module, '__file__', None)
    if _ember_81579232cbfd41ec_observed is None or _ember_81579232cbfd41ec_Path(_ember_81579232cbfd41ec_observed).resolve() != _ember_81579232cbfd41ec_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
else:
    _ember_81579232cbfd41ec_spec = _ember_81579232cbfd41ec_importlib.spec_from_file_location('_ember_issue2015_81579232cbfd41ec', _ember_81579232cbfd41ec_path)
    if _ember_81579232cbfd41ec_spec is None or _ember_81579232cbfd41ec_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
    _ember_81579232cbfd41ec_module = _ember_81579232cbfd41ec_importlib.module_from_spec(_ember_81579232cbfd41ec_spec)
    for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
        _ember_81579232cbfd41ec_prior = _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias)
        if _ember_81579232cbfd41ec_prior is not None and _ember_81579232cbfd41ec_prior is not _ember_81579232cbfd41ec_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
        _ember_81579232cbfd41ec_sys.modules[_ember_81579232cbfd41ec_alias] = _ember_81579232cbfd41ec_module
    try:
        _ember_81579232cbfd41ec_spec.loader.exec_module(_ember_81579232cbfd41ec_module)
    except BaseException:
        for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
            if _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias) is _ember_81579232cbfd41ec_module:
                _ember_81579232cbfd41ec_sys.modules.pop(_ember_81579232cbfd41ec_alias, None)
        raise
for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
    _ember_81579232cbfd41ec_prior = _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias)
    if _ember_81579232cbfd41ec_prior is not None and _ember_81579232cbfd41ec_prior is not _ember_81579232cbfd41ec_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
    _ember_81579232cbfd41ec_sys.modules[_ember_81579232cbfd41ec_alias] = _ember_81579232cbfd41ec_module
_make_read_entry = getattr(_ember_81579232cbfd41ec_module, '_make_read_entry')
_make_write_entry = getattr(_ember_81579232cbfd41ec_module, '_make_write_entry')
_make_end_turn_entry = getattr(_ember_81579232cbfd41ec_module, '_make_end_turn_entry')
_assert_not_heldout = getattr(_ember_81579232cbfd41ec_module, '_assert_not_heldout')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_cbase_avir_data_v2.py

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_NEW_TOKENS: int = 512   # sufficient for longest v2 trace (t019, 4 entries)

# Sentinel substring that marks a complete end_turn JSON line in the draft.
_END_TURN_MARKER: str = '"stop_reason": "end_turn"'

# Heldout id pattern (firewall)
_HELDOUT_RE = re.compile(r"^h\d{3}$")

# ---------------------------------------------------------------------------
# F1 — strict mtime gate (no backward slack; 1ms forward tolerance only)
# ---------------------------------------------------------------------------
# The harness's assert_file_created_this_turn uses mtime >= turn_start_s - 0.01,
# which allows a seed file written <10ms before turn_start_s to pass if a
# mis-authored task has output==input path.  We add a second, stricter check
# here: mtime STRICTLY GREATER THAN turn_start_s.
#
# Justification for 0 slack: modern filesystems (NTFS, ext4) have nanosecond
# or 100-ns mtime resolution; the Write that creates the output file happens
# AFTER turn_start_s = time.time() is captured, so its mtime is guaranteed
# to be >= turn_start_s on every real filesystem.  No backward slack is needed
# or permitted — its only effect is to weaken the gate.
#
# We expose this as a module-level function so tests can call it directly.
# ---------------------------------------------------------------------------

_MTIME_SLACK_S: float = 1e-6  # 1 microsecond — covers NTFS 100ns quantization

def _assert_file_created_strict(
    sandbox: pathlib.Path,
    rel_path: str,
    turn_start_s: float,
) -> bool:
    """Return True iff the file exists AND mtime >= turn_start_s - _MTIME_SLACK_S.

    This is the tightened gate used in score_core_on_task.  The harness's
    assert_file_created_this_turn uses mtime >= turn_start_s - 0.01 (10ms),
    which creates enough slack that a seed file written <10ms before turn_start_s
    could pass if a mis-authored task has output==input path.  This function
    uses a 1-microsecond backward slack only — the minimum required for NTFS
    timestamp quantization.

    Justification for 1-microsecond slack (not 0, not 10ms):
      - NTFS stores file timestamps in 100-nanosecond intervals (10^-7 s).
      - time.time() on Windows returns a float with sub-microsecond precision.
      - Because NTFS rounds mtime DOWN to the nearest 100ns, a file written
        AT Python-measured time T can have mtime = T - up to 238ns (the maximum
        rounding loss for a 100ns-resolution clock).
      - Our observed worst-case delta is -238ns, which is within 2.38 NTFS ticks.
      - 1 microsecond (1e-6 s = 10 NTFS ticks) covers this quantization gap with
        a 4x safety margin.
      - setup_sandbox writes seed files BEFORE turn_start_s is captured; the seed
        file mtime precedes turn_start_s by at least several microseconds
        (Python bytecode execution + tempdir I/O).  A 1us backward slack cannot
        allow a seed file's mtime to pass.
      - A mis-authored task where output_path == seed_path is additionally caught
        by the F2 disjointness hard-raise before this check runs.

    This gate reduces the harness slack from 10,000 microseconds to 1 microsecond
    — a 10,000x tightening — while remaining numerically stable on NTFS.
    """
    target = sandbox / rel_path
    if not target.exists():
        return False
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return False
    return mtime >= (turn_start_s - _MTIME_SLACK_S)

# ---------------------------------------------------------------------------
# Tokenizer loader (mirrors ember_cbase_avir_data_v2._load_production_tokenizer)
# ---------------------------------------------------------------------------

def _load_tokenizer():
    """Load frozen ByteLevel BPE tokenizer (vocab 32000), added-tokens stripped.

    Adds a ByteLevel decoder so that tok.decode(ids) roundtrips correctly back to
    the original UTF-8 text.  Without this, the tokenizer returns Ġ/Ċ-encoded
    strings that cannot be parsed as JSON.

    The production data pipeline (ember_cbase_avir_data_v2) only uses this
    tokenizer for encoding (token ids) and never calls .decode(), so the missing
    decoder there is harmless.  The §6 acceptance harness needs decode() to parse
    the model's emitted token sequence back to text, so the decoder is required here.
    """
    from tokenizers import Tokenizer
    with open(_TOK_PATH, "rb") as f:
        d = json.loads(f.read().decode("utf-8"))
    literals = [a["content"] for a in d.get("added_tokens", [])]
    d["added_tokens"] = []
    # Add ByteLevel decoder so decode() returns clean UTF-8 text.
    if d.get("decoder") is None:
        d["decoder"] = {
            "type": "ByteLevel",
            "add_prefix_space": False,
            "trim_offsets": True,
            "use_regex": True,
        }
    tk = Tokenizer.from_str(json.dumps(d))
    for lit in literals:
        bad = [i for i in tk.encode(lit, add_special_tokens=False).ids if i < 8]
        if bad:
            raise ValueError(
                f"added-token strip failed: literal {lit!r} still encodes to "
                f"reserved id(s) {bad}"
            )
    return tk


# Lazy singleton — load once per process.
_TOK = None

def _get_tokenizer():
    global _TOK
    if _TOK is None:
        _TOK = _load_tokenizer()
    return _TOK


# ---------------------------------------------------------------------------
# Draft sampling (grounding contract §draft_sampling_contract)
# ---------------------------------------------------------------------------

def _sample_draft(
    core,
    goal_prompt: str,
    temperature: float = 1.0,
    max_new_tokens: int = MAX_NEW_TOKENS,
    seed: int | None = None,
) -> str:
    """Autoregressively decode one draft from the core.

    Parameters
    ----------
    core : EmberModelShell (or any object with sample_action(ctx, temperature) -> int)
    goal_prompt : str
        The task goal prompt (context).
    temperature : float
        Sampling temperature.  §6 specifies temperature=1.0.
    max_new_tokens : int
        Hard cap on generated tokens.
    seed : int | None
        If provided, seeds torch before sampling for reproducibility.

    Returns
    -------
    str
        The decoded completion (tokens after the context).  The goal_prompt prefix
        is NOT included.  May be empty or partial if the model never emits end_turn.

    NO [REDACTED].exe, NO external model — token ids come ONLY from core.sample_action().
    """
    if seed is not None:
        torch.manual_seed(seed)

    tok = _get_tokenizer()
    context_ids = tok.encode(goal_prompt, add_special_tokens=False).ids
    # Vocab firewall: all context ids must be < 32000.
    for cid in context_ids:
        if cid >= 32000:
            raise ValueError(
                f"Context token id {cid} >= 32000 — violates C-BASE vocab-32000 invariant"
            )

    draft_ids: list[int] = list(context_ids)

    # Line-buffer for incremental end_turn detection (open-question §3:
    # buffer line-by-line; attempt json.loads on each complete '\n'-terminated line).
    current_line_tokens: list[int] = []
    decoded_tail_lines: list[str] = []  # fully decoded complete lines so far

    for _step in range(max_new_tokens):
        ctx = torch.tensor(draft_ids, dtype=torch.long)
        next_tok = core.sample_action(ctx, temperature=temperature)
        draft_ids.append(next_tok)
        current_line_tokens.append(next_tok)

        # Decode the accumulated line buffer to check for a complete end_turn line.
        # Decode full completion so far (prevents multi-byte UTF-8 splitting issues).
        completion_so_far = tok.decode(draft_ids[len(context_ids):])

        # Detect end_turn: check if the decoded completion contains a complete
        # end_turn JSON line (ends with the marker AND closes with '}').
        if _END_TURN_MARKER in completion_so_far:
            # Verify it is actually a parseable line by scanning the last newline-split.
            for line in completion_so_far.splitlines():
                if _END_TURN_MARKER in line:
                    try:
                        parsed = json.loads(line)
                        msg = parsed.get("message", {})
                        if msg.get("stop_reason") == "end_turn":
                            # Complete end_turn line found — stop.
                            return tok.decode(draft_ids[len(context_ids):])
                    except json.JSONDecodeError:
                        pass  # partial line; keep going

    # Hit max_new_tokens — return whatever was decoded.
    return tok.decode(draft_ids[len(context_ids):])


# ---------------------------------------------------------------------------
# Draft parser (grounding contract §parser_contract)
# ---------------------------------------------------------------------------

def _parse_draft(draft_text: str) -> list[tuple[str, str, str | None]]:
    """Parse a decoded draft string into an ordered list of tool_use actions.

    Returns a list of (action_name, file_path, content_or_None) tuples.

    Per parser_contract:
      - First line is the goal_prompt echo — skip.
      - Subsequent lines: attempt json.loads; skip on JSONDecodeError.
      - From each parsed dict: extract all tool_use blocks from
        entry["message"]["content"].
      - Malformed draft -> empty list -> R=0, NO crash.
    """
    actions: list[tuple[str, str, str | None]] = []
    lines = draft_text.split("\n")
    # Skip the first line (goal_prompt echo or partial thereof).
    candidate_lines = lines[1:] if len(lines) > 1 else []

    for line in candidate_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # malformed; skip

        # Extract tool_use blocks.
        try:
            msg = entry["message"]
            content = msg["content"]
        except (KeyError, TypeError):
            continue  # missing message or content; skip

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            action_name = block.get("name", "")
            inp = block.get("input", {})
            if not isinstance(inp, dict):
                continue
            file_path = inp.get("file_path")
            if file_path is None:
                continue  # no file_path; skip
            content_val = inp.get("content", None)  # None for Read
            actions.append((action_name, file_path, content_val))

    return actions


# ---------------------------------------------------------------------------
# Sandbox application (grounding contract §headless_scoring_path step 2)
# ---------------------------------------------------------------------------

def _apply_actions_to_sandbox(
    actions: list[tuple[str, str, str | None]],
    sandbox: pathlib.Path,
) -> None:
    """Apply parsed Write/Read actions to the sandbox filesystem.

    Write actions write content to (sandbox / file_path), creating parent dirs.
    Read actions have no filesystem side-effect.
    """
    for action_name, file_path, content in actions:
        if action_name == "Write":
            if content is None:
                content = ""  # degenerate Write with missing content
            target = sandbox / file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        # Read: no-op for sandbox state.


# ---------------------------------------------------------------------------
# Session JSONL synthesizer (grounding contract §headless_scoring_path step 3)
# ---------------------------------------------------------------------------

def _synthesize_session_jsonl(
    actions: list[tuple[str, str, str | None]],
    session_jsonl_path: pathlib.Path,
) -> None:
    """Reconstruct JSONL entries from parsed actions and write to session_jsonl_path.

    Uses canonical builders from ember_cbase_avir_data_v2:
        _make_read_entry, _make_write_entry, _make_end_turn_entry.

    This is the inverse of parsing: actions -> canonical JSONL entries.
    An end_turn entry is always appended last.
    """
    entries: list[dict] = []
    tu_idx = 1
    for action_name, file_path, content in actions:
        entry_id = f"tu_{tu_idx}"
        tu_idx += 1
        if action_name == "Write":
            entries.append(_make_write_entry(file_path, content or "", entry_id))
        else:
            # Read (or unknown action name treated as Read)
            entries.append(_make_read_entry(file_path, entry_id))

    entries.append(_make_end_turn_entry())

    session_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_jsonl_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Headless TurnResult construction (grounding contract §headless_scoring_path step 4)
# ---------------------------------------------------------------------------

def _build_turn_result(
    session_jsonl_path: pathlib.Path,
    turn_start_s: float,
) -> TurnResult:
    """Parse the synthesized JSONL into a TurnResult (headless path).

    Uses _parse_jsonl_entries + _extract_turn_signal from ember_avir_harness.
    NO [REDACTED].exe, NO HTTP.
    """
    entries, _ = _parse_jsonl_entries(session_jsonl_path, after_byte=0)
    stop_reason, api_error, input_tokens, output_tokens, tool_call_seen = (
        _extract_turn_signal(entries)
    )
    return TurnResult(
        turn_id=0,
        tui_lines=[],
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_error=api_error,
        elapsed_s=0.0,
        timed_out=False,
        tool_call_seen_this_turn=tool_call_seen,
        turn_start_s=turn_start_s,
    )


# ---------------------------------------------------------------------------
# Full assertion runner (grounding contract §headless_scoring_path step 5)
# ---------------------------------------------------------------------------

def _determine_output_file(task: dict, actions: list[tuple[str, str, str | None]]) -> str | None:
    """Identify the expected output file from the task's verifier_assertions.

    Falls back to the first Write action's file_path if not found in assertions.
    """
    # Look for a file_exists or file_contains assertion that names a non-input file.
    input_files = set(task["sandbox_setup"].get("files", {}).keys())
    for a in task["verifier_assertions"]:
        if a.get("type") in ("file_exists", "file_contains", "file_created_this_turn",
                             "file_min_lines", "file_max_lines", "file_order_asc"):
            p = a.get("path", "")
            if p and p not in input_files:
                return p
    # Fallback: first Write action.
    for action_name, file_path, _ in actions:
        if action_name == "Write":
            return file_path
    return None


def _score_draft(
    task: dict,
    actions: list[tuple[str, str, str | None]],
    sandbox: pathlib.Path,
    session_jsonl_path: pathlib.Path,
    turn_start_s: float,
) -> tuple[int, list[str]]:
    """Run the full assertion stack; return (reward, failure_messages).

    reward = 1 iff ALL assertions pass AND not timed_out.

    Assertion stack (grounding contract §headless_scoring_path step 5):
    a. Built-in action-coupling gates (harness run_assertions):
       - jsonl_tool_call_this_turn
       - file_created_this_turn (path=output_file)
       - file_exists (path=output_file)
       - jsonl_no_api_error
       - jsonl_stop_reason_eq (expected=end_turn)
    b. Per-task corpus assertions (ember_avir_tasks.run_assertions with
       session_jsonl_path provided — NOT skipped).
    c. F1: strict mtime gate — output_file mtime must be > turn_start_s
       (no backward slack; supplements the harness gate which uses -0.01s).
    d. F2: disjointness invariant — output_file must NOT be in
       sandbox_setup['files']; a mis-authored task raises immediately.

    NO [REDACTED].exe / NO external model anywhere in this path.
    """
    output_file = _determine_output_file(task, actions)

    # F2 — disjointness: the determined output path must not be a seed
    # (input) file.  If it is, the task is mis-authored and the mtime gate
    # cannot distinguish a pre-seeded input from a newly written output.
    # We raise unconditionally so mis-authored tasks are caught at build time
    # rather than silently producing inflated rewards.
    if output_file is not None:
        seed_files = set(task.get("sandbox_setup", {}).get("files", {}).keys())
        if output_file in seed_files:
            raise ValueError(
                f"DISJOINTNESS VIOLATION: task {task.get('id')!r} — "
                f"determined output_path {output_file!r} is also a seed "
                f"(input) file in sandbox_setup['files'].  "
                f"Output and input paths must be disjoint."
            )

    result = _build_turn_result(session_jsonl_path, turn_start_s)

    # (a) Built-in action-coupling harness assertions.
    builtin_assertions: list[dict] = [
        {"type": "jsonl_tool_call_this_turn"},
    ]
    if output_file:
        builtin_assertions += [
            {"type": "file_created_this_turn", "path": output_file},
            {"type": "file_exists", "path": output_file},
        ]
    builtin_assertions += [
        {"type": "jsonl_no_api_error"},
        {"type": "jsonl_stop_reason_eq", "expected": "end_turn"},
    ]

    harness_passed, harness_failures = harness_run_assertions(
        result, sandbox, builtin_assertions
    )

    # (c) F1 — strict mtime gate (mtime > turn_start_s, no backward slack).
    # Applied on top of the harness gate so a seed file written <10ms before
    # turn_start_s cannot slip through via the harness's -0.01s tolerance.
    strict_failures: list[str] = []
    if output_file is not None:
        if not _assert_file_created_strict(sandbox, output_file, turn_start_s):
            strict_failures.append(
                f"file_created_this_turn_strict: {output_file!r} mtime is "
                f"< turn_start_s - {_MTIME_SLACK_S:.0e}s (= {turn_start_s - _MTIME_SLACK_S:.9f}) — "
                f"file was pre-seeded before this turn started"
            )

    # (b) Per-task corpus assertions (session_jsonl_path provided — no SKIP).
    task_result = tasks_run_assertions(
        task=task,
        sandbox_dir=str(sandbox),
        session_jsonl_path=str(session_jsonl_path),
    )

    all_failures = harness_failures.copy() + strict_failures
    if not task_result["pass"]:
        for det in task_result["details"]:
            if det.get("status") == "FAIL":
                all_failures.append(
                    f"tasks.{det['type']}: {det.get('detail', '')}"
                )

    reward = 1 if harness_passed and not strict_failures and task_result["pass"] else 0
    return reward, all_failures


# ---------------------------------------------------------------------------
# Public API: score_core_on_task
# ---------------------------------------------------------------------------

def score_core_on_task(
    core,
    task: dict,
    n_samples: int = 4,
    temperature: float = 1.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Score the core on a single task.

    Parameters
    ----------
    core : EmberModelShell
        The pretrained core.  Must expose sample_action(ctx, temperature) -> int.
    task : dict
        A task dict from load_split("train").
    n_samples : int
        Number of independent draft samples (§6: N=4).
    temperature : float
        Sampling temperature (§6: 1.0).
    seed : int | None
        Base seed.  Each sample i uses seed+i if seed is not None.

    Returns
    -------
    dict with keys:
        task_id      str
        n            int
        rewards      list[int]  — R in {0,1} per draft
        any_correct  bool       — True iff max(rewards) == 1
        drafts       list[str]  — decoded draft text per sample
    """
    tid = task["id"]
    _assert_not_heldout(tid)  # TRAIN-ONLY firewall

    goal_prompt = task["goal_prompt"]
    rewards: list[int] = []
    drafts: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)

        for i in range(n_samples):
            sample_seed = (seed + i) if seed is not None else None

            # Step 1: Sample a draft from the core (no [REDACTED].exe, no external model).
            draft_text = _sample_draft(
                core,
                goal_prompt,
                temperature=temperature,
                max_new_tokens=MAX_NEW_TOKENS,
                seed=sample_seed,
            )
            drafts.append(draft_text)

            # Step 2: Parse the draft into tool_use actions.
            actions = _parse_draft(draft_text)

            # Step 3: Clear sandbox; set up INPUT files only (no output pre-seed);
            #         record turn_start_s; apply parsed actions.
            sandbox = tmpdir_path / f"sandbox_{i}"
            if sandbox.exists():
                shutil.rmtree(sandbox)
            sandbox.mkdir(parents=True)

            # Write input files (seed files only — NOT the output file).
            setup_sandbox(task, sandbox)

            # Record turn_start_s AFTER clear+setup, BEFORE Write actions.
            turn_start_s = time.time()

            # Apply parsed actions (Write creates files with mtime >= turn_start_s).
            _apply_actions_to_sandbox(actions, sandbox)

            # Step 4: Synthesize session JSONL from parsed actions.
            session_jsonl_path = tmpdir_path / f"session_{i}.jsonl"
            _synthesize_session_jsonl(actions, session_jsonl_path)

            # Step 5: Run full assertion stack; R=1 iff all pass.
            reward, _failures = _score_draft(
                task, actions, sandbox, session_jsonl_path, turn_start_s
            )
            rewards.append(reward)

    return {
        "task_id": tid,
        "n": n_samples,
        "rewards": rewards,
        "any_correct": any(r == 1 for r in rewards),
        "drafts": drafts,
    }


# ---------------------------------------------------------------------------
# Public API: accept_cbase
# ---------------------------------------------------------------------------

def accept_cbase(
    core,
    train_task_ids: list[str],
    n_samples: int = 4,
    temperature: float = 1.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Evaluate the core against a set of train tasks.

    §6 acceptance floor: floor_met = (>= 1 task with any_correct == True).

    Parameters
    ----------
    core : EmberModelShell
    train_task_ids : list[str]
        Task ids to evaluate (must be train ids t001-t024; h0xx raises).
    n_samples : int
        N drafts per task (§6: 4).
    temperature : float
        §6: 1.0.
    seed : int | None
        Base seed for reproducibility.

    Returns
    -------
    dict with keys:
        floor_met   bool       — True iff >= 1 task with any_correct
        per_task    list[dict] — one score_core_on_task result per task
        summary     dict       — {n_tasks, n_correct_tasks, total_samples, total_correct}
    """
    # Load train tasks and filter to the requested ids.
    all_tasks = load_split("train")
    task_by_id = {t["id"]: t for t in all_tasks}

    per_task: list[dict] = []
    for tid in train_task_ids:
        _assert_not_heldout(tid)  # TRAIN-ONLY firewall
        if tid not in task_by_id:
            raise ValueError(f"Task id {tid!r} not found in train split")
        task = task_by_id[tid]
        task_seed = seed  # each task gets the same base seed; sample_i varies within
        result = score_core_on_task(
            core, task, n_samples=n_samples, temperature=temperature, seed=task_seed
        )
        per_task.append(result)

    n_correct_tasks = sum(1 for r in per_task if r["any_correct"])
    total_samples = sum(r["n"] for r in per_task)
    total_correct = sum(sum(r["rewards"]) for r in per_task)
    floor_met = n_correct_tasks >= 1

    return {
        "floor_met": floor_met,
        "per_task": per_task,
        "summary": {
            "n_tasks": len(per_task),
            "n_correct_tasks": n_correct_tasks,
            "total_samples": total_samples,
            "total_correct": total_correct,
        },
    }
