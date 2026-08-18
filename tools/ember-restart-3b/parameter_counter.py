# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed and isolated sparse checkpoint-realization counter."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import pickle
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterator, Mapping

# ``python -I tools/ember-restart-3b/parameter_counter.py`` intentionally
# ignores ambient import configuration.  The counter's declared stream
# consumer is a sibling module, so resolve that sibling from this executable's
# own directory rather than relying on PYTHONPATH or site packages.
_COUNTER_MODULE_DIRECTORY = Path(__file__).resolve().parent
if str(_COUNTER_MODULE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_COUNTER_MODULE_DIRECTORY))

_P2B_STREAM_MANIFEST_SHA256 = "90ae6dd08430ead9f8287028ad20ed115a14d8d9fa3fc6c6c615f05e110fc9d0"
_P2B_STREAM_BUILD_RECEIPT_SHA256 = "748787e23c3100836713f6672a05629185a914563475f592c264ee977260f2d8"
_P2B_STREAM_CORPUS_ROOT_SHA256 = "42d1aac14c1e59563d348b7a53ce83dcce499a48217569d7d00a3966199141ab"
EXPERT_NAMES = ("vision", "audio", "reasoning", "tool")
ARCHITECTURE_REVISION = "ember-sparse-3b-v2"
_EXPERT_GENESIS_AUTHORITY_SCHEMA = "ember-expert-genesis-authority-v1"
_EXPERT_GENESIS_AUTHORITY_FIELDS = frozenset(
    {
        "schema_version",
        "architecture_revision",
        "model_config_sha256",
        "contract_sha256",
        "checkpoint_manifest_sha256",
        "expert_genesis_sha256",
    }
)


def _optimizer_owner_for_name(name: str) -> str:
    for expert_name in EXPERT_NAMES:
        if f".experts.{expert_name}." in name:
            return expert_name
    return "shared"
# `active_parameters` / `episode_trainable_parameters` semantics (issue #1329
# finding 3, decided not redefined): see the `_counts` docstring.
REALIZATION_RECEIPT_FIELDS = frozenset(
    {
        "schema_version", "verification_boundary", "result", "model_config_sha256",
        "subject_checkpoint_sha256", "architecture_revision", "counter_sha256",
        "allocated_parameters", "unique_parameters", "trainable_parameters",
        "served_parameters", "active_parameters", "episode_trainable_parameters",
        "active_expert_ids", "expert_genesis_sha256", "expert_parameter_sha256",
        "runtime_authority",
    }
)

_RUNTIME_AUTHORITY_NONE = {
    "schema_version": "ember-counter-runtime-authority-v1",
    "kind": "NONE",
}


def _runtime_authority_from_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Project a path-free, closed runtime witness into a measured receipt."""
    files = bundle.get("files")
    distribution = bundle.get("distribution")
    if not isinstance(files, list) or not files or not isinstance(distribution, Mapping):
        raise ValueError("tokenizer runtime authority is invalid")
    total_bytes = 0
    for item in files:
        if not isinstance(item, Mapping) or type(item.get("bytes")) is not int or item["bytes"] < 0:
            raise ValueError("tokenizer runtime authority is invalid")
        total_bytes += item["bytes"]
    return {
        "schema_version": "ember-counter-runtime-authority-v1",
        "kind": "P2B_TOKENIZERS_RECORD_V1",
        "runtime_schema_version": bundle.get("schema_version"),
        "distribution": {"name": distribution.get("name"), "version": distribution.get("version")},
        "record_sha256": bundle.get("record_sha256"),
        "compatibility": bundle.get("compatibility"),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "root_sha256": bundle.get("root_sha256"),
        "runtime_manifest_sha256": bundle.get("manifest_sha256"),
    }


def _validate_runtime_authority(value: Any) -> dict[str, Any]:
    if value == _RUNTIME_AUTHORITY_NONE:
        return dict(_RUNTIME_AUTHORITY_NONE)
    fields = {
        "schema_version", "kind", "runtime_schema_version", "distribution",
        "record_sha256", "compatibility", "file_count", "total_bytes",
        "root_sha256", "runtime_manifest_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("realization receipt runtime authority is invalid")
    if value.get("schema_version") != "ember-counter-runtime-authority-v1" or value.get("kind") != "P2B_TOKENIZERS_RECORD_V1":
        raise ValueError("realization receipt runtime authority is invalid")
    if value.get("runtime_schema_version") != "ember-p2b-tokenizer-runtime-bundle-v1":
        raise ValueError("realization receipt runtime authority is invalid")
    distribution = value.get("distribution")
    if not isinstance(distribution, Mapping) or set(distribution) != {"name", "version"} or distribution.get("name") != "tokenizers" or not isinstance(distribution.get("version"), str) or not distribution["version"]:
        raise ValueError("realization receipt runtime authority is invalid")
    compatibility = value.get("compatibility")
    if not isinstance(compatibility, Mapping) or set(compatibility) != {"python_version", "cache_tag", "abi_tag", "platform_tag"} or not all(isinstance(item, str) for item in compatibility.values()):
        raise ValueError("realization receipt runtime authority is invalid")
    for field in ("record_sha256", "root_sha256", "runtime_manifest_sha256"):
        candidate = value.get(field)
        if not isinstance(candidate, str) or len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
            raise ValueError("realization receipt runtime authority is invalid")
    if type(value.get("file_count")) is not int or value["file_count"] < 1 or type(value.get("total_bytes")) is not int or value["total_bytes"] < 0:
        raise ValueError("realization receipt runtime authority is invalid")
    return dict(value)
SPECIALIST_VERIFICATION_FIELDS = frozenset(
    {
        "schema_version",
        "result",
        "capability",
        "data_manifest_sha256",
        "tokenizer_sha256",
        "verifier_sha256",
        "data_class",
        "record_count",
        "token_count",
        "source_manifest_sha256",
        "records_artifact_sha256",
        "semantic_checks",
        "generator_replay_verified",
        "admission",
        "semantic_model_contract_sha256",
        "runtime_semantic_model_contract_sha256",
    }
)

# Deliberately uninitialized until the P2B branch is selected.  Keeping this
# named seam allows in-process authority tests to substitute only the stream
# opener without forcing an optional stream dependency into the legacy CLI.
open_specialist_stream: Any | None = None


def _specialist_stream_api() -> tuple[Any, str, str, Any]:
    """Load the P2B-only stream consumer after legacy admission is selected."""
    from specialist_stream import (
        SELECTION_CURSOR_SCHEMA_VERSION,
        TRAINING_CURSOR_SCHEMA_VERSION,
        canonical_record_bytes,
        open_specialist_stream,
    )

    return (
        canonical_record_bytes,
        SELECTION_CURSOR_SCHEMA_VERSION,
        TRAINING_CURSOR_SCHEMA_VERSION,
        globals().get("open_specialist_stream") or open_specialist_stream,
    )


@contextmanager
def _lease_p2b_tokenizer_runtime(*, bundle_root: Path, manifest_path: Path) -> Iterator[dict[str, Any]]:
    """Keep bound tokenizer bytes immutable through real P2B stream validation."""
    from tokenizer_runtime_bundle import lease_tokenizer_runtime_bundle

    with lease_tokenizer_runtime_bundle(bundle_root=bundle_root, manifest_path=manifest_path) as authority:
        yield authority


def validate_realization_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one closed receipt schema emitted by the counter."""
    if not isinstance(receipt, Mapping) or set(receipt) != REALIZATION_RECEIPT_FIELDS:
        raise ValueError("realization receipt has an invalid closed schema")
    if receipt["schema_version"] != "ember-sparse-realization-receipt-v1":
        raise ValueError("realization receipt has an unsupported schema")
    if receipt["verification_boundary"] != "VERIFIED_MEASURED" or receipt["result"] != "MEASURED":
        raise ValueError("realization receipt is not measured evidence")
    if receipt["architecture_revision"] != ARCHITECTURE_REVISION:
        raise ValueError("realization receipt architecture revision drifted")
    _validate_runtime_authority(receipt["runtime_authority"])
    for field in ("model_config_sha256", "subject_checkpoint_sha256", "counter_sha256"):
        value = receipt[field]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError(f"realization receipt has an invalid {field}")
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
        value = receipt[field]
        if type(value) is not int or value < 0:
            raise ValueError(f"realization receipt has an invalid {field}")
    active = receipt["active_expert_ids"]
    if not isinstance(active, list) or len(active) != 1 or active[0] not in {"shared", *EXPERT_NAMES}:
        raise ValueError("realization receipt has an invalid active expert route")
    for field in ("expert_genesis_sha256", "expert_parameter_sha256"):
        mapping = receipt[field]
        if not isinstance(mapping, Mapping) or set(mapping) != set(EXPERT_NAMES):
            raise ValueError(f"realization receipt has an invalid {field} map")
        for expert, digest in mapping.items():
            if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError(f"realization receipt has an invalid {field} for {expert}")
    return dict(receipt)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_value(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_p2b_stream_episode(episode: Mapping[str, Any], *, active_expert: str) -> dict[str, Any]:
    """Validate the closed stream-selection episode; legacy execution-slice episodes remain disjoint."""

    canonical_record_bytes, selection_cursor_schema_version, _training_cursor_schema_version, _open_specialist_stream = _specialist_stream_api()

    fields = {
        "schema_version", "active_expert", "selection_receipt", "selection_receipt_sha256",
        "start_selection_cursor", "end_selection_cursor", "completed_updates", "training_token_delta",
        "stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256",
    }
    if not isinstance(episode, Mapping) or set(episode) != fields:
        raise ValueError("P2B stream episode has an invalid closed schema")
    if episode.get("schema_version") != "ember-specialist-stream-episode-v1" or episode.get("active_expert") != active_expert:
        raise ValueError("P2B stream episode active expert does not match")
    capability_for_expert = {"vision": "image", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    receipt_fields = {
        "schema_version", "stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256",
        "family_root_sha256", "capability", "selection_rule_id", "selected_record_count", "selected_token_count",
        "selected_records_sha256", "selection_commitment_sha256",
    }
    receipt = episode["selection_receipt"]
    if not isinstance(receipt, Mapping) or set(receipt) != receipt_fields or receipt.get("schema_version") != "ember-owned-specialist-stream-selection-receipt-v1":
        raise ValueError("P2B stream episode selection receipt is invalid")
    expected_rule = "image_scene_split_train_v1" if active_expert == "vision" else "all_records_semantic_pretraining_v1"
    if receipt.get("capability") != capability_for_expert.get(active_expert) or receipt.get("selection_rule_id") != expected_rule:
        raise ValueError("P2B stream episode capability or rule does not match active expert")
    for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256", "selected_records_sha256", "selection_commitment_sha256"):
        _sha256_value(receipt.get(field), label=f"P2B selection {field}")
    if any(type(receipt.get(field)) is not int or receipt[field] < 1 for field in ("selected_record_count", "selected_token_count")):
        raise ValueError("P2B stream episode selection counts are invalid")
    canonical = hashlib.sha256(canonical_record_bytes(dict(receipt))).hexdigest()
    if episode.get("selection_receipt_sha256") != canonical:
        raise ValueError("P2B stream episode selection receipt hash does not match")
    cursor_fields = {"schema_version", "selection_receipt_sha256", "selection_rule_id", "selected_ordinal", "next_source_index"}
    cursors: list[dict[str, Any]] = []
    for label in ("start_selection_cursor", "end_selection_cursor"):
        cursor = episode[label]
        if not isinstance(cursor, Mapping) or set(cursor) != cursor_fields or cursor.get("schema_version") != selection_cursor_schema_version:
            raise ValueError("P2B stream episode selection cursor is invalid")
        if cursor.get("selection_receipt_sha256") != canonical or cursor.get("selection_rule_id") != expected_rule:
            raise ValueError("P2B stream episode selection cursor identity does not match")
        if any(type(cursor.get(field)) is not int or cursor[field] < 0 for field in ("selected_ordinal", "next_source_index")):
            raise ValueError("P2B stream episode selection cursor progress is invalid")
        cursors.append(dict(cursor))
    start, end = cursors
    if not (0 <= start["selected_ordinal"] < end["selected_ordinal"] <= receipt["selected_record_count"]):
        raise ValueError("P2B stream episode selected ordinal is outside the selected range")
    if (end["selected_ordinal"] - start["selected_ordinal"] != episode.get("completed_updates")
            or end["next_source_index"] <= start["next_source_index"]):
        raise ValueError("P2B stream episode cursor does not advance by completed updates")
    if type(episode.get("completed_updates")) is not int or episode["completed_updates"] < 1 or type(episode.get("training_token_delta")) is not int or episode["training_token_delta"] < 1:
        raise ValueError("P2B stream episode counters are invalid")
    for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256"):
        if episode.get(field) != receipt.get(field):
            raise ValueError("P2B stream episode authority does not match selection receipt")
    if (receipt["stream_manifest_sha256"] != _P2B_STREAM_MANIFEST_SHA256
            or receipt["stream_build_receipt_sha256"] != _P2B_STREAM_BUILD_RECEIPT_SHA256
            or receipt["corpus_root_sha256"] != _P2B_STREAM_CORPUS_ROOT_SHA256):
        raise ValueError("P2B stream episode does not bind the canonical stream authorities")
    return dict(episode)


def validate_p2b_counter_stream_authority(
    episode: Mapping[str, Any], *, active_expert: str, repo_root: Path,
    stream_manifest_path: Path, stream_build_receipt_path: Path,
    stream_manifest_bytes: bytes, stream_build_receipt_bytes: bytes,
) -> dict[str, Any]:
    """Require caller-bound stream artifacts before counter admission of a P2B episode."""
    _canonical_record_bytes, _selection_cursor_schema_version, _training_cursor_schema_version, open_specialist_stream = _specialist_stream_api()
    normalized = validate_p2b_stream_episode(episode, active_expert=active_expert)
    if not isinstance(stream_manifest_bytes, bytes) or not isinstance(stream_build_receipt_bytes, bytes):
        raise ValueError("P2B stream authority bytes are required")
    root = Path(repo_root).resolve()
    manifest_path = Path(stream_manifest_path).resolve()
    build_path = Path(stream_build_receipt_path).resolve()
    if hashlib.sha256(stream_manifest_bytes).hexdigest() != normalized["stream_manifest_sha256"]:
        raise ValueError("P2B stream manifest authority mismatch")
    if hashlib.sha256(stream_build_receipt_bytes).hexdigest() != normalized["stream_build_receipt_sha256"]:
        raise ValueError("P2B stream build receipt authority mismatch")
    stream = open_specialist_stream(
        repo_root=root, manifest_path=manifest_path,
        expected_manifest_sha256=normalized["stream_manifest_sha256"],
        expected_corpus_root_sha256=normalized["corpus_root_sha256"],
        manifest_bytes=stream_manifest_bytes,
    )
    receipt = normalized["selection_receipt"]
    family = stream.families.get(str(receipt["capability"]))
    if not isinstance(family, Mapping) or family.get("corpus_root_sha256") != normalized["family_root_sha256"]:
        raise ValueError("P2B stream family authority mismatch")
    stream.open_execution_selection(
        receipt=receipt,
        cursor=normalized["end_selection_cursor"],
        build_receipt_path=build_path,
        expected_build_receipt_sha256=normalized["stream_build_receipt_sha256"],
        expected_selection_receipt_sha256=normalized["selection_receipt_sha256"],
        build_receipt_bytes=stream_build_receipt_bytes,
    )
    return normalized


def validate_p2b_counter_checkpoint_progress(
    episode: Mapping[str, Any], candidate_data_cursor: Mapping[str, Any], parent_data_cursor: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate stream-episode progress against candidate and parent checkpoint cursors."""
    _canonical_record_bytes, _selection_cursor_schema_version, training_cursor_schema_version, _open_specialist_stream = _specialist_stream_api()
    required = {"schema_version", "selection_cursor", "global_step", "tokens_seen"}
    if not isinstance(candidate_data_cursor, Mapping) or set(candidate_data_cursor) != required:
        raise ValueError("P2B counter candidate training cursor is invalid")
    if candidate_data_cursor.get("schema_version") != training_cursor_schema_version:
        raise ValueError("P2B counter candidate training cursor schema is invalid")
    if not isinstance(episode, Mapping) or not isinstance(parent_data_cursor, Mapping):
        raise ValueError("P2B counter progress bindings are invalid")
    end = episode.get("end_selection_cursor")
    if candidate_data_cursor.get("selection_cursor") != end:
        raise ValueError("P2B counter candidate cursor does not match episode end")
    for label, value in (("parent global step", parent_data_cursor.get("global_step")), ("parent tokens", parent_data_cursor.get("tokens_seen")), ("candidate global step", candidate_data_cursor.get("global_step")), ("candidate tokens", candidate_data_cursor.get("tokens_seen")), ("completed updates", episode.get("completed_updates")), ("training token delta", episode.get("training_token_delta"))):
        if type(value) is not int or value < 0:
            raise ValueError(f"P2B counter {label} is invalid")
    if episode["completed_updates"] <= 0 or episode["training_token_delta"] <= 0:
        raise ValueError("P2B counter episode progress is invalid")
    if candidate_data_cursor["global_step"] - parent_data_cursor["global_step"] != episode["completed_updates"]:
        raise ValueError("P2B counter global-step delta does not match episode")
    if candidate_data_cursor["tokens_seen"] - parent_data_cursor["tokens_seen"] != episode["training_token_delta"]:
        raise ValueError("P2B counter token delta does not match episode")
    return dict(candidate_data_cursor)


def _validate_specialist_counter_episode(
    lineage: Mapping[str, Any], *, active_expert: str, repo_root: Path,
    stream_manifest_path: Path, stream_build_receipt_path: Path,
    stream_manifest_bytes: bytes, stream_build_receipt_bytes: bytes,
) -> dict[str, Any] | None:
    """Dispatch only the closed P2B episode shape to canonical stream reopening."""
    episode = lineage.get("episode")
    if not isinstance(episode, Mapping) or episode.get("schema_version") != "ember-specialist-stream-episode-v1":
        return None
    return validate_p2b_counter_stream_authority(
        episode,
        active_expert=active_expert,
        repo_root=repo_root,
        stream_manifest_path=stream_manifest_path,
        stream_build_receipt_path=stream_build_receipt_path,
        stream_manifest_bytes=stream_manifest_bytes,
        stream_build_receipt_bytes=stream_build_receipt_bytes,
    )


def _validate_legacy_specialist_counter_episode(episode: object, *, active_expert: str) -> None:
    """Preserve the established v4 data-verification/execution-slice episode contract."""
    capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    episode_fields = {"active_expert", "data_verification_receipt", "data_verification_receipt_sha256", "execution_slice", "execution_slice_sha256"}
    if active_expert == "vision":
        episode_fields |= {"scene_split_selection", "scene_split_selection_sha256"}
    if (not isinstance(episode, Mapping) or set(episode) != episode_fields
            or episode.get("active_expert") != active_expert or not isinstance(episode.get("data_verification_receipt"), Mapping)):
        raise ValueError("specialist v4 lineage lacks a closed active episode")
    verification = episode["data_verification_receipt"]
    if (set(verification) != SPECIALIST_VERIFICATION_FIELDS or verification.get("schema_version") != "ember-training-data-verification-v1"
            or verification.get("result") != "VERIFIED" or verification.get("data_class") != "SEMANTIC_PRETRAINING"
            or verification.get("generator_replay_verified") is not True
            or verification.get("admission") != "ADMISSIBLE_SEMANTIC_CONTRACT"
            or verification.get("semantic_model_contract_sha256") != verification.get("runtime_semantic_model_contract_sha256")
            or capability_experts.get(verification.get("capability")) != active_expert):
        raise ValueError("specialist v4 lineage has an invalid data verification receipt")
    for field in ("semantic_model_contract_sha256", "runtime_semantic_model_contract_sha256"):
        _sha256_value(verification.get(field), label=f"specialist verification {field}")
    canonical = hashlib.sha256(json.dumps(dict(verification), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if episode.get("data_verification_receipt_sha256") != canonical:
        raise ValueError("specialist v4 lineage data verification receipt hash does not match")
    execution_slice = episode.get("execution_slice")
    slice_fields = {"schema_version", "start_record", "record_count", "token_count", "records_sha256", "tokens_sha256"}
    if active_expert == "vision":
        slice_fields |= {"scene_split_record_count"}
    if (not isinstance(execution_slice, Mapping) or set(execution_slice) != slice_fields
            or execution_slice.get("schema_version") != "ember-specialist-execution-slice-v1"
            or type(execution_slice.get("start_record")) is not int or execution_slice["start_record"] < 0
            or type(execution_slice.get("record_count")) is not int or execution_slice["record_count"] <= 0
            or type(execution_slice.get("token_count")) is not int or execution_slice["token_count"] <= 0
            or execution_slice["start_record"] + execution_slice["record_count"] > verification["record_count"]):
        raise ValueError("specialist v4 lineage has an invalid execution slice")
    for field in ("records_sha256", "tokens_sha256"):
        _sha256_value(execution_slice.get(field), label=f"specialist execution slice {field}")
    slice_canonical = hashlib.sha256(json.dumps(dict(execution_slice), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if episode.get("execution_slice_sha256") != slice_canonical:
        raise ValueError("specialist v4 lineage execution slice hash does not match")
    if active_expert == "vision":
        selection = episode.get("scene_split_selection")
        selection_fields = {"schema_version", "capability", "scene_split", "full_records_artifact_sha256", "selected_record_count", "selected_token_count", "selected_records_sha256", "selected_tokens_sha256"}
        if (not isinstance(selection, Mapping) or set(selection) != selection_fields
                or selection.get("schema_version") != "ember-specialist-scene-split-selection-v1"
                or selection.get("capability") != "image" or selection.get("scene_split") != "train"
                or selection.get("full_records_artifact_sha256") != verification.get("records_artifact_sha256")
                or selection.get("selected_record_count") != execution_slice.get("scene_split_record_count")
                or execution_slice["start_record"] + execution_slice["record_count"] > selection.get("selected_record_count", 0)
                or execution_slice["token_count"] > selection.get("selected_token_count", 0)):
            raise ValueError("specialist v4 lineage has an invalid train scene split selection")
        for field in ("full_records_artifact_sha256", "selected_records_sha256", "selected_tokens_sha256"):
            _sha256_value(selection.get(field), label=f"scene split {field}")
        if any(type(selection.get(field)) is not int or selection[field] <= 0 for field in ("selected_record_count", "selected_token_count")):
            raise ValueError("specialist v4 lineage has invalid scene split counts")
        selection_canonical = hashlib.sha256(json.dumps(dict(selection), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if episode.get("scene_split_selection_sha256") != selection_canonical:
            raise ValueError("specialist v4 lineage scene split selection hash does not match")


def _read_bytes_snapshot(path: Path, *, label: str) -> tuple[bytes, str]:
    try:
        with path.open("rb") as handle:
            payload = handle.read()
    except OSError as error:
        raise ValueError(f"{label} cannot be read") from error
    return payload, hashlib.sha256(payload).hexdigest()


def _read_json_snapshot(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    payload, digest = _read_bytes_snapshot(path, label=label)
    try:
        parsed = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must contain a JSON object") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return parsed, digest
def _model_shape(config: Mapping[str, Any]) -> dict[str, int]:
    model = config.get("model")
    if not isinstance(model, dict):
        raise ValueError("model config lacks model shape")
    routing = model.get("expert_routing")
    image = model.get("image_projection")
    audio = model.get("audio_projection")
    if not isinstance(routing, dict) or not isinstance(image, dict) or not isinstance(audio, dict):
        raise ValueError("model config lacks sparse modality/routing declarations")
    if tuple(routing.get("expert_names", ())) != EXPERT_NAMES:
        raise ValueError("model config must declare the four authorized experts")
    if tuple(image.get("input_shape", ())) != (48, 48, 3) or int(image.get("output_size", -1)) != int(model.get("hidden_size", -2)):
        raise ValueError("model config must declare raw 48x48x3 projection")
    if int(audio.get("frame_samples", -1)) != 640 or int(audio.get("output_size", -1)) != int(model.get("hidden_size", -2)):
        raise ValueError("model config must declare raw 640-sample projection")
    shape = {
        "hidden_size": int(model["hidden_size"]),
        "layers": int(model["layers"]),
        "attention_heads": int(model["attention_heads"]),
        "vocab_size": int(model["vocab_size"]),
    }
    if any(value <= 0 for value in shape.values()) or shape["hidden_size"] % shape["attention_heads"]:
        raise ValueError("model config has an invalid decoder shape")
    if model.get("tied_embeddings") is not True:
        raise ValueError("model config must require tied embeddings")
    return shape


def _expected_shared(shape: Mapping[str, int]) -> dict[str, tuple[int, ...]]:
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    head_dim = hidden // shape["attention_heads"]
    expected = {
        "token_embedding.weight": (vocab, hidden),
        "lm_head.weight": (vocab, hidden),
        "image_projector.linear.weight": (hidden, 48 * 48 * 3),
        "audio_projector.linear.weight": (hidden, 640),
        "final_norm.weight": (hidden,),
    }
    for layer in range(layers):
        prefix = f"layers.{layer}."
        expected.update({
            prefix + "pre_attention_norm.weight": (hidden,),
            prefix + "attention.qkv.weight": (3 * hidden, hidden),
            prefix + "attention.q_norm.weight": (head_dim,),
            prefix + "attention.k_norm.weight": (head_dim,),
            prefix + "attention.output.weight": (hidden, hidden),
            prefix + "pre_ffn_norm.weight": (hidden,),
            prefix + "shared_ffn.up_gate.weight": (8 * hidden, hidden),
            prefix + "shared_ffn.down.weight": (hidden, 4 * hidden),
        })
    return expected


def _expected_expert(shape: Mapping[str, int], name: str) -> dict[str, tuple[int, ...]]:
    hidden, layers = shape["hidden_size"], shape["layers"]
    return {
        f"layers.{layer}.experts.{name}.up_gate.weight": (8 * hidden, hidden)
        for layer in range(layers)
    } | {
        f"layers.{layer}.experts.{name}.down.weight": (hidden, 4 * hidden)
        for layer in range(layers)
    }


class _StorageRef:
    def __init__(self, size: int, key: str = "", storage_type: str = "") -> None:
        self.size = int(size)
        self.key = key
        self.storage_type = storage_type


class _TensorMetadata:
    def __init__(self, storage: _StorageRef, offset: object, shape: object, stride: object) -> None:
        self.storage = storage
        self.offset = int(offset)
        self.shape = tuple(int(value) for value in shape)
        self.stride = tuple(int(value) for value in stride)


def _rebuild_tensor(storage: _StorageRef, offset: object, shape: object, stride: object, *unused: object) -> _TensorMetadata:
    if not isinstance(storage, _StorageRef):
        raise ValueError("checkpoint tensor lacks an authorized storage reference")
    return _TensorMetadata(storage, offset, shape, stride)


def _rebuild_parameter(value: _TensorMetadata, *unused: object) -> _TensorMetadata:
    return value


class _TensorTypeSentinel:
    """Non-executable placeholder for the exact torch.Tensor pickle global."""


def _rebuild_tensor_from_type(func: object, new_type: object, args: object, state: object) -> _TensorMetadata:
    """Extract only shape metadata from PyTorch's tensor-subtype pickle wrapper."""

    if func is not _rebuild_tensor or new_type is not _TensorTypeSentinel or not isinstance(args, tuple):
        raise ValueError("checkpoint tensor subtype wrapper is not an authorized metadata form")
    value = _rebuild_tensor(*args)
    if not isinstance(value, _TensorMetadata):
        raise ValueError("checkpoint tensor subtype wrapper did not produce tensor metadata")
    return value


class _CheckpointMetadataUnpickler(pickle.Unpickler):
    """Read only tensor metadata from a Torch zip checkpoint."""

    def persistent_load(self, persistent_id: object) -> _StorageRef:
        if not isinstance(persistent_id, tuple) or len(persistent_id) != 5 or persistent_id[0] != "storage":
            raise ValueError("checkpoint contains an unsupported persistent reference")
        storage_type = persistent_id[1]
        return _StorageRef(int(persistent_id[4]), str(persistent_id[2]), getattr(storage_type, "__name__", ""))

    def find_class(self, module: str, name: str) -> object:
        if module == "collections" and name == "OrderedDict":
            from collections import OrderedDict
            return OrderedDict
        if module == "torch._utils" and name.startswith("_rebuild_tensor"):
            return _rebuild_tensor
        if module == "torch._utils" and name == "_rebuild_parameter":
            return _rebuild_parameter
        if module == "torch._tensor" and name == "_rebuild_from_type_v2":
            return _rebuild_tensor_from_type
        if module == "torch" and name == "Tensor":
            return _TensorTypeSentinel
        if module == "torch" and name.endswith("Storage"):
            return type(name, (), {})
        raise ValueError(f"checkpoint references disallowed global {module}.{name}")


def _digest_open_handle(handle: Any) -> str:
    digest = hashlib.sha256(); handle.seek(0)
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    handle.seek(0)
    return digest.hexdigest()


def _load_checkpoint_metadata(archive: zipfile.ZipFile) -> Any:
    try:
        candidates = [name for name in archive.namelist() if name.endswith("data.pkl")]
        if len(candidates) != 1:
            raise ValueError("checkpoint zip lacks exactly one data.pkl")
        return _CheckpointMetadataUnpickler(io.BytesIO(archive.read(candidates[0]))).load()
    except (pickle.PickleError, zipfile.BadZipFile, ValueError) as error:
        raise ValueError(f"checkpoint realization cannot be safely inspected: {error}") from error


def _validate_state(state: Any, expected: Mapping[str, tuple[int, ...]], *, label: str) -> None:
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError(f"{label} state keys do not realize the authorized architecture")
    for key, tensor in state.items():
        if not isinstance(tensor, _TensorMetadata) or tensor.shape != expected[key]:
            raise ValueError(f"{label} tensor shape mismatch: {key}")


def _contiguous_stride(shape: tuple[int, ...]) -> tuple[int, ...]:
    stride: list[int] = []; next_stride = 1
    for dimension in reversed(shape):
        stride.append(next_stride); next_stride *= dimension
    return tuple(reversed(stride))


def _storage_element_bytes(storage_type: str) -> int:
    widths = {"BFloat16Storage": 2, "FloatStorage": 4, "DoubleStorage": 8, "HalfStorage": 2, "LongStorage": 8, "IntStorage": 4, "ShortStorage": 2, "CharStorage": 1, "ByteStorage": 1, "BoolStorage": 1}
    if storage_type not in widths:
        raise ValueError("shared expert genesis uses an unsupported storage type")
    return widths[storage_type]


def _tensor_raw_bytes(archive: zipfile.ZipFile, tensor: _TensorMetadata) -> bytes:
    if tensor.offset != 0 or tensor.stride != _contiguous_stride(tensor.shape):
        raise ValueError("shared expert genesis tensor is not a contiguous base storage")
    width = _storage_element_bytes(tensor.storage.storage_type)
    candidates = [name for name in archive.namelist() if name.endswith(f"data/{tensor.storage.key}")]
    if len(candidates) != 1:
        raise ValueError("shared expert genesis storage entry is ambiguous")
    raw = archive.read(candidates[0]); expected = tensor.storage.size * width
    if len(raw) != expected:
        raise ValueError("shared expert genesis storage byte size mismatch")
    required = width
    for dimension in tensor.shape: required *= dimension
    if required != len(raw):
        raise ValueError("shared expert genesis tensor does not own its full storage")
    return raw


def _expert_raw_digest(archive: zipfile.ZipFile, payload: Any, *, name: str, shape: Mapping[str, int]) -> str:
    """Hash one expert bank's raw storage bytes straight off the archive."""
    state = payload.get("model") if isinstance(payload, dict) else None
    expected = _expected_expert(shape, name)
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError(f"expert genesis payload state mismatch: {name}")
    digest = hashlib.sha256()
    for layer in range(shape["layers"]):
        for suffix in ("up_gate.weight", "down.weight"):
            tensor = state.get(f"layers.{layer}.experts.{name}.{suffix}")
            if not isinstance(tensor, _TensorMetadata):
                raise ValueError(f"expert genesis payload tensor mismatch: {name}")
            digest.update(_tensor_raw_bytes(archive, tensor))
    return digest.hexdigest()


def _verify_shared_expert_genesis(archive: zipfile.ZipFile, payload: Any, *, name: str, genesis: Mapping[str, str], shape: Mapping[str, int]) -> None:
    if _expert_raw_digest(archive, payload, name=name, shape=shape) != genesis[name]:
        raise ValueError(f"shared expert genesis hash mismatch: {name}")


def _verify_expert_trained_from_genesis(archive: zipfile.ZipFile, payload: Any, *, name: str, genesis: Mapping[str, str], shape: Mapping[str, int]) -> None:
    """Inverted genesis check: full-coverage root claims every bank trained.

    Unlike ``_verify_shared_expert_genesis`` (which requires an exact genesis
    match for the untouched pure-genesis checkpoint), a full-coverage root
    realization asserts all four banks were trained in this one episode. Byte
    evidence for that claim requires each bank's recomputed raw hash to
    DIFFER from its recorded genesis hash -- a bank still at genesis bytes
    means the manifest's claim is unearned.
    """
    if _expert_raw_digest(archive, payload, name=name, shape=shape) == genesis[name]:
        raise ValueError(f"full-coverage root expert genesis byte-verification failed (untrained): {name}")


_STORAGE_PROJECTION_SCHEMA = "ember-checkpoint-storage-projection-v1"


def _full_coverage_root_projection(manifest: Mapping[str, Any], *, active_expert: str) -> bool:
    """True when the manifest is a signed full-coverage root.

    A governed-vertical genesis run trains every expert in one episode: the
    checkpoint is specialist-active (one routed expert) yet has no lineage,
    because there is no parent — all four banks were realized from genesis in
    this same run. The discriminator is the manifest's own digest-bound storage
    projection attesting that every optimizer route was active. Any tampering
    (forged digest, partial route list, mismatched active expert, missing
    projection, or an id list widened over route bytes that are not actually
    positive for all four routes) makes this return False and the lineage
    refusal stands. The route-bytes cross-check mirrors
    ``_validate_checkpoint_storage_projection`` (checkpoint_artifacts.py) so a
    re-signed manifest that widens only the id list over a genuinely-partial
    optimizer state is refused here too, not just at governed publication.
    """
    if active_expert == "shared":
        return False
    if manifest.get("schema_version") != "ember-sparse-checkpoint-v5":
        return False
    if manifest.get("lineage") is not None:
        return False
    projection = manifest.get("storage_projection")
    if not isinstance(projection, Mapping):
        return False
    if projection.get("schema_version") != _STORAGE_PROJECTION_SCHEMA:
        return False
    declared = projection.get("projection_sha256")
    if not isinstance(declared, str):
        return False
    unsigned = {key: value for key, value in projection.items() if key != "projection_sha256"}
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != declared:
        return False
    if projection.get("active_expert") != active_expert:
        return False
    if projection.get("optimizer_state_active_expert_ids") != list(EXPERT_NAMES):
        return False
    route_bytes = projection.get("optimizer_state_tensor_storage_by_route_bytes")
    if not isinstance(route_bytes, Mapping) or set(route_bytes) != {"shared", *EXPERT_NAMES}:
        return False
    if any(type(value) is not int or value < 0 for value in route_bytes.values()):
        return False
    if route_bytes[active_expert] <= 0:
        return False
    if [name for name in EXPERT_NAMES if route_bytes[name] > 0] != list(EXPERT_NAMES):
        return False
    return True


def _validate_external_genesis_authority(
    authority: Mapping[str, Any],
    *,
    config_sha256: str,
    subject_checkpoint_sha256: str,
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    """Validate the independent, content-addressed genesis binding."""

    if set(authority) != _EXPERT_GENESIS_AUTHORITY_FIELDS:
        raise ValueError("external genesis authority has an invalid closed schema")
    if authority.get("schema_version") != _EXPERT_GENESIS_AUTHORITY_SCHEMA:
        raise ValueError("external genesis authority has an unsupported schema")
    if authority.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ValueError("external genesis authority architecture revision drifted")
    if authority.get("model_config_sha256") != config_sha256:
        raise ValueError("external genesis authority model-config hash mismatch")
    if authority.get("checkpoint_manifest_sha256") != subject_checkpoint_sha256:
        raise ValueError("external genesis authority checkpoint hash mismatch")
    contract_sha256 = _sha256_value(authority.get("contract_sha256"), label="external genesis contract hash")
    manifest_contract_sha256 = _sha256_value(manifest.get("contract_sha256"), label="checkpoint contract hash")
    if contract_sha256 != manifest_contract_sha256:
        raise ValueError("external genesis authority contract hash mismatch")
    genesis = authority.get("expert_genesis_sha256")
    if not isinstance(genesis, Mapping) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError("external genesis authority lacks the four expert hashes")
    validated_genesis: dict[str, str] = {}
    for expert in EXPERT_NAMES:
        validated_genesis[expert] = _sha256_value(
            genesis.get(expert), label=f"external {expert} genesis hash"
        )
    manifest_genesis = manifest.get("expert_genesis_sha256")
    if not isinstance(manifest_genesis, Mapping) or set(manifest_genesis) != set(EXPERT_NAMES):
        raise ValueError("checkpoint lacks the four expert genesis hashes")
    if dict(manifest_genesis) != validated_genesis:
        raise ValueError("checkpoint genesis map disagrees with external authority")
    return validated_genesis


def _inspect_realization(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    *,
    active_expert: str,
    shape: Mapping[str, int],
    full_coverage_root: bool = False,
    genesis_override: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    records = manifest.get("shards")
    if not isinstance(records, list): raise ValueError("checkpoint manifest lacks shard records")
    schema_version = manifest.get("schema_version")
    optimizer_state_layout = manifest.get("optimizer_state_layout", "legacy-v1")
    if schema_version == "ember-sparse-checkpoint-v5":
        if optimizer_state_layout == "owner-sharded-v1":
            owner_ids = manifest.get("optimizer_state_owner_ids")
            if (
                not isinstance(owner_ids, list)
                or owner_ids != [owner for owner in ("shared", *EXPERT_NAMES) if owner in owner_ids]
                or not owner_ids
            ):
                raise ValueError("checkpoint owner-sharded optimizer layout is not closed")
            required = {
                "shared-model.pt",
                "replay-state.pt",
                *(f"optimizer-state-{owner}.pt" for owner in owner_ids),
                *(f"expert-{name}.pt" for name in EXPERT_NAMES),
            }
        elif optimizer_state_layout == "legacy-v1":
            required = {
                "shared-model.pt",
                "optimizer-state.pt",
                "replay-state.pt",
                *(f"expert-{name}.pt" for name in EXPERT_NAMES),
            }
        else:
            raise ValueError("checkpoint optimizer state layout is unsupported")
    elif schema_version in {"ember-sparse-checkpoint-v3", "ember-sparse-checkpoint-v4"}:
        required = {"shared.pt", "replay-state.pt", *(f"expert-{name}.pt" for name in EXPERT_NAMES)}
    else:
        raise ValueError("checkpoint realization schema is unsupported")
    by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        relative = record.get("path") if isinstance(record, dict) else None
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts or relative in by_path:
            raise ValueError("checkpoint shard path is not bundle-relative")
        by_path[relative] = record
    if set(by_path) != required: raise ValueError("checkpoint realization shard set is not closed for its schema")
    if schema_version == "ember-sparse-checkpoint-v5":
        if manifest.get("shared_model_shard_sha256") != by_path["shared-model.pt"].get("sha256"):
            raise ValueError("checkpoint v5 split shard identity does not match its closed records")
        if optimizer_state_layout == "owner-sharded-v1":
            owner_ids = manifest["optimizer_state_owner_ids"]
            owner_hashes = manifest.get("optimizer_state_owner_shard_sha256")
            owner_by_parameter = manifest.get("optimizer_state_owner_by_parameter")
            if (
                not isinstance(owner_hashes, Mapping)
                or set(owner_hashes) != set(owner_ids)
                or not isinstance(owner_by_parameter, Mapping)
                or not owner_by_parameter
                or set(owner_by_parameter.values()) - set(owner_ids)
            ):
                raise ValueError("checkpoint owner-sharded optimizer identity is not closed")
            for owner in owner_ids:
                if owner_hashes[owner] != by_path[f"optimizer-state-{owner}.pt"].get("sha256"):
                    raise ValueError("checkpoint owner-sharded optimizer identity does not match its closed records")
        elif manifest.get("optimizer_state_shard_sha256") != by_path["optimizer-state.pt"].get("sha256"):
            raise ValueError("checkpoint v5 split shard identity does not match its closed records")
    elif manifest.get("shared_optimizer_shard_sha256") != by_path["shared.pt"].get("sha256"):
        raise ValueError("legacy shared optimizer shard identity does not match its closed record")
    if manifest.get("active_expert_ids") != [active_expert]: raise ValueError("checkpoint active expert does not match executed counter argument")
    if active_expert != "shared" and (
        schema_version not in {"ember-sparse-checkpoint-v4", "ember-sparse-checkpoint-v5"}
        or not isinstance(manifest.get("lineage"), Mapping)
    ) and not _full_coverage_root_projection(manifest, active_expert=active_expert):
        raise ValueError("specialist-active realization requires a lineage manifest")
    genesis = genesis_override if genesis_override is not None else manifest.get("expert_genesis_sha256")
    expert_hashes = manifest.get("expert_checkpoint_sha256")
    if not isinstance(genesis, dict) or set(genesis) != set(EXPERT_NAMES) or not isinstance(expert_hashes, dict) or set(expert_hashes) != set(EXPERT_NAMES): raise ValueError("checkpoint lacks the four expert genesis/checkpoint hashes")
    for name, digest in genesis.items(): _sha256_value(digest, label=f"{name} genesis hash")
    authorized_parameter_names = set(_expected_shared(shape))
    for expert_name in EXPERT_NAMES:
        authorized_parameter_names.update(_expected_expert(shape, expert_name))
    owner_state_names: set[str] = set()
    for relative, record in by_path.items():
        shard = manifest_path.parent / relative
        if not shard.is_file() or shard.stat().st_size != record.get("bytes"): raise ValueError(f"checkpoint shard byte-size mismatch: {relative}")
        try:
            with shard.open("rb") as handle:
                if _digest_open_handle(handle) != record.get("sha256"): raise ValueError(f"checkpoint shard hash mismatch: {relative}")
                if relative == "replay-state.pt": continue
                with zipfile.ZipFile(handle) as archive:
                    payload = _load_checkpoint_metadata(archive)
                    if relative in {"shared.pt", "shared-model.pt"}:
                        if relative == "shared.pt" and (not isinstance(payload, dict) or "optimizer" not in payload):
                            raise ValueError("legacy shared checkpoint lacks optimizer realization")
                        _validate_state(payload.get("model") if isinstance(payload, dict) else None, _expected_shared(shape), label="shared")
                    elif relative == "optimizer-state.pt":
                        if not isinstance(payload, dict) or "optimizer" not in payload: raise ValueError("shared checkpoint lacks optimizer realization")
                    elif relative.startswith("optimizer-state-") and optimizer_state_layout == "owner-sharded-v1":
                        owner = relative[len("optimizer-state-"):-len(".pt")]
                        if (
                            not isinstance(payload, dict)
                            or set(payload) != {"schema_version", "owner", "state", "param_groups", "optimizer_contract", "optimizer_realization"}
                            or payload.get("schema_version") != "ember-optimizer-owner-shard-v1"
                            or payload.get("owner") != owner
                            or payload.get("optimizer_contract") != manifest.get("optimizer_contract")
                            or payload.get("optimizer_realization") != manifest.get("optimizer_realization")
                            or not isinstance(payload.get("state"), Mapping)
                            or not payload["state"]
                            or not isinstance(payload.get("param_groups"), list)
                        ):
                            raise ValueError(f"checkpoint owner optimizer payload is malformed: {owner}")
                        for name in payload["state"]:
                            if (
                                not isinstance(name, str)
                                or name not in authorized_parameter_names
                                or name not in manifest["optimizer_state_owner_by_parameter"]
                                or manifest["optimizer_state_owner_by_parameter"][name] != owner
                                or _optimizer_owner_for_name(name) != owner
                                or name in owner_state_names
                            ):
                                raise ValueError("checkpoint owner optimizer payload violates parameter ownership")
                            owner_state_names.add(name)
                    else:
                        name = relative[len("expert-"):-len(".pt")]
                        if expert_hashes[name] != record["sha256"]: raise ValueError(f"checkpoint expert hash is not bound: {name}")
                        if not isinstance(payload, dict) or payload.get("expert") != name: raise ValueError(f"expert realization identifies the wrong bank: {name}")
                        _validate_state(payload.get("model"), _expected_expert(shape, name), label=f"expert {name}")
                        if active_expert == "shared": _verify_shared_expert_genesis(archive, payload, name=name, genesis=genesis, shape=shape)
                        elif full_coverage_root: _verify_expert_trained_from_genesis(archive, payload, name=name, genesis=genesis, shape=shape)
        except (OSError, zipfile.BadZipFile, ValueError) as error:
            if isinstance(error, ValueError): raise
            raise ValueError(f"checkpoint realization cannot be safely inspected: {error}") from error
    if schema_version == "ember-sparse-checkpoint-v5" and optimizer_state_layout == "owner-sharded-v1":
        if owner_state_names != set(manifest["optimizer_state_owner_by_parameter"]):
            raise ValueError("checkpoint owner optimizer projection does not match shard payloads")
    return dict(manifest)
def _counts(shape: Mapping[str, int], *, active_expert: str) -> dict[str, int]:
    """Measure the receipt's parameter-count fields.

    Decided episode-scope semantics (issue #1329 finding 3): ``active_parameters``
    and ``episode_trainable_parameters`` are always the per-step ROUTED-ACTIVE
    scope -- shared plus at most the one bank named by ``active_expert`` -- for
    every admission path, including a full-coverage root realization where the
    manifest's own storage projection attests all four banks were trained in
    the one governed-vertical episode. They never report the wider per-episode
    TRAINED set (shared plus all four banks); that would be a silent
    redefinition rippling into the byte-bound arithmetic of #1320 and into
    ``checkpoint_artifacts._validate_counter_receipt``'s architecture
    cross-check, which is explicitly not wanted. A caller who needs the wider
    trained-set figure for a full-coverage root receipt derives it itself as
    ``allocated_parameters`` (== ``total`` below), since a full-coverage root's
    trained scope is by definition the whole model.
    """
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    head_dim = hidden // shape["attention_heads"]
    shared = (
        vocab * hidden
        + layers * (4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim)
        + hidden
        + (48 * 48 * 3) * hidden
        + 640 * hidden
    )
    expert = layers * 12 * hidden * hidden
    total = shared + len(EXPERT_NAMES) * expert
    active = shared if active_expert == "shared" else shared + expert
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
    }


def execute_counter(
    *, model_config: Path, checkpoint_manifest: Path, active_expert: str,
    parent_manifest: Path | None = None, root_manifest: Path | None = None,
    p2b_repo_root: Path | None = None, p2b_stream_manifest: Path | None = None,
    p2b_stream_build_receipt: Path | None = None, p2b_tokenizer_runtime_root: Path | None = None,
    p2b_tokenizer_runtime_manifest: Path | None = None,
    expert_genesis_authority: Path | None = None,
    expert_genesis_authority_sha256: str | None = None,
) -> dict[str, Any]:
    """Measure a checkpoint using an independent genesis authority when supplied.

    The authority is a closed JSON snapshot whose expected SHA-256 is supplied
    separately; its expert map is checked against the checkpoint manifest before
    any shard payload is inspected.  Legacy in-process callers may omit this
    optional binding for compatibility, while governed external-genesis callers
    must provide both the path and expected content hash.
    """

    if active_expert not in {*EXPERT_NAMES, "shared"}:
        raise ValueError("active expert must be shared or one of the four authorized banks")
    if (expert_genesis_authority is None) != (expert_genesis_authority_sha256 is None):
        raise ValueError("external genesis authority path and SHA-256 are required together")
    config, config_sha256 = _read_json_snapshot(model_config, label="model config")
    if config.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ValueError("model config revision is not ember-sparse-3b-v2")
    shape = _model_shape(config)
    manifest_snapshot, subject_checkpoint_sha256 = _read_json_snapshot(checkpoint_manifest, label="checkpoint manifest")
    # Determined from the raw snapshot (not the post-inspection manifest) so the
    # discriminator can be threaded into `_inspect_realization` for the inverted
    # genesis byte-verification (Finding 2, issue #1329) in the same shard pass.
    full_coverage_root = _full_coverage_root_projection(manifest_snapshot, active_expert=active_expert)
    external_genesis: dict[str, str] | None = None
    if expert_genesis_authority is not None:
        expected_authority_sha256 = _sha256_value(
            expert_genesis_authority_sha256,
            label="external genesis authority SHA-256",
        )
        authority_snapshot, authority_sha256 = _read_json_snapshot(
            Path(expert_genesis_authority), label="external genesis authority"
        )
        if authority_sha256 != expected_authority_sha256:
            raise ValueError("external genesis authority content hash mismatch")
        external_genesis = _validate_external_genesis_authority(
            authority_snapshot,
            config_sha256=config_sha256,
            subject_checkpoint_sha256=subject_checkpoint_sha256,
            manifest=manifest_snapshot,
        )
    manifest = _inspect_realization(
        checkpoint_manifest,
        manifest_snapshot,
        active_expert=active_expert,
        shape=shape,
        full_coverage_root=full_coverage_root,
        genesis_override=external_genesis,
    )
    p2b_inputs = (p2b_repo_root, p2b_stream_manifest, p2b_stream_build_receipt, p2b_tokenizer_runtime_root, p2b_tokenizer_runtime_manifest)
    runtime_authority: dict[str, Any] = dict(_RUNTIME_AUTHORITY_NONE)
    if active_expert == "shared" and any(value is not None for value in p2b_inputs):
        raise ValueError("legacy counter call must not include P2B stream authority")
    if full_coverage_root:
        if any(value is not None for value in p2b_inputs):
            raise ValueError("full-coverage root counter call must not include P2B stream authority")
        if parent_manifest is not None or root_manifest is not None:
            raise ValueError("full-coverage root realization must not carry external lineage manifests")
        root_parameters = manifest.get("expert_parameter_sha256")
        if not isinstance(root_parameters, dict) or set(root_parameters) != set(EXPERT_NAMES):
            raise ValueError("full-coverage root manifest lacks closed expert parameter hashes")
        for name in EXPERT_NAMES:
            _sha256_value(root_parameters[name], label=f"root {name} parameter hash")
    if active_expert != "shared" and not full_coverage_root and (parent_manifest is None or root_manifest is None):
        raise ValueError("specialist-active realization requires external parent and root manifests")
    if active_expert != "shared" and not full_coverage_root:
        lineage = manifest.get("lineage")
        if not isinstance(lineage, Mapping):
            raise ValueError("specialist-active realization lacks v4 lineage")
        parent_manifest = Path(parent_manifest).resolve()
        root_manifest = Path(root_manifest).resolve()
        snapshot_cache: dict[Path, tuple[dict[str, Any], str]] = {}
        def external_snapshot(path: Path, label: str) -> tuple[dict[str, Any], str]:
            if path not in snapshot_cache:
                snapshot_cache[path] = _read_json_snapshot(path, label=f"external {label} manifest")
            return snapshot_cache[path]
        parent_snapshot, parent_sha256 = external_snapshot(parent_manifest, "parent")
        root_snapshot, root_sha256 = external_snapshot(root_manifest, "root")
        if lineage.get("parent_checkpoint_sha256") != parent_sha256:
            raise ValueError("specialist lineage parent checkpoint hash does not match external manifest")
        if lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
            raise ValueError("specialist lineage root checkpoint hash does not match external manifest")
        external_manifests: dict[str, dict[str, Any]] = {}
        for external_manifest, label, external, external_sha256 in ((parent_manifest, "parent", parent_snapshot, parent_sha256), (root_manifest, "root", root_snapshot, root_sha256)):
            external_active = external.get("active_expert_ids")
            if not isinstance(external_active, list) or len(external_active) != 1:
                raise ValueError(f"external {label} manifest lacks one active expert")
            external_manifests[label] = _inspect_realization(external_manifest, external, active_expert=external_active[0], shape=shape)
        parent_external, root_external = external_manifests["parent"], external_manifests["root"]
        parent_lineage = parent_external.get("lineage")
        if not isinstance(parent_lineage, Mapping):
            if parent_sha256 != root_sha256:
                raise ValueError("first specialist successor requires matching external parent and root")
            parent_history: list[str] = []
        else:
            if not isinstance(parent_lineage, Mapping) or parent_lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
                raise ValueError("external parent does not bind the supplied immutable root")
            parent_history = parent_lineage.get("trained_expert_ids")
            if not isinstance(parent_history, list):
                raise ValueError("external parent has invalid trained expert history")
        if any(name not in EXPERT_NAMES for name in parent_history) or len(set(parent_history)) != len(parent_history):
            raise ValueError("external parent has invalid trained expert history")
        expected_history = [*parent_history, *([] if active_expert in parent_history else [active_expert])]
        episode = lineage.get("episode")
        if isinstance(episode, Mapping) and episode.get("schema_version") == "ember-specialist-stream-episode-v1":
            if any(value is None for value in p2b_inputs):
                raise ValueError("P2B counter requires explicit stream authority inputs")
            assert p2b_repo_root is not None and p2b_stream_manifest is not None and p2b_stream_build_receipt is not None and p2b_tokenizer_runtime_root is not None and p2b_tokenizer_runtime_manifest is not None
            stream_manifest_bytes, _ = _read_bytes_snapshot(Path(p2b_stream_manifest), label="P2B stream manifest")
            stream_build_receipt_bytes, _ = _read_bytes_snapshot(Path(p2b_stream_build_receipt), label="P2B stream build receipt")
            with _lease_p2b_tokenizer_runtime(
                bundle_root=Path(p2b_tokenizer_runtime_root),
                manifest_path=Path(p2b_tokenizer_runtime_manifest),
            ) as p2b_tokenizer_runtime:
                runtime_authority = _runtime_authority_from_bundle(p2b_tokenizer_runtime)
                p2b_episode = _validate_specialist_counter_episode(
                    lineage,
                    active_expert=active_expert,
                    repo_root=Path(p2b_repo_root),
                    stream_manifest_path=Path(p2b_stream_manifest),
                    stream_build_receipt_path=Path(p2b_stream_build_receipt),
                    stream_manifest_bytes=stream_manifest_bytes,
                    stream_build_receipt_bytes=stream_build_receipt_bytes,
                )
            validate_p2b_counter_checkpoint_progress(
                p2b_episode,
                manifest.get("data_cursor"),
                parent_external.get("data_cursor"),
            )
        else:
            if any(value is not None for value in p2b_inputs):
                raise ValueError("legacy counter call must not include P2B stream authority")
            _validate_legacy_specialist_counter_episode(lineage.get("episode"), active_expert=active_expert)
        candidate_parameters = manifest.get("expert_parameter_sha256")
        parent_parameters = parent_external.get("expert_parameter_sha256", parent_external.get("expert_genesis_sha256"))
        root_parameters = root_external.get("expert_parameter_sha256", root_external.get("expert_genesis_sha256"))
        candidate_files = manifest.get("expert_checkpoint_sha256")
        parent_files = parent_external.get("expert_checkpoint_sha256")
        history = lineage.get("trained_expert_ids")
        if (not isinstance(candidate_parameters, dict) or set(candidate_parameters) != set(EXPERT_NAMES)
                or not isinstance(parent_parameters, dict) or set(parent_parameters) != set(EXPERT_NAMES)
                or not isinstance(root_parameters, dict) or set(root_parameters) != set(EXPERT_NAMES)
                or not isinstance(candidate_files, dict) or not isinstance(parent_files, dict)
                or history != expected_history):
            raise ValueError("specialist v4 lineage lacks closed expert accretion fields")
        for name in EXPERT_NAMES:
            _sha256_value(candidate_parameters[name], label=f"candidate {name} parameter hash")
        if candidate_parameters[active_expert] == parent_parameters[active_expert]:
            raise ValueError("active expert parameter content does not differ from parent")
        for name in EXPERT_NAMES:
            if name == active_expert:
                continue
            if candidate_files.get(name) != parent_files.get(name):
                raise ValueError(f"inactive expert file does not match parent: {name}")
            if candidate_parameters[name] != parent_parameters[name]:
                raise ValueError(f"inactive expert parameter content does not match parent: {name}")
            if name not in history and candidate_parameters[name] != root_parameters[name]:
                raise ValueError(f"untrained expert parameter content does not match root: {name}")
    _counter_bytes, counter_sha256 = _read_bytes_snapshot(Path(__file__), label="counter source")
    if manifest.get("model_config_sha256") != config_sha256:
        raise ValueError("checkpoint model-config hash mismatch")
    return validate_realization_receipt({
        "schema_version": "ember-sparse-realization-receipt-v1",
        "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED",
        "model_config_sha256": config_sha256,
        "subject_checkpoint_sha256": subject_checkpoint_sha256,
        "architecture_revision": ARCHITECTURE_REVISION,
        "counter_sha256": counter_sha256,
        **_counts(shape, active_expert=active_expert),
        "active_expert_ids": [active_expert],
        "expert_genesis_sha256": dict(manifest["expert_genesis_sha256"]),
        "expert_parameter_sha256": dict(manifest.get("expert_parameter_sha256", manifest["expert_genesis_sha256"])),
        "runtime_authority": runtime_authority,
    })


def measure_parameter_counts(model: Any) -> dict[str, Any]:
    """Measure total allocated capacity and one active episode path in-process."""

    total = model.count_unique_trainable_parameters(include_frozen=True)
    active = model.count_unique_trainable_parameters()
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
        "active_expert_ids": [model.active_expert],
    }


def measure_dense_a1_parameter_counts(model: Any) -> dict[str, Any]:
    """Measure the distinct dense carrier without sparse-route semantics."""

    from a1_dense import DenseA1Decoder

    if not isinstance(model, DenseA1Decoder):
        raise ValueError("dense A1 counter requires DenseA1Decoder")
    named = list(model.named_parameters())
    if len({id(parameter) for _, parameter in named}) != len(named):
        raise ValueError("dense A1 live parameter inventory contains aliases")
    unique = sum(parameter.numel() for _, parameter in named)
    structural = model.config.structural_parameter_count()
    if unique != structural:
        raise ValueError("dense A1 live parameter inventory differs from structure")
    return {
        "schema_version": "ember-a1-dense-parameter-inventory-v1",
        "architecture_revision": "ember-dense-a1-3b-v1",
        "unique_parameters": unique,
        "trainable_parameters": sum(
            parameter.numel() for _, parameter in named if parameter.requires_grad
        ),
        "active_parameters": unique,
        "contains_router_or_experts": False,
        "parameter_tensors": len(named),
    }


def write_parameter_receipt(
    model: Any,
    config_path: Path,
    checkpoint_manifest_path: Path,
    expert_genesis_sha256: dict[str, str],
) -> dict[str, Any]:
    """Emit an in-process receipt; production must also execute this file under -I."""

    counts = measure_parameter_counts(model)
    return {
        "schema_version": "ember-sparse-parameter-receipt-v1",
        "result": "MEASURED",
        "model_config_sha256": _sha256(config_path),
        "counter_sha256": _read_bytes_snapshot(Path(__file__), label="counter source")[1],
        "subject_checkpoint_sha256": _sha256(checkpoint_manifest_path),
        "architecture_revision": ARCHITECTURE_REVISION,
        **counts,
        "expert_genesis_sha256": dict(expert_genesis_sha256),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a sparse checkpoint realization and emit its measured capacity.")
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--checkpoint-manifest", type=Path, required=True)
    parser.add_argument("--active-expert", required=True)
    parser.add_argument("--parent-manifest", type=Path)
    parser.add_argument("--root-manifest", type=Path)
    parser.add_argument("--p2b-repo-root", type=Path)
    parser.add_argument("--p2b-stream-manifest", type=Path)
    parser.add_argument("--p2b-stream-build-receipt", type=Path)
    parser.add_argument("--p2b-tokenizer-runtime-root", type=Path)
    parser.add_argument("--p2b-tokenizer-runtime-manifest", type=Path)
    parser.add_argument("--expert-genesis-authority", type=Path)
    parser.add_argument("--expert-genesis-authority-sha256")
    args = parser.parse_args(argv)
    try:
        counter_kwargs = {
            "model_config": args.model_config,
            "checkpoint_manifest": args.checkpoint_manifest,
            "active_expert": args.active_expert,
            "parent_manifest": args.parent_manifest,
            "root_manifest": args.root_manifest,
            "p2b_repo_root": args.p2b_repo_root,
            "p2b_stream_manifest": args.p2b_stream_manifest,
            "p2b_stream_build_receipt": args.p2b_stream_build_receipt,
            "p2b_tokenizer_runtime_root": args.p2b_tokenizer_runtime_root,
            "p2b_tokenizer_runtime_manifest": args.p2b_tokenizer_runtime_manifest,
        }
        if args.expert_genesis_authority is not None or args.expert_genesis_authority_sha256 is not None:
            counter_kwargs.update(
                expert_genesis_authority=args.expert_genesis_authority,
                expert_genesis_authority_sha256=args.expert_genesis_authority_sha256,
            )
        print(json.dumps(execute_counter(**counter_kwargs), sort_keys=True))
    except Exception as error:
        print(f"parameter realization failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
