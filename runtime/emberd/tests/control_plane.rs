// goal_id: EMBER-01
// workstream_id: EMBER-01A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use emberd::{Daemon, EmberdError, JobSpec, JobState};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Duration;
use std::time::{SystemTime, UNIX_EPOCH};

fn sandbox(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("emberd-{name}-{}-{nonce}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn sha256(path: &Path) -> String {
    let bytes = fs::read(path).unwrap();
    format!("{:x}", Sha256::digest(bytes))
}

fn write_identity(root: &Path) -> (PathBuf, String) {
    let path = root.join("identity.json");
    fs::write(
        &path,
        br#"{"schema":"ember-identity-v1","model_id":"fixture-owned-3b","checkpoint_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","lineage":"clean_genesis"}"#,
    )
    .unwrap();
    let hash = sha256(&path);
    (path, hash)
}

#[test]
fn fixture_child_process() {
    if std::env::var("EMBERD_FIXTURE_CHILD").as_deref() != Ok("1") {
        return;
    }
    if std::env::var("EMBERD_FIXTURE_SPAWN_CHILD").as_deref() == Ok("1") {
        let child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "fixture_child_process", "--nocapture"])
            .env("EMBERD_FIXTURE_CHILD", "1")
            .env("EMBERD_FIXTURE_SLEEP_MS", "30000")
            .env_remove("EMBERD_FIXTURE_SPAWN_CHILD")
            .env_remove("EMBERD_FIXTURE_CHILD_PID_FILE")
            .spawn()
            .unwrap();
        fs::write(
            std::env::var_os("EMBERD_FIXTURE_CHILD_PID_FILE").unwrap(),
            child.id().to_string(),
        )
        .unwrap();
        drop(child);
    }
    let sleep_ms = std::env::var("EMBERD_FIXTURE_SLEEP_MS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(30_000);
    thread::sleep(Duration::from_millis(sleep_ms));
}

#[cfg(windows)]
fn process_is_alive(pid: u32) -> bool {
    use windows_sys::Win32::Foundation::{CloseHandle, WAIT_TIMEOUT};
    use windows_sys::Win32::System::Threading::{
        OpenProcess, WaitForSingleObject, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    const SYNCHRONIZE_RIGHT: u32 = 0x0010_0000;
    let handle = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_RIGHT,
            0,
            pid,
        )
    };
    if handle.is_null() {
        return false;
    }
    let status = unsafe { WaitForSingleObject(handle, 0) };
    unsafe { CloseHandle(handle) };
    status == WAIT_TIMEOUT
}
#[test]
fn sqlite_wal_identity_binding_and_exclusive_lease_survive_reopen() {
    let root = sandbox("state");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);

    let daemon = Daemon::open(&db).unwrap();
    assert_eq!(daemon.journal_mode().unwrap(), "wal");
    daemon
        .bind_identity("fixture-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("heavy-workload", "fixture-job")
        .unwrap();
    assert!(matches!(
        daemon.acquire_lease("heavy-workload", "other-job"),
        Err(EmberdError::LeaseConflict { .. })
    ));
    drop(daemon);

    let reopened = Daemon::open(&db).unwrap();
    assert_eq!(
        reopened.lease_owner("heavy-workload").unwrap().as_deref(),
        Some("fixture-job")
    );
    assert_eq!(
        reopened.identity_hash("fixture-job").unwrap().as_deref(),
        Some(identity_hash.as_str())
    );

    fs::write(&identity, b"tampered").unwrap();
    assert!(matches!(
        reopened.verify_identity("fixture-job"),
        Err(EmberdError::IdentityMismatch { .. })
    ));
}

#[test]
fn detached_job_is_adopted_stopped_and_exported_after_daemon_reopen() {
    let root = sandbox("job");
    let db = root.join("emberd.sqlite3");
    let receipt = root.join("receipt.json");
    let (identity, identity_hash) = write_identity(&root);

    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("sleep-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "sleep-job").unwrap();
    let fixture = std::env::current_exe().unwrap();
    let spec = JobSpec::new(
        "sleep-job",
        fixture.to_string_lossy(),
        ["--exact", "fixture_child_process", "--nocapture"],
        "cpu-fixture",
    )
    .with_env("EMBERD_FIXTURE_CHILD", "1")
    .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000");
    let started = daemon.start_job(spec).unwrap();
    assert!(started.pid > 0);
    assert_eq!(
        daemon.job_state("sleep-job").unwrap(),
        Some(JobState::Running)
    );
    drop(daemon);

    let reopened = Daemon::open(&db).unwrap();
    let adopted = reopened.adopt_job("sleep-job").unwrap();
    assert_eq!(adopted.pid, started.pid);
    assert!(reopened.has_retained_process_handle("sleep-job"));
    assert_eq!(
        reopened.job_state("sleep-job").unwrap(),
        Some(JobState::Running)
    );
    reopened.stop_job("sleep-job").unwrap();
    assert!(!reopened.has_retained_process_handle("sleep-job"));
    assert_eq!(
        reopened.job_state("sleep-job").unwrap(),
        Some(JobState::Stopped)
    );
    reopened.export_receipt("sleep-job", &receipt).unwrap();
    assert!(matches!(
        reopened.export_receipt("sleep-job", &receipt),
        Err(EmberdError::ReceiptAlreadyExists { .. })
    ));

    let payload: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(payload["schema"], "emberd-operational-receipt-v1");
    assert_eq!(payload["job_id"], "sleep-job");
    assert_eq!(payload["identity_sha256"], identity_hash);
    assert_eq!(payload["resource_lease"], "cpu-fixture");
    assert_eq!(payload["state"], "stopped");
    let events = payload["events"].as_array().unwrap();
    assert!(events.iter().any(|row| row["kind"] == "job_started"));
    assert!(events.iter().any(|row| row["kind"] == "job_adopted"));
    assert!(events.iter().any(|row| row["kind"] == "job_stopped"));
}

#[test]
fn unbound_owner_cannot_acquire_a_durable_lease() {
    let root = sandbox("unbound-lease");
    let daemon = Daemon::open(&root.join("emberd.sqlite3")).unwrap();
    assert!(matches!(
        daemon.acquire_lease("heavy-workload", "missing-identity"),
        Err(EmberdError::IdentityNotFound { .. })
    ));
}

#[test]
fn concurrent_lease_claims_have_exactly_one_winner() {
    let root = sandbox("lease-race");
    let db = root.join("emberd.sqlite3");
    let daemon = Arc::new(Daemon::open(&db).unwrap());
    for owner in ["worker-a", "worker-b"] {
        let (path, hash) = write_identity_for(&root, owner);
        daemon.bind_identity(owner, &path, &hash).unwrap();
    }
    let barrier = Arc::new(Barrier::new(3));
    let mut workers = Vec::new();
    for owner in ["worker-a", "worker-b"] {
        let daemon = Arc::clone(&daemon);
        let barrier = Arc::clone(&barrier);
        workers.push(thread::spawn(move || {
            barrier.wait();
            daemon.acquire_lease("heavy-workload", owner)
        }));
    }
    barrier.wait();
    let results: Vec<_> = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(EmberdError::LeaseConflict { .. })))
            .count(),
        1
    );
}

fn write_identity_for(root: &Path, name: &str) -> (PathBuf, String) {
    let path = root.join(format!("identity-{name}.json"));
    fs::write(
        &path,
        format!(r#"{{"schema":"ember-identity-v1","model_id":"{name}","checkpoint_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","lineage":"clean_genesis"}}"#),
    )
    .unwrap();
    let hash = sha256(&path);
    (path, hash)
}

#[test]
fn dead_persisted_job_is_failed_and_releases_its_lease_on_adoption() {
    let root = sandbox("dead-reconcile");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("short-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "short-job").unwrap();
    let fixture = std::env::current_exe().unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "short-job",
                fixture.to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();
    drop(daemon);
    thread::sleep(Duration::from_millis(250));

    let reopened = Daemon::open(&db).unwrap();
    assert!(matches!(
        reopened.adopt_job("short-job"),
        Err(EmberdError::ProcessUnavailable { .. })
    ));
    assert_eq!(
        reopened.job_state("short-job").unwrap(),
        Some(JobState::Failed)
    );
    assert_eq!(reopened.lease_owner("cpu-fixture").unwrap(), None);
}

#[test]
fn receipt_export_reverifies_bound_identity_bytes() {
    let root = sandbox("receipt-identity");
    let db = root.join("emberd.sqlite3");
    let receipt = root.join("receipt.json");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("receipt-job", &identity, &identity_hash)
        .unwrap();
    fs::write(&identity, b"tampered after binding").unwrap();
    assert!(matches!(
        daemon.export_receipt("receipt-job", &receipt),
        Err(EmberdError::IdentityMismatch { .. })
    ));
    assert!(!receipt.exists());
}

#[cfg(windows)]
#[test]
fn stopping_job_terminates_its_entire_process_cohort() {
    let root = sandbox("cohort");
    let db = root.join("emberd.sqlite3");
    let child_pid_file = root.join("child.pid");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("cohort-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "cohort-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "cohort-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000")
            .with_env("EMBERD_FIXTURE_SPAWN_CHILD", "1")
            .with_env(
                "EMBERD_FIXTURE_CHILD_PID_FILE",
                child_pid_file.to_string_lossy(),
            ),
        )
        .unwrap();
    for _ in 0..100 {
        if child_pid_file.exists() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    let child_pid: u32 = fs::read_to_string(&child_pid_file)
        .unwrap()
        .parse()
        .unwrap();
    assert!(process_is_alive(child_pid));
    daemon.stop_job("cohort-job").unwrap();
    assert!(!process_is_alive(child_pid));
    assert_eq!(daemon.lease_owner("cpu-fixture").unwrap(), None);
}

#[cfg(windows)]
#[test]
fn failed_job_started_event_is_not_committed_and_child_is_cleaned_up() {
    let root = sandbox("event-atomicity");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("event-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "event-job").unwrap();
    rusqlite::Connection::open(&db).unwrap().execute_batch("CREATE TRIGGER reject_job_started BEFORE INSERT ON events WHEN NEW.kind='job_started' BEGIN SELECT RAISE(ABORT, 'fixture rejects job_started'); END;").unwrap();
    let result = daemon.start_job(
        JobSpec::new(
            "event-job",
            std::env::current_exe().unwrap().to_string_lossy(),
            ["--exact", "fixture_child_process", "--nocapture"],
            "cpu-fixture",
        )
        .with_env("EMBERD_FIXTURE_CHILD", "1")
        .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000"),
    );
    assert!(result.is_err());
    assert_eq!(
        daemon.job_state("event-job").unwrap(),
        Some(JobState::Failed)
    );
    assert_eq!(daemon.lease_owner("cpu-fixture").unwrap(), None);
}

#[test]
fn receipt_publication_never_replaces_an_existing_file() {
    let root = sandbox("receipt-no-replace");
    let db = root.join("emberd.sqlite3");
    let receipt = root.join("receipt.json");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("receipt-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "receipt-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "receipt-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    daemon.stop_job("receipt-job").unwrap();
    fs::write(&receipt, b"pre-existing receipt bytes").unwrap();
    assert!(matches!(
        daemon.export_receipt("receipt-job", &receipt),
        Err(EmberdError::ReceiptAlreadyExists { .. })
    ));
    assert_eq!(fs::read(&receipt).unwrap(), b"pre-existing receipt bytes");
}
#[cfg(windows)]
fn force_terminate_process(pid: u32) {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::Threading::{
        OpenProcess, TerminateProcess, WaitForSingleObject, PROCESS_TERMINATE,
    };
    const SYNCHRONIZE_RIGHT: u32 = 0x0010_0000;
    let handle = unsafe { OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE_RIGHT, 0, pid) };
    if !handle.is_null() {
        unsafe {
            TerminateProcess(handle, 0xE0D00002);
            WaitForSingleObject(handle, 5000);
            CloseHandle(handle);
        }
    }
}

#[cfg(windows)]
#[test]
fn lifetime_handle_cannot_escape_from_root_to_descendant() {
    let root = sandbox("noninheritable-job-handle");
    let db = root.join("emberd.sqlite3");
    let child_pid_file = root.join("child.pid");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("lifetime-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "lifetime-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "lifetime-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "25")
            .with_env("EMBERD_FIXTURE_SPAWN_CHILD", "1")
            .with_env(
                "EMBERD_FIXTURE_CHILD_PID_FILE",
                child_pid_file.to_string_lossy(),
            ),
        )
        .unwrap();
    for _ in 0..100 {
        if child_pid_file.exists() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    let child_pid: u32 = fs::read_to_string(&child_pid_file)
        .unwrap()
        .parse()
        .unwrap();

    drop(daemon);
    thread::sleep(Duration::from_millis(500));
    let child_survived = process_is_alive(child_pid);
    if child_survived {
        force_terminate_process(child_pid);
    }
    assert!(
        !child_survived,
        "a descendant inherited the root-held Job Object lifetime handle"
    );
}
#[cfg(windows)]
#[test]
fn adoption_cannot_commit_after_a_newer_stopped_transition() {
    let root = sandbox("adopt-state-fence");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Arc::new(Daemon::open(&db).unwrap());
    daemon
        .bind_identity("race-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "race-job").unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "race-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();

    let opened = Arc::new(Barrier::new(2));
    let proceed = Arc::new(Barrier::new(2));
    let adopter = {
        let daemon = Arc::clone(&daemon);
        let opened = Arc::clone(&opened);
        let proceed = Arc::clone(&proceed);
        thread::spawn(move || {
            opened.wait();
            proceed.wait();
            daemon.adopt_job("race-job")
        })
    };
    opened.wait();
    let blocker = rusqlite::Connection::open(&db).unwrap();
    blocker.execute_batch("BEGIN IMMEDIATE").unwrap();
    proceed.wait();

    thread::sleep(Duration::from_millis(200));
    blocker
        .execute_batch(
            "UPDATE jobs SET state='stopped',updated_at_ms=updated_at_ms+1 WHERE job_id='race-job';
             INSERT INTO events(job_id,ts_ms,kind,payload_json)
             VALUES('race-job',0,'job_stopped','{}');
             COMMIT;",
        )
        .unwrap();

    let result = adopter.join().unwrap();
    let events = daemon.job_event_kinds("race-job").unwrap();
    force_terminate_process(started.pid);
    assert!(
        matches!(result, Err(EmberdError::InvalidTransition { .. })),
        "stale adoption unexpectedly committed: {result:?}"
    );
    let stopped = events
        .iter()
        .position(|kind| kind == "job_stopped")
        .unwrap();
    assert!(
        !events[stopped + 1..]
            .iter()
            .any(|kind| kind == "job_adopted"),
        "job_adopted was appended after job_stopped: {events:?}"
    );
}
#[cfg(windows)]
#[test]
fn stale_uncertain_reconciliation_cannot_overwrite_stopped_state() {
    let root = sandbox("uncertain-state-fence");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Arc::new(Daemon::open(&db).unwrap());
    daemon
        .bind_identity("uncertain-race", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("cpu-fixture", "uncertain-race")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "uncertain-race",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE jobs SET process_start_token='stale-token' WHERE job_id='uncertain-race'",
            [],
        )
        .unwrap();

    let opened = Arc::new(Barrier::new(2));
    let proceed = Arc::new(Barrier::new(2));
    let reconciler = {
        let daemon = Arc::clone(&daemon);
        let opened = Arc::clone(&opened);
        let proceed = Arc::clone(&proceed);
        thread::spawn(move || {
            opened.wait();
            proceed.wait();
            daemon.reconcile()
        })
    };
    opened.wait();
    let blocker = rusqlite::Connection::open(&db).unwrap();
    blocker.execute_batch("BEGIN IMMEDIATE").unwrap();
    proceed.wait();
    thread::sleep(Duration::from_millis(200));
    blocker
        .execute_batch(
            "UPDATE jobs SET state='stopped',updated_at_ms=updated_at_ms+1
             WHERE job_id='uncertain-race';
             INSERT INTO events(job_id,ts_ms,kind,payload_json)
             VALUES('uncertain-race',0,'job_stopped','{}');
             COMMIT;",
        )
        .unwrap();

    let result = reconciler.join().unwrap();
    let state = daemon.job_state("uncertain-race").unwrap();
    let events = daemon.job_event_kinds("uncertain-race").unwrap();
    force_terminate_process(started.pid);
    assert!(matches!(result, Err(EmberdError::InvalidTransition { .. })));
    assert_eq!(state, Some(JobState::Stopped));
    let stopped = events
        .iter()
        .position(|kind| kind == "job_stopped")
        .unwrap();
    assert!(
        !events[stopped + 1..]
            .iter()
            .any(|kind| kind == "job_reconciled_identity_conflict"),
        "stale reconciliation appended after stop: {events:?}"
    );
}

#[cfg(windows)]
#[test]
fn stale_dead_reconciliation_cannot_overwrite_stopped_state() {
    let root = sandbox("dead-state-fence");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Arc::new(Daemon::open(&db).unwrap());
    daemon
        .bind_identity("dead-race", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "dead-race").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "dead-race",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();
    drop(daemon);
    thread::sleep(Duration::from_millis(250));
    let daemon = Arc::new(Daemon::open(&db).unwrap());

    let opened = Arc::new(Barrier::new(2));
    let proceed = Arc::new(Barrier::new(2));
    let reconciler = {
        let daemon = Arc::clone(&daemon);
        let opened = Arc::clone(&opened);
        let proceed = Arc::clone(&proceed);
        thread::spawn(move || {
            opened.wait();
            proceed.wait();
            daemon.reconcile()
        })
    };
    opened.wait();
    let blocker = rusqlite::Connection::open(&db).unwrap();
    blocker.execute_batch("BEGIN IMMEDIATE").unwrap();
    proceed.wait();
    thread::sleep(Duration::from_millis(200));
    blocker
        .execute_batch(
            "UPDATE jobs SET state='stopped',updated_at_ms=updated_at_ms+1
             WHERE job_id='dead-race';
             INSERT INTO events(job_id,ts_ms,kind,payload_json)
             VALUES('dead-race',0,'job_stopped','{}');
             COMMIT;",
        )
        .unwrap();

    let result = reconciler.join().unwrap();
    let state = daemon.job_state("dead-race").unwrap();
    let events = daemon.job_event_kinds("dead-race").unwrap();
    assert!(matches!(result, Err(EmberdError::InvalidTransition { .. })));
    assert_eq!(state, Some(JobState::Stopped));
    let stopped = events
        .iter()
        .position(|kind| kind == "job_stopped")
        .unwrap();
    assert!(
        !events[stopped + 1..]
            .iter()
            .any(|kind| kind == "job_reconciled_dead"),
        "stale dead reconciliation appended after stop: {events:?}"
    );
}

#[cfg(windows)]
#[test]
fn starting_reconciliation_cannot_kill_a_concurrently_committed_start() {
    let root = sandbox("starting-kill-fence");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Arc::new(Daemon::open(&db).unwrap());
    daemon
        .bind_identity("starting-race", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("cpu-fixture", "starting-race")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "starting-race",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE jobs SET state='starting' WHERE job_id='starting-race'",
            [],
        )
        .unwrap();

    let blocker = rusqlite::Connection::open(&db).unwrap();
    blocker.execute_batch("BEGIN IMMEDIATE").unwrap();
    let proceed = Arc::new(Barrier::new(2));
    let reconciler = {
        let daemon = Arc::clone(&daemon);
        let proceed = Arc::clone(&proceed);
        thread::spawn(move || {
            proceed.wait();
            daemon.reconcile()
        })
    };
    proceed.wait();
    thread::sleep(Duration::from_millis(200));

    let alive_while_state_commit_is_fenced = process_is_alive(started.pid);
    blocker
        .execute_batch(
            "UPDATE jobs SET state='running',updated_at_ms=updated_at_ms+1
             WHERE job_id='starting-race';
             COMMIT;",
        )
        .unwrap();
    let result = reconciler.join().unwrap();

    if alive_while_state_commit_is_fenced {
        daemon.stop_job("starting-race").unwrap();
    }
    assert!(
        alive_while_state_commit_is_fenced,
        "reconciliation killed the cohort before winning the starting-state DB fence"
    );
    assert!(matches!(result, Err(EmberdError::InvalidTransition { .. })));
}
#[cfg(windows)]
#[test]
fn resident_daemon_reaps_natural_exit_records_status_and_releases_lease() {
    let root = sandbox("resident-reaper");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("finite-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "finite-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "finite-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();

    for _ in 0..200 {
        if daemon.job_state("finite-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }

    assert_eq!(
        daemon.job_state("finite-job").unwrap(),
        Some(JobState::Exited)
    );
    assert_eq!(daemon.job_exit_code("finite-job").unwrap(), Some(0));
    assert_eq!(daemon.lease_owner("cpu-fixture").unwrap(), None);
    assert!(!daemon.has_retained_process_handle("finite-job"));
    assert!(daemon
        .job_event_kinds("finite-job")
        .unwrap()
        .iter()
        .any(|kind| kind == "job_exited"));
}
#[cfg(windows)]
#[test]
fn state_store_has_exactly_one_resident_writer_owner() {
    let root = sandbox("single-writer");
    let db = root.join("emberd.sqlite3");
    let first = Daemon::open(&db).unwrap();
    assert!(matches!(
        Daemon::open(&db),
        Err(EmberdError::StateWriterBusy { .. })
    ));
    drop(first);
    Daemon::open(&db).unwrap();
}

#[cfg(windows)]
#[test]
fn daemon_handoff_cancels_old_monitor_and_records_exit_once() {
    let root = sandbox("monitor-handoff");
    let db = root.join("emberd.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("handoff-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "handoff-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "handoff-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBERD_FIXTURE_CHILD", "1")
            .with_env("EMBERD_FIXTURE_SLEEP_MS", "250"),
        )
        .unwrap();
    drop(daemon);

    let reopened = Daemon::open(&db).unwrap();
    reopened.adopt_job("handoff-job").unwrap();
    for _ in 0..300 {
        if reopened.job_state("handoff-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(
        reopened.job_state("handoff-job").unwrap(),
        Some(JobState::Exited)
    );
    let events = reopened.job_event_kinds("handoff-job").unwrap();
    assert_eq!(
        events.iter().filter(|kind| *kind == "job_exited").count(),
        1,
        "a former daemon monitor wrote after ownership handoff: {events:?}"
    );
    assert_eq!(reopened.lease_owner("cpu-fixture").unwrap(), None);
}
