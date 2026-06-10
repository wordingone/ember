"""kernel_replay — the executable definition of "replayable" (freeze spec §4).

Mode B (any platform, CPU-only, no GPU/daemon):
    python kernel_replay.py --receipt receipts/t4-r1-q3-arc1-seed14-<ts>.json
  Re-derives every arm summary and paired delta in a t4 receipt from the raw
  per-task rows (<tag>-chunks.jsonl), via an independent code path that
  implements the same frozen gate semantics (mean×100 round-2; bootstrap
  n=10000 seed=7 percentile CI; paired delta over task-aligned any-bits).
  Cross-checks task any-bits against the raw per-sample rows
  (<tag>-samples.jsonl). Prints field-by-field PASS/FAIL and a terminal
  KERNEL_REPLAY_PASS / KERNEL_REPLAY_FAIL line.

Mode A (POSIX only — daemon dispatch; imports the sandbox lazily):
    python kernel_replay.py --episode <task_key> [--ledger data/episodes.jsonl]
  Re-executes the episode's src through the SAME sandbox (t1_probe.run_program)
  against the task's original train pairs and asserts verified == True.

A receipt that cannot be replayed against its raw rows is not a receipt
(kernel v1.0 freeze surface, member 4).
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


# ── independent re-implementations of the frozen gate math ──────────────────
def replay_bootstrap_ci(values, n=10000, seed=7):
    rng = random.Random(seed)
    m = len(values)
    stats = sorted(sum(rng.choices(values, k=m)) / m for _ in range(n))
    return [round(100 * stats[int(n * q)], 2) for q in (0.025, 0.975)]


def replay_paired_delta_ci(a, b, n=10000, seed=7):
    rng = random.Random(seed)
    pairs = list(zip(a, b))
    m = len(pairs)
    deltas = sorted(
        sum(x - y for x, y in rng.choices(pairs, k=m)) / m for _ in range(n))
    return [round(100 * deltas[int(n * q)], 2) for q in (0.025, 0.975)]


def load_sample_aggregates(samples_path, k=None):
    """Per-(arm,task) OR-aggregated (solved,verified) from sample rows,
    RESUMED-RUN SAFE (eng #8): a crashed-then-resumed chunk leaves stale
    partial sample rows in the file, followed by the complete re-run rows
    for the same (arm, chunk, task). Re-run-lines-win == keep only the
    LAST k rows of each (arm, chunk, task) group (a complete group is
    exactly k samples; anything older in the group is pre-crash residue).
    Contiguity is NOT a usable boundary: when the crash arm is also the
    resume's first arm, stale and re-run rows are adjacent with identical
    keys (caught by the synthetic fixture). k=None -> keep all rows
    (clean-run behavior, exact for never-resumed files).
    The old OR-over-everything produced false mismatches on legitimate
    resumed receipts."""
    groups = {}
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            groups.setdefault(
                (r.get("arm"), r.get("chunk"), r.get("task")), []).append(r)
    agg = {}
    for (arm, _chunk, task), rows in groups.items():
        kept = rows if k is None else rows[-int(k):]
        for r in kept:
            key = (arm, task)
            s, v = agg.get(key, (0, 0))
            agg[key] = (s | int(r.get("solved", 0)),
                        v | int(r.get("verified", 0)))
    return agg


def load_task_rows(chunks_path, arms):
    """Per-arm per-task bits, later-lines-win; first-seen order preserved
    (mirrors t4_chunked's append-order accumulation)."""
    acc = {a: {} for a in arms}
    order = []
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("arm") in acc:
                if r["task"] not in acc[r["arm"]]:
                    if r["task"] not in order:
                        order.append(r["task"])
                acc[r["arm"]][r["task"]] = r
    return acc, order


def replay_receipt(receipt_path):
    with open(receipt_path, encoding="utf-8") as f:
        receipt = json.load(f)
    base = os.path.basename(receipt_path)
    tag = base.rsplit("-", 1)[0]  # strip -<ts>.json
    rdir = os.path.dirname(receipt_path)
    chunks_path = os.path.join(rdir, f"{tag}-chunks.jsonl")
    samples_path = os.path.join(rdir, f"{tag}-samples.jsonl")
    arms = [a for a, v in receipt["arms"].items() if "skipped" not in v]

    acc, order = load_task_rows(chunks_path, arms)
    ids = [t for t in order if all(t in acc[a] for a in arms)]

    checks, fails = [], 0

    def check(name, got, want, tol=None):
        nonlocal fails
        ok = (got == want) if tol is None else (
            want is not None and got is not None
            and all(abs(g - w) <= tol for g, w in zip(got, want)))
        if not ok:
            fails += 1
        checks.append((name, got, want, "PASS" if ok else "FAIL"))

    check("n_tasks_done", len(ids), receipt.get("n_tasks_done"))
    solved_by_arm = {}
    for arm in arms:
        solved = [int(acc[arm][i]["solved"]) for i in ids]
        verified = [int(acc[arm][i]["verified"]) for i in ids]
        solved_by_arm[arm] = solved
        want = receipt["arms"][arm]
        check(f"{arm}.n_tasks", len(ids), want["n_tasks"])
        check(f"{arm}.solve_any_pct",
              round(100 * sum(solved) / max(len(ids), 1), 2),
              want["solve_any_pct"])
        check(f"{arm}.verify_any_pct",
              round(100 * sum(verified) / max(len(ids), 1), 2),
              want["verify_any_pct"])
        check(f"{arm}.solve_ci95", replay_bootstrap_ci(solved),
              want["solve_ci95"])
    if "core_meta" in solved_by_arm and "core_only" in solved_by_arm:
        check("delta_meta_minus_core_ci95",
              replay_paired_delta_ci(solved_by_arm["core_meta"],
                                     solved_by_arm["core_only"]),
              receipt.get("delta_meta_minus_core_ci95"))
    if "core_meta" in solved_by_arm and "control" in solved_by_arm:
        check("delta_meta_minus_control_ci95",
              replay_paired_delta_ci(solved_by_arm["core_meta"],
                                     solved_by_arm["control"]),
              receipt.get("delta_meta_minus_control_ci95"))

    # cross-check: task any-bits re-derived from raw per-sample rows
    # (resumed-run safe: stale pre-crash stretches dropped, eng #8)
    mismatch, sampleless = 0, 0
    if os.path.exists(samples_path):
        agg = load_sample_aggregates(samples_path,
                                     k=(receipt.get("args") or {}).get("k"))
        for arm in arms:
            for i in ids:
                row = acc[arm][i]
                got = agg.get((arm, i))
                if got is None:
                    sampleless += 1  # length-capped/skipped: scored 0, known
                    continue
                if got != (int(row["solved"]), int(row["verified"])):
                    mismatch += 1
        check("samples_vs_chunks_mismatches", mismatch, 0)

    for name, got, want, verdict in checks:
        print(f"  [{verdict}] {name}: replay={got} receipt={want}")
    if sampleless:
        print(f"  [note] {sampleless} arm-task cells have chunk rows but no "
              f"sample rows (length-capped, scored 0 — known quirk)")
    print(f"KERNEL_REPLAY_{'FAIL' if fails else 'PASS'} "
          f"({len(checks) - fails}/{len(checks)} fields) {base}")
    return fails == 0


def replay_episode(task_key, ledger_path):
    """Mode A — POSIX only; re-runs V on one ledger entry."""
    sys.path.insert(0, HERE)
    from t1_probe import run_program, load_tasks  # noqa: lazy heavy import
    entry = None
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("key") == task_key or r.get("task") == task_key:
                entry = r  # later lines win
    if entry is None:
        print(f"KERNEL_REPLAY_FAIL episode {task_key} not in {ledger_path}")
        return False
    tasks = {t["id"]: t for t in load_tasks("arc1", "train")}
    tid = entry["task"].split("#")[0]
    if tid not in tasks:
        print(f"KERNEL_REPLAY_FAIL task {tid} not in world")
        return False
    t = tasks[tid]
    out = run_program((entry["src"], t["train"], t["test"]))
    ok = bool(out["verified"])
    print(f"  re-executed V({task_key}): verified={out['verified']} "
          f"(ledger asserts True) error={out['error']}")
    print(f"KERNEL_REPLAY_{'PASS' if ok else 'FAIL'} episode {task_key}")
    return ok


def _selftest():
    """Synthetic resumed-run fixture (eng #8) — fully fabricated, built in a
    temp dir, exercises: (1) a resumed receipt replays PASS (stale pre-crash
    sample stretch superseded); (2) under the OLD or-over-everything
    aggregation the same fixture would mismatch (asserted directly);
    (3) a tampered receipt replays FAIL (replay catches edits)."""
    import tempfile
    arms = ["core_only", "core_meta", "control"]
    tasks = ["t1", "t2", "t3", "t4"]
    solved = {"core_only": [1, 0, 0, 0], "core_meta": [0, 0, 0, 0],
              "control": [0, 0, 0, 0]}
    with tempfile.TemporaryDirectory() as td:
        tag = "synthfix-t4-resumed"
        chunks, samples = [], []
        for ci, chunk_tasks in ((0, tasks[:2]), (1, tasks[2:])):
            for arm in arms:
                if ci == 1 and arm == "core_only":
                    # STALE pre-crash stretch: t3 wrongly solved, partial
                    samples.append({"arm": arm, "chunk": 1, "task": "t3",
                                    "solved": 1, "verified": 1})
                    chunks.append({"arm": arm, "chunk": 1, "task": "t3",
                                   "solved": 1, "verified": 1})
            for arm in arms:  # complete (re-)run stretches, later lines
                for t in chunk_tasks:
                    i = tasks.index(t)
                    for _ in range(2):  # k=2 samples
                        samples.append({"arm": arm, "chunk": ci, "task": t,
                                        "solved": solved[arm][i],
                                        "verified": solved[arm][i]})
                    chunks.append({"arm": arm, "chunk": ci, "task": t,
                                   "solved": solved[arm][i],
                                   "verified": solved[arm][i]})
        receipt = {"n_tasks_done": 4, "arms": {}, "args": {"k": 2}}
        for arm in arms:
            receipt["arms"][arm] = {
                "n_tasks": 4,
                "solve_any_pct": round(100 * sum(solved[arm]) / 4, 2),
                "verify_any_pct": round(100 * sum(solved[arm]) / 4, 2),
                "solve_ci95": replay_bootstrap_ci(solved[arm])}
        receipt["delta_meta_minus_core_ci95"] = replay_paired_delta_ci(
            solved["core_meta"], solved["core_only"])
        receipt["delta_meta_minus_control_ci95"] = replay_paired_delta_ci(
            solved["core_meta"], solved["control"])
        rp = os.path.join(td, f"{tag}-00000000T000000Z.json")
        with open(rp, "w") as f:
            json.dump(receipt, f)
        for suffix, rows in (("chunks", chunks), ("samples", samples)):
            with open(os.path.join(td, f"{tag}-{suffix}.jsonl"), "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")

        # (2) the old aggregation WOULD have flagged the stale t3 row
        old_agg = {}
        for r in samples:
            k = (r["arm"], r["task"])
            s, v = old_agg.get(k, (0, 0))
            old_agg[k] = (s | r["solved"], v | r["verified"])
        assert old_agg[("core_only", "t3")] == (1, 1)  # stale residue
        assert load_sample_aggregates(
            os.path.join(td, f"{tag}-samples.jsonl"), k=2)[
                ("core_only", "t3")] == (0, 0)  # fix drops it

        # (1) resumed receipt replays PASS
        assert replay_receipt(rp) is True

        # (3) tampering caught
        receipt["arms"]["core_only"]["solve_any_pct"] += 1.0
        with open(rp, "w") as f:
            json.dump(receipt, f)
        assert replay_receipt(rp) is False
    print("KERNEL_REPLAY_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", help="t4 receipt JSON to replay (mode B)")
    ap.add_argument("--episode", help="ledger task key to re-verify (mode A)")
    ap.add_argument("--selftest", action="store_true",
                    help="synthetic resumed-run fixture (eng #8)")
    ap.add_argument("--ledger", default=os.path.join(
        os.path.dirname(HERE), "data", "episodes.jsonl"))
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    if not args.receipt and not args.episode:
        ap.error("need --receipt or --episode")
    ok = True
    if args.receipt:
        ok = replay_receipt(args.receipt) and ok
    if args.episode:
        ok = replay_episode(args.episode, args.ledger) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
