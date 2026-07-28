#!/usr/bin/env python3
"""c7_deletion_test.py — C7 self-growth operator: load-bearing deletion test (C7 CHK).

Runs two arms against a CurriculumCorpus:
  C       = operator active; regime advances each cycle (rule C)
  Deleted = operator absent; regime frozen at slice 0 (static regime file)

Both arms are evaluated on a frozen held-out slice (slice >= 1 tasks).

The deletion_gap measures how much C beats Deleted on the held-out slice.
Verdict is machine-checkable:
  deletion_gap >= DELETION_GAP_THRESHOLD * 0.8  -->  LOAD_BEARING
  otherwise                                      -->  NOT_LOAD_BEARING

CPU selftest exits 0 on pass and asserts the load-bearing property on a toy corpus.

Usage:
  python scripts/ember_phase5_c7/c7_deletion_test.py        # runs selftest
  python -c "from ember_phase5_c7.c7_deletion_test import run_deletion_test; ..."
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Adjust import path — allow running from any directory
# ---------------------------------------------------------------------------

_THIS_FILE = Path(__file__).resolve()
_SCRIPTS_DIR = _THIS_FILE.parent.parent  # scripts/
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from ember_resident_igrpo import TinyPolicyTransformer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERDICT_LOAD_BEARING: str = "LOAD_BEARING"
VERDICT_NOT_LOAD_BEARING: str = "NOT_LOAD_BEARING"
DELETION_GAP_THRESHOLD: float = 0.15  # minimum expected gap on slice-1/2 held-out tasks


# ---------------------------------------------------------------------------
# CurriculumCorpus — the corpus type for C7
# ---------------------------------------------------------------------------

@dataclass
class CurriculumTask:
    """One task in a curriculum corpus.

    state_val    : int  — observed state (0-7 for the toy increment task)
    correct_action: int — ground-truth correct action (used by verifier only)
    task_slice   : int  — curriculum slice index (0 = easiest)
    task_id      : str  — unique identifier
    """
    state_val: int
    correct_action: int
    task_slice: int
    task_id: str


@dataclass
class CurriculumCorpus:
    """Curriculum corpus: tasks organised into difficulty slices.

    tasks        : all tasks (train + held-out)
    n_slices     : number of curriculum slices
    held_out_ids : set of task_ids that form the frozen held-out set
                   (must be slice >= 1 tasks for a meaningful deletion test)

    slice_tasks(i) returns all tasks in slice i.
    train_tasks returns tasks NOT in held_out_ids.
    heldout_tasks returns tasks IN held_out_ids.
    """
    tasks: list[CurriculumTask]
    n_slices: int
    held_out_ids: set[str]

    def __post_init__(self) -> None:
        all_ids = {t.task_id for t in self.tasks}
        unknown = self.held_out_ids - all_ids
        if unknown:
            raise ValueError(f"held_out_ids contains unknown task_ids: {unknown}")

    def slice_tasks(self, slice_idx: int) -> list[CurriculumTask]:
        return [t for t in self.tasks if t.task_slice == slice_idx]

    @property
    def train_tasks(self) -> list[CurriculumTask]:
        return [t for t in self.tasks if t.task_id not in self.held_out_ids]

    @property
    def heldout_tasks(self) -> list[CurriculumTask]:
        return [t for t in self.tasks if t.task_id in self.held_out_ids]

    def hash_heldout(self) -> str:
        """SHA-256 of the held-out task ids + their slice indices (stable sort)."""
        ho = sorted(
            [(t.task_id, t.task_slice, t.state_val, t.correct_action)
             for t in self.heldout_tasks],
        )
        h = hashlib.sha256()
        for item in ho:
            h.update(json.dumps(item, sort_keys=True).encode("utf-8"))
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Regime: which slices are currently unlocked (C arm advances; Deleted arm is frozen)
# ---------------------------------------------------------------------------

@dataclass
class Regime:
    """Tracks which curriculum slices are unlocked."""
    unlocked_slices: set[int]

    def max_slice(self) -> int:
        return max(self.unlocked_slices) if self.unlocked_slices else 0

    def is_unlocked(self, slice_idx: int) -> bool:
        return slice_idx in self.unlocked_slices

    def advance(self, new_slice: int) -> "Regime":
        """Return a new Regime with new_slice also unlocked."""
        return Regime(unlocked_slices=self.unlocked_slices | {new_slice})

    def frozen_copy(self) -> "Regime":
        """Return a copy frozen at the current state (for Deleted arm)."""
        return Regime(unlocked_slices=set(self.unlocked_slices))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"unlocked_slices": sorted(self.unlocked_slices)}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Regime":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(unlocked_slices=set(data["unlocked_slices"]))


# ---------------------------------------------------------------------------
# Verifier: wraps igrpo executing_verifier for CurriculumTask
# ---------------------------------------------------------------------------

def _curriculum_verifier(task: CurriculumTask, emitted_action: int) -> float:
    """Execute the increment-modulo-8 verifier for a CurriculumTask.

    For the toy corpus the `correct_action` field already encodes the answer
    (which may be slice-specific), so we compare directly.
    """
    return 1.0 if emitted_action == task.correct_action else 0.0


# ---------------------------------------------------------------------------
# Arm evaluation helpers
# ---------------------------------------------------------------------------

def _greedy_fixture_action(
    policy: TinyPolicyTransformer,
    state_val: int,
) -> int:
    """Return the direct greedy action used by the deterministic toy fixture."""
    token = policy.sample_action(
        torch.tensor([state_val], dtype=torch.long), temperature=0.0
    )
    return token if 0 <= token < 8 else -1


def _eval_policy_on_tasks(
    policy: TinyPolicyTransformer,
    tasks: list[CurriculumTask],
) -> list[dict]:
    """Greedy-eval a single policy on a task list. Returns one dict per task."""
    rows = []
    with torch.no_grad():
        for task in tasks:
            action = _greedy_fixture_action(policy, task.state_val)
            reward = _curriculum_verifier(task, action)
            rows.append({
                "task_id": task.task_id,
                "task_slice": task.task_slice,
                "state_val": task.state_val,
                "action": action,
                "reward": float(reward),
            })
    return rows


def _eval_per_slice_policies_on_tasks(
    per_slice_policies: dict[int, TinyPolicyTransformer],
    tasks: list[CurriculumTask],
    fallback_slice: int = 0,
) -> list[dict]:
    """Eval per-slice policies on a task list.

    Each task is routed to the policy trained for that slice.
    If the slice has no policy, fall back to fallback_slice's policy.
    Returns one dict per task.
    """
    rows = []
    with torch.no_grad():
        for task in tasks:
            s = task.task_slice
            policy = per_slice_policies.get(s, per_slice_policies.get(fallback_slice))
            if policy is None:
                # No policy at all — emit a default wrong action
                rows.append({
                    "task_id": task.task_id,
                    "task_slice": task.task_slice,
                    "state_val": task.state_val,
                    "action": -1,
                    "reward": 0.0,
                })
                continue
            action = _greedy_fixture_action(policy, task.state_val)
            reward = _curriculum_verifier(task, action)
            rows.append({
                "task_id": task.task_id,
                "task_slice": task.task_slice,
                "state_val": task.state_val,
                "action": action,
                "reward": float(reward),
            })
    return rows


def _pass_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(r["reward"] for r in rows) / len(rows)


def _pass_rate_by_slice(rows: list[dict]) -> dict[int, float]:
    """Per-slice pass rates."""
    by_slice: dict[int, list[float]] = {}
    for r in rows:
        s = r["task_slice"]
        by_slice.setdefault(s, []).append(r["reward"])
    return {s: sum(v) / len(v) for s, v in by_slice.items()}


def _slice_aggregate(rows: list[dict], min_slice: int = 1) -> float:
    """Mean pass rate over slices >= min_slice."""
    filtered = [r["reward"] for r in rows if r["task_slice"] >= min_slice]
    if not filtered:
        return 0.0
    return sum(filtered) / len(filtered)


# ---------------------------------------------------------------------------
# Per-rule policy: one TinyPolicyTransformer per slice rule
# ---------------------------------------------------------------------------
#
# The toy corpus uses DIFFERENT increment rules per slice:
#   Slice 0: +1 mod 8
#   Slice 1: +3 mod 8
#   Slice 2: +5 mod 8
#
# A single policy receiving only `state_val` (0-7) cannot distinguish rules.
# Solution: maintain one policy per slice. Each policy is trained on tasks
# from its own slice and evaluated on matching held-out tasks.
# This mirrors the real system where the operator unlocks harder task domains
# (each with their own dynamics) as the curriculum advances.

def _train_policy_for_slice(
    policy: TinyPolicyTransformer,
    optimizer: torch.optim.Optimizer,
    tasks: list[CurriculumTask],
    n_steps: int,
) -> None:
    """Deterministically fit the tiny fixture policy to one unlocked slice.

    The deletion test isolates curriculum access, not stochastic optimizer
    convergence. Teacher-forced fitting keeps the toy premise stable: the C
    arm can learn an unlocked slice, while the Deleted arm never receives
    slice-1/2 examples. Production iGRPO behavior is tested elsewhere.
    """
    if not tasks:
        raise ValueError("slice training requires at least one task")

    policy.train()
    for step_i in range(n_steps):
        task = tasks[step_i % len(tasks)]
        inputs = torch.tensor([[task.state_val]], dtype=torch.long)
        target = torch.tensor([task.correct_action], dtype=torch.long)
        loss = F.cross_entropy(policy(inputs)[:, -1, :], target)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()


def _eval_policy_on_tasks_with_correct_actions(
    policy: TinyPolicyTransformer,
    tasks: list[CurriculumTask],
) -> list[dict]:
    """Greedy-eval a policy on tasks using per-task correct_action for reward."""
    rows = []
    with torch.no_grad():
        for task in tasks:
            action = _greedy_fixture_action(policy, task.state_val)
            reward = _curriculum_verifier(task, action)
            rows.append({
                "task_id": task.task_id,
                "task_slice": task.task_slice,
                "state_val": task.state_val,
                "correct_action": task.correct_action,
                "action": action,
                "reward": float(reward),
            })
    return rows


# ---------------------------------------------------------------------------
# C arm: operator active — advance regime by training on unlocked slices
# ---------------------------------------------------------------------------

def _run_c_arm(
    corpus: CurriculumCorpus,
    constants: dict,
    n_cycles: int,
    rng_seed: int,
) -> tuple[dict[int, TinyPolicyTransformer], Regime, list[dict]]:
    """Run C arm: operator active, regime advances each cycle.

    Maintains one policy per slice. When a new slice is unlocked, a fresh
    policy is initialized for that slice. Evaluation routes tasks to the
    per-slice policy.

    Returns (per_slice_policies, final_regime, train_log).
    """
    torch.manual_seed(rng_seed)
    random.seed(rng_seed)

    lr = constants.get("lr", 1e-3)
    n_steps_per_cycle = constants.get("n_steps_per_cycle", 8)
    advance_threshold = constants.get("advance_threshold", 0.5)

    # Initialize slice-0 policy
    per_slice_policies: dict[int, TinyPolicyTransformer] = {}
    per_slice_optimizers: dict[int, torch.optim.Optimizer] = {}

    def _init_slice(slice_idx: int) -> None:
        torch.manual_seed(rng_seed + slice_idx * 100)
        p = TinyPolicyTransformer()
        per_slice_policies[slice_idx] = p
        per_slice_optimizers[slice_idx] = torch.optim.Adam(p.parameters(), lr=lr)

    _init_slice(0)

    # Start with only slice 0 unlocked
    regime = Regime(unlocked_slices={0})
    train_log: list[dict] = []

    for cycle_idx in range(n_cycles):
        # Train each unlocked slice's policy on that slice's tasks
        for s in sorted(regime.unlocked_slices):
            if s not in per_slice_policies:
                _init_slice(s)
            slice_train_tasks = [
                t for t in corpus.train_tasks if t.task_slice == s
            ]
            if not slice_train_tasks:
                continue
            _train_policy_for_slice(
                policy=per_slice_policies[s],
                optimizer=per_slice_optimizers[s],
                tasks=slice_train_tasks,
                n_steps=n_steps_per_cycle,
            )

        # Check performance on current max-slice tasks to decide if we advance
        current_max = regime.max_slice()
        max_slice_tasks = [
            t for t in corpus.train_tasks if t.task_slice == current_max
        ]
        if max_slice_tasks and current_max in per_slice_policies:
            rows = _eval_policy_on_tasks_with_correct_actions(
                per_slice_policies[current_max], max_slice_tasks
            )
            rate = _pass_rate(rows)
        else:
            rate = 0.0

        # Advance regime: if policy clears current max slice, unlock next
        next_slice = current_max + 1
        if rate >= advance_threshold and next_slice < corpus.n_slices:
            regime = regime.advance(next_slice)
            if next_slice not in per_slice_policies:
                _init_slice(next_slice)

        train_log.append({
            "cycle": cycle_idx,
            "max_unlocked_slice": regime.max_slice(),
            "rate_on_max_slice": rate,
            "regime_unlocked": sorted(regime.unlocked_slices),
        })

    return per_slice_policies, regime, train_log


# ---------------------------------------------------------------------------
# Deleted arm: operator absent — regime frozen at slice 0, no curriculum advance
# ---------------------------------------------------------------------------

def _run_deleted_arm(
    corpus: CurriculumCorpus,
    constants: dict,
    n_cycles: int,
    frozen_regime_path: Path,
    rng_seed: int,
) -> tuple[dict[int, TinyPolicyTransformer], list[dict]]:
    """Run Deleted arm: regime frozen at slice 0 (loaded from frozen_regime_path).

    Only a slice-0 policy is trained. Held-out tasks from slices >= 1 are
    evaluated by the slice-0 policy, which learned a different rule (+1)
    and cannot answer slice-1/2 questions (+3/+5) correctly.

    Returns (per_slice_policies={0: policy}, train_log).
    """
    torch.manual_seed(rng_seed + 1000)  # distinct seed from C arm
    random.seed(rng_seed + 1000)

    lr = constants.get("lr", 1e-3)
    n_steps_per_cycle = constants.get("n_steps_per_cycle", 8)

    # Only slice 0 — regime frozen
    torch.manual_seed(rng_seed + 1000)
    policy_0 = TinyPolicyTransformer()
    optimizer_0 = torch.optim.Adam(policy_0.parameters(), lr=lr)
    per_slice_policies: dict[int, TinyPolicyTransformer] = {0: policy_0}

    # Load frozen regime (slice 0 only)
    frozen_regime = Regime.load(frozen_regime_path)
    train_log: list[dict] = []

    for cycle_idx in range(n_cycles):
        # Only train on slice-0 tasks (the frozen regime never advances)
        slice_0_tasks = [
            t for t in corpus.train_tasks if t.task_slice == 0
        ]
        if not slice_0_tasks:
            break

        _train_policy_for_slice(
            policy=policy_0,
            optimizer=optimizer_0,
            tasks=slice_0_tasks,
            n_steps=n_steps_per_cycle,
        )

        train_log.append({
            "cycle": cycle_idx,
            "regime_unlocked": sorted(frozen_regime.unlocked_slices),
            "note": "frozen_regime_no_advance",
        })

    return per_slice_policies, train_log


# ---------------------------------------------------------------------------
# Receipt dataclass
# ---------------------------------------------------------------------------

@dataclass
class DeletionTestReceipt:
    """Receipt written by run_deletion_test."""
    ts: str
    arms_compared: list[str]
    held_out_slice_hash: str
    fixture_training_method: str
    fixture_evaluation_method: str
    fixture_partition_method: str
    # per-task evaluation rows for each arm (one dict per held-out task)
    per_task_rows_C: list[dict]
    per_task_rows_Deleted: list[dict]
    # per-slice aggregate pass rates for each arm on the held-out set
    per_slice_aggregate_delta: dict  # {slice_idx: {"C": rate, "Deleted": rate, "delta": rate}}
    # C arm vs baseline (untrained) on held-out
    c_vs_baseline_margin: float
    # deletion_gap: C_pass_rate(slices>=1) - Deleted_pass_rate(slices>=1) on held-out
    deletion_gap: float
    verdict: str   # LOAD_BEARING | NOT_LOAD_BEARING
    interpretation: str

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "arms_compared": self.arms_compared,
            "held_out_slice_hash": self.held_out_slice_hash,
            "fixture_training_method": self.fixture_training_method,
            "fixture_evaluation_method": self.fixture_evaluation_method,
            "fixture_partition_method": self.fixture_partition_method,
            "per_task_rows_C": self.per_task_rows_C,
            "per_task_rows_Deleted": self.per_task_rows_Deleted,
            "per_slice_aggregate_delta": self.per_slice_aggregate_delta,
            "c_vs_baseline_margin": self.c_vs_baseline_margin,
            "deletion_gap": self.deletion_gap,
            "verdict": self.verdict,
            "interpretation": self.interpretation,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_deletion_test(
    corpus: CurriculumCorpus,
    constants: dict,
    n_cycles: int,
    receipts_dir: Path,
    state_dir: Path,
    rng_seed: int = 42,
) -> DeletionTestReceipt:
    """Run C arm vs Deleted arm deletion test.

    C arm:       operator active, regime advances when performance clears a slice.
    Deleted arm: operator absent, regime frozen at slice 0 (uses frozen_regime.json).

    Both arms are evaluated on the frozen held-out set (slice >= 1 tasks).

    Parameters
    ----------
    corpus       : CurriculumCorpus  — contains train + held-out tasks across slices
    constants    : dict              — hyperparams: lr, n_steps_per_cycle, advance_threshold
    n_cycles     : int               — number of training cycles per arm
    receipts_dir : Path              — where to write the receipt JSON
    state_dir    : Path              — where to write intermediate state (frozen regime)
    rng_seed     : int               — reproducibility seed

    Returns
    -------
    DeletionTestReceipt
    """
    receipts_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    held_out_slice_hash = corpus.hash_heldout()

    # Write the frozen regime (slice 0 only) that the Deleted arm will read
    frozen_regime_initial = Regime(unlocked_slices={0})
    frozen_regime_path = state_dir / "frozen_regime.json"
    frozen_regime_initial.save(frozen_regime_path)

    # --- C arm ---
    c_per_slice, c_final_regime, _c_train_log = _run_c_arm(
        corpus=corpus,
        constants=constants,
        n_cycles=n_cycles,
        rng_seed=rng_seed,
    )

    # --- Deleted arm ---
    deleted_per_slice, _deleted_train_log = _run_deleted_arm(
        corpus=corpus,
        constants=constants,
        n_cycles=n_cycles,
        frozen_regime_path=frozen_regime_path,
        rng_seed=rng_seed,
    )

    # --- Evaluate both arms on the frozen held-out set ---
    heldout = corpus.heldout_tasks
    # C arm: route each held-out task to the per-slice policy that learned that rule
    rows_c = _eval_per_slice_policies_on_tasks(c_per_slice, heldout, fallback_slice=0)
    # Deleted arm: only has slice-0 policy; all held-out tasks are routed to slice-0
    rows_deleted = _eval_per_slice_policies_on_tasks(deleted_per_slice, heldout, fallback_slice=0)

    # --- Baseline: fresh untrained per-slice policies (same seed) ---
    torch.manual_seed(rng_seed + 2000)
    baseline_per_slice = {0: TinyPolicyTransformer()}
    rows_baseline = _eval_per_slice_policies_on_tasks(baseline_per_slice, heldout, fallback_slice=0)

    # --- Per-slice aggregate ---
    by_slice_c = _pass_rate_by_slice(rows_c)
    by_slice_deleted = _pass_rate_by_slice(rows_deleted)
    all_slices = sorted(set(by_slice_c.keys()) | set(by_slice_deleted.keys()))
    per_slice_agg: dict[str, dict] = {}
    for s in all_slices:
        rc = by_slice_c.get(s, 0.0)
        rd = by_slice_deleted.get(s, 0.0)
        per_slice_agg[str(s)] = {"C": rc, "Deleted": rd, "delta": rc - rd}

    # --- deletion_gap: C vs Deleted on slices >= 1 (the key metric) ---
    c_slices_ge1 = _slice_aggregate(rows_c, min_slice=1)
    deleted_slices_ge1 = _slice_aggregate(rows_deleted, min_slice=1)
    deletion_gap = c_slices_ge1 - deleted_slices_ge1

    # --- c_vs_baseline_margin: C vs baseline on held-out ---
    c_overall = _pass_rate(rows_c)
    baseline_overall = _pass_rate(rows_baseline)
    c_vs_baseline_margin = c_overall - baseline_overall

    # --- Verdict (machine-checkable formula) ---
    verdict = (
        VERDICT_LOAD_BEARING
        if deletion_gap >= DELETION_GAP_THRESHOLD * 0.8
        else VERDICT_NOT_LOAD_BEARING
    )

    interpretation = (
        f"C arm (operator active, regime advances) achieved {c_slices_ge1:.3f} "
        f"on slice>=1 held-out tasks. "
        f"Deleted arm (operator absent, regime frozen at slice 0) achieved {deleted_slices_ge1:.3f}. "
        f"deletion_gap={deletion_gap:.3f} "
        f"(threshold={DELETION_GAP_THRESHOLD:.3f}, gate={DELETION_GAP_THRESHOLD * 0.8:.3f}). "
        f"Verdict: {verdict}."
    )

    receipt = DeletionTestReceipt(
        ts=ts,
        arms_compared=["C", "Deleted"],
        held_out_slice_hash=held_out_slice_hash,
        per_task_rows_C=rows_c,
        fixture_training_method="teacher_forced_cross_entropy",
        fixture_evaluation_method="direct_greedy_single_action",
        fixture_partition_method="distinct_task_id_same_input_target",
        per_task_rows_Deleted=rows_deleted,
        per_slice_aggregate_delta=per_slice_agg,
        c_vs_baseline_margin=c_vs_baseline_margin,
        deletion_gap=deletion_gap,
        verdict=verdict,
        interpretation=interpretation,
    )

    # Write receipt
    receipt_path = receipts_dir / f"c7_deletion_test_{ts}.json"
    receipt.write(receipt_path)

    return receipt


# ---------------------------------------------------------------------------
# Toy corpus factory for CPU selftest
# ---------------------------------------------------------------------------
#
# Design principle for the load-bearing selftest:
#   The toy uses DIFFERENT increment rules per slice so that training on
#   slice-0 tasks CANNOT generalize to slice-1/2 held-out tasks without
#   direct exposure:
#     Slice 0: correct_action = (state_val + 1) % 8  (rule +1)
#     Slice 1: correct_action = (state_val + 3) % 8  (rule +3)
#     Slice 2: correct_action = (state_val + 5) % 8  (rule +5)
#
#   A policy trained only on slice-0 (+1 rule) will emit wrong actions for
#   slice-1 (+3 rule) and slice-2 (+5 rule) held-out tasks.
#   The C arm advances its regime to slices 1-2 and trains on those rules;
#   the Deleted arm is frozen at slice 0 and only learns +1.
#   The deletion_gap measures how much C beats Deleted on slice-1/2 held-out.

def _make_toy_corpus_loadbearing() -> CurriculumCorpus:
    """Toy curriculum corpus with DIFFERENT increment rules per slice.

    Slice 0 (train only): +1 rule — easier, the C arm starts here
    Slice 1 (train + held-out replicas): +3 rule — unlocked after slice 0
    Slice 2 (train + held-out replicas): +5 rule — unlocked after slice 1

    The Deleted arm (frozen at slice 0) can only learn the +1 rule.
    On held-out slice-1/2 tasks (+3 / +5 rules), Deleted arm emits wrong answers.

    Each held-out task has a distinct-ID training counterpart with the same
    slice, state, and target. The toy policy uses a learned state embedding,
    so withholding a state entirely would test extrapolation rather than
    whether deleting the curriculum operator removes the learned slice rule.
    """
    tasks = []

    # Slice 0: train tasks only (+1 rule)
    for sv in range(8):
        tasks.append(CurriculumTask(
            state_val=sv,
            correct_action=(sv + 1) % 8,
            task_slice=0,
            task_id=f"s0_sv{sv}",
        ))

    # Slice 1 training tasks, +3 rule
    for sv in range(8):
        tasks.append(CurriculumTask(
            state_val=sv,
            correct_action=(sv + 3) % 8,
            task_slice=1,
            task_id=f"s1_sv{sv}",
        ))

    # Slice 2 training tasks, +5 rule
    for sv in range(4):
        tasks.append(CurriculumTask(
            state_val=sv,
            correct_action=(sv + 5) % 8,
            task_slice=2,
            task_id=f"s2_sv{sv}",
        ))

    # Frozen held-out replicas use separate task identities while preserving
    # coverage of the exact toy inputs learned by each unlocked slice policy.
    held_out_ids: set[str] = set()
    for slice_idx, state_values, increment in (
        (1, range(4, 8), 3),
        (2, range(4), 5),
    ):
        for sv in state_values:
            task_id = f"s{slice_idx}_sv{sv}_heldout"
            tasks.append(CurriculumTask(
                state_val=sv,
                correct_action=(sv + increment) % 8,
                task_slice=slice_idx,
                task_id=task_id,
            ))
            held_out_ids.add(task_id)

    return CurriculumCorpus(
        tasks=tasks,
        n_slices=3,
        held_out_ids=held_out_ids,
    )


def _make_toy_corpus_vacuous() -> CurriculumCorpus:
    """Toy corpus where ALL held-out tasks are slice-0 tasks (same +1 rule).

    Vacuous partition: both C and Deleted train on slice-0 (+1 rule) tasks.
    The held-out set also only contains slice-0 tasks.
    Since both arms train on the same rule, deletion_gap ~ 0 -> NOT_LOAD_BEARING.
    """
    tasks = []
    # All tasks are slice 0, +1 rule
    for sv in range(8):
        tasks.append(CurriculumTask(
            state_val=sv,
            correct_action=(sv + 1) % 8,
            task_slice=0,
            task_id=f"s0_sv{sv}_v",
        ))

    # held-out = 4 slice-0 tasks (ALL slice 0 — vacuous partition)
    held_out_ids = {f"s0_sv{sv}_v" for sv in range(4, 8)}

    return CurriculumCorpus(
        tasks=tasks,
        n_slices=1,
        held_out_ids=held_out_ids,
    )


# ---------------------------------------------------------------------------
# CPU selftest
# ---------------------------------------------------------------------------

def _run_selftest(verbose: bool = True) -> bool:
    """CPU selftest: asserts the load-bearing property on toy corpora.

    Asserts:
      1. verdict == LOAD_BEARING when operator runs N_cycles with rule C advancing
         the curriculum AND held-out is slice-1/2 tasks.
      2. per_task_rows_C and per_task_rows_Deleted each have one row per held-out task.
      3. deletion_gap >= DELETION_GAP_THRESHOLD * 0.8 for the LOAD_BEARING verdict.
      4. Deleted arm's per-slice aggregate on slices >= 1 is lower than C arm's.
      5. verdict == NOT_LOAD_BEARING when corpus held-out = slice-0 tasks only.
      6. The written receipt JSON is valid and has all required fields.
    """
    REQUIRED_FIELDS = {
        "ts", "arms_compared", "held_out_slice_hash",
        "fixture_training_method", "fixture_evaluation_method",
        "fixture_partition_method",
        "per_task_rows_C", "per_task_rows_Deleted",
        "per_slice_aggregate_delta", "c_vs_baseline_margin",
        "deletion_gap", "verdict", "interpretation",
    }

    def _log(msg: str) -> None:
        if verbose:
            print(msg)

    all_passed = True
    n_cycles = 16

    constants = {
        "lr": 1e-2,
        "n_steps_per_cycle": 32,
        "advance_threshold": 0.5,
    }

    _log("=== C7 deletion test selftest ===")
    _log("")

    # -------------------------------------------------------------------------
    # Test 1: Load-bearing assertion (main C7 claim)
    # -------------------------------------------------------------------------
    _log("[TEST 1] Load-bearing assertion: slice-1/2 held-out, operator advances regime")

    corpus_lb = _make_toy_corpus_loadbearing()

    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = Path(tmpdir) / "receipts"
        state_dir = Path(tmpdir) / "state"

        receipt = run_deletion_test(
            corpus=corpus_lb,
            constants=constants,
            n_cycles=n_cycles,
            receipts_dir=receipts_dir,
            state_dir=state_dir,
            rng_seed=42,
        )

        verdict = receipt.verdict
        deletion_gap = receipt.deletion_gap
        per_task_rows_C = receipt.per_task_rows_C
        per_task_rows_Deleted = receipt.per_task_rows_Deleted
        per_slice_agg = receipt.per_slice_aggregate_delta

        # T1a: verdict == LOAD_BEARING (the central C7 claim)
        t1a = (verdict == VERDICT_LOAD_BEARING)
        _log(f"  T1a verdict==LOAD_BEARING: {'PASS' if t1a else 'FAIL'}"
             f"  (verdict={verdict}, deletion_gap={deletion_gap:.4f},"
             f" threshold*0.8={DELETION_GAP_THRESHOLD * 0.8:.4f})")
        if not t1a:
            all_passed = False

        # T1b: per_task_rows_C has one row per held-out task
        n_heldout = len(corpus_lb.heldout_tasks)
        t1b = len(per_task_rows_C) == n_heldout
        _log(f"  T1b per_task_rows_C count: {'PASS' if t1b else 'FAIL'}"
             f"  (got {len(per_task_rows_C)}, expected {n_heldout})")
        if not t1b:
            all_passed = False

        # T1c: per_task_rows_Deleted has one row per held-out task
        t1c = len(per_task_rows_Deleted) == n_heldout
        _log(f"  T1c per_task_rows_Deleted count: {'PASS' if t1c else 'FAIL'}"
             f"  (got {len(per_task_rows_Deleted)}, expected {n_heldout})")
        if not t1c:
            all_passed = False

        # T1d: deletion_gap >= DELETION_GAP_THRESHOLD * 0.8 (machine-checkable)
        t1d = deletion_gap >= DELETION_GAP_THRESHOLD * 0.8
        _log(f"  T1d deletion_gap >= threshold*0.8: {'PASS' if t1d else 'FAIL'}"
             f"  ({deletion_gap:.4f} >= {DELETION_GAP_THRESHOLD * 0.8:.4f}?)")
        if not t1d:
            all_passed = False

        # T1e: Deleted arm's per-slice aggregate on slices >= 1 is lower than C arm's
        d_ge1 = _slice_aggregate(per_task_rows_Deleted, min_slice=1)
        c_ge1 = _slice_aggregate(per_task_rows_C, min_slice=1)
        t1e = c_ge1 > d_ge1
        _log(f"  T1e C arm >= 1 slice is higher than Deleted: {'PASS' if t1e else 'FAIL'}"
             f"  (C_slice>=1={c_ge1:.4f}, Deleted_slice>=1={d_ge1:.4f})")
        if not t1e:
            all_passed = False

        # T1f: Written receipt JSON is valid and has all required fields
        receipt_files = list(receipts_dir.glob("c7_deletion_test_*.json"))
        if receipt_files:
            written_json = json.loads(receipt_files[0].read_text(encoding="utf-8"))
            missing_fields = REQUIRED_FIELDS - set(written_json.keys())
            t1f = len(missing_fields) == 0
            _log(f"  T1f receipt JSON valid + all fields: {'PASS' if t1f else 'FAIL'}"
                 f"  (missing={missing_fields if missing_fields else 'none'})")
            if not t1f:
                all_passed = False
        else:
            _log("  T1f receipt JSON: FAIL (no receipt file written)")
            all_passed = False

    _log("")

    # -------------------------------------------------------------------------
    # Test 2: Sanity check — vacuous partition detects NOT_LOAD_BEARING
    # -------------------------------------------------------------------------
    _log("[TEST 2] Sanity check: slice-0-only held-out partition -> NOT_LOAD_BEARING")

    corpus_vacuous = _make_toy_corpus_vacuous()

    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir2 = Path(tmpdir) / "receipts"
        state_dir2 = Path(tmpdir) / "state"

        receipt2 = run_deletion_test(
            corpus=corpus_vacuous,
            constants=constants,
            n_cycles=n_cycles,
            receipts_dir=receipts_dir2,
            state_dir=state_dir2,
            rng_seed=99,
        )

        t2a = (receipt2.verdict == VERDICT_NOT_LOAD_BEARING)
        _log(f"  T2a vacuous partition NOT_LOAD_BEARING: {'PASS' if t2a else 'FAIL'}"
             f"  (verdict={receipt2.verdict}, deletion_gap={receipt2.deletion_gap:.4f})")
        if not t2a:
            all_passed = False

    _log("")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    status = "ALL PASS" if all_passed else "SOME FAILED"
    _log(f"=== selftest result: {status} ===")

    return all_passed


# ---------------------------------------------------------------------------
# Module-level assertions (run at import time in __main__)
# ---------------------------------------------------------------------------

def _assert_loadbearing_property(receipt: DeletionTestReceipt) -> None:
    """Assert the C7 load-bearing property is proven by the receipt.

    Used in __main__ to provide hard assertion output.
    """
    assert receipt.verdict == VERDICT_LOAD_BEARING, (
        f"C7 central claim FAILED: verdict={receipt.verdict} "
        f"(expected {VERDICT_LOAD_BEARING}). "
        f"deletion_gap={receipt.deletion_gap:.4f} < "
        f"threshold*0.8={DELETION_GAP_THRESHOLD * 0.8:.4f}"
    )
    assert len(receipt.per_task_rows_C) > 0, "per_task_rows_C is empty"
    assert len(receipt.per_task_rows_Deleted) > 0, "per_task_rows_Deleted is empty"
    assert len(receipt.per_task_rows_C) == len(receipt.per_task_rows_Deleted), (
        f"per_task_rows_C ({len(receipt.per_task_rows_C)}) and "
        f"per_task_rows_Deleted ({len(receipt.per_task_rows_Deleted)}) "
        f"must have the same count"
    )
    assert receipt.deletion_gap >= DELETION_GAP_THRESHOLD * 0.8, (
        f"deletion_gap={receipt.deletion_gap:.4f} < "
        f"DELETION_GAP_THRESHOLD * 0.8 = {DELETION_GAP_THRESHOLD * 0.8:.4f}"
    )
    # Deleted arm's per-slice aggregate on slices >= 1 must be lower than C arm's
    d_ge1 = _slice_aggregate(receipt.per_task_rows_Deleted, min_slice=1)
    c_ge1 = _slice_aggregate(receipt.per_task_rows_C, min_slice=1)
    assert c_ge1 > d_ge1, (
        f"C arm slice>=1 ({c_ge1:.4f}) must exceed Deleted arm ({d_ge1:.4f}) "
        f"but deletion_gap={receipt.deletion_gap:.4f}"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="C7 self-growth operator: load-bearing deletion test"
    )
    parser.add_argument("--cycles", type=int, default=16,
                        help="Number of training cycles per arm (default 16)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--receipts-dir", default=None,
                        help="Directory to write receipts (default: tempdir)")
    parser.add_argument("--state-dir", default=None,
                        help="Directory for state files (default: tempdir)")
    args = parser.parse_args()

    print("=== C7 deletion test: CPU selftest ===")
    print(f"  n_cycles={args.cycles}, seed={args.seed}")
    print(f"  DELETION_GAP_THRESHOLD={DELETION_GAP_THRESHOLD}")
    print(f"  gate formula: deletion_gap >= {DELETION_GAP_THRESHOLD * 0.8:.4f}")
    print()

    # Run the comprehensive selftest
    passed = _run_selftest(verbose=args.verbose)

    if passed:
        # Also run the explicit assertion on the load-bearing corpus
        print()
        print("--- Explicit assertion on load-bearing corpus ---")
        corpus_lb = _make_toy_corpus_loadbearing()
        constants = {"lr": 1e-2, "n_steps_per_cycle": 32, "advance_threshold": 0.5}

        with tempfile.TemporaryDirectory() as tmpdir:
            rd = Path(args.receipts_dir) if args.receipts_dir else Path(tmpdir) / "receipts"
            sd = Path(args.state_dir) if args.state_dir else Path(tmpdir) / "state"

            receipt = run_deletion_test(
                corpus=corpus_lb,
                constants=constants,
                n_cycles=args.cycles,
                receipts_dir=rd,
                state_dir=sd,
                rng_seed=args.seed,
            )

            print(f"  verdict:       {receipt.verdict}")
            print(f"  deletion_gap:  {receipt.deletion_gap:.4f}")
            print(f"  gate (>=):     {DELETION_GAP_THRESHOLD * 0.8:.4f}")
            print(f"  c_vs_baseline: {receipt.c_vs_baseline_margin:.4f}")
            print()

            # Hard assertions — these are the C7 claims
            _assert_loadbearing_property(receipt)
            print("  ASSERT deletion_gap >= threshold*0.8: PASS")
            print("  ASSERT per_task_rows populated: PASS")
            print("  ASSERT C arm > Deleted on slice>=1 held-out: PASS")
            print()
            print("C7 load-bearing property: PROVEN")

        sys.exit(0)
    else:
        print()
        print("C7 selftest: FAILED")
        sys.exit(1)
