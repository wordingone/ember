#!/usr/bin/env python3
# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate Ember model/experiment identity manifests without loading a model."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ember-model-experiment-identity-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

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
    "identity": {"model_id", "experiment_id", "disposition", "selected_as_owned_ember"},
    "architecture": {"source", "sha256"},
    "checkpoint": {"format", "byte_sha256", "tensors", "ancestry"},
    "tokenizer": {"id", "sha256"},
    "data": {
        "corpus_id", "sha256", "ordering_sha256", "curriculum_sha256",
        "verifier_sha256", "clean_genesis",
    },
    "parameters": {"allocated", "unique", "active", "trainable", "served", "actually_trained"},
    "training": {
        "steps", "effective_tokens", "modality_mixture", "optimizer_state_sha256",
        "numerics", "stopping_rule",
    },
    "training.modality_mixture": {"text", "image", "audio"},
    "capabilities": {"native_modalities", "reasoning", "structured_tool_use"},
    "capabilities.reasoning": {"state", "evidence_receipts"},
    "capabilities.structured_tool_use": {"state", "evidence_receipts"},
    "mechanisms": {"experts", "router", "memory_substrates", "world_models", "deletion_objects"},
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


def _is_unresolved(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("status") == "unresolved"


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
    expected: Mapping[str, Any] | None = None,
    require_resolved: bool = False,
) -> dict[str, Any]:
    """Validate one manifest and return a deep copy on success.

    Validation never derives identity from filenames, labels, endpoint defaults, or
    checkpoint shapes. Unknown values must be explicit unresolved objects.
    """
    if not isinstance(payload, Mapping):
        raise IdentityValidationError([_finding("manifest.not_object", "top level must be an object")])

    findings: list[dict[str, str]] = []

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
    if checkpoint_bytes is not None and checkpoint_present:
        actual = hashlib.sha256(checkpoint_bytes).hexdigest()
        if checkpoint_hash != actual:
            findings.append(
                _finding(
                    "checkpoint.byte_hash_mismatch",
                    f"manifest={checkpoint_hash}; actual={actual}",
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
            isinstance(native, list)
            and all(isinstance(item, str) for item in native)
            and set(native) == {"text", "image", "audio"}
            and len(native) == 3
        )
        if not valid_native:
            findings.append(_finding("capabilities.native_modalities_invalid", "requires exact text/image/audio values"))

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
        "experts", "router", "memory_substrates", "world_models", "deletion_objects"
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
                and set(item) == {"id", "sha256", "state"}
                and isinstance(item.get("id"), str)
                and bool(item.get("id"))
                and isinstance(item.get("sha256"), str)
                and bool(SHA256_RE.fullmatch(item["sha256"]))
                and item.get("state") in {"ACTIVE", "INACTIVE", "HISTORICAL", "UNVERIFIED"}
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
    parser.add_argument("--expected", type=Path)
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
        expected = (
            json.loads(args.expected.read_text(encoding="utf-8"))
            if args.expected
            else None
        )
        validated = validate_manifest(
            payload,
            checkpoint_bytes=args.checkpoint.read_bytes() if args.checkpoint else None,
            tensor_hashes=tensor_hashes,
            expected=expected,
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
