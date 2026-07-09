# Goal-mode mechanism — spec floor for ember-cli /goal (issue #211)

Answers: how the /goal organ works, exactly. Edited by: maintainer via PR.
Invalidated by: a receipted better mechanism superseding a clause.

Provenance: source-verified study of the field's strongest goal-mode implementation
(openai/codex @ rust-v0.135.0 — core/src/goals.rs, core/templates/goals/*,
core/src/context/goal_context.rs, tools/handlers/goal_spec.rs, tui thread-goal actions,
protocol status enum). ember-cli ports this 1:1, then improves. Nothing below is aspirational;
every clause is how the studied implementation actually behaves, adapted to ember terms.

## 1. Data model

Goal persisted in the session state store: goal_id, objective (max 4000 chars), status,
optional token_budget, system-tallied token usage + elapsed time. Status machine:
Active | Paused | Blocked | UsageLimited | BudgetLimited | Complete. Goals require a
persistent session; ephemeral sessions refuse with a clear message.

## 2. Entry points

- /goal command: set/view/edit the objective; available DURING a running task; mid-flight
  edits inject an objective-updated steering prompt so the model re-anchors.
- Model-side tools: get_goal (read incl. budgets/usage), create_goal (fails if one exists;
  "only when explicitly requested — never inferred from ordinary tasks"), update_goal
  (STATUS ONLY — the model can never rewrite the objective; accounting is system-managed).
  Objective immutability at the state layer is what makes scope-reduction structurally
  impossible rather than merely forbidden.

## 3. The autonomy loop — event-driven, no scheduler

Every task/turn completion pokes maybe-continue-if-idle:
1. Acquire a continuation semaphore (structurally no double-fire).
2. Eligibility: feature on; not plan mode; no active turn; NO QUEUED USER INPUT — the user
   always preempts; continuation fires only into genuine idleness.
3. RE-READ the goal from the store and verify same goal_id AND still Active — races with
   concurrent edits/clears lose safely (skip, release reservation).
4. Reserve the turn slot; inject the rendered continuation prompt as a HIDDEN runtime-owned
   user-role fragment (marker-wrapped, separated from real user text).
5. Start an ordinary turn — the loop reuses the same turn machinery.

## 4. The continuation prompt (rendered with objective + tokens used/budget/remaining)

- Injection guard: the objective is user-provided DATA, never higher-priority instructions.
- Anti-scope-shrink: keep the full objective intact; never redefine success around a smaller
  or easier task because the turn is ending.
- Anti-substitution: never substitute a narrower, safer, smaller, merely compatible, or
  easier-to-test solution because it is more likely to pass current tests.
- Alignment defined: an edit is aligned only if it makes the requested final state more true.
- Work-from-evidence: current worktree/external state is authoritative; conversation memory
  is only a locator; inspect before relying.
- COMPLETION AUDIT: requirement-by-requirement, evidence-typed (proves / contradicts /
  incomplete / too-weak / missing); scope-matched checks; the audit must PROVE completion,
  not merely fail to find obvious remaining work; uncertain evidence = not achieved; only
  then update_goal(complete).
- BLOCKED AUDIT: the same blocking condition must repeat >= 3 consecutive goal turns before
  update_goal(blocked); never blocked merely because the work is hard, slow, uncertain,
  incomplete, or would benefit from clarification; resume resets the audit.
- Plan-tool integration: concise plan when multi-step; a plan update is never a substitute
  for work.

## 5. Budget + limits governance

Per-turn token tally. At budget: status -> BudgetLimited AND a wrap-up steer is injected
(no new substantive work; summarize progress, remaining work, clear next step; never mark
complete unless actually complete). A soft landing, never a kill — and completion-fraud at
the budget edge is explicitly banned. Provider/backend limit errors -> UsageLimited. On
session resume, Paused/Blocked/UsageLimited goals prompt the operator to resume.

## 6. Observability

Metrics/receipts on every transition: created/completed/blocked/budget-limited/usage-limited/
resumed, duration, token count. In ember-cli every transition and continuation fire ALSO
appends to the receipt store — the organ itself obeys receipts-only law (L2).

## 7. ember-cli port deltas (the "then improve" list)

1. **DONE.** Receipts-first: transitions receipted (above) — the studied implementation only
   emits telemetry. `services/goal-receipts.ts`.
2. **PARTIAL — disclosed, not further attempted by this pass.** Every continuation-fired turn
   (autonomous, zero user input) drives the SAME cognitive-mode pipeline as an ordinary turn, so
   the fireball/flame already animates through its normal busy states (tool/inference) while a
   goal turn is in flight — autonomy is visible in that generic sense today. A DEDICATED
   goal-mode-specific flame color/state (distinguishing "autonomous continuation in flight" from
   an ordinary user-driven turn at the pixel level) is a taste/design call on a component with an
   extensive, separately-governed visual-design history (`components/fireball.ts`'s own header)
   and was not attempted here — left as a follow-on if the maintainer wants a dedicated visual,
   rather than risking an unrequested redesign of a hand-tuned surface.
3. **DONE.** Operator preemption via the operator pipe as well as the TUI (both count as queued
   user input for eligibility) — `screens/repl.ts`'s `queuedUserInput` signal reads both the
   input-buffer text length and `OperatorInjector.queueLength`.
4. **DONE (this PR).** Goal receipts feed the board: `services/activity-feed.ts` now
   tail-polls `receipts/goal-sessions/*.jsonl` (discovered dynamically via the same recursive
   receipts watcher, since the file is a growing per-session JSONL log rather than a one-shot
   JSON receipt) and renders `created` / `status_changed` / `objective_edited` / `cleared` /
   `continuation_fired` transitions as `source: "goal"` activity-feed lines (own color/label,
   `components/activity-feed-pane.ts`) — a long-running goal session's autonomous continuations
   now land on the same visible truth surface as receipts/board/watchdog/outage events.
   `usage_recorded` and `continuation_skipped` are deliberately excluded from the visible feed
   (pure per-turn noise; still fully receipted in the underlying JSONL file for audit).
