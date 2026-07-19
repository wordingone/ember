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

#![cfg(windows)]

use emberd::{Daemon, HostCommitCapacity};
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
        thread::sleep(Duration::from_secs(30));
    }
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
/// "claims-ab" / "claims-a" is the same substring-collision trick used
/// elsewhere in this suite: two DISTINCT job_ids can both pass the filename
/// job-scoping check against the same receipt path.
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

    // A DIFFERENT job_id ("claims-a" collides via substring) re-dispatches
    // the SAME receipt path. Before the fix this refuses forever with
    // DispatchReceiptClaimConflict; after the fix it must be admitted.
    let manifest_a = write_manifest(&root, "claims-a", "gpu-claims-a", &shared_receipt);
    let result = dispatch(&daemon, &manifest_a);
    assert!(
        result.is_ok(),
        "WEDGE: receipt path still claimed after the prior job's clean stop \
         (dispatch_receipt_claims never released on terminal transition): {result:?}"
    );
    daemon.stop_job("claims-a").unwrap();
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
    let manifest_b = write_manifest(&root, "claimsfail-a", "gpu-claimsfail-a", &shared_receipt);
    let result = dispatch(&daemon, &manifest_b);
    assert!(
        result.is_ok(),
        "ORPHAN: receipt path still claimed after spawn-failure rollback deleted \
         the job from every other table: {result:?}"
    );
    daemon.stop_job("claimsfail-a").unwrap();
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
    let manifest_b = write_manifest(&root, "claimscrash-a", "gpu-claimscrash-a", &shared_receipt);
    let result = dispatch(&daemon, &manifest_b);
    assert!(
        result.is_ok(),
        "WEDGE-AFTER-RECONCILE: receipt path still claimed by the crash-orphaned \
         'starting' job after reconcile marked it failed: {result:?}"
    );
    daemon.stop_job("claimscrash-a").unwrap();
}
