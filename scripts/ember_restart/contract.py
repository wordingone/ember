#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed contract for one owned Ember checkpoint path."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .prediction_contract import ContractError, load_predictions
except ImportError:  # Direct execution: python scripts/ember_restart/contract.py
    from prediction_contract import ContractError, load_predictions


SCHEMA_VERSION = "ember-owned-rung-v1"
PARAMETER_FLOOR = 3_000_000_000
CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")
SEMANTIC_CHECKS = {
    "text": ["token_roundtrip", "source_target_pair"],
    "image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"],
    "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"],
    "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"],
    "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"],
}
CAPABILITY_CRITERIA = {
    capability: f"ember-3b-{capability}-capability-v1" for capability in CAPABILITIES
}
EVALUATION_EVIDENCE = {
    "split": "split_sha256",
    "harness": "harness_sha256",
    "protocol": "protocol_sha256",
    "inference_implementation": "inference_implementation_sha256",
    "predictions": "predictions_sha256",
    "score_artifact": "score_artifact_sha256",
}
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
ARCHITECTURE_REVISION = "ember-sparse-3b-v2"
ARCHITECTURE_SHAPE = {
    "hidden_size": 2048,
    "layers": 14,
    "attention_heads": 16,
    "vocab_size": 32000,
    "image_input_shape": [48, 48, 3],
    "audio_frame_samples": 640,
}
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


def _verify_architecture(
    root: Path,
    manifest: dict[str, Any],
    trusted_verifiers: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
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
    active_route = (
        active_experts[0]
        if isinstance(active_experts, list) and len(active_experts) == 1
        else None
    )
    if not isinstance(active_experts, list) or len(active_experts) != 1:
        errors.append("architecture.active_expert_ids: exactly one route must be active per episode")
    elif active_route != "shared" and active_route not in bank_ids:
        errors.append("architecture.active_expert_ids: active route is not declared")

    if architecture.get("revision") != ARCHITECTURE_REVISION:
        errors.append(f"architecture.revision: must equal {ARCHITECTURE_REVISION}")
    model_config_ref = architecture.get("model_config")
    model_config = _load_bound_json(
        root,
        model_config_ref,
        "path",
        "architecture.model_config",
        errors,
    )
    model_config_sha256 = (
        model_config_ref.get("sha256") if isinstance(model_config_ref, dict) else None
    )
    model_config_path = (
        _artifact(root, model_config_ref.get("path"), "architecture.model_config.path", errors)
        if isinstance(model_config_ref, dict)
        else None
    )
    config_counts: dict[str, int] | None = None
    if model_config is not None:
        if model_config.get("contract_name") != "ember-restart-3b":
            errors.append("architecture.model_config: contract_name mismatch")
        if model_config.get("contract_version") != 3:
            errors.append("architecture.model_config: contract_version mismatch")
        if model_config.get("architecture_revision") != ARCHITECTURE_REVISION:
            errors.append("architecture.model_config: architecture_revision mismatch")
        model = model_config.get("model")
        if not isinstance(model, dict):
            errors.append("architecture.model_config.model: expected object")
        else:
            observed_shape = {
                "hidden_size": model.get("hidden_size"),
                "layers": model.get("layers"),
                "attention_heads": model.get("attention_heads"),
                "vocab_size": model.get("vocab_size"),
                "image_input_shape": (
                    model.get("image_projection", {}).get("input_shape")
                    if isinstance(model.get("image_projection"), dict)
                    else None
                ),
                "audio_frame_samples": (
                    model.get("audio_projection", {}).get("frame_samples")
                    if isinstance(model.get("audio_projection"), dict)
                    else None
                ),
            }
            if observed_shape != ARCHITECTURE_SHAPE:
                errors.append("architecture.model_config: shape does not match revision")
            routing = model.get("expert_routing")
            if (
                not isinstance(routing, dict)
                or routing.get("expert_names") != list(EXPERT_DOMAINS)
                or routing.get("shared_text_ffn") != "always_active_SwiGLU_4H"
            ):
                errors.append("architecture.model_config: expert routing mismatch")
            if model.get("tied_embeddings") is not True:
                errors.append("architecture.model_config: tied_embeddings must be true")
            if observed_shape == ARCHITECTURE_SHAPE:
                hidden = ARCHITECTURE_SHAPE["hidden_size"]
                layers = ARCHITECTURE_SHAPE["layers"]
                vocab = ARCHITECTURE_SHAPE["vocab_size"]
                image_input = 1
                for size in ARCHITECTURE_SHAPE["image_input_shape"]:
                    image_input *= size
                audio_input = ARCHITECTURE_SHAPE["audio_frame_samples"]
                head_dim = hidden // ARCHITECTURE_SHAPE["attention_heads"]
                shared_per_layer = (
                    4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim
                )
                expert_per_layer = 12 * hidden * hidden
                shared_total = (
                    vocab * hidden
                    + layers * shared_per_layer
                    + image_input * hidden
                    + audio_input * hidden
                    + hidden
                )
                expert_total = layers * expert_per_layer
                total = shared_total + len(EXPERT_DOMAINS) * expert_total
                active_count = (
                    shared_total if active_route == "shared" else shared_total + expert_total
                )
                config_counts = {
                    "allocated_parameters": total,
                    "unique_parameters": total,
                    "trainable_parameters": total,
                    "served_parameters": total,
                    "active_parameters": active_count,
                    "episode_trainable_parameters": active_count,
                }
                if model.get("total_unique_trainable_parameters") != total:
                    errors.append("architecture.model_config: declared total is not config-derived")
                for field, expected in config_counts.items():
                    if architecture.get(field) != expected:
                        errors.append(f"architecture.{field}: does not match config-derived count")

    counter = architecture.get("parameter_counter")
    counter_path = _verify_file(root, counter, "architecture.parameter_counter", errors)
    counter_sha256 = counter.get("sha256") if isinstance(counter, dict) else None
    counter_verifier = trusted_verifiers.get(counter_sha256)
    counter_is_trusted = (
        counter_verifier is not None
        and "parameter_realization" in counter_verifier.get("evidence_classes", [])
    )
    if not counter_is_trusted:
        errors.append("architecture.parameter_counter: verifier is not independently trusted")
    parameter_receipt = architecture.get("parameter_receipt")
    receipt = _load_bound_json(
        root,
        parameter_receipt,
        "path",
        "architecture.parameter_receipt",
        errors,
    )
    if receipt is not None:
        if receipt.get("result") != "MEASURED":
            errors.append("architecture.parameter_receipt: result must equal MEASURED")
        checkpoint = manifest.get("checkpoint")
        checkpoint_sha256 = checkpoint.get("sha256") if isinstance(checkpoint, dict) else None
        if receipt.get("subject_checkpoint_sha256") != checkpoint_sha256:
            errors.append("architecture.parameter_receipt: checkpoint mismatch")
        if counter_path is None or receipt.get("counter_sha256") != counter_sha256:
            errors.append("architecture.parameter_receipt: counter mismatch")
        if receipt.get("model_config_sha256") != model_config_sha256:
            errors.append("architecture.parameter_receipt: model config mismatch")
        if receipt.get("architecture_revision") != ARCHITECTURE_REVISION:
            errors.append("architecture.parameter_receipt: architecture revision mismatch")
        for field in (*TOTAL_PARAMETER_FIELDS, "active_parameters", "episode_trainable_parameters"):
            if receipt.get(field) != architecture.get(field):
                errors.append(f"architecture.parameter_receipt: {field} mismatch")
        if receipt.get("active_expert_ids") != active_experts:
            errors.append("architecture.parameter_receipt: active_expert_ids mismatch")
        expected_banks = {
            bank.get("id"): bank.get("genesis_sha256")
            for bank in expert_banks
            if isinstance(bank, dict)
        } if isinstance(expert_banks, list) else {}
        if receipt.get("expert_genesis_sha256") != expected_banks:
            errors.append("architecture.parameter_receipt: expert genesis mismatch")

        checkpoint = manifest.get("checkpoint")
        checkpoint_path = (
            _artifact(
                root,
                checkpoint.get("manifest_path"),
                "checkpoint.manifest_path",
                errors,
            )
            if isinstance(checkpoint, dict)
            else None
        )
        if (
            counter_is_trusted
            and counter_path is not None
            and model_config_path is not None
            and checkpoint_path is not None
        ):
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        str(counter_path),
                        "--model-config",
                        str(model_config_path),
                        "--checkpoint-manifest",
                        str(checkpoint_path),
                        "--active-expert",
                        str(active_experts[0]) if isinstance(active_experts, list) and active_experts else "",
                    ],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"architecture.parameter_counter: counter execution failed: {exc}")
            else:
                if completed.returncode != 0:
                    errors.append(
                        "architecture.parameter_counter: counter execution failed "
                        f"with exit code {completed.returncode}"
                    )
                else:
                    try:
                        measured = json.loads(completed.stdout)
                    except json.JSONDecodeError:
                        errors.append("architecture.parameter_counter: counter execution returned invalid JSON")
                    else:
                        if not isinstance(measured, dict):
                            errors.append("architecture.parameter_counter: counter execution must return an object")
                        else:
                            measured_fields = (
                                "result",
                                "subject_checkpoint_sha256",
                                "model_config_sha256",
                                "architecture_revision",
                                *TOTAL_PARAMETER_FIELDS,
                                "active_parameters",
                                "episode_trainable_parameters",
                                "active_expert_ids",
                            )
                            for field in measured_fields:
                                if measured.get(field) != receipt.get(field):
                                    errors.append(
                                        f"architecture.parameter_counter: executed {field} mismatch"
                                    )


def _verify_data(
    root: Path,
    manifest: dict[str, Any],
    trusted_verifiers: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    tokenizer = manifest.get("tokenizer")
    tokenizer_path = _verify_file(root, tokenizer, "tokenizer", errors)
    tokenizer_sha256 = tokenizer.get("sha256") if isinstance(tokenizer, dict) else None
    if isinstance(tokenizer, dict):
        if tokenizer.get("owned") is not True:
            errors.append("tokenizer.owned: must be true")
        if tokenizer.get("kind") != "OWNED_TRAINED":
            errors.append("tokenizer.kind: must equal OWNED_TRAINED")
        if tokenizer.get("vocab_size") != ARCHITECTURE_SHAPE["vocab_size"]:
            errors.append("tokenizer.vocab_size: must equal model vocab_size")
        training_script = _verify_file(
            root, tokenizer.get("training_script"), "tokenizer.training_script", errors
        )
        corpus_manifest = _verify_file(
            root,
            tokenizer.get("training_corpus_manifest"),
            "tokenizer.training_corpus_manifest",
            errors,
        )
        tokenizer_verifier = tokenizer.get("verifier")
        tokenizer_verifier_path = _verify_file(
            root, tokenizer_verifier, "tokenizer.verifier", errors
        )
        tokenizer_verifier_sha256 = (
            tokenizer_verifier.get("sha256")
            if isinstance(tokenizer_verifier, dict)
            else None
        )
        tokenizer_trust = trusted_verifiers.get(tokenizer_verifier_sha256)
        if (
            tokenizer_trust is None
            or "tokenizer_freeze" not in tokenizer_trust.get("evidence_classes", [])
        ):
            errors.append("tokenizer.verifier: verifier is not independently trusted")
        freeze = _load_bound_json(
            root, tokenizer.get("freeze_receipt"), "path", "tokenizer.freeze_receipt", errors
        )
        if freeze is not None:
            expected = {
                "schema_version": "ember-owned-tokenizer-freeze-v1",
                "result": "FROZEN",
                "tokenizer_sha256": tokenizer_sha256,
                "vocab_size": ARCHITECTURE_SHAPE["vocab_size"],
                "training_script_sha256": (
                    _sha256(training_script) if training_script is not None else None
                ),
                "training_corpus_sha256": (
                    _sha256(corpus_manifest) if corpus_manifest is not None else None
                ),
                "verifier_sha256": tokenizer_verifier_sha256,
                "borrowed_tokenizer": False,
                "frozen_pre_step0": True,
            }
            for field, value in expected.items():
                if freeze.get(field) != value:
                    errors.append(f"tokenizer.freeze_receipt.{field}: binding mismatch")
            if (
                tokenizer_trust is not None
                and "tokenizer_freeze" in tokenizer_trust.get("evidence_classes", [])
                and tokenizer_verifier_path is not None
                and tokenizer_path is not None
                and training_script is not None
                and corpus_manifest is not None
            ):
                try:
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            str(tokenizer_verifier_path),
                            "--tokenizer",
                            str(tokenizer_path),
                            "--training-script",
                            str(training_script),
                            "--training-corpus-manifest",
                            str(corpus_manifest),
                        ],
                        cwd=root,
                        text=True,
                        capture_output=True,
                        timeout=120,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    errors.append(f"tokenizer.verifier: execution failed: {exc}")
                else:
                    if completed.returncode != 0:
                        errors.append(
                            "tokenizer.verifier: execution failed with exit code "
                            f"{completed.returncode}"
                        )
                    else:
                        try:
                            executed = json.loads(completed.stdout)
                        except json.JSONDecodeError:
                            errors.append("tokenizer.verifier: returned invalid JSON")
                        else:
                            if not isinstance(executed, dict):
                                errors.append("tokenizer.verifier: must return an object")
                            else:
                                for field in expected:
                                    if executed.get(field) != freeze.get(field):
                                        errors.append(
                                            f"tokenizer.verifier: executed {field} mismatch"
                                        )
    else:
        errors.append("tokenizer.kind: must equal OWNED_TRAINED")
        errors.append("tokenizer.freeze_receipt: expected object")

    entries = manifest.get("training_data")
    if not isinstance(entries, list):
        errors.append("training_data: expected list")
        return
    found: dict[str, int] = {}
    data_classes: set[str] = set()
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
        data_ref = {"path": entry.get("manifest_path"), "sha256": entry.get("sha256")}
        data_path = _verify_file(root, data_ref, prefix, errors)
        data_payload = _load_bound_json(
            root, data_ref, "path", f"{prefix} manifest", errors
        )
        verifier = entry.get("verifier")
        verifier_path = _verify_file(root, verifier, f"{prefix}.verifier", errors)
        verifier_sha256 = verifier.get("sha256") if isinstance(verifier, dict) else None
        trusted = trusted_verifiers.get(verifier_sha256)
        if trusted is None or "training_data" not in trusted.get("evidence_classes", []):
            errors.append(f"{prefix}.verifier: verifier is not independently trusted")
        verification = _load_bound_json(
            root,
            entry.get("verification_receipt"),
            "path",
            f"{prefix}.verification_receipt",
            errors,
        )
        if entry.get("owned") is not True:
            errors.append(f"{prefix}.owned: must be true")
        if entry.get("locally_verified") is not True:
            errors.append(f"{prefix}.locally_verified: must be true")
        if data_payload is not None:
            if data_payload.get("schema_version") != "ember-owned-training-data-v1":
                errors.append(
                    f"{prefix} manifest.schema_version: "
                    "must equal ember-owned-training-data-v1"
                )
            if data_payload.get("capability") != capability:
                errors.append(f"{prefix} manifest.capability: binding mismatch")
            data_class = data_payload.get("data_class")
            if data_class not in {"SMOKE_ONLY", "SEMANTIC_PRETRAINING"}:
                errors.append(
                    f"{prefix} manifest.data_class: "
                    "must equal SMOKE_ONLY or SEMANTIC_PRETRAINING"
                )
            else:
                data_classes.add(data_class)
            if data_payload.get("tokenizer_sha256") != tokenizer_sha256:
                errors.append(f"{prefix} manifest.tokenizer_sha256: binding mismatch")
            if data_payload.get("model_mediated") is not False:
                errors.append(f"{prefix} manifest.model_mediated: must be false")
            if data_payload.get("borrowed_labels") is not False:
                errors.append(f"{prefix} manifest.borrowed_labels: must be false")
            for field in ("record_count", "token_count"):
                value = data_payload.get(field)
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    errors.append(f"{prefix} manifest.{field}: must be a positive integer")
            source_manifest = _verify_file(
                root,
                data_payload.get("source_manifest"),
                f"{prefix} manifest.source_manifest",
                errors,
            )
            source_payload = _load_bound_json(
                root,
                data_payload.get("source_manifest"),
                "path",
                f"{prefix} source_manifest",
                errors,
            )
            if source_payload is not None:
                if source_payload.get("schema_version") != "ember-owned-source-v1":
                    errors.append(
                        f"{prefix} source_manifest.schema_version: "
                        "must equal ember-owned-source-v1"
                    )
                if source_payload.get("capability") != capability:
                    errors.append(f"{prefix} source_manifest.capability: binding mismatch")
                if source_payload.get("model_mediated") is not False:
                    errors.append(f"{prefix} source_manifest.model_mediated: must be false")
                if source_payload.get("borrowed_labels") is not False:
                    errors.append(f"{prefix} source_manifest.borrowed_labels: must be false")
            records_artifact = _verify_file(
                root,
                data_payload.get("records_artifact"),
                f"{prefix} manifest.records_artifact",
                errors,
            )
            required_semantic_checks = (
                SEMANTIC_CHECKS.get(str(capability), [])
                if data_class == "SEMANTIC_PRETRAINING"
                else []
            )
            if verification is not None:
                expected = {
                    "schema_version": "ember-training-data-verification-v1",
                    "result": "VERIFIED",
                    "capability": capability,
                    "data_manifest_sha256": entry.get("sha256"),
                    "tokenizer_sha256": tokenizer_sha256,
                    "verifier_sha256": verifier_sha256,
                    "data_class": data_class,
                    "record_count": data_payload.get("record_count"),
                    "token_count": data_payload.get("token_count"),
                    "source_manifest_sha256": (
                        _sha256(source_manifest) if source_manifest is not None else None
                    ),
                    "records_artifact_sha256": (
                        _sha256(records_artifact) if records_artifact is not None else None
                    ),
                    "semantic_checks": required_semantic_checks,
                }
                for field, value in expected.items():
                    if verification.get(field) != value:
                        errors.append(f"{prefix}.verification_receipt.{field}: binding mismatch")
                if (
                    trusted is not None
                    and "training_data" in trusted.get("evidence_classes", [])
                    and verifier_path is not None
                    and data_path is not None
                    and tokenizer_path is not None
                ):
                    try:
                        completed = subprocess.run(
                            [
                                sys.executable,
                                "-I",
                                str(verifier_path),
                                "--data-manifest",
                                str(data_path),
                                "--tokenizer",
                                str(tokenizer_path),
                                "--capability",
                                str(capability),
                            ],
                            cwd=root,
                            text=True,
                            capture_output=True,
                            timeout=120,
                            check=False,
                        )
                    except (OSError, subprocess.SubprocessError) as exc:
                        errors.append(f"{prefix}.verifier: execution failed: {exc}")
                    else:
                        if completed.returncode != 0:
                            errors.append(
                                f"{prefix}.verifier: execution failed with exit code "
                                f"{completed.returncode}"
                            )
                        else:
                            try:
                                executed = json.loads(completed.stdout)
                            except json.JSONDecodeError:
                                errors.append(f"{prefix}.verifier: returned invalid JSON")
                            else:
                                if not isinstance(executed, dict):
                                    errors.append(f"{prefix}.verifier: must return an object")
                                else:
                                    for field in expected:
                                        if executed.get(field) != verification.get(field):
                                            errors.append(
                                                f"{prefix}.verifier: executed {field} mismatch"
                                            )
    for capability in CAPABILITIES:
        if found.get(capability) != 1:
            errors.append(f"training_data: requires exactly one {capability} binding")
    if len(data_classes) > 1:
        errors.append("training_data: mixed SMOKE_ONLY and SEMANTIC_PRETRAINING classes")


def _verify_training(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    training = manifest.get("training")
    if not isinstance(training, dict):
        errors.append("training: expected object")
        return
    input_class = training.get("input_class")
    if input_class not in {"SMOKE_ONLY", "SEMANTIC_PRETRAINING"}:
        errors.append(
            "training.input_class: must equal SMOKE_ONLY or SEMANTIC_PRETRAINING"
        )
    optimizer = training.get("optimizer")
    if not isinstance(optimizer, dict):
        errors.append("training.optimizer: expected object")
    else:
        if not isinstance(optimizer.get("implementation"), str) or not optimizer["implementation"]:
            errors.append("training.optimizer.implementation: must be non-empty")
        if not isinstance(optimizer.get("hyperparameters"), dict):
            errors.append("training.optimizer.hyperparameters: expected object")
        if not isinstance(optimizer.get("state_format"), str) or not optimizer["state_format"]:
            errors.append("training.optimizer.state_format: must be non-empty")
    optimizer_receipt = _load_bound_json(
        root,
        training.get("optimizer_receipt"),
        "path",
        "training.optimizer_receipt",
        errors,
    )
    architecture = manifest.get("architecture")
    model_config = None
    if isinstance(architecture, dict):
        model_config = _load_bound_json(
            root,
            architecture.get("model_config"),
            "path",
            "training.model_config",
            errors,
        )
    declared_optimizer = (
        model_config.get("training", {}).get("optimizer")
        if isinstance(model_config, dict) and isinstance(model_config.get("training"), dict)
        else None
    )
    if isinstance(optimizer, dict) and declared_optimizer != optimizer:
        errors.append("training.optimizer: does not match model config")
    checkpoint = manifest.get("checkpoint")
    checkpoint_payload = None
    if isinstance(checkpoint, dict):
        checkpoint_payload = _load_bound_json(
            root,
            {"path": checkpoint.get("manifest_path"), "sha256": checkpoint.get("sha256")},
            "path",
            "training.checkpoint_manifest",
            errors,
        )
    if isinstance(optimizer, dict) and isinstance(checkpoint_payload, dict):
        if checkpoint_payload.get("optimizer") != optimizer:
            errors.append("training.optimizer: does not match checkpoint manifest")
    if optimizer_receipt is not None:
        model_config_ref = architecture.get("model_config") if isinstance(architecture, dict) else None
        expected = {
            "schema_version": "ember-optimizer-realization-v1",
            "result": "REALIZED",
            "implementation": optimizer.get("implementation") if isinstance(optimizer, dict) else None,
            "hyperparameters": optimizer.get("hyperparameters") if isinstance(optimizer, dict) else None,
            "state_format": optimizer.get("state_format") if isinstance(optimizer, dict) else None,
            "model_config_sha256": (
                model_config_ref.get("sha256") if isinstance(model_config_ref, dict) else None
            ),
        }
        for field, value in expected.items():
            if optimizer_receipt.get(field) != value:
                errors.append(f"training.optimizer_receipt.{field}: binding mismatch")
    bound_data_classes: set[str] = set()
    entries = manifest.get("training_data")
    if isinstance(entries, list):
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            payload = _load_bound_json(
                root,
                {"path": entry.get("manifest_path"), "sha256": entry.get("sha256")},
                "path",
                f"training.training_data[{index}]",
                errors,
            )
            if isinstance(payload, dict) and payload.get("data_class") in {
                "SMOKE_ONLY",
                "SEMANTIC_PRETRAINING",
            }:
                bound_data_classes.add(payload["data_class"])
    if (
        input_class in {"SMOKE_ONLY", "SEMANTIC_PRETRAINING"}
        and bound_data_classes
        and bound_data_classes != {input_class}
    ):
        errors.append("training.input_class: does not match bound training data")
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
    expected_registry_sha256: str | None = None,
) -> dict[str, dict[str, Any]]:
    if registry_path is None:
        errors.append("trusted_verifier_registry: required for checkpoint claims")
        return {}
    try:
        registry_bytes = registry_path.read_bytes()
        if expected_registry_sha256 is not None and hashlib.sha256(registry_bytes).hexdigest() != expected_registry_sha256:
            errors.append("trusted_verifier_registry: external authority hash mismatch")
            return {}
        payload = json.loads(registry_bytes)
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
                resolved_entry = dict(entry)
                resolved_entry["_resolved_path"] = path
                trusted[sha256] = resolved_entry
    return trusted


def _verify_admission(
    root: Path,
    manifest: dict[str, Any],
    trusted_verifiers: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    checkpoint = manifest.get("checkpoint")
    checkpoint_sha256 = checkpoint.get("sha256") if isinstance(checkpoint, dict) else None
    architecture = manifest.get("architecture")
    model_config = architecture.get("model_config") if isinstance(architecture, dict) else None
    model_config_sha256 = model_config.get("sha256") if isinstance(model_config, dict) else None
    tokenizer = manifest.get("tokenizer")
    tokenizer_sha256 = tokenizer.get("sha256") if isinstance(tokenizer, dict) else None

    training = manifest.get("training")
    sufficient = training.get("sufficient_pretraining") if isinstance(training, dict) else None
    trainable_parameters = (
        architecture.get("trainable_parameters") if isinstance(architecture, dict) else None
    )
    tokens_seen = training.get("tokens_seen") if isinstance(training, dict) else None
    if (
        isinstance(trainable_parameters, int)
        and not isinstance(trainable_parameters, bool)
        and isinstance(tokens_seen, int)
        and not isinstance(tokens_seen, bool)
        and tokens_seen < trainable_parameters
    ):
        errors.append("training.sufficient_pretraining: tokens_seen must be at least trainable_parameters")
    admission_mixture = training.get("modality_tokens") if isinstance(training, dict) else None
    if isinstance(admission_mixture, dict):
        for capability in CAPABILITIES:
            exposure = admission_mixture.get(capability)
            if (
                not isinstance(exposure, int)
                or isinstance(exposure, bool)
                or exposure < 1_000_000
            ):
                errors.append(f"training.modality_tokens.{capability}: admission requires at least 1000000")
    sufficient_payload = _load_bound_json(
        root, sufficient, "receipt_path", "training.sufficient_pretraining", errors
    )
    sufficient_evidence_paths: dict[str, Path] = {}
    sufficient_evidence_fields = {
        "training_ledger": "training_ledger_sha256",
        "stopping_evaluation": "stopping_evaluation_sha256",
        "checkpoint_progression": "checkpoint_progression_sha256",
    }
    if not isinstance(sufficient, dict):
        errors.append("training.sufficient_pretraining: expected object")
    else:
        if sufficient.get("criterion_id") != "ember-sufficient-pretraining-v2":
            errors.append("training.sufficient_pretraining.criterion_id: unsupported criterion")
        if sufficient.get("result") != "PASSED":
            errors.append("training.sufficient_pretraining.result: must equal PASSED")
        sufficient_evidence = sufficient.get("evidence")
        if not isinstance(sufficient_evidence, dict):
            errors.append("training.sufficient_pretraining: executed evidence object missing")
        else:
            for evidence_name, receipt_field in sufficient_evidence_fields.items():
                record = sufficient_evidence.get(evidence_name)
                evidence_path = _verify_file(
                    root,
                    record,
                    f"training.sufficient_pretraining.evidence.{evidence_name}",
                    errors,
                )
                if evidence_path is not None:
                    sufficient_evidence_paths[evidence_name] = evidence_path
                evidence_hash = record.get("sha256") if isinstance(record, dict) else None
                if sufficient_payload is not None and sufficient_payload.get(receipt_field) != evidence_hash:
                    errors.append(
                        f"training.sufficient_pretraining receipt: executed evidence {receipt_field} mismatch"
                    )
    ledger_path = sufficient_evidence_paths.get("training_ledger")
    if ledger_path is not None:
        try:
            training_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            training_ledger = None
        ledger_modalities = (
            training_ledger.get("modality_tokens") if isinstance(training_ledger, dict) else None
        )
        if (
            not isinstance(training_ledger, dict)
            or training_ledger.get("schema_version") != "ember-training-ledger-v2"
            or training_ledger.get("subject_checkpoint_sha256") != checkpoint_sha256
            or training_ledger.get("tokens_seen") != tokens_seen
            or ledger_modalities != admission_mixture
        ):
            errors.append(
                "training.sufficient_pretraining.training_ledger: "
                "modality exposure is not evidence-bound"
            )
        if isinstance(sufficient_payload, dict):
            if "modality_tokens" not in sufficient_payload:
                errors.append(
                    "training.sufficient_pretraining receipt: missing modality_tokens"
                )
            elif sufficient_payload.get("modality_tokens") != admission_mixture:
                errors.append(
                    "training.sufficient_pretraining receipt: modality_tokens mismatch"
                )
    stopping_path = sufficient_evidence_paths.get("stopping_evaluation")
    heldout_tokens = None
    genesis_loss = None
    final_loss = None
    stopping_genesis_checkpoint_sha256 = None
    heldout_hashes: dict[str, str | None] = {
        "heldout_split_sha256": None,
        "heldout_harness_sha256": None,
        "heldout_protocol_sha256": None,
        "genesis_measurement_sha256": None,
        "final_measurement_sha256": None,
    }
    if stopping_path is not None:
        try:
            stopping_evaluation = json.loads(stopping_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            stopping_evaluation = None
        if (
            not isinstance(stopping_evaluation, dict)
            or stopping_evaluation.get("schema_version") != "ember-heldout-learning-v2"
            or stopping_evaluation.get("criterion") != "plateau-and-heldout-v2"
            or stopping_evaluation.get("subject_checkpoint_sha256") != checkpoint_sha256
            or not isinstance(stopping_evaluation.get("evidence"), dict)
        ):
            errors.append(
                "training.sufficient_pretraining.stopping_evaluation: "
                "checkpoint-bound heldout evidence missing"
            )
        else:
            heldout_tokens = stopping_evaluation.get("heldout_tokens")
            genesis_loss = stopping_evaluation.get("genesis_loss")
            final_loss = stopping_evaluation.get("final_loss")
            stopping_genesis_checkpoint_sha256 = stopping_evaluation.get(
                "genesis_checkpoint_sha256"
            )
            stopping_evidence = stopping_evaluation["evidence"]
            evidence_paths: dict[str, Path] = {}
            evidence_names = (
                "heldout_split",
                "harness",
                "protocol",
                "genesis_measurement",
                "final_measurement",
            )
            for evidence_name in evidence_names:
                record = stopping_evidence.get(evidence_name)
                evidence_path = _verify_file(
                    root,
                    record,
                    "training.sufficient_pretraining.stopping_evaluation"
                    f".evidence.{evidence_name}",
                    errors,
                )
                if evidence_path is not None:
                    evidence_paths[evidence_name] = evidence_path
                evidence_hash = record.get("sha256") if isinstance(record, dict) else None
                receipt_field = {
                    "heldout_split": "heldout_split_sha256",
                    "harness": "heldout_harness_sha256",
                    "protocol": "heldout_protocol_sha256",
                    "genesis_measurement": "genesis_measurement_sha256",
                    "final_measurement": "final_measurement_sha256",
                }[evidence_name]
                heldout_hashes[receipt_field] = evidence_hash
            measurements: dict[str, Any] = {}
            for measurement_name in ("genesis_measurement", "final_measurement"):
                measurement_path = evidence_paths.get(measurement_name)
                try:
                    measurement = (
                        json.loads(measurement_path.read_text(encoding="utf-8"))
                        if measurement_path is not None
                        else None
                    )
                except (OSError, UnicodeError, json.JSONDecodeError):
                    measurement = None
                measurements[measurement_name] = measurement
            common_measurement = {
                "heldout_split_sha256": heldout_hashes["heldout_split_sha256"],
                "harness_sha256": heldout_hashes["heldout_harness_sha256"],
                "protocol_sha256": heldout_hashes["heldout_protocol_sha256"],
                "heldout_tokens": heldout_tokens,
            }
            genesis_measurement = measurements["genesis_measurement"]
            final_measurement = measurements["final_measurement"]
            measurements_bound = True
            for measurement, expected_checkpoint, expected_loss in (
                (
                    genesis_measurement,
                    stopping_genesis_checkpoint_sha256,
                    genesis_loss,
                ),
                (final_measurement, checkpoint_sha256, final_loss),
            ):
                if (
                    not isinstance(measurement, dict)
                    or measurement.get("schema_version")
                    != "ember-heldout-loss-measurement-v2"
                    or measurement.get("checkpoint_manifest_sha256")
                    != expected_checkpoint
                    or any(
                        measurement.get(field) != expected
                        for field, expected in common_measurement.items()
                    )
                    or measurement.get("loss") != expected_loss
                ):
                    measurements_bound = False
            if (
                not isinstance(heldout_tokens, int)
                or isinstance(heldout_tokens, bool)
                or heldout_tokens < 1_000_000
                or not isinstance(genesis_loss, (int, float))
                or isinstance(genesis_loss, bool)
                or not math.isfinite(genesis_loss)
                or genesis_loss <= 0
                or not isinstance(final_loss, (int, float))
                or isinstance(final_loss, bool)
                or not math.isfinite(final_loss)
                or final_loss < 0
                or final_loss > genesis_loss * 0.9
                or not measurements_bound
            ):
                errors.append(
                    "training.sufficient_pretraining.stopping_evaluation: "
                    "requires checkpoint-bound common heldout evidence with 10% loss improvement"
                )
    progression_path = sufficient_evidence_paths.get("checkpoint_progression")
    checkpoint_count = None
    genesis_checkpoint_sha256 = None
    terminal_checkpoint_sha256 = None
    if progression_path is not None:
        try:
            progression = json.loads(progression_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            progression = None
        entries = progression.get("entries") if isinstance(progression, dict) else None
        if (
            not isinstance(progression, dict)
            or progression.get("schema_version") != "ember-checkpoint-progression-v2"
            or not isinstance(entries, list)
            or len(entries) < 3
        ):
            errors.append(
                "training.sufficient_pretraining.checkpoint_progression: "
                "content-addressed checkpoint entries missing"
            )
        else:
            checkpoint_count = len(entries)
            checkpoint_hashes: list[str] = []
            checkpoint_tokens: list[int] = []
            final_path = None
            for index, entry in enumerate(entries):
                prefix = (
                    "training.sufficient_pretraining.checkpoint_progression"
                    f".entries[{index}]"
                )
                if not isinstance(entry, dict):
                    errors.append(f"{prefix}: expected object")
                    continue
                checkpoint_record = entry.get("checkpoint_manifest")
                resolved_checkpoint = _verify_file(
                    root, checkpoint_record, f"{prefix}.checkpoint_manifest", errors
                )
                checkpoint_hash = (
                    checkpoint_record.get("sha256")
                    if isinstance(checkpoint_record, dict)
                    else None
                )
                entry_tokens = entry.get("tokens_seen")
                if (
                    not isinstance(entry_tokens, int)
                    or isinstance(entry_tokens, bool)
                    or entry_tokens < 0
                ):
                    errors.append(f"{prefix}.tokens_seen: expected nonnegative integer")
                checkpoint_manifest = None
                if resolved_checkpoint is not None:
                    try:
                        checkpoint_manifest = json.loads(
                            resolved_checkpoint.read_text(encoding="utf-8")
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        checkpoint_manifest = None
                checkpoint_shards = (
                    checkpoint_manifest.get("shards")
                    if isinstance(checkpoint_manifest, dict)
                    else None
                )
                checkpoint_cursor = (
                    checkpoint_manifest.get("data_cursor")
                    if isinstance(checkpoint_manifest, dict)
                    else None
                )
                checkpoint_manifest_valid = (
                    isinstance(checkpoint_manifest, dict)
                    and checkpoint_manifest.get("schema_version")
                    == "ember-sparse-checkpoint-v3"
                    and isinstance(checkpoint_shards, list)
                    and bool(checkpoint_shards)
                    and isinstance(checkpoint_cursor, dict)
                    and checkpoint_cursor.get("tokens_seen") == entry_tokens
                )
                if not checkpoint_manifest_valid:
                    errors.append(f"{prefix}.checkpoint_manifest: invalid checkpoint structure")
                elif resolved_checkpoint is not None and index != checkpoint_count - 1:
                    for shard_index, shard_record in enumerate(checkpoint_shards):
                        shard_path = _verify_file(
                            resolved_checkpoint.parent,
                            shard_record,
                            f"{prefix}.checkpoint_manifest.shards[{shard_index}]",
                            errors,
                        )
                        expected_bytes = (
                            shard_record.get("bytes")
                            if isinstance(shard_record, dict)
                            else None
                        )
                        if (
                            not isinstance(expected_bytes, int)
                            or isinstance(expected_bytes, bool)
                            or expected_bytes < 0
                        ):
                            errors.append(
                                f"{prefix}.checkpoint_manifest.shards[{shard_index}].bytes: "
                                "expected non-negative integer"
                            )
                            checkpoint_manifest_valid = False
                        elif shard_path is not None and shard_path.stat().st_size != expected_bytes:
                            errors.append(
                                f"{prefix}.checkpoint_manifest.shards[{shard_index}].bytes: "
                                "size mismatch"
                            )
                            checkpoint_manifest_valid = False
                        if shard_path is None:
                            checkpoint_manifest_valid = False
                if (
                    checkpoint_manifest_valid
                    and isinstance(entry_tokens, int)
                    and not isinstance(entry_tokens, bool)
                    and entry_tokens >= 0
                    and isinstance(checkpoint_hash, str)
                    and resolved_checkpoint is not None
                ):
                    checkpoint_hashes.append(checkpoint_hash)
                    checkpoint_tokens.append(entry_tokens)
                    final_path = checkpoint_record.get("path")
            if (
                len(checkpoint_hashes) != checkpoint_count
                or len(set(checkpoint_hashes)) != checkpoint_count
                or any(
                    later <= earlier
                    for earlier, later in zip(checkpoint_tokens, checkpoint_tokens[1:])
                )
            ):
                errors.append(
                    "training.sufficient_pretraining.checkpoint_progression: "
                    "requires distinct checkpoints with strictly increasing tokens"
                )
            else:
                genesis_checkpoint_sha256 = checkpoint_hashes[0]
                terminal_checkpoint_sha256 = checkpoint_hashes[-1]
                checkpoint_manifest_path = (
                    checkpoint.get("manifest_path") if isinstance(checkpoint, dict) else None
                )
                if (
                    terminal_checkpoint_sha256 != checkpoint_sha256
                    or final_path != checkpoint_manifest_path
                    or checkpoint_tokens[-1] != tokens_seen
                ):
                    errors.append(
                        "training.sufficient_pretraining.checkpoint_progression: "
                        "terminal checkpoint does not bind admitted subject"
                    )
    if stopping_genesis_checkpoint_sha256 != genesis_checkpoint_sha256:
        errors.append(
            "training.sufficient_pretraining.stopping_evaluation: "
            "genesis measurement does not bind checkpoint progression"
        )
    if sufficient_payload is not None:
        if sufficient_payload.get("criterion_id") != "ember-sufficient-pretraining-v2":
            errors.append("training.sufficient_pretraining receipt: criterion mismatch")
        if sufficient_payload.get("result") != "PASSED":
            errors.append("training.sufficient_pretraining receipt: result must equal PASSED")
        if sufficient_payload.get("subject_checkpoint_sha256") != checkpoint_sha256:
            errors.append("training.sufficient_pretraining receipt: checkpoint mismatch")
        if (
            sufficient_payload.get("checkpoint_count") != checkpoint_count
            or sufficient_payload.get("genesis_checkpoint_sha256")
            != genesis_checkpoint_sha256
            or sufficient_payload.get("terminal_checkpoint_sha256")
            != terminal_checkpoint_sha256
        ):
            errors.append(
                "training.sufficient_pretraining receipt: checkpoint progression mismatch"
            )
        expected_heldout_receipt = {
            "heldout_tokens": heldout_tokens,
            "genesis_loss": genesis_loss,
            "final_loss": final_loss,
            **heldout_hashes,
        }
        if any(
            sufficient_payload.get(field) != expected
            for field, expected in expected_heldout_receipt.items()
        ):
            errors.append(
                "training.sufficient_pretraining receipt: "
                "checkpoint-bound heldout evidence mismatch"
            )
        training = manifest.get("training")
        tokens_seen = sufficient_payload.get("tokens_seen")
        if (
            not isinstance(tokens_seen, int)
            or isinstance(tokens_seen, bool)
            or tokens_seen <= 0
            or not isinstance(training, dict)
            or tokens_seen != training.get("tokens_seen")
        ):
            errors.append("training.sufficient_pretraining receipt: executed tokens_seen mismatch")
        for field in ("gpu_hours", "final_loss"):
            value = sufficient_payload.get(field)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                errors.append(f"training.sufficient_pretraining receipt: executed {field} invalid")
        verifier = trusted_verifiers.get(sufficient_payload.get("verifier_sha256"))
        if verifier is None or "sufficient_pretraining" not in verifier.get("evidence_classes", []):
            errors.append("training.sufficient_pretraining receipt: verifier is not trusted")
        elif "ember-sufficient-pretraining-v2" not in verifier.get("criterion_ids", []):
            errors.append("training.sufficient_pretraining receipt: criterion is not trusted")
        else:
            verifier_path = verifier.get("_resolved_path")
            checkpoint_record = manifest.get("checkpoint")
            checkpoint_path = (
                _artifact(
                    root,
                    checkpoint_record.get("manifest_path"),
                    "checkpoint.manifest_path",
                    errors,
                )
                if isinstance(checkpoint_record, dict)
                else None
            )
            if (
                isinstance(verifier_path, Path)
                and checkpoint_path is not None
                and set(sufficient_evidence_paths) == set(sufficient_evidence_fields)
            ):
                command = [
                    sys.executable,
                    "-I",
                    str(verifier_path),
                    "--checkpoint-manifest",
                    str(checkpoint_path),
                    "--criterion-id",
                    "ember-sufficient-pretraining-v2",
                ]
                for evidence_name in sufficient_evidence_fields:
                    command.extend(
                        [f"--{evidence_name.replace('_', '-')}", str(sufficient_evidence_paths[evidence_name])]
                    )
                try:
                    completed = subprocess.run(
                        command,
                        cwd=root,
                        text=True,
                        capture_output=True,
                        timeout=120,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    errors.append(
                        f"training.sufficient_pretraining receipt: sufficiency verifier execution failed: {exc}"
                    )
                else:
                    if completed.returncode != 0:
                        errors.append(
                            "training.sufficient_pretraining receipt: sufficiency verifier execution "
                            f"failed with exit code {completed.returncode}"
                        )
                    else:
                        try:
                            executed = json.loads(completed.stdout)
                        except json.JSONDecodeError:
                            errors.append(
                                "training.sufficient_pretraining receipt: sufficiency verifier execution returned invalid JSON"
                            )
                        else:
                            executed_fields = (
                                "criterion_id",
                                "result",
                                "subject_checkpoint_sha256",
                                *sufficient_evidence_fields.values(),
                                "tokens_seen",
                                "gpu_hours",
                                "modality_tokens",
                                "checkpoint_count",
                                "genesis_checkpoint_sha256",
                                "terminal_checkpoint_sha256",
                                "heldout_tokens",
                                "genesis_loss",
                                "heldout_split_sha256",
                                "heldout_harness_sha256",
                                "heldout_protocol_sha256",
                                "genesis_measurement_sha256",
                                "final_measurement_sha256",
                                "final_loss",
                            )
                            if not isinstance(executed, dict):
                                errors.append(
                                    "training.sufficient_pretraining receipt: sufficiency verifier execution must return an object"
                                )
                            else:
                                for field in executed_fields:
                                    if field not in sufficient_payload:
                                        errors.append(
                                            "training.sufficient_pretraining receipt: "
                                            f"missing {field}"
                                        )
                                    elif field not in executed:
                                        errors.append(
                                            "training.sufficient_pretraining receipt: sufficiency verifier "
                                            f"execution missing {field}"
                                        )
                                    elif executed[field] != sufficient_payload[field]:
                                        errors.append(
                                            "training.sufficient_pretraining receipt: sufficiency verifier "
                                            f"execution {field} mismatch"
                                        )

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
                if payload.get("benchmark_id") != benchmark_id:
                    errors.append(f"{prefix} receipt: benchmark_id mismatch")
                benchmark_version = payload.get("benchmark_version")
                if not isinstance(benchmark_version, str) or not benchmark_version.strip():
                    errors.append(f"{prefix} receipt: executed evidence benchmark_version missing")
                evidence = evaluation.get("evidence")
                evidence_paths: dict[str, Path] = {}
                if not isinstance(evidence, dict):
                    errors.append(f"{prefix}: executed evidence object missing")
                else:
                    for evidence_name, receipt_field in EVALUATION_EVIDENCE.items():
                        record = evidence.get(evidence_name)
                        evidence_path = _verify_file(
                            root, record, f"{prefix}.evidence.{evidence_name}", errors
                        )
                        if evidence_path is not None:
                            evidence_paths[evidence_name] = evidence_path
                        evidence_hash = record.get("sha256") if isinstance(record, dict) else None
                        if payload.get(receipt_field) != evidence_hash:
                            errors.append(f"{prefix} receipt: executed evidence {receipt_field} mismatch")
                sample_count = payload.get("sample_count")
                if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count <= 0:
                    errors.append(f"{prefix} receipt: executed evidence sample_count must be positive")
                predictions_path = evidence_paths.get("predictions")
                if predictions_path is not None:
                    try:
                        predictions = load_predictions(predictions_path)
                    except ContractError as exc:
                        errors.append(f"{prefix} predictions: {exc}")
                    else:
                        prediction_benchmark = predictions["benchmark"]
                        prediction_bindings = {
                            "checkpoint": (
                                predictions["checkpoint_manifest_sha256"], checkpoint_sha256
                            ),
                            "model config": (
                                predictions["model_config_sha256"], model_config_sha256
                            ),
                            "tokenizer": (
                                predictions["tokenizer_sha256"], tokenizer_sha256
                            ),
                            "inference implementation": (
                                predictions["inference_implementation_sha256"],
                                payload.get("inference_implementation_sha256"),
                            ),
                            "capability": (prediction_benchmark["capability"], capability),
                            "benchmark id": (prediction_benchmark["id"], benchmark_id),
                            "benchmark version": (
                                prediction_benchmark["version"], benchmark_version
                            ),
                            "split": (
                                prediction_benchmark["split_sha256"],
                                payload.get("split_sha256"),
                            ),
                            "protocol": (
                                prediction_benchmark["protocol_sha256"],
                                payload.get("protocol_sha256"),
                            ),
                            "sample count": (len(predictions["rows"]), sample_count),
                        }
                        for binding, (actual, expected) in prediction_bindings.items():
                            if actual != expected:
                                errors.append(f"{prefix} predictions: {binding} mismatch")
                metrics = payload.get("metrics")
                if (
                    not isinstance(metrics, dict)
                    or not metrics
                    or any(
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not math.isfinite(value)
                        for value in metrics.values()
                    )
                ):
                    errors.append(f"{prefix} receipt: executed evidence metrics must be finite numeric values")
                criterion_id = CAPABILITY_CRITERIA.get(capability)
                if payload.get("criterion_id") != criterion_id:
                    errors.append(f"{prefix} receipt: capability criterion mismatch")
                if payload.get("criterion_result") != "PASSED":
                    errors.append(f"{prefix} receipt: capability criterion must be PASSED")
                verifier = trusted_verifiers.get(payload.get("verifier_sha256"))
                if verifier is None or "evaluation" not in verifier.get("evidence_classes", []):
                    errors.append(f"{prefix} receipt: verifier is not trusted")
                elif criterion_id not in verifier.get("criterion_ids", []):
                    errors.append(f"{prefix} receipt: capability criterion is not trusted")
                else:
                    verifier_path = verifier.get("_resolved_path")
                    checkpoint_record = manifest.get("checkpoint")
                    checkpoint_path = (
                        _artifact(
                            root,
                            checkpoint_record.get("manifest_path"),
                            "checkpoint.manifest_path",
                            errors,
                        )
                        if isinstance(checkpoint_record, dict)
                        else None
                    )
                    if (
                        isinstance(verifier_path, Path)
                        and checkpoint_path is not None
                        and set(evidence_paths) == set(EVALUATION_EVIDENCE)
                        and isinstance(benchmark_version, str)
                        and isinstance(criterion_id, str)
                    ):
                        command = [
                            sys.executable,
                            "-I",
                            str(verifier_path),
                            "--capability",
                            str(capability),
                            "--checkpoint-manifest",
                            str(checkpoint_path),
                            "--benchmark-id",
                            str(benchmark_id),
                            "--benchmark-version",
                            benchmark_version,
                            "--criterion-id",
                            criterion_id,
                        ]
                        for evidence_name in EVALUATION_EVIDENCE:
                            command.extend(
                                [f"--{evidence_name.replace('_', '-')}", str(evidence_paths[evidence_name])]
                            )
                        try:
                            completed = subprocess.run(
                                command,
                                cwd=root,
                                text=True,
                                capture_output=True,
                                timeout=120,
                                check=False,
                            )
                        except (OSError, subprocess.SubprocessError) as exc:
                            errors.append(f"{prefix} receipt: verifier execution failed: {exc}")
                        else:
                            if completed.returncode != 0:
                                errors.append(
                                    f"{prefix} receipt: verifier execution failed with exit code "
                                    f"{completed.returncode}"
                                )
                            else:
                                try:
                                    executed = json.loads(completed.stdout)
                                except json.JSONDecodeError:
                                    errors.append(f"{prefix} receipt: verifier execution returned invalid JSON")
                                else:
                                    executed_fields = (
                                        "capability",
                                        "result",
                                        "subject_checkpoint_sha256",
                                        "benchmark_id",
                                        "benchmark_version",
                                        *EVALUATION_EVIDENCE.values(),
                                        "sample_count",
                                        "metrics",
                                        "criterion_id",
                                        "criterion_result",
                                    )
                                    if not isinstance(executed, dict):
                                        errors.append(f"{prefix} receipt: verifier execution must return an object")
                                    else:
                                        for field in executed_fields:
                                            if executed.get(field) != payload.get(field):
                                                errors.append(
                                                    f"{prefix} receipt: verifier execution {field} mismatch"
                                                )
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
        _verify_file(
            root,
            serving_payload.get("server_implementation"),
            "cli serving manifest.server_implementation",
            errors,
        )
        model_format = serving_payload.get("model_format")
        if not isinstance(model_format, str) or not model_format.strip():
            errors.append("cli serving manifest: model_format must be non-empty")
        endpoint_url = serving_payload.get("endpoint_url")
        endpoint_valid = False
        if isinstance(endpoint_url, str):
            try:
                parsed_endpoint = urlparse(endpoint_url)
                endpoint_valid = (
                    parsed_endpoint.scheme == "http"
                    and parsed_endpoint.hostname in {"127.0.0.1", "::1", "localhost"}
                    and parsed_endpoint.username is None
                    and parsed_endpoint.password is None
                    and parsed_endpoint.query == ""
                    and parsed_endpoint.fragment == ""
                    and parsed_endpoint.path in {"", "/"}
                )
                # Accessing port validates malformed or out-of-range values.
                _ = parsed_endpoint.port
            except ValueError:
                endpoint_valid = False
        if not endpoint_valid:
            errors.append("cli serving manifest: endpoint_url must be loopback HTTP")
        if serving_payload.get("protocol") != "openai-chat-v1":
            errors.append("cli serving manifest: protocol must equal openai-chat-v1")
        if serving_payload.get("identity_path") != "/v1/models":
            errors.append("cli serving manifest: identity_path must equal /v1/models")


def validate_manifest(
    path: Path,
    trusted_verifier_registry: Path | None = None,
    expected_trusted_verifier_registry_sha256: str | None = None,
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
    if stage == "OWNED_ADMITTED" and (not isinstance(expected_trusted_verifier_registry_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_trusted_verifier_registry_sha256)):
        errors.append("trusted_verifier_registry: external authority hash is required for OWNED_ADMITTED")
    trusted_verifiers = _load_trusted_verifiers(trusted_verifier_registry, errors, expected_trusted_verifier_registry_sha256)
    _verify_lineage(manifest, errors)
    _verify_architecture(root, manifest, trusted_verifiers, errors)
    _verify_data(root, manifest, trusted_verifiers, errors)
    _verify_training(root, manifest, errors)
    _verify_checkpoint(root, manifest, errors)
    if stage == "OWNED_ADMITTED":
        training = manifest.get("training")
        if not isinstance(training, dict) or training.get("input_class") != "SEMANTIC_PRETRAINING":
            errors.append(
                "training.input_class: OWNED_ADMITTED requires SEMANTIC_PRETRAINING"
            )
        _verify_admission(root, manifest, trusted_verifiers, errors)
    return {"valid": not errors, "stage": stage, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--trusted-verifier-registry", type=Path)
    validate.add_argument("--expected-trusted-verifier-registry-sha256")
    args = parser.parse_args(argv)
    result = validate_manifest(args.manifest, args.trusted_verifier_registry, args.expected_trusted_verifier_registry_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
