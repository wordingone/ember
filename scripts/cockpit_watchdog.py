#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cockpit_watchdog.py -- standing liveness watchdog for the ember cockpit (#362).

Composed liveness predicate over four independent legs:

  1. window    -- a visible tab with the ledgered title exists in Windows Terminal
                  (or a top-level non-wt window with the ledgered title).
                  v1.1: UIA TabItem enumeration over WindowsTerminal.exe's HWNDs,
                  falling back to exact-title matching for non-wt windows.
  2. process   -- the window's owning process (GetWindowThreadProcessId) is
                  alive and its image name matches the ledgered process name.
  3. heartbeat -- the cockpit's renderer heartbeat exists, is fresh, and its
                  pid matches the independently observed backing process.
                  Missing, malformed, future-dated, stale, or mismatched rows fail loud.
  4. residency -- VRAM tenant state is consistent with the declared mode read
                  from state/gpu-lease.json. Absent lease file = no lease =
                  inference mode = tenant expected PRESENT. A lease file
                  present = training mode = tenant expected ABSENT (the
                  cockpit is deliberately unloaded for the training leg).
                  The watchdog READS this file; it never writes it.

Policy (v1, frozen by the addendum): REPORT-ONLY. Every cycle classifies the
composed state and appends one receipt row (JSONL) plus one heartbeat row
(so a silently-dead watchdog is itself detectable). No kill, no window
close, no auto-restore -- that is v2, scoped to the unambiguous "missing"
case only, after the report path has receipts.

Issue #413 closes the old frozen-pixel gap: a pane with no process emits
PANE-WITHOUT-PROCESS and a non-fresh renderer pulse emits HEARTBEAT-STALE.

CLI:
  python cockpit_watchdog.py run --once --title <t> [--process <p>] [...]
  python cockpit_watchdog.py run --interval 180 --title <t> [...]
  python cockpit_watchdog.py selftest
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import ntpath
import os
import posixpath
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Live clock -- hand-written timestamps are banned everywhere in this repo.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Leg 1 -- window existence (UIA/enumeration tier)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int


def enumerate_visible_windows() -> list[WindowInfo]:
    """Real backend: EnumWindows + IsWindowVisible + GetWindowText(+Length) +
    GetWindowThreadProcessId, one pass. This is the UIA/enumeration tier --
    process listings CANNOT see wt.exe's sibling windows (single process,
    multiple top-level HWNDs)."""
    user32 = ctypes.windll.user32
    results: list[WindowInfo] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return 1
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return 1
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        results.append(WindowInfo(hwnd=int(hwnd), title=buf.value, pid=int(pid.value)))
        return 1

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return results


@dataclass(frozen=True)
class TabInfo:
    """Represents a Windows Terminal tab enumerated via UIA."""
    title: str
    hwnd: int  # the wt.exe window HWND that owns this tab
    pid: int   # the wt.exe process ID


def enumerate_wt_tabs() -> list[TabInfo]:
    """Real backend: enumerate TabItem descendants of WindowsTerminal.exe windows
    via UIA (AutomationElement tree traversal). Returns the title of each tab
    plus the HWND/PID of its parent wt.exe window.

    This handles the case where the cockpit is a tab inside Windows Terminal,
    not a top-level window itself. Absent UIAutomation or wt not running returns [].
    """
    try:
        import uiautomation as uia
    except ImportError:
        return []

    tabs: list[TabInfo] = []

    try:
        # Enumerate all visible top-level windows
        user32 = ctypes.windll.user32
        results: list[tuple[int, int]] = []  # (hwnd, pid)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return 1
            length = user32.GetWindowTextLengthW(hwnd)
            # Match wt window class; exact title is less reliable since it changes
            class_name_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name_buf, 256)
            class_name = class_name_buf.value
            if "CASCADIA" not in class_name and class_name != "WindowsTerminal":
                return 1  # Not a wt window
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            results.append((int(hwnd), int(pid.value)))
            return 1

        user32.EnumWindows(WNDENUMPROC(_cb), 0)

        # For each wt window, enumerate its TabItem children via UIA
        for hwnd, pid in results:
            try:
                # Get the AutomationElement for this window
                elem = uia.ControlFromHandle(hwnd)
                if not elem:
                    continue

                # Walk the tree looking for TabItem controls
                def walk_for_tabs(control, hwnd_val, pid_val):
                    nonlocal tabs
                    try:
                        if control.ControlType == uia.ControlType.TabItemControl:
                            # Extract the tab name (usually the Name property)
                            name = control.Name
                            if name:
                                tabs.append(TabInfo(title=name, hwnd=hwnd_val, pid=pid_val))
                    except Exception:
                        pass

                    # Recurse into children
                    try:
                        for child in control.GetChildren():
                            walk_for_tabs(child, hwnd_val, pid_val)
                    except Exception:
                        pass

                walk_for_tabs(elem, hwnd, pid)
            except Exception:
                pass
    except Exception:
        pass

    return tabs


def check_window_leg(
    expected_title: str,
    window_lister: Callable[[], "list[WindowInfo]"] = enumerate_visible_windows,
    tab_lister: Callable[[], "list[TabInfo]"] = enumerate_wt_tabs,
) -> dict[str, Any]:
    """Leg 1: does the expected_title exist as a visible window or as a tab in
    Windows Terminal?

    v1.1: First checks wt tabs via UIA enumeration; if not found, falls back
    to exact-title matching on top-level windows. This eliminates the false
    "orphan-process" alarm when the cockpit is inside a wt tab (the common case
    under Windows Terminal) vs a standalone window.
    """
    # First check: is the title present as a wt tab?
    tabs = tab_lister()
    tab_match = next((t for t in tabs if t.title == expected_title), None)
    if tab_match is not None:
        return {
            "leg": "window",
            "present": True,
            "hwnd": tab_match.hwnd,
            "pid_from_window": tab_match.pid,
            "all_visible_titles": [t.title for t in tabs],
            "found_in": "wt-tab",
        }

    # Fallback: check top-level windows (for non-wt cases, or wt windows that
    # update their title to match the active tab)
    windows = window_lister()
    match = next((w for w in windows if w.title == expected_title), None)
    if match is None:
        return {
            "leg": "window",
            "present": False,
            "hwnd": None,
            "pid_from_window": None,
            "all_visible_titles": [w.title for w in windows],
            "found_in": None,
        }

    # Check if this is actually a Windows Terminal window (class CASCADIA_*).
    # If so, treat it as a wt-tab case (skip parented pid validation).
    is_wt_window = _is_windows_terminal_window(match.hwnd)
    found_in = "wt-tab" if is_wt_window else "toplevel-window"

    return {
        "leg": "window",
        "present": True,
        "hwnd": match.hwnd,
        "pid_from_window": match.pid,
        "all_visible_titles": [w.title for w in windows if w is not match],
        "found_in": found_in,
    }


def _is_windows_terminal_window(hwnd: int) -> bool:
    """Check if an HWND belongs to a Windows Terminal window."""
    try:
        user32 = ctypes.windll.user32
        class_name_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name_buf, 256)
        class_name = class_name_buf.value
        return "CASCADIA" in class_name or class_name == "WindowsTerminal"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Leg 2 -- backing process
# ---------------------------------------------------------------------------

def _psutil_process_name(pid: int) -> Optional[str]:
    """Real backend: psutil.Process(pid).name(). Returns None if the pid is
    gone or unreadable (dead process, access denied, etc.)."""
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return None


def is_process_alive(
    pid: int,
    expected_name: str,
    process_lookup: Optional[Callable[[int], Optional[str]]] = None,
) -> bool:
    """Is pid alive and does its image name match expected_name (case-insensitive)?"""
    if process_lookup is None:
        process_lookup = _psutil_process_name
    name = process_lookup(pid)
    if name is None:
        return False
    return name.lower() == expected_name.lower()


def find_process_by_name(expected_name: str) -> Optional[int]:
    """Real backend: independent process-name scan (psutil.process_iter),
    used ONLY when leg 1 found no window -- this is what makes an
    'orphan-process' (process alive, no matching window) detectable at all.
    Returns the first matching pid, or None if none is running."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info.get("name")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name and name.lower() == expected_name.lower():
                return proc.info["pid"]
    except Exception:
        return None
    return None


def check_process_leg(
    window_leg: dict[str, Any],
    expected_process_name: str,
    process_lookup: Optional[Callable[[int], Optional[str]]] = None,
    process_finder: Optional[Callable[[str], Optional[int]]] = None,
) -> dict[str, Any]:
    """Leg 2: is the backing process alive and parented to the ledgered
    window?

    Special case (v1.1): if the window was found inside Windows Terminal (a
    wt-tab), the hwnd's process is wt.exe, not the expected process. In this
    case, skip the pid-parented check and instead verify the expected process
    exists via independent process scan -- finding the cockpit tab in wt
    already proves the window is present; we just need to verify the backing
    ember process is still alive.

    If leg 1 found a non-wt window, its pid is authoritative: check THAT pid
    is alive and named expected_process_name (parented).

    If leg 1 found no window, there is no pid to parent-check -- fall back
    to an independent process-name scan so a process-alive-but-window-gone
    case is still detectable as orphan-process.
    """
    pid = window_leg.get("pid_from_window")
    found_in = window_leg.get("found_in")

    # v1.1: if found in a wt tab, the pid is the wt.exe process, not our process.
    # Skip the parented check and verify the backing process exists.
    if pid is not None and found_in == "wt-tab":
        if process_finder is None:
            process_finder = find_process_by_name
        found_pid = process_finder(expected_process_name)
        return {"leg": "process", "present": found_pid is not None, "pid": found_pid,
                "parented": False, "wt_tab_case": True}

    # Top-level window case (non-wt): validate the pid matches our expected process
    if pid is not None:
        alive = is_process_alive(pid, expected_process_name, process_lookup)
        return {"leg": "process", "present": alive, "pid": pid, "parented": True}

    # No window found: independent process-name scan
    if process_finder is None:
        process_finder = find_process_by_name
    found_pid = process_finder(expected_process_name)
    return {"leg": "process", "present": found_pid is not None, "pid": found_pid,
            "parented": False}


# ---------------------------------------------------------------------------
# Leg 3 -- renderer heartbeat (#413; independent from watchdog heartbeat)
# ---------------------------------------------------------------------------

def read_renderer_heartbeat(path: str) -> Optional[dict[str, Any]]:
    """Read one strict cockpit renderer heartbeat snapshot.

    Returning None is deliberately fail-closed: missing, unreadable,
    malformed, unknown-key, or wrong-typed state can never count as fresh.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if not isinstance(value, dict):
        return None
    allowed = {"ts", "pid", "version", "telemetry"}
    if set(value) - allowed or not {"ts", "pid", "version"} <= set(value):
        return None
    if not isinstance(value["ts"], str):
        return None
    if isinstance(value["pid"], bool) or not isinstance(value["pid"], int) or value["pid"] <= 0:
        return None
    if not isinstance(value["version"], str) or not value["version"]:
        return None
    if "telemetry" in value and not isinstance(value["telemetry"], dict):
        return None
    return value


def _parse_heartbeat_ts(ts: str) -> Optional[float]:
    if not ts.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(ts[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.timestamp()


def check_renderer_heartbeat_leg(
    path: Optional[str],
    process_leg: dict[str, Any],
    *,
    max_age_s: float,
    now_epoch_s: Optional[float] = None,
    heartbeat_reader: Callable[[str], Optional[dict[str, Any]]] = read_renderer_heartbeat,
) -> dict[str, Any]:
    """Leg 3: bind a fresh renderer pulse to the independently observed PID."""
    if path is None:
        return {
            "leg": "renderer-heartbeat", "required": False, "fresh": None,
            "reason": "not-configured", "path": None,
        }
    if (
        isinstance(max_age_s, bool)
        or not isinstance(max_age_s, (int, float))
        or not math.isfinite(max_age_s)
        or max_age_s <= 0
    ):
        raise ValueError("renderer heartbeat max age must be finite and positive")
    if not process_leg.get("present"):
        return {
            "leg": "renderer-heartbeat", "required": True, "fresh": None,
            "reason": "process-absent", "path": path,
        }

    row = heartbeat_reader(path)
    heartbeat_epoch_s = None if row is None else _parse_heartbeat_ts(row.get("ts", ""))
    if row is None or heartbeat_epoch_s is None:
        return {
            "leg": "renderer-heartbeat", "required": True, "fresh": False,
            "reason": "missing-or-invalid", "path": path,
        }
    observed_pid = process_leg.get("pid")
    if row.get("pid") != observed_pid:
        return {
            "leg": "renderer-heartbeat", "required": True, "fresh": False,
            "reason": "pid-mismatch", "path": path, "heartbeat_pid": row.get("pid"),
            "observed_pid": observed_pid,
        }

    now_s = time.time() if now_epoch_s is None else now_epoch_s
    age_s = now_s - heartbeat_epoch_s
    fresh = 0 <= age_s <= max_age_s
    reason = "fresh" if fresh else ("future-timestamp" if age_s < 0 else "stale")
    return {
        "leg": "renderer-heartbeat", "required": True, "fresh": fresh,
        "reason": reason, "path": path, "age_s": age_s,
        "heartbeat_pid": row["pid"], "observed_pid": observed_pid,
        "max_age_s": float(max_age_s),
    }


# ---------------------------------------------------------------------------
# Leg 4 -- residency vs the gpu-lease.json convention (read-only)
# ---------------------------------------------------------------------------

def read_gpu_lease(path: str) -> Optional[dict[str, Any]]:
    """Read state/gpu-lease.json. Absent file = no lease = inference mode is
    the healthy default (per the issue-362 spec addendum). The watchdog
    reads this file; it NEVER writes it."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def query_vram_used_mb(gpu_index: int = 0) -> Optional[float]:
    """Real backend: nvidia-smi --query-gpu=memory.used. Returns None on any
    failure (no GPU, nvidia-smi missing, timeout) -- residency leg reports
    'consistent: None' (unknown) in that case rather than guessing."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", f"--id={gpu_index}",
             "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, timeout=10,
        )
        return float(out.strip().splitlines()[0])
    except Exception:
        return None


def check_residency_leg(
    lease: Optional[dict[str, Any]],
    vram_used_mb: Optional[float],
    inference_floor_mb: float = 512.0,
) -> dict[str, Any]:
    """Leg 4: is the observed VRAM tenant state consistent with the mode
    declared by the lease file?

      lease is None  => declared mode = inference => tenant expected PRESENT
      lease present  => declared mode = training  => tenant expected ABSENT
    """
    declared_mode = "training" if lease is not None else "inference"
    if vram_used_mb is None:
        return {
            "leg": "residency", "consistent": None, "declared_mode": declared_mode,
            "vram_used_mb": None, "lease": lease,
        }
    tenant_present = vram_used_mb >= inference_floor_mb
    consistent = tenant_present if declared_mode == "inference" else not tenant_present
    return {
        "leg": "residency", "consistent": consistent, "declared_mode": declared_mode,
        "vram_used_mb": vram_used_mb, "tenant_present": tenant_present, "lease": lease,
    }


# ---------------------------------------------------------------------------
# classify() -- compose the three legs into one classified state
# ---------------------------------------------------------------------------

def classify(window_leg: dict[str, Any], process_leg: dict[str, Any],
             residency_leg: dict[str, Any],
             renderer_heartbeat_leg: Optional[dict[str, Any]] = None) -> str:
    """Compose the four legs into one classified state.

    States (v1 vocabulary, matching the issue's "error pane vs hung vs
    missing" classification as closely as the available legs allow):

      healthy              -- window+process present, residency consistent
                               (or unknown), heartbeat fresh when configured.
      heartbeat-stale      -- window+process present, but the required
                               renderer heartbeat is not fresh/PID-bound.
      lease-down-healthy   -- training lease active, window+process both
                               absent (cockpit deliberately unloaded) --
                               NOT a failure.
      missing              -- window+process both absent, no lease active
                               -- classic corpse/gone.
      corpse-or-error-pane -- a window occupies the ledgered slot but no
                               matching process backs it (stray pane from a
                               failed launch, or a leftover error dialog).
      orphan-process       -- the backing process is alive and matches, but
                               no window was found for it (closed/hidden
                               while the process runs on).
      vram-mismatch        -- window+process both present but the residency
                               leg disagrees with the declared mode (model
                               unloaded unexpectedly, or double-booked GPU
                               during a training lease).
      ambiguous            -- defensive fallback; should be unreachable.
    """
    win_present = window_leg["present"]
    proc_present = process_leg["present"]
    residency_consistent = residency_leg["consistent"]
    declared_mode = residency_leg["declared_mode"]
    heartbeat_fresh = None if renderer_heartbeat_leg is None else renderer_heartbeat_leg["fresh"]

    if not win_present and not proc_present:
        return "lease-down-healthy" if declared_mode == "training" else "missing"

    if win_present and proc_present:
        if heartbeat_fresh is False:
            return "heartbeat-stale"
        return "vram-mismatch" if residency_consistent is False else "healthy"

    if win_present and not proc_present:
        return "corpse-or-error-pane"

    if proc_present and not win_present:
        return "orphan-process"

    return "ambiguous"


def liveness_findings(
    window_leg: dict[str, Any],
    process_leg: dict[str, Any],
    renderer_heartbeat_leg: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    if window_leg["present"] and not process_leg["present"]:
        findings.append("PANE-WITHOUT-PROCESS")
    if window_leg["present"] and process_leg["present"] and renderer_heartbeat_leg["fresh"] is False:
        findings.append("HEARTBEAT-STALE")
    return findings


# ---------------------------------------------------------------------------
# Receipt / heartbeat writer (JSONL, append + fsync -- matches
# heartbeat_runner.py's _append_chain convention)
# ---------------------------------------------------------------------------

def append_jsonl(path: str, record: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------------------
# Focus-safe window capture -- PrintWindow(PW_RENDERFULLCONTENT) only.
# NEVER calls SetForegroundWindow; NEVER falls back to foreground/full-screen
# capture (matches tools/ember-cli/scratchpad/safe-capture-window.ps1's rule).
# ---------------------------------------------------------------------------

PW_RENDERFULLCONTENT = 0x00000002


def capture_window_bitmap(hwnd: int, out_path: str) -> Optional[str]:
    """Capture hwnd's own pixels into out_path (24-bit BMP), focus-safe. This
    is the real backend; run_cycle() takes it as an injectable so tests never
    touch a live window."""
    if not hwnd:
        return None

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    hwnd_dc = user32.GetWindowDC(ctypes.c_void_p(hwnd))
    if not hwnd_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)

    ok = bool(user32.PrintWindow(ctypes.c_void_p(hwnd), mem_dc, PW_RENDERFULLCONTENT))
    written_path = None

    if ok:
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        row_size = ((width * 3 + 3) // 4) * 4
        image_size = row_size * height
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # negative = top-down DIB
        header.biPlanes = 1
        header.biBitCount = 24
        header.biCompression = 0
        header.biSizeImage = image_size

        buf = ctypes.create_string_buffer(image_size)
        copied = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(header), 0)
        if copied:
            parent = os.path.dirname(out_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(out_path, "wb") as f:
                _write_bmp(f, width, height, buf.raw)
            written_path = out_path

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(ctypes.c_void_p(hwnd), hwnd_dc)

    return written_path


def _write_bmp(f, width: int, height: int, pixel_data: bytes) -> None:
    row_size = ((width * 3 + 3) // 4) * 4
    image_size = row_size * height
    file_size = 14 + 40 + image_size
    f.write(b"BM")
    f.write(file_size.to_bytes(4, "little"))
    f.write((0).to_bytes(4, "little"))
    f.write((14 + 40).to_bytes(4, "little"))
    f.write((40).to_bytes(4, "little"))
    f.write(width.to_bytes(4, "little", signed=True))
    f.write(height.to_bytes(4, "little", signed=True))
    f.write((1).to_bytes(2, "little"))
    f.write((24).to_bytes(2, "little"))
    f.write((0).to_bytes(4, "little"))
    f.write(image_size.to_bytes(4, "little"))
    f.write((2835).to_bytes(4, "little", signed=True))
    f.write((2835).to_bytes(4, "little", signed=True))
    f.write((0).to_bytes(4, "little"))
    f.write((0).to_bytes(4, "little"))
    f.write(pixel_data)


# ---------------------------------------------------------------------------
# Watchdog cycle -- report-only, every backend injectable for hermetic tests
# ---------------------------------------------------------------------------

@dataclass
class WatchdogConfig:
    expected_title: str
    expected_process_name: str
    lease_path: str
    receipt_path: str
    heartbeat_path: str
    capture_dir: str
    inference_floor_mb: float = 512.0
    renderer_heartbeat_path: Optional[str] = None
    renderer_heartbeat_max_age_s: float = 5.0
    gpu_index: int = 0


def run_cycle(
    cfg: WatchdogConfig,
    window_lister: Callable[[], "list[WindowInfo]"] = enumerate_visible_windows,
    tab_lister: Callable[[], "list[TabInfo]"] = enumerate_wt_tabs,
    process_lookup: Optional[Callable[[int], Optional[str]]] = None,
    process_finder: Optional[Callable[[str], Optional[int]]] = None,
    lease_reader: Callable[[str], Optional[dict[str, Any]]] = read_gpu_lease,
    vram_query: Callable[[int], Optional[float]] = query_vram_used_mb,
    capture_fn: Callable[[int, str], Optional[str]] = capture_window_bitmap,
    renderer_heartbeat_reader: Callable[[str], Optional[dict[str, Any]]] = read_renderer_heartbeat,
    now_epoch_s: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """One watchdog cycle: evaluate the 4 legs, classify, capture iff the
    state is anomalous AND a ledgered hwnd exists, append a receipt row,
    append a heartbeat row. REPORT-ONLY: never kills a process, never closes
    a window, never relaunches anything (v1 policy, frozen by the addendum).
    """
    ts = _now_iso()

    window_leg = check_window_leg(cfg.expected_title, window_lister, tab_lister)
    process_leg = check_process_leg(window_leg, cfg.expected_process_name,
                                     process_lookup, process_finder)
    lease = lease_reader(cfg.lease_path)
    vram_used = vram_query(cfg.gpu_index)
    residency_leg = check_residency_leg(lease, vram_used, cfg.inference_floor_mb)
    renderer_heartbeat_leg = check_renderer_heartbeat_leg(
        cfg.renderer_heartbeat_path,
        process_leg,
        max_age_s=cfg.renderer_heartbeat_max_age_s,
        now_epoch_s=now_epoch_s(),
        heartbeat_reader=renderer_heartbeat_reader,
    )

    state = classify(window_leg, process_leg, residency_leg, renderer_heartbeat_leg)
    findings = liveness_findings(window_leg, process_leg, renderer_heartbeat_leg)

    capture_path = None
    if state not in ("healthy", "lease-down-healthy") and window_leg["hwnd"]:
        capture_name = f"cockpit-watchdog-{_now_compact()}.bmp"
        capture_path = capture_fn(window_leg["hwnd"], os.path.join(cfg.capture_dir, capture_name))

    receipt = {
        "ticket": "COCKPIT-WATCHDOG-CYCLE",
        "ts": ts,
        "state": state,
        "policy": "report-only",
        "window": window_leg,
        "process": process_leg,
        "renderer_heartbeat": renderer_heartbeat_leg,
        "residency": residency_leg,
        "findings": findings,
        "capture_path": capture_path,
    }
    append_jsonl(cfg.receipt_path, receipt)
    append_jsonl(cfg.heartbeat_path, {"ts": ts, "cycle": "ok", "state": state})

    return receipt


def run_loop(
    cfg: WatchdogConfig,
    interval_s: float,
    once: bool,
    **inject: Any,
) -> None:
    """Cadence loop. --once runs a single cycle and returns (tests/CI);
    otherwise sleeps interval_s between cycles until interrupted."""
    while True:
        run_cycle(cfg, **inject)
        if once:
            return
        time.sleep(interval_s)


# ---------------------------------------------------------------------------
# selftest -- simulated cycles across every classify() state, all-fake backends
# ---------------------------------------------------------------------------

def run_selftest() -> None:
    print("=== cockpit_watchdog selftest ===")
    results: dict[str, bool] = {}

    cases = {
        "healthy": dict(windows=[WindowInfo(111, "ember-resident", 222)],
                        proc_name="ember.exe", found_pid=None, lease=None, vram=8000.0),
        "lease_down_healthy": dict(windows=[], proc_name=None, found_pid=None,
                                    lease={"holder": "w1b"}, vram=50.0),
        "missing": dict(windows=[], proc_name=None, found_pid=None, lease=None, vram=0.0),
        "corpse_or_error_pane": dict(windows=[WindowInfo(111, "ember-resident", 222)],
                                      proc_name=None, found_pid=None, lease=None, vram=0.0),
        "orphan_process": dict(windows=[], proc_name=None, found_pid=222, lease=None, vram=0.0),
        "vram_mismatch": dict(windows=[WindowInfo(111, "ember-resident", 222)],
                               proc_name="ember.exe", found_pid=None,
                               lease={"holder": "w1b"}, vram=9000.0),
    }
    expected_state = {
        "healthy": "healthy", "lease_down_healthy": "lease-down-healthy",
        "missing": "missing", "corpse_or_error_pane": "corpse-or-error-pane",
        "orphan_process": "orphan-process", "vram_mismatch": "vram-mismatch",
    }

    import tempfile
    for name, case in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            cfg = WatchdogConfig(
                expected_title="ember-resident", expected_process_name="ember.exe",
                lease_path=os.path.join(tmp, "gpu-lease.json"),
                receipt_path=os.path.join(tmp, "receipts.jsonl"),
                heartbeat_path=os.path.join(tmp, "heartbeat.jsonl"),
                capture_dir=os.path.join(tmp, "captures"),
            )

            def _proc_lookup(pid, _n=case["proc_name"]):
                return _n

            def _proc_finder(_expected_name, _p=case["found_pid"]):
                return _p

            receipt = run_cycle(
                cfg,
                window_lister=lambda w=case["windows"]: w,
                process_lookup=_proc_lookup,
                process_finder=_proc_finder,
                lease_reader=lambda p, ls=case["lease"]: ls,
                vram_query=lambda gi, v=case["vram"]: v,
                capture_fn=lambda hwnd, out_path: out_path,
            )
            results[name] = receipt["state"] == expected_state[name]
            print(f"  {name}: state={receipt['state']} expected={expected_state[name]}")

    all_pass = all(results.values())
    verdict = "PASS" if all_pass else "FAIL"
    for k, v in sorted(results.items()):
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print(f"\nCOCKPIT_WATCHDOG_SELFTEST_{verdict}")
    if not all_pass:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# #413/#1330 (review round 2): third resolution-point consumer, in lockstep with
# tools/ember-cli/src/utils/ember-state-root.ts (emberStateRoot/repoStateKey) and
# Get-EmberStateRoot/Get-EmberStateRootKey in the preparation-only cockpit helper. Guarded against
# drift by scripts/tests/test_cockpit_watchdog.py's KEY_PARITY_VECTORS, which pins this
# port's output against the SAME vectors the other two suites already share.
#
# The renderer heartbeat writer (services/liveness-heartbeat.ts) resolves through
# emberStatePath(): EMBER_STATE_ROOT verbatim if set, else
# <EMBER_HOME>/cockpit-state/<repoStateKey(repoRoot)>. This module reads that same file, so
# it needs the SAME two-arm resolution -- mirroring only the override arm (as an earlier
# round of this fix did) left a standard watchdog run, with EMBER_STATE_ROOT unset in its
# own process env, reading a path the writer never touches: structural blindness dressed as
# fail-loud. Nothing wires EMBER_STATE_ROOT into the watchdog's launch environment today
# (prepare-ember-cockpit.ps1 resolves it only inside its owned preparation), so the default arm is
# the one that actually fires in practice.


class EmberStateRootError(Exception):
    """Raised when the cockpit state root cannot be resolved. Named so a caller can catch
    precisely this class, mirroring EmberStateRootError in ember-state-root.ts."""


def _repo_state_key(root: str) -> str:
    """Port of repoStateKey() in tools/ember-cli/src/utils/ember-state-root.ts. Filesystem-
    safe, case-stable key for a checkout root -- lowercased because Windows paths are
    case-insensitive, so two spellings of one checkout key to one state directory. Pinned
    byte-for-byte against KEY_PARITY_VECTORS in scripts/tests/test_cockpit_watchdog.py."""
    resolved = os.path.abspath(root).rstrip("\\/")
    key = re.sub(r"[^a-z0-9]+", "-", resolved.lower()).strip("-")
    if not key:
        raise EmberStateRootError(f"cannot derive a state key from root '{root}'")
    return key


def _ember_config_home_dir(platform: str | None = None) -> str:
    """State parent shared with the launcher/TypeScript writer.

    Explicit EMBER_HOME remains verbatim. The implicit Windows parent is the governed
    B: volume (#1317); POSIX retains the user config-home fallback.
    """
    ember_home = os.environ.get("EMBER_HOME", "").strip()
    if ember_home:
        return ember_home
    if (platform or os.name) == "nt":
        return ntpath.join("B:" + ntpath.sep, "M")
    return posixpath.join(str(Path.home()), ".ember")


def _resolve_ember_state_root(repo_root: str, platform: str | None = None) -> str:
    r"""Port of emberStateRoot()'s resolution order (the read side never needs its
    writer-only assertStateRootIsWritable guard -- this module only reads the heartbeat,
    it never writes there):
      1. EMBER_STATE_ROOT, used verbatim.
      2. <EMBER_HOME>/cockpit-state/<repoStateKey(repoRoot)> when explicit.
      3. the governed B: state parent on Windows; user config home on POSIX.
    Never silently falls back to the old in-tree path -- that file is permanently unwritten
    now, and returning it here would manufacture a false "not fresh" read instead of a loud
    resolution failure."""
    override = os.environ.get("EMBER_STATE_ROOT", "").strip()
    path_api = ntpath if (platform or os.name) == "nt" else posixpath
    if override:
        return path_api.abspath(override)
    return path_api.join(
        _ember_config_home_dir(platform), "cockpit-state", _repo_state_key(repo_root)
    )


def _default_renderer_heartbeat_path() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        state_root = _resolve_ember_state_root(repo_root)
    except EmberStateRootError as err:
        raise SystemExit(f"cockpit_watchdog: state root unresolvable: {err}") from err
    return os.path.join(state_root, "cockpit-heartbeat.json")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="cockpit_watchdog")
    sub = parser.add_subparsers(dest="cmd")

    run_p = sub.add_parser("run", help="run the watchdog (--once or --interval)")
    run_p.add_argument("--title", required=True, help="ledgered window title to match")
    run_p.add_argument("--process", default="ember.exe",
                        help="expected backing process image name (default: ember.exe)")
    run_p.add_argument("--lease-path", default=os.path.join("state", "gpu-lease.json"))
    run_p.add_argument("--receipt-path",
                        default=os.path.join("state", "cockpit-watchdog-receipts.jsonl"))
    run_p.add_argument("--heartbeat-path",
                        default=os.path.join("state", "cockpit-watchdog-heartbeat.jsonl"))
    run_p.add_argument("--renderer-heartbeat-path",
                        default=_default_renderer_heartbeat_path())
    run_p.add_argument("--renderer-heartbeat-max-age", type=float, default=5.0,
                        help="maximum accepted renderer heartbeat age in seconds")
    run_p.add_argument("--capture-dir",
                        default=os.path.join("state", "cockpit-watchdog-captures"))
    run_p.add_argument("--inference-floor-mb", type=float, default=512.0,
                        help="VRAM MB threshold above which the tenant counts as PRESENT")
    run_p.add_argument("--gpu-index", type=int, default=0)
    run_p.add_argument("--interval", type=float, default=180.0,
                        help="seconds between cycles (default 180s; spec band is ~2-5min)")
    run_p.add_argument("--once", action="store_true",
                        help="run a single cycle then exit (tests/CI; never loops)")

    sub.add_parser("selftest", help="simulated cycles across every classify() state")

    args = parser.parse_args(argv)

    if args.cmd is None or args.cmd == "selftest":
        run_selftest()
        return

    if args.cmd == "run":
        cfg = WatchdogConfig(
            expected_title=args.title,
            expected_process_name=args.process,
            lease_path=args.lease_path,
            receipt_path=args.receipt_path,
            heartbeat_path=args.heartbeat_path,
            capture_dir=args.capture_dir,
            renderer_heartbeat_path=args.renderer_heartbeat_path,
            renderer_heartbeat_max_age_s=args.renderer_heartbeat_max_age,
            inference_floor_mb=args.inference_floor_mb,
            gpu_index=args.gpu_index,
        )
        run_loop(cfg, interval_s=args.interval, once=args.once)


if __name__ == "__main__":
    main()
