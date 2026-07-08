"""test_p1_envelope_sweep.py -- schedule-shape + receipt-schema tests for
scripts/p1_envelope_sweep.py (issue #118, this lane's frozen build spec).

Both tests are CPU-only and fast (no CUDA, no real corpus, no decontam
gate, no network) -- matching the repo's existing pytest convention
(scripts/test_w1_live_gates.py).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import p1_envelope_sweep as sweep  # noqa: E402
import w1_collapse_control_run as w1c  # noqa: E402


# ---------------------------------------------------------------------------
# Schedule-shape: budget -> step-count -> LR curve endpoints.
# ---------------------------------------------------------------------------

def test_steps_for_point_known_points():
    """Every prereg sweep point (3-8) resolves to a positive step count, and
    the multiplier ordering is monotonic (larger multiplier -> more steps) --
    the basic sanity floor of the budget->step-count mapping."""
    infos = {k: sweep.steps_for_point(k) for k in sorted(sweep.POINT_MULTIPLIERS)}
    steps_by_point = {k: v["steps"] for k, v in infos.items()}
    assert all(s >= 1 for s in steps_by_point.values())
    ordered_points = sorted(steps_by_point)
    ordered_steps = [steps_by_point[p] for p in ordered_points]
    assert ordered_steps == sorted(ordered_steps), (
        f"steps must be monotonically non-decreasing with multiplier: {steps_by_point}")


def test_steps_for_point_3_matches_frozen_spec_approx_24s():
    """The frozen build spec states point 3 (0.1xE0) is '~24s GPU'. This is
    the strongest available evidence the E0-to-token-budget derivation
    (module docstring item 2) is calibrated the way the spec author
    intended -- assert the derived TARGET wall-clock (before overhead) is
    within a wide but meaningful tolerance of 24s."""
    info = sweep.steps_for_point(3)
    assert info["target_gpu_hours"] * 3600.0 == pytest.approx(24.29, abs=1.0)


def test_steps_for_point_bad_point_refuses():
    with pytest.raises(SystemExit, match="P1_SWEEP_BAD_POINT"):
        sweep.steps_for_point(2)
    with pytest.raises(SystemExit, match="P1_SWEEP_BAD_POINT"):
        sweep.steps_for_point(9)


def test_intended_warmup_steps_capped_and_floored():
    # tiny budget: 2% floors to < 1, so max(1, ...) applies
    assert sweep.intended_warmup_steps(10) == 1
    # large budget: 2% would exceed the absolute cap, so the cap applies
    huge_budget = 100_000
    expected_cap = sweep.ABSOLUTE_WARMUP_STEPS_CAP
    assert sweep.intended_warmup_steps(huge_budget) == expected_cap
    # mid-size budget: plain 2% applies (neither floor nor cap binds)
    mid_budget = 5000
    assert sweep.intended_warmup_steps(mid_budget) == max(
        1, min(round(0.02 * mid_budget), expected_cap))


def test_lr_curve_endpoints_match_actually_applied_schedule():
    """The schedule ACTUALLY applied by run_phase2_live (reused, not
    reimplemented) is cosine_warmup_frac/apply_cosine_warmup at its
    hardcoded defaults (warmup_frac=0.1, min_lr_frac=0.1) -- verify the
    curve's endpoints match a standard cosine-with-warmup decay to 10% of
    peak.

    Point 3's own computed budget (~10 steps) collapses warmup_steps=
    max(1, int(budget*0.1)) to exactly 1 step, so step 0 already reaches
    the full multiplier ((0+1)/1==1.0) -- correct behavior of the reused
    function at this tiny scale, not a ramp. The "warmup actually ramps"
    assertion therefore uses a larger synthetic budget where warmup spans
    multiple steps; the "decays to min_lr_frac at the final step" assertion
    uses point 3's own real computed budget (what this lane's gate probe
    actually runs)."""
    large_budget = 200  # warmup_steps = int(200*0.1) = 20, several steps
    first_mult = w1c.cosine_warmup_frac(0, large_budget)
    ramp_mult = w1c.cosine_warmup_frac(5, large_budget)
    assert 0.0 < first_mult < ramp_mult < 1.0

    budget_steps = sweep.steps_for_point(3)["steps"]
    assert budget_steps >= 1
    last_mult = w1c.cosine_warmup_frac(budget_steps, budget_steps)
    # the final step of the schedule must sit at min_lr_frac (0.1 = "decay
    # to 10% of peak", prereg section 2's own frozen wording).
    assert last_mult == pytest.approx(0.1, abs=1e-9)

    # monotonic decay check on the back half: multiplier at the final step
    # must be <= the multiplier at the midpoint (cosine decay, never rises
    # after warmup ends).
    mid_mult = w1c.cosine_warmup_frac(budget_steps // 2, budget_steps)
    assert last_mult <= mid_mult


# ---------------------------------------------------------------------------
# Receipt-schema: dry-run path assembles every instrumentation field the
# frozen spec's "Instrumentation at birth" item requires, without touching
# CUDA/corpus/gate.
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL_KEYS = {
    "ticket", "ts", "issue", "schema", "prereg_ref", "point", "multiplier",
    "budget_derivation", "adm_fingerprint", "c_functional_id", "e_gpu_hours",
    "lever_class", "claim_type", "power",
}


def test_dry_run_receipt_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "REPO", str(tmp_path))
    args = sweep.build_arg_parser().parse_args(["--point", "3", "--dry-run"])
    point_info = sweep.steps_for_point(args.point)
    intended_warmup = sweep.intended_warmup_steps(point_info["steps"])
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    receipt = sweep.run_point_dry(args, point_info, "20260101T000000Z", out_dir, intended_warmup)

    missing = REQUIRED_TOP_LEVEL_KEYS - set(receipt)
    assert not missing, f"receipt missing required keys: {missing}"

    assert receipt["dry_run"] is True
    assert receipt["issue"] == "#118"
    assert receipt["schema"] == "p1-envelope-sweep-point/v1"
    assert receipt["c_functional_id"] == "neg_val_loss_v1"
    assert receipt["claim_type"] == "envelope-point"
    assert receipt["power"]["power_qualifier"] == "unqualified"
    assert receipt["point"] == 3
    assert receipt["multiplier"] == sweep.POINT_MULTIPLIERS[3]

    # the written file itself must be valid, BOM-free JSON (repo convention,
    # matches receipt_write.checked_write's own contract).
    out_path = receipt["_receipt_path"]
    with open(out_path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    with open(out_path, "r", encoding="utf-8") as f:
        reloaded = json.load(f)
    assert reloaded["point"] == 3


def test_dry_run_rejects_missing_authorization_is_not_required():
    """--dry-run must NOT require EMBER_GATE_AUTHORIZED=1 (it never touches
    CUDA); a live run WITHOUT --dry-run and without the env var must refuse."""
    dry_args = sweep.build_arg_parser().parse_args(["--point", "3", "--dry-run"])
    sweep.refuse_unless_authorized(dry_args)  # must not raise

    live_args = sweep.build_arg_parser().parse_args(["--point", "3"])
    os.environ.pop("EMBER_GATE_AUTHORIZED", None)
    with pytest.raises(SystemExit, match="P1_SWEEP_LIVE_REFUSED"):
        sweep.refuse_unless_authorized(live_args)
