"""t1_chunked.py — NC0 layer 1b: chunked/resumable train-split baseline.

Replaces the write-at-end t1 --full (killed run 57e1d01f lost 2,624 gens).
Tasks are partitioned into fixed chunks; each chunk samples, executes, and
APPENDS its rows to one canonical samples JSONL before the next chunk starts.
A progress file records completed chunks, so a killed run resumes at the
first incomplete chunk with everything before it already on disk.

Resume contract: progress is keyed to an args fingerprint — resuming with
different model/k/temp/seed fails loudly instead of mixing distributions.
Model loads ONCE per process (not per chunk). Headroom rule inherited from
t1_probe (EMBER_THROTTLE_S between batches, capped exec pool).

Usage (via wrapper t1_full_chunked.py): t1_chunked.py [--chunk-tasks 50] ...
Artifacts: receipts/t1-full-chunked-samples.jsonl   (canonical, append-only)
           receipts/t1-chunked-progress.json        (resume state)
           receipts/t1-full-<ts>.json               (final aggregate receipt)
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (ARC_TRAIN, RECEIPTS, extract_code, execute_batch,  # noqa: E402
                      generate, load_model, load_tasks)

SAMPLES = f"{RECEIPTS}/t1-full-chunked-samples.jsonl"  # t2_r1 glob-compatible
PROGRESS = f"{RECEIPTS}/t1-chunked-progress.json"


def fingerprint(args):
    keys = ("model", "k", "batch_size", "max_new", "temp", "seed",
            "chunk_tasks")
    return hashlib.sha1(json.dumps(
        {k: getattr(args, k) for k in keys}, sort_keys=True).encode()
    ).hexdigest()[:16]


def load_progress(fp):
    if os.path.exists(PROGRESS):
        with open(PROGRESS) as f:
            p = json.load(f)
        if p.get("fingerprint") != fp:
            raise SystemExit(
                f"PROGRESS-MISMATCH: {PROGRESS} was written by a run with "
                f"different args (theirs {p.get('fingerprint')}, ours {fp}). "
                "Archive or delete it to start fresh — refusing to mix "
                "sampling distributions in one samples file.")
        return p
    return {"fingerprint": fp, "done_chunks": [], "started": []}


def save_progress(p):
    tmp = PROGRESS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(p, f, indent=2)
    os.replace(tmp, PROGRESS)


def run_chunk(model, tok, tasks, args, chunk_idx):
    """Sample + execute one chunk; returns rows ready to append."""
    by_id = {t["id"]: t for t in tasks}
    gen_meta, completions, all_meta, gen_tokens, gen_secs = generate(
        model, tok, tasks, args.k, args.batch_size, args.max_new,
        args.temp, args.seed + chunk_idx)  # per-chunk seed: resume-stable
    jobs, job_meta = [], []
    for m, comp in zip(gen_meta, completions):
        src = extract_code(comp)
        if src is None:
            job_meta.append({**m, "extracted": False,
                             "raw_tail": comp[-300:]})
            continue
        t = by_id[m["task"]]
        job_meta.append({**m, "extracted": True, "job_idx": len(jobs)})
        jobs.append((src, t["train"], t["test"]))
    results = execute_batch(jobs)
    rows = []
    for m in job_meta:
        if m.get("extracted"):
            r = results[m["job_idx"]]
            row = {**m, **r, "src": jobs[m["job_idx"]][0]}
            row.pop("job_idx", None)
        else:
            row = {**m, "verified": False, "solved": False,
                   "error": "no-code-block"}
        row["chunk"] = chunk_idx
        rows.append(row)
    skipped = [m for m in all_meta if m.get("skipped")]
    stats = {"chunk": chunk_idx, "tasks": len(tasks), "rows": len(rows),
             "programs": len(jobs), "skipped_prompt_len": len(skipped),
             "gen_tokens": int(gen_tokens), "gen_secs": round(gen_secs, 1)}
    return rows, stats


def aggregate_receipt(args, ts):
    per_task, n_rows = {}, 0
    with open(SAMPLES) as f:
        for line in f:
            row = json.loads(line)
            n_rows += 1
            pt = per_task.setdefault(row["task"],
                                     {"verified": False, "solved": False})
            pt["verified"] |= bool(row.get("verified"))
            pt["solved"] |= bool(row.get("solved"))
    n = len(per_task)
    return {
        "ticket": "NC0-T1", "mode": "full-chunked", "ts": ts,
        "args": vars(args), "samples": SAMPLES,
        "summary": {
            "tasks_sampled": n, "rows": n_rows,
            "verify_any_pct": round(100 * sum(
                t["verified"] for t in per_task.values()) / max(n, 1), 2),
            "solve_any_pct": round(100 * sum(
                t["solved"] for t in per_task.values()) / max(n, 1), 2),
        }}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--k", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-new", type=int, default=768)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--chunk-tasks", type=int, default=50)
    args = ap.parse_args()

    fp = fingerprint(args)
    progress = load_progress(fp)
    tasks = load_tasks(ARC_TRAIN)
    chunks = [tasks[i:i + args.chunk_tasks]
              for i in range(0, len(tasks), args.chunk_tasks)]
    todo = [i for i in range(len(chunks))
            if i not in progress["done_chunks"]]
    print(f"tasks={len(tasks)} chunks={len(chunks)} done="
          f"{len(progress['done_chunks'])} todo={len(todo)} fp={fp}",
          flush=True)
    if not todo:
        print("all chunks already complete — writing aggregate receipt only",
              flush=True)
    else:
        model, tok = load_model(args.model)
        for ci in todo:
            t0 = time.time()
            rows, stats = run_chunk(model, tok, chunks[ci], args, ci)
            with open(SAMPLES, "a") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
            progress["done_chunks"].append(ci)
            progress["chunk_stats"] = progress.get("chunk_stats", []) + [stats]
            save_progress(progress)
            print(f"CHUNK {ci} DONE rows={stats['rows']} "
                  f"({time.time() - t0:.0f}s) "
                  f"[{len(progress['done_chunks'])}/{len(chunks)}]",
                  flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = aggregate_receipt(args, ts)
    receipt["chunks"] = progress.get("chunk_stats", [])
    path = f"{RECEIPTS}/t1-full-{ts}.json"
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt["summary"], indent=2))
    print("T1_CHUNKED_DONE")


if __name__ == "__main__":
    main()
