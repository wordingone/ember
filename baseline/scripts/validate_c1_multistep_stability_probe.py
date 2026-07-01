#!/usr/bin/env python3
"""Validate bounded C1 real-token multi-step stability probe evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-multistep-stability-probe-pretraining-equivalent.json"


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
        failures.append({"code": "multistep_stability_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_not_pretraining_equivalent", "actual": receipt.get("lane")})
    if receipt.get("uses_real_token_data") is not True:
        failures.append({"code": "not_real_token_data"})
    if receipt.get("checkpoint_resume") is not None:
        failures.append({"code": "checkpoint_resume_should_not_be_part_of_stability_probe", "checkpoint_resume": receipt.get("checkpoint_resume")})
    if receipt.get("steps_completed", 0) < 4:
        failures.append({"code": "too_few_steps_completed", "actual": receipt.get("steps_completed")})
    losses = receipt.get("loss_values")
    if not isinstance(losses, list) or len(losses) != receipt.get("steps_completed"):
        failures.append({"code": "loss_values_missing_or_length_mismatch", "loss_values": losses, "steps_completed": receipt.get("steps_completed")})
    else:
        bad = [x for x in losses if not isinstance(x, (int, float)) or not math.isfinite(float(x)) or float(x) <= 0]
        if bad:
            failures.append({"code": "nonfinite_or_nonpositive_loss", "bad": bad[:5]})
        if max(float(x) for x in losses) > 10000:
            failures.append({"code": "loss_exploded", "max_loss": max(float(x) for x in losses)})
    if receipt.get("loss_is_finite_all_steps") is not True:
        failures.append({"code": "loss_finite_flag_not_true", "actual": receipt.get("loss_is_finite_all_steps")})
    window = receipt.get("real_data_window") or {}
    if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json" or window.get("separator_tokens_in_window") != 0:
        failures.append({"code": "real_data_window_not_pinned_clean", "window": window})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_MULTISTEP_STABILITY_PROBE_VALIDATED" if not failures else "C1_MULTISTEP_STABILITY_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_multistep_stability_probe_validation",
        "receipt_path": RECEIPT,
        "steps_completed": receipt.get("steps_completed"),
        "loss_first": receipt.get("loss_first"),
        "loss_last": receipt.get("loss_last"),
        "completion_limit": "This validates bounded same-window real-token multi-step stability telemetry only. It is not a full-data epoch, long-run throughput, checkpoint cadence, convergence, or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
