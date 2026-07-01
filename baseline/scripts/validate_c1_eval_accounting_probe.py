#!/usr/bin/env python3
"""Validate bounded C1 streamed real-token evaluation-accounting evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-eval-accounting-probe-pretraining-equivalent.json"


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
        failures.append({"code": "eval_accounting_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_not_pretraining_equivalent", "actual": receipt.get("lane")})
    if receipt.get("uses_real_token_data") is not True or receipt.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "not_streamed_varied_real_token_data"})
    if receipt.get("includes_dataloader_timing") is not True or receipt.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "dataloader_timing_not_included"})
    if receipt.get("steps_completed") != 4:
        failures.append({"code": "steps_completed_mismatch", "actual": receipt.get("steps_completed")})
    eval_accounting = receipt.get("eval_accounting") or {}
    if eval_accounting.get("enabled") is not True:
        failures.append({"code": "eval_accounting_not_enabled", "eval_accounting": eval_accounting})
    if eval_accounting.get("eval_steps") != 2 or eval_accounting.get("eval_window_count") != 2 or eval_accounting.get("eval_unique_input_window_count") != 2:
        failures.append({"code": "eval_step_or_window_count_mismatch", "eval_accounting": eval_accounting})
    if eval_accounting.get("eval_uses_no_grad") is not True or eval_accounting.get("eval_activation_checkpointing_disabled") is not True:
        failures.append({"code": "eval_execution_mode_not_locked", "eval_accounting": eval_accounting})
    if eval_accounting.get("eval_included_in_total_elapsed") is not True:
        failures.append({"code": "eval_not_included_in_total_elapsed", "eval_accounting": eval_accounting})
    if eval_accounting.get("local_path_recorded") is not False:
        failures.append({"code": "eval_local_path_policy_invalid", "eval_accounting": eval_accounting})
    eval_losses = eval_accounting.get("eval_losses")
    if not isinstance(eval_losses, list) or len(eval_losses) != 2:
        failures.append({"code": "eval_losses_missing_or_wrong_length", "eval_losses": eval_losses})
    elif any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) <= 0 for x in eval_losses):
        failures.append({"code": "eval_losses_nonfinite_or_nonpositive", "eval_losses": eval_losses})
    if eval_accounting.get("eval_loss_is_finite_all_steps") is not True:
        failures.append({"code": "eval_loss_finite_flag_not_true"})
    eval_elapsed = receipt.get("eval_elapsed_s")
    eval_fraction = receipt.get("eval_elapsed_fraction")
    if not isinstance(eval_elapsed, (int, float)) or not math.isfinite(float(eval_elapsed)) or float(eval_elapsed) <= 0:
        failures.append({"code": "eval_elapsed_missing_or_invalid", "actual": eval_elapsed})
    if not isinstance(eval_fraction, (int, float)) or not math.isfinite(float(eval_fraction)) or float(eval_fraction) <= 0:
        failures.append({"code": "eval_fraction_missing_or_invalid", "actual": eval_fraction})
    windows = eval_accounting.get("eval_windows")
    if not isinstance(windows, list) or len(windows) != 2:
        failures.append({"code": "eval_windows_missing_or_wrong_length", "windows": windows})
    else:
        starts = []
        hashes = []
        for index, window in enumerate(windows):
            if window.get("eval_window_index") != index:
                failures.append({"code": "eval_window_index_mismatch", "index": index, "window": window})
            if window.get("source") != "pinned_token_shard_stream_loader":
                failures.append({"code": "eval_window_source_not_stream_loader", "index": index, "source": window.get("source")})
            if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
                failures.append({"code": "eval_window_shard_receipt_not_pinned", "index": index, "actual": window.get("token_shard_receipt")})
            if window.get("separator_tokens_in_window") != 0:
                failures.append({"code": "separator_tokens_in_eval_window", "index": index, "actual": window.get("separator_tokens_in_window")})
            start = window.get("stream_token_start")
            token_hash = window.get("input_tokens_sha256")
            if isinstance(start, int):
                starts.append(start)
            else:
                failures.append({"code": "eval_window_start_missing", "index": index, "actual": start})
            if isinstance(token_hash, str) and len(token_hash) == 64:
                hashes.append(token_hash)
            else:
                failures.append({"code": "eval_window_input_hash_missing", "index": index, "actual": token_hash})
        if len(set(starts)) != len(starts):
            failures.append({"code": "eval_window_starts_not_unique", "starts": starts})
        if len(set(hashes)) != len(hashes):
            failures.append({"code": "eval_window_hashes_not_unique"})
        train_hashes = {row.get("input_tokens_sha256") for row in receipt.get("real_data_windows", []) if isinstance(row, dict)}
        if train_hashes.intersection(hashes):
            failures.append({"code": "eval_windows_overlap_training_windows"})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or not isinstance(required, (int, float)):
        failures.append({"code": "throughput_fields_missing", "measured": measured, "required": required})
    elif measured >= required:
        failures.append({"code": "eval_accounting_probe_should_not_clear_throughput_gate", "measured": measured, "required": required})
    losses = receipt.get("loss_values")
    if not isinstance(losses, list) or len(losses) != receipt.get("steps_completed"):
        failures.append({"code": "train_loss_values_missing_or_length_mismatch"})
    elif any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) <= 0 for x in losses):
        failures.append({"code": "train_losses_nonfinite_or_nonpositive"})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "train_loss_finite_flag_not_true"})
    guard = str(receipt.get("completion_limit", ""))
    for term in ("bounded eval-accounting telemetry only", "not a full external evaluation suite", "not family completion"):
        if term not in guard:
            failures.append({"code": "completion_limit_missing_guard_term", "term": term})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_EVAL_ACCOUNTING_PROBE_VALIDATED" if not failures else "C1_EVAL_ACCOUNTING_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_eval_accounting_probe_validation",
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "eval_steps": eval_accounting.get("eval_steps"),
        "eval_elapsed_s": eval_elapsed,
        "eval_elapsed_fraction": eval_fraction,
        "eval_loss_mean": eval_accounting.get("eval_loss_mean"),
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates bounded no-grad LM-head eval accounting on streamed real-token windows only. It is not a full external evaluation suite, recovery accounting, data-hygiene PASS, throughput completion, or overall baseline completion receipt.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
