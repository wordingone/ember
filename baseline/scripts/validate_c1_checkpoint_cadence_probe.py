#!/usr/bin/env python3
"""Validate bounded C1 streamed real-token checkpoint-cadence evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-checkpoint-cadence-probe-pretraining-equivalent.json"


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
        failures.append({"code": "checkpoint_cadence_receipt_missing", "path": RECEIPT})
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
    if receipt.get("real_data_window_count") != 4 or receipt.get("real_data_unique_input_window_count") != 4:
        failures.append({"code": "real_data_window_count_mismatch", "count": receipt.get("real_data_window_count"), "unique": receipt.get("real_data_unique_input_window_count")})
    ckpt = receipt.get("checkpoint_cadence") or {}
    if ckpt.get("enabled") is not True:
        failures.append({"code": "checkpoint_cadence_not_enabled", "checkpoint_cadence": ckpt})
    if ckpt.get("checkpoint_interval_steps") != 2 or ckpt.get("checkpoint_event_count") != 2:
        failures.append({"code": "checkpoint_cadence_count_or_interval_mismatch", "checkpoint_cadence": ckpt})
    if ckpt.get("checkpoint_path_recorded") is not False:
        failures.append({"code": "checkpoint_public_path_policy_invalid", "checkpoint_cadence": ckpt})
    if ckpt.get("all_checkpoints_deleted_after_hash") is not True:
        failures.append({"code": "not_all_checkpoints_deleted", "checkpoint_cadence": ckpt})
    if ckpt.get("all_checkpoints_contain_model_state") is not True or ckpt.get("all_checkpoints_contain_optimizer_state") is not True:
        failures.append({"code": "checkpoint_missing_model_or_optimizer_state", "checkpoint_cadence": ckpt})
    events = ckpt.get("checkpoint_events")
    if not isinstance(events, list) or len(events) != 2:
        failures.append({"code": "checkpoint_events_missing_or_wrong_length", "events": events})
    else:
        expected_steps = [2, 4]
        hashes = []
        for index, event in enumerate(events):
            if event.get("checkpoint_index") != index or event.get("checkpoint_after_steps") != expected_steps[index]:
                failures.append({"code": "checkpoint_event_step_mismatch", "index": index, "event": event})
            if event.get("loaded_completed_steps") != expected_steps[index] or event.get("loaded_seed") != receipt.get("seed") or event.get("loaded_lane") != receipt.get("lane"):
                failures.append({"code": "checkpoint_event_loaded_identity_mismatch", "index": index, "event": event})
            if event.get("checkpoint_path_recorded") is not False or event.get("checkpoint_deleted_after_hash") is not True:
                failures.append({"code": "checkpoint_event_path_or_cleanup_invalid", "index": index, "event": event})
            if event.get("checkpoint_contains_model_state") is not True or event.get("checkpoint_contains_optimizer_state") is not True:
                failures.append({"code": "checkpoint_event_missing_state", "index": index, "event": event})
            if not isinstance(event.get("checkpoint_sha256"), str) or len(event["checkpoint_sha256"]) != 64:
                failures.append({"code": "checkpoint_event_hash_missing", "index": index, "event": event})
            else:
                hashes.append(event["checkpoint_sha256"])
            if not isinstance(event.get("checkpoint_size_bytes"), int) or event["checkpoint_size_bytes"] <= 1_000_000_000:
                failures.append({"code": "checkpoint_event_size_too_small", "index": index, "event": event})
            if not isinstance(event.get("checkpoint_elapsed_s"), (int, float)) or event["checkpoint_elapsed_s"] <= 0:
                failures.append({"code": "checkpoint_event_elapsed_invalid", "index": index, "event": event})
        if len(set(hashes)) != len(hashes):
            failures.append({"code": "checkpoint_hashes_not_unique"})
    ckpt_elapsed = receipt.get("checkpoint_elapsed_s")
    ckpt_fraction = receipt.get("checkpoint_elapsed_fraction")
    if not isinstance(ckpt_elapsed, (int, float)) or not math.isfinite(float(ckpt_elapsed)) or float(ckpt_elapsed) <= 0:
        failures.append({"code": "checkpoint_elapsed_missing_or_invalid", "actual": ckpt_elapsed})
    if not isinstance(ckpt_fraction, (int, float)) or not math.isfinite(float(ckpt_fraction)) or float(ckpt_fraction) <= 0.5:
        failures.append({"code": "checkpoint_fraction_not_accounted", "actual": ckpt_fraction})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or not isinstance(required, (int, float)):
        failures.append({"code": "throughput_fields_missing", "measured": measured, "required": required})
    elif measured >= required:
        failures.append({"code": "cadence_probe_should_not_clear_throughput_gate", "measured": measured, "required": required})
    losses = receipt.get("loss_values")
    if not isinstance(losses, list) or len(losses) != receipt.get("steps_completed"):
        failures.append({"code": "loss_values_missing_or_length_mismatch"})
    elif any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) <= 0 for x in losses):
        failures.append({"code": "nonfinite_or_nonpositive_loss"})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "loss_finite_flag_not_true"})
    guard = str(receipt.get("completion_limit", ""))
    for term in ("bounded checkpoint-cadence telemetry only", "not a long-run checkpoint policy receipt", "not family completion"):
        if term not in guard:
            failures.append({"code": "completion_limit_missing_guard_term", "term": term})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CHECKPOINT_CADENCE_PROBE_VALIDATED" if not failures else "C1_CHECKPOINT_CADENCE_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_checkpoint_cadence_probe_validation",
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "checkpoint_event_count": ckpt.get("checkpoint_event_count"),
        "checkpoint_elapsed_s": ckpt_elapsed,
        "checkpoint_elapsed_fraction": ckpt_fraction,
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates bounded repeated checkpoint save/hash/reload/delete mechanics with streamed real-token steps only. It is not a long-run checkpoint policy, recovery, evaluation, throughput-completion, data-hygiene PASS, or overall baseline completion receipt.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
