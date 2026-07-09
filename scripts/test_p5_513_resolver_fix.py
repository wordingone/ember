#!/usr/bin/env python3
"""CPU tests for issue #513: build_real_d_comm_closures' momentum-buffer
resolver fix (scripts/p5_ratio_audit/run_p5_audit.py).

Defect: the prior resolver read `opt_state['state'][gate_key]` -- a STRING
key at the TOP level of the optimizer state -- but the real on-disk
optimizer.pt stores `{'muon': {'state': {int_param_id: {'momentum_buffer':
...}}}}`, keyed by the INTEGER position of the parameter in the model's own
state_dict. The string-keyed lookup never matched, so it silently fell
through to a `zeros_like` substitution -- the b3 d_comm arms were measured
on a silently-zeroed momentum buffer (issue #513).

Three tests, per the frozen fix spec:
  (a) resolve_gate_momentum_buffer() returns the REAL buffer from the
      actual on-disk optimizer.pt of the 2026-07-08 remeasure run (rms
      ~3.6e-4, nonzero) -- skipped gracefully if the (gitignored, ~GB-
      scale) checkpoint tree isn't present on this box.
  (b) a synthetic mis-keyed checkpoint (old string-keyed top-level 'state'
      nesting) resolves to None under the new resolver, and
      build_real_d_comm_closures fail-closes (EngagementFailure) rather
      than silently substituting zeros -- covering BOTH the nested
      {'muon': {'state': {int_id: ...}}} and the flat
      {'state': {int_id: ...}} tolerant nestings.
  (c) compute_d_comm_real_run()'s receipt gains pre_buffer_rms_consumed
      and resolved_lr_muon fields (never a script constant).
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

GATE_KEY = "backbone_model.layers.0.mlp.gate_proj.weight"
UP_KEY = "backbone_model.layers.0.mlp.up_proj.weight"
DOWN_KEY = "backbone_model.layers.0.mlp.down_proj.weight"

# Real on-disk checkpoint (gitignored, models/ tree) -- the 2026-07-08
# rung2-event b1-snapshot whose optimizer.pt this issue's forensic examines.
# Relative suffix only (leak-gate discipline); the absolute root is
# REPO_ROOT (this repo checkout) or EMBER_MODELS_ROOT if set.
REAL_CKPT_RELATIVE = os.path.join(
    "models", "cbase-grow-rung", "rung2-event-grow-rung2-20260708-real", "b1-snapshot")
EXPECTED_REAL_BUFFER_RMS = 3.6057e-4
REAL_BUFFER_RMS_TOLERANCE = 3e-7  # matches the pre-registration's "cached 3.6057e-4"


def _real_ckpt_dir():
    root = os.environ.get("EMBER_MODELS_ROOT", REPO_ROOT)
    d = os.path.join(root, REAL_CKPT_RELATIVE)
    if os.path.isfile(os.path.join(d, "model.pt")) and os.path.isfile(os.path.join(d, "optimizer.pt")):
        return d
    return None


def test_a_real_buffer_resolves_nonzero():
    """resolve_gate_momentum_buffer() against the real on-disk optimizer.pt
    of the remeasure run returns the real buffer, rms ~3.6e-4, nonzero."""
    ckpt_dir = _real_ckpt_dir()
    if ckpt_dir is None:
        print("[test_a] SKIP: real checkpoint tree not present on this box "
              f"(gitignored models/ tree; looked under {REAL_CKPT_RELATIVE!r})")
        return True

    import torch
    from p5_ratio_audit.run_p5_audit import resolve_gate_momentum_buffer, rms

    model_state = torch.load(os.path.join(ckpt_dir, "model.pt"), map_location="cpu", weights_only=True)
    opt_state = torch.load(os.path.join(ckpt_dir, "optimizer.pt"), map_location="cpu", weights_only=True)

    buf = resolve_gate_momentum_buffer(model_state, opt_state, GATE_KEY)
    assert buf is not None, "[test_a] FAIL: resolver returned None against the real checkpoint"
    measured_rms = rms(buf)
    print(f"[test_a] resolved real buffer rms={measured_rms:.6e} (expected ~{EXPECTED_REAL_BUFFER_RMS:.4e})")
    assert measured_rms > 1e-10, f"[test_a] FAIL: resolved buffer is zero (rms={measured_rms:.3e})"
    assert abs(measured_rms - EXPECTED_REAL_BUFFER_RMS) < REAL_BUFFER_RMS_TOLERANCE, (
        f"[test_a] FAIL: resolved rms {measured_rms:.6e} does not match the pre-registered "
        f"cached value {EXPECTED_REAL_BUFFER_RMS:.4e} within tolerance")

    # OLD (defective) resolver, for contrast -- must be None/missing (this
    # IS the P-3 forensic's first check, replicated here as a regression
    # guard so the old defect can never silently return).
    old_result = opt_state.get("state", {}).get(GATE_KEY, {}).get("momentum_buffer")
    assert old_result is None, "[test_a] FAIL: the OLD string-keyed resolver unexpectedly found something"
    print("[test_a] PASS")
    return True


def test_b_mis_keyed_checkpoint_fails_closed():
    """A synthetic checkpoint using the OLD (mis-keyed) nesting resolves to
    None, and build_real_d_comm_closures refuses (EngagementFailure) rather
    than silently substituting zeros. Covers both the nested
    {'muon': {'state': {int_id: ...}}} and flat {'state': {int_id: ...}}
    tolerant forms on the PASS side, and the old-style top-level
    string-keyed 'state' on the FAIL side."""
    import torch
    from p5_ratio_audit.run_p5_audit import (
        resolve_gate_momentum_buffer, build_real_d_comm_closures, EngagementFailure)

    pre_model_state = {GATE_KEY: torch.randn(4, 4), UP_KEY: torch.randn(4, 4), DOWN_KEY: torch.randn(4, 4)}
    real_buf = torch.randn(4, 4) * 0.05

    # PASS side 1: real nested {'muon': {'state': {int_id: ...}}}.
    nested_opt = {"muon": {"state": {0: {"momentum_buffer": real_buf}}}}
    resolved = resolve_gate_momentum_buffer(pre_model_state, nested_opt, GATE_KEY)
    assert resolved is not None and torch.equal(resolved, real_buf), \
        "[test_b] FAIL: nested {'muon': {'state': {int_id}}} form did not resolve"

    # PASS side 2: flat {'state': {int_id: ...}} tolerant form.
    flat_opt = {"state": {0: {"momentum_buffer": real_buf}}}
    resolved_flat = resolve_gate_momentum_buffer(pre_model_state, flat_opt, GATE_KEY)
    assert resolved_flat is not None and torch.equal(resolved_flat, real_buf), \
        "[test_b] FAIL: flat {'state': {int_id}} tolerant form did not resolve"

    # FAIL side: the OLD defect shape -- top-level 'state' keyed by the
    # STRING gate_key (never a real on-disk shape) -- must resolve to None.
    mis_keyed_opt = {"state": {GATE_KEY: {"momentum_buffer": real_buf}}}
    resolved_mis = resolve_gate_momentum_buffer(pre_model_state, mis_keyed_opt, GATE_KEY)
    assert resolved_mis is None, "[test_b] FAIL: mis-keyed (string-key) checkpoint unexpectedly resolved"
    print("[test_b] resolve_gate_momentum_buffer: nested=PASS flat=PASS mis-keyed(old-defect-shape)=None(correct)")

    # FAIL-CLOSED: build_real_d_comm_closures must raise (never zeros_like)
    # when pre_opt_state is a genuine (non-None) optimizer state that
    # resolves to nothing.
    grad_pre_gate = torch.randn(4, 4)
    grad_post_gate = torch.randn(4, 4)
    try:
        build_real_d_comm_closures(
            pre_model_state, mis_keyed_opt, None, None, GATE_KEY, UP_KEY, DOWN_KEY,
            pre_lr=0.02, post_lr=0.02, grad_pre_gate=grad_pre_gate, grad_post_gate=grad_post_gate)
        raise AssertionError("[test_b] FAIL: build_real_d_comm_closures did not raise on a mis-keyed/zero buffer")
    except EngagementFailure as e:
        print(f"[test_b] build_real_d_comm_closures correctly fail-closed: {e}")

    # Also cover the explicit all-zero fixture named in the spec ("zero-
    # buffer fixture -> hard abort") under the CORRECT nesting.
    zero_opt = {"muon": {"state": {0: {"momentum_buffer": torch.zeros(4, 4)}}}}
    try:
        build_real_d_comm_closures(
            pre_model_state, zero_opt, None, None, GATE_KEY, UP_KEY, DOWN_KEY,
            pre_lr=0.02, post_lr=0.02, grad_pre_gate=grad_pre_gate, grad_post_gate=grad_post_gate)
        raise AssertionError("[test_b] FAIL: build_real_d_comm_closures did not raise on an explicit zero buffer")
    except EngagementFailure as e:
        print(f"[test_b] zero-buffer fixture correctly fail-closed: {e}")

    print("[test_b] PASS")
    return True


def test_c_receipt_fields_present():
    """compute_d_comm_real_run()'s returned dict gains pre_buffer_rms_consumed
    and resolved_lr_muon (the resolved cfg's LR, never a script constant)."""
    import torch
    from p5_ratio_audit.run_p5_audit import compute_d_comm_real_run

    torch.manual_seed(0)
    pre_model_state = {
        GATE_KEY: torch.randn(4, 4), UP_KEY: torch.randn(4, 4), DOWN_KEY: torch.randn(4, 4),
    }
    post_model_state = {
        GATE_KEY: torch.randn(8, 4), UP_KEY: torch.randn(8, 4), DOWN_KEY: torch.randn(4, 8),
    }
    pre_opt_state = {"muon": {"state": {0: {"momentum_buffer": torch.randn(4, 4) * 0.05}}}}
    post_opt_state = {"muon": {"state": {0: {"momentum_buffer": torch.randn(8, 4) * 0.05}}}}
    grad_pre_gate = torch.randn(4, 4)
    grad_post_gate = torch.randn(8, 4)
    discovery = {"pre_grow_rung1": {"found": True}, "post_grow_rung1": {"found": True}}

    resolved_lr_muon = 0.02  # the real config value (configs/v0-pretrain-config.json), not 0.015
    result = compute_d_comm_real_run(
        discovery, grad_pre_gate, grad_post_gate,
        pre_model_state, pre_opt_state, post_model_state, post_opt_state,
        pre_ff=4, post_ff=8, pre_lr=resolved_lr_muon, post_lr=resolved_lr_muon, layer_index=0)

    assert "pre_buffer_rms_consumed" in result, "[test_c] FAIL: pre_buffer_rms_consumed missing from receipt"
    assert "resolved_lr_muon" in result, "[test_c] FAIL: resolved_lr_muon missing from receipt"
    assert result["resolved_lr_muon"] == resolved_lr_muon, "[test_c] FAIL: resolved_lr_muon not threaded from caller"
    assert result["pre_buffer_rms_consumed"] > 1e-10, "[test_c] FAIL: pre_buffer_rms_consumed reads as zero"
    print(f"[test_c] pre_buffer_rms_consumed={result['pre_buffer_rms_consumed']:.6e} "
          f"resolved_lr_muon={result['resolved_lr_muon']}")
    print("[test_c] PASS")
    return True


def test_d_resolved_lr_muon_matches_frozen_config():
    """The frozen config contract's lr_muon is 0.02, not 0.015 (P-3
    forensic's second kill condition) -- regression guard on the config
    file itself, independent of any code path."""
    import json
    cfg_path = os.path.join(REPO_ROOT, "configs", "v0-pretrain-config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    lr_muon = cfg["optimizer"]["lr_muon"]
    print(f"[test_d] configs/v0-pretrain-config.json optimizer.lr_muon={lr_muon}")
    assert lr_muon == 0.02, f"[test_d] FAIL: lr_muon={lr_muon}, expected 0.02"
    assert lr_muon != 0.015, "[test_d] FAIL: lr_muon reads as the never-executed script constant 0.015"
    print("[test_d] PASS")
    return True


if __name__ == "__main__":
    tests = [
        test_a_real_buffer_resolves_nonzero,
        test_b_mis_keyed_checkpoint_fails_closed,
        test_c_receipt_fields_present,
        test_d_resolved_lr_muon_matches_frozen_config,
    ]
    failures = []
    for t in tests:
        try:
            ok = t()
            if not ok:
                failures.append(t.__name__)
        except Exception as e:
            print(f"[{t.__name__}] ERROR: {e}")
            import traceback
            traceback.print_exc()
            failures.append(t.__name__)

    if failures:
        print(f"\nP5_513_RESOLVER_FIX_TEST_FAIL: {failures}")
        sys.exit(1)
    print("\nP5_513_RESOLVER_FIX_TEST_PASS")
    sys.exit(0)
