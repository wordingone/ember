#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hermetic tests for cockpit_watchdog.py (#362).

Red-first (TDD): every case is faked -- lease file, renderer heartbeat,
process absence, VRAM values -- via dependency injection. No live cockpit
dependency: the real ctypes/nvidia-smi/psutil backends are never invoked
by these tests, only the injected fakes.

Covers the composed liveness predicate over legs 1 (window), 2 (process),
3 (renderer heartbeat), and 4 (residency/lease).
"""

import json
import ntpath
import os
import posixpath
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "src", "ember", "governance", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import pytest

from cockpit_watchdog import (
    WindowInfo,
    TabInfo,
    WatchdogConfig,
    check_window_leg,
    check_process_leg,
    check_renderer_heartbeat_leg,
    check_residency_leg,
    classify,
    read_gpu_lease,
    append_jsonl,
    run_cycle,
    _default_renderer_heartbeat_path,
    _ember_config_home_dir,
    _repo_state_key,
    _resolve_ember_state_root,
)


# ---------------------------------------------------------------------------
# Leg 3 -- renderer heartbeat (#413)
# ---------------------------------------------------------------------------

def test_renderer_heartbeat_leg_is_fresh_and_pid_bound():
    leg = check_renderer_heartbeat_leg(
        "ignored.json",
        {"present": True, "pid": 222},
        max_age_s=5.0,
        now_epoch_s=100.0,
        heartbeat_reader=lambda _path: {
            "ts": "1970-01-01T00:01:38Z", "pid": 222, "version": "test"
        },
    )
    assert leg["fresh"] is True
    assert leg["age_s"] == 2.0
    assert leg["reason"] == "fresh"


def test_renderer_heartbeat_leg_flags_stale_age():
    leg = check_renderer_heartbeat_leg(
        "ignored.json",
        {"present": True, "pid": 222},
        max_age_s=5.0,
        now_epoch_s=100.0,
        heartbeat_reader=lambda _path: {
            "ts": "1970-01-01T00:01:30Z", "pid": 222, "version": "test"
        },
    )
    assert leg["fresh"] is False
    assert leg["reason"] == "stale"


def test_renderer_heartbeat_leg_flags_missing_or_malformed_rows():
    missing = check_renderer_heartbeat_leg(
        "ignored.json",
        {"present": True, "pid": 222},
        max_age_s=5.0,
        now_epoch_s=100.0,
        heartbeat_reader=lambda _path: None,
    )
    malformed = check_renderer_heartbeat_leg(
        "ignored.json",
        {"present": True, "pid": 222},
        max_age_s=5.0,
        now_epoch_s=100.0,
        heartbeat_reader=lambda _path: {"ts": "bad", "pid": "222"},
    )
    assert missing["fresh"] is False
    assert missing["reason"] == "missing-or-invalid"
    assert malformed["fresh"] is False
    assert malformed["reason"] == "missing-or-invalid"


def test_renderer_heartbeat_leg_flags_pid_mismatch():
    leg = check_renderer_heartbeat_leg(
        "ignored.json",
        {"present": True, "pid": 222},
        max_age_s=5.0,
        now_epoch_s=100.0,
        heartbeat_reader=lambda _path: {
            "ts": "1970-01-01T00:01:39Z", "pid": 999, "version": "test"
        },
    )
    assert leg["fresh"] is False
    assert leg["reason"] == "pid-mismatch"


def test_renderer_heartbeat_leg_reads_real_file_and_rejects_unknown_keys():
    with tempfile.TemporaryDirectory() as tmp:
        heartbeat = Path(tmp, "cockpit-heartbeat.json")
        heartbeat.write_text(
            json.dumps({
                "ts": "1970-01-01T00:01:39Z",
                "pid": 222,
                "version": "test",
            }),
            encoding="utf-8",
        )
        fresh = check_renderer_heartbeat_leg(
            str(heartbeat),
            {"present": True, "pid": 222},
            max_age_s=5.0,
            now_epoch_s=100.0,
        )
        assert fresh["fresh"] is True

        heartbeat.write_text(
            json.dumps({
                "ts": "1970-01-01T00:01:39Z",
                "pid": 222,
                "version": "test",
                "untrusted": True,
            }),
            encoding="utf-8",
        )
        invalid = check_renderer_heartbeat_leg(
            str(heartbeat),
            {"present": True, "pid": 222},
            max_age_s=5.0,
            now_epoch_s=100.0,
        )
        assert invalid["fresh"] is False
        assert invalid["reason"] == "missing-or-invalid"


def test_renderer_heartbeat_leg_rejects_future_timestamp_and_nonfinite_age_limit():
    future = check_renderer_heartbeat_leg(
        "ignored.json",
        {"present": True, "pid": 222},
        max_age_s=5.0,
        now_epoch_s=100.0,
        heartbeat_reader=lambda _path: {
            "ts": "1970-01-01T00:01:41Z", "pid": 222, "version": "test"
        },
    )
    assert future["fresh"] is False
    assert future["reason"] == "future-timestamp"

    try:
        check_renderer_heartbeat_leg(
            "ignored.json",
            {"present": True, "pid": 222},
            max_age_s=float("nan"),
            now_epoch_s=100.0,
            heartbeat_reader=lambda _path: None,
        )
    except ValueError as exc:
        assert "finite and positive" in str(exc)
    else:
        raise AssertionError("NaN heartbeat age limit must fail closed")


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
# Leg 1 (v1.1) -- window via UIA tab enumeration (wt.exe tabs)
# ---------------------------------------------------------------------------

def test_window_leg_present_when_title_found_in_wt_tabs():
    """v1.1: cockpit inside Windows Terminal is detected via UIA TabItem enumeration."""
    fake_tabs = [TabInfo(title="ember-resident", hwnd=555, pid=666),
                  TabInfo(title="other tab", hwnd=555, pid=666)]
    leg = check_window_leg("ember-resident",
                          window_lister=lambda: [],  # no top-level windows
                          tab_lister=lambda: fake_tabs)
    assert leg["present"] is True
    assert leg["hwnd"] == 555
    assert leg["pid_from_window"] == 666
    assert leg["found_in"] == "wt-tab"


def test_window_leg_present_when_title_found_in_toplevel_window():
    """Fallback: cockpit as a standalone top-level window (non-wt case)."""
    fake_windows = [WindowInfo(hwnd=111, title="ember-resident", pid=222)]
    leg = check_window_leg("ember-resident",
                          window_lister=lambda: fake_windows,
                          tab_lister=lambda: [])  # no wt tabs
    assert leg["present"] is True
    assert leg["hwnd"] == 111
    assert leg["pid_from_window"] == 222
    assert leg["found_in"] == "toplevel-window"


def test_window_leg_prefers_wt_tab_over_toplevel_window():
    """When title exists in both wt tabs and top-level windows, tab wins
    (the wt case is primary under modern Terminal usage patterns)."""
    fake_tabs = [TabInfo(title="ember-resident", hwnd=555, pid=666)]
    fake_windows = [WindowInfo(hwnd=111, title="ember-resident", pid=222),
                   WindowInfo(hwnd=333, title="other", pid=444)]
    leg = check_window_leg("ember-resident",
                          window_lister=lambda: fake_windows,
                          tab_lister=lambda: fake_tabs)
    assert leg["present"] is True
    assert leg["hwnd"] == 555  # wt hwnd, not the top-level window hwnd
    assert leg["pid_from_window"] == 666  # wt pid
    assert leg["found_in"] == "wt-tab"


def test_window_leg_absent_when_not_in_tabs_or_windows():
    """Title not found in either wt tabs or top-level windows."""
    fake_tabs = [TabInfo(title="other tab", hwnd=555, pid=666)]
    fake_windows = [WindowInfo(hwnd=333, title="unrelated window", pid=444)]
    leg = check_window_leg("ember-resident",
                          window_lister=lambda: fake_windows,
                          tab_lister=lambda: fake_tabs)
    assert leg["present"] is False
    assert leg["hwnd"] is None
    assert leg["found_in"] is None


# ---------------------------------------------------------------------------
# Leg 2 -- backing process (fake process lookup, no real psutil/GetWindow call)
# ---------------------------------------------------------------------------

def test_process_leg_present_when_pid_matches_expected_name():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222, "found_in": "toplevel-window"}
    leg = check_process_leg(window_leg, "ember.exe",
                             process_lookup=lambda pid: "ember.exe" if pid == 222 else None)
    assert leg["present"] is True
    assert leg["pid"] == 222


def test_process_leg_absent_when_pid_dead():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222, "found_in": "toplevel-window"}
    leg = check_process_leg(window_leg, "ember.exe", process_lookup=lambda pid: None)
    assert leg["present"] is False


def test_process_leg_absent_when_name_mismatch():
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222, "found_in": "toplevel-window"}
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
    window_leg = {"present": True, "hwnd": 111, "pid_from_window": 222, "found_in": "toplevel-window"}
    leg = check_process_leg(window_leg, "ember.exe", process_lookup=lambda pid: "ember.exe")
    assert leg["present"] is True
    assert leg["parented"] is True


def test_process_leg_wt_tab_case_skips_pid_validation():
    """v1.1: when cockpit is found in a wt tab, the pid is wt.exe's process,
    not the expected ember.exe process. Skip the pid-parented check and verify
    the backing process exists via independent scan instead."""
    # Window found in a wt tab (found_in="wt-tab"), with wt's pid
    window_leg = {
        "present": True,
        "hwnd": 555,  # The wt window HWND
        "pid_from_window": 24280,  # This is wt.exe's PID, not ember.exe
        "found_in": "wt-tab",
    }
    # The process lookup would show pid 24280 is wt.exe, not ember.exe
    leg = check_process_leg(
        window_leg, "ember.exe",
        process_lookup=lambda pid: "wt.exe" if pid == 24280 else None,
        process_finder=lambda name: 999 if name == "ember.exe" else None,
    )
    # The process leg should report success because we found ember.exe via scan,
    # not because we validated the wt.exe process
    assert leg["present"] is True
    assert leg["pid"] == 999  # The found ember.exe PID
    assert leg["parented"] is False
    assert leg["wt_tab_case"] is True


def test_process_leg_wt_tab_case_absent_when_ember_not_running():
    """v1.1: wt tab case, but the ember process isn't running."""
    window_leg = {
        "present": True,
        "hwnd": 555,
        "pid_from_window": 24280,
        "found_in": "wt-tab",
    }
    leg = check_process_leg(
        window_leg, "ember.exe",
        process_lookup=lambda pid: "wt.exe" if pid == 24280 else None,
        process_finder=lambda name: None,  # ember not running
    )
    assert leg["present"] is False
    assert leg["wt_tab_case"] is True


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
            tab_lister=lambda: [],
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
            tab_lister=lambda: [],
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
            tab_lister=lambda: [],
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
            tab_lister=lambda: [],
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
            tab_lister=lambda: [],
            process_lookup=lambda pid: None,
            process_finder=lambda name: None,  # cockpit deliberately down for the lease
            lease_reader=lambda path: lease,
            vram_query=lambda gpu_index: 50.0,
            capture_fn=lambda hwnd, out_path: (_ for _ in ()).throw(
                AssertionError("capture must not be called on lease-down-healthy")),
        )
        assert receipt["state"] == "lease-down-healthy"
        assert receipt["capture_path"] is None


def test_run_cycle_flags_pane_without_process_loudly():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "watchdog-heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
            renderer_heartbeat_path=os.path.join(tmp, "cockpit-heartbeat.json"),
        )
        receipt = run_cycle(
            cfg,
            window_lister=lambda: [WindowInfo(hwnd=111, title="ember-resident", pid=222)],
            tab_lister=lambda: [],
            process_lookup=lambda _pid: None,
            lease_reader=lambda _path: None,
            vram_query=lambda _gpu: 0.0,
            capture_fn=lambda _hwnd, out_path: out_path,
            renderer_heartbeat_reader=lambda _path: None,
            now_epoch_s=lambda: 100.0,
        )
        assert receipt["state"] == "corpse-or-error-pane"
        assert receipt["findings"] == ["PANE-WITHOUT-PROCESS"]
        assert receipt["renderer_heartbeat"]["reason"] == "process-absent"


def test_run_cycle_flags_stale_renderer_heartbeat_loudly():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = WatchdogConfig(
            expected_title="ember-resident",
            expected_process_name="ember.exe",
            lease_path=os.path.join(tmp, "gpu-lease.json"),
            receipt_path=os.path.join(tmp, "receipts.jsonl"),
            heartbeat_path=os.path.join(tmp, "watchdog-heartbeat.jsonl"),
            capture_dir=os.path.join(tmp, "captures"),
            renderer_heartbeat_path=os.path.join(tmp, "cockpit-heartbeat.json"),
            renderer_heartbeat_max_age_s=5.0,
        )
        receipt = run_cycle(
            cfg,
            window_lister=lambda: [WindowInfo(hwnd=111, title="ember-resident", pid=222)],
            tab_lister=lambda: [],
            process_lookup=lambda _pid: "ember.exe",
            lease_reader=lambda _path: None,
            vram_query=lambda _gpu: 8000.0,
            capture_fn=lambda _hwnd, out_path: out_path,
            renderer_heartbeat_reader=lambda _path: {
                "ts": "1970-01-01T00:01:30Z", "pid": 222, "version": "test"
            },
            now_epoch_s=lambda: 100.0,
        )
        assert receipt["state"] == "heartbeat-stale"
        assert receipt["findings"] == ["HEARTBEAT-STALE"]
        assert receipt["renderer_heartbeat"]["age_s"] == 10.0


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


# ---------------------------------------------------------------------------
# #413/#1330 review round 2 -- the renderer-heartbeat-path default is a THIRD
# resolution-point consumer, in lockstep with tools/ember-cli/src/utils/ember-state-root.ts
# (emberStateRoot/repoStateKey) and Get-EmberStateRoot/Get-EmberStateRootKey in
# the preparation-only cockpit helper. KEY_PARITY_VECTORS below is the SAME set already shared by
# ember-state-root.test.ts and tests/domain-governance/test_ember_root_launcher.py -- if this port drifts from
# either, this suite goes red.
# ---------------------------------------------------------------------------

#: [repo root, expected key] -- mirrored verbatim from KEY_PARITY_VECTORS in
#: tools/ember-cli/src/utils/ember-state-root.test.ts and tests/domain-governance/test_ember_root_launcher.py.
KEY_PARITY_VECTORS = [
    (r"C:\fixture\ember", "c-fixture-ember"),
    ("C:\\Fixture\\Ember\\", "c-fixture-ember"),
    (r"C:\fixture\ember repo", "c-fixture-ember-repo"),
    (r"C:\fixture\ember-wt\wt-1330", "c-fixture-ember-wt-wt-1330"),
]


@pytest.fixture
def clean_state_root_env(monkeypatch):
    """Isolates EMBER_STATE_ROOT/EMBER_HOME for each test in this section -- these are
    real process-wide env vars the rest of the suite (and a real cockpit session) may also
    read, so tests here must never leak into or out of that state."""
    monkeypatch.delenv("EMBER_STATE_ROOT", raising=False)
    monkeypatch.delenv("EMBER_HOME", raising=False)
    return monkeypatch


def test_repo_state_key_matches_the_typescript_and_powershell_resolution_points(clean_state_root_env):
    for root, expected_key in KEY_PARITY_VECTORS:
        assert _repo_state_key(root) == expected_key


def test_resolve_ember_state_root_honours_the_override_verbatim(clean_state_root_env):
    clean_state_root_env.setenv("EMBER_STATE_ROOT", r"C:\fixture\cockpit-state")
    assert _resolve_ember_state_root(r"C:\fixture\ember") == os.path.abspath(r"C:\fixture\cockpit-state")


def test_resolve_ember_state_root_defaults_to_ember_home_cockpit_state_key(clean_state_root_env):
    clean_state_root_env.setenv("EMBER_HOME", r"C:\fixture\home")
    resolved = _resolve_ember_state_root(r"C:\fixture\ember")
    assert resolved == os.path.join(r"C:\fixture\home", "cockpit-state", "c-fixture-ember")


def test_resolve_ember_state_root_defaults_to_home_dot_ember_when_ember_home_unset(clean_state_root_env, tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    resolved = _resolve_ember_state_root(r"C:\fixture\ember", platform="posix")
    assert resolved == posixpath.join(
        str(fake_home), ".ember", "cockpit-state", "c-fixture-ember"
    )


def test_resolve_ember_state_root_defaults_windows_receipts_and_cache_to_b(clean_state_root_env):
    assert _resolve_ember_state_root(r"C:\fixture\ember", platform="nt") == (
        ntpath.join("B:" + ntpath.sep, "M", "cockpit-state", "c-fixture-ember")
    )


def test_ember_config_home_dir_matches_env_detection_ts_contract(clean_state_root_env, tmp_path, monkeypatch):
    # EMBER_HOME verbatim when set.
    clean_state_root_env.setenv("EMBER_HOME", str(tmp_path))
    assert _ember_config_home_dir() == str(tmp_path)
    # Falls back to ~/.ember when unset, same as getEmberConfigHomeDir() in env-detection.ts.
    monkeypatch.delenv("EMBER_HOME", raising=False)
    fake_home = tmp_path / "home2"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert _ember_config_home_dir(platform="posix") == posixpath.join(
        str(fake_home), ".ember"
    )
    assert _ember_config_home_dir(platform="nt") == ntpath.join("B:" + ntpath.sep, "M")


def test_default_renderer_heartbeat_path_matches_the_writer_when_override_is_set(clean_state_root_env):
    clean_state_root_env.setenv("EMBER_STATE_ROOT", r"C:\fixture\cockpit-state")
    assert _default_renderer_heartbeat_path() == os.path.join(
        os.path.abspath(r"C:\fixture\cockpit-state"), "cockpit-heartbeat.json"
    )


def test_default_renderer_heartbeat_path_never_falls_back_to_the_legacy_in_tree_path(clean_state_root_env):
    # #413/#1330 review round 2 blocker: the old fallback silently read a permanently-empty
    # in-tree path when EMBER_STATE_ROOT was unset -- structural blindness dressed as
    # fail-loud. The default now must resolve through the SAME EMBER_HOME/repoStateKey arm
    # the writer uses, never a literal join under the checkout.
    default_path = _default_renderer_heartbeat_path()
    legacy_in_tree = os.path.abspath(os.path.join(
        SCRIPTS_DIR, "..", "tools", "ember-cli", "state", "cockpit-heartbeat.json"))
    assert default_path != legacy_in_tree
    assert "tools" not in Path(default_path).parts or "ember-cli" not in Path(default_path).parts
