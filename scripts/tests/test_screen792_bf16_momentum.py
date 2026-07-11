#!/usr/bin/env python3
"""test_screen792_bf16_momentum.py -- required negative fixture for ember
issue #792 (screen792_bf16_momentum.py).

#792 spec, quoted: "REQUIRED NEGATIVE FIXTURE: a small-increment EMA case
where increments fall below the bf16 ULP -- must PASS under the A1 fp32-
read-modify-writeback dataflow and FAIL (detectably stall) under the naive
in-place bf16 implementation. This fixture is the guard against the exact
defect AMENDMENT-1 cured; a screen without it is unmergeable."

DESIGN (team-lead review, shape (b) of the two amendment-authorized
shapes): momentum stays at the production value (0.95, not 1.0 -- a
momentum of exactly 1.0 would make the naive two-op sequence, buf.mul_(1.0)
[an exact no-op] then buf.add_(g), and A1's one-op fp32-combined sequence
mathematically IDENTICAL, collapsing the double-rounding-vs-single-rounding
distinction this fixture exists to catch; either implementation would show
the SAME behavior at mom=1.0, discriminating nothing -- flagged to the
team-lead alongside this file for correction if that derivation is wrong).
With mom=0.95, BOTH implementations exhibit real, large, CORRECT
multiplicative decay of the seed value -- the discriminating question is
NOT "did buf move" (both move) but "did the grad's contribution survive
that decay": the naive implementation's PER-OP rounding (bf16-round after
buf.mul_(mom), bf16-round AGAIN after buf.add_(g)) loses the grad term
across the decay-dominated phase of the trajectory; A1's SINGLE rounding
(fp32-combined mul+add, one round on write-back) does not.

This fixture therefore compares BOTH implementations against TWO
INDEPENDENT analytic references, computed in plain Python fp64 with zero
bf16/torch/memmap anywhere (ground-truth-source discipline: a check must
never derive its expectation from the object it is checking):
  pure_decay(N)      = seed * momentum**N                    (NO grad term)
  correct_with_grad(N) = the true recurrence buf = buf*mom + g, N times
The naive control should land close to pure_decay(N) -- the grad
contribution LOST. The A1-fixed implementation should land close to
correct_with_grad(N) -- the grad contribution RETAINED, i.e. A1 should
show the FULL analytic deviation from pure decay (correct_with_grad(N) -
pure_decay(N)) that the naive control fails to show.

UNVERIFIED PENDING EXECUTION: this file was authored and py_compile'd but
never RUN (HARD TIMING RAIL, issue #792 -- no execution before the
coordinator's window-release GO). The tolerance constants below are
generous, derived from bf16's known ~2**-8 relative precision compounded
over _N_SYNTHETIC_STEPS, not from a runtime measurement. If --selftest's
first real run shows these mis-calibrated, that is a same-day CONSTANT-
TUNING fix (the underlying mechanism -- compare both implementations
against two independent analytic references -- is not in question), not a
redesign; report the actual measured numbers back to the issue thread
either way.

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
                              # regime is fully exercised, not just the early
                              # pure-decay phase
_SHAPE = (4, 4)               # 2D -- Muon's split-routing invariant requires ndim==2
_LR = 0.0                     # zero param-update lr -- isolates the
                              # MOMENTUM-BUFFER persistence question from any
                              # confounding parameter-update drift; the
                              # fixture asks "did the buffer accumulate
                              # correctly", not "did the parameter move"
_MOM = 0.95                   # production momentum coefficient (contract
                              # default) -- MUST be <1 for any discrimination
                              # to exist between the two implementations; see
                              # module docstring DESIGN


def _pure_decay(seed: float, momentum: float, n_steps: int) -> float:
    """Analytic reference with NO grad term at all -- the naive control's
    expected landing point if the grad's contribution is fully lost to
    per-op bf16 rounding: buf_N = seed * momentum**n_steps."""
    return float(seed) * (float(momentum) ** n_steps)


def _fp64_reference_ema(seed: float, grad: float, momentum: float, n_steps: int) -> float:
    """Independent ground-truth recurrence -- plain Python floats (fp64),
    zero bf16/torch/memmap anywhere in this function. The A1-fixed
    implementation's expected landing point if the grad's contribution is
    fully retained: buf = buf*momentum + grad, applied n_steps times."""
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
    """The required negative fixture. Returns True iff ALL conditions hold
    against the two independent analytic references:
      (a) the naive in-place-bf16 control lands close to pure_decay(N) --
          the grad contribution LOST to per-op double rounding (FAIL case);
      (b) the A1-fixed implementation lands close to correct_with_grad(N)
          -- the grad contribution RETAINED via single fp32-combined
          rounding (PASS case);
      (c) A1's deviation from pure_decay(N) is close to the FULL analytic
          deviation (correct_with_grad(N) - pure_decay(N)) -- i.e. A1
          genuinely shows the accumulated-grad term, not a partial/
          attenuated fraction of it.
    A fixture that cannot produce all three does not discriminate the two
    implementations and is not evidence of anything -- this function IS the
    falsifiability check on the fixture itself, run every time via
    screen792_bf16_momentum.py's --selftest."""
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    MuonNaive = s792._muon_bf16_naive_inplace_class()

    pure_decay = _pure_decay(_WORKING_MAGNITUDE, _MOM, _N_SYNTHETIC_STEPS)
    correct_with_grad = _fp64_reference_ema(
        _WORKING_MAGNITUDE, _SUB_ULP_GRAD, _MOM, _N_SYNTHETIC_STEPS)
    full_grad_term = correct_with_grad - pure_decay

    buf_fixed = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    buf_naive = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)

    final_fixed = _run_n_steps(MuonFixed, buf_fixed, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    final_naive = _run_n_steps(MuonNaive, buf_naive, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)

    err_naive_vs_pure_decay = _relative_error(final_naive, pure_decay)
    err_fixed_vs_correct = _relative_error(final_fixed, correct_with_grad)
    fixed_grad_term = final_fixed - pure_decay
    grad_term_retained_frac = (
        (fixed_grad_term / full_grad_term) if full_grad_term != 0 else None)

    # Generous bounds (UNVERIFIED pending execution -- see module docstring):
    # bf16's per-element relative precision is ~2**-8 (~0.4%); compounded
    # over _N_SYNTHETIC_STEPS steps of a decaying recurrence, 10% is
    # deliberately loose to avoid a false FAIL on the correct mechanism.
    NAIVE_TOL = 0.10          # naive must land within 10% of pure decay
    A1_TOL = 0.10             # A1 must land within 10% of the true recurrence
    GRAD_RETAINED_FLOOR = 0.5  # A1 must retain AT LEAST half the analytic
                               # grad-term deviation from pure decay (a
                               # partial/attenuated retention still counts
                               # as evidence of the mechanism; well above
                               # what the naive control should show)

    naive_lost_grad = err_naive_vs_pure_decay < NAIVE_TOL
    fixed_tracks_correct = err_fixed_vs_correct < A1_TOL
    fixed_retained_grad = (grad_term_retained_frac is not None
                           and grad_term_retained_frac > GRAD_RETAINED_FLOOR)

    if verbose:
        print(f"screen792 negative fixture: pure_decay={pure_decay!r} "
              f"correct_with_grad={correct_with_grad!r} full_grad_term={full_grad_term!r}")
        print(f"  final_naive={final_naive!r} rel_err_vs_pure_decay={err_naive_vs_pure_decay!r} "
              f"(naive lost the grad term: {naive_lost_grad})")
        print(f"  final_fixed={final_fixed!r} rel_err_vs_correct={err_fixed_vs_correct!r} "
              f"grad_term_retained_frac={grad_term_retained_frac!r} "
              f"(A1 retained the grad term: {fixed_retained_grad})")

    return naive_lost_grad and fixed_tracks_correct and fixed_retained_grad


def test_naive_inplace_bf16_loses_grad_term():
    """Shape (b): the naive control (per-op double rounding) should land
    close to the NO-GRAD pure-decay analytic value -- the additive grad
    contribution lost across the decay-dominated trajectory."""
    pure_decay = _pure_decay(_WORKING_MAGNITUDE, _MOM, _N_SYNTHETIC_STEPS)
    MuonNaive = s792._muon_bf16_naive_inplace_class()
    buf = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    final = _run_n_steps(MuonNaive, buf, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    err = _relative_error(final, pure_decay)
    assert err < 0.10, (
        f"naive in-place-bf16 control should land close to the NO-GRAD "
        f"pure-decay value ({pure_decay!r}) -- the grad contribution lost "
        f"to per-op double rounding; got final={final!r} rel_err={err!r}")


def test_a1_dataflow_retains_grad_term():
    """Shape (b): the A1-fixed implementation (single fp32-combined
    rounding) should land close to the TRUE recurrence (grad retained), and
    should show substantially more deviation from pure decay than the
    naive control does -- i.e. it actually carries the accumulated-grad
    term the naive control loses."""
    pure_decay = _pure_decay(_WORKING_MAGNITUDE, _MOM, _N_SYNTHETIC_STEPS)
    correct_with_grad = _fp64_reference_ema(
        _WORKING_MAGNITUDE, _SUB_ULP_GRAD, _MOM, _N_SYNTHETIC_STEPS)
    full_grad_term = correct_with_grad - pure_decay
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    buf = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    final = _run_n_steps(MuonFixed, buf, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS)
    err = _relative_error(final, correct_with_grad)
    assert err < 0.10, (
        f"A1-fixed implementation should track the TRUE recurrence "
        f"({correct_with_grad!r}) within 10%; got final={final!r} rel_err={err!r}")
    retained_frac = (final - pure_decay) / full_grad_term if full_grad_term != 0 else None
    assert retained_frac is not None and retained_frac > 0.5, (
        f"A1-fixed implementation should retain more than half of the "
        f"analytic grad-term deviation from pure decay ({full_grad_term!r}); "
        f"got retained_frac={retained_frac!r} (final={final!r}, "
        f"pure_decay={pure_decay!r})")


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
               test_naive_inplace_bf16_loses_grad_term,
               test_a1_dataflow_retains_grad_term,
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
