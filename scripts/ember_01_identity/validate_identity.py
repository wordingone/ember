#!/usr/bin/env python3
# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate Ember model/experiment identity manifests without loading a model."""

from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only in a broken runtime
    Draft202012Validator = None  # type: ignore[assignment]


SCHEMA = "ember-model-experiment-identity-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "manifests"
    / "ember-01-identity"
    / "schema-v1.json"
)
TRUSTED_VERIFIER_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "manifests"
    / "ember-01-identity"
    / "trusted-verifiers-v1.json"
)
OWNED_ADMISSION_PARAMETER_FLOOR = 3_000_000_000
EVIDENCE_RECEIPT_SCHEMA = "ember-identity-evidence-receipt-v1"
SUFFICIENT_PRETRAINING_CRITERION = "ember-sufficient-pretraining-v1"
OWNED_LEARNED_SIGNAL_SOURCES = {
    "owned_training_data",
    "locally_verified_experience",
}
OWNED_CAPABILITY_CREDIT_SOURCES = {
    "owned_checkpoint",
    "checkpoint_bound_causal_evidence",
}

REQUIRED_PATHS = (
    "authority.goal_id",
    "authority.workstream_id",
    "authority.next_executed_outcome",
    "schema",
    "identity.model_id",
    "identity.experiment_id",
    "identity.disposition",
    "identity.selected_as_owned_ember",
    "architecture.source",
    "architecture.sha256",
    "checkpoint.format",
    "checkpoint.byte_sha256",
    "checkpoint.tensors",
    "checkpoint.ancestry",
    "tokenizer.id",
    "tokenizer.sha256",
    "data.corpus_id",
    "data.sha256",
    "data.ordering_sha256",
    "data.curriculum_sha256",
    "data.verifier_sha256",
    "data.clean_genesis",
    "parameters.allocated",
    "parameters.unique",
    "parameters.active",
    "parameters.trainable",
    "parameters.served",
    "parameters.actually_trained",
    "training.steps",
    "training.effective_tokens",
    "training.modality_mixture",
    "training.optimizer_state_sha256",
    "training.numerics",
    "training.stopping_rule",
    "capabilities.native_modalities",
    "capabilities.reasoning",
    "capabilities.structured_tool_use",
    "mechanisms.experts",
    "mechanisms.router",
    "mechanisms.memory_substrates",
    "mechanisms.world_models",
    "mechanisms.deletion_objects",
    "backend.executable_sha256",
    "backend.process_identity",
    "backend.protocol",
    "backend.device",
    "backend.runtime_dependencies",
    "backend.resource_lease_id",
    "evaluation.benchmark_id",
    "evaluation.version",
    "evaluation.split",
    "evaluation.harness_sha256",
    "evaluation.subject_checkpoint_sha256",
    "evaluation.comparator_identity",
    "evaluation.score",
    "evaluation.uncertainty",
    "evaluation.receipt_sha256",
    "evaluation.counts_toward_owned_completion",
    "provenance.ownership",
    "provenance.exclusion_reasons",
    "provenance.learned_signal_sources",
    "provenance.neural_capability_credit_sources",
    "unresolved",
)

HASH_PATHS = (
    "architecture.sha256",
    "checkpoint.byte_sha256",
    "tokenizer.sha256",
    "data.sha256",
    "data.ordering_sha256",
    "data.curriculum_sha256",
    "data.verifier_sha256",
    "training.optimizer_state_sha256",
    "backend.executable_sha256",
    "evaluation.harness_sha256",
    "evaluation.subject_checkpoint_sha256",
)

BINDING_PATHS = (
    "architecture",
    "architecture.sha256",
    "tokenizer",
    "tokenizer.sha256",
    "data",
    "data.sha256",
    "mechanisms",
    "mechanisms.router",
    "training.modality_mixture",
    "training.stopping_rule",
    "capabilities.native_modalities",
    "backend",
    "backend.executable_sha256",
    "evaluation.benchmark_id",
    "evaluation.version",
    "evaluation.split",
    "evaluation.harness_sha256",
    "evaluation.comparator_identity",
    "checkpoint.ancestry",
)

INVALID_CAPABILITY_CREDIT_SOURCES = {
    "borrowed_model",
    "harness",
    "human_intervention",
    "script",
    "search",
    "tool",
    "ui_label",
    "verifier",
}

FORBIDDEN_LEARNED_SIGNAL_SOURCES = {
    "weights",
    "outputs",
    "teachers",
    "judges",
    "filters",
    "ranks",
    "curricula",
    "stopping_decisions",
    "borrowed_weights",
    "borrowed_outputs",
    "teacher",
    "judge",
    "filter",
    "rank",
    "borrowed_curriculum",
    "borrowed_stopping_decision",
    "hidden_external_cognition",
}

CLOSED_OBJECT_KEYS: dict[str, set[str]] = {
    "": {
        "authority", "schema", "identity", "architecture", "checkpoint",
        "tokenizer", "data", "parameters", "training", "capabilities",
        "mechanisms", "backend", "evaluation", "provenance", "unresolved",
    },
    "authority": {"goal_id", "workstream_id", "next_executed_outcome"},
    "identity": {"model_id", "experiment_id", "run_id", "checkpoint_id", "disposition", "selected_as_owned_ember"},
    "architecture": {"source", "sha256"},
    "checkpoint": {"format", "byte_sha256", "tensors", "ancestry", "recovery_state"},
    "tokenizer": {"id", "sha256"},
    "data": {
        "corpus_id", "sha256", "ordering_sha256", "curriculum_sha256",
        "verifier_sha256", "clean_genesis",
    },
    "parameters": {"allocated", "unique", "active", "trainable", "served", "actually_trained", "evidence_receipts"},
    "parameters.evidence_receipts": {"allocated", "unique", "active", "trainable", "served", "actually_trained"},
    "training": {
        "steps", "effective_tokens", "modality_mixture", "optimizer_state_sha256",
        "numerics", "stopping_rule",
    },
    "training.modality_mixture": {"text", "image", "audio"},
    "training.stopping_rule": {"criterion_id", "result", "receipt_sha256"},
    "capabilities": {"native_modalities", "reasoning", "structured_tool_use"},
    "capabilities.native_modalities": {"text", "image", "audio"},
    "capabilities.native_modalities.text": {"state", "evidence_receipts"},
    "capabilities.native_modalities.image": {"state", "evidence_receipts"},
    "capabilities.native_modalities.audio": {"state", "evidence_receipts"},
    "capabilities.reasoning": {"state", "evidence_receipts"},
    "capabilities.structured_tool_use": {"state", "evidence_receipts"},
    "mechanisms": {"experts", "router", "temporary_adapters", "permanent_merges", "memory_substrates", "world_models", "dreaming_updates", "deletion_objects"},
    "backend": {
        "executable_sha256", "process_identity", "protocol", "device",
        "runtime_dependencies", "resource_lease_id",
    },
    "evaluation": {
        "benchmark_id", "version", "split", "harness_sha256",
        "subject_checkpoint_sha256", "comparator_identity", "score",
        "uncertainty", "receipt_sha256", "counts_toward_owned_completion",
    },
    "provenance": {
        "ownership", "exclusion_reasons", "learned_signal_sources",
        "neural_capability_credit_sources",
    },
}


class IdentityValidationError(ValueError):
    def __init__(self, findings: list[dict[str, str]]):
        self.findings = findings
        super().__init__("; ".join(f"{row['code']}: {row['detail']}" for row in findings))


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Return stable JSON without changing or filling any identity field."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _get(payload: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _finding(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


@functools.lru_cache(maxsize=1)
def _schema_validator() -> Any:
    if Draft202012Validator is None:
        raise RuntimeError("jsonschema Draft202012Validator is unavailable")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _apply_schema(
    payload: Mapping[str, Any], findings: list[dict[str, str]]
) -> None:
    try:
        errors = sorted(
            _schema_validator().iter_errors(payload),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                error.message,
            ),
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        findings.append(
            _finding("schema.authority_unavailable", type(exc).__name__)
        )
        return
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        findings.append(_finding("schema.validation", f"{path}: {error.message}"))


def _is_unresolved(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("status") == "unresolved"


def _string_list_subset(value: Any, allowed: set[str]) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) for item in value)
        and set(value) <= allowed
    )


def _verified_receipt_evidence(value: Any) -> bool:
    receipts = value.get("evidence_receipts") if isinstance(value, Mapping) else None
    return (
        isinstance(value, Mapping)
        and value.get("state") == "VERIFIED"
        and isinstance(receipts, list)
        and bool(receipts)
        and all(
            isinstance(receipt, str) and bool(SHA256_RE.fullmatch(receipt))
            for receipt in receipts
        )
    )


def _receipt_sha256(receipt: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_admission_receipt(
    digest: Any,
    *,
    receipt_bundle: Mapping[str, Any] | None,
    expected_class: str,
    expected_checkpoint: Any,
    expected_verifier: Any,
    findings: list[dict[str, str]],
    expected_result: str = "VERIFIED",
    expected_criterion: str | None = None,
    expected_claims: Mapping[str, Any] | None = None,
) -> None:
    if receipt_bundle is None:
        return
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        findings.append(_finding("admission.receipt_hash_invalid", expected_class))
        return
    receipt = receipt_bundle.get(digest)
    if not isinstance(receipt, Mapping):
        findings.append(_finding("admission.receipt_missing", digest))
        return
    if _receipt_sha256(receipt) != digest:
        findings.append(_finding("admission.receipt_hash_mismatch", digest))

    required = {
        "schema",
        "evidence_class",
        "subject_checkpoint_sha256",
        "verifier_sha256",
        "result",
    }
    if expected_criterion is not None:
        required.add("criterion_id")
    if expected_claims is not None:
        required.update(expected_claims)
    if set(receipt) != required:
        findings.append(_finding("admission.receipt_shape", expected_class))
    if receipt.get("schema") != EVIDENCE_RECEIPT_SCHEMA:
        findings.append(_finding("admission.receipt_schema", expected_class))
    if receipt.get("evidence_class") != expected_class:
        findings.append(_finding("admission.receipt_class_mismatch", expected_class))
    if receipt.get("subject_checkpoint_sha256") != expected_checkpoint:
        findings.append(
            _finding("admission.receipt_checkpoint_mismatch", expected_class)
        )
    if receipt.get("verifier_sha256") != expected_verifier:
        findings.append(
            _finding("admission.receipt_verifier_mismatch", expected_class)
        )
    if receipt.get("result") != expected_result:
        findings.append(_finding("admission.receipt_result_mismatch", expected_class))
    if (
        expected_criterion is not None
        and receipt.get("criterion_id") != expected_criterion
    ):
        findings.append(
            _finding(
                "admission.sufficient_pretraining_criterion",
                str(receipt.get("criterion_id")),
            )
        )
    if expected_claims is not None:
        for key, expected_value in expected_claims.items():
            if receipt.get(key) != expected_value:
                findings.append(
                    _finding("admission.receipt_claim_mismatch", f"{expected_class}.{key}")
                )


def _check_closed_objects(
    payload: Mapping[str, Any], findings: list[dict[str, str]]
) -> None:
    for path, allowed in CLOSED_OBJECT_KEYS.items():
        if path:
            present, value = _get(payload, path)
            if not present or not isinstance(value, Mapping):
                continue
        else:
            value = payload
        for unknown in sorted(set(value) - allowed):
            location = f"{path}.{unknown}" if path else unknown
            findings.append(_finding("field.unknown", location))


def _unresolved_paths(value: Any, path: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(value, Mapping):
        if value.get("status") == "unresolved":
            reason = value.get("reason")
            if isinstance(reason, str) and reason.strip():
                found[path] = reason.strip()
            else:
                found[path] = ""
            return found
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            found.update(_unresolved_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(_unresolved_paths(child, f"{path}[{index}]"))
    return found


def validate_manifest(
    payload: Mapping[str, Any],
    *,
    checkpoint_bytes: bytes | None = None,
    tensor_hashes: Mapping[str, str] | None = None,
    tensor_manifest: Mapping[str, Any] | None = None,
    artifact_bundle: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any] | None = None,
    receipt_bundle: Mapping[str, Any] | None = None,
    verifier_bytes: bytes | None = None,
    trusted_verifier_registry: Mapping[str, Any] | None = None,
    require_resolved: bool = False,
) -> dict[str, Any]:
    """Validate one manifest and return a deep copy on success.

    Validation never derives identity from filenames, labels, endpoint defaults, or
    checkpoint shapes. Unknown values must be explicit unresolved objects.
    """
    if not isinstance(payload, Mapping):
        raise IdentityValidationError([_finding("manifest.not_object", "top level must be an object")])

    findings: list[dict[str, str]] = []

    _apply_schema(payload, findings)
    _check_closed_objects(payload, findings)

    if payload.get("schema") != SCHEMA:
        findings.append(_finding("schema.unsupported", f"expected {SCHEMA!r}"))

    for path in REQUIRED_PATHS:
        present, _ = _get(payload, path)
        if not present:
            findings.append(_finding("field.missing", path))

    for path in HASH_PATHS:
        present, value = _get(payload, path)
        if present and not (isinstance(value, str) and SHA256_RE.fullmatch(value)):
            findings.append(_finding("hash.invalid", path))

    present, tensors = _get(payload, "checkpoint.tensors")
    if present:
        if not isinstance(tensors, list) or not tensors:
            findings.append(_finding("checkpoint.tensors_invalid", "must contain at least one tensor"))
        else:
            seen: set[str] = set()
            for index, tensor in enumerate(tensors):
                prefix = f"checkpoint.tensors[{index}]"
                if not isinstance(tensor, Mapping):
                    findings.append(_finding("checkpoint.tensor_invalid", prefix))
                    continue
                for unknown in sorted(set(tensor) - {"name", "shape", "dtype", "sha256"}):
                    findings.append(_finding("field.unknown", f"{prefix}.{unknown}"))
                for field in ("name", "shape", "dtype", "sha256"):
                    if field not in tensor:
                        findings.append(_finding("field.missing", f"{prefix}.{field}"))
                name = tensor.get("name")
                if not isinstance(name, str) or not name or name in seen:
                    findings.append(_finding("checkpoint.tensor_name_invalid", prefix))
                else:
                    seen.add(name)
                tensor_sha = tensor.get("sha256")
                if not isinstance(tensor_sha, str) or not SHA256_RE.fullmatch(tensor_sha):
                    findings.append(_finding("hash.invalid", f"{prefix}.sha256"))

    ancestry_present, ancestry = _get(payload, "checkpoint.ancestry")
    if ancestry_present:
        if not isinstance(ancestry, list):
            findings.append(_finding("checkpoint.ancestry_invalid", "must be a list"))
            ancestry = []
        for index, row in enumerate(ancestry):
            prefix = f"checkpoint.ancestry[{index}]"
            if not isinstance(row, Mapping):
                findings.append(_finding("checkpoint.ancestry_invalid", prefix))
                continue
            if set(row) != {"checkpoint_sha256", "relationship"}:
                findings.append(_finding("checkpoint.ancestry_invalid", prefix))
            parent_sha = row.get("checkpoint_sha256")
            if not isinstance(parent_sha, str) or not SHA256_RE.fullmatch(parent_sha):
                findings.append(_finding("hash.invalid", f"{prefix}.checkpoint_sha256"))

    checkpoint_present, checkpoint_hash = _get(payload, "checkpoint.byte_sha256")
    parsed_checkpoint_tensors: list[dict[str, Any]] | None = None
    if checkpoint_bytes is not None and checkpoint_present:
        actual = hashlib.sha256(checkpoint_bytes).hexdigest()
        if checkpoint_hash != actual:
            findings.append(
                _finding(
                    "checkpoint.byte_hash_mismatch",
                    f"manifest={checkpoint_hash}; actual={actual}",
                )
            )
        if _get(payload, "checkpoint.format")[1] == "ember-checkpoint-envelope-v1":
            try:
                envelope = json.loads(checkpoint_bytes.decode("utf-8"))
                if (
                    not isinstance(envelope, Mapping)
                    or set(envelope) != {"schema", "tensors"}
                    or envelope.get("schema") != "ember-checkpoint-envelope-v1"
                    or not isinstance(envelope.get("tensors"), list)
                    or not envelope["tensors"]
                ):
                    raise ValueError("closed checkpoint envelope required")
                parsed_checkpoint_tensors = []
                seen_checkpoint_names: set[str] = set()
                for row in envelope["tensors"]:
                    if (
                        not isinstance(row, Mapping)
                        or set(row) != {"name", "shape", "dtype", "content_hex"}
                        or not isinstance(row.get("name"), str)
                        or not row["name"]
                        or row["name"] in seen_checkpoint_names
                        or not isinstance(row.get("shape"), list)
                        or not row["shape"]
                        or any(
                            not isinstance(dimension, int)
                            or isinstance(dimension, bool)
                            or dimension <= 0
                            for dimension in row["shape"]
                        )
                        or not isinstance(row.get("dtype"), str)
                        or not row["dtype"]
                        or not isinstance(row.get("content_hex"), str)
                    ):
                        raise ValueError("invalid checkpoint tensor entry")
                    tensor_bytes = bytes.fromhex(row["content_hex"])
                    element_count = math.prod(row["shape"])
                    dtype = row["dtype"]
                    scalar_widths = {
                        "float32": 4,
                        "float16": 2,
                        "bfloat16": 2,
                        "int8": 1,
                        "uint8": 1,
                    }
                    if dtype == "constant_float32":
                        if len(tensor_bytes) != 4:
                            raise ValueError("constant tensor requires one float32 value")
                    elif dtype in scalar_widths:
                        if len(tensor_bytes) != element_count * scalar_widths[dtype]:
                            raise ValueError("tensor byte length does not match shape and dtype")
                    else:
                        raise ValueError("unsupported checkpoint tensor dtype")
                    seen_checkpoint_names.add(row["name"])
                    parsed_checkpoint_tensors.append(
                        {
                            "name": row["name"],
                            "shape": list(row["shape"]),
                            "dtype": row["dtype"],
                            "sha256": hashlib.sha256(tensor_bytes).hexdigest(),
                        }
                    )
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                parsed_checkpoint_tensors = None
                findings.append(
                    _finding(
                        "checkpoint.envelope_invalid",
                        "checkpoint bytes do not resolve the declared tensor envelope",
                    )
                )
            else:
                if parsed_checkpoint_tensors != tensors:
                    findings.append(
                        _finding(
                            "checkpoint.envelope_tensor_mismatch",
                            "checkpoint-derived tensors do not match manifest tensors",
                        )
                    )

    if tensor_hashes is not None and isinstance(tensors, list):
        declared = {
            tensor.get("name"): tensor.get("sha256")
            for tensor in tensors
            if isinstance(tensor, Mapping) and isinstance(tensor.get("name"), str)
        }
        for name in sorted(set(declared) | set(tensor_hashes)):
            if declared.get(name) != tensor_hashes.get(name):
                findings.append(_finding("checkpoint.tensor_hash_mismatch", str(name)))

    if tensor_manifest is not None:
        valid_tensor_manifest = (
            isinstance(tensor_manifest, Mapping)
            and set(tensor_manifest) == {"schema", "checkpoint_sha256", "tensors"}
            and tensor_manifest.get("schema") == "ember-tensor-manifest-v1"
            and tensor_manifest.get("checkpoint_sha256") == checkpoint_hash
            and tensor_manifest.get("tensors") == tensors
        )
        if not valid_tensor_manifest:
            manifest_tensors = tensor_manifest.get("tensors") if isinstance(tensor_manifest, Mapping) else None
            declared_by_name = {
                row.get("name"): row.get("sha256") for row in tensors or []
                if isinstance(row, Mapping)
            }
            supplied_by_name = {
                row.get("name"): row.get("sha256") for row in manifest_tensors or []
                if isinstance(row, Mapping)
            }
            code = "checkpoint.tensor_hash_mismatch" if declared_by_name != supplied_by_name else "checkpoint.tensor_manifest_mismatch"
            findings.append(_finding(code, "tensor manifest does not exactly match checkpoint identity"))
        elif parsed_checkpoint_tensors is not None and tensor_manifest.get("tensors") != parsed_checkpoint_tensors:
            findings.append(
                _finding(
                    "checkpoint.tensor_manifest_not_in_checkpoint",
                    "tensor manifest was not derived from checkpoint bytes",
                )
            )

    counts_present, counts = _get(payload, "parameters")
    if counts_present and isinstance(counts, Mapping):
        names = ("allocated", "unique", "active", "trainable", "served", "actually_trained")
        numeric = {
            name: counts.get(name)
            for name in names
            if isinstance(counts.get(name), int) and not isinstance(counts.get(name), bool)
        }
        for name in names:
            value = counts.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                findings.append(_finding("parameters.invalid", name))
        if len(numeric) == len(names):
            allocated = numeric["allocated"]
            unique = numeric["unique"]
            if unique > allocated or any(
                numeric[name] > unique
                for name in ("active", "trainable", "served", "actually_trained")
            ):
                findings.append(_finding("parameters.contradictory", json.dumps(numeric, sort_keys=True)))

    mixture_present, mixture = _get(payload, "training.modality_mixture")
    if mixture_present:
        required_modalities = {"text", "image", "audio"}
        if not isinstance(mixture, Mapping) or set(mixture) != required_modalities:
            findings.append(_finding("training.modality_mixture_invalid", "requires exact text/image/audio keys"))
        elif any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value < 0
            for value in mixture.values()
        ):
            findings.append(_finding("training.modality_mixture_invalid", "weights must be non-negative numbers"))
        elif abs(sum(float(value) for value in mixture.values()) - 1.0) > 1e-9:
            findings.append(_finding("training.modality_mixture_invalid", "weights must sum to one"))

    native_present, native = _get(payload, "capabilities.native_modalities")
    if native_present:
        valid_native = (
            isinstance(native, Mapping)
            and set(native) == {"text", "image", "audio"}
            and all(
                isinstance(native.get(modality), Mapping)
                and set(native[modality]) == {"state", "evidence_receipts"}
                for modality in ("text", "image", "audio")
            )
        )
        if not valid_native:
            findings.append(
                _finding(
                    "capabilities.native_modalities_invalid",
                    "requires exact text/image/audio evidence objects",
                )
            )

    for capability_name in ("reasoning", "structured_tool_use"):
        present, capability = _get(payload, f"capabilities.{capability_name}")
        if not present or not isinstance(capability, Mapping):
            continue
        receipts = capability.get("evidence_receipts")
        if capability.get("state") == "VERIFIED" and (
            not isinstance(receipts, list) or not receipts
        ):
            findings.append(
                _finding(
                    "capability.evidence_missing",
                    f"{capability_name} is VERIFIED without checkpoint-bound receipts",
                )
            )
        if isinstance(receipts, list):
            for receipt in receipts:
                if not isinstance(receipt, str) or not SHA256_RE.fullmatch(receipt):
                    findings.append(
                        _finding("capability.receipt_hash_invalid", capability_name)
                )

    process_present, process_identity = _get(payload, "backend.process_identity")
    if process_present and not _is_unresolved(process_identity):
        required_process = {
            "pid", "start_time_utc", "executable_sha256", "command_sha256", "nonce"
        }
        valid_process = (
            isinstance(process_identity, Mapping)
            and set(process_identity) == required_process
            and isinstance(process_identity.get("pid"), int)
            and process_identity.get("pid", 0) > 0
            and isinstance(process_identity.get("start_time_utc"), str)
            and bool(process_identity.get("start_time_utc"))
            and isinstance(process_identity.get("nonce"), str)
            and bool(process_identity.get("nonce"))
            and all(
                isinstance(process_identity.get(field), str)
                and bool(SHA256_RE.fullmatch(process_identity[field]))
                for field in ("executable_sha256", "command_sha256")
            )
        )
        if not valid_process:
            findings.append(_finding("backend.process_identity_invalid", "backend.process_identity"))

    deps_present, dependencies = _get(payload, "backend.runtime_dependencies")
    if deps_present:
        if not isinstance(dependencies, list):
            findings.append(_finding("backend.runtime_dependency_invalid", "must be a list"))
        else:
            for index, dependency in enumerate(dependencies):
                valid_dependency = (
                    isinstance(dependency, Mapping)
                    and set(dependency) == {"name", "version", "sha256"}
                    and isinstance(dependency.get("name"), str)
                    and bool(dependency.get("name"))
                    and isinstance(dependency.get("version"), str)
                    and bool(dependency.get("version"))
                    and isinstance(dependency.get("sha256"), str)
                    and bool(SHA256_RE.fullmatch(dependency["sha256"]))
                )
                if not valid_dependency:
                    findings.append(
                        _finding("backend.runtime_dependency_invalid", str(index))
                    )

    mechanism_groups = (
        "experts", "router", "temporary_adapters", "permanent_merges",
        "memory_substrates", "world_models", "dreaming_updates", "deletion_objects"
    )
    for group in mechanism_groups:
        present, items = _get(payload, f"mechanisms.{group}")
        if not present or not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if _is_unresolved(item):
                continue
            valid_item = (
                isinstance(item, Mapping)
                and set(item) == {"id", "sha256", "state", "evidence_receipts"}
                and isinstance(item.get("id"), str)
                and bool(item.get("id"))
                and isinstance(item.get("sha256"), str)
                and bool(SHA256_RE.fullmatch(item["sha256"]))
                and item.get("state") in {"ACTIVE", "INACTIVE", "HISTORICAL", "UNVERIFIED"}
                and isinstance(item.get("evidence_receipts"), list)
                and all(
                    isinstance(receipt, str) and bool(SHA256_RE.fullmatch(receipt))
                    for receipt in item["evidence_receipts"]
                )
            )
            if not valid_item:
                findings.append(
                    _finding("mechanism.identity_invalid", f"{group}[{index}]")
                )

    subject_present, subject_hash = _get(payload, "evaluation.subject_checkpoint_sha256")
    if checkpoint_present and subject_present and subject_hash != checkpoint_hash:
        findings.append(_finding("evaluation.subject_checkpoint_mismatch", "evaluation subject is not checkpoint bytes"))

    disposition = _get(payload, "identity.disposition")[1]
    selected = _get(payload, "identity.selected_as_owned_ember")[1]
    completion_credit = _get(payload, "evaluation.counts_toward_owned_completion")[1]
    if disposition == "OWNED_ADMITTED" and parsed_checkpoint_tensors is not None:
        checkpoint_parameter_count = sum(
            math.prod(row["shape"]) for row in parsed_checkpoint_tensors
        )
        parameters = payload.get("parameters")
        if not isinstance(parameters, Mapping) or any(
            parameters.get(field) != checkpoint_parameter_count
            for field in ("allocated", "unique")
        ):
            findings.append(
                _finding(
                    "admission.checkpoint_parameter_count_mismatch",
                    str(checkpoint_parameter_count),
                )
            )
    if disposition == "OWNED_ADMITTED" and completion_credit is True:
        evaluation = payload.get("evaluation")
        if not isinstance(evaluation, Mapping):
            findings.append(_finding("admission.evaluation_receipt", "evaluation object missing"))
        else:
            digest = evaluation.get("receipt_sha256")
            if not isinstance(receipt_bundle, Mapping) or digest not in receipt_bundle:
                findings.append(_finding("admission.evaluation_receipt", str(digest)))
            if isinstance(receipt_bundle, Mapping):
                _resolve_admission_receipt(
                    digest,
                    receipt_bundle=receipt_bundle,
                    expected_class="evaluation_result",
                    expected_checkpoint=checkpoint_hash,
                    expected_verifier=_get(payload, "data.verifier_sha256")[1],
                    expected_result="VERIFIED",
                    expected_claims={
                        field: evaluation.get(field)
                        for field in (
                            "benchmark_id", "version", "split", "harness_sha256",
                            "comparator_identity", "score", "uncertainty",
                            "counts_toward_owned_completion",
                        )
                    },
                    findings=findings,
                )
    if (selected is True or completion_credit is True) and disposition != "OWNED_ADMITTED":
        findings.append(
            _finding(
                "admission.disposition",
                "owned selection/completion requires OWNED_ADMITTED",
            )
        )
    if disposition == "REFERENCE_ONLY":
        if selected is True:
            findings.append(_finding("reference.selected_as_owned", "reference cannot be owned Ember"))
        if completion_credit is True:
            findings.append(_finding("reference.owned_completion_credit", "reference cannot increment owned completion"))

    present, credit_sources = _get(payload, "provenance.neural_capability_credit_sources")
    if present and isinstance(credit_sources, list):
        invalid = sorted(set(str(item) for item in credit_sources) & INVALID_CAPABILITY_CREDIT_SOURCES)
        if invalid:
            findings.append(_finding("capability.invalid_credit_source", ",".join(invalid)))

    present, learned_sources = _get(payload, "provenance.learned_signal_sources")
    if present and isinstance(learned_sources, list):
        invalid = sorted(set(str(item) for item in learned_sources) & FORBIDDEN_LEARNED_SIGNAL_SOURCES)
        if invalid:
            findings.append(_finding("provenance.forbidden_learned_signal", ",".join(invalid)))

    unresolved = _unresolved_paths(payload)
    declared_unresolved = payload.get("unresolved")
    if unresolved and any(not reason for reason in unresolved.values()):
        findings.append(_finding("unresolved.reason_missing", "every unresolved value needs a reason"))
    if isinstance(declared_unresolved, list):
        if set(declared_unresolved) != set(unresolved):
            findings.append(
                _finding(
                    "unresolved.index_mismatch",
                    f"declared={sorted(map(str, declared_unresolved))}; actual={sorted(unresolved)}",
                )
            )
    if require_resolved:
        for path in sorted(unresolved):
            findings.append(_finding("field.unresolved", path))

    if disposition == "OWNED_ADMITTED":
        if _get(payload, "checkpoint.format")[1] != "ember-checkpoint-envelope-v1":
            findings.append(
                _finding(
                    "admission.checkpoint_format_unsupported",
                    "OWNED_ADMITTED requires a parseable Ember checkpoint envelope",
                )
            )
        if checkpoint_bytes is None:
            findings.append(
                _finding(
                    "admission.checkpoint_bytes_missing",
                    "OWNED_ADMITTED requires actual checkpoint bytes",
                )
            )
        if tensor_manifest is None:
            findings.append(
                _finding(
                    "admission.tensor_manifest_missing",
                    "OWNED_ADMITTED requires an independently resolved tensor manifest",
                )
            )
        if artifact_bundle is None:
            findings.append(_finding("admission.artifact_bundle_missing", "OWNED_ADMITTED requires content-addressed artifact bytes"))
        elif not (
            isinstance(artifact_bundle, Mapping)
            and set(artifact_bundle) == {"schema", "artifacts"}
            and artifact_bundle.get("schema") == "ember-artifact-bundle-v1"
            and isinstance(artifact_bundle.get("artifacts"), Mapping)
        ):
            findings.append(_finding("admission.artifact_bundle_invalid", "invalid artifact bundle"))
        else:
            required_artifacts: dict[str, Any] = {
                "architecture": _get(payload, "architecture.sha256")[1],
                "tokenizer": _get(payload, "tokenizer.sha256")[1],
                "data.corpus": _get(payload, "data.sha256")[1],
                "data.ordering": _get(payload, "data.ordering_sha256")[1],
                "data.curriculum": _get(payload, "data.curriculum_sha256")[1],
                "training.optimizer_state": _get(payload, "training.optimizer_state_sha256")[1],
                "training.numerics": _get(payload, "training.numerics.sha256")[1],
                "backend.executable": _get(payload, "backend.executable_sha256")[1],
            }
            for index, row in enumerate(ancestry or []):
                if isinstance(row, Mapping):
                    required_artifacts[f"ancestry:{index}"] = row.get("checkpoint_sha256")
            for row in tensors or []:
                if isinstance(row, Mapping):
                    required_artifacts[f"tensor:{row.get('name')}"] = row.get("sha256")
            for group in mechanism_groups:
                for row in _get(payload, f"mechanisms.{group}")[1] or []:
                    if isinstance(row, Mapping) and not _is_unresolved(row):
                        required_artifacts[f"mechanism:{group}:{row.get('id')}"] = row.get("sha256")
            for row in dependencies or []:
                if isinstance(row, Mapping):
                    required_artifacts[f"runtime_dependency:{row.get('name')}"] = row.get("sha256")
            supplied_artifacts = artifact_bundle["artifacts"]
            for artifact_id, expected_sha in required_artifacts.items():
                entry = supplied_artifacts.get(artifact_id)
                if not isinstance(entry, Mapping):
                    findings.append(_finding("admission.artifact_missing", artifact_id))
                    continue
                valid_entry = set(entry) == {"sha256", "content_hex"}
                try:
                    content = bytes.fromhex(entry.get("content_hex", "")) if valid_entry else b""
                except (TypeError, ValueError):
                    content = b""
                    valid_entry = False
                actual_sha = hashlib.sha256(content).hexdigest()
                if not valid_entry or entry.get("sha256") != expected_sha or actual_sha != expected_sha:
                    findings.append(_finding("admission.artifact_hash_mismatch", artifact_id))
        declared_verifier = _get(payload, "data.verifier_sha256")[1]
        if verifier_bytes is not None:
            actual_verifier = hashlib.sha256(verifier_bytes).hexdigest()
            if actual_verifier != declared_verifier:
                findings.append(
                    _finding(
                        "admission.verifier_hash_mismatch",
                        f"manifest={declared_verifier}; actual={actual_verifier}",
                    )
                )
            try:
                verifier_program = json.loads(verifier_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                verifier_program = None
            required_program = {
                "schema": "ember-admission-verifier-program-v1",
                "rules": [
                    "bind_checkpoint",
                    "bind_claims",
                    "derive_allocated_unique",
                    "require_verified_result",
                ],
            }
            if verifier_program != required_program:
                findings.append(
                    _finding(
                        "admission.verifier_program_invalid",
                        "verifier bytes do not encode the closed admission program",
                    )
                )
            try:
                pinned_registry = json.loads(
                    TRUSTED_VERIFIER_REGISTRY_PATH.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                pinned_registry = None
            pinned_hashes = (
                pinned_registry.get("verifier_sha256", [])
                if isinstance(pinned_registry, Mapping)
                else []
            )
            if actual_verifier not in pinned_hashes:
                findings.append(
                    _finding("admission.verifier_untrusted", actual_verifier)
                )
        elif trusted_verifier_registry is not None:
            registry_valid = (
                isinstance(trusted_verifier_registry, Mapping)
                and set(trusted_verifier_registry)
                == {"schema", "verifier_sha256"}
                and trusted_verifier_registry.get("schema")
                == "ember-trusted-verifier-registry-v1"
                and isinstance(
                    trusted_verifier_registry.get("verifier_sha256"), list
                )
                and all(
                    isinstance(item, str) and bool(SHA256_RE.fullmatch(item))
                    for item in trusted_verifier_registry["verifier_sha256"]
                )
                and len(set(trusted_verifier_registry["verifier_sha256"]))
                == len(trusted_verifier_registry["verifier_sha256"])
            )
            if not registry_valid:
                findings.append(
                    _finding(
                        "admission.verifier_registry_invalid",
                        "trusted verifier registry has invalid schema or entries",
                    )
                )
            else:
                try:
                    pinned_registry = json.loads(
                        TRUSTED_VERIFIER_REGISTRY_PATH.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    pinned_registry = None
                supplied_canonical = json.dumps(
                    trusted_verifier_registry,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                pinned_canonical = (
                    json.dumps(
                        pinned_registry,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    if isinstance(pinned_registry, Mapping)
                    else None
                )
                if supplied_canonical != pinned_canonical:
                    findings.append(
                        _finding(
                            "admission.verifier_registry_untrusted_root",
                            "supplied registry does not match the checked-in trust root",
                        )
                    )
                elif declared_verifier not in trusted_verifier_registry[
                "verifier_sha256"
                ]:
                    findings.append(
                        _finding(
                            "admission.verifier_untrusted",
                            str(declared_verifier),
                        )
                    )
        else:
            findings.append(
                _finding(
                    "admission.verifier_authority_missing",
                    "OWNED_ADMITTED requires verifier bytes or trusted registry",
                )
            )
        if receipt_bundle is None:
            findings.append(
                _finding(
                    "admission.receipt_bundle_missing",
                    "OWNED_ADMITTED requires resolved receipt content",
                )
            )
        elif not isinstance(receipt_bundle, Mapping):
            findings.append(
                _finding(
                    "admission.receipt_bundle_invalid",
                    "receipt bundle must be a digest-to-object mapping",
                )
            )
        if _get(payload, "data.clean_genesis")[1] is not True:
            findings.append(
                _finding("admission.clean_genesis", "OWNED_ADMITTED requires clean genesis")
            )
        ownership = _get(payload, "provenance.ownership")[1]
        if ownership != "OWNED_CLEAN_GENESIS":
            findings.append(
                _finding("admission.ownership", "OWNED_ADMITTED requires owned provenance")
            )
        admitted_counts = _get(payload, "parameters")[1]
        floor_fields = (
            "allocated",
            "unique",
            "active",
            "trainable",
            "served",
            "actually_trained",
        )
        if not isinstance(admitted_counts, Mapping) or any(
            not isinstance(admitted_counts.get(field), int)
            or isinstance(admitted_counts.get(field), bool)
            or admitted_counts[field] < OWNED_ADMISSION_PARAMETER_FLOOR
            for field in floor_fields
        ):
            findings.append(
                _finding(
                    "admission.parameter_floor",
                    "allocated/unique/active/trainable/served/actually_trained must each be >=3B",
                )
            )
        parameter_receipts = (
            admitted_counts.get("evidence_receipts")
            if isinstance(admitted_counts, Mapping)
            else None
        )
        if (
            not isinstance(parameter_receipts, Mapping)
            or set(parameter_receipts) != set(floor_fields)
            or any(
                not isinstance(parameter_receipts.get(field), list)
                or not parameter_receipts[field]
                for field in floor_fields
            )
        ):
            findings.append(
                _finding(
                    "admission.parameter_evidence",
                    "every parameter axis requires checkpoint-bound count evidence",
                )
            )
        elif isinstance(receipt_bundle, Mapping):
            for field in floor_fields:
                for digest in parameter_receipts[field]:
                    _resolve_admission_receipt(
                        digest,
                        receipt_bundle=receipt_bundle,
                        expected_class=f"parameter_{field}",
                        expected_checkpoint=checkpoint_hash,
                        expected_verifier=_get(payload, "data.verifier_sha256")[1],
                        expected_claims={"claimed_count": admitted_counts[field]},
                        findings=findings,
                    )
        for group in mechanism_groups:
            mechanism_items = _get(payload, f"mechanisms.{group}")[1]
            if not isinstance(mechanism_items, list):
                continue
            for item in mechanism_items:
                if not isinstance(item, Mapping) or _is_unresolved(item):
                    continue
                mechanism_receipts = item.get("evidence_receipts")
                if not isinstance(mechanism_receipts, list) or not mechanism_receipts:
                    findings.append(
                        _finding("admission.mechanism_evidence", f"{group}:{item.get('id')}")
                    )
                    continue
                if isinstance(receipt_bundle, Mapping):
                    expected_claims = {
                        "mechanism_id": item.get("id"),
                        "mechanism_sha256": item.get("sha256"),
                    }
                    if group == "deletion_objects":
                        expected_claims["deletion_effect"] = "CAPABILITY_ERASED"
                    for digest in mechanism_receipts:
                        _resolve_admission_receipt(
                            digest,
                            receipt_bundle=receipt_bundle,
                            expected_class=f"mechanism_{group}",
                            expected_checkpoint=checkpoint_hash,
                            expected_verifier=_get(payload, "data.verifier_sha256")[1],
                            expected_claims=expected_claims,
                            findings=findings,
                        )
        for capability_name in ("reasoning", "structured_tool_use"):
            capability = _get(payload, f"capabilities.{capability_name}")[1]
            if (
                not isinstance(capability, Mapping)
                or capability.get("state") != "VERIFIED"
                or not isinstance(capability.get("evidence_receipts"), list)
                or not capability["evidence_receipts"]
            ):
                findings.append(
                    _finding(
                        "admission.capability_evidence",
                        f"{capability_name} requires verified receipt evidence",
                    )
                )
            elif isinstance(receipt_bundle, Mapping):
                for digest in capability["evidence_receipts"]:
                    _resolve_admission_receipt(
                        digest,
                        receipt_bundle=receipt_bundle,
                        expected_class=capability_name,
                        expected_checkpoint=checkpoint_hash,
                        expected_verifier=_get(payload, "data.verifier_sha256")[1],
                        findings=findings,
                    )
        admitted_mixture = _get(payload, "training.modality_mixture")[1]
        if (
            not isinstance(admitted_mixture, Mapping)
            or set(admitted_mixture) != {"text", "image", "audio"}
            or any(
                not isinstance(admitted_mixture.get(modality), (int, float))
                or isinstance(admitted_mixture.get(modality), bool)
                or admitted_mixture[modality] <= 0
                for modality in ("text", "image", "audio")
            )
        ):
            findings.append(
                _finding(
                    "admission.modality_exposure",
                    "OWNED_ADMITTED requires nonzero text/image/audio training exposure",
                )
            )
        admitted_modalities = _get(payload, "capabilities.native_modalities")[1]
        if (
            not isinstance(admitted_modalities, Mapping)
            or set(admitted_modalities) != {"text", "image", "audio"}
            or any(
                not _verified_receipt_evidence(admitted_modalities.get(modality))
                for modality in ("text", "image", "audio")
            )
        ):
            findings.append(
                _finding(
                    "admission.native_modality_evidence",
                    "OWNED_ADMITTED requires checkpoint-bound verification receipts for text/image/audio",
                )
            )
        elif isinstance(receipt_bundle, Mapping):
            for modality in ("text", "image", "audio"):
                for digest in admitted_modalities[modality]["evidence_receipts"]:
                    _resolve_admission_receipt(
                        digest,
                        receipt_bundle=receipt_bundle,
                        expected_class=f"native_{modality}",
                        expected_checkpoint=checkpoint_hash,
                        expected_verifier=_get(payload, "data.verifier_sha256")[1],
                        findings=findings,
                    )
        stopping_rule = _get(payload, "training.stopping_rule")[1]
        if (
            not isinstance(stopping_rule, Mapping)
            or not isinstance(stopping_rule.get("criterion_id"), str)
            or not stopping_rule.get("criterion_id")
            or stopping_rule.get("result") != "PASSED"
            or not isinstance(stopping_rule.get("receipt_sha256"), str)
            or not SHA256_RE.fullmatch(stopping_rule["receipt_sha256"])
        ):
            findings.append(
                _finding(
                    "admission.sufficient_pretraining",
                    "OWNED_ADMITTED requires a passed criterion and receipt",
                )
            )
        elif stopping_rule.get("criterion_id") != SUFFICIENT_PRETRAINING_CRITERION:
            findings.append(
                _finding(
                    "admission.sufficient_pretraining_criterion",
                    str(stopping_rule.get("criterion_id")),
                )
            )
        elif isinstance(receipt_bundle, Mapping):
            _resolve_admission_receipt(
                stopping_rule["receipt_sha256"],
                receipt_bundle=receipt_bundle,
                expected_class="sufficient_pretraining",
                expected_checkpoint=checkpoint_hash,
                expected_verifier=_get(payload, "data.verifier_sha256")[1],
                expected_result="PASSED",
                expected_criterion=SUFFICIENT_PRETRAINING_CRITERION,
                findings=findings,
            )
        admitted_learned = _get(payload, "provenance.learned_signal_sources")[1]
        if not _string_list_subset(
            admitted_learned, OWNED_LEARNED_SIGNAL_SOURCES
        ):
            findings.append(
                _finding(
                    "admission.learned_signal_source",
                    "OWNED_ADMITTED permits only owned learned-signal classes",
                )
            )
        admitted_credit = _get(
            payload, "provenance.neural_capability_credit_sources"
        )[1]
        if not _string_list_subset(
            admitted_credit, OWNED_CAPABILITY_CREDIT_SOURCES
        ):
            findings.append(
                _finding(
                    "admission.capability_credit_source",
                    "OWNED_ADMITTED permits only checkpoint-bound owned credit",
                )
            )
        if unresolved:
            findings.append(
                _finding(
                    "admission.unresolved",
                    "OWNED_ADMITTED cannot contain unresolved identity/evidence",
                )
            )

    if expected is not None:
        for path in BINDING_PATHS:
            actual_present, actual = _get(payload, path)
            expected_present, wanted = _get(expected, path)
            if not actual_present or not expected_present or actual != wanted:
                findings.append(_finding(f"binding.{path}_mismatch", path))

    if findings:
        raise IdentityValidationError(findings)
    return copy.deepcopy(dict(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--tensor-hashes", type=Path)
    parser.add_argument("--tensor-manifest", type=Path)
    parser.add_argument("--artifact-bundle", type=Path)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--receipt-bundle", type=Path)
    parser.add_argument("--verifier", type=Path)
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--require-resolved", action="store_true")
    parser.add_argument("--canonical", action="store_true")
    args = parser.parse_args()

    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        tensor_hashes = (
            json.loads(args.tensor_hashes.read_text(encoding="utf-8"))
            if args.tensor_hashes
            else None
        )
        tensor_manifest = json.loads(args.tensor_manifest.read_text(encoding="utf-8")) if args.tensor_manifest else None
        artifact_bundle = json.loads(args.artifact_bundle.read_text(encoding="utf-8")) if args.artifact_bundle else None
        expected = (
            json.loads(args.expected.read_text(encoding="utf-8"))
            if args.expected
            else None
        )
        receipt_bundle = (
            json.loads(args.receipt_bundle.read_text(encoding="utf-8"))
            if args.receipt_bundle
            else None
        )
        trusted_verifier_registry = (
            json.loads(args.trusted_verifier_registry.read_text(encoding="utf-8"))
            if args.trusted_verifier_registry
            else None
        )
        validated = validate_manifest(
            payload,
            checkpoint_bytes=args.checkpoint.read_bytes() if args.checkpoint else None,
            tensor_hashes=tensor_hashes,
            tensor_manifest=tensor_manifest,
            artifact_bundle=artifact_bundle,
            expected=expected,
            receipt_bundle=receipt_bundle,
            verifier_bytes=args.verifier.read_bytes() if args.verifier else None,
            trusted_verifier_registry=trusted_verifier_registry,
            require_resolved=args.require_resolved,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "findings": [{"code": "input.invalid", "detail": str(exc)}]}))
        return 1
    except IdentityValidationError as exc:
        print(json.dumps({"ok": False, "findings": exc.findings}, indent=2, sort_keys=True))
        return 1

    if args.canonical:
        sys.stdout.write(canonical_json(validated))
    else:
        print(json.dumps({"ok": True, "schema": validated["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
