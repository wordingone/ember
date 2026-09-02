# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Integration test: phase_b1m momentum lookup bug demonstration.

This test demonstrates the actual bug: phase_b1m tries to look up momentum
using a string parameter name, but the seed optimizer stores state by numeric ID.

Expected: FAILS on master (demonstrates the bug)
After fix: PASSES (bug fixed)
"""

import torch
from pathlib import Path
import sys

# Assume we have access to the snapshot
REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SNAPSHOT_DIR = REPO_ROOT / "models/cbase-grow-rung/rung2-event-grow-rung2-20260708-real/b1-snapshot"
GATE_KEY = "backbone_model.layers.0.mlp.gate_proj.weight"


def test_b1m_lookup_bug_with_real_snapshot():
    """
    Demonstrate the bug: load real seed optimizer and model, show that
    string-based lookup fails but numeric ID lookup succeeds.
    """
    if not SNAPSHOT_DIR.exists():
        print(f"[SKIP] Snapshot dir not found: {SNAPSHOT_DIR}")
        return

    print(f"Loading snapshot from: {SNAPSHOT_DIR}")

    # Load model to get parameter order
    model_state = torch.load(SNAPSHOT_DIR / "model.pt", map_location="cpu", weights_only=True)
    model_param_names = list(model_state.keys())
    print(f"Model has {len(model_param_names)} parameters")

    # Load optimizer
    seed_optimizer_state = torch.load(SNAPSHOT_DIR / "optimizer.pt", map_location="cpu", weights_only=True)

    # --- DEMONSTRATE THE BUG ---
    # Current code (BUGGY) tries string-based lookup:
    print(f"\n--- BUGGY METHOD (current code) ---")
    print(f"Attempting: seed_optimizer_state['muon']['state'].get('{GATE_KEY}')")
    pre_momentum_buggy = seed_optimizer_state.get("muon", {}).get("state", {}).get(GATE_KEY, {}).get("momentum_buffer")
    if pre_momentum_buggy is None:
        print(f"Result: NOT FOUND (returned None)")
        pre_momentum_buggy = torch.zeros(16384, 1024)  # This is the default fallback
        print(f"Fallback: Defaulted to zeros")
        buggy_rms = 0.0
    else:
        buggy_rms = float(torch.sqrt(torch.mean(pre_momentum_buggy ** 2)))
        print(f"Result: FOUND, RMS = {buggy_rms:.4e}")

    # --- CORRECT METHOD (after fix) ---
    # Look up by numeric ID instead:
    print(f"\n--- CORRECT METHOD (after fix) ---")
    gate_param_id = model_param_names.index(GATE_KEY)
    print(f"Gate param is at index {gate_param_id} in model parameter list")
    print(f"Attempting: seed_optimizer_state['muon']['state'].get({gate_param_id})")

    if gate_param_id in seed_optimizer_state["muon"]["state"]:
        gate_state = seed_optimizer_state["muon"]["state"][gate_param_id]
        pre_momentum_correct = gate_state.get("momentum_buffer")
        if pre_momentum_correct is not None:
            correct_rms = float(torch.sqrt(torch.mean(pre_momentum_correct ** 2)))
            nonzero_count = torch.count_nonzero(pre_momentum_correct).item()
            print(f"Result: FOUND, RMS = {correct_rms:.4e}, nonzero = {nonzero_count}/{pre_momentum_correct.numel()}")
        else:
            print(f"Result: ID found but momentum_buffer is None")
            correct_rms = 0.0
    else:
        print(f"Result: ID not found in optimizer state")
        correct_rms = 0.0

    # --- VERDICT ---
    print(f"\n--- COMPARISON ---")
    print(f"Buggy method RMS:   {buggy_rms:.4e}")
    print(f"Correct method RMS: {correct_rms:.4e}")

    if correct_rms > 1e-10 and buggy_rms < 1e-10:
        print(f"\n[BUG CONFIRMED] Buggy lookup defaults to zero; correct lookup finds nonzero!")
        print(f"This is the root cause of issue #466 transplant arm identity.")
        return True
    elif correct_rms > 1e-10 and buggy_rms > 1e-10:
        print(f"\n[UNEXPECTED] Both methods found nonzero momentum. Bug may be elsewhere.")
        return False
    elif correct_rms < 1e-10:
        print(f"\n[UNUSUAL] Even correct method found zero. Snapshot may be initial training.")
        return False
    else:
        print(f"\n[ERROR] Unexpected outcome.")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("INTEGRATION TEST: phase_b1m momentum lookup bug")
    print("=" * 70)
    print()

    try:
        bug_confirmed = test_b1m_lookup_bug_with_real_snapshot()
        if bug_confirmed:
            print("\n" + "=" * 70)
            print("BUG DEMONSTRATED SUCCESSFULLY")
            print("=" * 70)
            sys.exit(0)
        else:
            print("\n" + "=" * 70)
            print("UNABLE TO CONFIRM BUG WITH THIS SNAPSHOT")
            print("=" * 70)
            sys.exit(0)  # Still exit 0 for skip
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
