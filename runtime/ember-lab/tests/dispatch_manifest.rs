// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

#![cfg(windows)]

use ember_lab::{Daemon, EmberLabError, HostCommitCapacity, JobState, ResourceGuardRearmRequest};
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
const SIMULATED_PEAK_COMMIT_BYTES: u64 = GIB;
const CPU_RATE_PERCENT: u32 = 25;

fn host_capacity(available_maximum_commit_bytes: u64) -> HostCommitCapacity {
    HostCommitCapacity {
        basis: "maximum_configured_capacity".to_string(),
        sampled_at_ms: 10_000,
        snapshot_sha256: "c".repeat(64),
        physical_ram_bytes: 64 * GIB,
        physical_available_bytes: 32 * GIB,
        pagefile_maximum_bytes: 32 * GIB,
        pagefile_configuration_source:
            r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles"
                .to_string(),
        pagefile_configuration_sha256: "a".repeat(64),
        commit_total_bytes: 96 * GIB - available_maximum_commit_bytes,
        current_commit_limit_bytes: 80 * GIB,
        current_commit_remaining_bytes: 16 * GIB,
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
        "ember-lab-dispatch-{name}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn remove_sandbox_when_unlocked(path: &Path) {
    for _ in 0..50 {
        match fs::remove_dir_all(path) {
            Ok(()) => break,
            Err(error) if error.raw_os_error() == Some(32) => {
                thread::sleep(Duration::from_millis(20));
            }
            Err(error) => panic!("failed to remove dispatch sandbox: {error}"),
        }
    }
    assert!(!path.exists(), "dispatch sandbox remained locked");
}

fn sha256(path: &Path) -> String {
    format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
}

#[test]
fn fixture_dispatch_child() {
    if std::env::var("EMBER_LAB_DISPATCH_FIXTURE_CHILD").as_deref() == Ok("1") {
        if let Ok(path) = std::env::var("EMBER_LAB_DISPATCH_TOKEN_CAPTURE") {
            let job_id = std::env::var("EMBER_LAB_DISPATCH_JOB_ID").unwrap();
            let token = std::env::var("EMBER_LAB_DISPATCH_TOKEN").unwrap();
            fs::write(path, format!("{job_id}\n{token}\n")).unwrap();
        }
        if let Ok(raw) = std::env::var("EMBER_LAB_DISPATCH_ALLOCATE_BYTES") {
            let bytes: usize = raw.parse().unwrap();
            let mut allocation = vec![0u8; bytes];
            for offset in (0..allocation.len()).step_by(4096) {
                allocation[offset] = 1;
            }
            std::hint::black_box(allocation);
        }
        if std::env::var("EMBER_LAB_DISPATCH_CPU_BURN").as_deref() == Ok("1") {
            let workers = std::thread::available_parallelism().unwrap().get();
            for seed in 0..workers {
                thread::spawn(move || {
                    let until = std::time::Instant::now() + Duration::from_secs(10);
                    let mut value = seed as u64;
                    while std::time::Instant::now() < until {
                        value = value.wrapping_mul(6364136223846793005).wrapping_add(1);
                        std::hint::black_box(value);
                    }
                });
            }
        }
        let sleep_ms = std::env::var("EMBER_LAB_DISPATCH_FIXTURE_SLEEP_MS")
            .ok()
            .and_then(|raw| raw.parse::<u64>().ok())
            .unwrap_or(30_000);
        thread::sleep(Duration::from_millis(sleep_ms));
    }
}

/// Window-contract fixture (issue #898 L6): when
/// `EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW=1`, paints a real, visible
/// top-level `CreateWindowExW` window on the current desktop. This is the
/// exact gap PR #1691 left open (its own "Unverified areas" section: the
/// UILIMIT job-object wall "does not, by themselves, prevent the job's own
/// process from creating a window on the existing interactive desktop") --
/// a plain `CREATE_NO_WINDOW`/`JOB_OBJECT_UILIMIT_*`-restricted child can
/// still call a real user32 window API and have it render. The fallback
/// sleep keeps the fixture from exiting cleanly on its own if the parent's
/// census/kill is ever slower than expected, so a probe miss shows up as a
/// hang the test's own deadline catches, not a silent false negative.
///
/// `EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW_WARMUP=1` (issue #1727 round 2):
/// paired with the window var, creates the same window, destroys it
/// immediately, and returns instead of sleeping. A prior fix warmed only the
/// process (loader/CRT/harness init) by spawning this fixture with the
/// window var unset; that still failed cold, because the dominant first-use
/// cost is the window-creation path itself (win32k session init, desktop-
/// heap connection, class registration), which only pays down when a window
/// is actually created -- and that cost is session-side, not process-side,
/// so a real create+destroy in a throwaway process still warms it for the
/// timed dispatch that follows.
fn to_wide_null(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

#[test]
fn fixture_dispatch_child_presents_a_visible_window() {
    if std::env::var("EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW").as_deref() == Ok("1") {
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            CreateWindowExW, DestroyWindow, WS_POPUP, WS_VISIBLE,
        };
        // A top-level visible window on the predefined STATIC class -- the exact
        // thing census_top_level_windows() enumerates (EnumWindows +
        // IsWindowVisible + owning PID), and a fair stand-in for any GUI a
        // headless_no_windows job might wrongly present.
        //
        // Deliberately NOT MessageBoxW. A modal dialog has to load a dialog
        // template, theme, and font and enter a modal loop before it is ever
        // visible, which under the parallel suite regularly overran the 200ms
        // admission census and made this test flaky (see the PR's cold-start
        // note). It also blocked on input, so killed-late children held a lock
        // on their own .exe and broke the next relink with LNK1104. One
        // CreateWindowExW call is visible essentially immediately and needs no
        // message pump to be enumerable, so the test now exercises the census
        // rather than the host's dialog-subsystem latency.
        let class = to_wide_null("STATIC");
        let title = to_wide_null("l6-window-contract-fixture");
        let hwnd = unsafe {
            CreateWindowExW(
                0,
                class.as_ptr(),
                title.as_ptr(),
                WS_POPUP | WS_VISIBLE,
                0,
                0,
                320,
                120,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null(),
            )
        };
        if std::env::var("EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW_WARMUP").as_deref() == Ok("1") {
            unsafe {
                DestroyWindow(hwnd);
            }
            return;
        }
        thread::sleep(Duration::from_secs(30));
    }
}

fn write_manifest(root: &Path, job_id: &str, not_before_ms: i64) -> PathBuf {
    let custody = root.join("custody");
    fs::create_dir_all(&custody).unwrap();
    let mut env = BTreeMap::new();
    env.insert("EMBER_LAB_DISPATCH_FIXTURE_CHILD", "1".to_string());
    env.insert(
        "EMBER_LAB_DISPATCH_TOKEN_CAPTURE",
        custody
            .join("dispatch-token.txt")
            .to_string_lossy()
            .into_owned(),
    );
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
        "schema_version": "ember-lab-dispatch-manifest-v3",
            "job_id": job_id,
            "source_commit": "5326043c344227c1b145a4ddbb3519cfa62d4943",
            "not_before_ms": not_before_ms,
            "expires_at_ms": not_before_ms + 60_000,
            "resource_lease": "gpu-smoke",
        "program": {"path": program, "sha256": sha256(&program)},
            "args": ["--exact", "fixture_dispatch_child", "--nocapture"],
            "workload_profile": {
                "profile_id": "evidence_verifier",
                "pinned_host_producers": [{
                    "kind": "receipt_verifier",
                    "maximum_bytes": SIMULATED_PEAK_COMMIT_BYTES
                }],
                "requires_ui_responsiveness": false,
                "cpu_rate_percent": CPU_RATE_PERCENT
            },
            "cpu_pacing_class": "unpaced",
            "window_contract": "headless_no_windows",
            "env": env,
        "bindings": [
            {"kind": "config", "path": binding, "sha256": sha256(&binding)},
            {"kind": "manifest", "path": data_manifest, "sha256": sha256(&data_manifest)}
        ],
            "custody_root": custody,
            "storage_reserves": [{"root": root, "minimum_free_bytes": 1}],
        "minimum_free_vram_bytes": 0,
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
fn evidence_verifier_dispatch_token_is_bound_to_owned_child_and_consumed_once() {
    let root = sandbox("dispatch-token");
    let dispatch_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let manifest = write_manifest(&root, "dispatch-token-job", dispatch_at);
    let capture = root.join("custody").join("dispatch-token.txt");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    for _ in 0..100 {
        if capture.is_file() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    let captured = fs::read_to_string(&capture).unwrap();
    let mut lines = captured.lines();
    let job_id = lines.next().unwrap();
    let token = lines.next().unwrap();
    assert_eq!(job_id, "dispatch-token-job");
    assert_eq!(token.len(), 64);

    let wrong_pid = daemon
        .consume_dispatch_token(job_id, token, outcome.handle.pid.saturating_add(1))
        .unwrap_err();
    assert!(matches!(
        wrong_pid,
        EmberLabError::DispatchTokenRefused { .. }
    ));
    let forged = daemon
        .consume_dispatch_token(job_id, &"0".repeat(64), outcome.handle.pid)
        .unwrap_err();
    assert!(matches!(forged, EmberLabError::DispatchTokenRefused { .. }));
    let original_identity: (String, String) =
        rusqlite::Connection::open(root.join("ember-lab.sqlite3"))
            .unwrap()
            .query_row(
                "SELECT process_start_token,executable_identity FROM jobs WHERE job_id=?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
    rusqlite::Connection::open(root.join("ember-lab.sqlite3"))
        .unwrap()
        .execute(
            "UPDATE jobs SET process_start_token='foreign-start', executable_identity='foreign-exe' WHERE job_id=?1",
            [job_id],
        )
        .unwrap();
    let identity_mismatch = daemon
        .consume_dispatch_token(job_id, token, outcome.handle.pid)
        .unwrap_err();
    assert!(matches!(
        identity_mismatch,
        EmberLabError::DispatchTokenRefused { .. }
    ));
    rusqlite::Connection::open(root.join("ember-lab.sqlite3"))
        .unwrap()
        .execute(
            "UPDATE jobs SET process_start_token=?2, executable_identity=?3 WHERE job_id=?1",
            rusqlite::params![job_id, original_identity.0, original_identity.1],
        )
        .unwrap();
    daemon
        .consume_dispatch_token(job_id, token, outcome.handle.pid)
        .unwrap();
    let replay = daemon
        .consume_dispatch_token(job_id, token, outcome.handle.pid)
        .unwrap_err();
    assert!(matches!(replay, EmberLabError::DispatchTokenRefused { .. }));

    daemon.stop_job(job_id).unwrap();
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn dispatch_token_refuses_persisted_stale_start_before_consumption_or_event() {
    let root = sandbox("dispatch-token-stale-start");
    let dispatch_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let manifest = write_manifest(&root, "dispatch-token-stale-start-job", dispatch_at);
    let capture = root.join("custody").join("dispatch-token.txt");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    for _ in 0..100 {
        if capture.is_file() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    let captured = fs::read_to_string(&capture).unwrap();
    let mut lines = captured.lines().map(str::to_owned);
    let job_id = lines.next().unwrap();
    let token = lines.next().unwrap();
    let connection = Connection::open(root.join("ember-lab.sqlite3")).unwrap();
    let original: String = connection
        .query_row(
            "SELECT process_start_token FROM jobs WHERE job_id=?1",
            [&job_id],
            |row| row.get(0),
        )
        .unwrap();
    connection
        .execute(
            "UPDATE jobs SET process_start_token='stale-start-token' WHERE job_id=?1",
            [&job_id],
        )
        .unwrap();
    let refused = daemon.consume_dispatch_token(&job_id, &token, outcome.handle.pid);
    assert!(matches!(
        refused,
        Err(EmberLabError::DispatchTokenRefused { .. })
    ));
    assert_eq!(
        connection
            .query_row(
                "SELECT consumed_at_ms FROM dispatch_tokens WHERE job_id=?1",
                [&job_id],
                |row| row.get::<_, Option<i64>>(0),
            )
            .unwrap(),
        None
    );
    assert_eq!(
        connection
            .query_row(
                "SELECT COUNT(*) FROM events WHERE job_id=?1 AND kind='dispatch_token_consumed'",
                [&job_id],
                |row| row.get::<_, i64>(0),
            )
            .unwrap(),
        0
    );
    connection
        .execute(
            "UPDATE jobs SET process_start_token=?2 WHERE job_id=?1",
            rusqlite::params![&job_id, original],
        )
        .unwrap();
    drop(connection);
    daemon.stop_job(&job_id).unwrap();
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn dispatch_token_refuses_foreign_executable_before_consumption_or_event() {
    let root = sandbox("dispatch-token-foreign-executable");
    let dispatch_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let manifest = write_manifest(&root, "dispatch-token-foreign-executable-job", dispatch_at);
    let capture = root.join("custody").join("dispatch-token.txt");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    for _ in 0..100 {
        if capture.is_file() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    let captured = fs::read_to_string(&capture).unwrap();
    let mut lines = captured.lines().map(str::to_owned);
    let job_id = lines.next().unwrap();
    let token = lines.next().unwrap();
    let connection = Connection::open(root.join("ember-lab.sqlite3")).unwrap();
    let original: String = connection
        .query_row(
            "SELECT executable_identity FROM jobs WHERE job_id=?1",
            [&job_id],
            |row| row.get(0),
        )
        .unwrap();
    connection
        .execute(
            "UPDATE jobs SET executable_identity='foreign-executable' WHERE job_id=?1",
            [&job_id],
        )
        .unwrap();
    let refused = daemon.consume_dispatch_token(&job_id, &token, outcome.handle.pid);
    assert!(matches!(
        refused,
        Err(EmberLabError::DispatchTokenRefused { .. })
    ));
    assert_eq!(
        connection
            .query_row(
                "SELECT consumed_at_ms FROM dispatch_tokens WHERE job_id=?1",
                [&job_id],
                |row| row.get::<_, Option<i64>>(0),
            )
            .unwrap(),
        None
    );
    assert_eq!(
        connection
            .query_row(
                "SELECT COUNT(*) FROM events WHERE job_id=?1 AND kind='dispatch_token_consumed'",
                [&job_id],
                |row| row.get::<_, i64>(0),
            )
            .unwrap(),
        0
    );
    connection
        .execute(
            "UPDATE jobs SET executable_identity=?2 WHERE job_id=?1",
            rusqlite::params![&job_id, original],
        )
        .unwrap();
    drop(connection);
    daemon.stop_job(&job_id).unwrap();
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn dispatch_token_refuses_identity_update_race_before_consumption_or_event() {
    let root = sandbox("dispatch-token-identity-race");
    let dispatch_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let manifest = write_manifest(&root, "dispatch-token-identity-race-job", dispatch_at);
    let capture = root.join("custody").join("dispatch-token.txt");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    for _ in 0..100 {
        if capture.is_file() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    let captured = fs::read_to_string(&capture).unwrap();
    let mut lines = captured.lines().map(str::to_owned);
    let job_id = lines.next().unwrap();
    let token = lines.next().unwrap();
    let connection = Connection::open(root.join("ember-lab.sqlite3")).unwrap();
    connection
        .execute_batch(
            "CREATE TRIGGER mutate_dispatch_identity BEFORE UPDATE OF consumed_at_ms ON dispatch_tokens
             BEGIN UPDATE jobs SET process_start_token='raced-start-token' WHERE job_id=NEW.job_id; END;",
        )
        .unwrap();

    let refused = daemon.consume_dispatch_token(&job_id, &token, outcome.handle.pid);
    assert!(matches!(
        refused,
        Err(EmberLabError::DispatchTokenRefused { .. })
    ));
    assert_eq!(
        connection
            .query_row(
                "SELECT consumed_at_ms FROM dispatch_tokens WHERE job_id=?1",
                [&job_id],
                |row| row.get::<_, Option<i64>>(0),
            )
            .unwrap(),
        None
    );
    assert_eq!(
        connection
            .query_row(
                "SELECT COUNT(*) FROM events WHERE job_id=?1 AND kind='dispatch_token_consumed'",
                [&job_id],
                |row| row.get::<_, i64>(0),
            )
            .unwrap(),
        0
    );
    drop(connection);
    daemon.stop_job(&job_id).unwrap();
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn evidence_verifier_dispatch_is_cpu_only_and_rejects_caller_token_authority() {
    let root = sandbox("dispatch-token-cpu-only");
    let dispatch_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let manifest = write_manifest(&root, "dispatch-token-cpu-only-job", dispatch_at);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["minimum_free_vram_bytes"] = json!(0);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let _outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || panic!("evidence verification must not probe GPU state"),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    daemon.stop_job("dispatch-token-cpu-only-job").unwrap();

    let caller_root = sandbox("dispatch-token-caller-authority");
    let caller_manifest = write_manifest(&caller_root, "dispatch-token-caller-job", dispatch_at);
    let mut caller: Value = serde_json::from_slice(&fs::read(&caller_manifest).unwrap()).unwrap();
    caller["env"]["EMBER_LAB_DISPATCH_TOKEN"] = json!("0".repeat(64));
    fs::write(&caller_manifest, serde_json::to_vec(&caller).unwrap()).unwrap();
    let caller_daemon = Daemon::open(&caller_root.join("ember-lab.sqlite3")).unwrap();
    let error = caller_daemon
        .dispatch_manifest_at_with_probes_and_host(
            &caller_manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || panic!("caller token must refuse before probes"),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap_err();
    assert!(matches!(
        error,
        EmberLabError::InvalidDispatchManifest { .. }
    ));
    assert_eq!(
        caller_daemon
            .job_state("dispatch-token-caller-job")
            .unwrap(),
        None
    );
    drop(caller_daemon);
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
    remove_sandbox_when_unlocked(&caller_root);
}

#[test]
fn dispatch_refuses_manifest_missing_window_contract_with_named_refusal() {
    // Proves the refusal-message-quality requirement through the real
    // dispatch path (Daemon::dispatch_manifest_at_with_probes_and_host):
    // a manifest missing a required closed-choice field must fail closed
    // with a message naming the field and its legal values, not a bare
    // serde parse error.
    let root = sandbox("dispatch-refusal-window-contract");
    let dispatch_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let manifest = write_manifest(&root, "dispatch-refusal-window-contract-job", dispatch_at);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload.as_object_mut().unwrap().remove("window_contract");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            dispatch_at + 1,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap_err();
    let EmberLabError::InvalidDispatchManifest { detail } = error else {
        panic!("expected InvalidDispatchManifest, got {error:?}");
    };
    assert!(
        detail.contains(
            "window_contract: missing required field (legal values: headless_no_windows, cockpit_hosted)"
        ),
        "refusal did not name the missing field and its legal values: {detail}"
    );
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn dispatch_manifest_hashes_preflights_and_governs_spawn() {
    let root = sandbox("green");
    let manifest = write_manifest(&root, "dispatch-green", 10_000);
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let host_probe_calls = std::cell::Cell::new(0_u32);
    let outcome = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || {
                let call = host_probe_calls.get() + 1;
                host_probe_calls.set(call);
                let mut capacity = host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES);
                capacity.sampled_at_ms = 10_000 + i64::from(call);
                capacity.snapshot_sha256 = format!("{call:064x}");
                Ok(capacity)
            },
        )
        .unwrap();
    assert_eq!(
        host_probe_calls.get(),
        2,
        "host commit must be re-read near spawn"
    );
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
    assert_eq!(receipt["schema_version"], "ember-lab-dispatch-preflight-v1");
    assert_eq!(receipt["result"], "PREFLIGHT_PASSED");
    assert_eq!(
        receipt["source_commit"],
        "5326043c344227c1b145a4ddbb3519cfa62d4943"
    );
    assert_eq!(receipt["dispatch_manifest_sha256"], sha256(&manifest));
    assert_eq!(
        receipt["workload_profile"]["profile_id"],
        "evidence_verifier"
    );
    assert_eq!(
        receipt["workload_profile"]["pinned_host_producers"][0]["kind"],
        "receipt_verifier"
    );
    assert_eq!(
        receipt["workload_profile"]["pinned_host_producers"][0]["maximum_bytes"],
        SIMULATED_PEAK_COMMIT_BYTES
    );
    assert_eq!(
        receipt["workload_profile"]["cpu_rate_percent"],
        CPU_RATE_PERCENT
    );
    assert_eq!(receipt["vram_reserve"]["minimum_free_bytes"], 0);
    assert_eq!(receipt["vram_reserve"]["available_free_bytes"], 0);
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
    assert_eq!(receipt["host_commit"]["sampled_at_ms"], 10_002);
    assert_eq!(
        receipt["host_commit"]["snapshot_sha256"],
        format!("{:064x}", 2)
    );
    assert!(
        receipt["host_commit"]["spawn_authorized_at_ms"]
            .as_i64()
            .unwrap()
            > 0
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
fn dispatch_manifest_requires_a_bounded_cpu_rate_before_identity_or_spawn() {
    for (name, rate) in [("missing", None), ("zero", Some(0)), ("over", Some(101))] {
        let root = sandbox(&format!("cpu-rate-{name}"));
        let job_id = format!("dispatch-cpu-rate-{name}");
        let manifest = write_manifest(&root, &job_id, 10_000);
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        match rate {
            Some(rate) => payload["workload_profile"]["cpu_rate_percent"] = json!(rate),
            None => {
                payload["workload_profile"]
                    .as_object_mut()
                    .unwrap()
                    .remove("cpu_rate_percent");
            }
        }
        fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
        assert!(matches!(
            daemon.dispatch_manifest_at_with_probes_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(2048),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            ),
            Err(EmberLabError::InvalidDispatchManifest { .. })
        ));
        assert_eq!(daemon.identity_hash(&job_id).unwrap(), None);
        assert_eq!(daemon.job_state(&job_id).unwrap(), None);
        assert!(!root.join("custody").join("preflight.json").exists());
    }
}

fn write_manifest_with_pacing_class(
    root: &Path,
    job_id: &str,
    not_before_ms: i64,
    pacing_class: &str,
) -> PathBuf {
    let manifest = write_manifest(root, job_id, not_before_ms);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["cpu_pacing_class"] = json!(pacing_class);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    manifest
}

/// Dispatches one fixture job under `pacing_class` and asserts the host's
/// blanket CPU hard cap is present on the job object *whatever* that class is
/// -- the cap is defense-in-depth and never comes off. Returns the live daemon,
/// sandbox root, and `job_prepared` payload so the caller can assert the
/// class-specific half of the receipt.
fn dispatch_under_pacing_class(
    sandbox_label: &str,
    job_id: &str,
    pacing_class: &str,
) -> (Daemon, PathBuf, Value) {
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        JobObjectCpuRateControlInformation, OpenJobObjectW, QueryInformationJobObject,
        JOBOBJECT_CPU_RATE_CONTROL_INFORMATION, JOB_OBJECT_CPU_RATE_CONTROL_ENABLE,
        JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    };

    let root = sandbox(sandbox_label);
    let manifest = write_manifest_with_pacing_class(&root, job_id, 10_000, pacing_class);
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    let connection = Connection::open(&db).unwrap();
    let job_object_name: String = connection
        .query_row(
            "SELECT job_object_name FROM jobs WHERE job_id=?1",
            [job_id],
            |row| row.get(0),
        )
        .unwrap();
    let wide: Vec<u16> = std::ffi::OsStr::new(&job_object_name)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let job = unsafe { OpenJobObjectW(0x0004, 0, wide.as_ptr()) };
    assert!(!job.is_null());
    let mut info: JOBOBJECT_CPU_RATE_CONTROL_INFORMATION = unsafe { zeroed() };
    let ok = unsafe {
        QueryInformationJobObject(
            job,
            JobObjectCpuRateControlInformation,
            (&mut info as *mut JOBOBJECT_CPU_RATE_CONTROL_INFORMATION).cast(),
            size_of::<JOBOBJECT_CPU_RATE_CONTROL_INFORMATION>() as u32,
            std::ptr::null_mut(),
        )
    };
    unsafe { CloseHandle(job) };
    assert_ne!(ok, 0);
    assert_eq!(
        info.ControlFlags,
        JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
        "{pacing_class} spawn lost the host CPU hard-cap flags"
    );
    assert_eq!(
        unsafe { info.Anonymous.CpuRate },
        CPU_RATE_PERCENT * 100,
        "{pacing_class} spawn lost the host CPU hard-cap rate"
    );
    let prepared_payload: String = connection
        .query_row(
            "SELECT payload_json FROM events WHERE job_id=?1 AND kind='job_prepared'",
            [job_id],
            |row| row.get(0),
        )
        .unwrap();
    let prepared: Value = serde_json::from_str(&prepared_payload).unwrap();
    (daemon, root, prepared)
}

fn assert_terminal_receipt_carries_prepared(
    daemon: &Daemon,
    root: &Path,
    job_id: &str,
    prepared: &Value,
) {
    daemon.stop_job(job_id).unwrap();
    let artifact = daemon
        .export_content_addressed_receipt(job_id, &root.join("terminal-receipts"))
        .unwrap();
    let terminal: Value = serde_json::from_slice(&fs::read(artifact.path).unwrap()).unwrap();
    let terminal_prepared = terminal["events"]
        .as_array()
        .unwrap()
        .iter()
        .find(|event| event["kind"] == "job_prepared")
        .unwrap();
    assert_eq!(terminal_prepared["payload"], *prepared);
}

#[test]
fn dispatch_manifest_applies_the_declared_windows_cpu_hard_cap() {
    // `unpaced` declares no pacing contract, so it earns no verification
    // receipt -- but the host still caps it, which the shared helper asserts
    // directly off the job object.
    let (daemon, root, prepared) =
        dispatch_under_pacing_class("cpu-hard-cap", "dispatch-cpu-hard-cap", "unpaced");
    assert_eq!(prepared["cpu_pacing_class"], "unpaced");
    assert_eq!(prepared["cpu_rate_control_verified"], false);
    assert_eq!(prepared["applied_cpu_rate"], Value::Null);
    assert_terminal_receipt_carries_prepared(&daemon, &root, "dispatch-cpu-hard-cap", &prepared);
}

#[test]
fn governed_dispatch_earns_the_reopened_cpu_rate_verification_receipt() {
    let (daemon, root, prepared) =
        dispatch_under_pacing_class("cpu-hard-cap-governed", "dispatch-cpu-governed", "governed");
    assert_eq!(prepared["cpu_pacing_class"], "governed");
    assert_eq!(prepared["cpu_rate_control_verified"], true);
    assert_eq!(prepared["applied_cpu_rate"], CPU_RATE_PERCENT * 100);
    assert_terminal_receipt_carries_prepared(&daemon, &root, "dispatch-cpu-governed", &prepared);
}

#[test]
fn governed_pacing_is_refused_at_a_cpu_rate_that_paces_nothing() {
    let root = sandbox("governed-full-rate");
    let manifest =
        write_manifest_with_pacing_class(&root, "dispatch-governed-100", 10_000, "governed");
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["workload_profile"]["cpu_rate_percent"] = json!(100);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-governed-100").unwrap(), None);
}

/// Runs a real sustained all-core burn inside a dispatched job and asserts the
/// job object actually throttled it. This is #898's CPU acceptance probe, and
/// it runs for BOTH pacing classes: the host cap is what does the throttling,
/// and a `Governed` declaration must not be what a job depends on to be capped.
fn assert_cpu_burn_stays_inside_hard_cap(sandbox_label: &str, job_id: &str, pacing_class: &str) {
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        JobObjectBasicAccountingInformation, OpenJobObjectW, QueryInformationJobObject,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    };

    let root = sandbox(sandbox_label);
    let manifest = write_manifest_with_pacing_class(&root, job_id, 10_000, pacing_class);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["env"]["EMBER_LAB_DISPATCH_CPU_BURN"] = json!("1");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    let started = std::time::Instant::now();
    daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    thread::sleep(Duration::from_millis(1_500));
    let connection = Connection::open(&db).unwrap();
    let job_object_name: String = connection
        .query_row(
            "SELECT job_object_name FROM jobs WHERE job_id=?1",
            [job_id],
            |row| row.get(0),
        )
        .unwrap();
    let wide: Vec<u16> = std::ffi::OsStr::new(&job_object_name)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let job = unsafe { OpenJobObjectW(0x0004, 0, wide.as_ptr()) };
    assert!(!job.is_null());
    let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { zeroed() };
    let ok = unsafe {
        QueryInformationJobObject(
            job,
            JobObjectBasicAccountingInformation,
            (&mut accounting as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
            size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
            std::ptr::null_mut(),
        )
    };
    unsafe { CloseHandle(job) };
    assert_ne!(ok, 0);
    let cpu_ms = (accounting.TotalUserTime + accounting.TotalKernelTime) / 10_000;
    let elapsed_ms = started.elapsed().as_millis() as i64;
    let logical_cpus = std::thread::available_parallelism().unwrap().get() as i64;
    let expected_cap_ms = elapsed_ms * logical_cpus * CPU_RATE_PERCENT as i64 / 100;
    assert!(
        cpu_ms >= 100,
        "{pacing_class} probe did not create sustained CPU load: {cpu_ms}ms"
    );
    assert!(
        cpu_ms <= expected_cap_ms * 3 / 2 + 100,
        "{pacing_class}: 25% hard cap exceeded bounded tolerance: cpu={cpu_ms}ms cap={expected_cap_ms}ms"
    );
    daemon.stop_job(job_id).unwrap();
}

#[test]
fn dispatched_cpu_burn_stays_inside_the_reopened_hard_cap() {
    assert_cpu_burn_stays_inside_hard_cap(
        "cpu-burn-governed",
        "dispatch-cpu-burn-governed",
        "governed",
    );
}

#[test]
fn unpaced_dispatched_cpu_burn_still_stays_inside_the_host_hard_cap() {
    assert_cpu_burn_stays_inside_hard_cap("cpu-burn-boundary", "dispatch-cpu-burn", "unpaced");
}

#[test]
fn dispatch_manifest_walls_the_declared_windows_ui_surface_for_non_cockpit_profiles() {
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        JobObjectBasicUIRestrictions, OpenJobObjectW, QueryInformationJobObject,
        JOBOBJECT_BASIC_UI_RESTRICTIONS, JOB_OBJECT_UILIMIT_DESKTOP,
        JOB_OBJECT_UILIMIT_DISPLAYSETTINGS, JOB_OBJECT_UILIMIT_EXITWINDOWS,
        JOB_OBJECT_UILIMIT_GLOBALATOMS, JOB_OBJECT_UILIMIT_HANDLES,
        JOB_OBJECT_UILIMIT_READCLIPBOARD, JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS,
        JOB_OBJECT_UILIMIT_WRITECLIPBOARD,
    };

    // write_manifest's fixture declares the evidence_verifier profile with
    // requires_ui_responsiveness: false — the closed schema requires that
    // pairing for every profile except Cockpit (validate_dispatch_workload_profile).
    let root = sandbox("ui-wall");
    let manifest = write_manifest(&root, "dispatch-ui-wall", 10_000);
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    let connection = Connection::open(&db).unwrap();
    let job_object_name: String = connection
        .query_row(
            "SELECT job_object_name FROM jobs WHERE job_id='dispatch-ui-wall'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let wide: Vec<u16> = std::ffi::OsStr::new(&job_object_name)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let job = unsafe { OpenJobObjectW(0x0004, 0, wide.as_ptr()) };
    assert!(!job.is_null());
    let mut info: JOBOBJECT_BASIC_UI_RESTRICTIONS = unsafe { zeroed() };
    let ok = unsafe {
        QueryInformationJobObject(
            job,
            JobObjectBasicUIRestrictions,
            (&mut info as *mut JOBOBJECT_BASIC_UI_RESTRICTIONS).cast(),
            size_of::<JOBOBJECT_BASIC_UI_RESTRICTIONS>() as u32,
            std::ptr::null_mut(),
        )
    };
    unsafe { CloseHandle(job) };
    assert_ne!(ok, 0);
    let expected = JOB_OBJECT_UILIMIT_HANDLES
        | JOB_OBJECT_UILIMIT_READCLIPBOARD
        | JOB_OBJECT_UILIMIT_WRITECLIPBOARD
        | JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS
        | JOB_OBJECT_UILIMIT_DISPLAYSETTINGS
        | JOB_OBJECT_UILIMIT_GLOBALATOMS
        | JOB_OBJECT_UILIMIT_DESKTOP
        | JOB_OBJECT_UILIMIT_EXITWINDOWS;
    assert_eq!(info.UIRestrictionsClass, expected);

    // The declaration is receipted alongside the job-object identity so the
    // wall is provable from custody evidence, not just live kernel state.
    let events: Vec<String> = connection
        .prepare("SELECT payload_json FROM events WHERE job_id='dispatch-ui-wall' AND kind IN ('job_start_reserved','job_prepared') ORDER BY seq")
        .unwrap()
        .query_map([], |row| row.get(0))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert!(!events.is_empty());
    for payload in events {
        let value: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(value["requires_ui_responsiveness"], false);
    }
    daemon.stop_job("dispatch-ui-wall").unwrap();
}

#[test]
fn dispatch_manifest_does_not_wall_the_windows_ui_surface_for_cockpit_profiles() {
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        JobObjectBasicUIRestrictions, OpenJobObjectW, QueryInformationJobObject,
        JOBOBJECT_BASIC_UI_RESTRICTIONS,
    };

    // The closed Cockpit workload profile is the only profile permitted to
    // declare requires_ui_responsiveness: true (validate_dispatch_workload_profile
    // rejects the pairing for every other profile). Cockpit also requires a
    // TelemetryBuffer pinned-host producer instead of evidence_verifier's
    // ReceiptVerifier; the producer budget must still exactly cover
    // SIMULATED_PEAK_COMMIT_BYTES, so only profile_id, producer kind, and the
    // UI-responsiveness flag change from write_manifest's default fixture —
    // mirroring the mutation dispatch_manifest_fails_closed_before_spawn_on_time_hash_and_storage
    // already uses to build a Cockpit manifest for its "vram" case.
    let root = sandbox("ui-cockpit-escape");
    let manifest = write_manifest(&root, "dispatch-ui-cockpit-escape", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["workload_profile"]["profile_id"] = json!("cockpit");
    payload["workload_profile"]["pinned_host_producers"][0]["kind"] = json!("telemetry_buffer");
    payload["workload_profile"]["requires_ui_responsiveness"] = json!(true);
    // Every non-EvidenceVerifier profile must declare a positive VRAM floor
    // (validate_dispatch_manifest_snapshot_preconditions) — write_manifest's
    // default fixture leaves it at 0 because evidence_verifier is exempt.
    payload["minimum_free_vram_bytes"] = json!(1);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();

    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    let token_capture = root.join("custody").join("dispatch-token.txt");
    let token_capture_deadline = std::time::Instant::now() + Duration::from_secs(5);
    while !token_capture.exists() && std::time::Instant::now() < token_capture_deadline {
        thread::sleep(Duration::from_millis(10));
    }
    let token_capture = fs::read_to_string(&token_capture).unwrap();
    let mut token_lines = token_capture.lines();
    assert_eq!(token_lines.next(), Some("dispatch-ui-cockpit-escape"));
    assert_eq!(token_lines.next().unwrap().len(), 64);
    assert_eq!(token_lines.next(), None);
    let connection = Connection::open(&db).unwrap();
    let job_object_name: String = connection
        .query_row(
            "SELECT job_object_name FROM jobs WHERE job_id='dispatch-ui-cockpit-escape'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let wide: Vec<u16> = std::ffi::OsStr::new(&job_object_name)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let job = unsafe { OpenJobObjectW(0x0004, 0, wide.as_ptr()) };
    assert!(!job.is_null());
    let mut info: JOBOBJECT_BASIC_UI_RESTRICTIONS = unsafe { zeroed() };
    let ok = unsafe {
        QueryInformationJobObject(
            job,
            JobObjectBasicUIRestrictions,
            (&mut info as *mut JOBOBJECT_BASIC_UI_RESTRICTIONS).cast(),
            size_of::<JOBOBJECT_BASIC_UI_RESTRICTIONS>() as u32,
            std::ptr::null_mut(),
        )
    };
    unsafe { CloseHandle(job) };
    assert_ne!(ok, 0);
    assert_eq!(
        info.UIRestrictionsClass, 0,
        "Cockpit-profile job must not carry the non-Cockpit UI-restriction wall"
    );

    // The escape hatch is receipted alongside the job-object identity so it
    // is provable from custody evidence, not just live kernel state.
    let events: Vec<String> = connection
        .prepare("SELECT payload_json FROM events WHERE job_id='dispatch-ui-cockpit-escape' AND kind IN ('job_start_reserved','job_prepared') ORDER BY seq")
        .unwrap()
        .query_map([], |row| row.get(0))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert!(!events.is_empty());
    for payload in events {
        let value: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(value["requires_ui_responsiveness"], true);
    }
    daemon.stop_job("dispatch-ui-cockpit-escape").unwrap();
}

#[test]
fn dispatch_manifest_refuses_a_headless_no_windows_spawn_that_presents_a_visible_window() {
    // write_manifest's fixture already declares window_contract:
    // "headless_no_windows" (the required-field default for every non-Cockpit
    // profile). Swap only the spawned program's args/env to point at
    // fixture_dispatch_child_presents_a_visible_window, which paints a real
    // window (CreateWindowExW) instead of the default fixture's plain 30s
    // sleep.
    let root = sandbox("window-contract-violation");
    let manifest = write_manifest(&root, "dispatch-window-violation", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["args"] = json!([
        "--exact",
        "fixture_dispatch_child_presents_a_visible_window",
        "--nocapture"
    ]);
    payload["env"]["EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW"] = json!("1");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();

    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();

    // Test-side warmup (issue #1727 round 2), kept: it is a real, measured
    // latency reduction for the spawned child's own cold start (loader, CRT,
    // harness init, first window-creation call), even though round 3 proved
    // it is not sufficient on its own (see the budget comment below).
    let warmup_status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "fixture_dispatch_child_presents_a_visible_window",
            "--nocapture",
        ])
        .env("EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW", "1")
        .env("EMBER_LAB_DISPATCH_FIXTURE_CHILD_WINDOW_WARMUP", "1")
        .status()
        .unwrap();
    assert!(
        warmup_status.success(),
        "warmup spawn of the fixture binary failed"
    );

    // Issue #1727 round 3: rounds 1-2 chased a cold-start/session-warmth
    // theory and both failed a forced-cold 3x-green bar (round 3 evidence:
    // COLD_GREEN_RUNS=2/3, an identically-shaped failure on a maximally warm
    // session). The real defect is a fixed-budget timing race: the child's
    // CreateWindowExW has no scheduling guarantee against the census+poll
    // window, and under host load (parallel test threads, rebuild tails) it
    // can lose that race even though the window contract is not actually
    // respected. Production keeps a tight 200ms budget
    // (DEFAULT_WINDOW_CENSUS_BUDGET in lib.rs, its own small default-value
    // test) because admission must stay fast; late windows are explicitly
    // out of scope for admission-time enforcement (the L7 periodic
    // re-census leg covers those). This test exists to verify the REFUSAL
    // MECHANISM -- that a job-owned window is detected and enriched with
    // hwnd/pid/title detail, and that the refusal fails closed -- not to
    // race the production scheduler, so it injects a generous budget via
    // the census-budget-injectable entry point instead of shrinking the
    // production default.
    let outcome = daemon.dispatch_manifest_at_with_probes_and_host_and_window_census_budget(
        &manifest,
        10_001,
        |_root| Ok(1024),
        || Ok(2048),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        Duration::from_secs(5),
    );
    let error = outcome.unwrap_err();
    match &error {
        EmberLabError::WindowContractViolation { job_id, detail } => {
            assert_eq!(job_id, "dispatch-window-violation");
            assert!(
                detail.contains("headless_no_windows"),
                "refusal message must self-describe the violated contract: {detail}"
            );
            // The refusal carries real per-window debugging detail (HWND,
            // owning PID, and the fixture's own window title text), not
            // just a bare count -- prove the enrichment actually ran
            // against the real window, not merely that the code compiles.
            assert!(
                detail.contains("hwnd=0x") && detail.contains("pid="),
                "refusal message must carry per-window hwnd/pid detail: {detail}"
            );
            assert!(
                detail.contains("l6-window-contract-fixture"),
                "refusal message must carry the offending window's own title text: {detail}"
            );
        }
        other => panic!("expected WindowContractViolation, got {other:?}"),
    }

    // Fail-closed cleanup: dispatch_manifest_at_with_probes_and_host's outer
    // rollback_dispatch_attempt purges the job/events/lease rows for any
    // start_job failure that reaches a terminal state (mirrors every other
    // start_job failure kind -- job_spawn_failed, job_prepare_commit_failed,
    // job_launch_commit_failed -- see e.g.
    // dispatch_manifest_rejects_a_missing_job_memory_ceiling's identical
    // job_state==None assertion). The synchronous returned
    // WindowContractViolation error, asserted above, is the receipt a
    // caller actually sees; a caller retrying the same resource is not
    // blocked by the refused spawn.
    assert_eq!(daemon.job_state("dispatch-window-violation").unwrap(), None);
    assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);

    // mark_failed still records the distinct "job_window_contract_violation"
    // kind (not the generic job_launch_commit_failed every other running-
    // closure failure shares) in the same commit that transitions the job
    // to 'failed' -- it is visible for the instant between that commit and
    // rollback_dispatch_attempt's purge, and would remain durable if this
    // codebase's purge-on-terminal-failure convention ever changes. Confirm
    // the purge actually ran (rather than merely never having written
    // anything) by checking the jobs table is empty for this job_id too.
    let connection = Connection::open(&db).unwrap();
    let remaining_job_rows: i64 = connection
        .query_row(
            "SELECT COUNT(*) FROM jobs WHERE job_id='dispatch-window-violation'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(remaining_job_rows, 0);
}

#[test]
fn identical_dispatch_retry_reconstructs_the_existing_job_and_receipt() {
    let root = sandbox("idempotent-retry");
    let manifest = write_manifest(&root, "dispatch-idempotent-retry", 10_000);
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();

    let first = daemon.dispatch_manifest_at_with_probes_and_host(
        &manifest,
        10_001,
        |_root| {
            fs::create_dir(&receipt_path).unwrap();
            Ok(1024)
        },
        || Ok(2048),
        || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
    );
    assert!(matches!(
        first,
        Err(EmberLabError::DispatchReceiptRecoveryPending { .. })
    ));
    assert_eq!(
        daemon.job_state("dispatch-receipt-recovery").unwrap(),
        Some(JobState::Running)
    );
    assert!(matches!(
        daemon.adopt_job("dispatch-receipt-recovery"),
        Err(EmberLabError::DispatchReceiptRecoveryPending { .. })
    ));
    let connection = Connection::open(root.join("ember-lab.sqlite3")).unwrap();
    let first_pid: u32 = connection
        .query_row(
            "SELECT pid FROM jobs WHERE job_id='dispatch-receipt-recovery'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    fs::remove_dir(&receipt_path).unwrap();
    connection
        .execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason='recovery_must_precede_new_admission',observed_at_ms=10002,oracle_evidence_required=1,observation_json=?1 WHERE singleton=1",
            [json!({"result":"FROZEN_DURING_RECEIPT_RECOVERY"}).to_string()],
        )
        .unwrap();
    drop(connection);

    let recovered = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| panic!("an already-admitted recovery must not rerun storage admission"),
            || panic!("an already-admitted recovery must not rerun VRAM admission"),
            || panic!("an already-admitted recovery must not rerun host-commit admission"),
        )
        .unwrap();
    assert_eq!(recovered.handle.pid, first_pid);
    assert!(recovered.receipt.path.is_file());
    let recovered_receipt: Value =
        serde_json::from_slice(&fs::read(&recovered.receipt.path).unwrap()).unwrap();
    assert_eq!(recovered_receipt["result"], "PREFLIGHT_PASSED");
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
        Err(EmberLabError::LeaseConflict { .. })
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
    payload["schema_version"] = json!("ember-lab-dispatch-manifest-v1");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
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
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
        let error = daemon
            .dispatch_manifest_at_with_probes_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
                || {
                    Ok(HostCommitCapacity {
                        basis: "maximum_configured_capacity".to_string(),
                        sampled_at_ms: 10_000,
                        snapshot_sha256: "d".repeat(64),
                        physical_ram_bytes: physical,
                        physical_available_bytes: 32 * GIB,
                        pagefile_maximum_bytes: pagefile_maximum,
                        pagefile_configuration_source: r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles".to_string(),
                        pagefile_configuration_sha256: "b".repeat(64),
                        commit_total_bytes: commit_total,
                        current_commit_limit_bytes: 80 * GIB,
                        current_commit_remaining_bytes: (80 * GIB).saturating_sub(commit_total),
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
    ] {
        let root = sandbox(name);
        let manifest = write_manifest(&root, &format!("dispatch-{name}"), 10_000);
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        payload["required_available_maximum_commit_bytes"] = json!(declared_free);
        payload["maximum_job_memory_bytes"] = json!(maximum);
        payload["simulated_peak_commit_bytes"] = json!(simulated_peak);
        fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
    payload["workload_profile"]["pinned_host_producers"][0]["maximum_bytes"] = json!(67_108_864u64);
    payload["env"]["EMBER_LAB_DISPATCH_ALLOCATE_BYTES"] = json!(536_870_912u64.to_string());
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
    let receipt_path = root.join("operational-receipt.json");
    daemon
        .export_receipt("dispatch-memory-ceiling", &receipt_path)
        .unwrap();
    let receipt: Value = serde_json::from_slice(&fs::read(receipt_path).unwrap()).unwrap();
    let events = receipt["events"].as_array().unwrap();
    let alarm = events
        .iter()
        .find(|event| event["kind"] == "job_memory_limit_reached")
        .expect("the kernel job-memory-limit alarm must be receipted");
    assert_eq!(alarm["payload"]["kernel_message_code"], 10);
    assert_eq!(alarm["payload"]["overshoot_allowance_bps"], 617);
    assert_eq!(
        alarm["payload"]["overshoot_allowance_basis"],
        "windows_job_object_cuda_wddm_measured"
    );
    assert_eq!(
        alarm["payload"]["kernel_limit_signal_observation_available"],
        true
    );
    assert_eq!(
        alarm["payload"]["kernel_limit_signal_observation_reason"],
        Value::Null
    );
    assert_eq!(alarm["payload"]["scope"], "windows_job_object");
    assert!(alarm["payload"]["offending_pid"].as_u64().unwrap() > 0);
    assert!(
        alarm["payload"]["peak_job_memory_used_bytes"]
            .as_u64()
            .unwrap()
            > 0
    );
    assert_eq!(
        alarm["payload"]["verification"]["job_object_membership"]["verified"],
        true
    );
    assert_eq!(
        alarm["payload"]["verification"]["process_identity"]["verified"],
        true
    );
    assert_eq!(
        alarm["payload"]["verification"]["process_identity"]["handle_pid"],
        alarm["payload"]["offending_pid"]
    );
    assert_eq!(
        alarm["payload"]["verification"]["process_identity"]["handle_pid_verified"],
        true
    );
    assert_eq!(alarm["payload"]["verification"]["lease"]["verified"], true);
    assert_eq!(
        events
            .iter()
            .filter(|event| event["kind"] == "job_memory_limit_reached")
            .count(),
        1
    );
    let accounting_index = events
        .iter()
        .position(|event| event["kind"] == "job_memory_accounting")
        .expect("terminal job-memory accounting must be receipted");
    assert_eq!(
        events[accounting_index]["payload"]["limit_signal_observed"],
        true
    );
    let exited_index = events
        .iter()
        .position(|event| event["kind"] == "job_exited")
        .expect("job exit must be receipted");
    assert!(accounting_index < exited_index);
}

#[test]
fn dispatch_job_memory_below_limit_receipts_peak_without_alarm() {
    let root = sandbox("job-memory-below-limit");
    let manifest = write_manifest(&root, "dispatch-memory-below-limit", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["env"]["EMBER_LAB_DISPATCH_ALLOCATE_BYTES"] = json!((16 * 1024 * 1024u64).to_string());
    payload["env"]["EMBER_LAB_DISPATCH_FIXTURE_SLEEP_MS"] = json!("50");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
            .job_state("dispatch-memory-below-limit")
            .unwrap()
            .unwrap();
        if matches!(state, JobState::Exited | JobState::Failed) {
            break;
        }
        assert!(std::time::Instant::now() < deadline);
        thread::sleep(Duration::from_millis(25));
    }
    let receipt_path = root.join("operational-receipt.json");
    daemon
        .export_receipt("dispatch-memory-below-limit", &receipt_path)
        .unwrap();
    let receipt: Value = serde_json::from_slice(&fs::read(receipt_path).unwrap()).unwrap();
    let events = receipt["events"].as_array().unwrap();
    assert!(!events
        .iter()
        .any(|event| event["kind"] == "job_memory_limit_reached"));
    let accounting = events
        .iter()
        .find(|event| event["kind"] == "job_memory_accounting")
        .expect("terminal job-memory accounting must be receipted");
    assert_eq!(accounting["payload"]["limit_signal_observed"], false);
    assert_eq!(
        accounting["payload"]["kernel_limit_signal_observation_available"],
        true
    );
    assert_eq!(
        accounting["payload"]["kernel_limit_signal_observation_reason"],
        Value::Null
    );
    assert_eq!(accounting["payload"]["overshoot_allowance_bps"], 617);
    assert!(
        accounting["payload"]["peak_job_memory_used_bytes"]
            .as_u64()
            .unwrap()
            > 0
    );
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-missing-memory").unwrap(), None);
    assert!(!root.join("custody").join("preflight.json").exists());
}

#[test]
fn dispatch_manifest_rejects_caller_supplied_armed_job_memory_environment() {
    let root = sandbox("caller-supplied-armed-job-memory-env");
    let manifest = write_manifest(&root, "dispatch-caller-armed-cap", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["env"]["EMBER_LAB_DISPATCH_MAXIMUM_JOB_MEMORY_BYTES"] =
        json!(MAXIMUM_JOB_MEMORY_BYTES.to_string());
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
    ));
    assert_eq!(daemon.job_state("dispatch-caller-armed-cap").unwrap(), None);
    assert!(!root.join("custody").join("preflight.json").exists());
}

#[test]
fn dispatch_manifest_requires_a_closed_workload_profile_before_spawn() {
    for (name, mutate) in [
        (
            "missing",
            Box::new(|payload: &mut Value| {
                payload.as_object_mut().unwrap().remove("workload_profile");
            }) as Box<dyn Fn(&mut Value)>,
        ),
        (
            "unknown-producer",
            Box::new(|payload: &mut Value| {
                payload["workload_profile"]["pinned_host_producers"][0]["kind"] =
                    json!("unbounded_plugin");
            }),
        ),
        (
            "duplicate-producer",
            Box::new(|payload: &mut Value| {
                let duplicate = payload["workload_profile"]["pinned_host_producers"][0].clone();
                payload["workload_profile"]["pinned_host_producers"]
                    .as_array_mut()
                    .unwrap()
                    .push(duplicate);
            }),
        ),
        (
            "producer-budget-overflow",
            Box::new(|payload: &mut Value| {
                payload["workload_profile"]["pinned_host_producers"][0]["maximum_bytes"] =
                    json!(MAXIMUM_JOB_MEMORY_BYTES + 1);
            }),
        ),
        (
            "ui-profile-mismatch",
            Box::new(|payload: &mut Value| {
                payload["workload_profile"]["requires_ui_responsiveness"] = json!(true);
            }),
        ),
    ] {
        let root = sandbox(&format!("profile-{name}"));
        let job_id = format!("dispatch-profile-{name}");
        let manifest = write_manifest(&root, &job_id, 10_000);
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        mutate(&mut payload);
        fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
        assert!(matches!(
            daemon.dispatch_manifest_at_with_probes_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            ),
            Err(EmberLabError::InvalidDispatchManifest { .. })
        ));
        assert_eq!(daemon.job_state(&job_id).unwrap(), None);
        assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
        assert!(!root.join("custody").join("preflight.json").exists());
    }
}

#[test]
fn sticky_resource_guard_freeze_refuses_dispatch_with_a_durable_receipt() {
    let root = sandbox("resource-guard-frozen");
    let db = root.join("ember-lab.sqlite3");
    let manifest = write_manifest(&root, "dispatch-resource-guard-frozen", 10_000);
    let daemon = Daemon::open(&db).unwrap();
    Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason='physical_available_below_survival_floor',observed_at_ms=9999,oracle_evidence_required=1,observation_json=?1 WHERE singleton=1",
            [json!({
                "schema_version": "ember-lab-resource-guard-observation-v1",
                "result": "SURVIVAL_FLOOR_BREACH",
                "physical_available_bytes": 1,
                "commit_remaining_bytes": 2,
                "driver_locked_provider": "UNAVAILABLE"
            }).to_string()],
        )
        .unwrap();

    let error = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap_err();
    assert!(
        format!("{error:?}").contains("ResourceAdmissionFrozen"),
        "unexpected error: {error:?}"
    );
    assert_eq!(
        daemon.job_state("dispatch-resource-guard-frozen").unwrap(),
        None
    );
    assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);
    let receipt: Value =
        serde_json::from_slice(&fs::read(root.join("custody").join("preflight.json")).unwrap())
            .unwrap();
    assert_eq!(receipt["result"], "REFUSED_RESOURCE_GUARD_FROZEN");
    assert_eq!(receipt["resource_guard"]["admission_state"], "frozen");
    assert_eq!(receipt["resource_guard"]["oracle_evidence_required"], true);
    assert_eq!(receipt["foreign_process_pressure_refusal"], false);
    assert!(receipt.get("foreign_process_pressure").is_none());
    let refusal_path = root.join("custody").join("preflight.json");
    let refusal_before = fs::read(&refusal_path).unwrap();
    fs::remove_file(&refusal_path).unwrap();
    assert!(daemon
        .rearm_resource_guard_at(
            ResourceGuardRearmRequest {
                frozen_observation_sha256: "0".repeat(64),
                breach_class: "physical_available_below_survival_floor".into(),
                diagnostic_receipt_path: root.join("absent-diagnostic.json"),
                diagnostic_receipt_sha256: "1".repeat(64),
            },
            10_000,
        )
        .is_err());
    Connection::open(&db)
        .unwrap()
        .execute(
            "UPDATE foreign_process_pressure_state
             SET state='clear',observed_at_ms=20001,observation_json=?1
             WHERE singleton=1",
            [json!({
                "schema_version": "ember-lab-foreign-process-pressure-observation-v1",
                "result": "CLEAR",
                "test_marker": "changed_between_sticky_refusals"
            })
            .to_string()],
        )
        .unwrap();
    assert!(daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .is_err());
    assert_eq!(fs::read(&refusal_path).unwrap(), refusal_before);
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn evidenced_resource_guard_rearm_consumes_the_exact_freeze_after_a_healthy_window() {
    let root = sandbox("resource-guard-evidenced-rearm");
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open_with_resource_guard_seed(&db, Ok(host_capacity(16 * GIB))).unwrap();
    let freeze_at_ms = 10_000i64;
    let freeze = json!({
        "schema_version": "ember-lab-resource-guard-observation-v1",
        "result": "SURVIVAL_FLOOR_BREACH",
        "observed_at_ms": freeze_at_ms,
        "monitor_tier": "cheap_host_counters",
        "driver_locked_provider": "UNAVAILABLE",
        "physical_available_bytes": 16 * GIB,
        "commit_remaining_bytes": GIB,
        "minimum_physical_available_bytes": 8 * GIB,
        "minimum_commit_remaining_bytes": 10 * GIB,
    });
    let freeze_bytes = serde_json::to_vec(&freeze).unwrap();
    let freeze_sha256 = format!("{:x}", Sha256::digest(&freeze_bytes));
    let connection = Connection::open(&db).unwrap();
    connection
        .execute(
            "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(?1,'frozen',?2)",
            rusqlite::params![freeze_at_ms, String::from_utf8(freeze_bytes).unwrap()],
        )
        .unwrap();
    connection
        .execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason='commit_remaining_below_survival_floor',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
            rusqlite::params![freeze_at_ms, serde_json::to_string(&freeze).unwrap()],
        )
        .unwrap();
    for index in 1..=31i64 {
        let observed_at_ms = freeze_at_ms + index * 2_000;
        let healthy = json!({
            "schema_version": "ember-lab-resource-guard-observation-v1",
            "result": "HEALTHY",
            "observed_at_ms": observed_at_ms,
            "monitor_tier": "cheap_host_counters",
            "driver_locked_provider": "UNAVAILABLE",
            "physical_available_bytes": 12 * GIB,
            "commit_remaining_bytes": 15 * GIB,
            "minimum_physical_available_bytes": 8 * GIB,
            "minimum_commit_remaining_bytes": 10 * GIB,
        });
        connection
            .execute(
                "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(?1,'healthy',?2)",
                rusqlite::params![observed_at_ms, serde_json::to_string(&healthy).unwrap()],
            )
            .unwrap();
    }
    let diagnostic = json!({
        "schema_version": "ember-lab-resource-guard-diagnostic-v1",
        "result": "EXECUTED",
        "breach_class": "commit_remaining_below_survival_floor",
        "frozen_observation_sha256": freeze_sha256,
        "executed_at_ms": freeze_at_ms + 30_000,
        "probe": {
            "resource": "host_commit",
            "kind": "allocation_probe",
            "real_allocation_executed": true,
            "requested_bytes": 1,
            "result": "COMPLETED",
        },
    });
    let diagnostic_bytes = serde_json::to_vec(&diagnostic).unwrap();
    let diagnostic_sha256 = format!("{:x}", Sha256::digest(&diagnostic_bytes));
    let diagnostic_path = root.join(format!("{diagnostic_sha256}.json"));
    fs::write(&diagnostic_path, diagnostic_bytes).unwrap();

    let artifact = daemon
        .rearm_resource_guard_at(
            ResourceGuardRearmRequest {
                frozen_observation_sha256: freeze_sha256.clone(),
                breach_class: "commit_remaining_below_survival_floor".into(),
                diagnostic_receipt_path: diagnostic_path,
                diagnostic_receipt_sha256: diagnostic_sha256.clone(),
            },
            freeze_at_ms + 63_000,
        )
        .unwrap();

    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "open"
    );
    assert_eq!(sha256(&artifact.path), artifact.sha256);
    let receipt: Value = serde_json::from_slice(&fs::read(&artifact.path).unwrap()).unwrap();
    assert_eq!(
        receipt["schema_version"],
        "ember-lab-resource-guard-rearm-v1"
    );
    assert_eq!(receipt["result"], "RESOURCE_GUARD_REARMED");
    assert_eq!(receipt["frozen_observation_sha256"], freeze_sha256);
    assert_eq!(receipt["healthy_window"]["sample_count"], 31);
    assert_eq!(receipt["healthy_window"]["span_ms"], 60_000);
    assert_eq!(receipt["healthy_window"]["hysteresis_numerator"], 3);
    assert_eq!(receipt["healthy_window"]["hysteresis_denominator"], 2);
    assert_eq!(receipt["flap_guard"]["multiplier"], 1);
    assert_eq!(receipt["diagnostic_receipt_sha256"], diagnostic_sha256);

    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);
}

fn resource_guard_rearm_fixture(
    name: &str,
    healthy_sample_count: i64,
    diagnostic_executed_at_ms: i64,
) -> (
    PathBuf,
    PathBuf,
    Daemon,
    Connection,
    ResourceGuardRearmRequest,
) {
    let root = sandbox(name);
    let db = root.join("ember-lab.sqlite3");
    let daemon =
        Daemon::open_with_resource_guard_seed_without_monitor(&db, Ok(host_capacity(16 * GIB)))
            .unwrap();
    assert!(!daemon.resource_guard_monitor_started_for_test());
    let freeze_at_ms = 10_000i64;
    let freeze = json!({
        "schema_version": "ember-lab-resource-guard-observation-v1",
        "result": "SURVIVAL_FLOOR_BREACH",
        "observed_at_ms": freeze_at_ms,
        "monitor_tier": "cheap_host_counters",
        "driver_locked_provider": "UNAVAILABLE",
        "physical_available_bytes": 16 * GIB,
        "commit_remaining_bytes": GIB,
        "minimum_physical_available_bytes": 8 * GIB,
        "minimum_commit_remaining_bytes": 10 * GIB,
    });
    let freeze_json = serde_json::to_string(&freeze).unwrap();
    let freeze_sha256 = format!("{:x}", Sha256::digest(freeze_json.as_bytes()));
    let connection = Connection::open(&db).unwrap();
    connection
        .execute(
            "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(?1,'frozen',?2)",
            rusqlite::params![freeze_at_ms, freeze_json],
        )
        .unwrap();
    connection
        .execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason='commit_remaining_below_survival_floor',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
            rusqlite::params![freeze_at_ms, serde_json::to_string(&freeze).unwrap()],
        )
        .unwrap();
    for index in 1..=healthy_sample_count {
        let observed_at_ms = freeze_at_ms + index * 2_000;
        let healthy = json!({
            "schema_version": "ember-lab-resource-guard-observation-v1",
            "result": "HEALTHY",
            "observed_at_ms": observed_at_ms,
            "monitor_tier": "cheap_host_counters",
            "driver_locked_provider": "UNAVAILABLE",
            "physical_available_bytes": 12 * GIB,
            "commit_remaining_bytes": 15 * GIB,
            "minimum_physical_available_bytes": 8 * GIB,
            "minimum_commit_remaining_bytes": 10 * GIB,
        });
        connection
            .execute(
                "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(?1,'healthy',?2)",
                rusqlite::params![observed_at_ms, serde_json::to_string(&healthy).unwrap()],
            )
            .unwrap();
    }
    let diagnostic = json!({
        "schema_version": "ember-lab-resource-guard-diagnostic-v1",
        "result": "EXECUTED",
        "breach_class": "commit_remaining_below_survival_floor",
        "frozen_observation_sha256": freeze_sha256,
        "executed_at_ms": diagnostic_executed_at_ms,
        "probe": {
            "resource": "host_commit",
            "kind": "allocation_probe",
            "real_allocation_executed": true,
            "requested_bytes": 1,
            "result": "COMPLETED",
        },
    });
    let diagnostic_bytes = serde_json::to_vec(&diagnostic).unwrap();
    let diagnostic_sha256 = format!("{:x}", Sha256::digest(&diagnostic_bytes));
    let diagnostic_path = root.join(format!("{diagnostic_sha256}.json"));
    fs::write(&diagnostic_path, diagnostic_bytes).unwrap();
    let request = ResourceGuardRearmRequest {
        frozen_observation_sha256: freeze_sha256,
        breach_class: "commit_remaining_below_survival_floor".into(),
        diagnostic_receipt_path: diagnostic_path,
        diagnostic_receipt_sha256: diagnostic_sha256,
    };
    (root, db, daemon, connection, request)
}

#[test]
fn resource_guard_rearm_refuses_unbound_stale_or_insufficient_evidence_without_thawing() {
    let cases = [
        ("insufficient-span", 30, 40_000, 73_000),
        ("stale-newest", 31, 40_000, 83_001),
        ("diagnostic-outside-window", 31, 9_999, 73_000),
    ];
    for (name, samples, diagnostic_at, transition_at) in cases {
        let (root, _db, daemon, connection, request) =
            resource_guard_rearm_fixture(name, samples, diagnostic_at);
        assert!(daemon
            .rearm_resource_guard_at(request, transition_at)
            .is_err());
        assert_eq!(
            daemon.resource_guard_status().unwrap()["admission_state"],
            "frozen"
        );
        drop(daemon);
        drop(connection);
        remove_sandbox_when_unlocked(&root);
    }

    let (root, _db, daemon, connection, request) =
        resource_guard_rearm_fixture("wrong-binding", 31, 40_000);
    let mut wrong_hash = request.clone();
    wrong_hash.frozen_observation_sha256 = "0".repeat(64);
    assert!(daemon.rearm_resource_guard_at(wrong_hash, 73_000).is_err());
    let mut wrong_class = request.clone();
    wrong_class.breach_class = "physical_available_below_survival_floor".into();
    assert!(daemon.rearm_resource_guard_at(wrong_class, 73_000).is_err());
    let mut wrong_receipt = request.clone();
    wrong_receipt.diagnostic_receipt_sha256 = "f".repeat(64);
    assert!(daemon
        .rearm_resource_guard_at(wrong_receipt, 73_000)
        .is_err());
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);

    let (root, _db, daemon, connection, request) =
        resource_guard_rearm_fixture("unknown-diagnostic-field", 31, 40_000);
    let mut diagnostic: Value =
        serde_json::from_slice(&fs::read(&request.diagnostic_receipt_path).unwrap()).unwrap();
    diagnostic
        .as_object_mut()
        .unwrap()
        .insert("unbound_claim".into(), Value::Bool(true));
    let diagnostic_bytes = serde_json::to_vec(&diagnostic).unwrap();
    let diagnostic_sha256 = format!("{:x}", Sha256::digest(&diagnostic_bytes));
    let diagnostic_path = root.join(format!("{diagnostic_sha256}.json"));
    fs::write(&diagnostic_path, diagnostic_bytes).unwrap();
    assert!(daemon
        .rearm_resource_guard_at(
            ResourceGuardRearmRequest {
                diagnostic_receipt_path: diagnostic_path,
                diagnostic_receipt_sha256: diagnostic_sha256,
                ..request
            },
            73_000,
        )
        .is_err());
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);

    let (root, _db, daemon, connection, request) =
        resource_guard_rearm_fixture("interleaved-breach", 31, 40_000);
    connection
        .execute(
            "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(72500,'frozen','{}')",
            [],
        )
        .unwrap();
    assert!(daemon.rearm_resource_guard_at(request, 73_000).is_err());
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);

    let (root, _db, daemon, connection, request) =
        resource_guard_rearm_fixture("below-hysteresis", 31, 40_000);
    let below_hysteresis = json!({
        "schema_version": "ember-lab-resource-guard-observation-v1",
        "result": "HEALTHY",
        "observed_at_ms": 72_500,
        "physical_available_bytes": 12 * GIB - 1,
        "commit_remaining_bytes": 15 * GIB,
        "minimum_physical_available_bytes": 8 * GIB,
        "minimum_commit_remaining_bytes": 10 * GIB,
    });
    connection
        .execute(
            "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(72500,'healthy',?1)",
            [serde_json::to_string(&below_hysteresis).unwrap()],
        )
        .unwrap();
    assert!(daemon.rearm_resource_guard_at(request, 73_000).is_err());
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);

    let (root, db, daemon, connection, request) =
        resource_guard_rearm_fixture("flap-doubles-window", 31, 40_000);
    connection
        .execute(
            "INSERT INTO resource_guard_rearms(frozen_observation_sha256,breach_class,transitioned_at_ms,receipt_path,receipt_sha256,healthy_sample_count,healthy_window_ms,flap_multiplier) VALUES(?1,?2,?3,?4,?5,31,60000,1)",
            rusqlite::params!["1".repeat(64), "commit_remaining_below_survival_floor", 72_000i64, root.join("prior.json").to_string_lossy(), "2".repeat(64)],
        )
        .unwrap();
    assert!(daemon.rearm_resource_guard_at(request, 73_000).is_err());
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    assert_eq!(
        Connection::open(db)
            .unwrap()
            .query_row("SELECT COUNT(*) FROM resource_guard_rearms", [], |row| row
                .get::<_, i64>(
                0
            ))
            .unwrap(),
        1
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);

    let (root, _db, daemon, connection, request) =
        resource_guard_rearm_fixture("single-use-freeze", 31, 40_000);
    daemon
        .rearm_resource_guard_at(request.clone(), 73_000)
        .unwrap();
    let frozen_json = connection
        .query_row(
            "SELECT payload_json FROM resource_guard_observations WHERE outcome='frozen' ORDER BY seq DESC LIMIT 1",
            [],
            |row| row.get::<_, String>(0),
        )
        .unwrap();
    connection
        .execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason='commit_remaining_below_survival_floor',observed_at_ms=10000,oracle_evidence_required=1,observation_json=?1 WHERE singleton=1",
            [frozen_json],
        )
        .unwrap();
    assert!(daemon.rearm_resource_guard_at(request, 74_000).is_err());
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn real_epoch_monitor_observation_refuses_a_synthetic_rearm_timeline() {
    let (root, _db, daemon, connection, request) =
        resource_guard_rearm_fixture("real-epoch-row-refuses-synthetic-rearm", 31, 40_000);
    let real_epoch_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64;
    let real_epoch_observation = json!({
        "schema_version": "ember-lab-resource-guard-observation-v1",
        "result": "HEALTHY",
        "observed_at_ms": real_epoch_ms,
        "monitor_tier": "cheap_host_counters",
        "driver_locked_provider": "UNAVAILABLE",
        "physical_available_bytes": 16 * GIB,
        "commit_remaining_bytes": 20 * GIB,
        "minimum_physical_available_bytes": 8 * GIB,
        "minimum_commit_remaining_bytes": 10 * GIB,
    });
    let real_epoch_observation_json = serde_json::to_string(&real_epoch_observation).unwrap();
    connection
        .execute(
            "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(?1,'healthy',?2)",
            rusqlite::params![real_epoch_ms, real_epoch_observation_json],
        )
        .unwrap();
    let error = daemon.rearm_resource_guard_at(request, 73_000).unwrap_err();
    assert!(matches!(
        error,
        EmberLabError::InvalidDispatchManifest { ref detail }
            if detail == "resource guard re-arm newest healthy observation is stale or future"
    ));
    assert_eq!(
        daemon.resource_guard_status().unwrap()["admission_state"],
        "frozen"
    );
    drop(daemon);
    drop(connection);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn resource_guard_monitor_samples_for_the_daemon_lifetime() {
    let root = sandbox("resource-guard-monitor-lifetime");
    let db_path = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db_path).unwrap();
    let initial = Connection::open(&db_path)
        .unwrap()
        .query_row(
            "SELECT COUNT(*) FROM resource_guard_observations",
            [],
            |row| row.get::<_, i64>(0),
        )
        .unwrap();
    assert_eq!(initial, 1);

    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    let later = loop {
        let count = Connection::open(&db_path)
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM resource_guard_observations",
                [],
                |row| row.get::<_, i64>(0),
            )
            .unwrap();
        if count >= 2 || std::time::Instant::now() >= deadline {
            break count;
        }
        thread::sleep(Duration::from_millis(100));
    };
    assert!(
        later >= 2,
        "expected a daemon-lifetime monitor sample before the 10-second deadline; observed {later} rows"
    );
    assert_eq!(
        daemon.resource_guard_status().unwrap()["driver_locked_provider"],
        "UNAVAILABLE"
    );
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
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
        if name == "vram" {
            let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
            payload["workload_profile"]["profile_id"] = json!("cockpit");
            payload["workload_profile"]["pinned_host_producers"][0]["kind"] =
                json!("telemetry_buffer");
            payload["workload_profile"]["requires_ui_responsiveness"] = json!(true);
            payload["minimum_free_vram_bytes"] = json!(1);
            fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
        }
        if corrupt_binding {
            fs::write(root.join("config.json"), b"changed").unwrap();
        }
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
fn unavailable_vram_provider_is_a_receipted_refusal_before_spawn() {
    let root = sandbox("vram-provider-unavailable");
    let job_id = "dispatch-vram-provider-unavailable";
    let manifest = write_manifest(&root, job_id, 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["workload_profile"]["profile_id"] = json!("cockpit");
    payload["workload_profile"]["pinned_host_producers"][0]["kind"] = json!("telemetry_buffer");
    payload["workload_profile"]["requires_ui_responsiveness"] = json!(true);
    payload["minimum_free_vram_bytes"] = json!(1);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();

    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let error = daemon
        .dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || {
                Err(EmberLabError::InvalidDispatchManifest {
                    detail: "nvidia-smi VRAM probe failed to start: program not found".into(),
                })
            },
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap_err();
    assert!(
        matches!(error, EmberLabError::DispatchVramProbeUnavailable { .. }),
        "got {error:?}"
    );
    assert_eq!(daemon.job_state(job_id).unwrap(), None);
    assert_eq!(daemon.lease_owner("gpu-smoke").unwrap(), None);

    let receipt_path = root.join("custody").join("preflight.json");
    let receipt: Value = serde_json::from_slice(&fs::read(&receipt_path).unwrap()).unwrap();
    assert_eq!(receipt["result"], "REFUSED_VRAM_PROBE_UNAVAILABLE");
    assert_eq!(receipt["job_id"], job_id);
    assert_eq!(receipt["vram_probe"]["provider"], "nvidia_smi");
    assert_eq!(receipt["vram_probe"]["minimum_free_bytes"], 1);
    assert_eq!(receipt["vram_probe"]["measurement_available"], false);
    assert!(receipt["vram_probe"]["measurement_error"]
        .as_str()
        .unwrap()
        .contains("program not found"));
    drop(daemon);
    remove_sandbox_when_unlocked(&root);
}

#[test]
fn v4_gpu_manifest_binds_uuid_fraction_floor_and_daemon_owned_environment() {
    let root = sandbox("v4-vram-wall");
    let manifest = write_manifest(&root, "dispatch-v4-vram-wall", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["schema_version"] = json!("ember-lab-dispatch-manifest-v4");
    payload
        .as_object_mut()
        .unwrap()
        .remove("minimum_free_vram_bytes");
    payload["vram_wall"] = json!({
        "applicability":"required",
        "contract":{
            "provider":"nvidia_smi_nvml",
            "device_uuid":"GPU-00000000-1111-2222-3333-444444444444",
            "maximum_process_fraction_millionths":500_000,
            "minimum_free_bytes":256 * 1024 * 1024_u64,
            "consecutive_breach_samples":3,
            "sample_interval_ms":2_000
        }
    });
    payload["workload_profile"]["profile_id"] = json!("cockpit");
    payload["workload_profile"]["pinned_host_producers"][0]["kind"] = json!("telemetry_buffer");
    payload["workload_profile"]["requires_ui_responsiveness"] = json!(true);
    payload["env"]
        .as_object_mut()
        .unwrap()
        .remove("EMBER_LAB_DISPATCH_TOKEN_CAPTURE");
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();

    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_v4_at_with_device_probe_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            |contract| {
                assert_eq!(
                    contract.device_uuid,
                    "GPU-00000000-1111-2222-3333-444444444444"
                );
                Ok(ember_lab::VramDeviceCapacity {
                    provider: "nvidia_smi_nvml".into(),
                    device_uuid: contract.device_uuid.clone(),
                    total_bytes: 1_000 * 1024 * 1024,
                    free_bytes: 700 * 1024 * 1024,
                })
            },
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    let receipt: Value = serde_json::from_slice(&fs::read(&outcome.receipt.path).unwrap()).unwrap();
    assert_eq!(receipt["vram_reserve"]["applicability"], "required");
    assert_eq!(
        receipt["vram_reserve"]["maximum_process_vram_bytes"],
        500 * 1024 * 1024_u64
    );
    assert_eq!(receipt["vram_reserve"]["consecutive_breach_samples"], 3);
    assert_eq!(receipt["vram_reserve"]["sample_interval_ms"], 2_000);
    assert!(receipt["vram_reserve"]["claim_boundary"]
        .as_str()
        .unwrap()
        .contains("not_total_vram_guarantee"));
    daemon.stop_job("dispatch-v4-vram-wall").unwrap();
}

#[test]
fn v5_manifest_binds_two_named_roots_and_samples_the_shared_volume_once() {
    let root = sandbox("v5-disk-wall");
    let manifest = write_manifest(&root, "dispatch-v5-disk-wall", 10_000);
    let write_root_a = root.join("disk-wall-a");
    let write_root_b = root.join("disk-wall-b");
    fs::create_dir(&write_root_a).unwrap();
    fs::create_dir(&write_root_b).unwrap();
    fs::write(write_root_a.join("a.bin"), b"ember-a").unwrap();
    fs::write(write_root_b.join("b.bin"), b"ember-bb").unwrap();
    let root_text = root.to_string_lossy();
    let volume_root = PathBuf::from(format!(r"{}\", &root_text[..2]));

    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["schema_version"] = json!("ember-lab-dispatch-manifest-v5");
    payload
        .as_object_mut()
        .unwrap()
        .remove("minimum_free_vram_bytes");
    payload["vram_wall"] = json!({"applicability":"not_applicable"});
    payload["disk_write_walls"] = json!([
        {
            "volume_root":volume_root,
            "write_root":write_root_a,
            "maximum_write_bytes":100 * 1024 * 1024_u64,
            "minimum_free_bytes":1,
            "sample_interval_ms":2_000,
            "maximum_measurement_duration_ms":250
        },
        {
            "volume_root":volume_root,
            "write_root":write_root_b,
            "maximum_write_bytes":100 * 1024 * 1024_u64,
            "minimum_free_bytes":1,
            "sample_interval_ms":2_000,
            "maximum_measurement_duration_ms":250
        }
    ]);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();

    let free_space_calls = std::cell::Cell::new(0_u32);
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let outcome = daemon
        .dispatch_manifest_v4_at_with_device_probe_and_host(
            &manifest,
            10_001,
            |_observed_root| {
                free_space_calls.set(free_space_calls.get() + 1);
                Ok(1024 * 1024 * 1024)
            },
            |_contract| panic!("evidence verifier v5 must not probe a GPU"),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        )
        .unwrap();
    // One call is the existing storage-reserve root. The other is the single
    // shared-volume floor probe for both named roots.
    assert_eq!(free_space_calls.get(), 2);

    let receipt: Value = serde_json::from_slice(&fs::read(&outcome.receipt.path).unwrap()).unwrap();
    let disk_receipts = receipt["disk_write_walls"].as_array().unwrap();
    assert_eq!(disk_receipts.len(), 3);
    assert_eq!(disk_receipts[0]["baseline_tree_bytes"], 7);
    assert_eq!(disk_receipts[1]["baseline_tree_bytes"], 8);
    assert_eq!(
        disk_receipts[2]["aggregate_declared_maximum_duration_ms"],
        500
    );
    assert_eq!(disk_receipts[2]["maximum_aggregate_duration_ms"], 1_000);
    assert!(disk_receipts[0]["claim_boundary"]
        .as_str()
        .unwrap()
        .contains("not_os_wide_write_quota"));

    assert_eq!(
        Connection::open(root.join("ember-lab.sqlite3"))
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM job_disk_walls WHERE job_id='dispatch-v5-disk-wall'",
                [],
                |row| row.get::<_, i64>(0),
            )
            .unwrap(),
        2
    );
    daemon.stop_job("dispatch-v5-disk-wall").unwrap();
}

#[test]
fn v5_manifest_refuses_missing_roots_and_overbudget_aggregate_measurement() {
    for (name, wall_count, create_roots, expected_detail) in [
        ("missing-root", 1_usize, false, "must exist at admission"),
        (
            "aggregate-cap",
            5_usize,
            true,
            "explicit resource declarations",
        ),
    ] {
        let root = sandbox(name);
        let manifest = write_manifest(&root, &format!("dispatch-v5-{name}"), 10_000);
        let root_text = root.to_string_lossy();
        let volume_root = PathBuf::from(format!(r"{}\", &root_text[..2]));
        let walls = (0..wall_count)
            .map(|index| {
                let write_root = root.join(format!("disk-wall-{index}"));
                if create_roots {
                    fs::create_dir(&write_root).unwrap();
                }
                json!({
                    "volume_root":volume_root,
                    "write_root":write_root,
                    "maximum_write_bytes":100 * 1024 * 1024_u64,
                    "minimum_free_bytes":1,
                    "sample_interval_ms":2_000,
                    "maximum_measurement_duration_ms":250
                })
            })
            .collect::<Vec<_>>();
        let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        payload["schema_version"] = json!("ember-lab-dispatch-manifest-v5");
        payload
            .as_object_mut()
            .unwrap()
            .remove("minimum_free_vram_bytes");
        payload["vram_wall"] = json!({"applicability":"not_applicable"});
        payload["disk_write_walls"] = json!(walls);
        fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();

        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
        let error = daemon
            .dispatch_manifest_v4_at_with_device_probe_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024 * 1024 * 1024),
                |_contract| panic!("evidence verifier v5 must not probe a GPU"),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            )
            .unwrap_err();
        assert!(
            error.to_string().contains(expected_detail),
            "unexpected refusal for {name}: {error}"
        );
        assert_eq!(
            daemon.job_state(&format!("dispatch-v5-{name}")).unwrap(),
            None
        );
    }
}

#[test]
fn dispatch_manifest_rejects_unknown_fields_and_cache_escape() {
    let root = sandbox("closed");
    let manifest = write_manifest(&root, "dispatch-closed", 10_000);
    let mut payload: Value = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
    payload["unknown"] = json!(true);
    fs::write(&manifest, serde_json::to_vec(&payload).unwrap()).unwrap();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
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
        .join("ember-lab.sqlite3.logs")
        .join("dispatch-manifests")
        .join(format!("{manifest_sha256}.json"));
    fs::create_dir_all(custody_snapshot.parent().unwrap()).unwrap();
    fs::write(&custody_snapshot, b"{\"attacker\":true}").unwrap();

    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_bytes_at_with_probes_and_host(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();

    assert!(matches!(
        daemon.dispatch_manifest_bytes_at_with_probes_and_host(
            &manifest_bytes,
            &manifest_sha256,
            10_001,
            |_root| Ok(1024),
            || Ok(1024),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
    ));
    assert!(!unapproved.exists());
    assert!(!root
        .join("ember-lab.sqlite3.logs")
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
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
            Err(EmberLabError::DispatchHostCommitReserve { .. })
        ));
    }
    let snapshots = root
        .join("ember-lab.sqlite3.logs")
        .join("dispatch-manifests");
    let count = fs::read_dir(&snapshots).unwrap().count();
    assert_eq!(count, 64);
}
#[test]
fn duplicate_snapshot_at_capacity_preserves_every_unrelated_snapshot() {
    let root = sandbox("duplicate-snapshot-capacity");
    let manifest = write_manifest(&root, "dispatch-duplicate-snapshot", 10_000);
    let duplicate_bytes = fs::read(&manifest).unwrap();
    let duplicate_digest = format!("{:x}", Sha256::digest(&duplicate_bytes));
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let snapshots = root
        .join("ember-lab.sqlite3.logs")
        .join("dispatch-manifests");
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
        Err(EmberLabError::DispatchHostCommitReserve { .. })
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
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    assert!(matches!(
        daemon.dispatch_manifest_at_with_probes_and_host(
            &manifest,
            10_001,
            |_root| Ok(1024),
            || Ok(2048),
            || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES))
        ),
        Err(EmberLabError::InvalidDispatchManifest { .. })
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
        Err(EmberLabError::InvalidDispatchManifest { .. })
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
        Err(EmberLabError::DispatchStorageReserve { .. })
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
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
        assert!(matches!(
            daemon.dispatch_manifest_at_with_probes_and_host(
                &manifest,
                10_001,
                |_root| Ok(1024),
                || Ok(1024),
                || Ok(host_capacity(DECLARED_AVAILABLE_MAXIMUM_COMMIT_BYTES)),
            ),
            Err(EmberLabError::InvalidDispatchManifest { .. })
        ));
        assert_eq!(daemon.job_state(&format!("dispatch-{name}")).unwrap(), None);
        assert!(!root.join("custody").join("preflight.json").exists());
    }
}
