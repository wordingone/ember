"""fp19_bench.py — owned-core pretrain throughput micro-benchmark (#111, fp-19).

The June-22 critical path (research/june22-critical-path.md §2) needs the
owned-core envelope MEASURED, not paper-claimed: what (params x bit-variant
x token budget) fits the remaining continuous-GPU days on THIS 4090.

Measures full TRAINING steps (fwd + loss + bwd + AdamW step) on randomly
initialized small decoder configs with synthetic token batches:

  c01  ~0.09B  (hidden 640, 12 layers, 10 heads, vocab 32k, seq 1024)
  c03  ~0.29B  (hidden 1024, 20 layers, 16 heads, vocab 32k, seq 1024)

Variants per config:
  bf16     — plain bf16 training step (baseline).
  qat      — fake-quant STE on linear weights each step (int8-grid
             quant-dequant; overhead proxy for quantization-native
             pretraining; NOT fused kernels — flagged).
  ternary  — BitNet-style sign()+abs-mean-scale STE on linear weights
             (overhead proxy; real b1.58 trains in fp with constraints,
             so the STE wrapper IS the honest cost shape at this scale).

Governor (mandatory, safety rail): VRAM fraction cap via
set_per_process_memory_fraction(0.80), post-warmup free-VRAM margin
assert (>= 1.5 GiB), inter-step pacing sleep (PACE_S) so duty cycle
stays below wall-to-wall; budget math uses the PACED rate.

Envelope math in-receipt: paced tok/s x 86,400 x {7,8} days vs the
compute-optimal need (~20 tok/param) per config — achievable/needed
ratio + the over/under-train verdict input for the fp-19 table.

Run via daemon (train window). `--selftest` is pure-logic, no GPU.
"""
import json
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"

VOCAB = 32000
SEQ = 1024
WARMUP = 3
TIMED = 10
PACE_S = 0.05          # inter-step sleep — governor duty-cycle pacing
VRAM_FRACTION = 0.80   # per-process cap
MARGIN_GIB = 1.5       # post-warmup free-VRAM floor
DAYS = (7, 8)
TOK_PER_PARAM = 20     # compute-optimal reference (Chinchilla-class)

CONFIGS = {
    "c01": {"hidden": 640, "layers": 12, "heads": 10, "batch": 8},
    "c03": {"hidden": 1024, "layers": 20, "heads": 16, "batch": 4},
}
VARIANTS = ("bf16", "qat", "ternary")


def param_count(hidden, layers, vocab=VOCAB):
    """Decoder param estimate: 12*h^2 per layer (attn 4h^2 + mlp 8h^2)
    + tied embedding vocab*h + norms (negligible)."""
    return 12 * layers * hidden * hidden + vocab * hidden


def envelope(tok_s, params, days=DAYS, tpp=TOK_PER_PARAM):
    need = params * tpp
    out = {}
    for d in days:
        ach = tok_s * 86400 * d
        out[f"{d}d"] = {
            "achievable_tokens": int(ach),
            "needed_compute_optimal": int(need),
            "ratio": round(ach / need, 2),
        }
    return out


def _apply_fake_quant(model, mode):
    """STE-style weight transform applied in-place pre-forward each step;
    returns a restore list. int8-grid for qat; sign*scale for ternary."""
    import torch
    saved = []
    for m in model.modules():
        if isinstance(m, torch.nn.Linear):
            w = m.weight.data
            saved.append((m, w.clone()))
            if mode == "qat":
                s = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
                m.weight.data = (w / s).round().clamp(-127, 127) * s
            elif mode == "ternary":
                s = w.abs().mean()
                m.weight.data = w.sign() * s
    return saved


def _restore(saved):
    for m, w in saved:
        m.weight.data = w


def bench_one(cfg_name, variant):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    c = CONFIGS[cfg_name]
    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=c["hidden"],
        intermediate_size=4 * c["hidden"],
        num_hidden_layers=c["layers"], num_attention_heads=c["heads"],
        num_key_value_heads=c["heads"], max_position_embeddings=SEQ,
        tie_word_embeddings=True,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.gradient_checkpointing_enable()
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
    n_params = sum(p.numel() for p in model.parameters())

    def step():
        if variant != "bf16":
            saved = _apply_fake_quant(model, variant)
        ids = torch.randint(0, VOCAB, (c["batch"], SEQ), device="cuda")
        out = model(input_ids=ids, labels=ids)
        out.loss.backward()
        if variant != "bf16":
            _restore(saved)  # grads flow to fp weights (STE)
        opt.step()
        opt.zero_grad(set_to_none=True)

    for _ in range(WARMUP):
        step()
    torch.cuda.synchronize()
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    assert free_gib >= MARGIN_GIB, \
        f"VRAM margin violated: {free_gib:.2f} GiB free < {MARGIN_GIB}"

    t0 = time.perf_counter()
    for _ in range(TIMED):
        step()
        torch.cuda.synchronize()
        time.sleep(PACE_S)
    dt = time.perf_counter() - t0

    toks = TIMED * c["batch"] * SEQ
    paced = toks / dt
    raw = toks / (dt - TIMED * PACE_S)
    res = {
        "params": n_params,
        "params_formula_est": param_count(c["hidden"], c["layers"]),
        "batch": c["batch"], "seq": SEQ,
        "timed_steps": TIMED,
        "tok_s_paced": round(paced, 1),
        "tok_s_raw": round(raw, 1),
        "free_vram_gib_post_warmup": round(free_gib, 2),
        "envelope_paced": envelope(paced, n_params),
    }
    del model, opt
    torch.cuda.empty_cache()
    return res


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    results = {}
    for cfg in CONFIGS:
        for var in VARIANTS:
            key = f"{cfg}-{var}"
            print(f"[fp19] bench {key} ...", flush=True)
            results[key] = bench_one(cfg, var)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP19-BENCH", "ts": ts,
        "device": "RTX 4090 (governed)",
        "governor": {"vram_fraction": VRAM_FRACTION,
                     "margin_gib_floor": MARGIN_GIB,
                     "pace_s_per_step": PACE_S,
                     "budget_math_uses": "tok_s_paced"},
        "results": results,
        "flags": [
            "qat/ternary are STE weight-transform proxies, NOT fused "
            "low-bit kernels — overhead shape is honest, absolute "
            "speedups from real kernels are NOT claimed",
            "synthetic random batches — no data pipeline; tok/s is an "
            "UPPER bound on corpus-fed throughput",
            "gradient checkpointing ON (memory-for-compute trade is "
            "part of the measured rate)",
            f"compute-optimal reference {TOK_PER_PARAM} tok/param; "
            "over-training beyond it is allowed by the envelope, "
            "under-training is the binding direction",
        ],
    }
    out = f"{RECEIPTS}/fp19-bench-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP19_BENCH_DONE {out}")


def _selftest():
    # param formula sanity: c01 ~0.08-0.10B, c03 ~0.28-0.32B
    p1 = param_count(640, 12)
    p3 = param_count(1024, 20)
    assert 7e7 < p1 < 1.1e8, p1
    assert 2.6e8 < p3 < 3.3e8, p3
    # envelope arithmetic
    e = envelope(10000.0, 1e8, days=(7,), tpp=20)
    assert e["7d"]["achievable_tokens"] == int(10000.0 * 86400 * 7)
    assert e["7d"]["needed_compute_optimal"] == int(2e9)
    assert abs(e["7d"]["ratio"] - round(10000.0 * 86400 * 7 / 2e9, 2)) < 1e-9
    # ratio direction: more days, higher ratio
    e2 = envelope(10000.0, 1e8, days=(7, 8), tpp=20)
    assert e2["8d"]["ratio"] > e2["7d"]["ratio"]
    # configs well-formed
    for c in CONFIGS.values():
        assert c["hidden"] % c["heads"] == 0
    print("FP19_BENCH_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
