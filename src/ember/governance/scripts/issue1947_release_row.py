#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Produce a durable named refusal for a non-executable protected release row."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROWS = (
    "E-MATRIX-TEXT-LANGUAGE",
    "E-MATRIX-IMAGE",
    "E-MATRIX-AUDIO",
    "E-MATRIX-IMAGE-TEXT",
    "E-MATRIX-AUDIO-TEXT",
    "E-MATRIX-IMAGE-AUDIO-TEXT",
    "E-MATRIX-REASONING",
    "E-MATRIX-TOOL-USE",
    "E-MATRIX-ROUTING-PATHWAY",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_self_hashed(path: Path, schema_version: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema_version") != schema_version:
        raise ValueError(f"SCHEMA_DRIFT:{path}")
    claimed = payload.get("self_sha256")
    body = dict(payload)
    body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError(f"SELF_HASH_DRIFT:{path}")
    return payload, raw


def build_refusal(row_id: str, missing_predicates: list[str]) -> dict[str, object]:
    if row_id not in ROWS:
        raise ValueError(f"UNKNOWN_RELEASE_ROW:{row_id}")
    if not missing_predicates or any(
        not value.startswith("MISSING_") for value in missing_predicates
    ):
        raise ValueError(f"INVALID_MISSING_PREDICATES:{row_id}")
    if len(missing_predicates) != len(set(missing_predicates)):
        raise ValueError(f"DUPLICATE_MISSING_PREDICATE:{row_id}")
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1947-release-row-refusal-v1",
        "result": "REFUSED",
        "row_id": row_id,
        "missing_predicates": missing_predicates,
        "claim_boundary": "NAMED_NONEXECUTABLE_ROW_REFUSAL_ONLY; NO EXECUTION CAPABILITY RELEASE ISSUE_OR_GOAL_CREDIT",
    }
    receipt["self_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    return receipt


def adapt_text(contract_path: Path, source_path: Path) -> dict[str, object]:
    contract, _ = load_self_hashed(
        contract_path, "ember-issue1947-protected-text-contract-totality-v1"
    )
    source, source_raw = load_self_hashed(
        source_path, "ember-issue1964-statistics-child-row-carrier-v1"
    )
    binding = contract.get("source_child_receipt")
    if not isinstance(binding, dict) or binding.get("raw_sha256") != sha(source_raw):
        raise ValueError("TEXT_SOURCE_RECEIPT_BINDING_DRIFT")
    source_row = source["row"]
    frozen_items = contract.get("frozen_items")
    if not isinstance(frozen_items, list) or len(frozen_items) != 1:
        raise ValueError("TEXT_CONTRACT_ITEM_TOTALITY_DRIFT")
    frozen = frozen_items[0]
    expected = {
        "item_id": source_row["row_id"],
        "gold_item_sha256": source_row["target_token_id_sha256"],
        "source_text_sha256": source_row["source_text_sha256"],
        "content_sha256": source_row["content_sha256"],
        "prefix_token_ids_sha256": source_row["prefix_token_ids_sha256"],
    }
    if frozen != expected or contract.get("totality", {}).get("complete") is not True:
        raise ValueError("TEXT_CONTRACT_ITEM_IDENTITY_DRIFT")
    return {
        "row_id": "E-MATRIX-TEXT-LANGUAGE",
        "items": [{
            "item_id": source_row["row_id"],
            "gold_item_sha256": source_row["target_token_id_sha256"],
            "prediction": source_row["predicted_token_id"],
            "score": 1.0 if source_row["exact_id_match"] is True else 0.0,
        }],
    }


def adapt_image(contract_path: Path, source_path: Path) -> dict[str, object]:
    contract, contract_raw = load_self_hashed(
        contract_path, "ember-issue2105-protected-image-contract-v1"
    )
    source_raw = source_path.read_bytes()
    try:
        source = json.loads(source_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("IMAGE_SOURCE_RECEIPT_UNREADABLE_REFUSED") from error
    task = contract.get("task")
    if (
        contract.get("result") != "PASS"
        or contract.get("task_class") != "adapter_totality"
        or not isinstance(task, dict)
        or task.get("id") != "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY"
        or task.get("consumes") != ["image_payload_bytes"]
        or task.get("forbidden_inputs")
        != ["mmmu_question", "mmmu_answer", "mmmu_options"]
        or contract.get("totality")
        != {"expected": 64, "observed": 64, "complete": True}
    ):
        raise ValueError("IMAGE_CONTRACT_TASK_TOTALITY_REFUSED")
    binding = contract.get("source")
    if (
        not isinstance(binding, dict)
        or binding.get("connector_receipt_raw_sha256") != sha(source_raw)
    ):
        raise ValueError("IMAGE_SOURCE_RECEIPT_BINDING_DRIFT_REFUSED")
    if source.get("schema") != "corpus-connector-receipt-v1":
        raise ValueError("IMAGE_SOURCE_RECEIPT_SCHEMA_REFUSED")
    root_value = source.get("dest_root")
    files = source.get("files")
    if not isinstance(root_value, str) or not isinstance(files, list):
        raise TypeError("IMAGE_SOURCE_RECEIPT_TOTALITY_REFUSED")
    root = Path(root_value)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("IMAGE_CUSTODY_ROOT_MISSING_REFUSED")
    root = root.resolve()
    by_sha: dict[str, dict[str, object]] = {}
    for row in files:
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
            raise TypeError("IMAGE_SOURCE_RECEIPT_FILE_SCHEMA_REFUSED")
        if row["sha256"] in by_sha:
            raise ValueError("IMAGE_SOURCE_RECEIPT_DUPLICATE_OBJECT_REFUSED")
        by_sha[row["sha256"]] = row
    frozen_items = contract.get("frozen_items")
    if not isinstance(frozen_items, list) or len(frozen_items) != 64:
        raise ValueError("IMAGE_CONTRACT_ITEM_TOTALITY_REFUSED")
    items: list[dict[str, object]] = []
    for frozen in frozen_items:
        if not isinstance(frozen, dict):
            raise TypeError("IMAGE_CONTRACT_ITEM_SCHEMA_REFUSED")
        gold = frozen.get("gold_object_sha256")
        source_row = by_sha.get(gold) if isinstance(gold, str) else None
        if (
            source_row is None
            or source_row.get("bytes") != frozen.get("byte_count")
            or source_row.get("sha256") != gold
            or not isinstance(source_row.get("path"), str)
        ):
            raise ValueError(f"IMAGE_PAYLOAD_MISSING_REFUSED:{gold}")
        physical = (root / Path(source_row["path"])).resolve()
        try:
            physical.relative_to(root)
        except ValueError as error:
            raise ValueError(f"IMAGE_PAYLOAD_PATH_ESCAPE_REFUSED:{gold}") from error
        if not physical.is_file():
            raise ValueError(f"IMAGE_PAYLOAD_MISSING_REFUSED:{gold}")
        prediction = sha(physical.read_bytes())
        # The release executor's item schema (issue1947_release_execute.validate_row)
        # is exactly {item_id, gold_item_sha256, prediction, score}; the contract's
        # `gold_object_sha256` is the same digest under the image contract's name.
        items.append({
            "item_id": frozen.get("item_id"),
            "gold_item_sha256": gold,
            "prediction": prediction,
            "score": 1.0 if prediction == gold else 0.0,
        })
    receipt: dict[str, object] = {
        "schema_version": "ember-issue2105-image-row-receipt-v1",
        "result": "IMAGE_HELDOUT_ROW_PRODUCED",
        "row_id": "E-MATRIX-IMAGE",
        "task_class": "adapter_totality",
        "task": "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY",
        "contract_raw_sha256": sha(contract_raw),
        "connector_receipt_raw_sha256": sha(source_raw),
        "items": items,
        "score": sum(float(item["score"]) for item in items) / len(items),
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


def adapt_audio(contract_path: Path, source_path: Path) -> dict[str, object]:
    contract, contract_raw = load_self_hashed(
        contract_path, "ember-issue1947-protected-audio-contract-v1"
    )
    source_raw = source_path.read_bytes()
    try:
        source = json.loads(source_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AUDIO_SOURCE_RECEIPT_UNREADABLE_REFUSED") from error
    task = contract.get("task")
    if (
        contract.get("result") != "PASS"
        or contract.get("task_class") != "adapter_totality"
        or not isinstance(task, dict)
        or task.get("id") != "EXACT_AUDIO_PAYLOAD_SHA256_IDENTITY"
        or task.get("consumes") != ["audio_payload_bytes"]
        or task.get("forbidden_inputs")
        != ["librispeech_transcript", "speaker_metadata", "chapter_metadata"]
        or contract.get("totality")
        != {"expected": 64, "observed": 64, "complete": True}
    ):
        raise ValueError("AUDIO_CONTRACT_TASK_TOTALITY_REFUSED")
    binding = contract.get("source")
    if (
        not isinstance(binding, dict)
        or binding.get("connector_receipt_raw_sha256") != sha(source_raw)
    ):
        raise ValueError("AUDIO_SOURCE_RECEIPT_BINDING_DRIFT_REFUSED")
    if source.get("schema") != "corpus-connector-receipt-v1":
        raise ValueError("AUDIO_SOURCE_RECEIPT_SCHEMA_REFUSED")
    root_value = source.get("dest_root")
    files = source.get("files")
    if not isinstance(root_value, str) or not isinstance(files, list):
        raise TypeError("AUDIO_SOURCE_RECEIPT_TOTALITY_REFUSED")
    root = Path(root_value)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("AUDIO_CUSTODY_ROOT_MISSING_REFUSED")
    root = root.resolve()
    by_sha: dict[str, dict[str, object]] = {}
    for row in files:
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
            raise TypeError("AUDIO_SOURCE_RECEIPT_FILE_SCHEMA_REFUSED")
        if row["sha256"] in by_sha:
            raise ValueError("AUDIO_SOURCE_RECEIPT_DUPLICATE_OBJECT_REFUSED")
        by_sha[row["sha256"]] = row
    frozen_items = contract.get("frozen_items")
    if not isinstance(frozen_items, list) or len(frozen_items) != 64:
        raise ValueError("AUDIO_CONTRACT_ITEM_TOTALITY_REFUSED")
    items: list[dict[str, object]] = []
    for frozen in frozen_items:
        if not isinstance(frozen, dict):
            raise TypeError("AUDIO_CONTRACT_ITEM_SCHEMA_REFUSED")
        gold = frozen.get("gold_object_sha256")
        source_row = by_sha.get(gold) if isinstance(gold, str) else None
        if (
            source_row is None
            or source_row.get("bytes") != frozen.get("byte_count")
            or source_row.get("sha256") != gold
            or not isinstance(source_row.get("path"), str)
        ):
            raise ValueError(f"AUDIO_PAYLOAD_MISSING_REFUSED:{gold}")
        physical = (root / Path(source_row["path"])).resolve()
        try:
            physical.relative_to(root)
        except ValueError as error:
            raise ValueError(f"AUDIO_PAYLOAD_PATH_ESCAPE_REFUSED:{gold}") from error
        if not physical.is_file():
            raise ValueError(f"AUDIO_PAYLOAD_MISSING_REFUSED:{gold}")
        prediction = sha(physical.read_bytes())
        # Same item schema as adapt_image (issue1947_release_execute.validate_row):
        # {item_id, gold_item_sha256, prediction, score}; the audio contract's
        # `gold_object_sha256` is the same digest under the audio contract's name.
        items.append({
            "item_id": frozen.get("item_id"),
            "gold_item_sha256": gold,
            "prediction": prediction,
            "score": 1.0 if prediction == gold else 0.0,
        })
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1947-audio-row-receipt-v1",
        "result": "AUDIO_HELDOUT_ROW_PRODUCED",
        "row_id": "E-MATRIX-AUDIO",
        "task_class": "adapter_totality",
        "task": "EXACT_AUDIO_PAYLOAD_SHA256_IDENTITY",
        "contract_raw_sha256": sha(contract_raw),
        "connector_receipt_raw_sha256": sha(source_raw),
        "items": items,
        "score": sum(float(item["score"]) for item in items) / len(items),
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


IMAGE_TEXT_CONTRACT_SCHEMA = "ember-protected-image-text-contract-v1"
IMAGE_TEXT_TASK_ID = "EXACT_IMAGE_TEXT_PAYLOAD_SHA256_IDENTITY"
IMAGE_TEXT_FORBIDDEN_INPUTS = ["mmmu_answer_dictionary", "prediction_custody"]
IMAGE_TEXT_ITEM_COUNT = 847
IMAGE_TEXT_TEXT_KEYS = frozenset({"id", "question", "options"})


def _image_text_canonical_bytes(item_id: str, payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _load_image_text_sources(
    contract: dict[str, object], source_paths: list[Path]
) -> tuple[dict[str, tuple[Path, dict[str, object]]], list[str]]:
    return _load_bound_sources(contract, source_paths, "IMAGE_TEXT")


def _load_bound_sources(
    contract: dict[str, object], source_paths: list[Path], prefix: str,
) -> tuple[dict[str, tuple[Path, dict[str, object]]], list[str]]:
    """Every source must be a connector receipt bound by the contract; the bound
    set must be supplied in full. A receipt of any other schema (a prediction
    custody receipt, an answer dictionary) is a forbidden input, refused before
    any byte under it is read."""

    binding = contract.get("source")
    bound = binding.get("connector_receipt_raw_sha256s") if isinstance(binding, dict) else None
    if not isinstance(bound, list) or not bound or any(not isinstance(v, str) for v in bound):
        raise ValueError(f"{prefix}_CONTRACT_SOURCE_BINDING_REFUSED")
    by_sha: dict[str, tuple[Path, dict[str, object]]] = {}
    supplied: list[str] = []
    for source_path in source_paths:
        source_raw = source_path.read_bytes()
        try:
            source = json.loads(source_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{prefix}_SOURCE_RECEIPT_UNREADABLE_REFUSED") from error
        if not isinstance(source, dict) or source.get("schema") != "corpus-connector-receipt-v1":
            observed = source.get("schema") if isinstance(source, dict) else None
            observed = observed or (source.get("schema_version") if isinstance(source, dict) else None)
            raise ValueError(f"{prefix}_FORBIDDEN_INPUT_REFUSED:source_schema:{observed}")
        digest = sha(source_raw)
        if digest not in bound:
            raise ValueError(f"{prefix}_SOURCE_RECEIPT_BINDING_DRIFT_REFUSED")
        if digest in supplied:
            raise ValueError(f"{prefix}_SOURCE_RECEIPT_DUPLICATE_REFUSED")
        supplied.append(digest)
        root_value = source.get("dest_root")
        files = source.get("files")
        if not isinstance(root_value, str) or not isinstance(files, list):
            raise TypeError(f"{prefix}_SOURCE_RECEIPT_TOTALITY_REFUSED")
        root = Path(root_value)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError(f"{prefix}_CUSTODY_ROOT_MISSING_REFUSED")
        root = root.resolve()
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
                raise TypeError(f"{prefix}_SOURCE_RECEIPT_FILE_SCHEMA_REFUSED")
            if row["sha256"] in by_sha:
                raise ValueError(f"{prefix}_SOURCE_RECEIPT_DUPLICATE_OBJECT_REFUSED")
            by_sha[row["sha256"]] = (root, row)
    if sorted(supplied) != sorted(bound):
        raise ValueError(f"{prefix}_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED")
    return by_sha, sorted(supplied)


def _image_text_payload(
    by_sha: dict[str, tuple[Path, dict[str, object]]], digest: object, byte_count: object, item_id: object,
) -> bytes:
    return _bound_payload(by_sha, digest, byte_count, item_id, "IMAGE_TEXT")


def _bound_payload(
    by_sha: dict[str, tuple[Path, dict[str, object]]], digest: object, byte_count: object, item_id: object,
    prefix: str,
) -> bytes:
    entry = by_sha.get(digest) if isinstance(digest, str) else None
    if entry is None:
        raise ValueError(f"{prefix}_PAYLOAD_MISSING_REFUSED:{item_id}:{digest}")
    root, row = entry
    if row.get("bytes") != byte_count or not isinstance(row.get("path"), str):
        raise ValueError(f"{prefix}_PAYLOAD_MISSING_REFUSED:{item_id}:{digest}")
    physical = (root / Path(row["path"])).resolve()
    try:
        physical.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{prefix}_PAYLOAD_PATH_ESCAPE_REFUSED:{item_id}:{digest}") from error
    if not physical.is_file():
        raise ValueError(f"{prefix}_PAYLOAD_MISSING_REFUSED:{item_id}:{digest}")
    return physical.read_bytes()


def adapt_image_text(contract_path: Path, source_paths: list[Path]) -> dict[str, object]:
    contract, contract_raw = load_self_hashed(contract_path, IMAGE_TEXT_CONTRACT_SCHEMA)
    task = contract.get("task")
    if (
        contract.get("result") != "PASS"
        or contract.get("task_class") != "adapter_totality"
        or not isinstance(task, dict)
        or task.get("id") != IMAGE_TEXT_TASK_ID
        or task.get("consumes") != ["image_payload_bytes", "item_text_payload_bytes"]
        or task.get("forbidden_inputs") != IMAGE_TEXT_FORBIDDEN_INPUTS
        or contract.get("totality")
        != {"expected": IMAGE_TEXT_ITEM_COUNT, "observed": IMAGE_TEXT_ITEM_COUNT, "complete": True}
    ):
        raise ValueError("IMAGE_TEXT_CONTRACT_TASK_TOTALITY_REFUSED")
    by_sha, supplied = _load_image_text_sources(contract, source_paths)
    frozen_items = contract.get("frozen_items")
    if not isinstance(frozen_items, list) or len(frozen_items) != IMAGE_TEXT_ITEM_COUNT:
        raise ValueError("IMAGE_TEXT_CONTRACT_ITEM_TOTALITY_REFUSED")
    items: list[dict[str, object]] = []
    for frozen in frozen_items:
        if not isinstance(frozen, dict):
            raise TypeError("IMAGE_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        item_id = frozen.get("item_id")
        gold = frozen.get("gold_item_sha256")
        image_objects = frozen.get("image_objects")
        text_object = frozen.get("item_text_object")
        if (
            not isinstance(item_id, str)
            or not isinstance(gold, str)
            or not isinstance(image_objects, list)
            or not image_objects
            or not isinstance(text_object, dict)
        ):
            raise TypeError("IMAGE_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        buffer = bytearray()
        for image in image_objects:
            if not isinstance(image, dict):
                raise TypeError("IMAGE_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
            buffer += _image_text_payload(by_sha, image.get("sha256"), image.get("byte_count"), item_id)
        text_raw = _image_text_payload(by_sha, text_object.get("sha256"), text_object.get("byte_count"), item_id)
        # The item-text object may carry only the canonical {id, question, options}
        # payload. Any other member (the answer, an explanation, a prediction) is a
        # forbidden input and refuses the row rather than scoring it.
        try:
            text_payload = json.loads(text_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"IMAGE_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_unreadable:{item_id}") from error
        if (
            not isinstance(text_payload, dict)
            or set(text_payload) != IMAGE_TEXT_TEXT_KEYS
            or text_payload.get("id") != item_id
            or _image_text_canonical_bytes(item_id, text_payload) != text_raw
        ):
            raise ValueError(f"IMAGE_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_shape:{item_id}")
        buffer += text_raw
        prediction = sha(bytes(buffer))
        # Same item schema as adapt_image / adapt_audio (issue1947_release_execute.validate_row):
        # {item_id, gold_item_sha256, prediction, score}.
        items.append({
            "item_id": item_id,
            "gold_item_sha256": gold,
            "prediction": prediction,
            "score": 1.0 if prediction == gold else 0.0,
        })
    receipt: dict[str, object] = {
        "schema_version": "ember-issue2130-image-text-row-receipt-v1",
        "result": "IMAGE_TEXT_HELDOUT_ROW_PRODUCED",
        "row_id": "E-MATRIX-IMAGE-TEXT",
        "task_class": "adapter_totality",
        "task": IMAGE_TEXT_TASK_ID,
        "contract_raw_sha256": sha(contract_raw),
        "connector_receipt_raw_sha256s": supplied,
        "items": items,
        "score": sum(float(item["score"]) for item in items) / len(items),
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


AUDIO_TEXT_CONTRACT_SCHEMA = "ember-issue1947-protected-audio-text-contract-v1"
AUDIO_TEXT_TASK_ID = "EXACT_AUDIO_TEXT_PAIR_IDENTITY"
AUDIO_TEXT_FORBIDDEN_INPUTS = ["speaker_metadata", "chapter_metadata", "prediction_custody"]
AUDIO_TEXT_ITEM_COUNT = 64
AUDIO_TEXT_TEXT_KEYS = frozenset({"utterance_id", "transcript"})


def _audio_text_canonical_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def adapt_audio_text(contract_path: Path, source_paths: list[Path]) -> dict[str, object]:
    """E-MATRIX-AUDIO-TEXT (#2138): pair identity over the admitted audio payload and the
    admitted transcript text object. Speaker/chapter identities and prediction custody are
    forbidden inputs: a transcript object carrying any member beyond {utterance_id,
    transcript} refuses the row, and a non-connector receipt refuses before any byte is read."""

    contract, contract_raw = load_self_hashed(contract_path, AUDIO_TEXT_CONTRACT_SCHEMA)
    task = contract.get("task")
    if (
        contract.get("result") != "PASS"
        or contract.get("task_class") != "adapter_totality"
        or not isinstance(task, dict)
        or task.get("id") != AUDIO_TEXT_TASK_ID
        or task.get("consumes") != ["audio_payload_bytes", "transcript_text_payload_bytes"]
        or task.get("forbidden_inputs") != AUDIO_TEXT_FORBIDDEN_INPUTS
        or contract.get("totality")
        != {"expected": AUDIO_TEXT_ITEM_COUNT, "observed": AUDIO_TEXT_ITEM_COUNT, "complete": True}
    ):
        raise ValueError("AUDIO_TEXT_CONTRACT_TASK_TOTALITY_REFUSED")
    by_sha, supplied = _load_bound_sources(contract, source_paths, "AUDIO_TEXT")
    frozen_items = contract.get("frozen_items")
    if not isinstance(frozen_items, list) or len(frozen_items) != AUDIO_TEXT_ITEM_COUNT:
        raise ValueError("AUDIO_TEXT_CONTRACT_ITEM_TOTALITY_REFUSED")
    items: list[dict[str, object]] = []
    for frozen in frozen_items:
        if not isinstance(frozen, dict):
            raise TypeError("AUDIO_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        item_id = frozen.get("item_id")
        gold = frozen.get("gold_item_sha256")
        audio_object = frozen.get("audio_object")
        text_object = frozen.get("item_text_object")
        if (
            not isinstance(item_id, str)
            or not isinstance(gold, str)
            or not isinstance(audio_object, dict)
            or not isinstance(text_object, dict)
        ):
            raise TypeError("AUDIO_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        audio_raw = _bound_payload(by_sha, audio_object.get("sha256"), audio_object.get("byte_count"), item_id, "AUDIO_TEXT")
        text_raw = _bound_payload(by_sha, text_object.get("sha256"), text_object.get("byte_count"), item_id, "AUDIO_TEXT")
        try:
            text_payload = json.loads(text_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"AUDIO_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_unreadable:{item_id}") from error
        if (
            not isinstance(text_payload, dict)
            or set(text_payload) != AUDIO_TEXT_TEXT_KEYS
            or text_payload.get("utterance_id") != item_id
            or not isinstance(text_payload.get("transcript"), str)
            or _audio_text_canonical_bytes(text_payload) != text_raw
        ):
            raise ValueError(f"AUDIO_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_shape:{item_id}")
        prediction = sha(audio_raw + text_raw)
        # Same item schema as the other adapters (issue1947_release_execute.validate_row).
        items.append({
            "item_id": item_id,
            "gold_item_sha256": gold,
            "prediction": prediction,
            "score": 1.0 if prediction == gold else 0.0,
        })
    receipt: dict[str, object] = {
        "schema_version": "ember-issue2138-audio-text-row-receipt-v1",
        "result": "AUDIO_TEXT_HELDOUT_ROW_PRODUCED",
        "row_id": "E-MATRIX-AUDIO-TEXT",
        "task_class": "adapter_totality",
        "task": AUDIO_TEXT_TASK_ID,
        "contract_raw_sha256": sha(contract_raw),
        "connector_receipt_raw_sha256s": supplied,
        "items": items,
        "score": sum(float(item["score"]) for item in items) / len(items),
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    refuse = subparsers.add_parser("refuse")
    refuse.add_argument("--row-id", required=True, choices=ROWS)
    refuse.add_argument("--missing-predicate", action="append", required=True)
    refuse.add_argument("--receipt", type=Path, required=True)
    text = subparsers.add_parser("adapt-text")
    text.add_argument("--contract", type=Path, required=True)
    text.add_argument("--source-receipt", type=Path, required=True)
    text.add_argument("--result", type=Path, required=True)
    image = subparsers.add_parser("adapt-image")
    image.add_argument("--contract", type=Path, required=True)
    image.add_argument("--source-receipt", type=Path, required=True)
    image.add_argument("--result", type=Path, required=True)
    audio = subparsers.add_parser("adapt-audio")
    audio.add_argument("--contract", type=Path, required=True)
    audio.add_argument("--source-receipt", type=Path, required=True)
    audio.add_argument("--result", type=Path, required=True)
    image_text = subparsers.add_parser("adapt-image-text")
    image_text.add_argument("--contract", type=Path, required=True)
    image_text.add_argument(
        "--source-receipt", type=Path, required=True, action="append",
        help="connector receipt bound by the contract; repeat for every bound receipt",
    )
    image_text.add_argument("--result", type=Path, required=True)
    audio_text = subparsers.add_parser("adapt-audio-text")
    audio_text.add_argument("--contract", type=Path, required=True)
    audio_text.add_argument(
        "--source-receipt", type=Path, required=True, action="append",
        help="connector receipt bound by the contract; repeat for every bound receipt",
    )
    audio_text.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "adapt-text":
        row = adapt_text(args.contract, args.source_receipt)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with args.result.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(row, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"result": "COMPLETE", "row_id": row["row_id"]}, sort_keys=True))
        return 0
    if args.operation == "adapt-image":
        try:
            row = adapt_image(args.contract, args.source_receipt)
            returncode = 0
        except (OSError, TypeError, ValueError) as error:
            row = {
                "schema_version": "ember-issue2105-image-row-refusal-v1",
                "result": "IMAGE_HELDOUT_REFUSED",
                "row_id": "E-MATRIX-IMAGE",
                "task_class": "adapter_totality",
                "reason": str(error),
                "claim_boundary": "ADAPTER TOTALITY REFUSAL ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
            }
            row["self_sha256"] = sha(canonical(row))
            returncode = 78
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with args.result.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(row, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"result": row["result"], "row_id": row["row_id"]}, sort_keys=True))
        return returncode
    if args.operation == "adapt-image-text":
        try:
            row = adapt_image_text(args.contract, list(args.source_receipt))
            returncode = 0
        except (OSError, TypeError, ValueError) as error:
            row = {
                "schema_version": "ember-issue2130-image-text-row-refusal-v1",
                "result": "IMAGE_TEXT_HELDOUT_REFUSED",
                "row_id": "E-MATRIX-IMAGE-TEXT",
                "task_class": "adapter_totality",
                "reason": str(error),
                "claim_boundary": "ADAPTER TOTALITY REFUSAL ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
            }
            row["self_sha256"] = sha(canonical(row))
            returncode = 78
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with args.result.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(row, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"result": row["result"], "row_id": row["row_id"]}, sort_keys=True))
        return returncode
    if args.operation == "adapt-audio-text":
        try:
            row = adapt_audio_text(args.contract, list(args.source_receipt))
            returncode = 0
        except (OSError, TypeError, ValueError) as error:
            row = {
                "schema_version": "ember-issue2138-audio-text-row-refusal-v1",
                "result": "AUDIO_TEXT_HELDOUT_REFUSED",
                "row_id": "E-MATRIX-AUDIO-TEXT",
                "task_class": "adapter_totality",
                "reason": str(error),
                "claim_boundary": "ADAPTER TOTALITY REFUSAL ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
            }
            row["self_sha256"] = sha(canonical(row))
            returncode = 78
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with args.result.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(row, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"result": row["result"], "row_id": row["row_id"]}, sort_keys=True))
        return returncode
    if args.operation == "adapt-audio":
        try:
            row = adapt_audio(args.contract, args.source_receipt)
            returncode = 0
        except (OSError, TypeError, ValueError) as error:
            row = {
                "schema_version": "ember-issue1947-audio-row-refusal-v1",
                "result": "AUDIO_HELDOUT_REFUSED",
                "row_id": "E-MATRIX-AUDIO",
                "task_class": "adapter_totality",
                "reason": str(error),
                "claim_boundary": "ADAPTER TOTALITY REFUSAL ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
            }
            row["self_sha256"] = sha(canonical(row))
            returncode = 78
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with args.result.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(row, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"result": row["result"], "row_id": row["row_id"]}, sort_keys=True))
        return returncode
    receipt = build_refusal(args.row_id, args.missing_predicate)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"result": "REFUSED", "row_id": args.row_id}, sort_keys=True))
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
