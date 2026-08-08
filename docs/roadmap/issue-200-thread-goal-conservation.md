# Issue #200 thread-goal conservation

Status: `SUPERSEDED_CURRENT_EMBER_03`

## Ruling

Issue #200 began as a cron-shaped automation sketch and was later corrected to
the source-verified thread-goal primitive. The old cron tracker and its
historical pipe vocabulary must not become a second scheduler, operator loop,
daemon, or receipt authority.

The corrected thread-goal and scheduled-run acceptance remains current.
Canonical EMBER-03 has accepted the complete contract, so the historical issue
can close as superseded without claiming that its manual-seat gate, scheduled
runs, or R-ladder result already exists.

## Historical boundary

The original issue required an automation definition, append-only run memory,
operator-session receipts, terminal result events, and three consecutive
board-freshness runs, gated behind #197 and one completed manual operator
session.

The pinned revision correctly made a durable thread goal—not cron—the primary
primitive: immutable objective, optional budget, closed statuses, event-driven
continuation, queued-user preemption, anti-scope-shrink audits, and status-only
model updates. Those clauses remain the governing interpretation. Neither the
early sketch nor the revision is execution evidence.

## Lossless current-owner transfer

Canonical owner: [EMBER-03/#1117](https://github.com/wordingone/ember/issues/1117).

Accepted transfer: https://github.com/wordingone/ember/issues/1117#issuecomment-5222195698

The accepted transfer preserves:

1. one persisted per-thread goal with an immutable objective of at most 4,000
   characters, optional token budget, and a closed Active, Paused, Blocked,
   usage-limited, budget-limited, or Complete status;
2. serialized event-driven continuation only after an ordinary turn completes,
   only with no active turn and no queued user input, with queued input always
   preempting;
3. a same-id, still-Active durable-state reread immediately before the governed
   hidden continuation prompt starts an ordinary turn;
4. anti-scope-shrink doctrine, a requirement-by-requirement completion audit,
   and Blocked only after the same blocker persists for three goal turns;
5. explicit budget and usage status transitions plus a wrap-up steer, never a
   silent kill or a reason to mark Complete;
6. get/create/update goal tools with status-only update, preventing the model
   from rewriting the objective to make success easier;
7. R-ladder mapping from objectives and budgets to rung work, board conditions
   to completion evidence, and honest Blocked transitions to negative evidence;
8. only a thin scheduler that creates ordinary goals, with a closed definition
   for id, name, versioned in-repository prompt protocol, RFC5545 recurrence,
   dated Active/Paused state, model/effort, and working directory;
9. append-only run memory recording checks, exact receipts, verdict, and notify
   or dedup rationale; every automation run must end in a machine-minted
   terminal-result event using the same session evidence as a manual turn, and
   a wedged automation is a bug whose journal must record its terminal state;
10. the completed-manual-seat gate and terminal acceptance of three consecutive
    board-freshness runs with current source/executable identity, receipts,
    journal rows, and no new suite regression;
11. queued-user, interruption, malformed/foreign-state, deduplication,
    deletion, rollback, and negative evidence.

## Architecture and claim boundary

Current Ember Lab, the goal store and continuation engine, CLI session path,
activity journal, and receipt/custody spine remain the sole authority. This
ruling creates no cron daemon, second scheduler runtime, hidden operator,
parallel goal store, or parallel receipt family.

`NO_NEW_PARALLEL_AUTHORITY`

No completed manual operator session, scheduled run, R-rung result, GPU run,
training, checkpoint, capability, sufficient-pretraining, or milestone claim is
made.

## Rollback

Revert the conservation commit and reopen #200 if the accepted transfer is
removed, narrowed, or detached from the EMBER-03 certificate.
