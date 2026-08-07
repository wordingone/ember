#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""factor1_lever_microbench.py -- FACTOR-1 lever micro-bench, ember issue #764.

Round-3: repairs every defect named against round-2 on the live issue thread.
Exact source comments (fetched verbatim via `gh api repos/.../issues/comments/<id>`,
not paraphrased): BLOCK_764_CANDIDATE_ROUND1 (4943207305), AMENDMENT-4
(4943214957), BLOCK_764_LIVE_ENTRYPOINT_UNGOVERNED (4943223089),
BLOCK_764_ROUND2 (4943386132), BLOCK_764_L3A_NOT_AN_OPTIMIZER_STEP
(4943419393), plus the coordinator's --lease-token addendum and lease ruling
relayed directly.

Architecture (round-3's central fix): a CANONICAL snapshot -- grad + pristine
param + pristine state (momentum / AdamW moments) -- is built file-backed
ONCE per scale, under the run's own governed directory, and is NEVER MUTATED
AGAIN. Every lever (L0, L0-repeat, every L2 worker, L3a) loads FROM that one
canonical copy into its own transient in-RAM working tensors, runs its real
optimizer step there, and discards the working tensors on exit -- the
canonical bytes on disk never change. This is what makes "every lever starts
from an identical forked snapshot" true BY CONSTRUCTION (no explicit
clone/restore bookkeeping needed) and what keeps disk usage bounded to ONE
copy of the working set regardless of how many levers or replicates read it
(BLOCK_764_ROUND2 point 2: an earlier per-worker-copy design priced ~373 GiB
at 2.2B against ~84 GiB free).

Governance: EVERY --live / --l2-worker / CUDA touch requires a fresh,
coordinator-issued --lease-token file (issued_by/ts/expiry/scope[+
server_yielded for scope needing the shared llama-server tenant yielded).
The token is REQUIRED for every scope, including 434M CPU legs -- an earlier
per-scale-policy reading was wrong; the coordinator's addendum is unconditional
("no live/worker/CUDA dispatch before my token"). --l2-worker independently
re-verifies its own token (defense in depth: a worker invoked directly must
never be able to bypass the parent's gate). CUDA carries its own scope
("cuda") -- a CPU-scoped token never implies GPU authorization. Nothing is
allocated -- no memmap, no CUDA call -- until the full chain (token -> yield
marker where scoped -> commit gate -> physical gate -> disk gate -> abort
monitor armed) passes.

No git commits from this module. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false. This file performs NO live/worker/CUDA dispatch
on its own initiative -- `--live`/`--l2-worker` always require --lease-token.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path

# grad views are deliberately opened read-only (memmap mode='r') and are
# never written to by any optimizer step -- PyTorch's non-writable-array
# warning here is confirming the intended invariant, not flagging a bug.
warnings.filterwarnings("ignore", category=UserWarning, message=".*not writable.*")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import factor1_cpuoffload_producer as native                      # noqa: E402
import cpu_offload_adamw as coa                                       # noqa: E402
from receipt_check import INVARIANT_SHA256                            # noqa: E402
from receipt_write import checked_write                               # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_THIS_FILE = str(Path(__file__).resolve())


class _CurrentNative:
    """Small current-native adapter; historical sub-3B trainer is not imported."""
    _muon_class = staticmethod(native._muon_class)
    _zeropower_via_newtonschulz5 = staticmethod(native._zeropower_via_newtonschulz5)

    @staticmethod
    def load_contract() -> dict:
        return {"model": {"hidden": 1024, "layers": 20, "heads": 16, "vocab": 32000},
                "optimizer": {"lr_muon": 0.02, "lr_adamw": 0.0003, "weight_decay": 0.1}}


ts = _CurrentNative()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---------------------------------------------------------------------------
# Exact per-tensor shape contract (unchanged from round-2 -- this part was
# never flagged; BLOCK_764_ROUND2's shape complaint was the CONSUMER of these
# totals conflating two different reference constants, fixed below).
# ---------------------------------------------------------------------------
N_LAYERS = 20
HIDDEN = 1024
VOCAB = 32000
N_MTP = 2
FF_GROWN_2P2B = 32768
FF_BASE_434M = 4096

REF_N_MUON = 140
REF_N_ADAMW = 44
REF_ADAMW_PARAM_ELEMS = 98_345_984           # raw shape-list total (3x[32000,1024] + 41x[1024])
REF_ADAMW_STATE_ELEMS = 196_692_012          # 2 moments/param: 2*REF_ADAMW_PARAM_ELEMS + REF_N_ADAMW scalar steps
REF_2P2B_MUON_STATE_ELEMS = 2_097_152_000
REF_434M_MUON_STATE_ELEMS = 335_544_320
REF_2P2B_REALIZED_NUMEL = 2_195_497_984
REF_434M_REALIZED_NUMEL = 433_890_304

# AMENDMENT-4 point 1, verified independently against ns5_flops() below:
# 80x32.212254720 GF square + 60x697.932185600 GF rectangular (tall+wide
# share the same r=min,n=max -> same FLOP count per matrix regardless of
# orientation) = 44.4529115136 TFLOP for one full 2.2B Muon NS5 update.
COMPUTE_ROOFLINE_2P2B_TFLOP = 44.4529115136

SCALES = {
    "434M": {"intermediate": FF_BASE_434M,
              "expected_muon_elems": REF_434M_MUON_STATE_ELEMS,
              "expected_realized_numel": REF_434M_REALIZED_NUMEL,
              "scope_key": "434M-cpu", "requires_yield": False},
    "2.2B": {"intermediate": FF_GROWN_2P2B,
              "expected_muon_elems": REF_2P2B_MUON_STATE_ELEMS,
              "expected_realized_numel": REF_2P2B_REALIZED_NUMEL,
              "scope_key": "2.2B-cpu", "requires_yield": True},
}


def build_muon_shape_list(intermediate: int, n_layers: int = N_LAYERS, hidden: int = HIDDEN) -> list:
    """4x[hidden,hidden] (q/k/v/o) + 2x[intermediate,hidden] (gate/up) +
    1x[hidden,intermediate] (down), per layer. Orientation preserved
    (equal-numel square vs wide showed a 2.07x wall gap on the production
    NS5 kernel -- executed counterexample -- so totals-only surrogates are
    invalid). hidden defaults to production HIDDEN=1024; non-default is for
    selftest fixture-scale probes only."""
    items = []
    for i in range(n_layers):
        for tag in ("q", "k", "v", "o"):
            items.append({"name": f"layers.{i}.self_attn.{tag}_proj.weight",
                          "shape": (hidden, hidden), "family": "square_qkvo"})
        for tag in ("gate", "up"):
            items.append({"name": f"layers.{i}.mlp.{tag}_proj.weight",
                          "shape": (intermediate, hidden), "family": "tall_gate_up"})
        items.append({"name": f"layers.{i}.mlp.down_proj.weight",
                      "shape": (hidden, intermediate), "family": "wide_down"})
    return items


def build_adamw_shape_list(n_layers: int = N_LAYERS, hidden: int = HIDDEN,
                           vocab: int = VOCAB, n_mtp: int = N_MTP) -> list:
    """3x[vocab,hidden] (embed + n_mtp heads) + (2*n_layers+1)x[hidden] norm
    vectors. Defaults are the frozen production constants."""
    items = [{"name": "embed_tokens.weight", "shape": (vocab, hidden), "family": "embed_head"}]
    for k in range(n_mtp):
        items.append({"name": f"mtp_heads.{k}.weight", "shape": (vocab, hidden), "family": "embed_head"})
    for i in range(n_layers):
        items.append({"name": f"layers.{i}.input_layernorm.weight", "shape": (hidden,), "family": "norm_vec"})
        items.append({"name": f"layers.{i}.post_attention_layernorm.weight", "shape": (hidden,), "family": "norm_vec"})
    items.append({"name": "final_norm.weight", "shape": (hidden,), "family": "norm_vec"})
    return items


def _elems(shape) -> int:
    n = 1
    for d in shape:
        n *= d
    return n


def shape_list_totals(muon_list: list, adamw_list: list) -> dict:
    muon_elems = sum(_elems(it["shape"]) for it in muon_list)
    adamw_elems = sum(_elems(it["shape"]) for it in adamw_list)
    return {"n_muon": len(muon_list), "n_adamw": len(adamw_list),
            "muon_elems_total": muon_elems, "adamw_elems_total": adamw_elems}


SCALES_BY_INTERMEDIATE = {FF_BASE_434M: SCALES["434M"], FF_GROWN_2P2B: SCALES["2.2B"]}


def assert_shape_list_identity(intermediate: int, expected: dict) -> dict:
    """F1BENCH_SHAPES_BOUND_PASS core predicate: the identity fixture
    reproduces the frozen totals from the exact shape lists BEFORE any
    allocation or timing -- fail-closed. `adamw_elems_total` is compared
    against REF_ADAMW_PARAM_ELEMS (raw shape-list sum), never against
    REF_ADAMW_STATE_ELEMS (the DERIVED 2-moment state total) -- these are
    related but different numbers; BLOCK_764_ROUND2 caught round-2
    conflating them."""
    muon_list = build_muon_shape_list(intermediate)
    adamw_list = build_adamw_shape_list()
    totals = shape_list_totals(muon_list, adamw_list)
    errs = []
    if totals["n_muon"] != REF_N_MUON:
        errs.append(f"n_muon {totals['n_muon']} != {REF_N_MUON}")
    if totals["n_adamw"] != REF_N_ADAMW:
        errs.append(f"n_adamw {totals['n_adamw']} != {REF_N_ADAMW}")
    if totals["adamw_elems_total"] != REF_ADAMW_PARAM_ELEMS:
        errs.append(f"adamw_elems_total {totals['adamw_elems_total']} != {REF_ADAMW_PARAM_ELEMS}")
    adamw_state_elems = totals["adamw_elems_total"] * 2 + REF_N_ADAMW
    if adamw_state_elems != REF_ADAMW_STATE_ELEMS:
        errs.append(f"adamw_state_elems(derived) {adamw_state_elems} != {REF_ADAMW_STATE_ELEMS}")
    if totals["muon_elems_total"] != expected["expected_muon_elems"]:
        errs.append(f"muon_elems_total {totals['muon_elems_total']} != {expected['expected_muon_elems']}")
    realized = totals["muon_elems_total"] + totals["adamw_elems_total"]
    if realized != expected["expected_realized_numel"]:
        errs.append(f"realized_numel {realized} != {expected['expected_realized_numel']}")
    if errs:
        raise ValueError("F1BENCH_SHAPES_BOUND_REFUSED: " + "; ".join(errs))
    return {"muon_list": muon_list, "adamw_list": adamw_list, "totals": totals}


# ---------------------------------------------------------------------------
# Governance: authorization + lease-token + physical/commit/disk preflight +
# abort-monitor arming. Nothing below allocates memory or touches CUDA -- it
# only reads system telemetry and JSON files.
# ---------------------------------------------------------------------------
PHYSICAL_MARGIN_FLOOR_GIB = 6.0
COMMIT_MARGIN_FLOOR_GIB = 6.0
DISK_MARGIN_FLOOR_GIB = 4.0
LEASE_TOKEN_MAX_AGE_S = 2 * 3600   # token older than its own ts by this much, even if not yet "expired", is suspect

# Mid-run ENFORCED thresholds (BLOCK_764_ROUND3 point 4: round-3's first cut
# recorded disk-free and page-fault deltas but only ever set should_abort
# from physical margin -- "a recorder is not a governor"). Rate thresholds
# are deliberately generous first-cut floors (disclosed, not empirically
# calibrated) so a legitimate one-time canonical-snapshot write burst never
# false-positive-aborts a governed run; tightening is a coordinator call
# once a real live receipt exists to calibrate against.
PAGE_FAULT_RATE_ABORT_PER_S = 2_000_000.0
DISK_IO_RATE_ABORT_MBPS = 6000.0
RATE_CHECK_MIN_ELAPSED_S = 1.0   # below this window a rate estimate is noise, not signal -- measured, not enforced


def _read_mem_status() -> dict | None:
    """Ground-truth Windows physical + commit via ONE GlobalMemoryStatusEx
    call. Never raises -- returns None on failure (disclosed, never a
    silent pass)."""
    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if not ok:
            return None
        gib = 1024.0 ** 3
        return {
            "available_physical_gib": round(stat.ullAvailPhys / gib, 3),
            "total_physical_gib": round(stat.ullTotalPhys / gib, 3),
            "available_commit_gib": round(stat.ullAvailPageFile / gib, 3),
            "total_commit_gib": round(stat.ullTotalPageFile / gib, 3),
        }
    except Exception:
        return None


def _read_page_fault_count() -> int | None:
    """Current process page-fault count via GetProcessMemoryInfo (psapi).
    Windows-native equivalent of the posix rusage field; used for the
    before/peak/after paging telemetry AMENDMENT-4 point 3 requires."""
    try:
        class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        # GetCurrentProcess returns a pointer-sized pseudo-handle (-1).
        # Without explicit restype/argtypes ctypes marshals it through the
        # default c_int return type, truncating it -- every downstream
        # psapi call then fails with ERROR_INVALID_HANDLE (6), silently
        # returning None forever. Found live: this is exactly why a
        # 'recorded but never enforced' page-fault check never surfaced it.
        ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.kernel32.GetCurrentProcess.argtypes = []
        ctypes.windll.psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), ctypes.c_ulong]
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(counters), counters.cb)
        return int(counters.PageFaultCount) if ok else None
    except Exception:
        return None


def _read_io_counters() -> dict | None:
    """Current process disk-I/O byte counters via GetProcessIoCounters --
    lets the abort monitor measure sustained disk-I/O rate, not just
    page-fault count (BLOCK_764_ROUND3 point 4: 'no ... disk-I/O measurement
    exists'). Never raises -- returns None on failure (disclosed, never a
    silent pass)."""
    try:
        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong), ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong), ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong), ("OtherTransferCount", ctypes.c_ulonglong),
            ]
        counters = _IO_COUNTERS()
        # Same pseudo-handle truncation fix as _read_page_fault_count.
        ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.kernel32.GetCurrentProcess.argtypes = []
        ctypes.windll.kernel32.GetProcessIoCounters.restype = ctypes.c_int
        ctypes.windll.kernel32.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IO_COUNTERS)]
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.kernel32.GetProcessIoCounters(h, ctypes.byref(counters))
        if not ok:
            return None
        return {"read_bytes": int(counters.ReadTransferCount), "write_bytes": int(counters.WriteTransferCount)}
    except Exception:
        return None


def _read_disk_free_gib(path: str) -> dict | None:
    import shutil
    try:
        usage = shutil.disk_usage(path)
        gib = 1024.0 ** 3
        return {"free_gib": round(usage.free / gib, 3), "total_gib": round(usage.total / gib, 3)}
    except Exception:
        return None


def preflight_gate(*, required_working_set_gib: float, run_dir: str,
                    physical_floor_gib: float = PHYSICAL_MARGIN_FLOOR_GIB,
                    commit_floor_gib: float = COMMIT_MARGIN_FLOOR_GIB,
                    disk_floor_gib: float = DISK_MARGIN_FLOOR_GIB) -> dict:
    """Fail-closed: refuses on insufficient OR unavailable physical/commit/
    disk -- an unmeasured required resource is a refusal, never a silent
    pass. Called BEFORE any memmap is created."""
    mem = _read_mem_status()
    disk = _read_disk_free_gib(run_dir)
    result = {"required_working_set_gib": required_working_set_gib,
              "mem": mem, "disk": disk, "sufficient": True, "refusal_reasons": []}

    def _refuse(reason):
        result["sufficient"] = False
        result["refusal_reasons"].append(reason)

    if mem is None:
        _refuse("physical/commit measurement unavailable (GlobalMemoryStatusEx read failure)")
    else:
        phys_margin = round(mem["available_physical_gib"] - required_working_set_gib, 3)
        commit_margin = round(mem["available_commit_gib"] - required_working_set_gib, 3)
        result["physical_margin_gib"] = phys_margin
        result["commit_margin_gib"] = commit_margin
        if phys_margin < physical_floor_gib:
            _refuse(f"available-physical margin {phys_margin}GiB < floor {physical_floor_gib}GiB "
                    f"(available={mem['available_physical_gib']}GiB, required={required_working_set_gib}GiB)")
        if commit_margin < commit_floor_gib:
            _refuse(f"available-commit margin {commit_margin}GiB < floor {commit_floor_gib}GiB")

    if disk is None:
        _refuse("disk-free measurement unavailable (disk_usage read failure)")
    else:
        disk_margin = round(disk["free_gib"] - required_working_set_gib, 3)
        result["disk_margin_gib"] = disk_margin
        if disk_margin < disk_floor_gib:
            _refuse(f"disk-free margin {disk_margin}GiB < floor {disk_floor_gib}GiB")

    result["refusal"] = " | ".join(result["refusal_reasons"]) or None
    return result


def arm_abort_monitor(run_dir: str) -> dict:
    """Final preflight step (chain: token -> yield -> commit -> physical ->
    disk -> ABORT MONITOR ARMED -> only then allocate). Captures baseline
    physical/commit/page-fault/disk-I/O telemetry plus a monotonic clock
    reading (for rate computation); `check_abort_monitor` computes deltas
    against this baseline at later phase boundaries so an in-run resource
    collapse aborts cleanly instead of running into the wall."""
    return {"armed_at": _ts(), "armed_at_monotonic": time.perf_counter(),
            "baseline_mem": _read_mem_status(),
            "baseline_page_faults": _read_page_fault_count(),
            "baseline_io": _read_io_counters(),
            "baseline_disk": _read_disk_free_gib(run_dir)}


def check_abort_monitor(armed: dict, *, run_dir: str, required_working_set_gib: float,
                        physical_floor_gib: float = PHYSICAL_MARGIN_FLOOR_GIB,
                        commit_floor_gib: float = COMMIT_MARGIN_FLOOR_GIB,
                        disk_floor_gib: float = DISK_MARGIN_FLOOR_GIB,
                        page_fault_rate_abort_per_s: float = PAGE_FAULT_RATE_ABORT_PER_S,
                        disk_io_rate_abort_mbps: float = DISK_IO_RATE_ABORT_MBPS) -> dict:
    """Phase-boundary re-check: same discipline as the in-run commit
    governor pattern used elsewhere in this tree -- refuse to proceed into
    the wall rather than degrade. Never fatal by itself; callers decide
    whether to abort the scale run on `should_abort`. ENFORCES (not just
    records) commit margin, disk margin, sustained page-fault rate, and
    sustained disk-I/O rate against the armed baseline -- round-3's first
    cut recorded disk/page-fault deltas but only ever aborted on physical
    margin (BLOCK_764_ROUND3 point 4: 'a recorder is not a governor'). Rate
    checks are measured-but-not-enforced below RATE_CHECK_MIN_ELAPSED_S,
    since a near-zero window makes any rate estimate noise, not signal."""
    mem = _read_mem_status()
    disk = _read_disk_free_gib(run_dir)
    pf = _read_page_fault_count()
    io = _read_io_counters()
    now_mono = time.perf_counter()
    elapsed_s = max(now_mono - armed.get("armed_at_monotonic", now_mono), 1e-6)

    should_abort = False
    reasons = []

    if mem is None:
        should_abort = True
        reasons.append("physical/commit measurement unavailable mid-run")
    else:
        phys_margin = round(mem["available_physical_gib"] - required_working_set_gib, 3)
        commit_margin = round(mem["available_commit_gib"] - required_working_set_gib, 3)
        if phys_margin < physical_floor_gib:
            should_abort = True
            reasons.append(f"mid-run available-physical margin {phys_margin}GiB < floor {physical_floor_gib}GiB")
        if commit_margin < commit_floor_gib:
            should_abort = True
            reasons.append(f"mid-run available-commit margin {commit_margin}GiB < floor {commit_floor_gib}GiB")

    if disk is None:
        should_abort = True
        reasons.append("disk-free measurement unavailable mid-run")
    else:
        disk_margin = round(disk["free_gib"] - required_working_set_gib, 3)
        if disk_margin < disk_floor_gib:
            should_abort = True
            reasons.append(f"mid-run disk-free margin {disk_margin}GiB < floor {disk_floor_gib}GiB")

    page_faults_delta = (pf - armed["baseline_page_faults"]) if (
        pf is not None and armed.get("baseline_page_faults") is not None) else None
    io_delta_bytes = None
    if io is not None and armed.get("baseline_io") is not None:
        io_delta_bytes = ((io["read_bytes"] + io["write_bytes"])
                          - (armed["baseline_io"]["read_bytes"] + armed["baseline_io"]["write_bytes"]))

    page_fault_rate_per_s = None
    io_rate_mbps = None
    rate_window_sufficient = elapsed_s >= RATE_CHECK_MIN_ELAPSED_S
    if page_faults_delta is not None:
        page_fault_rate_per_s = page_faults_delta / elapsed_s
        if rate_window_sufficient and page_fault_rate_per_s > page_fault_rate_abort_per_s:
            should_abort = True
            reasons.append(f"sustained page-fault rate {round(page_fault_rate_per_s)}/s "
                           f"> floor {page_fault_rate_abort_per_s}/s")
    if io_delta_bytes is not None:
        io_rate_mbps = (io_delta_bytes / 1e6) / elapsed_s
        if rate_window_sufficient and io_rate_mbps > disk_io_rate_abort_mbps:
            should_abort = True
            reasons.append(f"sustained disk-I/O rate {round(io_rate_mbps, 1)}MB/s > floor {disk_io_rate_abort_mbps}MB/s")

    return {"ts": _ts(), "elapsed_s": round(elapsed_s, 3), "rate_window_sufficient": rate_window_sufficient,
            "mem": mem, "disk": disk, "page_faults": pf, "page_faults_delta": page_faults_delta,
            "page_fault_rate_per_s": round(page_fault_rate_per_s, 1) if page_fault_rate_per_s is not None else None,
            "io": io, "io_delta_bytes": io_delta_bytes,
            "io_rate_mbps": round(io_rate_mbps, 3) if io_rate_mbps is not None else None,
            "should_abort": should_abort, "reason": " | ".join(reasons) if reasons else None}


def check_authorization() -> dict:
    return {"env_authorized": os.environ.get("EMBER_GATE_AUTHORIZED") == "1"}


def check_lease_token(token_path, *, required_scope: str) -> dict:
    """Coordinator addendum (binding, unconditional across every scale):
    '--live requires an explicit --lease-token <path> pointing to a
    coordinator-written lease file... absent/expired/malformed token =
    refuse BEFORE any build_state or CUDA touch.' Token schema:
    {issued_by, ts, expiry, scope: [...], server_yielded?}. `required_scope`
    is one of SCALES[x]['scope_key'] or 'cuda' -- a token authorizes only
    the scopes explicitly listed; a CPU-scoped token never implies CUDA.
    scopes 'requires_yield' (2.2B-cpu, cuda) additionally require
    server_yielded=true in the token."""
    if token_path is None:
        return {"valid": False, "reason": "no --lease-token provided"}
    p = Path(token_path)
    if not p.is_file():
        return {"valid": False, "reason": f"lease token not found: {p}"}
    try:
        with open(p, "r", encoding="utf-8") as f:
            token = json.load(f)
    except Exception as e:
        return {"valid": False, "reason": f"lease token unparseable: {type(e).__name__}: {e}"}
    for field in ("issued_by", "ts", "expiry", "scope"):
        if field not in token:
            return {"valid": False, "reason": f"lease token missing required field: {field}"}
    try:
        ts_epoch = _parse_iso(token["ts"])
        expiry_epoch = _parse_iso(token["expiry"])
    except Exception as e:
        return {"valid": False, "reason": f"lease token ts/expiry unparseable: {type(e).__name__}: {e}"}
    now = time.time()
    if now > expiry_epoch:
        return {"valid": False, "reason": f"lease token expired at {token['expiry']}"}
    if now < ts_epoch:
        return {"valid": False, "reason": f"lease token future-dated: ts={token['ts']}"}
    scope = token.get("scope")
    if not isinstance(scope, list) or required_scope not in scope:
        return {"valid": False, "reason": f"lease token scope {scope!r} does not include required '{required_scope}'"}
    requires_yield = required_scope in ("2.2B-cpu", "cuda")
    if requires_yield and token.get("server_yielded") is not True:
        return {"valid": False, "reason": f"scope '{required_scope}' requires server_yielded=true in the token"}
    return {"valid": True, "token": token, "age_s": round(now - ts_epoch, 1)}


def exact_scale_working_set_gib(muon_elems: int, adamw_elems: int) -> float:
    """Muon side: shadow + grad + momentum = 3x raw elems -> 2,097,152,000
    elems = 23.4375 GiB exactly. AdamW side: shadow + grad + 2 moments = 4x
    raw elems -> 98,345,984 elems = 1.46547 GiB exactly. Combined at 2.2B:
    24.90297 GiB, matching the adopted reference figure to 5 decimals.
    `adamw_elems` is the RAW param-element total (REF_ADAMW_PARAM_ELEMS),
    matching what shape_list_totals() returns -- not the state-element
    total."""
    muon_bytes = muon_elems * 4 * 3
    adamw_bytes = adamw_elems * 4 * 4
    return round((muon_bytes + adamw_bytes) / (1024 ** 3), 5)


# ---------------------------------------------------------------------------
# Canonical snapshot: built file-backed ONCE per scale, NEVER mutated again.
# Every lever loads FROM it into transient in-RAM working tensors. Grad is
# opened read-only (memmap, zero-copy, safely shared across sequential
# readers since it is never written). Param/state are copied into REAL
# in-RAM tensors (never a new memmap file) so an optimizer step's in-place
# mutation never touches the canonical bytes on disk -- this is the
# 'workers open it read-only and write only their own small output buffers'
# design (team-lead ruling, repairs BLOCK_764_ROUND2 point 2's ~373 GiB
# disk-explosion defect).
# ---------------------------------------------------------------------------
CHUNK_ELEMS = 8_000_000   # ~32MB fp32 chunks -- bounded transient allocation


def _sanitize(name: str) -> str:
    return name.replace(".", "_")


def _memmap_random_chunked(path: Path, shape: tuple, *, generator):
    import numpy as np
    import torch
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.memmap(str(path), dtype=np.float32, mode="w+", shape=shape)
    flat = arr.reshape(-1)
    n = flat.shape[0]
    pos = 0
    while pos < n:
        take = min(CHUNK_ELEMS, n - pos)
        chunk = torch.randn(take, generator=generator, dtype=torch.float32).numpy()
        flat[pos:pos + take] = chunk
        pos += take
    arr.flush()
    del arr
    return path


def build_canonical_snapshot(intermediate: int, run_dir: Path, seed: int, *,
                              only_items=None, n_layers: int = N_LAYERS,
                              hidden: int = HIDDEN, vocab: int = VOCAB) -> dict:
    """Builds pristine grad + param(shadow) + state files ONCE. Returns a
    manifest (file paths + shapes + families) -- no torch tensors held
    open here, so this function's own memory footprint stays bounded to one
    CHUNK_ELEMS buffer regardless of scale."""
    if only_items is not None:
        muon_list, adamw_list = only_items["muon"], only_items["adamw"]
    elif intermediate in SCALES_BY_INTERMEDIATE:
        identity = assert_shape_list_identity(intermediate, SCALES_BY_INTERMEDIATE[intermediate])
        muon_list, adamw_list = identity["muon_list"], identity["adamw_list"]
    else:
        muon_list = build_muon_shape_list(intermediate, n_layers=n_layers, hidden=hidden)
        adamw_list = build_adamw_shape_list(n_layers=n_layers, hidden=hidden, vocab=vocab)

    import torch
    canon_dir = run_dir / "canonical"
    g = torch.Generator().manual_seed(seed)
    manifest = {"dir": str(canon_dir), "seed": seed, "intermediate": intermediate, "muon": [], "adamw": []}
    for item in muon_list:
        stem = canon_dir / _sanitize(item["name"])
        param_path = _memmap_random_chunked(Path(str(stem) + ".param.f32"), item["shape"], generator=g)
        grad_path = _memmap_random_chunked(Path(str(stem) + ".grad.f32"), item["shape"], generator=g)
        mom_path = Path(str(stem) + ".momentum.f32")
        coa._memmap_zeros(mom_path, item["shape"])
        manifest["muon"].append({**item, "param_path": str(param_path), "grad_path": str(grad_path),
                                 "momentum_path": str(mom_path)})
    for item in adamw_list:
        stem = canon_dir / _sanitize(item["name"])
        param_path = _memmap_random_chunked(Path(str(stem) + ".param.f32"), item["shape"], generator=g)
        grad_path = _memmap_random_chunked(Path(str(stem) + ".grad.f32"), item["shape"], generator=g)
        exp_avg_path = Path(str(stem) + ".exp_avg.f32")
        exp_avg_sq_path = Path(str(stem) + ".exp_avg_sq.f32")
        coa._memmap_zeros(exp_avg_path, item["shape"])
        coa._memmap_zeros(exp_avg_sq_path, item["shape"])
        manifest["adamw"].append({**item, "param_path": str(param_path), "grad_path": str(grad_path),
                                  "exp_avg_path": str(exp_avg_path), "exp_avg_sq_path": str(exp_avg_sq_path)})
    return manifest


def _load_ram_copy(path: str, shape: tuple):
    """Force an in-RAM COPY off a memmap file -- mutating the returned
    tensor NEVER touches the file on disk (np.array(memmap) copies)."""
    import numpy as np
    import torch
    arr = np.array(np.memmap(path, dtype=np.float32, mode="r", shape=shape))
    return torch.from_numpy(arr)


def _load_readonly_view(path: str, shape: tuple):
    """Zero-copy read-only memmap view -- safe to open from multiple
    sequential (never-concurrent-writing) readers since the file is never
    mutated after build_canonical_snapshot returns."""
    import numpy as np
    import torch
    arr = np.memmap(path, dtype=np.float32, mode="r", shape=shape)
    return torch.from_numpy(arr)


def build_exact_optimizers_from_canonical(manifest: dict, cfg: dict, *, only_families=None) -> dict:
    """Loads each lever's OWN transient working copy from the canonical
    snapshot: grad is a read-only memmap view (zero-copy); param is an
    in-RAM mutable copy; state (momentum / AdamW moments) is an in-RAM
    mutable copy seeded from the canonical zeros. Instantiates and returns
    the REAL torch.optim.AdamW / ts._muon_class() optimizers wired to these
    tensors -- never reimplemented math."""
    import torch
    muon_items = [it for it in manifest["muon"] if only_families is None or it["family"] in only_families]
    adamw_items = [it for it in manifest["adamw"] if only_families is None or it["family"] in only_families]

    muon_params = []
    for item in muon_items:
        shadow = _load_ram_copy(item["param_path"], item["shape"])
        shadow.requires_grad_(True)
        shadow.grad = _load_readonly_view(item["grad_path"], item["shape"])
        muon_params.append((item, shadow))
    adamw_params = []
    for item in adamw_items:
        shadow = _load_ram_copy(item["param_path"], item["shape"])
        shadow.requires_grad_(True)
        shadow.grad = _load_readonly_view(item["grad_path"], item["shape"])
        adamw_params.append((item, shadow))

    Muon = ts._muon_class()
    lr_muon = cfg["optimizer"]["lr_muon"]
    lr_adamw = cfg["optimizer"]["lr_adamw"]
    wd = cfg["optimizer"]["weight_decay"]

    muon_opt = adamw_opt = None
    if muon_params:
        muon_opt = Muon([t for _, t in muon_params], lr=lr_muon, weight_decay=wd)
        for item, shadow_p in muon_params:
            muon_opt.state[shadow_p] = {"momentum_buffer": _load_ram_copy(item["momentum_path"], item["shape"])}
    if adamw_params:
        adamw_opt = torch.optim.AdamW([t for _, t in adamw_params], lr=lr_adamw, weight_decay=wd)
        for item, shadow_p in adamw_params:
            adamw_opt.state[shadow_p] = {
                "step": torch.tensor(0.0, dtype=torch.float32),
                "exp_avg": _load_ram_copy(item["exp_avg_path"], item["shape"]),
                "exp_avg_sq": _load_ram_copy(item["exp_avg_sq_path"], item["shape"])}
    return {"muon_opt": muon_opt, "adamw_opt": adamw_opt, "muon_params": muon_params, "adamw_params": adamw_params}


# ---------------------------------------------------------------------------
# Custody hashing + transition-equivalence gate. Tolerances FROZEN here.
# ---------------------------------------------------------------------------
EQUIV_MAX_ABS_TOL = 1e-3
EQUIV_MAX_REL_TOL = 1e-2
EQUIV_COSINE_FLOOR = 0.999
EQUIV_UPDATE_NORM_RATIO_BAND = (0.98, 1.02)


def _custody_hash(params: list) -> str:
    h = hashlib.sha256()
    for _, t in params:
        h.update(t.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def _flatten_all(params: list):
    import torch
    return torch.cat([t.detach().reshape(-1).to(torch.float64) for _, t in params]) if params else None


def compare_transition(pre_params: list, post_params_a: list, post_params_b: list, *, label: str) -> dict:
    """pre_params/post_params_a/post_params_b must be INDEPENDENT tensors
    (never the same aliased objects at different times -- BLOCK_764_ROUND2
    point 3: 'pre_params = built[...]; post_params = pre_params' collapses
    upd_a to zero and makes the gate self-satisfying). Every caller in this
    file loads pre/post from SEPARATE canonical reads or explicit clones."""
    import torch
    pre = _flatten_all(pre_params)
    post_a = _flatten_all(post_params_a)
    post_b = _flatten_all(post_params_b)
    if pre is None:
        return {"label": label, "passed": True, "note": "empty param list"}
    upd_a = post_a - pre
    upd_b = post_b - pre
    finite_a = bool(torch.isfinite(post_a).all())
    finite_b = bool(torch.isfinite(post_b).all())
    max_abs = float((upd_a - upd_b).abs().max())
    denom = upd_a.abs().clamp_min(1e-12)
    max_rel = float(((upd_a - upd_b).abs() / denom).max())
    norm_a = float(upd_a.norm())
    norm_b = float(upd_b.norm())
    cosine = float(torch.dot(upd_a, upd_b) / (upd_a.norm() * upd_b.norm() + 1e-12)) if norm_a > 0 and norm_b > 0 else 1.0
    norm_ratio = (norm_b / norm_a) if norm_a > 0 else 1.0
    passed = (finite_a and finite_b and max_abs <= EQUIV_MAX_ABS_TOL and max_rel <= EQUIV_MAX_REL_TOL
              and cosine >= EQUIV_COSINE_FLOOR
              and EQUIV_UPDATE_NORM_RATIO_BAND[0] <= norm_ratio <= EQUIV_UPDATE_NORM_RATIO_BAND[1])
    return {"label": label, "passed": passed, "finite_a": finite_a, "finite_b": finite_b,
            "max_abs": max_abs, "max_rel": max_rel, "cosine": cosine, "update_norm_ratio": norm_ratio,
            "tolerances": {"max_abs_tol": EQUIV_MAX_ABS_TOL, "max_rel_tol": EQUIV_MAX_REL_TOL,
                           "cosine_floor": EQUIV_COSINE_FLOOR,
                           "update_norm_ratio_band": list(EQUIV_UPDATE_NORM_RATIO_BAND)}}


# ---------------------------------------------------------------------------
# Roofline calibration -- bandwidth AND compute.
# ---------------------------------------------------------------------------
BANDWIDTH_NOMINAL_GBPS = 96.0
BANDWIDTH_EMPIRICAL_FLAG_MULTIPLE = 1.5
COMPUTE_NOMINAL_TFLOPS = 4.3
COMPUTE_EMPIRICAL_FLAG_MULTIPLE = 3.0


def calibrate_bandwidth(thread_counts=(1, 8, 16, 24, 32), n_elems: int = 1 << 24, n_trials: int = 5) -> dict:
    import torch
    prev = torch.get_num_threads()
    results = {}
    try:
        for t in thread_counts:
            torch.set_num_threads(t)
            src = torch.randn(n_elems, dtype=torch.float32)
            dst = torch.empty(n_elems, dtype=torch.float32)
            for _ in range(2):
                dst.copy_(src)
            t0 = time.perf_counter()
            for _ in range(n_trials):
                dst.copy_(src)
            dt = (time.perf_counter() - t0) / n_trials
            gbps = (n_elems * 4 / dt) / 1e9 if dt > 0 else None
            results[str(t)] = {"gbps": round(gbps, 3) if gbps else None, "seconds_per_copy": round(dt, 6)}
    finally:
        torch.set_num_threads(prev)
    plateau_gbps = max((v["gbps"] for v in results.values() if v["gbps"]), default=None)
    return {"by_threads": results, "empirical_plateau_gbps": plateau_gbps, "nominal_gbps": BANDWIDTH_NOMINAL_GBPS}


def calibrate_compute(dim: int = 1024, threads: int = 16, n_trials: int = 5) -> dict:
    import torch
    prev = torch.get_num_threads()
    torch.set_num_threads(threads)
    try:
        a = torch.randn(dim, dim, dtype=torch.float32)
        b = torch.randn(dim, dim, dtype=torch.float32)
        for _ in range(2):
            a @ b
        t0 = time.perf_counter()
        for _ in range(n_trials):
            a @ b
        dt = (time.perf_counter() - t0) / n_trials
        flops = 2 * dim ** 3
        tflops = (flops / dt) / 1e12 if dt > 0 else None
    finally:
        torch.set_num_threads(prev)
    return {"dim": dim, "threads": threads, "seconds_per_matmul": round(dt, 6),
            "empirical_tflops": round(tflops, 4) if tflops else None, "nominal_tflops": COMPUTE_NOMINAL_TFLOPS}


def ns5_flops(dim0: int, dim1: int, steps: int = 5) -> int:
    """r=min(dims), n=max(dims); FLOP = steps*(4*r^2*n + 2*r^3). Verified
    against AMENDMENT-4's own executed reference: 80x32.212254720 GF square
    + 60x697.932185600 GF rectangular = 44.4529115136 TFLOP total at 2.2B."""
    r, n = min(dim0, dim1), max(dim0, dim1)
    return int(steps * (4 * r * r * n + 2 * r ** 3))


def roofline_sanity_check(*, elems_touched: int, measured_time_s, flop_total: int,
                           bandwidth_calib: dict, compute_calib: dict) -> dict:
    if not measured_time_s or measured_time_s <= 0:
        return {"passed": False, "reason": "non-positive measured time"}
    implied_gbps = (elems_touched * 4 / measured_time_s) / 1e9
    implied_tflops = (flop_total / measured_time_s) / 1e12
    plateau = bandwidth_calib.get("empirical_plateau_gbps") or BANDWIDTH_NOMINAL_GBPS
    empirical_tflops = compute_calib.get("empirical_tflops") or COMPUTE_NOMINAL_TFLOPS
    bw_flag = implied_gbps > BANDWIDTH_EMPIRICAL_FLAG_MULTIPLE * plateau
    bw_refuse = implied_gbps > BANDWIDTH_NOMINAL_GBPS
    cp_flag = implied_tflops > COMPUTE_EMPIRICAL_FLAG_MULTIPLE * empirical_tflops
    cp_refuse = implied_tflops > COMPUTE_NOMINAL_TFLOPS
    passed = not (bw_refuse or cp_refuse)
    return {"passed": passed, "implied_gbps": round(implied_gbps, 3), "implied_tflops": round(implied_tflops, 4),
            "bandwidth_flag": bw_flag, "bandwidth_refuse": bw_refuse,
            "compute_flag": cp_flag, "compute_refuse": cp_refuse,
            "bandwidth_nominal_gbps": BANDWIDTH_NOMINAL_GBPS, "compute_nominal_tflops": COMPUTE_NOMINAL_TFLOPS}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 0


def _bootstrap_ci95_median(values: list, *, n_resamples: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED) -> dict:
    import numpy as np
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return {"lower": None, "upper": None, "median": None, "n": 0}
    idx = rng.integers(0, n, size=(n_resamples, n))
    medians = np.median(arr[idx], axis=1)
    lower, upper = np.percentile(medians, [2.5, 97.5])
    return {"lower": round(float(lower), 6), "upper": round(float(upper), 6),
            "median": round(float(np.median(arr)), 6), "n": int(n)}


def _ci_overlap(ci_a: dict, ci_b: dict) -> bool:
    if ci_a.get("lower") is None or ci_b.get("lower") is None:
        return False
    return not (ci_a["upper"] < ci_b["lower"] or ci_b["upper"] < ci_a["lower"])


# ---------------------------------------------------------------------------
# L0: loads a FRESH transient working copy from the canonical snapshot every
# time it is called (build_exact_optimizers_from_canonical), so repeated
# calls are automatically identical forks -- no explicit clone/restore
# bookkeeping, and no aliasing between the pre-step and post-step reference
# (round-2's bug: this file now keeps an EXPLICIT independent pre-step
# custody snapshot captured before any step() call, distinct from the
# post-step live tensors).
# ---------------------------------------------------------------------------
PRODUCTION_DEFAULT_THREADS = 16
N_WARMUP = 3
N_TIMED = 20


def _step_all(built: dict):
    if built["muon_opt"] is not None:
        built["muon_opt"].step()
    if built["adamw_opt"] is not None:
        built["adamw_opt"].step()


def lever_L0(manifest: dict, cfg: dict, *, only_families=None,
             n_warmup: int = N_WARMUP, n_timed: int = N_TIMED,
             threads: int = PRODUCTION_DEFAULT_THREADS) -> dict:
    """Times ONLY the inner optimizer step (torch.optim.AdamW.step() /
    ts._muon_class().step(), driven directly on transient working tensors
    loaded from the canonical snapshot) -- never the CPUOffloadOptimizer
    wrapper's grad-shuttle phases, which are CPU-CPU-copy artifacts on this
    fixture and not real GPU-offload physics (BLOCK_764_CANDIDATE_ROUND1
    point 1). A separate selftest leg proves the real wrapper still
    round-trips end to end on a tiny model."""
    import torch
    prev = torch.get_num_threads()
    torch.set_num_threads(threads)
    try:
        built = build_exact_optimizers_from_canonical(manifest, cfg, only_families=only_families)
        for _ in range(n_warmup):
            _step_all(built)
        # re-load a fresh identical fork for the actually-timed portion, so
        # warmup's mutation never contaminates the timed measurement's
        # starting point either.
        built = build_exact_optimizers_from_canonical(manifest, cfg, only_families=only_families)
        live_params = built["muon_params"] + built["adamw_params"]
        pre_snapshot = [(it, t.detach().clone()) for it, t in live_params]
        # independent pre-step momentum snapshot (Muon only -- BLOCK_764_ROUND3
        # point 2 needs param AND momentum numeric equivalence for L3a, not
        # just tensor-name parity).
        pre_momentum = ([(it, built["muon_opt"].state[t]["momentum_buffer"].detach().clone())
                         for it, t in built["muon_params"]] if built["muon_opt"] is not None else [])
        pre_hash = _custody_hash(pre_snapshot)
        walls = []
        for _ in range(n_timed):
            t0 = time.perf_counter()
            _step_all(built)
            walls.append(time.perf_counter() - t0)
        post_live = live_params   # mutated in place -- now holds true post-step values
        post_momentum = ([(it, built["muon_opt"].state[t]["momentum_buffer"].detach().clone())
                          for it, t in built["muon_params"]] if built["muon_opt"] is not None else [])
    finally:
        torch.set_num_threads(prev)
    ci = _bootstrap_ci95_median(walls)
    return {"lever": "L0_production_order", "threads": threads, "seed": manifest["seed"],
            "pre_custody_hash": pre_hash, "walls_s": walls, "median_s": ci["median"], "ci95": ci,
            "pre_params": pre_snapshot, "post_params": post_live,
            "pre_momentum": pre_momentum, "post_momentum": post_momentum}


# ---------------------------------------------------------------------------
# L1: compiler-inventory-gated (fixed round-2: a bare-matmul probe silently
# 'succeeds' via a direct ATen kernel call even with zero compilers present
# -- not diagnostic. Gate on inventory first; pilot only if a compiler
# exists, against the real NS5 elementwise+matmul mix.)
# ---------------------------------------------------------------------------
def lever_L1_disposition() -> dict:
    import shutil
    compilers = {name: shutil.which(name) for name in ("cl", "gcc", "clang")}
    if not any(compilers.values()):
        return {"lever": "L1_torch_compile", "status": "L1_UNAVAILABLE",
                "reason": ("no C/C++ compiler on PATH (cl/gcc/clang all absent) -- no live pilot "
                           "attempted; a trivial bare-matmul probe is not diagnostic here (Inductor "
                           "can satisfy that graph via a direct ATen kernel call with zero codegen "
                           "even with no compiler present)"),
                "compilers_found": compilers,
                "cure_priced_not_applied": "VS Build Tools install (~7 GiB disk, free, local) -- "
                                           "material environment mutation, deferred to a post-window "
                                           "coordinator decision; lever stays enumerated with this price"}
    import torch
    try:
        def f(x):
            return ts._zeropower_via_newtonschulz5(x, steps=5)
        torch._dynamo.reset()
        compiled = torch.compile(f, fullgraph=True)
        x = torch.randn(64, 64)
        compiled(x)
        graph_break_count = None
        try:
            graph_break_count = torch._dynamo.explain(f)(x).graph_break_count
        except Exception:
            pass
        return {"lever": "L1_torch_compile", "status": "ok",
                "note": "compiled the real NS5 elementwise+matmul mix, not a bare matmul",
                "compilers_found": compilers, "graph_break_count": graph_break_count}
    except Exception as e:
        return {"lever": "L1_torch_compile", "status": "L1_UNAVAILABLE",
                "reason": f"{type(e).__name__}: {e}", "compilers_found": compilers,
                "traceback_tail": traceback.format_exc()[-1500:]}


# ---------------------------------------------------------------------------
# L2: fresh subprocess per thread setting, randomized/counterbalanced order,
# each worker loads from the SHARED canonical snapshot (zero per-worker disk
# duplication), each worker independently re-verifies the lease token,
# pooled n >= 20 across >= 3 replicates (BLOCK_764_ROUND2 point 5: 3x5=15
# was below floor).
# ---------------------------------------------------------------------------
L2_THREAD_COUNTS = (1, 8, 16, 24, 32)
L2_N_REPLICATES = 4
L2_WORKER_N_WARMUP = 1
L2_WORKER_N_TIMED = 6   # pooled per setting = 4*6 = 24 >= 20 floor


def _l2_worker_run(scale_name: str, threads: int, seed: int, canonical_dir: str, lease_token_path: str) -> dict:
    """Runs inside a FRESH subprocess. Inherits the FULL gate chain the main
    path uses, SAME ORDER: lease token (includes yield-marker via
    server_yielded) -> preflight_gate (commit+physical+disk, computed from
    the SAME manifest the allocation will use) -> abort monitor armed --
    BEFORE any state allocation (BLOCK_764_ROUND3 point 1: lease-only
    validation let an authorized-but-unpreflighted worker allocate the full
    working copy outside the parent's resource gate -- 'lease validation is
    necessary but not the promised token->resource->monitor chain'). threads
    is set BEFORE any tensor work. Prints one JSON line to stdout."""
    scope_key = SCALES[scale_name]["scope_key"]
    lease = check_lease_token(lease_token_path, required_scope=scope_key)
    if not lease["valid"]:
        result = {"threads": threads, "seed": seed, "status": "REFUSED_UNAUTHORIZED", "reason": lease["reason"]}
        print("F1BENCH_L2_WORKER_RESULT " + json.dumps(result), flush=True)
        return result

    with open(Path(canonical_dir) / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    muon_elems = sum(_elems(it["shape"]) for it in manifest["muon"])
    adamw_elems = sum(_elems(it["shape"]) for it in manifest["adamw"])
    required_gib = exact_scale_working_set_gib(muon_elems, adamw_elems)

    preflight = preflight_gate(required_working_set_gib=required_gib, run_dir=canonical_dir)
    if not preflight["sufficient"]:
        result = {"threads": threads, "seed": seed, "status": "REFUSED_PREFLIGHT", "preflight": preflight}
        print("F1BENCH_L2_WORKER_RESULT " + json.dumps(result), flush=True)
        return result
    armed = arm_abort_monitor(canonical_dir)

    import torch
    import psutil
    torch.set_num_threads(threads)
    cfg = ts.load_contract()
    proc = psutil.Process()
    freq = None
    try:
        freq = psutil.cpu_freq()._asdict()
    except Exception:
        pass
    affinity = None
    try:
        affinity = proc.cpu_affinity()
    except Exception:
        pass
    built = build_exact_optimizers_from_canonical(manifest, cfg)   # first allocation -- gated above
    for _ in range(L2_WORKER_N_WARMUP):
        _step_all(built)

    mid_check = check_abort_monitor(armed, run_dir=canonical_dir, required_working_set_gib=required_gib)
    if mid_check["should_abort"]:
        result = {"threads": threads, "seed": seed, "status": "ABORTED_MIDRUN", "reason": mid_check["reason"],
                  "preflight": preflight}
        print("F1BENCH_L2_WORKER_RESULT " + json.dumps(result), flush=True)
        return result

    built = build_exact_optimizers_from_canonical(manifest, cfg)   # fresh fork for the timed portion
    walls = []
    for _ in range(L2_WORKER_N_TIMED):
        t0 = time.perf_counter()
        _step_all(built)
        walls.append(time.perf_counter() - t0)

    final_check = check_abort_monitor(armed, run_dir=canonical_dir, required_working_set_gib=required_gib)
    status = "ABORTED_MIDRUN" if final_check["should_abort"] else "ok"
    result = {"threads": threads, "seed": seed, "status": status, "walls_s": walls,
              "effective_threads": torch.get_num_threads(),
              "cpu_affinity_len": len(affinity) if affinity else None, "cpu_freq": freq,
              "preflight": preflight, "abort_check_final_reason": final_check["reason"]}
    print("F1BENCH_L2_WORKER_RESULT " + json.dumps(result), flush=True)
    return result


def lever_L2_subprocess_sweep(scale_name: str, manifest: dict, lease_token_path: str, *,
                               thread_counts=L2_THREAD_COUNTS, n_replicates: int = L2_N_REPLICATES) -> dict:
    """Orchestrator: verifies its OWN lease token before launching anything;
    launches n_replicates x len(thread_counts) fresh subprocesses in
    RANDOMIZED order, each pointed at the shared canonical snapshot dir
    (zero per-worker state duplication) and required to re-verify the same
    token. Pools samples per thread setting, computes cross-process CI95,
    ranks a setting above the production default only on non-overlapping CI."""
    scope_key = SCALES[scale_name]["scope_key"]
    lease = check_lease_token(lease_token_path, required_scope=scope_key)
    if not lease["valid"]:
        return {"lever": "L2_thread_sweep_subprocess", "status": "REFUSED_UNAUTHORIZED", "reason": lease["reason"]}

    import random
    all_threads = sorted(set(thread_counts) | {PRODUCTION_DEFAULT_THREADS})
    jobs = [(t, rep) for t in all_threads for rep in range(n_replicates)]
    rng = random.Random(1234)
    rng.shuffle(jobs)

    canonical_dir = manifest["dir"]
    pooled = {str(t): [] for t in all_threads}
    per_run = []
    for threads, rep in jobs:
        seed = 100 + rep
        proc = subprocess.run(
            [sys.executable, _THIS_FILE, "--l2-worker", "--scale", scale_name,
             "--threads", str(threads), "--seed", str(seed),
             "--canonical-dir", canonical_dir, "--lease-token", lease_token_path],
            capture_output=True, text=True, timeout=1800)
        line = None
        for out_line in proc.stdout.splitlines():
            if out_line.startswith("F1BENCH_L2_WORKER_RESULT "):
                line = out_line[len("F1BENCH_L2_WORKER_RESULT "):]
        if line is None:
            per_run.append({"threads": threads, "rep": rep, "status": "failed",
                            "returncode": proc.returncode, "stderr_tail": proc.stderr[-1500:]})
            continue
        r = json.loads(line)
        if r.get("status") != "ok":
            per_run.append({"threads": threads, "rep": rep, "status": "failed", "worker_result": r})
            continue
        pooled[str(threads)].extend(r["walls_s"])
        per_run.append({"threads": threads, "rep": rep, "status": "ok", "result": r})

    by_threads = {}
    all_sufficient = True
    for t in all_threads:
        vals = pooled[str(t)]
        ci = _bootstrap_ci95_median(vals) if vals else {"lower": None, "upper": None, "median": None, "n": 0}
        sufficient_n = ci["n"] >= 20
        all_sufficient = all_sufficient and sufficient_n
        by_threads[str(t)] = {"pooled_walls_s": vals, "median_s": ci["median"], "ci95": ci,
                              "sufficient_n": sufficient_n}

    default_ci = by_threads[str(PRODUCTION_DEFAULT_THREADS)]["ci95"]
    for t, row in by_threads.items():
        row["ranks_above_default"] = (
            row["ci95"]["median"] is not None and default_ci["median"] is not None
            and row["ci95"]["upper"] is not None and default_ci["lower"] is not None
            and row["ci95"]["upper"] < default_ci["lower"])

    return {"lever": "L2_thread_sweep_subprocess", "status": "ok" if all_sufficient else "INSUFFICIENT_SAMPLES",
            "production_default_threads": PRODUCTION_DEFAULT_THREADS, "n_replicates": n_replicates,
            "sample_floor": 20, "randomized_job_order": [[t, r] for t, r in jobs],
            "per_run": per_run, "by_threads": by_threads}


# ---------------------------------------------------------------------------
# L3: 2.2B full residency remains a REFUSAL FIXTURE (pure arithmetic).
# L3a: FULL tiled Muon transition over ALL 140 matrices (BLOCK_764_L3A_NOT_
# AN_OPTIMIZER_STEP total rewrite -- round-2's version cloned VALUES and ran
# NS5 alone, never touched grad/momentum/LR/WD/write-back). Every tile
# instantiates the REAL Muon optimizer on its GPU-resident slice (grad +
# momentum transferred from the canonical snapshot, never reimplemented
# math), runs ONE real step, transfers the updated param+momentum back to
# an aggregate CPU buffer, and the FULL aggregate is equivalence-gated
# against an L0 CPU run from the SAME canonical snapshot.
# ---------------------------------------------------------------------------
L3_STATE_BYTES_FULL_2P2B_GIB = 8.545235
L3_MEASURED_PRODUCTION_PEAK_2P2B_GIB = (19.98, 20.04)
L3_CARD_CAPACITY_GIB = 24.0
L3A_TILE_SIZES = (1, 4, 16, 64)


def lever_L3_refusal_fixture_2p2b() -> dict:
    peak_lo, peak_hi = L3_MEASURED_PRODUCTION_PEAK_2P2B_GIB
    total_lo = round(L3_STATE_BYTES_FULL_2P2B_GIB + peak_lo, 3)
    total_hi = round(L3_STATE_BYTES_FULL_2P2B_GIB + peak_hi, 3)
    over_lo = round(total_lo - L3_CARD_CAPACITY_GIB, 3)
    over_hi = round(total_hi - L3_CARD_CAPACITY_GIB, 3)
    return {
        "lever": "L3_full_residency_2p2b", "status": "REFUSED_ANALYTICALLY_INFEASIBLE",
        "muon_state_gib": 7.8125, "adamw_state_gib": 0.732735,
        "combined_state_gib": L3_STATE_BYTES_FULL_2P2B_GIB,
        "measured_production_peak_gib_range": list(L3_MEASURED_PRODUCTION_PEAK_2P2B_GIB),
        "combined_total_gib_range": [total_lo, total_hi],
        "card_capacity_gib": L3_CARD_CAPACITY_GIB,
        "over_capacity_gib_range": [over_lo, over_hi],
        "reason": (f"full GPU-resident Muon state at 2.2B lands at {total_lo}-{total_hi} GiB, "
                   f"{over_lo}-{over_hi} GiB over a 24 GiB card -- refused analytically, no CUDA "
                   "allocation attempted."),
    }


def _partition_tiles(muon_list: list, tile_size: int) -> list:
    """Full coverage: every one of the 140 matrices appears in exactly one
    batch. Never params[:tile_size] (round-2's bug -- silently omitted the
    FF32768 families whenever tile_size < 140)."""
    return [muon_list[i:i + tile_size] for i in range(0, len(muon_list), tile_size)]


_MUON_FAMILIES = {"square_qkvo", "tall_gate_up", "wide_down"}


def _l3a_check_equivalence(l0_pre: list, l0_post: list, l0_pre_momentum: list, l0_post_momentum: list,
                            aggregate_post: dict, aggregate_post_momentum: dict, *, label_suffix: str) -> dict:
    """Independent-copy param+momentum numeric equivalence for one L3a tile
    size, overall AND per Muon shape family, against the L0 CPU reference
    from the SAME canonical snapshot (BLOCK_764_ROUND3 point 2: the prior
    check only asked whether tensor NAMES matched -- 'aggregate_post is not
    read, momentum is not compared at all... a completely corrupted GPU
    transition with the right names reports checked=True'). Uses the SAME
    frozen tolerances as every other equivalence gate in this file
    (compare_transition), never a separate ad hoc predicate."""
    pre_muon = [(it, t) for it, t in l0_pre if it["family"] in _MUON_FAMILIES]
    post_a_muon = [(it, t) for it, t in l0_post if it["family"] in _MUON_FAMILIES]
    post_b_muon = [(it, aggregate_post[it["name"]]) for it, _ in pre_muon]
    param_equiv = compare_transition(pre_muon, post_a_muon, post_b_muon, label=f"L3a_params_{label_suffix}")

    post_b_mom = [(it, aggregate_post_momentum[it["name"]]) for it, _ in l0_pre_momentum]
    momentum_equiv = compare_transition(l0_pre_momentum, l0_post_momentum, post_b_mom,
                                        label=f"L3a_momentum_{label_suffix}")

    per_family_params = {}
    for fam in sorted(_MUON_FAMILIES):
        fp = [(it, t) for it, t in pre_muon if it["family"] == fam]
        fa = [(it, t) for it, t in post_a_muon if it["family"] == fam]
        fb = [(it, t) for it, t in post_b_muon if it["family"] == fam]
        per_family_params[fam] = compare_transition(fp, fa, fb, label=f"L3a_params_{fam}_{label_suffix}")

    passed = (param_equiv["passed"] and momentum_equiv["passed"]
              and all(v["passed"] for v in per_family_params.values()))
    return {"passed": passed, "params": param_equiv, "momentum": momentum_equiv,
            "per_family_params": per_family_params}


def _l3a_aggregate_status(by_tile: dict) -> dict:
    """Pure aggregation, CPU/CUDA-independent, unit-testable in isolation.

    BLOCK_764_ROUND4 point 2: top-level status requires ALL requested tile sizes
    to independently pass -- never any() (one passing tile size previously
    marked the whole lever 'ok' while other tile sizes silently sat skipped,
    failed, or numerically non-equivalent). Also guards the empty-dict
    vacuous-truth case explicitly (all() over an empty iterable is True)."""
    tile_status_summary = {ts_key: v["status"] for ts_key, v in by_tile.items()}
    all_ok = bool(by_tile) and all(v["status"] == "ok" for v in by_tile.values())
    return {"status": "ok" if all_ok else "NOT_ALL_TILES_OK", "tile_status_summary": tile_status_summary}


def lever_L3a_tiled(manifest: dict, cfg: dict, l0_reference_post: list, *,
                     l0_reference_pre: list = None, l0_reference_pre_momentum: list = None,
                     l0_reference_post_momentum: list = None,
                     tile_sizes=L3A_TILE_SIZES, lease_token_path=None, scale_name=None) -> dict:
    """Requires its own CUDA-scoped lease (never implied by a CPU scope).
    For each tile size: partitions ALL 140 Muon matrices into batches,
    and for EACH batch runs the REAL production Muon transition on GPU
    (grad+momentum transferred from canonical, ts._muon_class().step()
    executed on the GPU-resident slice, updated param+momentum transferred
    back) -- never a value-only NS5 proxy. A tile size's status is 'ok'
    ONLY if every tile of that size ran (full_coverage) AND its aggregate
    param+momentum state passes numeric equivalence against the L0 CPU
    reference from the same canonical snapshot -- 'right names, wrong
    numbers' is a non-OK result, never a silent 'ok' (BLOCK_764_ROUND3
    point 2)."""
    lease = check_lease_token(lease_token_path, required_scope="cuda")
    if not lease["valid"]:
        return {"lever": "L3a_tiled_muon", "status": "REFUSED_UNAUTHORIZED", "reason": lease["reason"]}

    try:
        nvsmi = coa.nvidia_smi_vram()
    except Exception as e:
        return {"lever": "L3a_tiled_muon", "status": "skipped",
                "reason": f"nvidia-smi read failed: {type(e).__name__}: {e}"}

    import torch
    muon_list = manifest["muon"]
    if not muon_list:
        return {"lever": "L3a_tiled_muon", "status": "skipped", "reason": "no muon params in manifest"}
    lr_muon = cfg["optimizer"]["lr_muon"]
    wd = cfg["optimizer"]["weight_decay"]
    Muon = ts._muon_class()

    by_tile = {}
    for tile_size in tile_sizes:
        batches = _partition_tiles(muon_list, tile_size)
        max_elems_in_any_tile = max(_elems(it["shape"]) for it in muon_list)
        # generous transient estimate: param+grad+momentum+~2 NS5 working
        # buffers, per matrix in the largest possible tile.
        required_gib = (max_elems_in_any_tile * 4 * 5 * tile_size) / (1024 ** 3)
        margin_floor = 0.5
        free_gib = nvsmi["free_gib"]
        if (free_gib - required_gib) < margin_floor:
            by_tile[str(tile_size)] = {
                "status": "skipped",
                "reason": (f"insufficient free VRAM for tile_size={tile_size}: free={free_gib}GiB, "
                           f"required~={round(required_gib, 3)}GiB + {margin_floor}GiB margin. "
                           "No CUDA op launched."),
                "nvidia_smi_vram": nvsmi, "required_gib": round(required_gib, 3), "n_matrices": len(muon_list)}
            continue

        torch.cuda.reset_peak_memory_stats()
        aggregate_post = {}            # item name -> updated CPU param tensor
        aggregate_post_momentum = {}   # item name -> updated CPU momentum tensor
        h2d_bytes = d2h_bytes = 0
        per_family_wall = {}
        total_wall_s = 0.0
        n_covered = 0
        tile_ok = True
        tile_reason = None
        try:
            for batch in batches:
                torch.cuda.synchronize()   # drain any queued work from the prior batch first
                t0 = time.perf_counter()
                gpu_params = []
                for item in batch:
                    param_cpu = _load_ram_copy(item["param_path"], item["shape"])
                    grad_cpu = _load_readonly_view(item["grad_path"], item["shape"])
                    mom_cpu = _load_ram_copy(item["momentum_path"], item["shape"])
                    gp = torch.nn.Parameter(param_cpu.to("cuda", dtype=torch.float32))
                    gp.grad = grad_cpu.to("cuda", dtype=torch.float32)
                    gpu_params.append((item, gp, mom_cpu.to("cuda", dtype=torch.float32)))
                    h2d_bytes += 3 * _elems(item["shape"]) * 4
                tile_opt = Muon([gp for _, gp, _ in gpu_params], lr=lr_muon, weight_decay=wd)
                for item, gp, mom_gpu in gpu_params:
                    tile_opt.state[gp] = {"momentum_buffer": mom_gpu}
                tile_opt.step()   # REAL production Muon math, on this GPU-resident slice
                torch.cuda.synchronize()   # BLOCK_764_ROUND4: ensures step()'s kernels are
                                            # complete before the D2H write-back below (H2D
                                            # transfers above are already synchronous .to("cuda")
                                            # calls; this closes the one async gap -- step()).
                for item, gp, mom_gpu in gpu_params:
                    aggregate_post[item["name"]] = gp.detach().to("cpu")
                    aggregate_post_momentum[item["name"]] = mom_gpu.detach().to("cpu")
                    d2h_bytes += _elems(item["shape"]) * 4 * 2   # updated param + updated momentum
                    n_covered += 1
                # dt captured AFTER the D2H write-back completes (BLOCK_764_ROUND4_POINT2: dt was
                # previously stopped before gp.to("cpu")/momentum.to("cpu") while the row still
                # counted d2h_bytes and claimed full transition+write-back -- the measured window
                # must span exactly what the row's bytes/claim fields say it spans, never narrower
                # than the claim). .to("cpu") without non_blocking is itself a blocking transfer,
                # so no additional synchronize is needed past this point.
                dt = time.perf_counter() - t0
                # Assign each measured batch interval ONCE (BLOCK_764_ROUND3
                # point 5: the prior version added the full batch dt once per
                # ITEM in the batch, multiplying the same interval by up to
                # tile_size). total_wall_s is the ground truth (sums to
                # exactly the wall clock spent stepping AND writing back);
                # per_family_wall_s is a size-proportional split of dt across
                # the families actually present in a mixed batch, so it sums
                # back to total_wall_s exactly.
                total_wall_s += dt
                batch_family_counts = {}
                for item in batch:
                    batch_family_counts[item["family"]] = batch_family_counts.get(item["family"], 0) + 1
                for fam, cnt in batch_family_counts.items():
                    per_family_wall[fam] = per_family_wall.get(fam, 0.0) + dt * (cnt / len(batch))
                del gpu_params, tile_opt
                torch.cuda.empty_cache()
        except Exception as e:
            tile_ok = False
            tile_reason = f"{type(e).__name__}: {e}"

        peak_alloc = torch.cuda.max_memory_allocated() / (1024 ** 3)
        peak_reserved = torch.cuda.max_memory_reserved() / (1024 ** 3)
        torch.cuda.empty_cache()
        full_coverage = n_covered == len(muon_list)

        equivalence = None
        if tile_ok and full_coverage:
            if l0_reference_pre is None or l0_reference_pre_momentum is None or l0_reference_post_momentum is None:
                equivalence = {"passed": False,
                               "reason": "L0 pre/momentum reference not supplied -- cannot verify, never ok"}
            else:
                equivalence = _l3a_check_equivalence(
                    l0_reference_pre, l0_reference_post, l0_reference_pre_momentum, l0_reference_post_momentum,
                    aggregate_post, aggregate_post_momentum, label_suffix=f"tile{tile_size}")

        by_tile[str(tile_size)] = {
            "status": "ok" if (tile_ok and full_coverage and equivalence is not None and equivalence["passed"]) else "non_ok",
            "tile_reason": tile_reason,
            "n_matrices_total": len(muon_list), "n_matrices_covered": n_covered, "full_coverage": full_coverage,
            "n_tiles": len(batches),
            "h2d_bytes": h2d_bytes, "d2h_bytes": d2h_bytes,
            "total_wall_s": round(total_wall_s, 6), "per_family_wall_s": per_family_wall,
            "peak_allocated_gib": round(peak_alloc, 4), "peak_reserved_gib": round(peak_reserved, 4),
            "nvidia_smi_vram_before": nvsmi, "equivalence": equivalence,
        }

    agg = _l3a_aggregate_status(by_tile)
    return {"lever": "L3a_tiled_muon", "status": agg["status"],
            "tile_status_summary": agg["tile_status_summary"],
            "by_tile_size": by_tile,
            "design": ("full production Muon transition per tile (grad+momentum transfer, real "
                       "ts._muon_class().step(), param+momentum write-back) over ALL 140 matrices "
                       "partitioned into batches -- never a value-only NS5 proxy, never params[:tile_size]. "
                       "status='ok' requires ALL requested tile_sizes to independently pass "
                       "(tile_status_summary discloses every tile size's individual verdict).")}


def lever_L3_positive_control_434m(manifest: dict, cfg: dict, *, lease_token_path=None) -> dict:
    lease = check_lease_token(lease_token_path, required_scope="cuda")
    if not lease["valid"]:
        return {"lever": "L3_full_residency_434m_positive_control", "status": "REFUSED_UNAUTHORIZED",
                "reason": lease["reason"]}
    try:
        nvsmi = coa.nvidia_smi_vram()
    except Exception as e:
        return {"lever": "L3_full_residency_434m_positive_control", "status": "skipped",
                "reason": f"nvidia-smi read failed: {type(e).__name__}: {e}"}
    muon_list = manifest["muon"]
    n_elems = sum(_elems(it["shape"]) for it in muon_list)
    required_gib = (n_elems * 4 * 3) / (1024 ** 3)
    free_gib = nvsmi["free_gib"]
    if (free_gib - required_gib) < 0.5:
        return {"lever": "L3_full_residency_434m_positive_control", "status": "skipped",
                "reason": f"insufficient free VRAM: free={free_gib}GiB, required~={round(required_gib, 3)}GiB",
                "nvidia_smi_vram": nvsmi, "required_gib": round(required_gib, 3)}
    import torch
    Muon = ts._muon_class()
    torch.cuda.reset_peak_memory_stats()
    gpu_params = []
    for item in muon_list:
        gp = torch.nn.Parameter(_load_ram_copy(item["param_path"], item["shape"]).to("cuda", dtype=torch.float32))
        gp.grad = _load_readonly_view(item["grad_path"], item["shape"]).to("cuda", dtype=torch.float32)
        gpu_params.append((item, gp))
    gpu_opt = Muon([gp for _, gp in gpu_params], lr=cfg["optimizer"]["lr_muon"], weight_decay=cfg["optimizer"]["weight_decay"])
    for item, gp in gpu_params:
        mom = _load_ram_copy(item["momentum_path"], item["shape"]).to("cuda", dtype=torch.float32)
        gpu_opt.state[gp] = {"momentum_buffer": mom}
    for _ in range(N_WARMUP):
        gpu_opt.step()
    torch.cuda.synchronize()
    walls = []
    for _ in range(N_TIMED):
        torch.cuda.synchronize(); t0 = time.perf_counter()
        gpu_opt.step()
        torch.cuda.synchronize()
        walls.append(time.perf_counter() - t0)
    peak = torch.cuda.max_memory_allocated() / (1024 ** 3)
    ci = _bootstrap_ci95_median(walls)
    torch.cuda.empty_cache()
    return {"lever": "L3_full_residency_434m_positive_control", "status": "ok",
            "walls_s": walls, "median_s": ci["median"], "ci95": ci, "peak_vram_allocated_gib": round(peak, 3)}


# ---------------------------------------------------------------------------
# Amdahl kill math -- explicit per-lever verdict, kills subcritical levers.
# ---------------------------------------------------------------------------
INNER_FRAC_LOW = 0.935
INNER_FRAC_HIGH = 0.941
MAJOR_REDUCTION_E2E_TARGET = 2.0


def amdahl_kill(inner_speedup: float, *, lever_label: str = "") -> dict:
    results = {}
    for label, f in (("low_f", INNER_FRAC_LOW), ("high_f", INNER_FRAC_HIGH)):
        denom = (1.0 / MAJOR_REDUCTION_E2E_TARGET) - (1.0 - f)
        required_inner_speedup = (f / denom) if denom > 0 else float("inf")
        e2e_speedup = 1.0 / ((1 - f) + f / inner_speedup) if inner_speedup > 0 else 0.0
        meets_bar = e2e_speedup >= MAJOR_REDUCTION_E2E_TARGET
        results[label] = {"inner_frac": f, "required_inner_speedup_for_2x_e2e": round(required_inner_speedup, 4),
                          "given_inner_speedup": round(inner_speedup, 4), "implied_e2e_speedup": round(e2e_speedup, 4),
                          "meets_major_reduction_bar": meets_bar,
                          "verdict": "MEETS_2X_E2E_BAR" if meets_bar else "SUBCRITICAL_KILLED"}
    results["lever"] = lever_label
    results["overall_verdict"] = ("MEETS_2X_E2E_BAR" if all(results[k]["meets_major_reduction_bar"]
                                                             for k in ("low_f", "high_f")) else "SUBCRITICAL_KILLED")
    return results


# ---------------------------------------------------------------------------
# Negative fixtures + selftest (fixture scale). Now exercises the --live
# boundary itself (lease-token chain), per BLOCK_764_LIVE_ENTRYPOINT_UNGOVERNED
# and BLOCK_764_ROUND2's explicit complaint that round-2's green selftest
# never exercised that boundary.
# ---------------------------------------------------------------------------
def _tiny_real_cfg() -> dict:
    return {"model": {"hidden": 32, "layers": 2, "heads": 2, "vocab": 64, "seq": 16,
                      "tied_embeddings": True, "grad_checkpointing": False},
            "objective": {"mtp_aux_heads": {"n_heads": 1}},
            "optimizer": {"lr_muon": 0.02, "lr_adamw": 0.0003, "weight_decay": 0.1}}


def _selftest_shapes_bound_pass() -> bool:
    r2 = assert_shape_list_identity(FF_GROWN_2P2B, SCALES["2.2B"])
    r4 = assert_shape_list_identity(FF_BASE_434M, SCALES["434M"])
    ok = (r2["totals"]["muon_elems_total"] == REF_2P2B_MUON_STATE_ELEMS
          and r4["totals"]["muon_elems_total"] == REF_434M_MUON_STATE_ELEMS
          and r2["totals"]["adamw_elems_total"] == REF_ADAMW_PARAM_ELEMS == r4["totals"]["adamw_elems_total"]
          and r2["totals"]["adamw_elems_total"] * 2 + REF_N_ADAMW == REF_ADAMW_STATE_ELEMS)
    bad_list = list(build_muon_shape_list(FF_GROWN_2P2B))
    bad_list[0] = dict(bad_list[0], shape=(1, 1))
    bad_totals = shape_list_totals(bad_list, build_adamw_shape_list())
    negative_ok = bad_totals["muon_elems_total"] != REF_2P2B_MUON_STATE_ELEMS
    total_flop = sum(ns5_flops(*it["shape"]) for it in r2["muon_list"])
    roofline_ok = abs(total_flop / 1e12 - COMPUTE_ROOFLINE_2P2B_TFLOP) < 1e-6
    return ok and negative_ok and roofline_ok


def _selftest_lease_token_boundary(tmp: Path) -> bool:
    """Proves the --live/--l2-worker/CUDA boundary itself refuses on:
    missing token, malformed token, expired token, future-dated token,
    wrong scope, missing server_yielded for a yield-requiring scope; and
    passes on a fresh well-scoped token. This is the leg BLOCK_764_ROUND2
    explicitly flagged as never exercised by round-2's selftest."""
    import datetime as dtmod
    now = datetime.now(timezone.utc)

    def _iso(dt):
        return dt.isoformat().replace("+00:00", "Z")

    if check_lease_token(None, required_scope="434M-cpu")["valid"] is not False:
        return False
    if check_lease_token(str(tmp / "nope.json"), required_scope="434M-cpu")["valid"] is not False:
        return False

    malformed = tmp / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    if check_lease_token(str(malformed), required_scope="434M-cpu")["valid"] is not False:
        return False

    def _write(path, **fields):
        path.write_text(json.dumps(fields), encoding="utf-8")

    expired = tmp / "expired.json"
    _write(expired, issued_by="team-lead", ts=_iso(now - dtmod.timedelta(hours=5)),
           expiry=_iso(now - dtmod.timedelta(hours=1)), scope=["434M-cpu"])
    if check_lease_token(str(expired), required_scope="434M-cpu")["valid"] is not False:
        return False

    future = tmp / "future.json"
    _write(future, issued_by="team-lead", ts=_iso(now + dtmod.timedelta(hours=1)),
           expiry=_iso(now + dtmod.timedelta(hours=2)), scope=["434M-cpu"])
    if check_lease_token(str(future), required_scope="434M-cpu")["valid"] is not False:
        return False

    wrong_scope = tmp / "wrong_scope.json"
    _write(wrong_scope, issued_by="team-lead", ts=_iso(now), expiry=_iso(now + dtmod.timedelta(hours=1)),
           scope=["2.2B-cpu"])
    if check_lease_token(str(wrong_scope), required_scope="434M-cpu")["valid"] is not False:
        return False

    yield_scope_no_flag = tmp / "yield_no_flag.json"
    _write(yield_scope_no_flag, issued_by="team-lead", ts=_iso(now),
           expiry=_iso(now + dtmod.timedelta(hours=1)), scope=["2.2B-cpu"], server_yielded=False)
    if check_lease_token(str(yield_scope_no_flag), required_scope="2.2B-cpu")["valid"] is not False:
        return False

    good_cpu = tmp / "good_cpu.json"
    _write(good_cpu, issued_by="team-lead", ts=_iso(now), expiry=_iso(now + dtmod.timedelta(hours=1)),
           scope=["434M-cpu"])
    if check_lease_token(str(good_cpu), required_scope="434M-cpu")["valid"] is not True:
        return False

    good_yield = tmp / "good_yield.json"
    _write(good_yield, issued_by="team-lead", ts=_iso(now), expiry=_iso(now + dtmod.timedelta(hours=1)),
           scope=["2.2B-cpu", "cuda"], server_yielded=True)
    if check_lease_token(str(good_yield), required_scope="2.2B-cpu")["valid"] is not True:
        return False
    if check_lease_token(str(good_yield), required_scope="cuda")["valid"] is not True:
        return False
    if check_lease_token(str(good_cpu), required_scope="cuda")["valid"] is not False:
        return False   # a CPU-only good token must NOT authorize cuda

    l2_result = lever_L2_subprocess_sweep("434M", {"dir": str(tmp / "nonexistent-canonical")}, None)
    if l2_result.get("status") != "REFUSED_UNAUTHORIZED":
        return False
    return True


def _selftest_governance_boundary(tmp: Path) -> bool:
    huge_preflight = preflight_gate(required_working_set_gib=1_000_000.0, run_dir=str(tmp))
    if huge_preflight["sufficient"] is not False:
        return False
    tiny_preflight = preflight_gate(required_working_set_gib=0.001, run_dir=str(tmp))
    if tiny_preflight["sufficient"] is not True:
        return False
    armed = arm_abort_monitor(str(tmp))
    check = check_abort_monitor(armed, run_dir=str(tmp), required_working_set_gib=1_000_000.0)
    if check["should_abort"] is not True:
        return False
    # commit_floor_gib/disk_floor_gib pinned trivially-low here: this is the
    # ORIGINAL physical-margin happy-path check, and this box is shared
    # across concurrent sessions whose commit usage can transiently swing by
    # double-digit GiB between two calls a few lines apart -- pinning keeps
    # this specific assertion about physical margin only. The commit/disk
    # floors get their OWN dedicated forced-positive tests immediately below.
    check2 = check_abort_monitor(armed, run_dir=str(tmp), required_working_set_gib=0.001,
                                 commit_floor_gib=0.001, disk_floor_gib=0.001)
    if check2["should_abort"] is not False:
        return False

    # commit-margin and disk-margin must be independently ENFORCED, not just
    # recorded (BLOCK_764_ROUND3 point 4: round-3's first cut recorded disk
    # and page-fault deltas but only ever aborted on physical margin).
    # Forcing each floor to an unattainable value isolates that exact leg
    # regardless of this box's live memory/disk state.
    commit_forced = check_abort_monitor(armed, run_dir=str(tmp), required_working_set_gib=0.001,
                                        commit_floor_gib=1_000_000.0)
    if commit_forced["should_abort"] is not True:
        return False
    disk_forced = check_abort_monitor(armed, run_dir=str(tmp), required_working_set_gib=0.001,
                                      disk_floor_gib=1_000_000.0)
    if disk_forced["should_abort"] is not True:
        return False

    # page-fault-rate and disk-I/O-rate are only ENFORCED once the sampling
    # window clears RATE_CHECK_MIN_ELAPSED_S -- simulate elapsed time by
    # backdating the armed baseline's monotonic clock (deterministic, no
    # sleep). Floors of -1 guarantee ANY measured rate (>=0) trips them.
    # commit_floor_gib/disk_floor_gib pinned trivially-low again to isolate
    # exactly the mechanism under test (the rate branches) from this box's
    # live, volatile commit margin -- see the comment on check2 above.
    rate_armed = dict(armed)
    rate_armed["armed_at_monotonic"] = armed["armed_at_monotonic"] - (RATE_CHECK_MIN_ELAPSED_S + 5.0)
    pf_forced = check_abort_monitor(rate_armed, run_dir=str(tmp), required_working_set_gib=0.001,
                                    commit_floor_gib=0.001, disk_floor_gib=0.001,
                                    page_fault_rate_abort_per_s=-1.0)
    if pf_forced["should_abort"] is not True or pf_forced["rate_window_sufficient"] is not True:
        return False
    io_forced = check_abort_monitor(rate_armed, run_dir=str(tmp), required_working_set_gib=0.001,
                                    commit_floor_gib=0.001, disk_floor_gib=0.001,
                                    disk_io_rate_abort_mbps=-1.0)
    if io_forced["should_abort"] is not True or io_forced["rate_window_sufficient"] is not True:
        return False
    # and confirm the window guard itself: an immediate re-check (no
    # backdating) must NOT enforce a rate floor even when forced to -1.
    immediate = check_abort_monitor(armed, run_dir=str(tmp), required_working_set_gib=0.001,
                                    commit_floor_gib=0.001, disk_floor_gib=0.001,
                                    page_fault_rate_abort_per_s=-1.0, disk_io_rate_abort_mbps=-1.0)
    if immediate["rate_window_sufficient"] is not False or immediate["should_abort"] is not False:
        return False

    auth_off = os.environ.pop("EMBER_GATE_AUTHORIZED", None)
    auth = check_authorization()
    if auth["env_authorized"] is not False:
        if auth_off is not None:
            os.environ["EMBER_GATE_AUTHORIZED"] = auth_off
        return False
    if auth_off is not None:
        os.environ["EMBER_GATE_AUTHORIZED"] = auth_off
    return True


def _selftest_l3a_equivalence_numeric() -> bool:
    """CPU-only, CUDA-free unit test of _l3a_check_equivalence
    (BLOCK_764_ROUND3 point 2): proves the L3a equivalence gate does REAL
    numeric param+momentum comparison, not the prior name-only check --
    an honest candidate passes; a param-corrupted candidate fails; a
    momentum-corrupted candidate (with honest params) ALSO independently
    fails. This is exactly the gap a checked=all(name in ...) predicate
    hid: 'a completely corrupted GPU transition with the right names
    reports checked=True'."""
    import torch
    items = [
        {"name": "m0", "family": "square_qkvo", "shape": (2, 2)},
        {"name": "m1", "family": "tall_gate_up", "shape": (3, 2)},
        {"name": "m2", "family": "wide_down", "shape": (2, 3)},
    ]
    g = torch.Generator().manual_seed(11)
    pre = [(it, torch.randn(it["shape"], generator=g)) for it in items]
    post = [(it, p + torch.randn(it["shape"], generator=g) * 0.01) for it, p in pre]
    pre_mom = [(it, torch.randn(it["shape"], generator=g) * 0.1) for it in items]
    post_mom = [(it, m + torch.randn(it["shape"], generator=g) * 0.01) for it, m in pre_mom]

    honest_agg = {it["name"]: t.clone() for it, t in post}
    honest_agg_mom = {it["name"]: t.clone() for it, t in post_mom}
    honest = _l3a_check_equivalence(pre, post, pre_mom, post_mom, honest_agg, honest_agg_mom,
                                    label_suffix="selftest")
    if honest["passed"] is not True:
        return False

    corrupt_param_agg = dict(honest_agg)
    corrupt_param_agg["m1"] = corrupt_param_agg["m1"] + 1000.0
    bad_param = _l3a_check_equivalence(pre, post, pre_mom, post_mom, corrupt_param_agg, honest_agg_mom,
                                       label_suffix="selftest-badparam")
    if bad_param["passed"] is not False:
        return False

    corrupt_mom_agg = dict(honest_agg_mom)
    corrupt_mom_agg["m2"] = corrupt_mom_agg["m2"] + 1000.0
    bad_mom = _l3a_check_equivalence(pre, post, pre_mom, post_mom, honest_agg, corrupt_mom_agg,
                                     label_suffix="selftest-badmom")
    if bad_mom["passed"] is not False:
        return False
    if bad_mom["params"]["passed"] is not True:   # params were honest -- only momentum was corrupted
        return False

    return True


def _selftest_equivalence_gate_corruption_fails(tmp: Path) -> bool:
    """Uses the SAME canonical-snapshot architecture the live path uses, at
    fixture scale (n_layers=2, hidden=32, vocab=64 -- intermediate=64 is not
    a registered production scale, so build_canonical_snapshot takes the
    fixture branch, no identity check, fast). Proves: (a) an honest
    comparison of two independent loads from the same canonical snapshot
    PASSES, (b) a corrupted comparison FAILS."""
    cfg = _tiny_real_cfg()
    manifest = build_canonical_snapshot(64, tmp / "equiv-canon", seed=7, n_layers=2, hidden=32, vocab=64)

    built_ref = build_exact_optimizers_from_canonical(manifest, cfg)
    ref_params = built_ref["muon_params"] + built_ref["adamw_params"]
    pre_snapshot = [(it, t.detach().clone()) for it, t in ref_params]
    _step_all(built_ref)
    ref_post = ref_params

    built_cand = build_exact_optimizers_from_canonical(manifest, cfg)
    cand_params = built_cand["muon_params"] + built_cand["adamw_params"]
    if _custody_hash(cand_params) != _custody_hash(pre_snapshot):
        return False   # identical canonical load must reproduce identical pre-step values
    _step_all(built_cand)
    cand_post = cand_params

    honest = compare_transition(pre_snapshot, ref_post, cand_post, label="honest")
    if honest["passed"] is not True:
        return False

    corrupted = [(it, t.clone()) for it, t in cand_post]
    corrupted[0] = (corrupted[0][0], corrupted[0][1] + 1000.0)
    bad = compare_transition(pre_snapshot, ref_post, corrupted, label="corrupted")
    return bad["passed"] is False


def _selftest_l3a_tile_partition_covers_all() -> bool:
    """CUDA-free logic check (never touches CUDA in a selftest): the tile
    partitioner covers every one of the 140 matrices exactly once, for
    every tile size in L3A_TILE_SIZES -- proves round-2's params[:tile_size]
    bug (silent partial coverage) cannot recur."""
    muon_list = build_muon_shape_list(FF_GROWN_2P2B)
    if len(muon_list) != REF_N_MUON:
        return False
    for tile_size in L3A_TILE_SIZES:
        batches = _partition_tiles(muon_list, tile_size)
        covered_names = [it["name"] for batch in batches for it in batch]
        if sorted(covered_names) != sorted(it["name"] for it in muon_list):
            return False
        if len(covered_names) != len(set(covered_names)):
            return False
    return True


def _selftest_l3a_aggregate_status_hardened() -> bool:
    """CUDA-free logic check of _l3a_aggregate_status (BLOCK_764_ROUND4 point 2):
    proves the any()->all() fix and the empty-dict vacuous-truth guard, using
    fabricated by_tile shapes -- never touches CUDA."""
    all_pass = {"1": {"status": "ok"}, "4": {"status": "ok"}, "16": {"status": "ok"}}
    r_all = _l3a_aggregate_status(all_pass)
    if r_all["status"] != "ok":
        return False

    one_bad = {"1": {"status": "ok"}, "4": {"status": "non_ok"}, "16": {"status": "ok"}}
    r_one_bad = _l3a_aggregate_status(one_bad)
    # This is the exact defect class: one passing tile size must NEVER mask
    # another tile size's failure into a top-level "ok".
    if r_one_bad["status"] == "ok":
        return False
    if r_one_bad["tile_status_summary"] != {"1": "ok", "4": "non_ok", "16": "ok"}:
        return False

    all_skipped = {"1": {"status": "skipped"}, "4": {"status": "skipped"}}
    r_all_skipped = _l3a_aggregate_status(all_skipped)
    if r_all_skipped["status"] == "ok":
        return False

    # Vacuous-truth guard: all() over an empty iterable is True -- an empty
    # by_tile (e.g. tile_sizes=() misconfiguration) must never read "ok".
    r_empty = _l3a_aggregate_status({})
    if r_empty["status"] == "ok":
        return False

    return True


def _selftest_l0_production_wrapper_roundtrip(tmp: Path) -> bool:
    """Separately proves the REAL CPUOffloadOptimizer wrapper (production's
    actual code path) still round-trips end to end on a tiny real model."""
    import torch
    adam_params, muon_params, adam, muon = native._build_tiny_production_optimizers(tmp / "wrapper-check")
    params = adam_params + muon_params
    g = torch.Generator().manual_seed(3)
    for _, p in params:
        p.grad = torch.randn(tuple(p.shape), generator=g, dtype=torch.float32)
    for key, opt in (("adamw", adam), ("muon", muon)):
        if not isinstance(opt, coa.CPUOffloadOptimizer):
            return False
        if key == "adamw" and not isinstance(opt._inner, torch.optim.Adam):
            return False
        if key == "muon" and opt._inner.__class__ is not native._muon_class():
            return False
    for opt in (adam, muon):
        opt.step()
    return True


def _run_selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="f1bench-selftest-"))
    results = {}
    ok = True
    for marker, fn in (
        ("F1BENCH_SHAPES_BOUND_PASS", lambda: _selftest_shapes_bound_pass()),
        ("F1BENCH_L0_PRODUCTION_PATH_PASS", lambda: _selftest_l0_production_wrapper_roundtrip(tmp)),
        ("F1BENCH_GOVERNANCE_BOUNDARY_PASS", lambda: _selftest_governance_boundary(tmp)),
        ("F1BENCH_LEASE_TOKEN_BOUNDARY_PASS", lambda: _selftest_lease_token_boundary(tmp)),
        ("F1BENCH_EQUIVALENCE_GATE_CORRUPTION_DETECTED", lambda: _selftest_equivalence_gate_corruption_fails(tmp)),
        ("F1BENCH_L3A_TILE_PARTITION_COVERS_ALL", lambda: _selftest_l3a_tile_partition_covers_all()),
        ("F1BENCH_L3A_EQUIVALENCE_NUMERIC_PASS", lambda: _selftest_l3a_equivalence_numeric()),
        ("F1BENCH_L3A_AGGREGATE_STATUS_HARDENED", lambda: _selftest_l3a_aggregate_status_hardened()),
    ):
        try:
            r = fn()
            results[marker] = r
            ok = ok and bool(r)
        except Exception as e:
            results[marker] = f"EXCEPTION: {type(e).__name__}: {e}\n{traceback.format_exc()[-1000:]}"
            ok = False
    results["F1BENCH_NEGATIVE_FIXTURES_PASS"] = (
        results["F1BENCH_EQUIVALENCE_GATE_CORRUPTION_DETECTED"] is True
        and results["F1BENCH_GOVERNANCE_BOUNDARY_PASS"] is True
        and results["F1BENCH_LEASE_TOKEN_BOUNDARY_PASS"] is True
        and results["F1BENCH_L3A_EQUIVALENCE_NUMERIC_PASS"] is True
        and results["F1BENCH_L3A_AGGREGATE_STATUS_HARDENED"] is True)

    for marker, passed in results.items():
        print(f"{marker} {'PASS' if passed is True else f'FAIL ({passed})'}", flush=True)
    print("F1BENCH_SELFTEST_ALL_PASS" if ok else "F1BENCH_SELFTEST_FAILED", flush=True)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Live orchestration
# ---------------------------------------------------------------------------
def run_scale_live(scale_name: str, cfg: dict, run_dir: Path, *, lease_token_path: str) -> dict:
    scale_cfg = SCALES[scale_name]
    intermediate = scale_cfg["intermediate"]
    scope_key = scale_cfg["scope_key"]

    lease = check_lease_token(lease_token_path, required_scope=scope_key)
    result = {"scale": scale_name, "intermediate": intermediate, "lease_check": lease}
    if not lease["valid"]:
        result["status"] = "REFUSED_UNAUTHORIZED"
        if scale_name == "2.2B":
            result["L3"] = lever_L3_refusal_fixture_2p2b()
        return result

    identity = assert_shape_list_identity(intermediate, scale_cfg)
    working_set_gib = exact_scale_working_set_gib(
        identity["totals"]["muon_elems_total"], identity["totals"]["adamw_elems_total"])
    result["shape_identity"] = identity["totals"]
    result["working_set_gib"] = working_set_gib

    preflight = preflight_gate(required_working_set_gib=working_set_gib, run_dir=str(run_dir))
    result["preflight"] = preflight
    if not preflight["sufficient"]:
        result["status"] = "REFUSED_PREFLIGHT"
        if scale_name == "2.2B":
            result["L3"] = lever_L3_refusal_fixture_2p2b()
        return result

    armed = arm_abort_monitor(str(run_dir))
    result["abort_monitor_armed_at"] = armed["armed_at"]
    result["telemetry_baseline"] = {"mem": armed["baseline_mem"], "page_faults": armed["baseline_page_faults"]}

    print(f"F1BENCH scale={scale_name} preflight PASS, working_set={working_set_gib}GiB", flush=True)
    print(f"F1BENCH scale={scale_name} building canonical snapshot (ONE copy, never mutated again)...", flush=True)
    manifest = build_canonical_snapshot(intermediate, run_dir, seed=0)
    manifest_path = Path(manifest["dir"]) / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    mid_check = check_abort_monitor(armed, run_dir=str(run_dir), required_working_set_gib=working_set_gib)
    result["abort_check_post_canonical"] = mid_check
    if mid_check["should_abort"]:
        result["status"] = "ABORTED_MIDRUN"
        result["abort_reason"] = mid_check["reason"]
        return result

    legs_ok = []

    print(f"F1BENCH scale={scale_name} roofline calibration...", flush=True)
    bw_calib = calibrate_bandwidth()
    cp_calib = calibrate_compute()
    result["roofline_calibration"] = {"bandwidth": bw_calib, "compute": cp_calib}

    print(f"F1BENCH scale={scale_name} L0...", flush=True)
    # BLOCK_764_ROUND4 point 4 (contamination-adjudication instrument): every
    # timed leg gets its own start_ts/end_ts UTC wall-clock stamp so a shared-
    # box contamination window can be adjudicated leg-by-leg against the
    # receipt alone, without needing the stdout log's line order as a proxy.
    l0_start_ts = _ts()
    l0 = lever_L0(manifest, cfg)
    l0_end_ts = _ts()
    result["L0"] = {k: v for k, v in l0.items() if k not in ("pre_params", "post_params", "pre_momentum", "post_momentum")}
    result["L0"]["wall_clock"] = {"start_ts": l0_start_ts, "end_ts": l0_end_ts}
    print(f"F1BENCH scale={scale_name} L0_median_s={l0['median_s']}", flush=True)

    l0_repeat_start_ts = _ts()
    l0_repeat = lever_L0(manifest, cfg)
    l0_repeat_end_ts = _ts()
    determinism_ci_overlap = _ci_overlap(l0["ci95"], l0_repeat["ci95"])
    result["L0_determinism_check"] = {"ci_overlap": determinism_ci_overlap, "l0_repeat_median_s": l0_repeat["median_s"],
                                       "wall_clock": {"start_ts": l0_repeat_start_ts, "end_ts": l0_repeat_end_ts}}
    legs_ok.append(determinism_ci_overlap)

    equiv = compare_transition(l0["pre_params"], l0["post_params"], l0_repeat["post_params"], label="L0_vs_L0_repeat")
    result["transition_equivalence_L0_repeat"] = equiv
    legs_ok.append(equiv["passed"])

    per_family = {}
    all_items = identity["muon_list"] + identity["adamw_list"]
    families = sorted(set(it["family"] for it in all_items))
    for fam in families:
        fam_muon = [it for it in identity["muon_list"] if it["family"] == fam]
        fam_flop = sum(ns5_flops(*it["shape"]) for it in fam_muon)
        fam_elems = sum(_elems(it["shape"]) for it in
                        (fam_muon + [it for it in identity["adamw_list"] if it["family"] == fam]))
        if fam_elems == 0:
            continue
        fam_start_ts = _ts()
        fam_result = lever_L0(manifest, cfg, only_families={fam})
        fam_end_ts = _ts()
        ci = fam_result["ci95"]
        achieved_tflops = (fam_flop / ci["median"] / 1e12) if (fam_flop and ci["median"]) else None
        per_family[fam] = {"count": len([it for it in all_items if it["family"] == fam]), "iterations": N_TIMED,
                           "median_wall_s": ci["median"], "ci95": ci,
                           "effective_elems_per_s": round(fam_elems / ci["median"], 1) if ci["median"] else None,
                           "family_elems_total": fam_elems, "family_ns5_gflop": round(fam_flop / 1e9, 6) if fam_flop else 0,
                           "achieved_tflops": round(achieved_tflops, 4) if achieved_tflops else None,
                           "wall_clock": {"start_ts": fam_start_ts, "end_ts": fam_end_ts}}
        gc.collect()
    result["per_shape_family"] = per_family

    print(f"F1BENCH scale={scale_name} L1 disposition...", flush=True)
    l1_start_ts = _ts()
    result["L1"] = lever_L1_disposition()
    result["L1"]["wall_clock"] = {"start_ts": l1_start_ts, "end_ts": _ts()}

    print(f"F1BENCH scale={scale_name} L2 (subprocess sweep, this can take a while)...", flush=True)
    l2_start_ts = _ts()
    l2 = lever_L2_subprocess_sweep(scale_name, manifest, lease_token_path)
    l2["wall_clock"] = {"start_ts": l2_start_ts, "end_ts": _ts()}
    result["L2"] = l2
    legs_ok.append(l2.get("status") == "ok")

    if scale_name == "2.2B":
        result["L3"] = lever_L3_refusal_fixture_2p2b()
    else:
        l3pc_start_ts = _ts()
        result["L3_positive_control"] = lever_L3_positive_control_434m(manifest, cfg, lease_token_path=lease_token_path)
        result["L3_positive_control"]["wall_clock"] = {"start_ts": l3pc_start_ts, "end_ts": _ts()}
    l3a_start_ts = _ts()
    l3a = lever_L3a_tiled(manifest, cfg, l0["post_params"],
                         l0_reference_pre=l0["pre_params"], l0_reference_pre_momentum=l0["pre_momentum"],
                         l0_reference_post_momentum=l0["post_momentum"],
                         lease_token_path=lease_token_path, scale_name=scale_name)
    l3a["wall_clock"] = {"start_ts": l3a_start_ts, "end_ts": _ts()}
    result["L3a_tiled"] = l3a
    # L3a is BINDING on run status whenever it was actually attempted with a
    # valid CUDA lease (BLOCK_764_ROUND3 point 3: 'run_scale_live.status can
    # be OK when every L3a tile is skipped, fails, or produces wrong
    # parameter/momentum state' -- legs_ok never appended it at all). A CPU-
    # only run with no CUDA lease legitimately does not attempt L3a; that
    # REFUSED_UNAUTHORIZED disposition is disclosed via L3a_binding=False and
    # does not itself block CPU-leg OK status.
    l3a_binding = l3a.get("status") != "REFUSED_UNAUTHORIZED"
    result["L3a_binding"] = l3a_binding
    if l3a_binding:
        legs_ok.append(l3a.get("status") == "ok")

    ns5_flop_total = sum(ns5_flops(*it["shape"]) for it in identity["muon_list"])
    result["ns5_flop_total_tflop"] = round(ns5_flop_total / 1e12, 10)
    if scale_name == "2.2B":
        result["compute_roofline_crosscheck"] = {
            "computed_tflop": round(ns5_flop_total / 1e12, 10),
            "reference_tflop": COMPUTE_ROOFLINE_2P2B_TFLOP,
            "matches": abs(ns5_flop_total / 1e12 - COMPUTE_ROOFLINE_2P2B_TFLOP) < 1e-6}
    roofline = roofline_sanity_check(
        elems_touched=identity["totals"]["muon_elems_total"] + identity["totals"]["adamw_elems_total"],
        measured_time_s=l0["median_s"], flop_total=ns5_flop_total, bandwidth_calib=bw_calib, compute_calib=cp_calib)
    result["roofline_sanity"] = roofline
    legs_ok.append(roofline["passed"])

    if l0["median_s"] and l0["median_s"] > 0:
        result["amdahl_L0_baseline"] = amdahl_kill(inner_speedup=1.0, lever_label="L0_baseline")
        if l2.get("status") == "ok":
            default_median = l2["by_threads"].get(str(PRODUCTION_DEFAULT_THREADS), {}).get("median_s")
            for t_str, row in l2["by_threads"].items():
                if row["median_s"] and default_median:
                    inner_speedup = default_median / row["median_s"]
                    row["amdahl_kill"] = amdahl_kill(inner_speedup=inner_speedup, lever_label=f"L2_threads_{t_str}")

    final_check = check_abort_monitor(armed, run_dir=str(run_dir), required_working_set_gib=working_set_gib)
    result["telemetry_final"] = final_check
    if final_check["should_abort"]:
        result["status"] = "ABORTED_MIDRUN"
        result["abort_reason"] = final_check["reason"]
        return result

    # status is the AND of every required leg -- BLOCK_764_ROUND2 point 4:
    # round-2 set status="OK" unconditionally.
    result["status"] = "OK" if all(legs_ok) else "PARTIAL_FAIL"
    result["legs_ok_detail"] = legs_ok
    del l0, l0_repeat
    gc.collect()
    return result


def _build_receipt(results: dict, run_ts: str) -> dict:
    return {
        "ticket": "EMBER-764-FACTOR1-LEVER-MICROBENCH-R3",
        "ts": run_ts,
        "issue": "wordingone/ember#764",
        "adopted_contract": ["#764 body", "AMENDMENT-1", "AMENDMENT-2", "AMENDMENT-3", "AMENDMENT-4",
                             "BLOCK_764_CANDIDATE_ROUND1 (4943207305)", "BLOCK_764_LIVE_ENTRYPOINT_UNGOVERNED (4943223089)",
                             "BLOCK_764_ROUND2 (4943386132)", "BLOCK_764_L3A_NOT_AN_OPTIMIZER_STEP (4943419393)",
                             "coordinator --lease-token addendum", "coordinator lease ruling (b-now/a-scheduled)"],
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": ("invariant_sha256 is the fixed constitutional invariant hash "
                           "(genesis-entrenched, issue #281) copied verbatim from "
                           "receipt_check.INVARIANT_SHA256, never a locally-computed content "
                           "hash; no other sha256-bearing field exists in this receipt"),
        "n_scales": len(results),
        "value_independence_disclosure": (
            "Every canonical shadow/grad/state tensor is populated with fixed-seed "
            "(torch.Generator, seed=0) random FP32 values in bounded chunks, never real "
            "trained weights or gradients."),
        "results_by_scale": results,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scale", choices=["434M", "2.2B", "both"], default="both")
    parser.add_argument("--lease-token", default=None)
    parser.add_argument("--l2-worker", action="store_true")
    parser.add_argument("--canonical-dir", default=None)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.l2_worker:
        scale = args.scale if args.scale != "both" else "434M"
        _l2_worker_run(scale, args.threads, args.seed, args.canonical_dir, args.lease_token)
        return 0

    if args.selftest:
        return _run_selftest()

    if not args.live:
        print("Nothing to do -- pass --selftest or --live.")
        return 1

    auth = check_authorization()
    if not auth["env_authorized"]:
        print("F1BENCH_REFUSED_UNAUTHORIZED: EMBER_GATE_AUTHORIZED=1 not set. No allocation attempted.")
        return 1
    if not args.lease_token:
        print("F1BENCH_REFUSED_UNAUTHORIZED: --lease-token is required for --live (every scope, no exceptions). "
              "No allocation attempted.")
        return 1

    cfg = ts.load_contract()
    run_ts = _ts()
    run_dir = _REPO / "scratch" / f"f1bench-{run_ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    scales = ["434M", "2.2B"] if args.scale == "both" else [args.scale]
    results = {}
    for scale_name in scales:
        results[scale_name] = run_scale_live(scale_name, cfg, run_dir, lease_token_path=args.lease_token)
        print(f"F1BENCH scale={scale_name} status={results[scale_name]['status']}", flush=True)

    receipt = _build_receipt(results, run_ts)
    out_path = _REPO / "receipts" / f"factor1-lever-microbench-{run_ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    print(f"F1BENCH_RECEIPT_WRITTEN {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
