// goal_id: EMBER-01
// workstream_id: EMBER-01A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

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

#[test]
fn fixture_rpc_child_process() {
    if std::env::var("EMBERD_RPC_FIXTURE_CHILD").as_deref() == Ok("1") {
        thread::sleep(Duration::from_secs(30));
    }
}

#[test]
fn named_pipe_rpc_survives_daemon_restart_and_controls_bound_job() {
    let root = sandbox("restart");
    let db = root.join("emberd.sqlite3");
    let identity = root.join("identity.json");
    let receipt = root.join("receipt.json");
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
            "env": env,
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
    rpc(
        &pipe,
        10,
        "export_receipt",
        json!({"job_id": "rpc-job", "path": receipt}),
    );
    let payload: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(payload["job_id"], "rpc-job");
    assert_eq!(payload["state"], "stopped");
    assert!(payload["events"]
        .as_array()
        .unwrap()
        .iter()
        .any(|event| event["kind"] == "job_adopted"));

    rpc(&pipe, 11, "shutdown", json!({}));
    wait_for_exit(&mut second);
}
