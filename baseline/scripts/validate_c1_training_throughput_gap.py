#!/usr/bin/env python3
"""Validate the current C1 measured training-throughput gap.

This validator is intentionally a negative C1 gate. It proves that the best
existing full-stack LM-loss probe is below the locked days-scale throughput
requirement, so the single-4090 family cannot be promoted to complete until a
replacement measured receipt closes the gap.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANES = {
    "from_scratch": "receipts/4090-full-stack-lm-loss-probe-from-scratch.json",
    "pretraining_equivalent": "receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent.json",
}

EXPECTED_VERDICT = "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_lane(root: Path, lane: str, rel: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    path = root / rel
    if not path.exists():
        return None, [{"code": "probe_receipt_missing", "lane": lane, "path": rel}]
    receipt = read_json(path)
    if receipt.get("lane") != lane:
        failures.append({"code": "lane_mismatch", "lane": lane, "actual": receipt.get("lane"), "path": rel})
    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "unexpected_probe_verdict", "lane": lane, "actual": receipt.get("verdict"), "path": rel})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "lane": lane, "actual": receipt.get("active_trainable_parameters"), "path": rel})
    shape = receipt.get("probe_shape", {})
    required_shape = {"seq_len": 2048, "hidden": 2048, "heads": 16, "model_layers": 19, "layers_executed": 19, "vocab_size": 32768}
    for field, expected in required_shape.items():
        if shape.get(field) != expected:
            failures.append({"code": "shape_mismatch", "lane": lane, "field": field, "expected": expected, "actual": shape.get(field), "path": rel})
    if receipt.get("uses_full_lm_head_loss") is not True:
        failures.append({"code": "lm_head_loss_not_used", "lane": lane, "path": rel})
    if receipt.get("uses_hidden_state_surrogate_loss") is not False:
        failures.append({"code": "surrogate_loss_not_rejected", "lane": lane, "path": rel})
    if receipt.get("uses_scaled_dot_product_attention") is not True:
        failures.append({"code": "sdpa_not_used", "lane": lane, "path": rel})
    if receipt.get("uses_activation_checkpointing") is not True:
        failures.append({"code": "activation_checkpointing_not_used", "lane": lane, "path": rel})
    measured = receipt.get("estimated_stack_training_tflops_lower_bound")
    required = receipt.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or measured <= 0:
        failures.append({"code": "measured_tflops_missing", "lane": lane, "actual": measured, "path": rel})
    if not isinstance(required, (int, float)) or required <= 0:
        failures.append({"code": "required_tflops_missing", "lane": lane, "actual": required, "path": rel})
    if isinstance(measured, (int, float)) and isinstance(required, (int, float)) and measured >= required:
        failures.append({"code": "gap_not_present_use_completion_or_stronger_ceiling_validator", "lane": lane, "measured": measured, "required": required, "path": rel})
    if receipt.get("steps_completed", 0) < 1:
        failures.append({"code": "no_probe_steps_completed", "lane": lane, "actual": receipt.get("steps_completed"), "path": rel})
    summary = {
        "lane": lane,
        "path": rel,
        "active_trainable_parameters": receipt.get("active_trainable_parameters"),
        "steps_completed": receipt.get("steps_completed"),
        "tokens_per_second": receipt.get("tokens_per_second"),
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
        "measured_to_required_ratio": (measured / required) if isinstance(measured, (int, float)) and isinstance(required, (int, float)) and required else None,
        "shortfall_tflops": (required - measured) if isinstance(measured, (int, float)) and isinstance(required, (int, float)) else None,
    }
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    lane_summaries: list[dict[str, Any]] = []
    for lane, rel in LANES.items():
        summary, lane_failures = validate_lane(root, lane, rel)
        failures.extend(lane_failures)
        if summary is not None:
            lane_summaries.append(summary)

    required_values = {row.get("required_sustained_tflops") for row in lane_summaries if row.get("required_sustained_tflops") is not None}
    if len(required_values) != 1:
        failures.append({"code": "lanes_do_not_share_locked_required_tflops", "values": sorted(required_values)})
    best = max((row for row in lane_summaries if isinstance(row.get("measured_tflops_lower_bound"), (int, float))), key=lambda row: row["measured_tflops_lower_bound"], default=None)
    required = next(iter(required_values)) if len(required_values) == 1 else None
    best_ratio = None
    if best is not None and isinstance(required, (int, float)) and required > 0:
        best_ratio = best["measured_tflops_lower_bound"] / required

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_TRAINING_THROUGHPUT_GAP_VALIDATED" if not failures else "C1_TRAINING_THROUGHPUT_GAP_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_training_throughput_gap",
        "lane_summaries": lane_summaries,
        "best_measured_lane": best.get("lane") if best else None,
        "best_measured_tflops_lower_bound": best.get("measured_tflops_lower_bound") if best else None,
        "required_sustained_tflops": required,
        "best_measured_to_required_ratio": best_ratio,
        "minimum_multiplier_needed_to_reach_requirement": (1 / best_ratio) if best_ratio else None,
        "c1_completion_gate": "Current measured full-stack LM-loss throughput is below the locked <=14-day requirement. C1 cannot complete until a replacement measured full-stack long-run receipt meets or exceeds the requirement, or a stronger native/lower-level ceiling receipt supersedes this gap without weakening data, memory, evaluation, and replay constraints.",
        "completion_limit": "This is a measured throughput-gap validation, not a completion receipt and not an Ember win.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
