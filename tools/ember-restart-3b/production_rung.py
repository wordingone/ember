# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build and independently replay the first owned four-domain vertical rung.

This is deliberately a measured launch rung, not sufficient-pretraining evidence.
Its four records are selected from deterministic, raw-owned generator replays and
their targets are recomputed locally before the input identity may admit them.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tokenizers import Tokenizer

from build_owned_audio_frames import build_records as build_audio_records
from build_owned_reasoning_tool_trajectories import build_records as build_trajectory_records
from build_owned_vision_scenes import build_records as build_vision_records
from semantic_contract import semantic_model_contract_sha256
from specialist_semantics import verify_audio_supervision, verify_image_supervision
from verify_capability_record import verify_record


ARTIFACT_ID = "owned-four-domain-production-rung-v1"
SHARD_SCHEMA = "ember-owned-pretraining-shard-v1"
RECEIPT_SCHEMA = "ember-owned-four-domain-production-rung-receipt-v1"
DATA_CLASS = "MEASURED_RUNG_NOT_SUFFICIENT_PRETRAINING"
SHARD_RELATIVE = "data/ember-restart-3b/owned-four-domain-production-rung-v1.json"
RECEIPT_RELATIVE = "data/ember-restart-3b/owned-four-domain-production-rung-v1.receipt.json"
TOKENIZER_RELATIVE = "tokenizer/tokenizer.json"
CONFIG_RELATIVE = "configs/ember-restart-3b.json"
SOURCE_RECORD_COUNT = 512
EXPERTS = ("vision", "audio", "reasoning", "tool")
PROVENANCE = {
    "borrowed_model_outputs": False,
    "borrowed_labels": False,
    "generated_labels": False,
    "model_derived_data": False,
    "teacher_outputs": False,
}
GENERATOR_RELATIVE = {
    "vision": "tools/ember-restart-3b/build_owned_vision_scenes.py",
    "audio": "tools/ember-restart-3b/build_owned_audio_frames.py",
    "reasoning": "tools/ember-restart-3b/build_owned_reasoning_tool_trajectories.py",
    "tool": "tools/ember-restart-3b/build_owned_reasoning_tool_trajectories.py",
}


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _model_markers(config: Mapping[str, Any]) -> tuple[int, int]:
    model = config.get("model")
    if not isinstance(model, Mapping) or model.get("vocab_size") != 32_000:
        raise ValueError("production rung requires the authorized 32k model contract")
    image = model.get("image_projection")
    audio = model.get("audio_projection")
    if not isinstance(image, Mapping) or image.get("input_shape") != [48, 48, 3]:
        raise ValueError("production rung requires raw 48x48x3 image projection")
    if not isinstance(audio, Mapping) or audio.get("frame_samples") != 640:
        raise ValueError("production rung requires raw 640-sample audio projection")
    return int(model["vocab_size"]) - 2, int(model["vocab_size"]) - 1


def _replay_records(root: Path) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    tokenizer_path = root / TOKENIZER_RELATIVE
    config_path = root / CONFIG_RELATIVE
    if not tokenizer_path.is_file() or not config_path.is_file():
        raise ValueError("production rung requires the frozen tokenizer and model config")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    config = _json(config_path, "model config")
    image_marker, audio_marker = _model_markers(config)
    source: dict[str, list[dict[str, object]]] = {
        "vision": build_vision_records(tokenizer, count=SOURCE_RECORD_COUNT, image_marker=image_marker),
        "audio": build_audio_records(tokenizer, count=SOURCE_RECORD_COUNT, audio_marker=audio_marker),
        "reasoning": build_trajectory_records(tokenizer, count=SOURCE_RECORD_COUNT, capability="reasoning"),
        "tool": build_trajectory_records(tokenizer, count=SOURCE_RECORD_COUNT, capability="tool"),
    }
    selected: dict[str, dict[str, object]] = {}
    replay: dict[str, dict[str, object]] = {}
    for expert in EXPERTS:
        candidates = source[expert]
        if expert == "vision":
            candidates = [record for record in candidates if record.get("scene_split") == "train"]
        if not candidates:
            raise ValueError(f"production rung source replay has no selected {expert} record")
        record = candidates[0]
        sample_id = record.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError(f"production rung source replay has malformed {expert} sample id")
        generator = root / GENERATOR_RELATIVE[expert]
        selected[expert] = record
        replay[expert] = {
            "generator_path": GENERATOR_RELATIVE[expert],
            "generator_sha256": _sha256_path(generator),
            "source_record_count": SOURCE_RECORD_COUNT,
            "selected_sample_id": sample_id,
            "selected_record_sha256": _sha256_bytes(_canonical_bytes(record)),
        }
    return selected, replay


def build_payload(root: Path) -> dict[str, Any]:
    """Generate the exact four selected records from canonical owned sources."""

    selected, replay = _replay_records(root)
    return {
        "schema_version": SHARD_SCHEMA,
        "artifact_id": ARTIFACT_ID,
        "data_class": DATA_CLASS,
        "provenance": dict(PROVENANCE),
        "records": [selected[expert] for expert in EXPERTS],
        "source_replay": replay,
    }


def _validate_raw_records(root: Path, payload: Mapping[str, Any]) -> None:
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != len(EXPERTS):
        raise ValueError("production rung requires exactly one record for every expert")
    by_expert: dict[str, Mapping[str, object]] = {}
    for record in records:
        if not isinstance(record, Mapping) or record.get("schema_version") != "ember-owned-semantic-record-v1":
            raise ValueError("production rung record schema is invalid")
        expert = record.get("active_expert")
        if not isinstance(expert, str) or expert in by_expert:
            raise ValueError("production rung experts must be unique")
        by_expert[expert] = record
    if set(by_expert) != set(EXPERTS):
        raise ValueError("production rung lacks a declared expert family")
    tokenizer = Tokenizer.from_file(str(root / TOKENIZER_RELATIVE))
    image_marker, audio_marker = _model_markers(_json(root / CONFIG_RELATIVE, "model config"))
    image = by_expert["vision"]
    image_values = image.get("image_patches_u8_base64")
    if not isinstance(image_values, list):
        raise ValueError("production vision rung lacks raw image patches")
    try:
        image_patches = [base64.b64decode(value, validate=True) for value in image_values if isinstance(value, str)]
    except (ValueError, TypeError) as error:
        raise ValueError("production vision rung raw image encoding is invalid") from error
    if len(image_patches) != len(image_values):
        raise ValueError("production vision rung raw image encoding is invalid")
    verify_image_supervision(image, patches=image_patches, tokenizer=tokenizer, image_marker=image_marker)
    audio = by_expert["audio"]
    audio_values = audio.get("audio_frames_i16le_base64")
    if not isinstance(audio_values, list):
        raise ValueError("production audio rung lacks raw audio frames")
    try:
        audio_frames = [base64.b64decode(value, validate=True) for value in audio_values if isinstance(value, str)]
    except (ValueError, TypeError) as error:
        raise ValueError("production audio rung raw audio encoding is invalid") from error
    if len(audio_frames) != len(audio_values):
        raise ValueError("production audio rung raw audio encoding is invalid")
    verify_audio_supervision(audio, frames=audio_frames, tokenizer=tokenizer, audio_marker=audio_marker)
    for expert in ("reasoning", "tool"):
        verify_record(by_expert[expert])


def build_receipt(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the receipt only after raw semantic verification and source replay."""

    if payload.get("schema_version") != SHARD_SCHEMA or payload.get("artifact_id") != ARTIFACT_ID:
        raise ValueError("production rung payload identity is invalid")
    if payload.get("data_class") != DATA_CLASS or payload.get("provenance") != PROVENANCE:
        raise ValueError("production rung must remain explicitly owned measured-rung data")
    _validate_raw_records(root, payload)
    expected = build_payload(root)
    if payload != expected:
        raise ValueError("production rung bytes do not equal the canonical owned source replay")
    records = payload["records"]
    return {
        "schema_version": RECEIPT_SCHEMA,
        "result": "VERIFIED",
        "artifact_id": ARTIFACT_ID,
        "data_class": DATA_CLASS,
        "shard_sha256": _sha256_bytes(_canonical_bytes(payload)),
        "records_sha256": _sha256_bytes(_canonical_bytes(records)),
        "domain_record_counts": {expert: 1 for expert in EXPERTS},
        "record_sha256": {record["active_expert"]: _sha256_bytes(_canonical_bytes(record)) for record in records},
        "source_replay": payload["source_replay"],
        "tokenizer_sha256": _sha256_path(root / TOKENIZER_RELATIVE),
        "model_config_sha256": _sha256_path(root / CONFIG_RELATIVE),
        "semantic_model_contract_sha256": semantic_model_contract_sha256(_json(root / CONFIG_RELATIVE, "model config")),
        "verifier_sha256": _sha256_path(Path(__file__)),
        "provenance": dict(PROVENANCE),
        "semantic_checks": {
            "vision": ["raw_image_spatial_relation_execution", "frozen_tokenizer_target"],
            "audio": ["raw_audio_signal_execution", "frozen_tokenizer_target"],
            "reasoning": ["local_answer_execution"],
            "tool": ["typed_tool_execution"],
        },
    }


def verify_bound_rung(*, root: Path, shard_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Recompute the complete source selection and reject any decorative receipt."""

    root = root.resolve()
    if root not in shard_path.resolve().parents or root not in receipt_path.resolve().parents:
        raise ValueError("production rung authority path escapes the selected repository")
    payload = _json(shard_path, "production rung shard")
    receipt = _json(receipt_path, "production rung receipt")
    expected = build_receipt(root, payload)
    if receipt != expected:
        raise ValueError("production rung receipt does not equal the recomputed source replay")
    return receipt


def verify_checked_in_production_rung(root: Path) -> dict[str, Any]:
    return verify_bound_rung(root=root, shard_path=root / SHARD_RELATIVE, receipt_path=root / RECEIPT_RELATIVE)


def write_checked_in_production_rung(root: Path) -> dict[str, Any]:
    """Materialize deterministic checked-in bytes; caller must review the resulting hashes."""

    root = root.resolve()
    payload = build_payload(root)
    receipt = build_receipt(root, payload)
    (root / SHARD_RELATIVE).write_bytes(_canonical_bytes(payload))
    (root / RECEIPT_RELATIVE).write_bytes(_canonical_bytes(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        receipt = write_checked_in_production_rung(args.repo_root)
    else:
        receipt = verify_checked_in_production_rung(args.repo_root)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
