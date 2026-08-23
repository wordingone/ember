# Issue #898 D+C Job-Memory Envelope and Observability Design

**Date:** 2026-08-23  
**Issue:** #898  
**Packet:** 1 — Cure D mechanism-derived `maximum_job_memory_bytes` plus Cure C job-scoped alarm and peak observability  
**Base:** `3126da1b6d84914d8e58101e3243c2fa3976c526`

## Outcome

The dense A1 launch derives its Windows Job Object memory ceiling from the
mechanism that creates commit charge. The daemon records the kernel's one-shot
job-memory-limit signal and the job-scoped peak in its ordinary operational
receipt. A lawful dense envelope admits; a lower, caller-authored envelope
refuses before argv construction or process birth.

This packet does not tune the pagefile, reactivate mmap Cure A, create a second
launcher, infer job memory from whole-host commit deltas, or act on a foreign
process.

## Governing evidence

The design follows the public #898 amendment and L2 probe:

- [Cure C amendment](https://github.com/wordingone/ember/issues/898#issuecomment-5375859115):
  the dense ceiling must be derived from the declared mechanism footprint.
- [L2 Job Object probe](https://github.com/wordingone/ember/issues/898#issuecomment-5289202818):
  `JOB_OBJECT_LIMIT_JOB_MEMORY` enforces, CUDA/WDDM commit is charged to the
  job, `JOB_OBJECT_MSG_JOB_MEMORY_LIMIT` is the one-shot alarm wire, and the
  largest measured hard-limit overshoot was 6.17 percent.
- #1873 and #1875 established the live host-setup preflight and receipt path.
  This packet extends that path rather than creating a parallel producer.

The 6.17 percent measurement generalizes to dense A1 because the probe measured
the same Windows hard Job Object limit across CUDA/WDDM allocation, and dense
A1 is a CUDA/WDDM job. It is used as a conservative hard-limit allowance, not
as a whole-host attribution or a claim about trainer working-set behavior.
Profiles without that mechanism evidence use zero allowance until equivalent
evidence is explicitly bound; callers cannot choose the percentage.

## D: closed mechanism-derived envelope

### Formula

`HostMechanismProfile` remains the sole source of the dense mechanism operands:

```text
optimizer_state_bytes = active_parameters * bytes_per_param
simulated_peak_commit_bytes = optimizer_state_bytes + transient_bytes
overshoot_allowance_bps = 617
overshoot_margin_bytes = ceil(simulated_peak_commit_bytes * 617 / 10_000)
maximum_job_memory_bytes = simulated_peak_commit_bytes + overshoot_margin_bytes
required_headroom_bytes = maximum_job_memory_bytes + reserve_bytes
```

The multiplication and addition are checked for overflow. Integer division is
rounded upward so the envelope never understates the receipted allowance.

`reserve_bytes` is host-survival headroom. It is deliberately outside the Job
Object ceiling because it is not job-charged demand. Admission requires live
available commit to be at least `required_headroom_bytes`; the Job Object is
armed only with `maximum_job_memory_bytes`.

### Disclosure

The existing host-setup disclosure gains a closed `job_memory_envelope` object:

```json
{
  "schema_version": "ember-host-job-memory-envelope-v1",
  "mechanism": "dense_full_state_adamw_cpu_offload",
  "active_parameters": 3839161856,
  "bytes_per_param": 12,
  "optimizer_state_bytes": 46069942272,
  "transient_bytes": 8589934592,
  "simulated_peak_commit_bytes": 54659876864,
  "overshoot_allowance_basis": {
    "kind": "windows_job_object_cuda_wddm_measured",
    "issue_comment": 5289202818,
    "basis_points": 617
  },
  "overshoot_margin_bytes": 3372514403,
  "maximum_job_memory_bytes": 58032391267,
  "host_reserve_bytes": 6442450944,
  "required_headroom_bytes": 64474842211
}
```

The numbers above illustrate the formula and are not an alternate manifest.
Production values are derived once from the profile and the same object is
threaded through preflight and receipt generation.

### Authority and refusal

- Dense defaults select a compiled, evidence-bound 617-basis-point allowance.
- A caller may disclose an expected `maximum_job_memory_bytes`, but it is a
  consistency assertion, not authority. Any value different from the derived
  result refuses before argv construction and spawn.
- A caller cannot override individual operands or the allowance through an
  unrelated run ID, manifest field, or environment variable.
- Host admission compares live available commit against the derived maximum
  plus reserve. The refusal receipt includes the same envelope disclosure.
- The existing certified launch receipt includes the exact envelope used for
  admission so the value reaching the Rust dispatch manifest is mechanically
  traceable to the mechanism profile.

The daemon makes the cap that actually armed the Job Object available to its
fixed, hash-bound certified-launch child through a new daemon-owned environment
field. Dispatch manifests are forbidden from supplying that field. The shared
dispatch-token consumer authenticates the named-pipe daemon, consumes the
single-use PID-bound token, parses the cap, removes the daemon-owned fields,
and returns the authenticated value to `certified_train_launch.py`.

The certified launcher then compares that authenticated armed cap with its
derived envelope before it builds or spawns the trainer runner. The certified
launcher process is necessarily already a suspended-then-resumed member of the
daemon Job Object; "pre-spawn" in this packet means the load-bearing trainer
runner boundary, not the authenticated launcher shim. Thus an underdeclared
manifest can create only the fixed refusal shim, never a trainer process.

The narrow #675 Q2 simulation producer is unchanged. A future generic native
profile producer belongs to the later sole-entrypoint packet, not this packet.

## C: per-job kernel alarm and terminal accounting

### Handle lifecycle

For a fresh Windows spawn, `spawn_managed` performs these steps before creating
the child:

1. Create the named Job Object.
2. Arm `JOB_OBJECT_LIMIT_JOB_MEMORY` and kill-on-close.
3. Create a private IO completion port.
4. Associate the port with the job using
   `JOBOBJECT_ASSOCIATE_COMPLETION_PORT`.
5. Create the child atomically inside the job with
   `PROC_THREAD_ATTRIBUTE_JOB_LIST`.

The completion-port handle travels with the Job Object through
`SpawnedProcess` into `LiveProcess`. Every failure path closes both handles and
terminates/waits only the newly created owned child. No handle or observer is
detached.

### Approved daemon-handoff exception

Windows refuses `JobObjectAssociateCompletionPortInformation` with Win32 error
5 when a daemon adopts a named Job Object that was already associated with the
former daemon's completion port. The association cannot be replaced. Killing
the still-valid job would violate detached-job custody, while claiming that a
replacement observer sees kernel code 10 would fabricate evidence.

Therefore the old observer cancels without terminating the job during daemon
handoff. The adopting daemon creates a private sentinel-only port and preserves
terminal job-scoped `PeakJobMemoryUsed` accounting. Its terminal event sets
`kernel_limit_signal_observation_available: false` and the machine-readable
reason
`job_object_completion_port_already_associated_win32_5_after_daemon_handoff`.
This is structurally unavailable observation, not a green no-alarm result and
not an observer failure. Fresh spawns continue to set the availability field
to true and retain the full kernel code-10 path.

### Observer and terminal ordering

Each live job gets one blocking observer for its private completion port. A
daemon-global demultiplexer is intentionally avoided: it would broaden shared
state and failure domains for no packet benefit.

The observer processes `JOB_OBJECT_MSG_JOB_MEMORY_LIMIT` (code 10), latches the
first signal, and persists it immediately. The kernel signal itself is
one-shot per job lifetime, so the receipt describes a latch, never a refusal
counter.

When the process handle becomes signaled, the existing exit monitor posts a
private terminal sentinel to the completion port. At that point no owned
process can make another allocation. The observer drains queued kernel packets,
queries `PeakJobMemoryUsed`, persists terminal accounting, and acknowledges a
barrier. Only after that barrier does the exit monitor persist `job_exited` or
the equivalent terminal state. This ordering prevents a limit signal from
racing receipt export.

The observer's terminal accounting is emitted even when the limit signal never
fired. Failure to query, verify, or persist is represented explicitly and
cannot be converted into a green value.

### Event schema

The first kernel limit message writes a `job_memory_limit_reached` event with:

- schema version and `scope: "windows_job_object"`;
- kernel message code 10 and `signal_latched: true`;
- job ID, offending PID, observed timestamp, and declared
  `maximum_job_memory_bytes`;
- the explicit `overshoot_allowance_basis`, `overshoot_allowance_bps: 617`,
  and `overshoot_margin_bytes` from the bound envelope;
- job-scoped `peak_job_memory_used_bytes` queried after the signal;
- `kernel_limit_signal_observation_available: true` and a null unavailability
  reason on fresh spawns;
- actual Job Object membership, process identity, and lease verification
  results, including an error/status when a check cannot complete.

The terminal `job_memory_accounting` event carries the same envelope identity,
the final job-scoped peak, whether the kernel signal was observed, and any
query/verification error. Boolean verification fields are computed from
`IsProcessInJob`, process start/executable identity, and the current database
lease; they are never hard-coded literals.

Because operational receipt export already serializes the job's event ledger,
these events become receipt evidence without a second receipt family. No
`CommitTotal` subtraction or other whole-host surrogate appears in either
event.

For an adopted job, terminal accounting instead carries
`kernel_limit_signal_observation_available: false` plus the exact handoff
reason above. `limit_signal_observed: false` in that event must not be
interpreted as proof that no code-10 message occurred before adoption.

## Error handling

- Failure to create or associate the completion port is a pre-birth refusal.
- Failure to start the observer after child creation terminates and waits that
  exact owned child before returning failure.
- A database write failure is preserved as an observer/terminal failure and
  prevents a complete terminal receipt; it is not silently dropped.
- Unexpected completion messages may be recorded diagnostically but cannot be
  interpreted as a memory-limit signal.
- Foreign PIDs are never opened for control or acted upon. The PID carried by
  code 10 is checked only against this job's membership and identity.

## Verification

### Python contract tests

Tests first establish:

1. exact dense formula, including upward rounding at 617 basis points;
2. reserve excluded from the job ceiling but included in admission headroom;
3. overflow and malformed-profile refusal;
4. lawful derived ceiling accepted and underdeclared ceiling refused before
   argv/spawn;
5. certified launch and receipt disclosure preserve the exact envelope.

All Python tests run with `-p no:cacheprovider`.

### Rust tests

Pure tests cover event serialization, one-shot latch semantics, explicit
allowance fields, terminal ordering, and failed verification representation.
Windows-native paired tests use the real managed-spawn path:

- below-limit child: no code-10 event, terminal job-scoped peak present;
- over-limit child: code-10 event with offending PID, allowance fields, and
  terminal job-scoped peak present.

These paired kernel-alarm probes cover fresh spawns, where the completion-port
association is owned from before process birth. A separate daemon-handoff test
proves that adopted jobs preserve custody, persist terminal peak accounting
before terminal state, and disclose the machine-readable alarm-unavailability
reason; it does not claim adopted-job kernel-alarm coverage.

The native child is a test fixture born inside the owned Job Object. It does
not train, use foreign processes, or rely on whole-host commit attribution.

### Dense-arm premerge probe

The frozen candidate runs a discardable receipt-first preflight pair under
`state/issue898-probe-*`:

- exact derived envelope: admission passes;
- same mechanism with an underdeclared expected cap: refuses before birth.

Custody is no-overwrite and records exact source, executable, commands,
stdout/stderr, raw hashes, and self-hashes. This probe grants no training,
checkpoint, or capability credit.

## Rejected alternatives

- **Peak polling only:** cannot distinguish a kernel refusal from no refusal.
- **Daemon-global completion port:** unnecessary shared-state restructuring.
- **Host reserve inside the Job Object cap:** lies about job-charged demand.
- **Caller-authored cap:** recreates the guessed-envelope defect.
- **Whole-host commit delta:** is not job-scoped evidence.

## Delivery boundary

Packet completion means source, tests, native probes, receipt review, exact-head
independent review, required CI, merge, and public verification appropriate to
the carrier. It does not close #898: A, B, E, G, narrowed H, I, and J remain in
the ruled successor order.
