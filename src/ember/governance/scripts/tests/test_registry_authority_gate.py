# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from registry_gate import check, check_dispatch_authority  # noqa: E402


GOAL = "EMBER-00"
OUTCOME = "EMBER-01 clean 3B custody and identity spine"
CAPABILITIES = ["text", "image", "audio", "reasoning", "structured_tool_use"]


def candidate(**patch):
    authority = {
        "artifact_class": "research_candidate",
        "execution_authority": "allowed",
        "goal_id": GOAL,
        "next_executed_outcome": OUTCOME,
        "total_parameters": 3_000_000_000,
        "native_capabilities": CAPABILITIES,
        "published_family_backbone": "none",
        "model_mediated_signals": [],
    }
    authority.update(patch)
    return {"authority": authority}


def test_historical_config_is_never_dispatchable() -> None:
    config = {
        "authority": {
            "artifact_class": "historical_only",
            "execution_authority": "denied",
            "goal_id": GOAL,
            "next_executed_outcome": OUTCOME,
        }
    }
    ok, reason = check_dispatch_authority(config, GOAL, OUTCOME)
    assert ok is False
    assert "historical" in reason


def test_candidate_must_match_active_goal_and_outcome() -> None:
    ok, reason = check_dispatch_authority(
        candidate(goal_id="EMBER-01"), GOAL, OUTCOME
    )
    assert ok is False
    assert "goal_id" in reason

    ok, reason = check_dispatch_authority(
        candidate(next_executed_outcome="different"), GOAL, OUTCOME
    )
    assert ok is False
    assert "next_executed_outcome" in reason


def test_candidate_must_conserve_scale_modalities_and_lineage() -> None:
    for patch in (
        {"total_parameters": 2_999_999_999},
        {"native_capabilities": ["text", "image", "audio", "structured_tool_use"]},
        {"published_family_backbone": "llama"},
        {"model_mediated_signals": ["teachers"]},
    ):
        ok, _reason = check_dispatch_authority(candidate(**patch), GOAL, OUTCOME)
        assert ok is False


DECLARED_TEACHER = {"model": "open-teacher", "version": "sha256:" + "a" * 64, "role": "teacher", "licence_recorded": True, "share": 0.25}


def test_declared_licence_recorded_model_signal_passes() -> None:
    """GOAL §6: a declared, licence-recorded model-assisted input is admissible at dispatch."""
    ok, reason = check_dispatch_authority(candidate(model_mediated_signals=[DECLARED_TEACHER]), GOAL, OUTCOME)
    assert ok is True, reason


def test_undeclared_model_signal_variants_refuse() -> None:
    """GOAL §6 condition 2: bare, unlicensed, unversioned, weights-role or zero-share signals refuse."""
    for entry in (
        "teachers",
        {**DECLARED_TEACHER, "licence_recorded": False},
        {k: v for k, v in DECLARED_TEACHER.items() if k != "version"},
        {**DECLARED_TEACHER, "role": "weights"},
        {**DECLARED_TEACHER, "share": 0},
    ):
        ok, reason = check_dispatch_authority(candidate(model_mediated_signals=[entry]), GOAL, OUTCOME)
        assert ok is False and "undeclared" in reason, (entry, reason)


def test_fully_bound_candidate_passes_config_specific_gate() -> None:
    ok, reason = check_dispatch_authority(candidate(), GOAL, OUTCOME)
    assert ok is True, reason


def test_frozen_reference_seat_is_preserved_without_lineage_credit() -> None:
    config = {
        "authority": {
            "artifact_class": "borrowed_reference",
            "execution_authority": "reference_only",
            "goal_id": GOAL,
            "next_executed_outcome": OUTCOME,
            "frozen": True,
            "lineage_ingress": False,
            "capability_credit": "none",
            "model_mediated_signals": [],
        }
    }
    ok, reason = check_dispatch_authority(config, GOAL, OUTCOME)
    assert ok is True, reason
    config["authority"]["lineage_ingress"] = True
    ok, reason = check_dispatch_authority(config, GOAL, OUTCOME)
    assert ok is False
    assert "lineage_ingress" in reason


def test_registry_consumes_only_currently_adopted_rows() -> None:
    rows = [
        {"id": "current", "status": "ADOPTED_CURRENT_CONFIG"},
        {"id": "teacher", "status": "HISTORICAL_EVIDENCE"},
    ]
    config = {"registry": {"consumes": ["current", "teacher", "unknown"]}}
    verdict = check(config, rows)
    assert verdict["ok"] is False
    assert verdict["inactive_consumed"] == ["teacher"]
    assert verdict["unknown_consumed"] == ["unknown"]
