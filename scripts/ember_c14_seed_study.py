#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_c14_seed_study.py — C14 seed-sensitivity CPU study (issue #4 comment
"8j" pre-registered follow-up to C14 attempt 19,
receipts/ember-c14-owned-run/live-20260703T154830Z.json, verdict
C14-LIVE-NOT-CLEARED).

PURPOSE: attempt 19 was a single --live run (one seed, one GPU pass). Its
shape — static-phase train acquisition onset ~step 192, peak train pass-rate
3/5 (rows differ slightly by seed) around steps 704-896, heldout 0/3 at every
checkpoint, and a destructive dynamic phase (corpus-v3 exemplar resampling
switched on at step 768) that degraded train performance by the final
checkpoint — is a SINGLE-RUN observation. This script asks: how much of that
shape is seed noise vs a real property of the training dynamics, so future
single-run deltas (attempt 20+) are interpretable against a baseline
variance, not read as if they were noise-free.

SUBSTRATE (CPU-cheap, reuses the runner's OWN machinery, never
reimplemented): src/ember/governance/scripts/ember_c14_owned_run.py --dry-run — CPU, toy core
(TinyPolicyTransformer), but the FULL rig path (run_rig() + every
GatePredicate + check_guards()) via that file's own corpus generator, and
critically: --dry-run supports --corpus-v3-resample /
--corpus-v3-resample-start-step and --eval-checkpoint-interval IDENTICALLY
to --live (same cmd_dry_run/cmd_live code paths call the same
generate_corpus(), _make_corpus_v3_resample_fn(), _make_checkpoint_eval_
callback(), run_rig()). So this study's dry-run substrate expresses BOTH the
static acquisition phase AND the dynamic destruction phase — nothing about
the protocol is reduced to fit CPU; only the core (toy transformer vs the
real ~368M-param owned core) differs. See HONESTY NOTE in the summary
receipt for the one caveat this does NOT resolve.

ENVELOPE (held fixed across every seed, copied verbatim from attempt 19's
receipt envelope_v1_7 block): corpus_seed=20260702, heldout_size=3,
corpus_v2 (k_exemplars=3), corpus_v3_resample with
corpus_v3_resample_start_step=768, n_train_steps=1024, lr=1e-3,
temp_schedule="1.5:1.0:384", entropy_beta=0.02, degenerate_resample,
eval_checkpoint_interval=64. The ONLY thing this script varies across runs
is --seed (torch.manual_seed/random.seed at cmd_dry_run's top — the RNG
stream driving Stage-1/Stage-2 rollout sampling and the degenerate-resample
retry), which is exactly the seed-sensitivity axis issue #4/8j asks about.
--corpus-seed is held fixed on purpose: this study isolates TRAINING-RNG
variance, not corpus/split variance (a separate study).

STATISTICS (per seed, from that seed's 16 checkpoint_evals rows):
  onset_step:            first checkpoint step with train_pass_count/
                          train_total >= 0.4 (i.e. >= 2/5 on this corpus's
                          5-task train split) — None if never reached.
  peak_static:            max train_pass_count over checkpoints at
                          step <= corpus_v3_resample_start_step (768).
  peak_overall:           max train_pass_count over ALL checkpoints.
  final_train:            train_pass_count at the LAST checkpoint
                          (step == n_train_steps).
  destruction_magnitude:  peak_static - final_train (can be <= 0 if the
                          seed never regressed; reported as-is, never
                          clipped).
  heldout_ever_nonzero:   True if ANY checkpoint (any step) for this seed
                          has heldout_pass_count > 0 — the transfer
                          question attempt 19 answered "no" for on one seed.

RECEIPTS: one JSON per seed under receipts/ember-c14-seed-study/, plus one
summary JSON aggregating the two target distributions (onset, destruction)
and the heldout-ever-nonzero flag across all seeds. Every receipt records
its exact CLI invocation and the underlying dry-run receipt path it was
computed from (full provenance, nothing recomputed from memory).

CPU-ONLY. No .cuda() call anywhere in this file; the wrapped runner's
--dry-run path never touches a GPU (TinyPolicyTransformer has no device
kwarg). No git commits. No founder/user names in any receipt.

Run:
  python scripts/ember_c14_seed_study.py --seeds 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16
  python scripts/ember_c14_seed_study.py --seeds 1-16 --wall-budget-s 9000
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "scripts" / "ember_c14_owned_run.py"
OUT_DIR = REPO / "receipts" / "ember-c14-seed-study"

# Envelope copied verbatim from attempt 19's live receipt
# (receipts/ember-c14-owned-run/live-20260703T154830Z.json ->
# corpus / envelope_v1_7 blocks) -- see this file's module docstring.
CORPUS_SEED = 20260702
HELDOUT_SIZE = 3
K_EXEMPLARS = 3
N_TRAIN_STEPS = 1024
LR = 1e-3
TEMP_SCHEDULE = "1.5:1.0:384"
ENTROPY_BETA = 0.02
CORPUS_V3_RESAMPLE_START_STEP = 768
EVAL_CHECKPOINT_INTERVAL = 64
ONSET_THRESHOLD_FRACTION = 0.4  # >= 2/5 on this corpus's fixed 5-task train split

TICKET = "C14-SEED-SENSITIVITY-STUDY"
SHA_CONVENTION = "sha256"


def _ts_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_seed_list(spec: str) -> list[int]:
    """Accepts comma-separated ints and/or 'a-b' ranges, e.g. '1-16' or
    '1,2,3,9001'. Order-preserving, de-duplicated."""
    seeds: list[int] = []
    seen: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk and not chunk.startswith("-"):
            lo, hi = chunk.split("-", 1)
            for s in range(int(lo), int(hi) + 1):
                if s not in seen:
                    seeds.append(s)
                    seen.add(s)
        else:
            s = int(chunk)
            if s not in seen:
                seeds.append(s)
                seen.add(s)
    return seeds


def _build_argv(seed: int, n_train_steps: int, eval_checkpoint_interval: int) -> list[str]:
    return [
        sys.executable, str(RUNNER), "--dry-run",
        "--seed", str(seed),
        "--corpus-seed", str(CORPUS_SEED),
        "--heldout-size", str(HELDOUT_SIZE),
        "--corpus-v2",
        "--k-exemplars", str(K_EXEMPLARS),
        "--corpus-v3-resample",
        "--corpus-v3-resample-start-step", str(CORPUS_V3_RESAMPLE_START_STEP),
        "--n-train-steps", str(n_train_steps),
        "--lr", str(LR),
        "--temp-schedule", TEMP_SCHEDULE,
        "--entropy-beta", str(ENTROPY_BETA),
        "--degenerate-resample",
        "--eval-checkpoint-interval", str(eval_checkpoint_interval),
    ]


def _run_one_seed(seed: int, n_train_steps: int, eval_checkpoint_interval: int) -> dict:
    """Subprocess the existing runner for one seed; parse its stdout for the
    receipt path it printed (`receipt=<path>`), load that receipt, and
    return a dict with the raw subprocess result + parsed underlying
    receipt. Raises RuntimeError with full stdout/stderr on any failure —
    never silently skips a seed."""
    argv = _build_argv(seed, n_train_steps, eval_checkpoint_interval)
    t0 = time.time()
    proc = subprocess.run(
        argv, cwd=str(REPO), capture_output=True, text=True, timeout=1800,
    )
    wall_s = time.time() - t0
    if proc.returncode not in (0, 1):
        # 0 = C14-DRY-RUN-PASS, 1 = C14-DRY-RUN-NOT-CLEARED -- both are
        # legitimate completed runs (see cmd_dry_run's return). Anything
        # else (exception, arg error) is a genuine failure.
        raise RuntimeError(
            f"seed={seed} subprocess exit={proc.returncode}\n"
            f"argv={argv}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    receipt_path: Optional[Path] = None
    for line in proc.stdout.splitlines():
        if line.startswith("receipt="):
            receipt_path = Path(line[len("receipt="):].strip())
            break
    if receipt_path is None or not receipt_path.exists():
        raise RuntimeError(
            f"seed={seed}: could not locate underlying receipt path in "
            f"stdout.\nargv={argv}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    underlying = json.loads(receipt_path.read_text(encoding="utf-8"))
    return {
        "seed": seed,
        "argv": argv,
        "wall_s": wall_s,
        "returncode": proc.returncode,
        "underlying_receipt_path": str(receipt_path.relative_to(REPO)).replace("\\", "/"),
        "underlying_receipt": underlying,
    }


def _compute_stats(underlying: dict) -> dict:
    ce = underlying.get("checkpoint_evals") or []
    if not ce:
        raise RuntimeError(
            "underlying receipt has no checkpoint_evals -- "
            "--eval-checkpoint-interval must have been dropped somewhere"
        )
    ce_sorted = sorted(ce, key=lambda r: r["step"])

    onset_step = None
    for row in ce_sorted:
        frac = row["train_pass_count"] / row["train_total"] if row["train_total"] else 0.0
        if frac >= ONSET_THRESHOLD_FRACTION:
            onset_step = row["step"]
            break

    static_rows = [r for r in ce_sorted if r["step"] <= CORPUS_V3_RESAMPLE_START_STEP]
    peak_static = max((r["train_pass_count"] for r in static_rows), default=0)
    peak_overall = max(r["train_pass_count"] for r in ce_sorted)
    final_row = ce_sorted[-1]
    final_train = final_row["train_pass_count"]
    destruction_magnitude = peak_static - final_train
    destruction_magnitude_overall_peak = peak_overall - final_train
    heldout_ever_nonzero = any(r["heldout_pass_count"] > 0 for r in ce_sorted)

    return {
        "onset_step": onset_step,
        "onset_reached": onset_step is not None,
        "peak_static": peak_static,
        "peak_overall": peak_overall,
        "final_train": final_train,
        "final_step": final_row["step"],
        "destruction_magnitude": destruction_magnitude,
        "destruction_magnitude_overall_peak": destruction_magnitude_overall_peak,
        "heldout_ever_nonzero": heldout_ever_nonzero,
        "train_total": ce_sorted[0]["train_total"],
        "heldout_total": ce_sorted[0]["heldout_total"],
        "checkpoint_series_train": [
            (r["step"], r["train_pass_count"]) for r in ce_sorted
        ],
        "checkpoint_series_heldout": [
            (r["step"], r["heldout_pass_count"]) for r in ce_sorted
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds", type=str, default="1-16",
        help="comma-separated ints and/or 'a-b' ranges, e.g. '1-16' (default) "
        "or '1,2,3,9001'",
    )
    parser.add_argument(
        "--wall-budget-s", type=float, default=8400.0,
        help="total CPU wall budget for the whole sweep (default 8400s = "
        "2h20m, leaving margin under the 2.5h ceiling for the summary "
        "write); a seed is skipped (not started) once the running total "
        "plus the observed per-seed average would exceed this",
    )
    parser.add_argument(
        "--n-train-steps", type=int, default=N_TRAIN_STEPS,
        help="C-arm training steps per seed (default 1024, matching attempt "
        "19's --live run). Override to a small value for a fast smoke test "
        "of the orchestration logic only -- NOT for the real study.",
    )
    parser.add_argument(
        "--eval-checkpoint-interval", type=int, default=EVAL_CHECKPOINT_INTERVAL,
        help="checkpoint-eval cadence (default 64, matching attempt 19).",
    )
    args = parser.parse_args()

    seeds = _parse_seed_list(args.seeds)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    per_seed_results: list[dict] = []
    skipped_seeds: list[dict] = []
    study_t0 = time.time()
    per_seed_wall: list[float] = []

    for i, seed in enumerate(seeds):
        elapsed_so_far = time.time() - study_t0
        avg = statistics.mean(per_seed_wall) if per_seed_wall else 200.0
        if elapsed_so_far + avg > args.wall_budget_s:
            skipped_seeds.append({
                "seed": seed,
                "reason": (
                    f"wall budget guard: elapsed_so_far={elapsed_so_far:.1f}s + "
                    f"observed_avg_per_seed={avg:.1f}s would exceed "
                    f"--wall-budget-s={args.wall_budget_s}s"
                ),
            })
            print(f"[seed {seed}] SKIPPED (wall budget guard) -- {skipped_seeds[-1]['reason']}")
            continue

        print(f"[seed {seed}] ({i+1}/{len(seeds)}) running...")
        run = _run_one_seed(seed, args.n_train_steps, args.eval_checkpoint_interval)
        per_seed_wall.append(run["wall_s"])
        stats = _compute_stats(run["underlying_receipt"])
        print(
            f"[seed {seed}] done in {run['wall_s']:.1f}s: onset={stats['onset_step']} "
            f"peak_static={stats['peak_static']} final={stats['final_train']} "
            f"destruction={stats['destruction_magnitude']} "
            f"heldout_ever_nonzero={stats['heldout_ever_nonzero']}"
        )

        receipt = {
            "ticket": TICKET,
            "ts": _ts_iso(),
            "sha_convention": SHA_CONVENTION,
            "script": "scripts/ember_c14_seed_study.py",
            "seed": seed,
            "invocation_argv": run["argv"],
            "code_path": (
                "dry-run-class: src/ember/governance/scripts/ember_c14_owned_run.py --dry-run "
                "(CPU, TinyPolicyTransformer toy core) via run_rig() + full "
                "GatePredicate/check_guards() stack, same corpus generator "
                "and same corpus-v3 dynamic-resample / checkpoint-eval "
                "machinery attempt 19's --live run used -- see this "
                "script's module docstring for why this substrate expresses "
                "both the static and dynamic phases without protocol "
                "reduction."
            ),
            "underlying_receipt_path": run["underlying_receipt_path"],
            "underlying_clearance": run["underlying_receipt"].get("clearance"),
            "underlying_verdict": run["underlying_receipt"].get("verdict"),
            "stats": stats,
            "wall_s": run["wall_s"],
            "api_spend_usd": 0,
            "paid_api_surface_used": False,
        }
        out_path = OUT_DIR / f"seed-{seed}-{_ts_compact()}.json"
        out_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        per_seed_results.append(receipt)

    total_wall = time.time() - study_t0

    reached = [r["stats"] for r in per_seed_results if r["stats"]["onset_reached"]]
    onset_values = [r["onset_step"] for r in reached]
    destruction_values = [r["stats"]["destruction_magnitude"] for r in per_seed_results]
    destruction_values_overall_peak = [
        r["stats"]["destruction_magnitude_overall_peak"] for r in per_seed_results
    ]
    heldout_flags = {r["seed"]: r["stats"]["heldout_ever_nonzero"] for r in per_seed_results}
    heldout_ever_nonzero_any = any(heldout_flags.values())

    def _dist(values: list) -> dict:
        if not values:
            return {"n": 0, "values": [], "mean": None, "stdev": None, "min": None, "max": None}
        return {
            "n": len(values),
            "values": values,
            "mean": statistics.mean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
        }

    summary = {
        "ticket": TICKET,
        "ts": _ts_iso(),
        "sha_convention": SHA_CONVENTION,
        "script": "scripts/ember_c14_seed_study.py",
        "purpose": (
            "Pre-registered follow-up (issue #4 comment 8j) to C14 attempt "
            "19 (receipts/ember-c14-owned-run/live-20260703T154830Z.json, "
            "C14-LIVE-NOT-CLEARED): a seed-sensitivity study so single-run "
            "deltas in future attempts are interpretable against a real "
            "variance baseline, not read as if noise-free."
        ),
        "envelope": {
            "corpus_seed": CORPUS_SEED,
            "heldout_size": HELDOUT_SIZE,
            "corpus_v2": True,
            "k_exemplars": K_EXEMPLARS,
            "corpus_v3_resample": True,
            "corpus_v3_resample_start_step": CORPUS_V3_RESAMPLE_START_STEP,
            "n_train_steps": N_TRAIN_STEPS,
            "lr": LR,
            "temp_schedule": TEMP_SCHEDULE,
            "entropy_beta": ENTROPY_BETA,
            "degenerate_resample": True,
            "eval_checkpoint_interval": EVAL_CHECKPOINT_INTERVAL,
            "onset_threshold_fraction": ONSET_THRESHOLD_FRACTION,
            "note": (
                "Identical to attempt 19's live envelope_v1_7 block + "
                "corpus block, verbatim. The ONLY axis varied across runs "
                "in this study is --seed."
            ),
        },
        "code_path": (
            "dry-run-class (CPU, TinyPolicyTransformer toy core) via "
            "src/ember/governance/scripts/ember_c14_owned_run.py --dry-run, NOT the live-class "
            "real-owned-core path -- see honesty_note."
        ),
        "seeds_requested": seeds,
        "seeds_completed": [r["seed"] for r in per_seed_results],
        "seeds_skipped": skipped_seeds,
        "per_seed_receipts": [r["underlying_receipt_path"] for r in per_seed_results],
        "per_seed_summary": [
            {
                "seed": r["seed"],
                "onset_step": r["stats"]["onset_step"],
                "onset_reached": r["stats"]["onset_reached"],
                "peak_static": r["stats"]["peak_static"],
                "peak_overall": r["stats"]["peak_overall"],
                "final_train": r["stats"]["final_train"],
                "destruction_magnitude": r["stats"]["destruction_magnitude"],
                "destruction_magnitude_overall_peak": r["stats"]["destruction_magnitude_overall_peak"],
                "heldout_ever_nonzero": r["stats"]["heldout_ever_nonzero"],
                "wall_s": r["wall_s"],
            }
            for r in per_seed_results
        ],
        "acquisition_onset_distribution": {
            **_dist(onset_values),
            "n_seeds_total": len(per_seed_results),
            "n_never_reached": len(per_seed_results) - len(reached),
        },
        "destruction_magnitude_distribution_static_peak": _dist(destruction_values),
        "destruction_magnitude_distribution_overall_peak": _dist(destruction_values_overall_peak),
        "heldout_ever_nonzero_per_seed": heldout_flags,
        "heldout_ever_nonzero_any_seed": heldout_ever_nonzero_any,
        "wall_time_s_total": total_wall,
        "wall_budget_s": args.wall_budget_s,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "honesty_note": (
            "This study runs on the CPU dry-run/toy-core substrate, not the "
            "real ~368M-param owned core attempt 19 trained. "
            "src/ember/governance/scripts/ember_c14_owned_run.py's --dry-run path DOES express "
            "the FULL protocol including the dynamic corpus-v3 exemplar-"
            "resampling phase (--corpus-v3-resample/--corpus-v3-resample-"
            "start-step and --eval-checkpoint-interval are wired into "
            "cmd_dry_run identically to cmd_live -- same generate_corpus(), "
            "_make_corpus_v3_resample_fn(), _make_checkpoint_eval_callback(), "
            "run_rig() calls) so nothing about the PROTOCOL is reduced; the "
            "measurable half/measurable-only-partially caveat some CPU "
            "substrates would require does not apply here -- both the "
            "acquisition statistic and the destruction statistic are "
            "measured, not just acquisition. What IS NOT resolved by this "
            "study: whether the TinyPolicyTransformer toy core's seed-"
            "sensitivity magnitude transfers quantitatively to the real "
            "owned core (different parameter count, different loss "
            "landscape) -- this study bounds the SHAPE of seed variance "
            "(does onset/destruction vary a little or a lot; does heldout "
            "ever move) on the SAME code path attempt 19 ran, not the exact "
            "numeric magnitude a --live rerun would show."
        ),
    }

    summary_path = OUT_DIR / f"summary-{_ts_compact()}.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("=" * 60)
    print(f"SEED STUDY COMPLETE: {len(per_seed_results)}/{len(seeds)} seeds "
          f"({len(skipped_seeds)} skipped), total_wall={total_wall:.1f}s")
    print(f"onset distribution: {summary['acquisition_onset_distribution']}")
    print(f"destruction distribution (static peak): {summary['destruction_magnitude_distribution_static_peak']}")
    print(f"heldout_ever_nonzero_any_seed: {heldout_ever_nonzero_any}")
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
