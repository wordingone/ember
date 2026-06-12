"""fp33_a3ii_gsm8k_eval.py — GSM8K-200 greedy exact-match eval harness.

A3-ii leg of fp-33 surpass-prereg-v1 (FROZEN). First 200 problems from
GSM8K test split, greedy decode, exact-match numeric answer extraction.
Paired-run capable: --model selects the evaluated model; same seat for both
sides of a paired comparison.

Runs under csi-eval venv (transformers 5.11.0). Re-exec pattern from E3b.

Receipts:
  receipts/fp33-a3ii-gsm8k-<ts>.jsonl  (per-task pass/fail + extracted)
  receipts/fp33-a3ii-gsm8k-<ts>.json   (summary + harness sha)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CSIEVAL_PYTHON = "/mnt/c/Users/Admin/.venvs/csi-eval/bin/python"
REEXEC_FLAG    = "FP33_A3II_REEXEC"

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")

DEFAULT_MODEL = "google/gemma-4-E2B-it"
N_PROBLEMS    = 200
MAX_NEW_TOK   = 512

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

# GSM8K: reference answer ends with "#### <number>"
ANSWER_RE = re.compile(r"####\s*([\d,]+)")


def _extract_answer(text: str) -> str | None:
    """Extract the numeric answer from model or reference text."""
    m = ANSWER_RE.search(text)
    if m:
        return m.group(1).replace(",", "").strip()
    # Fallback: last standalone integer in the text
    nums = re.findall(r"\b(\d+)\b", text)
    return nums[-1] if nums else None


def _harness_sha() -> str:
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _parse_args():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--selftest", action="store_true")
    return p.parse_args()


def run_eval(model_id: str):
    import torch
    from datasets import load_dataset
    from transformers import AutoProcessor, AutoModelForCausalLM

    print(f"[A3ii] model: {model_id}", flush=True)
    print(f"[A3ii] torch: {torch.__version__}", flush=True)

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    total_gib = total_b / (1 << 30)
    print(f"[A3ii] VRAM: {free_gib:.2f}/{total_gib:.2f} GiB free", flush=True)
    if free_gib < MARGIN_GIB:
        raise RuntimeError(f"[A3ii] VRAM margin violated: {free_gib:.2f} GiB")

    # Load dataset
    ds = load_dataset("openai/gsm8k", "main", split="test")
    tasks = list(ds)[:N_PROBLEMS]
    print(f"[A3ii] {len(tasks)} tasks loaded from GSM8K test", flush=True)

    # Load model
    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=torch.bfloat16,
        device_map="cuda",
    )
    model.eval()
    load_s = round(time.perf_counter() - t0, 1)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[A3ii] loaded in {load_s}s, {n_params / 1e9:.3f}B params", flush=True)

    alloc_gib = torch.cuda.memory_allocated() / (1 << 30)
    free_b2, _ = torch.cuda.mem_get_info()
    if free_b2 / (1 << 30) < MARGIN_GIB:
        raise RuntimeError(f"[A3ii] post-load VRAM margin violated")

    harness_sha = _harness_sha()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = os.path.join(RECEIPTS, f"fp33-a3ii-gsm8k-{ts}.jsonl")
    json_path  = os.path.join(RECEIPTS, f"fp33-a3ii-gsm8k-{ts}.json")

    os.makedirs(RECEIPTS, exist_ok=True)

    n_pass = n_extract_fail_ref = n_extract_fail_model = 0
    task_rows = []

    with open(jsonl_path, "w", encoding="utf-8", newline="\n") as jl:
        for i, task in enumerate(tasks):
            question = task["question"]
            ref_text = task["answer"]
            ref_ans  = _extract_answer(ref_text)
            if ref_ans is None:
                n_extract_fail_ref += 1

            # Format prompt via chat template
            messages = [{"role": "user", "content": question}]
            prompt = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = processor(prompt, return_tensors="pt").to("cuda")

            with torch.no_grad():
                out_ids = model.generate(
                    **inputs,
                    do_sample=False,
                    max_new_tokens=MAX_NEW_TOK,
                    pad_token_id=processor.tokenizer.eos_token_id,
                )

            # Decode only the new tokens
            gen_ids = out_ids[0, inputs["input_ids"].shape[-1]:]
            gen_text = processor.decode(gen_ids, skip_special_tokens=True)
            model_ans = _extract_answer(gen_text)

            if model_ans is None:
                n_extract_fail_model += 1

            verified = (
                ref_ans is not None
                and model_ans is not None
                and ref_ans == model_ans
            )
            if verified:
                n_pass += 1

            row = {
                "task_id":    i,
                "question":   question[:200],
                "ref_answer": ref_ans,
                "model_answer": model_ans,
                "verified":   verified,
                "error":      None,
            }
            task_rows.append({"task_id": i, "verified": verified, "error": None})
            jl.write(json.dumps(row) + "\n")

            if (i + 1) % 10 == 0:
                print(f"[A3ii] {i + 1}/{len(tasks)} pass={n_pass}", flush=True)

            time.sleep(PACE_S)

    pass_pct = round(n_pass / len(tasks) * 100, 2)
    print(f"[A3ii] pass: {n_pass}/{len(tasks)} ({pass_pct}%)", flush=True)

    receipt = {
        "ticket":   "FP33-A3II-GSM8K-EVAL",
        "ts":       ts,
        "harness_sha": harness_sha,
        "model": {
            "id":       model_id,
            "n_params_b": round(n_params / 1e9, 3),
            "load_s":   load_s,
            "alloc_gib": round(alloc_gib, 2),
        },
        "runtime": {
            "python":       sys.executable,
            "torch":        torch.__version__,
            "device":       torch.cuda.get_device_name(0),
        },
        "eval": {
            "dataset":       "openai/gsm8k",
            "config":        "main",
            "split":         "test",
            "n_problems":    len(tasks),
            "do_sample":     False,
            "max_new_tokens": MAX_NEW_TOK,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s": PACE_S,
        },
        "results": {
            "n_pass":               n_pass,
            "n_total":              len(tasks),
            "pass_pct":             pass_pct,
            "n_extract_fail_ref":   n_extract_fail_ref,
            "n_extract_fail_model": n_extract_fail_model,
        },
        "task_rows": task_rows,
        "receipts": {
            "jsonl": jsonl_path,
            "json":  json_path,
        },
        "flags": [
            "greedy decode: do_sample=False",
            "answer extraction: #### pattern, fallback last-integer",
            "paired-run capable: --model selects evaluated model",
            "live run 12c050e7 NOT touched",
        ],
    }

    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_A3II_GSM8K_EVAL_DONE {json_path}")
    return receipt


def _selftest():
    # Pure-logic: verify extraction + harness_sha works without GPU
    assert _extract_answer("...some work\n#### 42") == "42"
    assert _extract_answer("The answer is #### 1,234") == "1234"
    assert _extract_answer("...no marker but ends with 99") == "99"
    assert _extract_answer("no numbers here") is None
    sha = _harness_sha()
    assert len(sha) == 64
    print(f"[A3ii] harness_sha: {sha}")
    print("FP33_A3II_GSM8K_EVAL_SELFTEST_PASS")


def _reexec():
    if os.environ.get(REEXEC_FLAG):
        return  # already in correct venv
    if sys.executable == CSIEVAL_PYTHON:
        return  # running under csi-eval already
    print(f"[A3ii] re-exec under csi-eval Python: {CSIEVAL_PYTHON}", flush=True)
    os.environ[REEXEC_FLAG] = "1"
    os.execv(CSIEVAL_PYTHON, [CSIEVAL_PYTHON] + sys.argv)


if __name__ == "__main__":
    args = _parse_args()
    if args.selftest:
        _selftest()
    else:
        _reexec()
        run_eval(args.model)
