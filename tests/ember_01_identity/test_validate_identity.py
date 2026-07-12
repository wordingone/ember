from __future__ import annotations

# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
FIXTURE = Path(__file__).parent / "fixtures" / "valid-identity-v1.json"
SCHEMA_PATH = ROOT / "manifests" / "ember-01-identity" / "schema-v1.json"
NEGATIVE_CASES = Path(__file__).parent / "fixtures" / "negative-cases-v1.json"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_identity import (  # noqa: E402
    IdentityValidationError,
    canonical_json,
    validate_manifest,
)


def valid_manifest() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def admitted_manifest() -> dict:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "OWNED_ADMITTED"
    payload["identity"]["selected_as_owned_ember"] = True
    for field in ("allocated", "unique", "active", "served", "actually_trained"):
        payload["parameters"][field] = 3_000_000_000
    payload["capabilities"]["reasoning"] = {
        "state": "VERIFIED",
        "evidence_receipts": ["6" * 64],
    }
    payload["capabilities"]["structured_tool_use"] = {
        "state": "VERIFIED",
        "evidence_receipts": ["7" * 64],
    }
    payload["capabilities"]["native_modalities"] = {
        "text": {"state": "VERIFIED", "evidence_receipts": ["a" * 64]},
        "image": {"state": "VERIFIED", "evidence_receipts": ["b" * 64]},
        "audio": {"state": "VERIFIED", "evidence_receipts": ["c" * 64]},
    }
    payload["training"]["stopping_rule"] = {
        "criterion_id": "sufficient-pretraining-v1",
        "result": "PASSED",
        "receipt_sha256": "d" * 64,
    }
    payload["backend"]["process_identity"] = {
        "pid": 123,
        "start_time_utc": "2026-07-12T00:00:00Z",
        "executable_sha256": "4" * 64,
        "command_sha256": "8" * 64,
        "nonce": "fixture-process",
    }
    payload["backend"]["resource_lease_id"] = "fixture-lease"
    payload["evaluation"]["score"] = {"value": 1.0, "unit": "fixture-score"}
    payload["evaluation"]["uncertainty"] = {"value": 0.0, "unit": "fixture-score"}
    payload["evaluation"]["receipt_sha256"] = "9" * 64
    payload["evaluation"]["counts_toward_owned_completion"] = True
    payload["unresolved"] = []
    return payload


def test_json_schema_is_versioned_and_closed_world() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:ember:model-experiment-identity:v1"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(valid_manifest())
    assert schema["properties"]["schema"]["const"] == "ember-model-experiment-identity-v1"
    assert "anyOf" in schema["$defs"]["valueOrUnresolved"]


def test_json_schema_rejects_untyped_runtime_and_mechanism_objects() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    payload = valid_manifest()
    payload["backend"]["process_identity"] = {"pid": 123}
    assert list(validator.iter_errors(payload))

    payload = valid_manifest()
    payload["mechanisms"]["experts"] = ["unnamed-expert"]
    assert list(validator.iter_errors(payload))


def error_codes(payload: dict, **kwargs) -> set[str]:
    with pytest.raises(IdentityValidationError) as caught:
        validate_manifest(payload, **kwargs)
    return {finding["code"] for finding in caught.value.findings}


def _set_path(payload: dict, path: str, value: object) -> None:
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _delete_path(payload: dict, path: str) -> None:
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    del target[parts[-1]]


def test_named_negative_fixture_catalog_fails_for_declared_reason() -> None:
    cases = json.loads(NEGATIVE_CASES.read_text(encoding="utf-8"))
    assert len(cases) >= 8
    for case in cases:
        payload = valid_manifest()
        if "set" in case:
            _set_path(payload, case["path"], case["set"])
        else:
            _delete_path(payload, case["path"])
        assert case["expected_code"] in error_codes(payload), case["id"]


def test_valid_manifest_round_trips_without_reinterpretation() -> None:
    payload = valid_manifest()
    validated = validate_manifest(copy.deepcopy(payload))
    assert json.loads(canonical_json(validated)) == payload


def test_unknown_schema_and_missing_required_field_fail() -> None:
    payload = valid_manifest()
    payload["schema"] = "future-unrecognized-schema"
    assert "schema.unsupported" in error_codes(payload)

    payload = valid_manifest()
    del payload["tokenizer"]["sha256"]
    assert "field.missing" in error_codes(payload)


def test_authority_binding_is_required() -> None:
    payload = valid_manifest()
    del payload["authority"]["goal_id"]
    assert "field.missing" in error_codes(payload)


def test_checkpoint_bytes_and_tensor_hashes_are_bound() -> None:
    payload = valid_manifest()
    assert hashlib.sha256(b"hello world").hexdigest() == payload["checkpoint"]["byte_sha256"]
    assert "checkpoint.byte_hash_mismatch" in error_codes(
        payload, checkpoint_bytes=b"different bytes"
    )
    assert "checkpoint.tensor_hash_mismatch" in error_codes(
        payload, tensor_hashes={"fixture.weight": "0" * 64}
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unique", 3_000_000_001),
        ("active", 3_000_000_001),
        ("trainable", 3_000_000_001),
        ("served", 3_000_000_001),
        ("actually_trained", 3_000_000_001),
    ],
)
def test_contradictory_parameter_counts_fail(field: str, value: int) -> None:
    payload = valid_manifest()
    payload["parameters"][field] = value
    assert "parameters.contradictory" in error_codes(payload)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        ("architecture.sha256", "9" * 64),
        ("tokenizer.sha256", "9" * 64),
        ("data.sha256", "9" * 64),
        ("mechanisms.router", ["unexpected-router"]),
        ("backend.executable_sha256", "9" * 64),
        ("evaluation.benchmark_id", "wrong-benchmark"),
        ("evaluation.comparator_identity", "wrong-comparator"),
        ("checkpoint.ancestry", []),
    ],
)
def test_expected_identity_bindings_fail_closed(path: str, replacement: object) -> None:
    expected = valid_manifest()
    payload = copy.deepcopy(expected)
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = replacement
    assert f"binding.{path}_mismatch" in error_codes(payload, expected=expected)


@pytest.mark.parametrize(
    ("path", "replacement", "expected_code"),
    [
        ("architecture.source", "other.py", "binding.architecture_mismatch"),
        ("tokenizer.id", "other-tokenizer", "binding.tokenizer_mismatch"),
        ("data.ordering_sha256", "9" * 64, "binding.data_mismatch"),
        ("mechanisms.world_models", ["other-world"], "binding.mechanisms_mismatch"),
        ("backend.protocol", "other-protocol", "binding.backend_mismatch"),
        (
            "training.stopping_rule.result",
            "FAILED",
            "binding.training.stopping_rule_mismatch",
        ),
        (
            "training.modality_mixture.audio",
            0.20,
            "binding.training.modality_mixture_mismatch",
        ),
        (
            "capabilities.native_modalities.audio.state",
            "REGRESSED",
            "binding.capabilities.native_modalities_mismatch",
        ),
        ("evaluation.version", "v2", "binding.evaluation.version_mismatch"),
        ("evaluation.split", "other", "binding.evaluation.split_mismatch"),
        ("evaluation.harness_sha256", "9" * 64, "binding.evaluation.harness_sha256_mismatch"),
    ],
)
def test_all_identity_axes_are_expected_bindings(
    path: str, replacement: object, expected_code: str
) -> None:
    expected = valid_manifest()
    payload = copy.deepcopy(expected)
    _set_path(payload, path, replacement)
    assert expected_code in error_codes(payload, expected=expected)


def test_reference_only_cannot_be_owned_or_counted() -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "REFERENCE_ONLY"
    payload["identity"]["selected_as_owned_ember"] = True
    payload["evaluation"]["counts_toward_owned_completion"] = True
    codes = error_codes(payload)
    assert "reference.selected_as_owned" in codes
    assert "reference.owned_completion_credit" in codes


@pytest.mark.parametrize("source", ["harness", "tool", "script", "verifier", "ui_label"])
def test_non_neural_surfaces_cannot_supply_capability_credit(source: str) -> None:
    payload = valid_manifest()
    payload["provenance"]["neural_capability_credit_sources"] = [source]
    assert "capability.invalid_credit_source" in error_codes(payload)


def test_verified_capability_requires_checkpoint_bound_receipt() -> None:
    payload = valid_manifest()
    payload["capabilities"]["reasoning"]["state"] = "VERIFIED"
    assert "capability.evidence_missing" in error_codes(payload)


@pytest.mark.parametrize(
    "source",
    ["weights", "outputs", "teachers", "judges", "filters", "ranks", "curricula", "stopping_decisions", "hidden_external_cognition"],
)
def test_exact_forbidden_lineage_signals_are_rejected(source: str) -> None:
    payload = valid_manifest()
    payload["provenance"]["learned_signal_sources"] = [source]
    assert "provenance.forbidden_learned_signal" in error_codes(payload)


def test_unresolved_values_are_explicit_and_preserved() -> None:
    payload = valid_manifest()
    validated = validate_manifest(copy.deepcopy(payload))
    assert validated["backend"]["process_identity"] == {
        "status": "unresolved",
        "reason": "synthetic fixture is not running",
    }
    assert "field.unresolved" in error_codes(payload, require_resolved=True)


def test_missing_values_are_not_defaulted() -> None:
    payload = valid_manifest()
    del payload["backend"]["process_identity"]
    assert "field.missing" in error_codes(payload)


def test_validator_rejects_unknown_fields_at_every_fixed_boundary() -> None:
    payload = valid_manifest()
    payload["invented_identity"] = "filename-derived"
    assert "field.unknown" in error_codes(payload)

    payload = valid_manifest()
    payload["checkpoint"]["label"] = "2.2b"
    assert "field.unknown" in error_codes(payload)


def test_validator_rejects_malformed_resolved_runtime_objects() -> None:
    payload = valid_manifest()
    payload["backend"]["process_identity"] = {"pid": 123}
    assert "backend.process_identity_invalid" in error_codes(payload)

    payload = valid_manifest()
    payload["mechanisms"]["experts"] = ["unnamed-expert"]
    assert "mechanism.identity_invalid" in error_codes(payload)

    payload = valid_manifest()
    payload["backend"]["runtime_dependencies"] = [{"name": "python"}]
    assert "backend.runtime_dependency_invalid" in error_codes(payload)


@pytest.mark.parametrize(
    ("path", "replacement", "expected_code"),
    [
        ("capabilities.native_modalities", None, "capabilities.native_modalities_invalid"),
        ("capabilities.native_modalities", [{"invented": True}], "capabilities.native_modalities_invalid"),
        ("training.modality_mixture.text", True, "training.modality_mixture_invalid"),
        ("checkpoint.ancestry", {}, "checkpoint.ancestry_invalid"),
        ("checkpoint.tensors", {}, "checkpoint.tensors_invalid"),
    ],
)
def test_validator_rejects_malformed_shapes_without_crashing(
    path: str, replacement: object, expected_code: str
) -> None:
    payload = valid_manifest()
    _set_path(payload, path, replacement)
    assert expected_code in error_codes(payload)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        ("identity.disposition", "EXTERNAL_QWEN_MISLABELED"),
        ("identity.selected_as_owned_ember", "true"),
        ("data.clean_genesis", "yes"),
        ("provenance.ownership", "arbitrary-owner"),
        ("provenance.learned_signal_sources", ["qwen_teacher_signal"]),
        ("provenance.neural_capability_credit_sources", ["external_qwen"]),
    ],
)
def test_runtime_validator_applies_canonical_schema(
    path: str, replacement: object
) -> None:
    payload = valid_manifest()
    _set_path(payload, path, replacement)
    assert "schema.validation" in error_codes(payload)


@pytest.mark.parametrize(
    "disposition", ["OWNED_CANDIDATE", "HISTORICAL_ONLY", "REFERENCE_ONLY"]
)
def test_only_owned_admitted_can_be_selected_or_counted(disposition: str) -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = disposition
    payload["identity"]["selected_as_owned_ember"] = True
    payload["evaluation"]["counts_toward_owned_completion"] = True
    assert "admission.disposition" in error_codes(payload)


@pytest.mark.parametrize(
    ("path", "replacement", "expected_code"),
    [
        ("data.clean_genesis", False, "admission.clean_genesis"),
        ("provenance.ownership", "REFERENCE_ONLY", "admission.ownership"),
        ("parameters.served", 0, "admission.parameter_floor"),
        ("parameters.actually_trained", 2_999_999_999, "admission.parameter_floor"),
        (
            "capabilities.reasoning.state",
            "UNVERIFIED",
            "admission.capability_evidence",
        ),
    ],
)
def test_owned_admission_requires_positive_evidence(
    path: str, replacement: object, expected_code: str
) -> None:
    payload = admitted_manifest()
    _set_path(payload, path, replacement)
    assert expected_code in error_codes(payload)


def test_owned_admission_rejects_any_unresolved_evidence() -> None:
    payload = admitted_manifest()
    payload["evaluation"]["score"] = {
        "status": "unresolved",
        "reason": "not measured",
    }
    payload["unresolved"] = ["evaluation.score"]
    assert "admission.unresolved" in error_codes(payload)


def test_fully_evidenced_owned_admission_passes() -> None:
    payload = admitted_manifest()
    assert validate_manifest(payload) == payload


@pytest.mark.parametrize(
    "path",
    [
        "provenance.learned_signal_sources",
        "provenance.neural_capability_credit_sources",
    ],
)
def test_malformed_admission_source_items_fail_without_crashing(path: str) -> None:
    payload = admitted_manifest()
    _set_path(payload, path, [{"renamed_external_source": "qwen"}])
    assert "schema.validation" in error_codes(payload)


def test_owned_admission_requires_nonzero_training_exposure_per_modality() -> None:
    payload = admitted_manifest()
    payload["training"]["modality_mixture"] = {
        "text": 0.75,
        "image": 0.0,
        "audio": 0.25,
    }
    assert "admission.modality_exposure" in error_codes(payload)


def test_owned_admission_requires_checkpoint_bound_receipt_per_modality() -> None:
    payload = admitted_manifest()
    payload["capabilities"]["native_modalities"] = {
        "text": {"state": "VERIFIED", "evidence_receipts": ["a" * 64]},
        "image": {"state": "VERIFIED", "evidence_receipts": ["b" * 64]},
        "audio": {"state": "UNVERIFIED", "evidence_receipts": []},
    }
    assert "admission.native_modality_evidence" in error_codes(payload)


@pytest.mark.parametrize("result", ["NOT_REACHED", "FAILED"])
def test_owned_admission_requires_passed_sufficient_pretraining_receipt(
    result: str,
) -> None:
    payload = admitted_manifest()
    payload["training"]["stopping_rule"] = {
        "criterion_id": "sufficient-pretraining-v1",
        "result": result,
        "receipt_sha256": "c" * 64,
    }
    assert "admission.sufficient_pretraining" in error_codes(payload)
