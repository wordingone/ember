"""fp37_l7_duty_cycle.py — L7: harness-side stall receipt for run 12c050e7.

Extracts checkpoint-interval tok/s from the v0-r1s1 run dir and compares
against the E4 profiler baseline (pure compute + governor, no loader) to
measure the data-loader and checkpoint-I/O stall fractions.

Scope: HARNESS-side stalls only (loader/checkpoint/eval gaps) — the GPU
anatomy is already receipted in fp33-e4-profiler. This receipt feeds c04
harness design (architecture-independent gap fraction).

No GPU required. Reads checkpoint manifests + E4 profiler receipt.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write                        # noqa: E402

RUN_DIR   = (r"B:\M\avir\eli\state\ember-eng\runs\v0-r1s1"
             if os.name == "nt" else
             "/mnt/b/M/avir/eli/state/ember-eng/runs/v0-r1s1")
RECEIPTS  = f"{NC}/receipts"
JOB_ID    = "12c050e7"
JOB_START = "2026-06-12T01:30:50Z"   # daemon-recorded start (train_list)
BATCH     = 4
SEQ       = 1024
TOKENS_PER_STEP = BATCH * SEQ        # 4096

# E4 profiler: GPU-phase anatomy (synthetic, no loader)
E4_RECEIPT = os.path.join(RUN_DIR, "receipts",
                          "fp33-e4-profiler-20260612T032739Z.json")
E4_PHASE_GPU_TOTAL_MS_PER_STEP = 406.75    # from E4 receipt (15-step mean)
GOVERNOR_PACE_S = 0.05                      # floor, never loosened

# checkpoint-every from v0_r1s1_launch.py
CKPT_EVERY = 25000


def _parse_ts(s):
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def load_checkpoints():
    base = os.path.join(RUN_DIR, "checkpoints")
    ckpts = sorted(os.listdir(base))
    out = []
    for c in ckpts:
        p = os.path.join(base, c, "manifest.json")
        if not os.path.exists(p):
            continue
        m = json.load(open(p, encoding="utf-8"))
        ts = datetime.strptime(m["ts"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc)
        sizes = {}
        ckpt_path = os.path.join(base, c)
        for f in os.listdir(ckpt_path):
            if f == "manifest.json":
                continue
            sizes[f] = os.path.getsize(os.path.join(ckpt_path, f))
        out.append({"step": m["step"], "ts": ts, "sizes_bytes": sizes})
    return out


def analyze(ckpts, job_start_ts):
    intervals = []
    prev_step = 0
    prev_ts = job_start_ts
    for c in ckpts:
        steps_in_interval = c["step"] - prev_step
        dt = (c["ts"] - prev_ts).total_seconds()
        s_per_step = dt / steps_in_interval
        tok_s = TOKENS_PER_STEP / s_per_step
        ckpt_bytes = sum(c["sizes_bytes"].values())
        intervals.append({
            "to_step": c["step"],
            "steps": steps_in_interval,
            "wall_s": round(dt, 1),
            "s_per_step": round(s_per_step, 5),
            "tok_s": round(tok_s, 1),
            "checkpoint_bytes": ckpt_bytes,
        })
        prev_step = c["step"]
        prev_ts = c["ts"]

    # Exclude first interval (includes model init + shard-scan startup)
    steady = intervals[1:] if len(intervals) > 1 else intervals
    avg_s_per_step = sum(i["s_per_step"] for i in steady) / len(steady)
    avg_tok_s = TOKENS_PER_STEP / avg_s_per_step

    # Checkpoint I/O amortization (one write per interval, spread over
    # CKPT_EVERY steps — model.pt + optimizer.pt sequential write)
    # Estimate from file size + conservative 400 MB/s NVMe → WSL2 throughput
    ckpt_bytes_typical = sum(ckpts[-1]["sizes_bytes"].values())
    ckpt_write_s_est = ckpt_bytes_typical / (400e6)    # 400 MB/s (WSL2 floor)
    ckpt_amortized_s_per_step = ckpt_write_s_est / CKPT_EVERY

    # E4 baseline: pure GPU compute + governor (no loader)
    e4_compute_s = E4_PHASE_GPU_TOTAL_MS_PER_STEP / 1000.0
    e4_expected_s_per_step = e4_compute_s + GOVERNOR_PACE_S

    # Stall attribution
    total_gap_s = avg_s_per_step - e4_expected_s_per_step
    loader_stall_s = max(0.0, total_gap_s - ckpt_amortized_s_per_step)
    loader_stall_pct = 100 * loader_stall_s / avg_s_per_step
    ckpt_stall_pct = 100 * ckpt_amortized_s_per_step / avg_s_per_step
    governor_pct = 100 * GOVERNOR_PACE_S / avg_s_per_step
    compute_pct = 100 * e4_compute_s / avg_s_per_step

    # Wall-days cost of loader+ckpt stalls for full c03 run
    total_steps = ckpts[-1]["sizes_bytes"] and 1702547   # from launch script
    total_steps = 1702547
    remaining_steps = total_steps - ckpts[-1]["step"] if ckpts else total_steps
    stall_wall_days = ((loader_stall_s + ckpt_amortized_s_per_step)
                       * total_steps / 86400)

    return {
        "intervals": intervals,
        "steady_state": {
            "intervals_used": len(steady),
            "avg_s_per_step": round(avg_s_per_step, 5),
            "avg_tok_s_paced": round(avg_tok_s, 1),
        },
        "e4_baseline": {
            "receipt": os.path.basename(E4_RECEIPT),
            "compute_ms_per_step": E4_PHASE_GPU_TOTAL_MS_PER_STEP,
            "governor_s_per_step": GOVERNOR_PACE_S,
            "expected_s_per_step": round(e4_expected_s_per_step, 5),
            "expected_tok_s": round(TOKENS_PER_STEP / e4_expected_s_per_step, 1),
        },
        "stall_attribution": {
            "total_gap_s_per_step": round(total_gap_s, 5),
            "loader_stall_s_per_step": round(loader_stall_s, 5),
            "ckpt_amortized_s_per_step": round(ckpt_amortized_s_per_step, 5),
            "ckpt_write_est_s": round(ckpt_write_s_est, 2),
            "ckpt_bytes_total": ckpt_bytes_typical,
        },
        "duty_cycle_pct": {
            "gpu_compute": round(compute_pct, 2),
            "governor_sleep": round(governor_pct, 2),
            "loader_stall": round(loader_stall_pct, 2),
            "ckpt_io": round(ckpt_stall_pct, 2),
            "note": "gpu_compute + governor + loader + ckpt ≈ 100%",
        },
        "wall_days_impact": {
            "total_steps": total_steps,
            "steps_completed": ckpts[-1]["step"] if ckpts else 0,
            "stall_wall_days_full_run": round(stall_wall_days, 4),
            "note": ("loader+ckpt stall cost for the full 1.7M-step c03 run"
                     " — feeds c04 harness gap budget"),
        },
    }


def main():
    from datetime import datetime as _dt
    ts_now = _dt.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    ckpts = load_checkpoints()
    assert ckpts, "no checkpoints found in run dir"
    job_start_ts = _parse_ts(JOB_START)

    result = analyze(ckpts, job_start_ts)

    print(f"[fp37_l7] checkpoints: {len(ckpts)}, up to step {ckpts[-1]['step']}")
    print(f"[fp37_l7] steady avg: {result['steady_state']['avg_tok_s_paced']} tok/s "
          f"({result['steady_state']['avg_s_per_step']:.4f}s/step)")
    print(f"[fp37_l7] e4 baseline: {result['e4_baseline']['expected_tok_s']} tok/s "
          f"({result['e4_baseline']['expected_s_per_step']:.4f}s/step)")
    dc = result["duty_cycle_pct"]
    print(f"[fp37_l7] duty cycle: compute={dc['gpu_compute']}% "
          f"governor={dc['governor_sleep']}% "
          f"loader={dc['loader_stall']}% ckpt={dc['ckpt_io']}%")
    print(f"[fp37_l7] stall wall-days (full run): "
          f"{result['wall_days_impact']['stall_wall_days_full_run']}")

    receipt = {
        "ticket": "FP37-L7-DUTY-CYCLE",
        "ts": ts_now,
        "lever": "L7",
        "issue": 225,
        "job_id": JOB_ID,
        "scope": ("harness-side stalls: loader/checkpoint-I/O — "
                  "GPU anatomy receipted in E4; scope per leo mail 15070"),
        "run_dir": RUN_DIR,
        "job_started_at": JOB_START,
        "result": result,
        "governor": {
            "vram_fraction": 0.80,
            "margin_gib_floor": 1.5,
            "pace_s_per_step": GOVERNOR_PACE_S,
        },
        "flags": [
            f"batch={BATCH}, seq={SEQ}, tokens_per_step={TOKENS_PER_STEP}",
            f"checkpoints: {len(ckpts)} written, every {CKPT_EVERY} steps",
            "first interval excluded from steady-state (startup overhead)",
            "ckpt write speed estimated at 400 MB/s (WSL2 NTFS floor)",
            f"e4_baseline: {os.path.basename(E4_RECEIPT)} (GPU phases, synthetic)",
        ],
    }

    out = f"{RECEIPTS}/fp37-l7-duty-cycle-{ts_now}.json"
    checked_write(out, receipt)
    print(f"FP37_L7_DUTY_CYCLE_DONE {os.path.relpath(out, NC)}")
    return receipt


if __name__ == "__main__":
    main()
