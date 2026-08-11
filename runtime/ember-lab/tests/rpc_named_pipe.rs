// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

use ember_lab::{probe_host_commit_capacity, MAX_DISPATCH_MANIFEST_BYTES};
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
    let path = std::env::temp_dir().join(format!(
        "ember-lab-rpc-{name}-{}-{nonce}",
        std::process::id()
    ));
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
fn ember_lab_binary() -> PathBuf {
    option_env!("CARGO_BIN_EXE_ember-lab")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("missing-ember-lab-binary"))
}

struct ServerGuard(Child);

impl Drop for ServerGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn start_server(binary: &Path, db: &Path, pipe: &str) -> ServerGuard {
    ServerGuard(
        Command::new(binary)
            .args(["serve", "--db", &db.to_string_lossy(), "--pipe", pipe])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap(),
    )
}

fn rpc_response(pipe: &str, id: u64, method: &str, params: Value) -> Value {
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
                return response;
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
    let response = rpc_response(pipe, id, method, params);
    assert!(
        response.get("error").is_none(),
        "RPC {method} failed: {response}"
    );
    response["result"].clone()
}

fn wait_for_exit(server: &mut ServerGuard) {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if server.0.try_wait().unwrap().is_some() {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "ember-lab did not exit after shutdown"
        );
        thread::sleep(Duration::from_millis(20));
    }
}

fn write_dispatch_manifest(root: &Path, job_id: &str) -> PathBuf {
    let custody = root.join("custody");
    fs::create_dir_all(&custody).unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBER_LAB_RPC_FIXTURE_CHILD".to_string(), "1".to_string());
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
            "schema_version": "ember-lab-dispatch-manifest-v3",
            "workload_profile": {
                "profile_id": "evidence_verifier",
                "pinned_host_producers": [{
                    "kind": "receipt_verifier",
                    "maximum_bytes": 536_870_912u64
                }],
                "requires_ui_responsiveness": false,
                "cpu_rate_percent": 100
            },
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
            "preflight_receipt": root.join("custody").join("preflight.json")
        }))
        .unwrap(),
    )
    .unwrap();
    manifest
}

fn pad_dispatch_manifest_to_exact_bytes(path: &Path, target_bytes: usize) {
    let mut manifest: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    manifest["env"].as_object_mut().unwrap().insert(
        "EMBER_LAB_TEST_PADDING".into(),
        Value::String(String::new()),
    );
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
        .insert("EMBER_LAB_TEST_PADDING".into(), Value::String(padding));
    let encoded = serde_json::to_vec(&manifest).unwrap();
    assert_eq!(encoded.len(), target_bytes);
    fs::write(path, encoded).unwrap();
}
#[test]
fn fixture_rpc_child_process() {
    if std::env::var("EMBER_LAB_RPC_FIXTURE_CHILD").as_deref() == Ok("1") {
        thread::sleep(Duration::from_secs(30));
    }
}

#[test]
fn dispatch_cli_uses_persistent_named_pipe_daemon_and_governed_spawn() {
    let root = sandbox("dispatch-cli");
    let db = root.join("ember-lab.sqlite3");
    let pipe = format!(
        r"\\.\pipe\ember-lab-dispatch-cli-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = ember_lab_binary();
    let manifest = write_dispatch_manifest(&root, "dispatch-cli-job");
    let mut server = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 100, "ping", json!({}))["status"], "ok");
    let runtime_identity = rpc(&pipe, 101, "runtime_identity", json!({}));
    assert_eq!(
        runtime_identity["schema_version"],
        "ember-lab-runtime-identity-v1"
    );
    assert_eq!(runtime_identity["pid"], server.0.id());

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
    let db = root.join("ember-lab.sqlite3");
    let pipe = format!(
        r"\\.\pipe\ember-lab-dispatch-transport-ceiling-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = ember_lab_binary();
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
    let db = root.join("ember-lab.sqlite3");
    let pipe = format!(
        r"\\.\pipe\ember-lab-dispatch-bytes-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = ember_lab_binary();
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
fn named_pipe_refuses_raw_start_job_before_process_creation() {
    let root = sandbox("raw-start-refusal");
    let db = root.join("ember-lab.sqlite3");
    let identity = root.join("identity.json");
    fs::write(&identity, b"{\"identity\":\"bound\"}").unwrap();
    let pipe = format!(
        r"\\.\pipe\ember-lab-raw-start-refusal-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = ember_lab_binary();
    let mut server = start_server(&binary, &db, &pipe);
    rpc(
        &pipe,
        300,
        "bind_identity",
        json!({
            "job_id": "raw-start-job",
            "path": identity,
            "sha256": sha256(&identity),
        }),
    );
    rpc(
        &pipe,
        301,
        "acquire_lease",
        json!({"resource": "cpu-fixture", "job_id": "raw-start-job"}),
    );

    let fixture = std::env::current_exe().unwrap();
    let response = rpc_response(
        &pipe,
        302,
        "start_job",
        json!({
            "job_id": "raw-start-job",
            "program": fixture,
            "args": ["--exact", "fixture_rpc_child_process", "--nocapture"],
            "resource_lease": "cpu-fixture",
            "env": {"EMBER_LAB_RPC_FIXTURE_CHILD": "1"},
            "restart_policy": "never",
        }),
    );
    let state = rpc(&pipe, 303, "job_state", json!({"job_id": "raw-start-job"}));
    if state["state"] == "running" {
        rpc(&pipe, 304, "stop_job", json!({"job_id": "raw-start-job"}));
    }
    rpc(&pipe, 305, "shutdown", json!({}));
    wait_for_exit(&mut server);

    assert_eq!(response["error"]["code"], -32601, "{response}");
    assert!(state["state"].is_null(), "raw start created a job: {state}");
}

#[test]
fn named_pipe_rpc_survives_daemon_restart_and_controls_bound_job() {
    if let Err(error) = probe_host_commit_capacity() {
        eprintln!(
            "skipping governed restart/adoption replay because this host refuses the production commit-capacity probe: {error}"
        );
        return;
    }
    let root = sandbox("restart");
    let db = root.join("ember-lab.sqlite3");
    let receipt = root.join("receipt.json");
    let alarm_path = root.join("schedule-alarms.json");
    let content_addressed_receipts = root.join("content-addressed-receipts");
    let manifest = write_dispatch_manifest(&root, "rpc-job");
    let manifest_bytes = fs::read(&manifest).unwrap();
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let manifest_utf8 = String::from_utf8(manifest_bytes).unwrap();
    let pipe = format!(
        r"\\.\pipe\ember-lab-rpc-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = ember_lab_binary();
    assert!(
        binary.is_file(),
        "the resident ember-lab binary target must exist"
    );

    let mut first = start_server(&binary, &db, &pipe);
    assert_eq!(rpc(&pipe, 1, "ping", json!({}))["status"], "ok");
    let started = rpc(
        &pipe,
        4,
        "dispatch_manifest",
        json!({
            "manifest_utf8": manifest_utf8,
            "manifest_sha256": manifest_sha256,
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

    let assessment_directory = root.join("assessment-evidence");
    let assessment = rpc(
        &pipe,
        140,
        "export_assessment_evidence",
        json!({"job_id": "rpc-job", "directory": assessment_directory}),
    );
    assert_eq!(assessment["schema"], "ember-lab-assessment-evidence-v1");
    let assessment_keys: std::collections::BTreeSet<_> = assessment
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(
        assessment_keys,
        [
            "ember_lab_identity",
            "preflight_receipt",
            "operational_receipt",
            "schedule_alarm_state",
            "schema",
            "stderr_log",
            "stdout_log",
        ]
        .into_iter()
        .collect()
    );
    for field in [
        "preflight_receipt",
        "operational_receipt",
        "stdout_log",
        "stderr_log",
        "schedule_alarm_state",
    ] {
        let artifact = &assessment[field];
        assert_eq!(
            artifact
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<std::collections::BTreeSet<_>>(),
            ["path", "sha256"].into_iter().collect()
        );
        let path = PathBuf::from(artifact["path"].as_str().unwrap());
        assert!(path.starts_with(&assessment_directory));
        assert_eq!(sha256(&path), artifact["sha256"]);
    }
    let duplicate = rpc_response(
        &pipe,
        141,
        "export_assessment_evidence",
        json!({"job_id": "rpc-job", "directory": assessment_directory}),
    );
    assert!(duplicate.get("error").is_some());
    let unknown = rpc_response(
        &pipe,
        142,
        "export_assessment_evidence",
        json!({"job_id": "rpc-job", "directory": root.join("unknown-field"), "extra": true}),
    );
    assert!(unknown.get("error").is_some());
    assert!(!root.join("unknown-field").exists());
    let oversized = rpc_response(
        &pipe,
        143,
        "export_assessment_evidence",
        json!({"job_id": "rpc-job", "directory": "x".repeat(4097)}),
    );
    assert!(oversized.get("error").is_some());

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
    let measured_assessment = rpc(
        &pipe,
        144,
        "export_assessment_evidence",
        json!({"job_id": "rpc-job", "directory": root.join("assessment-evidence-measured")}),
    );
    let measured_schedule: Value = serde_json::from_slice(
        &fs::read(
            measured_assessment["schedule_alarm_state"]["path"]
                .as_str()
                .unwrap(),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(measured_schedule["runs"][0]["job_id"], "rpc-job");
    assert_eq!(measured_schedule["runs"][0]["measured_duration_ms"], 55_000);
    assert_eq!(
        measured_schedule["runs"][0]["measurement_daemon_identity"],
        measured_assessment["ember_lab_identity"]
    );
    rpc(
        &pipe,
        18,
        "write_schedule_alarm_state",
        json!({"path": alarm_path}),
    );
    let alarm: Value = serde_json::from_slice(&fs::read(&alarm_path).unwrap()).unwrap();
    assert_eq!(alarm["schema_version"], "ember-lab-schedule-alarm-state-v1");
    assert_eq!(alarm["alarms"]["prediction_overrun"], false);
    assert_eq!(alarm["runs"][0]["measurement_outcome"], "COMPLETED");
    rpc(&pipe, 19, "shutdown", json!({}));
    wait_for_exit(&mut second);
}

#[test]
fn production_typescript_manifest_transport_reaches_the_real_named_pipe_daemon() {
    let root = sandbox("typescript-production-transport");
    let db = root.join("ember-lab.sqlite3");
    let pipe = format!(
        r"\\.\pipe\ember-lab-typescript-production-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let binary = ember_lab_binary();
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
        .env("EMBER_LAB_REAL_DAEMON_PIPE", &pipe)
        .env("EMBER_LAB_REAL_DAEMON_MANIFEST", &manifest)
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
