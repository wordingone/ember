# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp44_multimodal_tokps_bench.py — GPU tok/s bench for realized v0 multimodal config.

ember #433. Measures training-step throughput (forward + backward + AdamW step)
on the production multimodal backbone: LlamaForCausalLM with v0 dims (c03:
hidden=1024, layers=20, heads=16, vocab=32000, seq=1024, bfloat16, CUDA).

This is the tok/s lever that closes fp-44 ≤1-day-bar arithmetic and finalizes
the optimizer pick per docs/domains/governance/design/fp44-multimodal-optimizer-decision.md.

Short bench: WARMUP=3 + TIMED=200 steps. Does not trip long-run interlock.

Receipt: receipts/fp44-multimodal-tokps-<ts>.json
  tokps_basis: "realized-v0-multimodal-config: hidden=1024 layers=20 heads=16
                vocab=32000 seq=1024 batch=4 bfloat16 AdamW RTX-4090"
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
RECEIPTS = ROOT / "receipts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

VOCAB = 32000
SEQ = 1024
HIDDEN = 1024
LAYERS = 20
HEADS = 16
BATCH = 4
WARMUP = 3
TIMED = 200
VRAM_FRACTION = 0.80
MARGIN_GIB = 1.5
PACE_S = 0.05


def main():
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM
    from receipt_write import checked_write

    assert torch.cuda.is_available(), "CUDA required"
    device_name = torch.cuda.get_device_name(0)
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    conf = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=HIDDEN,
        intermediate_size=4 * HIDDEN,
        num_hidden_layers=LAYERS,
        num_attention_heads=HEADS,
        num_key_value_heads=HEADS,
        max_position_embeddings=SEQ,
        tie_word_embeddings=True,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.gradient_checkpointing_enable()
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"model params: {n_params:,}", flush=True)

    def step():
        ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        out = model(input_ids=ids, labels=ids)
        out.loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)

    print(f"warmup {WARMUP} steps ...", flush=True)
    for _ in range(WARMUP):
        step()
    torch.cuda.synchronize()

    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    total_gib = total_b / (1 << 30)
    assert free_gib >= MARGIN_GIB, \
        f"VRAM margin violated: {free_gib:.2f} GiB free < {MARGIN_GIB} GiB"
    print(f"VRAM: {free_gib:.2f}/{total_gib:.2f} GiB free post-warmup", flush=True)

    print(f"timing {TIMED} steps ...", flush=True)
    t0 = time.perf_counter()
    for i in range(TIMED):
        step()
        torch.cuda.synchronize()
        time.sleep(PACE_S)
        if (i + 1) % 50 == 0:
            print(f"  step {i+1}/{TIMED}", flush=True)
    dt = time.perf_counter() - t0

    toks = TIMED * BATCH * SEQ
    tok_s_paced = toks / dt
    tok_s_raw = toks / (dt - TIMED * PACE_S)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path = RECEIPTS / f"fp44-multimodal-tokps-{ts}.json"
    RECEIPTS.mkdir(exist_ok=True)

    tokps_basis = (
        f"realized-v0-multimodal-config: hidden={HIDDEN} layers={LAYERS} "
        f"heads={HEADS} vocab={VOCAB} seq={SEQ} batch={BATCH} "
        f"bfloat16 gradient-ckpt AdamW {device_name}"
    )
    receipt = {
        "ticket": "FP44-MULTIMODAL-TOKPS",
        "ts": ts,
        "device": device_name,
        "config": {
            "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
            "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
            "dtype": "bfloat16", "grad_ckpt": True, "optimizer": "AdamW",
        },
        "params": n_params,
        "warmup_steps": WARMUP,
        "timed_steps": TIMED,
        "tokens_per_second_paced": round(tok_s_paced, 1),
        "tokens_per_second_raw": round(tok_s_raw, 1),
        "tokens_per_second": round(tok_s_paced, 1),
        "free_vram_gib_post_warmup": round(free_gib, 2),
        "tokps_basis": tokps_basis,
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
    }
    checked_write(str(receipt_path), receipt)

    print(f"\ntok/s paced: {tok_s_paced:,.1f}")
    print(f"tok/s raw:   {tok_s_raw:,.1f}")
    print(f"receipt:     {receipt_path}")
    print(f"FP44_MULTIMODAL_TOKPS_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
