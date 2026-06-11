"""t1_probe.py — NC0 T1: CORE_ONLY probe on ARC-AGI-1 (the never-run Stage 0').

Samples k Python programs per task from a frozen local model, executes them in
a sandboxed pool, verifies against each task's own train pairs (R5 ground
truth), and records solve on the held test pair (recorded, never fed back).

Modes:
  --selftest          no model; proves the sandbox/verifier on golden cases
  --smoke             N tasks (default 30), k (default 8)
  --full              400 training tasks, k (default 32)

Receipts: /mnt/b/M/avir/leo/state/nc-ladder/receipts/t1-<mode>-<ts>.json
          + per-sample JSONL next to it.
"""

import os

# Single-threaded BLAS in sandbox workers; must precede any numpy import.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
# Loop is local-only: base weights already in HF_HOME cache; any network
# reach must fail loudly, not silently succeed.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# Long-context, varied-length batches fragment the caching allocator badly
# under the VRAM fraction cap (e3d7c490: 4.94GB reserved-but-unallocated at
# OOM). Expandable segments lets the allocator grow blocks instead.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import argparse
import json
import multiprocessing as mp
import re
import resource
import signal
import sys
import time
from datetime import datetime, timezone

# Object-graph reachability guard (#86, eng-23). Hard import, no fallback,
# by design: the sandbox MUST NOT run without the second false-accept class
# (graph traversal) closed. Resolves from the same scripts/ dir on every
# call path (callers insert NC/scripts at sys.path[0] before importing this).
from v_reachguard import scan as _reachguard_scan

ARC_TRAIN = "/mnt/b/M/the-search/incoming/arc-agi1-visa/ARC-AGI/data/training"
RECEIPTS = "/mnt/b/M/avir/leo/state/nc-ladder/receipts"

EXEC_TIMEOUT_S = 4
EXEC_MEM_MB = 4096  # RLIMIT_AS is virtual address space; numpy/OpenBLAS map a lot
MAX_PROMPT_TOKENS = 6000

# ─── task loading ─────────────────────────────────────────────────────────────

def load_tasks(task_dir, limit=None):
    tasks = []
    for name in sorted(os.listdir(task_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(task_dir, name)) as f:
            t = json.load(f)
        tasks.append({
            "id": name[:-5],
            "train": [(p["input"], p["output"]) for p in t["train"]],
            "test": [(p["input"], p["output"]) for p in t["test"]],
        })
        if limit and len(tasks) >= limit:
            break
    return tasks


# ─── prompting ────────────────────────────────────────────────────────────────

def render_grid(g):
    rows = ",\n ".join(json.dumps(row) for row in g)
    return f"[{rows}]"


INSTRUCTIONS = """You are given input/output grid pairs from a reasoning puzzle. Each grid is a Python list of lists of integers 0-9. Every pair is produced by ONE transformation rule. Infer the rule, then implement it.

Reply format:
1. One comment line stating the rule you inferred.
2. ONE fenced python code block defining exactly:
   def solve(grid):  # grid: list[list[int]] -> returns list[list[int]]
   Pure Python and/or numpy; the Hodel ARC grid library is also importable
   (`from dsl import *`, `from constants import *`) if useful. No I/O,
   no printing.
"""


def task_prompt(task):
    parts = [INSTRUCTIONS, "Training pairs:"]
    for i, (gi, go) in enumerate(task["train"], 1):
        parts.append(
            f"\n# Pair {i}: input {len(gi)}x{len(gi[0])} -> "
            f"output {len(go)}x{len(go[0])}\n"
            f"input_{i} = {render_grid(gi)}\n"
            f"output_{i} = {render_grid(go)}")
    parts.append("\nState the rule in one comment line, then write the "
                 "python code block implementing solve.")
    return "\n".join(parts)


CODE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text):
    m = CODE_RE.search(text)
    if m:
        return m.group(1).strip()
    if "def solve" in text:  # unfenced fallback
        start = text.index("def solve")
        # Ledger-style programs (t3_seed PROG_TMPL) put 'from dsl import *'
        # and 'def _impl' ABOVE solve; cutting at solve decapitates them ->
        # guaranteed NameError at runtime (136x '_impl' in t4-r1-q15
        # context_only). Back start up to the earliest of those when present.
        for pat in ("from dsl import", "def _impl"):
            i = text.find(pat)
            if 0 <= i < start:
                start = i
        return text[start:].strip()
    return None


# ─── sandboxed execution ──────────────────────────────────────────────────────

# Unified world library (t3b diag 2026-06-10): dsl resolves to re-arc's copy
# (generation-compatible, verifiers 48/48); constants.py only exists in
# arc-dsl, so both dirs go on the path — re-arc first.
VENDOR_DSL_PATHS = ["/mnt/b/M/avir/leo/state/nc-ladder/vendor/re-arc",
                    "/mnt/b/M/avir/leo/state/nc-ladder/vendor/arc-dsl"]


def _worker_init():
    resource.setrlimit(resource.RLIMIT_AS, (EXEC_MEM_MB * 1024 * 1024,) * 2)
    os.nice(5)
    for p in reversed(VENDOR_DSL_PATHS):
        if p not in sys.path:
            sys.path.insert(0, p)  # makes `import dsl`/`constants` resolvable


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout()


_ALLOWED_IMPORTS = {"math", "itertools", "functools", "collections", "copy",
                    "re", "numpy", "numpy.linalg", "heapq", "bisect",
                    "string", "operator", "fractions", "statistics",
                    # Hodel arc-dsl as world library (seed curriculum, MIT):
                    "dsl", "constants", "arc_types", "typing"}


def _safe_import(name, *args, **kwargs):
    if name.split(".")[0] not in {m.split(".")[0] for m in _ALLOWED_IMPORTS}:
        raise ImportError(f"import of '{name}' not allowed")
    return __import__(name, *args, **kwargs)


def run_program(args):
    """Executes one program against one task's pairs. Returns dict verdict."""
    src, train_pairs, test_pairs = args
    import builtins
    safe_builtins = {k: getattr(builtins, k) for k in dir(builtins)
                     if k not in {"open", "input", "exec", "eval", "compile",
                                  "exit", "quit", "help", "breakpoint"}}
    safe_builtins["__import__"] = _safe_import
    g = {"__builtins__": safe_builtins}
    signal.signal(signal.SIGALRM, _alarm)
    out = {"compiled": False, "train_pass": 0, "train_total": len(train_pairs),
           "verified": False, "solved": False, "error": None}
    # Reachability guard (#86): refuse object-graph traversal to non-allow-listed
    # objects BEFORE exec. Fail-closed — flagged source returns a normal FAIL
    # verdict with a REACHGUARD: sentinel (prefix-first; truncated to 200).
    _reach = _reachguard_scan(src)
    if _reach:
        out["error"] = _reach
        return out
    try:
        signal.alarm(EXEC_TIMEOUT_S)
        exec(src, g)  # noqa: S102 — sandboxed worker, rlimit+alarm+import-whitelist
        solve = g.get("solve")
        if not callable(solve):
            out["error"] = "no solve()"
            return out
        out["compiled"] = True
        for gi, go in train_pairs:
            r = solve([row[:] for row in gi])
            if _grids_equal(r, go):
                out["train_pass"] += 1
            else:
                return out
        out["verified"] = out["train_pass"] == out["train_total"]
        if out["verified"]:
            ok = all(_grids_equal(solve([row[:] for row in gi]), go)
                     for gi, go in test_pairs)
            out["solved"] = ok
    except _Timeout:
        out["error"] = "timeout"
    except MemoryError:
        out["error"] = "memory"
    except Exception as e:  # noqa: BLE001 — any program failure is a verdict
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    finally:
        signal.alarm(0)
    return out


def _grids_equal(a, b):
    try:
        if hasattr(a, "tolist"):
            a = a.tolist()
        if not isinstance(a, list) or not a:
            return False
        return [[int(c) for c in row] for row in a] == b
    except Exception:  # noqa: BLE001
        return False


# Headroom rule (user 2026-06-10: "100% should never be the case, for both
# GPU and CPU"): duty-cycle pause between GPU batches, and CPU pools capped
# below the core count. Tunable via EMBER_THROTTLE_S without code edits.
THROTTLE_S = float(os.environ.get("EMBER_THROTTLE_S", "0.6"))

# Governor receipt block, filled by load_model via governor.preflight()
# (eng #14: limits ride on receipts instead of being asserted in prose).
GOV = {}
EXEC_WORKERS = max(2, min(6, (os.cpu_count() or 8) - 2))
# Per-batch sleep is too sparse for long generations (one eval batch = 3-4
# min continuous kernel time → duty 99.7%, observed pegged 100% during t4
# s14). Decode-step pacer: pause inside generation, every N decode steps.
PACE_EVERY = int(os.environ.get("EMBER_DECODE_PAUSE_EVERY", "32"))
PACE_S = float(os.environ.get("EMBER_DECODE_PAUSE_S", "0.5"))


def decode_pacer():
    """StoppingCriteriaList that sleeps PACE_S every PACE_EVERY decode steps
    (~94% GPU duty at 768-token generations) and never stops generation."""
    from transformers import StoppingCriteria, StoppingCriteriaList

    class _Pacer(StoppingCriteria):
        def __init__(self):
            self.n = 0

        def __call__(self, input_ids, scores, **kw):
            self.n += 1
            if PACE_EVERY > 0 and self.n % PACE_EVERY == 0:
                time.sleep(PACE_S)
            return False

    return StoppingCriteriaList([_Pacer()])


def execute_batch(jobs, workers=EXEC_WORKERS):
    """jobs: list of (src, train_pairs, test_pairs). Pool with per-job timeout."""
    results = [None] * len(jobs)
    with mp.get_context("fork").Pool(workers, initializer=_worker_init,
                                     maxtasksperchild=16) as pool:
        async_results = [pool.apply_async(run_program, (j,)) for j in jobs]
        for i, ar in enumerate(async_results):
            try:
                results[i] = ar.get(timeout=EXEC_TIMEOUT_S + 6)
            except Exception:  # noqa: BLE001 — stuck/killed worker
                results[i] = {"compiled": False, "train_pass": 0,
                              "train_total": len(jobs[i][1]), "verified": False,
                              "solved": False, "error": "pool-timeout"}
    return results


# ─── self-test ────────────────────────────────────────────────────────────────

def selftest():
    ident = {"train": [([[1, 2]], [[1, 2]])], "test": [([[3]], [[3]])]}
    transpose = {"train": [([[1, 2], [3, 4]], [[1, 3], [2, 4]])],
                 "test": [([[5, 6]], [[5], [6]])]}
    cases = [
        ("identity-correct", "def solve(grid):\n    return grid", ident,
         {"verified": True, "solved": True}),
        ("transpose-correct",
         "import numpy as np\ndef solve(grid):\n    return np.array(grid).T.tolist()",
         transpose, {"verified": True, "solved": True}),
        ("transpose-wrong", "def solve(grid):\n    return grid", transpose,
         {"verified": False}),
        ("infinite-loop", "def solve(grid):\n    while True:\n        pass", ident,
         {"verified": False, "error": "timeout"}),
        ("memory-bomb", "def solve(grid):\n    x=[0]*(10**9)\n    return grid",
         ident, {"verified": False}),
        ("malformed", "def solve(grid)\n    return grid", ident,
         {"verified": False}),
        ("bad-import", "import socket\ndef solve(grid):\n    return grid", ident,
         {"verified": False}),
    ]
    jobs = [(src, c["train"], c["test"]) for _, src, c, _ in cases]
    results = execute_batch(jobs, workers=4)
    report, ok_all = [], True
    for (name, _, _, want), got in zip(cases, results):
        ok = all(
            (got.get(k) == v) if k != "error" else (v in str(got.get("error")))
            for k, v in want.items()
        )
        ok_all &= ok
        report.append({"case": name, "ok": ok, "got": got})
    return ok_all, report


# ─── sampling ─────────────────────────────────────────────────────────────────

def load_model(model_id, adapter=None):
    """One model load, reusable across generate() calls (chunked runs)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    # Resource governor (post-crash 2026-06-10, the user headroom rule — LAUNCH
    # PRECONDITION, not politeness; crash context 0670e3ec documented in
    # governor.py, the single canonical copy since eng #14). Cap + margin
    # assert; receipt block stashed for the summary writer. The decode pacer
    # (THROTTLE_S=0.6 above) is generation-side and intentionally NOT the
    # module's train-step throttle.
    from governor import preflight
    GOV.update(preflight())

    tok = AutoTokenizer.from_pretrained(model_id, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(
        model_id, device_map="cuda", torch_dtype="auto")
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
        # Merge LoRA into the base weights: PEFT's runtime path keeps the
        # adapter unmerged and adds per-token lora_B(lora_A(x)) activations —
        # e3d7c490 OOM'd exactly there under the VRAM cap while the frozen
        # base arm passed. Merged = identical math (W + B@A), and adapter
        # arms get the same memory profile as the base.
        model = model.merge_and_unload()
    model.eval()
    return model, tok


def sample_model(model_id, tasks, k, batch_size, max_new, temp, seed,
                 adapter=None):
    model, tok = load_model(model_id, adapter=adapter)
    return generate(model, tok, tasks, k, batch_size, max_new, temp, seed)


def generate(model, tok, tasks, k, batch_size, max_new, temp, seed):
    import torch

    torch.manual_seed(seed)
    prompts, meta = [], []
    for t in tasks:
        text = tok.apply_chat_template(
            [{"role": "user", "content": task_prompt(t)}],
            tokenize=False, add_generation_prompt=True)
        n_tok = len(tok(text).input_ids)
        if n_tok > MAX_PROMPT_TOKENS:
            meta.append({"task": t["id"], "skipped": "prompt-too-long",
                         "prompt_tokens": n_tok})
            continue
        for _ in range(k):
            prompts.append(text)
            meta.append({"task": t["id"], "prompt_tokens": n_tok})

    # Sort by prompt length so batches are homogeneous (kills padding waste).
    gen_meta = [m for m in meta if "skipped" not in m]
    order = sorted(range(len(prompts)),
                   key=lambda i: gen_meta[i]["prompt_tokens"])
    prompts = [prompts[i] for i in order]
    gen_meta = [gen_meta[i] for i in order]
    completions, gen_tokens, t0 = [], 0, time.time()
    for i in range(0, len(prompts), batch_size):
        chunk = prompts[i:i + batch_size]
        enc = tok(chunk, return_tensors="pt", padding=True).to("cuda")
        with torch.no_grad():
            out = model.generate(
                **enc, do_sample=True, temperature=temp, top_p=0.95,
                max_new_tokens=max_new, pad_token_id=tok.pad_token_id
                or tok.eos_token_id, stopping_criteria=decode_pacer())
        new = out[:, enc.input_ids.shape[1]:]
        gen_tokens += int((new != (tok.pad_token_id or tok.eos_token_id)).sum())
        completions.extend(tok.batch_decode(new, skip_special_tokens=True))
        done = min(i + batch_size, len(prompts))
        print(f"GEN {done}/{len(prompts)} "
              f"({gen_tokens / max(time.time() - t0, 1):.0f} tok/s)", flush=True)
        time.sleep(THROTTLE_S)  # headroom rule: GPU never pegged wall-to-wall
    return gen_meta, completions, meta, gen_tokens, time.time() - t0


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["selftest", "smoke", "full"], required=True)
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit")
    ap.add_argument("--n-tasks", type=int, default=30)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-new", type=int, default=768)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=14)
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(RECEIPTS, exist_ok=True)
    receipt_path = os.path.join(RECEIPTS, f"t1-{args.mode}-{ts}.json")
    receipt = {"ticket": "NC0-T1", "mode": args.mode, "ts": ts,
               "args": vars(args)}

    if args.mode == "selftest":
        ok, report = selftest()
        receipt["selftest_ok"] = ok
        receipt["cases"] = report
        with open(receipt_path, "w") as f:
            json.dump(receipt, f, indent=2)
        print(json.dumps(report, indent=2))
        print(f"SELFTEST {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)

    limit = args.n_tasks if args.mode == "smoke" else None
    tasks = load_tasks(ARC_TRAIN, limit=limit)
    by_id = {t["id"]: t for t in tasks}
    print(f"tasks={len(tasks)} k={args.k} model={args.model}", flush=True)

    gen_meta, completions, all_meta, gen_tokens, gen_secs = sample_model(
        args.model, tasks, args.k, args.batch_size, args.max_new,
        args.temp, args.seed)

    jobs, job_meta = [], []
    for m, comp in zip(gen_meta, completions):
        src = extract_code(comp)
        t = by_id[m["task"]]
        if src is None:
            job_meta.append({**m, "extracted": False})
            continue
        job_meta.append({**m, "extracted": True, "job_idx": len(jobs)})
        jobs.append((src, t["train"], t["test"]))

    print(f"executing {len(jobs)} programs...", flush=True)
    results = execute_batch(jobs)

    samples_path = receipt_path.replace(".json", "-samples.jsonl")
    per_task = {}
    with open(samples_path, "w") as f:
        for i, m in enumerate(job_meta):
            if m.get("extracted"):
                r = results[m["job_idx"]]
                row = {**m, **r, "src": jobs[m["job_idx"]][0]}
            else:
                r = {"verified": False, "solved": False, "error": "no-code-block"}
                row = {**m, **r, "raw_tail": completions[i][-300:]}
            f.write(json.dumps(row) + "\n")
            pt = per_task.setdefault(m["task"], {"verified": False, "solved": False})
            pt["verified"] |= bool(r.get("verified"))
            pt["solved"] |= bool(r.get("solved"))

    n = len(per_task)
    receipt["summary"] = {
        "tasks_sampled": n,
        "tasks_skipped_prompt_len": sum(1 for m in all_meta if m.get("skipped")),
        "verify_any_pct": round(100 * sum(t["verified"] for t in per_task.values()) / max(n, 1), 2),
        "solve_any_pct": round(100 * sum(t["solved"] for t in per_task.values()) / max(n, 1), 2),
        "programs_executed": len(jobs),
        "extraction_rate_pct": round(100 * len(jobs) / max(len(job_meta), 1), 2),
        "gen_tokens": int(gen_tokens),
        "gen_secs": round(gen_secs, 1),
        "gen_tok_per_s": round(gen_tokens / max(gen_secs, 1), 1),
    }
    if GOV:
        receipt["governor"] = dict(GOV)
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt["summary"], indent=2))
    print("T1_PROBE_DONE")


if __name__ == "__main__":
    main()
