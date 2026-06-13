"""fp44_horizon_optimizer_equiv.py — 2000-step horizon optimizer equivalence bench (#376).

Decision: does full_fused_adamw match muon_split_baseline at 2000 training steps?

Arms:
  muon_split_baseline  — Muon(2D excl embed, lr=0.02, ns5) + AdamW(rest, lr=3e-4)
  full_fused_adamw     — all params in AdamW(lr=3e-4, fused=True)  [fp40 throughput winner]

Config (c03 frozen):
  hidden=1024, layers=20, heads=16, seq=1024, batch=16
  ckpt=True, QAT fake_quant (variant=qat), MTP 2 heads weight=0.3
  compile: deferred (eager) — C-4 env wall #373 unresolved

Shard paths (WSL2):
  train: SHARD_DIR/v0-00000.bin
  val:   SHARD_DIR/v0-00001.bin

Protocol:
  1. Noise-floor run: muon_split_baseline seeds {42,43} for 2000 steps each.
     Both seeds start from the same post-warmup model/optimizer snapshot.
     noise_floor = |val_loss_seed42@2000 - val_loss_seed43@2000|
     threshold   = max(0.05, noise_floor)
  2. A/B bench: seed 16, 2000 steps each arm. Val loss at {250,500,1000,1500,2000}.
  3. Decision rule (pre-registered):
     |delta@2000| <= threshold AND full_fused_adamw not diverging -> EQUIV_PASS
       -> AdamW ≡ Muon at horizon -> commit AdamW -> c03 gate-9 -> pretrain
     muon val loss meaningfully lower @2000 -> TRADEOFF
       -> user decision; Muon=19223 tok/s = 1.32 governed days (over ≤1-day bar)

Governor rails (HOLD — never loosened):
  VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05

Via train MCP (WSL2/CUDA). Selftest: python fp44_horizon_optimizer_equiv.py --selftest
Marker: FP44_HORIZON_OPTIMIZER_EQUIV_DONE
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fp19_bench as fp19          # noqa: E402
from receipt_write import checked_write   # noqa: E402
import timeshare_pretrain as ts    # noqa: E402

RECEIPTS = os.path.join(NC, "receipts")

# Shard paths — WSL2 /mnt/b mount
SHARD_DIR   = "/mnt/b/M/avir/eli/state/ember-eng/shards-v0"
TRAIN_SHARD = "v0-00000.bin"
VAL_SHARD   = "v0-00001.bin"

# c03 frozen config
SEQ    = fp19.SEQ       # 1024
VOCAB  = fp19.VOCAB     # 32000
PACE_S = fp19.PACE_S    # 0.05
VRAM_FRACTION = 0.80
MARGIN_GIB    = fp19.MARGIN_GIB  # 1.5

BATCH       = 16
MTP_N_HEADS = 2
MTP_WEIGHT  = 0.3
LR_MUON     = 0.02
LR_ADAMW    = 3e-4
WEIGHT_DECAY = 0.1

WARMUP_STEPS   = 8       # compile warmup (even though compile deferred, keeps arms symmetric)
TRAIN_STEPS    = 2000
VAL_CHECKPOINTS = [250, 500, 1000, 1500, 2000]
VAL_BATCH       = 8     # smaller batch for val to save memory
VAL_STEPS       = 16    # steps averaged for each val measurement

NOISE_FLOOR_THRESHOLD_FLOOR = 0.05  # nats — absolute floor on derived threshold

ARMS = ["muon_split_baseline", "full_fused_adamw"]
NOISE_SEEDS = [42, 43]
BENCH_SEED  = 16


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Shard-backed tokenized dataset (uint16 binary, numpy memmap)
# ---------------------------------------------------------------------------

class ShardTokens:
    """Sequential uint16 token reader from a binary shard file."""
    def __init__(self, shard_path: str, seq: int):
        import numpy as np
        if not os.path.exists(shard_path):
            raise FileNotFoundError(f"shard not found: {shard_path}")
        self._tokens = np.memmap(shard_path, dtype=np.uint16, mode="r").astype(np.int64)
        self._seq = seq
        self._pos = 0

    def next_batch(self, batch: int):
        import torch
        import numpy as np
        xs, ys = [], []
        for _ in range(batch):
            if self._pos + self._seq + 1 > len(self._tokens):
                self._pos = 0  # wrap
            chunk = self._tokens[self._pos: self._pos + self._seq + 1]
            xs.append(chunk[:-1])
            ys.append(chunk[1:])
            self._pos += self._seq
        return (
            torch.tensor(np.stack(xs), dtype=torch.long, device="cuda"),
            torch.tensor(np.stack(ys), dtype=torch.long, device="cuda"),
        )

    def reset(self):
        self._pos = 0


# ---------------------------------------------------------------------------
# Model + optimizer builders
# ---------------------------------------------------------------------------

def _build_model(grad_ckpt: bool):
    import torch
    from transformers import LlamaConfig, LlamaModel

    conf = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=1024,
        intermediate_size=4096,
        num_hidden_layers=20,
        num_attention_heads=16,
        num_key_value_heads=16,
        max_position_embeddings=SEQ,
        use_cache=False,
    )
    backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
    if grad_ckpt:
        backbone.gradient_checkpointing_enable()

    head = torch.nn.Linear(1024, VOCAB, bias=False).cuda().to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight

    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(1024, VOCAB, bias=False).cuda().to(torch.bfloat16)
        for _ in range(MTP_N_HEADS)
    ])

    return backbone, head, mtp_heads


def _build_opts(backbone, head, mtp_heads, arm: str):
    import torch
    all_params = dict(backbone.named_parameters())
    for i, h in enumerate(mtp_heads):
        for n, p in h.named_parameters():
            all_params[f"mtp_heads.{i}.{n}"] = p

    if arm == "full_fused_adamw":
        all_p = list(all_params.values())
        return {"adamw": torch.optim.AdamW(all_p, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY,
                                           fused=True)}

    # muon_split_baseline
    muon_p, adamw_p = [], []
    for name, p in all_params.items():
        if p.ndim == 2 and "embed_tokens" not in name:
            muon_p.append(p)
        else:
            adamw_p.append(p)

    Muon = ts._muon_class()
    opts = {}
    if muon_p:
        opts["muon"] = Muon(muon_p, lr=LR_MUON, weight_decay=WEIGHT_DECAY, ns_steps=5)
    opts["adamw"] = torch.optim.AdamW(adamw_p, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY)
    return opts


# ---------------------------------------------------------------------------
# Step and val-loss functions
# ---------------------------------------------------------------------------

def _step(backbone, head, mtp_heads, opts, ids, tgts_primary, tgts_mtp, variant="qat"):
    """One train step. Returns loss value (float)."""
    saved = fp19._apply_fake_quant(backbone, variant)
    hidden = backbone(input_ids=ids).last_hidden_state
    h_flat = hidden.reshape(-1, hidden.shape[-1])
    primary_ce, _ = ts.chunked_cross_entropy(
        h_flat, head.weight, tgts_primary.reshape(-1), chunk_tokens=1024)
    mtp_ces = [
        ts.chunked_cross_entropy(h_flat, mh.weight, tgts_mtp[k].reshape(-1),
                                 chunk_tokens=1024)[0]
        for k, mh in enumerate(mtp_heads)
    ]
    loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
    fp19._restore(saved)
    loss.backward()
    for opt in opts.values():
        opt.step()
    for opt in opts.values():
        opt.zero_grad(set_to_none=True)
    return loss.item()


def _val_loss(backbone, head, mtp_heads, val_ds, variant="qat"):
    """Compute val loss over VAL_STEPS batches. Returns mean loss (nats)."""
    import torch
    backbone.eval()
    val_ds.reset()
    losses = []
    with torch.no_grad():
        for _ in range(VAL_STEPS):
            ids, tgts = val_ds.next_batch(VAL_BATCH)
            tgts_primary = tgts
            tgts_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, variant)
            hidden = backbone(input_ids=ids).last_hidden_state
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ts.chunked_cross_entropy(
                h_flat, head.weight, tgts_primary.reshape(-1), chunk_tokens=1024)
            mtp_ces = [
                ts.chunked_cross_entropy(h_flat, mh.weight, tgts_mtp[k].reshape(-1),
                                         chunk_tokens=1024)[0]
                for k, mh in enumerate(mtp_heads)
            ]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            losses.append(loss.item())
    backbone.train()
    return round(sum(losses) / len(losses), 6)


def _run_arm(arm: str, seed: int, train_ds: "ShardTokens", val_ds: "ShardTokens",
             label: str = "") -> dict:
    """Train arm for TRAIN_STEPS steps, measuring val loss at VAL_CHECKPOINTS.

    Returns result dict.
    """
    import torch
    import copy

    tag = label or f"{arm}-seed{seed}"
    out: dict = {"arm": arm, "seed": seed, "train_steps": TRAIN_STEPS,
                 "val_checkpoints": VAL_CHECKPOINTS}

    try:
        torch.manual_seed(seed)
        backbone, head, mtp_heads = _build_model(grad_ckpt=True)
        opts = _build_opts(backbone, head, mtp_heads, arm)
        backbone.train(); head.train(); mtp_heads.train()
        train_ds.reset()

        # Warmup (symmetric across arms)
        print(f"[fp44] {tag}: warmup {WARMUP_STEPS} steps ...", flush=True)
        for i in range(WARMUP_STEPS):
            ids, tgts = train_ds.next_batch(BATCH)
            tgts_primary = tgts
            tgts_mtp_list = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            _step(backbone, head, mtp_heads, opts, ids, tgts_primary, tgts_mtp_list)
            time.sleep(PACE_S)
            print(f"[fp44]   warmup {i+1}/{WARMUP_STEPS}", flush=True)

        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del backbone, head, mtp_heads, opts
            torch.cuda.empty_cache()
            return out

        # Training with val checkpoints
        val_losses: dict[int, float] = {}
        print(f"[fp44] {tag}: training {TRAIN_STEPS} steps ...", flush=True)
        t0 = time.perf_counter()

        for step in range(1, TRAIN_STEPS + 1):
            ids, tgts = train_ds.next_batch(BATCH)
            tgts_primary = tgts
            tgts_mtp_list = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            _step(backbone, head, mtp_heads, opts, ids, tgts_primary, tgts_mtp_list)
            time.sleep(PACE_S)

            if step in VAL_CHECKPOINTS:
                vl = _val_loss(backbone, head, mtp_heads, val_ds)
                val_losses[step] = vl
                elapsed = time.perf_counter() - t0
                print(f"[fp44]   step {step}/{TRAIN_STEPS} val_loss={vl:.4f} "
                      f"elapsed={elapsed:.0f}s", flush=True)

        total_time = time.perf_counter() - t0
        out.update(
            status="OK",
            val_losses=val_losses,
            total_time_s=round(total_time, 1),
        )

        del backbone, head, mtp_heads, opts
        torch.cuda.empty_cache()
        return out

    except Exception as e:
        import traceback
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:400]
        print(traceback.format_exc(), flush=True)
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        return out


def _noise_floor_run() -> dict:
    """Run muon_split_baseline with seeds {42,43} for TRAIN_STEPS steps each.

    Both seeds start from THE SAME post-warmup snapshot (same model + opt state).
    noise_floor = |val@2000[seed42] - val@2000[seed43]|
    derived_threshold = max(NOISE_FLOOR_THRESHOLD_FLOOR, noise_floor)
    Returns full result dict.
    """
    import torch
    import copy

    train_ds = ShardTokens(os.path.join(SHARD_DIR, TRAIN_SHARD), SEQ)
    val_ds   = ShardTokens(os.path.join(SHARD_DIR, VAL_SHARD),   SEQ)

    # Build and warm up the shared snapshot
    torch.manual_seed(NOISE_SEEDS[0])
    backbone, head, mtp_heads = _build_model(grad_ckpt=True)
    opts = _build_opts(backbone, head, mtp_heads, "muon_split_baseline")
    backbone.train(); head.train(); mtp_heads.train()
    train_ds.reset()

    print(f"[fp44] noise-floor: warmup {WARMUP_STEPS} steps ...", flush=True)
    for i in range(WARMUP_STEPS):
        ids, tgts = train_ds.next_batch(BATCH)
        tgts_primary = tgts
        tgts_mtp_list = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
        _step(backbone, head, mtp_heads, opts, ids, tgts_primary, tgts_mtp_list)
        time.sleep(PACE_S)

    # Snapshot post-warmup state
    model_snap = {k: v.detach().clone() for k, v in backbone.state_dict().items()}
    head_snap  = {k: v.detach().clone() for k, v in head.state_dict().items()}
    mtp_snap   = {k: v.detach().clone() for k, v in mtp_heads.state_dict().items()}
    opt_snaps  = {k: copy.deepcopy(opt.state_dict()) for k, opt in opts.items()}

    seed_results = {}
    for seed in NOISE_SEEDS:
        print(f"\n[fp44] noise-floor seed {seed}: training {TRAIN_STEPS} steps ...", flush=True)
        backbone.load_state_dict(model_snap)
        head.load_state_dict(head_snap)
        mtp_heads.load_state_dict(mtp_snap)
        for k, opt in opts.items():
            opt.load_state_dict(opt_snaps[k])

        # Reset train shard to same position for both seeds (same data, different torch seed)
        train_ds.reset()
        torch.manual_seed(seed)

        val_losses: dict[int, float] = {}
        t0 = time.perf_counter()
        for step in range(1, TRAIN_STEPS + 1):
            ids, tgts = train_ds.next_batch(BATCH)
            tgts_primary = tgts
            tgts_mtp_list = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            _step(backbone, head, mtp_heads, opts, ids, tgts_primary, tgts_mtp_list)
            time.sleep(PACE_S)

            if step in VAL_CHECKPOINTS:
                vl = _val_loss(backbone, head, mtp_heads, val_ds)
                val_losses[step] = vl
                elapsed = time.perf_counter() - t0
                print(f"[fp44]   seed {seed} step {step}/{TRAIN_STEPS} "
                      f"val_loss={vl:.4f} elapsed={elapsed:.0f}s", flush=True)

        seed_results[seed] = {
            "val_losses": val_losses,
            "total_time_s": round(time.perf_counter() - t0, 1),
        }

    del backbone, head, mtp_heads, opts
    torch.cuda.empty_cache()

    v42 = seed_results[42]["val_losses"].get(TRAIN_STEPS)
    v43 = seed_results[43]["val_losses"].get(TRAIN_STEPS)
    noise_floor = round(abs(v42 - v43), 6) if (v42 is not None and v43 is not None) else 0.05
    derived_threshold = round(max(NOISE_FLOOR_THRESHOLD_FLOOR, noise_floor), 6)

    return {
        "seed_results":       seed_results,
        "noise_floor":        noise_floor,
        "derived_threshold":  derived_threshold,
        "threshold_floor":    NOISE_FLOOR_THRESHOLD_FLOOR,
    }


def _apply_decision_rule(muon_result: dict, adamw_result: dict,
                         derived_threshold: float) -> dict:
    """Apply the pre-registered decision rule.

    EQUIV_PASS:   |delta@2000| <= derived_threshold AND adamw not diverging
    TRADEOFF:     muon val loss meaningfully lower at step 2000
    ADAMW_BETTER: adamw val loss lower at step 2000 (unexpected; report as-is)
    INSUFFICIENT: missing val@2000 values (run error)
    """
    muon_v = muon_result.get("val_losses", {}).get(TRAIN_STEPS)
    adamw_v = adamw_result.get("val_losses", {}).get(TRAIN_STEPS)

    if muon_v is None or adamw_v is None:
        return {
            "verdict": "INSUFFICIENT",
            "reason": "missing val@2000",
            "muon_val_2000": muon_v,
            "adamw_val_2000": adamw_v,
        }

    delta = round(adamw_v - muon_v, 6)  # positive = adamw is worse (higher loss)

    # Divergence check: adamw val loss increasing monotonically across last 3 checkpoints
    adamw_vals = adamw_result.get("val_losses", {})
    last3 = [adamw_vals.get(c) for c in [1000, 1500, 2000] if adamw_vals.get(c) is not None]
    adamw_diverging = (len(last3) == 3 and last3[0] < last3[1] < last3[2])

    if abs(delta) <= derived_threshold and not adamw_diverging:
        verdict = "EQUIV_PASS"
        consequence = ("AdamW ≡ Muon at 2000-step horizon. "
                       "Commit AdamW (full_fused_adamw). c03 to gate-9. Pretrain GO.")
    elif delta > derived_threshold and not adamw_diverging:
        verdict = "TRADEOFF"
        consequence = (
            f"Muon val lower by {delta:.4f} nats at step 2000 (above threshold={derived_threshold:.4f}). "
            "User decision: Muon=19223 tok/s = 1.32 governed days (over ≤1-day bar). "
            "Do NOT pick AdamW to dodge it.")
    elif adamw_diverging:
        verdict = "ADAMW_DIVERGING"
        consequence = "AdamW val loss increasing monotonically in last 3 checkpoints — reject."
    else:
        verdict = "ADAMW_BETTER"
        consequence = f"AdamW val lower by {abs(delta):.4f} nats — unexpected win; report as-is."

    return {
        "verdict":           verdict,
        "delta_adamw_minus_muon": delta,
        "muon_val_2000":     muon_v,
        "adamw_val_2000":    adamw_v,
        "derived_threshold": derived_threshold,
        "adamw_diverging":   adamw_diverging,
        "consequence":       consequence,
    }


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def selftest():
    """CPU-only selftest. No GPU required.

    Tests: ShardTokens shape/wrap, noise-floor threshold logic, decision rule.
    Marker: FP44_SELFTEST_PASS
    """
    import tempfile
    import numpy as np

    failures = []

    # 1. ShardTokens: create fixture, check shape and wrap
    with tempfile.TemporaryDirectory() as td:
        shard_path = os.path.join(td, "test.bin")
        n_tokens = 200
        arr = np.arange(n_tokens, dtype=np.uint16)
        arr.tofile(shard_path)

        class _FakeShardTokens(ShardTokens):
            """Override to skip CUDA device placement."""
            def next_batch(self, batch: int):
                import numpy as np
                xs, ys = [], []
                for _ in range(batch):
                    if self._pos + self._seq + 1 > len(self._tokens):
                        self._pos = 0
                    chunk = self._tokens[self._pos: self._pos + self._seq + 1]
                    xs.append(chunk[:-1])
                    ys.append(chunk[1:])
                    self._pos += self._seq
                import torch
                return (
                    torch.tensor(np.stack(xs), dtype=torch.long),
                    torch.tensor(np.stack(ys), dtype=torch.long),
                )

        ds = _FakeShardTokens(shard_path, seq=10)
        x, y = ds.next_batch(2)
        if x.shape != (2, 10):
            failures.append(f"1a. wrong shape: {x.shape}")
        if not (y == x + 1).all():
            failures.append("1b. y != x+1 (sequential tokens broken)")

        # Wrap: exhaust and ensure no crash
        for _ in range(30):
            ds.next_batch(1)

    # 2. Noise-floor threshold logic
    for (v42, v43, expected_floor, expected_thresh) in [
        (10.0, 10.1, 0.05, 0.1),    # noise_floor=0.1 > floor
        (10.0, 10.02, 0.05, 0.05),  # noise_floor=0.02 < floor -> use floor
        (10.0, 10.05, 0.05, 0.05),  # noise_floor=0.05 == floor
    ]:
        nf = round(abs(v42 - v43), 6)
        dt = round(max(NOISE_FLOOR_THRESHOLD_FLOOR, nf), 6)
        if abs(dt - expected_thresh) > 1e-9:
            failures.append(f"2. threshold {dt} != {expected_thresh} for v42={v42} v43={v43}")

    # 3. Decision rule
    def _dr(muon_v, adamw_v, threshold, last3=None):
        muon_r = {"val_losses": {TRAIN_STEPS: muon_v}}
        adamw_r = {"val_losses": {TRAIN_STEPS: adamw_v}}
        if last3:
            adamw_r["val_losses"].update({1000: last3[0], 1500: last3[1], 2000: last3[2]})
        return _apply_decision_rule(muon_r, adamw_r, threshold)

    # EQUIV_PASS: |delta| <= threshold
    r = _dr(10.0, 10.03, threshold=0.05)
    if r["verdict"] != "EQUIV_PASS":
        failures.append(f"3a. expected EQUIV_PASS got {r['verdict']}")

    # TRADEOFF: adamw worse by more than threshold
    r = _dr(10.0, 10.1, threshold=0.05)
    if r["verdict"] != "TRADEOFF":
        failures.append(f"3b. expected TRADEOFF got {r['verdict']}")

    # ADAMW_BETTER
    r = _dr(10.1, 10.0, threshold=0.05)
    if r["verdict"] != "ADAMW_BETTER":
        failures.append(f"3c. expected ADAMW_BETTER got {r['verdict']}")

    # ADAMW_DIVERGING
    r = _dr(10.0, 10.03, threshold=0.05, last3=[9.9, 10.0, 10.1])
    if r["verdict"] != "ADAMW_DIVERGING":
        failures.append(f"3d. expected ADAMW_DIVERGING got {r['verdict']}")

    # INSUFFICIENT
    r = _apply_decision_rule({"val_losses": {}}, {"val_losses": {TRAIN_STEPS: 10.0}}, 0.05)
    if r["verdict"] != "INSUFFICIENT":
        failures.append(f"3e. expected INSUFFICIENT got {r['verdict']}")

    # 4. Shard path constants defined
    if not SHARD_DIR or not TRAIN_SHARD or not VAL_SHARD:
        failures.append("4. shard path constants missing")

    if failures:
        for f in failures:
            print(f"[fp44_selftest] FAIL: {f}")
        print("FP44_SELFTEST_FAIL")
        sys.exit(1)
    else:
        print("FP44_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[fp44] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp44] torch:  {torch.__version__}", flush=True)
    print(f"[fp44] fp-44 horizon optimizer equivalence bench", flush=True)
    print(f"[fp44] train_steps={TRAIN_STEPS} val_checkpoints={VAL_CHECKPOINTS}", flush=True)
    print(f"[fp44] shard_dir={SHARD_DIR}", flush=True)

    # Verify shards exist before allocating anything
    for fname in [TRAIN_SHARD, VAL_SHARD]:
        p = os.path.join(SHARD_DIR, fname)
        if not os.path.exists(p):
            print(f"[fp44] FATAL: shard not found: {p}", flush=True)
            sys.exit(1)
    print("[fp44] shards verified", flush=True)

    # Phase 1: noise-floor run
    print(f"\n[fp44] Phase 1: noise-floor (muon_split seeds {NOISE_SEEDS}) ...", flush=True)
    nf_result = _noise_floor_run()
    print(f"[fp44] noise_floor={nf_result['noise_floor']} "
          f"derived_threshold={nf_result['derived_threshold']}", flush=True)

    # Phase 2: A/B bench — muon_split_baseline
    train_ds = ShardTokens(os.path.join(SHARD_DIR, TRAIN_SHARD), SEQ)
    val_ds   = ShardTokens(os.path.join(SHARD_DIR, VAL_SHARD),   SEQ)

    print(f"\n[fp44] Phase 2a: muon_split_baseline seed {BENCH_SEED} ...", flush=True)
    muon_result = _run_arm("muon_split_baseline", BENCH_SEED, train_ds, val_ds,
                           label=f"muon_split_baseline-seed{BENCH_SEED}")

    # Phase 2: A/B bench — full_fused_adamw
    print(f"\n[fp44] Phase 2b: full_fused_adamw seed {BENCH_SEED} ...", flush=True)
    adamw_result = _run_arm("full_fused_adamw", BENCH_SEED, train_ds, val_ds,
                            label=f"full_fused_adamw-seed{BENCH_SEED}")

    # Decision
    decision = _apply_decision_rule(muon_result, adamw_result, nf_result["derived_threshold"])
    print(f"\n[fp44] DECISION: {decision['verdict']}", flush=True)
    print(f"[fp44]   muon_val@2000={decision.get('muon_val_2000')} "
          f"adamw_val@2000={decision.get('adamw_val_2000')} "
          f"delta={decision.get('delta_adamw_minus_muon')}", flush=True)
    print(f"[fp44]   {decision.get('consequence', '')}", flush=True)

    ts_now = _ts()
    receipt = {
        "ticket":         "FP44-HORIZON-OPTIMIZER-EQUIV",
        "ts":             ts_now,
        "issue":          "#376",
        "decision_rule":  (
            "Pre-registered: |delta_adamw_minus_muon@2000| <= derived_threshold "
            "AND adamw not diverging -> EQUIV_PASS -> commit AdamW -> gate-9 -> pretrain. "
            "muon val lower @2000 -> TRADEOFF -> user decision."
        ),
        "config": {
            "hidden": 1024, "layers": 20, "heads": 16, "seq": SEQ, "batch": BATCH,
            "grad_checkpointing": True, "variant": "qat",
            "mtp_n_heads": MTP_N_HEADS, "mtp_weight": MTP_WEIGHT,
            "lr_muon": LR_MUON, "lr_adamw": LR_ADAMW,
            "weight_decay": WEIGHT_DECAY, "train_steps": TRAIN_STEPS,
            "val_checkpoints": VAL_CHECKPOINTS, "val_batch": VAL_BATCH,
            "val_steps": VAL_STEPS, "warmup_steps": WARMUP_STEPS,
            "noise_seeds": NOISE_SEEDS, "bench_seed": BENCH_SEED,
            "compile": "DEFERRED (eager) — C-4 env wall #373",
            "train_shard": TRAIN_SHARD, "val_shard": VAL_SHARD,
        },
        "noise_floor_run":    nf_result,
        "muon_result":        muon_result,
        "adamw_result":       adamw_result,
        "decision":           decision,
        "runtime": {
            "device": torch.cuda.get_device_name(0),
            "torch":  torch.__version__,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "flags": [
            "c03 frozen config (h=1024 d=20 heads=16)",
            "B=16, ckpt=True, QAT, MTP 2h w=0.3",
            "compile: DEFERRED (eager) — C-4 env wall #373 unresolved",
            "noise-floor: same post-warmup snapshot for seeds 42+43",
            "A/B bench: seed 16, 2000 steps each arm",
            "val loss measured at {250,500,1000,1500,2000} steps",
            f"threshold = max({NOISE_FLOOR_THRESHOLD_FLOOR}, noise_floor@2000)",
            "governor rails HOLD — never loosened",
            "prior fp40: full_fused_adamw 27703 tok/s / 3.16% opt wall (EQUIV at 100 steps)",
            "fp40 100-step horizon insufficient (synthetic data, loss floors to 0) -> fp-44",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out_path = os.path.join(RECEIPTS, f"fp44-horizon-optimizer-equiv-{ts_now}.json")
    checked_write(out_path, receipt)
    print(f"\n[fp44] receipt: {out_path}", flush=True)
    print(f"FP44_HORIZON_OPTIMIZER_EQUIV_DONE verdict={decision['verdict']} "
          f"delta={decision.get('delta_adamw_minus_muon')}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
    else:
        main()
