# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""exp711_sensitivity.py -- #711 ordering-screen CPU apparatus, component 6
(AC extension, #739, carries #711 AMENDMENT A8 -- coordinator comment
4941969820, FROZEN before any fixture execution):

target-observable positive control. Proves the apparatus CAN detect an
order-sensitivity effect at all -- without this leg a null main-screen
result cannot distinguish apparatus insensitivity from a true null.

CONSTRUCTION (pinned; non-bespoke consumer path):
  Trainer step: literal run_v0_segment(live=False, ...) from
  src/ember/governance/scripts/timeshare_pretrain.py -- the same full-stack CPU dry-run path
  _selftest_v0ext already exercises (real PackedShardLoader,
  chunked_cross_entropy, Muon/AdamW split, WSD schedule, _tiny_v0_model).

  Multiset: a tiny packed-shard fixture (rng ints -> write_packed_shard),
  one TARGET block (~20% of windows). Two arms consume the IDENTICAL
  window multiset (same TARGET_TOKENS + same FILLER_TOKENS byte content,
  same steps/batch), differing ONLY in target-block POSITION within the
  packed stream: EARLY (front-loaded, windows 0..k-1) vs LATE
  (back-loaded, windows n-k..n-1). Ordering bookkeeping (which window ids
  land at which training step, for each arm) is derived via
  exp711_permute.py's own identity_arm/batch_window_ids machinery -- no
  second ordering mechanism is written here.

  Outcome statistic: after each arm trains, ONE forward pass (no
  backward) over the TARGET window content itself (a dedicated
  target-only packed shard, byte-identical TARGET_TOKENS for both arms),
  loss via the identical chunked_cross_entropy. This is a
  memorization-recency APPARATUS control -- deliberately evaluated on
  trained content; never a generalization claim.

  Validity requirements (asserted, not just satisfied by hope):
    (1) the post-last-exposure step gap must DIFFER by more than 1 step
        between arms (EARLY: many filler steps after; LATE: ~0).
    (2) no EMA / parameter averaging (run_v0_segment as called here has
        none -- disclosed).
    (3) LR schedule not fully decayed before the target's last exposure
        in EITHER arm -- asserted directly against wsd_lr_frac's own
        stable_until_frac boundary, not assumed.

DIRECTION (frozen): delta_sens := NLL_target(EARLY_arm) -
NLL_target(LATE_arm). Prediction: delta_sens > 0 (recency -- the arm
that saw the target LAST fits it better, i.e. LATE has lower NLL).

FLOOR RULE (frozen fraction, calibration-derived magnitude; coordinator
comment 4941969820):
  1. ONE calibration run of the exact fixture, seed-pinned
     (CALIBRATION_SEED), executed AFTER the freeze comment posts. Raw
     receipt (both NLLs, seed, steps, window counts) posted to #711
     BEFORE the production fixture body lands.
  2. floor := 0.5 * |delta_sens(calibration)| -- the 0.5 fraction is
     frozen; the magnitude is measured, not asserted.
  3. Production/selftest runs use PRODUCTION_SEED (DIFFERENT from
     CALIBRATION_SEED). PASS requires direction correct AND
     |delta_sens| >= floor (inclusive). Anything else -- missing/
     malformed receipt, wrong direction, below floor -- is
     INVALID_SCREEN via exp711_verdict.sensitivity_preflight().

Run:
    python src/ember/governance/scripts/exp711_sensitivity.py --calibrate
        (raw calibration receipt; frozen CALIBRATION_SEED; does NOT
        require FROZEN_FLOOR to be set yet)
    python src/ember/governance/scripts/exp711_sensitivity.py --emit
        (production receipt at PRODUCTION_SEED, checked against
        FROZEN_FLOOR; requires FROZEN_FLOOR to be baked in first)
    python src/ember/governance/scripts/exp711_sensitivity.py --selftest
        (runs the production-seed fixture end to end + structural
        asserts + a live sensitivity_preflight() integration check;
        this IS the real apparatus, not a mock -- there is no cheaper
        correctness check for a mechanism this shape)
"""
import argparse
import copy
import hashlib
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

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
import exp711_permute as ep  # noqa: E402
import exp711_verdict as ev  # noqa: E402
from timeshare_pretrain import (  # noqa: E402
    load_contract, run_v0_segment, write_packed_shard, PackedShardLoader,
    build_v0_model, load_checkpoint, chunked_cross_entropy,
)

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over the little-endian uint16 bytes of the packed token stream"
OUT_DIR = os.path.join(REPO, "receipts", "exp711-apparatus")

# Frozen fixture shape -- AMENDMENT A8.1 (issue #711 comment 4942042739),
# superseding the original A8 sizing (comment 4941969820) after the
# 20260711T031316Z calibration at n_steps=12/batch_size=2 barely trained
# (total loss moved ~0.2 nats; both target NLLs near the ln(64) uniform
# baseline) -- posted 4942041135, disclosed as-is, not floor-ified.
# structural construction, direction prediction, and the 0.5 floor fraction
# are UNCHANGED by A8.1; only numeric sizing moved. total_steps is set well
# beyond n_steps so the WSD schedule never leaves the warmup/stable region
# during this segment (validity requirement 3, asserted, not assumed).
SEQ = 16
N_MTP = 2
TINY_DIMS = {"vocab": 64, "hidden": 32, "depth": 2, "seq": SEQ}  # unchanged by A8.1
BATCH_SIZE = 4   # A8.1: 2 -> 4
N_STEPS = 80     # A8.1: 12 -> 80
TOTAL_STEPS = N_STEPS * 4
TARGET_FRACTION = 0.20
CE_CHUNK_TOKENS = 32

# TRAINED-AT-ALL precondition (A8.1, frozen, mechanical floor-eligibility
# gate): a resized calibration is floor-eligible ONLY IF both hold. A
# calibration failing this is not a calibration -- STOP and report.
TRAINED_LOSS_DROP_MIN_NATS = 0.5
TRAINED_NLL_MARGIN_NATS = 0.5  # min(nll_early, nll_late) <= ln(vocab) - this

# AMENDMENT A8.2 (issue #711 comment 4942176352): the A8.1 resize (seed
# 90101, n_steps=80, batch_size=4) FAILED trained-at-all
# (loss_drop_min=0.044062 < 0.5) -- more steps at the same LR did not move
# it. Diagnosis: embed.weight/head.weight (the only params this
# position-independent stand-in can use to memorize anything) are routed
# by split_param_groups to AdamW at the frozen production lr_adamw=0.0003,
# structurally too slow at fixture scale. A8.2 ruling: A8's "exact
# training/eval consumer path" clause pins the CODE PATH (run_v0_segment,
# split_param_groups, chunked_cross_entropy, the exp711 permutation
# machinery, eval-on-target-window), not the production hyperparameters --
# a positive control must be able to plant a detectable signal (same class
# as the #703 prereg's planted-gain oracle). Caller-side ONLY: a deepcopy
# of cfg with cfg["optimizer"]["lr_adamw"] bumped to the muon-group scale;
# the frozen contract file on disk is never touched. Applied identically to
# BOTH arms and disclosed via cfg_overrides in every receipt this override
# touches (calibration and production alike -- the floor is only
# meaningful if calibration and production share the same construction).
A82_LR_ADAMW_OVERRIDE = 0.02  # matches lr_muon's scale, fixed pre-run, no iteration

# CALIBRATION_SEED is frozen the moment the calibration receipt is posted to
# #711 (A8.2 comment 4942176352: seed=90201, superseding the retired
# 90001/90101). PRODUCTION_SEED is a DIFFERENT frozen seed for the
# production/selftest fixture (A8 step 3, unaffected by A8.1/A8.2).
# FROZEN_FLOOR is filled in AFTER the calibration receipt is measured AND
# passes trained-at-all (0.5 * |delta_sens|) -- None until then;
# --emit/--selftest refuse to run against a None floor (fail-closed: a
# missing floor must never silently pass).
CALIBRATION_SEED = 90201
PRODUCTION_SEED = 90002
FROZEN_FLOOR = None  # set AFTER the A8.2 calibration passes trained-at-all
# AND direction_correct (outcome (a) only -- (b)/(c2) leave this None).


class SensitivityError(ValueError):
    pass


def _now_ts():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------

def block_len_of(seq: int, n_mtp: int) -> int:
    return seq + 1 + n_mtp


def n_target_windows_of(n_windows: int, fraction: float) -> int:
    k = max(1, round(fraction * n_windows))
    if k >= n_windows:
        raise SensitivityError(
            f"TARGET_TOO_LARGE: {k} target windows >= {n_windows} total")
    return k


def build_token_pools(seed: int, n_windows: int, n_target_windows: int,
                       seq: int, n_mtp: int, vocab: int):
    """TARGET_TOKENS (length exactly covering n_target_windows clean
    windows) and FILLER_TOKENS (the remainder), drawn from disjoint rng
    streams derived from the single `seed` argument -- one seed controls
    the whole fixture instance (calibration vs production differ only by
    which seed is passed here)."""
    import numpy as np
    block_len = block_len_of(seq, n_mtp)
    n_tokens_total = (n_windows - 1) * seq + block_len
    target_len = (n_target_windows - 1) * seq + block_len
    filler_len = n_tokens_total - target_len
    if filler_len <= 0:
        raise SensitivityError(
            f"FILLER_EMPTY: target_len={target_len} >= n_tokens_total={n_tokens_total}")
    rng_target = np.random.default_rng(seed)
    rng_filler = np.random.default_rng(seed + 1)
    # 1..vocab-1 (0 reserved as the doc-separator convention used elsewhere
    # in this apparatus, e.g. run_v0_segment's own default synthetic shard).
    target_tokens = rng_target.integers(1, vocab, size=target_len, dtype=np.int64)
    filler_tokens = rng_filler.integers(1, vocab, size=filler_len, dtype=np.int64)
    return (target_tokens.astype(np.uint16), filler_tokens.astype(np.uint16),
            n_tokens_total, target_len, filler_len)


def build_arm_streams(target_tokens, filler_tokens):
    """EARLY = target ++ filler (target windows at the FRONT of the
    trained curriculum); LATE = filler ++ target (target windows at the
    BACK). Byte-identical token pools, only concatenation order differs --
    this IS the treatment."""
    import numpy as np
    early = np.concatenate([target_tokens, filler_tokens])
    late = np.concatenate([filler_tokens, target_tokens])
    return early, late


def assert_token_multiset_equality(early_stream, late_stream) -> None:
    """The synthetic-fixture analog of exp711_permute's hash-multiset
    equality assert: EARLY and LATE differ only in ORDER, never in
    content -- sorted byte-multisets must match exactly."""
    import numpy as np
    if not np.array_equal(np.sort(early_stream), np.sort(late_stream)):
        raise SensitivityError(
            "TOKEN_MULTISET_MISMATCH: EARLY and LATE streams are not a pure "
            "reordering of the same token multiset")


# ---------------------------------------------------------------------------
# Step -> target-window bookkeeping, reusing exp711_permute's own
# identity_arm / batch_window_ids -- no bespoke second stepper.
# ---------------------------------------------------------------------------

def target_window_ids_for(arm_name: str, n_windows: int, n_target_windows: int):
    if arm_name == "EARLY":
        return set(range(n_target_windows))
    if arm_name == "LATE":
        return set(range(n_windows - n_target_windows, n_windows))
    raise SensitivityError(f"unknown arm {arm_name!r}")


def last_target_step(arm_name: str, n_windows: int, n_target_windows: int,
                      n_steps: int, batch_size: int) -> int:
    """The last GLOBAL STEP (0-indexed) whose batch touches any target
    window, walked via exp711_permute.identity_arm + batch_window_ids
    (the physical byte layout already encodes EARLY/LATE placement, so
    the arm_order fed to batch_window_ids is the canonical/identity
    order -- exactly the case exp711_permute's own selftest validates
    against the real PackedShardLoader)."""
    manifest_ids = list(range(n_windows))
    arm_order = ep.identity_arm(manifest_ids)
    targets = target_window_ids_for(arm_name, n_windows, n_target_windows)
    last = None
    for step in range(n_steps):
        wids = ep.batch_window_ids(arm_order, step, batch_size)
        if targets.intersection(wids):
            last = step
    if last is None:
        raise SensitivityError(
            f"NO_TARGET_STEP: arm {arm_name!r} never trains on a target window")
    return last


def assert_validity_requirements(cfg: dict, n_windows: int, n_target_windows: int,
                                  n_steps: int, batch_size: int,
                                  total_steps: int) -> dict:
    """The three frozen validity requirements, asserted directly against
    the constructed step schedule -- never assumed by construction alone."""
    last_early = last_target_step("EARLY", n_windows, n_target_windows, n_steps, batch_size)
    last_late = last_target_step("LATE", n_windows, n_target_windows, n_steps, batch_size)
    gap_early = (n_steps - 1) - last_early
    gap_late = (n_steps - 1) - last_late

    # (1) the post-last-exposure gap must differ by more than 1 step.
    if not (gap_early - gap_late) > 1:
        raise SensitivityError(
            f"VALIDITY_GAP_FAIL: gap_early={gap_early} gap_late={gap_late} "
            f"does not differ by more than 1 step")

    # (2) no EMA / parameter averaging -- run_v0_segment as called by this
    # module never receives an EMA parameter; there is none to disable.
    # Disclosed here rather than silently assumed.
    ema_used = False

    # (3) LR schedule not fully decayed before the target's last exposure
    # in EITHER arm -- asserted directly against the WSD schedule's own
    # stable_until_frac boundary (decay has not even STARTED at that
    # step, which is strictly stronger than "not fully decayed").
    sc = cfg["schedule"]
    decay_start_step = sc["stable_until_frac"] * total_steps
    if not (last_early < decay_start_step):
        raise SensitivityError(
            f"VALIDITY_LR_DECAY_FAIL[EARLY]: last exposure step {last_early} "
            f">= decay start step {decay_start_step}")
    if not (last_late < decay_start_step):
        raise SensitivityError(
            f"VALIDITY_LR_DECAY_FAIL[LATE]: last exposure step {last_late} "
            f">= decay start step {decay_start_step}")

    return {
        "last_target_step": {"EARLY": last_early, "LATE": last_late},
        "gap_after_last_exposure": {"EARLY": gap_early, "LATE": gap_late},
        "gap_difference": gap_early - gap_late,
        "ema_used": ema_used,
        "decay_start_step": decay_start_step,
        "decay_started_before_last_exposure": {"EARLY": False, "LATE": False},
    }


# ---------------------------------------------------------------------------
# Arm training + target-only eval
# ---------------------------------------------------------------------------

def run_arm(arm_name: str, stream_tokens, run_dir: str, cfg: dict, model_seed: int):
    """Trains one arm via the literal run_v0_segment(live=False, ...)
    path and returns (segment_receipt, last_checkpoint_dir)."""
    import torch
    shard_dir = os.path.join(run_dir, "shards")
    os.makedirs(shard_dir, exist_ok=True)
    write_packed_shard(os.path.join(shard_dir, f"{arm_name.lower()}-00000.bin"),
                        [int(t) for t in stream_tokens])

    torch.manual_seed(model_seed)
    random.seed(model_seed)
    receipt = run_v0_segment(
        run_dir, cfg, n_steps=N_STEPS, total_steps=TOTAL_STEPS, live=False,
        checkpoint_every=N_STEPS, pace_s=0.0, segment_id=f"exp711-sens-{arm_name}",
        shard_dir=shard_dir, tiny_dims=TINY_DIMS, batch_size=BATCH_SIZE,
        ce_chunk_tokens=CE_CHUNK_TOKENS, mmap_cache_dir=None)
    if receipt["verdict"] != "V0_SEGMENT_COMPLETE":
        raise SensitivityError(
            f"ARM_RUN_INCOMPLETE[{arm_name}]: verdict={receipt['verdict']!r}")
    if receipt["last_checkpoint"] is None:
        raise SensitivityError(f"ARM_NO_CHECKPOINT[{arm_name}]: last_checkpoint is None")
    return receipt, receipt["last_checkpoint"]


def assess_trained_at_all(early_receipt: dict, late_receipt: dict,
                           nll_early: float, nll_late: float, vocab: int) -> dict:
    """A8.1 mechanical floor-eligibility precondition (issue #711 comment
    4942042739): total train-loss drop >= TRAINED_LOSS_DROP_MIN_NATS
    (checked per arm, the binding value is the min of the two) AND
    min(nll_target_early, nll_target_late) <= ln(vocab) -
    TRAINED_NLL_MARGIN_NATS. This is OUTCOME data (did the experiment
    train enough to be informative), not an apparatus-integrity guard --
    it never raises; a failing result is itself the finding."""
    import math
    early_drop = early_receipt["loss_first"] - early_receipt["loss_last"]
    late_drop = late_receipt["loss_first"] - late_receipt["loss_last"]
    loss_drop_min = min(early_drop, late_drop)
    ln_vocab = math.log(vocab)
    nll_ceiling = ln_vocab - TRAINED_NLL_MARGIN_NATS
    min_nll = min(nll_early, nll_late)
    passed = (loss_drop_min >= TRAINED_LOSS_DROP_MIN_NATS) and (min_nll <= nll_ceiling)
    return {
        "early_loss_drop": round(early_drop, 6),
        "late_loss_drop": round(late_drop, 6),
        "loss_drop_min": round(loss_drop_min, 6),
        "loss_drop_threshold": TRAINED_LOSS_DROP_MIN_NATS,
        "ln_vocab": round(ln_vocab, 6),
        "nll_ceiling": round(nll_ceiling, 6),
        "min_nll_target": round(min_nll, 6),
        "passed": passed,
    }


def eval_target(ckpt_dir: str, cfg: dict, target_tokens, seq: int, n_mtp: int,
                 n_target_windows: int, chunk_tokens: int):
    """ONE forward pass (no backward) over the TARGET window content
    itself, using the arm's own final trained weights. Returns
    (nll_target: float, n_valid_tokens: int)."""
    import torch
    with tempfile.TemporaryDirectory(prefix="exp711sens_targeteval_") as tmp:
        shard_dir = os.path.join(tmp, "target_only")
        os.makedirs(shard_dir)
        write_packed_shard(os.path.join(shard_dir, "target-00000.bin"),
                            [int(t) for t in target_tokens])
        loader = PackedShardLoader(shard_dir, seq=seq, n_mtp=n_mtp)
        if loader.n_windows != n_target_windows:
            raise SensitivityError(
                f"TARGET_LOADER_WINDOW_MISMATCH: expected {n_target_windows}, "
                f"got {loader.n_windows}")

        model, _, _, _ = build_v0_model(cfg, live=False, tiny_dims=TINY_DIMS, device="cpu")
        m_state, _, _, _ = load_checkpoint(ckpt_dir)
        model.load_state_dict(m_state)
        model.eval()

        x, y0, _ = loader.batch(0, n_target_windows)
        with torch.no_grad():
            hidden_out = model.backbone(x)
            h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
            nll, n_valid = chunked_cross_entropy(
                h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=chunk_tokens)
        return float(nll), n_valid


# ---------------------------------------------------------------------------
# Full fixture orchestration
# ---------------------------------------------------------------------------

def run_sensitivity_fixture(seed: int, floor: "float | None") -> dict:
    """Builds the fixture, trains both arms, evaluates the target content
    on each arm's final weights, and returns the full apparatus receipt.
    `floor` is None for a calibration run (raw measurement only, no
    PASS/FAIL disposition yet); a numeric floor for production/selftest
    runs (direction_correct + measured_delta computed AND checked)."""
    cfg = load_contract()
    # AMENDMENT A8.2: caller-side deepcopy, frozen contract file on disk
    # never touched. Identical override for BOTH arms; disclosed below.
    cfg_train = copy.deepcopy(cfg)
    cfg_train["optimizer"]["lr_adamw"] = A82_LR_ADAMW_OVERRIDE
    cfg_overrides = {
        "amendment": "A8.2", "issue_comment": 4942176352,
        "lr_adamw": {"frozen_contract_value": cfg["optimizer"]["lr_adamw"],
                     "override_value": A82_LR_ADAMW_OVERRIDE,
                     "applied_to": ["EARLY", "LATE"]},
    }
    n_windows = N_STEPS * BATCH_SIZE
    n_target_windows = n_target_windows_of(n_windows, TARGET_FRACTION)

    validity = assert_validity_requirements(
        cfg, n_windows, n_target_windows, N_STEPS, BATCH_SIZE, TOTAL_STEPS)

    target_tokens, filler_tokens, n_tokens_total, target_len, filler_len = \
        build_token_pools(seed, n_windows, n_target_windows, SEQ, N_MTP,
                          TINY_DIMS["vocab"])
    early_stream, late_stream = build_arm_streams(target_tokens, filler_tokens)
    assert_token_multiset_equality(early_stream, late_stream)

    # Both arms share the SAME model_seed (derived from `seed`, offset from
    # the token-pool seeds) so init + optimizer trajectory are identical --
    # the ONLY difference between arms is target-block position.
    model_seed = seed + 2

    with tempfile.TemporaryDirectory(prefix="exp711sens_") as tmp:
        early_receipt, early_ckpt = run_arm(
            "EARLY", early_stream, os.path.join(tmp, "early"), cfg_train, model_seed)
        late_receipt, late_ckpt = run_arm(
            "LATE", late_stream, os.path.join(tmp, "late"), cfg_train, model_seed)

        nll_early, nvalid_early = eval_target(
            early_ckpt, cfg_train, target_tokens, SEQ, N_MTP, n_target_windows, CE_CHUNK_TOKENS)
        nll_late, nvalid_late = eval_target(
            late_ckpt, cfg_train, target_tokens, SEQ, N_MTP, n_target_windows, CE_CHUNK_TOKENS)

    delta_sens = nll_early - nll_late  # frozen sign: NLL(EARLY) - NLL(LATE)
    direction_correct = delta_sens > 0.0
    trained_at_all = assess_trained_at_all(
        early_receipt, late_receipt, nll_early, nll_late, TINY_DIMS["vocab"])

    disposition = None
    if floor is not None:
        preflight = ev.sensitivity_preflight(
            {"direction_correct": direction_correct, "measured_delta": delta_sens},
            floor=floor)
        disposition = preflight

    return {
        "seed": seed,
        "model_seed": model_seed,
        "cfg_overrides": cfg_overrides,
        "n_windows": n_windows,
        "n_target_windows": n_target_windows,
        "target_fraction_actual": round(n_target_windows / n_windows, 6),
        "n_tokens_total": int(n_tokens_total),
        "target_len_tokens": int(target_len),
        "filler_len_tokens": int(filler_len),
        "n_steps": N_STEPS,
        "total_steps": TOTAL_STEPS,
        "batch_size": BATCH_SIZE,
        "seq": SEQ,
        "n_mtp": N_MTP,
        "validity": validity,
        "nll_target_early": round(nll_early, 6),
        "nll_target_late": round(nll_late, 6),
        "n_valid_tokens_early": nvalid_early,
        "n_valid_tokens_late": nvalid_late,
        "delta_sens": round(delta_sens, 6),
        "direction_correct": direction_correct,
        "measured_delta": delta_sens,
        "trained_at_all": trained_at_all,
        "floor": floor,
        "disposition": disposition,
        "early_segment_receipt_summary": {
            "verdict": early_receipt["verdict"], "steps": early_receipt["steps"],
            "loss_first": early_receipt["loss_first"], "loss_last": early_receipt["loss_last"]},
        "late_segment_receipt_summary": {
            "verdict": late_receipt["verdict"], "steps": late_receipt["steps"],
            "loss_first": late_receipt["loss_first"], "loss_last": late_receipt["loss_last"]},
        "apparatus_note": ("memorization-recency control -- evaluated on trained "
                            "content by construction; never a generalization claim"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _stream_sha(stream) -> str:
    import numpy as np
    return hashlib.sha256(np.asarray(stream, dtype="<u2").tobytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true",
                     help="ONE seed-pinned calibration run (CALIBRATION_SEED); "
                          "raw measurement only, receipt for posting to #711")
    ap.add_argument("--emit", action="store_true",
                     help="production run (PRODUCTION_SEED) checked against "
                          "FROZEN_FLOOR")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if args.calibrate:
        result = run_sensitivity_fixture(CALIBRATION_SEED, floor=None)
        os.makedirs(OUT_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = os.path.join(OUT_DIR, f"exp711-sensitivity-calibration-{ts}.json")
        receipt_out = {
            "ticket": "EXP711-SENSITIVITY-CALIBRATION", "ts": _now_ts(),
            "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
            "refs": [711, 739], "role": "calibration (A8.1 sizing + A8.2 "
            "lr_adamw override; raw measurement, no floor disposition unless "
            "trained_at_all.passed -- floor is derived FROM this receipt "
            "per A8 step 2 / A8.1 / A8.2)",
            **result,
        }
        checked_write(out_path, receipt_out)
        print(f"EXP711_SENSITIVITY_CALIBRATE_OK: {out_path}")
        print(json.dumps({
            "delta_sens": result["delta_sens"],
            "direction_correct": result["direction_correct"],
            "nll_target_early": result["nll_target_early"],
            "nll_target_late": result["nll_target_late"],
            "trained_at_all": result["trained_at_all"],
            "proposed_floor_0.5x": round(0.5 * abs(result["delta_sens"]), 6),
            "floor_eligible": result["trained_at_all"]["passed"],
        }, indent=2))
        return

    if args.emit:
        if FROZEN_FLOOR is None:
            raise SystemExit(
                "FROZEN_FLOOR_UNSET: post the calibration receipt to #711 and "
                "bake in FROZEN_FLOOR = 0.5 * |delta_sens(calibration)| first")
        result = run_sensitivity_fixture(PRODUCTION_SEED, floor=FROZEN_FLOOR)
        os.makedirs(OUT_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = os.path.join(OUT_DIR, f"exp711-sensitivity-{ts}.json")
        receipt_out = {
            "ticket": "EXP711-SENSITIVITY", "ts": _now_ts(),
            "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
            "refs": [711, 739], "role": "production", **result,
        }
        checked_write(out_path, receipt_out)
        print(f"EXP711_SENSITIVITY_EMIT_OK: {out_path}")
        print(json.dumps(result["disposition"], indent=2))
        return

    ap.error("pass --calibrate, --emit, or --selftest")


# ---------------------------------------------------------------------------
# Selftest -- runs the REAL production-seed fixture end to end (there is no
# cheaper correctness check for a mechanism whose entire point is "does the
# real consumer path detect a planted effect"), plus structural asserts and
# a live sensitivity_preflight() integration check.
# ---------------------------------------------------------------------------

def _selftest():
    if FROZEN_FLOOR is None:
        raise AssertionError(
            "SELFTEST: FROZEN_FLOOR must be baked in before selftest can run "
            "(post-calibration step)")
    assert CALIBRATION_SEED != PRODUCTION_SEED, (
        "SELFTEST: calibration and production seeds must differ (A8 step 3)")

    # --- bookkeeping unit checks (cheap, no torch) ------------------------
    n_windows = N_STEPS * BATCH_SIZE
    n_target = n_target_windows_of(n_windows, TARGET_FRACTION)
    assert 0 < n_target < n_windows

    early_targets = target_window_ids_for("EARLY", n_windows, n_target)
    late_targets = target_window_ids_for("LATE", n_windows, n_target)
    assert early_targets == set(range(n_target))
    assert late_targets == set(range(n_windows - n_target, n_windows))
    assert early_targets.isdisjoint(late_targets) or n_target * 2 > n_windows, (
        "SELFTEST: EARLY/LATE target blocks unexpectedly overlap at this "
        "fixture size")

    cfg = load_contract()
    validity = assert_validity_requirements(
        cfg, n_windows, n_target, N_STEPS, BATCH_SIZE, TOTAL_STEPS)
    assert validity["gap_difference"] > 1
    assert validity["last_target_step"]["EARLY"] < validity["last_target_step"]["LATE"], (
        "SELFTEST: EARLY's last target exposure must be earlier than LATE's")

    # A corrupted/degenerate fixture (target spans the WHOLE window range,
    # so EARLY and LATE are identical) must be refused by n_target_windows_of
    # or produce gap_difference == 0 -- prove the validity assert actually
    # catches a broken construction, not just accepts the good one.
    try:
        assert_validity_requirements(cfg, n_windows, n_windows, N_STEPS,
                                     BATCH_SIZE, TOTAL_STEPS)
        raise AssertionError(
            "SELFTEST: validity assert failed to catch target_fraction=1.0 "
            "(EARLY/LATE degenerate to the same last-exposure step)")
    except SensitivityError:
        pass

    # --- token pool + multiset checks --------------------------------------
    tgt, fill, n_tok, tgt_len, fill_len = build_token_pools(
        PRODUCTION_SEED, n_windows, n_target, SEQ, N_MTP, TINY_DIMS["vocab"])
    assert tgt_len + fill_len == n_tok
    early_stream, late_stream = build_arm_streams(tgt, fill)
    assert len(early_stream) == len(late_stream) == n_tok
    assert_token_multiset_equality(early_stream, late_stream)
    # a genuinely different multiset must be caught, not silently accepted.
    import numpy as np
    corrupted = late_stream.copy()
    corrupted[0] = (int(corrupted[0]) % 63) + 1 if corrupted[0] != (int(corrupted[0]) % 63) + 1 else 1
    if corrupted[0] not in early_stream or list(np.sort(corrupted)) != list(np.sort(early_stream)):
        try:
            assert_token_multiset_equality(early_stream, corrupted)
            raise AssertionError(
                "SELFTEST: token multiset assert failed to catch a corrupted stream")
        except SensitivityError:
            pass

    # target content is byte-identical regardless of arm placement.
    assert early_stream[:tgt_len].tolist() == tgt.tolist()
    assert late_stream[fill_len:].tolist() == tgt.tolist()

    # --- full apparatus run at PRODUCTION_SEED (the real consumer path) ---
    result = run_sensitivity_fixture(PRODUCTION_SEED, floor=FROZEN_FLOOR)
    assert result["seed"] == PRODUCTION_SEED
    assert result["n_valid_tokens_early"] > 0
    assert result["n_valid_tokens_late"] > 0
    assert isinstance(result["delta_sens"], float)
    assert result["disposition"] is not None
    assert result["disposition"]["status"] in ("PROCEED", "INVALID_SCREEN"), (
        f"SELFTEST: unexpected disposition status {result['disposition']}")

    # --- sensitivity_preflight() integration: this receipt shape must be
    # exactly what exp711_verdict's preflight (landed 0cee0b4) accepts.
    preflight_receipt = {"direction_correct": result["direction_correct"],
                          "measured_delta": result["measured_delta"]}
    live_check = ev.sensitivity_preflight(preflight_receipt, floor=FROZEN_FLOOR)
    assert live_check["status"] == result["disposition"]["status"]

    # A deliberately malformed/missing/wrong-direction/below-floor receipt
    # must still hard-stop through the SAME preflight (already covered by
    # exp711_verdict's own selftest; re-asserted here at the integration
    # boundary this module actually produces).
    assert ev.sensitivity_preflight(None, floor=FROZEN_FLOOR)["status"] == "INVALID_SCREEN"
    below = {"direction_correct": True, "measured_delta": FROZEN_FLOOR / 100.0}
    assert ev.sensitivity_preflight(below, floor=FROZEN_FLOOR)["status"] == "INVALID_SCREEN"

    print("EXP711_SENSITIVITY_SELFTEST_PASS")
    print(json.dumps({
        "n_windows": n_windows, "n_target_windows": n_target,
        "target_fraction_actual": result["target_fraction_actual"],
        "gap_difference": validity["gap_difference"],
        "production_seed": PRODUCTION_SEED,
        "calibration_seed": CALIBRATION_SEED,
        "frozen_floor": FROZEN_FLOOR,
        "nll_target_early": result["nll_target_early"],
        "nll_target_late": result["nll_target_late"],
        "delta_sens": result["delta_sens"],
        "direction_correct": result["direction_correct"],
        "preflight_status": result["disposition"]["status"],
    }, indent=2))


if __name__ == "__main__":
    main()
