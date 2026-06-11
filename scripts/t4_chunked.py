"""t4_chunked.py — chunked/resumable four-arm heldout eval with early stop.

Post-crash redesign 2026-06-10 (pending layer 1a). Replaces the all-or-
nothing t4_eval run shape (the 0670e3ec crash burned 1.5h with ZERO salvage
because the receipt only wrote at the end). Same arms, same pairing, same
bootstrap math as t4_eval — orchestrated in chunks:

  - chunks of --chunk-size tasks; ALL arms complete per chunk, so a crash
    loses at most one chunk;
  - per-task rows appended to <tag>-chunks.jsonl after every arm
    (re-run lines win on resume rebuild);
  - atomic progress file keyed to an args fingerprint (PROGRESS-MISMATCH
    refusal under changed args — t1_chunked pattern);
  - paired bootstrap CIs recomputed over ALL accumulated tasks after each
    chunk; EARLY STOP once >= --min-tasks-stop tasks are in AND both
    (meta-core) and (meta-control) CIs exclude 0 — the verdict is settled,
    further GPU-hours buy nothing. Degenerate all-zero arms never trigger
    the stop (CI [0,0] includes 0) and run to the cap.

Resume = relaunch the same wrapper. Receipt at stop/cap:
receipts/t4-r{N}{suffix}-{surface}-seed{S}-<ts>.json (schema superset of
t4_eval's — gate logic carries).
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
# Loop is local-only: weights cached in HF_HOME; network reach = loud failure.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from t1_probe import load_tasks  # noqa: E402
from t4_eval import (ADAPTERS, RECEIPTS, SURFACES, bootstrap_ci,  # noqa: E402
                     fewshot_messages, paired_delta_ci, run_arm)
try:
    from stats_exact import build_exact_block as _build_exact_block  # noqa: E402
except ImportError:
    _build_exact_block = None


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def ci_excludes_zero(ci):
    return ci is not None and (ci[0] > 0 or ci[1] < 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--arms", nargs="+",
                    default=["core_only", "core_meta", "control",
                             "context_only"])
    ap.add_argument("--n-tasks", type=int, default=100)
    ap.add_argument("--k", type=int, default=8)
    # batch 8, not 16: e3d7c490 OOM'd at 16 under the VRAM cap (long ARC
    # eval prompts; peak activation scales with batch x longest-in-batch).
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-new", type=int, default=768)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--surface", default="arc1", choices=sorted(SURFACES))
    ap.add_argument("--chunk-size", type=int, default=25)
    ap.add_argument("--min-tasks-stop", type=int, default=50)
    ap.add_argument("--tag-suffix", default=os.environ.get("EMBER_ADAPTER_TAG",
                                                           ""),
                    help="adapter/receipt tag suffix per core, e.g. '-q15'")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    all_tasks = load_tasks(SURFACES[args.surface])
    tasks = rng.sample(all_tasks, min(args.n_tasks, len(all_tasks)))
    chunks = [tasks[i:i + args.chunk_size]
              for i in range(0, len(tasks), args.chunk_size)]

    arm_cfg = {
        "core_only": (None, []),
        "core_meta": (f"{ADAPTERS}/r{args.round}{args.tag_suffix}", []),
        "control": (f"{ADAPTERS}/r{args.round}{args.tag_suffix}-control", []),
        "context_only": (None, fewshot_messages()),
    }

    fp = hashlib.sha1(json.dumps(
        {k: v for k, v in sorted(vars(args).items())},
        sort_keys=True).encode()).hexdigest()[:16]
    tag = (f"t4-r{args.round}{args.tag_suffix}-{args.surface}"
           f"-seed{args.seed}")
    os.makedirs(RECEIPTS, exist_ok=True)
    progress_path = f"{RECEIPTS}/{tag}-progress.json"
    rows_path = f"{RECEIPTS}/{tag}-chunks.jsonl"
    samples_path = f"{RECEIPTS}/{tag}-samples.jsonl"

    done_chunks = 0
    skipped_arms = {}
    if os.path.exists(progress_path):
        with open(progress_path) as f:
            prog = json.load(f)
        if prog["fingerprint"] != fp:
            raise SystemExit(
                f"PROGRESS-MISMATCH: progress file {progress_path} was made "
                f"under different args (fp {prog['fingerprint']} != {fp}); "
                f"move it aside or restore the original args")
        if prog.get("stopped"):
            print(f"ALREADY-STOPPED: {prog.get('stop_reason')}")
            print("T4_CHUNKED_DONE")
            return
        done_chunks = prog["chunks_done"]
        skipped_arms = prog.get("skipped_arms", {})
        print(f"RESUME: {done_chunks}/{len(chunks)} chunks already done",
              flush=True)

    # accumulated per-task results, rebuilt from rows (later lines win, so a
    # re-run of a half-finished chunk is authoritative)
    acc = {arm: {} for arm in args.arms}
    if os.path.exists(rows_path):
        with open(rows_path) as f:
            for line in f:
                r = json.loads(line)
                if r["arm"] in acc:
                    acc[r["arm"]][r["task"]] = r

    def summarize(n_chunks_done):
        """Arm summaries + paired deltas over the common accumulated set."""
        ids = [t["id"] for t in tasks[:n_chunks_done * args.chunk_size]]
        ids = [i for i in ids if all(i in acc[a] for a in args.arms
                                     if a not in skipped_arms)]
        out, solved_by_arm = {}, {}
        for arm in args.arms:
            if arm in skipped_arms:
                out[arm] = {"skipped": skipped_arms[arm]}
                continue
            solved = [int(acc[arm][i]["solved"]) for i in ids]
            verified = [int(acc[arm][i]["verified"]) for i in ids]
            solved_by_arm[arm] = solved
            out[arm] = {
                "n_tasks": len(ids),
                "solve_any_pct": round(100 * sum(solved) / max(len(ids), 1),
                                       2),
                "solve_ci95": bootstrap_ci(solved) if ids else None,
                "verify_any_pct": round(
                    100 * sum(verified) / max(len(ids), 1), 2),
            }
        deltas = {}
        if "core_meta" in solved_by_arm and "core_only" in solved_by_arm:
            deltas["delta_meta_minus_core_ci95"] = paired_delta_ci(
                solved_by_arm["core_meta"], solved_by_arm["core_only"])
        if "core_meta" in solved_by_arm and "control" in solved_by_arm:
            deltas["delta_meta_minus_control_ci95"] = paired_delta_ci(
                solved_by_arm["core_meta"], solved_by_arm["control"])
        return out, deltas, len(ids)

    stop_reason = None
    for ci_idx in range(done_chunks, len(chunks)):
        chunk_tasks = chunks[ci_idx]
        for arm in args.arms:
            if arm in skipped_arms:
                continue
            adapter, prefix = arm_cfg[arm]
            if adapter and not os.path.isdir(adapter):
                skipped_arms[arm] = f"no adapter at {adapter}"
                continue
            per_task, rows, info = run_arm(
                arm, args.model, adapter, chunk_tasks, args.k,
                args.batch_size, args.max_new, args.temp, args.seed, prefix)
            with open(samples_path, "a") as sf:
                for row in rows:
                    sf.write(json.dumps({**row, "chunk": ci_idx}) + "\n")
            with open(rows_path, "a") as rf:
                for tid, v in per_task.items():
                    rec = {"arm": arm, "chunk": ci_idx, "task": tid,
                           "verified": int(v["verified"]),
                           "solved": int(v["solved"])}
                    acc[arm][tid] = rec
                    rf.write(json.dumps(rec) + "\n")
            print(f"[chunk {ci_idx + 1}/{len(chunks)}] {arm} done "
                  f"({info['gen_secs']}s, {info['programs']} programs)",
                  flush=True)

        arms_sum, deltas, n_done = summarize(ci_idx + 1)
        prog = {"fingerprint": fp, "chunks_done": ci_idx + 1,
                "n_tasks_done": n_done, "arms": arms_sum, "deltas": deltas,
                "skipped_arms": skipped_arms, "stopped": False}
        if (n_done >= args.min_tasks_stop
                and ci_excludes_zero(
                    deltas.get("delta_meta_minus_core_ci95"))
                and ci_excludes_zero(
                    deltas.get("delta_meta_minus_control_ci95"))):
            stop_reason = (f"EARLY-STOP at {n_done} tasks: both paired CIs "
                           f"exclude 0 — verdict settled")
            prog["stopped"], prog["stop_reason"] = True, stop_reason
        atomic_write(progress_path, prog)
        print(json.dumps({"chunk": ci_idx + 1, "n_tasks": n_done,
                          **deltas}), flush=True)
        if stop_reason:
            break

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    arms_sum, deltas, n_done = summarize(len(chunks))
    # Additive exact-method sub-block (Wilson + Newcombe + MDE); falls back
    # gracefully if stats_exact is unavailable — no existing field is modified,
    # early-stop still keys off bootstrap CIs exactly as before.
    _exact_block = None
    if _build_exact_block is not None and n_done > 0:
        _succ_by_arm = {
            arm: sum(acc[arm][i]["solved"] for i in
                     [t["id"] for t in tasks[:len(chunks) * args.chunk_size]
                      if t["id"] in acc.get(arm, {})])
            for arm in args.arms if arm not in skipped_arms
        }
        _ids_common = [
            t["id"] for t in tasks[:len(chunks) * args.chunk_size]
            if all(t["id"] in acc.get(a, {}) for a in args.arms
                   if a not in skipped_arms)
        ]
        _paired_outcomes = {}
        sbarm = {arm: [int(acc[arm][i]["solved"]) for i in _ids_common]
                 for arm in args.arms if arm not in skipped_arms
                 and all(i in acc.get(arm, {}) for i in _ids_common)}
        if "core_meta" in sbarm and "core_only" in sbarm:
            _paired_outcomes["delta_meta_minus_core_ci95"] = (
                sbarm["core_meta"], sbarm["core_only"])
        if "core_meta" in sbarm and "control" in sbarm:
            _paired_outcomes["delta_meta_minus_control_ci95"] = (
                sbarm["core_meta"], sbarm["control"])
        _exact_block = _build_exact_block(_succ_by_arm, _paired_outcomes,
                                          n_done)
    receipt = {"ticket": "NC0-T4-CHUNKED", "round": args.round, "ts": ts,
               "surface": args.surface, "tag_suffix": args.tag_suffix,
               "args": {k: v for k, v in vars(args).items() if k != "arms"},
               "n_tasks_done": n_done,
               "stopped_early": bool(stop_reason),
               "stop_reason": stop_reason,
               "arms": arms_sum, **deltas,
               **( {"exact": _exact_block} if _exact_block is not None else {})}
    path = f"{RECEIPTS}/{tag}-{ts}.json"
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({"arms": arms_sum, **deltas,
                      "stopped_early": bool(stop_reason)}, indent=2))
    print("T4_CHUNKED_DONE")


if __name__ == "__main__":
    main()
