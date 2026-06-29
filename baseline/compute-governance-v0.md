# Compute Governance V0

Status: ACTIVE DRAFT for baseline staging.

GPU and CPU time are evidence budget. A run is justified only when it can change a locked verdict or fill a contract field.

## Reuse First

Before reproducing any external baseline:

1. check whether the external project already publishes the exact metric, source version, hardware or compute condition, and command/config required by the active contract;
2. if yes, cite it and create a source-metadata receipt;
3. if no, choose the cheapest path that creates the missing field;
4. run local reproduction only if it changes a verdict, validates same-hardware normalization, validates parser compatibility, or supplies missing variance/seed coverage.

## Short Jobs

Default ceiling:

- CPU: <=10 minutes.
- GPU: <=10 minutes.

Allowed:

- imports, shapes, dtype, memory fit;
- parser and receipt validation;
- tiny evaluator wiring checks;
- throughput probes used only for sizing.

Forbidden:

- benchmark PASS claims;
- replacing a governed long run;
- collecting disconnected smoke receipts without a verdict.

## Long Jobs

Before any long job, write a compute-spend packet with:

- claim ID;
- uncheatable X/Y/Z/T/C/B/V contract;
- exact command/config/commit/data/checkpoint;
- why existing receipts and external citations are insufficient;
- expected new information;
- budget in wall-clock, GPU/CPU, VRAM/RAM, disk, and energy measurement method;
- checkpoint cadence, resume plan, logs, and receipt path;
- kill conditions;
- post-run parser command.

## Kill Conditions

Kill or redesign when:

- throughput makes the locked wall-clock impossible;
- memory fit violates preserved constraints;
- data/eval contamination appears;
- metric cannot reach the threshold under remaining budget;
- parser or receipt path fails;
- the run no longer answers the active contract.

## Current Long-Job Authorization

No long job is authorized by this staging packet.
