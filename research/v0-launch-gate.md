# v0 launch gate — receipt-checkable preconditions for the owned-core pretrain dispatch

Frozen 2026-06-11 (~06:58). The owned-core v0 pretrain (NC2-own, c03 shape:
0.368B QAT, seq 1024, w1-governed 4090) is the June-22 critical path. This
gate turns "ready to launch" from prose into named receipts. The dispatch
shim refuses unless every G-row is green; no row may be waived except by
the user by name.

| Gate | Condition (receipt-checkable) | Status 2026-06-11 |
|---|---|---|
| G-corpus | v0 assembly receipt committed + receipt_check PASS; sha pinned (`a29d2e567f1853966cc72a4890eadc963164265e4f24a89cadea24d9ff5b80c2`); hard_bar <100GB | **GREEN** (eng-36, PR #149: 25.30 GB / 7.39 B heuristic tokens) |
| G-tokenizer | TOKENIZER-FREEZE-V0 production receipt: receipt_check PASS; pins the assembly receipt name+sha (fail-closed); reserved multimodal token band verified (NC2 v0 LOCK #1); REAL token counts emitted (`tokens_pending_tokenizer_freeze=false`) | **GREEN** (PR #164 merged 07:26Z: `tokenizer-freeze-20260611T060423Z` receipt_check PASS on the PR tree; assembly sha exact; committed tokenizer blob sha independently recomputed == receipt; band ids 0–7 fixed; real total 6.974B, code fraction 0.581; −5.3% vs compute-optimal ABSORBED at gate) |
| G-config | v0 train config frozen as a file + selftest: c03-qat base (fp19-bench receipted 18,737.7 tok/s paced) + cheap survivor adoptions from the v2 multiplier table (Muon on 2D-hidden/AdamW elsewhere, torch.compile, sequence packing, WSD schedule, chunked/fused CE); FP8 and sparse-attention EXCLUDED for v0 (receipted-negative: 0.98 surviving multipliers); MTP aux heads per component contract | **CONTRACT FROZEN** (`configs/v0-pretrain-config.json` + `scripts/v0_config_check.py`, selftest green; launch mode fail-closes on the null tokenizer receipt). Runner base = eng-33 `timeshare_pretrain.py` (checkpoint/resume/interlock exist); trainer extension against the contract = eng issue (Muon split-opt, WSD, chunked-CE, MTP heads, packed-corpus loader) |
| G-governor | Governor block in the train config matches the fp19-bench receipted shape: VRAM fraction cap 0.8, margin floor 1.5 GiB, pace 0.05 s/step, budget math uses tok_s_paced; asserted at job start, fail-closed | TEMPLATE EXISTS (fp19-bench governor block); binds with G-config |
| G-world | fp-22 verify-floor world wired for eval cadence; fp-23 checkpoint-probe prereg attached so fp-24 (#139) fires on real v0 checkpoints; fp-21b (#132) + fp-20c (#146) fire on the first sampling round | SPEC EXISTS (fp-22 closed, fp-23 prereg frozen); wiring rides G-config |
| G-budget | Launch date L satisfies: days-remaining(L→Jun 22) ≥ 4.55 (receipted-unstacked envelope, fp19-bench) — i.e. **L ≤ Jun 17** unstacked, L ≤ Jun 19 if the conservative stack (3.12 d) is receipted locally first | GREEN today (11 days; tightens daily) |
| G-prereg | fp-26 round-3 prereg frozen citing the decision artifact + the monitor's MDE-wording resolution (mail 14582 ask #2) | PENDING (draft committed 4cf78fc; awaits monitor reply) |

## Dispatch rule

The v0 pretrain shim (`scripts/v0_pretrain_launch_gate.py`, **BUILT**) embeds
this table as assertions: it loads each named receipt, receipt_checks it,
verifies the pins (assembly sha byte-true == the pin AND inside the
tokenizer receipt; governor block inside its own config via
`v0_config_check --launch`), computes the budget against the deadline, and
refuses with the failing G-row(s) named. Same fail-closed grammar as
fp25_surfaceb select mode. `--emit` writes a dated `v0-launch-gate-<ts>.json`
receipt (checked-write: the emitted receipt must itself pass receipt_check);
`--selftest` proves the fail-closed branches on mutated pins.

The #167 trainer (timeshare_pretrain.py extended against the frozen config)
is dispatched ONLY when this gate exits 0 (`V0_LAUNCH_GATE_GREEN`). As of
2026-06-11T07:54Z the gate is GREEN on 6/7 rows and refuses on exactly
**G-prereg** (no `fp26-prereg-*.json` frozen receipt yet) — receipt
`v0-launch-gate-20260611T075419Z.json`. Launch is one row from green: the
fp-26 round-3 prereg freeze (blocked on the monitor's MDE-wording reply,
mail 14582 ask #2) flips G-prereg and the gate goes launch-green.

## Sequence to green (critical path, in order)

1. Eli's #160 production freeze receipt (interlocked behind the #149 gate
   — already merged, so unblocked on his side) → G-tokenizer.
2. G-config build (Leo or gated subagent): config file + selftest +
   governor block; adopt survivors; receipt the local pace delta vs
   fp19-bench c03-qat (discharges the v2 table's conditional for the
   adopted subset).
3. fp-26 prereg freeze on the monitor's wording reply → G-prereg.
4. Dispatch v0 pretrain; fp-24 probes ride the checkpoints.

*Owner: Leo. Refs: #166 (fp-26), #139 (fp-24), #160 (tokenizer), task #49.*
