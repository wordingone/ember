<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->
# R1 (WARM-100) exit-evidence inventory — 20260805

Authority: `docs/domains/governance/spec/ember02-preregistration-v1.md` §3 "R1 — WARM-100" (exits R1-E1..E8,
kill criteria) + `docs/spec/ember02-preregistration-thresholds-v1.json` (T-01..T-09, F-11).
Subject run named by the task brief: `<custody>/r1-warm100-20260804` — `<custody>` is the
off-tree live-receipts custody root on the training host; absolute local paths never appear
in tracked bytes (checkpoint `artifacts/checkpoints/checkpoint-vertical-slice-seed-830001/`).

## Headline finding (read this before the table)

**The run at `r1-warm100-20260804` is not the R1 WARM-100 100-consecutive-step canary.**
It is a **`governed-vertical` structural/plumbing check**: `run_vertical_slice.py`'s own
docstring says this mode "routes one record through every specialist" — exactly one record
per expert (vision/audio/reasoning/tool), from a fixed 4-record `owned-four-domain-production-rung-v1`
shard. The checkpoint's own `data_cursor` proves it: `global_step: 4`, `record_index: 4`,
`tokens_seen: 36`. This is independently confirmed by a later same-day resume attempt
(`r2-resume-20260804`, argv `--resume-checkpoint .../r1-warm100-20260804/.../checkpoint-vertical-slice-seed-830001`)
which crashed immediately with `RuntimeError: production resume cursor has no remaining
authorized records` — i.e. all 4 authorized records were already consumed; there is no
"step 5" to advance to under this mode, ever, regardless of `--max-records`.

Worse: **`governed-vertical`'s CLI parser has no `--telemetry-path` flag at all.**
`run_governed_vertical()` never passes `telemetry_path`/`telemetry_run_id` into `run()`,
so `append_training_telemetry` is architecturally unreachable on this path — zero
per-step loss/grad-norm/tokens-were ever recorded, not just for this run, for *any*
governed-vertical run. The *only* CLI subcommand in `run_vertical_slice.py` that wires
`--telemetry-path`/`--telemetry-run-id` as required arguments is `specialist` (single-capability
continuation training, requires an existing checkpoint + parent/root manifests). `semantic`
(which *does* take `--steps`) also has no telemetry flags wired in `main()`.

And the certified/sanctioned launch surface makes this categorical for MODES, not incidental:
`certified_train_launch.py::_require_scope_subset` hard-fails unless
`authorized["allowed_modes"] == ["governed-vertical"]` exactly — so extending the
certificate's `allowed_modes` is not the cure (any other list refuses every launch); the
`specialist` route is instead authorized through the certificate's separate
`allowed_training_capabilities` key (#1430/#1454, live at this head, `--telemetry-path`
wiring included). The remaining R1 gap is that `governed-vertical` — the only allowed
mode — wires no telemetry, and `specialist` is single-capability continuation training off
an existing checkpoint, not a WARM-100 canary: a real R1-E1 still requires an engineering
task (wire telemetry through a 100+-step-capable canary mode), not a different flag on an
existing command.

Two other same-day run directories exist beyond the one named in the brief:

| Run root | argv mode | exit_code | What it actually is |
|---|---|---|---|
| `r1-warm100-20260802` | `governed-vertical --seed 830001 --max-records 200` | 1 (FAILED) | Prior failed attempt, zero artifacts produced |
| `r1-warm100-20260804` | same | 0 (COMPLETED) | The 4-record structural check; sole checkpoint on disk |
| `r1-chainproof-20260804` | — | — | Directory scaffolded (`artifacts/` exists), **zero files inside** — never executed |
| `r2-resume-20260804` | `governed-vertical ... --resume-checkpoint <r1-warm100-20260804 checkpoint>` | 1 (crashed) | Resume/restore attempt against the r1-warm100-20260804 checkpoint; crashed pre-restore on the "no remaining records" guard. Its `disk-budget-runner-receipt-child.log` proves `certified_train_launch.py` was upgraded **between** the r1-warm100-20260804 run and this one to start redirecting child stdout+stderr to a log file (the r1-warm100 runs' certified-launch receipts have no `child_log` key at all; r2-resume's does) — so even `governed-vertical`'s final `peak_memory_bytes` JSON line, printed to stdout, was never captured anywhere for the run this task is about. A fresh run today would capture it. |

## Verdict table (R1-E1..E8)

| Exit | Requirement (prereg §3, thresholds) | Evidence on disk | Verdict |
|---|---|---|---|
| **R1-E1** | T-01=100 consecutive steps; zero NaN/Inf in loss + grad-norm | None. Run reached global_step=4 of a fixed 4-record shard; no telemetry file exists anywhere (architecturally unreachable on this CLI path — see above) | **EVIDENCE-MISSING** (and NEEDS-EXECUTION is blocked on NEEDS-ENGINEERING, see plan) |
| **R1-E2** | mean loss, final T-03=10 steps < mean loss, first T-02=10 steps | Same — needs ≥20 steps of loss telemetry; none exist, only 4 steps ran | **EVIDENCE-MISSING** |
| **R1-E3** | checkpoint save/restore round trip: written, reloaded, cursor advances | **Write leg: real, verifiable now** — `checkpoint-manifest.json` (schema `ember-sparse-checkpoint-v5`) declares per-shard sha256 for all 7 shards (`shared-model.pt`, `optimizer-state.pt`, `replay-state.pt`, 4× `expert-*.pt`), cross-referenced against top-level `expert_checkpoint_sha256`/`shared_model_shard_sha256`/`optimizer_state_shard_sha256`. **Restore leg: attempted once, crashed before reaching restore code** (`r2-resume-20260804`, guard-level `RuntimeError`, not a restore failure) | **DERIVABLE-NOW (write-integrity sub-check only) / NOT-MET overall** — fail-closed: never reports E3 green from a write-only check |
| **R1-E4** | measured tokens/s, MFU, peak allocated/reserved VRAM, host utilization | No tokens/s or MFU anywhere. A **pre-run** VRAM preflight snapshot exists (`checkpoint-manifest.json → data_cursor.governor`: free_gb 24.1, total_gb 25.76, margin_gb 4.0, vram_fraction 0.85 cap) — this is `governor.preflight()`'s BEFORE-load snapshot, not peak-during-training. The real `torch.cuda.max_memory_allocated()` value is computed at end-of-run and printed to stdout as part of the final JSON line — never captured for this run (see child-log finding above). Whole-process wall-clock (97.4s) exists but mixes CUDA init + model construction + 4 records + checkpoint write, not steady-state throughput | **EVIDENCE-MISSING** for all 4 named quantities; disclosed non-substitute context only |
| **R1-E5** | first closed-boundary frontier receipt (§5.4) with `energy_boundary: DEGRADED_PROXY` | No frontier receipt anywhere. No energy-proxy sampling occurred (`scripts/energy_proxy_logger.py` exists but was not invoked). No frontier-receipt generator script exists anywhere in `scripts/` (repo-wide grep, zero hits). The §5.2 fixed-prior manifest **does** exist and is hash-checkable (`manifests/ember-restart-3b/fixed-prior-manifest-v1.json`) — one of §5.4's 8 field classes, not the receipt itself | **EVIDENCE-MISSING** |
| **R1-E6** | forecast-recalibration receipt: predicted vs measured step time/tok-s/joules/VRAM/loss | No forecast document exists anywhere (repo-wide grep for "forecast_recalibration" etc., zero hits) to recalibrate against, and no measured 100-step baseline exists to recalibrate with | **EVIDENCE-MISSING** |
| **R1-E7** | `sigma_seed(m)` per frozen probe metric, ≥ T-07=2 seed replicas at R1 scale | Only one seed (830001) has ever been run under any R1-labeled directory; zero seeds have usable step-level metric telemetry | **EVIDENCE-MISSING** (1 of 2 required seeds present, 0 with usable data) |
| **R1-E8** | A1 discriminating-check (liveness T-08, parity T-09/F-11) | No A1 (dense) arm run of any kind exists anywhere in `tools/ember-restart-3b` or the receipts tree (repo-wide grep for tier1/offload/Q-GaLore mechanisms, zero hits beyond the prereg text itself). The one checkpoint that exists is A3's sparse role-prior architecture (`ember-sparse-3b-v2`, 4 experts), not A1 | **EVIDENCE-MISSING** |

Net: **7 of 8 exits are pure EVIDENCE-MISSING; the 8th (E3) yields one genuine, scoped,
DERIVABLE-NOW sub-receipt (write-side hash integrity) but is NOT-MET overall.** This is the
receipted confirmation of the operator's standing finding — no true R1 rung exit currently
holds evidence, and the gap is partly a missing execution (run 100 steps) and partly a
missing capability (no CLI path today can both run ≥100 steps *and* record telemetry,
*and* be launched through the certified surface).

## Deliverables produced against this inventory

- `src/ember/governance/scripts/r1_exit_battery.py` — runs against real run-root bytes; for each of E1..E8 either
  computes a real verdict from present evidence or emits a fail-closed `EVIDENCE_MISSING`
  refusal naming exactly the missing bytes. `--selftest` covers both paths per exit with
  hermetic synthetic fixtures (namespaced `SELFTEST_FIXTURE_*`), zero GPU/checkpoint bytes
  required to run the tests.
- Receipts land under `receipts/ember-02-r1-exits/` in this worktree (never in the
  off-tree custody root), via `receipt_write.checked_write` (same atomic
  quarantine-on-invalid convention as `scripts/r2_cheap_probe_battery.py`).
- Needs-execution plan: see the battery's own `--exit e1..e8` refusal `result.needs` field
  (machine-readable) and the build task's final report (this file does not re-duplicate
  the argv list — it lives with the execution plan since some legs need engineering first,
  not just a command).
