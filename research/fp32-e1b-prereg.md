# fp-32 E1b prereg — batch-deviation loss-match protocol (FROZEN pre-shards)

Frozen 2026-06-11, BEFORE any v0 token shard exists, so no loss number can
shape the rule (same discipline as fp-26/fp-27: the decision rule precedes
the data). Carrier: #225. Companion: research/fp32-bottleneck-ledger.json
row R1; gain receipt receipts/fp32-step-econ-20260611T142831Z.json.

## Question

Does raising `throughput.batch` 4 → 16 (ladder to 24) preserve training
quality per token on REAL corpus data, so the receipted 1.345× throughput
gain can land as a registered deviation to `configs/v0-pretrain-config.json`?
Throughput alone never justifies the deviation — loss-per-token does.

## Protocol (executes after the #218 re-freeze + shard rerun, BEFORE --live)

Two governed segments per comparison, run by the eng-54 trainer in its
normal interlocked smoke mode (no --live, no checkpoint chain pollution —
segment dirs are temp, deleted after the receipt):

- **Identical in both legs:** shard prefix (first shards of the re-frozen
  set, same order), init seed, data order, seq 1024, frozen optimizer
  (Muon+AdamW, lr_muon 0.02 / lr_adamw 3e-4), WSD warmup applied
  identically by token fraction, QAT + MTP per config, governor (0.80
  fraction / 1.5 GiB margin / 0.05 s pace).
- **Only variable:** batch (4 vs candidate).
- **Token budget per leg:** 10,485,760 tokens (= 2,560 steps at B=4;
  640 at B=16; ~427 at B=24). ~9–10 min GPU per pair at measured rates.
- **Metric:** primary-objective CE component only (MTP aux excluded —
  aux weight is constant across legs but its head-init noise is not),
  mean over the FINAL 10% of each leg's token budget.

## Decision rule (frozen)

1. **PASS (deviation lands):** `ce_final10(B_cand) <= ce_final10(B4) * 1.02`
   at frozen lr. Deviation PR amends `throughput.batch` to the candidate,
   citing this prereg + both receipts. Ladder: test B=16 first; iff B=16
   PASSES, optionally test B=24 by the same rule (B=24 additionally
   requires free-VRAM ≥ 1.5 GiB margin to hold in the REAL trainer, which
   carries Muon states + MTP heads + loader buffers the bench did not).
2. **One scaled-lr retry (only if step 1 fails):** single retry of the
   candidate leg with lr_muon 0.04 / lr_adamw 6e-4 (linear scaling, batch
   4→16). Same rule vs the SAME B=4 baseline leg. PASS → deviation lands
   WITH the scaled lr recorded in the same deviation PR.
3. **FAIL (both):** deviation KILLED — negative receipt emitted, B=4
   stands, #225 closes on the negative receipt, the ledger row flips
   `killed`. No third configuration, no tolerance widening, no
   metric substitution (fp-22 no-third-retry class).

## Receipt shape (per pair)

`receipts/fp32-e1b-lossmatch-<ts>.json`: ticket FP32-E1B-LOSSMATCH,
shard_set sha pins, init seed, per-leg {batch, lr_muon, lr_adamw, steps,
tokens, ce_final10, wall_s, governor}, rule_verdict PASS / PASS-SCALED-LR /
FAIL, deviation_action, sha_convention. receipt_check-clean, committed.

### Contract tightening 2026-06-11 (Kai 14639 — rule UNCHANGED, binding hardened)

The fire-time gate is `scripts/fp32_e1b_gate.py`; the decision rule above
is untouched. The pair-receipt CONTRACT gains binding obligations:

1. Bare gate invocation (no `--pair`) exits NONZERO — staged is never
   readable as a pass.
2. `ticket == "FP32-E1B-LOSSMATCH"` and `seq == 1024` are enforced
   values.
3. Exact accounting per leg: `steps == ceil(budget/(B*seq))`,
   `tokens == steps*B*seq` (B=24 legitimately overshoots the 10,485,760
   budget by <1 step; "equal tokens" in the protocol above reads as
   "equal budget, minimal whole steps").
4. The scaled-lr leg is refused unless the frozen-lr candidate MISSED
   the bar (rule 2 is a retry, never an extra arm).
5. Shard provenance is bound, not trusted: the pair receipt names the
   post-#218 `TOKEN-SHARDS-V0` receipt (`shard_receipt` field);
   `shard_set_sha256` must equal the sha256 of that receipt's on-disk
   bytes; the gate requires it git-tracked, receipt_check-clean, and its
   `total_stream_tokens` equal to the LIVE tokenizer-freeze total via
   the fp-30 binder — a pair built on stale shards can never certify
   the deviation.

## What this prereg does NOT authorize

- No change to seq, optimizer family, QAT scheme, MTP weight, WSD shape,
  governor constants, or token budget — batch (and lr only via rule 2) is
  the entire deviation surface.
- No --live dispatch: E1b is pre-launch evidence inside the launch-gate
  window, not the run.
- No execution before the #218 deviations land and the shard receipt
  reproduces the re-frozen total (E1b on stale shards would bind the
  loss-match to a corpus that no longer exists).
