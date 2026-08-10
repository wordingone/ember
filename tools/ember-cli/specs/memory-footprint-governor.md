<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Native memory-footprint governor

Status: CURRENT

Issue: #1282 C1 (carried from #1273; covers the #756 failure class without closing it)

Consumer: `tools/ember-cli/src/services/memory-footprint-governor.ts`

Consumer: `tools/ember-cli/src/services/process-memory-census.ts`

Consumer: `tools/ember-cli/src/services/memory-footprint-service.ts`

Consumer: `tools/ember-cli/src/services/memory-footprint-live.ts`

Consumer: `tools/ember-cli/src/services/memory-footprint-cockpit.ts`

## Authority and custody

The native Ember CLI cockpit is the sole live poll-loop owner. It loads the
existing canonical bytes at
`tools/ember-cli/specs/liveness-watchdog-memory-v1.json`, binds their SHA-256
into every trip receipt, and appends receipts below the external Ember state
root. It never rewrites the frozen JSON spec and never writes runtime state into
the checkout. Headless capture installs no poll loop.

The Windows census uses hidden PowerShell only to read `Win32_Process`
parentage and `PagedMemorySize64`. The exact current cockpit PID is admitted.
Configured brain-server names are admitted when they are direct children of
that cockpit or when their PID is returned by the resident Ember Lab daemon's
same-user named-pipe `ember-lab-runtime-identity-v1` response. This keeps a
daemon that predates the cockpit observable without accepting a foreign
same-named process. If the daemon identity is unavailable, cockpit observation
continues and the ownership failure is operator-visible; no unbound process is
silently admitted. Unreadable or ambiguous owned rows fail closed.

## Threshold and receipt contract

Each `(process_class, pid)` owns an isolated debounce episode. Three consecutive
hard polls trip once; a poll below hard resets a partial debounce, and a tripped
episode rearms only below hard. A vanished process clears its episode before a
recycled PID can inherit it.

The durable JSONL row is written before any corrective request and includes at
least `{ts, pid, commit_gb, threshold, action}`, plus the process class and exact
canonical spec path/SHA-256. Receipt-write failure blocks the corrective request
and leaves the next poll eligible to retry.

For the current cockpit PID, the post-receipt action is exit code 75 so the
existing verified Windows Task Scheduler restart-on-failure authority performs
the restart. A foreign cockpit receipt can never exit the current process. A
brain-server trip is routed only through the injected Ember Lab owner callback;
this service never kills or launches a model process directly. If no callback
is installed, the durable receipt and named warning remain evidence of an
unfulfilled operator action rather than a false restart claim.

## Lifecycle, failure, and rollback

Mount starts exactly one supervisor; unmount stops it. Slow polls never overlap,
and scheduled census failures are contained and reported without an unhandled
rejection. Removal of the five consumers, their focused tests, the REPL wiring,
and this spec is the complete rollback. Rollback reopens #1282 C1 because the
legacy JSON threshold spec would again have no live consumer.

This carrier grants no GPU, training, checkpoint, model-quality, availability,
#756 closure, or whole-issue #1282 closure credit. C2-C4 remain separate live
obligations.
