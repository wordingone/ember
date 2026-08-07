// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::{Daemon, EmberLabError, JobSpec, JobState, RestartPolicy, SchedulePrediction};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Barrier,
};
use std::thread;
use std::time::Duration;
use std::time::{SystemTime, UNIX_EPOCH};

fn sandbox(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path =
        std::env::temp_dir().join(format!("ember-lab-{name}-{}-{nonce}", std::process::id()));
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

fn write_restore_manifest(root: &Path, job_id: &str) -> PathBuf {
    const GIB: u64 = 1024 * 1024 * 1024;
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let custody = root.join(format!("restore-custody-{job_id}"));
    fs::create_dir_all(&custody).unwrap();
    let mut env = BTreeMap::new();
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
        env.insert(key, path.to_string_lossy().into_owned());
    }
    env.insert("EMBER_LAB_FIXTURE_CHILD", "1".into());
    env.insert("EMBER_LAB_FIXTURE_SLEEP_MS", "30000".into());
    let config = root.join("restore-config.json");
    let data_manifest = root.join("restore-data.json");
    fs::write(&config, b"{\"config\":\"restore\"}").unwrap();
    fs::write(&data_manifest, b"{\"records\":1}").unwrap();
    let program = std::env::current_exe().unwrap();
    let manifest = root.join(format!("restore-manifest-{job_id}.json"));
    fs::write(
        &manifest,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": "ember-lab-dispatch-manifest-v3",
            "job_id": job_id,
            "source_commit": "5326043c344227c1b145a4ddbb3519cfa62d4943",
            "not_before_ms": now_ms.saturating_sub(1_000),
            "expires_at_ms": now_ms.saturating_add(600_000),
            "resource_lease": "server:8082",
            "program": {"path": program, "sha256": sha256(&program)},
            "args": ["--exact", "fixture_child_process", "--nocapture"],
            "workload_profile": {
                "profile_id": "evidence_verifier",
                "pinned_host_producers": [{"kind": "receipt_verifier", "maximum_bytes": 1}],
                "requires_ui_responsiveness": false
            },
            "env": env,
            "bindings": [
                {"kind": "config", "path": config, "sha256": sha256(&config)},
                {"kind": "manifest", "path": data_manifest, "sha256": sha256(&data_manifest)}
            ],
            "custody_root": custody,
            "storage_reserves": [{"root": root, "minimum_free_bytes": 1}],
            "minimum_free_vram_bytes": 1,
            "required_available_maximum_commit_bytes": 12 * GIB,
            "maximum_job_memory_bytes": 2 * GIB,
            "simulated_peak_commit_bytes": 1,
            "preflight_receipt": custody.join("preflight.json")
        }))
        .unwrap(),
    )
    .unwrap();
    manifest
}

#[test]
fn fixture_child_process() {
    if std::env::var("EMBER_LAB_FIXTURE_CHILD").as_deref() != Ok("1") {
        return;
    }
    if std::env::var("EMBER_LAB_FIXTURE_SPAWN_CHILD").as_deref() == Ok("1") {
        let child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "fixture_child_process", "--nocapture"])
            .env("EMBER_LAB_FIXTURE_CHILD", "1")
            .env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000")
            .env_remove("EMBER_LAB_FIXTURE_SPAWN_CHILD")
            .env_remove("EMBER_LAB_FIXTURE_CHILD_PID_FILE")
            .spawn()
            .unwrap();
        fs::write(
            std::env::var_os("EMBER_LAB_FIXTURE_CHILD_PID_FILE").unwrap(),
            child.id().to_string(),
        )
        .unwrap();
        drop(child);
    }
    let sleep_ms = std::env::var("EMBER_LAB_FIXTURE_SLEEP_MS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(30_000);
    if let Ok(message) = std::env::var("EMBER_LAB_FIXTURE_LOG_MESSAGE") {
        println!("stdout:{message}");
        eprintln!("stderr:{message}");
    }
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

#[cfg(windows)]
fn suspend_thread_id(thread_id: u32) {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::Threading::{OpenThread, SuspendThread, THREAD_SUSPEND_RESUME};

    let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, thread_id) };
    assert!(!thread.is_null(), "fixture main thread must be openable");
    let previous = unsafe { SuspendThread(thread) };
    unsafe { CloseHandle(thread) };
    assert_ne!(previous, u32::MAX, "fixture main thread must suspend");
}
#[test]
fn sqlite_wal_identity_binding_and_exclusive_lease_survive_reopen() {
    let root = sandbox("state");
    let db = root.join("ember-lab.sqlite3");
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
        Err(EmberLabError::LeaseConflict { .. })
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
        Err(EmberLabError::IdentityMismatch { .. })
    ));
}

#[test]
fn detached_job_is_adopted_stopped_and_exported_after_daemon_reopen() {
    let root = sandbox("job");
    let db = root.join("ember-lab.sqlite3");
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
    .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
    .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000");
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
    #[cfg(windows)]
    assert!(reopened.has_retained_process_handle("sleep-job"));
    #[cfg(not(windows))]
    assert!(!reopened.has_retained_process_handle("sleep-job"));
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
        Err(EmberLabError::ReceiptAlreadyExists { .. })
    ));

    let payload: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(payload["schema"], "ember-lab-operational-receipt-v1");
    assert_eq!(payload["job_id"], "sleep-job");
    assert_eq!(payload["identity_sha256"], identity_hash);
    assert_eq!(payload["resource_lease"], "cpu-fixture");
    assert_eq!(payload["state"], "stopped");
    for field in ["binary_sha256", "source_sha256"] {
        let value = payload["ember_lab_identity"][field].as_str().unwrap();
        assert_eq!(value.len(), 64);
        assert!(value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()));
    }
    let events = payload["events"].as_array().unwrap();
    assert!(events.iter().any(|row| row["kind"] == "job_started"));
    assert!(events.iter().any(|row| row["kind"] == "job_adopted"));
    assert!(events.iter().any(|row| row["kind"] == "job_stopped"));
}

#[test]
fn schedule_alarm_turns_red_after_seven_days_even_without_any_prediction() {
    let root = sandbox("schedule-empty-week");
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    let started_at_ms = daemon.schedule_monitor_started_at_ms().unwrap();

    let before = daemon
        .schedule_alarm_state_at(started_at_ms + 7 * 24 * 60 * 60 * 1000 - 1)
        .unwrap();
    assert_eq!(before["alarms"]["zero_schedule_receipts_7d"], false);

    let overdue = daemon
        .schedule_alarm_state_at(started_at_ms + 7 * 24 * 60 * 60 * 1000)
        .unwrap();
    assert_eq!(overdue["alarms"]["zero_schedule_receipts_7d"], true);
}

#[test]
fn schedule_lease_requires_prediction_and_measurement_drives_durable_alarms() {
    let root = sandbox("schedule-loop");
    let db = root.join("ember-lab.sqlite3");
    let alarm_path = root.join("schedule-alarms.json");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("screen-1", &identity, &identity_hash)
        .unwrap();

    assert!(matches!(
        daemon.acquire_lease("schedule:compute-primitive", "screen-1"),
        Err(EmberLabError::SchedulePredictionRequired { .. })
    ));

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    daemon
        .register_schedule_prediction(SchedulePrediction {
            job_id: "screen-1".into(),
            artifact_class: "compute-primitive".into(),
            predicted_duration_ms: 60_000,
            predicted_tokens: 4096,
            predicted_program_completion_ms: now + 2_000_000,
            absolute_deadline_ms: now + 1_000_000,
        })
        .unwrap();
    daemon
        .acquire_lease("schedule:compute-primitive", "screen-1")
        .unwrap();

    let overdue = daemon
        .schedule_alarm_state_at(now + 7 * 24 * 60 * 60 * 1000 + 1)
        .unwrap();
    assert_eq!(
        overdue["schema_version"],
        "ember-lab-schedule-alarm-state-v1"
    );
    assert_eq!(overdue["alarms"]["prediction_overrun"], true);
    assert_eq!(overdue["alarms"]["zero_schedule_receipts_7d"], true);
    assert_eq!(overdue["alarms"]["absolute_deadline_drift"], true);

    daemon
        .record_schedule_measurement("screen-1", 55_000, 4096, "COMPLETED", &"a".repeat(64))
        .unwrap();
    assert_eq!(
        daemon.lease_owner("schedule:compute-primitive").unwrap(),
        None,
        "shadow-mode measurement must release its schedule lease",
    );
    let measured = daemon.schedule_alarm_state_at(now + 120_000).unwrap();
    assert_eq!(measured["alarms"]["prediction_overrun"], false);
    assert_eq!(measured["alarms"]["zero_schedule_receipts_7d"], false);
    assert_eq!(measured["runs"][0]["measured_duration_ms"], 55_000);
    assert_eq!(
        measured["runs"][0]["measurement_receipt_sha256"],
        "a".repeat(64)
    );

    daemon
        .write_schedule_alarm_state_at(&alarm_path, now + 120_000)
        .unwrap();
    let persisted: Value = serde_json::from_slice(&fs::read(&alarm_path).unwrap()).unwrap();
    assert_eq!(persisted, measured);

    drop(daemon);
    let reopened = Daemon::open(&db).unwrap();
    assert_eq!(
        reopened.schedule_alarm_state_at(now + 120_000).unwrap(),
        measured
    );
}
#[test]
fn unbound_owner_cannot_acquire_a_durable_lease() {
    let root = sandbox("unbound-lease");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.acquire_lease("heavy-workload", "missing-identity"),
        Err(EmberLabError::IdentityNotFound { .. })
    ));
}

#[test]
fn ember_lab_server_cycle_uses_bound_authority_and_governed_restore() {
    use ember_lab::server_supervisor::{EndpointHealth, RestoreEvidence, ServerCycleRequest};

    let root = sandbox("server-cycle-red");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("server-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "server-job").unwrap();

    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 8082,
        "pid": 4321,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));

    let request = ServerCycleRequest {
        authority_path,
        authority_sha256,
        receipt_path: root.join("server-cycle-receipt.json"),
        observation: ember_lab::server_supervisor::ServerObservation {
            process_alive: true,
            endpoint: EndpointHealth::Dead,
        },
        available_headroom_bytes: 2,
        required_headroom_bytes: 1,
        now_ms: 1_000,
    };
    let mut restored = false;
    let receipt = daemon
        .supervise_server_cycle(request, |_authority| {
            restored = true;
            Ok(RestoreEvidence {
                restore_cost_s: 1.25,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(receipt.decision, "RESTORED");
    assert_eq!(receipt.death_cause.as_deref(), Some("endpoint_dead"));
    assert_eq!(receipt.restore_cost_s, Some(1.25));
    assert!(restored);
    assert_eq!(
        daemon.job_event_kinds("server-job").unwrap(),
        vec!["server_restored"]
    );
    let persisted: Value =
        serde_json::from_slice(&fs::read(root.join("server-cycle-receipt.json")).unwrap()).unwrap();
    assert_eq!(persisted["schema"], "ember-lab-operational-receipt-v1");
    assert_eq!(persisted["events"][0]["kind"], "server_restored");
    assert_eq!(persisted["events"][0]["payload"]["restore_cost_s"], 1.25);
    assert_eq!(
        persisted["events"][0]["payload"]["death_cause"],
        "endpoint_dead"
    );
    assert!(persisted.to_string().contains("server_restored"));
    assert!(!persisted.to_string().contains("authority_path"));
}

#[test]
fn ember_lab_server_cycle_covers_health_outage_hung_headroom_and_alarm_law() {
    use ember_lab::server_supervisor::{EndpointHealth, ServerCycleRequest};

    let root = sandbox("server-cycle-matrix");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("server-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "server-job").unwrap();
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 8082,
        "pid": 4321,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let mut sequence = 0u32;
    let mut request = |endpoint: EndpointHealth, now_ms: i64, headroom: u64| {
        sequence += 1;
        ServerCycleRequest {
            authority_path: authority_path.clone(),
            authority_sha256: authority_sha256.clone(),
            receipt_path: root.join(format!("cycle-{sequence}.json")),
            observation: ember_lab::server_supervisor::ServerObservation {
                process_alive: true,
                endpoint,
            },
            available_headroom_bytes: headroom,
            required_headroom_bytes: 10,
            now_ms,
        }
    };

    daemon
        .plan_outage("server:8082", 0, 2_000, "planned maintenance")
        .unwrap();
    let mut restore_calls = 0;
    let waited = daemon
        .supervise_server_cycle(request(EndpointHealth::Dead, 1_000, 20), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(waited.decision, "WAIT_PLANNED_OUTAGE");
    assert_eq!(restore_calls, 0);

    let expired = daemon
        .supervise_server_cycle(request(EndpointHealth::Dead, 3_000, 20), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(expired.outage_state, "expired");
    assert_eq!(expired.decision, "RESTORED");

    daemon
        .plan_outage("server:8082", 0, 10_000, "closed maintenance")
        .unwrap();
    assert_eq!(daemon.cancel_outages("server:8082").unwrap(), 1);
    let closed = daemon
        .supervise_server_cycle(request(EndpointHealth::Dead, 4_000, 20), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(closed.outage_state, "closed");
    assert_eq!(closed.decision, "RESTORED");

    let hung = daemon
        .supervise_server_cycle(request(EndpointHealth::Hung, 5_000, 20), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 2.0,
                health_status: 503,
            })
        })
        .unwrap();
    assert_eq!(hung.death_cause.as_deref(), Some("endpoint_hung"));
    assert_eq!(hung.decision, "RESTORE_FAILED");

    let headroom = daemon
        .supervise_server_cycle(request(EndpointHealth::Dead, 3_500, 9), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(headroom.decision, "RESTORE_REFUSED_HEADROOM");

    let alarm = daemon
        .supervise_server_cycle(request(EndpointHealth::Dead, 7_000, 20), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(alarm.decision, "ALARM_BACKOFF");

    let healthy = daemon
        .supervise_server_cycle(request(EndpointHealth::Healthy, 8_000, 20), |_authority| {
            restore_calls += 1;
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .unwrap();
    assert_eq!(healthy.decision, "HEALTHY");
    assert_eq!(restore_calls, 3);
    assert!(daemon.job_event_kinds("server-job").unwrap().len() >= 7);
}

#[test]
fn ember_lab_server_cycle_rejects_unbound_or_overwritten_authority() {
    use ember_lab::server_supervisor::{EndpointHealth, ServerCycleRequest};

    let root = sandbox("server-cycle-authority-negative");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("server-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "server-job").unwrap();
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 8082,
        "pid": 4321,
        "identity_sha256": identity_hash,
    });
    let bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &bytes).unwrap();
    let sha256 = format!("{:x}", Sha256::digest(&bytes));
    let request = || ServerCycleRequest {
        authority_path: authority_path.clone(),
        authority_sha256: sha256.clone(),
        receipt_path: root.join("cycle.json"),
        observation: ember_lab::server_supervisor::ServerObservation {
            process_alive: true,
            endpoint: EndpointHealth::Dead,
        },
        available_headroom_bytes: 20,
        required_headroom_bytes: 10,
        now_ms: 1_000,
    };
    fs::write(&authority_path, b"tampered").unwrap();
    assert!(daemon
        .supervise_server_cycle(request(), |_authority| {
            Err(EmberLabError::InvalidTransition {
                job_id: "server-job".into(),
                detail: "restore must not run".into(),
            })
        })
        .is_err());
    fs::write(&authority_path, bytes).unwrap();
    assert!(daemon
        .supervise_server_cycle(request(), |_authority| {
            Ok(ember_lab::server_supervisor::RestoreEvidence {
                restore_cost_s: 1.0,
                health_status: 200,
            })
        })
        .is_ok());
    assert!(
        daemon
            .supervise_server_cycle(request(), |_authority| {
                Err(EmberLabError::InvalidTransition {
                    job_id: "server-job".into(),
                    detail: "receipt must not overwrite".into(),
                })
            })
            .is_err(),
        "receipt output is atomic and must not be overwritten"
    );
}

#[test]
fn ember_lab_live_server_cycle_uses_real_endpoint_and_existing_dispatch_authority() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-cycle-live");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("live-server-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("server:8082", "live-server-job")
        .unwrap();

    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0u8; 128];
        let _ = std::io::Read::read(&mut stream, &mut request);
        std::io::Write::write_all(
            &mut stream,
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",
        )
        .unwrap();
    });

    let fixture = std::env::current_exe().unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "live-server-job",
                fixture.to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "live-server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": port,
        "pid": started.pid,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let request = ServerLiveCycleRequest {
        authority_path,
        authority_sha256,
        receipt_path: root.join("live-cycle.json"),
        restore_manifest_path: root.join("unused-restore-manifest.json"),
        required_headroom_bytes: 1,
        now_ms: 1_000,
    };
    daemon.register_server_supervision(&request).unwrap();
    let receipt = daemon
        .supervise_registered_server_once(1_000)
        .unwrap()
        .pop()
        .unwrap();
    daemon.stop_job("live-server-job").unwrap();
    server.join().unwrap();
    assert_eq!(receipt.decision, "HEALTHY");
    assert_eq!(receipt.endpoint_health, "healthy");
    assert!(fs::metadata(root.join("live-cycle-1000.json")).is_ok());
}

#[test]
fn server_cycle_derives_restart_count_from_authoritative_activity_events() {
    use ember_lab::server_supervisor::{EndpointHealth, RestoreEvidence, ServerCycleRequest};

    let root = sandbox("server-cycle-derived-restarts");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("server-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "server-job").unwrap();

    let connection = rusqlite::Connection::open(&db).unwrap();
    for (timestamp, kind) in [
        (400_i64, "server_restored"),
        (500_i64, "server_restored"),
        (600_i64, "server_restore_failed"),
    ] {
        connection
            .execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
                rusqlite::params![
                    "server-job",
                    timestamp,
                    kind,
                    serde_json::json!({
                        "supervision_id": "ember-lab-server-supervision-v1:server:8082"
                    })
                    .to_string()
                ],
            )
            .unwrap();
    }
    drop(connection);

    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 8082,
        "pid": 4321,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));

    let receipt = daemon
        .supervise_server_cycle(
            ServerCycleRequest {
                authority_path,
                authority_sha256,
                receipt_path: root.join("server-cycle-receipt.json"),
                observation: ember_lab::server_supervisor::ServerObservation {
                    process_alive: true,
                    endpoint: EndpointHealth::Dead,
                },
                available_headroom_bytes: 2,
                required_headroom_bytes: 1,
                now_ms: 1_000,
            },
            |_authority| {
                Ok(RestoreEvidence {
                    restore_cost_s: 1.0,
                    health_status: 200,
                })
            },
        )
        .unwrap();
    assert_eq!(receipt.restarts_last_hour, 3);
    assert_eq!(receipt.decision, "ALARM_BACKOFF");
}

#[test]
fn server_cycle_backoff_spans_rebound_job_ids_and_rejects_restore() {
    use ember_lab::server_supervisor::{EndpointHealth, RestoreEvidence, ServerCycleRequest};

    let root = sandbox("server-cycle-stable-supervision-id");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("current-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "current-job").unwrap();

    let supervision_id = "ember-lab-server-supervision-v1:server:8082";
    let connection = rusqlite::Connection::open(&db).unwrap();
    for (timestamp, job_id) in [
        (400_i64, "old-job"),
        (500_i64, "rebound-1"),
        (600_i64, "rebound-2"),
    ] {
        connection
            .execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'server_restored',?3)",
                rusqlite::params![
                    job_id,
                    timestamp,
                    serde_json::json!({"supervision_id": supervision_id}).to_string()
                ],
            )
            .unwrap();
    }
    drop(connection);

    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "current-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 8082,
        "pid": 4321,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let restore_calls = Arc::new(AtomicUsize::new(0));
    let restore_calls_for_callback = Arc::clone(&restore_calls);
    let receipt = daemon
        .supervise_server_cycle(
            ServerCycleRequest {
                authority_path,
                authority_sha256,
                receipt_path: root.join("server-cycle-stable-receipt.json"),
                observation: ember_lab::server_supervisor::ServerObservation {
                    process_alive: true,
                    endpoint: EndpointHealth::Dead,
                },
                available_headroom_bytes: 2,
                required_headroom_bytes: 1,
                now_ms: 1_000,
            },
            |_authority| {
                restore_calls_for_callback.fetch_add(1, Ordering::SeqCst);
                Ok(RestoreEvidence {
                    restore_cost_s: 1.0,
                    health_status: 200,
                })
            },
        )
        .unwrap();
    assert_eq!(receipt.decision, "ALARM_BACKOFF");
    assert_eq!(restore_calls.load(Ordering::SeqCst), 0);
    let receipt_json = serde_json::to_value(&receipt).unwrap();
    assert_eq!(receipt_json["supervision_id"], supervision_id);
}

#[test]
fn ember_lab_server_supervision_exposes_one_bounded_lifecycle_tick() {
    let root = sandbox("server-supervision-loop");
    let database = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&database).unwrap();
    let receipts = daemon.supervise_registered_server_once(1_000).unwrap();
    assert!(receipts.is_empty());
}

#[test]
fn server_supervision_rejects_foreign_pid_and_receipt_custody_escape() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-supervision-custody");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("foreign-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "foreign-job").unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "foreign-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "foreign-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 8082,
        "pid": started.pid.saturating_add(1),
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let escaped = ServerLiveCycleRequest {
        authority_path: authority_path.clone(),
        authority_sha256: authority_sha256.clone(),
        receipt_path: root.parent().unwrap().join("escaped-server-receipt.json"),
        restore_manifest_path: root.join("restore.json"),
        required_headroom_bytes: 1,
        now_ms: 1_000,
    };
    assert!(daemon.register_server_supervision(&escaped).is_err());

    let in_custody = ServerLiveCycleRequest {
        authority_path,
        authority_sha256,
        receipt_path: root.join("server-receipt.json"),
        restore_manifest_path: root.join("restore.json"),
        required_headroom_bytes: 1,
        now_ms: 1_000,
    };
    assert!(matches!(
        daemon.supervise_server_live_cycle(in_custody),
        Err(EmberLabError::ProcessIdentityMismatch { .. })
    ));
    assert_eq!(
        daemon.job_state("foreign-job").unwrap(),
        Some(JobState::Running)
    );
    daemon.stop_job("foreign-job").unwrap();
}

#[test]
fn server_live_cycle_fences_dead_endpoint_before_restore_dispatch() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-supervision-handoff");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("handoff-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "handoff-job").unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "handoff-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "handoff-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": port,
        "pid": started.pid,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let receipt = daemon
        .supervise_server_live_cycle(ServerLiveCycleRequest {
            authority_path,
            authority_sha256,
            receipt_path: root.join("handoff-receipt.json"),
            restore_manifest_path: root.join("invalid-restore.json"),
            required_headroom_bytes: 1,
            now_ms: 1_000,
        })
        .unwrap();
    assert_eq!(receipt.decision, "RESTORE_FAILED");
    assert_eq!(
        daemon.job_state("handoff-job").unwrap(),
        Some(JobState::Stopped)
    );
    assert_eq!(daemon.lease_owner("server:8082").unwrap(), None);
    assert!(fs::metadata(root.join("handoff-receipt.json")).is_ok());
}

#[test]
fn server_live_cycle_open_planned_outage_does_not_fence_or_dispatch() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-supervision-open-outage");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("outage-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("server:8082", "outage-job").unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "outage-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    daemon
        .plan_outage("server:8082", 900, 2_000, "planned maintenance")
        .unwrap();
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "outage-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 65_51,
        "pid": started.pid,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let receipt = daemon
        .supervise_server_live_cycle(ServerLiveCycleRequest {
            authority_path,
            authority_sha256,
            receipt_path: root.join("outage-receipt.json"),
            restore_manifest_path: root.join("must-not-dispatch.json"),
            required_headroom_bytes: 1,
            now_ms: 1_000,
        })
        .unwrap();
    assert_eq!(receipt.decision, "WAIT_PLANNED_OUTAGE");
    assert_eq!(
        daemon.job_state("outage-job").unwrap(),
        Some(JobState::Running)
    );
    assert_eq!(
        daemon.lease_owner("server:8082").unwrap().as_deref(),
        Some("outage-job")
    );
    daemon.stop_job("outage-job").unwrap();
}

#[test]
fn background_supervision_errors_are_receipted_and_appended() {
    let root = sandbox("server-supervision-error");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let error = EmberLabError::InvalidTransition {
        job_id: "supervised-job".into(),
        detail: "fixture supervision failure".into(),
    };
    daemon.record_supervision_error(1_000, &error).unwrap();
    let path = root
        .join("ember-lab.sqlite3.logs")
        .join("server-supervision-errors")
        .join("1000.json");
    let payload: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(payload["schema"], "ember-lab-supervision-error-v1");
    assert_eq!(payload["observed_at_ms"], 1_000);
    assert_eq!(payload["scientific_capability_evidence"], false);
    assert!(payload["error"]
        .as_str()
        .unwrap()
        .contains("fixture supervision failure"));
    assert_eq!(
        daemon
            .job_event_kinds("ember-lab-supervisor")
            .unwrap()
            .as_slice(),
        &["server_supervision_error"]
    );
}

#[test]
fn server_live_cycle_rebinds_successful_restore_for_subsequent_ticks() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-supervision-rebind");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("old-server-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("server:8082", "old-server-job")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "old-server-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    listener.set_nonblocking(true).unwrap();
    let responses = Arc::new(AtomicUsize::new(0));
    let response_counter = Arc::clone(&responses);
    let server = thread::spawn(move || {
        for _ in 0..40 {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    let response = if response_counter.fetch_add(1, Ordering::SeqCst) == 0 {
                        b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n".to_vec()
                    } else {
                        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec()
                    };
                    let _ = std::io::Write::write_all(&mut stream, &response);
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(25));
                }
                Err(_) => break,
            }
        }
    });
    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "old-server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": port,
        "pid": started.pid,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let manifest_path = write_restore_manifest(&root, "restored-server-job");
    let receipt = daemon
        .supervise_server_live_cycle(ServerLiveCycleRequest {
            authority_path,
            authority_sha256,
            receipt_path: root.join("rebind-receipt.json"),
            restore_manifest_path: manifest_path,
            required_headroom_bytes: 1,
            now_ms: 1_000,
        })
        .unwrap();
    assert_eq!(receipt.decision, "RESTORED");
    assert_eq!(
        daemon.job_state("restored-server-job").unwrap(),
        Some(JobState::Running)
    );
    let next = daemon
        .supervise_registered_server_once(2_000)
        .unwrap()
        .pop()
        .unwrap();
    assert_eq!(next.decision, "HEALTHY");
    assert_eq!(next.job_id, "restored-server-job");
    let following = daemon
        .supervise_registered_server_once(3_000)
        .unwrap()
        .pop()
        .unwrap();
    assert_eq!(following.decision, "HEALTHY");
    assert_eq!(following.job_id, "restored-server-job");
    assert_eq!(
        daemon.lease_owner("server:8082").unwrap().as_deref(),
        Some("restored-server-job")
    );
    daemon.stop_job("restored-server-job").unwrap();
    server.join().unwrap();
    assert_eq!(responses.load(Ordering::SeqCst), 4);
}

#[test]
fn server_live_cycle_restarts_across_rebound_authorities_then_backs_off() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-supervision-stable-backoff");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("old-server-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("server:8082", "old-server-job")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "old-server-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    listener.set_nonblocking(true).unwrap();
    let responses = Arc::new(AtomicUsize::new(0));
    let response_counter = Arc::clone(&responses);
    let server = thread::spawn(move || {
        for _ in 0..400 {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    let index = response_counter.fetch_add(1, Ordering::SeqCst);
                    let response = if index.is_multiple_of(2) {
                        b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n".to_vec()
                    } else {
                        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec()
                    };
                    let _ = std::io::Write::write_all(&mut stream, &response);
                    if index >= 6 {
                        break;
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(10));
                }
                Err(_) => break,
            }
        }
    });
    let mut authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "old-server-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": port,
        "pid": started.pid,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let mut job_id = "old-server-job".to_string();

    for iteration in 1..=3 {
        if iteration > 1 {
            daemon.stop_job(&job_id).unwrap();
        }
        let next_job_id = format!("rebound-server-job-{iteration}");
        let manifest_path = write_restore_manifest(&root, &next_job_id);
        let authority_bytes = fs::read(&authority_path).unwrap();
        let receipt = daemon
            .supervise_server_live_cycle(ServerLiveCycleRequest {
                authority_path: authority_path.clone(),
                authority_sha256: format!("{:x}", Sha256::digest(&authority_bytes)),
                receipt_path: root.join(format!("stable-backoff-{iteration}.json")),
                restore_manifest_path: manifest_path,
                required_headroom_bytes: 1,
                now_ms: iteration * 1_000,
            })
            .unwrap();
        assert_eq!(receipt.decision, "RESTORED");
        assert_eq!(
            receipt.supervision_id,
            "ember-lab-server-supervision-v1:server:8082"
        );
        assert_eq!(
            daemon.job_state(&next_job_id).unwrap(),
            Some(JobState::Running)
        );
        let stem = authority_path.file_stem().unwrap().to_string_lossy();
        let rebound_name = format!(
            "{stem}-rebound-{}.json",
            &format!("{:x}", Sha256::digest(next_job_id.as_bytes()))[..16]
        );
        authority_path = root.join(rebound_name);
        job_id = next_job_id;
    }

    daemon.stop_job(&job_id).unwrap();
    let authority_bytes = fs::read(&authority_path).unwrap();
    let fourth = daemon
        .supervise_server_live_cycle(ServerLiveCycleRequest {
            authority_path,
            authority_sha256: format!("{:x}", Sha256::digest(&authority_bytes)),
            receipt_path: root.join("stable-backoff-fourth.json"),
            restore_manifest_path: root.join("must-not-dispatch-fourth.json"),
            required_headroom_bytes: 1,
            now_ms: 4_000,
        })
        .unwrap();
    assert_eq!(fourth.decision, "ALARM_BACKOFF");
    assert_eq!(fourth.restarts_last_hour, 3);
    assert_eq!(daemon.job_state("rebound-server-job-4").unwrap(), None);
    assert_eq!(daemon.lease_owner("server:8082").unwrap(), None);
    assert_eq!(responses.load(Ordering::SeqCst), 7);
    server.join().unwrap();
}

#[test]
fn server_live_cycle_accepts_natural_exit_after_lease_release() {
    use ember_lab::server_supervisor::ServerLiveCycleRequest;

    let root = sandbox("server-supervision-natural-exit");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("natural-exit-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("server:8082", "natural-exit-job")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "natural-exit-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "server:8082",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "1"),
        )
        .unwrap();
    for _ in 0..100 {
        if daemon.job_state("natural-exit-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(25));
    }
    assert_eq!(
        daemon.job_state("natural-exit-job").unwrap(),
        Some(JobState::Exited)
    );
    assert_eq!(daemon.lease_owner("server:8082").unwrap(), None);

    let authority_path = root.join("server-authority.json");
    let authority = serde_json::json!({
        "schema_version": "ember-lab-server-authority-v1",
        "job_id": "natural-exit-job",
        "resource_lease": "server:8082",
        "target": "llama-server",
        "host": "127.0.0.1",
        "port": 6551,
        "pid": started.pid,
        "identity_sha256": identity_hash,
    });
    let authority_bytes = serde_json::to_vec(&authority).unwrap();
    fs::write(&authority_path, &authority_bytes).unwrap();
    let authority_sha256 = format!("{:x}", Sha256::digest(&authority_bytes));
    let receipt = daemon
        .supervise_server_live_cycle(ServerLiveCycleRequest {
            authority_path,
            authority_sha256,
            receipt_path: root.join("natural-exit-receipt.json"),
            restore_manifest_path: root.join("invalid-restore.json"),
            required_headroom_bytes: 1,
            now_ms: 1_000,
        })
        .unwrap();
    assert_eq!(receipt.decision, "RESTORE_FAILED");
    assert_eq!(daemon.lease_owner("server:8082").unwrap(), None);
}

#[test]
fn concurrent_lease_claims_have_exactly_one_winner() {
    let root = sandbox("lease-race");
    let db = root.join("ember-lab.sqlite3");
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
            .filter(|result| matches!(result, Err(EmberLabError::LeaseConflict { .. })))
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
fn dead_persisted_running_job_is_exited_unknown_and_releases_its_lease() {
    let root = sandbox("dead-reconcile");
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();
    drop(daemon);
    thread::sleep(Duration::from_millis(250));

    let reopened = Daemon::open(&db).unwrap();
    assert!(matches!(
        reopened.adopt_job("short-job"),
        Err(EmberLabError::ProcessUnavailable { .. })
    ));
    assert_eq!(
        reopened.job_state("short-job").unwrap(),
        Some(JobState::Exited)
    );
    assert_eq!(reopened.lease_owner("cpu-fixture").unwrap(), None);
    assert_eq!(reopened.job_exit_code("short-job").unwrap(), None);
    assert!(reopened
        .job_event_kinds("short-job")
        .unwrap()
        .iter()
        .any(|kind| kind == "job_reconciled_exited_unknown"));
    let first = reopened
        .export_content_addressed_receipt("short-job", &root.join("receipts"))
        .unwrap();
    let second = reopened
        .export_content_addressed_receipt("short-job", &root.join("receipts"))
        .unwrap();
    assert_eq!(first, second);
    let payload: Value = serde_json::from_slice(&fs::read(&first.path).unwrap()).unwrap();
    assert_eq!(payload["state"], "exited");
    assert_eq!(payload["logs"]["stdout"]["sealed"], false);
    assert!(payload["logs"]["stdout"]["sha256"].is_null());
    let enriched = reopened
        .export_content_addressed_receipt_with_observation(
            "short-job",
            &root.join("receipts"),
            &json!({"phase":"test"}),
        )
        .unwrap();
    assert_eq!(enriched.sha256, sha256(&enriched.path));
    let enriched_payload: Value =
        serde_json::from_slice(&fs::read(&enriched.path).unwrap()).unwrap();
    assert_eq!(enriched_payload["rehearsal"]["phase"], "test");
    let original_payload: Value = serde_json::from_slice(&fs::read(&first.path).unwrap()).unwrap();
    assert!(original_payload.get("rehearsal").is_none());
}

#[cfg(windows)]
#[test]
fn failed_launch_exports_stable_receipt_without_blessing_unsealed_logs() {
    let root = sandbox("failed-launch-receipt");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("failed-launch", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("cpu-fixture", "failed-launch")
        .unwrap();
    assert!(daemon
        .start_job(JobSpec::new(
            "failed-launch",
            root.join("does-not-exist.exe").to_string_lossy(),
            std::iter::empty::<String>(),
            "cpu-fixture",
        ))
        .is_err());
    assert_eq!(
        daemon.job_state("failed-launch").unwrap(),
        Some(JobState::Failed)
    );
    assert_eq!(daemon.lease_owner("cpu-fixture").unwrap(), None);
    let artifact = daemon
        .export_content_addressed_receipt("failed-launch", &root.join("receipts"))
        .unwrap();
    let payload: Value = serde_json::from_slice(&fs::read(artifact.path).unwrap()).unwrap();
    assert_eq!(payload["state"], "failed");
    assert_eq!(payload["logs"]["stdout"]["sealed"], false);
    assert!(payload["logs"]["stdout"]["sha256"].is_null());
}

#[test]
fn receipt_export_reverifies_bound_identity_bytes() {
    let root = sandbox("receipt-identity");
    let db = root.join("ember-lab.sqlite3");
    let receipt = root.join("receipt.json");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("receipt-job", &identity, &identity_hash)
        .unwrap();
    fs::write(&identity, b"tampered after binding").unwrap();
    assert!(matches!(
        daemon.export_receipt("receipt-job", &receipt),
        Err(EmberLabError::IdentityMismatch { .. })
    ));
    assert!(!receipt.exists());
}

#[cfg(windows)]
#[test]
fn stopping_job_terminates_its_entire_process_cohort() {
    let root = sandbox("cohort");
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000")
            .with_env("EMBER_LAB_FIXTURE_SPAWN_CHILD", "1")
            .with_env(
                "EMBER_LAB_FIXTURE_CHILD_PID_FILE",
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
    let db = root.join("ember-lab.sqlite3");
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
        .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
        .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
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
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    daemon.stop_job("receipt-job").unwrap();
    fs::write(&receipt, b"pre-existing receipt bytes").unwrap();
    assert!(matches!(
        daemon.export_receipt("receipt-job", &receipt),
        Err(EmberLabError::ReceiptAlreadyExists { .. })
    ));
    assert_eq!(fs::read(&receipt).unwrap(), b"pre-existing receipt bytes");
}

#[test]
fn phase_events_are_daemon_bound_and_foreign_bytes_do_not_authorize() {
    let root = sandbox("phase-event-authority");
    let db = root.join("ember-lab.sqlite3");
    let foreign = root.join("foreign-train.json");
    fs::write(
        &foreign,
        br#"{"schema":"ember-lab-phase-evidence-v1","producer":"ember-lab-daemon","result":"COMPLETED","job_id":"phase-job","phase":"train"}"#,
    )
    .unwrap();
    let foreign_sha256 = sha256(&foreign);
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("phase-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "phase-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "phase-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
        .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let forged_dir = root
        .join("ember-lab.sqlite3.logs")
        .join("rehearsal")
        .join(ember_lab::hash_bytes(b"phase-job"));
    fs::create_dir_all(&forged_dir).unwrap();
    let forged_path = forged_dir.join("forged-train.json");
    fs::write(
        &forged_path,
        br#"{"schema":"ember-lab-phase-evidence-v1","producer":"ember-lab-daemon","result":"COMPLETED","job_id":"phase-job","phase":"train","operation_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","operation":"ember-lab-daemon-phase-owner:train","operation_evidence":{"kind":"running_job_observed","pid":1,"lease_epoch":1},"observed_at_ms":1,"lease_epoch":1,"pid":1,"identity_verified":true,"job_started_event":true}"#,
    )
    .unwrap();
    let (forged_pid, forged_lease_epoch): (u32, i64) = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT pid,lease_epoch FROM jobs WHERE job_id='phase-job'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
            rusqlite::params![
                "phase-job",
                1_i64,
                "ember_lab_phase_train",
                serde_json::json!({
                    "producer":"ember-lab-daemon",
                    "job_id":"phase-job",
                    "phase":"train",
                    "evidence_file_name":"forged-train.json",
                    "evidence_sha256": sha256(&forged_path),
                    "operation_sha256":"f".repeat(64),
                    "lease_epoch":forged_lease_epoch,
                    "pid":forged_pid,
                    "event_authority_sha256":"0".repeat(64),
                })
                .to_string(),
            ],
        )
        .unwrap();
    assert!(!daemon
        .phase_event_authorized("phase-job", "train", &foreign_sha256)
        .unwrap());
    assert!(!daemon
        .phase_event_authorized("phase-job", "train", &sha256(&forged_path))
        .unwrap());
    assert!(daemon.load_authorized_phase_evidence("phase-job").is_err());
    let produced = daemon.execute_minimal_episode("phase-job").unwrap();
    let consumed = daemon.load_authorized_phase_evidence("phase-job").unwrap();
    assert_eq!(consumed.len(), 6);
    let evidence = produced
        .iter()
        .find(|evidence| evidence.phase == ember_lab::rehearsal::Phase::Train)
        .unwrap();
    assert!(daemon
        .phase_event_authorized("phase-job", "train", &evidence.sha256)
        .unwrap());
    assert_eq!(produced.len(), 6);
    assert!(produced.iter().all(|evidence| evidence
        .path
        .starts_with(root.join("ember-lab.sqlite3.logs").join("rehearsal"))));
    fs::write(&evidence.path, br#"{"producer":"foreign"}"#).unwrap();
    assert!(!daemon
        .phase_event_authorized("phase-job", "train", &evidence.sha256)
        .unwrap());
    daemon.stop_job("phase-job").unwrap();
    assert!(daemon.execute_minimal_episode("phase-job").is_err());
}

#[test]
fn phase_owner_refuses_before_dispatch_and_emits_no_later_phase_events() {
    let root = sandbox("phase-event-no-dispatch");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("phase-not-started", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("cpu-fixture", "phase-not-started")
        .unwrap();

    assert!(daemon.execute_minimal_episode("phase-not-started").is_err());
    assert!(!daemon
        .job_event_kinds("phase-not-started")
        .unwrap()
        .iter()
        .any(|kind| kind.starts_with("ember_lab_phase_")));
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
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25")
            .with_env("EMBER_LAB_FIXTURE_SPAWN_CHILD", "1")
            .with_env(
                "EMBER_LAB_FIXTURE_CHILD_PID_FILE",
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
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
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
        matches!(result, Err(EmberLabError::InvalidTransition { .. })),
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
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
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
    assert!(matches!(
        result,
        Err(EmberLabError::InvalidTransition { .. })
    ));
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
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25"),
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
    assert!(matches!(
        result,
        Err(EmberLabError::InvalidTransition { .. })
    ));
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
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
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
    assert!(matches!(
        result,
        Err(EmberLabError::InvalidTransition { .. })
    ));
}
#[cfg(windows)]
#[test]
fn resident_daemon_reaps_natural_exit_records_status_and_releases_lease() {
    let root = sandbox("resident-reaper");
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25"),
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
    let db = root.join("ember-lab.sqlite3");
    let first = Daemon::open(&db).unwrap();
    assert!(matches!(
        Daemon::open(&db),
        Err(EmberLabError::StateWriterBusy { .. })
    ));
    drop(first);
    Daemon::open(&db).unwrap();
}

#[cfg(windows)]
#[test]
fn daemon_handoff_cancels_old_monitor_and_records_exit_once() {
    let root = sandbox("monitor-handoff");
    let db = root.join("ember-lab.sqlite3");
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
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "250"),
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

#[cfg(windows)]
#[test]
fn planned_outage_blocks_launch_and_receipt_is_content_addressed() {
    let root = sandbox("outage-receipt");
    let db = root.join("ember-lab.sqlite3");
    let receipts = root.join("receipts");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("outage-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "outage-job").unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    daemon
        .plan_outage(
            "cpu-fixture",
            now - 1,
            now + 60_000,
            "operator-planned maintenance",
        )
        .unwrap();
    let spec = || {
        JobSpec::new(
            "outage-job",
            std::env::current_exe().unwrap().to_string_lossy(),
            ["--exact", "fixture_child_process", "--nocapture"],
            "cpu-fixture",
        )
        .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
        .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25")
    };
    assert!(matches!(
        daemon.start_job(spec()),
        Err(EmberLabError::PlannedOutageActive { .. })
    ));
    daemon.cancel_outages("cpu-fixture").unwrap();
    daemon.start_job(spec()).unwrap();
    for _ in 0..200 {
        if daemon.job_state("outage-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(
        daemon.job_restart_policy("outage-job").unwrap(),
        RestartPolicy::Never
    );
    let first = daemon
        .export_content_addressed_receipt("outage-job", &receipts)
        .unwrap();
    let second = daemon
        .export_content_addressed_receipt("outage-job", &receipts)
        .unwrap();
    assert_eq!(first, second);
    assert_eq!(
        first.path.file_name().unwrap().to_string_lossy(),
        format!("{}.json", first.sha256)
    );
    assert_eq!(sha256(&first.path), first.sha256);
    let payload: Value = serde_json::from_slice(&fs::read(&first.path).unwrap()).unwrap();
    assert_eq!(payload["restart_policy"], "never");
    assert_eq!(payload["exit_code"], 0);
}
#[cfg(windows)]
#[test]
fn process_stdout_and_stderr_are_append_only_and_receipt_bound() {
    let root = sandbox("process-logs");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("logged-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "logged-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "logged-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_LOG_MESSAGE", "durable-output")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();
    for _ in 0..200 {
        if daemon.job_state("logged-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    let (stdout_path, stderr_path) = daemon.job_log_paths("logged-job").unwrap();
    assert!(fs::read_to_string(&stdout_path)
        .unwrap()
        .contains("stdout:durable-output"));
    assert!(fs::read_to_string(&stderr_path)
        .unwrap()
        .contains("stderr:durable-output"));
    let artifact = daemon
        .export_content_addressed_receipt("logged-job", &root.join("receipts"))
        .unwrap();
    let payload: Value = serde_json::from_slice(&fs::read(artifact.path).unwrap()).unwrap();
    assert_eq!(payload["logs"]["stdout"]["sha256"], sha256(&stdout_path));
    assert_eq!(payload["logs"]["stderr"]["sha256"], sha256(&stderr_path));
    assert_eq!(
        payload["logs"]["stdout"]["file_name"],
        stdout_path.file_name().unwrap().to_string_lossy().as_ref()
    );
}

#[cfg(windows)]
#[test]
fn nonterminal_job_cannot_publish_a_content_addressed_receipt() {
    let root = sandbox("nonterminal-receipt");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("running-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "running-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "running-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();

    assert!(matches!(
        daemon.export_content_addressed_receipt("running-job", &root.join("receipts")),
        Err(EmberLabError::NonTerminalReceipt { state, .. }) if state == "running"
    ));
    daemon.stop_job("running-job").unwrap();
}

#[cfg(windows)]
#[test]
fn sealed_log_tampering_is_detected_instead_of_blessed() {
    let root = sandbox("sealed-log-tamper");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("tamper-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "tamper-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "tamper-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_LOG_MESSAGE", "sealed")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();
    for _ in 0..200 {
        if daemon.job_state("tamper-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(
        daemon.job_state("tamper-job").unwrap(),
        Some(JobState::Exited)
    );
    let (stdout_path, _) = daemon.job_log_paths("tamper-job").unwrap();
    fs::write(&stdout_path, b"rewritten-after-seal").unwrap();

    assert!(matches!(
        daemon.export_content_addressed_receipt("tamper-job", &root.join("receipts")),
        Err(EmberLabError::LogEvidenceMismatch { stream, .. }) if stream == "stdout"
    ));
}

#[cfg(windows)]
#[test]
fn terminal_receipt_ignores_outage_events_after_its_persisted_cutoff() {
    let root = sandbox("receipt-outage-cutoff");
    let db = root.join("ember-lab.sqlite3");
    let receipts = root.join("receipts");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("cutoff-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "cutoff-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "cutoff-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "25"),
        )
        .unwrap();
    for _ in 0..200 {
        if daemon.job_state("cutoff-job").unwrap() == Some(JobState::Exited) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(
        daemon.job_state("cutoff-job").unwrap(),
        Some(JobState::Exited)
    );
    let first = daemon
        .export_content_addressed_receipt("cutoff-job", &receipts)
        .unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    daemon
        .plan_outage("cpu-fixture", now + 1000, now + 2000, "later outage")
        .unwrap();
    daemon.cancel_outages("cpu-fixture").unwrap();
    let second = daemon
        .export_content_addressed_receipt("cutoff-job", &receipts)
        .unwrap();
    assert_eq!(first, second);
}

#[cfg(windows)]
#[test]
fn prepared_recovery_defers_resume_while_outage_is_active() {
    let root = sandbox("prepared-outage-recovery");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("prepared-job", &identity, &identity_hash)
        .unwrap();
    daemon.acquire_lease("cpu-fixture", "prepared-job").unwrap();
    daemon
        .start_job(
            JobSpec::new(
                "prepared-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let thread_id: u32 = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT main_thread_id FROM jobs WHERE job_id='prepared-job'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    suspend_thread_id(thread_id);
    drop(daemon);
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE jobs SET state='prepared' WHERE job_id='prepared-job' AND state='running'",
            [],
        )
        .unwrap();

    let reopened = Daemon::open(&db).unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    reopened
        .plan_outage("cpu-fixture", now - 1, now + 60_000, "defer recovery")
        .unwrap();
    reopened.reconcile().unwrap();
    assert_eq!(
        reopened.job_state("prepared-job").unwrap(),
        Some(JobState::Prepared)
    );
    assert!(reopened
        .job_event_kinds("prepared-job")
        .unwrap()
        .iter()
        .any(|kind| kind == "job_resume_deferred_outage"));
    reopened.cancel_outages("cpu-fixture").unwrap();
    reopened.reconcile().unwrap();
    assert_eq!(
        reopened.job_state("prepared-job").unwrap(),
        Some(JobState::Running)
    );
    reopened.stop_job("prepared-job").unwrap();
}

#[cfg(windows)]
#[test]
fn prepared_recovery_terminates_process_when_running_commit_fails() {
    let root = sandbox("prepared-commit-failure");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("prepared-failure", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("cpu-fixture", "prepared-failure")
        .unwrap();
    let handle = daemon
        .start_job(
            JobSpec::new(
                "prepared-failure",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let thread_id: u32 = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT main_thread_id FROM jobs WHERE job_id='prepared-failure'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    suspend_thread_id(thread_id);
    drop(daemon);
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute_batch(
            "UPDATE jobs SET state='prepared' WHERE job_id='prepared-failure' AND state='running';
             CREATE TRIGGER fail_recovered_running
             BEFORE UPDATE OF state ON jobs
             WHEN OLD.job_id='prepared-failure' AND NEW.state='running'
             BEGIN SELECT RAISE(FAIL, 'forced recovered-running persistence failure'); END;",
        )
        .unwrap();

    let reopened = Daemon::open(&db).unwrap();
    assert!(matches!(
        reopened.reconcile(),
        Err(EmberLabError::Sqlite(_))
    ));
    assert_eq!(
        reopened.job_state("prepared-failure").unwrap(),
        Some(JobState::Failed)
    );
    assert_eq!(reopened.lease_owner("cpu-fixture").unwrap(), None);
    for _ in 0..200 {
        if !process_is_alive(handle.pid) {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert!(
        !process_is_alive(handle.pid),
        "a resumed process escaped after its running-state commit failed"
    );
    assert!(reopened
        .job_event_kinds("prepared-failure")
        .unwrap()
        .iter()
        .any(|kind| kind == "job_recovered_resume_commit_failed"));
}

#[cfg(windows)]
#[test]
fn pre_resume_fence_error_does_not_kill_a_still_prepared_process() {
    let root = sandbox("pre-resume-fence-failure");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("pre-resume-failure", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("cpu-fixture", "pre-resume-failure")
        .unwrap();
    let handle = daemon
        .start_job(
            JobSpec::new(
                "pre-resume-failure",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "cpu-fixture",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    let thread_id: u32 = rusqlite::Connection::open(&db)
        .unwrap()
        .query_row(
            "SELECT main_thread_id FROM jobs WHERE job_id='pre-resume-failure'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    suspend_thread_id(thread_id);
    drop(daemon);
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute_batch(
            "UPDATE jobs SET state='prepared' WHERE job_id='pre-resume-failure' AND state='running';
             CREATE TRIGGER fail_pre_resume_fence
             BEFORE UPDATE OF updated_at_ms ON jobs
             WHEN OLD.job_id='pre-resume-failure' AND OLD.state='prepared'
             BEGIN SELECT RAISE(FAIL, 'forced pre-resume fence failure'); END;",
        )
        .unwrap();

    let reopened = Daemon::open(&db).unwrap();
    assert!(matches!(
        reopened.reconcile(),
        Err(EmberLabError::Sqlite(_))
    ));
    assert_eq!(
        reopened.job_state("pre-resume-failure").unwrap(),
        Some(JobState::Prepared)
    );
    assert_eq!(
        reopened.lease_owner("cpu-fixture").unwrap(),
        Some("pre-resume-failure".into())
    );
    assert!(
        process_is_alive(handle.pid),
        "a pre-resume fence error must not kill the still-valid prepared process"
    );
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute_batch("DROP TRIGGER fail_pre_resume_fence;")
        .unwrap();
    reopened.reconcile().unwrap();
    assert_eq!(
        reopened.job_state("pre-resume-failure").unwrap(),
        Some(JobState::Running)
    );
    reopened.stop_job("pre-resume-failure").unwrap();
}

#[cfg(windows)]
#[test]
fn protective_owned_stop_requests_checkpoint_then_stops_only_after_durable_decision() {
    let root = sandbox("protective-owned-stop");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("protected-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("protected-resource", "protected-job")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "protected-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "protected-resource",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE resource_guard_state
             SET admission_state='frozen',
                 reason='physical_available_below_survival_floor',
                 observed_at_ms=1234,
                 oracle_evidence_required=1,
                 observation_json='{\"result\":\"SURVIVAL_FLOOR_BREACH\"}'
             WHERE singleton=1",
            [],
        )
        .unwrap();

    let artifact = daemon
        .protective_owned_stop("protected-job", Duration::from_millis(25))
        .unwrap();

    assert!(!process_is_alive(started.pid));
    assert_eq!(
        daemon.job_state("protected-job").unwrap(),
        Some(JobState::Stopped)
    );
    assert_eq!(daemon.lease_owner("protected-resource").unwrap(), None);
    assert_eq!(sha256(&artifact.path), artifact.sha256);
    let receipt: Value = serde_json::from_slice(&fs::read(&artifact.path).unwrap()).unwrap();
    assert_eq!(
        receipt["schema_version"],
        "ember-lab-protective-owned-stop-v1"
    );
    assert_eq!(receipt["result"], "PROTECTIVE_OWNED_STOP_AUTHORIZED");
    assert_eq!(receipt["reason"], "host_protection_not_causation");
    assert_eq!(receipt["job_id"], "protected-job");
    assert_eq!(receipt["lease"]["resource"], "protected-resource");
    assert_eq!(receipt["lease"]["owner_job_id"], "protected-job");
    assert_eq!(receipt["process"]["pid"], started.pid);
    assert_eq!(receipt["process"]["identity_verified"], true);
    assert_eq!(receipt["process"]["job_object_membership_verified"], true);
    assert_eq!(receipt["checkpoint_request"]["result"], "GRACE_EXPIRED");
    assert_eq!(receipt["checkpoint_request"]["grace_ms"], 25);
    assert_eq!(
        receipt["termination"]["decision_receipt_persisted_before_termination"],
        true
    );
    let request_name = receipt["checkpoint_request"]["request_artifact"]
        .as_str()
        .unwrap();
    let request_path = artifact.path.parent().unwrap().join(request_name);
    assert!(request_path.is_file());
    assert_eq!(
        sha256(&request_path),
        receipt["checkpoint_request"]["request_sha256"]
    );
    assert!(daemon
        .job_event_kinds("protected-job")
        .unwrap()
        .iter()
        .any(|kind| kind == "protective_owned_stop_completed"));
}

#[cfg(windows)]
#[test]
fn daemon_lifetime_guard_automatically_protects_an_owned_job_after_sticky_freeze() {
    let root = sandbox("protective-owned-stop-monitor");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("monitor-protected-job", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("monitor-protected-resource", "monitor-protected-job")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "monitor-protected-job",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "monitor-protected-resource",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE resource_guard_state
             SET admission_state='frozen',
                 reason='commit_remaining_below_survival_floor',
                 observed_at_ms=1234,
                 oracle_evidence_required=1,
                 observation_json='{\"result\":\"SURVIVAL_FLOOR_BREACH\"}'
             WHERE singleton=1",
            [],
        )
        .unwrap();

    for _ in 0..100 {
        if daemon.job_state("monitor-protected-job").unwrap() == Some(JobState::Stopped) {
            break;
        }
        thread::sleep(Duration::from_millis(100));
    }

    let automatic_state = daemon.job_state("monitor-protected-job").unwrap();
    let automatic_lease_owner = daemon.lease_owner("monitor-protected-resource").unwrap();
    let automatic_events = daemon.job_event_kinds("monitor-protected-job").unwrap();
    if process_is_alive(started.pid) {
        daemon.stop_job("monitor-protected-job").unwrap();
    }
    assert_eq!(
        automatic_state,
        Some(JobState::Stopped),
        "daemon-lifetime guard did not execute ProtectiveOwnedStop"
    );
    assert_eq!(automatic_lease_owner, None);
    assert!(automatic_events
        .iter()
        .any(|kind| kind == "protective_owned_stop_completed"));
    let receipt_count = fs::read_dir(root.join("ember-lab.sqlite3.logs"))
        .unwrap()
        .filter_map(|entry| entry.ok())
        .filter(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .starts_with("protective-owned-stop-")
        })
        .count();
    assert_eq!(receipt_count, 1);
}

#[cfg(windows)]
#[test]
fn protective_owned_stop_refuses_identity_conflict_without_killing_process() {
    let root = sandbox("protective-owned-stop-identity");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("protected-identity", &identity, &identity_hash)
        .unwrap();
    daemon
        .acquire_lease("protected-resource", "protected-identity")
        .unwrap();
    let started = daemon
        .start_job(
            JobSpec::new(
                "protected-identity",
                std::env::current_exe().unwrap().to_string_lossy(),
                ["--exact", "fixture_child_process", "--nocapture"],
                "protected-resource",
            )
            .with_env("EMBER_LAB_FIXTURE_CHILD", "1")
            .with_env("EMBER_LAB_FIXTURE_SLEEP_MS", "30000"),
        )
        .unwrap();
    rusqlite::Connection::open(&db)
        .unwrap()
        .execute_batch(
            "UPDATE resource_guard_state
             SET admission_state='frozen',
                 reason='commit_remaining_below_survival_floor',
                 observed_at_ms=1234,
                 oracle_evidence_required=1,
                 observation_json='{\"result\":\"SURVIVAL_FLOOR_BREACH\"}';
             UPDATE jobs SET process_start_token='foreign-token'
             WHERE job_id='protected-identity';",
        )
        .unwrap();

    let result = daemon.protective_owned_stop("protected-identity", Duration::from_millis(25));

    assert!(matches!(
        result,
        Err(EmberLabError::ProcessControlUncertain { .. })
    ));
    assert!(process_is_alive(started.pid));
    assert_eq!(
        daemon.job_state("protected-identity").unwrap(),
        Some(JobState::Running)
    );
    assert_eq!(
        daemon.lease_owner("protected-resource").unwrap().as_deref(),
        Some("protected-identity")
    );
    daemon.stop_job("protected-identity").unwrap();
}

#[test]
fn pre_log_schema_migrates_without_reinterpreting_existing_job_identity() {
    let root = sandbox("schema-migration");
    let db = root.join("ember-lab.sqlite3");
    let (identity, identity_hash) = write_identity(&root);
    let connection = rusqlite::Connection::open(&db).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
             INSERT INTO metadata(key,value) VALUES('schema_version','1');
             CREATE TABLE jobs(
               job_id TEXT PRIMARY KEY,
               program TEXT NOT NULL,
               args_json TEXT NOT NULL,
               env_json TEXT NOT NULL,
               resource TEXT NOT NULL,
               lease_epoch INTEGER NOT NULL,
               pid INTEGER NOT NULL DEFAULT 0,
               main_thread_id INTEGER NOT NULL DEFAULT 0,
               job_object_name TEXT NOT NULL,
               process_start_token TEXT NOT NULL DEFAULT '',
               executable_identity TEXT NOT NULL DEFAULT '',
               argv_sha256 TEXT NOT NULL,
               state TEXT NOT NULL,
               exit_code INTEGER,
               exited_at_ms INTEGER,
               started_at_ms INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL
             );
             INSERT INTO jobs(
               job_id,program,args_json,env_json,resource,lease_epoch,
               job_object_name,argv_sha256,state,started_at_ms,updated_at_ms
             ) VALUES(
               'legacy-job','fixture.exe','[]','{}','cpu-fixture',7,
               'ember-lab-job-legacy','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
               'failed',1,1
             );",
        )
        .unwrap();
    drop(connection);

    let daemon = Daemon::open(&db).unwrap();
    daemon
        .bind_identity("legacy-job", &identity, &identity_hash)
        .unwrap();
    assert_eq!(
        daemon.job_restart_policy("legacy-job").unwrap(),
        RestartPolicy::Never
    );
    let (stdout, stderr) = daemon.job_log_paths("legacy-job").unwrap();
    assert!(!stdout.as_os_str().is_empty());
    assert!(!stderr.as_os_str().is_empty());
    assert_ne!(stdout, stderr);
    let receipts = root.join("receipts");
    let first = daemon
        .export_content_addressed_receipt("legacy-job", &receipts)
        .unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    daemon
        .plan_outage("cpu-fixture", now + 1000, now + 2000, "post-migration")
        .unwrap();
    daemon.cancel_outages("cpu-fixture").unwrap();
    let second = daemon
        .export_content_addressed_receipt("legacy-job", &receipts)
        .unwrap();
    assert_eq!(first, second);
}
