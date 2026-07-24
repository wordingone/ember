// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

use emberd::{
    CanaryHostSnapshot, CanaryProcessIdentity, Daemon, EmberdError, HostCommitCapacity, JobState,
};
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

fn emberd_source_sha256() -> String {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let sources = [
        root.join("src").join("lib.rs"),
        root.join("src").join("rpc.rs"),
        root.join("src").join("main.rs"),
        root.join("src").join("host_probe.rs"),
        root.join("Cargo.toml"),
        root.join("Cargo.lock"),
    ];
    let mut digest = Sha256::new();
    for source in sources {
        let bytes = fs::read(source).unwrap();
        digest.update((bytes.len() as u64).to_le_bytes());
        digest.update(bytes);
    }
    format!("{:x}", digest.finalize())
}

fn python_executable() -> PathBuf {
    let output = std::process::Command::new("where.exe")
        .arg("python.exe")
        .output()
        .unwrap();
    assert!(output.status.success());
    let first = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .unwrap()
        .to_string();
    fs::canonicalize(first).unwrap()
}

fn canary_snapshot(processes: Vec<CanaryProcessIdentity>) -> CanaryHostSnapshot {
    CanaryHostSnapshot {
        observed_at_ms: 10_001,
        gpu_uuid: "GPU-EMBER-CANARY".into(),
        free_vram_bytes: 24 * GIB,
        total_vram_bytes: 24 * GIB,
        nvidia_smi_sha256: "1".repeat(64),
        gpu_query_sha256: "2".repeat(64),
        compute_query_sha256: "3".repeat(64),
        process_inventory_sha256: "4".repeat(64),
        processes,
        wsl_detected: false,
        docker_detected: false,
        persistent_worker_detected: false,
    }
}

fn write_governed_canary_manifest(root: &Path, job_id: &str) -> PathBuf {
    let manifest = write_manifest(root, job_id, 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let program = python_executable();
    let emberd_binary = std::env::current_exe().unwrap();
    let certified_consumer = root.join("certified_train_launch.py");
    let disk_budget_runner = root.join("disk_budget_runner.py");
    let governed_runner = root.join("run_vertical_slice.py");
    let tokenizer = root.join("tokenizer.json");
    fs::write(&certified_consumer, b"# certified consumer\n").unwrap();
    fs::write(
        &disk_budget_runner,
        b"import time\nif __name__ == '__main__':\n    time.sleep(30)\n",
    )
    .unwrap();
    fs::write(&governed_runner, b"# governed runner\n").unwrap();
    fs::write(&tokenizer, b"{\"tokenizer\":\"owned\"}").unwrap();
    let certified_consumer = fs::canonicalize(certified_consumer).unwrap();
    let disk_budget_runner = fs::canonicalize(disk_budget_runner).unwrap();
    let governed_runner = fs::canonicalize(governed_runner).unwrap();
    let tokenizer = fs::canonicalize(tokenizer).unwrap();
    let config_path = payload["bindings"][0]["path"].as_str().unwrap().to_string();
    let config_sha256 = payload["bindings"][0]["sha256"]
        .as_str()
        .unwrap()
        .to_string();
    payload["program"] = json!({"path":&program,"sha256":sha256(&program)});
    payload["args"] = json!([
        &disk_budget_runner,
        "--",
        &program,
        &governed_runner,
        "governed-vertical",
        "--config",
        &config_path,
        "--tokenizer",
        &tokenizer
    ]);
    payload["env"]
        .as_object_mut()
        .unwrap()
        .remove("EMBERD_DISPATCH_FIXTURE_CHILD");
    payload["bindings"].as_array_mut().unwrap().extend([
        json!({"kind":"certified_consumer","path":&certified_consumer,"sha256":sha256(&certified_consumer)}),
        json!({"kind":"disk_budget_runner","path":&disk_budget_runner,"sha256":sha256(&disk_budget_runner)}),
        json!({"kind":"governed_runner","path":&governed_runner,"sha256":sha256(&governed_runner)}),
        json!({"kind":"tokenizer","path":&tokenizer,"sha256":sha256(&tokenizer)}),
    ]);
    payload["schema_version"] = json!("emberd-governed-canary-dispatch-v1");
    payload["minimum_free_vram_bytes"] = json!(20 * GIB);
    payload["resource_lease"] = json!("gpu:GPU-EMBER-CANARY:bounded-canary");
    payload["canary_scope"] = json!({
        "dispatch_kind": "governed_vertical",
        "expected_gpu_uuid": "GPU-EMBER-CANARY",
        "minimum_free_vram_bytes": 20 * GIB,
        "lease_id": "gpu:GPU-EMBER-CANARY:bounded-canary",
        "expected_emberd_binary_sha256": sha256(&emberd_binary),
        "expected_emberd_source_sha256": emberd_source_sha256(),
        "certified_consumer": {"path": &certified_consumer, "sha256": sha256(&certified_consumer)},
        "disk_budget_runner": {"path": &disk_budget_runner, "sha256": sha256(&disk_budget_runner)},
        "governed_runner": {"path": &governed_runner, "sha256": sha256(&governed_runner)},
        "config": {"path": config_path, "sha256": config_sha256},
        "tokenizer": {"path": &tokenizer, "sha256": sha256(&tokenizer)},
        "forbidden_process_names": ["llama-server.exe", "qwen.exe"],
        "wsl_allowed": false,
        "docker_allowed": false,
        "persistent_worker_allowed": false
    });
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    manifest
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
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
fn governed_canary_refuses_the_legacy_dispatch_path_without_a_host_probe() {
    let root = sandbox("governed-canary-no-probe");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-no-probe");
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(u64::MAX),
            || Ok(24 * GIB),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("governed-canary-no-probe").unwrap(), None);
}

#[test]
fn governed_canary_persists_a_first_probe_refusal_before_identity_or_lease() {
    let root = sandbox("governed-canary-first-probe-refusal");
    let job_id = "governed-canary-first-probe-refusal";
    let lease_id = "gpu:GPU-EMBER-CANARY:bounded-canary";
    let manifest = write_governed_canary_manifest(&root, job_id);
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let mut probes = 0;
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || {
            probes += 1;
            Err(EmberdError::InvalidDispatchManifest {
                detail: "authoritative native probe unavailable".into(),
            })
        },
    );
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(probes, 1);
    assert_eq!(daemon.job_state(job_id).unwrap(), None);
    assert_eq!(daemon.identity_hash(job_id).unwrap(), None);
    assert_eq!(daemon.lease_owner(lease_id).unwrap(), None);
    let receipt: Value =
        serde_json::from_slice(&fs::read(root.join("custody").join("preflight.json")).unwrap())
            .unwrap();
    assert_eq!(receipt["result"], "REFUSED_CANARY_HOST_PROBE");
    assert_eq!(
        receipt["governed_canary"]["process_exclusivity"],
        "EMPTY_PRESPAWN_GPU_COMPUTE_SET_REQUIRED"
    );
    assert!(receipt["governed_canary"]["before"].is_null());
    assert!(receipt["governed_canary"]["before_spawn"].is_null());
}

#[test]
fn governed_canary_refuses_a_scope_hash_without_an_exact_file_binding() {
    let root = sandbox("governed-canary-unbound-hash");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-unbound-hash");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let tokenizer_sha = payload["canary_scope"]["tokenizer"]["sha256"]
        .as_str()
        .unwrap()
        .to_string();
    payload["bindings"]
        .as_array_mut()
        .unwrap()
        .retain(|binding| binding["sha256"] != tokenizer_sha);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let mut probes = 0;
    assert!(matches!(
        daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
            &bytes,
            &digest,
            &manifest,
            10_001,
            |_root| Ok(u64::MAX),
            || Ok(24 * GIB),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            || {
                probes += 1;
                Ok(canary_snapshot(Vec::new()))
            },
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(probes, 0);
    assert_eq!(
        daemon.job_state("governed-canary-unbound-hash").unwrap(),
        None
    );
}

#[test]
fn governed_canary_refuses_swapped_semantic_role_hashes() {
    let root = sandbox("governed-canary-role-swap");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-role-swap");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let source_sha = payload["canary_scope"]["certified_consumer"]["sha256"].clone();
    let tokenizer_sha = payload["canary_scope"]["tokenizer"]["sha256"].clone();
    payload["canary_scope"]["certified_consumer"]["sha256"] = tokenizer_sha;
    payload["canary_scope"]["tokenizer"]["sha256"] = source_sha;
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon.stop_job("governed-canary-role-swap").unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn governed_canary_refuses_a_semantic_role_bound_with_the_wrong_kind() {
    let root = sandbox("governed-canary-role-kind");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-role-kind");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let source_sha = payload["canary_scope"]["certified_consumer"]["sha256"]
        .as_str()
        .unwrap()
        .to_string();
    for binding in payload["bindings"].as_array_mut().unwrap() {
        if binding["sha256"] == source_sha {
            binding["kind"] = json!("input");
        }
    }
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon.stop_job("governed-canary-role-kind").unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn governed_canary_refuses_a_duplicate_semantic_role_binding() {
    let root = sandbox("governed-canary-duplicate-role");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-duplicate-role");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let duplicate_source = root.join("duplicate-certified-source.py");
    fs::write(&duplicate_source, b"# duplicate certified source\n").unwrap();
    payload["bindings"]
        .as_array_mut()
        .unwrap()
        .push(json!({"kind":"certified_consumer","path":duplicate_source,"sha256":sha256(&duplicate_source)}));
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon.stop_job("governed-canary-duplicate-role").unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn governed_canary_refuses_a_governed_runner_not_equal_to_the_argv_chain() {
    let root = sandbox("governed-canary-governed-runner-drift");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-governed-runner-drift");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let unrelated_runner = root.join("unrelated-governed-runner.py");
    fs::write(&unrelated_runner, b"# unrelated runner\n").unwrap();
    payload["canary_scope"]["governed_runner"] =
        json!({"path": unrelated_runner, "sha256": sha256(&unrelated_runner)});
    for binding in payload["bindings"].as_array_mut().unwrap() {
        if binding["kind"] == "governed_runner" {
            binding["path"] = json!(unrelated_runner);
            binding["sha256"] = json!(sha256(&unrelated_runner));
        }
    }
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon
            .stop_job("governed-canary-governed-runner-drift")
            .unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn governed_canary_refuses_a_bound_governed_runner_missing_from_argv() {
    let root = sandbox("governed-canary-missing-governed-argv");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-missing-governed-argv");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["args"].as_array_mut().unwrap().pop();
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(
        daemon
            .identity_hash("governed-canary-missing-governed-argv")
            .unwrap(),
        None
    );
}

#[test]
fn governed_canary_refuses_a_config_binding_not_equal_to_the_argv_chain() {
    let root = sandbox("governed-canary-config-drift");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-config-drift");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let unrelated_config = root.join("unrelated-config.json");
    fs::write(&unrelated_config, b"{\"model\":\"other\"}").unwrap();
    payload["canary_scope"]["config"] =
        json!({"path": unrelated_config, "sha256": sha256(&unrelated_config)});
    for binding in payload["bindings"].as_array_mut().unwrap() {
        if binding["kind"] == "config" {
            binding["path"] = json!(unrelated_config);
            binding["sha256"] = json!(sha256(&unrelated_config));
        }
    }
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon.stop_job("governed-canary-config-drift").unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { ref detail })
            if detail.contains("config argv binding")
    ));
}

#[test]
fn governed_canary_refuses_a_tokenizer_binding_not_equal_to_the_argv_chain() {
    let root = sandbox("governed-canary-tokenizer-drift");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-tokenizer-drift");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let unrelated_tokenizer = root.join("unrelated-tokenizer.json");
    fs::write(&unrelated_tokenizer, b"{\"tokenizer\":\"other\"}").unwrap();
    payload["canary_scope"]["tokenizer"] =
        json!({"path": unrelated_tokenizer, "sha256": sha256(&unrelated_tokenizer)});
    for binding in payload["bindings"].as_array_mut().unwrap() {
        if binding["kind"] == "tokenizer" {
            binding["path"] = json!(unrelated_tokenizer);
            binding["sha256"] = json!(sha256(&unrelated_tokenizer));
        }
    }
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon.stop_job("governed-canary-tokenizer-drift").unwrap();
    }
    assert!(
        matches!(
            result,
            Err(EmberdError::InvalidDispatchManifest { ref detail })
                if detail.contains("tokenizer argv binding")
        ),
        "unexpected result: {result:?}"
    );
}

#[test]
fn governed_canary_refuses_a_substituted_forbidden_process_policy() {
    let root = sandbox("governed-canary-forbidden-policy-substitution");
    let manifest =
        write_governed_canary_manifest(&root, "governed-canary-forbidden-policy-substitution");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["canary_scope"]["forbidden_process_names"] = json!(["benign.exe"]);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon
            .stop_job("governed-canary-forbidden-policy-substitution")
            .unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn governed_canary_refuses_an_incomplete_forbidden_process_policy() {
    let root = sandbox("governed-canary-forbidden-policy-omission");
    let manifest =
        write_governed_canary_manifest(&root, "governed-canary-forbidden-policy-omission");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["canary_scope"]["forbidden_process_names"] = json!(["llama-server.exe"]);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    if result.is_ok() {
        daemon
            .stop_job("governed-canary-forbidden-policy-omission")
            .unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
}

#[test]
fn governed_canary_refuses_any_foreign_gpu_compute_process_before_spawn() {
    let root = sandbox("governed-canary-foreign-compute");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-foreign-compute");
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let foreign = CanaryProcessIdentity {
        pid: 998,
        parent_pid: 1,
        start_token: 122,
        image_name: "python.exe".into(),
        image_sha256: "4".repeat(64),
        gpu_uuid: Some("GPU-EMBER-CANARY".into()),
    };
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(vec![foreign.clone()])),
    );
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(
        daemon
            .lease_owner("gpu:GPU-EMBER-CANARY:bounded-canary")
            .unwrap(),
        None
    );
    assert_eq!(
        daemon
            .identity_hash("governed-canary-foreign-compute")
            .unwrap(),
        None
    );
    let receipt: Value =
        serde_json::from_slice(&fs::read(root.join("custody").join("preflight.json")).unwrap())
            .unwrap();
    assert_eq!(receipt["result"], "REFUSED_CANARY_HOST_PROBE");
    assert_eq!(
        receipt["governed_canary"]["process_exclusivity"],
        "EMPTY_PRESPAWN_GPU_COMPUTE_SET_REQUIRED"
    );
}

#[test]
fn governed_canary_refuses_gpu_process_identity_drift_before_spawn() {
    let root = sandbox("governed-canary-drift");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-drift");
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let mut probes = 0;
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || {
            probes += 1;
            let process = (probes == 2).then_some(CanaryProcessIdentity {
                pid: 999,
                parent_pid: 1,
                start_token: 123,
                image_name: "python.exe".into(),
                image_sha256: "5".repeat(64),
                gpu_uuid: Some("GPU-EMBER-CANARY".into()),
            });
            Ok(canary_snapshot(process.into_iter().collect()))
        },
    );
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(probes, 2);
    assert_eq!(daemon.job_state("governed-canary-drift").unwrap(), None);
    assert_eq!(
        daemon
            .lease_owner("gpu:GPU-EMBER-CANARY:bounded-canary")
            .unwrap(),
        None
    );
}

#[test]
fn governed_canary_refuses_execution_file_replacement_after_final_host_probe() {
    let root = sandbox("governed-canary-execution-file-replacement");
    let job_id = "governed-canary-execution-file-replacement";
    let manifest = write_governed_canary_manifest(&root, job_id);
    let payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    let governed_runner = PathBuf::from(
        payload["canary_scope"]["governed_runner"]["path"]
            .as_str()
            .unwrap(),
    );
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let mut probe_count = 0;
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || {
            probe_count += 1;
            if probe_count == 2 {
                fs::write(&governed_runner, b"# replaced after admission\n").unwrap();
            }
            Ok(canary_snapshot(Vec::new()))
        },
    );
    if result.is_ok() {
        daemon.stop_job(job_id).unwrap();
    }
    assert!(matches!(
        result,
        Err(EmberdError::DispatchBindingMismatch { .. })
    ));
    assert_eq!(probe_count, 2);
    assert_eq!(daemon.job_state(job_id).unwrap(), None);
    assert_eq!(
        daemon
            .lease_owner("gpu:GPU-EMBER-CANARY:bounded-canary")
            .unwrap(),
        None
    );
}

#[test]
fn governed_canary_acquires_the_gpu_lease_before_the_final_host_probe() {
    let root = sandbox("governed-canary-lease-before-final-probe");
    let job_id = "governed-canary-lease-before-final-probe";
    let lease_id = "gpu:GPU-EMBER-CANARY:bounded-canary";
    let manifest = write_governed_canary_manifest(&root, job_id);
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let mut probes = 0;
    let mut final_probe_observed_lease = false;
    let outcome = daemon
        .dispatch_governed_canary_manifest_bytes_at_with_probes(
            &bytes,
            &digest,
            &manifest,
            10_001,
            |_root| Ok(u64::MAX),
            || Ok(24 * GIB),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            || {
                probes += 1;
                if probes == 2 {
                    final_probe_observed_lease =
                        daemon.lease_owner(lease_id)?.as_deref() == Some(job_id);
                }
                Ok(canary_snapshot(Vec::new()))
            },
        )
        .unwrap();
    assert_eq!(probes, 2);
    assert!(
        final_probe_observed_lease,
        "the final host probe must run after the exact GPU lease is acquired"
    );
    daemon.stop_job(job_id).unwrap();
    assert!(outcome.handle.pid > 0);
}

#[test]
fn governed_canary_refuses_unexplained_free_vram_loss_after_lease() {
    let root = sandbox("governed-canary-free-vram-drift");
    let job_id = "governed-canary-free-vram-drift";
    let lease_id = "gpu:GPU-EMBER-CANARY:bounded-canary";
    let manifest = write_governed_canary_manifest(&root, job_id);
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let mut probes = 0;
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &bytes,
        &digest,
        &manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || {
            probes += 1;
            let mut snapshot = canary_snapshot(Vec::new());
            if probes == 2 {
                snapshot.free_vram_bytes -= GIB;
            }
            Ok(snapshot)
        },
    );
    assert!(matches!(
        result,
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(probes, 2);
    assert_eq!(daemon.job_state(job_id).unwrap(), None);
    assert_eq!(daemon.lease_owner(lease_id).unwrap(), None);
    assert_eq!(daemon.identity_hash(job_id).unwrap(), None);
    let receipt: Value =
        serde_json::from_slice(&fs::read(root.join("custody").join("preflight.json")).unwrap())
            .unwrap();
    assert_eq!(receipt["result"], "REFUSED_CANARY_HOST_DRIFT");
    assert_eq!(
        receipt["governed_canary"]["process_exclusivity"],
        "EMPTY_PRESPAWN_GPU_COMPUTE_SET_REQUIRED"
    );
    assert_eq!(
        receipt["governed_canary"]["before"]["free_vram_bytes"],
        24 * GIB
    );
    assert_eq!(
        receipt["governed_canary"]["before_spawn"]["free_vram_bytes"],
        23 * GIB
    );
}

#[test]
fn governed_canary_persists_a_refusal_when_the_gpu_lease_has_an_owner() {
    let daemon_root = sandbox("governed-canary-lease-conflict-daemon");
    let first_root = sandbox("governed-canary-lease-conflict-first");
    let second_root = sandbox("governed-canary-lease-conflict-second");
    let lease_id = "gpu:GPU-EMBER-CANARY:bounded-canary";
    let first_manifest = write_governed_canary_manifest(&first_root, "governed-canary-owner");
    let second_manifest = write_governed_canary_manifest(&second_root, "governed-canary-contender");
    let daemon = Daemon::open(&daemon_root.join("emberd.sqlite3")).unwrap();
    let first_bytes = fs::read(&first_manifest).unwrap();
    let first_digest = format!("{:x}", Sha256::digest(&first_bytes));
    daemon
        .dispatch_governed_canary_manifest_bytes_at_with_probes(
            &first_bytes,
            &first_digest,
            &first_manifest,
            10_001,
            |_root| Ok(u64::MAX),
            || Ok(24 * GIB),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            || Ok(canary_snapshot(Vec::new())),
        )
        .unwrap();
    let second_bytes = fs::read(&second_manifest).unwrap();
    let second_digest = format!("{:x}", Sha256::digest(&second_bytes));
    let result = daemon.dispatch_governed_canary_manifest_bytes_at_with_probes(
        &second_bytes,
        &second_digest,
        &second_manifest,
        10_001,
        |_root| Ok(u64::MAX),
        || Ok(24 * GIB),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        || Ok(canary_snapshot(Vec::new())),
    );
    assert!(matches!(result, Err(EmberdError::LeaseConflict { .. })));
    assert_eq!(
        daemon.lease_owner(lease_id).unwrap().as_deref(),
        Some("governed-canary-owner")
    );
    assert_eq!(
        daemon.identity_hash("governed-canary-contender").unwrap(),
        None
    );
    let receipt: Value = serde_json::from_slice(
        &fs::read(second_root.join("custody").join("preflight.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(receipt["result"], "REFUSED_CANARY_LEASE_CONFLICT");
    assert_eq!(
        receipt["governed_canary"]["process_exclusivity"],
        "EMPTY_PRESPAWN_GPU_COMPUTE_SET_REQUIRED"
    );
    daemon.stop_job("governed-canary-owner").unwrap();
}

#[test]
fn governed_canary_binds_two_stable_host_snapshots_into_the_preflight_receipt() {
    let root = sandbox("governed-canary-green");
    let manifest = write_governed_canary_manifest(&root, "governed-canary-green");
    let bytes = fs::read(&manifest).unwrap();
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_governed_canary_manifest_bytes_at_with_probes(
            &bytes,
            &digest,
            &manifest,
            10_001,
            |_root| Ok(u64::MAX),
            || Ok(24 * GIB),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            || Ok(canary_snapshot(Vec::new())),
        )
        .unwrap();
    let receipt: Value = serde_json::from_slice(&fs::read(&outcome.receipt.path).unwrap()).unwrap();
    assert_eq!(
        receipt["governed_canary"]["scope"]["dispatch_kind"],
        "governed_vertical"
    );
    assert_eq!(
        receipt["governed_canary"]["before"]["gpu_uuid"],
        "GPU-EMBER-CANARY"
    );
    assert_eq!(
        receipt["governed_canary"]["before_spawn"]["gpu_uuid"],
        "GPU-EMBER-CANARY"
    );
    daemon.stop_job("governed-canary-green").unwrap();
}

#[test]
fn identical_dispatch_retry_reconstructs_the_existing_job_and_receipt() {
    let root = sandbox("idempotent-retry");
    let manifest = write_manifest(&root, "dispatch-idempotent-retry", 10_000);
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let first = daemon
        .dispatch_manifest_bytes_at_with_probes_and_host(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    let second = daemon
        .dispatch_manifest_bytes_at_with_probes_and_host(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
    let receipt_path = root.join("custody").join("preflight.json");
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();

    let first = daemon.dispatch_manifest_at_with_probes_and_host(
        &manifest,
        10_001,
        |_root| Ok(1024),
        || {
            fs::create_dir(&receipt_path).unwrap();
            Ok(2048)
        },
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
    payload["preflight_receipt"] = json!(root.join("custody").join("second-preflight.json"));
    fs::write(&second, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    daemon
        .dispatch_manifest_at_with_probes_and_host(
            &first,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &second,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberdError::LeaseConflict { .. })
    ));
    assert!(!root.join("custody").join("second-preflight.json").exists());
    assert_eq!(daemon.job_state("dispatch-lease-second").unwrap(), None);
    assert_eq!(daemon.identity_hash("dispatch-lease-second").unwrap(), None);
    daemon.stop_job("dispatch-lease-first").unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &second,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .is_err());
    assert!(!root.join("custody").join("preflight.json").exists());
    assert_eq!(daemon.job_state("dispatch-spawn-retry").unwrap(), None);
    assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
    assert_eq!(daemon.identity_hash("dispatch-spawn-retry").unwrap(), None);
    let repaired = write_manifest(&root, "dispatch-spawn-retry", 10_000);
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &repaired,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-stale-v1").unwrap(), None);
    assert!(!root.join("custody").join("preflight.json").exists());
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
            .dispatch_manifest_at_with_probes_and_host(
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
            )
            .unwrap_err();
        assert!(format!("{error:?}").contains("DispatchHostCommitReserve"));
        let receipt: Value =
            serde_json::from_slice(&fs::read(root.join("custody").join("preflight.json")).unwrap())
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
            .dispatch_manifest_at_with_probes_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(2048),
                || Ok(host_capacity(observed_free)),
            )
            .unwrap_err();
        assert!(
            format!("{error:?}").contains("DispatchHostCommitReserve"),
            "unexpected error: {error:?}"
        );
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        let receipt_path = root.join("custody").join("preflight.json");
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
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
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
            .dispatch_manifest_at_with_probes_and_host(
                &manifest,
                now_ms,
                |_root| Ok(free_bytes),
                || Ok(free_vram),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-binding-classes").unwrap(), None);
    assert!(!root.join("custody").join("preflight.json").exists());
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
        daemon.dispatch_manifest_bytes_at_with_probes_and_host(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberdError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(fs::read(&custody_snapshot).unwrap(), b"{\"attacker\":true}");
    assert!(!root.join("custody").join("preflight.json").exists());
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
    payload["preflight_receipt"] = json!(unapproved.join("preflight.json"));
    let manifest_bytes = serde_json::to_vec(&payload).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();

    assert!(matches!(
        daemon.dispatch_manifest_bytes_at_with_probes_and_host(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
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
            json!(root.join("custody").join(format!("snapshot-{index}.json")));
        let bytes = serde_json::to_vec(&payload).unwrap();
        let digest = format!("{:x}", Sha256::digest(&bytes));
        assert!(matches!(
            daemon.dispatch_manifest_bytes_at_with_probes_and_host(
                &bytes,
                &digest,
                10_001,
                |_root| Ok(1024),
                || Ok(2048),
                || Ok(host_capacity(0)),
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
        daemon.dispatch_manifest_bytes_at_with_probes_and_host(
            &duplicate_bytes,
            &duplicate_digest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(0)),
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
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
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(0),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
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
            daemon.dispatch_manifest_at_with_probes_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            ),
            Err(EmberdError::InvalidDispatchManifest { .. })
        ));
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        assert!(!root.join("custody").join("preflight.json").exists());
    }
}
