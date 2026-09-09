# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Decode owned raw multimodal sequences and enforce domain-routed training episodes."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

_REPO_IMPORT_HOME = Path(__file__).resolve().parents[5]
if str(_REPO_IMPORT_HOME) not in sys.path:
    sys.path.insert(0, str(_REPO_IMPORT_HOME))
from src.ember.model.model import EXPERT_NAMES, MultimodalSpan, RestartDecoderConfig, UnifiedDecoder


DOMAIN_MODALITIES = {
    "vision": {"image"},
    "audio": {"audio"},
    "reasoning": set(),
    "tool": set(),
    "shared": set(),
}


def _base64_bytes(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid base64") from exc


def _decode_i16le(value: bytes) -> list[int]:
    if len(value) % 2:
        raise ValueError("audio frame bytes must contain whole little-endian int16 samples")
    return list(struct.unpack(f"<{len(value) // 2}h", value))

def _sequence_bytes(record: dict[str, Any], *, plural: str, legacy: str, field: str) -> list[bytes]:
    if plural in record:
        values = record[plural]
    elif legacy in record:
        values = [record[legacy]]
    else:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{field} sequence must be a list when present")
    return [_base64_bytes(value, f"{field}[{index}]") for index, value in enumerate(values)]


def _spans(record: dict[str, Any], *, sequence_length: int) -> list[MultimodalSpan]:
    raw = record.get("multimodal_spans")
    if not isinstance(raw, list):
        raise ValueError("multimodal_spans must be an explicit list")
    spans: list[MultimodalSpan] = []
    for index, item in enumerate(raw):
        attention_mode = str(item.get("attention_mode", "causal"))
        if attention_mode == "isolated" and record.get("schema_version") == "ember-owned-bootstrap-batch-v1":
            attention_mode = "bidirectional"
        if not isinstance(item, dict):
            raise ValueError(f"multimodal_spans[{index}] must be an object")
        try:
            span = MultimodalSpan(
                start=int(item["start"]),
                length=int(item["length"]),
                modality=str(item["modality"]),
                attention_mode=attention_mode,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"multimodal_spans[{index}] is invalid") from error
        if span.start + span.length > sequence_length:
            raise ValueError(f"multimodal_spans[{index}] exceeds token sequence")
        spans.append(span)
    return spans


def _validate_span_coverage(spans: list[MultimodalSpan], *, marker_positions: dict[str, list[int]]) -> None:
    for modality in ("image", "audio"):
        expected = set(marker_positions[modality])
        covered: set[int] = set()
        for span in spans:
            if span.modality == modality:
                covered.update(range(span.start, span.start + span.length))
        if covered != expected:
            raise ValueError(f"multimodal spans must cover exactly all {modality} marker positions")


def _validate_domain(*, active_expert: str, image_count: int, audio_count: int) -> None:
    present = {name for name, count in {"image": image_count, "audio": audio_count}.items() if count}
    expected = DOMAIN_MODALITIES[active_expert]
    if present != expected:
        raise ValueError(
            f"{active_expert} episode must contain exactly its routed raw modalities; expected={sorted(expected)}, found={sorted(present)}"
        )


def _decode_semantic_text_batch(
    record: dict[str, Any],
    config: RestartDecoderConfig,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Decode a micro-batch of equal-length shared-core text episodes into [B, T] tensors (#2136)."""

    if record.get("active_expert") != "shared":
        raise ValueError("semantic text batches must use the shared core route")
    token_rows = record.get("token_ids")
    target_rows = record.get("target_ids")
    if (
        not isinstance(token_rows, list) or not isinstance(target_rows, list)
        or not token_rows or len(token_rows) != len(target_rows)
        or any(not isinstance(row, list) or not row for row in token_rows + target_rows)
    ):
        raise ValueError("semantic text batch token_ids and target_ids must be non-empty lists of equal-length rows")
    width = len(token_rows[0])
    if any(len(row) != width for row in token_rows + target_rows):
        raise ValueError("semantic text batch rows must share one sequence length")
    if any(not isinstance(item, int) or item < 0 or item >= config.vocab_size for row in token_rows + target_rows for item in row):
        raise ValueError("token IDs must be within the configured vocabulary")
    return {
        "input_ids": torch.tensor(token_rows, dtype=torch.long, device=device),
        "target_ids": torch.tensor(target_rows, dtype=torch.long, device=device),
        "image_patches": None, "audio_frames": None,
        "image_coordinates": torch.empty((0, 2), dtype=torch.long, device=device),
        "spans": [], "active_expert": "shared",
    }


def decode_owned_batch(
    record: dict[str, Any],
    config: RestartDecoderConfig,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Decode explicit raw sequences, 2D coordinates, and exact-cover attention spans."""

    schema_version = record.get("schema_version")
    if schema_version == "ember-owned-semantic-text-batch-v1":
        return _decode_semantic_text_batch(record, config, device=device)
    if schema_version not in {"ember-owned-bootstrap-batch-v1", "ember-owned-semantic-text-v1", "ember-owned-semantic-record-v1"}:
        raise ValueError("unrecognized owned batch schema")
    token_ids = record.get("token_ids")
    target_ids = record.get("target_ids")
    if not isinstance(token_ids, list) or not isinstance(target_ids, list) or len(token_ids) != len(target_ids):
        raise ValueError("token_ids and target_ids must be equal-length lists")
    if not token_ids or any(not isinstance(item, int) or item < 0 or item >= config.vocab_size for item in token_ids + target_ids):
        raise ValueError("token IDs must be within the configured vocabulary")
    if schema_version == "ember-owned-semantic-text-v1":
        if record.get("active_expert") != "shared":
            raise ValueError("semantic text episodes must use the shared core route")
        return {
            "input_ids": torch.tensor(token_ids, dtype=torch.long, device=device).unsqueeze(0),
            "target_ids": torch.tensor(target_ids, dtype=torch.long, device=device).unsqueeze(0),
            "image_patches": None, "audio_frames": None,
            "image_coordinates": torch.empty((0, 2), dtype=torch.long, device=device),
            "spans": [], "active_expert": "shared",
        }
    image_positions = [index for index, token in enumerate(token_ids) if token == config.image_token_id]
    audio_positions = [index for index, token in enumerate(token_ids) if token == config.audio_token_id]
    image_bytes = _sequence_bytes(record, plural="image_patches_u8_base64", legacy="image_u8_base64", field="image patches")
    audio_bytes = _sequence_bytes(record, plural="audio_frames_i16le_base64", legacy="audio_i16le_base64", field="audio frames")
    if any(len(value) != 48 * 48 * 3 for value in image_bytes):
        raise ValueError("every image patch must encode raw 48x48x3 bytes")
    if any(len(value) != 640 * 2 for value in audio_bytes):
        raise ValueError("every audio frame must encode raw 640-sample int16 bytes")
    if len(image_positions) != len(image_bytes) or len(audio_positions) != len(audio_bytes):
        raise ValueError("raw modality sequence length must equal its marker count")
    raw_coordinates = record.get("image_coordinates")
    if not isinstance(raw_coordinates, list) or len(raw_coordinates) != len(image_bytes):
        raise ValueError("image_coordinates must provide one [x,y] pair per raw patch")
    if any(not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(value, int) or value < 0 for value in pair) for pair in raw_coordinates):
        raise ValueError("image_coordinates must contain nonnegative integer [x,y] pairs")
    spans = _spans(record, sequence_length=len(token_ids))
    _validate_span_coverage(spans, marker_positions={"image": image_positions, "audio": audio_positions})
    active_expert = record.get("active_expert")
    if active_expert not in EXPERT_NAMES:
        raise ValueError("batch must declare one authorized expert")
    _validate_domain(active_expert=active_expert, image_count=len(image_bytes), audio_count=len(audio_bytes))
    image = None
    if image_bytes:
        image = torch.tensor([list(value) for value in image_bytes], dtype=torch.float32, device=device).reshape(1, len(image_bytes), 48, 48, 3)
    audio = None
    if audio_bytes:
        audio = torch.tensor([_decode_i16le(value) for value in audio_bytes], dtype=torch.float32, device=device).reshape(1, len(audio_bytes), 640) / 32768.0
    return {
        "input_ids": torch.tensor(token_ids, dtype=torch.long, device=device).unsqueeze(0),
        "target_ids": torch.tensor(target_ids, dtype=torch.long, device=device).unsqueeze(0),
        "image_patches": image,
        "audio_frames": audio,
        "image_coordinates": (torch.tensor(raw_coordinates, dtype=torch.long, device=device).reshape(-1, 2) if raw_coordinates else torch.empty((0, 2), dtype=torch.long, device=device)),
        "spans": spans,
        "active_expert": active_expert,
    }


def _canonical_record_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def decode_owned_packed_batch(
    records: list[dict[str, Any]],
    config: RestartDecoderConfig,
    *,
    device: torch.device,
    expected_records: int,
) -> dict[str, Any]:
    """Decode one fixed-size, same-expert pack without counting right padding as data."""

    if type(expected_records) is not int or expected_records < 1:
        raise ValueError("packed batch expected_records must be positive")
    if not isinstance(records, list) or len(records) != expected_records:
        raise ValueError(f"packed batch requires exactly {expected_records} records")
    decoded = [decode_owned_batch(record, config, device=device) for record in records]
    experts = {str(batch["active_expert"]) for batch in decoded}
    if len(experts) != 1:
        raise ValueError("packed batch requires exactly one active expert")

    def span_contract(batch: dict[str, Any]) -> tuple[tuple[int, int, str, str], ...]:
        return tuple(
            (span.start, span.length, span.modality, span.attention_mode)
            for span in batch["spans"]
        )

    topology = span_contract(decoded[0])
    if any(span_contract(batch) != topology for batch in decoded[1:]):
        raise ValueError("packed batch requires one static multimodal span topology")
    for field in ("image_patches", "audio_frames"):
        shapes = {
            None if batch[field] is None else tuple(batch[field].shape[1:])
            for batch in decoded
        }
        if len(shapes) != 1:
            raise ValueError(f"packed batch requires one static {field} topology")

    lengths = [int(batch["input_ids"].shape[1]) for batch in decoded]
    maximum = max(lengths)
    input_ids = torch.zeros((expected_records, maximum), dtype=torch.long, device=device)
    target_ids = torch.zeros((expected_records, maximum), dtype=torch.long, device=device)
    loss_mask = torch.zeros((expected_records, maximum), dtype=torch.bool, device=device)
    for index, batch in enumerate(decoded):
        length = lengths[index]
        input_ids[index, :length].copy_(batch["input_ids"][0])
        target_ids[index, :length].copy_(batch["target_ids"][0])
        loss_mask[index, :length] = True

    def packed_modality(field: str) -> torch.Tensor | None:
        first = decoded[0][field]
        if first is None:
            return None
        return torch.cat([batch[field] for batch in decoded], dim=0)

    record_hashes = [hashlib.sha256(_canonical_record_bytes(record)).hexdigest() for record in records]
    token_rows = [batch["input_ids"][0].tolist() for batch in decoded]
    true_source_tokens = sum(lengths)
    processed_padded_tokens = expected_records * maximum
    identity = {
        "schema_version": "ember-owned-packed-batch-v1",
        "active_expert": next(iter(experts)),
        "record_count": expected_records,
        "true_source_tokens": true_source_tokens,
        "processed_padded_tokens": processed_padded_tokens,
        "padding_tokens": processed_padded_tokens - true_source_tokens,
        "record_hashes": record_hashes,
        "token_rows_sha256": hashlib.sha256(_canonical_record_bytes({"rows": token_rows})).hexdigest(),
    }
    return {
        "input_ids": input_ids,
        "target_ids": target_ids,
        "loss_mask": loss_mask,
        "image_patches": packed_modality("image_patches"),
        "audio_frames": packed_modality("audio_frames"),
        "image_coordinates": torch.cat([batch["image_coordinates"] for batch in decoded], dim=0),
        "spans": decoded[0]["spans"],
        "active_expert": next(iter(experts)),
        "record_count": expected_records,
        "true_source_tokens": true_source_tokens,
        "processed_padded_tokens": processed_padded_tokens,
        "padding_tokens": processed_padded_tokens - true_source_tokens,
        "record_hashes": record_hashes,
        "record_order_sha256": hashlib.sha256(_canonical_record_bytes({"records": record_hashes})).hexdigest(),
        "tokens_sha256": identity["token_rows_sha256"],
        "pack_signature_sha256": hashlib.sha256(_canonical_record_bytes(identity)).hexdigest(),
    }


def run_one_batch(
    record: dict[str, Any], config: RestartDecoderConfig, *, device: torch.device
) -> dict[str, Any]:
    """Run one real decoded sequence with only its declared expert trainable."""

    model = UnifiedDecoder(config, device=device)
    model.train()
    batch = decode_owned_batch(record, config, device=device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    logits = model(
        batch["input_ids"], image_patches=batch["image_patches"], audio_frames=batch["audio_frames"],
        image_coordinates=batch["image_coordinates"], spans=batch["spans"], active_expert=batch["active_expert"],
    )
    loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), batch["target_ids"].reshape(-1))
    loss.backward()
    optimizer.step()
    return {
        "loss": float(loss.detach().cpu()),
        "active_expert": batch["active_expert"],
        "episode_trainable_parameters": model.count_unique_trainable_parameters(),
        "total_unique_parameters": model.count_unique_trainable_parameters(include_frozen=True),
    }
