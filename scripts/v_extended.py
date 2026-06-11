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

== asserts now route through the strict comparator (v_compare, single source,
eng-21 semantics); execution path is the guarded sandbox (t1_probe.run_program).
w1_humaneval's --ext-verify path imports build_harness from this module, so
that path is tightened automatically (single source, no second wiring).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from receipt_write import checked_write

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
SOLVE_STUB = "\n\ndef solve(grid):\n    return [[0]]\n"  # sandbox gadget

# STRICT_SRC and split_assert are imported at call sites below so this module
# remains selftest-safe on Windows without NC/scripts on sys.path.


def build_harness(src, plus_test, imports=()):
    """Candidate src + MBPP+ extended test code, with strict comparator preamble.

    plus_test is the MBPP+ `test` field — a multi-line code blob. Top-level
    single-line `assert L == R` statements (column-0 only) are rewritten to
    `_v_check((L), (R))` (eng-21 semantics, v_compare single source). Indented
    asserts — e.g. inside a for-loop — pass verbatim; rewriting them to a
    top-level _v_check call would drop the indent and produce a SyntaxError
    (= false flips). Non-== shapes and setup lines also pass verbatim.
    """
    # Late import so _selftest() (pure logic) works without NC/scripts.
    _scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    from v_compare import STRICT_SRC  # noqa: PLC0415
    from fp8_vgate import split_assert  # noqa: PLC0415

    instrumented = []
    for line in plus_test.splitlines():
        # Only rewrite top-level (column-0) single assert L == R lines.
        if line.lstrip() == line and line.startswith("assert "):
            pair = split_assert(line)
            if pair is not None:
                instrumented.append(f"_v_check(({pair[0]}), ({pair[1]}))")
                continue
        instrumented.append(line)
    tests_block = "\n".join(instrumented)
    return ("\n".join(imports) + "\n" + src + "\n" + STRICT_SRC + "\n" +
            tests_block + SOLVE_STUB)


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
        with open(f"{RECEIPTS}/{flags_file}", "w", encoding="utf-8", newline="\n") as f:
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
    checked_write(f"{RECEIPTS}/v-extended-{ts}.json", receipt)
    print(json.dumps(receipt, indent=2))
    print("V_EXTENDED_DONE")


def _selftest():
    # (a) top-level `assert f(2) == 4` gets rewritten to a _v_check call
    h_top = build_harness("def f(x):\n    return x * 2\n",
                          "assert f(2) == 4", [])
    assert "_v_check((f(2)), (4))" in h_top, \
        "top-level == assert must be instrumented"
    assert "def _v_check" in h_top, "STRICT_SRC preamble must be present"

    # (b) INDENTED assert inside a for-loop passes verbatim; harness compiles
    indented_block = "for i in [2]:\n    assert f(i) == i * 2"
    h_ind = build_harness("def f(x):\n    return x * 2\n",
                          indented_block, [])
    assert "    assert f(i) == i * 2" in h_ind, \
        "indented assert must pass verbatim (no indent-drop false flip)"
    assert "_v_check((f(i))" not in h_ind, \
        "indented assert must NOT be rewritten"
    # compile() confirms the harness is syntactically valid
    compile(h_ind, "<selftest-indented>", "exec")

    # (c) non-== asserts and setup lines pass verbatim
    mixed = ("x = 5\nassert f(x) is not None\nassert f(0) == 0\n"
             "assert math.isclose(f(1), 2.0)")
    h_mix = build_harness("def f(x):\n    return x * 2\n", mixed, ["import math"])
    assert "x = 5" in h_mix, "setup line must pass verbatim"
    assert "assert f(x) is not None" in h_mix, "is-not-None assert verbatim"
    assert "_v_check((f(0)), (0))" in h_mix, "top-level == rewritten"
    assert "assert math.isclose(f(1), 2.0)" in h_mix, \
        "isclose assert passes verbatim"

    # (d) STRICT_SRC present between src and test block
    h_ord = build_harness("def f(x):\n    return x\n", "assert f(1) == 1", [])
    assert h_ord.index("def f(x):") < h_ord.index("def _v_check") \
        < h_ord.index("_v_check((f(1)), (1))") < h_ord.index("def solve(grid):"), \
        "order: src / STRICT_SRC / tests / stub"

    # (e) keep all existing fpr_block assertions
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
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
