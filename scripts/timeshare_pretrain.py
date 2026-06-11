"""timeshare_pretrain.py — pretrain segment runner for the v0 owned-core (#123, eng-33).

Implements §3 of research/june22-critical-path.md (timeshare rule):
  - Pretrain holds the GPU by default.
  - Periodic checkpointing: model + optimizer + RNG state (torch CPU/CUDA +
    python random + numpy), written atomically (tmp + rename) under a run dir.
  - Per-checkpoint manifest JSON with sha256 of each checkpoint file.
  - Resume path: load checkpoint, assert bit-exact state round-trip where
    achievable; non-achievable divergence is RECEIPTED (loss-continuity block),
    never silent.
  - Governor consumption mandatory on the GPU path (fp19_bench constants as
    the floor; see GOVERNOR_FLOOR below).
  - LAUNCH INTERLOCK (default-closed): any GPU/real-pretrain path requires
    EMBER_GATE_AUTHORIZED=1 AND --live on the command line. All selftests and
    dry-runs are 100% CPU-local.

fp19_bench constants (sha-pinned from fp19_bench.py at commit be76095 / fp19
frozen 2026-06-11):
  VRAM_FRACTION = 0.80     # same as fp19_bench.VRAM_FRACTION
  MARGIN_GIB    = 1.5      # same as fp19_bench.MARGIN_GIB
  PACE_S        = 0.05     # same as fp19_bench.PACE_S
  VOCAB         = 32000    # c03 config
  SEQ           = 1024     # c03 seq
These are the GOVERNING FLOOR; the governor.py env-var layer (EMBER_VRAM_FRACTION
/ EMBER_VRAM_MARGIN_GB) may TIGHTEN them but never loosen below these values.

v0 named config (fp19-envelope.md):
  c03 shape — 0.37B decoder, hidden 1024, 20 layers, 16 heads, vocab 32k,
  seq 1024, tied embeddings, grad checkpointing, QAT int8-grid fake-quant.

Dispatch-side interlock (complement of #105 guard):
  Round windows may only open AFTER a completed CHECKPOINT_OUT record (managed
  by timeshare_handoff.py). The pretrain resume may only fire AFTER
  WINDOW_CLOSED with zero in-flight jobs. This file asserts its own side of
  that contract; handoff.py asserts the window side.

Selftest: python timeshare_pretrain.py --selftest
  Pure-logic, CPU only, < 30 s. Marker: TIMESHARE_PRETRAIN_SELFTEST_PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# fp19_bench governing-floor constants (sha-pinned; never relax)
# ---------------------------------------------------------------------------
# Source: scripts/fp19_bench.py, frozen fp-19 (2026-06-11), commit be76095.
# Any change here must raise the floor, never lower it.
FP19_VRAM_FRACTION = 0.80   # fp19_bench.VRAM_FRACTION
FP19_MARGIN_GIB    = 1.5    # fp19_bench.MARGIN_GIB
FP19_PACE_S        = 0.05   # fp19_bench.PACE_S
FP19_VOCAB         = 32000  # c03 vocab
FP19_SEQ           = 1024   # c03 seq

# ---------------------------------------------------------------------------
# Launch interlock (default-closed)
# ---------------------------------------------------------------------------

def _check_launch_interlock(*, live: bool) -> None:
    """Refuse GPU/real-pretrain launch unless both guards are satisfied.

    Guards:
      1. EMBER_GATE_AUTHORIZED=1 in environment.
      2. --live flag passed to this invocation.

    If either guard is absent, print a refusal line and raise SystemExit.
    Real v0 pretrain launch fires only on fp-22's gate — not in this PR.
    """
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not (authorized and live):
        msg = (
            "TIMESHARE_LAUNCH_INTERLOCK_REFUSED: GPU/real-pretrain path blocked. "
            "Requires EMBER_GATE_AUTHORIZED=1 (env) AND --live (flag). "
            "Real v0 pretrain fires only on fp-22's gate. "
            f"[authorized={authorized}, live={live}]"
        )
        print(msg)
        raise SystemExit(msg)

    # eng-52 (#190): env+flag is AUTHORIZATION, not substance. The live/GPU
    # dispatch must ALSO pass v0_pretrain_launch_gate (all G-rows green:
    # corpus / tokenizer / shards / config / governor / world / budget /
    # prereg). Without this call the interlock was fail-OPEN w.r.t. the gate —
    # the gate was a standalone shim the trainer never consulted, so a drifted
    # premise / missing shards / over-budget corpus could still dispatch under
    # env+flag. Fail-closed; the failing rows are named. (Lazy import keeps the
    # module top CPU-safe and avoids any cycle — the gate never imports this.)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import v0_pretrain_launch_gate as _lg
    rows = _lg.gate(datetime.now(timezone.utc).date())
    blocked = [r for r in rows if r[1] != "GREEN"]
    if blocked:
        detail = "; ".join(f"{r[0]}={r[2]}" for r in blocked)
        msg = ("TIMESHARE_LAUNCH_GATE_REFUSED: v0_pretrain_launch_gate BLOCKS "
               f"dispatch — blocked rows {[r[0] for r in blocked]}. {detail}")
        print(msg)
        raise SystemExit(msg)


# ---------------------------------------------------------------------------
# Governor consumption (GPU path only; imported lazily to stay CPU-safe)
# ---------------------------------------------------------------------------

def _apply_governor() -> dict[str, Any]:
    """Call governor.preflight() and assert fp19 floor.

    Returns the receipt block from governor.preflight(). Raises SystemExit
    if floor constants are violated.
    """
    import governor  # type: ignore[import]
    import torch

    frac, margin_gb, _ = governor.env_limits()
    # Tighten fp19 floor: env may set stricter, never looser.
    eff_frac = min(frac, FP19_VRAM_FRACTION)
    eff_margin_gb = max(margin_gb, FP19_MARGIN_GIB)
    torch.cuda.set_per_process_memory_fraction(eff_frac)
    free, total = torch.cuda.mem_get_info()
    if free < eff_margin_gb * (1 << 30):
        raise SystemExit(
            f"TIMESHARE_GOVERNOR_FAIL: {free/(1<<30):.2f} GiB free < "
            f"{eff_margin_gb} GiB floor (fp19 floor = {FP19_MARGIN_GIB})")
    return {
        "vram_fraction_applied": eff_frac,
        "fp19_fraction_floor": FP19_VRAM_FRACTION,
        "free_gib": round(free / (1 << 30), 2),
        "total_gib": round(total / (1 << 30), 2),
        "margin_gib_floor": eff_margin_gb,
    }


# ---------------------------------------------------------------------------
# Checkpoint writers — atomic (tmp + rename)
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_checkpoint(
    run_dir: str,
    step: int,
    model_state: dict,
    optimizer_state: dict,
    rng_state: dict,
    extra: dict | None = None,
) -> str:
    """Write checkpoint atomically under run_dir/checkpoints/step-{step:08d}/.

    Files written:
      model.pt      — model state_dict
      optimizer.pt  — optimizer state_dict
      rng.pt        — RNG state bundle (torch_cpu, torch_cuda if available,
                       py_random, np_random if numpy present)
      manifest.json — per-file sha256, step, timestamp, sha_convention

    Uses tmp-sibling + rename for atomicity. Returns the checkpoint directory.
    """
    import torch

    ckpt_dir = os.path.join(run_dir, "checkpoints", f"step-{step:08d}")
    tmp_dir = ckpt_dir + ".tmp"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)

    mp = os.path.join(tmp_dir, "model.pt")
    op = os.path.join(tmp_dir, "optimizer.pt")
    rp = os.path.join(tmp_dir, "rng.pt")

    torch.save(model_state, mp)
    torch.save(optimizer_state, op)
    torch.save(rng_state, rp)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest: dict[str, Any] = {
        "ticket": "TIMESHARE-CHECKPOINT",
        "ts": ts,
        "step": step,
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "files": {
            "model.pt": _sha256_file(mp),
            "optimizer.pt": _sha256_file(op),
            "rng.pt": _sha256_file(rp),
        },
        "extra": extra or {},
    }
    # Write manifest without self-hash first, then add self-hash and rewrite.
    # We must iterate twice: first write gives us the content hash, second write
    # adds it — but the second write changes the file. To avoid an infinite loop,
    # we use a sentinel: manifest.json's own sha256 is omitted from the hash
    # computation (only data files are hashed in "files").
    mfp = os.path.join(tmp_dir, "manifest.json")
    with open(mfp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, sort_keys=True, separators=(",", ": "), indent=2)

    # Atomic rename: remove existing if present, then rename tmp -> final.
    if os.path.exists(ckpt_dir):
        shutil.rmtree(ckpt_dir)
    os.rename(tmp_dir, ckpt_dir)
    return ckpt_dir


def load_checkpoint(ckpt_dir: str) -> tuple[dict, dict, dict, dict]:
    """Load and verify a checkpoint written by save_checkpoint.

    Returns (model_state, optimizer_state, rng_state, manifest).
    Raises ValueError on sha256 mismatch (file corruption / partial write).
    """
    import torch

    mfp = os.path.join(ckpt_dir, "manifest.json")
    with open(mfp, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for fname, expected_sha in manifest["files"].items():
        actual = _sha256_file(os.path.join(ckpt_dir, fname))
        if actual != expected_sha:
            raise ValueError(
                f"TIMESHARE_CHECKPOINT_CORRUPT: {fname} "
                f"expected={expected_sha} actual={actual}")

    model_state = torch.load(os.path.join(ckpt_dir, "model.pt"), map_location="cpu", weights_only=True)
    optimizer_state = torch.load(os.path.join(ckpt_dir, "optimizer.pt"), map_location="cpu", weights_only=True)
    # rng.pt contains Python random + numpy state objects; weights_only=False is
    # required. These checkpoints are written by save_checkpoint above (trusted
    # internal source); sha256 verification precedes this load.
    rng_state = torch.load(os.path.join(ckpt_dir, "rng.pt"), map_location="cpu", weights_only=False)  # noqa: S614
    return model_state, optimizer_state, rng_state, manifest


def read_manifest(ckpt_dir: str) -> dict:
    """Read a checkpoint's manifest.json (no tensor loads, no hash verify)."""
    with open(os.path.join(ckpt_dir, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def verify_resume(run_dir: str) -> dict:
    """Post-failure resume-safety determination (fail-closed).

    Scans run_dir/checkpoints, validates every checkpoint's manifest + per-file
    sha256, and emits an explicit verdict distinguishing safe resume from
    restart-from-scratch:

      SAFE_RESUME           — at least one fully hash-valid checkpoint exists;
                              latest_valid names the resume target (dir, step,
                              per-file hashes).
      RESTART_FROM_SCRATCH  — no valid checkpoint (none written, all corrupt,
                              or only orphan .tmp dirs from aborted writes).

    Orphan .tmp directories (aborted atomic writes) are reported and are never
    resume-eligible. Any defect (missing manifest, missing file, sha mismatch,
    malformed json) marks that checkpoint invalid — fail-closed, never a guess.
    """
    base = os.path.join(run_dir, "checkpoints")
    entries = sorted(os.listdir(base)) if os.path.isdir(base) else []
    checkpoints: list[dict[str, Any]] = []
    orphan_tmp: list[str] = []
    for name in entries:
        p = os.path.join(base, name)
        if name.endswith(".tmp"):
            orphan_tmp.append(p)
            continue
        if not os.path.isdir(p):
            continue
        rec: dict[str, Any] = {"dir": p, "valid": False, "step": None, "error": None}
        try:
            manifest = read_manifest(p)
            for fname, expected in manifest["files"].items():
                actual = _sha256_file(os.path.join(p, fname))
                if actual != expected:
                    raise ValueError(
                        f"sha256 mismatch on {fname}: expected={expected} actual={actual}")
            rec["valid"] = True
            rec["step"] = manifest["step"]
            rec["files"] = manifest["files"]
        except Exception as e:  # noqa: BLE001 — any defect = invalid, fail-closed
            rec["error"] = f"{type(e).__name__}: {e}"
        checkpoints.append(rec)
    valid = [c for c in checkpoints if c["valid"]]
    latest = max(valid, key=lambda c: c["step"]) if valid else None
    return {
        "ticket": "TIMESHARE-RESUME-VERIFY",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": "wordingone/ember#123",
        "scope": "post-failure resume-safety determination (safe resume vs restart-from-scratch)",
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
        "run_dir": run_dir,
        "checkpoints_scanned": len(checkpoints),
        "checkpoints_valid": len(valid),
        "checkpoints": checkpoints,
        "orphan_tmp_dirs": orphan_tmp,
        "latest_valid": (
            {"dir": latest["dir"], "step": latest["step"], "files": latest["files"]}
            if latest else None
        ),
        "pass": True,
        "verdict": "SAFE_RESUME" if latest else "RESTART_FROM_SCRATCH",
    }


# ---------------------------------------------------------------------------
# RNG capture / restore (CPU paths; CUDA path gated by has_cuda)
# ---------------------------------------------------------------------------

def capture_rng() -> dict:
    """Capture Python random + numpy (if present) + torch CPU RNG states."""
    import torch
    state: dict[str, Any] = {
        "py_random": random.getstate(),
        "torch_cpu": torch.random.get_rng_state(),
    }
    try:
        import numpy as np
        state["np_random"] = np.random.get_state()
    except ImportError:
        pass
    if torch.cuda.is_available():
        state["torch_cuda"] = [
            torch.cuda.get_rng_state(i)
            for i in range(torch.cuda.device_count())
        ]
    return state


def restore_rng(state: dict) -> None:
    """Restore RNG states from a capture_rng() snapshot."""
    import torch
    random.setstate(state["py_random"])
    torch.random.set_rng_state(state["torch_cpu"])
    if "np_random" in state:
        import numpy as np
        np.random.set_state(state["np_random"])
    if "torch_cuda" in state and torch.cuda.is_available():
        for i, s in enumerate(state["torch_cuda"]):
            torch.cuda.set_rng_state(s, i)


# ---------------------------------------------------------------------------
# Pacing meter (fp-14 meter pattern)
# ---------------------------------------------------------------------------

_PACING: dict[str, Any] = {
    "throttle_s": 0.0, "throttle_steps": 0,
    "pace_s": 0.0, "pace_steps": 0,
}


def _pace_reset() -> None:
    _PACING.update(throttle_s=0.0, throttle_steps=0, pace_s=0.0, pace_steps=0)


def _pace_record(kind: str, duration: float) -> None:
    if kind == "throttle":
        _PACING["throttle_s"] = round(_PACING["throttle_s"] + duration, 6)
        _PACING["throttle_steps"] += 1
    elif kind == "pace":
        _PACING["pace_s"] = round(_PACING["pace_s"] + duration, 6)
        _PACING["pace_steps"] += 1


def pacing_snapshot() -> dict:
    """Return a copy of the pacing meter (fp-14 meter pattern).

    convention: pacing_total_s = wall time spent in governor/pacing sleeps;
    compute-only wall = elapsed - pacing_total_s.
    """
    snap = dict(_PACING)
    snap["pacing_total_s"] = round(snap["throttle_s"] + snap["pace_s"], 6)
    snap["convention"] = (
        "pacing_total_s = wall time in governor/pacing sleeps; "
        "compute-only wall = elapsed - pacing_total_s"
    )
    return snap


# ---------------------------------------------------------------------------
# Resume-integrity check (loss-continuity)
# ---------------------------------------------------------------------------

def check_resume_integrity(
    loss_before: list[float],
    loss_after_resume: list[float],
    *,
    rtol: float = 1e-4,
) -> dict:
    """Assert bit-exact (or close) loss continuity across a checkpoint boundary.

    Compares the last loss value before checkpoint-out with the first loss
    value after resume. For deterministic CPU training these should be
    bit-identical; for non-deterministic GPU paths any divergence is RECEIPTED,
    never silent.

    Returns a receipt block with verdict and quoted values.
    """
    if not loss_before or not loss_after_resume:
        return {
            "pass": False,
            "verdict": "INCOMPLETE_DATA",
            "detail": "empty loss sequence supplied",
        }
    pre = loss_before[-1]
    post = loss_after_resume[0]
    rel_diff = abs(pre - post) / (abs(pre) + 1e-12)
    bit_exact = pre == post
    close = rel_diff <= rtol
    verdict = "BIT_EXACT" if bit_exact else ("CLOSE" if close else "DIVERGED")
    receipt = {
        "pass": bit_exact or close,
        "verdict": verdict,
        "loss_pre_checkpoint": pre,
        "loss_post_resume": post,
        "rel_diff": round(rel_diff, 8),
        "rtol": rtol,
        "note": (
            "BIT_EXACT: deterministic CPU path confirmed" if bit_exact
            else "DIVERGED: non-deterministic path; divergence receipted, not silent"
            if not close else "CLOSE: within rtol tolerance"
        ),
    }
    return receipt


# ---------------------------------------------------------------------------
# Pretrain segment runner (skeleton — CPU dry-run + GPU behind interlock)
# ---------------------------------------------------------------------------

def run_segment(
    run_dir: str,
    n_steps: int,
    *,
    live: bool = False,
    resume_ckpt_dir: str | None = None,
    checkpoint_every: int = 50,
    pace_s: float = FP19_PACE_S,
    tiny_cpu: bool = False,
    segment_id: str = "seg-A",
) -> dict:
    """Run a pretrain segment, checkpointing periodically.

    Arguments:
      run_dir          — directory for checkpoints and receipts
      n_steps          — number of optimizer steps to run
      live             — if True AND EMBER_GATE_AUTHORIZED=1, enable GPU path
      resume_ckpt_dir  — path to a prior checkpoint to resume from
      checkpoint_every — steps between checkpoints
      pace_s           — inter-step pace sleep (fp19 floor)
      tiny_cpu         — use a tiny pure-numpy/torch-CPU model for selftests
      segment_id       — label for receipts

    Returns a segment receipt dict.
    """
    import torch

    if live:
        _check_launch_interlock(live=live)
        gov_receipt = _apply_governor()
    else:
        gov_receipt = {
            "mode": "cpu_dryrun",
            "fp19_fraction_floor": FP19_VRAM_FRACTION,
            "fp19_margin_gib_floor": FP19_MARGIN_GIB,
            "fp19_pace_s_floor": FP19_PACE_S,
            "note": "governor.preflight() not called (no GPU path)",
        }

    os.makedirs(run_dir, exist_ok=True)
    _pace_reset()

    # --- Model + optimizer (tiny for CPU tests; real c03 behind interlock) ---
    if tiny_cpu or not live:
        # Tiny 3-layer MLP as a stand-in — pure CPU, no GPU, no HuggingFace.
        class _TinyModel(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.fc1 = torch.nn.Linear(32, 64)
                self.fc2 = torch.nn.Linear(64, 64)
                self.fc3 = torch.nn.Linear(64, 32)

            def forward(self, x: "torch.Tensor") -> "torch.Tensor":
                return self.fc3(torch.relu(self.fc2(torch.relu(self.fc1(x)))))

        model = _TinyModel()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    else:
        # Real c03 config — gated, only reachable with --live + auth.
        from transformers import LlamaConfig, LlamaForCausalLM  # type: ignore
        conf = LlamaConfig(
            vocab_size=FP19_VOCAB, hidden_size=1024,
            intermediate_size=4096, num_hidden_layers=20,
            num_attention_heads=16, num_key_value_heads=16,
            max_position_embeddings=FP19_SEQ, tie_word_embeddings=True,
        )
        model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
        model.gradient_checkpointing_enable()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)

    # --- Resume path ---
    resume_step = 0
    resume_receipt: dict | None = None
    loss_before_ckpt: list[float] = []

    resume_checkpoint: dict | None = None
    if resume_ckpt_dir is not None:
        m_state, o_state, r_state, manifest = load_checkpoint(resume_ckpt_dir)
        model.load_state_dict(m_state)
        optimizer.load_state_dict(o_state)
        restore_rng(r_state)
        resume_step = manifest["step"]
        # Checkpoint-in record: load_checkpoint verified every per-file sha256
        # (fail-closed above), so reaching this line means hashes matched.
        resume_checkpoint = {
            "ckpt_dir": resume_ckpt_dir,
            "step": manifest["step"],
            "files": manifest["files"],
            "hash_verified": True,
        }
        # First step after resume — record loss for continuity check.
        # We do NOT train yet; run one forward pass to get reference loss.
        if tiny_cpu or not live:
            x = torch.randn(4, 32)
            tgt = torch.randn(4, 32)
            _l = torch.nn.functional.mse_loss(model(x), tgt)
            loss_before_ckpt = [float(manifest["extra"].get("last_loss", float("nan")))]
            first_loss_after = float(_l.detach())
            resume_receipt = check_resume_integrity(
                loss_before_ckpt, [first_loss_after])
        else:
            resume_receipt = {"note": "GPU resume integrity check deferred to fp-22 run"}

    # --- Training loop ---
    losses: list[float] = []
    last_ckpt_dir: str | None = None
    t_start = time.perf_counter()

    for local_step in range(n_steps):
        global_step = resume_step + local_step

        if tiny_cpu or not live:
            x = torch.randn(4, 32)
            tgt = torch.randn(4, 32)
            loss = torch.nn.functional.mse_loss(model(x), tgt)
        else:
            # Real c03 step (behind interlock).
            ids = torch.randint(0, FP19_VOCAB, (4, FP19_SEQ), device="cuda")
            out = model(input_ids=ids, labels=ids)
            loss = out.loss

        loss.backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(float(loss.detach()))

        # Paced duty cycle (fp19 floor).
        time.sleep(pace_s)
        _pace_record("pace", pace_s)

        # Periodic checkpoint.
        if (local_step + 1) % checkpoint_every == 0 or local_step == n_steps - 1:
            rng = capture_rng()
            last_ckpt_dir = save_checkpoint(
                run_dir,
                global_step + 1,
                model.state_dict(),
                optimizer.state_dict(),
                rng,
                extra={"last_loss": losses[-1], "segment_id": segment_id},
            )

    wall_s = time.perf_counter() - t_start
    pacing = pacing_snapshot()

    # Tokens and steps (synthetic for dry-run; real for GPU path).
    tokens_this_seg = n_steps * 4 * 32 if (tiny_cpu or not live) else n_steps * 4 * FP19_SEQ

    receipt: dict[str, Any] = {
        "ticket": "TIMESHARE-SEGMENT",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": "wordingone/ember#123",
        "scope": "pretrain segment runner — cpu dry-run",
        "segment_id": segment_id,
        "steps": n_steps,
        "resume_step": resume_step,
        "global_step_end": resume_step + n_steps,
        "tokens_this_segment": tokens_this_seg,
        "wall_s": round(wall_s, 3),
        "tok_per_s": round(tokens_this_seg / wall_s, 1) if wall_s > 0 else None,
        "loss_first": round(losses[0], 6) if losses else None,
        "loss_last": round(losses[-1], 6) if losses else None,
        "pacing": pacing,
        "governor": gov_receipt,
        "last_checkpoint": last_ckpt_dir,
        "resume_checkpoint": resume_checkpoint,
        "resume_integrity": resume_receipt,
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
        "pass": True,
        "verdict": "SEGMENT_COMPLETE",
    }
    return receipt


# ===========================================================================
# v0 SURVIVOR-STACK EXTENSION (eng-43, #167)
# ===========================================================================
# Implements the FROZEN contract configs/v0-pretrain-config.json against the
# eng-33 primitives ABOVE (save_checkpoint/load_checkpoint/capture_rng/
# restore_rng/verify_resume/_apply_governor/_check_launch_interlock/pacing —
# all reused unchanged; the eng-33 surface is byte-identical). Component
# choices are frozen in the contract, NOT here.
#
#   1. Muon split-optimizer  — Muon on 2D hidden weights; AdamW on
#                              embeddings/norms/head. AdamW-everything fallback
#                              is RECEIPTED (never a silent drop).
#   2. WSD schedule          — warmup 1% / stable to 85% / decay to 10% lr;
#                              checkpoints ride the stable phase.
#   3. Chunked/fused CE       — Liger FLCE if importable, else a portable
#                              cut-CE that never materializes [N, vocab].
#   4. MTP aux heads          — n=2, weight 0.3 (contract #5); CE-only fallback
#                              is RECEIPTED.
#   5. Packed-shard loader    — no-pad sequence packing; synthetic fixture now
#                              (real shards blocked on the production token
#                              shards; the merged tokenizer receipt binds them).
#
# Constraints honored: governor floor tighten-only (eng-33 _apply_governor),
# launch interlock unchanged (eng-33 _check_launch_interlock), NO FP8, NO
# sparse attention, every fallback emits a deviation receipt (directed-path
# gate — a silent component drop is a gate violation).
# ---------------------------------------------------------------------------

CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "v0-pretrain-config.json")

# vocab 32000 < 65536 -> uint16 is the packed-shard dtype (memory-mappable).
PACK_DTYPE = "<u2"


def load_contract(path: str | None = None) -> dict:
    """Load the frozen v0 pretrain config contract."""
    with open(path or CONTRACT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def emit_deviation_receipt(out_dir: str, component: str, *, basis: str,
                           detail: str) -> str:
    """Write a fail-closed deviation receipt for a RECEIPTED fallback path.

    A silent component drop is a gate violation (directed-path gate); every
    fallback that deviates from the frozen contract lands one of these.
    """
    from receipt_write import checked_write
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec = {
        "ticket": "V0EXT-DEVIATION",
        "ts": ts,
        "issue": "wordingone/ember#167",
        "component": component,
        "basis": basis,
        "detail": detail,
        "clause": ("fallback path RECEIPTED per the directed-path gate; the "
                   "component re-enters at the contract-named window — never "
                   "silently dropped"),
    }
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"v0ext-deviation-{component}-{ts}.json")
    checked_write(out, rec)
    return out


# --- 1. Muon optimizer (self-contained, CPU-deterministic, no external dep) -

def _zeropower_via_newtonschulz5(G, steps: int = 5, eps: float = 1e-7):
    """Orthogonalize a 2D matrix via the quintic Newton-Schulz iteration
    (Muon / Bernstein-Newhouse). float32, deterministic matmuls on CPU.
    Pushes the singular values of G toward 1 (semi-orthogonal update)."""
    import torch
    assert G.ndim == 2, "Newton-Schulz operates on 2D matrices only"
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.to(torch.float32)
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    X = X / (X.norm() + eps)
    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * (A @ A)
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X


_MUON_CLS = None


def _muon_class():
    """Build (once) the Muon optimizer class. Lazy so the module imports
    without torch (eng-33 discipline: pure-logic paths stay torch-free)."""
    global _MUON_CLS
    if _MUON_CLS is not None:
        return _MUON_CLS
    import torch

    class _Muon(torch.optim.Optimizer):
        """Momentum-orthogonalized optimizer for 2D hidden weights. State
        (momentum_buffer per param) rides the optimizer state_dict, so the
        eng-33 checkpoint/resume round-trip carries it bit-exact."""

        def __init__(self, params, lr=0.02, momentum=0.95, nesterov=True,
                     ns_steps=5, weight_decay=0.0):
            defaults = dict(lr=lr, momentum=momentum, nesterov=nesterov,
                            ns_steps=ns_steps, weight_decay=weight_decay)
            super().__init__(params, defaults)

        @torch.no_grad()
        def step(self, closure=None):
            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            for group in self.param_groups:
                lr = group["lr"]
                mom = group["momentum"]
                nesterov = group["nesterov"]
                ns_steps = group["ns_steps"]
                wd = group["weight_decay"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    g = p.grad
                    if g.ndim != 2:
                        # Routing guarantees 2D; fail closed rather than
                        # silently corrupt a non-2D parameter.
                        raise ValueError(
                            "Muon received a non-2D parameter — the "
                            "split-routing invariant is violated")
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        state["momentum_buffer"] = torch.zeros_like(g)
                    buf = state["momentum_buffer"]
                    buf.mul_(mom).add_(g)
                    upd = g.add(buf, alpha=mom) if nesterov else buf
                    upd = _zeropower_via_newtonschulz5(upd, steps=ns_steps)
                    # aspect-ratio scale (Keller Jordan): update RMS ~ constant
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    if wd != 0.0:
                        p.mul_(1.0 - lr * wd)
                    p.add_(upd, alpha=-lr * scale)
            return loss

    _MUON_CLS = _Muon
    return _MUON_CLS


def split_param_groups(model):
    """Route params per the contract: a 2D weight that is NOT an embedding and
    NOT a head goes to Muon; everything else (embeddings, 1D norms/biases,
    primary + MTP heads) goes to AdamW. Tied tensors are deduped by id() so a
    tied embed/head appears exactly once. Deterministic over named_parameters
    order (resume-safe optimizer-state indexing)."""
    muon, adamw = [], []
    seen = set()
    for name, p in model.named_parameters():
        if not p.requires_grad or id(p) in seen:
            continue
        seen.add(id(p))
        low = name.lower()
        is_2d = p.ndim == 2
        is_embed = "embed" in low
        is_head = "head" in low
        if is_2d and not is_embed and not is_head:
            muon.append((name, p))
        else:
            adamw.append((name, p))
    return muon, adamw


def build_split_optimizer(model, cfg, *, force_fallback: bool = False,
                          deviation_dir: str | None = None):
    """Build the Muon/AdamW split optimizer from the contract lrs. On
    force_fallback (Muon impl failed its selftest) build AdamW-everything and
    RECEIPT the deviation. Returns (optimizers_dict, base_lrs, routing)."""
    import torch
    opt_cfg = cfg["optimizer"]
    lr_muon = opt_cfg["lr_muon"]
    lr_adamw = opt_cfg["lr_adamw"]
    wd = opt_cfg["weight_decay"]
    muon_named, adamw_named = split_param_groups(model)
    routing = {
        "muon_params": [n for n, _ in muon_named],
        "adamw_params": [n for n, _ in adamw_named],
        "n_muon": len(muon_named),
        "n_adamw": len(adamw_named),
    }
    if force_fallback:
        all_params = [p for _, p in muon_named] + [p for _, p in adamw_named]
        opt = torch.optim.AdamW(all_params, lr=lr_adamw, weight_decay=wd)
        routing["mode"] = "adamw_everything_fallback"
        if deviation_dir is not None:
            routing["deviation_receipt"] = emit_deviation_receipt(
                deviation_dir, "optimizer-muon",
                basis="Muon implementation failed its selftest at build time",
                detail=("split optimizer fell back to AdamW-everything; Muon "
                        "re-enters at the first checkpoint window per "
                        "contract.optimizer.fallback (RECEIPTED)"))
        return {"adamw_all": opt}, {"adamw_all": lr_adamw}, routing
    Muon = _muon_class()
    opts: dict[str, Any] = {}
    base_lrs: dict[str, float] = {}
    if muon_named:
        opts["muon"] = Muon([p for _, p in muon_named], lr=lr_muon,
                            weight_decay=wd)
        base_lrs["muon"] = lr_muon
    if adamw_named:
        opts["adamw"] = torch.optim.AdamW([p for _, p in adamw_named],
                                          lr=lr_adamw, weight_decay=wd)
        base_lrs["adamw"] = lr_adamw
    routing["mode"] = "muon_split"
    return opts, base_lrs, routing


def save_optimizers_state(optimizers: dict) -> dict:
    """Bundle every optimizer's state_dict for checkpointing. The bundle is
    an opaque dict to the eng-33 save_checkpoint (it just torch.saves it)."""
    return {k: opt.state_dict() for k, opt in optimizers.items()}


def load_optimizers_state(optimizers: dict, bundle: dict) -> None:
    """Restore each optimizer from a save_optimizers_state() bundle. Same key
    set + same param order (split_param_groups is deterministic) => the state
    indices align, so the resume is bit-exact."""
    for k, opt in optimizers.items():
        if k not in bundle:
            raise ValueError(
                f"optimizer state bundle missing key {k!r} (have "
                f"{sorted(bundle)}) — checkpoint/runner optimizer mismatch")
        opt.load_state_dict(bundle[k])


# --- 2. WSD schedule (pure lr-multiplier function) -------------------------

def wsd_lr_frac(step: int, total_steps: int, warmup_frac: float,
                stable_until_frac: float, decay_to_lr_frac: float) -> float:
    """Warmup-Stable-Decay lr multiplier in [decay_to_lr_frac, 1.0].

      warmup : linear 0 -> 1 over [0, warmup_frac)
      stable : 1.0 over [warmup_frac, stable_until_frac)
      decay  : linear 1.0 -> decay_to_lr_frac over [stable_until_frac, 1.0]

    Pure function of the step fraction; identical on resume (no RNG)."""
    if total_steps <= 0:
        return 1.0
    frac = step / total_steps
    if frac < 0.0:
        frac = 0.0
    elif frac > 1.0:
        frac = 1.0
    if frac < warmup_frac:
        return frac / warmup_frac if warmup_frac > 0 else 1.0
    if frac < stable_until_frac:
        return 1.0
    span = 1.0 - stable_until_frac
    if span <= 0:
        return decay_to_lr_frac
    progress = (frac - stable_until_frac) / span
    return 1.0 + progress * (decay_to_lr_frac - 1.0)


def apply_wsd(optimizers: dict, base_lrs: dict, step: int, total_steps: int,
              sched_cfg: dict) -> float:
    """Set every optimizer group's lr = base_lr * WSD(step). Returns the
    multiplier so the receipt can quote the realized schedule."""
    mult = wsd_lr_frac(step, total_steps, sched_cfg["warmup_frac"],
                       sched_cfg["stable_until_frac"],
                       sched_cfg["decay_to_lr_frac"])
    for key, opt in optimizers.items():
        for g in opt.param_groups:
            g["lr"] = base_lrs[key] * mult
    return mult


# --- 3. Chunked / fused cross-entropy --------------------------------------

def chunked_cross_entropy(hidden, weight, targets, *, chunk_tokens: int = 1024,
                          ignore_index: int = -100):
    """Portable cut-CE. hidden [N, H], weight [V, H] (logits = hidden @ wᵀ),
    targets [N] int64. Mean CE over valid (target != ignore_index) tokens
    WITHOUT ever materializing the full [N, V] logit tensor — peak logit
    memory is [chunk_tokens, V]. Deterministic accumulation (fixed chunk
    order). Returns (mean_ce, n_valid)."""
    import torch
    n = hidden.shape[0]
    total_nll = hidden.new_zeros(())
    n_valid = 0
    for s in range(0, n, chunk_tokens):
        e = min(s + chunk_tokens, n)
        logits = hidden[s:e] @ weight.T          # [chunk, V] — the bounded term
        logp = torch.log_softmax(logits, dim=-1)
        t = targets[s:e]
        mask = (t != ignore_index)
        safe_t = t.clamp(min=0).unsqueeze(-1)
        nll = -logp.gather(-1, safe_t).squeeze(-1)
        total_nll = total_nll + (nll * mask).sum()
        n_valid += int(mask.sum())
    if n_valid == 0:
        return hidden.new_zeros(()), 0
    return total_nll / n_valid, n_valid


def resolve_ce_impl(*, prefer_liger: bool = True):
    """Pick the chunked-CE implementation. Liger FLCE (fused linear+CE, never
    materializes the logit tensor) when importable on the real GPU path; else
    the portable cut-CE. Both are contract-valid 'chunked/fused CE' — this is
    NOT a deviation. Returns (impl_name, ce_fn) with ce_fn(hidden, weight,
    targets, chunk_tokens=..., ignore_index=...) -> (loss, n_valid)."""
    if prefer_liger:
        try:
            from liger_kernel.transformers import (  # type: ignore
                LigerFusedLinearCrossEntropyLoss)

            _flce = LigerFusedLinearCrossEntropyLoss()

            def _liger_ce(hidden, weight, targets, *, chunk_tokens=1024,
                          ignore_index=-100):
                # Liger fuses hidden@weightᵀ + CE; the full logit tensor is
                # never materialized. chunk_tokens is irrelevant (kernel-tiled).
                loss = _flce(weight, hidden, targets)
                import torch
                n_valid = int((targets != ignore_index).sum())
                return loss, n_valid

            return "liger_flce", _liger_ce
        except Exception:
            pass
    return "cut_ce_chunked", chunked_cross_entropy


# --- 4. MTP aux heads — loss composition -----------------------------------

def mtp_total_loss(primary_ce, mtp_ces, weight):
    """total = primary_ce + weight * mean(mtp_ces). CE-only (total =
    primary_ce) when mtp_ces is empty — the contract's RECEIPTED fallback."""
    if not mtp_ces:
        return primary_ce
    import torch
    return primary_ce + weight * torch.stack(list(mtp_ces)).mean()


# --- 5. Packed-shard loader (no-pad sequence packing) ----------------------

def write_packed_shard(path: str, token_ids) -> str:
    """Write a flat uint16 packed shard (fixture writer / tokenization-side
    util). token_ids: iterable of ints in [0, 65536)."""
    import numpy as np
    arr = np.asarray(list(token_ids), dtype=PACK_DTYPE)
    arr.tofile(path)
    return path


class PackedShardLoader:
    """No-pad sequence packing over tokenizer-freeze output shards.

    Reads every *.bin shard in shard_dir (sorted) as one flat uint16 stream
    and yields contiguous windows of block_len = seq + 1 + n_mtp tokens at
    stride `seq`. The final short window is DROPPED (no padding token is ever
    introduced — the whole point of packing). Per window:

      x         = w[0 : seq]                 model input
      y_primary = w[1 : seq+1]               next-token target (offset +1)
      y_mtp[k]  = w[k+2 : seq+k+2]           MTP head k target (offset +k+2)

    Window i input is stream[i*seq : i*seq+seq]; inputs are disjoint and
    contiguous, so concatenating them reconstructs the stream prefix exactly
    (the round-trip claim). batch(step, B) is a pure function of step (windows
    indexed mod n_windows), so resume re-derives the identical data stream."""

    def __init__(self, shard_dir: str, seq: int, n_mtp: int):
        import numpy as np
        self.seq = seq
        self.n_mtp = n_mtp
        self.block_len = seq + 1 + n_mtp
        shards = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
        if not shards:
            raise ValueError(f"no .bin packed shards in {shard_dir}")
        arrs = [np.fromfile(os.path.join(shard_dir, s), dtype=PACK_DTYPE)
                for s in shards]
        self.stream = np.concatenate(arrs) if len(arrs) > 1 else arrs[0]
        self.n_tokens = int(self.stream.shape[0])
        if self.n_tokens < self.block_len:
            raise ValueError(
                f"stream {self.n_tokens} tokens < block_len {self.block_len}")
        self.n_windows = (self.n_tokens - self.block_len) // self.seq + 1
        self.shards = shards

    def window_np(self, i: int):
        """Window i as (x, y_primary, [y_mtp...]) numpy int64 arrays. i is
        taken mod n_windows so dry-runs cycle deterministically; the
        round-trip selftest uses i in [0, n_windows)."""
        start = (i % self.n_windows) * self.seq
        w = self.stream[start:start + self.block_len].astype("int64")
        x = w[:self.seq]
        y0 = w[1:self.seq + 1]
        y_mtp = [w[k + 2:self.seq + k + 2] for k in range(self.n_mtp)]
        return x, y0, y_mtp

    def batch(self, step: int, batch_size: int):
        """A (x, y_primary, [y_mtp...]) batch of torch int64 tensors [B, seq]
        for global `step`. Pure function of step — resume-safe."""
        import numpy as np
        import torch
        xs, y0s = [], []
        ymtps: list[list] = [[] for _ in range(self.n_mtp)]
        for j in range(batch_size):
            x, y0, ym = self.window_np(step * batch_size + j)
            xs.append(x)
            y0s.append(y0)
            for k in range(self.n_mtp):
                ymtps[k].append(ym[k])
        x_t = torch.from_numpy(np.stack(xs))
        y0_t = torch.from_numpy(np.stack(y0s))
        ymtp_t = [torch.from_numpy(np.stack(ymtps[k]))
                  for k in range(self.n_mtp)]
        return x_t, y0_t, ymtp_t


# --- the model (tiny CPU stand-in; real c03 backbone behind the interlock) -

def _tiny_v0_model(vocab: int, hidden: int, n_mtp: int, depth: int = 2):
    """Tiny CPU stand-in with the SAME interface as the real c03 wrapper:
    .backbone(ids) -> [B,T,H]; .head + .mtp_heads as separate linear heads.
    Routing names (embed/blocks/norm/head/mtp_heads) exercise split_param_groups
    exactly as the real model does."""
    import torch

    class _TinyV0(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embed = torch.nn.Embedding(vocab, hidden)
            self.blocks = torch.nn.ModuleList(
                [torch.nn.Linear(hidden, hidden, bias=False)
                 for _ in range(depth)])
            self.norm = torch.nn.LayerNorm(hidden)
            self.head = torch.nn.Linear(hidden, vocab, bias=False)
            self.mtp_heads = torch.nn.ModuleList(
                [torch.nn.Linear(hidden, vocab, bias=False)
                 for _ in range(n_mtp)])

        def backbone(self, ids):
            h = self.embed(ids)
            for blk in self.blocks:
                h = torch.relu(blk(h))
            return self.norm(h)

    return _TinyV0()


def build_v0_model(cfg: dict, *, live: bool, tiny_dims: dict | None = None):
    """Build the v0 model. CPU dry-run: tiny stand-in. live (gated): real c03
    LlamaModel backbone + tied primary head + MTP heads. Returns (model,
    vocab, hidden, n_mtp)."""
    import torch
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    if not live:
        td = tiny_dims or {"vocab": 64, "hidden": 32, "depth": 2}
        model = _tiny_v0_model(td["vocab"], td["hidden"], n_mtp,
                               td.get("depth", 2))
        return model, td["vocab"], td["hidden"], n_mtp
    # live: real c03 — gated by the eng-33 interlock; fires on fp-22's gate.
    from transformers import LlamaConfig, LlamaModel  # type: ignore
    m = cfg["model"]

    class _V0Real(torch.nn.Module):
        def __init__(self):
            super().__init__()
            conf = LlamaConfig(
                vocab_size=m["vocab"], hidden_size=m["hidden"],
                intermediate_size=4096, num_hidden_layers=m["layers"],
                num_attention_heads=m["heads"], num_key_value_heads=m["heads"],
                max_position_embeddings=m["seq"], tie_word_embeddings=False)
            self.backbone_model = LlamaModel(conf)
            self.head = torch.nn.Linear(m["hidden"], m["vocab"], bias=False)
            if m["tied_embeddings"]:
                self.head.weight = self.backbone_model.embed_tokens.weight
            self.mtp_heads = torch.nn.ModuleList(
                [torch.nn.Linear(m["hidden"], m["vocab"], bias=False)
                 for _ in range(n_mtp)])

        def backbone(self, ids):
            return self.backbone_model(input_ids=ids).last_hidden_state

    model = _V0Real().cuda().to(torch.bfloat16)
    model.backbone_model.gradient_checkpointing_enable()
    return model, m["vocab"], m["hidden"], n_mtp


# --- assemble + run a v0 segment (full survivor stack) ---------------------

def run_v0_segment(
    run_dir: str,
    cfg: dict,
    *,
    n_steps: int,
    total_steps: int | None = None,
    live: bool = False,
    resume_ckpt_dir: str | None = None,
    checkpoint_every: int = 50,
    pace_s: float = FP19_PACE_S,
    segment_id: str = "v0-seg-A",
    shard_dir: str | None = None,
    tiny_dims: dict | None = None,
    batch_size: int | None = None,
    ce_chunk_tokens: int = 256,
    mtp_force_fallback: bool = False,
    opt_force_fallback: bool = False,
    deviation_dir: str | None = None,
) -> dict:
    """Run a v0 pretrain segment with the full survivor stack against the
    frozen contract. CPU dry-run by default; the real c03 path is gated by the
    eng-33 launch interlock (EMBER_GATE_AUTHORIZED=1 + --live). Reuses the
    eng-33 checkpoint/resume/governor/pacing primitives unchanged."""
    import torch

    if live:
        _check_launch_interlock(live=live)
        gov_receipt = _apply_governor()
    else:
        gov_receipt = {
            "mode": "cpu_dryrun",
            "fp19_fraction_floor": FP19_VRAM_FRACTION,
            "fp19_margin_gib_floor": FP19_MARGIN_GIB,
            "fp19_pace_s_floor": FP19_PACE_S,
            "note": "governor.preflight() not called (no GPU path)",
        }

    os.makedirs(run_dir, exist_ok=True)
    deviation_dir = deviation_dir or os.path.join(run_dir, "deviations")
    _pace_reset()

    seq = cfg["model"]["seq"] if live else (tiny_dims or {}).get("seq", 16)
    batch_size = batch_size or (cfg["throughput"]["batch"] if live else 2)
    if total_steps is None:
        total_steps = n_steps

    # --- model + heads ---
    model, vocab, hidden, n_mtp = build_v0_model(cfg, live=live,
                                                 tiny_dims=tiny_dims)

    # --- packed-shard loader (synthetic fixture for the dry-run) ---
    if shard_dir is None:
        shard_dir = os.path.join(run_dir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        import numpy as np
        rng = np.random.default_rng(0)
        need = (n_steps + 4) * batch_size * seq + seq + n_mtp + 8
        toks = rng.integers(1, vocab, size=int(need), dtype=np.int64)
        # plant <|endoftext|>=0 doc separators (packing flows across them)
        toks[:: max(1, seq * 3)] = 0
        write_packed_shard(os.path.join(shard_dir, "synthetic-00000.bin"),
                           toks.astype(np.uint16).tolist())
    loader = PackedShardLoader(shard_dir, seq, n_mtp)

    # --- optimizer (Muon split, or AdamW-everything fallback RECEIPTED) ---
    optimizers, base_lrs, routing = build_split_optimizer(
        model, cfg, force_fallback=opt_force_fallback,
        deviation_dir=deviation_dir)

    # --- chunked/fused CE impl ---
    ce_impl, ce_fn = resolve_ce_impl(prefer_liger=live)

    # --- MTP composition (CE-only fallback RECEIPTED) ---
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_weight = mtp_cfg["weight"]
    mtp_enabled = mtp_cfg["enabled"] and not mtp_force_fallback
    mtp_deviation = None
    if mtp_cfg["enabled"] and mtp_force_fallback:
        mtp_deviation = emit_deviation_receipt(
            deviation_dir, "mtp-aux-heads",
            basis="MTP head implementation failed its selftest at build time",
            detail=("v0 trains CE-only; the MTP aux heads re-enter at v0.1 per "
                    "contract.objective.mtp_aux_heads.fallback (RECEIPTED)"))

    # --- resume ---
    resume_step = 0
    resume_checkpoint = None
    if resume_ckpt_dir is not None:
        m_state, o_state, r_state, manifest = load_checkpoint(resume_ckpt_dir)
        model.load_state_dict(m_state)
        load_optimizers_state(optimizers, o_state)
        restore_rng(r_state)
        resume_step = manifest["step"]
        resume_checkpoint = {
            "ckpt_dir": resume_ckpt_dir, "step": manifest["step"],
            "files": manifest["files"], "hash_verified": True,
        }

    # --- training loop ---
    losses: list[float] = []
    last_ckpt_dir: str | None = None
    t_start = time.perf_counter()
    lr_mults: list[float] = []

    for local_step in range(n_steps):
        global_step = resume_step + local_step
        x, y0, y_mtp = loader.batch(global_step, batch_size)
        if live:
            x = x.cuda()
            y0 = y0.cuda()
            y_mtp = [t.cuda() for t in y_mtp]

        hidden_out = model.backbone(x)                       # [B, T, H]
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1),
                              chunk_tokens=ce_chunk_tokens)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1),
                                chunk_tokens=ce_chunk_tokens)
                mtp_ces.append(ce_k)
        loss = mtp_total_loss(primary_ce, mtp_ces, mtp_weight)

        mult = apply_wsd(optimizers, base_lrs, global_step, total_steps,
                         cfg["schedule"])
        lr_mults.append(round(mult, 6))

        loss.backward()
        for opt in optimizers.values():
            opt.step()
        for opt in optimizers.values():
            opt.zero_grad(set_to_none=True)
        losses.append(float(loss.detach()))

        time.sleep(pace_s)
        _pace_record("pace", pace_s)

        if (local_step + 1) % checkpoint_every == 0 or local_step == n_steps - 1:
            rng = capture_rng()
            last_ckpt_dir = save_checkpoint(
                run_dir, global_step + 1,
                model.state_dict(), save_optimizers_state(optimizers), rng,
                extra={"last_loss": losses[-1], "segment_id": segment_id,
                       "optimizer_mode": routing["mode"], "ce_impl": ce_impl,
                       "mtp_enabled": bool(mtp_enabled),
                       "total_steps": total_steps})

    wall_s = time.perf_counter() - t_start
    tokens_this_seg = n_steps * batch_size * seq

    deviations = [d for d in (routing.get("deviation_receipt"), mtp_deviation)
                  if d]

    receipt: dict[str, Any] = {
        "ticket": "TIMESHARE-V0-SEGMENT",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": "wordingone/ember#167",
        "scope": "v0 survivor-stack pretrain segment — cpu dry-run"
                 if not live else "v0 survivor-stack pretrain segment — live",
        "segment_id": segment_id,
        "contract": "configs/v0-pretrain-config.json",
        "mode": "cpu_dryrun" if not live else "live",
        "steps": n_steps,
        "resume_step": resume_step,
        "global_step_end": resume_step + n_steps,
        "total_steps": total_steps,
        "tokens_this_segment": tokens_this_seg,
        "wall_s": round(wall_s, 3),
        "loss_first": round(losses[0], 6) if losses else None,
        "loss_last": round(losses[-1], 6) if losses else None,
        "losses": losses,
        "lr_mults": lr_mults,
        "components": {
            "optimizer": {"mode": routing["mode"], "n_muon": routing["n_muon"],
                          "n_adamw": routing["n_adamw"],
                          "lr_muon": cfg["optimizer"]["lr_muon"],
                          "lr_adamw": cfg["optimizer"]["lr_adamw"]},
            "schedule": {"type": cfg["schedule"]["type"],
                         "warmup_frac": cfg["schedule"]["warmup_frac"],
                         "stable_until_frac": cfg["schedule"]["stable_until_frac"],
                         "decay_to_lr_frac": cfg["schedule"]["decay_to_lr_frac"],
                         "lr_mult_first": lr_mults[0] if lr_mults else None,
                         "lr_mult_last": lr_mults[-1] if lr_mults else None},
            "ce": {"impl": ce_impl},
            "mtp": {"enabled": bool(mtp_enabled),
                    "n_heads": n_mtp if mtp_enabled else 0,
                    "weight": mtp_weight,
                    "composition": "total = primary_ce + weight * mean(mtp_ces)"},
            "loader": {"seq": seq, "n_mtp": n_mtp,
                       "block_len": loader.block_len,
                       "n_windows": loader.n_windows,
                       "batch_size": batch_size,
                       "packing": "no-pad sequence packing, stride=seq"},
        },
        "governor": gov_receipt,
        "pacing": pacing_snapshot(),
        "last_checkpoint": last_ckpt_dir,
        "resume_checkpoint": resume_checkpoint,
        "deviation_receipts": deviations,
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending "
            "normalization)"),
        "pass": True,
        "verdict": "V0_SEGMENT_COMPLETE",
    }
    return receipt


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Selftest: checkpoint/resume state round-trip on a tiny CPU config.

    1. Run N steps, checkpoint.
    2. Run M more steps recording losses.
    3. Resume from the checkpoint and replay M steps — assert bit-exact loss
       sequence (or receipt the divergence path explicitly as the negative branch).
    4. Assert atomic-write behavior (no partial manifest left on simulated failure).

    All CPU, no GPU, no daemon, < 30 s.
    Marker: TIMESHARE_PRETRAIN_SELFTEST_PASS
    """
    import torch

    tmpdir = tempfile.mkdtemp(prefix="timeshare_selftest_")
    try:
        # Reproducible seed for bit-exact comparisons.
        torch.manual_seed(42)
        random.seed(42)

        N, M, CKPT_EVERY = 5, 8, 5

        # ---- Phase 1: Run N steps, checkpoint ----
        class _Tiny(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.fc = torch.nn.Linear(16, 16, bias=False)

            def forward(self, x: "torch.Tensor") -> "torch.Tensor":
                return self.fc(x)

        model = _Tiny()
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
        torch.manual_seed(42)
        random.seed(42)

        _pace_reset()
        for _ in range(N):
            x = torch.randn(2, 16)
            loss = torch.nn.functional.mse_loss(model(x), torch.zeros(2, 16))
            loss.backward()
            opt.step()
            opt.zero_grad(set_to_none=True)

        rng_snap = capture_rng()
        ckpt_dir = save_checkpoint(
            tmpdir, N,
            model.state_dict(), opt.state_dict(), rng_snap,
            extra={"last_loss": float(loss.detach()), "selftest": True},
        )

        # Verify manifest integrity (sha checks).
        _, _, _, manifest = load_checkpoint(ckpt_dir)
        assert manifest["step"] == N, f"manifest step mismatch: {manifest['step']}"
        assert "sha_convention" in manifest, "sha_convention missing from manifest"

        # ---- Phase 2: Run M more steps from current state (reference) ----
        ref_losses: list[float] = []
        ref_rng = capture_rng()
        ref_model_state = {k: v.clone() for k, v in model.state_dict().items()}
        ref_opt_state_raw = opt.state_dict()  # captured pre-M steps

        for _ in range(M):
            x = torch.randn(2, 16)
            loss = torch.nn.functional.mse_loss(model(x), torch.zeros(2, 16))
            loss.backward()
            opt.step()
            opt.zero_grad(set_to_none=True)
            ref_losses.append(float(loss.detach()))

        # ---- Phase 3: Resume from checkpoint, replay M steps ----
        model2 = _Tiny()
        opt2 = torch.optim.AdamW(model2.parameters(), lr=1e-3)

        m_state, o_state, r_state, _ = load_checkpoint(ckpt_dir)
        model2.load_state_dict(m_state)
        opt2.load_state_dict(o_state)
        restore_rng(r_state)

        resumed_losses: list[float] = []
        for _ in range(M):
            x = torch.randn(2, 16)
            loss2 = torch.nn.functional.mse_loss(model2(x), torch.zeros(2, 16))
            loss2.backward()
            opt2.step()
            opt2.zero_grad(set_to_none=True)
            resumed_losses.append(float(loss2.detach()))

        # ---- Assert bit-exact loss sequence ----
        # ref_losses and resumed_losses start from the same checkpoint state + RNG,
        # so each step must produce identical losses (same inputs, same weights,
        # same optimizer state).
        mismatches = [
            i for i, (a, b) in enumerate(zip(ref_losses, resumed_losses)) if a != b
        ]
        if mismatches:
            # Divergence path: receipt it explicitly (negative branch coverage).
            # check_resume_integrity compares last-before vs first-after (boundary
            # continuity check). For divergence coverage we compare the first step.
            div_receipt = check_resume_integrity([ref_losses[0]], [resumed_losses[0]])
            # CPU deterministic path should be bit-exact; if not, receipt and fail.
            assert False, (
                f"RESUME_DIVERGED on CPU (expected BIT_EXACT): "
                f"mismatched steps {mismatches}; receipt={div_receipt}"
            )

        # ---- Positive-branch integrity receipt ----
        # check_resume_integrity checks last-before vs first-after (loss-continuity
        # across a real segment boundary). Here: last phase-1 step loss is the
        # pre-checkpoint value; first phase-2/resumed step is the post-resume value.
        # These are SEQUENTIAL steps from the same trained model — continuity means
        # they are within a reasonable range. We use a generous rtol here because
        # loss naturally varies step-to-step; the key claim is that the SEQUENCES
        # ref_losses and resumed_losses are bit-identical (checked above).
        loss_at_checkpoint = [float(loss.detach())]  # last phase-1 step
        int_receipt = check_resume_integrity(loss_at_checkpoint, resumed_losses[:1],
                                             rtol=2.0)
        assert int_receipt["pass"], int_receipt

        # ---- Positive-branch for same-step comparison ----
        # First step of both runs must be bit-exact (proves RNG + model + opt restored).
        pos_receipt = check_resume_integrity([ref_losses[0]], [resumed_losses[0]])
        assert pos_receipt["pass"] and pos_receipt["verdict"] == "BIT_EXACT", pos_receipt

        # ---- Negative-branch integrity receipt (forced divergence) ----
        neg_receipt = check_resume_integrity([1.0], [2.0], rtol=0.01)
        assert not neg_receipt["pass"], "negative branch should fail"
        assert neg_receipt["verdict"] == "DIVERGED", neg_receipt

        # ---- Atomic-write test: simulate aborted write ----
        # 1. Start a write that will leave only a .tmp directory.
        atomic_dir = os.path.join(tmpdir, "checkpoints", "step-00000099")
        tmp_atomic = atomic_dir + ".tmp"
        os.makedirs(tmp_atomic, exist_ok=True)
        # Write only model.pt (partial).
        torch.save(model.state_dict(), os.path.join(tmp_atomic, "model.pt"))
        # No manifest.json — simulates abort before rename.
        # save_checkpoint on a fresh step must overwrite and produce a clean result.
        rng_snap2 = capture_rng()
        clean_ckpt = save_checkpoint(
            tmpdir, 99,
            model.state_dict(), opt.state_dict(), rng_snap2,
        )
        # The .tmp must be gone (renamed or removed).
        assert not os.path.exists(tmp_atomic), (
            f"Partial .tmp directory survived atomic write: {tmp_atomic}")
        # The final checkpoint must be loadable.
        _, _, _, clean_manifest = load_checkpoint(clean_ckpt)
        assert clean_manifest["step"] == 99, clean_manifest

        # ---- verify_resume: safe-resume vs restart-from-scratch determination ----
        # Layout now: step-00000005 (valid), step-00000099 (valid). Corrupt the
        # older one and plant an orphan .tmp; the determination must name step 99
        # as the safe-resume target, mark step 5 invalid, and never count the .tmp.
        with open(os.path.join(ckpt_dir, "model.pt"), "ab") as f:
            f.write(b"\x00")  # corrupt step-5 model.pt (sha mismatch)
        orphan = os.path.join(tmpdir, "checkpoints", "step-00000123.tmp")
        os.makedirs(orphan, exist_ok=True)

        vr = verify_resume(tmpdir)
        assert vr["verdict"] == "SAFE_RESUME", vr
        assert vr["checkpoints_scanned"] == 2, vr["checkpoints_scanned"]
        assert vr["checkpoints_valid"] == 1, vr["checkpoints_valid"]
        assert vr["latest_valid"]["step"] == 99, vr["latest_valid"]
        assert len(vr["orphan_tmp_dirs"]) == 1, vr["orphan_tmp_dirs"]
        corrupt_rec = [c for c in vr["checkpoints"] if not c["valid"]]
        assert len(corrupt_rec) == 1 and "sha256 mismatch" in corrupt_rec[0]["error"], corrupt_rec

        # Empty run dir → restart-from-scratch, fail-closed.
        empty_dir = os.path.join(tmpdir, "empty-run")
        os.makedirs(empty_dir, exist_ok=True)
        vr_empty = verify_resume(empty_dir)
        assert vr_empty["verdict"] == "RESTART_FROM_SCRATCH", vr_empty
        assert vr_empty["latest_valid"] is None, vr_empty

        print("TIMESHARE_PRETRAIN_SELFTEST_PASS")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _selftest_v0ext() -> None:
    """v0 survivor-stack selftest (eng-43, #167). CPU-only, no GPU, no daemon.

    Covers the contract's five components + the AC's full-stack proof:
      1. optimizer split-param routing (Muon vs AdamW) + the Newton-Schulz core
      2. WSD schedule shape (warmup/stable/decay boundaries + monotonicity)
      3. packed-shard loader round-trip (no-pad reconstruction + shifted targets)
      4. MTP head loss composition (+ CE-only fallback)
      5. full-stack CPU dry-run: step + checkpoint + bit-exact resume
    Plus: v0_config_check structural green, and both RECEIPTED fallback paths
    (AdamW-everything, CE-only) actually write a deviation receipt.

    Marker: TIMESHARE_V0EXT_SELFTEST_PASS
    """
    import numpy as np
    import torch

    cfg = load_contract()

    # ---- 0. contract is structurally green (the validator the launch shim runs)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import v0_config_check  # noqa: E402
    assert v0_config_check.check(cfg) == [], v0_config_check.check(cfg)

    # ---- 1. optimizer split-param routing -------------------------------
    model = _tiny_v0_model(vocab=64, hidden=32, n_mtp=2, depth=2)
    muon_named, adamw_named = split_param_groups(model)
    muon_names = {n for n, _ in muon_named}
    adamw_names = {n for n, _ in adamw_named}
    assert muon_names == {"blocks.0.weight", "blocks.1.weight"}, muon_names
    assert adamw_names == {"embed.weight", "norm.weight", "norm.bias",
                           "head.weight", "mtp_heads.0.weight",
                           "mtp_heads.1.weight"}, adamw_names
    # no param routed twice; every trainable param covered exactly once
    all_ids = {id(p) for _, p in model.named_parameters() if p.requires_grad}
    muon_ids = {id(p) for _, p in muon_named}
    adamw_ids = {id(p) for _, p in adamw_named}
    assert muon_ids.isdisjoint(adamw_ids), "a param is in both groups"
    assert muon_ids | adamw_ids == all_ids, "params dropped from routing"

    # Newton-Schulz core: the iteration pushes singular values toward 1, i.e.
    # makes the matrix MORE semi-orthogonal than the raw (Frobenius-normalized)
    # input. It is approximate by design at 5 steps (Muon needs near-, not
    # exact, orthogonality), so the claim is improvement, not a tiny residual.
    torch.manual_seed(0)
    G = torch.randn(8, 16)
    Xn = G / (G.norm() + 1e-7)
    before = (Xn @ Xn.T - torch.eye(8)).abs().max().item()
    O = _zeropower_via_newtonschulz5(G, steps=5)
    after = (O @ O.T - torch.eye(8)).abs().max().item()
    assert after < before, (
        f"Newton-Schulz did not improve orthogonality: {after} !< {before}")
    assert after < 0.35, f"Newton-Schulz residual too large: {after}"

    # Muon optimizer actually moves a 2D weight (the step ran end to end).
    Muon = _muon_class()
    p = torch.nn.Parameter(torch.randn(8, 16))
    before = p.detach().clone()
    mopt = Muon([p], lr=0.02)
    (p.sum()).backward()
    mopt.step()
    assert not torch.equal(before, p.detach()), "Muon step was a no-op"

    # ---- 2. WSD schedule shape ------------------------------------------
    T = 1000
    assert wsd_lr_frac(0, T, 0.01, 0.85, 0.10) == 0.0
    assert abs(wsd_lr_frac(5, T, 0.01, 0.85, 0.10) - 0.5) < 1e-9    # mid-warmup
    assert wsd_lr_frac(10, T, 0.01, 0.85, 0.10) == 1.0             # warmup end
    assert wsd_lr_frac(500, T, 0.01, 0.85, 0.10) == 1.0            # stable
    assert wsd_lr_frac(850, T, 0.01, 0.85, 0.10) == 1.0            # decay start
    assert abs(wsd_lr_frac(925, T, 0.01, 0.85, 0.10) - 0.55) < 1e-9  # mid-decay
    assert abs(wsd_lr_frac(T, T, 0.01, 0.85, 0.10) - 0.10) < 1e-9  # decay floor
    # monotone: warmup non-decreasing, decay non-increasing; all in [floor, 1]
    warm = [wsd_lr_frac(s, T, 0.01, 0.85, 0.10) for s in range(0, 10)]
    assert all(b >= a for a, b in zip(warm, warm[1:]))
    dec = [wsd_lr_frac(s, T, 0.01, 0.85, 0.10) for s in range(850, 1001, 10)]
    assert all(b <= a for a, b in zip(dec, dec[1:]))
    # global range is [0, 1]: warmup ramps from 0, decay bottoms at the floor
    assert all(0.0 <= wsd_lr_frac(s, T, 0.01, 0.85, 0.10) <= 1.0 + 1e-9
               for s in range(0, T + 1, 7))
    # boundaries hold on the ACTUAL contract fractions too
    sc = cfg["schedule"]
    assert wsd_lr_frac(0, T, sc["warmup_frac"], sc["stable_until_frac"],
                       sc["decay_to_lr_frac"]) == 0.0
    assert abs(wsd_lr_frac(T, T, sc["warmup_frac"], sc["stable_until_frac"],
                           sc["decay_to_lr_frac"]) - sc["decay_to_lr_frac"]) < 1e-9

    # ---- 3. packed-shard loader round-trip ------------------------------
    tmp = tempfile.mkdtemp(prefix="v0ext_selftest_")
    try:
        shard_dir = os.path.join(tmp, "shards")
        os.makedirs(shard_dir)
        N_TOK = 200
        stream = [(i % 60) + 1 for i in range(N_TOK)]
        stream[0] = 0  # a doc separator — packing flows across it
        stream[100] = 0
        write_packed_shard(os.path.join(shard_dir, "s-00000.bin"), stream)
        loader = PackedShardLoader(shard_dir, seq=8, n_mtp=2)
        assert loader.block_len == 11
        assert loader.n_windows == (N_TOK - 11) // 8 + 1
        # inputs disjoint + contiguous -> reconstruct the stream prefix exactly
        recon = []
        for i in range(loader.n_windows):
            x, y0, ym = loader.window_np(i)
            recon.extend(int(t) for t in x)
            base = i * 8
            assert list(int(t) for t in y0) == stream[base + 1:base + 9]
            assert list(int(t) for t in ym[0]) == stream[base + 2:base + 10]
            assert list(int(t) for t in ym[1]) == stream[base + 3:base + 11]
        assert recon == stream[:loader.n_windows * 8], "round-trip mismatch"
        # no pad token was ever introduced: every reconstructed token is real
        assert all(t in stream for t in recon)
        # batch() is a pure function of step (resume-safe)
        bx, by0, bym = loader.batch(0, 2)
        assert tuple(bx.shape) == (2, 8) and len(bym) == 2
        x0, _, _ = loader.window_np(0)
        assert list(int(t) for t in bx[0]) == list(int(t) for t in x0)

        # ---- 4. MTP loss composition ------------------------------------
        tot = mtp_total_loss(torch.tensor(2.0),
                             [torch.tensor(1.0), torch.tensor(3.0)], 0.3)
        assert abs(float(tot) - 2.6) < 1e-6, float(tot)   # 2 + 0.3*mean(1,3)
        ce_only = mtp_total_loss(torch.tensor(2.0), [], 0.3)
        assert float(ce_only) == 2.0, "CE-only fallback must equal primary CE"

        # ---- 5. full-stack CPU dry-run: step + checkpoint + bit-exact resume
        tiny = {"vocab": 64, "hidden": 32, "depth": 2, "seq": 8}
        shared = os.path.join(tmp, "shared-shards")
        os.makedirs(shared)
        rng = np.random.default_rng(7)
        toks = rng.integers(1, 64, size=4000, dtype=np.int64)
        toks[::24] = 0
        write_packed_shard(os.path.join(shared, "shared-00000.bin"),
                           toks.astype(np.uint16).tolist())
        Nstep, Mstep, TOTAL = 3, 4, 7

        def _run(run_dir, n_steps, resume=None):
            torch.manual_seed(123)
            random.seed(123)
            return run_v0_segment(
                run_dir, cfg, n_steps=n_steps, total_steps=TOTAL,
                checkpoint_every=Nstep, pace_s=0.0, shard_dir=shared,
                tiny_dims=tiny, batch_size=2, ce_chunk_tokens=8,
                resume_ckpt_dir=resume)

        straight = _run(os.path.join(tmp, "straight"), Nstep + Mstep)
        assert straight["verdict"] == "V0_SEGMENT_COMPLETE"
        assert len(straight["losses"]) == Nstep + Mstep
        ckpt_n = os.path.join(tmp, "straight", "checkpoints",
                              f"step-{Nstep:08d}")
        assert os.path.isdir(ckpt_n), "step-N checkpoint missing"
        resumed = _run(os.path.join(tmp, "resumed"), Mstep, resume=ckpt_n)
        assert len(resumed["losses"]) == Mstep
        # bit-exact: resumed trajectory == the straight run's tail
        for i, (a, b) in enumerate(zip(resumed["losses"],
                                       straight["losses"][Nstep:])):
            assert a == b, (f"resume not bit-exact at step {i}: "
                            f"{a!r} != {b!r}")
        # the Muon split optimizer was the live optimizer (not the fallback)
        assert straight["components"]["optimizer"]["mode"] == "muon_split"
        assert straight["components"]["ce"]["impl"] == "cut_ce_chunked"
        assert straight["components"]["mtp"]["enabled"] is True
        assert straight["components"]["mtp"]["n_heads"] == 2

        # ---- RECEIPTED fallbacks actually write a deviation receipt ------
        import receipt_check
        dev_dir = os.path.join(tmp, "devs")
        r_opt = run_v0_segment(
            os.path.join(tmp, "opt-fb"), cfg, n_steps=2, total_steps=2,
            checkpoint_every=2, pace_s=0.0, shard_dir=shared, tiny_dims=tiny,
            batch_size=2, ce_chunk_tokens=8, opt_force_fallback=True,
            deviation_dir=dev_dir)
        assert r_opt["components"]["optimizer"]["mode"] == \
            "adamw_everything_fallback"
        assert r_opt["deviation_receipts"], "optimizer fallback left no receipt"
        for dpath in r_opt["deviation_receipts"]:
            assert os.path.exists(dpath)
            assert receipt_check.run_file(dpath) == 0, dpath
            with open(dpath, encoding="utf-8") as f:
                assert "RECEIPTED" in f.read()

        r_mtp = run_v0_segment(
            os.path.join(tmp, "mtp-fb"), cfg, n_steps=2, total_steps=2,
            checkpoint_every=2, pace_s=0.0, shard_dir=shared, tiny_dims=tiny,
            batch_size=2, ce_chunk_tokens=8, mtp_force_fallback=True,
            deviation_dir=dev_dir)
        assert r_mtp["components"]["mtp"]["enabled"] is False
        assert r_mtp["components"]["mtp"]["n_heads"] == 0
        assert r_mtp["deviation_receipts"], "MTP fallback left no receipt"
        for dpath in r_mtp["deviation_receipts"]:
            assert os.path.exists(dpath) and receipt_check.run_file(dpath) == 0

        dryrun_summary = {
            "straight_steps": Nstep + Mstep,
            "resume_from_step": Nstep,
            "resumed_steps": Mstep,
            "bit_exact_resume": True,
            "optimizer_mode": straight["components"]["optimizer"]["mode"],
            "ce_impl": straight["components"]["ce"]["impl"],
            "mtp_n_heads": straight["components"]["mtp"]["n_heads"],
            "loader_n_windows": straight["components"]["loader"]["n_windows"],
            "loss_first": straight["loss_first"],
            "loss_last_resumed": resumed["loss_last"],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    checks = {
        "config_structural_green": True,
        "optimizer_split_routing": True,
        "newton_schulz_orthogonalizes": True,
        "wsd_schedule_shape": True,
        "packed_loader_roundtrip_nopad": True,
        "mtp_loss_composition": True,
        "full_stack_checkpoint_resume_bit_exact": True,
        "optimizer_fallback_receipted": True,
        "mtp_fallback_receipted": True,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "TIMESHARE-V0EXT-SELFTEST",
        "ts": ts,
        "issue": "wordingone/ember#167",
        "contract": "configs/v0-pretrain-config.json",
        "checks": checks,
        "dryrun": dryrun_summary,
        "components_implemented": [
            "muon-split-optimizer", "wsd-schedule", "chunked-cut-ce",
            "mtp-aux-heads-n2-w0.3", "packed-shard-loader-nopad"],
        "fallbacks_receipted": ["optimizer->adamw_everything", "mtp->ce_only"],
        "exclusions_held": ["no_fp8", "no_sparse_attention"],
        "base_preserved": ("eng-33 timeshare_pretrain.py surface byte-identical "
                           "— extension only"),
        "no_network": True,
        "no_gpu": True,
        "note": ("pace re-bench vs fp19-bench c03-qat rides the first governed "
                 "GPU window per the AC (live path gated by "
                 "EMBER_GATE_AUTHORIZED=1 + --live)"),
    }
    # ---- 6. launch-gate ENFORCEMENT (eng-52 #190) ----------------------
    # The interlock must consult v0_pretrain_launch_gate, not just env+flag —
    # else the gate is decorative (a meta-fail-open on GPU dispatch). No GPU is
    # reachable here: the interlock raises before any dispatch.
    import v0_pretrain_launch_gate as _lg  # noqa: E402
    _saved_env = os.environ.get("EMBER_GATE_AUTHORIZED")
    _saved_gate = _lg.gate
    try:
        # 6a: env+flag set but the REAL gate blocks (today: G-shards has no
        # shard receipt) -> the interlock must refuse with the gate's rows.
        os.environ["EMBER_GATE_AUTHORIZED"] = "1"
        _gate_refused = False
        try:
            _check_launch_interlock(live=True)
        except SystemExit as e:
            _gate_refused = "TIMESHARE_LAUNCH_GATE_REFUSED" in str(e)
        assert _gate_refused, ("interlock must refuse when the launch gate "
                               "blocks, even with env+flag set (eng-52)")
        # 6b: gate all-green (monkeypatched) -> the interlock passes.
        _lg.gate = lambda *a, **k: [(r, "GREEN", "ok") for r in _lg.ROWS]
        _check_launch_interlock(live=True)        # must NOT raise
        # 6c: the env/flag guard is still independently required (it fires
        # before the gate check) even when the gate would be green.
        os.environ.pop("EMBER_GATE_AUTHORIZED", None)
        _env_refused = False
        try:
            _check_launch_interlock(live=True)
        except SystemExit as e:
            _env_refused = "TIMESHARE_LAUNCH_INTERLOCK_REFUSED" in str(e)
        assert _env_refused, "env+flag guard must hold independently (eng-52)"
    finally:
        _lg.gate = _saved_gate
        if _saved_env is None:
            os.environ.pop("EMBER_GATE_AUTHORIZED", None)
        else:
            os.environ["EMBER_GATE_AUTHORIZED"] = _saved_env

    from receipt_write import checked_write
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(repo, "receipts", f"v0ext-selftest-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("TIMESHARE_V0EXT_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="Run pure-logic CPU selftest (< 30 s)")
    ap.add_argument("--selftest-v0ext", action="store_true",
                    help="Run the v0 survivor-stack selftest (eng-43, CPU-only)")
    ap.add_argument("--v0-dryrun", action="store_true",
                    help="Run a short v0 survivor-stack CPU dry-run (synthetic "
                         "shards) and print the segment receipt")
    ap.add_argument("--live", action="store_true",
                    help="Enable GPU path (requires EMBER_GATE_AUTHORIZED=1)")
    ap.add_argument("--run-dir", default=None,
                    help="Directory for checkpoints and receipts")
    ap.add_argument("--steps", type=int, default=100,
                    help="Number of optimizer steps")
    ap.add_argument("--segment-id", default="seg-A",
                    help="Segment label for receipts")
    ap.add_argument("--resume-ckpt", default=None,
                    help="Checkpoint directory to resume from")
    ap.add_argument("--verify-resume", action="store_true",
                    help="Scan --run-dir checkpoints and print the safe-resume "
                         "vs restart-from-scratch determination (no training)")
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        return

    if args.selftest_v0ext:
        _selftest_v0ext()
        return

    if args.v0_dryrun:
        import random as _r
        import torch
        torch.manual_seed(123)
        _r.seed(123)
        run_dir = args.run_dir or tempfile.mkdtemp(prefix="v0_dryrun_")
        cfg = load_contract()
        receipt = run_v0_segment(
            run_dir, cfg, n_steps=args.steps, total_steps=args.steps,
            checkpoint_every=max(1, args.steps // 2), pace_s=0.0,
            tiny_dims={"vocab": 64, "hidden": 32, "depth": 2, "seq": 16},
            batch_size=2, ce_chunk_tokens=64, segment_id=args.segment_id)
        from receipt_write import checked_write
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = os.path.join(repo, "receipts",
                           f"v0ext-dryrun-{receipt['ts']}.json")
        checked_write(out, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        print(f"[v0-dryrun] receipt: {out}")
        return

    if args.verify_resume:
        if not args.run_dir:
            raise SystemExit("--verify-resume requires --run-dir")
        print(json.dumps(verify_resume(args.run_dir), indent=2, sort_keys=True))
        return

    if args.live:
        _check_launch_interlock(live=True)

    run_dir = args.run_dir or tempfile.mkdtemp(prefix="timeshare_run_")
    receipt = run_segment(
        run_dir,
        args.steps,
        live=args.live,
        resume_ckpt_dir=args.resume_ckpt,
        segment_id=args.segment_id,
        tiny_cpu=not args.live,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
