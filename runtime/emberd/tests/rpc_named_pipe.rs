// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// These legs spawn the REAL `emberd` binary out-of-process (CARGO_BIN_EXE_emberd)
// and drive it purely over the named-pipe RPC transport, then use
// EMBERD_TEST_FLOOR_FREE_BYTES / EMBERD_TEST_VRAM_PROVIDER_UNAVAILABLE env
// overrides for deterministic floor/VRAM fixtures. Both the daemon's
// env-override code paths AND the `emberd` binary itself are compiled ONLY
// under the `test-fixtures` Cargo feature (see `[features]` in Cargo.toml) —
// a plain `cargo build`/`cargo test` never contains this code, so it can
// never leak into a production binary. Run this suite with
// `cargo test --features test-fixtures`: Cargo's per-package feature
// unification rebuilds `[[bin]] emberd` (the same package as this lib) with
// the feature enabled for that invocation, so CARGO_BIN_EXE_emberd points at
// a feature-enabled binary automatically — no separate build step needed.

#![cfg(windows)]

use emberd::{probe_host_commit_capacity, MAX_DISPATCH_MANIFEST_BYTES};
use rusqlite::Connection;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

fn sandbox(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path =
        std::env::temp_dir().join(format!("emberd-rpc-{name}-{}-{nonce}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
}

fn bun_binary() -> PathBuf {
    if let Some(path) = std::env::var_os("BUN") {
        return PathBuf::from(path);
    }
    let output = Command::new("where.exe").arg("bun.cmd").output().unwrap();
    assert!(
        output.status.success(),
        "bun is required for the production TypeScript bridge test"
    );
    let paths = String::from_utf8(output.stdout).unwrap();
    let path = paths
        .lines()
        .next()
        .expect("where.exe returned no bun path")
        .trim();
    PathBuf::from(path)
}
fn emberd_binary() -> PathBuf {
    option_env!("CARGO_BIN_EXE_emberd")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("missing-emberd-binary"))
}

struct ServerGuard(Child);

impl Drop for ServerGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn start_server(binary: &Path, db: &Path, pipe: &str) -> ServerGuard {
    // Default pipe-test servers pin the survival-floor probe to a passing
    // deterministic value: these legs test transport/adoption/admission
    // semantics, and must not flake when the host's real free space hovers
    // near the consumer floors. Floor ENFORCEMENT has its own dedicated
    // deterministic legs (refusal + disclosure) below.
    start_server_with_env(
        binary,
        db,
        pipe,
        &[("EMBERD_TEST_FLOOR_FREE_BYTES", "18446744073709551615")],
    )
}

fn rpc_error(pipe: &str, id: u64, method: &str, params: Value) -> Value {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        match OpenOptions::new().read(true).write(true).open(pipe) {
            Ok(mut stream) => {
                let request = json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": method,
                    "params": params,
                });
                writeln!(stream, "{}", serde_json::to_string(&request).unwrap()).unwrap();
                stream.flush().unwrap();
                let mut response = String::new();
                BufReader::new(stream).read_line(&mut response).unwrap();
                let response: Value = serde_json::from_str(&response).unwrap();
                assert_eq!(response["jsonrpc"], "2.0");
                assert_eq!(response["id"], id);
                assert!(
                    response.get("error").is_some(),
                    "RPC {method} unexpectedly succeeded: {response}"
                );
                return response["error"].clone();
            }
            Err(error) if Instant::now() < deadline => {
                let _ = error;
                thread::sleep(Duration::from_millis(20));
            }
            Err(error) => panic!("timed out connecting to {pipe}: {error}"),
        }
    }
}

fn rpc(pipe: &str, id: u64, method: &str, params: Value) -> Value {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        match OpenOptions::new().read(true).write(true).open(pipe) {
            Ok(mut stream) => {
                let request = json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": method,
                    "params": params,
                });
                writeln!(stream, "{}", serde_json::to_string(&request).unwrap()).unwrap();
                stream.flush().unwrap();
                let mut response = String::new();
                BufReader::new(stream).read_line(&mut response).unwrap();
                let response: Value = serde_json::from_str(&response).unwrap();
                assert_eq!(response["jsonrpc"], "2.0");
                assert_eq!(response["id"], id);
                assert!(
                    response.get("error").is_none(),
                    "RPC {method} failed: {response}"
                );
                return response["result"].clone();
            }
            Err(error) if Instant::now() < deadline => {
                let _ = error;
                thread::sleep(Duration::from_millis(20));
            }
            Err(error) => panic!("timed out connecting to {pipe}: {error}"),
        }
    }
}

fn wait_for_exit(server: &mut ServerGuard) {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if server.0.try_wait().unwrap().is_some() {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "emberd did not exit after shutdown"
        );
        thread::sleep(Duration::from_millis(20));
    }
}

fn write_dispatch_manifest(root: &Path, job_id: &str) -> PathBuf {
    let custody = root.join("custody");
    fs::create_dir_all(&custody).unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBERD_RPC_FIXTURE_CHILD".to_string(), "1".to_string());
    for key in [
        "TEMP",
        "TMP",
        "TORCH_HOME",
        "TRITON_CACHE_DIR",
        "CUDA_CACHE_PATH",
        "HF_HOME",
        "XDG_CACHE_HOME",
    ] {
        let path = custody.join(key.to_ascii_lowercase());
        fs::create_dir_all(&path).unwrap();
        env.insert(key.to_string(), path.to_string_lossy().into_owned());
    }
    let config = root.join("config.json");
    fs::write(&config, b"{\"dispatch\":\"bound\"}").unwrap();
    let data_manifest = root.join("data-manifest.json");
    fs::write(&data_manifest, b"{\"records\":4096}").unwrap();
    let program = std::env::current_exe().unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let host_commit = probe_host_commit_capacity().unwrap();
    let maximum_job_memory_bytes = 1_073_741_824u64;
    let declared_available_maximum_commit_bytes =
        10 * 1024 * 1024 * 1024 + maximum_job_memory_bytes;
    assert!(host_commit.available_maximum_commit_bytes >= declared_available_maximum_commit_bytes);
    let manifest = root.join("dispatch.json");
    fs::write(
        &manifest,
        serde_json::to_vec(&json!({
            "schema_version": "emberd-dispatch-manifest-v2",
            "job_id": job_id,
            "source_commit": "5326043c344227c1b145a4ddbb3519cfa62d4943",
            "not_before_ms": now - 1_000,
            "expires_at_ms": now + 60_000,
            "resource_lease": "gpu-dispatch-cli",
            "program": {"path": program, "sha256": sha256(&program)},
            "args": ["--exact", "fixture_rpc_child_process", "--nocapture"],
            "env": env,
            "bindings": [
                {"kind": "config", "path": config, "sha256": sha256(&config)},
                {"kind": "manifest", "path": data_manifest, "sha256": sha256(&data_manifest)}
            ],
            "custody_root": custody,
            "storage_reserves": [{"root": root, "minimum_free_bytes": 1}],
            "minimum_free_vram_bytes": 1,
            "required_available_maximum_commit_bytes": declared_available_maximum_commit_bytes,
            "maximum_job_memory_bytes": maximum_job_memory_bytes,
            "simulated_peak_commit_bytes": 536_870_912u64,
            "preflight_receipt": root.join("custody").join(format!("{job_id}-preflight.json"))
        }))
        .unwrap(),
    )
    .unwrap();
    manifest
}

fn pad_dispatch_manifest_to_exact_bytes(path: &Path, target_bytes: usize) {
    let mut manifest: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    manifest["env"]
        .as_object_mut()
        .unwrap()
        .insert("EMBERD_TEST_PADDING".into(), Value::String(String::new()));
    let encoded_without_padding = serde_json::to_vec(&manifest).unwrap();
    assert!(encoded_without_padding.len() <= target_bytes);
    let remaining = target_bytes - encoded_without_padding.len();
    let padding = format!(
        "{}{}",
        "\\".repeat(remaining / 2),
        "x".repeat(remaining % 2)
    );
    manifest["env"]
        .as_object_mut()
        .unwrap()
        .insert("EMBERD_TEST_PADDING".into(), Value::String(padding));
    let encoded = serde_json::to_vec(&manifest).unwrap();
    assert_eq!(encoded.len(), target_bytes);
    fs::write(path, encoded).unwrap();
}
#[test]
fn fixture_rpc_child_process() {
    if std::env::var("EMBERD_RPC_FIXTURE_CHILD").as_deref() == Ok("1") {
        thread::sleep(Duration::from_secs(30));
    }
}

#[test]
fn dispatch_cli_uses_persistent_named_pipe_daemon_and_governed_spawn() {
    let root = sandbox("dispatch-cli");
    let db = root.join("emberd.sqlite3");
    let pipe = format!(
        r"\\.\pipe\emberd-dispatch-cli-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "dispatch-cli-job");
    let mut server = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 100, "ping", json!({}))["status"], "ok");

    let output = Command::new(&binary)
        .args([
            "dispatch",
            "--pipe",
            &pipe,
            "--manifest",
            &manifest.to_string_lossy(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "dispatch CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(result["pid"].as_u64().unwrap() > 0);
    let receipt = PathBuf::from(result["preflight_receipt_path"].as_str().unwrap());
    assert_eq!(sha256(&receipt), result["preflight_receipt_sha256"]);
    // The REAL binary's receipt must disclose the increment-1 admission
    // evidence end-to-end: the consumer survival-floor probes and the VRAM
    // provider status ("unavailable" admits with truthful disclosure under
    // the provider-availability law; "available" enforces the minimum).
    let receipt_json: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(receipt_json["result"], "PREFLIGHT_PASSED");
    let floors = receipt_json["consumer_floor"].as_array().unwrap();
    assert!(
        !floors.is_empty(),
        "receipt must carry per-root consumer floor evidence: {receipt_json}"
    );
    for floor in floors {
        assert!(floor["root"].is_string());
        assert!(floor["minimum_free_bytes"].as_u64().unwrap() > 0);
        assert!(
            floor["available_free_bytes"].as_u64().unwrap()
                >= floor["minimum_free_bytes"].as_u64().unwrap()
        );
    }
    let provider_status = receipt_json["vram_reserve"]["provider_status"]
        .as_str()
        .unwrap();
    assert!(
        provider_status == "available" || provider_status == "unavailable",
        "provider_status must be disclosed truthfully: {receipt_json}"
    );
    assert_eq!(
        rpc(
            &pipe,
            101,
            "job_state",
            json!({"job_id": "dispatch-cli-job"})
        )["state"],
        "running"
    );
    rpc(
        &pipe,
        102,
        "stop_job",
        json!({"job_id": "dispatch-cli-job"}),
    );
    rpc(&pipe, 103, "shutdown", json!({}));
    wait_for_exit(&mut server);
}

#[test]
fn named_pipe_dispatch_accepts_the_exact_manifest_transport_ceiling() {
    const MAX_MANIFEST_TRANSPORT_BYTES: usize = MAX_DISPATCH_MANIFEST_BYTES;
    let root = sandbox("dispatch-transport-ceiling");
    let db = root.join("emberd.sqlite3");
    let pipe = format!(
        r"\\.\pipe\emberd-dispatch-transport-ceiling-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "dispatch-transport-ceiling-job");
    pad_dispatch_manifest_to_exact_bytes(&manifest, MAX_MANIFEST_TRANSPORT_BYTES);
    assert_eq!(
        fs::metadata(&manifest).unwrap().len(),
        MAX_MANIFEST_TRANSPORT_BYTES as u64
    );
    let mut server = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 180, "ping", json!({}))["status"], "ok");
    let output = Command::new(&binary)
        .args([
            "dispatch",
            "--pipe",
            &pipe,
            "--manifest",
            &manifest.to_string_lossy(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "dispatch CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(result["pid"].as_u64().unwrap() > 0);
    rpc(
        &pipe,
        181,
        "stop_job",
        json!({"job_id": "dispatch-transport-ceiling-job"}),
    );
    rpc(&pipe, 182, "shutdown", json!({}));
    wait_for_exit(&mut server);
}
#[test]
fn named_pipe_dispatch_consumes_the_bound_manifest_bytes_after_source_mutation() {
    let root = sandbox("dispatch-bytes");
    let db = root.join("emberd.sqlite3");
    let pipe = format!(
        r"\\.\pipe\emberd-dispatch-bytes-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "dispatch-bytes-job");
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let manifest_utf8 = String::from_utf8(manifest_bytes).unwrap();
    fs::write(&manifest, b"{\"mutated_after_cli_read\":true}").unwrap();
    let mut server = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 200, "ping", json!({}))["status"], "ok");

    let result = rpc(
        &pipe,
        201,
        "dispatch_manifest",
        json!({"manifest_utf8": manifest_utf8.clone(), "manifest_sha256": manifest_sha256.clone()}),
    );
    assert!(result["pid"].as_u64().unwrap() > 0);
    let receipt = PathBuf::from(result["preflight_receipt_path"].as_str().unwrap());
    assert_eq!(sha256(&receipt), result["preflight_receipt_sha256"]);
    let replay = rpc(
        &pipe,
        202,
        "dispatch_manifest",
        json!({"manifest_utf8": manifest_utf8.clone(), "manifest_sha256": manifest_sha256.clone()}),
    );
    assert_eq!(replay["pid"], result["pid"]);
    assert_eq!(
        replay["preflight_receipt_sha256"],
        result["preflight_receipt_sha256"]
    );
    assert_eq!(
        rpc(
            &pipe,
            202,
            "job_state",
            json!({"job_id": "dispatch-bytes-job"})
        )["state"],
        "running"
    );
    rpc(
        &pipe,
        203,
        "stop_job",
        json!({"job_id": "dispatch-bytes-job"}),
    );
    rpc(&pipe, 205, "shutdown", json!({}));
    wait_for_exit(&mut server);
}
#[test]
fn named_pipe_rpc_survives_daemon_restart_and_controls_bound_job() {
    let root = sandbox("restart");
    let db = root.join("emberd.sqlite3");
    let identity = root.join("identity.json");
    let receipt = root.join("receipt.json");
    let alarm_path = root.join("schedule-alarms.json");
    let content_addressed_receipts = root.join("content-addressed-receipts");
    fs::write(
        &identity,
        br#"{"schema":"ember-identity-v1","model_id":"fixture-owned-3b","checkpoint_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","lineage":"clean_genesis"}"#,
    )
    .unwrap();
    let identity_hash = sha256(&identity);
    let pipe = format!(
        r"\\.\pipe\emberd-rpc-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = emberd_binary();
    assert!(
        binary.is_file(),
        "the resident emberd binary target must exist"
    );

    let mut first = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 1, "ping", json!({}))["status"], "ok");
    rpc(
        &pipe,
        2,
        "bind_identity",
        json!({
            "job_id": "rpc-job",
            "path": identity,
            "sha256": identity_hash,
        }),
    );
    rpc(
        &pipe,
        3,
        "acquire_lease",
        json!({"resource": "cpu-fixture", "job_id": "rpc-job"}),
    );
    let fixture = std::env::current_exe().unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBERD_RPC_FIXTURE_CHILD", "1");
    let started = rpc(
        &pipe,
        4,
        "start_job",
        json!({
            "job_id": "rpc-job",
            "program": fixture,
            "args": ["--exact", "fixture_rpc_child_process", "--nocapture"],
            "resource_lease": "cpu-fixture",
            "maximum_job_memory_bytes": 64 * 1024 * 1024,
            "env": env,
            "restart_policy": "never",
        }),
    );
    assert!(started["pid"].as_u64().unwrap() > 0);
    assert_eq!(
        rpc(&pipe, 5, "job_state", json!({"job_id": "rpc-job"}))["state"],
        "running"
    );

    rpc(&pipe, 6, "shutdown", json!({}));
    wait_for_exit(&mut first);

    let mut second = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 7, "ping", json!({}))["status"], "ok");
    assert_eq!(
        rpc(&pipe, 8, "job_state", json!({"job_id": "rpc-job"}))["state"],
        "running"
    );
    rpc(&pipe, 9, "stop_job", json!({"job_id": "rpc-job"}));
    assert!(rpc(&pipe, 10, "job_exit_code", json!({"job_id": "rpc-job"}))["exit_code"].is_null());
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let planned = rpc(
        &pipe,
        11,
        "plan_outage",
        json!({
            "resource": "cpu-fixture",
            "starts_at_ms": now + 60_000,
            "ends_at_ms": now + 120_000,
            "reason": "rpc typed-method proof",
        }),
    );
    assert!(planned["outage_id"].as_i64().unwrap() > 0);
    assert_eq!(
        rpc(
            &pipe,
            12,
            "cancel_outages",
            json!({"resource": "cpu-fixture"})
        )["cancelled"],
        1
    );
    rpc(
        &pipe,
        13,
        "export_receipt",
        json!({"job_id": "rpc-job", "path": receipt}),
    );
    let payload: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(payload["job_id"], "rpc-job");
    assert_eq!(payload["state"], "stopped");
    assert_eq!(payload["restart_policy"], "never");
    assert!(payload["events"]
        .as_array()
        .unwrap()
        .iter()
        .any(|event| event["kind"] == "job_adopted"));
    let artifact = rpc(
        &pipe,
        14,
        "export_content_addressed_receipt",
        json!({
            "job_id": "rpc-job",
            "directory": content_addressed_receipts,
        }),
    );
    let artifact_path = PathBuf::from(artifact["path"].as_str().unwrap());
    assert_eq!(sha256(&artifact_path), artifact["sha256"]);
    assert_eq!(
        artifact_path.file_name().unwrap().to_string_lossy(),
        format!("{}.json", artifact["sha256"].as_str().unwrap())
    );

    rpc(
        &pipe,
        15,
        "register_schedule_prediction",
        json!({
            "job_id": "rpc-job",
            "artifact_class": "cost-model",
            "predicted_duration_ms": 60_000,
            "predicted_tokens": 4096,
            "predicted_program_completion_ms": now + 10_000,
            "absolute_deadline_ms": now + 20_000,
        }),
    );
    rpc(
        &pipe,
        16,
        "acquire_lease",
        json!({"resource": "schedule:cost-model", "job_id": "rpc-job"}),
    );
    rpc(
        &pipe,
        17,
        "record_schedule_measurement",
        json!({
            "job_id": "rpc-job",
            "measured_duration_ms": 55_000,
            "measured_tokens": 4096,
            "outcome": "COMPLETED",
            "receipt_sha256": "b".repeat(64),
        }),
    );
    rpc(
        &pipe,
        18,
        "write_schedule_alarm_state",
        json!({"path": alarm_path}),
    );
    let alarm: Value = serde_json::from_slice(&fs::read(&alarm_path).unwrap()).unwrap();
    assert_eq!(alarm["schema_version"], "emberd-schedule-alarm-state-v1");
    assert_eq!(alarm["alarms"]["prediction_overrun"], false);
    assert_eq!(alarm["runs"][0]["measurement_outcome"], "COMPLETED");
    rpc(&pipe, 19, "shutdown", json!({}));
    wait_for_exit(&mut second);
}

#[test]
fn production_typescript_manifest_transport_reaches_the_real_named_pipe_daemon() {
    let root = sandbox("typescript-production-transport");
    let db = root.join("emberd.sqlite3");
    let pipe = format!(
        r"\\.\pipe\emberd-typescript-production-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "typescript-production-transport-job");
    let mut server = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 220, "ping", json!({}))["status"], "ok");

    let repository = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .canonicalize()
        .unwrap();
    let output = Command::new("cmd.exe")
        .args(["/D", "/S", "/C"])
        .arg(bun_binary())
        .current_dir(&repository)
        .env("EMBERD_REAL_DAEMON_PIPE", &pipe)
        .env("EMBERD_REAL_DAEMON_MANIFEST", &manifest)
        .args([
            "test",
            "tools/ember-cli/src/entrypoints/owned-server-supervisor.test.ts",
            "--test-name-pattern",
            "uses the production manifest_utf8 request type against the real Rust daemon",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "production TypeScript named-pipe transport failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        rpc(
            &pipe,
            221,
            "job_state",
            json!({"job_id": "typescript-production-transport-job"})
        )["state"],
        "running"
    );
    rpc(
        &pipe,
        222,
        "stop_job",
        json!({"job_id": "typescript-production-transport-job"}),
    );
    rpc(&pipe, 223, "shutdown", json!({}));
    wait_for_exit(&mut server);
}

// ---- Deterministic probe-fixture legs (reviewer-required): the REAL
// binary, driven over the real named pipe, with floor/provider probes made
// deterministic via transport-entrypoint-only env overrides. These exist
// because the host's real free space legitimately hovers near the consumer
// floors — a floor leg must not flake with the disk.

fn start_server_with_env(
    binary: &Path,
    db: &Path,
    pipe: &str,
    envs: &[(&str, &str)],
) -> ServerGuard {
    let mut command = Command::new(binary);
    command
        .args(["serve", "--db", &db.to_string_lossy(), "--pipe", pipe])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit());
    for (key, value) in envs {
        command.env(key, value);
    }
    ServerGuard(command.spawn().unwrap())
}

fn fixture_pipe(name: &str) -> String {
    format!(
        r"\\.\pipe\emberd-{name}-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    )
}

#[test]
fn named_pipe_dispatch_refuses_on_consumer_floor_with_receipt_through_real_binary() {
    let root = sandbox("pipe-floor-refusal");
    let db = root.join("emberd.sqlite3");
    let pipe = fixture_pipe("floor-refusal");
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "pipe-floor-job");
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let manifest_utf8 = String::from_utf8(manifest_bytes).unwrap();
    // 1024 free bytes is below every configured survival floor.
    let mut server = start_server_with_env(
        &binary,
        &db,
        &pipe,
        &[("EMBERD_TEST_FLOOR_FREE_BYTES", "1024")],
    );
    assert_eq!(rpc(&pipe, 300, "ping", json!({}))["status"], "ok");
    let error = rpc_error(
        &pipe,
        301,
        "dispatch_manifest",
        json!({"manifest_utf8": manifest_utf8, "manifest_sha256": manifest_sha256}),
    );
    assert!(
        error["data"]
            .as_str()
            .unwrap()
            .contains("DispatchConsumerFloorViolation"),
        "floor-refused dispatch must surface the typed violation: {error}"
    );
    let receipt_path = root.join("custody").join("pipe-floor-job-preflight.json");
    let receipt: Value = serde_json::from_slice(&fs::read(&receipt_path).unwrap()).unwrap();
    assert_eq!(receipt["result"], "REFUSED_CONSUMER_FLOOR");
    assert_eq!(
        rpc(&pipe, 302, "job_state", json!({"job_id": "pipe-floor-job"}))["state"],
        Value::Null,
    );
    rpc(&pipe, 303, "shutdown", json!({}));
    wait_for_exit(&mut server);
}

#[test]
fn named_pipe_dispatch_admits_under_passing_floors_with_both_roots_disclosed() {
    let root = sandbox("pipe-floor-pass");
    let db = root.join("emberd.sqlite3");
    let pipe = fixture_pipe("floor-pass");
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "pipe-floor-pass-job");
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let manifest_utf8 = String::from_utf8(manifest_bytes).unwrap();
    let mut server = start_server_with_env(
        &binary,
        &db,
        &pipe,
        &[("EMBERD_TEST_FLOOR_FREE_BYTES", "18446744073709551615")],
    );
    assert_eq!(rpc(&pipe, 310, "ping", json!({}))["status"], "ok");
    let result = rpc(
        &pipe,
        311,
        "dispatch_manifest",
        json!({"manifest_utf8": manifest_utf8, "manifest_sha256": manifest_sha256}),
    );
    assert!(result["pid"].as_u64().unwrap() > 0);
    let receipt = PathBuf::from(result["preflight_receipt_path"].as_str().unwrap());
    let receipt_json: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(receipt_json["result"], "PREFLIGHT_PASSED");
    // Both configured roots are disclosed, present or not: an absent drive
    // reads status=absent, a present one status=available. Nothing is
    // silently omitted from the pass evidence.
    let floors = receipt_json["consumer_floor"].as_array().unwrap();
    assert_eq!(
        floors.len(),
        2,
        "both configured roots disclosed: {receipt_json}"
    );
    for floor in floors {
        let status = floor["status"].as_str().unwrap();
        assert!(status == "available" || status == "absent");
        assert!(floor["minimum_free_bytes"].as_u64().unwrap() > 0);
        if status == "available" {
            assert!(
                floor["available_free_bytes"].as_u64().unwrap()
                    >= floor["minimum_free_bytes"].as_u64().unwrap()
            );
        }
    }
    rpc(&pipe, 312, "stop_job", json!({"job_id": "pipe-floor-pass-job"}));
    rpc(&pipe, 313, "shutdown", json!({}));
    wait_for_exit(&mut server);
}

#[test]
fn named_pipe_dispatch_admits_with_unavailable_provider_disclosed_through_real_binary() {
    let root = sandbox("pipe-provider-unavailable");
    let db = root.join("emberd.sqlite3");
    let pipe = fixture_pipe("provider-unavailable");
    let binary = emberd_binary();
    let manifest = write_dispatch_manifest(&root, "pipe-provider-job");
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let manifest_utf8 = String::from_utf8(manifest_bytes).unwrap();
    let mut server = start_server_with_env(
        &binary,
        &db,
        &pipe,
        &[
            ("EMBERD_TEST_FLOOR_FREE_BYTES", "18446744073709551615"),
            ("EMBERD_TEST_VRAM_PROVIDER_UNAVAILABLE", "1"),
        ],
    );
    assert_eq!(rpc(&pipe, 320, "ping", json!({}))["status"], "ok");
    let result = rpc(
        &pipe,
        321,
        "dispatch_manifest",
        json!({"manifest_utf8": manifest_utf8, "manifest_sha256": manifest_sha256}),
    );
    assert!(result["pid"].as_u64().unwrap() > 0);
    let receipt = PathBuf::from(result["preflight_receipt_path"].as_str().unwrap());
    let receipt_json: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(receipt_json["result"], "PREFLIGHT_PASSED");
    assert_eq!(
        receipt_json["vram_reserve"]["provider_status"],
        "unavailable"
    );
    assert_eq!(
        receipt_json["vram_reserve"]["available_free_bytes"],
        Value::Null
    );
    assert_eq!(
        rpc(&pipe, 322, "job_state", json!({"job_id": "pipe-provider-job"}))["state"],
        "running"
    );
    rpc(&pipe, 323, "stop_job", json!({"job_id": "pipe-provider-job"}));
    rpc(&pipe, 324, "shutdown", json!({}));
    wait_for_exit(&mut server);
}

#[test]
fn named_pipe_start_job_rejects_missing_or_zero_memory_ceiling_as_invalid_params() {
    let root = sandbox("pipe-start-invalid-params");
    let db = root.join("emberd.sqlite3");
    let pipe = fixture_pipe("start-invalid-params");
    let binary = emberd_binary();
    let mut server = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 330, "ping", json!({}))["status"], "ok");
    for (id, job_id, payload) in [
        (
            331u64,
            "pipe-no-ceiling",
            json!({"job_id": "pipe-no-ceiling", "program": "x", "args": [], "resource_lease": "cpu-x", "env": {}, "restart_policy": "never"}),
        ),
        (
            332u64,
            "pipe-zero-ceiling",
            json!({"job_id": "pipe-zero-ceiling", "program": "x", "args": [], "resource_lease": "cpu-x", "env": {}, "restart_policy": "never", "maximum_job_memory_bytes": 0}),
        ),
    ] {
        let error = rpc_error(&pipe, id, "start_job", payload);
        assert_eq!(
            error["code"].as_i64().unwrap(),
            -32602,
            "missing/zero ceiling must be invalid params: {error}"
        );
        // -32602 must be a pure validation refusal: zero durable side
        // effects. No job_state, no jobs/leases/dispatch_receipt_claims
        // row, no receipt file — a rejected-params call must be as if it
        // never happened.
        assert_eq!(
            rpc(&pipe, id + 1000, "job_state", json!({"job_id": job_id})),
            Value::Null,
            "invalid-params start_job must leave no job_state for {job_id}"
        );
        let connection = Connection::open(&db).unwrap();
        let jobs_count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM jobs WHERE job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(jobs_count, 0, "no jobs row for {job_id}");
        let leases_count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM leases WHERE owner_job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(leases_count, 0, "no lease row for {job_id}");
        let claims_count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM dispatch_receipt_claims WHERE job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(claims_count, 0, "no dispatch_receipt_claims row for {job_id}");
    }
    rpc(&pipe, 333, "shutdown", json!({}));
    wait_for_exit(&mut server);
}
