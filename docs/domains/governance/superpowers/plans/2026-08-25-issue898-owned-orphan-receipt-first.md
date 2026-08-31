# Issue #898 L7 Owned-Orphan Receipt-First Reclamation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make startup-orphan cleanup terminate only an immediately reverified Ember Lab-owned Job Object after a durable content-addressed decision receipt exists.

**Architecture:** Replace `reclaim_starting_job`'s terminate-before-event ordering with a small owned-orphan decision/verification unit. Keep the exact state/lease fence held across receipt creation, perform a second identity and Job Object membership check immediately before termination, then commit terminal state and lease release.

**Tech Stack:** Rust 2021, `rusqlite`, `serde_json`, `windows-sys` Job Objects/process identity APIs, existing content-addressed receipt helpers and Windows integration tests.

**Spec:** `docs/superpowers/specs/2026-08-25-issue898-foreign-pressure-sentinel-design.md`

## Global Constraints

- Exact base is `b4084ac442a3f70c38f1bec0a0bd480512b7e145` plus the reviewed foreign-pressure plan changes.
- Only an exact persisted PID/creation token/executable identity that is a current member of the exact persisted named Ember Lab Job Object is controllable.
- Persist the decision receipt before termination and repeat identity/membership verification immediately before `TerminateJobObject`.
- Any PID reuse, missing Job Object, lost membership, lease/state change, or unreadable identity refuses termination and retains a fenced/uncertain record.
- Never fall back to image, path, name, parent PID, argv, or environment matching.
- Never control a pre-existing desktop process; integration tests create and own exact hidden/no-window fixtures.
- The integration owner holds Git/index/commit authority; send review packets and do not commit without explicit transfer.

---

### Task 1: Extract an exact owned-orphan verifier

**Files:**
- Modify: `domains/runtime/runtime/ember-lab/src/lib.rs:11299-11440`
- Modify: `domains/runtime/runtime/ember-lab/src/lib.rs:11521-11535`

**Interfaces:**
- Produces: `open_verified_owned_job(row: &JobProcessRow, rights: OwnedJobRights) -> Result<VerifiedOwnedJob>`, whose handles retain PID/start token/executable/Job Object membership; `OwnedJobRights::QueryOnly` and `OwnedJobRights::QueryAndTerminate`.
- Consumes: existing `inspect_handle`, `same_executable`, `IsProcessInJob`, `OpenJobObjectW`, and `OpenProcess`.

- [ ] **Step 1: Write failing unit tests for access masks and identity decisions**

Factor pure helpers so tests assert `QueryOnly` excludes terminate rights, `QueryAndTerminate` includes Job Object terminate rights only, and `owned_identity_matches` requires all of start token, executable identity, and membership.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib owned_orphan_identity -- --nocapture`

Expected: compile failure because the verifier and rights enum do not exist.

- [ ] **Step 3: Implement the verifier without changing behavior callers yet**

`open_verified_owned_job` must open the process with query/synchronize rights, open the named Job Object with query plus the explicitly requested Job Object rights, call `GetProcessTimes`/`inspect_handle`, call `IsProcessInJob`, and return owned handles only when every persisted field matches. It must map missing/mismatched identity to `ProcessControlUncertain`, never to dead/clean.

- [ ] **Step 4: Run GREEN and existing process-identity tests**

Run:

```text
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --lib owned_orphan_identity -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane identity_conflict -- --nocapture
```

- [ ] **Step 5: Send Task 1 review packet to the review seat**

Include access masks, diff, hashes, and raw tests.

---

### Task 2: Receipt-before-termination state machine

**Files:**
- Modify: `domains/runtime/runtime/ember-lab/src/lib.rs:6999-7044`
- Modify: `domains/runtime/runtime/ember-lab/src/lib.rs:11521-11643`
- Modify: `domains/runtime/runtime/ember-lab/tests/control_plane.rs` beside reconciliation tests

**Interfaces:**
- Consumes: `open_verified_owned_job`, `write_content_addressed_receipt`, `job_process_row_from_connection`, and exact lease/state SQL fences.
- Produces: `reclaim_starting_job` returning `Result<ReceiptArtifact>` and schema `ember-lab-owned-orphan-termination-v1`.

- [ ] **Step 1: Write failing real Windows ordering tests**

Create a test-owned suspended/no-window process inside a named Job Object and a `starting` row with its exact identity. Instrument a test-only termination hook that records the receipt path at the instant before the real `TerminateJobObject` call. Assert:

```rust
assert!(receipt_path.is_file());
assert_eq!(hash_file(&receipt_path).unwrap(), artifact.sha256);
assert_eq!(second_verification.pid, original.pid);
assert_eq!(second_verification.start_token, original.start_token);
assert!(second_verification.job_object_membership_verified);
```

Add separate tests that swap the persisted token, remove membership, and change the lease epoch. Each must return uncertainty/refusal while the test-owned process remains alive.

- [ ] **Step 2: Run reconciliation tests and confirm RED**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane reclaim_starting_job -- --nocapture`

Expected: ordering assertion fails because current code calls `terminate_job_object_by_name` before durable receipt creation.

- [ ] **Step 3: Implement the fenced decision transaction and receipt**

First transaction:

```sql
UPDATE jobs SET updated_at_ms=?
WHERE job_id=? AND state='starting' AND lease_epoch=?
AND EXISTS(SELECT 1 FROM leases WHERE resource=jobs.resource
  AND owner_job_id=jobs.job_id AND lease_epoch=jobs.lease_epoch);
```

Perform query-only verification, then create a content-addressed receipt under
`log_dir/owned-orphan-terminations`. The JSON binds schema/result/reason, job ID,
state, resource and lease epoch, Job Object name, PID, start token, executable
identity SHA-256, membership result, first verification timestamp, intended
exact-Job-Object action, `foreign_process_control:false`, and
`decision_receipt_persisted_before_termination:true`.

- [ ] **Step 4: Implement immediate second verification and exact termination**

Open fresh process and Job Object handles with `QueryAndTerminate`, repeat exact identity and membership checks, and call `TerminateJobObject` through those verified retained handles—never by reopening from image/path/name selection. Wait for the exact process and Job Object active count to reach terminal.

Then in one immediate transaction require the same `starting` state and lease epoch, mark `failed`, release exactly that lease, and record a completion event containing the receipt path/hash and both verification timestamps. If post-receipt verification fails, record an uncertainty event that binds the receipt but do not terminate or release the lease.

- [ ] **Step 5: Run GREEN plus PID-reuse/lost-membership refusals**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane reclaim_starting_job -- --nocapture`

Expected: receipt exists before the action hook; exact-owned path terminates; every conflict leaves the process alive.

- [ ] **Step 6: Send Task 2 receipt-first packet to the review seat**

Include one exact decision receipt's raw/self hashes and JSON, event rows, process terminal evidence for the owned fixture, survival evidence for every exact refusal fixture, raw tests, source hashes, and status.

---

### Task 3: Reconciliation regression and immutable handoff

**Files:**
- Verify: `domains/runtime/runtime/ember-lab/src/lib.rs`
- Verify: `domains/runtime/runtime/ember-lab/tests/control_plane.rs`
- Verify: `docs/superpowers/specs/2026-08-25-issue898-foreign-pressure-sentinel-design.md`

**Interfaces:**
- Consumes: Tasks 1–2 and the foreign-pressure plan.
- Produces: complete L7 immutable review packet to the review seat.

- [ ] **Step 1: Run focused and adjacent tests**

```text
cargo fmt --manifest-path runtime/ember-lab/Cargo.toml --all -- --check
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane reclaim_starting_job -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane protective_owned_stop -- --nocapture
cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --test control_plane reconcile -- --nocapture
```

- [ ] **Step 2: Run the full crate suite**

Run: `cargo test -j 8 --manifest-path runtime/ember-lab/Cargo.toml --all-targets -- --nocapture`

Expected: zero failures and no detached process or monitor remains.

- [ ] **Step 3: Audit termination authority**

Run:

```text
rg -n "terminate_job_object_by_name|TerminateJobObject|TerminateProcess|PROCESS_TERMINATE" domains/runtime/runtime/ember-lab/src/lib.rs
git diff --check
git status --short
```

Every remaining termination call must consume an exact owned handle or be an
existing pre-birth cleanup of a child created by the same call. The old
terminate-by-name startup path must be absent.

- [ ] **Step 4: Send complete L7 packet to the review seat**

Mail exact base/head/status, all changed-file hashes, focused/full raw test
outputs, receipt raw/self hashes/content, exact test-fixture survival evidence, and a
claim boundary: L7 source/probe evidence is ready for independent review but
#898 is not complete until independent review, required checks, integration, merge,
and remaining issue gates are terminal.
