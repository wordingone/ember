#!/usr/bin/env python3
"""Validate bounded owned-engine SFT repair-attempt receipts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED = [
    {
        "path": "receipts/owned-engine-sft-v2-tool-loop-2026-06-30.json",
        "schema": "owned_engine.sft_tool_loop_probe.v2",
        "min_steps": 900,
        "min_tool_observations": 1,
        "root_test": "large-count generalization",
    },
    {
        "path": "receipts/owned-engine-sft-v3-turnwise-tool-loop-2026-06-30.json",
        "schema": "owned_engine.sft_turnwise_tool_loop_probe.v1",
        "min_steps": 900,
        "min_tool_observations": 1,
        "root_test": "turnwise next-action supervision",
    },
    {
        "path": "receipts/owned-engine-sft-v4-copy-contract-tool-loop-2026-06-30.json",
        "schema": "owned_engine.sft_copy_contract_tool_loop_probe.v1",
        "min_steps": 1200,
        "min_tool_observations": 1,
        "root_test": "normalized copy-contract runtime",
    },
    {
        "path": "receipts/owned-engine-sft-v5-compositional-copy-tool-loop-2026-06-30.json",
        "schema": "owned_engine.sft_compositional_copy_tool_loop_probe.v1",
        "min_steps": 1200,
        "min_tool_observations": 1,
        "root_test": "compositional target-path copying",
    },
    {
        "path": "receipts/owned-engine-sft-v6-observation-copy-tool-loop-2026-06-30.json",
        "schema": "owned_engine.sft_observation_copy_tool_loop_probe.v1",
        "min_steps": 1200,
        "min_tool_observations": 1,
        "root_test": "live-observation to write-body copying",
    },
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def forbidden_local_text(value: Any) -> list[str]:
    text = json.dumps(value, sort_keys=True)
    needles = {
        "local_tmp_forward": "C:" + "/" + "tmp",
        "local_tmp_back": "C:" + "\\" + "tmp",
        "user_home": "C:" + "\\" + "Users" + "\\" + "Admin",
        "private_tree_forward": "B:" + "/" + "M" + "/" + "av" + "ir",
        "private_tree_back": "B:" + "\\" + "M" + "\\" + "av" + "ir",
    }
    lower = text.lower()
    return [name for name, needle in needles.items() if needle.lower() in lower]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for spec in EXPECTED:
        rel = spec["path"]
        path = root / rel
        receipt = read_json(path) if path.exists() else {}
        if not receipt:
            failures.append({"code": "receipt_missing", "path": rel})
            continue
        if receipt.get("schema") != spec["schema"]:
            failures.append({"code": "schema_mismatch", "path": rel, "actual": receipt.get("schema")})
        if receipt.get("verdict") != "FAIL":
            failures.append({"code": "repair_probe_unexpectedly_passed_or_unclassified", "path": rel, "actual": receipt.get("verdict")})
        training = receipt.get("training_run", {}) if isinstance(receipt.get("training_run"), dict) else {}
        if training.get("steps", 0) < spec["min_steps"]:
            failures.append({"code": "training_steps_below_floor", "path": rel, "actual": training.get("steps")})
        checkpoint = receipt.get("checkpoint", {}) if isinstance(receipt.get("checkpoint"), dict) else {}
        if not checkpoint.get("sha256") or checkpoint.get("size_bytes", 0) <= 0:
            failures.append({"code": "checkpoint_hash_or_size_missing", "path": rel})
        probe = receipt.get("probe", {}) if isinstance(receipt.get("probe"), dict) else {}
        if probe.get("expected_output") != "470" or probe.get("task_passed") is not False:
            failures.append({"code": "heldout_probe_shape_mismatch", "path": rel, "actual": probe})
        if probe.get("valid_tool_observation_count", 0) < spec["min_tool_observations"]:
            failures.append({"code": "tool_loop_not_exercised", "path": rel, "actual": probe.get("valid_tool_observation_count")})
        forbidden = forbidden_local_text(receipt)
        if forbidden:
            failures.append({"code": "receipt_contains_forbidden_local_text", "path": rel, "markers": forbidden})
        summaries[rel] = {
            "root_test": spec["root_test"],
            "training_steps": training.get("steps"),
            "checkpoint_size_bytes": checkpoint.get("size_bytes"),
            "task_passed": probe.get("task_passed"),
            "observed_output": probe.get("observed_output"),
            "valid_tool_observation_count": probe.get("valid_tool_observation_count"),
        }

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "OWNED_ENGINE_SFT_REPAIR_ATTEMPTS_NEGATIVE_EVIDENCE_VALIDATED" if not failures else "OWNED_ENGINE_SFT_REPAIR_ATTEMPTS_VALIDATION_FAILED",
        "failure_count": len(failures),
        "failures": failures,
        "summaries": summaries,
        "completion_limit": "This validates bounded negative repair-attempt evidence only. It is not an external benchmark win and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
