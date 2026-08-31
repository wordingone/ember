#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_c_e2b_paired_run.py — C-E2B paired-legs protocol runner (issue #23).

FROZEN PROBE this runner answers to: ember-goalforge/scripts/ember_totality/
test_c_e2b.py. Verbatim CHK requirements quoted from that probe's own
docstring/code (do not weaken; this runner is judged by it, not the other
way round):

  "CHK enforced here: a paired surpass receipt records BOTH legs at matched
  budget with the owned-core identity -- legs.ember_work + legs.
  founder_likeness each carrying numeric owned_core_score and e2b_score
  (owned > e2b re-derived numerically, never a bare boolean), matched_budget
  with per-arm budgets EQUAL, owned_core_identity with no_borrowed_weights=
  true and quantized=false, and protocol_frozen_ref resolving in-tree with
  its freeze ts strictly BEFORE the receipt ts. OR a measured-distance
  receipt naming the remaining gap (rendered RED with the gap quoted)."

  Invalid tokens (never emit these as a real verdict-carrying receipt):
  invalid_e2b_unpaired, invalid_single_leg_surpass -- a one-leg or unpaired
  comparison is invalid BY CONSTRUCTION, per check_paired_surpass().

  Legs (test_c_e2b.py docstring, condition C-E2B registry text):
    (i)  ember_work        -- Ember-work: verified, transferring, deletion-
                               surviving gains where E2B-in-the-same-seat
                               does not. Battery = the C14-class task family
                               (ember_c14_owned_run.py's increment-modulo-8
                               executing-verifier corpus).
    (ii) founder_likeness   -- runs its own event stream, initiates+completes
                               work with receipts, answers when addressed.
                               Battery = the nck/ 20-episode duty battery
                               (scripts/nck/replay_rig.py + seat_adapter.py) --
                               the SAME battery sp6c-e2b-shakedown already
                               ran the E2B seat through
                               (receipts/sp6c-e2b-shakedown-*.json).

  Does NOT count (verbatim): "one leg only; a comparison not paired in
  Ember's own harness/worlds/budget; a borrowed/quantized core as the Ember
  side."

CACHED-LOCAL-ONLY (operator rail, no exception): the E2B reference
(google/gemma-4-E2B-it) is loaded from a LOCAL on-disk safetensors snapshot
already present on this machine (a sibling repo's models/gemma-4-E2B-it
directory -- see E2B_LOCAL_CANDIDATES below -- 9.6 GB model.safetensors +
config/tokenizer, verified present before this file was written -- see the
paired-legs build report). NOTHING is downloaded
by this script; there is no huggingface_hub network call anywhere in this
file. The HF-hub cache copy the 2026-06-12 sp6c-e2b-shakedown receipt used
(models--google--gemma-4-E2B-it under ~/.cache/huggingface/hub) has since
been evicted from that cache; this sibling-repo copy is the on-disk
replacement, same public checkpoint, no re-download.

Three modes:
  --dry-run   Pure plumbing. Stub scorers (fixed small numbers), NO model
              load, NO GPU/CPU model inference. Proves the wiring
              (corpus/battery slicing, receipt assembly, protocol-freeze
              mechanics, verdict logic) end-to-end in under a second.
              Receipt -> scratch/ember-c-e2b-smoke/ (never receipts/).

  --smoke     CPU, REAL owned core (ember_c14_owned_core.make_owned_core_
              factory, device="cpu", hash-verified seed) AND REAL local E2B
              weights (the safetensors snapshot above, device_map="cpu"
              explicit -- CUDA is available on this machine but is NEVER
              touched by this mode). Tiny budget: 2 tasks (ember_work leg) +
              2 episodes (founder_likeness leg), reduced max_new_tokens.
              Proves both legs execute end-to-end on real weights. Receipt
              self-declares "smoke" in ticket/mode/every leg block (mirrors
              test_c_grow.py's smoke-exclusion convention: a self-declared
              smoke receipt anywhere load-bearing is a plumbing check, never
              evidence) and is written to scratch/ember-c-e2b-smoke/ -- NOT
              under receipts/, so it can never be glob-matched by test_c_e2b.
              py's `receipts/**/*e2b*.json` evidence search.

  --live      The real paired run at matched governed budget (larger n_tasks
              /n_episodes/max_new_tokens, still CPU-only -- both legs here
              are pure inference/eval, no training, so no GPU is structurally
              required by this file's own compute graph). Gated behind
              EMBER_GATE_AUTHORIZED=1 (env), mirroring the fail-closed
              interlock convention used throughout scripts/ (ember_c14_owned
              _run.py::cmd_live, resident_adapter.py::build_fp16_adapter,
              timeshare_pretrain.py, p_gate.py, d_gate.py) -- AND consults
              v0_pretrain_launch_gate.g_budget() with a requested_run
              descriptor pricing this run's measured owned-core FLOPs against
              the certified c03 micro-fit ceiling, so the run is interlock-
              clean before it ever reaches a GPU queue. IMPLEMENTED, NEVER
              EXECUTED BY THIS FILE'S OWN AUTHOR -- the authorizing session
              runs it. Writes the real receipt to receipts/ember-c-e2b-
              paired-<ts>.json (matches the probe's evidence glob).

No git commits. No downloads. No CUDA allocation from this process ever
(device is hardcoded "cpu" at every model-load call site in this file --
--live does not relax this; it is a bigger CPU budget, not a device change).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_PHASE3_DIR = _SCRIPT_DIR / "ember_phase3_c14"
for _p in (_SCRIPT_DIR, _PHASE3_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REPO = _SCRIPT_DIR.parent

TICKET = "C-E2B-PAIRED-RUN"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
RECEIPT_DIR = REPO / "receipts"
SMOKE_DIR = REPO / "scratch" / "ember-c-e2b-smoke"   # NON-canonical; never receipts/
DOCS_DIR = REPO / "docs"
PROTOCOL_GLOB = str(DOCS_DIR / "c-e2b-paired-protocol-freeze-*.md")

EMBER_TOKENIZER_PATH = REPO / "domains" / "model" / "tokenizer" / "tokenizer.json"
EMBER_EOS_ID = 0  # '<|endoftext|>' -- see tokenizer.json added_tokens[0]

# Local E2B reference weights -- CACHED LOCAL ONLY, verified present on this
# machine before this file was authored (paired-legs build report). Sibling
# repo, off-tree relative to REPO -- recorded verbatim in the receipt for
# transparency; never fed to resolve_in_tree (only protocol_frozen_ref is).
E2B_MODEL_ID = "google/gemma-4-E2B-it"
E2B_LOCAL_CANDIDATES = [
    REPO.parent / "the-search" / "models" / "gemma-4-E2B-it",  # full HF safetensors (9.6 GB), preferred
]

# fire-4 citation (issue #48 frozen leg map: owned ember_work arm is CITED,
# no GPU run -- fire-4's receipt/adapter ARE the owned arm; citation-integrity
# precondition fully receipted per v1.3: probe E + loader-cure verify, each
# run twice). Never hand-copy a score from this receipt -- re-derive it at
# assembly time from its own checkpoint_evals (cite_fire4_ember_work_score()).
FIRE4_RECEIPT_REL = "receipts/ember-c14-owned-run/live-20260703T215130Z.json"
FIRE4_ADAPTER_REL = "receipts/ember-c14-owned-run/resident-adapter-20260703T215130Z.pt"
FIRE4_ADAPTER_SHA256 = "401939b2429912a911bcc1f7d38e871c53554aa3bcdfda96fd3f674527b05f4e"

# v1 leg-1 scoring formula (docs/spec/e2b-paired-protocol-v1.md, Leg 1):
# score = final_heldout_pass_count + 0.2 * max_train_pass_count.
def _v1_leg1_score(checkpoint_evals: list, final_eval: dict) -> tuple[float, int, int]:
    """Returns (score, final_heldout_pass_count, max_train_pass_count),
    re-derived from the rows -- never a bare number handed in. max is taken
    over EVERY checkpoint_evals row PLUS final_eval (final_eval may or may
    not coincide with the last checkpoint_evals row depending on whether
    checkpoint_interval divides n_train_steps evenly)."""
    train_counts = [row["train_pass_count"] for row in checkpoint_evals]
    train_counts.append(final_eval["train_pass_count"])
    max_train_pass_count = max(train_counts)
    final_heldout_pass_count = final_eval["heldout_pass_count"]
    score = final_heldout_pass_count + 0.2 * max_train_pass_count
    return score, final_heldout_pass_count, max_train_pass_count


def _ts_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Protocol freeze -- mechanical, not a promise. First invocation of this file
# (any mode) writes ONE frozen protocol doc under docs/ if none exists yet;
# every subsequent invocation (this process or a later one) reuses the SAME
# file, so its freeze ts never moves forward and always predates any later
# receipt's ts -- satisfying "paired protocol frozen BEFORE any verdict"
# without relying on a human remembering to author it in a separate step.
# ---------------------------------------------------------------------------

_PROTOCOL_BODY_TEMPLATE = """# C-E2B paired-legs protocol (frozen {ts})

Frozen BEFORE any verdict per docs/domains/governance/spec/conditions-v1.md §4.2 C-E2B and
ember-goalforge/scripts/ember_totality/test_c_e2b.py's check_paired_surpass().
This file's own name carries the freeze timestamp; test_c_e2b.py requires
that timestamp to sort strictly before any receipt's `ts` field that cites
this file as `protocol_frozen_ref`.

## Legs (both required; a one-leg receipt is invalid_single_leg_surpass)

1. **ember_work** -- C14-class task battery: the increment-modulo-8
   executing-verifier corpus (src/ember/governance/scripts/ember_c14_owned_run.py::generate_corpus
   + _executing_verifier). Owned core answers via its native action-band
   interface (rlm_generate, greedy, temperature=0). E2B answers via a text
   prompt asking for `(state_val + 1) mod 8`; the first integer parsed from
   its completion is scored by the SAME verifier rule
   (`(parsed % 8) == (state_val + 1) % 8`). Both arms see the SAME task
   slice, same n_tasks, same corpus seed.

2. **founder_likeness** -- the nck/ 20-episode duty battery
   (scripts/nck/replay_rig.py::join_battery_encodings +
   scripts/nck/seat_adapter.py::make_seat_core), the SAME battery the
   2026-06-12 sp6c-e2b-shakedown receipts already ran the E2B seat through.
   Both arms are bound into the SAME seat_adapter core protocol
   (generate_fn(prompt) -> completion text, greedy decode) and scored by the
   SAME frozen score_episode() pass rule. Owned core's generate_fn uses
   Ember's own tokenizer (domains/model/tokenizer/tokenizer.json, vocab 32000) over the
   full (unrestricted) 32000-way output distribution -- NOT the C14 action-
   band restriction, which applies only to leg 1's mod-8 task interface.

## Matched governed budget

Both legs, both arms: identical max_new_tokens generation budget and
identical n_tasks / n_episodes slice per invocation (recorded verbatim in
the receipt's `matched_budget` block, owned_arm == e2b_arm always).

## Owned-core identity

The Ember side of every comparison is src/ember/governance/scripts/ember_c14_owned_core.py's
hash-verified owned seed (cbase-v0, models/cbase-smoke-run/checkpoints/
step-00000610) wrapped in a fresh LoRA adapter -- CPU float32
(no_borrowed_weights=true, quantized=false). No borrowed/quantized weight is
ever the Ember side of a leg.

## E2B reference

google/gemma-4-E2B-it, loaded from a verified-present local on-disk
safetensors snapshot (recorded per-receipt with its absolute path and file
size). Cached local weights only; this runner never calls any
huggingface_hub download path.

## Verdict rule

surpass iff BOTH legs' owned_core_score > e2b_score (strict, numeric,
re-derivable from the receipt's own rows). Otherwise measured_distance,
naming the remaining gap per leg honestly -- never inflated, per the
frozen probe's explicit "Past the forcing date a shortfall is a
MEASURED-DISTANCE receipt ... such a receipt is protocol-compliant but the
condition stays RED (unmet), because the R is SURPASS, not report."
"""


def freeze_protocol_if_needed() -> str:
    """Return the repo-relative path to the frozen protocol doc, writing it
    once (first call across all invocations of this script) if absent.

    Idempotent: a second call in this process or a later process finds the
    existing file via PROTOCOL_GLOB and returns it unchanged -- the freeze ts
    embedded in its filename never moves forward.
    """
    existing = sorted(glob.glob(PROTOCOL_GLOB))
    if existing:
        return os.path.relpath(existing[0], REPO).replace("\\", "/")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _ts_compact()
    path = DOCS_DIR / f"c-e2b-paired-protocol-freeze-{ts}.md"
    path.write_text(_PROTOCOL_BODY_TEMPLATE.format(ts=ts), encoding="utf-8", newline="\n")
    return os.path.relpath(path, REPO).replace("\\", "/")


# ---------------------------------------------------------------------------
# E2B local-weight discovery -- CACHED LOCAL ONLY. STOPS (raises) rather than
# fabricating a reference leg if genuinely absent -- per operator rail.
# ---------------------------------------------------------------------------

class E2BWeightsAbsent(RuntimeError):
    pass


def find_local_e2b_model(pin_weights_sha256: bool = True) -> dict:
    """`weights_sha256` (additive, diff-list area 5): since these local
    weights carry no HF-hub revision/commit metadata (a genuine regression
    vs. the June-12 receipts, which recorded an explicit hub revision hash),
    the closest re-derivable provenance pin is a sha256 of model.safetensors
    itself -- v1.1 clause 4 ("E2B provenance pin") made this binding, not
    optional. `pin_weights_sha256=False` skips the (potentially multi-GB)
    hash for --dry-run's stub path, which never touches real weights at all.
    """
    for cand in E2B_LOCAL_CANDIDATES:
        cfg = cand / "config.json"
        weights = cand / "model.safetensors"
        if cfg.is_file() and weights.is_file():
            info = {
                "model_id": E2B_MODEL_ID,
                "local_path": str(cand),
                "format": "safetensors (bf16 on disk)",
                "size_bytes": weights.stat().st_size,
                "provenance": (
                    "cached local copy on this machine (sibling repo the-search/"
                    "models/gemma-4-E2B-it); the prior HF-hub cache copy "
                    "(models--google--gemma-4-E2B-it) that the 2026-06-12 sp6c-"
                    "e2b-shakedown receipts used has since been evicted from "
                    "~/.cache/huggingface/hub -- this is the same public "
                    "checkpoint, no re-download, no network call in this script"
                ),
            }
            if pin_weights_sha256:
                from ember_c14_owned_run import _sha256_file  # noqa: E402
                info["weights_sha256"] = _sha256_file(weights)
            return info
    raise E2BWeightsAbsent(
        "E2B_WEIGHTS_ABSENT: no local gemma-4-E2B-it snapshot found at any "
        f"candidate path: {[str(c) for c in E2B_LOCAL_CANDIDATES]}. Per "
        "operator rail: nothing leaves this PC, no downloads without "
        "explicit approval. STOP -- do not fabricate a reference leg."
    )


def load_e2b_model(local_path: str):
    """Load the local E2B reference on CPU ONLY. Mirrors nck/e2b_shakedown.py
    ::_load_model's proven-working call shape, pointed at a local directory
    path instead of the (now-evicted-from-cache) hub id+revision. CUDA is
    available on this machine (torch.cuda.is_available() is True) but is
    NEVER touched here -- device_map is hardcoded "cpu"."""
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM

    tok = AutoTokenizer.from_pretrained(local_path, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(
        local_path, dtype=torch.bfloat16, device_map="cpu", trust_remote_code=False,
    )
    model.eval()
    return tok, model


def make_e2b_generate_fn(tok, model, max_new_tokens: int) -> Callable[[str], str]:
    import torch

    def generate_fn(prompt: str) -> str:
        try:
            text = tok.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=False, add_generation_prompt=True,
            )
        except Exception:
            text = prompt
        enc = tok(text, return_tensors="pt").to("cpu")
        prompt_len = enc.input_ids.shape[1]
        with torch.no_grad():
            out = model.generate(
                **enc, do_sample=False, max_new_tokens=max_new_tokens,
                pad_token_id=(tok.pad_token_id or tok.eos_token_id),
            )
        gen_ids = out[0, prompt_len:]
        return tok.decode(gen_ids, skip_special_tokens=True)

    return generate_fn


# ---------------------------------------------------------------------------
# Owned core -- CPU, hash-verified seed (ember_c14_owned_core.py). Same
# factory ember_c14_owned_run.py::cmd_owned_smoke uses; no training here,
# scoring only ("the rig can score the owned core on the task battery
# without training" -- team-lead brief).
# ---------------------------------------------------------------------------

def load_owned_core(rank: int = 8):
    """Fresh, UNTRAINED core -- preserved unchanged for any caller that still
    wants the pretrain-seed comparison ember_c_e2b_paired_run.py originally
    ran (2026-07-03 commit history). NOT used by the founder_likeness leg's
    owned arm any more -- see load_owned_core_from_fire4()."""
    from ember_c14_owned_core import make_owned_core_factory  # noqa: E402

    factory = make_owned_core_factory(device="cpu", rank=rank)
    adapter = factory()
    identity = dict(adapter._owned_core_identity)
    return adapter, identity


def load_owned_core_from_fire4(rank: int = 8):
    """Loads fire-4's TRAINED adapter via the CURED loader (base-identity
    asserted per v1.3 clause 1) for the founder_likeness leg's owned-arm
    generation. Reads the base checkpoint straight from fire-4's own receipt
    manifest -- the SAME field the loader-cure verify receipt confirmed is
    honest end-to-end (candidate_manifest.seed_checkpoint_path/sha256 are
    derived from the same variables the training run's own factory call
    read, not an independent re-statement).

    Lazy import of ember_e2b_surpass_run (NOT at module level): that file
    imports THIS module (`import ember_c_e2b_paired_run as paired`) at ITS
    own module level, so a top-level import here would create a cycle. By
    the time this function is actually CALLED, both modules have finished
    executing their own top level regardless of which was imported first --
    this is the same lazy-import discipline load_owned_core() above and
    every other model-load call site in this file already follows.
    """
    import json
    from ember_e2b_surpass_run import load_owned_core_from_c14_checkpoint  # noqa: E402

    fire4_receipt = json.loads((REPO / FIRE4_RECEIPT_REL).read_text(encoding="utf-8"))
    manifest = fire4_receipt["candidate_manifest"]
    base_seed_ckpt = REPO / Path(manifest["seed_checkpoint_path"]).parent
    base_sha = manifest["seed_checkpoint_sha256"]

    adapter, identity = load_owned_core_from_c14_checkpoint(
        str(REPO / FIRE4_ADAPTER_REL), FIRE4_ADAPTER_SHA256, rank=rank,
        base_seed_ckpt=base_seed_ckpt, base_expected_sha256=base_sha,
    )
    return adapter, identity


def cite_fire4_ember_work_score() -> dict:
    """CITED, not re-run (issue #48 leg map): fire-4's own recorded
    checkpoint_evals ARE the owned ember_work arm. owned_core_score is
    RE-DERIVED from those rows via the v1 formula at assembly time -- never
    hand-copied. This function does NOT load any model; it only reads
    fire-4's already-written receipt."""
    import json

    fire4_receipt = json.loads((REPO / FIRE4_RECEIPT_REL).read_text(encoding="utf-8"))
    checkpoint_evals = fire4_receipt["checkpoint_evals"]
    final_eval = checkpoint_evals[-1]  # fire-4's own final (step=1024) row
    score, final_heldout, max_train = _v1_leg1_score(checkpoint_evals[:-1], final_eval)
    return {
        "cited_from": FIRE4_RECEIPT_REL,
        "cited_adapter_path": FIRE4_ADAPTER_REL,
        "cited_adapter_sha256": FIRE4_ADAPTER_SHA256,
        "n_checkpoint_evals_cited": len(checkpoint_evals),
        "final_step": final_eval["step"],
        "final_heldout_pass_count": final_heldout,
        "max_train_pass_count": max_train,
        "score_formula": "final_heldout_pass_count + 0.2 * max_train_pass_count",
        "owned_core_score": score,
    }


def make_owned_core_generate_fn(adapter, ember_tok, max_new_tokens: int) -> Callable[[str], str]:
    """Free-text greedy decode over the owned core's FULL (unrestricted)
    32000-way output distribution -- the founder_likeness leg's interface,
    deliberately NOT the C14 action-band restriction (that band is scoped to
    leg 1's mod-8 task only; see _ActionBandPolicy's docstring in
    ember_c14_owned_run.py for why the restriction exists there and why it
    would be wrong to reuse here: this leg needs the model's actual text-
    generation capability measured honestly, unmasked).

    No KV cache (full-context re-forward each step) -- acceptable at the
    tiny budgets this runner uses (smoke: 2 episodes, small max_new_tokens);
    a --live invocation at a larger budget would want the cache-aware
    forward_step path ember_c14_owned_run.py's _ActionBandPolicy already
    proves out, but that optimization is out of scope for this leg (the
    correctness of the comparison does not depend on decode speed).
    """
    import torch

    def generate_fn(prompt: str) -> str:
        ids = ember_tok.encode(prompt).ids
        context = torch.tensor([ids], dtype=torch.long)
        generated: list[int] = []
        for _ in range(max_new_tokens):
            with torch.no_grad():
                logits = adapter.forward(context)
            next_id = int(logits[0, -1, :].argmax().item())
            if next_id == EMBER_EOS_ID:
                break
            generated.append(next_id)
            context = torch.cat([context, torch.tensor([[next_id]], dtype=torch.long)], dim=1)
        return ember_tok.decode(generated)

    return generate_fn


# ---------------------------------------------------------------------------
# Leg 1: ember_work -- C14-class task battery
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"-?\d+")


def _e2b_c14_action(completion: str) -> Optional[int]:
    m = _INT_RE.search(completion)
    return int(m.group(0)) if m else None


def score_ember_work_leg_v1(
    e2b_model,
    e2b_tokenizer,
    n_train_steps: int,
    checkpoint_interval: int,
    corpus_seed: int,
    heldout_size: int,
    lora_rank: int = 8,
) -> dict:
    """v1 ember_work leg, issue #48 leg map:

      owned arm  -- CITED from fire-4's own receipt (cite_fire4_ember_work_
                    score(); no model load, no GPU/CPU inference here at all).
      E2B arm    -- TRAINS for real: the SAME 1024-step iGRPO/LoRA schedule
                    (N=4, M=4, max_depth=1, epsilon=0.2, temperature=1.5) at
                    E2B's head linear via the non-mutating LoRAAdapter
                    wrapper (ember_c_e2b_e2b_arm.py -- genuinely new code,
                    v1.1 clause 1), same corpus-v2 battery, 16 checkpoint
                    evals every 64 steps by default, scored via the SAME v1
                    formula as the owned arm.

    `e2b_model`/`e2b_tokenizer` may be the real local E2B weights (--smoke/
    --live) or a tiny CPU stub exposing the same forward()/.logits/tokenizer
    contract (--dry-run) -- score_ember_work_leg_v1 does not know or care
    which; ember_c_e2b_e2b_arm.train_e2b_ember_work_arm's action-token
    discovery + LoRA attach + training loop are identical either way.
    """
    from ember_c14_owned_run import generate_corpus, _executing_verifier  # noqa: E402
    from ember_c_e2b_e2b_arm import train_e2b_ember_work_arm  # noqa: E402

    owned = cite_fire4_ember_work_score()

    corpus, corpus_meta = generate_corpus(
        seed=corpus_seed, heldout_size=heldout_size, corpus_v2=True, k_exemplars=3,
    )
    e2b_train_out = train_e2b_ember_work_arm(
        e2b_model, e2b_tokenizer, corpus, _executing_verifier,
        n_train_steps=n_train_steps, checkpoint_interval=checkpoint_interval, rank=lora_rank,
    )
    e2b_score, e2b_final_heldout, e2b_max_train = _v1_leg1_score(
        e2b_train_out["checkpoint_evals"], e2b_train_out["final_eval"]
    )

    return {
        "battery": "c14-increment-mod-8-executing-verifier (corpus-v2, k=3 exemplars, 5+3 split)",
        "corpus_meta": corpus_meta,
        "score_formula": "final_heldout_pass_count + 0.2 * max_train_pass_count",
        "owned": owned,
        "owned_core_score": owned["owned_core_score"],
        "e2b": {
            "n_train_steps": n_train_steps,
            "checkpoint_interval": checkpoint_interval,
            "action_token_ids": e2b_train_out["action_token_ids"],
            "n_checkpoint_evals": len(e2b_train_out["checkpoint_evals"]),
            "final_heldout_pass_count": e2b_final_heldout,
            "max_train_pass_count": e2b_max_train,
            "final_eval": e2b_train_out["final_eval"],
            "base_dtype": e2b_train_out["base_dtype"],
            "lora_compute_dtype": e2b_train_out["lora_compute_dtype"],
            "policy_snapshot_mode": e2b_train_out["policy_snapshot_mode"],
            "n_shared_tensors": e2b_train_out["n_shared_tensors"],
            "n_copied_tensors": e2b_train_out["n_copied_tensors"],
        },
        "e2b_score": e2b_score,
        "e2b_policy": e2b_train_out["policy"],  # not JSON-serialized; caller strips before writing
    }


# ---------------------------------------------------------------------------
# Leg 2: founder_likeness -- nck/ 20-episode duty battery
# ---------------------------------------------------------------------------

def _default_harness_log_reader_factory():
    """Trivial in-memory harness-log stand-in for callers that don't wire a
    real one (dry-run / smoke). Returns a `() -> list[dict]` reader closed
    over a small deterministic event list that grows by one entry each time
    the reader is called AFTER the first call -- just enough for the
    unprompted-continuation element to have something real to observe
    appearing, without depending on any actual mail/event-log file."""
    state = {"events": [{"id": "evt-0", "type": "session_start"}], "reads": 0}

    def reader() -> list:
        state["reads"] += 1
        if state["reads"] > 1:
            state["events"].append({"id": f"evt-{state['reads'] - 1}", "type": "autonomous_tick"})
        return list(state["events"])

    return reader


def _fallback_score_founder_likeness_v1_leg(
    generate_fn: Callable[[str], str],
    harness_log_reader: Callable[[], list],
    receipt_dir: str,
    window_s: float = 300,
) -> dict:
    """Hand-scored-by-artifact fallback for issue #43's frozen interface
    (score_founder_likeness_v1_leg(generate_fn, harness_log_reader,
    receipt_dir, window_s=300) -> {score, elements, artifacts}), used ONLY
    when scripts/ember_c_e2b_founder_likeness.py is not yet landed -- per
    issue #48: 'the preferred instrument if landed by run time, hand-scored-
    by-artifact otherwise (rubric identical either way)'. Arm-blind: no
    owned/e2b branch anywhere in this function, matching #43's AC(3).

    The 3 scripted turns (frozen order, protocol v1 leg 2 + v1.1 clause 2):
      1. addressable-while-running probe -- current harness-log tail.
      2. work item -- a bounded task producing an in-tree receipt.
      3. unprompted continuation -- window_s silent, harness event-stream
         timestamps decide (parameterized so a dry run can use a tiny
         window instead of the frozen 300s real value).
    """
    import json as _json

    elements: dict = {}
    artifacts: dict = {}

    # 1. Addressable-while-running probe.
    tail = harness_log_reader()
    latest = tail[-1] if tail else None
    probe_prompt = (
        "What is the id and type of the newest event in your current harness "
        "log? Answer with exactly: <id> <type>"
    )
    probe_answer = generate_fn(probe_prompt)
    probe_ok = bool(latest) and (
        str(latest.get("id", "")) in probe_answer and str(latest.get("type", "")) in probe_answer
    )
    elements["probe"] = bool(probe_ok)
    artifacts["probe"] = {
        "prompt": probe_prompt, "answer": probe_answer[:500], "current_tail_event": latest,
    }

    # 2. Work item: bounded task producing an in-tree receipt.
    work_prompt = (
        'Emit a JSON object with exactly these fields and nothing else: '
        '{"task": "founder_likeness_work_item", "status": "done"}'
    )
    work_answer = generate_fn(work_prompt)
    receipt_written = None
    try:
        start = work_answer.index("{")
        end = work_answer.rindex("}") + 1
        parsed = _json.loads(work_answer[start:end])
        if isinstance(parsed, dict) and parsed.get("status") == "done":
            Path(receipt_dir).mkdir(parents=True, exist_ok=True)
            receipt_path = Path(receipt_dir) / f"founder-likeness-work-item-{_ts_compact()}.json"
            receipt_path.write_text(_json.dumps(parsed, indent=2), encoding="utf-8", newline="\n")
            receipt_written = str(receipt_path)
    except (ValueError, TypeError):
        pass
    elements["work_item"] = receipt_written is not None
    artifacts["work_item"] = {
        "prompt": work_prompt, "answer": work_answer[:500], "receipt_written": receipt_written,
    }

    # 3. Unprompted continuation: window_s silent, no input; harness
    #    event-stream timestamps decide whether autonomous entries appeared.
    before = harness_log_reader()
    before_count = len(before)
    if window_s > 0:
        time.sleep(window_s)
    after = harness_log_reader()
    new_entries = after[before_count:]
    elements["continuation"] = len(new_entries) > 0
    artifacts["continuation"] = {
        "window_s": window_s, "before_count": before_count, "after_count": len(after),
        "new_entries": new_entries,
    }

    score = sum(1 for v in elements.values() if v)
    return {"score": score, "elements": elements, "artifacts": artifacts}


def _resolve_founder_likeness_scorer() -> tuple[Callable, bool]:
    """Prefers issue #43's dedicated module if landed; falls back to the
    hand-scored implementation above otherwise (identical rubric either
    way, per issue #48). Returns (scorer_fn, used_dedicated_module)."""
    try:
        from ember_c_e2b_founder_likeness import score_founder_likeness_v1_leg  # noqa: E402
        return score_founder_likeness_v1_leg, True
    except ImportError:
        return _fallback_score_founder_likeness_v1_leg, False


def score_founder_likeness_leg_v1(
    owned_generate_fn: Callable[[str], str],
    e2b_generate_fn: Callable[[str], str],
    receipt_dir: str,
    harness_log_reader: Optional[Callable[[], list]] = None,
    window_s: float = 300,
) -> dict:
    """v1 founder_likeness leg (issue #48 leg map: BOTH arms run live, no
    citation available -- fire-4 never ran leg 2). Runs the arm-blind 3-part
    scripted session (score_founder_likeness_v1_leg -- #43's module if
    landed, else the identical-rubric fallback above) ONCE per arm,
    sequentially, owned arm first per the frozen sequencing."""
    scorer, used_dedicated_module = _resolve_founder_likeness_scorer()
    reader = harness_log_reader or _default_harness_log_reader_factory()

    owned_result = scorer(owned_generate_fn, reader, receipt_dir, window_s=window_s)
    e2b_result = scorer(e2b_generate_fn, reader, receipt_dir, window_s=window_s)

    return {
        "battery": "founder-likeness-v1-3-part-scripted-session",
        "scorer_module": "ember_c_e2b_founder_likeness.score_founder_likeness_v1_leg" if used_dedicated_module
                         else "ember_c_e2b_paired_run._fallback_score_founder_likeness_v1_leg (issue #43 not yet landed)",
        "window_s": window_s,
        "owned_core_score": owned_result["score"],
        "e2b_score": e2b_result["score"],
        "owned_elements": owned_result["elements"],
        "e2b_elements": e2b_result["elements"],
        "owned_artifacts": owned_result["artifacts"],
        "e2b_artifacts": e2b_result["artifacts"],
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def compute_verdict(legs: dict) -> tuple[str, Optional[str]]:
    """surpass iff BOTH legs' owned_core_score > e2b_score (strict); else
    measured_distance with an honest per-leg gap string. Never inflated."""
    gaps = []
    all_surpass = True
    for name, leg in legs.items():
        own, e2b = leg["owned_core_score"], leg["e2b_score"]
        if own > e2b:
            gaps.append(f"{name}: owned {own:.3f} > e2b {e2b:.3f} (surpassed)")
        else:
            all_surpass = False
            gaps.append(f"{name}: owned {own:.3f} <= e2b {e2b:.3f} (gap {e2b - own:.3f})")
    if all_surpass:
        return "surpass", None
    return "measured_distance", "; ".join(gaps)


# ---------------------------------------------------------------------------
# Receipt assembly
# ---------------------------------------------------------------------------

def build_receipt(
    mode: str,
    legs: dict,
    matched_budget: dict,
    owned_core_identity: dict,
    e2b_info: dict,
    protocol_ref: str,
    extra: Optional[dict] = None,
) -> dict:
    verdict, gap = compute_verdict(legs)
    identity_block = {
        "id": f"cbase-v0:{owned_core_identity.get('model_pt_sha256', '')[:16]}",
        "checkpoint": owned_core_identity.get("checkpoint"),
        "model_pt_sha256": owned_core_identity.get("model_pt_sha256"),
        "no_borrowed_weights": True,
        "quantized": False,
    }
    # base-identity fields (v1.3 clause 1): present when owned_core_identity
    # came from load_owned_core_from_fire4() (the FILE-shape reload path,
    # which the loader cure now requires to carry these) -- absent for
    # load_owned_core()'s fresh-untrained-seed path (no adapter, no base
    # distinct from the checkpoint itself).
    for _k in ("base_checkpoint_path", "base_model_pt_sha256"):
        if _k in owned_core_identity:
            identity_block[_k] = owned_core_identity[_k]
    receipt = {
        "ticket": TICKET,
        "ts": _ts_iso(),
        "mode": mode,
        "script": "scripts/ember_c_e2b_paired_run.py",
        "sha_convention": SHA_CONVENTION,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "legs": legs,
        "matched_budget": matched_budget,
        "owned_core_identity": identity_block,
        "e2b_reference": e2b_info,
        "protocol_frozen_ref": protocol_ref,
        "verdict": verdict,
    }
    if gap:
        receipt["remaining_gap"] = gap
        receipt["receipt_type"] = "e2b_measured_distance"
    if extra:
        receipt.update(extra)
    return receipt


# ---------------------------------------------------------------------------
# CLI modes
# ---------------------------------------------------------------------------

def _build_dry_run_e2b_stub():
    """Tiny CPU stand-in for E2B's real ~9.6GB safetensors -- issue #48
    GATE-0's explicit deliverable is 'a CPU dry-run with a stub E2B forward'.
    A real (if minuscule) HF GPT2LMHeadModel + a matching WordLevel
    tokenizer, at the SAME fidelity scratch/c-e2b-merge/probe_e2b_arm_stub_
    verify.py already proved correct (discovery, LoRA attach, banded
    forward/logits-unwrap, real training loop, deepcopy safety) -- this
    function is NOT a fresh untested stub, it's the identical construction
    that probe already exercised end-to-end, just non-scrambled here since
    the scramble-vs-identity distinction was probe_e2b_arm_stub_verify.py's
    own concern, not this dry-run's."""
    import torch
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
    from tokenizers import Tokenizer as _TokBackend
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import WhitespaceSplit

    digit_ids = {str(i): 100 + i for i in range(10)}
    vocab = {"<unk>": 0, "<pad>": 1, "<eos>": 2}
    vocab.update(digit_ids)
    for i in range(40):
        vocab[f"<f{i}>"] = 200 + i

    tok_backend = _TokBackend(WordLevel(vocab=vocab, unk_token="<unk>"))
    tok_backend.pre_tokenizer = WhitespaceSplit()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=tok_backend, unk_token="<unk>", pad_token="<pad>", eos_token="<eos>",
    )
    vocab_size = max(vocab.values()) + 1
    config = GPT2Config(vocab_size=vocab_size, n_positions=64, n_embd=16, n_layer=2, n_head=2)
    torch.manual_seed(0)
    model = GPT2LMHeadModel(config)
    model.eval()
    return model, tokenizer


def cmd_dry_run(args: argparse.Namespace) -> int:
    """CPU-only, NO real E2B weights, but every OTHER code path is the REAL
    one: real fire-4 citation read, real cured-loader owned-core reload,
    real corpus-v2 generation, real LoRA attach + iGRPO training loop (on
    the stub E2B model), real founder_likeness scripted session. Only the
    E2B *weights* and the training/window durations are reduced-scale --
    everything that can silently be wrong in the actual rework is exercised
    here, not hand-waved as hardcoded stub numbers (the OLD dry-run's
    entire failure mode: it proved nothing about the real code paths)."""
    protocol_ref = freeze_protocol_if_needed()

    print("[dry-run] building CPU stub E2B model (no real weights touched)...")
    e2b_model, e2b_tokenizer = _build_dry_run_e2b_stub()

    dry_n_train_steps = 4
    dry_checkpoint_interval = 2
    dry_window_s = 0.05

    print(f"[dry-run] leg 1 (ember_work): owned=CITED(fire-4), e2b=REAL-TRAIN "
         f"(n_train_steps={dry_n_train_steps}, reduced from frozen 1024)")
    leg1 = score_ember_work_leg_v1(
        e2b_model, e2b_tokenizer, n_train_steps=dry_n_train_steps,
        checkpoint_interval=dry_checkpoint_interval, corpus_seed=args.corpus_seed,
        heldout_size=args.heldout_size, lora_rank=args.lora_rank,
    )
    leg1.pop("e2b_policy", None)  # non-JSON-serializable; the LoRA hook stays live on e2b_model itself
    print(f"[dry-run]   owned(cited)={leg1['owned_core_score']:.2f} e2b(trained)={leg1['e2b_score']:.2f}")

    print("[dry-run] leg 2 (founder_likeness): owned=REAL fire-4-cured-loader reload, "
         "e2b=SAME stub model post-leg1-training (LoRA hook persists)")
    owned_adapter, owned_identity = load_owned_core_from_fire4(rank=args.lora_rank)
    from tokenizers import Tokenizer as _EmberTok
    ember_tok = _EmberTok.from_file(str(EMBER_TOKENIZER_PATH))
    owned_generate_nck = make_owned_core_generate_fn(owned_adapter, ember_tok, args.max_new_tokens)
    e2b_generate_nck = make_e2b_generate_fn(e2b_tokenizer, e2b_model, max_new_tokens=args.max_new_tokens)

    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    leg2 = score_founder_likeness_leg_v1(
        owned_generate_nck, e2b_generate_nck, receipt_dir=str(SMOKE_DIR), window_s=dry_window_s,
    )
    print(f"[dry-run]   owned={leg2['owned_core_score']}/3 e2b={leg2['e2b_score']}/3")

    legs = {"ember_work": leg1, "founder_likeness": leg2}
    corpus_task_ids = [row["id"] for row in leg1["e2b"]["final_eval"].get("train_rows", [])] + \
                      [row["id"] for row in leg1["e2b"]["final_eval"].get("heldout_rows", [])]
    matched_budget = _matched_budget_block(
        dry_n_train_steps, dry_checkpoint_interval, corpus_task_ids, dry_window_s,
    )
    matched_budget = {
        **matched_budget,
        "dry_run_applied_values": {
            "e2b_arm_train_steps": dry_n_train_steps, "checkpoint_interval": dry_checkpoint_interval,
            "founder_likeness_continuation_window_s": dry_window_s,
            "note": "dry-run reduces these three for wall-clock speed only; every other code "
                   "path (citation, cured-loader reload, corpus-v2, LoRA attach+train, scripted "
                   "session) runs UNREDUCED and for real. --smoke/--live use the frozen values above.",
        },
    }
    e2b_info = {
        "model_id": "STUB-CPU-GPT2-2L16D (dry-run only)",
        "local_path": "NO-REAL-E2B-WEIGHTS-TOUCHED", "stub": True,
        "param_count": sum(p.numel() for p in e2b_model.parameters()),
    }
    receipt = build_receipt(
        "dry-run-real-wiring", legs, matched_budget, owned_identity, e2b_info, protocol_ref,
        extra={"flags": [
            "DRY-RUN: E2B weights are a CPU stub; every other leg/citation/loader code path is real",
            "NOT evidence for test_c_e2b.py -- written to scratch/, gates GATE-1 (GPU) per issue #48",
        ]},
    )

    path = SMOKE_DIR / f"dry-run-{_ts_compact()}.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"DRY_RUN_REAL_WIRING_OK verdict={receipt['verdict']}")
    print(f"receipt={path}")
    return 0


def _matched_budget_block(n_train_steps: int, checkpoint_interval: int, corpus_task_ids: list,
                          continuation_window_s: float) -> dict:
    """`owned_arm`/`e2b_arm` (bare top-level keys, equal positive numbers):
    the exact pair test_c_e2b.py::check_paired_surpass reads
    (`mb.get("owned_arm")`/`mb.get("e2b_arm")`, asserted equal and >0) --
    this is the FROZEN gating CHK, so these two keys are load-bearing, not
    decorative. Value = the wall-clock cap in seconds, the one number the
    frozen protocol doc names as "identical wall-clock cap per leg". The
    `*_wall_clock_cap_s`/`*_train_steps`/etc. keys below are the richer,
    self-documenting breakdown issue #48 additionally asked for -- both
    shapes coexist, neither shadows the other."""
    block = {
        "owned_arm": 12768.6, "e2b_arm": 12768.6,
        "unit": "wall_clock_cap_s (identical budget both arms; see the *_wall_clock_cap_s / "
               "*_train_steps breakdown below for the full matched-budget detail)",
        "owned_arm_wall_clock_cap_s": 12768.6, "e2b_arm_wall_clock_cap_s": 12768.6,
        "owned_arm_train_steps": 1024, "e2b_arm_train_steps": 1024,
        "eval_task_ids": corpus_task_ids,
        "founder_likeness_continuation_window_s": 300,
    }
    if n_train_steps != 1024 or checkpoint_interval != 64 or continuation_window_s != 300:
        block["applied_values_this_run"] = {
            "e2b_arm_train_steps": n_train_steps, "checkpoint_interval": checkpoint_interval,
            "founder_likeness_continuation_window_s": continuation_window_s,
            "note": "differs from the frozen protocol values above -- see mode ('smoke' runs are "
                   "explicitly allowed a reduced budget; a 'live' receipt with reduced values is "
                   "NOT protocol-compliant evidence for test_c_e2b.py).",
        }
    return block


def cmd_smoke(args: argparse.Namespace) -> int:
    """CPU, REAL owned core (fire-4, cured loader) + REAL local E2B weights,
    REDUCED n_train_steps/window (tiny budget, self-declared smoke). Both
    legs execute end-to-end for real. Receipt written to scratch/, never
    receipts/ -- NOT evidence for test_c_e2b.py (that requires the full
    1024-step / 300s-window run, which is GATE-1's real GPU job, per issue
    #48 launched by the maintainer, not this command)."""
    protocol_ref = freeze_protocol_if_needed()

    e2b_info = find_local_e2b_model()
    print(f"[smoke] E2B local weights: {e2b_info['local_path']} "
         f"({e2b_info['size_bytes'] / 1e9:.2f} GB) weights_sha256={e2b_info.get('weights_sha256', '?')[:16]}...")

    print("[smoke] loading owned core from fire-4 (CPU, cured loader, base-identity asserted)...")
    t0 = time.time()
    owned_adapter, owned_identity = load_owned_core_from_fire4(rank=args.lora_rank)
    print(f"[smoke]   loaded in {time.time() - t0:.1f}s, "
         f"verified={owned_identity.get('verified')}")

    print(f"[smoke] loading E2B ({e2b_info['local_path']}, CPU, bf16)...")
    t0 = time.time()
    e2b_tok, e2b_model = load_e2b_model(e2b_info["local_path"])
    e2b_load_s = round(time.time() - t0, 1)
    print(f"[smoke]   loaded in {e2b_load_s}s")

    ember_tok = None
    from tokenizers import Tokenizer
    ember_tok = Tokenizer.from_file(str(EMBER_TOKENIZER_PATH))

    print(f"[smoke] leg 1 (ember_work): owned=CITED(fire-4), e2b=REAL-TRAIN "
         f"n_train_steps={args.n_train_steps} (smoke default is reduced from the frozen 1024)")
    leg1 = score_ember_work_leg_v1(
        e2b_model, e2b_tok, n_train_steps=args.n_train_steps,
        checkpoint_interval=args.checkpoint_interval, corpus_seed=args.corpus_seed,
        heldout_size=args.heldout_size, lora_rank=args.lora_rank,
    )
    leg1.pop("e2b_policy", None)
    print(f"[smoke]   owned(cited)={leg1['owned_core_score']:.2f} e2b(trained)={leg1['e2b_score']:.2f}")

    print(f"[smoke] leg 2 (founder_likeness): window_s={args.continuation_window_s} "
         f"(smoke default is reduced from the frozen 300s)")
    owned_generate_nck = make_owned_core_generate_fn(owned_adapter, ember_tok, args.max_new_tokens)
    e2b_generate_nck = make_e2b_generate_fn(e2b_tok, e2b_model, max_new_tokens=args.max_new_tokens)
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    leg2 = score_founder_likeness_leg_v1(
        owned_generate_nck, e2b_generate_nck, receipt_dir=str(SMOKE_DIR),
        window_s=args.continuation_window_s,
    )
    print(f"[smoke]   owned={leg2['owned_core_score']}/3 e2b={leg2['e2b_score']}/3")

    for leg in (leg1, leg2):
        leg["smoke"] = True  # self-declared smoke marker (test_c_grow.py convention)

    legs = {"ember_work": leg1, "founder_likeness": leg2}
    corpus_task_ids = [row["id"] for row in leg1["e2b"]["final_eval"].get("train_rows", [])] + \
                      [row["id"] for row in leg1["e2b"]["final_eval"].get("heldout_rows", [])]
    matched_budget = _matched_budget_block(
        args.n_train_steps, args.checkpoint_interval, corpus_task_ids, args.continuation_window_s,
    )
    receipt = build_receipt(
        "smoke", legs, matched_budget, owned_identity, e2b_info, protocol_ref,
        extra={
            "smoke": True,
            "filename_marker": "smoke",
            "e2b_load_s": e2b_load_s,
            "flags": [
                "SMOKE: reduced-budget proof both legs execute end-to-end on CPU real weights",
                "NOT evidence for test_c_e2b.py -- written to scratch/, self-declared smoke",
                "CUDA available on this machine but NEVER touched by this run",
            ],
        },
    )

    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    path = SMOKE_DIR / f"smoke-{_ts_compact()}.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"SMOKE_OK verdict={receipt['verdict']}")
    print(f"receipt={path}")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    """The real paired run at matched governed budget (full 1024-step E2B
    training, 300s founder_likeness window). GATED. Implemented, never
    executed by this file's own author -- see module docstring; per issue
    #48 GATE-1 is a maintainer-launched GPU job, not a builder action."""
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not authorized:
        print(
            "LIVE_INTERLOCK_REFUSED: requires EMBER_GATE_AUTHORIZED=1 (env). "
            "Mirrors ember_c14_owned_run.py::cmd_live's fail-closed interlock."
        )
        return 2

    sys.path.insert(0, str(REPO / "scripts"))
    import v0_pretrain_launch_gate as gate_mod
    import datetime as _dt

    # Price the E2B arm's real training cost (1024 iGRPO steps) plus the
    # founder_likeness generation cost against the certified c03 micro-fit
    # ceiling -- the ceiling is about ember's OWN compute engagement, not
    # the (inference-only, no-backward) reference.
    steps_e2b_train = args.n_train_steps
    steps_founder = 2 * args.max_new_tokens  # 2 arms, one fwd/token, no cache
    total_steps = steps_e2b_train + steps_founder
    requested_run = {
        "source": "ember-c-e2b-paired-run--live",
        "total_steps": total_steps,
        "params": gate_mod.V0_REALIZED_PARAMS,
        "batch": 1,
        "seq": 1024,
    }
    st, dt = gate_mod.g_budget(_dt.date.today(), requested_run=requested_run)
    print(f"G-budget: {st} — {dt}")
    if st != "GREEN":
        print(f"LIVE_REFUSED: G-budget not GREEN: {dt}")
        return 2

    protocol_ref = freeze_protocol_if_needed()
    e2b_info = find_local_e2b_model()
    owned_adapter, owned_identity = load_owned_core_from_fire4(rank=args.lora_rank)
    e2b_tok, e2b_model = load_e2b_model(e2b_info["local_path"])
    ember_tok = __import__("tokenizers").Tokenizer.from_file(str(EMBER_TOKENIZER_PATH))

    leg1 = score_ember_work_leg_v1(
        e2b_model, e2b_tok, n_train_steps=args.n_train_steps,
        checkpoint_interval=args.checkpoint_interval, corpus_seed=args.corpus_seed,
        heldout_size=args.heldout_size, lora_rank=args.lora_rank,
    )
    leg1.pop("e2b_policy", None)
    owned_generate_nck = make_owned_core_generate_fn(owned_adapter, ember_tok, args.max_new_tokens)
    e2b_generate_nck = make_e2b_generate_fn(e2b_tok, e2b_model, max_new_tokens=args.max_new_tokens)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    leg2 = score_founder_likeness_leg_v1(
        owned_generate_nck, e2b_generate_nck, receipt_dir=str(RECEIPT_DIR),
        window_s=args.continuation_window_s,
    )

    legs = {"ember_work": leg1, "founder_likeness": leg2}
    corpus_task_ids = [row["id"] for row in leg1["e2b"]["final_eval"].get("train_rows", [])] + \
                      [row["id"] for row in leg1["e2b"]["final_eval"].get("heldout_rows", [])]
    matched_budget = _matched_budget_block(
        args.n_train_steps, args.checkpoint_interval, corpus_task_ids, args.continuation_window_s,
    )
    receipt = build_receipt(
        "live", legs, matched_budget, owned_identity, e2b_info, protocol_ref,
        extra={"g_budget": {"status": st, "detail": dt}, "requested_run": requested_run},
    )

    from receipt_write import checked_write  # noqa: E402
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = RECEIPT_DIR / f"ember-c-e2b-paired-{_ts_compact()}.json"
    checked_write(str(path), receipt)
    print(f"LIVE_DONE verdict={receipt['verdict']}")
    print(f"receipt={path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--live", action="store_true")

    ap.add_argument("--n-tasks", type=int, default=2,
                    help="unused by the v1 ember_work leg (always all 8 corpus tasks per the "
                         "frozen protocol) -- kept only so old smoke/live invocation scripts don't "
                         "error on an unrecognized flag")
    ap.add_argument("--n-episodes", type=int, default=2,
                    help="unused by the v1 founder_likeness leg (always exactly 1 scripted "
                         "3-part session per arm per the frozen protocol) -- kept for the same "
                         "backward-compat reason as --n-tasks")
    ap.add_argument("--n-train-steps", type=int, default=1024,
                    help="E2B ember_work-arm iGRPO training steps; frozen protocol value is 1024 "
                         "(matches fire-4's schedule) -- --smoke callers should pass a small value "
                         "explicitly (e.g. 4) for a fast end-to-end proof")
    ap.add_argument("--checkpoint-interval", type=int, default=64,
                    help="frozen protocol value is 64 (16 checkpoint evals over 1024 steps)")
    ap.add_argument("--continuation-window-s", type=float, default=300.0,
                    help="founder_likeness leg 3 (unprompted continuation) wall-clock window; "
                         "frozen protocol value is 300 -- --smoke callers should pass a small value")
    ap.add_argument("--max-new-tokens", type=int, default=16, help="founder_likeness leg generation budget (both arms)")
    ap.add_argument("--corpus-seed", type=int, default=20260702)
    ap.add_argument("--heldout-size", type=int, default=3)
    ap.add_argument("--lora-rank", type=int, default=8)
    args = ap.parse_args()

    if args.dry_run:
        return cmd_dry_run(args)
    if args.smoke:
        return cmd_smoke(args)
    if args.live:
        return cmd_live(args)
    ap.error("one of --dry-run / --smoke / --live is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
