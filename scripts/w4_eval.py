"""w4_eval.py — W-code heldout gate: multi-arm eval on MBPP sanitized/validation.

The G1/G2 surface for W-code rounds (formalization S4): arms run sequentially
in one process (governed load per arm, base arm = no adapter), each sampled at
k on the VALIDATION split (heldout — never in the world pool; test stays
t5-harm-only), verified by each task's own asserts in the t1_probe sandbox.
Paired bootstrap deltas between every named arm and 'base', and between
'trained' and 'control' when both present.

Arms are CLI-declared so round wiring never edits this file:
  --arm base= --arm trained=/path/to/adapters/r2-w --arm control=/path/to/...
(name=adapterpath; empty path = no adapter.)

Receipt: receipts/w4-eval-<tag>-<ts>.json + per-sample jsonl (src persisted,
sampler provenance per row — same harvestable shape as w1).
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
from t1_probe import execute_batch, extract_code, load_model  # noqa: E402
from t4_eval import bootstrap_ci, paired_delta_ci  # noqa: E402
from w1_mbpp import SOLVE_STUB, generate_chat, load_split, problem_prompt  # noqa: E402

RECEIPTS = f"{NC}/receipts"


def parse_arms(specs):
    """['base=', 'trained=/x'] -> [('base', None), ('trained', '/x')]. Pure."""
    arms = []
    for spec in specs:
        name, _, path = spec.partition("=")
        if not name:
            raise SystemExit(f"w4: bad --arm spec {spec!r} (want name=path)")
        arms.append((name, path or None))
    names = [n for n, _ in arms]
    if len(set(names)) != len(names):
        raise SystemExit(f"w4: duplicate arm names in {names}")
    return arms


def task_pass_vector(rows, order):
    """Per-sample rows -> pass-any-per-task vector aligned to `order`. Pure."""
    passed = {tid: 0 for tid in order}
    for r in rows:
        if r["verified"]:
            passed[r["tid"]] = 1
    return [passed[tid] for tid in order]


def run_arm(name, adapter, model_id, problems, args):
    model, tok = load_model(model_id, adapter=adapter)
    user_texts, meta = [], []
    for p in problems:
        for _ in range(args.k):
            user_texts.append(problem_prompt(p))
            meta.append(p["id"])
    t0 = time.time()
    completions = generate_chat(model, tok, user_texts, args.batch_size,
                                args.max_new, args.temp, args.seed)
    gen_secs = round(time.time() - t0, 1)
    del model, tok
    import gc
    import torch
    gc.collect()
    torch.cuda.empty_cache()

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

    sampler = f"{model_id}+{adapter}" if adapter else model_id
    rows, ri = [], 0
    for pid, src in job_meta:
        if src is None:
            rows.append({"arm": name, "tid": pid, "verified": False,
                         "error": "extraction-failed", "src": None,
                         "sampler": sampler})
            continue
        r = results[ri]
        ri += 1
        ok = bool(r.get("verified")) and not r.get("error")
        rows.append({"arm": name, "tid": pid, "verified": ok,
                     "error": r.get("error"), "src": src, "sampler": sampler})
    return rows, {"gen_secs": gen_secs, "extraction_fail": n_extract_fail,
                  "programs": len(jobs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--arm", action="append", required=True,
                    help="name=adapterpath (empty path = base); repeatable")
    ap.add_argument("--split", default="validation")
    ap.add_argument("--n-tasks", type=int, default=0, help="0 = whole split")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-new", type=int, default=512)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--tag", default="", help="receipt tag (e.g. r2w-q3)")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    arms = parse_arms(args.arm)
    problems = load_split(args.split, args.n_tasks or None)
    order = [p["id"] for p in problems]
    print(f"w4 heldout eval: {len(problems)} tasks x k={args.k} "
          f"arms={[n for n, _ in arms]} model={args.model}", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tagpart = f"-{args.tag}" if args.tag else ""
    samples_path = f"{RECEIPTS}/w4-eval{tagpart}-{ts}-samples.jsonl"
    os.makedirs(RECEIPTS, exist_ok=True)

    arm_vec, arm_stats = {}, {}
    with open(samples_path, "w", encoding="utf-8", newline="\n") as sf:
        for name, adapter in arms:
            print(f"[w4] arm {name} adapter={adapter}", flush=True)
            rows, stats = run_arm(name, adapter, args.model, problems, args)
            for r in rows:
                sf.write(json.dumps(r) + "\n")
            sf.flush()
            vec = task_pass_vector(rows, order)
            arm_vec[name] = vec
            arm_stats[name] = {
                "pass_any_pct": round(100 * sum(vec) / len(vec), 2),
                "pass_ci95": bootstrap_ci(vec), **stats}

    receipt = {"ticket": "W4-EVAL", "ts": ts, "args": vars(args),
               "n_tasks": len(problems), "k": args.k, "arms": arm_stats,
               "deltas": {}, "samples_file": os.path.basename(samples_path),
               "split_discipline": "validation=heldout only; train=world pool; "
                                   "test=t5-harm-only"}
    if "base" in arm_vec:
        for name in arm_vec:
            if name != "base":
                receipt["deltas"][f"{name}_minus_base_ci95"] = \
                    paired_delta_ci(arm_vec[name], arm_vec["base"])
    if "trained" in arm_vec and "control" in arm_vec:
        receipt["deltas"]["trained_minus_control_ci95"] = \
            paired_delta_ci(arm_vec["trained"], arm_vec["control"])

    with open(f"{RECEIPTS}/w4-eval{tagpart}-{ts}.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({"arms": arm_stats, "deltas": receipt["deltas"]},
                     indent=2))
    print("W4_EVAL_DONE")


if __name__ == "__main__":
    main()
