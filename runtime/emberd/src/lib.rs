// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
#[cfg(not(windows))]
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
#[cfg(windows)]
use std::sync::{RwLock, Weak};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub mod rpc;

pub type Result<T> = std::result::Result<T, EmberdError>;

#[derive(Debug)]
pub enum EmberdError {
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
    Poisoned,
}

impl fmt::Display for EmberdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for EmberdError {}
impl From<rusqlite::Error> for EmberdError {
    fn from(value: rusqlite::Error) -> Self {
        Self::Sqlite(value)
    }
}
impl From<std::io::Error> for EmberdError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
impl From<serde_json::Error> for EmberdError {
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
    pub pagefile_maximum_bytes: u64,
    pub pagefile_configuration_source: String,
    pub pagefile_configuration_sha256: String,
    pub commit_total_bytes: u64,
    pub current_commit_limit_bytes: u64,
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
            _ => Err(EmberdError::InvalidTransition {
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
            _ => Err(EmberdError::InvalidTransition {
                job_id: String::new(),
                detail: format!("unknown restart policy {value}"),
            }),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReceiptArtifact {
    pub path: PathBuf,
    pub sha256: String,
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
    emberd_binary_sha256: String,
    emberd_source_sha256: String,
    #[cfg(windows)]
    live: Arc<Mutex<HashMap<String, RetainedProcess>>>,
    #[cfg(windows)]
    monitor_shutdown: OwnedHandle,
    #[cfg(windows)]
    monitor_ownership: Arc<RwLock<bool>>,
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

impl Daemon {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let state_writer_lock = acquire_state_writer_lock(path)?;
        let mut log_dir_name = path
            .file_name()
            .unwrap_or_else(|| std::ffi::OsStr::new("emberd"))
            .to_os_string();
        log_dir_name.push(".logs");
        let log_dir = path.with_file_name(log_dir_name);
        fs::create_dir_all(&log_dir)?;
        #[cfg(windows)]
        let monitor_shutdown = create_monitor_shutdown()?;
        let conn = Connection::open(path)?;
        let emberd_binary_sha256 = hash_file(&std::env::current_exe()?)?;
        let emberd_source_sha256 = emberd_source_hash();
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
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, ts_ms INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL);")?;
        migrate_schema(&conn, &log_dir)?;
        conn.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES('schedule_monitor_started_at_ms',?1)",
            [now_ms().to_string()],
        )?;
        Ok(Self {
            _state_writer_lock: state_writer_lock,
            log_dir,
            db: Arc::new(Mutex::new(conn)),
            emberd_binary_sha256,
            emberd_source_sha256,
            #[cfg(windows)]
            live: Arc::new(Mutex::new(HashMap::new())),
            #[cfg(windows)]
            monitor_shutdown,
            #[cfg(windows)]
            monitor_ownership: Arc::new(RwLock::new(true)),
        })
    }

    fn conn(&self) -> Result<std::sync::MutexGuard<'_, Connection>> {
        self.db.lock().map_err(|_| EmberdError::Poisoned)
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

    pub fn bind_identity(&self, job_id: &str, path: &Path, expected: &str) -> Result<()> {
        validate_hash(expected)?;
        let canonical = fs::canonicalize(path)?;
        let identity_blob = fs::read(&canonical)?;
        let actual = hash_bytes(&identity_blob);
        if actual != expected {
            return Err(EmberdError::IdentityMismatch {
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
            return Err(EmberdError::IdentityAlreadyBound {
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
        let (path, expected) = row.ok_or_else(|| EmberdError::IdentityNotFound {
            job_id: job_id.into(),
        })?;
        let actual = hash_file(Path::new(&path))?;
        if actual != expected {
            return Err(EmberdError::IdentityMismatch {
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
            return Err(EmberdError::InvalidSchedulePrediction {
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
            return Err(EmberdError::IdentityNotFound {
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
                self.emberd_binary_sha256,
                self.emberd_source_sha256,
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
            return Err(EmberdError::InvalidSchedulePrediction {
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
                self.emberd_binary_sha256,
                self.emberd_source_sha256,
            ],
        )?;
        if changed != 1 {
            return Err(EmberdError::InvalidSchedulePrediction {
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
        let records: Vec<(
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
        )> = statement
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
            "schema_version": "emberd-schedule-alarm-state-v1",
            "generated_at_ms": at_ms,
            "emberd_identity": {
                "binary_sha256": self.emberd_binary_sha256,
                "source_sha256": self.emberd_source_sha256,
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
                return Err(EmberdError::SchedulePredictionRequired {
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
            Some(owner) => Err(EmberdError::LeaseConflict {
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
                    return Err(EmberdError::IdentityNotFound {
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
            return Err(EmberdError::InvalidPlannedOutage {
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
            .ok_or_else(|| EmberdError::JobNotFound {
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
            .ok_or_else(|| EmberdError::JobNotFound {
                job_id: job_id.into(),
            })?;
        RestartPolicy::parse(&policy)
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
        mut free_space: F,
        mut free_vram: G,
        mut free_host_commit: H,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut() -> Result<u64>,
        H: FnMut() -> Result<HostCommitCapacity>,
    {
        let manifest_path = fs::canonicalize(manifest_path).map_err(|error| {
            EmberdError::InvalidDispatchManifest {
                detail: format!("dispatch manifest is not a canonical file: {error}"),
            }
        })?;
        let manifest_bytes = fs::read(&manifest_path)?;
        let manifest: DispatchManifest =
            serde_json::from_slice(&manifest_bytes).map_err(|error| {
                EmberdError::InvalidDispatchManifest {
                    detail: format!("dispatch manifest schema is invalid: {error}"),
                }
            })?;
        if manifest.schema_version != "emberd-dispatch-manifest-v2"
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
            || manifest.minimum_free_vram_bytes == 0
            || manifest.required_available_maximum_commit_bytes == 0
            || manifest.maximum_job_memory_bytes == 0
            || manifest.simulated_peak_commit_bytes == 0
        {
            return Err(EmberdError::InvalidDispatchManifest {
                detail: "dispatch manifest requires the closed v2 schema, identities, window, bindings, and reserves".into(),
            });
        }
        if observed_at_ms < manifest.not_before_ms {
            return Err(EmberdError::DispatchTooEarly {
                not_before_ms: manifest.not_before_ms,
                observed_at_ms,
            });
        }
        if observed_at_ms >= manifest.expires_at_ms {
            return Err(EmberdError::DispatchExpired {
                expires_at_ms: manifest.expires_at_ms,
                observed_at_ms,
            });
        }

        let custody_root = fs::canonicalize(&manifest.custody_root).map_err(|error| {
            EmberdError::InvalidDispatchManifest {
                detail: format!("dispatch custody root is unavailable: {error}"),
            }
        })?;
        if !custody_root.is_dir() {
            return Err(EmberdError::InvalidDispatchManifest {
                detail: "dispatch custody root is not a directory".into(),
            });
        }
        let receipt_path = absolute_under_root(&manifest.preflight_receipt, &custody_root)?;
        if receipt_path.exists() {
            return Err(EmberdError::ReceiptAlreadyExists { path: receipt_path });
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
                "schema_version": "emberd-dispatch-preflight-v1",
                "result": "REFUSED_HOST_COMMIT_CAP",
                "job_id": &manifest.job_id,
                "source_commit": &manifest.source_commit,
                "observed_at_ms": observed_at_ms,
                "dispatch_manifest_sha256": hash_bytes(&manifest_bytes),
                "host_commit": {
                    "basis": "maximum_configured_capacity",
                    "required_available_maximum_commit_bytes": manifest.required_available_maximum_commit_bytes,
                    "observed_available_maximum_commit_bytes": observed_available_maximum_commit_bytes,
                    "physical_ram_bytes": host_commit.physical_ram_bytes,
                    "pagefile_maximum_bytes": host_commit.pagefile_maximum_bytes,
                    "pagefile_configuration_source": host_commit.pagefile_configuration_source,
                    "pagefile_configuration_sha256": host_commit.pagefile_configuration_sha256,
                    "commit_total_bytes": host_commit.commit_total_bytes,
                    "current_commit_limit_bytes": host_commit.current_commit_limit_bytes,
                    "maximum_commit_capacity_bytes": host_commit.maximum_commit_capacity_bytes,
                    "reserve_bytes": DISPATCH_HOST_COMMIT_RESERVE_BYTES,
                    "maximum_job_memory_bytes": manifest.maximum_job_memory_bytes,
                    "simulated_peak_commit_bytes": manifest.simulated_peak_commit_bytes,
                },
            });
            atomic_replace(&receipt_path, &serde_json::to_vec(&refusal)?)?;
            return Err(EmberdError::DispatchHostCommitReserve {
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
                return Err(EmberdError::InvalidDispatchManifest {
                    detail: "dispatch bindings contain a duplicate canonical path".into(),
                });
            }
            kinds.insert(binding.kind);
            verified_bindings.push((canonical, binding.sha256.clone(), binding.kind));
        }
        if !kinds.contains(&DispatchBindingKind::Config)
            || !kinds.contains(&DispatchBindingKind::Manifest)
        {
            return Err(EmberdError::InvalidDispatchManifest {
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
                    .ok_or_else(|| EmberdError::InvalidDispatchManifest {
                        detail: format!("dispatch environment lacks custody binding {key}"),
                    })?;
            let cache =
                fs::canonicalize(raw).map_err(|error| EmberdError::InvalidDispatchManifest {
                    detail: format!("dispatch cache {key} is unavailable: {error}"),
                })?;
            if !cache.is_dir() || !cache.starts_with(&custody_root) {
                return Err(EmberdError::InvalidDispatchManifest {
                    detail: format!("dispatch cache {key} escapes custody"),
                });
            }
        }

        let mut reserve_receipts = Vec::with_capacity(manifest.storage_reserves.len());
        let mut reserve_roots = std::collections::BTreeSet::new();
        for reserve in &manifest.storage_reserves {
            if reserve.minimum_free_bytes == 0 {
                return Err(EmberdError::InvalidDispatchManifest {
                    detail: "dispatch storage reserve must be positive".into(),
                });
            }
            let root = fs::canonicalize(&reserve.root).map_err(|error| {
                EmberdError::InvalidDispatchManifest {
                    detail: format!("dispatch storage root is unavailable: {error}"),
                }
            })?;
            if !reserve_roots.insert(root.clone()) {
                return Err(EmberdError::InvalidDispatchManifest {
                    detail: "dispatch storage roots must be unique".into(),
                });
            }
            let available = free_space(&root)?;
            if available < reserve.minimum_free_bytes {
                return Err(EmberdError::DispatchStorageReserve {
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

        let available_vram = free_vram()?;
        if available_vram < manifest.minimum_free_vram_bytes {
            return Err(EmberdError::DispatchVramReserve {
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
        let manifest_sha256 = hash_bytes(&manifest_bytes);
        let args_sha256 = hash_bytes(&serde_json::to_vec(&manifest.args)?);
        let env_sha256 = hash_bytes(&serde_json::to_vec(&manifest.env)?);
        let receipt_payload = json!({
            "schema_version": "emberd-dispatch-preflight-v1",
            "result": "PREFLIGHT_PASSED",
            "job_id": &manifest.job_id,
            "source_commit": &manifest.source_commit,
            "observed_at_ms": observed_at_ms,
            "not_before_ms": manifest.not_before_ms,
            "expires_at_ms": manifest.expires_at_ms,
            "dispatch_manifest_sha256": manifest_sha256,
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
                "pagefile_maximum_bytes": host_commit.pagefile_maximum_bytes,
                "pagefile_configuration_source": host_commit.pagefile_configuration_source,
                "pagefile_configuration_sha256": host_commit.pagefile_configuration_sha256,
                "commit_total_bytes": host_commit.commit_total_bytes,
                "current_commit_limit_bytes": host_commit.current_commit_limit_bytes,
                "maximum_commit_capacity_bytes": host_commit.maximum_commit_capacity_bytes,
                "reserve_bytes": DISPATCH_HOST_COMMIT_RESERVE_BYTES,
                "maximum_job_memory_bytes": manifest.maximum_job_memory_bytes,
                "simulated_peak_commit_bytes": manifest.simulated_peak_commit_bytes,
            },
            "emberd_identity": {
                "binary_sha256": &self.emberd_binary_sha256,
                "source_sha256": &self.emberd_source_sha256,
            },
        });
        let receipt_bytes = serde_json::to_vec(&receipt_payload)?;
        atomic_replace(&receipt_path, &receipt_bytes)?;
        let receipt = ReceiptArtifact {
            path: receipt_path,
            sha256: hash_bytes(&receipt_bytes),
        };

        self.bind_identity(&manifest.job_id, &manifest_path, &manifest_sha256)?;
        self.acquire_lease(&manifest.resource_lease, &manifest.job_id)?;
        let mut spec = JobSpec::new(
            manifest.job_id,
            program.to_string_lossy().into_owned(),
            manifest.args,
            manifest.resource_lease,
        )
        .with_maximum_job_memory_bytes(manifest.maximum_job_memory_bytes);
        for (key, value) in manifest.env {
            spec = spec.with_env(key, value);
        }
        let handle = self.start_job(spec)?;
        Ok(DispatchOutcome { handle, receipt })
    }

    pub fn start_job(&self, spec: JobSpec) -> Result<JobHandle> {
        self.verify_identity(&spec.job_id)?;
        let argv_json = serde_json::to_string(&spec.args)?;
        let env_json = serde_json::to_string(&spec.env)?;
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
                return Err(EmberdError::PlannedOutageActive {
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
            let (owner, lease_epoch) = lease.ok_or_else(|| EmberdError::LeaseNotOwned {
                resource: spec.resource_lease.clone(),
                job_id: spec.job_id.clone(),
            })?;
            if owner != spec.job_id {
                return Err(EmberdError::LeaseNotOwned {
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
                return Err(EmberdError::InvalidTransition {
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
                params![spec.job_id, now_ms(), json!({"job_object_name":job_object_name}).to_string()],
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
                return Err(EmberdError::InvalidTransition {
                    job_id: spec.job_id.clone(),
                    detail: "start reservation disappeared".into(),
                });
            }
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_prepared',?3)",
                params![spec.job_id, now_ms(), json!({"pid":pid,"job_object_name":job_object_name}).to_string()],
            )?;
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
                return Err(EmberdError::PlannedOutageActive {
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
                return Err(EmberdError::InvalidTransition {
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
                return Err(EmberdError::InvalidTransition {
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

    pub fn job_exit_code(&self, job_id: &str) -> Result<Option<i64>> {
        self.conn()?
            .query_row(
                "SELECT exit_code FROM jobs WHERE job_id=?1",
                [job_id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| EmberdError::JobNotFound {
                job_id: job_id.into(),
            })
    }

    pub fn adopt_job(&self, job_id: &str) -> Result<JobHandle> {
        let row = self.job_process_row(job_id)?;
        if row.state != JobState::Running {
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "only running jobs can be adopted".into(),
            });
        }
        #[cfg(windows)]
        let live = match open_live_status(&row) {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead => {
                let _ = self.mark_exited_unknown(job_id, &row, "job_reconciled_exited_unknown");
                return Err(EmberdError::ProcessUnavailable {
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
                return Err(EmberdError::ProcessControlUncertain {
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
                return Err(EmberdError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
        };
        #[cfg(not(windows))]
        {
            let current =
                inspect_process(row.pid).map_err(|_| EmberdError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })?;
            if current.start_token != row.start_token
                || !same_executable(&current.executable, &row.executable)
            {
                return Err(EmberdError::ProcessIdentityMismatch {
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
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "only running or stopping jobs can be stopped".into(),
            });
        }
        #[cfg(windows)]
        let live = self
            .live
            .lock()
            .map_err(|_| EmberdError::Poisoned)?
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
                return Err(EmberdError::ProcessUnavailable {
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
                return Err(EmberdError::ProcessControlUncertain {
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
                return Err(EmberdError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
        };
        #[cfg(not(windows))]
        {
            let current =
                inspect_process(row.pid).map_err(|_| EmberdError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                })?;
            if current.start_token != row.start_token
                || !same_executable(&current.executable, &row.executable)
            {
                return Err(EmberdError::ProcessIdentityMismatch {
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
                    return Err(EmberdError::InvalidTransition {
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
            self.live.lock().map_err(|_| EmberdError::Poisoned)?.insert(
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
            .ok_or_else(|| EmberdError::JobNotFound {
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
                        return Err(EmberdError::LogEvidenceMismatch {
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
                return Err(EmberdError::LogEvidenceUnsealed {
                    job_id: job_id.into(),
                })
            }
        };
        let receipt = json!({
            "schema":"emberd-operational-receipt-v1",
            "emberd_identity":{
                "binary_sha256":self.emberd_binary_sha256,
                "source_sha256":self.emberd_source_sha256
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
            .ok_or_else(|| EmberdError::JobNotFound {
                job_id: job_id.into(),
            })?;
        if !matches!(
            state,
            JobState::Stopped | JobState::Exited | JobState::Failed
        ) {
            return Err(EmberdError::NonTerminalReceipt {
                job_id: job_id.into(),
                state: state.as_str().into(),
            });
        }
        let bytes = self.receipt_bytes(job_id)?;
        let sha256 = hash_bytes(&bytes);
        fs::create_dir_all(directory)?;
        let path = directory.join(format!("{sha256}.json"));
        if path.exists() {
            if fs::read(&path)? == bytes {
                return Ok(ReceiptArtifact { path, sha256 });
            }
            return Err(EmberdError::ReceiptHashCollision { path });
        }
        match atomic_create(&path, &bytes) {
            Ok(()) => Ok(ReceiptArtifact { path, sha256 }),
            Err(EmberdError::ReceiptAlreadyExists { .. }) if fs::read(&path)? == bytes => {
                Ok(ReceiptArtifact { path, sha256 })
            }
            Err(EmberdError::ReceiptAlreadyExists { .. }) => {
                Err(EmberdError::ReceiptHashCollision { path })
            }
            Err(error) => Err(error),
        }
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
                        Err(EmberdError::MonitorSetupCleanupFailed {
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
                                return Err(EmberdError::PreparedResumeCleanupFailed {
                                    job_id,
                                    transition: format!("{transition_error:?}"),
                                    cleanup: format!("{termination_error:?}"),
                                });
                            }
                            if let Err(cleanup_error) =
                                self.mark_failed(&job_id, "job_recovered_resume_commit_failed")
                            {
                                return Err(EmberdError::PreparedResumeCleanupFailed {
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
            return Err(EmberdError::InvalidTransition {
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
                EmberdError::InvalidTransition {
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
                EmberdError::InvalidTransition {
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
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "stop finalization lost its state or lease epoch fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberdError::InvalidTransition {
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

    fn reclaim_starting_job(&self, job_id: &str, row: &JobProcessRow, kind: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let fenced = tx.execute(
            "UPDATE jobs SET updated_at_ms=?2 WHERE job_id=?1 AND state='starting' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.lease_epoch],
        )?;
        if fenced != 1 {
            return Err(EmberdError::InvalidTransition {
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
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "starting reconciliation lost its held state fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberdError::InvalidTransition {
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
            return Err(EmberdError::InvalidTransition {
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
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "unknown-exit reconciliation lost its state or lease epoch fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberdError::InvalidTransition {
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
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "dead reconciliation lost its state or lease epoch fence".into(),
            });
        }
        let released = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            params![row.resource, job_id, row.lease_epoch],
        )?;
        if released != 1 {
            return Err(EmberdError::InvalidTransition {
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
        self.conn()?
            .query_row(
                "SELECT pid,process_start_token,executable_identity,resource,state,job_object_name,main_thread_id,lease_epoch,stdout_log_path,stderr_log_path,stdout_child_handle,stderr_child_handle FROM jobs WHERE job_id=?1",
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
                    ))
                },
            )
            .optional()?
            .ok_or_else(|| EmberdError::JobNotFound {
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
                })
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
}

#[cfg(windows)]
enum PreparedTransitionError {
    BeforeResume(EmberdError),
    AfterResume(EmberdError),
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
        Err(EmberdError::InvalidIdentityHash {
            value: value.into(),
        })
    }
}
fn hash_file(path: &Path) -> Result<String> {
    Ok(hash_bytes(&fs::read(path)?))
}
fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn verify_dispatch_file(path: &Path, sha256: &str) -> Result<PathBuf> {
    validate_hash(sha256).map_err(|_| EmberdError::InvalidDispatchManifest {
        detail: format!(
            "dispatch binding has an invalid SHA-256: {}",
            path.display()
        ),
    })?;
    let canonical =
        fs::canonicalize(path).map_err(|error| EmberdError::InvalidDispatchManifest {
            detail: format!(
                "dispatch binding is unavailable at {}: {error}",
                path.display()
            ),
        })?;
    if !canonical.is_file() {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: format!("dispatch binding is not a file: {}", canonical.display()),
        });
    }
    let actual = hash_file(&canonical)?;
    if actual != sha256 {
        return Err(EmberdError::DispatchBindingMismatch {
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
        return Err(EmberdError::DispatchBindingMismatch {
            path: path.to_path_buf(),
            expected: expected_sha256.to_string(),
            actual,
        });
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn absolute_under_root(path: &Path, root: &Path) -> Result<PathBuf> {
    if !path.is_absolute() {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: format!("dispatch output path must be absolute: {}", path.display()),
        });
    }
    let name = path
        .file_name()
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: format!("dispatch output path lacks a file name: {}", path.display()),
        })?;
    let parent = path
        .parent()
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: format!("dispatch output path lacks a parent: {}", path.display()),
        })?;
    let parent =
        fs::canonicalize(parent).map_err(|error| EmberdError::InvalidDispatchManifest {
            detail: format!("dispatch output parent is unavailable: {error}"),
        })?;
    if !parent.starts_with(root) {
        return Err(EmberdError::InvalidDispatchManifest {
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
                return Err(EmberdError::InvalidDispatchManifest {
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
                EmberdError::InvalidDispatchManifest {
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
            return Err(EmberdError::InvalidDispatchManifest {
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
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: "resume realization registry is not an exact manifest binding".into(),
        })?;
    let root = registry
        .parent()
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: "resume realization registry lacks a parent directory".into(),
        })?;
    let payload = read_verified_json_snapshot(&registry, &registry_binding.1)?;
    let object = payload
        .as_object()
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
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
        return Err(EmberdError::InvalidDispatchManifest {
            detail: "resume realization registry schema is not closed v2".into(),
        });
    }
    for (field, kind) in [
        ("verifiers", DispatchBindingKind::Verifier),
        ("realization_receipts", DispatchBindingKind::Manifest),
        ("model_configs", DispatchBindingKind::Config),
    ] {
        let records = object.get(field).and_then(Value::as_array).ok_or_else(|| {
            EmberdError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} is not an array"),
            }
        })?;
        if records.len() != 1 {
            return Err(EmberdError::InvalidDispatchManifest {
                detail: format!(
                    "resume realization registry {field} must contain exactly one file"
                ),
            });
        }
        let entry = records[0]
            .as_object()
            .ok_or_else(|| EmberdError::InvalidDispatchManifest {
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
            return Err(EmberdError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} entry schema is not closed"),
            });
        }
        let relative = entry
            .get("path")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty() && !Path::new(value).is_absolute())
            .ok_or_else(|| EmberdError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} path is invalid"),
            })?;
        let declared_sha256 = entry
            .get("sha256")
            .and_then(Value::as_str)
            .filter(|value| is_sha256(value))
            .ok_or_else(|| EmberdError::InvalidDispatchManifest {
                detail: format!("resume realization registry {field} sha256 is invalid"),
            })?;
        let nested = fs::canonicalize(root.join(relative))?;
        if !nested.starts_with(root)
            || !bindings.iter().any(|(path, sha256, binding_kind)| {
                *path == nested && *binding_kind == kind && sha256 == declared_sha256
            })
        {
            return Err(EmberdError::InvalidDispatchManifest {
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
    Err(EmberdError::InvalidDispatchManifest {
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
    let pages_to_bytes = |pages: usize, label: &str| {
        (pages as u64)
            .checked_mul(page_size)
            .ok_or_else(|| EmberdError::InvalidDispatchManifest {
                detail: format!("Windows host commit probe overflowed {label}"),
            })
    };
    let physical_ram_bytes = pages_to_bytes(info.PhysicalTotal, "physical RAM bytes")?;
    let commit_total_bytes = pages_to_bytes(info.CommitTotal, "committed bytes")?;
    let current_commit_limit_bytes =
        pages_to_bytes(info.CommitLimit, "current commit limit bytes")?;
    let (pagefile_maximum_bytes, pagefile_configuration_sha256) =
        configured_pagefile_maximum_bytes()?;
    let maximum_commit_capacity_bytes = physical_ram_bytes
        .checked_add(pagefile_maximum_bytes)
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: "Windows maximum commit capacity overflowed bytes".into(),
        })?;
    if maximum_commit_capacity_bytes < current_commit_limit_bytes {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: "configured pagefile maximum is below the live Windows commit limit".into(),
        });
    }
    if maximum_commit_capacity_bytes < commit_total_bytes {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: "live committed bytes exceed configured maximum commit capacity".into(),
        });
    }
    Ok(HostCommitCapacity {
        physical_ram_bytes,
        pagefile_maximum_bytes,
        pagefile_configuration_source:
            r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PagingFiles"
                .into(),
        pagefile_configuration_sha256,
        commit_total_bytes,
        current_commit_limit_bytes,
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
    if first != ERROR_SUCCESS || bytes < 4 || bytes % 2 != 0 {
        return Err(EmberdError::InvalidDispatchManifest {
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
        return Err(EmberdError::InvalidDispatchManifest {
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
                String::from_utf16(entry).map_err(|_| EmberdError::InvalidDispatchManifest {
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
            .ok_or_else(|| EmberdError::InvalidDispatchManifest {
                detail: "pagefile setting is not a fixed positive maximum".into(),
            })?;
        total_mib = total_mib.checked_add(maximum_mib).ok_or_else(|| {
            EmberdError::InvalidDispatchManifest {
                detail: "pagefile maximum overflowed MiB".into(),
            }
        })?;
    }
    if total_mib == 0 {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: "no fixed pagefile maximum is configured".into(),
        });
    }
    total_mib
        .checked_mul(1024 * 1024)
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: "pagefile maximum overflowed bytes".into(),
        })
}

#[cfg(not(windows))]
pub fn probe_host_commit_capacity() -> Result<HostCommitCapacity> {
    Err(EmberdError::InvalidDispatchManifest {
        detail: "native host commit probing is currently Windows-only".into(),
    })
}

fn available_free_vram_bytes() -> Result<u64> {
    let output = std::process::Command::new("nvidia-smi")
        .args(["--query-gpu=memory.free", "--format=csv,noheader,nounits"])
        .output()
        .map_err(|error| EmberdError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM probe failed to start: {error}"),
        })?;
    if !output.status.success() {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM probe failed with {}", output.status),
        });
    }
    let stdout =
        String::from_utf8(output.stdout).map_err(|error| EmberdError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM output was not UTF-8: {error}"),
        })?;
    let values = stdout
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| line.trim().parse::<u64>())
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(|error| EmberdError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM output was invalid: {error}"),
        })?;
    if values.len() != 1 {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: format!(
                "dispatch requires exactly one visible GPU, observed {}",
                values.len()
            ),
        });
    }
    values[0]
        .checked_mul(1024 * 1024)
        .ok_or_else(|| EmberdError::InvalidDispatchManifest {
            detail: "nvidia-smi VRAM value overflowed bytes".into(),
        })
}
fn emberd_source_hash() -> String {
    let sources: [&[u8]; 5] = [
        include_bytes!("lib.rs"),
        include_bytes!("rpc.rs"),
        include_bytes!("main.rs"),
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

fn migrate_schema(conn: &Connection, log_dir: &Path) -> Result<()> {
    let columns: Vec<String> = {
        let mut statement = conn.prepare("PRAGMA table_info(jobs)")?;
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
            conn.execute_batch(&format!(
                "ALTER TABLE jobs ADD COLUMN {column} {definition}"
            ))?;
        }
    }
    let jobs: Vec<String> = {
        let mut statement =
            conn.prepare("SELECT job_id FROM jobs WHERE stdout_log_path='' OR stderr_log_path=''")?;
        let rows = statement
            .query_map([], |row| row.get(0))?
            .collect::<std::result::Result<_, _>>()?;
        rows
    };
    for job_id in jobs {
        let key = hash_bytes(job_id.as_bytes());
        let stdout = log_dir.join(format!("{key}.stdout.log"));
        let stderr = log_dir.join(format!("{key}.stderr.log"));
        conn.execute(
            "UPDATE jobs SET stdout_log_path=?2,stderr_log_path=?3 WHERE job_id=?1",
            params![job_id, stdout.to_string_lossy(), stderr.to_string_lossy()],
        )?;
    }
    conn.execute(
        "UPDATE jobs SET outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events) WHERE outage_event_cutoff_seq IS NULL AND state IN ('stopped','exited','failed')",
        [],
    )?;
    conn.execute(
        "UPDATE metadata SET value='3' WHERE key='schema_version'",
        [],
    )?;
    Ok(())
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

fn state_writer_lock_path(path: &Path) -> PathBuf {
    let mut name = path
        .file_name()
        .unwrap_or_else(|| std::ffi::OsStr::new("emberd"))
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
            Err(EmberdError::StateWriterBusy { path: lock_path })
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
                Some(80 | 183) => Err(EmberdError::ReceiptAlreadyExists {
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
                Err(EmberdError::ReceiptAlreadyExists {
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
        return Err(EmberdError::InvalidTransition {
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
        return Err(EmberdError::InvalidTransition {
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
        CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_JOB_MEMORY,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, GetCurrentProcess, WaitForSingleObject, CREATE_NEW_PROCESS_GROUP,
        CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT,
        PROCESS_INFORMATION, STARTF_USESTDHANDLES, STARTUPINFOEXW,
    };

    let maximum_job_memory = spec
        .maximum_job_memory_bytes
        .map(usize::try_from)
        .transpose()
        .map_err(|_| EmberdError::InvalidDispatchManifest {
            detail: "maximum job memory does not fit the current Windows address space".into(),
        })?;

    unsafe { windows_sys::Win32::Foundation::SetLastError(0) };
    let name = wide(job_name);
    let job = unsafe { CreateJobObjectW(std::ptr::null(), name.as_ptr()) };
    if job.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    if std::io::Error::last_os_error().raw_os_error() == Some(183) {
        unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
        return Err(EmberdError::InvalidTransition {
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
            CREATE_SUSPENDED
                | CREATE_NEW_PROCESS_GROUP
                | CREATE_UNICODE_ENVIRONMENT
                | EXTENDED_STARTUPINFO_PRESENT,
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
    let mut conn = db.lock().map_err(|_| EmberdError::Poisoned)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let lease: Option<(String, i64)> = tx
        .query_row(
            "SELECT resource,lease_epoch FROM jobs WHERE job_id=?1 AND state='running' AND pid=?2",
            params![job_id, pid],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let (resource, lease_epoch) = lease.ok_or_else(|| EmberdError::InvalidTransition {
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
        return Err(EmberdError::InvalidTransition {
            job_id: job_id.into(),
            detail: "natural-exit monitor lost its state or lease epoch fence".into(),
        });
    }
    let released = tx.execute(
        "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
        params![resource, job_id, lease_epoch],
    )?;
    if released != 1 {
        return Err(EmberdError::InvalidTransition {
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
    })
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
        return Err(EmberdError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        });
    }
    let mut path = vec![0u16; 32768];
    let mut size = path.len() as u32;
    if unsafe { QueryFullProcessImageNameW(handle, 0, path.as_mut_ptr(), &mut size) } == 0 {
        return Err(EmberdError::ProcessUnavailable {
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
        return Err(EmberdError::ProcessUnavailable {
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
    Err(EmberdError::ProcessUnavailable {
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
        "Local\\emberd-{}-{}-{}",
        std::process::id(),
        now_ms(),
        &hash_bytes(job_id.as_bytes())[..16]
    )
}
#[cfg(not(windows))]
fn job_object_name(job_id: &str) -> String {
    format!(
        "emberd-{}-{}",
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
fn inspect_process(pid: u32) -> Result<ProcessIdentity> {
    let exe = fs::read_link(format!("/proc/{pid}/exe"))?;
    let stat = fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let token = stat
        .split_whitespace()
        .nth(21)
        .ok_or_else(|| EmberdError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        })?;
    Ok(ProcessIdentity {
        start_token: token.into(),
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
        Err(EmberdError::ProcessUnavailable {
            job_id: String::new(),
            pid,
        })
    }
}

#[cfg(test)]
mod dispatch_binding_snapshot_tests {
    use super::*;

    #[test]
    fn registry_replacement_between_initial_hash_and_parse_is_rejected() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("emberd-binding-snapshot-{nonce}"));
        fs::create_dir_all(&root).unwrap();
        let registry = root.join("trusted-verifiers.json");
        fs::write(
            &registry,
            br#"{"schema_version":"ember-trusted-verifiers-v2"}"#,
        )
        .unwrap();
        let initially_bound = hash_file(&registry).unwrap();
        fs::write(&registry, br#"{"schema_version":"replaced"}"#).unwrap();

        let error = read_verified_json_snapshot(&registry, &initially_bound).unwrap_err();
        assert!(matches!(error, EmberdError::DispatchBindingMismatch { .. }));
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
}
