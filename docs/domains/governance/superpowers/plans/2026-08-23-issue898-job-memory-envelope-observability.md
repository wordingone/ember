# Issue #898 D+C Job-Memory Envelope and Observability Implementation Plan

> **Execution rule:** follow the committed design in
> `docs/domains/governance/superpowers/specs/2026-08-23-issue898-job-memory-envelope-observability-design.md`.
> Tests precede implementation. Every process-producing command runs through
> `src/ember/governance/scripts/owned_process.py`; every Python process also runs through
> the configured hidden/no-window Python launcher; pytest always uses
> `-p no:cacheprovider`.

**Goal:** Derive dense A1's armed Job Object cap from its declared mechanism,
refuse any mismatch before trainer spawn, and persist the kernel job-memory
alarm plus final job-scoped peak in the ordinary daemon receipt.

**Architecture:** Python owns the mechanism formula. Rust owns the Job Object
and stamps the cap it actually armed into a manifest-forbidden daemon field.
The authenticated dispatch-token consumer returns that value to the fixed
certified-launch shim, which compares it with the derived envelope. Each
Windows job has a private IOCP observer and a terminal sentinel/barrier so code
10 and `PeakJobMemoryUsed` are durable before terminal receipt export.

**Stack:** Python 3.10, pytest/unittest, Rust 2021, rusqlite, serde_json,
windows-sys 0.59, Windows Job Objects and IO completion ports.

---

## Task 1: Derive the closed dense mechanism envelope

**Files:**

- Modify: `tests/ember_restart_model/domain-governance/test_host_setup_contract.py`
- Modify: `tools/ember-restart-3b/host_setup_contract.py`

### Step 1: Write failing formula and refusal tests

Add tests for:

- 617-basis-point upward rounding;
- `simulated_peak_commit_bytes = optimizer + transient`;
- `maximum_job_memory_bytes = simulated + margin`;
- reserve excluded from maximum but included in required headroom;
- malformed/overflow operands fail closed;
- expected maximum exact-match passes and an underdeclared value refuses.

Run the focused test and preserve the expected red output.

### Step 2: Implement the minimum envelope object

Add a frozen, schema-versioned envelope disclosure and checked integer helpers.
Bind 617 basis points only in the dense CUDA/WDDM profile. Make
`HostSetupContractRefusal` report the derived maximum, reserve, required
headroom, and shortfall without pagefile formalization.

### Step 3: Run the focused tests green

Run only `test_host_setup_contract.py`, then the whole
`tests/ember_restart_model` host-contract subset.

## Task 2: Bind the actually armed daemon cap to the consumer

**Files:**

- Modify: `runtime/ember-lab/src/lib.rs`
- Modify: `src/ember/governance/scripts/ember_dispatch_token.py`
- Modify: `scripts/tests/test_ember_dispatch_token.py`
- Modify: `runtime/ember-lab/tests/dispatch_manifest.rs`

### Step 1: Write failing shared-consumer tests

Require a daemon-owned armed-cap field, strict positive-integer parsing,
return of the authenticated value, and removal before child inheritance. Test
missing, malformed, ambient-only, and authenticated cases.

### Step 2: Write failing manifest-boundary test

Prove a dispatch manifest that supplies the daemon-owned field is refused
before spawn.

### Step 3: Stamp and consume the field

In the daemon, reserve the field name and stamp `JobSpec`'s actual
`maximum_job_memory_bytes` only on the token-gated child. Keep it in the
persisted environment disclosure but never persist the token. In the shared
consumer, authenticate the named-pipe server and consume the PID-bound token
before trusting the field; then return the parsed cap and remove all
daemon-owned dispatch fields.

### Step 4: Run both focused suites green

Run the Python token tests and the relevant Rust dispatch-manifest tests.

## Task 3: Refuse dense cap drift before trainer argv/spawn

**Files:**

- Modify: `tests/ember_restart_model/test_a1_certified_launch.py`
- Modify: `tools/ember-restart-3b/certified_train_launch.py`

### Step 1: Write failing launch-boundary tests

Prove:

- a lawful authenticated cap admits;
- an underdeclared authenticated cap raises before `build_runner_argv` and
  before the injected `run_process` is called;
- the certified receipt carries the exact closed envelope;
- Tier 2 and non-dense routes retain their current host-contract behavior.

### Step 2: Thread the authenticated cap

Return the cap from `consume_ember_lab_dispatch`, pass it through `main`, and
compare it inside the Tier-1 host setup validation. Keep direct test entrypoints
explicit: a dense call without an authenticated armed cap fails closed rather
than inventing one.

### Step 3: Run focused and neighboring launcher tests green

Run the two host/launcher files together and review the execution receipt bytes.

## Task 4: Add the per-job IOCP lifecycle and truthful event model

**Files:**

- Modify: `runtime/ember-lab/Cargo.toml`
- Modify: `runtime/ember-lab/src/lib.rs`
- Modify: `runtime/ember-lab/tests/control_plane.rs` or colocated unit tests

### Step 1: Write failing pure event tests

Define tests for:

- code-10 latches once;
- explicit 617-basis-point allowance disclosure;
- peak and maximum remain job-scoped;
- failed membership/identity/lease checks serialize as failed or unavailable,
  never literal green;
- terminal accounting precedes `job_exited`.

### Step 2: Add Windows completion-port ownership

Enable the windows-sys SystemServices feature. Create and associate one private
completion port after arming the Job Object and before `CreateProcessW`. Carry
the owned handle through `SpawnedProcess` and `LiveProcess`. Close it on every
failure path.

### Step 3: Add observer, sentinel, and barrier

Start one blocking observer per retained job. On code 10, query the job peak and
persist the first signal with actual PID membership, process identity, and
lease checks. After the process signals, post a private sentinel; drain the
port, query the final peak, persist `job_memory_accounting`, acknowledge the
barrier, then permit `record_process_exit` to persist `job_exited`.

### Step 4: Make setup/persistence failure fail closed

If observer setup fails after birth, terminate and wait the exact owned job and
mark failure. If terminal accounting cannot persist, do not emit a complete
terminal receipt. Preserve diagnostic status without hard-coded verification.

### Step 5: Run Rust unit tests green

Run the library tests and focused control-plane tests under the owned runner.

## Task 5: Prove real Windows alarm and no-alarm legs

**Files:**

- Modify: `runtime/ember-lab/tests/dispatch_manifest.rs`

### Step 1: Extend the existing allocation fixture

Reuse `EMBER_LAB_DISPATCH_ALLOCATE_BYTES`; do not introduce another launcher.
Add a below-limit leg that exits normally and an over-limit leg that exercises
the real Job Object allocation refusal.

### Step 2: Assert exact operational receipt content

For below-limit, assert no `job_memory_limit_reached`, one terminal
`job_memory_accounting`, and a positive job-scoped peak. For over-limit, assert
code 10, the offending PID, explicit 617 allowance, actual verification
results, one latched event, and final peak before `job_exited`.

### Step 3: Run the native test repeatedly

Run the exact paired tests at least twice to expose ordering races, then the
entire `dispatch_manifest` integration target. Verify owned cleanup after every
run.

## Task 6: Run the frozen dense admit/refuse probe

**Files:**

- Create under no-overwrite custody: `state/issue898-probe-*`
- Do not commit generated probe custody unless the integrator/reviewer
  explicitly rules it into the carrier.

### Step 1: Freeze candidate identity and commands

Record exact source commit, daemon executable/source hashes, run-spec and
certificate hashes, derived envelope, command lines, and custody roots.

### Step 2: Execute the receipt-first pair

Run the fixed certified-launch shim through the real daemon path:

- lawful armed cap equal to the derived envelope: preflight admits;
- cap one byte below the derived maximum: certified shim refuses before
  trainer argv/spawn.

Both legs use hidden/no-window owned processes and distinct no-overwrite roots.

### Step 3: Review raw and self hashes

Review stdout/stderr and every JSON field. Recompute raw hashes, verify any
self-hash convention, confirm no trainer process was born in the refusal leg,
and confirm neither receipt uses whole-host attribution as job peak evidence.

## Task 7: Full verification and freeze handoff

**Files:**

- Modify as required by gates only; no opportunistic cleanup.

### Step 1: Run formatting and static gates

Run Rust fmt check, clippy with warnings denied, Python compile/import checks,
focused pytest with `-p no:cacheprovider`, the Rust library/integration suites,
commit guard, and worktree lifecycle audit.

### Step 2: Inspect the exact diff and custody

Run `git diff --check`, inspect every changed path, verify the base/head tuple,
ensure no generated cache or unrelated user change is staged, and verify no
owned descendant remains.

### Step 3: Freeze to integrator

Mail the integrator the exact head, base, changed paths, test commands and
outputs, native probe roots and hashes, review boundaries, and integrator
commands. Do not claim #898 closure; packet successors remain separately gated.
