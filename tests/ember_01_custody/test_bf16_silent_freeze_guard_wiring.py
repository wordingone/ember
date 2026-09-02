# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C0 conjunct-3 wiring test for the BF16_SILENT_FREEZE failure class.

The C0 ledger row for BF16_SILENT_FREEZE was reverted from CLOSED_GUARDED because
its previously-cited guard (src/ember/governance/scripts/tests/test_screen792_bf16_momentum.py) is DEAD
ON IMPORT -- bytes exist but the file cannot even be pytest-collected, so it cannot
regression-guard anything. The row's own reopening bar (verbatim from
manifests/ember-01-custody/c0-failure-class-ledger.json) is: "a LIVE guard on the
current bf16-momentum path lands and is proven collectable + RED-first."

src/ember/governance/scripts/preflight/update_survival.py (landed #1232, merged 2026-07-31, independent
of and postdating the dead #792 guard) IS that live guard: it distinguishes
gradient-caused parameter movement from weight-decay movement under a treatment
dtype (including bf16), and fails PREFLIGHT_FAIL when a tensor class's
causal-changed-fraction falls below its declared survival floor -- exactly the
silent-freeze signature (a run that LOOKS like it trained because parameters moved,
but the movement was pure decay, not a gradient-caused update).

This file adds the C0-custody-owned wiring proof on top of #1232's own focused
suite (tests/test_update_survival_preflight.py etc., already collectable and
green -- confirmed directly, not assumed):

1. RED-first positive control: the module's own BitNet 15-of-24 bf16 fixture (9
   norm_scale tensors carry a gradient too small to clear their causal-survival
   floor under bf16 storage -- a genuine silent freeze) is rejected PREFLIGHT_FAIL.
2. Mutation-proof load-bearing check: the SAME fixture, with the causal-changed-
   fraction floor comparison neutralized (monkeypatched to report every tensor
   class as 100% causally changed), is wrongly accepted PREFLIGHT_PASS -- proving
   the floor comparison is the guard, not decorative code alongside it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

update_survival = importlib.import_module("src.ember.governance.scripts.preflight.update_survival")


def _bitnet_freeze_probes(*, required_survival: bool) -> list:
    """The module's own 15-weight/9-norm_scale BitNet fixture, with
    required_survival controllable so the two independent freeze-detection paths
    (per-tensor frozen_required_tensors vs. per-class causal_changed_fraction
    floor) can be exercised separately."""
    base = update_survival._selftest_bitnet_probes()
    return [
        update_survival.TensorProbe(
            name=probe.name,
            tensor_class=probe.tensor_class,
            initial=probe.initial,
            gradient=probe.gradient,
            required_survival=required_survival,
        )
        for probe in base
    ]


def _bitnet_freeze_case(*, required_survival: bool = True) -> dict:
    return {
        "probes": _bitnet_freeze_probes(required_survival=required_survival),
        "optimizer_spec": update_survival._selftest_sgd_spec(),
        "treatment_dtype": update_survival.torch.bfloat16,
        "step_counts": (1,),
        "class_survival_floors": {"weight": 0.9, "norm_scale": 0.01},
        "gradient_source": {
            "kind": "synthetic",
            "source_id": "c0-bf16-silent-freeze-wiring-v1",
        },
    }


def test_bf16_momentum_silent_freeze_fixture_is_preflight_fail() -> None:
    """RED-first: the genuine silent-freeze fixture must be rejected."""
    receipt = update_survival.run_update_survival_preflight(**_bitnet_freeze_case())
    assert receipt["verdict"] == "PREFLIGHT_FAIL"
    failed_classes = {
        class_name
        for step in receipt["steps"]
        for class_name in step["failed_tensor_classes"]
    }
    assert "norm_scale" in failed_classes


def test_bf16_momentum_class_floor_freeze_is_preflight_fail_isolated() -> None:
    """RED-first, isolated to the per-class causal_changed_fraction floor path:
    with required_survival=False (the per-tensor frozen_required_tensors path
    disabled), the SAME genuine freeze is still caught by the class floor alone."""
    receipt = update_survival.run_update_survival_preflight(
        **_bitnet_freeze_case(required_survival=False)
    )
    assert receipt["verdict"] == "PREFLIGHT_FAIL"
    failed_classes = {
        class_name
        for step in receipt["steps"]
        for class_name in step["failed_tensor_classes"]
    }
    assert "norm_scale" in failed_classes


def test_bf16_momentum_freeze_mutation_guard_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neutralize the causal-changed-fraction floor comparison (the class-level
    detection path, isolated via required_survival=False so the per-tensor
    frozen_required_tensors path cannot independently catch the freeze) and prove
    the same genuinely-frozen fixture is then wrongly accepted -- the floor
    comparison is load-bearing, not vacuous."""

    real_class_metrics = update_survival._class_metrics

    def _always_fully_changed(rows):
        result = real_class_metrics(rows)
        for class_name in result:
            result[class_name]["causal_changed_fraction"] = 1.0
        return result

    monkeypatch.setattr(update_survival, "_class_metrics", _always_fully_changed)
    receipt = update_survival.run_update_survival_preflight(
        **_bitnet_freeze_case(required_survival=False)
    )
    assert receipt["verdict"] == "PREFLIGHT_PASS"
    for step in receipt["steps"]:
        assert step["failed_tensor_classes"] == []
        assert step["frozen_required_tensors"] == []
