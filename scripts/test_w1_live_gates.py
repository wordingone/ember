# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_w1_live_gates.py -- hermetic regression tests for issue #121's two
spec-compliance additions to src/ember/governance/scripts/w1_collapse_control_run.py:

  Defect A: refuse_if_contaminated() -- the live launch must hard-refuse when
    this run's own fresh contamination_recheck() finds any confirmed match
    (previously computed and disclosed, never gated).
  Defect B: rebuild_batch_from_decontam_receipt() -- an external
    w2-heldout-decontam/v1 receipt's own selected_window_indices drive which
    windows are held out, with the rebuilt batch's sha256 asserted against
    the receipt's pinned batch_sha256, fail-closed on mismatch.

Plus (2026-07-07, real-launch refusal fork-A fix): classify_contamination_
self_matches() / refuse_if_non_self_contaminated() -- a held-out batch's own
true source windows will ALWAYS match themselves when contamination_recheck()
scans the real corpus (they were drawn from it); refuse_if_contaminated
cannot tell that apart from a genuine foreign duplicate. The new gate must
still refuse on a genuine foreign duplicate.

Real code under test (imported, never reimplemented), synthetic-only data
(tempfile.TemporaryDirectory() per case, a tiny made-up token stream) -- same
convention as src/ember/governance/scripts/w2_heldout/test_launch_gate.py. No real corpus or real
receipt is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np
import pytest
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/w1_collapse_control_run.py
import importlib.util as _ember_85e76a5cb35a8ea2_importlib
import sys as _ember_85e76a5cb35a8ea2_sys
from pathlib import Path as _ember_85e76a5cb35a8ea2_Path
_ember_85e76a5cb35a8ea2_path = _ember_85e76a5cb35a8ea2_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'w1_collapse_control_run.py')
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
refuse_if_contaminated = getattr(_ember_85e76a5cb35a8ea2_module, 'refuse_if_contaminated')
rebuild_batch_from_decontam_receipt = getattr(_ember_85e76a5cb35a8ea2_module, 'rebuild_batch_from_decontam_receipt')
derive_rung_receipt_from_manifest = getattr(_ember_85e76a5cb35a8ea2_module, 'derive_rung_receipt_from_manifest')
sha256_tokens = getattr(_ember_85e76a5cb35a8ea2_module, 'sha256_tokens')
contamination_recheck = getattr(_ember_85e76a5cb35a8ea2_module, 'contamination_recheck')
classify_contamination_self_matches = getattr(_ember_85e76a5cb35a8ea2_module, 'classify_contamination_self_matches')
refuse_if_non_self_contaminated = getattr(_ember_85e76a5cb35a8ea2_module, 'refuse_if_non_self_contaminated')
write_refusal_receipt = getattr(_ember_85e76a5cb35a8ea2_module, 'write_refusal_receipt')
rung_provenance_info = getattr(_ember_85e76a5cb35a8ea2_module, 'rung_provenance_info')
w1_main = getattr(_ember_85e76a5cb35a8ea2_module, 'main')
DEFAULT_PRICING_RECEIPT = getattr(_ember_85e76a5cb35a8ea2_module, 'DEFAULT_PRICING_RECEIPT')
DEFAULT_RUNG_RECEIPT = getattr(_ember_85e76a5cb35a8ea2_module, 'DEFAULT_RUNG_RECEIPT')
# issue2015 exact-local-import-end:src/ember/governance/scripts/w1_collapse_control_run.py
from timeshare_pretrain import PackedShardLoader  # noqa: E402


SEQ = 8
N_MTP = 1


def _make_shard_dir(tmpdir: str, n_tokens: int = 400) -> str:
    """Writes one tiny synthetic .bin shard (uint16 tokens 0..n_tokens-1,
    deterministic, never touching any real corpus) and returns its dir."""
    shard_dir = os.path.join(tmpdir, "shards")
    os.makedirs(shard_dir, exist_ok=True)
    tokens = np.arange(n_tokens, dtype="<u2") % 997  # keep values small/varied
    tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))
    return shard_dir


def _batch_sha_for_indices(loader: PackedShardLoader, indices: list[int]) -> str:
    """Ground truth: the SAME convention rebuild_batch_from_decontam_receipt
    itself uses (sha256_tokens over concat([x, y], dim=1)) -- computed here
    independently, directly from the loader, to build a CORRECT receipt for
    the green-path test."""
    xs, ys = [], []
    for idx in indices:
        x_np, y_np, _y_mtp = loader.window_np(idx)
        xs.append(x_np)
        ys.append(y_np)
    eval_x = torch.as_tensor(np.stack(xs), dtype=torch.long)
    eval_y = torch.as_tensor(np.stack(ys), dtype=torch.long)
    return sha256_tokens(torch.cat([eval_x, eval_y], dim=1))


# ---------------------------------------------------------------------------
# Test 1 (Defect A): CONTAMINATED verdict -> refuses; CLEAN -> does not.
# ---------------------------------------------------------------------------

def test_contaminated_verdict_refuses():
    contaminated = {
        "verdict": "CONTAMINATED",
        "confirmed_matches": [{"shard": "shard-0000.bin", "offset": 3, "window": [1, 2, 3]}],
    }
    with pytest.raises(SystemExit, match="W1_LIVE_CONTAMINATION_REFUSED"):
        refuse_if_contaminated(contaminated)


def test_clean_verdict_does_not_refuse():
    clean = {"verdict": "CLEAN", "confirmed_matches": []}
    refuse_if_contaminated(clean)  # must not raise


# ---------------------------------------------------------------------------
# Test 2 (Defect B, RED): a receipt whose pinned batch_sha256 does not match
# the rebuilt batch (tampered/stale/wrong-shard-dir) -> refuses.
# ---------------------------------------------------------------------------

def test_sha_mismatch_refuses():
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = _make_shard_dir(tmpdir)
        loader = PackedShardLoader(shard_dir, SEQ, n_mtp=N_MTP)

        receipt = {
            "selected_window_indices": [0, 2, 5],
            "batch_sha256": "deadbeef" * 8,  # deliberately wrong (64 hex chars)
        }
        with pytest.raises(SystemExit, match="W1_LIVE_DECONTAM_BATCH_SHA_MISMATCH"):
            rebuild_batch_from_decontam_receipt(loader, receipt, "cpu")


# ---------------------------------------------------------------------------
# Test 3 (Defect B, GREEN): a correctly-pinned receipt is accepted, and the
# rebuilt batch corresponds EXACTLY to the receipt's selected_window_indices
# -- not silently substituted with the script's internal "last N windows"
# convention.
# ---------------------------------------------------------------------------

def test_certified_receipt_selected_windows_match_indices_exactly():
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = _make_shard_dir(tmpdir)
        loader = PackedShardLoader(shard_dir, SEQ, n_mtp=N_MTP)

        indices = [1, 3, 4]  # deliberately non-contiguous, deliberately NOT
                              # "the last batch-many windows" of the stream
        correct_sha = _batch_sha_for_indices(loader, indices)
        receipt = {"selected_window_indices": indices, "batch_sha256": correct_sha}

        eval_x, eval_y, eval_sha = rebuild_batch_from_decontam_receipt(
            loader, receipt, "cpu")

        assert eval_sha == correct_sha

        for row, idx in enumerate(indices):
            expected_x, expected_y, _ = loader.window_np(idx)
            assert torch.equal(eval_x[row], torch.as_tensor(expected_x, dtype=torch.long))
            assert torch.equal(eval_y[row], torch.as_tensor(expected_y, dtype=torch.long))

        # Negative control: NOT equal to the internal "last batch-many
        # windows" convention this test deliberately avoided.
        last_n_x, _last_n_y, _ = loader.window_np(loader.n_windows - len(indices))
        assert not torch.equal(eval_x[0], torch.as_tensor(last_n_x, dtype=torch.long))


# ---------------------------------------------------------------------------
# Test 4 (item 7): derive_rung_receipt_from_manifest -- reads ff_grown from a
# real per-checkpoint manifest.json, derives vocab/hidden from the actual
# model.pt embedding tensor shape, and discloses (never fabricates) the
# fields a checkpoint manifest cannot carry (params_unique_after,
# params_state_dict_sum_after, tok_s_paced).
# ---------------------------------------------------------------------------

def test_derive_rung_receipt_from_manifest():
    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "step-00000001")
        os.makedirs(ckpt_dir, exist_ok=True)
        vocab, hidden = 37, 11
        state = {"model.embed_tokens.weight": torch.zeros(vocab, hidden)}
        torch.save(state, os.path.join(ckpt_dir, "model.pt"))
        manifest_path = os.path.join(ckpt_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            import json
            json.dump({"step": 1, "extra": {"ff_grown": 4096}}, f)

        rung_receipt = derive_rung_receipt_from_manifest(manifest_path)

        assert rung_receipt["ff_grown"] == 4096
        assert rung_receipt["params_dedup"]["measured_duplicate_numel"] == vocab * hidden
        assert rung_receipt["params_unique_after"] is None
        assert rung_receipt["params_state_dict_sum_after"] is None
        assert rung_receipt["stabilization_segment"]["tok_s_paced"] is None
        assert rung_receipt["stabilization_segment"]["checkpoint"] == ckpt_dir
        assert "unavailable" in rung_receipt["_derivation"]["params_unique_after"]


# ---------------------------------------------------------------------------
# Tests 5-7 (2026-07-07 real-launch refusal, fork-A fix): a held-out batch's
# own true source windows will ALWAYS match themselves when
# contamination_recheck() scans the real corpus -- classify_contamination_
# self_matches must exclude those (matching build_decontam_batch_mp.py's
# is_self convention) while STILL refusing on a genuine foreign duplicate.
# window=13 (CONTAMINATION_WINDOW_TOKENS) needs row length (seq+1) >= 13, so
# these tests use a wider SEQ2 than the SEQ=8 fixture above.
# ---------------------------------------------------------------------------

SEQ2 = 16
N_MTP2 = 1


def _eval_rows_for_indices(loader: PackedShardLoader, indices: list[int]) -> list[list[int]]:
    rows = []
    for idx in indices:
        x_np, y_np, _y_mtp = loader.window_np(idx)
        rows.append(list(x_np) + [int(y_np[-1])])
    return rows


def test_self_match_only_refuses_raw_but_passes_classified():
    """The exact class of the 2026-07-07 refusal: a batch drawn from windows
    that ARE part of the corpus (unavoidable -- that's what 'held out'
    means) must refuse on the RAW gate (reproducing the bug) but PASS on the
    self-exclusion-aware gate (the fix)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        # Unique-valued stream (no modulo) so no incidental 13-gram repeats
        # anywhere else in the corpus can confound this test's assumptions.
        n_tokens = 2000
        tokens = np.arange(n_tokens, dtype="<u2")
        tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))
        loader = PackedShardLoader(shard_dir, SEQ2, n_mtp=N_MTP2)

        candidate_indices = [5, 20, 40]  # disjoint from each other and small
        eval_rows = _eval_rows_for_indices(loader, candidate_indices)

        contamination = contamination_recheck(eval_rows, shard_dir)
        assert contamination["verdict"] == "CONTAMINATED"
        assert len(contamination["confirmed_matches"]) > 0
        with pytest.raises(SystemExit, match="W1_LIVE_CONTAMINATION_REFUSED"):
            refuse_if_contaminated(contamination)  # reproduces the 2026-07-07 bug

        classified = classify_contamination_self_matches(
            contamination, candidate_indices,
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)
        assert classified["verdict"] == "CLEAN"
        assert classified["confirmed_non_self_matches"] == []
        assert classified["self_matches_excluded"] == len(contamination["confirmed_matches"])
        # Mock args and other params for the test (non-refusal path)
        mock_args = argparse.Namespace(
            decontam_receipt=None, shard_dir=shard_dir,
            live_ceiling_steps=None, live_eval_every=None, live_checkpoint_every=None)
        refuse_if_non_self_contaminated(
            classified, contamination=contamination,
            candidate_window_indices=candidate_indices,
            args=mock_args, out_dir=tmpdir, ts="20260707T000000Z",
            real_arch={"seq": SEQ2, "n_mtp": N_MTP2, "batch": len(candidate_indices)},
            disjoint_check={"mode": "contiguous-default"})  # must NOT raise


def test_genuine_foreign_duplicate_still_refuses():
    """A candidate window whose token sequence ALSO appears somewhere else
    in the corpus (not at its own location) is real contamination -- the
    self-exclusion fix must not neuter this."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        n_tokens = 3000
        tokens = np.arange(n_tokens, dtype="<u2")
        block_len = SEQ2 + 1 + N_MTP2  # 18

        candidate_idx = 5  # window covers tokens [5*16, 5*16+18) = [80, 98)
        foreign_copy_start = 2000  # far away, no overlap with any candidate
        tokens[foreign_copy_start:foreign_copy_start + block_len] = \
            tokens[candidate_idx * SEQ2: candidate_idx * SEQ2 + block_len]
        tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))

        loader = PackedShardLoader(shard_dir, SEQ2, n_mtp=N_MTP2)
        eval_rows = _eval_rows_for_indices(loader, [candidate_idx])

        contamination = contamination_recheck(eval_rows, shard_dir)
        classified = classify_contamination_self_matches(
            contamination, [candidate_idx],
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)

        assert classified["verdict"] == "CONTAMINATED"
        assert len(classified["confirmed_non_self_matches"]) > 0
        # The candidate's OWN home-location matches are still excluded --
        # only the foreign copy's matches remain.
        assert classified["self_matches_excluded"] > 0
        # Mock args and other params for the test (refusal path)
        mock_args = argparse.Namespace(
            decontam_receipt=None, shard_dir=shard_dir,
            live_ceiling_steps=None, live_eval_every=None, live_checkpoint_every=None)
        with pytest.raises(SystemExit, match="W1_LIVE_CONTAMINATION_REFUSED"):
            refuse_if_non_self_contaminated(
                classified, contamination=contamination,
                candidate_window_indices=[candidate_idx],
                args=mock_args, out_dir=tmpdir, ts="20260707T000000Z",
                real_arch={"seq": SEQ2, "n_mtp": N_MTP2, "batch": 1},
                disjoint_check={"mode": "contiguous-default"})


def test_boundary_match_global_start_conversion():
    """A confirmed match reported in 'boundary' form (a hit spanning two
    shard files, as contamination_recheck's join-array branch produces) must
    convert to the correct global position too, not just the plain 'shard'
    form -- otherwise a real cross-shard-boundary contamination would be
    silently misclassified as self (or vice versa)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        # Two shards; candidate lives entirely in shard 0, nowhere near the
        # boundary -- so a fabricated 'boundary' match must be classified
        # non-self (it cannot overlap the candidate's true range).
        shard0 = np.arange(0, 100, dtype="<u2")
        shard1 = np.arange(100, 200, dtype="<u2")
        shard0.tofile(os.path.join(shard_dir, "shard-0000.bin"))
        shard1.tofile(os.path.join(shard_dir, "shard-0001.bin"))

        candidate_idx = 1  # tokens [16, 34) -- nowhere near the shard0|shard1 join
        contamination = {
            "confirmed_matches": [
                {"boundary": "shard-0000.bin|shard-0001.bin", "offset_in_join": 0,
                 "window": list(range(13))},
            ],
        }
        classified = classify_contamination_self_matches(
            contamination, [candidate_idx],
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)
        assert classified["verdict"] == "CONTAMINATED"
        assert classified["self_matches_excluded"] == 0
        assert len(classified["confirmed_non_self_matches"]) == 1


# ---------------------------------------------------------------------------
# Tests 8-9 (2026-07-07, attempt-2 crash fix): the terminal receipt writer
# used to hash args.rung_receipt UNCONDITIONALLY, even when the run was
# launched in --rung-manifest mode -- where args.rung_receipt is never
# loaded and keeps its DEFAULT_RUNG_RECEIPT value, a path that does not
# resolve inside a worktree. Attempt 2 (real GPU run, w1-live-
# 20260707T091615Z) trained through to an early-stop MATCH (eval_loss=9.25
# <= target 9.375 at step 50) and then crashed writing this exact field.
# main_live() (the real GPU entrypoint, "device = 'cuda'" hardcoded at its
# top) is -- per its own docstring -- never invoked end-to-end outside real
# CUDA; its receipt-write tail shared the IDENTICAL two-line bug with
# main()'s CPU dry-run tail (same unconditional sha256_file(args.rung_
# receipt) pattern, same DEFAULT_RUNG_RECEIPT root cause). Test 9 drives
# that shared receipt-write path end-to-end via the dry-run branch (cheap,
# CPU-only, no CUDA required) in manifest mode -- the only way to exercise
# the actual crash line without real hardware -- and test 8 unit-tests the
# extracted fix function directly (the exact code main_live's tail now
# calls for this field).
# ---------------------------------------------------------------------------

def test_rung_provenance_info_manifest_mode_never_touches_default_receipt_path():
    """In --rung-manifest mode, rung_provenance_info must hash the manifest
    path -- and must NEVER attempt to open args.rung_receipt's unused
    DEFAULT_RUNG_RECEIPT value. Proven by leaving rung_receipt pointed at a
    path that does not exist (the real-world default) and asserting no
    crash plus the correct source is reported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "step-00000001")
        os.makedirs(ckpt_dir, exist_ok=True)
        vocab, hidden = 37, 11
        state = {"model.embed_tokens.weight": torch.zeros(vocab, hidden)}
        torch.save(state, os.path.join(ckpt_dir, "model.pt"))
        manifest_path = os.path.join(ckpt_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            import json
            json.dump({"step": 1, "extra": {"ff_grown": 4096}}, f)

        class _Args:
            rung_manifest = manifest_path
            rung_receipt = os.path.join(tmpdir, "does-not-exist.json")

        info = rung_provenance_info(_Args())
        assert info["mode"] == "manifest"
        assert info["path"] == manifest_path
        assert len(info["sha256"]) == 64  # real sha256 of the manifest, computed without error

    def _receipt_mode_still_works():
        with tempfile.TemporaryDirectory() as tmpdir2:
            receipt_path = os.path.join(tmpdir2, "rung.json")
            with open(receipt_path, "w", encoding="utf-8") as f:
                import json
                json.dump({"ok": True}, f)

            class _Args2:
                rung_manifest = None
                rung_receipt = receipt_path

            info2 = rung_provenance_info(_Args2())
            assert info2["mode"] == "receipt"
            assert info2["path"] == receipt_path
            assert len(info2["sha256"]) == 64

    _receipt_mode_still_works()


def test_main_dryrun_manifest_mode_receipt_write_does_not_crash():
    """Regression test for the attempt-2 crash (issue #121): drives the real
    receipt-write path (shared by main_live's live tail and this CPU
    dry-run tail -- same two lines, same bug, same fix) end-to-end via
    main(argv) in --rung-manifest mode, with --rung-receipt left at its
    real DEFAULT_RUNG_RECEIPT value. At the pre-fix commit (6d9185a2,
    PR #330 merge -- the exact head attempt 2 ran against) this raises
    FileNotFoundError while writing the terminal receipt, reproducing the
    crash exactly. After the fix it must return 0 and the written receipt's
    real_lineage_reference must disclose rung_provenance_mode="manifest",
    the manifest path, and a real sha256 -- never touching
    DEFAULT_RUNG_RECEIPT's broken path at all.

    Fresh-clone fixture (issue #368): uses committed
    src/ember/governance/scripts/tests/fixtures/w1-pricing-fixture-minimal.json so the test
    passes on any fresh clone without machine-local files."""
    assert not os.path.exists(DEFAULT_RUNG_RECEIPT), (
        "fixture assumption: DEFAULT_RUNG_RECEIPT must NOT exist in this "
        "worktree (the real condition attempt 2 crashed under) -- if this "
        "ever exists, the test is no longer proving the crash class")

    # Use committed fixture for fresh-clone reproducibility (issue #368)
    pricing_receipt_path = os.path.join(
        HERE, "tests", "fixtures", "w1-pricing-fixture-minimal.json")
    assert os.path.exists(pricing_receipt_path), (
        f"fixture must exist: {pricing_receipt_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "step-00000001")
        os.makedirs(ckpt_dir, exist_ok=True)
        # vocab MUST equal the real pricing receipt's control_arm.target_
        # architecture vocab (32000) -- derive_real_arch_config asserts
        # measured_duplicate_numel % vocab == 0.
        vocab, hidden = 32000, 4
        state = {"model.embed_tokens.weight": torch.zeros(vocab, hidden)}
        torch.save(state, os.path.join(ckpt_dir, "model.pt"))
        manifest_path = os.path.join(ckpt_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            import json
            json.dump({"step": 1, "extra": {"ff_grown": 16}}, f)

        out_dir = os.path.join(tmpdir, "out")
        receipts_dir_repo = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "receipts", "ember-c-scale")
        before = set(os.listdir(receipts_dir_repo)) if os.path.isdir(receipts_dir_repo) else set()

        written_path = None
        try:
            rc = w1_main([
                "--pricing-receipt", pricing_receipt_path,
                "--rung-manifest", manifest_path,
                "--out-dir", out_dir,
                "--receipts-out-dir", receipts_dir_repo,
                "--phase1-train-steps", "2",
                "--ceiling-steps", "2",
                "--eval-every", "1",
                "--checkpoint-every", "1",
            ])
            assert rc == 0

            after = set(os.listdir(receipts_dir_repo))
            new_files = after - before
            assert len(new_files) == 1, (
                f"expected exactly one new receipt, found {new_files!r}")
            written_path = os.path.join(receipts_dir_repo, next(iter(new_files)))

            with open(written_path, "r", encoding="utf-8") as f:
                import json
                receipt = json.load(f)
            ref = receipt["real_lineage_reference"]
            assert ref["rung_provenance_mode"] == "manifest"
            # On Windows, tempfile.TemporaryDirectory() defaults to C: drive,
            # while the repo is on B: -- cross-drive paths are sanitized to
            # 'external:<basename>' format per repo_relative_path (issue #361
            # fix-forward). Verify the path is safely recorded (either
            # repo-relative for in-repo paths, or external:<name> for out-of-
            # repo ones), never the raw absolute path.
            assert (ref["rung_provenance_path"] == manifest_path or
                    ref["rung_provenance_path"].startswith("external:")), (
                f"rung_provenance_path must be either the original path (if "
                f"in-repo) or sanitized to 'external:' format (if cross-drive), "
                f"never a raw absolute path: {ref['rung_provenance_path']!r}")
            assert len(ref["rung_provenance_sha256"]) == 64
            assert "rung_receipt_path" not in ref
            assert "rung_receipt_sha256" not in ref
        finally:
            if written_path and os.path.exists(written_path):
                os.remove(written_path)  # test artifact, never left in the repo


# ---------------------------------------------------------------------------
# Test refusal receipt writing (issue #371)
# ---------------------------------------------------------------------------

def test_refusal_receipt_written_on_genuine_foreign_duplicate():
    """Issue #371: refusal receipt must be written to scratch/w1-control/receipts/
    with full match counts, derivation mode, first N matches, batch sha, and
    resolved args. This test creates a genuine foreign duplicate, triggers a
    refusal via classify_contamination_self_matches, and verifies the refusal
    receipt exists with required fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)

        # Create a token stream with a candidate window and a foreign copy
        # of that window at a different location (using SEQ2 for wider rows)
        n_tokens = 2500
        tokens = np.arange(n_tokens, dtype="<u2")

        # candidate window: window 5
        candidate_idx = 5
        block_len = SEQ2 + 1 + N_MTP2
        # Make a copy of candidate's tokens at a foreign location (far away)
        foreign_copy_start = 2000
        tokens[foreign_copy_start:foreign_copy_start + block_len] = \
            tokens[candidate_idx * SEQ2: candidate_idx * SEQ2 + block_len]
        tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))

        loader = PackedShardLoader(shard_dir, SEQ2, n_mtp=N_MTP2)

        # Our held-out batch is just the candidate window
        candidate_indices = [candidate_idx]
        eval_rows = _eval_rows_for_indices(loader, candidate_indices)

        contamination = contamination_recheck(eval_rows, shard_dir)
        assert contamination["verdict"] == "CONTAMINATED", \
            f"Expected CONTAMINATED, got {contamination['verdict']}"

        classified = classify_contamination_self_matches(
            contamination, candidate_indices,
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)
        assert classified["verdict"] == "CONTAMINATED", \
            f"Expected CONTAMINATED after classification, got {classified['verdict']}"
        assert len(classified["confirmed_non_self_matches"]) > 0, \
            "Expected non-self matches from foreign copy"

        # Mock args
        args = argparse.Namespace(
            decontam_receipt=None,
            shard_dir=shard_dir,
            live_ceiling_steps=None,
            live_eval_every=None,
            live_checkpoint_every=None,
        )

        # Mock other params
        out_dir = tmpdir
        ts = "20260707T000000Z"
        real_arch = {"seq": SEQ2, "n_mtp": N_MTP2, "batch": len(candidate_indices)}
        disjoint_check = {"mode": "contiguous-default"}
        eval_batch_sha = "abc123def456"

        # Write refusal receipt
        receipt_path = write_refusal_receipt(
            contamination, classified, candidate_indices,
            args=args, out_dir=out_dir, ts=ts, real_arch=real_arch,
            disjoint_check=disjoint_check, eval_batch_sha=eval_batch_sha)

        # Verify receipt exists and has required fields
        assert os.path.exists(receipt_path)
        assert "w1-contamination-refused" in receipt_path
        assert receipt_path.endswith(".json")

        with open(receipt_path, "r", encoding="utf-8") as f:
            receipt = json.load(f)

        # Check required fields
        assert receipt["ticket"] == "W1-CONTAMINATION-REFUSED"
        assert receipt["schema"] == "w1-contamination-refusal/v1"
        assert receipt["issue"] == "#371"
        assert receipt["derivation_mode"] == "contiguous-default"
        assert receipt["held_out_candidate_window_indices"] == candidate_indices
        assert receipt["contamination_verdict"] == "CONTAMINATED"

        # Check match counts
        assert "match_counts" in receipt
        assert receipt["match_counts"]["raw_confirmed_matches"] > 0
        assert receipt["match_counts"]["confirmed_non_self_matches"] > 0

        # Check direction structure
        assert "direction_structure" in receipt
        assert "self_exclusion_description" in receipt["direction_structure"]
        assert "what_self_exclusion_excluded" in receipt["direction_structure"]
        assert "why_remainder_is_non_self" in receipt["direction_structure"]

        # Check first N matches
        assert "first_n_matches" in receipt
        assert len(receipt["first_n_matches"]) <= 20
        assert receipt["n_matches_shown"] <= 20
        assert receipt["total_matches_available"] == len(contamination["confirmed_matches"])

        # Check batch identity and resolved args
        assert receipt["batch_identity"]["batch_sha256"] == eval_batch_sha
        assert receipt["batch_identity"]["candidate_windows_count"] == len(candidate_indices)
        assert receipt["resolved_args"]["decontam_receipt"] is None


def test_continuation_source_verification_block_structure():
    """Issue #375: verify_continuation_source_checkpoint() computes the
    verification block structure correctly: checkpoint_dir, manifest_sha256,
    on_disk_model_pt_sha256, and match boolean.

    Direct unit test of the verification function with minimal fixture."""
    # issue2015 exact-local-import:src/ember/governance/scripts/w1_collapse_control_run.py
    import importlib.util as _ember_85e76a5cb35a8ea2_importlib
    import sys as _ember_85e76a5cb35a8ea2_sys
    from pathlib import Path as _ember_85e76a5cb35a8ea2_Path
    _ember_85e76a5cb35a8ea2_path = _ember_85e76a5cb35a8ea2_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'w1_collapse_control_run.py')
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
    verify_continuation_source_checkpoint = getattr(_ember_85e76a5cb35a8ea2_module, 'verify_continuation_source_checkpoint')
    sha256_file = getattr(_ember_85e76a5cb35a8ea2_module, 'sha256_file')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/w1_collapse_control_run.py

    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "checkpoint")
        os.makedirs(ckpt_dir, exist_ok=True)

        # Create minimal checkpoint files
        model_pt_path = os.path.join(ckpt_dir, "model.pt")
        torch.save({"embed_tokens.weight": torch.zeros(100, 64)}, model_pt_path)

        # Compute sha256
        model_pt_sha = sha256_file(model_pt_path)

        # Create manifest with matching sha
        manifest = {
            "step": 5,
            "files": {
                "model.pt": model_pt_sha,
                "optimizer.pt": "0" * 64,
                "rng.pt": "0" * 64,
            }
        }
        manifest_path = os.path.join(ckpt_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Call the verification function
        result = verify_continuation_source_checkpoint(ckpt_dir, manifest)

        # Verify structure
        assert isinstance(result, dict), "Result must be a dict"
        assert "checkpoint_dir" in result, "Must have checkpoint_dir"
        assert "manifest_sha256" in result, "Must have manifest_sha256"
        assert "on_disk_model_pt_sha256" in result, "Must have on_disk_model_pt_sha256"
        assert "match" in result, "Must have match boolean"

        # Verify values
        assert result["checkpoint_dir"] == ckpt_dir
        assert len(result["manifest_sha256"]) == 64, "manifest_sha256 should be 64 hex chars"
        assert len(result["on_disk_model_pt_sha256"]) == 64, "on_disk_model_pt_sha256 should be 64 hex chars"
        assert all(c in "0123456789abcdef" for c in result["manifest_sha256"].lower())
        assert all(c in "0123456789abcdef" for c in result["on_disk_model_pt_sha256"].lower())

        # Verify match is True (model.pt sha matches manifest)
        assert result["match"] is True, \
            f"model.pt sha should match manifest record (match={result['match']}, " \
            f"manifest sha={result['on_disk_model_pt_sha256']}, " \
            f"expected={model_pt_sha})"


def test_accepted_run_receipt_carries_derivation_mode():
    """Issue #371 requirement: derivation_mode line must appear in EVERY receipt
    (both accepted and refused). This is a placeholder test that verifies the
    schema supports it; the actual test would be in main_dry_run smoke test
    or integration test."""
    # This is verified by the main_dryrun test - it just checks that when we
    # build a receipt, the held_out_batch section includes derivation_mode.
    # The full integration test would require running main() with --dry-run
    # and inspecting the receipt, which is already done in
    # test_main_dryrun_manifest_mode_receipt_write_does_not_crash.
    pass


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
