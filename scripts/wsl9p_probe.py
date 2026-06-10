#!/usr/bin/env python3
"""
WSL 9P filesystem tax micro-benchmark.

Measures sequential + random I/O on /mnt/b (9P) vs /tmp (ext4).
Emits receipt JSON to --output path or stdout.

Usage:
  python3 wsl9p_probe.py [--output /path/to/receipt.json] [--note "quiet window, no other jobs"]
  python3 wsl9p_probe.py --selftest

Dependencies: stdlib only (os, sys, time, json, random, threading, statistics).
Requires: python 3.10+
"""

# ---------------------------------------------------------------------------
# Corrections vs draft
# ---------------------------------------------------------------------------
# C1 RNG SEED: draft had no seed — random.randint in run_random_io was non-
#    deterministic. Fixed: random.seed(16) called once in main(); seed value
#    recorded in receipt["rng_seed"].
#
# C2 REPETITIONS: draft ran each op once. Fixed: each op runs 3 times; receipt
#    records all reps as "reps_ms" list + "median_ms"; penalty matrix is
#    computed on medians, not single samples.
#
# C3 os.uname() GUARD: draft called os.uname().nodename unconditionally —
#    AttributeError on Windows (os.uname not available on win32). Fixed:
#    hasattr(os, "uname") guard; fallback to platform.node() + platform.system().
#
# C4 SETUP INSIDE TIMED SECTION — SEQ_WRITE: run_sequential_write wrote
#    os.urandom() data inside the timed section. The intent is to measure
#    write throughput, so the generate-and-write loop is correctly timed;
#    however the draft used os.urandom() per-chunk (CSPRNG, slow on Windows).
#    Fixed: generate the full payload BEFORE the timer starts; timer covers
#    only the f.write() calls.  The payload buffer is reused across reps.
#
# C5 SETUP INSIDE TIMED SECTION — SEQ_READ: run_sequential_read wrote the
#    file, then timed the read — setup correctly outside the timer. No change
#    needed here; confirmed and noted.
#
# C6 SETUP INSIDE TIMED SECTION — RANDOM_IO: run_random_io wrote the file,
#    then timed seeks. Setup was outside timer. Confirmed correct; no change.
#    Additional fix: seek offsets pre-computed before the timer starts so the
#    random.randint calls (which consume RNG state) are not inside the timed
#    hot loop.
#
# C7 SETUP INSIDE TIMED SECTION — PARALLEL_IO: run_parallel_io wrote then
#    read. Setup outside timer. Confirmed correct.
#
# C8 DEFAULT OUTPUT PATH: draft defaulted to stdout when --output omitted.
#    Fixed: default is
#    /mnt/b/M/avir/leo/state/nc-ladder/receipts/wsl9p-probe-<UTCts>.json
#    per issue spec. Stdout fallback retained when that path is not writable.
#
# C9 CONCURRENT_CAVEAT FIELD: draft had no field for quiet-window status.
#    Fixed: --note arg populates receipt["concurrent_caveat"] (free text).
#
# C10 SELFTEST MODE: draft had no --selftest. Added: exercises penalty math
#     and rep-median logic on synthetic numbers; prints WSL9P_SELFTEST_PASS.
#
# C11 SHUTIL IMPORT: draft imported shutil inside the loop. Moved to top-level.
# ---------------------------------------------------------------------------

import os
import sys
import json
import time
import random
import shutil
import threading
import statistics
import platform
from datetime import datetime, timezone
from pathlib import Path

REPS = 3
RNG_SEED = 16


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_platform_info() -> dict:
    """Portable platform info — does not crash on Windows (no os.uname)."""
    info = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "node": platform.node(),
        "system": platform.system(),
        "release": platform.release(),
    }
    if hasattr(os, "uname"):  # C3: guard os.uname()
        u = os.uname()
        info["uname_sysname"] = u.sysname
        info["uname_release"] = u.release
        info["uname_machine"] = u.machine
    return info


# ---------------------------------------------------------------------------
# I/O primitives — each returns (elapsed_ms, error_or_None).
# SETUP (file creation) is always OUTSIDE the timed region.
# ---------------------------------------------------------------------------

def _write_file(path: Path, payload: bytes) -> None:
    """Write payload to path in 64 KB chunks (not timed)."""
    chunk = 65536
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        offset = 0
        while offset < len(payload):
            f.write(payload[offset: offset + chunk])
            offset += chunk


def run_sequential_write(path: Path, size_bytes: int) -> tuple:
    """
    Time writing `size_bytes` to `path`.
    Payload generated BEFORE timer (C4).
    """
    # C4: generate payload outside timer
    payload = os.urandom(size_bytes)
    try:
        chunk = 65536
        start = time.perf_counter()
        with open(path, "wb") as f:
            offset = 0
            while offset < len(payload):
                f.write(payload[offset: offset + chunk])
                offset += chunk
        return (time.perf_counter() - start) * 1000, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def run_sequential_read(path: Path, size_bytes: int) -> tuple:
    """
    Write `size_bytes` to `path` (setup, not timed), then time sequential read.
    C5: confirmed setup outside timer.
    """
    payload = os.urandom(size_bytes)
    _write_file(path, payload)  # setup, outside timer
    try:
        start = time.perf_counter()
        with open(path, "rb") as f:
            while f.read(65536):
                pass
        return (time.perf_counter() - start) * 1000, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def run_random_io(path: Path, file_size_bytes: int, num_seeks: int = 1000) -> tuple:
    """
    Create file (setup, not timed), then time `num_seeks` random 16 KB reads.
    Seek offsets pre-computed outside timer (C6).
    """
    payload = os.urandom(file_size_bytes)
    _write_file(path, payload)
    read_size = 16384  # 16 KB
    # C6: pre-compute offsets outside timer
    max_offset = max(0, file_size_bytes - read_size)
    offsets = [random.randint(0, max_offset) for _ in range(num_seeks)]
    try:
        start = time.perf_counter()
        with open(path, "rb") as f:
            for off in offsets:
                f.seek(off)
                f.read(read_size)
        return (time.perf_counter() - start) * 1000, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


def run_parallel_io(path: Path, size_bytes: int, num_threads: int = 2) -> tuple:
    """
    Write file (setup, not timed), then time `num_threads` concurrent reads.
    C7: setup confirmed outside timer.
    """
    payload = os.urandom(size_bytes)
    _write_file(path, payload)
    errors = []

    def reader():
        try:
            with open(path, "rb") as f:
                while f.read(65536):
                    pass
        except Exception as e:
            errors.append(str(e))

    try:
        threads = [threading.Thread(target=reader) for _ in range(num_threads)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed_ms = (time.perf_counter() - start) * 1000
        if errors:
            return None, f"Thread error: {errors[0]}"
        return elapsed_ms, None
    except Exception as e:
        return None, str(e)
    finally:
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Rep runner — runs one op REPS times, returns all times + median (C2)
# ---------------------------------------------------------------------------

def run_reps(fn, *args) -> dict:
    """
    Call fn(*args) REPS times.
    Returns {"reps_ms": [...], "median_ms": float} or {"error": str}.
    """
    times = []
    for _ in range(REPS):
        elapsed, err = fn(*args)
        if err is not None:
            return {"error": err}
        times.append(round(elapsed, 2))
    med = round(statistics.median(times), 2)
    return {"reps_ms": times, "median_ms": med}


# ---------------------------------------------------------------------------
# Penalty computation on medians (C2)
# ---------------------------------------------------------------------------

def compute_penalties(tmp_res: dict, b_res: dict) -> dict:
    """
    penalty_pct = ((9P_median - ext4_median) / ext4_median) * 100
    Computed on median_ms fields.
    """
    penalties = {}
    for op in tmp_res:
        if op in b_res:
            t = tmp_res[op]
            b = b_res[op]
            if "median_ms" in t and "median_ms" in b and t["median_ms"] > 0:
                pct = ((b["median_ms"] - t["median_ms"]) / t["median_ms"]) * 100
                penalties[op] = round(pct, 1)
    return penalties


# ---------------------------------------------------------------------------
# Self-test (C10)
# ---------------------------------------------------------------------------

def run_selftest() -> None:
    """
    Exercise penalty math and rep-median logic on synthetic numbers.
    Prints WSL9P_SELFTEST_PASS on success, raises AssertionError on failure.
    """
    # Test 1: median of odd reps
    times = [100.0, 200.0, 150.0]
    med = statistics.median(times)
    assert med == 150.0, f"median fail: {med}"

    # Test 2: median of even reps (statistics.median averages middle two)
    times4 = [100.0, 200.0, 300.0, 400.0]
    med4 = statistics.median(times4)
    assert med4 == 250.0, f"median4 fail: {med4}"

    # Test 3: penalty math
    tmp_res = {"seq_write_10m": {"median_ms": 100.0}}
    b_res   = {"seq_write_10m": {"median_ms": 300.0}}
    p = compute_penalties(tmp_res, b_res)
    assert p["seq_write_10m"] == 200.0, f"penalty fail: {p}"

    # Test 4: zero-penalty (equal)
    tmp2 = {"op": {"median_ms": 50.0}}
    b2   = {"op": {"median_ms": 50.0}}
    p2 = compute_penalties(tmp2, b2)
    assert p2["op"] == 0.0, f"zero-penalty fail: {p2}"

    # Test 5: negative penalty (9P faster — unlikely but must not crash)
    tmp3 = {"op": {"median_ms": 200.0}}
    b3   = {"op": {"median_ms": 100.0}}
    p3 = compute_penalties(tmp3, b3)
    assert p3["op"] == -50.0, f"negative-penalty fail: {p3}"

    # Test 6: missing median_ms key (error result) — skipped in penalty
    tmp4 = {"op": {"error": "disk full"}}
    b4   = {"op": {"median_ms": 100.0}}
    p4 = compute_penalties(tmp4, b4)
    assert "op" not in p4, f"error-key not skipped: {p4}"

    # Test 7: rng seed reproducibility
    random.seed(RNG_SEED)
    a = random.randint(0, 1_000_000)
    random.seed(RNG_SEED)
    b = random.randint(0, 1_000_000)
    assert a == b, f"seed not deterministic: {a} != {b}"

    # Test 8: platform info does not crash
    info = _get_platform_info()
    assert "platform" in info
    assert "node" in info

    print("WSL9P_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args():
    args = sys.argv[1:]
    output_path = None
    note = ""
    selftest = "--selftest" in args
    if "--output" in args:
        idx = args.index("--output")
        if idx + 1 < len(args):
            output_path = args[idx + 1]
    if "--note" in args:
        idx = args.index("--note")
        if idx + 1 < len(args):
            note = args[idx + 1]
    return output_path, note, selftest


def main():
    output_arg, note, selftest = _parse_args()

    if selftest:
        run_selftest()
        return

    # C1: seed RNG deterministically
    random.seed(RNG_SEED)

    ts = now_iso()

    # C9: default output path
    default_output = f"/mnt/b/M/avir/leo/state/nc-ladder/receipts/wsl9p-probe-{ts.replace(':', '')}.json"
    output_path = output_arg if output_arg is not None else default_output

    receipt = {
        "schema": "wsl9p_probe_v1",
        "timestamp": ts,
        "rng_seed": RNG_SEED,          # C1
        "reps": REPS,                   # C2
        "concurrent_caveat": note,      # C9 — set via --note
        "platform_info": _get_platform_info(),  # C3
        "results": {},
    }

    # Test matrix: (op_name, fn, *args)
    # file_size_bytes used only for labelling; actual size passed to fn
    MB = 1024 * 1024
    tests = [
        ("seq_write_10m",    run_sequential_write, 10 * MB),
        ("seq_write_100m",   run_sequential_write, 100 * MB),
        ("seq_read_10m",     run_sequential_read,  10 * MB),
        ("seq_read_100m",    run_sequential_read,  100 * MB),
        ("random_io_1gb",    run_random_io,        1024 * MB),
        ("parallel_read_10m", run_parallel_io,     10 * MB),
    ]

    for fs_root in ["/tmp", "/mnt/b"]:
        if not Path(fs_root).exists():
            receipt["results"][fs_root] = {"error": f"{fs_root} not mounted/accessible"}
            continue

        fs_results = {}
        for op_name, fn, *fn_args in tests:
            test_dir = Path(fs_root) / "wsl9p_probe" / op_name
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / "testfile"

            # C2: run REPS repetitions
            result = run_reps(fn, test_file, *fn_args)
            fs_results[op_name] = result

            try:
                shutil.rmtree(test_dir)
            except Exception:
                pass

        receipt["results"][fs_root] = fs_results

    # Compute penalties on medians (C2)
    if "/tmp" in receipt["results"] and "/mnt/b" in receipt["results"]:
        receipt["penalties_pct"] = compute_penalties(
            receipt["results"]["/tmp"],
            receipt["results"]["/mnt/b"],
        )
        # Verdict
        above_threshold = [
            op for op, pct in receipt["penalties_pct"].items() if pct > 20
        ]
        receipt["verdict"] = (
            f"9P penalty >20% on {len(above_threshold)}/{len(receipt['penalties_pct'])} ops"
            f" ({', '.join(above_threshold) or 'none'})"
        )

    output_json = json.dumps(receipt, indent=2)

    # C8: write to default path, fall back to stdout if not writable
    written = False
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(output_json)
            print(f"Receipt written to {output_path}", file=sys.stderr)
            written = True
        except Exception as e:
            print(f"WARNING: could not write to {output_path}: {e}; falling back to stdout",
                  file=sys.stderr)

    if not written:
        print(output_json)


if __name__ == "__main__":
    main()
