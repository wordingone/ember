// goal_id: EMBER-01
// workstream_id: EMBER-01A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

use serde_json::{json, Value};
use std::fs::OpenOptions;
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
    std::fs::create_dir_all(&path).unwrap();
    path
}

fn emberd_binary() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_emberd"))
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

fn unique_pipe() -> String {
    format!(
        r"\\.\pipe\emberd-resilience-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    )
}

fn open_pipe(pipe: &str, timeout: Duration) -> std::fs::File {
    let deadline = Instant::now() + timeout;
    loop {
        match OpenOptions::new().read(true).write(true).open(pipe) {
            Ok(stream) => return stream,
            Err(_) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
            Err(error) => panic!("timed out connecting to {pipe}: {error}"),
        }
    }
}

fn raw_rpc(pipe: &str, line: &str, timeout: Duration) -> Value {
    let mut stream = open_pipe(pipe, timeout);
    writeln!(stream, "{line}").unwrap();
    stream.flush().unwrap();
    let mut response = String::new();
    BufReader::new(stream).read_line(&mut response).unwrap();
    serde_json::from_str(&response).unwrap()
}

fn ping(pipe: &str) {
    let response = raw_rpc(
        pipe,
        &json!({"jsonrpc":"2.0","id":1,"method":"ping","params":{}}).to_string(),
        Duration::from_secs(2),
    );
    assert_eq!(response["result"]["status"], "ok");
}

fn shutdown(pipe: &str) {
    let response = raw_rpc(
        pipe,
        &json!({"jsonrpc":"2.0","id":99,"method":"shutdown","params":{}}).to_string(),
        Duration::from_secs(2),
    );
    assert_eq!(response["result"]["status"], "shutting_down");
}

#[test]
fn connect_then_disconnect_does_not_terminate_server() {
    let root = sandbox("disconnect");
    let pipe = unique_pipe();
    let _server = start_server(&emberd_binary(), &root.join("state.sqlite3"), &pipe);
    ping(&pipe);

    drop(open_pipe(&pipe, Duration::from_secs(2)));
    thread::sleep(Duration::from_millis(100));

    ping(&pipe);
    shutdown(&pipe);
}

#[test]
fn oversized_request_is_rejected_without_terminating_server() {
    let root = sandbox("oversized");
    let pipe = unique_pipe();
    let _server = start_server(&emberd_binary(), &root.join("state.sqlite3"), &pipe);
    ping(&pipe);

    let request = json!({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "ping",
        "params": {},
        "padding": "a".repeat(70_000),
    })
    .to_string();
    let response = raw_rpc(&pipe, &request, Duration::from_secs(2));
    assert_eq!(response["error"]["code"], -32600);

    ping(&pipe);
    shutdown(&pipe);
}

#[test]
fn stalled_connection_does_not_monopolize_server() {
    let root = sandbox("stalled");
    let pipe = unique_pipe();
    let _server = start_server(&emberd_binary(), &root.join("state.sqlite3"), &pipe);
    ping(&pipe);

    let stalled = open_pipe(&pipe, Duration::from_secs(2));
    ping(&pipe);
    drop(stalled);

    shutdown(&pipe);
}
