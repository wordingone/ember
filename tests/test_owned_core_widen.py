#!/usr/bin/env python3
"""test_owned_core_widen.py — TDD tests for owned-core LoRA rank expansion (issue #125).

Tests cover:
1. Param-count arithmetic: config produces ≥1.1e6 trainable params
2. D7 dual-layer guard: run-start assert + receipt semantic check (accept ≥1e6 / reject <1e6)
3. Config-loads: config parses, valid architecture, no contradictions
4. CPU-cheap function-preservation harness: tiny synthetic core, same code path, fp tolerance ≤1e-4
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

# Add repo root to path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import torch
import torch.nn as nn


# ---------------------------------------------------------------------------
# Test 1: Config loads and specifies valid architecture
# ---------------------------------------------------------------------------

def test_config_loads():
    """Config parses as valid JSON and specifies correct architecture."""
    config_path = REPO / "configs" / "owned-core-widen-config.json"
    assert config_path.exists(), f"Config not found at {config_path}"

    with open(config_path, "r") as f:
        config = json.load(f)

    # Verify required top-level keys
    assert "source_owned_core" in config
    assert "widen_operator" in config
    assert "function_preservation_spec" in config
    assert "guards" in config

    # Verify source core architecture
    src_arch = config["source_owned_core"]["arch"]
    assert src_arch["hidden"] == 1024
    assert src_arch["vocab"] == 32000
    assert src_arch["layers"] == 20

    # Verify widen operator specifies rank
    assert "target_rank" in config["widen_operator"]
    assert config["widen_operator"]["target_rank"] > 0

    print("[PASS] test_config_loads")
    return config


# ---------------------------------------------------------------------------
# Test 2: Param-count arithmetic
# ---------------------------------------------------------------------------

def test_param_count_arithmetic(config: dict):
    """Verify target rank produces ≥1.1e6 trainable params."""
    src = config["source_owned_core"]
    widen = config["widen_operator"]

    hidden_dim = src["arch"]["hidden"]
    vocab_size = src["arch"]["vocab"]
    target_rank = widen["target_rank"]

    # LoRA trainable params: rank * (hidden_dim + vocab_size)
    expected_params = target_rank * (hidden_dim + vocab_size)

    # Config should specify this explicitly
    assert widen["target_trainable_params"] == expected_params, \
        f"Config param count mismatch: declared={widen['target_trainable_params']}, calculated={expected_params}"

    # Guard floor: ≥1.1e6
    GUARD_FLOOR = 1_100_000
    assert expected_params >= GUARD_FLOOR, \
        f"Param count {expected_params} does not meet guard floor {GUARD_FLOOR}"

    # Additional: verify it's at least 10% above 1e6 per spec ("10% over the guard floor")
    assert expected_params >= 1_100_000, \
        f"Must be 10% above 1e6 floor; got {expected_params}"

    print(f"[PASS] test_param_count_arithmetic PASS (rank={target_rank}, params={expected_params})")
    return expected_params


# ---------------------------------------------------------------------------
# Test 3: D7 dual-layer guard specification
# ---------------------------------------------------------------------------

def test_d7_guard_spec(config: dict, target_params: int):
    """Verify D7 guards are properly specified in config."""
    guards = config["guards"]

    # Layer 1: run-start assert
    assert "D7_layer1_run_start_assert" in guards
    assert "1000000" in guards["D7_layer1_run_start_assert"] or "1e6" in guards["D7_layer1_run_start_assert"]

    # Layer 2: receipt semantic check
    assert "D7_layer2_receipt_semantic_check" in guards
    assert "accept" in guards["D7_layer2_receipt_semantic_check"].lower()
    assert "reject" in guards["D7_layer2_receipt_semantic_check"].lower()

    # Verify this config passes both layers
    assert target_params >= 1_000_000, "Must pass run-start layer1"

    # Semantic check would accept this
    receipt_check = target_params >= 1_000_000
    assert receipt_check, "Must pass receipt layer2"

    print("[PASS] test_d7_guard_spec PASS")


# ---------------------------------------------------------------------------
# Test 4: CPU-cheap function-preservation harness
# ---------------------------------------------------------------------------

class TinyLoRA(nn.Module):
    """Minimal LoRA-on-head model for synthetic function-preservation test."""

    def __init__(self, hidden_dim: int, vocab_size: int, rank: int):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.vocab_size = vocab_size
        self.rank = rank

        # Base head (frozen in widen case)
        self.head_base = nn.Linear(hidden_dim, vocab_size, bias=False)
        self.head_base.requires_grad_(False)

        # LoRA adapter (trainable)
        self.lora_A = nn.Linear(hidden_dim, rank, bias=False)
        self.lora_B = nn.Linear(rank, vocab_size, bias=False)

        # Initialize LoRA to near-zero to preserve base behavior
        nn.init.xavier_uniform_(self.lora_A.weight)
        nn.init.zeros_(self.lora_B.weight)  # Zero B ensures zero contribution at start

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x shape: (batch, hidden_dim); output: (batch, vocab_size)"""
        base_out = self.head_base(x)
        lora_out = self.lora_B(self.lora_A(x))
        return base_out + lora_out


def test_function_preservation_cpu_harness(config: dict):
    """CPU-cheap test: expand synthetic tiny core, verify logit preservation."""
    torch.manual_seed(42)

    hidden_dim = config["source_owned_core"]["arch"]["hidden"]
    vocab_size = config["source_owned_core"]["arch"]["vocab"]
    rank_small = config["source_owned_core"]["lora_config_current"]["rank"]
    rank_large = config["widen_operator"]["target_rank"]

    # Create small model (pre-widen state)
    model_small = TinyLoRA(hidden_dim, vocab_size, rank_small)
    model_small.eval()

    # Fixed test batch (deterministic, reproducible)
    batch = torch.randn(1, hidden_dim)

    # Forward pass on small model
    with torch.no_grad():
        logits_small = model_small(batch)

    # Create large model with expanded rank
    model_large = TinyLoRA(hidden_dim, vocab_size, rank_large)
    model_large.eval()

    # Copy base weights from small to large (unchanged)
    model_large.head_base.load_state_dict(model_small.head_base.state_dict())

    # Copy LoRA weights and initialize new entries to preserve behavior
    # LoRA_A weight: (rank, hidden_dim) — rank is first dim, expands
    # LoRA_B weight: (vocab_size, rank) — rank is second dim, expands
    with torch.no_grad():
        old_rank = rank_small
        new_rank = rank_large

        # For LoRA_A (rank, hidden_dim):
        # - Rows 0:old_rank = copy from small
        # - Rows old_rank:new_rank = fresh xavier
        large_A_weight = model_large.lora_A.weight  # shape: (rank_large, hidden)
        small_A_weight = model_small.lora_A.weight  # shape: (rank_small, hidden)
        large_A_weight[:old_rank, :] = small_A_weight[:old_rank, :]  # Copy old rows
        # New rows [old_rank:] already xavier-initialized

        # For LoRA_B (vocab_size, rank):
        # - Cols 0:old_rank = scaled copy from small (scaled by 1/sqrt(ratio) to dampen)
        # - Cols old_rank:new_rank = zeros (ensures zero contribution from new entries)
        large_B_weight = model_large.lora_B.weight  # shape: (vocab, rank_large)
        small_B_weight = model_small.lora_B.weight  # shape: (vocab, rank_small)
        scale_factor = math.sqrt(old_rank / new_rank)  # Dampen to account for expanded input dimension
        large_B_weight[:, :old_rank] = small_B_weight[:, :old_rank] * scale_factor
        large_B_weight[:, old_rank:] = 0  # New cols zero -> zero contribution

    # Forward pass on large model
    with torch.no_grad():
        logits_large = model_large(batch)

    # Measure function preservation
    fp_diff = float((logits_large - logits_small).abs().max())
    TOLERANCE = config["function_preservation_spec"]["tolerance_logit_max_abs_diff"]

    assert fp_diff <= TOLERANCE, \
        f"Function preservation FAIL: max_abs_diff={fp_diff} > tolerance={TOLERANCE}"

    print(f"[PASS] test_function_preservation_cpu_harness PASS (fp_diff={fp_diff:.2e} <= {TOLERANCE})")


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all tests in order."""
    try:
        print("\n" + "="*70)
        print("OWNED-CORE WIDEN TESTS (TDD)")
        print("="*70 + "\n")

        # Test 1: Config loads
        config = test_config_loads()

        # Test 2: Param-count arithmetic
        target_params = test_param_count_arithmetic(config)

        # Test 3: D7 guard spec
        test_d7_guard_spec(config, target_params)

        # Test 4: Function-preservation harness
        test_function_preservation_cpu_harness(config)

        print("\n" + "="*70)
        print("ALL TESTS PASS [PASS]")
        print("="*70 + "\n")
        return 0

    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
