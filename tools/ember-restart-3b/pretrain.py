# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real bounded pretraining segments over independently verified routed records."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from batch import DOMAIN_MODALITIES, decode_owned_batch
from model import EXPERT_NAMES, RestartDecoderConfig, UnifiedDecoder

CheckpointCallback = Callable[[int, dict[str, Any]], None]
VERIFIER_PATH = Path(__file__).with_name("verify_capability_record.py")
VERIFIER_PUBLIC_PATH = "tools/ember-restart-3b/verify_capability_record.py"


def _verified_capabilities(record: Mapping[str, object], *, active_expert: str) -> set[str]:
    """Execute the exact local verifier before semantic capability credit is counted."""

    if active_expert not in DOMAIN_MODALITIES:
        raise ValueError("record must select a declared routed expert")
    capabilities = {"text", *DOMAIN_MODALITIES[active_expert]}
    if active_expert in {"vision", "audio", "shared"}:
        return capabilities
    receipt = record.get("capability_receipt")
    if not isinstance(receipt, Mapping):
        raise ValueError(f"{active_expert} episode requires a content-addressed local verifier receipt")
    verifier_hash = hashlib.sha256(VERIFIER_PATH.read_bytes()).hexdigest()
    if receipt.get("verifier_path") != VERIFIER_PUBLIC_PATH or receipt.get("verifier_sha256") != verifier_hash:
        raise ValueError("capability receipt is not bound to the exact local verifier bytes")
    encoded = base64.b64encode(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
    completed = subprocess.run(
        [sys.executable, "-I", str(VERIFIER_PATH), "--record-json-base64", encoded],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"local {active_expert} verifier did not pass: {completed.stderr.strip() or completed.stdout.strip()}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("local capability verifier emitted invalid JSON") from error
    if not isinstance(result, dict) or result.get("result") != "PASSED" or result.get("receipt") != dict(receipt):
        raise ValueError("local verifier result does not reproduce the content-addressed receipt")
    capabilities.add(active_expert)
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
    data_shard_id: str = "owned-pretraining",
    require_complete_coverage: bool = True,
) -> dict[str, Any]:
    """Execute verified routed updates and bind counters needed for exact resume."""

    if not records:
        raise ValueError("pretraining segment requires at least one owned record")
    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive")
    if min(initial_global_step, initial_tokens_seen, initial_data_cursor) < 0:
        raise ValueError("resume counters must be nonnegative")
    if initial_data_cursor > len(records):
        raise ValueError("resume data cursor exceeds the bound record sequence")
    if not isinstance(data_shard_id, str) or not data_shard_id:
        raise ValueError("data_shard_id must be a nonempty owned shard identifier")
    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0, "reasoning": 0, "tool": 0}
    expert_examples = {expert: 0 for expert in EXPERT_NAMES}
    tokens_seen = initial_tokens_seen
    data_cursor = initial_data_cursor
    remaining_records = records[initial_data_cursor:]
    for local_step, record in enumerate(remaining_records, start=1):
        batch = decode_owned_batch(record, config, device=device)
        active_expert = batch["active_expert"]
        capabilities = _verified_capabilities(record, active_expert=active_expert)
        optimizer.zero_grad(set_to_none=True)
        logits = model(
            batch["input_ids"], image_patches=batch["image_patches"], audio_frames=batch["audio_frames"],
            image_coordinates=batch["image_coordinates"], spans=batch["spans"], active_expert=active_expert,
        )
        loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), batch["target_ids"].reshape(-1))
        if not torch.isfinite(loss):
            raise RuntimeError(f"pretraining segment stopped on non-finite loss at step {initial_global_step + local_step}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
        tokens_seen += int(batch["input_ids"].numel())
        data_cursor += 1
        if active_expert in EXPERT_NAMES:
            expert_examples[active_expert] += 1
        for capability in capabilities:
            modality_examples[capability] += 1
        global_step = initial_global_step + local_step
        cursor = {"shard": data_shard_id, "record_index": data_cursor, "global_step": global_step, "tokens_seen": tokens_seen}
        result = {
            "step": global_step, "global_step": global_step, "losses": list(losses), "tokens_seen": tokens_seen,
            "data_cursor": cursor, "modality_examples": dict(modality_examples),
            "expert_examples": dict(expert_examples), "active_expert": active_expert,
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
        "steps": len(remaining_records), "global_step": initial_global_step + len(remaining_records), "losses": losses,
        "tokens_seen": tokens_seen,
        "data_cursor": {"shard": data_shard_id, "record_index": data_cursor, "global_step": initial_global_step + len(remaining_records), "tokens_seen": tokens_seen},
        "modality_examples": modality_examples, "expert_examples": expert_examples,
    }