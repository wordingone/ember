"""fp33_e3b_gemma_e2b_proper.py — E3 proper: Gemma 4 E2B eval on MBPP validation.

Runs google/gemma-4-E2B-it (on-disk) via csi-eval venv (transformers 5.11.0+,
gemma4 architecture supported). Re-execs under csi-eval Python if needed.

csi-train is NOT touched. Leo approval: mail 14736/14740.

Split discipline:
  sanitized/validation (~43 tasks) = heldout eval surface; never used for SFT.

Governor: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05
Load: CPU bulk-load then .cuda()

Receipt: receipts/fp33-e3-gemma-e2b-smoke-<ts>.json
Ticket: FP33-E3-GEMMA-E2B-SMOKE (proper run, supersedes E3-plumbing proxy)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

# ─── csi-eval re-exec ───────────────────────────────────────────────────────
# csi-eval Python may symlink to the same binary as csi-train — realpath
# comparison is unreliable. Use an env-var flag instead.
EVAL_PYTHON = "/mnt/c/Users/Admin/.venvs/csi-eval/bin/python"

if not os.environ.get("FP33_E3_REEXEC"):
    if not os.path.exists(EVAL_PYTHON):
        raise RuntimeError(
            f"csi-eval venv not found at {EVAL_PYTHON}. "
            "Run fp33_e3_setup_eval_venv.py first."
        )
    print(f"[E3] re-exec under csi-eval Python: {EVAL_PYTHON}", flush=True)
    os.environ["FP33_E3_REEXEC"] = "1"
    os.execv(EVAL_PYTHON, [EVAL_PYTHON] + sys.argv)
    # os.execv replaces this process — code below only runs in csi-eval
# ─────────────────────────────────────────────────────────────────────────────

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
NC_SCRIPTS = "/mnt/b/M/avir/leo/state/nc-ladder/scripts"
sys.path.insert(0, NC_SCRIPTS)

RECEIPTS = f"{NC}/receipts"

MODEL_ID   = "google/gemma-4-E2B-it"
MODEL_PATH = (
    "/mnt/c/Users/Admin/.cache/huggingface/hub/"
    "models--google--gemma-4-E2B-it/snapshots/"
    "b324173c7d5721c2baba7f3b17b3b9b3d34ab1e9"
)

N_TASKS  = 10
K        = 1
MAX_NEW  = 512
TEMP     = 0.1
SEED     = 42

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05


def load_mbpp_validation(n: int) -> list[dict]:
    from datasets import load_dataset
    ds = load_dataset("google-research-datasets/mbpp", "sanitized",
                      split="validation")
    rows = []
    for r in ds:
        rows.append({
            "id": int(r["task_id"]),
            "prompt": r["prompt"],
            "tests": list(r["test_list"]),
            "imports": list(r.get("test_imports") or []),
        })
    return rows[:n]


def problem_prompt(p: dict) -> str:
    tests = "\n".join(p["tests"])
    return (
        f"Write a Python function for this task:\n{p['prompt']}\n\n"
        f"It must pass these tests:\n```python\n{tests}\n```\n"
        "Reply with ONE fenced python code block containing only the "
        "function definition(s). No prints, no explanations."
    )


def generate_one(model, tok, prompt: str, torch) -> str:
    try:
        text = tok.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False, add_generation_prompt=True,
        )
    except Exception:
        text = prompt
    enc = tok(text, return_tensors="pt", truncation=True,
              max_length=2048).to("cuda")
    with torch.no_grad():
        out = model.generate(
            **enc,
            do_sample=(TEMP > 0),
            temperature=TEMP if TEMP > 0 else 1.0,
            max_new_tokens=MAX_NEW,
            pad_token_id=tok.pad_token_id or tok.eos_token_id,
        )
    new_ids = out[0, enc.input_ids.shape[1]:]
    return tok.decode(new_ids, skip_special_tokens=True)


def main():
    import transformers
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from t1_probe import execute_batch, extract_code

    print(f"[E3] Python: {sys.executable}", flush=True)
    print(f"[E3] transformers: {transformers.__version__}", flush=True)

    # Verify gemma4 support
    from transformers.models.auto.configuration_auto import CONFIG_MAPPING
    gemma4_keys = [k for k in CONFIG_MAPPING.keys() if "gemma4" in k]
    if not gemma4_keys:
        raise RuntimeError(
            f"gemma4 not in CONFIG_MAPPING. "
            f"transformers version: {transformers.__version__}. "
            "Upgrade transformers in csi-eval first."
        )
    print(f"[E3] gemma4 keys: {gemma4_keys}", flush=True)

    torch.manual_seed(SEED)
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    free_b, total_b = torch.cuda.mem_get_info()
    free_gib  = free_b  / (1 << 30)
    total_gib = total_b / (1 << 30)
    print(f"[E3] VRAM pre-load: {free_gib:.2f}/{total_gib:.2f} GiB", flush=True)
    if free_gib < 3.0:
        raise RuntimeError(f"[E3] Insufficient VRAM: {free_gib:.2f} GiB")

    print(f"[E3] loading model: {MODEL_ID}", flush=True)
    tok = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=False)
    t_load0 = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH, torch_dtype=torch.bfloat16, trust_remote_code=False,
    )
    model = model.cuda()
    model.eval()
    t_load = time.perf_counter() - t_load0
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[E3] loaded in {t_load:.1f}s, {n_params/1e9:.3f}B params", flush=True)

    alloc_gib = torch.cuda.memory_allocated() / (1 << 30)
    free_post, _ = torch.cuda.mem_get_info()
    free_post_gib = free_post / (1 << 30)
    if free_post_gib < MARGIN_GIB:
        raise RuntimeError(
            f"[E3] VRAM margin violated: {free_post_gib:.2f} < {MARGIN_GIB}")

    problems = load_mbpp_validation(N_TASKS)
    print(f"[E3] {len(problems)} validation tasks loaded", flush=True)

    completions = []
    t_gen0 = time.perf_counter()
    for i, p in enumerate(problems):
        comp = generate_one(model, tok, problem_prompt(p), torch)
        completions.append(comp)
        print(f"[E3] generated {i+1}/{len(problems)}", flush=True)
        time.sleep(PACE_S)
    gen_secs = round(time.perf_counter() - t_gen0, 2)

    SOLVE_STUB = "\n\ndef solve(grid):\n    return [[0]]\n"
    try:
        from v_compare import strict_harness
        use_strict = True
    except ImportError:
        use_strict = False

    jobs, job_meta = [], []
    n_extract_fail = 0
    for p, comp in zip(problems, completions):
        src = extract_code(comp)
        if src is None:
            n_extract_fail += 1
            job_meta.append((p["id"], None))
            continue
        if use_strict:
            harness = strict_harness(p["imports"], src, p["tests"], SOLVE_STUB)
        else:
            full = "\n".join(p["imports"]) + "\n" + src
            for t in p["tests"]:
                full += f"\nassert {t}"
            harness = full
        jobs.append((harness, [], []))
        job_meta.append((p["id"], src))

    results = execute_batch(jobs)

    passed = []
    ri = 0
    task_rows = []
    for pid, src in job_meta:
        if src is None:
            task_rows.append({"task_id": pid, "verified": False,
                              "error": "extraction-failed"})
        else:
            r = results[ri]; ri += 1
            ok = bool(r.get("verified")) and not r.get("error")
            task_rows.append({"task_id": pid, "verified": ok,
                              "error": r.get("error")})
            if ok:
                passed.append(pid)

    n_pass = len(passed)
    n_total = len(problems)
    pass_pct = round(100.0 * n_pass / n_total, 1)

    del model
    torch.cuda.empty_cache()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP33-E3-GEMMA-E2B-SMOKE",
        "run_type": "PROPER",
        "ts": ts,
        "model": {
            "id": MODEL_ID,
            "path": MODEL_PATH,
            "n_params_b": round(n_params / 1e9, 3),
            "load_s": round(t_load, 1),
            "alloc_gib": round(alloc_gib, 2),
        },
        "runtime": {
            "python": sys.executable,
            "transformers": transformers.__version__,
            "gemma4_keys": gemma4_keys,
        },
        "eval": {
            "split": "validation",
            "n_tasks": n_total,
            "k": K,
            "temp": TEMP,
            "seed": SEED,
            "max_new_tokens": MAX_NEW,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s": PACE_S,
        },
        "results": {
            "n_pass": n_pass,
            "n_total": n_total,
            "pass_pct": pass_pct,
            "n_extract_fail": n_extract_fail,
            "gen_secs": gen_secs,
            "passed_task_ids": passed,
        },
        "task_rows": task_rows,
        "comparator": f"strict_harness={'yes' if use_strict else 'fallback'}",
        "flags": [
            "PROPER RUN: google/gemma-4-E2B-it in csi-eval venv",
            f"csi-eval transformers={transformers.__version__} (gemma4 supported)",
            "validation split = heldout eval surface (never used in SFT)",
            "smoke: k=1, N=10 — not a full floor measurement",
            "live run 12c050e7 NOT touched",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/fp33-e3-gemma-e2b-smoke-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_E3_GEMMA_E2B_SMOKE_DONE {out}")
    return receipt


if __name__ == "__main__":
    main()
