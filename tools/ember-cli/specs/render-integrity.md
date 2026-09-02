<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Render integrity and receipt-event edge semantics

Status: SHIPPED

Issue: #561

Consumer: `src/ember/infrastructure/tools/ember-cli/src/screens/activity-flood-render-integrity.test.ts`
Consumer: `tools/ember-cli/src/services/activity-feed.test.ts`
Consumer: `src/ember/infrastructure/tools/ember-cli/src/ink/welcome-top-anchor.test.ts`

The ember-cli body has three invariant regions: the welcome/banner region remains locked at the
top, the conversation and activity stream owns the scrollable middle, and input/status chrome
remains locked at the bottom. Receipt activity is edge-triggered and resumable; existing files,
bulk materialization, fixture/plugin subtrees, and restart replay cannot masquerade as new work.

The named consumers are the executable constraint for this node. Issue #561's trusted closure
receipt and merge history remain the acceptance authority; this node does not create a new
capability claim.
