#!/usr/bin/env python3
"""Parse receipts emitted by train_1b_4090.py into PASS/FAIL/INVALID verdicts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = [
    "verdict",
    "config_id",
    "lane",
    "active_trainable_parameters",
    "token_budget",
    "capability_target",
    "memory_plan",
    "throughput",
    "stop_rule",
]








def parse_full_stack_lm_loss_probe(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    failures = []
    required = [
        "verdict",
        "kind",
        "config_id",
        "lane",
        "active_trainable_parameters",
        "probe_shape",
        "steps_completed",
        "tokens_per_second",
        "estimated_stack_training_tflops_lower_bound",
        "full_config_required_sustained_tflops",
        "peak_memory_bytes",
        "uses_scaled_dot_product_attention",
        "uses_activation_checkpointing",
        "uses_full_lm_head_loss",
        "uses_hidden_state_surrogate_loss",
        "completion_limit",
    ]
    for field in required:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_full_stack_lm_loss_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    shape = receipt.get("probe_shape", {})
    if shape.get("hidden") != 2048 or shape.get("heads") != 16 or shape.get("model_layers") != 19 or shape.get("layers_executed") != 19:
        failures.append({"code": "lm_loss_shape_not_locked_c1_stack", "shape": shape})
    if shape.get("seq_len") != 2048 or shape.get("vocab_size") != 32768:
        failures.append({"code": "lm_loss_sequence_or_vocab_mismatch", "shape": shape})
    if receipt.get("steps_completed", 0) < 1:
        failures.append({"code": "no_probe_steps_completed", "actual": receipt.get("steps_completed")})
    if receipt.get("uses_scaled_dot_product_attention") is not True:
        failures.append({"code": "sdpa_not_used"})
    if receipt.get("uses_activation_checkpointing") is not True:
        failures.append({"code": "activation_checkpointing_not_used"})
    if receipt.get("uses_full_lm_head_loss") is not True or receipt.get("uses_hidden_state_surrogate_loss") is not False:
        failures.append({"code": "lm_loss_controls_missing"})
    if "not family completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})
    verdict = "FULL_STACK_LM_LOSS_PROBE_PARSE_PASS" if not failures else "ENGINEERING_RECEIPT_INVALID"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Full-stack LM-loss parser PASS validates bounded all-layer language-model loss telemetry only. It is not a long-run 1B language-model training receipt and not overall baseline completion.",
    }

def parse_native_kernel_probe(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    failures = []
    required = [
        "verdict",
        "kind",
        "config_id",
        "lane",
        "active_trainable_parameters",
        "capability_target",
        "toolchain",
        "benchmarks",
        "completion_limit",
    ]
    for field in required:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("verdict") != "NATIVE_KERNEL_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_native_kernel_probe_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    toolchain = receipt.get("toolchain", {})
    if toolchain.get("triton_available") is not True:
        failures.append({"code": "triton_not_available", "toolchain": toolchain})
    if toolchain.get("nvcc_available") is not True:
        failures.append({"code": "nvcc_not_available", "toolchain": toolchain})
    benchmarks = receipt.get("benchmarks")
    if not isinstance(benchmarks, list) or not benchmarks:
        failures.append({"code": "native_benchmarks_missing"})
    else:
        for row in benchmarks:
            for field in ("name", "m", "n", "k", "torch_tflops", "triton_tflops", "max_reference_abs", "max_relative_error"):
                if row.get(field) is None:
                    failures.append({"code": "native_benchmark_field_missing", "field": field, "row": row})
            if row.get("triton_tflops", 0) <= 0 or row.get("torch_tflops", 0) <= 0:
                failures.append({"code": "native_benchmark_nonpositive_tflops", "row": row})
            if row.get("max_relative_error") is not None and row.get("max_relative_error") > 0.02:
                failures.append({"code": "native_benchmark_relative_error_too_large", "row": row})
    if "not family completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})
    verdict = "NATIVE_KERNEL_PROBE_PARSE_PASS" if not failures else "ENGINEERING_RECEIPT_INVALID"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Native kernel parser PASS validates bounded Triton/CUDA toolchain telemetry only. It is not full 1B training throughput and not overall baseline completion.",
    }

def parse_full_stack_step_probe(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    failures = []
    required = [
        "verdict",
        "kind",
        "config_id",
        "lane",
        "active_trainable_parameters",
        "probe_shape",
        "steps_completed",
        "tokens_per_second",
        "estimated_stack_training_tflops_lower_bound",
        "full_config_required_sustained_tflops",
        "peak_memory_bytes",
        "uses_scaled_dot_product_attention",
        "uses_activation_checkpointing",
        "uses_hidden_state_surrogate_loss",
        "completion_limit",
    ]
    for field in required:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("verdict") != "FULL_STACK_STEP_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_full_stack_step_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    shape = receipt.get("probe_shape", {})
    if shape.get("hidden") != 2048 or shape.get("heads") != 16 or shape.get("model_layers") != 19 or shape.get("layers_executed") != 19:
        failures.append({"code": "full_stack_shape_not_locked_c1_stack", "shape": shape})
    if shape.get("seq_len", 0) <= 0 or shape.get("seq_len", 0) > shape.get("configured_sequence_length", 2048):
        failures.append({"code": "full_stack_sequence_invalid", "shape": shape})
    if receipt.get("steps_completed", 0) < 1:
        failures.append({"code": "no_probe_steps_completed", "actual": receipt.get("steps_completed")})
    if receipt.get("uses_scaled_dot_product_attention") is not True:
        failures.append({"code": "sdpa_not_used"})
    if receipt.get("uses_activation_checkpointing") is not True:
        failures.append({"code": "activation_checkpointing_not_used"})
    if "not family completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})
    verdict = "FULL_STACK_STEP_PROBE_PARSE_PASS" if not failures else "ENGINEERING_RECEIPT_INVALID"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Full-stack parser PASS validates bounded all-layer stack telemetry only. It is not a long-run 1B language-model training receipt and not overall baseline completion.",
    }

def parse_full_shape_block_probe(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    failures = []
    required = [
        "verdict",
        "kind",
        "config_id",
        "lane",
        "active_trainable_parameters",
        "probe_shape",
        "steps_completed",
        "tokens_per_second",
        "estimated_block_training_tflops_lower_bound",
        "full_config_required_sustained_tflops",
        "peak_memory_bytes",
        "uses_scaled_dot_product_attention",
    ]
    for field in required:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("verdict") != "FULL_SHAPE_BLOCK_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_full_shape_block_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    shape = receipt.get("probe_shape", {})
    if shape.get("seq_len") != 2048 or shape.get("hidden") != 2048 or shape.get("heads") != 16:
        failures.append({"code": "probe_shape_not_locked_c1_shape", "shape": shape})
    if receipt.get("steps_completed", 0) < 1:
        failures.append({"code": "no_probe_steps_completed", "actual": receipt.get("steps_completed")})
    if receipt.get("uses_scaled_dot_product_attention") is not True:
        failures.append({"code": "sdpa_not_used"})
    verdict = "FULL_SHAPE_BLOCK_PROBE_PARSE_PASS" if not failures else "ENGINEERING_RECEIPT_INVALID"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Full-shape block parser PASS validates representative block telemetry only. It is not full 19-layer 1B long-run throughput and not overall baseline completion.",
    }

def parse_full_memory_probe(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    failures = []
    required = [
        "verdict",
        "kind",
        "config_id",
        "lane",
        "active_trainable_parameters",
        "allocation_plan",
        "allocations",
        "peak_reserved_bytes",
        "device_total_memory_bytes",
        "fits_memory_probe",
    ]
    for field in required:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("verdict") != "FULL_CONFIG_MEMORY_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_memory_probe_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    if receipt.get("fits_memory_probe") is not True:
        failures.append({"code": "memory_probe_did_not_fit", "actual": receipt.get("fits_memory_probe")})
    if receipt.get("peak_reserved_bytes", 0) >= receipt.get("device_total_memory_bytes", 0):
        failures.append({"code": "peak_reserved_exceeds_device", "peak": receipt.get("peak_reserved_bytes"), "device": receipt.get("device_total_memory_bytes")})
    allocations = receipt.get("allocations")
    if not isinstance(allocations, list) or len(allocations) < 5:
        failures.append({"code": "memory_probe_missing_segments", "actual_count": len(allocations) if isinstance(allocations, list) else None})
    verdict = "FULL_MEMORY_PROBE_PARSE_PASS" if not failures else "ENGINEERING_RECEIPT_INVALID"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Memory probe parser PASS validates full-config allocation feasibility only. It is not full 1B forward/backward throughput and not overall baseline completion.",
    }

def parse_governed_probe(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    failures = []
    required = [
        "verdict",
        "kind",
        "config_id",
        "lane",
        "active_trainable_parameters",
        "full_config_parameter_count",
        "capability_target",
        "probe_shape",
        "steps_completed",
        "peak_memory_bytes",
        "full_config_required_sustained_tflops",
        "stop_rule",
    ]
    for field in required:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("verdict") != "GOVERNED_PROBE_NOT_COMPLETION":
        failures.append({"code": "unexpected_governed_probe_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    if receipt.get("steps_completed", 0) < 1:
        failures.append({"code": "no_probe_steps_completed", "actual": receipt.get("steps_completed")})
    if not receipt.get("cuda_available"):
        failures.append({"code": "cuda_not_available"})
    if not receipt.get("stop_rule", {}).get("no_completion_claim"):
        failures.append({"code": "stop_rule_missing_no_completion_claim"})
    verdict = "GOVERNED_PROBE_PARSE_PASS" if not failures else "ENGINEERING_RECEIPT_INVALID"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Governed probe parser PASS validates bounded GPU telemetry only. It is not representative 1B long-run throughput and not overall baseline completion.",
    }

def parse(path: Path) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    if receipt.get("kind") == "single_4090_full_stack_lm_loss_probe":
        return parse_full_stack_lm_loss_probe(receipt, path)
    if receipt.get("kind") == "single_4090_native_kernel_probe":
        return parse_native_kernel_probe(receipt, path)
    if receipt.get("kind") == "single_4090_full_stack_step_probe":
        return parse_full_stack_step_probe(receipt, path)
    if receipt.get("kind") == "single_4090_full_shape_block_probe":
        return parse_full_shape_block_probe(receipt, path)
    if receipt.get("kind") == "single_4090_full_config_memory_probe":
        return parse_full_memory_probe(receipt, path)
    if receipt.get("kind") == "single_4090_governed_probe":
        return parse_governed_probe(receipt, path)
    failures = []
    for field in REQUIRED_TOP_LEVEL:
        if field not in receipt:
            failures.append({"code": "missing_field", "field": field})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    memory = receipt.get("memory_plan", {})
    if isinstance(memory, dict) and memory.get("estimated_8bit_optimizer_total_gb", 999) >= 24:
        failures.append({"code": "memory_plan_exceeds_24gb", "actual": memory.get("estimated_8bit_optimizer_total_gb")})
    throughput = receipt.get("throughput", {})
    if isinstance(throughput, dict) and throughput.get("required_sustained_tflops", 9999) <= 0:
        failures.append({"code": "invalid_required_tflops", "actual": throughput.get("required_sustained_tflops")})
    if receipt.get("precondition_failures"):
        failures.append({"code": "precondition_failures", "items": receipt.get("precondition_failures")})
    dry_run = receipt.get("dry_run") is True
    verdict = "ENGINEERING_DRY_RUN_PASS" if dry_run and not failures else "ENGINEERING_RECEIPT_INVALID"
    if not dry_run and not failures:
        verdict = "ENGINEERING_RUN_READY_FOR_GOVERNED_EVAL"
    return {
        "verdict": verdict,
        "input_receipt": str(path),
        "failure_count": len(failures),
        "failures": failures,
        "completion_limit": "Parser PASS only validates the engineered 4090 baseline surface/receipt shape. It is not overall baseline completion.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = parse(args.receipt)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if result["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
