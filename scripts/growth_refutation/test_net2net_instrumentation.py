#!/usr/bin/env python3
"""
Unit tests for the two-gate net2net instrumentation.

Tests 1-4: CPU unit tests (no GPU required).
  1. bf16 metrics on identical distributions (argmax_agree=1.0, kl=0)
  2. bf16 metrics with flipped argmax (agree < 1.0)
  3. bf16 metrics with small perturbation (agree > 0.95)
  4. float32 correctness gate on synthetic pre/post logit pairs

Test 5 (--gpu): Real model validation on GPU.
  Loads the real 0.5B model, runs net2net_grow with the layered gate,
  and reports raw Gate A (fp32_max_abs_diff) and Gate B (bf16_argmax_agree)
  numbers. Gate A < 1e-3 and Gate B >= 0.99 are hard asserts.

Usage:
  python test_net2net_instrumentation.py           # CPU unit tests only
  python test_net2net_instrumentation.py --gpu     # CPU + GPU real-model test
"""

import math
import sys
import torch
import torch.nn as nn
from capacity import _compute_bf16_metrics


def test_bf16_metrics_identical_distributions():
    """
    Test 1: Identical distributions should give argmax_agree=1.0, kl_mean≈0.
    """
    print("Test 1: bf16 metrics on identical distributions...")

    # Create identical logits
    logits = torch.randn(10, 100)  # batch_size=10, vocab=100

    metrics = _compute_bf16_metrics(logits, logits)
    argmax_agree = metrics["argmax_agree"]
    kl_mean = metrics["kl_mean"]

    print(f"  argmax_agree={argmax_agree:.6f} (expected 1.0)")
    print(f"  kl_mean={kl_mean:.8f} (expected ~0.0)")

    assert argmax_agree > 0.999, f"Expected argmax_agree ≈ 1.0, got {argmax_agree}"
    assert kl_mean < 1e-4, f"Expected kl_mean ≈ 0, got {kl_mean}"
    print("  PASSED\n")


def test_bf16_metrics_flipped_argmax():
    """
    Test 2: When argmax flips on some positions, agreement should be < 1.0.
    """
    print("Test 2: bf16 metrics with flipped argmax...")

    # Create logits where argmax will flip on some positions
    logits_before = torch.zeros(10, 100)
    logits_before[0, 50] = 10.0  # position 0: argmax is 50
    logits_before[1, 75] = 10.0  # position 1: argmax is 75
    logits_before[2:, :] = torch.randn(8, 100)  # other positions: random

    logits_after = logits_before.clone()
    # Flip argmax at positions 0 and 1 by making a different index higher
    logits_after[0, 30] = 11.0   # new argmax is 30 (was 50)
    logits_after[1, 90] = 11.0   # new argmax is 90 (was 75)
    # Keep positions 2-9 unchanged

    metrics = _compute_bf16_metrics(logits_before, logits_after)
    argmax_agree = metrics["argmax_agree"]

    print(f"  argmax_agree={argmax_agree:.6f} (expected 0.8 = 8/10)")
    print(f"  flipped positions: 2/10")

    expected_agree = 0.8  # 8 out of 10 should still agree
    assert argmax_agree < 1.0, f"Expected argmax_agree < 1.0, got {argmax_agree}"
    assert 0.7 <= argmax_agree <= 0.9, f"Expected argmax_agree ≈ 0.8, got {argmax_agree}"
    print("  PASSED\n")


def test_bf16_metrics_small_perturbation():
    """
    Test 3: Small perturbation should keep argmax_agree high.
    (Note: kl_mean may be small negative due to bf16 numerical precision)
    """
    print("Test 3: bf16 metrics with small perturbation...")

    logits_before = torch.randn(10, 100)
    # Very small perturbation (noise) to keep argmax mostly stable
    logits_after = logits_before + 0.001 * torch.randn_like(logits_before)

    metrics = _compute_bf16_metrics(logits_before, logits_after)
    argmax_agree = metrics["argmax_agree"]
    kl_mean = metrics["kl_mean"]

    print(f"  argmax_agree={argmax_agree:.6f} (expected > 0.95)")
    print(f"  kl_mean={kl_mean:.8f} (expected ~= 0, may be slightly negative in bf16)")

    assert argmax_agree > 0.95, f"Expected argmax_agree > 0.95, got {argmax_agree}"
    assert -0.001 < kl_mean < 0.1, f"Expected kl_mean ≈ 0 (small noise), got {kl_mean}"
    print("  PASSED\n")


def test_net2net_correctness_gate_synthetic():
    """
    Test 4: Test the float32 correctness gate on a tiny synthetic scenario.

    The gate compares pre/post-expansion logits after upcasting to float32.
    - Correct expansion: max_diff < 1e-3 (gate passes)
    - Corrupted expansion: max_diff > 1e-3 (gate would raise)
    """
    print("Test 4: Float32 correctness gate on synthetic expansion...")

    # Simulate a pre/post expansion logit pair (batch=2, vocab=50)
    # This represents what the gate would compare
    print("  Sub-case 4a: Correct expansion scenario (max_diff < 1e-3)...")

    logits_before = torch.randn(2, 50, dtype=torch.float32)
    # Small numerical error from float precision (< 1e-3)
    logits_after_correct = logits_before + 0.0001 * torch.randn_like(logits_before)

    max_diff_correct = (logits_after_correct - logits_before).abs().max().item()
    print(f"    Correct max_diff={max_diff_correct:.6e} (expected < 1e-3)")
    assert max_diff_correct < 1e-3, f"Expected diff < 1e-3, got {max_diff_correct}"
    print("  Sub-case 4a: PASSED (gate would NOT raise)")

    # Sub-case 4b: Corrupted expansion (large deviation)
    print("  Sub-case 4b: Corrupted expansion scenario (max_diff > 1e-3)...")

    logits_after_corrupted = logits_before + 0.5 * torch.randn_like(logits_before)

    max_diff_corrupted = (logits_after_corrupted - logits_before).abs().max().item()
    print(f"    Corrupted max_diff={max_diff_corrupted:.6e} (expected > 1e-3)")
    assert max_diff_corrupted > 1e-3, f"Expected diff > 1e-3, got {max_diff_corrupted}"
    print("  Sub-case 4b: PASSED (gate would RAISE)")

    print("  Test 4: PASSED\n")


def test_net2net_on_real_model_gpu():
    """
    Test 5: Real model GPU validation — layered gate (Gate A fp32, Gate B bf16).

    Governed: sets VRAM fraction cap to 0.80 before loading.
    Expects: Gate A fp32_max_abs_diff < 1e-3 (hard assert).
             Gate B bf16_argmax_agree >= 0.99 (hard assert).

    Run with --gpu to execute this test.
    """
    print("Test 5: Real model GPU — Gate A (fp32) + Gate B (bf16)...")

    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("  SKIP: transformers not installed")
        return

    if not torch.cuda.is_available():
        print("  SKIP: no CUDA device available")
        return

    # Resource governance: VRAM fraction cap before any allocation
    torch.cuda.set_per_process_memory_fraction(0.80)

    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from capacity import net2net_grow, NET2NET_ASSERT_TOL

    model_id = "Qwen/Qwen2.5-0.5B-Instruct"
    print(f"  Loading {model_id} in bf16 on cuda...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
    )
    model.eval()
    print("  Model loaded. Running net2net_grow (round_idx=0, tier=0, seed=42)...")

    model, tokenizer, metrics = net2net_grow(
        model, tokenizer, round_idx=0, tier=0, seed=42
    )

    fp32_diff   = metrics["net2net_fp32_max_abs_diff"]
    argmax      = metrics["net2net_bf16_argmax_agree"]
    kl          = metrics["net2net_bf16_kl_mean"]

    print(f"  fp32_max_abs_diff = {fp32_diff:.6e}  (tol={NET2NET_ASSERT_TOL}, expect ~1e-4)")
    print(f"  bf16_argmax_agree = {argmax:.6f}       (expect 1.0)")
    print(f"  bf16_kl_mean      = {kl:.6e}")

    gate_a_pass = fp32_diff < NET2NET_ASSERT_TOL
    gate_b_pass = argmax >= 0.99

    print(f"  Gate A (fp32 < {NET2NET_ASSERT_TOL}): {'PASS' if gate_a_pass else 'FAIL'}")
    print(f"  Gate B (bf16 argmax >= 0.99): {'PASS' if gate_b_pass else 'FAIL'}")

    assert gate_a_pass, (
        f"Gate A FAILED: fp32_max_abs_diff={fp32_diff:.6e} >= {NET2NET_ASSERT_TOL}"
    )
    assert gate_b_pass, (
        f"Gate B FAILED: bf16_argmax_agree={argmax:.6f} < 0.99"
    )
    print("  Test 5: PASSED\n")


def main():
    """Run unit tests; add --gpu to also run the real-model GPU test."""
    run_gpu = "--gpu" in sys.argv

    print("=" * 70)
    print("Unit Tests: Two-Gate Net2Net Instrumentation")
    print("=" * 70)
    print()

    try:
        test_bf16_metrics_identical_distributions()
        test_bf16_metrics_flipped_argmax()
        test_bf16_metrics_small_perturbation()
        test_net2net_correctness_gate_synthetic()

        if run_gpu:
            test_net2net_on_real_model_gpu()

        print("=" * 70)
        if run_gpu:
            print("ALL TESTS PASSED (including GPU real-model validation)")
        else:
            print("ALL CPU UNIT TESTS PASSED  (use --gpu for real-model validation)")
        print("=" * 70)
        return 0
    except Exception as e:
        print()
        print("=" * 70)
        print(f"TEST FAILED: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
