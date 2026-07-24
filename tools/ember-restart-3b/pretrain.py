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
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from batch import DOMAIN_MODALITIES, decode_owned_batch
from model import EXPERT_NAMES, RestartDecoderConfig, UnifiedDecoder
from specialist_stream import TRAINING_CURSOR_SCHEMA_VERSION
from semantic_stream import ManifestBoundTokenStream

CheckpointCallback = Callable[[int, dict[str, Any]], None]
ProgressCallback = Callable[[dict[str, object]], None]
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
    progress_callback: ProgressCallback | None = None,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
    initial_data_cursor: int = 0,
    data_shard_id: str = "owned-pretraining",
    require_complete_coverage: bool = True,
    max_records: int | None = None,
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
    if max_records is not None and (type(max_records) is not int or max_records < 1 or max_records > 200):
        raise ValueError("pretraining max_records must be an integer from 1 through 200")
    if not isinstance(data_shard_id, str) or not data_shard_id:
        raise ValueError("data_shard_id must be a nonempty owned shard identifier")
    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0, "reasoning": 0, "tool": 0}
    expert_examples = {expert: 0 for expert in EXPERT_NAMES}
    tokens_seen = initial_tokens_seen
    data_cursor = initial_data_cursor
    remaining_records = records[initial_data_cursor:] if max_records is None else records[initial_data_cursor:initial_data_cursor + max_records]
    final_global_step = initial_global_step + len(remaining_records)
    for local_step, record in enumerate(remaining_records, start=1):
        step_started = time.perf_counter()
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
        progress_event = None
        if progress_callback is not None:
            progress_event = {
                "step": global_step,
                "total_steps": final_global_step,
                "loss": losses[-1],
                "step_ms": float((time.perf_counter() - step_started) * 1000.0),
            }
        if global_step % checkpoint_every == 0 or local_step == len(remaining_records):
            checkpoint_callback(global_step, result)
        if progress_event is not None:
            progress_callback(progress_event)
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


def run_selection_pretraining_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    selection: object,
    config: RestartDecoderConfig,
    device: torch.device,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
    progress_callback: ProgressCallback | None = None,
    initial_selection_cursor: Mapping[str, object] | None = None,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
    max_records: int | None = None,
    require_complete_coverage: bool = True,
) -> dict[str, Any]:
    """Train a bounded specialist selection through its sequential cursor interface only."""

    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive")
    if min(initial_global_step, initial_tokens_seen) < 0:
        raise ValueError("resume counters must be nonnegative")
    if max_records is not None and (type(max_records) is not int or max_records <= 0):
        raise ValueError("max_records must be a positive integer when supplied")
    if not isinstance(getattr(selection, "receipt", None), Mapping):
        raise ValueError("selection consumer requires a bound selection receipt")
    iter_from = getattr(selection, "iter_from", None)
    if not callable(iter_from):
        raise ValueError("selection consumer requires sequential iter_from")

    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0, "reasoning": 0, "tool": 0}
    expert_examples = {expert: 0 for expert in EXPERT_NAMES}
    tokens_seen = initial_tokens_seen
    completed = 0
    last_cursor: dict[str, object] | None = None
    last_result: dict[str, Any] | None = None
    last_checkpoint_step: int | None = None
    for item in iter_from(initial_selection_cursor):
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], Mapping) or not isinstance(item[1], Mapping):
            raise ValueError("selection iterator must yield a record and exact next cursor")
        record = dict(item[0])
        next_selection_cursor = dict(item[1])
        step_started = time.perf_counter()
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
            raise RuntimeError(f"pretraining selection stopped on non-finite loss at step {initial_global_step + completed + 1}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        completed += 1
        tokens_seen += int(batch["input_ids"].numel())
        losses.append(float(loss.detach().cpu()))
        if active_expert in EXPERT_NAMES:
            expert_examples[active_expert] += 1
        for capability in capabilities:
            modality_examples[capability] += 1
        global_step = initial_global_step + completed
        last_cursor = next_selection_cursor
        training_cursor = {
            "schema_version": TRAINING_CURSOR_SCHEMA_VERSION,
            "selection_cursor": dict(last_cursor),
            "global_step": global_step,
            "tokens_seen": tokens_seen,
        }
        last_result = {
            "step": global_step, "global_step": global_step, "losses": list(losses), "tokens_seen": tokens_seen,
            "data_cursor": training_cursor, "modality_examples": dict(modality_examples),
            "expert_examples": dict(expert_examples), "active_expert": active_expert,
        }
        progress_event = None
        if progress_callback is not None:
            progress_event = {
                "step": global_step, "total_steps": None, "loss": losses[-1],
                "step_ms": float((time.perf_counter() - step_started) * 1000.0),
            }
        if global_step % checkpoint_every == 0:
            checkpoint_callback(global_step, last_result)
            last_checkpoint_step = global_step
        if progress_event is not None:
            progress_callback(progress_event)
        if max_records is not None and completed >= max_records:
            break
    if last_result is None or last_cursor is None:
        raise ValueError("selection consumer requires at least one selected record")
    if last_checkpoint_step != last_result["global_step"]:
        checkpoint_callback(int(last_result["global_step"]), last_result)
    if require_complete_coverage:
        missing_capabilities = [name for name, value in modality_examples.items() if value <= 0]
        missing_experts = [name for name, value in expert_examples.items() if value <= 0]
        if missing_capabilities or missing_experts:
            raise RuntimeError(
                "pretraining selection stopped because required exposure is missing: "
                f"capabilities={missing_capabilities}, experts={missing_experts}"
            )
    return {
        "steps": completed, "global_step": int(last_result["global_step"]), "losses": losses,
        "tokens_seen": tokens_seen, "data_cursor": dict(last_result["data_cursor"]),
        "modality_examples": modality_examples, "expert_examples": expert_examples,
    }
def run_manifest_bound_semantic_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    stream: ManifestBoundTokenStream,
    config: RestartDecoderConfig,
    device: torch.device,
    sequence_length: int,
    steps: int,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
    initial_data_cursor: Mapping[str, object] | None = None,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
) -> dict[str, Any]:
    """Train bounded shared-text episodes while preserving receipt-bound shard resume state."""

    if not isinstance(sequence_length, int) or sequence_length < 1:
        raise ValueError("semantic stream sequence_length must be positive")
    if not isinstance(steps, int) or steps < 1:
        raise ValueError("semantic stream steps must be positive")
    if type(initial_global_step) is not int or type(initial_tokens_seen) is not int or min(initial_global_step, initial_tokens_seen) < 0:
        raise ValueError("semantic stream resume counters must be nonnegative integers")
    expected_shard = "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12]
    if initial_data_cursor is None:
        shard_index, token_offset = 0, 0
    else:
        if not isinstance(initial_data_cursor, Mapping):
            raise ValueError("semantic stream resume cursor is malformed")
        if (
            initial_data_cursor.get("receipt_sha256") != stream.receipt_sha256
            or initial_data_cursor.get("tokenizer_sha256") != stream.tokenizer_sha256
        ):
            raise ValueError("semantic stream resume cursor does not bind this receipt and tokenizer")
        if (
            initial_data_cursor.get("shard") != expected_shard
            or type(initial_data_cursor.get("record_index")) is not int
            or initial_data_cursor["record_index"] != initial_global_step
            or type(initial_data_cursor.get("global_step")) is not int
            or initial_data_cursor["global_step"] != initial_global_step
            or type(initial_data_cursor.get("tokens_seen")) is not int
            or initial_data_cursor["tokens_seen"] != initial_tokens_seen
        ):
            raise ValueError("semantic stream resume cursor identity is inconsistent")
        shard_index = initial_data_cursor.get("shard_index")
        token_offset = initial_data_cursor.get("token_offset")
        if type(shard_index) is not int or type(token_offset) is not int or shard_index < 0 or token_offset < 0:
            raise ValueError("semantic stream resume cursor is malformed")

    records: list[dict[str, object]] = []
    cursors: list[dict[str, int]] = []
    for _ in range(steps):
        episode, next_cursor = stream.next_episode(
            shard_index=shard_index,
            token_offset=token_offset,
            sequence_length=sequence_length,
        )
        records.append(episode)
        cursors.append(next_cursor)
        shard_index, token_offset = next_cursor["shard_index"], next_cursor["token_offset"]

    def bound_cursor(cursor: Mapping[str, int], global_step: int, tokens_seen: int) -> dict[str, object]:
        return {
            "shard": "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12],
            "record_index": global_step,
            "receipt_sha256": stream.receipt_sha256,
            "tokenizer_sha256": stream.tokenizer_sha256,
            "shard_index": cursor["shard_index"],
            "token_offset": cursor["token_offset"],
            "global_step": global_step,
            "tokens_seen": tokens_seen,
        }

    def stream_checkpoint(global_step: int, state: dict[str, Any]) -> None:
        local_index = global_step - initial_global_step - 1
        checkpoint_state = dict(state)
        checkpoint_state["data_cursor"] = bound_cursor(
            cursors[local_index],
            global_step,
            int(state["tokens_seen"]),
        )
        checkpoint_callback(global_step, checkpoint_state)

    result = run_pretraining_segment(
        model=model,
        optimizer=optimizer,
        records=records,
        config=config,
        device=device,
        checkpoint_every=checkpoint_every,
        checkpoint_callback=stream_checkpoint,
        initial_global_step=initial_global_step,
        initial_tokens_seen=initial_tokens_seen,
        data_shard_id="TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12],
        require_complete_coverage=False,
    )
    result["data_cursor"] = bound_cursor(
        cursors[-1],
        int(result["global_step"]),
        int(result["tokens_seen"]),
    )
    return result
