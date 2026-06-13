"""c04_compile_probe5.py — minimal: does fullgraph=False succeed on LlamaModel step?"""
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

def step():
    return backbone(input_ids=ids).last_hidden_state.sum()

print("=== fullgraph=False warmup (allows breaks) ===", flush=True)
compiled_step = torch.compile(step, fullgraph=False)
try:
    for i in range(3):
        out = compiled_step()
        torch.cuda.synchronize()
        print(f"  step {i} OK: out={out.item():.4f}", flush=True)
    print("PASS: fullgraph=False runs successfully", flush=True)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {str(e)[:300]}", flush=True)

print("C04_COMPILE_PROBE5_DONE", flush=True)
