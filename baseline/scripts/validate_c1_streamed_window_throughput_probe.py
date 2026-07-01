#!/usr/bin/env python3
"""Validate bounded C1 dataloader-inclusive streamed real-token throughput evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-streamed-window-throughput-probe-pretraining-equivalent.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    path = root / RECEIPT
    receipt = read_json(path) if path.exists() else {}
    if not receipt:
        failures.append({"code": "streamed_window_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_not_pretraining_equivalent", "actual": receipt.get("lane")})
    if receipt.get("uses_real_token_data") is not True:
        failures.append({"code": "not_real_token_data"})
    if receipt.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "varied_window_flag_not_true"})
    if receipt.get("includes_dataloader_timing") is not True or receipt.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "dataloader_timing_not_included", "includes": receipt.get("includes_dataloader_timing"), "inside_step": receipt.get("dataloader_window_loaded_inside_timed_step")})
    stream = receipt.get("real_data_stream") or {}
    if stream.get("window_search_and_tensor_source_inside_timed_step") is not True or stream.get("local_path_recorded") is not False:
        failures.append({"code": "stream_loader_contract_invalid", "stream": stream})
    if stream.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
        failures.append({"code": "stream_loader_shard_receipt_not_pinned", "actual": stream.get("token_shard_receipt")})
    steps = receipt.get("steps_completed")
    if not isinstance(steps, int) or steps < 16:
        failures.append({"code": "too_few_steps_completed", "actual": steps})
    if receipt.get("real_data_window_count") != steps:
        failures.append({"code": "window_count_does_not_match_steps", "windows": receipt.get("real_data_window_count"), "steps": steps})
    if receipt.get("real_data_unique_input_window_count") != steps:
        failures.append({"code": "unique_window_count_does_not_match_steps", "unique": receipt.get("real_data_unique_input_window_count"), "steps": steps})
    windows = receipt.get("real_data_windows")
    if not isinstance(windows, list) or len(windows) != steps:
        failures.append({"code": "real_data_windows_missing_or_length_mismatch"})
    else:
        starts = []
        hashes = []
        for index, window in enumerate(windows):
            if window.get("window_index") != index:
                failures.append({"code": "window_index_mismatch", "index": index, "window": window.get("window_index")})
            if window.get("source") != "pinned_token_shard_stream_loader":
                failures.append({"code": "window_source_not_stream_loader", "index": index, "source": window.get("source")})
            if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
                failures.append({"code": "window_shard_receipt_not_pinned", "index": index, "actual": window.get("token_shard_receipt")})
            if window.get("separator_tokens_in_window") != 0:
                failures.append({"code": "separator_tokens_in_window", "index": index, "actual": window.get("separator_tokens_in_window")})
            start = window.get("stream_token_start")
            token_hash = window.get("input_tokens_sha256")
            if not isinstance(start, int):
                failures.append({"code": "window_start_missing", "index": index, "actual": start})
            else:
                starts.append(start)
            if not isinstance(token_hash, str) or len(token_hash) != 64:
                failures.append({"code": "window_input_hash_missing", "index": index, "actual": token_hash})
            else:
                hashes.append(token_hash)
        if len(set(starts)) != len(starts):
            failures.append({"code": "window_starts_not_unique", "starts": starts})
        if len(set(hashes)) != len(hashes):
            failures.append({"code": "window_input_hashes_not_unique"})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or not isinstance(required, (int, float)) or measured < required:
        failures.append({"code": "streamed_window_did_not_clear_required_tflops", "measured": measured, "required": required})
    loader_s = receipt.get("dataloader_elapsed_s")
    loader_fraction = receipt.get("dataloader_elapsed_fraction")
    step_times = receipt.get("dataloader_step_times_s")
    if not isinstance(loader_s, (int, float)) or not math.isfinite(float(loader_s)) or float(loader_s) <= 0:
        failures.append({"code": "dataloader_elapsed_missing_or_nonpositive", "actual": loader_s})
    if not isinstance(loader_fraction, (int, float)) or not math.isfinite(float(loader_fraction)) or float(loader_fraction) <= 0:
        failures.append({"code": "dataloader_fraction_missing_or_nonpositive", "actual": loader_fraction})
    if not isinstance(step_times, list) or len(step_times) != steps or any(not isinstance(x, (int, float)) or float(x) <= 0 for x in step_times):
        failures.append({"code": "dataloader_step_times_invalid"})
    losses = receipt.get("loss_values")
    if not isinstance(losses, list) or len(losses) != steps:
        failures.append({"code": "loss_values_missing_or_length_mismatch"})
    elif any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) <= 0 for x in losses):
        failures.append({"code": "nonfinite_or_nonpositive_loss"})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "loss_finite_flag_not_true"})
    guard = str(receipt.get("completion_limit", ""))
    for term in ("bounded dataloader-inclusive varied-window throughput telemetry", "not a long-run training receipt", "not family completion"):
        if term not in guard:
            failures.append({"code": "completion_limit_missing_guard_term", "term": term})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_STREAMED_WINDOW_THROUGHPUT_PROBE_VALIDATED" if not failures else "C1_STREAMED_WINDOW_THROUGHPUT_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_streamed_window_throughput_probe_validation",
        "receipt_path": RECEIPT,
        "steps_completed": steps,
        "real_data_window_count": receipt.get("real_data_window_count"),
        "unique_real_data_window_count": receipt.get("real_data_unique_input_window_count"),
        "dataloader_elapsed_s": loader_s,
        "dataloader_elapsed_fraction": loader_fraction,
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates bounded streamed real-token throughput telemetry with per-step loader timing only. It is not full-shard dataloader coverage, checkpoint cadence, evaluation, recovery, data-hygiene PASS, or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
