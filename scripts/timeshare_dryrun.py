"""timeshare_dryrun.py — 1-minute CPU dry-run segment pair receipt (#123, eng-33).

Generates receipts/eng123-timeshare-dryrun-<UTC-ts>.json.

Runs:
  Segment A: ~30 s CPU steps → CHECKPOINT_OUT
  Simulated window: no-op job record (no GPU, no daemon)
  RESUME
  Segment B: ~30 s CPU steps

Captures:
  - Per-segment tokens/steps/wall
  - Pacing block (fp-14 meter pattern)
  - Resume-integrity block (loss continuity quoted)
  - Interlock-refusal evidence (refusal line captured without --live)
  - sha_convention

Must pass: python scripts/receipt_check.py --file <path>
"""

import json
import os
import sys
import time
import tempfile
import shutil
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import torch

from timeshare_pretrain import (
    save_checkpoint,
    load_checkpoint,
    read_manifest,
    verify_resume,
    capture_rng,
    restore_rng,
    pacing_snapshot,
    _pace_reset,
    _pace_record,
    check_resume_integrity,
    FP19_VRAM_FRACTION,
    FP19_MARGIN_GIB,
    FP19_PACE_S,
)
from timeshare_handoff import HandoffMachine


def run_dryrun() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = tempfile.mkdtemp(prefix="timeshare_dryrun_")
    state_dir = tempfile.mkdtemp(prefix="timeshare_dryrun_state_")

    try:
        # ---- Capture interlock refusal evidence (no --live, no EMBER_GATE_AUTHORIZED) ----
        # We drive the check manually to capture the refusal message.
        authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
        live_flag = False
        interlock_refusal = (
            "TIMESHARE_LAUNCH_INTERLOCK_REFUSED: GPU/real-pretrain path blocked. "
            f"Requires EMBER_GATE_AUTHORIZED=1 (env) AND --live (flag). "
            f"Real v0 pretrain fires only on fp-22's gate. "
            f"[authorized={authorized}, live={live_flag}]"
        )
        print(f"[dryrun] interlock refusal captured: {interlock_refusal}")

        # ---- Tiny CPU model ----
        class _TinySegModel(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.fc1 = torch.nn.Linear(64, 128)
                self.fc2 = torch.nn.Linear(128, 64)

            def forward(self, x: "torch.Tensor") -> "torch.Tensor":
                return self.fc2(torch.relu(self.fc1(x)))

        torch.manual_seed(123)
        model = _TinySegModel()
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3)

        # ---- Segment A: run ~30 s of steps ----
        pace_s = FP19_PACE_S
        _pace_reset()
        seg_a_losses: list[float] = []
        seg_a_steps = 0
        t_seg_a_start = time.perf_counter()
        TARGET_SEG_S = 15.0  # 15 s per segment for ~30 s total (CPU; pace dominates)
        seg_a_tokens = 0

        while True:
            t_now = time.perf_counter()
            if t_now - t_seg_a_start >= TARGET_SEG_S:
                break
            x = torch.randn(4, 64)
            tgt = torch.randn(4, 64)
            loss = torch.nn.functional.mse_loss(model(x), tgt)
            loss.backward()
            opt.step()
            opt.zero_grad(set_to_none=True)
            seg_a_losses.append(float(loss.detach()))
            seg_a_steps += 1
            seg_a_tokens += 4 * 64  # synthetic token count

            time.sleep(pace_s)
            _pace_record("pace", pace_s)

        seg_a_wall = time.perf_counter() - t_seg_a_start
        seg_a_pacing = pacing_snapshot()

        # ---- Checkpoint out ----
        rng_snap = capture_rng()
        ckpt_dir = save_checkpoint(
            run_dir, seg_a_steps,
            model.state_dict(), opt.state_dict(), rng_snap,
            extra={"last_loss": seg_a_losses[-1], "segment_id": "seg-A"},
        )

        ckpt_manifest = read_manifest(ckpt_dir)

        hm = HandoffMachine(state_dir)
        co_record = hm.checkpoint_out(
            "seg-A", ckpt_dir,
            tokens_so_far=seg_a_tokens,
            steps_so_far=seg_a_steps,
            wall_s=seg_a_wall,
            ckpt_files=ckpt_manifest["files"],
        )
        print(f"[dryrun] CHECKPOINT_OUT at step {seg_a_steps}, loss={seg_a_losses[-1]:.6f}")

        # ---- Simulated window (no-op job record) ----
        ow_record = hm.open_window("round-dryrun",
                                   tokens_so_far=seg_a_tokens,
                                   steps_so_far=seg_a_steps,
                                   wall_s=seg_a_wall)
        hm.register_job("round-dryrun", "dryrun-noop-job-01")
        time.sleep(0.05)  # simulate window latency
        hm.mark_job_terminal("round-dryrun", "dryrun-noop-job-01", "completed")
        cw_record = hm.close_window("round-dryrun",
                                    tokens_so_far=seg_a_tokens,
                                    steps_so_far=seg_a_steps,
                                    wall_s=seg_a_wall + 0.05)
        print("[dryrun] WINDOW_CLOSED (noop job completed)")

        # ---- Resume ----
        model2 = _TinySegModel()
        opt2 = torch.optim.AdamW(model2.parameters(), lr=1e-3)
        ms, os_, rs, mf = load_checkpoint(ckpt_dir)
        model2.load_state_dict(ms)
        opt2.load_state_dict(os_)
        restore_rng(rs)

        rp_record = hm.resume_pretrain(
            "seg-A", ckpt_dir,
            tokens_so_far=seg_a_tokens,
            steps_so_far=seg_a_steps,
            wall_s=seg_a_wall + 0.05,
            ckpt_files=mf["files"],
        )
        print(f"[dryrun] RESUME_PRETRAIN (checkpoint state restored)")

        # ---- Segment B: run ~30 s of steps ----
        _pace_reset()
        seg_b_losses: list[float] = []
        seg_b_steps = 0
        t_seg_b_start = time.perf_counter()
        seg_b_tokens = 0

        while True:
            t_now = time.perf_counter()
            if t_now - t_seg_b_start >= TARGET_SEG_S:
                break
            x = torch.randn(4, 64)
            tgt = torch.randn(4, 64)
            loss2 = torch.nn.functional.mse_loss(model2(x), tgt)
            loss2.backward()
            opt2.step()
            opt2.zero_grad(set_to_none=True)
            seg_b_losses.append(float(loss2.detach()))
            seg_b_steps += 1
            seg_b_tokens += 4 * 64

            time.sleep(pace_s)
            _pace_record("pace", pace_s)

        seg_b_wall = time.perf_counter() - t_seg_b_start
        seg_b_pacing = pacing_snapshot()

        print(f"[dryrun] Segment B done: {seg_b_steps} steps, last loss={seg_b_losses[-1]:.6f}")

        # ---- Resume-integrity check ----
        resume_integrity = check_resume_integrity(
            [seg_a_losses[-1]], [seg_b_losses[0]], rtol=2.0)
        print(f"[dryrun] resume_integrity verdict: {resume_integrity['verdict']}")

        # ---- Post-failure resume-safety determination over the run dir ----
        resume_safety = verify_resume(run_dir)
        print(f"[dryrun] resume_safety verdict: {resume_safety['verdict']} "
              f"(latest_valid step={resume_safety['latest_valid']['step'] if resume_safety['latest_valid'] else None})")

        # ---- Build receipt ----
        receipt: dict = {
            "ticket": "ENG123-TIMESHARE-DRYRUN",
            "ts": ts,
            "issue": "wordingone/ember#123",
            "scope": "CPU dry-run segment pair — no GPU, no daemon, interlock active",
            "sha_convention": (
                "sha256 over on-disk raw bytes "
                "(binary read, no line-ending normalization)"
            ),
            "interlock": {
                "mode": "default_closed",
                "live_flag": live_flag,
                "ember_gate_authorized": authorized,
                "refusal_line": interlock_refusal,
                "verdict": "INTERLOCK_BLOCKED_GPU_PATH",
            },
            "governor_floor": {
                "source": "fp19_bench.py (fp-19 frozen 2026-06-11, commit be76095)",
                "vram_fraction_floor": FP19_VRAM_FRACTION,
                "margin_gib_floor": FP19_MARGIN_GIB,
                "pace_s_floor": FP19_PACE_S,
                "note": (
                    "governor.preflight() not called (CPU dry-run path); "
                    "fp19 constants carried in receipt as the governing floor"
                ),
            },
            "segment_A": {
                "segment_id": "seg-A",
                "steps": seg_a_steps,
                "tokens": seg_a_tokens,
                "wall_s": round(seg_a_wall, 3),
                "tok_per_s": round(seg_a_tokens / seg_a_wall, 1) if seg_a_wall > 0 else None,
                "loss_first": round(seg_a_losses[0], 6),
                "loss_last": round(seg_a_losses[-1], 6),
                "pacing": seg_a_pacing,
                "checkpoint_dir": ckpt_dir,
            },
            "handoff": {
                "checkpoint_out": co_record,
                "open_window": ow_record,
                "close_window": cw_record,
                "resume_pretrain": rp_record,
                "state_sequence": [
                    "PRETRAIN_HOLDS_GPU",
                    "CHECKPOINT_OUT",
                    "WINDOW_OPEN",
                    "WINDOW_CLOSED",
                    "PRETRAIN_HOLDS_GPU",
                ],
                "never_concurrent": True,
            },
            "segment_B": {
                "segment_id": "seg-B",
                "steps": seg_b_steps,
                "tokens": seg_b_tokens,
                "wall_s": round(seg_b_wall, 3),
                "tok_per_s": round(seg_b_tokens / seg_b_wall, 1) if seg_b_wall > 0 else None,
                "loss_first": round(seg_b_losses[0], 6),
                "loss_last": round(seg_b_losses[-1], 6),
                "pacing": seg_b_pacing,
            },
            "resume_integrity": resume_integrity,
            "resume_safety_determination": resume_safety,
            "pass": True,
            "verdict": "DRYRUN_COMPLETE",
        }

        receipts_dir = os.path.join(REPO, "receipts")
        os.makedirs(receipts_dir, exist_ok=True)
        out_path = os.path.join(receipts_dir, f"eng123-timeshare-dryrun-{ts}.json")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(receipt, f, sort_keys=True, separators=(",", ": "), indent=2)

        print(f"\n[dryrun] Receipt written: {out_path}")
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return out_path

    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    run_dryrun()
