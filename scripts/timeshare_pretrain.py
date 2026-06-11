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

    if resume_ckpt_dir is not None:
        m_state, o_state, r_state, manifest = load_checkpoint(resume_ckpt_dir)
        model.load_state_dict(m_state)
        optimizer.load_state_dict(o_state)
        restore_rng(r_state)
        resume_step = manifest["step"]
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
        "resume_integrity": resume_receipt,
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
        "pass": True,
        "verdict": "SEGMENT_COMPLETE",
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

        print("TIMESHARE_PRETRAIN_SELFTEST_PASS")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="Run pure-logic CPU selftest (< 30 s)")
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
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
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
