#!/usr/bin/env python3
"""Validate the owned-engine SFT tool-loop probe receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def contains_forbidden_local_text(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True)
    markers = [
        "C:" + "/" + "tmp",
        "C:" + "\\" + "tmp",
        "C:" + "\\" + "Users" + "\\" + "Admin",
        "B:" + "/" + "M" + "/" + "av" + "ir",
        "B:" + "\\" + "M" + "\\" + "av" + "ir",
    ]
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", default="receipts/owned-engine-sft-tool-loop-2026-06-30.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    receipt_path = root / args.receipt
    failures: list[dict[str, Any]] = []
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    if not receipt:
        failures.append({"code": "receipt_missing", "path": args.receipt})
    if receipt.get("schema") != "owned_engine.sft_tool_loop_probe.v1":
        failures.append({"code": "schema_mismatch", "actual": receipt.get("schema")})
    if receipt.get("verdict") != "FAIL" or receipt.get("returncode") != 2:
        failures.append({"code": "expected_negative_probe_not_recorded", "actual": {"verdict": receipt.get("verdict"), "returncode": receipt.get("returncode")}})
    training = receipt.get("training_run", {}) if isinstance(receipt.get("training_run"), dict) else {}
    if training.get("steps") != 700:
        failures.append({"code": "training_steps_mismatch", "actual": training.get("steps")})
    if training.get("synthetic_trace_count") != 2000:
        failures.append({"code": "trace_count_mismatch", "actual": training.get("synthetic_trace_count")})
    checkpoint = receipt.get("checkpoint", {}) if isinstance(receipt.get("checkpoint"), dict) else {}
    if not checkpoint.get("sha256") or checkpoint.get("size_bytes", 0) <= 0:
        failures.append({"code": "checkpoint_hash_or_size_missing", "actual": checkpoint})
    probe = receipt.get("probe", {}) if isinstance(receipt.get("probe"), dict) else {}
    if probe.get("expected_output") == probe.get("observed_output"):
        failures.append({"code": "probe_unexpectedly_passed_without_external_trial", "actual": probe})
    if probe.get("valid_tool_observation_count", 0) < 1:
        failures.append({"code": "sft_probe_did_not_improve_tool_parsing", "actual": probe.get("valid_tool_observation_count")})
    if probe.get("output_file_created_but_wrong") is not True:
        failures.append({"code": "negative_probe_shape_not_preserved", "actual": probe})
    delta = receipt.get("capability_delta_vs_untrained_probe", {}) if isinstance(receipt.get("capability_delta_vs_untrained_probe"), dict) else {}
    if delta.get("sft_valid_tool_observations", 0) <= delta.get("untrained_valid_tool_calls", 0):
        failures.append({"code": "capability_delta_not_positive_on_tool_parsing", "actual": delta})
    if contains_forbidden_local_text(receipt):
        failures.append({"code": "receipt_contains_forbidden_local_text"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "OWNED_ENGINE_SFT_TOOL_LOOP_NEGATIVE_EVIDENCE_VALIDATED" if not failures else "OWNED_ENGINE_SFT_TOOL_LOOP_VALIDATION_FAILED",
        "failure_count": len(failures),
        "failures": failures,
        "receipt": args.receipt,
        "summary": {
            "training_steps": training.get("steps"),
            "checkpoint_size_bytes": checkpoint.get("size_bytes"),
            "probe_expected_output": probe.get("expected_output"),
            "probe_observed_output": probe.get("observed_output"),
            "valid_tool_observation_count": probe.get("valid_tool_observation_count"),
            "task_passed": probe.get("task_passed"),
        },
        "completion_limit": "This validates a bounded SFT/probe negative-evidence receipt only. It is not a governed external benchmark win and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
