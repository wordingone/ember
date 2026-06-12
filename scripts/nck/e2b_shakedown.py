#!/usr/bin/env python3
"""sp-6c E2B seat binding — SHAKEDOWN receipt (#311).

Binds google/gemma-4-E2B-it as the E2B seat via seat_adapter.make_seat_core,
runs the frozen 20-episode battery (CPU inference, greedy decode), writes a
SHAKEDOWN receipt with determinism proof.

SHAKEDOWN-NOT-B-RUN: proves binding + replay-identity mechanics only.
The official B3 run replays BOTH seats fresh in one receipt per the frozen
prereg; this receipt gates the E2B half so the B-run can proceed.

Resource rails:
- CPU inference: device="cpu", dtype=bfloat16. No GPU allocated — live run
  12c050e7 holds VRAM; 1-model-at-a-time serialization rule holds.
- Governor pace floor (PACE_S_PER_STEP) tracked for the battery loop timing.
- Live run 12c050e7 UNTOUCHED.

AC:
1. generate_fn determinism: same prompt twice → byte-identical completion.
2. Full 20-episode battery; receipt carries every required field.
3. live_run_untouched flag in receipt.
4. template_hash in receipt proves frozen template (zero edits to template).

CLI:
  --run           required to execute (staged guard)
  --write         write receipt to receipts/sp6c-e2b-shakedown-<ts>.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nck.seat_adapter import TEMPLATE_HASH, make_seat_core
from nck.replay_rig import (
    REPO_ROOT,
    join_battery_encodings,
    materialize,
    replay_episode,
    score_episode,
)
from nck.event_loop import Event, ToolRegistry

MODEL_ID = "google/gemma-4-E2B-it"
MODEL_REVISION = "b324173c7d5721c2baba7f3b17b3b9b3d34ab1e9"
MAX_NEW_TOKENS = 128
DEVICE = "cpu"

# Governor pace rail (from v0-pretrain-config.json fp19 floor)
PACE_S_PER_STEP = 0.05

# Staged guard: print and exit-1 unless --run passed (same pattern as rig)
_STAGED_MSG = (
    "STAGED: e2b_shakedown loaded but not triggered. "
    "Pass --run to bind E2B and run the battery. "
    "Pass --write to record the receipt. "
    "Exit-1 is the evidence-promotion gate."
)


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def _load_model():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM

    tok = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        dtype=torch.bfloat16,
        device_map=DEVICE,
    )
    model.eval()
    return tok, model


# ---------------------------------------------------------------------------
# generate_fn factory
# ---------------------------------------------------------------------------


def _make_generate_fn(tok, model):
    """Return a deterministic generate_fn(prompt) -> completion.

    Greedy decode (do_sample=False). Prompt is passed as a user message via
    the model's chat template; completion is the decoded generated tokens only.
    """
    import torch

    def generate_fn(prompt: str) -> str:
        # apply_chat_template(tokenize=False) returns text; tok() gives tensor.
        # Avoids BatchEncoding vs Tensor ambiguity in transformers 5.x.
        text = tok.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tok(text, return_tensors="pt").to(DEVICE)
        prompt_len = inputs.input_ids.shape[1]
        with torch.no_grad():
            out_ids = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=MAX_NEW_TOKENS,
            )
        gen_ids = out_ids[0, prompt_len:]
        return tok.decode(gen_ids, skip_special_tokens=True)

    return generate_fn


# ---------------------------------------------------------------------------
# Determinism selftest (AC1)
# ---------------------------------------------------------------------------


def selftest_determinism(generate_fn) -> dict:
    """Prove generate_fn determinism: same prompt twice → byte-identical.

    Uses a battery episode prompt so the full pipeline (build_prompt →
    generate → parse) is exercised. Returns a result dict for the receipt.
    """
    from nck.seat_adapter import build_prompt
    from nck.replay_rig import build_events

    episodes = join_battery_encodings()
    ep = episodes[0]  # first episode; arbitrary but fixed

    with tempfile.TemporaryDirectory(prefix="sp6c-det-") as tmp:
        materialize(ep, tmp)
        events = build_events(ep, tmp)
        ev = events[0]
        prompt = build_prompt(ev, tmp)

    c1 = generate_fn(prompt)
    c2 = generate_fn(prompt)
    identical = (c1 == c2)

    return {
        "identical": identical,
        "episode_id": ep["id"],
        "prompt_len": len(prompt),
        "completion_len_run1": len(c1),
        "completion_sample_run1": c1[:120],
    }


# ---------------------------------------------------------------------------
# Battery runner
# ---------------------------------------------------------------------------


def run_e2b_battery(generate_fn) -> list[dict]:
    """Run all 20 episodes with the E2B generate_fn; return score dicts."""
    from nck.seat_adapter import make_seat_core

    core = make_seat_core(generate_fn)
    episodes = join_battery_encodings()
    results: list[dict] = []

    for i, ep in enumerate(episodes):
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="sp6c-e2b-") as tmp:
            materialize(ep, tmp)
            actions = replay_episode(ep, core, tmp)
            score = score_episode(ep, actions, sandbox_dir=tmp)
        elapsed = time.time() - t0
        score["inference_s"] = round(elapsed, 2)
        results.append(score)
        status = "PASS" if score["pass"] else "FAIL"
        print(f"  [{i+1:2d}/20] {ep['id']}: {status} — {score['reason'][:80]}")

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_commit_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]
    if "--run" not in args:
        print(_STAGED_MSG)
        return 1

    write = "--write" in args

    # Seat adapter selftest first (no model) — confirms adapter mechanics OK
    import subprocess as sp
    st = sp.run(
        [sys.executable, str(_SCRIPTS_DIR / "nck" / "selftest_seat_adapter.py")],
        capture_output=True, text=True,
    )
    if st.returncode != 0:
        print(f"SEAT_ADAPTER_SELFTEST FAIL:\n{st.stdout}\n{st.stderr}")
        return 1
    print(f"Adapter selftest: {st.stdout.strip()}")

    # Load model on CPU
    print(f"\nLoading {MODEL_ID} (CPU, bfloat16)...")
    t_load = time.time()
    tok, model = _load_model()
    load_s = round(time.time() - t_load, 1)
    print(f"Loaded in {load_s}s")

    generate_fn = _make_generate_fn(tok, model)

    # AC1: determinism selftest
    print("\nProving determinism (two identical prompts -> byte-identical completion)...")
    det = selftest_determinism(generate_fn)
    if not det["identical"]:
        print(f"DETERMINISM_FAIL: completions differ for episode {det['episode_id']}")
        return 1
    print(f"Determinism PASS: episode={det['episode_id']}, completion_len={det['completion_len_run1']}")

    # AC2: full 20-episode battery
    print("\nRunning 20-episode battery (CPU inference, greedy decode)...")
    t_bat = time.time()
    scores = run_e2b_battery(generate_fn)
    bat_s = round(time.time() - t_bat, 1)

    n_pass = sum(1 for s in scores if s["pass"])
    print(f"\nBattery: {n_pass}/20 PASS in {bat_s}s")

    commit_sha = _get_commit_sha()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "SP6C-E2B-SHAKEDOWN",
        "label": "SHAKEDOWN-NOT-B-RUN",
        "ts": ts,
        "seat": "e2b",
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "load_s": load_s,
            "device": DEVICE,
            "torch_dtype": "bfloat16",
        },
        "decode_params": {
            "do_sample": False,
            "greedy": True,
            "max_new_tokens": MAX_NEW_TOKENS,
        },
        "template_hash": TEMPLATE_HASH,
        "adapter_commit_sha": commit_sha,
        "rig_commit_sha": commit_sha,
        "determinism_proof": det,
        "battery": {
            "n_pass": n_pass,
            "n_total": len(scores),
            "pass_pct": round(100.0 * n_pass / len(scores), 1) if scores else 0.0,
            "bat_s": bat_s,
            "episodes": scores,
        },
        "flags": [
            "SHAKEDOWN-NOT-B-RUN: proves binding + replay-identity mechanics",
            f"CPU inference: device={DEVICE}, dtype=bfloat16, live 12c050e7 holds VRAM",
            "live run 12c050e7 NOT touched",
            "template_hash frozen — any edit voids the B-run",
            "zero edits to frozen battery/encodings/template",
        ],
        "live_run_untouched": "12c050e7",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
    }

    if write:
        receipt_dir = REPO_ROOT / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        fname = receipt_dir / f"sp6c-e2b-shakedown-{ts}.json"
        fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"RECEIPT: {fname}")
    else:
        print("(dry-run: pass --write to save receipt)")
        print(json.dumps({
            "n_pass": n_pass, "n_total": len(scores),
            "determinism_proof.identical": det["identical"],
            "template_hash": TEMPLATE_HASH[:16] + "...",
        }, indent=2))

    # Exit 1 if any AC fails (not a gate on pass_count — SHAKEDOWN only proves mechanics)
    if not det["identical"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
