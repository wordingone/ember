# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit content-addressed, non-admitted owned specialist data manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from tokenizers import Tokenizer

from build_owned_audio_frames import build_records as build_audio_records
from build_owned_reasoning_tool_trajectories import build_records as build_trajectory_records
from build_owned_vision_scenes import build_records as build_vision_records
from semantic_contract import semantic_model_contract_sha256, SCHEMA_VERSION


CAPABILITIES = ("image", "audio", "reasoning", "tool")
MIN_ADMISSIBLE_RECORDS = 4_096
MIN_ADMISSIBLE_TOKENS = 24_576
DEFAULT_PRODUCTION_RECORDS = 65_536
GENERATOR_NAMES = {
    "image": "build_owned_vision_scenes.py",
    "audio": "build_owned_audio_frames.py",
    "reasoning": "build_owned_reasoning_tool_trajectories.py",
    "tool": "build_owned_reasoning_tool_trajectories.py",
}
DERIVATIONS = {
    "image": "raw_image_property_execution",
    "audio": "raw_audio_signal_execution",
    "reasoning": "local_answer_execution",
    "tool": "typed_tool_execution",
}
DESCRIPTIONS = {
    "image": "Owned raw RGB patch scenes with captions recomputed from component pixels.",
    "audio": "Owned raw little-endian PCM frames with captions recomputed from signal polarity.",
    "reasoning": "Owned arithmetic trajectories with sums executed locally from integer operands.",
    "tool": "Owned typed calculator trajectories with observations executed from expressions.",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return _sha256(path)


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError as error:
        raise ValueError("bundle paths must remain within repo_root") from error


def _config_markers(payload: dict[str, Any]) -> tuple[int, int]:
    model = payload.get("model") if isinstance(payload, dict) else None
    if not isinstance(model, dict) or model.get("vocab_size") != 32_000:
        raise ValueError("model config must declare the authorized 32k vocabulary")
    image = model.get("image_projection")
    audio = model.get("audio_projection")
    if not isinstance(image, dict) or image.get("input_shape") != [48, 48, 3] or not isinstance(audio, dict) or audio.get("frame_samples") != 640:
        raise ValueError("model config must declare authorized raw modality shapes")
    return 31_998, 31_999


def _model_contract_ref(repo_root: Path, model_config_path: Path, config_payload: dict[str, Any]) -> dict[str, str]:
    return {"schema_version": SCHEMA_VERSION, "path": _relative(repo_root, model_config_path), "semantic_sha256": semantic_model_contract_sha256(config_payload)}


def _records(tokenizer: Tokenizer, capability: str, *, count: int, image_marker: int, audio_marker: int) -> list[dict[str, object]]:
    if capability == "image":
        return build_vision_records(tokenizer, count=count, image_marker=image_marker)
    if capability == "audio":
        return build_audio_records(tokenizer, count=count, audio_marker=audio_marker)
    # Numeric transcripts require six next-token positions; 704 clears the 4096-token floor.
    return build_trajectory_records(tokenizer, count=max(count, 704), capability=capability)


def emit_bundle(*, repo_root: Path, output_root: Path, tokenizer_path: Path, model_config_path: Path, count: int) -> dict[str, Path]:
    """Emit four source-bound manifests. Output is preparation, never admission."""

    if not isinstance(count, int) or count < MIN_ADMISSIBLE_RECORDS:
        raise ValueError(f"specialist bundle requires at least {MIN_ADMISSIBLE_RECORDS} requested records per family")
    repo_root = repo_root.resolve()
    output_root = output_root.resolve()
    if repo_root not in output_root.parents:
        raise ValueError("bundle output must reside below repo_root")
    tokenizer_path = tokenizer_path.resolve()
    model_config_path = model_config_path.resolve()
    if repo_root not in tokenizer_path.parents or repo_root not in model_config_path.parents:
        raise ValueError("tokenizer and model config must reside below repo_root")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    config_bytes = model_config_path.read_bytes()
    try:
        config_payload = json.loads(config_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("model config is not valid JSON") from error
    if not isinstance(config_payload, dict):
        raise ValueError("model config must be an object")
    image_marker, audio_marker = _config_markers(config_payload)
    tokenizer_hash = _sha256(tokenizer_path)
    model_contract_ref = _model_contract_ref(repo_root, model_config_path, config_payload)
    emitted: dict[str, Path] = {}
    for capability in CAPABILITIES:
        records = _records(tokenizer, capability, count=count, image_marker=image_marker, audio_marker=audio_marker)
        records_path = output_root / "records" / f"{capability}.json"
        records_hash = _write_json(records_path, {"schema_version": "ember-owned-semantic-records-v1", "records": records})
        generator_path = repo_root / "tools" / "ember-restart-3b" / GENERATOR_NAMES[capability]
        if not generator_path.is_file():
            raise ValueError("authorized specialist generator source is missing")
        source_path = output_root / "sources" / f"{capability}.json"
        source_hash = _write_json(source_path, {
            "schema_version": "ember-owned-source-v1", "capability": capability,
            "model_mediated": False, "borrowed_labels": False,
            "semantic_provenance": {
                "schema_version": "ember-owned-semantic-source-v1", "origin": "owned_raw_samples",
                "target_derivation": DERIVATIONS[capability], "source_description": DESCRIPTIONS[capability],
                "minimum_record_count": MIN_ADMISSIBLE_RECORDS, "minimum_token_count": MIN_ADMISSIBLE_TOKENS,
                "generator": {"path": _relative(repo_root, generator_path), "sha256": _sha256(generator_path)},
                "generation": {"schema_version": "ember-owned-specialist-generation-v1", "record_count": len(records)},
            },
        })
        manifest_path = output_root / "manifests" / f"{capability}.json"
        manifest: dict[str, Any] = {
            "schema_version": "ember-owned-training-data-v1", "capability": capability,
            "data_class": "SEMANTIC_PRETRAINING", "tokenizer_sha256": tokenizer_hash,
            "model_mediated": False, "borrowed_labels": False,
            "record_count": len(records), "token_count": sum(len(record["token_ids"]) for record in records),
            "source_manifest": {"path": _relative(repo_root, source_path), "sha256": source_hash},
            "records_artifact": {"path": _relative(repo_root, records_path), "sha256": records_hash},
            "model_contract": model_contract_ref,
        }
        _write_json(manifest_path, manifest)
        emitted[capability] = manifest_path
    return emitted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--count", type=int, default=DEFAULT_PRODUCTION_RECORDS)
    args = parser.parse_args()
    emitted = emit_bundle(repo_root=args.repo_root, output_root=args.output_root, tokenizer_path=args.tokenizer, model_config_path=args.model_config, count=args.count)
    print(json.dumps({capability: str(path) for capability, path in emitted.items()}, sort_keys=True))


if __name__ == "__main__":
    main()