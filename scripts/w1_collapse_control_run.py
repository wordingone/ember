# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""w1_collapse_control_run.py -- W1 token-collapse control-run producer (#71).

Builds the width-matched from-scratch baseline runner specified by the FROZEN
spec `docs/spec/w1-token-collapse-control-v1.md` and pinned by the pricing
receipt `scratch/w1-control/w1-pricing-20260704T063236Z.json`. Two phases:

  Phase 1 (capability-point leg): evaluate the grow arm's terminal checkpoint
    on a FIXED held-out batch (sha-pinned token ids, the function_preservation
    _check idiom) to get the pre-registered target_eval_loss. No training on
    the real path.
  Phase 2 (control leg): identical architecture, RANDOM init, standard
    from-scratch cosine+warmup LR schedule (never the grow-path's continuation
    schedule -- spec section 2 anti-poison clause), eval on the SAME
    sha-pinned batch every K steps via the SAME code path as phase 1,
    early-stop when eval_loss <= target, hard ceiling, resumable
    checkpointing, governor 0.8 one-job.

THIS invocation is CPU --dry-run ONLY. A tiny toy architecture stands in for
the real rung-1 config; phase 1's "checkpoint" is a tiny model trained a few
steps inside this harness (no real lineage exists at CPU-dry-run scale), so
every dry-run receipt field is honestly labeled dry_run=true,
is_real_lineage=false. The real GPU run (real rung-1 checkpoint, real
tokenizer/shards, 1533-step ceiling, K=100) is maintainer-window-scheduled
(issue #53) and is never fired by this builder -- --device cuda requires
--live AND EMBER_GATE_AUTHORIZED=1, and even then refuses to fabricate
synthetic shards (mirrors the eng-54 #194 guard already in
timeshare_pretrain.run_v0_segment).

Citations (read-only; never edited by this script):
  spec              docs/spec/w1-token-collapse-control-v1.md
  issue             #71 (pins the two-phase structure; #62 opened the wall)
  pricing receipt   scratch/w1-control/w1-pricing-20260704T063236Z.json
  grow-arm terminal receipts/cbase-grow-rung/cbase-grow-rung1-live-20260703T155711Z.json
  v0/c03 config doc fp19-envelope.md, quoted verbatim in
                    scripts/timeshare_pretrain.py's module docstring
                    ("c03 shape -- 0.37B decoder, hidden 1024, 20 layers,
                    16 heads, vocab 32k, seq 1024, tied embeddings")

Usage (dry run, the only supported mode from this workstation):
  python scripts/w1_collapse_control_run.py --dry-run
  python scripts/w1_collapse_control_run.py --dry-run --out-dir scratch/w1-control/dry-run/custom

Real run (maintainer-window only, never executed here):
  EMBER_GATE_AUTHORIZED=1 python scripts/w1_collapse_control_run.py \
      --live --device cuda --shard-dir <real shard dir>

Receipt: receipts/ember-c-scale/w1-collapse-control-<ts>.json, schema
w1-collapse-control/v1 per spec section 7.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import numpy as np
import torch

from timeshare_pretrain import (  # reused, not edited (hard rail: new files only)
    save_checkpoint,
    load_checkpoint,
    capture_rng,
    restore_rng,
    pacing_snapshot,
    _pace_reset,
    _pace_record,
    check_resume_integrity,
    FP19_PACE_S,
    CONTRACT_PATH as PRETRAIN_CONTRACT_PATH,
    build_split_optimizer,
    save_optimizers_state,
    load_optimizers_state,
    resolve_ce_impl,
    mtp_total_loss,
)
from receipt_write import checked_write
from w1_recheck_cache import (
    check_recheck_cache,
    write_recheck_cache,
    disclose_cache_hit,
)

# ---------------------------------------------------------------------------
# Citations (paths + the exact figures pinned by the pricing/rung receipts).
# Read at runtime for the "real_lineage_reference" block; never used to drive
# dry-run arithmetic (dry-run computes everything from its own toy execution).
# ---------------------------------------------------------------------------

SPEC_REF = "docs/spec/w1-token-collapse-control-v1.md"
ISSUE_REF = "#71"
DEFAULT_PRICING_RECEIPT = os.path.join(
    REPO, "scratch", "w1-control", "w1-pricing-20260704T063236Z.json")
# Cross-tree source (per spec section 2 / the pricing receipt's own note):
# the grow-arm lineage receipts live in the ember work tree, not this
# goalforge tree. Read-only citation; never written to.
DEFAULT_RUNG_RECEIPT = os.path.normpath(os.path.join(
    REPO, "..", "ember", "receipts", "cbase-grow-rung",
    "cbase-grow-rung1-live-20260703T155711Z.json"))

REAL_EVAL_CADENCE_K = 100          # pinned by the pricing receipt
# Issue #71's body states "hard ceiling 1533 steps (25,100,288 tokens)".
# The exact arithmetic (see real_hard_ceiling_derivation) gives 1532: 16384 *
# 1532 = 25,100,288 EXACTLY (no remainder), so ceil(25,100,288 / 16384) =
# 1532, not 1533. This is a genuine one-step discrepancy between the issue
# text and the exact math -- flagged rather than silently propagated (same
# convention as the rung receipt's own params_dedup ambiguity note). Both
# figures are carried in the receipt; ISSUE_STATED is what a maintainer
# invocation should pass as --ceiling-steps unless they resolve the
# discrepancy first.
REAL_HARD_CEILING_STEPS_ISSUE_STATED = 1533
REAL_HARD_CEILING_STEPS = REAL_HARD_CEILING_STEPS_ISSUE_STATED

# ---------------------------------------------------------------------------
# REAL LIVE PATH constants (issue #82).
#
# Corpus citation (read-only; the combined sha is ASSERTED at launch, never
# trusted from a receipt's self-report): receipts/corpus-verification-
# 20260704T095213Z.json -- 26/26 shards sha-verified twice independently
# (coreutils + manifest_sha), n_files=26, total_tokens=6,977,868,758.
# ---------------------------------------------------------------------------

CORPUS_VERIFICATION_RECEIPT = os.path.join(
    REPO, "receipts", "corpus-verification-20260704T095213Z.json")
CORPUS_MANIFEST_COMBINED_SHA256_EXPECTED = (
    "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a")

# Issue #82 reopened defect: RealW1Model omitted the MTP auxiliary heads that
# every real checkpoint carries (production ALWAYS constructs mtp_heads in
# _V0Real.__init__, timeshare_pretrain.py, regardless of whether the MTP loss
# term is enabled for training -- see run_v0_segment's mtp_enabled branch,
# which only gates whether mtp_heads receive a loss term, never whether they
# exist in the state_dict). PRETRAIN_CONTRACT_PATH (imported above as
# timeshare_pretrain.CONTRACT_PATH) is the SAME config file production reads
# its mtp_aux_heads.n_heads from -- read fresh at derive time, never
# hardcoded, so a config change is never silently stale.

# Second, INDEPENDENT launch interlock (verification leg (c), issue #82).
# refuse_unless_dry_run_safe's existing EMBER_GATE_AUTHORIZED gate is a
# general-purpose flag reused elsewhere in the repo (e.g. timeshare_pretrain.
# _check_launch_interlock) -- a builder/test session can end up with it set
# for unrelated reasons. On this machine torch.cuda.is_available() is True
# even from a builder session (the GPU exists; it is merely window-occupied
# by the maintainer's own concurrent job) -- so neither hardware presence nor
# the general authorization flag is a sufficient safety signal on its own.
# This SEPARATE env var is the deterministic second key: set ONLY by the
# maintainer's actual GPU-launch runbook, NEVER by this builder, NEVER in a
# test. Do NOT weaken EMBER_GATE_AUTHORIZED's existing check to compensate --
# both gates are required, independently, every time.
MAINTAINER_WINDOW_ENV = "EMBER_W1_MAINTAINER_WINDOW_CONFIRMED"

# Same convention as scratch/corpus-wire/contamination_check.py.
CONTAMINATION_WINDOW_TOKENS = 13
CONTAMINATION_ROLL_BASE = 1000000007

# Issue #445: contamination_recheck's own per-shard rolling-hash buffer used
# to materialize the WHOLE shard as one uint64 array (arr64 = arr.astype(
# uint64); h = np.zeros(n_out, uint64)) -- for a 268M-token shard that is a
# ~2.14GB contiguous allocation, exactly the "268M-element uint64" /
# "2GiB contiguous" ArrayMemoryError that killed the P1 point-3 final
# recheck (issue #445 instance 2). Same bound + retry floor as
# w2_heldout/build_decontam_batch_mp.py's DEFAULT_SCAN_CHUNK_TOKENS /
# MIN_SCAN_SUBCHUNK_TOKENS (defined locally here, not imported, to avoid a
# circular import -- that module imports contamination_recheck FROM this one).
DEFAULT_SCAN_CHUNK_TOKENS = 33_554_432  # 32M tokens per chunk (memory-safe slicing)
MIN_SCAN_SUBCHUNK_TOKENS = 1 << 20  # 1,048,576 tokens -- retry floor; below this
# a further halving cannot help and the box is genuinely exhausted.

# ---------------------------------------------------------------------------
# W1b (#355) -- unwidened-continuation control. The grow arm's MARGINAL
# (post-seed) token bill: 156 steps @ batch16 seq1024 = 156*16*1024, cited
# verbatim from #355's own pre-registration and cross-checked here via exact
# arithmetic (never just copied): 156 * 16 * 1024 = 2,555,904.
W1B_MARGINAL_TOKENS_GROWPATH = 2_555_904
W1B_ISSUE_REF = "#355"
# #355's pre-registered early-stop target (informational default only --
# the actual gate is always target_eval_loss from phase 1, computed fresh;
# this constant is never used to drive a comparison, only carried/citable).
W1B_PREREGISTERED_EARLY_STOP_EVAL_LOSS = 9.375


def real_hard_ceiling_derivation(ceiling_tokens: int, batch: int, seq: int) -> int:
    """ceil(ceiling_tokens / (batch*seq)) -- the real-run step ceiling,
    derived fresh from the pricing receipt's own ceiling_tokens figure (never
    hardcoded)."""
    return -(-ceiling_tokens // (batch * seq))  # ceil via negated floor division


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tokens(token_ids: "torch.Tensor") -> str:
    """sha256 over the raw int64 bytes of a token-id tensor -- same convention
    as the function_preservation_check idiom (rung receipt: batch/seqlen/
    token_ids_sha256/generator_seed)."""
    arr = token_ids.detach().to("cpu").contiguous().to(torch.int64).numpy()
    return sha256_hex(arr.tobytes())


# ---------------------------------------------------------------------------
# Real-architecture derivation (citation-only; never drives dry-run numbers).
#
# The rung-1 terminal receipt does not carry vocab/hidden as named fields.
# Every figure below is either read directly or derived with its arithmetic
# shown -- no silent guess:
#   vocab   = 32000                          (pricing receipt control_arm.
#                                              target_architecture string)
#   seq     = 1024, batch = 16               (pricing receipt +
#                                              rung receipt g_budget_preflight.
#                                              requested_run)
#   hidden  = 1024                           (DERIVED: rung receipt
#                                              params_dedup.measured_duplicate
#                                              _numel = 32,768,000 = vocab *
#                                              hidden tied-embedding count;
#                                              32,768,000 / 32000 = 1024)
#   ff_grown = 16384                         (rung receipt, the grow TARGET --
#                                              this IS the rung-1 terminal FF
#                                              width)
#   params_unique_after = 1,188,865,024      (rung receipt, D4-authoritative)
#   params_state_dict_sum_after = 1,221,633,024 (rung receipt, carried
#                                              alongside per D4 ruling)
#   layers = 20, heads = 16                  (NOT independently re-derivable
#                                              from the grow-rung receipt
#                                              chain -- carried from the v0/
#                                              c03 config precedent quoted in
#                                              scripts/timeshare_pretrain.py's
#                                              module docstring, fp19-envelope
#                                              .md. Flagged, not silently
#                                              assumed.)
# ---------------------------------------------------------------------------

def rung_provenance_info(args: argparse.Namespace) -> dict:
    """Attempt-2 crash fix (issue #121): the terminal receipt writer used to
    hash args.rung_receipt unconditionally, even in --rung-manifest mode
    (item 7 above) where args.rung_receipt is never loaded and keeps its
    DEFAULT_RUNG_RECEIPT value -- a path that does not resolve inside this
    worktree. That crashed sha256_file with FileNotFoundError on receipt
    write, after a real run had already trained through to an early-stop
    match. Discloses which provenance source was actually used, and hashes
    that one -- never the unused default."""
    if args.rung_manifest:
        return {"mode": "manifest", "path": args.rung_manifest,
                "sha256": sha256_file(args.rung_manifest)}
    return {"mode": "receipt", "path": args.rung_receipt,
            "sha256": sha256_file(args.rung_receipt)}


def derive_rung_receipt_from_manifest(manifest_path: str) -> dict:
    """Issue #121 item 7: DEFAULT_RUNG_RECEIPT (a bespoke aggregate receipt
    documenting the rung-1 grow+stabilize run) does not exist on disk or in
    any git history reachable from this branch (mapped separately). What DOES
    exist is the real, sha-verifiable per-checkpoint manifest.json the
    timeshare_pretrain checkpoint format already writes (files{sha256}, step,
    extra{...}). This builds a rung_receipt-SHAPED dict from that manifest
    plus the checkpoint's own model.pt tensor shapes -- every field is
    disclosed as read_from_manifest / derived_from_checkpoint_tensor_shape /
    unavailable under "_derivation" (never invented). NEVER writes a receipt
    file to disk -- purely an in-memory substitution consumed directly by
    derive_real_arch_config / verify_real_checkpoint / derive_wall_hours_
    from_rung, which already tolerate a None tok_s_paced (wall_hours_estimate
    becomes None) and never compute on params_unique_after/params_state_dict_
    sum_after (carried through as receipt metadata only)."""
    ckpt_dir = os.path.dirname(os.path.abspath(manifest_path))
    manifest = load_json(manifest_path)
    extra = manifest.get("extra", {})
    ff_grown = extra.get("ff_grown")
    ff_grown_derivation = "read_from_manifest.extra.ff_grown"

    model_pt = os.path.join(ckpt_dir, "model.pt")
    state = torch.load(model_pt, map_location="cpu")
    embed_key = next((k for k in state if k.endswith("embed_tokens.weight")), None)
    if embed_key is None:
        raise SystemExit(
            f"W1_LIVE_RUNG_MANIFEST_NO_EMBED_KEY: no *embed_tokens.weight key in "
            f"{model_pt!r}'s state_dict -- cannot derive vocab/hidden, refusing.")
    vocab, hidden = (int(x) for x in state[embed_key].shape)

    if ff_grown is None:
        # extra.ff_grown is not written into every checkpoint's manifest (e.g.
        # rung1-.../step-00000766, confirmed absent by direct read) even
        # though the SAME state_dict this function already loads for
        # vocab/hidden carries the FF width directly, in the MLP gate/up
        # projection's output dim -- the identical
        # derived_from_checkpoint_tensor_shape class already used for
        # vocab/hidden above, just applied to a second tensor. Never a
        # workaround around a safety gate: this is not a contamination/
        # authorization interlock, only an incomplete field read. Falls
        # back to the manifest-missing hard refusal only if the state_dict
        # itself lacks any MLP gate/up projection to read.
        gate_key = next((k for k in state if k.endswith("mlp.gate_proj.weight")
                          or k.endswith("mlp.up_proj.weight")), None)
        if gate_key is None:
            raise SystemExit(
                f"W1_LIVE_RUNG_MANIFEST_NO_FF_GROWN: {manifest_path!r} "
                "extra.ff_grown missing AND no mlp.{gate,up}_proj.weight key "
                f"found in {model_pt!r}'s state_dict -- cannot derive "
                "architecture, refusing.")
        ff_grown = int(state[gate_key].shape[0])
        ff_grown_derivation = (
            f"derived_from_checkpoint_tensor_shape: extra.ff_grown absent from "
            f"{manifest_path!r}; {gate_key}.shape[0]={ff_grown}")
    del state  # free the multi-GB state_dict promptly

    return {
        "params_dedup": {"measured_duplicate_numel": vocab * hidden},
        "ff_grown": int(ff_grown),
        "params_unique_after": None,
        "params_state_dict_sum_after": None,
        "stabilization_segment": {"checkpoint": ckpt_dir, "tok_s_paced": None},
        "_derivation": {
            "source_manifest": manifest_path,
            "ff_grown": ff_grown_derivation,
            "params_dedup.measured_duplicate_numel": (
                f"derived_from_checkpoint_tensor_shape: {embed_key}.shape="
                f"({vocab}, {hidden}) -> vocab*hidden"),
            "params_unique_after": "unavailable -- not reconstructable from the "
                                    "checkpoint manifest or tensor shapes alone "
                                    "(needs the original D4 param-dedup methodology)",
            "params_state_dict_sum_after": "unavailable -- same reason",
            "stabilization_segment.tok_s_paced": (
                "unavailable -- a historical wall-clock throughput measurement, "
                "not present in the checkpoint manifest and not reconstructable "
                "after the fact; wall_hours_estimate will be None, not fabricated"),
            "chain_of_custody_note": (
                "verify_real_checkpoint's path-identity check compares the "
                "derived checkpoint path to itself in this mode (there is no "
                "separate rung_receipt authority) -- the per-file sha re-hash "
                "against the checkpoint's OWN manifest is the real protection "
                "this mode retains; it still fails closed on bit-rot/corruption/"
                "a substituted directory with a stale manifest."),
        },
    }


def derive_real_arch_config(pricing_receipt: dict, rung_receipt: dict) -> dict:
    target_arch_str = pricing_receipt["control_arm"]["target_architecture"]
    vocab_match = re.search(r"vocab=(\d+)", target_arch_str)
    seq_match = re.search(r"seq=(\d+)", target_arch_str)
    params_match = re.search(r"(\d+)\s*params", target_arch_str)
    if not (vocab_match and seq_match and params_match):
        raise ValueError(
            "W1_ARCH_DERIVE_FAIL: could not parse vocab/seq/params from "
            f"pricing receipt control_arm.target_architecture={target_arch_str!r}")
    vocab = int(vocab_match.group(1))
    seq = int(seq_match.group(1))
    batch = pricing_receipt["control_arm"]["batch"]

    dedup_numel = rung_receipt["params_dedup"]["measured_duplicate_numel"]
    if dedup_numel % vocab != 0:
        raise ValueError(
            "W1_ARCH_DERIVE_FAIL: measured_duplicate_numel "
            f"{dedup_numel} not divisible by vocab {vocab}")
    hidden = dedup_numel // vocab

    # n_mtp (issue #82 reopened defect): read from the SAME contract file
    # production's _V0Real reads (timeshare_pretrain.py: n_mtp =
    # cfg["objective"]["mtp_aux_heads"]["n_heads"]) -- production constructs
    # mtp_heads unconditionally at that count regardless of whether the MTP
    # loss term is enabled for a given segment, so the checkpoint's state_dict
    # always carries mtp_heads.<k>.weight for k in range(n_mtp). Never
    # hardcoded; read fresh so a contract change can't go silently stale.
    pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)
    n_mtp = pretrain_contract["objective"]["mtp_aux_heads"]["n_heads"]

    return {
        "vocab": vocab,
        "seq": seq,
        "batch": batch,
        "hidden": hidden,
        "n_mtp": n_mtp,
        "n_mtp_source": (
            f"{PRETRAIN_CONTRACT_PATH} objective.mtp_aux_heads.n_heads="
            f"{n_mtp} -- the SAME contract path production's _V0Real reads "
            "(timeshare_pretrain.CONTRACT_PATH), read fresh, never hardcoded"),
        "hidden_derivation": (
            f"params_dedup.measured_duplicate_numel={dedup_numel} / vocab={vocab} "
            f"= {hidden} (tied embed/head dedup count = vocab*hidden)"),
        "ff_grown": rung_receipt["ff_grown"],
        "params_unique_after": rung_receipt["params_unique_after"],
        "params_state_dict_sum_after": rung_receipt["params_state_dict_sum_after"],
        "layers_heads_source": (
            "layers=20, heads=16 carried from the v0/c03 config precedent "
            "(fp19-envelope.md, quoted in scripts/timeshare_pretrain.py's "
            "module docstring) -- NOT independently present in the grow-rung "
            "receipt chain; flagged, not silently assumed"),
        "layers_assumed": 20,
        "heads_assumed": 16,
        "terminal_checkpoint_ref": rung_receipt["stabilization_segment"]["checkpoint"],
        "terminal_checkpoint_receipt": DEFAULT_RUNG_RECEIPT,
    }


# ---------------------------------------------------------------------------
# Shared model -- SAME class for phase 1 and phase 2 (identical architecture,
# spec section 2's control-arm requirement, mechanically enforced via a
# config_sha equality assertion in main()).
#
# Naming mirrors the repo's established _tiny_v0_model idiom
# (embed/blocks/norm/head) so this stand-in reads like the rest of the
# codebase's dry-run models. head carries a bias -- a deliberate dry-run-only
# simplification (see synthetic_corpus() docstring for why) that does NOT
# carry to the real rung-1 architecture, which is tied/no-bias per the
# net2net convention.
# ---------------------------------------------------------------------------

class TinyW1Model(torch.nn.Module):
    def __init__(self, vocab: int, hidden: int, depth: int):
        super().__init__()
        self.embed = torch.nn.Embedding(vocab, hidden)
        self.blocks = torch.nn.ModuleList(
            [torch.nn.Linear(hidden, hidden, bias=False) for _ in range(depth)])
        self.norm = torch.nn.LayerNorm(hidden)
        self.head = torch.nn.Linear(hidden, vocab, bias=True)

    def backbone(self, ids: "torch.Tensor") -> "torch.Tensor":
        h = self.embed(ids)
        for blk in self.blocks:
            h = torch.relu(blk(h))
        return self.norm(h)

    def forward(self, ids: "torch.Tensor") -> "torch.Tensor":
        return self.head(self.backbone(ids))


def arch_config_dict(vocab: int, hidden: int, depth: int, seq: int, batch: int) -> dict:
    return {"vocab": vocab, "hidden": hidden, "depth": depth, "seq": seq,
            "batch": batch, "tied_embeddings": False, "head_bias": True}


def config_sha(cfg: dict) -> str:
    return sha256_hex(json.dumps(cfg, sort_keys=True).encode("utf-8"))


def build_model(cfg: dict, seed: int, device: str) -> "torch.nn.Module":
    torch.manual_seed(seed)
    model = TinyW1Model(cfg["vocab"], cfg["hidden"], cfg["depth"])
    return model.to(device)


# ---------------------------------------------------------------------------
# Standard from-scratch cosine-with-linear-warmup LR schedule.
#
# Deliberately NOT timeshare_pretrain.apply_wsd (the warmup-stable-decay
# schedule used for the grow-path's CONTINUATION training) -- spec section 2:
# "an intentionally-hobbled control inflates the ratio and poisons the
# result." Source: standard SGDR-style cosine decay envelope with linear
# warmup (Loshchilov & Hutter 2016), documented here rather than imported so
# the control arm's schedule is visibly independent of the grow-path module.
# ---------------------------------------------------------------------------

def cosine_warmup_lr(step: int, total_steps: int, *, base_lr: float,
                      warmup_frac: float = 0.1, min_lr_frac: float = 0.1) -> float:
    warmup_steps = max(1, int(total_steps * warmup_frac))
    if step < warmup_steps:
        return base_lr * (step + 1) / warmup_steps
    progress = min(1.0, (step - warmup_steps) / max(1, total_steps - warmup_steps))
    cos = 0.5 * (1.0 + math.cos(math.pi * progress))
    return base_lr * (min_lr_frac + (1.0 - min_lr_frac) * cos)


LR_SCHEDULE_SOURCE = (
    "standard from-scratch cosine-with-linear-warmup (SGDR-style decay "
    "envelope, Loshchilov & Hutter 2016), self-contained in this script -- "
    "distinct from timeshare_pretrain.apply_wsd's warmup-stable-decay "
    "schedule used for the grow-path's continuation training (spec section 2 "
    "anti-poison clause forbids reusing the continuation schedule here)")


def cosine_warmup_frac(step: int, total_steps: int, *,
                        warmup_frac: float = 0.1,
                        min_lr_frac: float = 0.1,
                        warmup_steps: "int | None" = None) -> float:
    """Pure lr-multiplier form of cosine_warmup_lr (base_lr factored out) --
    SAME mechanical contract shape as timeshare_pretrain.wsd_lr_frac, so it
    slots into a split-optimizer apply function the same way apply_wsd does.
    Formula is UNCHANGED from cosine_warmup_lr (issue #82 live-fire finding
    2's matched-recipe control still uses the spec sec.2 anti-poison
    cosine+warmup schedule, only now applied across muon+adamw base_lrs
    instead of one AdamW lr -- cosine_warmup_lr itself is left untouched,
    still used verbatim by the dry-run leg).

    warmup_steps (optional, additive -- issue #118 P1 envelope sweep,
    2026-07-08, docs/deviations.md DEV-003): when given, OVERRIDES
    warmup_frac*total_steps as the EXACT number of warmup steps, never
    re-derived from a fraction (avoids an int()-truncation round-trip for a
    caller that already computed an absolute step count, e.g. prereg
    section 2's "min(2% of budget, absolute cap)" rule). Default None
    preserves prior behavior byte-for-byte for every existing caller."""
    if warmup_steps is not None:
        ws = max(1, int(warmup_steps))
    else:
        ws = max(1, int(total_steps * warmup_frac))
    if step < ws:
        return (step + 1) / ws
    progress = min(1.0, (step - ws) / max(1, total_steps - ws))
    cos = 0.5 * (1.0 + math.cos(math.pi * progress))
    return min_lr_frac + (1.0 - min_lr_frac) * cos


def apply_cosine_warmup(optimizers: dict, base_lrs: dict, step: int,
                         total_steps: int, *, warmup_frac: float = 0.1,
                         min_lr_frac: float = 0.1,
                         warmup_steps: "int | None" = None) -> float:
    """Set every split-optimizer group's lr = base_lr * cosine_warmup_frac
    (step) -- SAME mechanical application shape as timeshare_pretrain.
    apply_wsd (never edited; this is the anti-poison schedule swap-in for
    the matched-recipe control, issue #82 live-fire finding 2). Returns the
    multiplier so the receipt can quote the realized schedule.

    warmup_steps: see cosine_warmup_frac -- additive override, default None
    (unchanged behavior)."""
    mult = cosine_warmup_frac(step, total_steps, warmup_frac=warmup_frac,
                              min_lr_frac=min_lr_frac, warmup_steps=warmup_steps)
    for key, opt in optimizers.items():
        for g in opt.param_groups:
            g["lr"] = base_lrs[key] * mult
    return mult


MATCHED_RECIPE_SCHEDULE_SOURCE = (
    "cosine_warmup_frac/apply_cosine_warmup -- the SAME formula as "
    "cosine_warmup_lr (spec sec.2 anti-poison clause: an intentionally-"
    "hobbled control inflates the ratio and poisons the result, so the "
    "control arm never reuses timeshare_pretrain.apply_wsd, which is tuned "
    "for the grow-path's CONTINUATION training), restructured as a pure "
    "multiplier + apply pair (mirroring apply_wsd's own mechanical shape) "
    "so it can drive the muon+adamw split optimizer's two base_lrs the way "
    "apply_wsd drives production's. This is the ONE deliberate delta from "
    "an otherwise full matched-recipe reuse (issue #82 live-fire finding 2: "
    "production optimizer mix + production MTP aux objective, since the "
    "production optimizer mix demonstrably fits the governed card while "
    "plain AdamW-everything at this shape does not).")


# ---------------------------------------------------------------------------
# Synthetic corpus (dry-run fixture ONLY -- never used on the --live path,
# which requires a real --shard-dir, mirroring the eng-54 #194 guard already
# in timeshare_pretrain.run_v0_segment).
#
# Tokens are i.i.d. draws from a fixed Zipf-like marginal pmf. Next-token
# prediction under i.i.d. tokens has one learnable quantity: the marginal
# distribution itself: cross-entropy is minimized when the model's output
# equals the pmf, converging toward the pmf's true entropy H(pmf) < log
# (vocab) as training proceeds. This is a genuinely learnable AND genuinely
# transferable-to-a-disjoint-held-out-batch quantity (real language modeling
# gets its easiest wins from the same unigram-frequency signal) -- unlike raw
# sequence memorization, which would not generalize to a fresh eval batch at
# all. The head's bias term (see TinyW1Model) is what lets a 2-block linear
# stand-in fit this within tens of CPU steps.
# ---------------------------------------------------------------------------

CORPUS_SEED_PHASE1 = 7
CORPUS_SEED_PHASE2 = 8
EVAL_GENERATOR_SEED = 42  # matches the function_preservation_check precedent


def zipf_pmf(vocab: int) -> "np.ndarray":
    ranks = np.arange(1, vocab + 1, dtype=np.float64)
    weights = 1.0 / ranks
    return weights / weights.sum()


def synthetic_corpus(vocab: int, seq: int, n_windows: int, seed: int) -> "np.ndarray":
    """n_windows windows of (seq+1) i.i.d. tokens each, drawn from the fixed
    Zipf pmf. Returns shape [n_windows, seq+1]."""
    rng = np.random.default_rng(seed)
    pmf = zipf_pmf(vocab)
    flat = rng.choice(vocab, size=n_windows * (seq + 1), p=pmf)
    return flat.reshape(n_windows, seq + 1)


def batch_from_corpus(corpus: "np.ndarray", step: int, batch_size: int,
                       device: str) -> tuple["torch.Tensor", "torch.Tensor"]:
    n_windows = corpus.shape[0]
    idxs = [(step * batch_size + b) % n_windows for b in range(batch_size)]
    windows = corpus[idxs]  # [batch, seq+1]
    x = torch.as_tensor(windows[:, :-1], dtype=torch.long, device=device)
    y = torch.as_tensor(windows[:, 1:], dtype=torch.long, device=device)
    return x, y


def eval_loss_fn(model: "torch.nn.Module", x: "torch.Tensor",
                  y: "torch.Tensor") -> float:
    """The ONE code path both phases use to compute eval loss (spec section 3:
    'evaluated ... in both arms with the same code path')."""
    model.eval()
    with torch.no_grad():
        logits = model(x)
        loss = torch.nn.functional.cross_entropy(
            logits.reshape(-1, logits.shape[-1]), y.reshape(-1))
    model.train()
    return float(loss.item())


def train_step(model: "torch.nn.Module", optimizer: "torch.optim.Optimizer",
                x: "torch.Tensor", y: "torch.Tensor") -> float:
    optimizer.zero_grad(set_to_none=True)
    logits = model(x)
    loss = torch.nn.functional.cross_entropy(
        logits.reshape(-1, logits.shape[-1]), y.reshape(-1))
    loss.backward()
    optimizer.step()
    return float(loss.item())


def train_step_matched_recipe(model: "torch.nn.Module", optimizers: dict,
                               ce_fn, *, x: "torch.Tensor", y0: "torch.Tensor",
                               y_mtp: list, mtp_enabled: bool,
                               mtp_weight: float,
                               ce_chunk_tokens: int = 256) -> float:
    """Matched-recipe training step (issue #82 live-fire finding 2) --
    per-step mechanics mirror run_v0_segment's own composition EXACTLY:
    backbone -> primary CE via ce_fn against model.head.weight -> MTP CEs via
    ce_fn against each model.mtp_heads[k].weight -> mtp_total_loss composition
    -> single backward() over the composite -> step() EACH split optimizer ->
    zero_grad EACH. This is a NEW, separate function from the shared
    train_step() above (untouched, still used verbatim by the dry-run leg) --
    train_step assumes one optimizer and a primary-CE-only objective, neither
    of which holds for the matched-recipe control arm."""
    for opt in optimizers.values():
        opt.zero_grad(set_to_none=True)
    hidden_out = model.backbone(x)
    h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
    primary_ce, _n_primary = ce_fn(h_flat, model.head.weight, y0.reshape(-1),
                                    chunk_tokens=ce_chunk_tokens)
    mtp_ces = []
    if mtp_enabled:
        for k, head in enumerate(model.mtp_heads):
            ce_k, _n_k = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1),
                               chunk_tokens=ce_chunk_tokens)
            mtp_ces.append(ce_k)
    loss = mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
    loss.backward()
    for opt in optimizers.values():
        opt.step()
    return float(loss.detach())


def make_eval_batch(vocab: int, batch: int, seq: int, device: str
                     ) -> tuple["torch.Tensor", "torch.Tensor", str]:
    """FIXED held-out batch, disjoint from both training corpora (own
    generator seed), the function_preservation_check idiom applied to eval
    rather than function-preservation: batch+seqlen+token_ids_sha256+
    generator_seed all recorded."""
    corpus = synthetic_corpus(vocab, seq, n_windows=batch, seed=EVAL_GENERATOR_SEED)
    x = torch.as_tensor(corpus[:, :-1], dtype=torch.long, device=device)
    y = torch.as_tensor(corpus[:, 1:], dtype=torch.long, device=device)
    combined_sha = sha256_tokens(torch.cat([x, y], dim=1))
    return x, y, combined_sha


# ---------------------------------------------------------------------------
# Phase 1 -- capability-point leg.
# ---------------------------------------------------------------------------

def run_phase1_dryrun(cfg: dict, *, train_steps: int, seed: int, device: str,
                       out_dir: str, eval_x, eval_y) -> dict:
    """Dry-run stand-in for 'load the existing rung-1 terminal checkpoint':
    since no real lineage exists at CPU-dry-run scale, this trains a tiny
    model here inside the harness so a real (if toy) capability point exists
    -- labeled dry_run=true, is_real_lineage=false throughout."""
    model = build_model(cfg, seed, device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.05)
    # n_windows must exceed the total draws for this phase (train_steps *
    # batch) with margin -- too few unique windows lets the model MEMORIZE
    # specific (position, token) pairs instead of learning the pmf's
    # marginal, which measurably HURTS held-out eval loss (verified: an
    # 8-window pool drove eval loss above the log(vocab) random baseline).
    # Enough unique windows forces the only transferable regularity --
    # per-position output near the true pmf -- which IS what a disjoint
    # held-out batch rewards.
    corpus = synthetic_corpus(cfg["vocab"], cfg["seq"],
                              n_windows=max(train_steps * cfg["batch"] * 3, 64),
                              seed=CORPUS_SEED_PHASE1)

    losses = []
    t0 = time.perf_counter()
    for step in range(train_steps):
        x, y = batch_from_corpus(corpus, step, cfg["batch"], device)
        losses.append(train_step(model, optimizer, x, y))
    wall_s = time.perf_counter() - t0

    target_eval_loss = eval_loss_fn(model, eval_x, eval_y)

    ckpt_dir = save_checkpoint(
        out_dir, train_steps, model.state_dict(), optimizer.state_dict(),
        capture_rng(),
        extra={"segment_id": "w1-phase1-dryrun-harness", "dry_run": True,
               "is_real_lineage": False, "last_train_loss": losses[-1],
               "target_eval_loss": target_eval_loss})

    tokens_total = train_steps * cfg["batch"] * cfg["seq"]
    return {
        "dry_run": True,
        "is_real_lineage": False,
        "terminal_checkpoint_ref": ckpt_dir,
        "init_seed": seed,
        "train_steps": train_steps,
        "tokens_total": tokens_total,
        "loss_first": round(losses[0], 6),
        "loss_last": round(losses[-1], 6),
        "wall_s": round(wall_s, 3),
        "target_eval_loss": target_eval_loss,
        "note": ("toy model trained inside this harness stands in for the "
                 "real rung-1 terminal checkpoint; proves the capability-"
                 "point leg's mechanics, carries no physical meaning"),
    }


# ---------------------------------------------------------------------------
# Phase 2 -- control leg (random init, from-scratch schedule, early-stop /
# ceiling, one deliberate checkpoint+resume cycle to prove resumability).
# ---------------------------------------------------------------------------

def run_phase2_dryrun(cfg: dict, *, ceiling_steps: int, eval_every: int,
                       checkpoint_every: int, target_eval_loss: float,
                       seed: int, device: str, out_dir: str,
                       eval_x, eval_y, continue_from: str | None = None) -> dict:
    """continue_from (W1b, #355): when given, NO from-scratch init -- the
    model/optimizer/rng state is loaded from this checkpoint dir instead
    (load_continuation_checkpoint, fail-closed on missing/mismatched),
    before the identical from-here-on control-arm loop below runs. Never a
    silent fallback to random init on any failure of that load."""
    base_lr = 0.05
    model = build_model(cfg, seed, device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=base_lr)
    continuation_source_manifest: dict | None = None
    if continue_from:
        o_state, r_state, continuation_source_manifest = load_continuation_checkpoint(
            continue_from, model)
        optimizer.load_state_dict(o_state)
        restore_rng(r_state)
    init_mode = "continuation" if continue_from else "from_scratch"
    # same diversity rationale as phase 1 (see its comment) -- ceiling_steps
    # is the worst case (a run that never early-stops).
    corpus = synthetic_corpus(cfg["vocab"], cfg["seq"],
                              n_windows=max(ceiling_steps * cfg["batch"] * 3, 64),
                              seed=CORPUS_SEED_PHASE2)

    _pace_reset()
    eval_trace: list[dict] = []
    lr_trace: list[float] = []
    resume_proof: dict | None = None
    matched = False
    tokens_to_match: int | None = None
    stop_step: int | None = None

    def do_eval(step_idx: int, tokens_so_far: int) -> float:
        el = eval_loss_fn(model, eval_x, eval_y)
        eval_trace.append({"step": step_idx, "tokens_so_far": tokens_so_far,
                            "eval_loss": el})
        return el

    resume_at_step = checkpoint_every  # deliberate mid-run kill+resume point
    resumed_once = False
    t0 = time.perf_counter()

    step = 0
    el0 = do_eval(0, 0)
    if el0 <= target_eval_loss:
        matched, tokens_to_match, stop_step = True, 0, 0

    while step < ceiling_steps and not matched:
        x, y = batch_from_corpus(corpus, step, cfg["batch"], device)
        lr = cosine_warmup_lr(step, ceiling_steps, base_lr=base_lr)
        for g in optimizer.param_groups:
            g["lr"] = lr
        lr_trace.append(round(lr, 8))
        train_step(model, optimizer, x, y)
        step += 1
        tokens_so_far = step * cfg["batch"] * cfg["seq"]
        _pace_record("pace", 0.0)

        if step == resume_at_step and not resumed_once:
            # --- deliberate checkpoint + kill + resume cycle -----------------
            pre_ckpt_eval = eval_loss_fn(model, eval_x, eval_y)
            rng_snap = capture_rng()
            ckpt_dir = save_checkpoint(
                out_dir, step, model.state_dict(), optimizer.state_dict(),
                rng_snap, extra={"segment_id": "w1-phase2-dryrun-control",
                                  "dry_run": True, "step": step})
            # simulate a genuine process restart: drop the live objects,
            # rebuild fresh ones, load state back in.
            del model, optimizer
            model = build_model(cfg, seed, device)  # architecture only; state overwritten below
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
            m_state, o_state, r_state, manifest = load_checkpoint(ckpt_dir)
            model.load_state_dict(m_state)
            optimizer.load_state_dict(o_state)
            restore_rng(r_state)
            post_resume_eval = eval_loss_fn(model, eval_x, eval_y)
            resume_proof = {
                "checkpoint_dir": ckpt_dir,
                "resume_step": manifest["step"],
                "eval_loss_pre_checkpoint": pre_ckpt_eval,
                "eval_loss_immediately_post_resume": post_resume_eval,
                "bit_exact": pre_ckpt_eval == post_resume_eval,
                "loss_continuity": check_resume_integrity(
                    [pre_ckpt_eval], [post_resume_eval], rtol=1e-6),
                "verdict": ("RESUME_BIT_EXACT" if pre_ckpt_eval == post_resume_eval
                            else "RESUME_STATE_MISMATCH"),
            }
            resumed_once = True

        if step % eval_every == 0 or step == ceiling_steps:
            el = do_eval(step, tokens_so_far)
            if el <= target_eval_loss:
                matched = True
                tokens_to_match = tokens_so_far
                stop_step = step

    wall_s = time.perf_counter() - t0
    tokens_at_ceiling = ceiling_steps * cfg["batch"] * cfg["seq"]

    return {
        "config_sha": config_sha(cfg),
        "init_seed": seed,
        "init_mode": init_mode,
        "continue_from_checkpoint": (repo_relative_path(continue_from)
                                      if continue_from else None),
        "continuation_source_manifest_step": (
            (continuation_source_manifest or {}).get("step")),
        "continuation_source_manifest": continuation_source_manifest,  # added for issue #375
        "lr_schedule": {"source": LR_SCHEDULE_SOURCE, "base_lr": base_lr,
                        "warmup_frac": 0.1, "min_lr_frac": 0.1,
                        "total_steps_for_schedule": ceiling_steps,
                        "lr_trace_first": lr_trace[0] if lr_trace else None,
                        "lr_trace_last": lr_trace[-1] if lr_trace else None},
        "eval_cadence_K": eval_every,
        "ceiling_steps": ceiling_steps,
        "steps_run": step,
        "matched": matched,
        "tokens_to_match": tokens_to_match,
        "tokens_at_ceiling": None if matched else tokens_at_ceiling,
        "stop_step": stop_step,
        "eval_trace": eval_trace,
        "resume_proof": resume_proof,
        "wall_s": round(wall_s, 3),
        "pacing": pacing_snapshot(),
        "governor": {
            "mode": "cpu_dryrun",
            "note": "governor.preflight() not called on the CPU dry-run path "
                    "(no GPU); the real --live/--device cuda path calls it "
                    "before any load and asserts the 0.80 fraction floor",
        },
    }


# ---------------------------------------------------------------------------
# REAL LIVE PATH (issue #82) -- phase 1 loads the real rung-1 terminal
# checkpoint and evaluates it on a real sha-pinned held-out batch drawn from
# the verified 26-shard corpus; phase 2 trains a width-matched from-scratch
# control on real shard tokens. Reachable ONLY through refuse_unless_dry_
# run_safe's two independent interlocks -- never fired by this builder.
# ---------------------------------------------------------------------------

def verify_continuation_source_checkpoint(checkpoint_dir: str, manifest: dict) -> dict:
    """Issue #375: Verify continuation-source checkpoint (the one passed to
    --continue-from) by computing sha256 of both the manifest.json and the
    model.pt file on disk, verifying the model.pt sha matches the manifest's
    recorded sha. Returns a dict with checkpoint_dir, manifest_sha256,
    on_disk_model_pt_sha256, and match=True/False.

    This is a receipted verification block added to the terminal receipt so
    the lineage claim is auditable from the receipt alone (no out-of-band
    hand-verification required).
    """
    manifest_path = os.path.join(checkpoint_dir, "manifest.json")
    model_pt_path = os.path.join(checkpoint_dir, "model.pt")

    # Compute sha256 of manifest.json
    manifest_sha = sha256_file(manifest_path)

    # Compute sha256 of model.pt on disk
    model_pt_sha = sha256_file(model_pt_path)

    # Compare against the model.pt sha from the manifest
    expected_model_pt_sha = manifest.get("files", {}).get("model.pt")
    match = model_pt_sha == expected_model_pt_sha

    return {
        "checkpoint_dir": checkpoint_dir,
        "manifest_sha256": manifest_sha,
        "on_disk_model_pt_sha256": model_pt_sha,
        "match": match,
    }


def verify_real_checkpoint(ckpt_dir: str, rung_receipt: dict) -> dict:
    """Fail-closed real-checkpoint verification (issue #82 point 3, first
    real-input assertion). Two checks, both must hold:

      1. chain of custody -- ckpt_dir must be EXACTLY the terminal checkpoint
         path the rung-1 receipt itself names (stabilization_segment.
         checkpoint); a substituted path is refused, not silently accepted.
      2. integrity -- every file the checkpoint's OWN manifest.json lists is
         re-hashed from on-disk bytes (streaming sha256; no torch.load, no
         tensor materialization -- CPU/disk-only, safe with no CUDA budget)
         and must match exactly.

    Raises SystemExit on any mismatch (fail-closed, never a warning).
    """
    expected_ckpt = rung_receipt["stabilization_segment"]["checkpoint"]
    if os.path.normpath(ckpt_dir) != os.path.normpath(expected_ckpt):
        raise SystemExit(
            "W1_LIVE_CHECKPOINT_PATH_MISMATCH: ckpt_dir "
            f"{ckpt_dir!r} is not the rung-1 receipt's own terminal "
            f"checkpoint {expected_ckpt!r} -- refusing a substituted path.")
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise SystemExit(
            f"W1_LIVE_CHECKPOINT_MANIFEST_MISSING: {manifest_path!r} not found")
    manifest = load_json(manifest_path)
    verified_files: dict[str, str] = {}
    for fname, expected_sha in manifest.get("files", {}).items():
        fpath = os.path.join(ckpt_dir, fname)
        if not os.path.isfile(fpath):
            raise SystemExit(f"W1_LIVE_CHECKPOINT_FILE_MISSING: {fpath!r}")
        actual_sha = sha256_file(fpath)
        if actual_sha != expected_sha:
            raise SystemExit(
                f"W1_LIVE_CHECKPOINT_SHA_MISMATCH: {fname} "
                f"expected={expected_sha} actual={actual_sha}")
        verified_files[fname] = actual_sha
    if not verified_files:
        raise SystemExit(
            f"W1_LIVE_CHECKPOINT_MANIFEST_EMPTY: {manifest_path!r} lists no files")
    return {
        "checkpoint_dir": ckpt_dir,
        "rung_receipt_terminal_checkpoint": expected_ckpt,
        "path_identity_verified": True,
        "files_sha256_verified": verified_files,
        "method": "streaming re-hash of on-disk bytes against the checkpoint's "
                  "own manifest.json (no tensor load; CPU/disk-only)",
    }


def verify_shard_corpus(shard_dir: str,
                         expected_combined_sha256: str | None = None) -> dict:
    """Fail-closed shard-corpus verification (issue #82 point 3, second
    real-input assertion), reusing manifest_sha.compute_manifest -- never
    reimplemented. Raises SystemExit if shard_dir has zero shards, or if
    expected_combined_sha256 is given and the freshly-computed digest
    disagrees (a swapped, stale, or corrupted corpus directory)."""
    import manifest_sha
    if not os.path.isdir(shard_dir):
        raise SystemExit(f"W1_LIVE_SHARD_DIR_MISSING: {shard_dir!r} is not a directory")
    try:
        manifest = manifest_sha.compute_manifest(shard_dir)
    except FileNotFoundError as e:
        raise SystemExit(f"W1_LIVE_SHARD_MANIFEST_EMPTY: {e}")
    if expected_combined_sha256 and manifest["combined_sha256"] != expected_combined_sha256:
        raise SystemExit(
            "W1_LIVE_SHARD_MANIFEST_MISMATCH: computed combined_sha256="
            f"{manifest['combined_sha256']} != expected={expected_combined_sha256} "
            f"-- shard_dir {shard_dir!r} is not the verified corpus.")
    return manifest


def compute_n_windows_from_manifest(manifest: dict, seq: int, n_mtp: int = 0) -> int:
    """Re-derive PackedShardLoader's n_windows from manifest byte SIZES alone
    -- no token data is loaded (matches receipts/corpus-verification-
    20260704T095213Z.json's 'windowing_rederivation' methodology exactly:
    total_tokens = total_size_bytes // 2, n_windows = (total_tokens -
    block_len)//seq + 1). This lets the held-out window range be chosen
    before PackedShardLoader's RAM-heavy (~14-27GB) full-corpus concatenation
    ever runs."""
    total_tokens = manifest["total_size_bytes"] // 2   # dtype <u2, 2 bytes/token
    block_len = seq + 1 + n_mtp
    if total_tokens < block_len:
        raise SystemExit(
            f"W1_LIVE_CORPUS_TOO_SMALL: total_tokens={total_tokens} < "
            f"block_len={block_len}")
    return (total_tokens - block_len) // seq + 1


def held_out_window_start(n_windows: int, eval_batch_size: int) -> int:
    """Reserve the LAST eval_batch_size windows of the packed stream as the
    held-out capability-point batch. Deterministic, no RNG."""
    start = n_windows - eval_batch_size
    if start <= 0:
        raise SystemExit(
            f"W1_LIVE_HELDOUT_RANGE_EMPTY: n_windows={n_windows} <= "
            f"eval_batch_size={eval_batch_size}")
    return start


def assert_disjoint_from_training(held_out_start: int, ceiling_steps: int,
                                   train_batch: int) -> dict:
    """Fail-closed proof that the held-out window range can never be touched
    by phase-2 from-scratch training. PackedShardLoader.batch(step, B) reads
    window indices [step*B, step*B+B) for step in [0, ceiling_steps);
    training always starts at step=0 (spec sec.2: random initialization, a
    fresh from-scratch run), so the highest window index training can EVER
    reach is ceiling_steps*train_batch - 1. held_out_start must exceed that."""
    max_training_window_index = ceiling_steps * train_batch - 1
    disjoint = held_out_start > max_training_window_index
    result = {
        "held_out_window_start": held_out_start,
        "max_training_window_index_at_ceiling": max_training_window_index,
        "arithmetic": (f"{held_out_start} > {ceiling_steps}*{train_batch}-1"
                       f"={max_training_window_index}"),
        "disjoint": disjoint,
    }
    if not disjoint:
        raise SystemExit(
            "W1_LIVE_HELDOUT_NOT_DISJOINT: held-out window range overlaps "
            f"training's reachable window range -- {result}")
    return result


# ---------------------------------------------------------------------------
# Receipt path sanitization (issue #357 cure).
#
# First occurrence (PR #356 landing): the terminal-receipt writer embedded
# the raw --shard-dir absolute path, and that path contained a founder-name
# fragment -- repo-guard (tools/repo-guard.sh sections 2/2b/3: absolute-path
# scan, local-path-fragment scan, operator-name scan) correctly blocked the
# landing; the lane had to hand-sanitize 6 receipt files post-generation.
# Two shapes, matching the cure's own two categories:
#   repo_relative_path()          -- for paths THIS repo owns (checkpoints
#                                     under --out-dir, etc.): a plain relpath
#                                     is safe because the divergent path
#                                     component is internal directory
#                                     structure, never an operator name.
#   corpus_identity_for_receipt() -- for the EXTERNAL shard corpus
#                                     specifically: relpath is NOT safe here
#                                     (the divergent component IS the
#                                     founder-named directory itself), so
#                                     this substitutes a name-safe logical
#                                     corpus_id -- the corpus dir's own
#                                     basename ('shards-v0' is already the
#                                     established repo-wide name for this
#                                     corpus: docs/density-ab-spec-v1.md,
#                                     scripts/token_shards_v0.py) -- plus the
#                                     manifest's own combined_sha256, which
#                                     pins CONTENT strictly more precisely
#                                     than a path string ever did (a path
#                                     names a location; a sha names bytes).
# ---------------------------------------------------------------------------

def repo_relative_path(path: str) -> str:
    """Best-effort relpath to REPO, forward-slash normalized. FAILS CLOSED
    on a cross-drive path: os.path.relpath raises ValueError on Windows when
    `path` and REPO sit on different drive letters -- this is the exact
    defect a B:-drive launch-lane run caught (issue #361 fix-forward): REPO
    lives on B:, tempfile.TemporaryDirectory() defaults to C:, so every
    checkpoint path built in a temp dir hit this branch and (before this
    fix) returned the raw C:\\... path verbatim into a generated receipt.
    Never returns the raw input on failure -- returns a name-safe
    'external:<basename>' marker instead, same convention as
    corpus_identity_for_receipt (basename only, never more): this is the
    same #357 class of leak, just triggered by a drive boundary instead of
    an external corpus mount."""
    try:
        rel = os.path.relpath(os.path.abspath(path), REPO)
    except ValueError:
        return f"external:{os.path.basename(os.path.normpath(path))}"
    return rel.replace(os.sep, "/")


def corpus_identity_for_receipt(shard_dir: str, manifest: dict) -> dict:
    """issue #357 cure. Returns {"corpus_id", "corpus_manifest_sha256"} --
    NEVER the raw shard_dir string. corpus_id is the directory's own
    basename (e.g. 'shards-v0'), never a path, so it stays name-safe
    regardless of what absolute, possibly founder-named prefix the real
    corpus happens to live under."""
    corpus_id = os.path.basename(os.path.normpath(shard_dir)) or "external-corpus"
    return {"corpus_id": corpus_id,
            "corpus_manifest_sha256": manifest["combined_sha256"]}


def build_shard_corpus_verification_block(shard_dir: str, shard_manifest: dict,
                                           expected_combined_sha256: str | None,
                                           verified: bool) -> dict:
    """Pure, CUDA-free construction of the receipt's shard_corpus_verification
    block -- factored out of main_live so the path-sanitization fix (never
    embed the raw shard_dir string) is unit-testable without a live GPU
    launch. Field shape is otherwise unchanged from before this fix (n_files/
    total_tokens/combined_sha256/expected_combined_sha256/verified) -- only
    the corpus-reference field swaps from shard_dir (raw path) to corpus_id +
    corpus_manifest_sha256 (name-safe identifier + content pin)."""
    block = corpus_identity_for_receipt(shard_dir, shard_manifest)
    block.update({
        "n_files": shard_manifest["n_files"],
        "total_tokens": shard_manifest["total_tokens"],
        "combined_sha256": shard_manifest["combined_sha256"],
        "expected_combined_sha256": expected_combined_sha256,
        "verified": verified,
    })
    return block


def _hash_chunk_for_hits(arr_u16, n_keep: int, window: int, roll_base: int,
                          needle_arr) -> "list[int]":
    """Single-attempt (no retry) rolling-hash + isin() over one in-memory
    span. Module-level (not a closure) so it is independently monkeypatchable
    by tests simulating a MemoryError. Raises MemoryError /
    np._core._exceptions._ArrayMemoryError on allocation failure -- callers
    (_hash_chunk_with_retry) catch and adaptively halve; this function never
    catches anything itself."""
    import numpy as np

    n = arr_u16.shape[0]
    if n < window or n_keep <= 0:
        return []
    arr64 = arr_u16.astype(np.uint64)
    n_out = n - window + 1
    h = np.zeros(n_out, dtype=np.uint64)
    power = np.uint64(1)
    rb = np.uint64(roll_base)
    # uint64 wraparound IS the mod-2**64 reduction (same convention as
    # scratch/corpus-wire/contamination_check.py) -- expected, not an error.
    with np.errstate(over="ignore"):
        for k in range(window):
            h += arr64[k:k + n_out] * power
            power = power * rb
    keep = min(n_keep, n_out)
    if needle_arr.size == 0 or keep <= 0:
        return []
    return [int(i) for i in np.where(np.isin(h[:keep], needle_arr))[0]]


def _hash_chunk_with_retry(arr_u16, n_keep: int, window: int, roll_base: int,
                            needle_arr, chunk_tokens: int,
                            min_chunk_tokens: int = MIN_SCAN_SUBCHUNK_TOKENS) -> "list[int]":
    """Issue #445: folds build_decontam_batch_mp.py's adaptive chunk-halving
    guard directly into the serial scan (same halving logic + min-chunk-floor
    semantics as that module's _hash_and_hit_offsets) so no unguarded entry
    point to contamination_recheck exists. Tries _hash_chunk_for_hits at
    `chunk_tokens`; on MemoryError/ArrayMemoryError, halves chunk_tokens and
    re-processes in overlap-safe sub-chunks (window-1 overlap so each
    sub-chunk still hashes its own last few positions correctly), bottoming
    out at min_chunk_tokens with a NAMED MemoryError instead of letting
    numpy's bare internal trace propagate. Returns hit offsets LOCAL to
    arr_u16 (relative to its own start)."""
    import numpy as np

    n = arr_u16.shape[0]
    try:
        return _hash_chunk_for_hits(arr_u16, n_keep, window, roll_base, needle_arr)
    except (MemoryError, np._core._exceptions._ArrayMemoryError) as exc:
        if chunk_tokens <= min_chunk_tokens or n <= min_chunk_tokens:
            raise MemoryError(
                f"W1_LIVE_CONTAMINATION_SCAN_OOM: exhausted memory hashing a "
                f"{n}-token span even at the {min_chunk_tokens}-token retry "
                f"floor (window={window})."
            ) from exc
        half = max(chunk_tokens // 2, min_chunk_tokens)
        hits: list[int] = []
        pos = 0
        n_keep_local = min(n_keep, n)
        while pos < n_keep_local:
            sub_end_keep = min(pos + half, n_keep_local)
            # extend by (window-1) overlap tokens so this sub-chunk can still
            # hash its own last few positions correctly
            sub_data_end = min(sub_end_keep + (window - 1), n)
            sub_data = arr_u16[pos:sub_data_end]
            sub_keep = sub_end_keep - pos
            sub_hits = _hash_chunk_with_retry(sub_data, sub_keep, window, roll_base,
                                               needle_arr, half, min_chunk_tokens)
            hits.extend(pos + hh for hh in sub_hits)
            pos = sub_end_keep
        return hits


def _scan_shard_for_hits(arr_u16, window: int, roll_base: int, needle_arr,
                          chunk_tokens: int,
                          min_chunk_tokens: int = MIN_SCAN_SUBCHUNK_TOKENS) -> "tuple[int, list[int]]":
    """Chunks arr_u16 into <=chunk_tokens spans (with window-1 overlap for
    boundary safety between chunks), hash+hit-tests each chunk via
    _hash_chunk_with_retry and discards it before moving to the next --
    bounds peak allocation to chunk_tokens instead of the whole span (issue
    #445: this is what keeps the per-shard scan from ever materializing a
    268M-element/~2GiB uint64 buffer in one shot). Per-chunk isin() checks
    are elementwise-equivalent to one pass over the concatenated array
    (verified unchanged against the chunked-path equivalence receipts: 16,472
    exact reproduction, PR #443's regression). Returns (n_out_total,
    absolute_hit_offsets) -- same shape contamination_recheck's caller loop
    already expects from the pre-#445 unchunked path."""
    n = arr_u16.shape[0]
    if n < window:
        return 0, []
    n_chunks = (n + chunk_tokens - 1) // chunk_tokens
    total = 0
    hits: list[int] = []
    for chunk_i in range(n_chunks):
        chunk_start = chunk_i * chunk_tokens
        next_start = (chunk_i + 1) * chunk_tokens
        is_last = next_start >= n
        chunk_end = n if is_last else min(next_start + (window - 1), n)
        chunk_data = arr_u16[chunk_start:chunk_end]
        chunk_len = chunk_data.shape[0]
        if chunk_len >= window:
            n_out = chunk_len - window + 1
            n_keep = n_out if is_last else min(chunk_tokens, n_out)
            total += n_keep
            local_hits = _hash_chunk_with_retry(chunk_data, n_keep, window, roll_base,
                                                 needle_arr, chunk_tokens, min_chunk_tokens)
            hits.extend(chunk_start + h for h in local_hits)
    return total, hits


def contamination_recheck(eval_rows: "list[list[int]]", shard_dir: str, *,
                           window: int = CONTAMINATION_WINDOW_TOKENS,
                           roll_base: int = CONTAMINATION_ROLL_BASE,
                           scan_chunk_tokens: int = DEFAULT_SCAN_CHUNK_TOKENS,
                           min_scan_subchunk_tokens: int = MIN_SCAN_SUBCHUNK_TOKENS) -> dict:
    """Exhaustive exact-match contamination check of the REAL eval batch
    against the shard corpus -- the 'contamination re-check hook' issue #82
    point 1 requires, per receipts/corpus-verification-20260704T095213Z.json's
    own OPEN ITEM ('re-run this script once issue #53 lands a real
    capability_point receipt'). Same method as scratch/corpus-wire/
    contamination_check.py (13-token polynomial rolling hash, uint64 mod
    2**64, hash hits re-verified by exact elementwise comparison,
    shard-to-shard boundary windows checked too) -- reimplemented here as a
    reusable function (that script is a scratch one-off hardcoded to the
    dry-run batch) rather than imported. CPU-only, one shard resident in RAM
    at a time -- eval_rows is small (batch rows of length seq+1), never the
    corpus itself.

    Issue #445: the per-shard scan is chunked (scan_chunk_tokens) with an
    adaptive MemoryError/ArrayMemoryError halving guard down to a
    min_scan_subchunk_tokens floor (see _hash_chunk_with_retry /
    _scan_shard_for_hits) -- folded in here, not layered on top, so this
    function is the ONLY entry point and every caller inherits the guard
    with zero signature changes (new params are keyword-only with
    production-safe defaults matching w2_heldout/build_decontam_batch_mp.py's
    DEFAULT_SCAN_CHUNK_TOKENS / MIN_SCAN_SUBCHUNK_TOKENS)."""
    import numpy as np

    mod = 1 << 64

    def _needle_hash(ids) -> int:
        h = 0
        b = 1
        for v in ids:
            h = (h + int(v) * b) % mod
            b = (b * roll_base) % mod
        return h

    def _sliding_windows(ids, w):
        n = len(ids)
        return [tuple(int(x) for x in ids[i:i + w]) for i in range(n - w + 1)] if n >= w else []

    needle_windows = []
    for row in eval_rows:
        needle_windows.extend(_sliding_windows(list(row), window))
    needle_hash_to_windows: dict[int, list[tuple]] = {}
    for w in needle_windows:
        needle_hash_to_windows.setdefault(_needle_hash(w), []).append(w)
    needle_hash_set = set(needle_hash_to_windows.keys())

    shard_paths = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    if not shard_paths:
        raise SystemExit(f"W1_LIVE_CONTAMINATION_NO_SHARDS: {shard_dir!r}")

    confirmed_matches: list[dict] = []
    candidate_collisions = 0
    total_windows_hashed = 0
    prev_tail = None
    prev_name = None
    needle_arr = (np.fromiter(needle_hash_set, dtype=np.uint64, count=len(needle_hash_set))
                  if needle_hash_set else np.array([], dtype=np.uint64))

    for name in shard_paths:
        # 2026-07-08 (issue #118 P1 sweep, coordinator ruling -- third site,
        # same class as the corpus loader and build_decontam_batch_mp.py's
        # scan worker): np.fromfile read the WHOLE shard (up to 512MiB) into
        # one contiguous RAM block before #451's chunked hashing even started
        # -- #451 chunked the HASH computation but not this read, and this
        # exact call crashed with a real 512MiB ArrayMemoryError at 28.7GB
        # free RAM (fragmentation, not capacity -- same signature as the
        # 13GB corpus-loader failures). np.memmap(mode='r') defers paging to
        # _scan_shard_for_hits's own chunk slicing below, so peak materialized
        # RAM per shard is bounded by scan_chunk_tokens (~64MB), not shard
        # size -- composes correctly with #451's chunking because every
        # consumer here (._astype(), tuple(...) candidate extraction, the
        # tiny window-1 boundary join) only ever reads, never mutates, arr.
        arr = np.memmap(os.path.join(shard_dir, name), dtype="<u2", mode="r")
        n = arr.shape[0]

        n_out, hit_offsets = _scan_shard_for_hits(arr, window, roll_base, needle_arr,
                                                   scan_chunk_tokens, min_scan_subchunk_tokens)
        total_windows_hashed += n_out
        for i in hit_offsets:
            candidate = tuple(int(x) for x in arr[i:i + window])
            hh = _needle_hash(candidate)
            if hh in needle_hash_to_windows and candidate in needle_hash_to_windows[hh]:
                confirmed_matches.append({"shard": name, "offset": i,
                                           "window": list(candidate)})
            else:
                candidate_collisions += 1

        if prev_tail is not None and n >= (window - 1) and needle_hash_set:
            join = np.concatenate([prev_tail, arr[:window - 1]])
            join_n, join_hit_offsets = _scan_shard_for_hits(join, window, roll_base, needle_arr,
                                                             scan_chunk_tokens, min_scan_subchunk_tokens)
            total_windows_hashed += join_n
            for i in join_hit_offsets:
                candidate = tuple(int(x) for x in join[i:i + window])
                hh = _needle_hash(candidate)
                if hh in needle_hash_to_windows and candidate in needle_hash_to_windows[hh]:
                    confirmed_matches.append({
                        "boundary": f"{prev_name}|{name}",
                        "offset_in_join": i, "window": list(candidate)})

        prev_tail = arr[-(window - 1):].copy() if n >= (window - 1) else prev_tail
        prev_name = name

    return {
        "method": "13-token polynomial rolling hash (uint64 mod 2**64), hash "
                  "hits re-verified by exact elementwise comparison, "
                  "shard-to-shard boundary windows checked -- same convention "
                  "as scratch/corpus-wire/contamination_check.py",
        "corpus_verification_open_item_ref": CORPUS_VERIFICATION_RECEIPT,
        "shards_scanned": len(shard_paths),
        "windows_hashed": total_windows_hashed,
        "confirmed_matches": confirmed_matches,
        "hash_collisions_ruled_out": candidate_collisions,
        "verdict": "CLEAN" if not confirmed_matches else "CONTAMINATED",
    }


# ---------------------------------------------------------------------------
# Issue #121 spec-compliance additions (Defect A + Defect B). W2 sec.4:
# "contamination_recheck must report 0 matches or the launch gate refuses" --
# contamination_recheck() above computed and disclosed the verdict but never
# gated on it. Two independent fixes, both fail-closed, neither touching the
# frozen protocol's default behavior when unused:
# ---------------------------------------------------------------------------

def write_refusal_receipt(contamination: dict, contamination_classified: dict,
                          candidate_window_indices: "list[int]",
                          *, args: argparse.Namespace, out_dir: str, ts: str,
                          real_arch: dict, disjoint_check: dict,
                          eval_batch_sha: "str|None" = None) -> str:
    """Write a contamination refusal receipt to scratch/w1-control/receipts/,
    carrying match counts, derivation mode, first N matches, batch sha, and
    resolved args. Returns the receipt path for logging."""
    # Derivation mode: decontam-receipt vs contiguous-default
    derivation_mode = ("decontam-receipt-indices"
                       if args.decontam_receipt else "contiguous-default")

    # First N=20 matches with shard+offset
    confirmed_matches = contamination.get("confirmed_matches", [])
    first_n_matches = confirmed_matches[:20]

    # Build the refusal receipt
    refusal_receipt = {
        "ticket": "W1-CONTAMINATION-REFUSED",
        "ts": ts,
        "issue": "#371",
        "schema": "w1-contamination-refusal/v1",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "derivation_mode": derivation_mode,
        "held_out_candidate_window_indices": candidate_window_indices,
        "contamination_verdict": contamination.get("verdict"),
        "match_counts": {
            "raw_confirmed_matches": len(confirmed_matches),
            "self_matches_excluded": contamination_classified.get("self_matches_excluded", 0),
            "confirmed_non_self_matches": len(
                contamination_classified.get("confirmed_non_self_matches", [])),
        },
        "direction_structure": {
            "self_exclusion_description": (
                "The held-out batch was drawn from the real corpus at "
                "candidate_window_indices; matches at these exact locations are "
                "unavoidable self-matches (the batch matching itself at its own "
                "true source), not evidence of foreign contamination."),
            "what_self_exclusion_excluded": (
                f"contamination_classified['self_matches_excluded']="
                f"{contamination_classified.get('self_matches_excluded', 0)} "
                f"of {len(confirmed_matches)} raw confirmed_matches"),
            "why_remainder_is_non_self": (
                "confirmed_non_self_matches are computed by checking each raw "
                "match's global position ([shard, offset] → global_start) against "
                "each candidate_window's known [global_start, global_end) range; "
                "overlap = self-match, no overlap = genuine foreign duplicate"),
        },
        "first_n_matches": first_n_matches,
        "n_matches_shown": len(first_n_matches),
        "total_matches_available": len(confirmed_matches),
        "batch_identity": {
            "batch_sha256": eval_batch_sha,
            "candidate_windows_count": len(candidate_window_indices),
        },
        "architecture_config": {
            "seq": real_arch.get("seq"),
            "n_mtp": real_arch.get("n_mtp"),
            "batch": real_arch.get("batch"),
        },
        "disjoint_check": disjoint_check,
        "resolved_args": {
            "decontam_receipt": args.decontam_receipt,
            "shard_dir": repo_relative_path(args.shard_dir) if args.shard_dir else None,
            "live_ceiling_steps": args.live_ceiling_steps,
            "live_eval_every": args.live_eval_every,
            "live_checkpoint_every": args.live_checkpoint_every,
        },
    }

    # Write to scratch/w1-control/receipts/ (never canonical tree)
    receipts_dir = os.path.join(REPO, "scratch", "w1-control", "receipts")
    os.makedirs(receipts_dir, exist_ok=True)
    out_path = os.path.join(receipts_dir,
                             f"w1-contamination-refused-{ts}.json")
    checked_write(out_path, refusal_receipt)

    # BOM-free plain-utf8 verification
    with open(out_path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "W1_RECEIPT_HAS_BOM"
    with open(out_path, "r", encoding="utf-8") as f:
        json.load(f)

    return out_path


def refuse_if_contaminated(contamination: dict) -> None:
    """Defect A: hard-refuse the live launch when THIS run's own fresh
    contamination_recheck() (scanned against the real shard corpus at launch
    time, not a cached receipt) finds any confirmed match. Unconditional --
    applies whether or not --decontam-receipt is given, since this is a live
    re-verification of the actual eval batch about to be trained against, not
    a trust of a prior receipt's claim.

    SUPERSEDED as main_live's actual gate by refuse_if_non_self_contaminated
    below (2026-07-07 real-launch refusal, fork-A fix) -- this raw-verdict
    gate is kept, and still tested, because it is technically correct for
    what it claims to do (refuse on ANY confirmed match); the bug was calling
    it directly on a held-out batch's OWN true source windows, which will
    ALWAYS match themselves and are not contamination. See
    classify_contamination_self_matches's docstring for the root-cause
    analysis and receipt reference."""
    verdict = contamination.get("verdict")
    if verdict != "CLEAN":
        raise SystemExit(
            "W1_LIVE_CONTAMINATION_REFUSED: contamination_recheck.verdict="
            f"{verdict!r} (confirmed_matches="
            f"{len(contamination.get('confirmed_matches', []))}) -- W2 sec.4 "
            "requires the held-out batch to be contamination-clean before "
            f"training; refusing launch. {json.dumps(contamination)}")


def classify_contamination_self_matches(
        contamination: dict, candidate_window_indices: "list[int]", *,
        seq: int, n_mtp: int, shard_dir: str,
        window: int = CONTAMINATION_WINDOW_TOKENS) -> dict:
    """2026-07-07 real-launch refusal, fork-A fix (issue #121 followup): the
    W1 real launch refused with confirmed_matches=16208 -- EXACTLY 16 selected
    windows x 1013 sliding 13-token sub-windows/row (1025-13+1), i.e. every
    single 'confirmed match' was the held-out batch matching ITSELF at its
    own true source location (v0-00016.bin, sequential offsets from 1024) --
    zero evidence of a genuine foreign duplicate. refuse_if_contaminated
    gates on contamination_recheck()'s raw verdict, which has no way to tell
    a self-match (unavoidable -- the batch WAS drawn from the real corpus)
    from a genuine foreign duplicate. scripts/w2_heldout/build_decontam_
    batch_mp.py's _classify_once already solves exactly this for RECEIPT
    GENERATION (is_self via global-position overlap against each candidate's
    own known [global_start, global_start+block_len) range,
    self_matches_excluded / confirmed_non_self_matches fields) -- this is the
    same class of check, applied at LAUNCH time, using window indices the
    launcher already knows it asked for (never re-derived from the match
    data itself).

    candidate_window_indices: the exact PackedShardLoader window indices the
    held-out batch's rows were built from (decontam_receipt['selected_
    window_indices'] on the --decontam-receipt path; [held_out_start+j, ...]
    on the default path)."""
    block_len = seq + 1 + n_mtp
    candidate_ranges = [(idx * seq, idx * seq + block_len)
                        for idx in candidate_window_indices]

    shard_names = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    cum = [0]
    for name in shard_names:
        n_tokens = os.path.getsize(os.path.join(shard_dir, name)) // 2  # <u2
        cum.append(cum[-1] + n_tokens)
    name_to_cum_start = {name: cum[i] for i, name in enumerate(shard_names)}

    def _match_global_start(m: dict):
        if "shard" in m:
            base = name_to_cum_start.get(m["shard"])
            return None if base is None else base + m["offset"]
        if "boundary" in m:
            _, right_name = m["boundary"].split("|", 1)
            right_base = name_to_cum_start.get(right_name)
            if right_base is None:
                return None
            # The join array is [prev_tail(last window-1 tokens of the LEFT
            # shard), first window-1 tokens of the RIGHT shard] (see
            # contamination_recheck's boundary branch) -- position 0 of the
            # join is (window-1) tokens before the right shard's global start.
            return right_base - (window - 1) + m["offset_in_join"]
        return None

    non_self_matches = []
    self_matches_excluded = 0
    for m in contamination.get("confirmed_matches", []):
        gstart = _match_global_start(m)
        is_self = False
        if gstart is not None:
            gend = gstart + window
            is_self = any(gstart >= c_start and gend <= c_end
                          for c_start, c_end in candidate_ranges)
        if is_self:
            self_matches_excluded += 1
        else:
            non_self_matches.append(m)

    return {
        "verdict": "CLEAN" if not non_self_matches else "CONTAMINATED",
        "confirmed_non_self_matches": non_self_matches,
        "self_matches_excluded": self_matches_excluded,
        "raw_confirmed_matches": len(contamination.get("confirmed_matches", [])),
    }


def refuse_if_non_self_contaminated(classified: dict, *,
                                     contamination: dict,
                                     candidate_window_indices: "list[int]",
                                     args: argparse.Namespace, out_dir: str, ts: str,
                                     real_arch: dict, disjoint_check: dict,
                                     eval_batch_sha: "str|None" = None) -> None:
    """Defect A v2 (2026-07-07 fork-A fix): gates on classify_contamination_
    self_matches's non-self verdict, not the raw contamination_recheck()
    verdict -- see that function's docstring for why the raw gate false-
    positives on a held-out batch's own true source windows. Issue #371:
    writes refusal receipt before refusing."""
    if classified["verdict"] != "CLEAN":
        receipt_path = write_refusal_receipt(
            contamination, classified, candidate_window_indices,
            args=args, out_dir=out_dir, ts=ts, real_arch=real_arch,
            disjoint_check=disjoint_check, eval_batch_sha=eval_batch_sha)
        raise SystemExit(
            "W1_LIVE_CONTAMINATION_REFUSED: confirmed_non_self_matches="
            f"{len(classified['confirmed_non_self_matches'])} "
            f"(self_matches_excluded={classified['self_matches_excluded']} of "
            f"{classified['raw_confirmed_matches']} raw matches) -- W2 sec.4 "
            "requires the held-out batch to be contamination-clean, EXCLUDING "
            "its own true source windows, before training; refusing launch. "
            f"Refusal receipt: {receipt_path}")


def rebuild_batch_from_decontam_receipt(loader, receipt: dict, device: str
                                         ) -> tuple["torch.Tensor", "torch.Tensor", str]:
    """Defect B: rebuild the held-out batch from an EXTERNAL decontamination
    receipt's own `selected_window_indices` (schema w2-heldout-decontam/v1)
    instead of this script's internal 'last batch-many windows' convention --
    the receipt's curated pool may sit anywhere in the corpus (replacement
    rounds swap out any window that scanned CONTAMINATED), so the two
    conventions are not interchangeable. Asserts the rebuilt batch's sha256
    (SAME convention as sha256_tokens/batch_sha256: concat([x, y], dim=1) of
    the raw window, sha256 over the int64 bytes) matches the receipt's own
    pinned batch_sha256 -- fail-closed on any mismatch (tampered/stale
    receipt, wrong --shard-dir, or a receipt built for a different seq)."""
    indices = receipt.get("selected_window_indices")
    if not isinstance(indices, list) or not indices:
        raise SystemExit(
            "W1_LIVE_DECONTAM_RECEIPT_NO_WINDOWS: receipt missing/empty "
            "selected_window_indices -- refusing launch.")
    xs, ys = [], []
    for idx in indices:
        x_np, y_np, _y_mtp = loader.window_np(int(idx))
        xs.append(x_np)
        ys.append(y_np)
    eval_x = torch.as_tensor(np.stack(xs), dtype=torch.long, device=device)
    eval_y = torch.as_tensor(np.stack(ys), dtype=torch.long, device=device)
    eval_sha = sha256_tokens(torch.cat([eval_x, eval_y], dim=1))
    expected_sha = receipt.get("batch_sha256")
    if eval_sha != expected_sha:
        raise SystemExit(
            f"W1_LIVE_DECONTAM_BATCH_SHA_MISMATCH: rebuilt batch sha256={eval_sha} "
            f"!= receipt-pinned batch_sha256={expected_sha!r} -- refusing launch "
            "(tampered/stale receipt, wrong --shard-dir, or seq/n_mtp mismatch).")
    return eval_x, eval_y, eval_sha


def wire_launch_gate_check(xs: list, ys: list, *, seq: int, receipt_path: str,
                            out_dir: str, ts: str) -> dict:
    """Literal integration of scripts/w2_heldout/launch_gate.py's
    assert_launch_allowed -- an independent, separately-coded re-verification
    of the SAME two facts rebuild_batch_from_decontam_receipt just checked
    (receipt pass/contamination_recheck fields + batch sha256), via a
    completely separate hashing code path (launch_gate._batch_sha256_from_file
    vs this file's sha256_tokens) so a bug in either implementation alone
    cannot silently pass a launch. Writes the rebuilt raw windows to a
    temp .npy in the exact layout launch_gate expects ([batch, seq+1] raw
    token ids, not pre-split x/y) -- same convention build_decontam_batch.py
    uses for its own batch_sha256, confirmed by reading both functions."""
    HERE_DIR = os.path.dirname(os.path.abspath(__file__))
    if HERE_DIR not in sys.path:
        sys.path.insert(0, HERE_DIR)
    from w2_heldout.launch_gate import assert_launch_allowed

    raw_windows = np.stack([
        np.concatenate([np.asarray(x_np, dtype=np.int64),
                         [int(y_np[-1])]])
        for x_np, y_np in zip(xs, ys)
    ])
    tmp_npy = os.path.join(out_dir, f"w1-live-decontam-rebuilt-batch-{ts}.npy")
    np.save(tmp_npy, raw_windows)
    result = assert_launch_allowed(batch_path=tmp_npy, receipt_path=receipt_path)
    return {"allowed": result.allowed, "reason": result.reason,
            "receipt_path": result.receipt_path, "batch_path": tmp_npy}


class RealW1Model(torch.nn.Module):
    """Real rung-1-shaped model for the W1 live path. Mirrors timeshare_
    pretrain._V0Real's key naming (backbone_model / head / mtp_heads, tied
    embeddings) EXACTLY so load_state_dict(strict=True) matches the real
    rung-1 checkpoint byte-for-byte. NOT imported from timeshare_pretrain
    because _V0Real is a closure-local class inside build_v0_model with
    intermediate_size HARDCODED to 4096 (the un-grown seed FF width) --
    this checkpoint is rung-1 TERMINAL (post-grow, ff=16384), which
    build_v0_model has no parameter for. Same transformers.LlamaModel
    backbone class/convention as build_v0_model's live path -- new only in
    the FF-width parameter build_v0_model lacks.

    mtp_heads (issue #82 reopened defect, cure): _V0Real.__init__
    (timeshare_pretrain.py) constructs mtp_heads UNCONDITIONALLY at
    cfg["objective"]["mtp_aux_heads"]["n_heads"] count -- run_v0_segment's
    mtp_enabled flag only gates whether they receive a loss term during
    training, never whether they exist in the model / state_dict. The rung-1
    terminal checkpoint therefore always carries mtp_heads.<k>.weight keys,
    and load_state_dict(strict=True) rejects a class that omits them (the
    live-fire failure this class previously caused). Cured by constructing
    the identical ModuleList (same per-head shape: Linear(hidden, vocab,
    bias=False), same count, sourced from the same contract file production
    reads -- see derive_real_arch_config's n_mtp/n_mtp_source).

    forward()/eval loss deliberately does NOT route through mtp_heads --
    verified by reading run_v0_segment's training loop (timeshare_pretrain.py
    ~L1316-1326), not guessed: mtp_heads consume the SAME shared backbone
    hidden_out as a separate, parallel prediction target (further-future
    tokens, y_mtp[k]) via their OWN independent CE term
    (mtp_total_loss(primary_ce, mtp_ces, mtp_weight)); they do not feed into
    or affect model.head's own computation, which depends only on
    backbone(ids) and its own weight. This is the standard multi-token-
    prediction architecture (an auxiliary training-time densifying signal,
    dropped at inference) -- so the W1 capability metric (primary next-token
    eval loss, spec sec.3) is architecturally unaffected by whether mtp_heads
    are invoked in forward(), and matches the pre-existing, already-approved
    TinyW1Model dry-run convention (primary CE only, spec sec.3 never
    mentions MTP). mtp_heads exist here ONLY so the checkpoint loads; they
    are present in model.parameters() (so an optimizer built over this class
    would list them) but receive no gradient because forward() never calls
    them -- the same structural shape as a legitimate CE-only fallback
    segment (RECEIPTED elsewhere in the repo as a real production mode), not
    a new deviation this class introduces."""

    def __init__(self, real_arch: dict):
        super().__init__()
        from transformers import LlamaConfig, LlamaModel
        conf = LlamaConfig(
            vocab_size=real_arch["vocab"], hidden_size=real_arch["hidden"],
            intermediate_size=real_arch["ff_grown"],
            num_hidden_layers=real_arch["layers_assumed"],
            num_attention_heads=real_arch["heads_assumed"],
            num_key_value_heads=real_arch["heads_assumed"],
            max_position_embeddings=real_arch["seq"],
            tie_word_embeddings=False)
        self.backbone_model = LlamaModel(conf)
        self.head = torch.nn.Linear(real_arch["hidden"], real_arch["vocab"], bias=False)
        self.head.weight = self.backbone_model.embed_tokens.weight  # tied, per rung receipt's tied_pairs_detected
        self.mtp_heads = torch.nn.ModuleList(
            [torch.nn.Linear(real_arch["hidden"], real_arch["vocab"], bias=False)
             for _ in range(real_arch["n_mtp"])])

    def backbone(self, ids: "torch.Tensor") -> "torch.Tensor":
        return self.backbone_model(input_ids=ids).last_hidden_state

    def forward(self, ids: "torch.Tensor") -> "torch.Tensor":
        return self.head(self.backbone(ids))


def real_config_dict(real_arch: dict) -> dict:
    return {"vocab": real_arch["vocab"], "hidden": real_arch["hidden"],
            "layers": real_arch["layers_assumed"], "heads": real_arch["heads_assumed"],
            "ff": real_arch["ff_grown"], "seq": real_arch["seq"],
            "batch": real_arch["batch"], "tied_embeddings": True, "head_bias": False,
            "n_mtp": real_arch["n_mtp"]}


def build_real_model(real_arch: dict, device: str, seed: int | None = None):
    """Builds RealW1Model and casts it EXACTLY the way every real-
    architecture model construction path in timeshare_pretrain.py (both
    trees -- build_v0_model's live branch, ember's extended `.to(device).
    to(torch.bfloat16)` CPU-smoke variant, and the older inline run_segment
    live branch, all checked directly) unconditionally does:
    `.to(device).to(torch.bfloat16)` then `.gradient_checkpointing_enable()`
    -- regardless of device, matching that this codebase applies both
    UNCONDITIONALLY, never gated on device=="cuda" (verified: ember's
    build_v0_model calls this same pair with device="cpu" for its own
    real-architecture CPU smoke-test path).

    Root cause (issue #82 live-fire finding 2 -- confirmed by reading, not
    guessed): the prior RealW1Model built plain fp32 with no checkpointing,
    while the checkpoint this class loads (model.pt, checked directly) is
    ENTIRELY torch.bfloat16 and was produced by a run that (per the SAME
    unconditional convention above) also ran under gradient checkpointing --
    this is the confirmed, non-guessed pair of discrepancies behind the
    CUDA OOM at run_phase2_live's first forward pass (17.32GiB allocated vs
    19.19GiB allowed -- see run_phase2_live's docstring for the full
    arithmetic). Applying both here, on every device, restores byte-for-
    byte dtype parity with the checkpoint (no more implicit bf16->fp32
    upcast on load_state_dict) and is directly verified working on CPU
    (forward/backward/optimizer.step all run cleanly in bf16 with
    gradient_checkpointing_enable() active -- checked, not assumed)."""
    if seed is not None:
        torch.manual_seed(seed)
    model = RealW1Model(real_arch)
    model = model.to(device).to(torch.bfloat16)
    model.backbone_model.gradient_checkpointing_enable()
    return model


def assess_real_lineage(*, checkpoint_verified: bool, shard_verified: bool,
                         eval_batch_pinned: bool) -> tuple[bool, list[str]]:
    """issue #82 point 3: is_real_lineage=True ONLY when every real-input
    assertion holds; fail-closed otherwise, with the failing assertions
    NAMED -- never a silent/blanket True (the manufactured-GREEN trap
    issue #82 caught: the prior code stamped 'is_real_lineage: False if
    dry_run else True' unconditionally)."""
    reasons = []
    if not checkpoint_verified:
        reasons.append("checkpoint_sha_did_not_match_rung_receipt")
    if not shard_verified:
        reasons.append("shard_dir_did_not_sha_verify_against_corpus_manifest")
    if not eval_batch_pinned:
        reasons.append("eval_batch_sha256_not_pinned")
    return (len(reasons) == 0, reasons)


def verify_checkpoint_key_shape_parity(model_state: dict,
                                        model: "torch.nn.Module") -> dict:
    """Issue #82 reopened-defect cure, point 2: a CPU-only, seconds-cheap
    key-set + shape parity diff between an already-loaded checkpoint
    state_dict and a model instance's own state_dict() -- catches exactly
    the class of defect that killed the live run (RealW1Model omitted
    mtp_heads, so model.load_state_dict(m_state, strict=True) rejected the
    real checkpoint's mtp_heads.0.weight / mtp_heads.1.weight keys) for free,
    WITHOUT needing a --live --device cuda invocation to find out. This is
    the exact check the issue names: torch.load(model.pt, map_location=
    'cpu').keys() vs RealW1Model().state_dict().keys() -- generalized to any
    already-loaded state_dict/model pair so it is reusable standalone (a
    selftest fixture) or wired into run_phase1_live ahead of the real strict
    load (below), which stays in place, unweakened, as defense-in-depth.

    model_state: a state_dict from load_checkpoint()/torch.load(model.pt) --
    the caller decides how/when the checkpoint touches disk; never re-loaded
    here.
    model: an already-constructed model instance whose .state_dict() is
    compared against model_state."""
    own_state = model.state_dict()
    ckpt_keys = set(model_state.keys())
    own_keys = set(own_state.keys())
    missing_in_model = sorted(ckpt_keys - own_keys)
    unexpected_in_model = sorted(own_keys - ckpt_keys)
    shape_mismatches = {
        k: {"checkpoint": list(model_state[k].shape), "model": list(own_state[k].shape)}
        for k in sorted(ckpt_keys & own_keys)
        if tuple(model_state[k].shape) != tuple(own_state[k].shape)
    }
    if missing_in_model or unexpected_in_model or shape_mismatches:
        raise SystemExit(
            "W1_LIVE_CHECKPOINT_KEY_SHAPE_MISMATCH: the model's state_dict "
            "does not match the checkpoint's -- "
            f"missing_in_model(checkpoint has, model construction lacks)="
            f"{missing_in_model} "
            f"unexpected_in_model(model has, checkpoint lacks)="
            f"{unexpected_in_model} "
            f"shape_mismatches={shape_mismatches}. This is exactly the class "
            "of defect that killed the 2026-07-04 live run at strict=True "
            "load (issue #82 reopened) -- fix the model class's "
            "construction, never the checkpoint.")
    return {"n_keys_checked": len(ckpt_keys), "keys_match": True, "shapes_match": True}


def load_continuation_checkpoint(checkpoint_dir: str, model: "torch.nn.Module"
                                  ) -> tuple[dict, dict, dict]:
    """W1b (#355) continuation-mode checkpoint load -- fail-closed, reusing
    (never reimplementing) load_checkpoint's own sha256 manifest re-verify
    and verify_checkpoint_key_shape_parity's key/shape diff (the SAME parity
    check run_phase1_live already runs before its own strict load, just
    applied here at step 0 instead of before an eval-only forward pass).
    Applies model_state to `model` in place via strict=True load and returns
    (optimizer_state, rng_state, manifest) for the caller to apply the same
    way the pre-existing mid-run resume cycle already does (save_checkpoint
    -> load_checkpoint -> load_state_dict -> optimizer.load_state_dict ->
    restore_rng) -- this is that exact cycle, run once at t=0, NO from-
    scratch init anywhere on this path (#355's core requirement).

    Refuses fail-closed on:
      - checkpoint_dir missing or unreadable (no manifest.json)
      - a corrupt checkpoint (load_checkpoint's own sha256 re-verify)
      - a shape/key mismatch between the checkpoint and `model`'s own
        architecture (verify_checkpoint_key_shape_parity, reused verbatim --
        this is what catches the true 'mismatched checkpoint' case, e.g. a
        seed checkpoint from a different width/depth than the current cfg)
    Never refuses a healthy, matching checkpoint -- that path returns
    normally with model already loaded in place."""
    manifest_path = os.path.join(checkpoint_dir, "manifest.json")
    if not os.path.isdir(checkpoint_dir) or not os.path.isfile(manifest_path):
        raise SystemExit(
            "W1B_CONTINUE_FROM_CHECKPOINT_MISSING: "
            f"{checkpoint_dir!r} is not a checkpoint directory (no "
            "manifest.json found) -- refusing continuation-mode launch "
            f"({W1B_ISSUE_REF}: NO from-scratch init is ever a silent "
            "fallback in this mode).")
    try:
        m_state, o_state, r_state, manifest = load_checkpoint(checkpoint_dir)
    except (ValueError, FileNotFoundError, EOFError) as e:
        raise SystemExit(
            f"W1B_CONTINUE_FROM_CHECKPOINT_CORRUPT: {checkpoint_dir!r} "
            f"failed to load/verify -- {e}") from e
    verify_checkpoint_key_shape_parity(m_state, model)  # raises on mismatch
    model.load_state_dict(m_state, strict=True)
    return o_state, r_state, manifest


def optimizer_state_shape_parity(resumed_bundle: dict, original_bundle: dict) -> dict:
    """Explicit, named optimizer-state shape-parity check (issue #82
    live-fire finding 2, requirement 6) -- verifies a resumed split-optimizer
    bundle's tensor shapes match the originally-saved bundle key-for-key,
    LAYERED ON TOP of load_optimizers_state's own implicit validation
    (PyTorch's optimizer.load_state_dict already raises internally on a
    structural mismatch -- this makes the check explicit, named, and
    receipted rather than relying solely on that implicit exception path,
    the same defense-in-depth relationship verify_checkpoint_key_shape_
    parity has with the model's own strict=True load)."""
    mismatches: list[str] = []
    for opt_key in original_bundle:
        if opt_key not in resumed_bundle:
            mismatches.append(f"missing optimizer key {opt_key!r} after resume")
            continue
        orig_state = original_bundle[opt_key].get("state", {})
        new_state = resumed_bundle[opt_key].get("state", {})
        if set(orig_state.keys()) != set(new_state.keys()):
            mismatches.append(
                f"{opt_key}: param-index key sets differ "
                f"(original={sorted(orig_state.keys())} "
                f"resumed={sorted(new_state.keys())})")
            continue
        for pidx, orig_pstate in orig_state.items():
            new_pstate = new_state.get(pidx, {})
            for buf_name, orig_t in orig_pstate.items():
                if not isinstance(orig_t, torch.Tensor):
                    continue
                new_t = new_pstate.get(buf_name)
                if new_t is None or tuple(new_t.shape) != tuple(orig_t.shape):
                    mismatches.append(
                        f"{opt_key}[{pidx}].{buf_name}: shape "
                        f"{None if new_t is None else tuple(new_t.shape)} != "
                        f"{tuple(orig_t.shape)}")
    return {"n_optimizer_keys_checked": len(original_bundle),
            "mismatches": mismatches, "shapes_match": len(mismatches) == 0}


def hard_free_and_assert_phase_boundary(
        device: str, *, threshold_bytes: int = 512 * 1024 * 1024) -> dict:
    """Phase-boundary hygiene (issue #82 live-fire finding 2, requirement 2):
    hard-free phase-1's resident and ASSERT allocated CUDA memory is below a
    named threshold before phase-2 builds its own model + optimizers.

    Root-cause note on whether phase-1 leaked into phase-2 (from reading,
    not guessed): run_phase1_live's `model` is a function-local that goes
    out of scope on return; main_live only ever keeps the RETURNED DICT
    (strings/floats/lists, no tensor or model reference) -- so CPython's
    deterministic refcounting should already free phase-1's model with no
    reference cycle involved (none was found reading run_phase1_live/
    main_live). The observed 17.32GiB allocated at the phase-2 crash is
    fully and independently explained by phase-2's OWN single-model
    forward-pass activation accumulation without gradient checkpointing
    (see run_phase2_live's docstring for the arithmetic) -- so this is NOT
    confirmed to be a phase-1 leak. This assert is kept as a permanent,
    cheap hygiene boundary regardless: it converts "probably fine" into a
    receipted, fail-closed guarantee, and would catch a REAL leak
    introduced by some future change immediately rather than at the next
    OOM."""
    import gc
    gc.collect()
    if device != "cuda":
        return {"mode": "cpu_no_op",
                "note": "device != 'cuda' -- nothing to free/assert "
                        "(tiny-fixture selftest path; production live path "
                        "always passes device='cuda')"}
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    allocated = torch.cuda.memory_allocated()
    reserved = torch.cuda.memory_reserved()
    result = {
        "mode": "cuda",
        "allocated_bytes": allocated,
        "allocated_gib": round(allocated / (1024 ** 3), 3),
        "reserved_bytes": reserved,
        "reserved_gib": round(reserved / (1024 ** 3), 3),
        "threshold_bytes": threshold_bytes,
        "threshold_gib": round(threshold_bytes / (1024 ** 3), 3),
        "below_threshold": allocated < threshold_bytes,
    }
    if not result["below_threshold"]:
        raise SystemExit(
            "W1_LIVE_PHASE_BOUNDARY_RESIDUE: "
            f"{result['allocated_gib']}GiB still allocated after the "
            f"phase-1->phase-2 hard-free (gc.collect + empty_cache + "
            f"synchronize), above the {result['threshold_gib']}GiB "
            "threshold -- a real residue, not the expected near-zero "
            "baseline. Refusing to start phase-2 on top of it rather than "
            f"risk compounding toward another OOM. {json.dumps(result)}")
    return result


def derive_wall_hours_from_rung(rung_receipt: dict, ceiling_tokens: int) -> dict:
    """Wall/throughput re-estimate (issue #82 live-fire finding 2,
    requirement 4) -- derived FRESH from the rung receipt's own measured
    rate, never the prior w1-pricing receipt's pass-through figure. This is
    now a MORE faithful estimate than before: phase-2 adopts the SAME
    matched recipe (muon-split optimizer + MTP aux objective + bf16 +
    gradient checkpointing) the rung's own stabilization segment used when
    it measured this throughput, at the same architecture/batch/seq/
    governor pacing convention -- unlike the prior plain-AdamW design, which
    this throughput figure never actually characterized."""
    tok_s = rung_receipt["stabilization_segment"]["tok_s_paced"]
    wall_s = ceiling_tokens / tok_s if tok_s else None
    return {
        "throughput_tok_s_paced": tok_s,
        "throughput_source": (
            "rung_receipt.stabilization_segment.tok_s_paced -- measured "
            "during the live run that used the SAME matched recipe (muon "
            "split optimizer + MTP aux objective, at the same governor "
            "pacing) phase-2 now also uses, not the prior plain-AdamW-"
            "agnostic pricing-receipt pass-through"),
        "ceiling_tokens": ceiling_tokens,
        "wall_hours": None if wall_s is None else round(wall_s / 3600.0, 4),
    }


def run_phase1_live(real_arch: dict, rung_receipt: dict, *, device: str,
                     eval_x, eval_y) -> dict:
    """Real capability-point leg (issue #82 point 1): load the rung-1
    terminal checkpoint (sha-verified against the rung receipt), evaluate on
    the real held-out batch via the SAME eval_loss_fn dry-run phase 1 uses --
    NO retraining (spec sec.3: 'computed once from the existing checkpoint,
    CPU/GPU-cheap')."""
    checkpoint_verify = verify_real_checkpoint(
        real_arch["terminal_checkpoint_ref"], rung_receipt)
    model = build_real_model(real_arch, device)
    m_state, _, _, _ = load_checkpoint(real_arch["terminal_checkpoint_ref"])
    # Cheap, named parity check BEFORE the strict load (issue #82 reopened
    # cure) -- strict=True below still stays, unweakened, as the final
    # defense-in-depth assertion.
    key_shape_parity = verify_checkpoint_key_shape_parity(m_state, model)
    model.load_state_dict(m_state, strict=True)
    target_eval_loss = eval_loss_fn(model, eval_x, eval_y)
    return {
        "dry_run": False,
        "checkpoint_verify": checkpoint_verify,
        "key_shape_parity": key_shape_parity,
        "terminal_checkpoint_ref": real_arch["terminal_checkpoint_ref"],
        "target_eval_loss": target_eval_loss,
        "note": ("real rung-1 terminal checkpoint loaded and sha-verified "
                 "(path identity + per-file re-hash + key/shape parity + "
                 "strict state_dict match); no training in this leg -- the "
                 "capability point is computed once from the existing "
                 "checkpoint, per spec section 3."),
    }


def derive_continuation_arch(checkpoint_dir: str, real_arch: dict) -> dict:
    """W1b (#355): the continuation checkpoint is the UNWIDENED pre-grow
    seed -- its FF width is NOT real_arch['ff_grown'] (the grow arm's
    TARGET width; that is exactly what got widened). Derives a
    continuation-specific arch dict by reading the checkpoint's own
    model.pt tensor shape directly (same derived_from_checkpoint_tensor_
    shape convention as derive_rung_receipt_from_manifest's ff_grown
    fallback) so the continuation model is built at the checkpoint's OWN
    width -- vocab/hidden/n_mtp/seq/batch/layers/heads are shared with
    real_arch (only the FF width differs across the grow step)."""
    model_pt = os.path.join(checkpoint_dir, "model.pt")
    state = torch.load(model_pt, map_location="cpu")
    gate_key = next((k for k in state if k.endswith("mlp.gate_proj.weight")
                      or k.endswith("mlp.up_proj.weight")), None)
    if gate_key is None:
        raise SystemExit(
            "W1B_CONTINUE_FROM_NO_FF_WIDTH: no mlp.{gate,up}_proj.weight key "
            f"found in {model_pt!r}'s state_dict -- cannot derive the "
            "continuation checkpoint's FF width, refusing.")
    ff_seed = int(state[gate_key].shape[0])
    del state
    arch = dict(real_arch)
    arch["ff_grown"] = ff_seed
    arch["ff_grown_derivation"] = (
        f"derived_from_checkpoint_tensor_shape (W1b continuation checkpoint): "
        f"{gate_key}.shape[0]={ff_seed} -- deliberately NOT real_arch's "
        f"grow-target width ({real_arch['ff_grown']}); {W1B_ISSUE_REF} loads "
        "the UNWIDENED pre-grow seed, never the grown target.")
    return arch


# Sentinel distinguishing "caller did not pass mmap_cache_dir at all" from an
# explicit None (legacy opt-out) or an explicit path (opt-in) -- same
# convention as timeshare_pretrain.run_v0_segment's
# _RUN_V0_SEGMENT_MMAP_CACHE_DIR_UNSET (issue #570/#573).
_RUN_PHASE2_LIVE_MMAP_CACHE_DIR_UNSET = object()


def run_phase2_live(cfg_real: dict, real_arch: dict, *, ceiling_steps: int,
                     eval_every: int, checkpoint_every: int,
                     target_eval_loss: float, seed: int, device: str,
                     out_dir: str, shard_dir: str, eval_x, eval_y,
                     loader=None, rung_receipt: dict | None = None,
                     progress_path: str | None = None,
                     continue_from: str | None = None,
                     warmup_steps: int | None = None,
                     mmap_cache_dir: str | None = _RUN_PHASE2_LIVE_MMAP_CACHE_DIR_UNSET,
                     ) -> dict:
    """Real control leg, REWORKED to the full matched-recipe control (issue
    #82 live-fire finding 2, 2026-07-04): the prior plain-AdamW single-
    optimizer design OOM'd at 17.32GiB allocated + 1.61GiB fragmentation-
    reserved vs the 19.19GiB governed allowance, on its VERY FIRST forward
    pass (scratch/w1-control/live/w1-live-20260704c.log traceback: crashed
    inside backbone_model's MLP down_proj, "Tried to allocate 1024.00 MiB"
    == exactly batch*seq*ff_grown*4bytes, one MLP intermediate activation
    tensor in fp32; no backward()/optimizer.step() had run yet for this
    step, so NO optimizer state existed at the crash point -- this rules out
    "2 AdamW moment buffers" as the proximate trigger, though the design
    asymmetry was real and is now resolved anyway).

    Root-caused by READING the ACTUAL code that produced the proven-fit
    existence-proof run (rung-1 stabilization: cbase_grow_rung.py ->
    timeshare_pretrain.run_v0_segment -> build_v0_model's live branch, both
    trees checked, functions confirmed byte-identical across the contract/
    execution split) -- two confirmed discrepancies, never guessed:
      1. build_v0_model casts `.to(device).to(torch.bfloat16)`
         UNCONDITIONALLY (even on its own CPU smoke-test path). The real
         checkpoint's model.pt is confirmed ENTIRELY torch.bfloat16 (checked
         directly against the file). The prior RealW1Model built fp32
         (default), silently doubling every param/activation/gradient
         tensor's memory AND silently upcasting the checkpoint's bf16
         weights to fp32 on load_state_dict.
      2. build_v0_model calls `.gradient_checkpointing_enable()`
         UNCONDITIONALLY (same, even on CPU) -- this executes regardless of
         v0-pretrain-config.json's model.grad_checkpointing:false field
         (confirmed identical in both the v3-licensed execution-tree config
         and the v4 contract-tree config; the code does not read this flag
         at all). Without it, retained MLP activations across all 20 layers
         (ff_grown=16384 -> ~2.1GB/layer fp32) accumulate simultaneously
         during forward for backward -- 17.32GiB / ~2.1GB ~= 8 layers,
         closely matching the crash point.
    Also confirmed directly: the real checkpoint's optimizer.pt has
    top-level keys ['muon', 'adamw'] (proof the rung segment used
    build_split_optimizer's muon_split routing, never the AdamW-everything
    fallback), with a MIX of bfloat16 (Muon's momentum buffer, matching its
    bf16 param/grad) and float32 (AdamW's exp_avg/exp_avg_sq) tensor dtypes
    -- exactly what naturally falls out of casting the model to bf16 and
    building the SAME optimizers over it via build_split_optimizer, not a
    separately-chosen policy this rework has to reproduce by hand.

    Cure: reuses (never reimplements) build_split_optimizer, resolve_ce_impl,
    mtp_total_loss, save_optimizers_state/load_optimizers_state from
    timeshare_pretrain -- the SAME building blocks run_v0_segment itself
    composes (run_v0_segment cannot be called directly: its model comes from
    build_v0_model, whose intermediate_size is hardcoded to 4096, not this
    checkpoint's grown 16384 -- the same FF-width constraint that required
    RealW1Model to exist in the first place). ONLY the LR schedule is
    deliberately swapped for cosine+warmup (see cosine_warmup_frac/
    apply_cosine_warmup, MATCHED_RECIPE_SCHEDULE_SOURCE -- spec sec.2
    anti-poison clause: WSD is tuned for the grow-path's continuation, not
    a from-scratch control). The capability metric (target_eval_loss,
    eval_loss_fn) is UNCHANGED -- primary-CE-only, per the pre-existing spec
    sec.3 convention; only the TRAINING objective now includes the real MTP
    composite, matching production.

    loader: an already-built PackedShardLoader over shard_dir with
    n_mtp=real_arch["n_mtp"] (main_live now builds it at this count, not 0,
    since training needs real MTP targets too -- window x/primary-y for a
    given index are unaffected by n_mtp, verified by reading window_np's
    slicing directly, so this is also the correct loader for the held-out
    eval batch). Reused here for training to avoid a second ~14-27GB corpus
    load; builds its own (also at real_arch["n_mtp"]) only if none given
    (tiny-fixture selftest calling this function standalone).

    rung_receipt: if given, the wall/throughput estimate (requirement 4) is
    derived fresh from its own stabilization_segment.tok_s_paced field (see
    derive_wall_hours_from_rung) instead of the prior pricing-receipt
    pass-through.

    progress_path: instrumentation-only addition (observability for a
    detached, multi-hour background launch) -- when given, do_eval() appends
    one JSON line (step, tokens_so_far, eval_loss, ts) per evaluation,
    flushed immediately, so a monitor can confirm the run is alive without
    waiting for the terminal receipt. Never affects training/eval math or
    any gate decision -- purely a side-channel write.

    warmup_steps: optional, additive (issue #118 P1 envelope sweep,
    2026-07-08, docs/deviations.md DEV-003) -- passed straight through to
    apply_cosine_warmup's own warmup_steps override (see its docstring).
    Default None preserves this function's EXACT prior schedule (10% of
    ceiling_steps) for every pre-existing caller (main_live never passes
    it). Lets a caller with its own pre-computed absolute warmup-step count
    (e.g. prereg section 2's "min(2% of budget, absolute cap)" rule) apply
    it exactly, without a fraction round-trip."""
    if device == "cuda":
        from timeshare_pretrain import _apply_governor
        gov_receipt = _apply_governor()
    else:
        # governor.preflight() asserts a VRAM budget -- meaningless without an
        # actual GPU device. Production always calls this with device="cuda"
        # (main_live hardcodes device="cuda"); this branch exists so the
        # mechanics are exercisable end-to-end on a tiny CPU fixture without
        # ever touching CUDA (issue #82 verification leg: CPU-only, no CUDA
        # allocation from the builder session).
        gov_receipt = {
            "mode": "cpu_live_test",
            "note": "governor.preflight() not called -- device != 'cuda' "
                    "(tiny-fixture selftest path; production live path always "
                    "passes device='cuda')",
        }

    pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)
    mtp_cfg = pretrain_contract["objective"]["mtp_aux_heads"]
    mtp_enabled = bool(mtp_cfg["enabled"])
    mtp_weight = mtp_cfg["weight"]

    deviation_dir = os.path.join(out_dir, "deviations")

    # W1b (#355): continuation mode builds the model at the CHECKPOINT's own
    # (unwidened) FF width, never real_arch's grow-target width -- see
    # derive_continuation_arch's docstring.
    build_arch = derive_continuation_arch(continue_from, real_arch) if continue_from else real_arch

    def _build_model_and_optimizers():
        m = build_real_model(build_arch, device, seed=seed)
        opts, blrs, routing_ = build_split_optimizer(
            m, pretrain_contract, force_fallback=False,
            deviation_dir=deviation_dir)
        return m, opts, blrs, routing_

    model, optimizers, base_lrs, routing = _build_model_and_optimizers()
    continuation_source_manifest: dict | None = None
    if continue_from:
        # NO from-scratch init in this mode (#355's core requirement) --
        # fail-closed on a missing/mismatched checkpoint, reusing the exact
        # same load_continuation_checkpoint every other mode-entry path uses.
        o_state, r_state, continuation_source_manifest = load_continuation_checkpoint(
            continue_from, model)
        load_optimizers_state(optimizers, o_state)
        restore_rng(r_state)
    init_mode = "continuation" if continue_from else "from_scratch"
    ce_impl, ce_fn = resolve_ce_impl(prefer_liger=(device == "cuda"))

    if loader is None:
        from timeshare_pretrain import PackedShardLoader
        # mmap_cache_dir (issue #575): omitted -> sane default under THIS
        # segment's own out_dir (`<out_dir>/mmap_cache`), so any caller that
        # reaches this fallback construction (never passing a pre-built
        # loader) automatically gets the fragmentation-safe streamed-memmap
        # path over a real-corpus shard_dir. Explicit None still preserves
        # the legacy np.fromfile+np.concatenate path byte-for-byte. Both
        # current callers (main_live, p1_envelope_sweep.py) always pass an
        # explicit pre-built `loader=`, so this branch is not live-exercised
        # today -- fixed defensively so it can never silently regress to the
        # #570/#575 ArrayMemoryError class if a future caller omits loader.
        if mmap_cache_dir is _RUN_PHASE2_LIVE_MMAP_CACHE_DIR_UNSET:
            mmap_cache_dir = os.path.join(out_dir, "mmap_cache")
        loader = PackedShardLoader(shard_dir, real_arch["seq"],
                                   n_mtp=real_arch["n_mtp"],
                                   mmap_cache_dir=mmap_cache_dir)
        assert (loader.mmap_cache_report is not None) == (mmap_cache_dir is not None), (
            f"W1_LIVE_MMAP_CACHE_DIR_FORWARD_BROKEN: mmap_cache_dir={mmap_cache_dir!r} "
            f"but mmap_cache_report={loader.mmap_cache_report!r} -- forwarding "
            "invariant violated (issue #575)")

    _pace_reset()
    eval_trace: list[dict] = []
    lr_trace: list[float] = []
    resume_proof: dict | None = None
    matched = False
    tokens_to_match: int | None = None
    stop_step: int | None = None

    def do_eval(step_idx: int, tokens_so_far: int) -> float:
        el = eval_loss_fn(model, eval_x, eval_y)
        eval_trace.append({"step": step_idx, "tokens_so_far": tokens_so_far,
                            "eval_loss": el})
        if progress_path:
            row = {"step": step_idx, "tokens_so_far": tokens_so_far,
                   "eval_loss": el, "target_eval_loss": target_eval_loss,
                   "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}
            with open(progress_path, "a", encoding="utf-8", newline="\n") as pf:
                pf.write(json.dumps(row) + "\n")
                pf.flush()
                os.fsync(pf.fileno())
            print(f"[w1-live-progress] step={step_idx} tokens={tokens_so_far} "
                  f"eval_loss={el} target={target_eval_loss}", flush=True)
        return el

    resume_at_step = checkpoint_every
    resumed_once = False
    t0 = time.perf_counter()

    step = 0
    el0 = do_eval(0, 0)
    if el0 <= target_eval_loss:
        matched, tokens_to_match, stop_step = True, 0, 0

    while step < ceiling_steps and not matched:
        x, y0, y_mtp = loader.batch(step, real_arch["batch"])
        x = x.to(device)
        y0 = y0.to(device)
        y_mtp = [t.to(device) for t in y_mtp]
        mult = apply_cosine_warmup(optimizers, base_lrs, step, ceiling_steps,
                                    warmup_steps=warmup_steps)
        lr_trace.append(round(mult, 8))
        train_step_matched_recipe(
            model, optimizers, ce_fn, x=x, y0=y0, y_mtp=y_mtp,
            mtp_enabled=mtp_enabled, mtp_weight=mtp_weight)
        step += 1
        tokens_so_far = step * real_arch["batch"] * real_arch["seq"]
        _pace_record("pace", 0.0)

        if step == resume_at_step and not resumed_once:
            pre_ckpt_eval = eval_loss_fn(model, eval_x, eval_y)
            rng_snap = capture_rng()
            saved_o_state = save_optimizers_state(optimizers)
            ckpt_dir = save_checkpoint(
                out_dir, step, model.state_dict(), saved_o_state,
                rng_snap, extra={"segment_id": "w1-phase2-live-control",
                                  "dry_run": False, "step": step,
                                  "optimizer_mode": routing["mode"]})
            del model, optimizers
            model, optimizers, base_lrs, routing = _build_model_and_optimizers()
            m_state, o_state, r_state, manifest = load_checkpoint(ckpt_dir)
            model.load_state_dict(m_state, strict=True)
            load_optimizers_state(optimizers, o_state)
            restore_rng(r_state)
            post_resume_eval = eval_loss_fn(model, eval_x, eval_y)
            resume_proof = {
                "checkpoint_dir": ckpt_dir,
                "resume_step": manifest["step"],
                "eval_loss_pre_checkpoint": pre_ckpt_eval,
                "eval_loss_immediately_post_resume": post_resume_eval,
                "bit_exact": pre_ckpt_eval == post_resume_eval,
                "loss_continuity": check_resume_integrity(
                    [pre_ckpt_eval], [post_resume_eval], rtol=1e-6),
                "verdict": ("RESUME_BIT_EXACT" if pre_ckpt_eval == post_resume_eval
                            else "RESUME_STATE_MISMATCH"),
                "optimizer_state_shape_check": optimizer_state_shape_parity(
                    save_optimizers_state(optimizers), saved_o_state),
            }
            resumed_once = True

        if step % eval_every == 0 or step == ceiling_steps:
            el = do_eval(step, tokens_so_far)
            if el <= target_eval_loss:
                matched = True
                tokens_to_match = tokens_so_far
                stop_step = step

    wall_s = time.perf_counter() - t0
    tokens_at_ceiling = ceiling_steps * real_arch["batch"] * real_arch["seq"]

    wall_hours_estimate = (derive_wall_hours_from_rung(rung_receipt, tokens_at_ceiling)
                          if rung_receipt is not None else None)

    # W1b (#355): config_sha must describe the model actually built --
    # build_arch (checkpoint's own FF width) in continuation mode, never the
    # caller-supplied cfg_real (which describes real_arch, the grow-TARGET).
    actual_cfg_real = real_config_dict(build_arch) if continue_from else cfg_real

    return {
        "config_sha": config_sha(actual_cfg_real),
        "init_seed": seed,
        "init_mode": init_mode,
        "continue_from_checkpoint": (repo_relative_path(continue_from)
                                      if continue_from else None),
        "continuation_source_manifest_step": (
            (continuation_source_manifest or {}).get("step")),
        "continuation_source_manifest": continuation_source_manifest,  # added for issue #375
        "lr_schedule": {"source": MATCHED_RECIPE_SCHEDULE_SOURCE,
                        "base_lrs": base_lrs, "warmup_frac": 0.1,
                        "warmup_steps_override": warmup_steps,
                        "effective_warmup_steps": (
                            max(1, int(warmup_steps)) if warmup_steps is not None
                            else max(1, int(ceiling_steps * 0.1))),
                        "min_lr_frac": 0.1,
                        "total_steps_for_schedule": ceiling_steps,
                        "lr_mult_trace_first": lr_trace[0] if lr_trace else None,
                        "lr_mult_trace_last": lr_trace[-1] if lr_trace else None},
        "optimizer": {"mode": routing["mode"], "n_muon": routing.get("n_muon"),
                      "n_adamw": routing.get("n_adamw"), "ce_impl": ce_impl,
                      "mtp_enabled": mtp_enabled, "mtp_weight": mtp_weight,
                      "n_mtp_heads": real_arch["n_mtp"]},
        "eval_cadence_K": eval_every,
        "ceiling_steps": ceiling_steps,
        "steps_run": step,
        "matched": matched,
        "tokens_to_match": tokens_to_match,
        "tokens_at_ceiling": None if matched else tokens_at_ceiling,
        "stop_step": stop_step,
        "eval_trace": eval_trace,
        "resume_proof": resume_proof,
        "wall_s": round(wall_s, 3),
        "wall_hours_estimate": wall_hours_estimate,
        "pacing": pacing_snapshot(),
        "governor": gov_receipt,
    }


# ---------------------------------------------------------------------------
# Outcome classification (spec section 4 -- all three land as truth).
# ---------------------------------------------------------------------------

def classify_outcome(tokens_growpath: int, phase2: dict) -> dict:
    if phase2["matched"]:
        tokens_fromscratch = phase2["tokens_to_match"]
        ratio = (tokens_fromscratch / tokens_growpath) if tokens_growpath > 0 else None
        if ratio is None:
            outcome = "L2"
            lower_bound = True
            ratio_repr = None
        elif ratio > 1:
            outcome = "L1"
            lower_bound = False
            ratio_repr = ratio
        else:
            outcome = "L3"
            lower_bound = False
            ratio_repr = ratio
        return {"outcome": outcome, "ratio": ratio_repr, "lower_bound": lower_bound,
                "tokens_fromscratch": tokens_fromscratch}
    else:
        tokens_ceiling = phase2["tokens_at_ceiling"]
        ratio_lower = (tokens_ceiling / tokens_growpath) if tokens_growpath > 0 else None
        return {"outcome": "L2", "ratio": f"> {ratio_lower}" if ratio_lower else None,
                "lower_bound": True, "tokens_fromscratch": tokens_ceiling}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true",
                    help="real-run path; refuses unless EMBER_GATE_AUTHORIZED=1 "
                         "AND --device cuda AND --shard-dir given. Never fired "
                         "by this builder.")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--shard-dir", default=None,
                    help="real packed-token shards; required on --live, refused "
                         "to fabricate (eng-54 #194 guard)")
    ap.add_argument("--out-dir", default=os.path.join(
        REPO, "scratch", "w1-control", "dry-run"))
    ap.add_argument("--receipts-out-dir", default=None,
                    help="issue #361 fix-forward: override the receipt "
                    "output directory. Dry-run mode (default) writes its "
                    "receipt under scratch/, never the canonical receipts/ "
                    "tree, unless this is set explicitly -- a launch lane's "
                    "own dry-run smoke test previously landed a toy-fixture "
                    "receipt in receipts/ember-c-scale/. --live is "
                    "unaffected: a real live run always writes to the "
                    "canonical receipts/ember-c-scale/ tree.")
    ap.add_argument("--pricing-receipt", default=DEFAULT_PRICING_RECEIPT)
    ap.add_argument("--rung-receipt", default=DEFAULT_RUNG_RECEIPT)
    ap.add_argument("--rung-manifest", default=None,
                    help="issue #121 item 7: path to a real per-checkpoint "
                         "manifest.json (e.g. models/cbase-grow-rung/.../"
                         "stabilize/checkpoints/step-NNNNNN/manifest.json) to "
                         "use INSTEAD of --rung-receipt, when no aggregate "
                         "rung_receipt file exists. Builds a rung_receipt-"
                         "shaped dict via derive_rung_receipt_from_manifest -- "
                         "disclosed derivation, never a hand-authored receipt.")
    # tiny dry-run architecture (task-specified defaults)
    ap.add_argument("--vocab", type=int, default=512)
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--seq", type=int, default=64)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--ceiling-steps", type=int, default=40)
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--checkpoint-every", type=int, default=10)
    ap.add_argument("--phase1-train-steps", type=int, default=20)
    ap.add_argument("--phase1-seed", type=int, default=1001)
    ap.add_argument("--phase2-seed", type=int, default=2002)
    # Live-path-only options (issue #82). Kept SEPARATE from the dry-run
    # tunables above (--ceiling-steps/--eval-every/--checkpoint-every) so the
    # dry-run branch's defaults/behavior are untouched by this change.
    ap.add_argument("--corpus-manifest-sha256",
                    default=CORPUS_MANIFEST_COMBINED_SHA256_EXPECTED,
                    help="expected combined_sha256 of --shard-dir's manifest "
                         "(sha-verified fail-closed on live launch, cited from "
                         "receipts/corpus-verification-20260704T095213Z.json); "
                         "pass '' to skip the check (NOT recommended -- only "
                         "for a deliberate, disclosed corpus refresh).")
    ap.add_argument("--live-ceiling-steps", type=int, default=None,
                    help="live control-arm hard ceiling steps; default "
                         f"REAL_HARD_CEILING_STEPS ({REAL_HARD_CEILING_STEPS}, "
                         "issue-stated) unless given.")
    ap.add_argument("--live-eval-every", type=int, default=None,
                    help="live eval cadence K; default "
                         f"REAL_EVAL_CADENCE_K ({REAL_EVAL_CADENCE_K}) unless given.")
    ap.add_argument("--live-checkpoint-every", type=int, default=None,
                    help="live checkpoint cadence; defaults to --live-eval-every "
                         "unless given (spec sec.6: 'checkpoint + eval every K steps').")
    ap.add_argument("--decontam-receipt", default=None,
                    help="issue #121 spec-compliance (Defect B): path to an "
                         "external w2-heldout-decontam/v1 receipt. When given, "
                         "the live held-out batch is rebuilt from the receipt's "
                         "own selected_window_indices (not this script's default "
                         "'last batch-many windows' convention) and the rebuilt "
                         "batch's sha256 is asserted against the receipt's pinned "
                         "batch_sha256, refusing on any mismatch. Omit to keep "
                         "the frozen protocol's original default behavior "
                         "unchanged.")
    ap.add_argument("--recheck-cache-dir", default=None,
                    help="issue #351: stable cache directory for contamination "
                         "recheck results. Defaults to scratch/w1-control/recheck-cache/. "
                         "The cache key is (batch_sha, decontam_receipt_sha, "
                         "classifier_code_sha); cache hits skip the expensive recheck. "
                         "Must be stable across launches (NOT a per-run out-dir). "
                         "Non-PASS verdicts are never cached.")
    ap.add_argument("--continue-from", default=None,
                    help=f"W1b ({W1B_ISSUE_REF}): resume-from-checkpoint-"
                         "UNWIDENED continuation mode. Path to a checkpoint "
                         "dir (save_checkpoint format) to load INSTEAD of "
                         "from-scratch init -- everything else (eval_loss_fn, "
                         "certified held-out batch, anti-poison cosine+"
                         "warmup schedule, contamination recheck, receipt "
                         "schema) is identical to the W1 control path. "
                         "Refuses fail-closed on a missing or architecture-"
                         "mismatched checkpoint (load_continuation_"
                         "checkpoint); NEVER silently falls back to random "
                         "init. Omit to keep the original from-scratch "
                         "control-arm behavior unchanged.")
    ap.add_argument("--tokens-growpath-marginal", type=int,
                    default=W1B_MARGINAL_TOKENS_GROWPATH,
                    help=f"W1b ({W1B_ISSUE_REF}): the grow arm's MARGINAL "
                         f"(post-seed) token bill -- default "
                         f"{W1B_MARGINAL_TOKENS_GROWPATH} (156 steps @ "
                         "batch16 seq1024). Drives the outcome classifier's "
                         "PRIMARY ratio/outcome/lower_bound fields in "
                         "continuation mode (--continue-from given); only "
                         "used in that mode.")
    ap.add_argument("--tokens-growpath-cumulative", type=int, default=None,
                    help=f"W1b ({W1B_ISSUE_REF}) context-only field, only "
                         "used in continuation mode: the ORIGINAL W1 "
                         "cumulative grow-arm bill (seed+pre-grow+stabilize). "
                         "Carried alongside the marginal ratio so the "
                         "pre-registered reading rules have both figures -- "
                         "NEVER drives the primary outcome/ratio fields. "
                         "Defaults to this run's own phase-1 tokens_total "
                         "(dry-run) or the pricing receipt's grow_arm."
                         "tokens_total (live) when omitted.")
    return ap


def refuse_unless_dry_run_safe(args: argparse.Namespace) -> None:
    """Default-closed guard (mirrors timeshare_pretrain._check_launch_interlock):
    refuses the GPU/real-run path unless explicitly authorized, and refuses to
    fabricate synthetic shards on that path even when authorized."""
    if not args.live and args.device == "cpu":
        return
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not (authorized and args.live and args.device == "cuda"):
        msg = ("W1_CONTROL_LAUNCH_INTERLOCK_REFUSED: real/GPU path blocked. "
               "Requires EMBER_GATE_AUTHORIZED=1 (env) AND --live AND "
               "--device cuda. The real run is maintainer-window-scheduled "
               f"(issue #53); never fired by this builder. "
               f"[authorized={authorized}, live={args.live}, device={args.device}]")
        print(msg)
        raise SystemExit(msg)
    if not args.shard_dir:
        raise SystemExit(
            "W1_CONTROL_LIVE_NO_SHARDS: live control-arm training requires a "
            "real --shard-dir of packed token shards; refusing to fabricate "
            "synthetic tokens on the live/GPU path (mirrors eng-54 #194).")
    maintainer_confirmed = os.environ.get(MAINTAINER_WINDOW_ENV, "") == "1"
    if not maintainer_confirmed:
        raise SystemExit(
            "W1_CONTROL_LIVE_SECOND_INTERLOCK_REFUSED: real/GPU launch "
            f"additionally requires {MAINTAINER_WINDOW_ENV}=1, INDEPENDENT of "
            "EMBER_GATE_AUTHORIZED=1 -- a second, W1-specific key so a "
            "builder/test session that happens to carry EMBER_GATE_AUTHORIZED=1 "
            "for unrelated reasons (or a machine where torch.cuda.is_available() "
            "is True because the GPU merely happens to be window-occupied, not "
            "absent) can never reach the real training path. Set only by the "
            "maintainer's actual GPU-launch runbook.")


def main_live(args: argparse.Namespace, ts: str, pricing_receipt: dict,
              rung_receipt: dict, real_arch: dict) -> int:
    """REAL live pipeline (issue #82). Reachable ONLY after both
    refuse_unless_dry_run_safe interlocks passed (EMBER_GATE_AUTHORIZED=1 AND
    EMBER_W1_MAINTAINER_WINDOW_CONFIRMED=1 AND --live AND --device cuda AND
    --shard-dir). Never invoked by this builder outside a fixture-mocked
    selftest that stops short of this function (the selftest exercises the
    constituent assertion functions directly, on tiny fixtures, never this
    entrypoint end-to-end against real CUDA)."""
    import numpy as np

    # Fragmentation mitigation (issue #82 live-fire finding 2, requirement 3)
    # -- MUST be set before the process's first CUDA context init (before any
    # .cuda()/.to("cuda") call anywhere below), or it has no effect. The env
    # var name is copied EXACTLY from the actual OOM error message ("If
    # reserved but unallocated memory is large try setting
    # PYTORCH_ALLOC_CONF=expandable_segments:True"), not assumed/renamed.
    pytorch_alloc_conf_already_set = "PYTORCH_ALLOC_CONF" in os.environ
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    pytorch_alloc_conf_receipt = {
        "env_var": "PYTORCH_ALLOC_CONF",
        "value": os.environ["PYTORCH_ALLOC_CONF"],
        "already_set_by_caller": pytorch_alloc_conf_already_set,
        "adopted_by_this_run": not pytorch_alloc_conf_already_set,
    }

    from timeshare_pretrain import PackedShardLoader

    device = "cuda"
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    expected_corpus_sha = args.corpus_manifest_sha256 or None
    shard_manifest = verify_shard_corpus(
        args.shard_dir, expected_combined_sha256=expected_corpus_sha)
    shard_verified_ok = (expected_corpus_sha is None or
                         shard_manifest["combined_sha256"] == expected_corpus_sha)

    # n_mtp threaded through (issue #82 live-fire finding 2): the matched-
    # recipe training loop needs real MTP targets, so the ONE loader built
    # below is now sized at real_arch["n_mtp"] (was 0) and reused for BOTH
    # the held-out eval batch AND phase-2 training -- window_np's x/primary-y
    # slicing for a given window index is unaffected by n_mtp (verified by
    # reading PackedShardLoader.window_np directly: x = w[:seq] always
    # starts at i*seq regardless of block_len), only n_windows itself shrinks
    # slightly as n_mtp grows, so n_windows must be re-derived at the SAME
    # n_mtp the loader actually uses for held-out-start/disjointness to stay
    # exactly correct (not "coincidentally correct at this corpus scale").
    n_windows = compute_n_windows_from_manifest(
        shard_manifest, real_arch["seq"], n_mtp=real_arch["n_mtp"])
    ceiling_steps = args.live_ceiling_steps or REAL_HARD_CEILING_STEPS
    eval_every = args.live_eval_every or REAL_EVAL_CADENCE_K
    checkpoint_every = args.live_checkpoint_every or eval_every

    # mmap_cache_dir (issue #575): this real live entrypoint (--shard-dir is
    # a real, potentially large external corpus) never forwarded the
    # parameter at all -- sane default under THIS run's own out_dir
    # (`<out_dir>/mmap_cache`, out_dir already resolved above), the same
    # fragmentation-safe streamed-memmap path timeshare_pretrain.
    # run_v0_segment's callers get automatically (issue #570/#573). No CLI
    # opt-out flag exists yet, matching #573/#575's "surgical forwarding
    # only" scope -- this is the exact ArrayMemoryError class the memmap
    # cache exists to kill, at real-corpus scale, so the default engages
    # unconditionally.
    mmap_cache_dir = os.path.join(out_dir, "mmap_cache")
    eval_loader = PackedShardLoader(args.shard_dir, real_arch["seq"],
                                    n_mtp=real_arch["n_mtp"],
                                    mmap_cache_dir=mmap_cache_dir)
    assert (eval_loader.mmap_cache_report is not None) == (mmap_cache_dir is not None), (
        f"W1_LIVE_MMAP_CACHE_DIR_FORWARD_BROKEN: mmap_cache_dir={mmap_cache_dir!r} "
        f"but mmap_cache_report={eval_loader.mmap_cache_report!r} -- forwarding "
        "invariant violated (issue #575)")

    decontam_receipt = None
    launch_gate_result = None
    if args.decontam_receipt:
        # Defect B: external decontam receipt drives WHICH windows are held
        # out (never this script's internal 'last batch-many windows' rule --
        # the receipt's curated pool may sit anywhere in the corpus).
        decontam_receipt = load_json(args.decontam_receipt)
        held_out_start = None
        candidate_window_indices = decontam_receipt.get("selected_window_indices") or []
        # 2026-07-07 fork-B hardening: the receipt's OWN cached disjoint_check
        # was computed at RECEIPT-GENERATION time, against WHATEVER
        # ceiling_steps/batch that generation run assumed -- never previously
        # re-derived against THIS live invocation's ACTUAL ceiling_steps/
        # real_arch["batch"] (which can differ via --live-ceiling-steps or a
        # different --batch). Re-derive independently here; a receipt that
        # happens to still be disjoint under this run's real numbers passes
        # silently, a receipt that is NOT refuses fail-closed instead of
        # trusting a figure that was never about this run.
        this_run_disjoint_check = assert_disjoint_from_training(
            min(candidate_window_indices) if candidate_window_indices else 0,
            ceiling_steps, real_arch["batch"])
        disjoint_check = {
            "mode": "external_decontam_receipt",
            "receipt_path": args.decontam_receipt,
            "selected_window_indices": candidate_window_indices,
            "receipt_own_disjoint_check": (decontam_receipt.get("source_pool", {})
                                            .get("pool_reservation", {})
                                            .get("disjoint_check")),
            "this_run_disjoint_check": this_run_disjoint_check,
            "note": ("disjointness is re-derived HERE against this run's actual "
                     "ceiling_steps/batch (this_run_disjoint_check), not merely "
                     "cited from the receipt's own generation-time figure "
                     "(receipt_own_disjoint_check) -- 2026-07-07 fork-B "
                     "hardening."),
        }
        eval_x, eval_y, eval_sha = rebuild_batch_from_decontam_receipt(
            eval_loader, decontam_receipt, device)
        xs = [eval_x[i].to("cpu").numpy() for i in range(eval_x.shape[0])]
        ys = [eval_y[i].to("cpu").numpy() for i in range(eval_y.shape[0])]
        eval_batch_pinned_ok = bool(eval_sha)
        # Literal reuse of scripts/w2_heldout/launch_gate.py's assert_launch_
        # allowed -- an independently-coded re-verification (separate hashing
        # code path) of the same receipt's pass/contamination_recheck fields
        # and the rebuilt batch's sha256, layered on top of the assertion
        # rebuild_batch_from_decontam_receipt already performed above.
        launch_gate_result = wire_launch_gate_check(
            xs, ys, seq=real_arch["seq"], receipt_path=args.decontam_receipt,
            out_dir=out_dir, ts=ts)
    else:
        held_out_start = held_out_window_start(n_windows, real_arch["batch"])
        disjoint_check = assert_disjoint_from_training(
            held_out_start, ceiling_steps, real_arch["batch"])
        candidate_window_indices = [held_out_start + j for j in range(real_arch["batch"])]
        xs, ys = [], []
        for j in range(real_arch["batch"]):
            x_np, y_np, _y_mtp = eval_loader.window_np(held_out_start + j)
            xs.append(x_np)
            ys.append(y_np)
        eval_x = torch.as_tensor(np.stack(xs), dtype=torch.long, device=device)
        eval_y = torch.as_tensor(np.stack(ys), dtype=torch.long, device=device)
        eval_sha = sha256_tokens(torch.cat([eval_x, eval_y], dim=1))
        eval_batch_pinned_ok = bool(eval_sha)

    # Contamination re-check hook (corpus-verification receipt's open item):
    # reconstruct the full seq+1 window per held-out row (x_np is w[0:seq],
    # y_np is w[1:seq+1], so w = x_np + [y_np[-1]]) before scanning.
    eval_rows = [list(x_np) + [int(y_np[-1])] for x_np, y_np in zip(xs, ys)]

    # Issue #351: Content-addressed contamination recheck cache. If the triple
    # key (batch sha + decontam receipt sha + classifier code sha) matches a
    # cached PASS result, skip the expensive recheck and cite the cached receipt.
    # Cache root is stable across launches (not per-run out-dir) to enable
    # cross-launch cache hits. Any mismatch or non-PASS verdict triggers full recheck.
    cache_root = args.recheck_cache_dir or os.path.join(
        REPO, "scratch", "w1-control", "recheck-cache")
    contamination = check_recheck_cache(
        eval_rows, args.shard_dir, args.decontam_receipt, cache_root,
        classifier_code_path=os.path.join(HERE, "w1_collapse_control_run.py"))
    if not contamination:
        # Cache miss or non-PASS verdict: run full recheck
        contamination = contamination_recheck(eval_rows, args.shard_dir)
        # Write to cache if this is a PASS result (non-PASS results are not cached)
        write_recheck_cache(
            contamination, eval_rows, args.decontam_receipt, cache_root,
            classifier_code_path=os.path.join(HERE, "w1_collapse_control_run.py"))
    # Defect A v2 (2026-07-07 fork-A fix): gate on the SELF-EXCLUSION-AWARE
    # classification, not the raw verdict -- contamination_recheck() cannot
    # tell the held-out batch's own true source windows (unavoidable matches)
    # from a genuine foreign duplicate. Applies whether or not
    # --decontam-receipt was given.
    contamination_classified = classify_contamination_self_matches(
        contamination, candidate_window_indices,
        seq=real_arch["seq"], n_mtp=real_arch["n_mtp"], shard_dir=args.shard_dir)
    refuse_if_non_self_contaminated(
        contamination_classified, contamination=contamination,
        candidate_window_indices=candidate_window_indices,
        args=args, out_dir=out_dir, ts=ts, real_arch=real_arch,
        disjoint_check=disjoint_check, eval_batch_sha=eval_sha)

    phase1 = run_phase1_live(real_arch, rung_receipt, device=device,
                              eval_x=eval_x, eval_y=eval_y)

    # Phase-boundary hygiene (issue #82 live-fire finding 2, requirement 2):
    # hard-free phase-1's resident + ASSERT allocated is below threshold
    # BEFORE phase-2 builds its own model + optimizers.
    phase_boundary_hygiene = hard_free_and_assert_phase_boundary(device)

    cfg_real = real_config_dict(real_arch)
    progress_path = os.path.join(out_dir, f"w1-live-progress-{ts}.jsonl")
    phase2 = run_phase2_live(
        cfg_real, real_arch, ceiling_steps=ceiling_steps, eval_every=eval_every,
        checkpoint_every=checkpoint_every, target_eval_loss=phase1["target_eval_loss"],
        seed=args.phase2_seed, device=device,
        out_dir=os.path.join(out_dir, "phase2-live"), shard_dir=args.shard_dir,
        eval_x=eval_x, eval_y=eval_y,
        loader=eval_loader,  # reuse -- avoid a second ~14-27GB corpus load
        rung_receipt=rung_receipt,
        progress_path=progress_path,
        continue_from=args.continue_from)

    is_real_lineage, lineage_reasons = assess_real_lineage(
        checkpoint_verified=True,   # run_phase1_live raises before returning if not
        shard_verified=shard_verified_ok,
        eval_batch_pinned=eval_batch_pinned_ok)

    # W1b (#355): continuation mode prices the outcome classifier against the
    # MARGINAL bill; the cumulative W1 bill is carried alongside as context
    # only (w1b_continuation block below) -- same split as the dry-run branch.
    w1b_continuation = None
    if args.continue_from:
        tokens_growpath_marginal = args.tokens_growpath_marginal
        tokens_growpath_cumulative = (
            args.tokens_growpath_cumulative
            if args.tokens_growpath_cumulative is not None
            else pricing_receipt["grow_arm"]["tokens_total"])
        outcome = classify_outcome(tokens_growpath_marginal, phase2)
        outcome_cumulative = classify_outcome(tokens_growpath_cumulative, phase2)
        w1b_continuation = {
            "issue_ref": W1B_ISSUE_REF,
            "mode": "continuation",
            "continue_from_checkpoint": phase2["continue_from_checkpoint"],
            "continuation_source_manifest_step": phase2["continuation_source_manifest_step"],
            "tokens_growpath_marginal": tokens_growpath_marginal,
            "tokens_growpath_cumulative": tokens_growpath_cumulative,
            "ratio_marginal": outcome["ratio"],
            "outcome_marginal": outcome["outcome"],
            "ratio_cumulative": outcome_cumulative["ratio"],
            "outcome_cumulative": outcome_cumulative["outcome"],
            "note": ("ratio/outcome/lower_bound at the receipt's top level are "
                     "the MARGINAL reading (this run's primary classification, "
                     f"per {W1B_ISSUE_REF}); ratio_cumulative/outcome_cumulative "
                     "above are context only, carried so the pre-registered "
                     "reading rules have both figures."),
        }
    else:
        outcome = classify_outcome(pricing_receipt["grow_arm"]["tokens_total"], phase2)

    eval_trace_path = os.path.join(out_dir, f"w1-eval-trace-live-{ts}.json")
    with open(eval_trace_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(phase2["eval_trace"], f, indent=2)
    eval_trace_sha = sha256_file(eval_trace_path)
    rung_prov = rung_provenance_info(args)

    receipt = {
        "ticket": "W1-COLLAPSE-CONTROL",
        "ts": ts,
        "issue": ISSUE_REF,
        "schema": "w1-collapse-control/v1",
        "spec_ref": f"{SPEC_REF} section 7",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "dry_run": False,
        "is_real_lineage": is_real_lineage,
        "is_real_lineage_reasons": lineage_reasons,
        "mode": "live",
        "device": device,
        "real_lineage_reference": {
            # issue #361 fix-forward: pricing_receipt_path/rung_provenance_path
            # were written raw with no repo_relative_path call at all (same
            # #357 class as the shard_dir leak, now cured here too).
            "pricing_receipt_path": repo_relative_path(args.pricing_receipt),
            "pricing_receipt_sha256": sha256_file(args.pricing_receipt),
            "rung_provenance_mode": rung_prov["mode"],
            "rung_provenance_path": repo_relative_path(rung_prov["path"]),
            "rung_provenance_sha256": rung_prov["sha256"],
            "corpus_verification_receipt": CORPUS_VERIFICATION_RECEIPT,
            "derived_target_architecture": real_arch,
        },
        "checkpoint_verification": phase1["checkpoint_verify"],
        # issue #357 cure: corpus_id + corpus_manifest_sha256, never the raw
        # --shard-dir string (see build_shard_corpus_verification_block).
        "shard_corpus_verification": build_shard_corpus_verification_block(
            args.shard_dir, shard_manifest, expected_corpus_sha, shard_verified_ok),
        "held_out_batch": {
            "window_start": held_out_start,
            "n_windows_total": n_windows,
            "derivation_mode": ("decontam-receipt-indices"
                                if args.decontam_receipt else "contiguous-default"),
            "disjointness_check": disjoint_check,
            "decontam_receipt_path": args.decontam_receipt,
            "launch_gate_result": launch_gate_result,
        },
        "recheck_cache_config": {
            "cache_root": cache_root,
            "cache_hit": contamination.get("cache_write_ts") is not None,
            "cached_receipt_path": contamination.get("cached_receipt_path"),
            "cached_receipt_ts": contamination.get("cache_write_ts"),
        },
        "contamination_recheck": contamination,
        "contamination_recheck_self_exclusion": contamination_classified,
        "grow_arm": {
            "terminal_checkpoint_ref": phase1["terminal_checkpoint_ref"],
            "tokens_total": pricing_receipt["grow_arm"]["tokens_total"],
            "bill_aggregation_rows": pricing_receipt["grow_arm"]["bill_aggregation_rows"],
            "dry_run": False,
            "is_real_lineage": is_real_lineage,
        },
        "control_arm": {
            "config_sha": phase2["config_sha"],
            "init_seed": phase2["init_seed"],
            "init_mode": phase2["init_mode"],
            "continue_from_checkpoint": phase2["continue_from_checkpoint"],
            "continuation_source_manifest_step": phase2["continuation_source_manifest_step"],
            "lr_schedule": phase2["lr_schedule"],
            "optimizer": phase2["optimizer"],
            "tokens_to_match": phase2["tokens_to_match"],
            "tokens_at_ceiling": phase2["tokens_at_ceiling"],
            "eval_trace_ref": eval_trace_path,
            "eval_trace_sha256": eval_trace_sha,
            "eval_cadence_K": phase2["eval_cadence_K"],
            "ceiling_steps": phase2["ceiling_steps"],
            "ceiling_steps_issue_stated": REAL_HARD_CEILING_STEPS_ISSUE_STATED,
            "steps_run": phase2["steps_run"],
            "resume_proof": phase2["resume_proof"],
            "governor": phase2["governor"],
            "pacing": phase2["pacing"],
            "wall_s": phase2["wall_s"],
            "wall_hours_estimate": phase2["wall_hours_estimate"],
        },
        "w1b_continuation": w1b_continuation,
    }

    # Issue #375: Add continuation_source_verification block if --continue-from was used
    if args.continue_from and phase2.get("continuation_source_manifest"):
        receipt["continuation_source_verification"] = verify_continuation_source_checkpoint(
            args.continue_from, phase2["continuation_source_manifest"])

    # Add remaining receipt fields
    receipt.update({
        "cap_disclosure": {
            "note": "Two different 'L0 budget cap' multipliers exist in this "
                    "program's documentation and must not be conflated. This run "
                    "enforces ONLY the first one.",
            "w1_pricing_receipt_ceiling": {
                "multiplier": "2.0 * grow_arm",
                "tokens": pricing_receipt["wall_hours_pricing"]["control_arm_ceiling_tokens"],
                "source": args.pricing_receipt,
                "matches_issue_71_stated_hard_ceiling": True,
            },
            "w2_scale_preregistration_multiplier_1p5x": {
                "multiplier": "1.5 * grow.projected",
                "source": "docs/spec/w2-scale-preregistration-v1.md section 3 (L0 "
                           "definition) -- a DIFFERENT experiment's convention "
                           "(rung-2 scale arms), not this W1 from-scratch control "
                           "run's own frozen ceiling. Referenced here only because "
                           "a launch instruction cited it alongside this run; NOT "
                           "enforced by this script.",
            },
            "bound_enforced_this_run": (
                "w1_pricing_receipt_ceiling (ceiling_steps, "
                f"REAL_HARD_CEILING_STEPS_ISSUE_STATED={REAL_HARD_CEILING_STEPS_ISSUE_STATED}), "
                "or target_eval_loss match if that fired first -- see "
                "control_arm.tokens_to_match vs control_arm.tokens_at_ceiling above "
                "for which one actually terminated this run."),
        },
        "phase_boundary_hygiene": phase_boundary_hygiene,
        "pytorch_alloc_conf": pytorch_alloc_conf_receipt,
        "capability_point": {
            "eval_batch_sha256": eval_sha,
            "eval_batch_shape": {"batch": real_arch["batch"], "seqlen": real_arch["seq"]},
            "target_eval_loss": phase1["target_eval_loss"],
            "dry_run_capability_point": False,
        },
        "ratio": outcome["ratio"],
        "outcome": outcome["outcome"],
        "lower_bound": outcome["lower_bound"],
        "seeds": 1,
        "seed_sensitivity_unmeasured": True,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "pass": is_real_lineage,
        "verdict": ("W1_CONTROL_LIVE_COMPLETE" if is_real_lineage
                    else "W1_CONTROL_LIVE_LINEAGE_UNVERIFIED"),
        "note": ("" if is_real_lineage else
                 f"is_real_lineage=False -- failing assertions: {lineage_reasons}. "
                 "Fail-closed per issue #82 point 3: never a silent/blanket True."),
    })

    receipts_dir = os.path.join(REPO, "receipts", "ember-c-scale")
    os.makedirs(receipts_dir, exist_ok=True)
    out_path = os.path.join(receipts_dir, f"w1-collapse-control-{ts}.json")
    checked_write(out_path, receipt)

    with open(out_path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "W1_RECEIPT_HAS_BOM"
    with open(out_path, "r", encoding="utf-8") as f:
        json.load(f)

    print(f"[w1-control-live] receipt written: {out_path}")
    print(f"[w1-control-live] outcome={receipt['outcome']} "
          f"is_real_lineage={is_real_lineage} lineage_reasons={lineage_reasons}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    refuse_unless_dry_run_safe(args)

    dry_run = not (args.live and args.device == "cuda")
    device = args.device if not dry_run else "cpu"

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    pricing_receipt = load_json(args.pricing_receipt)
    rung_receipt = (derive_rung_receipt_from_manifest(args.rung_manifest)
                     if args.rung_manifest else load_json(args.rung_receipt))
    real_arch = derive_real_arch_config(pricing_receipt, rung_receipt)

    if not dry_run:
        # REAL LIVE PATH (issue #82) -- only reachable once refuse_unless_
        # dry_run_safe's two independent interlocks both passed. Everything
        # below this point (the ORIGINAL dry-run pipeline) is untouched.
        return main_live(args, ts, pricing_receipt, rung_receipt, real_arch)

    cfg = arch_config_dict(args.vocab, args.hidden, args.depth, args.seq, args.batch)
    cfg_sha = config_sha(cfg)

    eval_x, eval_y, eval_sha = make_eval_batch(args.vocab, args.batch, args.seq, device)

    phase1 = run_phase1_dryrun(
        cfg, train_steps=args.phase1_train_steps, seed=args.phase1_seed,
        device=device, out_dir=os.path.join(args.out_dir, "phase1"),
        eval_x=eval_x, eval_y=eval_y)

    phase2 = run_phase2_dryrun(
        cfg, ceiling_steps=args.ceiling_steps, eval_every=args.eval_every,
        checkpoint_every=args.checkpoint_every,
        target_eval_loss=phase1["target_eval_loss"], seed=args.phase2_seed,
        device=device, out_dir=os.path.join(args.out_dir, "phase2"),
        eval_x=eval_x, eval_y=eval_y, continue_from=args.continue_from)

    assert phase2["config_sha"] == cfg_sha, (
        "W1_ARCH_MISMATCH: control-arm config_sha diverged from the shared "
        "architecture dict -- spec section 2's identical-architecture "
        "requirement violated")

    # W1b (#355): in continuation mode the outcome classifier is priced
    # against the MARGINAL (post-seed) bill, not the cumulative one -- the
    # cumulative figure is carried alongside as context only (w1b_continuation
    # block below), never as the classifying figure (issue's own outcome-
    # semantics framing: "the outcome classifier gets the marginal bill as
    # tokens_growpath when in this mode").
    w1b_continuation = None
    if args.continue_from:
        tokens_growpath_marginal = args.tokens_growpath_marginal
        tokens_growpath_cumulative = (
            args.tokens_growpath_cumulative
            if args.tokens_growpath_cumulative is not None
            else phase1["tokens_total"])
        outcome = classify_outcome(tokens_growpath_marginal, phase2)
        outcome_cumulative = classify_outcome(tokens_growpath_cumulative, phase2)
        w1b_continuation = {
            "issue_ref": W1B_ISSUE_REF,
            "mode": "continuation",
            "continue_from_checkpoint": phase2["continue_from_checkpoint"],
            "continuation_source_manifest_step": phase2["continuation_source_manifest_step"],
            "tokens_growpath_marginal": tokens_growpath_marginal,
            "tokens_growpath_cumulative": tokens_growpath_cumulative,
            "ratio_marginal": outcome["ratio"],
            "outcome_marginal": outcome["outcome"],
            "ratio_cumulative": outcome_cumulative["ratio"],
            "outcome_cumulative": outcome_cumulative["outcome"],
            "note": ("ratio/outcome/lower_bound at the receipt's top level are "
                     "the MARGINAL reading (this run's primary classification, "
                     f"per {W1B_ISSUE_REF}); ratio_cumulative/outcome_cumulative "
                     "above are context only, carried so the pre-registered "
                     "reading rules have both figures."),
        }
    else:
        outcome = classify_outcome(phase1["tokens_total"], phase2)

    eval_trace_path = os.path.join(args.out_dir, f"w1-eval-trace-{ts}.json")
    with open(eval_trace_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(phase2["eval_trace"], f, indent=2)
    eval_trace_sha = sha256_file(eval_trace_path)
    rung_prov = rung_provenance_info(args)

    receipt = {
        "ticket": "W1-COLLAPSE-CONTROL",
        "ts": ts,
        "issue": ISSUE_REF,
        "schema": "w1-collapse-control/v1",
        "spec_ref": f"{SPEC_REF} section 7",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "dry_run": dry_run,
        "is_real_lineage": False if dry_run else True,
        "mode": "cpu_dryrun" if dry_run else "live",
        "device": device,
        "real_lineage_reference": {
            "note": ("informational citation ONLY -- NOT used to compute this "
                     "receipt's ratio/outcome. Real grow-arm token bill and "
                     "bill_aggregation_rows imported verbatim from the pricing "
                     "receipt, with citation, per issue #71's instruction."),
            # issue #361 fix-forward: pricing_receipt_path/rung_provenance_path
            # were written raw with no repo_relative_path call at all (same
            # #357 class as the shard_dir leak, now cured here too).
            "pricing_receipt_path": repo_relative_path(args.pricing_receipt),
            "pricing_receipt_sha256": sha256_file(args.pricing_receipt),
            "rung_provenance_mode": rung_prov["mode"],
            "rung_provenance_path": repo_relative_path(rung_prov["path"]),
            "rung_provenance_sha256": rung_prov["sha256"],
            "grow_arm_terminal_checkpoint_ref": pricing_receipt["grow_arm"]["terminal_checkpoint_ref"],
            "grow_arm_tokens_total": pricing_receipt["grow_arm"]["tokens_total"],
            "grow_arm_bill_aggregation_rows": pricing_receipt["grow_arm"]["bill_aggregation_rows"],
            # NOTE: control_arm.tokens_ceiling in the pricing receipt is a
            # human-readable "2.0 * grow_arm = N" string; the integer lives in
            # wall_hours_pricing.control_arm_ceiling_tokens.
            "control_arm_ceiling_tokens_real": pricing_receipt["wall_hours_pricing"]["control_arm_ceiling_tokens"],
            "control_arm_eval_cadence_K_real": pricing_receipt["control_arm"]["eval_cadence_K"],
            "derived_target_architecture": real_arch,
            "real_hard_ceiling_steps_issue_stated": REAL_HARD_CEILING_STEPS_ISSUE_STATED,
            "real_hard_ceiling_steps_exact_derivation": (
                real_hard_ceiling_derivation(
                    pricing_receipt["wall_hours_pricing"]["control_arm_ceiling_tokens"],
                    real_arch["batch"], real_arch["seq"])),
            "real_hard_ceiling_steps_discrepancy_note": (
                f"issue #71 states 1533; exact arithmetic ceil("
                f"{pricing_receipt['wall_hours_pricing']['control_arm_ceiling_tokens']} / "
                f"({real_arch['batch']}*{real_arch['seq']})) = "
                f"{real_hard_ceiling_derivation(pricing_receipt['wall_hours_pricing']['control_arm_ceiling_tokens'], real_arch['batch'], real_arch['seq'])} "
                "-- 16384*1532 = 25,100,288 exactly, no remainder. One-step "
                "discrepancy flagged, not silently resolved either way; the "
                "maintainer should pick which figure the real run uses."),
        },
        "grow_arm": {
            "terminal_checkpoint_ref": phase1["terminal_checkpoint_ref"],
            "tokens_total": phase1["tokens_total"],
            "bill_aggregation_rows": [{
                "segment": "w1-phase1-dryrun-harness",
                "tokens_computed": f"{phase1['train_steps']} * {args.batch} * {args.seq} = {phase1['tokens_total']}",
                "steps": phase1["train_steps"], "batch": args.batch, "seq": args.seq,
                "tokens_value": phase1["tokens_total"],
                "note": "DRY-RUN toy harness training, not real lineage",
            }],
            "dry_run": True,
            "is_real_lineage": False,
            "init_seed": phase1["init_seed"],
            "loss_first": phase1["loss_first"],
            "loss_last": phase1["loss_last"],
            "wall_s": phase1["wall_s"],
        },
        "control_arm": {
            "config_sha": phase2["config_sha"],
            "init_seed": phase2["init_seed"],
            "init_mode": phase2["init_mode"],
            "continue_from_checkpoint": phase2["continue_from_checkpoint"],
            "continuation_source_manifest_step": phase2["continuation_source_manifest_step"],
            "lr_schedule": phase2["lr_schedule"],
            "tokens_to_match": phase2["tokens_to_match"],
            "tokens_at_ceiling": phase2["tokens_at_ceiling"],
            "eval_trace_ref": eval_trace_path,
            "eval_trace_sha256": eval_trace_sha,
            "eval_cadence_K": phase2["eval_cadence_K"],
            "ceiling_steps": phase2["ceiling_steps"],
            "steps_run": phase2["steps_run"],
            "resume_proof": phase2["resume_proof"],
            "governor": phase2["governor"],
            "pacing": phase2["pacing"],
            "wall_s": phase2["wall_s"],
        },
        "capability_point": {
            "eval_batch_sha256": eval_sha,
            "eval_batch_shape": {"batch": args.batch, "seqlen": args.seq},
            "generator_seed": EVAL_GENERATOR_SEED,
            "target_eval_loss": phase1["target_eval_loss"],
            "dry_run_capability_point": True,
        },
        "w1b_continuation": w1b_continuation,
    }

    # Issue #375: Add continuation_source_verification block if --continue-from was used
    if args.continue_from and phase2.get("continuation_source_manifest"):
        receipt["continuation_source_verification"] = verify_continuation_source_checkpoint(
            args.continue_from, phase2["continuation_source_manifest"])

    # Add remaining receipt fields
    receipt.update({
        "ratio": outcome["ratio"],
        "outcome": outcome["outcome"],
        "lower_bound": outcome["lower_bound"],
        "seeds": 1,
        "seed_sensitivity_unmeasured": True,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "pass": True,
        "verdict": (
            "W1_CONTROL_DRYRUN_PIPELINE_PROVEN" if dry_run
            else "W1_CONTROL_LIVE_COMPLETE"),
        "note": (
            "CPU dry-run: proves the two-phase pipeline (capability-point "
            "leg, control leg with early-stop/ceiling/resume, outcome "
            "classification) end-to-end on a toy architecture. Carries NO "
            "physical claim about the real W1 collapse ratio -- that is the "
            "real GPU run's job (maintainer-window-scheduled, issue #53)."
            if dry_run else ""),
    })

    # issue #361 fix-forward: dry-run receipts default under scratch/, never
    # the canonical receipts/ tree -- a launch lane's own dry-run smoke test
    # previously landed a toy-fixture receipt in receipts/ember-c-scale/.
    # --receipts-out-dir overrides explicitly; --live is unaffected (see
    # main_live's own unconditional receipts/ember-c-scale/ write, below).
    receipts_dir = (args.receipts_out_dir if args.receipts_out_dir
                     else os.path.join(REPO, "scratch", "w1-control", "receipts"))
    os.makedirs(receipts_dir, exist_ok=True)
    out_path = os.path.join(receipts_dir, f"w1-collapse-control-{ts}.json")
    checked_write(out_path, receipt)

    # BOM-free plain-utf8 round-trip verification (hard requirement).
    with open(out_path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "W1_RECEIPT_HAS_BOM"
    with open(out_path, "r", encoding="utf-8") as f:
        json.load(f)  # raises if not plain-utf8-parseable

    print(f"[w1-control] receipt written: {out_path}")
    print(f"[w1-control] outcome={receipt['outcome']} ratio={receipt['ratio']} "
          f"lower_bound={receipt['lower_bound']} dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
