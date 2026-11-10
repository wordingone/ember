// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! `Daemon::start_hour`: the hour job class (issue #2119). Runs a real Git bash hour script as a lab job.
#![cfg(windows)]

use ember_lab::hour_job::{hour_env, HourStartRequest};
use ember_lab::{Daemon, EmberLabError, JobState};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const SCRIPT: &str = r#"#!/bin/bash
echo "HOUR_START arg0=$0"
echo "CWDW=$(pwd -W 2>/dev/null || pwd)"
echo "MARK=${HOUR_MARK:-unset}"
echo "EMBER_COUNT=$(env | grep -c '^EMBER_')"
if [ -n "$SPAWN_SURVIVOR" ]; then
  sleep 300 &
  echo "CHILDWIN $(cat /proc/$!/winpid)"
  if [ "$SPAWN_SURVIVOR" = "exit" ]; then echo HOUR_EXIT_WITH_SURVIVOR; exit 0; fi
fi
i=0
while [ ! -f "$STOP_FILE" ]; do
  i=$((i+1)); echo "TICK $i"; sleep 1
  if [ "$i" -gt 120 ]; then exit 3; fi
done
echo HOUR_DONE
exit 0
"#;

fn sandbox(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "ember-lab-hour-{name}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn forward(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

struct Fixture {
    dir: PathBuf,
    script: PathBuf,
    sha: String,
    stop: PathBuf,
}

fn fixture(name: &str) -> Fixture {
    let dir = sandbox(name);
    let script = dir.join("h99_dispatch_v1.sh");
    fs::write(&script, SCRIPT.as_bytes()).unwrap();
    let sha = format!("{:x}", Sha256::digest(SCRIPT.as_bytes()));
    let stop = dir.join("stop.flag");
    Fixture {
        dir,
        script,
        sha,
        stop,
    }
}

fn env_for(fx: &Fixture, extra: &[(&str, &str)]) -> BTreeMap<String, String> {
    // The caller's environment minus every EMBER_*, exactly as the cockpit builds it, plus the test's own variables.
    let mut env = hour_env(std::env::vars());
    env.insert("HOUR_MARK".into(), "mark-7".into());
    env.insert("STOP_FILE".into(), forward(&fx.stop));
    for (key, value) in extra {
        env.insert((*key).into(), (*value).into());
    }
    env
}

fn request(fx: &Fixture, log_name: &str, extra: &[(&str, &str)]) -> HourStartRequest {
    HourStartRequest {
        script: fx.script.clone(),
        sha256: fx.sha.clone(),
        log: fx.dir.join(log_name),
        cwd: Some(fx.dir.clone()),
        bash: None,
        env: env_for(fx, extra),
    }
}

fn wait_until(seconds: u64, mut condition: impl FnMut() -> bool) -> bool {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        if condition() {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    condition()
}

fn log_text(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_default()
}

fn pid_alive(pid: u32) -> bool {
    let out = Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/NH"])
        .output()
        .unwrap();
    String::from_utf8_lossy(&out.stdout)
        .split_whitespace()
        .any(|token| token == pid.to_string())
}

fn kill_pid(pid: u32) {
    let _ = Command::new("taskkill")
        .args(["/F", "/PID", &pid.to_string()])
        .output();
}

fn child_winpid(log: &Path) -> u32 {
    assert!(
        wait_until(30, || log_text(log).contains("CHILDWIN ")),
        "no CHILDWIN line in {}",
        log_text(log)
    );
    log_text(log)
        .lines()
        .find_map(|line| line.strip_prefix("CHILDWIN "))
        .unwrap()
        .trim()
        .parse()
        .unwrap()
}

fn refusal(result: Result<ember_lab::hour_job::HourStarted, EmberLabError>) -> (String, u8) {
    match result {
        Err(EmberLabError::HourRefused { code, rc, .. }) => (code, rc),
        other => panic!("expected an hour refusal, got {other:?}"),
    }
}

#[test]
fn hour_runs_with_the_exact_env_cwd_log_and_a_start_receipt() {
    let fx = fixture("run");
    let daemon = Daemon::open(&fx.dir.join("lab.sqlite3")).unwrap();
    let started = daemon.start_hour(request(&fx, "hour.log", &[])).unwrap();
    assert!(started.line().starts_with("START_HOUR_OK pid="));
    assert!(started
        .line()
        .contains(&format!("log={}", started.log.display())));
    assert!(started
        .line()
        .contains(&format!("receipt={}", started.receipt_path.display())));
    assert!(wait_until(30, || log_text(&started.log).contains("TICK 1")));
    let log = log_text(&started.log);
    assert!(log.contains("MARK=mark-7"), "{log}");
    // Nothing EMBER_* reaches the hour: not the caller's, and not the lab's own (EMBER_LAB_*, protective-checkpoint paths).
    assert!(log.contains("EMBER_COUNT=0"), "{log}");
    let expected_cwd = forward(&fx.dir).to_ascii_lowercase();
    let cwd_line = log.lines().find_map(|l| l.strip_prefix("CWDW=")).unwrap();
    assert_eq!(
        cwd_line.replace('\\', "/").to_ascii_lowercase(),
        expected_cwd
    );
    // The start receipt is complete before start_hour returned.
    let receipt: Value =
        serde_json::from_str(&fs::read_to_string(&started.receipt_path).unwrap()).unwrap();
    assert_eq!(receipt["schema"], "ember-lab-hour-start-v1");
    assert_eq!(receipt["phase"], "started");
    assert_eq!(receipt["pid"], started.pid);
    assert_eq!(receipt["sha256"], fx.sha);
    assert_eq!(receipt["redirect"], "exec bash \"$0\" >>\"$1\" 2>&1");
    let receipt_text = fs::read_to_string(&started.receipt_path).unwrap();
    assert!(
        !receipt_text.contains("mark-7"),
        "env VALUES must not be receipted"
    );
    // Durable job row and events.
    assert_eq!(
        daemon.job_state(&started.job_id).unwrap(),
        Some(JobState::Running)
    );
    let events = daemon.job_events(&started.job_id, 0, 100).unwrap();
    let kinds: Vec<&str> = events.iter().map(|e| e["kind"].as_str().unwrap()).collect();
    assert!(kinds.contains(&"job_started"), "{kinds:?}");
    fs::write(&fx.stop, b"stop").unwrap();
    assert!(wait_until(30, || daemon
        .job_state(&started.job_id)
        .unwrap()
        == Some(JobState::Exited)));
    assert_eq!(daemon.job_exit_code(&started.job_id).unwrap(), Some(0));
    assert!(log_text(&started.log).contains("HOUR_DONE"));
    let kinds_after: Vec<String> = daemon
        .job_events(&started.job_id, 0, 100)
        .unwrap()
        .iter()
        .map(|e| e["kind"].as_str().unwrap().to_string())
        .collect();
    assert!(
        kinds_after.iter().any(|k| k == "job_exited"),
        "{kinds_after:?}"
    );
    // The lease is released on exit: a second hour (new log) starts.
    fs::remove_file(&fx.stop).unwrap();
    let second = daemon.start_hour(request(&fx, "hour2.log", &[])).unwrap();
    assert_ne!(second.job_id, started.job_id);
    daemon.stop_job(&second.job_id).unwrap();
}

#[test]
fn every_check_refuses_with_its_own_code_and_exit_code() {
    let fx = fixture("refuse");
    let daemon = Daemon::open(&fx.dir.join("lab.sqlite3")).unwrap();

    let mut relative = request(&fx, "a.log", &[]);
    relative.log = PathBuf::from("relative.log");
    assert_eq!(
        refusal(daemon.start_hour(relative)),
        ("hour_path_relative".into(), 20)
    );

    let bad_name = fx.dir.join("not_an_hour.sh");
    fs::write(&bad_name, SCRIPT.as_bytes()).unwrap();
    let mut named = request(&fx, "b.log", &[]);
    named.script = bad_name;
    assert_eq!(
        refusal(daemon.start_hour(named)),
        ("hour_script_name".into(), 21)
    );

    let mut missing = request(&fx, "c.log", &[]);
    missing.script = fx.dir.join("h98_dispatch_v1.sh");
    assert_eq!(
        refusal(daemon.start_hour(missing)),
        ("hour_script_missing".into(), 22)
    );

    let mut malformed = request(&fx, "d.log", &[]);
    malformed.sha256 = fx.sha.to_ascii_uppercase();
    assert_eq!(
        refusal(daemon.start_hour(malformed)),
        ("hour_sha_malformed".into(), 23)
    );

    let mut mismatch = request(&fx, "e.log", &[]);
    mismatch.sha256 = "0".repeat(64);
    assert_eq!(
        refusal(daemon.start_hour(mismatch)),
        ("hour_sha_mismatch".into(), 24)
    );

    let existing = request(&fx, "f.log", &[]);
    fs::write(&existing.log, b"").unwrap();
    assert_eq!(
        refusal(daemon.start_hour(existing)),
        ("hour_log_exists".into(), 25)
    );

    let mut unwritable = request(&fx, "g.log", &[]);
    unwritable.log = fx.dir.join("no-such-dir").join("g.log");
    assert_eq!(
        refusal(daemon.start_hour(unwritable)),
        ("hour_log_unwritable".into(), 26)
    );

    let mut shim = request(&fx, "h.log", &[]);
    shim.bash = Some(PathBuf::from("C:\\Windows\\System32\\bash.exe"));
    assert_eq!(
        refusal(daemon.start_hour(shim)),
        ("hour_bash_refused".into(), 27)
    );
    let mut absent = request(&fx, "h2.log", &[]);
    absent.bash = Some(fx.dir.join("no-bash.exe"));
    assert_eq!(
        refusal(daemon.start_hour(absent)),
        ("hour_bash_refused".into(), 27)
    );

    let ember = request(&fx, "i.log", &[("EMBER_API_KEY", "x")]);
    assert_eq!(
        refusal(daemon.start_hour(ember)),
        ("hour_env_ember_key".into(), 28)
    );
    let ember_lower = request(&fx, "i2.log", &[("ember_model_seat", "x")]);
    assert_eq!(
        refusal(daemon.start_hour(ember_lower)),
        ("hour_env_ember_key".into(), 28)
    );

    let mut empty_env = request(&fx, "j.log", &[]);
    empty_env.env.clear();
    assert_eq!(
        refusal(daemon.start_hour(empty_env)),
        ("hour_env_invalid".into(), 29)
    );
    let mut no_path = request(&fx, "j2.log", &[]);
    no_path
        .env
        .retain(|key, _| !key.eq_ignore_ascii_case("PATH"));
    assert_eq!(
        refusal(daemon.start_hour(no_path)),
        ("hour_env_invalid".into(), 29)
    );

    let mut bad_cwd = request(&fx, "k.log", &[]);
    bad_cwd.cwd = Some(fx.dir.join("no-such-cwd"));
    assert_eq!(
        refusal(daemon.start_hour(bad_cwd)),
        ("hour_cwd_invalid".into(), 36)
    );

    let receipt_clash = request(&fx, "l.log", &[]);
    fs::write(
        format!("{}.lab-start.json", receipt_clash.log.display()),
        b"{}",
    )
    .unwrap();
    assert_eq!(
        refusal(daemon.start_hour(receipt_clash)),
        ("hour_receipt_exists".into(), 33)
    );

    // A bash that exists but cannot run: the spawn is refused, the lease is released (a good start follows).
    let fake_bash = fx.dir.join("fake-bash.exe");
    fs::write(&fake_bash, b"not an executable").unwrap();
    let mut spawn = request(&fx, "m.log", &[]);
    spawn.bash = Some(fake_bash);
    assert_eq!(
        refusal(daemon.start_hour(spawn)),
        ("hour_spawn_failed".into(), 35)
    );
    fs::write(&fx.stop, b"stop").unwrap();
    let good = daemon.start_hour(request(&fx, "n.log", &[])).unwrap();
    assert!(wait_until(30, || log_text(&good.log).contains("HOUR_DONE")));
}

#[test]
fn a_second_hour_is_refused_while_one_holds_the_lease() {
    let fx = fixture("lease");
    let daemon = Daemon::open(&fx.dir.join("lab.sqlite3")).unwrap();
    let first = daemon.start_hour(request(&fx, "first.log", &[])).unwrap();
    let second = request(&fx, "second.log", &[]);
    let (code, rc) = refusal(daemon.start_hour(second));
    assert_eq!((code.as_str(), rc), ("hour_lease_conflict", 32));
    assert!(
        !fx.dir.join("second.log").exists(),
        "a refused start must not create its log"
    );
    daemon.stop_job(&first.job_id).unwrap();
}

#[test]
fn hour_survives_a_daemon_drop_and_is_readopted_then_exits_zero() {
    // RISK 2: a Studio close or a daemon crash must not end the hour; a restarted daemon re-adopts it.
    let fx = fixture("risk2");
    let db = fx.dir.join("lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    let started = daemon.start_hour(request(&fx, "hour.log", &[])).unwrap();
    assert!(wait_until(30, || log_text(&started.log).contains("TICK 2")));
    drop(daemon);
    let ticks_at_drop = log_text(&started.log).matches("TICK ").count();
    thread::sleep(Duration::from_secs(3));
    let ticks_later = log_text(&started.log).matches("TICK ").count();
    assert!(
        ticks_later >= ticks_at_drop + 2,
        "the hour kept running after the daemon dropped: {ticks_at_drop} -> {ticks_later}"
    );
    assert!(pid_alive(started.pid));

    let reopened = Daemon::open(&db).unwrap();
    let adopted = reopened.adopt_job(&started.job_id).unwrap();
    assert_eq!(adopted.pid, started.pid);
    assert_eq!(
        reopened.job_state(&started.job_id).unwrap(),
        Some(JobState::Running)
    );
    fs::write(&fx.stop, b"stop").unwrap();
    assert!(wait_until(30, || reopened
        .job_state(&started.job_id)
        .unwrap()
        == Some(JobState::Exited)));
    assert_eq!(reopened.job_exit_code(&started.job_id).unwrap(), Some(0));
    assert!(log_text(&started.log).contains("HOUR_DONE"));
}

#[test]
fn stop_job_ends_the_whole_hour_tree() {
    let fx = fixture("stop");
    let daemon = Daemon::open(&fx.dir.join("lab.sqlite3")).unwrap();
    let started = daemon
        .start_hour(request(&fx, "hour.log", &[("SPAWN_SURVIVOR", "wait")]))
        .unwrap();
    let child = child_winpid(&started.log);
    assert!(pid_alive(child));
    daemon.stop_job(&started.job_id).unwrap();
    assert_eq!(
        daemon.job_state(&started.job_id).unwrap(),
        Some(JobState::Stopped)
    );
    assert!(
        wait_until(15, || !pid_alive(started.pid) && !pid_alive(child)),
        "the stopped hour left a live process"
    );
}

#[test]
fn a_surviving_descendant_is_not_killed_when_the_hour_main_process_exits() {
    // Parity with a detached /resume-hour: no KILL_ON_JOB_CLOSE for the hour class.
    let fx = fixture("survivor");
    let daemon = Daemon::open(&fx.dir.join("lab.sqlite3")).unwrap();
    let started = daemon
        .start_hour(request(&fx, "hour.log", &[("SPAWN_SURVIVOR", "exit")]))
        .unwrap();
    let child = child_winpid(&started.log);
    assert!(wait_until(30, || daemon
        .job_state(&started.job_id)
        .unwrap()
        == Some(JobState::Exited)));
    thread::sleep(Duration::from_secs(2));
    let survived = pid_alive(child);
    kill_pid(child);
    assert!(
        survived,
        "the descendant was killed when the main process exited"
    );
}
