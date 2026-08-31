#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""resource_dispatch_guard.py -- EMBER-01 C0 pre-dispatch resource guard.

Cures two BLOCKING rows in manifests/ember-01-custody/c0-failure-class-ledger.json
(conjunct-3, PR #1017): VRAM_OOM and COMMIT_CHARGE. Both are named there as
"resource pressure exists only as prose (CLAUDE.md safety rails), no executable
regression guard proves it is enforced" -- this module IS that guard.

Prior art this reuses rather than reimplements:
  - VRAM floor pair (vram_fraction<=0.80, margin_gib_floor>=1.5) ==
    src/ember/governance/scripts/v0_config_check.py's GOVERNOR_FLOOR, already the frozen contract
    g_governor() in src/ember/governance/scripts/v0_pretrain_launch_gate.py checks against the
    LAUNCH CONFIG. This module applies the SAME floor as a LIVE pre-dispatch
    counter read instead of a static config-value check -- a config can say
    vram_fraction<=0.80 while the box is already at 0.95 from something else
    running; this guard catches that case, g_governor() does not.
  - Commit-charge 6GiB free floor == the visible-window-hygiene.md in-run
    commit governor ("margin < 6GB free commit at any phase boundary ->
    checkpoint + clean abort") and scripts/build_fixed_prior_manifest.py's
    HOST_GOVERNOR_FLOOR_BYTES (6.0 GiB). That law governs mid-run; this
    module applies the identical floor PRE-dispatch, before the run starts.
  - GlobalMemoryStatusEx.ullAvailPageFile / ullTotalPageFile as the
    commit-charge counter == scripts/cbase_grow_rung2_gpu_offload_probe.py's
    _va_report and scripts/cbase_grow_rung2_event.py's phase_preflight
    (commit_margin_gib_floor check), reused as the same Windows API call.

Design (matches verify_c0_failure_class_ledger.py's own "honesty over green"
law): every check function is FAIL-CLOSED. A reading that is missing, the
wrong type, negative, or otherwise cannot be trusted is NEVER silently
treated as "plenty of headroom" -- it returns not-ok with a named reason.

Testability: the pure-logic check_*() functions take an INJECTED reading
dict, so the regression test suite drives them with fixture values -- no
GPU allocation, no host commit-charge draining, no torch import at test
time. The read_*_live() functions perform the REAL counter reads for a
production caller (dispatch_guard(..., live=True)); they are exercised in
production, not by CI.
"""

from __future__ import annotations

import sys
from typing import Optional

# ---- Floors (prior-art pinned; tighten-only, changing a value is a contract
# change and must be a disclosed decision, not a silent drift) ---------------
VRAM_FRACTION_CAP = 0.80            # src/ember/governance/scripts/v0_config_check.py GOVERNOR_FLOOR
VRAM_MARGIN_GIB_FLOOR = 1.5         # src/ember/governance/scripts/v0_config_check.py GOVERNOR_FLOOR
COMMIT_CHARGE_FREE_FLOOR_GIB = 6.0  # visible-window-hygiene.md in-run commit governor;
                                     # build_fixed_prior_manifest.py HOST_GOVERNOR_FLOOR_BYTES

GIB = 1024 ** 3


class ResourceReadingError(Exception):
    """Raised when a live counter cannot be read. Callers must treat this as a
    fail-closed BLOCK, never as 'no reading available, assume fine'."""


def check_vram_headroom(
    reading: dict,
    *,
    fraction_cap: float = VRAM_FRACTION_CAP,
    margin_gib_floor: float = VRAM_MARGIN_GIB_FLOOR,
) -> tuple[bool, str]:
    """Pure logic, no I/O. reading = {"total_gib": float, "allocated_gib": float,
    "requested_additional_gib": float}. Returns (ok, detail).

    Projects (allocated + requested) against total: BLOCKED (ok=False) if the
    projected fraction exceeds fraction_cap OR the projected free margin falls
    below margin_gib_floor -- the same two-clause floor v0_config_check's
    GOVERNOR_FLOOR applies to config values, applied here to a LIVE counter
    reading before work starts.

    Fail-closed: reading not a dict, or any required field missing / wrong
    type / negative, returns ok=False with a named reason -- never silently
    treated as passing headroom."""
    if not isinstance(reading, dict):
        return False, f"VRAM_OOM: reading is not a dict: {reading!r}"
    for key in ("total_gib", "allocated_gib", "requested_additional_gib"):
        val = reading.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val < 0:
            return False, f"VRAM_OOM: reading.{key} missing/invalid: {val!r}"
    total = reading["total_gib"]
    if total <= 0:
        return False, f"VRAM_OOM: reading.total_gib must be > 0, got {total!r}"
    allocated = reading["allocated_gib"]
    requested = reading["requested_additional_gib"]
    projected = allocated + requested
    projected_fraction = projected / total
    projected_free = total - projected

    if projected_fraction > fraction_cap:
        return False, (
            f"VRAM_OOM: projected usage fraction {projected_fraction:.4f} > cap "
            f"{fraction_cap} (allocated={allocated:.3f}GiB + "
            f"requested={requested:.3f}GiB of total={total:.3f}GiB)"
        )
    if projected_free < margin_gib_floor:
        return False, (
            f"VRAM_OOM: projected free margin {projected_free:.3f}GiB < floor "
            f"{margin_gib_floor}GiB (allocated={allocated:.3f}GiB + "
            f"requested={requested:.3f}GiB of total={total:.3f}GiB)"
        )
    return True, (
        f"VRAM_OOM: projected usage fraction {projected_fraction:.4f} <= cap "
        f"{fraction_cap}, projected free margin {projected_free:.3f}GiB >= floor "
        f"{margin_gib_floor}GiB"
    )


def check_commit_charge_margin(
    reading: dict,
    *,
    free_floor_gib: float = COMMIT_CHARGE_FREE_FLOOR_GIB,
) -> tuple[bool, str]:
    """Pure logic, no I/O. reading = {"total_pagefile_gib": float,
    "avail_pagefile_gib": float}. Returns (ok, detail).

    BLOCKED (ok=False) if avail_pagefile_gib < free_floor_gib -- the same
    6GiB free-commit floor law as the in-run commit governor, applied
    PRE-dispatch instead of mid-run.

    Fail-closed: reading not a dict, or either field missing / wrong type /
    negative, returns ok=False with a named reason."""
    if not isinstance(reading, dict):
        return False, f"COMMIT_CHARGE: reading is not a dict: {reading!r}"
    for key in ("total_pagefile_gib", "avail_pagefile_gib"):
        val = reading.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val < 0:
            return False, f"COMMIT_CHARGE: reading.{key} missing/invalid: {val!r}"
    avail = reading["avail_pagefile_gib"]
    total = reading["total_pagefile_gib"]
    if avail < free_floor_gib:
        return False, (
            f"COMMIT_CHARGE: avail_pagefile {avail:.3f}GiB < floor "
            f"{free_floor_gib}GiB (total_pagefile={total:.3f}GiB)"
        )
    return True, (
        f"COMMIT_CHARGE: avail_pagefile {avail:.3f}GiB >= floor {free_floor_gib}GiB "
        f"(total_pagefile={total:.3f}GiB)"
    )


# ---- Live counter readers (production path). NOT exercised by the unit test
# suite -- tests always drive check_*() directly with injected fixture
# readings, per the assignment's "NO GPU allocation in tests" instruction. ---

def read_commit_charge_live() -> dict:
    """Windows GlobalMemoryStatusEx.ullAvailPageFile/ullTotalPageFile -- the
    same field the in-run commit governor and
    cbase_grow_rung2_gpu_offload_probe.py's _va_report already key off.
    Raises ResourceReadingError on any non-Windows platform or API failure;
    never silently returns a fabricated reading."""
    if sys.platform != "win32":
        raise ResourceReadingError(
            f"COMMIT_CHARGE: live read unsupported on platform {sys.platform!r} "
            "(GlobalMemoryStatusEx is Windows-only)"
        )
    import ctypes
    import ctypes.wintypes as wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    try:
        kernel32 = ctypes.windll.kernel32
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            raise ResourceReadingError("COMMIT_CHARGE: GlobalMemoryStatusEx returned FALSE")
    except OSError as exc:
        raise ResourceReadingError(
            f"COMMIT_CHARGE: GlobalMemoryStatusEx call failed: {exc}"
        ) from exc

    return {
        "total_pagefile_gib": stat.ullTotalPageFile / GIB,
        "avail_pagefile_gib": stat.ullAvailPageFile / GIB,
    }


def read_vram_live() -> dict:
    """torch.cuda.mem_get_info() live snapshot. Raises ResourceReadingError
    when torch is unavailable, no CUDA device is visible, or the query
    itself fails; never silently returns a fabricated reading.

    requested_additional_gib is always 0.0 here -- this reader reports
    CURRENT state only. A real launch caller computes its own planned
    allocation estimate and passes it as an override before calling
    check_vram_headroom (see dispatch_guard)."""
    try:
        import torch
    except ImportError as exc:
        raise ResourceReadingError(f"VRAM_OOM: torch not importable: {exc}") from exc
    if not torch.cuda.is_available():
        raise ResourceReadingError("VRAM_OOM: torch.cuda.is_available() is False")
    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
    except Exception as exc:  # noqa: BLE001 -- fail closed on ANY query failure
        raise ResourceReadingError(
            f"VRAM_OOM: torch.cuda.mem_get_info() failed: {exc}"
        ) from exc
    total_gib = total_bytes / GIB
    allocated_gib = total_gib - (free_bytes / GIB)
    return {
        "total_gib": total_gib,
        "allocated_gib": allocated_gib,
        "requested_additional_gib": 0.0,
    }


def dispatch_guard(
    vram_reading: Optional[dict] = None,
    commit_reading: Optional[dict] = None,
    *,
    live: bool = False,
) -> tuple[bool, list[str]]:
    """Combined pre-dispatch assert -- BOTH VRAM headroom and commit-charge
    margin must hold before work starts. This is the fail-closed BEFORE-work
    gate the ledger's blocking_reason for VRAM_OOM/COMMIT_CHARGE names as
    missing ("no executable regression guard proves ... is enforced at
    launch time").

    live=True reads real counters for any reading left None (the production
    path). live=False (default) requires BOTH readings to be passed
    explicitly -- an absent reading under live=False is a caller error
    (raises ValueError), never silently treated as "skip this check".

    Returns (ok, reasons): ok is True only if BOTH checks pass; reasons
    lists both checks' details (not just the first failure) so a caller
    sees the full picture."""
    if vram_reading is None:
        if not live:
            raise ValueError("dispatch_guard: vram_reading is required when live=False")
        vram_reading = read_vram_live()
    if commit_reading is None:
        if not live:
            raise ValueError("dispatch_guard: commit_reading is required when live=False")
        commit_reading = read_commit_charge_live()

    vram_ok, vram_detail = check_vram_headroom(vram_reading)
    commit_ok, commit_detail = check_commit_charge_margin(commit_reading)
    return (vram_ok and commit_ok), [vram_detail, commit_detail]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="read real VRAM/commit-charge counters for any reading not overridden below",
    )
    parser.add_argument("--vram-json", default=None, help="JSON reading dict override")
    parser.add_argument("--commit-json", default=None, help="JSON reading dict override")
    args = parser.parse_args(argv)

    vram_reading = _json.loads(args.vram_json) if args.vram_json else None
    commit_reading = _json.loads(args.commit_json) if args.commit_json else None

    if not args.live and vram_reading is None and commit_reading is None:
        parser.error("either --live or --vram-json/--commit-json must be given")

    try:
        ok, reasons = dispatch_guard(vram_reading, commit_reading, live=args.live)
    except (ValueError, ResourceReadingError) as exc:
        print(f"RESOURCE_DISPATCH_GUARD_RED: {exc}")
        return 1

    for r in reasons:
        print(r)
    if ok:
        print("RESOURCE_DISPATCH_GUARD_GREEN -- dispatch permitted")
        return 0
    print("RESOURCE_DISPATCH_GUARD_BLOCKED -- dispatch refused")
    return 1


if __name__ == "__main__":
    sys.exit(main())
