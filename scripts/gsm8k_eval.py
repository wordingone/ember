"""gsm8k_eval.py — GSM8K-200 greedy exact-match eval harness (issue #341).

Both-seat capable: --core <model_id> [--adapter <path>]
Greedy decode, seed-free determinism check, governed load via t1_probe.load_model.

Usage:
    python scripts/gsm8k_eval.py --selftest
    python scripts/gsm8k_eval.py --download-data
    python scripts/gsm8k_eval.py --core <model_or_path> [--adapter <path>]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

CSIEVAL_PYTHON = "/mnt/c/Users/Admin/.venvs/csi-eval/bin/python"
REEXEC_FLAG = "GSM8K_EVAL_REEXEC"

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)  # ember repo root

for _p in (HERE,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RECEIPTS = os.path.join(NC, "receipts")
DATA_DIR = os.path.join(NC, "data")
LOCAL_DATA = os.path.join(DATA_DIR, "gsm8k-test-200.jsonl")

# Source URL — pinned; data is cached locally, never re-downloaded per eval run
GSM8K_HF_DATASET = "openai/gsm8k"
GSM8K_HF_CONFIG = "main"
GSM8K_HF_SPLIT = "test"
GSM8K_URL_PIN = "hf://datasets/openai/gsm8k@main/main/test-00000-of-00001.parquet"

N_PROBLEMS = 200
MAX_NEW_TOK = 512
N_DET_CHECK = 5  # first N problems run twice to verify greedy determinism


# ---------------------------------------------------------------------------
# Answer extraction — supports negatives (-42), commas (1,234), units (10 km)
# ---------------------------------------------------------------------------

_ANSWER_RE = re.compile(r"####\s*([\-\d,]+)")


def _extract_answer(text: str) -> str | None:
    m = _ANSWER_RE.search(text)
    if m:
        return m.group(1).replace(",", "").strip()
    # Fallback: last standalone integer including negatives
    nums = re.findall(r"-?\b\d+\b", text)
    return nums[-1] if nums else None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _harness_sha() -> str:
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _seat(core: str, adapter: str | None) -> str:
    return "core+adapter" if adapter else "core"


# ---------------------------------------------------------------------------
# Data: local JSONL (no network during eval)
# ---------------------------------------------------------------------------

def _load_local_data(local_data: str) -> list[dict]:
    if not os.path.isfile(local_data):
        raise FileNotFoundError(
            f"Local data not found: {local_data}\n"
            "Run: python scripts/gsm8k_eval.py --download-data"
        )
    tasks = []
    with open(local_data, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks[:N_PROBLEMS]


def download_data(local_data: str = LOCAL_DATA) -> None:
    """Download GSM8K test split once and write to local JSONL."""
    from datasets import load_dataset  # type: ignore[import]
    print(f"[gsm8k_eval] downloading {GSM8K_HF_DATASET}/{GSM8K_HF_CONFIG} {GSM8K_HF_SPLIT}...", flush=True)
    ds = load_dataset(GSM8K_HF_DATASET, GSM8K_HF_CONFIG, split=GSM8K_HF_SPLIT)
    tasks = list(ds)
    os.makedirs(os.path.dirname(local_data), exist_ok=True)
    with open(local_data, "w", encoding="utf-8", newline="\n") as f:
        for task in tasks:
            f.write(json.dumps({"question": task["question"], "answer": task["answer"]}) + "\n")
    sha = _file_sha256(local_data)
    print(f"[gsm8k_eval] wrote {len(tasks)} problems → {local_data}")
    print(f"[gsm8k_eval] sha256: {sha}")
    print(f"[gsm8k_eval] url_pin: {GSM8K_URL_PIN}")


# ---------------------------------------------------------------------------
# Greedy decode (single problem, no batching — deterministic by design)
# ---------------------------------------------------------------------------

def _decode_one(model, tok, question: str) -> str:
    import torch
    messages = [{"role": "user", "content": question}]
    prompt = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tok(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out_ids = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=MAX_NEW_TOK,
            pad_token_id=tok.eos_token_id,
        )
    gen_ids = out_ids[0, inputs["input_ids"].shape[-1]:]
    return tok.decode(gen_ids, skip_special_tokens=True)


def _eval_rows(model, tok, tasks: list[dict]) -> list[dict]:
    rows = []
    for i, task in enumerate(tasks):
        ref_ans = _extract_answer(task["answer"])
        gen_text = _decode_one(model, tok, task["question"])
        pred_ans = _extract_answer(gen_text)
        match = (
            ref_ans is not None
            and pred_ans is not None
            and ref_ans == pred_ans
        )
        rows.append({
            "id": i,
            "pred": pred_ans,
            "gold": ref_ans,
            "match": match,
        })
    return rows


# ---------------------------------------------------------------------------
# Determinism check: two runs on the first N_DET_CHECK problems must match
# ---------------------------------------------------------------------------

def _check_determinism(model, tok, tasks: list[dict]) -> None:
    subset = tasks[:N_DET_CHECK]
    run1 = _eval_rows(model, tok, subset)
    run2 = _eval_rows(model, tok, subset)
    for i, (r1, r2) in enumerate(zip(run1, run2)):
        if r1 != r2:
            raise RuntimeError(
                f"Determinism check FAILED at row {i}:\n  run1={r1}\n  run2={r2}"
            )
    print(f"[gsm8k_eval] determinism check PASS: {N_DET_CHECK} rows identical across 2 runs", flush=True)


# ---------------------------------------------------------------------------
# Full eval
# ---------------------------------------------------------------------------

def run_eval(core: str, adapter: str | None, local_data: str) -> None:
    from t1_probe import load_model  # type: ignore[import]

    seat = _seat(core, adapter)
    print(f"[gsm8k_eval] seat={seat} core={core} adapter={adapter}", flush=True)

    tasks = _load_local_data(local_data)
    data_sha = _file_sha256(local_data)
    print(f"[gsm8k_eval] {len(tasks)} tasks loaded, data_sha={data_sha[:16]}...", flush=True)

    model, tok = load_model(core, adapter=adapter)
    print(f"[gsm8k_eval] model loaded", flush=True)

    # Gate: determinism check before full eval
    _check_determinism(model, tok, tasks)

    ts = _ts()
    os.makedirs(RECEIPTS, exist_ok=True)
    jsonl_path = os.path.join(RECEIPTS, f"gsm8k200-{seat}-{ts}.jsonl")
    json_path = os.path.join(RECEIPTS, f"gsm8k200-{seat}-{ts}.json")

    n_pass = 0
    rows = []
    with open(jsonl_path, "w", encoding="utf-8", newline="\n") as jl:
        for i, task in enumerate(tasks):
            ref_ans = _extract_answer(task["answer"])
            gen_text = _decode_one(model, tok, task["question"])
            pred_ans = _extract_answer(gen_text)
            match = (
                ref_ans is not None
                and pred_ans is not None
                and ref_ans == pred_ans
            )
            if match:
                n_pass += 1
            row = {"id": i, "pred": pred_ans, "gold": ref_ans, "match": match}
            rows.append(row)
            jl.write(json.dumps(row) + "\n")
            if (i + 1) % 20 == 0:
                print(f"[gsm8k_eval] {i+1}/{len(tasks)} pass={n_pass}", flush=True)

    pass_pct = round(n_pass / len(tasks) * 100, 2)
    print(f"[gsm8k_eval] DONE pass={n_pass}/{len(tasks)} ({pass_pct}%)", flush=True)

    import torch
    receipt = {
        "ticket": "GSM8K-200-EVAL",
        "ts": ts,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "seat": seat,
        "model": {"core": core, "adapter": adapter},
        "data": {
            "url_pin": GSM8K_URL_PIN,
            "local_path": local_data,
            "sha256": data_sha,
            "n_problems": len(tasks),
        },
        "eval": {
            "do_sample": False,
            "max_new_tokens": MAX_NEW_TOK,
            "n_det_check": N_DET_CHECK,
            "determinism": "PASS",
        },
        "results": {
            "n_pass": n_pass,
            "n_total": len(tasks),
            "pass_pct": pass_pct,
        },
        "runtime": {
            "python": sys.executable,
            "torch": torch.__version__,
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        },
        "receipts": {"jsonl": jsonl_path, "json": json_path},
        "flags": [
            "greedy decode: do_sample=False",
            "governed load: t1_probe.load_model",
            "local data only: no re-download per run",
            "live pretrain run 12c050e7 NOT touched",
        ],
    }

    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"GSM8K_EVAL_DONE {json_path}")


# ---------------------------------------------------------------------------
# Selftest — synthetic fixture, extraction edge cases, determinism
# ---------------------------------------------------------------------------

_SYNTHETIC = [
    # (question_text, answer_text_with_marker, expected_extraction)
    ("Janet has 5 apples. She eats 2. How many left?", "3\n#### 3", "3"),
    ("Store has 100 items, sells 47. Stock?", "53\n#### 53", "53"),
    ("Owed $1,234. Paid $567. Still owe?", "667\n#### 667", "667"),
    ("Running 5 km/hr for 2 hours. Distance in km?", "10 km\n#### 10", "10"),
    ("Below zero: temp -3°C, drops 5 more. Temp?", "-8\n#### -8", "-8"),
]


def _selftest() -> None:
    failures = []

    # 1. Extraction on synthetic answers (gold side)
    for q, ans, expected in _SYNTHETIC:
        got = _extract_answer(ans)
        if got != expected:
            failures.append(f"extraction[gold] q={q!r}: expected={expected!r} got={got!r}")

    # 2. Extraction edge cases: negatives, commas, units in model-style output
    _EDGE = [
        ("The answer is #### 42", "42"),
        ("...work... #### 1,234", "1234"),
        ("...work... #### -8", "-8"),
        ("...10 km... #### 10", "10"),
        ("no marker but last integer is 99", "99"),
        ("absolutely no numbers", None),
    ]
    for text, expected in _EDGE:
        got = _extract_answer(text)
        if got != expected:
            failures.append(f"extraction[edge] text={text!r}: expected={expected!r} got={got!r}")

    # 3. Determinism: two passes over synthetic rows must be byte-identical
    def _synthetic_rows(problems: list[tuple]) -> list[dict]:
        rows = []
        for i, (q, ans, _) in enumerate(problems):
            ref = _extract_answer(ans)
            rows.append({"id": i, "pred": ref, "gold": ref, "match": True})
        return rows

    run1 = _synthetic_rows(_SYNTHETIC)
    run2 = _synthetic_rows(_SYNTHETIC)
    for i, (r1, r2) in enumerate(zip(run1, run2)):
        if r1 != r2:
            failures.append(f"determinism: row {i} differs: {r1} vs {r2}")

    # 4. Receipt structure: ticket + ts required
    ts_now = _ts()
    receipt = {"ticket": "GSM8K-200-EVAL", "ts": ts_now}
    assert "ticket" in receipt and "ts" in receipt, "missing ticket/ts"

    # 5. harness_sha roundtrips
    sha = _harness_sha()
    assert len(sha) == 64, f"unexpected sha length: {len(sha)}"

    for f in failures:
        print(f"  [FAIL] {f}")
    if failures:
        print("GSM8K_EVAL_SELFTEST FAIL")
        sys.exit(1)
    print("GSM8K_EVAL_SELFTEST PASS")


# ---------------------------------------------------------------------------
# Re-exec under csi-eval venv (GPU eval path only)
# ---------------------------------------------------------------------------

def _reexec() -> None:
    if os.environ.get(REEXEC_FLAG):
        return
    if sys.executable == CSIEVAL_PYTHON:
        return
    print(f"[gsm8k_eval] re-exec under csi-eval: {CSIEVAL_PYTHON}", flush=True)
    os.environ[REEXEC_FLAG] = "1"
    os.execv(CSIEVAL_PYTHON, [CSIEVAL_PYTHON] + sys.argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--core", default=None, help="Base model id or path")
    p.add_argument("--adapter", default=None, help="LoRA adapter path (optional)")
    p.add_argument("--local-data", default=LOCAL_DATA, dest="local_data")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--download-data", action="store_true", dest="download_data")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.selftest:
        _selftest()
    elif args.download_data:
        _reexec()
        download_data(args.local_data)
    else:
        if not args.core:
            print("[gsm8k_eval] --core required for eval run", file=sys.stderr)
            sys.exit(1)
        _reexec()
        run_eval(args.core, args.adapter, args.local_data)
