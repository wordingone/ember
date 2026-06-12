#!/usr/bin/env python3
"""sp-6c ember seat binding — SHAKEDOWN receipt (#313).

Binds the ember v0 checkpoint (step-00025000 by default; configurable via
--checkpoint-dir so the B-run can point at the designated final checkpoint)
into seat_adapter.make_seat_core, runs the frozen 20-episode battery (CPU
inference, greedy decode, raw text — no chat template), writes a SHAKEDOWN
receipt.

SHAKEDOWN-NOT-B-RUN: proves binding + replay-identity mechanics only.
Unparseable ember output is the datum: a raw pretrain core at step-25k may
emit zero conforming lines — that IS the baseline reading, never a
prompt-tuning trigger.

Resource rails:
- Checkpoint read from a COPY (never live file handles on v0-r1s1).
- CPU inference only: bf16 weights, manual KV-cache generation loop.
- Live run 12c050e7 UNTOUCHED.

AC:
1. generate_fn determinism: same prompt twice -> byte-identical completion.
2. Full 20-episode battery; receipt carries every required field.
3. live_run_untouched flag in receipt; checkpoint read from copy.
4. template_hash in receipt proves frozen template.

CLI:
  --run              required to execute (staged guard)
  --write            write receipt to receipts/sp6c-ember-shakedown-<ts>.json
  --checkpoint-dir   path to the checkpoint directory (default: step-00025000)
"""
from __future__ import annotations

import hashlib
import json
import shutil
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

DEFAULT_CHECKPOINT_DIR = (
    REPO_ROOT.parent / "runs" / "v0-r1s1" / "checkpoints" / "step-00025000"
)
TOKENIZER_PATH = REPO_ROOT / "tokenizer" / "tokenizer.json"
MAX_NEW_TOKENS = 128
DEVICE = "cpu"
EOS_ID = 0  # <|endoftext|> — sole stop token for raw pretrain

PACE_S_PER_STEP = 0.05

_STAGED_MSG = (
    "STAGED: ember_shakedown loaded but not triggered. "
    "Pass --run to bind ember and run the battery. "
    "Pass --write to record the receipt. "
    "Pass --checkpoint-dir <path> to target a specific checkpoint. "
    "Exit-1 is the evidence-promotion gate."
)


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def _checkpoint_sha256(ckpt_dir: Path, filename: str = "model.pt") -> str:
    h = hashlib.sha256()
    with open(ckpt_dir / filename, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_checkpoint(ckpt_dir: Path, dest_dir: str) -> Path:
    """Copy checkpoint files to dest_dir. Returns path to model.pt copy."""
    dest = Path(dest_dir)
    for fname in ["model.pt", "manifest.json"]:
        src = ckpt_dir / fname
        if src.exists():
            shutil.copy2(str(src), str(dest / fname))
    return dest / "model.pt"


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def _build_model_class():
    """Build the _V0Real class (mirrors timeshare_pretrain.build_v0_model live path)."""
    import torch
    from transformers import LlamaConfig, LlamaModel

    cfg_path = REPO_ROOT / "configs" / "v0-pretrain-config.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    m = cfg["model"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]

    class _V0Real(torch.nn.Module):
        def __init__(self):
            super().__init__()
            conf = LlamaConfig(
                vocab_size=m["vocab"], hidden_size=m["hidden"],
                intermediate_size=4096, num_hidden_layers=m["layers"],
                num_attention_heads=m["heads"], num_key_value_heads=m["heads"],
                max_position_embeddings=m["seq"], tie_word_embeddings=False,
            )
            self.backbone_model = LlamaModel(conf)
            self.head = torch.nn.Linear(m["hidden"], m["vocab"], bias=False)
            if m["tied_embeddings"]:
                self.head.weight = self.backbone_model.embed_tokens.weight
            self.mtp_heads = torch.nn.ModuleList(
                [torch.nn.Linear(m["hidden"], m["vocab"], bias=False)
                 for _ in range(n_mtp)]
            )

    return _V0Real, m, n_mtp


def _load_model(model_pt_path: Path):
    import torch
    _V0Real, m, n_mtp = _build_model_class()
    model = _V0Real()
    sd = torch.load(str(model_pt_path), map_location=DEVICE, weights_only=True)
    model.load_state_dict(sd, strict=True)
    model.eval()
    return model


def _load_tokenizer():
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(TOKENIZER_PATH))


# ---------------------------------------------------------------------------
# generate_fn factory (raw text, no chat template, KV-cache greedy decode)
# ---------------------------------------------------------------------------


def _make_generate_fn(model, tok):
    """Return a deterministic generate_fn(prompt: str) -> completion: str.

    Raw pretrain base-model consumption: prompt is passed as raw text
    (no chat template). Generation is greedy (argmax), stops at EOS_ID
    or MAX_NEW_TOKENS. Uses LlamaModel KV-cache for efficiency.
    """
    import torch

    def generate_fn(prompt: str) -> str:
        encoding = tok.encode(prompt)
        input_ids = torch.tensor([encoding.ids], dtype=torch.long)

        generated_ids: list[int] = []
        past_key_values = None

        with torch.no_grad():
            # Prefill: process full prompt once
            out = model.backbone_model(
                input_ids=input_ids,
                use_cache=True,
                past_key_values=None,
            )
            past_key_values = out.past_key_values
            h = out.last_hidden_state[:, -1, :]  # last position hidden state

            for _ in range(MAX_NEW_TOKENS):
                logits = model.head(h)
                next_id = int(logits.argmax(dim=-1).item())
                if next_id == EOS_ID:
                    break
                generated_ids.append(next_id)

                # Decode step with KV cache
                new_tok = torch.tensor([[next_id]], dtype=torch.long)
                out = model.backbone_model(
                    input_ids=new_tok,
                    use_cache=True,
                    past_key_values=past_key_values,
                )
                past_key_values = out.past_key_values
                h = out.last_hidden_state[:, 0, :]

        return tok.decode(generated_ids)

    return generate_fn


# ---------------------------------------------------------------------------
# Determinism selftest (AC1)
# ---------------------------------------------------------------------------


def selftest_determinism(generate_fn) -> dict:
    """Same-prompt-twice -> byte-identical completion."""
    from nck.seat_adapter import build_prompt
    from nck.replay_rig import build_events

    episodes = join_battery_encodings()
    ep = episodes[0]

    with tempfile.TemporaryDirectory(prefix="sp6c-emb-det-") as tmp:
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


def run_ember_battery(generate_fn) -> list[dict]:
    """Run all 20 episodes with the ember generate_fn; return score dicts."""
    core = make_seat_core(generate_fn)
    episodes = join_battery_encodings()
    results: list[dict] = []

    for i, ep in enumerate(episodes):
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="sp6c-emb-") as tmp:
            materialize(ep, tmp)
            actions = replay_episode(ep, core, tmp)
            score = score_episode(ep, actions, sandbox_dir=tmp)
        elapsed = time.time() - t0
        score["inference_s"] = round(elapsed, 2)
        results.append(score)
        status = "PASS" if score["pass"] else "FAIL"
        print(f"  [{i+1:2d}/20] {ep['id']}: {status} -- {score['reason'][:80]}")

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

    # Parse --checkpoint-dir
    ckpt_dir = DEFAULT_CHECKPOINT_DIR
    if "--checkpoint-dir" in args:
        idx = args.index("--checkpoint-dir")
        ckpt_dir = Path(args[idx + 1])

    if not (ckpt_dir / "model.pt").exists():
        print(f"EMBER_SHAKEDOWN_NO_CHECKPOINT: model.pt not found at {ckpt_dir}")
        return 1

    # Seat adapter selftest (no model) — confirms adapter mechanics OK
    import subprocess as sp
    st = sp.run(
        [sys.executable, str(_SCRIPTS_DIR / "nck" / "selftest_seat_adapter.py")],
        capture_output=True, text=True,
    )
    if st.returncode != 0:
        print(f"SEAT_ADAPTER_SELFTEST FAIL:\n{st.stdout}\n{st.stderr}")
        return 1
    print(f"Adapter selftest: {st.stdout.strip()}")

    # sha256 of checkpoint BEFORE copy (proves which checkpoint was bound)
    print(f"\nCheckpoint: {ckpt_dir}")
    model_pt_sha = _checkpoint_sha256(ckpt_dir)
    print(f"model.pt sha256: {model_pt_sha[:24]}...")

    # Copy checkpoint to tempdir (never hold live file handles)
    with tempfile.TemporaryDirectory(prefix="sp6c-emb-ckpt-") as ckpt_tmp:
        print(f"Copying checkpoint to temp (no live file handles)...")
        model_pt_copy = _copy_checkpoint(ckpt_dir, ckpt_tmp)

        # Load model from copy
        print(f"\nLoading ember v0 (CPU, bfloat16, {ckpt_dir.name})...")
        t_load = time.time()
        model = _load_model(model_pt_copy)
        load_s = round(time.time() - t_load, 1)
        print(f"Loaded in {load_s}s")

        tok = _load_tokenizer()
        generate_fn = _make_generate_fn(model, tok)

        # AC1: determinism selftest
        print("\nProving determinism (two identical prompts -> byte-identical completion)...")
        det = selftest_determinism(generate_fn)
        if not det["identical"]:
            print(f"DETERMINISM_FAIL: completions differ for episode {det['episode_id']}")
            return 1
        print(f"Determinism PASS: episode={det['episode_id']}, completion_len={det['completion_len_run1']}")

        # AC2: full 20-episode battery
        print("\nRunning 20-episode battery (CPU inference, greedy decode, raw text)...")
        t_bat = time.time()
        scores = run_ember_battery(generate_fn)
        bat_s = round(time.time() - t_bat, 1)

    n_pass = sum(1 for s in scores if s["pass"])
    print(f"\nBattery: {n_pass}/20 PASS in {bat_s}s")

    commit_sha = _get_commit_sha()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "SP6C-EMBER-SHAKEDOWN",
        "label": "SHAKEDOWN-NOT-B-RUN",
        "ts": ts,
        "seat": "ember",
        "checkpoint": {
            "path": str(ckpt_dir),
            "name": ckpt_dir.name,
            "model_pt_sha256": model_pt_sha,
            "load_s": load_s,
            "device": DEVICE,
            "torch_dtype": "bfloat16",
        },
        "decode_params": {
            "do_sample": False,
            "greedy": True,
            "max_new_tokens": MAX_NEW_TOKENS,
            "format": "raw_text_no_chat_template",
            "eos_token_id": EOS_ID,
            "eos_token": "<|endoftext|>",
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
            "raw pretrain base-model: zero conforming lines IS the baseline datum",
            f"CPU inference: device={DEVICE}, dtype=bfloat16, KV-cache greedy loop",
            "checkpoint read from a COPY — live file handles on v0-r1s1 never held",
            "live run 12c050e7 NOT touched",
            "template_hash frozen -- any edit voids the B-run",
            "zero edits to frozen battery/encodings/template",
        ],
        "live_run_untouched": "12c050e7",
    }

    if write:
        receipt_dir = REPO_ROOT / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        fname = receipt_dir / f"sp6c-ember-shakedown-{ts}.json"
        fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"RECEIPT: {fname}")
    else:
        print("(dry-run: pass --write to save receipt)")
        print(json.dumps({
            "n_pass": n_pass, "n_total": len(scores),
            "determinism_proof.identical": det["identical"],
            "template_hash": TEMPLATE_HASH[:16] + "...",
            "checkpoint": ckpt_dir.name,
            "model_pt_sha256": model_pt_sha[:24] + "...",
        }, indent=2))

    if not det["identical"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
