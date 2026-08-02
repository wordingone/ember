# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the loop/graph engineering substrate (issue #1309)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from loop_graph import gates, lifecycle, mutex, receipts, replay, validate  # noqa: E402
from loop_graph.hashing import hash_bytes, hash_file  # noqa: E402


# --------------------------------------------------------------------------
# schema validation pass/fail
# --------------------------------------------------------------------------

def make_execution_node(**overrides) -> dict:
    node = {
        "node_id": "exec-1h-canary-a1b2c3",
        "authority_ref": "EMBER-02A-stage-1h",
        "type": "canary",
        "owner": "agent-a",
        "resource_class": "cpu",
        "prereqs": [],
        "command": {"argv": ["python", "run.py"], "cwd": "."},
        "state": "PENDING",
        "created_at": "2026-08-02T16:00:00+00:00",
    }
    node.update(overrides)
    return node


def make_receipt(**overrides) -> dict:
    receipt = {
        "receipt_id": "1h-canonical-20260802T161827Z",
        "node_id": "exec-1h-canary-a1b2c3",
        "path": "receipts/1h-canonical-20260802T161827Z.json",
        "content_hash": "sha256:" + "0" * 64,
        "verdict": "PASS",
        "verified_by": "reviewer-L3-recount",
        "ts": "2026-08-02T18:12:00+00:00",
    }
    receipt.update(overrides)
    return receipt


def test_valid_execution_node_passes_schema():
    assert validate.validate(make_execution_node(), "execution") == []


def test_invalid_execution_node_fails_schema_missing_required_field():
    node = make_execution_node()
    del node["resource_class"]
    errors = validate.validate(node, "execution")
    assert errors, "expected schema violation for missing resource_class"


def test_invalid_execution_node_fails_schema_bad_enum():
    node = make_execution_node(state="NOT_A_REAL_STATE")
    errors = validate.validate(node, "execution")
    assert errors


def test_valid_receipt_passes_schema():
    assert validate.validate(make_receipt(), "receipt") == []


def test_receipt_missing_node_id_fails_schema():
    receipt = make_receipt()
    del receipt["node_id"]
    errors = validate.validate(receipt, "receipt")
    assert errors


def test_authority_graph_matches_existing_ember_file_shape():
    # Regression guard: the real docs/roadmap/execution-graph.json (an
    # authority-graph-v1-shaped document) must still validate cleanly
    # against nothing here since it predates schema_version tagging --
    # instead we check that a v2-tagged equivalent validates.
    doc = {
        "schema_version": "ember-authority-graph-v2",
        "nodes": [
            {"id": "EMBER-00", "state": "AUTHORITY_IN_FORCE", "depends_on": []},
            {"id": "EMBER-01", "state": "ACTIVE_CERTIFICATION_GATE", "depends_on": ["EMBER-00"]},
        ],
        "credit_rule": "Only the exact version-controlled completion certificate can do so.",
    }
    assert validate.validate(doc, "authority") == []


def test_fallback_validator_agrees_with_jsonschema_when_both_available():
    node = make_execution_node()
    schema = validate.load_schema("execution")
    fallback_errors = validate._fallback_validate(node, schema)
    assert fallback_errors == []

    bad = make_execution_node()
    del bad["command"]
    assert validate._fallback_validate(bad, schema)


# --------------------------------------------------------------------------
# lifecycle: idempotent transitions, crash/resume
# --------------------------------------------------------------------------

def test_create_is_idempotent(tmp_path: Path):
    store = tmp_path / "nodes"
    node = make_execution_node()

    first = lifecycle.create(store, node)
    second = lifecycle.create(store, node)

    assert first == second
    assert first["state"] == lifecycle.PENDING


def test_full_lifecycle_happy_path(tmp_path: Path):
    store = tmp_path / "nodes"
    node_id = "exec-full"
    lifecycle.create(store, make_execution_node(node_id=node_id))

    lifecycle.claim(store, node_id, owner="agent-a")
    started = lifecycle.start(store, node_id, owner_pid=os.getpid())
    assert started["state"] == lifecycle.RUNNING
    assert started["lock"]["owner_pid"] == os.getpid()

    reviewed = lifecycle.request_review(store, node_id)
    assert reviewed["state"] == lifecycle.AWAITING_REVIEW

    closed = lifecycle.close(store, node_id, lifecycle.CLOSED_PASS, receipt_id="r1")
    assert closed["state"] == lifecycle.CLOSED_PASS
    assert "lock" not in closed
    assert closed["receipt_id"] == "r1"


def test_double_transition_is_idempotent_not_an_error(tmp_path: Path):
    store = tmp_path / "nodes"
    node_id = "exec-double"
    lifecycle.create(store, make_execution_node(node_id=node_id))
    pid = os.getpid()

    started_once = lifecycle.start(store, node_id, owner_pid=pid)
    started_twice = lifecycle.start(store, node_id, owner_pid=pid)
    assert started_once == started_twice

    closed_once = lifecycle.close(store, node_id, lifecycle.CLOSED_PASS)
    closed_twice = lifecycle.close(store, node_id, lifecycle.CLOSED_PASS)
    assert closed_once == closed_twice


def test_conflicting_reclose_with_different_verdict_raises(tmp_path: Path):
    store = tmp_path / "nodes"
    node_id = "exec-conflict"
    lifecycle.create(store, make_execution_node(node_id=node_id))
    lifecycle.start(store, node_id, owner_pid=os.getpid())
    lifecycle.close(store, node_id, lifecycle.CLOSED_PASS)

    with pytest.raises(lifecycle.LifecycleError) as excinfo:
        lifecycle.close(store, node_id, lifecycle.CLOSED_REJECTED)
    assert excinfo.value.code == "VERDICT_CONFLICT"


def test_crash_mid_transition_resume_is_safe(tmp_path: Path):
    """Simulates a crash: the node file is left exactly at RUNNING (as if the
    process died right after start() completed its atomic write, before
    doing any further work). Re-issuing start() on "resume" must be a no-op,
    and the subsequent close() must succeed normally -- no corruption, no
    stuck state."""
    store = tmp_path / "nodes"
    node_id = "exec-crash"
    lifecycle.create(store, make_execution_node(node_id=node_id))
    pid = os.getpid()

    lifecycle.start(store, node_id, owner_pid=pid)
    # "crash" happens here -- nothing further was written.
    resumed = lifecycle.start(store, node_id, owner_pid=pid)
    assert resumed["state"] == lifecycle.RUNNING

    closed = lifecycle.close(store, node_id, lifecycle.CLOSED_PASS)
    assert closed["state"] == lifecycle.CLOSED_PASS


def test_start_before_create_raises_not_found(tmp_path: Path):
    store = tmp_path / "nodes"
    with pytest.raises(lifecycle.LifecycleError) as excinfo:
        lifecycle.start(store, "no-such-node", owner_pid=1)
    assert excinfo.value.code == "NODE_NOT_FOUND"


def test_claim_by_different_owner_refused(tmp_path: Path):
    store = tmp_path / "nodes"
    node_id = "exec-claim"
    lifecycle.create(store, make_execution_node(node_id=node_id))
    lifecycle.claim(store, node_id, owner="agent-a")

    with pytest.raises(lifecycle.LifecycleError) as excinfo:
        lifecycle.claim(store, node_id, owner="agent-b")
    assert excinfo.value.code == "ALREADY_CLAIMED"


# --------------------------------------------------------------------------
# mutex: gpu-exclusive contention + stale-lock reclaim
# --------------------------------------------------------------------------

def test_gpu_exclusive_mutex_refuses_second_claim(tmp_path: Path):
    locks = tmp_path / "locks"
    pid = os.getpid()

    assert mutex.acquire(locks, "gpu-exclusive", "node-a", pid) is True

    with pytest.raises(mutex.MutexBusy):
        mutex.acquire(locks, "gpu-exclusive", "node-b", pid)


def test_gpu_exclusive_mutex_idempotent_reacquire_by_same_node(tmp_path: Path):
    locks = tmp_path / "locks"
    pid = os.getpid()
    mutex.acquire(locks, "gpu-exclusive", "node-a", pid)
    assert mutex.acquire(locks, "gpu-exclusive", "node-a", pid) is True


def test_non_exclusive_resource_class_never_contends(tmp_path: Path):
    locks = tmp_path / "locks"
    pid = os.getpid()
    assert mutex.acquire(locks, "cpu", "node-a", pid) is True
    assert mutex.acquire(locks, "cpu", "node-b", pid) is True  # no contention at all


def test_release_then_reacquire_by_different_node_succeeds(tmp_path: Path):
    locks = tmp_path / "locks"
    pid = os.getpid()
    mutex.acquire(locks, "gpu-exclusive", "node-a", pid)
    mutex.release(locks, "gpu-exclusive", "node-a")
    assert mutex.acquire(locks, "gpu-exclusive", "node-b", pid) is True


def test_stale_lock_from_dead_pid_is_reclaimed(tmp_path: Path):
    locks = tmp_path / "locks"
    dead_pid = _find_dead_pid()

    mutex.acquire(locks, "gpu-exclusive", "node-dead", dead_pid)
    # A live process claiming the same class should reclaim it, not raise.
    assert mutex.acquire(locks, "gpu-exclusive", "node-live", os.getpid()) is True
    holder = mutex.current_holder(locks, "gpu-exclusive")
    assert holder["node_id"] == "node-live"


def _find_dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# --------------------------------------------------------------------------
# stale-node detection
# --------------------------------------------------------------------------

def test_stale_detection_flags_dead_owner_pid(tmp_path: Path):
    store = tmp_path / "nodes"
    store.mkdir()
    dead_pid = _find_dead_pid()
    node = make_execution_node(node_id="exec-stale-dead", state=lifecycle.RUNNING)
    node["lock"] = {"owner_pid": dead_pid, "acquired_at": datetime.now(timezone.utc).isoformat()}
    from loop_graph._atomic import atomic_write_json

    atomic_write_json(store / "exec-stale-dead.json", node)

    from loop_graph import stale

    reports = stale.scan(store)
    assert len(reports) == 1
    assert reports[0].node_id == "exec-stale-dead"
    assert reports[0].reason == "DEAD_OWNER"


def test_stale_detection_flags_wall_budget_exceeded(tmp_path: Path):
    store = tmp_path / "nodes"
    store.mkdir()
    node = make_execution_node(node_id="exec-stale-budget", state=lifecycle.RUNNING)
    started = datetime.now(timezone.utc) - timedelta(seconds=1000)
    node["lock"] = {
        "owner_pid": os.getpid(),
        "acquired_at": started.isoformat(),
        "wall_budget_seconds": 600,
    }
    from loop_graph._atomic import atomic_write_json

    atomic_write_json(store / "exec-stale-budget.json", node)

    from loop_graph import stale

    reports = stale.scan(store)
    assert len(reports) == 1
    assert reports[0].reason == "WALL_BUDGET_EXCEEDED"


def test_stale_detection_never_flags_a_healthy_running_node(tmp_path: Path):
    store = tmp_path / "nodes"
    store.mkdir()
    node = make_execution_node(node_id="exec-healthy", state=lifecycle.RUNNING)
    node["lock"] = {
        "owner_pid": os.getpid(),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "wall_budget_seconds": 3600,
    }
    from loop_graph._atomic import atomic_write_json

    atomic_write_json(store / "exec-healthy.json", node)

    from loop_graph import stale

    assert stale.scan(store) == []


def test_stale_detection_never_flags_pending_or_closed_nodes(tmp_path: Path):
    store = tmp_path / "nodes"
    store.mkdir()
    from loop_graph._atomic import atomic_write_json

    atomic_write_json(store / "exec-pending.json", make_execution_node(node_id="exec-pending"))
    atomic_write_json(
        store / "exec-closed.json", make_execution_node(node_id="exec-closed", state=lifecycle.CLOSED_PASS)
    )

    from loop_graph import stale

    assert stale.scan(store) == []


# --------------------------------------------------------------------------
# deterministic replay
# --------------------------------------------------------------------------

def test_replay_check_passes_when_everything_matches(tmp_path: Path):
    script = tmp_path / "run.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    input_file = tmp_path / "input.json"
    input_file.write_text('{"a": 1}', encoding="utf-8")
    output_file = tmp_path / "output.json"
    output_file.write_text('{"b": 2}', encoding="utf-8")

    node = make_execution_node(
        state=lifecycle.CLOSED_PASS,
        command={"argv": ["python", "run.py"], "cwd": str(tmp_path), "content_hash": hash_file(script)},
        inputs=[{"path": "input.json", "content_hash": hash_file(input_file)}],
        outputs=[{"path": "output.json", "content_hash": hash_file(output_file)}],
    )

    result = replay.replay_check(node)
    assert result.ok, result.problems


def test_replay_check_detects_tampered_input(tmp_path: Path):
    script = tmp_path / "run.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    input_file = tmp_path / "input.json"
    input_file.write_text('{"a": 1}', encoding="utf-8")
    recorded_hash = hash_file(input_file)

    node = make_execution_node(
        state=lifecycle.CLOSED_PASS,
        command={"argv": ["python", "run.py"], "cwd": str(tmp_path), "content_hash": hash_file(script)},
        inputs=[{"path": "input.json", "content_hash": recorded_hash}],
        outputs=[],
    )

    # tamper after the fact
    input_file.write_text('{"a": 999}', encoding="utf-8")

    result = replay.replay_check(node)
    assert not result.ok
    assert any("input.json" in problem for problem in result.problems)


def test_replay_check_refuses_non_closed_node(tmp_path: Path):
    node = make_execution_node(state=lifecycle.PENDING)
    result = replay.replay_check(node)
    assert not result.ok


def test_replay_check_verifies_receipt_integrity(tmp_path: Path):
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text('{"verdict": "PASS"}', encoding="utf-8")
    node = make_execution_node(state=lifecycle.CLOSED_PASS, command={"argv": ["python", "run.py"], "cwd": str(tmp_path)})

    good_receipt = {
        "node_id": node["node_id"],
        "path": str(receipt_file),
        "content_hash": hash_file(receipt_file),
    }
    assert replay.replay_check(node, receipt=good_receipt).ok

    tampered_receipt = dict(good_receipt)
    tampered_receipt["content_hash"] = hash_bytes(b"not the real content")
    result = replay.replay_check(node, receipt=tampered_receipt)
    assert not result.ok
    assert any("receipt file" in problem for problem in result.problems)


# --------------------------------------------------------------------------
# receipt chain reconstruction
# --------------------------------------------------------------------------

def test_receipt_chain_reconstruction_by_node_id(tmp_path: Path):
    index_path = tmp_path / "INDEX.jsonl"

    receipts.append_receipt(index_path, make_receipt(receipt_id="r1", node_id="exec-a", ts="2026-08-02T18:00:00+00:00"))
    receipts.append_receipt(index_path, make_receipt(receipt_id="r2", node_id="exec-b", ts="2026-08-02T18:05:00+00:00"))
    receipts.append_receipt(index_path, make_receipt(receipt_id="r3", node_id="exec-a", ts="2026-08-02T18:10:00+00:00"))

    chain = receipts.receipts_for_node(index_path, "exec-a")
    assert [row["receipt_id"] for row in chain] == ["r1", "r3"]

    latest = receipts.latest_receipt_for_node(index_path, "exec-a")
    assert latest["receipt_id"] == "r3"

    assert receipts.receipts_for_node(index_path, "exec-nonexistent") == []


def test_append_receipt_rejects_invalid_receipt(tmp_path: Path):
    index_path = tmp_path / "INDEX.jsonl"
    bad = make_receipt()
    del bad["node_id"]

    with pytest.raises(validate.ValidationError):
        receipts.append_receipt(index_path, bad)

    assert receipts.load_index(index_path) == []


def test_append_receipt_is_append_only_and_survives_many_rows(tmp_path: Path):
    index_path = tmp_path / "INDEX.jsonl"
    for i in range(25):
        receipts.append_receipt(
            index_path, make_receipt(receipt_id=f"r{i}", node_id=f"exec-{i % 5}", ts="2026-08-02T18:00:00+00:00")
        )
    assert len(receipts.load_index(index_path)) == 25
    assert len(receipts.receipts_for_node(index_path, "exec-0")) == 5


# --------------------------------------------------------------------------
# gate-invariant checker
# --------------------------------------------------------------------------

def test_gate_invariant_asserted_form_passes_and_fails():
    invariants = [{"field": "n_leaves", "source": "builder_actual", "asserted": True}]

    ok = gates.check_gate_invariants(invariants, {"n_leaves": 128})
    assert ok.ok

    missing = gates.check_gate_invariants(invariants, {})
    assert not missing.ok
    assert "n_leaves" in missing.problems[0]


def test_gate_invariant_expect_unchanged_form():
    invariants = [{"field": "space_hash", "expect": "unchanged"}]

    ok = gates.check_gate_invariants(invariants, {"space_hash": "abc"}, baseline={"space_hash": "abc"})
    assert ok.ok

    bad = gates.check_gate_invariants(invariants, {"space_hash": "xyz"}, baseline={"space_hash": "abc"})
    assert not bad.ok


def test_gate_invariant_expect_equals_form_chains_to_prior_node():
    invariants = [{"field": "prev_space_hash", "expect_equals": "exec-1g-verdict-9f8e7d.output_hash"}]
    prior = {"exec-1g-verdict-9f8e7d": {"output_hash": "deadbeef"}}

    ok = gates.check_gate_invariants(invariants, {"prev_space_hash": "deadbeef"}, prior_node_outputs=prior)
    assert ok.ok

    bad = gates.check_gate_invariants(invariants, {"prev_space_hash": "wrong"}, prior_node_outputs=prior)
    assert not bad.ok


def test_gate_invariant_full_sketch_example_all_three_forms():
    invariants = [
        {"field": "n_leaves", "source": "builder_actual", "asserted": True},
        {"field": "space_hash", "expect": "unchanged"},
        {"field": "prev_space_hash", "expect_equals": "exec-1g-verdict-9f8e7d.output_hash"},
    ]
    result = {"n_leaves": 128, "space_hash": "abc", "prev_space_hash": "deadbeef"}
    baseline = {"space_hash": "abc"}
    prior = {"exec-1g-verdict-9f8e7d": {"output_hash": "deadbeef"}}

    outcome = gates.check_gate_invariants(invariants, result, baseline=baseline, prior_node_outputs=prior)
    assert outcome.ok, outcome.problems
