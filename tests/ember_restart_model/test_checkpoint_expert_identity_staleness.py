# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU/meta-device regression guard for issue #892 (cured by #893).

Boundary: a specialist episode transitions the routed expert mid-run
(reasoning -> vision). The checkpoint pre-publication verifier compares an
in-process *expectation* of the active-expert identity against the isolated
counter receipt built from the freshly-staged checkpoint manifest.

Failure #892: the expectation was captured at run-start (active_expert=reasoning),
so at checkpoint the six numeric capacity fields agreed but active_expert_ids
mismatched (expected [reasoning] vs receipt [vision]) and the run failed closed.

Cure #893 (commit cf965fb, in origin/master 21d9b75): the run() verifier now
re-measures the *live* routed expert at publication via
``_counter_expected_counts(model)`` instead of the run-start ``counts``.

This test reproduces the exact boundary WITHOUT the production model or GPU:
a tiny meta-device model whose active expert transitions across the episode,
driving the same capture -> checkpoint-verify comparison. It asserts the
stale-capture strategy FAILS and the live-capture (#893) strategy PASSES, that
the verifier is NOT weakened (a genuine numeric-capacity disagreement still
fails under the live strategy), and that the production source still binds the
verifier to the live strategy (guards against a #893 revert).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import torch

# The exact required-field tuple and mismatch rule the production verifier
# applies, mirrored from tools/ember-restart-3b/run_vertical_slice.py
# (_execute_realization_counter, lines ~1881-1891 at base 21d9b75). Kept in
# lockstep with the source; a divergence in the six numeric fields would be a
# separate contract change and is asserted against the source below.
_REQUIRED_FIELDS = (
    "allocated_parameters",
    "unique_parameters",
    "trainable_parameters",
    "served_parameters",
    "active_parameters",
    "episode_trainable_parameters",
    "active_expert_ids",
)


def _verifier_disagrees(receipt: dict[str, object], expected: dict[str, object]) -> bool:
    """The production comparison: True == verifier refuses (raises RuntimeError)."""
    return any(receipt.get(name) != expected.get(name) for name in _REQUIRED_FIELDS)


class _MetaSparseModel:
    """Minimal stand-in for UnifiedDecoder: meta-device params, mutable routed expert.

    active_parameters is a function of the active expert (as in the real sparse
    model), while unique/allocated capacity is invariant to routing (the whole
    bank is instantiated). This is exactly the #892 shape: numerics agree across
    reasoning/vision here by construction, isolating the active-expert identity.
    """

    _ACTIVE_PARAMS = {"reasoning": 1_725_232_640, "vision": 1_725_232_640}

    def __init__(self, active_expert: str) -> None:
        # Genuine meta-device tensors: no host/device allocation, no GPU.
        self._bank = {
            name: torch.nn.Parameter(torch.empty(4, device="meta"), requires_grad=True)
            for name in ("reasoning", "vision")
        }
        self.active_expert = active_expert

    def _activate_expert(self, expert: str) -> None:
        assert expert in self._bank, expert
        self.active_expert = expert


def _measure_parameter_counts(model: _MetaSparseModel) -> dict[str, object]:
    """Mirror of parameter_counter.measure_parameter_counts for the fields the
    verifier compares: active_expert_ids == [model.active_expert] (live)."""
    return {
        "allocated_parameters": 3_839_161_856,
        "unique_parameters": 3_839_161_856,
        "trainable_parameters": 3_839_161_856,
        "served_parameters": 3_839_161_856,
        "active_parameters": model._ACTIVE_PARAMS[model.active_expert],
        "episode_trainable_parameters": model._ACTIVE_PARAMS[model.active_expert],
        "active_expert_ids": [model.active_expert],
    }


def _counter_expected_counts(model: _MetaSparseModel) -> dict[str, object]:
    """The #893 live-capture strategy: re-measure at checkpoint publication."""
    return _measure_parameter_counts(model)


def _receipt_from_staged_manifest(model: _MetaSparseModel) -> dict[str, object]:
    """The isolated counter's receipt is built from the freshly-staged manifest,
    whose active_expert_ids == [model.active_expert] at publication (checkpoint_artifacts).
    """
    return _measure_parameter_counts(model)


def _drive_episode() -> tuple[_MetaSparseModel, dict[str, object], dict[str, object]]:
    """Run-start on reasoning, capture the stale expectation, transition to vision,
    then produce the checkpoint-time receipt. Returns (model, stale_expected, receipt)."""
    model = _MetaSparseModel(active_expert="reasoning")
    stale_expected = _measure_parameter_counts(model)  # captured pre-activation (the #892 bug)
    model._activate_expert("vision")  # verified image episode activates the vision expert
    receipt = _receipt_from_staged_manifest(model)  # built at checkpoint time -> [vision]
    return model, stale_expected, receipt


def test_stale_capture_reproduces_892_mismatch() -> None:
    """Pre-#893 strategy (expectation pinned at run-start) fails closed."""
    _model, stale_expected, receipt = _drive_episode()
    # The exact #892 shape: six numeric capacity fields agree...
    numeric = [f for f in _REQUIRED_FIELDS if f != "active_expert_ids"]
    assert all(receipt[f] == stale_expected[f] for f in numeric)
    # ...but the stale active-expert identity disagrees, so the verifier refuses.
    assert stale_expected["active_expert_ids"] == ["reasoning"]
    assert receipt["active_expert_ids"] == ["vision"]
    assert _verifier_disagrees(receipt, stale_expected) is True


def test_live_capture_893_passes() -> None:
    """#893 strategy (re-measure the routed expert at publication) passes."""
    model, _stale, receipt = _drive_episode()
    live_expected = _counter_expected_counts(model)  # measured at checkpoint -> [vision]
    assert live_expected["active_expert_ids"] == ["vision"]
    assert _verifier_disagrees(receipt, live_expected) is False


def test_live_capture_still_catches_genuine_capacity_disagreement() -> None:
    """The fix must not weaken the verifier: a real numeric-capacity divergence
    (e.g. a corrupted/short-allocated bank) is still caught under the live strategy."""
    model, _stale, receipt = _drive_episode()
    live_expected = _counter_expected_counts(model)
    corrupted = {**receipt, "unique_parameters": receipt["unique_parameters"] - 4}
    assert _verifier_disagrees(corrupted, live_expected) is True


def test_meta_model_allocated_nothing_on_host_or_gpu() -> None:
    """Guard the CPU-only contract: every parameter stays on the meta device."""
    model = _MetaSparseModel(active_expert="reasoning")
    assert all(p.device.type == "meta" for p in model._bank.values())
    assert not torch.cuda.is_initialized()


def test_production_source_binds_verifier_to_live_capture() -> None:
    """Regression lock: run()'s pre-publication verifier must feed the live
    _counter_expected_counts(model), not a run-start `counts`. A revert of #893
    (back to `expected_counts=counts` on the routed-expert path) fails here."""
    source = (
        Path(__file__).resolve().parents[2]
        / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
    ).read_text(encoding="utf-8")
    # The routed-expert verifier call (active_expert=str(model.active_expert)) must
    # pair with the live expectation.
    routed_call = re.search(
        r"active_expert=str\(model\.active_expert\),\s*expected_counts=([A-Za-z_][\w().]*)",
        source,
    )
    assert routed_call is not None, "routed-expert verifier call not found"
    assert routed_call.group(1).startswith("_counter_expected_counts(model)"), (
        f"routed-expert verifier must use live capture, found {routed_call.group(1)!r} "
        "(a run-start `counts` here is the #892 regression)"
    )
    # And the required-field tuple this test mirrors must match the source's.
    for field in _REQUIRED_FIELDS:
        assert f'"{field}"' in source, f"verifier field {field} missing from source"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
