#!/usr/bin/env python3
"""Validate the C1 power-sampled 128-window streamed throughput probe.

This validator proves bounded power/energy telemetry exists for a real-token
1B C1 probe. It intentionally does not turn that probe into days-scale
training completion or full-run energy accounting.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-power-sampled-128-window-throughput-2026-06-30.json"
PROBE_RECEIPT = "receipts/4090-real-data-streamed-128-window-power-sampled-probe-pretraining-equivalent.json"
EXPECTED_VERDICT = "C1_POWER_SAMPLED_128_WINDOW_THROUGHPUT_READY_NOT_COMPLETION"
EXPECTED_PROBE_VERDICT = "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION"
MIN_STEPS = 128
PRIVATE_NAME_PATTERNS = ["av" + "ir", "le" + "o", "ka" + "i", "cla" + "ude", "wording" + "one"]
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[/\\]|Users[/\\]Admin|" + "|".join(r"\\b" + item + r"\\b" for item in PRIVATE_NAME_PATTERNS) + r")", re.IGNORECASE)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def find_local_path_leaks(value: Any, path: str = "$") -> list[dict[str, str]]:
    leaks: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            leaks.extend(find_local_path_leaks(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            leaks.extend(find_local_path_leaks(item, f"{path}[{idx}]"))
    elif isinstance(value, str) and LOCAL_PATH_RE.search(value):
        leaks.append({"path": path, "value": value[:200]})
    return leaks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_path = root / RECEIPT
    probe_path = root / PROBE_RECEIPT
    failures: list[dict[str, Any]] = []

    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    probe = read_json(probe_path) if probe_path.exists() else {}

    if not receipt_path.exists():
        failures.append({"code": "power_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "power_receipt_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("child_returncode") != 0:
        failures.append({"code": "child_returncode_nonzero", "actual": receipt.get("child_returncode")})
    if receipt.get("probe_receipt", {}).get("repo_path") != PROBE_RECEIPT:
        failures.append({"code": "probe_receipt_repo_path_mismatch", "actual": receipt.get("probe_receipt", {}).get("repo_path")})
    if not probe_path.exists():
        failures.append({"code": "probe_receipt_missing", "path": PROBE_RECEIPT})
    if probe.get("verdict") != EXPECTED_PROBE_VERDICT:
        failures.append({"code": "probe_bad_verdict", "actual": probe.get("verdict")})

    steps = probe.get("steps_completed") if isinstance(probe.get("steps_completed"), int) else 0
    requested = probe.get("steps_requested") if isinstance(probe.get("steps_requested"), int) else 0
    if steps < MIN_STEPS or requested < MIN_STEPS:
        failures.append({"code": "probe_insufficient_steps", "completed": probe.get("steps_completed"), "requested": probe.get("steps_requested")})
    if probe.get("uses_real_token_data") is not True or probe.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "probe_not_real_varied", "real": probe.get("uses_real_token_data"), "varied": probe.get("uses_varied_real_token_windows")})
    if probe.get("includes_dataloader_timing") is not True or probe.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "probe_missing_dataloader_timing"})
    if probe.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "probe_loss_not_finite"})

    windows = probe.get("real_data_windows", [])
    hashes = [row.get("input_tokens_sha256") for row in windows if isinstance(row, dict)]
    if len(windows) < MIN_STEPS or len(windows) != steps:
        failures.append({"code": "probe_window_count_mismatch", "windows": len(windows), "steps": steps})
    if len(set(hashes)) != len(hashes):
        failures.append({"code": "probe_window_hashes_not_unique", "count": len(hashes), "unique": len(set(hashes))})

    shape = probe.get("probe_shape", {})
    expected_shape = {"seq_len": 2048, "hidden": 2048, "heads": 16, "layers_executed": 19}
    for key, expected in expected_shape.items():
        if shape.get(key) != expected:
            failures.append({"code": "probe_shape_mismatch", "key": key, "expected": expected, "actual": shape.get(key)})
    if probe.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "probe_active_params_below_1b", "actual": probe.get("active_trainable_parameters")})
    measured = probe.get("estimated_stack_training_tflops_lower_bound")
    required = probe.get("full_config_required_sustained_tflops")
    if not finite_positive(measured) or not finite_positive(required) or measured < required:
        failures.append({"code": "probe_tflops_below_required", "measured": measured, "required": required})

    sampling = receipt.get("power_sampling", {})
    if "nvidia-smi" not in str(sampling.get("sampling_method", "")):
        failures.append({"code": "sampling_method_not_nvidia_smi", "actual": sampling.get("sampling_method")})
    sample_count = sampling.get("sample_count")
    if not isinstance(sample_count, int) or sample_count < 5:
        failures.append({"code": "insufficient_power_samples", "actual": sample_count})
    for field in ("sample_span_s", "avg_power_w", "max_power_w", "energy_joules_trapezoid", "energy_wh", "joules_per_step", "joules_per_training_token"):
        if not finite_positive(sampling.get(field)):
            failures.append({"code": "power_metric_not_positive", "field": field, "actual": sampling.get(field)})
    if not finite_positive(sampling.get("max_temperature_c")):
        failures.append({"code": "max_temperature_invalid", "actual": sampling.get("max_temperature_c")})
    if sampling.get("tokens_accounted") != steps * 2048:
        failures.append({"code": "tokens_accounted_mismatch", "actual": sampling.get("tokens_accounted"), "expected": steps * 2048})
    if sampling.get("includes_child_wall_clock") is not True:
        failures.append({"code": "sampling_not_child_wall_clock"})

    for source, value in (("power_receipt", receipt), ("probe_receipt", probe)):
        leaks = find_local_path_leaks(value)
        if leaks:
            failures.append({"code": "local_path_or_private_name_leak", "source": source, "examples": leaks[:5]})

    limit = str(receipt.get("completion_limit", ""))
    for phrase in ("not days-scale long-run training", "not full-run energy accounting", "not overall baseline completion"):
        if phrase not in limit:
            failures.append({"code": "completion_limit_missing_phrase", "phrase": phrase})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_POWER_SAMPLED_128_WINDOW_THROUGHPUT_VALIDATED" if not failures else "C1_POWER_SAMPLED_128_WINDOW_THROUGHPUT_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "probe_receipt_path": PROBE_RECEIPT,
        "steps_completed": probe.get("steps_completed"),
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "sample_count": sampling.get("sample_count"),
        "energy_joules_trapezoid": sampling.get("energy_joules_trapezoid"),
        "completion_limit": "This validates bounded nvidia-smi power sampling around a 128-window streamed real-token full-stack C1 probe only. It is not days-scale long-run training, not full-run energy accounting, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
