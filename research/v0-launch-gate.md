# v0 launch gate — receipt-checkable preconditions for the owned-core pretrain dispatch

Frozen 2026-06-11 (~06:58). The owned-core v0 pretrain (NC2-own, c03 shape:
0.368B QAT, seq 1024, w1-governed 4090) is the June-22 critical path. This
gate turns "ready to launch" from prose into named receipts. The dispatch
shim refuses unless every G-row is green; no row may be waived except by
the user by name.

| Gate | Condition (receipt-checkable) | Status 2026-06-11 |
|---|---|---|
| G-corpus | v0 assembly receipt committed + receipt_check PASS; sha pinned (`a29d2e567f1853966cc72a4890eadc963164265e4f24a89cadea24d9ff5b80c2`); hard_bar <100GB | **GREEN** (eng-36, PR #149: 25.30 GB / 7.39 B heuristic tokens) |
| G-tokenizer | TOKENIZER-FREEZE-V0 production receipt: receipt_check PASS; pins the assembly receipt name+sha (fail-closed); reserved multimodal token band verified (NC2 v0 LOCK #1); REAL token counts emitted (`tokens_pending_tokenizer_freeze=false`) | PENDING (eng-42/#160; harness accepted by monitor 14576, production receipt not yet produced; merge shape = rebase onto current master, never branch-tree replacement) |
| G-config | v0 train config frozen as a file + selftest: c03-qat base (fp19-bench receipted 18,737.7 tok/s paced) + cheap survivor adoptions from the v2 multiplier table (Muon on 2D-hidden/AdamW elsewhere, torch.compile, sequence packing, WSD schedule, chunked/fused CE); FP8 and sparse-attention EXCLUDED for v0 (receipted-negative: 0.98 surviving multipliers); MTP aux heads per component contract | NOT STARTED (next build item after this gate doc) |
| G-governor | Governor block in the train config matches the fp19-bench receipted shape: VRAM fraction cap 0.8, margin floor 1.5 GiB, pace 0.05 s/step, budget math uses tok_s_paced; asserted at job start, fail-closed | TEMPLATE EXISTS (fp19-bench governor block); binds with G-config |
| G-world | fp-22 verify-floor world wired for eval cadence; fp-23 checkpoint-probe prereg attached so fp-24 (#139) fires on real v0 checkpoints; fp-21b (#132) + fp-20c (#146) fire on the first sampling round | SPEC EXISTS (fp-22 closed, fp-23 prereg frozen); wiring rides G-config |
| G-budget | Launch date L satisfies: days-remaining(L→Jun 22) ≥ 4.55 (receipted-unstacked envelope, fp19-bench) — i.e. **L ≤ Jun 17** unstacked, L ≤ Jun 19 if the conservative stack (3.12 d) is receipted locally first | GREEN today (11 days; tightens daily) |
| G-prereg | fp-26 round-3 prereg frozen citing the decision artifact + the monitor's MDE-wording resolution (mail 14582 ask #2) | PENDING (draft committed 4cf78fc; awaits monitor reply) |

## Dispatch rule

The v0 pretrain shim (`v0_pretrain.py`, to be built with G-config) embeds
this table as assertions: it loads each named receipt, receipt_checks it,
verifies the pins (assembly sha inside the tokenizer receipt; governor
block inside its own config), and refuses with the failing G-row named.
Same fail-closed grammar as fp25_surfaceb select mode.

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
