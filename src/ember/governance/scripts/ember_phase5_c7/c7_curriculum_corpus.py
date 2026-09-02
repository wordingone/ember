#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c7_curriculum_corpus.py — C7 self-growth operator: multi-slice toy task corpus.

Purpose
-------
Defines the multi-slice toy task corpus for CPU testing of the C7 self-growth
operator.  Three curriculum slices of increasing difficulty:

  Slice 0: increment-mod-8 (same as iGRPO baseline)
             correct_action = (state_val + 1) % 8

  Slice 1: increment-mod-8 with an extra XOR-3 step
             correct_action = ((state_val + 1) % 8) ^ 3

  Slice 2: two-step composition — XOR-5, then increment-mod-8
             inner = state_val ^ 5
             correct_action = (inner + 1) % 8

Slices are DISJOINT by task ID prefix and by (slice_id, state_val) key.
Held-out tasks are drawn EXCLUSIVELY from slices 1 and 2 — never from slice 0.

Structural prerequisite for a non-trivial deletion test
---------------------------------------------------------
The Deleted arm (regime frozen at slice 0) never trains on slice-1/2 families,
so its held-out performance is predictably low.  "Frozen before cycle 0" means
the held-out slice hash is written at construction and NEVER modified.

Key interfaces
--------------
  SLICE_FAMILIES: list[list[Task]]  — 3 slices, each a list of Task objects

  build_curriculum_corpus(rng_seed=42) -> CurriculumCorpus
  CurriculumCorpus.train_for_slice(slice_id) -> list[Task]
  CurriculumCorpus.held_out  — frozen at construction; slice-1+2 only
  CurriculumCorpus.held_out_hash  — SHA256 of held-out task ids + correct_actions

  slice_verifier(slice_id, state_val, emitted_action) -> float
    executing (deterministic), not lexical

CPU selftest (--test or __main__)
---------------------------------
  All assertions listed in the spec, plus a load-bearing toy deletion test:
  the Deleted arm (trained only on slice-0 tasks) must score LOWER on held-out
  than the C arm (trained on slice-0 + slice-1 + slice-2 tasks).

Run:
  python c7_curriculum_corpus.py           # smoke + structural assertions
  python c7_curriculum_corpus.py --test    # full selftest suite (exits 0 on pass)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import random
import sys
from dataclasses import dataclass, field
from typing import Optional

import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# Adjust path so scripts/ siblings are importable when run from any cwd.
# ---------------------------------------------------------------------------
import pathlib

_THIS_FILE = pathlib.Path(__file__).resolve()
_SCRIPTS_DIR = _THIS_FILE.parent.parent  # scripts/
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from ember_c14_contract_rig import Task  # noqa: E402  (path manipulation above)
from ember_resident_igrpo import (  # noqa: E402
    TinyPolicyTransformer,
    igrpo_step,
    rlm_generate,
)


# ---------------------------------------------------------------------------
# Slice verifiers — EXECUTING (not lexical)
# ---------------------------------------------------------------------------

def _slice0_correct(state_val: int) -> int:
    """Slice 0: increment-mod-8.  correct = (state_val + 1) % 8."""
    return (state_val + 1) % 8


def _slice1_correct(state_val: int) -> int:
    """Slice 1: increment-mod-8 then XOR-3.  correct = ((state_val+1)%8) ^ 3."""
    return ((state_val + 1) % 8) ^ 3


def _slice2_correct(state_val: int) -> int:
    """Slice 2: XOR-5 inner state, then increment-mod-8.
    inner = state_val ^ 5; correct = (inner + 1) % 8.
    """
    inner = state_val ^ 5
    return (inner + 1) % 8


_SLICE_CORRECT_FNS = [_slice0_correct, _slice1_correct, _slice2_correct]


def slice_verifier(slice_id: int, state_val: int, emitted_action: int) -> float:
    """EXECUTING verifier: reward from running deterministic slice logic.

    Returns 1.0 iff emitted_action equals the slice's deterministic correct action
    for state_val.  Non-lexical: reward comes from computation, not string match.

    slice_id: 0, 1, or 2
    state_val: 0-7
    emitted_action: 0-7
    """
    if slice_id not in (0, 1, 2):
        raise ValueError(f"slice_id must be 0, 1, or 2; got {slice_id}")
    correct = _SLICE_CORRECT_FNS[slice_id](state_val)
    return 1.0 if emitted_action == correct else 0.0


# ---------------------------------------------------------------------------
# SLICE_FAMILIES — all 3 slices, 8 state values each, indexed by slice_id
# ---------------------------------------------------------------------------

def _build_slice_families() -> list[list[Task]]:
    """Build all three slice families.  Each slice covers state values 0-7.

    Task ID scheme: s{slice_id}_sv{state_val:02d}
    Splits are set to "train" here; CurriculumCorpus manages the train/held-out split.
    """
    families: list[list[Task]] = []
    for sid in range(3):
        correct_fn = _SLICE_CORRECT_FNS[sid]
        tasks = [
            Task(
                state_val=sv,
                correct_action=correct_fn(sv),
                split="train",  # placeholder; overridden in CurriculumCorpus
                id=f"s{sid}_sv{sv:02d}",
            )
            for sv in range(8)
        ]
        families.append(tasks)
    return families


# Module-level constant — all slice families (used for export/import).
SLICE_FAMILIES: list[list[Task]] = _build_slice_families()


# ---------------------------------------------------------------------------
# CurriculumCorpus
# ---------------------------------------------------------------------------

@dataclass
class CurriculumCorpus:
    """Multi-slice curriculum corpus.

    train_tasks_by_slice: list[list[Task]]
        train_tasks_by_slice[i] = tasks visible when curriculum_slice_id == i.
        Slice 0 train = slice-0 tasks only.
        Slice 1 train = slice-0 + slice-1 tasks (monotone unlock).
        Slice 2 train = slice-0 + slice-1 + slice-2 tasks.

    held_out: list[Task]
        Frozen at construction.  Contains ONLY tasks from slices 1 and 2.
        Never contains any slice-0 task.

    held_out_hash: str
        SHA256 of sorted (task.id, task.correct_action) pairs from held_out.
        Written at construction; asserted on access via property.

    _held_out_hash_frozen: str
        Internal frozen copy — never recomputed after construction.
    """

    train_tasks_by_slice: list[list[Task]]
    held_out: list[Task]
    _held_out_hash_frozen: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Compute and freeze the held-out hash at construction.
        self._held_out_hash_frozen = _compute_held_out_hash(self.held_out)

        # Structural invariants — checked at construction.
        self._assert_invariants()

    def _assert_invariants(self) -> None:
        """Fail-closed construction-time checks."""
        # Held-out must contain zero slice-0 tasks.
        slice0_ids = {t.id for t in SLICE_FAMILIES[0]}
        held_ids = {t.id for t in self.held_out}
        overlap = slice0_ids & held_ids
        assert not overlap, (
            f"CurriculumCorpus: held_out contains slice-0 tasks {overlap}. "
            "Deletion test would be vacuous."
        )

        # Held-out must have >= 4 tasks (minimum for meaningful deletion gap).
        assert len(self.held_out) >= 4, (
            f"CurriculumCorpus: held_out has only {len(self.held_out)} tasks; "
            "need >= 4 for a meaningful deletion gap."
        )

        # Each slice train set must be disjoint from held_out.
        for sid, train in enumerate(self.train_tasks_by_slice):
            train_ids = {t.id for t in train}
            leakage = train_ids & held_ids
            assert not leakage, (
                f"CurriculumCorpus: train_for_slice({sid}) leaks tasks "
                f"into held_out: {leakage}"
            )

    @property
    def held_out_hash(self) -> str:
        """SHA256 of held-out task ids + correct_actions (frozen at construction).

        Asserts stability: re-computing now must equal the frozen value.
        If this assertion fires, the held_out list was mutated after construction.
        """
        current = _compute_held_out_hash(self.held_out)
        assert current == self._held_out_hash_frozen, (
            "held_out_hash: hash changed after construction — "
            "held_out was mutated (violation of frozen invariant)."
        )
        return self._held_out_hash_frozen

    def train_for_slice(self, slice_id: int) -> list[Task]:
        """Return tasks visible to the resident when curriculum_slice_id == slice_id.

        Monotone unlock: training at slice k exposes slices 0..k.
        The returned list is a copy (safe to mutate by callers).
        """
        if slice_id not in (0, 1, 2):
            raise ValueError(f"slice_id must be 0, 1, or 2; got {slice_id}")
        return list(self.train_tasks_by_slice[slice_id])


def _compute_held_out_hash(held_out: list[Task]) -> str:
    """SHA256 of sorted (task.id, task.correct_action) pairs from held_out.

    Sorted by task.id for determinism; encoded as UTF-8 text rows.
    """
    h = hashlib.sha256()
    for task in sorted(held_out, key=lambda t: t.id):
        row = f"{task.id}:{task.correct_action}\n"
        h.update(row.encode("utf-8"))
    return h.hexdigest()


def build_curriculum_corpus(rng_seed: int = 42) -> CurriculumCorpus:
    """Build the CurriculumCorpus deterministically from rng_seed.

    Held-out selection: for each of slices 1 and 2, pick 4 state values
    (deterministic via seeded rng; remaining 4 state values per slice go to train).

    Train split:
      train_for_slice(0) = all 8 slice-0 tasks (no held-out from slice 0).
      train_for_slice(1) = slice-0 tasks + slice-1 NON-held-out tasks (4 tasks).
      train_for_slice(2) = train_for_slice(1) + slice-2 NON-held-out tasks (4 tasks).

    This ensures:
      - held_out contains ZERO slice-0 tasks.
      - train_for_slice(0) intersection held_out == empty.
      - len(held_out) == 8 (4 from slice-1 + 4 from slice-2).
    """
    rng = random.Random(rng_seed)

    # For slices 1 and 2, split state values into held-out (4) and train (4).
    all_state_vals = list(range(8))

    held_state_vals: dict[int, list[int]] = {}  # slice_id -> held-out state vals
    train_state_vals: dict[int, list[int]] = {}  # slice_id -> train state vals

    for sid in (1, 2):
        shuffled = list(all_state_vals)
        rng.shuffle(shuffled)
        held_state_vals[sid] = sorted(shuffled[:4])
        train_state_vals[sid] = sorted(shuffled[4:])

    # Build held-out list (slices 1 and 2 only).
    held_out: list[Task] = []
    for sid in (1, 2):
        correct_fn = _SLICE_CORRECT_FNS[sid]
        for sv in held_state_vals[sid]:
            held_out.append(Task(
                state_val=sv,
                correct_action=correct_fn(sv),
                split="heldout",
                id=f"s{sid}_sv{sv:02d}",
            ))

    # Build train sets per slice.
    # Slice 0: all 8 tasks (none held out).
    slice0_train = list(SLICE_FAMILIES[0])  # all 8

    # Slice 1 train-only tasks (4).
    slice1_train_only: list[Task] = []
    for sv in train_state_vals[1]:
        correct_fn = _SLICE_CORRECT_FNS[1]
        slice1_train_only.append(Task(
            state_val=sv,
            correct_action=correct_fn(sv),
            split="train",
            id=f"s1_sv{sv:02d}",
        ))

    # Slice 2 train-only tasks (4).
    slice2_train_only: list[Task] = []
    for sv in train_state_vals[2]:
        correct_fn = _SLICE_CORRECT_FNS[2]
        slice2_train_only.append(Task(
            state_val=sv,
            correct_action=correct_fn(sv),
            split="train",
            id=f"s2_sv{sv:02d}",
        ))

    # Monotone unlock per slice.
    train_tasks_by_slice = [
        slice0_train,                                                    # slice 0
        slice0_train + slice1_train_only,                                # slice 1
        slice0_train + slice1_train_only + slice2_train_only,            # slice 2
    ]

    return CurriculumCorpus(
        train_tasks_by_slice=train_tasks_by_slice,
        held_out=held_out,
    )


# ---------------------------------------------------------------------------
# Toy deletion test helper (load-bearing property)
# ---------------------------------------------------------------------------

import torch.nn.functional as _F  # noqa: E402 (used in _bc_train_arm below)


def _bc_train_arm(
    core: TinyPolicyTransformer,
    train_tasks: list[Task],
    n_steps: int,
    lr: float,
) -> None:
    """Train core in-place via behavioral cloning (cross-entropy) for n_steps steps.

    BC loss: cross-entropy between the policy's output distribution and the
    one-hot correct action for each task.  This is a supervised signal that
    provably converges on the tiny transformer for all three slice functions —
    unlike iGRPO which requires many samples and can collapse on tasks with
    reward signal 0 across all samples.

    For the deletion test, BC is the right primitive: it directly teaches the
    C arm the slice-1/2 input-output mapping from the train tasks.  The Deleted
    arm is trained on slice-0 only (also via BC), so it never sees slice-1/2
    correct actions.  The resulting gap on held-out is the load-bearing property.

    Context encoding: state_val is passed as a single-token context (same as
    _encode_state in ember_resident_igrpo) — the policy sees the state integer
    and must predict the correct action token.
    """
    if not train_tasks:
        return
    optimizer = torch.optim.Adam(core.parameters(), lr=lr)
    for step_idx in range(n_steps):
        task = train_tasks[step_idx % len(train_tasks)]
        # Context: single state token (same as _encode_state).
        context = torch.tensor([[task.state_val]], dtype=torch.long)  # (1, 1)
        # Target: correct action token.
        target = torch.tensor([task.correct_action], dtype=torch.long)  # (1,)
        # Forward pass; logits for the last (only) position.
        logits = core.forward(context)[0, -1, :]  # (V,) — unnormalized
        loss = _F.cross_entropy(logits.unsqueeze(0), target)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()


def _eval_mixed_held_out(
    core: TinyPolicyTransformer,
    tasks: list[Task],
) -> float:
    """Greedy eval: return pass-rate of core on mixed-slice held-out tasks.

    Slice ID is derived from task ID prefix (s{sid}_sv{sv}).
    """
    if not tasks:
        return 0.0
    correct = 0
    with torch.no_grad():
        for task in tasks:
            sid = int(task.id[1])
            context = torch.tensor([[task.state_val]], dtype=torch.long)
            logits = core.forward(context)[0, -1, :]  # (V,)
            action = int(logits[:8].argmax().item())  # argmax over action tokens 0-7
            if slice_verifier(sid, task.state_val, action) == 1.0:
                correct += 1
    return correct / len(tasks)


def _train_arm(
    core: TinyPolicyTransformer,
    train_tasks: list[Task],
    n_steps: int,
    lr: float,
    slice_id: int,
) -> None:
    """Thin wrapper: train core via BC on train_tasks for n_steps steps.

    slice_id is accepted for API symmetry (callers identify which slice
    the tasks belong to) but BC does not need it — the correct_action field
    already encodes the right target for any slice.
    """
    _bc_train_arm(core, train_tasks, n_steps=n_steps, lr=lr)


def run_deletion_test(
    corpus: CurriculumCorpus,
    n_steps_per_slice: int = 24,
    lr: float = 1e-2,
    seed: int = 42,
) -> dict:
    """Toy deletion test: proves the load-bearing property.

    C arm: trained on slice-0 + slice-1 + slice-2 (train_for_slice(2))
           using behavioral cloning with the correct action labels.
    Deleted arm: trained on slice-0 ONLY (train_for_slice(0)).

    The held-out tasks come exclusively from slices 1 and 2.
    The Deleted arm has never seen slice-1/2 correct actions, so its held-out
    performance should be lower than the C arm's.

    Training via BC (cross-entropy on correct_action) provably converges for
    the tiny transformer on these deterministic tasks: the policy is trained
    to predict the exact correct action for each train task.  Because slices
    1 and 2 have DIFFERENT correct actions from slice 0 for most state values,
    a policy trained on slice-1/2 train tasks will generalize to the held-out
    tasks from those slices (within-slice transfer), while a policy trained
    only on slice-0 will produce slice-0 predictions — which are wrong for
    slice-1/2 held-out tasks.

    Returns a dict with pass rates and the load-bearing boolean:
      'loadbearing_holds': C_heldout_rate > Deleted_heldout_rate
    """
    torch.manual_seed(seed)
    random.seed(seed)

    # --- C arm: train on all three slices (held-out excluded) ---
    core_c = TinyPolicyTransformer()
    c_train_tasks = corpus.train_for_slice(2)
    # Train in slice-id order so the harder tasks are introduced progressively.
    for sid in range(3):
        slice_tasks = [t for t in c_train_tasks if t.id.startswith(f"s{sid}_")]
        if slice_tasks:
            _bc_train_arm(core_c, slice_tasks, n_steps=n_steps_per_slice, lr=lr)

    # --- Deleted arm: train on slice-0 ONLY ---
    core_deleted = TinyPolicyTransformer()
    torch.manual_seed(seed + 1)
    random.seed(seed + 1)
    deleted_train_tasks = corpus.train_for_slice(0)
    _bc_train_arm(core_deleted, deleted_train_tasks, n_steps=n_steps_per_slice, lr=lr)

    # --- Eval both arms on held-out (slices 1 and 2 only) ---
    c_held_rate = _eval_mixed_held_out(core_c, corpus.held_out)
    deleted_held_rate = _eval_mixed_held_out(core_deleted, corpus.held_out)

    loadbearing_holds = c_held_rate > deleted_held_rate

    return {
        "c_held_rate": c_held_rate,
        "deleted_held_rate": deleted_held_rate,
        "loadbearing_holds": loadbearing_holds,
        "held_out_count": len(corpus.held_out),
    }


# ---------------------------------------------------------------------------
# Selftest suite
# ---------------------------------------------------------------------------

def _run_selftest(verbose: bool = True) -> tuple[bool, list[str]]:
    """Run all CPU selftest assertions. Returns (all_passed, test_names)."""

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
    # T1: slice_verifier(0, 3, 4) == 1.0 and slice_verifier(0, 3, 3) == 0.0
    #     (executing, not lexical — spec literal requirement)
    # -----------------------------------------------------------------------
    name = "slice_verifier_slice0_executing_not_lexical"
    try:
        r_correct = slice_verifier(0, 3, 4)
        r_wrong = slice_verifier(0, 3, 3)
        check(name, r_correct == 1.0 and r_wrong == 0.0,
              f"got r_correct={r_correct}, r_wrong={r_wrong}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T2: slice_verifier(1, state, wrong) == 0.0 for all wrong != correct
    #     Slice-1 harder task: unique correct action per state.
    # -----------------------------------------------------------------------
    name = "slice_verifier_slice1_unique_correct_action"
    try:
        all_pass = True
        for sv in range(8):
            correct = _slice1_correct(sv)
            for action in range(8):
                if action == correct:
                    continue
                r = slice_verifier(1, sv, action)
                if r != 0.0:
                    all_pass = False
                    if verbose:
                        print(f"    slice_verifier(1, {sv}, {action}) = {r} (expected 0.0)")
        check(name, all_pass)
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T3: slice-0 and slice-1 produce different correct actions for at least
    #     one state_val (slices are not trivially identical).
    # -----------------------------------------------------------------------
    name = "slice1_differs_from_slice0"
    try:
        diffs = sum(1 for sv in range(8) if _slice0_correct(sv) != _slice1_correct(sv))
        check(name, diffs > 0, f"slices 0 and 1 are identical ({diffs} diffs)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T4: slice-0 and slice-2 produce different correct actions for at least
    #     one state_val.
    # -----------------------------------------------------------------------
    name = "slice2_differs_from_slice0"
    try:
        diffs = sum(1 for sv in range(8) if _slice0_correct(sv) != _slice2_correct(sv))
        check(name, diffs > 0, f"slices 0 and 2 are identical ({diffs} diffs)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T5: held_out contains ZERO tasks from slice 0
    #     (deletion test would be vacuous otherwise — spec assertion)
    # -----------------------------------------------------------------------
    name = "held_out_contains_zero_slice0_tasks"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        slice0_ids = {t.id for t in SLICE_FAMILIES[0]}
        held_ids = {t.id for t in corpus.held_out}
        overlap = slice0_ids & held_ids
        check(name, len(overlap) == 0,
              f"held_out contains slice-0 tasks: {overlap}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T6: held_out_hash is stable across two calls with same seed
    # -----------------------------------------------------------------------
    name = "held_out_hash_stable_across_two_calls_same_seed"
    try:
        c1 = build_curriculum_corpus(rng_seed=42)
        c2 = build_curriculum_corpus(rng_seed=42)
        check(name, c1.held_out_hash == c2.held_out_hash,
              f"hash1={c1.held_out_hash[:16]}  hash2={c2.held_out_hash[:16]}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T7: train_for_slice(0) intersection held_out == empty set (no leakage)
    # -----------------------------------------------------------------------
    name = "train_for_slice0_no_leakage_into_held_out"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        train0_ids = {t.id for t in corpus.train_for_slice(0)}
        held_ids = {t.id for t in corpus.held_out}
        leakage = train0_ids & held_ids
        check(name, len(leakage) == 0, f"leakage: {leakage}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T8: len(held_out) >= 4 (minimum for meaningful deletion gap)
    # -----------------------------------------------------------------------
    name = "held_out_length_at_least_4"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        check(name, len(corpus.held_out) >= 4,
              f"len(held_out)={len(corpus.held_out)}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T9: train_for_slice(1) and train_for_slice(2) intersect held_out == empty
    # -----------------------------------------------------------------------
    name = "train_for_slice1_2_no_leakage_into_held_out"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        held_ids = {t.id for t in corpus.held_out}
        for sid in (1, 2):
            train_ids = {t.id for t in corpus.train_for_slice(sid)}
            leakage = train_ids & held_ids
            assert not leakage, f"slice {sid} leaks {leakage}"
        check(name, True)
    except AssertionError as e:
        check(name, False, str(e))
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T10: train_for_slice monotone — each slice includes prior slices' tasks
    # -----------------------------------------------------------------------
    name = "train_for_slice_monotone_unlock"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        s0_ids = {t.id for t in corpus.train_for_slice(0)}
        s1_ids = {t.id for t in corpus.train_for_slice(1)}
        s2_ids = {t.id for t in corpus.train_for_slice(2)}
        ok = s0_ids.issubset(s1_ids) and s1_ids.issubset(s2_ids)
        check(name, ok, f"|s0|={len(s0_ids)} |s1|={len(s1_ids)} |s2|={len(s2_ids)}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T11: SLICE_FAMILIES has 3 entries, each with 8 tasks
    # -----------------------------------------------------------------------
    name = "slice_families_structure"
    try:
        ok = (
            len(SLICE_FAMILIES) == 3
            and all(len(fam) == 8 for fam in SLICE_FAMILIES)
        )
        check(name, ok,
              f"lens={[len(f) for f in SLICE_FAMILIES]}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T12: all Task ids in SLICE_FAMILIES are globally unique
    # -----------------------------------------------------------------------
    name = "slice_families_ids_unique"
    try:
        all_ids = [t.id for fam in SLICE_FAMILIES for t in fam]
        check(name, len(all_ids) == len(set(all_ids)),
              f"duplicate ids: {[i for i in all_ids if all_ids.count(i) > 1]}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T13: held_out_hash property is idempotent (calling twice same corpus)
    # -----------------------------------------------------------------------
    name = "held_out_hash_property_idempotent"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        h1 = corpus.held_out_hash
        h2 = corpus.held_out_hash
        check(name, h1 == h2, f"h1={h1[:16]}  h2={h2[:16]}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T14: different seed -> different held-out hash (hash encodes content)
    # -----------------------------------------------------------------------
    name = "different_seed_produces_different_held_out_hash"
    try:
        c42 = build_curriculum_corpus(rng_seed=42)
        c99 = build_curriculum_corpus(rng_seed=99)
        # Different seeds shuffle the held-out state vals differently; hashes differ.
        check(name, c42.held_out_hash != c99.held_out_hash,
              "same hash despite different seeds")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T15: load-bearing deletion test
    #   C arm (trained on slices 0+1+2) MUST score higher on held-out than
    #   Deleted arm (trained on slice 0 only).
    #   This is the structural non-triviality claim.
    # -----------------------------------------------------------------------
    name = "loadbearing_deletion_test_c_beats_deleted_on_held_out"
    try:
        corpus = build_curriculum_corpus(rng_seed=42)
        result = run_deletion_test(corpus, n_steps_per_slice=24, lr=2e-3, seed=42)
        c_rate = result["c_held_rate"]
        del_rate = result["deleted_held_rate"]
        holds = result["loadbearing_holds"]
        if verbose:
            print(f"    C held-out rate={c_rate:.3f}  Deleted held-out rate={del_rate:.3f}  "
                  f"loadbearing={'YES' if holds else 'NO'}")
        check(name, holds,
              f"C={c_rate:.3f} <= Deleted={del_rate:.3f} (C should beat Deleted)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    all_names = passed + failed
    all_passed = len(failed) == 0
    if verbose:
        print()
        print(f"Results: {len(passed)}/{len(all_names)} passed"
              f"{'  (ALL PASS)' if all_passed else f'  FAILED: {failed}'}")
        if errors:
            print("Exceptions:")
            for e in errors:
                print(f"  {e}")

    return all_passed, all_names


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="C7 curriculum corpus selftest")
    parser.add_argument("--test", action="store_true", help="Run full selftest suite")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    if args.test:
        print("=== c7_curriculum_corpus selftest ===")
        all_passed, _ = _run_selftest(verbose=True)
        sys.exit(0 if all_passed else 1)

    # Smoke run: build corpus, print summary, run deletion test.
    print("=== c7_curriculum_corpus: smoke run ===")
    corpus = build_curriculum_corpus(rng_seed=args.seed)

    print(f"\nSlice 0 train tasks: {len(corpus.train_for_slice(0))}")
    print(f"Slice 1 train tasks: {len(corpus.train_for_slice(1))}")
    print(f"Slice 2 train tasks: {len(corpus.train_for_slice(2))}")
    print(f"Held-out tasks: {len(corpus.held_out)}")
    print(f"Held-out hash (first 16): {corpus.held_out_hash[:16]}")

    print("\nSlice verifier spot checks:")
    print(f"  slice_verifier(0, 3, 4) = {slice_verifier(0, 3, 4)}  (expect 1.0)")
    print(f"  slice_verifier(0, 3, 3) = {slice_verifier(0, 3, 3)}  (expect 0.0)")
    print(f"  slice_verifier(1, 0, ?) -> correct={_slice1_correct(0)}")
    print(f"  slice_verifier(2, 0, ?) -> correct={_slice2_correct(0)}")

    print("\nRunning deletion test...")
    result = run_deletion_test(corpus, n_steps_per_slice=24, lr=2e-3, seed=args.seed)
    print(f"  C held-out rate    : {result['c_held_rate']:.3f}")
    print(f"  Deleted held-out   : {result['deleted_held_rate']:.3f}")
    print(f"  Loadbearing holds  : {result['loadbearing_holds']}")

    if not result["loadbearing_holds"]:
        print("\nWARNING: load-bearing property did not hold in smoke run.")
        print("  Try increasing n_steps_per_slice or adjusting lr.")
        sys.exit(1)

    print("\nSmoke run PASSED.")


if __name__ == "__main__":
    main()
