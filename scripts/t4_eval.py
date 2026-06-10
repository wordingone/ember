"""t4_eval.py — NC0 T4: four-arm held-out evaluation.

Arms (each at identical inference budget on the SAME eval-task subset):
  core_only     frozen base
  core_meta     base + adapters/r{N}
  control       base + adapters/r{N}-control (matched-budget unverified SFT)
  context_only  frozen base + few-shot verified episodes from the ledger

Eval split = ARC-AGI-1 evaluation/ (never trained on, never verified against).
Per eval task: "verified" = passes the task's own train pairs; "solved" =
passes the held test pair (the headline). Paired bootstrap CIs over tasks.

Usage (wrapper): t4_eval.py --round N [--arms ...] [--n-tasks 100] [--k 8]
                 [--seed 14]
Receipt: receipts/t4-r{N}-seed{S}-<ts>.json (+ per-sample JSONL)
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
# Loop is local-only: weights cached in HF_HOME; network reach = loud failure.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (MAX_PROMPT_TOKENS, THROTTLE_S, decode_pacer,  # noqa: E402
                      extract_code, execute_batch, load_model, load_tasks,
                      task_prompt)

ARC_EVAL = "/mnt/b/M/the-search/incoming/arc-agi1-visa/ARC-AGI/data/evaluation"
# Second held-out surface: training only ever touches ARC-1 training tasks,
# so gains here = transfer beyond the seed distribution (same JSON format).
ARC2_EVAL = "/mnt/b/M/avir/leo/state/nc-ladder/vendor/ARC-AGI-2/data/evaluation"
SURFACES = {"arc1": ARC_EVAL, "arc2": ARC2_EVAL}
LEDGER = f"{NC}/ledger/episodes.jsonl"
ADAPTERS = f"{NC}/adapters"
RECEIPTS = f"{NC}/receipts"
N_FEWSHOT = 2


def fewshot_messages():
    """Two shortest verified episodes from the ledger as worked examples."""
    if not os.path.exists(LEDGER):
        return []
    train_tasks = {t["id"]: t for t in load_tasks(
        "/mnt/b/M/the-search/incoming/arc-agi1-visa/ARC-AGI/data/training")}
    rows = []
    with open(LEDGER) as f:
        for line in f:
            r = json.loads(line)
            t = train_tasks.get(r["task"])
            if t:
                rows.append((len(task_prompt(t)) + len(r["src"]), t, r["src"]))
    rows.sort(key=lambda x: x[0])
    msgs = []
    for _, t, src in rows[:N_FEWSHOT]:
        msgs.append({"role": "user", "content": task_prompt(t)})
        msgs.append({"role": "assistant", "content": f"```python\n{src}\n```"})
    return msgs


def run_arm(arm, model_id, adapter, tasks, k, batch_size, max_new, temp, seed,
            prefix_msgs):
    import torch

    torch.manual_seed(seed)
    # load via t1_probe.load_model so the resource governor (VRAM fraction
    # cap + free-margin assert, post-crash 2026-06-10) applies to t4 too —
    # the crashed 0670e3ec used this inline load path, ungoverned.
    model, tok = load_model(model_id, adapter=adapter)

    prompts, meta = [], []
    for t in tasks:
        msgs = list(prefix_msgs) + [{"role": "user", "content": task_prompt(t)}]
        text = tok.apply_chat_template(msgs, tokenize=False,
                                       add_generation_prompt=True)
        n_tok = len(tok(text).input_ids)
        if n_tok > MAX_PROMPT_TOKENS + 3000:
            continue
        for _ in range(k):
            prompts.append(text)
            meta.append(t["id"])

    # Length-sort so each batch pads to a near neighbor, not the global
    # longest — halves peak activation on mixed-length ARC eval prompts
    # (same harness precedent as t1 smoke-v2's length-sorted batches).
    order = sorted(range(len(prompts)), key=lambda i: len(prompts[i]))
    prompts = [prompts[i] for i in order]
    meta = [meta[i] for i in order]

    completions, t0 = [], time.time()
    for i in range(0, len(prompts), batch_size):
        chunk = prompts[i:i + batch_size]
        enc = tok(chunk, return_tensors="pt", padding=True).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, do_sample=True, temperature=temp,
                                 top_p=0.95, max_new_tokens=max_new,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id,
                                 stopping_criteria=decode_pacer())
        completions.extend(tok.batch_decode(out[:, enc.input_ids.shape[1]:],
                                            skip_special_tokens=True))
        print(f"[{arm}] {min(i + batch_size, len(prompts))}/{len(prompts)}",
              flush=True)
        time.sleep(THROTTLE_S)  # headroom rule: GPU never pegged wall-to-wall
    secs = time.time() - t0

    by_id = {t["id"]: t for t in tasks}
    jobs, job_ids = [], []
    for task_id, comp in zip(meta, completions):
        src = extract_code(comp)
        if src is None:
            continue
        t = by_id[task_id]
        jobs.append((src, t["train"], t["test"]))
        job_ids.append(task_id)
    results = execute_batch(jobs)

    per_task = {t["id"]: {"verified": 0, "solved": 0} for t in tasks}
    rows = []
    for task_id, (src, _, _), r in zip(job_ids, jobs, results):
        rows.append({"arm": arm, "task": task_id,
                     "verified": bool(r.get("verified")),
                     "solved": bool(r.get("solved")),
                     "error": r.get("error")})
        per_task[task_id]["verified"] |= bool(r.get("verified"))
        per_task[task_id]["solved"] |= bool(r.get("solved"))

    del model
    torch.cuda.empty_cache()
    return per_task, rows, {"gen_secs": round(secs, 1),
                            "programs": len(jobs)}


def bootstrap_ci(values, n=10000, seed=7):
    rng = random.Random(seed)
    m = len(values)
    stats = sorted(sum(rng.choices(values, k=m)) / m for _ in range(n))
    return [round(100 * stats[int(n * q)], 2) for q in (0.025, 0.975)]


def paired_delta_ci(a, b, n=10000, seed=7):
    rng = random.Random(seed)
    pairs = list(zip(a, b))
    m = len(pairs)
    deltas = sorted(
        sum(x - y for x, y in rng.choices(pairs, k=m)) / m for _ in range(n))
    return [round(100 * deltas[int(n * q)], 2) for q in (0.025, 0.975)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--arms", nargs="+",
                    default=["core_only", "core_meta", "control", "context_only"])
    ap.add_argument("--n-tasks", type=int, default=100)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-new", type=int, default=768)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--surface", default="arc1", choices=sorted(SURFACES))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    all_tasks = load_tasks(SURFACES[args.surface])
    tasks = rng.sample(all_tasks, min(args.n_tasks, len(all_tasks)))
    task_order = [t["id"] for t in tasks]

    arm_cfg = {
        "core_only": (None, []),
        "core_meta": (f"{ADAPTERS}/r{args.round}", []),
        "control": (f"{ADAPTERS}/r{args.round}-control", []),
        "context_only": (None, fewshot_messages()),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"ticket": "NC0-T4", "round": args.round, "ts": ts,
               "surface": args.surface,
               "args": {k: v for k, v in vars(args).items() if k != "arms"},
               "arms": {}}
    samples_path = (f"{RECEIPTS}/t4-r{args.round}-{args.surface}"
                    f"-seed{args.seed}-{ts}-samples.jsonl")
    os.makedirs(RECEIPTS, exist_ok=True)

    arm_solved = {}
    with open(samples_path, "w") as sf:
        for arm in args.arms:
            adapter, prefix = arm_cfg[arm]
            if adapter and not os.path.isdir(adapter):
                receipt["arms"][arm] = {"skipped": f"no adapter at {adapter}"}
                continue
            per_task, rows, info = run_arm(
                arm, args.model, adapter, tasks, args.k, args.batch_size,
                args.max_new, args.temp, args.seed, prefix)
            for row in rows:
                sf.write(json.dumps(row) + "\n")
            solved = [per_task[t]["solved"] for t in task_order]
            verified = [per_task[t]["verified"] for t in task_order]
            arm_solved[arm] = solved
            receipt["arms"][arm] = {
                **info,
                "solve_any_pct": round(100 * sum(solved) / len(solved), 2),
                "solve_ci95": bootstrap_ci(solved),
                "verify_any_pct": round(100 * sum(verified) / len(verified), 2),
            }

    if "core_meta" in arm_solved and "core_only" in arm_solved:
        receipt["delta_meta_minus_core_ci95"] = paired_delta_ci(
            arm_solved["core_meta"], arm_solved["core_only"])
    if "core_meta" in arm_solved and "control" in arm_solved:
        receipt["delta_meta_minus_control_ci95"] = paired_delta_ci(
            arm_solved["core_meta"], arm_solved["control"])

    path = f"{RECEIPTS}/t4-r{args.round}-{args.surface}-seed{args.seed}-{ts}.json"
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: v for k, v in receipt.items()
                      if k in ("arms", "delta_meta_minus_core_ci95",
                               "delta_meta_minus_control_ci95")}, indent=2))
    print("T4_EVAL_DONE")


if __name__ == "__main__":
    main()
