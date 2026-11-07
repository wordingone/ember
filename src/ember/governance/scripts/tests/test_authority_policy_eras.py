# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red tests for the two authority policy eras (INVARIANT v1 and the public succession to v2).

A GOAL policy without invariant_v2_sha256 is judged by the v1 rules (the existing fixture in
test_authority_conservation.py). One that pins v2 is judged by the v2 rules, and only when the pin binds the v2
bytes and the succession record exists. Mixed shapes fail.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from test_authority_conservation import (  # type: ignore
    assert_rejected,
    rewrite_policy,
    run_verifier,
    write_valid_fixture,
    REPO_ROOT,
)

# The real v2 and succession bytes: the verifier pins the real v2 hash, so no stand-in bytes and no override.
V2_BYTES = (REPO_ROOT / "docs" / "authority" / "INVARIANT-v2.md").read_bytes()
SUCCESSION_BYTES = (REPO_ROOT / "docs" / "authority" / "SUCCESSION-2026-11-07.md").read_bytes()


def _v2_lineage(policy: dict) -> None:
    policy["lineage"].update(
        borrowed_models_role="declared_training_resource",
        forbidden_model_mediated_signals=["weights", "hidden_external_cognition"],
        model_assisted_conditions=[
            "licence_recorded",
            "per_hour_declaration",
            "boundary_recorded_at_first_declared_hour",
            "frozen_declared_judges",
            "contamination_scrub_on_teacher_data",
        ],
        creation_rule="invariant_v2_clause_3_declared_lineage",
        creation_claims_state_model_assisted=True,
        model_free_baseline="every_hour_before_the_first_declared_model_resource",
    )
    policy["mutation_controls_required"] = [
        "undeclared_model_mediated_signal" if c == "model_mediated_signal" else c
        for c in policy["mutation_controls_required"]
    ]


def _write_v2_docs(root: Path, monkeypatch, succession: bool = True) -> str:
    d = root / "docs" / "authority"
    d.mkdir(parents=True, exist_ok=True)
    (d / "INVARIANT-v2.md").write_bytes(V2_BYTES)
    if succession:
        (d / "SUCCESSION-2026-11-07.md").write_bytes(SUCCESSION_BYTES)
    return hashlib.sha256(V2_BYTES).hexdigest()


@pytest.fixture
def v2_sha():
    return hashlib.sha256(V2_BYTES).hexdigest()


def _v2_fixture(root: Path, sha: str, monkeypatch, succession: bool = True) -> None:
    write_valid_fixture(root)
    _write_v2_docs(root, monkeypatch, succession)

    def mutate(policy):
        _v2_lineage(policy)
        policy["invariant_v2_sha256"] = sha.upper()

    rewrite_policy(root, mutate)


def _codes(root: Path) -> set[str]:
    result = run_verifier(root)
    return {item["code"] for item in json.loads(result.stdout)["errors"]}


def test_v1_shaped_policy_still_passes(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_v2_shaped_policy_bound_to_v2_passes(tmp_path: Path, v2_sha, monkeypatch) -> None:
    _v2_fixture(tmp_path, v2_sha, monkeypatch)
    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_v2_fields_without_v2_pin_refuse(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    rewrite_policy(tmp_path, _v2_lineage)
    codes = _codes(tmp_path)
    assert {"policy.borrowed_role", "policy.model_mediated_signals", "policy.mutation_controls"} <= codes


def test_v2_pin_with_v1_fields_refuses(tmp_path: Path, v2_sha, monkeypatch) -> None:
    write_valid_fixture(tmp_path)
    _write_v2_docs(tmp_path, monkeypatch)
    rewrite_policy(tmp_path, lambda p: p.update(invariant_v2_sha256=v2_sha))
    codes = _codes(tmp_path)
    assert {"policy.borrowed_role", "policy.creation_boundary", "policy.mutation_controls"} <= codes


def test_v2_pin_that_does_not_bind_the_v2_bytes_refuses(tmp_path: Path, v2_sha, monkeypatch) -> None:
    _v2_fixture(tmp_path, v2_sha, monkeypatch)
    (tmp_path / "docs" / "authority" / "INVARIANT-v2.md").write_bytes(V2_BYTES + b"edited\n")
    assert "policy.invariant_v2_unbound" in _codes(tmp_path)


def test_v2_pin_without_succession_record_refuses(tmp_path: Path, v2_sha, monkeypatch) -> None:
    _v2_fixture(tmp_path, v2_sha, monkeypatch, succession=False)
    assert "policy.invariant_v2_unbound" in _codes(tmp_path)


def test_forged_v2_pin_refuses(tmp_path: Path, v2_sha, monkeypatch) -> None:
    _v2_fixture(tmp_path, "0" * 64, monkeypatch)
    assert "policy.invariant_v2_unbound" in _codes(tmp_path)


def _candidate(root: Path, signals) -> None:
    (root / "configs" / "candidate.json").write_text(
        json.dumps(
            {
                "authority": {
                    "artifact_class": "research_candidate",
                    "execution_authority": "allowed",
                    "goal_id": "EMBER-02",
                    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                    "total_parameters": 3_000_000_000,
                    "native_capabilities": ["text", "image", "audio", "reasoning", "structured_tool_use"],
                    "published_family_backbone": "none",
                    "model_mediated_signals": signals,
                }
            }
        ),
        encoding="utf-8",
    )


DECLARED = [{"model": "m", "version": "sha256:" + "a" * 64, "role": "teacher", "licence_recorded": True, "share": 0.25}]


def test_v1_era_config_with_a_declared_signal_refuses(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    _candidate(tmp_path, DECLARED)
    assert "config.model_mediated_signal" in _codes(tmp_path)


def test_v2_era_config_with_a_declared_signal_is_admitted(tmp_path: Path, v2_sha, monkeypatch) -> None:
    _v2_fixture(tmp_path, v2_sha, monkeypatch)
    _candidate(tmp_path, DECLARED)
    codes = _codes(tmp_path)
    assert "config.undeclared_model_mediated_signal" not in codes and "config.model_mediated_signal" not in codes


def test_v2_era_config_with_an_undeclared_signal_refuses(tmp_path: Path, v2_sha, monkeypatch) -> None:
    _v2_fixture(tmp_path, v2_sha, monkeypatch)
    _candidate(tmp_path, ["teachers"])
    assert "config.undeclared_model_mediated_signal" in _codes(tmp_path)
