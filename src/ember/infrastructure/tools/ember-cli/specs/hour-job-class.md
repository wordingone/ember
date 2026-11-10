<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Lineage hour as an Ember Lab job

Status: CURRENT

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/ember-lab-hour.ts`, `runtime/ember-lab/src/hour_job.rs`

`start_hour` is an Ember Lab job class that starts one pinned hour dispatch
script (`^h\d+_dispatch_v\d+\.sh$`, exact lowercase SHA-256, a log that must not
exist) under the resident lab daemon, so Ember Studio and ember-cli can press a
lineage hour without a cockpit window. The contract is the one `/resume-hour`
already enforces and is pinned in `resume-hour-contract.json`, which both the
TypeScript and the Rust tests run case by case.

The lab starts the hour with an explicit normal priority class and the full
system CPU mask, read back while the child is still suspended; a mismatch
terminates the child and refuses. The child environment is the process
environment minus every `EMBER_*` key. The start receipt `<log>.lab-start.json`
is written before the START line is printed.

The hour survives Studio closing and a lab daemon crash: the job object is not
closed on exit for the hour class, and a restarted daemon re-adopts the running
hour through `reconcile()`. The typed client returns a refusal as a value
(`EmberLabRpcError` carries the server's error object).

Surviving descendants. `stop_job` ends the hour's whole process tree. When the hour's main process exits on its own, a
descendant it spawned and left running is NOT killed and is outside lab custody: the job is recorded `exited`, its
`hour-chain` lease is released, and `stop_job` on the `exited` row opens nothing, so a second job can start on the card while
the survivor runs and the lab cannot stop it (parity with a detached `/resume-hour`). The pinned hour and learn scripts run
their work in the foreground, so this does not arise for them; a script that detaches breaks one-job-at-a-time and the follow-up
issue (#2460) tracks keeping the lease and reporting `job_exited_with_survivors`.

Exclusive lease and receipt state. A start takes the `hour-chain` lease exclusively: any existing owner, including the same job
id from an identical concurrent start (same script, sha and log), refuses with `hour_lease_conflict`, and a refused start releases
no lease. If the child is already running but the `started`-phase receipt cannot be completed, the start still SUCCEEDS: the
result carries `job_id`, `pid`, `receipt_complete: false` and `receipt_error`, `START_HOUR_OK` ends with
`receipt_incomplete=<error>`, and the `intent` receipt stays on disk; the caller must not retry, because the hour is running.
Likewise, if the lab's own start returns an error AFTER the child was resumed and its row says `running`, the start still
SUCCEEDS and the lease is KEPT: the result carries `start_tail_error` (job id, pid and the error), `START_HOUR_OK` ends with
`start_tail_error=<error>`, and the `started` receipt records it. An error while the row is not `running` still frees the lease and
answers `hour_spawn_failed`. Freeing the lease of a live hour would let a second hour start on the card beside it.

Job kinds. The request carries `kind`, `hour` (the default, everything above) or
`learn` (a LEARN job, issue #2453). Kind `learn` takes a script named
`^learn_[A-Za-z0-9_-]+\.sh$` and a job id prefixed `learn-`; kind `hour` still
takes only `hNN_dispatch_vN.sh`, so a learn name under `hour`, an hour name under
`learn` and any other kind (`hour_kind_unknown`, exit code 37) are refused. Both
kinds hold the one `hour-chain` lease, so the shared card runs one job at a time,
and both get the same job events, stop, start receipt (which records `kind`) and
re-adoption. The `learn` kind adds no hour-only clause.

Preflight. `check_hour` (`ember-lab start-hour --check`) runs the same checks as
`start_hour` and peeks the lease, then returns `CHECK_HOUR_OK` or the same refusal
code; it creates no log, receipt, identity, lease or process. A client that asks
the lab before it presses therefore sees the refusal the start would raise, on
every check the lab makes itself. Only what the spawn alone can prove (the child
priority and CPU mask readback) is still refused at start.

This class grants no execution, model-update, or scientific-result credit. The
pre-press checks of an hour (loop hypothesis rows, commit gate, tree pins, the
B: floor wait) stay inside the pinned dispatch script, not in the lab.
