#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

CALIBRATED 2026-07-11 (round-2 cure A, external falsifier finding A): the
original ad-hoc 10%-tolerance design (N=500) was PROVEN unsound --
N=500 fully decays the buffer to its fp32 steady state, where the
grad/buffer ratio is fixed at (1-momentum)=0.05, structurally always
above bf16's ~0.4% ULP, so the naive implementation can NEVER lose the
grad term entirely at that N (first-principles: the discriminating
window is the EARLY-DECAY TRANSIENT, not the converged steady state).
A naive "just pick a smaller N" fix was independently proven unsound
too: at N=8 the two implementations are BIT-IDENTICAL yet a bare
%-tolerance check reported PASS (false positive), and no small N was
auto-licensed without predeclared separation predicates.

Replacement methodology (predeclared BEFORE any calibration run, per
finding A points 1-5): three predicates checked against the SAME two
independent fp64 analytic references (_pure_decay, _fp64_reference_ema):
  p1 SEPARATION: |final_fixed - final_naive| >= 0.25 * full_grad_term
  p2 FIXED CLOSER TO TRUTH: err(naive, correct) >= 2.0 * err(fixed, correct)
  p3 NAIVE CLOSER TO NO-GRAD: err(fixed, pure_decay) >= 2.0 * err(naive, pure_decay)
swept across 3 frozen (seed, grad) configs spanning two ratio regimes
(1e-4 "typical", 1e-5 "deep sub-ULP stress") at two absolute scales each
-- satisfying "sweep >1 seed magnitude/grad scale" without claiming
ratio-universal generalization (see SCOPE below). N was selected by
scanning N=15..220 at fine (then finer, N=61..79) resolution for the
smallest N where ALL 3 configs pass ALL 3 predicates simultaneously,
then choosing the CENTER of the resulting robust 6-wide interior band
(N=72..77 all pass; N=61..71 and N>=78 flicker/fail) rather than a
boundary value -- N=75 frozen. Selection rule and full 3-config x
19-candidate scan are logged in the PR; nothing here was tuned after
peeking at a single favorable output.

SCOPE (disclosed, not silently narrow): calibration verified only at
the two frozen ratio regimes above, at power-of-two-friendly scales
(1.0, 0.5, 0.25, 2.0, 4.0). An extended holdout probe found the design
does NOT generalize to arbitrary seed values -- a third ratio (3e-4)
and non-power-of-two seeds (0.73, 0.61) broke the predicates at every
N in the robust band, most likely because bf16's rounding grid is not
perfectly scale/value invariant (the analytic references assume an
UNROUNDED float64 seed, while the real seed is bf16-rounded on
creation via _seed_bf16_momentum -- exact for power-of-two magnitudes,
lossy otherwise). This fixture makes NO claim beyond its own frozen
_SWEEP_CONFIGS; it is not a general-purpose bf16-EMA discriminator.

Pure CPU, no model/GPU/live dispatch.

No git commits from this module. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false (CPU-only test module; no paid API surface).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import screen792_bf16_momentum as s792  # noqa: E402
except SystemExit as exc:
    if "historical_only" in str(exc):
        pytest.skip(
            "screen792 imports execution-denied historical_only trainer",
            allow_module_level=True,
        )
    raise

# Working magnitude the momentum buffer sits at once warmed up. bfloat16 has
# an 8-bit mantissa (7 explicit + 1 implicit) -- at magnitude ~1.0 its ULP is
# 2**-7 == 0.0078125, so a per-step additive increment of 1e-4 is well below
# half that ULP (~0.0039) at the seed magnitude -- the exact regime
# AMENDMENT-1 finding 2 identified as silently lost when accumulated
# in-place on a bf16 destination tensor.
_WORKING_MAGNITUDE = 1.0
_SUB_ULP_GRAD = 1e-4
_N_SYNTHETIC_STEPS = 75        # frozen calibration -- band-center of the
                              # robust N=72..77 interior found by the
                              # predeclared 3-config x 19-candidate scan;
                              # see CALIBRATED note in the module docstring
_SEPARATION_FRAC = 0.25       # predicate 1: separation floor as a fraction
                              # of the analytic full grad-term deviation
_CLOSER_MARGIN = 2.0          # predicates 2/3: "closer to X than Y" margin
_SWEEP_CONFIGS = (            # (label, seed, grad) -- two ratio regimes,
                              # two absolute scales each; see SCOPE note
    ("baseline", _WORKING_MAGNITUDE, _SUB_ULP_GRAD),
    ("half_scale_same_ratio", 0.5, 5e-5),
    ("deeper_sub_ulp", 1.0, 1e-5),
)
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
    """First-execution finding (#792 cure round, unrelated to the
    falsifier's three findings): the installed torch build enforces
    grad_dtype == tensor dtype by default -- a bf16-dtype `p` cannot accept
    a float32 `.grad` assignment directly (RuntimeError). `p`'s OWN dtype
    is not under test here (only opt.state[p]['momentum_buffer']'s dtype
    is, and _LR=0.0 makes any p.add_() update in Muon.step() a numeric
    no-op regardless of p's dtype -- see module docstring), so p is created
    fp32 to match its grad, matching what production actually varies
    (momentum-buffer storage dtype), never the parameter's own dtype."""
    import torch
    p = torch.nn.Parameter(torch.zeros(_SHAPE, dtype=torch.float32))
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


def _run_n_steps(muon_cls, momentum_buffer, grad_fill: float, n_steps: int,
                  *, momentum: float = _MOM) -> float:
    """Drives muon_cls.step() n_steps times against a single 2D param whose
    grad is held at a constant SUB-ULP fill value every step (the
    small-increment EMA case the fixture spec names), with the SAME
    momentum_buffer object pre-seeded into state before the first step
    (mirroring how CPUOffloadOptimizer pre-seeds state before any step()
    call in production). `momentum` defaults to the production constant
    _MOM but is overridable for the mom=1.0 empirical settle below. Returns
    one scalar reading of the final momentum buffer (all entries are
    identical by construction -- uniform grad, uniform seed -- so [0, 0] is
    representative)."""
    import torch
    p = _make_param_and_grad(grad_fill)
    opt = muon_cls([p], lr=_LR, momentum=momentum, nesterov=True, ns_steps=5, weight_decay=0.0)
    opt.state[p] = {"momentum_buffer": momentum_buffer}
    for _ in range(n_steps):
        p.grad = torch.full(_SHAPE, grad_fill, dtype=torch.float32)
        opt.step()
    final = opt.state[p]["momentum_buffer"].detach().to(torch.float32)
    return float(final[0, 0])


def _check_predicates(seed: float, grad: float, n_steps: int,
                       final_naive: float, final_fixed: float) -> dict:
    """The three predeclared separation predicates (round-2 cure A, finding
    A points 1-3), checked against the two independent fp64 analytic
    references. Ground-truth-source discipline: this function derives its
    expectation from _pure_decay/_fp64_reference_ema (plain Python floats,
    zero bf16/torch/memmap), never from either implementation under test."""
    pd = _pure_decay(seed, _MOM, n_steps)
    cwg = _fp64_reference_ema(seed, grad, _MOM, n_steps)
    full_grad_term = cwg - pd
    err_naive_vs_correct = abs(final_naive - cwg)
    err_fixed_vs_correct = abs(final_fixed - cwg)
    err_naive_vs_pure = abs(final_naive - pd)
    err_fixed_vs_pure = abs(final_fixed - pd)
    p1_separation = abs(final_fixed - final_naive) >= _SEPARATION_FRAC * abs(full_grad_term)
    p2_fixed_closer_to_truth = err_naive_vs_correct >= _CLOSER_MARGIN * max(err_fixed_vs_correct, 1e-300)
    p3_naive_closer_to_no_grad = err_fixed_vs_pure >= _CLOSER_MARGIN * max(err_naive_vs_pure, 1e-300)
    return dict(
        pure_decay=pd, correct_with_grad=cwg, full_grad_term=full_grad_term,
        final_naive=final_naive, final_fixed=final_fixed,
        p1_separation=p1_separation,
        p2_fixed_closer_to_truth=p2_fixed_closer_to_truth,
        p3_naive_closer_to_no_grad=p3_naive_closer_to_no_grad,
        all_pass=bool(p1_separation and p2_fixed_closer_to_truth and p3_naive_closer_to_no_grad),
    )


def run_negative_fixture(*, verbose: bool = True) -> bool:
    """The required negative fixture. Returns True iff ALL three predicates
    (separation, fixed-closer-to-truth, naive-closer-to-no-grad -- see
    _check_predicates) hold for EVERY config in _SWEEP_CONFIGS at the
    frozen _N_SYNTHETIC_STEPS. A fixture that cannot produce this for even
    one swept config does not discriminate the two implementations and is
    not evidence of anything -- this function IS the falsifiability check
    on the fixture itself, run every time via screen792_bf16_momentum.py's
    --selftest."""
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    MuonNaive = s792._muon_bf16_naive_inplace_class()

    all_pass = True
    for label, seed, grad in _SWEEP_CONFIGS:
        buf_fixed = _seed_bf16_momentum(_SHAPE, seed)
        buf_naive = _seed_bf16_momentum(_SHAPE, seed)
        final_fixed = _run_n_steps(MuonFixed, buf_fixed, grad, _N_SYNTHETIC_STEPS)
        final_naive = _run_n_steps(MuonNaive, buf_naive, grad, _N_SYNTHETIC_STEPS)
        r = _check_predicates(seed, grad, _N_SYNTHETIC_STEPS, final_naive, final_fixed)
        all_pass = all_pass and r["all_pass"]
        if verbose:
            print(f"screen792 negative fixture [{label}] seed={seed} grad={grad} "
                  f"n_steps={_N_SYNTHETIC_STEPS}: p1_separation={r['p1_separation']} "
                  f"p2_fixed_closer_to_truth={r['p2_fixed_closer_to_truth']} "
                  f"p3_naive_closer_to_no_grad={r['p3_naive_closer_to_no_grad']} "
                  f"all_pass={r['all_pass']} final_naive={r['final_naive']!r} "
                  f"final_fixed={r['final_fixed']!r} correct_with_grad={r['correct_with_grad']!r} "
                  f"pure_decay={r['pure_decay']!r}")

    return all_pass


def test_bf16_view_memmap_roundtrip():
    import tempfile
    import torch
    # ignore_cleanup_errors=True: see screen792_bf16_momentum.py _selftest's
    # step-1 comment -- np.memmap keeps its backing file mapped on Windows,
    # so a TemporaryDirectory holding an open memmap cannot rmtree itself at
    # __exit__ until the OS releases the handle.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
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


def settle_mom_one_empirically(*, verbose: bool = True) -> dict:
    """Empirical settle (team-lead-approved, GO condition) for the shape-(a)
    disagreement in the module docstring: at mom=1.0, buf.mul_(1.0) is an
    exact no-op, so my derivation says naive collapses to A1's single
    add_() -- identical output, zero discrimination. Diagnostic only; does
    NOT gate the required fixture above (that lives at mom=0.95)."""
    MuonFixed = s792._muon_bf16_momentum_fixed_class()
    MuonNaive = s792._muon_bf16_naive_inplace_class()
    buf_fixed = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    buf_naive = _seed_bf16_momentum(_SHAPE, _WORKING_MAGNITUDE)
    final_fixed = _run_n_steps(MuonFixed, buf_fixed, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS, momentum=1.0)
    final_naive = _run_n_steps(MuonNaive, buf_naive, _SUB_ULP_GRAD, _N_SYNTHETIC_STEPS, momentum=1.0)
    diff = abs(final_fixed - final_naive)
    result = {"final_fixed": final_fixed, "final_naive": final_naive,
              "abs_diff": diff, "identical_within_1ulp": diff < 2.0 ** -6}
    if verbose:
        print(f"MOM1_SETTLE: final_fixed={final_fixed!r} final_naive={final_naive!r} "
              f"abs_diff={diff!r} identical_within_1ulp={result['identical_within_1ulp']}")
    return result


def test_required_negative_fixture_discriminates():
    assert run_negative_fixture(verbose=False), (
        "required negative fixture failed to discriminate the A1-correct "
        "implementation from the naive in-place-bf16 control -- per #792, "
        "'a screen without it is unmergeable'")


def test_live_main_creates_nested_receipt_directory_before_write():
    """A completed live screen must not lose its verdict at final write."""
    with tempfile.TemporaryDirectory() as d:
        receipt_dir = Path(d) / "nested" / "receipts"
        observed = {}

        def _checked_write(path, receipt):
            observed["parent_exists"] = Path(path).parent.is_dir()
            observed["path"] = Path(path)

        def _run_screen(**kwargs):
            observed["precompute_parent_exists"] = receipt_dir.is_dir()
            return fake_receipt

        fake_receipt = {
            "ts": "2026-07-14T22:30:00Z",
            "verdict": "PROMOTE",
            "verdict_reason": "fixture-only",
        }
        argv = [
            "--live",
            "--shard-dir", str(Path(d) / "shards"),
            "--out-dir", str(Path(d) / "run"),
            "--receipt-dir", str(receipt_dir),
            "--device", "cpu",
        ]
        with mock.patch.dict(os.environ, {"EMBER_GATE_AUTHORIZED": "1"}), \
             mock.patch.object(s792, "_schema_probe", return_value=0), \
             mock.patch.object(s792.ts, "load_contract", return_value={}), \
             mock.patch.object(s792, "run_screen", side_effect=_run_screen), \
             mock.patch.object(s792.receipt_write, "checked_write", side_effect=_checked_write):
            rc = s792.main(argv)

        assert rc == 0
        assert observed.get("parent_exists") is True, (
            "main must create --receipt-dir before a completed live run "
            "reaches receipt_write.checked_write")
        assert observed.get("precompute_parent_exists") is True, (
            "main must validate/create --receipt-dir before spending GPU "
            "compute")
        assert observed["path"].parent == receipt_dir


def _selftest() -> int:
    ok = True
    for fn in (test_bf16_view_memmap_roundtrip,
               test_required_negative_fixture_discriminates):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            ok = False
    # Diagnostic only -- settles the shape-(a) mom=1.0 disagreement flagged
    # in the module docstring; never gates selftest pass/fail.
    settle_mom_one_empirically(verbose=True)
    if ok:
        print("TEST_SCREEN792_BF16_MOMENTUM_SELFTEST_PASS")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_selftest())
