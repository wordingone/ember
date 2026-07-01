#!/usr/bin/env python3
"""Validate bounded C1 streamed recovery-accounting evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-recovery-accounting-probe-pretraining-equivalent.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _check_window(window: dict[str, Any], failures: list[dict[str, Any]], label: str) -> str | None:
    if window.get("source") != "pinned_token_shard_stream_loader":
        failures.append({"code": f"{label}_source_not_stream_loader", "source": window.get("source")})
    if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
        failures.append({"code": f"{label}_shard_receipt_not_pinned", "actual": window.get("token_shard_receipt")})
    if window.get("separator_tokens_in_window") != 0:
        failures.append({"code": f"{label}_separator_tokens_present", "actual": window.get("separator_tokens_in_window")})
    token_hash = window.get("input_tokens_sha256")
    if not isinstance(token_hash, str) or len(token_hash) != 64:
        failures.append({"code": f"{label}_input_hash_missing", "actual": token_hash})
        return None
    return token_hash


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
        failures.append({"code": "recovery_accounting_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_not_pretraining_equivalent", "actual": receipt.get("lane")})
    if receipt.get("uses_real_token_data") is not True or receipt.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "not_streamed_varied_real_token_data"})
    if receipt.get("includes_dataloader_timing") is not True or receipt.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "dataloader_timing_not_included"})
    if receipt.get("steps_completed") != 2:
        failures.append({"code": "steps_completed_mismatch", "actual": receipt.get("steps_completed")})
    recovery = receipt.get("recovery_accounting") or {}
    if recovery.get("enabled") is not True:
        failures.append({"code": "recovery_accounting_not_enabled", "recovery": recovery})
    if recovery.get("checkpoint_contains_model_state") is not True or recovery.get("checkpoint_contains_optimizer_state") is not True:
        failures.append({"code": "recovery_checkpoint_missing_state", "recovery": recovery})
    if recovery.get("checkpoint_path_recorded") is not False or recovery.get("local_path_recorded") is not False:
        failures.append({"code": "recovery_public_path_policy_invalid", "recovery": recovery})
    if recovery.get("checkpoint_deleted_after_hash") is not True:
        failures.append({"code": "recovery_checkpoint_not_deleted", "recovery": recovery})
    if not isinstance(recovery.get("checkpoint_sha256"), str) or len(recovery["checkpoint_sha256"]) != 64:
        failures.append({"code": "recovery_checkpoint_hash_missing", "recovery": recovery})
    if not isinstance(recovery.get("checkpoint_size_bytes"), int) or recovery["checkpoint_size_bytes"] <= 1_000_000_000:
        failures.append({"code": "recovery_checkpoint_size_too_small", "recovery": recovery})
    if recovery.get("loaded_completed_steps") != 2 or recovery.get("loaded_seed") != receipt.get("seed") or recovery.get("loaded_lane") != receipt.get("lane"):
        failures.append({"code": "recovery_loaded_identity_mismatch", "recovery": recovery})
    for key in ("recovery_load_elapsed_s", "post_recovery_train_elapsed_s", "post_recovery_eval_elapsed_s", "recovery_elapsed_s"):
        value = recovery.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            failures.append({"code": f"{key}_missing_or_invalid", "actual": value})
    if recovery.get("recovery_included_in_total_elapsed") is not True:
        failures.append({"code": "recovery_not_included_in_total_elapsed", "recovery": recovery})
    recovery_elapsed = receipt.get("recovery_elapsed_s")
    recovery_fraction = receipt.get("recovery_elapsed_fraction")
    if not isinstance(recovery_elapsed, (int, float)) or float(recovery_elapsed) <= 0:
        failures.append({"code": "top_level_recovery_elapsed_invalid", "actual": recovery_elapsed})
    if not isinstance(recovery_fraction, (int, float)) or float(recovery_fraction) <= 0.5:
        failures.append({"code": "recovery_fraction_not_accounted", "actual": recovery_fraction})
    train_loss = recovery.get("post_recovery_train_loss")
    eval_loss = recovery.get("post_recovery_eval_loss")
    if not isinstance(train_loss, (int, float)) or not math.isfinite(float(train_loss)) or float(train_loss) <= 0:
        failures.append({"code": "post_recovery_train_loss_invalid", "actual": train_loss})
    if not isinstance(eval_loss, (int, float)) or not math.isfinite(float(eval_loss)) or float(eval_loss) <= 0:
        failures.append({"code": "post_recovery_eval_loss_invalid", "actual": eval_loss})
    if recovery.get("post_recovery_eval_uses_no_grad") is not True or recovery.get("post_recovery_eval_activation_checkpointing_disabled") is not True:
        failures.append({"code": "post_recovery_eval_mode_invalid", "recovery": recovery})
    train_hash = _check_window(recovery.get("post_recovery_train_window") or {}, failures, "post_recovery_train_window")
    eval_hash = _check_window(recovery.get("post_recovery_eval_window") or {}, failures, "post_recovery_eval_window")
    train_hashes = {row.get("input_tokens_sha256") for row in receipt.get("real_data_windows", []) if isinstance(row, dict)}
    if train_hash in train_hashes or eval_hash in train_hashes or train_hash == eval_hash:
        failures.append({"code": "post_recovery_windows_not_distinct_from_train_or_each_other"})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or not isinstance(required, (int, float)):
        failures.append({"code": "throughput_fields_missing", "measured": measured, "required": required})
    elif measured >= required:
        failures.append({"code": "recovery_probe_should_not_clear_throughput_gate", "measured": measured, "required": required})
    guard = str(receipt.get("completion_limit", ""))
    for term in ("bounded recovery-accounting telemetry only", "not a long-run recovery policy receipt", "not family completion"):
        if term not in guard:
            failures.append({"code": "completion_limit_missing_guard_term", "term": term})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_RECOVERY_ACCOUNTING_PROBE_VALIDATED" if not failures else "C1_RECOVERY_ACCOUNTING_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_recovery_accounting_probe_validation",
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "recovery_elapsed_s": recovery_elapsed,
        "recovery_elapsed_fraction": recovery_fraction,
        "post_recovery_train_loss": train_loss,
        "post_recovery_eval_loss": eval_loss,
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates bounded checkpoint recovery plus post-recovery train/eval accounting only. It is not a long-run recovery policy, full external evaluation suite, data-hygiene PASS, throughput completion, or overall baseline completion receipt.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
