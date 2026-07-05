# Goal coverage matrix — 2026-07-05 (full-obligation census; operator question: "is EVERYTHING specced?")

Method: 5-leg parallel extraction over every binding surface (GOAL.md authority+clear-conditions;
totality board RED/AUDIT rows at 20260705T081932Z; claims-evidence-map + publication-gate
conjuncts; the pre-registration corpus follow-ons; issue-#35 audit debts + ember-completeness.md
self-reported gaps) → 74 obligation rows → joined against the issue tracker (118 issues), the
spec corpus, the receipt corpus, and in-flight lanes. Workflow run wf_32b7df77 (5 readers, 0
errors); join + rulings by the maintainer session. Truth date: 2026-07-05 ~11:3xZ.

## Verdict

**After this census: every extracted obligation maps to exactly one of** (a) a receipt (done),
(b) a frozen spec/issue, (c) an in-flight lane, or (d) one of the FIVE gap issues filed from
this census — #139 (C-E2B gap-closing re-run), #140 (C-SURFACE2 live re-capture), #141 (C15
BitNet trigger registration), #142 (resident-gate floor_contract_manifest), #143
(completeness-ledger verify-or-mint sweep). Zero obligations remain unmapped — with the honest
caveats in §Caveats.

## Coverage by surface (summary)

| Surface | Rows | Covered pre-census | Gaps filed |
|---|---|---|---|
| Publication conjuncts + claims rows (18/19/21) | 6 | 6 — #123/#124/#125/#3, queue #53 | 0 |
| Pre-registration follow-ons (w2/c8/e2b/p1-sweep/rung2) | 13 | 12 — #115(run live)/#113/#108/#123/#126/#29 | #139 (e2b terminal re-run) |
| Board RED/AUDIT rows | 7 | 5 — annex landed (C-1), #133 (C0), #20/#98/#107 (C11), #29/#62 (C-SCALE), C-TALLY rides board re-run | #139 (C-E2B), #140 (C-SURFACE2) |
| GOAL.md clear conditions §1–§15 + authority clauses | 35 | 33 — §1/§2 receipted GREEN; §3–§6 per-run machinery (C2/C3 receipted); §7/§12/§13 board-GREEN receipts; §8=#123; §9/§10 process-invariants (C9/C10); §11=#20/#98/#107; §14a–f=#41/#37/#3/#125; debt-scan=C10; code-vs-docs=C9 | #141 (§15 BitNet), #142 (floor manifest) |
| Audit debts (#35 items) + completeness rows | 13 | 6 — #35 umbrella carries its own items | #143 (7 completeness rows) |

## Standing actions that are NOT specs (riding the loop)

- Board re-run post-annex → confirms C(-1) flip + regenerates C-TALLY (next REVIEW tick).
- Shared-checkout branch hygiene: B:/M/ember-goalforge sits on a stale lane branch; return to
  master at next landing.
- This matrix lands via PR (docs/, per the evidence-artifact location convention).

## Caveats (honest limits of this census)

1. Extraction is reader-grade: 5 haiku readers quoting binding docs. The GOAL.md leg's
   status_hints were spot-checked against the fresh board (e.g. §12/§13 read RED in stale doc
   prose but their board conditions are GREEN on executed receipts — board wins).
2. "Covered by umbrella" (#35, #29, #53) means the obligation is INSIDE a tracked issue's scope,
   not that a dedicated lane exists for it today.
3. A census is a snapshot: the census step in every REVIEW tick (work-loop STEP 0) is the
   standing mechanism that keeps this matrix from rotting — deltas surface per-tick, not
   per-crisis.

## Gap-issue index (filed 2026-07-05 from this census)

- #139 — C-E2B gap-closing re-run: scorer hook-in (#136 module), tie diagnosis, surpass attempt.
- #140 — C-SURFACE2 live-telemetry re-capture (replay provenance is the named defect).
- #141 — C15 tiny BitNet comparison: trigger-gated registration (fires on first neural C14 PASS).
- #142 — resident-gate floor_contract_manifest (machine-checkable, keyed by every floor row).
- #143 — completeness-ledger ABSENT rows: verify-or-mint sweep (7 rows).
