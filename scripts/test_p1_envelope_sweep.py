# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_p1_envelope_sweep.py -- schedule-shape + receipt-schema tests for
src/ember/governance/scripts/p1_envelope_sweep.py (issue #118, this lane's frozen build spec).

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

# issue2015 exact-local-import:src/ember/governance/scripts/p1_envelope_sweep.py
import importlib.util as _ember_28f42e29e3fb41af_importlib
import sys as _ember_28f42e29e3fb41af_sys
from pathlib import Path as _ember_28f42e29e3fb41af_Path
_ember_28f42e29e3fb41af_path = _ember_28f42e29e3fb41af_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'p1_envelope_sweep.py')
if not _ember_28f42e29e3fb41af_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/p1_envelope_sweep.py')
_ember_28f42e29e3fb41af_aliases = ('_ember_issue2015_28f42e29e3fb41af', 'p1_envelope_sweep', 'scripts.p1_envelope_sweep')
_ember_28f42e29e3fb41af_existing = []
for _ember_28f42e29e3fb41af_alias in _ember_28f42e29e3fb41af_aliases:
    _ember_28f42e29e3fb41af_candidate = _ember_28f42e29e3fb41af_sys.modules.get(_ember_28f42e29e3fb41af_alias)
    if _ember_28f42e29e3fb41af_candidate is not None and all(_ember_28f42e29e3fb41af_candidate is not item for item in _ember_28f42e29e3fb41af_existing):
        _ember_28f42e29e3fb41af_existing.append(_ember_28f42e29e3fb41af_candidate)
if len(_ember_28f42e29e3fb41af_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/p1_envelope_sweep.py')
if _ember_28f42e29e3fb41af_existing:
    _ember_28f42e29e3fb41af_module = _ember_28f42e29e3fb41af_existing[0]
    _ember_28f42e29e3fb41af_observed = getattr(_ember_28f42e29e3fb41af_module, '__file__', None)
    if _ember_28f42e29e3fb41af_observed is None or _ember_28f42e29e3fb41af_Path(_ember_28f42e29e3fb41af_observed).resolve() != _ember_28f42e29e3fb41af_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/p1_envelope_sweep.py')
else:
    _ember_28f42e29e3fb41af_spec = _ember_28f42e29e3fb41af_importlib.spec_from_file_location('_ember_issue2015_28f42e29e3fb41af', _ember_28f42e29e3fb41af_path)
    if _ember_28f42e29e3fb41af_spec is None or _ember_28f42e29e3fb41af_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/p1_envelope_sweep.py')
    _ember_28f42e29e3fb41af_module = _ember_28f42e29e3fb41af_importlib.module_from_spec(_ember_28f42e29e3fb41af_spec)
    for _ember_28f42e29e3fb41af_alias in _ember_28f42e29e3fb41af_aliases:
        _ember_28f42e29e3fb41af_prior = _ember_28f42e29e3fb41af_sys.modules.get(_ember_28f42e29e3fb41af_alias)
        if _ember_28f42e29e3fb41af_prior is not None and _ember_28f42e29e3fb41af_prior is not _ember_28f42e29e3fb41af_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p1_envelope_sweep.py')
        _ember_28f42e29e3fb41af_sys.modules[_ember_28f42e29e3fb41af_alias] = _ember_28f42e29e3fb41af_module
    try:
        _ember_28f42e29e3fb41af_spec.loader.exec_module(_ember_28f42e29e3fb41af_module)
    except BaseException:
        for _ember_28f42e29e3fb41af_alias in _ember_28f42e29e3fb41af_aliases:
            if _ember_28f42e29e3fb41af_sys.modules.get(_ember_28f42e29e3fb41af_alias) is _ember_28f42e29e3fb41af_module:
                _ember_28f42e29e3fb41af_sys.modules.pop(_ember_28f42e29e3fb41af_alias, None)
        raise
for _ember_28f42e29e3fb41af_alias in _ember_28f42e29e3fb41af_aliases:
    _ember_28f42e29e3fb41af_prior = _ember_28f42e29e3fb41af_sys.modules.get(_ember_28f42e29e3fb41af_alias)
    if _ember_28f42e29e3fb41af_prior is not None and _ember_28f42e29e3fb41af_prior is not _ember_28f42e29e3fb41af_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/p1_envelope_sweep.py')
    _ember_28f42e29e3fb41af_sys.modules[_ember_28f42e29e3fb41af_alias] = _ember_28f42e29e3fb41af_module
sweep = _ember_28f42e29e3fb41af_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/p1_envelope_sweep.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/w1_collapse_control_run.py
import importlib.util as _ember_85e76a5cb35a8ea2_importlib
import sys as _ember_85e76a5cb35a8ea2_sys
from pathlib import Path as _ember_85e76a5cb35a8ea2_Path
_ember_85e76a5cb35a8ea2_path = _ember_85e76a5cb35a8ea2_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'w1_collapse_control_run.py')
if not _ember_85e76a5cb35a8ea2_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w1_collapse_control_run.py')
_ember_85e76a5cb35a8ea2_aliases = ('_ember_issue2015_85e76a5cb35a8ea2', 'scripts.w1_collapse_control_run', 'w1_collapse_control_run')
_ember_85e76a5cb35a8ea2_existing = []
for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
    _ember_85e76a5cb35a8ea2_candidate = _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias)
    if _ember_85e76a5cb35a8ea2_candidate is not None and all(_ember_85e76a5cb35a8ea2_candidate is not item for item in _ember_85e76a5cb35a8ea2_existing):
        _ember_85e76a5cb35a8ea2_existing.append(_ember_85e76a5cb35a8ea2_candidate)
if len(_ember_85e76a5cb35a8ea2_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w1_collapse_control_run.py')
if _ember_85e76a5cb35a8ea2_existing:
    _ember_85e76a5cb35a8ea2_module = _ember_85e76a5cb35a8ea2_existing[0]
    _ember_85e76a5cb35a8ea2_observed = getattr(_ember_85e76a5cb35a8ea2_module, '__file__', None)
    if _ember_85e76a5cb35a8ea2_observed is None or _ember_85e76a5cb35a8ea2_Path(_ember_85e76a5cb35a8ea2_observed).resolve() != _ember_85e76a5cb35a8ea2_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w1_collapse_control_run.py')
else:
    _ember_85e76a5cb35a8ea2_spec = _ember_85e76a5cb35a8ea2_importlib.spec_from_file_location('_ember_issue2015_85e76a5cb35a8ea2', _ember_85e76a5cb35a8ea2_path)
    if _ember_85e76a5cb35a8ea2_spec is None or _ember_85e76a5cb35a8ea2_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w1_collapse_control_run.py')
    _ember_85e76a5cb35a8ea2_module = _ember_85e76a5cb35a8ea2_importlib.module_from_spec(_ember_85e76a5cb35a8ea2_spec)
    for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
        _ember_85e76a5cb35a8ea2_prior = _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias)
        if _ember_85e76a5cb35a8ea2_prior is not None and _ember_85e76a5cb35a8ea2_prior is not _ember_85e76a5cb35a8ea2_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_collapse_control_run.py')
        _ember_85e76a5cb35a8ea2_sys.modules[_ember_85e76a5cb35a8ea2_alias] = _ember_85e76a5cb35a8ea2_module
    try:
        _ember_85e76a5cb35a8ea2_spec.loader.exec_module(_ember_85e76a5cb35a8ea2_module)
    except BaseException:
        for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
            if _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias) is _ember_85e76a5cb35a8ea2_module:
                _ember_85e76a5cb35a8ea2_sys.modules.pop(_ember_85e76a5cb35a8ea2_alias, None)
        raise
for _ember_85e76a5cb35a8ea2_alias in _ember_85e76a5cb35a8ea2_aliases:
    _ember_85e76a5cb35a8ea2_prior = _ember_85e76a5cb35a8ea2_sys.modules.get(_ember_85e76a5cb35a8ea2_alias)
    if _ember_85e76a5cb35a8ea2_prior is not None and _ember_85e76a5cb35a8ea2_prior is not _ember_85e76a5cb35a8ea2_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_collapse_control_run.py')
    _ember_85e76a5cb35a8ea2_sys.modules[_ember_85e76a5cb35a8ea2_alias] = _ember_85e76a5cb35a8ea2_module
w1c = _ember_85e76a5cb35a8ea2_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/w1_collapse_control_run.py  # noqa: E402


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
    """cosine_warmup_frac's curve shape (min_lr_frac=0.1 default, unchanged
    by the warmup_steps override -- see the dedicated override tests below
    for that surface) must match a standard cosine-with-warmup decay to 10%
    of peak. Uses a synthetic budget with several warmup steps to check the
    ramp, and point 3's own real computed budget for the "decays to
    min_lr_frac at the final step" endpoint (what this lane's gate probe
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
# warmup_steps override (docs/ledgers/deviations.md DEV-003, ruling d): additive
# reuse on src/ember/governance/scripts/w1_collapse_control_run.py's cosine_warmup_frac /
# apply_cosine_warmup / run_phase2_live -- default None must be BYTE-
# IDENTICAL to pre-DEV-003 behavior (regression), and an explicit override
# must take effect exactly (no fraction round-trip).
# ---------------------------------------------------------------------------

def test_warmup_steps_override_default_none_matches_prior_frac_behavior():
    """Regression: warmup_steps=None (the default for every OTHER existing
    caller of these shared functions, e.g. main_live) must reproduce the
    exact pre-DEV-003 formula -- max(1, int(total_steps * warmup_frac))."""
    total_steps = 137
    for step in (0, 1, 13, 68, 136, 137):
        with_default = w1c.cosine_warmup_frac(step, total_steps)
        explicit_none = w1c.cosine_warmup_frac(step, total_steps, warmup_steps=None)
        assert with_default == explicit_none
        # cross-check against the formula directly (never trust one path alone)
        ws = max(1, int(total_steps * 0.1))
        if step < ws:
            expected = (step + 1) / ws
        else:
            import math
            progress = min(1.0, (step - ws) / max(1, total_steps - ws))
            expected = 0.1 + 0.9 * (0.5 * (1.0 + math.cos(math.pi * progress)))
        assert with_default == pytest.approx(expected, abs=1e-12)


def test_warmup_steps_override_takes_effect_exactly():
    """An explicit warmup_steps must be used VERBATIM (never re-derived from
    warmup_frac*total_steps) -- pick a budget/override pair where the two
    formulas clearly disagree and confirm the override wins."""
    total_steps = 1000
    frac_derived_warmup = max(1, int(total_steps * 0.1))  # == 100
    override_warmup = 20  # deliberately far from the frac-derived value

    # at step 50: under frac-derived warmup (100), step 50 is STILL in
    # warmup (ramping, < 1.0); under the override (20), step 50 is PAST
    # warmup and already decaying via cosine.
    default_mult = w1c.cosine_warmup_frac(50, total_steps)
    override_mult = w1c.cosine_warmup_frac(50, total_steps, warmup_steps=override_warmup)
    assert 50 < frac_derived_warmup  # sanity: step 50 is inside the default warmup window
    assert 50 >= override_warmup     # sanity: step 50 is past the override's warmup window
    assert default_mult < 1.0
    assert override_mult != default_mult

    # the override's own warmup boundary must behave correctly: the step
    # immediately before it still ramps, matching (step+1)/warmup_steps.
    just_inside = w1c.cosine_warmup_frac(override_warmup - 1, total_steps,
                                          warmup_steps=override_warmup)
    assert just_inside == pytest.approx(
        override_warmup / override_warmup, abs=1e-12)  # == 1.0, last warmup step


def test_apply_cosine_warmup_warmup_steps_default_unchanged(monkeypatch):
    """apply_cosine_warmup (the function run_phase2_live actually calls
    every step) must ALSO preserve default behavior with warmup_steps
    omitted -- exercised on a tiny fake optimizer/base_lrs pair (no torch
    model needed, matching this function's own pure-dict contract)."""
    class _FakeParamGroup(dict):
        pass

    class _FakeOptimizer:
        def __init__(self):
            self.param_groups = [{"lr": 0.0}]

    optimizers = {"muon": _FakeOptimizer(), "adamw": _FakeOptimizer()}
    base_lrs = {"muon": 0.02, "adamw": 0.0003}

    mult_default = w1c.apply_cosine_warmup(optimizers, base_lrs, 5, 137)
    mult_explicit_none = w1c.apply_cosine_warmup(optimizers, base_lrs, 5, 137,
                                                  warmup_steps=None)
    assert mult_default == mult_explicit_none
    assert optimizers["muon"].param_groups[0]["lr"] == pytest.approx(
        base_lrs["muon"] * mult_explicit_none)


def test_intended_warmup_steps_matches_what_the_live_runner_passes():
    """Integration check on the SPEC-side of the fix: intended_warmup_steps
    (this script's prereg-rule computation) is exactly what run_point_live
    now threads through as run_phase2_live's warmup_steps= kwarg (see the
    source -- grepped rather than re-executed, since the live path needs a
    real GPU/corpus)."""
    import inspect
    src = inspect.getsource(sweep.run_point_live)
    assert "warmup_steps=intended_warmup" in src, (
        "run_point_live must pass warmup_steps=intended_warmup to "
        "w1c.run_phase2_live -- DEV-003 ruling d requires the prereg-"
        "intended figure to be the ACTUALLY-APPLIED one, not merely disclosed")


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
