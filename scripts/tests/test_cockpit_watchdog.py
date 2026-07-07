#!/usr/bin/env python3
"""Hermetic tests for cockpit_watchdog.py (#362).

Red-first (TDD): every case is faked -- lease file, ledger row, process
absence, VRAM values -- via dependency injection. No live cockpit
dependency: the real ctypes/nvidia-smi/psutil backends are never invoked
by these tests, only the injected fakes.

Covers the composed liveness predicate over legs 1 (window), 2 (process),
4 (residency/lease) -- leg 3 (renderer heartbeat) is deferred per the
issue-362 spec addendum and out of scope here.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, SCRIPTS_DIR)

from cockpit_watchdog import (
    WindowInfo,
    WatchdogConfig,
    check_window_leg,
    check_process_leg,
    check_residency_leg,
    classify,
    read_gpu_lease,
    append_jsonl,
    run_cycle,
)


# ---------------------------------------------------------------------------
# Leg 1 -- window (fake enumeration, no real EnumWindows call)
# ---------------------------------------------------------------------------

def test_window_leg_present_when_title_matches():
    fake_windows = [WindowInfo(hwnd=111, title="ember-resident", pid=222),
                    WindowInfo(hwnd=333, title="unrelated window", pid=444)]
    leg = check_window_leg("ember-resident", window_lister=lambda: fake_windows)
    assert leg["present"] is True
    assert leg["hwnd"] == 111
    assert leg["pid_from_window"] == 222


def test_window_leg_absent_when_no_title_matches():
    fake_windows = [WindowInfo(hwnd=333, title="unrelated window", pid=444)]
    leg = check_window_leg("ember-resident", window_lister=lambda: fake_windows)
    assert leg["present"] is False
    assert leg["hwnd"] is None
    assert leg["all_visible_titles"] == ["unrelated window"]


def test_window_leg_absent_when_enumeration_empty():
    leg = check_window_leg("ember-resident", window_lister=lambda: [])
    assert leg["present"] is False
    assert leg["all_visible_titles"] == []


# ---------------------------------------------------------------------------
# Leg 2 -- backing process (fake process lookup, no real psutil/GetWindow call)
# ---------------------------------------------------------------------------

def test_process_leg_present_when_pid_matches_expected_name():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222}
    leg = check_process_leg(window_leg, "ember.exe",
                             process_lookup=lambda pid: "ember.exe" if pid == 222 else None)
    assert leg["present"] is True
    assert leg["pid"] == 222


def test_process_leg_absent_when_pid_dead():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222}
    leg = check_process_leg(window_leg, "ember.exe", process_lookup=lambda pid: None)
    assert leg["present"] is False


def test_process_leg_absent_when_name_mismatch():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222}
    leg = check_process_leg(window_leg, "ember.exe",
                             process_lookup=lambda pid: "notepad.exe")
    assert leg["present"] is False


def test_process_leg_absent_when_no_window_and_no_process_found():
    # No window => falls back to an independent name scan (injected here so
    # the real psutil.process_iter backend is never touched by this test).
    window_leg = {"present": False, "hwnd": None, "pid_from_window": None}
    leg = check_process_leg(window_leg, "ember.exe",
                             process_lookup=lambda pid: "ember.exe",
                             process_finder=lambda name: None)
    assert leg["present"] is False
    assert leg["pid"] is None
    assert leg["parented"] is False


def test_process_leg_orphan_process_detected_via_independent_name_scan():
    # No window found, but the independent process-name scan finds a live
    # match -- this is exactly the 'orphan-process' case: window closed or
    # hidden while the backing process is still alive.
    window_leg = {"present": False, "hwnd": None, "pid_from_window": None}
    leg = check_process_leg(window_leg, "ember.exe",
                             process_lookup=lambda pid: "ember.exe",
                             process_finder=lambda name: 999 if name == "ember.exe" else None)
    assert leg["present"] is True
    assert leg["pid"] == 999
    assert leg["parented"] is False


def test_process_leg_parented_true_when_window_backs_it():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222}
    leg = check_process_leg(window_leg, "ember.exe", process_lookup=lambda pid: "ember.exe")
    assert leg["present"] is True
    assert leg["parented"] is True


# ---------------------------------------------------------------------------
# Leg 4 -- residency vs lease (fake lease file, fake VRAM query)
# ---------------------------------------------------------------------------

def test_read_gpu_lease_absent_file_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gpu-lease.json")
        assert not os.path.exists(path)
        assert read_gpu_lease(path) is None


def test_read_gpu_lease_present_file_parses():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gpu-lease.json")
        lease = {"holder": "w1b-lane", "purpose": "training-leg",
                  "since": "2026-07-07T00:00:00Z", "expected_end": None}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(lease, f)
        assert read_gpu_lease(path) == lease


def test_read_gpu_lease_corrupt_file_returns_none_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gpu-lease.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        assert read_gpu_lease(path) is None


def test_residency_consistent_inference_mode_tenant_present():
    # No lease => inference mode => VRAM tenant expected PRESENT
    leg = check_residency_leg(lease=None, vram_used_mb=8000.0, inference_floor_mb=512.0)
    assert leg["declared_mode"] == "inference"
    assert leg["consistent"] is True


def test_residency_inconsistent_inference_mode_tenant_absent():
    # No lease (inference expected) but VRAM is empty -- model unexpectedly unloaded
    leg = check_residency_leg(lease=None, vram_used_mb=50.0, inference_floor_mb=512.0)
    assert leg["declared_mode"] == "inference"
    assert leg["consistent"] is False


def test_residency_consistent_training_lease_tenant_absent():
    lease = {"holder": "w1b-lane", "purpose": "training-leg"}
    leg = check_residency_leg(lease=lease, vram_used_mb=50.0, inference_floor_mb=512.0)
    assert leg["declared_mode"] == "training"
    assert leg["consistent"] is True


def test_residency_inconsistent_training_lease_tenant_present():
    # Training lease active but cockpit's VRAM tenant is STILL present -- double-booked GPU
    lease = {"holder": "w1b-lane", "purpose": "training-leg"}
    leg = check_residency_leg(lease=lease, vram_used_mb=9000.0, inference_floor_mb=512.0)
    assert leg["declared_mode"] == "training"
    assert leg["consistent"] is False


def test_residency_unknown_when_vram_query_fails():
    leg = check_residency_leg(lease=None, vram_used_mb=None, inference_floor_mb=512.0)
    assert leg["consistent"] is None
    assert leg["vram_used_mb"] is None


# ---------------------------------------------------------------------------
# classify() -- composed predicate over the three legs
# ---------------------------------------------------------------------------

def _win(present, hwnd=None):
    return {"present": present, "hwnd": hwnd, "pid_from_window": 222 if present else None,
            "all_visible_titles": []}


def _proc(present, pid=222):
    return {"present": present, "pid": pid if present else None}


def _res(consistent, declared_mode="inference"):
    return {"consistent": consistent, "declared_mode": declared_mode}


def test_classify_healthy():
    state = classify(_win(True, hwnd=111), _proc(True), _res(True, "inference"))
    assert state == "healthy"


def test_classify_lease_down_healthy():
    # Training lease active, cockpit deliberately down (no window, no process) -- NOT a failure
    state = classify(_win(False), _proc(False), _res(True, "training"))
    assert state == "lease-down-healthy"


def test_classify_missing_no_lease():
    # No window, no process, no lease -- classic corpse/gone
    state = classify(_win(False), _proc(False), _res(True, "inference"))
    assert state == "missing"


def test_classify_corpse_or_error_pane():
    # A window occupies the ledgered slot but nothing backs it -- stray/corpse pane
    state = classify(_win(True, hwnd=111), _proc(False), _res(None, "inference"))
    assert state == "corpse-or-error-pane"


def test_classify_orphan_process():
    # Process alive+matching but no window found for it
    state = classify(_win(False), _proc(True), _res(None, "inference"))
    assert state == "orphan-process"


def test_classify_vram_mismatch():
    # Window+process both present but residency leg disagrees with declared mode
    state = classify(_win(True, hwnd=111), _proc(True), _res(False, "training"))
    assert state == "vram-mismatch"


# ---------------------------------------------------------------------------
# append_jsonl -- receipt/heartbeat writer
# ---------------------------------------------------------------------------

def test_append_jsonl_creates_dirs_and_appends():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "nested", "receipts.jsonl")
        append_jsonl(path, {"a": 1})
        append_jsonl(path, {"a": 2})
        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"a": 2}


# ---------------------------------------------------------------------------
# run_cycle -- full wiring, all backends faked, REPORT-ONLY (no kill/close/restore)
# ---------------------------------------------------------------------------

def test_run_cycle_healthy_writes_receipt_and_heartbeat_no_capture():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
        )
        captured = []

        def fake_capture(hwnd, out_path):
            captured.append((hwnd, out_path))
            return out_path

        receipt = run_cycle(
            cfg,
            window_lister=lambda: [WindowInfo(hwnd=111, title="ember-resident", pid=222)],
            process_lookup=lambda pid: "ember.exe",
            lease_reader=lambda path: None,
            vram_query=lambda gpu_index: 8000.0,
            capture_fn=fake_capture,
        )

        assert receipt["state"] == "healthy"
        assert receipt["policy"] == "report-only"
        assert receipt["capture_path"] is None
        assert captured == []  # no capture on healthy state

        receipt_lines = Path(cfg.receipt_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(receipt_lines) == 1
        heartbeat_lines = Path(cfg.heartbeat_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(heartbeat_lines) == 1
        hb = json.loads(heartbeat_lines[0])
        assert hb["state"] == "healthy"
        assert "ts" in hb


def test_run_cycle_missing_state_no_capture_no_hwnd():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
        )
        captured = []

        receipt = run_cycle(
            cfg,
            window_lister=lambda: [],
            process_lookup=lambda pid: None,
            process_finder=lambda name: None,  # nothing running either -- true corpse/gone
            lease_reader=lambda path: None,
            vram_query=lambda gpu_index: 0.0,
            capture_fn=lambda hwnd, out_path: captured.append((hwnd, out_path)) or out_path,
        )
        assert receipt["state"] == "missing"
        assert receipt["capture_path"] is None
        assert captured == []  # nothing to capture: no hwnd


def test_run_cycle_orphan_process_no_capture_no_hwnd():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
        )
        captured = []

        receipt = run_cycle(
            cfg,
            window_lister=lambda: [],  # window closed/hidden
            process_lookup=lambda pid: None,
            process_finder=lambda name: 999,  # but the process is still alive
            lease_reader=lambda path: None,
            vram_query=lambda gpu_index: 8000.0,
            capture_fn=lambda hwnd, out_path: captured.append((hwnd, out_path)) or out_path,
        )
        assert receipt["state"] == "orphan-process"
        assert receipt["process"]["pid"] == 999
        assert receipt["capture_path"] is None
        assert captured == []  # nothing visual to capture: no window


def test_run_cycle_corpse_captures_the_stray_window():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
        )
        captured = []

        def fake_capture(hwnd, out_path):
            captured.append((hwnd, out_path))
            return out_path

        receipt = run_cycle(
            cfg,
            window_lister=lambda: [WindowInfo(hwnd=111, title="ember-resident", pid=222)],
            process_lookup=lambda pid: None,  # process dead -- window is a corpse pane
            lease_reader=lambda path: None,
            vram_query=lambda gpu_index: 0.0,
            capture_fn=fake_capture,
        )
        assert receipt["state"] == "corpse-or-error-pane"
        assert receipt["capture_path"] is not None
        assert len(captured) == 1
        assert captured[0][0] == 111  # captured the ledgered hwnd


def test_run_cycle_lease_down_healthy_no_capture():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
        )
        lease = {"holder": "w1b-lane", "purpose": "training-leg",
                 "since": "2026-07-07T00:00:00Z", "expected_end": None}

        receipt = run_cycle(
            cfg,
            window_lister=lambda: [],
            process_lookup=lambda pid: None,
            process_finder=lambda name: None,  # cockpit deliberately down for the lease
            lease_reader=lambda path: lease,
            vram_query=lambda gpu_index: 50.0,
            capture_fn=lambda hwnd, out_path: (_ for _ in ()).throw(
                AssertionError("capture must not be called on lease-down-healthy")),
        )
        assert receipt["state"] == "lease-down-healthy"
        assert receipt["capture_path"] is None


def test_run_cycle_never_kills_or_closes_or_restores():
    """REPORT-ONLY v1 policy: no actual kill/close/relaunch CALL may exist in
    the module. Walks the AST (not raw text) so prose in docstrings/comments
    explaining what's deferred to v2 ("no auto-restore in v1...") can never
    produce a false positive -- only real Call nodes are inspected."""
    import ast
    import inspect
    import cockpit_watchdog as mod

    tree = ast.parse(inspect.getsource(mod))
    banned_names = {
        "TerminateProcess", "PostMessage", "SendMessage", "kill",
        "CreateProcess", "WinExec", "ShellExecute",
    }
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if name in banned_names:
                hits.append(name)
    assert hits == [], f"v1 must be report-only; found banned call(s): {hits}"
