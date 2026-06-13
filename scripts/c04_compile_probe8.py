"""c04_compile_probe8.py -- Test forward-only compile (no backward inside compiled fn).

In torch 2.6, Tensor.backward is unsupported under fullgraph=True when called
inside the compiled function. Solution: compile only the forward pass; backward
and optimizer step run outside the compiled region.

Tests:
  1. forward_only() with fullgraph=True — backbone + CE + mtp_loss, returns loss
  2. Timed eager vs compiled throughput (5 warmup + 10 timed steps)

h2048-d12, batch=4 (small but measurable), no grad_ckpt.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import c04_dynamo_patch

print(f"[probe8] torch: {torch.__version__}", flush=True)

import timeshare_pretrain as ts
from transformers import LlamaConfig, LlamaModel

HIDDEN, LAYERS, HEADS = 2048, 12, 32
SEQ, VOCAB = 1024, 50304
MTP_N_HEADS = 2
MTP_WEIGHT  = 0.3
LR_MUON, LR_ADAMW, WD = 0.02, 3e-4, 0.1
BATCH = 4   # enough for throughput signal

WARMUP = 5
TIMED  = 10
PACE_S = 0.0

torch.cuda.set_per_process_memory_fraction(0.75)

conf = LlamaConfig(
    vocab_size=VOCAB, hidden_size=HIDDEN, intermediate_size=HIDDEN*4,
    num_hidden_layers=LAYERS, num_attention_heads=HEADS,
    num_key_value_heads=HEADS, max_position_embeddings=SEQ, use_cache=False,
)

def build_model():
    backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
    backbone.train()
    head = torch.nn.Linear(HIDDEN, VOCAB, bias=False).cuda().to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight
    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(HIDDEN, VOCAB, bias=False).cuda().to(torch.bfloat16)
        for _ in range(MTP_N_HEADS)
    ])
    all_params = dict(backbone.named_parameters())
    for i, h in enumerate(mtp_heads):
        for n, p in h.named_parameters():
            all_params[f"mtp_heads.{i}.{n}"] = p
    muon_p, adamw_p = [], []
    for name, p in all_params.items():
        if p.ndim == 2 and "embed_tokens" not in name:
            muon_p.append(p)
        else:
            adamw_p.append(p)
    Muon = ts._muon_class()
    opts = {}
    if muon_p:
        opts["muon"] = Muon(muon_p, lr=LR_MUON, weight_decay=WD)
    opts["adamw"] = torch.optim.AdamW(adamw_p, lr=LR_ADAMW, weight_decay=WD)
    return backbone, head, mtp_heads, opts


def run_bench(backbone, head, mtp_heads, opts, ce_fn, fwd_fn, label):
    """Run WARMUP + TIMED steps, return tok/s."""
    def full_step():
        ids   = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        tgt0  = torch.roll(ids, -1, dims=1)
        tgt_m = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
        loss  = fwd_fn(ids, tgt0, tgt_m)
        loss.backward()
        for o in opts.values():
            o.step()
        for o in opts.values():
            o.zero_grad(set_to_none=True)
        return loss.item()

    print(f"[probe8] {label}: warmup {WARMUP} ...", flush=True)
    for i in range(WARMUP):
        full_step()
        print(f"[probe8]   warmup {i+1}/{WARMUP}", flush=True)

    torch.cuda.synchronize()
    print(f"[probe8] {label}: bench {TIMED} steps ...", flush=True)
    t0 = time.perf_counter()
    for _ in range(TIMED):
        full_step()
        torch.cuda.synchronize()
    total_dt = time.perf_counter() - t0
    toks = TIMED * BATCH * SEQ
    tok_s = toks / total_dt
    print(f"[probe8] {label}: tok/s={tok_s:.0f} total_dt={total_dt:.2f}s", flush=True)
    return tok_s


# ── Apply patches ─────────────────────────────────────────────────────────────
print("\n[probe8] applying patches ...", flush=True)
msg = c04_dynamo_patch.apply()
print(f"[probe8] {msg}", flush=True)

# ── EAGER baseline ────────────────────────────────────────────────────────────
print("\n[probe8] === EAGER BASELINE ===", flush=True)
bb_e, hd_e, mh_e, opts_e = build_model()
c04_dynamo_patch.apply_compile_patch(bb_e)
ce_fn = ts.chunked_cross_entropy

def fwd_eager(ids, tgt0, tgt_m):
    hid  = bb_e(input_ids=ids).last_hidden_state
    hf   = hid.reshape(-1, hid.shape[-1])
    pce, _ = ce_fn(hf, hd_e.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces   = [ce_fn(hf, mh_e[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
              for k in range(MTP_N_HEADS)]
    return ts.mtp_total_loss(pce, mces, MTP_WEIGHT)

try:
    tok_s_eager = run_bench(bb_e, hd_e, mh_e, opts_e, ce_fn, fwd_eager, "eager")
except torch.cuda.OutOfMemoryError:
    print("[probe8] EAGER: OOM", flush=True)
    tok_s_eager = 0.0

del bb_e, hd_e, mh_e, opts_e
torch.cuda.empty_cache()

# ── COMPILED forward-only ─────────────────────────────────────────────────────
print("\n[probe8] === COMPILED (forward-only, fullgraph=True) ===", flush=True)
bb_c, hd_c, mh_c, opts_c = build_model()
c04_dynamo_patch.apply_compile_patch(bb_c)

def fwd_for_compile(ids, tgt0, tgt_m):
    hid  = bb_c(input_ids=ids).last_hidden_state
    hf   = hid.reshape(-1, hid.shape[-1])
    pce, _ = ce_fn(hf, hd_c.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces   = [ce_fn(hf, mh_c[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
              for k in range(MTP_N_HEADS)]
    return ts.mtp_total_loss(pce, mces, MTP_WEIGHT)

compile_status = "SKIP"
tok_s_compiled = 0.0
try:
    fwd_compiled = torch.compile(fwd_for_compile, fullgraph=True)
    print("[probe8] compile call ...", flush=True)
    # trigger compile with one call (outside bench)
    _ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
    _t0  = torch.roll(_ids, -1, dims=1)
    _tm  = [torch.roll(_ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
    _l = fwd_compiled(_ids, _t0, _tm)
    _l.backward()
    for o in opts_c.values():
        o.step(); o.zero_grad(set_to_none=True)
    print("[probe8] compile: PASS", flush=True)
    compile_status = "PASS"
    tok_s_compiled = run_bench(bb_c, hd_c, mh_c, opts_c, ce_fn, fwd_compiled, "compiled")
except torch._dynamo.exc.Unsupported as e:
    compile_status = "FAIL-Unsupported"
    print(f"[probe8] compile FAIL: {str(e)[:400]}", flush=True)
except torch._dynamo.exc.UserError as e:
    compile_status = "FAIL-UserError"
    print(f"[probe8] compile FAIL: {str(e)[:400]}", flush=True)
except Exception as e:
    compile_status = f"FAIL-{type(e).__name__}"
    print(f"[probe8] compile FAIL: {str(e)[:400]}", flush=True)

del bb_c, hd_c, mh_c, opts_c
torch.cuda.empty_cache()

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n[probe8] === SUMMARY ===", flush=True)
print(f"[probe8] compile_status: {compile_status}", flush=True)
print(f"[probe8] eager  tok/s: {tok_s_eager:.0f}", flush=True)
print(f"[probe8] compiled tok/s: {tok_s_compiled:.0f}", flush=True)
if tok_s_eager > 0 and tok_s_compiled > 0:
    speedup = tok_s_compiled / tok_s_eager
    print(f"[probe8] speedup: {speedup:.3f}x", flush=True)
print(f"\nC04_PROBE8_DONE compile={compile_status} eager={tok_s_eager:.0f} compiled={tok_s_compiled:.0f}", flush=True)
