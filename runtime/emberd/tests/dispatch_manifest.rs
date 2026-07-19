// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

use emberd::{Daemon, EmberdError, HostCommitCapacity, JobState};
use rusqlite::Connection;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const GIB: u64 = 1024 * 1024 * 1024;
const HOST_COMMIT_RESERVE_BYTES: u64 = 10 * GIB;
const DECLARED_PHYSICAL_RAM_BYTES: u64 = 64 * GIB;
const DECLARED_PAGEFILE_MAXIMUM_BYTES: u64 = 32 * GIB;
const DECLARED_COMMIT_TOTAL_BYTES: u64 = 80 * GIB;
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
        "emberd-dispatch-{name}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
}

#[test]
fn fixture_dispatch_child() {
    if std::env::var("EMBERD_DISPATCH_FIXTURE_CHILD").as_deref() == Ok("1") {
        if let Ok(raw) = std::env::var("EMBERD_DISPATCH_ALLOCATE_BYTES") {
            let bytes: usize = raw.parse().unwrap();
            let mut allocation = vec![0u8; bytes];
            for offset in (0..allocation.len()).step_by(4096) {
                allocation[offset] = 1;
            }
            std::hint::black_box(allocation);
        }
        thread::sleep(Duration::from_secs(30));
    }
}

fn write_manifest(root: &Path, job_id: &str, not_before_ms: i64) -> PathBuf {
    let custody = root.join("custody");
    fs::create_dir_all(&custody).unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBERD_DISPATCH_FIXTURE_CHILD", "1".to_string());
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
        env.insert(name, path.to_string_lossy().into_owned());
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
            "not_before_ms": not_before_ms,
            "expires_at_ms": not_before_ms + 60_000,
            "resource_lease": "gpu-smoke",
        "program": {"path": program, "sha256": sha256(&program)},
            "args": ["--exact", "fixture_dispatch_child", "--nocapture"],
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
        "preflight_receipt": root.join("custody").join(format!("{job_id}-preflight.json"))
        }))
        .unwrap(),
    )
    .unwrap();
    manifest
}

#[test]
fn dispatch_manifest_hashes_preflights_and_governs_spawn() {
    let root = sandbox("green");
    let manifest = write_manifest(&root, "dispatch-green", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome.handle.pid > 0);
    assert_eq!(
        daemon.job_state("dispatch-green").unwrap(),
        Some(JobState::Running)
    );
    assert_eq!(
        daemon.lease_owner("gpu-smoke").unwrap().as_deref(),
        Some("dispatch-green")
    );
    assert_eq!(
        daemon.identity_hash("dispatch-green").unwrap().as_deref(),
        Some(sha256(&manifest).as_str())
    );
    assert_eq!(sha256(&outcome.receipt.path), outcome.receipt.sha256);
    let receipt: Value = serde_json::from_slice(&fs::read(&outcome.receipt.path).unwrap()).unwrap();
    assert_eq!(receipt["schema_version"], "emberd-dispatch-preflight-v1");
    assert_eq!(receipt["result"], "PREFLIGHT_PASSED");
    assert_eq!(
        receipt["source_commit"],
        "5326043c344227c1b145a4ddbb3519cfa62d4943"
    );
    assert_eq!(receipt["dispatch_manifest_sha256"], sha256(&manifest));
    assert_eq!(receipt["vram_reserve"]["minimum_free_bytes"], 1);
    assert_eq!(receipt["vram_reserve"]["available_free_bytes"], 2048);
    assert_eq!(
        receipt["host_commit"]["required_available_maximum_commit_bytes"],
        DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES
    );
    assert_eq!(
        receipt["host_commit"]["observed_available_maximum_commit_bytes"],
        DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES
    );
    assert_eq!(receipt["host_commit"]["physical_ram_bytes"], 64 * GIB);
    assert_eq!(receipt["host_commit"]["pagefile_maximum_bytes"], 32 * GIB);
    assert_eq!(
        receipt["host_commit"]["pagefile_configuration_source"],
        r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles"
    );
    assert_eq!(
        receipt["host_commit"]["pagefile_configuration_sha256"],
        "a".repeat(64)
    );
    assert_eq!(receipt["host_commit"]["commit_total_bytes"], 80 * GIB);
    assert_eq!(
        receipt["host_commit"]["current_commit_limit_bytes"],
        80 * GIB
    );
    assert_eq!(
        receipt["host_commit"]["maximum_commit_capacity_bytes"],
        96 * GIB
    );
    assert_eq!(
        receipt["host_commit"]["basis"],
        "maximum_configured_capacity"
    );
    assert_eq!(
        receipt["host_commit"]["reserve_bytes"],
        HOST_COMMIT_RESERVE_BYTES
    );
    assert_eq!(
        receipt["host_commit"]["maximum_job_memory_bytes"],
        MAXIMUM_JOB_MEMORY_BYTES
    );
    assert_eq!(
        receipt["host_commit"]["simulated_peak_commit_bytes"],
        SIMULATED_PEAK_COMMIT_BYTES
    );
    daemon.stop_job("dispatch-green").unwrap();
}

#[test]
fn identical_dispatch_retry_reconstructs_the_existing_job_and_receipt() {
    let root = sandbox("idempotent-retry");
    let manifest = write_manifest(&root, "dispatch-idempotent-retry", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let first = daemon
        .dispatch_manifest_bytes_at_with_probes_and_host_and_floor(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    let second = daemon
        .dispatch_manifest_bytes_at_with_probes_and_host_and_floor(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert_eq!(first.handle.pid, second.handle.pid);
    assert_eq!(first.receipt.path, second.receipt.path);
    assert_eq!(first.receipt.sha256, second.receipt.sha256);
    assert_eq!(
        daemon.job_state("dispatch-idempotent-retry").unwrap(),
        Some(JobState::Running)
    );
    daemon.stop_job("dispatch-idempotent-retry").unwrap();
}

#[test]
fn receipt_publication_failure_is_typed_and_an_identical_retry_recovers_without_a_second_start() {
    let root = sandbox("receipt-publication-recovery");
    let manifest = write_manifest(&root, "dispatch-receipt-recovery", 10_000);
    let receipt_path = root.join("custody").join("dispatch-receipt-recovery-preflight.json");
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();

    let first = daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
        &manifest,
        10_001,
        |_root| Ok(1024),
        || {
            fs::create_dir(&receipt_path).unwrap();
            Ok(2048)
        },
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        |_root| Ok(u64::MAX),
    );
    assert!(matches!(
        first,
        Err(EmberdError::DispatchReceiptRecoveryPending { .. })
    ));
    assert_eq!(
        daemon.job_state("dispatch-receipt-recovery").unwrap(),
        Some(JobState::Running)
    );
    assert!(matches!(
        daemon.adopt_job("dispatch-receipt-recovery"),
        Err(EmberdError::DispatchReceiptRecoveryPending { .. })
    ));
    let connection = Connection::open(root.join("emberd.sqlite3")).unwrap();
    let first_pid: u32 = connection
        .query_row(
            "SELECT pid FROM jobs WHERE job_id='dispatch-receipt-recovery'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    fs::remove_dir(&receipt_path).unwrap();

    let recovered = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert_eq!(recovered.handle.pid, first_pid);
    assert!(recovered.receipt.path.is_file());
    daemon.stop_job("dispatch-receipt-recovery").unwrap();
}

#[test]
fn dispatch_manifest_lease_conflict_leaves_no_selectable_preflight_and_retries() {
    let root = sandbox("lease-conflict-retry");
    let first = write_manifest(&root, "dispatch-lease-first", 10_000);
    let second = root.join("dispatch-second.json");
    let mut payload: Value = serde_json::from_slice(&fs::read(&first).unwrap()).unwrap();
    payload["job_id"] = json!("dispatch-lease-second");
    payload["preflight_receipt"] = json!(root.join("custody").join("dispatch-lease-second-preflight.json"));
    fs::write(&second, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &first,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &second,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::LeaseConflict { .. })
    ));
    assert!(!root.join("custody").join("dispatch-lease-second-preflight.json").exists());
    assert_eq!(daemon.job_state("dispatch-lease-second").unwrap(), None);
    assert_eq!(daemon.identity_hash("dispatch-lease-second").unwrap(), None);
    daemon.stop_job("dispatch-lease-first").unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &second,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome.receipt.path.exists());
    daemon.stop_job("dispatch-lease-second").unwrap();
}

#[test]
fn dispatch_manifest_spawn_failure_leaves_no_selectable_preflight_and_retries() {
    let root = sandbox("spawn-failure-retry");
    let manifest = write_manifest(&root, "dispatch-spawn-retry", 10_000);
    let invalid_program = root.join("not-a-program.txt");
    fs::write(&invalid_program, b"not an executable image").unwrap();
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["program"] = json!({"path": invalid_program, "sha256": sha256(&invalid_program)});
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .is_err());
    assert!(!root.join("custody").join("dispatch-spawn-retry-preflight.json").exists());
    assert_eq!(daemon.job_state("dispatch-spawn-retry").unwrap(), None);
    assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
    assert_eq!(daemon.identity_hash("dispatch-spawn-retry").unwrap(), None);
    let repaired = write_manifest(&root, "dispatch-spawn-retry", 10_000);
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &repaired,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome.receipt.path.exists());
    daemon.stop_job("dispatch-spawn-retry").unwrap();
}
#[test]
fn dispatch_manifest_rejects_stale_v1_host_capacity_schema() {
    let root = sandbox("stale-v1-host-capacity");
    let manifest = write_manifest(&root, "dispatch-stale-v1", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["schema_version"] = json!("emberd-dispatch-manifest-v1");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-stale-v1").unwrap(), None);
    assert!(!root.join("custody").join("dispatch-stale-v1-preflight.json").exists());
}

#[test]
fn dispatch_manifest_refuses_physical_pagefile_and_commit_drift() {
    for (name, physical, pagefile_maximum, commit_total) in [
        (
            "physical-drift",
            DECLARED_PHYSICAL_RAM_BYTES - 1,
            DECLARED_PAGEFILE_MAXIMUM_BYTES,
            DECLARED_COMMIT_TOTAL_BYTES,
        ),
        (
            "pagefile-drift",
            DECLARED_PHYSICAL_RAM_BYTES,
            DECLARED_PAGEFILE_MAXIMUM_BYTES - 1,
            DECLARED_COMMIT_TOTAL_BYTES,
        ),
        (
            "commit-drift",
            DECLARED_PHYSICAL_RAM_BYTES,
            DECLARED_PAGEFILE_MAXIMUM_BYTES,
            DECLARED_COMMIT_TOTAL_BYTES + 1,
        ),
    ] {
        let root = sandbox(name);
        let manifest = write_manifest(&root, &format!("dispatch-{name}"), 10_000);
        let maximum = physical + pagefile_maximum;
        let observed_available = maximum - commit_total;
        let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
        let error = daemon
            .dispatch_manifest_at_with_probes_and_host_and_floor(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
                || {
                    Ok(HostCommitCapacity {
                        physical_ram_bytes: physical,
                        pagefile_maximum_bytes: pagefile_maximum,
                        pagefile_configuration_source: r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles".to_string(),
                        pagefile_configuration_sha256: "b".repeat(64),
                        commit_total_bytes: commit_total,
                        current_commit_limit_bytes: 80 * GIB,
                        maximum_commit_capacity_bytes: maximum,
                        available_maximum_commit_bytes: observed_available,
                    })
                },
                |_root| Ok(u64::MAX),
            )
            .unwrap_err();
        assert!(format!("{error:?}").contains("DispatchHostCommitReserve"));
        let receipt: Value =
            serde_json::from_slice(&fs::read(root.join("custody").join(format!("dispatch-{name}-preflight.json"))).unwrap())
                .unwrap();
        assert_eq!(receipt["result"], "REFUSED_HOST_COMMIT_CAP");
        assert_eq!(receipt["host_commit"]["physical_ram_bytes"], physical);
        assert_eq!(
            receipt["host_commit"]["pagefile_maximum_bytes"],
            pagefile_maximum
        );
        assert_eq!(receipt["host_commit"]["commit_total_bytes"], commit_total);
        assert_eq!(
            receipt["host_commit"]["observed_available_maximum_commit_bytes"],
            observed_available
        );
    }
}

#[test]
fn dispatch_manifest_refuses_unsafe_host_commit_cap_with_receipt_before_spawn() {
    for (name, declared_free, maximum, simulated_peak, observed_free) in [
        (
            "formula",
            DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES,
            MAXIMUM_JOB_MEMORY_BYTES + 1,
            SIMULATED_PEAK_COMMIT_BYTES,
            DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES,
        ),
        (
            "drift",
            DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES,
            MAXIMUM_JOB_MEMORY_BYTES,
            SIMULATED_PEAK_COMMIT_BYTES,
            DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES - 1,
        ),
        (
            "simulated-peak",
            DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES,
            MAXIMUM_JOB_MEMORY_BYTES,
            MAXIMUM_JOB_MEMORY_BYTES + 1,
            DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES,
        ),
    ] {
        let root = sandbox(name);
        let manifest = write_manifest(&root, &format!("dispatch-{name}"), 10_000);
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        payload["required_available_maximum_commit_bytes"] = json!(declared_free);
        payload["maximum_job_memory_bytes"] = json!(maximum);
        payload["simulated_peak_commit_bytes"] = json!(simulated_peak);
        fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
        let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
        let error = daemon
            .dispatch_manifest_at_with_probes_and_host_and_floor(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(2048),
                || Ok(host_capacity(observed_free)),
                |_root| Ok(u64::MAX),
            )
            .unwrap_err();
        assert!(
            format!("{error:?}").contains("DispatchHostCommitReserve"),
            "unexpected error: {error:?}"
        );
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        let receipt_path = root.join("custody").join(format!("dispatch-{name}-preflight.json"));
        let receipt: Value = serde_json::from_slice(&fs::read(receipt_path).unwrap()).unwrap();
        assert_eq!(receipt["result"], "REFUSED_HOST_COMMIT_CAP");
        assert_eq!(
            receipt["host_commit"]["required_available_maximum_commit_bytes"],
            declared_free
        );
        assert_eq!(
            receipt["host_commit"]["observed_available_maximum_commit_bytes"],
            observed_free
        );
        assert_eq!(receipt["host_commit"]["maximum_job_memory_bytes"], maximum);
        assert_eq!(
            receipt["host_commit"]["simulated_peak_commit_bytes"],
            simulated_peak
        );
    }
}

#[test]
fn dispatch_job_memory_ceiling_terminates_an_over_allocation_probe() {
    let root = sandbox("job-memory-ceiling");
    let manifest = write_manifest(&root, "dispatch-memory-ceiling", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let declared_available = HOST_COMMIT_RESERVE_BYTES + 134_217_728u64;
    payload["required_available_maximum_commit_bytes"] = json!(declared_available);
    payload["maximum_job_memory_bytes"] = json!(134_217_728u64);
    payload["simulated_peak_commit_bytes"] = json!(67_108_864u64);
    payload["env"]["EMBERD_DISPATCH_ALLOCATE_BYTES"] = json!(536_870_912u64.to_string());
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(15);
    loop {
        let state = daemon
            .job_state("dispatch-memory-ceiling")
            .unwrap()
            .unwrap();
        if matches!(state, JobState::Exited | JobState::Failed) {
            break;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "over-allocation probe remained live past the job-memory ceiling"
        );
        thread::sleep(Duration::from_millis(25));
    }
    assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
}

#[test]
fn dispatch_manifest_rejects_a_missing_job_memory_ceiling() {
    let root = sandbox("missing-job-memory-ceiling");
    let manifest = write_manifest(&root, "dispatch-missing-memory", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload
        .as_object_mut()
        .unwrap()
        .remove("maximum_job_memory_bytes");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-missing-memory").unwrap(), None);
    assert!(!root.join("custody").join("dispatch-missing-memory-preflight.json").exists());
}

#[test]
fn dispatch_manifest_fails_closed_before_spawn_on_time_hash_and_storage() {
    for (name, now_ms, free_bytes, free_vram, corrupt_binding, expected) in [
        ("early", 9_999, 1024, 1024, false, "DispatchTooEarly"),
        ("storage", 10_001, 0, 1024, false, "DispatchStorageReserve"),
        ("vram", 10_001, 1024, 0, false, "DispatchVramReserve"),
        ("hash", 10_001, 1024, 1024, true, "DispatchBindingMismatch"),
    ] {
        let root = sandbox(name);
        let manifest = write_manifest(&root, &format!("dispatch-{name}"), 10_000);
        if corrupt_binding {
            fs::write(root.join("config.json"), b"changed").unwrap();
        }
        let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
        let error = daemon
            .dispatch_manifest_at_with_probes_and_host_and_floor(
                &manifest,
                now_ms,
                |_root| Ok(free_bytes),
                || Ok(free_vram),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
                |_root| Ok(u64::MAX),
            )
            .unwrap_err();
        assert!(
            format!("{error:?}").contains(expected),
            "unexpected error: {error:?}"
        );
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
        assert!(!root.join("custody").join(format!("dispatch-{name}-preflight.json")).exists());
    }
}

#[test]
fn dispatch_manifest_refuses_receipt_path_not_scoped_to_job() {
    // Per-job collision-refusing receipt paths: a manifest whose declared
    // preflight_receipt filename does not carry its own job_id is refused
    // before any receipt or job row is produced — two jobs can never race
    // one shared receipt file.
    let root = sandbox("receipt-not-job-scoped");
    let manifest = write_manifest(&root, "dispatch-unscoped-receipt", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["preflight_receipt"] = json!(root.join("custody").join("shared-preflight.json"));
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap_err();
    assert!(
        matches!(error, EmberdError::DispatchReceiptPathNotJobScoped { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(daemon.job_state("dispatch-unscoped-receipt").unwrap(), None);
    assert!(!root.join("custody").join("shared-preflight.json").exists());
}

#[test]
fn dispatch_manifest_rejects_unknown_fields_and_cache_escape() {
    let root = sandbox("closed");
    let manifest = write_manifest(&root, "dispatch-closed", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["unknown"] = json!(true);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn dispatch_manifest_requires_typed_config_and_manifest_bindings() {
    let root = sandbox("binding-classes");
    let manifest = write_manifest(&root, "dispatch-binding-classes", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["bindings"]
        .as_array_mut()
        .unwrap()
        .retain(|binding| binding["kind"] == "config");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX)
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-binding-classes").unwrap(), None);
    assert!(!root.join("custody").join("dispatch-binding-classes-preflight.json").exists());
}

#[test]
fn dispatch_manifest_bytes_refuses_a_conflicting_daemon_custody_snapshot_before_launch() {
    let root = sandbox("manifest-bytes-snapshot");
    let manifest = write_manifest(&root, "dispatch-manifest-bytes-snapshot", 10_000);
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let custody_snapshot = root
        .join("emberd.sqlite3.logs")
        .join("dispatch-manifests")
        .join(format!("{manifest_sha256}.json"));
    fs::create_dir_all(custody_snapshot.parent().unwrap()).unwrap();
    fs::write(&custody_snapshot, b"{\"attacker\":true}").unwrap();

    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_bytes_at_with_probes_and_host_and_floor(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(fs::read(&custody_snapshot).unwrap(), b"{\"attacker\":true}");
    assert!(!root.join("custody").join("dispatch-manifest-bytes-snapshot-preflight.json").exists());
    assert_eq!(
        daemon
            .job_state("dispatch-manifest-bytes-snapshot")
            .unwrap(),
        None
    );
}
#[test]
fn dispatch_manifest_bytes_never_creates_an_unapproved_candidate_custody_root() {
    let root = sandbox("manifest-bytes-unapproved-custody");
    let manifest = write_manifest(&root, "dispatch-manifest-bytes-unapproved-custody", 10_000);
    let unapproved = root.join("unapproved-custody");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["custody_root"] = json!(unapproved);
    payload["preflight_receipt"] = json!(unapproved.join("dispatch-manifest-bytes-unapproved-custody-preflight.json"));
    let manifest_bytes = serde_json::to_vec(&payload).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();

    assert!(matches!(
        daemon.dispatch_manifest_bytes_at_with_probes_and_host_and_floor(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert!(!unapproved.exists());
    assert!(!root
        .join("emberd.sqlite3.logs")
        .join("dispatch-manifests")
        .exists());
    assert_eq!(
        daemon
            .job_state("dispatch-manifest-bytes-unapproved-custody")
            .unwrap(),
        None
    );
}
#[test]
fn dispatch_manifest_snapshots_are_bounded_after_semantic_preflight() {
    let root = sandbox("bounded-snapshots");
    let manifest = write_manifest(&root, "dispatch-snapshot-base", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    for index in 0..65 {
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        payload["job_id"] = json!(format!("dispatch-snapshot-{index}"));
        payload["preflight_receipt"] =
            json!(root.join("custody").join(format!("dispatch-snapshot-{index}-preflight.json")));
        let bytes = serde_json::to_vec(&payload).unwrap();
        let digest = format!("{:x}", Sha256::digest(&bytes));
        assert!(matches!(
            daemon.dispatch_manifest_bytes_at_with_probes_and_host_and_floor(
                &bytes,
                &digest,
                10_001,
                |_root| Ok(1024),
                || Ok(2048),
                || Ok(host_capacity(0)),
                |_root| Ok(u64::MAX),
            ),
            Err(EmberdError::DispatchHostCommitReserve { .. })
        ));
    }
    let snapshots = root.join("emberd.sqlite3.logs").join("dispatch-manifests");
    let count = fs::read_dir(&snapshots).unwrap().count();
    assert_eq!(count, 64);
}
#[test]
fn duplicate_snapshot_at_capacity_preserves_every_unrelated_snapshot() {
    let root = sandbox("duplicate-snapshot-capacity");
    let manifest = write_manifest(&root, "dispatch-duplicate-snapshot", 10_000);
    let duplicate_bytes = fs::read(&manifest).unwrap();
    let duplicate_digest = format!("{:x}", Sha256::digest(&duplicate_bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let snapshots = root.join("emberd.sqlite3.logs").join("dispatch-manifests");
    fs::create_dir_all(&snapshots).unwrap();
    for index in 0..63 {
        fs::write(
            snapshots.join(format!("unrelated-{index:02}.json")),
            b"{}\n",
        )
        .unwrap();
    }
    std::thread::sleep(Duration::from_millis(20));
    fs::write(
        snapshots.join(format!("{duplicate_digest}.json")),
        &duplicate_bytes,
    )
    .unwrap();
    let before = fs::read_dir(&snapshots)
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(before.len(), 64);
    assert!(matches!(
        daemon.dispatch_manifest_bytes_at_with_probes_and_host_and_floor(
            &duplicate_bytes,
            &duplicate_digest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(0)),
            |_root| Ok(u64::MAX),
        ),
        Err(EmberdError::DispatchHostCommitReserve { .. })
    ));
    let after = fs::read_dir(&snapshots)
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(after, before);
}
#[test]
fn historical_resume_registry_requires_every_nested_authority_file_binding() {
    let root = sandbox("resume-registry-closure");
    let manifest = write_manifest(&root, "dispatch-resume-registry", 10_000);
    let registry_root = root.join("registry");
    fs::create_dir_all(&registry_root).unwrap();
    let counter = registry_root.join("parameter_counter.py");
    let receipt = registry_root.join("step2-realization-receipt.json");
    let historical_config = registry_root.join("model-config.json");
    fs::write(&counter, b"# exact counter bytes\n").unwrap();
    fs::write(&receipt, b"{\"result\":\"MEASURED\"}").unwrap();
    fs::write(&historical_config, b"{\"model\":\"historical\"}").unwrap();
    let registry = registry_root.join("trusted-verifiers.json");
    fs::write(
        &registry,
        serde_json::to_vec(&json!({
            "schema_version": "ember-trusted-verifiers-v2",
            "verifiers": [{"path": "parameter_counter.py", "sha256": sha256(&counter), "evidence_classes": ["parameter_realization"], "criterion_ids": ["ember-sparse-step2-realization-v1"]}],
            "realization_receipts": [{"path": "step2-realization-receipt.json", "sha256": sha256(&receipt), "subject_checkpoint_sha256": "b".repeat(64), "model_config_sha256": "5".repeat(64), "counter_sha256": sha256(&counter), "active_expert": "shared"}],
            "model_configs": [{"path": "model-config.json", "sha256": sha256(&historical_config), "semantic_sha256": "4".repeat(64)}]
        }))
        .unwrap(),
    )
    .unwrap();
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["args"]
        .as_array_mut()
        .unwrap()
        .extend([json!("--resume-realization-registry"), json!(registry)]);
    payload["bindings"].as_array_mut().unwrap().push(json!({
        "kind": "manifest", "path": registry, "sha256": sha256(&registry)
    }));
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX)
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));

    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["bindings"].as_array_mut().unwrap().extend([
        json!({"kind": "verifier", "path": counter, "sha256": sha256(&counter)}),
        json!({"kind": "manifest", "path": receipt, "sha256": sha256(&receipt)}),
        json!({"kind": "config", "path": historical_config, "sha256": sha256(&historical_config)}),
    ]);
    let mut registry_payload: Value =
        serde_json::from_slice(&fs::read(&registry).unwrap()).unwrap();
    registry_payload["verifiers"][0]["unreviewed_authority"] = json!(true);
    fs::write(&registry, serde_json::to_vec(&registry_payload).unwrap()).unwrap();
    let registry_binding = payload["bindings"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|binding| binding["path"] == json!(registry))
        .unwrap();
    registry_binding["sha256"] = json!(sha256(&registry));
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX)
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    registry_payload["verifiers"][0]
        .as_object_mut()
        .unwrap()
        .remove("unreviewed_authority");
    fs::write(&registry, serde_json::to_vec(&registry_payload).unwrap()).unwrap();
    let registry_binding = payload["bindings"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|binding| binding["path"] == json!(registry))
        .unwrap();
    registry_binding["sha256"] = json!(sha256(&registry));
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(0),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX)
        ),
        Err(EmberdError::DispatchStorageReserve { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-resume-registry").unwrap(), None);
}

#[test]
fn dispatch_manifest_rejects_cache_and_equals_path_escapes() {
    for name in ["cache-escape", "arg-escape"] {
        let root = sandbox(name);
        let manifest = write_manifest(&root, &format!("dispatch-{name}"), 10_000);
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        if name == "cache-escape" {
            payload["env"]["TEMP"] = json!(root);
        } else {
            let outside = sandbox("outside-custody");
            payload["args"] = json!([format!("--output={}", outside.display())]);
        }
        fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
        let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
        assert!(matches!(
            daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
                |_root| Ok(u64::MAX),
            ),
            Err(EmberdError::InvalidDispatchManifest { .. })
        ));
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        assert!(!root.join("custody").join("dispatch-resume-registry-preflight.json").exists());
    }
}

// --- INFRA governor increment 1: causal PinnedHostBudget + survival floors ---

#[test]
fn dispatch_manifest_pinned_host_budget_subtracts_live_jobs_and_releases_on_exit() {
    let root_a = sandbox("pinned-budget-a");
    let manifest_a = write_manifest(&root_a, "dispatch-pin-a", 10_000);
    let mut payload_a: Value = serde_json::from_slice(&fs::read(&manifest_a).unwrap()).unwrap();
    payload_a["resource_lease"] = json!("gpu-smoke-a");
    fs::write(&manifest_a, serde_json::to_vec(&payload_a).unwrap()).unwrap();

    let daemon = Daemon::open(&root_a.join("emberd.sqlite3")).unwrap();
    let outcome_a = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest_a,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome_a.handle.pid > 0);
    assert_eq!(
        daemon.live_committed_job_memory_bytes().unwrap(),
        MAXIMUM_JOB_MEMORY_BYTES
    );

    // A second job, on its own lease, whose own declared requirement is
    // satisfied by the raw host probe alone but NOT once A's live declared
    // budget is causally subtracted from it: refused.
    let root_b = sandbox("pinned-budget-b-refused");
    let manifest_b = write_manifest(&root_b, "dispatch-pin-b", 10_000);
    let mut payload_b: Value = serde_json::from_slice(&fs::read(&manifest_b).unwrap()).unwrap();
    payload_b["resource_lease"] = json!("gpu-smoke-b");
    fs::write(&manifest_b, serde_json::to_vec(&payload_b).unwrap()).unwrap();
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest_b,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap_err();
    assert!(
        matches!(error, EmberdError::DispatchPinnedHostBudgetExceeded { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(daemon.job_state("dispatch-pin-b").unwrap(), None);
    assert_eq!(daemon.lease_owner("gpu-smoke-b").unwrap(), None);
    let receipt: Value = serde_json::from_slice(
        &fs::read(root_b.join("custody").join("dispatch-pin-b-preflight.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(receipt["result"], "REFUSED_PINNED_HOST_BUDGET");
    assert_eq!(
        receipt["pinned_host_budget"]["live_committed_job_memory_bytes"],
        MAXIMUM_JOB_MEMORY_BYTES
    );
    assert_eq!(
        receipt["pinned_host_budget"]["residual_available_maximum_commit_bytes"],
        DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES - MAXIMUM_JOB_MEMORY_BYTES
    );

    // Release: once A exits, its declared budget is no longer live-committed
    // and an equivalent dispatch now clears the same causal check.
    daemon.stop_job("dispatch-pin-a").unwrap();
    assert_eq!(daemon.live_committed_job_memory_bytes().unwrap(), 0);

    let root_b2 = sandbox("pinned-budget-b-retry");
    let manifest_b2 = write_manifest(&root_b2, "dispatch-pin-b2", 10_000);
    let mut payload_b2: Value = serde_json::from_slice(&fs::read(&manifest_b2).unwrap()).unwrap();
    payload_b2["resource_lease"] = json!("gpu-smoke-b");
    fs::write(&manifest_b2, serde_json::to_vec(&payload_b2).unwrap()).unwrap();
    let outcome_b2 = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest_b2,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome_b2.handle.pid > 0);
    daemon.stop_job("dispatch-pin-b2").unwrap();
}

#[test]
fn dispatch_manifest_refuses_consumer_floor_violation_regardless_of_manifest() {
    let root = sandbox("consumer-floor");
    let manifest = write_manifest(&root, "dispatch-consumer-floor", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    // The manifest's own storage_reserves (root, minimum_free_bytes: 1) is
    // trivially satisfied by the `free_space` probe below; the hardcoded
    // consumer floor is a SEPARATE, non-manifest-controlled gate driven by
    // the dedicated floor probe, which here reports far below the floor.
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(1),
        )
        .unwrap_err();
    assert!(
        matches!(error, EmberdError::DispatchConsumerFloorViolation { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(
        daemon.job_state("dispatch-consumer-floor").unwrap(),
        None
    );
    let receipt: Value = serde_json::from_slice(
        &fs::read(root.join("custody").join("dispatch-consumer-floor-preflight.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(receipt["result"], "REFUSED_CONSUMER_FLOOR");
    assert_eq!(receipt["consumer_floor"]["available_free_bytes"], 1);
}

#[test]
fn dispatch_manifest_vram_provider_unavailable_admits_with_disclosure() {
    // Continuation/resource law (reviewer correction 2026-07-18): no
    // numerical runtime provider may be REQUIRED until a direct named
    // source exists. A Driver-Locked provider (VRAM) reporting UNAVAILABLE
    // therefore does not block admission; safety is carried by the causal
    // owned-budget admission + Job wall + survival floors, and the receipt
    // truthfully discloses provider_status = "unavailable".
    let root = sandbox("vram-unavailable");
    let manifest = write_manifest(&root, "dispatch-vram-unavailable", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || {
                Err(EmberdError::VramProviderUnavailable {
                    detail: "no nvidia-smi on this host".into(),
                })
            },
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    let receipt: Value =
        serde_json::from_slice(&fs::read(&outcome.receipt.path).unwrap()).unwrap();
    assert_eq!(receipt["result"], "PREFLIGHT_PASSED");
    assert_eq!(receipt["vram_reserve"]["provider_status"], "unavailable");
    assert_eq!(receipt["vram_reserve"]["available_free_bytes"], Value::Null);
    assert_eq!(
        daemon.job_state("dispatch-vram-unavailable").unwrap(),
        Some(JobState::Running)
    );
    daemon.stop_job("dispatch-vram-unavailable").unwrap();
}

#[test]
fn dispatch_manifest_pinned_host_budget_admits_exactly_one_of_two_concurrent_overcommitting_dispatches(
) {
    // Deterministic interleaving harness (no sleeps): two real OS threads,
    // released together via a Barrier, race the SAME Daemon's admission
    // path with manifests that individually fit but jointly overcommit the
    // pinned host budget. The invariant this proves holds under EVERY
    // interleaving once the SUM-read + residual-decision + jobs-row INSERT
    // are atomic: exactly one dispatch is admitted and exactly one refuses
    // on the typed budget error -- never both, never neither.
    let root = sandbox("pinned-budget-concurrent");
    let daemon = std::sync::Arc::new(Daemon::open(&root.join("emberd.sqlite3")).unwrap());

    let manifest_a = write_manifest(&root, "dispatch-conc-a", 10_000);
    let mut payload_a: Value = serde_json::from_slice(&fs::read(&manifest_a).unwrap()).unwrap();
    payload_a["resource_lease"] = json!("gpu-conc-a");
    fs::write(&manifest_a, serde_json::to_vec(&payload_a).unwrap()).unwrap();

    let manifest_b = write_manifest(&root, "dispatch-conc-b", 10_000);
    let mut payload_b: Value = serde_json::from_slice(&fs::read(&manifest_b).unwrap()).unwrap();
    payload_b["resource_lease"] = json!("gpu-conc-b");
    fs::write(&manifest_b, serde_json::to_vec(&payload_b).unwrap()).unwrap();

    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));

    let run = |manifest: PathBuf, daemon: std::sync::Arc<Daemon>, barrier: std::sync::Arc<std::sync::Barrier>| {
        thread::spawn(move || {
            barrier.wait();
            daemon.dispatch_manifest_at_with_probes_and_host_and_floor(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(2048),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
                |_root| Ok(u64::MAX),
            )
        })
    };
    let t1 = run(manifest_a, daemon.clone(), barrier.clone());
    let t2 = run(manifest_b, daemon.clone(), barrier.clone());

    let r1 = t1.join().unwrap();
    let r2 = t2.join().unwrap();
    let results = [&r1, &r2];

    let admitted = results.iter().filter(|r| r.is_ok()).count();
    let refused_on_budget = results
        .iter()
        .filter(|r| matches!(r, Err(EmberdError::DispatchPinnedHostBudgetExceeded { .. })))
        .count();
    assert_eq!(
        admitted, 1,
        "exactly one concurrent overcommitting dispatch must be admitted: {r1:?} / {r2:?}"
    );
    assert_eq!(
        refused_on_budget, 1,
        "the other must refuse on the typed pinned-budget error: {r1:?} / {r2:?}"
    );
    assert_eq!(
        daemon.live_committed_job_memory_bytes().unwrap(),
        MAXIMUM_JOB_MEMORY_BYTES,
        "exactly the admitted job's declared budget stays live-committed"
    );
    let admitted_outcome = results.iter().find_map(|r| r.as_ref().ok()).unwrap();
    let admitted_receipt: Value =
        serde_json::from_slice(&fs::read(&admitted_outcome.receipt.path).unwrap()).unwrap();
    assert_eq!(
        admitted_receipt["result"], "PREFLIGHT_PASSED",
        "the admitted dispatch's own receipt must be the passing one"
    );
    // The loser leaves a truthful refusal receipt and ZERO committed state:
    // no job row, no lease, no bound identity survive its rollback.
    let (loser_job, loser_lease) = if r1.is_err() {
        ("dispatch-conc-a", "gpu-conc-a")
    } else {
        ("dispatch-conc-b", "gpu-conc-b")
    };
    let loser_receipt_path = root
        .join("custody")
        .join(format!("{loser_job}-preflight.json"));
    let loser_receipt: Value =
        serde_json::from_slice(&fs::read(&loser_receipt_path).unwrap()).unwrap();
    assert_eq!(loser_receipt["result"], "REFUSED_PINNED_HOST_BUDGET");
    assert_eq!(daemon.job_state(loser_job).unwrap(), None);
    assert_eq!(daemon.lease_owner(loser_lease).unwrap(), None);
    assert_eq!(daemon.identity_hash(loser_job).unwrap(), None);

    for job_id in ["dispatch-conc-a", "dispatch-conc-b"] {
        let _ = daemon.stop_job(job_id);
    }
}

#[test]
fn dispatch_manifest_refuses_a_receipt_path_already_claimed_by_another_job() {
    // Intentional same-path collision: job-id containment is non-injective
    // ("collide-a" is a substring of "collide-ab-preflight.json"), so two
    // DISTINCT jobs can both pass the filename scoping check with the same
    // receipt path. The atomic dispatch_receipt_claims row is what actually
    // refuses the second claim — and the winner's receipt bytes survive.
    let root = sandbox("receipt-claim-collision");
    let shared_receipt = root.join("custody").join("collide-ab-preflight.json");

    let manifest_ab = write_manifest(&root, "collide-ab", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest_ab,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert_eq!(
        outcome.receipt.path.file_name(),
        shared_receipt.file_name()
    );
    let winner_bytes = fs::read(&shared_receipt).unwrap();

    // Second, DISTINCT job declares the SAME receipt path (its job_id
    // "collide-a" is contained in the filename, so scoping alone passes).
    let manifest_a = write_manifest(&root, "collide-a", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest_a).unwrap()).unwrap();
    payload["preflight_receipt"] = json!(&shared_receipt);
    payload["resource_lease"] = json!("gpu-collide-a");
    fs::write(&manifest_a, serde_json::to_vec(&payload).unwrap()).unwrap();
    // With the winner's receipt file on disk, the fast pre-admission
    // exists-check refuses first — and the winner's bytes are untouched.
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest_a,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap_err();
    assert!(
        matches!(error, EmberdError::ReceiptAlreadyExists { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(daemon.job_state("collide-a").unwrap(), None);
    assert_eq!(fs::read(&shared_receipt).unwrap(), winner_bytes);

    // The exists-check alone is NOT the authority: simulate its blind spot
    // (receipt file gone — crash cleanup, tampering, or a race that passed
    // the check before the winner's write) and the atomic claims row in
    // the admission transaction must still refuse the foreign job.
    fs::remove_file(&shared_receipt).unwrap();
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest_a,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap_err();
    assert!(
        matches!(error, EmberdError::DispatchReceiptClaimConflict { .. }),
        "unexpected error: {error:?}"
    );
    assert_eq!(daemon.job_state("collide-a").unwrap(), None);
    assert!(
        !shared_receipt.exists(),
        "the refused collision must write nothing at the claimed path"
    );
    daemon.stop_job("collide-ab").unwrap();
}

#[test]
fn dispatch_refuses_while_a_pre_upgrade_live_job_has_unknown_receipt_identity() {
    // A live row persisted before dispatch_receipt_path existed is NULL —
    // an UNKNOWN receipt identity that may collide with any manifest's
    // path. Manifest admission fails closed (typed, naming the job) until
    // it exits; new rows always carry a path or the known-none sentinel.
    let root = sandbox("legacy-receipt-identity");
    let manifest = write_manifest(&root, "dispatch-post-receipt-upgrade", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    {
        let connection = rusqlite::Connection::open(root.join("emberd.sqlite3")).unwrap();
        connection
            .execute(
                "INSERT INTO jobs(job_id,program,args_json,env_json,resource,lease_epoch,job_object_name,argv_sha256,restart_policy,stdout_log_path,stderr_log_path,maximum_job_memory_bytes,dispatch_receipt_path,state,started_at_ms,updated_at_ms) VALUES('legacy-receipt-unknown','x','[]','{}','legacy-receipt-lease',1,'obj','deadbeef','never','out.log','err.log',1048576,NULL,'running',1,1)",
                [],
            )
            .unwrap();
    }
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap_err();
    match error {
        EmberdError::DispatchUnknownLegacyReceiptIdentity { job_ids } => {
            assert_eq!(job_ids, vec!["legacy-receipt-unknown".to_string()]);
        }
        other => panic!("unexpected error: {other:?}"),
    }
    assert_eq!(
        daemon.job_state("dispatch-post-receipt-upgrade").unwrap(),
        None
    );
    // Once the unknown-identity row exits, admission proceeds.
    {
        let connection = rusqlite::Connection::open(root.join("emberd.sqlite3")).unwrap();
        connection
            .execute(
                "UPDATE jobs SET state='exited' WHERE job_id='legacy-receipt-unknown'",
                [],
            )
            .unwrap();
    }
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome.receipt.path.exists());
    daemon.stop_job("dispatch-post-receipt-upgrade").unwrap();
}


#[test]
fn dispatch_refuses_while_a_pre_upgrade_live_job_has_unknown_budget() {
    // Upgrade-state reconciliation: a live job persisted BEFORE the
    // maximum_job_memory_bytes column existed carries the migration default
    // 0 (an UNKNOWN budget). Admission must fail CLOSED, naming the job,
    // until that job exits — counting it as zero would over-reserve.
    let root = sandbox("legacy-live-budget");
    let manifest = write_manifest(&root, "dispatch-post-upgrade", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    {
        let connection = rusqlite::Connection::open(root.join("emberd.sqlite3")).unwrap();
        connection
            .execute(
                "INSERT INTO jobs(job_id,program,args_json,env_json,resource,lease_epoch,job_object_name,argv_sha256,restart_policy,stdout_log_path,stderr_log_path,maximum_job_memory_bytes,state,started_at_ms,updated_at_ms) VALUES('legacy-pre-upgrade','x','[]','{}','legacy-lease',1,'obj','deadbeef','never','out.log','err.log',0,'running',1,1)",
                [],
            )
            .unwrap();
    }
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap_err();
    match error {
        EmberdError::DispatchUnknownLegacyLiveBudget { job_ids } => {
            assert_eq!(job_ids, vec!["legacy-pre-upgrade".to_string()]);
        }
        other => panic!("unexpected error: {other:?}"),
    }
    // The legacy job exiting clears the reconciliation block.
    {
        let connection = rusqlite::Connection::open(root.join("emberd.sqlite3")).unwrap();
        connection
            .execute(
                "UPDATE jobs SET state='exited' WHERE job_id='legacy-pre-upgrade'",
                [],
            )
            .unwrap();
    }
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host_and_floor(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            |_root| Ok(u64::MAX),
        )
        .unwrap();
    assert!(outcome.receipt.path.is_file());
    daemon.stop_job("dispatch-post-upgrade").unwrap();
}
