// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! The hour job class (issue #2119, Relates only): `start_hour` runs an already-derived lineage hour dispatch script
//! (`hNN_dispatch_vN.sh`) as a lab JOB instead of a detached child of the cockpit.
//!
//! It keeps the exact contract of the cockpit's `/resume-hour` (ember-cli `commands/resume-hour.ts`, shared golden
//! fixture `resume-hour-contract.json`): the script's name, its exact sha256, a log that does not exist yet, a pinned
//! Git bash (never the System32 shim), and an environment that carries no `EMBER_*` variable. What the lab adds: the
//! hour is a durable job row (state, events, exit code, lease `hour-chain`), it survives a daemon crash, and a restarted
//! daemon re-adopts it (`adopt_job`).
//!
//! What the class does NOT do, on purpose: it injects nothing into the environment (the child sees exactly the map the
//! caller sent), it persists only a fingerprint of that environment (never the values), it sets no
//! KILL_ON_JOB_CLOSE (a detached chain keeps its descendants when the main process exits), and it refuses to start from a
//! hour whose child is not at Normal priority on every CPU the host has (the cockpit never gave it less): the child is
//! created with an explicit NORMAL class and the full system CPU mask, proved by readback before it runs.

use super::{hash_bytes, now_ms, Daemon, DispatchWindowContract, EmberLabError, JobSpec, Result};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

/// The log redirect bash runs; identical to ember-cli's `REDIRECT` (`exec bash "$0" >>"$1" 2>&1`).
pub const REDIRECT: &str = "exec bash \"$0\" >>\"$1\" 2>&1";
/// The lease every hour job takes: one hour chain at a time.
pub const HOUR_RESOURCE: &str = "hour-chain";
pub const START_RECEIPT_SCHEMA: &str = "ember-lab-hour-start-v1";

/// Stable refusal codes and their distinct process exit codes (the `start-hour` CLI exits with `rc`; success is 0).
pub const REFUSAL_CODES: &[(&str, u8)] = &[
    ("hour_path_relative", 20),
    ("hour_script_name", 21),
    ("hour_script_missing", 22),
    ("hour_sha_malformed", 23),
    ("hour_sha_mismatch", 24),
    ("hour_log_exists", 25),
    ("hour_log_unwritable", 26),
    ("hour_bash_refused", 27),
    ("hour_env_ember_key", 28),
    ("hour_env_invalid", 29),
    ("hour_child_priority", 30),
    ("hour_child_affinity", 31),
    ("hour_lease_conflict", 32),
    ("hour_receipt_exists", 33),
    ("hour_receipt_write", 34),
    ("hour_spawn_failed", 35),
    ("hour_cwd_invalid", 36),
];

pub fn refusal_rc(code: &str) -> u8 {
    REFUSAL_CODES
        .iter()
        .find(|(name, _)| *name == code)
        .map_or(99, |(_, rc)| *rc)
}

fn refuse(code: &'static str, detail: impl Into<String>) -> EmberLabError {
    EmberLabError::HourRefused {
        code: code.into(),
        rc: refusal_rc(code),
        detail: detail.into(),
    }
}

/// Working directory the hour child starts in (the cockpit's cwd for a `/resume-hour`).
#[derive(Clone, Debug)]
pub(crate) struct HourChainSpec {
    pub cwd: Option<PathBuf>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HourStartRequest {
    /// Absolute path of the `hNN_dispatch_vN.sh` script.
    pub script: PathBuf,
    /// Expected sha256 of the script's bytes (64 lowercase hex).
    pub sha256: String,
    /// Absolute path of the log; it must not exist (one start per log).
    pub log: PathBuf,
    /// The child's working directory (absolute, an existing directory). Omitted: the daemon's own.
    #[serde(default)]
    pub cwd: Option<PathBuf>,
    /// The child's pinned Git bash. Omitted: `C:/Program Files/Git/bin/bash.exe` on Windows, `/bin/bash` elsewhere.
    #[serde(default)]
    pub bash: Option<PathBuf>,
    /// The child's EXACT environment (the caller's environment minus every `EMBER_*`).
    pub env: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HourStarted {
    pub job_id: String,
    pub pid: u32,
    pub script: PathBuf,
    pub sha256: String,
    pub log: PathBuf,
    pub receipt_path: PathBuf,
    pub bash: PathBuf,
    pub cwd: Option<PathBuf>,
}

impl HourStarted {
    /// The one machine-readable line printed on a successful start.
    pub fn line(&self) -> String {
        format!(
            "START_HOUR_OK pid={} job_id={} log={} receipt={}",
            self.pid,
            self.job_id,
            self.log.display(),
            self.receipt_path.display()
        )
    }
}

struct Checked {
    script: PathBuf,
    sha256: String,
    log: PathBuf,
    bash: PathBuf,
    cwd: Option<PathBuf>,
    env: BTreeMap<String, String>,
}

/// `^h\d+_dispatch_v\d+\.sh$` (ASCII digits), the same name rule as the cockpit's `DISPATCH_NAME`.
pub fn dispatch_name_ok(name: &str) -> bool {
    let Some(rest) = name.strip_prefix('h') else {
        return false;
    };
    let first = rest.bytes().take_while(u8::is_ascii_digit).count();
    if first == 0 {
        return false;
    }
    let Some(rest) = rest[first..].strip_prefix("_dispatch_v") else {
        return false;
    };
    let second = rest.bytes().take_while(u8::is_ascii_digit).count();
    second > 0 && &rest[second..] == ".sh"
}

/// `/^[0-9a-f]{64}$/` (the cockpit's expected-sha256 shape).
pub fn sha_well_formed(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `/^EMBER_/i` on a variable name.
pub fn is_ember_key(key: &str) -> bool {
    let bytes = key.as_bytes();
    bytes.len() >= 6 && bytes[..6].eq_ignore_ascii_case(b"EMBER_")
}

/// The cockpit's `hourEnv`: every variable except the `EMBER_*` ones.
pub fn hour_env<I: IntoIterator<Item = (String, String)>>(env: I) -> BTreeMap<String, String> {
    env.into_iter()
        .filter(|(key, _)| !is_ember_key(key))
        .collect()
}

/// Pinned-bash rule of `resolveHourBash`: the System32 shim is refused; on Windows the file must exist.
pub fn bash_refusal(candidate: &Path) -> Option<String> {
    let mut text = candidate
        .to_string_lossy()
        .replace('\\', "/")
        .to_ascii_lowercase();
    while text.contains("//") {
        text = text.replace("//", "/");
    }
    if text.ends_with("system32/bash.exe") {
        return Some("the System32 bash shim is refused".into());
    }
    if !candidate.is_absolute() {
        return Some("bash must be an absolute path".into());
    }
    if cfg!(windows) && !candidate.is_file() {
        return Some(format!("bash not found: {}", candidate.display()));
    }
    None
}

fn default_bash() -> PathBuf {
    if cfg!(windows) {
        PathBuf::from("C:/Program Files/Git/bin/bash.exe")
    } else {
        PathBuf::from("/bin/bash")
    }
}

fn env_invalid(env: &BTreeMap<String, String>) -> Option<String> {
    if env.is_empty() {
        return Some("environment is empty".into());
    }
    for (key, value) in env {
        if key.is_empty() || key.contains('=') || key.contains('\0') || value.contains('\0') {
            return Some(format!("malformed environment entry {key:?}"));
        }
    }
    if !env.keys().any(|key| key.eq_ignore_ascii_case("PATH")) {
        return Some("environment carries no PATH".into());
    }
    None
}

/// Fingerprint of an environment: sha256 over its sorted `KEY=VALUE\n` lines.
pub fn env_sha256(env: &BTreeMap<String, String>) -> String {
    let mut hasher = Sha256::new();
    for (key, value) in env {
        hasher.update(key.as_bytes());
        hasher.update(b"=");
        hasher.update(value.as_bytes());
        hasher.update(b"\n");
    }
    format!("{:x}", hasher.finalize())
}

/// What the lab persists about an hour's environment: a fingerprint and a count, never the values.
pub(crate) fn env_summary(env: &BTreeMap<String, String>) -> BTreeMap<String, String> {
    BTreeMap::from([
        ("hour_env_sha256".to_string(), env_sha256(env)),
        ("hour_env_key_count".to_string(), env.len().to_string()),
    ])
}

fn check_request(request: &HourStartRequest) -> Result<Checked> {
    if !request.script.is_absolute() || !request.log.is_absolute() {
        return Err(refuse(
            "hour_path_relative",
            "script and log must be absolute paths",
        ));
    }
    let name = request
        .script
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    if !dispatch_name_ok(&name) {
        return Err(refuse(
            "hour_script_name",
            format!("not an hour dispatch script name (hNN_dispatch_vN.sh): {name}"),
        ));
    }
    if !request.script.is_file() {
        return Err(refuse(
            "hour_script_missing",
            format!("dispatch script not found: {}", request.script.display()),
        ));
    }
    let expected = &request.sha256;
    if !sha_well_formed(expected) {
        return Err(refuse(
            "hour_sha_malformed",
            "expected sha256 must be 64 lowercase hex",
        ));
    }
    let bytes = fs::read(&request.script)
        .map_err(|error| refuse("hour_script_missing", format!("script unreadable: {error}")))?;
    let actual = hash_bytes(&bytes);
    if &actual != expected {
        return Err(refuse(
            "hour_sha_mismatch",
            format!("dispatch script sha256 {actual} is not the expected {expected}"),
        ));
    }
    if request.log.exists() {
        return Err(refuse(
            "hour_log_exists",
            format!(
                "log already exists (one start per log): {}",
                request.log.display()
            ),
        ));
    }
    let bash = request.bash.clone().unwrap_or_else(default_bash);
    if let Some(reason) = bash_refusal(&bash) {
        return Err(refuse("hour_bash_refused", reason));
    }
    if let Some(key) = request.env.keys().find(|key| is_ember_key(key)) {
        return Err(refuse(
            "hour_env_ember_key",
            format!("the hour environment carries an EMBER_* variable: {key}"),
        ));
    }
    if let Some(reason) = env_invalid(&request.env) {
        return Err(refuse("hour_env_invalid", reason));
    }
    if let Some(cwd) = request.cwd.as_ref() {
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(refuse(
                "hour_cwd_invalid",
                format!(
                    "cwd is not an absolute existing directory: {}",
                    cwd.display()
                ),
            ));
        }
    }
    Ok(Checked {
        script: request.script.clone(),
        sha256: actual,
        log: request.log.clone(),
        bash,
        cwd: request.cwd.clone(),
        env: request.env.clone(),
    })
}

pub const NORMAL_PRIORITY_CLASS: u32 = 0x0000_0020;

/// RISK 1: the hour child must be at NORMAL priority on every CPU the system has, whatever the daemon was started with
/// (a daemon launched from a below-normal lane, or pinned to a subset of CPUs, must not slow the hour).
pub fn child_cpu_refusal(
    priority_class: u32,
    process_mask: usize,
    system_mask: usize,
) -> Option<EmberLabError> {
    if priority_class != NORMAL_PRIORITY_CLASS {
        return Some(refuse(
            "hour_child_priority",
            format!("hour child priority class is {priority_class:#x}, not NORMAL (0x20)"),
        ));
    }
    if process_mask != system_mask {
        return Some(refuse(
            "hour_child_affinity",
            format!("hour child CPU mask {process_mask:#x} is not the full system mask {system_mask:#x}"),
        ));
    }
    None
}

/// Set the suspended child's CPU mask to the full system mask, then read priority and mask back and refuse unless both hold.
#[cfg(windows)]
pub(crate) fn enforce_child_cpu(process: windows_sys::Win32::Foundation::HANDLE) -> Result<()> {
    use windows_sys::Win32::System::Threading::{
        GetPriorityClass, GetProcessAffinityMask, SetProcessAffinityMask,
    };
    let (_, _, system_mask) = daemon_inherit_snapshot()?;
    if unsafe { SetProcessAffinityMask(process, system_mask) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let (mut process_mask, mut readback_system) = (0usize, 0usize);
    let priority = unsafe { GetPriorityClass(process) };
    if priority == 0
        || unsafe { GetProcessAffinityMask(process, &mut process_mask, &mut readback_system) } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    match child_cpu_refusal(priority, process_mask, readback_system) {
        Some(refusal) => Err(refusal),
        None => Ok(()),
    }
}

#[cfg(windows)]
fn daemon_inherit_snapshot() -> Result<(u32, usize, usize)> {
    use windows_sys::Win32::System::Threading::{
        GetCurrentProcess, GetPriorityClass, GetProcessAffinityMask,
    };
    let (mut process_mask, mut system_mask) = (0usize, 0usize);
    let process = unsafe { GetCurrentProcess() };
    let priority = unsafe { GetPriorityClass(process) };
    if priority == 0
        || unsafe { GetProcessAffinityMask(process, &mut process_mask, &mut system_mask) } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok((priority, process_mask, system_mask))
}

#[cfg(not(windows))]
fn daemon_inherit_snapshot() -> Result<(u32, usize, usize)> {
    Ok((NORMAL_PRIORITY_CLASS, 0, 0))
}

fn create_new(path: &Path) -> std::io::Result<fs::File> {
    OpenOptions::new().write(true).create_new(true).open(path)
}

impl Daemon {
    /// Start one hour dispatch script as a lab job. Every check refuses with its own `HourRefused { code, rc }`
    /// before anything is created; the start receipt (`<log>.lab-start.json`) exists before this returns.
    pub fn start_hour(&self, request: HourStartRequest) -> Result<HourStarted> {
        let checked = check_request(&request)?;
        // The daemon's own priority and CPU mask are receipted as covariates; the child gets NORMAL / full mask regardless.
        let (priority, process_mask, system_mask) = daemon_inherit_snapshot()?;
        let job_id = format!(
            "hour-{}-{}",
            &checked.sha256[..12],
            &hash_bytes(checked.log.to_string_lossy().as_bytes())[..8]
        );
        self.bind_identity(&job_id, &checked.script, &checked.sha256)?;
        match self.acquire_lease(HOUR_RESOURCE, &job_id) {
            Ok(()) => {}
            Err(EmberLabError::LeaseConflict { owner, .. }) => {
                return Err(refuse(
                    "hour_lease_conflict",
                    format!("another hour chain holds the lease: {owner}"),
                ));
            }
            Err(other) => return Err(other),
        }
        let release = |daemon: &Daemon| {
            let _ = daemon.release_lease(HOUR_RESOURCE, &job_id);
        };
        // The log is created first (as the cockpit does), then the start receipt, both create-new.
        if let Err(error) = create_new(&checked.log) {
            release(self);
            return Err(if error.kind() == std::io::ErrorKind::AlreadyExists {
                refuse(
                    "hour_log_exists",
                    format!("log already exists: {}", checked.log.display()),
                )
            } else {
                refuse(
                    "hour_log_unwritable",
                    format!("{}: {error}", checked.log.display()),
                )
            });
        }
        let receipt_path =
            PathBuf::from(format!("{}.lab-start.json", checked.log.to_string_lossy()));
        let base = json!({
            "schema": START_RECEIPT_SCHEMA,
            "job_id": job_id,
            "script": checked.script,
            "sha256": checked.sha256,
            "log": checked.log,
            "bash": checked.bash,
            "cwd": checked.cwd,
            "redirect": REDIRECT,
            "env_key_count": checked.env.len(),
            "env_sha256": env_sha256(&checked.env),
            "daemon_pid": std::process::id(),
            "daemon_priority_class": priority,
            "daemon_affinity_mask": process_mask,
            "daemon_system_mask": system_mask,
            "intent_at_ms": now_ms(),
        });
        let mut intent = base.clone();
        intent["phase"] = json!("intent");
        match create_new(&receipt_path) {
            Ok(mut file) => {
                if let Err(error) = file
                    .write_all(serde_json::to_string_pretty(&intent)?.as_bytes())
                    .and_then(|_| file.sync_all())
                {
                    release(self);
                    return Err(refuse(
                        "hour_receipt_write",
                        format!("{}: {error}", receipt_path.display()),
                    ));
                }
            }
            Err(error) => {
                release(self);
                return Err(if error.kind() == std::io::ErrorKind::AlreadyExists {
                    refuse("hour_receipt_exists", receipt_path.display().to_string())
                } else {
                    refuse(
                        "hour_receipt_write",
                        format!("{}: {error}", receipt_path.display()),
                    )
                });
            }
        }
        let mut spec = JobSpec::new(
            job_id.clone(),
            checked.bash.to_string_lossy(),
            [
                "-c".to_string(),
                REDIRECT.to_string(),
                checked.script.to_string_lossy().into_owned(),
                checked.log.to_string_lossy().into_owned(),
            ],
            HOUR_RESOURCE,
        )
        .with_requires_ui_responsiveness(true)
        .with_window_contract(DispatchWindowContract::CockpitHosted)
        .with_hour_chain(HourChainSpec {
            cwd: checked.cwd.clone(),
        });
        spec.env = checked.env.clone();
        let handle = match self.start_job(spec) {
            Ok(handle) => handle,
            Err(refusal @ EmberLabError::HourRefused { .. }) => {
                release(self);
                return Err(refusal);
            }
            Err(error) => {
                release(self);
                return Err(refuse("hour_spawn_failed", format!("{error:?}")));
            }
        };
        let mut complete = base;
        complete["phase"] = json!("started");
        complete["pid"] = json!(handle.pid);
        complete["started_at_ms"] = json!(now_ms());
        fs::write(&receipt_path, serde_json::to_string_pretty(&complete)?).map_err(|error| {
            refuse(
                "hour_receipt_write",
                format!(
                    "hour {job_id} is RUNNING (pid {}); completing {} failed: {error}",
                    handle.pid,
                    receipt_path.display()
                ),
            )
        })?;
        Ok(HourStarted {
            job_id,
            pid: handle.pid,
            script: checked.script,
            sha256: checked.sha256,
            log: checked.log,
            receipt_path,
            bash: checked.bash,
            cwd: checked.cwd,
        })
    }

    /// Events of one job after `after_seq` (exclusive), oldest first, at most `limit` (clamped to 1000).
    pub fn job_events(&self, job_id: &str, after_seq: i64, limit: u32) -> Result<Vec<Value>> {
        let conn = self.conn()?;
        let mut statement = conn.prepare(
            "SELECT seq,ts_ms,kind,payload_json FROM events WHERE job_id=?1 AND seq>?2 ORDER BY seq LIMIT ?3",
        )?;
        let rows = statement.query_map(params![job_id, after_seq, limit.min(1000)], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
            ))
        })?;
        let mut events = Vec::new();
        for row in rows {
            let (seq, ts_ms, kind, payload) = row?;
            let payload = serde_json::from_str::<Value>(&payload).unwrap_or(Value::String(payload));
            events.push(json!({"seq": seq, "ts_ms": ts_ms, "kind": kind, "payload": payload}));
        }
        Ok(events)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dispatch_names_follow_the_cockpit_rule() {
        for ok in [
            "h49_dispatch_v2.sh",
            "h1_dispatch_v10.sh",
            "h0_dispatch_v0.sh",
        ] {
            assert!(dispatch_name_ok(ok), "{ok}");
        }
        for bad in [
            "h_dispatch_v1.sh",
            "h49_dispatch_v.sh",
            "h49_dispatch_v1.sh.bak",
            "H49_dispatch_v1.sh",
            "xh49_dispatch_v1.sh",
            "h49_dispatch_v1.sh ",
            "h49_dispatch_v1.bash",
            "chain_segment_H49_v1.sh",
            "h49-dispatch-v1.sh",
            "h٤٩_dispatch_v1.sh",
            "",
        ] {
            assert!(!dispatch_name_ok(bad), "{bad:?}");
        }
    }

    #[test]
    fn ember_keys_are_matched_case_insensitively() {
        assert!(is_ember_key("EMBER_API_KEY"));
        assert!(is_ember_key("ember_startup_resume_hour"));
        assert!(is_ember_key("Ember_X"));
        assert!(!is_ember_key("EMBER"));
        assert!(!is_ember_key("EMBERS_X"));
        assert!(!is_ember_key("PATH"));
        assert!(!is_ember_key("XEMBER_X"));
    }

    #[test]
    fn hour_env_drops_only_ember_variables() {
        let env = hour_env([
            ("PATH".to_string(), "p".to_string()),
            ("EMBER_API_KEY".to_string(), "k".to_string()),
            ("Ember_model_seat".to_string(), "s".to_string()),
            ("HOME".to_string(), "h".to_string()),
        ]);
        assert_eq!(env.keys().cloned().collect::<Vec<_>>(), ["HOME", "PATH"]);
    }

    #[test]
    fn system32_bash_is_refused_in_every_spelling() {
        for shim in [
            "C:\\Windows\\System32\\bash.exe",
            "c:/windows/system32/bash.exe",
            "C:/WINDOWS/SYSTEM32//bash.exe",
        ] {
            assert!(bash_refusal(Path::new(shim)).is_some(), "{shim}");
        }
    }

    #[test]
    fn refusal_codes_are_distinct_and_stable() {
        let mut rcs = REFUSAL_CODES.iter().map(|(_, rc)| *rc).collect::<Vec<_>>();
        let mut names = REFUSAL_CODES
            .iter()
            .map(|(name, _)| *name)
            .collect::<Vec<_>>();
        rcs.sort_unstable();
        rcs.dedup();
        names.sort_unstable();
        names.dedup();
        assert_eq!(rcs.len(), REFUSAL_CODES.len());
        assert_eq!(names.len(), REFUSAL_CODES.len());
        assert!(REFUSAL_CODES.iter().all(|(_, rc)| (20..=36).contains(rc)));
        assert_eq!(refusal_rc("hour_sha_mismatch"), 24);
        assert_eq!(refusal_rc("not_a_code"), 99);
    }

    #[test]
    fn child_cpu_refusal_names_priority_and_mask() {
        assert!(child_cpu_refusal(NORMAL_PRIORITY_CLASS, 0xFFFF, 0xFFFF).is_none());
        let priority = child_cpu_refusal(0x4000, 0xFFFF, 0xFFFF).unwrap();
        assert!(
            matches!(&priority, EmberLabError::HourRefused { code, rc: 30, .. } if code == "hour_child_priority")
        );
        let mask = child_cpu_refusal(NORMAL_PRIORITY_CLASS, 0xFF, 0xFFFF).unwrap();
        assert!(
            matches!(&mask, EmberLabError::HourRefused { code, rc: 31, .. } if code == "hour_child_affinity")
        );
    }

    #[test]
    fn the_persisted_environment_summary_holds_no_values() {
        let env = BTreeMap::from([
            ("PATH".to_string(), "secret-path".to_string()),
            ("TOKEN".to_string(), "secret-token".to_string()),
        ]);
        let summary = env_summary(&env);
        assert_eq!(summary.len(), 2);
        assert!(summary.values().all(|value| !value.contains("secret")));
        assert_eq!(summary["hour_env_key_count"], "2");
        assert_eq!(summary["hour_env_sha256"], env_sha256(&env));
    }
}
