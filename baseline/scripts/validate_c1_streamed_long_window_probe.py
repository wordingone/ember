#!/usr/bin/env python3
"""Validate the C1 128-window streamed real-token throughput probe.

This is a longer bounded telemetry validator. It intentionally does not turn
128 streamed windows into days-scale training completion.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-streamed-128-window-throughput-probe-pretraining-equivalent.json"
EXPECTED_VERDICT = "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION"
MIN_STEPS = 128


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "long_window_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_mismatch", "actual": receipt.get("lane")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "active_params_below_1b", "actual": receipt.get("active_trainable_parameters")})
    completed = receipt.get("steps_completed") if isinstance(receipt.get("steps_completed"), int) else 0
    requested = receipt.get("steps_requested") if isinstance(receipt.get("steps_requested"), int) else 0
    if completed < MIN_STEPS or requested < MIN_STEPS:
        failures.append({"code": "insufficient_steps", "completed": receipt.get("steps_completed"), "requested": receipt.get("steps_requested")})
    if receipt.get("uses_real_token_data") is not True or receipt.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "real_varied_windows_not_enabled", "real": receipt.get("uses_real_token_data"), "varied": receipt.get("uses_varied_real_token_windows")})
    if receipt.get("includes_dataloader_timing") is not True or receipt.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "dataloader_timing_not_included"})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "loss_not_finite_all_steps"})

    shape = receipt.get("probe_shape", {})
    expected_shape = {"seq_len": 2048, "hidden": 2048, "heads": 16, "layers_executed": 19}
    for key, expected in expected_shape.items():
        if shape.get(key) != expected:
            failures.append({"code": "shape_mismatch", "key": key, "expected": expected, "actual": shape.get(key)})
    if shape.get("full_model_active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "shape_params_below_1b", "actual": shape.get("full_model_active_trainable_parameters")})

    windows = receipt.get("real_data_windows", [])
    hashes = [row.get("input_tokens_sha256") for row in windows]
    if len(windows) != completed or len(windows) < MIN_STEPS:
        failures.append({"code": "window_count_mismatch", "windows": len(windows), "steps": receipt.get("steps_completed")})
    if len(set(hashes)) != len(hashes):
        failures.append({"code": "window_hashes_not_unique", "count": len(hashes), "unique": len(set(hashes))})
    for idx, row in enumerate(windows):
        if row.get("source") != "pinned_token_shard_stream_loader":
            failures.append({"code": "window_not_stream_loader", "idx": idx})
            break
        if row.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
            failures.append({"code": "window_not_pinned_shard_receipt", "idx": idx})
            break
        if row.get("separator_tokens_in_window") != 0:
            failures.append({"code": "window_separator_tokens_present", "idx": idx})
            break
        digest = row.get("input_tokens_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            failures.append({"code": "window_hash_invalid", "idx": idx})
            break

    stream = receipt.get("real_data_stream", {})
    if stream.get("sha256_verified_before_timing") is not True or stream.get("window_search_and_tensor_source_inside_timed_step") is not True:
        failures.append({"code": "stream_loader_controls_missing", "stream": stream})
    if stream.get("local_path_recorded") is not False:
        failures.append({"code": "stream_local_path_policy_invalid", "stream": stream})

    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not finite_positive(measured) or not finite_positive(required) or measured < required:
        failures.append({"code": "long_window_throughput_below_required", "measured": measured, "required": required})
    if not finite_positive(receipt.get("elapsed_s")) or not finite_positive(receipt.get("tokens_per_second")):
        failures.append({"code": "elapsed_or_token_rate_invalid", "elapsed": receipt.get("elapsed_s"), "tokens_per_second": receipt.get("tokens_per_second")})
    if receipt.get("checkpoint_cadence") is not None or receipt.get("eval_accounting") is not None or receipt.get("recovery_accounting") is not None:
        failures.append({"code": "unexpected_policy_accounting_enabled"})
    limit = str(receipt.get("completion_limit", ""))
    for phrase in ("not a long-run training receipt", "not full-data coverage", "not family completion"):
        if phrase not in limit:
            failures.append({"code": "completion_limit_missing_phrase", "phrase": phrase})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_STREAMED_128_WINDOW_THROUGHPUT_VALIDATED" if not failures else "C1_STREAMED_128_WINDOW_THROUGHPUT_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "unique_window_count": len(set(hashes)) if hashes else 0,
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates 128 streamed real-token full-stack windows only. It is not days-scale long-run training, not full-data coverage, not convergence, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
