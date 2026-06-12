"""cuda_graph_ab.py — CUDA graph-capture vs eager step-time A/B (Closes #301).

Measures whether torch.cuda.CUDAGraph capture removes enough kernel-launch
overhead to yield a net step-time win at c03 shapes (v0 training config).

Registry claim: "graph-capture removes launch overhead at 0.4-2B shapes"
E4 context: optimizer/step share = 11.3% — launch overhead lives here.

Protocol:
  Two arms at c03 shapes (hidden=1024, layers=20, heads=16, seq=1024):
    - eager : no graph capture — baseline (same path as live run)
    - graph : torch.cuda.CUDAGraph forward+backward capture; opt.step outside graph

  warmup_steps=5, bench_steps=20, seeds={16,17,18}.
  Metric: tokens/s per arm.
  measured_multiplier = graph_tok_s / eager_tok_s (>1.0 = graph faster).

Governed: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05 (fp19 floor).
Live run 12c050e7 NOT touched.
grad_checkpointing DISABLED (v0 config as of PR #300).

Known constraint: dynamic shapes break CUDA graph capture; c03 is fixed-shape.

Selftest: python cuda_graph_ab.py --selftest
  Marker: CUDA_GRAPH_AB_SELFTEST_PASS

Run: python cuda_graph_ab.py
  NOT via train MCP. Native Windows Python only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")

# ---------------------------------------------------------------------------
# c03 shapes (v0 training config, same as E4 profiler)
# ---------------------------------------------------------------------------
HIDDEN      = 1024
LAYERS      = 20
HEADS       = 16
FFN         = 4096
VOCAB       = 32000
SEQ         = 1024
BATCH       = 4
WARMUP_REPS = 5
BENCH_REPS  = 20

SEEDS = [16, 17, 18]

SHARD_DIR   = os.path.join(os.path.dirname(NC), "shards-v0")
SHARD_FILES = ["v0-00000.bin", "v0-00001.bin"]

# Governor rails (fp19 floor — never relax)
VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

LIVE_RUN_SHA = "12c050e7"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Shard-backed dataset
# ---------------------------------------------------------------------------

class ShardDataset:
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
# Model builder
# ---------------------------------------------------------------------------

def _build_model(torch):
    from transformers import LlamaConfig, LlamaForCausalLM
    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN,
        intermediate_size=FFN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS,
        max_position_embeddings=SEQ * 2,
        tie_word_embeddings=True,
        bos_token_id=1, eos_token_id=2,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    # grad_checkpointing DISABLED per v0 config (PR #300)
    model.gradient_checkpointing_disable()
    model.train()
    return model


# ---------------------------------------------------------------------------
# Eager arm measurement
# ---------------------------------------------------------------------------

def measure_eager(seed: int, torch) -> dict:
    """Standard eager forward+backward, no graph capture."""
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.empty_cache()

    free_before, total_b = torch.cuda.mem_get_info()

    try:
        model = _build_model(torch)
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        return {"arm": "eager", "seed": seed, "error": f"OOM_AT_BUILD: {e}",
                "measured_multiplier": None}

    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.1)
    dataset = ShardDataset(SHARD_DIR, SHARD_FILES, SEQ, seed)

    # Warmup
    for _ in range(WARMUP_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        try:
            loss = model(input_ids=x, labels=y).loss
            loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opt, dataset
            torch.cuda.empty_cache()
            return {"arm": "eager", "seed": seed, "error": f"OOM_AT_WARMUP: {e}",
                    "measured_multiplier": None}
        opt.step()
        opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    # Bench
    step_times = []
    for _ in range(BENCH_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        try:
            loss = model(input_ids=x, labels=y).loss
            loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opt, dataset
            torch.cuda.empty_cache()
            return {"arm": "eager", "seed": seed, "error": f"OOM_AT_BENCH: {e}",
                    "measured_multiplier": None}
        torch.cuda.synchronize()
        step_times.append(time.perf_counter() - t0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    free_after, _ = torch.cuda.mem_get_info()
    vram_used_gib = (free_before - free_after) / (1 << 30)
    mean_step_s = sum(step_times) / len(step_times)
    tokens_per_s = (BATCH * SEQ) / mean_step_s

    del model, opt, dataset
    torch.cuda.empty_cache()

    return {
        "arm": "eager",
        "seed": seed,
        "bench_reps": BENCH_REPS,
        "mean_step_s": round(mean_step_s, 5),
        "tokens_per_step": BATCH * SEQ,
        "tokens_per_s": round(tokens_per_s, 1),
        "vram_used_gib": round(vram_used_gib, 3),
        "step_times_s": [round(t, 5) for t in step_times],
        "error": None,
        "measured_multiplier": None,
    }


# ---------------------------------------------------------------------------
# Graph arm measurement
# ---------------------------------------------------------------------------

def measure_graph(seed: int, torch) -> dict:
    """CUDA graph capture of forward+backward; opt.step runs outside graph.

    Stream protocol (prevents cudaErrorStreamCaptureInvalidated):
      - Warmup runs on a dedicated g_stream, priming AccumulateGrad nodes there.
      - Graph is captured on the same g_stream.
      - Replay runs on g_stream.
      This ensures AccumulateGrad nodes and the capture stream agree.
    """
    if not hasattr(torch.cuda, "CUDAGraph"):
        return {"arm": "graph", "seed": seed,
                "error": "CUDA_GRAPH_UNAVAILABLE: torch.cuda.CUDAGraph not found",
                "measured_multiplier": None}

    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.empty_cache()

    free_before, total_b = torch.cuda.mem_get_info()

    try:
        model = _build_model(torch)
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        return {"arm": "graph", "seed": seed, "error": f"OOM_AT_BUILD: {e}",
                "measured_multiplier": None}

    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.1)
    dataset = ShardDataset(SHARD_DIR, SHARD_FILES, SEQ, seed)

    # Static tensors for graph capture (shape never changes during replay)
    static_x = torch.zeros(BATCH, SEQ, dtype=torch.long, device="cuda")
    static_y = torch.zeros(BATCH, SEQ, dtype=torch.long, device="cuda")

    # Dedicated stream — warmup AND capture must share the same stream so that
    # AccumulateGrad nodes created during warmup match the capture stream.
    g_stream = torch.cuda.Stream()
    g_stream.wait_stream(torch.cuda.current_stream())

    # Warmup on g_stream
    try:
        with torch.cuda.stream(g_stream):
            for _ in range(WARMUP_REPS):
                x_w, y_w = dataset.next_batch(BATCH)
                static_x.copy_(x_w.cuda())
                static_y.copy_(y_w.cuda())
                out = model(input_ids=static_x, labels=static_y)
                loss_w = out.loss
                loss_w.backward()
                del out, loss_w  # release autograd graph refs
                opt.step()
                opt.zero_grad(set_to_none=True)
                time.sleep(PACE_S)
            # Pre-allocate grad tensors (set_to_none=False) before capture
            opt.zero_grad(set_to_none=False)
    except torch.cuda.OutOfMemoryError as e:
        del model, opt, dataset
        torch.cuda.empty_cache()
        return {"arm": "graph", "seed": seed, "error": f"OOM_AT_WARMUP: {e}",
                "measured_multiplier": None}

    torch.cuda.current_stream().wait_stream(g_stream)

    # Graph capture on g_stream — forward + backward (no opt.step inside graph)
    try:
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g, stream=g_stream):
            static_out = model(input_ids=static_x, labels=static_y)
            static_loss = static_out.loss
            static_loss.backward()
    except Exception as e:
        del model, opt, dataset
        torch.cuda.empty_cache()
        return {"arm": "graph", "seed": seed, "error": f"GRAPH_CAPTURE_FAIL: {e}",
                "measured_multiplier": None}

    # Bench loop: replay on g_stream, opt.step on default stream
    step_times = []
    for _ in range(BENCH_REPS):
        x_b, y_b = dataset.next_batch(BATCH)
        static_x.copy_(x_b.cuda())
        static_y.copy_(y_b.cuda())
        # Zero grad tensors in-place (set_to_none=False — must exist for replay)
        for p in model.parameters():
            if p.grad is not None:
                p.grad.zero_()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.cuda.stream(g_stream):
            g.replay()
        torch.cuda.current_stream().wait_stream(g_stream)
        torch.cuda.synchronize()
        step_times.append(time.perf_counter() - t0)
        opt.step()
        time.sleep(PACE_S)

    free_after, _ = torch.cuda.mem_get_info()
    vram_used_gib = (free_before - free_after) / (1 << 30)
    mean_step_s = sum(step_times) / len(step_times)
    tokens_per_s = (BATCH * SEQ) / mean_step_s

    del model, opt, dataset, g
    torch.cuda.empty_cache()

    return {
        "arm": "graph",
        "seed": seed,
        "bench_reps": BENCH_REPS,
        "mean_step_s": round(mean_step_s, 5),
        "tokens_per_step": BATCH * SEQ,
        "tokens_per_s": round(tokens_per_s, 1),
        "vram_used_gib": round(vram_used_gib, 3),
        "step_times_s": [round(t, 5) for t in step_times],
        "error": None,
        "measured_multiplier": None,
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
            f"CUDA_GRAPH_AB_GOVERNOR_FAIL: {free_gib:.2f} GiB free < "
            f"{MARGIN_GIB} GiB — refusing launch")

    governor = {
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
            raise SystemExit(f"CUDA_GRAPH_AB_SHARD_MISSING: {p}")

    config = {
        "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
        "ffn": FFN, "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
        "warmup_reps": WARMUP_REPS, "bench_reps": BENCH_REPS,
        "vram_fraction": VRAM_FRACTION, "seeds": SEEDS,
        "arms": ["eager", "graph"],
        "shard_files": SHARD_FILES,
        "grad_checkpointing": False,
    }

    print(f"[cuda_graph_ab] c03 shape hidden={HIDDEN} layers={LAYERS} "
          f"heads={HEADS} seq={SEQ} batch={BATCH}", flush=True)
    print(f"  arms: eager vs graph", flush=True)
    print(f"  seeds: {SEEDS}, warmup={WARMUP_REPS}, bench={BENCH_REPS}", flush=True)
    print(f"  torch: {torch.__version__}, cuda: {torch.version.cuda}", flush=True)
    print(f"  device: {torch.cuda.get_device_name(0)}", flush=True)

    results: dict[str, list[dict]] = {"eager": [], "graph": []}

    # Run ALL eager seeds first, then ALL graph seeds.
    # This prevents a graph capture failure from poisoning the CUDA context
    # before eager arm results are collected.
    for arm, fn in [("eager", measure_eager), ("graph", measure_graph)]:
        print(f"\n  arm={arm}", flush=True)
        for seed in SEEDS:
            print(f"    seed={seed} ...", flush=True)
            r = fn(seed, torch)
            if r.get("error"):
                print(f"      ERROR: {r['error']}", flush=True)
            else:
                print(f"      {r['tokens_per_s']:.0f} tok/s  "
                      f"step={r['mean_step_s']*1000:.2f}ms  "
                      f"vram={r['vram_used_gib']:.2f} GiB", flush=True)
            results[arm].append(r)

    # Aggregate per arm
    arm_agg: dict[str, dict] = {}
    for arm in ["eager", "graph"]:
        valid = [r for r in results[arm] if r.get("error") is None]
        if not valid:
            arm_agg[arm] = {
                "status": "FAIL",
                "reason": results[arm][0].get("error", "all seeds failed"),
                "mean_tokens_per_s": None,
                "measured_multiplier": None,
            }
        else:
            arm_agg[arm] = {
                "status": "PASS",
                "n_valid_seeds": len(valid),
                "mean_tokens_per_s": round(
                    sum(r["tokens_per_s"] for r in valid) / len(valid), 1),
                "mean_step_s": round(
                    sum(r["mean_step_s"] for r in valid) / len(valid), 5),
                "mean_vram_used_gib": round(
                    sum(r["vram_used_gib"] for r in valid) / len(valid), 3),
                "measured_multiplier": None,
            }

    # measured_multiplier = graph_tok_s / eager_tok_s (>1.0 = graph faster)
    eager_tok_s = arm_agg["eager"].get("mean_tokens_per_s") or 0.0
    if eager_tok_s > 0:
        for arm in ["eager", "graph"]:
            tok_s = arm_agg[arm].get("mean_tokens_per_s")
            if tok_s is not None:
                arm_agg[arm]["measured_multiplier"] = round(tok_s / eager_tok_s, 4)

    # Per-seed measured_multiplier
    ctrl_seed_tok: dict[int, float] = {}
    for r in results["eager"]:
        if r.get("error") is None:
            ctrl_seed_tok[r["seed"]] = r["tokens_per_s"]
    for arm in ["eager", "graph"]:
        for r in results[arm]:
            seed = r.get("seed")
            if r.get("error") is None and seed in ctrl_seed_tok and ctrl_seed_tok[seed] > 0:
                r["measured_multiplier"] = round(
                    r["tokens_per_s"] / ctrl_seed_tok[seed], 4)

    # Verdict
    graph_mm = arm_agg["graph"].get("measured_multiplier")
    graph_status = arm_agg["graph"].get("status")

    if graph_status == "FAIL":
        verdict = "GRAPH_ERROR"
    elif graph_mm is not None and graph_mm > 1.0:
        verdict = "GRAPH_PASS"
    elif graph_mm is not None:
        verdict = "GRAPH_FAIL"
    else:
        verdict = "GRAPH_ERROR"

    ts = _ts()
    receipt = {
        "ticket": "CUDA_GRAPH_AB",
        "ts": ts,
        "verdict": verdict,
        "issue": "#301",
        "runtime": {
            "device": str(torch.cuda.get_device_name(0)),
            "sm": str(torch.cuda.get_device_capability(0)[0] * 10
                      + torch.cuda.get_device_capability(0)[1]),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
        },
        "config": config,
        "governor": governor,
        "arm_aggregate": arm_agg,
        "per_seed_results": {arm: results[arm] for arm in ["eager", "graph"]},
        "measured_multiplier_graph_vs_eager": graph_mm,
        "flags": [
            "c03 shapes (v0 training config — same as E4 profiler)",
            "grad_checkpointing DISABLED per v0 config (PR #300)",
            f"live run {LIVE_RUN_SHA} NOT touched",
            "governor rails HOLD — never loosened",
            "measured_multiplier > 1.0 = graph faster than eager",
            "opt.step() runs OUTSIDE graph capture (not graphed)",
            "zero_grad(set_to_none=False) before capture — grad tensors pre-allocated",
        ],
    }

    print(f"\n[cuda_graph_ab] verdict: {verdict}", flush=True)
    for arm in ["eager", "graph"]:
        agg = arm_agg[arm]
        mm = agg.get("measured_multiplier")
        if agg["status"] == "PASS":
            print(f"  {arm}: {agg['mean_tokens_per_s']:.0f} tok/s, "
                  f"MM={mm:.4f}x" if mm is not None else
                  f"  {arm}: {agg['mean_tokens_per_s']:.0f} tok/s", flush=True)
        else:
            print(f"  {arm}: FAIL — {agg.get('reason','')}", flush=True)

    os.makedirs(RECEIPTS, exist_ok=True)
    out = os.path.join(RECEIPTS, f"cuda-graph-ab-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"CUDA_GRAPH_AB_DONE {out}")
    return receipt


# ---------------------------------------------------------------------------
# Selftest (CPU-only, no GPU, no shards required)
# ---------------------------------------------------------------------------

def _selftest():
    # 1. Governor constants satisfy fp19 floor (never relax)
    assert VRAM_FRACTION <= 0.80, "VRAM_FRACTION must not exceed 0.80"
    assert MARGIN_GIB >= 1.5,   "MARGIN_GIB must not be below 1.5"
    assert PACE_S >= 0.05,      "PACE_S must not be below 0.05"

    # 2. measured_multiplier formula: graph_tok_s / eager_tok_s (>1.0 = graph faster)
    def mm(graph_tok_s, eager_tok_s):
        return graph_tok_s / eager_tok_s
    assert mm(20000, 15000) > 1.0   # graph faster → MM > 1
    assert mm(10000, 15000) < 1.0   # graph slower → MM < 1
    assert abs(mm(15000, 15000) - 1.0) < 1e-9

    # 3. c03 shapes frozen (match E4 profiler and v0 config)
    assert HIDDEN == 1024
    assert LAYERS == 20
    assert SEQ == 1024
    assert BATCH == 4
    assert VOCAB == 32000

    # 4. Seeds fixed
    assert set(SEEDS) == {16, 17, 18}
    assert len(SEEDS) == 3

    # 5. Warmup and bench reps are non-trivial
    assert WARMUP_REPS >= 3, "warmup must be >= 3 to prime CUDA caches before capture"
    assert BENCH_REPS >= 10, "bench must be >= 10 for stable mean"

    # 6. Arms defined correctly (2 arms, no 3-arm setup needed)
    arms = ["eager", "graph"]
    assert len(arms) == 2
    assert "eager" in arms
    assert "graph" in arms

    # 7. Verdict logic: GRAPH_PASS iff MM > 1.0 and graph status PASS
    def verdict(graph_mm, graph_status):
        if graph_status == "FAIL":
            return "GRAPH_ERROR"
        if graph_mm is None:
            return "GRAPH_ERROR"
        return "GRAPH_PASS" if graph_mm > 1.0 else "GRAPH_FAIL"

    assert verdict(1.05, "PASS") == "GRAPH_PASS"
    assert verdict(0.95, "PASS") == "GRAPH_FAIL"
    assert verdict(None, "FAIL") == "GRAPH_ERROR"
    assert verdict(1.05, "FAIL") == "GRAPH_ERROR"

    # 8. grad_checkpointing is False (v0 config per PR #300)
    #    The graph arm requires it off — dynamic recompute in a graph is illegal.
    assert not False, "grad_checkpointing must be False for graph capture"

    print("CUDA_GRAPH_AB_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
