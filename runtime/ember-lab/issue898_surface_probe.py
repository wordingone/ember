# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Dispatch-only destructive probes for issue #898 resource-cage receipts.

This is a probe payload, never a launcher. It consumes the daemon-minted
dispatch token before parsing a probe mode or touching a resource. Each mode
then really attempts the declared crossing and remains alive for the daemon's
kernel wall or sentinel to terminate it; it never reports PASS itself.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# issue2015 exact-local-import:src/ember/governance/scripts/ember_dispatch_token.py
import importlib.util as _ember_95137563367d86b9_importlib
import sys as _ember_95137563367d86b9_sys
from pathlib import Path as _ember_95137563367d86b9_Path
_ember_95137563367d86b9_path = _ember_95137563367d86b9_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'ember_dispatch_token.py')
if not _ember_95137563367d86b9_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_dispatch_token.py')
_ember_95137563367d86b9_aliases = ('_ember_issue2015_95137563367d86b9', 'ember_dispatch_token', 'scripts.ember_dispatch_token')
_ember_95137563367d86b9_existing = []
for _ember_95137563367d86b9_alias in _ember_95137563367d86b9_aliases:
    _ember_95137563367d86b9_candidate = _ember_95137563367d86b9_sys.modules.get(_ember_95137563367d86b9_alias)
    if _ember_95137563367d86b9_candidate is not None and all(_ember_95137563367d86b9_candidate is not item for item in _ember_95137563367d86b9_existing):
        _ember_95137563367d86b9_existing.append(_ember_95137563367d86b9_candidate)
if len(_ember_95137563367d86b9_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_dispatch_token.py')
if _ember_95137563367d86b9_existing:
    _ember_95137563367d86b9_module = _ember_95137563367d86b9_existing[0]
    _ember_95137563367d86b9_observed = getattr(_ember_95137563367d86b9_module, '__file__', None)
    if _ember_95137563367d86b9_observed is None or _ember_95137563367d86b9_Path(_ember_95137563367d86b9_observed).resolve() != _ember_95137563367d86b9_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_dispatch_token.py')
else:
    _ember_95137563367d86b9_spec = _ember_95137563367d86b9_importlib.spec_from_file_location('_ember_issue2015_95137563367d86b9', _ember_95137563367d86b9_path)
    if _ember_95137563367d86b9_spec is None or _ember_95137563367d86b9_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_dispatch_token.py')
    _ember_95137563367d86b9_module = _ember_95137563367d86b9_importlib.module_from_spec(_ember_95137563367d86b9_spec)
    for _ember_95137563367d86b9_alias in _ember_95137563367d86b9_aliases:
        _ember_95137563367d86b9_prior = _ember_95137563367d86b9_sys.modules.get(_ember_95137563367d86b9_alias)
        if _ember_95137563367d86b9_prior is not None and _ember_95137563367d86b9_prior is not _ember_95137563367d86b9_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_dispatch_token.py')
        _ember_95137563367d86b9_sys.modules[_ember_95137563367d86b9_alias] = _ember_95137563367d86b9_module
    try:
        _ember_95137563367d86b9_spec.loader.exec_module(_ember_95137563367d86b9_module)
    except BaseException:
        for _ember_95137563367d86b9_alias in _ember_95137563367d86b9_aliases:
            if _ember_95137563367d86b9_sys.modules.get(_ember_95137563367d86b9_alias) is _ember_95137563367d86b9_module:
                _ember_95137563367d86b9_sys.modules.pop(_ember_95137563367d86b9_alias, None)
        raise
for _ember_95137563367d86b9_alias in _ember_95137563367d86b9_aliases:
    _ember_95137563367d86b9_prior = _ember_95137563367d86b9_sys.modules.get(_ember_95137563367d86b9_alias)
    if _ember_95137563367d86b9_prior is not None and _ember_95137563367d86b9_prior is not _ember_95137563367d86b9_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_dispatch_token.py')
    _ember_95137563367d86b9_sys.modules[_ember_95137563367d86b9_alias] = _ember_95137563367d86b9_module
consume_dispatch = getattr(_ember_95137563367d86b9_module, 'consume_dispatch')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_dispatch_token.py  # noqa: E402


def _canonical_positive(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a canonical positive integer") from error
    if value <= 0 or str(value) != raw:
        raise ValueError(f"{name} must be a canonical positive integer")
    return value


def _virtual_alloc(size: int) -> tuple[bool, int]:
    if os.name != "nt":
        raise OSError("issue #898 commit probe requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    virtual_alloc = kernel32.VirtualAlloc
    virtual_alloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    virtual_alloc.restype = ctypes.c_void_p
    address = virtual_alloc(None, size, 0x3000, 0x04)  # MEM_RESERVE|MEM_COMMIT, PAGE_READWRITE
    if not address:
        return False, ctypes.get_last_error()
    allocation = (ctypes.c_ubyte * size).from_address(address)
    for offset in range(0, size, 4096):
        allocation[offset] = 1
    return True, 0


def _hold_for_daemon() -> None:
    time.sleep(60)


def _hold_for_vram_ladder() -> None:
    # Five sample intervals at the governed 2 s cadence. The cage, not this
    # payload, must end a successful crossing before this returns.
    time.sleep(10)


def run_commit_probe(
    *,
    attempt_bytes: int,
    maximum_job_memory_bytes: int,
    allocate: Callable[[int], tuple[bool, int]] = _virtual_alloc,
    hold: Callable[[], None] = _hold_for_daemon,
) -> dict:
    if attempt_bytes <= maximum_job_memory_bytes:
        raise ValueError("commit probe attempt must cross the daemon job-memory cap")
    allocated, win32_error = allocate(attempt_bytes)
    if not allocated:
        return {
            "result": "OS_ALLOCATION_REFUSED",
            "attempt_bytes": attempt_bytes,
            "win32_error": win32_error,
        }
    hold()
    return {"result": "CROSSING_SURVIVED_UNEXPECTEDLY", "attempt_bytes": attempt_bytes}


def run_disk_probe(
    *,
    write_roots: Iterable[Path],
    maximum_write_bytes: int,
    attempt_bytes_per_root: int,
    hold: Callable[[], None] = _hold_for_daemon,
) -> dict:
    roots = list(write_roots)
    if not roots:
        raise ValueError("disk probe requires at least one named write root")
    if attempt_bytes_per_root <= maximum_write_bytes:
        raise ValueError("disk probe attempt must write past the daemon budget")
    writes = []
    chunk = b"x" * min(attempt_bytes_per_root, 1024 * 1024)
    for root in roots:
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("disk probe write roots must be existing absolute directories")
        path = root / "issue898-disk-crossing.bin"
        remaining = attempt_bytes_per_root
        with path.open("xb") as stream:
            while remaining:
                payload = chunk[:remaining]
                stream.write(payload)
                remaining -= len(payload)
            stream.flush()
            os.fsync(stream.fileno())
        writes.append({"path": str(path), "bytes": attempt_bytes_per_root})
    hold()
    return {
        "result": "WRITE_PAST_BUDGET_ATTEMPTED",
        "maximum_write_bytes": maximum_write_bytes,
        "bytes_per_root": attempt_bytes_per_root,
        "writes": writes,
    }


def run_vram_fraction_probe(
    *,
    attempt_bytes: int,
    maximum_process_vram_bytes: int,
    daemon_process_fraction_millionths: int,
    minimum_device_margin_bytes: int,
    torch_module,
    hold: Callable[[], None] = _hold_for_vram_ladder,
) -> dict:
    if attempt_bytes <= maximum_process_vram_bytes:
        raise ValueError("VRAM fraction probe attempt must cross the daemon cap")
    if not 0 < daemon_process_fraction_millionths <= 1_000_000:
        raise ValueError("VRAM fraction must be in the enforceable range")
    if minimum_device_margin_bytes <= 0:
        raise ValueError("VRAM fraction probe requires a positive device margin")
    observed_free_bytes, observed_total_bytes = torch_module.cuda.mem_get_info(device=0)
    if attempt_bytes + minimum_device_margin_bytes > observed_total_bytes:
        return {
            "result": "INCONCLUSIVE_DEVICE_MARGIN",
            "attempt_bytes": attempt_bytes,
            "minimum_device_margin_bytes": minimum_device_margin_bytes,
            "observed_free_bytes": observed_free_bytes,
            "observed_total_bytes": observed_total_bytes,
        }
    try:
        allocation = torch_module.empty(attempt_bytes, dtype=torch_module.uint8, device="cuda")
        torch_module.cuda.synchronize()
    except RuntimeError as error:
        if "out of memory" not in str(error).lower():
            raise
        return {
            "result": "INCONCLUSIVE_CUDA_OOM",
            "attempt_bytes": attempt_bytes,
            "maximum_process_vram_bytes": maximum_process_vram_bytes,
            "observed_free_bytes": observed_free_bytes,
            "observed_total_bytes": observed_total_bytes,
            "error_class": type(error).__name__,
        }
    hold()
    del allocation
    return {"result": "CROSSING_SURVIVED_UNEXPECTEDLY", "attempt_bytes": attempt_bytes}


def run_vram_floor_probe(
    *,
    allocation_bytes: int,
    minimum_free_vram_bytes: int,
    torch_module,
    hold: Callable[[], None] = _hold_for_vram_ladder,
) -> dict:
    observed_free_bytes, _total_bytes = torch_module.cuda.mem_get_info(device=0)
    if observed_free_bytes - allocation_bytes >= minimum_free_vram_bytes:
        return {
            "result": "INCONCLUSIVE_FLOOR_NOT_CROSSED",
            "observed_free_bytes": observed_free_bytes,
            "minimum_free_vram_bytes": minimum_free_vram_bytes,
            "allocation_bytes": allocation_bytes,
        }
    allocation = torch_module.empty(allocation_bytes, dtype=torch_module.uint8, device="cuda")
    torch_module.cuda.synchronize()
    hold()
    del allocation
    return {
        "result": "VRAM_FLOOR_CROSSING_HELD_FOR_SENTINEL",
        "allocation_bytes": allocation_bytes,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("commit", "disk", "vram-fraction", "vram-floor"))
    parser.add_argument("--dispatch-profile", choices=("governed-vertical",))
    parser.add_argument("--attempt-bytes", required=True)
    parser.add_argument("--maximum-write-bytes")
    parser.add_argument("--minimum-device-margin-bytes")
    parser.add_argument("--write-root", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    maximum_job_memory_bytes = consume_dispatch(ROOT)
    args = _parser().parse_args(argv)
    attempt_bytes = _canonical_positive(args.attempt_bytes, "--attempt-bytes")
    is_vram_mode = args.mode in {"vram-fraction", "vram-floor"}
    if is_vram_mode != (args.dispatch_profile == "governed-vertical"):
        raise ValueError("VRAM probes require the governed-vertical dispatch profile")
    if args.mode == "commit":
        result = run_commit_probe(
            attempt_bytes=attempt_bytes,
            maximum_job_memory_bytes=maximum_job_memory_bytes,
        )
        print(json.dumps(result, sort_keys=True), flush=True)
        return 86 if result["result"] == "OS_ALLOCATION_REFUSED" else 88
    if args.mode == "disk":
        if args.maximum_write_bytes is None:
            raise ValueError("disk probe requires --maximum-write-bytes")
        result = run_disk_probe(
            write_roots=[Path(value) for value in args.write_root],
            maximum_write_bytes=_canonical_positive(
                args.maximum_write_bytes, "--maximum-write-bytes"
            ),
            attempt_bytes_per_root=attempt_bytes,
        )
        print(json.dumps(result, sort_keys=True), flush=True)
        return 88

    import torch

    if args.mode == "vram-fraction":
        if args.minimum_device_margin_bytes is None:
            raise ValueError("VRAM fraction probe requires --minimum-device-margin-bytes")
        daemon_fraction = _canonical_positive(
            os.environ["EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS"],
            "EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS",
        )
        maximum_process_vram_bytes = _canonical_positive(
            os.environ["EMBER_LAB_DISPATCH_MAXIMUM_PROCESS_VRAM_BYTES"],
            "EMBER_LAB_DISPATCH_MAXIMUM_PROCESS_VRAM_BYTES",
        )
        result = run_vram_fraction_probe(
            attempt_bytes=attempt_bytes,
            maximum_process_vram_bytes=maximum_process_vram_bytes,
            daemon_process_fraction_millionths=daemon_fraction,
            minimum_device_margin_bytes=_canonical_positive(
                args.minimum_device_margin_bytes, "--minimum-device-margin-bytes"
            ),
            torch_module=torch,
        )
        print(json.dumps(result, sort_keys=True), flush=True)
        return 87 if result["result"] == "CUDA_ALLOCATOR_REFUSED" else 88
    result = run_vram_floor_probe(
        allocation_bytes=attempt_bytes,
        minimum_free_vram_bytes=_canonical_positive(
            os.environ["EMBER_LAB_DISPATCH_MINIMUM_FREE_VRAM_BYTES"],
            "EMBER_LAB_DISPATCH_MINIMUM_FREE_VRAM_BYTES",
        ),
        torch_module=torch,
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return 88


if __name__ == "__main__":
    raise SystemExit(main())
