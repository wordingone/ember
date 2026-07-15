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
SPECIALIST_MINIMUMS = {
    "image": {"records": 128, "tokens": 4096, "derivation": "raw_image_property_execution"},
    "audio": {"records": 128, "tokens": 4096, "derivation": "raw_audio_signal_execution"},
    "reasoning": {"records": 128, "tokens": 4096, "derivation": "local_answer_execution"},
    "tool": {"records": 128, "tokens": 4096, "derivation": "typed_tool_execution"},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_file(root: Path, record: object, name: str) -> Path:
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
    if _sha256(path) != expected:
        raise ValueError(f"{name} sha256 does not match")
    return path


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object")
    return payload


def verify(data_path: Path, tokenizer_path: Path, capability: str, *, root: Path) -> dict[str, Any]:
    if capability not in SEMANTIC_CHECKS:
        raise ValueError("unsupported semantic capability")
    data_path = data_path.resolve()
    if root not in data_path.parents:
        raise ValueError("data manifest escapes verifier root")
    data = _load_json(data_path, "data manifest")
    if data.get("schema_version") != "ember-owned-training-data-v1":
        raise ValueError("data manifest schema is invalid")
    if data.get("capability") != capability or data.get("data_class") != "SEMANTIC_PRETRAINING":
        raise ValueError("data manifest capability or class is invalid")
    if data.get("model_mediated") is not False or data.get("borrowed_labels") is not False:
        raise ValueError("data manifest provenance is invalid")
    tokenizer_hash = _sha256(tokenizer_path)
    if data.get("tokenizer_sha256") != tokenizer_hash:
        raise ValueError("data manifest tokenizer sha256 does not match")
    raw_contract: dict[str, int] | None = None
    if capability in {"image", "audio"}:
        config_path = _bound_file(root, data.get("model_config"), "model config")
        config = _load_json(config_path, "model config").get("model")
        if not isinstance(config, Mapping) or not isinstance(config.get("vocab_size"), int):
            raise ValueError("model config lacks a valid vocabulary")
        image = config.get("image_projection")
        audio = config.get("audio_projection")
        if not isinstance(image, Mapping) or not isinstance(audio, Mapping) or image.get("input_shape") != [48, 48, 3] or audio.get("frame_samples") != 640:
            raise ValueError("model config lacks the authorized raw modality shapes")
        raw_contract = {"image_marker": config["vocab_size"] - 2, "audio_marker": config["vocab_size"] - 1}

    source_path = _bound_file(root, data.get("source_manifest"), "source manifest")
    records_path = _bound_file(root, data.get("records_artifact"), "records artifact")
    source = _load_json(source_path, "source manifest")
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
    tokenizer = _load_json(tokenizer_path, "tokenizer")
    vocab = tokenizer.get("model", {}).get("vocab") if isinstance(tokenizer.get("model"), dict) else None
    if not isinstance(vocab, dict) or not vocab:
        raise ValueError("tokenizer does not declare a vocabulary")
    vocab_size = max(vocab.values()) + 1 if all(isinstance(value, int) and value >= 0 for value in vocab.values()) else 0
    if vocab_size <= 0:
        raise ValueError("tokenizer vocabulary is invalid")
    records_payload = _load_json(records_path, "records artifact")
    records = records_payload.get("records")
    if records_payload.get("schema_version") != "ember-owned-semantic-records-v1" or not isinstance(records, list) or not records:
        raise ValueError("semantic records artifact is invalid")
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
                from tokenizers import Tokenizer
                from specialist_semantics import verify_image_supervision
                frozen_tokenizer = Tokenizer.from_file(str(tokenizer_path))
            except Exception as error:
                raise ValueError("image semantic verifier cannot load the exact frozen tokenizer") from error
            try:
                verify_image_supervision(record, patches=decoded, tokenizer=frozen_tokenizer, image_marker=raw_contract["image_marker"])
            except ValueError as error:
                raise ValueError(str(error)) from error
        if capability == "audio":
            try:
                from tokenizers import Tokenizer
                from specialist_semantics import verify_audio_supervision
                frozen_tokenizer = Tokenizer.from_file(str(tokenizer_path))
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
                from tokenizers import Tokenizer
                frozen_tokenizer = Tokenizer.from_file(str(tokenizer_path))
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
        "data_manifest_sha256": _sha256(data_path),
        "tokenizer_sha256": tokenizer_hash,
        "verifier_sha256": _sha256(Path(__file__)),
        "data_class": "SEMANTIC_PRETRAINING",
        "record_count": len(records),
        "token_count": token_count,
        "source_manifest_sha256": _sha256(source_path),
        "records_artifact_sha256": _sha256(records_path),
        "semantic_checks": SEMANTIC_CHECKS[capability],
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

