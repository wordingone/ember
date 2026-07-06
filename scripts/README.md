# scripts/

This file plus the root `README.md` (see its "Repository layout" table and
"How to reproduce the public checks" section) are the routing table for this
directory. A **prefix is an experiment family**, not a subsystem: most
filenames encode which numbered pipeline stage or ticket produced the script,
not what the script does architecturally. When in doubt, `grep` the ticket
prefix against `receipts/CLAIMS.md` / `receipts/INDEX.jsonl` (see
`scripts/build_claims_index.py`) to find the receipt(s) a given script
produced.

## Census (measured 2026-07-06)

- **506** files total under `scripts/`.
- **400** (79.1%) sit loose at the `scripts/` root, organized only by
  filename-prefix convention.
- **106** files live in 10 organized subdirectories (plus `__pycache__/`,
  a gitignored bytecode cache — not a real category).

Re-measure at any time:

```
find scripts -maxdepth 1 -type f | wc -l      # loose-at-root count
find scripts -type f | wc -l                  # total
```

## Canonical entry points

These are the scripts a new reader should run first — all already documented
in root `README.md` / `docs/REPRODUCIBILITY.md`; listed here so `scripts/`
is self-describing without a second hop:

| script | what it is |
|---|---|
| `receipt_check.py` | the schema-floor validator; `--selftest` (no deps), `--all` (report over every `receipts/*.json`), `--file <path>` |
| `corpus_acquire.py` / `corpus_acquire_selftest.py` | hydrates the v0 corpus from canonical sources / no-network selftest |
| `corpus_mix.py` / `corpus_mix_selftest.py` | mixes the hydrated corpus into training shards / no-deps selftest |
| `train_multimodal_v0.py` | the frozen v0 pretrain entry point (24 GB VRAM GPU + hydrated corpus required) |
| `ember_candidate_generator.py` (+ `_selftest.py`) | the A/B/C candidate-generation harness |
| `ember_d3_broader_multifamily_admission.py`, `ember_d3_broader_multifamily_loop.py`, `ember_d3_generalized_candidate_exec.py` (+ each `_selftest.py`) | the D3 native-loop stages |
| `ember_gate_*_selftest.py` (13 files) | one no-GPU selftest per readiness-gate surface (cleanroom inventory/legal boundary, full parity harness, receipt store, state persistence, hook runner, launch packaging, rollback/rewind, process supervision, tool dispatch permissions, function slash commands, communication/mailbox/computer-use, goal-mode parity adapter, backend coordinator agents) |
| `build_claims_index.py` | generates `receipts/INDEX.jsonl` + `receipts/CLAIMS.md` (this issue, #248 item 1) |

## Organized subdirectories

| dir | files | contents |
|---|---|---|
| `ember_totality/` | 47 | the condition-registry test suite — `test_c0.py`..`test_c15.py` etc. map 1:1 to the numbered conditions in `docs/spec/conditions-v1.md`, plus `ember_totality_spec.py` (the totality/tally spec) and `enforcement_leg_test.py` |
| `nck/` | 19 | NC-K, the resident event-driven harness kernel (`docs/nck-spec-v0.md`) — event loop, invariants, checkpoint/activation receipts, e2e proof, selftests. Frozen and sha256-pinned per script in `kernel-v1.0.manifest` |
| `w2_heldout/` | 10 | W2-stage held-out/decontamination batch building (`build_decontam_batch*.py`, `decon_scan_worker.py`, `launch_gate.py`) |
| `ember_phase5_c7/` | 9 | phase-5 work on condition C7 (self-growing operator): curriculum corpus, cycle runner, deletion test |
| `ember_phase3_c14/` | 6 | phase-3 work on condition C14: iGRPO trainer, floor-contract manifest, resident-arch spec, ABC-deleted harness |
| `ember_sovereign_retrieval/` | 4 | the sovereign-retrieval harness (IVF-PQ index, CPU smoke test) |
| `ember_phase4_c15/` | 3 | phase-4 work on condition C15: BitLinear unit, blocked emitter, comparison verifier |
| `growth_refutation/` | 3 | net2net-style growth-mechanism capacity tests |
| `accumulation_law/` | 2 | the P1 energy-law accumulation verification harness |
| `probes/` | 1 | canonical frozen probe sets (sha-stamped); documented in root `README.md` |

## Root-level loose-file prefix taxonomy

Counts below are alpha-prefix + numeric-suffix families among the 400 loose
root files, measured by grouping on the leading `[a-z]+[0-9]*` token. Where a
prefix's letter meaning isn't independently specified elsewhere in the repo,
it's described here only as "inferred from filenames/content" rather than
asserted as an authoritative name.

| prefix family | count | family meaning |
|---|---|---|
| `ember_*` | 112 | ember-cli / ember-system components not yet moved into a `ember_phaseN_*` subdir: gates, D3 loop pieces, bitnet core, field-level contribution proof, etc. |
| `fpN_*` | 81 | "FP" (falsification-probe) tickets, one file family per numbered FP ticket (FP3 through FP45 observed) — each is a one-shot experiment tied to a specific `fpNN-*` receipt/doc pair |
| `tN_*` / `tNc_*` | 52 | numbered pipeline-stage runners (T0 preflight through T5), each stage split into smoke/selftest/control-arm/quantization variants (inferred from content — no separate T-stage glossary found) |
| `cN_*` (all `c04_*`) | 22 | the C04 experiment family: design-bench sweeps, compile probes, dynamo patch, fp8 A/B, grid, budget, optimizer pick. **Not** the same namespace as the `C0`–`C15`/`C-SCALE` board conditions in `docs/spec/conditions-v1.md` — the collision is coincidental (ticket prefix vs. condition ID) |
| `wN_*` | 19 | numbered stage runners W1/W2/W4 (held-out floor evals, ingest, control-delta repair) — the organized subset of this family lives in `w2_heldout/` |
| `gN_*` (`g1_*`) | 12 | G1 paired-round runs: base/control/GRPO/MTP/SFT arms across r1w/r2w rounds |
| `density_*` | 10 | density-ablation A/B experiment (`density_ab_*`) + sensitivity probe |
| `rN_*` / `r2d_*` | 9 | round-stage claim executor, window minter, arm/power analysis, r2d control/GRPO/MTP/SFT variants |
| `corpus_*` | 7 | corpus acquisition/mixing entry points + selftests (see canonical entry points above) |
| `spN_*` | 4 | numbered "SP" spec/audit/battery selftests (sp2b gate, sp3 terminal audit, sp5 spec selftest, sp6 battery selftest) |
| everything else | 72 | 60+ singleton or 2-3-file families (`act_`, `arcade_`, `bits_`, `build_`, `calibrate_`/`calibration_`, `cbase_`, `ckpt_`, `corpus_acquire_*`, `cuda_`, `dgate_`, `governor_`, `gpu_`, `gsm8k_`, `kernel_`, `ledger_`, `loop_`, `power_`, `probe_`, `receipt_`, `registry_`, `selftest_`, `stageN_`, `test_`, `timeshare_`, `token(izer)_`, `train_`, `v_`/`vN_`, `verify_`, `wslN_`, `muon_`, ...) — mostly single-purpose utility or one-shot scripts named after their own ticket |

Regenerate this census with (adjust the regex if new prefix conventions are
added):

```
find scripts -maxdepth 1 -type f -name "*.py" | sed 's#scripts/##'
```
