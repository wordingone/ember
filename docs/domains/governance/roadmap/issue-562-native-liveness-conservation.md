# Issue #562 native-liveness conservation

Status: `SUPERSEDED_NOT_PLANNED`

## Ruling

Issue #562's historical body-liveness carrier is superseded by current Ember
Lab owned-server supervision and canonical EMBER-03 operator evidence. The
removed hand-rolled PowerShell watchdog stays retired. Control-plane and
Task-Scheduler source work is implementation evidence only; live installed
task, kill/restart, next-boot, one-window, and continuous-recovery acceptance
has not been executed.

## Lossless current-owner transfer

Canonical owner: [EMBER-03/#1117](https://github.com/wordingone/ember/issues/1117),
using the single current Ember Lab supervision path completed under
[#802](https://github.com/wordingone/ember/issues/802).

Accepted transfer: https://github.com/wordingone/ember/issues/1117#issuecomment-5224506173

The accepted transfer conserves all four rungs:

1. **Rung 1 - native server supervision.** Preserve owned-server
   health/process/endpoint observation, planned-outage ordering, governed
   restore, stable resource identity across rebound jobs, lease/PID fencing,
   bounded backoff/alarm, and operational/activity receipts. Completed
   #802/PR #1522 supplies control-plane implementation evidence only and does
   not claim a live tenant, model, GPU, training, or capability result.
2. **Rung 2 - crash-free body.** Preserve exception containment and
   organism-visible, receipted errors through the current activity and CLI
   paths. No live crash/recovery result is inferred.
3. **Rung 3 - one OS-native restart rule.** Preserve one current-user,
   least-privilege, single-instance OS-native Ember CLI bounded
   restart-on-failure rule with exact installed `ember.exe` identity,
   XML/readback verification, kill/restart/next-boot receipt, and
   one-current-window/no-dead-shell proof. PR #1230 is implementation evidence;
   it did not execute the installed task or operator receipt.
4. **Rung 4 - watchdog retirement.** Preserve permanent retirement of the
   PowerShell watchdog and its dedicated process/window-enumeration surfaces,
   while retaining historical watchdog receipt parsing as provenance.

Preserve continuous owned-server live recovery, installed task identity,
negative/foreign-process refusal, deletion, interruption, and rollback.
Preserve exact source, executable, run, job, lease, process, and telemetry
identity, with strict live versus historical/replayed, stale, offline, missing,
malformed, and foreign evidence states.

## Architecture and claim boundary

Current Ember Lab, `runtime/ember-lab`, Ember CLI, dispatch, lease/PID fencing,
activity, and receipt/custody primitives remain the sole authority. This ruling
creates no hand-rolled watchdog, second daemon, second launcher, parallel
scheduler, or receipt family.

`NO_NEW_PARALLEL_AUTHORITY`

No installed-task execution, kill/restart, next-boot, live recovery, model
availability, GPU, training, capability, or milestone-completion credit is
claimed.

## Rollback

Revert this conservation document and reopen #562 if the accepted public
transfer is not posted, is rejected, is removed, is narrowed, if the retired
watchdog is revived, or if the obligations become detached from canonical
EMBER-03/current Ember Lab authority.
