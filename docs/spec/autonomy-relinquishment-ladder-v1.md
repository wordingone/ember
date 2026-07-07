# Autonomy-Relinquishment Ladder v1

## Contract

The autonomy-relinquishment ladder governs the transfer of the maintainer's levers to ember itself over five rungs (R1–R5), with R0 as the entry state.

### Safety Floor

This contract enforces three never-transfer capabilities:
- escalation set (money, cloud, new hardware, >100GB disk, leaves-PC)
- governor caps (resource limits on spawned processes)
- kill-discipline (PIDs only, never name patterns; kill-receipts required)

### Rung Definitions (Placeholder v1)

- R0: Initial state — no autonomy claimed
- R1: Scheduler provenance — board re-runs + audit cadence
- R2: Queue provenance — fire CPU-safe jobs
- R3: Launch token — fire governed GPU windows
- R4: Spec/execution provenance — choose next job, gate verdicts, spec authorship
- R5: Publication provenance — publication to public master

*Full spec in progress. This file establishes the contract reference for autonomy-ladder-state.json.*
