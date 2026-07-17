# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Independently verify one owned semantic text training-data manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from semantic_contract import semantic_model_contract_sha256, SCHEMA_VERSION

SEMANTIC_CHECKS = {
    "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"],
    "image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"],
    "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"],
    "text": ["token_roundtrip", "source_target_pair"],
    "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"],
}

# A source must be substantial before its structural records can be called semantic
# pretraining.  These floors deliberately exclude the former one-row byte-ramp
# fixture; they are an admission floor, not a claim of sufficient pretraining.
CANONICAL_GENERATORS = {
    "image": "build_owned_vision_scenes.py",
    "audio": "build_owned_audio_frames.py",
    "reasoning": "build_owned_reasoning_tool_trajectories.py",
    "tool": "build_owned_reasoning_tool_trajectories.py",
}


def _replay_bound_specialist_records(
    *, capability: str, generation: object, generator_path: Path, tokenizer: object,
    raw_contract: Mapping[str, int] | None, records: list[Mapping[str, Any]],
) -> None:
    """Re-execute only known owned generators and compare their complete record sequence."""

    if generation is None:
        return
    if not isinstance(generation, Mapping) or set(generation) != {"schema_version", "record_count"}:
        raise ValueError("specialist generator replay metadata is invalid")
    count = generation.get("record_count")
    if generation.get("schema_version") != "ember-owned-specialist-generation-v1" or type(count) is not int or count < 512 or count != len(records):
        raise ValueError("specialist generator replay metadata does not bind the records")
    expected_name = CANONICAL_GENERATORS[capability]
    if generator_path.resolve() != Path(__file__).with_name(expected_name).resolve():
        raise ValueError("specialist generator replay requires the canonical owned generator path")
    if capability == "image":
        from build_owned_vision_scenes import build_records
        if raw_contract is None:
            raise ValueError("image generator replay lacks the bound marker")
        replayed = build_records(tokenizer, count=count, image_marker=raw_contract["image_marker"])
    elif capability == "audio":
        from build_owned_audio_frames import build_records
        if raw_contract is None:
            raise ValueError("audio generator replay lacks the bound marker")
        replayed = build_records(tokenizer, count=count, audio_marker=raw_contract["audio_marker"])
    else:
        from build_owned_reasoning_tool_trajectories import build_records
        replayed = build_records(tokenizer, count=count, capability=capability)
    if replayed != records:
        raise ValueError("specialist records do not match the bound generator replay")

SPECIALIST_MINIMUMS = {
    "image": {"records": 4096, "tokens": 24576, "derivation": "raw_image_spatial_relation_execution"},
    "audio": {"records": 4096, "tokens": 24576, "derivation": "raw_audio_signal_execution"},
    "reasoning": {"records": 4096, "tokens": 24576, "derivation": "local_answer_execution"},
    "tool": {"records": 4096, "tokens": 24576, "derivation": "typed_tool_execution"},
}


def _read_authority_bytes(path: Path, name: str) -> tuple[bytes, str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{name} cannot be read") from exc
    return payload, hashlib.sha256(payload).hexdigest()


def _json_from_authority_bytes(payload: bytes, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be an object")
    return parsed


def _read_authority_json(path: Path, name: str) -> tuple[dict[str, Any], str]:
    payload, digest = _read_authority_bytes(path, name)
    return _json_from_authority_bytes(payload, name), digest


def _bound_file(root: Path, record: object, name: str) -> tuple[Path, bytes, str]:
    if not isinstance(record, Mapping):
        raise ValueError(f"{name} must be a path and sha256 record")
    relative = record.get("path")
    expected = record.get("sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"{name} path must be nonempty and relative")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"{name} sha256 is malformed")
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError(f"{name} path escapes verifier root")
    payload, digest = _read_authority_bytes(path, name)
    if digest != expected:
        raise ValueError(f"{name} sha256 does not match")
    return path, payload, digest



def _bound_semantic_contract(root: Path, record: object) -> tuple[dict[str, Any], str]:
    if not isinstance(record, Mapping) or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("semantic model contract binding is missing or malformed")
    relative = record.get("path")
    expected = record.get("semantic_sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("semantic model contract path must be nonempty and relative")
    if not isinstance(expected, str) or len(expected) != 64 or expected.lower() != expected:
        raise ValueError("semantic model contract sha256 is malformed")
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("semantic model contract path escapes verifier root")
    payload_bytes, _file_sha256 = _read_authority_bytes(path, "semantic model contract")
    payload = _json_from_authority_bytes(payload_bytes, "semantic model contract")
    actual = semantic_model_contract_sha256(payload)
    if actual != expected:
        raise ValueError("semantic model contract sha256 does not match")
    return payload, actual

def verify(data_path: Path, tokenizer_path: Path, capability: str, *, root: Path) -> dict[str, Any]:
    if capability not in SEMANTIC_CHECKS:
        raise ValueError("unsupported semantic capability")
    data_path = data_path.resolve()
    if root not in data_path.parents:
        raise ValueError("data manifest escapes verifier root")
    data, data_sha256 = _read_authority_json(data_path, "data manifest")
    if data.get("schema_version") != "ember-owned-training-data-v1":
        raise ValueError("data manifest schema is invalid")
    if data.get("capability") != capability or data.get("data_class") != "SEMANTIC_PRETRAINING":
        raise ValueError("data manifest capability or class is invalid")
    if data.get("model_mediated") is not False or data.get("borrowed_labels") is not False:
        raise ValueError("data manifest provenance is invalid")
    tokenizer_bytes, tokenizer_hash = _read_authority_bytes(tokenizer_path, "tokenizer")
    verifier_bytes, verifier_sha256 = _read_authority_bytes(Path(__file__), "verifier source")
    if data.get("tokenizer_sha256") != tokenizer_hash:
        raise ValueError("data manifest tokenizer sha256 does not match")
    raw_contract: dict[str, int] | None = None
    semantic_contract_sha256: str | None = None
    semantic_contract_payload: dict[str, Any] | None = None
    if isinstance(data.get("model_contract"), Mapping):
        semantic_contract_payload, semantic_contract_sha256 = _bound_semantic_contract(root, data.get("model_contract"))
        config = semantic_contract_payload.get("model")
        if not isinstance(config, Mapping) or not isinstance(config.get("vocab_size"), int):
            raise ValueError("semantic model contract lacks a valid vocabulary")
    elif capability in {"image", "audio"}:
        # Legacy fixtures are retained for migration evidence only; emitted
        # specialist bundles use model_contract and are checked below.
        _config_path, config_bytes, _config_sha256 = _bound_file(root, data.get("model_config"), "model config")
        config = _json_from_authority_bytes(config_bytes, "model config").get("model")
        if not isinstance(config, Mapping) or not isinstance(config.get("vocab_size"), int):
            raise ValueError("model config lacks a valid vocabulary")
    else:
        config = None
    if capability in {"image", "audio"}:
        if not isinstance(config, Mapping):
            raise ValueError("model contract lacks modality configuration")
        image = config.get("image_projection")
        audio = config.get("audio_projection")
        if not isinstance(image, Mapping) or not isinstance(audio, Mapping) or image.get("input_shape") != [48, 48, 3] or audio.get("frame_samples") != 640:
            raise ValueError("model contract lacks the authorized raw modality shapes")
        raw_contract = {"image_marker": config["vocab_size"] - 2, "audio_marker": config["vocab_size"] - 1}

    source_path, source_bytes, source_sha256 = _bound_file(root, data.get("source_manifest"), "source manifest")
    records_path, records_bytes, records_sha256 = _bound_file(root, data.get("records_artifact"), "records artifact")
    source = _json_from_authority_bytes(source_bytes, "source manifest")
    if (
        source.get("schema_version") != "ember-owned-source-v1"
        or source.get("capability") != capability
        or source.get("model_mediated") is not False
        or source.get("borrowed_labels") is not False
    ):
        raise ValueError("source manifest provenance is invalid")
    specialist_minimum = SPECIALIST_MINIMUMS.get(capability)
    if specialist_minimum is not None:
        semantic_source = source.get("semantic_provenance")
        if (
            not isinstance(semantic_source, Mapping)
            or semantic_source.get("schema_version") != "ember-owned-semantic-source-v1"
            or semantic_source.get("origin") != "owned_raw_samples"
            or semantic_source.get("target_derivation") != specialist_minimum["derivation"]
            or not isinstance(semantic_source.get("source_description"), str)
            or len(semantic_source["source_description"].strip()) < 40
            or type(semantic_source.get("minimum_record_count")) is not int
            or semantic_source["minimum_record_count"] < specialist_minimum["records"]
            or type(semantic_source.get("minimum_token_count")) is not int
            or semantic_source["minimum_token_count"] < specialist_minimum["tokens"]
        ):
            raise ValueError("semantic source provenance is insufficient for specialist pretraining")
        generator_path, _generator_bytes, _generator_sha256 = _bound_file(root, semantic_source.get("generator"), "semantic source generator")
        if generator_path.suffix != ".py":
            raise ValueError("semantic source generator must bind Python generator bytes")
        generation = semantic_source.get("generation")
        if generation is not None and semantic_contract_sha256 is None:
            raise ValueError("generated specialist bundle must bind a semantic model contract")
    tokenizer = _json_from_authority_bytes(tokenizer_bytes, "tokenizer")
    vocab = tokenizer.get("model", {}).get("vocab") if isinstance(tokenizer.get("model"), dict) else None
    if not isinstance(vocab, dict) or not vocab:
        raise ValueError("tokenizer does not declare a vocabulary")
    vocab_size = max(vocab.values()) + 1 if all(isinstance(value, int) and value >= 0 for value in vocab.values()) else 0
    if vocab_size <= 0:
        raise ValueError("tokenizer vocabulary is invalid")
    frozen_tokenizer = None
    if capability in {"image", "audio", "reasoning", "tool"}:
        try:
            from tokenizers import Tokenizer
            frozen_tokenizer = Tokenizer.from_str(tokenizer_bytes.decode("utf-8"))
        except Exception as error:
            raise ValueError(f"{capability} semantic verifier cannot load the exact frozen tokenizer") from error
    records_payload = _json_from_authority_bytes(records_bytes, "records artifact")
    records = records_payload.get("records")
    if records_payload.get("schema_version") != "ember-owned-semantic-records-v1" or not isinstance(records, list) or not records:
        raise ValueError("semantic records artifact is invalid")
    if specialist_minimum is not None:
        _replay_bound_specialist_records(capability=capability, generation=generation, generator_path=generator_path, tokenizer=frozen_tokenizer, raw_contract=raw_contract, records=records)
    token_count = 0
    capability_records: list[Mapping[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("semantic record is invalid")
        token_ids, target_ids = record.get("token_ids"), record.get("target_ids")
        if (
            not isinstance(token_ids, list)
            or not isinstance(target_ids, list)
            or not token_ids
            or len(token_ids) != len(target_ids)
            or any(not isinstance(token, int) or token < 0 or token >= vocab_size for token in [*token_ids, *target_ids])
            or target_ids[:-1] != token_ids[1:]
        ):
            raise ValueError("semantic record does not satisfy token roundtrip and source-target pairing")
        if capability in {"image", "audio"}:
            assert raw_contract is not None
            marker = raw_contract["image_marker" if capability == "image" else "audio_marker"]
            field = "image_patches_u8_base64" if capability == "image" else "audio_frames_i16le_base64"
            expected_bytes = 48 * 48 * 3 if capability == "image" else 640 * 2
            values = record.get(field)
            if record.get("active_expert") != ("vision" if capability == "image" else "audio") or not isinstance(values, list) or not values:
                raise ValueError(f"{capability} semantic record lacks its routed raw values")
            if token_ids.count(marker) != len(values):
                raise ValueError(f"{capability} raw value count does not match config-derived markers")
            try:
                decoded = [base64.b64decode(value, validate=True) for value in values]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{capability} raw values are not base64") from exc
            if any(len(value) != expected_bytes for value in decoded):
                raise ValueError(f"{capability} raw values do not match the bound shape")
            if capability == "image":
                coordinates = record.get("image_coordinates")
                if not isinstance(coordinates, list) or len(coordinates) != len(values) or any(not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(value, int) or value < 0 for value in pair) for pair in coordinates):
                    raise ValueError("image semantic record lacks explicit 2D coordinates")
            spans = record.get("multimodal_spans")
            positions = {index for index, token in enumerate(token_ids) if token == marker}
            if not isinstance(spans, list):
                raise ValueError(f"{capability} semantic record lacks explicit modality spans")
            covered: set[int] = set()
            for span in spans:
                if not isinstance(span, Mapping) or span.get("modality") != capability or span.get("attention_mode") not in {"causal", "bidirectional", "isolated"}:
                    continue
                start, length = span.get("start"), span.get("length")
                if isinstance(start, int) and isinstance(length, int) and start >= 0 and length > 0 and start + length <= len(token_ids):
                    covered.update(range(start, start + length))
            if covered != positions:
                raise ValueError(f"{capability} modality spans do not cover exactly its raw markers")
        if capability == "image":
            try:
                from specialist_semantics import verify_image_supervision
            except Exception as error:
                raise ValueError("image semantic verifier cannot load the exact frozen tokenizer") from error
            try:
                verify_image_supervision(record, patches=decoded, tokenizer=frozen_tokenizer, image_marker=raw_contract["image_marker"])
            except ValueError as error:
                raise ValueError(str(error)) from error
        if capability == "audio":
            try:
                from specialist_semantics import verify_audio_supervision
                verify_audio_supervision(record, frames=decoded, tokenizer=frozen_tokenizer, audio_marker=raw_contract["audio_marker"])
            except ValueError as error:
                raise ValueError(str(error)) from error
            except Exception as error:
                raise ValueError("audio semantic verifier cannot load the exact frozen tokenizer") from error
        if capability in {"reasoning", "tool"}:
            if record.get("active_expert") != capability:
                raise ValueError(f"{capability} semantic record must route to the {capability} expert")
            target_text = record.get("target_text")
            if not isinstance(target_text, str):
                raise ValueError(f"{capability} semantic record lacks a target transcript")
            try:
                expected_target = list(frozen_tokenizer.encode(target_text).ids)
            except Exception as error:
                raise ValueError(f"{capability} semantic verifier cannot load the exact frozen tokenizer") from error
            if len(expected_target) < 2 or token_ids != expected_target[:-1] or target_ids != expected_target[1:]:
                raise ValueError(f"{capability} semantic target tokenization does not bind the frozen tokenizer and executed transcript")
            capability_records.append(record)
        token_count += len(token_ids)
    if capability_records:
        records_json = json.dumps([dict(record) for record in capability_records], sort_keys=True, separators=(",", ":"))
        completed = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("verify_capability_record.py")), "--records-json-stdin"], input=records_json, text=True, capture_output=True, timeout=15, check=False)
        if completed.returncode != 0:
            raise ValueError(f"{capability} semantic records local verifier failed")
        result = json.loads(completed.stdout)
        receipts = result.get("receipts") if isinstance(result, dict) else None
        if result.get("result") != "PASSED" or not isinstance(receipts, list) or len(receipts) != len(capability_records) or any(not isinstance(receipt, dict) for receipt in receipts):
            raise ValueError(f"{capability} semantic records lack executed local receipts")
    if data.get("record_count") != len(records) or data.get("token_count") != token_count:
        raise ValueError("data manifest counts do not match verified semantic records")
    if specialist_minimum is not None and (len(records) < specialist_minimum["records"] or token_count < specialist_minimum["tokens"] or len(records) < semantic_source["minimum_record_count"] or token_count < semantic_source["minimum_token_count"]):
        raise ValueError("specialist semantic data is below the nontrivial admission floor")
    return {
        "schema_version": "ember-training-data-verification-v1",
        "result": "VERIFIED",
        "capability": capability,
        "data_manifest_sha256": data_sha256,
        "tokenizer_sha256": tokenizer_hash,
        "verifier_sha256": verifier_sha256,
        "data_class": "SEMANTIC_PRETRAINING",
        "generator_replay_verified": bool(generation is not None) if specialist_minimum is not None else None,
        "record_count": len(records),
        "token_count": token_count,
        "source_manifest_sha256": source_sha256,
        "records_artifact_sha256": records_sha256,
        "semantic_checks": SEMANTIC_CHECKS[capability],
        "semantic_model_contract_sha256": semantic_contract_sha256,
        "admission": "ADMISSIBLE_SEMANTIC_CONTRACT" if semantic_contract_sha256 is not None else "NON_ADMISSIBLE_LEGACY",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.data_manifest, args.tokenizer, args.capability, root=Path.cwd().resolve()), sort_keys=True))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

