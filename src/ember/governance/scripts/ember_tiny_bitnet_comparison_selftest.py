#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the immediate post-resident-gate tiny BitNet comparison."""
from __future__ import annotations


def main() -> int:
    import tempfile
    from pathlib import Path

    import ember_tiny_bitnet_comparison as bitnet

    with tempfile.TemporaryDirectory(prefix="ember-bitnet-selftest-") as td:
        receipt = bitnet.run_comparison(Path(td))
        assert receipt["verdict"] in {"BITNET_COMPARISON_PASS", "BITNET_BLOCKED"}
        assert receipt["post_resident_gate_required"] is True
        assert receipt["resident_gate_receipt_status"] == "PASS"
        if receipt["verdict"] == "BITNET_BLOCKED":
            assert receipt["missing_implementation_surface"]
            assert receipt["next_executable_command"]
        else:
            assert receipt["fp16_baseline_identity"]
            assert receipt["bitnet_model_identity"]
            assert receipt["precision_quantization_scheme"]
            assert receipt["fp16_trainable_parameter_count"] == receipt["bitnet_trainable_parameter_count"]
            assert receipt["fp16_pre_parameter_hash"] != receipt["fp16_post_parameter_hash"]
            assert receipt["bitnet_pre_parameter_hash"] != receipt["bitnet_post_parameter_hash"]
            assert receipt["matched_budget_envelope"]["same_train_rows"] is True
            assert receipt["matched_budget_envelope"]["same_heldout_rows"] is True
            assert receipt["matched_budget_envelope"]["same_transfer_rows"] is True
            assert receipt["quality_delta"]["bitnet_minus_fp16_heldout_mean"] is not None
            assert receipt["footprint"]["bitnet_effective_weight_bits"] == 1.58
            assert receipt["throughput_latency"]
            assert receipt["memory_cpu_measurements"]
            assert receipt["transfer_rows"]
            assert all(row["split"] == "transfer" for row in receipt["transfer_rows"])
            assert all(row["deleted_score"] < row["bitnet_score"] for row in receipt["deletion_revert_evidence"])
    print("EMBER_TINY_BITNET_COMPARISON_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
