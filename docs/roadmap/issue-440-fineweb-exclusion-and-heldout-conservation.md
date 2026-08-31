# Issue #440 fineweb exclusion and heldout conservation

Status: `SUPERSEDED_NOT_PLANNED` / `MOOTED_BY_CURRENT_FINEWEB_EXCLUSION` only
after this exact carrier receives an independent exact-head PASS, fresh
required checks are green, and the carrier merges. This document does not
claim a new corpus, heldout evaluation, training run, result, or capability.

## Historical subject retired

Issue #440 tracked the shards-v0 repair-vs-certify decision after shard-19 and
shard-25 probes. The exact v0 manifest and receipts remain historical truth;
v0 is never edited in place. Missing source bytes, regenerated shards, or a
different corpus cannot retroactively prove a historical result.

The latest #440 audit recommended holding the issue open only until physical
`fineweb_edu` exclusion landed, then closing it as mooted by exclusion. That
condition is now satisfied on current master by merged PR #1456, while the
frozen v2.1 future-heldout predicate and all historical evidence remain
preserved on their current owners.

## Accepted current owners

- OPEN EMBER-02/#1116 accepts the v2.1 heldout predicate and contamination
  science:
  https://github.com/wordingone/ember/issues/1116#issuecomment-5225327056
- OPEN corpus/source owner #648 accepts physical `fineweb_edu` exclusion and
  current corpus custody:
  https://github.com/wordingone/ember/issues/648#issuecomment-5225327377
- #440 bidirectional bridge:
  https://github.com/wordingone/ember/issues/440#issuecomment-5225328943

The owners are independent and complementary. Neither inherits evidence from
the other, and neither is closed by this carrier. #370 remains a separate
persistent-index mechanics contract and cannot supply #440 predicate evidence.

## Current physical exclusion truth

Historical shard 19 maps 100% to `fineweb_edu`: 1,666,837,789 tokens at stream
offsets [4,055,121,325, 5,723,508,974). Comment 5187250498 correctly recorded
the then-current source-blind gap. Merged PR #1456, reviewed head
`e535e9f9f8979301fe790d2613e5318490dc00c1`, merge
`75448febc5f469057ef18af189e3c80cf3ad07dc`, subsequently cured the default
consumer path.

Current `src/ember/governance/scripts/fineweb_exclusion.py` derives the exclusion from the
TOKEN-SHARDS-V0 and assembly receipts rather than filenames. The default
`PackedShardLoader` and launch gate skip overlapping windows and refuse
unidentified streams, damaged rulings, geometry mismatch, or edits that would
re-admit ruled-out sources.

The checked preflight receipt records:

- 6,814,324 unenforced windows;
- 5,185,038 enforced windows;
- 1,629,286 dropped windows;
- `zero_overlap_verified=true`; and
- 5,306,794,511 clean content tokens of 6,973,632,300 stream content tokens.

This cure is exact but bounded. Shards-v1 does not yet exist; tainted v0 bytes
remain on disk and are skipped at read time. Three historical direct-import
`w1_*` paths remain execution-denied rather than newly gated, and the disclosed
legacy initializer wrapper remains outside this result. A future shards-v1
must be newly named, deterministically rebuilt from admitted sources, bound to
complete lineage/bytes/hashes, and receipted before/after; v0 is never edited.

## Frozen v2.1 future-heldout contract

#1116 preserves `v2.1-exact50-droponly` for future heldout construction:

1. Recover documents by splitting the globally concatenated 26-shard stream
   on `SEPARATOR_ID=0`, never per shard. Exact separator checks are code
   1,867,710; fineweb 1,549,860; wiki 813,598; gutenberg 4,510; ledger 780;
   text-borne id-0 noise exactly 2 corpus-wide.
2. Eval documents are positionally disjoint from realized training set R;
   content novelty remains the load-bearing layer.
3. Scored continuation windows use exact-substring W=50 BPE tokens, stride 1,
   against R with self-exclusion. Admission requires zero collision.
4. A window is boilerplate-grade only when it collides in more than
   `K_source` distinct training documents. A scored row containing it is
   dropped, never admitted-and-forgiven; boilerplate alone does not reject an
   entire document.
5. `K_source(s)=max(10, round(f*N_docs(s)))`. f is frozen from one
   pre-model-output document-frequency histogram and may not be tuned against
   loss or admitted-row counts.
6. v2.1 is the sole primary future-heldout convention. Strict-13 survives only
   as a versioned conservative comparability bound.
7. The reference set is realized training tokens, or the full 6.98B-token
   pre-arm superset.
8. Execution is deterministic and L3-clean. Receipts bind predicate version,
   W, f, K table, source tallies, source/config/corpus/eval identity, reason
   taxonomy, dropped rows, negatives, interruption, rollback, and refusal.
9. The separate L4 rule remains: every training token has receipted lineage.
   The published ethnobotanical source implicated by shard 19 retains its
   unresolved license-clean/public-domain question.

Template or boilerplate recurrence is not silently reclassified as semantic
content leakage. The retired frequency-denominator predicate is not revived.

## Historical mechanism evidence

Shard-19 self-source arithmetic remains exact: `5,194,351 * 1025` lands at
global token 5,324,209,775 inside shard-19 range [5,100,273,664,
5,368,709,120). All 16,472 fwd_1m matches land in shard 19; shard-only replay
returns 16,468 = 16,472 - 4. They occupy a 124,277-token span, 0.046% of the
shard, in roughly 91 clusters. The mechanism is coherent template-structure
recurrence, not degenerate filler or verbatim document duplication. Mechanical
excision is near-tautological for a pool sourced from that shard.

Shard-25's trivial within-shard self-baseline is 1013 matches. Six of eight
sampled points have approximately zero excess; the hot excesses are +39,644
and +187 and reflect low-information scene-break formatting. The corpus-wide
0/192 tail-clean result and shard-local result are compatible because their
reference sets differ.

The scan lane's `pool_start * 1025` token convention and P1's
`held_out_window_start` retain an unresolved unit mismatch. No exact-position
claim may collapse those units. The W1 strict-13 clean control survives
unregraded; historical dirty-region claims remain suspect where match mass is
shard-concentrated.

## Negatives and rollback

- Missing, foreign, stale, partial, hash-drifted, source-blind, or unreceipted
  exclusion evidence fails closed.
- No old shard, absent byte, prose assertion, regenerated corpus, helper, or
  synthetic fixture becomes historical result evidence by citation.
- No v2.1 parameter may be tuned from model output or admitted-row counts.
- No dropped boilerplate row may be scored or forgiven.
- No index/cache result may inherit #440 predicate completion from #370.
- Receipt-first interruption preserves the last truthful manifest and keeps
  unadmitted tokens excluded.
- Rollback is ordinary Git revert of this carrier plus reopening #440 while
  the accepted owner comments and #1456 evidence remain append-only custody.

## Terminal falsifier and reopen rule

Current physical-exclusion completion is supported only while the default
loader/launch-gate receipt binding and zero-overlap arithmetic remain current.
Scientific v2.1 completion separately requires an executable exact-W50/
drop-only heldout builder with global boundary recovery, separator checks,
frozen f/K table, exact R identity, deterministic reason taxonomy, L4 custody,
and planted boundary/content/boilerplate/clean negatives.

This carrier permits `SUPERSEDED_NOT_PLANNED` because #440's stated
enforcement-before-close condition landed, not because v2.1 executed. Loss or
narrowing of the accepted owner links, #1456 enforcement truth or limitations,
historical shard-19/25 evidence, v2.1 predicate, L4/license question, no-v0-
rewrite rule, #370 separation, negative, rollback, or authority boundary
reopens #440.

## Credit and authority boundary

- `completion_credit=false`
- `scientific_execution_credit=false`
- `acquisition_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

Current EMBER-02/#1116 and corpus/source owner #648 remain the sole authorities
in their accepted scopes.

`NO_NEW_PARALLEL_AUTHORITY`
