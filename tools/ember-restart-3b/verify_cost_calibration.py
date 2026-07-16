# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify an anchor-bound native compute-screen replication certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


def _read_object(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, raw


def verify(certificate_path: Path, receipt_path: Path) -> dict[str, object]:
    certificate, _ = _read_object(certificate_path, "certificate")
    receipt, receipt_bytes = _read_object(receipt_path, "receipt")
    if certificate.get("schema_version") != "ember-anchor-cost-calibration-certificate-v1":
        raise ValueError("unsupported certificate schema")
    observed_hash = hashlib.sha256(receipt_bytes).hexdigest()
    if certificate.get("replication_receipt_sha256") != observed_hash:
        raise ValueError("replication_receipt_sha256 mismatch")
    receipt_binding = certificate.get("receipt_binding")
    if not isinstance(receipt_binding, dict):
        raise ValueError("certificate receipt_binding must be an object")
    scalar_binding_fields = (
        "checkpoint_manifest_sha256",
        "model_config_sha256",
        "tokenizer_sha256",
        "source_sha256",
        "optimizer_contract_sha256",
        "stream_receipt_sha256",
    )
    required_binding_fields = {*scalar_binding_fields, "source_closure_sha256"}
    if set(receipt_binding) != required_binding_fields:
        raise ValueError("certificate receipt_binding fields mismatch")
    for field in scalar_binding_fields:
        if receipt.get(field) != receipt_binding[field]:
            raise ValueError(f"receipt binding {field} mismatch")
    custody = receipt.get("custody")
    if not isinstance(custody, dict):
        raise ValueError("receipt custody must be an object")
    source_closure = custody.get("source_closure_sha256")
    if not isinstance(source_closure, dict) or source_closure != receipt_binding["source_closure_sha256"]:
        raise ValueError("receipt binding source_closure_sha256 mismatch")
    expected_identity = {
        "schema_version": "ember-native-compute-screen-v1",
        "result": "MEASURED",
        "admission": "NON_ADMISSIBLE_COMPUTE_PRIMITIVE",
        "genesis_seed": 83,
        "sequence_length": 1024,
        "required_batches": [1, 2],
        "total_parameters": 3_839_161_856,
        "active_parameters": 1_020_589_568,
    }
    for field, expected in expected_identity.items():
        if receipt.get(field) != expected:
            raise ValueError(f"receipt {field} mismatch")
    steps = receipt.get("steps")
    if not isinstance(steps, list) or len(steps) != 2:
        raise ValueError("receipt requires exactly two steps")
    if [step.get("batch_size") for step in steps if isinstance(step, dict)] != [1, 2]:
        raise ValueError("receipt steps must be batch 1 then batch 2")
    anchor = certificate.get("anchor")
    thresholds = certificate.get("thresholds")
    if not isinstance(anchor, dict) or not isinstance(thresholds, dict):
        raise ValueError("certificate anchor and thresholds must be objects")
    b1, b2 = steps
    assert isinstance(b1, dict) and isinstance(b2, dict)
    values = {
        "batch_1_elapsed_relative_error": abs(float(b1["elapsed_seconds"]) - float(anchor["batch_1_elapsed_seconds"])) / float(anchor["batch_1_elapsed_seconds"]),
        "batch_2_elapsed_relative_error": abs(float(b2["elapsed_seconds"]) - float(anchor["batch_2_elapsed_seconds"])) / float(anchor["batch_2_elapsed_seconds"]),
        "batch_2_throughput_speedup_over_batch_1": (2.0 / float(b2["elapsed_seconds"])) / (1.0 / float(b1["elapsed_seconds"])),
        "batch_1_loss_absolute_error_from_anchor": abs(float(b1["loss"]) - float(anchor["batch_1_loss"])),
        "batch_2_loss_absolute_error_from_anchor": abs(float(b2["loss"]) - float(anchor["batch_2_loss"])),
    }
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("derived calibration metrics must be finite")
    checks = {
        "batch_1_elapsed_relative_error": values["batch_1_elapsed_relative_error"] <= float(thresholds["batch_1_elapsed_relative_error_max"]),
        "batch_2_elapsed_relative_error": values["batch_2_elapsed_relative_error"] <= float(thresholds["batch_2_elapsed_relative_error_max"]),
        "batch_2_throughput_speedup_over_batch_1": values["batch_2_throughput_speedup_over_batch_1"] >= float(thresholds["minimum_batch_2_throughput_speedup_over_batch_1"]),
        "batch_1_loss_absolute_error_from_anchor": values["batch_1_loss_absolute_error_from_anchor"] <= float(thresholds["batch_1_loss_absolute_error_from_anchor_max"]),
        "batch_2_loss_absolute_error_from_anchor": values["batch_2_loss_absolute_error_from_anchor"] <= float(thresholds["batch_2_loss_absolute_error_from_anchor_max"]),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("failed frozen thresholds: " + ", ".join(failures))
    return {
        "schema_version": "ember-anchor-cost-calibration-verdict-v1",
        "adjudication": "PASS",
        "credit": certificate.get("credit"),
        "replication_receipt_sha256": observed_hash,
        "derived_metrics": values,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.certificate, args.receipt), sort_keys=True))
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
