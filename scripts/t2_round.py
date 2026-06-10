"""t2_round.py — NC0 T2: one expert-iteration round.

Phases: (1) acquire episodes — either ingest a T1 samples JSONL (round 1,
no resample) or sample k programs/task from base+adapter_{N-1}; verified
episodes append to the ledger. (2) build SFT dataset from the full ledger.
(3) QLoRA-train FROM BASE on it (adapter r_N reflects all episodes <= N).

--control builds the MATCHED-SFT control arm instead: same per-task example
counts, same training config, but programs that FAILED verification.

Usage (via wrapper): t2_round.py --round N [--from-samples PATH] [--control]
Artifacts: ledger/episodes.jsonl, adapters/r{N}[-control]/, receipts/t2-*.json
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ["UNSLOTH_USE_TRITON"] = "0"  # spec-forge-proven on this box
# NOTE: unsloth's fused-CE guard raises "No or negligible GPU memory" when
# driver-free VRAM ~= 0 at step 0. 4 identical crashes (0cb82c79/1fbfbb77/
# 18b1fc3f/9ca1b8be) at bf16: 7B weights = 15.2GB leave too little margin on
# 24GB for first-forward transients. The "spec-forge-proven" recipe was proven
# on Qwen2.5-3B (~6GB) — margin, not seq/batch, was the variable. Fix below:
# load_in_4bit=True (true QLoRA, ~5.3GB base). Probe: probe_meminfo (H-B).
# Loop is local-only: weights cached in HF_HOME; network reach = loud failure.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (ARC_TRAIN, extract_code, execute_batch, load_tasks,  # noqa: E402
                      sample_model, task_prompt)

LEDGER = f"{NC}/ledger/episodes.jsonl"
CONTROL_POOL = f"{NC}/ledger/control_pool.jsonl"
ADAPTERS = f"{NC}/adapters"
RECEIPTS = f"{NC}/receipts"
MAX_PER_TASK = 4  # shortest distinct verified programs kept per task
# max_seq 3072: seed prompts cap at ~2.8k tok; 4096 + fused-CE buffer OOM'd
# on 24GB with the bf16 base (attempts 0cb82c79/1fbfbb77/18b1fc3f).
LORA = {"r": 32, "alpha": 64, "dropout": 0.05, "lr": 2e-4, "epochs": 3,
        "max_seq": 3072}


def sha(s):
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def append_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seen = set()
    if os.path.exists(path):
        with open(path) as f:
            seen = {json.loads(line)["key"] for line in f if line.strip()}
    added = 0
    with open(path, "a") as f:
        for r in rows:
            if r["key"] in seen:
                continue
            f.write(json.dumps(r) + "\n")
            seen.add(r["key"])
            added += 1
    return added


def ingest_samples(samples_path, round_n):
    verified, failed = [], []
    with open(samples_path) as f:
        for line in f:
            row = json.loads(line)
            if "src" not in row:
                continue
            rec = {"key": f"{row['task']}:{sha(row['src'])}",
                   "task": row["task"], "src": row["src"],
                   "round": round_n, "solved": bool(row.get("solved"))}
            (verified if row.get("verified") else failed).append(rec)
    return verified, failed


def sample_round(model_id, adapter, k, round_n, batch_size, seed):
    tasks = load_tasks(ARC_TRAIN)
    by_id = {t["id"]: t for t in tasks}
    gen_meta, completions, _, gen_tokens, secs = sample_model(
        model_id, tasks, k, batch_size, 768, 0.8, seed, adapter=adapter)
    jobs, metas = [], []
    for m, comp in zip(gen_meta, completions):
        src = extract_code(comp)
        if src is None:
            continue
        t = by_id[m["task"]]
        jobs.append((src, t["train"], t["test"]))
        metas.append((m["task"], src))
    results = execute_batch(jobs)
    verified, failed = [], []
    for (task_id, src), r in zip(metas, results):
        rec = {"key": f"{task_id}:{sha(src)}", "task": task_id, "src": src,
               "round": round_n, "solved": bool(r.get("solved"))}
        (verified if r.get("verified") else failed).append(rec)
    return verified, failed, {"gen_tokens": int(gen_tokens),
                              "gen_secs": round(secs, 1),
                              "programs": len(jobs)}


def build_dataset(ledger_path, cap=MAX_PER_TASK, match_counts=None):
    """Returns chat examples. match_counts: {task: n} to mirror (control).

    Records carrying inline "pairs" (seed episodes from t3_seed, incl. re-arc
    augmented variants like "tid#a2") render their prompt from those pairs;
    others look up the task in ARC_TRAIN.
    """
    by_task = {}
    with open(ledger_path) as f:
        for line in f:
            r = json.loads(line)
            by_task.setdefault(r["task"], []).append(r)
    tasks = {t["id"]: t for t in load_tasks(ARC_TRAIN)}
    examples, counts = [], {}
    rng = random.Random(7)
    for task_id, recs in sorted(by_task.items()):
        uniq = {}
        for r in recs:
            uniq.setdefault(r["src"], r)
        recs = sorted(uniq.values(), key=lambda r: len(r["src"]))
        n = (match_counts or {}).get(task_id, cap) if match_counts is not None \
            else cap
        if match_counts is not None and task_id not in match_counts:
            continue
        if match_counts is not None:
            rng.shuffle(recs)
        for r in recs[:n]:
            if r.get("prompt"):
                # Non-ARC worlds (W-code mbpp:* via w2_ingest): the record
                # carries the exact user text the sampler saw — render it
                # verbatim; these task keys are not in ARC_TRAIN.
                user = r["prompt"]
            elif r.get("pairs"):
                user = task_prompt({"id": task_id, "train": r["pairs"],
                                    "test": r.get("test", [])})
            elif task_id in tasks:
                user = task_prompt(tasks[task_id])
            else:
                continue
            examples.append({
                "messages": [
                    {"role": "user", "content": user},
                    {"role": "assistant",
                     "content": f"```python\n{r['src']}\n```"},
                ]})
            counts[task_id] = counts.get(task_id, 0) + 1
    return examples, counts


def train_lora(model_id, examples, out_dir, seed=3407):
    """Mirrors the spec-forge-proven unsloth invocation on this box."""
    import torch
    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments, TrainerCallback
    from datasets import Dataset

    class _Headroom(TrainerCallback):
        # Headroom rule (user 2026-06-10): never pegged wall-to-wall — brief
        # pause each optimizer step keeps GPU/CPU duty cycle under 100%.
        def on_step_end(self, args, state, control, **kw):
            time.sleep(float(os.environ.get("EMBER_THROTTLE_S", "0.3")))

    # Resource governor (post-crash 2026-06-10, the user headroom rule): hard
    # per-process VRAM cap + free-margin assert as launch PRECONDITIONS —
    # same block as t1_probe.load_model; the 0670e3ec crash receipt is the
    # reason. r1's 4-bit train peaked 16.4/24.5GB, well inside the cap.
    frac = float(os.environ.get("EMBER_VRAM_FRACTION", "0.85"))
    torch.cuda.set_per_process_memory_fraction(frac)
    free, total = torch.cuda.mem_get_info()
    margin_gb = float(os.environ.get("EMBER_VRAM_MARGIN_GB", "4.0"))
    if free < margin_gb * 1e9:
        raise SystemExit(
            f"VRAM-PREFLIGHT: {free/1e9:.1f}GB free of {total/1e9:.1f}GB — "
            f"need >= {margin_gb}GB free before load; refusing launch")

    # unsloth pings the HF API even when weights are cached; under our
    # offline flags that raises. Resolve the cached snapshot DIR offline and
    # hand unsloth a local path — zero network, flags stay on.
    try:
        from huggingface_hub import snapshot_download
        model_path = snapshot_download(model_id, local_files_only=True)
    except Exception:  # noqa: BLE001 — fall back to repo id if no cache
        model_path = model_id
    model, tok = FastLanguageModel.from_pretrained(
        model_name=model_path, max_seq_length=LORA["max_seq"],
        dtype=torch.bfloat16, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=LORA["r"], lora_alpha=LORA["alpha"],
        lora_dropout=LORA["dropout"], bias="none",
        use_gradient_checkpointing="unsloth", random_state=seed,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    texts = [tok.apply_chat_template(e["messages"], tokenize=False)
             for e in examples]
    if len(texts) < 200:  # spec-forge small-dataset repeat
        rep = max(5, 200 // max(len(texts), 1))
        texts = texts * rep
        random.Random(seed).shuffle(texts)
    ds = Dataset.from_list([{"text": t} for t in texts])
    trainer = SFTTrainer(
        model=model, tokenizer=tok, train_dataset=ds,
        dataset_text_field="text", max_seq_length=LORA["max_seq"],
        dataset_num_proc=4,  # headroom rule: don't peg all cores tokenizing
        callbacks=[_Headroom()],
        args=TrainingArguments(
            output_dir=out_dir + "-ckpt", per_device_train_batch_size=1,
            gradient_accumulation_steps=16, num_train_epochs=LORA["epochs"],
            learning_rate=LORA["lr"], lr_scheduler_type="cosine",
            warmup_steps=10, logging_steps=5, save_strategy="no",
            seed=seed, report_to="none", fp16=False, bf16=True))
    stats = trainer.train()
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    return {"train_loss": round(stats.training_loss, 4),
            "steps": stats.global_step, "n_examples": len(examples),
            "n_texts_after_repeat": len(texts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--from-samples", default=None)
    ap.add_argument("--train-only", action="store_true",
                    help="skip episode acquisition; train from existing ledger")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--k", type=int, default=32)
    ap.add_argument("--batch-size", type=int, default=24)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--tag-suffix", default=os.environ.get("EMBER_ADAPTER_TAG", ""),
                    help="adapter/receipt tag suffix per core, e.g. '-q15' "
                         "(small-core re-stage 2026-06-10; keeps 7B artifacts "
                         "untouched)")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = f"r{args.round}{args.tag_suffix}" + ("-control" if args.control else "")
    receipt = {"ticket": "NC0-T2", "round": args.round, "control": args.control,
               "model": args.model, "ts": ts}

    if not args.control:
        if args.train_only:
            verified, failed = [], []
            receipt["sampling"] = {"source": "ledger-only (--train-only)"}
        elif args.from_samples:
            verified, failed, receipt["sampling"] = \
                (*ingest_samples(args.from_samples, args.round),
                 {"source": args.from_samples})
        else:
            adapter = (f"{ADAPTERS}/r{args.round - 1}{args.tag_suffix}"
                       if args.round > 1 else None)
            verified, failed, receipt["sampling"] = sample_round(
                args.model, adapter, args.k, args.round, args.batch_size,
                args.seed + args.round)
        receipt["episodes_verified_new"] = append_jsonl(LEDGER, verified)
        receipt["control_pool_new"] = append_jsonl(CONTROL_POOL, failed)

    # dataset
    if args.control:
        _, verified_counts = build_dataset(LEDGER)
        examples, counts = build_dataset(CONTROL_POOL,
                                         match_counts=verified_counts)
    else:
        examples, counts = build_dataset(LEDGER)
    receipt["dataset"] = {"n_examples": len(examples),
                          "n_tasks": len(counts)}

    if not examples:
        receipt["verdict"] = "EMPTY-DATASET (K1 territory — gate before training)"
    else:
        t0 = time.time()
        receipt["training"] = train_lora(args.model, examples,
                                         f"{ADAPTERS}/{tag}")
        receipt["training"]["secs"] = round(time.time() - t0, 1)
        receipt["adapter"] = f"{ADAPTERS}/{tag}"

    os.makedirs(RECEIPTS, exist_ok=True)
    path = f"{RECEIPTS}/t2-{tag}-{ts}.json"
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: v for k, v in receipt.items() if k != "ts"},
                     indent=2, default=str))
    print("T2_ROUND_DONE")


if __name__ == "__main__":
    main()
