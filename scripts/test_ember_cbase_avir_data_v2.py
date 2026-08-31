#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_ember_cbase_avir_data_v2.py — TDD tests for the v2 pipeline.

Each test targets a specific does-not-count defect from the REJECT verdict:

  test_firewall_raises_on_heldout:
    FIREWALL — raises on any heldout id (h001-h020).

  test_answers_computed_from_input:
    Defect D closed — perturbing an input file changes the answer.
    No hardcoded dict.

  test_wrong_answer_fails_file_contains:
    A deliberately WRONG synthesized answer FAILS file_contains.

  test_missing_tool_use_fails_gates:
    A trace with no tool_use FAILS jsonl_tool_call_this_turn and
    jsonl_tool_call_count_gte.

  test_preseeded_file_fails_mtime_gate:
    A PRE-SEEDED file (mtime before turn_start) FAILS file_created_this_turn.

  test_full_pipeline_round_trip:
    Full pipeline produces verified traces and round-trips the packed shard.

Run: python scripts/test_ember_cbase_avir_data_v2.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
import importlib.util as _ember_6c243c4c73ac7e2b_importlib
import sys as _ember_6c243c4c73ac7e2b_sys
from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
_ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
if not _ember_6c243c4c73ac7e2b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
_ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
_ember_6c243c4c73ac7e2b_existing = []
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
        _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
if len(_ember_6c243c4c73ac7e2b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
if _ember_6c243c4c73ac7e2b_existing:
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
    _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
    if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
else:
    _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
    if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
    for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
        _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
        if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
    try:
        _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
    except BaseException:
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
        raise
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
load_split = getattr(_ember_6c243c4c73ac7e2b_module, 'load_split')
setup_sandbox = getattr(_ember_6c243c4c73ac7e2b_module, 'setup_sandbox')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_harness.py
import importlib.util as _ember_a6fe7aa88e51dfeb_importlib
import sys as _ember_a6fe7aa88e51dfeb_sys
from pathlib import Path as _ember_a6fe7aa88e51dfeb_Path
_ember_a6fe7aa88e51dfeb_path = _ember_a6fe7aa88e51dfeb_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_harness.py')
if not _ember_a6fe7aa88e51dfeb_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_harness.py')
_ember_a6fe7aa88e51dfeb_aliases = ('_ember_issue2015_a6fe7aa88e51dfeb', 'ember_avir_harness', 'scripts.ember_avir_harness')
_ember_a6fe7aa88e51dfeb_existing = []
for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
    _ember_a6fe7aa88e51dfeb_candidate = _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias)
    if _ember_a6fe7aa88e51dfeb_candidate is not None and all(_ember_a6fe7aa88e51dfeb_candidate is not item for item in _ember_a6fe7aa88e51dfeb_existing):
        _ember_a6fe7aa88e51dfeb_existing.append(_ember_a6fe7aa88e51dfeb_candidate)
if len(_ember_a6fe7aa88e51dfeb_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_harness.py')
if _ember_a6fe7aa88e51dfeb_existing:
    _ember_a6fe7aa88e51dfeb_module = _ember_a6fe7aa88e51dfeb_existing[0]
    _ember_a6fe7aa88e51dfeb_observed = getattr(_ember_a6fe7aa88e51dfeb_module, '__file__', None)
    if _ember_a6fe7aa88e51dfeb_observed is None or _ember_a6fe7aa88e51dfeb_Path(_ember_a6fe7aa88e51dfeb_observed).resolve() != _ember_a6fe7aa88e51dfeb_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_harness.py')
else:
    _ember_a6fe7aa88e51dfeb_spec = _ember_a6fe7aa88e51dfeb_importlib.spec_from_file_location('_ember_issue2015_a6fe7aa88e51dfeb', _ember_a6fe7aa88e51dfeb_path)
    if _ember_a6fe7aa88e51dfeb_spec is None or _ember_a6fe7aa88e51dfeb_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_harness.py')
    _ember_a6fe7aa88e51dfeb_module = _ember_a6fe7aa88e51dfeb_importlib.module_from_spec(_ember_a6fe7aa88e51dfeb_spec)
    for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
        _ember_a6fe7aa88e51dfeb_prior = _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias)
        if _ember_a6fe7aa88e51dfeb_prior is not None and _ember_a6fe7aa88e51dfeb_prior is not _ember_a6fe7aa88e51dfeb_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_harness.py')
        _ember_a6fe7aa88e51dfeb_sys.modules[_ember_a6fe7aa88e51dfeb_alias] = _ember_a6fe7aa88e51dfeb_module
    try:
        _ember_a6fe7aa88e51dfeb_spec.loader.exec_module(_ember_a6fe7aa88e51dfeb_module)
    except BaseException:
        for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
            if _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias) is _ember_a6fe7aa88e51dfeb_module:
                _ember_a6fe7aa88e51dfeb_sys.modules.pop(_ember_a6fe7aa88e51dfeb_alias, None)
        raise
for _ember_a6fe7aa88e51dfeb_alias in _ember_a6fe7aa88e51dfeb_aliases:
    _ember_a6fe7aa88e51dfeb_prior = _ember_a6fe7aa88e51dfeb_sys.modules.get(_ember_a6fe7aa88e51dfeb_alias)
    if _ember_a6fe7aa88e51dfeb_prior is not None and _ember_a6fe7aa88e51dfeb_prior is not _ember_a6fe7aa88e51dfeb_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_harness.py')
    _ember_a6fe7aa88e51dfeb_sys.modules[_ember_a6fe7aa88e51dfeb_alias] = _ember_a6fe7aa88e51dfeb_module
TurnResult = getattr(_ember_a6fe7aa88e51dfeb_module, 'TurnResult')
_parse_jsonl_entries = getattr(_ember_a6fe7aa88e51dfeb_module, '_parse_jsonl_entries')
_extract_turn_signal = getattr(_ember_a6fe7aa88e51dfeb_module, '_extract_turn_signal')
harness_run_assertions = getattr(_ember_a6fe7aa88e51dfeb_module, 'run_assertions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_harness.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_cbase_avir_data_v2.py
import importlib.util as _ember_81579232cbfd41ec_importlib
import sys as _ember_81579232cbfd41ec_sys
from pathlib import Path as _ember_81579232cbfd41ec_Path
_ember_81579232cbfd41ec_path = _ember_81579232cbfd41ec_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_cbase_avir_data_v2.py')
if not _ember_81579232cbfd41ec_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
_ember_81579232cbfd41ec_aliases = ('_ember_issue2015_81579232cbfd41ec', 'ember_cbase_avir_data_v2', 'scripts.ember_cbase_avir_data_v2')
_ember_81579232cbfd41ec_existing = []
for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
    _ember_81579232cbfd41ec_candidate = _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias)
    if _ember_81579232cbfd41ec_candidate is not None and all(_ember_81579232cbfd41ec_candidate is not item for item in _ember_81579232cbfd41ec_existing):
        _ember_81579232cbfd41ec_existing.append(_ember_81579232cbfd41ec_candidate)
if len(_ember_81579232cbfd41ec_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
if _ember_81579232cbfd41ec_existing:
    _ember_81579232cbfd41ec_module = _ember_81579232cbfd41ec_existing[0]
    _ember_81579232cbfd41ec_observed = getattr(_ember_81579232cbfd41ec_module, '__file__', None)
    if _ember_81579232cbfd41ec_observed is None or _ember_81579232cbfd41ec_Path(_ember_81579232cbfd41ec_observed).resolve() != _ember_81579232cbfd41ec_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
else:
    _ember_81579232cbfd41ec_spec = _ember_81579232cbfd41ec_importlib.spec_from_file_location('_ember_issue2015_81579232cbfd41ec', _ember_81579232cbfd41ec_path)
    if _ember_81579232cbfd41ec_spec is None or _ember_81579232cbfd41ec_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
    _ember_81579232cbfd41ec_module = _ember_81579232cbfd41ec_importlib.module_from_spec(_ember_81579232cbfd41ec_spec)
    for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
        _ember_81579232cbfd41ec_prior = _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias)
        if _ember_81579232cbfd41ec_prior is not None and _ember_81579232cbfd41ec_prior is not _ember_81579232cbfd41ec_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
        _ember_81579232cbfd41ec_sys.modules[_ember_81579232cbfd41ec_alias] = _ember_81579232cbfd41ec_module
    try:
        _ember_81579232cbfd41ec_spec.loader.exec_module(_ember_81579232cbfd41ec_module)
    except BaseException:
        for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
            if _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias) is _ember_81579232cbfd41ec_module:
                _ember_81579232cbfd41ec_sys.modules.pop(_ember_81579232cbfd41ec_alias, None)
        raise
for _ember_81579232cbfd41ec_alias in _ember_81579232cbfd41ec_aliases:
    _ember_81579232cbfd41ec_prior = _ember_81579232cbfd41ec_sys.modules.get(_ember_81579232cbfd41ec_alias)
    if _ember_81579232cbfd41ec_prior is not None and _ember_81579232cbfd41ec_prior is not _ember_81579232cbfd41ec_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data_v2.py')
    _ember_81579232cbfd41ec_sys.modules[_ember_81579232cbfd41ec_alias] = _ember_81579232cbfd41ec_module
_assert_not_heldout = getattr(_ember_81579232cbfd41ec_module, '_assert_not_heldout')
_compute_answer = getattr(_ember_81579232cbfd41ec_module, '_compute_answer')
_build_session_entries = getattr(_ember_81579232cbfd41ec_module, '_build_session_entries')
_synthesize_turn_result = getattr(_ember_81579232cbfd41ec_module, '_synthesize_turn_result')
_build_harness_builtin_assertions = getattr(_ember_81579232cbfd41ec_module, '_build_harness_builtin_assertions')
_render_pretrain_text = getattr(_ember_81579232cbfd41ec_module, '_render_pretrain_text')
_make_write_entry = getattr(_ember_81579232cbfd41ec_module, '_make_write_entry')
_make_end_turn_entry = getattr(_ember_81579232cbfd41ec_module, '_make_end_turn_entry')
run_pipeline = getattr(_ember_81579232cbfd41ec_module, 'run_pipeline')
does_not_count_self_check = getattr(_ember_81579232cbfd41ec_module, 'does_not_count_self_check')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_cbase_avir_data_v2.py

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASS_COUNT = 0
_FAIL_COUNT = 0
_RESULTS: list[tuple[str, bool, str]] = []


def _ok(name: str, condition: bool, detail: str = "") -> None:
    global _PASS_COUNT, _FAIL_COUNT
    if condition:
        _PASS_COUNT += 1
        _RESULTS.append((name, True, detail))
        print(f"PASS  {name}{': ' + detail if detail else ''}")
    else:
        _FAIL_COUNT += 1
        _RESULTS.append((name, False, detail))
        print(f"FAIL  {name}{': ' + detail if detail else ''}")


def _expect_raises(name: str, fn, exc_type=Exception) -> None:
    """Assert fn() raises exc_type."""
    try:
        fn()
        _ok(name, False, f"expected {exc_type.__name__} but no exception raised")
    except exc_type as e:
        _ok(name, True, f"raised {exc_type.__name__}: {e!s:.80}")
    except Exception as e:
        _ok(name, False, f"raised {type(e).__name__} (not {exc_type.__name__}): {e!s:.80}")


# ---------------------------------------------------------------------------
# Test 1: FIREWALL raises on heldout ids
# ---------------------------------------------------------------------------

def test_firewall_raises_on_heldout() -> None:
    print("\n--- test_firewall_raises_on_heldout ---")

    # Each h0xx id must raise ValueError
    heldout_ids = [f"h{i:03d}" for i in range(1, 21)]
    for hid in heldout_ids:
        _expect_raises(f"firewall_{hid}", lambda h=hid: _assert_not_heldout(h), ValueError)

    # Train ids must NOT raise
    train_ids = [f"t{i:03d}" for i in range(1, 25)]
    for tid in train_ids:
        try:
            _assert_not_heldout(tid)
            _ok(f"firewall_allow_{tid}", True)
        except Exception as e:
            _ok(f"firewall_allow_{tid}", False, f"raised unexpectedly: {e}")

    # Edge cases
    _expect_raises("firewall_h001_direct", lambda: _assert_not_heldout("h001"), ValueError)
    _expect_raises("firewall_h020_direct", lambda: _assert_not_heldout("h020"), ValueError)

    # Non-heldout patterns that might look like heldout
    for safe in ["t001", "x001", "H001", "h1", "h0001"]:
        try:
            _assert_not_heldout(safe)
            _ok(f"firewall_allow_{safe}", True)
        except ValueError:
            _ok(f"firewall_allow_{safe}", False, f"wrongly blocked {safe!r}")


# ---------------------------------------------------------------------------
# Test 2: answers computed from input (perturb -> answer changes)
# ---------------------------------------------------------------------------

def test_answers_computed_from_input() -> None:
    print("\n--- test_answers_computed_from_input ---")

    tasks = load_split("train")
    tasks_by_id = {t["id"]: t for t in tasks}

    # t001: sum(17, 34, 9, 41) = 101; perturb to 18 -> 102
    with tempfile.TemporaryDirectory() as tmpdir:
        task = tasks_by_id["t001"]
        sb = setup_sandbox(task, tmpdir)
        ans1 = _compute_answer(task, sb)
        _ok("t001_original_sum", ans1["output.txt"].strip() == "101", ans1["output.txt"].strip())

        # perturb numbers.txt: change 17 to 18
        (sb / "numbers.txt").write_text("18\n34\n9\n41\n")
        ans2 = _compute_answer(task, sb)
        _ok("t001_perturbed_sum", ans2["output.txt"].strip() == "102", ans2["output.txt"].strip())
        _ok("t001_answer_changed", ans1 != ans2, f"{ans1} vs {ans2}")

    # t008: winner is bob; perturb scores so alice wins
    with tempfile.TemporaryDirectory() as tmpdir:
        task = tasks_by_id["t008"]
        sb = setup_sandbox(task, tmpdir)
        ans1 = _compute_answer(task, sb)
        _ok("t008_original_winner", "bob" in ans1["winner.txt"], ans1["winner.txt"].strip())

        # perturb scores.txt: alice gets 99 (highest)
        (sb / "scores.txt").write_text("alice:99\nbob:91\ncarol:58\ndave:84\n")
        ans2 = _compute_answer(task, sb)
        _ok("t008_perturbed_winner", "alice" in ans2["winner.txt"], ans2["winner.txt"].strip())
        _ok("t008_answer_changed", ans1 != ans2, f"{ans1} vs {ans2}")

    # t019 (count=3): perturb to verify two-file count changes
    with tempfile.TemporaryDirectory() as tmpdir:
        task = tasks_by_id["t019"]
        sb = setup_sandbox(task, tmpdir)
        ans1 = _compute_answer(task, sb)
        _ok("t019_original_total", "5" in ans1["line_tally.txt"], ans1["line_tally.txt"].strip())

        # add a line to a.txt
        (sb / "a.txt").write_text("line_A1\nline_A2\nline_A3\n")
        ans2 = _compute_answer(task, sb)
        _ok("t019_perturbed_total", "6" in ans2["line_tally.txt"], ans2["line_tally.txt"].strip())
        _ok("t019_answer_changed", ans1 != ans2)

    # Verify all 24 tasks can compute without error
    for task in tasks:
        with tempfile.TemporaryDirectory() as tmpdir:
            sb = setup_sandbox(task, tmpdir)
            try:
                ans = _compute_answer(task, sb)
                _ok(f"compute_no_error_{task['id']}", True, list(ans.keys())[0])
            except Exception as e:
                _ok(f"compute_no_error_{task['id']}", False, str(e))


# ---------------------------------------------------------------------------
# Test 3: wrong answer fails file_contains
# ---------------------------------------------------------------------------

def test_wrong_answer_fails_file_contains() -> None:
    print("\n--- test_wrong_answer_fails_file_contains ---")

    tasks = load_split("train")
    task = next(t for t in tasks if t["id"] == "t001")

    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)
        turn_start_s = time.time() - 0.001

        # Write a WRONG answer (999 instead of 101)
        wrong_content = "999\n"
        (sandbox / "output.txt").write_text(wrong_content)

        # Synthesize JSONL with wrong content
        wrong_entries = [
            _make_write_entry("output.txt", wrong_content, "tu_1"),
            _make_end_turn_entry(),
        ]
        jsonl_path = tmpdir_path / "session_wrong.jsonl"
        with jsonl_path.open("w") as fh:
            for e in wrong_entries:
                fh.write(json.dumps(e) + "\n")

        result = _synthesize_turn_result(jsonl_path, turn_start_s)

        # Build assertions — the file_contains needle is "101" but we wrote "999"
        assertions = [
            {"type": "file_exists", "path": "output.txt"},
            {"type": "file_contains", "path": "output.txt", "needle": "101"},
            {"type": "jsonl_tool_call_this_turn"},
            {"type": "jsonl_stop_reason_eq", "expected": "end_turn"},
        ]
        passed, failures = harness_run_assertions(result, sandbox, assertions)
        _ok("wrong_answer_fails_file_contains",
            not passed and any("file_contains" in f for f in failures),
            f"passed={passed}, failures={failures}")

    # Also verify correct answer passes file_contains
    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)
        turn_start_s = time.time() - 0.001

        correct_content = "101\n"
        (sandbox / "output.txt").write_text(correct_content)

        correct_entries = [
            _make_write_entry("output.txt", correct_content, "tu_1"),
            _make_end_turn_entry(),
        ]
        jsonl_path = tmpdir_path / "session_correct.jsonl"
        with jsonl_path.open("w") as fh:
            for e in correct_entries:
                fh.write(json.dumps(e) + "\n")

        result = _synthesize_turn_result(jsonl_path, turn_start_s)
        assertions = [
            {"type": "file_exists", "path": "output.txt"},
            {"type": "file_contains", "path": "output.txt", "needle": "101"},
            {"type": "jsonl_tool_call_this_turn"},
            {"type": "jsonl_stop_reason_eq", "expected": "end_turn"},
        ]
        passed, failures = harness_run_assertions(result, sandbox, assertions)
        _ok("correct_answer_passes_file_contains", passed, f"failures={failures}")


# ---------------------------------------------------------------------------
# Test 4: missing tool_use fails jsonl_tool_call_this_turn and count_gte
# ---------------------------------------------------------------------------

def test_missing_tool_use_fails_gates() -> None:
    print("\n--- test_missing_tool_use_fails_gates ---")

    tasks = load_split("train")
    task = next(t for t in tasks if t["id"] == "t002")  # count=2 gte

    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)
        turn_start_s = time.time() - 0.001

        correct_content = "5\n"
        (sandbox / "count.txt").write_text(correct_content)

        # Synthesize JSONL with ONLY end_turn — no tool_use entries
        text_only_entries = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                    "content": [{"type": "text", "text": "I counted 5 lines in words.txt."}],
                },
            }
        ]
        jsonl_path = tmpdir_path / "session_text_only.jsonl"
        with jsonl_path.open("w") as fh:
            for e in text_only_entries:
                fh.write(json.dumps(e) + "\n")

        result = _synthesize_turn_result(jsonl_path, turn_start_s)

        # Test jsonl_tool_call_this_turn
        _ok("no_tool_use_tool_call_seen_false",
            not result.tool_call_seen_this_turn,
            f"tool_call_seen={result.tool_call_seen_this_turn}")

        assertions_gate = [{"type": "jsonl_tool_call_this_turn"}]
        passed, failures = harness_run_assertions(result, sandbox, assertions_gate)
        _ok("no_tool_use_fails_tool_call_gate",
            not passed,
            f"passed={passed}, failures={failures}")

        # Test jsonl_tool_call_count_gte via ember_avir_tasks
        # issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
        import importlib.util as _ember_6c243c4c73ac7e2b_importlib
        import sys as _ember_6c243c4c73ac7e2b_sys
        from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
        _ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
        if not _ember_6c243c4c73ac7e2b_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
        _ember_6c243c4c73ac7e2b_existing = []
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
            if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
                _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
        if len(_ember_6c243c4c73ac7e2b_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        if _ember_6c243c4c73ac7e2b_existing:
            _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
            _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
            if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
        else:
            _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
            if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
            _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
            for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
                _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
                if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
                _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
            try:
                _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
            except BaseException:
                for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
                    if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                        _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
                raise
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
            if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
            _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
        _eat = _ember_6c243c4c73ac7e2b_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py
        task_result = _eat.run_assertions(task, sandbox, session_jsonl_path=str(jsonl_path))
        gte_details = [d for d in task_result["details"]
                       if d["type"] == "jsonl_tool_call_count_gte"]
        _ok("no_tool_use_fails_count_gte",
            any(d.get("status") == "FAIL" for d in gte_details),
            f"gte_details={gte_details}")

    # Also verify that 1 tool_use fails gte=2
    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)
        turn_start_s = time.time() - 0.001

        correct_content = "5\n"
        (sandbox / "count.txt").write_text(correct_content)

        # Only 1 tool_use (gte=2 should fail)
        one_tool_entries = [
            _make_write_entry("count.txt", correct_content, "tu_1"),
            _make_end_turn_entry(),
        ]
        jsonl_path = tmpdir_path / "session_one_tool.jsonl"
        with jsonl_path.open("w") as fh:
            for e in one_tool_entries:
                fh.write(json.dumps(e) + "\n")

        # issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
        import importlib.util as _ember_6c243c4c73ac7e2b_importlib
        import sys as _ember_6c243c4c73ac7e2b_sys
        from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
        _ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
        if not _ember_6c243c4c73ac7e2b_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
        _ember_6c243c4c73ac7e2b_existing = []
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
            if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
                _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
        if len(_ember_6c243c4c73ac7e2b_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        if _ember_6c243c4c73ac7e2b_existing:
            _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
            _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
            if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
        else:
            _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
            if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
            _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
            for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
                _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
                if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
                _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
            try:
                _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
            except BaseException:
                for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
                    if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                        _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
                raise
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
            if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
            _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
        _eat = _ember_6c243c4c73ac7e2b_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py
        task_result = _eat.run_assertions(task, sandbox, session_jsonl_path=str(jsonl_path))
        gte_details = [d for d in task_result["details"]
                       if d["type"] == "jsonl_tool_call_count_gte"]
        _ok("one_tool_fails_gte2",
            any(d.get("status") == "FAIL" for d in gte_details),
            f"gte_details={gte_details}")


# ---------------------------------------------------------------------------
# Test 5: pre-seeded file (mtime before turn_start) fails file_created_this_turn
# ---------------------------------------------------------------------------

def test_preseeded_file_fails_mtime_gate() -> None:
    print("\n--- test_preseeded_file_fails_mtime_gate ---")

    tasks = load_split("train")
    task = next(t for t in tasks if t["id"] == "t001")

    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)

        # Pre-seed the output file BEFORE recording turn_start
        pre_seed_content = "101\n"
        (sandbox / "output.txt").write_text(pre_seed_content)

        # Sleep briefly to ensure mtime is in the past
        time.sleep(0.05)

        # Record turn_start AFTER the pre-seed
        turn_start_s = time.time()

        # Synthesize JSONL (valid tool_use + end_turn)
        valid_entries = [
            _make_write_entry("output.txt", pre_seed_content, "tu_1"),
            _make_end_turn_entry(),
        ]
        jsonl_path = tmpdir_path / "session_preseed.jsonl"
        with jsonl_path.open("w") as fh:
            for e in valid_entries:
                fh.write(json.dumps(e) + "\n")

        result = _synthesize_turn_result(jsonl_path, turn_start_s)

        # file_created_this_turn should FAIL because mtime < turn_start_s
        assertions = [{"type": "file_created_this_turn", "path": "output.txt"}]
        passed, failures = harness_run_assertions(result, sandbox, assertions)
        _ok("preseed_fails_mtime_gate",
            not passed and any("file_created_this_turn" in f for f in failures),
            f"passed={passed}, failures={failures}")

    # Verify that file written AFTER turn_start PASSES the gate
    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)

        # Record turn_start BEFORE writing the file
        turn_start_s = time.time() - 0.001

        correct_content = "101\n"
        (sandbox / "output.txt").write_text(correct_content)

        valid_entries = [
            _make_write_entry("output.txt", correct_content, "tu_1"),
            _make_end_turn_entry(),
        ]
        jsonl_path = tmpdir_path / "session_after_turn.jsonl"
        with jsonl_path.open("w") as fh:
            for e in valid_entries:
                fh.write(json.dumps(e) + "\n")

        result = _synthesize_turn_result(jsonl_path, turn_start_s)
        assertions = [{"type": "file_created_this_turn", "path": "output.txt"}]
        passed, failures = harness_run_assertions(result, sandbox, assertions)
        _ok("after_turn_start_passes_mtime_gate",
            passed,
            f"failures={failures}")


# ---------------------------------------------------------------------------
# Test 6: t019 requires count=3 tool_use entries
# ---------------------------------------------------------------------------

def test_t019_requires_three_tool_calls() -> None:
    print("\n--- test_t019_requires_three_tool_calls ---")

    tasks = load_split("train")
    task = next(t for t in tasks if t["id"] == "t019")

    with tempfile.TemporaryDirectory() as tmpdir_outer:
        tmpdir_path = pathlib.Path(tmpdir_outer)
        sandbox = setup_sandbox(task, tmpdir_path)
        turn_start_s = time.time() - 0.001

        # Compute correct answer
        ans = _compute_answer(task, sandbox)
        output_file = list(ans.keys())[0]
        output_content = ans[output_file]
        (sandbox / output_file).write_text(output_content)

        # Build entries: 3 tool_use (Read a.txt, Read b.txt, Write line_tally.txt)
        entries = _build_session_entries(task, ans)
        tool_use_count = sum(
            1 for e in entries
            if e.get("message", {}).get("stop_reason") == "tool_use"
        )
        _ok("t019_entries_have_3_tool_use",
            tool_use_count == 3,
            f"tool_use_count={tool_use_count}")

        jsonl_path = tmpdir_path / "session_t019.jsonl"
        with jsonl_path.open("w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")

        # issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
        import importlib.util as _ember_6c243c4c73ac7e2b_importlib
        import sys as _ember_6c243c4c73ac7e2b_sys
        from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
        _ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
        if not _ember_6c243c4c73ac7e2b_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
        _ember_6c243c4c73ac7e2b_existing = []
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
            if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
                _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
        if len(_ember_6c243c4c73ac7e2b_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        if _ember_6c243c4c73ac7e2b_existing:
            _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
            _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
            if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
        else:
            _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
            if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
            _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
            for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
                _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
                if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
                _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
            try:
                _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
            except BaseException:
                for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
                    if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                        _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
                raise
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
            if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
            _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
        _eat = _ember_6c243c4c73ac7e2b_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py
        task_result = _eat.run_assertions(task, sandbox, session_jsonl_path=str(jsonl_path))
        gte_details = [d for d in task_result["details"]
                       if d["type"] == "jsonl_tool_call_count_gte"]
        _ok("t019_count3_passes_gte",
            all(d.get("status") == "PASS" for d in gte_details),
            f"gte_details={gte_details}")


# ---------------------------------------------------------------------------
# Test 7: full pipeline produces R=1 traces and round-trips shard
# ---------------------------------------------------------------------------

def test_full_pipeline_round_trip() -> None:
    print("\n--- test_full_pipeline_round_trip ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_pipeline(output_dir=tmpdir, verbose=False)

        _ok("pipeline_traces_emitted_gt0",
            result["traces_emitted"] > 0,
            f"emitted={result['traces_emitted']}")
        _ok("pipeline_traces_full_R1_gt0",
            result["traces_full_R1"] > 0,
            f"full_R1={result['traces_full_R1']}")
        _ok("pipeline_roundtrip_ok",
            result["roundtrip_ok"],
            f"roundtrip={result['roundtrip_ok']}")
        _ok("pipeline_shard_tokens_gt0",
            result["shard_tokens"] > 0,
            f"tokens={result['shard_tokens']}")
        _ok("pipeline_no_dropped_tasks",
            len(result["dropped"]) == 0,
            f"dropped={result['dropped']}")

        # All 24 tasks should pass
        _ok("pipeline_all_24_pass",
            result["traces_full_R1"] == 24,
            f"full_R1={result['traces_full_R1']}")

        # Verify per-task: every task has r=1
        failed_tasks = [p for p in result["per_task"] if p.get("r") != 1]
        _ok("pipeline_all_per_task_r1",
            len(failed_tasks) == 0,
            f"failed_tasks={[p['id'] for p in failed_tasks]}")

        # Load shard directly via numpy and verify token count
        import numpy as np
        shard_path = result["shard_path"]
        rt_arr = np.fromfile(shard_path, dtype="<u2")
        _ok("pipeline_shard_token_count_matches",
            int(len(rt_arr)) == result["shard_tokens"],
            f"loaded={len(rt_arr)}, expected={result['shard_tokens']}")

        # Verify no heldout ids in per_task
        heldout_in_corpus = [p for p in result["per_task"] if p["id"].startswith("h")]
        _ok("pipeline_no_heldout_in_corpus",
            len(heldout_in_corpus) == 0,
            f"heldout_in_corpus={heldout_in_corpus}")

        # Verify all token ids < 32000
        max_id = int(rt_arr.max()) if len(rt_arr) > 0 else 0
        _ok("pipeline_token_ids_lt_32000",
            max_id < 32000,
            f"max_id={max_id}")


# ---------------------------------------------------------------------------
# Test 8: does_not_count self-check string contains all 4 defect closures
# ---------------------------------------------------------------------------

def test_does_not_count_self_check() -> None:
    print("\n--- test_does_not_count_self_check ---")
    text = does_not_count_self_check()
    _ok("selfcheck_no_preseed", "NO_SANDBOX_PRESEED" in text)
    _ok("selfcheck_no_jsonl_none", "NO_SESSION_JSONL_NONE" in text)
    _ok("selfcheck_canonical_format", "CANONICAL_FORMAT" in text)
    _ok("selfcheck_answers_computed", "ANSWERS_COMPUTED_FROM_INPUT" in text)
    _ok("selfcheck_firewall_enforced", "FIREWALL_ENFORCED" in text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== test_ember_cbase_avir_data_v2 ===")

    test_firewall_raises_on_heldout()
    test_answers_computed_from_input()
    test_wrong_answer_fails_file_contains()
    test_missing_tool_use_fails_gates()
    test_preseeded_file_fails_mtime_gate()
    test_t019_requires_three_tool_calls()
    test_full_pipeline_round_trip()
    test_does_not_count_self_check()

    print(f"\n=== SUMMARY: {_PASS_COUNT} PASS, {_FAIL_COUNT} FAIL ===")
    if _FAIL_COUNT > 0:
        print("FAILED TESTS:")
        for name, ok, detail in _RESULTS:
            if not ok:
                print(f"  FAIL  {name}: {detail}")
        sys.exit(1)
    else:
        print("ALL PASS")


if __name__ == "__main__":
    main()
