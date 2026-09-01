# Class 2 (unwatched mandates) recon — 2026-07-04

**Scope note:** report-only recon per issue #35 "DISPATCH 2 of 3." No commits, no probe edits,
no CHK authorship (control-author != probe-author per the anti-gaming contract; CHK build-out is
a separate later dispatch). This document re-verifies the 07-03 audit's Class 2 findings against
today's tree and classifies what remains.

## The source-list gap (a finding in its own right)

The 07-03 audit (`docs/audit/goal-audit-20260703.md`) states "26 mandates fully UNWATCHED" but
that document is explicitly "the durable summary + cure ledger," not the full itemization — the
"full machine-readable findings" it refers to is an **operator-held audit transcript that was
never committed to either tree**. Searched both the historical execution tree and its goal-forge worktree for a
per-mandate watched/unwatched registry (a hoped-for cross-reference against
`docs/domains/governance/spec/conditions-v1.md` §4.3): none exists — §4.3 is a numeric-closure count authority (33
conditions), not a mandate-level ledger. `docs/spec/goalforge-debate-ledger.md` and the
`docs/audit/` directory were also checked; no fuller list surfaced.

**Consequence:** this recon can only re-verify what the summary names explicitly — one dominant
cluster (the audit's own estimate: "~12 rows") plus 5 individually-named holes. That accounts for
an estimated 17 of the 26; the identity of the remaining ~9 is not recoverable from any tracked
artifact today. **This gap is itself Class-2-shaped**: the 07-03 audit produced a headline count
with no durable, re-derivable itemization — a future re-audit hits the same wall unless the full
per-mandate list is persisted as a tracked artifact (or reconstructed fresh against GOAL.md's
full mandate text, which is a bigger job than this recon dispatch scopes). Flagging rather than
inventing 9 items to fill the count.

## Re-verified findings

### 1. Dominant hole — publication/research-focus enforcement layer (audit estimate: ~12 rows)

**07-03 status:** `check_publication_gate.py` (5 conjuncts) and the energy-law checker existed
but were manually-invoked only; the totality board tamper-hashed them without executing either,
so a regression in either checker would never turn a board row RED.

**TODAY'S status: CURED, board-wired, confirmed present.** Issue #38 landed the fix:
`scripts/ember_totality/test_c_enf.py` implements condition **C-ENF**, present in
`ember_totality_spec.py`'s `ORDER` list (line 149) and `FILENAME_ID` map (line 135). Verified by
reading the file directly: `test_c_enf.py` calls `enforcement_leg.run_enforcement_leg` over
`DEFAULT_CHECKERS` (both real checkers), GREEN iff every dual-source verdict is PASS — FAIL,
DISAGREEMENT, UNRESOLVABLE, startup-failure, or empty-registry all read RED, fail-closed. Issue
#38's own before/after sandbox evidence (32-id registry -> 33-id registry) shows C-ENF reading
RED *honestly* against the still-CLOSED publication gate (0/5 conjuncts) at the time it landed —
proving the wiring executes the real checker rather than rubber-stamping it.

**Classification:** N/A — already mechanized. **Blast radius if it later regressed:** HIGH (this
was the single largest hole; regressing it silently un-does 12 mandates' worth of coverage at
once) — worth a NEG-selftest audit at some point (does C-ENF's own test suite include a
deliberately-broken-checker case?), but that is verification work, not a new watcher, and is
outside this recon's scope.

### 2. §13-2 — "Milestones mirror the lattice" (§7 milestone lattice ↔ GitHub milestones)

**07-03 status:** unchecked.

**TODAY'S status: PARTIALLY ADDRESSED, same un-wired shape as the dominant hole before its own
cure.** `src/ember/governance/scripts/check_milestone_reconciliation.py` exists (landed 2026-07-01, predates the
audit — so the audit correctly flagged it as unwatched even though the checker itself already
existed) and produces a receipt (commit `462bbe7`: "milestone-reconciliation checker + receipt
(PASS 55/0/0/0)"). It is **not** in `ember_totality_spec.py`'s `ORDER`/`FILENAME_ID` — no `test_c_*.py`
file references it, confirmed by grep across both trees. A milestone/lattice divergence today
would not flip any board row.

**Classification: existing-probe extension (cheapest honest shape) — the exact precedent is
C-ENF itself.** `check_milestone_reconciliation.py` already does the real check and already
emits a receipt; the missing piece is a thin `test_c_*.py` status-probe wrapper (parse the
receipt, GREEN iff PASS, RED otherwise, fail-closed on missing/stale receipt) plus a registry
row — the identical shape issue #38 already proved out. This is the cheapest of the five
remaining holes to close.

**Blast radius:** MEDIUM. A silent lattice/milestone divergence misrepresents progress
externally (GitHub milestones are the public-facing tracking surface per §14 item 2) but does
not itself corrupt any measurement the board's numeric closure depends on.

### 3. §8 — Program-level disconfirmation triggers (EARNED-growth / H0-ceiling / B2-bootstrap hinges)

**07-03 status:** unchecked; "a trigger with no evaluator is prose" (GOAL.md's own words at the
clause).

**TODAY'S status: STILL FULLY UNWATCHED.** Searched both trees for `BOOTSTRAP_FAIL`,
disconfirmation-trigger evaluator code, and the escalation-object writer path
(`receipts/escalation/disconfirmation-<hinge>-<date>.json`): zero hits outside GOAL.md's own
prose. The clause names its intended evaluator (`docs/spec/experimentation-v1.md §6` standing
cadence) but that cadence is not implemented as code that actually counts consecutive
NOT-earned/BOOTSTRAP_FAIL attempts or writes the escalation object.

**Classification: new board CHK (not a probe extension) — this is a stateful counter across
RUNS, not a point-in-time check of one receipt.** It needs to tally consecutive attempt outcomes
per hinge across the receipt history and fire on the 2-of-2 / 3-of-3 thresholds GOAL.md
specifies; that is a genuinely new mechanism, not an extension of an existing one.

**Blast radius: HIGH.** This is the project's own designated "central conjecture false" failure
branch — GOAL.md is explicit that "nothing above distinguishes progressing-slowly from
central-conjecture-false" without it. A silent miss here means the system could continue
spending GPU-days past its own designated kill signal with no mechanical trip-wire at all.

### 4. §1 item 1 — Ledger admission integrity (adversarial-class self-satisfaction check)

**07-03 status:** "fake/self-report/threshold-corner episode has no probe."

**TODAY'S status: STILL FULLY UNWATCHED**, with one partial adjacency worth naming precisely so
it isn't mistaken for coverage: `bootstrap_threshold_sweep.py` under `scripts/proofs/` exercises
`BOOTSTRAP_PASS`'s threshold behavior, and `check_publication_gate.py` (now board-wired via
C-ENF, see #1 above) checks a different thing — the publication/research-focus conjunct, not
whether an actual admitted ledger entry evaded the four named adversary classes (self-report,
matched control, threshold corner, surface-memorizer). No probe inspects real admitted-episode
receipts for evidence one of those four classes was live and unhandled.

**Classification: new board CHK.** This needs to inspect actual admission events (not a synthetic
threshold sweep) against the four adversary-class criteria — closer in shape to C(-1)'s own
lane-14 hardening (verdict-linkage + silence-is-not-proof fixes, `test_c_neg1.py`) than to a
simple extension.

**Blast radius: HIGH.** This is the mechanism that is supposed to make §1's core admission
criterion (`BOOTSTRAP_PASS`) trustworthy against exactly the four failure modes the project
itself enumerates as its adversary. An unwatched admission path means the ledger's contents
(the thing every downstream condition ultimately measures against) could be adversarially
satisfied without any board signal.

### 5. §14 item 5 — Delegation-shape compliance (frontier-session grunt work vs. delegated builds)

**07-03 status:** no probe.

**TODAY'S status: STILL FULLY UNWATCHED**, and the clause itself is worded soft: "each session's
process-visibility receipt (§13) SHOULD note delegation shape... Violations are correctable
process defects — name them in STATE, do not hide them." This is a self-report convention by
design, not (today) a machine-checked one. No probe distinguishing delegation shape found in
either tree.

**Classification: NOT-MECHANIZABLE-WITHOUT-JUDGMENT, flag only — do not force.** Whether a given
session's work was "frontier doing serial grunt work a workflow's cheap stages could carry" is a
judgment call about task shape, not a receipt-schema property a script can evaluate today. A
weaker, genuinely mechanizable proxy exists (e.g., a receipt-schema rule that a process-visibility
receipt's `delegation_shape` field is PRESENT, not that its CONTENT is correct) — that would be a
receipt-schema rule closing the "silently hides" half of the clause (an omitted field is instantly
visible) while leaving the judgment half (was the shape actually right) correctly unmechanized.

**Blast radius: LOW-MEDIUM.** Violating this clause wastes frontier capacity rather than
corrupting a measurement; the clause's own text already treats violations as "correctable process
defects," i.e., self-limiting once named, not silent corruption of downstream results.

### 6. §1 (dated-claim clauses) — grounding-doc staleness re-sweep

**07-03 status:** unchecked ("re-sweep due dates").

**TODAY'S status: STILL FULLY UNWATCHED.** GOAL.md's §1 end-state clauses carry multiple "dated
claim" qualifiers (e.g., "the surviving, still-unclaimed kernel... as of the 2026-07-01 grounding
sweep (dated claim...)"). Searched both trees for a staleness/re-sweep mechanism keyed to these
dates: none found. (Note: `scratch/c-neg1-staleness-sandbox` exists but is unrelated — it is a
C(-1) paid-API-zero-cost fixture sandbox, confirmed by reading `test_c_neg1.py`'s docstring; it
does not touch dated-claim staleness.)

**Classification: receipt-schema rule (cheapest honest shape) with a NOT-MECHANIZABLE remainder.**
A rule that a "dated claim" citation must carry a re-sweep-by date and that the date's passage
without a fresh sweep receipt is itself flaggable is schema-checkable. Whether the underlying
literature claim is STILL true after a re-sweep is a judgment call (same shape as #5) —
mechanize the clock, flag the judgment.

**Blast radius: MEDIUM.** These are field-positioning claims (novelty/priority statements), not
measurements the board's completion math depends on — a stale claim misrepresents the project's
standing in the literature rather than corrupting an internal result, but it is exactly the kind
of thing an external reviewer would catch and the project itself would not.

## Ranked by blast radius of a silent violation (highest first)

1. **§8 disconfirmation triggers** — the designated kill-signal for the entire research program; silent miss = unbounded GPU-spend past a self-declared failure point.
2. **§1 item 1 ledger admission integrity** — the trust boundary under every downstream condition's input data.
3. **§13-2 milestone/lattice mirror** — external misrepresentation, cheapest to close (probe extension, C-ENF precedent).
4. **§1 dated-claim staleness** — external field-positioning misrepresentation; partially mechanizable via a clock rule.
5. **§14 delegation-shape** — internal capacity waste, self-limiting once named, partially mechanizable via a presence rule.

(The ~9 unidentified mandates from the original 26 cannot be ranked without their identity — see
the source-list gap above.)

## Summary table

| Mandate | 07-03 | Today | Classification if still open | Blast radius |
|---|---|---|---|---|
| Publication/energy-law enforcement (~12 mandates) | unwatched | **CURED** (C-ENF, board-wired) | — | (was HIGH) |
| §13-2 milestone/lattice mirror | unwatched | checker exists, not board-wired | existing-probe extension | MEDIUM |
| §8 disconfirmation triggers | unwatched | still unwatched | new board CHK (stateful counter) | HIGH |
| §1-1 ledger admission integrity | unwatched | still unwatched | new board CHK | HIGH |
| §14 delegation-shape | unwatched | still unwatched | NOT-MECHANIZABLE-WITHOUT-JUDGMENT (flag) + optional receipt-schema presence rule for the omission half | LOW-MEDIUM |
| §1 dated-claim staleness | unwatched | still unwatched | receipt-schema rule (clock) + NOT-MECHANIZABLE remainder (truth re-check) | MEDIUM |
| ~9 unidentified mandates | unwatched (per headline count) | **unknown — source list not recoverable from any tracked artifact** | N/A | unrankable |

IND-5 comprehension (named in the dispatch as a same-day landing, not part of the named-hole
list above but checked per the dispatch's instruction to note "now-watched-by-what"): confirmed
**already machine-checkable** via `test_c_ind.py` (condition C-IND, already board-wired) — GOAL.md
line 366 states the comprehension class is honestly split "[S]-checkable vs [A]-operator-attested,"
with only the [A] operator-attestation sub-piece open, correctly left as a flagged judgment call
rather than forced. This is the classification scheme's own worked example.
