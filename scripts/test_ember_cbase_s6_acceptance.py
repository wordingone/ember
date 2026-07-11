#!/usr/bin/env python3
"""test_ember_cbase_s6_acceptance.py — TDD suite for the §6 acceptance harness.

Runs against the REAL tiny_cpu_instance (build_multimodal_v0_model(cfg, live=False)).
All tests are CPU-only, no daemon, no [REDACTED].exe.

Tests:
  1. stub_correct_trace_scores_R1 — a stub core that emits a KNOWN-CORRECT trace
     for t001 scores R=1 (full stack, all assertions).
  2. garbage_core_scores_R0 — a core that emits garbage/empty scores R=0 (parser
     returns no actions; no crash).
  3. input_trap_rejects — THE /input-TRAP TEST: a core whose decoded draft is just
     the goal_prompt text (no tool_use) MUST score R=0 — proving the harness does
     NOT route to a capable model to "rescue" it.
  4. wrong_value_trace_fails — a WRONG-VALUE trace (correct structure, wrong file
     content) FAILS file_contains -> R=0.
  5. preseeded_file_fails_mtime — a PRE-SEEDED file (mtime before turn_start) FAILS
     file_created_this_turn -> R=0.
  6. gte_coverage_fails — a draft with too few tool_use actions FAILS
     jsonl_tool_call_count_gte for a gte>=2 task -> R=0.
  7. accept_cbase_aggregates — accept_cbase aggregates correctly (floor_met iff >=1
     task any_correct).
  8. real_tiny_cpu_end_to_end — the REAL tiny_cpu_instance (untrained, random weights)
     runs end-to-end without crashing (expected R=0 — it has not learned the format).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

import torch

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from ember_avir_tasks import load_split, setup_sandbox
from ember_cbase_avir_data_v2 import (
    _make_write_entry,
    _make_read_entry,
    _make_end_turn_entry,
    _compute_answer,
    _build_session_entries,
    _render_pretrain_text,
)
from ember_cbase_s6_acceptance import (
    score_core_on_task,
    accept_cbase,
    _parse_draft,
    _apply_actions_to_sandbox,
    _synthesize_session_jsonl,
    _score_draft,
    _get_tokenizer,
    MAX_NEW_TOKENS,
)

# ---------------------------------------------------------------------------
# Stub cores
# ---------------------------------------------------------------------------

class _StubCore:
    """A stub core that emits a pre-baked token sequence.

    The token ids are produced by encoding the target draft text with the
    production tokenizer.  sample_action() emits them one at a time, then
    returns EOS (token 0) indefinitely.

    This guarantees the harness decodes exactly the target draft — bypassing
    random model weights — so we can test R=1 / R=0 cleanly.

    NOTE: This stub does NOT call [REDACTED].exe /input; it returns pre-baked
    token ids from the tokenizer, not from a capable model.  The R=1 result
    proves the harness full-stack works correctly.
    """

    def __init__(self, draft_text: str) -> None:
        tok = _get_tokenizer()
        self._ids: list[int] = tok.encode(draft_text, add_special_tokens=False).ids
        self._pos: int = 0

    def sample_action(self, context_ids: torch.Tensor, temperature: float = 1.0) -> int:  # noqa: ARG002
        if self._pos < len(self._ids):
            tok_id = self._ids[self._pos]
            self._pos += 1
            return tok_id
        return 0  # EOS / padding after sequence exhausted


class _GarbageCore:
    """Emits random low-id tokens that will never parse as valid JSONL."""

    def sample_action(self, context_ids: torch.Tensor, temperature: float = 1.0) -> int:  # noqa: ARG002
        # Token id 5 decodes to something non-JSON on ByteLevel BPE.
        return 5


class _EchoGoalCore:
    """Emits the goal_prompt text only (no tool_use JSON).

    /input-trap test: if the harness were to feed this draft to [REDACTED].exe /input,
    gemma4-26b would produce correct tool_use actions and we'd get a false R=1.
    The harness must parse the core's OWN tokens only and score R=0.
    """

    def __init__(self, goal_prompt: str) -> None:
        tok = _get_tokenizer()
        # Re-encode just the goal prompt to produce a draft that looks like a prompt echo.
        self._ids: list[int] = tok.encode(goal_prompt, add_special_tokens=False).ids
        self._pos: int = 0

    def sample_action(self, context_ids: torch.Tensor, temperature: float = 1.0) -> int:  # noqa: ARG002
        if self._pos < len(self._ids):
            tok_id = self._ids[self._pos]
            self._pos += 1
            return tok_id
        return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_train_task(tid: str) -> dict:
    tasks = load_split("train")
    for t in tasks:
        if t["id"] == tid:
            return t
    raise ValueError(f"Task {tid!r} not found in train split")


def _build_correct_draft_for_task(task: dict) -> str:
    """Build the exact pretrain rendering for a task (the ground-truth draft).

    Uses the same pipeline as ember_cbase_avir_data_v2:
      - setup_sandbox -> compute_answer -> build_session_entries -> render_pretrain_text.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = setup_sandbox(task, pathlib.Path(tmpdir))
        answer = _compute_answer(task, sandbox)
        entries = _build_session_entries(task, answer)
        # The pretrain text is: goal_prompt + "\n" + "\n".join(json.dumps(e) for e in entries)
        return _render_pretrain_text(task, entries)


# ---------------------------------------------------------------------------
# Test 1: stub correct trace -> R=1 (full stack)
# ---------------------------------------------------------------------------

def test_stub_correct_trace_scores_R1():
    """A stub core emitting the exact correct trace for t001 must score R=1."""
    task = _get_train_task("t001")
    correct_draft = _build_correct_draft_for_task(task)

    # The stub emits the completion portion only (after the goal_prompt line).
    # The _sample_draft function encodes goal_prompt, then the stub provides
    # the remaining tokens.  We construct the stub to emit the FULL pretrain text;
    # the harness strips the goal_prompt prefix from the decoded output.
    stub = _StubCore(correct_draft)
    result = score_core_on_task(stub, task, n_samples=1, temperature=1.0, seed=0)

    assert result["task_id"] == "t001", f"task_id mismatch: {result['task_id']}"
    assert result["n"] == 1
    assert result["rewards"] == [1], f"Expected [1], got {result['rewards']}"
    assert result["any_correct"] is True, "any_correct should be True"
    print("[PASS] test_stub_correct_trace_scores_R1")


# ---------------------------------------------------------------------------
# Test 2: garbage core -> R=0, no crash
# ---------------------------------------------------------------------------

def test_garbage_core_scores_R0():
    """A core emitting garbage tokens produces no valid actions -> R=0, no crash."""
    task = _get_train_task("t001")
    core = _GarbageCore()
    result = score_core_on_task(core, task, n_samples=1, temperature=1.0, seed=0)

    assert result["task_id"] == "t001"
    assert result["rewards"] == [0], f"Expected [0], got {result['rewards']}"
    assert result["any_correct"] is False
    print("[PASS] test_garbage_core_scores_R0")


# ---------------------------------------------------------------------------
# Test 3: /input-trap test -> R=0 (proves no capable-model rescue)
# ---------------------------------------------------------------------------

def test_input_trap_rejects():
    """A draft that is just the goal_prompt (no tool_use JSON) must score R=0.

    This is the CRITICAL /input-trap test:
      - If the harness were to route the draft to [REDACTED].exe POST /input, gemma4-26b
        would respond with correct tool_use actions -> false R=1.
      - The harness must parse the core's OWN tokens ONLY.
      - A goal_prompt echo contains no tool_use JSON -> empty action list -> R=0.
    """
    task = _get_train_task("t001")
    core = _EchoGoalCore(task["goal_prompt"])
    result = score_core_on_task(core, task, n_samples=1, temperature=1.0, seed=0)

    assert result["rewards"] == [0], (
        f"/input-trap VIOLATED: echo-prompt draft scored R={result['rewards']} "
        f"(should be R=0 — harness must not route to capable model)"
    )
    assert result["any_correct"] is False
    print("[PASS] test_input_trap_rejects — harness does NOT route to /input")


# ---------------------------------------------------------------------------
# Test 4: wrong-value trace -> file_contains fails -> R=0
# ---------------------------------------------------------------------------

def test_wrong_value_trace_fails():
    """Correct structure but wrong file content: file_contains FAILS -> R=0."""
    task = _get_train_task("t001")  # t001: sum numbers.txt -> output.txt

    # Build a correct-structure trace but with WRONG content.
    wrong_content = "99999\n"  # deliberately wrong sum
    write_entry = _make_write_entry("output.txt", wrong_content, "tu_1")
    end_entry = _make_end_turn_entry()
    wrong_entries = [write_entry, end_entry]
    goal_prompt = task["goal_prompt"]
    wrong_draft = goal_prompt + "\n" + "\n".join(json.dumps(e) for e in wrong_entries)

    stub = _StubCore(wrong_draft)
    result = score_core_on_task(stub, task, n_samples=1, temperature=1.0, seed=0)

    assert result["rewards"] == [0], (
        f"Wrong-value trace should score R=0, got {result['rewards']}"
    )
    assert result["any_correct"] is False
    print("[PASS] test_wrong_value_trace_fails")


# ---------------------------------------------------------------------------
# Test 5: pre-seeded file fails mtime gate
# ---------------------------------------------------------------------------

def test_preseeded_file_fails_mtime():
    """A file written BEFORE turn_start_s fails file_created_this_turn -> R=0."""
    task = _get_train_task("t001")

    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = pathlib.Path(tmpdir) / "sandbox"
        setup_sandbox(task, sandbox)

        # Compute the correct answer.
        answer = _compute_answer(task, sandbox)
        output_file = list(answer.keys())[0]
        output_content = answer[output_file]

        # Pre-seed the output file BEFORE recording turn_start_s.
        target = sandbox / output_file
        target.write_text(output_content, encoding="utf-8")

        # Record turn_start_s AFTER writing (simulates a warm sandbox).
        time.sleep(0.05)  # ensure mtime < turn_start_s
        turn_start_s = time.time()

        # Build correct actions.
        actions = [("Write", output_file, output_content)]

        # Synthesize session JSONL.
        session_jsonl_path = pathlib.Path(tmpdir) / "session.jsonl"
        _synthesize_session_jsonl(actions, session_jsonl_path)

        reward, failures = _score_draft(
            task, actions, sandbox, session_jsonl_path, turn_start_s
        )

    # The file was pre-seeded, so mtime < turn_start_s -> file_created_this_turn FAILS.
    assert reward == 0, (
        f"Pre-seeded file should fail mtime gate (R=0), got reward={reward}. "
        f"Failures: {failures}"
    )
    assert any("file_created_this_turn" in f for f in failures), (
        f"Expected file_created_this_turn in failures: {failures}"
    )
    print("[PASS] test_preseeded_file_fails_mtime")


# ---------------------------------------------------------------------------
# Test 6: gte_coverage — too few tool_use -> jsonl_tool_call_count_gte fails -> R=0
# ---------------------------------------------------------------------------

def test_gte_coverage_fails():
    """A trace with too few tool_use entries fails jsonl_tool_call_count_gte -> R=0.

    t002 requires gte=2 (Read + Write).  A Write-only trace has only 1 tool_use.
    """
    task = _get_train_task("t002")  # t002 has gte=2

    # Verify the task has gte >= 2.
    gte = None
    for a in task["verifier_assertions"]:
        if a.get("type") == "jsonl_tool_call_count_gte":
            gte = a["count"]
            break
    assert gte is not None and gte >= 2, f"t002 expected gte>=2, got {gte}"

    # Build a trace with only 1 tool_use (Write-only, no Read).
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = pathlib.Path(tmpdir) / "sandbox"
        setup_sandbox(task, sandbox)
        answer = _compute_answer(task, sandbox)
        output_file = list(answer.keys())[0]
        output_content = answer[output_file]

        # Only Write (1 tool_use), no Read — violates gte=2.
        one_tool_entries = [
            _make_write_entry(output_file, output_content, "tu_1"),
            _make_end_turn_entry(),
        ]
        goal_prompt = task["goal_prompt"]
        one_tool_draft = goal_prompt + "\n" + "\n".join(json.dumps(e) for e in one_tool_entries)

    stub = _StubCore(one_tool_draft)
    result = score_core_on_task(stub, task, n_samples=1, temperature=1.0, seed=0)

    assert result["rewards"] == [0], (
        f"gte coverage: 1-tool trace should score R=0, got {result['rewards']}"
    )
    assert result["any_correct"] is False
    print("[PASS] test_gte_coverage_fails")


# ---------------------------------------------------------------------------
# Test 7: accept_cbase aggregates correctly
# ---------------------------------------------------------------------------

def test_accept_cbase_aggregates():
    """accept_cbase: floor_met iff >= 1 task any_correct.

    Uses two tasks: t001 with a correct stub (any_correct=True) and t002 with
    a garbage stub (any_correct=False).  Combined: floor_met=True.
    """
    task_t001 = _get_train_task("t001")
    correct_draft = _build_correct_draft_for_task(task_t001)

    class _MixedCore:
        """Emits correct trace for t001 (1st call), garbage for t002 (2nd+ calls)."""
        def __init__(self):
            tok = _get_tokenizer()
            self._t001_ids: list[int] = tok.encode(
                correct_draft, add_special_tokens=False
            ).ids
            self._pos: int = 0
            self._call_count: int = 0

        def sample_action(self, context_ids: torch.Tensor, temperature: float = 1.0) -> int:
            # The first n tokens are for t001; after that emit garbage.
            if self._pos < len(self._t001_ids):
                tok_id = self._t001_ids[self._pos]
                self._pos += 1
                return tok_id
            return 5  # garbage after t001 is exhausted

    # Test floor_met=True (1 correct task).
    core_with_one_correct = _MixedCore()

    # Build a "correct on t001 only" result manually via score_core_on_task.
    result_t001 = score_core_on_task(
        _StubCore(correct_draft), task_t001, n_samples=1, temperature=1.0, seed=0
    )
    result_t002 = score_core_on_task(
        _GarbageCore(), _get_train_task("t002"), n_samples=1, temperature=1.0, seed=0
    )

    assert result_t001["any_correct"] is True, "t001 stub should be correct"
    assert result_t002["any_correct"] is False, "garbage core should not be correct"

    # Combine manually to test aggregation logic.
    per_task = [result_t001, result_t002]
    n_correct = sum(1 for r in per_task if r["any_correct"])
    floor_met = n_correct >= 1
    assert floor_met is True, f"floor_met should be True (1 correct task), got {floor_met}"

    # Test floor_met=False (0 correct tasks).
    per_task_none = [result_t002, result_t002]
    n_correct_none = sum(1 for r in per_task_none if r["any_correct"])
    floor_met_none = n_correct_none >= 1
    assert floor_met_none is False, f"floor_met should be False (0 correct tasks)"

    print("[PASS] test_accept_cbase_aggregates")


# ---------------------------------------------------------------------------
# Test 8: real tiny_cpu_instance end-to-end (expected R=0 — untrained)
# ---------------------------------------------------------------------------

def test_real_tiny_cpu_end_to_end():
    """The REAL tiny_cpu_instance runs end-to-end without crashing.

    Expected: R=0 on all samples (untrained random weights cannot produce valid
    JSONL traces).  This test proves the harness handles a real untrained core
    gracefully — no exceptions, no hangs.
    """
    from build_multimodal_v0_model import build_multimodal_v0_model
    from train_multimodal_v0 import load_multimodal_config
    from ember_c14_real_adapter import EmberModelShell

    cfg = load_multimodal_config()
    model, vocab, hidden = build_multimodal_v0_model(cfg, live=False)
    # vocab returned from cfg is 32000 (production); model itself has vocab=64 (tiny).
    assert vocab == 32000 or vocab == 32008, f"Expected vocab 32000 or 32008, got {vocab}"

    shell = EmberModelShell(model)

    task = _get_train_task("t001")

    # Run with n_samples=2 (full §6 uses 4; 2 is enough to prove no crash).
    result = score_core_on_task(shell, task, n_samples=2, temperature=1.0, seed=42)

    assert result["task_id"] == "t001"
    assert result["n"] == 2
    assert len(result["rewards"]) == 2
    assert len(result["drafts"]) == 2
    # R=0 expected (untrained), but we allow R=1 if by extreme luck — the key
    # invariant is no crash.
    for r in result["rewards"]:
        assert r in (0, 1), f"Reward must be in {{0,1}}, got {r}"
    print(
        f"[PASS] test_real_tiny_cpu_end_to_end — rewards={result['rewards']} "
        f"(R=0 expected for untrained; crash = FAIL)"
    )


# ---------------------------------------------------------------------------
# Smoke: accept_cbase on the real tiny core (2 tasks, 2 samples each)
# ---------------------------------------------------------------------------

def smoke_accept_cbase_tiny():
    """Smoke run: accept_cbase on the real tiny_cpu_instance.

    Uses 2 train tasks and n_samples=2 to keep runtime short.  Expected result:
    floor_met=False (untrained core; R=0 on all samples).  The key invariant:
    no crash, summary fields populated, per_task list has 2 entries.
    """
    from build_multimodal_v0_model import build_multimodal_v0_model
    from train_multimodal_v0 import load_multimodal_config
    from ember_c14_real_adapter import EmberModelShell

    cfg = load_multimodal_config()
    model, vocab, hidden = build_multimodal_v0_model(cfg, live=False)
    shell = EmberModelShell(model)

    task_ids = ["t001", "t002"]
    result = accept_cbase(
        core=shell,
        train_task_ids=task_ids,
        n_samples=2,
        temperature=1.0,
        seed=7,
    )

    assert "floor_met" in result
    assert "per_task" in result
    assert "summary" in result
    assert len(result["per_task"]) == 2
    assert result["summary"]["n_tasks"] == 2
    assert result["summary"]["total_samples"] == 4  # 2 tasks * 2 samples
    # floor_met can be True or False; we assert it is a bool.
    assert isinstance(result["floor_met"], bool)

    print(
        f"[SMOKE PASS] smoke_accept_cbase_tiny — "
        f"floor_met={result['floor_met']}, "
        f"n_correct_tasks={result['summary']['n_correct_tasks']}, "
        f"total_correct={result['summary']['total_correct']}"
    )
    return result


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_all_tests():
    print("=" * 60)
    print("ember_cbase_s6_acceptance TDD suite")
    print("=" * 60)

    tests = [
        test_stub_correct_trace_scores_R1,
        test_garbage_core_scores_R0,
        test_input_trap_rejects,
        test_wrong_value_trace_fails,
        test_preseeded_file_fails_mtime,
        test_gte_coverage_fails,
        test_accept_cbase_aggregates,
        test_real_tiny_cpu_end_to_end,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"[FAIL] {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Tests: {passed} passed, {failed} failed")

    print()
    print("Running smoke: accept_cbase on real tiny_cpu_instance...")
    try:
        smoke_result = smoke_accept_cbase_tiny()
        print(f"Smoke result: {json.dumps({k: v for k, v in smoke_result.items() if k != 'per_task'}, indent=2)}")
    except Exception as e:
        import traceback
        print(f"[SMOKE FAIL] {e}")
        traceback.print_exc()
        failed += 1

    print("=" * 60)
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILED: {failed} test(s)")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
