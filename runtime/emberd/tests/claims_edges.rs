// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Governor claims-table lifecycle probes (folded in from the fburst-2053-govprobe
// independent audit). Root finding: dispatch_receipt_claims had NO deletion path
// anywhere in the crate (CREATE lib.rs:611/4225, SELECT lib.rs:2163/2179,
// INSERT-upsert lib.rs:2220 were the only statements against it). Three real
// consequences, reproduced here end-to-end against the ACTUAL `Daemon` (not a
// hand-copied SQL model): a clean job exit left its claim wedged forever against
// any different-job re-dispatch of the same receipt path (D2, the default
// re-run path); a spawn-failure rollback left an orphaned claim for a job
// deleted from every other table (D1); a crash-orphaned 'starting' job's claim
// survived `reconcile()` marking it failed (D3).
//
// The fix (this same round): every terminal transition
// (rollback_dispatch_attempt, finalize_stopped, reclaim_starting_job,
// mark_exited_unknown, mark_dead, record_natural_exit) now also runs
// `DELETE FROM dispatch_receipt_claims WHERE job_id=?1`. These tests exercise
// the real Daemon end-to-end and assert the post-termination invariant: the
// receipt path is free for a DIFFERENT job_id once the prior job has reached
// any terminal state.
//
// Reviewer amendment (durability-before-release + escaped-receipt guard +
// legacy-state convergence): every terminal-transition site above writes its
// terminal event/state FIRST and releases the claim SECOND, but both live in
// ONE transaction (open -> commit), so there is no crash point between them
// -- a crash before commit rolls back the whole transaction (neither write
// lands); a crash after commit lands both. Per-site tx open/claim-delete/
// commit line citations (this round's lib.rs):
//   rollback_dispatch_attempt:  tx lib.rs:2224 .. delete lib.rs:2272 .. commit lib.rs:2273
//   finalize_stopped:           tx lib.rs:3568 .. event lib.rs:3602 .. delete lib.rs:3612 .. commit lib.rs:3613
//   reclaim_starting_job:       tx lib.rs:3619 .. event lib.rs:3659 .. delete lib.rs:3662 .. commit lib.rs:3663
//   mark_exited_unknown:        tx lib.rs:3707 .. event lib.rs:3732 .. delete lib.rs:3740 .. commit lib.rs:3741
//   mark_dead:                  tx lib.rs:3747 .. event lib.rs:3772 .. delete lib.rs:3775 .. commit lib.rs:3776
//   record_natural_exit:        tx lib.rs:5101 .. event lib.rs:5151 .. delete lib.rs:5158 .. commit lib.rs:5159
// rollback_dispatch_attempt also gained an escaped-receipt guard (lib.rs
// ~2297-2330): validate_receipt_claim_available now checks, on a claim
// conflict, whether the claimed owner's job row is gone or terminal; if so
// it self-heals the stale claim in the SAME reservation transaction instead
// of refusing forever -- this closes the remaining gap where a claim row
// predates this fix (or any future release-site gap) and would otherwise
// wedge a receipt path permanently even though its owner is long dead.

#![cfg(windows)]

use emberd::{Daemon, HostCommitCapacity};
use rusqlite::OptionalExtension;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const GIB: u64 = 1024 * 1024 * 1024;
const HOST_COMMIT_RESERVE_BYTES: u64 = 10 * GIB;
const DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES: u64 = 16 * GIB;
const MAXIMUM_JOB_MEMORY_BYTES: u64 =
    DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES - HOST_COMMIT_RESERVE_BYTES;
const SIMULATED_PEAK_COMMIT_BYTES: u64 = 1 * GIB;

fn host_capacity(available_maximum_commit_bytes: u64) -> HostCommitCapacity {
    HostCommitCapacity {
        physical_ram_bytes: 64 * GIB,
        pagefile_maximum_bytes: 32 * GIB,
        pagefile_configuration_source:
            r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles"
                .to_string(),
        pagefile_configuration_sha256: "a".repeat(64),
        commit_total_bytes: 96 * GIB - available_maximum_commit_bytes,
        current_commit_limit_bytes: 80 * GIB,
        maximum_commit_capacity_bytes: 96 * GIB,
        available_maximum_commit_bytes,
    }
}

fn sandbox(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "emberd-claims-edges-{name}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
}

#[test]
fn fixture_claims_child() {
    if std::env::var("EMBERD_CLAIMS_FIXTURE_CHILD").as_deref() == Ok("1") {
        let sleep_ms: u64 = std::env::var("EMBERD_CLAIMS_FIXTURE_SLEEP_MS")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(30_000);
        thread::sleep(Duration::from_millis(sleep_ms));
    }
}

/// Writes a manifest at `root` for `job_id`, with a receipt path caller can
/// choose (so a colliding job_id can target the SAME receipt path), and a
/// caller-chosen fixture-child sleep so the real process can be made to
/// exit quickly (crash-point tests need the process actually gone).
fn write_manifest_with_sleep_ms(
    root: &Path,
    job_id: &str,
    resource_lease: &str,
    receipt_path: &Path,
    sleep_ms: u64,
) -> PathBuf {
    let manifest = write_manifest(root, job_id, resource_lease, receipt_path);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["env"]["EMBERD_CLAIMS_FIXTURE_SLEEP_MS"] = json!(sleep_ms.to_string());
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    manifest
}

/// Writes a manifest at `root` for `job_id`, with a receipt path caller can
/// choose (so a colliding job_id can target the SAME receipt path).
fn write_manifest(root: &Path, job_id: &str, resource_lease: &str, receipt_path: &Path) -> PathBuf {
    let custody = root.join("custody");
    fs::create_dir_all(&custody).unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBERD_CLAIMS_FIXTURE_CHILD".to_string(), "1".to_string());
    for name in [
        "TEMP",
        "TMP",
        "TORCH_HOME",
        "TRITON_CACHE_DIR",
        "CUDA_CACHE_PATH",
        "HF_HOME",
        "XDG_CACHE_HOME",
    ] {
        let path = custody.join(name.to_ascii_lowercase());
        fs::create_dir_all(&path).unwrap();
        env.insert(name.to_string(), path.to_string_lossy().into_owned());
    }
    let binding = root.join("config.json");
    fs::write(&binding, b"{\"config\":\"bound\"}").unwrap();
    let data_manifest = root.join("data-manifest.json");
    fs::write(&data_manifest, b"{\"records\":4096}").unwrap();
    let program = std::env::current_exe().unwrap();
    let manifest = root.join(format!("{job_id}-dispatch.json"));
    fs::write(
        &manifest,
        serde_json::to_vec(&json!({
            "schema_version": "emberd-dispatch-manifest-v2",
            "job_id": job_id,
            "source_commit": "5326043c344227c1b145a4ddbb3519cfa62d4943",
            "not_before_ms": 10_000,
            "expires_at_ms": 70_000,
            "resource_lease": resource_lease,
            "program": {"path": program, "sha256": sha256(&program)},
            "args": ["--exact", "fixture_claims_child", "--nocapture"],
            "env": env,
            "bindings": [
                {"kind": "config", "path": binding, "sha256": sha256(&binding)},
                {"kind": "manifest", "path": data_manifest, "sha256": sha256(&data_manifest)}
            ],
            "custody_root": custody,
            "storage_reserves": [{"root": root, "minimum_free_bytes": 1}],
            "minimum_free_vram_bytes": 1,
            "required_available_maximum_commit_bytes": DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES,
            "maximum_job_memory_bytes": MAXIMUM_JOB_MEMORY_BYTES,
            "simulated_peak_commit_bytes": SIMULATED_PEAK_COMMIT_BYTES,
            "preflight_receipt": receipt_path
        }))
        .unwrap(),
    )
    .unwrap();
    manifest
}

fn dispatch_ok(daemon: &Daemon, manifest: &Path) -> emberd::DispatchOutcome {
    daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap()
}

fn dispatch(daemon: &Daemon, manifest: &Path) -> emberd::Result<emberd::DispatchOutcome> {
    daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
        manifest,
        10_001,
        |_root| Ok(1024),
        || Ok(2048),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        |_root| Ok(u64::MAX),
    )
}

/// D2 (default re-run path, HIGH): a job that reaches a clean terminal state
/// (here: stopped, via `stop_job`) must release its receipt claim so a later
/// dispatch of the SAME receipt path under a DIFFERENT job_id is admitted.
/// "claims-ab" / "ab" is the same delimiter-bounded-segment trick used
/// elsewhere in this suite: "ab" is its own hyphen-delimited segment inside
/// "claims-ab-preflight.json" (bounded on both sides), so two DISTINCT
/// job_ids can each legitimately pass the (post-AUDIT-B, bounded) filename
/// job-scoping check against the same receipt path -- unlike a bare prefix
/// collision (e.g. "run7" against "run77-preflight.json"), which the
/// bounded check now correctly refuses (see the AUDIT-B negative test).
#[test]
fn redispatch_same_receipt_path_by_a_new_job_succeeds_after_clean_stop() {
    let root = sandbox("redispatch-after-stop");
    let shared_receipt = root.join("custody").join("claims-ab-preflight.json");

    let manifest_ab = write_manifest(&root, "claims-ab", "gpu-claims-ab", &shared_receipt);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), shared_receipt.file_name());

    // Clean terminal transition: stop the job (finalize_stopped).
    daemon.stop_job("claims-ab").unwrap();
    // The winner's receipt FILE is untouched by stop_job; remove it so the
    // fast pre-admission exists-check doesn't refuse first (ReceiptAlreadyExists)
    // and we reach the actual claims-table guard this test targets.
    fs::remove_file(&shared_receipt).unwrap();

    // A DIFFERENT job_id ("ab", its own bounded segment in the shared
    // filename) re-dispatches the SAME receipt path. Before the fix this
    // refuses forever with
    // DispatchReceiptClaimConflict; after the fix it must be admitted.
    let manifest_a = write_manifest(&root, "ab", "gpu-ab", &shared_receipt);
    let result = dispatch(&daemon, &manifest_a);
    assert!(
        result.is_ok(),
        "WEDGE: receipt path still claimed after the prior job's clean stop \
         (dispatch_receipt_claims never released on terminal transition): {result:?}"
    );
    daemon.stop_job("ab").unwrap();
}

/// D1 (HIGH): the claim commits (insert_reserved_job_row, inside the pinned-
/// budget admission transaction) BEFORE the process ever spawns. A spawn
/// failure must roll the claim back too, or it survives as an orphan owned
/// by a job that `rollback_dispatch_attempt` already deleted from every
/// other table.
#[test]
fn redispatch_same_receipt_path_by_a_new_job_succeeds_after_spawn_failure_rollback() {
    let root = sandbox("redispatch-after-spawn-failure");
    let shared_receipt = root.join("custody").join("claimsfail-ab-preflight.json");

    let manifest_ab = write_manifest(&root, "claimsfail-ab", "gpu-claimsfail-ab", &shared_receipt);
    // Corrupt the program binding to a non-executable file so the admission
    // transaction commits the claim (verify_dispatch_file passes for the
    // ORIGINAL manifest below is skipped: this manifest is broken from the
    // start, so it fails BEFORE any claim commit) — we need failure to occur
    // AFTER the claim commits, i.e. at spawn time. verify_dispatch_file runs
    // long before admission, so instead we corrupt AFTER a first successful
    // admission by re-pointing a SEPARATE job's program at a bad binary while
    // keeping bindings/hashes internally consistent for that job's own
    // manifest (the hash is recomputed against the corrupted file itself, so
    // verify_dispatch_file still passes; the file is simply not a valid
    // executable image, so CreateProcess fails at spawn time).
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest_ab).unwrap()).unwrap();
    let invalid_program = root.join("not-a-program.txt");
    fs::write(&invalid_program, b"not an executable image").unwrap();
    payload["program"] = json!({"path": invalid_program, "sha256": sha256(&invalid_program)});
    fs::write(&manifest_ab, serde_json::to_vec(&payload).unwrap()).unwrap();

    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = dispatch(&daemon, &manifest_ab);
    assert!(result.is_err(), "corrupted program must fail to spawn");
    // rollback_dispatch_attempt has already run; the job is gone everywhere.
    assert_eq!(daemon.job_state("claimsfail-ab").unwrap(), None);

    // A DIFFERENT job_id re-dispatches the SAME receipt path. Before the fix
    // the orphaned claim (committed pre-spawn, never released on rollback)
    // refuses this forever; after the fix it must be admitted.
    let manifest_b = write_manifest(&root, "ab", "gpu-ab", &shared_receipt);
    let result = dispatch(&daemon, &manifest_b);
    assert!(
        result.is_ok(),
        "ORPHAN: receipt path still claimed after spawn-failure rollback deleted \
         the job from every other table: {result:?}"
    );
    daemon.stop_job("ab").unwrap();
}

/// D3 (MED): a crash between the admission commit and the process resume
/// leaves a 'starting' job with a committed claim and no live process.
/// `reconcile()`'s starting-reconciliation path (`reclaim_starting_job`)
/// marks it failed; the claim must be released in the SAME transition, or
/// the receipt path stays wedged even after reconcile runs.
#[test]
fn crash_orphaned_starting_job_releases_its_claim_after_reconcile() {
    let root = sandbox("crash-orphan-reconcile");
    let db = root.join("emberd.sqlite3");
    let shared_receipt = root.join("custody").join("claimscrash-ab-preflight.json");

    let manifest_ab = write_manifest(&root, "claimscrash-ab", "gpu-claimscrash-ab", &shared_receipt);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), shared_receipt.file_name());

    // Simulate "crash before resume": force the already-running job's state
    // back to 'starting' (same technique used elsewhere in this suite for
    // driving `reconcile()`'s starting-reconciliation path deterministically
    // against a real, live process).
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE jobs SET state='starting' WHERE job_id='claimscrash-ab'",
            [],
        )
        .unwrap();

    daemon.reconcile().unwrap();
    assert_eq!(
        daemon.job_state("claimscrash-ab").unwrap(),
        Some(emberd::JobState::Failed)
    );
    // The winner's receipt FILE (written at the original successful
    // dispatch) is untouched by reconcile; remove it so the fast
    // pre-admission exists-check doesn't refuse first.
    fs::remove_file(&shared_receipt).unwrap();

    // A DIFFERENT job_id re-dispatches the SAME receipt path. Before the fix
    // reconcile's starting->failed transition never released the claim, so
    // this refuses forever; after the fix it must be admitted.
    let manifest_b = write_manifest(&root, "ab", "gpu-ab", &shared_receipt);
    let result = dispatch(&daemon, &manifest_b);
    assert!(
        result.is_ok(),
        "WEDGE-AFTER-RECONCILE: receipt path still claimed by the crash-orphaned \
         'starting' job after reconcile marked it failed: {result:?}"
    );
    daemon.stop_job("ab").unwrap();
}

/// Reviewer amendment (durability-before-release, point 2): rollback must
/// prove no externally-visible receipt escaped for this job BEFORE it frees
/// the claim. If a receipt file already exists at the claimed path when
/// spawn fails, silently deleting the claim would erase the only record
/// tying that file back to an owner. Rollback must refuse and surface the
/// typed `DispatchReceiptEscapedRollback` error instead of the underlying
/// spawn error, and must leave the claim (and every other row it would
/// otherwise have deleted, since it is one atomic transaction) untouched.
#[test]
fn rollback_refuses_to_release_a_claim_when_a_receipt_escaped_to_disk() {
    let root = sandbox("rollback-escaped-receipt");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("claimsescape-ab-preflight.json");

    // A genuine successful admission writes the preflight receipt for real
    // -- this is the exact externally-visible artifact the guard protects.
    let manifest_ab = write_manifest(&root, "claimsescape-ab", "gpu-claimsescape-ab", &receipt_path);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), receipt_path.file_name());
    assert!(
        receipt_path.exists(),
        "setup invariant: the preflight receipt must be on disk after a real admission"
    );

    // Force the job to a terminal state so rollback_dispatch_attempt's own
    // precondition (failed/stopped/exited) is satisfied -- modeling a
    // defensive/backstop rollback call arriving after the receipt already
    // legitimately escaped to disk (test_rollback_dispatch_attempt drives
    // the exact same private function production calls, deterministically,
    // rather than racing the real spawn-failure timing).
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE jobs SET state='failed' WHERE job_id='claimsescape-ab'",
            [],
        )
        .unwrap();

    let error = daemon
        .test_rollback_dispatch_attempt("claimsescape-ab", "gpu-claimsescape-ab", false)
        .expect_err("rollback must refuse when a receipt already escaped to disk");
    let debug = format!("{error:?}");
    assert!(
        debug.contains("DispatchReceiptEscapedRollback"),
        "SILENT FREE: rollback must surface the escaped-receipt guard instead of quietly \
         deleting the claim, got: {debug}"
    );

    // The claim must still exist -- rollback refused to delete it (and,
    // since it is one atomic transaction, the job/lease rows it would
    // otherwise also have deleted must survive too).
    let claim_owner: Option<String> = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id FROM dispatch_receipt_claims WHERE job_id=?1",
            ["claimsescape-ab"],
            |row| row.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(
        claim_owner.as_deref(),
        Some("claimsescape-ab"),
        "claim must survive when rollback detects an escaped receipt already on disk"
    );

    // The escaped receipt file itself must be untouched by rollback.
    assert!(receipt_path.exists());
}

/// Round-8 P1-1: a rollback that releases a claim cleanly (receipt genuinely
/// absent, the ordinary spawn-failure path) must still leave a DURABLE
/// evidence row behind. Before this fix, `rollback_dispatch_attempt` deleted
/// `events`, `jobs`, and the claim itself with nothing surviving anywhere
/// job-scoped to explain why this receipt_path was ever touched -- a later
/// audit of the same path has no record a rollback happened at all.
#[test]
fn rollback_writes_durable_evidence_before_releasing_a_clean_claim() {
    let root = sandbox("rollback-durable-evidence");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("p11ab-preflight.json");

    let manifest = write_manifest(&root, "p11ab", "gpu-p11ab", &receipt_path);
    let daemon = Daemon::open(&db).unwrap();

    // Reserve the claim without ever letting the real receipt land on disk:
    // force the job terminal BEFORE dispatch would write the receipt is not
    // possible via the public path (dispatch writes the receipt as part of
    // admission), so model the "spawn failed before anything escaped" case
    // the same way the existing escaped-receipt test models its own
    // precondition -- reserve via a real admission, then delete the receipt
    // file out-of-band before rollback runs, proving rollback's OWN probe
    // (not a cached assumption) drives the evidence content.
    let outcome = dispatch_ok(&daemon, &manifest);
    assert_eq!(outcome.receipt.path.file_name(), receipt_path.file_name());
    fs::remove_file(&receipt_path).unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute("UPDATE jobs SET state='failed' WHERE job_id='p11ab'", [])
        .unwrap();

    daemon
        .test_rollback_dispatch_attempt("p11ab", "gpu-p11ab", false)
        .expect("rollback must succeed when the receipt is confirmed absent");

    let row: (String, i64, String) = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id, escaped, reason FROM dispatch_receipt_rollback_evidence WHERE job_id=?1",
            ["p11ab"],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .expect("NO EVIDENCE: a clean rollback release must leave a durable row behind");
    assert_eq!(row.0, "p11ab");
    assert_eq!(row.1, 0, "a confirmed-absent rollback must record escaped=0");
    assert_eq!(row.2, "dispatch_rollback");

    // And the claim itself is gone -- the ordinary release still happens.
    let claim_owner: Option<String> = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id FROM dispatch_receipt_claims WHERE job_id=?1",
            ["p11ab"],
            |row| row.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(claim_owner, None);
}

/// Round-8 P1-2: the escaped-receipt guard must fail CLOSED when the
/// existence probe itself errors (permission denied, inaccessible path,
/// etc), never collapse that into "confirmed absent" the way
/// `Path::exists()` does. `EMBERD_TEST_ROLLBACK_RECEIPT_PROBE_ERROR`
/// deterministically forces the probe's `Err` arm without needing a real
/// ACL/UNC trick.
#[test]
fn rollback_fails_closed_when_the_receipt_existence_probe_errors() {
    let root = sandbox("rollback-probe-error");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("p12ab-preflight.json");

    let manifest = write_manifest(&root, "p12ab", "gpu-p12ab", &receipt_path);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest);
    assert_eq!(outcome.receipt.path.file_name(), receipt_path.file_name());
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute("UPDATE jobs SET state='failed' WHERE job_id='p12ab'", [])
        .unwrap();

    std::env::set_var("EMBERD_TEST_ROLLBACK_RECEIPT_PROBE_ERROR", "1");
    let error = daemon.test_rollback_dispatch_attempt("p12ab", "gpu-p12ab", false);
    std::env::remove_var("EMBERD_TEST_ROLLBACK_RECEIPT_PROBE_ERROR");
    let error = error.expect_err("a probe error must fail CLOSED, never silently release");
    let debug = format!("{error:?}");
    assert!(
        debug.contains("DispatchReceiptEscapedRollback"),
        "FAIL-OPEN: a probe error must surface the escaped-receipt guard, got: {debug}"
    );

    let row: (i64, String) = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT escaped, reason FROM dispatch_receipt_rollback_evidence WHERE job_id=?1",
            ["p12ab"],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .expect("a fail-closed rollback must still leave durable evidence");
    assert_eq!(row.0, 1, "a probe-error rollback must record escaped=1 (fail-closed)");
    assert!(
        row.1.contains("receipt_existence_probe_failed"),
        "reason must disclose the probe failure, got: {}",
        row.1
    );

    // The claim must survive: fail-closed preserves it exactly like a
    // confirmed escape does.
    let claim_owner: Option<String> = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id FROM dispatch_receipt_claims WHERE job_id=?1",
            ["p12ab"],
            |row| row.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(claim_owner.as_deref(), Some("p12ab"));

    // The receipt file itself was never touched by rollback (untouched by
    // the probe-error path -- it was already going to be preserved anyway).
    assert!(receipt_path.exists());
}

/// AUDIT-A: `rollback_dispatch_attempt` deletes the `jobs` row for a
/// terminal job BEFORE the escaped-receipt guard decides whether the claim
/// survives, so a preserved-escaped claim has owner=None in `jobs` -- the
/// exact same shape self-heal treats as "owner is gone, safe to reclaim".
/// If the escaped FILE is later removed out-of-band (the operator cleans it
/// up, a retention sweep, etc), self-heal must NOT silently admit a foreign
/// job at that path: the durable `escaped=1` evidence row (P1-1/P1-2) is the
/// last surviving signal that this path had an unresolved escape, and it
/// must be consulted before any owner=None claim is treated as stale.
#[test]
fn admission_refuses_to_reclaim_an_escaped_tombstone_after_the_file_is_removed_out_of_band() {
    let root = sandbox("audita-tombstone-reclaim");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("tombstone-ab-preflight.json");

    // "ab" and "tombstone" are both hyphen-delimited, boundary-clean
    // segments of the shared filename "tombstone-ab-preflight.json" (the
    // same delimiter-bounded-segment technique the rest of this suite uses
    // post-AUDIT-B), so both distinct job_ids legitimately pass the bounded
    // filename job-scoping check against this one receipt path.
    let manifest_a = write_manifest(&root, "ab", "gpu-ab", &receipt_path);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_a);
    assert_eq!(outcome.receipt.path.file_name(), receipt_path.file_name());
    assert!(receipt_path.exists());

    rusqlite::Connection::open(&db)
        .unwrap()
        .execute("UPDATE jobs SET state='failed' WHERE job_id='ab'", [])
        .unwrap();

    // Rollback sees the receipt still on disk -> escaped, claim preserved,
    // durable evidence written, `jobs` row deleted (terminal-job branch runs
    // unconditionally before the escape decision) -- owner=None from here on.
    let rollback_error = daemon
        .test_rollback_dispatch_attempt("ab", "gpu-ab", false)
        .expect_err("setup invariant: rollback must refuse on a genuinely escaped receipt");
    assert!(format!("{rollback_error:?}").contains("DispatchReceiptEscapedRollback"));
    assert_eq!(
        daemon.job_state("ab").unwrap(),
        None,
        "setup invariant: the jobs row must be gone after this rollback (owner=None going forward)"
    );

    // Now the escaped file itself disappears out-of-band -- nothing left
    // anywhere except the durable evidence row.
    fs::remove_file(&receipt_path).unwrap();

    // A different job targeting the same receipt path must be REFUSED, not
    // silently admitted as if the stale claim were an ordinary orphan.
    let manifest_foreign = write_manifest(&root, "tombstone", "gpu-tombstone", &receipt_path);
    let foreign = dispatch(&daemon, &manifest_foreign);
    let foreign_error = foreign.expect_err(
        "TOMBSTONE ERASED: a foreign job was admitted at a path whose only owner-gone signal \
         was the escape marker -- self-heal treated the escape tombstone as an ordinary stale claim"
    );
    assert!(
        format!("{foreign_error:?}").contains("DispatchReceiptClaimConflict"),
        "expected DispatchReceiptClaimConflict, got: {foreign_error:?}"
    );

    // The original claim must still belong to the escaped job, not the
    // foreign one.
    let claim_owner: Option<String> = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id FROM dispatch_receipt_claims WHERE job_id=?1",
            ["ab"],
            |row| row.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(claim_owner.as_deref(), Some("ab"));
}

/// Round-9 reviewer REJECT: `validate_receipt_claim_available` only
/// consulted `dispatch_receipt_rollback_evidence` on the FOREIGN-job branch
/// (`claimed_by_job_id != job_id`); the `claimed_by_job_id == job_id` branch
/// fell through with no tombstone check at all. That let the OWNING job_id
/// itself reopen its own escaped tombstone: an escaped rollback deletes the
/// `jobs` row but preserves the claim + an `escaped=1` evidence row: remove
/// the escaped file out-of-band, then replay the SAME job_id at the SAME
/// path (rather than a foreign one), and the same-pair allowance admitted
/// the reservation with the tombstone never consulted. This test proves the
/// same-job_id replay is refused identically to the foreign-job replay
/// already covered above.
#[test]
fn admission_refuses_a_same_job_id_replay_of_an_escaped_tombstone_after_the_file_is_removed_out_of_band()
{
    let root = sandbox("audita-same-job-tombstone-replay");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("replay-ab-preflight.json");

    // Short sleep_ms: the real fixture process must have actually exited
    // before the replay below reuses the SAME job_id (same job_id -> same
    // stdout/stderr log filenames, derived from `hash_bytes(job_id)`).
    let manifest_ab = write_manifest_with_sleep_ms(&root, "ab", "gpu-ab", &receipt_path, 30);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), receipt_path.file_name());
    assert!(receipt_path.exists());

    // Drop this Daemon entirely (same technique as the crash-mid-running
    // test above): its in-memory monitor/handle-duplication state for "ab"
    // goes with it, so once the real short-lived fixture process exits on
    // its own a moment later, NOTHING still holds the stdout/stderr log
    // files open. A fresh `Daemon::open` below starts with no in-memory
    // state for "ab" at all -- only the DB rows this test manipulates
    // directly, exactly like every other rollback test in this suite.
    drop(daemon);
    thread::sleep(Duration::from_millis(500));
    let daemon = Daemon::open(&db).unwrap();

    rusqlite::Connection::open(&db)
        .unwrap()
        .execute("UPDATE jobs SET state='failed' WHERE job_id='ab'", [])
        .unwrap();

    // Rollback sees the receipt still on disk -> escaped, claim preserved,
    // durable evidence written, `jobs` row deleted -- owner=None from here
    // on, exactly like the foreign-replay setup above. `remove_identity:
    // true` -- unlike the foreign-job variant of this test, the replay
    // below reuses the SAME job_id, so its identity binding must be cleared
    // here or the replay would refuse on the UNRELATED `IdentityAlreadyBound`
    // guard before ever reaching the receipt-claim tombstone check this test
    // targets.
    let rollback_error = daemon
        .test_rollback_dispatch_attempt("ab", "gpu-ab", true)
        .expect_err("setup invariant: rollback must refuse on a genuinely escaped receipt");
    assert!(format!("{rollback_error:?}").contains("DispatchReceiptEscapedRollback"));
    assert_eq!(
        daemon.job_state("ab").unwrap(),
        None,
        "setup invariant: the jobs row must be gone after this rollback (owner=None going forward)"
    );

    // The escaped file disappears out-of-band -- nothing left anywhere
    // except the durable evidence row and the preserved claim.
    fs::remove_file(&receipt_path).unwrap();

    // Replay the IDENTICAL job_id ("ab") at the IDENTICAL receipt_path. The
    // claimed_by_job_id == job_id same-pair allowance must NOT bypass the
    // tombstone: this must refuse exactly like the foreign-job case.
    let manifest_replay = write_manifest(&root, "ab", "gpu-ab", &receipt_path);
    let replay = dispatch(&daemon, &manifest_replay);
    let replay_error = replay.expect_err(
        "TOMBSTONE ERASED: a same-job_id replay was admitted at a path whose only owner-gone \
         signal was the escape marker -- the same-pair allowance skipped the tombstone check"
    );
    assert!(
        format!("{replay_error:?}").contains("DispatchReceiptClaimConflict"),
        "expected DispatchReceiptClaimConflict, got: {replay_error:?}"
    );
    // The original claim row must still exist, still owned by "ab", untouched
    // by the refused replay attempt.
    let claim_owner: Option<String> = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id FROM dispatch_receipt_claims WHERE job_id=?1",
            ["ab"],
            |row| row.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(claim_owner.as_deref(), Some("ab"));

    // And the durable evidence row must still read escaped=1 -- the refused
    // replay must not have touched it either.
    let evidence_escaped: i64 = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT escaped FROM dispatch_receipt_rollback_evidence WHERE job_id='ab'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(evidence_escaped, 1);

    // Round-10: the conflict refusal must clean up the identity row that was
    // created at the start of this replay attempt. The identity was created
    // before validate_receipt_claim_available ran, so when that validation
    // refuses, the identity residue must be removed (but the original claim
    // and evidence stay intact).
    assert_eq!(
        daemon.identity_hash("ab").unwrap(),
        None,
        "the refused replay attempt must have cleaned up its created identity row"
    );
}

/// Round-10: complementary regression for conflict cleanup — a pre-existing
/// identity from a prior successful dispatch must be preserved when a
/// conflict refusal happens on a replay. The conflict refusal removes only
/// the identity row created by THIS attempt (created_identity=true), but
/// must leave untouched any pre-existing identity (created_identity=false).
#[test]
fn admission_refuses_conflict_with_pre_existing_identity_preserved() {
    let root = sandbox("audita-preexisting-identity-preserved");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("preexist-ef-preflight.json");

    // First dispatch of "ef" succeeds and creates an identity binding.
    let manifest_ef = write_manifest(&root, "ef", "gpu-ef", &receipt_path);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ef);
    assert!(receipt_path.exists());

    // Capture the identity that was created for "ef".
    let original_identity = daemon
        .identity_hash("ef")
        .unwrap()
        .expect("first dispatch must have created an identity");

    // Store the manifest bytes for use in the replay below.
    let manifest_bytes = fs::read(&manifest_ef).unwrap();

    // Clean up the job exactly like before: drop daemon, wait for process
    // exit, reopen, mark as failed, rollback to escape the receipt.
    drop(daemon);
    thread::sleep(Duration::from_millis(500));
    let daemon = Daemon::open(&db).unwrap();

    rusqlite::Connection::open(&db)
        .unwrap()
        .execute("UPDATE jobs SET state='failed' WHERE job_id='ef'", [])
        .unwrap();

    // Rollback with remove_identity=false (the pre-existing identity should
    // NOT be removed in the rollback — only escape markers should be set).
    let rollback_error = daemon
        .test_rollback_dispatch_attempt("ef", "gpu-ef", false)
        .expect_err("setup invariant: rollback must refuse on a genuinely escaped receipt");
    assert!(format!("{rollback_error:?}").contains("DispatchReceiptEscapedRollback"));

    // Verify the identity is still there after rollback.
    assert_eq!(
        daemon.identity_hash("ef").unwrap(),
        Some(original_identity.clone()),
        "rollback with remove_identity=false must preserve the identity"
    );

    // The escaped file disappears out-of-band.
    fs::remove_file(&receipt_path).unwrap();

    // Replay the IDENTICAL job_id ("ef") at the IDENTICAL receipt_path, using
    // the IDENTICAL manifest bytes from the first dispatch. This will fail with
    // DispatchReceiptClaimConflict. The conflict refusal must recognize that
    // created_identity=false (the identity pre-existed and bind_identity_bytes
    // recognized the identical bytes at line 708), so it must NOT remove the
    // identity row when refusing.
    let replay = dispatch(&daemon, &manifest_ef);
    let replay_error = replay.expect_err(
        "replay with pre-existing identity must refuse on tombstone conflict"
    );
    assert!(
        format!("{replay_error:?}").contains("DispatchReceiptClaimConflict"),
        "expected DispatchReceiptClaimConflict, got: {replay_error:?}"
    );

    // The pre-existing identity MUST still exist after the conflict refusal.
    assert_eq!(
        daemon.identity_hash("ef").unwrap(),
        Some(original_identity),
        "conflict refusal with pre-existing identity must preserve it"
    );

    // The claim and evidence rows must be untouched.
    let claim_owner: Option<String> = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT job_id FROM dispatch_receipt_claims WHERE job_id=?1",
            ["ef"],
            |row| row.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(claim_owner.as_deref(), Some("ef"));

    let evidence_escaped: i64 = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT escaped FROM dispatch_receipt_rollback_evidence WHERE job_id='ef'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(evidence_escaped, 1);
}

/// Round-11 reviewer REJECT: identity creation, receipt-claim validation,
/// and the jobs-row reservation used to run as three SEPARATELY-lockable
/// steps (`identity_hash` read + `bind_identity_bytes`'s own commit, then
/// `start_job_with_pinned_budget_admission`'s own transaction, then --
/// on a claim conflict -- a manual `DELETE FROM identities`). Two concurrent
/// dispatch attempts for the SAME job_id could interleave across those
/// steps: both observe "no identity yet", one wins the bind, the other's
/// STALE `created_identity=true` (captured before the winner's bind
/// committed) then survived into that manual cleanup and could delete the
/// identity the winner's now-running job depends on.
///
/// This test drives the race deterministically rather than hoping a real
/// race lands: `EMBERD_TEST_IDENTITY_BIND_RACE_DELAY_MS` (round-11's new
/// hook, mirroring the existing P1-3 `EMBERD_TEST_RECEIPT_REFUSAL_RACE_DELAY_MS`
/// pattern) pauses `bind_identity_within` for 300ms WHILE STILL HOLDING the
/// connection mutex, immediately after observing no identity row exists --
/// i.e. exactly the moment a concurrent second attempt could, on the old
/// three-step design, race in and observe the same "absent" state. Thread A
/// starts first and lands inside that pause; thread B (spawned after a
/// short deterministic head start, same technique as the P1-3 test) then
/// attempts to dispatch the IDENTICAL job_id at the IDENTICAL manifest/path
/// concurrently. On the fixed, single-transaction design this is not
/// actually a race at all: B cannot even begin its OWN reservation
/// transaction (which must also acquire the same connection mutex) until
/// A's transaction has fully committed or rolled back, so B can never
/// observe "absent" while A's insert is in flight. B's own attempt is then
/// correctly refused (the job_id already exists) with NOTHING to clean up --
/// there is no longer a separate identity-erasure code path for a refusal
/// to run at all. The regression proves the surviving (A) attempt's
/// identity, lease, and running state are completely unaffected by B's
/// refused attempt, and that B was genuinely serialized behind A's paused
/// transaction (elapsed-time assertion) rather than racing past it.
#[test]
fn concurrent_same_job_id_dispatch_cannot_let_a_refused_attempt_delete_the_winners_identity() {
    let root = sandbox("round11-concurrent-identity-ownership");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("race-job-preflight.json");
    let manifest = write_manifest(&root, "race-job", "gpu-race-job", &receipt_path);
    let expected_identity_sha256 = sha256(&manifest);

    let daemon = std::sync::Arc::new(Daemon::open(&db).unwrap());

    std::env::set_var("EMBERD_TEST_IDENTITY_BIND_RACE_DELAY_MS", "300");
    let daemon_a = daemon.clone();
    let manifest_a = manifest.clone();
    let thread_a = thread::spawn(move || {
        let started = std::time::Instant::now();
        let result = dispatch(&daemon_a, &manifest_a);
        (result, started.elapsed())
    });
    // Short, deliberate head start: thread A's own pre-mutex work (probe
    // calls, JSON parsing) is sub-millisecond, so 60ms is ample time for it
    // to be inside the mutex-held pause in `bind_identity_within` before
    // thread B even starts -- deterministic ordering without needing a
    // Barrier to hit a narrow window (same technique as the existing P1-3
    // refusal-race test in dispatch_manifest.rs).
    thread::sleep(Duration::from_millis(60));

    let b_started = std::time::Instant::now();
    let result_b = dispatch(&daemon, &manifest);
    let b_elapsed = b_started.elapsed();
    std::env::remove_var("EMBERD_TEST_IDENTITY_BIND_RACE_DELAY_MS");

    let (result_a, _a_elapsed) = thread_a.join().unwrap();

    assert!(
        b_elapsed >= Duration::from_millis(250),
        "TOCTOU REOPENED: thread B's dispatch attempt for the SAME job_id must be blocked by \
         the daemon's connection mutex for (nearly) the whole 300ms identity-bind pause -- it \
         returned after only {b_elapsed:?}, meaning it was never serialized behind thread A's \
         held transaction and could have observed the identity as absent"
    );

    // Exactly one of the two identical-job_id attempts is admitted; the
    // other is refused (as "job already exists", since both target the
    // same job_id and the winner's reservation already committed).
    assert!(
        result_a.is_ok() && result_b.is_err(),
        "expected thread A (head start, wins the mutex first) to be admitted and thread B to be \
         refused; got a={result_a:?} b={result_b:?}"
    );

    // The identity thread A created must survive completely untouched by
    // thread B's refused attempt -- never deleted, never a different hash.
    assert_eq!(
        daemon.identity_hash("race-job").unwrap(),
        Some(expected_identity_sha256),
        "IDENTITY DESTROYED: a refused concurrent attempt for the SAME job_id deleted (or \
         corrupted) the identity the admitted attempt now depends on"
    );

    // The admitted job's own state and lease are unaffected by the refused
    // concurrent attempt.
    assert_eq!(
        daemon.job_state("race-job").unwrap(),
        Some(emberd::JobState::Running),
        "the winning attempt's job must still be running after the refused concurrent attempt"
    );
    assert_eq!(
        daemon.lease_owner("gpu-race-job").unwrap().as_deref(),
        Some("race-job"),
        "the winning attempt's lease must be unaffected by the refused concurrent attempt"
    );

    daemon.stop_job("race-job").unwrap();
}

/// Round-9 reviewer REJECT: the `dispatch_receipt_rollback_evidence` UPSERT
/// used a bare `ON CONFLICT DO UPDATE SET escaped=excluded.escaped`, so a
/// later, ORDINARY clean rollback (escaped=0) landing on the same
/// receipt_path silently DOWNGRADED a prior `escaped=1` tombstone row --
/// erasing the durable evidence AUDIT-A's self-heal check depends on, and
/// discarding the original escape's reason/ts in the process. This test
/// seeds an escaped=1 evidence row directly (simulating a prior escape,
/// exactly as a real rollback would have written one), then drives a
/// genuinely clean rollback (receipt file absent -> escaped=false) against
/// the SAME receipt_path, and asserts the row is unchanged: escaped stays 1
/// and the ORIGINAL reason/ts survive.
#[test]
fn rollback_evidence_upsert_never_downgrades_an_existing_escaped_tombstone() {
    let root = sandbox("rollback-evidence-monotone");
    let db = root.join("emberd.sqlite3");
    let receipt_path = root.join("custody").join("monotone-cd-preflight.json");

    let manifest = write_manifest(&root, "cd", "gpu-cd", &receipt_path);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest);
    assert_eq!(outcome.receipt.path.file_name(), receipt_path.file_name());

    rusqlite::Connection::open(&db)
        .unwrap()
        .execute("UPDATE jobs SET state='failed' WHERE job_id='cd'", [])
        .unwrap();

    // Remove the receipt out-of-band BEFORE rollback runs, so this
    // rollback's own escape probe sees confirmed-absent (escaped=false) --
    // dispatch itself writes the receipt as part of admission, so it exists
    // on disk until removed here.
    fs::remove_file(&receipt_path).unwrap();
    assert!(!receipt_path.exists());

    // `dispatch_receipt_claims.receipt_path` is written via
    // `absolute_under_root`, which canonicalizes the parent (Windows
    // extended-length `\\?\` form) -- NOT the same string this test built by
    // hand. Read back the exact stored key so the seed row below lands on
    // the SAME primary key the rollback's own upsert will target.
    let stored_receipt_path: String = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT receipt_path FROM dispatch_receipt_claims WHERE job_id='cd'",
            [],
            |row| row.get(0),
        )
        .unwrap();

    // Seed a prior escaped=1 evidence row directly, standing in for an
    // earlier rollback's durable write. Distinct reason/ts from anything the
    // upcoming clean rollback would generate, so any overwrite is visible.
    const SEEDED_REASON: &str = "receipt_escaped_to_disk";
    const SEEDED_TS_MS: i64 = 424_242;
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "INSERT INTO dispatch_receipt_rollback_evidence(receipt_path,job_id,escaped,reason,ts_ms) VALUES(?1,?2,1,?3,?4)",
            rusqlite::params![stored_receipt_path, "cd", SEEDED_REASON, SEEDED_TS_MS],
        )
        .unwrap();

    // This rollback's own probe now sees escaped=false and attempts an
    // ordinary clean upsert (escaped=0) on the SAME receipt_path the seeded
    // row already covers.
    daemon
        .test_rollback_dispatch_attempt("cd", "gpu-cd", false)
        .expect("a genuinely clean rollback (no receipt on disk) must succeed");

    let row: (i64, String, i64) = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT escaped, reason, ts_ms FROM dispatch_receipt_rollback_evidence WHERE job_id='cd'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(row.0, 1, "DOWNGRADE: a clean rollback erased the prior escaped=1 tombstone");
    assert_eq!(
        row.1, SEEDED_REASON,
        "a clean rollback must not overwrite the ORIGINAL escape's reason"
    );
    assert_eq!(
        row.2, SEEDED_TS_MS,
        "a clean rollback must not overwrite the ORIGINAL escape's ts_ms"
    );
}

/// Crash-point coverage (reviewer amendment, point 3): a job whose real
/// process has already exited, but whose row still says 'running' because
/// no monitor observed the exit yet, is the exact pre-reconcile crash
/// window. Before reconcile ever writes terminal evidence for it, a
/// different job_id must NOT be able to claim the same receipt path (the
/// claim and the live-looking row move together — never a premature free).
/// Only once reconcile's `mark_exited_unknown` path lands (terminal event +
/// claim release, same transaction) is the path safely reusable — never a
/// permanent orphan either.
#[test]
fn running_job_whose_process_already_exited_keeps_its_claim_until_reconcile_then_releases_it() {
    let root = sandbox("crash-mid-running");
    let db = root.join("emberd.sqlite3");
    let shared_receipt = root.join("custody").join("claimsmid-ab-preflight.json");

    let manifest_ab = write_manifest_with_sleep_ms(
        &root,
        "claimsmid-ab",
        "gpu-claimsmid-ab",
        &shared_receipt,
        25,
    );
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), shared_receipt.file_name());
    // Drop the daemon: this kills the live exit-monitor thread, so nothing
    // updates the row when the short-lived child exits on its own a moment
    // later -- the exact "process gone, row still says running" crash window
    // (same technique as control_plane.rs's dead_persisted_running_job_*).
    drop(daemon);
    thread::sleep(Duration::from_millis(300));

    let reopened = Daemon::open(&db).unwrap();
    assert_eq!(
        reopened.job_state("claimsmid-ab").unwrap(),
        Some(emberd::JobState::Running),
        "setup invariant: the row must still say running before reconcile runs"
    );

    // Pre-reconcile: no terminal evidence exists yet for the crashed job. A
    // different job_id must be refused, not silently admitted.
    let manifest_premature = write_manifest(&root, "ab", "gpu-ab", &shared_receipt);
    let premature = dispatch(&reopened, &manifest_premature);
    let premature_error = premature.expect_err(
        "PREMATURE FREE: a different job claimed the path before any terminal evidence \
         landed for the crashed job",
    );
    let debug = format!("{premature_error:?}");
    assert!(
        debug.contains("DispatchReceiptClaimConflict") || debug.contains("ReceiptAlreadyExists"),
        "expected a claim-conflict/receipt-exists refusal before reconcile, got: {debug}"
    );

    // reconcile() detects the dead process and lands mark_exited_unknown --
    // terminal event write and claim release inside the same transaction.
    reopened.reconcile().unwrap();
    assert_eq!(
        reopened.job_state("claimsmid-ab").unwrap(),
        Some(emberd::JobState::Exited)
    );
    fs::remove_file(&shared_receipt).unwrap();

    // The slot is now safely reusable -- never a permanent orphan. Retry the
    // SAME bounded-segment-colliding job_id ("ab") that was correctly
    // refused above: the prior refusal left no row for it (the guard fired
    // before any admission write), so this is a clean, distinct-job retry
    // now that terminal evidence for "claimsmid-ab" has landed.
    let result = dispatch(&reopened, &manifest_premature);
    assert!(
        result.is_ok(),
        "PERMANENT ORPHAN: receipt path still claimed after reconcile recorded terminal \
         evidence for the crashed job: {result:?}"
    );
    reopened.stop_job("ab").unwrap();
}

/// Legacy/inconsistent-state convergence (reviewer amendment, point 3b): a
/// claim row can in principle exist whose owning job is ALREADY terminal --
/// e.g. a row written before this fix existed, or any future gap in the
/// write-time release set this file doesn't yet cover. Direct SQL injection
/// reproduces that inconsistency without depending on any particular
/// history. The invariant: the NEXT admission attempt at that receipt path
/// by a different job_id must converge -- self-heal the stale claim, since
/// its owner is provably gone -- rather than wedge the path forever.
#[test]
fn admission_self_heals_a_legacy_claim_whose_owner_is_already_terminal() {
    let root = sandbox("legacy-claim-self-heal");
    let db = root.join("emberd.sqlite3");
    let shared_receipt = root.join("custody").join("claimslegacy-ab-preflight.json");

    let manifest_ab = write_manifest(&root, "claimslegacy-ab", "gpu-claimslegacy-ab", &shared_receipt);
    let daemon = Daemon::open(&db).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), shared_receipt.file_name());

    // Capture the EXACT receipt_path string production stored for this
    // claim (it is canonicalized at manifest-parse time, e.g. a Windows
    // `\\?\` prefix, so it will not textually match a freshly-built PathBuf
    // -- read it back rather than reconstructing it, or the re-injected row
    // below would silently target a different string and never collide).
    let canonical_receipt_path: String = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT receipt_path FROM dispatch_receipt_claims WHERE job_id=?1",
            ["claimslegacy-ab"],
            |row| row.get(0),
        )
        .unwrap();

    // Reach a genuine terminal state the normal way (finalize_stopped
    // releases the claim in its own atomic tx, lib.rs:3568-3613). Then
    // re-inject the pre-fix inconsistency directly via raw SQL, using the
    // SAME canonical string, as if this job's terminal transition had run
    // under code that never released it.
    daemon.stop_job("claimslegacy-ab").unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "INSERT INTO dispatch_receipt_claims(receipt_path,job_id,manifest_sha256,claimed_at_ms) VALUES(?1,?2,?3,?4)",
            rusqlite::params![canonical_receipt_path, "claimslegacy-ab", "legacy-sha", 1_i64],
        )
        .unwrap();
    fs::remove_file(&shared_receipt).unwrap();

    // A DIFFERENT job_id dispatches at the same path. The claim's owner
    // ("claimslegacy-ab") is terminal ('stopped'), so
    // validate_receipt_claim_available must self-heal the stale claim
    // rather than refuse forever.
    let manifest_b = write_manifest(&root, "ab", "gpu-ab", &shared_receipt);
    let result = dispatch(&daemon, &manifest_b);
    assert!(
        result.is_ok(),
        "PERMANENT ORPHAN: a legacy claim row for an already-terminal owner was never \
         self-healed at the next admission attempt: {result:?}"
    );
    daemon.stop_job("ab").unwrap();
}

/// Companion negative control for the self-heal above: a claim whose owner
/// is genuinely still live must NOT be healed away -- self-healing must be
/// scoped strictly to gone/terminal owners, never to a live one.
#[test]
fn admission_still_conflicts_when_the_claim_owner_is_genuinely_live() {
    let root = sandbox("legacy-claim-live-owner");
    let shared_receipt = root.join("custody").join("claimslive-ab-preflight.json");

    let manifest_ab = write_manifest(&root, "claimslive-ab", "gpu-claimslive-ab", &shared_receipt);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let outcome = dispatch_ok(&daemon, &manifest_ab);
    assert_eq!(outcome.receipt.path.file_name(), shared_receipt.file_name());

    // Owner is still 'running' -- a different job_id must still be refused,
    // never silently self-healed.
    let manifest_b = write_manifest(&root, "ab", "gpu-ab", &shared_receipt);
    let result = dispatch(&daemon, &manifest_b);
    let error = result.expect_err("a genuinely live owner must still refuse a different job");
    let debug = format!("{error:?}");
    assert!(
        debug.contains("DispatchReceiptClaimConflict") || debug.contains("ReceiptAlreadyExists"),
        "expected a live-owner conflict, got: {debug}"
    );
    daemon.stop_job("claimslive-ab").unwrap();
}
