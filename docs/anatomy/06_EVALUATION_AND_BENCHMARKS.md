# 06 — Evaluation and Benchmarks

## Operator-required benchmark set

`scripts/verify_authority_conservation.py` pins the benchmark obligation
directly (`REQUIRED_OPERATOR_BENCHMARKS`): SWE-Bench Pro, FrontierCode
Diamond, GDPval-AA, GDPpdf, Blueprint-Bench 2, AutomationBench,
OSWorld-Verified, Legal Agent Benchmark, Humanity's Last Exam, Terminal-Bench
2.1 — plus `ADDITIONAL_DIRECT_BENCHMARKS`: ARC-AGI 1, ARC-AGI 2, ARC-AGI 3.
`invalid-token` class `benchmark_obligation_erasure` guards against quietly
dropping any of these from governing text.

## The D3 native loop (external held-out evaluation)

Condition `C2` requires a candidate to run on an EXTERNAL held-out benchmark
with frozen rows, verified by hash and a freeze-before-candidate timestamp
check — the last board render's C2 row cites
`receipts/ember-d3-native-loop/d3-native-loop-20260708T221708Z.json`
(external `osunlp/D3-Gym`, 12 rows, frozen-rows sha256 verified on disk,
frozen strictly before the candidate run). `C3` requires an equal-budget
arm contract (`A<->C` arms sharing wall time, GPU/CPU, data access, attempt
budget, seed policy, and verifier path — all six dimensions declared, none
waived). `C6` requires a complete, reusable, rerun-reproduced recipe (commands
/ hashes / env / seeds / rerun_command present AND independently reproduced).

## The anti-gaming C1–C5 protocol (conditions-v1.md §4.2, NOT GOAL.md's C1-C5)

`docs/domains/governance/spec/conditions-v1.md` disambiguates three unrelated "C" numbering
schemes sharing this repo. This file's own §4.2 protocol — benchmark
discovery, held-out task, equal-budget, before-after, positive-delta — is the
anti-fraud checklist a performance CLAIM must pass; it runs on the totality
board as the plain-numbered rows `C1` through `C15` (distinct from GOAL.md's
own completion-bar C1–C5, which map loosely onto NAMED board rows like
`C-SCALE`/`C8` instead). `C1` (discovery receipts) was RED on the last
render for a hash-verification gap: candidate paths resolved off-tree under
the audited root, so in-tree hash-verify (mandatory since lane-14 hardening)
could not confirm them.

## Current gaps — honestly stated

Per the last board render: `C1` RED (hash-verify gap, not a discovery
absence), `C2`/`C3`/`C6` GREEN, `C4`/`C5` RED (`ARTIFACT REACHABILITY
failed` — a harness-interface placeholder blocks trusting pre/post neural
parameter hashes without an in-tree backing artifact), `C7` RED (no
`c7-selftest`/operator-ablation receipt on disk), `C8` RED (field-level
contribution-proof receipts present but none prove a falsifiable field-level
breakthrough per the CHK's conjunctive requirements). This doc maps the
protocol; it does not claim these conditions currently pass.
