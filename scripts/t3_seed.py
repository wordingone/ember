"""t3_seed.py — NC0 T3: seed-curriculum builder (K1 curriculum redirect).

Renders Hodel arc-dsl solvers (MIT; verified programs for all 400 ARC-AGI-1
training tasks) + re-arc procedural generators (MIT; fresh pairs per task)
into ember seed episodes. EVERY program is re-verified in OUR sandbox before
it enters the ledger — seed episodes carry our receipts, not upstream claims.
SOAR (arXiv 2507.14172) is the published precedent that seeded expert
iteration moves this exact base model from ~1% to 36%; the seed data here is
built locally instead of importing SOAR's ledger.

Phases:
  A. parse solvers.py -> standalone `def solve(grid)` programs (dsl = world lib)
  B. sandbox-verify all programs against ORIGINAL task pairs
  C. re-arc augmentation: fresh pairs -> variant tasks -> sandbox-verify each
  D. emit ledger/episodes.jsonl (inline pairs) + ledger/control_pool.jsonl
     (wrong-task pairings, confirmed-FAIL in sandbox)

No model, no GPU — pure CPU. Receipt: receipts/t3-seed-<ts>.json
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import hashlib
import json
import random
import re
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
ARC_DSL = f"{NC}/vendor/arc-dsl"
RE_ARC = f"{NC}/vendor/re-arc"
LEDGER_DIR = f"{NC}/ledger"
RECEIPTS = f"{NC}/receipts"
EPISODES = f"{LEDGER_DIR}/episodes.jsonl"
CONTROL_POOL = f"{LEDGER_DIR}/control_pool.jsonl"

sys.path.insert(0, f"{NC}/scripts")
from t1_probe import (ARC_TRAIN, execute_batch, load_tasks,  # noqa: E402
                      task_prompt)

SEED = 14
N_VARIANTS = 4                      # augmented variants per task
DIFFS = [0.3, 0.5, 0.7, 1.0]        # diff_ub ladder across variants
PAIRS_PER_VARIANT = 4               # 3 train + 1 test
GEN_RETRIES = 12
MAX_PROMPT_CHARS = 10000            # ~2.8k tokens; keeps train seqs in budget
MAX_GRID_DIM = 30

# v2 (t3b diag receipt 20260610T015000Z): generation runs NATIVE under
# re-arc's dsl (no pinning); augmented episodes use re-arc verifiers.py as
# program text (48/48 on generated pairs vs solvers' 25/48); sandbox world
# library unified on re-arc's dsl (t1_probe.VENDOR_DSL_PATHS). Original-pair
# episodes still use arc-dsl solvers.py text. Everything re-verified here.
SOLVER_RE = re.compile(
    r"^def solve_([0-9a-f]{8})\(I\):\n(.*?)(?=^def |\Z)", re.M | re.S)
VERIFIER_RE = re.compile(
    r"^def verify_([0-9a-f]{8})\(I[^)]*\)[^\n]*:\n(.*?)(?=^def |\Z)",
    re.M | re.S)

PROG_TMPL = """from dsl import *
from constants import *

def _impl(I):
{body}

def solve(grid):
    I = tuple(tuple(row) for row in grid)
    O = _impl(I)
    return [list(row) for row in O]
"""


def sha16(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def parse_solvers():
    with open(f"{ARC_DSL}/solvers.py") as f:
        src = f.read()
    progs = {}
    for tid, body in SOLVER_RE.findall(src):
        progs[tid] = PROG_TMPL.format(body=body.rstrip())
    return progs


def parse_verifiers():
    with open(f"{RE_ARC}/verifiers.py") as f:
        src = f.read()
    progs = {}
    for tid, body in VERIFIER_RE.findall(src):
        progs[tid] = PROG_TMPL.format(body=body.rstrip())
    return progs


def grid_ok(g):
    return (isinstance(g, (list, tuple)) and 0 < len(g) <= MAX_GRID_DIM
            and all(isinstance(r, (list, tuple))
                    and 0 < len(r) <= MAX_GRID_DIM for r in g))


def gen_pairs(gen, diff_ub, n, rng):
    pairs = []
    for _ in range(n):
        for _attempt in range(GEN_RETRIES):
            try:
                ex = gen(0.0, diff_ub)
                gi = [list(r) for r in ex["input"]]
                go = [list(r) for r in ex["output"]]
                if grid_ok(gi) and grid_ok(go):
                    pairs.append((gi, go))
                    break
            except Exception:  # noqa: BLE001 — generator misfire, retry
                continue
        else:
            return None
    return pairs


def append_dedup(path, recs):
    seen = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["key"])
                except Exception:  # noqa: BLE001
                    continue
    written = 0
    with open(path, "a") as f:
        for r in recs:
            if r["key"] in seen:
                continue
            seen.add(r["key"])
            f.write(json.dumps(r) + "\n")
            written += 1
    return written


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    random.seed(SEED)  # re-arc utils use the global random module
    os.makedirs(LEDGER_DIR, exist_ok=True)
    os.makedirs(RECEIPTS, exist_ok=True)
    # v2 builds the seed ledger FRESH; archive any v1 files (don't mix
    # solver-text and verifier-text variants of the same episodes).
    for p in (EPISODES, CONTROL_POOL):
        if os.path.exists(p):
            os.replace(p, p + ".v1-archived")

    tasks = {t["id"]: t for t in load_tasks(ARC_TRAIN)}
    progs = parse_solvers()
    vprogs = parse_verifiers()
    print(f"parsed {len(progs)} solvers, {len(vprogs)} verifiers, "
          f"{len(tasks)} tasks", flush=True)

    # v2: NATIVE imports — re-arc's dsl loads first and is the sandbox world
    # library too (t1_probe.VENDOR_DSL_PATHS). No pinning (t3b H1).
    # re-arc's utils.py imports matplotlib at module level purely for its
    # plotting helpers; the generators never touch it. Stub it out instead of
    # installing a plotting stack into the shared training venv.
    import types
    _mpl = types.ModuleType("matplotlib")
    _plt = types.ModuleType("matplotlib.pyplot")
    _colors = types.ModuleType("matplotlib.colors")
    _colors.ListedColormap = object
    _colors.Normalize = object
    _mpl.pyplot = _plt
    _mpl.colors = _colors
    sys.modules.setdefault("matplotlib", _mpl)
    sys.modules.setdefault("matplotlib.pyplot", _plt)
    sys.modules.setdefault("matplotlib.colors", _colors)
    sys.path.insert(0, ARC_DSL)   # constants.py for exec'd programs (main)
    sys.path.insert(0, RE_ARC)    # dsl resolves to re-arc's copy
    import generators  # noqa: E402

    # Phase B — verify every solver program against ORIGINAL task pairs,
    # under the unified (re-arc) dsl the forked workers inherit.
    tids = sorted(set(progs) & set(tasks))
    jobs = [(progs[tid], tasks[tid]["train"], tasks[tid]["test"])
            for tid in tids]
    results = execute_batch(jobs)
    verified_orig, failed_orig = [], []
    for tid, r in zip(tids, results):
        if r.get("verified"):
            verified_orig.append((tid, bool(r.get("solved"))))
        else:
            failed_orig.append({"task": tid, "error": r.get("error"),
                                "train_pass": r.get("train_pass")})
    print(f"phase B: {len(verified_orig)}/{len(tids)} verified on original "
          f"pairs ({len(failed_orig)} failed)", flush=True)

    # Phase C — re-arc augmentation -> variant tasks -> sandbox verify.
    # Program text for augmented episodes = re-arc verifiers.py (t3b H2).
    variant_jobs, variant_meta = [], []
    gen_fail, prompt_skips, no_generator = [], 0, []
    for tid, _solved in verified_orig:
        gen = getattr(generators, f"generate_{tid}", None)
        if gen is None or tid not in vprogs:
            no_generator.append(tid)
            continue
        for v in range(N_VARIANTS):
            pairs = gen_pairs(gen, DIFFS[v], PAIRS_PER_VARIANT, rng)
            if pairs is None:
                gen_fail.append(f"{tid}#a{v}")
                continue
            variant = {"id": f"{tid}#a{v}", "train": pairs[:3],
                       "test": pairs[3:]}
            if len(task_prompt(variant)) > MAX_PROMPT_CHARS:
                prompt_skips += 1
                continue
            variant_jobs.append((vprogs[tid], variant["train"],
                                 variant["test"]))
            variant_meta.append((tid, variant))
    print(f"phase C: {len(variant_jobs)} variant jobs "
          f"(gen_fail={len(gen_fail)}, prompt_skips={prompt_skips}, "
          f"no_generator={len(no_generator)})", flush=True)
    vresults = execute_batch(variant_jobs)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    episodes = []
    for tid, solved in verified_orig:
        episodes.append({
            "task": tid, "src": progs[tid], "pairs": tasks[tid]["train"],
            "test": tasks[tid]["test"], "verified": True, "solved": solved,
            "origin": "seed-dsl-orig", "ts": ts,
            "key": f"{tid}:{sha16(progs[tid])}"})
    aug_verified = 0
    for (tid, variant), r in zip(variant_meta, vresults):
        if r.get("verified") and r.get("solved"):
            aug_verified += 1
            episodes.append({
                "task": variant["id"], "src": vprogs[tid],
                "pairs": variant["train"], "test": variant["test"],
                "verified": True, "solved": True,
                "origin": "seed-verifier-rearc-v2", "ts": ts,
                "key": f"{variant['id']}:{sha16(vprogs[tid])}"})

    # Phase D — control pool: wrong-task programs on each episode's pairs,
    # kept only when the sandbox CONFIRMS verification failure.
    ctrl_jobs, ctrl_meta = [], []
    vtids = [tid for tid, _ in verified_orig]
    for ep in episodes:
        wrong = rng.choice(vtids)
        base = ep["task"].split("#")[0]
        while wrong == base and len(vtids) > 1:
            wrong = rng.choice(vtids)
        ctrl_jobs.append((progs[wrong], ep["pairs"], ep["test"]))
        ctrl_meta.append((ep, wrong))
    cresults = execute_batch(ctrl_jobs)
    controls, accidental_pass = [], 0
    for (ep, wrong), r in zip(ctrl_meta, cresults):
        if r.get("verified"):
            accidental_pass += 1
            continue
        controls.append({
            "task": ep["task"], "src": progs[wrong], "pairs": ep["pairs"],
            "test": ep["test"], "verified": False,
            "origin": "seed-control-wrongtask", "ts": ts,
            "key": f"{ep['task']}:ctrl:{sha16(progs[wrong])}"})

    n_ep = append_dedup(EPISODES, episodes)
    n_ctrl = append_dedup(CONTROL_POOL, controls)

    receipt = {
        "ticket": "NC0-T3-SEED-v2", "ts": ts, "seed": SEED,
        "v2": "native re-arc dsl generation; verifiers.py text for augmented "
              "episodes; unified sandbox dsl; fresh ledger (v1 archived)",
        "config": {"n_variants": N_VARIANTS, "diffs": DIFFS,
                   "pairs_per_variant": PAIRS_PER_VARIANT,
                   "max_prompt_chars": MAX_PROMPT_CHARS},
        "phase_a": {"solvers_parsed": len(progs)},
        "phase_b": {"verified_orig": len(verified_orig),
                    "failed_orig": failed_orig},
        "phase_c": {"variant_jobs": len(variant_jobs),
                    "aug_verified": aug_verified,
                    "gen_fail": gen_fail[:50],
                    "gen_fail_count": len(gen_fail),
                    "prompt_skips": prompt_skips,
                    "no_generator": no_generator},
        "phase_d": {"controls_written": n_ctrl,
                    "accidental_pass_dropped": accidental_pass},
        "episodes_total": len(episodes), "episodes_written_new": n_ep,
        "secs": round(time.time() - t0, 1),
    }
    path = f"{RECEIPTS}/t3-seed-{ts}.json"
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: receipt[k] for k in
                      ("episodes_total", "episodes_written_new")}, indent=2))
    print(f"phase B verified {len(verified_orig)}, aug {aug_verified}, "
          f"controls {n_ctrl}", flush=True)
    print("T3_SEED_DONE")


if __name__ == "__main__":
    main()
