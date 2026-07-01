#!/usr/bin/env python3
"""Validate bounded C1 real-token checkpoint/resume probe evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-real-data-checkpoint-resume-probe-pretraining-equivalent.json"


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
        failures.append({"code": "checkpoint_resume_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_verdict", "actual": receipt.get("verdict")})
    if receipt.get("lane") != "pretraining_equivalent":
        failures.append({"code": "lane_not_pretraining_equivalent", "actual": receipt.get("lane")})
    if receipt.get("uses_real_token_data") is not True:
        failures.append({"code": "not_real_token_data"})
    if receipt.get("steps_completed") != 2:
        failures.append({"code": "steps_completed_mismatch", "actual": receipt.get("steps_completed")})
    ckpt = receipt.get("checkpoint_resume") or {}
    if ckpt.get("enabled") is not True:
        failures.append({"code": "checkpoint_resume_not_enabled", "checkpoint_resume": ckpt})
    if ckpt.get("checkpoint_contains_model_state") is not True or ckpt.get("checkpoint_contains_optimizer_state") is not True:
        failures.append({"code": "checkpoint_missing_model_or_optimizer_state", "checkpoint_resume": ckpt})
    if ckpt.get("checkpoint_after_steps") != 1 or ckpt.get("loaded_completed_steps") != 1 or ckpt.get("resumed_for_additional_steps") != 1:
        failures.append({"code": "checkpoint_resume_step_accounting_mismatch", "checkpoint_resume": ckpt})
    if ckpt.get("loaded_seed") != receipt.get("seed") or ckpt.get("loaded_lane") != receipt.get("lane"):
        failures.append({"code": "loaded_checkpoint_identity_mismatch", "checkpoint_resume": ckpt})
    if ckpt.get("checkpoint_path_recorded") is not False or not ckpt.get("checkpoint_sha256") or ckpt.get("checkpoint_size_bytes", 0) <= 0:
        failures.append({"code": "checkpoint_hash_or_public_path_policy_invalid", "checkpoint_resume": ckpt})
    if ckpt.get("checkpoint_deleted_after_hash") is not True:
        failures.append({"code": "temporary_checkpoint_not_deleted", "checkpoint_resume": ckpt})
    window = receipt.get("real_data_window") or {}
    if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json" or window.get("separator_tokens_in_window") != 0:
        failures.append({"code": "real_data_window_not_pinned_clean", "window": window})
    if "bounded checkpoint/resume telemetry only" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_bounded_checkpoint_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CHECKPOINT_RESUME_PROBE_VALIDATED" if not failures else "C1_CHECKPOINT_RESUME_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "kind": "single_4090_c1_checkpoint_resume_probe_validation",
        "receipt_path": RECEIPT,
        "completion_limit": "This validates bounded real-token checkpoint/resume mechanics only. It is not a long-run checkpoint cadence receipt, not a throughput completion receipt, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
