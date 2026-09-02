from __future__ import annotations
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import sys
from pathlib import Path

import pytest
import torch


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPTS = ROOT / "scripts"
PHASE3 = SCRIPTS / "ember_phase3_c14"
for path in (str(PHASE3), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import abc_deleted_harness as harness
from ember_c14_contract_rig import (
    _make_stub_corpus,
    _stub_eval_arm_C_and_deleted,
    _stub_verifier,
    _validate_engagement_receipt,
)
from ember_resident_igrpo import TinyPolicyTransformer, igrpo_step


def engagement(*, requested_n: int = 4, requested_g: int = 16) -> dict:
    return {
        "schema_version": "ember-igrpo-engagement-step-v1",
        "requested_n": requested_n,
        "requested_g": requested_g,
        "realized_stage1_drafts": requested_n,
        "attempted": requested_g,
        "emitted": requested_g,
        "valid": requested_g,
        "scored": requested_g,
        "unique_completions": requested_g,
        "reward_vector_length": requested_g,
        "advantage_vector_length": requested_g,
        "group_ids": [f"stage2:{i}" for i in range(requested_g)],
        "normalization_denominator": requested_g,
        "estimator_name": "population_std_group_relative",
        "drop_reasons": [],
    }


def test_g16_full_engagement_tuple_is_accepted() -> None:
    normalized = _validate_engagement_receipt(
        {"engagement": engagement()},
        requested_n=4,
        requested_g=16,
        min_unique_completions=1,
    )
    assert normalized["scored"] == 16
    assert normalized["advantage_vector_length"] == 16
    assert normalized["normalization_denominator"] == 16
    assert normalized["unique_completions"] == 16


def test_real_cpu_g16_step_emits_a_validated_realized_receipt() -> None:
    torch.manual_seed(667)
    policy = TinyPolicyTransformer()
    optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)
    step_result = igrpo_step(
        policy,
        optimizer,
        state_val=3,
        N=4,
        G=16,
        max_depth=1,
        temperature=1.5,
    )
    normalized = _validate_engagement_receipt(
        step_result,
        requested_n=4,
        requested_g=16,
        min_unique_completions=1,
    )
    assert normalized["attempted"] == 16
    assert normalized["scored"] == 16
    assert normalized["advantage_vector_length"] == 16
    assert normalized["normalization_denominator"] == 16
    assert len(normalized["drop_reasons"]) == 16 - normalized["valid"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("realized_stage1_drafts", 3),
        ("attempted", 15),
        ("emitted", 12),
        ("scored", 15),
        ("reward_vector_length", 15),
        ("advantage_vector_length", 4),
        ("normalization_denominator", 4),
    ],
)
def test_requested_and_realized_count_mismatches_refuse(
    field: str,
    value: int,
) -> None:
    row = engagement()
    row[field] = value
    with pytest.raises(ValueError, match=field):
        _validate_engagement_receipt(
            {"engagement": row},
            requested_n=4,
            requested_g=16,
            min_unique_completions=1,
        )


def test_invalid_completions_are_allowed_only_with_exact_drop_accounting() -> None:
    row = engagement()
    row["valid"] = 11
    row["drop_reasons"] = [
        "stage2:0:fallback_fired",
        "stage2:2:fallback_fired",
        "stage2:7:fallback_fired",
        "stage2:8:fallback_fired",
        "stage2:14:fallback_fired",
    ]
    normalized = _validate_engagement_receipt(
        {"engagement": row},
        requested_n=4,
        requested_g=16,
        min_unique_completions=1,
    )
    assert normalized["valid"] == 11
    row["drop_reasons"].pop()
    with pytest.raises(ValueError, match="drop_reasons"):
        _validate_engagement_receipt(
            {"engagement": row},
            requested_n=4,
            requested_g=16,
            min_unique_completions=1,
        )


def test_group_ids_and_drop_reasons_are_canonical() -> None:
    row = engagement()
    row["group_ids"][0] = "other:0"
    with pytest.raises(ValueError, match="group_ids"):
        _validate_engagement_receipt(
            {"engagement": row},
            requested_n=4,
            requested_g=16,
            min_unique_completions=1,
        )
    row = engagement()
    row["valid"] = 15
    row["drop_reasons"] = ["stage2:0:made_up"]
    with pytest.raises(ValueError, match="drop_reasons"):
        _validate_engagement_receipt(
            {"engagement": row},
            requested_n=4,
            requested_g=16,
            min_unique_completions=1,
        )


def test_missing_typed_engagement_return_refuses() -> None:
    with pytest.raises(ValueError, match="engagement"):
        _validate_engagement_receipt(
            {},
            requested_n=4,
            requested_g=16,
            min_unique_completions=1,
        )


def test_duplicate_draws_are_receipted_and_checked_against_frozen_floor() -> None:
    row = engagement()
    row["unique_completions"] = 1
    normalized = _validate_engagement_receipt(
        {"engagement": row},
        requested_n=4,
        requested_g=16,
        min_unique_completions=1,
    )
    assert normalized["unique_completions"] == 1
    with pytest.raises(ValueError, match="unique_completions"):
        _validate_engagement_receipt(
            {"engagement": row},
            requested_n=4,
            requested_g=16,
            min_unique_completions=2,
        )


def test_phase3_wrapper_caller_counts_override_legacy_rig_defaults(monkeypatch) -> None:
    captured: dict = {}

    def fake_step(**kwargs):
        captured.update(kwargs)
        return {"engagement": engagement(requested_n=7, requested_g=16)}

    monkeypatch.setattr(harness, "igrpo_step", fake_step)
    train_fn = harness._build_toy_train_fn(N=7, M=16)
    result = train_fn(
        policy=object(),
        optimizer=object(),
        state_val=3,
        N=4,
        G=4,
    )
    assert captured["N"] == 7
    assert captured["G"] == 16
    assert result["engagement"]["requested_g"] == 16


def test_rig_c_arm_receives_caller_counts_and_preserves_step_receipt() -> None:
    captured: dict = {}
    sink: list[dict] = []

    def train_fn(**kwargs):
        captured.update(kwargs)
        return {"engagement": engagement(requested_n=7, requested_g=16)}

    corpus = _make_stub_corpus()
    _stub_eval_arm_C_and_deleted(
        core_factory=TinyPolicyTransformer,
        train_tasks=corpus.train[:1],
        heldout_tasks=corpus.heldout[:1],
        verifier=_stub_verifier,
        n_train_steps=1,
        train_resident_fn=train_fn,
        requested_n=7,
        requested_g=16,
        min_unique_completions=1,
        require_engagement_receipt=True,
        engagement_receipt_sink=sink,
    )
    assert captured["N"] == 7
    assert captured["G"] == 16
    assert len(sink) == 1
    assert sink[0]["normalization_denominator"] == 16


def test_rig_c_arm_refuses_missing_required_training_receipt() -> None:
    corpus = _make_stub_corpus()

    def train_fn(**_kwargs):
        return {}

    with pytest.raises(ValueError, match="engagement"):
        _stub_eval_arm_C_and_deleted(
            core_factory=TinyPolicyTransformer,
            train_tasks=corpus.train[:1],
            heldout_tasks=corpus.heldout[:1],
            verifier=_stub_verifier,
            n_train_steps=1,
            train_resident_fn=train_fn,
            requested_n=7,
            requested_g=16,
            min_unique_completions=1,
            require_engagement_receipt=True,
        )


def test_phase3_defaults_path_returns_first_class_realized_receipts() -> None:
    result = harness.run_phase3_contract(
        harness.Phase3ArmConfig(
            toy_cpu=True,
            n_train_steps=1,
            seed=667,
        )
    )
    assert len(result.engagement_receipts) == 1
    receipt = result.engagement_receipts[0]
    assert receipt["requested_n"] == 4
    assert receipt["requested_g"] == 4
    assert receipt["scored"] == 4
    assert receipt["normalization_denominator"] == 4


def test_unknown_engagement_fields_refuse() -> None:
    row = engagement()
    row["advertised_only"] = 16
    with pytest.raises(ValueError, match="unknown"):
        _validate_engagement_receipt(
            {"engagement": row},
            requested_n=4,
            requested_g=16,
            min_unique_completions=1,
        )
