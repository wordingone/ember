<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Serving topology drift

Status: CURRENT

This specification re-homes issue #1282 C2 from the retired PowerShell watchdog
into the surviving native Ember cockpit. It does not create a serving launcher,
registry, or restart authority. Ember Lab remains the sole serving lifecycle
owner; this consumer only observes the live process set and the canonical
`state/serving-registry.json` rows.

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/serving-topology-drift.ts`

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/serving-topology-census.ts`

Consumer: `tools/ember-cli/src/services/serving-topology-live.ts`

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/poll-failure-status.ts`

## Contract

- The cockpit polls at an explicit five-second cadence while mounted and stops
  the cadence on unmount. Headless capture installs no poller.
- A hidden, noninteractive Windows census supplies PID, process name, and full
  command line. `llama-server`, `brain-server`, and the canonical
  `serve_cbase_openai.py` shim are the only live serving shapes.
- Reconciliation compares exact PID sets, not only counts. An unregistered live
  process and a dead registry row are independent drift shapes; an equal-count
  PID swap must produce both.
- Drift is written first to the external Ember state root as a path-free
  `ember-serving-topology-drift-v1` JSONL alarm. Only after the write succeeds
  may the cockpit append its operator-visible warning.
- One unchanged drift episode emits one alarm. A healthy poll rearms the same
  later drift. Malformed process/registry rows, duplicate PIDs, and an alarm
  path inside the source checkout fail closed.

## Claim boundary

This is CPU/file-only topology observation. It grants no serving availability,
restore, GPU, model, training, checkpoint, scientific-result, C3/C4, or issue
completion credit. `NO_NEW_PARALLEL_AUTHORITY`.

Poll-cadence failure diagnostics route through the shared `poll-failure-status.ts`
tracker into the cockpit activity feed rather than raw `console.warn` (#1698);
the tracker carries no drift-detection, alarm-write, or reconciliation
authority of its own. It publishes a transition line only on a failure class's
first-seen, message-changed, or recovered edge -- never one per poll tick or
per elapsed window -- and exposes the steady-state per-class status (running
count, since-timestamp) the sticky status region renders (#1701). The original
`poll-failure-dedup.ts` window-republish helper (#1698/#1700) remains in the
tree, unmodified and independently tested, but is no longer wired to any
producer.

## Rollback

Revert the four consumers, the REPL lifecycle wiring, tests, and this spec as
one unit. Preserve already-emitted external alarm receipts for audit.
