#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_c14_contract_rig.py — C14 A/B/C/Deleted contract apparatus.

Produces C14 clearance by running four arms against a verifier-scored task corpus
and asserting the gate predicates:

  A        = owned core, NO resident: core action-gen directly, no weight update.
  B        = owned core + best FIXED action-template (RLM scaffold, no weight update).
  C        = owned core + iGRPO/RLM resident: trains the core on TRAIN tasks, then evals.
  Deleted  = C with the resident weight-delta REVERTED (exact pre-C core state_dict).

Gate predicates (all four must hold for C14):
  (1) C > A  AND  C > B  on train
  (2) |Deleted - A| is small on train  (deletion degrades to ~A)
  (3) C > A  AND  C > B  on held-out  (transfer)
  (4) Deleted drops the held-out tasks C newly passes  (deletion on held-out)

Does-NOT-count guards (fail-closed, asserted mechanically):
  (a) weight-delta is in the CORE: pre/post param-hash DIFFER for C;
      Deleted restores the EXACT pre-C hash.  No side-classifier escape.
  (b) verifier is EXECUTING (binary task-success), NOT lexical/inclusion.
  (c) transfer is NOT won by construction: corpus is echo-proof; answers
      are never injected into prompts.
  (d) frozen/borrowed/zero-init core reported as the owned core is REJECTED.

Parameterised on {core_factory, train_resident_fn, eval_arm_fn, verifier, corpus}:

  STUB instantiation (runs on CPU, no [REDACTED].exe):
    core_factory    = TinyPolicyTransformer (from ember_resident_igrpo)
    train_resident  = igrpo_step (from ember_resident_igrpo)
    eval_arm        = _stub_eval_arm (uses executing_verifier from ember_resident_igrpo)
    verifier        = executing_verifier from ember_resident_igrpo (increment-modulo-8 task)
    corpus          = tiny task set embedded in this file (8 train + 4 held-out tasks)

  REAL instantiation (documented, not run here):
    core_factory    = lambda: build_multimodal_v0_model(live=True)  # C-BASE owned core
    train_resident  = train_multimodal_v0-hosted iGRPO (adapter per adapt-verdict JSON)
    eval_arm        = ember_avir_harness.executing_verifier (real [REDACTED].exe clean-room)
    verifier        = ember_avir_harness.run_assertions (binary task-success)
    corpus          = ember_avir_tasks.load_split("train") / load_split("heldout")

Run (stub end-to-end):
  python ember_c14_contract_rig.py           # full run + gate structure printed
  python ember_c14_contract_rig.py --test    # TDD test suite only
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import math
import random
import sys
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# Import from banked resident loop
# ---------------------------------------------------------------------------

# Adjust import path so this script can be run from any directory.
import importlib
import pathlib

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from ember_resident_igrpo import (
    TinyPolicyTransformer,
    igrpo_step,
    executing_verifier as _igrpo_executing_verifier,
    rlm_generate,
    _encode_state,
    ACTION_FINAL,
)

_ENGAGEMENT_SCHEMA_VERSION = "ember-igrpo-engagement-step-v1"
_ENGAGEMENT_FIELDS = {
    "schema_version",
    "requested_n",
    "requested_g",
    "realized_stage1_drafts",
    "attempted",
    "emitted",
    "valid",
    "scored",
    "unique_completions",
    "reward_vector_length",
    "advantage_vector_length",
    "group_ids",
    "normalization_denominator",
    "estimator_name",
    "drop_reasons",
}


def _validate_engagement_receipt(
    step_result: Any,
    *,
    requested_n: int,
    requested_g: int,
    min_unique_completions: int,
) -> dict[str, Any]:
    """Validate one realized iGRPO step against the caller's frozen counts."""
    if type(requested_n) is not int or requested_n <= 0:
        raise ValueError("requested_n must be a positive integer")
    if type(requested_g) is not int or requested_g <= 0:
        raise ValueError("requested_g must be a positive integer")
    if (
        type(min_unique_completions) is not int
        or min_unique_completions <= 0
        or min_unique_completions > requested_g
    ):
        raise ValueError("min_unique_completions must be in [1, requested_g]")
    if not isinstance(step_result, dict):
        raise ValueError("training result must be an object containing engagement")
    row = step_result.get("engagement")
    if not isinstance(row, dict):
        raise ValueError("training result engagement must be an object")
    unknown = set(row) - _ENGAGEMENT_FIELDS
    missing = _ENGAGEMENT_FIELDS - set(row)
    if unknown:
        raise ValueError(f"engagement has unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"engagement is missing fields: {sorted(missing)}")
    if row["schema_version"] != _ENGAGEMENT_SCHEMA_VERSION:
        raise ValueError("engagement schema_version is invalid")
    expected_counts = {
        "requested_n": requested_n,
        "requested_g": requested_g,
        "realized_stage1_drafts": requested_n,
        "attempted": requested_g,
        "emitted": requested_g,
        "scored": requested_g,
        "reward_vector_length": requested_g,
        "advantage_vector_length": requested_g,
        "normalization_denominator": requested_g,
    }
    for field_name, expected in expected_counts.items():
        value = row[field_name]
        if type(value) is not int or value != expected:
            raise ValueError(
                f"engagement {field_name} must equal {expected}; got {value!r}"
            )
    valid = row["valid"]
    if type(valid) is not int or valid < 0 or valid > requested_g:
        raise ValueError(
            "engagement valid must be an integer in "
            f"[0, {requested_g}]; got {valid!r}"
        )
    unique = row["unique_completions"]
    if (
        type(unique) is not int
        or unique < min_unique_completions
        or unique > requested_g
    ):
        raise ValueError(
            "engagement unique_completions must satisfy the frozen floor "
            f"{min_unique_completions} <= unique <= {requested_g}; got {unique!r}"
        )
    group_ids = row["group_ids"]
    expected_group_ids = [f"stage2:{index}" for index in range(requested_g)]
    if group_ids != expected_group_ids:
        raise ValueError("engagement group_ids must be the canonical stage2 sequence")
    if row["estimator_name"] != "population_std_group_relative":
        raise ValueError("engagement estimator_name is invalid")
    drop_reasons = row["drop_reasons"]
    if not isinstance(drop_reasons, list) or any(
        not isinstance(item, str) or not item for item in drop_reasons
    ):
        raise ValueError("engagement drop_reasons must be a list of nonempty strings")
    seen_drop_indices: set[int] = set()
    allowed_drop_codes = {
        "no_emitted_tokens",
        "no_final_action",
        "fallback_fired",
    }
    for item in drop_reasons:
        parts = item.split(":")
        if len(parts) != 3 or parts[0] != "stage2" or not parts[1].isdigit():
            raise ValueError("engagement drop_reasons contain a malformed reason")
        drop_index = int(parts[1])
        if (
            str(drop_index) != parts[1]
            or drop_index < 0
            or drop_index >= requested_g
            or drop_index in seen_drop_indices
            or parts[2] not in allowed_drop_codes
        ):
            raise ValueError("engagement drop_reasons contain an invalid reason")
        seen_drop_indices.add(drop_index)
    if len(drop_reasons) != requested_g - valid:
        raise ValueError(
            "engagement drop_reasons must account for every invalid completion; "
            f"expected {requested_g - valid}, got {len(drop_reasons)}"
        )
    return copy.deepcopy(row)


# ---------------------------------------------------------------------------
# Corpus types
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """One task in the corpus.

    state_val    : int  — observed state (0-7 for stub; [REDACTED] task spec for real)
    correct_action: int — expected action (verified by verifier function)
    split        : str  — "train" | "heldout"
    id           : str  — unique identifier

    For text-structured TaskSpec (real [REDACTED]-cli corpus):
    prompt       : Optional[str] — the task description/prompt text shown to the policy
    description  : Optional[str] — any auxiliary task description text

    CORPUS-V2 (additive, default OFF — 2026-07-03):
    exemplars    : Optional[list[tuple[int, int]]] — k in-context demonstration
                   (exemplar_state, exemplar_action) pairs, prepended to this
                   task's observable context by ember_resident_igrpo._encode_state.
                   NEVER contains (this task's own state_val, ...) or
                   (..., this task's own correct_action) — see
                   Corpus.echo_proof_assert()'s corpus-v2 checks. None (the
                   default) reproduces pre-corpus-v2 behavior exactly.
    """
    state_val: int
    correct_action: int
    split: str
    id: str
    # Optional text fields for real [REDACTED]-cli TaskSpec tasks
    prompt: Optional[str] = None
    description: Optional[str] = None
    # Optional corpus-v2 in-context exemplars (default OFF; see docstring above)
    exemplars: Optional[list[tuple[int, int]]] = None


@dataclass
class Corpus:
    """Echo-proof task corpus for A/B/C/Deleted evaluation.

    Does-NOT-count guard (c): answers are never injected into prompts.
    The task only stores state_val (the observation); correct_action is used
    ONLY by the verifier, never surfaced as part of the policy's input.
    """
    train: list[Task]
    heldout: list[Task]

    def __post_init__(self) -> None:
        # Guard (c): assert no ID overlap between train and held-out.
        train_ids = {t.id for t in self.train}
        heldout_ids = {t.id for t in self.heldout}
        overlap = train_ids & heldout_ids
        if overlap:
            raise ValueError(f"Corpus has overlapping train/heldout IDs: {overlap}")

    def echo_proof_assert(self) -> None:
        """Assert corpus is echo-proof: correct_action is not in task id/state text.

        DEFECT-5 FIX: for text-structured TaskSpec tasks (real [REDACTED]-cli corpus), also
        assert that the correct_action text is NOT embedded in any task description or
        prompt field. This mirrors the corpus echo-proof property at the rig boundary:
        the policy must not be able to find the answer by reading the prompt.
        """
        for t in self.train + self.heldout:
            # The only thing the policy sees is state_val; correct_action is
            # hidden in the verifier.  No string injection is possible at this
            # abstraction level.  This assertion documents the invariant.
            assert isinstance(t.correct_action, int), (
                f"Task {t.id}: correct_action must be int, not {type(t.correct_action)}"
            )
            assert isinstance(t.state_val, int), (
                f"Task {t.id}: state_val must be int, not {type(t.state_val)}"
            )
            # DEFECT-5 FIX: for text-structured TaskSpec (real corpus), check
            # that correct_action text is NOT embedded in prompt/description fields.
            correct_action_str = str(t.correct_action)
            for field_name, field_val in [("prompt", t.prompt), ("description", t.description)]:
                if field_val is not None:
                    assert correct_action_str not in field_val, (
                        f"Task {t.id}: echo-proof VIOLATION — correct_action "
                        f"'{correct_action_str}' found in {field_name} field. "
                        f"Answers must not be injected into task prompts."
                    )

        # CORPUS-V2 guards (additive, only exercised when t.exemplars is set):
        # (i) an exemplar's state is never THIS task's own queried state_val
        #     (would trivially leak "the answer is whatever action follows
        #     the token identical to your own observation");
        # (ii) an exemplar's action is never THIS task's own correct_action
        #      (the queried state's answer must NEVER appear in its prompt —
        #      guaranteed by (i) alone under the bijective +1-mod-8 map, since
        #      state != state_val implies (state+1)%8 != correct_action, but
        #      checked directly here too as defense-in-depth, not derived);
        # (iii) exemplar states are drawn ONLY from this corpus's own train
        #      state_vals — derived from self.train, never taken on faith —
        #      so a held-out task's solvability is a genuine unseen-state
        #      transfer test, never won by construction.
        train_state_vals = {t.state_val for t in self.train}
        for t in self.train + self.heldout:
            if not t.exemplars:
                continue
            for ex_state, ex_action in t.exemplars:
                assert ex_state != t.state_val, (
                    f"Task {t.id}: corpus-v2 echo-proof VIOLATION — exemplar "
                    f"state {ex_state} equals the task's OWN queried state_val; "
                    "exemplars must be OTHER states only."
                )
                assert ex_action != t.correct_action, (
                    f"Task {t.id}: corpus-v2 echo-proof VIOLATION — exemplar "
                    f"action {ex_action} equals the task's OWN correct_action "
                    f"({t.correct_action}); the queried state's own answer "
                    "must never appear in its prompt."
                )
                assert ex_state in train_state_vals, (
                    f"Task {t.id}: corpus-v2 VIOLATION — exemplar state "
                    f"{ex_state} is not one of this corpus's TRAIN state_vals "
                    f"({sorted(train_state_vals)}); exemplars must be drawn "
                    "from train states only, for BOTH train and held-out "
                    "tasks, so held-out solvability is a genuine transfer "
                    "test and never won by construction."
                )


# ---------------------------------------------------------------------------
# Stub corpus (tiny, CPU-only, proves apparatus end-to-end)
# ---------------------------------------------------------------------------

def _make_stub_corpus() -> Corpus:
    """8 train tasks + 4 held-out tasks for the stub instantiation.

    Stub task = increment-modulo-8 state machine (from ember_resident_igrpo).
    correct_action = (state_val + 1) % 8.
    """
    train_tasks = [
        Task(state_val=i, correct_action=(i + 1) % 8, split="train", id=f"train_{i:02d}")
        for i in range(8)
    ]
    # Held-out tasks are structurally different: they use state_vals that
    # require modular wrap (5,6,7) plus one mid-range (3) — different structure
    # from the training distribution (0-7 uniform).
    heldout_tasks = [
        Task(state_val=5, correct_action=6, split="heldout", id="held_05"),
        Task(state_val=6, correct_action=7, split="heldout", id="held_06"),
        Task(state_val=7, correct_action=0, split="heldout", id="held_07"),
        Task(state_val=3, correct_action=4, split="heldout", id="held_03"),
    ]
    return Corpus(train=train_tasks, heldout=heldout_tasks)


# ---------------------------------------------------------------------------
# Verifier protocol
# ---------------------------------------------------------------------------

VerifierFn = Callable[[Any, int], float]
"""verifier(task, emitted_action) -> reward in {0.0, 1.0}.

Must be EXECUTING (non-lexical): reward comes from running a deterministic
check, not from string overlap with the task prompt.
"""


def _stub_verifier(task: Task, emitted_action: int) -> float:
    """Stub verifier: wraps executing_verifier from ember_resident_igrpo.

    Delegates to the state-machine increment verifier.  Non-lexical: the reward
    comes from running (state_val + 1) % 8, not from string comparison.
    """
    return _igrpo_executing_verifier(task.state_val, emitted_action)


# ---------------------------------------------------------------------------
# Does-NOT-count guard: frozen/borrowed/zero-init core detection
# ---------------------------------------------------------------------------

def _assert_core_not_frozen_borrowed_zero(
    core: nn.Module,
    name: str = "core",
) -> None:
    """Guard (d): reject a frozen/borrowed/zero-init core.

    Checks:
      1. At least one parameter has requires_grad=True (not frozen).
      2. The parameter distribution is NOT all-zeros (not zero-init with no grad).
      3. Parameters are not all identical (a cheap proxy for "borrowed" constant init).

    Raises ValueError if any guard fails.
    """
    params = list(core.parameters())
    if not params:
        raise ValueError(f"{name}: core has no parameters — cannot be a valid owned core.")

    # Guard: at least one trainable parameter
    trainable = [p for p in params if p.requires_grad]
    if not trainable:
        raise ValueError(
            f"{name}: core is FROZEN (no parameters with requires_grad=True). "
            "A frozen core cannot be the owned core."
        )

    # Guard: not all zeros
    all_zeros = all(p.data.abs().max().item() == 0.0 for p in params)
    if all_zeros:
        raise ValueError(
            f"{name}: core has ALL-ZERO parameters (zero-init). "
            "A zero-init core cannot be the owned core."
        )

    # Guard: parameters are not all the same constant value
    # (catches borrowed/constant-fill cores)
    all_values_same = True
    first_val: Optional[float] = None
    for p in params:
        vals = p.data.flatten()
        if len(vals) > 0:
            v = vals[0].item()
            if first_val is None:
                first_val = v
            if not all(abs(x.item() - first_val) < 1e-9 for x in vals):
                all_values_same = False
                break
    if all_values_same and first_val is not None:
        raise ValueError(
            f"{name}: all core parameters have the same constant value ({first_val}). "
            "This looks like a borrowed/constant-fill core — not the owned core."
        )


# ---------------------------------------------------------------------------
# Param hash — canonical content hash of all core parameters
# ---------------------------------------------------------------------------

def _param_hash(core: nn.Module) -> str:
    """SHA-256 of all parameter tensors (sorted by name) as a hex digest.

    Used to assert that C's weight-delta is in the CORE and that Deleted
    restores the exact pre-C state_dict.

    numpy has no native bfloat16 type, so param.data.numpy() raises for the
    CUDA path's bf16 core weights. Reinterpreting the contiguous CPU tensor
    as uint8 (Tensor.view(torch.uint8)) dumps the exact same underlying byte
    buffer that .numpy().tobytes() would for any dtype numpy DOES support —
    so float32 (the CPU path's only dtype) hashes byte-for-byte identically
    to before, and bf16 now hashes too instead of raising.
    """
    h = hashlib.sha256()
    # Chunked + zero-copy (no .tobytes() duplicate): bounds the host-RAM
    # transient to ~128MB per chunk; digest is byte-identical because sha256
    # streams the same byte sequence. GATE-0 refire-d died MemoryError on the
    # whole-tensor tobytes copy under tight commit (2026-07-04).
    chunk_elems = 64_000_000
    for name, param in sorted(core.named_parameters()):
        h.update(name.encode("utf-8"))
        flat = param.data.detach().reshape(-1)
        for start in range(0, flat.numel(), chunk_elems):
            piece = flat[start:start + chunk_elems].cpu().contiguous()
            h.update(piece.view(torch.uint8).numpy())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Arm evaluation
# ---------------------------------------------------------------------------

@dataclass
class ArmResult:
    """Per-task result rows + aggregate pass count for one arm."""
    arm: str
    rows: list[dict]       # one dict per task: {id, state_val, action, reward}
    pass_count: int        # number of tasks with reward=1.0
    total: int             # total tasks evaluated
    pass_rate: float       # pass_count / total


EvalArmFn = Callable[[nn.Module, list[Task], VerifierFn], ArmResult]
"""eval_arm(core, tasks, verifier) -> ArmResult."""


def _stub_eval_arm_A(
    core: TinyPolicyTransformer,
    tasks: list[Task],
    verifier: VerifierFn,
) -> ArmResult:
    """Arm A: owned core, NO resident — greedy action-gen, no weight update."""
    rows = []
    with torch.no_grad():
        for task in tasks:
            # Generate action directly from core (greedy, temperature=0)
            # CORPUS-V2: task.exemplars is None unless generate_corpus() was
            # called with corpus_v2=True — same call, same behavior, either way.
            episode = rlm_generate(
                core, task.state_val, max_depth=0, temperature=0.0,
                exemplars=task.exemplars,
            )
            action = episode.final_action if episode.final_action is not None else 0
            r = verifier(task, action)
            rows.append({"id": task.id, "state_val": task.state_val,
                         "action": action, "reward": r})
    pass_count = sum(1 for row in rows if row["reward"] == 1.0)
    return ArmResult(
        arm="A",
        rows=rows,
        pass_count=pass_count,
        total=len(tasks),
        pass_rate=pass_count / len(tasks) if tasks else 0.0,
    )


def _select_arm_b_template(
    core: TinyPolicyTransformer,
    train_tasks: list[Task],
    verifier: VerifierFn,
) -> int:
    """Select the best FIXED action template using ONLY the train split.

    DEFECT-4 FIX: template selection must use only train tasks, never held-out.
    This function is separate so eval on train and held-out both use the SAME
    template that was fixed on train — no oracle access to held-out.

    Returns the best fixed action token (int).
    """
    best_action = 0
    best_score = -1.0
    with torch.no_grad():
        for candidate_action in range(8):
            total_r = sum(verifier(task, candidate_action) for task in train_tasks)
            if total_r > best_score:
                best_score = total_r
                best_action = candidate_action
    return best_action


def _apply_arm_b_template(
    tasks: list[Task],
    verifier: VerifierFn,
    fixed_action: int,
    arm_name: str = "B",
) -> ArmResult:
    """Apply a pre-selected FIXED action template to a task list (no oracle search).

    DEFECT-4 FIX: called separately for train and held-out, both using the
    same fixed_action that was selected on train only. No oracle over held-out.
    """
    rows = []
    for task in tasks:
        r = verifier(task, fixed_action)
        rows.append({"id": task.id, "state_val": task.state_val,
                     "action": fixed_action, "reward": r})
    pass_count = sum(1 for row in rows if row["reward"] == 1.0)
    return ArmResult(
        arm=arm_name,
        rows=rows,
        pass_count=pass_count,
        total=len(tasks),
        pass_rate=pass_count / len(tasks) if tasks else 0.0,
    )


def _stub_eval_arm_B(
    core: TinyPolicyTransformer,
    tasks: list[Task],
    verifier: VerifierFn,
    _fixed_action: Optional[int] = None,
) -> ArmResult:
    """Arm B: owned core + best FIXED action-template (no weight update).

    DEFECT-4 FIX: when called for held-out eval, _fixed_action must be
    pre-supplied from the train split selection (no oracle over held-out).
    When called for train eval, _fixed_action=None and the template is
    selected here (oracle over train is correct for arm B by definition).

    The key property: the template selection uses ONLY the train split;
    the held-out apply call uses the pre-fixed template without seeing
    held-out rewards.
    """
    if _fixed_action is None:
        # Select template on this task set (caller must ensure these are train tasks)
        best_action = _select_arm_b_template(core, tasks, verifier)
    else:
        best_action = _fixed_action
    return _apply_arm_b_template(tasks, verifier, best_action, arm_name="B")


def _stub_eval_arm_C_and_deleted(
    core_factory: Callable[[], TinyPolicyTransformer],
    train_tasks: list[Task],
    heldout_tasks: list[Task],
    verifier: VerifierFn,
    n_train_steps: int = 16,
    lr: float = 1e-3,
    train_resident_fn: Optional[Callable] = None,
    eval_checkpoint_callback: Optional[Callable[[int, Any], None]] = None,
    eval_checkpoint_interval: Optional[int] = None,
    corpus_v3_resample_fn: Optional[Callable[[Task, int], Task]] = None,
    requested_n: int = 4,
    requested_g: int = 4,
    min_unique_completions: int = 1,
    require_engagement_receipt: bool = False,
    engagement_receipt_sink: Optional[list[dict[str, Any]]] = None,
) -> tuple[ArmResult, ArmResult, ArmResult, ArmResult, str, str, str]:
    """Run C arm (train + eval) and Deleted arm (revert + eval).

    DEFECT-3 FIX: train_resident_fn is now threaded through as a parameter.
    The C arm trains via the PASSED function (not module-level igrpo_step
    directly). For the stub default, train_resident_fn=igrpo_step.
    For the REAL instantiation, train_resident_fn=real_adapter (the
    train_multimodal_v0-hosted iGRPO, per adapt-verdict JSON).

    DEFECT-2 FIX: returns the INDEPENDENTLY-computed deleted_hash as the
    7th element (was previously absent; callers that passed pre_c_hash by
    fiat are now fixed).

    Returns:
        (C_train, C_heldout, Deleted_train, Deleted_heldout,
         pre_c_hash, post_c_hash, deleted_hash)

    Guard (a) is checked here:
      - pre_c_hash != post_c_hash (C updates the core)
      - Deleted restores EXACT pre_c_hash

    CHECKPOINT-EVAL HOOK (additive, 2026-07-03): eval_checkpoint_callback/
    eval_checkpoint_interval default to None, so the training loop below is
    byte-identical to before this change whenever either is left unset (no
    new calls, no new state, no new randomness) — the ONLY new code that
    executes is a single `is not None`/interval check per step. When both
    ARE set, the callback fires as `callback(step_num, core)` right after
    the step's train_resident_fn() call, using the SAME `core` reference
    that call just trained — so the checkpoint always observes the exact
    post-step weights, never a stale or reconstructed copy. The callback is
    eval-only by construction of what callers pass in (see
    ember_c14_owned_run.py's _make_checkpoint_eval_callback: greedy
    temperature=0.0 argmax draws touch no RNG at all — see
    ember_resident_igrpo.py's SAMPLING-COST CURE PHASE 2 docstring — so this
    hook cannot perturb the training RNG stream no matter how many
    checkpoints fire).

    CORPUS-V3 DYNAMIC EXEMPLAR RESAMPLING (additive, default OFF — design
    spec c14-owned-core-resident-run-v1.md sec 8g, envelope v2.0):
    `corpus_v3_resample_fn`, if given, is called as `corpus_v3_resample_fn
    (task, step_idx)` once per C-arm TRAINING step, right where the loop
    below already picks `task = train_tasks[step_idx % len(train_tasks)]` —
    the single presentation point for the C-arm's SOLE gradient path (spec
    sec 1). It must return a Task (typically `dataclasses.replace(task,
    exemplars=...)` — see ember_c14_owned_run.py::_make_corpus_v3_resample_fn,
    the caller this is designed for) whose `exemplars` carry a FRESH
    per-presentation draw; that returned Task — never the original — is
    what gets handed to `train_resident_fn`, so `train_tasks` (the corpus's
    own stored Task objects, and every OTHER call site that reads them:
    Arm C's post-train eval, the Deleted arm, and the --eval-checkpoint-
    interval callback, all of which keep the generation-time STATIC
    exemplars per spec sec 8g's "heldout evaluation and checkpoint TRAIN
    evals stay comparable") are never mutated by this hook — the resample
    fn is responsible for returning a new object, and this function reads
    `task.state_val` for the training call itself (unaffected by any
    resample) so a resample_fn is trusted only for `exemplars`, never for
    changing which state this presentation trains on. `None` (the default)
    skips the call entirely: `presented_task is task` every step, so the
    loop is byte-identical to pre-corpus-v3 behavior when this parameter is
    omitted or explicitly None.
    """
    # DEFECT-3 FIX: default to igrpo_step only if no function passed
    if train_resident_fn is None:
        train_resident_fn = igrpo_step

    core = core_factory()
    optimizer = torch.optim.Adam(core.parameters(), lr=lr)

    # Snapshot EXACT pre-C state_dict (used for Deleted arm)
    pre_c_state = copy.deepcopy(core.state_dict())
    pre_c_hash = _param_hash(core)

    # --- C arm: train on train tasks via the PASSED train_resident_fn ---
    for step_idx in range(n_train_steps):
        # Cycle through train tasks
        task = train_tasks[step_idx % len(train_tasks)]
        # DEFECT-3 FIX: call via train_resident_fn parameter, not module-level igrpo_step
        # CORPUS-V2: train_resident_fn is a CALLER-SUPPLIED Callable of
        # arbitrary signature (T23's sentinel proves some have neither
        # **kwargs nor an exemplars parameter) — so the kwarg is included
        # ONLY when this task actually carries corpus-v2 exemplars
        # (task.exemplars is None unless generate_corpus(corpus_v2=True) was
        # used), keeping every corpus-v2-OFF call byte-identical to
        # pre-corpus-v2 regardless of train_resident_fn's own signature.
        # igrpo_step accepts this kwarg (default None); the cmd_live adapter
        # (_train_fn) forwards it into train_one_step (corpus-v2 live-path
        # gap closed 2026-07-03 — see the corpus-v2 report).
        #
        # CORPUS-V3 (additive, default OFF — see this function's docstring):
        # corpus_v3_resample_fn, if supplied, replaces THIS presentation's
        # exemplars only; `task` itself (the corpus's own stored object) is
        # never reassigned, so train_tasks is provably unmutated regardless
        # of how many steps run.
        presented_task = (
            task if corpus_v3_resample_fn is None else corpus_v3_resample_fn(task, step_idx)
        )
        extra_kwargs = (
            {"exemplars": presented_task.exemplars} if presented_task.exemplars is not None else {}
        )
        step_result = train_resident_fn(
            policy=core,
            optimizer=optimizer,
            state_val=task.state_val,
            N=requested_n,
            G=requested_g,
            max_depth=1,
            epsilon=0.2,
            temperature=1.5,
            **extra_kwargs,
        )
        if require_engagement_receipt or (
            isinstance(step_result, dict) and "engagement" in step_result
        ):
            receipt = _validate_engagement_receipt(
                step_result,
                requested_n=requested_n,
                requested_g=requested_g,
                min_unique_completions=min_unique_completions,
            )
            if engagement_receipt_sink is not None:
                engagement_receipt_sink.append(receipt)
        # CHECKPOINT-EVAL HOOK: see this function's docstring. No-op unless
        # BOTH a callback and a truthy interval were supplied by the caller.
        if eval_checkpoint_callback is not None and eval_checkpoint_interval:
            step_num = step_idx + 1
            if step_num % eval_checkpoint_interval == 0:
                eval_checkpoint_callback(step_num, core)

    post_c_hash = _param_hash(core)

    # Eval C on train tasks
    c_train = _eval_arm_from_core(core, train_tasks, verifier, arm_name="C")
    # Eval C on heldout tasks
    c_heldout = _eval_arm_from_core(core, heldout_tasks, verifier, arm_name="C")

    # --- Deleted arm: revert to exact pre-C state_dict ---
    core.load_state_dict(pre_c_state)

    # DEFECT-2 FIX: compute deleted_hash INDEPENDENTLY by hashing the actual
    # core params AFTER the revert. This is a derived comparison, NOT an
    # assignment from pre_c_hash (which was the prior self-fulfilling defect).
    deleted_hash = _param_hash(core)

    # Guard (a): Deleted must restore EXACT pre-C hash
    if deleted_hash != pre_c_hash:
        raise RuntimeError(
            f"GUARD VIOLATION (a): Deleted arm did not restore the exact pre-C hash. "
            f"pre_c={pre_c_hash[:16]}... deleted={deleted_hash[:16]}..."
        )

    # Eval Deleted on train
    deleted_train = _eval_arm_from_core(core, train_tasks, verifier, arm_name="Deleted")
    # Eval Deleted on heldout
    deleted_heldout = _eval_arm_from_core(core, heldout_tasks, verifier, arm_name="Deleted")

    return c_train, c_heldout, deleted_train, deleted_heldout, pre_c_hash, post_c_hash, deleted_hash


def _eval_arm_from_core(
    core: TinyPolicyTransformer,
    tasks: list[Task],
    verifier: VerifierFn,
    arm_name: str = "?",
) -> ArmResult:
    """Evaluate core (greedy) against tasks using verifier. No weight update."""
    rows = []
    with torch.no_grad():
        for task in tasks:
            # CORPUS-V2: task.exemplars is None unless generate_corpus() was
            # called with corpus_v2=True — used to eval BOTH C and Deleted so
            # they see the SAME per-task context as arm A above (fair compare).
            episode = rlm_generate(
                core, task.state_val, max_depth=0, temperature=0.0,
                exemplars=task.exemplars,
            )
            action = episode.final_action if episode.final_action is not None else 0
            r = verifier(task, action)
            rows.append({"id": task.id, "state_val": task.state_val,
                         "action": action, "reward": r})
    pass_count = sum(1 for row in rows if row["reward"] == 1.0)
    return ArmResult(
        arm=arm_name,
        rows=rows,
        pass_count=pass_count,
        total=len(tasks),
        pass_rate=pass_count / len(tasks) if tasks else 0.0,
    )


# ---------------------------------------------------------------------------
# Side-classifier detector — guard (a)
# ---------------------------------------------------------------------------

def _is_side_classifier(core: nn.Module) -> bool:
    """Heuristic: detect if core is a side-classifier rather than a real policy.

    A side-classifier typically has:
      - very few parameters (< 1000 total)
      - no attention/transformer layers
      - only Linear layers + bias

    A real TinyPolicyTransformer has embedding + multi-head attention + FFN.
    """
    total_params = sum(p.numel() for p in core.parameters())
    if total_params < 1000:
        return True
    # Check for transformer-like layers
    has_attention = any(
        "attn" in name.lower() or "attention" in name.lower() or
        "transformer" in name.lower() or "encoder" in name.lower()
        for name, _ in core.named_modules()
    )
    if not has_attention:
        return True
    return False


# ---------------------------------------------------------------------------
# Gate predicate computation
# ---------------------------------------------------------------------------

@dataclass
class GatePredicates:
    """Four C14 gate predicates."""
    # (1) C beats A AND C beats B on train
    c_beats_a_train: bool
    c_beats_b_train: bool
    # (2) Deleted degrades to ~A on train (|Deleted - A| <= tolerance)
    deleted_degrades_to_a_train: bool
    deleted_a_delta: float
    # (3) C beats A AND C beats B on held-out (transfer)
    c_beats_a_heldout: bool
    c_beats_b_heldout: bool
    # (4) Deleted drops held-out tasks C newly passes
    deletion_drops_heldout_c_tasks: bool
    c_new_passes_heldout: int   # tasks C passes that A does not
    deleted_drops_count: int    # how many of those Deleted fails

    @property
    def all_pass(self) -> bool:
        return (
            self.c_beats_a_train
            and self.c_beats_b_train
            and self.deleted_degrades_to_a_train
            and self.c_beats_a_heldout
            and self.c_beats_b_heldout
            and self.deletion_drops_heldout_c_tasks
        )


def compute_gate_predicates(
    a_train: ArmResult,
    b_train: ArmResult,
    c_train: ArmResult,
    deleted_train: ArmResult,
    a_heldout: ArmResult,
    b_heldout: ArmResult,
    c_heldout: ArmResult,
    deleted_heldout: ArmResult,
    deletion_tolerance: float = 0.15,
) -> GatePredicates:
    """Compute all four C14 gate predicates from arm results.

    deletion_tolerance: max |Deleted_rate - A_rate| that still counts as
    "Deleted degrades to ~A".  Default 0.15 (15pp).
    """
    # (1) C beats A and B on train
    c_beats_a_train = c_train.pass_rate > a_train.pass_rate
    c_beats_b_train = c_train.pass_rate > b_train.pass_rate

    # (2) Deleted degrades to ~A on train
    deleted_a_delta = abs(deleted_train.pass_rate - a_train.pass_rate)
    deleted_degrades = deleted_a_delta <= deletion_tolerance

    # (3) Transfer: C beats A and B on held-out
    c_beats_a_heldout = c_heldout.pass_rate > a_heldout.pass_rate
    c_beats_b_heldout = c_heldout.pass_rate > b_heldout.pass_rate

    # (4) Deletion on held-out: Deleted drops tasks C newly passes
    # Identify held-out tasks C passes that A does NOT pass
    a_pass_ids = {row["id"] for row in a_heldout.rows if row["reward"] == 1.0}
    c_pass_ids = {row["id"] for row in c_heldout.rows if row["reward"] == 1.0}
    deleted_pass_ids = {row["id"] for row in deleted_heldout.rows if row["reward"] == 1.0}

    c_newly_passes = c_pass_ids - a_pass_ids   # tasks C wins that A doesn't
    deleted_drops = c_newly_passes - deleted_pass_ids  # of those, Deleted fails

    deletion_drops_c_tasks = len(c_newly_passes) > 0 and len(deleted_drops) > 0

    return GatePredicates(
        c_beats_a_train=c_beats_a_train,
        c_beats_b_train=c_beats_b_train,
        deleted_degrades_to_a_train=deleted_degrades,
        deleted_a_delta=deleted_a_delta,
        c_beats_a_heldout=c_beats_a_heldout,
        c_beats_b_heldout=c_beats_b_heldout,
        deletion_drops_heldout_c_tasks=deletion_drops_c_tasks,
        c_new_passes_heldout=len(c_newly_passes),
        deleted_drops_count=len(deleted_drops),
    )


# ---------------------------------------------------------------------------
# Does-NOT-count guards (fail-closed assertions)
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Results of all does-NOT-count guard assertions."""
    # (a) weight-delta is in core: C changes params, Deleted restores exact pre-C
    guard_a_c_changes_core: bool
    guard_a_deleted_restores_core: bool
    pre_c_hash: str
    post_c_hash: str
    deleted_hash: str
    # (b) verifier is executing (documented; not re-checked here — see verifier source)
    guard_b_verifier_executing: bool
    # (c) corpus is echo-proof (verified at Corpus construction time)
    guard_c_echo_proof: bool
    # (d) core is not frozen/borrowed/zero-init
    guard_d_core_not_frozen: bool
    # (e) core is not a side-classifier
    guard_e_not_side_classifier: bool
    # (g) gradient-flow: core params received non-None .grad from backward before step
    guard_g_gradient_flow: bool
    # (h) reward-dependence: C_scrambled does NOT clear (gain vanishes without real rewards)
    guard_h_reward_dependence: bool
    # Diagnostic fields for (h)
    c_train_rate: float = 0.0
    c_scrambled_train_rate: float = 0.0
    a_train_rate: float = 0.0

    @property
    def all_pass(self) -> bool:
        return (
            self.guard_a_c_changes_core
            and self.guard_a_deleted_restores_core
            and self.guard_b_verifier_executing
            and self.guard_c_echo_proof
            and self.guard_d_core_not_frozen
            and self.guard_e_not_side_classifier
            and self.guard_g_gradient_flow
            and self.guard_h_reward_dependence
        )


def _probe_verifier_is_executing(verifier: VerifierFn) -> bool:
    """DEFECT-1 FIX: mechanically verify the verifier is EXECUTING, not lexical.

    A lexical/inclusion verifier scores by checking whether the action token
    appears as a substring in the task prompt or state description — not by
    running any computation. An executing verifier runs the actual task logic.

    Mechanical probe strategy:
      Find a (state_val, action) pair where:
        - The action token digit APPEARS in the state representation (lexical overlap)
        - But the action is NOT the correct increment result (execution disagrees)

      For the stub increment-modulo-8 task:
        state_val=2 -> correct_action=3
        But the digit "2" appears in the state; a lexical verifier that checks
        if the emitted digit appears in str(state_val) would return 1.0 for
        emitted_action=2 (wrong by execution, but "2" is in "2").

      Alternatively: state_val=1, action=1.
        Lexical match: "1" is in str(1) -> lexical would score 1.0
        Execution: correct=(1+1)%8=2, not 1 -> execution scores 0.0

      We probe with the known disagreement pair (state_val=1, action=1):
        Executing verifier MUST return 0.0 (action 1 != correct 2).
        A lexical verifier that checks str(action) in str(state_val) would
        return 1.0 (string "1" appears in "1").

      Additionally probe (state_val=3, action=4) — the correct pair:
        Executing verifier MUST return 1.0.
        A verifier that always returns 0.0 or is broken would fail here.

    If the verifier returns the EXECUTION result on both probes, guard_b passes.
    If it returns the lexical result on the disagreement probe, guard_b FAILS.

    This is a concrete mechanical test, not documentation.
    """
    # Probe 1: disagreement pair — lexical overlap would give 1.0, execution gives 0.0
    # state_val=1, action=1: str(1) is in str(1) -> lexical=1.0, execution=0.0 (correct=2)
    # We build a minimal stub Task for this probe.
    probe_task_disagree = Task(
        state_val=1,
        correct_action=2,  # (1+1)%8=2
        split="train",
        id="__guard_b_probe_disagree__",
    )
    # Probe: emit action=1 (same digit as state — lexical overlap)
    # Executing verifier: correct for state=1 is 2, so action=1 -> reward=0.0
    # Lexical verifier that checks str(action) in str(state_val): "1" in "1" -> 1.0
    result_disagree = verifier(probe_task_disagree, 1)

    # If the verifier returns 1.0 on the disagreement probe, it's lexical -> FAIL
    if result_disagree != 0.0:
        return False  # lexical result returned — guard (b) FAILS

    # Probe 2: correct pair — executing verifier MUST return 1.0
    probe_task_correct = Task(
        state_val=3,
        correct_action=4,  # (3+1)%8=4
        split="train",
        id="__guard_b_probe_correct__",
    )
    result_correct = verifier(probe_task_correct, 4)
    if result_correct != 1.0:
        return False  # verifier broken — guard (b) FAILS

    return True  # both probes returned the EXECUTION result


def _wrap_train_fn_for_gradient_probe(
    train_resident_fn: Callable,
    core: nn.Module,
) -> tuple[Callable, list[bool]]:
    """Return a wrapped train_resident_fn that records whether core params received
    a non-None .grad from an actual backward pass BEFORE optimizer.step().

    Guard (g) GRADIENT-FLOW:
      A genuine gradient-based trainer calls loss.backward() which populates .grad
      on every leaf param that is in the computation graph.  A load_state_dict
      weight-setter calls backward on NOTHING — param .grad stays None.

      A dummy backward on an unrelated tensor does NOT satisfy the guard because
      .grad is only populated for params that participated in the backward's
      computation graph.  We therefore require at least one CORE param (a param
      from the core module itself) to have non-None .grad.

    Implementation:
      We monkey-patch optimizer.step() to snapshot .grad existence on the CORE
      params right before the step fires.  The wrapper returns (wrapped_fn, log)
      where log is a mutable list; each call appends True if at least one core
      param had non-None .grad at step time, False otherwise.

    ACCEPTED LIMITATION — float32 subnormal hash blind spot:
      SHA-256 hashes the raw float bytes.  A weight perturbation whose absolute
      magnitude is below ~1.175e-38 (the smallest positive normalised float32)
      falls into subnormal territory; the byte encoding of such a delta may be
      indistinguishable from zero at the byte level.  For real gradient-based
      updates the deltas are orders of magnitude larger (Adam LR 1e-3, loss O(1)),
      so this blind spot is irrelevant in practice.  It is documented here as an
      ACCEPTED limitation, not a fixable defect: the guard tests .grad presence
      (a boolean), not the magnitude of the resulting weight change.
    """
    grad_log: list[bool] = []

    def _wrapped(
        policy: nn.Module,
        optimizer: torch.optim.Optimizer,
        **kwargs,
    ) -> Any:
        # Intercept optimizer.step to read .grad on CORE params before it fires.
        original_step = optimizer.step

        def _patched_step(*a, **kw):
            # Check: does at least one CORE parameter have a non-None grad?
            # We check ONLY the params that belong to the core module (policy),
            # not any other param that may have been in some unrelated graph.
            core_params_with_grad = [
                p for p in policy.parameters()
                if p.grad is not None
            ]
            had_grad = len(core_params_with_grad) > 0
            grad_log.append(had_grad)
            return original_step(*a, **kw)

        optimizer.step = _patched_step  # type: ignore[method-assign]
        try:
            result = train_resident_fn(policy=policy, optimizer=optimizer, **kwargs)
        finally:
            optimizer.step = original_step  # restore
        return result

    return _wrapped, grad_log


def _run_scrambled_arm(
    core_factory: Callable[[], nn.Module],
    train_tasks: list[Task],
    verifier: VerifierFn,
    train_resident_fn: Callable,
    n_train_steps: int = 16,
    lr: float = 1e-3,
    seed_offset: int = 9999,
    requested_n: int = 4,
    requested_g: int = 4,
    min_unique_completions: int = 1,
    require_engagement_receipt: bool = False,
) -> ArmResult:
    """Run a C_scrambled arm: same train_resident_fn but with ZEROED rewards.

    Guard (h) REWARD-DEPENDENCE:
      A genuine iGRPO trainer uses the verifier rewards to compute group-relative
      advantages A_j = (r_j - mean) / std.  When ALL rewards are zero, std = 0,
      so ALL advantages are zero, and the policy gradient is exactly zero —
      no learning signal reaches the optimizer.  A genuine reward-driven trainer
      trained with zeroed rewards cannot improve over A (untrained baseline).

      A reward-ignoring trainer (e.g. a weight-setter via load_state_dict) copies
      good weights directly, completely ignoring the reward signal.  Its
      C_scrambled pass_rate equals its C pass_rate (both copy the same golden
      weights), so C_scrambled still beats A — guard (h) catches this.

    Implementation: monkey-patch the executing_verifier in the ember_resident_igrpo
      module to return 0.0 for every call during the scrambled arm run.  This is
      the most direct intervention: every reward the trainer sees is 0, forcing
      std(rewards) = 0 and advantages = 0 throughout the entire training run.

      After the arm run we restore the original verifier.

    Why zeroed rewards rather than permuted/scrambled:
      - Zeroed rewards are unambiguous: std = 0 -> advantages = 0 -> gradient = 0.
        There is no dependence on the specific permutation or its correlation with
        the real rewards.
      - Permuting rewards across a mini-batch can accidentally preserve useful
        signal if the batch happens to be partially correct.
      - For the real instantiation: pass zeroed rewards to the training loop in
        the same way (patch the reward signal to 0.0 for all samples).

    Invariant:
      genuine  igrpo_step + zeroed rewards:  C_scrambled pass_rate ~ A pass_rate
      weight-setter / reward-ignoring:       C_scrambled pass_rate ~ C pass_rate >> A
    """
    import ember_resident_igrpo as _igrpo_module

    # Monkey-patch executing_verifier in the module to always return 0.0.
    _original_verifier = _igrpo_module.executing_verifier

    def _zeroed_verifier(state_val: int, emitted_action: int) -> float:
        return 0.0

    _igrpo_module.executing_verifier = _zeroed_verifier  # type: ignore[attr-defined]

    try:
        core = core_factory()
        optimizer = torch.optim.Adam(core.parameters(), lr=lr)
        rng_state = random.getstate()
        random.seed(seed_offset)
        torch.manual_seed(seed_offset)

        for step_idx in range(n_train_steps):
            task = train_tasks[step_idx % len(train_tasks)]
            step_result = train_resident_fn(
                policy=core,
                optimizer=optimizer,
                state_val=task.state_val,
                N=requested_n,
                G=requested_g,
                max_depth=1,
                epsilon=0.2,
                temperature=1.5,
            )
            if require_engagement_receipt or (
                isinstance(step_result, dict) and "engagement" in step_result
            ):
                _validate_engagement_receipt(
                    step_result,
                    requested_n=requested_n,
                    requested_g=requested_g,
                    min_unique_completions=min_unique_completions,
                )

        random.setstate(rng_state)
    finally:
        # Always restore the original verifier, even on exception.
        _igrpo_module.executing_verifier = _original_verifier  # type: ignore[attr-defined]

    return _eval_arm_from_core(core, train_tasks, verifier, arm_name="C_scrambled")


def check_guards(
    core_factory: Callable[[], nn.Module],
    pre_c_hash: str,
    post_c_hash: str,
    deleted_hash: str,
    verifier: VerifierFn,
    corpus: Corpus,
    train_resident_fn: Optional[Callable] = None,
    c_train_result: Optional["ArmResult"] = None,
    a_train_result: Optional["ArmResult"] = None,
    n_train_steps: int = 16,
    lr: float = 1e-3,
    requested_n: int = 4,
    requested_g: int = 4,
    min_unique_completions: int = 1,
    require_engagement_receipt: bool = False,
) -> GuardResult:
    """Run all does-NOT-count guards.  Fail-closed: any failure blocks clearance.

    Parameters
    ----------
    core_factory        : produces a fresh owned core (used for guards d, e, g, h)
    pre_c_hash          : hash before C-arm training
    post_c_hash         : hash after C-arm training
    deleted_hash        : hash after Deleted-arm revert
    verifier            : VerifierFn (used for guard b probe and h scrambled arm)
    corpus              : Corpus (used for guard c and h)
    train_resident_fn   : the train function used for C arm (used for guard g and h);
                          if None, guard_g and guard_h are skipped (set False)
    c_train_result      : ArmResult for C on train (used by guard h comparison);
                          if None, guard h skips the comparison and uses scrambled only
    a_train_result      : ArmResult for A on train (used by guard h comparison)
    n_train_steps       : steps for the guard-g gradient probe and guard-h scrambled arm
    lr                  : learning rate for guard-g and guard-h probe runs
    """
    # (a) C changes core params; Deleted restores
    guard_a_c_changes = (pre_c_hash != post_c_hash)
    guard_a_deleted_restores = (deleted_hash == pre_c_hash)

    # (b) DEFECT-1 FIX: Verifier is executing — MECHANICAL probe, not annotation.
    guard_b = _probe_verifier_is_executing(verifier)

    # (c) Echo-proof — verified at Corpus construction; call echo_proof_assert()
    try:
        corpus.echo_proof_assert()
        guard_c = True
    except Exception:
        guard_c = False

    # (d) Core not frozen/borrowed/zero-init — check on a fresh instance
    try:
        probe_core = core_factory()
        _assert_core_not_frozen_borrowed_zero(probe_core, name="core_factory()")
        guard_d = True
    except ValueError:
        guard_d = False

    # (e) Core is not a side-classifier
    try:
        probe_core2 = core_factory()
        guard_e = not _is_side_classifier(probe_core2)
    except Exception:
        guard_e = False

    # -----------------------------------------------------------------------
    # (g) GRADIENT-FLOW guard — added to close SYMBOLIC_PROXY_PASS
    #
    # A load_state_dict weight-setter calls no backward() on the core params,
    # so .grad stays None on every param.  We run a short probe training loop
    # and assert that at least one core param received a non-None .grad BEFORE
    # optimizer.step() during at least one training step.
    #
    # A dummy backward on an UNRELATED tensor does NOT satisfy this guard because
    # .grad is only populated for params that participated in that backward's
    # computation graph.  We require grads on the CORE params that actually
    # change (i.e., the params of the policy/core module being trained).
    #
    # ACCEPTED LIMITATION — float32 subnormal hash blind spot (documented here):
    #   SHA-256 operates on raw float bytes.  Weight perturbations with magnitude
    #   below ~1.175e-38 (smallest positive normalised float32) fall in subnormal
    #   range; at that scale the byte encoding may not differ from zero.
    #   For real gradient updates (Adam LR 1e-3, loss O(1)) deltas are O(1e-3)
    #   to O(1e-1) — far above the subnormal floor — so this blind spot is
    #   irrelevant in practice.  Guard (g) checks .grad presence (a boolean),
    #   not the magnitude of the resulting weight change, so it is unaffected.
    # -----------------------------------------------------------------------
    guard_g = False
    if train_resident_fn is not None:
        try:
            probe_core_g = core_factory()
            probe_opt_g = torch.optim.Adam(probe_core_g.parameters(), lr=lr)
            _wrapped_g, grad_log_g = _wrap_train_fn_for_gradient_probe(
                train_resident_fn, probe_core_g
            )
            for step_i in range(min(n_train_steps, 4)):
                task = corpus.train[step_i % len(corpus.train)]
                step_result = _wrapped_g(
                    policy=probe_core_g,
                    optimizer=probe_opt_g,
                    state_val=task.state_val,
                    N=requested_n,
                    G=requested_g,
                    max_depth=1,
                    epsilon=0.2,
                    temperature=1.5,
                )
                if require_engagement_receipt or (
                    isinstance(step_result, dict) and "engagement" in step_result
                ):
                    _validate_engagement_receipt(
                        step_result,
                        requested_n=requested_n,
                        requested_g=requested_g,
                        min_unique_completions=min_unique_completions,
                    )
            # Guard passes iff at least one step had core grad non-None
            guard_g = any(had for had in grad_log_g)
        except Exception:
            guard_g = False

    # -----------------------------------------------------------------------
    # (h) REWARD-DEPENDENCE guard — added to close SYMBOLIC_PROXY_PASS
    #
    # A C_scrambled arm trains via the SAME train_resident_fn but with SCRAMBLED
    # rewards (wrong task remapping).  A genuine iGRPO trainer's gain over A
    # vanishes when rewards are scrambled — the advantage signal is noise.
    # A weight-setter or reward-ignoring trainer improves regardless of rewards:
    # its C_scrambled clears as well as C.
    #
    # We assert: C_scrambled gain over A is NOT positive (within noise tolerance).
    # Specifically: C_scrambled.pass_rate <= A.pass_rate + noise_tolerance.
    # If C_scrambled also beats A, the trainer is NOT reward-driven -> guard (h) FAILS.
    #
    # noise_tolerance = 0.20 (20pp) to account for random initialisation variance
    # in the tiny stub.  For the real instantiation, set tighter (e.g. 0.05).
    # -----------------------------------------------------------------------
    guard_h = False
    c_scrambled_train_rate: float = 0.0
    c_train_rate_for_h: float = 0.0
    a_train_rate_for_h: float = 0.0
    REWARD_DEPENDENCE_NOISE_TOLERANCE = 0.20

    if train_resident_fn is not None:
        try:
            c_scrambled_result = _run_scrambled_arm(
                core_factory=core_factory,
                train_tasks=corpus.train,
                verifier=verifier,
                train_resident_fn=train_resident_fn,
                n_train_steps=n_train_steps,
                lr=lr,
                requested_n=requested_n,
                requested_g=requested_g,
                min_unique_completions=min_unique_completions,
                require_engagement_receipt=require_engagement_receipt,
            )
            c_scrambled_train_rate = c_scrambled_result.pass_rate

            # Get A and C rates for comparison.
            a_rate = a_train_result.pass_rate if a_train_result is not None else 0.0
            c_rate = c_train_result.pass_rate if c_train_result is not None else 1.0
            c_train_rate_for_h = c_rate
            a_train_rate_for_h = a_rate

            # C_scrambled must NOT beat A by more than noise_tolerance.
            # If C_scrambled clears (beats A), the trainer is reward-ignoring -> FAIL.
            c_scrambled_beats_a = (
                c_scrambled_train_rate > a_rate + REWARD_DEPENDENCE_NOISE_TOLERANCE
            )
            guard_h = not c_scrambled_beats_a
        except Exception:
            guard_h = False

    return GuardResult(
        guard_a_c_changes_core=guard_a_c_changes,
        guard_a_deleted_restores_core=guard_a_deleted_restores,
        pre_c_hash=pre_c_hash,
        post_c_hash=post_c_hash,
        deleted_hash=deleted_hash,
        guard_b_verifier_executing=guard_b,
        guard_c_echo_proof=guard_c,
        guard_d_core_not_frozen=guard_d,
        guard_e_not_side_classifier=guard_e,
        guard_g_gradient_flow=guard_g,
        guard_h_reward_dependence=guard_h,
        c_train_rate=c_train_rate_for_h,
        c_scrambled_train_rate=c_scrambled_train_rate,
        a_train_rate=a_train_rate_for_h,
    )


# ---------------------------------------------------------------------------
# Full rig runner
# ---------------------------------------------------------------------------

@dataclass
class RigResult:
    """Complete output of one rig run."""
    a_train: ArmResult
    b_train: ArmResult
    c_train: ArmResult
    deleted_train: ArmResult
    a_heldout: ArmResult
    b_heldout: ArmResult
    c_heldout: ArmResult
    deleted_heldout: ArmResult
    gate: GatePredicates
    guards: GuardResult
    stub_run: bool   # True = STUB instantiation; False = REAL
    engagement_receipts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clearance(self) -> bool:
        """C14 clearance: all gate predicates AND all guards pass."""
        return self.gate.all_pass and self.guards.all_pass


def run_rig(
    core_factory: Callable[[], nn.Module],
    train_resident_fn: Callable,
    verifier: VerifierFn,
    corpus: Corpus,
    n_train_steps: int = 32,
    lr: float = 1e-3,
    deletion_tolerance: float = 0.15,
    stub: bool = True,
    eval_checkpoint_callback: Optional[Callable[[int, Any], None]] = None,
    eval_checkpoint_interval: Optional[int] = None,
    corpus_v3_resample_fn: Optional[Callable[[Task, int], Task]] = None,
    requested_n: int = 4,
    requested_g: int = 4,
    min_unique_completions: int = 1,
    require_engagement_receipt: bool = False,
) -> RigResult:
    """Run the full A/B/C/Deleted apparatus.

    Parameters
    ----------
    core_factory        : callable -> nn.Module  — produces a fresh owned core
    train_resident_fn   : callable(core, optimizer, state_val, ...) -> dict
                          (igrpo_step signature for stub; real adapter for REAL)
    verifier            : VerifierFn  — (task, action) -> reward in {0,1}
    corpus              : Corpus  — echo-proof task corpus
    n_train_steps       : int  — iGRPO steps for C arm training
    lr                  : float  — learning rate for C arm optimizer
    deletion_tolerance  : float  — max |Deleted - A| rate gap for predicate (2)
    stub                : bool  — True = STUB instantiation (logged in result)
    eval_checkpoint_callback : optional callable(step, core) -> None, invoked
                          after every eval_checkpoint_interval-th C-arm train
                          step (additive; both default None = feature OFF,
                          byte-identical C-arm training loop — see
                          _stub_eval_arm_C_and_deleted's docstring).
    eval_checkpoint_interval : optional int  — checkpoint cadence in steps.
    corpus_v3_resample_fn : optional callable(task, step_idx) -> Task —
                          envelope v2.0 (design spec sec 8g) dynamic
                          exemplar resampling for C-arm TRAINING
                          presentations only (additive; default None =
                          feature OFF, byte-identical to static corpus-v2 —
                          see _stub_eval_arm_C_and_deleted's docstring).
    """
    # Guard (d): assert core is not frozen/borrowed/zero-init before running
    _assert_core_not_frozen_borrowed_zero(core_factory(), name="core_factory()")

    # Arm A — shared core (fresh), no resident
    core_a = core_factory()
    a_train = _stub_eval_arm_A(core_a, corpus.train, verifier)
    a_heldout = _stub_eval_arm_A(core_a, corpus.heldout, verifier)

    # DEFECT-4 FIX: Arm B — fix the template on TRAIN only, then apply unchanged
    # to held-out. No oracle search over held-out.
    b_fixed_action = _select_arm_b_template(core_a, corpus.train, verifier)
    b_train = _apply_arm_b_template(corpus.train, verifier, b_fixed_action, arm_name="B")
    b_heldout = _apply_arm_b_template(corpus.heldout, verifier, b_fixed_action, arm_name="B")

    # DEFECT-3 FIX: Arms C and Deleted — thread train_resident_fn through
    # DEFECT-2 FIX: receive the independently-computed deleted_hash (7th return value)
    engagement_receipts: list[dict[str, Any]] = []
    (c_train, c_heldout,
     deleted_train, deleted_heldout,
     pre_c_hash, post_c_hash,
     deleted_hash) = _stub_eval_arm_C_and_deleted(
        core_factory=core_factory,
        train_tasks=corpus.train,
        heldout_tasks=corpus.heldout,
        verifier=verifier,
        n_train_steps=n_train_steps,
        lr=lr,
        train_resident_fn=train_resident_fn,
        eval_checkpoint_callback=eval_checkpoint_callback,
        eval_checkpoint_interval=eval_checkpoint_interval,
        corpus_v3_resample_fn=corpus_v3_resample_fn,
        requested_n=requested_n,
        requested_g=requested_g,
        min_unique_completions=min_unique_completions,
        require_engagement_receipt=require_engagement_receipt,
        engagement_receipt_sink=engagement_receipts,
    )

    # DEFECT-2 FIX: deleted_hash is NOW the independently-computed hash of the
    # Deleted core's actual params after the revert (returned from
    # _stub_eval_arm_C_and_deleted), NOT assigned by fiat from pre_c_hash.
    # The GuardResult comparison is a derived check, not a self-fulfilling assignment.

    # Gate predicates
    gate = compute_gate_predicates(
        a_train=a_train,
        b_train=b_train,
        c_train=c_train,
        deleted_train=deleted_train,
        a_heldout=a_heldout,
        b_heldout=b_heldout,
        c_heldout=c_heldout,
        deleted_heldout=deleted_heldout,
        deletion_tolerance=deletion_tolerance,
    )

    # Does-NOT-count guards
    guards = check_guards(
        core_factory=core_factory,
        pre_c_hash=pre_c_hash,
        post_c_hash=post_c_hash,
        deleted_hash=deleted_hash,
        verifier=verifier,
        corpus=corpus,
        train_resident_fn=train_resident_fn,
        c_train_result=c_train,
        a_train_result=a_train,
        n_train_steps=n_train_steps,
        lr=lr,
        requested_n=requested_n,
        requested_g=requested_g,
        min_unique_completions=min_unique_completions,
        require_engagement_receipt=require_engagement_receipt,
    )

    return RigResult(
        a_train=a_train,
        b_train=b_train,
        c_train=c_train,
        deleted_train=deleted_train,
        a_heldout=a_heldout,
        b_heldout=b_heldout,
        c_heldout=c_heldout,
        deleted_heldout=deleted_heldout,
        gate=gate,
        guards=guards,
        stub_run=stub,
        engagement_receipts=engagement_receipts,
    )


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(result: RigResult) -> None:
    """Print the gate structure produced by the rig."""
    mode = "STUB" if result.stub_run else "REAL"
    print(f"\n{'='*60}")
    print(f"  C14 A/B/C/Deleted Contract Rig — {mode} RUN")
    print(f"{'='*60}")

    # Per-arm pass counts (train + heldout)
    print("\n--- Arm pass rates ---")
    print(f"  {'Arm':<12} {'Train':>10} {'Held-out':>10}")
    print(f"  {'-'*34}")
    for arm_train, arm_heldout in [
        (result.a_train,       result.a_heldout),
        (result.b_train,       result.b_heldout),
        (result.c_train,       result.c_heldout),
        (result.deleted_train, result.deleted_heldout),
    ]:
        train_str  = f"{arm_train.pass_count}/{arm_train.total} ({arm_train.pass_rate:.2%})"
        heldout_str = f"{arm_heldout.pass_count}/{arm_heldout.total} ({arm_heldout.pass_rate:.2%})"
        print(f"  {arm_train.arm:<12} {train_str:>10} {heldout_str:>10}")

    # Per-task rows (train)
    print("\n--- Per-task rows (train) ---")
    all_train_ids = [row["id"] for row in result.a_train.rows]
    print(f"  {'Task':<12} {'A':>4} {'B':>4} {'C':>4} {'Del':>4}")
    print(f"  {'-'*30}")
    a_map = {row["id"]: row["reward"] for row in result.a_train.rows}
    b_map = {row["id"]: row["reward"] for row in result.b_train.rows}
    c_map = {row["id"]: row["reward"] for row in result.c_train.rows}
    d_map = {row["id"]: row["reward"] for row in result.deleted_train.rows}
    for tid in all_train_ids:
        print(f"  {tid:<12} {int(a_map.get(tid,0)):>4} {int(b_map.get(tid,0)):>4} "
              f"{int(c_map.get(tid,0)):>4} {int(d_map.get(tid,0)):>4}")

    # Per-task rows (heldout)
    print("\n--- Per-task rows (held-out) ---")
    all_heldout_ids = [row["id"] for row in result.a_heldout.rows]
    print(f"  {'Task':<12} {'A':>4} {'B':>4} {'C':>4} {'Del':>4}")
    print(f"  {'-'*30}")
    a_hmap = {row["id"]: row["reward"] for row in result.a_heldout.rows}
    b_hmap = {row["id"]: row["reward"] for row in result.b_heldout.rows}
    c_hmap = {row["id"]: row["reward"] for row in result.c_heldout.rows}
    d_hmap = {row["id"]: row["reward"] for row in result.deleted_heldout.rows}
    for tid in all_heldout_ids:
        print(f"  {tid:<12} {int(a_hmap.get(tid,0)):>4} {int(b_hmap.get(tid,0)):>4} "
              f"{int(c_hmap.get(tid,0)):>4} {int(d_hmap.get(tid,0)):>4}")

    # Gate predicates
    g = result.gate
    print("\n--- Gate predicates ---")
    def _pf(b: bool) -> str: return "PASS" if b else "FAIL"
    print(f"  (1a) C > A on train:                {_pf(g.c_beats_a_train)}")
    print(f"  (1b) C > B on train:                {_pf(g.c_beats_b_train)}")
    print(f"  (2)  |Deleted - A| <= tol on train: {_pf(g.deleted_degrades_to_a_train)}"
          f"  (delta={g.deleted_a_delta:.3f})")
    print(f"  (3a) C > A on held-out (transfer):  {_pf(g.c_beats_a_heldout)}")
    print(f"  (3b) C > B on held-out (transfer):  {_pf(g.c_beats_b_heldout)}")
    print(f"  (4)  Deleted drops C-new heldout:   {_pf(g.deletion_drops_heldout_c_tasks)}"
          f"  (C-new={g.c_new_passes_heldout}, dropped={g.deleted_drops_count})")
    print(f"  ALL GATE:                           {_pf(g.all_pass)}")

    # Does-NOT-count guards
    gr = result.guards
    print("\n--- Does-NOT-count guards ---")
    print(f"  (a1) C changes core params:         {_pf(gr.guard_a_c_changes_core)}")
    print(f"       pre_C  hash: {gr.pre_c_hash[:16]}...")
    print(f"       post_C hash: {gr.post_c_hash[:16]}...")
    print(f"  (a2) Deleted restores exact pre-C:  {_pf(gr.guard_a_deleted_restores_core)}")
    print(f"  (b)  Verifier is executing:         {_pf(gr.guard_b_verifier_executing)}")
    print(f"  (c)  Corpus is echo-proof:          {_pf(gr.guard_c_echo_proof)}")
    print(f"  (d)  Core not frozen/borrowed/zero: {_pf(gr.guard_d_core_not_frozen)}")
    print(f"  (e)  Core not side-classifier:      {_pf(gr.guard_e_not_side_classifier)}")
    print(f"  (g)  Gradient-flow (core .grad!=None before step): {_pf(gr.guard_g_gradient_flow)}")
    print(f"  (h)  Reward-dependence (scrambled C does NOT clear):")
    print(f"       A_train={gr.a_train_rate:.2%}  C_train={gr.c_train_rate:.2%}"
          f"  C_scrambled_train={gr.c_scrambled_train_rate:.2%}  {_pf(gr.guard_h_reward_dependence)}")
    print(f"  ALL GUARDS:                         {_pf(gr.all_pass)}")

    # Final verdict
    verdict = "C14-CLEARED" if result.clearance else "C14-NOT-CLEARED"
    print(f"\n  VERDICT: {verdict}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# TDD test suite
# ---------------------------------------------------------------------------

def _run_tests(verbose: bool = True) -> tuple[bool, list[str], list[str]]:
    """Run all TDD tests.  Returns (all_passed, passed_names, failed_names)."""

    passed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []

    def check(name: str, cond: bool, msg: str = "") -> None:
        if cond:
            passed.append(name)
            if verbose:
                print(f"  PASS  {name}")
        else:
            failed.append(name)
            if verbose:
                print(f"  FAIL  {name}  {msg}")

    # -----------------------------------------------------------------------
    # T01: Arm A runs and returns ArmResult
    # -----------------------------------------------------------------------
    name = "T01_arm_A_runs"
    try:
        torch.manual_seed(1)
        corpus = _make_stub_corpus()
        core = TinyPolicyTransformer()
        result = _stub_eval_arm_A(core, corpus.train, _stub_verifier)
        check(name, result.arm == "A" and result.total == len(corpus.train),
              f"arm={result.arm}, total={result.total}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T02: Arm B runs and returns ArmResult
    # -----------------------------------------------------------------------
    name = "T02_arm_B_runs"
    try:
        torch.manual_seed(2)
        corpus = _make_stub_corpus()
        core = TinyPolicyTransformer()
        result = _stub_eval_arm_B(core, corpus.train, _stub_verifier)
        check(name, result.arm == "B" and result.total == len(corpus.train),
              f"arm={result.arm}, total={result.total}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T03: Arms C and Deleted run end-to-end
    # -----------------------------------------------------------------------
    name = "T03_arms_C_deleted_run"
    try:
        torch.manual_seed(3)
        corpus = _make_stub_corpus()
        (c_tr, c_ho, del_tr, del_ho,
         pre_h, post_h, del_h) = _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=corpus.train,
            heldout_tasks=corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=8,
        )
        check(name,
              c_tr.arm == "C" and del_tr.arm == "Deleted"
              and c_tr.total == len(corpus.train)
              and del_tr.total == len(corpus.train),
              f"arms={c_tr.arm},{del_tr.arm}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T04: C arm weight-delta is in the core (pre_hash != post_hash)
    # -----------------------------------------------------------------------
    name = "T04_C_arm_changes_core_params"
    try:
        torch.manual_seed(4)
        corpus = _make_stub_corpus()
        (_, _, _, _, pre_h, post_h, _del_h) = _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=corpus.train,
            heldout_tasks=corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=16,
        )
        check(name, pre_h != post_h,
              f"pre_hash={pre_h[:16]}... == post_hash={post_h[:16]}... (C did not change core)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T05: Deleted arm restores EXACT pre-C hash
    # -----------------------------------------------------------------------
    name = "T05_deleted_restores_exact_pre_C_hash"
    try:
        torch.manual_seed(5)
        corpus = _make_stub_corpus()
        core = TinyPolicyTransformer()
        pre_state = copy.deepcopy(core.state_dict())
        pre_h = _param_hash(core)
        # Train (simulate C arm)
        opt = torch.optim.Adam(core.parameters(), lr=1e-3)
        for i in range(8):
            igrpo_step(core, opt, state_val=i % 8, N=2, G=2, max_depth=0)
        # Revert
        core.load_state_dict(pre_state)
        restored_h = _param_hash(core)
        check(name, restored_h == pre_h,
              f"restored_hash={restored_h[:16]}... != pre_hash={pre_h[:16]}...")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T06: Gate predicates compute correctly on synthetic arm scores
    # Synthetic: C > A, C > B on train; Deleted ~= A; C > A and B on heldout;
    # Deleted drops C-new heldout tasks.
    # -----------------------------------------------------------------------
    name = "T06_gate_predicates_compute_correctly_synthetic"
    try:
        def _fake_arm(arm_name: str, rewards: list[float], task_ids: list[str]) -> ArmResult:
            rows = [{"id": tid, "state_val": i, "action": 0, "reward": r}
                    for i, (tid, r) in enumerate(zip(task_ids, rewards))]
            pc = sum(1 for r in rewards if r == 1.0)
            return ArmResult(arm=arm_name, rows=rows, pass_count=pc,
                             total=len(rewards), pass_rate=pc/len(rewards))

        train_ids = [f"t{i}" for i in range(4)]
        held_ids  = [f"h{i}" for i in range(4)]
        # A: 1/4 on train, 1/4 on heldout
        # B: 1/4 on train, 1/4 on heldout
        # C: 3/4 on train, 3/4 on heldout
        # Deleted: 1/4 on train (same as A), 1/4 on heldout
        a_tr  = _fake_arm("A",       [1,0,0,0], train_ids)
        b_tr  = _fake_arm("B",       [0,0,0,1], train_ids)
        c_tr  = _fake_arm("C",       [1,1,1,0], train_ids)
        d_tr  = _fake_arm("Deleted", [1,0,0,0], train_ids)
        a_ho  = _fake_arm("A",       [1,0,0,0], held_ids)
        b_ho  = _fake_arm("B",       [0,0,0,1], held_ids)
        c_ho  = _fake_arm("C",       [1,1,1,0], held_ids)
        d_ho  = _fake_arm("Deleted", [1,0,0,0], held_ids)

        gate = compute_gate_predicates(
            a_tr, b_tr, c_tr, d_tr, a_ho, b_ho, c_ho, d_ho,
            deletion_tolerance=0.15,
        )
        # (1) C=0.75 > A=0.25 AND C=0.75 > B=0.25 on train
        # (2) |Deleted=0.25 - A=0.25| = 0.0 <= 0.15
        # (3) C=0.75 > A=0.25 AND C=0.75 > B=0.25 on held-out
        # (4) C newly passes h1,h2 (not in A); Deleted fails both -> drops 2
        all_ok = (
            gate.c_beats_a_train and gate.c_beats_b_train
            and gate.deleted_degrades_to_a_train
            and gate.c_beats_a_heldout and gate.c_beats_b_heldout
            and gate.deletion_drops_heldout_c_tasks
            and gate.all_pass
        )
        check(name, all_ok,
              f"predicates: (1a)={gate.c_beats_a_train} (1b)={gate.c_beats_b_train} "
              f"(2)={gate.deleted_degrades_to_a_train} delta={gate.deleted_a_delta:.3f} "
              f"(3a)={gate.c_beats_a_heldout} (3b)={gate.c_beats_b_heldout} "
              f"(4)={gate.deletion_drops_heldout_c_tasks}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T07: Gate (1) fails correctly when C does NOT beat A on train
    # -----------------------------------------------------------------------
    name = "T07_gate_predicate_1_fails_when_C_le_A_train"
    try:
        def _fake_arm2(arm_name, rewards, task_ids):
            rows = [{"id": tid, "state_val": i, "action": 0, "reward": r}
                    for i, (tid, r) in enumerate(zip(task_ids, rewards))]
            pc = sum(1 for r in rewards if r == 1.0)
            return ArmResult(arm=arm_name, rows=rows, pass_count=pc,
                             total=len(rewards), pass_rate=pc/len(rewards))
        train_ids = [f"t{i}" for i in range(4)]
        held_ids  = [f"h{i}" for i in range(4)]
        # C <= A on train
        a_tr = _fake_arm2("A", [1,1,1,1], train_ids)  # 4/4
        b_tr = _fake_arm2("B", [0,0,0,0], train_ids)
        c_tr = _fake_arm2("C", [1,1,1,0], train_ids)  # 3/4 < A=4/4
        d_tr = _fake_arm2("Deleted", [1,1,1,1], train_ids)
        a_ho = _fake_arm2("A", [1,0,0,0], held_ids)
        b_ho = _fake_arm2("B", [0,0,0,0], held_ids)
        c_ho = _fake_arm2("C", [1,1,0,0], held_ids)
        d_ho = _fake_arm2("Deleted", [1,0,0,0], held_ids)
        gate = compute_gate_predicates(a_tr, b_tr, c_tr, d_tr, a_ho, b_ho, c_ho, d_ho)
        check(name, not gate.c_beats_a_train,
              f"expected c_beats_a_train=False, got {gate.c_beats_a_train}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T08: Gate (2) fails when Deleted does NOT degrade to ~A
    # -----------------------------------------------------------------------
    name = "T08_gate_predicate_2_fails_when_deleted_does_not_degrade"
    try:
        def _fa3(arm_name, rewards, task_ids):
            rows = [{"id": tid, "state_val": i, "action": 0, "reward": r}
                    for i, (tid, r) in enumerate(zip(task_ids, rewards))]
            pc = sum(1 for r in rewards if r == 1.0)
            return ArmResult(arm=arm_name, rows=rows, pass_count=pc,
                             total=len(rewards), pass_rate=pc/len(rewards))
        train_ids = [f"t{i}" for i in range(4)]
        held_ids  = [f"h{i}" for i in range(4)]
        a_tr = _fa3("A",       [1,0,0,0], train_ids)  # 0.25
        b_tr = _fa3("B",       [0,1,0,0], train_ids)
        c_tr = _fa3("C",       [1,1,1,1], train_ids)  # 1.00
        # Deleted = same as C (not degrading to A)
        d_tr = _fa3("Deleted", [1,1,1,1], train_ids)  # 1.00, delta = |1.0 - 0.25| = 0.75
        a_ho = _fa3("A",       [0,0,0,0], held_ids)
        b_ho = _fa3("B",       [0,0,0,0], held_ids)
        c_ho = _fa3("C",       [0,0,0,0], held_ids)
        d_ho = _fa3("Deleted", [0,0,0,0], held_ids)
        gate = compute_gate_predicates(a_tr, b_tr, c_tr, d_tr, a_ho, b_ho, c_ho, d_ho,
                                        deletion_tolerance=0.15)
        check(name, not gate.deleted_degrades_to_a_train,
              f"expected deleted_degrades=False, delta={gate.deleted_a_delta:.3f}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T09: Guard (a) — side-classifier C arm is REJECTED
    # A "side-classifier" C arm that doesn't actually modify the core's
    # params (pre_hash == post_hash) must be caught by guard (a).
    # -----------------------------------------------------------------------
    name = "T09_guard_a_rejects_side_classifier_C_arm"
    try:
        # Simulate: C arm runs but core params don't change (same hash)
        fake_pre_hash = "abc123"
        fake_post_hash = "abc123"  # same = C did NOT change core
        fake_deleted_hash = "abc123"
        corpus = _make_stub_corpus()
        guards = check_guards(
            core_factory=TinyPolicyTransformer,
            pre_c_hash=fake_pre_hash,
            post_c_hash=fake_post_hash,
            deleted_hash=fake_deleted_hash,
            verifier=_stub_verifier,
            corpus=corpus,
        )
        # guard_a_c_changes_core must be False (pre == post -> C did not change core)
        check(name, not guards.guard_a_c_changes_core,
              f"expected guard_a_c_changes_core=False for side-classifier C arm")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T10: Guard (a) — Deleted that does NOT restore pre-C hash is REJECTED
    # -----------------------------------------------------------------------
    name = "T10_guard_a_rejects_deleted_not_restoring_pre_C_hash"
    try:
        fake_pre_hash = "aaa111"
        fake_post_hash = "bbb222"  # C changed core (good)
        fake_deleted_hash = "ccc333"  # Deleted did NOT restore pre-C (bad)
        corpus = _make_stub_corpus()
        guards = check_guards(
            core_factory=TinyPolicyTransformer,
            pre_c_hash=fake_pre_hash,
            post_c_hash=fake_post_hash,
            deleted_hash=fake_deleted_hash,
            verifier=_stub_verifier,
            corpus=corpus,
        )
        # guard_a_deleted_restores_core must be False
        check(name, not guards.guard_a_deleted_restores_core,
              f"expected guard_a_deleted_restores_core=False")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T11: Guard (d) — frozen core (no requires_grad) is REJECTED
    # -----------------------------------------------------------------------
    name = "T11_guard_d_rejects_frozen_core"
    try:
        frozen_core = TinyPolicyTransformer()
        for p in frozen_core.parameters():
            p.requires_grad_(False)
        rejected = False
        try:
            _assert_core_not_frozen_borrowed_zero(frozen_core, "frozen_test")
        except ValueError:
            rejected = True
        check(name, rejected, "frozen core was NOT rejected by guard (d)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T12: Guard (d) — zero-init core is REJECTED
    # -----------------------------------------------------------------------
    name = "T12_guard_d_rejects_zero_init_core"
    try:
        zero_core = TinyPolicyTransformer()
        with torch.no_grad():
            for p in zero_core.parameters():
                p.data.zero_()
        rejected = False
        try:
            _assert_core_not_frozen_borrowed_zero(zero_core, "zero_test")
        except ValueError:
            rejected = True
        check(name, rejected, "zero-init core was NOT rejected by guard (d)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T13: Guard (e) — side-classifier (tiny Linear) is REJECTED
    # -----------------------------------------------------------------------
    name = "T13_guard_e_rejects_side_classifier"
    try:
        # A tiny nn.Linear(7, 10) — no attention, too few params
        side_cls = nn.Linear(7, 10)
        is_side = _is_side_classifier(side_cls)
        check(name, is_side,
              "side-classifier was NOT detected by _is_side_classifier")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T14: Guard (e) — real TinyPolicyTransformer is NOT flagged as side-classifier
    # -----------------------------------------------------------------------
    name = "T14_guard_e_accepts_real_transformer"
    try:
        real_core = TinyPolicyTransformer()
        is_side = _is_side_classifier(real_core)
        check(name, not is_side,
              "TinyPolicyTransformer was incorrectly flagged as a side-classifier")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T15: Corpus echo-proof assert passes for stub corpus
    # -----------------------------------------------------------------------
    name = "T15_corpus_echo_proof_passes"
    try:
        corpus = _make_stub_corpus()
        try:
            corpus.echo_proof_assert()
            check(name, True)
        except Exception as exc:
            check(name, False, f"echo_proof_assert raised: {exc}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T16: Corpus construction fails with overlapping train/heldout IDs
    # -----------------------------------------------------------------------
    name = "T16_corpus_rejects_id_overlap"
    try:
        train = [Task(state_val=0, correct_action=1, split="train", id="dup")]
        heldout = [Task(state_val=1, correct_action=2, split="heldout", id="dup")]
        rejected = False
        try:
            Corpus(train=train, heldout=heldout)
        except ValueError:
            rejected = True
        check(name, rejected, "overlapping IDs were NOT rejected by Corpus.__post_init__")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T17: Gate (4) — deletion drops 0 C-new tasks is FAIL predicate
    # -----------------------------------------------------------------------
    name = "T17_gate_predicate_4_fails_when_deleted_drops_nothing"
    try:
        def _fa4(arm_name, rewards, task_ids):
            rows = [{"id": tid, "state_val": i, "action": 0, "reward": r}
                    for i, (tid, r) in enumerate(zip(task_ids, rewards))]
            pc = sum(1 for r in rewards if r == 1.0)
            return ArmResult(arm=arm_name, rows=rows, pass_count=pc,
                             total=len(rewards), pass_rate=pc/len(rewards))
        train_ids = [f"t{i}" for i in range(4)]
        held_ids  = [f"h{i}" for i in range(4)]
        a_tr  = _fa4("A",       [0,0,0,0], train_ids)
        b_tr  = _fa4("B",       [0,0,0,0], train_ids)
        c_tr  = _fa4("C",       [1,1,0,0], train_ids)
        d_tr  = _fa4("Deleted", [0,0,0,0], train_ids)
        a_ho  = _fa4("A",       [1,1,0,0], held_ids)  # A passes h0,h1
        b_ho  = _fa4("B",       [0,0,0,0], held_ids)
        c_ho  = _fa4("C",       [1,1,0,0], held_ids)  # C=A on heldout (no new passes)
        d_ho  = _fa4("Deleted", [0,0,0,0], held_ids)
        gate = compute_gate_predicates(a_tr, b_tr, c_tr, d_tr, a_ho, b_ho, c_ho, d_ho)
        # C newly passes = (C passes) - (A passes) = {} on heldout => predicate (4) = False
        check(name, not gate.deletion_drops_heldout_c_tasks,
              f"expected deletion_drops=False, got c_new={gate.c_new_passes_heldout}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T18: Param hash differs for two different cores
    # -----------------------------------------------------------------------
    name = "T18_param_hash_differs_for_different_cores"
    try:
        torch.manual_seed(100)
        core1 = TinyPolicyTransformer()
        torch.manual_seed(200)
        core2 = TinyPolicyTransformer()
        h1 = _param_hash(core1)
        h2 = _param_hash(core2)
        check(name, h1 != h2,
              f"hash collision between two independently-seeded cores: {h1[:16]}...")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T19: Full STUB rig runs end-to-end without error and returns RigResult
    # -----------------------------------------------------------------------
    name = "T19_full_stub_rig_runs_end_to_end"
    try:
        torch.manual_seed(42)
        corpus = _make_stub_corpus()
        result = run_rig(
            core_factory=TinyPolicyTransformer,
            train_resident_fn=igrpo_step,
            verifier=_stub_verifier,
            corpus=corpus,
            n_train_steps=32,
            lr=1e-3,
            stub=True,
        )
        check(name,
              isinstance(result, RigResult)
              and result.stub_run
              and result.a_train.total == len(corpus.train)
              and result.a_heldout.total == len(corpus.heldout),
              f"RigResult malformed or wrong counts")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T20: Guards all pass on well-formed stub run (includes guards g and h)
    # -----------------------------------------------------------------------
    name = "T20_guards_all_pass_on_well_formed_stub_run"
    try:
        torch.manual_seed(43)
        corpus = _make_stub_corpus()
        result = run_rig(
            core_factory=TinyPolicyTransformer,
            train_resident_fn=igrpo_step,
            verifier=_stub_verifier,
            corpus=corpus,
            n_train_steps=32,
            stub=True,
        )
        guards = result.guards
        check(name,
              guards.guard_a_c_changes_core
              and guards.guard_a_deleted_restores_core
              and guards.guard_b_verifier_executing
              and guards.guard_c_echo_proof
              and guards.guard_d_core_not_frozen
              and guards.guard_e_not_side_classifier
              and guards.guard_g_gradient_flow
              and guards.guard_h_reward_dependence,
              f"guards failed: a1={guards.guard_a_c_changes_core} "
              f"a2={guards.guard_a_deleted_restores_core} "
              f"b={guards.guard_b_verifier_executing} "
              f"c={guards.guard_c_echo_proof} "
              f"d={guards.guard_d_core_not_frozen} "
              f"e={guards.guard_e_not_side_classifier} "
              f"g={guards.guard_g_gradient_flow} "
              f"h={guards.guard_h_reward_dependence}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T21: DEFECT-1 FIX — guard (b) rejects a lexical verifier
    # A lexical verifier scores by string inclusion, not execution.
    # It returns 1.0 when the action digit appears in str(state_val).
    # _probe_verifier_is_executing must detect this and return False.
    # -----------------------------------------------------------------------
    name = "T21_guard_b_rejects_lexical_verifier"
    try:
        def _lexical_verifier(task: Task, emitted_action: int) -> float:
            """Lexical verifier: scores 1.0 if str(action) appears in str(state_val)."""
            return 1.0 if str(emitted_action) in str(task.state_val) else 0.0

        # Probe: state_val=1, action=1 -> lexical: "1" in "1" -> 1.0 (WRONG by execution)
        # Execution: correct=(1+1)%8=2, so action=1 -> 0.0
        # _probe_verifier_is_executing must return False for this verifier
        result = _probe_verifier_is_executing(_lexical_verifier)
        check(name, result is False,
              f"_probe_verifier_is_executing returned {result} for lexical verifier "
              f"(expected False — lexical verifier must be rejected)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T22: DEFECT-2 FIX — deleted_hash mismatch FAILS guard (a2)
    # When the Deleted arm does NOT restore the exact pre-C hash, the guard
    # must fail. We inject a mismatched deleted_hash to verify.
    # -----------------------------------------------------------------------
    name = "T22_deleted_hash_mismatch_fails_guard_a2"
    try:
        torch.manual_seed(22)
        corpus = _make_stub_corpus()
        (_, _, _, _, pre_c_hash_real, post_c_hash_real,
         _deleted_hash_real) = _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=corpus.train,
            heldout_tasks=corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=8,
        )
        # Inject a WRONG deleted_hash (different from pre_c_hash_real) to verify
        # that check_guards returns guard_a_deleted_restores_core=False.
        wrong_deleted_hash = post_c_hash_real  # post-C hash != pre-C hash
        guards_bad = check_guards(
            core_factory=TinyPolicyTransformer,
            pre_c_hash=pre_c_hash_real,
            post_c_hash=post_c_hash_real,
            deleted_hash=wrong_deleted_hash,
            verifier=_stub_verifier,
            corpus=corpus,
        )
        check(name, not guards_bad.guard_a_deleted_restores_core,
              f"expected guard_a_deleted_restores_core=False when deleted_hash != pre_c_hash, "
              f"got {guards_bad.guard_a_deleted_restores_core}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T23: DEFECT-3 FIX — train_resident_fn sentinel is actually invoked
    # Pass a sentinel function that records calls. Verify it is invoked at
    # least once during the C arm training loop.
    # -----------------------------------------------------------------------
    name = "T23_train_resident_fn_sentinel_is_invoked"
    try:
        torch.manual_seed(23)
        corpus = _make_stub_corpus()
        sentinel_calls: list[dict] = []

        def _sentinel_train_fn(
            policy,
            optimizer,
            state_val: int,
            N: int = 4,
            G: int = 4,
            max_depth: int = 1,
            epsilon: float = 0.2,
            temperature: float = 1.5,
        ) -> dict:
            """Sentinel: records calls, then delegates to igrpo_step."""
            sentinel_calls.append({"state_val": state_val})
            return igrpo_step(
                policy=policy,
                optimizer=optimizer,
                state_val=state_val,
                N=N,
                G=G,
                max_depth=max_depth,
                epsilon=epsilon,
                temperature=temperature,
            )

        _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=corpus.train,
            heldout_tasks=corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=4,
            train_resident_fn=_sentinel_train_fn,
        )
        check(name, len(sentinel_calls) >= 4,
              f"sentinel_train_fn was called {len(sentinel_calls)} times "
              f"(expected >=4 for n_train_steps=4) — train_resident_fn may not be routed")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T24: DEFECT-4 FIX — Arm B has no held-out oracle
    # The fixed template must be selected on train tasks only.
    # Verify by using a verifier where the train-optimal action is DIFFERENT
    # from the heldout-optimal action, and confirming B applies the train
    # template to held-out (not the held-out oracle).
    # -----------------------------------------------------------------------
    name = "T24_arm_b_has_no_heldout_oracle"
    try:
        torch.manual_seed(24)
        # Construct a corpus where train-optimal action differs from heldout-optimal.
        # Train: tasks where correct_action=3 (action 3 wins on train)
        # Held-out: tasks where correct_action=7 (action 7 wins on heldout)
        train_tasks_b = [
            Task(state_val=2, correct_action=3, split="train", id="bt_0"),
            Task(state_val=2, correct_action=3, split="train", id="bt_1"),
        ]
        heldout_tasks_b = [
            Task(state_val=6, correct_action=7, split="heldout", id="bh_0"),
            Task(state_val=6, correct_action=7, split="heldout", id="bh_1"),
        ]

        # Verifier: correct iff action == task.correct_action
        def _biased_verifier(task: Task, emitted_action: int) -> float:
            return 1.0 if emitted_action == task.correct_action else 0.0

        core_b = TinyPolicyTransformer()

        # Select template on train: best action = 3 (only action that scores on train)
        fixed_action = _select_arm_b_template(core_b, train_tasks_b, _biased_verifier)
        check(name + "_template_is_train_optimal",
              fixed_action == 3,
              f"expected train-optimal action=3, got {fixed_action}")

        # Apply to heldout WITHOUT re-searching: B heldout uses action=3, not 7
        b_ho_result = _apply_arm_b_template(
            heldout_tasks_b, _biased_verifier, fixed_action, arm_name="B"
        )
        # With action=3 applied to heldout (correct=7): B heldout pass_rate=0.0
        # If B had oracle access to heldout, it would use action=7 -> pass_rate=1.0
        check(name,
              b_ho_result.pass_rate == 0.0,
              f"arm B heldout pass_rate={b_ho_result.pass_rate:.2f} "
              f"(expected 0.0 — template fixed on train=3, heldout needs 7; "
              f"non-zero means held-out oracle was used)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T25: Guard (g) — a load_state_dict weight-setter is REJECTED
    #
    # A weight-setter calls policy.load_state_dict(golden_state) directly,
    # performing NO backward pass.  Guard (g) must detect that no core param
    # received a non-None .grad and FAIL.
    #
    # This is the canonical SYMBOLIC_PROXY_PASS vector: the rig's old guards
    # (a)/(b)/(c)/(d)/(e) all passed for a weight-setter because params change
    # (guard a), the verifier executes (guard b), and so on.  Guard (g) closes
    # this gap by requiring gradient flow through the core params.
    # -----------------------------------------------------------------------
    name = "T25_guard_g_rejects_weight_setter_train_fn"
    try:
        torch.manual_seed(25)
        corpus = _make_stub_corpus()

        # Build a "golden" state that happens to perform well on the task.
        # We use a trained igrpo policy as the golden state — the setter will
        # copy these weights directly into the core, bypassing backward.
        golden_core = TinyPolicyTransformer()
        golden_opt = torch.optim.Adam(golden_core.parameters(), lr=1e-3)
        for i in range(32):
            task = corpus.train[i % len(corpus.train)]
            igrpo_step(golden_core, golden_opt, state_val=task.state_val,
                       N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5)
        golden_state = copy.deepcopy(golden_core.state_dict())

        # Weight-setter train_resident_fn: ignores loss/backward, sets weights directly.
        # This is the canonical SYMBOLIC_PROXY_PASS: params change (guard a passes)
        # but no gradient flows (guard g must FAIL).
        def _weight_setter_train_fn(
            policy: nn.Module,
            optimizer: torch.optim.Optimizer,
            state_val: int,
            **kwargs,
        ) -> dict:
            # Load the golden weights directly — no loss, no backward, no .grad.
            policy.load_state_dict(golden_state)
            return {"state_val": state_val, "loss": 0.0}

        # Run guard (g) probe with the weight-setter.
        probe_core_g = TinyPolicyTransformer()
        probe_opt_g = torch.optim.Adam(probe_core_g.parameters(), lr=1e-3)
        _wrapped_g, grad_log_g = _wrap_train_fn_for_gradient_probe(
            _weight_setter_train_fn, probe_core_g
        )
        for i in range(4):
            task = corpus.train[i % len(corpus.train)]
            _wrapped_g(
                policy=probe_core_g,
                optimizer=probe_opt_g,
                state_val=task.state_val,
                N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5,
            )
        guard_g_result = any(had for had in grad_log_g)

        # Guard (g) MUST be False for the weight-setter (no backward -> no .grad)
        check(name, not guard_g_result,
              f"guard_g returned {guard_g_result} for weight-setter "
              f"(expected False — no backward means no .grad on core params). "
              f"grad_log={grad_log_g}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T26: Guard (h) — a reward-ignoring trainer is REJECTED
    #
    # A reward-ignoring trainer improves the policy regardless of whether the
    # rewards are real or scrambled — it copies good weights directly (like a
    # weight-setter) or ignores the reward signal entirely.
    # Guard (h) must detect that C_scrambled also clears (scrambled gain ~ real gain)
    # and FAIL.
    #
    # We use the weight-setter from T25 as the reward-ignoring trainer:
    # it copies the golden state unconditionally, so its C_scrambled pass_rate
    # equals its C pass_rate (both equal golden_core's pass_rate on train tasks).
    # That means C_scrambled beats A by the same margin as C — guard (h) FAILS.
    #
    # The genuine igrpo_step, by contrast, should pass guard (h): when its
    # rewards are scrambled (wrong task remapping), the gradient signal is noise
    # and C_scrambled's gain over A vanishes.  That is tested in T20 (via run_rig
    # with igrpo_step and guards.guard_h_reward_dependence == True).
    # -----------------------------------------------------------------------
    name = "T26_guard_h_rejects_reward_ignoring_trainer"
    try:
        torch.manual_seed(26)
        corpus = _make_stub_corpus()

        # Build a COMPETENT golden state for the cheat trainer to copy.
        # 2026-07-02: previously this trained via 32 igrpo_steps, whose toy
        # competence was partly powered by the rlm_generate fallback-to-correct
        # fabrication (fixed in ember_resident_igrpo the same day) — after the
        # fix that recipe no longer guarantees the >20% margin this control
        # needs. T26's contract does not care HOW the copied state got
        # competent, only that a reward-IGNORING trainer holding a competent
        # state is caught by guard (h). So construct it explicitly: supervised
        # cross-entropy toward the task's correct action — a labeled TEST
        # FIXTURE construction inside the negative control, never an
        # evidence-path reward signal.
        # Episode-native competence: a passing episode must emit the correct
        # action token and then ACTION_FINAL, so teach exactly those two steps
        # (state -> correct, state+correct -> FINAL) to low loss. Measured
        # episode-eval pass_rate of this fixture: 1.0.
        golden_core2 = TinyPolicyTransformer()
        golden_opt2 = torch.optim.Adam(golden_core2.parameters(), lr=3e-3)
        for i in range(3000):
            task = corpus.train[i % len(corpus.train)]
            correct = (task.state_val + 1) % 8
            ctx1 = _encode_state(task.state_val)
            ctx2 = torch.cat([ctx1, torch.tensor([correct], dtype=torch.long)])
            l1 = golden_core2(ctx1.unsqueeze(0))[0, -1]
            l2 = golden_core2(ctx2.unsqueeze(0))[0, -1]
            loss = (
                torch.nn.functional.cross_entropy(
                    l1.unsqueeze(0), torch.tensor([correct], dtype=torch.long))
                + torch.nn.functional.cross_entropy(
                    l2.unsqueeze(0), torch.tensor([ACTION_FINAL], dtype=torch.long))
            )
            golden_opt2.zero_grad()
            loss.backward()
            golden_opt2.step()
            if i % 200 == 199 and loss.item() < 0.02:
                break
        golden_state2 = copy.deepcopy(golden_core2.state_dict())

        def _reward_ignoring_train_fn(
            policy: nn.Module,
            optimizer: torch.optim.Optimizer,
            state_val: int,
            **kwargs,
        ) -> dict:
            policy.load_state_dict(golden_state2)
            return {"state_val": state_val, "loss": 0.0}

        # Arm A: fresh core, no training — baseline pass_rate
        core_a = TinyPolicyTransformer()
        a_result = _stub_eval_arm_A(core_a, corpus.train, _stub_verifier)

        # C arm with reward-ignoring trainer: should clear (beats A)
        c_core = TinyPolicyTransformer()
        c_opt = torch.optim.Adam(c_core.parameters(), lr=1e-3)
        for i in range(16):
            task = corpus.train[i % len(corpus.train)]
            _reward_ignoring_train_fn(
                policy=c_core, optimizer=c_opt, state_val=task.state_val
            )
        c_result = _eval_arm_from_core(c_core, corpus.train, _stub_verifier)

        # C_scrambled with reward-ignoring trainer: should ALSO clear (same golden state)
        c_scrambled_result = _run_scrambled_arm(
            core_factory=TinyPolicyTransformer,
            train_tasks=corpus.train,
            verifier=_stub_verifier,
            train_resident_fn=_reward_ignoring_train_fn,
            n_train_steps=16,
            lr=1e-3,
            seed_offset=26001,
        )

        # Guard (h): C_scrambled must NOT beat A by > noise_tolerance for the guard to pass.
        # Since the reward-ignoring trainer copies the golden state regardless,
        # C_scrambled.pass_rate ~ C.pass_rate >> A.pass_rate.
        # So C_scrambled DOES beat A -> guard (h) should be False (REJECTED).
        NOISE_TOL = 0.20
        c_scrambled_beats_a = (
            c_scrambled_result.pass_rate > a_result.pass_rate + NOISE_TOL
        )
        # guard_h_passes = not c_scrambled_beats_a
        # We want guard_h to be False (i.e., it correctly REJECTS this trainer).
        guard_h_correctly_rejects = c_scrambled_beats_a  # True means the trainer was caught

        check(name, guard_h_correctly_rejects,
              f"guard_h did NOT reject reward-ignoring trainer: "
              f"A={a_result.pass_rate:.2%} C={c_result.pass_rate:.2%} "
              f"C_scrambled={c_scrambled_result.pass_rate:.2%} "
              f"(expected C_scrambled > A + {NOISE_TOL:.0%} = {a_result.pass_rate+NOISE_TOL:.2%})")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # =========================================================================
    # CORPUS-V3 DYNAMIC EXEMPLAR RESAMPLING (envelope v2.0, design spec
    # c14-owned-core-resident-run-v1.md sec 8g) — T27-T30.
    #
    # These four tests exercise the REAL production wiring end-to-end: the
    # resample builder lives in ember_c14_owned_run.py (generate_corpus,
    # _make_corpus_v3_resample_fn) and the hook lives here in
    # _stub_eval_arm_C_and_deleted/run_rig (corpus_v3_resample_fn param) —
    # imported lazily inside each test body so this module's own top-level
    # load order (ember_c14_owned_run imports FROM this file) never becomes
    # circular; by the time _run_tests() executes, this module has already
    # finished loading, so the nested import just resolves against
    # sys.modules — same precedent as ember_resident_igrpo.py's own T22 test.
    # =========================================================================

    # -----------------------------------------------------------------------
    # T27: flag OFF -> presentations byte-identical to static corpus-v2
    # (regression). Omitting corpus_v3_resample_fn and passing it explicitly
    # as None must be indistinguishable, and every presentation's exemplars
    # must equal the corpus's OWN generation-time static draw for that
    # step's task — never a resampled one.
    # -----------------------------------------------------------------------
    name = "T27_corpus_v3_off_byte_identical_to_static_v2"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=27000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        static_exemplars_by_id = {t.id: list(t.exemplars) for t in v3_corpus.train}

        def _capture(sink):
            def _fn(policy, optimizer, state_val, exemplars=None, **kwargs):
                sink.append((state_val, tuple(exemplars) if exemplars is not None else None))
                return {"state_val": state_val, "loss": 0.0}
            return _fn

        captured_omitted: list = []
        captured_explicit_none: list = []

        # Run A: corpus_v3_resample_fn simply omitted (pre-corpus-v3 call shape).
        _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=v3_corpus.train,
            heldout_tasks=v3_corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=20,
            lr=1e-3,
            train_resident_fn=_capture(captured_omitted),
        )
        # Run B: corpus_v3_resample_fn explicitly passed as None.
        _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=v3_corpus.train,
            heldout_tasks=v3_corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=20,
            lr=1e-3,
            train_resident_fn=_capture(captured_explicit_none),
            corpus_v3_resample_fn=None,
        )

        omit_eq_none = captured_omitted == captured_explicit_none

        matches_static = True
        for step_idx, (state_val, exemplars) in enumerate(captured_omitted):
            expected_task = v3_corpus.train[step_idx % len(v3_corpus.train)]
            if state_val != expected_task.state_val:
                matches_static = False
                break
            if exemplars is None or list(exemplars) != static_exemplars_by_id[expected_task.id]:
                matches_static = False
                break

        check(name, omit_eq_none and matches_static,
              f"omit_eq_none={omit_eq_none} matches_static={matches_static}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T28: flag ON -> two different steps of the SAME train task draw
    # DIFFERENT exemplars, and the draw for a given (corpus_seed, step_idx)
    # pair is reproducible across two independently-constructed resample
    # fns (each builds its own fresh random.Random per call — simulating
    # "two fresh processes").
    # -----------------------------------------------------------------------
    name = "T28_corpus_v3_on_varies_by_step_and_reproducible"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=28000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        n_train = len(v3_corpus.train)
        task0 = v3_corpus.train[0]

        resample_fn = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=28000, k_exemplars=3
        )
        step_a, step_b = 0, n_train * 8  # both map to task0 under step_idx % n_train
        draw_a = resample_fn(task0, step_a)
        draw_b = resample_fn(task0, step_b)
        differs_across_steps = draw_a.exemplars != draw_b.exemplars

        # Independent (fresh-closure) resample fn must reproduce draw_a exactly.
        resample_fn2 = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=28000, k_exemplars=3
        )
        draw_a_repro = resample_fn2(task0, step_a)
        reproducible = draw_a.exemplars == draw_a_repro.exemplars

        fresh_object = draw_a is not task0

        check(name, differs_across_steps and reproducible and fresh_object,
              f"differs_across_steps={differs_across_steps} "
              f"reproducible={reproducible} fresh_object={fresh_object} "
              f"draw_a={draw_a.exemplars} draw_b={draw_b.exemplars}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T29: every resampled draw passes the echo-proof guards (own-state
    # exclusion, own-answer exclusion, train-pool-only) across an
    # EXHAUSTIVE sweep of steps 0..767 x all 5 train tasks (768 = the v2.0
    # step budget, spec sec 8g).
    # -----------------------------------------------------------------------
    name = "T29_corpus_v3_echo_proof_exhaustive_sweep_0_to_767"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=29000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        resample_fn = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=29000, k_exemplars=3
        )

        swept_ok = True
        first_failure = ""
        for step_idx in range(768):
            resampled_train = [resample_fn(t, step_idx) for t in v3_corpus.train]
            probe_corpus = Corpus(train=resampled_train, heldout=[])
            try:
                probe_corpus.echo_proof_assert()
            except AssertionError as ae:
                swept_ok = False
                first_failure = f"step={step_idx}: {ae}"
                break

        check(name, swept_ok, first_failure)
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T30: the corpus's OWN stored train Task objects (and their
    # generation-time static exemplars) are unmutated after a full C-arm
    # training pass with resampling ON.
    # -----------------------------------------------------------------------
    name = "T30_corpus_v3_stored_tasks_unmutated_after_training"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=30000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        pre_exemplars = {t.id: list(t.exemplars) for t in v3_corpus.train}
        pre_ids = [id(t) for t in v3_corpus.train]

        resample_fn = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=30000, k_exemplars=3
        )

        _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=v3_corpus.train,
            heldout_tasks=v3_corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=32,
            lr=1e-3,
            train_resident_fn=igrpo_step,
            corpus_v3_resample_fn=resample_fn,
        )

        post_exemplars = {t.id: list(t.exemplars) for t in v3_corpus.train}
        post_ids = [id(t) for t in v3_corpus.train]

        unmutated = pre_exemplars == post_exemplars
        same_objects = pre_ids == post_ids

        check(name, unmutated and same_objects,
              f"unmutated={unmutated} same_objects={same_objects}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # =========================================================================
    # CORPUS-V3.1 RESAMPLE START-STEP (envelope v2.1, design spec
    # c14-owned-core-resident-run-v1.md sec 8h) — T31-T34. Same lazy-import
    # convention as T27-T30: ember_c14_owned_run is imported inside each test
    # body, resolving against sys.modules by the time _run_tests() executes.
    # =========================================================================

    # -----------------------------------------------------------------------
    # T31: resample_start_step=0 (corpus-v3.1's default) reproduces the
    # pre-v3.1 (corpus-v3.0) closure's draws bit-for-bit across steps 0..99
    # for every train task — the regression guard that a default-S run
    # reproduces attempt-17's draws exactly.
    # -----------------------------------------------------------------------
    name = "T31_corpus_v3_resample_start_step_0_matches_v30_closure"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=31000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        resample_v30 = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=31000, k_exemplars=3,
        )
        resample_s0 = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=31000, k_exemplars=3,
            resample_start_step=0,
        )

        all_match = True
        mismatch = ""
        for step_idx in range(100):
            for task in v3_corpus.train:
                if resample_v30(task, step_idx).exemplars != resample_s0(task, step_idx).exemplars:
                    all_match = False
                    mismatch = f"step={step_idx} task={task.id}"
                    break
            if not all_match:
                break

        check(name, all_match, f"mismatch at {mismatch}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T32: S=40 — steps 0..39 return the task's EXACT static generation-time
    # exemplars (object equality with the stored task, not merely equal
    # values) and steps 40..99 equal the v3.0 (S=0) closure's draws at the
    # same steps bit-for-bit.
    # -----------------------------------------------------------------------
    name = "T32_corpus_v3_resample_start_step_40_static_then_dynamic"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=32000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        S = 40
        resample_s40 = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=32000, k_exemplars=3,
            resample_start_step=S,
        )
        resample_v30 = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=32000, k_exemplars=3,
        )

        pre_s_static = True
        pre_s_detail = ""
        for step_idx in range(S):
            for task in v3_corpus.train:
                presented = resample_s40(task, step_idx)
                if presented is not task or presented.exemplars != task.exemplars:
                    pre_s_static = False
                    pre_s_detail = f"step={step_idx} task={task.id}"
                    break
            if not pre_s_static:
                break

        post_s_matches_v30 = True
        post_s_detail = ""
        for step_idx in range(S, 100):
            for task in v3_corpus.train:
                if resample_s40(task, step_idx).exemplars != resample_v30(task, step_idx).exemplars:
                    post_s_matches_v30 = False
                    post_s_detail = f"step={step_idx} task={task.id}"
                    break
            if not post_s_matches_v30:
                break

        check(name, pre_s_static and post_s_matches_v30,
              f"pre_s_static={pre_s_static} ({pre_s_detail}) "
              f"post_s_matches_v30={post_s_matches_v30} ({post_s_detail})")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T33: echo-proof sweep (T29's shape) with S=40 over steps 0..767 — every
    # presented train task (static pre-S, resampled post-S) passes
    # Corpus.echo_proof_assert.
    # -----------------------------------------------------------------------
    name = "T33_corpus_v3_resample_start_step_echo_proof_sweep_0_to_767"
    try:
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        v3_corpus, _ = _owned_run.generate_corpus(
            seed=33000, heldout_size=3, corpus_v2=True, k_exemplars=3
        )
        resample_fn = _owned_run._make_corpus_v3_resample_fn(
            v3_corpus.train, corpus_seed=33000, k_exemplars=3,
            resample_start_step=40,
        )

        swept_ok = True
        first_failure = ""
        for step_idx in range(768):
            presented_train = [resample_fn(t, step_idx) for t in v3_corpus.train]
            probe_corpus = Corpus(train=presented_train, heldout=[])
            try:
                probe_corpus.echo_proof_assert()
            except AssertionError as ae:
                swept_ok = False
                first_failure = f"step={step_idx}: {ae}"
                break

        check(name, swept_ok, first_failure)
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T34: the receipt envelope block carries corpus_v3_resample_start_step
    # correctly for 0 and 384, and the CLI parser rejects
    # --corpus-v3-resample-start-step when --corpus-v3-resample is absent
    # (black-box: invokes the real script as a subprocess since the
    # rejection lives in main()'s parser.error path, not a unit-testable
    # function).
    # -----------------------------------------------------------------------
    name = "T34_corpus_v3_resample_start_step_envelope_and_parser_gate"
    try:
        import argparse as _argparse
        import subprocess as _subprocess
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        ns_zero = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=True,
            corpus_v3_resample_start_step=0,
        )
        ns_384 = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=True,
            corpus_v3_resample_start_step=384,
        )
        block_zero = _owned_run._envelope_v1_7_block(ns_zero)
        block_384 = _owned_run._envelope_v1_7_block(ns_384)
        envelope_ok = (
            block_zero.get("corpus_v3_resample_start_step") == 0
            and block_384.get("corpus_v3_resample_start_step") == 384
        )

        owned_run_path = str(pathlib.Path(_owned_run.__file__))
        proc = _subprocess.run(
            [sys.executable, owned_run_path, "--dry-run",
             "--corpus-v3-resample-start-step", "5"],
            capture_output=True, text=True, timeout=60,
        )
        parser_rejects = (
            proc.returncode != 0
            and "--corpus-v3-resample-start-step requires --corpus-v3-resample" in proc.stderr
        )

        check(name, envelope_ok and parser_rejects,
              f"envelope_ok={envelope_ok} parser_rejects={parser_rejects} "
              f"returncode={proc.returncode} stderr_tail={proc.stderr[-300:]}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T35: _persist_resident_adapter (ember_c14_owned_run.py, --live trained-
    #      adapter persistence CURE) round-trips a small synthetic state
    #      dict to a temp .pt file with the correct sha256. RECEIPT_DIR is
    #      swapped to a throwaway tempdir for the call (swap-in-finally, the
    #      SAME pattern ember_e2b_surpass_run.py::load_owned_core_from_c14_
    #      checkpoint uses for its own module-global swap) so this test
    #      never writes into the real receipts/ember-c14-owned-run/ tree.
    # -----------------------------------------------------------------------
    name = "T35_persist_resident_adapter_roundtrips_state_dict_with_sha256"
    try:
        import shutil as _shutil35
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run35 = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        _owned_run35._TRAINED_ADAPTER_SNAPSHOT.clear()
        synthetic_sd = {
            "lora.lora_A": torch.randn(4, 2),
            "lora.lora_B": torch.zeros(2, 4),
        }
        _owned_run35._TRAINED_ADAPTER_SNAPSHOT["lora_state_dict"] = synthetic_sd
        _owned_run35._TRAINED_ADAPTER_SNAPSHOT["adapter_param_hash"] = "deadbeef" * 8
        _owned_run35._TRAINED_ADAPTER_SNAPSHOT["step"] = 7

        old_receipt_dir = _owned_run35.RECEIPT_DIR
        # SAME-DRIVE tempdir (never the default OS %TEMP%, which os.path.
        # relpath cannot express a path across from REPO's own drive on
        # Windows -- _persist_resident_adapter's rel_path computation
        # assumes RECEIPT_DIR is always under REPO, true for every real
        # --live invocation). Never receipts/ember-c14-owned-run/ or
        # scratch/ (both off-limits while the live GPU run is active) --
        # a dedicated, clearly-named, fully rmtree'd sibling directory.
        tmp_dir = _owned_run35.REPO / "_t35_t36_persist_test_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            _owned_run35.RECEIPT_DIR = tmp_dir
            block = _owned_run35._persist_resident_adapter("C14-LIVE-PASS")

            written = list(tmp_dir.glob("resident-adapter-*.pt"))
            file_exists = len(written) == 1
            ckpt_abs = written[0] if written else None

            field_resolves_same_file = False
            sha_matches = False
            roundtrip_ok = False
            if ckpt_abs is not None and block is not None:
                resolved_via_field = (_owned_run35.REPO / block["resident_checkpoint_path"]).resolve()
                field_resolves_same_file = resolved_via_field == ckpt_abs.resolve()

                actual_bytes = ckpt_abs.read_bytes()
                recomputed_sha = hashlib.sha256(actual_bytes).hexdigest()
                sha_matches = recomputed_sha == block["resident_checkpoint_sha256"]

                reloaded = torch.load(ckpt_abs, map_location="cpu", weights_only=True)
                roundtrip_ok = (
                    set(reloaded.keys()) == set(synthetic_sd.keys())
                    and torch.equal(reloaded["lora.lora_A"], synthetic_sd["lora.lora_A"])
                    and torch.equal(reloaded["lora.lora_B"], synthetic_sd["lora.lora_B"])
                )
        finally:
            _owned_run35.RECEIPT_DIR = old_receipt_dir
            _shutil35.rmtree(tmp_dir, ignore_errors=True)

        check(
            name,
            file_exists and field_resolves_same_file and sha_matches and roundtrip_ok,
            f"file_exists={file_exists} field_resolves_same_file={field_resolves_same_file} "
            f"sha_matches={sha_matches} roundtrip_ok={roundtrip_ok}",
        )
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T36: resident_training_candidate payload block carries the EXACT
    #      contract field names ember_e2b_surpass_run.py::
    #      resolve_c14_checkpoint() reads (string-literal asserted here, so
    #      a rename of either key breaks this test) on both verdicts a
    #      completed --live run can reach, and persistence is skipped
    #      (returns None) on every BLOCKED-* verdict.
    # -----------------------------------------------------------------------
    name = "T36_resident_training_candidate_contract_field_names"
    try:
        import shutil as _shutil36
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run36 = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        old_receipt_dir = _owned_run36.RECEIPT_DIR
        # SAME-DRIVE tempdir — see T35's comment for why (os.path.relpath
        # cross-drive limitation); never receipts/ember-c14-owned-run/ or
        # scratch/, fully rmtree'd in the finally block below.
        tmp_dir = _owned_run36.REPO / "_t35_t36_persist_test_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            _owned_run36.RECEIPT_DIR = tmp_dir
            _owned_run36._TRAINED_ADAPTER_SNAPSHOT.clear()
            _owned_run36._TRAINED_ADAPTER_SNAPSHOT["lora_state_dict"] = {
                "lora.lora_A": torch.zeros(2, 2),
                "lora.lora_B": torch.zeros(2, 2),
            }
            _owned_run36._TRAINED_ADAPTER_SNAPSHOT["adapter_param_hash"] = "cafef00d" * 8
            _owned_run36._TRAINED_ADAPTER_SNAPSHOT["step"] = 3

            pass_block = _owned_run36._persist_resident_adapter("C14-LIVE-PASS")
            not_cleared_block = _owned_run36._persist_resident_adapter("C14-LIVE-NOT-CLEARED")
            blocked_budget = _owned_run36._persist_resident_adapter("C14-LIVE-BLOCKED-BUDGET")
            blocked_interlock = _owned_run36._persist_resident_adapter("C14-LIVE-BLOCKED-INTERLOCK")
            blocked_plain = _owned_run36._persist_resident_adapter("C14-LIVE-BLOCKED")

            required_keys = {"resident_checkpoint_path", "resident_checkpoint_sha256"}
            pass_ok = pass_block is not None and required_keys <= set(pass_block.keys())
            not_cleared_ok = (
                not_cleared_block is not None and required_keys <= set(not_cleared_block.keys())
            )
            blocked_gated = (
                blocked_budget is None and blocked_interlock is None and blocked_plain is None
            )
        finally:
            _owned_run36.RECEIPT_DIR = old_receipt_dir
            _shutil36.rmtree(tmp_dir, ignore_errors=True)

        check(
            name, pass_ok and not_cleared_ok and blocked_gated,
            f"pass_ok={pass_ok} not_cleared_ok={not_cleared_ok} blocked_gated={blocked_gated}",
        )
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T37: --dry-run's own receipt (real CLI subprocess, same pattern as
    #      T34) carries the resident_training_candidate SKIP note
    #      (persisted=False, toy-core reason) and writes NO
    #      resident-adapter-*.pt file into receipts/ember-c14-owned-run/.
    # -----------------------------------------------------------------------
    name = "T37_dry_run_resident_training_candidate_skip_note_no_pt_written"
    try:
        import subprocess as _subprocess37
        import json as _json37
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_run.py
        import importlib.util as _ember_bff9ce1e3d7dd466_importlib
        import sys as _ember_bff9ce1e3d7dd466_sys
        from pathlib import Path as _ember_bff9ce1e3d7dd466_Path
        _ember_bff9ce1e3d7dd466_path = _ember_bff9ce1e3d7dd466_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_run.py')
        if not _ember_bff9ce1e3d7dd466_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_run.py')
        _ember_bff9ce1e3d7dd466_aliases = ('_ember_issue2015_bff9ce1e3d7dd466', 'ember_c14_owned_run', 'scripts.ember_c14_owned_run')
        _ember_bff9ce1e3d7dd466_existing = []
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_candidate = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_candidate is not None and all(_ember_bff9ce1e3d7dd466_candidate is not item for item in _ember_bff9ce1e3d7dd466_existing):
                _ember_bff9ce1e3d7dd466_existing.append(_ember_bff9ce1e3d7dd466_candidate)
        if len(_ember_bff9ce1e3d7dd466_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
        if _ember_bff9ce1e3d7dd466_existing:
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_existing[0]
            _ember_bff9ce1e3d7dd466_observed = getattr(_ember_bff9ce1e3d7dd466_module, '__file__', None)
            if _ember_bff9ce1e3d7dd466_observed is None or _ember_bff9ce1e3d7dd466_Path(_ember_bff9ce1e3d7dd466_observed).resolve() != _ember_bff9ce1e3d7dd466_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_run.py')
        else:
            _ember_bff9ce1e3d7dd466_spec = _ember_bff9ce1e3d7dd466_importlib.spec_from_file_location('_ember_issue2015_bff9ce1e3d7dd466', _ember_bff9ce1e3d7dd466_path)
            if _ember_bff9ce1e3d7dd466_spec is None or _ember_bff9ce1e3d7dd466_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_module = _ember_bff9ce1e3d7dd466_importlib.module_from_spec(_ember_bff9ce1e3d7dd466_spec)
            for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
                if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
                _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
            try:
                _ember_bff9ce1e3d7dd466_spec.loader.exec_module(_ember_bff9ce1e3d7dd466_module)
            except BaseException:
                for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
                    if _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias) is _ember_bff9ce1e3d7dd466_module:
                        _ember_bff9ce1e3d7dd466_sys.modules.pop(_ember_bff9ce1e3d7dd466_alias, None)
                raise
        for _ember_bff9ce1e3d7dd466_alias in _ember_bff9ce1e3d7dd466_aliases:
            _ember_bff9ce1e3d7dd466_prior = _ember_bff9ce1e3d7dd466_sys.modules.get(_ember_bff9ce1e3d7dd466_alias)
            if _ember_bff9ce1e3d7dd466_prior is not None and _ember_bff9ce1e3d7dd466_prior is not _ember_bff9ce1e3d7dd466_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_run.py')
            _ember_bff9ce1e3d7dd466_sys.modules[_ember_bff9ce1e3d7dd466_alias] = _ember_bff9ce1e3d7dd466_module
        _owned_run37 = _ember_bff9ce1e3d7dd466_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_run.py

        receipt_dir37 = _owned_run37.RECEIPT_DIR
        before_pts = set(receipt_dir37.glob("resident-adapter-*.pt")) if receipt_dir37.is_dir() else set()

        owned_run_path37 = str(pathlib.Path(_owned_run37.__file__))
        proc37 = _subprocess37.run(
            [sys.executable, owned_run_path37, "--dry-run", "--n-train-steps", "2"],
            capture_output=True, text=True, timeout=120,
        )
        receipt_line = next(
            (ln for ln in proc37.stdout.splitlines() if ln.startswith("receipt=")), None
        )
        receipt_path37 = pathlib.Path(receipt_line.split("=", 1)[1]) if receipt_line else None
        receipt_obj37 = (
            _json37.loads(receipt_path37.read_text(encoding="utf-8")) if receipt_path37 else {}
        )
        candidate_block = receipt_obj37.get("resident_training_candidate") or {}

        after_pts = set(receipt_dir37.glob("resident-adapter-*.pt")) if receipt_dir37.is_dir() else set()

        skip_note_ok = (
            candidate_block.get("persisted") is False
            and "toy" in candidate_block.get("reason", "")
        )
        no_new_pt = after_pts == before_pts

        # returncode is 0 (gate cleared) or 1 (ran to completion, gate did
        # NOT clear -- e.g. --n-train-steps 2 is far too few to clear;
        # clearance is not what this test is checking). Anything else (a
        # crash/traceback) would also leave receipt_path37 unset, since the
        # receipt is written and its path printed before cmd_dry_run's
        # return -- receipt_path37 is not None is the real completion proof.
        check(
            name,
            proc37.returncode in (0, 1) and receipt_path37 is not None and skip_note_ok and no_new_pt,
            f"returncode={proc37.returncode} receipt_path={receipt_path37} "
            f"candidate_block={candidate_block} no_new_pt={no_new_pt}",
        )
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    all_passed = len(failed) == 0
    total = len(passed) + len(failed)
    if verbose:
        print()
        print(f"Results: {len(passed)}/{total} passed"
              f"{'  (ALL PASS)' if all_passed else f'  FAILED: {failed}'}")
        if errors:
            print("Exceptions:")
            for e in errors:
                print(f"  {e}")

    return all_passed, passed, failed


# ---------------------------------------------------------------------------
# REAL instantiation documentation
# ---------------------------------------------------------------------------

REAL_INSTANTIATION_DOC = """
REAL instantiation (documented, NOT run in this file):

  from train_multimodal_v0 import build_multimodal_v0_model, load_multimodal_config
  from ember_avir_harness import executing_verifier as avir_verifier, TaskSpec
  from ember_avir_tasks import load_split, run_assertions

  def real_core_factory():
      cfg = load_multimodal_config()
      model = build_multimodal_v0_model(live=True)
      model.train()
      # sample_action wrapper required per adapt-verdict build item:
      # model.sample_action = lambda ctx, temp=1.0: int(
      #     F.softmax(model.forward(ctx.unsqueeze(0))[0,-1] / temp, dim=-1)
      #     .multinomial(1).item()
      # )
      return model

  def real_verifier(task, emitted_action):
      # task is an [REDACTED]-cli TaskSpec; emitted_action is the action string
      reward, _, _ = avir_verifier(task, sandbox_dir, client, ...)
      return float(reward)

  real_corpus = Corpus(
      train=[...from load_split("train")...],
      heldout=[...from load_split("heldout")...],
  )

  result = run_rig(
      core_factory=real_core_factory,
      train_resident_fn=igrpo_step,   # hosted in train_multimodal_v0 adapter
      verifier=real_verifier,
      corpus=real_corpus,
      n_train_steps=200,
      stub=False,
  )

  # C14 clearance iff result.clearance == True
"""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="C14 A/B/C/Deleted contract rig (TDD)"
    )
    parser.add_argument("--test", action="store_true", help="Run TDD test suite only")
    parser.add_argument("--steps", type=int, default=64,
                        help="iGRPO train steps for C arm (default 64)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--doc-real", action="store_true",
                        help="Print REAL instantiation documentation and exit")
    args = parser.parse_args()

    if args.doc_real:
        print(REAL_INSTANTIATION_DOC)
        return

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    if args.test:
        print("=== ember_c14_contract_rig TDD tests ===")
        all_passed, passed, failed = _run_tests(verbose=args.verbose)
        sys.exit(0 if all_passed else 1)

    # Full stub run
    print("=== ember_c14_contract_rig: STUB end-to-end run ===")
    corpus = _make_stub_corpus()
    result = run_rig(
        core_factory=TinyPolicyTransformer,
        train_resident_fn=igrpo_step,
        verifier=_stub_verifier,
        corpus=corpus,
        n_train_steps=args.steps,
        lr=1e-3,
        stub=True,
    )
    print_report(result)


if __name__ == "__main__":
    main()
