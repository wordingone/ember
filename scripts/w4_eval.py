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
try:
    from stats_exact import build_exact_block as _build_exact_block  # noqa: E402
except ImportError:
    _build_exact_block = None
from receipt_write import checked_write  # noqa: E402

RECEIPTS = f"{NC}/receipts"


def filter_problems_by_ids(problems, task_ids_file):
    """Filter problems to exact task ids from file (one per line, stripped).
    If file given, returns filtered list (fail-closed on absent ids).
    If file is None, returns problems unchanged (backward-compatible).
    Expects each line to be 'NNN' or 'mbpp:NNN'; strips 'mbpp:' prefix.
    """
    if task_ids_file is None:
        return problems

    requested_ids = set()
    with open(task_ids_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                # Strip 'mbpp:' prefix if present
                if line.startswith("mbpp:"):
                    line = line[5:]
                try:
                    requested_ids.add(int(line))
                except ValueError:
                    raise SystemExit(
                        f"w4: bad task id in {task_ids_file}: {line!r} "
                        f"(want NNN or mbpp:NNN)")

    # Check all requested ids are present
    problem_ids = {p["id"] for p in problems}
    missing = requested_ids - problem_ids
    if missing:
        raise SystemExit(
            f"w4: requested task ids not in split: {sorted(missing)}")

    # Filter to exact subset
    filtered = [p for p in problems if p["id"] in requested_ids]
    return filtered


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


def control_pairs(arm_vec):
    """Every non-base/non-control arm paired against control. Pure.

    eng #151 (G1 live audit, mail 14529): the control comparison was
    guarded by a literal 'trained' arm name, so the r2 five-arm record
    (base/sft/mtp/grpo/control) produced NO control deltas — and STATE's
    decision rule needs arm-minus-base AND arm-minus-control per trained
    arm. This is the single source of the pairing rule, used by both the
    bootstrap deltas block and the exact-method paired outcomes. The r1
    literal key is subsumed by construction: an arm named 'trained'
    still yields trained_minus_control_ci95.
    """
    if "control" not in arm_vec:
        return {}
    return {f"{name}_minus_control_ci95": (arm_vec[name], arm_vec["control"])
            for name in arm_vec if name not in ("base", "control")}


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
    ap.add_argument("--task-ids-file", default=None,
                    help="optional file: one task id per line (NNN or mbpp:NNN); "
                         "if given, filter problems to exact subset")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    arms = parse_arms(args.arm)
    problems = load_split(args.split, args.n_tasks or None)
    problems = filter_problems_by_ids(problems, args.task_ids_file)
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
    for key, (a, b) in control_pairs(arm_vec).items():
        receipt["deltas"][key] = paired_delta_ci(a, b)
    # Additive exact-method sub-block (Wilson + Newcombe + MDE); bootstrap and
    # all existing fields are unchanged; early-stop logic not present in w4.
    if _build_exact_block is not None and len(problems) > 0:
        _succ_by_arm = {name: sum(arm_vec[name]) for name in arm_vec}
        _paired_outcomes = {}
        if "base" in arm_vec:
            for name in arm_vec:
                if name != "base":
                    _paired_outcomes[f"{name}_minus_base_ci95"] = (
                        arm_vec[name], arm_vec["base"])
        _paired_outcomes.update(control_pairs(arm_vec))
        receipt["exact"] = _build_exact_block(
            _succ_by_arm, _paired_outcomes, len(problems))

    checked_write(f"{RECEIPTS}/w4-eval{tagpart}-{ts}.json", receipt)
    print(json.dumps({"arms": arm_stats, "deltas": receipt["deltas"]},
                     indent=2))
    print("W4_EVAL_DONE")


if __name__ == "__main__":
    main()
