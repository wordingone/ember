# fp-21b prong-A disposition — trigger retired with record; question re-instantiated on the owned track (Closes #132)

## The frozen obligation (#132, scope pinned PR #197)

Prong-A re-execution: bars 1.5 / p<0.05 / seed 17 / 10k perms; predicate
`fp12_band.band_member` on ROUND-1 (borrowed Qwen) stats, never recomputed.
Trigger: "round-3 sampling receipt (next accumulation pass)" on the
fallback-(a) borrowed-world path.

## Why the trigger cannot fire in the goal horizon (receipts)

1. Round-3 borrowed-world never launched: fp-26 set round-3 shape under the
   transfer ceiling; the program pivoted to the owned 0.37B core (fp-27
   prereg frozen, v0-r1s1 LIVE — job 12c050e7, dispatched 2026-06-12).
2. The re-adopted goal (user /goal 2026-06-12, GOAL.md verbatim) binds the
   GPU track to the owned core through 06-22 (E2B-SURPASS MILESTONE). No
   borrowed-world accumulation pass exists on the critical path.

## Why the obligation cannot port unchanged

The frozen predicate is band membership computed on BORROWED-core round-1
stats ("never recomputed"). Owned-core sampling receipts are outside its
domain — executing the frozen protocol on them would recompute the predicate
on a different model, violating the freeze. Porting unchanged is therefore
not available; pretending otherwise would be goalpost motion.

## Disposition (no scope reduction — both halves carried)

- **DORMANT, NOT DEAD:** the frozen prong-A obligation stays valid exactly
  as pinned (#197). Revival trigger unchanged: any future borrowed-world
  round-3 sampling receipt fires it verbatim. This file is the record; the
  freeze is untouched.
- **QUESTION RE-INSTANTIATED on the live track:** the underlying fp question
  — does band membership predict downstream transfer — gets a fresh carrier
  on owned-core data: successor fp-34 preregisters band definition from
  OWNED-core round-1 stats (same bars: 1.5 / p<0.05 / 10k perms; fresh seed
  declared at freeze), firing on owned-core round-2 sampling receipts.
  Precedent for the carrier-fold pattern: fp-20c folded into #205.

## Receipt check

- fp-21 receipt chain intact: fp15-bandtransfer-20260611T033030Z
  (INCONCLUSIVE 1.341 < 1.5, p 0.104) remains the last executed verdict.
- Nothing deleted, no bar relaxed, no trigger weakened; one dormant pin +
  one live successor.
