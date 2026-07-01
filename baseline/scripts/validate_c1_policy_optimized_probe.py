#!/usr/bin/env python3
"""Validate the C1 policy-optimized 1024-window streamed probe.

This validator requires real train/checkpoint/eval/recovery/power accounting at
larger bounded scale with overhead amortized across 1024 train windows. It does not treat the measured result as C1 completion.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_RECEIPT = "receipts/4090-policy-optimized-1024-window-probe-pretraining-equivalent.json"
POWER_RECEIPT = "receipts/4090-policy-optimized-1024-window-power-2026-06-30.json"
EXPECTED_POWER_VERDICT = "C1_POLICY_OPTIMIZED_1024_WINDOW_READY_NOT_COMPLETION"
MIN_STEPS = 1024
CHECKPOINT_INTERVAL = 1024
EVAL_STEPS = 4
PRIVATE_NAME_PATTERNS = ["av" + "ir", "le" + "o", "ka" + "i", "cla" + "ude", "wording" + "one"]
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[/\\]|Users[/\\]Admin|" + "|".join(r"\b" + item + r"\b" for item in PRIVATE_NAME_PATTERNS) + r")", re.IGNORECASE)


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


def window_hash(row: dict[str, Any], failures: list[dict[str, Any]], label: str) -> str | None:
    if row.get("source") != "pinned_token_shard_stream_loader":
        failures.append({"code": f"{label}_not_stream_loader"})
    if row.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
        failures.append({"code": f"{label}_not_pinned_shard_receipt"})
    if row.get("separator_tokens_in_window") != 0:
        failures.append({"code": f"{label}_separator_tokens_present"})
    digest = row.get("input_tokens_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        failures.append({"code": f"{label}_hash_missing"})
        return None
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    probe_path = root / PROBE_RECEIPT
    power_path = root / POWER_RECEIPT
    probe = read_json(probe_path) if probe_path.exists() else {}
    power = read_json(power_path) if power_path.exists() else {}
    failures: list[dict[str, Any]] = []

    if not probe_path.exists():
        failures.append({"code": "probe_receipt_missing", "path": PROBE_RECEIPT})
    if not power_path.exists():
        failures.append({"code": "power_receipt_missing", "path": POWER_RECEIPT})
    if power.get("verdict") != EXPECTED_POWER_VERDICT:
        failures.append({"code": "power_receipt_bad_verdict", "actual": power.get("verdict")})
    if power.get("child_returncode") != 0:
        failures.append({"code": "child_returncode_nonzero", "actual": power.get("child_returncode")})
    if power.get("probe_receipt", {}).get("repo_path") != PROBE_RECEIPT:
        failures.append({"code": "probe_receipt_repo_path_mismatch", "actual": power.get("probe_receipt", {}).get("repo_path")})

    if probe.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "probe_bad_verdict", "actual": probe.get("verdict")})
    if probe.get("lane") != "pretraining_equivalent" or probe.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "identity_mismatch", "lane": probe.get("lane"), "params": probe.get("active_trainable_parameters")})
    steps = probe.get("steps_completed") if isinstance(probe.get("steps_completed"), int) else 0
    if steps < MIN_STEPS or probe.get("steps_requested", 0) < MIN_STEPS:
        failures.append({"code": "insufficient_train_steps", "completed": probe.get("steps_completed"), "requested": probe.get("steps_requested")})
    if probe.get("uses_real_token_data") is not True or probe.get("uses_varied_real_token_windows") is not True:
        failures.append({"code": "probe_not_real_varied"})
    if probe.get("includes_dataloader_timing") is not True or probe.get("dataloader_window_loaded_inside_timed_step") is not True:
        failures.append({"code": "dataloader_timing_not_included"})
    if probe.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "train_losses_not_finite"})

    train_hashes = []
    for idx, row in enumerate(probe.get("real_data_windows", [])):
        if isinstance(row, dict):
            digest = window_hash(row, failures, f"train_window_{idx}")
            if digest:
                train_hashes.append(digest)
    if len(train_hashes) != steps or len(set(train_hashes)) != len(train_hashes) or len(set(train_hashes)) < MIN_STEPS:
        failures.append({"code": "train_windows_not_unique_or_insufficient", "count": len(train_hashes), "unique": len(set(train_hashes)), "steps": steps})

    shape = probe.get("probe_shape", {}) if isinstance(probe.get("probe_shape"), dict) else {}
    if shape.get("seq_len") != 2048 or shape.get("hidden") != 2048 or shape.get("heads") != 16 or shape.get("layers_executed") != 19:
        failures.append({"code": "shape_mismatch", "shape": shape})

    cadence = probe.get("checkpoint_cadence") or {}
    if cadence.get("enabled") is not True or cadence.get("checkpoint_interval_steps") != CHECKPOINT_INTERVAL or cadence.get("checkpoint_event_count") < 1:
        failures.append({"code": "checkpoint_cadence_scope_mismatch", "cadence": cadence})
    if cadence.get("all_checkpoints_deleted_after_hash") is not True or cadence.get("all_checkpoints_contain_model_state") is not True or cadence.get("all_checkpoints_contain_optimizer_state") is not True:
        failures.append({"code": "checkpoint_cadence_state_or_cleanup_invalid", "cadence": cadence})
    checkpoint_events = cadence.get("checkpoint_events", []) if isinstance(cadence.get("checkpoint_events"), list) else []
    checkpoint_steps = [event.get("checkpoint_after_steps") for event in checkpoint_events if isinstance(event, dict)]
    if CHECKPOINT_INTERVAL not in checkpoint_steps or MIN_STEPS not in checkpoint_steps:
        failures.append({"code": "checkpoint_steps_not_amortized_scope", "checkpoint_steps": checkpoint_steps})

    eval_accounting = probe.get("eval_accounting") or {}
    if eval_accounting.get("enabled") is not True or eval_accounting.get("eval_steps") != EVAL_STEPS or eval_accounting.get("eval_window_count") != EVAL_STEPS:
        failures.append({"code": "eval_accounting_scope_mismatch", "eval": eval_accounting})
    if eval_accounting.get("eval_uses_no_grad") is not True or eval_accounting.get("eval_included_in_total_elapsed") is not True:
        failures.append({"code": "eval_mode_or_accounting_invalid", "eval": eval_accounting})
    if eval_accounting.get("eval_loss_is_finite_all_steps") is not True:
        failures.append({"code": "eval_losses_not_finite"})
    eval_hashes = []
    for idx, row in enumerate(eval_accounting.get("eval_windows", [])):
        if isinstance(row, dict):
            digest = window_hash(row, failures, f"eval_window_{idx}")
            if digest:
                eval_hashes.append(digest)
    if len(set(eval_hashes)) != EVAL_STEPS or set(eval_hashes) & set(train_hashes):
        failures.append({"code": "eval_windows_not_unique_or_overlap_train", "eval_count": len(eval_hashes), "eval_unique": len(set(eval_hashes))})

    recovery = probe.get("recovery_accounting") or {}
    if recovery.get("enabled") is not True or recovery.get("loaded_completed_steps") != steps or recovery.get("recovery_included_in_total_elapsed") is not True:
        failures.append({"code": "recovery_scope_mismatch", "recovery": recovery})
    if recovery.get("checkpoint_deleted_after_hash") is not True or recovery.get("checkpoint_contains_model_state") is not True or recovery.get("checkpoint_contains_optimizer_state") is not True:
        failures.append({"code": "recovery_checkpoint_invalid", "recovery": recovery})
    if recovery.get("checkpoint_path_recorded") is not False or recovery.get("local_path_recorded") is not False:
        failures.append({"code": "recovery_path_policy_invalid", "recovery": recovery})
    if recovery.get("recovery_window_base") != steps + EVAL_STEPS:
        failures.append({"code": "recovery_window_base_mismatch", "expected": steps + EVAL_STEPS, "actual": recovery.get("recovery_window_base")})
    rec_train_hash = window_hash(recovery.get("post_recovery_train_window") or {}, failures, "post_recovery_train")
    rec_eval_hash = window_hash(recovery.get("post_recovery_eval_window") or {}, failures, "post_recovery_eval")
    prior = set(train_hashes) | set(eval_hashes)
    if not rec_train_hash or not rec_eval_hash or rec_train_hash == rec_eval_hash or rec_train_hash in prior or rec_eval_hash in prior:
        failures.append({"code": "recovery_windows_overlap_prior_or_each_other"})

    for key in ("elapsed_s", "dataloader_elapsed_s", "checkpoint_elapsed_s", "eval_elapsed_s", "recovery_elapsed_s"):
        if not finite_positive(probe.get(key)):
            failures.append({"code": f"probe_{key}_invalid", "actual": probe.get(key)})
    measured = probe.get("estimated_stack_training_tflops_lower_bound")
    required = probe.get("full_config_required_sustained_tflops")
    if not finite_positive(measured) or not finite_positive(required):
        failures.append({"code": "throughput_metrics_invalid", "measured": measured, "required": required})
    elif float(measured) < float(required):
        failures.append({"code": "policy_optimized_throughput_below_requirement", "measured": measured, "required": required})

    sampling = power.get("power_sampling") or {}
    if "nvidia-smi" not in str(sampling.get("sampling_method", "")):
        failures.append({"code": "sampling_method_not_nvidia_smi", "actual": sampling.get("sampling_method")})
    if not isinstance(sampling.get("sample_count"), int) or sampling.get("sample_count") < 20:
        failures.append({"code": "insufficient_power_samples", "actual": sampling.get("sample_count")})
    for field in ("sample_span_s", "avg_power_w", "max_power_w", "energy_joules_trapezoid", "energy_wh", "joules_per_step", "joules_per_training_token"):
        if not finite_positive(sampling.get(field)):
            failures.append({"code": "power_metric_not_positive", "field": field, "actual": sampling.get(field)})
    if sampling.get("tokens_accounted") != steps * 2048:
        failures.append({"code": "tokens_accounted_mismatch", "expected": steps * 2048, "actual": sampling.get("tokens_accounted")})
    if sampling.get("includes_child_wall_clock") is not True:
        failures.append({"code": "sampling_not_child_wall_clock"})

    for source, value in (("probe", probe), ("power", power)):
        leaks = find_local_path_leaks(value)
        if leaks:
            failures.append({"code": "local_path_or_private_name_leak", "source": source, "examples": leaks[:5]})

    limit = str(power.get("completion_limit", ""))
    for phrase in ("not days-scale long-run training", "not full-run energy accounting", "not overall baseline completion"):
        if phrase not in limit:
            failures.append({"code": "completion_limit_missing_phrase", "phrase": phrase})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_POLICY_OPTIMIZED_1024_WINDOW_VALIDATED" if not failures else "C1_POLICY_OPTIMIZED_1024_WINDOW_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "probe_receipt_path": PROBE_RECEIPT,
        "power_receipt_path": POWER_RECEIPT,
        "steps_completed": probe.get("steps_completed"),
        "checkpoint_event_count": cadence.get("checkpoint_event_count") if isinstance(cadence, dict) else None,
        "eval_window_count": eval_accounting.get("eval_window_count") if isinstance(eval_accounting, dict) else None,
        "recovery_window_base": recovery.get("recovery_window_base") if isinstance(recovery, dict) else None,
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "energy_joules_trapezoid": sampling.get("energy_joules_trapezoid") if isinstance(sampling, dict) else None,
        "completion_limit": "This validates a bounded 1024-window streamed train/checkpoint/eval/recovery/power policy probe only. It is not days-scale long-run training, not full-run energy accounting, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
