// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(all(windows, debug_assertions))]

use ember_lab::{
    arm_named_end_probe_pause_for_test, probe_host_commit_capacity,
    release_named_end_probe_pause_for_test, wait_for_named_end_probe_pause_for_test, Daemon,
    EmberLabError, ResourceGuardRearmRequest,
};
use rusqlite::Connection;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use windows_sys::Win32::Foundation::{CloseHandle, FILETIME};
use windows_sys::Win32::System::Memory::{
    VirtualAlloc, VirtualFree, MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, PAGE_READWRITE,
};
use windows_sys::Win32::System::Threading::{
    GetProcessTimes, OpenProcess, CREATE_NO_WINDOW, PROCESS_QUERY_LIMITED_INFORMATION,
};

const GIB: u64 = 1024 * 1024 * 1024;
const FLOOR: u64 = 10 * GIB;
const TARGET: u64 = 6 * GIB;
const CUTOFF: u64 = 4 * GIB;
const HARD_CAP: u64 = 24 * GIB;
const PHYSICAL_REARM_PREFLIGHT: u64 = 12 * GIB;
const COMMIT_REARM_PREFLIGHT: u64 = 15 * GIB;
const MINIMUM_RUNNER_REMAINING: u64 = 2 * GIB;
const DIAGNOSTIC_BYTES: usize = 64 * 1024 * 1024;
const STAGE_SCHEMA: &str = "ember-issue898-external-fence-stage-v1";

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock before Unix epoch")
        .as_millis() as i64
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha256_file(path: &Path) -> String {
    sha256_bytes(&fs::read(path).expect("read file for SHA-256"))
}

fn write_new(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("create-new {}: {error}", path.display()));
    file.write_all(bytes).expect("write immutable file");
    file.sync_all().expect("sync immutable file");
}

struct StageLedger {
    file: File,
}

impl StageLedger {
    fn create(path: &Path) -> Self {
        Self {
            file: OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(path)
                .unwrap_or_else(|error| panic!("create stage ledger {}: {error}", path.display())),
        }
    }

    fn record(&mut self, leg: &str, stage: &str, result: &str, evidence: Value) {
        let line = serde_json::to_vec(&json!({
            "schema_version": STAGE_SCHEMA,
            "recorded_at_ms": now_ms(),
            "leg": leg,
            "stage": stage,
            "result": result,
            "evidence": evidence,
        }))
        .expect("serialize stage line");
        self.file.write_all(&line).expect("write stage line");
        self.file.write_all(b"\n").expect("terminate stage line");
        self.file.sync_all().expect("sync stage line");
    }
}

fn current_process_start_token() -> String {
    process_start_token(std::process::id())
}

fn process_start_token(pid: u32) -> String {
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
    assert!(
        !handle.is_null(),
        "OpenProcess({pid}) failed: {}",
        std::io::Error::last_os_error()
    );
    let (mut creation, mut exit, mut kernel, mut user): (FILETIME, FILETIME, FILETIME, FILETIME) =
        unsafe { std::mem::zeroed() };
    let ok = unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) };
    unsafe { CloseHandle(handle) };
    assert_ne!(
        ok,
        0,
        "GetProcessTimes({pid}) failed: {}",
        std::io::Error::last_os_error()
    );
    format!(
        "{:08x}{:08x}",
        creation.dwHighDateTime, creation.dwLowDateTime
    )
}

struct UntouchedCommit(*mut core::ffi::c_void);

impl UntouchedCommit {
    fn reserve_and_commit(bytes: usize) -> Self {
        let address = unsafe {
            VirtualAlloc(
                std::ptr::null(),
                bytes,
                MEM_RESERVE | MEM_COMMIT,
                PAGE_READWRITE,
            )
        };
        assert!(
            !address.is_null(),
            "VirtualAlloc({bytes}) failed: {}",
            std::io::Error::last_os_error()
        );
        Self(address)
    }
}

impl Drop for UntouchedCommit {
    fn drop(&mut self) {
        if !self.0.is_null() {
            let ok = unsafe { VirtualFree(self.0, 0, MEM_RELEASE) };
            assert_ne!(
                ok,
                0,
                "VirtualFree failed: {}",
                std::io::Error::last_os_error()
            );
            self.0 = std::ptr::null_mut();
        }
    }
}

#[test]
fn issue898_external_commit_fixture_child() {
    if std::env::var("EMBER_ISSUE898_DISPATCH_CHILD").as_deref() == Ok("1") {
        thread::sleep(Duration::from_secs(30));
        return;
    }
    if std::env::var("EMBER_ISSUE898_EXTERNAL_FIXTURE").as_deref() != Ok("1") {
        return;
    }
    let bytes: usize = std::env::var("EMBER_ISSUE898_COMMIT_BYTES")
        .expect("fixture allocation bytes")
        .parse()
        .expect("fixture allocation bytes are numeric");
    let ready =
        PathBuf::from(std::env::var_os("EMBER_ISSUE898_READY").expect("fixture ready path"));
    let release =
        PathBuf::from(std::env::var_os("EMBER_ISSUE898_RELEASE").expect("fixture release path"));
    let allocation = UntouchedCommit::reserve_and_commit(bytes);
    write_new(
        &ready,
        &serde_json::to_vec(&json!({
            "pid": std::process::id(),
            "process_start_token": current_process_start_token(),
            "committed_bytes": bytes,
            "pages_touched": 0,
        }))
        .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(180);
    while !release.exists() {
        assert!(
            Instant::now() < deadline,
            "fixture owner did not release before deadline"
        );
        thread::sleep(Duration::from_millis(100));
    }
    drop(allocation);
}

fn wait_for_file(path: &Path, timeout: Duration) {
    let deadline = Instant::now() + timeout;
    while !path.is_file() {
        assert!(
            Instant::now() < deadline,
            "timed out waiting for {}",
            path.display()
        );
        thread::sleep(Duration::from_millis(100));
    }
}

struct ForeignFixture {
    child: Child,
    pid: u32,
    start_token: String,
    release: PathBuf,
}

impl Drop for ForeignFixture {
    fn drop(&mut self) {
        if matches!(self.child.try_wait(), Ok(None)) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

fn spawn_fixture(root: &Path, bytes: u64) -> ForeignFixture {
    let ready = root.join("fixture-ready.json");
    let release = root.join("fixture-release.intent");
    let stdout = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(root.join("fixture.stdout.log"))
        .expect("create fixture stdout");
    let stderr = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(root.join("fixture.stderr.log"))
        .expect("create fixture stderr");
    let child = Command::new(std::env::current_exe().expect("current test executable"))
        .args([
            "--exact",
            "issue898_external_commit_fixture_child",
            "--nocapture",
        ])
        .env("EMBER_ISSUE898_EXTERNAL_FIXTURE", "1")
        .env("EMBER_ISSUE898_COMMIT_BYTES", bytes.to_string())
        .env("EMBER_ISSUE898_READY", &ready)
        .env("EMBER_ISSUE898_RELEASE", &release)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .expect("spawn hidden external fixture");
    let pid = child.id();
    wait_for_file(&ready, Duration::from_secs(30));
    let receipt: Value = serde_json::from_slice(&fs::read(&ready).unwrap()).unwrap();
    let reported_pid = receipt["pid"].as_u64().unwrap() as u32;
    let reported_token = receipt["process_start_token"].as_str().unwrap().to_owned();
    assert_eq!(reported_pid, pid);
    assert_eq!(reported_token, process_start_token(pid));
    assert_eq!(receipt["pages_touched"], 0);
    write_new(
        &root.join("fixture-failsafe-cleanup-intent.json"),
        &serde_json::to_vec(&json!({
            "schema_version": "ember-issue898-fixture-failsafe-cleanup-intent-v1",
            "recorded_at_ms": now_ms(),
            "pid": pid,
            "process_start_token": reported_token,
            "authority": "fixture_owner_retained_child_handle",
            "action_on_unwind": "kill_and_wait_exact_retained_child",
        }))
        .unwrap(),
    );
    ForeignFixture {
        child,
        pid,
        start_token: reported_token,
        release,
    }
}

fn release_fixture(mut fixture: ForeignFixture, ledger: &mut StageLedger, leg: &str) {
    ledger.record(
        leg,
        "owner_release_intent",
        "RECORDED_BEFORE_ACTION",
        json!({"pid": fixture.pid, "process_start_token": fixture.start_token}),
    );
    write_new(&fixture.release, b"owner_release\n");
    let status = fixture.child.wait().expect("wait for fixture release");
    assert!(status.success(), "fixture release failed: {status}");
    ledger.record(
        leg,
        "owner_release",
        "PASS",
        json!({"pid": fixture.pid, "process_start_token": fixture.start_token, "exit_status": status.code()}),
    );
}

fn kill_fixture(mut fixture: ForeignFixture, ledger: &mut StageLedger) {
    ledger.record(
        "survival_red",
        "owner_kill_intent",
        "RECORDED_BEFORE_ACTION",
        json!({"pid": fixture.pid, "process_start_token": fixture.start_token}),
    );
    assert_eq!(process_start_token(fixture.pid), fixture.start_token);
    fixture
        .child
        .kill()
        .expect("kill exact retained child handle");
    let status = fixture.child.wait().expect("wait exact killed child");
    ledger.record(
        "survival_red",
        "owner_kill",
        "PASS",
        json!({"pid": fixture.pid, "process_start_token": fixture.start_token, "exit_status": status.code()}),
    );
}

fn wait_for_foreign_state(
    daemon: &Daemon,
    expected: &str,
    timeout: Duration,
    predicate: impl Fn(&Value) -> bool,
) -> Value {
    let deadline = Instant::now() + timeout;
    loop {
        let status = daemon
            .foreign_process_pressure_status()
            .expect("foreign pressure status");
        if status["state"] == expected && predicate(&status) {
            return status;
        }
        assert!(
            Instant::now() < deadline,
            "foreign state did not reach {expected}: {status}"
        );
        thread::sleep(Duration::from_millis(250));
    }
}

fn wait_for_named_exit_observation(db: &Path, pid: u32, timeout: Duration) -> Value {
    let deadline = Instant::now() + timeout;
    loop {
        let connection = Connection::open(db).unwrap();
        let mut statement = connection
            .prepare(
                "SELECT payload_json FROM foreign_process_pressure_observations ORDER BY seq DESC",
            )
            .unwrap();
        let rows = statement
            .query_map([], |row| row.get::<_, String>(0))
            .unwrap();
        for row in rows {
            let observation: Value = serde_json::from_str(&row.unwrap()).unwrap();
            let named_absent = observation["named_foreign_processes"]
                .as_array()
                .is_some_and(Vec::is_empty);
            let exact_exit = observation["exited_processes"]
                .as_array()
                .is_some_and(|exits| {
                    exits.iter().any(|exit| {
                        exit["pid"] == pid && exit["phase"] == "named_process_end_probe"
                    })
                });
            if named_absent && exact_exit {
                return observation;
            }
        }
        assert!(
            Instant::now() < deadline,
            "durable named-process exit observation did not arrive for PID {pid}"
        );
        thread::sleep(Duration::from_millis(250));
    }
}

fn write_dispatch_manifest(root: &Path, job_id: &str) -> PathBuf {
    const REQUIRED_AVAILABLE_COMMIT: u64 = 16 * GIB;
    const MAXIMUM_JOB_MEMORY: u64 = 6 * GIB;
    const SIMULATED_PEAK: u64 = GIB;
    let custody = root.join(format!("custody-{job_id}"));
    fs::create_dir(&custody).unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBER_ISSUE898_DISPATCH_CHILD", "1".to_string());
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
        fs::create_dir(&path).unwrap();
        env.insert(name, path.to_string_lossy().into_owned());
    }
    let binding = root.join(format!("{job_id}-config.json"));
    let data = root.join(format!("{job_id}-data.json"));
    write_new(&binding, b"{\"config\":\"bound\"}");
    write_new(&data, b"{\"records\":1}");
    let program = std::env::current_exe().unwrap();
    let at = now_ms();
    let path = root.join(format!("{job_id}-dispatch.json"));
    write_new(
        &path,
        &serde_json::to_vec(&json!({
            "schema_version": "ember-lab-dispatch-manifest-v3",
            "job_id": job_id,
            "source_commit": std::env::var("GITHUB_SHA").unwrap_or_else(|_| "0000000000000000000000000000000000000000".into()),
            "not_before_ms": at - 1_000,
            "expires_at_ms": at + 120_000,
            "resource_lease": format!("issue898-{job_id}"),
            "program": {"path": program, "sha256": sha256_file(&program)},
            "args": ["--exact", "issue898_external_commit_fixture_child", "--nocapture"],
            "workload_profile": {
                "profile_id": "evidence_verifier",
                "pinned_host_producers": [{"kind": "receipt_verifier", "maximum_bytes": SIMULATED_PEAK}],
                "requires_ui_responsiveness": false,
                "cpu_rate_percent": 25
            },
            "cpu_pacing_class": "unpaced",
            "window_contract": "headless_no_windows",
            "env": env,
            "bindings": [
                {"kind": "config", "path": binding, "sha256": sha256_file(&binding)},
                {"kind": "manifest", "path": data, "sha256": sha256_file(&data)}
            ],
            "custody_root": custody,
            "storage_reserves": [{"root": root, "minimum_free_bytes": 1}],
            "minimum_free_vram_bytes": 0,
            "required_available_maximum_commit_bytes": REQUIRED_AVAILABLE_COMMIT,
            "maximum_job_memory_bytes": MAXIMUM_JOB_MEMORY,
            "simulated_peak_commit_bytes": SIMULATED_PEAK,
            "preflight_receipt": custody.join("preflight.json")
        }))
        .unwrap(),
    );
    path
}

fn attempt_dispatch(
    daemon: &Daemon,
    manifest: &Path,
) -> Result<ember_lab::DispatchOutcome, EmberLabError> {
    daemon.dispatch_manifest_at_with_probes_and_host(
        manifest,
        now_ms(),
        |_root| Ok(u64::MAX / 2),
        || Ok(u64::MAX / 2),
        probe_host_commit_capacity,
    )
}

fn wait_for_first_healthy_after(db: &Path, freeze_seq: i64, timeout: Duration) -> i64 {
    let deadline = Instant::now() + timeout;
    loop {
        let connection = Connection::open(db).unwrap();
        let found = connection.query_row(
            "SELECT observed_at_ms FROM resource_guard_observations WHERE seq>?1 AND outcome='healthy' ORDER BY seq LIMIT 1",
            [freeze_seq],
            |row| row.get::<_, i64>(0),
        );
        if let Ok(observed_at_ms) = found {
            return observed_at_ms;
        }
        assert!(
            Instant::now() < deadline,
            "no healthy resource-guard sample after release"
        );
        thread::sleep(Duration::from_millis(250));
    }
}

fn healthy_tail(db: &Path, freeze_seq: i64) -> Vec<i64> {
    let connection = Connection::open(db).unwrap();
    let mut statement = connection
        .prepare("SELECT observed_at_ms,outcome FROM resource_guard_observations WHERE seq>?1 ORDER BY seq")
        .unwrap();
    let rows = statement
        .query_map([freeze_seq], |row| {
            Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
        })
        .unwrap();
    let mut tail = Vec::new();
    for row in rows {
        let (at, outcome) = row.unwrap();
        if outcome == "healthy" {
            tail.push(at);
        } else {
            tail.clear();
        }
    }
    tail
}

fn write_commit_diagnostic(
    root: &Path,
    frozen_observation_sha256: &str,
    first_healthy_at_ms: i64,
) -> (PathBuf, String, i64) {
    let allocation = UntouchedCommit::reserve_and_commit(DIAGNOSTIC_BYTES);
    let executed_at_ms = now_ms().max(first_healthy_at_ms);
    let receipt = json!({
        "schema_version": "ember-lab-resource-guard-diagnostic-v1",
        "result": "EXECUTED",
        "breach_class": "commit_remaining_below_survival_floor",
        "frozen_observation_sha256": frozen_observation_sha256,
        "executed_at_ms": executed_at_ms,
        "probe": {
            "resource": "host_commit",
            "kind": "allocation_probe",
            "real_allocation_executed": true,
            "requested_bytes": DIAGNOSTIC_BYTES,
            "result": "COMPLETED"
        }
    });
    let bytes = serde_json::to_vec(&receipt).unwrap();
    let digest = sha256_bytes(&bytes);
    let directory = root.join("resource-guard-diagnostic");
    fs::create_dir(&directory).unwrap();
    let path = directory.join(format!("{digest}.json"));
    write_new(&path, &bytes);
    drop(allocation);
    (path, digest, executed_at_ms)
}

fn run_main_leg(output: &Path, ledger: &mut StageLedger) -> Value {
    let root = output.join("main");
    fs::create_dir(&root).unwrap();
    let preflight = probe_host_commit_capacity().expect("real capacity preflight");
    let remaining = preflight.current_commit_remaining_bytes;
    let fixture_bytes = remaining.checked_sub(TARGET).expect("runner below target");
    let gates = json!({
        "commit_remaining_bytes": remaining,
        "physical_available_bytes": preflight.physical_available_bytes,
        "target_remaining_bytes": TARGET,
        "fixture_commit_bytes": fixture_bytes,
        "fixed_floor_bytes": FLOOR,
        "cutoff_bytes": CUTOFF,
        "hard_cap_bytes": HARD_CAP,
    });
    if remaining < COMMIT_REARM_PREFLIGHT
        || preflight.physical_available_bytes < PHYSICAL_REARM_PREFLIGHT
    {
        ledger.record(
            "main",
            "preflight",
            "INCONCLUSIVE_HOST_CANNOT_REARM_AFTER_RELEASE",
            gates.clone(),
        );
        panic!("INCONCLUSIVE_HOST_CANNOT_REARM_AFTER_RELEASE: {gates}");
    }
    if fixture_bytes < CUTOFF {
        ledger.record(
            "main",
            "preflight",
            "INCONCLUSIVE_FIXTURE_BELOW_ATTRIBUTION_CUTOFF",
            gates.clone(),
        );
        panic!("INCONCLUSIVE_FIXTURE_BELOW_ATTRIBUTION_CUTOFF: {gates}");
    }
    if fixture_bytes > HARD_CAP {
        ledger.record(
            "main",
            "preflight",
            "INCONCLUSIVE_HOST_TOO_LARGE",
            gates.clone(),
        );
        panic!("INCONCLUSIVE_HOST_TOO_LARGE: {gates}");
    }
    ledger.record("main", "preflight", "PASS", gates);

    let fixture = spawn_fixture(&root, fixture_bytes);
    let fixture_identity = json!({"pid": fixture.pid, "process_start_token": fixture.start_token, "committed_bytes": fixture_bytes});
    ledger.record("main", "fixture_ready", "PASS", fixture_identity.clone());
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).expect("open main daemon");
    ledger.record(
        "main",
        "fence",
        "STARTED",
        json!({"pid": fixture.pid, "process_start_token": fixture.start_token}),
    );
    let fenced = wait_for_foreign_state(&daemon, "fenced", Duration::from_secs(30), |status| {
        status["observation"]["host_commit_remaining_bytes"]
            .as_u64()
            .is_some_and(|bytes| (MINIMUM_RUNNER_REMAINING..FLOOR).contains(&bytes))
            && status["observation"]["named_foreign_processes"]
                .as_array()
                .is_some_and(|rows| {
                    rows.iter().any(|row| {
                        row["pid"] == fixture.pid
                            && row["process_start_token"] == fixture.start_token
                            && row["survived_end_probe"] == true
                    })
                })
    });
    ledger.record("main", "fence", "PASS", fenced.clone());

    let producer = daemon
        .foreign_process_pressure_probe_receipt(&root.join("foreign-probe-receipt"))
        .expect("mint exact foreign probe receipt");
    let producer_json: Value = serde_json::from_slice(&fs::read(&producer.path).unwrap()).unwrap();
    assert_eq!(producer_json["foreign_process_control"], false);
    assert!(producer_json["observation"]["named_foreign_processes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["pid"] == fixture.pid
            && row["process_start_token"] == fixture.start_token
            && row["survived_end_probe"] == true));
    ledger.record(
        "main",
        "producer_receipt",
        "PASS",
        json!({"path": producer.path, "sha256": producer.sha256}),
    );

    ledger.record("main", "dispatch_refusal", "STARTED", json!({}));
    let refused_manifest = write_dispatch_manifest(&root, "external-fence-refused");
    let refusal = attempt_dispatch(&daemon, &refused_manifest).unwrap_err();
    assert!(matches!(
        refusal,
        EmberLabError::ResourceAdmissionFrozen { .. }
    ));
    let refused_receipt_path = root
        .join("custody-external-fence-refused")
        .join("preflight.json");
    let refused_receipt: Value =
        serde_json::from_slice(&fs::read(&refused_receipt_path).unwrap()).unwrap();
    assert_eq!(
        refused_receipt["result"],
        "REFUSED_FOREIGN_PROCESS_PRESSURE"
    );
    assert_eq!(
        refused_receipt["foreign_process_pressure"]["state"],
        "fenced"
    );
    ledger.record("main", "dispatch_refusal", "PASS", refused_receipt.clone());

    let connection = Connection::open(&db).unwrap();
    let (freeze_at_ms, frozen_observation_json): (i64, String) = connection
        .query_row(
            "SELECT observed_at_ms,observation_json FROM resource_guard_state WHERE singleton=1 AND admission_state='frozen' AND reason='commit_remaining_below_survival_floor'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .expect("live sticky resource-guard freeze");
    let freeze_seq: i64 = connection
        .query_row(
            "SELECT seq FROM resource_guard_observations WHERE observed_at_ms=?1 AND outcome='frozen' AND payload_json=?2 ORDER BY seq DESC LIMIT 1",
            rusqlite::params![freeze_at_ms, &frozen_observation_json],
            |row| row.get(0),
        )
        .expect("exact freeze-causing resource-guard ledger row");
    drop(connection);
    let frozen_sha256 = sha256_bytes(frozen_observation_json.as_bytes());

    release_fixture(fixture, ledger, "main");
    ledger.record("main", "foreign_clear", "STARTED", json!({}));
    let clear = wait_for_foreign_state(&daemon, "clear", Duration::from_secs(30), |_| true);
    ledger.record("main", "foreign_clear", "PASS", clear);

    ledger.record(
        "main",
        "healthy_window",
        "STARTED",
        json!({"deadline_ms": 90_000, "required_sample_count": 30, "required_span_ms": 60_000}),
    );
    let first_healthy_at_ms =
        wait_for_first_healthy_after(&db, freeze_seq, Duration::from_secs(15));
    ledger.record(
        "main",
        "bound_allocation_diagnostic",
        "STARTED",
        json!({"purpose": "production resource-guard rearm evidence"}),
    );
    let (diagnostic_path, diagnostic_sha256, diagnostic_at_ms) =
        write_commit_diagnostic(&root, &frozen_sha256, first_healthy_at_ms);
    ledger.record(
        "main",
        "bound_allocation_diagnostic",
        "PASS",
        json!({
            "purpose": "satisfy the production rearm contract with content-addressed evidence that a real host_commit allocation executed inside the healthy window",
            "path": diagnostic_path,
            "sha256": diagnostic_sha256,
            "executed_at_ms": diagnostic_at_ms,
            "requested_bytes": DIAGNOSTIC_BYTES,
        }),
    );

    let healthy_deadline = Instant::now() + Duration::from_secs(90);
    let healthy = loop {
        let tail = healthy_tail(&db, freeze_seq);
        if tail.len() >= 30 && tail.last().unwrap() - tail.first().unwrap() >= 60_000 {
            break tail;
        }
        assert!(
            Instant::now() < healthy_deadline,
            "healthy window deadline expired: samples={}",
            tail.len()
        );
        thread::sleep(Duration::from_millis(250));
    };
    ledger.record(
        "main",
        "healthy_window",
        "PASS",
        json!({"sample_count": healthy.len(), "first_observed_at_ms": healthy.first(), "newest_observed_at_ms": healthy.last(), "span_ms": healthy.last().unwrap() - healthy.first().unwrap()}),
    );

    ledger.record(
        "main",
        "resource_guard_rearm",
        "STARTED",
        json!({"frozen_observation_sha256": frozen_sha256}),
    );
    let rearm = daemon
        .rearm_resource_guard(ResourceGuardRearmRequest {
            frozen_observation_sha256: frozen_sha256,
            breach_class: "commit_remaining_below_survival_floor".into(),
            diagnostic_receipt_path: diagnostic_path,
            diagnostic_receipt_sha256: diagnostic_sha256,
        })
        .expect("governed resource-guard rearm");
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "open"
    );
    ledger.record(
        "main",
        "resource_guard_rearm",
        "PASS",
        json!({"path": rearm.path, "sha256": rearm.sha256}),
    );

    ledger.record("main", "dispatch_admitted", "STARTED", json!({}));
    let admitted_manifest = write_dispatch_manifest(&root, "external-fence-admitted");
    let admitted =
        attempt_dispatch(&daemon, &admitted_manifest).expect("post-rearm real dispatch admitted");
    ledger.record("main", "dispatch_admitted", "PASS", json!({"pid": admitted.handle.pid, "receipt_path": admitted.receipt.path, "receipt_sha256": admitted.receipt.sha256}));
    daemon
        .stop_job("external-fence-admitted")
        .expect("receipt-first owned stop");
    ledger.record("main", "owned_cleanup", "PASS", json!({"job_id": "external-fence-admitted", "state": daemon.job_state("external-fence-admitted").unwrap()}));
    drop(daemon);
    json!({"producer_receipt": producer.path, "producer_sha256": producer.sha256, "fixture": fixture_identity})
}

fn run_control_leg(output: &Path, ledger: &mut StageLedger) {
    let root = output.join("no-fixture-control");
    fs::create_dir(&root).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).expect("open control daemon");
    ledger.record("no_fixture_control", "foreign_clear", "STARTED", json!({}));
    let clear = wait_for_foreign_state(&daemon, "clear", Duration::from_secs(15), |status| {
        status["observation"]["named_foreign_processes"]
            .as_array()
            .is_some_and(Vec::is_empty)
    });
    ledger.record("no_fixture_control", "foreign_clear", "PASS", clear);
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "open"
    );
    ledger.record(
        "no_fixture_control",
        "dispatch_admitted",
        "STARTED",
        json!({}),
    );
    let manifest = write_dispatch_manifest(&root, "no-fixture-admitted");
    let admitted =
        attempt_dispatch(&daemon, &manifest).expect("no-fixture control dispatch admitted");
    ledger.record(
        "no_fixture_control",
        "dispatch_admitted",
        "PASS",
        json!({"pid": admitted.handle.pid, "receipt_sha256": admitted.receipt.sha256}),
    );
    daemon
        .stop_job("no-fixture-admitted")
        .expect("receipt-first control cleanup");
    ledger.record(
        "no_fixture_control",
        "owned_cleanup",
        "PASS",
        json!({"state": daemon.job_state("no-fixture-admitted").unwrap()}),
    );
}

fn run_survival_red(output: &Path, ledger: &mut StageLedger) {
    let root = output.join("survival-red");
    fs::create_dir(&root).unwrap();
    let preflight = probe_host_commit_capacity().unwrap();
    let fixture_bytes = preflight
        .current_commit_remaining_bytes
        .checked_sub(TARGET)
        .unwrap();
    assert!((CUTOFF..=HARD_CAP).contains(&fixture_bytes));
    let fixture = spawn_fixture(&root, fixture_bytes);
    let pid = fixture.pid;
    let token = fixture.start_token.clone();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).expect("open survival-red daemon");
    arm_named_end_probe_pause_for_test(pid, token.clone());
    ledger.record(
        "survival_red",
        "actual_before_end_probe_pause",
        "STARTED",
        json!({"pid": pid, "process_start_token": token}),
    );
    assert!(
        wait_for_named_end_probe_pause_for_test(Duration::from_secs(15)),
        "census never actually paused at the named identity end probe"
    );
    ledger.record(
        "survival_red",
        "actual_before_end_probe_pause",
        "PASS",
        json!({"pid": pid, "process_start_token": token}),
    );
    kill_fixture(fixture, ledger);
    release_named_end_probe_pause_for_test();
    ledger.record(
        "survival_red",
        "dead_identity_rejected",
        "STARTED",
        json!({"pid": pid, "process_start_token": token}),
    );
    let exit_observation = wait_for_named_exit_observation(
        &root.join("ember-lab.sqlite3"),
        pid,
        Duration::from_secs(15),
    );
    ledger.record(
        "survival_red",
        "dead_identity_rejected",
        "PASS",
        exit_observation,
    );
    ledger.record("survival_red", "foreign_clear", "STARTED", json!({}));
    let clear = wait_for_foreign_state(&daemon, "clear", Duration::from_secs(15), |_| true);
    ledger.record("survival_red", "foreign_clear", "PASS", clear);
}

#[test]
#[ignore = "governed dispatch-only issue898 external pressure probe"]
fn issue898_external_fence_live_probe() {
    let output = PathBuf::from(
        std::env::var_os("EMBER_ISSUE898_EXTERNAL_OUTPUT")
            .expect("EMBER_ISSUE898_EXTERNAL_OUTPUT is required"),
    );
    fs::create_dir(&output).expect("output root must not already exist");
    let mut ledger = StageLedger::create(&output.join("stages.jsonl"));
    ledger.record("probe", "start", "PASS", json!({"github_sha": std::env::var("GITHUB_SHA").ok(), "github_run_id": std::env::var("GITHUB_RUN_ID").ok(), "gpu_external_class": "NOT_PROVEN_HOSTED_RUNNER_HAS_NO_GPU"}));
    let main = run_main_leg(&output, &mut ledger);
    run_control_leg(&output, &mut ledger);
    run_survival_red(&output, &mut ledger);
    let summary = json!({
        "schema_version": "ember-issue898-external-fence-probe-v1",
        "verdict": "PASS",
        "main": main,
        "required_legs": {"main": "PASS", "no_fixture_control": "PASS", "survival_red": "PASS"},
        "foreign_process_control": false,
        "gpu_external_class": "NOT_PROVEN_HOSTED_RUNNER_HAS_NO_GPU",
    });
    let without_self_hash = serde_json::to_vec(&summary).unwrap();
    let self_hash = sha256_bytes(&without_self_hash);
    let mut sealed = summary;
    sealed["receipt_sha256"] = Value::String(self_hash.clone());
    write_new(
        &output.join(format!("{self_hash}.json")),
        &serde_json::to_vec_pretty(&sealed).unwrap(),
    );
    ledger.record(
        "probe",
        "complete",
        "PASS",
        json!({"receipt_sha256": self_hash}),
    );
}
