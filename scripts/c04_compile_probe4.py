"""c04_compile_probe4.py — torch 2.6 compile workarounds for HF generic.py."""
import torch
from transformers import LlamaConfig, LlamaModel

conf = LlamaConfig(
    vocab_size=32000, hidden_size=512, intermediate_size=2048,
    num_hidden_layers=2, num_attention_heads=8, num_key_value_heads=8,
    max_position_embeddings=64, use_cache=False,
)
backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
backbone.train()
ids = torch.randint(0, 32000, (2, 64), device='cuda')

# --- Option A: suppress_errors ---
print("=== Option A: suppress_errors=True + fullgraph=True ===", flush=True)
torch._dynamo.reset()
orig = torch._dynamo.config.suppress_errors
torch._dynamo.config.suppress_errors = True
try:
    compiled = torch.compile(backbone, fullgraph=True)
    out = compiled(input_ids=ids)
    print(f"PASS: out.last_hidden_state.shape={out.last_hidden_state.shape}", flush=True)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {str(e)[:200]}", flush=True)
torch._dynamo.config.suppress_errors = orig

# --- Option B: fullgraph=False (default) + explain ---
print("\n=== Option B: fullgraph=False + torch._dynamo.explain ===", flush=True)
torch._dynamo.reset()

def step():
    return backbone(input_ids=ids).last_hidden_state.sum()

try:
    expl = torch._dynamo.explain(step)()
    print(f"graphs={len(expl.graphs)} break_reasons={len(expl.break_reasons)}", flush=True)
    for i, br in enumerate(expl.break_reasons[:5]):
        print(f"  break[{i}]: {str(br)[:150]}", flush=True)
except Exception as e:
    print(f"explain error: {type(e).__name__}: {str(e)[:200]}", flush=True)

torch._dynamo.reset()
try:
    compiled_step = torch.compile(step, fullgraph=False)
    out = compiled_step()
    print(f"PASS fullgraph=False: out.shape={out.shape}", flush=True)
except Exception as e:
    print(f"FAIL fullgraph=False: {type(e).__name__}: {str(e)[:200]}", flush=True)

# --- Option C: compile backbone module (not step fn) ---
print("\n=== Option C: torch.compile(backbone) module-level ===", flush=True)
torch._dynamo.reset()
backbone_c = torch.compile(backbone)
try:
    out = backbone_c(input_ids=ids)
    torch.cuda.synchronize()
    print(f"PASS module-compile: shape={out.last_hidden_state.shape}", flush=True)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {str(e)[:200]}", flush=True)

print("C04_COMPILE_PROBE4_DONE", flush=True)
