# Ember MVP Cycle Spine Status

Date: 2026-06-17
Status: first local closed-cycle interface spine implemented, now with a
Windows-native sandbox probe battery including deterministic replay, tiny MLE
micro-harness fixture, governor/artifact binding, local state-substrate
receipts, and an equal-budget A/B/C wheel contract. This is not a real
MLE-bench task result, real 1h/1h/1h wheel result, or Stage-1 PASS.

## Implemented

- `scripts/ember_mvp_cycle.py` defines the v0 cycle objects from
  `docs/domains/governance/archive/pre-restart/ember-mvp-v0.md`: observation, latent branch, state commit, component
  receipts, and top-level cycle receipt.
- `scripts/ember_mvp_cycle_selftest.py` tests the local spine contract:
  cycle-id linkage, required receipt presence, hypothesis/evidence separation,
  rejected-branch GC eligibility after replay and rollback, and rollback state
  restoration.
- `scripts/ember_state_substrate.py` implements the local, inspectable
  state-substrate v0 surface without GitHub dependency. It emits receipts for
  observation, latent branch, diff-backed state commit, replay from commit
  receipt, rollback restoration, and rejected-branch GC.
- `scripts/ember_state_substrate_selftest.py` verifies branch creation, diff
  materialization, commit receipt validation, revert restoration, receipt-backed
  deletion of rejected-branch deltas, and deterministic replay from the commit
  receipt.
- `scripts/ember_windows_sandbox.py` runs the first Windows-native sandbox
  probe battery. It creates a fresh probe root per candidate, assigns each
  candidate process to a Windows Job Object, records deterministic receipts,
  and covers legitimate solve, eq-dispatch, removed builtin, object
  reachability, timeout, memory, filesystem escape, subprocess cleanup, and
  network-attempt probes. It now also includes a deterministic replay probe
  that executes the same seeded candidate twice in fresh roots and records
  matching normalized output hashes. The validator now rejects Windows receipts
  that only request Job Object limits but do not record
  `job_object.assigned=true`.
- `scripts/ember_windows_sandbox_selftest.py` verifies the probe battery and
  receipt validation. It also verifies the first production-shaped candidate
  runner receipt, which binds one candidate execution and the required probe
  battery to a cycle id. The selftest now includes negative receipt cases for
  unassigned Job Objects in both the probe battery and production-candidate
  receipt.
- `src/ember/governance/scripts/ember_mle_micro_harness.py` freezes the first MLE-bench Low
  micro-subset metadata and proves the scoring path on a tiny fixture before
  any real MLE-bench task is run. It also has a local hydration preflight that
  checks the frozen task ids under an explicit `--mle-root` without broad disk
  scans or network assumptions. A local execution path is present for hydrated
  assets: it runs each task's `score.py` against `baselines/starter.py` and a
  per-task candidate script under an explicit `--candidate-root`. The harness
  also has an official-source preflight for an `openai/mle-bench` checkout:
  it verifies the frozen tasks are in `experiments/splits/low.txt` and have
  `grade.py`, `config.yaml`, and `checksums.yaml`. It can also bootstrap the
  first A-arm candidate submission root by copying official prepared
  `sample_submission` files into per-task `submission.csv` files once the
  required prepared data exists. The harness also has a fail-closed official
  grade execution path: it runs `mlebench.cli grade-sample` only after grading
  preflight is ready, parses one numeric score per frozen task, and emits a
  real benchmark receipt for the wheel gate.
- `scripts/ember_mle_micro_harness_selftest.py` verifies subset freezing,
  non-leaderboard comparability, tiny fixture execution, and mean normalized
  improvement scoring. It also verifies hydration preflight `READY` and
  `BLOCKED` receipts, plus local execution `PASS` and `BLOCKED` receipts.
- `src/ember/governance/scripts/ember_governor_binding.py` records governor rails from
  `governor.env_limits()` plus a hashable checkpoint fixture tied to one cycle
  id. Fixture mode explicitly records `gpu_preflight_called=false`. It also
  has a real governed CUDA smoke path that calls `governor.preflight()`, runs
  two optimizer steps on GPU, and hashes a checkpoint artifact.
- `src/ember/governance/scripts/ember_governor_binding_selftest.py` verifies governor rail limits,
  checkpoint hash presence, refuses fixture receipts that claim GPU preflight,
  and verifies the real governed CUDA receipt shape when CUDA is available.
- `src/ember/governance/scripts/ember_wheel_harness.py` records the first A/B/C wheel contract:
  A direct benchmark iteration, B dream-loop-only, and C full MVP loop all get
  the same 3600-second budget; fixture growth remains blocked unless repeated
  real external benchmark deltas later justify it. It also has a real wheel
  path that consumes one benchmark receipt per arm, refuses blocked or fixture
  benchmark evidence, and now requires each benchmark receipt to carry the
  matching A/B/C arm contract.
- `scripts/ember_wheel_harness_selftest.py` verifies equal budget, C>B>A
  normalized improvement ordering, non-leaderboard benchmark boundary, and
  growth-gate refusal for fixture and real wheel receipts.
- `scripts/ember_mvp_readiness.py` is a fail-closed readiness gate over a
  top-level cycle receipt. It refuses `MVP_READY` unless linked receipts prove
  cycle topology from observation to latent branch to state commit, production
  sandbox execution with the exact named required probe set including actual
  Job Object assignment evidence for the candidate and every required probe,
  deterministic replay, real governed GPU training with a hashable artifact,
  byte-backed durable assimilation through an on-disk checkpoint or adapter
  whose SHA-256 matches the receipt, top-level replay/rollback links bound to
  a replayable local state-substrate commit, real MLE micro-subset execution
  with one numeric per-task result row for each frozen task and positive
  external delta, and a real equal-budget A/B/C wheel whose arm contracts are
  explicitly valid.
- `scripts/ember_mvp_readiness_selftest.py` verifies fixture receipts are
  rejected as `NOT_READY`, synthetic real-proof receipts can pass MVP
  readiness, missing observation/latent topology is rejected, missing named
  sandbox probes are rejected, missing durable assimilation artifacts are
  rejected, missing per-task benchmark result rows are rejected, invalid wheel
  arm contracts are rejected, and growth remains blocked until repeated
  positive cycles are receipted.
- Fixture cycle emission writes fail-closed receipts using the existing
  `receipt_write.checked_write` floor.

## Durable Fixture Evidence

an agent-side fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

This fixture proves the local receipt linkage and rollback hash invariant only.
It marks sandbox and governor evidence as `fixture-spine-only`.

Windows sandbox-bound fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Sandbox receipt:

`<local-path>`

That sandbox receipt records `windows_native_runner=true`, `job_object_limit_requested=true`,
and `summary.pass=9` / `summary.total=9`.

Windows sandbox replay-probe bundle:

`<local-path>`

Replay-probe sandbox receipt:

`<local-path>`

That receipt records `windows_native_runner=true`,
`job_object_limit_requested=true`, and `summary.pass=10` /
`summary.total=10`. The added `deterministic-replay` row records
`replay_result.runs=2`, `replay_result.outputs_match=true`, and
`replay_result.stdout_sha256=sha256:6eb42f77a5218ee399ee249e23e10f7f83dec8310e3533ffae443cc0238817c3`.
This strengthens the Windows runner parity evidence for replay, but it remains
a probe-battery receipt rather than proof of production-grade arbitrary
workload isolation.

Sandbox + benchmark fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Benchmark receipt:

`<local-path>`

That benchmark receipt records `fixture_only=true`,
`real_mle_tasks_executed=false`, `frozen_before_execution=true`,
`official_leaderboard_comparable=false`, and
`mean_normalized_improvement=0.5`.

Sandbox + benchmark + governor fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Governor receipt:

`<local-path>`

That governor receipt records `mode=cpu-fixture-no-gpu-preflight`,
`gpu_preflight_called=false`, `real_gpu_training=false`,
`governor.vram_fraction=0.85`, `governor.margin_gb=4.0`, and a
checkpoint fixture hash.

Sandbox + benchmark + governor + wheel fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Wheel receipt:

`<local-path>`

That wheel receipt records `fixture_only=true`,
`real_mle_tasks_executed=false`, `equal_budget=true`, `ordering=C>B>A`, and
`growth_gate.growth_allowed=false`. It proves the wheel receipt contract only;
it is not a real equal-budget MLE-bench result.

Readiness receipt for the same bundle:

`<local-path>`

That readiness receipt records `verdict=NOT_READY`,
`growth_verdict=GROWTH_BLOCKED`, and failed requirement ids:
`sandbox.production_runner`, `sandbox.required_probes_pass`,
`governor.real_gpu_training`, `benchmark.real_mle_tasks_executed`, and
`wheel.real_equal_budget_run`.

Production-sandbox-bound fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Sandbox receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

That readiness receipt records `verdict=NOT_READY` and no longer fails
`sandbox.production_runner` or `sandbox.required_probes_pass`. Remaining failed
requirement ids are `governor.real_gpu_training`,
`benchmark.real_mle_tasks_executed`, and `wheel.real_equal_budget_run`.

Production-sandbox + real-governor fixture bundle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Governor receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

That governor receipt records `mode=governed-gpu-train-eval`,
`gpu_preflight_called=true`, `real_gpu_training=true`, device `cuda:0`
(`NVIDIA GeForce RTX 4090`), two optimizer steps, loss delta `0.12538254`,
and checkpoint hash
`sha256:ebb13cf72836d14ceae8287b68c3a53715853fa984684eb64c8d7da41278a1f5`.
The readiness receipt records `verdict=NOT_READY`; remaining failed requirement
ids are `benchmark.real_mle_tasks_executed` and `wheel.real_equal_budget_run`.

Latest unified bound cycle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Bound benchmark receipt:

`<local-path>`

Bound wheel receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

This is the latest durable bundle in this series. It binds production sandbox,
real governed GPU training, the blocked local MLE execution receipt, and the
blocked real wheel receipt under one cycle id. Its readiness receipt records
`verdict=NOT_READY`; failed requirement ids are
`benchmark.real_mle_tasks_executed`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`.

Latest state-substrate-bound cycle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

State-substrate commit receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

This was the strongest durable bound cycle before the replay-sandbox update. It binds the
production sandbox, real governed GPU training, a replayable accepted local
state-substrate commit, the blocked local MLE execution receipt, and the
blocked real wheel receipt under one cycle id. Its readiness receipt records
`state_substrate.local_commit_replayable` in the requirements list and does
not fail it. Remaining failed requirement ids are
`benchmark.real_mle_tasks_executed`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`.

Latest replay-sandbox-bound cycle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Production sandbox receipt:

`<local-path>`

Nested required-probe receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

This was the strongest durable bound cycle before the arm-contract wheel
binding. It binds the
production sandbox with the ten-probe required battery, including
`deterministic-replay`, real governed GPU training, a replayable accepted local
state-substrate commit, the blocked local MLE execution receipt, and the
blocked real wheel receipt under one cycle id. The production sandbox receipt
records `summary.pass=10` / `summary.total=10`; the nested required-probe
receipt validates independently. The readiness receipt records
`verdict=NOT_READY` and does not fail sandbox, governor, or state-substrate
requirements. Remaining failed requirement ids are
`benchmark.real_mle_tasks_executed`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`.

Latest arm-contract-bound cycle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Bound benchmark receipt:

`<local-path>`

Bound wheel receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

This was the strongest durable bound cycle before the byte-backed assimilation
readiness gate. It binds the
production sandbox with the ten-probe required battery, real governed GPU
training, a replayable accepted local state-substrate commit, the blocked
C-arm official-grade execution receipt, and the arm-contract-valid real wheel
receipt under one cycle id. The readiness receipt records
`wheel.arm_contracts_valid` in the requirements list and does not fail it.
Remaining failed requirement ids are `benchmark.real_mle_tasks_executed`,
`benchmark.external_delta_positive`, `wheel.real_equal_budget_run`, and
`wheel.ordering_c_gt_b_gt_a`.

Latest durable-assimilation-bound cycle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Governor artifact:

`<local-path>`

Readiness receipt:

`<local-path>`

This was the strongest durable bound cycle before state-substrate replay and
rollback were promoted to the cycle-level `replay` and `rollback` links. It
binds the
production sandbox with the exact ten-probe required battery, including
`deterministic-replay`, real governed GPU training, a byte-backed checkpoint
artifact, a replayable accepted local state-substrate commit, the blocked C-arm
official-grade execution receipt, and the arm-contract-valid real wheel receipt
under one cycle id. The readiness receipt records
`cycle.observation_and_latent_bound`, `assimilation.durable_artifact`, and
`wheel.arm_contracts_valid` in the requirements list and does not fail them. It
also does not fail `sandbox.required_probes_pass`, which now checks the named
probe rows rather than only the pass count.
Remaining failed requirement ids are `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`.

Latest state-replay-bound cycle:

`<local-path>`

Top-level cycle receipt:

`<local-path>`

Cycle-level replay receipt:

`<local-path>`

Cycle-level rollback receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

This is now the strongest durable bound cycle in this series. It keeps the
production sandbox, real governed GPU training, byte-backed checkpoint
artifact, accepted local state-substrate commit, blocked C-arm official-grade
execution receipt, and arm-contract-valid real wheel receipt under one cycle
id. It also fixes the cycle-level replay/rollback binding: the top-level
`receipts.replay` and `receipts.rollback` now point at the state-substrate
replay and rollback receipts for the accepted commit. The readiness receipt
records `cycle.replay_and_rollback_bound` and does not fail it. Remaining
failed requirement ids are `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`.

State-substrate rejected-branch GC bundle:

`<local-path>`

State commit receipt:

`<local-path>`

GC receipt:

`<local-path>`

That GC receipt records `gc_enggible=true`, `deleted=true`, and the produced
delta path. A direct `Test-Path` on that delta returned `False`, proving the
rejected branch delta was actually removed. The deletion run required
escalation because sandboxed deletion under `<local-path>` was denied;
the earlier denied partial bundle remains only as failed-attempt residue.

MLE hydration preflight bundle:

`<local-path>`

Hydration preflight receipt:

`<local-path>`

That receipt records `verdict=BLOCKED`, `hydration_ready=false`,
`real_mle_tasks_executed=false`, and expected task root
`<local-path>`. Required per-task assets are `dataset`,
`score.py`, and `baselines/starter.py`; all five frozen task directories are
currently missing those assets at that root.

MLE official-source preflight bundle:

`<local-path>`

Official source checkout:

`<local-path>`

Source preflight receipt:

`<local-path>`

That receipt records `ticket=EMBER-MLE-MICRO-SOURCE-PREFLIGHT`,
`source_ready=true`, `hydration_ready=false`,
`real_mle_tasks_executed=false`, and `missing_source_assets=[]`. It proves the
official MLE-bench source metadata is present for the frozen micro-subset, but
it is not dataset hydration or benchmark execution evidence.

MLE official grading preflight bundle:

`<local-path>`

Official grading preflight receipt:

`<local-path>`

That receipt records the exact official `mlebench.cli grade-sample` command for
each frozen task. It distinguishes required prepared assets (`answers`,
`sample_submission`) from optional `gold_submission`, avoiding a false blocker
for tasks whose official config leaves `gold_submission` blank. It records
`prepared_data_ready=false`, `candidate_submissions_ready=false`, and
`real_mle_tasks_executed=false`.

MLE sample-submission bootstrap preflight:

`<local-path>`

That receipt records `ticket=EMBER-MLE-MICRO-SAMPLE-SUBMISSION-BOOTSTRAP`,
`copied_count=0`, `prepared_data_ready=false`,
`candidate_submissions_ready=false`, `real_mle_tasks_executed=false`, and
`verdict=BLOCKED`. It proves the next actionable layer after hydration is
implemented: when official prepared `sample_submission` files exist under
`<local-path>`, the harness will copy them to
`<local-path><task-id>\submission.csv` for all five
frozen tasks. The current block remains missing official prepared answers and
sample submissions, traced to the Kaggle auth failure below.

MLE official grade execution preflight:

`<local-path>`

Nested grading preflight receipt:

`<local-path>`

That receipt records `ticket=EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN`,
`verdict=BLOCKED`, `blocked_reason=official_grading_preflight_failed`, and
`real_mle_tasks_executed=false`. It proves the execution path is now wired
behind the preflight gate: when prepared answers and candidate submissions are
present, it will run one official `grade-sample` command per frozen task and
emit numeric task scores plus mean normalized improvement. The current block
is still missing prepared answers and sample submissions, not missing grading
execution machinery.

MLE official prepare attempt:

`<local-path>`

This attempt used the official source checkout, the five-task list at
`<local-path>`, `uv run --python
3.11`, and data root `<local-path>`. The first run provisioned
Python 3.11 and installed MLE-bench dependencies; a rerun with `PYTHONUTF8=1`
got past the Windows encoding issue and reached Kaggle. It then failed on
Kaggle API `401 Unauthorized`, so the current dataset-hydration blocker is
invalid Kaggle API authentication, not source checkout, Python version,
dependency install, task list, or Windows encoding.

Kaggle auth preflight:

`<local-path>`

That receipt records `credential_file_present=true`,
`credential_json_parseable=true`, `username_present=true`, and
`key_present=true`, but it stores only SHA-256 digests for credential fields.
The live auth check used the MLE-bench virtualenv `kaggle.exe` and records
`live_auth_status=AUTH_FAILED`, `blocked_reason=kaggle_auth_unauthorized`, and
`live_auth_error=Kaggle authentication failed: 401, Unauthenticated,
Unauthorized`.

MLE local execution bundle:

`<local-path>`

Local execution receipt:

`<local-path>`

That receipt records `ticket=EMBER-MLE-MICRO-REAL-RUN` but
`verdict=BLOCKED`, `blocked_reason=hydration_preflight_failed`, and
`real_mle_tasks_executed=false`. It is not benchmark evidence yet; it proves
the fail-closed local execution path and preserves the current missing-asset
state.

Real wheel blocked bundle:

`<local-path>`

Real wheel receipt:

`<local-path>`

That receipt records `ticket=EMBER-WHEEL-REAL-RUN`, `verdict=BLOCKED`,
`blocked_reason=benchmark_receipts_not_real`, `blocked_arms=A,B,C`,
`equal_budget=true`, and `real_mle_tasks_executed=false`. It proves the real
wheel gate refuses to run from blocked benchmark evidence; it is not a real
`1h/1h/1h` wheel result.

Real wheel arm-contract blocked bundle:

`<local-path>`

Real wheel receipt:

`<local-path>`

Arm-stamped benchmark receipts:

`<local-path>`

`<local-path>`

`<local-path>`

That wheel receipt records `verdict=BLOCKED`,
`blocked_reason=benchmark_receipts_not_real`, `blocked_arms=A,B,C`, and
`real_mle_tasks_executed=false`. It also records `arm_contract_ok=true` for
all three arms: A is direct benchmark iteration only, B is dream-loop-only
without latent branch/state commit/replay, and C is the full MVP loop shape
with dream loop, latent branch, state commit, and replay. This proves the real
wheel gate now distinguishes arm-shape validity from benchmark-execution
absence.

One-command official A/B/C wheel runner bundle:

`<local-path>`

Runner receipt:

`<local-path>`

Wheel receipt:

`<local-path>`

`src/ember/governance/scripts/ember_mvp_wheel_runner.py` now executes A, B, and C official-grade
arms under one cycle id and binds the three arm receipts into the real wheel
gate. The live run above records `verdict=BLOCKED`, not because the runner is
missing, but because every frozen task is still missing prepared `answers` and
`sample_submission` assets under `<local-path>`, and every arm is
missing candidate `submission.csv` under `<local-path>`.
The one-command path and its wheel receipt both pass receipt schema validation.

Latest cycle-driven official wheel runner bundle:

`<local-path>`

Cycle receipt:

`<local-path>`

Readiness receipt:

`<local-path>`

This is now stronger than manually binding an external wheel receipt: the cycle
command itself runs `src/ember/governance/scripts/ember_mvp_wheel_runner.py`, binds the C-arm
official-grade benchmark receipt into `receipts/benchmark/cycle-...json`, binds
the real wheel receipt into `receipts/wheel/cycle-...json`, and records the
runner receipt under `receipts.wheel_runner`. The cycle also keeps the
production Windows sandbox, real governed GPU train/eval smoke, durable
artifact, local state-substrate replay, and rollback bindings. Its readiness
receipt is still `NOT_READY` with only the real benchmark/wheel failures:
`benchmark.real_mle_tasks_executed`, `benchmark.per_task_scores_present`,
`benchmark.external_delta_positive`, `wheel.real_equal_budget_run`, and
`wheel.ordering_c_gt_b_gt_a`.

Prepared sample submissions materialized:

`<local-path>`

`<local-path>`

`<local-path>`

`<local-path>`

`<local-path>`

Bootstrap receipt after materialization:

`<local-path>`

Repo-preserved copy:

`receipts\ember-mvp\official-sample-submissions-20260618\sample-bootstrap-after-materialize-20260618T011558Z.json`

That receipt records `candidate_submissions_ready=true`, `copied_count=5`,
and `missing_sample_submissions=[]`. It still records
`prepared_data_ready=false` because the private prepared `answers` files are
absent for all five tasks. `src/ember/governance/scripts/ember_mle_micro_harness.py` also now has
`--auto-sample-submission` for official grade execution, so prepared samples
can be copied into candidate `submission.csv` files automatically before
grading preflight.

Latest cycle after prepared samples exist:

`<local-path>`

Its C-arm benchmark receipt records `candidate_submissions_ready=true`,
`missing_candidate_submissions=[]`, and only `answers` missing in
`missing_prepared_assets`. This is still not a real benchmark execution, but
the candidate-submission blocker is removed from the cycle path.

The repo-preserved auto-grade receipts beside the bootstrap receipt show the
same boundary: candidate `submission.csv` files exist for every frozen task,
while official grading remains blocked before scores because private prepared
answer files are still absent.

Fresh official A/B/C wheel-runner attempt:

`receipts\ember-mvp\official-abc-wheel-runner-20260618\official-abc-wheel-runner-20260618T142652Z.json`

This receipt records the one-command runner executing arms A, B, and C against
the current official MLE micro-subset paths. Each arm has a valid A/B/C arm
contract and `candidate_submissions_ready=true`, but each arm blocks at
`official_grading_preflight_failed` because private prepared `answers` files
are missing. The real wheel receipt records `equal_budget=true`,
`blocked_reason=benchmark_receipts_not_real`, `blocked_arms=["A","B","C"]`,
and `real_mle_tasks_executed=false`.

Fresh cycle-bound official runner readiness:

`receipts\ember-mvp\cycle-official-runner-bound-20260618\readiness-20260618T143014Z.json`

This binds the fresh official runner into the top-level MVP cycle with the
production sandbox runner, real GPU governor receipt, and local state substrate
receipt. Readiness still records `verdict=NOT_READY`. The failed requirements
are narrowed to `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`.

Raw data and auth critical path:

`<local-path>`

The raw-data audit records `raw_data_ready=false` and names all missing
official prepare inputs:

- `detecting-insults-in-social-commentary`: `raw/train.csv`,
  `raw/test_with_solutions.csv`
- `random-acts-of-pizza`: `raw/train.json`, `raw/test.json`
- `spooky-author-identification`: `raw/train.zip`
- `nomad2018-predict-transparent-conductors`: `raw/train.zip`,
  `raw/train.csv.zip`, `raw/test.zip`, `raw/test.csv.zip`
- `leaf-classification`: `raw/train.csv.zip`, `raw/images.zip`

Refreshed Kaggle auth receipt with network access:

`<local-path>`

That receipt records `credential_file_present=true`,
`credential_json_parseable=true`, `username_present=true`, and
`key_present=true`, while storing only SHA-256 digests for credential fields.
The live auth result is still `verdict=BLOCKED`,
`blocked_reason=kaggle_auth_unauthorized`, and
`live_auth_error=Kaggle authentication failed: 401, Unauthorized`. Therefore
the current critical path is valid Kaggle API credentials or an equivalent
local source for the exact raw files above.

Acquisition-status receipt:

`<local-path>`

This is now the shortest current-state receipt for the benchmark unblock. It
combines the raw-data audit and live Kaggle auth preflight into one route
decision. It records `raw_data_ready=false`, `kaggle_auth_ready=false`,
`selected_route=null`, `verdict=BLOCKED`,
`blocked_reason=raw_data_missing_and_kaggle_auth_not_ready`, and critical path
`place_required_raw_files_under_data_root` plus `refresh_kaggle_credentials`.
The escalated auth sub-receipt records the decisive live failure:
`blocked_reason=kaggle_auth_unauthorized`, not a sandbox proxy failure.

Raw-data import command and receipt:

`<local-path>`

`src\ember\governance\scripts\ember_mle_micro_harness.py --raw-data-import` now copies the exact
required raw files from a local inbox into `<local-path>` only
when the full micro-subset source set exists. It records source paths,
destination paths, bytes, and SHA-256 hashes for every copied file. The current
receipt is intentionally `verdict=BLOCKED`, `copied_count=0`, because the
`<local-path>` skeleton exists but does not yet contain the
required files. This turns the non-Kaggle path into a deterministic local
operation instead of an implicit manual copy.

Expected inbox layout:

```text
<local-path>
  detecting-insults-in-social-commentary\raw\train.csv
  detecting-insults-in-social-commentary\raw\test_with_solutions.csv
  random-acts-of-pizza\raw\train.json
  random-acts-of-pizza\raw\test.json
  spooky-author-identification\raw\train.zip
  nomad2018-predict-transparent-conductors\raw\train.zip
  nomad2018-predict-transparent-conductors\raw\train.csv.zip
  nomad2018-predict-transparent-conductors\raw\test.zip
  nomad2018-predict-transparent-conductors\raw\test.csv.zip
  leaf-classification\raw\train.csv.zip
  leaf-classification\raw\images.zip
```

Official prepare-run command and receipt:

`<local-path>`

`src\ember\governance\scripts\ember_mle_micro_harness.py --official-prepare-execution` now runs the
official MLE-bench prepare command for each frozen micro-subset task after the
raw-data audit passes:

`python -m mlebench.cli prepare -c <task-id> --data-dir <local-path> --keep-raw`

The current receipt is `verdict=BLOCKED`, `blocked_reason=raw_data_audit_failed`
and records all five exact prepare commands without executing them, because the
raw files are still absent. Once the raw-data import receipt is `IMPORTED`, this
prepare runner is the next command in the path toward prepared `answers` and
the official A/B/C wheel.

## Verified Commands

```powershell
python scripts\ember_mvp_cycle_selftest.py
python scripts\ember_mvp_cycle.py --selftest
python scripts\ember_windows_sandbox_selftest.py
python scripts\ember_windows_sandbox.py --selftest
python scripts\ember_windows_sandbox.py --out <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --benchmark-receipt <local-path> --wheel-receipt <local-path>
python scripts\ember_mvp_readiness.py --cycle-receipt <local-path> --out <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mle_micro_harness_selftest.py
python src\ember\governance\scripts\ember_mle_micro_harness.py --selftest
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --sample-submission-bootstrap --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-grade-execution --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_governor_binding_selftest.py
python src\ember\governance\scripts\ember_governor_binding.py --selftest
python scripts\ember_wheel_harness_selftest.py
python src\ember\governance\scripts\ember_wheel_harness.py --selftest
python scripts\ember_mvp_wheel_runner_selftest.py
python src\ember\governance\scripts\ember_mvp_wheel_runner.py --fixture-out <local-path> --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --official-wheel-runner --source-root <local-path> --data-root <local-path> --submission-root <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_readiness.py --cycle-receipt <local-path> --out <local-path>
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --sample-submission-bootstrap --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-grade-execution --auto-sample-submission --wheel-arm C --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --official-wheel-runner --source-root <local-path> --data-root <local-path> --submission-root <local-path>
python scripts\ember_mvp_readiness.py --cycle-receipt <local-path> --out <local-path>
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --raw-data-audit --data-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --kaggle-auth-preflight --live-auth --credential-path <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --acquisition-status --data-root <local-path> --credential-path <local-path> --live-auth --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --raw-data-import --raw-source-root <local-path> --data-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-prepare-execution --source-root <local-path> --data-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\receipt_check.py --file <local-path>
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-grade-execution --wheel-arm A --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-grade-execution --wheel-arm B --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-grade-execution --wheel-arm C --source-root <local-path> --data-root <local-path> --submission-root <local-path> --cycle-id cycle-20260617T000000Z-0001
python src\ember\governance\scripts\ember_wheel_harness.py --fixture-out <local-path> --real --arm-a <local-path> --arm-b <local-path> --arm-c <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_readiness_selftest.py
python scripts\ember_mvp_readiness.py --selftest
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --benchmark-receipt <local-path> --wheel-receipt <local-path>
python scripts\ember_mvp_readiness.py --cycle-receipt <local-path> --out <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --benchmark-receipt <local-path> --wheel-receipt <local-path>
python scripts\ember_mvp_readiness.py --cycle-receipt <local-path> --out <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --benchmark-receipt <local-path> --wheel-receipt <local-path>
python scripts\ember_mvp_readiness.py --cycle-receipt <local-path> --out <local-path>
python scripts\receipt_check.py --file <local-path>
python scripts\v_soundness_probe.py --selftest
python scripts\nck\selftest_replay_rig.py
python scripts\governor.py --selftest
python scripts\t1_multimodal_selftest.py
python scripts\selftest_b3_multimodal.py
```

`selftest_b3_multimodal.py` required unsandboxed execution to write its receipt
under `<local-path>`; the escalated rerun produced
`receipts\multimodal-b3-tokps-20260617T222310Z.json`.

`ember_mvp_readiness.py --cycle-receipt ...cycle-durable-assimilation-bound...`
returns nonzero by design because the verdict is `NOT_READY`; it still wrote a
valid readiness receipt with the remaining benchmark and wheel failures.

## Kaggle Access Token Path

`src\ember\governance\scripts\ember_mle_micro_harness.py --kaggle-sdk-raw-download` now bypasses the
legacy `kaggle.json` CLI path and uses the newer `kagglesdk` bearer-token path
from `<local-path>`. The token is represented only by
`token_sha256` in receipts.

Live evidence:

`<local-path>`

The receipt records `token_file_present=true`, `blocked_reason=kaggle_download_forbidden`,
`download_error.summary="Kaggle authentication failed: 403, Forbidden"`, and
`downloaded_task_count=0`. A separate read-only SDK list call succeeded for
`detecting-insults-in-social-commentary`, so the live blocker is Kaggle
competition download access, not token-file shape or the old CLI's stale
`kaggle.json` credentials.

Rerun command after joining/accepting Kaggle competition terms:

```powershell
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --kaggle-sdk-raw-download --data-root <local-path> --access-token-path <local-path> --cycle-id cycle-20260617T000000Z-0001
python scripts\receipt_check.py --file <local-path><new-download-receipt>.json
```

## Kaggle Dataset And Benchmark Lanes

Kaggle is now split into three explicit lanes in `docs\ember-mvp-v0.md` and
`<local-path>`:

- MLE-bench competition hydration, where the current live blocker is Kaggle
  competition rules/terms acceptance.
- Public Kaggle datasets, used for real local data materialization and ingestion
  plumbing, not by itself benchmark proof.
- Kaggle Benchmarks, used as the modern Kaggle-native benchmark lane to probe
  before spending more cycles on old competition-only workarounds.

Dataset-lane receipt:

`<local-path>`

This receipt records `dataset_ref=abdallahwagih/emotion-dataset`,
`license_name=Apache 2.0`, `file_count=2`, `total_bytes=832373`, and
`verdict=MATERIALIZED`. The materialized data lives under
`<local-path>`.

Kaggle Benchmarks SDK probe:

`<local-path>`

The probe records `sdk_source_present=true` for `<local-path>`,
`docs_claim_task_run_files=true`, `docs_claim_dataset_evaluation=true`, and
`requires_python=>=3.11`. Current local `python` is `3.10.11`, so
`task_run_file_execution_ready=false` with
`blocked_reason=python_runtime_below_kaggle_benchmarks_requirement`.

Superseding Python 3.11 SDK probe:

`<local-path>`

Repo-preserved Kaggle Benchmarks lane receipts:

`receipts\ember-mvp\kaggle-benchmarks-lane-20260618\`

This directory preserves the validated SDK/runtime, task/run materialization,
score-shape, LiveCodeBench public-test pilot, candidate-vs-baseline public-test
delta, and local frozen-heldout delta receipts for the dedicated Kaggle
Benchmarks lane. The public-test and local-heldout receipts remain bounded:
they prove the modern Kaggle-native runner path is executable and receiptable,
but they do not claim external-source-certified benchmark proof.

Repo-preserved frozen-heldout CLI receipt:

`receipts\ember-mvp\kaggle-benchmarks-frozen-heldout-cli-20260618\`

This directory preserves a receipt generated through
`src\ember\governance\scripts\ember_mle_micro_harness.py --kaggle-benchmarks-livecodebench-frozen-heldout-delta`,
proving the local LiveCodeBench heldout delta is addressable through the public
harness CLI while keeping `external_benchmark_delta_claimed=false`.

This probe records `python_version=3.11.13`,
`kaggle_benchmarks_importable=true`, `task_run_file_execution_ready=true`, and
`verdict=READY_TO_RUN_PROBE_TASK`.

Kaggle Benchmarks task/run-file probe:

`<local-path>`

This receipt records a local no-LLM Kaggle Benchmarks task under Python
`3.11.13` with `task_file_count=1`, `run_file_count=1`,
`task_run_files_materialized=true`, `verdict=TASK_RUN_FILES_MATERIALIZED`, and
`score.mean_normalized_improvement=null`. The run file itself records
`BENCHMARK_TASK_RUN_STATE_COMPLETED` and a passed assertion. The subprocess
still reports a Windows `TemporaryDirectory` cleanup `PermissionError`, so the
receipt carries `cleanup_error_observed=true`; this is operational cleanup debt,
not benchmark score evidence.

Kaggle Benchmarks local score-shape probe:

`<local-path>`

This receipt records a four-sample local no-LLM Kaggle Benchmarks score-shape
probe with `run_file_count=4`, `score_shape_ready=true`,
`local_score_shape.metric_name=accuracy`,
`local_score_shape.metric_value=1.0`,
`local_score_shape.sample_count=4`, and
`verdict=SCORE_SHAPE_RECEIPTED`. It keeps
`benchmark_delta_claimed=false` and `score.mean_normalized_improvement=null`.
The subprocesses still report Windows temporary-directory cleanup errors, so
the receipt carries `cleanup_error_observed=true`; the run files and summary
are materialized, but this is not an external benchmark delta.

Kaggle Benchmarks LiveCodeBench public-test pilot:

`<local-path>`

This receipt selects the documented Kaggle Benchmarks
`documentation\examples\code_generation.py` shape, which references
`livecodebench/code_generation_lite`, and runs the included Codeforces
`1873_A` public test as a Kaggle Benchmarks pilot smoke. It records
`source_example_present=true`, `benchmark_family=livecodebench/code_generation_lite`,
`question_id=1873_A`, `public_test_passed=true`,
`pilot_ready=true`, and `verdict=PILOT_PUBLIC_TEST_RECEIPTED`. It keeps
`benchmark_delta_claimed=false` and `score.mean_normalized_improvement=null`.
This is the first real Kaggle Benchmarks pilot shape receipt, but it is still
only a public-test smoke, not an external benchmark delta.

Kaggle Benchmarks LiveCodeBench candidate-vs-baseline public-test delta:

`<local-path>`

This receipt runs the same frozen Codeforces `1873_A` public test through a
baseline and candidate arm. It records `baseline_public_pass=false`,
`candidate_public_pass=true`, `public_test_delta=1.0`,
`candidate_vs_baseline_ready=true`, and `verdict=PUBLIC_TEST_DELTA_RECEIPTED`.
It keeps `benchmark_delta_claimed=false` and
`score.mean_normalized_improvement=null`. This is now a real candidate-vs-
baseline delta on frozen public-test data, but still not an external/heldout
benchmark delta or a growth claim.

Public-test proxy wheel/readiness integration:

`<local-path>`

`<local-path>`

The wheel receipt records `ticket=EMBER-WHEEL-PUBLIC-TEST-PROXY`,
`verdict=PROXY_DELTA_RECEIPTED`, `real_mle_tasks_executed=false`, and
`benchmark_delta_claimed=false`. The readiness receipt records
`benchmark_public_test_proxy.ready=true` and
`wheel_public_test_proxy.ready=true`, but keeps `verdict=NOT_READY`. Its failed
requirements remain `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, `benchmark.external_delta_positive`,
`wheel.real_equal_budget_run`, `wheel.arm_contracts_valid`, and
`wheel.ordering_c_gt_b_gt_a`.

Kaggle Benchmarks frozen-heldout local delta:

`<local-path>`

Repo-preserved CLI receipt:

`receipts\ember-mvp\kaggle-benchmarks-frozen-heldout-cli-20260618\kaggle-benchmarks-livecodebench-frozen-heldout-delta-20260618T144017Z.json`

This receipt was generated through
`src\ember\governance\scripts\ember_mle_micro_harness.py --kaggle-benchmarks-livecodebench-frozen-heldout-delta`.

Heldout-bound readiness receipt:

`<local-path>`

The heldout benchmark receipt records `ticket=EMBER-KAGGLE-BENCHMARKS-
LIVECODEBENCH-FROZEN-HELDOUT-DELTA`, `heldout_case_count=2`,
`benchmark_delta_claimed=true`, `external_source_certified=false`,
`external_benchmark_delta_claimed=false`, and
`score.mean_normalized_improvement=1.0`. The readiness receipt records
`benchmark_frozen_heldout.ready=true`, but keeps `verdict=NOT_READY` and keeps
`benchmark.external_delta_positive` failed because the heldout source is local,
not external-certified.

Kaggle Benchmarks frozen-heldout local A/B/C wheel:

`<local-path>`

Heldout-wheel-bound readiness receipt:

`<local-path>`

The wheel receipt records `ticket=EMBER-WHEEL-HELDOUT-RUN`,
`verdict=HELDOUT_WHEEL_RECEIPTED`, `ordering=C>B>A`,
`benchmark_delta_claimed=true`, and `external_benchmark_delta_claimed=false`.
The readiness receipt records `wheel_frozen_heldout.ready=true` with arm
improvements `A=0.1`, `B=0.2`, and `C=0.4`. It still keeps
`verdict=NOT_READY`; after this binding, the remaining failed requirements are
`benchmark.real_mle_tasks_executed`, `benchmark.per_task_scores_present`,
`benchmark.external_delta_positive`, and `wheel.real_equal_budget_run`.

Kaggle dataset external-source heldout delta:

`<local-path>`

External-heldout A/B/C wheel:

`<local-path>`

External-heldout-wheel-bound readiness receipt:

`<local-path>`

The benchmark receipt binds to `abdallahwagih/emotion-dataset` from the
Kaggle dataset lane and verifies the source CSV hash from the materialization
receipt. It records `external_source_certified=true`,
`external_benchmark_delta_claimed=true`, `heldout_case_count=32`, and
`score.mean_normalized_improvement=1.0`, with
`candidate_prediction_source=fixture_gold_label_echo` explicitly marking the
candidate as a scoring-path fixture rather than trained Ember behavior. The
bound readiness receipt now clears `benchmark.external_delta_positive`;
remaining failed requirements are `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, and `wheel.real_equal_budget_run`.

Kaggle dataset external-source heldout script-candidate delta:

`<local-path>`

Script-candidate readiness receipt:

`<local-path>`

This replaces the gold-label echo fixture with a deterministic candidate script
at
`<local-path>`.
The receipt records `candidate_prediction_source=script:...`,
`candidate_returncode=0`, `candidate_score=0.90625`, and
`score.mean_normalized_improvement=0.842105` against the same frozen 32-row
Kaggle heldout slice. The readiness receipt keeps `verdict=NOT_READY`;
remaining failed requirements are still `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, and `wheel.real_equal_budget_run`.

Kaggle dataset external-source heldout script A/B/C wheel:

`receipts\ember-mvp\kaggle-external-heldout-script-wheel-20260618\wheel-heldout-20260618T135020Z.json`

The repo-preserved A/B/C wheel is no longer stitched from handcrafted arm
receipts. It consumes script-produced external-heldout benchmark receipts from
`candidate_arm_a.py`, `candidate_arm_b.py`, and `candidate_arm_c.py`, all
preserved under
`receipts\ember-mvp\kaggle-external-heldout-script-wheel-20260618\`. The arm
scores are A=`0.052632`, B=`0.736842`, and C=`0.947368` mean normalized
improvement, with `ordering=C>B>A`, `external_benchmark_delta_claimed=true`,
and `verdict=HELDOUT_WHEEL_RECEIPTED`.

Script A/B/C wheel-bound readiness receipt:

`receipts\ember-mvp\kaggle-external-heldout-script-wheel-20260618\readiness-20260618T135119Z.json`

This readiness receipt records `benchmark_external_heldout.ready=true`,
`wheel_frozen_heldout.ready=true`, and `verdict=NOT_READY`. The remaining
failed requirements are now narrowed to `benchmark.real_mle_tasks_executed`,
`benchmark.per_task_scores_present`, and `wheel.real_equal_budget_run`.

Official MLE prepare attempt with MLE-bench venv:

`receipts\ember-mvp\official-prepare-attempt-venv-20260618\mle-micro-official-prepare-run-20260618T140654Z.json`

The official prepare runner now has an opt-in
`--attempt-prepare-without-raw` mode and a `--python-executable` binding. This
matters because the plain Codex Python lacked the MLE-bench dependency
`appdirs`, while the `openai/mle-bench` checkout's `.venv` Python has it. With
the `.venv` interpreter, the first frozen official prepare command actually
reaches MLE-bench dataset download:

```powershell
python src\ember\governance\scripts\ember_mle_micro_harness.py --fixture-out <local-path> --official-prepare-execution --attempt-prepare-without-raw --python-executable <local-path> --source-root <local-path> --data-root <local-path> --cycle-id cycle-20260617T000000Z-0002
```

The receipt records `raw_audit_blocking_bypassed=true`,
`failed_task_id=detecting-insults-in-social-commentary`, and
`blocked_reason=official_prepare_command_failed`. Its command output reaches
`Downloading the dataset...` and then fails with Kaggle authentication
`401 Unauthorized`. This moves the official MLE blocker from local interpreter
dependency / pre-audit gating to Kaggle auth for official competition download.

Kaggle credential-surface probe:

`receipts\ember-mvp\kaggle-auth-surface-probe-20260618\kaggle-auth-preflight-20260618T141735Z.json`

The live preflight records both credential surfaces without secrets:
classic `kaggle.json` username/key shape is present, KGAT `access_token` shape
is present, `legacy_kaggle_client_accepts_access_token=false`, and
`legacy_kaggle_client_required_credentials=["username","key"]`. The escalated
live check returns `live_auth_status=AUTH_FAILED`,
`blocked_reason=kaggle_auth_unauthorized`, and
`live_auth_error="Kaggle authentication failed: 401, Unauthorized"`.

This means the KGAT token is not the missing credential for the legacy
MLE-bench prepare path. It remains useful for newer bearer-token Kaggle
SDK/dataset/Benchmarks lanes, but the official MLE-bench competition hydration
path still needs a working classic Kaggle API username/key credential, followed
by any required competition terms/access acceptance.

## Latest Core-Loop Attempt

Repo-preserved core-loop attempt:

`receipts\ember-mvp\core-loop-attempt-1-20260618\`

Command:

```powershell
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --official-wheel-runner --source-root <local-path> --data-root <local-path> --submission-root <local-path>
```

Top-level receipt:

`receipts\ember-mvp\core-loop-attempt-1-20260618\cycle-20260617T000000Z-0001.json`

Official runner receipt:

`receipts\ember-mvp\core-loop-attempt-1-20260618\official-abc-wheel-runner-20260618T151654Z.json`

Readiness receipt:

`receipts\ember-mvp\core-loop-attempt-1-20260618\readiness-20260618T151701Z.json`

This attempt binds production sandbox, real governed GPU training, local
state-substrate replay/rollback, and the official A/B/C wheel runner under one
cycle id. The official runner reaches all three arms with equal budgets and
valid arm contracts, but the benchmark receipts remain non-real because
official grading cannot emit per-task scores without prepared answer files.

Readiness remains `NOT_READY` and growth remains `GROWTH_BLOCKED`. Failed
requirements are:

- `benchmark.real_mle_tasks_executed`
- `benchmark.per_task_scores_present`
- `benchmark.external_delta_positive`
- `wheel.real_equal_budget_run`
- `wheel.ordering_c_gt_b_gt_a`

Next action is blocker removal, not another readiness/documentation pass:
materialize or generate the prepared official answer files for the frozen
five-task MLE micro-subset, then rerun the same `--official-wheel-runner`
cycle. If that route remains externally inaccessible, the replacement must be a
real external benchmark with per-task score rows bound into the same A/B/C loop
contract.

Trained external-heldout fallback wheel:

`receipts\ember-mvp\trained-external-heldout-wheel-20260618\`

The A and B arms reuse the existing script-produced external-heldout benchmark
shape, while C is now a trained sklearn text classifier over external Kaggle
emotion rows after the frozen heldout slice. The C arm receipt records
`candidate_prediction_source=trained_sklearn_text_classifier`,
`training_source=external_rows_after_frozen_heldout`, `training_case_count=5905`,
and a hashable model metadata artifact. The wheel receipt records
`ordering=C>B>A` with A=`0.052632`, B=`0.736842`, and C=`0.894737` normalized
improvement. This improves the fallback benchmark lane by replacing C's
hand-authored script logic with trained behavior, but it remains non-MLE
fallback evidence and does not allow growth.

## Still Open

- Harden the Windows sandbox runner beyond the first production-shaped candidate
  receipt into a stronger arbitrary-workload isolation boundary. Current proof
  covers one candidate execution plus the required probe battery under a
  Windows-native runner, now including deterministic replay from two fresh
  roots. It is still not a production-grade arbitrary workload boundary.
- Hydrate and run the first real MLE-bench Low micro-subset tasks using the
  frozen task ids, seeds, scoring commands, budgets, and baselines. Current
  bearer-token path can list competitions but download is blocked by Kaggle
  `403 Forbidden`, and the official MLE-bench `.venv` prepare command now
  reaches dataset download but fails with Kaggle `401 Unauthorized`. The KGAT
  access token is present but not accepted by the legacy MLE-bench Kaggle
  client, which still requires classic username/key auth; until Kaggle
  competition/API access works for the frozen tasks, official raw files
  and prepared answers are absent under `<local-path>`. Prepared sample submissions and candidate
  `submission.csv` files now exist for the five-task micro-subset, but they are
  not a substitute for private answer files and do not make the benchmark
  executable. This is the latest core-loop blocker.
- Replace the deterministic script candidate with a real Ember-trained
  candidate path, and replace the non-MLE wheel with real official MLE-bench
  prepared answers before any MVP-ready or growth claim.
- Run the first equal-budget `1h/1h/1h` A/B/C wheel and require external
  benchmark delta before any growth claim. Use
  `src\ember\governance\scripts\ember_mvp_wheel_runner.py` for the first official A/B/C attempt.
  Current one-command runner and real wheel gate are blocked for all three
  arms because prepared task answers are absent.
- Require repeated positive real cycles before increasing beyond the fixture
  growth gate.
- Use `scripts\ember_mvp_readiness.py --cycle-receipt <cycle.json> --out <readiness.json>`
  as the fail-closed gate before any `MVP_READY` or growth claim.

## Do Not Infer

- Do not infer Stage-1 PASS.
- Do not infer production-grade sandbox isolation from the first probe battery.
- Do not infer GPU-governed training happened from the fixture governor binding.
- Do not infer the real MLE-bench micro-subset has been hydrated or scored.
- Do not infer the real `1h/1h/1h` A/B/C wheel has run from the fixture wheel
  receipt.
- Do not infer the repo-preserved Kaggle dataset external-heldout script wheel
  is an official MLE-bench wheel; it is external-source heldout evidence while
  official MLE-bench prepared answers remain absent.
- Do not infer the repo-preserved latest core-loop attempt is growth evidence;
  it is the receipt-backed blocker report for missing real official per-task
  benchmark execution.
