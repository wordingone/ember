#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed contract for one owned Ember checkpoint path."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "ember-owned-rung-v1"
PARAMETER_FLOOR = 3_000_000_000
CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")
BORROWED_FLAGS = (
    "borrowed_weights",
    "borrowed_teachers",
    "borrowed_judges",
    "borrowed_filters",
    "borrowed_generated_labels",
)
ARCHITECTURE_FLAGS = (
    "raw_image_patches",
    "raw_audio_frames",
    "soft_token_splicing",
    "multimodal_span_attention",
    "rope_2d",
    "shared_core",
    "sparse_differentiated_capacity",
    "task_level_expert_routing",
    "asymmetric_expert_initialization",
)
TOTAL_PARAMETER_FIELDS = (
    "allocated_parameters",
    "unique_parameters",
    "trainable_parameters",
    "served_parameters",
)
EXPERT_DOMAINS = ("vision", "audio", "reasoning", "tool")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(root: Path, value: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field}: expected non-empty relative path")
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        errors.append(f"{field}: absolute paths are forbidden")
        return None
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        errors.append(f"{field}: path escapes artifact root")
        return None
    if not resolved.is_file():
        errors.append(f"{field}: file does not exist")
        return None
    return resolved


def _verify_file(
    root: Path,
    record: Any,
    prefix: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(record, dict):
        errors.append(f"{prefix}: expected object")
        return None
    path = _artifact(root, record.get("path"), f"{prefix}.path", errors)
    expected = record.get("sha256")
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
        errors.append(f"{prefix}.sha256: expected lowercase SHA-256")
    elif path is not None and _sha256(path) != expected:
        errors.append(f"{prefix}.sha256: content hash mismatch")
    return path


def _verify_lineage(manifest: dict[str, Any], errors: list[str]) -> None:
    lineage = manifest.get("lineage")
    if not isinstance(lineage, dict):
        errors.append("lineage: expected object")
        return
    if lineage.get("genesis") != "OWNED_RANDOM_INIT":
        errors.append("lineage.genesis: must equal OWNED_RANDOM_INIT")
    if lineage.get("parent_checkpoint_sha256") is not None:
        errors.append("lineage.parent_checkpoint_sha256: clean genesis requires null")
    for field in BORROWED_FLAGS:
        if lineage.get(field) is not False:
            errors.append(f"lineage.{field}: must be false")


def _verify_architecture(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    architecture = manifest.get("architecture")
    if not isinstance(architecture, dict):
        errors.append("architecture: expected object")
        return
    if architecture.get("family") != "ember-unified-decoder":
        errors.append("architecture.family: must equal ember-unified-decoder")
    for field in TOTAL_PARAMETER_FIELDS:
        value = architecture.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < PARAMETER_FLOOR:
            errors.append(f"architecture.{field}: must be an integer >= {PARAMETER_FLOOR}")
    allocated = architecture.get("allocated_parameters")
    unique = architecture.get("unique_parameters")
    trainable = architecture.get("trainable_parameters")
    served = architecture.get("served_parameters")
    active = architecture.get("active_parameters")
    episode_trainable = architecture.get("episode_trainable_parameters")
    if not isinstance(active, int) or isinstance(active, bool) or active <= 0:
        errors.append("architecture.active_parameters: must be a positive integer")
    if not isinstance(episode_trainable, int) or isinstance(episode_trainable, bool) or episode_trainable <= 0:
        errors.append("architecture.episode_trainable_parameters: must be a positive integer")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (allocated, unique)) and unique > allocated:
        errors.append("architecture.unique_parameters: cannot exceed allocated_parameters")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (unique, trainable)) and trainable > unique:
        errors.append("architecture.trainable_parameters: cannot exceed unique_parameters")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (unique, served)) and served != unique:
        errors.append("architecture.served_parameters: must equal unique_parameters")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (active, unique)) and active >= unique:
        errors.append("architecture.active_parameters: sparse execution requires active < unique")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (episode_trainable, active)) and episode_trainable > active:
        errors.append("architecture.episode_trainable_parameters: cannot exceed active_parameters")
    for field in ARCHITECTURE_FLAGS:
        if architecture.get(field) is not True:
            errors.append(f"architecture.{field}: must be true")
    if architecture.get("separate_pretrained_encoders") is not False:
        errors.append("architecture.separate_pretrained_encoders: must be false")

    expert_banks = architecture.get("expert_banks")
    bank_ids: set[str] = set()
    bank_domains: set[str] = set()
    genesis_hashes: set[str] = set()
    if not isinstance(expert_banks, list) or len(expert_banks) != len(EXPERT_DOMAINS):
        errors.append("architecture.expert_banks: requires exactly vision/audio/reasoning/tool banks")
    else:
        for index, bank in enumerate(expert_banks):
            prefix = f"architecture.expert_banks[{index}]"
            if not isinstance(bank, dict):
                errors.append(f"{prefix}: expected object")
                continue
            bank_id = bank.get("id")
            domain = bank.get("domain")
            genesis = bank.get("genesis_sha256")
            if not isinstance(bank_id, str) or not bank_id:
                errors.append(f"{prefix}.id: expected non-empty string")
            elif bank_id in bank_ids:
                errors.append(f"{prefix}.id: duplicate expert id")
            else:
                bank_ids.add(bank_id)
            if domain not in EXPERT_DOMAINS:
                errors.append(f"{prefix}.domain: unsupported domain")
            else:
                bank_domains.add(domain)
            if not isinstance(genesis, str) or not SHA256_RE.fullmatch(genesis):
                errors.append(f"{prefix}.genesis_sha256: expected lowercase SHA-256")
            else:
                _verify_file(
                    root,
                    {"path": bank.get("path"), "sha256": genesis},
                    f"{prefix}.genesis_artifact",
                    errors,
                )
                if genesis in genesis_hashes:
                    errors.append(f"{prefix}.genesis_sha256: expert genesis hashes must be distinct")
                else:
                    genesis_hashes.add(genesis)
        if bank_domains != set(EXPERT_DOMAINS):
            errors.append("architecture.expert_banks: domains must equal vision/audio/reasoning/tool")
    active_experts = architecture.get("active_expert_ids")
    if not isinstance(active_experts, list) or len(active_experts) != 1:
        errors.append("architecture.active_expert_ids: exactly one expert must be active per episode")
    elif active_experts[0] not in bank_ids:
        errors.append("architecture.active_expert_ids: active expert is not declared")


def _verify_data(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    tokenizer = manifest.get("tokenizer")
    _verify_file(root, tokenizer, "tokenizer", errors)
    if isinstance(tokenizer, dict) and tokenizer.get("owned") is not True:
        errors.append("tokenizer.owned: must be true")

    entries = manifest.get("training_data")
    if not isinstance(entries, list):
        errors.append("training_data: expected list")
        return
    found: dict[str, int] = {}
    for index, entry in enumerate(entries):
        prefix = f"training_data[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: expected object")
            continue
        capability = entry.get("capability")
        if capability not in CAPABILITIES:
            errors.append(f"{prefix}.capability: unsupported capability")
        else:
            found[capability] = found.get(capability, 0) + 1
        _verify_file(
            root,
            {"path": entry.get("manifest_path"), "sha256": entry.get("sha256")},
            prefix,
            errors,
        )
        if entry.get("owned") is not True:
            errors.append(f"{prefix}.owned: must be true")
        if entry.get("locally_verified") is not True:
            errors.append(f"{prefix}.locally_verified: must be true")
    for capability in CAPABILITIES:
        if found.get(capability) != 1:
            errors.append(f"training_data: requires exactly one {capability} binding")


def _verify_training(manifest: dict[str, Any], errors: list[str]) -> None:
    training = manifest.get("training")
    if not isinstance(training, dict):
        errors.append("training: expected object")
        return
    tokens_seen = training.get("tokens_seen")
    if not isinstance(tokens_seen, int) or isinstance(tokens_seen, bool) or tokens_seen <= 0:
        errors.append("training.tokens_seen: must be a positive integer")
    command = training.get("command")
    if not isinstance(command, str) or not command.strip():
        errors.append("training.command: must be non-empty")
    mixture = training.get("modality_tokens")
    if not isinstance(mixture, dict):
        errors.append("training.modality_tokens: expected object")
        return
    total = 0
    for capability in CAPABILITIES:
        value = mixture.get(capability)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"training.modality_tokens.{capability}: must be positive")
        else:
            total += value
    if isinstance(tokens_seen, int) and not isinstance(tokens_seen, bool) and total > tokens_seen:
        errors.append("training.modality_tokens: sum exceeds tokens_seen")


def _verify_checkpoint(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    checkpoint = manifest.get("checkpoint")
    path = _verify_file(
        root,
        {
            "path": checkpoint.get("manifest_path") if isinstance(checkpoint, dict) else None,
            "sha256": checkpoint.get("sha256") if isinstance(checkpoint, dict) else None,
        },
        "checkpoint",
        errors,
    )
    if path is None:
        return
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"checkpoint.manifest_path: invalid JSON: {exc}")
        return
    shards = index.get("shards") if isinstance(index, dict) else None
    if not isinstance(shards, list) or not shards:
        errors.append("checkpoint manifest: shards must be a non-empty list")
        return
    checkpoint_shards: dict[str, str] = {}
    for index, shard in enumerate(shards):
        prefix = f"checkpoint.shards[{index}]"
        shard_path = _verify_file(root, shard, prefix, errors)
        if isinstance(shard, dict):
            expected_bytes = shard.get("bytes")
            if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
                errors.append(f"{prefix}.bytes: expected non-negative integer")
            elif shard_path is not None and shard_path.stat().st_size != expected_bytes:
                errors.append(f"{prefix}.bytes: size mismatch")
            if isinstance(shard.get("path"), str) and isinstance(shard.get("sha256"), str):
                checkpoint_shards[shard["path"]] = shard["sha256"]
    architecture = manifest.get("architecture")
    expert_banks = architecture.get("expert_banks") if isinstance(architecture, dict) else None
    if isinstance(expert_banks, list):
        for index, bank in enumerate(expert_banks):
            if not isinstance(bank, dict):
                continue
            path_value = bank.get("path")
            genesis = bank.get("genesis_sha256")
            if checkpoint_shards.get(path_value) != genesis:
                errors.append(
                    f"architecture.expert_banks[{index}]: genesis artifact must be an exact checkpoint shard"
                )


def _load_bound_json(
    root: Path,
    record: Any,
    path_field: str,
    prefix: str,
    errors: list[str],
) -> dict[str, Any] | None:
    path = _verify_file(
        root,
        {
            "path": record.get(path_field) if isinstance(record, dict) else None,
            "sha256": record.get("sha256") if isinstance(record, dict) else None,
        },
        prefix,
        errors,
    )
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{prefix}: invalid JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{prefix}: receipt must be an object")
        return None
    return payload


def _load_trusted_verifiers(
    registry_path: Path | None,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if registry_path is None:
        errors.append("trusted_verifier_registry: required for OWNED_ADMITTED")
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"trusted_verifier_registry: {exc}")
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != "ember-trusted-verifiers-v1":
        errors.append("trusted_verifier_registry: invalid schema_version")
        return {}
    entries = payload.get("verifiers")
    if not isinstance(entries, list) or not entries:
        errors.append("trusted_verifier_registry: verifiers must be a non-empty list")
        return {}
    trusted: dict[str, dict[str, Any]] = {}
    root = registry_path.resolve().parent
    for index, entry in enumerate(entries):
        prefix = f"trusted_verifier_registry.verifiers[{index}]"
        path = _verify_file(root, entry, prefix, errors)
        if not isinstance(entry, dict):
            continue
        sha256 = entry.get("sha256")
        evidence_classes = entry.get("evidence_classes")
        criterion_ids = entry.get("criterion_ids")
        if not isinstance(evidence_classes, list) or not evidence_classes:
            errors.append(f"{prefix}.evidence_classes: expected non-empty list")
        if not isinstance(criterion_ids, list):
            errors.append(f"{prefix}.criterion_ids: expected list")
        if path is not None and isinstance(sha256, str):
            if sha256 in trusted:
                errors.append(f"{prefix}.sha256: duplicate verifier")
            else:
                trusted[sha256] = entry
    return trusted


def _verify_admission(
    root: Path,
    manifest: dict[str, Any],
    trusted_verifiers: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    checkpoint = manifest.get("checkpoint")
    checkpoint_sha256 = checkpoint.get("sha256") if isinstance(checkpoint, dict) else None

    training = manifest.get("training")
    sufficient = training.get("sufficient_pretraining") if isinstance(training, dict) else None
    sufficient_payload = _load_bound_json(
        root, sufficient, "receipt_path", "training.sufficient_pretraining", errors
    )
    if not isinstance(sufficient, dict):
        errors.append("training.sufficient_pretraining: expected object")
    else:
        if sufficient.get("criterion_id") != "ember-sufficient-pretraining-v1":
            errors.append("training.sufficient_pretraining.criterion_id: unsupported criterion")
        if sufficient.get("result") != "PASSED":
            errors.append("training.sufficient_pretraining.result: must equal PASSED")
    if sufficient_payload is not None:
        if sufficient_payload.get("criterion_id") != "ember-sufficient-pretraining-v1":
            errors.append("training.sufficient_pretraining receipt: criterion mismatch")
        if sufficient_payload.get("result") != "PASSED":
            errors.append("training.sufficient_pretraining receipt: result must equal PASSED")
        if sufficient_payload.get("subject_checkpoint_sha256") != checkpoint_sha256:
            errors.append("training.sufficient_pretraining receipt: checkpoint mismatch")
        verifier = trusted_verifiers.get(sufficient_payload.get("verifier_sha256"))
        if verifier is None or "sufficient_pretraining" not in verifier.get("evidence_classes", []):
            errors.append("training.sufficient_pretraining receipt: verifier is not trusted")
        elif "ember-sufficient-pretraining-v1" not in verifier.get("criterion_ids", []):
            errors.append("training.sufficient_pretraining receipt: criterion is not trusted")

    evaluations = manifest.get("evaluations")
    if not isinstance(evaluations, list):
        errors.append("evaluations: expected list")
    else:
        found: dict[str, int] = {}
        for index, evaluation in enumerate(evaluations):
            prefix = f"evaluations[{index}]"
            if not isinstance(evaluation, dict):
                errors.append(f"{prefix}: expected object")
                continue
            capability = evaluation.get("capability")
            if capability not in CAPABILITIES:
                errors.append(f"{prefix}.capability: unsupported capability")
            else:
                found[capability] = found.get(capability, 0) + 1
            benchmark_id = evaluation.get("benchmark_id")
            if not isinstance(benchmark_id, str) or not benchmark_id.strip():
                errors.append(f"{prefix}.benchmark_id: must be non-empty")
            if evaluation.get("subject_checkpoint_sha256") != checkpoint_sha256:
                errors.append(f"{prefix}.subject_checkpoint_sha256: checkpoint mismatch")
            payload = _load_bound_json(root, evaluation, "receipt_path", prefix, errors)
            if payload is not None:
                if payload.get("capability") != capability:
                    errors.append(f"{prefix} receipt: capability mismatch")
                if payload.get("result") != "MEASURED":
                    errors.append(f"{prefix} receipt: result must equal MEASURED")
                if payload.get("subject_checkpoint_sha256") != checkpoint_sha256:
                    errors.append(f"{prefix} receipt: checkpoint mismatch")
                verifier = trusted_verifiers.get(payload.get("verifier_sha256"))
                if verifier is None or "evaluation" not in verifier.get("evidence_classes", []):
                    errors.append(f"{prefix} receipt: verifier is not trusted")
        for capability in CAPABILITIES:
            if found.get(capability) != 1:
                errors.append(f"evaluations: requires exactly one {capability} receipt")

    cli = manifest.get("cli")
    serving_payload = _load_bound_json(
        root, cli, "serving_manifest_path", "cli.serving_manifest", errors
    )
    if not isinstance(cli, dict):
        errors.append("cli: expected object")
    else:
        if cli.get("seat") != "OWNED_ADMITTED":
            errors.append("cli.seat: must equal OWNED_ADMITTED")
        if cli.get("checkpoint_sha256") != checkpoint_sha256:
            errors.append("cli.checkpoint_sha256: checkpoint mismatch")
    if serving_payload is not None:
        if serving_payload.get("seat") != "OWNED_ADMITTED":
            errors.append("cli serving manifest: seat must equal OWNED_ADMITTED")
        if serving_payload.get("checkpoint_sha256") != checkpoint_sha256:
            errors.append("cli serving manifest: checkpoint mismatch")
        model_format = serving_payload.get("model_format")
        if not isinstance(model_format, str) or not model_format.strip():
            errors.append("cli serving manifest: model_format must be non-empty")


def validate_manifest(
    path: Path,
    trusted_verifier_registry: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"valid": False, "stage": None, "errors": [f"manifest: {exc}"]}
    if not isinstance(manifest, dict):
        return {"valid": False, "stage": None, "errors": ["manifest: expected object"]}
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must equal {SCHEMA_VERSION}")
    stage = manifest.get("stage")
    if stage not in {"CHECKPOINT_CANDIDATE", "OWNED_ADMITTED"}:
        errors.append("stage: must equal CHECKPOINT_CANDIDATE or OWNED_ADMITTED")
    if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"].strip():
        errors.append("run_id: must be non-empty")
    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit):
        errors.append("source_commit: expected lowercase 40-character Git SHA")
    root = path.resolve().parent
    trusted_verifiers = (
        _load_trusted_verifiers(trusted_verifier_registry, errors)
        if stage == "OWNED_ADMITTED"
        else {}
    )
    _verify_lineage(manifest, errors)
    _verify_architecture(root, manifest, errors)
    _verify_data(root, manifest, errors)
    _verify_training(manifest, errors)
    _verify_checkpoint(root, manifest, errors)
    if stage == "OWNED_ADMITTED":
        _verify_admission(root, manifest, trusted_verifiers, errors)
    return {"valid": not errors, "stage": stage, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--trusted-verifier-registry", type=Path)
    args = parser.parse_args(argv)
    result = validate_manifest(args.manifest, args.trusted_verifier_registry)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
