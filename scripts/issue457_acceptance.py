#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded, CPU-only acceptance probe for Ember issue #457."""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import gc
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cpu_offload_adamw as offload  # noqa: E402


INVARIANT_SHA256 = (
    "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
)
DEFAULT_FIRST_STEP_COMMIT_LIMIT_BYTES = 64 * 1024**2
HISTORICAL_RUNG2_RECEIPT = (
    ROOT / "receipts" / "cbase-grow-rung2-gpu-offload-probe-20260709T092042Z.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_private_commit_bytes() -> int:
    """Return this process's Windows private commit charge."""
    if sys.platform != "win32":
        raise RuntimeError("Windows process private-commit probe is unavailable")

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), ctypes.c_ulong)
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        raise OSError(
            f"GetProcessMemoryInfo failed: "
            f"{ctypes.WinError(ctypes.get_last_error())}"
        )
    return int(counters.PrivateUsage)


def classify_first_step_commit(
    *,
    before_bytes: int,
    after_bytes: int,
    limit_bytes: int = DEFAULT_FIRST_STEP_COMMIT_LIMIT_BYTES,
) -> dict[str, int | str]:
    for name, value in (
        ("before_bytes", before_bytes),
        ("after_bytes", after_bytes),
        ("limit_bytes", limit_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if limit_bytes == 0:
        raise ValueError("limit_bytes must be positive")
    delta = after_bytes - before_bytes
    charged = max(0, delta)
    return {
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "delta_bytes": delta,
        "charged_delta_bytes": charged,
        "limit_bytes": limit_bytes,
        "verdict": "PASS" if charged <= limit_bytes else "FAIL",
    }


def validate_historical_rung2_receipt(path: Path = HISTORICAL_RUNG2_RECEIPT) -> dict:
    value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if value.get("param_count_after") != 2_228_265_984:
        raise ValueError("historical receipt does not bind the rung-2 parameter count")
    preflight = value.get("commit_preflight")
    if not isinstance(preflight, dict) or preflight.get("sufficient") is not True:
        raise ValueError("historical receipt does not bind a passing commit preflight")
    for key in ("commit_available_gib", "free_physical_gib_not_the_gate"):
        if not isinstance(preflight.get(key), (int, float)):
            raise ValueError(f"historical commit preflight is missing {key}")
    offloaded_config = value.get("offloaded_config")
    if not isinstance(offloaded_config, dict):
        raise ValueError("historical receipt is missing offloaded_config")
    if offloaded_config.get("n_optimizer_steps") != 20:
        raise ValueError("historical receipt does not bind 20 optimizer steps")
    if value.get("verdict") != "MEASURED_PASS":
        raise ValueError("historical rung-2 measurement is not PASS")
    estimate = offloaded_config.get("required_estimate_detail")
    if not isinstance(estimate, dict):
        raise ValueError("historical receipt is missing optimizer-state estimate")
    if estimate.get("optimizer_state_gib_vram_resident") != 0.0:
        raise ValueError("historical optimizer state was not fully offloaded")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
        "param_count": value["param_count_after"],
        "optimizer_steps": offloaded_config["n_optimizer_steps"],
        "verdict": value["verdict"],
        "commit_available_gib": preflight["commit_available_gib"],
        "free_physical_gib_not_the_gate": preflight[
            "free_physical_gib_not_the_gate"
        ],
    }


def _execute_first_step_probe(
    *,
    root: Path,
    commit_reader: Callable[[], int],
    tensor_side: int,
    limit_bytes: int,
) -> dict:
    import torch

    param = torch.nn.Parameter(
        torch.linspace(-1.0, 1.0, tensor_side**2).reshape(tensor_side, tensor_side)
    )
    optimizer = offload.CPUOffloadOptimizer(
        [("probe.weight", param)],
        lambda params: torch.optim.AdamW(params, lr=1e-3),
        optstate_dir=root,
    )
    optimizer._shadow[0].grad = offload._memmap_zeros(
        root / "probe_weight.grad.f32", tuple(param.shape)
    )
    param.grad = torch.ones_like(param)
    before = commit_reader()
    optimizer.step()
    after = commit_reader()
    expected = {
        "probe_weight.shadow.f32",
        "probe_weight.grad.f32",
        "probe_weight.exp_avg.f32",
        "probe_weight.exp_avg_sq.f32",
    }
    actual = {path.name for path in root.iterdir() if path.is_file()}
    missing = sorted(expected - actual)
    if missing:
        raise AssertionError(f"missing file-backed optimizer surfaces: {missing}")
    classification = classify_first_step_commit(
        before_bytes=before, after_bytes=after, limit_bytes=limit_bytes
    )
    classification.update(
        {
            "tensor_side": tensor_side,
            "parameter_count": param.numel(),
            "file_backed_surfaces": sorted(expected),
        }
    )
    return classification


def run_first_step_probe(
    *,
    commit_reader: Callable[[], int] = process_private_commit_bytes,
    tensor_side: int = 256,
    limit_bytes: int = DEFAULT_FIRST_STEP_COMMIT_LIMIT_BYTES,
) -> dict:
    if tensor_side <= 0:
        raise ValueError("tensor_side must be positive")
    with tempfile.TemporaryDirectory(prefix="ember-issue457-") as raw:
        result = _execute_first_step_probe(
            root=Path(raw),
            commit_reader=commit_reader,
            tensor_side=tensor_side,
            limit_bytes=limit_bytes,
        )
        # The helper frame owned every Torch tensor backed by these memmaps.
        # Once it returns, collection closes all Windows mapping handles before
        # TemporaryDirectory attempts to remove the files.
        gc.collect()
        return result
def build_receipt() -> dict:
    first_step = run_first_step_probe()
    if first_step["verdict"] != "PASS":
        raise RuntimeError(f"first-step private commit exceeded bound: {first_step}")
    historical = validate_historical_rung2_receipt()
    return {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
        "ticket": "ISSUE-457-CURRENT-ACCEPTANCE",
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
        "issue": "wordingone/ember#457",
        "platform": sys.platform,
        "source": {
            "acceptance_probe_sha256": _sha256(Path(__file__)),
            "cpu_offload_adamw_sha256": _sha256(SCRIPTS / "cpu_offload_adamw.py"),
            "governor_sha256": _sha256(SCRIPTS / "governor.py"),
        },
        "first_step_private_commit": first_step,
        "historical_rung2_measurement": historical,
        "acceptance": {
            "file_backed_optimizer_state": True,
            "first_step_has_no_large_private_commit_delta": True,
            "commit_and_physical_numbers_bound": True,
            "rung2_instrumented_probe_completed": True,
        },
        "claim_boundary": (
            "This receipt proves only the current file-backed optimizer surfaces, "
            "a bounded CPU first-step private-commit measurement, and the immutable "
            "historical 2.2B twenty-step receipt binding. It makes no new GPU, "
            "training, checkpoint, model, benchmark, capability, or milestone claim."
        ),
        "verdict": "ISSUE_457_ACCEPTANCE_PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build_receipt()
    except Exception as exc:
        print(f"ISSUE_457_ACCEPTANCE_FAIL: {exc}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
