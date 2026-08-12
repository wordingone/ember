// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use rusqlite::{params, Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::fmt;
use std::fs::{self, OpenOptions};
#[cfg(not(windows))]
use std::io::Read;
use std::io::Write;
use std::path::{Path, PathBuf};
#[cfg(not(windows))]
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
#[cfg(windows)]
use std::sync::{RwLock, Weak};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub mod data_catalog;
pub mod rehearsal;
pub mod rpc;
pub mod scratch;
pub mod server_supervisor;
pub mod training_verify;

pub type Result<T> = std::result::Result<T, EmberLabError>;

/// Largest UTF-8 dispatch-manifest payload that fits the 64 KiB JSON-RPC line envelope even when JSON string escaping doubles every source byte.
pub const MAX_DISPATCH_MANIFEST_BYTES: usize = 30_000;
const CURRENT_DATABASE_SCHEMA_VERSION: u32 = 5;
const DISPATCH_TOKEN_ENV: &str = "EMBER_LAB_DISPATCH_TOKEN";
const DISPATCH_JOB_ID_ENV: &str = "EMBER_LAB_DISPATCH_JOB_ID";
const DISPATCH_DAEMON_PID_ENV: &str = "EMBER_LAB_DISPATCH_DAEMON_PID";
const DISPATCH_TOKEN_BYTES: usize = 32;

pub fn read_data_catalog_status(path: &Path) -> Result<Value> {
    let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    conn.busy_timeout(Duration::from_secs(10))?;
    conn.execute_batch("PRAGMA foreign_keys=ON;")?;
    let schema_version: String = conn.query_row(
        "SELECT value FROM metadata WHERE key='schema_version'",
        [],
        |row| row.get(0),
    )?;
    if schema_version != CURRENT_DATABASE_SCHEMA_VERSION.to_string() {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: format!(
                "read-only data catalog status requires database schema version {CURRENT_DATABASE_SCHEMA_VERSION}, found {schema_version}"
            ),
        });
    }
    data_catalog::status(&conn)
}

pub fn rollback_empty_data_catalog_migration(path: &Path) -> Result<()> {
    let _state_writer_lock = acquire_state_writer_lock(path)?;
    let mut conn = Connection::open(path)?;
    conn.busy_timeout(Duration::from_secs(10))?;
    conn.execute_batch("PRAGMA foreign_keys=ON;")?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let schema_version: String = tx.query_row(
        "SELECT value FROM metadata WHERE key='schema_version'",
        [],
        |row| row.get(0),
    )?;
    if schema_version != CURRENT_DATABASE_SCHEMA_VERSION.to_string() {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: format!(
                "data catalog rollback requires database schema version {CURRENT_DATABASE_SCHEMA_VERSION}, found {schema_version}"
            ),
        });
    }
    let catalog_rows: i64 = tx.query_row(
        "SELECT
             (SELECT COUNT(*) FROM data_catalog_records)
           + (SELECT COUNT(*) FROM data_catalog_edges)
           + (SELECT COUNT(*) FROM data_catalog_imports)",
        [],
        |row| row.get(0),
    )?;
    if catalog_rows != 0 {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: "data catalog rollback refuses after immutable catalog data exists".into(),
        });
    }
    tx.execute_batch(
        "DROP TABLE data_catalog_edges;
         DROP TABLE data_catalog_imports;
         DROP TABLE data_catalog_records;
         UPDATE metadata SET value='4' WHERE key='schema_version';",
    )?;
    tx.commit()?;
    Ok(())
}

#[derive(Debug)]
pub enum EmberLabError {
    Sqlite(rusqlite::Error),
    Io(std::io::Error),
    Json(serde_json::Error),
    InvalidIdentityHash {
        value: String,
    },
    IdentityNotFound {
        job_id: String,
    },
    IdentityMismatch {
        job_id: String,
        expected: String,
        actual: String,
    },
    IdentityAlreadyBound {
        job_id: String,
    },
    LeaseConflict {
        resource: String,
        owner: String,
        requested_by: String,
    },
    LeaseNotOwned {
        resource: String,
        job_id: String,
    },
    JobNotFound {
        job_id: String,
    },
    InvalidTransition {
        job_id: String,
        detail: String,
    },
    ProcessUnavailable {
        job_id: String,
        pid: u32,
    },
    ProcessIdentityMismatch {
        job_id: String,
        pid: u32,
    },
    ProcessControlUncertain {
        job_id: String,
        pid: u32,
        detail: String,
    },
    ReceiptAlreadyExists {
        path: PathBuf,
    },
    DispatchReceiptRecoveryPending {
        job_id: String,
        receipt_path: PathBuf,
    },
    StateWriterBusy {
        path: PathBuf,
    },
    MonitorSetupCleanupFailed {
        job_id: String,
        setup: String,
        cleanup: String,
    },
    PreparedResumeCleanupFailed {
        job_id: String,
        transition: String,
        cleanup: String,
    },
    InvalidPlannedOutage {
        resource: String,
        detail: String,
    },
    InvalidSchedulePrediction {
        job_id: String,
        detail: String,
    },
    SchedulePredictionRequired {
        resource: String,
        job_id: String,
    },
    PlannedOutageActive {
        resource: String,
        ends_at_ms: i64,
        reason: String,
    },
    ReceiptHashCollision {
        path: PathBuf,
    },
    NonTerminalReceipt {
        job_id: String,
        state: String,
    },
    LogEvidenceUnsealed {
        job_id: String,
    },
    LogEvidenceMismatch {
        job_id: String,
        stream: String,
        expected: String,
        actual: String,
    },
    InvalidDispatchManifest {
        detail: String,
    },
    DispatchTooEarly {
        not_before_ms: i64,
        observed_at_ms: i64,
    },
    DispatchExpired {
        expires_at_ms: i64,
        observed_at_ms: i64,
    },
    DispatchBindingMismatch {
        path: PathBuf,
        expected: String,
        actual: String,
    },
    DispatchStorageReserve {
        root: PathBuf,
        minimum_free_bytes: u64,
        available_free_bytes: u64,
    },
    DispatchVramReserve {
        minimum_free_bytes: u64,
        available_free_bytes: u64,
    },
    DispatchHostCommitReserve {
        required_available_maximum_commit_bytes: u64,
        observed_available_maximum_commit_bytes: u64,
        reserve_bytes: u64,
        maximum_job_memory_bytes: u64,
        simulated_peak_commit_bytes: u64,
        receipt_path: PathBuf,
    },
    ResourceAdmissionFrozen {
        reason: String,
        receipt_path: PathBuf,
    },
    DispatchTokenRefused {
        job_id: String,
    },
    InvalidDataCatalog {
        detail: String,
    },
    Poisoned,
}

impl fmt::Display for EmberLabError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for EmberLabError {}
impl From<rusqlite::Error> for EmberLabError {
    fn from(value: rusqlite::Error) -> Self {
        Self::Sqlite(value)
    }
}
impl From<std::io::Error> for EmberLabError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
impl From<serde_json::Error> for EmberLabError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobState {
    Starting,
    Prepared,
    Running,
    Stopping,
    Orphaned,
    IdentityConflict,
    Stopped,
    Exited,
    Failed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostCommitCapacity {
    pub physical_ram_bytes: u64,
    pub physical_available_bytes: u64,
    pub pagefile_maximum_bytes: u64,
    pub pagefile_configuration_source: String,
    pub pagefile_configuration_sha256: String,
    pub commit_total_bytes: u64,
    pub current_commit_limit_bytes: u64,
    pub current_commit_remaining_bytes: u64,
    pub maximum_commit_capacity_bytes: u64,
    pub available_maximum_commit_bytes: u64,
}

impl JobState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Starting => "starting",
            Self::Prepared => "prepared",
            Self::Running => "running",
            Self::Stopping => "stopping",
            Self::Orphaned => "orphaned",
            Self::IdentityConflict => "identity_conflict",
            Self::Stopped => "stopped",
            Self::Exited => "exited",
            Self::Failed => "failed",
        }
    }
    fn parse(value: &str) -> Result<Self> {
        match value {
            "starting" => Ok(Self::Starting),
            "prepared" => Ok(Self::Prepared),
            "running" => Ok(Self::Running),
            "stopping" => Ok(Self::Stopping),
            "orphaned" => Ok(Self::Orphaned),
            "identity_conflict" => Ok(Self::IdentityConflict),
            "stopped" => Ok(Self::Stopped),
            "exited" => Ok(Self::Exited),
            "failed" => Ok(Self::Failed),
            _ => Err(EmberLabError::InvalidTransition {
                job_id: String::new(),
                detail: format!("unknown persisted state {value}"),
            }),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RestartPolicy {
    #[default]
    Never,
}

impl RestartPolicy {
    fn as_str(self) -> &'static str {
        match self {
            Self::Never => "never",
        }
    }

    fn parse(value: &str) -> Result<Self> {
        match value {
            "never" => Ok(Self::Never),
            _ => Err(EmberLabError::InvalidTransition {
                job_id: String::new(),
                detail: format!("unknown restart policy {value}"),
            }),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ReceiptArtifact {
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AssessmentEvidenceArtifact {
    pub schema: String,
    pub preflight_receipt: ReceiptArtifact,
    pub operational_receipt: ReceiptArtifact,
    pub stdout_log: ReceiptArtifact,
    pub stderr_log: ReceiptArtifact,
    pub schedule_alarm_state: ReceiptArtifact,
    pub ember_lab_identity: Value,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchedulePrediction {
    pub job_id: String,
    pub artifact_class: String,
    pub predicted_duration_ms: i64,
    pub predicted_tokens: i64,
    pub predicted_program_completion_ms: i64,
    pub absolute_deadline_ms: i64,
}

#[derive(Clone, Debug)]
pub struct JobSpec {
    job_id: String,
    program: String,
    args: Vec<String>,
    resource_lease: String,
    env: BTreeMap<String, String>,
    restart_policy: RestartPolicy,
    maximum_job_memory_bytes: Option<u64>,
    cpu_rate_percent: Option<u32>,
    dispatch_token: Option<DispatchToken>,
}

#[derive(Clone, Debug)]
struct DispatchToken {
    sha256: String,
    expires_at_ms: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchFileHash {
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchFileBinding {
    pub kind: DispatchBindingKind,
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DispatchBindingKind {
    Config,
    Manifest,
    Input,
    Verifier,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchStorageReserve {
    pub root: PathBuf,
    pub minimum_free_bytes: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DispatchWorkloadProfileId {
    GovernedVertical,
    OwnedServing,
    EvidenceVerifier,
    Cockpit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DispatchPinnedHostProducerKind {
    TrainingDataLoader,
    CheckpointWriter,
    ModelServer,
    ReceiptVerifier,
    TelemetryBuffer,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchPinnedHostProducer {
    pub kind: DispatchPinnedHostProducerKind,
    pub maximum_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchWorkloadProfile {
    pub profile_id: DispatchWorkloadProfileId,
    pub pinned_host_producers: Vec<DispatchPinnedHostProducer>,
    pub requires_ui_responsiveness: bool,
    pub cpu_rate_percent: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchManifest {
    pub schema_version: String,
    pub job_id: String,
    pub source_commit: String,
    pub not_before_ms: i64,
    pub expires_at_ms: i64,
    pub resource_lease: String,
    pub program: DispatchFileHash,
    pub args: Vec<String>,
    pub workload_profile: DispatchWorkloadProfile,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    pub bindings: Vec<DispatchFileBinding>,
    pub custody_root: PathBuf,
    pub storage_reserves: Vec<DispatchStorageReserve>,
    pub minimum_free_vram_bytes: u64,
    pub required_available_maximum_commit_bytes: u64,
    pub maximum_job_memory_bytes: u64,
    pub simulated_peak_commit_bytes: u64,
    pub preflight_receipt: PathBuf,
}

const DISPATCH_HOST_COMMIT_RESERVE_BYTES: u64 = 10 * 1024 * 1024 * 1024;
const RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES: u64 = 8 * 1024 * 1024 * 1024;
const RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES: u64 = 10 * 1024 * 1024 * 1024;
const RESOURCE_GUARD_OBSERVATION_LIMIT: i64 = 1024;
const RESOURCE_GUARD_SAMPLE_INTERVAL_MS: u32 = 2_000;
const PROTECTIVE_CHECKPOINT_REQUEST_ENV: &str = "EMBER_LAB_PROTECTIVE_CHECKPOINT_REQUEST_PATH";
const PROTECTIVE_CHECKPOINT_RESPONSE_ENV: &str = "EMBER_LAB_PROTECTIVE_CHECKPOINT_RESPONSE_PATH";
const PROTECTIVE_CHECKPOINT_MAX_GRACE_MS: u64 = 30_000;
const PROTECTIVE_CHECKPOINT_MONITOR_TOTAL_GRACE_MS: u64 = 5_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchOutcome {
    pub handle: JobHandle,
    pub receipt: ReceiptArtifact,
}

impl JobSpec {
    pub fn new<J, P, I, A, R>(job_id: J, program: P, args: I, resource_lease: R) -> Self
    where
        J: Into<String>,
        P: Into<String>,
        I: IntoIterator<Item = A>,
        A: Into<String>,
        R: Into<String>,
    {
        Self {
            job_id: job_id.into(),
            program: program.into(),
            args: args.into_iter().map(Into::into).collect(),
            resource_lease: resource_lease.into(),
            env: BTreeMap::new(),
            restart_policy: RestartPolicy::Never,
            maximum_job_memory_bytes: None,
            cpu_rate_percent: None,
            dispatch_token: None,
        }
    }
    pub fn with_env<K: Into<String>, V: Into<String>>(mut self, key: K, value: V) -> Self {
        self.env.insert(key.into(), value.into());
        self
    }

    pub fn with_restart_policy(mut self, restart_policy: RestartPolicy) -> Self {
        self.restart_policy = restart_policy;
        self
    }

    pub fn with_maximum_job_memory_bytes(mut self, maximum_job_memory_bytes: u64) -> Self {
        self.maximum_job_memory_bytes = Some(maximum_job_memory_bytes);
        self
    }

    pub fn with_cpu_rate_percent(mut self, cpu_rate_percent: u32) -> Self {
        self.cpu_rate_percent = Some(cpu_rate_percent);
        self
    }

    fn with_dispatch_token(mut self, expires_at_ms: i64) -> Result<Self> {
        let raw = generate_dispatch_token()?;
        self.env.insert(DISPATCH_TOKEN_ENV.into(), raw.clone());
        self.env
            .insert(DISPATCH_JOB_ID_ENV.into(), self.job_id.clone());
        self.env.insert(
            DISPATCH_DAEMON_PID_ENV.into(),
            std::process::id().to_string(),
        );
        self.dispatch_token = Some(DispatchToken {
            sha256: hash_bytes(raw.as_bytes()),
            expires_at_ms,
        });
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct JobHandle {
    pub pid: u32,
}

#[cfg(windows)]
struct OwnedHandle(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
// SAFETY: kernel handles are process-wide values; ownership is unique, and the
// operations used here (wait, duplicate, set, close) are thread-safe.
unsafe impl Send for OwnedHandle {}
#[cfg(windows)]
unsafe impl Sync for OwnedHandle {}

#[cfg(windows)]
impl OwnedHandle {
    fn raw(&self) -> windows_sys::Win32::Foundation::HANDLE {
        self.0
    }
}

#[cfg(windows)]
impl Drop for OwnedHandle {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(self.0) };
        }
    }
}
#[cfg(windows)]
struct LiveProcess {
    job: OwnedHandle,
    process: OwnedHandle,
    _stdout_log_guard: OwnedHandle,
    _stderr_log_guard: OwnedHandle,
    pid: u32,
    identity: ProcessIdentity,
}

#[cfg(windows)]
struct RetainedProcess {
    live: LiveProcess,
    monitored: bool,
}

pub struct Daemon {
    _state_writer_lock: fs::File,
    log_dir: PathBuf,
    db: Arc<Mutex<Connection>>,
    ember_lab_binary_sha256: String,
    ember_lab_source_sha256: String,
    #[cfg(windows)]
    live: Arc<Mutex<HashMap<String, RetainedProcess>>>,
    #[cfg(windows)]
    monitor_shutdown: OwnedHandle,
    #[cfg(windows)]
    monitor_ownership: Arc<RwLock<bool>>,
}

#[cfg(windows)]
#[derive(Clone)]
struct ProtectiveStopContext {
    db: Arc<Mutex<Connection>>,
    live: Arc<Mutex<HashMap<String, RetainedProcess>>>,
    log_dir: PathBuf,
}

#[cfg(windows)]
impl ProtectiveStopContext {
    fn conn(&self) -> Result<std::sync::MutexGuard<'_, Connection>> {
        self.db.lock().map_err(|_| EmberLabError::Poisoned)
    }

    fn frozen_resource_guard(&self) -> Result<Option<Value>> {
        let conn = self.conn()?;
        let status = resource_guard_status_from_connection(&conn)?;
        if status.get("admission_state") == Some(&Value::String("frozen".into())) {
            Ok(Some(status))
        } else {
            Ok(None)
        }
    }

    fn job_process_row(&self, job_id: &str) -> Result<JobProcessRow> {
        let conn = self.conn()?;
        job_process_row_from_connection(&conn, job_id)
    }

    fn finalize_stopped(&self, job_id: &str, row: &JobProcessRow, seal_logs: bool) -> Result<()> {
        let mut conn = self.conn()?;
        finalize_stopped_in_connection(&mut conn, job_id, row, seal_logs)
    }

    #[cfg(windows)]
    fn protective_owned_stop(
        &self,
        job_id: &str,
        checkpoint_grace: Duration,
    ) -> Result<ReceiptArtifact> {
        let grace_ms = u64::try_from(checkpoint_grace.as_millis()).map_err(|_| {
            EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "protective checkpoint grace does not fit u64 milliseconds".into(),
            }
        })?;
        if grace_ms == 0 || grace_ms > PROTECTIVE_CHECKPOINT_MAX_GRACE_MS {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: format!(
                    "protective checkpoint grace must be within 1..={PROTECTIVE_CHECKPOINT_MAX_GRACE_MS} ms"
                ),
            });
        }
        let resource_guard =
            self.frozen_resource_guard()?
                .ok_or_else(|| EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: "protective owned stop requires a frozen resource guard".into(),
                })?;
        let row = self.job_process_row(job_id)?;
        if row.state != JobState::Running {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "protective owned stop requires a running job".into(),
            });
        }
        let lease_matches: bool = self.conn()?.query_row(
            "SELECT EXISTS(
                 SELECT 1 FROM leases
                 WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3
             )",
            params![&row.resource, job_id, row.lease_epoch],
            |record| record.get(0),
        )?;
        if !lease_matches {
            return Err(EmberLabError::LeaseNotOwned {
                resource: row.resource,
                job_id: job_id.into(),
            });
        }
        match open_live_status(&row) {
            LiveStatus::Verified(_) => {}
            LiveStatus::Dead => {
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })
            }
            LiveStatus::Orphaned(detail) | LiveStatus::IdentityConflict(detail) => {
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                })
            }
        }

        let protective_key = hash_bytes(job_id.as_bytes());
        let checkpoint_request_path = self.log_dir.join(format!(
            "{protective_key}.protective-checkpoint-request.json"
        ));
        let checkpoint_response_path = self.log_dir.join(format!(
            "{protective_key}.protective-checkpoint-response.json"
        ));
        let requested_at_ms = now_ms();
        let request = json!({
            "schema_version": "ember-lab-protective-checkpoint-request-v1",
            "job_id": job_id,
            "lease": {
                "resource": &row.resource,
                "owner_job_id": job_id,
                "lease_epoch": row.lease_epoch,
            },
            "process": {
                "pid": row.pid,
                "start_token": &row.start_token,
                "executable_identity_sha256": hash_bytes(row.executable.as_bytes()),
                "job_object_name": &row.job_object_name,
            },
            "requested_at_ms": requested_at_ms,
            "grace_ms": grace_ms,
            "reason": "host_protection_not_causation",
            "response_artifact": checkpoint_response_path.file_name().unwrap().to_string_lossy(),
        });
        let request_bytes = serde_json::to_vec_pretty(&request)?;
        let request_sha256 = hash_bytes(&request_bytes);
        atomic_replace(&checkpoint_request_path, &request_bytes)?;

        let deadline = Instant::now() + checkpoint_grace;
        let mut checkpoint_result = "GRACE_EXPIRED";
        let mut response_sha256 = None;
        while Instant::now() < deadline {
            if checkpoint_response_path.is_file() {
                let response_bytes = fs::read(&checkpoint_response_path)?;
                let response: Value = serde_json::from_slice(&response_bytes)?;
                let valid = response
                    == json!({
                        "schema_version": "ember-lab-protective-checkpoint-response-v1",
                        "job_id": job_id,
                        "request_sha256": request_sha256,
                        "result": "CHECKPOINT_COMPLETED",
                    });
                if valid {
                    checkpoint_result = "CHECKPOINT_COMPLETED";
                    response_sha256 = Some(hash_bytes(&response_bytes));
                    break;
                }
            }
            std::thread::sleep(Duration::from_millis(5));
        }

        let live = match open_live_status(&row) {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead => {
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })
            }
            LiveStatus::Orphaned(detail) | LiveStatus::IdentityConflict(detail) => {
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                })
            }
        };

        {
            let mut conn = self.conn()?;
            let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let changed = tx.execute(
                "UPDATE jobs SET state='stopping',updated_at_ms=?2
                 WHERE job_id=?1 AND state='running' AND lease_epoch=?3
                   AND EXISTS(
                     SELECT 1 FROM leases l
                     WHERE l.resource=jobs.resource
                       AND l.owner_job_id=jobs.job_id
                       AND l.lease_epoch=jobs.lease_epoch
                   )",
                params![job_id, now_ms(), row.lease_epoch],
            )?;
            if changed != 1 {
                return Err(EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: "protective owned stop lost its state or lease fence".into(),
                });
            }
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json)
                 VALUES(?1,?2,'protective_owned_stop_authorizing',?3)",
                params![
                    job_id,
                    now_ms(),
                    json!({
                        "pid": row.pid,
                        "lease_epoch": row.lease_epoch,
                        "checkpoint_request_sha256": request_sha256,
                        "checkpoint_result": checkpoint_result,
                    })
                    .to_string()
                ],
            )?;
            tx.commit()?;
        }

        let decision = json!({
            "schema_version": "ember-lab-protective-owned-stop-v1",
            "result": "PROTECTIVE_OWNED_STOP_AUTHORIZED",
            "reason": "host_protection_not_causation",
            "job_id": job_id,
            "observed_at_ms": now_ms(),
            "resource_guard": resource_guard,
            "lease": {
                "resource": &row.resource,
                "owner_job_id": job_id,
                "lease_epoch": row.lease_epoch,
                "verified": true,
            },
            "process": {
                "pid": row.pid,
                "start_token": &row.start_token,
                "executable_identity_sha256": hash_bytes(row.executable.as_bytes()),
                "job_object_name": &row.job_object_name,
                "identity_verified": true,
                "job_object_membership_verified": true,
            },
            "checkpoint_request": {
                "request_artifact": checkpoint_request_path.file_name().unwrap().to_string_lossy(),
                "request_sha256": request_sha256,
                "response_artifact": response_sha256.as_ref().map(|_| checkpoint_response_path.file_name().unwrap().to_string_lossy()),
                "response_sha256": response_sha256,
                "result": checkpoint_result,
                "grace_ms": grace_ms,
            },
            "termination": {
                "scope": "exact_identity_verified_ember_lab_owned_job_object",
                "foreign_process_control": false,
                "decision_receipt_persisted_before_termination": true,
            },
            "scientific_capability_evidence": false,
        });
        let decision_bytes = serde_json::to_vec_pretty(&decision)?;
        let decision_sha256 = hash_bytes(&decision_bytes);
        let decision_path = self
            .log_dir
            .join(format!("protective-owned-stop-{decision_sha256}.json"));
        let artifact = (|| -> Result<ReceiptArtifact> {
            if decision_path.exists() {
                if fs::read(&decision_path)? != decision_bytes {
                    return Err(EmberLabError::ReceiptHashCollision {
                        path: decision_path.clone(),
                    });
                }
                return Ok(ReceiptArtifact {
                    path: decision_path.clone(),
                    sha256: decision_sha256.clone(),
                });
            }
            match atomic_create(&decision_path, &decision_bytes) {
                Ok(()) => Ok(ReceiptArtifact {
                    path: decision_path.clone(),
                    sha256: decision_sha256.clone(),
                }),
                Err(EmberLabError::ReceiptAlreadyExists { .. })
                    if fs::read(&decision_path)? == decision_bytes =>
                {
                    Ok(ReceiptArtifact {
                        path: decision_path.clone(),
                        sha256: decision_sha256.clone(),
                    })
                }
                Err(EmberLabError::ReceiptAlreadyExists { .. }) => {
                    Err(EmberLabError::ReceiptHashCollision {
                        path: decision_path.clone(),
                    })
                }
                Err(error) => Err(error),
            }
        })();
        let artifact = match artifact {
            Ok(artifact) => artifact,
            Err(error) => {
                let _ = self.conn()?.execute(
                    "UPDATE jobs SET state='running',updated_at_ms=?2
                     WHERE job_id=?1 AND state='stopping' AND lease_epoch=?3
                       AND EXISTS(
                         SELECT 1 FROM leases l
                         WHERE l.resource=jobs.resource
                           AND l.owner_job_id=jobs.job_id
                           AND l.lease_epoch=jobs.lease_epoch
                       )",
                    params![job_id, now_ms(), row.lease_epoch],
                );
                return Err(error);
            }
        };

        self.live
            .lock()
            .map_err(|_| EmberLabError::Poisoned)?
            .remove(job_id);
        if let Err(error) = terminate_live(&live) {
            self.live
                .lock()
                .map_err(|_| EmberLabError::Poisoned)?
                .insert(
                    job_id.into(),
                    RetainedProcess {
                        live,
                        monitored: false,
                    },
                );
            return Err(error);
        }
        self.finalize_stopped(job_id, &row, true)?;
        self.conn()?.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json)
             VALUES(?1,?2,'protective_owned_stop_completed',?3)",
            params![
                job_id,
                now_ms(),
                json!({
                    "decision_receipt": artifact.path.file_name().unwrap().to_string_lossy(),
                    "decision_receipt_sha256": &artifact.sha256,
                })
                .to_string()
            ],
        )?;
        Ok(artifact)
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        #[cfg(windows)]
        {
            if let Ok(mut alive) = self.monitor_ownership.write() {
                *alive = false;
            }
            unsafe { windows_sys::Win32::System::Threading::SetEvent(self.monitor_shutdown.raw()) };
        }
    }
}

/// Column order of `SELECT ... FROM schedule_runs` in `schedule_alarm_state_at`;
/// the tuple field indices below are positional against this alias.
type ScheduleRunRow = (
    String,
    String,
    i64,
    i64,
    i64,
    i64,
    i64,
    String,
    String,
    Option<i64>,
    Option<i64>,
    Option<i64>,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
);

impl Daemon {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let state_writer_lock = acquire_state_writer_lock(path)?;
        let mut log_dir_name = path
            .file_name()
            .unwrap_or_else(|| std::ffi::OsStr::new("ember-lab"))
            .to_os_string();
        log_dir_name.push(".logs");
        let log_dir = path.with_file_name(log_dir_name);
        fs::create_dir_all(&log_dir)?;
        #[cfg(windows)]
        let monitor_shutdown = create_monitor_shutdown()?;
        let mut conn = Connection::open(path)?;
        let ember_lab_binary_sha256 = hash_file(&std::env::current_exe()?)?;
        let ember_lab_source_sha256 = ember_lab_source_hash();
        conn.busy_timeout(Duration::from_secs(10))?;
        conn.execute_batch("PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version','1');
            CREATE TABLE IF NOT EXISTS identities(job_id TEXT PRIMARY KEY, canonical_path TEXT NOT NULL, sha256 TEXT NOT NULL, identity_blob BLOB NOT NULL, bound_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS lease_generations(resource TEXT PRIMARY KEY, generation INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS leases(resource TEXT PRIMARY KEY, owner_job_id TEXT NOT NULL, lease_epoch INTEGER NOT NULL, acquired_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, program TEXT NOT NULL, args_json TEXT NOT NULL, env_json TEXT NOT NULL, resource TEXT NOT NULL, lease_epoch INTEGER NOT NULL, pid INTEGER NOT NULL DEFAULT 0, main_thread_id INTEGER NOT NULL DEFAULT 0, job_object_name TEXT NOT NULL, process_start_token TEXT NOT NULL DEFAULT '', executable_identity TEXT NOT NULL DEFAULT '', argv_sha256 TEXT NOT NULL, state TEXT NOT NULL, restart_policy TEXT NOT NULL DEFAULT 'never', stdout_log_path TEXT NOT NULL, stderr_log_path TEXT NOT NULL, stdout_child_handle INTEGER NOT NULL DEFAULT 0, stderr_child_handle INTEGER NOT NULL DEFAULT 0, stdout_log_sha256 TEXT, stderr_log_sha256 TEXT, outage_event_cutoff_seq INTEGER, exit_code INTEGER, exited_at_ms INTEGER, started_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS schedule_runs(job_id TEXT PRIMARY KEY, artifact_class TEXT NOT NULL, predicted_at_ms INTEGER NOT NULL, predicted_duration_ms INTEGER NOT NULL, predicted_tokens INTEGER NOT NULL, predicted_program_completion_ms INTEGER NOT NULL, absolute_deadline_ms INTEGER NOT NULL, prediction_daemon_binary_sha256 TEXT NOT NULL, prediction_daemon_source_sha256 TEXT NOT NULL, measured_at_ms INTEGER, measured_duration_ms INTEGER, measured_tokens INTEGER, measurement_outcome TEXT, measurement_receipt_sha256 TEXT, measurement_daemon_binary_sha256 TEXT, measurement_daemon_source_sha256 TEXT);
            CREATE TABLE IF NOT EXISTS planned_outages(outage_id INTEGER PRIMARY KEY AUTOINCREMENT, resource TEXT NOT NULL, starts_at_ms INTEGER NOT NULL, ends_at_ms INTEGER NOT NULL, reason TEXT NOT NULL, created_at_ms INTEGER NOT NULL, cancelled_at_ms INTEGER);
            CREATE TABLE IF NOT EXISTS outage_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, resource TEXT NOT NULL, ts_ms INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, ts_ms INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatch_receipt_recovery(job_id TEXT PRIMARY KEY, resource_lease TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, receipt_path TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, receipt_bytes BLOB NOT NULL, created_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatch_preflight_receipts(job_id TEXT PRIMARY KEY, resource_lease TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, receipt_bytes BLOB NOT NULL, created_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatch_tokens(token_sha256 TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, pid INTEGER NOT NULL, program TEXT NOT NULL, argv_sha256 TEXT NOT NULL, expires_at_ms INTEGER NOT NULL, consumed_at_ms INTEGER, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
            CREATE TABLE IF NOT EXISTS resource_guard_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), admission_state TEXT NOT NULL CHECK(admission_state IN ('open','frozen')), reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL CHECK(oracle_evidence_required IN (0,1)), observation_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resource_guard_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
            INSERT OR IGNORE INTO resource_guard_state(singleton,admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json) VALUES(1,'open',NULL,0,0,'{}');")?;
        migrate_schema(&mut conn, &log_dir)?;
        conn.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES('schedule_monitor_started_at_ms',?1)",
            [now_ms().to_string()],
        )?;
        let daemon = Self {
            _state_writer_lock: state_writer_lock,
            log_dir,
            db: Arc::new(Mutex::new(conn)),
            ember_lab_binary_sha256,
            ember_lab_source_sha256,
            #[cfg(windows)]
            live: Arc::new(Mutex::new(HashMap::new())),
            #[cfg(windows)]
            monitor_shutdown,
            #[cfg(windows)]
            monitor_ownership: Arc::new(RwLock::new(true)),
        };
        #[cfg(windows)]
        {
            persist_resource_guard_headroom(
                &*daemon.conn()?,
                now_ms(),
                probe_host_survival_headroom(),
            )?;
            spawn_resource_guard_monitor(
                Arc::downgrade(&daemon.db),
                Arc::downgrade(&daemon.live),
                daemon.log_dir.clone(),
                duplicate_owned_handle(daemon.monitor_shutdown.raw())?,
                Arc::downgrade(&daemon.monitor_ownership),
            )?;
        }
        Ok(daemon)
    }

    fn conn(&self) -> Result<std::sync::MutexGuard<'_, Connection>> {
        self.db.lock().map_err(|_| EmberLabError::Poisoned)
    }
    pub fn journal_mode(&self) -> Result<String> {
        Ok(self
            .conn()?
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))?)
    }
    pub fn schedule_monitor_started_at_ms(&self) -> Result<i64> {
        Ok(self.conn()?.query_row(
            "SELECT CAST(value AS INTEGER) FROM metadata WHERE key='schedule_monitor_started_at_ms'",
            [],
            |row| row.get(0),
        )?)
    }

    pub fn resource_guard_status(&self) -> Result<Value> {
        let conn = self.conn()?;
        resource_guard_status_from_connection(&conn)
    }

    pub fn import_data_catalog_manifest(
        &self,
        manifest_bytes: &[u8],
    ) -> Result<data_catalog::DataCatalogImportOutcome> {
        let mut conn = self.conn()?;
        data_catalog::import_manifest(&mut conn, manifest_bytes, now_ms())
    }

    pub fn export_data_catalog_manifest(&self) -> Result<Vec<u8>> {
        let conn = self.conn()?;
        data_catalog::export_manifest(&conn)
    }

    pub fn data_catalog_status(&self) -> Result<Value> {
        let conn = self.conn()?;
        data_catalog::status(&conn)
    }

    fn frozen_resource_guard(&self) -> Result<Option<Value>> {
        let status = self.resource_guard_status()?;
        if status.get("admission_state") == Some(&Value::String("frozen".into())) {
            Ok(Some(status))
        } else {
            Ok(None)
        }
    }

    pub fn bind_identity(&self, job_id: &str, path: &Path, expected: &str) -> Result<()> {
        let canonical = fs::canonicalize(path)?;
        let identity_blob = fs::read(&canonical)?;
        self.bind_identity_bytes(job_id, &canonical, &identity_blob, expected)
    }

    fn bind_identity_bytes(
        &self,
        job_id: &str,
        path: &Path,
        identity_blob: &[u8],
        expected: &str,
    ) -> Result<()> {
        validate_hash(expected)?;
        let canonical = fs::canonicalize(path)?;
        let actual = hash_bytes(identity_blob);
        if actual != expected {
            return Err(EmberLabError::IdentityMismatch {
                job_id: job_id.into(),
                expected: expected.into(),
                actual,
            });
        }
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let existing: Option<(String, String)> = tx
            .query_row(
                "SELECT canonical_path,sha256 FROM identities WHERE job_id=?1",
                [job_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((old_path, old_hash)) = existing {
            if old_path == canonical.to_string_lossy() && old_hash == expected {
                return Ok(());
            }
            return Err(EmberLabError::IdentityAlreadyBound {
                job_id: job_id.into(),
            });
        }
        tx.execute(
            "INSERT INTO identities(job_id,canonical_path,sha256,identity_blob,bound_at_ms) VALUES(?1,?2,?3,?4,?5)",
            params![job_id, canonical.to_string_lossy(), expected, identity_blob, now_ms()],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn verify_identity(&self, job_id: &str) -> Result<()> {
        let conn = self.conn()?;
        let row: Option<(String, String)> = conn
            .query_row(
                "SELECT canonical_path,sha256 FROM identities WHERE job_id=?1",
                [job_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        drop(conn);
        let (path, expected) = row.ok_or_else(|| EmberLabError::IdentityNotFound {
            job_id: job_id.into(),
        })?;
        let actual = hash_file(Path::new(&path))?;
        if actual != expected {
            return Err(EmberLabError::IdentityMismatch {
                job_id: job_id.into(),
                expected,
                actual,
            });
        }
        Ok(())
    }

    pub fn identity_hash(&self, job_id: &str) -> Result<Option<String>> {
        Ok(self
            .conn()?
            .query_row(
                "SELECT sha256 FROM identities WHERE job_id=?1",
                [job_id],
                |r| r.get(0),
            )
            .optional()?)
    }

    pub fn register_schedule_prediction(&self, prediction: SchedulePrediction) -> Result<()> {
        const CLASSES: [&str; 4] = [
            "training",
            "capability-learning-curve",
            "cost-model",
            "compute-primitive",
        ];
        if prediction.job_id.trim().is_empty()
            || !CLASSES.contains(&prediction.artifact_class.as_str())
            || prediction.predicted_duration_ms <= 0
            || prediction.predicted_tokens <= 0
            || prediction.absolute_deadline_ms <= 0
            || prediction.predicted_program_completion_ms <= 0
        {
            return Err(EmberLabError::InvalidSchedulePrediction {
                job_id: prediction.job_id,
                detail: "closed artifact class and positive prediction fields are required".into(),
            });
        }
        let predicted_at_ms = now_ms();
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let identity_exists: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM identities WHERE job_id=?1)",
            [&prediction.job_id],
            |row| row.get(0),
        )?;
        if !identity_exists {
            return Err(EmberLabError::IdentityNotFound {
                job_id: prediction.job_id,
            });
        }
        tx.execute(
            "INSERT INTO schedule_runs(job_id,artifact_class,predicted_at_ms,predicted_duration_ms,predicted_tokens,predicted_program_completion_ms,absolute_deadline_ms,prediction_daemon_binary_sha256,prediction_daemon_source_sha256) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            params![
                prediction.job_id,
                prediction.artifact_class,
                predicted_at_ms,
                prediction.predicted_duration_ms,
                prediction.predicted_tokens,
                prediction.predicted_program_completion_ms,
                prediction.absolute_deadline_ms,
                self.ember_lab_binary_sha256,
                self.ember_lab_source_sha256,
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn record_schedule_measurement(
        &self,
        job_id: &str,
        measured_duration_ms: i64,
        measured_tokens: i64,
        outcome: &str,
        receipt_sha256: &str,
    ) -> Result<()> {
        validate_hash(receipt_sha256)?;
        if measured_duration_ms <= 0
            || measured_tokens <= 0
            || !matches!(outcome, "COMPLETED" | "FAILED" | "ABORTED")
        {
            return Err(EmberLabError::InvalidSchedulePrediction {
                job_id: job_id.into(),
                detail: "positive measured fields and a closed outcome are required".into(),
            });
        }
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE schedule_runs SET measured_at_ms=?2,measured_duration_ms=?3,measured_tokens=?4,measurement_outcome=?5,measurement_receipt_sha256=?6,measurement_daemon_binary_sha256=?7,measurement_daemon_source_sha256=?8 WHERE job_id=?1 AND measured_at_ms IS NULL",
            params![
                job_id,
                now_ms(),
                measured_duration_ms,
                measured_tokens,
                outcome,
                receipt_sha256,
                self.ember_lab_binary_sha256,
                self.ember_lab_source_sha256,
            ],
        )?;
        if changed != 1 {
            return Err(EmberLabError::InvalidSchedulePrediction {
                job_id: job_id.into(),
                detail: "prediction is missing or already measured".into(),
            });
        }
        tx.execute(
            "DELETE FROM leases WHERE owner_job_id=?1 AND resource LIKE 'schedule:%' AND NOT EXISTS(SELECT 1 FROM jobs WHERE job_id=?1)",
            [job_id],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn schedule_alarm_state_at(&self, at_ms: i64) -> Result<Value> {
        const WEEK_MS: i64 = 7 * 24 * 60 * 60 * 1000;
        let conn = self.conn()?;
        let monitor_started_at_ms = conn.query_row("SELECT CAST(value AS INTEGER) FROM metadata WHERE key='schedule_monitor_started_at_ms'", [], |row| row.get(0))?;
        let mut statement = conn.prepare(
            "SELECT job_id,artifact_class,predicted_at_ms,predicted_duration_ms,predicted_tokens,predicted_program_completion_ms,absolute_deadline_ms,prediction_daemon_binary_sha256,prediction_daemon_source_sha256,measured_at_ms,measured_duration_ms,measured_tokens,measurement_outcome,measurement_receipt_sha256,measurement_daemon_binary_sha256,measurement_daemon_source_sha256 FROM schedule_runs ORDER BY predicted_at_ms,job_id",
        )?;
        let records: Vec<ScheduleRunRow> = statement
            .query_map([], |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                    row.get(8)?,
                    row.get(9)?,
                    row.get(10)?,
                    row.get(11)?,
                    row.get(12)?,
                    row.get(13)?,
                    row.get(14)?,
                    row.get(15)?,
                ))
            })?
            .collect::<std::result::Result<_, _>>()?;
        let latest_measurement = records.iter().filter_map(|record| record.9).max();
        let prediction_overrun = records
            .iter()
            .any(|record| record.9.is_none() && record.2.saturating_add(record.3) < at_ms);
        let absolute_deadline_drift = records.iter().any(|record| record.5 > record.6);
        let zero_schedule_receipts_7d = at_ms.saturating_sub(monitor_started_at_ms) >= WEEK_MS
            && latest_measurement
                .map(|latest| at_ms.saturating_sub(latest) >= WEEK_MS)
                .unwrap_or(true);
        let runs: Vec<Value> = records
            .into_iter()
            .map(|record| {
                json!({
                    "job_id": record.0,
                    "artifact_class": record.1,
                    "predicted_at_ms": record.2,
                    "predicted_duration_ms": record.3,
                    "predicted_tokens": record.4,
                    "predicted_program_completion_ms": record.5,
                    "absolute_deadline_ms": record.6,
                    "prediction_daemon_identity": {
                        "binary_sha256": record.7,
                        "source_sha256": record.8,
                    },
                    "measured_at_ms": record.9,
                    "measured_duration_ms": record.10,
                    "measured_tokens": record.11,
                    "measurement_outcome": record.12,
                    "measurement_receipt_sha256": record.13,
                    "measurement_daemon_identity": {
                        "binary_sha256": record.14,
                        "source_sha256": record.15,
                    },
                })
            })
            .collect();
        Ok(json!({
            "schema_version": "ember-lab-schedule-alarm-state-v1",
            "generated_at_ms": at_ms,
            "ember_lab_identity": {
                "binary_sha256": self.ember_lab_binary_sha256,
                "source_sha256": self.ember_lab_source_sha256,
            },
            "alarms": {
                "prediction_overrun": prediction_overrun,
                "zero_schedule_receipts_7d": zero_schedule_receipts_7d,
                "absolute_deadline_drift": absolute_deadline_drift,
            },
            "runs": runs,
        }))
    }

    pub fn write_schedule_alarm_state(&self, path: &Path) -> Result<()> {
        self.write_schedule_alarm_state_at(path, now_ms())
    }
    pub fn write_schedule_alarm_state_at(&self, path: &Path, at_ms: i64) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(&self.schedule_alarm_state_at(at_ms)?)?;
        atomic_replace(path, &bytes)
    }

    pub fn acquire_lease(&self, resource: &str, job_id: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some(artifact_class) = resource.strip_prefix("schedule:") {
            let predicted: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM schedule_runs WHERE job_id=?1 AND artifact_class=?2 AND measured_at_ms IS NULL)",
                params![job_id, artifact_class],
                |row| row.get(0),
            )?;
            if !predicted {
                return Err(EmberLabError::SchedulePredictionRequired {
                    resource: resource.into(),
                    job_id: job_id.into(),
                });
            }
        }
        let owner: Option<String> = tx
            .query_row(
                "SELECT owner_job_id FROM leases WHERE resource=?1",
                [resource],
                |r| r.get(0),
            )
            .optional()?;
        match owner {
            Some(owner) if owner == job_id => {
                tx.commit()?;
                Ok(())
            }
            Some(owner) => Err(EmberLabError::LeaseConflict {
                resource: resource.into(),
                owner,
                requested_by: job_id.into(),
            }),
            None => {
                let identity_exists: bool = tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM identities WHERE job_id=?1)",
                    [job_id],
                    |r| r.get(0),
                )?;
                if !identity_exists {
                    return Err(EmberLabError::IdentityNotFound {
                        job_id: job_id.into(),
                    });
                }
                let prior: Option<i64> = tx
                    .query_row(
                        "SELECT generation FROM lease_generations WHERE resource=?1",
                        [resource],
                        |r| r.get(0),
                    )
                    .optional()?;
                let epoch = prior.unwrap_or(0) + 1;
                tx.execute("INSERT INTO lease_generations(resource,generation) VALUES(?1,?2) ON CONFLICT(resource) DO UPDATE SET generation=excluded.generation", params![resource, epoch])?;
                tx.execute(
                    "INSERT INTO leases(resource,owner_job_id,lease_epoch,acquired_at_ms) VALUES(?1,?2,?3,?4)",
                    params![resource, job_id, epoch, now_ms()],
                )?;
                tx.commit()?;
                Ok(())
            }
        }
    }

    pub fn lease_owner(&self, resource: &str) -> Result<Option<String>> {
        Ok(self
            .conn()?
            .query_row(
                "SELECT owner_job_id FROM leases WHERE resource=?1",
                [resource],
                |r| r.get(0),
            )
            .optional()?)
    }

    pub fn plan_outage(
        &self,
        resource: &str,
        starts_at_ms: i64,
        ends_at_ms: i64,
        reason: &str,
    ) -> Result<i64> {
        if resource.trim().is_empty() || reason.trim().is_empty() || ends_at_ms <= starts_at_ms {
            return Err(EmberLabError::InvalidPlannedOutage {
                resource: resource.into(),
                detail: "resource/reason must be non-empty and ends_at_ms must exceed starts_at_ms"
                    .into(),
            });
        }
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO planned_outages(resource,starts_at_ms,ends_at_ms,reason,created_at_ms) VALUES(?1,?2,?3,?4,?5)",
            params![resource, starts_at_ms, ends_at_ms, reason, now_ms()],
        )?;
        let outage_id = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO outage_events(resource,ts_ms,kind,payload_json) VALUES(?1,?2,'outage_planned',?3)",
            params![
                resource,
                now_ms(),
                json!({"outage_id":outage_id,"starts_at_ms":starts_at_ms,"ends_at_ms":ends_at_ms,"reason":reason}).to_string(),
            ],
        )?;
        tx.commit()?;
        Ok(outage_id)
    }

    pub fn cancel_outages(&self, resource: &str) -> Result<usize> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let cancelled_at_ms = now_ms();
        let changed = tx.execute(
            "UPDATE planned_outages SET cancelled_at_ms=?2 WHERE resource=?1 AND cancelled_at_ms IS NULL",
            params![resource, cancelled_at_ms],
        )?;
        tx.execute(
            "INSERT INTO outage_events(resource,ts_ms,kind,payload_json) VALUES(?1,?2,'outages_cancelled',?3)",
            params![
                resource,
                cancelled_at_ms,
                json!({"count":changed}).to_string(),
            ],
        )?;
        tx.commit()?;
        Ok(changed)
    }

    pub fn job_log_paths(&self, job_id: &str) -> Result<(PathBuf, PathBuf)> {
        self.conn()?
            .query_row(
                "SELECT stdout_log_path,stderr_log_path FROM jobs WHERE job_id=?1",
                [job_id],
                |row| {
                    Ok((
                        PathBuf::from(row.get::<_, String>(0)?),
                        PathBuf::from(row.get::<_, String>(1)?),
                    ))
                },
            )
            .optional()?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })
    }

    pub fn job_restart_policy(&self, job_id: &str) -> Result<RestartPolicy> {
        let policy: String = self
            .conn()?
            .query_row(
                "SELECT restart_policy FROM jobs WHERE job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })?;
        RestartPolicy::parse(&policy)
    }

    pub fn dispatch_manifest_bytes(
        &self,
        manifest_bytes: &[u8],
        expected_sha256: &str,
    ) -> Result<DispatchOutcome> {
        self.dispatch_manifest_bytes_at_with_probes_and_host(
            manifest_bytes,
            expected_sha256,
            now_ms(),
            available_free_bytes,
            available_free_vram_bytes,
            probe_host_commit_capacity,
        )
    }
    pub fn dispatch_manifest(&self, manifest_path: &Path) -> Result<DispatchOutcome> {
        self.dispatch_manifest_at_with_probes(
            manifest_path,
            now_ms(),
            available_free_bytes,
            available_free_vram_bytes,
        )
    }

    pub fn dispatch_manifest_at_with_probes<F, G>(
        &self,
        manifest_path: &Path,
        observed_at_ms: i64,
        free_space: F,
        free_vram: G,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut() -> Result<u64>,
    {
        self.dispatch_manifest_at_with_probes_and_host(
            manifest_path,
            observed_at_ms,
            free_space,
            free_vram,
            probe_host_commit_capacity,
        )
    }

    pub fn dispatch_manifest_at_with_probes_and_host<F, G, H>(
        &self,
        manifest_path: &Path,
        observed_at_ms: i64,
        free_space: F,
        free_vram: G,
        free_host_commit: H,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut() -> Result<u64>,
        H: FnMut() -> Result<HostCommitCapacity>,
    {
        let canonical = fs::canonicalize(manifest_path).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("dispatch manifest is not a canonical file: {error}"),
            }
        })?;
        let manifest_bytes = fs::read(&canonical)?;
        self.dispatch_manifest_bytes_at_with_probes_and_host_inner(
            &manifest_bytes,
            &canonical,
            observed_at_ms,
            free_space,
            free_vram,
            free_host_commit,
        )
    }

    pub fn dispatch_manifest_bytes_at_with_probes_and_host<F, G, H>(
        &self,
        manifest_bytes: &[u8],
        expected_sha256: &str,
        observed_at_ms: i64,
        free_space: F,
        free_vram: G,
        free_host_commit: H,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut() -> Result<u64>,
        H: FnMut() -> Result<HostCommitCapacity>,
    {
        if validate_hash(expected_sha256).is_err() || hash_bytes(manifest_bytes) != expected_sha256
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch manifest bytes do not match the supplied sha256".into(),
            });
        }
        const MAX_DISPATCH_MANIFEST_SNAPSHOTS: usize = 64;
        let manifest: DispatchManifest =
            serde_json::from_slice(manifest_bytes).map_err(|error| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch manifest schema is invalid: {error}"),
                }
            })?;
        if manifest_bytes.len() > MAX_DISPATCH_MANIFEST_BYTES {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch manifest snapshot exceeds the daemon byte ceiling".into(),
            });
        }
        self.validate_dispatch_manifest_snapshot_preconditions(&manifest)?;
        // This is ember-lab state, not candidate-selected custody. Candidate custody is
        // validated by the byte consumer before it writes a preflight receipt.
        let snapshot_dir = self.log_dir.join("dispatch-manifests");
        fs::create_dir_all(&snapshot_dir)?;
        let snapshot = snapshot_dir.join(format!("{expected_sha256}.json"));
        if snapshot.exists() {
            if hash_bytes(&fs::read(&snapshot)?) != expected_sha256 {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "daemon dispatch snapshot conflicts with supplied sha256".into(),
                });
            }
            return self.dispatch_manifest_bytes_at_with_probes_and_host_inner(
                manifest_bytes,
                &snapshot,
                observed_at_ms,
                free_space,
                free_vram,
                free_host_commit,
            );
        }
        let mut snapshots = fs::read_dir(&snapshot_dir)?
            .filter_map(|entry| entry.ok())
            .filter_map(|entry| {
                let path = entry.path();
                (path.extension().and_then(|value| value.to_str()) == Some("json")).then_some(path)
            })
            .collect::<Vec<_>>();
        snapshots.sort_by_key(|path| {
            fs::metadata(path)
                .and_then(|metadata| metadata.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH)
        });
        while snapshots.len() >= MAX_DISPATCH_MANIFEST_SNAPSHOTS {
            fs::remove_file(snapshots.remove(0))?;
        }
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&snapshot)
        {
            Ok(mut file) => {
                file.write_all(manifest_bytes)?;
                file.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if hash_bytes(&fs::read(&snapshot)?) != expected_sha256 {
                    return Err(EmberLabError::InvalidDispatchManifest {
                        detail: "daemon dispatch snapshot conflicts with supplied sha256".into(),
                    });
                }
            }
            Err(error) => return Err(error.into()),
        }
        self.dispatch_manifest_bytes_at_with_probes_and_host_inner(
            manifest_bytes,
            &snapshot,
            observed_at_ms,
            free_space,
            free_vram,
            free_host_commit,
        )
    }

    fn validate_dispatch_manifest_snapshot_preconditions(
        &self,
        manifest: &DispatchManifest,
    ) -> Result<()> {
        if manifest.schema_version != "ember-lab-dispatch-manifest-v3"
            || manifest.job_id.trim().is_empty()
            || manifest.source_commit.len() != 40
            || !manifest
                .source_commit
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
            || manifest.resource_lease.trim().is_empty()
            || manifest.not_before_ms < 0
            || manifest.expires_at_ms <= manifest.not_before_ms
            || manifest.bindings.is_empty()
            || manifest.storage_reserves.is_empty()
            || (manifest.workload_profile.profile_id != DispatchWorkloadProfileId::EvidenceVerifier
                && manifest.minimum_free_vram_bytes == 0)
            || manifest.required_available_maximum_commit_bytes == 0
            || manifest.maximum_job_memory_bytes == 0
            || manifest.simulated_peak_commit_bytes == 0
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch manifest requires the closed v3 schema, workload profile, identities, window, bindings, and reserves".into(),
            });
        }
        if manifest.env.contains_key(DISPATCH_TOKEN_ENV)
            || manifest.env.contains_key(DISPATCH_JOB_ID_ENV)
            || manifest.env.contains_key(DISPATCH_DAEMON_PID_ENV)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch token environment is daemon-owned".into(),
            });
        }
        validate_dispatch_workload_profile(
            &manifest.workload_profile,
            &manifest.args,
            manifest.maximum_job_memory_bytes,
            manifest.simulated_peak_commit_bytes,
        )?;
        let custody_root = fs::canonicalize(&manifest.custody_root).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("dispatch custody root is unavailable: {error}"),
            }
        })?;
        if !custody_root.is_dir() {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch custody root is not a directory".into(),
            });
        }
        let _receipt_path = absolute_under_root(&manifest.preflight_receipt, &custody_root)?;
        let program = verify_dispatch_file(&manifest.program.path, &manifest.program.sha256)?;
        let mut verified_bindings = Vec::with_capacity(manifest.bindings.len());
        let mut seen = std::collections::BTreeSet::new();
        let mut kinds = std::collections::BTreeSet::new();
        for binding in &manifest.bindings {
            let canonical = verify_dispatch_binding(binding)?;
            if !seen.insert(canonical.clone()) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch bindings contain a duplicate canonical path".into(),
                });
            }
            kinds.insert(binding.kind);
            verified_bindings.push((canonical, binding.sha256.clone(), binding.kind));
        }
        if !kinds.contains(&DispatchBindingKind::Config)
            || !kinds.contains(&DispatchBindingKind::Manifest)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch bindings must include at least one config and one manifest"
                    .into(),
            });
        }
        validate_resume_registry_binding_closure(&manifest.args, &verified_bindings)?;
        for key in [
            "TEMP",
            "TMP",
            "TORCH_HOME",
            "TRITON_CACHE_DIR",
            "CUDA_CACHE_PATH",
            "HF_HOME",
            "XDG_CACHE_HOME",
        ] {
            let raw =
                manifest
                    .env
                    .get(key)
                    .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                        detail: format!("dispatch environment lacks custody binding {key}"),
                    })?;
            let cache =
                fs::canonicalize(raw).map_err(|error| EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch cache {key} is unavailable: {error}"),
                })?;
            if !cache.is_dir() || !cache.starts_with(&custody_root) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch cache {key} escapes custody"),
                });
            }
        }
        let mut reserve_roots = std::collections::BTreeSet::new();
        for reserve in &manifest.storage_reserves {
            if reserve.minimum_free_bytes == 0 {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch storage reserve must be positive".into(),
                });
            }
            let root = fs::canonicalize(&reserve.root).map_err(|error| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch storage root is unavailable: {error}"),
                }
            })?;
            if !reserve_roots.insert(root) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch storage roots must be unique".into(),
                });
            }
        }
        validate_absolute_dispatch_args(&manifest.args, &program, &verified_bindings, &custody_root)
    }
    fn dispatch_manifest_bytes_at_with_probes_and_host_inner<F, G, H>(
        &self,
        manifest_bytes: &[u8],
        manifest_identity_path: &Path,
        observed_at_ms: i64,
        mut free_space: F,
        mut free_vram: G,
        mut free_host_commit: H,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut() -> Result<u64>,
        H: FnMut() -> Result<HostCommitCapacity>,
    {
        let manifest_path = fs::canonicalize(manifest_identity_path).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("dispatch manifest identity snapshot is unavailable: {error}"),
            }
        })?;
        let manifest: DispatchManifest =
            serde_json::from_slice(manifest_bytes).map_err(|error| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch manifest schema is invalid: {error}"),
                }
            })?;
        if manifest.schema_version != "ember-lab-dispatch-manifest-v3"
            || manifest.job_id.trim().is_empty()
            || manifest.source_commit.len() != 40
            || !manifest
                .source_commit
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
            || manifest.resource_lease.trim().is_empty()
            || manifest.not_before_ms < 0
            || manifest.expires_at_ms <= manifest.not_before_ms
            || manifest.bindings.is_empty()
            || manifest.storage_reserves.is_empty()
            || (manifest.workload_profile.profile_id != DispatchWorkloadProfileId::EvidenceVerifier
                && manifest.minimum_free_vram_bytes == 0)
            || manifest.required_available_maximum_commit_bytes == 0
            || manifest.maximum_job_memory_bytes == 0
            || manifest.simulated_peak_commit_bytes == 0
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch manifest requires the closed v3 schema, workload profile, identities, window, bindings, and reserves".into(),
            });
        }
        if manifest.env.contains_key(DISPATCH_TOKEN_ENV)
            || manifest.env.contains_key(DISPATCH_JOB_ID_ENV)
            || manifest.env.contains_key(DISPATCH_DAEMON_PID_ENV)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch token environment is daemon-owned".into(),
            });
        }
        validate_dispatch_workload_profile(
            &manifest.workload_profile,
            &manifest.args,
            manifest.maximum_job_memory_bytes,
            manifest.simulated_peak_commit_bytes,
        )?;
        if observed_at_ms < manifest.not_before_ms {
            return Err(EmberLabError::DispatchTooEarly {
                not_before_ms: manifest.not_before_ms,
                observed_at_ms,
            });
        }
        if observed_at_ms >= manifest.expires_at_ms {
            return Err(EmberLabError::DispatchExpired {
                expires_at_ms: manifest.expires_at_ms,
                observed_at_ms,
            });
        }

        let custody_root = fs::canonicalize(&manifest.custody_root).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("dispatch custody root is unavailable: {error}"),
            }
        })?;
        if !custody_root.is_dir() {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch custody root is not a directory".into(),
            });
        }
        let receipt_path = absolute_under_root(&manifest.preflight_receipt, &custody_root)?;
        if let Some(existing) =
            self.reconstruct_existing_dispatch(&manifest, manifest_bytes, &receipt_path)?
        {
            return Ok(existing);
        }

        let host_commit = free_host_commit()?;
        let observed_available_maximum_commit_bytes = host_commit.available_maximum_commit_bytes;
        let derived_maximum = manifest
            .required_available_maximum_commit_bytes
            .checked_sub(DISPATCH_HOST_COMMIT_RESERVE_BYTES);
        if derived_maximum != Some(manifest.maximum_job_memory_bytes)
            || observed_available_maximum_commit_bytes
                < manifest.required_available_maximum_commit_bytes
            || manifest.simulated_peak_commit_bytes > manifest.maximum_job_memory_bytes
        {
            let refusal = json!({
                "schema_version": "ember-lab-dispatch-preflight-v1",
                "result": "REFUSED_HOST_COMMIT_CAP",
                "job_id": &manifest.job_id,
                "source_commit": &manifest.source_commit,
                "observed_at_ms": observed_at_ms,
                "dispatch_manifest_sha256": hash_bytes(manifest_bytes),
                "host_commit": {
                    "basis": "maximum_configured_capacity",
                    "required_available_maximum_commit_bytes": manifest.required_available_maximum_commit_bytes,
                    "observed_available_maximum_commit_bytes": observed_available_maximum_commit_bytes,
                    "physical_ram_bytes": host_commit.physical_ram_bytes,
                    "physical_available_bytes": host_commit.physical_available_bytes,
                    "pagefile_maximum_bytes": host_commit.pagefile_maximum_bytes,
                    "pagefile_configuration_source": host_commit.pagefile_configuration_source,
                    "pagefile_configuration_sha256": host_commit.pagefile_configuration_sha256,
                    "commit_total_bytes": host_commit.commit_total_bytes,
                    "current_commit_limit_bytes": host_commit.current_commit_limit_bytes,
                    "current_commit_remaining_bytes": host_commit.current_commit_remaining_bytes,
                    "maximum_commit_capacity_bytes": host_commit.maximum_commit_capacity_bytes,
                    "reserve_bytes": DISPATCH_HOST_COMMIT_RESERVE_BYTES,
                    "maximum_job_memory_bytes": manifest.maximum_job_memory_bytes,
                    "simulated_peak_commit_bytes": manifest.simulated_peak_commit_bytes,
                },
            });
            atomic_replace(&receipt_path, &serde_json::to_vec(&refusal)?)?;
            return Err(EmberLabError::DispatchHostCommitReserve {
                required_available_maximum_commit_bytes: manifest
                    .required_available_maximum_commit_bytes,
                observed_available_maximum_commit_bytes,
                reserve_bytes: DISPATCH_HOST_COMMIT_RESERVE_BYTES,
                maximum_job_memory_bytes: manifest.maximum_job_memory_bytes,
                simulated_peak_commit_bytes: manifest.simulated_peak_commit_bytes,
                receipt_path,
            });
        }

        let program = verify_dispatch_file(&manifest.program.path, &manifest.program.sha256)?;
        let mut verified_bindings = Vec::with_capacity(manifest.bindings.len());
        let mut seen = std::collections::BTreeSet::new();
        let mut kinds = std::collections::BTreeSet::new();
        for binding in &manifest.bindings {
            let canonical = verify_dispatch_binding(binding)?;
            if !seen.insert(canonical.clone()) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch bindings contain a duplicate canonical path".into(),
                });
            }
            kinds.insert(binding.kind);
            verified_bindings.push((canonical, binding.sha256.clone(), binding.kind));
        }
        if !kinds.contains(&DispatchBindingKind::Config)
            || !kinds.contains(&DispatchBindingKind::Manifest)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch bindings must include at least one config and one manifest"
                    .into(),
            });
        }
        validate_resume_registry_binding_closure(&manifest.args, &verified_bindings)?;

        const CACHE_KEYS: [&str; 7] = [
            "TEMP",
            "TMP",
            "TORCH_HOME",
            "TRITON_CACHE_DIR",
            "CUDA_CACHE_PATH",
            "HF_HOME",
            "XDG_CACHE_HOME",
        ];
        for key in CACHE_KEYS {
            let raw =
                manifest
                    .env
                    .get(key)
                    .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                        detail: format!("dispatch environment lacks custody binding {key}"),
                    })?;
            let cache =
                fs::canonicalize(raw).map_err(|error| EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch cache {key} is unavailable: {error}"),
                })?;
            if !cache.is_dir() || !cache.starts_with(&custody_root) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch cache {key} escapes custody"),
                });
            }
        }

        let mut reserve_receipts = Vec::with_capacity(manifest.storage_reserves.len());
        let mut reserve_roots = std::collections::BTreeSet::new();
        for reserve in &manifest.storage_reserves {
            if reserve.minimum_free_bytes == 0 {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch storage reserve must be positive".into(),
                });
            }
            let root = fs::canonicalize(&reserve.root).map_err(|error| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch storage root is unavailable: {error}"),
                }
            })?;
            if !reserve_roots.insert(root.clone()) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch storage roots must be unique".into(),
                });
            }
            let available = free_space(&root)?;
            if available < reserve.minimum_free_bytes {
                return Err(EmberLabError::DispatchStorageReserve {
                    root,
                    minimum_free_bytes: reserve.minimum_free_bytes,
                    available_free_bytes: available,
                });
            }
            reserve_receipts.push(json!({
                "root": root,
                "minimum_free_bytes": reserve.minimum_free_bytes,
                "available_free_bytes": available,
            }));
        }

        let available_vram = if manifest.workload_profile.profile_id
            == DispatchWorkloadProfileId::EvidenceVerifier
            && manifest.minimum_free_vram_bytes == 0
        {
            0
        } else {
            free_vram()?
        };
        if available_vram < manifest.minimum_free_vram_bytes {
            return Err(EmberLabError::DispatchVramReserve {
                minimum_free_bytes: manifest.minimum_free_vram_bytes,
                available_free_bytes: available_vram,
            });
        }

        validate_absolute_dispatch_args(
            &manifest.args,
            &program,
            &verified_bindings,
            &custody_root,
        )?;
        let manifest_sha256 = hash_bytes(manifest_bytes);
        let args_sha256 = hash_bytes(&serde_json::to_vec(&manifest.args)?);
        let env_sha256 = hash_bytes(&serde_json::to_vec(&manifest.env)?);
        let receipt_payload = json!({
            "schema_version": "ember-lab-dispatch-preflight-v1",
            "result": "PREFLIGHT_PASSED",
            "job_id": &manifest.job_id,
            "source_commit": &manifest.source_commit,
            "observed_at_ms": observed_at_ms,
            "not_before_ms": manifest.not_before_ms,
            "expires_at_ms": manifest.expires_at_ms,
            "dispatch_manifest_sha256": manifest_sha256,
            "workload_profile": &manifest.workload_profile,
            "program": {"path": &program, "sha256": &manifest.program.sha256},
            "bindings": verified_bindings.iter().map(|(path, sha256, kind)| json!({"kind":kind,"path":path,"sha256":sha256})).collect::<Vec<_>>(),
            "args_sha256": args_sha256,
            "env_sha256": env_sha256,
            "custody_root": &custody_root,
            "storage_reserves": reserve_receipts,
            "vram_reserve": {
                "minimum_free_bytes": manifest.minimum_free_vram_bytes,
                "available_free_bytes": available_vram,
            },
            "maximum_job_memory_bytes": manifest.maximum_job_memory_bytes,
            "host_commit": {
                "basis": "maximum_configured_capacity",
                "required_available_maximum_commit_bytes": manifest.required_available_maximum_commit_bytes,
                "observed_available_maximum_commit_bytes": observed_available_maximum_commit_bytes,
                "physical_ram_bytes": host_commit.physical_ram_bytes,
                "physical_available_bytes": host_commit.physical_available_bytes,
                "pagefile_maximum_bytes": host_commit.pagefile_maximum_bytes,
                "pagefile_configuration_source": host_commit.pagefile_configuration_source,
                "pagefile_configuration_sha256": host_commit.pagefile_configuration_sha256,
                "commit_total_bytes": host_commit.commit_total_bytes,
                "current_commit_limit_bytes": host_commit.current_commit_limit_bytes,
                "current_commit_remaining_bytes": host_commit.current_commit_remaining_bytes,
                "maximum_commit_capacity_bytes": host_commit.maximum_commit_capacity_bytes,
                "reserve_bytes": DISPATCH_HOST_COMMIT_RESERVE_BYTES,
                "maximum_job_memory_bytes": manifest.maximum_job_memory_bytes,
                "simulated_peak_commit_bytes": manifest.simulated_peak_commit_bytes,
            },
            "ember_lab_identity": {
                "binary_sha256": &self.ember_lab_binary_sha256,
                "source_sha256": &self.ember_lab_source_sha256,
            },
        });
        let receipt_bytes = serde_json::to_vec(&receipt_payload)?;
        if let Some(existing) = self.recover_pending_dispatch_receipt(
            &manifest,
            manifest_bytes,
            &receipt_path,
            &receipt_bytes,
        )? {
            return Ok(existing);
        }
        if let Some(resource_guard) = self.frozen_resource_guard()? {
            let reason = resource_guard
                .get("reason")
                .and_then(Value::as_str)
                .unwrap_or("resource_guard_frozen")
                .to_string();
            let refusal = json!({
                "schema_version": "ember-lab-dispatch-preflight-v1",
                "result": "REFUSED_RESOURCE_GUARD_FROZEN",
                "job_id": &manifest.job_id,
                "source_commit": &manifest.source_commit,
                "observed_at_ms": observed_at_ms,
                "dispatch_manifest_sha256": hash_bytes(manifest_bytes),
                "resource_guard": resource_guard,
            });
            atomic_replace(&receipt_path, &serde_json::to_vec(&refusal)?)?;
            return Err(EmberLabError::ResourceAdmissionFrozen {
                reason,
                receipt_path,
            });
        }
        let job_id = manifest.job_id.clone();
        let resource_lease = manifest.resource_lease.clone();
        let created_identity = self.identity_hash(&job_id)?.is_none();
        self.bind_identity_bytes(&job_id, &manifest_path, manifest_bytes, &manifest_sha256)?;
        if let Err(error) = self.acquire_lease(&resource_lease, &job_id) {
            let _ = self.rollback_dispatch_attempt(&job_id, &resource_lease, created_identity);
            return Err(error);
        }
        let profile_id = manifest.workload_profile.profile_id;
        let dispatch_expires_at_ms = manifest.expires_at_ms;
        let mut spec = JobSpec::new(
            job_id.clone(),
            program.to_string_lossy().into_owned(),
            manifest.args,
            resource_lease.clone(),
        )
        .with_maximum_job_memory_bytes(manifest.maximum_job_memory_bytes)
        .with_cpu_rate_percent(manifest.workload_profile.cpu_rate_percent);
        for (key, value) in manifest.env {
            spec = spec.with_env(key, value);
        }
        if profile_id == DispatchWorkloadProfileId::EvidenceVerifier {
            spec = spec.with_dispatch_token(dispatch_expires_at_ms)?;
        }
        let handle = match self.start_job(spec) {
            Ok(handle) => handle,
            Err(error) => {
                let _ = self.rollback_dispatch_attempt(&job_id, &resource_lease, created_identity);
                return Err(error);
            }
        };
        if atomic_replace(&receipt_path, &receipt_bytes).is_err() {
            self.persist_dispatch_receipt_recovery(
                &job_id,
                &resource_lease,
                manifest_bytes,
                &receipt_path,
                &receipt_bytes,
            )?;
            return Err(EmberLabError::DispatchReceiptRecoveryPending {
                job_id,
                receipt_path,
            });
        }
        self.persist_dispatch_preflight_receipt(
            &job_id,
            &resource_lease,
            &manifest_sha256,
            &receipt_bytes,
        )?;
        let receipt = ReceiptArtifact {
            path: receipt_path,
            sha256: hash_bytes(&receipt_bytes),
        };
        Ok(DispatchOutcome { handle, receipt })
    }

    fn persist_dispatch_receipt_recovery(
        &self,
        job_id: &str,
        resource_lease: &str,
        manifest_bytes: &[u8],
        receipt_path: &Path,
        receipt_bytes: &[u8],
    ) -> Result<()> {
        self.conn()?.execute(
            "INSERT INTO dispatch_receipt_recovery(job_id,resource_lease,manifest_sha256,receipt_path,receipt_sha256,receipt_bytes,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![
                job_id,
                resource_lease,
                hash_bytes(manifest_bytes),
                receipt_path.to_string_lossy(),
                hash_bytes(receipt_bytes),
                receipt_bytes,
                now_ms(),
            ],
        )?;
        Ok(())
    }

    fn persist_dispatch_preflight_receipt(
        &self,
        job_id: &str,
        resource_lease: &str,
        manifest_sha256: &str,
        receipt_bytes: &[u8],
    ) -> Result<()> {
        self.conn()?.execute(
            "INSERT OR REPLACE INTO dispatch_preflight_receipts(job_id,resource_lease,manifest_sha256,receipt_sha256,receipt_bytes,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6)",
            params![
                job_id,
                resource_lease,
                manifest_sha256,
                hash_bytes(receipt_bytes),
                receipt_bytes,
                now_ms(),
            ],
        )?;
        Ok(())
    }

    fn daemon_preflight_receipt(&self, job_id: &str) -> Result<Option<(String, String, Vec<u8>)>> {
        let row: Option<(String, String, String, Vec<u8>)> = self
            .conn()?
            .query_row(
                "SELECT resource_lease,manifest_sha256,receipt_sha256,receipt_bytes FROM dispatch_preflight_receipts WHERE job_id=?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;
        let Some((resource_lease, manifest_sha256, receipt_sha256, receipt_bytes)) = row else {
            return Ok(None);
        };
        if receipt_sha256 != hash_bytes(&receipt_bytes) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "daemon preflight receipt hash does not match DB bytes".into(),
            });
        }
        if self.identity_hash(job_id)?.as_deref() != Some(manifest_sha256.as_str()) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail:
                    "daemon preflight manifest binding does not match authenticated job identity"
                        .into(),
            });
        }
        Ok(Some((resource_lease, manifest_sha256, receipt_bytes)))
    }

    fn recover_pending_dispatch_receipt(
        &self,
        manifest: &DispatchManifest,
        manifest_bytes: &[u8],
        receipt_path: &Path,
        receipt_bytes: &[u8],
    ) -> Result<Option<DispatchOutcome>> {
        let row: Option<(String, String, String, String, Vec<u8>)> = self
            .conn()?
            .query_row(
                "SELECT resource_lease,manifest_sha256,receipt_path,receipt_sha256,receipt_bytes FROM dispatch_receipt_recovery WHERE job_id=?1",
                [&manifest.job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
            )
            .optional()?;
        let Some((resource_lease, manifest_sha256, stored_path, receipt_sha256, stored_bytes)) =
            row
        else {
            return Ok(None);
        };
        if resource_lease != manifest.resource_lease
            || manifest_sha256 != hash_bytes(manifest_bytes)
            || stored_path != receipt_path.to_string_lossy()
            || receipt_sha256 != hash_bytes(receipt_bytes)
            || stored_bytes != receipt_bytes
            || self.identity_hash(&manifest.job_id)? != Some(manifest_sha256.clone())
            || self.lease_owner(&manifest.resource_lease)?.as_deref()
                != Some(manifest.job_id.as_str())
            || self.job_state(&manifest.job_id)? != Some(JobState::Running)
        {
            return Err(EmberLabError::ReceiptAlreadyExists {
                path: receipt_path.to_path_buf(),
            });
        }
        atomic_replace(receipt_path, &stored_bytes)?;
        self.persist_dispatch_preflight_receipt(
            &manifest.job_id,
            &manifest.resource_lease,
            &manifest_sha256,
            &stored_bytes,
        )?;
        self.conn()?.execute(
            "DELETE FROM dispatch_receipt_recovery WHERE job_id=?1",
            [&manifest.job_id],
        )?;
        Ok(Some(DispatchOutcome {
            handle: self.adopt_job(&manifest.job_id)?,
            receipt: ReceiptArtifact {
                path: receipt_path.to_path_buf(),
                sha256: receipt_sha256,
            },
        }))
    }
    fn reconstruct_existing_dispatch(
        &self,
        manifest: &DispatchManifest,
        manifest_bytes: &[u8],
        receipt_path: &Path,
    ) -> Result<Option<DispatchOutcome>> {
        if !receipt_path.exists() {
            return Ok(None);
        }
        let receipt_bytes = fs::read(receipt_path)?;
        let receipt: Value = serde_json::from_slice(&receipt_bytes).map_err(|_| {
            EmberLabError::ReceiptAlreadyExists {
                path: receipt_path.to_path_buf(),
            }
        })?;
        let manifest_sha256 = hash_bytes(manifest_bytes);
        if receipt.get("schema_version")
            != Some(&Value::String("ember-lab-dispatch-preflight-v1".into()))
            || receipt.get("result") != Some(&Value::String("PREFLIGHT_PASSED".into()))
            || receipt.get("job_id") != Some(&Value::String(manifest.job_id.clone()))
            || receipt.get("dispatch_manifest_sha256")
                != Some(&Value::String(manifest_sha256.clone()))
            || self.identity_hash(&manifest.job_id)? != Some(manifest_sha256)
            || self.lease_owner(&manifest.resource_lease)?.as_deref()
                != Some(manifest.job_id.as_str())
            || self.job_state(&manifest.job_id)? != Some(JobState::Running)
        {
            return Err(EmberLabError::ReceiptAlreadyExists {
                path: receipt_path.to_path_buf(),
            });
        }
        Ok(Some(DispatchOutcome {
            handle: self.adopt_job(&manifest.job_id)?,
            receipt: ReceiptArtifact {
                path: receipt_path.to_path_buf(),
                sha256: hash_bytes(&receipt_bytes),
            },
        }))
    }
    fn rollback_dispatch_attempt(
        &self,
        job_id: &str,
        resource_lease: &str,
        remove_identity: bool,
    ) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let state: Option<String> = tx
            .query_row("SELECT state FROM jobs WHERE job_id=?1", [job_id], |row| {
                row.get(0)
            })
            .optional()?;
        if let Some(state) = state {
            if !matches!(state.as_str(), "failed" | "stopped" | "exited") {
                return Err(EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: "dispatch rollback refuses a nonterminal job".into(),
                });
            }
            tx.execute("DELETE FROM dispatch_tokens WHERE job_id=?1", [job_id])?;
            tx.execute("DELETE FROM events WHERE job_id=?1", [job_id])?;
            tx.execute("DELETE FROM jobs WHERE job_id=?1", [job_id])?;
        }
        tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2",
            params![resource_lease, job_id],
        )?;
        if remove_identity {
            tx.execute("DELETE FROM identities WHERE job_id=?1", [job_id])?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn start_job(&self, mut spec: JobSpec) -> Result<JobHandle> {
        self.verify_identity(&spec.job_id)?;
        let protective_key = hash_bytes(spec.job_id.as_bytes());
        let checkpoint_request_path = self.log_dir.join(format!(
            "{protective_key}.protective-checkpoint-request.json"
        ));
        let checkpoint_response_path = self.log_dir.join(format!(
            "{protective_key}.protective-checkpoint-response.json"
        ));
        spec.env.insert(
            PROTECTIVE_CHECKPOINT_REQUEST_ENV.into(),
            checkpoint_request_path.to_string_lossy().into_owned(),
        );
        spec.env.insert(
            PROTECTIVE_CHECKPOINT_RESPONSE_ENV.into(),
            checkpoint_response_path.to_string_lossy().into_owned(),
        );
        if spec.env.get("EMBER_LAB_MINIMAL_SLICE").map(String::as_str) == Some("1") {
            let output_root = self
                .log_dir
                .join("rehearsal")
                .join(hash_bytes(spec.job_id.as_bytes()));
            spec.env.insert(
                "EMBER_LAB_PHASE_OUTPUT_ROOT".into(),
                output_root.to_string_lossy().into_owned(),
            );
        }
        let argv_json = serde_json::to_string(&spec.args)?;
        let persisted_env = spec
            .env
            .iter()
            .filter(|(key, _)| key.as_str() != DISPATCH_TOKEN_ENV)
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect::<BTreeMap<_, _>>();
        let env_json = serde_json::to_string(&persisted_env)?;
        let argv_sha = hash_bytes(argv_json.as_bytes());
        let job_object_name = job_object_name(&spec.job_id);
        let log_key = hash_bytes(spec.job_id.as_bytes());
        let stdout_log_path = self.log_dir.join(format!("{log_key}.stdout.log"));
        let stderr_log_path = self.log_dir.join(format!("{log_key}.stderr.log"));
        {
            let mut conn = self.conn()?;
            let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let timestamp = now_ms();
            let outage: Option<(i64, String)> = tx
                .query_row(
                    "SELECT ends_at_ms,reason FROM planned_outages WHERE resource=?1 AND cancelled_at_ms IS NULL AND starts_at_ms<=?2 AND ends_at_ms>?2 ORDER BY outage_id DESC LIMIT 1",
                    params![spec.resource_lease, timestamp],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if let Some((ends_at_ms, reason)) = outage {
                return Err(EmberLabError::PlannedOutageActive {
                    resource: spec.resource_lease.clone(),
                    ends_at_ms,
                    reason,
                });
            }
            let lease: Option<(String, i64)> = tx
                .query_row(
                    "SELECT owner_job_id,lease_epoch FROM leases WHERE resource=?1",
                    [&spec.resource_lease],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?;
            let (owner, lease_epoch) = lease.ok_or_else(|| EmberLabError::LeaseNotOwned {
                resource: spec.resource_lease.clone(),
                job_id: spec.job_id.clone(),
            })?;
            if owner != spec.job_id {
                return Err(EmberLabError::LeaseNotOwned {
                    resource: spec.resource_lease,
                    job_id: spec.job_id,
                });
            }
            if tx
                .query_row("SELECT 1 FROM jobs WHERE job_id=?1", [&spec.job_id], |_| {
                    Ok(())
                })
                .optional()?
                .is_some()
            {
                return Err(EmberLabError::InvalidTransition {
                    job_id: spec.job_id,
                    detail: "job already exists".into(),
                });
            }
            tx.execute(
                "INSERT INTO jobs(job_id,program,args_json,env_json,resource,lease_epoch,job_object_name,argv_sha256,restart_policy,stdout_log_path,stderr_log_path,state,started_at_ms,updated_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,'starting',?12,?12)",
                params![spec.job_id, spec.program, argv_json, env_json, spec.resource_lease, lease_epoch, job_object_name, argv_sha, spec.restart_policy.as_str(), stdout_log_path.to_string_lossy(), stderr_log_path.to_string_lossy(), timestamp],
            )?;
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_start_reserved',?3)",
                params![spec.job_id, now_ms(), json!({"job_object_name":job_object_name,"cpu_rate_percent":spec.cpu_rate_percent}).to_string()],
            )?;
            tx.commit()?;
        }
        let mut spawned =
            match spawn_managed(&spec, &job_object_name, &stdout_log_path, &stderr_log_path) {
                Ok(spawned) => spawned,
                Err(error) => {
                    let _ = self.mark_failed(&spec.job_id, "job_spawn_failed");
                    return Err(error);
                }
            };
        let pid = spawned.pid();
        let identity = spawned.identity();
        let prepared = (|| -> Result<()> {
            let mut conn = self.conn()?;
            let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let changed = tx.execute(
                "UPDATE jobs SET pid=?2,main_thread_id=?3,process_start_token=?4,executable_identity=?5,stdout_child_handle=?6,stderr_child_handle=?7,state='prepared',updated_at_ms=?8 WHERE job_id=?1 AND state='starting' AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
                params![spec.job_id, pid, spawned.main_thread_id(), identity.start_token, identity.executable, spawned.stdout_child_handle(), spawned.stderr_child_handle(), now_ms()],
            )?;
            if changed != 1 {
                return Err(EmberLabError::InvalidTransition {
                    job_id: spec.job_id.clone(),
                    detail: "start reservation disappeared".into(),
                });
            }
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_prepared',?3)",
                params![spec.job_id, now_ms(), json!({"pid":pid,"job_object_name":job_object_name,"cpu_rate_percent":spec.cpu_rate_percent}).to_string()],
            )?;
            if let Some(token) = &spec.dispatch_token {
                tx.execute(
                    "INSERT INTO dispatch_tokens(token_sha256,job_id,pid,program,argv_sha256,expires_at_ms,consumed_at_ms) VALUES(?1,?2,?3,?4,?5,?6,NULL)",
                    params![token.sha256, spec.job_id, pid, spec.program, argv_sha, token.expires_at_ms],
                )?;
            }
            tx.commit()?;
            Ok(())
        })();
        if let Err(error) = prepared {
            let _ = spawned.terminate_and_wait();
            let _ = self.mark_failed(&spec.job_id, "job_prepare_commit_failed");
            return Err(error);
        }
        let running = (|| -> Result<()> {
            let mut conn = self.conn()?;
            let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let launch_at_ms = now_ms();
            let outage: Option<(i64, String)> = tx
                .query_row(
                    "SELECT ends_at_ms,reason FROM planned_outages WHERE resource=?1 AND cancelled_at_ms IS NULL AND starts_at_ms<=?2 AND ends_at_ms>?2 ORDER BY outage_id DESC LIMIT 1",
                    params![spec.resource_lease, launch_at_ms],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if let Some((ends_at_ms, reason)) = outage {
                return Err(EmberLabError::PlannedOutageActive {
                    resource: spec.resource_lease.clone(),
                    ends_at_ms,
                    reason,
                });
            }
            let fenced = tx.execute(
                "UPDATE jobs SET updated_at_ms=?2 WHERE job_id=?1 AND state='prepared' AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
                params![spec.job_id, launch_at_ms],
            )?;
            if fenced != 1 {
                return Err(EmberLabError::InvalidTransition {
                    job_id: spec.job_id.clone(),
                    detail: "prepared start lost its state or lease fence".into(),
                });
            }
            spawned.resume()?;
            let changed = tx.execute(
                "UPDATE jobs SET state='running',updated_at_ms=?2 WHERE job_id=?1 AND state='prepared' AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
                params![spec.job_id, now_ms()],
            )?;
            if changed != 1 {
                return Err(EmberLabError::InvalidTransition {
                    job_id: spec.job_id.clone(),
                    detail: "resumed start lost its held state or lease fence".into(),
                });
            }
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_started',?3)",
                params![
                    spec.job_id,
                    now_ms(),
                    json!({"pid":pid,"job_object_name":job_object_name}).to_string()
                ],
            )?;
            tx.commit()?;
            Ok(())
        })();
        if let Err(error) = running {
            let _ = spawned.terminate_and_wait();
            let _ = self.mark_failed(&spec.job_id, "job_launch_commit_failed");
            return Err(error);
        }
        #[cfg(windows)]
        self.retain_and_monitor(&spec.job_id, spawned.into_live())?;
        #[cfg(not(windows))]
        spawned.detach_reaper();
        Ok(JobHandle { pid })
    }

    pub fn job_state(&self, job_id: &str) -> Result<Option<JobState>> {
        let value: Option<String> = self
            .conn()?
            .query_row("SELECT state FROM jobs WHERE job_id=?1", [job_id], |r| {
                r.get(0)
            })
            .optional()?;
        value.map(|v| JobState::parse(&v)).transpose()
    }

    pub fn job_pid(&self, job_id: &str) -> Result<Option<u32>> {
        Ok(self
            .conn()?
            .query_row("SELECT pid FROM jobs WHERE job_id=?1", [job_id], |row| {
                row.get::<_, i64>(0)
            })
            .optional()?
            .and_then(|pid| u32::try_from(pid).ok()))
    }

    pub(crate) fn runtime_identity_hashes(&self) -> (&str, &str) {
        (&self.ember_lab_binary_sha256, &self.ember_lab_source_sha256)
    }

    pub fn consume_dispatch_token(&self, job_id: &str, token: &str, client_pid: u32) -> Result<()> {
        if job_id.trim().is_empty()
            || token.len() != DISPATCH_TOKEN_BYTES * 2
            || !token
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
            || client_pid == 0
        {
            return Err(EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            });
        }
        let row =
            self.job_process_row(job_id)
                .map_err(|_| EmberLabError::DispatchTokenRefused {
                    job_id: job_id.into(),
                })?;
        if row.pid != client_pid || !matches!(row.state, JobState::Prepared | JobState::Running) {
            return Err(EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            });
        }
        #[cfg(windows)]
        let live = match open_live_status(&row) {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead | LiveStatus::Orphaned(_) | LiveStatus::IdentityConflict(_) => {
                return Err(EmberLabError::DispatchTokenRefused {
                    job_id: job_id.into(),
                })
            }
        };
        #[cfg(windows)]
        let observed_identity = live.identity.clone();
        #[cfg(not(windows))]
        let observed_identity =
            inspect_process(client_pid).map_err(|_| EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            })?;
        let token_sha256 = hash_bytes(token.as_bytes());
        let consumed_at_ms = now_ms();
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE dispatch_tokens AS t SET consumed_at_ms=?4
             WHERE t.token_sha256=?1 AND t.job_id=?2 AND t.pid=?3
               AND t.consumed_at_ms IS NULL AND t.expires_at_ms>?4
               AND EXISTS(
                 SELECT 1 FROM jobs j
                 WHERE j.job_id=t.job_id AND j.pid=t.pid
                   AND j.program=t.program AND j.argv_sha256=t.argv_sha256
                   AND j.process_start_token=?5
                   AND j.executable_identity=?6
                   AND j.state IN ('prepared','running')
               )",
            params![
                token_sha256,
                job_id,
                client_pid,
                consumed_at_ms,
                observed_identity.start_token,
                observed_identity.executable,
            ],
        )?;
        if changed != 1 {
            return Err(EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            });
        }
        let persisted_identity: (String, String) = tx
            .query_row(
                "SELECT process_start_token,executable_identity FROM jobs WHERE job_id=?1 AND pid=?2",
                params![job_id, client_pid],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(|_| EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            })?;
        if persisted_identity.0 != observed_identity.start_token
            || !same_executable(&persisted_identity.1, &observed_identity.executable)
        {
            return Err(EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            });
        }
        #[cfg(windows)]
        if !live_process_is_running(&live) {
            return Err(EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'dispatch_token_consumed',?3)",
            params![job_id, consumed_at_ms, json!({"client_pid":client_pid}).to_string()],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn job_exit_code(&self, job_id: &str) -> Result<Option<i64>> {
        self.conn()?
            .query_row(
                "SELECT exit_code FROM jobs WHERE job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })
    }

    pub fn adopt_job(&self, job_id: &str) -> Result<JobHandle> {
        let pending_receipt_path: Option<String> = self
            .conn()?
            .query_row(
                "SELECT receipt_path FROM dispatch_receipt_recovery WHERE job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(receipt_path) = pending_receipt_path {
            return Err(EmberLabError::DispatchReceiptRecoveryPending {
                job_id: job_id.into(),
                receipt_path: PathBuf::from(receipt_path),
            });
        }
        let row = self.job_process_row(job_id)?;
        if row.state != JobState::Running {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "only running jobs can be adopted".into(),
            });
        }
        #[cfg(windows)]
        let live = match open_live_status(&row) {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead => {
                let _ = self.mark_exited_unknown(job_id, &row, "job_reconciled_exited_unknown");
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
            LiveStatus::Orphaned(detail) => {
                self.mark_uncertain(
                    job_id,
                    &row,
                    JobState::Orphaned,
                    "job_reconciled_orphaned",
                    &detail,
                )?;
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
            LiveStatus::IdentityConflict(detail) => {
                self.mark_uncertain(
                    job_id,
                    &row,
                    JobState::IdentityConflict,
                    "job_reconciled_identity_conflict",
                    &detail,
                )?;
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
        };
        #[cfg(not(windows))]
        {
            let current = match inspect_process(row.pid) {
                Ok(current) => current,
                Err(_) => {
                    self.mark_exited_unknown(job_id, &row, "job_reconciled_exited_unknown")?;
                    return Err(EmberLabError::ProcessUnavailable {
                        job_id: job_id.into(),
                        pid: row.pid,
                    });
                }
            };
            if current.start_token != row.start_token
                || !same_executable(&current.executable, &row.executable)
            {
                return Err(EmberLabError::ProcessIdentityMismatch {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
        }
        self.commit_adoption(job_id, &row)?;
        #[cfg(windows)]
        self.retain_and_monitor(job_id, live)?;
        Ok(JobHandle { pid: row.pid })
    }

    pub fn stop_job(&self, job_id: &str) -> Result<()> {
        let row = self.job_process_row(job_id)?;
        if !matches!(row.state, JobState::Running | JobState::Stopping) {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "only running or stopping jobs can be stopped".into(),
            });
        }
        #[cfg(windows)]
        let live = self
            .live
            .lock()
            .map_err(|_| EmberLabError::Poisoned)?
            .remove(job_id)
            .map(|retained| LiveStatus::Verified(retained.live))
            .unwrap_or_else(|| open_live_status(&row));
        #[cfg(windows)]
        let live = match live {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead if row.state == JobState::Stopping => {
                self.finalize_stopped(job_id, &row, false)?;
                return Ok(());
            }
            LiveStatus::Dead => {
                self.mark_exited_unknown(job_id, &row, "job_exited_before_stop")?;
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
            LiveStatus::Orphaned(detail) => {
                self.mark_uncertain(
                    job_id,
                    &row,
                    JobState::Orphaned,
                    "job_stop_orphaned",
                    &detail,
                )?;
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
            LiveStatus::IdentityConflict(detail) => {
                self.mark_uncertain(
                    job_id,
                    &row,
                    JobState::IdentityConflict,
                    "job_stop_identity_conflict",
                    &detail,
                )?;
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
        };
        #[cfg(not(windows))]
        {
            let current =
                inspect_process(row.pid).map_err(|_| EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })?;
            if current.start_token != row.start_token
                || !same_executable(&current.executable, &row.executable)
            {
                return Err(EmberLabError::ProcessIdentityMismatch {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
        }
        if row.state == JobState::Running {
            {
                let mut conn = self.conn()?;
                let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
                let changed = tx.execute("UPDATE jobs SET state='stopping',updated_at_ms=?2 WHERE job_id=?1 AND state='running' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)", params![job_id, now_ms(), row.lease_epoch])?;
                if changed != 1 {
                    return Err(EmberLabError::InvalidTransition {
                        job_id: job_id.into(),
                        detail: "stop lost its state or lease fence".into(),
                    });
                }
                tx.execute("INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_stop_requested',?3)", params![job_id, now_ms(), json!({"pid":row.pid}).to_string()])?;
                tx.commit()?;
            }
        }
        #[cfg(windows)]
        if let Err(error) = terminate_live(&live) {
            self.live
                .lock()
                .map_err(|_| EmberLabError::Poisoned)?
                .insert(
                    job_id.into(),
                    RetainedProcess {
                        live,
                        monitored: false,
                    },
                );
            return Err(error);
        }
        #[cfg(not(windows))]
        terminate_process(row.pid)?;
        self.finalize_stopped(job_id, &row, true)
    }

    #[cfg(windows)]
    pub fn protective_owned_stop(
        &self,
        job_id: &str,
        checkpoint_grace: Duration,
    ) -> Result<ReceiptArtifact> {
        ProtectiveStopContext {
            db: Arc::clone(&self.db),
            live: Arc::clone(&self.live),
            log_dir: self.log_dir.clone(),
        }
        .protective_owned_stop(job_id, checkpoint_grace)
    }

    fn receipt_bytes(&self, job_id: &str) -> Result<Vec<u8>> {
        self.verify_identity(job_id)?;
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let row: ReceiptRow = tx
            .query_row(
                "SELECT j.state,j.resource,i.sha256,j.executable_identity,j.pid,j.restart_policy,j.stdout_log_path,j.stderr_log_path,j.exit_code,j.stdout_log_sha256,j.stderr_log_sha256,j.outage_event_cutoff_seq FROM jobs j JOIN identities i ON i.job_id=j.job_id WHERE j.job_id=?1",
                [job_id],
                |row| {
                    Ok(ReceiptRow {
                        state: row.get(0)?,
                        resource: row.get(1)?,
                        identity_sha256: row.get(2)?,
                        executable_identity: row.get(3)?,
                        pid: row.get(4)?,
                        restart_policy: row.get(5)?,
                        stdout_log_path: row.get(6)?,
                        stderr_log_path: row.get(7)?,
                        exit_code: row.get(8)?,
                        stdout_log_sha256: row.get(9)?,
                        stderr_log_sha256: row.get(10)?,
                        outage_event_cutoff_seq: row.get(11)?,
                    })
                },
            )
            .optional()?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })?;
        let mut stmt = tx.prepare(
            "SELECT seq,ts_ms,kind,payload_json FROM events WHERE job_id=?1 ORDER BY seq",
        )?;
        let raw_events: Vec<(i64, i64, String, String)> = stmt
            .query_map([job_id], |row| {
                Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?))
            })?
            .collect::<std::result::Result<_, _>>()?;
        drop(stmt);
        let mut outage_stmt = tx.prepare(
            "SELECT seq,ts_ms,kind,payload_json FROM outage_events WHERE resource=?1 AND seq<=?2 ORDER BY seq",
        )?;
        let raw_outage_events: Vec<(i64, i64, String, String)> = outage_stmt
            .query_map(
                params![
                    &row.resource,
                    row.outage_event_cutoff_seq.unwrap_or(i64::MAX)
                ],
                |outage| {
                    Ok((
                        outage.get(0)?,
                        outage.get(1)?,
                        outage.get(2)?,
                        outage.get(3)?,
                    ))
                },
            )?
            .collect::<std::result::Result<_, _>>()?;
        drop(outage_stmt);
        tx.commit()?;
        let events: Vec<Value> = raw_events
            .into_iter()
            .map(|(seq, ts, kind, payload)| {
                Ok(json!({"seq":seq,"ts_ms":ts,"kind":kind,"payload":serde_json::from_str::<Value>(&payload)?}))
            })
            .collect::<Result<_>>()?;
        let outage_events: Vec<Value> = raw_outage_events
            .into_iter()
            .map(|(seq, ts, kind, payload)| {
                Ok(json!({"seq":seq,"ts_ms":ts,"kind":kind,"payload":serde_json::from_str::<Value>(&payload)?}))
            })
            .collect::<Result<_>>()?;
        let stdout_path = PathBuf::from(&row.stdout_log_path);
        let stderr_path = PathBuf::from(&row.stderr_log_path);
        let file_name = |path: &Path| {
            path.file_name()
                .map(|name| name.to_string_lossy().into_owned())
        };
        let (stdout_evidence, stderr_evidence) = match (
            row.stdout_log_sha256.as_ref(),
            row.stderr_log_sha256.as_ref(),
        ) {
            (Some(expected_stdout), Some(expected_stderr)) => {
                let stdout_sha256 = hash_file(&stdout_path)?;
                let stderr_sha256 = hash_file(&stderr_path)?;
                for (stream, expected, actual) in [
                    ("stdout", expected_stdout, &stdout_sha256),
                    ("stderr", expected_stderr, &stderr_sha256),
                ] {
                    if expected != actual {
                        return Err(EmberLabError::LogEvidenceMismatch {
                            job_id: job_id.into(),
                            stream: stream.into(),
                            expected: expected.clone(),
                            actual: actual.clone(),
                        });
                    }
                }
                (
                    json!({"file_name":file_name(&stdout_path),"sealed":true,"sha256":stdout_sha256}),
                    json!({"file_name":file_name(&stderr_path),"sealed":true,"sha256":stderr_sha256}),
                )
            }
            (None, None) => (
                json!({"file_name":file_name(&stdout_path),"sealed":false,"sha256":Value::Null}),
                json!({"file_name":file_name(&stderr_path),"sealed":false,"sha256":Value::Null}),
            ),
            _ => {
                return Err(EmberLabError::LogEvidenceUnsealed {
                    job_id: job_id.into(),
                })
            }
        };
        let receipt = json!({
            "schema":"ember-lab-operational-receipt-v1",
            "ember_lab_identity":{
                "binary_sha256":self.ember_lab_binary_sha256,
                "source_sha256":self.ember_lab_source_sha256
            },
            "job_id":job_id,
            "identity_sha256":row.identity_sha256,
            "resource_lease":row.resource,
            "state":row.state,
            "pid":row.pid,
            "executable_identity":row.executable_identity,
            "restart_policy":row.restart_policy,
            "exit_code":row.exit_code,
            "logs":{
                "stdout":stdout_evidence,
                "stderr":stderr_evidence
            },
            "events":events,
            "outage_events":outage_events,
            "scientific_capability_evidence":false
        });
        Ok(serde_json::to_vec_pretty(&receipt)?)
    }

    pub fn export_receipt(&self, job_id: &str, path: &Path) -> Result<()> {
        atomic_create(path, &self.receipt_bytes(job_id)?)
    }

    pub fn export_content_addressed_receipt(
        &self,
        job_id: &str,
        directory: &Path,
    ) -> Result<ReceiptArtifact> {
        let state = self
            .job_state(job_id)?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })?;
        if !matches!(
            state,
            JobState::Stopped | JobState::Exited | JobState::Failed
        ) {
            return Err(EmberLabError::NonTerminalReceipt {
                job_id: job_id.into(),
                state: state.as_str().into(),
            });
        }
        write_content_addressed_receipt(directory, &self.receipt_bytes(job_id)?)
    }

    /// Publish one daemon-derived assessment snapshot into an absent directory.
    ///
    /// All bytes are reopened and verified before a private staging directory is
    /// renamed into view, so callers never receive a partial or caller-authored
    /// receipt/log/schedule chain.
    pub fn export_assessment_evidence(
        &self,
        job_id: &str,
        directory: &Path,
    ) -> Result<AssessmentEvidenceArtifact> {
        let state = self
            .job_state(job_id)?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })?;
        if !matches!(
            state,
            JobState::Stopped | JobState::Exited | JobState::Failed
        ) {
            return Err(EmberLabError::NonTerminalReceipt {
                job_id: job_id.into(),
                state: state.as_str().into(),
            });
        }
        if directory.exists() {
            return Err(EmberLabError::ReceiptAlreadyExists {
                path: directory.to_path_buf(),
            });
        }
        let parent = directory
            .parent()
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "assessment evidence directory must have a parent".into(),
            })?;
        if !parent.is_dir() {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "assessment evidence parent must already exist".into(),
            });
        }

        let receipt_bytes = self.receipt_bytes(job_id)?;
        let receipt: Value = serde_json::from_slice(&receipt_bytes)?;
        let identity = receipt.get("ember_lab_identity").cloned().ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: "operational receipt omitted daemon identity".into(),
            }
        })?;
        let (resource_lease, manifest_sha256, preflight_bytes) = self
            .daemon_preflight_receipt(job_id)?
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "daemon preflight receipt is not present in DB custody".into(),
            })?;
        if receipt.get("identity_sha256").and_then(Value::as_str) != Some(manifest_sha256.as_str())
            || receipt.get("resource_lease").and_then(Value::as_str)
                != Some(resource_lease.as_str())
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "daemon preflight lease and identity are not bound to operational receipt"
                    .into(),
            });
        }
        let preflight: Value = serde_json::from_slice(&preflight_bytes)?;
        let preflight_object =
            preflight
                .as_object()
                .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                    detail: "daemon preflight receipt is not a JSON object".into(),
                })?;
        let preflight_program = preflight_object.get("program").and_then(Value::as_object);
        if preflight_object.get("schema_version")
            != Some(&Value::String("ember-lab-dispatch-preflight-v1".into()))
            || preflight_object.get("result") != Some(&Value::String("PREFLIGHT_PASSED".into()))
            || preflight_object.get("job_id") != Some(&Value::String(job_id.into()))
            || preflight_object
                .get("dispatch_manifest_sha256")
                .and_then(Value::as_str)
                != Some(manifest_sha256.as_str())
            || preflight_object.get("ember_lab_identity") != Some(&identity)
            || preflight_object
                .get("source_commit")
                .and_then(Value::as_str)
                .map(|value| {
                    value.len() == 40 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
                })
                != Some(true)
            || preflight_program
                .and_then(|value| value.get("path"))
                .and_then(Value::as_str)
                .map(|value| !value.is_empty())
                != Some(true)
            || preflight_program
                .and_then(|value| value.get("sha256"))
                .and_then(Value::as_str)
                .map(|value| {
                    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
                })
                != Some(true)
            || !preflight_object
                .get("bindings")
                .and_then(Value::as_array)
                .map(|value| !value.is_empty())
                .unwrap_or(false)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "daemon preflight receipt failed DB-custody schema validation".into(),
            });
        }
        let logs = receipt
            .get("logs")
            .and_then(Value::as_object)
            .ok_or_else(|| EmberLabError::LogEvidenceUnsealed {
                job_id: job_id.into(),
            })?;
        let (stdout_path, stderr_path) = self.job_log_paths(job_id)?;
        let stdout_bytes = fs::read(&stdout_path)?;
        let stderr_bytes = fs::read(&stderr_path)?;
        let stdout_sha256 = hash_bytes(&stdout_bytes);
        let stderr_sha256 = hash_bytes(&stderr_bytes);
        for (stream, path, actual) in [
            ("stdout", &stdout_path, &stdout_sha256),
            ("stderr", &stderr_path, &stderr_sha256),
        ] {
            let evidence = logs.get(stream).and_then(Value::as_object);
            let expected = evidence
                .and_then(|value| value.get("sha256"))
                .and_then(Value::as_str)
                .unwrap_or_default();
            let file_name = path.file_name().map(|value| value.to_string_lossy());
            if evidence
                .and_then(|value| value.get("sealed"))
                .and_then(Value::as_bool)
                != Some(true)
                || evidence
                    .and_then(|value| value.get("file_name"))
                    .and_then(Value::as_str)
                    != file_name.as_deref()
                || expected != actual
            {
                return Err(EmberLabError::LogEvidenceMismatch {
                    job_id: job_id.into(),
                    stream: stream.into(),
                    expected: expected.into(),
                    actual: actual.clone(),
                });
            }
        }
        let schedule_bytes = serde_json::to_vec_pretty(&self.schedule_alarm_state_at(now_ms())?)?;
        let receipt_sha256 = hash_bytes(&receipt_bytes);
        let preflight_sha256 = hash_bytes(&preflight_bytes);
        let schedule_sha256 = hash_bytes(&schedule_bytes);
        let staging = parent.join(format!(
            ".assessment-evidence-{}-{}-{}",
            directory.file_name().unwrap_or_default().to_string_lossy(),
            std::process::id(),
            now_ms()
        ));
        fs::create_dir(&staging)?;
        let publish = (|| -> Result<()> {
            atomic_create(
                &staging.join(format!("{preflight_sha256}.preflight.json")),
                &preflight_bytes,
            )?;
            atomic_create(
                &staging.join(format!("{receipt_sha256}.operational.json")),
                &receipt_bytes,
            )?;
            atomic_create(
                &staging.join(format!("{stdout_sha256}.stdout.log")),
                &stdout_bytes,
            )?;
            atomic_create(
                &staging.join(format!("{stderr_sha256}.stderr.log")),
                &stderr_bytes,
            )?;
            atomic_create(
                &staging.join(format!("{schedule_sha256}.schedule.json")),
                &schedule_bytes,
            )?;
            publish_staging_directory(&staging, directory)?;
            Ok(())
        })();
        if let Err(error) = publish {
            let _ = fs::remove_dir_all(&staging);
            return Err(error);
        }
        let artifact = |name: String, sha256: String| ReceiptArtifact {
            path: directory.join(name),
            sha256,
        };
        Ok(AssessmentEvidenceArtifact {
            schema: "ember-lab-assessment-evidence-v1".into(),
            preflight_receipt: artifact(
                format!("{preflight_sha256}.preflight.json"),
                preflight_sha256,
            ),
            operational_receipt: artifact(
                format!("{receipt_sha256}.operational.json"),
                receipt_sha256,
            ),
            stdout_log: artifact(format!("{stdout_sha256}.stdout.log"), stdout_sha256),
            stderr_log: artifact(format!("{stderr_sha256}.stderr.log"), stderr_sha256),
            schedule_alarm_state: artifact(
                format!("{schedule_sha256}.schedule.json"),
                schedule_sha256,
            ),
            ember_lab_identity: identity,
        })
    }

    /// Export the daemon-owned terminal receipt with one observation nested in
    /// the same operational receipt family. The base receipt is rebuilt from
    /// the verified job/identity/event database; callers cannot replace it in
    /// place or self-author a new authority family.
    pub fn export_content_addressed_receipt_with_observation(
        &self,
        job_id: &str,
        directory: &Path,
        observation: &Value,
    ) -> Result<ReceiptArtifact> {
        let state = self
            .job_state(job_id)?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })?;
        if !matches!(
            state,
            JobState::Stopped | JobState::Exited | JobState::Failed
        ) {
            return Err(EmberLabError::NonTerminalReceipt {
                job_id: job_id.into(),
                state: state.as_str().into(),
            });
        }
        let mut receipt: Value = serde_json::from_slice(&self.receipt_bytes(job_id)?)?;
        receipt
            .as_object_mut()
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "daemon operational receipt is not a JSON object".into(),
            })?
            .insert("rehearsal".into(), observation.clone());
        write_content_addressed_receipt(directory, &serde_json::to_vec_pretty(&receipt)?)
    }
    #[cfg(windows)]
    fn retain_and_monitor(&self, job_id: &str, live: LiveProcess) -> Result<()> {
        let registration = (|| -> Result<(OwnedHandle, OwnedHandle)> {
            Ok((
                duplicate_owned_handle(live.process.raw())?,
                duplicate_owned_handle(self.monitor_shutdown.raw())?,
            ))
        })();
        let (waiter, shutdown) = match registration {
            Ok(registration) => registration,
            Err(setup_error) => {
                let cleanup = terminate_live(&live)
                    .and_then(|_| self.mark_failed(job_id, "job_monitor_setup_failed"));
                return match cleanup {
                    Ok(()) => Err(setup_error),
                    Err(cleanup_error) => {
                        self.live
                            .lock()
                            .unwrap_or_else(|poisoned| poisoned.into_inner())
                            .insert(
                                job_id.into(),
                                RetainedProcess {
                                    live,
                                    monitored: false,
                                },
                            );
                        Err(EmberLabError::MonitorSetupCleanupFailed {
                            job_id: job_id.into(),
                            setup: format!("{setup_error:?}"),
                            cleanup: format!("{cleanup_error:?}"),
                        })
                    }
                };
            }
        };
        let pid = live.pid;
        let mut retained = self
            .live
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(existing) = retained.get_mut(job_id) {
            if existing.monitored {
                return Ok(());
            }
            existing.monitored = true;
            drop(retained);
        } else {
            retained.insert(
                job_id.into(),
                RetainedProcess {
                    live,
                    monitored: true,
                },
            );
            drop(retained);
        }
        spawn_exit_monitor(
            Arc::downgrade(&self.db),
            Arc::downgrade(&self.live),
            Arc::clone(&self.monitor_ownership),
            shutdown,
            job_id.into(),
            pid,
            waiter,
        );
        Ok(())
    }
    pub fn has_retained_process_handle(&self, job_id: &str) -> bool {
        #[cfg(windows)]
        {
            self.live
                .lock()
                .map(|live| live.contains_key(job_id))
                .unwrap_or(false)
        }
        #[cfg(not(windows))]
        {
            let _ = job_id;
            false
        }
    }

    pub fn job_event_kinds(&self, job_id: &str) -> Result<Vec<String>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare("SELECT kind FROM events WHERE job_id=?1 ORDER BY seq")?;
        let rows = stmt
            .query_map([job_id], |r| r.get(0))?
            .collect::<std::result::Result<_, _>>()?;
        Ok(rows)
    }

    fn consume_minimal_slice(
        &self,
        job_id: &str,
        expected_whole_run_peak_bytes: u64,
        readiness_deadline_ms: i64,
    ) -> Result<Vec<crate::rehearsal::PhaseEvidence>> {
        use crate::rehearsal::{Phase, PhaseEvidence};
        let _caller_supplied_peak = expected_whole_run_peak_bytes;
        let phases = [
            Phase::DataVerify,
            Phase::Train,
            Phase::Checkpoint,
            Phase::Publish,
            Phase::SelectableCheckpoint,
            Phase::Restore,
        ];
        if expected_whole_run_peak_bytes == 0 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice whole-run host peak must be measured".into(),
            });
        }
        self.identity_hash(job_id)?
            .ok_or_else(|| EmberLabError::IdentityNotFound {
                job_id: job_id.into(),
            })?;
        let phase_dir = self
            .log_dir
            .join("rehearsal")
            .join(hash_bytes(job_id.as_bytes()));
        let initial_row = self.job_process_row(job_id)?;
        if initial_row.state != JobState::Running
            || !self.lease_matches_process_row(job_id, &initial_row)?
        {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice producer is not running under its fenced lease".into(),
            });
        }
        let completion_path = phase_dir.join("completion.json");
        let completion_bytes = {
            loop {
                let current_row = self.job_process_row(job_id)?;
                if current_row.state != JobState::Running
                    || !same_job_process_fence(&initial_row, &current_row)
                    || !self.lease_matches_process_row(job_id, &current_row)?
                {
                    return Err(EmberLabError::InvalidTransition {
                        job_id: job_id.into(),
                        detail: "minimal-slice producer identity or lease changed before readiness"
                            .into(),
                    });
                }
                if now_ms() >= readiness_deadline_ms {
                    return Err(EmberLabError::InvalidTransition {
                        job_id: job_id.into(),
                        detail: "minimal-slice readiness deadline expired before completion".into(),
                    });
                }
                match fs::read(&completion_path) {
                    Ok(bytes) => break bytes,
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                        std::thread::sleep(Duration::from_millis(10));
                    }
                    Err(error) => {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: format!(
                                "minimal-slice durable completion marker is unavailable: {error}"
                            ),
                        });
                    }
                }
            }
        };
        let row = self.job_process_row(job_id)?;
        if row.state != JobState::Running
            || !same_job_process_fence(&initial_row, &row)
            || !self.lease_matches_process_row(job_id, &row)?
        {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice producer identity or lease changed at readiness".into(),
            });
        }
        let completion: Value = serde_json::from_slice(&completion_bytes).map_err(|_| {
            EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice durable completion marker is malformed".into(),
            }
        })?;
        let host_peak_path = phase_dir.join("host_peak.json");
        let host_peak_bytes =
            fs::read(&host_peak_path).map_err(|_| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice measured host peak artifact is absent".into(),
            })?;
        let host_peak: Value = serde_json::from_slice(&host_peak_bytes).map_err(|_| {
            EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice measured host peak artifact is malformed".into(),
            }
        })?;
        let executable_sha256 = hash_file(Path::new(&row.executable))?;
        let phase_artifact_sha256 =
            crate::rehearsal::phase_artifact_digest(&phase_dir).map_err(EmberLabError::Io)?;
        let completion_valid = completion.get("schema")
            == Some(&Value::String(
                "ember-lab-minimal-slice-completion-v1".into(),
            ))
            && completion.get("producer")
                == Some(&Value::String("ember-lab-minimal-slice-producer".into()))
            && completion.get("result") == Some(&Value::String("COMPLETED".into()))
            && completion.get("job_id") == Some(&Value::String(job_id.into()))
            && completion.get("producer_pid").and_then(Value::as_u64) == Some(row.pid as u64)
            && completion
                .get("completed_at_ms")
                .and_then(Value::as_i64)
                .is_some_and(|completed_at_ms| {
                    completed_at_ms >= row.started_at_ms && completed_at_ms <= readiness_deadline_ms
                })
            && completion.get("phase_count").and_then(Value::as_u64) == Some(6)
            && completion.get("host_peak_sha256").and_then(Value::as_str)
                == Some(hash_bytes(&host_peak_bytes).as_str())
            && completion
                .get("phase_artifact_sha256")
                .and_then(Value::as_str)
                == Some(phase_artifact_sha256.as_str())
            && completion
                .get("producer_binary_sha256")
                .and_then(Value::as_str)
                == Some(executable_sha256.as_str())
            && completion
                .get("producer_source_sha256")
                .and_then(Value::as_str)
                == Some(self.ember_lab_source_sha256.as_str());
        if !completion_valid {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail:
                    "minimal-slice completion marker is not bound to this daemon job/source/binary"
                        .into(),
            });
        }
        if host_peak.get("schema") != Some(&Value::String("ember-lab-host-peak-v1".into()))
            || host_peak.get("producer")
                != Some(&Value::String("ember-lab-minimal-slice-producer".into()))
            || host_peak.get("result") != Some(&Value::String("MEASURED".into()))
            || host_peak.get("job_id") != Some(&Value::String(job_id.into()))
            || host_peak.get("producer_pid").and_then(Value::as_u64) != Some(row.pid as u64)
            || host_peak
                .get("sample_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                < 2
            || host_peak
                .get("whole_run_peak_bytes")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                == 0
        {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice measured host peak is not bound to this child/run".into(),
            });
        }
        let observed_peak_bytes = observe_owned_process_tree_peak_bytes(&row)?;
        let observed_path = phase_dir.join("host_peak.observed.json");
        if observed_path.exists() {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak receipt already exists".into(),
            });
        }
        let observed_receipt = serde_json::to_vec(&json!({
            "schema": "ember-lab-daemon-host-peak-v1",
            "producer": "ember-lab-daemon",
            "result": "MEASURED",
            "job_id": job_id,
            "pid": row.pid,
            "process_start_token": row.start_token,
            "executable_identity": row.executable,
            "job_object_name": row.job_object_name,
            "lease_epoch": row.lease_epoch,
            "producer_schema": "ember-lab-host-peak-v1",
            "producer_binary_sha256": executable_sha256,
            "producer_source_sha256": self.ember_lab_source_sha256,
            "completion_sha256": hash_bytes(&completion_bytes),
            "child_host_peak_sha256": hash_bytes(&host_peak_bytes),
            "whole_run_peak_bytes": observed_peak_bytes,
            "observed_at_ms": now_ms(),
        }))?;
        atomic_create(&observed_path, &observed_receipt)?;
        self.record_daemon_peak_event(
            job_id,
            &row,
            &hash_bytes(&observed_receipt),
            observed_peak_bytes,
            &hash_bytes(&completion_bytes),
            &hash_bytes(&host_peak_bytes),
            &executable_sha256,
        )?;
        let mut operations = std::collections::BTreeMap::<Phase, Value>::new();
        let mut produced = Vec::with_capacity(phases.len());
        for phase in phases {
            let row = self.job_process_row(job_id)?;
            if row.state != JobState::Running {
                return Err(EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: format!("minimal-slice phase {} is not running", phase.as_str()),
                });
            }
            let path = phase_dir.join(format!("{}.json", phase.as_str()));
            let bytes = fs::read(&path).map_err(|_| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: format!(
                    "minimal-slice producer output is absent for {}",
                    phase.as_str()
                ),
            })?;
            let value: Value =
                serde_json::from_slice(&bytes).map_err(|_| EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: format!(
                        "minimal-slice producer output is malformed for {}",
                        phase.as_str()
                    ),
                })?;
            if value.get("schema") != Some(&Value::String("ember-lab-phase-producer-v1".into()))
                || value.get("producer")
                    != Some(&Value::String("ember-lab-minimal-slice-producer".into()))
                || value.get("result") != Some(&Value::String("COMPLETED".into()))
                || value.get("job_id") != Some(&Value::String(job_id.into()))
                || value.get("phase") != Some(&Value::String(phase.as_str().into()))
                || value.get("producer_pid").and_then(Value::as_u64) != Some(row.pid as u64)
                || value.get("sequence").and_then(Value::as_u64)
                    != Some((produced.len() + 1) as u64)
            {
                return Err(EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: format!(
                        "minimal-slice producer identity/sequence mismatch for {}",
                        phase.as_str()
                    ),
                });
            }
            let operation = value.get("operation").cloned().ok_or_else(|| {
                EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: format!("minimal-slice operation is absent for {}", phase.as_str()),
                }
            })?;
            let operation_sha256 = hash_bytes(&serde_json::to_vec(&operation)?);
            if value.get("operation_sha256") != Some(&Value::String(operation_sha256.clone())) {
                return Err(EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: format!(
                        "minimal-slice operation hash is not bound for {}",
                        phase.as_str()
                    ),
                });
            }
            let object = operation
                .as_object()
                .ok_or_else(|| EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: format!(
                        "minimal-slice operation is not an object for {}",
                        phase.as_str()
                    ),
                })?;
            let kind = object.get("kind").and_then(Value::as_str).unwrap_or("");
            let child_file = |name: &str| -> Result<PathBuf> {
                let candidate = Path::new(name);
                if name.trim().is_empty()
                    || candidate.file_name().and_then(|v| v.to_str()) != Some(name)
                {
                    return Err(EmberLabError::InvalidTransition {
                        job_id: job_id.into(),
                        detail: "minimal-slice producer path is not a basename".into(),
                    });
                }
                Ok(phase_dir.join(name))
            };
            let hash_named = |name: &str| -> Result<String> { hash_file(&child_file(name)?) };
            match phase {
                Phase::DataVerify => {
                    if kind != "data_verify_completed"
                        || object.get("record_count").and_then(Value::as_u64) != Some(3)
                        || object.get("subset_records").and_then(Value::as_u64) != Some(3)
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "data verify did not prove three subset records".into(),
                        });
                    }
                    let name = object
                        .get("input_file")
                        .and_then(Value::as_str)
                        .ok_or_else(|| EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "data verify input file is absent".into(),
                        })?;
                    let actual = hash_named(name)?;
                    if object.get("input_sha256").and_then(Value::as_str) != Some(actual.as_str())
                        || fs::read(child_file(name)?)?
                            .split(|byte| *byte == b'\n')
                            .filter(|line| !line.is_empty())
                            .count()
                            != 3
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "data verify input bytes are not bound".into(),
                        });
                    }
                }
                Phase::Train => {
                    if kind != "train_steps_completed"
                        || object
                            .get("train_steps")
                            .and_then(Value::as_u64)
                            .unwrap_or(0)
                            < 3
                        || object
                            .get("update_count")
                            .and_then(Value::as_u64)
                            .unwrap_or(0)
                            < 3
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "train did not prove nonzero update steps".into(),
                        });
                    }
                    let name = object
                        .get("optimizer_state_file")
                        .and_then(Value::as_str)
                        .ok_or_else(|| EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "optimizer state is absent".into(),
                        })?;
                    let actual = hash_named(name)?;
                    if object.get("optimizer_state_sha256").and_then(Value::as_str)
                        != Some(actual.as_str())
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "optimizer state bytes are not bound".into(),
                        });
                    }
                }
                Phase::Checkpoint => {
                    if kind != "checkpoint_written"
                        || object.get("final_checkpoint") != Some(&Value::Bool(true))
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "final checkpoint evidence is absent".into(),
                        });
                    }
                    let name = object
                        .get("checkpoint_file")
                        .and_then(Value::as_str)
                        .ok_or_else(|| EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "checkpoint bytes are absent".into(),
                        })?;
                    let actual = hash_named(name)?;
                    if object.get("checkpoint_sha256").and_then(Value::as_str)
                        != Some(actual.as_str())
                        || object.get("source_optimizer_state_sha256")
                            != operations
                                .get(&Phase::Train)
                                .and_then(|value| value.get("optimizer_state_sha256"))
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "checkpoint is not bound to train state".into(),
                        });
                    }
                }
                Phase::Publish => {
                    if kind != "checkpoint_published" {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "checkpoint publish evidence is absent".into(),
                        });
                    }
                    let name = object
                        .get("published_file")
                        .and_then(Value::as_str)
                        .ok_or_else(|| EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "published checkpoint is absent".into(),
                        })?;
                    let actual = hash_named(name)?;
                    if object
                        .get("published_checkpoint_sha256")
                        .and_then(Value::as_str)
                        != Some(actual.as_str())
                        || object.get("source_checkpoint_sha256")
                            != operations
                                .get(&Phase::Checkpoint)
                                .and_then(|value| value.get("checkpoint_sha256"))
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "published checkpoint is not bound".into(),
                        });
                    }
                }
                Phase::SelectableCheckpoint => {
                    if kind != "selectable_checkpoint_verified" {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "selectable checkpoint evidence is absent".into(),
                        });
                    }
                    let name = object
                        .get("selected_file")
                        .and_then(Value::as_str)
                        .ok_or_else(|| EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "selected checkpoint is absent".into(),
                        })?;
                    let actual = hash_named(name)?;
                    if object
                        .get("selected_checkpoint_sha256")
                        .and_then(Value::as_str)
                        != Some(actual.as_str())
                        || object.get("selected_checkpoint_sha256")
                            != operations
                                .get(&Phase::Publish)
                                .and_then(|value| value.get("published_checkpoint_sha256"))
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "selected checkpoint is not bound".into(),
                        });
                    }
                }
                Phase::Restore => {
                    if kind != "checkpoint_restored"
                        || object.get("restore_verified") != Some(&Value::Bool(true))
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "checkpoint restore evidence is absent".into(),
                        });
                    }
                    let name = object
                        .get("restored_file")
                        .and_then(Value::as_str)
                        .ok_or_else(|| EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "restored checkpoint is absent".into(),
                        })?;
                    let actual = hash_named(name)?;
                    if object
                        .get("restored_checkpoint_sha256")
                        .and_then(Value::as_str)
                        != Some(actual.as_str())
                        || object.get("restored_checkpoint_sha256")
                            != operations
                                .get(&Phase::SelectableCheckpoint)
                                .and_then(|value| value.get("selected_checkpoint_sha256"))
                    {
                        return Err(EmberLabError::InvalidTransition {
                            job_id: job_id.into(),
                            detail: "restored checkpoint is not bound".into(),
                        });
                    }
                }
                Phase::Admission => unreachable!("admission is owned by dispatch_manifest"),
            }
            self.verify_identity(job_id)?;
            if !self
                .job_event_kinds(job_id)?
                .iter()
                .any(|kind| kind == "job_started")
            {
                return Err(EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: "current Ember Lab phase owner has no durable job-start evidence"
                        .into(),
                });
            }
            let observed_at_ms = now_ms();
            self.record_phase_operation(job_id, phase, &operation_sha256, observed_at_ms, &row)?;
            let evidence_sha256 = hash_bytes(&bytes);
            self.record_phase_event(
                job_id,
                phase,
                &path,
                &evidence_sha256,
                &operation_sha256,
                observed_at_ms,
                &row,
            )?;
            operations.insert(phase, operation);
            produced.push(PhaseEvidence {
                phase,
                path,
                sha256: evidence_sha256,
            });
        }
        Ok(produced)
    }

    /// Consume the six current Ember Lab phase outputs for a live dispatched job.
    /// The child producer performs each operation; this method only records the
    /// existing bytes through the daemon's fenced event authority.
    pub fn execute_minimal_episode(
        &self,
        job_id: &str,
        expected_whole_run_peak_bytes: u64,
        readiness_deadline_ms: i64,
    ) -> Result<Vec<crate::rehearsal::PhaseEvidence>> {
        self.consume_minimal_slice(job_id, expected_whole_run_peak_bytes, readiness_deadline_ms)
    }

    /// Return the immutable daemon-owned whole-process-tree observation that
    /// was created during minimal-slice consumption.  Callers must use this
    /// artifact for the terminal rehearsal receipt; the producer's raw
    /// `host_peak.json` is only supporting evidence.
    pub fn authoritative_whole_run_peak(&self, job_id: &str) -> Result<(PathBuf, String, u64)> {
        let row = self.job_process_row(job_id)?;
        if row.state != JobState::Running || !self.lease_matches_process_row(job_id, &row)? {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak job row is no longer running under its lease"
                    .into(),
            });
        }
        #[cfg(windows)]
        match open_live_status(&row) {
            LiveStatus::Verified(_) => {}
            LiveStatus::Dead => {
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })
            }
            LiveStatus::Orphaned(detail) | LiveStatus::IdentityConflict(detail) => {
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                })
            }
        }
        #[cfg(not(windows))]
        {
            let identity =
                inspect_process(row.pid).map_err(|_| EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })?;
            if identity.start_token != row.start_token
                || !same_executable(&identity.executable, &row.executable)
            {
                return Err(EmberLabError::ProcessIdentityMismatch {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
        }
        let path = self
            .log_dir
            .join("rehearsal")
            .join(hash_bytes(job_id.as_bytes()))
            .join("host_peak.observed.json");
        let bytes = fs::read(&path).map_err(|_| EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "daemon-owned whole-run peak receipt is absent".into(),
        })?;
        let value: Value =
            serde_json::from_slice(&bytes).map_err(|_| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak receipt is malformed".into(),
            })?;
        let phase_dir = path
            .parent()
            .ok_or_else(|| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak receipt has no phase directory".into(),
            })?;
        let completion_path = phase_dir.join("completion.json");
        let child_peak_path = phase_dir.join("host_peak.json");
        let completion_bytes =
            fs::read(&completion_path).map_err(|_| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice completion marker is absent while reopening peak".into(),
            })?;
        let child_peak_bytes =
            fs::read(&child_peak_path).map_err(|_| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice child peak is absent while reopening peak".into(),
            })?;
        let completion: Value = serde_json::from_slice(&completion_bytes).map_err(|_| {
            EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice completion marker is malformed while reopening peak".into(),
            }
        })?;
        let child_peak: Value = serde_json::from_slice(&child_peak_bytes).map_err(|_| {
            EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "minimal-slice child peak is malformed while reopening peak".into(),
            }
        })?;
        let binary_sha256 = hash_file(Path::new(&row.executable))?;
        let completion_sha256 = hash_bytes(&completion_bytes);
        let child_peak_sha256 = hash_bytes(&child_peak_bytes);
        let phase_artifact_sha256 =
            crate::rehearsal::phase_artifact_digest(phase_dir).map_err(EmberLabError::Io)?;
        let child_peak_valid = child_peak.get("schema")
            == Some(&Value::String("ember-lab-host-peak-v1".into()))
            && child_peak.get("producer")
                == Some(&Value::String("ember-lab-minimal-slice-producer".into()))
            && child_peak.get("result") == Some(&Value::String("MEASURED".into()))
            && child_peak.get("job_id") == Some(&Value::String(job_id.into()))
            && child_peak.get("producer_pid").and_then(Value::as_u64) == Some(row.pid as u64)
            && child_peak
                .get("sample_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                >= 2
            && child_peak
                .get("whole_run_peak_bytes")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                > 0;
        let completion_valid = completion.get("schema")
            == Some(&Value::String(
                "ember-lab-minimal-slice-completion-v1".into(),
            ))
            && completion.get("producer")
                == Some(&Value::String("ember-lab-minimal-slice-producer".into()))
            && completion.get("result") == Some(&Value::String("COMPLETED".into()))
            && completion.get("job_id") == Some(&Value::String(job_id.into()))
            && completion.get("producer_pid").and_then(Value::as_u64) == Some(row.pid as u64)
            && completion.get("phase_count").and_then(Value::as_u64) == Some(6)
            && completion.get("host_peak_sha256").and_then(Value::as_str)
                == Some(child_peak_sha256.as_str())
            && completion
                .get("phase_artifact_sha256")
                .and_then(Value::as_str)
                == Some(phase_artifact_sha256.as_str())
            && completion
                .get("producer_binary_sha256")
                .and_then(Value::as_str)
                == Some(binary_sha256.as_str())
            && completion
                .get("producer_source_sha256")
                .and_then(Value::as_str)
                == Some(self.ember_lab_source_sha256.as_str());
        if !child_peak_valid || !completion_valid {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak child evidence is not bound to the current process/source/binary".into(),
            });
        }
        let observed_valid = value.get("schema")
            == Some(&Value::String("ember-lab-daemon-host-peak-v1".into()))
            && value.get("producer") == Some(&Value::String("ember-lab-daemon".into()))
            && value.get("result") == Some(&Value::String("MEASURED".into()))
            && value.get("job_id") == Some(&Value::String(job_id.into()))
            && value.get("pid").and_then(Value::as_u64) == Some(row.pid as u64)
            && value.get("process_start_token").and_then(Value::as_str)
                == Some(row.start_token.as_str())
            && value.get("executable_identity").and_then(Value::as_str)
                == Some(row.executable.as_str())
            && value.get("job_object_name").and_then(Value::as_str)
                == Some(row.job_object_name.as_str())
            && value.get("lease_epoch").and_then(Value::as_i64) == Some(row.lease_epoch)
            && value.get("producer_schema").and_then(Value::as_str)
                == Some("ember-lab-host-peak-v1")
            && value.get("producer_binary_sha256").and_then(Value::as_str)
                == Some(binary_sha256.as_str())
            && value.get("producer_source_sha256").and_then(Value::as_str)
                == Some(self.ember_lab_source_sha256.as_str())
            && value.get("completion_sha256").and_then(Value::as_str)
                == Some(completion_sha256.as_str())
            && value.get("child_host_peak_sha256").and_then(Value::as_str)
                == Some(child_peak_sha256.as_str())
            && value
                .get("whole_run_peak_bytes")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                > 0;
        if !observed_valid {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak receipt is not valid".into(),
            });
        }
        let observed_sha256 = hash_bytes(&bytes);
        let event_payload: Option<String> = self
            .conn()?
            .query_row(
                "SELECT payload_json FROM events WHERE job_id=?1 AND kind='ember_lab_daemon_host_peak' ORDER BY seq DESC LIMIT 1",
                [job_id],
                |row| row.get(0),
            )
            .optional()?;
        let Some(event_payload) = event_payload else {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak has no persisted authority event".into(),
            });
        };
        let event: Value = serde_json::from_str(&event_payload)?;
        let event_matches = event.get("producer")
            == Some(&Value::String("ember-lab-daemon".into()))
            && event.get("job_id") == Some(&Value::String(job_id.into()))
            && event.get("observed_sha256").and_then(Value::as_str)
                == Some(observed_sha256.as_str())
            && event.get("whole_run_peak_bytes").and_then(Value::as_u64)
                == value.get("whole_run_peak_bytes").and_then(Value::as_u64)
            && event.get("completion_sha256").and_then(Value::as_str)
                == Some(completion_sha256.as_str())
            && event.get("child_host_peak_sha256").and_then(Value::as_str)
                == Some(child_peak_sha256.as_str())
            && event.get("pid").and_then(Value::as_u64) == Some(row.pid as u64)
            && event.get("process_start_token").and_then(Value::as_str)
                == Some(row.start_token.as_str())
            && event.get("executable_identity").and_then(Value::as_str)
                == Some(row.executable.as_str())
            && event.get("job_object_name").and_then(Value::as_str)
                == Some(row.job_object_name.as_str())
            && event.get("lease_epoch").and_then(Value::as_i64) == Some(row.lease_epoch)
            && event.get("producer_binary_sha256").and_then(Value::as_str)
                == Some(binary_sha256.as_str())
            && event.get("producer_source_sha256").and_then(Value::as_str)
                == Some(self.ember_lab_source_sha256.as_str());
        if !event_matches {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak receipt changed after authority event".into(),
            });
        }
        let sha256 = hash_bytes(&bytes);
        let peak = value
            .get("whole_run_peak_bytes")
            .and_then(Value::as_u64)
            .ok_or_else(|| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak is missing".into(),
            })?;
        Ok((path, sha256, peak))
    }

    /// Persist one phase event through the daemon's existing job/lease
    /// authority.  This private helper is reachable only from production phase
    /// owners; callers can never supply a producer/authority string to it.
    fn record_phase_operation(
        &self,
        job_id: &str,
        phase: crate::rehearsal::Phase,
        operation_sha256: &str,
        observed_at_ms: i64,
        row: &JobProcessRow,
    ) -> Result<()> {
        let operation_authority_sha256 = hash_bytes(
            format!(
                "ember-lab-phase-operation-v1|{}|{}|{}|{}|{}|{}",
                job_id,
                phase.as_str(),
                operation_sha256,
                row.lease_epoch,
                row.pid,
                self.ember_lab_source_sha256,
            )
            .as_bytes(),
        );
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let inserted = tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
            params![
                job_id,
                observed_at_ms,
                format!("ember_lab_phase_operation_{}", phase.as_str()),
                json!({
                    "producer": "ember-lab-daemon",
                    "job_id": job_id,
                    "phase": phase.as_str(),
                    "operation_sha256": operation_sha256,
                    "operation_authority_sha256": operation_authority_sha256,
                    "lease_epoch": row.lease_epoch,
                    "pid": row.pid,
                })
                .to_string(),
            ],
        )?;
        if inserted != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "current Ember Lab phase operation was not persisted".into(),
            });
        }
        tx.commit()?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn record_daemon_peak_event(
        &self,
        job_id: &str,
        row: &JobProcessRow,
        observed_sha256: &str,
        whole_run_peak_bytes: u64,
        completion_sha256: &str,
        child_host_peak_sha256: &str,
        producer_binary_sha256: &str,
    ) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let inserted = tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'ember_lab_daemon_host_peak',?3)",
            params![
                job_id,
                now_ms(),
                json!({
                    "producer": "ember-lab-daemon",
                    "job_id": job_id,
                    "observed_sha256": observed_sha256,
                    "whole_run_peak_bytes": whole_run_peak_bytes,
                    "completion_sha256": completion_sha256,
                    "child_host_peak_sha256": child_host_peak_sha256,
                    "pid": row.pid,
                    "process_start_token": row.start_token,
                    "executable_identity": row.executable,
                    "job_object_name": row.job_object_name,
                    "lease_epoch": row.lease_epoch,
                    "producer_binary_sha256": producer_binary_sha256,
                    "producer_source_sha256": self.ember_lab_source_sha256,
                })
                .to_string(),
            ],
        )?;
        if inserted != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "daemon-owned whole-run peak authority event was not persisted".into(),
            });
        }
        tx.commit()?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn record_phase_event(
        &self,
        job_id: &str,
        phase: crate::rehearsal::Phase,
        evidence_path: &Path,
        evidence_sha256: &str,
        operation_sha256: &str,
        observed_at_ms: i64,
        row: &JobProcessRow,
    ) -> Result<()> {
        let canonical = fs::canonicalize(evidence_path)?;
        if hash_file(&canonical)? != evidence_sha256 {
            return Err(EmberLabError::DispatchBindingMismatch {
                path: canonical,
                expected: evidence_sha256.into(),
                actual: hash_file(evidence_path)?,
            });
        }
        let evidence_file_name = canonical
            .file_name()
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "phase evidence path has no file name".into(),
            })?
            .to_string_lossy()
            .into_owned();
        let event_authority_sha256 = hash_bytes(
            format!(
                "ember-lab-phase-authority-v2|{}|{}|{}|{}|{}|{}|{}|{}",
                job_id,
                phase.as_str(),
                evidence_sha256,
                operation_sha256,
                row.lease_epoch,
                row.pid,
                self.ember_lab_binary_sha256,
                self.ember_lab_source_sha256,
            )
            .as_bytes(),
        );
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let fenced = tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
            params![
                job_id,
                observed_at_ms,
                format!("ember_lab_phase_{}", phase.as_str()),
                json!({
                    "producer": "ember-lab-daemon",
                    "job_id": job_id,
                    "phase": phase.as_str(),
                    "evidence_file_name": evidence_file_name,
                    "evidence_sha256": evidence_sha256,
                    "operation_sha256": operation_sha256,
                    "event_authority_sha256": event_authority_sha256,
                    "lease_epoch": row.lease_epoch,
                    "pid": row.pid,
                })
                .to_string(),
            ],
        )?;
        if fenced != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "current Ember Lab phase event was not persisted".into(),
            });
        }
        tx.commit()?;
        Ok(())
    }

    /// Consume only phase evidence already emitted by the current daemon
    /// owners.  No file or event is created here; missing, forged, malformed,
    /// or unbound evidence fails the episode before a later phase can run.
    pub fn load_authorized_phase_evidence(
        &self,
        job_id: &str,
    ) -> Result<Vec<crate::rehearsal::PhaseEvidence>> {
        use crate::rehearsal::{Phase, PhaseEvidence};

        let expected_root = self
            .log_dir
            .join("rehearsal")
            .join(hash_bytes(job_id.as_bytes()));
        let mut consumed = Vec::with_capacity(6);
        for phase in [
            Phase::DataVerify,
            Phase::Train,
            Phase::Checkpoint,
            Phase::Publish,
            Phase::SelectableCheckpoint,
            Phase::Restore,
        ] {
            let kind = format!("ember_lab_phase_{}", phase.as_str());
            // Materialize the event payloads before asking phase_event_authorized
            // to open its own connection. Holding the query cursor across that
            // call can make SQLite's Windows WAL busy timeout fire once per
            // phase, turning a six-phase consume into an apparent hang.
            let payloads: Vec<String> = {
                let conn = self.conn()?;
                let mut stmt = conn.prepare(
                    "SELECT payload_json FROM events WHERE job_id=?1 AND kind=?2 ORDER BY seq",
                )?;
                let mut payloads = Vec::new();
                for payload in
                    stmt.query_map(params![job_id, kind], |row| row.get::<_, String>(0))?
                {
                    payloads.push(payload?);
                }
                payloads
            };
            let mut found = None;
            for payload in payloads {
                let value: Value = match serde_json::from_str(&payload) {
                    Ok(value) => value,
                    Err(_) => continue,
                };
                let Some(file_name) = value.get("evidence_file_name").and_then(Value::as_str)
                else {
                    continue;
                };
                let Some(evidence_sha256) = value.get("evidence_sha256").and_then(Value::as_str)
                else {
                    continue;
                };
                let Some(operation_sha256) = value.get("operation_sha256").and_then(Value::as_str)
                else {
                    continue;
                };
                let path = expected_root.join(file_name);
                if path.parent() != Some(expected_root.as_path())
                    || value.get("producer") != Some(&Value::String("ember-lab-daemon".into()))
                    || value.get("job_id") != Some(&Value::String(job_id.into()))
                    || value.get("phase") != Some(&Value::String(phase.as_str().into()))
                    || !path.is_file()
                    || !self.phase_event_authorized(job_id, phase.as_str(), evidence_sha256)?
                {
                    continue;
                }
                let bytes = fs::read(&path)?;
                let evidence: Value = match serde_json::from_slice(&bytes) {
                    Ok(value) => value,
                    Err(_) => continue,
                };
                if evidence.get("schema")
                    != Some(&Value::String("ember-lab-phase-producer-v1".into()))
                    || evidence.get("producer")
                        != Some(&Value::String("ember-lab-minimal-slice-producer".into()))
                    || evidence.get("result") != Some(&Value::String("COMPLETED".into()))
                    || evidence.get("job_id") != Some(&Value::String(job_id.into()))
                    || evidence.get("phase") != Some(&Value::String(phase.as_str().into()))
                    || evidence.get("operation_sha256")
                        != Some(&Value::String(operation_sha256.into()))
                    || hash_bytes(&bytes) != evidence_sha256
                {
                    continue;
                }
                found = Some(PhaseEvidence {
                    phase,
                    path,
                    sha256: evidence_sha256.into(),
                });
                break;
            }
            let evidence = found.ok_or_else(|| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: format!(
                    "current Ember Lab production phase evidence is absent or unbound for {}",
                    phase.as_str()
                ),
            })?;
            consumed.push(evidence);
        }
        Ok(consumed)
    }

    pub fn phase_event_authorized(
        &self,
        job_id: &str,
        phase: &str,
        evidence_sha256: &str,
    ) -> Result<bool> {
        let expected_root = self
            .log_dir
            .join("rehearsal")
            .join(hash_bytes(job_id.as_bytes()));
        let kind = format!("ember_lab_phase_{phase}");
        let conn = self.conn()?;
        let mut stmt = conn
            .prepare("SELECT payload_json FROM events WHERE job_id=?1 AND kind=?2 ORDER BY seq")?;
        for payload in stmt.query_map(params![job_id, kind], |row| row.get::<_, String>(0))? {
            let payload = payload?;
            let value: Value = serde_json::from_str(&payload)?;
            let Some(file_name) = value.get("evidence_file_name").and_then(Value::as_str) else {
                continue;
            };
            let Some(lease_epoch) = value.get("lease_epoch").and_then(Value::as_i64) else {
                continue;
            };
            let Some(pid) = value.get("pid").and_then(Value::as_u64) else {
                continue;
            };
            let Some(operation_sha256) = value.get("operation_sha256").and_then(Value::as_str)
            else {
                continue;
            };
            let expected_path = expected_root.join(file_name);
            if expected_path.parent() != Some(expected_root.as_path())
                || !expected_path.is_file()
                || hash_file(&expected_path)? != evidence_sha256
            {
                continue;
            }
            let authority = hash_bytes(
                format!(
                    "ember-lab-phase-authority-v2|{}|{}|{}|{}|{}|{}|{}|{}",
                    job_id,
                    phase,
                    evidence_sha256,
                    operation_sha256,
                    lease_epoch,
                    pid,
                    self.ember_lab_binary_sha256,
                    self.ember_lab_source_sha256,
                )
                .as_bytes(),
            );
            let operation_kind = format!("ember_lab_phase_operation_{phase}");
            let mut operation_stmt =
                conn.prepare("SELECT payload_json FROM events WHERE job_id=?1 AND kind=?2")?;
            let operation_bound = operation_stmt
                .query_map(params![job_id, operation_kind], |row| {
                    row.get::<_, String>(0)
                })?
                .filter_map(|payload| payload.ok())
                .any(|payload| {
                    let Ok(operation) = serde_json::from_str::<Value>(&payload) else {
                        return false;
                    };
                    let Some(operation_authority) = operation
                        .get("operation_authority_sha256")
                        .and_then(Value::as_str)
                    else {
                        return false;
                    };
                    let expected_operation_authority = hash_bytes(
                        format!(
                            "ember-lab-phase-operation-v1|{}|{}|{}|{}|{}|{}",
                            job_id,
                            phase,
                            operation_sha256,
                            lease_epoch,
                            pid,
                            self.ember_lab_source_sha256,
                        )
                        .as_bytes(),
                    );
                    operation.get("producer") == Some(&Value::String("ember-lab-daemon".into()))
                        && operation.get("job_id") == Some(&Value::String(job_id.into()))
                        && operation.get("phase") == Some(&Value::String(phase.into()))
                        && operation.get("operation_sha256")
                            == Some(&Value::String(operation_sha256.into()))
                        && operation.get("lease_epoch") == Some(&Value::from(lease_epoch))
                        && operation.get("pid") == Some(&Value::from(pid))
                        && operation_authority == expected_operation_authority
                });
            if operation_bound
                && value.get("producer") == Some(&Value::String("ember-lab-daemon".into()))
                && value.get("job_id") == Some(&Value::String(job_id.into()))
                && value.get("phase") == Some(&Value::String(phase.into()))
                && value.get("evidence_sha256") == Some(&Value::String(evidence_sha256.into()))
                && value.get("event_authority_sha256") == Some(&Value::String(authority))
            {
                return Ok(true);
            }
        }
        Ok(false)
    }

    pub fn reconcile(&self) -> Result<()> {
        let jobs: Vec<String> = {
            let conn = self.conn()?;
            let mut stmt = conn.prepare(
                "SELECT job_id FROM jobs WHERE state IN ('starting','prepared','running','stopping') ORDER BY job_id",
            )?;
            let rows = stmt
                .query_map([], |r| r.get(0))?
                .collect::<std::result::Result<_, _>>()?;
            rows
        };
        for job_id in jobs {
            let row = self.job_process_row(&job_id)?;
            #[cfg(windows)]
            match (row.state, open_live_status(&row)) {
                (JobState::Starting, LiveStatus::Dead) => {
                    self.mark_dead(&job_id, &row, "job_reconciled_unlaunched")?
                }
                (JobState::Starting, _) => {
                    self.reclaim_starting_job(&job_id, &row, "job_reconciled_unrecorded_process")?
                }
                (JobState::Prepared, LiveStatus::Verified(live)) => {
                    match self.transition_prepared_running(&job_id, &row) {
                        Ok(true) => self.retain_and_monitor(&job_id, live)?,
                        Ok(false) => {}
                        Err(PreparedTransitionError::BeforeResume(error)) => return Err(error),
                        Err(PreparedTransitionError::AfterResume(transition_error)) => {
                            if let Err(termination_error) = terminate_live(&live) {
                                self.live
                                    .lock()
                                    .unwrap_or_else(|poisoned| poisoned.into_inner())
                                    .insert(
                                        job_id.clone(),
                                        RetainedProcess {
                                            live,
                                            monitored: false,
                                        },
                                    );
                                return Err(EmberLabError::PreparedResumeCleanupFailed {
                                    job_id,
                                    transition: format!("{transition_error:?}"),
                                    cleanup: format!("{termination_error:?}"),
                                });
                            }
                            if let Err(cleanup_error) =
                                self.mark_failed(&job_id, "job_recovered_resume_commit_failed")
                            {
                                return Err(EmberLabError::PreparedResumeCleanupFailed {
                                    job_id,
                                    transition: format!("{transition_error:?}"),
                                    cleanup: format!("{cleanup_error:?}"),
                                });
                            }
                            return Err(transition_error);
                        }
                    }
                }
                (JobState::Prepared, LiveStatus::Dead) => {
                    self.mark_dead(&job_id, &row, "job_reconciled_dead")?
                }
                (JobState::Running, LiveStatus::Dead) => {
                    self.mark_exited_unknown(&job_id, &row, "job_reconciled_exited_unknown")?
                }
                (JobState::Running, LiveStatus::Verified(live)) => {
                    self.commit_adoption(&job_id, &row)?;
                    self.retain_and_monitor(&job_id, live)?;
                }
                (JobState::Stopping, LiveStatus::Verified(live)) => {
                    terminate_live(&live)?;
                    self.finalize_stopped(&job_id, &row, true)?;
                    self.live
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner())
                        .remove(&job_id);
                }
                (JobState::Stopping, LiveStatus::Dead) => {
                    self.finalize_stopped(&job_id, &row, false)?;
                    self.live
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner())
                        .remove(&job_id);
                }
                (_, LiveStatus::Orphaned(detail)) => self.mark_uncertain(
                    &job_id,
                    &row,
                    JobState::Orphaned,
                    "job_reconciled_orphaned",
                    &detail,
                )?,
                (_, LiveStatus::IdentityConflict(detail)) => self.mark_uncertain(
                    &job_id,
                    &row,
                    JobState::IdentityConflict,
                    "job_reconciled_identity_conflict",
                    &detail,
                )?,
                _ => {}
            }
            #[cfg(not(windows))]
            if row.state == JobState::Running {
                let _ = self.adopt_job(&job_id);
            }
        }
        Ok(())
    }

    fn commit_adoption(&self, job_id: &str, row: &JobProcessRow) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET updated_at_ms=?2 WHERE job_id=?1 AND state='running' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.lease_epoch],
        )?;
        if changed != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "adoption lost its state or lease fence".into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_adopted',?3)",
            params![
                job_id,
                now_ms(),
                json!({"pid":row.pid,"job_object_name":row.job_object_name}).to_string(),
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    #[cfg(windows)]
    fn transition_prepared_running(
        &self,
        job_id: &str,
        row: &JobProcessRow,
    ) -> std::result::Result<bool, PreparedTransitionError> {
        let mut conn = self.conn().map_err(PreparedTransitionError::BeforeResume)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| PreparedTransitionError::BeforeResume(error.into()))?;
        let launch_at_ms = now_ms();
        let fenced = tx.execute(
            "UPDATE jobs SET updated_at_ms=?2 WHERE job_id=?1 AND state='prepared' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, launch_at_ms, row.lease_epoch],
        ).map_err(|error| PreparedTransitionError::BeforeResume(error.into()))?;
        if fenced != 1 {
            return Err(PreparedTransitionError::BeforeResume(
                EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: "prepared reconciliation lost its pre-resume state or lease fence"
                        .into(),
                },
            ));
        }
        let outage: Option<(i64, String)> = tx
            .query_row(
                "SELECT ends_at_ms,reason FROM planned_outages WHERE resource=?1 AND cancelled_at_ms IS NULL AND starts_at_ms<=?2 AND ends_at_ms>?2 ORDER BY outage_id DESC LIMIT 1",
                params![row.resource, launch_at_ms],
                |outage| Ok((outage.get(0)?, outage.get(1)?)),
            )
            .optional()
            .map_err(|error| PreparedTransitionError::BeforeResume(error.into()))?;
        if let Some((ends_at_ms, reason)) = outage {
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_resume_deferred_outage',?3)",
                params![
                    job_id,
                    launch_at_ms,
                    json!({"resource":row.resource,"ends_at_ms":ends_at_ms,"reason":reason}).to_string()
                ],
            )
            .map_err(|error| PreparedTransitionError::BeforeResume(error.into()))?;
            tx.commit()
                .map_err(|error| PreparedTransitionError::BeforeResume(error.into()))?;
            return Ok(false);
        }
        resume_thread_id(row.main_thread_id).map_err(PreparedTransitionError::BeforeResume)?;
        let changed = tx.execute(
            "UPDATE jobs SET state='running',updated_at_ms=?2 WHERE job_id=?1 AND state='prepared' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.lease_epoch],
        ).map_err(|error| PreparedTransitionError::AfterResume(error.into()))?;
        if changed != 1 {
            return Err(PreparedTransitionError::AfterResume(
                EmberLabError::InvalidTransition {
                    job_id: job_id.into(),
                    detail: "prepared reconciliation lost its state or lease fence".into(),
                },
            ));
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_started',?3)",
            params![
                job_id,
                now_ms(),
                json!({"pid":row.pid,"reconciled":true}).to_string()
            ],
        )
        .map_err(|error| PreparedTransitionError::AfterResume(error.into()))?;
        tx.commit()
            .map_err(|error| PreparedTransitionError::AfterResume(error.into()))?;
        Ok(true)
    }

    fn finalize_stopped(&self, job_id: &str, row: &JobProcessRow, seal_logs: bool) -> Result<()> {
        let mut conn = self.conn()?;
        finalize_stopped_in_connection(&mut conn, job_id, row, seal_logs)
    }

    fn reclaim_starting_job(&self, job_id: &str, row: &JobProcessRow, kind: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let fenced = tx.execute(
            "UPDATE jobs SET updated_at_ms=?2 WHERE job_id=?1 AND state='starting' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.lease_epoch],
        )?;
        if fenced != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "starting reconciliation lost its state or lease epoch fence".into(),
            });
        }
        terminate_job_object_by_name(&row.job_object_name)?;
        let failed = tx.execute(
            "UPDATE jobs SET state='failed',outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events),updated_at_ms=?2 WHERE job_id=?1 AND state='starting' AND lease_epoch=?3",
            params![job_id, now_ms(), row.lease_epoch],
        )?;
        if failed != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "starting reconciliation lost its held state fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "starting reconciliation lost its lease epoch".into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,'{}')",
            params![job_id, now_ms(), kind],
        )?;
        tx.commit()?;
        Ok(())
    }

    fn mark_uncertain(
        &self,
        job_id: &str,
        row: &JobProcessRow,
        state: JobState,
        kind: &str,
        detail: &str,
    ) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET state=?2,updated_at_ms=?3 WHERE job_id=?1 AND state=?4 AND lease_epoch=?5 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, state.as_str(), now_ms(), row.state.as_str(), row.lease_epoch],
        )?;
        if changed != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "uncertain reconciliation lost its state or lease epoch fence".into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
            params![
                job_id,
                now_ms(),
                kind,
                json!({"detail":detail,"lease_retained":true}).to_string()
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    fn mark_failed(&self, job_id: &str, kind: &str) -> Result<()> {
        let row = self.job_process_row(job_id)?;
        self.mark_dead(job_id, &row, kind)
    }

    fn mark_exited_unknown(&self, job_id: &str, row: &JobProcessRow, kind: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET state='exited',exit_code=NULL,exited_at_ms=?2,outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events),updated_at_ms=?2 WHERE job_id=?1 AND state=?3 AND lease_epoch=?4 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.state.as_str(), row.lease_epoch],
        )?;
        if changed != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "unknown-exit reconciliation lost its state or lease epoch fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "unknown-exit reconciliation lost its lease epoch".into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
            params![
                job_id,
                now_ms(),
                kind,
                json!({"pid":row.pid,"exit_code":"unknown"}).to_string(),
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    fn mark_dead(&self, job_id: &str, row: &JobProcessRow, kind: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET state='failed',outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events),updated_at_ms=?2 WHERE job_id=?1 AND state=?3 AND lease_epoch=?4 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.state.as_str(), row.lease_epoch],
        )?;
        if changed != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "dead reconciliation lost its state or lease epoch fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "dead reconciliation lost its lease epoch".into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,'{}')",
            params![job_id, now_ms(), kind],
        )?;
        tx.commit()?;
        Ok(())
    }

    fn job_process_row(&self, job_id: &str) -> Result<JobProcessRow> {
        let conn = self.conn()?;
        job_process_row_from_connection(&conn, job_id)
    }

    fn lease_matches_process_row(&self, job_id: &str, row: &JobProcessRow) -> Result<bool> {
        let conn = self.conn()?;
        Ok(conn
            .query_row(
                "SELECT 1 FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
                params![row.resource, job_id, row.lease_epoch],
                |_| Ok(()),
            )
            .optional()?
            .is_some())
    }
}

fn finalize_stopped_in_connection(
    conn: &mut Connection,
    job_id: &str,
    row: &JobProcessRow,
    seal_logs: bool,
) -> Result<()> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let (stdout_sha256, stderr_sha256) = if seal_logs {
        let (stdout, stderr) = seal_log_hashes(&tx, job_id)?;
        (Some(stdout), Some(stderr))
    } else {
        (None, None)
    };
    let changed = tx.execute(
        "UPDATE jobs SET state='stopped',stdout_log_sha256=?4,stderr_log_sha256=?5,outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events),updated_at_ms=?2 WHERE job_id=?1 AND state='stopping' AND lease_epoch=?3",
        params![job_id, now_ms(), row.lease_epoch, stdout_sha256, stderr_sha256],
    )?;
    if changed != 1 {
        return Err(EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "stop finalization lost its state or lease epoch fence".into(),
        });
    }
    let released = tx.execute(
        "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
        params![row.resource, job_id, row.lease_epoch],
    )?;
    if released != 1 {
        return Err(EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "stop finalization lost its lease epoch".into(),
        });
    }
    tx.execute(
        "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_stopped',?3)",
        params![
            job_id,
            now_ms(),
            json!({"pid":row.pid,"lease_epoch":row.lease_epoch}).to_string()
        ],
    )?;
    tx.commit()?;
    Ok(())
}

fn job_process_row_from_connection(conn: &Connection, job_id: &str) -> Result<JobProcessRow> {
    conn.query_row(
        "SELECT pid,process_start_token,executable_identity,resource,state,job_object_name,main_thread_id,lease_epoch,stdout_log_path,stderr_log_path,stdout_child_handle,stderr_child_handle,started_at_ms FROM jobs WHERE job_id=?1",
        [job_id],
        |row| {
            let state: String = row.get(4)?;
            Ok((
                row.get::<_, u32>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                state,
                row.get::<_, String>(5)?,
                row.get::<_, u32>(6)?,
                row.get::<_, i64>(7)?,
                row.get::<_, String>(8)?,
                row.get::<_, String>(9)?,
                row.get::<_, i64>(10)?,
                row.get::<_, i64>(11)?,
                row.get::<_, i64>(12)?,
            ))
        },
    )
    .optional()?
    .ok_or_else(|| EmberLabError::JobNotFound {
        job_id: job_id.into(),
    })
    .and_then(|row| {
        Ok(JobProcessRow {
            pid: row.0,
            start_token: row.1,
            executable: row.2,
            resource: row.3,
            state: JobState::parse(&row.4)?,
            job_object_name: row.5,
            main_thread_id: row.6,
            lease_epoch: row.7,
            stdout_log_path: PathBuf::from(row.8),
            stderr_log_path: PathBuf::from(row.9),
            stdout_child_handle: row.10,
            stderr_child_handle: row.11,
            started_at_ms: row.12,
        })
    })
}

fn observe_owned_process_tree_peak_bytes(row: &JobProcessRow) -> Result<u64> {
    #[cfg(windows)]
    {
        use std::mem::zeroed;
        use windows_sys::Win32::Foundation::CloseHandle;
        use windows_sys::Win32::System::JobObjects::{
            JobObjectExtendedLimitInformation, OpenJobObjectW, QueryInformationJobObject,
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        };
        const JOB_OBJECT_QUERY_RIGHT: u32 = 0x0004;
        let name = wide(&row.job_object_name);
        let job = unsafe { OpenJobObjectW(JOB_OBJECT_QUERY_RIGHT, 0, name.as_ptr()) };
        if job.is_null() {
            return Err(EmberLabError::ProcessUnavailable {
                job_id: String::new(),
                pid: row.pid,
            });
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        let ok = unsafe {
            QueryInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                (&mut info as *mut JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        unsafe { CloseHandle(job) };
        if ok == 0 || info.PeakJobMemoryUsed == 0 {
            return Err(EmberLabError::ProcessUnavailable {
                job_id: String::new(),
                pid: row.pid,
            });
        }
        Ok(info.PeakJobMemoryUsed as u64)
    }
    #[cfg(not(windows))]
    {
        let status = fs::read_to_string(format!("/proc/{}/status", row.pid))?;
        let kib = status
            .lines()
            .find_map(|line| line.strip_prefix("VmHWM:")?.split_whitespace().next())
            .ok_or_else(|| EmberLabError::ProcessUnavailable {
                job_id: String::new(),
                pid: row.pid,
            })?
            .parse::<u64>()
            .map_err(|_| EmberLabError::ProcessUnavailable {
                job_id: String::new(),
                pid: row.pid,
            })?;
        kib.checked_mul(1024)
            .filter(|bytes| *bytes > 0)
            .ok_or_else(|| EmberLabError::ProcessUnavailable {
                job_id: String::new(),
                pid: row.pid,
            })
    }
}

struct JobProcessRow {
    pid: u32,
    start_token: String,
    executable: String,
    resource: String,
    state: JobState,
    job_object_name: String,
    main_thread_id: u32,
    lease_epoch: i64,
    stdout_log_path: PathBuf,
    stderr_log_path: PathBuf,
    stdout_child_handle: i64,
    stderr_child_handle: i64,
    started_at_ms: i64,
}

fn same_job_process_fence(expected: &JobProcessRow, observed: &JobProcessRow) -> bool {
    expected.pid == observed.pid
        && expected.start_token == observed.start_token
        && expected.executable == observed.executable
        && expected.resource == observed.resource
        && expected.job_object_name == observed.job_object_name
        && expected.main_thread_id == observed.main_thread_id
        && expected.lease_epoch == observed.lease_epoch
}

#[cfg(windows)]
enum PreparedTransitionError {
    BeforeResume(EmberLabError),
    AfterResume(EmberLabError),
}

struct ReceiptRow {
    state: String,
    resource: String,
    identity_sha256: String,
    executable_identity: String,
    pid: i64,
    restart_policy: String,
    stdout_log_path: String,
    stderr_log_path: String,
    exit_code: Option<i64>,
    stdout_log_sha256: Option<String>,
    stderr_log_sha256: Option<String>,
    outage_event_cutoff_seq: Option<i64>,
}

#[derive(Clone)]
struct ProcessIdentity {
    start_token: String,
    executable: String,
}

fn validate_hash(value: &str) -> Result<()> {
    if value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        Ok(())
    } else {
        Err(EmberLabError::InvalidIdentityHash {
            value: value.into(),
        })
    }
}
/// `pub`: also the self-identity hash `main.rs`'s `verify-training` subcommand reuses for a
/// one-shot command's `ember_lab_binary_sha256`, the same provenance discipline `Daemon::open`
/// already applies to the resident process.
pub fn hash_file(path: &Path) -> Result<String> {
    Ok(hash_bytes(&fs::read(path)?))
}
pub fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn generate_dispatch_token() -> Result<String> {
    let mut bytes = [0u8; DISPATCH_TOKEN_BYTES];
    fill_dispatch_random(&mut bytes)?;
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut token = String::with_capacity(DISPATCH_TOKEN_BYTES * 2);
    for byte in bytes {
        token.push(HEX[(byte >> 4) as usize] as char);
        token.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(token)
}

#[cfg(windows)]
fn fill_dispatch_random(bytes: &mut [u8]) -> Result<()> {
    #[link(name = "advapi32")]
    extern "system" {
        #[link_name = "SystemFunction036"]
        fn rtl_gen_random(buffer: *mut std::ffi::c_void, length: u32) -> u8;
    }
    let length =
        u32::try_from(bytes.len()).map_err(|_| EmberLabError::InvalidDispatchManifest {
            detail: "dispatch token entropy request is too large".into(),
        })?;
    if unsafe { rtl_gen_random(bytes.as_mut_ptr().cast(), length) } == 0 {
        return Err(EmberLabError::Io(std::io::Error::last_os_error()));
    }
    Ok(())
}

#[cfg(not(windows))]
fn fill_dispatch_random(bytes: &mut [u8]) -> Result<()> {
    std::fs::File::open("/dev/urandom")?.read_exact(bytes)?;
    Ok(())
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn validate_dispatch_workload_profile(
    profile: &DispatchWorkloadProfile,
    args: &[String],
    maximum_job_memory_bytes: u64,
    simulated_peak_commit_bytes: u64,
) -> Result<()> {
    if !(1..=100).contains(&profile.cpu_rate_percent) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "dispatch workload CPU rate must be between 1 and 100 percent".into(),
        });
    }
    if profile.pinned_host_producers.is_empty() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "dispatch workload profile has no pinned-host producer budget".into(),
        });
    }
    let mut seen = std::collections::BTreeSet::new();
    let mut total = 0u64;
    for producer in &profile.pinned_host_producers {
        if producer.maximum_bytes == 0 || !seen.insert(producer.kind) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch workload producer budgets must be positive and unique".into(),
            });
        }
        total = total.checked_add(producer.maximum_bytes).ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: "dispatch workload producer budgets overflow bytes".into(),
            }
        })?;
    }
    if total != simulated_peak_commit_bytes || total > maximum_job_memory_bytes {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "dispatch workload producer budgets must exactly cover the simulated peak within the Job Object ceiling".into(),
        });
    }
    let expected = match profile.profile_id {
        DispatchWorkloadProfileId::GovernedVertical => [
            DispatchPinnedHostProducerKind::TrainingDataLoader,
            DispatchPinnedHostProducerKind::CheckpointWriter,
            DispatchPinnedHostProducerKind::TelemetryBuffer,
        ]
        .into_iter()
        .collect(),
        DispatchWorkloadProfileId::OwnedServing => [
            DispatchPinnedHostProducerKind::ModelServer,
            DispatchPinnedHostProducerKind::TelemetryBuffer,
        ]
        .into_iter()
        .collect(),
        DispatchWorkloadProfileId::EvidenceVerifier => {
            [DispatchPinnedHostProducerKind::ReceiptVerifier]
                .into_iter()
                .collect()
        }
        DispatchWorkloadProfileId::Cockpit => [DispatchPinnedHostProducerKind::TelemetryBuffer]
            .into_iter()
            .collect(),
    };
    if seen != expected {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail:
                "dispatch workload profile declares unsupported or incomplete pinned-host producers"
                    .into(),
        });
    }
    let expects_ui = profile.profile_id == DispatchWorkloadProfileId::Cockpit;
    if profile.requires_ui_responsiveness != expects_ui {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "dispatch workload profile UI-responsiveness declaration is inconsistent"
                .into(),
        });
    }
    let governed_vertical = args.iter().any(|arg| arg == "governed-vertical");
    if governed_vertical != (profile.profile_id == DispatchWorkloadProfileId::GovernedVertical) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "dispatch workload profile does not match the governed-vertical argv".into(),
        });
    }
    Ok(())
}

fn verify_dispatch_file(path: &Path, sha256: &str) -> Result<PathBuf> {
    validate_hash(sha256).map_err(|_| EmberLabError::InvalidDispatchManifest {
        detail: format!(
            "dispatch binding has an invalid SHA-256: {}",
            path.display()
        ),
    })?;
    let canonical =
        fs::canonicalize(path).map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!(
                "dispatch binding is unavailable at {}: {error}",
                path.display()
            ),
        })?;
    if !canonical.is_file() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("dispatch binding is not a file: {}", canonical.display()),
        });
    }
    let actual = hash_file(&canonical)?;
    if actual != sha256 {
        return Err(EmberLabError::DispatchBindingMismatch {
            path: canonical,
            expected: sha256.to_string(),
            actual,
        });
    }
    Ok(canonical)
}

fn verify_dispatch_binding(binding: &DispatchFileBinding) -> Result<PathBuf> {
    verify_dispatch_file(&binding.path, &binding.sha256)
}

fn read_verified_json_snapshot(path: &Path, expected_sha256: &str) -> Result<Value> {
    let bytes = fs::read(path)?;
    let actual = hash_bytes(&bytes);
    if actual != expected_sha256 {
        return Err(EmberLabError::DispatchBindingMismatch {
            path: path.to_path_buf(),
            expected: expected_sha256.to_string(),
            actual,
        });
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn absolute_under_root(path: &Path, root: &Path) -> Result<PathBuf> {
    if !path.is_absolute() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("dispatch output path must be absolute: {}", path.display()),
        });
    }
    let name = path
        .file_name()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: format!("dispatch output path lacks a file name: {}", path.display()),
        })?;
    let parent = path
        .parent()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: format!("dispatch output path lacks a parent: {}", path.display()),
        })?;
    let parent =
        fs::canonicalize(parent).map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!("dispatch output parent is unavailable: {error}"),
        })?;
    if !parent.starts_with(root) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("dispatch output escapes custody: {}", path.display()),
        });
    }
    Ok(parent.join(name))
}

fn validate_absolute_dispatch_args(
    args: &[String],
    program: &Path,
    bindings: &[(PathBuf, String, DispatchBindingKind)],
    custody_root: &Path,
) -> Result<()> {
    for raw in args {
        let value = raw.split_once('=').map_or(raw.as_str(), |(_, value)| value);
        let path = Path::new(value);
        if path.is_absolute() {
            let allowed = if path.exists() {
                let canonical = fs::canonicalize(path)?;
                canonical == program
                    || canonical.starts_with(custody_root)
                    || bindings.iter().any(|(bound, _, _)| {
                        canonical == *bound
                            || bound.parent().is_some_and(|parent| canonical == parent)
                    })
            } else {
                path.starts_with(custody_root)
            };
            if !allowed {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: format!(
                        "absolute dispatch argument is neither hash-bound nor in custody: {raw}"
                    ),
                });
            }
        }
    }
    Ok(())
}

fn validate_resume_registry_binding_closure(
    args: &[String],
    bindings: &[(PathBuf, String, DispatchBindingKind)],
) -> Result<()> {
    let mut registry_argument: Option<&str> = None;
    let mut index = 0usize;
    while index < args.len() {
        let raw = &args[index];
        let candidate = if raw == "--resume-realization-registry" {
            index += 1;
            args.get(index).map(String::as_str).ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "resume realization registry flag lacks its path".into(),
                }
            })?
        } else if let Some(value) = raw.strip_prefix("--resume-realization-registry=") {
            value
        } else {
            index += 1;
            continue;
        };
        if registry_argument.replace(candidate).is_some() {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resume realization registry argument is duplicated".into(),
            });
        }
        index += 1;
    }
    let Some(raw_registry) = registry_argument else {
        return Ok(());
    };
    let registry = fs::canonicalize(raw_registry)?;
    let registry_binding = bindings
        .iter()
        .find(|(path, _, kind)| *path == registry && *kind == DispatchBindingKind::Manifest)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "resume realization registry is not an exact manifest binding".into(),
        })?;
    let root = registry
        .parent()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "resume realization registry lacks a parent directory".into(),
        })?;
    let payload = read_verified_json_snapshot(&registry, &registry_binding.1)?;
    let object = payload
        .as_object()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "resume realization registry must be a JSON object".into(),
        })?;
    let expected_keys = [
        "schema_version",
        "verifiers",
        "realization_receipts",
        "model_configs",
    ];
    if object.len() != expected_keys.len()
        || expected_keys.iter().any(|key| !object.contains_key(*key))
        || object.get("schema_version").and_then(Value::as_str)
            != Some("ember-trusted-verifiers-v2")
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "resume realization registry schema is not closed v2".into(),
        });
    }
    for (field, kind) in [
        ("verifiers", DispatchBindingKind::Verifier),
        ("realization_receipts", DispatchBindingKind::Manifest),
        ("model_configs", DispatchBindingKind::Config),
    ] {
        let records = object.get(field).and_then(Value::as_array).ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} is not an array"),
            }
        })?;
        if records.len() != 1 {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!(
                    "resume realization registry {field} must contain exactly one file"
                ),
            });
        }
        let entry =
            records[0]
                .as_object()
                .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                    detail: format!("resume realization registry {field} entry is not an object"),
                })?;
        let expected_entry_keys: &[&str] = match field {
            "verifiers" => &["path", "sha256", "evidence_classes", "criterion_ids"],
            "realization_receipts" => &[
                "path",
                "sha256",
                "subject_checkpoint_sha256",
                "model_config_sha256",
                "counter_sha256",
                "active_expert",
            ],
            "model_configs" => &["path", "sha256", "semantic_sha256"],
            _ => unreachable!(),
        };
        if entry.len() != expected_entry_keys.len()
            || expected_entry_keys
                .iter()
                .any(|key| !entry.contains_key(*key))
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} entry schema is not closed"),
            });
        }
        let relative = entry
            .get("path")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty() && !Path::new(value).is_absolute())
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} path is invalid"),
            })?;
        let declared_sha256 = entry
            .get("sha256")
            .and_then(Value::as_str)
            .filter(|value| is_sha256(value))
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} sha256 is invalid"),
            })?;
        let nested = fs::canonicalize(root.join(relative))?;
        if !nested.starts_with(root)
            || !bindings.iter().any(|(path, sha256, binding_kind)| {
                *path == nested && *binding_kind == kind && sha256 == declared_sha256
            })
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!(
                    "resume realization registry {field} file is not hash-bound with its required kind"
                ),
            });
        }
    }
    Ok(())
}

#[cfg(windows)]
fn available_free_bytes(root: &Path) -> Result<u64> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;

    let mut wide: Vec<u16> = root.as_os_str().encode_wide().collect();
    wide.push(0);
    let mut available = 0u64;
    if unsafe {
        GetDiskFreeSpaceExW(
            wide.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(available)
}

#[cfg(not(windows))]
fn available_free_bytes(_root: &Path) -> Result<u64> {
    Err(EmberLabError::InvalidDispatchManifest {
        detail: "native disk reserve probing is currently Windows-only".into(),
    })
}

#[cfg(windows)]
pub fn probe_host_commit_capacity() -> Result<HostCommitCapacity> {
    use windows_sys::Win32::System::ProcessStatus::{GetPerformanceInfo, PERFORMANCE_INFORMATION};

    let mut info: PERFORMANCE_INFORMATION = unsafe { std::mem::zeroed() };
    info.cb = std::mem::size_of::<PERFORMANCE_INFORMATION>() as u32;
    if unsafe { GetPerformanceInfo(&mut info, info.cb) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let page_size = info.PageSize as u64;
    let physical_available_bytes = (info.PhysicalAvailable as u64).checked_mul(page_size);
    let pages_to_bytes = |pages: usize, label: &str| {
        (pages as u64).checked_mul(page_size).ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("Windows host commit probe overflowed {label}"),
            }
        })
    };
    let physical_ram_bytes = pages_to_bytes(info.PhysicalTotal, "physical RAM bytes")?;
    let commit_total_bytes = pages_to_bytes(info.CommitTotal, "committed bytes")?;
    let current_commit_limit_bytes =
        pages_to_bytes(info.CommitLimit, "current commit limit bytes")?;
    let physical_available_bytes =
        physical_available_bytes.ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Windows host commit probe overflowed physical available bytes".into(),
        })?;
    let (pagefile_maximum_bytes, pagefile_configuration_sha256) =
        configured_pagefile_maximum_bytes()?;
    let maximum_commit_capacity_bytes = physical_ram_bytes
        .checked_add(pagefile_maximum_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Windows maximum commit capacity overflowed bytes".into(),
        })?;
    if maximum_commit_capacity_bytes < current_commit_limit_bytes {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "configured pagefile maximum is below the live Windows commit limit".into(),
        });
    }
    if maximum_commit_capacity_bytes < commit_total_bytes {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "live committed bytes exceed configured maximum commit capacity".into(),
        });
    }
    let current_commit_remaining_bytes = current_commit_limit_bytes
        .checked_sub(commit_total_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "live committed bytes exceed current Windows commit limit".into(),
        })?;
    Ok(HostCommitCapacity {
        physical_ram_bytes,
        physical_available_bytes,
        pagefile_maximum_bytes,
        pagefile_configuration_source:
            r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles"
                .into(),
        pagefile_configuration_sha256,
        commit_total_bytes,
        current_commit_limit_bytes,
        current_commit_remaining_bytes,
        maximum_commit_capacity_bytes,
        available_maximum_commit_bytes: maximum_commit_capacity_bytes - commit_total_bytes,
    })
}

#[cfg(windows)]
fn configured_pagefile_maximum_bytes() -> Result<(u64, String)> {
    use windows_sys::Win32::Foundation::ERROR_SUCCESS;
    use windows_sys::Win32::System::Registry::{
        RegGetValueW, HKEY_LOCAL_MACHINE, RRF_RT_REG_MULTI_SZ,
    };

    let wide = |value: &str| {
        value
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect::<Vec<_>>()
    };
    let subkey = wide(r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management");
    let name = wide("PagingFiles");
    let mut bytes = 0u32;
    let first = unsafe {
        RegGetValueW(
            HKEY_LOCAL_MACHINE,
            subkey.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_MULTI_SZ,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut bytes,
        )
    };
    if first != ERROR_SUCCESS || bytes < 4 || !bytes.is_multiple_of(2) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("fixed pagefile maximum registry size probe failed: {first}"),
        });
    }
    let mut buffer = vec![0u16; bytes as usize / 2];
    let second = unsafe {
        RegGetValueW(
            HKEY_LOCAL_MACHINE,
            subkey.as_ptr(),
            name.as_ptr(),
            RRF_RT_REG_MULTI_SZ,
            std::ptr::null_mut(),
            buffer.as_mut_ptr().cast(),
            &mut bytes,
        )
    };
    if second != ERROR_SUCCESS {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("fixed pagefile maximum registry read failed: {second}"),
        });
    }
    buffer.truncate(bytes as usize / 2);
    let raw_bytes =
        unsafe { std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), buffer.len() * 2) };
    let configuration_sha256 = hash_bytes(raw_bytes);
    let entries = buffer
        .split(|unit| *unit == 0)
        .filter(|entry| !entry.is_empty())
        .map(|entry| {
            let text =
                String::from_utf16(entry).map_err(|_| EmberLabError::InvalidDispatchManifest {
                    detail: "fixed pagefile maximum registry value is not UTF-16".into(),
                })?;
            Ok(text)
        })
        .collect::<Result<Vec<_>>>()?;
    Ok((
        pagefile_maximum_bytes_from_entries(&entries)?,
        configuration_sha256,
    ))
}

fn pagefile_maximum_bytes_from_entries(entries: &[String]) -> Result<u64> {
    let mut total_mib = 0u64;
    for text in entries {
        let maximum_mib = text
            .split_whitespace()
            .next_back()
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value > 0)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "pagefile setting is not a fixed positive maximum".into(),
            })?;
        total_mib = total_mib.checked_add(maximum_mib).ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: "pagefile maximum overflowed MiB".into(),
            }
        })?;
    }
    if total_mib == 0 {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "no fixed pagefile maximum is configured".into(),
        });
    }
    total_mib
        .checked_mul(1024 * 1024)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "pagefile maximum overflowed bytes".into(),
        })
}

#[cfg(not(windows))]
pub fn probe_host_commit_capacity() -> Result<HostCommitCapacity> {
    Err(EmberLabError::InvalidDispatchManifest {
        detail: "native host commit probing is currently Windows-only".into(),
    })
}

fn available_free_vram_bytes() -> Result<u64> {
    let output = std::process::Command::new("nvidia-smi")
        .args(["--query-gpu=memory.free", "--format=csv,noheader,nounits"])
        .output()
        .map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM probe failed to start: {error}"),
        })?;
    if !output.status.success() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM probe failed with {}", output.status),
        });
    }
    let stdout = String::from_utf8(output.stdout).map_err(|error| {
        EmberLabError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM output was not UTF-8: {error}"),
        }
    })?;
    let values = stdout
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| line.trim().parse::<u64>())
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM output was invalid: {error}"),
        })?;
    if values.len() != 1 {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!(
                "dispatch requires exactly one visible GPU, observed {}",
                values.len()
            ),
        });
    }
    values[0]
        .checked_mul(1024 * 1024)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "nvidia-smi VRAM value overflowed bytes".into(),
        })
}
/// `pub`: reused by `main.rs`'s `verify-training` subcommand for the same self-identity
/// receipt field the daemon already stamps on every dispatch (`Daemon::open`).
pub fn ember_lab_source_hash() -> String {
    let sources: [&[u8]; 7] = [
        include_bytes!("lib.rs"),
        include_bytes!("data_catalog.rs"),
        include_bytes!("rpc.rs"),
        include_bytes!("main.rs"),
        include_bytes!("training_verify.rs"),
        include_bytes!("../Cargo.toml"),
        include_bytes!("../Cargo.lock"),
    ];
    let mut digest = Sha256::new();
    for source in sources {
        digest.update((source.len() as u64).to_le_bytes());
        digest.update(source);
    }
    format!("{:x}", digest.finalize())
}
fn seal_log_hashes(tx: &rusqlite::Transaction<'_>, job_id: &str) -> Result<(String, String)> {
    let (stdout_path, stderr_path): (String, String) = tx.query_row(
        "SELECT stdout_log_path,stderr_log_path FROM jobs WHERE job_id=?1",
        [job_id],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    Ok((
        hash_file(Path::new(&stdout_path))?,
        hash_file(Path::new(&stderr_path))?,
    ))
}

fn migrate_schema(conn: &mut Connection, log_dir: &Path) -> Result<()> {
    let schema_version_text: String = conn.query_row(
        "SELECT value FROM metadata WHERE key='schema_version'",
        [],
        |row| row.get(0),
    )?;
    let schema_version =
        schema_version_text
            .parse::<u32>()
            .map_err(|_| EmberLabError::InvalidDataCatalog {
                detail: "database schema version must be a canonical unsigned integer".into(),
            })?;
    if schema_version.to_string() != schema_version_text {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: "database schema version must be a canonical unsigned integer".into(),
        });
    }
    if schema_version == 0 || schema_version > CURRENT_DATABASE_SCHEMA_VERSION {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: format!(
                "database schema version {schema_version} is outside the supported migration range 1..={CURRENT_DATABASE_SCHEMA_VERSION}"
            ),
        });
    }

    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;

    let columns: Vec<String> = {
        let mut statement = tx.prepare("PRAGMA table_info(jobs)")?;
        let rows = statement
            .query_map([], |row| row.get(1))?
            .collect::<std::result::Result<_, _>>()?;
        rows
    };
    for (column, definition) in [
        ("restart_policy", "TEXT NOT NULL DEFAULT 'never'"),
        ("stdout_log_path", "TEXT NOT NULL DEFAULT ''"),
        ("stderr_log_path", "TEXT NOT NULL DEFAULT ''"),
        ("stdout_child_handle", "INTEGER NOT NULL DEFAULT 0"),
        ("stderr_child_handle", "INTEGER NOT NULL DEFAULT 0"),
        ("stdout_log_sha256", "TEXT"),
        ("stderr_log_sha256", "TEXT"),
        ("outage_event_cutoff_seq", "INTEGER"),
        ("exit_code", "INTEGER"),
        ("exited_at_ms", "INTEGER"),
    ] {
        if !columns.iter().any(|existing| existing == column) {
            tx.execute_batch(&format!(
                "ALTER TABLE jobs ADD COLUMN {column} {definition}"
            ))?;
        }
    }
    let jobs: Vec<String> = {
        let mut statement =
            tx.prepare("SELECT job_id FROM jobs WHERE stdout_log_path='' OR stderr_log_path=''")?;
        let rows = statement
            .query_map([], |row| row.get(0))?
            .collect::<std::result::Result<_, _>>()?;
        rows
    };
    for job_id in jobs {
        let key = hash_bytes(job_id.as_bytes());
        let stdout = log_dir.join(format!("{key}.stdout.log"));
        let stderr = log_dir.join(format!("{key}.stderr.log"));
        tx.execute(
            "UPDATE jobs SET stdout_log_path=?2,stderr_log_path=?3 WHERE job_id=?1",
            params![job_id, stdout.to_string_lossy(), stderr.to_string_lossy()],
        )?;
    }
    tx.execute(
        "UPDATE jobs SET outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events) WHERE outage_event_cutoff_seq IS NULL AND state IN ('stopped','exited','failed')",
        [],
    )?;
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS resource_guard_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), admission_state TEXT NOT NULL CHECK(admission_state IN ('open','frozen')), reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL CHECK(oracle_evidence_required IN (0,1)), observation_json TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS resource_guard_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
         INSERT OR IGNORE INTO resource_guard_state(singleton,admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json) VALUES(1,'open',NULL,0,0,'{}');",
    )?;
    data_catalog::migrate(&tx)?;
    tx.execute(
        "UPDATE metadata SET value=?1 WHERE key='schema_version'",
        [CURRENT_DATABASE_SCHEMA_VERSION.to_string()],
    )?;
    tx.commit()?;
    Ok(())
}

#[cfg(test)]
fn create_resource_guard_tables(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS resource_guard_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), admission_state TEXT NOT NULL CHECK(admission_state IN ('open','frozen')), reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL CHECK(oracle_evidence_required IN (0,1)), observation_json TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS resource_guard_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
         INSERT OR IGNORE INTO resource_guard_state(singleton,admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json) VALUES(1,'open',NULL,0,0,'{}');",
    )?;
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct HostSurvivalHeadroom {
    physical_available_bytes: u64,
    commit_remaining_bytes: u64,
}

fn resource_guard_status_from_connection(conn: &Connection) -> Result<Value> {
    let (state, reason, observed_at_ms, oracle_required, observation_json): (
        String,
        Option<String>,
        i64,
        i64,
        String,
    ) = conn.query_row(
        "SELECT admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json FROM resource_guard_state WHERE singleton=1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
    )?;
    let observation: Value = serde_json::from_str(&observation_json).map_err(|error| {
        EmberLabError::InvalidDispatchManifest {
            detail: format!("resource guard observation is invalid: {error}"),
        }
    })?;
    Ok(json!({
        "schema_version": "ember-lab-resource-guard-state-v1",
        "admission_state": state,
        "reason": reason,
        "observed_at_ms": observed_at_ms,
        "oracle_evidence_required": oracle_required == 1,
        "driver_locked_provider": "UNAVAILABLE",
        "observation": observation,
        "diagnostic_oracle": {
            "name": "RAMMap",
            "role": "diagnostic_only",
            "state": if oracle_required == 1 { "REQUIRED_UNAVAILABLE" } else { "NOT_REQUIRED" },
        },
        "sampling_interval_ms": RESOURCE_GUARD_SAMPLE_INTERVAL_MS,
    }))
}

#[cfg(test)]
fn resource_guard_freeze_reason(capacity: &HostCommitCapacity) -> Option<&'static str> {
    resource_guard_headroom_freeze_reason(&HostSurvivalHeadroom {
        physical_available_bytes: capacity.physical_available_bytes,
        commit_remaining_bytes: capacity.current_commit_remaining_bytes,
    })
}

fn resource_guard_headroom_freeze_reason(headroom: &HostSurvivalHeadroom) -> Option<&'static str> {
    if headroom.physical_available_bytes < RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES {
        Some("physical_available_below_survival_floor")
    } else if headroom.commit_remaining_bytes < RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES {
        Some("commit_remaining_below_survival_floor")
    } else {
        None
    }
}

#[cfg(test)]
fn persist_resource_guard_sample(
    conn: &Connection,
    observed_at_ms: i64,
    sample: Result<HostCommitCapacity>,
) -> Result<()> {
    persist_resource_guard_headroom(
        conn,
        observed_at_ms,
        sample.map(|capacity| HostSurvivalHeadroom {
            physical_available_bytes: capacity.physical_available_bytes,
            commit_remaining_bytes: capacity.current_commit_remaining_bytes,
        }),
    )
}

fn persist_resource_guard_headroom(
    conn: &Connection,
    observed_at_ms: i64,
    sample: Result<HostSurvivalHeadroom>,
) -> Result<()> {
    let (outcome, reason, observation) = match sample {
        Ok(headroom) => {
            let reason = resource_guard_headroom_freeze_reason(&headroom);
            let outcome = if reason.is_some() {
                "frozen"
            } else {
                "healthy"
            };
            (
                outcome,
                reason.map(str::to_string),
                json!({
                    "schema_version": "ember-lab-resource-guard-observation-v1",
                    "result": if reason.is_some() { "SURVIVAL_FLOOR_BREACH" } else { "HEALTHY" },
                    "observed_at_ms": observed_at_ms,
                    "monitor_tier": "cheap_host_counters",
                    "driver_locked_provider": "UNAVAILABLE",
                    "physical_available_bytes": headroom.physical_available_bytes,
                    "commit_remaining_bytes": headroom.commit_remaining_bytes,
                    "minimum_physical_available_bytes": RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES,
                    "minimum_commit_remaining_bytes": RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES,
                }),
            )
        }
        Err(error) => (
            "probe_failed",
            Some("resource_guard_probe_failed".into()),
            json!({
                "schema_version": "ember-lab-resource-guard-observation-v1",
                "result": "PROBE_FAILED",
                "observed_at_ms": observed_at_ms,
                "monitor_tier": "cheap_host_counters",
                "driver_locked_provider": "UNAVAILABLE",
                "error": format!("{error:?}"),
                "minimum_physical_available_bytes": RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES,
                "minimum_commit_remaining_bytes": RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES,
            }),
        ),
    };
    let observation_json = serde_json::to_string(&observation)?;
    let tx = conn.unchecked_transaction()?;
    tx.execute(
        "INSERT INTO resource_guard_observations(observed_at_ms,outcome,payload_json) VALUES(?1,?2,?3)",
        params![observed_at_ms, outcome, observation_json],
    )?;
    tx.execute(
        "DELETE FROM resource_guard_observations WHERE seq <= COALESCE((SELECT MAX(seq) FROM resource_guard_observations),0)-?1",
        [RESOURCE_GUARD_OBSERVATION_LIMIT],
    )?;
    if let Some(reason) = reason {
        tx.execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason=?1,observed_at_ms=?2,oracle_evidence_required=1,observation_json=?3 WHERE singleton=1 AND admission_state='open'",
            params![reason, observed_at_ms, observation_json],
        )?;
    } else {
        tx.execute(
            "UPDATE resource_guard_state SET observed_at_ms=?1,observation_json=?2 WHERE singleton=1 AND admission_state='open'",
            params![observed_at_ms, observation_json],
        )?;
    }
    tx.commit()?;
    Ok(())
}

#[cfg(windows)]
fn probe_host_survival_headroom() -> Result<HostSurvivalHeadroom> {
    use windows_sys::Win32::System::ProcessStatus::{GetPerformanceInfo, PERFORMANCE_INFORMATION};

    let mut info: PERFORMANCE_INFORMATION = unsafe { std::mem::zeroed() };
    info.cb = std::mem::size_of::<PERFORMANCE_INFORMATION>() as u32;
    if unsafe { GetPerformanceInfo(&mut info, info.cb) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let page_size = info.PageSize as u64;
    let physical_available_bytes = (info.PhysicalAvailable as u64)
        .checked_mul(page_size)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Windows resource guard overflowed physical available bytes".into(),
        })?;
    let commit_total_bytes = (info.CommitTotal as u64)
        .checked_mul(page_size)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Windows resource guard overflowed current commit bytes".into(),
        })?;
    let commit_limit_bytes = (info.CommitLimit as u64)
        .checked_mul(page_size)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Windows resource guard overflowed commit limit bytes".into(),
        })?;
    let commit_remaining_bytes = commit_limit_bytes
        .checked_sub(commit_total_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Windows resource guard observed commit above its live limit".into(),
        })?;
    Ok(HostSurvivalHeadroom {
        physical_available_bytes,
        commit_remaining_bytes,
    })
}

#[cfg(not(windows))]
fn probe_host_survival_headroom() -> Result<HostSurvivalHeadroom> {
    Err(EmberLabError::InvalidDispatchManifest {
        detail: "native resource guard probing is currently Windows-only".into(),
    })
}

#[cfg(windows)]
fn create_monitor_shutdown() -> Result<OwnedHandle> {
    use windows_sys::Win32::System::Threading::CreateEventW;

    let handle = unsafe { CreateEventW(std::ptr::null(), 1, 0, std::ptr::null()) };
    if handle.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(OwnedHandle(handle))
}

#[cfg(windows)]
fn protective_checkpoint_monitor_grace_ms(job_count: usize) -> u64 {
    let divisor = u64::try_from(job_count).unwrap_or(u64::MAX).max(1);
    (PROTECTIVE_CHECKPOINT_MONITOR_TOTAL_GRACE_MS / divisor).max(1)
}
#[cfg(windows)]
fn running_job_ids_for_protective_stop(conn: &Connection) -> Result<Vec<String>> {
    let status = resource_guard_status_from_connection(conn)?;
    if status.get("admission_state") != Some(&Value::String("frozen".into())) {
        return Ok(Vec::new());
    }
    let mut statement =
        conn.prepare("SELECT job_id FROM jobs WHERE state='running' ORDER BY job_id")?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(EmberLabError::from)
}

#[cfg(windows)]
fn record_protective_owned_stop_failure(
    db: &Arc<Mutex<Connection>>,
    job_id: &str,
    error: &EmberLabError,
) {
    let Ok(conn) = db.lock() else {
        return;
    };
    let _ = conn.execute(
        "INSERT INTO events(job_id,ts_ms,kind,payload_json)
         VALUES(?1,?2,'protective_owned_stop_failed',?3)",
        params![
            job_id,
            now_ms(),
            json!({
                "error": error.to_string(),
                "foreign_process_control": false,
            })
            .to_string()
        ],
    );
}

#[cfg(windows)]
fn spawn_resource_guard_monitor(
    db: Weak<Mutex<Connection>>,
    live: Weak<Mutex<HashMap<String, RetainedProcess>>>,
    log_dir: PathBuf,
    shutdown: OwnedHandle,
    ownership: Weak<RwLock<bool>>,
) -> Result<()> {
    std::thread::Builder::new()
        .name("ember-lab-resource-guard".into())
        .spawn(move || {
            use windows_sys::Win32::Foundation::{WAIT_OBJECT_0, WAIT_TIMEOUT};
            use windows_sys::Win32::System::Threading::WaitForSingleObject;

            loop {
                let wait = unsafe {
                    WaitForSingleObject(shutdown.raw(), RESOURCE_GUARD_SAMPLE_INTERVAL_MS)
                };
                if wait == WAIT_OBJECT_0 {
                    break;
                }
                if wait != WAIT_TIMEOUT {
                    break;
                }
                let Some(ownership) = ownership.upgrade() else {
                    break;
                };
                if ownership.read().map(|alive| !*alive).unwrap_or(true) {
                    break;
                }
                let Some(db) = db.upgrade() else {
                    break;
                };
                let job_ids = {
                    let Ok(conn) = db.lock() else {
                        break;
                    };
                    if persist_resource_guard_headroom(
                        &conn,
                        now_ms(),
                        probe_host_survival_headroom(),
                    )
                    .is_err()
                    {
                        Vec::new()
                    } else {
                        running_job_ids_for_protective_stop(&conn).unwrap_or_default()
                    }
                };
                if job_ids.is_empty() {
                    continue;
                }
                let Some(live) = live.upgrade() else {
                    break;
                };
                let context = ProtectiveStopContext {
                    db: Arc::clone(&db),
                    live,
                    log_dir: log_dir.clone(),
                };
                let grace_ms = protective_checkpoint_monitor_grace_ms(job_ids.len());

                for job_id in job_ids {
                    if let Err(error) =
                        context.protective_owned_stop(&job_id, Duration::from_millis(grace_ms))
                    {
                        record_protective_owned_stop_failure(&db, &job_id, &error);
                    }
                }
            }
        })?;
    Ok(())
}
fn state_writer_lock_path(path: &Path) -> PathBuf {
    let mut name = path
        .file_name()
        .unwrap_or_else(|| std::ffi::OsStr::new("ember-lab"))
        .to_os_string();
    name.push(".writer.lock");
    path.with_file_name(name)
}

#[cfg(windows)]
fn acquire_state_writer_lock(path: &Path) -> Result<fs::File> {
    use std::os::windows::fs::OpenOptionsExt;

    let lock_path = state_writer_lock_path(path);
    match OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .share_mode(0)
        .open(&lock_path)
    {
        Ok(lock) => Ok(lock),
        Err(error) if matches!(error.raw_os_error(), Some(32 | 33)) => {
            Err(EmberLabError::StateWriterBusy { path: lock_path })
        }
        Err(error) => Err(error.into()),
    }
}

#[cfg(not(windows))]
fn acquire_state_writer_lock(path: &Path) -> Result<fs::File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(state_writer_lock_path(path))?)
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}
fn same_executable(a: &str, b: &str) -> bool {
    if cfg!(windows) {
        a.eq_ignore_ascii_case(b)
    } else {
        a == b
    }
}
fn atomic_replace(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temp = path.with_extension(format!("replace-{}-{}", std::process::id(), now_ms()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::Storage::FileSystem::{
            MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
        };
        let from: Vec<u16> = temp.as_os_str().encode_wide().chain(Some(0)).collect();
        let to: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        if unsafe {
            MoveFileExW(
                from.as_ptr(),
                to.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        } == 0
        {
            let error = std::io::Error::last_os_error();
            let _ = fs::remove_file(&temp);
            return Err(error.into());
        }
    }
    #[cfg(not(windows))]
    fs::rename(&temp, path)?;
    if let Some(parent) = path.parent() {
        if let Ok(directory) = OpenOptions::new().read(true).open(parent) {
            let _ = directory.sync_all();
        }
    }
    Ok(())
}

fn write_content_addressed_receipt(directory: &Path, bytes: &[u8]) -> Result<ReceiptArtifact> {
    let sha256 = hash_bytes(bytes);
    fs::create_dir_all(directory)?;
    let path = directory.join(format!("{sha256}.json"));
    if path.exists() {
        if fs::read(&path)? == bytes {
            return Ok(ReceiptArtifact { path, sha256 });
        }
        return Err(EmberLabError::ReceiptHashCollision { path });
    }
    match atomic_create(&path, bytes) {
        Ok(()) => Ok(ReceiptArtifact { path, sha256 }),
        Err(EmberLabError::ReceiptAlreadyExists { .. }) if fs::read(&path)? == bytes => {
            Ok(ReceiptArtifact { path, sha256 })
        }
        Err(EmberLabError::ReceiptAlreadyExists { .. }) => {
            Err(EmberLabError::ReceiptHashCollision { path })
        }
        Err(error) => Err(error),
    }
}

fn publish_staging_directory(staging: &Path, directory: &Path) -> Result<()> {
    match rename_directory_no_replace(staging, directory) {
        Ok(()) => Ok(()),
        Err(error) => {
            let _ = fs::remove_dir_all(staging);
            Err(error.into())
        }
    }
}

#[cfg(test)]
mod assessment_evidence_publish_tests {
    use super::*;
    use std::sync::{Arc, Barrier};

    #[test]
    fn raced_empty_destination_is_preserved_and_private_staging_is_removed() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "ember-lab-assessment-publish-race-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let staging = root.join("private-staging");
        let destination = root.join("fresh-output");
        fs::create_dir(&staging).unwrap();
        fs::write(staging.join("artifact"), b"daemon evidence").unwrap();
        assert!(!destination.exists());

        let barrier = Arc::new(Barrier::new(2));
        let racer_barrier = Arc::clone(&barrier);
        let raced_destination = destination.clone();
        let racer = std::thread::spawn(move || {
            racer_barrier.wait();
            fs::create_dir(&raced_destination).unwrap();
        });
        barrier.wait();
        racer.join().unwrap();

        assert!(publish_staging_directory(&staging, &destination).is_err());
        assert!(destination.is_dir());
        assert_eq!(fs::read_dir(&destination).unwrap().count(), 0);
        assert!(!staging.exists());
        fs::remove_dir_all(root).unwrap();
    }
}

#[cfg(windows)]
fn rename_directory_no_replace(from: &Path, to: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_WRITE_THROUGH};
    let from: Vec<u16> = from.as_os_str().encode_wide().chain(Some(0)).collect();
    let to: Vec<u16> = to.as_os_str().encode_wide().chain(Some(0)).collect();
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), MOVEFILE_WRITE_THROUGH) } == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn rename_directory_no_replace(from: &Path, to: &Path) -> std::io::Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    const AT_FDCWD: i32 = -100;
    const RENAME_NOREPLACE: u32 = 1;
    unsafe extern "C" {
        fn renameat2(
            olddirfd: i32,
            oldpath: *const std::os::raw::c_char,
            newdirfd: i32,
            newpath: *const std::os::raw::c_char,
            flags: u32,
        ) -> i32;
    }
    let from = CString::new(from.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in source path"))?;
    let to = CString::new(to.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in target path"))?;
    if unsafe {
        renameat2(
            AT_FDCWD,
            from.as_ptr(),
            AT_FDCWD,
            to.as_ptr(),
            RENAME_NOREPLACE,
        )
    } == 0
    {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(target_os = "macos")]
fn rename_directory_no_replace(from: &Path, to: &Path) -> std::io::Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    const RENAME_EXCL: u32 = 0x0000_0004;
    unsafe extern "C" {
        fn renamex_np(
            from: *const std::os::raw::c_char,
            to: *const std::os::raw::c_char,
            flags: u32,
        ) -> i32;
    }
    let from = CString::new(from.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in source path"))?;
    let to = CString::new(to.as_os_str().as_bytes())
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in target path"))?;
    if unsafe { renamex_np(from.as_ptr(), to.as_ptr(), RENAME_EXCL) } == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
fn rename_directory_no_replace(_from: &Path, _to: &Path) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "atomic no-replace directory publication is unavailable on this platform",
    ))
}

fn atomic_create(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temp = path.with_extension(format!("tmp-{}-{}", std::process::id(), now_ms()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_WRITE_THROUGH};
        let from: Vec<u16> = temp.as_os_str().encode_wide().chain(Some(0)).collect();
        let to: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), MOVEFILE_WRITE_THROUGH) } == 0 {
            let error = std::io::Error::last_os_error();
            let _ = fs::remove_file(&temp);
            return match error.raw_os_error() {
                Some(80 | 183) => Err(EmberLabError::ReceiptAlreadyExists {
                    path: path.to_path_buf(),
                }),
                _ => Err(error.into()),
            };
        }
    }
    #[cfg(not(windows))]
    {
        if let Err(error) = fs::hard_link(&temp, path) {
            let _ = fs::remove_file(&temp);
            return if error.kind() == std::io::ErrorKind::AlreadyExists {
                Err(EmberLabError::ReceiptAlreadyExists {
                    path: path.to_path_buf(),
                })
            } else {
                Err(error.into())
            };
        }
        fs::remove_file(&temp)?;
    }
    if let Some(parent) = path.parent() {
        if let Ok(dir) = OpenOptions::new().read(true).open(parent) {
            let _ = dir.sync_all();
        }
    }
    Ok(())
}

#[cfg(windows)]
struct SpawnedProcess {
    job: OwnedHandle,
    process: OwnedHandle,
    thread: OwnedHandle,
    stdout_log_guard: OwnedHandle,
    stderr_log_guard: OwnedHandle,
    pid: u32,
    main_thread_id: u32,
    identity: ProcessIdentity,
}

#[cfg(windows)]
impl SpawnedProcess {
    fn pid(&self) -> u32 {
        self.pid
    }
    fn main_thread_id(&self) -> u32 {
        self.main_thread_id
    }
    fn identity(&self) -> ProcessIdentity {
        self.identity.clone()
    }
    fn stdout_child_handle(&self) -> i64 {
        self.stdout_log_guard.raw() as isize as i64
    }
    fn stderr_child_handle(&self) -> i64 {
        self.stderr_log_guard.raw() as isize as i64
    }
    fn resume(&mut self) -> Result<()> {
        use windows_sys::Win32::System::Threading::ResumeThread;
        if unsafe { ResumeThread(self.thread.0) } == u32::MAX {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(())
    }
    fn terminate_and_wait(&mut self) -> Result<()> {
        terminate_handles(self.job.0, self.process.0, self.pid)
    }
    fn into_live(self) -> LiveProcess {
        LiveProcess {
            job: self.job,
            process: self.process,
            _stdout_log_guard: self.stdout_log_guard,
            _stderr_log_guard: self.stderr_log_guard,
            pid: self.pid,
            identity: self.identity,
        }
    }
}

#[cfg(windows)]
struct ProcThreadAttributeList {
    _storage: Vec<usize>,
    _jobs: Box<[windows_sys::Win32::Foundation::HANDLE; 1]>,
    _handles: Box<[windows_sys::Win32::Foundation::HANDLE; 3]>,
    ptr: windows_sys::Win32::System::Threading::LPPROC_THREAD_ATTRIBUTE_LIST,
}
#[cfg(windows)]
impl ProcThreadAttributeList {
    fn for_job_and_handles(
        job: windows_sys::Win32::Foundation::HANDLE,
        handles: [windows_sys::Win32::Foundation::HANDLE; 3],
    ) -> Result<Self> {
        use windows_sys::Win32::System::Threading::{
            InitializeProcThreadAttributeList, UpdateProcThreadAttribute,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST, PROC_THREAD_ATTRIBUTE_JOB_LIST,
        };
        let mut bytes = 0usize;
        unsafe { InitializeProcThreadAttributeList(std::ptr::null_mut(), 2, 0, &mut bytes) };
        if bytes == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let words = bytes.div_ceil(std::mem::size_of::<usize>());
        let mut storage = vec![0usize; words.max(1)];
        let ptr = storage.as_mut_ptr().cast();
        if unsafe { InitializeProcThreadAttributeList(ptr, 2, 0, &mut bytes) } == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let jobs = Box::new([job]);
        if unsafe {
            UpdateProcThreadAttribute(
                ptr,
                0,
                PROC_THREAD_ATTRIBUTE_JOB_LIST as usize,
                jobs.as_ptr().cast(),
                std::mem::size_of_val(jobs.as_ref()),
                std::ptr::null_mut(),
                std::ptr::null(),
            )
        } == 0
        {
            unsafe { windows_sys::Win32::System::Threading::DeleteProcThreadAttributeList(ptr) };
            return Err(std::io::Error::last_os_error().into());
        }
        let handles = Box::new(handles);
        if unsafe {
            UpdateProcThreadAttribute(
                ptr,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
                handles.as_ptr().cast(),
                std::mem::size_of_val(handles.as_ref()),
                std::ptr::null_mut(),
                std::ptr::null(),
            )
        } == 0
        {
            unsafe { windows_sys::Win32::System::Threading::DeleteProcThreadAttributeList(ptr) };
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(Self {
            _storage: storage,
            _jobs: jobs,
            _handles: handles,
            ptr,
        })
    }
}
#[cfg(windows)]
impl Drop for ProcThreadAttributeList {
    fn drop(&mut self) {
        unsafe { windows_sys::Win32::System::Threading::DeleteProcThreadAttributeList(self.ptr) };
    }
}
#[cfg(windows)]
fn duplicate_remote_log_handle(
    process: windows_sys::Win32::Foundation::HANDLE,
    remote_handle_value: i64,
    expected_path: &Path,
) -> Result<OwnedHandle> {
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt;
    use windows_sys::Win32::Foundation::{DuplicateHandle, DUPLICATE_SAME_ACCESS};
    use windows_sys::Win32::Storage::FileSystem::GetFinalPathNameByHandleW;
    use windows_sys::Win32::System::Threading::GetCurrentProcess;

    if remote_handle_value == 0 {
        return Err(EmberLabError::InvalidTransition {
            job_id: String::new(),
            detail: "persisted child log handle is absent".into(),
        });
    }
    let mut duplicated = std::ptr::null_mut();
    if unsafe {
        DuplicateHandle(
            process,
            remote_handle_value as isize as windows_sys::Win32::Foundation::HANDLE,
            GetCurrentProcess(),
            &mut duplicated,
            0,
            0,
            DUPLICATE_SAME_ACCESS,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    let owned = OwnedHandle(duplicated);
    let mut buffer = vec![0u16; 32768];
    let len = unsafe {
        GetFinalPathNameByHandleW(owned.raw(), buffer.as_mut_ptr(), buffer.len() as u32, 0)
    };
    if len == 0 || len as usize >= buffer.len() {
        return Err(std::io::Error::last_os_error().into());
    }
    let actual = PathBuf::from(OsString::from_wide(&buffer[..len as usize]));
    let normalize = |path: &Path| {
        path.to_string_lossy()
            .trim_start_matches(r"\\?\")
            .replace('/', "\\")
            .to_lowercase()
    };
    if normalize(&actual) != normalize(&fs::canonicalize(expected_path)?) {
        return Err(EmberLabError::InvalidTransition {
            job_id: String::new(),
            detail: format!(
                "duplicated child log handle path mismatch: expected {}, got {}",
                expected_path.display(),
                actual.display()
            ),
        });
    }
    Ok(owned)
}

#[cfg(windows)]
fn duplicate_inheritable_file_handle(file: &fs::File) -> Result<OwnedHandle> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Foundation::{DuplicateHandle, DUPLICATE_SAME_ACCESS};
    use windows_sys::Win32::System::Threading::GetCurrentProcess;

    let current = unsafe { GetCurrentProcess() };
    let mut duplicate = std::ptr::null_mut();
    if unsafe {
        DuplicateHandle(
            current,
            file.as_raw_handle().cast(),
            current,
            &mut duplicate,
            0,
            1,
            DUPLICATE_SAME_ACCESS,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(OwnedHandle(duplicate))
}

#[cfg(windows)]
fn managed_windows_creation_flags() -> u32 {
    use windows_sys::Win32::System::Threading::{
        CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT,
        EXTENDED_STARTUPINFO_PRESENT,
    };

    CREATE_SUSPENDED
        | CREATE_NEW_PROCESS_GROUP
        | CREATE_NO_WINDOW
        | CREATE_UNICODE_ENVIRONMENT
        | EXTENDED_STARTUPINFO_PRESENT
}

#[cfg(windows)]
fn spawn_managed(
    spec: &JobSpec,
    job_name: &str,
    stdout_path: &Path,
    stderr_path: &Path,
) -> Result<SpawnedProcess> {
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::{DuplicateHandle, DUPLICATE_SAME_ACCESS};
    use windows_sys::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectCpuRateControlInformation, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_CPU_RATE_CONTROL_INFORMATION,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_CPU_RATE_CONTROL_ENABLE,
        JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP, JOB_OBJECT_LIMIT_JOB_MEMORY,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, GetCurrentProcess, WaitForSingleObject, PROCESS_INFORMATION,
        STARTF_USESTDHANDLES, STARTUPINFOEXW,
    };

    let maximum_job_memory = spec
        .maximum_job_memory_bytes
        .map(usize::try_from)
        .transpose()
        .map_err(|_| EmberLabError::InvalidDispatchManifest {
            detail: "maximum job memory does not fit the current Windows address space".into(),
        })?;
    let cpu_rate = spec
        .cpu_rate_percent
        .map(|percent| percent.saturating_mul(100));

    unsafe { windows_sys::Win32::Foundation::SetLastError(0) };
    let name = wide(job_name);
    let job = unsafe { CreateJobObjectW(std::ptr::null(), name.as_ptr()) };
    if job.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    if std::io::Error::last_os_error().raw_os_error() == Some(183) {
        unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
        return Err(EmberLabError::InvalidTransition {
            job_id: spec.job_id.clone(),
            detail: "job object name already exists".into(),
        });
    }

    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if let Some(maximum) = maximum_job_memory {
        limits.JobMemoryLimit = maximum;
        limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY;
    }
    if unsafe {
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    } == 0
    {
        let error = std::io::Error::last_os_error();
        unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
        return Err(error.into());
    }

    if let Some(cpu_rate) = cpu_rate {
        let mut cpu: JOBOBJECT_CPU_RATE_CONTROL_INFORMATION = unsafe { zeroed() };
        cpu.ControlFlags =
            JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP;
        cpu.Anonymous.CpuRate = cpu_rate;
        if unsafe {
            SetInformationJobObject(
                job,
                JobObjectCpuRateControlInformation,
                (&cpu as *const JOBOBJECT_CPU_RATE_CONTROL_INFORMATION).cast(),
                size_of::<JOBOBJECT_CPU_RATE_CONTROL_INFORMATION>() as u32,
            )
        } == 0
        {
            let error = std::io::Error::last_os_error();
            unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
            return Err(error.into());
        }
    }

    let inherited_stdio = (|| -> Result<(OwnedHandle, OwnedHandle, OwnedHandle)> {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_SHARE_READ_RIGHT: u32 = 0x0000_0001;
        let stdin_file = OpenOptions::new().read(true).open("NUL")?;
        let stdout_file = OpenOptions::new()
            .create(true)
            .append(true)
            .truncate(false)
            .share_mode(FILE_SHARE_READ_RIGHT)
            .open(stdout_path)?;
        let stderr_file = OpenOptions::new()
            .create(true)
            .append(true)
            .truncate(false)
            .share_mode(FILE_SHARE_READ_RIGHT)
            .open(stderr_path)?;
        Ok((
            duplicate_inheritable_file_handle(&stdin_file)?,
            duplicate_inheritable_file_handle(&stdout_file)?,
            duplicate_inheritable_file_handle(&stderr_file)?,
        ))
    })();
    let (inherited_stdin, inherited_stdout, inherited_stderr) = match inherited_stdio {
        Ok(handles) => handles,
        Err(error) => {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
            return Err(error);
        }
    };
    let attributes = match ProcThreadAttributeList::for_job_and_handles(
        job,
        [
            inherited_stdin.raw(),
            inherited_stdout.raw(),
            inherited_stderr.raw(),
        ],
    ) {
        Ok(attributes) => attributes,
        Err(error) => {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
            return Err(error);
        }
    };
    let mut command_line = wide(&windows_command_line(&spec.program, &spec.args));
    let application: Vec<u16> = std::ffi::OsStr::new(&spec.program)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let environment = windows_environment(&spec.env);
    let mut startup: STARTUPINFOEXW = unsafe { zeroed() };
    startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = inherited_stdin.raw();
    startup.StartupInfo.hStdOutput = inherited_stdout.raw();
    startup.StartupInfo.hStdError = inherited_stderr.raw();
    startup.lpAttributeList = attributes.ptr;
    let mut info: PROCESS_INFORMATION = unsafe { zeroed() };
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
            managed_windows_creation_flags(),
            environment.as_ptr().cast(),
            std::ptr::null(),
            &startup.StartupInfo,
            &mut info,
        )
    };
    drop(attributes);
    if created == 0 {
        unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
        return Err(std::io::Error::last_os_error().into());
    }

    let current = unsafe { GetCurrentProcess() };
    let mut remote_lifetime_handle = std::ptr::null_mut();
    if unsafe {
        DuplicateHandle(
            current,
            job,
            info.hProcess,
            &mut remote_lifetime_handle,
            0,
            0,
            DUPLICATE_SAME_ACCESS,
        )
    } == 0
    {
        let error = std::io::Error::last_os_error();
        unsafe {
            TerminateJobObject(job, 1);
            WaitForSingleObject(info.hProcess, 5000);
            windows_sys::Win32::Foundation::CloseHandle(info.hThread);
            windows_sys::Win32::Foundation::CloseHandle(info.hProcess);
            windows_sys::Win32::Foundation::CloseHandle(job);
        }
        return Err(error.into());
    }

    let identity = match inspect_handle(info.hProcess, info.dwProcessId) {
        Ok(identity) => identity,
        Err(error) => {
            unsafe {
                TerminateJobObject(job, 1);
                WaitForSingleObject(info.hProcess, 5000);
                windows_sys::Win32::Foundation::CloseHandle(info.hThread);
                windows_sys::Win32::Foundation::CloseHandle(info.hProcess);
                windows_sys::Win32::Foundation::CloseHandle(job);
            }
            return Err(error);
        }
    };
    Ok(SpawnedProcess {
        job: OwnedHandle(job),
        process: OwnedHandle(info.hProcess),
        thread: OwnedHandle(info.hThread),
        stdout_log_guard: inherited_stdout,
        stderr_log_guard: inherited_stderr,
        pid: info.dwProcessId,
        main_thread_id: info.dwThreadId,
        identity,
    })
}
#[cfg(windows)]
enum LiveStatus {
    Verified(LiveProcess),
    Dead,
    Orphaned(String),
    IdentityConflict(String),
}

#[cfg(windows)]
fn duplicate_owned_handle(source: windows_sys::Win32::Foundation::HANDLE) -> Result<OwnedHandle> {
    use windows_sys::Win32::Foundation::{DuplicateHandle, DUPLICATE_SAME_ACCESS};
    use windows_sys::Win32::System::Threading::GetCurrentProcess;

    let current = unsafe { GetCurrentProcess() };
    let mut duplicate = std::ptr::null_mut();
    if unsafe {
        DuplicateHandle(
            current,
            source,
            current,
            &mut duplicate,
            0,
            0,
            DUPLICATE_SAME_ACCESS,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(OwnedHandle(duplicate))
}

#[cfg(windows)]
fn record_natural_exit(
    db: &Mutex<Connection>,
    job_id: &str,
    pid: u32,
    exit_code: u32,
    live: &LiveProcess,
) -> Result<()> {
    let mut conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let lease: Option<(String, i64)> = tx
        .query_row(
            "SELECT resource,lease_epoch FROM jobs WHERE job_id=?1 AND state='running' AND pid=?2",
            params![job_id, pid],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let (resource, lease_epoch) = lease.ok_or_else(|| EmberLabError::InvalidTransition {
        job_id: job_id.into(),
        detail: "natural-exit monitor lost its running state fence".into(),
    })?;
    terminate_live(live)?;
    let (stdout_sha256, stderr_sha256) = seal_log_hashes(&tx, job_id)?;
    let timestamp = now_ms();
    let changed = tx.execute(
        "UPDATE jobs SET state='exited',exit_code=?3,exited_at_ms=?4,stdout_log_sha256=?6,stderr_log_sha256=?7,outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events),updated_at_ms=?4 WHERE job_id=?1 AND state='running' AND pid=?2 AND lease_epoch=?5",
        params![
            job_id,
            pid,
            exit_code as i64,
            timestamp,
            lease_epoch,
            stdout_sha256,
            stderr_sha256
        ],
    )?;
    if changed != 1 {
        return Err(EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "natural-exit monitor lost its state or lease epoch fence".into(),
        });
    }
    let released = tx.execute(
        "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
        params![resource, job_id, lease_epoch],
    )?;
    if released != 1 {
        return Err(EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "natural-exit monitor lost its lease epoch".into(),
        });
    }
    tx.execute(
        "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_exited',?3)",
        params![
            job_id,
            timestamp,
            json!({"pid":pid,"exit_code":exit_code}).to_string()
        ],
    )?;
    tx.commit()?;
    Ok(())
}

#[cfg(windows)]
fn spawn_exit_monitor(
    db: Weak<Mutex<Connection>>,
    retained: Weak<Mutex<HashMap<String, RetainedProcess>>>,
    ownership: Arc<RwLock<bool>>,
    shutdown: OwnedHandle,
    job_id: String,
    pid: u32,
    waiter: OwnedHandle,
) {
    std::thread::spawn(move || {
        use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
        use windows_sys::Win32::System::Threading::{
            GetExitCodeProcess, WaitForMultipleObjects, INFINITE,
        };

        let handles = [waiter.raw(), shutdown.raw()];
        if unsafe { WaitForMultipleObjects(2, handles.as_ptr(), 0, INFINITE) } != WAIT_OBJECT_0 {
            return;
        }
        let mut exit_code = 0u32;
        if unsafe { GetExitCodeProcess(waiter.raw(), &mut exit_code) } == 0 {
            return;
        }
        let Ok(alive) = ownership.read() else {
            return;
        };
        if !*alive {
            return;
        }
        let Some(db) = db.upgrade() else {
            return;
        };
        let Some(retained) = retained.upgrade() else {
            return;
        };
        let Ok(mut retained) = retained.lock() else {
            return;
        };
        let Some(retained_process) = retained.get(&job_id) else {
            return;
        };
        if record_natural_exit(&db, &job_id, pid, exit_code, &retained_process.live).is_ok() {
            retained.remove(&job_id);
        }
    });
}
#[cfg(windows)]
fn open_live_status(row: &JobProcessRow) -> LiveStatus {
    use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
    use windows_sys::Win32::System::JobObjects::{
        IsProcessInJob, JobObjectBasicAccountingInformation, OpenJobObjectW,
        QueryInformationJobObject, JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    };
    use windows_sys::Win32::System::Threading::{
        OpenProcess, WaitForSingleObject, PROCESS_DUP_HANDLE, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    const SYNCHRONIZE_RIGHT: u32 = 0x0010_0000;
    const JOB_OBJECT_QUERY_RIGHT: u32 = 0x0004;
    const JOB_OBJECT_TERMINATE_RIGHT: u32 = 0x0008;
    let name = wide(&row.job_object_name);
    let job = unsafe {
        OpenJobObjectW(
            JOB_OBJECT_QUERY_RIGHT | JOB_OBJECT_TERMINATE_RIGHT,
            0,
            name.as_ptr(),
        )
    };
    if job.is_null() {
        let code = std::io::Error::last_os_error()
            .raw_os_error()
            .unwrap_or_default();
        if code != 2 {
            return LiveStatus::IdentityConflict(format!("OpenJobObjectW failed with {code}"));
        }
        if row.pid == 0 {
            return LiveStatus::Dead;
        }
        let process = unsafe {
            OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_DUP_HANDLE | SYNCHRONIZE_RIGHT,
                0,
                row.pid,
            )
        };
        if process.is_null() {
            return LiveStatus::Dead;
        }
        if unsafe { WaitForSingleObject(process, 0) } == WAIT_OBJECT_0 {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(process) };
            return LiveStatus::Dead;
        }
        let status = match inspect_handle(process, row.pid) {
            Ok(current)
                if current.start_token == row.start_token
                    && same_executable(&current.executable, &row.executable) =>
            {
                LiveStatus::Orphaned(
                    "verified root process exists without its named job object".into(),
                )
            }
            Ok(_) => LiveStatus::IdentityConflict(
                "pid exists but persisted process identity does not match".into(),
            ),
            Err(_) => LiveStatus::IdentityConflict(
                "pid exists but process identity cannot be verified".into(),
            ),
        };
        unsafe { windows_sys::Win32::Foundation::CloseHandle(process) };
        return status;
    }
    let process = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_DUP_HANDLE | SYNCHRONIZE_RIGHT,
            0,
            row.pid,
        )
    };
    if process.is_null() {
        let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
        let queried = unsafe {
            QueryInformationJobObject(
                job,
                JobObjectBasicAccountingInformation,
                (&mut accounting as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
        return if queried != 0 && accounting.ActiveProcesses == 0 {
            LiveStatus::Dead
        } else {
            LiveStatus::Orphaned(
                "named job still has active processes but its recorded root cannot be opened"
                    .into(),
            )
        };
    }
    if unsafe { WaitForSingleObject(process, 0) } == WAIT_OBJECT_0 {
        let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
        let queried = unsafe {
            QueryInformationJobObject(
                job,
                JobObjectBasicAccountingInformation,
                (&mut accounting as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(process);
            windows_sys::Win32::Foundation::CloseHandle(job);
        }
        return if queried != 0 && accounting.ActiveProcesses == 0 {
            LiveStatus::Dead
        } else {
            LiveStatus::Orphaned(
                "recorded root exited while its named job still has active descendants".into(),
            )
        };
    }
    let current = match inspect_handle(process, row.pid) {
        Ok(current) => current,
        Err(_) => {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(process);
                windows_sys::Win32::Foundation::CloseHandle(job);
            }
            return LiveStatus::IdentityConflict(
                "recorded process handle cannot be identified".into(),
            );
        }
    };
    let mut member = 0;
    let in_job = unsafe { IsProcessInJob(process, job, &mut member) };
    if in_job == 0
        || member == 0
        || current.start_token != row.start_token
        || !same_executable(&current.executable, &row.executable)
    {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(process);
            windows_sys::Win32::Foundation::CloseHandle(job);
        }
        return LiveStatus::IdentityConflict(
            "recorded process is not the verified root member of the named job".into(),
        );
    }
    let stdout_log_guard =
        match duplicate_remote_log_handle(process, row.stdout_child_handle, &row.stdout_log_path) {
            Ok(guard) => guard,
            Err(error) => {
                unsafe {
                    windows_sys::Win32::Foundation::CloseHandle(process);
                    windows_sys::Win32::Foundation::CloseHandle(job);
                }
                return LiveStatus::IdentityConflict(format!(
                    "stdout log guard cannot be re-established: {error:?}"
                ));
            }
        };
    let stderr_log_guard =
        match duplicate_remote_log_handle(process, row.stderr_child_handle, &row.stderr_log_path) {
            Ok(guard) => guard,
            Err(error) => {
                unsafe {
                    windows_sys::Win32::Foundation::CloseHandle(process);
                    windows_sys::Win32::Foundation::CloseHandle(job);
                }
                return LiveStatus::IdentityConflict(format!(
                    "stderr log guard cannot be re-established: {error:?}"
                ));
            }
        };
    LiveStatus::Verified(LiveProcess {
        job: OwnedHandle(job),
        process: OwnedHandle(process),
        _stdout_log_guard: stdout_log_guard,
        _stderr_log_guard: stderr_log_guard,
        pid: row.pid,
        identity: current,
    })
}

#[cfg(not(windows))]
fn terminate_job_object_by_name(_name: &str) -> Result<()> {
    Err(EmberLabError::Io(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "Windows Job Object termination is unavailable on this host",
    )))
}

#[cfg(windows)]
fn terminate_job_object_by_name(name: &str) -> Result<()> {
    use windows_sys::Win32::System::JobObjects::{OpenJobObjectW, TerminateJobObject};
    const JOB_OBJECT_TERMINATE_RIGHT: u32 = 0x0008;
    let name = wide(name);
    let job = unsafe { OpenJobObjectW(JOB_OBJECT_TERMINATE_RIGHT, 0, name.as_ptr()) };
    if job.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    let job = OwnedHandle(job);
    if unsafe { TerminateJobObject(job.0, 0xE0D00001) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

#[cfg(windows)]
fn resume_thread_id(thread_id: u32) -> Result<()> {
    use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};
    const SYNCHRONIZE_RIGHT: u32 = 0x0010_0000;
    let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME | SYNCHRONIZE_RIGHT, 0, thread_id) };
    if thread.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    let previous = unsafe { ResumeThread(thread) };
    unsafe { windows_sys::Win32::Foundation::CloseHandle(thread) };
    if previous == u32::MAX {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

#[cfg(windows)]
fn inspect_handle(
    handle: windows_sys::Win32::Foundation::HANDLE,
    pid: u32,
) -> Result<ProcessIdentity> {
    use std::mem::zeroed;
    use windows_sys::Win32::Foundation::FILETIME;
    use windows_sys::Win32::System::Threading::{GetProcessTimes, QueryFullProcessImageNameW};
    let (mut creation, mut exit, mut kernel, mut user): (FILETIME, FILETIME, FILETIME, FILETIME) =
        unsafe { zeroed() };
    if unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) } == 0 {
        return Err(EmberLabError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        });
    }
    let mut path = vec![0u16; 32768];
    let mut size = path.len() as u32;
    if unsafe { QueryFullProcessImageNameW(handle, 0, path.as_mut_ptr(), &mut size) } == 0 {
        return Err(EmberLabError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        });
    }
    Ok(ProcessIdentity {
        start_token: format!(
            "{:08x}{:08x}",
            creation.dwHighDateTime, creation.dwLowDateTime
        ),
        executable: String::from_utf16_lossy(&path[..size as usize]),
    })
}

#[cfg(windows)]
fn terminate_live(live: &LiveProcess) -> Result<()> {
    terminate_handles(live.job.0, live.process.0, live.pid)
}

#[cfg(windows)]
fn live_process_is_running(live: &LiveProcess) -> bool {
    use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
    use windows_sys::Win32::System::Threading::WaitForSingleObject;
    unsafe { WaitForSingleObject(live.process.raw(), 0) == WAIT_TIMEOUT }
}

#[cfg(windows)]
fn terminate_handles(
    job: windows_sys::Win32::Foundation::HANDLE,
    process: windows_sys::Win32::Foundation::HANDLE,
    pid: u32,
) -> Result<()> {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
    use windows_sys::Win32::System::JobObjects::{
        JobObjectBasicAccountingInformation, QueryInformationJobObject, TerminateJobObject,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    };
    use windows_sys::Win32::System::Threading::WaitForSingleObject;
    if unsafe { TerminateJobObject(job, 0xE0D00001) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if unsafe { WaitForSingleObject(process, 5000) } != WAIT_OBJECT_0 {
        return Err(EmberLabError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        });
    }
    for _ in 0..100 {
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
        if ok == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        if accounting.ActiveProcesses == 0 {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    Err(EmberLabError::ProcessUnavailable {
        job_id: String::new(),
        pid,
    })
}

#[cfg(windows)]
fn wide(value: &str) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    std::ffi::OsStr::new(value)
        .encode_wide()
        .chain(Some(0))
        .collect()
}
#[cfg(windows)]
fn windows_command_line(program: &str, args: &[String]) -> String {
    std::iter::once(program)
        .chain(args.iter().map(String::as_str))
        .map(quote_windows_arg)
        .collect::<Vec<_>>()
        .join(" ")
}
#[cfg(windows)]
fn quote_windows_arg(value: &str) -> String {
    if !value.is_empty() && !value.bytes().any(|b| b == b' ' || b == b'\t' || b == b'\"') {
        return value.into();
    }
    let mut out = String::from("\"");
    let mut slashes = 0;
    for ch in value.chars() {
        if ch == '\\' {
            slashes += 1;
        } else {
            if ch == '\"' {
                out.push_str(&"\\".repeat(slashes * 2 + 1));
            } else {
                out.push_str(&"\\".repeat(slashes));
            }
            slashes = 0;
            out.push(ch);
        }
    }
    out.push_str(&"\\".repeat(slashes * 2));
    out.push('\"');
    out
}
#[cfg(windows)]
fn windows_environment(overrides: &BTreeMap<String, String>) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    let mut env: BTreeMap<String, String> = std::env::vars().collect();
    env.extend(overrides.clone());
    let mut block = Vec::new();
    for (key, value) in env {
        block.extend(std::ffi::OsStr::new(&format!("{key}={value}")).encode_wide());
        block.push(0);
    }
    block.push(0);
    block
}

#[cfg(windows)]
fn job_object_name(job_id: &str) -> String {
    format!(
        "Local\\ember-lab-{}-{}-{}",
        std::process::id(),
        now_ms(),
        &hash_bytes(job_id.as_bytes())[..16]
    )
}
#[cfg(not(windows))]
fn job_object_name(job_id: &str) -> String {
    format!(
        "ember-lab-{}-{}",
        now_ms(),
        &hash_bytes(job_id.as_bytes())[..16]
    )
}

#[cfg(not(windows))]
struct SpawnedProcess {
    child: Option<std::process::Child>,
    pid: u32,
    identity: ProcessIdentity,
}
#[cfg(not(windows))]
impl SpawnedProcess {
    fn pid(&self) -> u32 {
        self.pid
    }
    fn main_thread_id(&self) -> u32 {
        0
    }
    fn identity(&self) -> ProcessIdentity {
        self.identity.clone()
    }
    fn stdout_child_handle(&self) -> i64 {
        0
    }
    fn stderr_child_handle(&self) -> i64 {
        0
    }
    fn resume(&mut self) -> Result<()> {
        Ok(())
    }
    fn terminate_and_wait(&mut self) -> Result<()> {
        if let Some(child) = self.child.as_mut() {
            child.kill()?;
            child.wait()?;
        }
        Ok(())
    }
    fn detach_reaper(mut self) {
        if let Some(mut child) = self.child.take() {
            std::thread::spawn(move || {
                let _ = child.wait();
            });
        }
    }
}
#[cfg(not(windows))]
fn spawn_managed(
    spec: &JobSpec,
    _job_name: &str,
    stdout_path: &Path,
    stderr_path: &Path,
) -> Result<SpawnedProcess> {
    let child = Command::new(&spec.program)
        .args(&spec.args)
        .envs(&spec.env)
        .stdin(Stdio::null())
        .stdout(Stdio::from(
            OpenOptions::new()
                .create(true)
                .append(true)
                .truncate(false)
                .open(stdout_path)?,
        ))
        .stderr(Stdio::from(
            OpenOptions::new()
                .create(true)
                .append(true)
                .truncate(false)
                .open(stderr_path)?,
        ))
        .spawn()?;
    let pid = child.id();
    let identity = inspect_process(pid)?;
    Ok(SpawnedProcess {
        child: Some(child),
        pid,
        identity,
    })
}

#[cfg(not(windows))]
fn proc_stat_start_token(stat: &str) -> Result<String> {
    let suffix = stat
        .rsplit_once(") ")
        .map(|(_, suffix)| suffix)
        .ok_or_else(|| EmberLabError::ProcessUnavailable {
            job_id: String::new(),
            pid: 0,
        })?;
    suffix
        .split_whitespace()
        .nth(19)
        .map(str::to_owned)
        .ok_or_else(|| EmberLabError::ProcessUnavailable {
            job_id: String::new(),
            pid: 0,
        })
}

#[cfg(not(windows))]
fn inspect_process(pid: u32) -> Result<ProcessIdentity> {
    let exe = fs::read_link(format!("/proc/{pid}/exe"))?;
    let stat = fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let token = proc_stat_start_token(&stat).map_err(|_| EmberLabError::ProcessUnavailable {
        job_id: String::new(),
        pid,
    })?;
    Ok(ProcessIdentity {
        start_token: token,
        executable: exe.to_string_lossy().into_owned(),
    })
}
#[cfg(not(windows))]
fn terminate_process(pid: u32) -> Result<()> {
    let status = Command::new("kill")
        .args(["-TERM", &pid.to_string()])
        .status()?;
    if status.success() {
        Ok(())
    } else {
        Err(EmberLabError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        })
    }
}

#[cfg(test)]
mod dispatch_binding_snapshot_tests {
    use super::*;

    #[cfg(not(windows))]
    #[test]
    fn proc_stat_start_token_uses_suffix_after_final_comm_paren() {
        let mut suffix = vec!["S".to_string()];
        suffix.extend((1..=19).map(|index| {
            if index == 19 {
                "987654".to_string()
            } else {
                "0".to_string()
            }
        }));
        let stat = format!("42 (worker name with ) chars) {}", suffix.join(" "));
        assert_eq!(proc_stat_start_token(&stat).unwrap(), "987654");
    }

    #[cfg(windows)]
    #[test]
    fn managed_windows_child_is_created_without_a_console_window() {
        use windows_sys::Win32::System::Threading::{CREATE_NO_WINDOW, CREATE_SUSPENDED};

        let flags = managed_windows_creation_flags();
        assert_ne!(flags & CREATE_SUSPENDED, 0);
        assert_ne!(flags & CREATE_NO_WINDOW, 0);
    }

    #[test]
    fn registry_replacement_between_initial_hash_and_parse_is_rejected() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = scratch::ember_scratch_dir(&format!("binding-snapshot-{nonce}")).unwrap();
        let registry = root.join("trusted-verifiers.json");
        fs::write(
            &registry,
            br#"{"schema_version":"ember-trusted-verifiers-v2"}"#,
        )
        .unwrap();
        let initially_bound = hash_file(&registry).unwrap();
        fs::write(&registry, br#"{"schema_version":"replaced"}"#).unwrap();

        let error = read_verified_json_snapshot(&registry, &initially_bound).unwrap_err();
        assert!(matches!(
            error,
            EmberLabError::DispatchBindingMismatch { .. }
        ));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn fixed_pagefile_maxima_are_parsed_and_system_managed_values_fail_closed() {
        let fixed = vec![r"C:\pagefile.sys 16384 32768".to_string()];
        assert_eq!(
            pagefile_maximum_bytes_from_entries(&fixed).unwrap(),
            32 * 1024 * 1024 * 1024
        );
        let multiple = vec![
            r"C:\pagefile.sys 1024 4096".to_string(),
            r"D:\pagefile.sys 2048 8192".to_string(),
        ];
        assert_eq!(
            pagefile_maximum_bytes_from_entries(&multiple).unwrap(),
            12 * 1024 * 1024 * 1024
        );
        for invalid in [
            vec![r"C:\pagefile.sys 0 0".to_string()],
            vec![r"C:\pagefile.sys malformed".to_string()],
            Vec::new(),
        ] {
            assert!(pagefile_maximum_bytes_from_entries(&invalid).is_err());
        }
    }

    fn healthy_host_capacity() -> HostCommitCapacity {
        HostCommitCapacity {
            physical_ram_bytes: 64 * 1024 * 1024 * 1024,
            physical_available_bytes: 32 * 1024 * 1024 * 1024,
            pagefile_maximum_bytes: 64 * 1024 * 1024 * 1024,
            pagefile_configuration_source: "test".into(),
            pagefile_configuration_sha256: "a".repeat(64),
            commit_total_bytes: 32 * 1024 * 1024 * 1024,
            current_commit_limit_bytes: 96 * 1024 * 1024 * 1024,
            current_commit_remaining_bytes: 64 * 1024 * 1024 * 1024,
            maximum_commit_capacity_bytes: 128 * 1024 * 1024 * 1024,
            available_maximum_commit_bytes: 96 * 1024 * 1024 * 1024,
        }
    }

    #[test]
    fn survival_floor_evaluation_uses_live_physical_and_commit_headroom() {
        let healthy = healthy_host_capacity();
        assert_eq!(resource_guard_freeze_reason(&healthy), None);

        let mut low_physical = healthy.clone();
        low_physical.physical_available_bytes = RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES - 1;
        assert_eq!(
            resource_guard_freeze_reason(&low_physical),
            Some("physical_available_below_survival_floor")
        );

        let mut low_commit = healthy;
        low_commit.current_commit_remaining_bytes = RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES - 1;
        assert_eq!(
            resource_guard_freeze_reason(&low_commit),
            Some("commit_remaining_below_survival_floor")
        );
    }

    #[test]
    fn a_resource_guard_freeze_is_sticky_across_later_healthy_samples() {
        let conn = Connection::open_in_memory().unwrap();
        create_resource_guard_tables(&conn).unwrap();

        let mut low = healthy_host_capacity();
        low.current_commit_remaining_bytes = RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES - 1;
        persist_resource_guard_sample(&conn, 100, Ok(low)).unwrap();

        let frozen = resource_guard_status_from_connection(&conn).unwrap();
        assert_eq!(frozen["admission_state"], "frozen");
        assert_eq!(frozen["reason"], "commit_remaining_below_survival_floor");
        assert_eq!(frozen["oracle_evidence_required"], true);

        persist_resource_guard_sample(&conn, 200, Ok(healthy_host_capacity())).unwrap();
        let still_frozen = resource_guard_status_from_connection(&conn).unwrap();
        assert_eq!(still_frozen["admission_state"], "frozen");
        assert_eq!(
            still_frozen["reason"],
            "commit_remaining_below_survival_floor"
        );
        let observations: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM resource_guard_observations",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(observations, 2);
    }

    #[test]
    fn a_failed_survival_probe_sticky_freezes_future_admissions() {
        let conn = Connection::open_in_memory().unwrap();
        create_resource_guard_tables(&conn).unwrap();
        persist_resource_guard_headroom(
            &conn,
            300,
            Err(EmberLabError::InvalidDispatchManifest {
                detail: "probe unavailable".into(),
            }),
        )
        .unwrap();

        let frozen = resource_guard_status_from_connection(&conn).unwrap();
        assert_eq!(frozen["admission_state"], "frozen");
        assert_eq!(frozen["reason"], "resource_guard_probe_failed");
        assert_eq!(frozen["oracle_evidence_required"], true);
        assert_eq!(frozen["diagnostic_oracle"]["name"], "RAMMap");
        assert_eq!(frozen["diagnostic_oracle"]["state"], "REQUIRED_UNAVAILABLE");
        assert!(frozen["observation"]["error"]
            .as_str()
            .unwrap()
            .contains("probe unavailable"));
    }
    #[cfg(windows)]
    #[test]
    fn protective_checkpoint_grace_has_one_daemon_wide_finite_budget() {
        assert_eq!(protective_checkpoint_monitor_grace_ms(0), 5_000);
        assert_eq!(protective_checkpoint_monitor_grace_ms(1), 5_000);
        assert_eq!(protective_checkpoint_monitor_grace_ms(2), 2_500);
        assert_eq!(protective_checkpoint_monitor_grace_ms(10_000), 1);
    }
}
