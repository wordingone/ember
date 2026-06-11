"""t1c_contamination.py — NC0 t1c: is ARC-AGI-1 memorized by the base model?

Both ARC-AGI-1 splits are on GitHub since 2019 and plausibly in Qwen's
pretraining data. Our heldout surface (t4, evaluation split) is only
trustworthy if the model can't reproduce it from weights. Two probes:

1. CONTINUATION (primary, high sensitivity): feed the task file's verbatim
   JSON text truncated right before the SECOND train pair's output grid,
   greedy-decode, score byte-exact reproduction of that grid. Arms:
     eval-orig   evaluation split, original bytes
     eval-perm   same tasks, colors 1-9 permuted per task (0 fixed) — a
                 rule-preserving relabel: a reasoner matches orig and perm
                 equally, memorization matches only orig
     train-orig  training split reference (also public; calibrates probe)
   Signal: exact(eval-orig) - exact(eval-perm). ~0 → heldout trusted.

2. ID-RECALL (secondary, low sensitivity / decisive if positive): ask the
   model to reproduce the eval task file from its filename alone; count
   verbatim grid hits. Weak retrieval cue — negative says little, any hit
   is unambiguous contamination.

Receipts: receipts/t1c-contamination-<ts>.json (+ per-row JSONL)
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (RECEIPTS, THROTTLE_S, decode_pacer,  # noqa: E402
                      load_model)
from receipt_write import checked_write  # noqa: E402

ARC_ROOT = "/mnt/b/M/the-search/incoming/arc-agi1-visa/ARC-AGI/data"


def task_files(split, n, seed):
    d = f"{ARC_ROOT}/{split}"
    names = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    rng = random.Random(seed)
    rng.shuffle(names)
    return [os.path.join(d, f) for f in names[:n]]


# ─── probe 1: raw-prefix continuation ────────────────────────────────────────

def split_at_second_output(text):
    """Prefix ends right after the 2nd '"output": ' key; target is that
    output grid's text. Returns (prefix, target) or None."""
    hits = [m.end() for m in re.finditer(r'"output":\s*', text)]
    if len(hits) < 2:
        return None
    cut = hits[1]
    m = re.match(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]", text[cut:])
    if not m:
        return None
    return text[:cut], m.group(0)


def permute_colors(text, seed):
    """Digits 1-9 shuffled (0 = background fixed), applied to raw text —
    grids are the only digit runs in these files."""
    rng = random.Random(seed)
    perm = list("123456789")
    rng.shuffle(perm)
    table = {str(i + 1): perm[i] for i in range(9)}
    return re.sub(r"[1-9]", lambda m: table[m.group(0)], text)


def continuation_arm(model, tok, files, arm, perm_seed=None):
    import torch
    rows = []
    for path in files:
        with open(path) as f:
            text = f.read()
        # 2nd '"output":' in file order is train[1] ONLY when >=2 train
        # pairs exist; with 1 train pair it would silently be the TEST
        # output. Enforce the guard the split function can't see.
        if len(json.loads(text)["train"]) < 2:
            rows.append({"task": os.path.basename(path)[:-5], "arm": arm,
                         "skipped": "needs >=2 train pairs"})
            continue
        if perm_seed is not None:
            # stable per-task offset (builtin hash() is per-process random)
            off = int(hashlib.sha1(path.encode()).hexdigest()[:6], 16)
            text = permute_colors(text, perm_seed + off)
        sp = split_at_second_output(text)
        if sp is None:
            rows.append({"task": os.path.basename(path)[:-5], "arm": arm,
                         "skipped": "no parseable 2nd output grid"})
            continue
        prefix, target = sp
        enc = tok(prefix, return_tensors="pt").to("cuda")
        n_target = len(tok(target).input_ids)
        with torch.no_grad():
            out = model.generate(
                **enc, do_sample=False, max_new_tokens=n_target + 16,
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
                stopping_criteria=decode_pacer())
        cont = tok.decode(out[0, enc.input_ids.shape[1]:],
                          skip_special_tokens=True)
        squeeze = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
        exact = squeeze(cont).startswith(squeeze(target))
        rows.append({"task": os.path.basename(path)[:-5], "arm": arm,
                     "exact": bool(exact), "target_chars": len(target),
                     "cont_head": cont[:120]})
        time.sleep(THROTTLE_S)  # headroom rule
    return rows


# ─── probe 2: id-recall ──────────────────────────────────────────────────────

def norm_grids_in_text(text):
    grids = set()
    for block in re.findall(r"\[\s*\[[\d,\s\[\]]+\]\s*\]", text):
        normalized = re.sub(r"\s+", "", block)
        if len(normalized) >= 12:  # ignore trivial 1x1/1x2
            grids.add(normalized)
    return grids


def id_recall_arm(model, tok, files):
    import torch
    rows = []
    for path in files:
        name = os.path.basename(path)
        with open(path) as f:
            task = json.load(f)
        true_grids = set()
        for split in ("train", "test"):
            for p in task[split]:
                true_grids.add(re.sub(r"\s+", "", json.dumps(p["input"])))
                true_grids.add(re.sub(r"\s+", "", json.dumps(p["output"])))
        prompt = (
            f"You have memorized the ARC-AGI benchmark (fchollet/ARC-AGI on "
            f"GitHub). Reproduce the exact JSON content of the evaluation "
            f"task file `{name}` — its train and test input/output grids.")
        text = tok.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False, add_generation_prompt=True)
        enc = tok(text, return_tensors="pt").to("cuda")
        with torch.no_grad():
            out = model.generate(
                **enc, do_sample=False, max_new_tokens=512,
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
                stopping_criteria=decode_pacer())
        gen = tok.decode(out[0, enc.input_ids.shape[1]:],
                         skip_special_tokens=True)
        produced = norm_grids_in_text(gen)
        hits = sorted(g for g in produced if g in true_grids)
        rows.append({"task": name[:-5], "arm": "id-recall",
                     "grids_produced": len(produced),
                     "verbatim_hits": len(hits), "hit_examples": hits[:2]})
        time.sleep(THROTTLE_S)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--n-tasks", type=int, default=50)
    ap.add_argument("--n-recall", type=int, default=20)
    ap.add_argument("--seed", type=int, default=14)
    args = ap.parse_args()

    model, tok = load_model(args.model)
    eval_files = task_files("evaluation", args.n_tasks, args.seed)
    arms = [
        ("eval-orig", eval_files, None),
        ("eval-perm", eval_files, args.seed),
        ("train-orig", task_files("training", args.n_tasks, args.seed), None),
    ]
    all_rows, summary = [], {}
    for arm, files, perm in arms:
        rows = continuation_arm(model, tok, files, arm, perm_seed=perm)
        all_rows.extend(rows)
        scored = [r for r in rows if "exact" in r]
        summary[arm] = {
            "n": len(scored),
            "exact": sum(r["exact"] for r in scored),
            "exact_pct": round(100 * sum(r["exact"] for r in scored)
                               / max(len(scored), 1), 2)}
        print(f"{arm}: {summary[arm]}", flush=True)

    recall_rows = id_recall_arm(model, tok, eval_files[:args.n_recall])
    all_rows.extend(recall_rows)
    summary["id-recall"] = {
        "n": len(recall_rows),
        "tasks_with_verbatim_hits": sum(
            1 for r in recall_rows if r["verbatim_hits"] > 0)}
    summary["contamination_signal_pp"] = round(
        summary["eval-orig"]["exact_pct"] - summary["eval-perm"]["exact_pct"], 2)
    summary["contamination_flag"] = bool(
        summary["contamination_signal_pp"] > 5
        or summary["id-recall"]["tasks_with_verbatim_hits"] > 0)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"ticket": "NC0-t1c", "ts": ts, "args": vars(args),
               "summary": summary}
    base = f"{RECEIPTS}/t1c-contamination-{ts}"
    os.makedirs(RECEIPTS, exist_ok=True)
    checked_write(base + ".json", receipt)
    with open(base + "-rows.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")
    print(json.dumps(summary, indent=2))
    print("T1C_CONTAMINATION_DONE")


if __name__ == "__main__":
    main()
