# Goal-organ floor-conformance audit

Issue #642 (refs #211). Audit only — this audit fixes nothing, and no clause verdict below was
softened to make a row read green.

- **Floor (the contract):** `docs/contracts/goal-mode-mechanism.md`, restated as the six frozen clauses
  enumerated in issue #642's body. That restatement is the audit's frozen scope; no clause here
  was invented, and no floor clause was dropped (see "Floor coverage" below).
- **Audited tree:** `wordingone/ember` at `ebae9f3aef1f497302c956ca534dc38f10e7e852`
  (`origin/master`, "docs(spec): freeze C8 F3 instrument list (#1323) (#1334)").
- **Evidence suite:** `src/ember/infrastructure/tools/ember-cli/src/core/goal-organ-floor-conformance-642.test.ts` —
  one `describe` block per clause, each test written so it would FAIL if its clause were violated.
- **Executed:** `cd tools/ember-cli/src && bun test core/goal-organ-floor-conformance-642.test.ts`
  → **23 pass, 1 skip, 0 fail, 90 expect() calls** (bun 1.3.12). The single skip is the
  clause-4 gap reproduction, described in row 4.
- **Provenance:** first drafted 2026-07-10 (the filename's date, and the path issue #663 already
  cites — kept unchanged so that reference does not rot). The draft was never committed; it was
  re-derived, corrected, and re-executed against current master on **2026-08-03**, which is the
  date every verdict below is true as of.

## Clause table

| # | Floor clause | Implementation site (file:line) | Evidence (test) | Verdict |
|---|---|---|---|---|
| 1 | Persistent objective **immutable to the executor** | `core/goal-store.ts:239` (`updateStatus` — signature carries no objective param), `core/goal-store.ts:222` (`editObjective`, the only mutator), `tools/goal-tools.ts:137` (`update_goal` schema, `.strict()`, no objective key), `tools/goal-tools.ts:219` (`GOAL_TOOLS` — the whole model surface) | CLAUSE 1, 4 tests | **CONFORMS** |
| 2 | **Status-only transitions** | `core/goal-store.ts:54` (`LEGAL_TRANSITIONS`), `core/goal-store.ts:71` (`isLegalTransition`), `tools/goal-tools.ts:134` (`MODEL_SETTABLE_STATUSES`) | CLAUSE 2, 3 tests (incl. exhaustive 6×6 = 36 pairs) | **CONFORMS** |
| 3 | **Event-driven continue-on-idle** with user preemption | `core/goal-continuation.ts:73` (preemption, checked before the semaphore and before any goal read), `core/goal-continuation-wiring.ts:59` (`createGoalContinuationPoke`, the self-chaining seam) | CLAUSE 3a (1), 3b (2) | **CONFORMS (preemption limb)** |
| 3′ | — same clause, "without polling" limb | `core/goal-continuation-wiring.ts:103,117` (`startGoalContinuationRearm`, 5 s `setInterval`), live at `screens/repl.ts:1303` | CLAUSE 3c, 5 tests | **DEVIATION-3c** (see below) |
| 4 | Completion audit must **PROVE completion** | `tools/goal-tools.ts:161` (`update_goal` `call` — no Complete branch at all), `core/goal-store.ts:239` (`updateStatus` — no evidence param), doctrine-only text at `core/goal-continuation-prompt.ts:71` | CLAUSE 4, 1 test, **committed `it.skip`** | **GAP — tracked by #663** |
| 5 | **Blocked** only after repeated consecutive impasse | `core/goal-store.ts:29` (`BLOCKED_TURNS_THRESHOLD = 3`), `core/goal-store.ts:283` (`noteBlocked`), `core/goal-store.ts:248` (resume resets the audit), `tools/goal-tools.ts:173` (the enforcing gate) | CLAUSE 5, 4 tests | **CONFORMS** |
| 6 | **Budget as soft-landing status** | `core/goal-continuation.ts:92-111` (`overBudget` → `BudgetLimited` + a wrap-up turn, never an abort), `core/goal-continuation-prompt.ts:97` (`renderBudgetWrapUpPrompt`), `core/goal-store.ts:65` (`BudgetLimited: ["Active", "Complete"]` — resumable, not terminal) | CLAUSE 6, 4 tests | **CONFORMS** |

Paths in the table are relative to `tools/ember-cli/src/`, matching the source files' own
citation convention.

## DEVIATION-3c — the organ now contains one scheduler

Clause 3 has two limbs: user input preempts, and idle → continue fires **without polling**. The
preemption limb conforms unconditionally. The no-polling limb does not, literally:

`startGoalContinuationRearm` (`core/goal-continuation-wiring.ts:103`) installs a five-second
`setInterval` and is wired into production at `screens/repl.ts:1303`, enabled by default. It was
added deliberately by PR #1158 for issue #279 — a continuation skipped by a transient
busy/queued-input race would otherwise never get another wakeup, because the only thing that pokes
the engine is the end of a turn that, by construction, is not going to happen.

This is recorded as a **deviation, not a clean pass**, because the floor's wording is "without
polling" and a timer is polling. It is recorded as a deviation **rather than a gap** because the
event-driven path remains the only thing that can actually start work, and the timer is structurally
subordinate — CLAUSE 3c pins that boundary with five executed tests: the scheduler is injectable
(no hidden global timer), a closed `shouldPoke` gate makes the timer inert rather than merely
delayed (so preemption survives the polling layer), the `EMBER_GOAL_CONTINUATION` kill switch
suppresses every tick, the cleanup clears the interval so no timer outlives its session, and a
non-finite or non-positive interval is refused outright so the deviation cannot be widened into a
busy loop.

The judgement call — deviation vs. gap — is the one place this audit exercises discretion, and it
is flagged here rather than buried so a reviewer can overrule it on the evidence.

## GAP row 4 — completion has no code-level proof gate

`update_goal(status: "Complete")` is accepted unconditionally whenever the transition is
state-machine-legal (`Active → Complete` and `BudgetLimited → Complete` both are,
`core/goal-store.ts:55,65`). There is no evidence parameter, no recorded-audit precondition, and no
verification of any kind. The "must PROVE completion" requirement lives entirely as doctrine text
injected into the model's context (`core/goal-continuation-prompt.ts:71`), so the clause is 100%
prompt-trust — while the structurally analogous **Blocked** clause got a real code-enforced counter
gate (`tools/goal-tools.ts:173`). That asymmetry is the finding.

Per the floor's own wording, an audit that merely fails to find remaining work is non-conforming by
definition; an organ that cannot tell whether the audit happened at all is a fortiori non-conforming.

Reproduction: un-skip the CLAUSE 4 test. Re-executed 2026-08-03 against
`ebae9f3aef1f497302c956ca534dc38f10e7e852` — the gap reproduces unchanged from #663's original
report:

```
290 |     // This is the assertion that FAILS today, proving the gap:
291 |     expect(data.ok).toBe(false);
                          ^
error: expect(received).toBe(expected)

Expected: false
Received: true
```

Tracked by **#663** (OPEN). No fix is attempted here; the audit is read + test only.

## Floor coverage — what the frozen six do and do not cover

The six clauses cover `docs/contracts/goal-mode-mechanism.md`'s "Selection and persistence" (clauses 1–2) and
"Continuation loop" (clauses 3–6). Two of the spec's four sections are outside the frozen scope and
are therefore **unaudited, not passed**:

- **"Artifact binding"** — every PR, experiment, configuration, receipt, and control artifact names
  `goal_id` and `next_executed_outcome`. This is a repo-wide artifact convention enforced by
  `tools/repo-guard.sh`, not a property of the ember-cli goal organ.
- **"Operator relationship"** — permission and autonomy modes explicit, configurable, revocable,
  behavior-tested. Spans the whole CLI permission system, far outside the goal organ's files.

Recording them as out-of-scope is deliberate: the alternative is a table that silently reads as
full-spec conformance when it is not.

## Deltas applied to the 2026-07-10 draft suite

The draft was treated as a draft, not as truth. Three corrections, all of which change what the
suite claims rather than what it tests:

1. **Retired the `GOAL.md §6` floor citation.** On current master, GOAL.md §6 is "Clean genesis and
   frozen-reference boundary" — unrelated to goal mode. `docs/contracts/goal-mode-mechanism.md` is the sole
   document floor. (The `spec §N` references scattered through the organ's own source comments are
   likewise stale against the current 52-line spec; that is a comment-accuracy issue in the organ,
   noted here, not fixed by this audit.)
2. **Added CLAUSE 3c** (5 tests). The organ evolved after the draft: PR #1158 introduced the re-arm
   timer. The draft's clause-3a test is scoped to the *engine* and remains true, but on its own it
   would now have reported a clean "no polling" pass for a production path that polls — a false
   all-clear produced by a passing test's silence.
3. **Named #663** in the clause-4 skip marker and comment, replacing the draft's "see report", and
   recorded the 2026-08-03 re-verification of the gap.

No test was weakened, and no assertion was removed.

## Issue #1348 — bounded-exception disposition (route a)

**ISSUE-1348-ROUTE-A-ACCEPTED**: the production five-second re-arm is accepted
as a bounded exception to clause 3's literal “without polling” limb. This is
not a full six-clause conformance or completion claim. The event-driven
continuation path remains the only path that can start work; the timer may
only retry the same `poke` after the live `featureEnabled` and `shouldPoke`
gates pass.

The permanent guard is the existing CLAUSE 3c evidence in
`goal-organ-floor-conformance-642.test.ts`: injectable scheduler, closed
`shouldPoke`/operator-preemption gate, `EMBER_GOAL_CONTINUATION` kill switch,
session cleanup, and finite positive interval validation. These guards are
the bounded-exception contract; a future change that bypasses any one of them
reopens #1348 rather than silently widening the timer.

This ruling is re-bound to current public master
`4b5868370c4472152313894ccf4a389e81fa3525`: `goal-continuation-wiring.ts`
blob `0b141c37e25ff7f439d170f64ea9fede38d91e7e`, `screens/repl.ts` blob
`cbed052374d1a2be2673a4fcf46f27ac473c739a`, and the current floor document
`docs/contracts/goal-mode-mechanism.md` blob `69484c1f6904630b611162c9dda7f6898d0b886a`.
The merged #1158 implementation and its closed #279 rationale remain
historical provenance for the exception, not a new authority.

The goal organ's source comments now cite the current unnumbered sections by
name: **Selection and persistence**, **Continuation loop**, **Artifact
binding**, and **Operator relationship**. Numeric `spec §4`, `spec §5`, and
`spec §7.1` references are not current section identifiers. The separate
completion-audit gap remains explicitly unresolved: **#663 remains OPEN**;
this route does not claim a completion proof, model, training, capability, or
full-spec result.
