# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""regenerate_cbase_heldout_slice.py -- rebuild the #760 frozen heldout slice
from clean, disjoint, real shard bytes.

WHY THIS EXISTS
----------------
The Wave-011 (PR #1228) frozen slice at manifests/cbase-heldout-slice-v1.json
draws all 16 windows from v0-00016.bin, global token range
[4294967296, 4563402752). The 2026-08-04 L3 fineweb_edu provenance audit
(#1436, src/ember/governance/scripts/fineweb_exclusion.py) proved the ruled-excluded fineweb_edu
range is [4055121325, 5723508974) -- which CONTAINS v0-00016.bin's entire
span. Every window in the committed frozen slice is 100% fineweb_edu content
now that the exclusion is ruled; scripts/cbase_heldout_eval.py's new
verify_slice_excludes_ruled_sources() correctly REFUSES it (proven: running
`python -B scripts/cbase_heldout_eval.py --validate-only --shard-dir
<real shard bytes>` against the real committed manifest exits 2 with
SLICE_OVERLAPS_EXCLUDED_SOURCE). The slice predates the ruling by 5 days
(PR #1228 merged 2026-07-30; the ruling audit is dated 2026-08-04) -- it was
correct when written and is invalidated by information that did not exist
yet, not by a bug in PR #1228.

This script picks a REPLACEMENT shard entirely outside every ruled-excluded
range, selects windows deterministically (even stride, no cherry-picking),
and verifies every property it can prove from receipts + real bytes: shard
identity (sha256 rehash), exclusion-clean (fineweb_exclusion, same module
the harness now consumes), and training-consumption disjointness (range
arithmetic against the highest window ceiling receipted anywhere in this
repo as of the run).

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
-------------------------------------------
It does not re-run n-gram contamination_recheck (the Jul-08 decontamination
batch's matcher, reused_matcher: "src/ember/governance/scripts/w1_collapse_control_run.py:
contamination_recheck"). That function is unreachable from live code:
w1_collapse_control_run.py imports timeshare_pretrain at module scope
(line 76), and timeshare_pretrain.py raises SystemExit at module scope
under the 2026-07-12 historical_only execution-denial lock -- importing
either file to call that function would violate the same lock this whole
codebase (and the #760 build spec) requires respecting. Porting
contamination_recheck into a standalone, non-execution-denied module
(mirroring how cbase_heldout_eval.py's own eval_loss mechanism was ported
out of that same file for Deliverable 1 of #760) is a named follow-up, not
attempted here.

Because of that, this script's output is a CANDIDATE manifest, not a
frozen one: manifests/cbase-heldout-slice-v1.json's schema hard-requires
selection_evidence.verdict == "CLEAN" (scripts/cbase_heldout_eval.py
load_frozen_slice_manifest, SLICE_SELECTION_VERDICT_INVALID), and "CLEAN"
in that field specifically denotes a passed n-gram decontamination check
(see receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json).
Writing "CLEAN" here without having run that check would be exactly the
fabricated-receipt failure mode this codebase's fail-closed culture exists
to prevent -- worse than leaving the slot UNMEASURABLE. This script
therefore writes selection_evidence.verdict = "DECONTAMINATION_NOT_PERFORMED"
and a companion receipt naming the blocker; it never touches the frozen
manifest path or FROZEN_SLICE_SHA256 in cbase_heldout_eval.py. A human (or
a follow-up task with the matcher ported) promotes the candidate once
decontamination is genuinely run.

CLI: --shard-dir (required, real shard bytes) --out (candidate manifest
path) --receipt-out (companion finding receipt) --window-count (default 16,
matching the invalidated slice's count for direct comparability) --dry-run
(compute + print, write nothing). Read-only against receipts/shard bytes
except for its own two output files. No GPU. No model. No checkpoint.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
NC = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# issue2015 exact-local-import:src/ember/governance/scripts/fineweb_exclusion.py
import importlib.util as _ember_d46db7ae0cab2934_importlib
import sys as _ember_d46db7ae0cab2934_sys
from pathlib import Path as _ember_d46db7ae0cab2934_Path
_ember_d46db7ae0cab2934_path = _ember_d46db7ae0cab2934_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fineweb_exclusion.py')
if not _ember_d46db7ae0cab2934_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fineweb_exclusion.py')
_ember_d46db7ae0cab2934_aliases = ('_ember_issue2015_d46db7ae0cab2934', 'fineweb_exclusion', 'scripts.fineweb_exclusion')
_ember_d46db7ae0cab2934_existing = []
for _ember_d46db7ae0cab2934_alias in _ember_d46db7ae0cab2934_aliases:
    _ember_d46db7ae0cab2934_candidate = _ember_d46db7ae0cab2934_sys.modules.get(_ember_d46db7ae0cab2934_alias)
    if _ember_d46db7ae0cab2934_candidate is not None and all(_ember_d46db7ae0cab2934_candidate is not item for item in _ember_d46db7ae0cab2934_existing):
        _ember_d46db7ae0cab2934_existing.append(_ember_d46db7ae0cab2934_candidate)
if len(_ember_d46db7ae0cab2934_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fineweb_exclusion.py')
if _ember_d46db7ae0cab2934_existing:
    _ember_d46db7ae0cab2934_module = _ember_d46db7ae0cab2934_existing[0]
    _ember_d46db7ae0cab2934_observed = getattr(_ember_d46db7ae0cab2934_module, '__file__', None)
    if _ember_d46db7ae0cab2934_observed is None or _ember_d46db7ae0cab2934_Path(_ember_d46db7ae0cab2934_observed).resolve() != _ember_d46db7ae0cab2934_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fineweb_exclusion.py')
else:
    _ember_d46db7ae0cab2934_spec = _ember_d46db7ae0cab2934_importlib.spec_from_file_location('_ember_issue2015_d46db7ae0cab2934', _ember_d46db7ae0cab2934_path)
    if _ember_d46db7ae0cab2934_spec is None or _ember_d46db7ae0cab2934_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fineweb_exclusion.py')
    _ember_d46db7ae0cab2934_module = _ember_d46db7ae0cab2934_importlib.module_from_spec(_ember_d46db7ae0cab2934_spec)
    for _ember_d46db7ae0cab2934_alias in _ember_d46db7ae0cab2934_aliases:
        _ember_d46db7ae0cab2934_prior = _ember_d46db7ae0cab2934_sys.modules.get(_ember_d46db7ae0cab2934_alias)
        if _ember_d46db7ae0cab2934_prior is not None and _ember_d46db7ae0cab2934_prior is not _ember_d46db7ae0cab2934_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fineweb_exclusion.py')
        _ember_d46db7ae0cab2934_sys.modules[_ember_d46db7ae0cab2934_alias] = _ember_d46db7ae0cab2934_module
    try:
        _ember_d46db7ae0cab2934_spec.loader.exec_module(_ember_d46db7ae0cab2934_module)
    except BaseException:
        for _ember_d46db7ae0cab2934_alias in _ember_d46db7ae0cab2934_aliases:
            if _ember_d46db7ae0cab2934_sys.modules.get(_ember_d46db7ae0cab2934_alias) is _ember_d46db7ae0cab2934_module:
                _ember_d46db7ae0cab2934_sys.modules.pop(_ember_d46db7ae0cab2934_alias, None)
        raise
for _ember_d46db7ae0cab2934_alias in _ember_d46db7ae0cab2934_aliases:
    _ember_d46db7ae0cab2934_prior = _ember_d46db7ae0cab2934_sys.modules.get(_ember_d46db7ae0cab2934_alias)
    if _ember_d46db7ae0cab2934_prior is not None and _ember_d46db7ae0cab2934_prior is not _ember_d46db7ae0cab2934_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fineweb_exclusion.py')
    _ember_d46db7ae0cab2934_sys.modules[_ember_d46db7ae0cab2934_alias] = _ember_d46db7ae0cab2934_module
fx = _ember_d46db7ae0cab2934_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/fineweb_exclusion.py      # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/token_shards_v0.py
import importlib.util as _ember_0c6ba95c4d327f51_importlib
import sys as _ember_0c6ba95c4d327f51_sys
from pathlib import Path as _ember_0c6ba95c4d327f51_Path
_ember_0c6ba95c4d327f51_path = _ember_0c6ba95c4d327f51_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'token_shards_v0.py')
if not _ember_0c6ba95c4d327f51_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/token_shards_v0.py')
_ember_0c6ba95c4d327f51_aliases = ('_ember_issue2015_0c6ba95c4d327f51', 'scripts.token_shards_v0', 'token_shards_v0')
_ember_0c6ba95c4d327f51_existing = []
for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
    _ember_0c6ba95c4d327f51_candidate = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
    if _ember_0c6ba95c4d327f51_candidate is not None and all(_ember_0c6ba95c4d327f51_candidate is not item for item in _ember_0c6ba95c4d327f51_existing):
        _ember_0c6ba95c4d327f51_existing.append(_ember_0c6ba95c4d327f51_candidate)
if len(_ember_0c6ba95c4d327f51_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
if _ember_0c6ba95c4d327f51_existing:
    _ember_0c6ba95c4d327f51_module = _ember_0c6ba95c4d327f51_existing[0]
    _ember_0c6ba95c4d327f51_observed = getattr(_ember_0c6ba95c4d327f51_module, '__file__', None)
    if _ember_0c6ba95c4d327f51_observed is None or _ember_0c6ba95c4d327f51_Path(_ember_0c6ba95c4d327f51_observed).resolve() != _ember_0c6ba95c4d327f51_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/token_shards_v0.py')
else:
    _ember_0c6ba95c4d327f51_spec = _ember_0c6ba95c4d327f51_importlib.spec_from_file_location('_ember_issue2015_0c6ba95c4d327f51', _ember_0c6ba95c4d327f51_path)
    if _ember_0c6ba95c4d327f51_spec is None or _ember_0c6ba95c4d327f51_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/token_shards_v0.py')
    _ember_0c6ba95c4d327f51_module = _ember_0c6ba95c4d327f51_importlib.module_from_spec(_ember_0c6ba95c4d327f51_spec)
    for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
        _ember_0c6ba95c4d327f51_prior = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
        if _ember_0c6ba95c4d327f51_prior is not None and _ember_0c6ba95c4d327f51_prior is not _ember_0c6ba95c4d327f51_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
        _ember_0c6ba95c4d327f51_sys.modules[_ember_0c6ba95c4d327f51_alias] = _ember_0c6ba95c4d327f51_module
    try:
        _ember_0c6ba95c4d327f51_spec.loader.exec_module(_ember_0c6ba95c4d327f51_module)
    except BaseException:
        for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
            if _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias) is _ember_0c6ba95c4d327f51_module:
                _ember_0c6ba95c4d327f51_sys.modules.pop(_ember_0c6ba95c4d327f51_alias, None)
        raise
for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
    _ember_0c6ba95c4d327f51_prior = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
    if _ember_0c6ba95c4d327f51_prior is not None and _ember_0c6ba95c4d327f51_prior is not _ember_0c6ba95c4d327f51_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
    _ember_0c6ba95c4d327f51_sys.modules[_ember_0c6ba95c4d327f51_alias] = _ember_0c6ba95c4d327f51_module
tsv = _ember_0c6ba95c4d327f51_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/token_shards_v0.py       # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_check.py
import importlib.util as _ember_2ad73f5df12b45ee_importlib
import sys as _ember_2ad73f5df12b45ee_sys
from pathlib import Path as _ember_2ad73f5df12b45ee_Path
_ember_2ad73f5df12b45ee_path = _ember_2ad73f5df12b45ee_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_check.py')
if not _ember_2ad73f5df12b45ee_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_check.py')
_ember_2ad73f5df12b45ee_aliases = ('_ember_issue2015_2ad73f5df12b45ee', 'receipt_check', 'scripts.receipt_check')
_ember_2ad73f5df12b45ee_existing = []
for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
    _ember_2ad73f5df12b45ee_candidate = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
    if _ember_2ad73f5df12b45ee_candidate is not None and all(_ember_2ad73f5df12b45ee_candidate is not item for item in _ember_2ad73f5df12b45ee_existing):
        _ember_2ad73f5df12b45ee_existing.append(_ember_2ad73f5df12b45ee_candidate)
if len(_ember_2ad73f5df12b45ee_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_check.py')
if _ember_2ad73f5df12b45ee_existing:
    _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_existing[0]
    _ember_2ad73f5df12b45ee_observed = getattr(_ember_2ad73f5df12b45ee_module, '__file__', None)
    if _ember_2ad73f5df12b45ee_observed is None or _ember_2ad73f5df12b45ee_Path(_ember_2ad73f5df12b45ee_observed).resolve() != _ember_2ad73f5df12b45ee_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_check.py')
else:
    _ember_2ad73f5df12b45ee_spec = _ember_2ad73f5df12b45ee_importlib.spec_from_file_location('_ember_issue2015_2ad73f5df12b45ee', _ember_2ad73f5df12b45ee_path)
    if _ember_2ad73f5df12b45ee_spec is None or _ember_2ad73f5df12b45ee_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_importlib.module_from_spec(_ember_2ad73f5df12b45ee_spec)
    for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
        _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
        if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
        _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
    try:
        _ember_2ad73f5df12b45ee_spec.loader.exec_module(_ember_2ad73f5df12b45ee_module)
    except BaseException:
        for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
            if _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias) is _ember_2ad73f5df12b45ee_module:
                _ember_2ad73f5df12b45ee_sys.modules.pop(_ember_2ad73f5df12b45ee_alias, None)
        raise
for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
    _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
    if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
receipt_check = _ember_2ad73f5df12b45ee_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py                # noqa: E402

SHARD_RECEIPT_NAME = "token-shards-v0-20260611T170047Z.json"
ISSUE = "#760"
SCALE = "W1_FROM_SCRATCH_PILOT_BASELINE"
RULE_SELECTION_ID = "EARLIEST_ADMISSIBLE_AFTER_EXCLUSION_FRONTIER_V1"
RULE_VERDICT = "RULE_DERIVED_EXCLUSION_CLEAN"
RULE_WINDOW_COUNT = 16
PRIOR_REFUSAL_SHA256 = "5573c2707be5a25ddaff878490a16699f905371f0882e5ebbed918e498ab910b"
EXCLUSION_KEYS = {"ticket","ts","shard_receipt","assembly_receipt","excluded_sources",
                  "excluded_token_ranges","loader_geometry","n_windows_unenforced",
                  "n_windows_enforced","n_windows_dropped","zero_overlap_verified",
                  "clean_content_tokens","stream_content_tokens","no_gpu",
                  "invariant_sha256","sha_convention","authority"}

# Highest max_training_window_index_at_ceiling receipted ANYWHERE in this
# repo as of 2026-08-05 (grepped across receipts/ -- the next-highest values
# found were 159 and 2495; every other disjointness receipt in the tree
# reuses this same W1 pilot number). window index is inclusive; the ceiling
# TOKEN is index*seq + BLOCK_LEN (the last training window's full read span,
# including its n_mtp+1 lookahead tail -- not (index+1)*seq, which undercounts
# by n_mtp+1 tokens). Re-grep before reusing this constant if training
# has advanced since this script was written -- it is a snapshot, not a
# live query, because no single aggregate "all consumption ranges" receipt
# exists yet (a real gap; see the emitted finding receipt's `notes`).
MAX_RECEIPTED_TRAINING_WINDOW_CEILING = 24527
TRAINING_CONSUMPTION_SOURCE = (
    "highest max_training_window_index_at_ceiling receipted anywhere in the "
    "repo as of 2026-08-05 (W1 pilot ceiling; see "
    "receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json and "
    "receipts/ember-c-scale/w1-collapse-control-20260707T*.json). No single "
    "aggregate receipt of every training run's consumed range exists; this "
    "is the maximum found by grep, not a closed-form proof of everything "
    "ever consumed -- disclosed as a limitation in the finding receipt.")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cumulative_shard_offsets(receipt: dict) -> tuple[dict, int]:
    """{shard_name: (global_start, global_end_exclusive)} in receipt shard
    order (shards are a flat concatenated stream -- PackedShardLoader reads
    them in listed order). Returns (offsets, total_tokens); total_tokens is
    cross-checked against the receipt's own total_stream_tokens by the
    caller, never trusted silently."""
    offsets = {}
    cursor = 0
    for s in receipt["shards"]:
        n = s["n_tokens"]
        offsets[s["name"]] = (cursor, cursor + n)
        cursor += n
    return offsets, cursor


def _lower_sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SystemExit(f"RULE_FREEZE_REFUSED: {code}")
    return value


def _load_exclusion_set(path: Path, expected_sha256: str, *, shard_dir: Path) -> dict:
    _lower_sha256(expected_sha256, "expected exclusion-set sha256 must be lowercase 64-hex")
    if _sha256(path) != expected_sha256:
        raise SystemExit("RULE_FREEZE_REFUSED: exclusion-set sha256 mismatch")
    value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(value, dict) or set(value) != EXCLUSION_KEYS:
        raise SystemExit("RULE_FREEZE_REFUSED: exclusion-set closed keys invalid")
    if (value.get("ticket") != "FINEWEB-EDU-EXCLUSION-PREFLIGHT"
            or value.get("zero_overlap_verified") is not True
            or value.get("no_gpu") is not True
            or value.get("invariant_sha256") != receipt_check.INVARIANT_SHA256
            or value.get("authority") != {
                "goal_id":"EMBER-02", "workstream_id":"EMBER-02A",
                "next_executed_outcome":"EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"}):
        raise SystemExit("RULE_FREEZE_REFUSED: exclusion-set authority invalid")
    geometry = value.get("loader_geometry")
    if geometry != {"seq": tsv.SEQ, "n_mtp": tsv.N_MTP, "block_len": tsv.BLOCK_LEN}:
        raise SystemExit("RULE_FREEZE_REFUSED: exclusion-set geometry drift")
    ranges = value.get("excluded_token_ranges")
    if (not isinstance(ranges, list) or not ranges
            or any(not isinstance(row, list) or len(row) != 2
                   or not all(isinstance(v, int) and not isinstance(v, bool) for v in row)
                   or row[1] <= row[0] for row in ranges)):
        raise SystemExit("RULE_FREEZE_REFUSED: exclusion-set ranges invalid")
    derived = fx.run_preflight(
        nc=str(NC), shard_dir=str(shard_dir), shard_receipt_name=value["shard_receipt"],
        assembly_name=value["assembly_receipt"], excluded_sources=set(value["excluded_sources"]),
        seq=tsv.SEQ, n_mtp=tsv.N_MTP)
    for key in ("shard_receipt","assembly_receipt","excluded_sources",
                "excluded_token_ranges","loader_geometry","zero_overlap_verified"):
        if derived[key] != value[key]:
            raise SystemExit(f"RULE_FREEZE_REFUSED: exclusion-set rederivation mismatch: {key}")
    return value


def select_earliest_admissible_windows(
        receipt: dict, *, excluded_ranges: list[tuple[int, int]],
        training_ranges: list[tuple[int, int]], seq: int, n_mtp: int,
        count: int = RULE_WINDOW_COUNT) -> list[dict]:
    """Canonical first `count` full-span-clean windows after exclusion frontier."""
    if count != RULE_WINDOW_COUNT:
        raise SystemExit("RULE_FREEZE_REFUSED: required window count is exactly 16")
    offsets, total = cumulative_shard_offsets(receipt)
    if total != receipt.get("total_stream_tokens"):
        raise SystemExit("RULE_FREEZE_REFUSED: shard token sum mismatch")
    block_len = seq + 1 + n_mtp
    frontier = max((end for _start, end in excluded_ranges), default=0)
    selected = []
    for shard in receipt["shards"]:
        shard_start, shard_end = offsets[shard["name"]]
        first_global = max(frontier, shard_start)
        first_global = ((first_global + seq - 1) // seq) * seq
        global_start = first_global
        while global_start + block_len <= shard_end:
            span = (global_start, global_start + block_len)
            if (not any(fx._overlaps(*span, es, ee) for es, ee in excluded_ranges)
                    and not any(fx._overlaps(*span, ts, te) for ts, te in training_ranges)):
                local_start = global_start - shard_start
                selected.append({
                    "window_index": global_start // seq,
                    "shard_name": shard["name"],
                    "shard_token_start": local_start,
                    "shard_token_end_exclusive": local_start + seq + 1,
                    "source_shard_token_end_exclusive": local_start + block_len,
                    "global_token_start": global_start,
                    "global_token_end_exclusive": global_start + seq + 1,
                    "source_global_token_end_exclusive": global_start + block_len,
                })
                if len(selected) == count:
                    return selected
            global_start += seq
    raise SystemExit(f"RULE_FREEZE_REFUSED: fewer than 16 admissible windows ({len(selected)})")


def build_rule_derived_candidate(*, shard_dir: Path, exclusion_set_receipt: Path,
                                 expected_exclusion_set_sha256: str,
                                 selection_receipt_path: str) -> tuple[dict, dict]:
    exclusion = _load_exclusion_set(
        exclusion_set_receipt, expected_exclusion_set_sha256, shard_dir=shard_dir)
    shard_receipt_path = NC / "receipts" / exclusion["shard_receipt"]
    shard_receipt = json.loads(shard_receipt_path.read_text(encoding="utf-8"))
    violations = tsv.validate_shards_receipt(
        shard_receipt, str(NC), shard_dir_override=str(shard_dir))
    if violations:
        raise SystemExit(f"RULE_FREEZE_REFUSED: shard receipt invalid: {violations}")
    training_end = MAX_RECEIPTED_TRAINING_WINDOW_CEILING * tsv.SEQ + tsv.BLOCK_LEN
    training_ranges = [(0, training_end)]
    ranges = [tuple(row) for row in exclusion["excluded_token_ranges"]]
    windows = select_earliest_admissible_windows(
        shard_receipt, excluded_ranges=ranges, training_ranges=training_ranges,
        seq=tsv.SEQ, n_mtp=tsv.N_MTP)
    offsets, _ = cumulative_shard_offsets(shard_receipt)
    used_names = list(dict.fromkeys(row["shard_name"] for row in windows))
    shard_by_name = {row["name"]: row for row in shard_receipt["shards"]}
    used = []
    for name in used_names:
        meta = shard_by_name[name]; start, end = offsets[name]
        if _sha256(shard_dir / name) != meta["sha256"]:
            raise SystemExit(f"RULE_FREEZE_REFUSED: shard identity mismatch: {name}")
        used.append({"name":name,"sha256":meta["sha256"],"n_tokens":meta["n_tokens"],
                     "global_token_start":start,"global_token_end_exclusive":end})
    exclusion_ranges_sha = hashlib.sha256(json.dumps(
        exclusion["excluded_token_ranges"], sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    receipt = {
        "ticket":"ISSUE-1433-RULE-DERIVED-HELDOUT-FREEZE", "issue":"#1433",
        "ts":datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "schema":"cbase-heldout-rule-freeze/v1", "status":"RULE_DERIVED_EXCLUSION_CLEAN",
        "selection_rule_id":RULE_SELECTION_ID,
        "selection_rule":"first 16 ascending full-span admissible windows at or after max exclusion end",
        "exclusion_set":{"path":str(exclusion_set_receipt.relative_to(NC)).replace("\\","/"),
                         "sha256":expected_exclusion_set_sha256,
                         "ranges_sha256":exclusion_ranges_sha,
                         "excluded_token_ranges":exclusion["excluded_token_ranges"]},
        "source_receipts":{"shard":{"path":f"receipts/{exclusion['shard_receipt']}",
                                      "sha256":_sha256(shard_receipt_path)},
                           "assembly":{"path":f"receipts/{exclusion['assembly_receipt']}",
                                        "sha256":_sha256(NC/'receipts'/exclusion['assembly_receipt'])}},
        "sequence":{"seq":tsv.SEQ,"n_mtp":tsv.N_MTP,"block_len":tsv.BLOCK_LEN},
        "training_ranges":[[0,training_end]], "windows":windows,
        "previous_refusal":{"sha256":PRIOR_REFUSAL_SHA256},
        "producer":{"path":"src/ember/governance/scripts/regenerate_cbase_heldout_slice.py",
                    "sha256":_sha256(Path(__file__)),"source_commit":_git_head(NC)},
        "invariant_sha256":receipt_check.INVARIANT_SHA256,
        "sha_convention":"bytes on disk as-is (binary read, no line-ending normalization)",
        "authority":{"goal_id":"EMBER-02","workstream_id":"EMBER-02A",
                     "next_executed_outcome":"EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"},
        "claim_boundary":"Intermediate rule-derived exclusion-clean freeze only; real exact-window n-gram scan is required before scoring or promotion."
    }
    combined = hashlib.sha256(json.dumps(
        [row["sha256"] for row in used], separators=(",", ":")).encode("ascii")).hexdigest()
    manifest = {
        "schema":"cbase-heldout-slice/v1","issue":ISSUE,"captured_public_master":_git_head(NC),
        "source_corpus":{"combined_sha256":combined,
                         "receipt_path":f"receipts/{exclusion['shard_receipt']}",
                         "receipt_sha256":_sha256(shard_receipt_path),"shards":used},
        "selection_evidence":{"path":selection_receipt_path,"sha256":"0"*64,
                              "batch_sha256":"0"*64,"verdict":RULE_VERDICT},
        "sequence":{"dtype":"<u2","seq":tsv.SEQ,"n_mtp":tsv.N_MTP,
                    "separator_id":tsv.SEPARATOR_ID,"packed_bytes_per_token":2,
                    "scoring":"primary_next_token_only"},
        "training_consumption":[{"source":TRAINING_CONSUMPTION_SOURCE,
                                 "window_start":0,"window_end_exclusive":MAX_RECEIPTED_TRAINING_WINDOW_CEILING+1,
                                 "global_token_start":0,"global_token_end_exclusive":training_end}],
        "windows":windows,"expected_scored_token_count":len(windows)*tsv.SEQ,"scale":SCALE,
        "availability":{"status":"AVAILABLE","missing":[],"note":"Rule-derived candidate; named shard bytes rehashed."},
        "claim_boundary":"Intermediate RULE_DERIVED_EXCLUSION_CLEAN candidate only; n-gram scan, scoring, promotion, registry and closure remain prohibited."
    }
    return manifest, receipt


def _write_json_no_overwrite(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): raise SystemExit(f"RULE_FREEZE_REFUSED: output exists: {path}")
    fd, staged = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            json.dump(value,stream,sort_keys=True,separators=(",",":")); stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        os.link(staged,path)
    finally:
        try: os.unlink(staged)
        except FileNotFoundError: pass


def pick_clean_shard(receipt: dict, excluded_ranges: list[tuple[int, int]]) -> tuple[str, int, int]:
    """The first WHOLLY-clean shard (its entire global range outside every
    excluded range) at or after the excluded region -- not merely a clean
    shard anywhere, so the choice stays maximally far from the low end of
    the stream where training consumption concentrates. Raises if none."""
    offsets, total = cumulative_shard_offsets(receipt)
    if total != receipt["total_stream_tokens"]:
        raise SystemExit(f"REGEN_REFUSED: sum(shard n_tokens) {total} != "
                         f"receipt total_stream_tokens {receipt['total_stream_tokens']}")
    exclusion_end = max((ee for _es, ee in excluded_ranges), default=0)
    candidates = [(name, s, e) for name, (s, e) in offsets.items() if s >= exclusion_end]
    for name, start, end in sorted(candidates, key=lambda row: row[1]):
        if not any(fx._overlaps(start, end, es, ee) for es, ee in excluded_ranges):
            return name, start, end
    raise SystemExit("REGEN_REFUSED: no shard is entirely outside every excluded range")


def select_windows(shard_name: str, shard_start: int, shard_len: int, *,
                   seq: int, n_mtp: int, count: int, training_ceiling_token: int) -> list[dict]:
    """`count` windows, evenly strided across the shard's usable window
    range -- deterministic and reproducible (same inputs always produce the
    same windows), no manual cherry-picking. Every window is asserted past
    the training ceiling before being accepted; this is defense in depth
    (the shard was already chosen far past it), not the primary proof."""
    block_len = seq + 1 + n_mtp
    n_windows_in_shard = (shard_len - block_len) // seq + 1
    if n_windows_in_shard < count:
        raise SystemExit(f"REGEN_REFUSED: shard {shard_name} too small for "
                         f"{count} windows (only {n_windows_in_shard} available)")
    stride = n_windows_in_shard // count
    out = []
    for k in range(count):
        local_index = k * stride
        local_start = local_index * seq
        global_start = shard_start + local_start
        if global_start < training_ceiling_token:
            raise SystemExit(f"REGEN_REFUSED: window at global {global_start} is "
                             f"below the training ceiling {training_ceiling_token}")
        window_index = global_start // seq
        out.append({
            "window_index": window_index,
            "shard_name": shard_name,
            "shard_token_start": local_start,
            "shard_token_end_exclusive": local_start + seq + 1,
            "source_shard_token_end_exclusive": local_start + block_len,
            "global_token_start": global_start,
            "global_token_end_exclusive": global_start + seq + 1,
            "source_global_token_end_exclusive": global_start + block_len,
        })
    return out


def build_candidate(*, shard_dir: Path, window_count: int) -> tuple[dict, dict]:
    receipt_path = NC / "receipts" / SHARD_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    violations = tsv.validate_shards_receipt(receipt, str(NC), shard_dir_override=str(shard_dir))
    if violations:
        raise SystemExit(f"REGEN_REFUSED: {SHARD_RECEIPT_NAME} FAILS validation "
                         f"against on-disk shard bytes: {violations}")
    excluded_sources = fx.ruled_excluded_sources(str(NC))
    assembly_name = receipt["premises"]["assembly_receipt"]["name"]
    excluded_ranges, reason = fx.enforcement_for_validated_receipt(
        receipt, nc=str(NC), assembly_name=assembly_name, excluded_sources=excluded_sources)
    if not excluded_ranges:
        raise SystemExit(f"REGEN_REFUSED: derived zero excluded ranges ({reason}) "
                         "-- refusing to proceed on an unproven exclusion set")

    shard_name, shard_start, shard_end = pick_clean_shard(receipt, excluded_ranges)
    shard_meta = next(s for s in receipt["shards"] if s["name"] == shard_name)
    on_disk_sha = _sha256(shard_dir / shard_name)
    if on_disk_sha != shard_meta["sha256"]:
        raise SystemExit(f"REGEN_REFUSED: {shard_name} on-disk sha256 {on_disk_sha[:12]} "
                         f"!= receipted {shard_meta['sha256'][:12]}")

    seq, n_mtp = tsv.SEQ, tsv.N_MTP
    training_ceiling_token = MAX_RECEIPTED_TRAINING_WINDOW_CEILING * seq + tsv.BLOCK_LEN
    windows = select_windows(shard_name, shard_start, shard_meta["n_tokens"], seq=seq, n_mtp=n_mtp,
                             count=window_count, training_ceiling_token=training_ceiling_token)
    for row in windows:
        gs, ge = row["global_token_start"], row["source_global_token_end_exclusive"]
        for es, ee in excluded_ranges:
            if fx._overlaps(gs, ge, es, ee):
                raise SystemExit(f"REGEN_REFUSED: selected window {row['window_index']} "
                                 f"overlaps excluded range [{es},{ee}) -- selection bug")

    combined_sha256 = hashlib.sha256(json.dumps(
        [shard_meta["sha256"]], separators=(",", ":")).encode("ascii")).hexdigest()
    manifest = {
        "schema": "cbase-heldout-slice/v1",
        "issue": ISSUE,
        "captured_public_master": _git_head(NC),
        "source_corpus": {
            "combined_sha256": combined_sha256,
            "receipt_path": f"receipts/{SHARD_RECEIPT_NAME}",
            "receipt_sha256": _sha256(receipt_path),
            "shards": [{"name": shard_name, "sha256": shard_meta["sha256"],
                       "n_tokens": shard_meta["n_tokens"],
                       "global_token_start": shard_start,
                       "global_token_end_exclusive": shard_end}],
        },
        "selection_evidence": {
            "path": "receipts/cbase-heldout-eval/issue-760-slice-regeneration-finding.json",
            "sha256": "0" * 64,   # filled in after the finding receipt is written; see main()
            "batch_sha256": "0" * 64,
            "verdict": "DECONTAMINATION_NOT_PERFORMED",
        },
        "sequence": {"dtype": "<u2", "seq": seq, "n_mtp": n_mtp, "separator_id": tsv.SEPARATOR_ID,
                    "packed_bytes_per_token": 2, "scoring": "primary_next_token_only"},
        "training_consumption": [{
            "source": TRAINING_CONSUMPTION_SOURCE,
            "window_start": 0, "window_end_exclusive": MAX_RECEIPTED_TRAINING_WINDOW_CEILING + 1,
            "global_token_start": 0, "global_token_end_exclusive": training_ceiling_token,
        }],
        "windows": windows,
        "expected_scored_token_count": len(windows) * seq,
        "scale": SCALE,
        "availability": {"status": "AVAILABLE", "missing": [],
                         "note": f"{shard_name} verified present on disk with matching sha256 "
                                 "at regeneration time, rehashed against the pinned "
                                 f"{SHARD_RECEIPT_NAME} entry (no local filesystem path recorded "
                                 "here by design -- shard_dir is a per-machine data-store "
                                 "location, not part of the corpus's identity)."},
        "claim_boundary": ("CANDIDATE slice: exclusion-clean (fineweb_exclusion-verified) and "
                           "training-range-disjoint (arithmetic-verified). NOT decontamination-"
                           "verified (no n-gram contamination_recheck run -- see selection_evidence "
                           "and the companion finding receipt). NOT the frozen production slice. "
                           "No heldout metric, capability, same-quality, or milestone-completion "
                           "claim."),
    }

    finding = {
        "ticket": "ISSUE-760-SLICE-REGENERATION-FINDING",
        "issue": ISSUE,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "status": "FROZEN_SLICE_INVALIDATED_REPLACEMENT_BLOCKED",
        "invalidated_slice": {
            "path": "manifests/cbase-heldout-slice-v1.json",
            "shard": "v0-00016.bin",
            "shard_global_range": [4294967296, 4563402752],
            "reason": ("entirely inside the ruled-excluded fineweb_edu range "
                      "[4055121325, 5723508974); the exclusion ruling (2026-08-04 L3 audit, "
                      "#1436) postdates this slice's PR (#1228, merged 2026-07-30) by 5 days"),
            "proof": ("python -B scripts/cbase_heldout_eval.py --validate-only --shard-dir "
                     "<real shards> exits 2 with SLICE_OVERLAPS_EXCLUDED_SOURCE against the "
                     "committed manifest, using the verify_slice_excludes_ruled_sources check "
                     "added in this same change"),
        },
        "candidate_slice": {
            "shard": shard_name,
            "shard_global_range": [shard_start, shard_end],
            "window_count": len(windows),
            "exclusion_verified": True,
            "exclusion_ranges_checked": [list(r) for r in excluded_ranges],
            "training_disjointness_verified": True,
            "training_disjointness_method": "range arithmetic only (see training_consumption source)",
            "decontamination_verified": False,
        },
        "blocker": {
            "what": "n-gram contamination_recheck was not re-run for the candidate windows",
            "why_not_run": ("the only implementation is src/ember/governance/scripts/w1_collapse_control_run.py:"
                           "contamination_recheck; that file imports timeshare_pretrain at "
                           "module scope (line 76), and timeshare_pretrain.py raises SystemExit "
                           "at module scope under the 2026-07-12 historical_only execution-"
                           "denial lock -- importing either to call it would violate that lock"),
            "resolution_paths": [
                "port contamination_recheck into a standalone, non-execution-denied module, "
                "mirroring how cbase_heldout_eval.py's own eval_loss mechanism was ported out "
                "of the same file for #760 Deliverable 1 (named follow-up, not attempted here)",
                "an explicit operator decision to accept range-arithmetic-only disjointness for "
                "this specific replacement slice, promoting the candidate manifest by hand",
            ],
        },
        "limitations": [
            "MAX_RECEIPTED_TRAINING_WINDOW_CEILING (24527 windows / 25,116,675 tokens) is the "
            "highest value found by grepping receipts/ for max_training_window_index_at_ceiling "
            "as of 2026-08-05, not a query against a single aggregate consumption ledger -- no "
            "such ledger exists yet. The candidate shard starts at global token "
            f"{shard_start:,}, ~{shard_start // max(training_ceiling_token, 1):,}x that ceiling, "
            "so this is not a close call, but it is a grep-derived bound, not a closed-form proof.",
        ],
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "no_gpu": True,
        "schema": "cbase-heldout-slice-regeneration-finding/v1",
        # Every post-genesis receipt must carry the constitutional invariant
        # hash (guard changed-receipts leg -> receipt_check, which refuses
        # MISSING_INVARIANT_SHA256). Read from receipt_check -- the component
        # that ENFORCES the value -- never copied, so the two cannot drift.
        # And any receipt carrying a *sha256* field must declare its
        # sha_convention (receipt_check SHA-CONVENTION rule). Mirrors
        # fineweb_exclusion.py's own --preflight receipt (:644-653).
        "invariant_sha256": receipt_check.INVARIANT_SHA256,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
    }
    return manifest, finding


def _git_head(nc: Path) -> str:
    import subprocess
    out = subprocess.run(["git", "-C", str(nc), "rev-parse", "origin/master"],
                         capture_output=True, text=True, check=False)
    sha = out.stdout.strip()
    return sha if len(sha) == 40 else "0" * 40


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--window-count", type=int, default=16)
    parser.add_argument("--out", default=str(NC / "manifests" /
                                             "cbase-heldout-slice-v1-CANDIDATE.json"))
    parser.add_argument("--receipt-out", default=str(
        NC / "receipts" / "cbase-heldout-eval" / "issue-760-slice-regeneration-finding.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rule-derived-exclusion", action="store_true")
    parser.add_argument("--exclusion-set-receipt")
    parser.add_argument("--expected-exclusion-set-sha256")
    args = parser.parse_args(argv)

    if args.rule_derived_exclusion:
        raw_args = list(sys.argv[1:] if argv is None else argv)
        if (not args.exclusion_set_receipt or not args.expected_exclusion_set_sha256
                or "--out" not in raw_args or "--receipt-out" not in raw_args
                or "--window-count" in raw_args or args.dry_run):
            raise SystemExit("RULE_FREEZE_REFUSED: exact exclusion receipt/hash and fresh explicit out/receipt-out are required; caller selection controls and dry-run are forbidden")
        out_path=Path(args.out); receipt_out=Path(args.receipt_out)
        if out_path.exists() or receipt_out.exists():
            raise SystemExit("RULE_FREEZE_REFUSED: output or receipt already exists")
        try:
            receipt_rel=str(receipt_out.resolve().relative_to(NC.resolve())).replace("\\","/")
        except ValueError as exc:
            raise SystemExit("RULE_FREEZE_REFUSED: receipt-out must be inside repository custody") from exc
        manifest, receipt = build_rule_derived_candidate(
            shard_dir=Path(args.shard_dir),
            exclusion_set_receipt=Path(args.exclusion_set_receipt),
            expected_exclusion_set_sha256=args.expected_exclusion_set_sha256,
            selection_receipt_path=receipt_rel)
        # issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
        import importlib.util as _ember_66ee9e91637922dc_importlib
        import sys as _ember_66ee9e91637922dc_sys
        from pathlib import Path as _ember_66ee9e91637922dc_Path
        _ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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
        # issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py        # noqa: E402
        receipt_out.parent.mkdir(parents=True,exist_ok=True)
        checked_write(str(receipt_out),receipt)
        receipt_sha=_sha256(receipt_out)
        manifest["selection_evidence"]["sha256"]=receipt_sha
        manifest["selection_evidence"]["batch_sha256"]=receipt_sha
        _write_json_no_overwrite(out_path,manifest)
        print(f"RULE_DERIVED_FREEZE_WRITTEN receipt={receipt_out} candidate={out_path} sha256={_sha256(out_path)}")
        return 0

    manifest, finding = build_candidate(shard_dir=Path(args.shard_dir), window_count=args.window_count)

    if args.dry_run:
        print(json.dumps({"candidate_shard": manifest["source_corpus"]["shards"][0]["name"],
                          "window_count": len(manifest["windows"]),
                          "status": finding["status"]}, sort_keys=True))
        return 0

    receipt_out = Path(args.receipt_out)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    # issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
    import importlib.util as _ember_66ee9e91637922dc_importlib
    import sys as _ember_66ee9e91637922dc_sys
    from pathlib import Path as _ember_66ee9e91637922dc_Path
    _ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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
    # issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py        # noqa: E402
    checked_write(str(receipt_out), finding)
    manifest["selection_evidence"]["sha256"] = _sha256(receipt_out)
    manifest["selection_evidence"]["batch_sha256"] = manifest["selection_evidence"]["sha256"]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    out_path.write_text(manifest_payload, encoding="utf-8", newline="\n")
    manifest_sha = _sha256(out_path)

    print(f"REGENERATE_CANDIDATE_WRITTEN {out_path} sha256={manifest_sha}")
    print(f"REGENERATE_FINDING_WRITTEN {receipt_out}")
    print(json.dumps({"candidate_shard": manifest["source_corpus"]["shards"][0]["name"],
                      "candidate_manifest_sha256": manifest_sha,
                      "window_count": len(manifest["windows"]),
                      "decontamination_verified": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
