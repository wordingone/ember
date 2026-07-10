"""test_governor.py -- unit tests for the C-PORT gap closures in
scripts/governor.py (issue #21): the fp8 gate, bf16 fallback ladder, and
device-relative throughput threshold.

CPU-only, fast, matches the repo's existing pytest convention
(scripts/test_p1_envelope_sweep.py: sys.path insert + plain `import governor`).
fp8_matmul_with_fallback needs torch (CPU tensors only here -- no CUDA
required); the other three surfaces (device_capability, select_precision,
device_relative_threshold) are pure Python and are additionally covered by
governor.py's own `--selftest` (Windows-safe, no torch).
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import governor  # noqa: E402

torch = pytest.importorskip("torch")


# ---------------------------------------------------------------------------
# device_capability -- simulated vs real, never claims an unqueried GPU.
# ---------------------------------------------------------------------------

def test_device_capability_simulated_profile_parses_name_and_sm():
    cap = governor.device_capability(simulate="3090:86")
    assert cap == {"name": "3090", "sm": 86, "kind": "simulated"}


def test_device_capability_simulated_cpu_has_no_sm():
    cap = governor.device_capability(simulate="cpu")
    assert cap == {"name": "cpu", "sm": None, "kind": "simulated-cpu"}


def test_device_capability_env_override(monkeypatch):
    monkeypatch.setenv("EMBER_SIMULATE_DEVICE", "t4:75")
    cap = governor.device_capability()
    assert cap == {"name": "t4", "sm": 75, "kind": "simulated"}


def test_device_capability_real_reports_cpu_when_cuda_unavailable(monkeypatch):
    monkeypatch.delenv("EMBER_SIMULATE_DEVICE", raising=False)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    cap = governor.device_capability()
    assert cap == {"name": "cpu", "sm": None, "kind": "real-cpu"}


# ---------------------------------------------------------------------------
# select_precision -- the fp8/bf16 gate itself (sm>=89 boundary).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sm,expected", [
    (89, "fp8"),      # RTX 4090 (Ada), the FP8_MIN_SM floor itself
    (90, "fp8"),      # Hopper+ also clears the gate
    (88, "bf16"),     # one below the floor -- must NOT get fp8
    (86, "bf16"),     # Ampere (3090-class) -- does NOT count as fp8-capable
    (75, "bf16"),     # Turing (T4-class)
    (None, "bf16"),   # CPU / unrecognised -- no sm at all
])
def test_select_precision_fp8_gate_boundary(sm, expected):
    assert governor.select_precision({"name": "x", "sm": sm}) == expected


def test_fp8_min_sm_is_89_tighten_only_guard():
    """Regression guard: FP8_MIN_SM must never be lowered (loosened) below
    89 -- that would let a sub-Ada device silently claim the fp8 path."""
    assert governor.FP8_MIN_SM == 89


# ---------------------------------------------------------------------------
# fp8_matmul_with_fallback -- the numerics ladder resolves, never a bare
# fp8 RuntimeError (the C-PORT invalid-token `fp8_runtimeerror_no_fallback`).
# ---------------------------------------------------------------------------

def test_fp8_matmul_with_fallback_uses_bf16_on_sub_89_device():
    cap = {"name": "3090", "sm": 86, "kind": "simulated"}
    a = torch.randn(4, 4)
    b = torch.randn(4, 4)
    out, precision = governor.fp8_matmul_with_fallback(a, b, capability=cap)
    assert precision == "bf16"
    assert out.shape == (4, 4)
    assert torch.isfinite(out).all()


def test_fp8_matmul_with_fallback_no_bare_runtimeerror_when_fp8_unreachable():
    """Simulate an sm>=89 capability (fp8-gate-eligible) on CPU tensors.
    The ladder must never crash regardless of whether this particular torch
    build happens to support an fp8 CPU reference kernel -- it either
    genuinely computes fp8 or falls back to bf16, never raises."""
    cap = {"name": "4090", "sm": 89, "kind": "simulated"}
    a = torch.randn(4, 4)
    b = torch.randn(4, 4)
    out, precision = governor.fp8_matmul_with_fallback(a, b, capability=cap)
    assert precision in ("fp8", "bf16")  # whichever the local torch build can do
    assert out.shape == (4, 4)
    assert torch.isfinite(out).all()


def test_fp8_matmul_with_fallback_catches_runtime_error_and_falls_back(monkeypatch):
    """Force the fp8 attempt itself to raise RuntimeError (as it would on
    real Ampere/Turing hardware, or a torch build with no fp8 GEMM kernel)
    and assert the ladder catches it and computes bf16 instead. This proves
    the CATCH path specifically -- not just that fp8 happens to succeed on
    whichever torch build runs this test -- closing the C-PORT invalid-token
    `fp8_runtimeerror_no_fallback` (an fp8 RuntimeError with no bf16 path)."""
    cap = {"name": "4090", "sm": 89, "kind": "simulated"}
    a = torch.randn(4, 4)
    b = torch.randn(4, 4)
    real_matmul = torch.matmul

    def _matmul_raising_on_fp8(x, y):
        if x.dtype == torch.float8_e4m3fn:
            raise RuntimeError("simulated: no fp8 GEMM kernel on this device")
        return real_matmul(x, y)

    monkeypatch.setattr(torch, "matmul", _matmul_raising_on_fp8)
    out, precision = governor.fp8_matmul_with_fallback(a, b, capability=cap)
    assert precision == "bf16"
    assert out.shape == (4, 4)
    assert torch.isfinite(out).all()


def test_fp8_matmul_with_fallback_defaults_to_device_capability(monkeypatch):
    """No capability passed -> falls back to governor.device_capability();
    on a simulated non-4090 env override, that still resolves to bf16."""
    monkeypatch.setenv("EMBER_SIMULATE_DEVICE", "3090:86")
    a = torch.randn(2, 2)
    b = torch.randn(2, 2)
    out, precision = governor.fp8_matmul_with_fallback(a, b)
    assert precision == "bf16"
    assert out.shape == (2, 2)


# ---------------------------------------------------------------------------
# device_relative_threshold -- roofline-derived FRACTION, never an absolute
# tok/s gate (the C-PORT invalid-token `absolute_tps_gate_on_other_device`).
# ---------------------------------------------------------------------------

def test_device_relative_threshold_basis_names_device_relative_roofline():
    cap = {"name": "3090", "sm": 86, "kind": "simulated"}
    thr = governor.device_relative_threshold(cap)
    assert "device-relative" in thr["basis"]
    assert "roofline" in thr["basis"]


def test_device_relative_threshold_reference_device_is_unity():
    cap = {"name": "4090", "sm": 89, "kind": "simulated"}
    thr = governor.device_relative_threshold(cap, reference_device="4090")
    assert thr["relative_flops_fraction"] == 1.0


def test_device_relative_threshold_non_reference_device_is_a_fraction():
    cap = {"name": "3090", "sm": 86, "kind": "simulated"}
    thr = governor.device_relative_threshold(cap, reference_device="4090")
    assert 0.0 < thr["relative_flops_fraction"] < 1.0


def test_device_relative_threshold_unrecognised_name_falls_back_to_cpu_tier():
    cap = {"name": "some-future-accelerator", "sm": None, "kind": "simulated"}
    thr = governor.device_relative_threshold(cap)
    assert thr["device_tier"] == "cpu"


@pytest.mark.parametrize("literal", ["19000", "25463", "27702"])
def test_device_relative_threshold_never_emits_absolute_tps_literals(literal):
    """These three constants are the C-PORT probe's explicit ABSOLUTE_TPS_GATES
    -- a device-relative basis must never surface them as if they were a
    cross-device pass/fail gate."""
    for name in ("4090", "3090", "t4", "5090", "cpu", "amd", "rtx-spark"):
        thr = governor.device_relative_threshold({"name": name, "sm": None})
        assert literal not in str(thr)
