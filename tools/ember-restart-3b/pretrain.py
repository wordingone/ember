# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real bounded pretraining segments over owned decoded multimodal records."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import torch
import torch.nn.functional as F

from batch import decode_owned_batch
from model import RestartDecoderConfig, UnifiedDecoder

CheckpointCallback = Callable[[int, dict[str, Any]], None]


def run_pretraining_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    records: Sequence[dict[str, object]],
    config: RestartDecoderConfig,
    device: torch.device,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
) -> dict[str, Any]:
    """Execute owned text/image/audio updates and report a bounded segment."""

    if not records:
        raise ValueError("pretraining segment requires at least one owned record")
    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive")
    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0}
    tokens_seen = 0
    for step, record in enumerate(records, start=1):
        batch = decode_owned_batch(record, config, device=device)
        logits = model(
            batch["input_ids"],
            image_patches=batch["image_patches"],
            audio_frames=batch["audio_frames"],
            active_expert=batch["active_expert"],
        )
        loss = F.cross_entropy(
            logits.float().reshape(-1, config.vocab_size),
            batch["target_ids"].reshape(-1),
        )
        if not torch.isfinite(loss):
            raise RuntimeError(f"pretraining segment stopped on non-finite loss at step {step}")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
        tokens_seen += int(batch["input_ids"].numel())
        modality_examples["text"] += 1
        modality_examples["image"] += int(batch["image_patches"].shape[0])
        modality_examples["audio"] += int(batch["audio_frames"].shape[0])
        result = {
            "step": step,
            "losses": list(losses),
            "tokens_seen": tokens_seen,
            "modality_examples": dict(modality_examples),
            "active_expert": batch["active_expert"],
        }
        if step % checkpoint_every == 0:
            checkpoint_callback(step, result)
    if any(value <= 0 for value in modality_examples.values()):
        raise RuntimeError("pretraining segment stopped because a native modality has zero exposure")
    return {
        "steps": len(records),
        "losses": losses,
        "tokens_seen": tokens_seen,
        "modality_examples": modality_examples,
    }