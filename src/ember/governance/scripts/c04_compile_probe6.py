# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c04_compile_probe6.py -- Probe fullgraph=True on full step after dynamo patch.

Tests:
  1. chunked_ce in isolation (patch applied)
  2. fwd_bwd stub without time.perf_counter (predict next blocker)
  3. full step with fullgraph=True (expect failure at time.perf_counter)
  4. full step with fullgraph=False (should compile with graph breaks)

h2048-d12 config, batch=1 (minimal VRAM), no grad_ckpt.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import c04_dynamo_patch
msg = c04_dynamo_patch.apply()
print(f"[probe6] {msg}", flush=True)

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

print(f"[probe6] torch: {torch.__version__}", flush=True)

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

ce_fn = ts.chunked_cross_entropy

# --- Test 1: chunked_ce isolation ---
print("\n[probe6] TEST-1: chunked_ce isolation with fullgraph=True ...", flush=True)
try:
    def ce_test():
        h = torch.randn(BATCH * SEQ, HIDDEN, device="cuda", dtype=torch.bfloat16)
        w = torch.randn(VOCAB, HIDDEN, device="cuda", dtype=torch.bfloat16)
        t = torch.randint(0, VOCAB, (BATCH * SEQ,), device="cuda")
        return ce_fn(h, w, t, chunk_tokens=1024)
    ce_c = torch.compile(ce_test, fullgraph=True)
    ce_c()
    print("[probe6] TEST-1: PASS chunked_ce compiles fullgraph=True", flush=True)
except Exception as e:
    print(f"[probe6] TEST-1: FAIL {type(e).__name__}: {str(e)[:300]}", flush=True)

torch.cuda.empty_cache()

# --- Test 2: fwd+bwd only (no optimizer, no time.perf_counter) ---
print("\n[probe6] TEST-2: fwd_bwd stub (no opt, no timer) with fullgraph=True ...", flush=True)
try:
    def fwd_bwd():
        ids   = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        tgt0  = torch.roll(ids, -1, dims=1)
        tgt_m = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
        hid   = backbone(input_ids=ids).last_hidden_state
        hf    = hid.reshape(-1, hid.shape[-1])
        pce, _ = ce_fn(hf, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
        mces   = [ce_fn(hf, mtp_heads[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
                  for k in range(MTP_N_HEADS)]
        loss = ts.mtp_total_loss(pce, mces, MTP_WEIGHT)
        loss.backward()
    fwd_bwd_c = torch.compile(fwd_bwd, fullgraph=True)
    fwd_bwd_c()
    print("[probe6] TEST-2: PASS fwd_bwd compiles fullgraph=True", flush=True)
except Exception as e:
    print(f"[probe6] TEST-2: FAIL {type(e).__name__}: {str(e)[:400]}", flush=True)

torch.cuda.empty_cache()
for o in opts.values():
    o.zero_grad(set_to_none=True)

# --- Test 3: full step with fullgraph=True (expect timer failure) ---
print("\n[probe6] TEST-3: full step fullgraph=True ...", flush=True)
def step_full():
    ids   = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
    tgt0  = torch.roll(ids, -1, dims=1)
    tgt_m = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
    hid   = backbone(input_ids=ids).last_hidden_state
    hf    = hid.reshape(-1, hid.shape[-1])
    pce, _ = ce_fn(hf, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mces   = [ce_fn(hf, mtp_heads[k].weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
              for k in range(MTP_N_HEADS)]
    loss = ts.mtp_total_loss(pce, mces, MTP_WEIGHT)
    loss.backward()
    t_opt_start = time.perf_counter()
    for o in opts.values():
        o.step()
    t_opt = time.perf_counter() - t_opt_start
    for o in opts.values():
        o.zero_grad(set_to_none=True)
    return t_opt

try:
    step_c = torch.compile(step_full, fullgraph=True)
    step_c()
    print("[probe6] TEST-3: PASS (unexpected — check for silent graph breaks)", flush=True)
except torch._dynamo.exc.UserError as e:
    print(f"[probe6] TEST-3: FAIL-UserError (expected): {str(e)[:400]}", flush=True)
except torch._dynamo.exc.Unsupported as e:
    print(f"[probe6] TEST-3: FAIL-Unsupported: {str(e)[:400]}", flush=True)
except Exception as e:
    print(f"[probe6] TEST-3: FAIL-{type(e).__name__}: {str(e)[:400]}", flush=True)

torch.cuda.empty_cache()
for o in opts.values():
    o.zero_grad(set_to_none=True)

# --- Test 4: full step with fullgraph=False (graph breaks allowed) ---
print("\n[probe6] TEST-4: full step fullgraph=False (graph breaks ok) ...", flush=True)
try:
    step_c2 = torch.compile(step_full, fullgraph=False)
    t = step_c2()
    print(f"[probe6] TEST-4: PASS compiled with breaks, t_opt={t:.4f}s", flush=True)
except Exception as e:
    print(f"[probe6] TEST-4: FAIL {type(e).__name__}: {str(e)[:400]}", flush=True)

print("\nC04_PROBE6_DONE", flush=True)
