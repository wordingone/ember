# Contract C1: Single-4090 >=1B Feasibility

Status: DRAFT.

## Uncheatable Form

Build or run Ember 1B+ active-parameter training artifact `X` that reaches capability target `Z` within days-scale threshold `T`, against hardware/scaling-law comparator `Y`, preserving one-RTX-4090 constraints `C`, under compute budget `B`, verified by protocol `V`, producing PASS, FAIL, or INVALID-RUN.

## Locked Defaults

- Days-scale default: <=14 calendar days.
- Hardware: one RTX 4090-class 24GB GPU.
- Parameter accounting: active trainable parameters must be >=1B; inactive sparse capacity and frozen parameters are reported separately.
- Compute estimate: `training_flops ~= 6 * active_parameters * trained_tokens`.

## Current Verdict

NOT RUN. Current inspected Ember v0 pretrain config is about 368M estimated parameters, so it cannot satisfy this >=1B contract.
