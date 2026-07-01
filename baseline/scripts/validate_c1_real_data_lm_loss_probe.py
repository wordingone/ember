#!/usr/bin/env python3
"""Validate C1 real-token full-stack LM-loss probe receipts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED = {
    "from_scratch": "receipts/4090-real-data-lm-loss-probe-from-scratch.json",
    "pretraining_equivalent": "receipts/4090-real-data-lm-loss-probe-pretraining-equivalent.json",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_one(root: Path, lane: str, rel: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    path = root / rel
    if not path.exists():
        return None, [{"code": "real_data_probe_missing", "lane": lane, "path": rel}]
    r = read_json(path)
    if r.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "lane": lane, "actual": r.get("verdict")})
    if r.get("lane") != lane:
        failures.append({"code": "lane_mismatch", "lane": lane, "actual": r.get("lane")})
    if r.get("uses_real_token_data") is not True:
        failures.append({"code": "not_real_token_data", "lane": lane})
    window = r.get("real_data_window") or {}
    if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
        failures.append({"code": "token_shard_receipt_not_pinned", "lane": lane, "window": window})
    if window.get("separator_tokens_in_window") != 0:
        failures.append({"code": "separator_token_in_probe_window", "lane": lane, "actual": window.get("separator_tokens_in_window")})
    if not window.get("input_tokens_sha256") or not window.get("target_tokens_sha256"):
        failures.append({"code": "token_window_hashes_missing", "lane": lane, "window": window})
    shape = r.get("probe_shape", {})
    expected_shape = {"batch_size": 1, "seq_len": 2048, "vocab_size": 32768, "hidden": 2048, "heads": 16, "model_layers": 19, "layers_executed": 19}
    for key, expected in expected_shape.items():
        if shape.get(key) != expected:
            failures.append({"code": "shape_mismatch", "lane": lane, "field": key, "expected": expected, "actual": shape.get(key)})
    if r.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "lane": lane, "actual": r.get("active_trainable_parameters")})
    if r.get("uses_full_lm_head_loss") is not True or r.get("uses_hidden_state_surrogate_loss") is not False:
        failures.append({"code": "lm_loss_controls_missing", "lane": lane})
    if r.get("steps_completed", 0) < 1:
        failures.append({"code": "no_probe_steps_completed", "lane": lane, "actual": r.get("steps_completed")})
    measured = r.get("estimated_stack_training_tflops_lower_bound")
    required = r.get("full_config_required_sustained_tflops")
    if not isinstance(measured, (int, float)) or measured <= 0:
        failures.append({"code": "measured_tflops_missing", "lane": lane, "actual": measured})
    if not isinstance(required, (int, float)) or required <= 0:
        failures.append({"code": "required_tflops_missing", "lane": lane, "actual": required})
    return {
        "lane": lane,
        "path": rel,
        "stream_token_start": window.get("stream_token_start"),
        "shard_name": window.get("shard_name"),
        "input_tokens_sha256": window.get("input_tokens_sha256"),
        "target_tokens_sha256": window.get("target_tokens_sha256"),
        "loss_first": r.get("loss_first"),
        "loss_last": r.get("loss_last"),
        "tokens_per_second": r.get("tokens_per_second"),
        "measured_tflops_lower_bound": measured,
        "required_sustained_tflops": required,
    }, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    lane_summaries: list[dict[str, Any]] = []
    for lane, rel in REQUIRED.items():
        summary, lane_failures = validate_one(root, lane, rel)
        failures.extend(lane_failures)
        if summary:
            lane_summaries.append(summary)
    starts = {row.get("stream_token_start") for row in lane_summaries}
    inputs = {row.get("input_tokens_sha256") for row in lane_summaries}
    if len(starts) != 1 or len(inputs) != 1:
        failures.append({"code": "lanes_do_not_share_same_real_data_window", "starts": sorted(starts), "inputs": sorted(inputs)})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_REAL_DATA_LM_LOSS_PROBE_VALIDATED" if not failures else "C1_REAL_DATA_LM_LOSS_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_real_data_lm_loss_probe_validation",
        "lane_summaries": lane_summaries,
        "completion_limit": "This validates bounded real-token full-stack LM-loss telemetry only. It is not a multi-step stability receipt, checkpoint/resume receipt, long-run training receipt, or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
