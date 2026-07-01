#!/usr/bin/env python3
"""Validate the C1 integrated streamed train/checkpoint/eval/recovery policy probe."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-integrated-policy-probe-pretraining-equivalent.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def window_hash(row: dict[str, Any], failures: list[dict[str, Any]], label: str) -> str | None:
    if row.get("source") != "pinned_token_shard_stream_loader":
        failures.append({"code": f"{label}_not_stream_loader", "row": row})
    if row.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
        failures.append({"code": f"{label}_not_pinned_shard_receipt", "row": row})
    if row.get("separator_tokens_in_window") != 0:
        failures.append({"code": f"{label}_separator_tokens_present", "row": row})
    digest = row.get("input_tokens_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        failures.append({"code": f"{label}_hash_missing", "row": row})
        return None
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "integrated_probe_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent" or receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "identity_mismatch", "lane": receipt.get("lane"), "params": receipt.get("active_trainable_parameters")})
    if receipt.get("steps_completed") != 8 or receipt.get("uses_real_token_data") is not True or receipt.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "train_step_scope_mismatch", "steps": receipt.get("steps_completed"), "real": receipt.get("uses_real_token_data"), "varied": receipt.get("uses_varied_real_token_windows")})
    if receipt.get("includes_dataloader_timing") is not True or receipt.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "dataloader_timing_not_included"})
    train_hashes: list[str] = []
    for idx, row in enumerate(receipt.get("real_data_windows", [])):
        digest = window_hash(row, failures, f"train_window_{idx}")
        if digest:
            train_hashes.append(digest)
    if len(set(train_hashes)) != 8:
        failures.append({"code": "train_windows_not_unique", "count": len(train_hashes), "unique": len(set(train_hashes))})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "train_losses_not_all_finite"})

    cadence = receipt.get("checkpoint_cadence") or {}
    if cadence.get("enabled") is not True or cadence.get("checkpoint_interval_steps") != 4 or cadence.get("checkpoint_event_count") != 2:
        failures.append({"code": "checkpoint_cadence_scope_mismatch", "cadence": cadence})
    if cadence.get("all_checkpoints_deleted_after_hash") is not True or cadence.get("all_checkpoints_contain_model_state") is not True or cadence.get("all_checkpoints_contain_optimizer_state") is not True:
        failures.append({"code": "checkpoint_cadence_state_or_cleanup_invalid", "cadence": cadence})
    for idx, event in enumerate(cadence.get("checkpoint_events", [])):
        if event.get("checkpoint_path_recorded") is not False or event.get("checkpoint_deleted_after_hash") is not True:
            failures.append({"code": "checkpoint_event_path_or_cleanup_invalid", "idx": idx, "event": event})
        if event.get("checkpoint_after_steps") not in (4, 8) or not finite_positive(event.get("checkpoint_elapsed_s")):
            failures.append({"code": "checkpoint_event_timing_invalid", "idx": idx, "event": event})

    eval_accounting = receipt.get("eval_accounting") or {}
    if eval_accounting.get("enabled") is not True or eval_accounting.get("eval_steps") != 2 or eval_accounting.get("eval_uses_no_grad") is not True:
        failures.append({"code": "eval_accounting_scope_mismatch", "eval": eval_accounting})
    if eval_accounting.get("eval_activation_checkpointing_disabled") is not True or eval_accounting.get("eval_included_in_total_elapsed") is not True:
        failures.append({"code": "eval_mode_or_accounting_invalid", "eval": eval_accounting})
    eval_hashes: list[str] = []
    for idx, row in enumerate(eval_accounting.get("eval_windows", [])):
        digest = window_hash(row, failures, f"eval_window_{idx}")
        if digest:
            eval_hashes.append(digest)
    if len(set(eval_hashes)) != 2 or set(eval_hashes) & set(train_hashes):
        failures.append({"code": "eval_windows_not_unique_or_overlap_train", "eval_count": len(eval_hashes), "eval_unique": len(set(eval_hashes))})
    if eval_accounting.get("eval_loss_is_finite_all_steps") is not True:
        failures.append({"code": "eval_losses_not_all_finite"})

    recovery = receipt.get("recovery_accounting") or {}
    if recovery.get("enabled") is not True or recovery.get("loaded_completed_steps") != 8 or recovery.get("recovery_included_in_total_elapsed") is not True:
        failures.append({"code": "recovery_scope_mismatch", "recovery": recovery})
    if recovery.get("checkpoint_deleted_after_hash") is not True or recovery.get("checkpoint_contains_model_state") is not True or recovery.get("checkpoint_contains_optimizer_state") is not True:
        failures.append({"code": "recovery_checkpoint_invalid", "recovery": recovery})
    if recovery.get("checkpoint_path_recorded") is not False or recovery.get("local_path_recorded") is not False:
        failures.append({"code": "recovery_path_policy_invalid", "recovery": recovery})
    if recovery.get("recovery_window_base") != 10:
        failures.append({"code": "recovery_window_base_not_after_eval", "actual": recovery.get("recovery_window_base")})
    recovery_train_hash = window_hash(recovery.get("post_recovery_train_window") or {}, failures, "post_recovery_train")
    recovery_eval_hash = window_hash(recovery.get("post_recovery_eval_window") or {}, failures, "post_recovery_eval")
    all_prior = set(train_hashes) | set(eval_hashes)
    if not recovery_train_hash or not recovery_eval_hash or recovery_train_hash == recovery_eval_hash or recovery_train_hash in all_prior or recovery_eval_hash in all_prior:
        failures.append({"code": "recovery_windows_overlap_prior_or_each_other"})
    for key in ("post_recovery_train_elapsed_s", "post_recovery_eval_elapsed_s", "recovery_elapsed_s", "recovery_load_elapsed_s"):
        if not finite_positive(recovery.get(key)):
            failures.append({"code": f"{key}_invalid", "actual": recovery.get(key)})
    for key in ("checkpoint_elapsed_s", "eval_elapsed_s", "recovery_elapsed_s", "elapsed_s"):
        if not finite_positive(receipt.get(key)):
            failures.append({"code": f"top_level_{key}_invalid", "actual": receipt.get(key)})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not finite_positive(measured) or not finite_positive(required) or measured >= required:
        failures.append({"code": "integrated_probe_must_preserve_overhead_gap", "measured": measured, "required": required})
    if "not a long-run 1B language-model training receipt" not in str(receipt.get("completion_limit", "")) or "not family completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_INTEGRATED_POLICY_PROBE_VALIDATED" if not failures else "C1_INTEGRATED_POLICY_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "checkpoint_event_count": cadence.get("checkpoint_event_count"),
        "eval_window_count": eval_accounting.get("eval_window_count"),
        "recovery_window_base": recovery.get("recovery_window_base"),
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates one bounded integrated streamed train/checkpoint/eval/recovery policy probe only. It is not long-run throughput, not external evaluation, not convergence, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
