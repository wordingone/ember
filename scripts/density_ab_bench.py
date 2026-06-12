"""density_ab_bench.py — one density A/B training cell.

Usage:
  python density_ab_bench.py --arm a --seed 0
  python density_ab_bench.py --arm a --seed 1
  python density_ab_bench.py --arm b --seed 0
  python density_ab_bench.py --arm b --seed 1

Each cell trains a c01 model (~79M params) on 100M tokens from the designated
arm shard, with probes at 50M (step 6103) and 100M (step 12207) tokens.
W-code rate evaluated at each probe using 400 MBPP prompts.

Governor rails (same as fp19, HOLD):
  VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05
"""

import argparse
import ast
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fp19_bench as fp19                           # noqa: E402
from receipt_write import checked_write             # noqa: E402

RECEIPTS = f"{NC}/receipts"
SHARD_DIR = "/mnt/b/M/avir/eli/state/ember-eng/density-ab-shards"

SEQ   = fp19.SEQ        # 1024
VOCAB = fp19.VOCAB      # 32000
PACE_S        = fp19.PACE_S         # 0.05
VRAM_FRACTION = 0.80
MARGIN_GIB    = fp19.MARGIN_GIB     # 1.5
VARIANT       = "qat"

# c01 config (fp19)
C01 = fp19.CONFIGS["c01"]   # hidden=640, layers=12, heads=10, batch=8
BATCH = C01["batch"]        # 8

# Training schedule (spec §3: ~12,207 steps for 100M tokens)
STEPS_TOTAL  = 12207
STEPS_50PCT  = 6103   # 50M token probe
WCODE_N      = 400    # max eval prompts
WCODE_MAX_NEW = 64    # tokens generated per prompt
WCODE_BATCH   = 16    # inference batch

MANIFEST_ARM_A = f"{NC}/density-ab-manifests/arm-a-manifest.json"
MANIFEST_ARM_B = f"{NC}/density-ab-manifests/arm-b-manifest.json"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _check_wcode(text):
    """Return True if text contains a syntactically valid Python statement."""
    # Try full block first
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        pass
    # Try each non-empty line
    for line in text.split("\n"):
        s = line.strip()
        if s and not s.startswith("#"):
            try:
                ast.parse(s)
                return True
            except SyntaxError:
                pass
    return False


def _wcode_eval_prompts():
    """Load up to WCODE_N MBPP prompts as code-continuation prefixes."""
    try:
        from datasets import load_dataset
        ds = load_dataset("mbpp", "sanitized", trust_remote_code=True)
        problems = []
        # Use validation first, then test
        for split in ("validation", "test", "train"):
            if split in ds:
                for ex in ds[split]:
                    if len(problems) >= WCODE_N:
                        break
                    # Extract function name from first test
                    tl = ex.get("test_list", [])
                    src = ex.get("source_code", "")
                    # Use the first line of source_code as prefix
                    first_line = (src.split("\n")[0] + "\n").strip()
                    if first_line.startswith("def "):
                        prompt = first_line + "\n"
                    else:
                        # Fallback: use description
                        prompt = f"# {ex.get('text', '')[:80]}\ndef solve():\n"
                    problems.append(prompt)
            if len(problems) >= WCODE_N:
                break
        return problems[:WCODE_N]
    except Exception as e:
        print(f"[wcode] MBPP load failed: {e} — using synthetic prompts", flush=True)
        # Fallback: synthetic Python continuation prompts
        return [f"def f{i}(x):\n" for i in range(WCODE_N)]


def run_wcode_eval(model, tok_ids_fn, prompts):
    """Generate completions + check W-code rate. Returns dict."""
    import torch
    model.eval()
    n_pass = 0
    n_total = len(prompts)
    with torch.no_grad():
        for i in range(0, n_total, WCODE_BATCH):
            batch_prompts = prompts[i:i + WCODE_BATCH]
            # Encode each prompt as token ids using a simple character-level fallback
            # or just use the prompt text as context via the production tokenizer
            for prompt in batch_prompts:
                # Tokenize the prompt
                ids = tok_ids_fn(prompt)
                if not ids:
                    continue
                inp = torch.tensor([ids], device="cuda")
                # Generate WCODE_MAX_NEW tokens (greedy)
                with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                    out = model.generate(
                        inp,
                        max_new_tokens=WCODE_MAX_NEW,
                        do_sample=False,
                        pad_token_id=0,
                    )
                # Decode generated tokens (new tokens only)
                new_ids = out[0, len(ids):].tolist()
                # Decode to text
                generated = "".join(chr(t) if 32 <= t < 128 else " " for t in new_ids)
                if _check_wcode(prompt + generated):
                    n_pass += 1
    rate = n_pass / n_total if n_total else 0.0
    model.train()
    return {"wcode_rate": round(rate, 4), "n_pass": n_pass, "n_prompts": n_total}


def _load_shard(shard_path):
    """Load shard as numpy uint16 array."""
    import numpy as np
    return np.fromfile(shard_path, dtype="<u2")


def _build_model(seed):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)

    conf = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=C01["hidden"],
        intermediate_size=4 * C01["hidden"],
        num_hidden_layers=C01["layers"],
        num_attention_heads=C01["heads"],
        num_key_value_heads=C01["heads"],
        max_position_embeddings=SEQ,
        tie_word_embeddings=True,
        use_cache=False,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.train()
    return model


def _load_tokenizer_encode_fn():
    """Load frozen tokenizer, return text->list[int] function."""
    tok_json = f"{NC}/tokenizer/tokenizer.json"
    from tokenizers import Tokenizer
    d = json.load(open(tok_json, encoding="utf-8"))
    d["added_tokens"] = []
    tk = Tokenizer.from_str(json.dumps(d))
    return lambda text: tk.encode(text, add_special_tokens=False).ids


def bench_cell(arm, seed, shard_path, prompts, encode_fn):
    import torch
    import numpy as np

    cell_name = f"arm-{arm}-seed{seed}"
    print(f"[bench] cell {cell_name} shard={shard_path}", flush=True)

    shard = _load_shard(shard_path)
    n_tokens = shard.size
    print(f"[bench] shard loaded: {n_tokens:,} tokens", flush=True)

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    model = _build_model(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.1)

    # Shard stream cursor
    cursor = 0
    block_len = SEQ + 1   # input + one shifted target

    def next_batch():
        nonlocal cursor
        ids = []
        for _ in range(BATCH):
            if cursor + block_len > n_tokens:
                cursor = 0  # wrap
            ids.append(shard[cursor:cursor + block_len].tolist())
            cursor += SEQ  # stride by SEQ (dense packing)
        return ids

    def train_step():
        batch_ids = next_batch()
        inp_t = torch.tensor([b[:SEQ] for b in batch_ids], dtype=torch.long, device="cuda")
        tgt_t = torch.tensor([b[1:SEQ+1] for b in batch_ids], dtype=torch.long, device="cuda")
        saved = fp19._apply_fake_quant(model, VARIANT)
        out = model(input_ids=inp_t, labels=tgt_t)
        loss = out.loss
        fp19._restore(saved)
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        return loss.item()

    # Warmup (not counted in timing)
    print(f"[bench] warmup 5 steps ...", flush=True)
    for _ in range(5):
        train_step()
    torch.cuda.synchronize()

    free_b, _ = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    print(f"[bench] post-warmup free VRAM: {free_gib:.2f} GiB", flush=True)
    if free_gib < MARGIN_GIB:
        print(f"[bench] SKIPPED-MARGIN ({free_gib:.2f} < {MARGIN_GIB} GiB)", flush=True)
        return {"cell": cell_name, "status": "SKIPPED-MARGIN",
                "free_vram_gib": round(free_gib, 2)}

    results = {"cell": cell_name, "arm": arm, "seed": seed, "batch": BATCH, "seq": SEQ}
    probes = {}

    def _run_probe(label, n_steps_done):
        """Run W-code eval at current model state."""
        print(f"[bench] probe {label}: W-code eval ...", flush=True)
        wr = run_wcode_eval(model, encode_fn, prompts)
        print(f"[bench] probe {label}: wcode_rate={wr['wcode_rate']}", flush=True)
        probes[label] = wr

    # --- train to 50% ---
    t0 = time.perf_counter()
    for step in range(STEPS_50PCT):
        train_step()
        torch.cuda.synchronize()
        time.sleep(PACE_S)
        if (step + 1) % 1000 == 0:
            print(f"[bench] step {step+1}/{STEPS_TOTAL}", flush=True)
    dt_50 = time.perf_counter() - t0
    toks_50 = STEPS_50PCT * BATCH * SEQ
    tok_s_50 = round(toks_50 / (dt_50 - STEPS_50PCT * PACE_S), 1)
    print(f"[bench] 50% done: {tok_s_50} raw tok/s", flush=True)
    _run_probe("50pct", STEPS_50PCT)

    # --- train to 100% ---
    t1 = time.perf_counter()
    remaining = STEPS_TOTAL - STEPS_50PCT
    for step in range(remaining):
        train_step()
        torch.cuda.synchronize()
        time.sleep(PACE_S)
        if (step + 1) % 1000 == 0:
            print(f"[bench] step {STEPS_50PCT+step+1}/{STEPS_TOTAL}", flush=True)
    dt_100 = time.perf_counter() - t1
    toks_100 = remaining * BATCH * SEQ
    tok_s_100 = round(toks_100 / (dt_100 - remaining * PACE_S), 1)
    print(f"[bench] 100% done: {tok_s_100} raw tok/s", flush=True)
    _run_probe("100pct", STEPS_TOTAL)

    free_b, _ = torch.cuda.mem_get_info()
    results.update({
        "status": "OK",
        "tok_s_raw_50pct": tok_s_50,
        "tok_s_raw_100pct": tok_s_100,
        "probes": probes,
        "slope": "rising" if probes["100pct"]["wcode_rate"] > probes["50pct"]["wcode_rate"]
                 else ("flat" if probes["100pct"]["wcode_rate"] == probes["50pct"]["wcode_rate"]
                       else "falling"),
        "free_vram_gib_final": round(free_b / (1 << 30), 2),
    })

    del model, opt
    torch.cuda.empty_cache()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=("a", "b"),
                    help="Arm A = bulk v0 mix; Arm B = curated code-only")
    ap.add_argument("--seed", required=True, type=int, choices=(0, 1),
                    help="Training seed (weight init + batch shuffle)")
    args, _ = ap.parse_known_args()

    arm, seed = args.arm, args.seed
    shard_path = f"{SHARD_DIR}/density-ab-arm-{arm}-100M.bin"
    if not os.path.exists(shard_path):
        raise FileNotFoundError(f"Shard not found: {shard_path}. Run density_ab_prep.py first.")

    # Load manifest to verify shard sha
    manifest_path = (MANIFEST_ARM_A if arm == "a" else MANIFEST_ARM_B)
    if os.path.exists(manifest_path):
        mf = json.load(open(manifest_path))
        expected_sha = mf.get("shard", {}).get("sha256")
        if expected_sha:
            actual_sha = _sha256(shard_path)
            if actual_sha != expected_sha:
                raise ValueError(f"Shard sha mismatch: {actual_sha[:16]} != {expected_sha[:16]}")
            print(f"[bench] Shard sha verified: {actual_sha[:16]}", flush=True)

    import torch
    print(f"[bench] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[bench] torch: {torch.__version__}", flush=True)
    print(f"[bench] density A/B: arm={arm} seed={seed}", flush=True)

    prompts = _wcode_eval_prompts()
    print(f"[bench] loaded {len(prompts)} W-code eval prompts", flush=True)
    encode_fn = _load_tokenizer_encode_fn()

    cell_result = bench_cell(arm, seed, shard_path, prompts, encode_fn)

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "DENSITY-AB-V1",
        "ts": ts_now,
        "issue": 225,
        "arm": arm,
        "arm_label": "bulk-v0-mix" if arm == "a" else "curated-code-only",
        "seed": seed,
        "code_fraction": 0.581 if arm == "a" else 1.0,
        "tokens": STEPS_TOTAL * BATCH * SEQ,
        "training_steps": STEPS_TOTAL,
        "model": "c01",
        "model_config": C01,
        "cell": cell_result,
        "caveats": {
            "code_fraction_is_proxy": (
                "code_fraction is a PROXY for the verified-density axis — "
                "the actual verification status of shards is not re-audited in this bench."
            ),
            "c01_to_c03_scale_transfer": (
                "c01→c03 scale transfer is an assumption — density signal at c01 "
                "(hidden=640, 79M params) may not hold at c03 (hidden=1024, 284M params); "
                "verdict is directional, not a precision estimate at production scale."
            ),
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "runtime": {
            "device": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
        },
    }

    out = f"{RECEIPTS}/density-ab-arm{arm}-seed{seed}-{ts_now}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "arm": arm, "seed": seed,
        "status": cell_result.get("status"),
        "wcode_50pct": cell_result.get("probes", {}).get("50pct", {}).get("wcode_rate"),
        "wcode_100pct": cell_result.get("probes", {}).get("100pct", {}).get("wcode_rate"),
        "slope": cell_result.get("slope"),
    }, indent=2))
    print(f"DENSITY_AB_CELL_DONE arm={arm} seed={seed}")


if __name__ == "__main__":
    main()
