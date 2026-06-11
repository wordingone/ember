"""t3b_diag.py — diagnose the 26% variant-verify rate from t3_seed.

Hypotheses:
  H1 dsl-pinning corrupted generation: t3 forced re-arc generators onto
     arc-dsl's dsl copy (75-line body delta, identical function set).
  H2 solver/verifier divergence: re-arc ships adapted verifiers.py because the
     ORIGINAL solvers genuinely don't cover the generator distribution.

Design: run the same probe twice in clean subprocesses —
  mode=pinned   arc-dsl's dsl pinned first (mirrors t3 production)
  mode=native   re-arc's own dsl only (upstream-intended)
Per mode, for N sampled tasks x P generated pairs: does the ORIGINAL solver
program pass? does re-arc's own verifier pass?
  H1 true -> native solver-pass >> pinned solver-pass
  H2 true -> verifier-pass >> solver-pass in BOTH modes
Receipt: receipts/t3b-diag-<ts>.json. CPU-only, no GPU, no model.
"""

import json
import os
import random
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
ARC_DSL = f"{NC}/vendor/arc-dsl"
RE_ARC = f"{NC}/vendor/re-arc"
RECEIPTS = f"{NC}/receipts"
N_TASKS = 12
PAIRS_PER_TASK = 4
GEN_RETRIES = 2          # x PAIRS_PER_TASK attempts max per task
GEN_ALARM_S = 3          # generators misfiring under wrong dsl hang/retry;
                         # short alarm keeps worst case ~5 min per mode
SEED = 14

SOLVER_RE = re.compile(
    r"^def solve_([0-9a-f]{8})\(I\):\n(.*?)(?=^def |\Z)", re.M | re.S)

PROG_TMPL = """from dsl import *
from constants import *

def _impl(I):
{body}

def solve(grid):
    I = tuple(tuple(row) for row in grid)
    O = _impl(I)
    return [list(row) for row in O]
"""


def _stub_matplotlib():
    import types
    mpl = types.ModuleType("matplotlib")
    plt = types.ModuleType("matplotlib.pyplot")
    colors = types.ModuleType("matplotlib.colors")
    colors.ListedColormap = object
    colors.Normalize = object
    mpl.pyplot = plt
    mpl.colors = colors
    sys.modules.setdefault("matplotlib", mpl)
    sys.modules.setdefault("matplotlib.pyplot", plt)
    sys.modules.setdefault("matplotlib.colors", colors)


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def probe(mode):
    if mode == "pinned":
        sys.path.insert(0, ARC_DSL)
        import dsl  # noqa: F401 — pins arc-dsl's copy (mirrors t3)
    _stub_matplotlib()
    sys.path.insert(0, RE_ARC)
    if mode == "pinned":
        # constants.py only exists in arc-dsl; make it importable either way
        sys.path.append(ARC_DSL)
    else:
        sys.path.append(ARC_DSL)  # for `from constants import *` in programs
    import generators
    import verifiers

    with open(f"{ARC_DSL}/solvers.py") as f:
        progs = {tid: PROG_TMPL.format(body=body.rstrip())
                 for tid, body in SOLVER_RE.findall(f.read())}

    rng = random.Random(SEED)
    random.seed(SEED)
    tids = sorted(t for t in progs
                  if hasattr(generators, f"generate_{t}")
                  and hasattr(verifiers, f"verify_{t}"))
    picks = rng.sample(tids, N_TASKS)

    signal.signal(signal.SIGALRM, _alarm)
    out = {"mode": mode, "pairs_generated": 0, "gen_exhausted": 0,
           "solver_pass": 0, "verifier_pass": 0, "solver_error": 0,
           "verifier_error": 0}
    for tid in picks:
        gen = getattr(generators, f"generate_{tid}")
        ver = getattr(verifiers, f"verify_{tid}")
        g = {"__builtins__": __builtins__}
        exec(progs[tid], g)  # noqa: S102 — trusted MIT solver text, diagnostic
        solve = g["solve"]
        got = 0
        for _ in range(PAIRS_PER_TASK * GEN_RETRIES):
            if got >= PAIRS_PER_TASK:
                break
            try:
                signal.alarm(GEN_ALARM_S)
                ex = gen(0.0, 0.5)
                gi = [list(r) for r in ex["input"]]
                go = [list(r) for r in ex["output"]]
            except Exception:  # noqa: BLE001
                continue
            finally:
                signal.alarm(0)
            got += 1
            out["pairs_generated"] += 1
            try:
                signal.alarm(10)
                r = solve([row[:] for row in gi])
                if [[int(c) for c in row] for row in r] == go:
                    out["solver_pass"] += 1
            except Exception:  # noqa: BLE001
                out["solver_error"] += 1
            finally:
                signal.alarm(0)
            try:
                signal.alarm(10)
                ti = tuple(tuple(r) for r in gi)
                vo = ver(ti)
                if [list(r) for r in vo] == go:
                    out["verifier_pass"] += 1
            except Exception:  # noqa: BLE001
                out["verifier_error"] += 1
            finally:
                signal.alarm(0)
        if got < PAIRS_PER_TASK:
            out["gen_exhausted"] += 1
        print(f"task {tid} done got={got}", flush=True)
    print("RESULT " + json.dumps(out), flush=True)


def main():
    results = {}
    for mode in ("pinned", "native"):
        try:
            p = subprocess.run(
                [sys.executable, os.path.abspath(__file__), mode],
                capture_output=True, text=True, timeout=600)
            stdout, stderr = p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or b"").decode(errors="replace") \
                if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = f"MODE TIMEOUT 600s; partial stdout tail: {stdout[-1500:]}"
        for line in stdout.splitlines():
            if line.startswith("RESULT "):
                results[mode] = json.loads(line[7:])
        if mode not in results:
            results[mode] = {"error": (stderr or "no RESULT line")[-2000:]}
        print(f"{mode}: {json.dumps(results[mode])}", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    verdict = "INCONCLUSIVE"
    pn, nv = results.get("pinned", {}), results.get("native", {})
    if pn.get("pairs_generated") and nv.get("pairs_generated"):
        sp = pn["solver_pass"] / pn["pairs_generated"]
        sn = nv["solver_pass"] / nv["pairs_generated"]
        vp = pn["verifier_pass"] / pn["pairs_generated"]
        vn = nv["verifier_pass"] / nv["pairs_generated"]
        if sn > sp + 0.15:
            verdict = "H1: dsl-pinning corrupted generation"
        elif vn > sn + 0.15 and vp > sp + 0.15:
            verdict = "H2: solver/verifier divergence (use verifiers.py text)"
        elif sn >= 0.6 and sp >= 0.6:
            verdict = ("NEITHER at diff<=0.5: t3 losses likely from "
                       "diff_ub 0.7/1.0 variants (difficulty, not bug)")
    receipt = {"ticket": "NC0-T3b-DIAG", "ts": ts,
               "n_tasks": N_TASKS, "pairs_per_task": PAIRS_PER_TASK,
               "diff_ub": 0.5, "results": results, "verdict": verdict}
    os.makedirs(RECEIPTS, exist_ok=True)
    with open(f"{RECEIPTS}/t3b-diag-{ts}.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({"verdict": verdict}))
    print("T3B_DIAG_DONE")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        probe(sys.argv[1])
    else:
        main()
