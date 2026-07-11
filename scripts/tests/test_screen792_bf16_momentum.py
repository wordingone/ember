#!/usr/bin/env python3
"""test_screen792_bf16_momentum.py -- required negative fixture for ember
issue #792 (screen792_bf16_momentum.py).

#792 spec, quoted: "REQUIRED NEGATIVE FIXTURE: a small-increment EMA case
where increments fall below the bf16 ULP -- must PASS under the A1 fp32-
read-modify-writeback dataflow and FAIL (detectably stall) under the naive
in-place bf16 implementation. This fixture is the guard against the exact
defect AMENDMENT-1 cured; a screen without it is unmergeable."

DESIGN NOTE (why this is a REFERENCE-COMPARISON fixture, not a "stall at
exactly the seed value" fixture): a momentum coefficient of exactly 1.0
would make the naive two-op sequence (buf.mul_(mom); buf.add_(g)) and the
A1 one-op fp32-combined sequence mathematically IDENTICAL (mul_ by exactly
1.0 introduces no rounding, collapsing the "double rounding vs single
rounding" distinction this fixture exists to catch) -- so momentum must be
<1 (the production value, 0.95) for any real discrimination to exist. But
with momentum <1, BOTH implementations exhibit real, large, CORRECT
multiplicative decay of the seed value (buf ~ seed * momentum**n) -- the
naive implementation does NOT freeze at the seed value; a "drift == 0"
assertion against the raw seed would be the wrong test and would not
actually verify anything about AMENDMENT-1's defect. The defect AMENDMENT-1
names is specifically the compounded DOUBLE ROUNDING (bf16-round after
mul_, then bf16-round again after add_) versus A1's SINGLE ROUNDING
(fp32-combined mul+add, one round on write-back) -- a well-established
numerical-analysis result (double rounding of a computation split into two
ops is never more accurate, and is generically less accurate over an
accumulated recurrence, than single rounding of the combined op). This
fixture therefore checks BOTH implementations against an INDEPENDENT fp64
ground-truth recurrence that uses NEITHER implementation's code
(ground-truth-source discipline: a check must never derive its expectation
from the object it is checking) -- A1 must track that reference closely;
the naive control must track it measurably worse.

UNVERIFIED PENDING EXECUTION: this file was authored and py_compile'd but
never RUN (HARD TIMING RAIL, issue #792 -- no execution before the
coordinator's window-release GO). The exact tolerance constants below
(_A1_REL_TOL, the relative-divergence assertion) are derived from
numerical-analysis first principles (single-rounding provably bounds error
at least as tightly as double-rounding for this class of recurrence), NOT
from a runtime measurement. If --selftest's first real run shows these
thresholds mis-calibrated, that is a same-day CONSTANT-TUNING fix (the
underlying mechanism -- compare both implementations against an
independent fp64 reference -- is not in question), not a redesign; flag
the actual measured numbers back to the issue thread either way.

Pure CPU, no model/GPU/live dispatch.

No git commits from this module. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false (CPU-only test module; no paid API surface).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import screen792_bf16_momentum as s792  # noqa: E402

# Working magnitude the momentum buffer sits at once warmed up. bfloat16 has
# an 8-bit mantissa (7 explicit + 1 implicit) -- at magnitude ~1.0 its ULP is
# 2**-7 == 0.0078125, so a per-step additive increment of 1e-4 is well below
# half that ULP (~0.0039) at the seed magnitude -- the exact regime
# AMENDMENT-1 finding 2 identified as silently lost when accumulated
# in-place on a bf16 destination tensor.
_WORKING_MAGNITUDE = 1.0
_SUB_ULP_GRAD = 1e-4
_N_SYNTHETIC_STEPS = 500       # long enough for the decay (0.95**500 ~ 1e-11)
                              # to fully resolve toward the fp32 steady state
                              # g/(1-mom)=0.002, so the additive-accumulation
                              # regime (where A1 vs naive actually diverge --
                              # see module docstring) is fully exercised, not
                              # just the early pure-decay phase
_SHAPE = (4, 4)               # 2D -- Muon's split-routing invariant requires ndim==2
_LR = 0.0                     # zero param-update lr -- isolates the
                              # MOMENTUM-BUFFER persistence question from any
                              # confounding parameter-update drift; the
                              # fixture asks "did the buffer accumulate
                              # correctly", not "did the parameter move"
_MOM = 0.95                   # production momentum coefficient (contract
                              # default) -- MUST be <1 for any discrimination
                              # to exist between the two implementations; see
                              # module docstring DESIGN NOTE


def _fp64_reference_ema(seed: float, grad: float, momentum: float, n_steps: int) -> float:
    """Independent ground-truth recurrence -- plain Python floats (fp64),
    zero bf16/torch/memmap anywhere in this function. Neither implementation
    under test can trivially satisfy this by construction (ground-truth-
    source discipline: the check must not derive its expectation from the
    object under test)."""
    buf = float(seed)
    g = float(grad)
    for _ in range(n_steps):
        buf = buf * momentum + g
    return buf


def _make_param_and_grad(fill_value: float):
    import torch
    p = torch.nn.Parameter(torch.zeros(_SHAPE, dtype=torch.bfloat16))
    p.grad = torch.full(_SHAPE, fill_value, dtype=torch.float32)
    return p


def _seed_bf16_momentum(shape, magnitude: float):
    """A bf16-dtype momentum_buffer, file-backed via the SAME bf16_view_
    memmap helper the live runner uses (not a plain torch.full(...,
    dtype=bfloat16) in-process tensor) -- so the fixture exercises the exact
    storage path (memmap + .view(bfloat16) bitcast) the screen depends on,
    not just the arithmetic in isolation."""
    import tempfile
    import torch
    d = tempfile.mkdtemp(prefix="screen792_fixture_")
    t = s792.bf16_view_memmap(Path(d) / "fixture.momentum.bf16proxy.i16", shape)
    t.copy_(torch.full(shape, magnitude, dtype=torch.bfloat16))
    return t


def _run_n_steps(muon_cls, momentum_buffer, grad_fill: float, n_steps: int) -> float:
    """Drives muon_cls.step() n_steps times against a single 2D param whose
    grad is held at a constant SUB-ULP fill value every step (the
    small-increment EMA case the fixture spec names), with the SAME
    momentum_buffer object pre-seeded into state before the first step
    (mirroring how CPUOffloadOptimizer pre-seeds state before any step()
    call in production). Returns one scalar reading of the final momentum
    buffer (all entries are identical by construction -- uniform grad,
    uniform seed -- so [0, 0] is representative)."""
    import torch
    p = _make_param_and_grad(grad_fill)
    opt = muon_cls([p], lr=_LR, momentum=_MOM, nesterov=True, ns_steps=5, weight_decay=0.0)
    opt.state[p] = {"momentum_buffer": momentum_buffer}
    for _ in range(n_steps):
        p.grad = torch.full(_SHAPE, grad_fill, dtype=torch.float32)
        opt.step()
    final = opt.state[p]["momentum_buffer"].detach().to(torch.float32)
    return float(final[0, 0])


def _relative_error(measured: float, reference: float) -> float:
    if reference == 0.0:
        return abs(measured)
    return abs(measured - reference) / abs(reference)


def run_negative_fixture(*, verbose: bool = True) -> bool:
    """The required negative fixture. Returns True iff BOTH conditions hold
    against the independent fp64 reference recurrence:
      (a) the A1-correct implementation (_MuonBF16MomentumFixed) tracks the
          reference within _A1_REL_TOL (PASS case -- single rounding on
          write-back stays close to the true accumulated EMA), and
      (b) the naive in-place-bf16 control (_MuonBF16NaiveInPlace) diverges
          from the reference by MORE than A1 does (FAIL case -- double
          rounding, per-op, compounds error the combined fp32 computation
          avoids).
    A fixture that cannot produce both outcomes does not discriminate the
    two implementations and is not evidence of anything -- this function IS
    the falsifiability check on the fixture itself, run every time via
    screen792_bf16_momentum.py's --selftest."""
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    MuonNaive = s792._muon_bf16_naive_inplace_class()

    reference = _fp64_reference_ema(_WORKING_MAGNITUDE, _SUB_ULP_GRAD, _MOM, _N_SYNTHETIC_STEPS)

    buf_fixed = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    buf_naive = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)

    final_fixed = _run_n_steps(MuonFixed, buf_fixed, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    final_naive = _run_n_steps(MuonNaive, buf_naive, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)

    err_fixed = _relative_error(final_fixed, reference)
    err_naive = _relative_error(final_naive, reference)

    # Generous bound: bf16's per-element relative precision is ~2**-8
    # (~0.4%); a single rounding on write-back every step, compounded over
    # _N_SYNTHETIC_STEPS steps of a decaying recurrence, should stay within
    # low-single-digit-percent of the fp64 reference. 10% is deliberately
    # loose (this constant is UNVERIFIED pending execution -- see module
    # docstring) to avoid a false FAIL on the correct implementation.
    A1_REL_TOL = 0.10

    fixed_passed = err_fixed < A1_REL_TOL
    naive_worse = err_naive > err_fixed

    if verbose:
        print(f"screen792 negative fixture: reference={reference!r} "
              f"final_fixed={final_fixed!r} (rel_err={err_fixed!r}) "
              f"final_naive={final_naive!r} (rel_err={err_naive!r})")
        print(f"  A1-correct tracks reference within {A1_REL_TOL}: {fixed_passed}")
        print(f"  naive-in-place diverges MORE than A1 from reference: {naive_worse}")

    return fixed_passed and naive_worse


def test_a1_dataflow_tracks_fp64_reference():
    reference = _fp64_reference_ema(_WORKING_MAGNITUDE, _SUB_ULP_GRAD, _MOM, _N_SYNTHETIC_STEPS)
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    buf = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    final = _run_n_steps(MuonFixed, buf, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    err = _relative_error(final, reference)
    assert err < 0.10, (
        f"A1-correct implementation should track the fp64 reference EMA "
        f"({reference!r}) within 10% over {_N_SYNTHETIC_STEPS} sub-ULP-"
        f"increment steps; got final={final!r} rel_err={err!r}")


def test_naive_inplace_bf16_diverges_more_than_a1():
    reference = _fp64_reference_ema(_WORKING_MAGNITUDE, _SUB_ULP_GRAD, _MOM, _N_SYNTHETIC_STEPS)
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    MuonNaive = s792._muon_bf16_naive_inplace_class()
    buf_fixed = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    buf_naive = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    final_fixed = _run_n_steps(MuonFixed, buf_fixed, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    final_naive = _run_n_steps(MuonNaive, buf_naive, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    err_fixed = _relative_error(final_fixed, reference)
    err_naive = _relative_error(final_naive, reference)
    assert err_naive > err_fixed, (
        f"naive in-place-bf16 control (double rounding: bf16-round after "
        f"mul_, bf16-round again after add_) should diverge from the fp64 "
        f"reference MORE than the A1-fixed implementation (single rounding, "
        f"fp32-combined) does -- got err_fixed={err_fixed!r} "
        f"err_naive={err_naive!r}; if this fails, re-derive the fixture's "
        f"parameters (see module docstring DESIGN NOTE) rather than "
        f"loosening this assertion")


def test_bf16_view_memmap_roundtrip():
    import tempfile
    import torch
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "roundtrip.bf16proxy.i16"
        t = s792.bf16_view_memmap(p, (2, 2))
        assert t.dtype == torch.bfloat16
        assert torch.equal(t, torch.zeros(2, 2, dtype=torch.bfloat16))
        t.copy_(torch.full((2, 2), 3.25, dtype=torch.bfloat16))
        import numpy as np
        reopened = torch.from_numpy(
            np.memmap(str(p), dtype=np.int16, mode="r", shape=(2, 2))
        ).view(torch.bfloat16)
        assert torch.equal(reopened, torch.full((2, 2), 3.25, dtype=torch.bfloat16)), (
            "bf16 write did not persist to the file-backed memmap")


def test_required_negative_fixture_discriminates():
    assert run_negative_fixture(verbose=False), (
        "required negative fixture failed to discriminate the A1-correct "
        "implementation from the naive in-place-bf16 control -- per #792, "
        "'a screen without it is unmergeable'")


def _selftest() -> int:
    ok = True
    for fn in (test_bf16_view_memmap_roundtrip,
               test_a1_dataflow_tracks_fp64_reference,
               test_naive_inplace_bf16_diverges_more_than_a1,
               test_required_negative_fixture_discriminates):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            ok = False
    if ok:
        print("TEST_SCREEN792_BF16_MOMENTUM_SELFTEST_PASS")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_selftest())
