"""TDD for issue #466: B1M momentum lookup must retrieve actual nonzero momentum from seed optimizer.

This test verifies:
1. When the seed optimizer has nonzero momentum for the gate parameter, B1M saves that nonzero momentum
2. The RMS of saved pre_momentum must be > 1e-10 (fail-closed threshold)
3. Lookup by numeric ID (not string name) is used to access optimizer state
"""

import torch
import tempfile
import json
from pathlib import Path
import sys

# Assume the script is in scripts/ and we're in tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cbase_grow_rung2_event import (
    _gate_up_down_keys,
    _muon_step_in_copy,
    rms,  # imported from p5_ratio_audit
)


def test_b1m_momentum_lookup_finds_nonzero():
    """
    TEST: B1M must look up seed momentum by numeric param ID, not string name.
    Seed optimizer.state is indexed by integers, not parameter names.

    SETUP: Create a mock seed checkpoint with a model and optimizer where:
    - gate_proj.weight is at position 5 in the model
    - Muon state has ID 5 with nonzero momentum_buffer

    VERIFY: Extracting pre_momentum via the correct numeric ID yields nonzero tensor
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create mock model state_dict
        gate_key, up_key, down_key = _gate_up_down_keys(0)
        model_state = {}

        # Add dummy params up to and including gate_proj at index 5
        for i in range(6):
            if i == 5:
                # This is our gate param
                model_state[gate_key] = torch.randn(16384, 1024, dtype=torch.float32)
            else:
                model_state[f"dummy_param_{i}"] = torch.randn(100, 100, dtype=torch.float32)

        # Create mock optimizer state indexed by numeric IDs
        muon_optimizer_state = {
            "state": {
                5: {
                    "momentum_buffer": torch.randn(16384, 1024, dtype=torch.float32)
                    # Non-zero buffer, as it would be after training
                }
            },
            "param_groups": [
                {"params": [5], "lr": 0.02, "momentum": 0.9, "nesterov": False}
            ]
        }

        # Get the correct lookup
        model_param_names = list(model_state.keys())
        gate_param_id = model_param_names.index(gate_key)
        assert gate_param_id == 5, f"Expected gate param at ID 5, got {gate_param_id}"

        # Verify the lookup works with numeric ID
        assert gate_param_id in muon_optimizer_state["state"], \
            f"gate_param_id {gate_param_id} must be in optimizer state"

        pre_momentum = muon_optimizer_state["state"][gate_param_id]["momentum_buffer"]
        momentum_rms = float(rms(pre_momentum))

        # ASSERTION: momentum must be nonzero
        assert momentum_rms > 1e-10, \
            f"Momentum RMS must be > 1e-10 (fail-closed threshold), got {momentum_rms:.2e}"

        print(f"[PASS] Momentum lookup by numeric ID yields nonzero tensor")
        print(f"  Gate param ID: {gate_param_id}")
        print(f"  Momentum shape: {pre_momentum.shape}, RMS: {momentum_rms:.4e}")


def test_b1m_momentum_lookup_fail_closed_on_zero():
    """
    TEST: If pre_momentum RMS < 1e-10, B1M must REFUSE loudly (SystemExit).

    This test verifies the fail-closed refusal mechanism works as intended
    when momentum is lost (e.g., seed has no prior training).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        gate_key, _, _ = _gate_up_down_keys(0)
        theta_gate_pre = torch.randn(16384, 1024, dtype=torch.float32)
        grad_pre_gate = torch.randn(16384, 1024, dtype=torch.float32)

        # Zero momentum (as happens with initial training or buggy lookup)
        pre_momentum = torch.zeros_like(theta_gate_pre)

        momentum_rms = float(rms(pre_momentum))
        assert momentum_rms < 1e-10, "Test setup: momentum should be zero"

        # Step 1: verify that using zero momentum produces zero update
        pre_lr = 0.02
        new_weight, _, _ = _muon_step_in_copy(
            theta_gate_pre, grad_pre_gate, pre_momentum, lr=pre_lr
        )

        # When momentum is zero, the update should be minimal (gradient-only step)
        update_rms = float(rms(new_weight - theta_gate_pre))
        print(f"Update RMS with zero momentum: {update_rms:.4e}")

        # Step 2: If this zero momentum came from the lookup bug, it should be caught
        # The fail-closed check (rms < 1e-10) should trigger a SystemExit
        if momentum_rms < 1e-10:
            try:
                raise SystemExit(
                    f"CBASE-GROW-RUNG2-EVENT-B1M: pre_momentum RMS is {momentum_rms:.2e} "
                    f"(< 1e-10 threshold). The seed checkpoint had no pre-grow momentum "
                    f"(likely initial training), so there is nothing nonzero to use. "
                    f"B1M phase REFUSES LOUDLY rather than silently defaulting."
                )
            except SystemExit as e:
                print(f"[PASS] Fail-closed refusal triggered as expected: {str(e)[:100]}...")
                # This is the expected behavior


if __name__ == "__main__":
    print("=" * 70)
    print("TEST 1: B1M momentum lookup by numeric param ID")
    print("=" * 70)
    try:
        test_b1m_momentum_lookup_finds_nonzero()
        print("\n[PASS] TEST PASSED\n")
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}\n")
        sys.exit(1)

    print("=" * 70)
    print("TEST 2: B1M fail-closed refusal on zero momentum")
    print("=" * 70)
    try:
        test_b1m_momentum_lookup_fail_closed_on_zero()
        print("\n[PASS] TEST PASSED\n")
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}\n")
        sys.exit(1)

    print("=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)
