# NC-K event-loop skeleton — architecture v0 (Closes #260)

## Architecture

The NC-K resident event-loop is a CPU-only, stdlib-only Python process that
runs perpetually, pulling events from registered sources and routing actions
through a single tool registry.  It is the harness half of the ember core ×
harness pair (sp5 §6).

### EventSource (ABC)

`poll() -> Iterator[Event]` — called each tick.  Four implementations:

| Source | Kind | Status |
|---|---|---|
| `FileWatchSource` | Polls a directory for new/changed files (mtime+size tracking) | LIVE |
| `ScheduleSource` | Cron-like due items from `schedule.json`; updates `last_run_ts` atomically | LIVE |
| `JobReceiptSource` | Polls a receipts directory for new `*.json` files | LIVE |
| `MailSource` | Signal-file watcher for mailbox events | **STUB** — see #259 |

### Tool Registry

One uniform interface: `name -> {fn, schema, concurrency_safe, read_only, permission_class}`.
Dispatch is name-lookup only; no special execution paths.  Unknown verb →
`REGISTRY_REFUSE` (ValueError); the loop journals a refusal record and
continues.

Built-in tools registered at loop construction:
- `write_gate_note` — appends a JSONL line to `gate_notes_dir/gate-notes.jsonl`
- `heartbeat_touch` — writes current timestamp to the heartbeat file

### Stub core

`stub_core(event, registry) -> list[Action]` — a pure Python function, no
model, no I/O.  Rules:

- `job_receipt` / `receipt_arrived` → `write_gate_note`
- `file_watch` / broadcast filename prefix → **no action** (selectivity)
- `schedule` / `tick_due` → `write_gate_note` with schedule id
- Everything else → no action

The stub core is the swappable boundary: replace with the real model-backed
core without touching the loop machinery.

### Crash-safe journal

`state/nck-journal.jsonl` — append-only JSONL.  Per action:

1. `{"status": "pending", ...}` written **before** execution (fsync).
2. Action executed via the tool registry.
3. `{"status": "applied", ...}` written **after** execution (fsync).

On restart, the journal is scanned: any `action_id` with an `applied` record
is skipped.  Any `pending` without `applied` is re-executed (idempotence
required per verb — `write_gate_note` is idempotent by construction).  An
unknown verb is journaled as `{"status": "refused"}` and skipped.

### Hook points

`loop.pre_action_hooks` and `loop.post_action_hooks` — lists of callables
invoked around every action execution.  Callables are registered by appending
to these lists before `loop.run()`.

### Fail-closed invariant config

`validate_invariant_config(config)` runs at `NCKEventLoop.__init__` time.  It
raises `SystemExit("LOOP_REFUSE: ...")` if:

- `governor` block absent or missing any of `{vram_fraction, margin_gib_floor, pace_s_per_step}`
- `goal_file` key absent

The loop will not start without these blocks (sp5 §5: un-removable invariants).

### Process supervision

Heartbeat file (`state/nck-heartbeat.txt`) is touched on every loop tick.
A dead heartbeat signals a stalled or crashed loop.  All tool execution is
in-process in this skeleton; child process supervision (for GPU bursts via
the train daemon) is scoped to a future issue that wires the daemon client.

---

## What is stubbed

| Component | Stub | Tracking issue |
|---|---|---|
| `MailSource` | Raises `NotImplementedError` with a pointer | #259 (ember mailbox identity + founders.yaml signal wiring) |
| Model core | `stub_core` — rule-based pure Python | #260 follow-on: replace with model-backed core |
| Child process supervision (GPU bursts) | Not implemented | Future issue: train-daemon client wiring |
| Protected-invariant boot-checksum layer | Not implemented | sp5 §5 — see nck-spec-v0.md §"The five un-removable invariants" |

---

## Provenance attestation

Every file read to produce this skeleton is listed below.  No avir-cli source
was accessed at any point.  The implementer worked solely from spec documents
and in-repo Python.

| File read | Role |
|---|---|
| `docs/sp5-nck-harness-port-spec-v0.md` | Primary spec: resident form (§2), harness invariants (§3/§5), communicability (§4) |
| `docs/sp6-duty-battery-v0.md` | Duty battery spec: verb classes, selectivity episodes, episode families |
| `docs/sp6-duty-battery.jsonl` | 20 episode rows: event/expected_verb/target_pattern for the four families |
| `docs/nck-invariant-contract-v0.md` | 15 invariants: uniform tool interface (inv 5), dispatch (inv 6/7), state persistence (inv 12/13) |
| `docs/nck-spec-v0.md` | Process shape, write surface, five un-removable invariants with mechanisms |
| `origin/eng/254-heartbeat-runner:scripts/heartbeat_runner.py` | Pattern reference only: phase machine, halt receipts, native subprocess, journal append pattern |

No file outside this repository was read.  No file under `B:/M/avir-cli` or
any avir-cli source, vendored copy, or transcript was accessed.

---

## Spec ambiguity resolutions

1. **MailSource in the loop body** — the spec requires MailSource to raise
   `NotImplementedError` but also requires the loop to function as a skeleton
   while #259 is open.  Resolution: the loop catches `NotImplementedError`
   from any source and skips it with a comment, so `FileWatchSource`,
   `ScheduleSource`, and `JobReceiptSource` continue working.  MailSource is
   still a STUB and will fail if polled directly.

2. **Crash-resume semantics for pending-without-applied** — the spec says
   "resume from journal without re-executing applied actions."  Pending-without-applied
   is ambiguous (the action may or may not have executed before the crash).
   Resolution: re-execute, relying on per-verb idempotence.  `write_gate_note`
   is idempotent (append-only).  The doc notes this requirement explicitly so
   the real core audits idempotence per verb before relying on replay.

3. **action_id stability** — the spec does not specify the ID scheme.
   Resolution: SHA-256 of `{verb, args, event_ts}` truncated to 16 hex chars.
   Stable across restarts for the same logical action; collision probability
   negligible for the expected cardinality.

4. **Heartbeat granularity** — the selftest case (e) may see equal timestamps
   at second granularity within the same test run.  Resolution: the test
   asserts `ts1 <= ts2` (not strict inequality) and checks both are non-empty.
   The operational invariant (heartbeat written every tick) is satisfied.
