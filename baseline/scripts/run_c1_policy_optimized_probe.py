#!/usr/bin/env python3
"""Run a C1 policy-optimized 1024-window streamed probe with nvidia-smi power sampling.

The child probe uses local shard inputs, but the public receipt records only
repo-relative artifact paths and bounded summary telemetry.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POWER_RECEIPT = "receipts/4090-policy-optimized-1024-window-power-2026-06-30.json"
PROBE_RECEIPT = "receipts/4090-policy-optimized-1024-window-probe-pretraining-equivalent.json"
EXPECTED_PROBE_VERDICT = "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_float(value: str) -> float | None:
    value = value.strip()
    if value in {"", "N/A", "[Not Supported]"}:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def sample_nvidia_smi() -> dict[str, Any] | None:
    cmd = [
        "nvidia-smi",
        "--query-gpu=timestamp,power.draw,temperature.gpu,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    if not line:
        return None
    row = next(csv.reader([line]))
    if len(row) < 6:
        return None
    return {
        "timestamp": row[0].strip(),
        "power_draw_w": parse_float(row[1]),
        "temperature_c": parse_float(row[2]),
        "utilization_gpu_percent": parse_float(row[3]),
        "memory_used_mib": parse_float(row[4]),
        "memory_total_mib": parse_float(row[5]),
    }


def sampling_loop(samples: list[dict[str, Any]], stop: threading.Event, interval_s: float) -> None:
    while not stop.is_set():
        t = time.perf_counter()
        sample = sample_nvidia_smi()
        if sample is not None:
            sample["monotonic_s"] = t
            samples.append(sample)
        stop.wait(interval_s)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def integrate_energy(samples: list[dict[str, Any]]) -> float | None:
    usable = [(float(row["monotonic_s"]), float(row["power_draw_w"])) for row in samples if isinstance(row.get("power_draw_w"), (int, float))]
    if len(usable) < 2:
        return None
    total = 0.0
    for (t0, p0), (t1, p1) in zip(usable, usable[1:]):
        dt = max(0.0, t1 - t0)
        total += ((p0 + p1) / 2.0) * dt
    return total


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_power_summary(samples: list[dict[str, Any]], child_elapsed_s: float, probe: dict[str, Any]) -> dict[str, Any]:
    powers = [float(row["power_draw_w"]) for row in samples if isinstance(row.get("power_draw_w"), (int, float))]
    temps = [float(row["temperature_c"]) for row in samples if isinstance(row.get("temperature_c"), (int, float))]
    utils = [float(row["utilization_gpu_percent"]) for row in samples if isinstance(row.get("utilization_gpu_percent"), (int, float))]
    mems = [float(row["memory_used_mib"]) for row in samples if isinstance(row.get("memory_used_mib"), (int, float))]
    sample_span_s = (samples[-1]["monotonic_s"] - samples[0]["monotonic_s"]) if len(samples) >= 2 else None
    energy_j = integrate_energy(samples)
    steps = int(probe.get("steps_completed") or 0)
    shape = probe.get("probe_shape", {}) if isinstance(probe.get("probe_shape"), dict) else {}
    seq = int(shape.get("seq_len") or 0)
    batch = int(shape.get("batch_size") or 0)
    tokens = steps * seq * max(batch, 1)
    return {
        "sampling_method": "nvidia-smi query-gpu timestamp,power.draw,temperature.gpu,utilization.gpu,memory.used,memory.total sampled around child wall clock",
        "sample_interval_s_requested": None,
        "sample_count": len(samples),
        "first_sample_timestamp": samples[0].get("timestamp") if samples else None,
        "last_sample_timestamp": samples[-1].get("timestamp") if samples else None,
        "sample_span_s": sample_span_s,
        "child_elapsed_s": child_elapsed_s,
        "includes_child_wall_clock": True,
        "avg_power_w": mean(powers),
        "min_power_w": min(powers) if powers else None,
        "max_power_w": max(powers) if powers else None,
        "avg_gpu_utilization_percent": mean(utils),
        "max_gpu_utilization_percent": max(utils) if utils else None,
        "max_temperature_c": max(temps) if temps else None,
        "max_memory_used_mib": max(mems) if mems else None,
        "energy_joules_trapezoid": energy_j,
        "energy_wh": (energy_j / 3600.0) if energy_j is not None else None,
        "steps_accounted": steps,
        "tokens_accounted": tokens,
        "joules_per_step": (energy_j / steps) if energy_j is not None and steps > 0 else None,
        "joules_per_training_token": (energy_j / tokens) if energy_j is not None and tokens > 0 else None,
        "raw_sample_count_recorded": len(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--token-shard-dir", type=Path, required=True)
    parser.add_argument("--token-offset", type=int, default=16_777_216)
    parser.add_argument("--token-stride", type=int, default=32_768)
    parser.add_argument("--steps", type=int, default=1024)
    parser.add_argument("--checkpoint-interval-steps", type=int, default=1024)
    parser.add_argument("--eval-steps", type=int, default=4)
    parser.add_argument("--sample-interval-s", type=float, default=0.5)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    probe_path = root / PROBE_RECEIPT
    power_path = root / POWER_RECEIPT
    child_args = [
        sys.executable,
        "engineering/4090-1b/full_stack_lm_loss_probe_4090.py",
        "--config",
        "engineering/4090-1b/configs/pretraining_equivalent_1b_4090.json",
        "--receipt",
        PROBE_RECEIPT,
        "--capability-target",
        "pretraining_equivalent_5b_tokens_7_days",
        "--steps",
        str(args.steps),
        "--batch-size",
        "1",
        "--seq-len",
        "2048",
        "--dtype",
        "bfloat16",
        "--optimizer",
        "adamw",
        "--activation-checkpointing",
        "--token-shard-dir",
        str(args.token_shard_dir),
        "--token-offset",
        str(args.token_offset),
        "--token-stride",
        str(args.token_stride),
        "--vary-real-token-window",
        "--stream-real-token-loader",
        "--max-real-data-search-tokens",
        "1000000",
        "--shard-receipt",
        "../receipts/token-shards-v0-20260611T170047Z.json",
        "--checkpoint-cadence-probe",
        "--checkpoint-interval-steps",
        str(args.checkpoint_interval_steps),
        "--eval-accounting-probe",
        "--eval-steps",
        str(args.eval_steps),
        "--recovery-accounting-probe",
    ]

    samples: list[dict[str, Any]] = []
    stop = threading.Event()
    sampler = threading.Thread(target=sampling_loop, args=(samples, stop, float(args.sample_interval_s)), daemon=True)
    created_at = now_utc()
    sampler.start()
    start = time.perf_counter()
    proc = subprocess.run(child_args, cwd=root, check=False, capture_output=True, text=True)
    child_elapsed_s = time.perf_counter() - start
    stop.set()
    sampler.join(timeout=2.0)
    final_sample = sample_nvidia_smi()
    if final_sample is not None:
        final_sample["monotonic_s"] = time.perf_counter()
        samples.append(final_sample)

    probe = read_json(probe_path) if probe_path.exists() else {}
    power_summary = build_power_summary(samples, child_elapsed_s, probe)
    power_summary["sample_interval_s_requested"] = float(args.sample_interval_s)
    verdict = proc.returncode == 0 and probe.get("verdict") == EXPECTED_PROBE_VERDICT
    receipt = {
        "created_at_utc": created_at,
        "kind": "single_4090_c1_policy_optimized_streamed_power_probe",
        "verdict": "C1_POLICY_OPTIMIZED_1024_WINDOW_READY_NOT_COMPLETION" if verdict else "C1_POLICY_OPTIMIZED_1024_WINDOW_INVALID",
        "child_returncode": int(proc.returncode),
        "child_stdout_bytes": len(proc.stdout.encode("utf-8", errors="replace")),
        "child_stderr_bytes": len(proc.stderr.encode("utf-8", errors="replace")),
        "child_command_recorded": False,
        "local_input_paths_recorded": False,
        "policy_scope": {
            "train_steps_requested": int(args.steps),
            "checkpoint_interval_steps": int(args.checkpoint_interval_steps),
            "eval_steps": int(args.eval_steps),
            "recovery_accounting_enabled": True,
            "power_sampling_enabled": True,
        },
        "probe_receipt": {
            "repo_path": PROBE_RECEIPT,
            "exists": probe_path.exists(),
            "verdict": probe.get("verdict"),
            "steps_completed": probe.get("steps_completed"),
            "active_trainable_parameters": probe.get("active_trainable_parameters"),
            "measured_tflops_lower_bound": probe.get("estimated_stack_training_tflops_lower_bound"),
            "required_sustained_tflops": probe.get("full_config_required_sustained_tflops"),
            "elapsed_s": probe.get("elapsed_s"),
            "checkpoint_elapsed_s": probe.get("checkpoint_elapsed_s"),
            "eval_elapsed_s": probe.get("eval_elapsed_s"),
            "recovery_elapsed_s": probe.get("recovery_elapsed_s"),
            "real_data_window_count": probe.get("real_data_window_count"),
            "unique_input_window_count": probe.get("real_data_unique_input_window_count"),
            "checkpoint_event_count": (probe.get("checkpoint_cadence") or {}).get("checkpoint_event_count") if isinstance(probe.get("checkpoint_cadence"), dict) else None,
            "eval_window_count": (probe.get("eval_accounting") or {}).get("eval_window_count") if isinstance(probe.get("eval_accounting"), dict) else None,
            "recovery_window_base": (probe.get("recovery_accounting") or {}).get("recovery_window_base") if isinstance(probe.get("recovery_accounting"), dict) else None,
        },
        "power_sampling": power_summary,
        "sample_preview": [
            {k: row.get(k) for k in ("timestamp", "power_draw_w", "temperature_c", "utilization_gpu_percent", "memory_used_mib", "memory_total_mib")}
            for row in (samples[:3] + samples[-3:] if len(samples) > 6 else samples)
        ],
        "completion_limit": "This is bounded nvidia-smi power sampling around a 1024-window streamed real-token full-stack C1 train/checkpoint/eval/recovery policy probe only: not days-scale long-run training, not full-run energy accounting for data prep/eval/recovery/packaging, and not overall baseline completion.",
    }
    power_path.parent.mkdir(parents=True, exist_ok=True)
    power_path.write_text(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "C1_POLICY_OPTIMIZED_1024_WINDOW_READY_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
