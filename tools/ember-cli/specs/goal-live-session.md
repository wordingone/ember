<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- issue_id: 211 -->
<!-- milestone: EMBER-03 -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Compiled goal-session live acceptance

Status: CURRENT

Evidence: compiled `goal-session-live` receipt and renderer-bound frame bytes.

Binding: renderer source and executable hashes are checked in with the receipt fixture.

Consumer: `tools/ember-cli/src/services/goal-live-session.ts`
Consumer: `tools/ember-cli/src/services/goal-live-session-frames.ts`
Consumer: `src/ember/infrastructure/tools/ember-cli/src/goal-live-session-compiled.test.ts`
Consumer: `tools/ember-cli/src/entrypoints/process-entry.ts`

The compiled `goal-session-live` path exercises the production continuation
engine and GoalStore boundaries with a deterministic local stub. Its receipt
binds queued-input preemption, autonomous continuation, Complete audit
evidence indices that precede Complete, and rendered frame bytes with fixed
dimensions plus exact source/executable bindings without external-model or
training claims.
