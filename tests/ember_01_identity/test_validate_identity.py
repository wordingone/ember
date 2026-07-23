# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations


import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
FIXTURE = Path(__file__).parent / "fixtures" / "valid-identity-v1.json"
SCHEMA_PATH = ROOT / "manifests" / "ember-01-identity" / "schema-v1.json"
NEGATIVE_CASES = Path(__file__).parent / "fixtures" / "negative-cases-v1.json"
VERIFIER_BYTES = (
    b'{"rules":["bind_checkpoint","bind_claims","derive_allocated_unique",'
    b'"require_verified_result","resolve_accepted_training_input_authority"],'
    b'"schema":"ember-admission-verifier-program-v1"}'
)
TENSOR_HASHES = {"fixture.weight": "b" * 64}
ARTIFACT_BYTES = {
    "architecture": b"owned architecture source",
    "tokenizer": b"owned tokenizer bytes",
    "data.corpus": b"owned corpus bytes",
    "data.ordering": b"owned sample order",
    "data.curriculum": b"owned curriculum",
    "data.shard_manifest": b"accepted clean-genesis shard manifest",
    "data.input_caller": b"trainer input caller",
    "data.input_gate": b"trainer input gate",
    "data.input_validator": b"trainer input validator",
    "training.optimizer_state": b"owned optimizer state",
    "training.numerics": b"bf16 activations fp32 master",
    "backend.executable": b"owned backend executable",
    "backend.command": b"emberd --manifest fixture-owned-admitted",
    "evaluation.harness": b"owned benchmark harness",
    "evaluation.comparator": b"frozen comparator identity artifact",
    "ancestry:0": b"clean genesis parent checkpoint",
    "tensor:fixture.weight": b"\x00\x00\x00\x00",
}
CHECKPOINT_BYTES = json.dumps(
    {
        "schema": "ember-checkpoint-envelope-v1",
        "tensors": [
            {
                "name": "fixture.weight",
                "shape": [1],
                "dtype": "float32",
                "content_hex": ARTIFACT_BYTES["tensor:fixture.weight"].hex(),
            }
        ],
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
TRUSTED_REGISTRY_PATH = (
    ROOT / "manifests" / "ember-01-identity" / "trusted-verifiers-v1.json"
)
sys.path.insert(0, str(SCRIPT_DIR))

import validate_identity as identity_validator  # noqa: E402

from validate_identity import (  # noqa: E402
    IdentityValidationError,
    canonical_json,
    validate_manifest,
)

TEST_SIGNING_KEY = Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY_HEX = TEST_SIGNING_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
).hex()


@pytest.fixture(autouse=True)
def pinned_test_verifier_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    registry = tmp_path / "trusted-verifiers-v1.json"
    registry.write_text(json.dumps({
        "schema": "ember-trusted-verifier-registry-v1",
        "verifiers": [{
            "verifier_sha256": hashlib.sha256(VERIFIER_BYTES).hexdigest(),
            "public_key_ed25519": TEST_PUBLIC_KEY_HEX,
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(identity_validator, "TRUSTED_VERIFIER_REGISTRY_PATH", registry)
    if request.node.name != "test_production_admission_floor_remains_three_billion":
        monkeypatch.setattr(identity_validator, "OWNED_ADMISSION_PARAMETER_FLOOR", 1)


def test_production_admission_floor_remains_three_billion() -> None:
    assert identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR == 3_000_000_000


def valid_manifest() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def receipt_sha256(receipt: dict) -> str:
    encoded = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sign_receipt(receipt: dict) -> dict:
    unsigned = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    receipt["signature_ed25519"] = TEST_SIGNING_KEY.sign(unsigned).hex()
    return receipt


def admitted_manifest(checkpoint_bytes: bytes = CHECKPOINT_BYTES) -> tuple[dict, dict[str, dict]]:
    payload = valid_manifest()
    receipts: dict[str, dict] = {}
    payload["identity"]["disposition"] = "OWNED_ADMITTED"
    payload["identity"]["selected_as_owned_ember"] = True
    payload["data"]["accepted_input"]["authority"] = "CURRENT_EXECUTABLE"
    payload["checkpoint"]["format"] = "ember-checkpoint-envelope-v1"
    payload["checkpoint"]["byte_sha256"] = hashlib.sha256(checkpoint_bytes).hexdigest()
    try:
        envelope = json.loads(checkpoint_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    else:
        payload["checkpoint"]["tensors"] = [
            {
                "name": row["name"],
                "shape": row["shape"],
                "dtype": row["dtype"],
                "sha256": hashlib.sha256(bytes.fromhex(row["content_hex"])).hexdigest(),
            }
            for row in envelope["tensors"]
        ]
    payload["evaluation"]["subject_checkpoint_sha256"] = payload["checkpoint"]["byte_sha256"]
    for field in (
        "allocated",
        "unique",
        "active",
        "trainable",
        "served",
        "actually_trained",
    ):
        payload["parameters"][field] = 1
    payload["data"]["verifier_sha256"] = hashlib.sha256(VERIFIER_BYTES).hexdigest()
    subject = payload["checkpoint"]["byte_sha256"]
    verifier = payload["data"]["verifier_sha256"]

    def bind_evidence(evidence_class: str, **claims: object) -> str:
        receipt = {
            "schema": "ember-identity-evidence-receipt-v1",
            "evidence_class": evidence_class,
            "subject_checkpoint_sha256": subject,
            "verifier_sha256": verifier,
            "result": "VERIFIED",
            **claims,
        }
        sign_receipt(receipt)
        digest = receipt_sha256(receipt)
        receipts[digest] = receipt
        return digest

    payload["parameters"]["evidence_receipts"] = {
        field: [
            bind_evidence(
                f"parameter_{field}", claimed_count=payload["parameters"][field]
            )
        ]
        for field in (
            "allocated",
            "unique",
            "active",
            "trainable",
            "served",
            "actually_trained",
        )
    }
    accepted_input = payload["data"]["accepted_input"]
    for field, artifact_id in {
        "shard_manifest_sha256": "data.shard_manifest",
        "caller_sha256": "data.input_caller",
        "gate_sha256": "data.input_gate",
        "validator_sha256": "data.input_validator",
    }.items():
        accepted_input[field] = hashlib.sha256(ARTIFACT_BYTES[artifact_id]).hexdigest()
    accepted_input["forwarding_receipt_sha256"] = bind_evidence(
        "training_input_forwarding",
        input_id=accepted_input["input_id"],
        authority_id=accepted_input["authority_id"],
        authority_record_sha256=accepted_input["authority_record_sha256"],
        authority=accepted_input["authority"],
        shard_manifest_sha256=accepted_input["shard_manifest_sha256"],
        caller_sha256=accepted_input["caller_sha256"],
        gate_sha256=accepted_input["gate_sha256"],
        validator_sha256=accepted_input["validator_sha256"],
    )

    payload["capabilities"]["reasoning"] = {
        "state": "VERIFIED",
        "evidence_receipts": [bind_evidence("reasoning")],
    }
    payload["capabilities"]["structured_tool_use"] = {
        "state": "VERIFIED",
        "evidence_receipts": [bind_evidence("structured_tool_use")],
    }
    payload["capabilities"]["native_modalities"] = {
        modality: {
            "state": "VERIFIED",
            "evidence_receipts": [bind_evidence(f"native_{modality}")],
        }
        for modality in ("text", "image", "audio")
    }
    stopping_receipt = {
        "schema": "ember-identity-evidence-receipt-v1",
        "evidence_class": "sufficient_pretraining",
        "subject_checkpoint_sha256": subject,
        "verifier_sha256": verifier,
        "criterion_id": "ember-sufficient-pretraining-v1",
        "result": "PASSED",
    }
    sign_receipt(stopping_receipt)
    stopping_digest = receipt_sha256(stopping_receipt)
    receipts[stopping_digest] = stopping_receipt
    payload["training"]["stopping_rule"] = {
        "criterion_id": "ember-sufficient-pretraining-v1",
        "result": "PASSED",
        "receipt_sha256": stopping_digest,
    }
    payload["backend"]["process_identity"] = {
        "pid": 123,
        "start_time_utc": "2026-07-12T00:00:00Z",
        "executable_sha256": hashlib.sha256(
            ARTIFACT_BYTES["backend.executable"]
        ).hexdigest(),
        "command_sha256": hashlib.sha256(
            ARTIFACT_BYTES["backend.command"]
        ).hexdigest(),
        "nonce": "fixture-process",
    }
    payload["backend"]["resource_lease_id"] = "fixture-lease"
    payload["backend"]["process_receipt_sha256"] = bind_evidence(
        "backend_process_identity",
        process_identity=payload["backend"]["process_identity"],
        protocol=payload["backend"]["protocol"],
        device=payload["backend"]["device"],
        resource_lease_id=payload["backend"]["resource_lease_id"],
    )
    payload["evaluation"]["score"] = {"value": 1.0, "unit": "fixture-score"}
    payload["evaluation"]["harness_sha256"] = hashlib.sha256(
        ARTIFACT_BYTES["evaluation.harness"]
    ).hexdigest()
    payload["evaluation"]["comparator_sha256"] = hashlib.sha256(
        ARTIFACT_BYTES["evaluation.comparator"]
    ).hexdigest()
    payload["evaluation"]["uncertainty"] = {"value": 0.0, "unit": "fixture-score"}
    payload["evaluation"]["counts_toward_owned_completion"] = True
    payload["evaluation"]["receipt_sha256"] = bind_evidence(
        "evaluation_result",
        benchmark_id=payload["evaluation"]["benchmark_id"],
        version=payload["evaluation"]["version"],
        split=payload["evaluation"]["split"],
        harness_sha256=payload["evaluation"]["harness_sha256"],
        comparator_identity=payload["evaluation"]["comparator_identity"],
        comparator_sha256=payload["evaluation"]["comparator_sha256"],
        score=payload["evaluation"]["score"],
        uncertainty=payload["evaluation"]["uncertainty"],
        counts_toward_owned_completion=True,
    )
    payload["unresolved"] = []
    # B4 REQUIRED-half (ember01plan.md SS B4 L1061-1082): OWNED_ADMITTED (what this
    # factory produces) now requires training.optimizer_contract -- default one in so
    # every existing OWNED_ADMITTED-fixture consumer across this test corpus stays
    # green; tests that specifically exercise the omission/mutation battery delete or
    # mutate individual fields off this default (see test_optimizer_identity_roundtrip.py).
    payload["training"]["optimizer_contract"] = {
        "implementation": "bitsandbytes.optim.AdamW8bit",
        "hyperparameters": {"learning_rate": 1e-4, "weight_decay": 0.1},
        "state_format": "bitsandbytes-device-resident-8bit-adamw-state-dict-v1",
        "implementation_source_sha256": "d" * 64,
        "param_group_mapping_convention": "by-module-qualified-name",
        "param_name_optimizer_id_mapping_sha256": "e" * 64,
        "realization_receipt_sha256": "f" * 64,
        "trusted_verifier_id": "fixture-optimizer-realization-verifier",
    }
    return payload, receipts


def admission_artifacts() -> dict:
    raise AssertionError("call artifact_authority(payload) instead")


def artifact_authority(payload: dict, checkpoint_bytes: bytes = CHECKPOINT_BYTES) -> dict:
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    payload["architecture"]["sha256"] = digest(ARTIFACT_BYTES["architecture"])
    payload["tokenizer"]["sha256"] = digest(ARTIFACT_BYTES["tokenizer"])
    payload["data"]["sha256"] = digest(ARTIFACT_BYTES["data.corpus"])
    payload["data"]["ordering_sha256"] = digest(ARTIFACT_BYTES["data.ordering"])
    payload["data"]["curriculum_sha256"] = digest(ARTIFACT_BYTES["data.curriculum"])
    payload["data"]["accepted_input"]["shard_manifest_sha256"] = digest(
        ARTIFACT_BYTES["data.shard_manifest"]
    )
    payload["data"]["accepted_input"]["caller_sha256"] = digest(
        ARTIFACT_BYTES["data.input_caller"]
    )
    payload["data"]["accepted_input"]["gate_sha256"] = digest(
        ARTIFACT_BYTES["data.input_gate"]
    )
    payload["data"]["accepted_input"]["validator_sha256"] = digest(
        ARTIFACT_BYTES["data.input_validator"]
    )
    payload["training"]["optimizer_state_sha256"] = digest(
        ARTIFACT_BYTES["training.optimizer_state"]
    )
    payload["training"]["numerics"] = {
        "profile": "bf16-activations-fp32-master",
        "sha256": digest(ARTIFACT_BYTES["training.numerics"]),
    }
    payload["backend"]["executable_sha256"] = digest(
        ARTIFACT_BYTES["backend.executable"]
    )
    payload["checkpoint"]["ancestry"][0]["checkpoint_sha256"] = digest(
        ARTIFACT_BYTES["ancestry:0"]
    )
    tensor_sha = digest(ARTIFACT_BYTES["tensor:fixture.weight"])
    payload["checkpoint"]["tensors"][0]["sha256"] = tensor_sha
    tensor_manifest = {
        "schema": "ember-tensor-manifest-v1",
        "checkpoint_sha256": payload["checkpoint"]["byte_sha256"],
        "tensors": copy.deepcopy(payload["checkpoint"]["tensors"]),
    }
    artifact_bundle = {
        "schema": "ember-artifact-bundle-v1",
        "artifacts": {
            artifact_id: {
                "sha256": digest(content),
                "content_hex": content.hex(),
            }
            for artifact_id, content in ARTIFACT_BYTES.items()
        },
    }
    return {
        "checkpoint_bytes": checkpoint_bytes,
        "tensor_manifest": tensor_manifest,
        "artifact_bundle": artifact_bundle,
        "verifier_bytes": VERIFIER_BYTES,
    }


def rebind_receipt(
    payload: dict,
    bundle: dict[str, dict],
    old_digest: str,
    **changes: object,
) -> str:
    receipt = copy.deepcopy(bundle.pop(old_digest))
    receipt.pop("signature_ed25519", None)
    receipt.update(changes)
    sign_receipt(receipt)
    new_digest = receipt_sha256(receipt)
    bundle[new_digest] = receipt
    return new_digest


def test_json_schema_is_versioned_and_closed_world() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:ember:model-experiment-identity:v1"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(valid_manifest())
    assert schema["properties"]["schema"]["const"] == "ember-model-experiment-identity-v1"
    assert "anyOf" in schema["$defs"]["valueOrUnresolved"]
    assert {"model_id", "experiment_id", "run_id", "checkpoint_id", "disposition", "selected_as_owned_ember"} == set(
        schema["properties"]["identity"]["required"]
    )
    assert "recovery_state" in schema["properties"]["checkpoint"]["required"]
    assert {"temporary_adapters", "permanent_merges", "dreaming_updates"} <= set(
        schema["properties"]["mechanisms"]["required"]
    )


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


def test_historical_unknown_hashes_are_explicitly_unresolved() -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "HISTORICAL_ONLY"
    payload["data"]["ordering_sha256"] = {
        "status": "unresolved",
        "reason": "historical ordering implementation bytes were not preserved",
    }
    payload["unresolved"].append("data.ordering_sha256")

    validated = validate_manifest(copy.deepcopy(payload))
    assert validated["data"]["ordering_sha256"]["status"] == "unresolved"
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


def test_schema_requires_artifact_bound_accepted_training_input() -> None:
    payload = valid_manifest()
    payload["data"].pop("accepted_input", None)
    assert "schema.validation" in error_codes(payload)


def test_owned_admission_rejects_historical_training_input_authority() -> None:
    payload, receipts = admitted_manifest()
    payload["data"]["accepted_input"]["authority"] = "HISTORICAL_REFERENCE"
    assert "admission.training_input_authority" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_resolves_checkpoint_bound_training_input_forwarding() -> None:
    payload, receipts = admitted_manifest()
    payload["data"]["accepted_input"]["forwarding_receipt_sha256"] = "a" * 64
    assert "admission.receipt_missing" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_rejects_forwarding_receipt_for_another_shard() -> None:
    payload, receipts = admitted_manifest()
    old_digest = payload["data"]["accepted_input"]["forwarding_receipt_sha256"]
    receipt = copy.deepcopy(receipts.pop(old_digest))
    receipt.pop("signature_ed25519")
    receipt["shard_manifest_sha256"] = "9" * 64
    sign_receipt(receipt)
    new_digest = receipt_sha256(receipt)
    receipts[new_digest] = receipt
    payload["data"]["accepted_input"]["forwarding_receipt_sha256"] = new_digest
    assert "admission.receipt_claim_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_rejects_signed_but_unpinned_training_input_identity() -> None:
    payload, receipts = admitted_manifest()
    old_digest = payload["data"]["accepted_input"]["forwarding_receipt_sha256"]
    receipt = copy.deepcopy(receipts.pop(old_digest))
    receipt.pop("signature_ed25519")
    receipt["input_id"] = "unauthorized-training-input"
    payload["data"]["accepted_input"]["input_id"] = receipt["input_id"]
    sign_receipt(receipt)
    new_digest = receipt_sha256(receipt)
    receipts[new_digest] = receipt
    payload["data"]["accepted_input"]["forwarding_receipt_sha256"] = new_digest
    assert "admission.training_input_authority" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_rejects_modified_accepted_input_trust_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = json.loads(
        (
            ROOT
            / "manifests"
            / "ember-01-identity"
            / "accepted-training-input-authorities-v1.json"
        ).read_text(encoding="utf-8")
    )
    registry["active"]["body_sha256"] = "0" * 64
    modified = tmp_path / "accepted-training-input-authorities-v1.json"
    modified.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        identity_validator, "ACCEPTED_TRAINING_INPUT_AUTHORITIES_PATH", modified
    )
    payload, receipts = admitted_manifest()
    assert "admission.training_input_authority" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_requires_harness_and_comparator_bytes() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["artifact_bundle"]["artifacts"].pop("evaluation.harness")
    artifacts["artifact_bundle"]["artifacts"].pop("evaluation.comparator")
    assert {
        "admission.artifact_missing",
    } <= error_codes(payload, receipt_bundle=receipts, **artifacts)


@pytest.mark.parametrize(
    "disposition", ["OWNED_CANDIDATE", "HISTORICAL_ONLY", "REFERENCE_ONLY"]
)
def test_only_owned_admitted_can_be_selected_or_counted(disposition: str) -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = disposition
    payload["identity"]["selected_as_owned_ember"] = True
    payload["evaluation"]["counts_toward_owned_completion"] = True
    assert "admission.disposition" in error_codes(payload)


def test_historical_contaminated_identity_preserves_forbidden_signal() -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "HISTORICAL_ONLY"
    payload["provenance"]["ownership"] = "EXCLUDED_CONTAMINATED"
    payload["provenance"]["exclusion_reasons"] = [
        "training corpus includes externally model-filtered FineWeb-Edu records"
    ]
    payload["provenance"]["learned_signal_sources"] = [
        "owned_training_data",
        "filter",
    ]

    assert validate_manifest(payload) == payload


def test_contaminated_owned_candidate_still_fails_closed() -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "OWNED_CANDIDATE"
    payload["provenance"]["ownership"] = "EXCLUDED_CONTAMINATED"
    payload["provenance"]["exclusion_reasons"] = ["external learned filter"]
    payload["provenance"]["learned_signal_sources"] = [
        "owned_training_data",
        "filter",
    ]

    assert {
        "provenance.forbidden_learned_signal",
        "candidate.contaminated_provenance",
    } <= error_codes(payload)


def test_historical_contamination_requires_explicit_excluded_provenance() -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "HISTORICAL_ONLY"
    payload["provenance"]["learned_signal_sources"] = [
        "owned_training_data",
        "filter",
    ]

    assert "historical.contamination_unclassified" in error_codes(payload)


def test_reference_contamination_does_not_receive_historical_exemption() -> None:
    payload = valid_manifest()
    payload["identity"]["disposition"] = "REFERENCE_ONLY"
    payload["provenance"]["ownership"] = "REFERENCE_ONLY"
    payload["provenance"]["exclusion_reasons"] = [
        "filter is external learned evidence"
    ]
    payload["provenance"]["learned_signal_sources"] = [
        "owned_training_data",
        "filter",
    ]

    assert "provenance.forbidden_learned_signal" in error_codes(payload)


@pytest.mark.parametrize(
    ("path", "replacement", "expected_code"),
    [
        ("data.clean_genesis", False, "admission.clean_genesis"),
        ("provenance.ownership", "REFERENCE_ONLY", "admission.ownership"),
        ("parameters.trainable", 500_000_000, "admission.parameter_floor"),
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
    path: str, replacement: object, expected_code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(identity_validator, "OWNED_ADMISSION_PARAMETER_FLOOR", 3_000_000_000)
    payload, receipts = admitted_manifest()
    _set_path(payload, path, replacement)
    assert expected_code in error_codes(payload, receipt_bundle=receipts)


def test_owned_admission_rejects_any_unresolved_evidence() -> None:
    payload, receipts = admitted_manifest()
    payload["evaluation"]["score"] = {
        "status": "unresolved",
        "reason": "not measured",
    }
    payload["unresolved"] = ["evaluation.score"]
    assert "admission.unresolved" in error_codes(payload, receipt_bundle=receipts)


def test_fully_evidenced_owned_admission_passes() -> None:
    payload, receipts = admitted_manifest()
    assert validate_manifest(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    ) == payload


def test_owned_completion_admits_registry_member_benchmark() -> None:
    # cond6 clause-(a) POSITIVE: the canonical owned-admitted fixture evaluates
    # a frozen-registry member (terminal-bench-2.1); clause-(a) does not fire.
    payload, receipts = admitted_manifest()
    assert payload["evaluation"]["benchmark_id"] == "terminal-bench-2.1"
    # fully-evidenced fixture validates clean: no membership finding is raised.
    assert validate_manifest(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    ) == payload


def test_owned_completion_rejects_unregistered_benchmark_id() -> None:
    # cond6 clause-(a) NEGATIVE: an owned-admitted eval whose benchmark_id is
    # not a member of the frozen registry is fail-closed RED.
    payload, receipts = admitted_manifest()
    payload["evaluation"]["benchmark_id"] = "fabricated-bench"
    codes = error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )
    assert "evaluation.benchmark_id_unregistered" in codes


def test_owned_completion_fails_closed_when_registry_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # cond6 clause-(a) NEGATIVE: a missing / unreadable pinned registry does not
    # silently pass — it surfaces evaluation.benchmark_registry_unavailable.
    missing = tmp_path / "benchmark-registry.json"
    monkeypatch.setattr(identity_validator, "BENCHMARK_REGISTRY_PATH", missing)
    payload, receipts = admitted_manifest()
    codes = error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )
    assert "evaluation.benchmark_registry_unavailable" in codes


def test_owned_admission_rejects_process_executable_mismatch() -> None:
    payload, receipts = admitted_manifest()
    payload["backend"]["process_identity"]["executable_sha256"] = "4" * 64
    codes = error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )
    assert "admission.backend_process_executable_mismatch" in codes


def test_owned_admission_requires_backend_command_artifact() -> None:
    payload, receipts = admitted_manifest()
    authority = artifact_authority(payload)
    authority["artifact_bundle"]["artifacts"].pop("backend.command")
    codes = error_codes(payload, receipt_bundle=receipts, **authority)
    assert "admission.artifact_missing" in codes


def test_owned_admission_requires_backend_process_receipt() -> None:
    payload, receipts = admitted_manifest()
    receipts.pop(payload["backend"]["process_receipt_sha256"])
    codes = error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )
    assert "admission.receipt_missing" in codes


def test_owned_admission_resolves_evaluation_receipt_without_completion_credit() -> None:
    payload, receipts = admitted_manifest()
    payload["evaluation"]["counts_toward_owned_completion"] = False
    receipts.pop(payload["evaluation"]["receipt_sha256"])
    codes = error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )
    assert "admission.evaluation_receipt" in codes


def test_owned_completion_rejects_unresolved_evaluation_receipt() -> None:
    payload, receipts = admitted_manifest()
    receipts.pop(payload["evaluation"]["receipt_sha256"])
    codes = error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )
    assert "admission.evaluation_receipt" in codes


def test_owned_admission_requires_checkpoint_tensor_and_verifier_artifacts() -> None:
    payload, receipts = admitted_manifest()
    codes = error_codes(payload, receipt_bundle=receipts)
    assert {
        "admission.checkpoint_bytes_missing",
        "admission.tensor_manifest_missing",
        "admission.artifact_bundle_missing",
        "admission.verifier_authority_missing",
    } <= codes


def test_owned_admission_rejects_wrong_checkpoint_bytes() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["checkpoint_bytes"] = b"nonexistent fabricated checkpoint"
    assert "checkpoint.byte_hash_mismatch" in error_codes(
        payload,
        receipt_bundle=receipts,
        **artifacts,
    )


def test_owned_admission_rejects_unparseable_checkpoint_even_when_all_hashes_agree() -> None:
    unrelated_checkpoint = b"caller-controlled checkpoint bytes"
    payload, receipts = admitted_manifest(unrelated_checkpoint)
    artifacts = artifact_authority(payload)
    artifacts["checkpoint_bytes"] = unrelated_checkpoint
    assert "checkpoint.envelope_invalid" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


def test_owned_admission_rejects_wrong_tensor_hashes() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["tensor_manifest"]["tensors"][0]["sha256"] = "0" * 64
    assert "checkpoint.tensor_hash_mismatch" in error_codes(
        payload,
        receipt_bundle=receipts,
        **artifacts,
    )


def test_owned_admission_rejects_wrong_verifier_bytes() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["verifier_bytes"] = b"fabricated verifier"
    assert "admission.verifier_hash_mismatch" in error_codes(
        payload,
        receipt_bundle=receipts,
        **artifacts,
    )


def test_owned_admission_rejects_non_executable_verifier_bytes() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["verifier_bytes"] = b"caller-authored opaque verifier"
    assert "admission.verifier_program_invalid" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


def test_caller_created_verifier_registry_cannot_authorize_itself() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts.pop("verifier_bytes")
    registry = {
        "schema": "ember-trusted-verifier-registry-v1",
        "verifiers": [
            {"verifier_sha256": payload["data"]["verifier_sha256"], "public_key_ed25519": TEST_PUBLIC_KEY_HEX},
            {"verifier_sha256": "0" * 64, "public_key_ed25519": "0" * 64},
        ],
    }
    assert "admission.verifier_registry_untrusted_root" in error_codes(
        payload,
        receipt_bundle=receipts,
        trusted_verifier_registry=registry,
        **artifacts,
    )


def test_checked_in_verifier_registry_is_empty_until_operator_authorizes_a_signing_key() -> None:
    registry = json.loads(TRUSTED_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry == {
        "schema": "ember-trusted-verifier-registry-v1",
        "verifiers": [],
    }


def test_owned_admission_rejects_untrusted_verifier_registry() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts.pop("verifier_bytes")
    registry = {
        "schema": "ember-trusted-verifier-registry-v1",
        "verifiers": [{"verifier_sha256": "0" * 64, "public_key_ed25519": "0" * 64}],
    }
    assert "admission.verifier_registry_untrusted_root" in error_codes(
        payload,
        receipt_bundle=receipts,
        trusted_verifier_registry=registry,
        **artifacts,
    )


@pytest.mark.parametrize(
    "registry",
    [
        {"schema": "wrong", "verifier_sha256": []},
        {"schema": "ember-trusted-verifier-registry-v1", "verifier_sha256": "not-a-list"},
        {"schema": "ember-trusted-verifier-registry-v1", "verifier_sha256": ["not-a-hash"]},
        {"schema": "ember-trusted-verifier-registry-v1", "verifier_sha256": ["0" * 64, "0" * 64]},
        {"schema": "ember-trusted-verifier-registry-v1", "verifier_sha256": [], "extra": True},
    ],
)
def test_owned_admission_rejects_malformed_trusted_verifier_registry(registry: dict) -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts.pop("verifier_bytes")
    assert "admission.verifier_registry_invalid" in error_codes(
        payload,
        receipt_bundle=receipts,
        trusted_verifier_registry=registry,
        **artifacts,
    )


def test_owned_admission_resolves_mechanism_and_runtime_dependency_bytes() -> None:
    payload, receipts = admitted_manifest()
    mechanism_bytes = b"owned router module"
    dependency_bytes = b"owned runtime dependency"
    mechanism_sha = hashlib.sha256(mechanism_bytes).hexdigest()
    dependency_sha = hashlib.sha256(dependency_bytes).hexdigest()
    mechanism_receipt = {
        "schema": "ember-identity-evidence-receipt-v1",
        "evidence_class": "mechanism_router",
        "subject_checkpoint_sha256": payload["checkpoint"]["byte_sha256"],
        "verifier_sha256": payload["data"]["verifier_sha256"],
        "result": "VERIFIED",
        "mechanism_id": "router-v1",
        "mechanism_sha256": mechanism_sha,
    }
    sign_receipt(mechanism_receipt)
    mechanism_digest = receipt_sha256(mechanism_receipt)
    receipts[mechanism_digest] = mechanism_receipt
    payload["mechanisms"]["router"] = [{
        "id": "router-v1",
        "sha256": mechanism_sha,
        "state": "ACTIVE",
        "evidence_receipts": [mechanism_digest],
    }]
    payload["backend"]["runtime_dependencies"] = [
        {"name": "runtime-v1", "version": "1", "sha256": dependency_sha}
    ]
    artifacts = artifact_authority(payload)
    artifacts["artifact_bundle"]["artifacts"].update(
        {
            "mechanism:router:router-v1": {
                "sha256": mechanism_sha,
                "content_hex": mechanism_bytes.hex(),
            },
            "runtime_dependency:runtime-v1": {
                "sha256": dependency_sha,
                "content_hex": dependency_bytes.hex(),
            },
        }
    )
    assert validate_manifest(payload, receipt_bundle=receipts, **artifacts) == payload
    artifacts["artifact_bundle"]["artifacts"].pop("mechanism:router:router-v1")
    assert "admission.artifact_missing" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )
    payload, receipts = admitted_manifest()
    payload["mechanisms"]["router"] = [{
        "id": "router-v1",
        "sha256": mechanism_sha,
        "state": "ACTIVE",
        "evidence_receipts": [],
    }]
    artifacts = artifact_authority(payload)
    artifacts["artifact_bundle"]["artifacts"]["mechanism:router:router-v1"] = {
        "sha256": mechanism_sha,
        "content_hex": mechanism_bytes.hex(),
    }
    assert "admission.mechanism_evidence" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


def test_owned_admission_rejects_self_attested_parameter_axes() -> None:
    payload, receipts = admitted_manifest()
    payload["parameters"]["evidence_receipts"]["active"] = []
    assert "admission.parameter_evidence" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_rejects_parameter_receipt_with_wrong_count() -> None:
    payload, receipts = admitted_manifest()
    old = payload["parameters"]["evidence_receipts"]["actually_trained"][0]
    new = rebind_receipt(payload, receipts, old, claimed_count=2)
    payload["parameters"]["evidence_receipts"]["actually_trained"] = [new]
    assert "admission.receipt_claim_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_claimant_cannot_rehash_modified_receipt_without_verifier_signature() -> None:
    payload, receipts = admitted_manifest()
    old = payload["parameters"]["evidence_receipts"]["active"][0]
    receipt = receipts.pop(old)
    receipt["claimed_count"] = 2
    forged = receipt_sha256(receipt)
    receipts[forged] = receipt
    payload["parameters"]["evidence_receipts"]["active"] = [forged]
    assert "admission.receipt_signature_invalid" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_rejects_parameter_counts_not_derived_from_checkpoint_tensors() -> None:
    payload, receipts = admitted_manifest()
    for field in ("allocated", "unique"):
        payload["parameters"][field] = 2
        old = payload["parameters"]["evidence_receipts"][field][0]
        payload["parameters"]["evidence_receipts"][field] = [
            rebind_receipt(payload, receipts, old, claimed_count=2)
        ]
    assert "admission.checkpoint_parameter_count_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_checkpoint_envelope_rejects_tensor_bytes_inconsistent_with_shape_and_dtype() -> None:
    envelope = json.loads(CHECKPOINT_BYTES)
    envelope["tensors"][0]["shape"] = [2]
    malformed = json.dumps(
        envelope, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload, receipts = admitted_manifest(malformed)
    assert "checkpoint.envelope_invalid" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload, malformed)
    )


def test_owned_admission_rejects_deletion_object_without_erasure_evidence() -> None:
    payload, receipts = admitted_manifest()
    deletion_bytes = b"owned deletion object"
    deletion_sha = hashlib.sha256(deletion_bytes).hexdigest()
    receipt = {
        "schema": "ember-identity-evidence-receipt-v1",
        "evidence_class": "mechanism_deletion_objects",
        "subject_checkpoint_sha256": payload["checkpoint"]["byte_sha256"],
        "verifier_sha256": payload["data"]["verifier_sha256"],
        "result": "VERIFIED",
        "mechanism_id": "delete-router-v1",
        "mechanism_sha256": deletion_sha,
        "deletion_effect": "CAPABILITY_RETAINED",
    }
    sign_receipt(receipt)
    digest = receipt_sha256(receipt)
    receipts[digest] = receipt
    payload["mechanisms"]["deletion_objects"] = [{
        "id": "delete-router-v1",
        "sha256": deletion_sha,
        "state": "ACTIVE",
        "evidence_receipts": [digest],
    }]
    artifacts = artifact_authority(payload)
    artifacts["artifact_bundle"]["artifacts"][
        "mechanism:deletion_objects:delete-router-v1"
    ] = {"sha256": deletion_sha, "content_hex": deletion_bytes.hex()}
    assert "admission.receipt_claim_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


@pytest.mark.parametrize(
    ("artifact_id", "expected_code"),
    [
        ("architecture", "admission.artifact_missing"),
        ("tokenizer", "admission.artifact_missing"),
        ("data.corpus", "admission.artifact_missing"),
        ("data.ordering", "admission.artifact_missing"),
        ("data.curriculum", "admission.artifact_missing"),
        ("data.shard_manifest", "admission.artifact_missing"),
        ("data.input_caller", "admission.artifact_missing"),
        ("data.input_gate", "admission.artifact_missing"),
        ("data.input_validator", "admission.artifact_missing"),
        ("training.optimizer_state", "admission.artifact_missing"),
        ("training.numerics", "admission.artifact_missing"),
        ("backend.executable", "admission.artifact_missing"),
        ("evaluation.harness", "admission.artifact_missing"),
        ("evaluation.comparator", "admission.artifact_missing"),
        ("ancestry:0", "admission.artifact_missing"),
        ("tensor:fixture.weight", "admission.artifact_missing"),
    ],
)
def test_owned_admission_rejects_missing_required_artifact(
    artifact_id: str, expected_code: str
) -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["artifact_bundle"]["artifacts"].pop(artifact_id)
    assert expected_code in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


@pytest.mark.parametrize(
    "artifact_id",
    [
        "architecture",
        "tokenizer",
        "data.corpus",
        "data.ordering",
        "data.curriculum",
        "training.optimizer_state",
        "training.numerics",
        "backend.executable",
        "evaluation.harness",
        "evaluation.comparator",
        "ancestry:0",
        "tensor:fixture.weight",
    ],
)
def test_owned_admission_rejects_artifact_hash_content_mismatch(artifact_id: str) -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["artifact_bundle"]["artifacts"][artifact_id][
        "content_hex"
    ] = b"fabricated artifact bytes".hex()
    assert "admission.artifact_hash_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


def test_owned_admission_rejects_receipt_with_wrong_result() -> None:
    payload, receipts = admitted_manifest()
    digest = payload["capabilities"]["reasoning"]["evidence_receipts"][0]
    replacement = rebind_receipt(payload, receipts, digest, result="FAILED")
    payload["capabilities"]["reasoning"]["evidence_receipts"] = [replacement]
    assert "admission.receipt_result_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifact_authority(payload)
    )


def test_owned_admission_rejects_wrong_tensor_shape_or_dtype() -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    artifacts["tensor_manifest"]["tensors"][0]["shape"] = [999]
    assert "checkpoint.tensor_manifest_mismatch" in error_codes(
        payload, receipt_bundle=receipts, **artifacts
    )


@pytest.mark.parametrize(
    "path",
    [
        "provenance.learned_signal_sources",
        "provenance.neural_capability_credit_sources",
    ],
)
def test_malformed_admission_source_items_fail_without_crashing(path: str) -> None:
    payload, receipts = admitted_manifest()
    _set_path(payload, path, [{"renamed_external_source": "qwen"}])
    assert "schema.validation" in error_codes(payload, receipt_bundle=receipts)


def test_owned_admission_requires_nonzero_training_exposure_per_modality() -> None:
    payload, receipts = admitted_manifest()
    payload["training"]["modality_mixture"] = {
        "text": 0.75,
        "image": 0.0,
        "audio": 0.25,
    }
    assert "admission.modality_exposure" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_requires_checkpoint_bound_receipt_per_modality() -> None:
    payload, receipts = admitted_manifest()
    payload["capabilities"]["native_modalities"] = {
        "text": {"state": "VERIFIED", "evidence_receipts": ["a" * 64]},
        "image": {"state": "VERIFIED", "evidence_receipts": ["b" * 64]},
        "audio": {"state": "UNVERIFIED", "evidence_receipts": []},
    }
    assert "admission.native_modality_evidence" in error_codes(
        payload, receipt_bundle=receipts
    )


@pytest.mark.parametrize("result", ["NOT_REACHED", "FAILED"])
def test_owned_admission_requires_passed_sufficient_pretraining_receipt(
    result: str,
) -> None:
    payload, receipts = admitted_manifest()
    payload["training"]["stopping_rule"] = {
        "criterion_id": "sufficient-pretraining-v1",
        "result": result,
        "receipt_sha256": "c" * 64,
    }
    assert "admission.sufficient_pretraining" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_requires_receipt_bundle() -> None:
    payload, _ = admitted_manifest()
    assert "admission.receipt_bundle_missing" in error_codes(payload)


def test_owned_admission_rejects_non_object_receipt_bundle() -> None:
    payload, _ = admitted_manifest()
    assert "admission.receipt_bundle_invalid" in error_codes(
        payload, receipt_bundle=[]
    )


def test_owned_admission_rejects_missing_receipt_content() -> None:
    payload, receipts = admitted_manifest()
    digest = payload["capabilities"]["reasoning"]["evidence_receipts"][0]
    receipts.pop(digest)
    assert "admission.receipt_missing" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_rejects_receipt_for_wrong_checkpoint() -> None:
    payload, receipts = admitted_manifest()
    old = payload["capabilities"]["reasoning"]["evidence_receipts"][0]
    new = rebind_receipt(
        payload, receipts, old, subject_checkpoint_sha256="0" * 64
    )
    payload["capabilities"]["reasoning"]["evidence_receipts"] = [new]
    assert "admission.receipt_checkpoint_mismatch" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_rejects_wrong_evidence_class() -> None:
    payload, receipts = admitted_manifest()
    old = payload["capabilities"]["reasoning"]["evidence_receipts"][0]
    new = rebind_receipt(payload, receipts, old, evidence_class="native_text")
    payload["capabilities"]["reasoning"]["evidence_receipts"] = [new]
    assert "admission.receipt_class_mismatch" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_rejects_unbound_verifier() -> None:
    payload, receipts = admitted_manifest()
    old = payload["capabilities"]["reasoning"]["evidence_receipts"][0]
    new = rebind_receipt(payload, receipts, old, verifier_sha256="0" * 64)
    payload["capabilities"]["reasoning"]["evidence_receipts"] = [new]
    assert "admission.receipt_verifier_mismatch" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_rejects_unapproved_pretraining_criterion() -> None:
    payload, receipts = admitted_manifest()
    old = payload["training"]["stopping_rule"]["receipt_sha256"]
    new = rebind_receipt(
        payload, receipts, old, criterion_id="self-declared-good-enough"
    )
    payload["training"]["stopping_rule"]["criterion_id"] = "self-declared-good-enough"
    payload["training"]["stopping_rule"]["receipt_sha256"] = new
    assert "admission.sufficient_pretraining_criterion" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_owned_admission_rejects_fabricated_hash_content_pair() -> None:
    payload, receipts = admitted_manifest()
    digest = payload["capabilities"]["reasoning"]["evidence_receipts"][0]
    receipts[digest]["result"] = "FABRICATED"
    assert "admission.receipt_hash_mismatch" in error_codes(
        payload, receipt_bundle=receipts
    )


def test_cli_requires_and_resolves_admission_receipt_bundle(tmp_path: Path) -> None:
    payload, receipts = admitted_manifest()
    artifacts = artifact_authority(payload)
    manifest_path = tmp_path / "admitted.json"
    bundle_path = tmp_path / "receipts.json"
    checkpoint_path = tmp_path / "checkpoint.bin"
    tensor_path = tmp_path / "tensor-manifest.json"
    artifact_path = tmp_path / "artifact-bundle.json"
    verifier_path = tmp_path / "verifier.bin"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    bundle_path.write_text(json.dumps(receipts), encoding="utf-8")
    checkpoint_path.write_bytes(CHECKPOINT_BYTES)
    tensor_path.write_text(json.dumps(artifacts["tensor_manifest"]), encoding="utf-8")
    artifact_path.write_text(
        json.dumps(artifacts["artifact_bundle"]), encoding="utf-8"
    )
    verifier_path.write_bytes(VERIFIER_BYTES)

    missing = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "validate_identity.py"), str(manifest_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode == 1
    assert "admission.receipt_bundle_missing" in missing.stdout

    bundle_only = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "validate_identity.py"),
            str(manifest_path),
            "--receipt-bundle",
            str(bundle_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert bundle_only.returncode == 1
    assert "admission.checkpoint_bytes_missing" in bundle_only.stdout
    assert "admission.tensor_manifest_missing" in bundle_only.stdout
    assert "admission.artifact_bundle_missing" in bundle_only.stdout
    assert "admission.verifier_authority_missing" in bundle_only.stdout

    resolved = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "validate_identity.py"),
            str(manifest_path),
            "--receipt-bundle",
            str(bundle_path),
            "--checkpoint",
            str(checkpoint_path),
            "--tensor-manifest",
            str(tensor_path),
            "--artifact-bundle",
            str(artifact_path),
            "--verifier",
            str(verifier_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert resolved.returncode == 1
    assert "admission.verifier_untrusted" in resolved.stdout
    assert "admission.receipt_signature_invalid" in resolved.stdout
    assert json.loads(resolved.stdout)["ok"] is False
