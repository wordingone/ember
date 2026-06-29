# Ember Baseline Protocol V0

Status: LOCKING DRAFT. Not yet a runnable final protocol.

## First Active Baseline Task

Task ID: `B0-MODNANO-TRAINING-EFFICIENCY-RULER`

Purpose: use Modded-NanoGPT as the external training-efficiency ruler, while keeping the single-4090 Ember claim separate until its own 4090 ceiling and throughput evidence exist.

## Comparator

External comparator: Modded-NanoGPT / NanoGPT speedrun family.
Source: https://github.com/KellerJordan/modded-nanogpt

Required final source fields:

- repository URL;
- commit hash;
- exact record or README line naming validation target;
- hardware condition;
- token count;
- wall-clock;
- command or reproduction notes;
- access date.

## Ember Artifact Under Test

Initial candidate: current Ember v0 training stack or successor config selected by contract.

Required fields before run:

- repo URL and commit;
- clean/dirty tree state;
- config path and hash;
- data manifest and hash;
- seed policy;
- GPU model, VRAM, driver, CUDA/PyTorch stack;
- time/token/step budget;
- evaluator command;
- parser command;
- receipt output path.

## Verdict Logic

PASS:

- Ember beats the comparator or pre-registered Pareto threshold under locked rules;
- all preserved constraints hold;
- parser emits one PASS JSON receipt;
- external source pins are exact.

FAIL:

- run is valid but misses metric, budget, capability, or guardrail threshold.

INVALID-RUN:

- missing source pin, hidden compute, changed metric, missing receipt, parser failure, dirty-tree promotion without replay plan, line-ending verifier failure, or public/private baseline mismatch.

## Stage Order

1. Finalize external source pins.
2. Validate schemas and parser.
3. Validate line endings.
4. Run CPU/static checks.
5. Run short GPU throughput or memory smoke only if needed.
6. Write compute-spend packet for any long run.
7. Run governed Ember trial.
8. Parse one canonical verdict.
9. Write report and negative-results section.
10. Promote to `/baseline` in both repos.

## Current Verdict

NOT RUN. This protocol cannot be used for a PASS claim until source pins and contract thresholds are locked.
