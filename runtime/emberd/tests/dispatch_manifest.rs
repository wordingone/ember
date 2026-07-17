// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

use emberd::{Daemon, EmberdError, JobState};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

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
    let manifest = root.join("dispatch.json");
    fs::write(
        &manifest,
        serde_json::to_vec(&json!({
            "schema_version": "emberd-dispatch-manifest-v1",
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
        "maximum_job_memory_bytes": 1_073_741_824u64,
        "preflight_receipt": root.join("custody").join("preflight.json")
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
        .dispatch_manifest_at_with_probes(&manifest, 10_001, |_root| Ok(1024), || Ok(2048))
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
    assert_eq!(receipt["maximum_job_memory_bytes"], 1_073_741_824u64);
    daemon.stop_job("dispatch-green").unwrap();
}

#[test]
fn dispatch_job_memory_ceiling_terminates_an_over_allocation_probe() {
    let root = sandbox("job-memory-ceiling");
    let manifest = write_manifest(&root, "dispatch-memory-ceiling", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["maximum_job_memory_bytes"] = json!(134_217_728u64);
    payload["env"]["EMBERD_DISPATCH_ALLOCATE_BYTES"] = json!(536_870_912u64.to_string());
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    daemon
        .dispatch_manifest_at_with_probes(&manifest, 10_001, |_root| Ok(1024), || Ok(1024))
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
        daemon.dispatch_manifest_at_with_probes(&manifest, 10_001, |_root| Ok(1024), || Ok(1024),),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-missing-memory").unwrap(), None);
    assert!(!root.join("custody").join("preflight.json").exists());
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
            .dispatch_manifest_at_with_probes(
                &manifest,
                now_ms,
                |_root| Ok(free_bytes),
                || Ok(free_vram),
            )
            .unwrap_err();
        assert!(
            format!("{error:?}").contains(expected),
            "unexpected error: {error:?}"
        );
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
        assert!(!root.join("custody").join("preflight.json").exists());
    }
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
        daemon.dispatch_manifest_at_with_probes(&manifest, 10_001, |_root| Ok(1024), || Ok(1024),),
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
        daemon.dispatch_manifest_at_with_probes(&manifest, 10_001, |_root| Ok(1024), || Ok(1024),),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-binding-classes").unwrap(), None);
    assert!(!root.join("custody").join("preflight.json").exists());
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
            daemon.dispatch_manifest_at_with_probes(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
            ),
            Err(EmberdError::InvalidDispatchManifest { .. })
        ));
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        assert!(!root.join("custody").join("preflight.json").exists());
    }
}
