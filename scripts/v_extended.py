"""v_extended.py — W-code V hardening: MBPP+ extended-test FPR (eng #7).

V-soundness caveat (kernel freeze spec; Liu et al. NeurIPS 2023,
arXiv 2305.01210): MBPP's 3 asserts under-specify tasks — programs can
pass V while wrong. EvalPlus's MBPP+ carries ~35x extended tests for the
same sanitized tasks. This script measures OUR local false-positive rate:
every V-passed ledger episode is re-executed in the SAME t1_probe sandbox
against the task's MBPP+ extended test. FPR = fraction of V-accepts that
fail extended.

Quarantine discipline: episodes failing extended are FLAGGED to
receipts/v-ext-flags-<ts>.jsonl — NOT auto-removed from the ledger; the
gate decides on the receipt (receipts-only truth; auto-deletion would be
a silent write to the identity ledger). Timeouts are tallied separately
from wrong-answers: extended suites are ~35x larger, a timeout under the
sandbox's fixed budget is a measurement limit, not proof of wrongness.

Per-stratum FPR rides on the eng-#5 annotations — false positives
concentrated in the frontier stratum would corrupt exactly the
highest-bits episodes, so the breakdown is the load-bearing number.

Coverage is reported, never silent: ledger tasks absent from MBPP+
(curation dropped some sanitized ids) are listed as uncovered.

Receipt: receipts/v-extended-<ts>.json. Selftest: `--selftest`
(Windows-safe: FPR math + harness assembly).
"""

import argparse
import json
import os
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
SOLVE_STUB = "\n\ndef solve(grid):\n    return [[0]]\n"  # sandbox gadget


def build_harness(src, plus_test, imports=()):
    """Candidate src + MBPP+ extended test code (calls candidate by name)."""
    return "\n".join(imports) + "\n" + src + "\n" + plus_test + SOLVE_STUB


def fpr_block(rows):
    """rows: [{task, stratum, ext_ok, timeout}] for V-PASSED episodes only.
    Returns overall + per-stratum FPR with timeouts tallied separately."""
    def sub(sel):
        n = len(sel)
        t = sum(1 for r in sel if r["timeout"])
        wrong = sum(1 for r in sel if not r["ext_ok"] and not r["timeout"])
        return {"n": n, "ext_wrong": wrong, "ext_timeout": t,
                "fpr": round(wrong / n, 4) if n else None,
                "fpr_incl_timeout": round((wrong + t) / n, 4) if n else None}
    out = {"overall": sub(rows)}
    for st in sorted({r.get("stratum", "?") for r in rows}):
        out[st] = sub([r for r in rows if r.get("stratum", "?") == st])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=f"{NC}/ledger/views/wcode-r1.jsonl")
    args, _unknown = ap.parse_known_args()  # daemon appends args

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    from datasets import load_dataset
    from t1_probe import execute_batch

    plus = {int(r["task_id"]): r for r in
            load_dataset("evalplus/mbppplus", split="test")}

    episodes = []
    with open(args.view) as f:
        for line in f:
            r = json.loads(line)
            if r.get("verified"):
                episodes.append(r)
    if not episodes:
        raise SystemExit("v_extended: no verified episodes in view")

    covered, uncovered_tasks = [], set()
    for r in episodes:
        tid = int(r["task"].split(":")[1])
        if tid in plus:
            covered.append((r, plus[tid]))
        else:
            uncovered_tasks.add(tid)

    jobs = [(build_harness(r["src"], p["test"],
                           p.get("test_imports") or []), [], [])
            for r, p in covered]
    results = execute_batch(jobs)

    rows, flags = [], []
    for (r, p), res in zip(covered, results):
        timeout = (res.get("error") or "") in ("timeout", "pool-timeout")
        ext_ok = bool(res.get("verified")) and not res.get("error")
        rows.append({"task": r["task"], "stratum": r.get("stratum", "?"),
                     "ext_ok": ext_ok, "timeout": timeout})
        if not ext_ok:
            flags.append({"key": r["key"], "task": r["task"],
                          "stratum": r.get("stratum", "?"),
                          "timeout": timeout,
                          "error": res.get("error")})

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(RECEIPTS, exist_ok=True)
    flags_file = None
    if flags:
        flags_file = f"v-ext-flags-{ts}.jsonl"
        with open(f"{RECEIPTS}/{flags_file}", "w") as f:
            for fl in flags:
                f.write(json.dumps(fl) + "\n")

    receipt = {"ticket": "V-EXTENDED", "ts": ts, "args": vars(args),
               "v_passed_episodes": len(episodes),
               "covered_episodes": len(covered),
               "uncovered_tasks": sorted(uncovered_tasks),
               "fpr": fpr_block(rows),
               "flags_file": flags_file,
               "quarantine": "GATE decision on this receipt — no auto-"
                             "removal from ledger"}
    with open(f"{RECEIPTS}/v-extended-{ts}.json", "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print("V_EXTENDED_DONE")


def _selftest():
    h = build_harness("def f(): pass", "assert f() is None", ["import math"])
    assert h.startswith("import math\ndef f(): pass\nassert")
    assert h.endswith(SOLVE_STUB)
    rows = ([{"task": "mbpp:1", "stratum": "easy", "ext_ok": True,
              "timeout": False}] * 8
            + [{"task": "mbpp:2", "stratum": "frontier", "ext_ok": False,
                "timeout": False}] * 1
            + [{"task": "mbpp:3", "stratum": "frontier", "ext_ok": False,
                "timeout": True}] * 1
            + [{"task": "mbpp:4", "stratum": "frontier", "ext_ok": True,
                "timeout": False}] * 2)
    b = fpr_block(rows)
    assert b["overall"]["n"] == 12 and b["overall"]["ext_wrong"] == 1
    assert b["overall"]["ext_timeout"] == 1
    assert b["overall"]["fpr"] == round(1 / 12, 4)
    assert b["overall"]["fpr_incl_timeout"] == round(2 / 12, 4)
    assert b["frontier"]["fpr"] == 0.25 and b["easy"]["fpr"] == 0.0
    print("V_EXTENDED_SELFTEST_PASS")


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        _selftest()
    else:
        main()
