"""w1_mbpp.py — W-code world (MBPP-graded): measured floor probe + sample harvest.

World admission test per docs/formalization-v0.md (S7) + research/world-choice.md:
a training world is admitted only on a MEASURED floor (F > 0 at affordable k).
This script measures it: a core sampled on the MBPP sanitized TRAIN split,
verified by each task's own asserts inside the t1_probe sandbox (same rlimits,
timeout, import whitelist, receipts discipline).

Split discipline (K3 independence):
- sanitized/train (~120)     = training-world sampling pool (this probe)
- sanitized/validation (~43) = heldout eval surface (reserved for round evals)
- sanitized/test             = t5 harm suite ONLY — never touched by the loop

Per-sample rows persist src, so verified samples are harvestable as ledger
episodes (task keys `mbpp:<id>`) once W-code ledger ingest lands.
Receipt: receipts/w1-floor-<model-tag><suffix>-<ts>.json
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import argparse
import json
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (THROTTLE_S, decode_pacer, execute_batch,  # noqa: E402
                      extract_code, load_model)
from t4_eval import bootstrap_ci  # noqa: E402

RECEIPTS = f"{NC}/receipts"
SOLVE_STUB = "\n\ndef solve(grid):\n    return [[0]]\n"  # satisfies sandbox gadget


def load_split(split, n=None):
    from datasets import load_dataset
    ds = load_dataset("google-research-datasets/mbpp", "sanitized", split=split)
    rows = [{"id": int(r["task_id"]), "prompt": r["prompt"],
             "tests": list(r["test_list"]),
             "imports": list(r.get("test_imports") or [])}
            for r in ds]
    return rows[:n] if n else rows


def problem_prompt(p):
    tests = "\n".join(p["tests"])
    return (f"Write a Python function for this task:\n{p['prompt']}\n\n"
            f"It must pass these tests:\n```python\n{tests}\n```\n"
            "Reply with ONE fenced python code block containing only the "
            "function definition(s). No prints, no explanations.")


def generate_chat(model, tok, user_texts, batch_size, max_new, temp, seed):
    """Governed batched chat generation: decode pacer + inter-batch throttle.
    Returns completions in the SAME order as user_texts."""
    import torch

    torch.manual_seed(seed)
    texts = [tok.apply_chat_template([{"role": "user", "content": u}],
                                     tokenize=False, add_generation_prompt=True)
             for u in user_texts]
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    completions = [None] * len(texts)
    done = 0
    for i in range(0, len(order), batch_size):
        idxs = order[i:i + batch_size]
        enc = tok([texts[j] for j in idxs], return_tensors="pt",
                  padding=True).to("cuda")
        with torch.no_grad():
            out = model.generate(
                **enc, do_sample=True, temperature=temp, top_p=0.95,
                max_new_tokens=max_new, stopping_criteria=decode_pacer(),
                pad_token_id=tok.pad_token_id or tok.eos_token_id)
        dec = tok.batch_decode(out[:, enc.input_ids.shape[1]:],
                               skip_special_tokens=True)
        for j, c in zip(idxs, dec):
            completions[j] = c
        done += len(idxs)
        print(f"[w1] {done}/{len(texts)}", flush=True)
        time.sleep(THROTTLE_S)
    return completions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    ap.add_argument("--adapter", default=None,
                    help="optional adapter dir (governed merge in load_model)")
    ap.add_argument("--split", default="train")
    ap.add_argument("--n-tasks", type=int, default=0, help="0 = whole split")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-new", type=int, default=512)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--tag", default="", help="receipt tag (e.g. q15, q3)")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    problems = load_split(args.split, args.n_tasks or None)
    print(f"w1 floor probe: {len(problems)} tasks x k={args.k} "
          f"model={args.model} adapter={args.adapter}", flush=True)

    model, tok = load_model(args.model, adapter=args.adapter)
    user_texts, meta = [], []
    for p in problems:
        for _ in range(args.k):
            user_texts.append(problem_prompt(p))
            meta.append(p["id"])
    t0 = time.time()
    completions = generate_chat(model, tok, user_texts, args.batch_size,
                                args.max_new, args.temp, args.seed)
    gen_secs = round(time.time() - t0, 1)

    by_id = {p["id"]: p for p in problems}
    jobs, job_meta = [], []
    n_extract_fail = 0
    for pid, comp in zip(meta, completions):
        src = extract_code(comp)
        if src is None:
            n_extract_fail += 1
            job_meta.append((pid, None))
            continue
        p = by_id[pid]
        harness = "\n".join(p["imports"]) + "\n" + src + "\n" + \
            "\n".join(p["tests"]) + SOLVE_STUB
        jobs.append((harness, [], []))
        job_meta.append((pid, src))

    results = execute_batch(jobs)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tagpart = f"-{args.tag}" if args.tag else ""
    samples_path = f"{RECEIPTS}/w1-floor{tagpart}-{ts}-samples.jsonl"

    passed_by_task = {p["id"]: 0 for p in problems}
    samples_by_task = {p["id"]: 0 for p in problems}
    ri = 0
    os.makedirs(RECEIPTS, exist_ok=True)
    with open(samples_path, "w") as sf:
        for pid, src in job_meta:
            if src is None:
                row = {"task": f"mbpp:{pid}", "verified": False,
                       "error": "extraction-failed", "src": None}
            else:
                r = results[ri]
                ri += 1
                ok = bool(r.get("verified")) and not r.get("error")
                row = {"task": f"mbpp:{pid}", "verified": ok,
                       "error": r.get("error"), "src": src}
                if ok:
                    passed_by_task[pid] += 1
            samples_by_task[pid] += 1
            sf.write(json.dumps(row) + "\n")

    order = [p["id"] for p in problems]
    task_pass = [1 if passed_by_task[i] > 0 else 0 for i in order]
    n_verified_samples = sum(passed_by_task.values())
    receipt = {
        "ticket": "W1-FLOOR", "ts": ts, "args": vars(args),
        "n_tasks": len(problems), "k": args.k,
        "feed_tasks": sum(task_pass),
        "feed_pct": round(100 * sum(task_pass) / len(task_pass), 2),
        "feed_ci95": bootstrap_ci(task_pass),
        "verified_samples": n_verified_samples,
        "verified_sample_pct": round(
            100 * n_verified_samples / len(job_meta), 2),
        "extraction_fail": n_extract_fail,
        "gen_secs": gen_secs,
        "samples_file": os.path.basename(samples_path),
        "split_discipline": "train=world pool, validation=heldout, "
                            "test=t5-harm-only",
    }
    with open(f"{RECEIPTS}/w1-floor{tagpart}-{ts}.json", "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: receipt[k] for k in
                      ("n_tasks", "k", "feed_tasks", "feed_pct", "feed_ci95",
                       "verified_samples", "verified_sample_pct",
                       "extraction_fail")}, indent=2))
    print("W1_FLOOR_DONE")


if __name__ == "__main__":
    main()
