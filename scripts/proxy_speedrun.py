"""proxy_speedrun.py — proxy-speedrun harness for registry-gate technique evaluation (#271).

Implements the proxy-speedrun contract from docs/registry-dispatch-gate-spec-v0.md:

  Frozen proxy: ~65M params (LLaMA-config, hidden=512, 12 layers, 8 heads,
  vocab=32000, seq=512, tied embeddings, grad checkpointing).
  Pinned slice: v0-00000.bin + v0-00001.bin (first 2 shards of shards-v0).
  Seeds: {16, 17, 18}.
  Arm: BASELINE — plain AdamW + bf16, no registry techniques.
  Governed: VRAM fraction 0.80, margin 1.5 GiB, pace 0.05 s/step.

Output per seed: final_loss, tokens_processed, wall_clock_s, step_count.
Receipt: receipts/proxy-speedrun-baseline-<ts>.json
  Contains: arm, config, governor, per_seed results, aggregate, frozen_target.

AC(b): one baseline-arm receipt in receipts/ (presence = PASS).

Selftest (CPU, no GPU): python proxy_speedrun.py --selftest
  Marker: PROXY_SPEEDRUN_SELFTEST_PASS

Run via native Windows Python — NOT train MCP daemon.
DO NOT touch live run 12c050e7.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)  # repo30 root
sys.path.insert(0, HERE)

RECEIPTS = os.path.join(NC, "receipts")

# ---------------------------------------------------------------------------
# Proxy architecture (frozen — never change for baseline comparability)
# ---------------------------------------------------------------------------
HIDDEN  = 512
LAYERS  = 12
HEADS   = 8
FFN     = 2048   # 4 × HIDDEN
VOCAB   = 32000
SEQ     = 512
BATCH   = 8
STEPS   = 500    # baseline arm length (establishes frozen_target loss)

# Governor rails (fp19 floor — never relax)
VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

SEEDS = [16, 17, 18]

# Pinned shard slice (first 2 shards, ~537M tokens total)
SHARD_FILES = ["v0-00000.bin", "v0-00001.bin"]
SHARD_DIR   = os.path.join(os.path.dirname(NC), "shards-v0")


# ---------------------------------------------------------------------------
# Config sha (uniquely identifies this proxy config for arm comparison)
# ---------------------------------------------------------------------------

_PROXY_CONFIG = {
    "arm": "baseline",
    "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
    "ffn": FFN, "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
    "steps": STEPS,
    "optimizer": "AdamW", "lr": 1e-3, "bf16": True,
    "grad_checkpointing": True,
    "shard_files": SHARD_FILES,
    "seeds": SEEDS,
}

CONFIG_SHA = hashlib.sha256(
    json.dumps(_PROXY_CONFIG, sort_keys=True).encode()
).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Shard-backed dataset (uint16 flat binary, pinned slice)
# ---------------------------------------------------------------------------

class ShardDataset:
    """Iterate SEQ-length token windows from the pinned shard slice."""

    def __init__(self, shard_dir: str, shard_files: list[str], seq: int, seed: int):
        import numpy as np
        chunks = []
        for fname in shard_files:
            p = os.path.join(shard_dir, fname)
            if not os.path.exists(p):
                raise FileNotFoundError(f"shard not found: {p}")
            chunks.append(np.memmap(p, dtype=np.uint16, mode="r"))
        self._tokens = np.concatenate([c.astype(np.int64) for c in chunks])
        self._seq = seq
        self._n = len(self._tokens) - seq - 1
        rng = np.random.default_rng(seed)
        self._order = rng.permutation(self._n)
        self._pos = 0

    def next_batch(self, batch: int):
        import numpy as np
        import torch
        idxs = []
        for _ in range(batch):
            if self._pos >= len(self._order):
                self._pos = 0
            idxs.append(self._order[self._pos])
            self._pos += 1
        rows = np.stack([self._tokens[i: i + self._seq + 1] for i in idxs])
        x = torch.from_numpy(rows[:, :-1].copy()).long()
        y = torch.from_numpy(rows[:, 1:].copy()).long()
        return x, y


# ---------------------------------------------------------------------------
# Per-seed training run
# ---------------------------------------------------------------------------

def train_seed(seed: int, torch) -> dict:
    """Run STEPS steps on one seed. Returns result dict."""
    from transformers import LlamaConfig, LlamaForCausalLM

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)

    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN,
        intermediate_size=FFN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS,
        max_position_embeddings=SEQ,
        tie_word_embeddings=True,
        bos_token_id=1, eos_token_id=2,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.gradient_checkpointing_enable()
    model.train()

    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.1)

    dataset = ShardDataset(SHARD_DIR, SHARD_FILES, SEQ, seed)

    losses = []
    t0 = time.perf_counter()

    for step in range(STEPS):
        x, y = dataset.next_batch(BATCH)
        x = x.cuda()
        y = y.cuda()

        out = model(input_ids=x, labels=y)
        loss = out.loss
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)

        losses.append(loss.item())
        time.sleep(PACE_S)

    wall_s = time.perf_counter() - t0
    tokens = STEPS * BATCH * SEQ

    del model, opt, dataset
    torch.cuda.empty_cache()

    return {
        "seed": seed,
        "final_loss": round(losses[-1], 6),
        "mean_last10_loss": round(sum(losses[-10:]) / 10, 6),
        "step_count": STEPS,
        "tokens_processed": tokens,
        "wall_clock_s": round(wall_s, 2),
        "tokens_per_s": round(tokens / wall_s, 1),
        "loss_first": round(losses[0], 6),
        "loss_trajectory_20step": [round(losses[i], 4)
                                   for i in range(0, STEPS, max(1, STEPS // 20))],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import torch

    # Governor preflight
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        raise SystemExit(
            f"PROXY_SPEEDRUN_GOVERNOR_FAIL: {free_gib:.2f} GiB free < "
            f"{MARGIN_GIB} GiB margin — refusing launch")
    governor_block = {
        "vram_fraction": VRAM_FRACTION,
        "margin_gib_floor": MARGIN_GIB,
        "pace_s_per_step": PACE_S,
        "free_gib_at_launch": round(free_gib, 2),
        "total_gib": round(total_b / (1 << 30), 2),
    }

    # Shard check
    for fname in SHARD_FILES:
        p = os.path.join(SHARD_DIR, fname)
        if not os.path.exists(p):
            raise SystemExit(f"PROXY_SPEEDRUN_SHARD_MISSING: {p}")

    print(f"[proxy_speedrun] BASELINE arm — config_sha={CONFIG_SHA}", flush=True)
    print(f"  model: ~65M params, hidden={HIDDEN}, layers={LAYERS}, "
          f"heads={HEADS}, seq={SEQ}, batch={BATCH}", flush=True)
    print(f"  shard_dir: {SHARD_DIR}", flush=True)
    print(f"  seeds: {SEEDS}, steps: {STEPS}", flush=True)

    per_seed = []
    for seed in SEEDS:
        print(f"[proxy_speedrun] seed={seed} ...", flush=True)
        result = train_seed(seed, torch)
        per_seed.append(result)
        print(f"  seed={seed} done: loss={result['final_loss']:.4f}, "
              f"{result['tokens_per_s']:.0f} tok/s, "
              f"{result['wall_clock_s']:.1f}s", flush=True)

    mean_final_loss = sum(r["final_loss"] for r in per_seed) / len(per_seed)
    mean_wall_s = sum(r["wall_clock_s"] for r in per_seed) / len(per_seed)
    mean_tok_s = sum(r["tokens_per_s"] for r in per_seed) / len(per_seed)
    total_tokens = sum(r["tokens_processed"] for r in per_seed)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "PROXY_SPEEDRUN_BASELINE",
        "ts": ts,
        "arm": "baseline",
        "config_sha": CONFIG_SHA,
        "config": _PROXY_CONFIG,
        "governor": governor_block,
        "per_seed": per_seed,
        "aggregate": {
            "n_seeds": len(SEEDS),
            "mean_final_loss": round(mean_final_loss, 6),
            "mean_wall_clock_s": round(mean_wall_s, 2),
            "mean_tokens_per_s": round(mean_tok_s, 1),
            "total_tokens": total_tokens,
        },
        # frozen_target: the mean final loss of the baseline arm at STEPS steps.
        # Future arms are measured by: steps/tokens/wall_clock to reach this loss.
        "frozen_target": {
            "loss": round(mean_final_loss, 6),
            "steps_baseline": STEPS,
            "tokens_per_seed_baseline": STEPS * BATCH * SEQ,
            "wall_clock_s_baseline": round(mean_wall_s, 2),
            "note": ("Baseline mean final loss at STEPS steps. "
                     "measured_multiplier for arm X = "
                     "baseline_wall_clock / arm_wall_clock_to_this_loss."),
        },
        "flags": [
            "plain AdamW + bf16 — no registry techniques",
            "grad checkpointing ON",
            "tied embeddings (embed + lm_head share weights)",
            "shard slice pinned: v0-00000.bin + v0-00001.bin",
            "live run 12c050e7 NOT touched",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/proxy-speedrun-baseline-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"PROXY_SPEEDRUN_BASELINE_DONE {out}")
    return receipt


# ---------------------------------------------------------------------------
# Selftest (CPU-only, no GPU, no shards required)
# ---------------------------------------------------------------------------

def _selftest():
    import hashlib, json

    # 1. Config sha is deterministic
    sha = hashlib.sha256(
        json.dumps(_PROXY_CONFIG, sort_keys=True).encode()
    ).hexdigest()[:16]
    assert sha == CONFIG_SHA, f"config_sha mismatch: {sha} != {CONFIG_SHA}"

    # 2. VRAM and margin constants satisfy fp19 floor (never relax)
    assert VRAM_FRACTION <= 0.80, "VRAM_FRACTION must not exceed fp19 floor 0.80"
    assert MARGIN_GIB >= 1.5, "MARGIN_GIB must not be below fp19 floor 1.5"
    assert PACE_S >= 0.05, "PACE_S must not be below fp19 floor 0.05"

    # 3. Seeds and steps are non-empty
    assert len(SEEDS) == 3 and set(SEEDS) == {16, 17, 18}
    assert STEPS > 0

    # 4. Frozen target formula: measured_multiplier = baseline / arm (>1 is win)
    def measured_multiplier(baseline_wall_s, arm_wall_s):
        return baseline_wall_s / arm_wall_s
    assert measured_multiplier(100.0, 80.0) > 1.0   # faster arm → MM > 1
    assert measured_multiplier(100.0, 120.0) < 1.0  # slower arm → MM < 1
    assert abs(measured_multiplier(100.0, 100.0) - 1.0) < 1e-9

    # 5. Approximate param count is within 50-100M spec
    n_embed = HIDDEN * VOCAB  # tied, not double-counted
    # Per-layer: QKV proj, O proj, gate, up, down, plus layernorms (tiny)
    n_layer = (
        3 * HIDDEN * HIDDEN  # Q, K, V
        + HIDDEN * HIDDEN    # O
        + 2 * HIDDEN * FFN   # gate + up
        + FFN * HIDDEN       # down
        + 2 * HIDDEN         # 2 layernorms (approx)
    )
    n_total = n_embed + LAYERS * n_layer + HIDDEN  # final norm
    assert 50_000_000 <= n_total <= 100_000_000, (
        f"proxy param count {n_total:,} outside 50-100M spec")

    # 6. Shard files list is non-empty and matches pinned spec
    assert len(SHARD_FILES) >= 1
    assert all(f.startswith("v0-") and f.endswith(".bin") for f in SHARD_FILES)

    print("PROXY_SPEEDRUN_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
