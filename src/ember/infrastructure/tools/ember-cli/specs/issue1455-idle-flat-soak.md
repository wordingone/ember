<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Issue #1455 delivered-state idle-flat soak guard

Status: CURRENT

Issue: #1455

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/issue1455-idle-soak-harness.ts`

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/ols-fit.ts`

## Contract

Pins the delivered state established by three overnight soak legs on issue
#1455: the runaway heap-growth class is cured; the residual native/off-heap
RSS growth under pollers-active conditions is bounded and linear; the
JS-managed heap shows no sustained trend. The verdict, scope decision, and
raw calibration data are recorded on the issue (see the leg-6 comment) and in
this PR's body — this node states the contract the regression test enforces,
not the calibration arithmetic itself.

`issue1455-idle-soak-harness.ts` spawns a real, compiled-from-source ember-cli
cockpit under `node-pty` with the exact env configuration the soak legs
measured (`headlessCaptureEnv()` always on, `EMBER_DIAGNOSTIC_FORCE_POLLERS_LIVE=1`,
activity-feed left enabled), and samples `process.memoryUsage()` plus
forced-GC `bun:jsc` heap floors over a live CDP session. `ols-fit.ts` is the
shared ordinary-least-squares slope helper both the harness's regression test
and the original investigation's own by-hand verification use, so a
regression claim in the test and a regression claim in the issue thread are
computed the same way.

Two assertions guard the runaway class returning, not the residual itself:
RSS OLS slope over a calibrated window stays under a generously-bounded
ceiling, and the JS-managed heap's forced-GC floor shows no meaningful
absolute drift between window start and end. Both thresholds and the window
length are calibrated from the investigation's own real raw sample data, not
judgment — see the closing PR body for the calibration script and the
window-length margin table.

## Lifecycle and rollback

The harness resolves the checkout root it spawns from its own file location
(never a worktree-canonicalizing resolver — see the harness's own comment on
why), so any future subprocess/spawn harness reusing this shape must do the
same. Removal of the harness, the OLS helper, their regression test, and this
spec node is the complete rollback; it reopens no other issue's obligations,
since #1455's runaway-class verdict is already recorded on the issue
independent of this test's existence.
