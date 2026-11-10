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

This class grants no execution, model-update, or scientific-result credit. The
pre-press checks of an hour (loop hypothesis rows, commit gate, tree pins, the
B: floor wait) stay inside the pinned dispatch script, not in the lab.
