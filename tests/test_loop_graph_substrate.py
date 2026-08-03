# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the loop/graph engineering substrate (issue #1309)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from loop_graph import gates, lifecycle, mutex, procid, receipts, replay, validate  # noqa: E402
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


def test_gate_invariant_unrecognized_expect_value_fails_closed():
    """review-pr1310.md MEDIUM-1: a typo'd expect directive must be reported,
    never silently pass through as ok=True."""
    invariants = [{"field": "space_hash", "expect": "unchagned"}]
    result = gates.check_gate_invariants(invariants, {"space_hash": "abc"}, baseline={"space_hash": "abc"})
    assert not result.ok
    assert any("unrecognized expect directive" in problem for problem in result.problems)


def test_gate_invariant_directive_less_entry_fails_closed():
    """review-pr1310.md MEDIUM-1: {"field": F} with none of asserted/expect/
    expect_equals must be reported, never silently pass through."""
    invariants = [{"field": "n_leaves"}]
    result = gates.check_gate_invariants(invariants, {"n_leaves": 128})
    assert not result.ok
    assert any("no recognized directive" in problem for problem in result.problems)


def test_gate_invariant_expect_unchanged_typo_rejected_by_schema():
    """review-pr1310.md MEDIUM-1: the schema enum-restricts expect, so the
    same typo is caught at validation time too, independent of gates.py."""
    node = make_execution_node(gate_invariants=[{"field": "space_hash", "expect": "unchagned"}])
    errors = validate.validate(node, "execution")
    assert errors


# --------------------------------------------------------------------------
# concurrency: true append-only receipts (MAJOR-1)
# --------------------------------------------------------------------------

def _append_worker_script(index_path: Path, worker_id: int, count: int) -> str:
    scripts_dir = str(REPO_ROOT / "scripts").replace("\\", "\\\\")
    index_str = str(index_path).replace("\\", "\\\\")
    return f"""
import sys
sys.path.insert(0, "{scripts_dir}")
from pathlib import Path
from loop_graph import receipts

for i in range({count}):
    receipts.append_receipt(Path("{index_str}"), {{
        "receipt_id": f"w{worker_id}-{{i}}",
        "node_id": "exec-{worker_id}",
        "path": "receipts/x.json",
        "content_hash": "sha256:" + "0" * 64,
        "verdict": "PASS",
        "verified_by": "reviewer-L3-recount",
        "ts": "2026-08-02T18:00:00+00:00",
    }})
"""


def test_concurrent_appends_across_processes_lose_no_rows(tmp_path: Path):
    """review-pr1310.md MAJOR-1 required test: N=8 processes x 25 appends
    each -> exactly 200 rows, all parseable. A read-modify-replace append
    (the pre-fix implementation) would silently drop rows here whenever two
    processes' os.replace calls raced; the locked true-append must not."""
    index_path = tmp_path / "INDEX.jsonl"
    workers = 8
    per_worker = 25

    procs = [
        subprocess.Popen([sys.executable, "-c", _append_worker_script(index_path, worker_id, per_worker)])
        for worker_id in range(workers)
    ]
    for proc in procs:
        assert proc.wait() == 0

    rows = receipts.load_index(index_path)  # raises on any unparseable row
    assert len(rows) == workers * per_worker

    for worker_id in range(workers):
        assert len(receipts.receipts_for_node(index_path, f"exec-{worker_id}")) == per_worker


# --------------------------------------------------------------------------
# concurrency: atomic mutex acquire (MAJOR-2)
# --------------------------------------------------------------------------

def test_mutex_concurrent_acquire_exactly_one_winner(tmp_path: Path):
    """review-pr1310.md MAJOR-2 required test: N racers, exactly one wins.
    All racers share this test process's own (live) PID -- correctness here
    is about os.open(O_CREAT|O_EXCL) atomicity, not about process liveness,
    so racing threads against a single shared PID is sufficient to prove the
    create-is-acquisition property. A check-then-write implementation (the
    pre-fix version) would let more than one thread land in the "class looks
    free" window and both return True."""
    locks = tmp_path / "locks"
    pid = os.getpid()
    n = 8
    barrier = threading.Barrier(n)
    results: list[tuple[str, int]] = []
    results_lock = threading.Lock()

    def worker(worker_id: int) -> None:
        barrier.wait()
        try:
            mutex.acquire(locks, "gpu-exclusive", f"node-{worker_id}", pid)
            outcome = "ok"
        except mutex.MutexBusy:
            outcome = "busy"
        with results_lock:
            results.append((outcome, worker_id))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [entry for entry in results if entry[0] == "ok"]
    assert len(winners) == 1
    assert len(results) == n


# --------------------------------------------------------------------------
# concurrency: atomic stale-reclaim (review-pr1310.md RE-REVIEW N1)
# --------------------------------------------------------------------------

def test_mutex_concurrent_reclaim_exactly_one_winner(tmp_path: Path):
    """review-pr1310.md RE-REVIEW N1 required test: N racers all observe the
    SAME dead-pid stale holder and race to reclaim it -- exactly one must
    end up the actual holder. The pre-fix implementation reclaimed via a
    bare `path.unlink()`, which deletes whatever currently sits at `path`
    regardless of content: a slower racer's unlink could delete a faster
    racer's freshly created VALID lock, after which both racers' acquire()
    calls had already returned True -- i.e. both believed they held
    gpu-exclusive simultaneously. The os.replace-to-tombstone reclaim must
    never allow that: acquire() returns True for at most one racer, and the
    lock file on disk always agrees with whichever one that was."""
    locks = tmp_path / "locks"
    dead_pid = _find_dead_pid()
    mutex.acquire(locks, "gpu-exclusive", "node-dead", dead_pid)

    n = 8
    barrier = threading.Barrier(n)
    results: list[tuple[str, int]] = []
    results_lock = threading.Lock()

    def worker(worker_id: int) -> None:
        barrier.wait()
        try:
            mutex.acquire(locks, "gpu-exclusive", f"node-{worker_id}", os.getpid())
            outcome = "ok"
        except mutex.MutexBusy:
            outcome = "busy"
        with results_lock:
            results.append((outcome, worker_id))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [entry for entry in results if entry[0] == "ok"]
    assert len(results) == n
    assert len(winners) == 1  # never more than one racer believes it holds the mutex

    holder = mutex.current_holder(locks, "gpu-exclusive")
    assert holder is not None
    assert holder["node_id"] == f"node-{winners[0][1]}"  # disk agrees with the sole winner


def test_mutex_reclaim_direct_call_on_live_lock_is_refused_and_leaves_it_intact(tmp_path: Path):
    """Reviewer's direct repro for RE-REVIEW N1: calling `_reclaim_stale`
    against a lock file that currently holds a LIVE record, passing a
    mismatched "expected dead" identity (as a straggler's stale read would
    be), must return False and leave the live lock file exactly intact --
    never a phantom win that silently deletes a live holder out from under
    it. Content-verification-free `os.replace(path, tombstone)` alone
    returns True here and destroys the live lock; this is exactly the gap
    the content check closes."""
    locks = tmp_path / "locks"
    pid = os.getpid()
    mutex.acquire(locks, "gpu-exclusive", "node-live", pid)
    path = mutex.lock_path(locks, "gpu-exclusive")
    live_before = mutex.current_holder(locks, "gpu-exclusive")

    dead_pid = _find_dead_pid()
    stale_identity_the_straggler_saw = {"owner_pid": dead_pid, "owner_creation_time": "some-other-time"}

    won = mutex._reclaim_stale(path, os.getpid(), stale_identity_the_straggler_saw)

    assert won is False
    live_after = mutex.current_holder(locks, "gpu-exclusive")
    assert live_after == live_before  # the live lock was restored/untouched, never lost


def test_mutex_straggler_reclaim_loses_to_concurrent_winner_and_live_lock_survives(tmp_path: Path):
    """review-pr1310.md RE-REVIEW N1 required test: the straggler
    interleaving the barrier-start race test above is structurally blind to.
    A reclaimer observes a dead holder (its "stale read"); before it acts on
    that read, a DIFFERENT racer fully reclaims and recreates a live lock at
    the same path; only THEN does the straggler fire its reclaim, still
    holding the identity it captured before the winner ever acted. That
    reclaim must LOSE (content no longer matches what it read), and the
    winner's live lock must remain exactly intact afterward -- never
    silently clobbered by a rename that only checked "does something exist
    at this path", not "is it still the thing I meant to remove"."""
    locks = tmp_path / "locks"
    dead_pid = _find_dead_pid()
    mutex.acquire(locks, "gpu-exclusive", "node-dead", dead_pid)
    path = mutex.lock_path(locks, "gpu-exclusive")

    # Straggler's "stale read" -- captured now, acted on later.
    straggler_observed = mutex.current_holder(locks, "gpu-exclusive")
    assert straggler_observed["node_id"] == "node-dead"

    # A different racer fully reclaims and creates a live lock in between,
    # before the straggler ever acts on what it read above.
    winner_pid = os.getpid()
    assert mutex.acquire(locks, "gpu-exclusive", "node-winner", winner_pid) is True
    live_before = mutex.current_holder(locks, "gpu-exclusive")
    assert live_before["node_id"] == "node-winner"

    # Straggler fires its reclaim now, using the STALE identity it captured
    # before the winner ever acted -- this must lose, not clobber the winner.
    won = mutex._reclaim_stale(path, os.getpid(), straggler_observed)
    assert won is False

    live_after = mutex.current_holder(locks, "gpu-exclusive")
    assert live_after == live_before  # the winner's live lock survived intact


def test_mutex_reclaim_restore_fails_safe_when_third_process_wins_the_gap(tmp_path: Path, monkeypatch):
    """Reviewer-driven deterministic repro for the RELOCATED N1 defect: the
    mismatch-RESTORE step is itself a second content-blind window if it
    uses a bare os.replace. Manually drives the exact interleaving the
    reviewer specified: V holds a live lock; a straggler S evicts it (its
    rename-out succeeds, moving V's live record to a tombstone -- this is
    the "S accidentally evicted a live lock" case _reclaim_stale detects via
    content mismatch); while S is deciding to restore what it evicted, a
    THIRD process U legitimately creates a fresh valid lock at the
    now-empty path. S's restore must then fail (O_EXCL sees `path`
    occupied) rather than silently overwrite U's fresh lock with V's
    evicted bytes -- U's lock must survive byte-for-byte, S must report a
    loss, never a phantom win, AND V's evicted record must survive intact
    as the orphaned tombstone (not be unconditionally unlinked on a lost
    restore -- that would destroy the only surviving copy of V just as
    permanently as the original defect, merely relocated to this file).

    The interleaving is driven deterministically (not via thread scheduling)
    by hooking `json.loads` -- the exact point in `_reclaim_stale` between
    "read back what the rename moved" and "decide whether to restore it" --
    to fire U's create exactly once, right after S observes V's evicted
    record and before S acts on that observation."""
    import json

    locks = tmp_path / "locks"
    path = mutex.lock_path(locks, "gpu-exclusive")

    # V: a live lock -- this is what straggler S is about to evict by
    # accident (S's own stale identity, below, deliberately does not match
    # V, forcing _reclaim_stale into the mismatch/restore branch).
    mutex.acquire(locks, "gpu-exclusive", "node-v", os.getpid())
    v_record = mutex.current_holder(locks, "gpu-exclusive")

    stale_identity_s_saw = {"owner_pid": 999999, "owner_creation_time": "some-other-time"}

    u_record = {
        "resource_class": "gpu-exclusive",
        "node_id": "node-u",
        "owner_pid": os.getpid(),
        "owner_creation_time": "u-creation-time",
        "owner_liveness_mode": "pid_only",
        "acquired_at": "2026-08-03T00:00:00+00:00",
    }

    original_loads = json.loads
    injected = {"done": False}

    def loads_with_u_interleaved(data, *args, **kwargs):
        result = original_loads(data, *args, **kwargs)
        # Fire exactly once: right after S reads back the record it just
        # evicted (V's), before S decides whether to restore it -- this is
        # the gap the reviewer's repro targets.
        if not injected["done"] and isinstance(result, dict) and result.get("node_id") == "node-v":
            injected["done"] = True
            created = mutex._create_exclusive_bytes(
                path, (json.dumps(u_record, sort_keys=True) + "\n").encode("utf-8")
            )
            assert created is True  # path must genuinely be empty at this point (S already renamed V out)
        return result

    monkeypatch.setattr(mutex.json, "loads", loads_with_u_interleaved)

    won = mutex._reclaim_stale(path, os.getpid(), stale_identity_s_saw)

    assert injected["done"]  # sanity: the interleaving actually fired
    assert won is False  # S must never report a win here
    survivor = mutex.current_holder(locks, "gpu-exclusive")
    assert survivor == u_record  # U's fresh lock survives byte-for-byte, never overwritten by V's evicted bytes

    # V's evicted record must survive as a named orphan tombstone -- a lost
    # restore must never unconditionally unlink the tombstone, since it is
    # the only surviving copy of what got evicted.
    orphans = list(locks.glob(f"{path.name}.stale.*"))
    assert len(orphans) == 1
    assert json.loads(orphans[0].read_text(encoding="utf-8")) == v_record


# --------------------------------------------------------------------------
# newline-guard against crash-torn append welding (review-pr1310.md RE-REVIEW N2)
# --------------------------------------------------------------------------

def test_atomic_append_newline_guard_after_crash_torn_tail(tmp_path: Path):
    """review-pr1310.md RE-REVIEW N2 required test: a crash that tears the
    final line of a JSONL file (no trailing newline) must not get welded to
    the next append. Without the newline-guard, `open(path, "a")` lands the
    new row's bytes directly after the torn tail with no separator,
    producing one line that mixes the torn tail with the new row -- which
    read_jsonl can never recover (a torn line is only ever tolerated when it
    stays the LAST line; welding pushes real data into an unparseable middle
    line the moment anything is appended after it). With the guard, the new
    row always lands on its own independently-parseable line."""
    import json

    from loop_graph._atomic import atomic_append_jsonl

    path = tmp_path / "INDEX.jsonl"
    good_row = {"receipt_id": "r0", "node_id": "exec-0"}
    torn_tail = '{"receipt_id": "r1", "node_id": "exec-1", "path": "rec'  # deliberately truncated, no trailing newline
    path.write_text(json.dumps(good_row, sort_keys=True) + "\n" + torn_tail, encoding="utf-8")

    new_row = {"receipt_id": "r2", "node_id": "exec-2"}
    atomic_append_jsonl(path, new_row)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == json.dumps(good_row, sort_keys=True)
    assert lines[1] == torn_tail  # the torn tail stays isolated, never welded
    assert json.loads(lines[2]) == new_row  # the new row parses on its own


def test_atomic_append_no_spurious_newline_when_prior_write_well_formed(tmp_path: Path):
    """The newline-guard must be a no-op when the file already ends cleanly
    -- it should never insert a blank line between two well-formed rows."""
    import json

    from loop_graph._atomic import atomic_append_jsonl

    path = tmp_path / "INDEX.jsonl"
    atomic_append_jsonl(path, {"receipt_id": "r0", "node_id": "exec-0"})
    atomic_append_jsonl(path, {"receipt_id": "r1", "node_id": "exec-1"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(line.strip() for line in lines)  # no blank line inserted


# --------------------------------------------------------------------------
# Windows lock-poll errno narrowing (review-pr1310.md RE-REVIEW N3)
# --------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt-specific errno narrowing")
def test_windows_exclusive_lock_propagates_non_contention_oserror(tmp_path: Path, monkeypatch):
    """review-pr1310.md RE-REVIEW N3 required test: ExclusiveLock's win32
    poll loop must retry ONLY on the lock-contention errno (EACCES) that
    msvcrt.locking raises when the region is already held. Any other OSError
    (a real fault) must propagate immediately instead of spinning forever --
    the pre-fix `except OSError: time.sleep(...)` caught everything and
    would hang on a genuine error."""
    import errno
    import msvcrt

    from loop_graph._atomic import ExclusiveLock

    def fake_locking(fd, mode, nbytes):
        raise OSError(errno.EINVAL, "simulated non-contention error")

    monkeypatch.setattr(msvcrt, "locking", fake_locking)

    lock = ExclusiveLock(tmp_path / "sidecar.lock")
    with pytest.raises(OSError) as excinfo:
        lock.__enter__()
    assert excinfo.value.errno == errno.EINVAL


# --------------------------------------------------------------------------
# lifecycle.create under the per-node lock (review-pr1310.md RE-REVIEW N4)
# --------------------------------------------------------------------------

def test_lifecycle_concurrent_create_exactly_one_writer_and_rest_idempotent(tmp_path: Path):
    """review-pr1310.md RE-REVIEW N4 required test: create() is now wrapped
    in the same per-node ExclusiveLock as claim/start/close, so N engines
    racing to create the same node_id all converge on one record instead of
    racing read-check-write independently."""
    store = tmp_path / "nodes"
    node_id = "exec-create-race"

    n = 8
    barrier = threading.Barrier(n)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(worker_id: int) -> None:
        node = make_execution_node(node_id=node_id, owner=f"agent-{worker_id}")
        barrier.wait()
        record = lifecycle.create(store, node)
        with results_lock:
            results.append(record)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == n
    owners = {record["owner"] for record in results}
    assert len(owners) == 1  # every racer converged on the same first-writer's record

    final = lifecycle.load_node(store, node_id)
    assert final["owner"] in owners


# --------------------------------------------------------------------------
# concurrency: atomic lifecycle claim (MEDIUM-3)
# --------------------------------------------------------------------------

def test_lifecycle_concurrent_claim_exactly_one_winner(tmp_path: Path):
    """review-pr1310.md MEDIUM-3 required test: N engines racing to claim the
    same PENDING node -- exactly one must win; the rest must get
    ALREADY_CLAIMED, never silently overwrite each other's ownership."""
    store = tmp_path / "nodes"
    node_id = "exec-race"
    # owner=None: make_execution_node()'s default "owner" is the schema's
    # declared-assignee field (any agent-name string), which lifecycle.claim
    # also reads as the current claimant -- a non-None default would make
    # every racer see the node as already claimed before the race even
    # starts.
    lifecycle.create(store, make_execution_node(node_id=node_id, owner=None))

    n = 8
    barrier = threading.Barrier(n)
    results: list[tuple[str, int]] = []
    results_lock = threading.Lock()

    def worker(worker_id: int) -> None:
        barrier.wait()
        try:
            lifecycle.claim(store, node_id, owner=f"agent-{worker_id}")
            outcome = "ok"
        except lifecycle.LifecycleError as exc:
            outcome = exc.code
        with results_lock:
            results.append((outcome, worker_id))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [entry for entry in results if entry[0] == "ok"]
    losers = [entry for entry in results if entry[0] == "ALREADY_CLAIMED"]
    assert len(winners) == 1
    assert len(losers) == n - 1

    final = lifecycle.load_node(store, node_id)
    winner_owner = f"agent-{winners[0][1]}"
    assert final["owner"] == winner_owner


# --------------------------------------------------------------------------
# PID-reuse-safe liveness (MEDIUM-2)
# --------------------------------------------------------------------------

def test_procid_identity_pid_only_mode_when_creation_time_unavailable():
    identity = {"pid": os.getpid(), "creation_time": None, "mode": procid.MODE_PID_ONLY}
    assert procid.is_same_process_alive(identity) is True


def test_procid_identity_detects_pid_reuse_via_creation_time_mismatch():
    """Simulates PID reuse without needing to actually exhaust and recycle a
    PID: a live PID whose recorded creation_time does not match its CURRENT
    creation_time must read as a different process, not the original
    holder -- this is exactly what protects the mutex/stale-scan from a
    reused PID silently reading as still-alive."""
    pid = os.getpid()
    real_creation_time = procid.creation_time(pid)
    if real_creation_time is None:
        pytest.skip("creation_time is unavailable on this platform")

    forged_identity = {
        "pid": pid,
        "creation_time": real_creation_time - 10_000,  # far outside tolerance
        "mode": procid.MODE_PID_AND_CREATION_TIME,
    }
    assert procid.is_same_process_alive(forged_identity) is False

    genuine_identity = {
        "pid": pid,
        "creation_time": real_creation_time,
        "mode": procid.MODE_PID_AND_CREATION_TIME,
    }
    assert procid.is_same_process_alive(genuine_identity) is True


def test_procid_dead_pid_is_not_alive_regardless_of_mode():
    dead_pid = _find_dead_pid()
    identity = {"pid": dead_pid, "creation_time": None, "mode": procid.MODE_PID_ONLY}
    assert procid.is_same_process_alive(identity) is False


def test_start_records_liveness_mode_in_lock(tmp_path: Path):
    store = tmp_path / "nodes"
    node_id = "exec-identity"
    lifecycle.create(store, make_execution_node(node_id=node_id))

    started = lifecycle.start(store, node_id, owner_pid=os.getpid())
    assert started["lock"]["owner_liveness_mode"] in (procid.MODE_PID_AND_CREATION_TIME, procid.MODE_PID_ONLY)
    if started["lock"]["owner_liveness_mode"] == procid.MODE_PID_AND_CREATION_TIME:
        assert started["lock"]["owner_creation_time"] is not None
