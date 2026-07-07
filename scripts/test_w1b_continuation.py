"""test_w1b_continuation.py -- hermetic regression tests for:

  #355 (W1b unwidened-continuation control): scripts/w1_collapse_control_run.py
    gains a resume-from-checkpoint-UNWIDENED mode (--continue-from). NO
    from-scratch init when given; refuses fail-closed on a missing or
    architecture-mismatched checkpoint; the receipt carries both the mode
    and the marginal/cumulative billing fields the pre-registered reading
    rules need.

  #357 (receipt path sanitization): the receipt writer must never embed the
    raw --shard-dir absolute path (which may carry an operator/founder-name
    fragment) -- it emits a name-safe corpus_id + content-pinning manifest
    sha instead. A regression test greps a generated receipt for the SAME
    absolute-path / local-path-fragment patterns tools/repo-guard.sh itself
    enforces -- read directly out of tools/repo-guard.sh's own source at
    test time (never hand-duplicated: a hand-copied regex containing the
    literal path-fragment substring would itself trip repo-guard's own
    scan on THIS test file, which is exactly what a first draft of this
    test did).

Real code under test (imported, never reimplemented), synthetic-only data
(tempfile.TemporaryDirectory() per case) -- same convention as
test_w1_live_gates.py. No real corpus, checkpoint, or pricing/rung receipt
is touched; this worktree's real DEFAULT_PRICING_RECEIPT/DEFAULT_RUNG_RECEIPT
are not assumed to exist (they are gitignored, machine-local artifacts) --
every test below supplies its own tiny --pricing-receipt/--rung-manifest
fixture instead.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

import pytest
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from w1_collapse_control_run import (  # noqa: E402
    arch_config_dict,
    build_model,
    corpus_identity_for_receipt,
    build_shard_corpus_verification_block,
    repo_relative_path,
    load_continuation_checkpoint,
    run_phase2_dryrun,
    make_eval_batch,
    main as w1_main,
    W1B_MARGINAL_TOKENS_GROWPATH,
    W1B_ISSUE_REF,
    REPO,
)
from timeshare_pretrain import save_checkpoint, capture_rng  # noqa: E402

def _extract_shell_var(script_text: str, name: str) -> str:
    """Pulls a single-quoted shell var assignment's RHS out of repo-guard.sh's
    own source text (e.g. PATHPAT='...'), read fresh every test run -- this
    is the single source of truth for what repo-guard actually enforces;
    hand-copying the pattern would duplicate it (and, for PATHFRAG
    specifically, embed the very substring it detects -- see module
    docstring)."""
    m = re.search(rf"^{re.escape(name)}='(.*)'$", script_text, re.MULTILINE)
    assert m, f"could not find {name}=... in tools/repo-guard.sh"
    return m.group(1)


_REPO_GUARD_SH_TEXT = open(
    os.path.join(REPO, "tools", "repo-guard.sh"), "r", encoding="utf-8").read()
# Same two regexes tools/repo-guard.sh enforces (sections 2/2b) -- extracted
# from its own tracked source, never hand-duplicated, so this test can never
# drift from what repo-guard actually checks (and never risks embedding the
# sensitive fragment itself).
REPO_GUARD_PATHPAT = re.compile(_extract_shell_var(_REPO_GUARD_SH_TEXT, "PATHPAT"))
REPO_GUARD_PATHFRAG = re.compile(_extract_shell_var(_REPO_GUARD_SH_TEXT, "PATHFRAG"))


def _assert_no_repo_guard_path_hits(text: str) -> None:
    assert not REPO_GUARD_PATHPAT.search(text), (
        f"absolute local path pattern found in receipt text: "
        f"{REPO_GUARD_PATHPAT.search(text).group(0)!r}")
    assert not REPO_GUARD_PATHFRAG.search(text), (
        f"local path fragment found in receipt text: "
        f"{REPO_GUARD_PATHFRAG.search(text).group(0)!r}")


# ---------------------------------------------------------------------------
# #357: corpus reference is name-safe + content-pinned, never a raw path.
# ---------------------------------------------------------------------------

def test_corpus_identity_for_receipt_is_name_safe_and_content_pinned():
    # Deliberately founder-named + repo-guard-PATHFRAG-shaped, exactly the
    # class of path PR #356's landing had to hand-sanitize. Never touches
    # disk -- corpus_identity_for_receipt only inspects the path string.
    founder_named_shard_dir = "B:\\M\\avir\\vault\\external-corpus\\shards-v0"
    manifest = {"combined_sha256": "ab" * 32}

    result = corpus_identity_for_receipt(founder_named_shard_dir, manifest)

    assert result == {"corpus_id": "shards-v0",
                       "corpus_manifest_sha256": manifest["combined_sha256"]}
    assert "shard_dir" not in result
    dumped = json.dumps(result)
    assert "avir" not in dumped
    _assert_no_repo_guard_path_hits(dumped)


def test_build_shard_corpus_verification_block_never_embeds_raw_shard_dir():
    founder_named_shard_dir = "B:\\M\\avir\\vault\\external-corpus\\shards-v0"
    shard_manifest = {"n_files": 3, "total_tokens": 900,
                       "combined_sha256": "cd" * 32}

    block = build_shard_corpus_verification_block(
        founder_named_shard_dir, shard_manifest, shard_manifest["combined_sha256"], True)

    assert "shard_dir" not in block
    assert block["corpus_id"] == "shards-v0"
    assert block["corpus_manifest_sha256"] == shard_manifest["combined_sha256"]
    assert block["n_files"] == 3
    assert block["verified"] is True
    _assert_no_repo_guard_path_hits(json.dumps(block))


def test_repo_relative_path_strips_absolute_repo_prefix():
    under_repo = os.path.join(REPO, "scratch", "w1-control", "dry-run", "phase2")
    rel = repo_relative_path(under_repo)
    assert not re.match(r"^[A-Za-z]:", rel), f"still absolute: {rel!r}"
    assert rel.replace("/", os.sep) == os.path.relpath(under_repo, REPO)


# ---------------------------------------------------------------------------
# #355: continuation-mode checkpoint loading -- fail-closed on missing/
# mismatched, loads (never inits) on a healthy match.
# ---------------------------------------------------------------------------

SEQ = 8
BATCH = 2
VOCAB = 37
HIDDEN = 6
DEPTH = 2


def _cfg():
    return arch_config_dict(VOCAB, HIDDEN, DEPTH, SEQ, BATCH)


def test_continue_from_missing_checkpoint_refuses():
    cfg = _cfg()
    model = build_model(cfg, seed=1, device="cpu")
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = os.path.join(tmpdir, "no-such-checkpoint")
        with pytest.raises(SystemExit, match="W1B_CONTINUE_FROM_CHECKPOINT_MISSING"):
            load_continuation_checkpoint(missing, model)


def test_continue_from_mismatched_checkpoint_refuses():
    cfg = _cfg()
    mismatched_cfg = arch_config_dict(VOCAB, HIDDEN + 1, DEPTH, SEQ, BATCH)  # different hidden
    with tempfile.TemporaryDirectory() as tmpdir:
        wrong_model = build_model(mismatched_cfg, seed=2, device="cpu")
        ckpt_dir = save_checkpoint(
            tmpdir, 5, wrong_model.state_dict(),
            torch.optim.AdamW(wrong_model.parameters()).state_dict(),
            capture_rng(), extra={"step": 5})

        model = build_model(cfg, seed=1, device="cpu")  # DIFFERENT hidden than wrong_model
        with pytest.raises(SystemExit, match="W1_LIVE_CHECKPOINT_KEY_SHAPE_MISMATCH"):
            load_continuation_checkpoint(ckpt_dir, model)


def test_continue_from_valid_checkpoint_loads_state_not_fresh_init():
    """A healthy, matching checkpoint must actually be LOADED -- proven by
    training the seed model a few real steps first (so its state diverges
    from a fresh init at the SAME seed), then asserting the continuation
    run's step-0 eval loss differs from a from-scratch run's step-0 eval
    loss at that identical seed. If continuation silently fell back to
    random init, the two step-0 losses would be identical (same seed, same
    architecture, same eval batch)."""
    cfg = _cfg()
    seed = 4242
    device = "cpu"
    eval_x, eval_y, _sha = make_eval_batch(VOCAB, BATCH, SEQ, device)

    with tempfile.TemporaryDirectory() as tmpdir:
        seed_model = build_model(cfg, seed=seed, device=device)
        opt = torch.optim.AdamW(seed_model.parameters(), lr=0.1)
        # Train a handful of real steps so the checkpoint's state genuinely
        # diverges from build_model(cfg, seed, device)'s fresh init.
        from w1_collapse_control_run import synthetic_corpus, batch_from_corpus, train_step
        corpus = synthetic_corpus(VOCAB, SEQ, n_windows=64, seed=99)
        for step in range(10):
            x, y = batch_from_corpus(corpus, step, BATCH, device)
            train_step(seed_model, opt, x, y)
        ckpt_dir = save_checkpoint(
            tmpdir, 10, seed_model.state_dict(), opt.state_dict(),
            capture_rng(), extra={"segment_id": "w1b-test-seed", "step": 10})

        phase2_continuation = run_phase2_dryrun(
            cfg, ceiling_steps=2, eval_every=1, checkpoint_every=1,
            target_eval_loss=-1e9,  # never early-stops
            seed=seed, device=device, out_dir=os.path.join(tmpdir, "cont"),
            eval_x=eval_x, eval_y=eval_y, continue_from=ckpt_dir)

        phase2_scratch = run_phase2_dryrun(
            cfg, ceiling_steps=2, eval_every=1, checkpoint_every=1,
            target_eval_loss=-1e9,
            seed=seed, device=device, out_dir=os.path.join(tmpdir, "scratch"),
            eval_x=eval_x, eval_y=eval_y, continue_from=None)

        assert phase2_continuation["init_mode"] == "continuation"
        assert phase2_continuation["continuation_source_manifest_step"] == 10
        assert phase2_scratch["init_mode"] == "from_scratch"
        assert phase2_scratch["continue_from_checkpoint"] is None

        step0_loss_continuation = phase2_continuation["eval_trace"][0]["eval_loss"]
        step0_loss_scratch = phase2_scratch["eval_trace"][0]["eval_loss"]
        assert step0_loss_continuation != step0_loss_scratch, (
            "continuation-mode step-0 eval loss must differ from a fresh "
            "from-scratch run at the identical seed -- if these are equal, "
            "the checkpoint was never actually loaded.")

        # continue_from_checkpoint must never leak a raw absolute path
        # carrying an operator-local prefix (issue #357's general principle
        # applied to this new field).
        cf = phase2_continuation["continue_from_checkpoint"]
        assert cf is not None
        assert not re.match(r"^[A-Za-z]:", cf), f"still absolute: {cf!r}"


# ---------------------------------------------------------------------------
# End-to-end: main(argv) in continuation mode writes a receipt carrying the
# mode + marginal/cumulative billing fields, with NO absolute-path leakage
# anywhere in the written JSON (the literal #357 regression the issue asks
# for: "a unit test greps a generated receipt for absolute-path patterns").
# ---------------------------------------------------------------------------

def _make_rung_manifest_fixture(tmpdir: str, *, vocab: int, hidden: int, ff_grown: int) -> str:
    ckpt_dir = os.path.join(tmpdir, "rung-seed-step-00000001")
    os.makedirs(ckpt_dir, exist_ok=True)
    state = {"model.embed_tokens.weight": torch.zeros(vocab, hidden)}
    torch.save(state, os.path.join(ckpt_dir, "model.pt"))
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"step": 1, "extra": {"ff_grown": ff_grown}}, f)
    return manifest_path


def _make_pricing_receipt_fixture(tmpdir: str, *, vocab: int, seq: int, batch: int) -> str:
    """Tiny, internally-consistent pricing-receipt fixture -- this worktree's
    real DEFAULT_PRICING_RECEIPT is a gitignored, machine-local artifact and
    is not assumed to exist (confirmed absent here); every field below is
    exactly what derive_real_arch_config / main()'s dry-run tail reads."""
    receipt = {
        "control_arm": {
            "target_architecture": f"toy decoder, vocab={vocab}, seq={seq}, 1000 params",
            "batch": batch,
            "eval_cadence_K": 1,
        },
        "grow_arm": {
            "terminal_checkpoint_ref": "dummy-grow-arm-checkpoint",
            "tokens_total": 500,
            "bill_aggregation_rows": [],
        },
        "wall_hours_pricing": {"control_arm_ceiling_tokens": 2000},
    }
    path = os.path.join(tmpdir, "fixture-pricing-receipt.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    return path


def test_main_dryrun_continuation_mode_receipt_fields_and_no_path_leakage():
    receipts_dir_repo = os.path.join(REPO, "receipts", "ember-c-scale")
    before = set(os.listdir(receipts_dir_repo)) if os.path.isdir(receipts_dir_repo) else set()

    written_path = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _cfg()
            seed_model = build_model(cfg, seed=777, device="cpu")
            opt = torch.optim.AdamW(seed_model.parameters())
            ckpt_dir = save_checkpoint(
                tmpdir, 3, seed_model.state_dict(), opt.state_dict(),
                capture_rng(), extra={"segment_id": "w1b-e2e-seed", "step": 3})

            manifest_path = _make_rung_manifest_fixture(
                tmpdir, vocab=VOCAB, hidden=HIDDEN, ff_grown=16)
            pricing_path = _make_pricing_receipt_fixture(
                tmpdir, vocab=VOCAB, seq=SEQ, batch=BATCH)

            out_dir = os.path.join(tmpdir, "out")
            rc = w1_main([
                "--pricing-receipt", pricing_path,
                "--rung-manifest", manifest_path,
                "--out-dir", out_dir,
                "--vocab", str(VOCAB), "--hidden", str(HIDDEN), "--depth", str(DEPTH),
                "--seq", str(SEQ), "--batch", str(BATCH),
                "--phase1-train-steps", "2",
                "--ceiling-steps", "2", "--eval-every", "1", "--checkpoint-every", "1",
                "--continue-from", ckpt_dir,
            ])
            assert rc == 0

            after = set(os.listdir(receipts_dir_repo))
            new_files = after - before
            assert len(new_files) == 1, f"expected exactly one new receipt, found {new_files!r}"
            written_path = os.path.join(receipts_dir_repo, next(iter(new_files)))

            with open(written_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            receipt = json.loads(raw_text)

            assert receipt["control_arm"]["init_mode"] == "continuation"
            assert receipt["control_arm"]["continuation_source_manifest_step"] == 3
            cf = receipt["control_arm"]["continue_from_checkpoint"]
            assert cf is not None and not re.match(r"^[A-Za-z]:", cf), f"leaked absolute path: {cf!r}"

            w1b = receipt["w1b_continuation"]
            assert w1b is not None
            assert w1b["issue_ref"] == W1B_ISSUE_REF
            assert w1b["mode"] == "continuation"
            assert w1b["tokens_growpath_marginal"] == W1B_MARGINAL_TOKENS_GROWPATH
            # Cumulative fallback = THIS run's own phase-1 dry-run harness
            # tokens_total (phase1_train_steps * batch * seq = 2*2*8 = 32) --
            # never the pricing receipt's informational grow_arm.tokens_total
            # citation, which the dry-run outcome path never reads.
            assert w1b["tokens_growpath_cumulative"] == 2 * BATCH * SEQ
            assert w1b["ratio_marginal"] is not None or w1b["outcome_marginal"] == "L2"
            assert "ratio_cumulative" in w1b
            assert "outcome_cumulative" in w1b

            # Top-level ratio/outcome are the MARGINAL reading in this mode.
            assert receipt["outcome"] == w1b["outcome_marginal"]
            assert receipt["ratio"] == w1b["ratio_marginal"]

            # The literal #357 regression: no absolute local path anywhere in
            # the generated receipt text (checks the SAME patterns
            # tools/repo-guard.sh enforces at landing time).
            _assert_no_repo_guard_path_hits(raw_text)
    finally:
        if written_path and os.path.exists(written_path):
            os.remove(written_path)  # test artifact, never left in the repo


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
