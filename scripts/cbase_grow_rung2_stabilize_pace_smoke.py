#!/usr/bin/env python3
"""cbase_grow_rung2_stabilize_pace_smoke.py — ember #627 point 6 (AC2 pace-smoke).

ONE governed real-checkpoint block, bounded by the R4 27-min pace gate, banked
BEFORE the full leg is preregistered. The component benchmark #594's AC2 always
required a POST-CURE governed block receipt (the merged #619 delivered none);
this module is that receipt's producer.

BANKED, NOT EXECUTED. GPU execution is gated on the coordinator's explicit GO.
This module NEVER launches GPU work implicitly:

  * default (no mode flag)     -> print the exact GPU invocation and exit 3.
  * --cpu-precheck             -> full wiring PROOF on CPU, no GPU, no training,
                                  no shards: drives the REAL production pace-gate
                                  code path (cbase_grow_rung2_stabilize._run_block)
                                  with a CPU fake block and asserts the block
                                  cleanly self-aborts at the deadline with a
                                  PACE_GATE_ABORT + a completed-step checkpoint.
  * --confirm-gpu-go           -> the ONLY path that runs the real governed block.
                                  Asserts EMBER_GATE_AUTHORIZED and a live CUDA
                                  device first, then invokes the leg runner for a
                                  SINGLE governed block (--start-block == --n-blocks),
                                  whose first-block pace gate is auto-armed. The
                                  coordinator passes this flag; a builder/CI never
                                  does. Any GPU execution without it is impossible.

The single-block GPU invocation reuses cbase_grow_rung2_stabilize.main() verbatim
(no duplicated training/checkpoint math): the leg runner already arms PACE_GATE_S
on the first governed block, so "one governed block, pace-gated, real checkpoint"
is exactly `--start-block N --n-blocks N` against the cured resume checkpoint.

No git commits from this module. No founder/user names. api_spend_usd=0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cbase_grow_rung2_stabilize as stab  # noqa: E402
import timeshare_pretrain as ts            # noqa: E402


PACE_SMOKE_DEADLINE_S = stab.PACE_GATE_S  # 1620 s == 27 min (single source of truth)


def _gpu_invocation(args) -> list[str]:
    """The exact argv the coordinator's GO runs -- one governed, pace-gated,
    real-checkpoint block via the leg runner. start_block == n_blocks makes the
    RUN loop execute exactly one block, and that block is the first of the leg,
    so PACE_GATE_S is auto-armed on it."""
    argv = [
        sys.executable, str(Path(stab.__file__).resolve()),
        "--start-block", str(args.block), "--n-blocks", str(args.block),
        "--seed-ckpt", args.seed_ckpt,
        "--shard-dir", args.shard_dir,
        "--resume-ckpt-dir-override", args.resume_ckpt_dir,
    ]
    if args.out_dir:
        argv += ["--out-dir", args.out_dir]
    if args.receipt_dir:
        argv += ["--receipt-dir", args.receipt_dir]
    return argv


def cpu_precheck() -> dict:
    """Prove the pace-gate wiring end-to-end on CPU, without GPU/training/shards.

    Drives the REAL production code path -- stab._run_block -- with
    ts.run_v0_segment monkeypatched to a CPU fake that honours the cooperative
    abort_event exactly as the real loop does (checkpoint completed steps, set
    aborted_by_pace_gate, return). With a tiny deadline the watchdog must fire,
    the fake must observe the abort and return early, and _run_block must
    surface pace_gate.aborted == True with a checkpoint. This is the same
    mechanism the >=27-min real block will use; a green precheck means the
    bound is wired, only the GPU execution is pending GO."""
    results: dict = {"checks": []}

    orig_run_v0 = ts.run_v0_segment
    orig_stage_marker = stab._stage_marker
    orig_nvsmi = stab.nvidia_smi_vram
    orig_power = stab._nvidia_smi_power_watts
    orig_momentum = stab.momentum_norm_by_group

    # Neutralize the GPU/host-instrument side calls _run_block makes around the
    # block (all read-only telemetry; irrelevant to the pace-gate proof).
    stab._stage_marker = lambda label: None
    stab.nvidia_smi_vram = lambda: {"used_gib": 0.0, "free_gib": 0.0, "total_gib": 0.0}
    stab._nvidia_smi_power_watts = lambda: None
    stab.momentum_norm_by_group = lambda _c: {"note": "cpu-precheck: skipped"}

    tmp = tempfile.mkdtemp(prefix="pace_smoke_precheck_")
    fake = {"observed_abort": False, "loops": 0}

    def _fake_slow_block(run_dir, cfg, *, n_steps, abort_event=None, **kwargs):
        # A block that would run well past the deadline unless aborted.
        deadline = time.monotonic() + 30.0
        ckpt = os.path.join(run_dir, "checkpoints", "step-00000811")
        while time.monotonic() < deadline:
            fake["loops"] += 1
            if abort_event is not None and abort_event.is_set():
                fake["observed_abort"] = True
                os.makedirs(ckpt, exist_ok=True)
                with open(os.path.join(ckpt, "manifest.json"), "w",
                          encoding="utf-8", newline="\n") as f:
                    json.dump({"step": 811, "note": "cpu-precheck fake abort ckpt"}, f)
                return {
                    "losses": [12.1], "loss_first": 12.1, "loss_last": 12.1,
                    "global_step_end": 811, "last_checkpoint": ckpt,
                    "aborted_by_pace_gate": True,
                }
            time.sleep(0.02)
        # Deadline never hit the abort -> the gate FAILED to fire (precheck fails).
        return {"losses": [12.1], "loss_first": 12.1, "loss_last": 12.1,
                "global_step_end": 900, "last_checkpoint": ckpt,
                "aborted_by_pace_gate": False}

    try:
        ts.run_v0_segment = _fake_slow_block
        t0 = time.monotonic()
        block_receipt, _raw = stab._run_block(
            {"model": {"seq": 1024}}, os.path.join(tmp, "block-05"), tmp,
            global_step_start=806, total_steps=1000, shard_dir=tmp,
            grad_accum_steps=1, block_idx=5, sample_interval_s=0.05,
            pace_gate_s=0.3)  # tiny deadline for the precheck
        elapsed = time.monotonic() - t0

        aborted = bool(block_receipt["pace_gate"]["aborted"])
        armed = bool(block_receipt["pace_gate"]["armed"])
        has_ckpt = bool(block_receipt["checkpoint"]) and os.path.isdir(block_receipt["checkpoint"])
        fired_within = elapsed < 25.0  # far under the fake's 30s max => aborted mid-block

        results["checks"] = [
            {"name": "watchdog_armed", "pass": armed},
            {"name": "watchdog_fired_and_aborted_cleanly", "pass": aborted},
            {"name": "block_observed_cooperative_abort", "pass": fake["observed_abort"]},
            {"name": "aborted_mid_block_not_after", "pass": fired_within},
            {"name": "completed_step_checkpoint_written", "pass": has_ckpt},
        ]
        results["elapsed_s"] = round(elapsed, 3)
        results["fake_loops"] = fake["loops"]
        results["block_receipt_pace_gate"] = block_receipt["pace_gate"]
    finally:
        ts.run_v0_segment = orig_run_v0
        stab._stage_marker = orig_stage_marker
        stab.nvidia_smi_vram = orig_nvsmi
        stab._nvidia_smi_power_watts = orig_power
        stab.momentum_norm_by_group = orig_momentum
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    results["all_pass"] = all(c["pass"] for c in results["checks"])
    results["deadline_s_real_leg"] = PACE_SMOKE_DEADLINE_S
    results["verdict"] = "PACE_SMOKE_CPU_PRECHECK_PASS" if results["all_pass"] \
        else "PACE_SMOKE_CPU_PRECHECK_FAIL"
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--cpu-precheck", action="store_true",
                      help="prove the pace-gate wiring on CPU (no GPU, no training). Safe to run anywhere.")
    mode.add_argument("--confirm-gpu-go", action="store_true",
                      help="COORDINATOR-ONLY: run the real single governed block. Requires "
                           "EMBER_GATE_AUTHORIZED and a live CUDA device. Never run by a builder/CI.")
    ap.add_argument("--block", type=int, default=stab.LINEAGE_LEG_START_BLOCK,
                    help="the single governed block index to run (default: the frozen leg start, block 5)")
    ap.add_argument("--seed-ckpt", help="pre-grow checkpoint dir (for resume manifest/step)")
    ap.add_argument("--shard-dir", help="real packed corpus shard dir")
    ap.add_argument("--resume-ckpt-dir", help="cured block-04 step-806 resume checkpoint dir")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--receipt-dir", default=None)
    args = ap.parse_args(argv)

    if args.cpu_precheck:
        res = cpu_precheck()
        print(json.dumps(res, indent=2))
        print(res["verdict"], flush=True)
        return 0 if res["all_pass"] else 1

    if args.confirm_gpu_go:
        # Hard gate: never launch GPU work without the authorized environment AND
        # a live CUDA device. abort-not-degrade -- refuse rather than degrade.
        import importlib
        torch = importlib.import_module("torch")
        if os.environ.get("EMBER_GATE_AUTHORIZED") != "1":
            print("PACE_SMOKE_REFUSED: EMBER_GATE_AUTHORIZED != 1 -- coordinator GO required", flush=True)
            return 2
        if not torch.cuda.is_available():
            print("PACE_SMOKE_REFUSED: no CUDA device -- the pace-smoke is a GPU action", flush=True)
            return 2
        if not (args.seed_ckpt and args.shard_dir and args.resume_ckpt_dir):
            print("PACE_SMOKE_REFUSED: --seed-ckpt, --shard-dir, --resume-ckpt-dir required for GPU run",
                  flush=True)
            return 2
        argv_run = _gpu_invocation(args)
        print(f"PACE_SMOKE_GPU_GO ts={datetime.now(timezone.utc).isoformat()} "
              f"block={args.block} deadline_s={PACE_SMOKE_DEADLINE_S}", flush=True)
        # Reuse the leg runner verbatim (single block, pace-gated) -- no duplicated math.
        import subprocess
        proc = subprocess.run(argv_run)
        return proc.returncode

    # Default: print the invocation, run nothing (banked-not-executed).
    print("cbase_grow_rung2_stabilize_pace_smoke — AC2 pace-smoke (ember #627 point 6)")
    print(f"  deadline: {PACE_SMOKE_DEADLINE_S} s ({PACE_SMOKE_DEADLINE_S // 60} min), single governed block")
    print("  BANKED, NOT EXECUTED. GPU execution is gated on the coordinator's explicit GO.")
    print("  CPU wiring proof (safe anywhere):")
    print(f"    {Path(sys.executable).name} {Path(__file__).name} --cpu-precheck")
    print("  Coordinator GPU GO (requires EMBER_GATE_AUTHORIZED=1 + CUDA):")
    print(f"    {Path(sys.executable).name} {Path(__file__).name} --confirm-gpu-go \\")
    print("        --seed-ckpt <dir> --shard-dir <dir> --resume-ckpt-dir <cured block-04 step-806 dir>")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
