# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

NC = "<local-path>"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (THROTTLE_S, decode_pacer, execute_batch,  # noqa: E402
                      extract_code, load_model)
from t4_eval import bootstrap_ci, paired_delta_ci  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

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

    torch.manual_seed(seed)
    # Governed load (post-crash 2026-06-10): VRAM fraction cap + margin
    # assert + adapter merge_and_unload — replaces the pre-governor inline
    # load this script was built with.
    model, tok = load_model(model_id, adapter=adapter)

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
                                 stopping_criteria=decode_pacer(),
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        completions.extend(tok.batch_decode(out[:, enc.input_ids.shape[1]:],
                                            skip_special_tokens=True))
        print(f"[{arm}] {min(i + batch_size, len(prompts))}/{len(prompts)}",
              flush=True)
        time.sleep(THROTTLE_S)

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
    ap.add_argument("--tag-suffix",
                    default=os.environ.get("EMBER_ADAPTER_TAG", ""),
                    help="adapter namespace suffix (e.g. -q3) matching t2_round")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore

    problems = load_mbpp(N_PROBLEMS)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    from receipt_fp import args_fingerprint  # eng #10
    receipt = {"ticket": "NC0-T5", "round": args.round, "ts": ts,
               "args_fp": args_fingerprint(vars(args)),
               "n_problems": len(problems), "args": vars(args), "arms": {}}

    arm_vals = {}
    for arm in args.arms:
        adapter = (f"{ADAPTERS}/r{args.round}{args.tag_suffix}"
                   if arm == "core_meta" else None)
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
    checked_write(f"{RECEIPTS}/t5-r{args.round}{args.tag_suffix}-{ts}.json",
                  receipt)
    print(json.dumps({k: receipt[k] for k in receipt
                      if k in ("arms", "delta_meta_minus_core_ci95",
                               "harm_flag")}, indent=2))
    print("T5_HARM_DONE")


if __name__ == "__main__":
    main()
