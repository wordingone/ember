# Issue #898 L7 Foreign-Pressure Sentinel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a daemon-lifetime, identity-bound Windows foreign commit/GPU census whose host-floor state fences admission without ever controlling a foreign process.

**Architecture:** Extend the existing Ember Lab resource-monitor thread and SQLite authority; do not add another daemon or launcher. Keep the new automatically clearing pressure state separate from the sticky survival guard, and make the existing dispatch preflight require both states to be open.

**Tech Stack:** Rust 2021, `rusqlite`, `serde_json`, `windows-sys` 0.59 (`ProcessStatus`, `Threading`, `JobObjects`), existing NVIDIA SMI parser, Windows integration tests.

**Spec:** `docs/superpowers/specs/2026-08-25-issue898-foreign-pressure-sentinel-design.md`

## Global Constraints

- Exact base is `b4084ac442a3f70c38f1bec0a0bd480512b7e145` in the assigned linked worktree.
- Run the census on the existing 2,000 ms resource-monitor interval; create no detached helper or second monitor authority.
- Fence trigger is `GetPerformanceInfo` commit remaining below the existing 10 GiB floor; 4 GiB inclusive is an attribution cutoff only.
- Every complete observation sums `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage` for all non-owned user processes, including sub-threshold processes.
- Ownership requires actual current Ember Lab Job Object membership; image, path, name, parent PID, argv, and environment are never ownership.
- Foreign process handles request read/query rights only and never terminate, suspend, debug, duplicate, or write rights.
- One `GetPerformanceInfo` sample is shared by the survival guard and foreign-pressure census on each monitor tick.
- Never control a pre-existing desktop process; tests create and own their own hidden/no-window sentinel fixtures and bind them by creation token.
- The integration owner holds shared Git/index/commit authority. Do not commit locally unless that authority is explicitly transferred; after each reviewable task, send the review seat exact status, diff, test output, and hashes.
- This plan runs no Python commands.

---

### Task 1: Pressure schema and pure transition policy

**Files:**
- Modify: `runtime/ember-lab/src/lib.rs:1230-1245`
- Modify: `runtime/ember-lab/src/lib.rs:2147-2170`
- Modify: `runtime/ember-lab/src/lib.rs:8520-8670`

**Interfaces:**
- Produces: `ForeignProcessIdentity`, `ForeignProcessCensus`, `ForeignPressureState`, `foreign_pressure_transition(&ForeignProcessCensus) -> ForeignPressureState`, `persist_foreign_process_census(&Connection, i64, Result<ForeignProcessCensus>) -> Result<()>`, and `foreign_process_pressure_status_from_connection(&Connection) -> Result<Value>`.
- Consumes: existing `RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES`, `RESOURCE_GUARD_SAMPLE_INTERVAL_MS`, `hash_bytes`, `now_ms`, and `rusqlite` transaction helpers.

- [ ] **Step 1: Write failing policy tests beside the resource-guard policy tests**

```rust
#[cfg(test)]
mod foreign_pressure_policy_tests {
    use super::*;

    fn census(commit_remaining_bytes: u64, rows: Vec<ForeignProcessIdentity>, total: u64) -> ForeignProcessCensus {
        ForeignProcessCensus {
            host_commit_total_bytes: 54 * GIB,
            host_commit_limit_bytes: 64 * GIB,
            host_commit_remaining_bytes: commit_remaining_bytes,
            total_foreign_private_commit_bytes: total,
            named_foreign_processes: rows,
            excluded_kernel_pids: vec![0, 4],
            enumerated_process_count: 14,
            owned_process_count: 2,
        }
    }

    fn foreign(pid: u32, private_commit_bytes: u64, gpu_bytes: Option<u64>) -> ForeignProcessIdentity {
        ForeignProcessIdentity {
            pid,
            process_start_token: format!("token-{pid}"),
            private_commit_bytes,
            gpu_bytes,
            provider: gpu_bytes.map(|_| "nvidia-smi".into()),
            candidate_classes: vec!["private_commit_attribution".into()],
        }
    }

    #[test]
    fn five_gib_foreign_process_is_named_but_does_not_fence_healthy_host() {
        let row = foreign(500, 5 * GIB, None);
        assert_eq!(foreign_pressure_transition(&census(12 * GIB, vec![row], 5 * GIB)), ForeignPressureState::Observed);
    }

    #[test]
    fn many_sub_cutoff_processes_fence_on_host_floor_with_empty_named_set() {
        assert_eq!(foreign_pressure_transition(&census(9 * GIB, vec![], 42 * GIB)), ForeignPressureState::Fenced);
    }
}
```

- [ ] **Step 2: Run the focused library tests and confirm RED**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib foreign_pressure_policy_tests -- --nocapture`

Expected: compile failure because the foreign-pressure types and functions do not exist.

- [ ] **Step 3: Add constants, data types, schema, and pure transition function**

```rust
const GIB: u64 = 1024 * 1024 * 1024;
const FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES: u64 = 4 * GIB;
const FOREIGN_PRESSURE_OBSERVATION_LIMIT: i64 = 4096;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ForeignProcessIdentity {
    pid: u32,
    process_start_token: String,
    private_commit_bytes: u64,
    gpu_bytes: Option<u64>,
    provider: Option<String>,
    candidate_classes: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ForeignProcessCensus {
    host_commit_total_bytes: u64,
    host_commit_limit_bytes: u64,
    host_commit_remaining_bytes: u64,
    total_foreign_private_commit_bytes: u64,
    named_foreign_processes: Vec<ForeignProcessIdentity>,
    excluded_kernel_pids: Vec<u32>,
    enumerated_process_count: u64,
    owned_process_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum ForeignPressureState { Clear, Observed, Fenced, ProbeFailed }

fn foreign_pressure_transition(census: &ForeignProcessCensus) -> ForeignPressureState {
    if census.host_commit_remaining_bytes < RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES {
        ForeignPressureState::Fenced
    } else if census.named_foreign_processes.is_empty() {
        ForeignPressureState::Clear
    } else {
        ForeignPressureState::Observed
    }
}
```

Add both tables and seed the singleton in `Daemon::open_inner` and the migration helper:

```sql
CREATE TABLE IF NOT EXISTS foreign_process_pressure_state(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  state TEXT NOT NULL CHECK(state IN ('clear','observed','fenced','probe_failed')),
  observed_at_ms INTEGER NOT NULL,
  observation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS foreign_process_pressure_observations(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at_ms INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
INSERT OR IGNORE INTO foreign_process_pressure_state(singleton,state,observed_at_ms,observation_json)
VALUES(1,'probe_failed',0,'{"schema_version":"ember-lab-foreign-process-pressure-observation-v1","result":"NOT_YET_SAMPLED"}');
```

`persist_foreign_process_census` must build one exact observation JSON value, insert it, trim to 4,096 rows, and update the singleton in one unchecked transaction. An error result writes `probe_failed` and the exact error; it must not retain an earlier clear state.

- [ ] **Step 4: Add persistence tests and run GREEN**

Test exact transitions `probe_failed -> observed -> fenced -> clear`, row count, aggregate, ordered identities, floor/cutoff fields, `foreign_process_control:false`, and bounded-ledger deletion. Run:

`cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib foreign_pressure -- --nocapture`

Expected: all focused tests pass.

- [ ] **Step 5: Send Task 1 review packet to the review seat**

Run `git diff --check`, `git status --short`, and SHA-256 the modified files with `Get-FileHash`. Mail the review seat the commands, raw pass summary, status, and hashes. Do not stage or commit without transferred integration authority.

---

### Task 2A: Schema version 7

**Files:**
- Modify: `runtime/ember-lab/src/lib.rs`
- Modify: `runtime/ember-lab/tests/data_catalog.rs`
- Modify: `domains/runtime/runtime/ember-lab/tests/artifact_custody.rs`

**Interfaces:**
- Produces: schema version 7 and both foreign-pressure tables.
- Consumes: the existing immediate SQLite migration transaction.

- [ ] **Step 1: RED — fresh schema identity**

Add `fresh_database_schema_seven_contains_foreign_pressure_tables`: a fresh `Daemon` database must report metadata version `7`, contain exactly both foreign-pressure tables, have zero observation rows, and hold the exact `probe_failed` / `NOT_YET_SAMPLED` singleton seed.

- [ ] **Step 2: GREEN — version and tables travel together**

Bump `CURRENT_DATABASE_SCHEMA_VERSION` from 6 to 7 and create/seed both tables inside the existing migration transaction. Run the focused schema test with `-j 8` and `--test-threads=2`.

- [ ] **Step 3: Continue directly into Task 2B**

Do not add rollback or historical rollback-chain changes in this packet. Review schema 7 together with the classifier/provider packet after Task 2C.

---

### Task 2B: Pure classifier and read-only Windows census provider

**Files:**
- Modify: `runtime/ember-lab/src/lib.rs:8280-8420`
- Modify: `runtime/ember-lab/src/lib.rs:8673-8720`
- Modify: `runtime/ember-lab/Cargo.toml:14-28` only if the already enabled Windows feature set fails to expose a required API

**Interfaces:**
- Consumes: `ForeignProcessIdentity`, `ForeignProcessCensus`, existing `ProcessIdentity`, `inspect_handle`, `nvidia_smi_text`, and retained/persisted Job Object identities.
- Produces: `OwnedJobIdentity { job_id: String, job_object_name: String }`, live-only `ProcessCommitSample { pid: u32, process_start_token: String, private_commit_bytes: u64 }`, `ProcessExitObservation`, `ProcessReadFailure`, `ProcessIdentityConflict`, `HostCommitSample { commit_total_bytes: u64, commit_limit_bytes: u64, commit_remaining_bytes: u64, page_size_bytes: u64 }`, `trait ForeignProcessCensusProvider { fn sample(&self, owned_jobs: &[OwnedJobIdentity]) -> Result<ForeignProcessCensus>; }`, production `WindowsForeignProcessCensusProvider`, and `sample_foreign_process_census(provider, owned_jobs)`.

- [ ] **Step 1: Write failing parser and classifier tests**

```rust
#[test]
fn gpu_pid_below_commit_cutoff_is_named() {
    let processes = vec![ProcessCommitSample { pid: 77, process_start_token: "aa".into(), private_commit_bytes: GIB }];
    let gpu = BTreeMap::from([(77, 256 * 1024 * 1024)]);
    let host = HostCommitSample { commit_total_bytes: 44 * GIB, commit_limit_bytes: 64 * GIB, commit_remaining_bytes: 20 * GIB };
    let census = classify_foreign_samples(host, processes, &gpu, &BTreeSet::new()).unwrap();
    assert_eq!(census.named_foreign_processes[0].candidate_classes, vec!["gpu_compute"]);
}

#[test]
fn owned_job_member_is_excluded_from_aggregate_and_named_rows() {
    let processes = vec![ProcessCommitSample { pid: 88, process_start_token: "bb".into(), private_commit_bytes: 6 * GIB }];
    let host = HostCommitSample { commit_total_bytes: 44 * GIB, commit_limit_bytes: 64 * GIB, commit_remaining_bytes: 20 * GIB };
    let owned = BTreeSet::from([(88, "bb".to_string())]);
    let census = classify_foreign_samples(host, processes, &BTreeMap::new(), &owned).unwrap();
    assert_eq!(census.total_foreign_private_commit_bytes, 0);
    assert!(census.named_foreign_processes.is_empty());
}
```

Also add `many_subcutoff_foreign_processes_remain_visible_in_aggregate`, `foreign_private_commit_sum_overflow_fails_closed`, `exited_process_during_enumeration_keeps_census_complete`, `unreadable_live_process_makes_census_incomplete`, `named_process_exit_during_production_probe_is_recorded_and_dropped`, `named_pid_reuse_makes_census_incomplete`, and `foreign_process_open_mask_is_query_and_synchronize_only`.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib foreign_process_census -- --nocapture`

Expected: compile failure because the provider/classifier interfaces do not exist.

- [ ] **Step 3: Implement the pure classifier and production Windows probe**

Use exactly these API roles:

```rust
// Host fence counter
GetPerformanceInfo(&mut PERFORMANCE_INFORMATION, size);

// Full PID enumeration; grow the Vec until bytes_returned < capacity bytes.
K32EnumProcesses(pids.as_mut_ptr(), capacity_bytes, &mut bytes_returned);

// Query/read only: no PROCESS_TERMINATE, PROCESS_SUSPEND_RESUME,
// PROCESS_DUP_HANDLE, PROCESS_VM_WRITE, or PROCESS_ALL_ACCESS.
const FOREIGN_PROCESS_OPEN_ACCESS_MASK: u32 =
    PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_RIGHT;
OpenProcess(FOREIGN_PROCESS_OPEN_ACCESS_MASK, 0, pid);
GetProcessTimes(process, &mut creation, &mut exit, &mut kernel, &mut user);
K32GetProcessMemoryInfo(process, (&mut counters as *mut PROCESS_MEMORY_COUNTERS_EX).cast(), size);
IsProcessInJob(process, owned_job_handle, &mut is_member);
```

Reuse the existing NVIDIA command runner and parse `pid,used_gpu_memory` as a complete successful set. Exclude only PID 0 and PID 4 as explicit kernel pseudo-processes. `ERROR_INVALID_PARAMETER` (87) means exited; `ERROR_ACCESS_DENIED` (5) and every unrecognized code mean unreadable/incomplete. Exited identities produce `ProcessExitObservation`, never `ProcessCommitSample`. Sort named identities by `(pid, process_start_token)`.

After building the named set, re-open each named PID with the same constant mask. A production exit is recorded and dropped, a changed token fails as PID reuse, and a same-token live identity records survival. The integration fixture's exit remains a hard failure.

- [ ] **Step 4: Run unit tests and a real Windows read-only integration probe**

Run:

```text
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib foreign_process_census -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane foreign_process_census -- --nocapture
```

The integration test creates one harmless, hidden, no-window sentinel process, samples it, asserts that exact PID/creation-token fixture survives after sampling, then terminates only that test-owned child during teardown. The production probe separately rechecks every named identity observed at probe start; no pre-existing PID is hard-coded.

- [ ] **Step 5: Send Task 2 review packet to the review seat**

Include the exact Win32 access mask used, raw tests, source diff, file hashes, and explicit confirmation that no foreign handle requested control rights.

---

### Task 3: Monitor persistence and effective admission fence

**Files:**
- Modify: `runtime/ember-lab/src/lib.rs:2209-2230`
- Modify: `runtime/ember-lab/src/lib.rs:2670-2685`
- Modify: `runtime/ember-lab/src/lib.rs:4010-4060`
- Modify: `runtime/ember-lab/src/lib.rs:9543-9660`
- Modify: `domains/runtime/runtime/ember-lab/tests/control_plane.rs:1760-1840`

**Interfaces:**
- Consumes: `ForeignProcessCensusProvider::sample`, `persist_foreign_process_census`, and `foreign_process_pressure_status_from_connection`.
- Produces: `Daemon::foreign_process_pressure_status() -> Result<Value>` and one dispatch refusal `REFUSED_FOREIGN_PROCESS_PRESSURE` with both guard observations.

- [ ] **Step 1: Write failing admission and monitor tests**

Create a debug-only `Daemon::open_with_monitor_providers` seam that accepts deterministic headroom and census providers but is not reachable from RPC, manifest, run ID, or environment. Tests must assert:

```rust
assert_eq!(daemon.foreign_process_pressure_status().unwrap()["state"], "fenced");
let error = daemon.dispatch_manifest_bytes(&manifest).unwrap_err();
assert!(matches!(error, EmberLabError::ResourceAdmissionFrozen { .. }));
assert!(!argv_marker.exists());
assert!(!child_birth_marker.exists());
```

Add the sequence `fenced -> observed` on the first complete healthy census and assert `resource_guard_state` remains frozen. Add a probe-failure case that refuses admission.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane foreign_pressure -- --nocapture`

Expected: compile/assertion failure because the monitor does not sample or admit against the new state.

- [ ] **Step 3: Wire the provider into the existing resource-monitor tick**

On each existing tick, snapshot owned Job Object identities, sample the census, and persist it before constructing any protective-stop list. Census errors persist `probe_failed`; they do not terminate the monitor. Do not append pressure-fenced jobs to `job_ids` and do not call `protective_owned_stop` because of foreign state.

Add status output with `schema_version: ember-lab-foreign-process-pressure-state-v1`, current state, timestamp, observation, 2,000 ms cadence, and an `effective_admission` object naming both the sticky survival guard and pressure state.

- [ ] **Step 4: Add the dispatch preflight check**

Read both current singleton rows before argv construction. For `fenced` or `probe_failed`, write the existing exclusive preflight receipt path with:

```json
{
  "schema_version": "ember-lab-dispatch-preflight-v1",
  "result": "REFUSED_FOREIGN_PROCESS_PRESSURE",
  "resource_guard": {},
  "foreign_process_pressure": {}
}
```

Use the current row values, not caller selectors. `observed` and `clear` allow the pressure check to pass; the sticky survival guard can still refuse independently.

- [ ] **Step 5: Run GREEN and monitor lifecycle regression tests**

Run:

```text
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane foreign_pressure -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane resource_guard -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane protective_owned_stop -- --nocapture
```

Expected: all selected tests pass; no monitor thread survives `Daemon::drop`.

- [ ] **Step 6: Send Task 3 review packet to the review seat**

Report raw tests, exact refusal receipt contents/hash, DB transition rows, file hashes, and confirmation that the live owned-job stop list is unchanged by pressure state.

---

### Task 4: Probe receipt and custody verifier

**Files:**
- Modify: `runtime/ember-lab/src/lib.rs` near the existing resource-guard status/probe APIs
- Modify: `domains/runtime/runtime/ember-lab/tests/control_plane.rs` beside foreign-pressure integration tests

**Interfaces:**
- Consumes: the current pressure singleton and bounded observation ledger.
- Produces: `Daemon::foreign_process_pressure_probe_receipt(output: &Path) -> Result<ReceiptArtifact>` and internal `verify_foreign_process_pressure_probe_receipt(bytes: &[u8]) -> Result<Value>`.

- [ ] **Step 1: Write failing receipt/refusal tests**

Tests require one complete production-provider observation and assert schema, source/binary hashes, current state, exact observation JSON/hash, named identity survival assertions, total foreign commit, counter sources, `foreign_process_control:false`, canonical self hash, and exclusive-create no-overwrite behavior. Tampering one start token, aggregate byte, or self hash must refuse.

- [ ] **Step 2: Run receipt tests and confirm RED**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane foreign_pressure_probe_receipt -- --nocapture`

Expected: compile failure because the receipt API does not exist.

- [ ] **Step 3: Implement content-addressed receipt and exact verifier**

Use schema `ember-lab-foreign-process-pressure-probe-v1`, verdict `EXECUTED`, and `write_content_addressed_receipt` under `log_dir/foreign-process-pressure-probes`. The self hash is SHA-256 over canonical JSON with `receipt_sha256` omitted. The verifier checks exact keys, hashes, state/observation binding, sorted identity uniqueness, complete probe, positive survival assertions, aggregate arithmetic, counter-source strings, and false control authority.

- [ ] **Step 4: Run GREEN plus tamper/no-overwrite cases**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane foreign_pressure_probe_receipt -- --nocapture`

Expected: happy path and every named refusal pass.

- [ ] **Step 5: Send Task 4 immutable receipt review to the review seat**

Send the receipt path, raw file SHA-256, self hash, exact JSON content, stdout/stderr siblings if a live helper was used, and confirmation the sentinel remained alive at probe end.

---

### Task 5: Full sentinel verification and handoff

**Files:**
- Verify: `runtime/ember-lab/src/lib.rs`
- Verify: `runtime/ember-lab/Cargo.toml`
- Verify: `domains/runtime/runtime/ember-lab/tests/control_plane.rs`
- Verify: `docs/superpowers/specs/2026-08-25-issue898-foreign-pressure-sentinel-design.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: immutable integration packet for the foreign-pressure half of L7.

- [ ] **Step 1: Run formatting and focused verification**

```text
cargo fmt --manifest-path runtime/ember-lab/Cargo.toml --all -- --check
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib foreign_pressure -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib foreign_process_census -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane foreign_pressure -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane resource_guard -- --nocapture
```

- [ ] **Step 2: Run the complete Ember Lab suite**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --all-targets -- --nocapture`

Expected: zero failures. If A: disk budget cannot safely hold build artifacts, mail the integration owner for an approved hidden build root; do not redirect or delete foreign artifacts without authority.

- [ ] **Step 3: Audit forbidden authority and receipt claims**

Run:

```text
rg -n "PROCESS_TERMINATE|PROCESS_SUSPEND_RESUME|PROCESS_ALL_ACCESS|TerminateProcess|TerminateJobObject" runtime/ember-lab/src/lib.rs
rg -n "foreign_process_control|PrivateUsage|CommitTotal|CommitLimit|FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES" runtime/ember-lab/src/lib.rs
git diff --check
git status --short
```

Manually attribute every control-right match to an existing owned-only path and prove the census code has none.

- [ ] **Step 4: Produce and send the immutable integration packet**

Hash every changed file, include exact base/head/status, raw test outputs and receipt contents, and mail the review seat. Do not claim #898 complete: the owned-orphan companion plan and all later issue gates remain.
