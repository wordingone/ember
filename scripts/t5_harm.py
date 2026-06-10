"""t5_harm.py — NC0 T5: harm suite (K3 input).

Measures general code capability (MBPP sanitized test, 50 problems) for
core_only vs core_meta. A regression beyond CI tolerance after a round =
HARM flag (the E1b lesson: wrong accumulation actively hurts novelty).

A generated program "passes" iff its module-level asserts (the MBPP tests)
raise nothing inside the sandbox. pass@k per problem; paired bootstrap CI.

Usage (wrapper): t5_harm.py --round N [--arms core_only core_meta]
Receipt: receipts/t5-r{N}-<ts>.json
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import extract_code, execute_batch  # noqa: E402
from t4_eval import bootstrap_ci, paired_delta_ci  # noqa: E402

ADAPTERS = f"{NC}/adapters"
RECEIPTS = f"{NC}/receipts"
N_PROBLEMS = 50
SOLVE_STUB = "\n\ndef solve(grid):\n    return [[0]]\n"  # satisfies the gadget


def load_mbpp(n):
    from datasets import load_dataset
    ds = load_dataset("google-research-datasets/mbpp", "sanitized",
                      split="test")
    return [{"id": int(r["task_id"]), "prompt": r["prompt"],
             "tests": list(r["test_list"]),
             "imports": list(r.get("test_imports") or [])}
            for r in list(ds)[:n]]


def problem_prompt(p):
    tests = "\n".join(p["tests"])
    return (f"Write a Python function for this task:\n{p['prompt']}\n\n"
            f"It must pass these tests:\n```python\n{tests}\n```\n"
            "Reply with ONE fenced python code block containing only the "
            "function definition(s). No prints, no explanations.")


def run_arm(arm, model_id, adapter, problems, k, batch_size, temp, seed):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.manual_seed(seed)
    tok = AutoTokenizer.from_pretrained(model_id, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(
        model_id, device_map="cuda", torch_dtype="auto")
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    model.eval()

    prompts, meta = [], []
    for p in problems:
        text = tok.apply_chat_template(
            [{"role": "user", "content": problem_prompt(p)}],
            tokenize=False, add_generation_prompt=True)
        for _ in range(k):
            prompts.append(text)
            meta.append(p["id"])

    completions = []
    t0 = time.time()
    for i in range(0, len(prompts), batch_size):
        chunk = prompts[i:i + batch_size]
        enc = tok(chunk, return_tensors="pt", padding=True).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, do_sample=True, temperature=temp,
                                 top_p=0.95, max_new_tokens=512,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        completions.extend(tok.batch_decode(out[:, enc.input_ids.shape[1]:],
                                            skip_special_tokens=True))
        print(f"[{arm}] {min(i + batch_size, len(prompts))}/{len(prompts)}",
              flush=True)

    by_id = {p["id"]: p for p in problems}
    jobs, job_ids = [], []
    for pid, comp in zip(meta, completions):
        src = extract_code(comp)
        if src is None:
            continue
        p = by_id[pid]
        harness = "\n".join(p["imports"]) + "\n" + src + "\n" + \
            "\n".join(p["tests"]) + SOLVE_STUB
        jobs.append((harness, [], []))
        job_ids.append(pid)
    results = execute_batch(jobs)

    passed = {p["id"]: 0 for p in problems}
    for pid, r in zip(job_ids, results):
        if r.get("verified") and not r.get("error"):
            passed[pid] = 1
    order = [p["id"] for p in problems]
    vals = [passed[i] for i in order]

    del model
    import torch as _t
    _t.cuda.empty_cache()
    return vals, {"pass_any_pct": round(100 * sum(vals) / len(vals), 2),
                  "ci95": bootstrap_ci(vals),
                  "gen_secs": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--arms", nargs="+", default=["core_only", "core_meta"])
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--temp", type=float, default=0.6)
    ap.add_argument("--seed", type=int, default=14)
    args = ap.parse_args()

    problems = load_mbpp(N_PROBLEMS)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"ticket": "NC0-T5", "round": args.round, "ts": ts,
               "n_problems": len(problems), "args": vars(args), "arms": {}}

    arm_vals = {}
    for arm in args.arms:
        adapter = f"{ADAPTERS}/r{args.round}" if arm == "core_meta" else None
        if adapter and not os.path.isdir(adapter):
            receipt["arms"][arm] = {"skipped": f"no adapter at {adapter}"}
            continue
        vals, summary = run_arm(arm, args.model, adapter, problems, args.k,
                                args.batch_size, args.temp, args.seed)
        arm_vals[arm] = vals
        receipt["arms"][arm] = summary

    if "core_only" in arm_vals and "core_meta" in arm_vals:
        receipt["delta_meta_minus_core_ci95"] = paired_delta_ci(
            arm_vals["core_meta"], arm_vals["core_only"])
        receipt["harm_flag"] = receipt["delta_meta_minus_core_ci95"][1] < 0

    os.makedirs(RECEIPTS, exist_ok=True)
    with open(f"{RECEIPTS}/t5-r{args.round}-{ts}.json", "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: receipt[k] for k in receipt
                      if k in ("arms", "delta_meta_minus_core_ci95",
                               "harm_flag")}, indent=2))
    print("T5_HARM_DONE")


if __name__ == "__main__":
    main()
