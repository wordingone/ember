#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_cbase_avir_augment.py — C-BASE [REDACTED]-task STRUCTURAL AUGMENTATION corpus.

Extends the banked v2 pipeline (ember_cbase_avir_data_v2.py).  For each of the
24 train tasks t001-t024, generates N DISTINCT variants by varying the sandbox
input content.  Each variant:

  1. Varies sandbox input (seeded RNG, variant index) — different VALUES, same
     task STRUCTURE (same file names, same operation, same output format).
  2. Recomputes the answer from the varied input via _compute_answer.
  3. Re-derives verifier_assertions with updated pinned values (file_contains
     "new_answer") so the assertion genuinely gates the variant answer.
  4. Synthesizes canonical [REDACTED].exe tool_use JSONL (via v2 _build_session_entries).
  5. Full-stack verification: clear sandbox, turn_start, write output, construct
     TurnResult, run harness + task assertions with the RE-DERIVED assertions.
     Only full-R=1 variants are kept.
  6. Renders pretrain text, tokenizes (vocab 32000), packs to shard.
  7. Round-trips via PackedShardLoader.

HARD RULES (same as v2, all retained):
  - TRAIN-ONLY FIREWALL: t001-t024 only.  Heldout h001-h020 raises.
  - answer is RECOMPUTED from varied input (not seed-echoed).
  - Vocab 32000; all token ids < 32000.
  - No GPU, no daemon — CPU only.
  - DO NOT edit ember_cbase_avir_data_v2.py, ember_avir_tasks.py,
    ember_avir_harness.py, or timeshare_pretrain.py.

Output shard: data/cbase_pretrain/cbase_avir_augment-00000.bin

Usage:
    python scripts/ember_cbase_avir_augment.py
    python scripts/ember_cbase_avir_augment.py --n 4
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import random
import re
import sys
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
_DATA_DIR = _REPO / "data" / "cbase_pretrain"
_TOK_PATH = _REPO / "domains" / "model" / "tokenizer" / "tokenizer.json"

sys.path.insert(0, str(_HERE))

# Import from v2 pipeline (read-only deps)
# issue2015 exact-local-import:src/ember/governance/scripts/ember_cbase_avir_data_v2.py
import importlib.util as _ember_81579232cbfd41ec_importlib
import sys as _ember_81579232cbfd41ec_sys
from pathlib import Path as _ember_81579232cbfd41ec_Path
_ember_81579232cbfd41ec_path = _ember_81579232cbfd41ec_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_cbase_avir_data_v2.py')
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
_assert_not_heldout = getattr(_ember_81579232cbfd41ec_module, '_assert_not_heldout')
_load_production_tokenizer = getattr(_ember_81579232cbfd41ec_module, '_load_production_tokenizer')
_compute_answer = getattr(_ember_81579232cbfd41ec_module, '_compute_answer')
_build_session_entries = getattr(_ember_81579232cbfd41ec_module, '_build_session_entries')
_make_read_entry = getattr(_ember_81579232cbfd41ec_module, '_make_read_entry')
_make_write_entry = getattr(_ember_81579232cbfd41ec_module, '_make_write_entry')
_make_end_turn_entry = getattr(_ember_81579232cbfd41ec_module, '_make_end_turn_entry')
_synthesize_turn_result = getattr(_ember_81579232cbfd41ec_module, '_synthesize_turn_result')
_build_harness_builtin_assertions = getattr(_ember_81579232cbfd41ec_module, '_build_harness_builtin_assertions')
_render_pretrain_text = getattr(_ember_81579232cbfd41ec_module, '_render_pretrain_text')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_cbase_avir_data_v2.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
import importlib.util as _ember_6c243c4c73ac7e2b_importlib
import sys as _ember_6c243c4c73ac7e2b_sys
from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
_ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_harness.py
import importlib.util as _ember_a6fe7aa88e51dfeb_importlib
import sys as _ember_a6fe7aa88e51dfeb_sys
from pathlib import Path as _ember_a6fe7aa88e51dfeb_Path
_ember_a6fe7aa88e51dfeb_path = _ember_a6fe7aa88e51dfeb_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_harness.py')
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
harness_run_assertions = getattr(_ember_a6fe7aa88e51dfeb_module, 'run_assertions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_harness.py  # noqa: E402
from timeshare_pretrain import write_packed_shard, PackedShardLoader  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
import importlib.util as _ember_6c243c4c73ac7e2b_importlib
import sys as _ember_6c243c4c73ac7e2b_sys
from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
_ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
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
_eat = _ember_6c243c4c73ac7e2b_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py  # noqa: E402

# ---------------------------------------------------------------------------
# TRAIN-ONLY FIREWALL (re-checked per-variant)
# ---------------------------------------------------------------------------

_HELDOUT_PATTERN = re.compile(r"^h\d{3}$")


def _check_firewall(task_id: str) -> None:
    if _HELDOUT_PATTERN.match(task_id):
        raise ValueError(
            f"FIREWALL VIOLATION: heldout task id {task_id!r} must never "
            f"enter the augmentation corpus. Train-only firewall triggered."
        )


# ---------------------------------------------------------------------------
# Sandbox content variation — deterministic per (task_id, variant_index, seed)
# ---------------------------------------------------------------------------

# Word lists for tasks that use names/words (no seed words reused verbatim)
_NAMES = [
    "alice", "bob", "carol", "dave", "eve", "frank", "grace", "henry",
    "iris", "jack", "kate", "[REDACTED]", "mia", "neil", "ora", "paul",
    "quinn", "rosa", "sam", "tina",
]
_WORDS = [
    "cedar", "birch", "maple", "oak", "pine", "elm", "ash", "yew",
    "lime", "beech", "alder", "walnut", "hazel", "rowan", "willow", "larch",
    "spruce", "fir", "thorn", "reed",
]
_ITEMS = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi",
    "rho", "sigma", "tau", "upsilon",
]
_LOG_MSGS = {
    "INFO": ["started", "running", "completed", "retry", "waiting", "resumed"],
    "ERROR": ["disk full", "timeout", "crash", "oom", "failed", "aborted"],
    "WARN": ["slow", "high load", "degraded", "noisy", "unstable"],
}
_TOKENS = [
    "north", "south", "east", "west", "up", "down", "left", "right",
    "inner", "outer", "front", "back", "near", "far", "high", "low",
]

# Words that start with vowels (for t009)
_VOWEL_WORDS = [
    "apple", "octopus", "umbrella", "ivy", "elephant", "ant", "eel",
    "orca", "iris", "oak",
]
# Words that do NOT start with vowels (for t009)
_CONSONANT_WORDS = [
    "basket", "table", "chair", "window", "floor", "roof", "wall",
    "brick", "stone", "plank",
]


def _vary_sandbox(task: dict, variant_idx: int, rng: random.Random) -> dict[str, str]:
    """Return a NEW files dict for the task's sandbox with varied content.

    Same file names as the seed; different values.  Produces content such that
    the COMPUTED ANSWER changes per variant.

    Args:
        task: original task dict
        variant_idx: 0-based variant index (used in content to ensure distinctness)
        rng: seeded Random instance for this (task, variant)

    Returns:
        dict mapping relpath -> content_string
    """
    tid = task["id"]
    _check_firewall(tid)

    if tid == "t001":
        # numbers.txt: 4 distinct integers, sum is different per variant
        # Use ranges that can't collide with seed (17+34+9+41=101)
        n = 4
        nums = [rng.randint(1, 99) for _ in range(n)]
        # Ensure sum != 101 (seed) by nudging first element if needed
        while sum(nums) == 101:
            nums[0] = rng.randint(1, 99)
        return {"numbers.txt": "\n".join(str(x) for x in nums) + "\n"}

    elif tid == "t002":
        # words.txt: 3-7 lines; count differs from 5 (seed)
        n = rng.choice([3, 4, 6, 7])
        words = rng.sample(_WORDS, n)
        return {"words.txt": "\n".join(words) + "\n"}

    elif tid == "t003":
        # values.txt: 5 integers; max changes
        vals = [rng.randint(10, 120) for _ in range(5)]
        # Ensure max != 87 (seed)
        while max(vals) == 87:
            vals[0] = rng.randint(10, 120)
        return {"values.txt": "\n".join(str(v) for v in vals) + "\n"}

    elif tid == "t004":
        # items.txt: 5 words that sort to a different first element than "apricot"
        candidates = rng.sample(_ITEMS, 5)
        # Shuffle to avoid always-sorted
        rng.shuffle(candidates)
        return {"items.txt": "\n".join(candidates) + "\n"}

    elif tid == "t005":
        # tokens.txt: 4-6 space-separated tokens on one line
        n = rng.choice([4, 5, 6])
        toks = rng.sample(_TOKENS, n)
        return {"tokens.txt": " ".join(toks) + "\n"}

    elif tid == "t006":
        # costs.txt: 4 item:price lines; total changes
        items = rng.sample(_ITEMS[:10], 4)
        prices = [rng.randint(1, 20) for _ in range(4)]
        # Ensure total != 14 (seed)
        while sum(prices) == 14:
            prices[0] = rng.randint(1, 20)
        lines = [f"{item}:{price}" for item, price in zip(items, prices)]
        return {"costs.txt": "\n".join(lines) + "\n"}

    elif tid == "t007":
        # pairs.txt: 3 key=value pairs; inverted form changes
        keys = rng.sample(["color", "shape", "size", "weight", "texture",
                            "height", "length", "width"], 3)
        vals = rng.sample(["blue", "round", "small", "light", "smooth",
                            "tall", "short", "wide", "narrow", "rough"], 3)
        lines = [f"{k}={v}" for k, v in zip(keys, vals)]
        return {"pairs.txt": "\n".join(lines) + "\n"}

    elif tid == "t008":
        # scores.txt: 4 name:score; winner must be deterministically different.
        # D2: use all 20 names (not just first 12) to maximise distinct winner space.
        names = rng.sample(_NAMES, 4)
        scores = [rng.randint(50, 99) for _ in range(4)]
        # Ensure max is unique (no tie) and winner != "bob" (seed) at least sometimes
        while len(set(scores)) != len(scores):
            scores = [rng.randint(50, 99) for _ in range(4)]
        lines = [f"{n}:{s}" for n, s in zip(names, scores)]
        return {"scores.txt": "\n".join(lines) + "\n"}

    elif tid == "t009":
        # tagged.txt: mix of vowel-starting and consonant-starting words
        # count of vowel-starting != 4 (seed)
        n_vowel = rng.choice([2, 3, 5, 6])
        n_consonant = rng.randint(2, 4)
        v_words = rng.sample(_VOWEL_WORDS, min(n_vowel, len(_VOWEL_WORDS)))
        c_words = rng.sample(_CONSONANT_WORDS, min(n_consonant, len(_CONSONANT_WORDS)))
        all_words = v_words + c_words
        rng.shuffle(all_words)
        return {"tagged.txt": "\n".join(all_words) + "\n"}

    elif tid == "t010":
        # sentences.txt: 3 lines with different word counts; total != 9 (seed)
        word_pool = _TOKENS + _WORDS[:10]
        lines = []
        total = 0
        for _ in range(3):
            n = rng.randint(2, 5)
            words = rng.sample(word_pool, n)
            lines.append(" ".join(words))
            total += n
        # Nudge if total == 9
        while total == 9:
            extra = rng.sample(word_pool, 1)
            lines[0] = lines[0] + " " + extra[0]
            total += 1
        return {"sentences.txt": "\n".join(lines) + "\n"}

    elif tid == "t011":
        # matrix.txt: 3x3 matrix; row sums differ
        rows = []
        for _ in range(3):
            row = [rng.randint(1, 15) for _ in range(3)]
            rows.append(row)
        # Ensure row sums are not all the same as seed (6, 15, 24)
        sums = [sum(r) for r in rows]
        while sums == [6, 15, 24]:
            rows[0] = [rng.randint(1, 15) for _ in range(3)]
            sums = [sum(r) for r in rows]
        return {"matrix.txt": "\n".join(" ".join(str(x) for x in r) for r in rows) + "\n"}

    elif tid == "t012":
        # lengths.txt: 3 words with different char lengths
        candidates = [w for w in _WORDS + _ITEMS if 2 <= len(w) <= 10]
        words = rng.sample(candidates, 3)
        # Ensure lengths != [3, 8, 2] (seed)
        while [len(w) for w in words] == [3, 8, 2]:
            words = rng.sample(candidates, 3)
        return {"lengths.txt": "\n".join(words) + "\n"}

    elif tid == "t013":
        # duplicates.txt: 6 lines with duplicates; unique count != 4 (seed)
        pool = rng.sample(_WORDS + _ITEMS, 8)
        n_unique = rng.choice([3, 5])
        base = pool[:n_unique]
        # fill to 6 lines by repeating some
        lines = list(base)
        while len(lines) < 6:
            lines.append(rng.choice(base))
        rng.shuffle(lines)
        return {"duplicates.txt": "\n".join(lines) + "\n"}

    elif tid == "t014":
        # ranges.txt: 3 low:high pairs; diffs change
        diffs_seed = [35, 16, 33]
        pairs = []
        for i in range(3):
            lo = rng.randint(1, 50)
            hi = lo + rng.randint(5, 50)
            pairs.append((lo, hi))
        # Ensure diffs != seed
        while [h - l for l, h in pairs] == diffs_seed:
            pairs[0] = (rng.randint(1, 50), rng.randint(51, 100))
        lines = [f"{lo}:{hi}" for lo, hi in pairs]
        return {"ranges.txt": "\n".join(lines) + "\n"}

    elif tid == "t015":
        # words2.txt: 6 lines with word repetitions; freq table changes
        pool = rng.sample(_WORDS, 4)
        # Build a different frequency pattern than cat:3, dog:2, bird:1
        counts = [rng.randint(1, 3) for _ in range(4)]
        lines = []
        for word, count in zip(pool, counts):
            lines.extend([word] * count)
        rng.shuffle(lines)
        return {"words2.txt": "\n".join(lines) + "\n"}

    elif tid == "t016":
        # coords.txt: 3 x,y pairs; products differ from [42, 33, 32] (seed)
        pairs = [(rng.randint(2, 12), rng.randint(2, 12)) for _ in range(3)]
        while [x * y for x, y in pairs] == [42, 33, 32]:
            pairs = [(rng.randint(2, 12), rng.randint(2, 12)) for _ in range(3)]
        lines = [f"{x},{y}" for x, y in pairs]
        return {"coords.txt": "\n".join(lines) + "\n"}

    elif tid == "t017":
        # log.txt: mix of INFO/ERROR/WARN; error count differs from 3 (seed)
        n_error = rng.choice([1, 2, 4, 5])
        n_info = rng.randint(1, 3)
        n_warn = rng.randint(0, 2)
        lines = []
        for _ in range(n_error):
            lines.append(f"ERROR: {rng.choice(_LOG_MSGS['ERROR'])}")
        for _ in range(n_info):
            lines.append(f"INFO: {rng.choice(_LOG_MSGS['INFO'])}")
        for _ in range(n_warn):
            lines.append(f"WARN: {rng.choice(_LOG_MSGS['WARN'])}")
        rng.shuffle(lines)
        return {"log.txt": "\n".join(lines) + "\n"}

    elif tid == "t018":
        # inventory.txt: 5 item:qty; low_stock_count (<10) differs from 3 (seed)
        items = rng.sample(_ITEMS[:10], 5)
        n_low = rng.choice([1, 2, 4])  # != 3 (seed)
        qtys = []
        for i in range(5):
            if i < n_low:
                qtys.append(rng.randint(1, 9))
            else:
                qtys.append(rng.randint(10, 50))
        rng.shuffle(qtys)
        lines = [f"{item}:{qty}" for item, qty in zip(items, qtys)]
        return {"inventory.txt": "\n".join(lines) + "\n"}

    elif tid == "t019":
        # a.txt and b.txt: different line counts; total != 5 (seed).
        # D2: the (na,nb) integer space is only ~12 pairs, which is too small for
        # n=8 with no dedup.  Enlarge by varying the LINE CONTENT too (sampled
        # from _WORDS), so each variant has distinct word lines even when na==nb
        # matches a prior variant.
        na = rng.randint(1, 4)
        nb = rng.randint(1, 4)
        while na + nb == 5:
            na = rng.randint(1, 4)
            nb = rng.randint(1, 4)
        # Use two non-overlapping sub-pools from _WORDS so a.txt and b.txt
        # words never collide with each other.
        a_pool = _WORDS[:10]   # first 10 tree names
        b_pool = _WORDS[10:]   # last 10 tree names
        a_lines = rng.sample(a_pool, min(na, len(a_pool)))
        b_lines = rng.sample(b_pool, min(nb, len(b_pool)))
        return {
            "a.txt": "\n".join(a_lines) + "\n",
            "b.txt": "\n".join(b_lines) + "\n",
        }

    elif tid == "t020":
        # numbers2.txt: 4 integers; average (1dp) differs from 25.0 (seed)
        nums = [rng.randint(5, 80) for _ in range(4)]
        avg = round(sum(nums) / len(nums), 1)
        while avg == 25.0:
            nums = [rng.randint(5, 80) for _ in range(4)]
            avg = round(sum(nums) / len(nums), 1)
        return {"numbers2.txt": "\n".join(str(n) for n in nums) + "\n"}

    elif tid == "t021":
        # tokens2.txt: 5 words; reversed+numbered output differs
        words = rng.sample(_WORDS, 5)
        return {"tokens2.txt": "\n".join(words) + "\n"}

    elif tid == "t022":
        # mapping.txt: 2 rename pairs; mv commands differ
        pool = _ITEMS[:12]
        src1, dst1 = rng.sample(pool, 2)
        src2, dst2 = rng.sample([w for w in pool if w not in (src1, dst1)], 2)
        return {"mapping.txt": f"{src1}.txt {dst1}.txt\n{src2}.csv {dst2}.csv\n"}

    elif tid == "t023":
        # grades.txt: 4 student:grade; average (rounded int) differs from 80 (seed)
        students = rng.sample(_NAMES[:8], 4)
        grades = [rng.randint(55, 99) for _ in range(4)]
        avg = round(sum(grades) / len(grades))
        while avg == 80:
            grades = [rng.randint(55, 99) for _ in range(4)]
            avg = round(sum(grades) / len(grades))
        lines = [f"{s}:{g}" for s, g in zip(students, grades)]
        return {"grades.txt": "\n".join(lines) + "\n"}

    elif tid == "t024":
        # flags.txt: 5 key:true/false; enabled_count differs from 3 (seed)
        keys = rng.sample(_ITEMS[:10], 5)
        n_true = rng.choice([0, 1, 2, 4, 5])  # != 3 (seed)
        bools = ["true"] * n_true + ["false"] * (5 - n_true)
        rng.shuffle(bools)
        lines = [f"{k}:{v}" for k, v in zip(keys, bools)]
        return {"flags.txt": "\n".join(lines) + "\n"}

    else:
        raise ValueError(f"_vary_sandbox: unrecognised task id {tid!r}")


# ---------------------------------------------------------------------------
# Assertion re-derivation
# ---------------------------------------------------------------------------

def _rederive_assertions(task: dict, answer: dict[str, str]) -> list[dict]:
    """Clone the task's verifier_assertions and update pinned file_contains values.

    For each file_contains assertion on the OUTPUT file, replace the 'text'
    with the corresponding substring from the recomputed answer.

    Returns the updated assertion list.  Task-structural assertions
    (file_exists, file_order_asc, file_min_lines, jsonl_*) are left unchanged.
    """
    output_file = list(answer.keys())[0]
    output_content = answer[output_file]

    # Build assertion map: output-file file_contains assertions get updated text
    new_assertions = []
    for orig in task["verifier_assertions"]:
        a = copy.deepcopy(orig)
        if (
            a.get("type") == "file_contains"
            and a.get("path") == output_file
        ):
            # Replace the pinned value with the recomputed answer content.
            # For single-value outputs (sum, max, winner, ...) the full content
            # minus trailing newline is the expected needle.
            # For multi-row outputs (row_sums, freq, etc.) the first line is
            # the most conservative needle (and the one v2 uses for t011/t015).
            # We instead verify the full stripped content is present.
            answer_stripped = output_content.rstrip("\n")
            # Some tasks check multiple lines individually (t011 checks "6","15","24")
            # We need to replace *each* original pinned needle with its updated equivalent.
            # Strategy: recompute all per-line / per-item checks from the new content.
            a["text"] = _derive_needle(task["id"], orig, output_content)
        new_assertions.append(a)
    return new_assertions


def _derive_needle(tid: str, orig_assertion: dict, output_content: str) -> str:
    """Derive the correct needle for a file_contains assertion given new content.

    For single-number outputs: the stripped content is the needle.
    For multi-row outputs where original text was a specific row value: match by
    row index (position in the sorted/ordered output).

    This function MUST produce a needle that is actually present in output_content.
    """
    output_lines = [l for l in output_content.splitlines() if l.strip()]
    orig_text = orig_assertion.get("text", "")

    # Tasks with labeled output (single assertion, full label)
    _LABELED_TASKS = {
        "t003": None,   # "max: N"
        "t008": None,   # "winner: NAME"
        "t009": None,   # "vowel_count: N"
        "t013": None,   # "unique_count: N"
        "t018": None,   # "low_stock_count: N"
        "t019": None,   # "total_lines: N"
        "t023": None,   # bare number
        "t024": None,   # "enabled_count: N"
    }
    if tid in _LABELED_TASKS:
        # Single-value output; needle is the full stripped content
        return output_content.rstrip("\n")

    # Tasks with multi-line single-value assertions (each line = one value)
    if tid in ("t011", "t014", "t016"):
        # Multiple file_contains assertions, one per row sum / diff / product.
        # The original needle was one of the computed values; map by position.
        # We can identify which row by matching the original needle to the seed value.
        # Since we re-derive all assertions, we return the corresponding new value.
        # Use index: the original assertion had orig_text = seed row value.
        # Map by position in output_lines (order is preserved).
        # We return the n-th line where n is the assertion's order in the assertion list.
        # Simpler approach: return the stripped line containing the original text's
        # positional match.  Since we don't have the position here, we return the
        # full output content and let the caller check — but we can't.
        # Best approach: return the n-th output line based on which assertion this is.
        # We reconstruct: all file_contains assertions for the output file in order.
        # Since we only have one assertion here, find which row this corresponds to
        # by checking if orig_text is a valid integer and returning the matching row.
        # For safety, just return the first row that IS in output_content.
        for line in output_lines:
            if line.strip():
                return line.strip()
        return output_content.rstrip("\n")

    if tid == "t007":
        # inverted.txt: two assertions for "red=color" and "large=size"
        # Match by position in lines
        for line in output_lines:
            if "=" in line:
                return line.strip()
        return output_lines[0].strip() if output_lines else ""

    if tid in ("t001", "t002", "t006", "t010", "t017", "t020"):
        # Single number output
        return output_content.rstrip("\n")

    if tid in ("t004", "t005"):
        # t004: file_contains "apricot" -> return first sorted word
        # t005: file_contains "north" -> return first token
        return output_lines[0].strip() if output_lines else ""

    if tid in ("t015",):
        # freq.txt: multiple file_contains assertions ("bird:1", "cat:3", "dog:2")
        # Return the first line
        return output_lines[0].strip() if output_lines else ""

    if tid == "t021":
        # reversed.txt: two assertions "1: fifth" and "5: first"
        # Return first line or last line based on orig_text
        if orig_text.startswith("1:") or orig_text.startswith("1: "):
            return output_lines[0].strip() if output_lines else ""
        else:
            return output_lines[-1].strip() if output_lines else ""

    if tid == "t022":
        # rename_script.sh: "mv foo.txt bar.txt"
        return output_lines[0].strip() if output_lines else ""

    if tid == "t012":
        # char_counts.txt: multiple per-word lengths; return any existing line
        for line in output_lines:
            if line.strip():
                return line.strip()

    # Default: return stripped full content
    return output_content.rstrip("\n")


def _rederive_all_file_contains(task: dict, answer: dict[str, str]) -> list[dict]:
    """Full re-derivation: produce one file_contains assertion per output line.

    For tasks like t011 (row_sums: 3 assertions) and t007 (2 assertions), we map
    each original file_contains assertion to the corresponding output line in order.

    D4 fix: if the varied output has MORE lines than the seed had assertions
    (e.g. t015: 4-word freq table vs. 3 seed assertions; t007: 3 pair inverse vs.
    2 seed assertions), we EXTEND the assertion list so every output line is gated.
    This closes the hole where a wrong final line would pass undetected.

    For single-value outputs the full stripped content is the needle (unchanged).
    """
    output_file = list(answer.keys())[0]
    output_content = answer[output_file]
    output_lines = [l.strip() for l in output_content.splitlines() if l.strip()]

    # Original file_contains assertions targeting the output file
    fc_assertions = [
        a for a in task["verifier_assertions"]
        if a.get("type") == "file_contains" and a.get("path") == output_file
    ]

    new_assertions = []
    fc_idx = 0

    for orig in task["verifier_assertions"]:
        a = copy.deepcopy(orig)
        if (
            a.get("type") == "file_contains"
            and a.get("path") == output_file
        ):
            if len(fc_assertions) == 1:
                # Single assertion: needle is the full stripped content
                a["text"] = output_content.rstrip("\n")
            elif len(output_lines) >= len(fc_assertions):
                # Map the fc_idx-th assertion to the fc_idx-th output line
                a["text"] = (
                    output_lines[fc_idx] if fc_idx < len(output_lines)
                    else output_content.rstrip("\n")
                )
            else:
                # Fewer output lines than original assertions — should not happen;
                # fall back to full content.
                a["text"] = output_content.rstrip("\n")
            fc_idx += 1
        new_assertions.append(a)

    # D4: if the varied output has MORE lines than the seed had file_contains
    # assertions, append extra assertions for the ungated lines.
    if len(fc_assertions) > 1 and len(output_lines) > len(fc_assertions):
        for extra_line in output_lines[len(fc_assertions):]:
            new_assertions.append({
                "type": "file_contains",
                "path": output_file,
                "text": extra_line,
            })

    return new_assertions


# ---------------------------------------------------------------------------
# Variant generation
# ---------------------------------------------------------------------------

def generate_variants(
    task: dict,
    n: int,
    base_seed: int = 42,
    verbose: bool = False,
) -> list[dict]:
    """Generate up to N full-R=1 variants for a single task.

    Returns list of dicts: {
        "task_id": str,
        "variant_idx": int,
        "sandbox_files": dict[str, str],
        "answer": dict[str, str],
        "entries": list[dict],
        "text": str,
        "token_ids": list[int],
        "r": float,
    }

    Only full-R=1 variants are included.  Failures are logged but not raised.
    """
    tid = task["id"]
    _check_firewall(tid)
    _assert_not_heldout(tid)

    # We need the tokenizer (caller loads it once and passes token_ids storage)
    # Since generate_variants is per-task, tokenizer is loaded externally.

    results = []
    dropped_indices = []
    # Track (sandbox_files JSON, answer JSON) pairs for dedup.
    _seen_fingerprints: set[str] = set()

    for vi in range(n):
        # D3: deterministic seed — sha256 of canonical f-string avoids PYTHONHASHSEED
        # randomisation so the shard is byte-reproducible across sessions.
        seed = int.from_bytes(
            hashlib.sha256(f"{tid}|{vi}|{base_seed}".encode()).digest()[:8], "big"
        )
        rng = random.Random(seed)

        # Step 1: vary sandbox content.
        # D2 dedup: if this seed produces a (sandbox, answer) fingerprint already seen,
        # resample with a fresh seed offset until unique or exhausted.
        _dedup_attempt = 0
        _max_dedup = 32
        varied_files = None
        while _dedup_attempt <= _max_dedup:
            if _dedup_attempt > 0:
                # Fresh seed offset to break the collision
                reseed = int.from_bytes(
                    hashlib.sha256(
                        f"{tid}|{vi}|{base_seed}|dedup{_dedup_attempt}".encode()
                    ).digest()[:8], "big"
                )
                rng = random.Random(reseed)
            try:
                candidate_files = _vary_sandbox(task, vi, rng)
            except Exception as exc:
                if verbose:
                    print(f"  [DROP] variant {vi}: _vary_sandbox raised {exc!r}")
                dropped_indices.append(vi)
                break
            # Quick fingerprint check (sandbox only — answer requires a tmpdir)
            fp_sandbox = json.dumps(candidate_files, sort_keys=True)
            if fp_sandbox not in _seen_fingerprints:
                varied_files = candidate_files
                break
            _dedup_attempt += 1

        if varied_files is None:
            # Either _vary_sandbox raised (already appended to dropped) or
            # all dedup attempts collided — drop this slot.
            if verbose and _dedup_attempt > _max_dedup:
                print(f"  [DROP] variant {vi}: dedup exhausted after {_max_dedup} resamples")
                dropped_indices.append(vi)
            continue

        # Step 2: build a modified task dict with the varied files
        varied_task = copy.deepcopy(task)
        varied_task["sandbox_setup"]["files"] = varied_files

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)

            # Set up sandbox with varied input (no output pre-seeded)
            sandbox = setup_sandbox(varied_task, tmpdir_path)

            # Step 3: recompute answer from varied input
            try:
                answer = _compute_answer(varied_task, sandbox)
            except Exception as exc:
                if verbose:
                    print(f"  [DROP] variant {vi}: _compute_answer raised {exc!r}")
                dropped_indices.append(vi)
                continue

            # D2 dedup: check full (sandbox+answer) fingerprint
            fp_full = json.dumps(varied_files, sort_keys=True) + "||" + json.dumps(answer, sort_keys=True)
            if fp_full in _seen_fingerprints:
                # The sandbox was unique but answer collided — rare; drop this slot.
                if verbose:
                    print(f"  [DROP] variant {vi}: answer collision after dedup")
                dropped_indices.append(vi)
                continue
            _seen_fingerprints.add(json.dumps(varied_files, sort_keys=True))
            _seen_fingerprints.add(fp_full)

            # Step 4: re-derive assertions with updated pinned values
            new_assertions = _rederive_all_file_contains(varied_task, answer)
            varied_task["verifier_assertions"] = new_assertions

            # Step 5: build JSONL entries
            try:
                entries = _build_session_entries(varied_task, answer)
            except Exception as exc:
                if verbose:
                    print(f"  [DROP] variant {vi}: _build_session_entries raised {exc!r}")
                dropped_indices.append(vi)
                continue

            # Record turn_start BEFORE writing output
            turn_start_s = time.time() - 0.001

            # Write synthesized JSONL
            session_jsonl_path = tmpdir_path / "session.jsonl"
            with session_jsonl_path.open("w", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(entry) + "\n")

            # Write output file to sandbox (simulates Write tool_use effect)
            output_file = list(answer.keys())[0]
            output_content = answer[output_file]
            target_path = sandbox / output_file
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(output_content, encoding="utf-8")

            # Step 6: full-stack verification
            # 6a: TurnResult via headless path
            result = _synthesize_turn_result(session_jsonl_path, turn_start_s)

            # 6b: harness built-in gates
            builtin_assertions = _build_harness_builtin_assertions(output_file)
            harness_passed, harness_failures = harness_run_assertions(result, sandbox, builtin_assertions)

            if not harness_passed:
                if verbose:
                    print(f"  [DROP] variant {vi}: harness failures: {harness_failures}")
                dropped_indices.append(vi)
                continue

            # 6c: task assertions (with re-derived assertions, session_jsonl_path not None)
            task_result = _eat.run_assertions(
                varied_task, sandbox,
                session_jsonl_path=str(session_jsonl_path),
            )
            if not task_result["pass"]:
                failed_details = [d for d in task_result["details"] if d.get("status") == "FAIL"]
                if verbose:
                    print(f"  [DROP] variant {vi}: task assertion failures: {failed_details}")
                dropped_indices.append(vi)
                continue

            # Full R=1 confirmed
            text = _render_pretrain_text(varied_task, entries)

            results.append({
                "task_id": tid,
                "variant_idx": vi,
                "sandbox_files": dict(varied_files),
                "answer": dict(answer),
                "entries": entries,
                "text": text,
                # token_ids filled by caller
                "r": 1.0,
            })

            if verbose:
                print(f"  [PASS] {tid} variant {vi}: R=1, answer={answer}")

    return results, dropped_indices


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    n: int = 8,
    output_dir: str | os.PathLike | None = None,
    verbose: bool = True,
    base_seed: int = 42,
) -> dict[str, Any]:
    """Run the full C-BASE [REDACTED]-task augmentation pipeline.

    For each train task t001-t024, generate N distinct variants.
    Packs all full-R=1 verified variant traces into a single shard.

    Args:
        n: number of variants per task (default 8)
        output_dir: directory for output shard (default data/cbase_pretrain/)
        verbose: print progress
        base_seed: base seed for RNG (default 42)

    Returns:
        result dict with counts and paths
    """
    out_dir = pathlib.Path(output_dir) if output_dir else _DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_split("train")

    # FIREWALL: check all task ids at entry
    for task in tasks:
        _check_firewall(task["id"])
        _assert_not_heldout(task["id"])

    tokenizer = _load_production_tokenizer()

    all_token_ids: list[int] = []
    total_emitted = 0
    total_full_R1 = 0
    dropped: list[str] = []
    per_task_results: list[dict] = []

    for task in tasks:
        tid = task["id"]
        _check_firewall(tid)

        if verbose:
            print(f"[{tid}] generating {n} variants...")

        variants, dropped_indices = generate_variants(
            task, n=n, base_seed=base_seed, verbose=verbose
        )

        for vi in dropped_indices:
            dropped.append(f"{tid}[{vi}]")

        for v in variants:
            # Tokenize
            text = v["text"]
            token_ids = tokenizer.encode(text, add_special_tokens=False).ids
            bad_ids = [i for i in token_ids if i >= 32000]
            if bad_ids:
                raise ValueError(f"Token ids >= 32000 in {tid} variant {v['variant_idx']}: {bad_ids[:5]}")

            all_token_ids.extend(token_ids)
            total_emitted += 1
            total_full_R1 += 1

        per_task_results.append({
            "id": tid,
            "variants_emitted": len(variants),
            "variants_dropped": len(dropped_indices),
        })

        if verbose:
            print(f"[{tid}] {len(variants)}/{n} variants R=1, {len(dropped_indices)} dropped")

    if not all_token_ids:
        raise RuntimeError("No token IDs produced — no verified variants to pack")

    # Pack into shard
    shard_path = out_dir / "cbase_avir_augment-00000.bin"
    write_packed_shard(str(shard_path), all_token_ids)

    if verbose:
        print(f"\nPacked {len(all_token_ids)} tokens into {shard_path}")
        print(f"Total variants emitted: {total_emitted}")
        print(f"Total full R=1: {total_full_R1}")
        print(f"Dropped: {dropped}")

    # Round-trip verification
    import numpy as _np_rt
    rt_arr = _np_rt.fromfile(str(shard_path), dtype="<u2")
    rt_first = list(rt_arr[:min(5, len(rt_arr))])
    rt_last = list(rt_arr[-min(5, len(rt_arr)):])
    expected_first = all_token_ids[:min(5, len(all_token_ids))]
    expected_last = all_token_ids[-min(5, len(all_token_ids)):]
    rt_token_count = int(len(rt_arr))
    rt_ok = (
        [int(x) for x in rt_first] == expected_first
        and [int(x) for x in rt_last] == expected_last
        and rt_token_count == len(all_token_ids)
    )

    if verbose:
        print(f"Round-trip: loaded {rt_token_count} tokens, ok={rt_ok}")

    if not rt_ok:
        raise RuntimeError(
            f"Round-trip FAILED: loaded {rt_token_count} != packed {len(all_token_ids)}"
        )

    return {
        "shard_path": str(shard_path),
        "shard_tokens": len(all_token_ids),
        "variants_emitted": total_emitted,
        "variants_full_R1": total_full_R1,
        "dropped": dropped,
        "roundtrip_ok": rt_ok,
        "per_task": per_task_results,
    }


# ---------------------------------------------------------------------------
# does_not_count self-check
# ---------------------------------------------------------------------------

def does_not_count_self_check() -> str:
    """Return a string confirming the augmentation does-not-count properties.

    This does NOT count as a test.  The TDD tests in
    test_ember_cbase_avir_augment.py are the evidence.
    """
    checks = [
        "ANSWERS_FROM_VARIED_INPUT: _vary_sandbox produces different VALUES per "
        "variant; _compute_answer reads the varied sandbox files (not seed); "
        "the variant's answer is derived from its own input, not echoed from seed.",
        "FULL_STACK_VERIFICATION: harness_run_assertions (action-coupling gates) + "
        "_eat.run_assertions (task assertions incl jsonl_tool_call_count_gte) with "
        "session_jsonl_path != None. No pre-seed, no skip.",
        "FIREWALL_ENFORCED: _check_firewall + _assert_not_heldout raises on h0xx "
        "pattern at entry and per-variant. Heldout tasks never enter the corpus.",
        "DISTINCT_VARIANTS: seeded RNG (hash(tid, vi, base_seed)) produces different "
        "content per variant_idx; assertion checks confirm different sandbox_files "
        "and different answers across variants.",
        "REDERIVED_ASSERTIONS: file_contains needles updated from recomputed answer; "
        "wrong answer fails the assertion (tested in TDD).",
    ]
    return "\n".join(checks)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="C-BASE [REDACTED] augmentation pipeline")
    parser.add_argument("--n", type=int, default=8, help="Variants per task (default: 8)")
    parser.add_argument("--seed", type=int, default=42, help="Base RNG seed (default: 42)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-task output")
    args = parser.parse_args()

    print(does_not_count_self_check())
    print()

    result = run_pipeline(n=args.n, verbose=not args.quiet, base_seed=args.seed)
    print("\n=== AUGMENTATION PIPELINE RESULT ===")
    print(f"shard_path:         {result['shard_path']}")
    print(f"shard_tokens:       {result['shard_tokens']}")
    print(f"variants_emitted:   {result['variants_emitted']}")
    print(f"variants_full_R1:   {result['variants_full_R1']}")
    print(f"dropped:            {result['dropped']}")
    print(f"roundtrip_ok:       {result['roundtrip_ok']}")
