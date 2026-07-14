# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real bounded pretraining segments over owned decoded multimodal records."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import torch
import torch.nn.functional as F

from batch import decode_owned_batch
from model import EXPERT_NAMES, RestartDecoderConfig, UnifiedDecoder

CheckpointCallback = Callable[[int, dict[str, Any]], None]


def _verified_reasoning(evidence: object) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    trace = evidence.get("trace_token_ids")
    target = evidence.get("verified_target")
    return (
        isinstance(trace, list)
        and bool(trace)
        and all(isinstance(token, int) and token >= 0 for token in trace)
        and isinstance(target, Mapping)
        and isinstance(target.get("kind"), str)
        and bool(target["kind"])
        and "value" in target
    )


def _verified_tool(evidence: object) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    return (
        isinstance(evidence.get("name"), str)
        and bool(evidence["name"])
        and isinstance(evidence.get("arguments"), Mapping)
        and isinstance(evidence.get("observation"), Mapping)
        and bool(evidence["observation"])
    )


def _record_capabilities(record: Mapping[str, object], *, active_expert: str) -> set[str]:
    """Validate owned semantic evidence before it can be counted as exposure."""

    evidence = record.get("capability_evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    reasoning = _verified_reasoning(evidence.get("reasoning"))
    tool = _verified_tool(evidence.get("tool"))
    if active_expert == "reasoning" and not reasoning:
        raise ValueError("reasoning episode requires a nonempty locally verified reasoning trace and target")
    if active_expert == "tool" and not tool:
        raise ValueError("tool episode requires a typed tool name, arguments, and observed result")
    capabilities = {"text", "image", "audio"}
    if reasoning:
        capabilities.add("reasoning")
    if tool:
        capabilities.add("tool")
    return capabilities


def run_pretraining_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    records: Sequence[dict[str, object]],
    config: RestartDecoderConfig,
    device: torch.device,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
    initial_data_cursor: int = 0,
    require_complete_coverage: bool = True,
) -> dict[str, Any]:
    """Execute routed owned updates and bind counters needed for interruption-safe resume."""

    if not records:
        raise ValueError("pretraining segment requires at least one owned record")
    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive")
    if min(initial_global_step, initial_tokens_seen, initial_data_cursor) < 0:
        raise ValueError("resume counters must be nonnegative")
    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0, "reasoning": 0, "tool": 0}
    expert_examples = {expert: 0 for expert in EXPERT_NAMES}
    tokens_seen = initial_tokens_seen
    data_cursor = initial_data_cursor
    for local_step, record in enumerate(records, start=1):
        batch = decode_owned_batch(record, config, device=device)
        active_expert = batch["active_expert"]
        capabilities = _record_capabilities(record, active_expert=active_expert)
        optimizer.zero_grad(set_to_none=True)
        logits = model(
            batch["input_ids"],
            image_patches=batch["image_patches"],
            audio_frames=batch["audio_frames"],
            image_coordinates=batch["image_coordinates"],
            spans=batch["spans"],
            active_expert=active_expert,
        )
        loss = F.cross_entropy(
            logits.float().reshape(-1, config.vocab_size),
            batch["target_ids"].reshape(-1),
        )
        if not torch.isfinite(loss):
            raise RuntimeError(f"pretraining segment stopped on non-finite loss at step {initial_global_step + local_step}")
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
        tokens_seen += int(batch["input_ids"].numel())
        data_cursor += 1
        expert_examples[active_expert] += 1
        modality_examples["text"] += 1
        modality_examples["image"] += int(batch["image_patches"].shape[1])
        modality_examples["audio"] += int(batch["audio_frames"].shape[1])
        for capability in ("reasoning", "tool"):
            modality_examples[capability] += int(capability in capabilities)
        global_step = initial_global_step + local_step
        result = {
            "step": global_step,
            "global_step": global_step,
            "losses": list(losses),
            "tokens_seen": tokens_seen,
            "data_cursor": data_cursor,
            "modality_examples": dict(modality_examples),
            "expert_examples": dict(expert_examples),
            "active_expert": active_expert,
        }
        if global_step % checkpoint_every == 0:
            checkpoint_callback(global_step, result)
    if require_complete_coverage:
        missing_capabilities = [name for name, value in modality_examples.items() if value <= 0]
        missing_experts = [name for name, value in expert_examples.items() if value <= 0]
        if missing_capabilities or missing_experts:
            raise RuntimeError(
                "pretraining segment stopped because required exposure is missing: "
                f"capabilities={missing_capabilities}, experts={missing_experts}"
            )
    return {
        "steps": len(records),
        "global_step": initial_global_step + len(records),
        "losses": losses,
        "tokens_seen": tokens_seen,
        "data_cursor": data_cursor,
        "modality_examples": modality_examples,
        "expert_examples": expert_examples,
    }