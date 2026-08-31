# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c04_compile_probe9.py -- Batch=8 + mode="reduce-overhead" (CUDA graphs) test.

Probe8 showed forward-only fullgraph=True gives 1.01x at batch=4.
This probe tests:
  A. Forward-only fullgraph=True at batch=8 (actual nockpt bench params)
  B. mode="reduce-overhead" on full step (CUDA graphs -- captures fwd+bwd+opt)
     mode="reduce-overhead" bypasses dynamo tracing restrictions by using CUDAGraph
     replay, which sidesteps the Tensor.backward fullgraph=True restriction.

h2048-d12, no grad_ckpt.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import c04_dynamo_patch
print(f"[probe9] torch: {torch.__version__}", flush=True)

# issue2015 exact-local-import:scripts/timeshare_pretrain.py
import importlib.util as _ember_d9c5c82c124e1dc8_importlib
import sys as _ember_d9c5c82c124e1dc8_sys
from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
_ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parents[4].joinpath('scripts', 'timeshare_pretrain.py')
if not _ember_d9c5c82c124e1dc8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/timeshare_pretrain.py')
_ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'scripts.timeshare_pretrain', 'timeshare_pretrain')
_ember_d9c5c82c124e1dc8_existing = []
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
        _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
if len(_ember_d9c5c82c124e1dc8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/timeshare_pretrain.py')
if _ember_d9c5c82c124e1dc8_existing:
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
    _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
    if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/timeshare_pretrain.py')
else:
    _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
    if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    try:
        _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
    except BaseException:
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
        raise
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
ts = _ember_d9c5c82c124e1dc8_module
# issue2015 exact-local-import-end:scripts/timeshare_pretrain.py
from transformers import LlamaConfig, LlamaModel

HIDDEN, LAYERS, HEADS = 2048, 12, 32
SEQ, VOCAB = 1024, 50304
MTP_N_HEADS = 2
MTP_WEIGHT  = 0.3
LR_MUON, LR_ADAMW, WD = 0.02, 3e-4, 0.1
BATCH = 8   # actual nockpt bench params for h2048-d12

WARMUP = 5
TIMED  = 10

torch.cuda.set_per_process_memory_fraction(0.80)

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


def run_bench(fwd_fn, opts, label):
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

    print(f"[probe9] {label}: warmup {WARMUP} ...", flush=True)
    for i in range(WARMUP):
        full_step()
        print(f"[probe9]   warmup {i+1}/{WARMUP}", flush=True)
    torch.cuda.synchronize()
    print(f"[probe9] {label}: bench {TIMED} steps ...", flush=True)
    t0 = time.perf_counter()
    for _ in range(TIMED):
        full_step()
        torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    tok_s = TIMED * BATCH * SEQ / dt
    print(f"[probe9] {label}: tok/s={tok_s:.0f} dt={dt:.2f}s", flush=True)
    return tok_s


# Apply patches
print("\n[probe9] applying patches ...", flush=True)
msg = c04_dynamo_patch.apply()
print(f"[probe9] {msg}", flush=True)

results = {}

# ── A: EAGER baseline (batch=8) ───────────────────────────────────────────────
print("\n[probe9] === A: EAGER batch=8 ===", flush=True)
bb, hd, mh, opts = build_model()
c04_dynamo_patch.apply_compile_patch(bb)
ce_fn = ts.chunked_cross_entropy

def fwd_eager(ids, tgt0, tgt_m):
    hid = bb(input_ids=ids).last_hidden_state
    hf  = hid.reshape(-1, hid.shape[-1])
    pce, _ = ce_fn(hf, hd.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces   = [ce_fn(hf, mh[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
              for k in range(MTP_N_HEADS)]
    return ts.mtp_total_loss(pce, mces, MTP_WEIGHT)

try:
    results["eager"] = run_bench(fwd_eager, opts, "eager-b8")
except torch.cuda.OutOfMemoryError:
    print("[probe9] A: OOM", flush=True)
    results["eager"] = 0.0
del bb, hd, mh, opts
torch.cuda.empty_cache()

# ── B: Forward-only fullgraph=True at batch=8 ────────────────────────────────
print("\n[probe9] === B: Forward-only fullgraph=True batch=8 ===", flush=True)
bb, hd, mh, opts = build_model()
c04_dynamo_patch.apply_compile_patch(bb)

def fwd_b(ids, tgt0, tgt_m):
    hid = bb(input_ids=ids).last_hidden_state
    hf  = hid.reshape(-1, hid.shape[-1])
    pce, _ = ce_fn(hf, hd.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces   = [ce_fn(hf, mh[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
              for k in range(MTP_N_HEADS)]
    return ts.mtp_total_loss(pce, mces, MTP_WEIGHT)

try:
    fwd_bc = torch.compile(fwd_b, fullgraph=True)
    # trigger compile
    _ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
    _t0  = torch.roll(_ids, -1, dims=1)
    _tm  = [torch.roll(_ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
    _l = fwd_bc(_ids, _t0, _tm); _l.backward()
    for o in opts.values(): o.step(); o.zero_grad(set_to_none=True)
    print("[probe9] B: compile PASS", flush=True)
    results["fwd_only_b8"] = run_bench(fwd_bc, opts, "fwd-only-b8")
except Exception as e:
    print(f"[probe9] B: FAIL {type(e).__name__}: {str(e)[:300]}", flush=True)
    results["fwd_only_b8"] = 0.0
del bb, hd, mh, opts
torch.cuda.empty_cache()

# ── C: mode="reduce-overhead" on full step function ──────────────────────────
print("\n[probe9] === C: mode='reduce-overhead' on full step (CUDA graphs) ===", flush=True)
bb, hd, mh, opts = build_model()
c04_dynamo_patch.apply_compile_patch(bb)

def fwd_c(ids, tgt0, tgt_m):
    hid = bb(input_ids=ids).last_hidden_state
    hf  = hid.reshape(-1, hid.shape[-1])
    pce, _ = ce_fn(hf, hd.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces   = [ce_fn(hf, mh[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
              for k in range(MTP_N_HEADS)]
    return ts.mtp_total_loss(pce, mces, MTP_WEIGHT)

try:
    fwd_cc = torch.compile(fwd_c, mode="reduce-overhead")
    _ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
    _t0  = torch.roll(_ids, -1, dims=1)
    _tm  = [torch.roll(_ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
    _l = fwd_cc(_ids, _t0, _tm); _l.backward()
    for o in opts.values(): o.step(); o.zero_grad(set_to_none=True)
    print("[probe9] C: compile PASS", flush=True)
    results["reduce_overhead_b8"] = run_bench(fwd_cc, opts, "reduce-overhead-b8")
except Exception as e:
    print(f"[probe9] C: FAIL {type(e).__name__}: {str(e)[:300]}", flush=True)
    results["reduce_overhead_b8"] = 0.0
del bb, hd, mh, opts
torch.cuda.empty_cache()

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n[probe9] === SUMMARY ===", flush=True)
eager = results.get("eager", 0.0)
for k, v in results.items():
    spd = f" ({v/eager:.3f}x)" if eager > 0 and k != "eager" and v > 0 else ""
    print(f"[probe9] {k}: {v:.0f} tok/s{spd}", flush=True)

print(f"\nC04_PROBE9_DONE eager={eager:.0f} fwd_only={results.get('fwd_only_b8',0):.0f} reduce_overhead={results.get('reduce_overhead_b8',0):.0f}", flush=True)
