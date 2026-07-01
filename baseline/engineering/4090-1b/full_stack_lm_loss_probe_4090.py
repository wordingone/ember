#!/usr/bin/env python3
"""Full-stack LM-loss probe for the single-4090 >=1B baseline.

This bounded probe runs the locked 1B decoder stack with token embeddings,
position embeddings, all configured transformer layers, tied LM head logits,
cross-entropy loss, backward, and optimizer step. It is representative training
telemetry, not a long-run completion receipt.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import platform
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))



def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_real_token_windows(args: argparse.Namespace, vocab: int, seq: int, batch: int, count: int) -> tuple[list[np.ndarray] | None, list[dict[str, Any]] | None]:
    if not args.token_shard_dir:
        return None, None
    shard_receipt = load_json(args.shard_receipt)
    shard_rows = {row["name"]: row for row in shard_receipt["shards"]}
    shard_name = args.token_shard_name
    if shard_name not in shard_rows:
        raise ValueError(f"token shard {shard_name!r} is not listed in shard receipt")
    shard_path = args.token_shard_dir / shard_name
    if not shard_path.exists():
        raise FileNotFoundError(f"token shard not found: {shard_name}")
    observed_sha256 = sha256_file(shard_path)
    expected_sha256 = shard_rows[shard_name]["sha256"]
    if observed_sha256 != expected_sha256:
        raise ValueError(f"token shard sha256 mismatch for {shard_name}")
    mmap = np.memmap(shard_path, dtype="<u2", mode="r")
    need = batch * seq + 1
    max_start = int(mmap.size) - need
    if max_start < 0:
        raise ValueError("token shard is shorter than requested real-data window")
    stride = int(getattr(args, "token_stride", need))
    if stride <= 0:
        raise ValueError("token stride must be positive")
    windows: list[np.ndarray] = []
    metas: list[dict[str, Any]] = []
    seen_starts: set[int] = set()
    for window_index in range(max(int(count), 1)):
        requested_start = int(args.token_offset) + (window_index * stride if getattr(args, "vary_real_token_window", False) else 0)
        start = min(max(requested_start, 0), max_start)
        found = None
        for pos in range(start, min(max_start + 1, start + int(args.max_real_data_search_tokens) + 1)):
            window = np.asarray(mmap[pos:pos + need], dtype=np.int64)
            if window.size != need:
                continue
            if int(np.count_nonzero(window == 0)):
                continue
            if int(window.max()) >= vocab or int(window.min()) < 0:
                continue
            found = (pos, window.copy())
            break
        if found is None:
            raise ValueError(f"no separator-free real-token window found within search budget for window {window_index}")
        pos, window = found
        if pos in seen_starts:
            raise ValueError(f"varied real-token window search reused stream start {pos}")
        seen_starts.add(pos)
        input_tokens = window[:-1].reshape(batch, seq)
        target_tokens = window[1:].reshape(batch, seq)
        windows.append(np.stack([input_tokens, target_tokens], axis=0))
        metas.append({
            "uses_real_token_data": True,
            "source": "pinned_token_shard_window",
            "window_index": int(window_index),
            "token_shard_receipt": "receipts/token-shards-v0-20260611T170047Z.json",
            "shard_name": shard_name,
            "shard_sha256": expected_sha256,
            "requested_stream_token_start": int(requested_start),
            "stream_token_start": int(pos),
            "tokens_consumed_including_next_token": int(need),
            "input_tokens_sha256": hashlib.sha256(input_tokens.astype("<u2", copy=False).tobytes()).hexdigest(),
            "target_tokens_sha256": hashlib.sha256(target_tokens.astype("<u2", copy=False).tobytes()).hexdigest(),
            "separator_token_id": 0,
            "separator_tokens_in_window": 0,
            "max_token_id_in_window": int(window.max()),
        })
    return windows, metas


def load_real_token_window(args: argparse.Namespace, vocab: int, seq: int, batch: int) -> tuple[np.ndarray | None, dict[str, Any] | None]:
    windows, metas = load_real_token_windows(args, vocab, seq, batch, 1)
    if windows is None or metas is None:
        return None, None
    return windows[0], metas[0]


def open_real_token_stream_loader(args: argparse.Namespace, vocab: int, seq: int, batch: int):
    """Return a timed-step loader for pinned real-token windows.

    The shard hash check and memmap open are setup costs. Each call performs the
    window search, CPU copy, metadata hashing, and tensor source construction
    inside the caller's timed step.
    """
    if not args.token_shard_dir:
        return None, None
    shard_receipt = load_json(args.shard_receipt)
    shard_rows = {row["name"]: row for row in shard_receipt["shards"]}
    shard_name = args.token_shard_name
    if shard_name not in shard_rows:
        raise ValueError(f"token shard {shard_name!r} is not listed in shard receipt")
    shard_path = args.token_shard_dir / shard_name
    if not shard_path.exists():
        raise FileNotFoundError(f"token shard not found: {shard_name}")
    observed_sha256 = sha256_file(shard_path)
    expected_sha256 = shard_rows[shard_name]["sha256"]
    if observed_sha256 != expected_sha256:
        raise ValueError(f"token shard sha256 mismatch for {shard_name}")
    mmap = np.memmap(shard_path, dtype="<u2", mode="r")
    need = batch * seq + 1
    max_start = int(mmap.size) - need
    if max_start < 0:
        raise ValueError("token shard is shorter than requested real-data window")
    stride = int(getattr(args, "token_stride", need))
    if stride <= 0:
        raise ValueError("token stride must be positive")
    seen_starts: set[int] = set()

    def load_window(window_index: int) -> tuple[np.ndarray, dict[str, Any]]:
        requested_start = int(args.token_offset) + (window_index * stride if getattr(args, "vary_real_token_window", False) else 0)
        start = min(max(requested_start, 0), max_start)
        found = None
        for pos in range(start, min(max_start + 1, start + int(args.max_real_data_search_tokens) + 1)):
            window = np.asarray(mmap[pos:pos + need], dtype=np.int64)
            if window.size != need:
                continue
            if int(np.count_nonzero(window == 0)):
                continue
            if int(window.max()) >= vocab or int(window.min()) < 0:
                continue
            found = (pos, window.copy())
            break
        if found is None:
            raise ValueError(f"no separator-free real-token window found within search budget for streamed window {window_index}")
        pos, window = found
        if pos in seen_starts:
            raise ValueError(f"streamed real-token window search reused stream start {pos}")
        seen_starts.add(pos)
        input_tokens = window[:-1].reshape(batch, seq)
        target_tokens = window[1:].reshape(batch, seq)
        meta = {
            "uses_real_token_data": True,
            "source": "pinned_token_shard_stream_loader",
            "window_index": int(window_index),
            "token_shard_receipt": "receipts/token-shards-v0-20260611T170047Z.json",
            "shard_name": shard_name,
            "shard_sha256": expected_sha256,
            "requested_stream_token_start": int(requested_start),
            "stream_token_start": int(pos),
            "tokens_consumed_including_next_token": int(need),
            "input_tokens_sha256": hashlib.sha256(input_tokens.astype("<u2", copy=False).tobytes()).hexdigest(),
            "target_tokens_sha256": hashlib.sha256(target_tokens.astype("<u2", copy=False).tobytes()).hexdigest(),
            "separator_token_id": 0,
            "separator_tokens_in_window": 0,
            "max_token_id_in_window": int(window.max()),
        }
        return np.stack([input_tokens, target_tokens], axis=0), meta

    stream_meta = {
        "source": "pinned_token_shard_stream_loader",
        "token_shard_receipt": "receipts/token-shards-v0-20260611T170047Z.json",
        "shard_name": shard_name,
        "shard_sha256": expected_sha256,
        "sha256_verified_before_timing": True,
        "memmap_opened_before_timing": True,
        "window_search_and_tensor_source_inside_timed_step": True,
        "local_path_recorded": False,
    }
    return load_window, stream_meta

def analytical_parameter_count(model: dict[str, Any]) -> dict[str, int]:
    vocab = int(model["vocab_size"])
    seq = int(model["sequence_length"])
    layers = int(model["n_layers"])
    d = int(model["n_embd"])
    mlp = int(model.get("mlp_ratio", 4)) * d
    bias = 1 if model.get("bias", False) else 0
    token_embedding = vocab * d
    position_embedding = seq * d
    attention = layers * ((3 * d * d + 3 * d * bias) + (d * d + d * bias))
    mlp_params = layers * ((d * mlp + mlp * bias) + (mlp * d + d * bias))
    norms = layers * 4 * d + 2 * d
    lm_head = 0 if model.get("tie_embeddings", True) else vocab * d
    total = token_embedding + position_embedding + attention + mlp_params + norms + lm_head
    return {
        "active_trainable_parameters": total,
        "token_embedding": token_embedding,
        "position_embedding": position_embedding,
        "attention": attention,
        "mlp": mlp_params,
        "norms": norms,
        "lm_head": lm_head,
    }


def run_probe(args: argparse.Namespace, raw: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.checkpoint import checkpoint

    if not torch.cuda.is_available():
        return {"verdict": "INVALID_RUN_CUDA_UNAVAILABLE", "cuda_available": False, "torch_version": torch.__version__}

    torch.manual_seed(int(args.seed))
    torch.cuda.manual_seed_all(int(args.seed))
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    device = torch.device("cuda:0")
    model_cfg = raw["model"]
    batch = int(args.batch_size)
    seq = int(args.seq_len or model_cfg["sequence_length"])
    hidden = int(model_cfg["n_embd"])
    heads = int(model_cfg["n_heads"])
    layers = int(model_cfg["n_layers"])
    head_dim = hidden // heads
    mlp_hidden = int(model_cfg.get("mlp_ratio", 4)) * hidden
    vocab = int(model_cfg["vocab_size"])
    dtype = torch.bfloat16 if args.dtype == "bfloat16" and torch.cuda.is_bf16_supported() else torch.float16

    class DecoderBlock(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.ln1 = nn.LayerNorm(hidden)
            self.qkv = nn.Linear(hidden, 3 * hidden, bias=False)
            self.proj = nn.Linear(hidden, hidden, bias=False)
            self.ln2 = nn.LayerNorm(hidden)
            self.fc1 = nn.Linear(hidden, mlp_hidden, bias=False)
            self.fc2 = nn.Linear(mlp_hidden, hidden, bias=False)

        def forward(self, x):
            y = self.ln1(x)
            qkv = self.qkv(y).view(batch, seq, 3, heads, head_dim).permute(2, 0, 3, 1, 4)
            q, k, v = qkv[0], qkv[1], qkv[2]
            y = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=0.0)
            y = y.transpose(1, 2).contiguous().view(batch, seq, hidden)
            x = x + self.proj(y)
            y = self.fc2(F.gelu(self.fc1(self.ln2(x))))
            return x + y

    class FullStackLM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.tok = nn.Embedding(vocab, hidden)
            self.pos = nn.Parameter(torch.zeros(1, int(model_cfg["sequence_length"]), hidden))
            self.blocks = nn.ModuleList([DecoderBlock() for _ in range(layers)])
            self.ln = nn.LayerNorm(hidden)

        def forward(self, idx):
            x = self.tok(idx) + self.pos[:, :seq, :]
            for block in self.blocks:
                if args.activation_checkpointing:
                    x = checkpoint(block, x, use_reentrant=False)
                else:
                    x = block(x)
            x = self.ln(x)
            return F.linear(x, self.tok.weight)

    torch.cuda.empty_cache()
    try:
        torch.cuda.reset_peak_memory_stats(0)
    except Exception:
        pass
    model = FullStackLM().to(device=device, dtype=dtype)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4) if args.optimizer == "adamw" else torch.optim.SGD(model.parameters(), lr=1e-4)
    optimizer_name = "AdamW" if args.optimizer == "adamw" else "SGD"
    real_token_loader = None
    real_data_stream = None
    if args.stream_real_token_loader:
        real_token_loader, real_data_stream = open_real_token_stream_loader(args, vocab, seq, batch)
        real_token_windows = None
        real_data_windows = []
    elif args.vary_real_token_window:
        real_token_windows, real_data_windows = load_real_token_windows(args, vocab, seq, batch, int(args.steps))
    else:
        real_tokens, real_data_window = load_real_token_window(args, vocab, seq, batch)
        real_token_windows = [real_tokens] if real_tokens is not None else None
        real_data_windows = [real_data_window] if real_data_window is not None else None
    if real_token_loader is not None:
        idx = torch.empty((batch, seq), dtype=torch.long, device=device)
        targets = torch.empty((batch, seq), dtype=torch.long, device=device)
        uses_real_token_data = True
    elif real_token_windows is None:
        idx = torch.randint(0, vocab, (batch, seq), device=device)
        targets = torch.roll(idx, shifts=-1, dims=1)
        uses_real_token_data = False
    else:
        idx = torch.as_tensor(real_token_windows[0][0], dtype=torch.long, device=device)
        targets = torch.as_tensor(real_token_windows[0][1], dtype=torch.long, device=device)
        uses_real_token_data = True
    real_data_window = real_data_windows[0] if real_data_windows else None
    real_data_window_hashes = [row["input_tokens_sha256"] for row in real_data_windows or []]
    dataloader_elapsed_s = 0.0
    dataloader_step_times_s: list[float] = []
    stack_params = sum(p.numel() for p in model.parameters())
    tokens_per_step = batch * seq
    losses = []
    completed = 0
    checkpoint_resume = None
    checkpoint_cadence = None
    checkpoint_events: list[dict[str, Any]] = []
    checkpoint_elapsed_s = 0.0
    eval_accounting = None
    eval_losses: list[float] = []
    eval_windows: list[dict[str, Any]] = []
    eval_elapsed_s = 0.0
    eval_loader_elapsed_s = 0.0
    eval_step_times_s: list[float] = []
    eval_loader_step_times_s: list[float] = []
    recovery_accounting = None
    recovery_elapsed_s = 0.0

    def train_one_step(step_index: int) -> float:
        nonlocal idx, targets, dataloader_elapsed_s, real_data_window, real_data_window_hashes
        if real_token_loader is not None:
            data_start = time.perf_counter()
            window, meta = real_token_loader(step_index)
            idx = torch.as_tensor(window[0], dtype=torch.long, device=device)
            targets = torch.as_tensor(window[1], dtype=torch.long, device=device)
            torch.cuda.synchronize(0)
            data_elapsed = time.perf_counter() - data_start
            dataloader_elapsed_s += data_elapsed
            dataloader_step_times_s.append(data_elapsed)
            real_data_windows.append(meta)
            real_data_window = real_data_windows[0]
            real_data_window_hashes = [row["input_tokens_sha256"] for row in real_data_windows]
        elif real_token_windows is not None and args.vary_real_token_window:
            window = real_token_windows[step_index]
            idx = torch.as_tensor(window[0], dtype=torch.long, device=device)
            targets = torch.as_tensor(window[1], dtype=torch.long, device=device)
        opt.zero_grad(set_to_none=True)
        logits = model(idx)
        loss = F.cross_entropy(logits.reshape(-1, vocab).float(), targets.reshape(-1))
        loss.backward()
        opt.step()
        torch.cuda.synchronize(0)
        return float(loss.detach().cpu())

    def file_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    start = time.perf_counter()
    for _ in range(args.steps):
        losses.append(train_one_step(completed))
        completed += 1
        should_checkpoint_once = args.checkpoint_resume_probe and completed == int(args.checkpoint_after_steps)
        should_checkpoint_cadence = args.checkpoint_cadence_probe and completed % int(args.checkpoint_interval_steps) == 0
        if should_checkpoint_once or should_checkpoint_cadence:
            checkpoint_start = time.perf_counter()
            if args.checkpoint_path is None:
                ckpt_path = Path(tempfile.gettempdir()) / ("ember-c1-checkpoint-cadence-probe.pt" if args.checkpoint_cadence_probe else "ember-c1-checkpoint-resume-probe.pt")
            else:
                ckpt_path = args.checkpoint_path
            if args.checkpoint_cadence_probe:
                ckpt_path = ckpt_path.with_name(f"{ckpt_path.stem}-step-{completed}{ckpt_path.suffix}")
            ckpt_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model": model.state_dict(),
                "optimizer": opt.state_dict(),
                "completed_steps": completed,
                "seed": int(args.seed),
                "real_data_window": real_data_window,
                "real_data_window_count": len(real_data_windows or []),
                "checkpoint_resume": checkpoint_resume,
                "checkpoint_event_index": len(checkpoint_events),
                "config_id": raw.get("config_id"),
                "lane": raw.get("lane"),
            }, ckpt_path)
            checkpoint_sha256 = file_sha256(ckpt_path)
            checkpoint_size = ckpt_path.stat().st_size
            del model
            del opt
            torch.cuda.empty_cache()
            model = FullStackLM().to(device=device, dtype=dtype)
            opt = torch.optim.AdamW(model.parameters(), lr=1e-4) if args.optimizer == "adamw" else torch.optim.SGD(model.parameters(), lr=1e-4)
            loaded = torch.load(ckpt_path, map_location=device, weights_only=False)
            model.load_state_dict(loaded["model"])
            opt.load_state_dict(loaded["optimizer"])
            event = {
                "checkpoint_index": len(checkpoint_events),
                "checkpoint_after_steps": completed,
                "checkpoint_sha256": checkpoint_sha256,
                "checkpoint_size_bytes": checkpoint_size,
                "loaded_completed_steps": int(loaded.get("completed_steps", -1)),
                "loaded_seed": int(loaded.get("seed", -1)),
                "loaded_lane": loaded.get("lane"),
                "remaining_steps_after_reload": int(args.steps) - completed,
                "checkpoint_path_recorded": False,
                "checkpoint_contains_optimizer_state": True,
                "checkpoint_contains_model_state": True,
            }
            try:
                ckpt_path.unlink()
                event["checkpoint_deleted_after_hash"] = True
            except OSError:
                event["checkpoint_deleted_after_hash"] = False
            event["checkpoint_elapsed_s"] = time.perf_counter() - checkpoint_start
            checkpoint_elapsed_s += event["checkpoint_elapsed_s"]
            if should_checkpoint_cadence:
                checkpoint_events.append(event)
            if should_checkpoint_once:
                checkpoint_resume = {
                    "enabled": True,
                    "checkpoint_after_steps": completed,
                    "checkpoint_sha256": checkpoint_sha256,
                    "checkpoint_size_bytes": checkpoint_size,
                    "loaded_completed_steps": event["loaded_completed_steps"],
                    "loaded_seed": event["loaded_seed"],
                    "loaded_lane": event["loaded_lane"],
                    "resumed_for_additional_steps": int(args.steps) - completed,
                    "checkpoint_path_recorded": False,
                    "checkpoint_contains_optimizer_state": True,
                    "checkpoint_contains_model_state": True,
                    "checkpoint_deleted_after_hash": event["checkpoint_deleted_after_hash"],
                }
        if time.perf_counter() - start > args.max_seconds:
            break
    if args.checkpoint_resume_probe and checkpoint_resume is None:
        checkpoint_resume = {"enabled": True, "error": "checkpoint step was not reached", "checkpoint_path_recorded": False}
    if args.checkpoint_cadence_probe:
        checkpoint_cadence = {
            "enabled": True,
            "checkpoint_interval_steps": int(args.checkpoint_interval_steps),
            "checkpoint_event_count": len(checkpoint_events),
            "checkpoint_events": checkpoint_events,
            "checkpoint_elapsed_s": checkpoint_elapsed_s,
            "checkpoint_path_recorded": False,
            "all_checkpoints_deleted_after_hash": all(event.get("checkpoint_deleted_after_hash") is True for event in checkpoint_events),
            "all_checkpoints_contain_model_state": all(event.get("checkpoint_contains_model_state") is True for event in checkpoint_events),
            "all_checkpoints_contain_optimizer_state": all(event.get("checkpoint_contains_optimizer_state") is True for event in checkpoint_events),
        }
    if args.eval_accounting_probe:
        if real_token_loader is None:
            raise ValueError("eval accounting probe requires --stream-real-token-loader")
        prev_checkpointing = args.activation_checkpointing
        args.activation_checkpointing = False
        model.eval()
        with torch.no_grad():
            for eval_index in range(int(args.eval_steps)):
                eval_step_start = time.perf_counter()
                eval_loader_start = time.perf_counter()
                window, meta = real_token_loader(completed + eval_index)
                eval_idx = torch.as_tensor(window[0], dtype=torch.long, device=device)
                eval_targets = torch.as_tensor(window[1], dtype=torch.long, device=device)
                torch.cuda.synchronize(0)
                loader_elapsed = time.perf_counter() - eval_loader_start
                logits = model(eval_idx)
                eval_loss = F.cross_entropy(logits.reshape(-1, vocab).float(), eval_targets.reshape(-1))
                torch.cuda.synchronize(0)
                step_elapsed = time.perf_counter() - eval_step_start
                eval_losses.append(float(eval_loss.detach().cpu()))
                meta["eval_window_index"] = int(eval_index)
                eval_windows.append(meta)
                eval_loader_elapsed_s += loader_elapsed
                eval_loader_step_times_s.append(loader_elapsed)
                eval_step_times_s.append(step_elapsed)
        model.train()
        args.activation_checkpointing = prev_checkpointing
        eval_elapsed_s = sum(eval_step_times_s)
        eval_hashes = [row["input_tokens_sha256"] for row in eval_windows]
        eval_accounting = {
            "enabled": True,
            "eval_steps": int(args.eval_steps),
            "eval_window_count": len(eval_windows),
            "eval_unique_input_window_count": len(set(eval_hashes)),
            "eval_losses": eval_losses,
            "eval_loss_mean": sum(eval_losses) / len(eval_losses) if eval_losses else None,
            "eval_loss_is_finite_all_steps": all(x == x and abs(x) != float("inf") for x in eval_losses),
            "eval_windows": eval_windows,
            "eval_windows_sha256": hashlib.sha256("\n".join(eval_hashes).encode("utf-8")).hexdigest() if eval_hashes else None,
            "eval_elapsed_s": eval_elapsed_s,
            "eval_step_times_s": eval_step_times_s,
            "eval_loader_elapsed_s": eval_loader_elapsed_s,
            "eval_loader_step_times_s": eval_loader_step_times_s,
            "eval_uses_no_grad": True,
            "eval_activation_checkpointing_disabled": True,
            "eval_included_in_total_elapsed": True,
            "local_path_recorded": False,
        }
    if args.recovery_accounting_probe:
        if real_token_loader is None:
            raise ValueError("recovery accounting probe requires --stream-real-token-loader")
        recovery_start = time.perf_counter()
        ckpt_path = args.checkpoint_path or (Path(tempfile.gettempdir()) / "ember-c1-recovery-accounting-probe.pt")
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "model": model.state_dict(),
            "optimizer": opt.state_dict(),
            "completed_steps": completed,
            "seed": int(args.seed),
            "real_data_window_count": len(real_data_windows or []),
            "config_id": raw.get("config_id"),
            "lane": raw.get("lane"),
        }, ckpt_path)
        recovery_checkpoint_sha256 = file_sha256(ckpt_path)
        recovery_checkpoint_size = ckpt_path.stat().st_size
        del model
        del opt
        torch.cuda.empty_cache()
        model = FullStackLM().to(device=device, dtype=dtype)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4) if args.optimizer == "adamw" else torch.optim.SGD(model.parameters(), lr=1e-4)
        recovery_load_start = time.perf_counter()
        loaded = torch.load(ckpt_path, map_location=device, weights_only=False)
        model.load_state_dict(loaded["model"])
        opt.load_state_dict(loaded["optimizer"])
        torch.cuda.synchronize(0)
        recovery_load_elapsed_s = time.perf_counter() - recovery_load_start
        recovery_window_base = completed + (int(args.eval_steps) if args.eval_accounting_probe else 0)
        post_recovery_train_start = time.perf_counter()
        post_window, post_meta = real_token_loader(recovery_window_base)
        idx = torch.as_tensor(post_window[0], dtype=torch.long, device=device)
        targets = torch.as_tensor(post_window[1], dtype=torch.long, device=device)
        opt.zero_grad(set_to_none=True)
        logits = model(idx)
        post_recovery_loss = F.cross_entropy(logits.reshape(-1, vocab).float(), targets.reshape(-1))
        post_recovery_loss.backward()
        opt.step()
        torch.cuda.synchronize(0)
        post_recovery_train_elapsed_s = time.perf_counter() - post_recovery_train_start
        post_recovery_eval_start = time.perf_counter()
        eval_window, eval_meta = real_token_loader(recovery_window_base + 1)
        prev_checkpointing = args.activation_checkpointing
        args.activation_checkpointing = False
        model.eval()
        with torch.no_grad():
            eval_idx = torch.as_tensor(eval_window[0], dtype=torch.long, device=device)
            eval_targets = torch.as_tensor(eval_window[1], dtype=torch.long, device=device)
            eval_logits = model(eval_idx)
            post_recovery_eval_loss = F.cross_entropy(eval_logits.reshape(-1, vocab).float(), eval_targets.reshape(-1))
            torch.cuda.synchronize(0)
        model.train()
        args.activation_checkpointing = prev_checkpointing
        post_recovery_eval_elapsed_s = time.perf_counter() - post_recovery_eval_start
        try:
            ckpt_path.unlink()
            recovery_checkpoint_deleted = True
        except OSError:
            recovery_checkpoint_deleted = False
        recovery_elapsed_s = time.perf_counter() - recovery_start
        recovery_accounting = {
            "enabled": True,
            "checkpoint_sha256": recovery_checkpoint_sha256,
            "checkpoint_size_bytes": recovery_checkpoint_size,
            "checkpoint_path_recorded": False,
            "checkpoint_deleted_after_hash": recovery_checkpoint_deleted,
            "checkpoint_contains_model_state": True,
            "checkpoint_contains_optimizer_state": True,
            "loaded_completed_steps": int(loaded.get("completed_steps", -1)),
            "loaded_seed": int(loaded.get("seed", -1)),
            "loaded_lane": loaded.get("lane"),
            "recovery_window_base": int(recovery_window_base),
            "recovery_load_elapsed_s": recovery_load_elapsed_s,
            "post_recovery_train_elapsed_s": post_recovery_train_elapsed_s,
            "post_recovery_train_loss": float(post_recovery_loss.detach().cpu()),
            "post_recovery_train_window": post_meta,
            "post_recovery_eval_elapsed_s": post_recovery_eval_elapsed_s,
            "post_recovery_eval_loss": float(post_recovery_eval_loss.detach().cpu()),
            "post_recovery_eval_window": eval_meta,
            "post_recovery_eval_uses_no_grad": True,
            "post_recovery_eval_activation_checkpointing_disabled": True,
            "recovery_elapsed_s": recovery_elapsed_s,
            "recovery_included_in_total_elapsed": True,
            "local_path_recorded": False,
        }
    elapsed = time.perf_counter() - start
    lower_bound_flops = 6.0 * counts["active_trainable_parameters"] * tokens_per_step * max(completed, 1)
    token_budget = int(raw["training"]["token_budget"])
    days_threshold = float(raw["training"].get("days_scale_threshold", 14))
    required_full_tflops = 6.0 * counts["active_trainable_parameters"] * token_budget / (days_threshold * 86400.0) / 1e12
    return {
        "verdict": "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION",
        "cuda_available": True,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0),
        "device_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "dtype": str(dtype).replace("torch.", ""),
        "optimizer": optimizer_name,
        "uses_scaled_dot_product_attention": True,
        "uses_activation_checkpointing": bool(args.activation_checkpointing),
        "uses_hidden_state_surrogate_loss": False,
        "uses_full_lm_head_loss": True,
        "uses_tied_lm_head": bool(model_cfg.get("tie_embeddings", True)),
        "seed": int(args.seed),
        "uses_real_token_data": uses_real_token_data,
        "uses_varied_real_token_windows": bool(args.vary_real_token_window and uses_real_token_data),
        "includes_dataloader_timing": bool(args.stream_real_token_loader),
        "dataloader_window_loaded_inside_timed_step": bool(args.stream_real_token_loader),
        "real_data_stream": real_data_stream,
        "dataloader_elapsed_s": dataloader_elapsed_s,
        "dataloader_step_times_s": dataloader_step_times_s,
        "dataloader_elapsed_fraction": dataloader_elapsed_s / elapsed if elapsed > 0 else None,
        "real_data_window": real_data_window,
        "real_data_windows": real_data_windows,
        "real_data_window_count": len(real_data_windows or []),
        "real_data_unique_input_window_count": len(set(real_data_window_hashes)),
        "real_data_windows_sha256": hashlib.sha256("\n".join(real_data_window_hashes).encode("utf-8")).hexdigest() if real_data_window_hashes else None,
        "token_stride": int(args.token_stride),
        "checkpoint_resume": checkpoint_resume,
        "checkpoint_cadence": checkpoint_cadence,
        "checkpoint_elapsed_s": checkpoint_elapsed_s,
        "checkpoint_elapsed_fraction": checkpoint_elapsed_s / elapsed if elapsed > 0 else None,
        "eval_accounting": eval_accounting,
        "eval_elapsed_s": eval_elapsed_s,
        "eval_elapsed_fraction": eval_elapsed_s / elapsed if elapsed > 0 else None,
        "recovery_accounting": recovery_accounting,
        "recovery_elapsed_s": recovery_elapsed_s,
        "recovery_elapsed_fraction": recovery_elapsed_s / elapsed if elapsed > 0 else None,
        "probe_shape": {
            "batch_size": batch,
            "seq_len": seq,
            "configured_sequence_length": int(model_cfg["sequence_length"]),
            "full_sequence_length_executed": seq == int(model_cfg["sequence_length"]),
            "vocab_size": vocab,
            "hidden": hidden,
            "heads": heads,
            "head_dim": head_dim,
            "mlp_hidden": mlp_hidden,
            "model_layers": layers,
            "layers_executed": layers,
            "stack_parameters_materialized": stack_params,
            "full_model_active_trainable_parameters": counts["active_trainable_parameters"],
            "logit_elements_per_step": batch * seq * vocab,
        },
        "steps_requested": args.steps,
        "steps_completed": completed,
        "elapsed_s": elapsed,
        "tokens_per_second": tokens_per_step * completed / elapsed if elapsed > 0 else None,
        "estimated_stack_training_tflops_lower_bound": lower_bound_flops / elapsed / 1e12 if elapsed > 0 else None,
        "full_config_required_sustained_tflops": required_full_tflops,
        "peak_memory_bytes": torch.cuda.max_memory_allocated(0),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "loss_values": losses,
        "loss_is_finite_all_steps": all(x == x and abs(x) != float("inf") for x in losses),
        "completion_limit": (
            "Full-stack LM-loss probe executes bounded streamed training, saves a model+optimizer recovery checkpoint, reloads fresh model/optimizer state, runs a post-recovery streamed train step, and runs post-recovery no-grad LM-head eval with recovery time included in total elapsed. It is bounded recovery-accounting telemetry only: not a long-run recovery policy receipt, not a full external evaluation suite, not convergence, not a dedupe/contamination PASS, not a long-run 1B language-model training receipt, and not family completion by itself."
            if args.recovery_accounting_probe
            else (
                "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, repeated optimizer steps, streamed real-token loading, and no-grad LM-head evaluation on additional pinned real-token windows with eval time included in total elapsed. It is bounded eval-accounting telemetry only: not a full external evaluation suite, not convergence, not recovery accounting, not a dedupe/contamination PASS, not a long-run 1B language-model training receipt, and not family completion by itself."
                if args.eval_accounting_probe
                else (
                "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, repeated optimizer steps, streamed real-token loading, and repeated model+optimizer checkpoint save/hash/reload/delete events at a fixed cadence. It is bounded checkpoint-cadence telemetry only: not a long-run checkpoint policy receipt, not external evaluation/recovery accounting, not a dedupe/contamination PASS, not a long-run 1B language-model training receipt, and not family completion by itself."
                if args.checkpoint_cadence_probe
                else (
                "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, optimizer step, checkpoint save/hash/reload, and post-resume optimizer step on a pinned real-token shard window. It is bounded checkpoint/resume telemetry only: not a long-run checkpoint cadence receipt, not a dedupe/contamination PASS, not a long-run 1B language-model training receipt, and not family completion by itself."
                if args.checkpoint_resume_probe
                else (
                "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, repeated optimizer steps, and timed per-step memmap window loading/GPU tensor creation across varied pinned real-token shard windows. It is bounded dataloader-inclusive varied-window throughput telemetry only: not a long-run training receipt, not full-data coverage, not convergence, not checkpoint cadence, not evaluation/recovery accounting, not a dedupe/contamination PASS, and not family completion by itself."
                if uses_real_token_data and args.stream_real_token_loader
                else (
                    "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, and repeated optimizer steps across varied pinned real-token shard windows. It is bounded varied-window throughput telemetry only: not a real dataloader long-run, not full-data coverage, not convergence, not checkpoint cadence, not a dedupe/contamination PASS, and not family completion by itself."
                    if uses_real_token_data and args.vary_real_token_window
                    else (
                        "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, and repeated optimizer steps on the same pinned real-token shard window. It is bounded multi-step stability telemetry only: not full-data coverage, not convergence, not long-run throughput, not a dedupe/contamination PASS, and not family completion by itself."
                        if uses_real_token_data and completed > 1
                        else (
                            "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, and optimizer step on a pinned real-token shard window. It is not a multi-step stability receipt, not a checkpoint/resume receipt, not a dedupe/contamination PASS, not a long-run 1B language-model training receipt, and not family completion by itself."
                            if uses_real_token_data
                            else "Full-stack LM-loss probe executes all configured transformer layers, tied LM head logits, cross-entropy, backward, and optimizer step on synthetic random tokens. It is not a real-data receipt, not a long-run 1B language-model training receipt, not a dedupe/contamination receipt, and not family completion by itself."
                        )
                    )
                )
                )
                )
                )
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capability-target", required=True)
    parser.add_argument("--steps", type=int, default=1)
    parser.add_argument("--max-seconds", type=float, default=900.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--seq-len", type=int)
    parser.add_argument("--dtype", choices=["bfloat16", "float16"], default="bfloat16")
    parser.add_argument("--optimizer", choices=["adamw", "sgd"], default="adamw")
    parser.add_argument("--activation-checkpointing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--token-shard-dir", type=Path, help="Directory containing pinned v0 token shards for real-data probe mode.")
    parser.add_argument("--token-shard-name", default="v0-00000.bin")
    parser.add_argument("--token-offset", type=int, default=1_048_576)
    parser.add_argument("--token-stride", type=int, default=8192)
    parser.add_argument("--vary-real-token-window", action="store_true")
    parser.add_argument("--stream-real-token-loader", action="store_true")
    parser.add_argument("--max-real-data-search-tokens", type=int, default=1_000_000)
    parser.add_argument("--shard-receipt", type=Path, default=Path("receipts/token-shards-v0-20260611T170047Z.json"))
    parser.add_argument("--checkpoint-resume-probe", action="store_true")
    parser.add_argument("--checkpoint-after-steps", type=int, default=1)
    parser.add_argument("--checkpoint-cadence-probe", action="store_true")
    parser.add_argument("--checkpoint-interval-steps", type=int, default=2)
    parser.add_argument("--eval-accounting-probe", action="store_true")
    parser.add_argument("--eval-steps", type=int, default=2)
    parser.add_argument("--recovery-accounting-probe", action="store_true")
    parser.add_argument("--checkpoint-path", type=Path)
    args = parser.parse_args()

    raw = load_json(args.config)
    counts = analytical_parameter_count(raw["model"])
    receipt: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "kind": "single_4090_full_stack_lm_loss_probe",
        "config_path": str(args.config),
        "config_id": raw.get("config_id"),
        "lane": raw.get("lane"),
        "capability_target": args.capability_target,
        "active_trainable_parameters": counts["active_trainable_parameters"],
        "parameter_count": counts,
        "stop_rule": {"max_seconds": args.max_seconds, "steps": args.steps, "no_completion_claim": True},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
    }
    try:
        receipt.update(run_probe(args, raw, counts))
    except Exception as exc:
        import traceback
        receipt["verdict"] = "INVALID_RUN_EXCEPTION"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("verdict") == "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
