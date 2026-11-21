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

Surviving descendants. `stop_job` ends the hour's whole process tree. The job object is not closed on exit for the hour class, so a
descendant the hour's main process left running is NOT killed when the main process exits, and it keeps the card. The lab therefore
treats the card as busy while the named job holds a process: the row becomes `exited` (with the exit code), the `hour-chain`
lease is KEPT, and the event `job_exited_with_survivors` names how many processes are left. A second start, and `check_hour`, are
refused `hour_lease_conflict` with a detail that names the hour and says `stop_job <id>` ends what it left. `stop_job` on that `exited`
row (or on an `orphaned` one: the main process ended while no lab was running) ends the named job's processes, releases the lease and
records `job_survivors_stopped`; a root that is alive without its named job cannot be ended by the lab and is reported with its pid.
When the survivors end on their own the next start, check or reconcile frees the lease (`job_survivors_gone`). At lab start a lease
whose job has no row is cleared (`hour_lease_without_job_cleared`).

Verified bytes. The script's sha256 is checked before the lease, then the lab opens the script file with a share mode that denies
writing, renaming and deleting, hashes the bytes through that handle (`hour_identity_changed` when they are not the pinned ones) and
holds the handle until the first lab call after the job leaves `running`. The start receipt records `script_locked: true`. Bash
still reads the file by its own path, so `$0` is the pinned path; nothing can change those bytes while the lab holds the handle. A
lab restart ends the protection (the hour itself is unaffected).

Exclusive lease and receipt state. A start takes the `hour-chain` lease exclusively: any existing owner, including the same job
id from an identical concurrent start (same script, sha and log), refuses with `hour_lease_conflict`, and a refused start releases
no lease and leaves no identity row. If the child is already running but the `started`-phase receipt cannot be completed, the start
still SUCCEEDS: the result carries `job_id`, `pid`, `receipt_complete: false` and `receipt_error`, `START_HOUR_OK` ends with
`receipt_incomplete="<error>"`, and the `intent` receipt stays on disk whole (the completing receipt is written to a temporary file,
synced and renamed over it, so a failed write cannot truncate the intent); the caller must not retry, because the hour is running.
Likewise, if the lab's own start returns an error AFTER the child was resumed and its row says `running` (or the row cannot be read),
the start still SUCCEEDS and the lease is KEPT: the result carries `start_tail_error` (job id, pid and the error), `START_HOUR_OK`
ends with `start_tail_error="<error>"` (both free-text fields are JSON strings, so a line carrying both parses unambiguously), and the
`started` receipt records it. The lab is NOT watching such an hour (no exit monitor was set up): when it ends its row stays `running`
and its lease stays until `stop_job <id>` or a restart of the lab. An error while the row is not `running` still frees the lease and
answers a refusal. Freeing the lease of a live hour would let a second hour start on the card beside it.

Refusal codes added for the start-only checks: `hour_outage_active` (122: a planned outage of `hour-chain` is in force),
`hour_job_object_exists` (123: the job object name is taken), `hour_identity_changed` (124: the script bytes changed after the first
check). 38 and 39 belong to the lab verbs, so these sit beside 120 and 121. `check_hour` mirrors the outage check; the others cannot be
known before a start creates anything.

Shell and working directory. `bash` must be `bash.exe` under a Git for Windows root (a folder holding `git-cmd.exe` one to three
levels above it) or the lab's own default path; any other file, even an existing `bash.exe`, is `hour_bash_refused`. An omitted
`cwd` means the lab daemon's working directory, which `/resume-hour` never uses: clients send their own (the typed client does by
default). The environment of the hour is the one the request carries (the client's environment minus every `EMBER_*` key); the lab
adds nothing to it for the `hour` and `learn` kinds.

Wire shape. `start_hour` params: `kind`, `script`, `sha256`, `log`, `cwd`, `bash`, `env`; result: `kind`, `job_id`, `pid`, `script`,
`sha256`, `log`, `receipt_path`, `bash`, `cwd`, `receipt_complete`, `receipt_error?`, `start_tail_error?`. `check_hour` takes the same
params and answers `kind`, `job_id` (the id a start would use), `script`, `sha256`, `log`, `receipt_path`, `bash`, `cwd`. `job_events`
returns at most 1000 events per call, oldest first after `after_seq`. The start receipt has two phases, `intent` then `started`.

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
