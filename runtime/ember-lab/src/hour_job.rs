// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! The hour job class (issue #2119, Relates only): `start_hour` runs an already-derived lineage hour dispatch script
//! (`hNN_dispatch_vN.sh`) as a lab JOB instead of a detached child of the cockpit.
//!
//! Job kinds (lead ruling 82485, #2453): the request's `kind` is `hour` (the default, the lineage hour above) or `learn` (a LEARN
//! job, script `learn_<name>.sh`, job id prefix `learn-`). Both take the one `hour-chain` lease, so the shared card runs one job at
//! a time, and both get the same events, stop and re-adoption. `check_hour` runs the same checks as `start_hour` and creates nothing.
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
    ("hour_kind_unknown", 37),
];

/// What a lab job of this class is. Both kinds run a sha-pinned bash script under the one `hour-chain` lease (one job at a
/// time on the shared card); they differ in the script-name rule and the job id prefix. `hour` is the lineage hour
/// (`hNN_dispatch_vN.sh`, unchanged); `learn` is a LEARN job (`learn_<name>.sh`, issue #2453).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JobKind {
    Hour,
    Learn,
}

impl JobKind {
    pub fn parse(text: &str) -> Option<JobKind> {
        match text {
            "hour" => Some(JobKind::Hour),
            "learn" => Some(JobKind::Learn),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            JobKind::Hour => "hour",
            JobKind::Learn => "learn",
        }
    }

    /// The job id prefix (`hour-<sha12>-<log8>` or `learn-<sha12>-<log8>`).
    pub fn job_prefix(self) -> &'static str {
        self.as_str()
    }

    pub fn name_ok(self, name: &str) -> bool {
        match self {
            JobKind::Hour => dispatch_name_ok(name),
            JobKind::Learn => learn_name_ok(name),
        }
    }

    fn name_rule(self) -> &'static str {
        match self {
            JobKind::Hour => "hNN_dispatch_vN.sh",
            JobKind::Learn => "learn_<name>.sh",
        }
    }
}

fn default_kind() -> String {
    JobKind::Hour.as_str().to_string()
}

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
    /// Job kind: `hour` (default, the lineage hour) or `learn` (a LEARN job). Anything else is refused `hour_kind_unknown`.
    #[serde(default = "default_kind")]
    pub kind: String,
    /// Absolute path of the `hNN_dispatch_vN.sh` script (kind hour) or `learn_<name>.sh` script (kind learn).
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
    #[serde(default = "default_kind")]
    pub kind: String,
    pub job_id: String,
    pub pid: u32,
    pub script: PathBuf,
    pub sha256: String,
    pub log: PathBuf,
    pub receipt_path: PathBuf,
    pub bash: PathBuf,
    pub cwd: Option<PathBuf>,
    /// False when the child is RUNNING but the `phase: started` receipt could not be written (the `intent` receipt stays on disk).
    /// The start still SUCCEEDED: the hour is live and `job_id`/`pid` are the handle to it, so a refusal here would invite a retry.
    #[serde(default = "default_receipt_complete")]
    pub receipt_complete: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receipt_error: Option<String>,
    /// Set when `start_job` returned an error AFTER the child was resumed and `running` was committed (lead review 82583 S1). The hour
    /// is live and its `hour-chain` lease is KEPT; this text names the job id, pid and the error. Never a refusal: a refusal would
    /// free the lease and let a second hour start next to a live one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub start_tail_error: Option<String>,
}

fn default_receipt_complete() -> bool {
    true
}

impl HourStarted {
    /// The one machine-readable line printed on a successful start. A running hour whose receipt is incomplete says so on the
    /// same line (`receipt_incomplete=<error>`) and still returns success, because the child exists.
    pub fn line(&self) -> String {
        let incomplete = match (&self.receipt_error, self.receipt_complete) {
            (Some(error), _) => format!(" receipt_incomplete={}", error.replace(['\r', '\n'], " ")),
            (None, false) => " receipt_incomplete=unknown".to_string(),
            (None, true) => String::new(),
        };
        let tail = match &self.start_tail_error {
            Some(error) => format!(" start_tail_error={}", error.replace(['\r', '\n'], " ")),
            None => String::new(),
        };
        format!(
            "START_HOUR_OK pid={} job_id={} log={} receipt={}{}{}",
            self.pid,
            self.job_id,
            self.log.display(),
            self.receipt_path.display(),
            incomplete,
            tail
        )
    }
}

/// What `check_hour` answers: the start would be accepted right now (same checks, nothing created).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HourChecked {
    pub kind: String,
    pub job_id: String,
    pub script: PathBuf,
    pub sha256: String,
    pub log: PathBuf,
    pub receipt_path: PathBuf,
    pub bash: PathBuf,
    pub cwd: Option<PathBuf>,
}

impl HourChecked {
    /// The one machine-readable line printed when a start would be accepted.
    pub fn line(&self) -> String {
        format!(
            "CHECK_HOUR_OK kind={} job_id={} log={} receipt={}",
            self.kind,
            self.job_id,
            self.log.display(),
            self.receipt_path.display()
        )
    }
}

struct Checked {
    kind: JobKind,
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

/// `^learn_[A-Za-z0-9_-]+\.sh$` (ASCII; no path separators, no spaces, no extra extension).
pub fn learn_name_ok(name: &str) -> bool {
    let Some(rest) = name.strip_prefix("learn_") else {
        return false;
    };
    let Some(stem) = rest.strip_suffix(".sh") else {
        return false;
    };
    !stem.is_empty()
        && stem
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
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
    let kind = JobKind::parse(&request.kind).ok_or_else(|| {
        refuse(
            "hour_kind_unknown",
            format!("job kind must be hour or learn, not {:?}", request.kind),
        )
    })?;
    let name = request
        .script
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    if !kind.name_ok(&name) {
        return Err(refuse(
            "hour_script_name",
            format!(
                "not a {} script name ({}): {name}",
                kind.as_str(),
                kind.name_rule()
            ),
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
    // The same two refusals `start_hour` would raise after the lease, raised here so `check_hour` gives the identical verdict.
    if let Some(parent) = request.log.parent() {
        if !parent.as_os_str().is_empty() && !parent.is_dir() {
            return Err(refuse(
                "hour_log_unwritable",
                format!("log directory does not exist: {}", parent.display()),
            ));
        }
    }
    if start_receipt_path(&request.log).exists() {
        return Err(refuse(
            "hour_receipt_exists",
            start_receipt_path(&request.log).display().to_string(),
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
        kind,
        script: request.script.clone(),
        sha256: actual,
        log: request.log.clone(),
        bash,
        cwd: request.cwd.clone(),
        env: request.env.clone(),
    })
}

/// `<log>.lab-start.json`, the start receipt next to the log.
fn start_receipt_path(log: &Path) -> PathBuf {
    PathBuf::from(format!("{}.lab-start.json", log.to_string_lossy()))
}

fn job_id_for(checked: &Checked) -> String {
    format!(
        "{}-{}-{}",
        checked.kind.job_prefix(),
        &checked.sha256[..12],
        &hash_bytes(checked.log.to_string_lossy().as_bytes())[..8]
    )
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

/// Complete the start receipt of a hour that is already RUNNING. `None` = written; `Some(text)` = it could not be, with the job id,
/// pid and path in the text. The caller turns that into a successful `HourStarted { receipt_complete: false }`, never a refusal.
fn complete_receipt(
    receipt_path: &Path,
    complete: &Value,
    job_id: &str,
    pid: u32,
    inject_failure: bool,
) -> Option<String> {
    serde_json::to_string_pretty(complete)
        .map_err(|error| error.to_string())
        .and_then(|text| {
            if inject_failure {
                return Err("injected receipt write failure".to_string());
            }
            fs::write(receipt_path, text).map_err(|error| error.to_string())
        })
        .err()
        .map(|error| {
            format!(
                "hour_receipt_write: hour {job_id} is RUNNING (pid {pid}); completing {} failed: {error}",
                receipt_path.display()
            )
        })
}

fn create_new(path: &Path) -> std::io::Result<fs::File> {
    OpenOptions::new().write(true).create_new(true).open(path)
}

impl Daemon {
    /// Would `start_hour` accept this request right now? Runs the SAME `check_request` (kind, script name, sha, log, bash, env, cwd)
    /// and peeks the `hour-chain` lease; creates nothing (no log, no receipt, no identity, no lease, no process). A caller that
    /// preflights with this and then starts sees the same refusal code on every path the lab itself checks; what only the spawn can
    /// prove (the child's priority and CPU mask readback) is still refused at start.
    pub fn check_hour(&self, request: HourStartRequest) -> Result<HourChecked> {
        let checked = check_request(&request)?;
        if let Some(owner) = self.lease_owner(HOUR_RESOURCE)? {
            return Err(refuse(
                "hour_lease_conflict",
                format!("another hour chain holds the lease: {owner}"),
            ));
        }
        Ok(HourChecked {
            kind: checked.kind.as_str().to_string(),
            job_id: job_id_for(&checked),
            receipt_path: start_receipt_path(&checked.log),
            script: checked.script,
            sha256: checked.sha256,
            log: checked.log,
            bash: checked.bash,
            cwd: checked.cwd,
        })
    }

    /// Start one hour dispatch script as a lab job. Every check refuses with its own `HourRefused { code, rc }`
    /// before anything is created; the start receipt (`<log>.lab-start.json`) exists before this returns.
    pub fn start_hour(&self, request: HourStartRequest) -> Result<HourStarted> {
        let checked = check_request(&request)?;
        // The daemon's own priority and CPU mask are receipted as covariates; the child gets NORMAL / full mask regardless.
        let (priority, process_mask, system_mask) = daemon_inherit_snapshot()?;
        let job_id = job_id_for(&checked);
        self.bind_identity(&job_id, &checked.script, &checked.sha256)?;
        // Exclusive: an identical concurrent start names the SAME job id, and the plain acquire is idempotent for the same owner, so
        // the loser would run on and its failure-path release would delete the winner's lease. `Ok` here means this call inserted it.
        match self.acquire_lease_exclusive(HOUR_RESOURCE, &job_id) {
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
        let receipt_path = start_receipt_path(&checked.log);
        let base = json!({
            "schema": START_RECEIPT_SCHEMA,
            "kind": checked.kind.as_str(),
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
        let mut start_tail_error = None;
        let pid = match self.start_job(spec) {
            Ok(handle) => handle.pid,
            Err(refusal @ EmberLabError::HourRefused { .. }) => {
                release(self);
                return Err(refusal);
            }
            Err(error) => match self.running_pid(&job_id) {
                // The error came after the child was resumed and `running` was committed: the hour is LIVE. Freeing the lease here
                // would let a second hour start on the card beside it, so the lease stays and the start is reported as success.
                Some(pid) => {
                    start_tail_error = Some(format!(
                        "hour_start_tail: hour {job_id} is RUNNING (pid {pid}) and keeps its lease; start_job returned an error after the child was resumed: {error:?}"
                    ));
                    pid
                }
                None => {
                    release(self);
                    return Err(refuse("hour_spawn_failed", format!("{error:?}")));
                }
            },
        };
        let mut complete = base;
        complete["phase"] = json!("started");
        complete["pid"] = json!(pid);
        complete["started_at_ms"] = json!(now_ms());
        if let Some(text) = &start_tail_error {
            complete["start_tail_error"] = json!(text);
        }
        // The child is running. A failure to complete the receipt must NOT turn into a refusal (the caller would retry, or lose the
        // handle): report success carrying job_id/pid and the receipt state, and leave the `intent` receipt on disk.
        let receipt_error = complete_receipt(
            &receipt_path,
            &complete,
            &job_id,
            pid,
            self.take_receipt_write_fault(),
        );
        Ok(HourStarted {
            receipt_complete: receipt_error.is_none(),
            receipt_error,
            start_tail_error,
            kind: checked.kind.as_str().to_string(),
            job_id,
            pid,
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
    fn learn_names_follow_their_own_rule() {
        for ok in [
            "learn_measure_001.sh",
            "learn_a.sh",
            "learn_Run-2_x.sh",
            "learn_0.sh",
        ] {
            assert!(learn_name_ok(ok), "{ok}");
        }
        for bad in [
            "learn_.sh",
            "learn.sh",
            "learn_measure_001.sh.bak",
            "learn_measure 001.sh",
            "learn_measure.001.sh",
            "Learn_measure_001.sh",
            "xlearn_measure_001.sh",
            "learn_measure_001.bash",
            "learn_mesure\u{0664}.sh",
            "h49_dispatch_v1.sh",
            "chain_segment_H49_v1.sh",
            "",
        ] {
            assert!(!learn_name_ok(bad), "{bad:?}");
        }
    }

    #[test]
    fn each_kind_accepts_only_its_own_script_name() {
        assert_eq!(JobKind::parse("hour"), Some(JobKind::Hour));
        assert_eq!(JobKind::parse("learn"), Some(JobKind::Learn));
        for unknown in ["", "Hour", "LEARN", "hour ", "train", "hours"] {
            assert_eq!(JobKind::parse(unknown), None, "{unknown:?}");
        }
        assert!(JobKind::Hour.name_ok("h49_dispatch_v2.sh"));
        assert!(!JobKind::Hour.name_ok("learn_measure_001.sh"));
        assert!(JobKind::Learn.name_ok("learn_measure_001.sh"));
        assert!(!JobKind::Learn.name_ok("h49_dispatch_v2.sh"));
        assert_eq!(JobKind::Hour.job_prefix(), "hour");
        assert_eq!(JobKind::Learn.job_prefix(), "learn");
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
        assert!(REFUSAL_CODES.iter().all(|(_, rc)| (20..=37).contains(rc)));
        assert_eq!(refusal_rc("hour_sha_mismatch"), 24);
        assert_eq!(refusal_rc("hour_kind_unknown"), 37);
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

    #[test]
    fn a_receipt_that_cannot_be_completed_reports_the_job_id_pid_and_path_instead_of_failing_the_start(
    ) {
        let dir = std::env::temp_dir().join(format!("ember-lab-receipt-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let good = dir.join("good.lab-start.json");
        assert!(
            complete_receipt(&good, &json!({"phase": "started"}), "hour-x", 7, false).is_none()
        );
        assert!(fs::read_to_string(&good).unwrap().contains("started"));
        // A directory in place of the receipt file makes the write fail on every platform.
        let bad = dir.join("bad.lab-start.json");
        fs::create_dir_all(&bad).unwrap();
        let error =
            complete_receipt(&bad, &json!({"phase": "started"}), "hour-x", 7, false).unwrap();
        assert!(error.starts_with("hour_receipt_write:"), "{error}");
        assert!(
            error.contains("hour-x") && error.contains("pid 7") && error.contains("RUNNING"),
            "{error}"
        );
        assert!(error.contains(&bad.display().to_string()), "{error}");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_start_line_names_an_incomplete_receipt_and_stays_unchanged_when_complete() {
        let mut started = HourStarted {
            kind: "hour".into(),
            job_id: "hour-aaaaaaaaaaaa-bbbbbbbb".into(),
            pid: 4321,
            script: PathBuf::from("B:/s/h49_dispatch_v2.sh"),
            sha256: "a".repeat(64),
            log: PathBuf::from("B:/l/hour.log"),
            receipt_path: PathBuf::from("B:/l/hour.log.lab-start.json"),
            bash: PathBuf::from("bash.exe"),
            cwd: None,
            receipt_complete: true,
            receipt_error: None,
            start_tail_error: None,
        };
        let complete = started.line();
        assert!(
            complete.starts_with("START_HOUR_OK pid=4321 job_id=hour-aaaaaaaaaaaa-bbbbbbbb "),
            "{complete}"
        );
        assert!(!complete.contains("receipt_incomplete"), "{complete}");
        started.receipt_complete = false;
        started.receipt_error = Some("hour_receipt_write: disk\nfull".into());
        let incomplete = started.line();
        assert!(
            incomplete.starts_with("START_HOUR_OK pid=4321 "),
            "{incomplete}"
        );
        assert!(
            incomplete.ends_with("receipt_incomplete=hour_receipt_write: disk full"),
            "{incomplete}"
        );
        assert!(!incomplete.contains('\n'));
        started.receipt_complete = true;
        started.receipt_error = None;
        started.start_tail_error = Some("hour_start_tail: RUNNING\nkeeps its lease".into());
        let tail = started.line();
        assert!(
            tail.ends_with("start_tail_error=hour_start_tail: RUNNING keeps its lease"),
            "{tail}"
        );
        assert!(!tail.contains('\n'));
        // A result from an older daemon without the new fields reads as complete.
        let old: HourStarted = serde_json::from_value(json!({
            "job_id": "j", "pid": 1, "script": "s", "sha256": "x", "log": "l", "receipt_path": "r", "bash": "b", "cwd": null,
        }))
        .unwrap();
        assert!(
            old.receipt_complete && old.receipt_error.is_none() && old.start_tail_error.is_none()
        );
    }
}
