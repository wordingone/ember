#!/usr/bin/env python3
"""Validate bounded C1 real-token steady-state throughput probe evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-steady-state-throughput-probe-pretraining-equivalent.json"


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
        failures.append({"code": "steady_state_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_not_pretraining_equivalent", "actual": receipt.get("lane")})
    if receipt.get("uses_real_token_data") is not True:
        failures.append({"code": "not_real_token_data"})
    if receipt.get("steps_completed", 0) < 16:
        failures.append({"code": "too_few_steps_completed", "actual": receipt.get("steps_completed")})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or not isinstance(required, (int, float)) or measured < required:
        failures.append({"code": "steady_state_did_not_clear_required_tflops", "measured": measured, "required": required})
    losses = receipt.get("loss_values")
    if not isinstance(losses, list) or len(losses) != receipt.get("steps_completed"):
        failures.append({"code": "loss_values_missing_or_length_mismatch"})
    elif any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) <= 0 for x in losses):
        failures.append({"code": "nonfinite_or_nonpositive_loss"})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "loss_finite_flag_not_true"})
    window = receipt.get("real_data_window") or {}
    if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json" or window.get("separator_tokens_in_window") != 0:
        failures.append({"code": "real_data_window_not_pinned_clean", "window": window})
    if "not long-run throughput" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_STEADY_STATE_THROUGHPUT_PROBE_VALIDATED" if not failures else "C1_STEADY_STATE_THROUGHPUT_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_steady_state_throughput_probe_validation",
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "completion_limit": "This validates bounded same-window steady-state throughput telemetry only. It is not a varied-data long-run, data-loader, evaluation, checkpoint cadence, or overall baseline completion receipt.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
