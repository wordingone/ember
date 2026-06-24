# Technique Registry — permanent, receipt-gated pretraining-optimization registry

User directive 2026-06-12 (chat, verbatim intent): this line of inquiry is
"exhaustively tested and stored permanently as compounding techniques for
further optimizing pretraining, as much as only physics will allow. It's a GPU
kernel level problem as much as a mathematical architecture of the network and
its pretraining requirements."

This file + `technique-registry.jsonl` are that permanent store. The
registry is machine-readable so the dispatch gate can ENFORCE it: a training
run admits only if its config consumes every ADOPT row or carries a receipted
exemption (fp-33 enforcement clause).

## The two axes (user framing)

1. **Kernel/systems — FLOPs delivery.** How close the step loop runs to the
   silicon ceiling: precision format, kernel fusion, launch overhead, memory
   hierarchy, dataloader overlap.
2. **Math/architecture — FLOPs efficiency.** How few delivered FLOPs the
   target quality needs: optimizer geometry, parametrization, attention shape,
   loss design, data curriculum, tokenization, distillation, verified
   self-curriculum.

A technique entry must name which axis it bends and the PHYSICS CEILING it
approaches — "as much as physics allows" is a measured distance, not rhetoric.

## Physics ceilings — RTX 4090 (sm89), the binding envelope

| Resource | Ceiling | Note |
|---|---|---|
| BF16 tensor-core, dense | ~165 TFLOP/s | realized MFU is the gap to close |
| FP8 tensor-core, dense | ~330 TFLOP/s | 2x bf16 — the E5/fp-33 prize |
| Memory bandwidth | ~1008 GB/s | roofline knee ≈164 FLOP/byte (bf16) |
| VRAM | 24 GB | sets max trainable params (E2 measures) |
| Power/thermal | governed (vram_frac 0.80, pacing) | governor rail, non-negotiable |

Every kernel-axis receipt reports achieved TFLOP/s and % of the relevant
ceiling. Every math-axis receipt reports tokens-to-target delta at fixed
quality.

## Exhaustive testing — the ember speedrun (proxy protocol)

Precedent: auto-nanogpt (Prime Intellect 2026-05) — agent loops running ~10k
experiments beat human records. Our local equivalent:

- **Frozen proxy target:** fixed val loss on a frozen shards-v0 slice at
  ~50-100M params, fixed seeds, fixed eval cadence. One number out:
  wall-clock-to-target (kernel axis) and tokens-to-target (math axis).
- **Loop:** governed agent experiment loop (Haiku/Sonnet workers, deterministic
  harness, jsonl receipts) mutates ONE technique per arm vs the current ADOPT
  stack. Composability tested pairwise for claimed top movers.
- **Transfer gate:** proxy wins are CANDIDATE only; ADOPT requires
  confirmation at 0.37B+ on a real segment (proxy-scale gains can vanish —
  µP-class parametrization mitigates but does not waive this).
- **Kill is data:** KILLed techniques stay in the registry with their receipt —
  the negative result is part of the permanent store.

## Registry schema (`technique-registry.jsonl`, append-only)

`{id, axis, claim, physics_ceiling, proxy_protocol, receipts[], measured_multiplier,
composes_with[], conflicts[], status: CANDIDATE|TESTED|ADOPT|KILL, source}`

Seed rows (status at mint, 2026-06-12): muon (ADOPT — in v0), wsd-schedule
(ADOPT — in v0), qat (ADOPT — in v0), governor-pacing (ADOPT — rail),
fp8-rowwise-torchao (CANDIDATE — E5 receipt decides), unit-scaling-muP
(CANDIDATE — µS 2502.05967), fused-muon-kernel (CANDIDATE — mine),
cuda-graph-step (CANDIDATE — cheapest, test first), fp8-recipe-infir2
(CANDIDATE — 2509.22536), distill-local-teacher (CANDIDATE), data-curation
(CANDIDATE — FineWeb-edu class), drafter-decode (CANDIDATE — floor-contract
row), kv-quant (CANDIDATE — AdaLLM sm89 precedent), verified-curriculum-loop
(CANDIDATE — STV 2605.30290 / R-Zero 2508.05004; fp-27b measures ours),
optimizer-state-quant (CANDIDATE — 2603.16731), muon-lowbit-qat-interaction
(WATCH-NEGATIVE — 2604.07888 reports no consistent gain; gate composability).

## Permanence + enforcement

- Lives in the ember repo, versioned; registry append-only; entries never
  deleted (KILL is a status, not a removal).
- Dispatch-gate hook reads the registry: run configs must consume ADOPT rows
  or carry `exemption_receipt`. No silent drift back to defaults.
- Every future fp/eng issue that tests a technique cites its registry id;
  every receipt path lands in the row. The codex compounds because the next
  run starts from the full ADOPT stack by construction.
