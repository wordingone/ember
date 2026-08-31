#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resolve a closed, exact, non-claiming owned-development Ember CLI seat."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


HEX64 = set("0123456789abcdef")
ROOT_FIELDS = {
    "schema_version",
    "seat",
    "claim_status",
    "endpoint_url",
    "checkpoint",
    "model_config",
    "tokenizer",
    "server",
    "runtime_bundle",
    "parameter_evidence",
    "training",
}
FILE_BINDING_FIELDS = {"path", "sha256"}
CHECKPOINT_BINDING_FIELDS = {"manifest_path", "sha256"}
PARAMETER_FIELDS = {
    "counter_path",
    "counter_sha256",
    "receipt_path",
    "receipt_sha256",
    "registry_path",
    "registry_sha256",
    "allocated_parameters",
    "active_parameters",
}
TRAINING_FIELDS = {"tokens_seen"}
RUNTIME_BUNDLE_FIELDS = {"index_path", "sha256"}
RUNTIME_INDEX_FIELDS = {"schema_version", "source_commit", "files"}
RUNTIME_FILE_FIELDS = {"sha256", "bytes"}
RUNTIME_FILES = {
    "configs/ember-restart-3b.json",
    "parameter-evidence/parameter_counter.py",
    "parameter-evidence/step2-realization-receipt.json",
    "parameter-evidence/trusted-verifiers.json",
    "scripts/ember_restart/development_cli_seat.py",
    "src/ember/governance/scripts/ember_restart/prediction_contract.py",
    "scripts/ember_restart_eval_checkpoint_consumer.py",
    "scripts/ember_restart_eval_raw_forward.py",
    "domains/model/tokenizer/tokenizer.json",
    "tools/ember-restart-3b/batch.py",
    "tools/ember-restart-3b/checkpoint_artifacts.py",
    "tools/ember-restart-3b/infer.py",
    "tools/ember-restart-3b/model.py",
    "tools/ember-restart-3b/parameter_counter.py",
    "tools/ember-restart-3b/serve_owned_openai.py",
}


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise ValueError(f"{label} fields are not closed (missing={missing}, extra={extra})")


def _require_hash(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in HEX64 for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _resolve_file(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise ValueError(f"{label} does not exist: {candidate}")
    return candidate


def _resolve_bundle_file(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{label} must be a bundle-relative path")
    candidate = (root / value).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"{label} escapes the runtime bundle")
    if not candidate.is_file():
        raise ValueError(f"{label} does not exist: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_file_hash(path: Path, expected: Any, label: str) -> str:
    expected_hash = _require_hash(expected, f"{label} sha256")
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{label} content hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return actual_hash


def _read_json_snapshot(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = _require_object(json.loads(payload), label)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return value, hashlib.sha256(payload).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    return _read_json_snapshot(path, label)[0]


def _require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_endpoint(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("endpoint_url must be a URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("endpoint_url must be exact loopback HTTP on 127.0.0.1")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint_url has an invalid port") from exc
    if port is None or port < 1 or port > 65535:
        raise ValueError("endpoint_url must include a valid explicit port")
    return f"http://127.0.0.1:{port}"


def resolve_development_seat(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
    expected_runtime_index_sha256: str,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest, manifest_sha256 = _read_json_snapshot(manifest_path, "development manifest")
    if manifest_sha256 != _require_hash(
        expected_manifest_sha256, "expected development manifest sha256"
    ):
        raise ValueError("development manifest bytes differ from the CLI bootstrap snapshot")
    _require_exact_fields(manifest, ROOT_FIELDS, "development manifest")
    if manifest["schema_version"] != "ember-owned-development-seat-v1":
        raise ValueError("schema_version must be ember-owned-development-seat-v1")
    if manifest["seat"] != "OWNED_DEVELOPMENT":
        raise ValueError("seat must be OWNED_DEVELOPMENT")
    if manifest["claim_status"] != "NON_ADMISSIBLE":
        raise ValueError("claim_status must be NON_ADMISSIBLE")

    root = manifest_path.parent
    runtime_binding = _require_object(manifest["runtime_bundle"], "runtime_bundle")
    _require_exact_fields(runtime_binding, RUNTIME_BUNDLE_FIELDS, "runtime_bundle")
    runtime_index_path = _resolve_bundle_file(
        root, runtime_binding["index_path"], "runtime bundle index"
    )
    manifest_runtime_index_sha256 = _require_hash(
        runtime_binding["sha256"], "runtime bundle index sha256"
    )
    expected_index_sha256 = _require_hash(
        expected_runtime_index_sha256, "expected runtime bundle index sha256"
    )
    if manifest_runtime_index_sha256 != expected_index_sha256:
        raise ValueError("runtime bundle index identity differs from the CLI bootstrap snapshot")
    runtime_index, runtime_index_sha256 = _read_json_snapshot(
        runtime_index_path, "runtime bundle index"
    )
    if runtime_index_sha256 != expected_index_sha256:
        raise ValueError("runtime bundle index bytes differ from the CLI bootstrap snapshot")
    _require_exact_fields(runtime_index, RUNTIME_INDEX_FIELDS, "runtime bundle index")
    if runtime_index["schema_version"] != "ember-owned-runtime-bundle-v1":
        raise ValueError("runtime bundle index schema_version is invalid")
    source_commit = runtime_index["source_commit"]
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in HEX64 for character in source_commit)
    ):
        raise ValueError("runtime bundle source_commit must be a lowercase Git SHA-1")
    runtime_files = _require_object(runtime_index["files"], "runtime bundle files")
    if set(runtime_files) != RUNTIME_FILES:
        raise ValueError("runtime bundle files do not equal the required source closure")
    resolved_runtime: dict[str, tuple[Path, str]] = {}
    for relative in sorted(RUNTIME_FILES):
        binding = _require_object(runtime_files[relative], f"runtime file {relative}")
        _require_exact_fields(binding, RUNTIME_FILE_FIELDS, f"runtime file {relative}")
        path = _resolve_bundle_file(root, relative, f"runtime file {relative}")
        size = binding["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"runtime file {relative} bytes must be a non-negative integer")
        if path.stat().st_size != size:
            raise ValueError(f"runtime file {relative} byte size mismatch")
        resolved_runtime[relative] = (
            path,
            _require_file_hash(path, binding["sha256"], f"runtime file {relative}"),
        )

    checkpoint_binding = _require_object(manifest["checkpoint"], "checkpoint")
    _require_exact_fields(checkpoint_binding, CHECKPOINT_BINDING_FIELDS, "checkpoint")
    checkpoint_path = _resolve_file(
        root, checkpoint_binding["manifest_path"], "checkpoint manifest"
    )
    checkpoint_hash = _require_file_hash(
        checkpoint_path, checkpoint_binding["sha256"], "checkpoint manifest"
    )

    resolved: dict[str, tuple[Path, str]] = {}
    for field, label in (
        ("model_config", "model config"),
        ("tokenizer", "tokenizer"),
        ("server", "server"),
    ):
        binding = _require_object(manifest[field], field)
        _require_exact_fields(binding, FILE_BINDING_FIELDS, field)
        path = _resolve_file(root, binding["path"], label)
        resolved[field] = (path, _require_file_hash(path, binding["sha256"], label))
    for field, relative in (
        ("model_config", "configs/ember-restart-3b.json"),
        ("tokenizer", "domains/model/tokenizer/tokenizer.json"),
        ("server", "tools/ember-restart-3b/serve_owned_openai.py"),
    ):
        if resolved[field] != resolved_runtime[relative]:
            raise ValueError(f"{field} does not match the indexed runtime bundle artifact")

    parameters = _require_object(manifest["parameter_evidence"], "parameter_evidence")
    _require_exact_fields(parameters, PARAMETER_FIELDS, "parameter_evidence")
    evidence_files: dict[str, tuple[Path, str]] = {}
    for prefix, label in (
        ("counter", "parameter counter"),
        ("receipt", "parameter receipt"),
        ("registry", "trusted verifier registry"),
    ):
        path = _resolve_file(root, parameters[f"{prefix}_path"], label)
        evidence_files[prefix] = (
            path,
            _require_file_hash(path, parameters[f"{prefix}_sha256"], label),
        )
    for prefix, relative in (
        ("counter", "parameter-evidence/parameter_counter.py"),
        ("receipt", "parameter-evidence/step2-realization-receipt.json"),
        ("registry", "parameter-evidence/trusted-verifiers.json"),
    ):
        if evidence_files[prefix] != resolved_runtime[relative]:
            raise ValueError(
                f"parameter {prefix} does not match the indexed runtime bundle artifact"
            )

    training = _require_object(manifest["training"], "training")
    _require_exact_fields(training, TRAINING_FIELDS, "training")
    tokens_seen = _require_positive_int(training["tokens_seen"], "tokens_seen")
    allocated = _require_positive_int(
        parameters["allocated_parameters"], "allocated_parameters"
    )
    active = _require_positive_int(parameters["active_parameters"], "active_parameters")
    if allocated < 3_000_000_000:
        raise ValueError("allocated_parameters must be at least 3,000,000,000")
    if active > allocated:
        raise ValueError("active_parameters cannot exceed allocated_parameters")

    checkpoint = _read_json(checkpoint_path, "checkpoint manifest")
    checkpoint_schema_version = checkpoint.get("schema_version")
    if not isinstance(checkpoint_schema_version, str) or checkpoint_schema_version not in {
        "ember-sparse-checkpoint-v3",
        "ember-sparse-checkpoint-v5",
    }:
        raise ValueError("checkpoint schema_version is not supported")
    architecture = _require_object(checkpoint.get("architecture"), "checkpoint architecture")
    cursor = _require_object(checkpoint.get("data_cursor"), "checkpoint data_cursor")
    if architecture.get("allocated_parameters") != allocated:
        raise ValueError("allocated_parameters does not match checkpoint manifest")
    if architecture.get("active_parameters") != active:
        raise ValueError("active_parameters does not match checkpoint manifest")
    if checkpoint.get("model_config_sha256") != resolved["model_config"][1]:
        raise ValueError("model_config sha256 does not match checkpoint manifest")
    if cursor.get("tokenizer_sha256") != resolved["tokenizer"][1]:
        raise ValueError("tokenizer sha256 does not match checkpoint manifest")
    if cursor.get("tokens_seen") != tokens_seen:
        raise ValueError("tokens_seen does not match checkpoint manifest")

    receipt = _read_json(evidence_files["receipt"][0], "parameter receipt")
    required_receipt = {
        "schema_version": "ember-sparse-realization-receipt-v1",
        "result": "MEASURED",
        "verification_boundary": "VERIFIED_MEASURED",
        "subject_checkpoint_sha256": checkpoint_hash,
        "model_config_sha256": resolved["model_config"][1],
        "counter_sha256": evidence_files["counter"][1],
        "allocated_parameters": allocated,
        "active_parameters": active,
    }
    for field, expected in required_receipt.items():
        if receipt.get(field) != expected:
            raise ValueError(f"parameter receipt {field} does not match development manifest")

    registry = _read_json(evidence_files["registry"][0], "trusted verifier registry")
    if registry.get("schema_version") != "ember-trusted-verifiers-v1":
        raise ValueError("trusted verifier registry schema_version is invalid")
    verifier_rows = registry.get("verifiers")
    receipt_rows = registry.get("realization_receipts")
    if not isinstance(verifier_rows, list) or not any(
        isinstance(row, dict)
        and row.get("sha256") == evidence_files["counter"][1]
        and row.get("criterion_ids") == ["ember-sparse-step2-realization-v1"]
        and row.get("evidence_classes") == ["parameter_realization"]
        for row in verifier_rows
    ):
        raise ValueError("parameter counter is not a trusted registry member")
    if not isinstance(receipt_rows, list) or not any(
        isinstance(row, dict)
        and row.get("sha256") == evidence_files["receipt"][1]
        and row.get("subject_checkpoint_sha256") == checkpoint_hash
        and row.get("model_config_sha256") == resolved["model_config"][1]
        and row.get("counter_sha256") == evidence_files["counter"][1]
        and row.get("active_expert") == "shared"
        for row in receipt_rows
    ):
        raise ValueError("parameter receipt is not a trusted registry member")

    endpoint = _require_endpoint(manifest["endpoint_url"])
    return {
        "valid": True,
        "seat": "OWNED_DEVELOPMENT",
        "claim_status": "NON_ADMISSIBLE",
        "checkpoint_sha256": checkpoint_hash,
        "endpoint_url": endpoint,
        "identity_url": endpoint + "/v1/models",
        "model_config_sha256": resolved["model_config"][1],
        "model_name": f"ember-owned-development:{checkpoint_hash[:12]}",
        "model_format": "pytorch-checkpoint-v3",
        "server_source_sha256": resolved["server"][1],
        "tokenizer_sha256": resolved["tokenizer"][1],
        "tokens_seen": tokens_seen,
        "allocated_parameters": allocated,
        "active_parameters": active,
        "launch": {
            "checkpoint_dir": str(checkpoint_path.parent),
            "development_manifest_path": str(manifest_path),
            "mode": "INTERACTIVE",
            "model_config_path": str(resolved["model_config"][0]),
            "server_path": str(resolved["server"][0]),
            "tokenizer_path": str(resolved["tokenizer"][0]),
        },
        "errors": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-runtime-index-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = resolve_development_seat(
            args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_runtime_index_sha256=args.expected_runtime_index_sha256,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        result = {
            "valid": False,
            "seat": None,
            "errors": [f"development seat: {exc}"],
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
