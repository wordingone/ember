// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! RISK 2 at process level (lead ruling on the lab hour job): the hour must outlive its daemon. A real `ember-lab serve`
//! process starts an hour through the real `ember-lab start-hour` CLI; the daemon process is then killed outright (the
//! shape of a crash, not a clean stop); the hour keeps running and keeps writing its log; a second `ember-lab serve`
//! on the same database re-adopts it and sees it exit 0. Also pins the CLI's machine-readable lines and exit codes.
#![cfg(windows)]

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::System::Threading::{
    OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE,
};

const SCRIPT: &str = "#!/bin/bash\necho HOUR_START\necho EMBER_COUNT $(env | grep -ci '^ember_')\ni=0\nwhile [ ! -f \"$STOP_FILE\" ]; do\n  i=$((i+1))\n  echo TICK $i\n  sleep 1\ndone\necho HOUR_DONE\nexit 0\n";

struct ServerGuard(Option<Child>);

impl ServerGuard {
    fn kill_now(&mut self) {
        if let Some(mut child) = self.0.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for ServerGuard {
    fn drop(&mut self) {
        self.kill_now();
    }
}

fn binary() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_ember-lab"))
}

fn start_server(db: &Path, pipe: &str) -> ServerGuard {
    ServerGuard(Some(
        Command::new(binary())
            .args(["serve", "--db", &db.to_string_lossy(), "--pipe", pipe])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap(),
    ))
}

fn rpc(pipe: &str, request: Value) -> Value {
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut stream = loop {
        match OpenOptions::new().read(true).write(true).open(pipe) {
            Ok(stream) => break stream,
            Err(_) if Instant::now() < deadline => thread::sleep(Duration::from_millis(20)),
            Err(error) => panic!("connect {pipe}: {error}"),
        }
    };
    writeln!(stream, "{request}").unwrap();
    stream.flush().unwrap();
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line).unwrap();
    serde_json::from_str(&line).unwrap()
}

fn job_state(pipe: &str, job_id: &str) -> String {
    let response = rpc(
        pipe,
        json!({"jsonrpc":"2.0","id":1,"method":"job_state","params":{"job_id":job_id}}),
    );
    response["result"]["state"]
        .as_str()
        .unwrap_or("none")
        .to_string()
}

fn pid_alive(pid: u32) -> bool {
    let handle = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, pid) };
    if handle.is_null() {
        return false;
    }
    let alive = unsafe { WaitForSingleObject(handle, 0) } != 0;
    unsafe { CloseHandle(handle) };
    alive
}

fn wait_for(what: &str, seconds: u64, mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        if condition() {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
    panic!("timed out waiting for {what}");
}

fn field<'a>(line: &'a str, key: &str) -> &'a str {
    let marker = format!("{key}=");
    let start = line
        .find(&marker)
        .unwrap_or_else(|| panic!("{key} missing in {line}"))
        + marker.len();
    let rest = &line[start..];
    rest.split(' ').next().unwrap()
}

fn tick_count(log: &Path) -> usize {
    fs::read_to_string(log)
        .map(|text| {
            text.lines()
                .filter(|line| line.starts_with("TICK "))
                .count()
        })
        .unwrap_or(0)
}

#[test]
fn the_hour_outlives_a_killed_daemon_and_a_new_daemon_readopts_it() {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "ember-lab-hour-proc-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&dir).unwrap();
    let script = dir.join("h98_dispatch_v1.sh");
    fs::write(&script, SCRIPT).unwrap();
    let sha = format!("{:x}", Sha256::digest(SCRIPT.as_bytes()));
    let stop = dir.join("stop.flag");
    let log = dir.join("hour.log");
    let db = dir.join("lab.sqlite3");
    let pipe = format!(
        r"\\.\pipe\ember-lab-hour-proc-{}-{nonce}",
        std::process::id()
    );

    let mut first = start_server(&db, &pipe);

    // A refusal comes back as one line on its own exit code (a wrong sha is hour_sha_mismatch / 24).
    let refused = Command::new(binary())
        .args(["start-hour", "--pipe", &pipe, "--script"])
        .arg(&script)
        .args(["--sha256", &"0".repeat(64), "--log"])
        .arg(dir.join("refused.log"))
        .output()
        .unwrap();
    let refused_text = String::from_utf8_lossy(&refused.stdout).to_string();
    assert_eq!(refused.status.code(), Some(24), "{refused_text}");
    assert!(
        refused_text.starts_with("START_HOUR_REFUSED code=hour_sha_mismatch rc=24 detail="),
        "{refused_text}"
    );
    assert_eq!(refused_text.trim_end().lines().count(), 1, "{refused_text}");

    let started = Command::new(binary())
        .args(["start-hour", "--pipe", &pipe, "--script"])
        .arg(&script)
        .args(["--sha256", &sha, "--log"])
        .arg(&log)
        .arg("--cwd")
        .arg(&dir)
        .env("STOP_FILE", stop.to_string_lossy().replace('\\', "/"))
        .env("EMBER_STARTUP_RESUME_HOUR", "must-not-reach-the-hour")
        .output()
        .unwrap();
    let started_text = String::from_utf8_lossy(&started.stdout).to_string();
    assert_eq!(started.status.code(), Some(0), "{started_text}");
    assert_eq!(started_text.trim_end().lines().count(), 1, "{started_text}");
    assert!(
        started_text.starts_with("START_HOUR_OK pid="),
        "{started_text}"
    );
    let pid: u32 = field(&started_text, "pid").parse().unwrap();
    let job_id = field(&started_text, "job_id").to_string();
    let receipt = PathBuf::from(started_text.trim_end().rsplit("receipt=").next().unwrap());
    assert!(
        receipt.exists(),
        "receipt must exist before the line is printed"
    );
    assert_eq!(job_state(&pipe, &job_id), "running");

    wait_for("first hour ticks", 20, || tick_count(&log) >= 2);

    // Crash the daemon. The hour must keep running and keep writing.
    first.kill_now();
    let before = tick_count(&log);
    wait_for("hour still writing after the daemon was killed", 20, || {
        tick_count(&log) >= before + 2
    });
    assert!(pid_alive(pid), "the hour process died with its daemon");

    // A second daemon on the same database re-adopts the running hour.
    let _second = start_server(&db, &pipe);
    wait_for("re-adoption", 30, || job_state(&pipe, &job_id) == "running");
    fs::write(&stop, b"stop").unwrap();
    wait_for("hour exit observed by the new daemon", 30, || {
        job_state(&pipe, &job_id) == "exited"
    });
    let exit = rpc(
        &pipe,
        json!({"jsonrpc":"2.0","id":2,"method":"job_exit_code","params":{"job_id":job_id}}),
    );
    assert_eq!(exit["result"]["exit_code"], 0, "{exit}");
    assert!(!pid_alive(pid));

    let text = fs::read_to_string(&log).unwrap();
    assert!(
        text.contains("HOUR_START") && text.contains("HOUR_DONE"),
        "{text}"
    );
    assert!(
        text.contains("EMBER_COUNT 0"),
        "an EMBER_* key reached the hour: {text}"
    );
    // The events RPC shows the job lifecycle.
    let events = rpc(
        &pipe,
        json!({"jsonrpc":"2.0","id":3,"method":"job_events","params":{"job_id":job_id,"after_seq":0,"limit":200}}),
    );
    assert!(
        events["result"]["events"]
            .as_array()
            .map(|e| !e.is_empty())
            .unwrap_or(false),
        "{events}"
    );
}
