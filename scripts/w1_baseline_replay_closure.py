# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""w1_baseline_replay_closure.py -- W1 step25->step50 REPLAY closure (#735 Leg A).

Issue #735 names the ONE closure gap on the closest trustworthy salvage
baseline in the program (W1 real random-init final-width control,
w1-live-20260707T110231Z, commit 56a85a4, config 83bca6..., corpus
aa48f6ee...): the live run exited on match at step 50 WITHOUT ever saving a
step50 checkpoint -- only the certified step25 resume checkpoint persists.

THIS IS A REPLAY, NOT A REIMPLEMENTATION. Every model/data/optimizer/eval
code path is IMPORTED from src/ember/governance/scripts/w1_collapse_control_run.py and
scripts/timeshare_pretrain.py -- the exact modules the live run used (see
receipts/ember-c-scale/w1-fp32-check-20260707T114517Z.json's own "All model/
eval code imported ... never reimplemented" method line, and
scripts/w1b_fp32_check.py, the prior landed instance of this exact reuse
discipline for a sibling fp32-reeval script). This file never constructs a
model class, a data generator, or an eval loop of its own -- it is a thin
orchestrator around historical modules.

Pipeline:

  1. PREFLIGHT (always executes for real, never a self-attested stub): every
     leg produces a MEASURED value compared against a receipt-pinned value --
     re-hash of the grow checkpoint (used to derive real_arch) and the
     certified control step25 checkpoint against
     receipts/ember-c-scale/w1-certification-check-20260707T114707Z.json's
     pinned per-file shas, config_sha re-derivation, decontam receipt
     identity, corpus combined-sha (LIVE recompute when --shard-dir resolves
     on disk here, else the receipted-verification-chain: the corpus-
     verification receipt's own file bytes re-hashed and its cited
     combined_sha256 compared -- still measured, never a bare assumption),
     and the certified eval batch's sha256 (live rebuild when a loader is
     available, else the decontam receipt's own pinned figure re-hashed and
     compared).

  2. REPLAY: loads the certified step25 checkpoint (model+optimizer+RNG) via
     the SAME load_checkpoint/load_optimizers_state/restore_rng sequence the
     original run's own in-run resume-test used (run_phase2_live's
     resume_proof block, RESUME_BIT_EXACT), then replays the historical
     REMAINING update indices 25..49 inclusive-exclusive (25 updates -- the
     exact updates that took the original run's step-25 state to its
     step-50 state; the original loop's `while step < ceiling_steps` reads
     loader.batch(step, ...) BEFORE incrementing `step`, so the updates that
     produced step k from step k-1 used loader.batch(k-1, ...) -- the 25
     updates from step25 to step50 are indices 25..49, never a naive
     26..50) via the SAME loader.batch(step, batch)/apply_cosine_warmup/
     train_step_matched_recipe calls, at the SAME ceiling_steps=1533
     (REAL_HARD_CEILING_STEPS) total-steps schedule denominator the original
     live run used for its cosine+warmup LR multiplier (so the trajectory is
     byte-identical to the original run's own steps 25..49, not a rescaled
     0..24 or 25..49-over-50 schedule).

  3. SAVE step50 -- the missing artifact -- via the SAME save_checkpoint call
     run_phase2_live itself uses at its own checkpoint boundaries.

  4. Reload step50 FROM BYTES (never the in-memory model) and re-eval both
     BF16 and FP32 on the frozen, sha-pinned eval batch, THEN apply the
     reloaded optimizer + RNG state to a FRESH optimizer/model build and
     parity-check that too -- proving the closed checkpoint is a genuine
     RESUME point (model + optimizer + RNG), not merely a model-weights
     snapshot. TRUSTWORTHY iff ALL SIX conjuncts hold: the step25 load
     matches its receipted BF16 figure, the step50 post-replay eval matches
     its receipted BF16 figure, the step50 reload-from-bytes is bit-exact
     against the pre-save in-memory eval, the reloaded FP32 loss matches the
     receipted terminal FP32 value (9.245222091674805, receipts/ember-
     c-scale/w1-fp32-check-20260707T114517Z.json) within --fp32-tolerance,
     the reloaded optimizer state has shape parity with what was saved
     (optimizer_state_shape_parity, reused verbatim), and the reloaded RNG
     state round-trips bit-exact. Any single conjunct failing is
     REPLAY_DIVERGED -- an investigation, never a shrug. In claim-bearing
     mode (claim_bearing=True, the default and the only mode --live uses)
     every receipted expectation is a REQUIRED input: a missing (None)
     expectation refuses to run rather than trivially passing that conjunct;
     the None-trivially-passes path is legal only under claim_bearing=False
     (selftest discovery only).

  5. CUSTODY: move (never copy-and-leave) the closed step50 checkpoint out of
     scratch/ into a models/ custody dir, per issue #677's checkpoint-
     custody addendum ("checkpoints that outlive their run must be moved/
     hardlinked to a custody path outside any worktree ... with the manifest
     recording the custody move"). Per-file sha256 is measured BEFORE and
     AFTER the move and asserted equal -- the move is never trusted to have
     preserved bytes, it is measured to have. --skip-custody-move (diagnostic
     use only) does NOT silently keep a trustworthy verdict: the CLOSURE
     verdict (distinct from the replay verdict) is downgraded to the
     non-promotable REPLAY_TRUSTWORTHY_NO_CUSTODY_NONPROMOTABLE and main()
     exits nonzero, even when the replay itself checked out clean.

  6. One closed receipt chaining 1-5, written via receipt_write.checked_write
     (schema-validated, same convention as every other receipt in this
     repo). Verdict label (when trustworthy + custodied, i.e. closure
     verdict == exactly "REPLAY_TRUSTWORTHY"):
     W1_FROM_SCRATCH_PILOT_BASELINE (narrow by construction: pilot scale,
     single seed, from-scratch final width -- disclosed, per #735's own
     framing; NOT a claim this closure receipt itself asserts as prose).

--selftest: CPU-only synthetic fixtures, no GPU, no real corpus, no real
checkpoints:
  (a) wrong-sha refusal -- a deliberately wrong expected-sha dict is refused
      fail-closed; the correct dict passes.
  (b) save->reload identity plumbing -- a checkpoint saved from one model
      instance and loaded into a FRESH, differently-seeded instance
      reproduces bit-exact eval loss.
  (c1)-(c5) replay_and_close() verdict-conjunction proof -- a discovery pass
      (claim_bearing=False) learns the fixture's own true bf16/fp32 figures,
      then a claim-bearing correct-path pass asserts all six conjuncts True
      (verdict REPLAY_TRUSTWORTHY), then FOUR independent negative fixtures
      each flip exactly ONE of the four receipted-comparison conjuncts
      (wrong step25-BF16 expectation / wrong step50-BF16 expectation /
      post-save checkpoint-bytes corruption via
      _corrupt_checkpoint_model_weights_for_test / wrong FP32 expectation)
      and assert the OTHER conjuncts stay True while verdict becomes
      REPLAY_DIVERGED -- proving the gate actually gates on every conjunct
      independently, not a subset.
  (d) API-conformance -- constructs the REAL model/loader/optimizer/CE
      objects via the historical modules against a tiny synthetic config and
      runs one train step + eval, proving the import signatures this script
      depends on have not drifted. No GPU, no real corpus needed.
  (e) claim-bearing missing-expected refusal -- claim_bearing=True (the
      --live default) with any receipted expectation left None refuses to
      run (W1_REPLAY_CLAIM_BEARING_MISSING_EXPECTED) rather than trivially
      passing that conjunct.

Real GPU replay is gated behind the SAME interlock
w1_collapse_control_run.refuse_unless_dry_run_safe already enforces
(EMBER_GATE_AUTHORIZED=1 AND --live AND --device cuda AND --shard-dir AND
EMBER_W1_MAINTAINER_WINDOW_CONFIRMED=1), reused verbatim -- never
reimplemented -- plus the standard VRAM governor
(timeshare_pretrain._apply_governor) before any model build. Never fired by
this builder; GPU dispatch is coordinator-scheduled.

Usage:
  python scripts/w1_baseline_replay_closure.py --selftest
  python scripts/w1_baseline_replay_closure.py                 # preflight-only, CPU-safe
  EMBER_GATE_AUTHORIZED=1 EMBER_W1_MAINTAINER_WINDOW_CONFIRMED=1 \\
      python scripts/w1_baseline_replay_closure.py --live --device cuda \\
      --shard-dir <real shard dir>                              # coordinator dispatch only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import torch  # noqa: E402

from w1_collapse_control_run import (  # noqa: E402 -- reused, never edited
    load_json, sha256_file, sha256_tokens, config_sha, real_config_dict,
    derive_real_arch_config, derive_rung_receipt_from_manifest,
    build_real_model, verify_checkpoint_key_shape_parity, eval_loss_fn,
    rebuild_batch_from_decontam_receipt, apply_cosine_warmup,
    train_step_matched_recipe, verify_shard_corpus, refuse_unless_dry_run_safe,
    optimizer_state_shape_parity,
    DEFAULT_PRICING_RECEIPT, REAL_HARD_CEILING_STEPS,
    CORPUS_MANIFEST_COMBINED_SHA256_EXPECTED, MATCHED_RECIPE_SCHEDULE_SOURCE,
)
from timeshare_pretrain import (  # noqa: E402 -- reused, never edited
    load_checkpoint, save_checkpoint, read_manifest, capture_rng, restore_rng,
    check_resume_integrity, PackedShardLoader, build_split_optimizer,
    save_optimizers_state, load_optimizers_state, resolve_ce_impl,
    _apply_governor, CONTRACT_PATH as PRETRAIN_CONTRACT_PATH,
)
from receipt_write import checked_write  # noqa: E402

# ---------------------------------------------------------------------------
# Pinned figures -- every value below is cited from a specific receipt, never
# invented. Source receipts:
#   receipts/ember-c-scale/w1-launch-receipt-20260707T110231Z.json
#   receipts/ember-c-scale/w1-certification-check-20260707T114707Z.json
#   receipts/ember-c-scale/w1-fp32-check-20260707T114517Z.json
#   receipts/ember-c-scale/w1-collapse-control-20260707T110256Z.json
# ---------------------------------------------------------------------------

ISSUE_REF = "#735"
HISTORICAL_RUN_TS = "20260707T110231Z"

DEFAULT_RUNG_MANIFEST = os.path.join(
    "models", "cbase-grow-rung", "rung1-20260703T155447Z", "stabilize",
    "checkpoints", "step-00000766", "manifest.json")
DEFAULT_GROW_CHECKPOINT_DIR = os.path.join(
    "models", "cbase-grow-rung", "rung1-20260703T155447Z", "stabilize",
    "checkpoints", "step-00000766")
DEFAULT_CONTROL_STEP25_DIR = os.path.join(
    "scratch", "w1-control", "live", f"w1-live-{HISTORICAL_RUN_TS}",
    "phase2-live", "checkpoints", "step-00000025")
# PROVENANCE RULING (team-lead, coordinator-verified in git): the decontam
# receipt the launch/certification receipts CITE
# (w2-heldout-decontam-20260707T055843Z.json) NEVER LANDED in git history --
# only a CRASHED-20260707T034418Z sibling survives, in one worktree, never
# committed. The file below IS the committed substitute: commit 5abbc54
# ("w2 decontam-batch regen", #118/#455) landed it and updated the stale
# DECONTAM_RECEIPT_DEFAULT constant in w1_collapse_control_run.py. This is a
# disclosed substitution, never a silent swap -- its identity claim is
# `batch_sha256` inside the substitute file being BYTE-EQUAL to the launch-
# pinned eval-batch sha (EXPECTED_EVAL_BATCH_SHA256 below); the file-identity
# check against EXPECTED_DECONTAM_RECEIPT_SHA256 is a secondary integrity
# assert, not the load-bearing one. See PROVENANCE_NOTE_DECONTAM_SUBSTITUTION.
DEFAULT_DECONTAM_RECEIPT = os.path.join(
    "receipts", "ember-c-scale", "w2-heldout-decontam-20260708T121128Z.json")
PROVENANCE_NOTE_DECONTAM_SUBSTITUTION = (
    "decontam receipt substitution (disclosed, coordinator-ruled): the "
    "original receipt cited by the launch/certification chain "
    "(w2-heldout-decontam-20260707T055843Z.json) never landed in git "
    "history -- only a CRASHED-20260707T034418Z sibling survives, "
    "uncommitted, in one worktree. The substitute used here "
    "(w2-heldout-decontam-20260708T121128Z.json, landed in commit "
    "5abbc54975f3e4c8efe6eaf77d9595a59201a3c5, 'w2 decontam-batch regen', "
    "#118/#455) is verified identical in the identity that matters: its "
    "batch_sha256 field is byte-equal to the launch-pinned eval-batch sha "
    "(91069e33b402b6a91267e59dfbeb02da96ddcbe683bc091817461fad79358929). "
    "This is a disclosed substitution, not a silent swap.")
DEFAULT_CUSTODY_ROOT = os.path.join("models", "w1-baseline-replay-custody")
# Committed public-repo edition of the corpus-verification receipt (issue
# #77) -- the literal path w1_collapse_control_run.CORPUS_VERIFICATION_RECEIPT
# cites (receipts/corpus-verification-20260704T095213Z.json, no suffix) does
# not exist in this tree; only the redacted edition is committed. Confirmed
# by directory listing, not guessed -- never silently substituted without
# disclosure (this comment IS the disclosure).
CORPUS_VERIFICATION_RECEIPT_DRY_CITE = os.path.join(
    "receipts", "corpus-verification-20260704T095213Z-redacted-edition.json")

# --- checkpoint manifest re-hash targets (w1-certification-check receipt) --
GROW_CHECKPOINT_EXPECTED_SHA256 = {
    "model.pt": "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b",
    "optimizer.pt": "a7f8ec8420ab4eebb0782218172ff3e36a6142c0fdf3affaf973f28973ad7ad1",
    "rng.pt": "2e30b6c87ed2e1edb9d4077e569da2115c2377d952bf256071ad93e990c8e6c7",
}
CONTROL_STEP25_EXPECTED_SHA256 = {
    "model.pt": "3fa4ca09db7d749cb68e470ff07cd66d53706512e212a8482124a8872d55deac",
    "optimizer.pt": "d52f5969887725551574a01c920342dff491a0f95cdff97ba4fe3511d83a70b0",
    "rng.pt": "c9ca61ab0e5fb9661e54dc9bb2df294f3828390829c997330f9290a02aabc379",
}
EXPECTED_CONFIG_SHA256 = "83bca66bffafe80ed5d2b4b7098c09ff5c562a04bf7ff9d6fb23f2d0a6ce0869"
EXPECTED_DECONTAM_RECEIPT_SHA256 = "40dfd9ecdd65cb74fb83d02b82c81c01aff1dd4586720847101cfb434452ec1a"
EXPECTED_EVAL_BATCH_SHA256 = "91069e33b402b6a91267e59dfbeb02da96ddcbe683bc091817461fad79358929"

# --- terminal-receipt-cited scalar figures ---------------------------------
EXPECTED_TARGET_EVAL_LOSS = 9.375
EXPECTED_STEP25_EVAL_LOSS_BF16 = 10.0     # w1-live-progress row step=25
EXPECTED_STEP50_EVAL_LOSS_BF16 = 9.25     # w1-live-progress row step=50
EXPECTED_STEP50_EVAL_LOSS_FP32 = 9.245222091674805  # w1-fp32-check control_arm_step50

PHASE2_SEED_HISTORICAL = 2002             # control_arm.init_seed
REPLAY_START_STEP = 25                    # inclusive
REPLAY_END_STEP = 50                      # exclusive -- 25 updates, 25..49
DEFAULT_FP32_TOLERANCE = 1e-3

SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint/corpus/receipt files; sha256 over the "
    "raw int64 token bytes of concat([x, y], dim=1) (sha256_tokens "
    "convention, same as the rest of the W1 chain) for the eval batch")


def resolve(repo_root: str, path: str) -> str:
    """Repo-relative paths resolve under repo_root; an already-absolute path
    (e.g. an external shard mount) passes through unchanged. Same helper as
    scripts/w1b_fp32_check.py's own resolve()."""
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


# ---------------------------------------------------------------------------
# Checkpoint manifest re-hash (never trusts a checkpoint's OWN manifest.json
# as ground truth -- compares against a value that lives OUTSIDE the
# checkpoint dir).
# ---------------------------------------------------------------------------

def _verify_checkpoint_manifest(ckpt_dir: str, expected_files: dict) -> dict:
    """Pure, non-raising: re-hash ckpt_dir's named files against
    expected_files and report per-file pass/fail. Never trusts the
    checkpoint's own manifest.json values -- reads them only for the
    (informational) step number, and independently re-hashes every file
    named in expected_files against the caller-supplied ground truth."""
    manifest = read_manifest(ckpt_dir)
    measured = {fname: sha256_file(os.path.join(ckpt_dir, fname))
                for fname in expected_files}
    per_file_match = {fname: measured[fname] == expected_files[fname]
                       for fname in expected_files}
    ok = all(per_file_match.values())
    return {"dir": ckpt_dir, "manifest_step": manifest.get("step"),
            "measured_sha256": measured, "expected_sha256": expected_files,
            "per_file_match": per_file_match, "pass": ok}


def _refuse_unless_manifest_matches(ckpt_dir: str, expected_files: dict) -> dict:
    """Fail-closed wrapper over _verify_checkpoint_manifest -- raises
    SystemExit naming exactly which file(s) mismatched."""
    result = _verify_checkpoint_manifest(ckpt_dir, expected_files)
    if not result["pass"]:
        mismatched = [f for f, ok in result["per_file_match"].items() if not ok]
        raise SystemExit(
            f"W1_REPLAY_CHECKPOINT_SHA_MISMATCH: {ckpt_dir!r} mismatched "
            f"files={mismatched!r} measured={result['measured_sha256']!r} "
            f"expected={result['expected_sha256']!r}")
    return result


# ---------------------------------------------------------------------------
# Preflight -- always executes for real; never a self-attested stub. Every
# leg below produces a MEASURED value compared against a receipt-pinned
# value. Collects ALL legs before refusing (so a failing preflight receipt
# names every failing leg, not just the first).
# ---------------------------------------------------------------------------

def preflight_verify(*, repo_root: str, pricing_receipt_path: str,
                      rung_manifest_path: str, grow_checkpoint_dir: str,
                      control_step25_dir: str, decontam_receipt_path: str,
                      shard_dir: "str | None", corpus_expected_sha: "str | None",
                      loader_for_batch_rebuild=None, device: str) -> tuple:
    result: dict = {}

    # Legs 1-2: checkpoint manifest re-hash (grow arm real_arch is derived
    # from + the certified control step25 resume checkpoint).
    result["grow_checkpoint_manifest_check"] = _verify_checkpoint_manifest(
        grow_checkpoint_dir, GROW_CHECKPOINT_EXPECTED_SHA256)
    result["control_step25_checkpoint_manifest_check"] = _verify_checkpoint_manifest(
        control_step25_dir, CONTROL_STEP25_EXPECTED_SHA256)

    # Leg 3: real_arch + config_sha re-derivation, from the SAME two inputs
    # (pricing receipt + rung manifest) the original live run's own
    # main_live used -- never guessed, never hardcoded.
    pricing_receipt = load_json(pricing_receipt_path)
    rung_receipt = derive_rung_receipt_from_manifest(rung_manifest_path)
    real_arch = derive_real_arch_config(pricing_receipt, rung_receipt)
    measured_config_sha = config_sha(real_config_dict(real_arch))
    result["config_sha_check"] = {
        "measured": measured_config_sha, "expected": EXPECTED_CONFIG_SHA256,
        "pass": measured_config_sha == EXPECTED_CONFIG_SHA256}

    # Leg 4: decontam receipt identity (the receipt that pins WHICH windows
    # are held out).
    decontam_sha = sha256_file(decontam_receipt_path)
    result["decontam_receipt_sha_check"] = {
        "path": decontam_receipt_path, "measured": decontam_sha,
        "expected": EXPECTED_DECONTAM_RECEIPT_SHA256,
        "pass": decontam_sha == EXPECTED_DECONTAM_RECEIPT_SHA256}
    decontam_receipt = load_json(decontam_receipt_path)

    # Leg 5: corpus combined-sha -- LIVE recompute when shard_dir resolves on
    # disk in THIS invocation's environment, else the receipted-verification
    # chain (the corpus-verification receipt's own bytes re-hashed and its
    # cited combined_sha256 extracted and compared -- still measured, never
    # a bare cite).
    if shard_dir and os.path.isdir(shard_dir):
        manifest = verify_shard_corpus(
            shard_dir, expected_combined_sha256=(corpus_expected_sha or None))
        result["corpus_check"] = {
            "mode": "live_recompute", "shard_dir": shard_dir,
            "measured_combined_sha256": manifest["combined_sha256"],
            "expected": corpus_expected_sha,
            "pass": (not corpus_expected_sha
                     or manifest["combined_sha256"] == corpus_expected_sha)}
    else:
        cv_path = resolve(repo_root, CORPUS_VERIFICATION_RECEIPT_DRY_CITE)
        cv_bytes_sha = sha256_file(cv_path)
        with open(cv_path, "r", encoding="utf-8") as f:
            cv_raw = f.read()
        m = re.search(r"combined_sha256\s*=\s*([0-9a-f]{64})", cv_raw)
        cited_combined = m.group(1) if m else None
        result["corpus_check"] = {
            "mode": "receipted_verification_chain_dry",
            "note": (f"shard_dir {shard_dir!r} not present in this "
                     "invocation's environment (the real corpus is a "
                     "maintainer-window external mount) -- live recompute "
                     "deferred to the GPU-dispatch leg; this leg measures "
                     "the corpus-verification receipt's own file bytes and "
                     "regex-extracts its cited combined_sha256, never a "
                     "bare assumption"),
            "corpus_verification_receipt_path": cv_path,
            "corpus_verification_receipt_sha256": cv_bytes_sha,
            "cited_combined_sha256": cited_combined,
            "expected": corpus_expected_sha,
            "pass": (not corpus_expected_sha or cited_combined == corpus_expected_sha)}

    # Leg 6: eval batch rebuild + sha assert, over the certified decontam
    # receipt -- live rebuild when a loader is available, else the decontam
    # receipt's own pinned batch_sha256 re-cited (already independently
    # re-hashed by leg 4 above as the receipt FILE's identity; this compares
    # its internal pinned field instead of a fresh window rebuild).
    if loader_for_batch_rebuild is not None:
        eval_x, eval_y, eval_sha = rebuild_batch_from_decontam_receipt(
            loader_for_batch_rebuild, decontam_receipt, device)
        result["eval_batch_check"] = {
            "mode": "live_rebuild", "measured": eval_sha,
            "expected": EXPECTED_EVAL_BATCH_SHA256,
            "pass": eval_sha == EXPECTED_EVAL_BATCH_SHA256}
    else:
        cited = decontam_receipt.get("batch_sha256")
        result["eval_batch_check"] = {
            "mode": "receipted_cite_dry",
            "note": ("no loader given (dry preflight-only invocation, no "
                     "--shard-dir on disk here) -- citing the decontam "
                     "receipt's own pinned batch_sha256; live rebuild runs "
                     "once a real loader is available (GPU-dispatch leg)"),
            "cited": cited, "expected": EXPECTED_EVAL_BATCH_SHA256,
            "pass": cited == EXPECTED_EVAL_BATCH_SHA256}
        eval_x = eval_y = None

    result["real_arch"] = real_arch
    result["pricing_receipt_path"] = pricing_receipt_path
    result["pricing_receipt_sha256"] = sha256_file(pricing_receipt_path)
    result["rung_manifest_path"] = rung_manifest_path
    result["rung_manifest_sha256"] = sha256_file(rung_manifest_path)

    leg_names = [k for k, v in result.items() if isinstance(v, dict) and "pass" in v]
    overall_pass = all(result[k]["pass"] for k in leg_names)
    result["legs_checked"] = leg_names
    result["overall_pass"] = overall_pass

    # Deliberately NEVER raises here -- the caller (main()) writes the
    # preflight receipt to disk FIRST, then refuses on overall_pass=False.
    # Raising in here would skip the receipt write entirely (the exact bug a
    # functional probe against the real historical checkpoints caught: the
    # refusal message claimed "already written to disk" while the receipt
    # had never been written).
    return result, eval_x, eval_y


# ---------------------------------------------------------------------------
# RNG-state structural equality (capture_rng()'s own bundle shape: py_random
# tuple, torch_cpu tensor, optional np_random tuple, optional torch_cuda
# tensor list) -- used to prove a restore_rng() round-trip is bit-exact, not
# merely "didn't raise".
# ---------------------------------------------------------------------------

def _rng_states_equal(a: dict, b: dict) -> bool:
    if set(a.keys()) != set(b.keys()):
        return False
    if a["py_random"] != b["py_random"]:
        return False
    if not torch.equal(a["torch_cpu"], b["torch_cpu"]):
        return False
    if "np_random" in a:
        an, bn = a["np_random"], b["np_random"]
        if an[0] != bn[0] or an[2] != bn[2] or an[3] != bn[3] or an[4] != bn[4]:
            return False
        if not np.array_equal(an[1], bn[1]):
            return False
    if "torch_cuda" in a:
        if len(a["torch_cuda"]) != len(b["torch_cuda"]):
            return False
        for ta, tb in zip(a["torch_cuda"], b["torch_cuda"]):
            if not torch.equal(ta, tb):
                return False
    return True


def _corrupt_checkpoint_model_weights_for_test(ckpt_dir: str) -> None:
    """TEST-ONLY (selftest negative fixture, never called from main()'s real
    path): perturbs EVERY floating-point tensor in the saved model.pt on
    disk and rewrites manifest.json's model.pt sha to match the perturbed
    bytes, so load_checkpoint's own sha-integrity check still passes. This
    isolates 'the saved bytes silently differ from what was in memory at
    save time' from the ALREADY-tested 'corrupted bytes get refused'
    scenario (that one is _refuse_unless_manifest_matches's job).

    Perturbs ALL float tensors, not just the first state_dict key: eval_
    loss_fn (reused verbatim from w1_collapse_control_run.py) computes
    cross-entropy over model(x)'s PRIMARY logits only -- it never touches
    the MTP aux heads. state_dict() key order is module-registration order,
    so a first-key-only perturbation can land on an MTP-head parameter that
    plays no part in the primary eval path and silently fails to flip
    reload_bit_exact_vs_pre_save (caught by this fixture's own selftest
    assertion during development). Perturbing every float tensor guarantees
    at least one on the primary path is corrupted."""
    model_pt_path = os.path.join(ckpt_dir, "model.pt")
    state = torch.load(model_pt_path, map_location="cpu")
    n_perturbed = 0
    for key, tensor in state.items():
        if torch.is_tensor(tensor) and tensor.is_floating_point():
            state[key] = tensor + 1.0
            n_perturbed += 1
    if n_perturbed == 0:
        raise AssertionError(
            "W1_REPLAY_TEST_CORRUPT_NO_FLOAT_TENSORS_FOUND: "
            f"state_dict keys={list(state.keys())!r}")
    torch.save(state, model_pt_path)
    new_sha = sha256_file(model_pt_path)
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["files"]["model.pt"] = new_sha
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, sort_keys=True, separators=(",", ": "), indent=2)


# ---------------------------------------------------------------------------
# Replay -- resume from the certified checkpoint, replay the historical
# remaining updates, save the missing step, reload-from-bytes and re-eval
# FP32.
# ---------------------------------------------------------------------------

def replay_and_close(*, real_arch: dict, pretrain_contract: dict,
                      control_step25_dir: str, loader, eval_x, eval_y,
                      eval_batch_sha: str, target_eval_loss: float,
                      ceiling_steps: int, replay_start_step: int,
                      replay_end_step: int, seed: int, device: str,
                      out_dir: str, fp32_tolerance: float,
                      expected_step25_eval_loss_bf16: "float | None",
                      expected_step50_eval_loss_bf16: "float | None",
                      expected_step50_eval_loss_fp32: "float | None",
                      claim_bearing: bool = True,
                      _test_corrupt_after_save: bool = False) -> dict:
    """claim_bearing (default True): a claim-bearing invocation (main()'s
    real --live path always uses this default) REQUIRES all three receipted
    expectations up front -- a None expectation refuses to run rather than
    trivially passing that conjunct (an unspecified target is not evidence
    of a match). Only a non-claim-bearing invocation (selftest fixtures
    exploring a synthetic checkpoint with no receipted historical figure to
    compare against) may pass claim_bearing=False to permit an omitted
    expectation, in which case that ONE conjunct trivially passes -- the
    other three (and the unconditional resumability leg below) still run
    for real and still gate the verdict.

    _test_corrupt_after_save: TEST-ONLY (selftest negative fixture) --
    corrupts the saved step50 checkpoint's bytes before the reload-from-
    bytes leg, to prove reload_bit_exact_vs_pre_save actually gates.
    """
    if claim_bearing:
        missing = [name for name, val in (
            ("expected_step25_eval_loss_bf16", expected_step25_eval_loss_bf16),
            ("expected_step50_eval_loss_bf16", expected_step50_eval_loss_bf16),
            ("expected_step50_eval_loss_fp32", expected_step50_eval_loss_fp32),
        ) if val is None]
        if missing:
            raise SystemExit(
                f"W1_REPLAY_CLAIM_BEARING_MISSING_EXPECTED: {missing!r} -- "
                "a claim-bearing replay (claim_bearing=True, the default) "
                "requires every receipted expectation up front; refusing to "
                "run with an unspecified target rather than trivially "
                "passing that conjunct. Pass claim_bearing=False only for "
                "non-claim-bearing (selftest) invocations.")

    # Defense-in-depth: re-verify the eval batch this call was HANDED still
    # matches the pinned sha (preflight already asserted this once at
    # rebuild time; a second, cheap assert here ties replay to preflight
    # without re-trusting a stale reference).
    measured_batch_sha = sha256_tokens(torch.cat([eval_x, eval_y], dim=1))
    if measured_batch_sha != eval_batch_sha:
        raise SystemExit(
            "W1_REPLAY_EVAL_BATCH_SHA_DRIFTED_SINCE_PREFLIGHT: "
            f"measured={measured_batch_sha} expected={eval_batch_sha}")

    deviation_dir = os.path.join(out_dir, "deviations")
    mtp_cfg = pretrain_contract["objective"]["mtp_aux_heads"]
    mtp_enabled = bool(mtp_cfg["enabled"])
    mtp_weight = mtp_cfg["weight"]
    ce_impl, ce_fn = resolve_ce_impl(prefer_liger=(device == "cuda"))

    model = build_real_model(real_arch, device, seed=seed)
    optimizers, base_lrs, routing = build_split_optimizer(
        model, pretrain_contract, force_fallback=False, deviation_dir=deviation_dir)

    # Load the certified checkpoint -- the SAME load_checkpoint / load_state_
    # dict(strict=True) / load_optimizers_state / restore_rng sequence
    # run_phase2_live's own in-run resume-test uses (RESUME_BIT_EXACT),
    # never load_continuation_checkpoint (that path is for the W1b GROW-ARM
    # width-narrowing continuation mode; this is the SAME arch resuming its
    # own checkpoint, not a continuation onto a different FF width).
    m_state, o_state, r_state, manifest25 = load_checkpoint(control_step25_dir)
    key_shape_parity = verify_checkpoint_key_shape_parity(m_state, model)
    model.load_state_dict(m_state, strict=True)
    load_optimizers_state(optimizers, o_state)
    restore_rng(r_state)

    eval_loss_at_load = eval_loss_fn(model, eval_x, eval_y)
    load_matches_receipted = (expected_step25_eval_loss_bf16 is None
                               or eval_loss_at_load == expected_step25_eval_loss_bf16)

    # Replay the historical REMAINING update indices [replay_start_step,
    # replay_end_step) -- the original loop's `while step < ceiling_steps`
    # reads loader.batch(step, ...) BEFORE incrementing step, so the updates
    # that carried step k-1 -> step k used loader.batch(k-1, ...); the
    # updates from step25 to step50 are indices 25..49, never 26..50.
    lr_trace = []
    for step in range(replay_start_step, replay_end_step):
        x, y0, y_mtp = loader.batch(step, real_arch["batch"])
        x = x.to(device)
        y0 = y0.to(device)
        y_mtp = [t.to(device) for t in y_mtp]
        mult = apply_cosine_warmup(optimizers, base_lrs, step, ceiling_steps)
        lr_trace.append(round(mult, 8))
        train_step_matched_recipe(
            model, optimizers, ce_fn, x=x, y0=y0, y_mtp=y_mtp,
            mtp_enabled=mtp_enabled, mtp_weight=mtp_weight)

    final_step = replay_end_step
    eval_loss_bf16_post_replay = eval_loss_fn(model, eval_x, eval_y)
    replay_matches_receipted_bf16 = (
        expected_step50_eval_loss_bf16 is None
        or eval_loss_bf16_post_replay == expected_step50_eval_loss_bf16)

    # SAVE step50 -- the missing artifact.
    rng_snap = capture_rng()
    saved_o_state = save_optimizers_state(optimizers)
    ckpt_dir_50 = save_checkpoint(
        out_dir, final_step, model.state_dict(), saved_o_state, rng_snap,
        extra={"segment_id": "w1-baseline-replay-closure", "issue": ISSUE_REF,
               "resumed_from": control_step25_dir,
               "replayed_step_range": [replay_start_step, replay_end_step],
               "dry_run": False, "optimizer_mode": routing["mode"]})
    del model, optimizers

    if _test_corrupt_after_save:
        _corrupt_checkpoint_model_weights_for_test(ckpt_dir_50)

    # Reload step50 FROM BYTES -- never reuse the in-memory model (mission
    # requirement: prove the SAVED artifact, not the process's own memory).
    model_reload = build_real_model(real_arch, device, seed=seed)
    m_state50, o_state50, r_state50, manifest50 = load_checkpoint(ckpt_dir_50)
    verify_checkpoint_key_shape_parity(m_state50, model_reload)
    model_reload.load_state_dict(m_state50, strict=True)
    eval_loss_bf16_reloaded = eval_loss_fn(model_reload, eval_x, eval_y)
    reload_bit_exact_vs_pre_save = (eval_loss_bf16_reloaded == eval_loss_bf16_post_replay)

    # Token IDs/labels (eval_x, eval_y) stay integer dtype throughout -- only
    # the model's own weights/activations are cast to fp32 here.
    model_reload = model_reload.to(torch.float32)
    eval_loss_fp32_reloaded = eval_loss_fn(model_reload, eval_x, eval_y)
    del model_reload
    if device == "cuda":
        torch.cuda.empty_cache()

    fp32_delta = (None if expected_step50_eval_loss_fp32 is None
                  else eval_loss_fp32_reloaded - expected_step50_eval_loss_fp32)
    fp32_within_tolerance = (expected_step50_eval_loss_fp32 is None
                              or abs(fp32_delta) <= fp32_tolerance)

    # Full resumability leg (not just model-reload): apply o_state50/
    # r_state50 to a FRESH optimizer set + RNG and parity-check both against
    # what was actually saved -- proves the closed checkpoint is a genuine
    # resume point, not merely a model-weights snapshot. optimizer_state_
    # shape_parity is REUSED verbatim from w1_collapse_control_run.py (the
    # same check run_phase2_live's own resume_proof block uses).
    model_resume_check = build_real_model(real_arch, device, seed=seed)
    model_resume_check.load_state_dict(m_state50, strict=True)
    optimizers_resume_check, _blrs_rc, _routing_rc = build_split_optimizer(
        model_resume_check, pretrain_contract, force_fallback=False,
        deviation_dir=deviation_dir)
    load_optimizers_state(optimizers_resume_check, o_state50)
    restore_rng(r_state50)
    optimizer_resume_parity = optimizer_state_shape_parity(
        save_optimizers_state(optimizers_resume_check), saved_o_state)
    rng_resume_bit_exact = _rng_states_equal(capture_rng(), r_state50)
    del model_resume_check, optimizers_resume_check
    if device == "cuda":
        torch.cuda.empty_cache()

    verdict = ("REPLAY_TRUSTWORTHY"
               if (load_matches_receipted and replay_matches_receipted_bf16
                   and reload_bit_exact_vs_pre_save and fp32_within_tolerance
                   and optimizer_resume_parity["shapes_match"]
                   and rng_resume_bit_exact)
               else "REPLAY_DIVERGED")

    return {
        "control_step25_dir": control_step25_dir,
        "control_step25_manifest_step": manifest25.get("step"),
        "key_shape_parity": key_shape_parity,
        "eval_loss_bf16_at_load": eval_loss_at_load,
        "expected_step25_eval_loss_bf16": expected_step25_eval_loss_bf16,
        "load_matches_receipted": load_matches_receipted,
        "replayed_update_indices": {
            "start_inclusive": replay_start_step, "end_exclusive": replay_end_step,
            "n_updates": replay_end_step - replay_start_step},
        "lr_schedule": {"source": MATCHED_RECIPE_SCHEDULE_SOURCE,
                        "total_steps_for_schedule": ceiling_steps,
                        "lr_mult_trace_first": lr_trace[0] if lr_trace else None,
                        "lr_mult_trace_last": lr_trace[-1] if lr_trace else None},
        "optimizer": {"mode": routing["mode"], "n_muon": routing.get("n_muon"),
                      "n_adamw": routing.get("n_adamw"), "ce_impl": ce_impl,
                      "mtp_enabled": mtp_enabled, "mtp_weight": mtp_weight},
        "eval_loss_bf16_post_replay": eval_loss_bf16_post_replay,
        "expected_step50_eval_loss_bf16": expected_step50_eval_loss_bf16,
        "replay_matches_receipted_bf16": replay_matches_receipted_bf16,
        "step50_checkpoint_dir": ckpt_dir_50,
        "step50_checkpoint_manifest_step": manifest50.get("step"),
        "eval_loss_bf16_reloaded_from_bytes": eval_loss_bf16_reloaded,
        "reload_bit_exact_vs_pre_save_bf16": reload_bit_exact_vs_pre_save,
        "eval_loss_fp32_reloaded_from_bytes": eval_loss_fp32_reloaded,
        "expected_step50_eval_loss_fp32": expected_step50_eval_loss_fp32,
        "fp32_delta_vs_receipted": fp32_delta,
        "fp32_tolerance": fp32_tolerance,
        "fp32_within_tolerance": fp32_within_tolerance,
        "optimizer_resume_parity": optimizer_resume_parity,
        "rng_resume_bit_exact": rng_resume_bit_exact,
        "claim_bearing": claim_bearing,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Custody -- move the closed step50 checkpoint out of scratch/ into a
# models/ custody dir (issue #677 checkpoint-custody addendum).
# ---------------------------------------------------------------------------

def custody_move(ckpt_dir: str, custody_root: str, *, run_ts: str) -> dict:
    import shutil
    dest_dir = os.path.join(
        custody_root, f"w1-baseline-replay-step50-{run_ts}")
    if os.path.exists(dest_dir):
        raise SystemExit(
            f"W1_REPLAY_CUSTODY_DEST_EXISTS: {dest_dir!r} already exists -- "
            "refusing to overwrite an existing custody artifact.")
    os.makedirs(custody_root, exist_ok=True)
    files = ["model.pt", "optimizer.pt", "rng.pt", "manifest.json"]
    pre_move_sha = {f: sha256_file(os.path.join(ckpt_dir, f)) for f in files}
    shutil.move(ckpt_dir, dest_dir)
    post_move_sha = {f: sha256_file(os.path.join(dest_dir, f)) for f in files}
    per_file_bytes_preserved = {f: pre_move_sha[f] == post_move_sha[f] for f in files}
    if not all(per_file_bytes_preserved.values()):
        raise SystemExit(
            "W1_REPLAY_CUSTODY_MOVE_BYTES_CHANGED: "
            f"{per_file_bytes_preserved!r}")
    record = {
        "ticket": "W1-REPLAY-CUSTODY-MOVE", "ts": run_ts,
        "ref": "issue #677 checkpoint-custody addendum",
        "sha_convention": SHA_CONVENTION,
        "source_dir": ckpt_dir, "dest_dir": dest_dir,
        "files_sha256_pre_move": pre_move_sha,
        "files_sha256_post_move": post_move_sha,
        "per_file_bytes_preserved": per_file_bytes_preserved,
    }
    with open(os.path.join(dest_dir, "custody-move-manifest.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    return record


# ---------------------------------------------------------------------------
# --selftest -- CPU-only synthetic fixtures. No GPU, no real corpus, no real
# checkpoints.
# ---------------------------------------------------------------------------

def _tiny_real_arch() -> dict:
    return {"vocab": 96, "seq": 8, "batch": 2, "hidden": 16, "n_mtp": 2,
            "ff_grown": 32, "layers_assumed": 2, "heads_assumed": 2,
            "params_unique_after": None, "params_state_dict_sum_after": None}


def _build_tiny_shard_dir(tmp_dir: str, *, vocab: int, n_tokens: int = 4000,
                           seed: int = 0) -> str:
    shard_dir = os.path.join(tmp_dir, "tiny-shards")
    os.makedirs(shard_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    tokens = rng.integers(0, vocab, size=n_tokens, dtype=np.uint16)
    tokens.tofile(os.path.join(shard_dir, "shard0.bin"))
    return shard_dir


def _selftest() -> None:
    import tempfile
    print("[w1-replay-closure-selftest] starting CPU-only synthetic-fixture selftest")
    with tempfile.TemporaryDirectory(prefix="w1replay735-selftest-") as tmp:
        real_arch = _tiny_real_arch()
        pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)
        shard_dir = _build_tiny_shard_dir(tmp, vocab=real_arch["vocab"])
        loader = PackedShardLoader(
            shard_dir, real_arch["seq"], n_mtp=real_arch["n_mtp"],
            excluded_ranges=None)
        device = "cpu"

        # --- (d) API-conformance: construct every real object this script
        # relies on and run ONE train step + eval, proving the historical
        # modules' import signatures have not drifted. ---
        model = build_real_model(real_arch, device, seed=1234)
        optimizers, base_lrs, routing = build_split_optimizer(
            model, pretrain_contract, force_fallback=False,
            deviation_dir=os.path.join(tmp, "deviations"))
        ce_impl, ce_fn = resolve_ce_impl(prefer_liger=False)
        x, y0, y_mtp = loader.batch(0, real_arch["batch"])
        mult = apply_cosine_warmup(optimizers, base_lrs, 0, 40)
        assert 0.0 < mult <= 1.0, f"W1_REPLAY_SELFTEST_LR_MULT_OUT_OF_RANGE: {mult}"
        mtp_cfg = pretrain_contract["objective"]["mtp_aux_heads"]
        loss0 = train_step_matched_recipe(
            model, optimizers, ce_fn, x=x, y0=y0, y_mtp=y_mtp,
            mtp_enabled=bool(mtp_cfg["enabled"]), mtp_weight=mtp_cfg["weight"])
        assert isinstance(loss0, float) and loss0 == loss0, (
            "W1_REPLAY_SELFTEST_TRAIN_STEP_NONFLOAT")
        print(f"[selftest] (d) API-conformance leg PASS -- "
              f"optimizer routing={routing['mode']} n_muon={routing.get('n_muon')} "
              f"n_adamw={routing.get('n_adamw')} ce_impl={ce_impl} loss0={loss0}")

        # --- fixture eval batch (real window rebuild, not the dry-run
        # synthetic_corpus helper -- this script never uses that path). ---
        xs_np, ys_np = [], []
        for j in range(real_arch["batch"]):
            xw, yw, _ = loader.window_np(1000 + j)
            xs_np.append(xw)
            ys_np.append(yw)
        eval_x = torch.as_tensor(np.stack(xs_np), dtype=torch.long, device=device)
        eval_y = torch.as_tensor(np.stack(ys_np), dtype=torch.long, device=device)
        eval_batch_sha = sha256_tokens(torch.cat([eval_x, eval_y], dim=1))

        # --- (b) save -> reload identity plumbing ---
        step10_dir = save_checkpoint(
            os.path.join(tmp, "run"), 10, model.state_dict(),
            save_optimizers_state(optimizers), capture_rng(),
            extra={"segment_id": "selftest"})
        eval_before = eval_loss_fn(model, eval_x, eval_y)
        model2 = build_real_model(real_arch, device, seed=999)  # different seed -- load must override it
        m_state, o_state, r_state, manifest10 = load_checkpoint(step10_dir)
        verify_checkpoint_key_shape_parity(m_state, model2)
        model2.load_state_dict(m_state, strict=True)
        eval_after = eval_loss_fn(model2, eval_x, eval_y)
        assert eval_before == eval_after, (
            f"W1_REPLAY_SELFTEST_SAVE_RELOAD_NOT_BIT_EXACT: "
            f"before={eval_before} after={eval_after}")
        print(f"[selftest] (b) save->reload identity leg PASS -- "
              f"eval_loss bit-exact ({eval_before})")

        # --- (a) wrong-sha refusal ---
        wrong_expected = {"model.pt": "0" * 64, "optimizer.pt": "0" * 64, "rng.pt": "0" * 64}
        try:
            _refuse_unless_manifest_matches(step10_dir, wrong_expected)
            raise AssertionError("W1_REPLAY_SELFTEST_WRONG_SHA_DID_NOT_REFUSE")
        except SystemExit as e:
            assert "W1_REPLAY_CHECKPOINT_SHA_MISMATCH" in str(e), (
                f"unexpected refusal message: {e}")
        right_expected = {fname: sha256_file(os.path.join(step10_dir, fname))
                           for fname in ("model.pt", "optimizer.pt", "rng.pt")}
        check_ok = _refuse_unless_manifest_matches(step10_dir, right_expected)
        assert check_ok["pass"], f"W1_REPLAY_SELFTEST_CORRECT_SHA_FALSE_REFUSED: {check_ok}"
        print("[selftest] (a) wrong-sha refusal leg PASS")

        # --- (e) claim-bearing upfront refusal gate: claim_bearing=True
        # (the default -- this is the mode --live uses) must REFUSE to run
        # rather than trivially pass when any receipted expectation is
        # missing (repair item 1b: None must never mean "trivially true"
        # in claim-bearing mode; the None-trivial-pass path is legal ONLY
        # under claim_bearing=False). ---
        try:
            replay_and_close(
                real_arch=real_arch, pretrain_contract=pretrain_contract,
                control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
                eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
                ceiling_steps=40, replay_start_step=10, replay_end_step=15,
                seed=1234, device=device,
                out_dir=os.path.join(tmp, "replay-claimbearing-refusal"),
                fp32_tolerance=1e-3,
                expected_step25_eval_loss_bf16=eval_before,
                expected_step50_eval_loss_bf16=None,
                expected_step50_eval_loss_fp32=None)
            raise AssertionError(
                "W1_REPLAY_SELFTEST_CLAIM_BEARING_DID_NOT_REFUSE_ON_MISSING_EXPECTED")
        except SystemExit as e:
            assert "W1_REPLAY_CLAIM_BEARING_MISSING_EXPECTED" in str(e), (
                f"unexpected refusal message: {e}")
        print("[selftest] (e) claim-bearing missing-expected refusal leg PASS")

        # --- (f) discovery pass (claim_bearing=False -- the only mode
        # permitted to leave receipted expectations unspecified) to learn
        # this synthetic fixture's OWN true bf16-post-replay / fp32-
        # reloaded values, since no historical receipt exists for it. ---
        discovery = replay_and_close(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
            eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
            ceiling_steps=40, replay_start_step=10, replay_end_step=15,
            seed=1234, device=device, out_dir=os.path.join(tmp, "replay-discovery"),
            fp32_tolerance=1e-3,
            expected_step25_eval_loss_bf16=eval_before,
            expected_step50_eval_loss_bf16=None,
            expected_step50_eval_loss_fp32=None,
            claim_bearing=False)
        assert discovery["verdict"] == "REPLAY_TRUSTWORTHY", (
            f"W1_REPLAY_SELFTEST_DISCOVERY_UNEXPECTED_VERDICT: {discovery}")
        assert discovery["optimizer_resume_parity"]["shapes_match"], (
            f"W1_REPLAY_SELFTEST_DISCOVERY_OPTIMIZER_RESUME_PARITY_FAILED: "
            f"{discovery['optimizer_resume_parity']}")
        assert discovery["rng_resume_bit_exact"], (
            "W1_REPLAY_SELFTEST_DISCOVERY_RNG_RESUME_NOT_BIT_EXACT")
        true_bf16 = discovery["eval_loss_bf16_post_replay"]
        true_fp32 = discovery["eval_loss_fp32_reloaded_from_bytes"]
        print(f"[selftest] (f) discovery leg PASS -- true_bf16={true_bf16} "
              f"true_fp32={true_fp32} optimizer_resume_parity=OK rng_resume=OK")

        # --- (c1) claim-bearing correct-path leg: every receipted
        # expectation supplied and correct -- all six conjuncts True,
        # verdict REPLAY_TRUSTWORTHY. ---
        replay1 = replay_and_close(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
            eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
            ceiling_steps=40, replay_start_step=10, replay_end_step=15,
            seed=1234, device=device, out_dir=os.path.join(tmp, "replay-correct"),
            fp32_tolerance=1e-3,
            expected_step25_eval_loss_bf16=eval_before,
            expected_step50_eval_loss_bf16=true_bf16,
            expected_step50_eval_loss_fp32=true_fp32)
        assert replay1["verdict"] == "REPLAY_TRUSTWORTHY", (
            f"W1_REPLAY_SELFTEST_UNEXPECTED_VERDICT: {replay1['verdict']}")
        for conjunct in ("load_matches_receipted", "replay_matches_receipted_bf16",
                         "reload_bit_exact_vs_pre_save_bf16", "fp32_within_tolerance",
                         "rng_resume_bit_exact"):
            assert replay1[conjunct], (
                f"W1_REPLAY_SELFTEST_CORRECT_PATH_CONJUNCT_FALSE: {conjunct}")
        assert replay1["optimizer_resume_parity"]["shapes_match"], (
            f"W1_REPLAY_SELFTEST_CORRECT_PATH_OPTIMIZER_RESUME_PARITY_FALSE: "
            f"{replay1['optimizer_resume_parity']}")
        print(f"[selftest] (c1) replay_and_close correct-path leg PASS -- "
              f"verdict={replay1['verdict']} all six conjuncts True")

        # --- (c2)-(c5): four negative fixtures, each flipping EXACTLY ONE
        # of the four receipted-comparison conjuncts independently, proving
        # the verdict actually gates on each rather than a subset (repair
        # item 1: "Make all four conjuncts, add negative fixtures flipping
        # each one independently"). ---
        replay_neg_load = replay_and_close(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
            eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
            ceiling_steps=40, replay_start_step=10, replay_end_step=15,
            seed=1234, device=device, out_dir=os.path.join(tmp, "replay-neg-load"),
            fp32_tolerance=1e-3,
            expected_step25_eval_loss_bf16=eval_before + 1.0,  # WRONG on purpose
            expected_step50_eval_loss_bf16=true_bf16,
            expected_step50_eval_loss_fp32=true_fp32)
        assert not replay_neg_load["load_matches_receipted"], (
            "W1_REPLAY_SELFTEST_NEG_LOAD_DID_NOT_FLIP")
        assert replay_neg_load["verdict"] == "REPLAY_DIVERGED", (
            f"W1_REPLAY_SELFTEST_NEG_LOAD_VERDICT_NOT_DIVERGED: {replay_neg_load['verdict']}")
        assert replay_neg_load["replay_matches_receipted_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_LOAD_COLLATERAL_FLIP_REPLAY")
        assert replay_neg_load["reload_bit_exact_vs_pre_save_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_LOAD_COLLATERAL_FLIP_RELOAD")
        assert replay_neg_load["fp32_within_tolerance"], (
            "W1_REPLAY_SELFTEST_NEG_LOAD_COLLATERAL_FLIP_FP32")
        print("[selftest] (c2) negative fixture: load_matches_receipted flipped -- PASS "
              "(verdict correctly REPLAY_DIVERGED, other three conjuncts unaffected)")

        replay_neg_replay = replay_and_close(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
            eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
            ceiling_steps=40, replay_start_step=10, replay_end_step=15,
            seed=1234, device=device, out_dir=os.path.join(tmp, "replay-neg-replay"),
            fp32_tolerance=1e-3,
            expected_step25_eval_loss_bf16=eval_before,
            expected_step50_eval_loss_bf16=true_bf16 + 1.0,  # WRONG on purpose
            expected_step50_eval_loss_fp32=true_fp32)
        assert not replay_neg_replay["replay_matches_receipted_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_REPLAY_DID_NOT_FLIP")
        assert replay_neg_replay["verdict"] == "REPLAY_DIVERGED", (
            f"W1_REPLAY_SELFTEST_NEG_REPLAY_VERDICT_NOT_DIVERGED: {replay_neg_replay['verdict']}")
        assert replay_neg_replay["load_matches_receipted"], (
            "W1_REPLAY_SELFTEST_NEG_REPLAY_COLLATERAL_FLIP_LOAD")
        assert replay_neg_replay["reload_bit_exact_vs_pre_save_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_REPLAY_COLLATERAL_FLIP_RELOAD")
        assert replay_neg_replay["fp32_within_tolerance"], (
            "W1_REPLAY_SELFTEST_NEG_REPLAY_COLLATERAL_FLIP_FP32")
        print("[selftest] (c3) negative fixture: replay_matches_receipted_bf16 flipped -- PASS "
              "(verdict correctly REPLAY_DIVERGED, other three conjuncts unaffected)")

        replay_neg_reload = replay_and_close(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
            eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
            ceiling_steps=40, replay_start_step=10, replay_end_step=15,
            seed=1234, device=device, out_dir=os.path.join(tmp, "replay-neg-reload"),
            fp32_tolerance=1e-3,
            expected_step25_eval_loss_bf16=eval_before,
            expected_step50_eval_loss_bf16=true_bf16,
            expected_step50_eval_loss_fp32=true_fp32,
            _test_corrupt_after_save=True)  # perturbs the SAVED model.pt bytes
        assert not replay_neg_reload["reload_bit_exact_vs_pre_save_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_RELOAD_DID_NOT_FLIP")
        assert replay_neg_reload["verdict"] == "REPLAY_DIVERGED", (
            f"W1_REPLAY_SELFTEST_NEG_RELOAD_VERDICT_NOT_DIVERGED: {replay_neg_reload['verdict']}")
        assert replay_neg_reload["load_matches_receipted"], (
            "W1_REPLAY_SELFTEST_NEG_RELOAD_COLLATERAL_FLIP_LOAD")
        # NOTE: fp32_within_tolerance is deliberately NOT asserted True here
        # -- the corruption is upstream of the fp32 reload-eval too, so a
        # cascading fp32 flip alongside the bf16 reload flip is CORRECT
        # behavior (both genuinely detect the same corrupted artifact), not
        # a leaky fixture.
        assert replay_neg_reload["optimizer_resume_parity"]["shapes_match"], (
            "W1_REPLAY_SELFTEST_NEG_RELOAD_COLLATERAL_FLIP_OPTIMIZER_PARITY")
        assert replay_neg_reload["rng_resume_bit_exact"], (
            "W1_REPLAY_SELFTEST_NEG_RELOAD_COLLATERAL_FLIP_RNG")
        print("[selftest] (c4) negative fixture: reload_bit_exact_vs_pre_save_bf16 flipped -- "
              "PASS (verdict correctly REPLAY_DIVERGED via corrupted saved bytes)")

        replay_neg_fp32 = replay_and_close(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            control_step25_dir=step10_dir, loader=loader, eval_x=eval_x, eval_y=eval_y,
            eval_batch_sha=eval_batch_sha, target_eval_loss=0.0,
            ceiling_steps=40, replay_start_step=10, replay_end_step=15,
            seed=1234, device=device, out_dir=os.path.join(tmp, "replay-neg-fp32"),
            fp32_tolerance=1e-3,
            expected_step25_eval_loss_bf16=eval_before,
            expected_step50_eval_loss_bf16=true_bf16,
            expected_step50_eval_loss_fp32=true_fp32 + 5.0)  # WRONG on purpose
        assert not replay_neg_fp32["fp32_within_tolerance"], (
            "W1_REPLAY_SELFTEST_NEG_FP32_DID_NOT_FLIP")
        assert replay_neg_fp32["verdict"] == "REPLAY_DIVERGED", (
            f"W1_REPLAY_SELFTEST_NEG_FP32_VERDICT_NOT_DIVERGED: {replay_neg_fp32['verdict']}")
        assert replay_neg_fp32["load_matches_receipted"], (
            "W1_REPLAY_SELFTEST_NEG_FP32_COLLATERAL_FLIP_LOAD")
        assert replay_neg_fp32["replay_matches_receipted_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_FP32_COLLATERAL_FLIP_REPLAY")
        assert replay_neg_fp32["reload_bit_exact_vs_pre_save_bf16"], (
            "W1_REPLAY_SELFTEST_NEG_FP32_COLLATERAL_FLIP_RELOAD")
        print("[selftest] (c5) negative fixture: fp32_within_tolerance flipped -- PASS "
              "(verdict correctly REPLAY_DIVERGED, other three conjuncts unaffected)")

    print("[w1-replay-closure-selftest] ALL LEGS PASS")


# ---------------------------------------------------------------------------
# commit-margin probe (best-effort; src/ember/governance/scripts/governor.py at HEAD exposes only
# a VRAM preflight()/env_limits() -- confirmed by reading the module
# directly, no commit_margin_preflight function exists in this tree, so this
# is a disclosed, non-blocking psutil-based diagnostic alongside the
# mandatory VRAM governor call below, never a substitute for it).
# ---------------------------------------------------------------------------

def _commit_margin_probe(min_free_gib: float = 6.0) -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        available_gib = vm.available / (1 << 30)
        return {"mode": "psutil_virtual_memory",
                "available_gib": round(available_gib, 2),
                "swap_used_gib": round(sm.used / (1 << 30), 2),
                "min_free_gib_floor": min_free_gib,
                "pass": available_gib >= min_free_gib}
    except Exception as e:  # noqa: BLE001 -- best-effort diagnostic only
        return {"mode": "unavailable", "error": f"{type(e).__name__}: {e}",
                "note": ("psutil not importable in this environment -- "
                         "commit-margin probe skipped; the VRAM governor "
                         "call is the load-bearing GPU-safety gate")}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only synthetic-fixture selftest; never touches "
                         "the real corpus/checkpoints/GPU.")
    ap.add_argument("--live", action="store_true",
                    help="Execute the real replay (training + save + "
                         "custody move). Refuses unless EMBER_GATE_"
                         "AUTHORIZED=1 AND --device cuda AND --shard-dir AND "
                         "EMBER_W1_MAINTAINER_WINDOW_CONFIRMED=1 (reuses "
                         "w1_collapse_control_run.refuse_unless_dry_run_safe "
                         "verbatim). Never fired by this builder.")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--shard-dir", default=None,
                    help="Real packed-token shard directory (the frozen W1 "
                         "corpus). Required on --live; when omitted or not "
                         "present on disk, preflight's corpus/eval-batch "
                         "legs fall back to their receipted-verification-"
                         "chain dry mode.")
    ap.add_argument("--pricing-receipt", default=DEFAULT_PRICING_RECEIPT)
    ap.add_argument("--rung-manifest", default=DEFAULT_RUNG_MANIFEST)
    ap.add_argument("--grow-checkpoint-dir", default=DEFAULT_GROW_CHECKPOINT_DIR)
    ap.add_argument("--control-step25-dir", default=DEFAULT_CONTROL_STEP25_DIR)
    ap.add_argument("--decontam-receipt", default=DEFAULT_DECONTAM_RECEIPT)
    ap.add_argument("--corpus-manifest-sha256",
                    default=CORPUS_MANIFEST_COMBINED_SHA256_EXPECTED,
                    help="pass '' to skip the corpus-sha compare")
    ap.add_argument("--out-dir", default=None,
                    help="defaults to scratch/w1-control/live/"
                         "w1-replay-closure-<ts>")
    ap.add_argument("--custody-dir", default=DEFAULT_CUSTODY_ROOT)
    ap.add_argument("--skip-custody-move", action="store_true",
                    help="Diagnostic use only: run --live without the "
                         "custody relocation leg. Disclosed in the closure "
                         "receipt when used.")
    ap.add_argument("--phase2-seed", type=int, default=PHASE2_SEED_HISTORICAL)
    ap.add_argument("--fp32-tolerance", type=float, default=DEFAULT_FP32_TOLERANCE)
    return ap


def main(argv: "list[str] | None" = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        print("W1_BASELINE_REPLAY_CLOSURE_SELFTEST_PASS")
        return 0

    repo_root = REPO_ROOT
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (resolve(repo_root, args.out_dir) if args.out_dir else
               os.path.join(repo_root, "scratch", "w1-control", "live",
                             f"w1-replay-closure-{ts}"))
    os.makedirs(out_dir, exist_ok=True)

    shard_dir = resolve(repo_root, args.shard_dir) if args.shard_dir else None
    pricing_receipt_path = resolve(repo_root, args.pricing_receipt)
    rung_manifest_path = resolve(repo_root, args.rung_manifest)
    decontam_receipt_path = resolve(repo_root, args.decontam_receipt)
    grow_checkpoint_dir = resolve(repo_root, args.grow_checkpoint_dir)
    control_step25_dir = resolve(repo_root, args.control_step25_dir)
    corpus_expected_sha = args.corpus_manifest_sha256 or None

    loader_for_preflight = None
    real_arch_probe = None
    if shard_dir and os.path.isdir(shard_dir):
        pricing_receipt_probe = load_json(pricing_receipt_path)
        rung_receipt_probe = derive_rung_receipt_from_manifest(rung_manifest_path)
        real_arch_probe = derive_real_arch_config(pricing_receipt_probe, rung_receipt_probe)
        mmap_cache_dir = os.path.join(out_dir, "mmap_cache")
        loader_for_preflight = PackedShardLoader(
            shard_dir, real_arch_probe["seq"], n_mtp=real_arch_probe["n_mtp"],
            mmap_cache_dir=mmap_cache_dir, excluded_ranges=None)

    preflight, eval_x, eval_y = preflight_verify(
        repo_root=repo_root, pricing_receipt_path=pricing_receipt_path,
        rung_manifest_path=rung_manifest_path,
        grow_checkpoint_dir=grow_checkpoint_dir,
        control_step25_dir=control_step25_dir,
        decontam_receipt_path=decontam_receipt_path,
        shard_dir=shard_dir, corpus_expected_sha=corpus_expected_sha,
        loader_for_batch_rebuild=loader_for_preflight, device=args.device)

    preflight_receipt = {
        "ticket": "W1-REPLAY-CLOSURE-PREFLIGHT", "ts": ts, "issue": ISSUE_REF,
        "schema": "w1-replay-closure-preflight/v1",
        "sha_convention": SHA_CONVENTION,
        "api_spend_usd": 0.0, "paid_api_surface_used": False,
        **{k: v for k, v in preflight.items() if k != "real_arch"},
        "real_arch": preflight["real_arch"],
    }
    preflight_path = os.path.join(out_dir, f"w1-replay-preflight-{ts}.json")
    checked_write(preflight_path, preflight_receipt)

    if not preflight["overall_pass"]:
        failing = [k for k in preflight["legs_checked"] if not preflight[k]["pass"]]
        raise SystemExit(
            f"W1_REPLAY_PREFLIGHT_REFUSED: failing legs={failing!r} -- "
            f"refusing to proceed to replay. Full per-leg detail written to "
            f"{preflight_path!r}.")

    if not args.live:
        print(json.dumps({
            "mode": "preflight_only",
            "preflight_receipt": os.path.relpath(preflight_path, repo_root),
            "overall_pass": preflight["overall_pass"],
        }, indent=2))
        return 0

    # --live: same interlock w1_collapse_control_run.py's own live path
    # requires, reused verbatim (never reimplemented).
    refuse_unless_dry_run_safe(args)

    if args.device == "cuda":
        gov_receipt = _apply_governor()
    else:
        gov_receipt = {"mode": "cpu_live_test",
                       "note": "device != cuda -- governor.preflight() skipped "
                               "(tiny-fixture / non-GPU invocation path)"}
    commit_margin = _commit_margin_probe()

    real_arch = real_arch_probe or derive_real_arch_config(
        load_json(pricing_receipt_path),
        derive_rung_receipt_from_manifest(rung_manifest_path))
    pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)
    loader = loader_for_preflight or PackedShardLoader(
        shard_dir, real_arch["seq"], n_mtp=real_arch["n_mtp"],
        mmap_cache_dir=os.path.join(out_dir, "mmap_cache"),
        excluded_ranges=None)

    replay = replay_and_close(
        real_arch=real_arch, pretrain_contract=pretrain_contract,
        control_step25_dir=control_step25_dir, loader=loader,
        eval_x=eval_x, eval_y=eval_y, eval_batch_sha=EXPECTED_EVAL_BATCH_SHA256,
        target_eval_loss=EXPECTED_TARGET_EVAL_LOSS,
        ceiling_steps=REAL_HARD_CEILING_STEPS,
        replay_start_step=REPLAY_START_STEP, replay_end_step=REPLAY_END_STEP,
        seed=args.phase2_seed, device=args.device, out_dir=out_dir,
        fp32_tolerance=args.fp32_tolerance,
        expected_step25_eval_loss_bf16=EXPECTED_STEP25_EVAL_LOSS_BF16,
        expected_step50_eval_loss_bf16=EXPECTED_STEP50_EVAL_LOSS_BF16,
        expected_step50_eval_loss_fp32=EXPECTED_STEP50_EVAL_LOSS_FP32)

    custody = None
    closure_verdict = replay["verdict"]
    if replay["verdict"] != "REPLAY_TRUSTWORTHY":
        print(f"W1_REPLAY_DIVERGED_CUSTODY_SKIPPED: verdict={replay['verdict']} -- "
              f"the step50 checkpoint stays at {replay['step50_checkpoint_dir']!r} "
              "for investigation, never moved to custody on a non-trustworthy replay.")
    elif args.skip_custody_move:
        # --skip-custody-move must NEVER silently promote a claim-bearing
        # trustworthy verdict: a checkpoint left in scratch/ has no custody
        # guarantee (issue #677), so the CLOSURE verdict (distinct from the
        # replay verdict) is downgraded to a diagnostic, non-promotable
        # value and main() exits nonzero even though the replay itself
        # checked out.
        closure_verdict = "REPLAY_TRUSTWORTHY_NO_CUSTODY_NONPROMOTABLE"
        print("W1_REPLAY_CUSTODY_MOVE_SKIPPED_BY_FLAG: --skip-custody-move given -- "
              "closure verdict downgraded to REPLAY_TRUSTWORTHY_NO_CUSTODY_NONPROMOTABLE "
              "(diagnostic use only; never cite this receipt as a trustworthy closure).")
    else:
        custody = custody_move(
            replay["step50_checkpoint_dir"], resolve(repo_root, args.custody_dir),
            run_ts=ts)

    closure = {
        "ticket": "W1-BASELINE-REPLAY-CLOSURE", "ts": ts, "issue": ISSUE_REF,
        "schema": "w1-baseline-replay-closure/v1",
        "sha_convention": SHA_CONVENTION,
        "historical_run_ref": f"w1-live-{HISTORICAL_RUN_TS}",
        "preflight": preflight, "replay": replay, "custody": custody,
        "governor": gov_receipt, "commit_margin_probe": commit_margin,
        "skip_custody_move_flag_used": args.skip_custody_move,
        "provenance_note": PROVENANCE_NOTE_DECONTAM_SUBSTITUTION,
        "replay_verdict": replay["verdict"],
        "verdict": closure_verdict,
        "verdict_language": (
            "W1_FROM_SCRATCH_PILOT_BASELINE (issue #735's own narrow-by-"
            "construction label: pilot scale, single seed, from-scratch "
            "final width) applies ONLY when verdict==REPLAY_TRUSTWORTHY "
            "(exactly that string) AND custody is non-null; "
            "REPLAY_TRUSTWORTHY_NO_CUSTODY_NONPROMOTABLE is a diagnostic "
            "verdict and carries no capability claim regardless of what "
            "the underlying replay measured. This receipt itself reports "
            "measured chain-verification data only, no capability-claim "
            "language is asserted here."),
        "api_spend_usd": 0.0, "paid_api_surface_used": False,
    }
    closure_path = os.path.join(
        repo_root, "receipts", "ember-c-scale", f"w1-baseline-replay-closure-{ts}.json")
    checked_write(closure_path, closure)
    print(json.dumps({
        "closure_receipt": os.path.relpath(closure_path, repo_root),
        "verdict": closure["verdict"],
        "step50_checkpoint_custody_dir": (custody or {}).get("dest_dir"),
    }, indent=2))
    return 0 if closure_verdict == "REPLAY_TRUSTWORTHY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
