# Issue #696: Ember Lab supersession of the historical brain supervisor

Status: `SUPERSEDED_DUPLICATE_NOT_PLANNED` on current public master.

Source issue: #696 (`ember-cli: wire brain-server supervisor into a real consumer path`).
Current source master: `63f33108b41441d4bd7ef93662d2cc29d51d0ecd`.
Canonical current carrier: merged #802 / Ember Lab `00eec85d2bd3073b137b51f2d89b78d905b46076`,
with the continuing current-architecture owner `runtime/ember-lab` and the open
`EMBER-03` roadmap parent (#1117).

## Historical-to-current crosswalk

The historical `tools/ember-cli/src/services/brain-server-supervisor.ts` vehicle
(`:8083`, borrowed 2.2B cbase) is `SUPERSEDED`, not a second production authority.
Its source/test/fixture blobs are retired by this change:

- implementation blob: `5a03fc58fc73ac33db523bd36cb7d0c03c3f1b71`;
- test blob: `99f379b6540f7afe3ddb5f8d80e5941a4411ccea`;
- fixture blob: `4709e99bb81846eb833b8be5527b833bacdee8cc`.

| Historical #696 obligation | Current owner and status | Lossless preservation |
|---|---|---|
| First real consumer starts the service lazily, never at boot | `tools/ember-cli/src/commands/model.ts` and `entrypoints/process-entry.ts` call `entrypoints/owned-server-supervisor.ts` only while a bound model command/session is established (`REORGANIZED`) | No boot-time or bare `start` spawn remains; the consumer path is the only start trigger. |
| Health, process ownership, and own-process-only stop | Ember Lab `server_supervisor.rs` plus owned-server identity/lease/process fencing (`REORGANIZED`) | Health and process identity are revalidated by the daemon; recovery cannot terminate a foreign PID or lease. |
| Planned-outage open/expired/closed behavior | Ember Lab planned-outage state and live supervisor cycle (`REORGANIZED`) | Open windows wait before fencing; expiry/closure returns supervision to the current owned-server path. |
| Restore/receipt/live-fire evidence | Ember Lab dispatch, activity ledger, and content-addressed receipt primitives (`REORGANIZED`) | Restore, health, death cause, cost, and activity events are daemon-owned; no caller-authored `:8083` receipt survives. |
| No idle tenant | Current owned-server consumer and Ember Lab lease authority (`REORGANIZED`) | A historical borrowed 2.2B tenant is not launched or credited; current model authority is required before serving. |

The #802 closure evidence explicitly covers the current owned-server health loop,
planned-outage ordering, stable rebound identity, no-foreign-process fencing,
receipt custody, activity events, and restart backoff. It grants no model,
capability, training, GPU, or historical 2.2B credit to #696.

## Conflict scan and authority verdict

The old supervisor had no production import consumer; only its tests and stale
documentation referenced it. The current `owned-server-supervisor.ts` delegates
to the existing Ember Lab RPC, while `runtime/ember-lab/src/server_supervisor.rs`
owns identity, lease, dispatch, outage, event, and receipt decisions. No launcher,
daemon, lease store, ledger, registry, or receipt family is added here.

`NO_NEW_PARALLEL_AUTHORITY`

Claim boundary: this is an architectural retirement and lossless obligation
transfer only. It does not claim a live Qwen tenant, model availability,
capability, training, benchmark, or GPU execution.
