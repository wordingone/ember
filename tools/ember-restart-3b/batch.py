# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Decode owned raw-batch bytes and execute one routed training update."""

from __future__ import annotations

import base64
from typing import Any

import torch
import torch.nn.functional as F

from model import EXPERT_NAMES, RestartDecoderConfig, UnifiedDecoder


def _base64_bytes(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid base64") from exc


def decode_owned_batch(
    record: dict[str, Any],
    config: RestartDecoderConfig,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Decode actual stored raw bytes, not generated modality placeholders."""

    if record.get("schema_version") != "ember-owned-bootstrap-batch-v1":
        raise ValueError("unrecognized owned batch schema")
    token_ids = record.get("token_ids")
    target_ids = record.get("target_ids")
    if not isinstance(token_ids, list) or not isinstance(target_ids, list) or len(token_ids) != len(target_ids):
        raise ValueError("token_ids and target_ids must be equal-length lists")
    if not token_ids or any(not isinstance(item, int) or item < 0 or item >= config.vocab_size for item in token_ids + target_ids):
        raise ValueError("token IDs must be within the configured vocabulary")
    image_bytes = _base64_bytes(record.get("image_u8_base64"), "image_u8_base64")
    audio_bytes = _base64_bytes(record.get("audio_i16le_base64"), "audio_i16le_base64")
    if len(image_bytes) != 48 * 48 * 3:
        raise ValueError("image bytes must encode one raw 48x48x3 patch")
    if len(audio_bytes) != 640 * 2:
        raise ValueError("audio bytes must encode one raw int16 frame")
    active_expert = record.get("active_expert")
    if active_expert not in EXPERT_NAMES:
        raise ValueError("batch must declare one authorized expert")
    image = torch.tensor(list(image_bytes), dtype=torch.float32, device=device).reshape(1, 48, 48, 3) / 255.0
    samples = torch.tensor(list(memoryview(audio_bytes).cast("h")), dtype=torch.float32, device=device).reshape(1, 640) / 32768.0
    return {
        "input_ids": torch.tensor(token_ids, dtype=torch.long, device=device).unsqueeze(0),
        "target_ids": torch.tensor(target_ids, dtype=torch.long, device=device).unsqueeze(0),
        "image_patches": image,
        "audio_frames": samples,
        "active_expert": active_expert,
    }


def run_one_batch(
    record: dict[str, Any],
    config: RestartDecoderConfig,
    *,
    device: torch.device,
) -> dict[str, Any]:
    """Run one real decoded batch with only its declared expert trainable."""

    model = UnifiedDecoder(config, device=device)
    model.train()
    batch = decode_owned_batch(record, config, device=device)
    optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
    logits = model(
        batch["input_ids"],
        image_patches=batch["image_patches"],
        audio_frames=batch["audio_frames"],
        active_expert=batch["active_expert"],
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
