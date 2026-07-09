#!/usr/bin/env python3
"""CPU tests for issue #524 cell M4: Branch-A boundary-policy wiring
(scripts/rung_boundary_momentum_transplant.py).

Covers the fail-closed nonzero-buffer assert (EngagementFailure on missing
or near-zero momentum buffer, never a silent reset/zeros substitution) and
the transplant success path (widened momentum shapes/values match
widen_state_dict's own declared math, mandatory receipt fields
pre_buffer_rms_consumed + resolved_lr_muon populated and threaded from the
caller, never a script constant).
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

HIDDEN = 4
FF_SEED = 3
N_LAYERS = 2
LR_MUON_TEST = 0.02  # deliberately the real config value, but threaded not hardcoded


def _synthetic_pre_state(n_layers=N_LAYERS, hidden=HIDDEN, ff=FF_SEED, seed=0):
    """A tiny synthetic pre-grow model_state + Muon opt_state (real on-disk
    nesting: {'muon': {'state': {int_param_id: {'momentum_buffer': ...}}}}),
    param ids assigned by dict-insertion order (matches
    resolve_gate_momentum_buffer's list(model_state.keys()).index(key)
    convention)."""
    import torch
    gen = torch.Generator().manual_seed(seed)
    model_state = {}
    opt_state_inner = {}
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        model_state[p + "gate_proj.weight"] = torch.randn(ff, hidden, generator=gen)
        model_state[p + "up_proj.weight"] = torch.randn(ff, hidden, generator=gen)
        model_state[p + "down_proj.weight"] = torch.randn(hidden, ff, generator=gen)
    for idx, key in enumerate(model_state.keys()):
        shape = model_state[key].shape
        opt_state_inner[idx] = {"momentum_buffer": torch.randn(*shape, generator=gen) * 0.1}
    opt_state = {"muon": {"state": opt_state_inner}}
    return model_state, opt_state


def test_a_transplant_succeeds_on_real_nonzero_buffers():
    """Full nonzero synthetic buffers: transplant returns widened momentum
    matching widen_state_dict's own row-dup / half-split-dup math exactly,
    and both mandatory receipt fields are populated."""
    import torch
    from rung_boundary_momentum_transplant import transplant_muon_ff_momentum

    model_state, opt_state = _synthetic_pre_state()
    result = transplant_muon_ff_momentum(
        model_state, opt_state, n_layers=N_LAYERS, lr_muon=LR_MUON_TEST)

    assert result["n_tensors_transplanted"] == N_LAYERS * 3, \
        f"[test_a] FAIL: expected {N_LAYERS * 3} tensors, got {result['n_tensors_transplanted']}"
    assert result["resolved_lr_muon"] == LR_MUON_TEST, \
        "[test_a] FAIL: resolved_lr_muon not threaded from caller"
    assert result["pre_buffer_rms_consumed"] > 1e-10, \
        "[test_a] FAIL: pre_buffer_rms_consumed reads as zero"

    grown = result["post_grow_momentum_state_dict"]
    for i in range(N_LAYERS):
        p = f"backbone_model.layers.{i}.mlp."
        gate_key, up_key, down_key = p + "gate_proj.weight", p + "up_proj.weight", p + "down_proj.weight"
        pre_gate = opt_state["muon"]["state"][list(model_state.keys()).index(gate_key)]["momentum_buffer"]
        pre_up = opt_state["muon"]["state"][list(model_state.keys()).index(up_key)]["momentum_buffer"]
        pre_down = opt_state["muon"]["state"][list(model_state.keys()).index(down_key)]["momentum_buffer"]

        expected_gate = torch.cat([pre_gate, pre_gate], dim=0)
        expected_up = torch.cat([pre_up, pre_up], dim=0)
        expected_down = torch.cat([pre_down * 0.5, pre_down * 0.5], dim=1)

        assert torch.equal(grown[gate_key], expected_gate), f"[test_a] FAIL: gate_proj momentum pushforward mismatch layer {i}"
        assert torch.equal(grown[up_key], expected_up), f"[test_a] FAIL: up_proj momentum pushforward mismatch layer {i}"
        assert torch.equal(grown[down_key], expected_down), f"[test_a] FAIL: down_proj momentum pushforward mismatch layer {i}"
        assert grown[gate_key].shape == (2 * FF_SEED, HIDDEN), "[test_a] FAIL: gate_proj widened shape wrong"
        assert grown[down_key].shape == (HIDDEN, 2 * FF_SEED), "[test_a] FAIL: down_proj widened shape wrong"

    print(f"[test_a] PASS n_tensors={result['n_tensors_transplanted']} "
          f"pre_buffer_rms_consumed={result['pre_buffer_rms_consumed']:.6e} "
          f"resolved_lr_muon={result['resolved_lr_muon']}")
    return True


def test_b_missing_buffer_fails_closed():
    """Deleting one layer's gate_proj entry from the optimizer state
    (simulating a real missing-buffer condition, e.g. an initial-training
    run with no prior momentum) must raise EngagementFailure naming that
    key -- never a silent zeros_like substitution."""
    from rung_boundary_momentum_transplant import transplant_muon_ff_momentum
    from p5_ratio_audit.run_p5_audit import EngagementFailure

    model_state, opt_state = _synthetic_pre_state()
    missing_key = "backbone_model.layers.0.mlp.gate_proj.weight"
    missing_idx = list(model_state.keys()).index(missing_key)
    del opt_state["muon"]["state"][missing_idx]

    raised = False
    try:
        transplant_muon_ff_momentum(model_state, opt_state, n_layers=N_LAYERS, lr_muon=LR_MUON_TEST)
    except EngagementFailure as e:
        raised = True
        assert missing_key in str(e), f"[test_b] FAIL: exception message does not name the missing key: {e}"
    assert raised, "[test_b] FAIL: missing buffer did not raise EngagementFailure"
    print("[test_b] PASS: missing buffer raised EngagementFailure, named the key")
    return True


def test_c_near_zero_buffer_fails_closed():
    """A near-zero (rms < 1e-10) momentum buffer -- the initial-training-run
    condition the spec explicitly names as Branch-A N/A -- must also raise
    EngagementFailure, not silently transplant near-zero noise."""
    import torch
    from rung_boundary_momentum_transplant import transplant_muon_ff_momentum
    from p5_ratio_audit.run_p5_audit import EngagementFailure

    model_state, opt_state = _synthetic_pre_state()
    zero_key = "backbone_model.layers.1.mlp.down_proj.weight"
    zero_idx = list(model_state.keys()).index(zero_key)
    shape = model_state[zero_key].shape
    opt_state["muon"]["state"][zero_idx]["momentum_buffer"] = torch.zeros(*shape)

    raised = False
    try:
        transplant_muon_ff_momentum(model_state, opt_state, n_layers=N_LAYERS, lr_muon=LR_MUON_TEST)
    except EngagementFailure as e:
        raised = True
        assert zero_key in str(e), f"[test_c] FAIL: exception message does not name the near-zero key: {e}"
    assert raised, "[test_c] FAIL: near-zero buffer did not raise EngagementFailure"
    print("[test_c] PASS: near-zero buffer raised EngagementFailure, named the key")
    return True


def test_d_resolved_lr_muon_never_a_constant():
    """resolved_lr_muon must equal exactly whatever the caller passes, not
    a value baked into the module (regression guard for the #513 class of
    defect: a script constant silently substituted for the real config)."""
    from rung_boundary_momentum_transplant import transplant_muon_ff_momentum

    model_state, opt_state = _synthetic_pre_state()
    distinctive_lr = 0.014159
    result = transplant_muon_ff_momentum(
        model_state, opt_state, n_layers=N_LAYERS, lr_muon=distinctive_lr)
    assert result["resolved_lr_muon"] == distinctive_lr, \
        "[test_d] FAIL: resolved_lr_muon did not thread the caller's distinctive value"
    print(f"[test_d] PASS resolved_lr_muon={result['resolved_lr_muon']}")
    return True


TESTS = [
    test_a_transplant_succeeds_on_real_nonzero_buffers,
    test_b_missing_buffer_fails_closed,
    test_c_near_zero_buffer_fails_closed,
    test_d_resolved_lr_muon_never_a_constant,
]


def main() -> int:
    failures = []
    for t in TESTS:
        try:
            ok = t()
            if not ok:
                failures.append(t.__name__)
        except AssertionError as e:
            failures.append(f"{t.__name__}: {e}")
        except Exception as e:
            failures.append(f"{t.__name__}: unexpected {type(e).__name__}: {e}")

    if failures:
        print("TEST_524_M4_MOMENTUM_TRANSPLANT_FAIL")
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("TEST_524_M4_MOMENTUM_TRANSPLANT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
