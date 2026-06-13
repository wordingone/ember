"""c04_compile_probe7.py -- Verify both dynamo patches (chunked_ce + backbone forward).

Tests:
  1. apply_compile_patch: does inspect.unwrap find __wrapped__?
  2. fwd_bwd with fullgraph=True after both patches
  3. fwd_bwd eager output matches before/after patch (correctness)
  4. If TEST-2 passes: time full-step compile failure (expect timer blocker)

h2048-d12, batch=1, no grad_ckpt.
"""
import sys, os, time, types, inspect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import c04_dynamo_patch

print(f"[probe7] torch: {torch.__version__}", flush=True)

import timeshare_pretrain as ts
from transformers import LlamaConfig, LlamaModel

HIDDEN, LAYERS, HEADS = 2048, 12, 32
SEQ, VOCAB = 1024, 50304
MTP_N_HEADS = 2
MTP_WEIGHT  = 0.3
LR_MUON, LR_ADAMW, WD = 0.02, 3e-4, 0.1
BATCH = 1

torch.cuda.set_per_process_memory_fraction(0.70)

conf = LlamaConfig(
    vocab_size=VOCAB, hidden_size=HIDDEN, intermediate_size=HIDDEN*4,
    num_hidden_layers=LAYERS, num_attention_heads=HEADS,
    num_key_value_heads=HEADS, max_position_embeddings=SEQ, use_cache=False,
)

# ── TEST 0: inspect __wrapped__ chain ────────────────────────────────────────
print("\n[probe7] TEST-0: inspect __wrapped__ chain on backbone.forward ...", flush=True)
bb0 = LlamaModel(conf)
fwd0 = bb0.forward
fn0 = getattr(fwd0, '__func__', fwd0)
orig0 = inspect.unwrap(fn0)
print(f"[probe7] forward.__func__: {fn0}", flush=True)
print(f"[probe7] inspect.unwrap result: {orig0}", flush=True)
print(f"[probe7] same as __func__: {orig0 is fn0}", flush=True)
print(f"[probe7] has __wrapped__: {hasattr(fn0, '__wrapped__')}", flush=True)
if hasattr(fn0, '__wrapped__'):
    print(f"[probe7] __wrapped__: {fn0.__wrapped__}", flush=True)
del bb0

# ── Build model ───────────────────────────────────────────────────────────────
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

# ── Apply patches ─────────────────────────────────────────────────────────────
print("\n[probe7] applying patches ...", flush=True)
msg1 = c04_dynamo_patch.apply()
print(f"[probe7] {msg1}", flush=True)
c04_dynamo_patch.apply_compile_patch(backbone)
print(f"[probe7] apply_compile_patch done; forward is now: {backbone.forward}", flush=True)

ce_fn = ts.chunked_cross_entropy

# ── TEST 1: correctness — eager run before/after patch ───────────────────────
print("\n[probe7] TEST-1: correctness check (eager fwd_bwd) ...", flush=True)
try:
    torch.manual_seed(42)
    ids  = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
    tgt0 = torch.roll(ids, -1, dims=1)
    tgt_m = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
    hid   = backbone(input_ids=ids).last_hidden_state
    hf    = hid.reshape(-1, hid.shape[-1])
    pce, nv = ce_fn(hf, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces  = [ce_fn(hf, mtp_heads[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
             for k in range(MTP_N_HEADS)]
    loss = ts.mtp_total_loss(pce, mces, MTP_WEIGHT)
    loss.backward()
    print(f"[probe7] TEST-1: PASS eager loss={loss.item():.4f} pce={pce.item():.4f} n_valid={nv}", flush=True)
except Exception as e:
    print(f"[probe7] TEST-1: FAIL {type(e).__name__}: {e}", flush=True)

for o in opts.values():
    o.zero_grad(set_to_none=True)
torch.cuda.empty_cache()

# ── TEST 2: fwd_bwd fullgraph=True ───────────────────────────────────────────
print("\n[probe7] TEST-2: fwd_bwd fullgraph=True (no opt, no timer) ...", flush=True)
try:
    def fwd_bwd():
        ids   = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        tgt0  = torch.roll(ids, -1, dims=1)
        tgt_m = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
        hid   = backbone(input_ids=ids).last_hidden_state
        hf    = hid.reshape(-1, hid.shape[-1])
        pce, _ = ce_fn(hf, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
        mces   = [ce_fn(hf, mtp_heads[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
                  for k in range(MTP_N_HEADS)]
        loss = ts.mtp_total_loss(pce, mces, MTP_WEIGHT)
        loss.backward()

    fwd_bwd_c = torch.compile(fwd_bwd, fullgraph=True)
    print("[probe7] compiling ...", flush=True)
    fwd_bwd_c()
    print("[probe7] TEST-2: PASS fwd_bwd compiles fullgraph=True", flush=True)
    compile_pass = True
except torch._dynamo.exc.Unsupported as e:
    print(f"[probe7] TEST-2: FAIL-Unsupported: {str(e)[:400]}", flush=True)
    compile_pass = False
except torch._dynamo.exc.UserError as e:
    print(f"[probe7] TEST-2: FAIL-UserError: {str(e)[:400]}", flush=True)
    compile_pass = False
except Exception as e:
    print(f"[probe7] TEST-2: FAIL-{type(e).__name__}: {str(e)[:400]}", flush=True)
    compile_pass = False

for o in opts.values():
    o.zero_grad(set_to_none=True)
torch.cuda.empty_cache()

# ── TEST 3: full step compile (expect timer blocker under fullgraph=True) ────
if compile_pass:
    print("\n[probe7] TEST-3: full step fullgraph=True (expect time.perf_counter blocker) ...", flush=True)
    def step_full():
        ids   = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        tgt0  = torch.roll(ids, -1, dims=1)
        tgt_m = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
        hid   = backbone(input_ids=ids).last_hidden_state
        hf    = hid.reshape(-1, hid.shape[-1])
        pce, _ = ce_fn(hf, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
        mces   = [ce_fn(hf, mtp_heads[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
                  for k in range(MTP_N_HEADS)]
        loss = ts.mtp_total_loss(pce, mces, MTP_WEIGHT)
        loss.backward()
        t0 = time.perf_counter()
        for o in opts.values():
            o.step()
        t_opt = time.perf_counter() - t0
        for o in opts.values():
            o.zero_grad(set_to_none=True)
        return t_opt

    try:
        step_c = torch.compile(step_full, fullgraph=True)
        step_c()
        print("[probe7] TEST-3: PASS (unexpected)", flush=True)
    except Exception as e:
        print(f"[probe7] TEST-3: FAIL-{type(e).__name__}: {str(e)[:300]}", flush=True)
        print("[probe7] NOTE: eli should compile fwd_bwd only; keep timer + opt step outside compiled region", flush=True)

print("\nC04_PROBE7_DONE", flush=True)
