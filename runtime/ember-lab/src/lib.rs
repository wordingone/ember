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
#[cfg(windows)]
use std::sync::RwLock;
use std::sync::{Arc, Condvar, Mutex, Weak};
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
const CURRENT_DATABASE_SCHEMA_VERSION: u32 = 7;
const DISPATCH_TOKEN_ENV: &str = "EMBER_LAB_DISPATCH_TOKEN";
const DISPATCH_JOB_ID_ENV: &str = "EMBER_LAB_DISPATCH_JOB_ID";
const DISPATCH_DAEMON_PID_ENV: &str = "EMBER_LAB_DISPATCH_DAEMON_PID";
const DISPATCH_MAXIMUM_JOB_MEMORY_ENV: &str = "EMBER_LAB_DISPATCH_MAXIMUM_JOB_MEMORY_BYTES";
const DISPATCH_VRAM_PROVIDER_ENV: &str = "EMBER_LAB_DISPATCH_VRAM_PROVIDER";
const DISPATCH_VRAM_DEVICE_UUID_ENV: &str = "EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID";
const DISPATCH_VRAM_FRACTION_ENV: &str = "EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS";
const DISPATCH_MAXIMUM_PROCESS_VRAM_ENV: &str = "EMBER_LAB_DISPATCH_MAXIMUM_PROCESS_VRAM_BYTES";
const DISPATCH_MINIMUM_FREE_VRAM_ENV: &str = "EMBER_LAB_DISPATCH_MINIMUM_FREE_VRAM_BYTES";
const DISPATCH_TOKEN_BYTES: usize = 32;
#[cfg(windows)]
const JOB_MEMORY_OVERSHOOT_ALLOWANCE_BASIS_POINTS: u32 = 617;
#[cfg(windows)]
const JOB_MEMORY_OVERSHOOT_ALLOWANCE_BASIS: &str = "windows_job_object_cuda_wddm_measured";
#[cfg(windows)]
const JOB_COMPLETION_KEY: usize = 1;
#[cfg(windows)]
const JOB_TERMINAL_COMPLETION_KEY: usize = 2;
#[cfg(windows)]
const JOB_OBSERVER_CANCEL_COMPLETION_KEY: usize = 3;

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

/// Verifies pinned artifact hashes against their registered locations without acquiring the
/// state-writer lock, mirroring `read_data_catalog_status`. Custody verification is a pure read,
/// and the preflights that consume it (rung entry, evaluation binding, certified launch) run
/// while the ember-lab daemon holds the writer lock -- routing this through `Daemon::open` would
/// make the gate unusable in exactly the deployment shape it exists for.
pub fn read_custody_verify(
    path: &Path,
    hashes: &[String],
    roots: &BTreeMap<String, PathBuf>,
    rehash: bool,
) -> Result<Value> {
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
                "read-only custody verify requires database schema version {CURRENT_DATABASE_SCHEMA_VERSION}, found {schema_version}"
            ),
        });
    }
    data_catalog::custody_verify(&conn, hashes, roots, rehash, now_ms())
}

/// Rolls back the #1581 data-catalog migration specifically (schema version 5 -> 4). This is
/// pinned to the literal version 5, not `CURRENT_DATABASE_SCHEMA_VERSION`: it represents one
/// specific historical transition, and later migrations (e.g. #1721's schema 6) move the
/// "current" version forward without changing what this step means. A database sitting at a
/// later version must roll back through each later step first (e.g.
/// `rollback_empty_artifact_custody_migration` for 6 -> 5) before this one applies.
pub fn rollback_empty_data_catalog_migration(path: &Path) -> Result<()> {
    const ROLLBACK_FROM_SCHEMA_VERSION: u32 = 5;
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
    if schema_version != ROLLBACK_FROM_SCHEMA_VERSION.to_string() {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: format!(
                "data catalog rollback requires database schema version {ROLLBACK_FROM_SCHEMA_VERSION}, found {schema_version}"
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

/// Rolls back the #1721 artifact-custody migration specifically (schema version 6 -> 5). Pinned
/// to the literal version 6 for the same reason `rollback_empty_data_catalog_migration` is
/// pinned to 5: it names one historical transition, not "whatever is current."
pub fn rollback_empty_artifact_custody_migration(path: &Path) -> Result<()> {
    const ROLLBACK_FROM_SCHEMA_VERSION: u32 = 6;
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
    if schema_version != ROLLBACK_FROM_SCHEMA_VERSION.to_string() {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: format!(
                "artifact custody rollback requires database schema version {ROLLBACK_FROM_SCHEMA_VERSION}, found {schema_version}"
            ),
        });
    }
    let event_rows: i64 = tx.query_row(
        "SELECT COUNT(*) FROM data_catalog_location_events",
        [],
        |row| row.get(0),
    )?;
    if event_rows != 0 {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: "artifact custody rollback refuses after location events exist".into(),
        });
    }
    tx.execute_batch(
        "DROP TABLE data_catalog_location_events;
         UPDATE metadata SET value='5' WHERE key='schema_version';",
    )?;
    tx.commit()?;
    Ok(())
}

/// Rolls back the #898 foreign-process-pressure migration specifically (schema 7 -> 6).
/// The rollback is permitted only before the first census changes the pristine migration seed.
pub fn rollback_empty_foreign_process_pressure_migration(path: &Path) -> Result<()> {
    const ROLLBACK_FROM_SCHEMA_VERSION: u32 = 7;
    const PRISTINE_OBSERVATION: &str = r#"{"schema_version":"ember-lab-foreign-process-pressure-observation-v1","result":"NOT_YET_SAMPLED"}"#;
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
    if schema_version != ROLLBACK_FROM_SCHEMA_VERSION.to_string() {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: format!(
                "foreign process pressure rollback requires database schema version {ROLLBACK_FROM_SCHEMA_VERSION}, found {schema_version}"
            ),
        });
    }
    let observation_rows: i64 = tx.query_row(
        "SELECT COUNT(*) FROM foreign_process_pressure_observations",
        [],
        |row| row.get(0),
    )?;
    if observation_rows != 0 {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: "foreign process pressure rollback refuses because the observation ledger is nonempty".into(),
        });
    }
    let pristine_rows: i64 = tx.query_row(
        "SELECT COUNT(*) FROM foreign_process_pressure_state WHERE singleton=1 AND state='probe_failed' AND observed_at_ms=0 AND observation_json=?1",
        [PRISTINE_OBSERVATION],
        |row| row.get(0),
    )?;
    let state_rows: i64 = tx.query_row(
        "SELECT COUNT(*) FROM foreign_process_pressure_state",
        [],
        |row| row.get(0),
    )?;
    if pristine_rows != 1 || state_rows != 1 {
        return Err(EmberLabError::InvalidDataCatalog {
            detail: "foreign process pressure rollback refuses because the singleton is not the pristine migration seed".into(),
        });
    }
    tx.execute_batch(
        "DROP TABLE foreign_process_pressure_observations;
         DROP TABLE foreign_process_pressure_state;
         UPDATE metadata SET value='6' WHERE key='schema_version';",
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
    DiskWallMeasurementDuration {
        elapsed_ms: u64,
        maximum_ms: u64,
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
    WindowContractViolation {
        job_id: String,
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceGuardRearmRequest {
    pub frozen_observation_sha256: String,
    pub breach_class: String,
    pub diagnostic_receipt_path: PathBuf,
    pub diagnostic_receipt_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceGuardDiagnosticReceipt {
    schema_version: String,
    result: String,
    breach_class: String,
    frozen_observation_sha256: String,
    executed_at_ms: i64,
    probe: ResourceGuardDiagnosticProbe,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceGuardDiagnosticProbe {
    resource: String,
    kind: String,
    real_allocation_executed: bool,
    requested_bytes: u64,
    result: String,
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
    vram_wall: Option<VramWallContract>,
    maximum_process_vram_bytes: Option<u64>,
    disk_write_walls: Vec<BoundDiskWriteWall>,
    simulated_peak_commit_bytes: Option<u64>,
    cpu_rate_percent: Option<u32>,
    cpu_pacing_class: DispatchCpuPacingClass,
    requires_ui_responsiveness: bool,
    window_contract: DispatchWindowContract,
    dispatch_token: Option<DispatchToken>,
}

#[derive(Clone, Debug)]
struct BoundDiskWriteWall {
    contract: DiskWriteWallContract,
    baseline_tree_bytes: u64,
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VramDeviceCapacity {
    pub provider: String,
    pub device_uuid: String,
    pub total_bytes: u64,
    pub free_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VramWallContract {
    pub provider: String,
    pub device_uuid: String,
    pub maximum_process_fraction_millionths: u32,
    pub minimum_free_bytes: u64,
    pub consecutive_breach_samples: u32,
    pub sample_interval_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "applicability", content = "contract", rename_all = "snake_case")]
pub enum DispatchVramWall {
    NotApplicable,
    Required(VramWallContract),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DiskWriteWallContract {
    pub volume_root: PathBuf,
    pub write_root: PathBuf,
    pub maximum_write_bytes: u64,
    pub minimum_free_bytes: u64,
    pub sample_interval_ms: u64,
    pub maximum_measurement_duration_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VramWallSample {
    pub observed_at_ms: i64,
    pub pid: u32,
    pub process_start_token: String,
    pub used_bytes: u64,
    pub capacity: VramDeviceCapacity,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum VramWallBreachClass {
    ProcessFraction,
    FreeFloor,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DiskWriteWallSample {
    pub observed_at_ms: i64,
    pub baseline_tree_bytes: u64,
    pub current_tree_bytes: u64,
    pub available_free_bytes: u64,
    pub measurement_duration_ms: u64,
}

const DISK_WALL_SAMPLE_INTERVAL_MS: u64 = 2_000;
const DISK_WALL_MAXIMUM_MEASUREMENT_DURATION_MS: u64 = 250;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiskWallBreachClass {
    NamedRootWriteBudget,
    VolumeFreeFloor,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum VramWallDecision {
    Healthy,
    Pending {
        breach_class: VramWallBreachClass,
        consecutive_observations: u32,
        required_observations: u32,
    },
    ProtectiveStop {
        breach_class: VramWallBreachClass,
        consecutive_observations: u32,
        required_observations: u32,
    },
}

/// Evaluates already-bound nvidia-smi/NVML observations for one owned root
/// process. The torch allocator fraction is only one signal: non-torch CUDA
/// allocations can escape it, so the independent PID/UUID floor sentinel is
/// deliberately load-bearing and uses the same three-sample debounce rule.
pub fn evaluate_vram_wall_samples(
    contract: &VramWallContract,
    samples: &[VramWallSample],
) -> Result<VramWallDecision> {
    validate_vram_wall_contract(contract)?;
    if samples.is_empty() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "VRAM wall requires at least one observation".into(),
        });
    }
    let expected_pid = samples[0].pid;
    let expected_start_token = samples[0].process_start_token.as_str();
    if expected_pid == 0 || expected_start_token.trim().is_empty() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "VRAM wall sample lacks an owned process identity".into(),
        });
    }
    let mut previous_at = None;
    let mut active_class = None;
    let mut consecutive = 0_u32;
    for sample in samples {
        if sample.pid != expected_pid
            || sample.process_start_token != expected_start_token
            || sample.capacity.provider != contract.provider
            || sample.capacity.device_uuid != contract.device_uuid
            || sample.capacity.total_bytes == 0
            || sample.capacity.free_bytes > sample.capacity.total_bytes
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "VRAM wall sample changed PID/start-token/provider/device identity".into(),
            });
        }
        if let Some(previous) = previous_at {
            let gap_ms = sample.observed_at_ms.saturating_sub(previous);
            let maximum_adjacent_gap_ms = contract.sample_interval_ms.saturating_mul(2);
            if sample.observed_at_ms <= previous
                || (gap_ms as u64) < contract.sample_interval_ms
                || (gap_ms as u64) > maximum_adjacent_gap_ms
            {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail:
                        "VRAM wall samples are non-monotone or non-adjacent to the declared cadence"
                            .into(),
                });
            }
        }
        previous_at = Some(sample.observed_at_ms);
        let maximum_process_bytes = sample
            .capacity
            .total_bytes
            .checked_mul(contract.maximum_process_fraction_millionths as u64)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "VRAM wall fraction derivation overflowed".into(),
            })?
            / 1_000_000;
        let class = if sample.capacity.free_bytes < contract.minimum_free_bytes {
            Some(VramWallBreachClass::FreeFloor)
        } else if sample.used_bytes > maximum_process_bytes {
            Some(VramWallBreachClass::ProcessFraction)
        } else {
            None
        };
        if class.is_none() {
            active_class = None;
            consecutive = 0;
            continue;
        }
        if class == active_class {
            consecutive = consecutive.saturating_add(1);
        } else {
            active_class = class;
            consecutive = 1;
        }
    }
    let Some(breach_class) = active_class else {
        return Ok(VramWallDecision::Healthy);
    };
    if consecutive >= contract.consecutive_breach_samples {
        Ok(VramWallDecision::ProtectiveStop {
            breach_class,
            consecutive_observations: consecutive,
            required_observations: contract.consecutive_breach_samples,
        })
    } else {
        Ok(VramWallDecision::Pending {
            breach_class,
            consecutive_observations: consecutive,
            required_observations: contract.consecutive_breach_samples,
        })
    }
}

fn validate_vram_wall_contract(contract: &VramWallContract) -> Result<()> {
    if contract.provider != "nvidia_smi_nvml"
        || !contract.device_uuid.starts_with("GPU-")
        || !(1..=1_000_000).contains(&contract.maximum_process_fraction_millionths)
        || contract.minimum_free_bytes == 0
        || contract.consecutive_breach_samples != 3
        || contract.sample_interval_ms != u64::from(RESOURCE_GUARD_SAMPLE_INTERVAL_MS)
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "VRAM wall contract requires an exact GPU UUID, three breach samples, and the daemon's 2s cadence".into(),
        });
    }
    Ok(())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiskWallDecision {
    Healthy {
        growth_bytes: u64,
    },
    ProtectiveStop {
        breach_class: DiskWallBreachClass,
        growth_bytes: u64,
    },
}

/// Disk growth is monotone inside the immutable named write root, so a bound
/// breach authorizes a stop on its first durable observation. This deliberately
/// differs from the transient VRAM wall's three-sample debounce. A volume-floor
/// breach protects host survival but never attributes foreign writes to the
/// owned job.
pub fn evaluate_disk_write_wall(
    contract: &DiskWriteWallContract,
    sample: &DiskWriteWallSample,
) -> Result<DiskWallDecision> {
    validate_disk_write_wall_contract(contract)?;
    if sample.observed_at_ms <= 0 {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "disk write wall observation timestamp must be positive".into(),
        });
    }
    if sample.current_tree_bytes < sample.baseline_tree_bytes {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "disk write wall named-root measurement shrank below its bound baseline".into(),
        });
    }
    if sample.measurement_duration_ms > contract.maximum_measurement_duration_ms {
        return Err(EmberLabError::DiskWallMeasurementDuration {
            elapsed_ms: sample.measurement_duration_ms,
            maximum_ms: contract.maximum_measurement_duration_ms,
        });
    }
    let growth_bytes = sample.current_tree_bytes - sample.baseline_tree_bytes;
    if growth_bytes > contract.maximum_write_bytes {
        return Ok(DiskWallDecision::ProtectiveStop {
            breach_class: DiskWallBreachClass::NamedRootWriteBudget,
            growth_bytes,
        });
    }
    if sample.available_free_bytes < contract.minimum_free_bytes {
        return Ok(DiskWallDecision::ProtectiveStop {
            breach_class: DiskWallBreachClass::VolumeFreeFloor,
            growth_bytes,
        });
    }
    Ok(DiskWallDecision::Healthy { growth_bytes })
}

fn validate_disk_write_wall_contract(contract: &DiskWriteWallContract) -> Result<()> {
    if !contract.volume_root.is_absolute()
        || !contract.write_root.is_absolute()
        || contract.write_root == contract.volume_root
        || !contract.write_root.starts_with(&contract.volume_root)
        || contract.maximum_write_bytes == 0
        || contract.minimum_free_bytes == 0
        || contract.sample_interval_ms != DISK_WALL_SAMPLE_INTERVAL_MS
        || contract.maximum_measurement_duration_ms != DISK_WALL_MAXIMUM_MEASUREMENT_DURATION_MS
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "disk write wall contract is incomplete or invalid".into(),
        });
    }
    Ok(())
}

#[cfg(windows)]
fn windows_file_link_count(path: &Path) -> Result<u32> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    let file = fs::File::open(path)?;
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe { GetFileInformationByHandle(file.as_raw_handle().cast(), &mut information) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(information.nNumberOfLinks)
}

#[cfg(windows)]
fn measure_disk_write_tree(
    directory: &Path,
    canonical_write_root: &Path,
    started: Instant,
    maximum_duration: Duration,
) -> Result<u64> {
    use std::os::windows::fs::MetadataExt;

    let mut total = 0_u64;
    for entry in fs::read_dir(directory)? {
        if started.elapsed() > maximum_duration {
            return Err(EmberLabError::DiskWallMeasurementDuration {
                elapsed_ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
                maximum_ms: u64::try_from(maximum_duration.as_millis()).unwrap_or(u64::MAX),
            });
        }
        let entry = entry?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!(
                    "disk write wall refuses reparse-point traversal at {}",
                    path.display()
                ),
            });
        }
        let canonical = fs::canonicalize(&path)?;
        if !canonical.starts_with(canonical_write_root) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!(
                    "disk write wall entry escaped its canonical write root: {}",
                    path.display()
                ),
            });
        }
        if metadata.is_dir() {
            total = total
                .checked_add(measure_disk_write_tree(
                    &canonical,
                    canonical_write_root,
                    started,
                    maximum_duration,
                )?)
                .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                    detail: "disk write wall tree byte count overflowed".into(),
                })?;
        } else if metadata.is_file() {
            if windows_file_link_count(&canonical)? != 1 {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: format!(
                        "disk write wall refuses hard-linked file attribution at {}",
                        path.display()
                    ),
                });
            }
            total = total.checked_add(metadata.file_size()).ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "disk write wall tree byte count overflowed".into(),
                }
            })?;
        } else {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!(
                    "disk write wall refuses an unsupported entry at {}",
                    path.display()
                ),
            });
        }
    }
    Ok(total)
}

#[cfg(windows)]
fn measure_disk_write_wall_sample_with_available_free(
    contract: &DiskWriteWallContract,
    baseline_tree_bytes: u64,
    observed_at_ms: i64,
    available_free_bytes: u64,
) -> Result<DiskWriteWallSample> {
    validate_disk_write_wall_contract(contract)?;
    let canonical_volume_root = fs::canonicalize(&contract.volume_root)?;
    let canonical_write_root = fs::canonicalize(&contract.write_root)?;
    if canonical_volume_root.parent().is_some()
        || canonical_write_root == canonical_volume_root
        || !canonical_write_root.starts_with(&canonical_volume_root)
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "disk write wall requires a canonical volume root containing the write root"
                .into(),
        });
    }
    let root_metadata = fs::symlink_metadata(&contract.write_root)?;
    use std::os::windows::fs::MetadataExt;
    if root_metadata.file_attributes() & 0x400 != 0 {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "disk write wall root itself must not be a reparse point".into(),
        });
    }
    let started = Instant::now();
    let maximum_duration = Duration::from_millis(contract.maximum_measurement_duration_ms);
    let current_tree_bytes = measure_disk_write_tree(
        &canonical_write_root,
        &canonical_write_root,
        started,
        maximum_duration,
    )?;
    let elapsed = started.elapsed();
    if elapsed > maximum_duration {
        return Err(EmberLabError::DiskWallMeasurementDuration {
            elapsed_ms: u64::try_from(elapsed.as_millis()).unwrap_or(u64::MAX),
            maximum_ms: contract.maximum_measurement_duration_ms,
        });
    }
    let measurement_duration_ms =
        u64::try_from(elapsed.as_nanos().div_ceil(1_000_000)).unwrap_or(u64::MAX);
    let sample = DiskWriteWallSample {
        observed_at_ms,
        baseline_tree_bytes,
        current_tree_bytes,
        available_free_bytes,
        measurement_duration_ms,
    };
    evaluate_disk_write_wall(contract, &sample)?;
    Ok(sample)
}

#[cfg(not(windows))]
fn measure_disk_write_wall_sample_with_available_free(
    _contract: &DiskWriteWallContract,
    _baseline_tree_bytes: u64,
    _observed_at_ms: i64,
    _available_free_bytes: u64,
) -> Result<DiskWriteWallSample> {
    Err(EmberLabError::InvalidDispatchManifest {
        detail: "disk write wall v5 is currently Windows-only".into(),
    })
}

#[cfg(windows)]
pub fn measure_disk_write_wall_sample(
    contract: &DiskWriteWallContract,
    baseline_tree_bytes: u64,
    observed_at_ms: i64,
) -> Result<DiskWriteWallSample> {
    let canonical_volume_root = fs::canonicalize(&contract.volume_root)?;
    let available_free_bytes = available_free_bytes(&canonical_volume_root)?;
    measure_disk_write_wall_sample_with_available_free(
        contract,
        baseline_tree_bytes,
        observed_at_ms,
        available_free_bytes,
    )
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

/// Declares whether a dispatched job's CPU usage is paced.
///
/// This is a required, closed-choice declaration: no `Option`, no
/// `#[serde(default)]`, and an unknown/missing value is refused rather than
/// silently defaulted (serde's ordinary enum/required-field deserialization
/// already enforces this -- there is deliberately no catch-all/other variant).
/// Later lanes may ADD variants to this enum (additive -- old manifests stay
/// valid); they must never add a default variant.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DispatchCpuPacingClass {
    /// Explicit, visible declaration that this spawn has no CPU pacing. This
    /// is the truth-telling value until a later CPU-enforcement lane lands;
    /// it is never used as a silent/implicit default.
    Unpaced,
    /// Paced by the daemon's governor. At L1 this only carries the
    /// declaration -- a later lane gives it enforcement teeth.
    Governed,
}

/// Declares the window-visibility contract of a dispatched job.
///
/// This is a required, closed-choice declaration: no `Option`, no
/// `#[serde(default)]`, and an unknown/missing value is refused rather than
/// silently defaulted (serde's ordinary enum/required-field deserialization
/// already enforces this -- there is deliberately no catch-all/other variant).
/// Later lanes may ADD variants to this enum (additive -- old manifests stay
/// valid); they must never add a default variant.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DispatchWindowContract {
    /// The spawn presents zero visible windows.
    HeadlessNoWindows,
    /// Visible surface exists only through the cockpit contract.
    CockpitHosted,
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
    pub cpu_pacing_class: DispatchCpuPacingClass,
    pub window_contract: DispatchWindowContract,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    pub bindings: Vec<DispatchFileBinding>,
    pub custody_root: PathBuf,
    pub storage_reserves: Vec<DispatchStorageReserve>,
    #[serde(default)]
    pub vram_wall: Option<DispatchVramWall>,
    #[serde(default)]
    pub disk_write_walls: Vec<DiskWriteWallContract>,
    #[serde(default)]
    pub minimum_free_vram_bytes: u64,
    pub required_available_maximum_commit_bytes: u64,
    pub maximum_job_memory_bytes: u64,
    pub simulated_peak_commit_bytes: u64,
    pub preflight_receipt: PathBuf,
}

/// Field name and legal snake_case spellings for `DispatchManifest`'s
/// closed-choice fields, shared between the parse-error describer below and
/// its tests.
const CPU_PACING_CLASS_FIELD: &str = "cpu_pacing_class";
const CPU_PACING_CLASS_LEGAL_VALUES: &[&str] = &["unpaced", "governed"];
const WINDOW_CONTRACT_FIELD: &str = "window_contract";
const WINDOW_CONTRACT_LEGAL_VALUES: &[&str] = &["headless_no_windows", "cockpit_hosted"];

/// Rewrite a `DispatchManifest` JSON parse failure into a refusal message
/// that names the specific missing/invalid closed-choice field and
/// enumerates its legal values, e.g. `"cpu_pacing_class: missing required
/// field (legal values: unpaced, governed)"`. Falls back to the underlying
/// serde message for every other failure shape (a different missing field,
/// malformed JSON, or a bad value on a field this function does not know
/// about). This never weakens fail-closed behavior --
/// `serde_json::from_slice::<DispatchManifest>` has already performed the
/// real rejection by the time this runs; it only rewrites the text the
/// caller sees.
pub fn describe_dispatch_manifest_parse_error(bytes: &[u8], error: &serde_json::Error) -> String {
    for (field, legal_values) in [
        (CPU_PACING_CLASS_FIELD, CPU_PACING_CLASS_LEGAL_VALUES),
        (WINDOW_CONTRACT_FIELD, WINDOW_CONTRACT_LEGAL_VALUES),
    ] {
        if let Some(detail) = describe_closed_choice_field_error(bytes, field, legal_values) {
            return detail;
        }
    }
    error.to_string()
}

fn describe_closed_choice_field_error(
    bytes: &[u8],
    field: &str,
    legal_values: &[&str],
) -> Option<String> {
    let value: Value = serde_json::from_slice(bytes).ok()?;
    let object = value.as_object()?;
    let legal = legal_values.join(", ");
    match object.get(field) {
        None => Some(format!(
            "{field}: missing required field (legal values: {legal})"
        )),
        Some(Value::String(actual)) if !legal_values.contains(&actual.as_str()) => Some(format!(
            "{field}: invalid value \"{actual}\" (legal values: {legal})"
        )),
        Some(Value::String(_)) => None,
        Some(other) => Some(format!(
            "{field}: invalid value {other} (legal values: {legal})"
        )),
    }
}

#[cfg(test)]
mod dispatch_manifest_refusal_message_tests {
    use super::*;

    fn parse_failure(bytes: &[u8]) -> serde_json::Error {
        serde_json::from_slice::<DispatchManifest>(bytes).unwrap_err()
    }

    #[test]
    fn names_missing_cpu_pacing_class_and_its_legal_values() {
        let bytes = br#"{"window_contract":"headless_no_windows"}"#;
        let error = parse_failure(bytes);
        assert_eq!(
            describe_dispatch_manifest_parse_error(bytes, &error),
            "cpu_pacing_class: missing required field (legal values: unpaced, governed)"
        );
    }

    #[test]
    fn names_invalid_cpu_pacing_class_value_and_its_legal_values() {
        let bytes = br#"{"cpu_pacing_class":"throttled","window_contract":"headless_no_windows"}"#;
        let error = parse_failure(bytes);
        assert_eq!(
            describe_dispatch_manifest_parse_error(bytes, &error),
            "cpu_pacing_class: invalid value \"throttled\" (legal values: unpaced, governed)"
        );
    }

    #[test]
    fn names_missing_window_contract_and_its_legal_values() {
        let bytes = br#"{"cpu_pacing_class":"unpaced"}"#;
        let error = parse_failure(bytes);
        assert_eq!(
            describe_dispatch_manifest_parse_error(bytes, &error),
            "window_contract: missing required field (legal values: headless_no_windows, cockpit_hosted)"
        );
    }

    #[test]
    fn names_invalid_window_contract_value_and_its_legal_values() {
        let bytes = br#"{"cpu_pacing_class":"unpaced","window_contract":"floating"}"#;
        let error = parse_failure(bytes);
        assert_eq!(
            describe_dispatch_manifest_parse_error(bytes, &error),
            "window_contract: invalid value \"floating\" (legal values: headless_no_windows, cockpit_hosted)"
        );
    }

    #[test]
    fn falls_back_to_the_raw_serde_message_for_unrelated_failures() {
        // Both closed-choice fields are present and legal here; the actual
        // failure (malformed top-level JSON) has nothing to do with either,
        // so the describer must not fabricate a field-specific message.
        let bytes = b"not json";
        let error = serde_json::from_slice::<DispatchManifest>(bytes).unwrap_err();
        let detail = describe_dispatch_manifest_parse_error(bytes, &error);
        assert_eq!(detail, error.to_string());
    }
}

const DISPATCH_HOST_COMMIT_RESERVE_BYTES: u64 = 10 * 1024 * 1024 * 1024;
const RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES: u64 = 8 * 1024 * 1024 * 1024;
const RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES: u64 = 10 * 1024 * 1024 * 1024;
const RESOURCE_GUARD_OBSERVATION_LIMIT: i64 = 1024;
const RESOURCE_GUARD_SAMPLE_INTERVAL_MS: u32 = 2_000;
const RESOURCE_GUARD_REARM_BASE_SAMPLE_COUNT: usize = 30;
const RESOURCE_GUARD_REARM_BASE_WINDOW_MS: i64 = 60_000;
const RESOURCE_GUARD_REARM_FRESHNESS_MS: i64 = 10_000;
const RESOURCE_GUARD_REARM_FLAP_WINDOW_MS: i64 = 30 * 60 * 1_000;
const RESOURCE_GUARD_REARM_MAX_MULTIPLIER: usize = 4;
const PROTECTIVE_CHECKPOINT_REQUEST_ENV: &str = "EMBER_LAB_PROTECTIVE_CHECKPOINT_REQUEST_PATH";
const PROTECTIVE_CHECKPOINT_RESPONSE_ENV: &str = "EMBER_LAB_PROTECTIVE_CHECKPOINT_RESPONSE_PATH";
const PROTECTIVE_CHECKPOINT_MAX_GRACE_MS: u64 = 30_000;
const PROTECTIVE_CHECKPOINT_MONITOR_TOTAL_GRACE_MS: u64 = 5_000;
/// Production window-contract census budget (issue #898 L6): how long
/// `poll_for_new_job_owned_windows` keeps checking for a job-owned window
/// after resume before concluding none appeared. Tests that need to
/// distinguish a real refusal from a scheduler-timing race under host load
/// inject a larger budget via
/// `dispatch_manifest_at_with_probes_and_host_and_window_census_budget`
/// instead of shrinking this constant.
const DEFAULT_WINDOW_CENSUS_BUDGET: Duration = Duration::from_millis(200);

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
            vram_wall: None,
            maximum_process_vram_bytes: None,
            disk_write_walls: Vec::new(),
            simulated_peak_commit_bytes: None,
            cpu_rate_percent: None,
            cpu_pacing_class: DispatchCpuPacingClass::Unpaced,
            requires_ui_responsiveness: false,
            window_contract: DispatchWindowContract::HeadlessNoWindows,
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

    pub fn with_vram_wall(
        mut self,
        vram_wall: VramWallContract,
        maximum_process_vram_bytes: u64,
    ) -> Self {
        self.vram_wall = Some(vram_wall);
        self.maximum_process_vram_bytes = Some(maximum_process_vram_bytes);
        self
    }

    fn with_disk_write_walls(mut self, disk_write_walls: Vec<BoundDiskWriteWall>) -> Self {
        self.disk_write_walls = disk_write_walls;
        self
    }

    pub fn with_simulated_peak_commit_bytes(mut self, simulated_peak_commit_bytes: u64) -> Self {
        self.simulated_peak_commit_bytes = Some(simulated_peak_commit_bytes);
        self
    }

    pub fn with_cpu_rate_percent(mut self, cpu_rate_percent: u32) -> Self {
        self.cpu_rate_percent = Some(cpu_rate_percent);
        self
    }

    /// Declares the job's CPU *pacing contract*, which is not the same thing
    /// as whether the host caps it. The `cpu_rate_percent` hard cap above is
    /// host-side defense-in-depth and is applied to every managed spawn
    /// regardless of this value -- it never comes off. This declaration only
    /// decides whether the spawn additionally proves the cap took: `Governed`
    /// re-reads the job object after setting it and refuses the spawn if the
    /// kernel did not accept the requested rate, and records that proof in
    /// the `job_prepared` receipt. `Unpaced` (the default, so an undeclared
    /// spec claims nothing) means no pacing contract was declared and no such
    /// proof is produced.
    pub fn with_cpu_pacing_class(mut self, cpu_pacing_class: DispatchCpuPacingClass) -> Self {
        self.cpu_pacing_class = cpu_pacing_class;
        self
    }

    /// Declares whether the spawned process is allowed to interact with the
    /// interactive desktop (clipboard, display settings, global atoms,
    /// cross-job USER handles, ExitWindows). Defaults to `false` (restricted)
    /// so an undeclared job is walled off, not left open by omission. Only
    /// the closed `Cockpit` workload profile is permitted to request `true`
    /// (`validate_dispatch_workload_profile` enforces the pairing before this
    /// spec is ever built from a manifest).
    pub fn with_requires_ui_responsiveness(mut self, requires_ui_responsiveness: bool) -> Self {
        self.requires_ui_responsiveness = requires_ui_responsiveness;
        self
    }

    /// Declares the spawned process's window-visibility contract (issue
    /// #898 L6). Defaults to `HeadlessNoWindows` -- the same
    /// restricted-by-omission posture as `requires_ui_responsiveness`.
    /// `HeadlessNoWindows` is enforced by a live before/after top-level
    /// window census taken around the spawn's resume (see
    /// `census_top_level_windows`/`poll_for_new_job_owned_windows`):
    /// any window that appears and belongs to the job is a fail-closed
    /// refusal. `CockpitHosted` is exempt -- the cockpit's own window is
    /// the contract's named exception.
    pub fn with_window_contract(mut self, window_contract: DispatchWindowContract) -> Self {
        self.window_contract = window_contract;
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
    completion_port: OwnedHandle,
    process: OwnedHandle,
    _stdout_log_guard: OwnedHandle,
    _stderr_log_guard: OwnedHandle,
    pid: u32,
    identity: ProcessIdentity,
    job_memory_contract: JobMemoryContract,
}

#[cfg(windows)]
#[derive(Clone, Copy)]
struct JobMemoryContract {
    maximum_job_memory_bytes: Option<u64>,
    simulated_peak_commit_bytes: Option<u64>,
    overshoot_allowance_basis_points: u32,
    kernel_limit_signal_observation_available: bool,
}

#[cfg(windows)]
struct JobMonitorHandles {
    waiter: OwnedHandle,
    shutdown: OwnedHandle,
    observer_job: OwnedHandle,
    observer_process: OwnedHandle,
    observer_port: OwnedHandle,
    terminal_job: OwnedHandle,
    terminal_process: OwnedHandle,
    terminal_port: OwnedHandle,
}

#[cfg(windows)]
struct JobMemoryObserverRegistration {
    db: Weak<Mutex<Connection>>,
    job_id: String,
    root_pid: u32,
    job: OwnedHandle,
    process: OwnedHandle,
    completion_port: OwnedHandle,
    expected_identity: ProcessIdentity,
    contract: JobMemoryContract,
}

#[cfg(windows)]
struct ExitMonitorRegistration {
    db: Weak<Mutex<Connection>>,
    retained: Weak<Mutex<HashMap<String, RetainedProcess>>>,
    ownership: Arc<RwLock<bool>>,
    shutdown: OwnedHandle,
    job_id: String,
    pid: u32,
    lease_epoch: i64,
    waiter: OwnedHandle,
    terminal_job: OwnedHandle,
    terminal_process: OwnedHandle,
    terminal_port: OwnedHandle,
    memory_barrier: Arc<JobMemoryObserverBarrier>,
}

#[cfg(windows)]
#[derive(Default)]
struct JobMemoryObserverBarrier {
    outcome: Mutex<Option<std::result::Result<(), String>>>,
    ready: Condvar,
}

#[cfg(windows)]
impl JobMemoryObserverBarrier {
    fn complete(&self, outcome: std::result::Result<(), String>) {
        if let Ok(mut stored) = self.outcome.lock() {
            *stored = Some(outcome);
            self.ready.notify_all();
        }
    }

    fn wait(&self) -> Result<()> {
        let stored = self.outcome.lock().map_err(|_| EmberLabError::Poisoned)?;
        let (stored, timeout) = self
            .ready
            .wait_timeout_while(stored, Duration::from_secs(5), |outcome| outcome.is_none())
            .map_err(|_| EmberLabError::Poisoned)?;
        if timeout.timed_out() && stored.is_none() {
            return Err(std::io::Error::other("job-memory observer barrier timed out").into());
        }
        match stored.as_ref().expect("barrier outcome exists after wait") {
            Ok(()) => Ok(()),
            Err(error) => Err(std::io::Error::other(error.clone()).into()),
        }
    }
}

#[cfg(windows)]
struct RetainedProcess {
    live: LiveProcess,
    monitored: bool,
    memory_barrier: Option<Arc<JobMemoryObserverBarrier>>,
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

#[derive(Debug, Clone, Serialize)]
pub struct WallObservationDaemonIdentity {
    pub schema_version: &'static str,
    pub pid: u32,
    pub binary_sha256: String,
    pub source_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct VramWallObservationSnapshotRow {
    pub seq: i64,
    pub job_id: String,
    pub observed_at_ms: i64,
    pub outcome: String,
    pub payload: Value,
}

#[derive(Debug, Clone, Serialize)]
pub struct DiskWallObservationSnapshotRow {
    pub seq: i64,
    pub job_id: String,
    pub write_root: String,
    pub observed_at_ms: i64,
    pub outcome: String,
    pub payload: Value,
}

#[derive(Debug, Clone, Serialize)]
pub struct WallObservationSnapshot {
    pub schema_version: &'static str,
    pub captured_at_ms: i64,
    pub after_vram_seq: i64,
    pub after_disk_seq: i64,
    pub next_vram_seq: i64,
    pub next_disk_seq: i64,
    pub daemon_identity: WallObservationDaemonIdentity,
    pub vram_observations: Vec<VramWallObservationSnapshotRow>,
    pub disk_observations: Vec<DiskWallObservationSnapshotRow>,
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
    fn verify_owned_live_process(&self, job_id: &str, row: &JobProcessRow) -> Result<()> {
        let retained = self.live.lock().map_err(|_| EmberLabError::Poisoned)?;
        if let Some(retained) = retained.get(job_id) {
            if retained.live.pid != row.pid
                || retained.live.identity.start_token != row.start_token
                || !same_executable(&retained.live.identity.executable, &row.executable)
            {
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail: "retained process identity does not match the persisted job".into(),
                });
            }
            if !live_process_is_running(&retained.live) {
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
            return Ok(());
        }
        drop(retained);
        match open_live_status(row) {
            LiveStatus::Verified(_) => Ok(()),
            LiveStatus::Dead => Err(EmberLabError::ProcessUnavailable {
                job_id: job_id.into(),
                pid: row.pid,
            }),
            LiveStatus::Orphaned(detail) | LiveStatus::IdentityConflict(detail) => {
                Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                })
            }
        }
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
        self.verify_owned_live_process(job_id, &row)?;

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

        self.verify_owned_live_process(job_id, &row)?;

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

        let retained = self
            .live
            .lock()
            .map_err(|_| EmberLabError::Poisoned)?
            .remove(job_id);
        let (live, memory_barrier) = match retained {
            Some(retained) => (LiveStatus::Verified(retained.live), retained.memory_barrier),
            None => (open_live_status(&row), None),
        };
        let live = match live {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead => {
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
            LiveStatus::Orphaned(detail) | LiveStatus::IdentityConflict(detail) => {
                return Err(EmberLabError::ProcessControlUncertain {
                    job_id: job_id.into(),
                    pid: row.pid,
                    detail,
                });
            }
        };
        if let Err(error) = terminate_live(&live) {
            self.live
                .lock()
                .map_err(|_| EmberLabError::Poisoned)?
                .insert(
                    job_id.into(),
                    RetainedProcess {
                        live,
                        monitored: false,
                        memory_barrier,
                    },
                );
            return Err(error);
        }
        if let Some(memory_barrier) = memory_barrier {
            use windows_sys::Win32::System::IO::PostQueuedCompletionStatus;
            if unsafe {
                PostQueuedCompletionStatus(
                    live.completion_port.raw(),
                    0,
                    JOB_TERMINAL_COMPLETION_KEY,
                    std::ptr::null(),
                )
            } == 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
            memory_barrier.wait()?;
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

/// Bundles the injectable dispatch-manifest probes (free-space, free-VRAM,
/// free-host-commit) and the window-census budget into one value, so a new
/// injectable knob widens this struct instead of adding another positional
/// parameter to `dispatch_manifest_bytes_at_with_probes_and_host_inner` and
/// pushing it back over clippy's argument-count cap (#898 L6 follow-up).
enum DispatchVramObservation {
    LegacyFreeBytes(u64),
    Device(VramDeviceCapacity),
}

impl From<u64> for DispatchVramObservation {
    fn from(value: u64) -> Self {
        Self::LegacyFreeBytes(value)
    }
}

impl From<VramDeviceCapacity> for DispatchVramObservation {
    fn from(value: VramDeviceCapacity) -> Self {
        Self::Device(value)
    }
}

struct DispatchProbes<F, G, H> {
    free_space: F,
    free_vram: G,
    free_host_commit: H,
    window_census_budget: Duration,
}

#[cfg(any(not(windows), test))]
fn consume_dispatch_token_with_process_observer<F>(
    conn: &mut Connection,
    job_id: &str,
    token: &str,
    client_pid: u32,
    mut observe_process: F,
) -> Result<()>
where
    F: FnMut(u32) -> Result<ProcessIdentity>,
{
    let observed_identity =
        observe_process(client_pid).map_err(|_| EmberLabError::DispatchTokenRefused {
            job_id: job_id.into(),
        })?;
    consume_dispatch_token_transaction(conn, job_id, token, client_pid, &observed_identity, || {
        let final_identity =
            observe_process(client_pid).map_err(|_| EmberLabError::DispatchTokenRefused {
                job_id: job_id.into(),
            })?;
        Ok(final_identity.start_token == observed_identity.start_token
            && same_executable(&final_identity.executable, &observed_identity.executable))
    })
}

fn consume_dispatch_token_transaction<F>(
    conn: &mut Connection,
    job_id: &str,
    token: &str,
    client_pid: u32,
    observed_identity: &ProcessIdentity,
    final_identity_matches: F,
) -> Result<()>
where
    F: FnOnce() -> Result<bool>,
{
    let token_sha256 = hash_bytes(token.as_bytes());
    let consumed_at_ms = now_ms();
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
        || !final_identity_matches()?
    {
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

impl Daemon {
    pub fn open(path: &Path) -> Result<Self> {
        Self::open_inner(path, probe_host_survival_headroom())
    }

    /// Debug-build integration seam. It exercises the real `Daemon::open`
    /// schema/migration/registration path while replacing only the resource
    /// guard's startup headroom sample -- the one host observation a CI
    /// runner cannot be relied on to match the production survival floor.
    /// It is absent from release builds and is not reachable through Ember
    /// Lab RPC.
    #[cfg(debug_assertions)]
    #[doc(hidden)]
    pub fn open_with_resource_guard_seed(
        path: &Path,
        resource_guard_seed: Result<HostCommitCapacity>,
    ) -> Result<Self> {
        Self::open_inner(
            path,
            resource_guard_seed.map(|capacity| HostSurvivalHeadroom {
                physical_available_bytes: capacity.physical_available_bytes,
                commit_remaining_bytes: capacity.current_commit_remaining_bytes,
            }),
        )
    }

    fn open_inner(path: &Path, resource_guard_seed: Result<HostSurvivalHeadroom>) -> Result<Self> {
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
        #[cfg(windows)]
        let foreign_process_provider: Arc<dyn ForeignProcessCensusProvider> =
            Arc::new(WindowsForeignProcessCensusProvider);
        let mut conn = Connection::open(path)?;
        let ember_lab_binary_sha256 = hash_file(&std::env::current_exe()?)?;
        let ember_lab_source_sha256 = ember_lab_source_hash();
        conn.busy_timeout(Duration::from_secs(10))?;
        conn.execute_batch(r#"PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
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
            CREATE TABLE IF NOT EXISTS job_vram_walls(job_id TEXT PRIMARY KEY, contract_json TEXT NOT NULL, maximum_process_vram_bytes INTEGER NOT NULL, consecutive_breach_observations INTEGER NOT NULL DEFAULT 0, active_breach_class TEXT, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
            CREATE TABLE IF NOT EXISTS vram_wall_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
            CREATE TABLE IF NOT EXISTS job_disk_walls(job_id TEXT NOT NULL, write_root TEXT NOT NULL, contract_json TEXT NOT NULL, baseline_tree_bytes INTEGER NOT NULL, consecutive_duration_misses INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id,write_root), FOREIGN KEY(job_id) REFERENCES jobs(job_id));
            CREATE TABLE IF NOT EXISTS disk_wall_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, write_root TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
            CREATE TABLE IF NOT EXISTS disk_volume_floor_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, volume_root TEXT NOT NULL, available_free_bytes INTEGER NOT NULL, payload_json TEXT NOT NULL, UNIQUE(observed_at_ms,volume_root));
            CREATE TABLE IF NOT EXISTS resource_guard_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), admission_state TEXT NOT NULL CHECK(admission_state IN ('open','frozen')), reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL CHECK(oracle_evidence_required IN (0,1)), observation_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resource_guard_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resource_guard_rearms(frozen_observation_sha256 TEXT PRIMARY KEY, breach_class TEXT NOT NULL, transitioned_at_ms INTEGER NOT NULL, receipt_path TEXT NOT NULL, receipt_sha256 TEXT NOT NULL UNIQUE, healthy_sample_count INTEGER NOT NULL, healthy_window_ms INTEGER NOT NULL, flap_multiplier INTEGER NOT NULL);
            INSERT OR IGNORE INTO resource_guard_state(singleton,admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json) VALUES(1,'open',NULL,0,0,'{}');
            CREATE TABLE IF NOT EXISTS foreign_process_pressure_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL CHECK(state IN ('clear','observed','fenced','probe_failed')), observed_at_ms INTEGER NOT NULL, observation_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS foreign_process_pressure_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
            INSERT OR IGNORE INTO foreign_process_pressure_state(singleton,state,observed_at_ms,observation_json) VALUES(1,'probe_failed',0,'{"schema_version":"ember-lab-foreign-process-pressure-observation-v1","result":"NOT_YET_SAMPLED"}');"#)?;
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
        // Linux gets the same real point-in-time headroom seed as Windows so
        // `resource_guard_state` is never left at its empty-observation seed
        // row (which reads as `available_headroom_bytes = 0` everywhere that
        // consumes it, e.g. supervise_server_live_cycle). The periodic
        // re-sampling monitor below stays Windows-only -- it depends on
        // WaitForSingleObject/job-object machinery with no Linux equivalent
        // wired up yet; porting that loop is separate, larger scope.
        persist_resource_guard_headroom(&*daemon.conn()?, now_ms(), resource_guard_seed)?;
        #[cfg(windows)]
        {
            let owned_jobs = {
                let conn = daemon.conn()?;
                owned_job_identities_from_connection(&conn)?
            };
            let observed_at_ms = now_ms();
            let census =
                sample_foreign_process_census(foreign_process_provider.as_ref(), &owned_jobs);
            persist_foreign_process_census(&*daemon.conn()?, observed_at_ms, census)?;
            spawn_resource_guard_monitor(
                Arc::downgrade(&daemon.db),
                Arc::downgrade(&daemon.live),
                daemon.log_dir.clone(),
                duplicate_owned_handle(daemon.monitor_shutdown.raw())?,
                Arc::downgrade(&daemon.monitor_ownership),
                foreign_process_provider,
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

    pub fn foreign_process_pressure_status(&self) -> Result<Value> {
        let conn = self.conn()?;
        foreign_process_pressure_status_from_connection(&conn)
    }

    pub fn foreign_process_pressure_probe_receipt(&self, output: &Path) -> Result<ReceiptArtifact> {
        let status = self.foreign_process_pressure_status()?;
        let state = status.get("state").and_then(Value::as_str).ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure state is missing".into(),
            }
        })?;
        let observed_at_ms = status
            .get("observed_at_ms")
            .and_then(Value::as_i64)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure timestamp is missing".into(),
            })?;
        let observation = status.get("observation").cloned().ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure observation is missing".into(),
            }
        })?;
        if observation.get("probe_complete") != Some(&Value::Bool(true)) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe receipt requires a complete production observation"
                    .into(),
            });
        }
        let observation_sha256 = hash_bytes(&serde_json::to_vec(&observation)?);
        let mut receipt = json!({
            "schema_version": "ember-lab-foreign-process-pressure-probe-v1",
            "verdict": "EXECUTED",
            "state": state,
            "observed_at_ms": observed_at_ms,
            "observation": observation,
            "observation_sha256": observation_sha256,
            "ember_lab_identity": {
                "binary_sha256": self.ember_lab_binary_sha256,
                "source_sha256": self.ember_lab_source_sha256,
            },
            "foreign_process_control": false,
        });
        let receipt_sha256 = hash_bytes(&serde_json::to_vec(&receipt)?);
        receipt.as_object_mut().unwrap().insert(
            "receipt_sha256".into(),
            Value::String(receipt_sha256.clone()),
        );
        let bytes = serde_json::to_vec_pretty(&receipt)?;
        verify_foreign_process_pressure_probe_receipt(&bytes)?;
        if output.exists() {
            return Err(EmberLabError::ReceiptAlreadyExists {
                path: output.to_path_buf(),
            });
        }
        fs::create_dir(output)?;
        let path = output.join(format!("{receipt_sha256}.json"));
        atomic_create(&path, &bytes)?;
        Ok(ReceiptArtifact {
            path,
            sha256: receipt_sha256,
        })
    }

    pub fn wall_observation_snapshot(
        &self,
        after_vram_seq: i64,
        after_disk_seq: i64,
    ) -> Result<WallObservationSnapshot> {
        if after_vram_seq < 0 || after_disk_seq < 0 {
            return Err(
                std::io::Error::other("wall observation cursors must be nonnegative").into(),
            );
        }
        let mut conn = self.conn()?;
        let transaction = conn.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let vram_observations = {
            let mut statement = transaction.prepare(
                "SELECT seq,job_id,observed_at_ms,outcome,payload_json FROM vram_wall_observations WHERE seq>?1 ORDER BY seq LIMIT 4096",
            )?;
            let rows = statement
                .query_map([after_vram_seq], |row| {
                    let payload_json: String = row.get(4)?;
                    let payload = serde_json::from_str(&payload_json).map_err(|error| {
                        rusqlite::Error::FromSqlConversionFailure(
                            4,
                            rusqlite::types::Type::Text,
                            Box::new(error),
                        )
                    })?;
                    Ok(VramWallObservationSnapshotRow {
                        seq: row.get(0)?,
                        job_id: row.get(1)?,
                        observed_at_ms: row.get(2)?,
                        outcome: row.get(3)?,
                        payload,
                    })
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            rows
        };
        let disk_observations = {
            let mut statement = transaction.prepare(
                "SELECT seq,job_id,write_root,observed_at_ms,outcome,payload_json FROM disk_wall_observations WHERE seq>?1 ORDER BY seq LIMIT 4096",
            )?;
            let rows = statement
                .query_map([after_disk_seq], |row| {
                    let payload_json: String = row.get(5)?;
                    let payload = serde_json::from_str(&payload_json).map_err(|error| {
                        rusqlite::Error::FromSqlConversionFailure(
                            5,
                            rusqlite::types::Type::Text,
                            Box::new(error),
                        )
                    })?;
                    Ok(DiskWallObservationSnapshotRow {
                        seq: row.get(0)?,
                        job_id: row.get(1)?,
                        write_root: row.get(2)?,
                        observed_at_ms: row.get(3)?,
                        outcome: row.get(4)?,
                        payload,
                    })
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            rows
        };
        let next_vram_seq = vram_observations
            .last()
            .map(|row| row.seq)
            .unwrap_or(after_vram_seq);
        let next_disk_seq = disk_observations
            .last()
            .map(|row| row.seq)
            .unwrap_or(after_disk_seq);
        transaction.commit()?;
        Ok(WallObservationSnapshot {
            schema_version: "ember-lab-wall-observation-snapshot-v1",
            captured_at_ms: now_ms(),
            after_vram_seq,
            after_disk_seq,
            next_vram_seq,
            next_disk_seq,
            daemon_identity: WallObservationDaemonIdentity {
                schema_version: "ember-lab-runtime-identity-v1",
                pid: std::process::id(),
                binary_sha256: self.ember_lab_binary_sha256.clone(),
                source_sha256: self.ember_lab_source_sha256.clone(),
            },
            vram_observations,
            disk_observations,
        })
    }

    pub fn rearm_resource_guard(
        &self,
        request: ResourceGuardRearmRequest,
    ) -> Result<ReceiptArtifact> {
        self.rearm_resource_guard_inner(request, now_ms())
    }

    #[cfg(debug_assertions)]
    #[doc(hidden)]
    pub fn rearm_resource_guard_at(
        &self,
        request: ResourceGuardRearmRequest,
        observed_at_ms: i64,
    ) -> Result<ReceiptArtifact> {
        self.rearm_resource_guard_inner(request, observed_at_ms)
    }

    fn rearm_resource_guard_inner(
        &self,
        request: ResourceGuardRearmRequest,
        transition_at_ms: i64,
    ) -> Result<ReceiptArtifact> {
        let diagnostic_bytes = fs::read(&request.diagnostic_receipt_path)?;
        if !is_sha256(&request.frozen_observation_sha256)
            || !is_sha256(&request.diagnostic_receipt_sha256)
            || hash_bytes(&diagnostic_bytes) != request.diagnostic_receipt_sha256
            || request
                .diagnostic_receipt_path
                .file_stem()
                .and_then(|value| value.to_str())
                != Some(request.diagnostic_receipt_sha256.as_str())
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm diagnostic receipt is not content-addressed".into(),
            });
        }
        let diagnostic: ResourceGuardDiagnosticReceipt = serde_json::from_slice(&diagnostic_bytes)?;
        let expected_resource = match request.breach_class.as_str() {
            "commit_remaining_below_survival_floor" => "host_commit",
            "physical_available_below_survival_floor" => "host_physical_memory",
            "resource_guard_probe_failed" => "host_resource_counters",
            _ => {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "resource guard re-arm breach class is not closed".into(),
                })
            }
        };
        if diagnostic.schema_version != "ember-lab-resource-guard-diagnostic-v1"
            || diagnostic.result != "EXECUTED"
            || diagnostic.breach_class != request.breach_class
            || diagnostic.frozen_observation_sha256 != request.frozen_observation_sha256
            || diagnostic.probe.resource != expected_resource
            || diagnostic.probe.kind != "allocation_probe"
            || !diagnostic.probe.real_allocation_executed
            || diagnostic.probe.requested_bytes == 0
            || diagnostic.probe.result != "COMPLETED"
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm diagnostic receipt is not an executed bound probe"
                    .into(),
            });
        }

        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (state, reason, freeze_at_ms, frozen_observation_json): (
            String,
            Option<String>,
            i64,
            String,
        ) = tx.query_row(
            "SELECT admission_state,reason,observed_at_ms,observation_json FROM resource_guard_state WHERE singleton=1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )?;
        if state != "frozen"
            || reason.as_deref() != Some(request.breach_class.as_str())
            || hash_bytes(frozen_observation_json.as_bytes()) != request.frozen_observation_sha256
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm does not bind the live frozen observation".into(),
            });
        }
        let already_consumed: i64 = tx.query_row(
            "SELECT COUNT(*) FROM resource_guard_rearms WHERE frozen_observation_sha256=?1",
            [&request.frozen_observation_sha256],
            |row| row.get(0),
        )?;
        if already_consumed != 0 {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm frozen observation was already consumed".into(),
            });
        }
        let freeze_seq: i64 = tx
            .query_row(
                "SELECT seq FROM resource_guard_observations WHERE observed_at_ms=?1 AND outcome='frozen' AND payload_json=?2 ORDER BY seq DESC LIMIT 1",
                params![freeze_at_ms, frozen_observation_json],
                |row| row.get(0),
            )
            .map_err(|_| EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm freeze-causing observation row is absent".into(),
            })?;
        let recent_rearms: i64 = tx.query_row(
            "SELECT COUNT(*) FROM resource_guard_rearms WHERE breach_class=?1 AND transitioned_at_ms>=?2 AND transitioned_at_ms<?3",
            params![
                request.breach_class,
                transition_at_ms - RESOURCE_GUARD_REARM_FLAP_WINDOW_MS,
                transition_at_ms,
            ],
            |row| row.get(0),
        )?;
        let shift = u32::try_from(recent_rearms.max(0))
            .unwrap_or(u32::MAX)
            .min(2);
        let flap_multiplier = (1usize << shift).min(RESOURCE_GUARD_REARM_MAX_MULTIPLIER);
        let required_samples = RESOURCE_GUARD_REARM_BASE_SAMPLE_COUNT * flap_multiplier;
        let required_window_ms = RESOURCE_GUARD_REARM_BASE_WINDOW_MS
            * i64::try_from(flap_multiplier).unwrap_or(i64::MAX);

        let mut statement = tx.prepare(
            "SELECT seq,observed_at_ms,outcome,payload_json FROM resource_guard_observations WHERE seq>?1 ORDER BY seq",
        )?;
        let rows = statement.query_map([freeze_seq], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
            ))
        })?;
        let mut healthy_tail: Vec<(i64, i64, String)> = Vec::new();
        for row in rows {
            let (seq, observed_at_ms, outcome, payload_json) = row?;
            if outcome != "healthy" {
                healthy_tail.clear();
                continue;
            }
            let payload: Value = serde_json::from_str(&payload_json)?;
            let physical = payload
                .get("physical_available_bytes")
                .and_then(Value::as_u64);
            let commit = payload
                .get("commit_remaining_bytes")
                .and_then(Value::as_u64);
            let payload_physical_floor = payload
                .get("minimum_physical_available_bytes")
                .and_then(Value::as_u64);
            let payload_commit_floor = payload
                .get("minimum_commit_remaining_bytes")
                .and_then(Value::as_u64);
            let physical_required = RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES
                .checked_mul(3)
                .and_then(|value| value.checked_div(2));
            let commit_required = RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES
                .checked_mul(3)
                .and_then(|value| value.checked_div(2));
            if payload.get("schema_version")
                != Some(&Value::String(
                    "ember-lab-resource-guard-observation-v1".into(),
                ))
                || payload.get("result") != Some(&Value::String("HEALTHY".into()))
                || payload.get("observed_at_ms") != Some(&Value::from(observed_at_ms))
                || payload_physical_floor != Some(RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES)
                || payload_commit_floor != Some(RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES)
                || physical
                    .zip(physical_required)
                    .is_none_or(|(actual, floor)| actual < floor)
                || commit
                    .zip(commit_required)
                    .is_none_or(|(actual, floor)| actual < floor)
            {
                healthy_tail.clear();
                continue;
            }
            healthy_tail.push((seq, observed_at_ms, payload_json));
        }
        drop(statement);
        if healthy_tail.len() < required_samples {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm healthy sample count is insufficient".into(),
            });
        }
        let first_healthy_at_ms = healthy_tail.first().map(|row| row.1).unwrap_or_default();
        let (newest_healthy_seq, newest_healthy_at_ms, newest_healthy_json) =
            healthy_tail.last().cloned().unwrap_or_default();
        let healthy_window_ms = newest_healthy_at_ms - first_healthy_at_ms;
        let freshness_ms = transition_at_ms - newest_healthy_at_ms;
        if healthy_window_ms < required_window_ms {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm healthy window is too short".into(),
            });
        }
        if !(0..=RESOURCE_GUARD_REARM_FRESHNESS_MS).contains(&freshness_ms) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm newest healthy observation is stale or future"
                    .into(),
            });
        }
        if diagnostic.executed_at_ms < first_healthy_at_ms
            || diagnostic.executed_at_ms > newest_healthy_at_ms
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail:
                    "resource guard re-arm diagnostic did not execute inside the healthy window"
                        .into(),
            });
        }
        let newest_row_at_commit: (i64, i64, String, String) = tx.query_row(
            "SELECT seq,observed_at_ms,outcome,payload_json FROM resource_guard_observations ORDER BY seq DESC LIMIT 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )?;
        if newest_row_at_commit
            != (
                newest_healthy_seq,
                newest_healthy_at_ms,
                "healthy".into(),
                newest_healthy_json.clone(),
            )
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm newest healthy observation changed before transition commit"
                    .into(),
            });
        }

        let receipt = json!({
            "schema_version": "ember-lab-resource-guard-rearm-v1",
            "result": "RESOURCE_GUARD_REARMED",
            "transitioned_at_ms": transition_at_ms,
            "breach_class": request.breach_class,
            "frozen_observation_sha256": request.frozen_observation_sha256,
            "diagnostic_receipt_path": request.diagnostic_receipt_path,
            "diagnostic_receipt_sha256": request.diagnostic_receipt_sha256,
            "healthy_window": {
                "sample_count": healthy_tail.len(),
                "first_observed_at_ms": first_healthy_at_ms,
                "newest_observed_at_ms": newest_healthy_at_ms,
                "span_ms": healthy_window_ms,
                "freshness_ms": freshness_ms,
                "hysteresis_numerator": 3,
                "hysteresis_denominator": 2,
                "minimum_physical_available_bytes": RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES,
                "minimum_commit_remaining_bytes": RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES,
            },
            "flap_guard": {
                "prior_same_class_rearms_within_30m": recent_rearms,
                "multiplier": flap_multiplier,
                "required_sample_count": required_samples,
                "required_window_ms": required_window_ms,
                "maximum_multiplier": RESOURCE_GUARD_REARM_MAX_MULTIPLIER,
            },
            "transition": {"from": "frozen", "to": "open"},
        });
        let receipt_bytes = serde_json::to_vec_pretty(&receipt)?;
        let artifact = write_content_addressed_receipt(
            &self.log_dir.join("resource-guard-rearms"),
            &receipt_bytes,
        )?;
        tx.execute(
            "INSERT INTO resource_guard_rearms(frozen_observation_sha256,breach_class,transitioned_at_ms,receipt_path,receipt_sha256,healthy_sample_count,healthy_window_ms,flap_multiplier) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![
                request.frozen_observation_sha256,
                request.breach_class,
                transition_at_ms,
                artifact.path.to_string_lossy(),
                artifact.sha256,
                i64::try_from(healthy_tail.len()).unwrap_or(i64::MAX),
                healthy_window_ms,
                i64::try_from(flap_multiplier).unwrap_or(i64::MAX),
            ],
        )?;
        let changed = tx.execute(
            "UPDATE resource_guard_state SET admission_state='open',reason=NULL,observed_at_ms=?1,oracle_evidence_required=0,observation_json=?2 WHERE singleton=1 AND admission_state='frozen' AND reason=?3 AND observed_at_ms=?4 AND observation_json=?5",
            params![
                newest_healthy_at_ms,
                newest_healthy_json,
                request.breach_class,
                freeze_at_ms,
                frozen_observation_json,
            ],
        )?;
        if changed != 1 {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "resource guard re-arm live frozen state changed before transition commit"
                    .into(),
            });
        }
        tx.commit()?;
        Ok(artifact)
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

    pub fn register_artifact(
        &self,
        sha256_hex: &str,
        byte_count: i64,
        media_type: &str,
        locations: &[data_catalog::ArtifactLocationInput],
    ) -> Result<data_catalog::RegisterArtifactOutcome> {
        let mut conn = self.conn()?;
        data_catalog::register_artifact(
            &mut conn,
            sha256_hex,
            byte_count,
            media_type,
            locations,
            now_ms(),
        )
    }

    pub fn retire_artifact_location(
        &self,
        sha256_hex: &str,
        volume: &str,
        locator: &str,
        reason: &str,
    ) -> Result<()> {
        let mut conn = self.conn()?;
        data_catalog::retire_artifact_location(
            &mut conn,
            sha256_hex,
            volume,
            locator,
            now_ms(),
            reason,
        )
    }

    pub fn custody_verify(
        &self,
        hashes: &[String],
        roots: &BTreeMap<String, PathBuf>,
        rehash: bool,
    ) -> Result<Value> {
        let conn = self.conn()?;
        data_catalog::custody_verify(&conn, hashes, roots, rehash, now_ms())
    }

    fn admission_guard_statuses(&self) -> Result<(Value, Value)> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let resource_guard = resource_guard_status_from_connection(&tx)?;
        let foreign_process_pressure = foreign_process_pressure_status_from_connection(&tx)?;
        tx.commit()?;
        Ok((resource_guard, foreign_process_pressure))
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
        self.dispatch_manifest_bytes_at_with_vram_observation_and_host(
            manifest_bytes,
            expected_sha256,
            now_ms(),
            available_free_bytes,
            available_vram_observation,
            probe_host_commit_capacity,
        )
    }
    pub fn dispatch_manifest(&self, manifest_path: &Path) -> Result<DispatchOutcome> {
        let manifest_bytes = fs::read(manifest_path)?;
        let manifest: DispatchManifest =
            serde_json::from_slice(&manifest_bytes).map_err(|error| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!("dispatch manifest schema is invalid: {error}"),
                }
            })?;
        if matches!(
            manifest.schema_version.as_str(),
            "ember-lab-dispatch-manifest-v4" | "ember-lab-dispatch-manifest-v5"
        ) {
            self.dispatch_manifest_v4_at_with_device_probe_and_host(
                manifest_path,
                now_ms(),
                available_free_bytes,
                probe_vram_device_capacity,
                probe_host_commit_capacity,
            )
        } else {
            self.dispatch_manifest_at_with_probes(
                manifest_path,
                now_ms(),
                available_free_bytes,
                available_free_vram_bytes,
            )
        }
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
        self.dispatch_manifest_at_with_probes_and_host_and_window_census_budget(
            manifest_path,
            observed_at_ms,
            free_space,
            free_vram,
            free_host_commit,
            DEFAULT_WINDOW_CENSUS_BUDGET,
        )
    }

    /// Same as `dispatch_manifest_at_with_probes_and_host`, with the
    /// window-contract census budget also injectable. Production callers
    /// use the plain method above (fixed at `DEFAULT_WINDOW_CENSUS_BUDGET`);
    /// this variant exists so a test can widen the budget to verify the
    /// refusal MECHANISM (enriched hwnd/pid/title detail, receipt shape)
    /// without racing the fixed production timing under host load.
    pub fn dispatch_manifest_at_with_probes_and_host_and_window_census_budget<F, G, H>(
        &self,
        manifest_path: &Path,
        observed_at_ms: i64,
        free_space: F,
        mut free_vram: G,
        free_host_commit: H,
        window_census_budget: Duration,
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
            DispatchProbes {
                free_space,
                free_vram: move |_| free_vram(),
                free_host_commit,
                window_census_budget,
            },
        )
    }

    pub fn dispatch_manifest_v4_at_with_device_probe_and_host<F, G, H>(
        &self,
        manifest_path: &Path,
        observed_at_ms: i64,
        free_space: F,
        mut device_vram: G,
        free_host_commit: H,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut(&VramWallContract) -> Result<VramDeviceCapacity>,
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
            DispatchProbes {
                free_space,
                free_vram: move |contract: Option<VramWallContract>| {
                    let contract =
                        contract.ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                            detail: "device probe requires a v4 VRAM wall contract".into(),
                        })?;
                    device_vram(&contract)
                },
                free_host_commit,
                window_census_budget: DEFAULT_WINDOW_CENSUS_BUDGET,
            },
        )
    }

    pub fn dispatch_manifest_bytes_at_with_probes_and_host<F, G, H>(
        &self,
        manifest_bytes: &[u8],
        expected_sha256: &str,
        observed_at_ms: i64,
        free_space: F,
        mut free_vram: G,
        free_host_commit: H,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut() -> Result<u64>,
        H: FnMut() -> Result<HostCommitCapacity>,
    {
        self.dispatch_manifest_bytes_at_with_vram_observation_and_host(
            manifest_bytes,
            expected_sha256,
            observed_at_ms,
            free_space,
            move |_| free_vram(),
            free_host_commit,
        )
    }

    fn dispatch_manifest_bytes_at_with_vram_observation_and_host<F, G, H, T>(
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
        G: FnMut(Option<VramWallContract>) -> Result<T>,
        T: Into<DispatchVramObservation>,
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
                    detail: format!(
                        "dispatch manifest schema is invalid: {}",
                        describe_dispatch_manifest_parse_error(manifest_bytes, &error)
                    ),
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
                DispatchProbes {
                    free_space,
                    free_vram,
                    free_host_commit,
                    window_census_budget: DEFAULT_WINDOW_CENSUS_BUDGET,
                },
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
            DispatchProbes {
                free_space,
                free_vram,
                free_host_commit,
                window_census_budget: DEFAULT_WINDOW_CENSUS_BUDGET,
            },
        )
    }

    fn validate_dispatch_manifest_snapshot_preconditions(
        &self,
        manifest: &DispatchManifest,
    ) -> Result<()> {
        let vram_declaration_valid = match manifest.schema_version.as_str() {
            "ember-lab-dispatch-manifest-v3" => {
                manifest.vram_wall.is_none()
                    && (manifest.workload_profile.profile_id
                        == DispatchWorkloadProfileId::EvidenceVerifier
                        || manifest.minimum_free_vram_bytes > 0)
            }
            "ember-lab-dispatch-manifest-v4" | "ember-lab-dispatch-manifest-v5" => {
                if manifest.minimum_free_vram_bytes != 0 {
                    false
                } else {
                    match (
                        manifest.workload_profile.profile_id,
                        manifest.vram_wall.as_ref(),
                    ) {
                        (
                            DispatchWorkloadProfileId::EvidenceVerifier,
                            Some(DispatchVramWall::NotApplicable),
                        ) => true,
                        (
                            DispatchWorkloadProfileId::EvidenceVerifier,
                            Some(DispatchVramWall::Required(_)) | None,
                        ) => false,
                        (_, Some(DispatchVramWall::Required(contract))) => {
                            validate_vram_wall_contract(contract).is_ok()
                        }
                        (_, Some(DispatchVramWall::NotApplicable) | None) => false,
                    }
                }
            }
            _ => false,
        };
        let disk_declaration_valid = match manifest.schema_version.as_str() {
            "ember-lab-dispatch-manifest-v3" | "ember-lab-dispatch-manifest-v4" => {
                manifest.disk_write_walls.is_empty()
            }
            "ember-lab-dispatch-manifest-v5" => {
                !manifest.disk_write_walls.is_empty()
                    && manifest
                        .disk_write_walls
                        .iter()
                        .all(|contract| validate_disk_write_wall_contract(contract).is_ok())
                    && manifest
                        .disk_write_walls
                        .iter()
                        .try_fold(0_u64, |total, contract| {
                            total.checked_add(contract.maximum_measurement_duration_ms)
                        })
                        .is_some_and(|total| total <= DISK_WALL_SAMPLE_INTERVAL_MS / 2)
            }
            _ => false,
        };
        if !vram_declaration_valid
            || !disk_declaration_valid
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
            || manifest.required_available_maximum_commit_bytes == 0
            || manifest.maximum_job_memory_bytes == 0
            || manifest.simulated_peak_commit_bytes == 0
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch manifest requires the closed v3/v4/v5 schema, workload profile, identities, window, bindings, reserves, and explicit resource declarations".into(),
            });
        }
        if manifest.env.contains_key(DISPATCH_TOKEN_ENV)
            || manifest.env.contains_key(DISPATCH_JOB_ID_ENV)
            || manifest.env.contains_key(DISPATCH_DAEMON_PID_ENV)
            || manifest.env.contains_key(DISPATCH_MAXIMUM_JOB_MEMORY_ENV)
            || manifest.env.contains_key(DISPATCH_VRAM_PROVIDER_ENV)
            || manifest.env.contains_key(DISPATCH_VRAM_DEVICE_UUID_ENV)
            || manifest.env.contains_key(DISPATCH_VRAM_FRACTION_ENV)
            || manifest.env.contains_key(DISPATCH_MAXIMUM_PROCESS_VRAM_ENV)
            || manifest.env.contains_key(DISPATCH_MINIMUM_FREE_VRAM_ENV)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "dispatch token environment is daemon-owned".into(),
            });
        }
        validate_dispatch_workload_profile(
            &manifest.workload_profile,
            manifest.cpu_pacing_class,
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
    fn dispatch_manifest_bytes_at_with_probes_and_host_inner<F, G, H, T>(
        &self,
        manifest_bytes: &[u8],
        manifest_identity_path: &Path,
        observed_at_ms: i64,
        probes: DispatchProbes<F, G, H>,
    ) -> Result<DispatchOutcome>
    where
        F: FnMut(&Path) -> Result<u64>,
        G: FnMut(Option<VramWallContract>) -> Result<T>,
        T: Into<DispatchVramObservation>,
        H: FnMut() -> Result<HostCommitCapacity>,
    {
        let DispatchProbes {
            mut free_space,
            mut free_vram,
            mut free_host_commit,
            window_census_budget,
        } = probes;
        let manifest_path = fs::canonicalize(manifest_identity_path).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("dispatch manifest identity snapshot is unavailable: {error}"),
            }
        })?;
        let manifest: DispatchManifest =
            serde_json::from_slice(manifest_bytes).map_err(|error| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!(
                        "dispatch manifest schema is invalid: {}",
                        describe_dispatch_manifest_parse_error(manifest_bytes, &error)
                    ),
                }
            })?;
        self.validate_dispatch_manifest_snapshot_preconditions(&manifest)?;
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

        let mut disk_wall_bindings = Vec::new();
        let mut disk_wall_receipts = Vec::new();
        if manifest.schema_version == "ember-lab-dispatch-manifest-v5" {
            let mut canonical_write_roots = Vec::<PathBuf>::new();
            let mut volume_free = BTreeMap::<PathBuf, u64>::new();
            let mut aggregate_measurement_duration_ms = 0_u64;
            let aggregate_declared_maximum_duration_ms = manifest
                .disk_write_walls
                .iter()
                .try_fold(0_u64, |total, wall| {
                    total.checked_add(wall.maximum_measurement_duration_ms)
                })
                .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                    detail: "disk write wall aggregate declared duration overflowed".into(),
                })?;
            for declared in &manifest.disk_write_walls {
                let canonical_volume_root =
                    fs::canonicalize(&declared.volume_root).map_err(|error| {
                        EmberLabError::InvalidDispatchManifest {
                            detail: format!(
                                "disk write wall volume root is unavailable at admission: {error}"
                            ),
                        }
                    })?;
                let canonical_write_root =
                    fs::canonicalize(&declared.write_root).map_err(|error| {
                        EmberLabError::InvalidDispatchManifest {
                            detail: format!(
                                "disk write wall named root must exist at admission: {error}"
                            ),
                        }
                    })?;
                if canonical_write_roots.iter().any(|existing| {
                    canonical_write_root.starts_with(existing)
                        || existing.starts_with(&canonical_write_root)
                }) {
                    return Err(EmberLabError::InvalidDispatchManifest {
                        detail: "disk write wall named roots must be pairwise non-overlapping"
                            .into(),
                    });
                }
                canonical_write_roots.push(canonical_write_root.clone());
                let available_free_bytes =
                    if let Some(value) = volume_free.get(&canonical_volume_root) {
                        *value
                    } else {
                        let value = free_space(&canonical_volume_root)?;
                        volume_free.insert(canonical_volume_root.clone(), value);
                        value
                    };
                let canonical_contract = DiskWriteWallContract {
                    volume_root: canonical_volume_root.clone(),
                    write_root: canonical_write_root.clone(),
                    maximum_write_bytes: declared.maximum_write_bytes,
                    minimum_free_bytes: declared.minimum_free_bytes,
                    sample_interval_ms: declared.sample_interval_ms,
                    maximum_measurement_duration_ms: declared.maximum_measurement_duration_ms,
                };
                let mut baseline = measure_disk_write_wall_sample_with_available_free(
                    &canonical_contract,
                    0,
                    observed_at_ms,
                    available_free_bytes,
                )?;
                baseline.baseline_tree_bytes = baseline.current_tree_bytes;
                if let DiskWallDecision::ProtectiveStop {
                    breach_class: DiskWallBreachClass::VolumeFreeFloor,
                    ..
                } = evaluate_disk_write_wall(&canonical_contract, &baseline)?
                {
                    return Err(EmberLabError::DispatchStorageReserve {
                        root: canonical_volume_root,
                        minimum_free_bytes: canonical_contract.minimum_free_bytes,
                        available_free_bytes,
                    });
                }
                aggregate_measurement_duration_ms = aggregate_measurement_duration_ms
                    .checked_add(baseline.measurement_duration_ms)
                    .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                        detail: "disk write wall aggregate measurement duration overflowed".into(),
                    })?;
                disk_wall_receipts.push(json!({
                    "volume_root":canonical_contract.volume_root,
                    "write_root":canonical_contract.write_root,
                    "baseline_tree_bytes":baseline.baseline_tree_bytes,
                    "maximum_write_bytes":canonical_contract.maximum_write_bytes,
                    "minimum_free_bytes":canonical_contract.minimum_free_bytes,
                    "available_free_bytes":available_free_bytes,
                    "measurement_duration_ms":baseline.measurement_duration_ms,
                    "maximum_measurement_duration_ms":canonical_contract.maximum_measurement_duration_ms,
                    "sample_interval_ms":canonical_contract.sample_interval_ms,
                    "claim_boundary":"immutable_named_root_growth_plus_per_volume_survival_floor_not_os_wide_write_quota",
                }));
                disk_wall_bindings.push(BoundDiskWriteWall {
                    contract: canonical_contract,
                    baseline_tree_bytes: baseline.baseline_tree_bytes,
                });
            }
            disk_wall_receipts.push(json!({
                "aggregate_measurement_duration_ms":aggregate_measurement_duration_ms,
                "aggregate_declared_maximum_duration_ms":aggregate_declared_maximum_duration_ms,
                "maximum_aggregate_duration_ms":DISK_WALL_SAMPLE_INTERVAL_MS / 2,
                "per_volume_floor_observations":volume_free,
            }));
        }

        let (vram_receipt, maximum_process_vram_bytes) = match (
            manifest.schema_version.as_str(),
            manifest.vram_wall.as_ref(),
        ) {
            (
                "ember-lab-dispatch-manifest-v4" | "ember-lab-dispatch-manifest-v5",
                Some(DispatchVramWall::NotApplicable),
            ) => (json!({"applicability":"not_applicable"}), None),
            (
                "ember-lab-dispatch-manifest-v4" | "ember-lab-dispatch-manifest-v5",
                Some(DispatchVramWall::Required(contract)),
            ) => {
                let observation: DispatchVramObservation =
                    free_vram(Some(contract.clone()))?.into();
                let DispatchVramObservation::Device(capacity) = observation else {
                    return Err(EmberLabError::InvalidDispatchManifest {
                        detail: "v4 VRAM wall requires a provider/UUID-bound device probe".into(),
                    });
                };
                if capacity.provider != contract.provider
                    || capacity.device_uuid != contract.device_uuid
                    || capacity.total_bytes == 0
                    || capacity.free_bytes > capacity.total_bytes
                {
                    return Err(EmberLabError::InvalidDispatchManifest {
                        detail: "v4 VRAM wall device provider/UUID/capacity mismatch".into(),
                    });
                }
                if capacity.free_bytes < contract.minimum_free_bytes {
                    return Err(EmberLabError::DispatchVramReserve {
                        minimum_free_bytes: contract.minimum_free_bytes,
                        available_free_bytes: capacity.free_bytes,
                    });
                }
                let maximum_process_bytes = capacity
                    .total_bytes
                    .checked_mul(contract.maximum_process_fraction_millionths as u64)
                    .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                        detail: "v4 VRAM wall fraction derivation overflowed".into(),
                    })?
                    / 1_000_000;
                (
                    json!({
                        "applicability":"required",
                        "claim_boundary":"torch_allocator_fraction_plus_load_bearing_external_sentinel_not_total_vram_guarantee",
                        "provider":capacity.provider,
                        "device_uuid":capacity.device_uuid,
                        "total_bytes":capacity.total_bytes,
                        "available_free_bytes":capacity.free_bytes,
                        "minimum_free_bytes":contract.minimum_free_bytes,
                        "maximum_process_fraction_millionths":contract.maximum_process_fraction_millionths,
                        "maximum_process_vram_bytes":maximum_process_bytes,
                        "consecutive_breach_samples":contract.consecutive_breach_samples,
                        "sample_interval_ms":contract.sample_interval_ms,
                    }),
                    Some(maximum_process_bytes),
                )
            }
            ("ember-lab-dispatch-manifest-v3", None) => {
                let available_vram = if manifest.workload_profile.profile_id
                    == DispatchWorkloadProfileId::EvidenceVerifier
                    && manifest.minimum_free_vram_bytes == 0
                {
                    0
                } else {
                    match free_vram(None)?.into() {
                        DispatchVramObservation::LegacyFreeBytes(value) => value,
                        DispatchVramObservation::Device(capacity) => capacity.free_bytes,
                    }
                };
                if available_vram < manifest.minimum_free_vram_bytes {
                    return Err(EmberLabError::DispatchVramReserve {
                        minimum_free_bytes: manifest.minimum_free_vram_bytes,
                        available_free_bytes: available_vram,
                    });
                }
                (
                    json!({
                        "minimum_free_bytes":manifest.minimum_free_vram_bytes,
                        "available_free_bytes":available_vram,
                    }),
                    None,
                )
            }
            _ => {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "dispatch VRAM declaration does not match its schema".into(),
                })
            }
        };

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
            "vram_reserve": vram_receipt,
            "disk_write_walls": disk_wall_receipts,
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
        let (resource_guard, foreign_process_pressure) = self.admission_guard_statuses()?;
        let foreign_pressure_state = foreign_process_pressure
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("probe_failed");
        if cfg!(windows) && matches!(foreign_pressure_state, "fenced" | "probe_failed") {
            let reason = if foreign_pressure_state == "probe_failed" {
                "foreign_process_host_counter_unavailable".to_string()
            } else {
                "foreign_process_host_commit_below_survival_floor".to_string()
            };
            let refusal = json!({
                "schema_version": "ember-lab-dispatch-preflight-v1",
                "result": "REFUSED_FOREIGN_PROCESS_PRESSURE",
                "job_id": &manifest.job_id,
                "source_commit": &manifest.source_commit,
                "observed_at_ms": observed_at_ms,
                "dispatch_manifest_sha256": hash_bytes(manifest_bytes),
                "resource_guard": resource_guard,
                "foreign_process_pressure": foreign_process_pressure,
            });
            atomic_replace(&receipt_path, &serde_json::to_vec(&refusal)?)?;
            return Err(EmberLabError::ResourceAdmissionFrozen {
                reason,
                receipt_path,
            });
        }
        if resource_guard.get("admission_state") == Some(&Value::String("frozen".into())) {
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
                "foreign_process_pressure": foreign_process_pressure,
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
        .with_simulated_peak_commit_bytes(manifest.simulated_peak_commit_bytes)
        .with_cpu_rate_percent(manifest.workload_profile.cpu_rate_percent)
        .with_cpu_pacing_class(manifest.cpu_pacing_class)
        .with_requires_ui_responsiveness(manifest.workload_profile.requires_ui_responsiveness)
        .with_window_contract(manifest.window_contract);
        if let (Some(DispatchVramWall::Required(contract)), Some(maximum_process_bytes)) =
            (manifest.vram_wall, maximum_process_vram_bytes)
        {
            spec = spec.with_vram_wall(contract, maximum_process_bytes);
        }
        spec = spec.with_disk_write_walls(disk_wall_bindings);
        for (key, value) in manifest.env {
            spec = spec.with_env(key, value);
        }
        if profile_id == DispatchWorkloadProfileId::EvidenceVerifier || spec.vram_wall.is_some() {
            spec = spec.with_dispatch_token(dispatch_expires_at_ms)?;
        }
        let handle = match self.start_job_with_window_census_budget(spec, window_census_budget) {
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
            tx.execute(
                "DELETE FROM vram_wall_observations WHERE job_id=?1",
                [job_id],
            )?;
            tx.execute("DELETE FROM job_vram_walls WHERE job_id=?1", [job_id])?;
            tx.execute(
                "DELETE FROM disk_wall_observations WHERE job_id=?1",
                [job_id],
            )?;
            tx.execute("DELETE FROM job_disk_walls WHERE job_id=?1", [job_id])?;
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
    pub fn start_job(&self, spec: JobSpec) -> Result<JobHandle> {
        self.start_job_with_window_census_budget(spec, DEFAULT_WINDOW_CENSUS_BUDGET)
    }

    /// Same as `start_job`, with the window-contract census budget also
    /// injectable. Production callers use `start_job` (fixed at
    /// `DEFAULT_WINDOW_CENSUS_BUDGET`); the dispatch-manifest path and tests
    /// that need to distinguish a real refusal from a scheduler-timing race
    /// under host load use this directly.
    pub fn start_job_with_window_census_budget(
        &self,
        mut spec: JobSpec,
        window_census_budget: Duration,
    ) -> Result<JobHandle> {
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
        if let Some(contract) = spec.vram_wall.as_ref() {
            if [
                DISPATCH_VRAM_PROVIDER_ENV,
                DISPATCH_VRAM_DEVICE_UUID_ENV,
                DISPATCH_VRAM_FRACTION_ENV,
                DISPATCH_MAXIMUM_PROCESS_VRAM_ENV,
                DISPATCH_MINIMUM_FREE_VRAM_ENV,
            ]
            .iter()
            .any(|key| spec.env.contains_key(*key))
            {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "VRAM wall environment is daemon-owned".into(),
                });
            }
            let maximum_process_bytes = spec.maximum_process_vram_bytes.ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "VRAM wall lacks its derived process byte cap".into(),
                }
            })?;
            spec.env
                .insert(DISPATCH_VRAM_PROVIDER_ENV.into(), contract.provider.clone());
            spec.env.insert(
                DISPATCH_VRAM_DEVICE_UUID_ENV.into(),
                contract.device_uuid.clone(),
            );
            spec.env.insert(
                DISPATCH_VRAM_FRACTION_ENV.into(),
                contract.maximum_process_fraction_millionths.to_string(),
            );
            spec.env.insert(
                DISPATCH_MAXIMUM_PROCESS_VRAM_ENV.into(),
                maximum_process_bytes.to_string(),
            );
            spec.env.insert(
                DISPATCH_MINIMUM_FREE_VRAM_ENV.into(),
                contract.minimum_free_bytes.to_string(),
            );
        }
        if spec.dispatch_token.is_some() {
            if spec.env.contains_key(DISPATCH_MAXIMUM_JOB_MEMORY_ENV) {
                return Err(EmberLabError::InvalidDispatchManifest {
                    detail: "maximum job memory environment is daemon-owned".into(),
                });
            }
            let maximum_job_memory_bytes = spec.maximum_job_memory_bytes.ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "token-gated dispatch requires maximum job memory".into(),
                }
            })?;
            spec.env.insert(
                DISPATCH_MAXIMUM_JOB_MEMORY_ENV.into(),
                maximum_job_memory_bytes.to_string(),
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
            if let (Some(contract), Some(maximum_process_bytes)) =
                (spec.vram_wall.as_ref(), spec.maximum_process_vram_bytes)
            {
                let maximum_process_bytes = i64::try_from(maximum_process_bytes).map_err(|_| {
                    EmberLabError::InvalidDispatchManifest {
                        detail: "VRAM wall byte cap exceeds the durable integer range".into(),
                    }
                })?;
                tx.execute(
                    "INSERT INTO job_vram_walls(job_id,contract_json,maximum_process_vram_bytes) VALUES(?1,?2,?3)",
                    params![spec.job_id, serde_json::to_string(contract)?, maximum_process_bytes],
                )?;
            }
            for wall in &spec.disk_write_walls {
                let baseline_tree_bytes =
                    i64::try_from(wall.baseline_tree_bytes).map_err(|_| {
                        EmberLabError::InvalidDispatchManifest {
                            detail: "disk write wall baseline exceeds the durable integer range"
                                .into(),
                        }
                    })?;
                tx.execute(
                    "INSERT INTO job_disk_walls(job_id,write_root,contract_json,baseline_tree_bytes) VALUES(?1,?2,?3,?4)",
                    params![
                        spec.job_id,
                        wall.contract.write_root.to_string_lossy(),
                        serde_json::to_string(&wall.contract)?,
                        baseline_tree_bytes,
                    ],
                )?;
            }
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_start_reserved',?3)",
                params![spec.job_id, now_ms(), json!({"job_object_name":job_object_name,"cpu_rate_percent":spec.cpu_rate_percent,"requires_ui_responsiveness":spec.requires_ui_responsiveness,"vram_wall":spec.vram_wall,"maximum_process_vram_bytes":spec.maximum_process_vram_bytes,"disk_write_walls":spec.disk_write_walls.iter().map(|wall| json!({"contract":wall.contract,"baseline_tree_bytes":wall.baseline_tree_bytes})).collect::<Vec<_>>()}).to_string()],
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
        let applied_cpu_rate = spawned.applied_cpu_rate();
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
                params![spec.job_id, now_ms(), json!({"pid":pid,"job_object_name":job_object_name,"cpu_rate_percent":spec.cpu_rate_percent,"requires_ui_responsiveness":spec.requires_ui_responsiveness,"cpu_pacing_class":spec.cpu_pacing_class,"cpu_rate_control_verified":applied_cpu_rate.is_some(),"applied_cpu_rate":applied_cpu_rate}).to_string()],
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
            // Window contract (issue #898 L6): the process is still suspended
            // here, so it cannot have created a window yet -- this is a true
            // baseline regardless of exactly when it is sampled relative to
            // other work in this closure.
            #[cfg(windows)]
            let pre_resume_windows = census_top_level_windows();
            spawned.resume()?;
            #[cfg(windows)]
            if spec.window_contract == DispatchWindowContract::HeadlessNoWindows {
                let violating_windows = poll_for_new_job_owned_windows(
                    &pre_resume_windows,
                    spawned.job_handle(),
                    window_census_budget,
                    Duration::from_millis(20),
                );
                if !violating_windows.is_empty() {
                    let windows_detail = violating_windows
                        .iter()
                        .map(ViolatingWindow::to_string)
                        .collect::<Vec<_>>()
                        .join("; ");
                    return Err(EmberLabError::WindowContractViolation {
                        job_id: spec.job_id.clone(),
                        detail: format!(
                            "headless_no_windows spawn presented {} visible window(s) outside the cockpit contract: {windows_detail}",
                            violating_windows.len()
                        ),
                    });
                }
            }
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
            let failure_kind = if matches!(error, EmberLabError::WindowContractViolation { .. }) {
                "job_window_contract_violation"
            } else {
                "job_launch_commit_failed"
            };
            let _ = self.mark_failed(&spec.job_id, failure_kind);
            return Err(error);
        }
        let lease_epoch = self.job_process_row(&spec.job_id)?.lease_epoch;
        #[cfg(windows)]
        self.retain_and_monitor(&spec.job_id, lease_epoch, spawned.into_live())?;
        #[cfg(not(windows))]
        spawned.detach_reaper(Arc::downgrade(&self.db), spec.job_id.clone(), lease_epoch);
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

    #[cfg(windows)]
    fn retained_live_observation(
        &self,
        job_id: &str,
    ) -> Result<Option<(u32, ProcessIdentity, bool)>> {
        let retained = self.live.lock().map_err(|_| EmberLabError::Poisoned)?;
        Ok(retained.get(job_id).map(|retained| {
            (
                retained.live.pid,
                retained.live.identity.clone(),
                live_process_is_running(&retained.live),
            )
        }))
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
        {
            let (observed_identity, process_running) = match self
                .retained_live_observation(job_id)
                .map_err(|_| EmberLabError::DispatchTokenRefused {
                    job_id: job_id.into(),
                })? {
                Some((pid, identity, running)) if pid == client_pid => (identity, running),
                Some(_) => {
                    return Err(EmberLabError::DispatchTokenRefused {
                        job_id: job_id.into(),
                    });
                }
                None => match open_live_status(&row) {
                    LiveStatus::Verified(live) => {
                        let running = live_process_is_running(&live);
                        (live.identity.clone(), running)
                    }
                    LiveStatus::Dead
                    | LiveStatus::Orphaned(_)
                    | LiveStatus::IdentityConflict(_) => {
                        return Err(EmberLabError::DispatchTokenRefused {
                            job_id: job_id.into(),
                        });
                    }
                },
            };
            let mut conn = self.conn()?;
            consume_dispatch_token_transaction(
                &mut conn,
                job_id,
                token,
                client_pid,
                &observed_identity,
                || Ok(process_running),
            )
        }
        #[cfg(not(windows))]
        {
            let mut conn = self.conn()?;
            consume_dispatch_token_with_process_observer(
                &mut conn,
                job_id,
                token,
                client_pid,
                inspect_process,
            )
        }
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

    pub fn job_result(&self, job_id: &str) -> Result<(i64, String)> {
        let row: (String, Option<i64>, String, Option<String>) = self
            .conn()?
            .query_row(
                "SELECT state,exit_code,stderr_log_path,stderr_log_sha256 FROM jobs WHERE job_id=?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?
            .ok_or_else(|| EmberLabError::JobNotFound {
                job_id: job_id.into(),
            })?;
        let state = JobState::parse(&row.0)?;
        if !matches!(
            state,
            JobState::Stopped | JobState::Exited | JobState::Failed
        ) {
            return Err(EmberLabError::NonTerminalReceipt {
                job_id: job_id.into(),
                state: state.as_str().into(),
            });
        }
        let exit_code = row.1.ok_or_else(|| EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "terminal certified launch lacks an exit code".into(),
        })?;
        let expected_stderr_sha256 = row.3.ok_or_else(|| EmberLabError::LogEvidenceUnsealed {
            job_id: job_id.into(),
        })?;
        let stderr_path = PathBuf::from(row.2);
        let stderr_bytes = fs::read(&stderr_path)?;
        let actual_stderr_sha256 = hash_bytes(&stderr_bytes);
        if actual_stderr_sha256 != expected_stderr_sha256 {
            return Err(EmberLabError::LogEvidenceMismatch {
                job_id: job_id.into(),
                stream: "stderr".into(),
                expected: expected_stderr_sha256,
                actual: actual_stderr_sha256,
            });
        }
        let stderr =
            String::from_utf8(stderr_bytes).map_err(|_| EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "terminal certified launch stderr is not UTF-8".into(),
            })?;
        Ok((exit_code, stderr))
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
        if let Some((pid, identity, running)) = self.retained_live_observation(job_id)? {
            if pid != row.pid
                || identity.start_token != row.start_token
                || !same_executable(&identity.executable, &row.executable)
            {
                return Err(EmberLabError::ProcessIdentityMismatch {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
            if !running {
                return Err(EmberLabError::ProcessUnavailable {
                    job_id: job_id.into(),
                    pid: row.pid,
                });
            }
            self.commit_adoption(job_id, &row)?;
            return Ok(JobHandle { pid: row.pid });
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
        self.retain_and_monitor(job_id, row.lease_epoch, live)?;
        Ok(JobHandle { pid: row.pid })
    }

    pub fn stop_job(&self, job_id: &str) -> Result<()> {
        let row = self.job_process_row(job_id)?;
        if matches!(row.state, JobState::Stopped | JobState::Exited) {
            #[cfg(windows)]
            self.live
                .lock()
                .map_err(|_| EmberLabError::Poisoned)?
                .remove(job_id);
            return Ok(());
        }
        if !matches!(row.state, JobState::Running | JobState::Stopping) {
            return Err(EmberLabError::InvalidTransition {
                job_id: job_id.into(),
                detail: "only running or stopping jobs can be stopped".into(),
            });
        }
        #[cfg(windows)]
        let retained = self
            .live
            .lock()
            .map_err(|_| EmberLabError::Poisoned)?
            .remove(job_id);
        #[cfg(windows)]
        let (live, memory_barrier) = match retained {
            Some(retained) => (LiveStatus::Verified(retained.live), retained.memory_barrier),
            None => (open_live_status(&row), None),
        };
        #[cfg(windows)]
        let live = match live {
            LiveStatus::Verified(live) => live,
            LiveStatus::Dead if row.state == JobState::Stopping => {
                self.finalize_stopped(job_id, &row, false)?;
                return Ok(());
            }
            LiveStatus::Dead => {
                if let Err(error) = self.mark_exited_unknown(job_id, &row, "job_exited_before_stop")
                {
                    let conn = self.conn()?;
                    if matches!(
                        process_state_at_fence(&conn, job_id, row.pid, row.lease_epoch)?,
                        Some(JobState::Stopped | JobState::Exited)
                    ) {
                        return Ok(());
                    }
                    return Err(error);
                }
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
                    match process_state_at_fence(&tx, job_id, row.pid, row.lease_epoch)? {
                        Some(JobState::Stopping) => {}
                        Some(JobState::Stopped | JobState::Exited) => return Ok(()),
                        _ => {
                            return Err(EmberLabError::InvalidTransition {
                                job_id: job_id.into(),
                                detail: "stop lost its state or lease fence".into(),
                            });
                        }
                    }
                } else {
                    tx.execute("INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_stop_requested',?3)", params![job_id, now_ms(), json!({"pid":row.pid}).to_string()])?;
                }
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
                        memory_barrier,
                    },
                );
            return Err(error);
        }
        #[cfg(windows)]
        if let Some(memory_barrier) = memory_barrier {
            use windows_sys::Win32::System::IO::PostQueuedCompletionStatus;
            if unsafe {
                PostQueuedCompletionStatus(
                    live.completion_port.raw(),
                    0,
                    JOB_TERMINAL_COMPLETION_KEY,
                    std::ptr::null(),
                )
            } == 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
            memory_barrier.wait()?;
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
    fn retain_and_monitor(&self, job_id: &str, lease_epoch: i64, live: LiveProcess) -> Result<()> {
        if self
            .live
            .lock()
            .map_err(|_| EmberLabError::Poisoned)?
            .get(job_id)
            .is_some_and(|existing| existing.monitored)
        {
            return Ok(());
        }
        let registration = (|| -> Result<JobMonitorHandles> {
            Ok(JobMonitorHandles {
                waiter: duplicate_owned_handle(live.process.raw())?,
                shutdown: duplicate_owned_handle(self.monitor_shutdown.raw())?,
                observer_job: duplicate_owned_handle(live.job.raw())?,
                observer_process: duplicate_owned_handle(live.process.raw())?,
                observer_port: duplicate_owned_handle(live.completion_port.raw())?,
                terminal_job: duplicate_owned_handle(live.job.raw())?,
                terminal_process: duplicate_owned_handle(live.process.raw())?,
                terminal_port: duplicate_owned_handle(live.completion_port.raw())?,
            })
        })();
        let handles = match registration {
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
                                    memory_barrier: None,
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
        let memory_barrier = match spawn_job_memory_observer(JobMemoryObserverRegistration {
            db: Arc::downgrade(&self.db),
            job_id: job_id.into(),
            root_pid: pid,
            job: handles.observer_job,
            process: handles.observer_process,
            completion_port: handles.observer_port,
            expected_identity: live.identity.clone(),
            contract: live.job_memory_contract,
        }) {
            Ok(receiver) => receiver,
            Err(setup_error) => {
                let cleanup = terminate_live(&live)
                    .and_then(|_| self.mark_failed(job_id, "job_memory_observer_setup_failed"));
                return match cleanup {
                    Ok(()) => Err(setup_error.into()),
                    Err(cleanup_error) => Err(EmberLabError::MonitorSetupCleanupFailed {
                        job_id: job_id.into(),
                        setup: setup_error.to_string(),
                        cleanup: format!("{cleanup_error:?}"),
                    }),
                };
            }
        };
        let mut retained = self
            .live
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(existing) = retained.get_mut(job_id) {
            if existing.monitored {
                return Ok(());
            }
            existing.monitored = true;
            existing.memory_barrier = Some(Arc::clone(&memory_barrier));
            drop(retained);
        } else {
            retained.insert(
                job_id.into(),
                RetainedProcess {
                    live,
                    monitored: true,
                    memory_barrier: Some(Arc::clone(&memory_barrier)),
                },
            );
            drop(retained);
        }
        spawn_exit_monitor(ExitMonitorRegistration {
            db: Arc::downgrade(&self.db),
            retained: Arc::downgrade(&self.live),
            ownership: Arc::clone(&self.monitor_ownership),
            shutdown: handles.shutdown,
            job_id: job_id.into(),
            pid,
            lease_epoch,
            waiter: handles.waiter,
            terminal_job: handles.terminal_job,
            terminal_process: handles.terminal_process,
            terminal_port: handles.terminal_port,
            memory_barrier,
        });
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
            // `write_new`/`atomic_create` publish this file via a same-directory
            // temp-file + atomic rename/hard-link, so a reader never observes a
            // torn (partially-written) file. But a parse failure on freshly-read
            // bytes is still possible in principle (e.g. a future writer of this
            // path that doesn't go through that primitive) and, unlike a plain
            // `NotFound`, was previously treated as immediately terminal — the
            // real defect this loop fixes. Treat a parse failure the same as
            // `NotFound`: retry within the existing readiness deadline, and only
            // surface it as terminal once that deadline actually expires, citing
            // the last parse error alongside the expiry.
            let mut last_parse_error: Option<String> = None;
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
                        detail: match last_parse_error {
                            Some(parse_error) => format!(
                                "minimal-slice readiness deadline expired before completion (last parse error: {parse_error})"
                            ),
                            None => {
                                "minimal-slice readiness deadline expired before completion".into()
                            }
                        },
                    });
                }
                match fs::read(&completion_path) {
                    Ok(bytes) => match serde_json::from_slice::<Value>(&bytes) {
                        Ok(_) => break bytes,
                        Err(error) => {
                            last_parse_error = Some(error.to_string());
                            std::thread::sleep(Duration::from_millis(10));
                        }
                    },
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
        // Class-sweep note (does NOT need the completion.json loop's
        // retry-on-parse-failure treatment): the shared producer (rehearsal.rs)
        // always calls `write_new` on `host_peak.json` strictly before
        // `completion.json` in the same function, and `write_new` only returns
        // `Ok` after its own internal `sync_all()`/atomic-publish completes.
        // Program order therefore guarantees `host_peak.json` is already fully
        // durable by the time this reader has just finished successfully
        // reading+parsing `completion.json` above — there is no window in
        // which this read can observe a torn or malformed file.
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
        // Class-sweep note: `phase_artifact_digest` reads six files
        // (data_verify.json, train.json, checkpoint.json, publish.json,
        // selectable_checkpoint.json, restore.json) that the same producer
        // writes, in that fixed order, strictly before `host_peak.json` and
        // `completion.json` (rehearsal.rs). Reaching this call already proves
        // `completion.json` was durable, so by the same program-order argument
        // all six are durable too — no retry-on-parse-failure treatment needed
        // here either.
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
        // Class-sweep note (does NOT need retry-on-parse-failure treatment):
        // this function is only reachable once `host_peak.observed.json`
        // exists, which `execute_minimal_episode` only writes (via
        // `atomic_create`, same process) strictly after it already
        // successfully read AND parsed both `completion.json` and
        // `host_peak.json` earlier in that same call. Every marker/receipt
        // file this producer writes is create-new-only (`write_new`/
        // `atomic_create` both fail rather than overwrite an existing path),
        // so these two files are permanently immutable once durable — their
        // proven-valid state at that earlier point in time still holds now.
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
                        Ok(true) => self.retain_and_monitor(&job_id, row.lease_epoch, live)?,
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
                                            memory_barrier: None,
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
                    self.retain_and_monitor(&job_id, row.lease_epoch, live)?;
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
        if matches!(
            process_state_at_fence(&tx, job_id, row.pid, row.lease_epoch)?,
            Some(JobState::Stopped | JobState::Exited)
        ) {
            return Ok(());
        }
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

fn process_state_at_fence(
    conn: &Connection,
    job_id: &str,
    pid: u32,
    lease_epoch: i64,
) -> Result<Option<JobState>> {
    let state: Option<String> = conn
        .query_row(
            "SELECT state FROM jobs WHERE job_id=?1 AND pid=?2 AND lease_epoch=?3",
            params![job_id, pid, lease_epoch],
            |row| row.get(0),
        )
        .optional()?;
    state.map(|state| JobState::parse(&state)).transpose()
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
    cpu_pacing_class: DispatchCpuPacingClass,
    args: &[String],
    maximum_job_memory_bytes: u64,
    simulated_peak_commit_bytes: u64,
) -> Result<()> {
    if !(1..=100).contains(&profile.cpu_rate_percent) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "dispatch workload CPU rate must be between 1 and 100 percent".into(),
        });
    }
    // A `Governed` declaration asserts a pacing contract exists. At 100 percent
    // the hard cap admits the whole machine, so such a contract would pace
    // nothing while still earning a `cpu_rate_control_verified` receipt --
    // exactly the decorative-declaration problem this class was added to end.
    // `Unpaced` keeps the full 1..=100 range: it promises nothing, and the
    // host's blanket cap applies to it either way.
    if cpu_pacing_class == DispatchCpuPacingClass::Governed && profile.cpu_rate_percent == 100 {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "governed CPU pacing requires a cpu_rate_percent below 100".into(),
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
    let governed_vertical = args.iter().any(|arg| {
        arg == "governed-vertical"
            || Path::new(arg).file_name().and_then(|name| name.to_str())
                == Some("certified_train_launch.py")
    });
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

/// Linux/macOS disk-free probe via a `df` subprocess, not `statvfs` FFI --
/// no verified struct-layout crate exists for this and there is no tested
/// macOS CI job to catch a layout mismatch, so hand-rolled FFI here is a
/// real memory-safety risk for no benefit over shelling out to the
/// coreutils tool every admin already trusts for this exact question.
/// `--output=avail` prints only the single avail-blocks column (no
/// filesystem/device-name column to wrap), and `-B1` fixes the block size
/// at 1 byte so the printed value is already a byte count.
#[cfg(not(windows))]
fn available_free_bytes(root: &Path) -> Result<u64> {
    let output = std::process::Command::new("df")
        .args(["--output=avail", "-B1"])
        .arg(root)
        .output()
        .map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!("df disk-free probe failed to start: {error}"),
        })?;
    if !output.status.success() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!(
                "df disk-free probe failed with {}: {}",
                output.status,
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        });
    }
    let stdout = String::from_utf8(output.stdout).map_err(|error| {
        EmberLabError::InvalidDispatchManifest {
            detail: format!("df disk-free output was not UTF-8: {error}"),
        }
    })?;
    parse_df_avail_bytes(&stdout)
}

/// Parses `df --output=avail -B1`'s stdout: a header line (`"Avail"`)
/// followed by exactly one right-aligned byte-count value line. Split out
/// from `available_free_bytes` so the parsing logic is testable without a
/// real filesystem stat.
#[cfg(not(windows))]
fn parse_df_avail_bytes(stdout: &str) -> Result<u64> {
    let mut lines = stdout
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty());
    lines
        .next()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "df disk-free output was empty".into(),
        })?;
    let value_line = lines
        .next()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "df disk-free output was missing a value line after the header".into(),
        })?;
    if lines.next().is_some() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "df disk-free output had more lines than the expected header+value pair".into(),
        });
    }
    value_line
        .parse::<u64>()
        .map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!(
                "df disk-free value {value_line:?} was not a valid byte count: {error}"
            ),
        })
}

#[cfg(all(test, not(windows)))]
mod linux_available_free_bytes_tests {
    use super::*;

    /// Exercises the real probe against this test runner's actual root
    /// filesystem -- not a stub, not injected values. Prior to this fix,
    /// `available_free_bytes` always returned `Err(InvalidDispatchManifest)`
    /// on Linux, so this test could not exist; its mere presence and pass is
    /// direct evidence the probe now executes and returns a real number.
    #[test]
    fn available_free_bytes_reads_a_real_filesystem() {
        let bytes = available_free_bytes(Path::new("/"))
            .expect("available_free_bytes must succeed against a real filesystem on Linux CI");
        assert!(bytes > 0);
    }

    #[test]
    fn parse_df_avail_bytes_reads_the_header_and_value() {
        assert_eq!(
            parse_df_avail_bytes("     Avail\n1234567890\n").unwrap(),
            1_234_567_890
        );
    }

    #[test]
    fn parse_df_avail_bytes_tolerates_no_trailing_newline() {
        assert_eq!(parse_df_avail_bytes("Avail\n42").unwrap(), 42);
    }

    #[test]
    fn parse_df_avail_bytes_rejects_a_missing_value_line() {
        assert!(parse_df_avail_bytes("Avail\n").is_err());
        assert!(parse_df_avail_bytes("").is_err());
    }

    #[test]
    fn parse_df_avail_bytes_rejects_a_non_numeric_value() {
        assert!(parse_df_avail_bytes("Avail\nnot-a-number").is_err());
    }

    #[test]
    fn parse_df_avail_bytes_rejects_unexpected_extra_lines() {
        // Guards against a future df invocation regressing to a
        // filesystem/device-name column that wraps onto extra lines.
        assert!(parse_df_avail_bytes("Avail\n1234\nextra\n").is_err());
    }
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

/// Linux commit-capacity probe, read from `/proc/meminfo`. Field mapping
/// (`man proc_meminfo`): `MemAvailable` is the kernel's own load-aware
/// estimate of free-for-allocation memory and is used directly as
/// `physical_available_bytes` -- the same role `PhysicalAvailable` plays in
/// the Windows probe above. `CommitLimit` minus `Committed_AS` is the
/// kernel's own headroom-before-overcommit-limit figure and is used
/// directly as `current_commit_remaining_bytes` -- the same role
/// `CommitLimit - CommitTotal` plays on Windows. `SwapTotal` stands in for
/// Windows' pagefile maximum.
///
/// Unlike Windows, `CommitLimit` is not guaranteed to be `<=`
/// `MemTotal + SwapTotal` on Linux -- it is `SwapTotal + MemTotal *
/// (overcommit_ratio / 100)`, and an admin-configured `overcommit_ratio` over
/// 100 (or `overcommit_memory=1`, "always overcommit") can legitimately push
/// it higher. Windows' cross-invariant checks (`maximum_commit_capacity_bytes
/// >= current_commit_limit_bytes` / `>= commit_total_bytes`) are therefore
/// not ported as hard errors here; `available_maximum_commit_bytes` is
/// clamped to 0 instead of erroring when that physical-RAM-plus-swap figure
/// is genuinely below what is already committed.
#[cfg(not(windows))]
pub fn probe_host_commit_capacity() -> Result<HostCommitCapacity> {
    let raw = std::fs::read_to_string("/proc/meminfo").map_err(|error| {
        EmberLabError::InvalidDispatchManifest {
            detail: format!("Linux host commit probe failed to read /proc/meminfo: {error}"),
        }
    })?;
    let field_bytes = |name: &str| -> Result<u64> {
        meminfo_field_kib(&raw, name)?
            .checked_mul(1024)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: format!("Linux host commit probe overflowed {name} bytes"),
            })
    };
    let physical_ram_bytes = field_bytes("MemTotal")?;
    let physical_available_bytes = field_bytes("MemAvailable")?;
    let pagefile_maximum_bytes = field_bytes("SwapTotal")?;
    let commit_total_bytes = field_bytes("Committed_AS")?;
    let current_commit_limit_bytes = field_bytes("CommitLimit")?;
    let current_commit_remaining_bytes = current_commit_limit_bytes
        .checked_sub(commit_total_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "live committed bytes exceed the current Linux commit limit".into(),
        })?;
    let maximum_commit_capacity_bytes = physical_ram_bytes
        .checked_add(pagefile_maximum_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "Linux maximum commit capacity overflowed bytes".into(),
        })?;
    let available_maximum_commit_bytes = maximum_commit_capacity_bytes
        .checked_sub(commit_total_bytes)
        .unwrap_or(0);
    Ok(HostCommitCapacity {
        physical_ram_bytes,
        physical_available_bytes,
        pagefile_maximum_bytes,
        pagefile_configuration_source: "/proc/meminfo SwapTotal".into(),
        pagefile_configuration_sha256: hash_bytes(raw.as_bytes()),
        commit_total_bytes,
        current_commit_limit_bytes,
        current_commit_remaining_bytes,
        maximum_commit_capacity_bytes,
        available_maximum_commit_bytes,
    })
}

/// Parses a `NAME:    <value> kB` line out of `/proc/meminfo` content,
/// returning the value in KiB. `/proc/meminfo` field names are unique and
/// unambiguous as line prefixes (e.g. `MemTotal` vs `MemAvailable` never
/// collide), so an exact-prefix match is sufficient.
#[cfg(not(windows))]
fn meminfo_field_kib(raw: &str, name: &str) -> Result<u64> {
    raw.lines()
        .find_map(|line| {
            let value = line.strip_prefix(name)?.strip_prefix(':')?.trim();
            value.strip_suffix(" kB")?.trim().parse::<u64>().ok()
        })
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: format!("/proc/meminfo is missing a parseable {name} line"),
        })
}

#[cfg(all(test, not(windows)))]
mod linux_host_commit_capacity_tests {
    use super::*;

    /// Exercises the real probe against this test runner's actual
    /// `/proc/meminfo` -- not a stub, not injected values. Prior to this
    /// fix, `probe_host_commit_capacity()` always returned
    /// `Err(InvalidDispatchManifest)` on Linux, so this test could not
    /// exist; its mere presence and pass is direct evidence the probe now
    /// executes and returns real numbers on `ubuntu-latest`.
    #[test]
    fn probe_host_commit_capacity_reads_real_proc_meminfo() {
        let capacity = probe_host_commit_capacity().expect(
            "probe_host_commit_capacity must succeed against a real /proc/meminfo on Linux CI",
        );
        assert!(capacity.physical_ram_bytes > 0);
        assert!(capacity.maximum_commit_capacity_bytes >= capacity.physical_ram_bytes);
        assert_eq!(
            capacity.available_maximum_commit_bytes,
            capacity
                .maximum_commit_capacity_bytes
                .saturating_sub(capacity.commit_total_bytes)
        );
        assert_eq!(
            capacity.pagefile_configuration_source,
            "/proc/meminfo SwapTotal"
        );
        assert_eq!(capacity.pagefile_configuration_sha256.len(), 64);
    }

    #[test]
    fn probe_host_survival_headroom_matches_commit_capacity_fields() {
        // Each call reads /proc/meminfo live, so `capacity` and `headroom` are
        // two independent kernel reads taken microseconds apart -- on a busy
        // host MemAvailable/Committed_AS can drift by a few KiB between them.
        // A generous tolerance still catches a real delegation bug (which
        // would differ by orders of magnitude, not kilobytes) without being
        // flaky on live CI runners.
        const DRIFT_TOLERANCE_BYTES: u64 = 64 * 1024 * 1024;
        let capacity = probe_host_commit_capacity().unwrap();
        let headroom = probe_host_survival_headroom().unwrap();
        let physical_diff = headroom
            .physical_available_bytes
            .abs_diff(capacity.physical_available_bytes);
        let commit_diff = headroom
            .commit_remaining_bytes
            .abs_diff(capacity.current_commit_remaining_bytes);
        assert!(
            physical_diff <= DRIFT_TOLERANCE_BYTES,
            "physical_available_bytes drifted by {physical_diff} bytes between two live reads (headroom={}, capacity={})",
            headroom.physical_available_bytes,
            capacity.physical_available_bytes,
        );
        assert!(
            commit_diff <= DRIFT_TOLERANCE_BYTES,
            "commit_remaining_bytes drifted by {commit_diff} bytes between two live reads (headroom={}, capacity={})",
            headroom.commit_remaining_bytes,
            capacity.current_commit_remaining_bytes,
        );
    }

    #[test]
    fn meminfo_field_kib_parses_a_real_field_and_rejects_an_absent_one() {
        let raw = std::fs::read_to_string("/proc/meminfo").unwrap();
        assert!(meminfo_field_kib(&raw, "MemTotal").unwrap() > 0);
        assert!(meminfo_field_kib(&raw, "NotARealMeminfoField").is_err());
    }
}

fn available_free_vram_bytes() -> Result<u64> {
    let stdout = nvidia_smi_text(&["--query-gpu=memory.free", "--format=csv,noheader,nounits"])?;
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

fn available_vram_observation(
    contract: Option<VramWallContract>,
) -> Result<DispatchVramObservation> {
    match contract {
        Some(contract) => {
            probe_vram_device_capacity(&contract).map(DispatchVramObservation::Device)
        }
        None => available_free_vram_bytes().map(DispatchVramObservation::LegacyFreeBytes),
    }
}

fn nvidia_smi_text(args: &[&str]) -> Result<String> {
    let mut command = std::process::Command::new("nvidia-smi");
    command.args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let output = command
        .output()
        .map_err(|error| EmberLabError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM probe failed to start: {error}"),
        })?;
    if !output.status.success() {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: format!("nvidia-smi VRAM probe failed with {}", output.status),
        });
    }
    String::from_utf8(output.stdout).map_err(|error| EmberLabError::InvalidDispatchManifest {
        detail: format!("nvidia-smi VRAM output was not UTF-8: {error}"),
    })
}

fn probe_vram_device_capacity(contract: &VramWallContract) -> Result<VramDeviceCapacity> {
    let stdout = nvidia_smi_text(&[
        "--query-gpu=uuid,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ])?;
    for line in stdout.lines().filter(|line| !line.trim().is_empty()) {
        let fields = line.split(',').map(str::trim).collect::<Vec<_>>();
        if fields.len() != 3 {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "nvidia-smi device capacity row has invalid cardinality".into(),
            });
        }
        if fields[0] != contract.device_uuid {
            continue;
        }
        let total_mib =
            fields[1]
                .parse::<u64>()
                .map_err(|error| EmberLabError::InvalidDispatchManifest {
                    detail: format!("nvidia-smi total VRAM value is invalid: {error}"),
                })?;
        let free_mib =
            fields[2]
                .parse::<u64>()
                .map_err(|error| EmberLabError::InvalidDispatchManifest {
                    detail: format!("nvidia-smi free VRAM value is invalid: {error}"),
                })?;
        return Ok(VramDeviceCapacity {
            provider: "nvidia_smi_nvml".into(),
            device_uuid: fields[0].into(),
            total_bytes: total_mib.checked_mul(1024 * 1024).ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "nvidia-smi total VRAM value overflowed".into(),
                }
            })?,
            free_bytes: free_mib.checked_mul(1024 * 1024).ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "nvidia-smi free VRAM value overflowed".into(),
                }
            })?,
        });
    }
    Err(EmberLabError::InvalidDispatchManifest {
        detail: format!(
            "declared VRAM device {} is absent from the provider",
            contract.device_uuid
        ),
    })
}

fn probe_process_vram_bytes(pid: u32, device_uuid: &str) -> Result<u64> {
    let stdout = nvidia_smi_text(&[
        "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ])?;
    let mut total = 0_u64;
    for line in stdout.lines().filter(|line| !line.trim().is_empty()) {
        let fields = line.split(',').map(str::trim).collect::<Vec<_>>();
        if fields.len() != 3 {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "nvidia-smi process VRAM row has invalid cardinality".into(),
            });
        }
        if fields[0].parse::<u32>().ok() != Some(pid) || fields[1] != device_uuid {
            continue;
        }
        let used_mib =
            fields[2]
                .parse::<u64>()
                .map_err(|error| EmberLabError::InvalidDispatchManifest {
                    detail: format!("nvidia-smi process VRAM value is invalid: {error}"),
                })?;
        total = total
            .checked_add(used_mib.checked_mul(1024 * 1024).ok_or_else(|| {
                EmberLabError::InvalidDispatchManifest {
                    detail: "nvidia-smi process VRAM value overflowed".into(),
                }
            })?)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "nvidia-smi aggregate process VRAM value overflowed".into(),
            })?;
    }
    Ok(total)
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
        r#"CREATE TABLE IF NOT EXISTS job_vram_walls(job_id TEXT PRIMARY KEY, contract_json TEXT NOT NULL, maximum_process_vram_bytes INTEGER NOT NULL, consecutive_breach_observations INTEGER NOT NULL DEFAULT 0, active_breach_class TEXT, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
         CREATE TABLE IF NOT EXISTS vram_wall_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
         CREATE TABLE IF NOT EXISTS job_disk_walls(job_id TEXT NOT NULL, write_root TEXT NOT NULL, contract_json TEXT NOT NULL, baseline_tree_bytes INTEGER NOT NULL, consecutive_duration_misses INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id,write_root), FOREIGN KEY(job_id) REFERENCES jobs(job_id));
         CREATE TABLE IF NOT EXISTS disk_wall_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, write_root TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
         CREATE TABLE IF NOT EXISTS disk_volume_floor_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, volume_root TEXT NOT NULL, available_free_bytes INTEGER NOT NULL, payload_json TEXT NOT NULL, UNIQUE(observed_at_ms,volume_root));
         CREATE TABLE IF NOT EXISTS resource_guard_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), admission_state TEXT NOT NULL CHECK(admission_state IN ('open','frozen')), reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL CHECK(oracle_evidence_required IN (0,1)), observation_json TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS resource_guard_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS resource_guard_rearms(frozen_observation_sha256 TEXT PRIMARY KEY, breach_class TEXT NOT NULL, transitioned_at_ms INTEGER NOT NULL, receipt_path TEXT NOT NULL, receipt_sha256 TEXT NOT NULL UNIQUE, healthy_sample_count INTEGER NOT NULL, healthy_window_ms INTEGER NOT NULL, flap_multiplier INTEGER NOT NULL);
         INSERT OR IGNORE INTO resource_guard_state(singleton,admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json) VALUES(1,'open',NULL,0,0,'{}');
         CREATE TABLE IF NOT EXISTS foreign_process_pressure_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL CHECK(state IN ('clear','observed','fenced','probe_failed')), observed_at_ms INTEGER NOT NULL, observation_json TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS foreign_process_pressure_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
         INSERT OR IGNORE INTO foreign_process_pressure_state(singleton,state,observed_at_ms,observation_json) VALUES(1,'probe_failed',0,'{"schema_version":"ember-lab-foreign-process-pressure-observation-v1","result":"NOT_YET_SAMPLED"}');"#,
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
         CREATE TABLE IF NOT EXISTS resource_guard_rearms(frozen_observation_sha256 TEXT PRIMARY KEY, breach_class TEXT NOT NULL, transitioned_at_ms INTEGER NOT NULL, receipt_path TEXT NOT NULL, receipt_sha256 TEXT NOT NULL UNIQUE, healthy_sample_count INTEGER NOT NULL, healthy_window_ms INTEGER NOT NULL, flap_multiplier INTEGER NOT NULL);
         INSERT OR IGNORE INTO resource_guard_state(singleton,admission_state,reason,observed_at_ms,oracle_evidence_required,observation_json) VALUES(1,'open',NULL,0,0,'{}');",
    )?;
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct HostSurvivalHeadroom {
    physical_available_bytes: u64,
    commit_remaining_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ForeignProcessIdentity {
    pid: u32,
    process_start_token: String,
    private_commit_bytes: u64,
    gpu_bytes: Option<u64>,
    gpu_memory_unavailable_token: Option<String>,
    provider: Option<String>,
    candidate_classes: Vec<String>,
    survived_end_probe: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ForeignProcessCensus {
    host_commit_total_bytes: u64,
    host_commit_limit_bytes: u64,
    host_commit_remaining_bytes: u64,
    host_page_size_bytes: u64,
    total_foreign_private_commit_bytes: u64,
    named_foreign_processes: Vec<ForeignProcessIdentity>,
    excluded_kernel_pids: Vec<u32>,
    enumerated_process_count: u64,
    owned_process_count: u64,
    probe_complete: bool,
    attribution_complete: bool,
    total_foreign_private_commit_is_lower_bound: bool,
    exited_processes: Vec<ProcessExitObservation>,
    unreadable_processes: Vec<ProcessReadFailure>,
    identity_conflicts: Vec<ProcessIdentityConflict>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct HostCommitSample {
    commit_total_bytes: u64,
    commit_limit_bytes: u64,
    commit_remaining_bytes: u64,
    page_size_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProcessCommitSample {
    pid: u32,
    process_start_token: String,
    private_commit_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct GpuComputeSample {
    bytes: Option<u64>,
    unavailable_token: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ProcessExitObservation {
    pid: u32,
    phase: String,
    win32_code: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ProcessReadFailure {
    pid: u32,
    phase: String,
    win32_code: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ProcessIdentityConflict {
    pid: u32,
    expected_start_token: String,
    observed_start_token: String,
    phase: String,
    win32_code: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum ProcessCensusObservation {
    Live(ProcessCommitSample),
    Exited(ProcessExitObservation),
    Unreadable(ProcessReadFailure),
    IdentityConflict(ProcessIdentityConflict),
}

#[cfg(windows)]
#[derive(Clone, Debug, Eq, PartialEq)]
struct OwnedJobIdentity {
    job_id: String,
    job_object_name: String,
}

#[cfg(windows)]
trait ForeignProcessCensusProvider: Send + Sync {
    fn sample(&self, owned_jobs: &[OwnedJobIdentity]) -> Result<ForeignProcessCensus>;
}

#[cfg(windows)]
struct WindowsForeignProcessCensusProvider;

#[cfg(windows)]
impl ForeignProcessCensusProvider for WindowsForeignProcessCensusProvider {
    fn sample(&self, owned_jobs: &[OwnedJobIdentity]) -> Result<ForeignProcessCensus> {
        sample_windows_foreign_process_census(owned_jobs)
    }
}

#[cfg(windows)]
fn sample_foreign_process_census(
    provider: &dyn ForeignProcessCensusProvider,
    owned_jobs: &[OwnedJobIdentity],
) -> Result<ForeignProcessCensus> {
    provider.sample(owned_jobs)
}

#[cfg(windows)]
fn owned_job_identities_from_connection(conn: &Connection) -> Result<Vec<OwnedJobIdentity>> {
    let mut statement = conn
        .prepare("SELECT job_id,job_object_name FROM jobs WHERE state='running' ORDER BY job_id")?;
    let rows = statement.query_map([], |row| {
        Ok(OwnedJobIdentity {
            job_id: row.get(0)?,
            job_object_name: row.get(1)?,
        })
    })?;
    rows.collect::<std::result::Result<Vec<_>, _>>()
        .map_err(Into::into)
}

#[cfg(windows)]
const FOREIGN_PROCESS_OPEN_ACCESS_MASK: u32 =
    windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION | 0x0010_0000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ForeignPressureState {
    Clear,
    Observed,
    Fenced,
    ProbeFailed,
}

const FOREIGN_PRESSURE_OBSERVATION_LIMIT: i64 = 4096;
const FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES: u64 = 4 * 1024 * 1024 * 1024;

impl ForeignPressureState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Clear => "clear",
            Self::Observed => "observed",
            Self::Fenced => "fenced",
            Self::ProbeFailed => "probe_failed",
        }
    }
}

fn foreign_pressure_transition(census: &ForeignProcessCensus) -> ForeignPressureState {
    if !census.probe_complete {
        ForeignPressureState::ProbeFailed
    } else if census.host_commit_remaining_bytes < RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES {
        ForeignPressureState::Fenced
    } else if census.named_foreign_processes.is_empty() {
        ForeignPressureState::Clear
    } else {
        ForeignPressureState::Observed
    }
}

fn classify_foreign_samples(
    host: HostCommitSample,
    observations: Vec<ProcessCensusObservation>,
    gpu_bytes_by_pid: &BTreeMap<u32, GpuComputeSample>,
    owned_identities: &std::collections::BTreeSet<(u32, String)>,
) -> Result<ForeignProcessCensus> {
    let enumerated_process_count = u64::try_from(observations.len()).unwrap_or(u64::MAX);
    let mut total_foreign_private_commit_bytes = 0_u64;
    let mut named_foreign_processes = Vec::new();
    let mut exited_processes = Vec::new();
    let mut unreadable_processes = Vec::new();
    let mut identity_conflicts = Vec::new();
    let mut owned_process_count = 0_u64;

    for observation in observations {
        match observation {
            ProcessCensusObservation::Live(process) => {
                if owned_identities.contains(&(process.pid, process.process_start_token.clone())) {
                    owned_process_count = owned_process_count.saturating_add(1);
                    continue;
                }
                total_foreign_private_commit_bytes = total_foreign_private_commit_bytes
                    .checked_add(process.private_commit_bytes)
                    .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                        detail: "foreign private commit aggregate overflowed".into(),
                    })?;
                let mut candidate_classes = Vec::new();
                let gpu_sample = gpu_bytes_by_pid.get(&process.pid);
                let gpu_bytes = gpu_sample.and_then(|sample| sample.bytes);
                if gpu_sample.is_some() {
                    candidate_classes.push("gpu_compute".into());
                }
                if process.private_commit_bytes >= FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES {
                    candidate_classes.push("private_commit_attribution".into());
                }
                if !candidate_classes.is_empty() {
                    named_foreign_processes.push(ForeignProcessIdentity {
                        pid: process.pid,
                        process_start_token: process.process_start_token,
                        private_commit_bytes: process.private_commit_bytes,
                        gpu_bytes,
                        gpu_memory_unavailable_token: gpu_sample
                            .and_then(|sample| sample.unavailable_token.clone()),
                        provider: gpu_sample.map(|_| "nvidia_smi_nvml".into()),
                        candidate_classes,
                        survived_end_probe: false,
                    });
                }
            }
            ProcessCensusObservation::Exited(exited) => exited_processes.push(exited),
            ProcessCensusObservation::Unreadable(unreadable) => {
                unreadable_processes.push(unreadable)
            }
            ProcessCensusObservation::IdentityConflict(conflict) => {
                identity_conflicts.push(conflict)
            }
        }
    }
    named_foreign_processes.sort_by(|left, right| {
        (left.pid, &left.process_start_token).cmp(&(right.pid, &right.process_start_token))
    });
    let attribution_complete = unreadable_processes.is_empty() && identity_conflicts.is_empty();

    Ok(ForeignProcessCensus {
        host_commit_total_bytes: host.commit_total_bytes,
        host_commit_limit_bytes: host.commit_limit_bytes,
        host_commit_remaining_bytes: host.commit_remaining_bytes,
        host_page_size_bytes: host.page_size_bytes,
        total_foreign_private_commit_bytes,
        named_foreign_processes,
        excluded_kernel_pids: vec![0, 4],
        enumerated_process_count,
        owned_process_count,
        probe_complete: true,
        attribution_complete,
        total_foreign_private_commit_is_lower_bound: !attribution_complete,
        exited_processes,
        unreadable_processes,
        identity_conflicts,
    })
}

fn persist_foreign_process_census(
    conn: &Connection,
    observed_at_ms: i64,
    sample: Result<ForeignProcessCensus>,
) -> Result<()> {
    let (state, observation) = match sample {
        Ok(census) => {
            let state = foreign_pressure_transition(&census);
            let result = match state {
                ForeignPressureState::Clear => "CLEAR",
                ForeignPressureState::Observed => "OBSERVED",
                ForeignPressureState::Fenced => "FENCED",
                ForeignPressureState::ProbeFailed => "PROBE_FAILED",
            };
            (
                state,
                json!({
                    "schema_version": "ember-lab-foreign-process-pressure-observation-v1",
                    "result": result,
                    "observed_at_ms": observed_at_ms,
                    "monitor_tier": "windows_process_private_commit_and_gpu_context",
                    "host_commit_total_bytes": census.host_commit_total_bytes,
                    "host_commit_limit_bytes": census.host_commit_limit_bytes,
                    "host_commit_remaining_bytes": census.host_commit_remaining_bytes,
                    "host_page_size_bytes": census.host_page_size_bytes,
                    "minimum_commit_remaining_bytes": RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES,
                    "foreign_process_attribution_cutoff_bytes": FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES,
                    "total_foreign_private_commit_bytes": census.total_foreign_private_commit_bytes,
                    "named_foreign_processes": census.named_foreign_processes,
                    "excluded_kernel_pids": census.excluded_kernel_pids,
                    "enumerated_process_count": census.enumerated_process_count,
                    "owned_process_count": census.owned_process_count,
                    "probe_complete": census.probe_complete,
                    "attribution_complete": census.attribution_complete,
                    "total_foreign_private_commit_is_lower_bound": census.total_foreign_private_commit_is_lower_bound,
                    "exited_processes": census.exited_processes,
                    "unreadable_processes": census.unreadable_processes,
                    "identity_conflicts": census.identity_conflicts,
                    "counter_sources": {
                        "host_commit": "GetPerformanceInfo.CommitLimit-CommitTotal",
                        "process_private_commit": "K32GetProcessMemoryInfo.PROCESS_MEMORY_COUNTERS_EX.PrivateUsage",
                        "gpu_compute_context": "nvidia-smi.query-compute-apps",
                    },
                    "foreign_process_control": false,
                }),
            )
        }
        Err(error) => (
            ForeignPressureState::ProbeFailed,
            json!({
                "schema_version": "ember-lab-foreign-process-pressure-observation-v1",
                "result": "PROBE_FAILED",
                "observed_at_ms": observed_at_ms,
                "monitor_tier": "windows_process_private_commit_and_gpu_context",
                "error": format!("{error:?}"),
                "minimum_commit_remaining_bytes": RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES,
                "foreign_process_attribution_cutoff_bytes": FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES,
                "foreign_process_control": false,
            }),
        ),
    };
    let observation_json = serde_json::to_string(&observation)?;
    let tx = conn.unchecked_transaction()?;
    tx.execute(
        "INSERT INTO foreign_process_pressure_observations(observed_at_ms,outcome,payload_json) VALUES(?1,?2,?3)",
        params![observed_at_ms, state.as_str(), observation_json],
    )?;
    tx.execute(
        "DELETE FROM foreign_process_pressure_observations WHERE seq <= COALESCE((SELECT MAX(seq) FROM foreign_process_pressure_observations),0)-?1",
        [FOREIGN_PRESSURE_OBSERVATION_LIMIT],
    )?;
    tx.execute(
        "UPDATE foreign_process_pressure_state SET state=?1,observed_at_ms=?2,observation_json=?3 WHERE singleton=1",
        params![state.as_str(), observed_at_ms, observation_json],
    )?;
    tx.commit()?;
    Ok(())
}

fn foreign_process_pressure_status_from_connection(conn: &Connection) -> Result<Value> {
    let (state, observed_at_ms, observation_json): (String, i64, String) = conn.query_row(
        "SELECT state,observed_at_ms,observation_json FROM foreign_process_pressure_state WHERE singleton=1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )?;
    let (resource_guard_state, resource_guard_reason): (String, Option<String>) = conn.query_row(
        "SELECT admission_state,reason FROM resource_guard_state WHERE singleton=1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let observation: Value = serde_json::from_str(&observation_json).map_err(|error| {
        EmberLabError::InvalidDispatchManifest {
            detail: format!("foreign process pressure observation is invalid: {error}"),
        }
    })?;
    let pressure_refuses = state == "fenced" || state == "probe_failed";
    let admission_state = if resource_guard_state == "frozen" || pressure_refuses {
        "frozen"
    } else {
        "open"
    };
    Ok(json!({
        "schema_version": "ember-lab-foreign-process-pressure-state-v1",
        "state": state,
        "observed_at_ms": observed_at_ms,
        "observation": observation,
        "sampling_interval_ms": RESOURCE_GUARD_SAMPLE_INTERVAL_MS,
        "effective_admission": {
            "admission_state": admission_state,
            "resource_guard_state": resource_guard_state,
            "resource_guard_reason": resource_guard_reason,
            "foreign_process_pressure_state": state,
        },
    }))
}

fn verify_foreign_process_pressure_probe_receipt(bytes: &[u8]) -> Result<Value> {
    let receipt: Value = serde_json::from_slice(bytes)?;
    let object = receipt
        .as_object()
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe receipt is not an object".into(),
        })?;
    let expected_keys = std::collections::BTreeSet::from([
        "ember_lab_identity",
        "foreign_process_control",
        "observation",
        "observation_sha256",
        "observed_at_ms",
        "receipt_sha256",
        "schema_version",
        "state",
        "verdict",
    ]);
    if object
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>()
        != expected_keys
        || object.get("schema_version")
            != Some(&Value::String(
                "ember-lab-foreign-process-pressure-probe-v1".into(),
            ))
        || object.get("verdict") != Some(&Value::String("EXECUTED".into()))
        || object.get("foreign_process_control") != Some(&Value::Bool(false))
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe receipt has an invalid top-level shape".into(),
        });
    }
    let identity = object
        .get("ember_lab_identity")
        .and_then(Value::as_object)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe receipt lacks daemon identity".into(),
        })?;
    if identity
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>()
        != std::collections::BTreeSet::from(["binary_sha256", "source_sha256"])
        || !identity
            .values()
            .all(|value| value.as_str().is_some_and(is_sha256))
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe receipt has an invalid daemon identity".into(),
        });
    }
    let observation =
        object
            .get("observation")
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe receipt lacks observation".into(),
            })?;
    let observation_object =
        observation
            .as_object()
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe observation is not an object".into(),
            })?;
    let expected_observation_keys = std::collections::BTreeSet::from([
        "attribution_complete",
        "counter_sources",
        "enumerated_process_count",
        "excluded_kernel_pids",
        "exited_processes",
        "foreign_process_attribution_cutoff_bytes",
        "foreign_process_control",
        "host_commit_limit_bytes",
        "host_commit_remaining_bytes",
        "host_commit_total_bytes",
        "host_page_size_bytes",
        "identity_conflicts",
        "minimum_commit_remaining_bytes",
        "monitor_tier",
        "named_foreign_processes",
        "observed_at_ms",
        "owned_process_count",
        "probe_complete",
        "result",
        "schema_version",
        "total_foreign_private_commit_bytes",
        "total_foreign_private_commit_is_lower_bound",
        "unreadable_processes",
    ]);
    if observation_object
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>()
        != expected_observation_keys
        || observation_object.get("schema_version")
            != Some(&Value::String(
                "ember-lab-foreign-process-pressure-observation-v1".into(),
            ))
        || observation_object.get("probe_complete") != Some(&Value::Bool(true))
        || observation_object
            .get("attribution_complete")
            .and_then(Value::as_bool)
            .is_none()
        || observation_object
            .get("total_foreign_private_commit_is_lower_bound")
            .and_then(Value::as_bool)
            != observation_object
                .get("attribution_complete")
                .and_then(Value::as_bool)
                .map(|complete| !complete)
        || observation_object.get("foreign_process_control") != Some(&Value::Bool(false))
        || observation_object.get("monitor_tier")
            != Some(&Value::String(
                "windows_process_private_commit_and_gpu_context".into(),
            ))
        || observation_object.get("excluded_kernel_pids") != Some(&json!([0, 4]))
        || observation_object
            .get("unreadable_processes")
            .and_then(Value::as_array)
            .is_none()
        || observation_object
            .get("identity_conflicts")
            .and_then(Value::as_array)
            .is_none()
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe observation is incomplete or malformed".into(),
        });
    }
    let attribution_complete = observation_object["attribution_complete"]
        .as_bool()
        .unwrap();
    let attribution_failure_count = observation_object["unreadable_processes"]
        .as_array()
        .unwrap()
        .len()
        + observation_object["identity_conflicts"]
            .as_array()
            .unwrap()
            .len();
    if attribution_complete != (attribution_failure_count == 0) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe attribution completeness is inconsistent".into(),
        });
    }
    let actual_observation_sha256 = hash_bytes(&serde_json::to_vec(observation)?);
    if object.get("observed_at_ms") != observation_object.get("observed_at_ms")
        || object.get("observation_sha256").and_then(Value::as_str)
            != Some(actual_observation_sha256.as_str())
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe observation binding is invalid".into(),
        });
    }
    let counters = observation_object
        .get("counter_sources")
        .and_then(Value::as_object);
    if counters
        .and_then(|value| value.get("host_commit"))
        .and_then(Value::as_str)
        != Some("GetPerformanceInfo.CommitLimit-CommitTotal")
        || counters
            .and_then(|value| value.get("process_private_commit"))
            .and_then(Value::as_str)
            != Some("K32GetProcessMemoryInfo.PROCESS_MEMORY_COUNTERS_EX.PrivateUsage")
        || counters
            .and_then(|value| value.get("gpu_compute_context"))
            .and_then(Value::as_str)
            != Some("nvidia-smi.query-compute-apps")
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe counter sources are invalid".into(),
        });
    }
    let u64_field = |name: &str| {
        observation_object
            .get(name)
            .and_then(Value::as_u64)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: format!("foreign pressure probe lacks {name}"),
            })
    };
    let total = u64_field("host_commit_total_bytes")?;
    let limit = u64_field("host_commit_limit_bytes")?;
    let remaining = u64_field("host_commit_remaining_bytes")?;
    if limit.checked_sub(total) != Some(remaining)
        || u64_field("host_page_size_bytes")? == 0
        || u64_field("minimum_commit_remaining_bytes")? != RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES
        || u64_field("foreign_process_attribution_cutoff_bytes")?
            != FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe host counter arithmetic is invalid".into(),
        });
    }
    let named = observation_object
        .get("named_foreign_processes")
        .and_then(Value::as_array)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe named identities are invalid".into(),
        })?;
    let mut previous: Option<(u64, String)> = None;
    let mut named_private_commit = 0_u64;
    for process in named {
        let process_object =
            process
                .as_object()
                .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                    detail: "foreign pressure probe named identity is not an object".into(),
                })?;
        if process_object
            .keys()
            .map(String::as_str)
            .collect::<std::collections::BTreeSet<_>>()
            != std::collections::BTreeSet::from([
                "candidate_classes",
                "gpu_bytes",
                "gpu_memory_unavailable_token",
                "pid",
                "private_commit_bytes",
                "process_start_token",
                "provider",
                "survived_end_probe",
            ])
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identity shape is invalid".into(),
            });
        }
        let pid = process.get("pid").and_then(Value::as_u64).ok_or_else(|| {
            EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identity lacks PID".into(),
            }
        })?;
        let token = process
            .get("process_start_token")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identity lacks start token".into(),
            })?;
        if pid > u32::MAX as u64 || process.get("survived_end_probe") != Some(&Value::Bool(true)) {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identity did not survive end probe".into(),
            });
        }
        let identity = (pid, token.to_string());
        if previous
            .as_ref()
            .is_some_and(|previous| previous >= &identity)
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identities are not sorted and unique".into(),
            });
        }
        previous = Some(identity);
        let classes = process
            .get("candidate_classes")
            .and_then(Value::as_array)
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identity lacks candidate classes".into(),
            })?;
        if classes.is_empty()
            || classes.iter().any(|class| {
                !matches!(
                    class.as_str(),
                    Some("gpu_compute" | "private_commit_attribution")
                )
            })
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named identity classes are invalid".into(),
            });
        }
        let gpu_class = classes
            .iter()
            .any(|class| class.as_str() == Some("gpu_compute"));
        let gpu_bytes = process.get("gpu_bytes").and_then(Value::as_u64);
        let unavailable = process
            .get("gpu_memory_unavailable_token")
            .and_then(Value::as_str);
        if (gpu_class && gpu_bytes.is_none() && unavailable.is_none())
            || (gpu_bytes.is_some() && unavailable.is_some())
            || (!gpu_class && (gpu_bytes.is_some() || unavailable.is_some()))
        {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe GPU size availability is invalid".into(),
            });
        }
        named_private_commit = named_private_commit
            .checked_add(
                process
                    .get("private_commit_bytes")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                        detail: "foreign pressure probe named identity lacks private commit".into(),
                    })?,
            )
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "foreign pressure probe named private commit overflowed".into(),
            })?;
    }
    let total_foreign = u64_field("total_foreign_private_commit_bytes")?;
    if named_private_commit > total_foreign {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe named private commit exceeds total foreign commit"
                .into(),
        });
    }
    let expected_state = if remaining < RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES {
        "fenced"
    } else if named.is_empty() {
        "clear"
    } else {
        "observed"
    };
    let expected_result = expected_state.to_ascii_uppercase();
    if object.get("state").and_then(Value::as_str) != Some(expected_state)
        || observation_object.get("result").and_then(Value::as_str)
            != Some(expected_result.as_str())
    {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe state does not match its observation".into(),
        });
    }
    let expected_self_hash = object
        .get("receipt_sha256")
        .and_then(Value::as_str)
        .filter(|value| is_sha256(value))
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe receipt lacks self hash".into(),
        })?;
    let mut without_self_hash = receipt.clone();
    without_self_hash
        .as_object_mut()
        .unwrap()
        .remove("receipt_sha256");
    if hash_bytes(&serde_json::to_vec(&without_self_hash)?) != expected_self_hash {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "foreign pressure probe self hash is invalid".into(),
        });
    }
    Ok(receipt)
}

#[cfg(windows)]
fn process_start_token(pid: u32) -> Result<String> {
    use windows_sys::Win32::System::Threading::OpenProcess;

    let process = unsafe { OpenProcess(FOREIGN_PROCESS_OPEN_ACCESS_MASK, 0, pid) };
    if process.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    let process = OwnedHandle(process);
    windows_process_time_identity(process.raw()).map(|(token, _)| token)
}

#[cfg(windows)]
fn windows_process_time_identity(
    handle: windows_sys::Win32::Foundation::HANDLE,
) -> Result<(String, bool)> {
    use std::mem::zeroed;
    use windows_sys::Win32::Foundation::FILETIME;
    use windows_sys::Win32::System::Threading::GetProcessTimes;

    let (mut creation, mut exit, mut kernel, mut user): (FILETIME, FILETIME, FILETIME, FILETIME) =
        unsafe { zeroed() };
    if unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok((
        format!(
            "{:08x}{:08x}",
            creation.dwHighDateTime, creation.dwLowDateTime
        ),
        exit.dwHighDateTime != 0 || exit.dwLowDateTime != 0,
    ))
}

#[cfg(windows)]
fn sample_windows_host_commit() -> Result<HostCommitSample> {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::System::ProcessStatus::{GetPerformanceInfo, PERFORMANCE_INFORMATION};

    let mut info: PERFORMANCE_INFORMATION = unsafe { zeroed() };
    info.cb = size_of::<PERFORMANCE_INFORMATION>() as u32;
    if unsafe { GetPerformanceInfo(&mut info, info.cb) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let page_size_bytes =
        u64::try_from(info.PageSize).map_err(|_| EmberLabError::InvalidDispatchManifest {
            detail: "host page size does not fit in u64".into(),
        })?;
    let commit_total_pages =
        u64::try_from(info.CommitTotal).map_err(|_| EmberLabError::InvalidDispatchManifest {
            detail: "host commit total does not fit in u64".into(),
        })?;
    let commit_limit_pages =
        u64::try_from(info.CommitLimit).map_err(|_| EmberLabError::InvalidDispatchManifest {
            detail: "host commit limit does not fit in u64".into(),
        })?;
    let commit_total_bytes = commit_total_pages
        .checked_mul(page_size_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "host commit total overflowed".into(),
        })?;
    let commit_limit_bytes = commit_limit_pages
        .checked_mul(page_size_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "host commit limit overflowed".into(),
        })?;
    let commit_remaining_bytes = commit_limit_bytes
        .checked_sub(commit_total_bytes)
        .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
            detail: "host commit total exceeded commit limit".into(),
        })?;
    Ok(HostCommitSample {
        commit_total_bytes,
        commit_limit_bytes,
        commit_remaining_bytes,
        page_size_bytes,
    })
}

#[cfg(windows)]
fn enumerate_windows_process_ids() -> Result<Vec<u32>> {
    use windows_sys::Win32::System::ProcessStatus::K32EnumProcesses;

    let mut capacity = 1024_usize;
    loop {
        let mut pids = vec![0_u32; capacity];
        let byte_capacity = pids
            .len()
            .checked_mul(std::mem::size_of::<u32>())
            .and_then(|size| u32::try_from(size).ok())
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "process enumeration buffer overflowed".into(),
            })?;
        let mut bytes_written = 0_u32;
        if unsafe { K32EnumProcesses(pids.as_mut_ptr(), byte_capacity, &mut bytes_written) } == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        if bytes_written < byte_capacity {
            pids.truncate(bytes_written as usize / std::mem::size_of::<u32>());
            return Ok(pids);
        }
        capacity =
            capacity
                .checked_mul(2)
                .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                    detail: "process enumeration capacity overflowed".into(),
                })?;
    }
}

#[cfg(windows)]
fn parse_nvidia_compute_rows(stdout: &str) -> Result<BTreeMap<u32, GpuComputeSample>> {
    let mut result = BTreeMap::new();
    for (line_index, line) in stdout.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let mut fields = line.split(',').map(str::trim);
        let pid = fields
            .next()
            .and_then(|value| value.parse::<u32>().ok())
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: format!("invalid NVIDIA compute PID at line {}", line_index + 1),
            })?;
        let memory = fields
            .next()
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: format!("missing NVIDIA compute memory at line {}", line_index + 1),
            })?;
        if fields.next().is_some() {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: format!(
                    "unexpected NVIDIA compute fields at line {}",
                    line_index + 1
                ),
            });
        }
        let normalized = memory.to_ascii_lowercase();
        let sample = if normalized == "n/a" || normalized == "[n/a]" {
            GpuComputeSample {
                bytes: None,
                unavailable_token: Some(memory.to_string()),
            }
        } else {
            let mib =
                memory
                    .parse::<u64>()
                    .map_err(|_| EmberLabError::InvalidDispatchManifest {
                        detail: format!("invalid NVIDIA compute memory at line {}", line_index + 1),
                    })?;
            GpuComputeSample {
                bytes: Some(mib.checked_mul(1024 * 1024).ok_or_else(|| {
                    EmberLabError::InvalidDispatchManifest {
                        detail: "NVIDIA compute memory overflowed".into(),
                    }
                })?),
                unavailable_token: None,
            }
        };
        match result.entry(pid) {
            std::collections::btree_map::Entry::Vacant(entry) => {
                entry.insert(sample);
            }
            std::collections::btree_map::Entry::Occupied(mut entry) => {
                let prior = entry.get_mut();
                prior.bytes = match (prior.bytes, sample.bytes) {
                    (Some(left), Some(right)) => {
                        Some(left.checked_add(right).ok_or_else(|| {
                            EmberLabError::InvalidDispatchManifest {
                                detail: "NVIDIA compute memory aggregate overflowed".into(),
                            }
                        })?)
                    }
                    _ => None,
                };
                if prior.unavailable_token.is_none() {
                    prior.unavailable_token = sample.unavailable_token;
                }
            }
        }
    }
    Ok(result)
}

#[cfg(windows)]
fn nvidia_compute_bytes_by_pid() -> Result<BTreeMap<u32, GpuComputeSample>> {
    let stdout = nvidia_smi_text(&[
        "--query-compute-apps=pid,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ])?;
    parse_nvidia_compute_rows(&stdout)
}

#[cfg(windows)]
fn probe_windows_process_observations_with_owned(
    owned_jobs: &[OwnedJobIdentity],
) -> Result<(
    HostCommitSample,
    Vec<ProcessCensusObservation>,
    BTreeMap<u32, GpuComputeSample>,
    std::collections::BTreeSet<(u32, String)>,
)> {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::Foundation::ERROR_INVALID_PARAMETER;
    use windows_sys::Win32::System::JobObjects::{IsProcessInJob, OpenJobObjectW};
    use windows_sys::Win32::System::ProcessStatus::{
        K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS, PROCESS_MEMORY_COUNTERS_EX,
    };
    use windows_sys::Win32::System::SystemServices::JOB_OBJECT_QUERY;
    use windows_sys::Win32::System::Threading::OpenProcess;

    let host = sample_windows_host_commit()?;
    let pids = enumerate_windows_process_ids()?;
    let gpu_bytes_by_pid = nvidia_compute_bytes_by_pid()?;
    let mut owned_handles = Vec::with_capacity(owned_jobs.len());
    for owned_job in owned_jobs {
        let name = wide(&owned_job.job_object_name);
        let handle = unsafe { OpenJobObjectW(JOB_OBJECT_QUERY, 0, name.as_ptr()) };
        if handle.is_null() {
            return Err(std::io::Error::last_os_error().into());
        }
        owned_handles.push((owned_job.job_id.clone(), OwnedHandle(handle)));
    }

    let mut observations = Vec::with_capacity(pids.len());
    let mut owned_identities = std::collections::BTreeSet::new();
    for pid in pids.into_iter().filter(|pid| *pid != 0 && *pid != 4) {
        let process = unsafe { OpenProcess(FOREIGN_PROCESS_OPEN_ACCESS_MASK, 0, pid) };
        if process.is_null() {
            let code = std::io::Error::last_os_error().raw_os_error().unwrap_or(0) as u32;
            if code == ERROR_INVALID_PARAMETER {
                observations.push(ProcessCensusObservation::Exited(ProcessExitObservation {
                    pid,
                    phase: "enumeration".into(),
                    win32_code: code,
                }));
            } else {
                observations.push(ProcessCensusObservation::Unreadable(ProcessReadFailure {
                    pid,
                    phase: "enumeration_open".into(),
                    win32_code: code,
                }));
            }
            continue;
        }
        let process = OwnedHandle(process);
        let process_start_token = match windows_process_time_identity(process.raw()) {
            Ok((_, true)) => {
                observations.push(ProcessCensusObservation::Exited(ProcessExitObservation {
                    pid,
                    phase: "enumeration_identity".into(),
                    win32_code: 0,
                }));
                continue;
            }
            Ok((token, false)) => token,
            Err(error) => {
                let code = match &error {
                    EmberLabError::Io(error) => error.raw_os_error().unwrap_or(0) as u32,
                    _ => 0,
                };
                let observation = if code == ERROR_INVALID_PARAMETER {
                    ProcessCensusObservation::Exited(ProcessExitObservation {
                        pid,
                        phase: "enumeration_identity".into(),
                        win32_code: code,
                    })
                } else {
                    ProcessCensusObservation::Unreadable(ProcessReadFailure {
                        pid,
                        phase: "enumeration_identity".into(),
                        win32_code: code,
                    })
                };
                observations.push(observation);
                continue;
            }
        };

        let mut counters: PROCESS_MEMORY_COUNTERS_EX = unsafe { zeroed() };
        counters.cb = size_of::<PROCESS_MEMORY_COUNTERS_EX>() as u32;
        if unsafe {
            K32GetProcessMemoryInfo(
                process.raw(),
                (&mut counters as *mut PROCESS_MEMORY_COUNTERS_EX)
                    .cast::<PROCESS_MEMORY_COUNTERS>(),
                counters.cb,
            )
        } == 0
        {
            let code = std::io::Error::last_os_error().raw_os_error().unwrap_or(0) as u32;
            let observation = if code == ERROR_INVALID_PARAMETER {
                ProcessCensusObservation::Exited(ProcessExitObservation {
                    pid,
                    phase: "enumeration_private_commit".into(),
                    win32_code: code,
                })
            } else {
                ProcessCensusObservation::Unreadable(ProcessReadFailure {
                    pid,
                    phase: "enumeration_private_commit".into(),
                    win32_code: code,
                })
            };
            observations.push(observation);
            continue;
        }

        let mut ownership_probe_failed = None;
        for (_, job) in &owned_handles {
            let mut is_member = 0;
            if unsafe { IsProcessInJob(process.raw(), job.raw(), &mut is_member) } == 0 {
                ownership_probe_failed =
                    Some(std::io::Error::last_os_error().raw_os_error().unwrap_or(0) as u32);
                break;
            }
            if is_member != 0 {
                owned_identities.insert((pid, process_start_token.clone()));
                break;
            }
        }
        if let Some(code) = ownership_probe_failed {
            observations.push(ProcessCensusObservation::Unreadable(ProcessReadFailure {
                pid,
                phase: "owned_job_membership".into(),
                win32_code: code,
            }));
            continue;
        }
        observations.push(ProcessCensusObservation::Live(ProcessCommitSample {
            pid,
            process_start_token,
            private_commit_bytes: u64::try_from(counters.PrivateUsage).map_err(|_| {
                EmberLabError::InvalidDispatchManifest {
                    detail: format!("private commit for PID {pid} does not fit in u64"),
                }
            })?,
        }));
    }
    Ok((host, observations, gpu_bytes_by_pid, owned_identities))
}

#[cfg(windows)]
fn probe_windows_process_observations(
    owned_jobs: &[OwnedJobIdentity],
) -> Result<(
    HostCommitSample,
    Vec<ProcessCensusObservation>,
    BTreeMap<u32, GpuComputeSample>,
)> {
    let (host, observations, gpu_bytes_by_pid, _) =
        probe_windows_process_observations_with_owned(owned_jobs)?;
    Ok((host, observations, gpu_bytes_by_pid))
}

#[cfg(windows)]
fn sample_windows_foreign_process_census(
    owned_jobs: &[OwnedJobIdentity],
) -> Result<ForeignProcessCensus> {
    use windows_sys::Win32::Foundation::ERROR_INVALID_PARAMETER;
    use windows_sys::Win32::System::Threading::OpenProcess;

    let (host, mut observations, gpu_bytes_by_pid, owned_identities) =
        probe_windows_process_observations_with_owned(owned_jobs)?;
    let initial = classify_foreign_samples(
        host,
        observations.clone(),
        &gpu_bytes_by_pid,
        &owned_identities,
    )?;
    let expected = initial
        .named_foreign_processes
        .iter()
        .map(|process| (process.pid, process.process_start_token.clone()))
        .collect::<BTreeMap<_, _>>();
    let mut survived = std::collections::BTreeSet::new();

    for (pid, expected_start_token) in expected {
        let replacement = {
            let process = unsafe { OpenProcess(FOREIGN_PROCESS_OPEN_ACCESS_MASK, 0, pid) };
            if process.is_null() {
                let code = std::io::Error::last_os_error().raw_os_error().unwrap_or(0) as u32;
                Some(if code == ERROR_INVALID_PARAMETER {
                    ProcessCensusObservation::Exited(ProcessExitObservation {
                        pid,
                        phase: "named_process_end_probe".into(),
                        win32_code: code,
                    })
                } else {
                    ProcessCensusObservation::Unreadable(ProcessReadFailure {
                        pid,
                        phase: "named_process_end_probe".into(),
                        win32_code: code,
                    })
                })
            } else {
                let process = OwnedHandle(process);
                match windows_process_time_identity(process.raw()) {
                    Ok((_, true)) => {
                        Some(ProcessCensusObservation::Exited(ProcessExitObservation {
                            pid,
                            phase: "named_process_end_probe".into(),
                            win32_code: 0,
                        }))
                    }
                    Ok((observed_start_token, false))
                        if observed_start_token == expected_start_token =>
                    {
                        survived.insert((pid, expected_start_token.clone()));
                        None
                    }
                    Ok((observed_start_token, false)) => Some(
                        ProcessCensusObservation::IdentityConflict(ProcessIdentityConflict {
                            pid,
                            expected_start_token: expected_start_token.clone(),
                            observed_start_token,
                            phase: "named_process_end_probe".into(),
                            win32_code: 0,
                        }),
                    ),
                    Err(error) => {
                        let code = match &error {
                            EmberLabError::Io(error) => error.raw_os_error().unwrap_or(0) as u32,
                            _ => 0,
                        };
                        Some(if code == ERROR_INVALID_PARAMETER {
                            ProcessCensusObservation::Exited(ProcessExitObservation {
                                pid,
                                phase: "named_process_end_probe".into(),
                                win32_code: code,
                            })
                        } else {
                            ProcessCensusObservation::Unreadable(ProcessReadFailure {
                                pid,
                                phase: "named_process_end_probe".into(),
                                win32_code: code,
                            })
                        })
                    }
                }
            }
        };
        if let Some(replacement) = replacement {
            observations.retain(|observation| {
                !matches!(observation, ProcessCensusObservation::Live(sample) if sample.pid == pid && sample.process_start_token == expected_start_token)
            });
            observations.push(replacement);
        }
    }

    let mut census =
        classify_foreign_samples(host, observations, &gpu_bytes_by_pid, &owned_identities)?;
    for process in &mut census.named_foreign_processes {
        process.survived_end_probe =
            survived.contains(&(process.pid, process.process_start_token.clone()));
    }
    Ok(census)
}

fn foreign_pressure_state_from_sample(
    sample: Result<ForeignProcessCensus>,
) -> ForeignPressureState {
    match sample {
        Ok(census) => foreign_pressure_transition(&census),
        Err(_) => ForeignPressureState::ProbeFailed,
    }
}

#[cfg(test)]
mod foreign_pressure_policy_tests {
    use super::*;

    fn pressure_test_connection() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            r#"CREATE TABLE foreign_process_pressure_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL CHECK(state IN ('clear','observed','fenced','probe_failed')), observed_at_ms INTEGER NOT NULL, observation_json TEXT NOT NULL);
               CREATE TABLE foreign_process_pressure_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
               INSERT INTO foreign_process_pressure_state VALUES(1,'probe_failed',0,'{}');
               CREATE TABLE resource_guard_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), admission_state TEXT NOT NULL, reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL, observation_json TEXT NOT NULL);
               INSERT INTO resource_guard_state VALUES(1,'frozen','preexisting_sticky_guard',1,1,'{"result":"FROZEN"}');"#,
        )
        .unwrap();
        conn
    }

    fn pressure_census(
        commit_remaining_bytes: u64,
        named_foreign_processes: Vec<ForeignProcessIdentity>,
    ) -> ForeignProcessCensus {
        ForeignProcessCensus {
            host_commit_total_bytes: 64 * 1024 * 1024 * 1024 - commit_remaining_bytes,
            host_commit_limit_bytes: 64 * 1024 * 1024 * 1024,
            host_commit_remaining_bytes: commit_remaining_bytes,
            host_page_size_bytes: 4096,
            total_foreign_private_commit_bytes: named_foreign_processes
                .iter()
                .map(|process| process.private_commit_bytes)
                .sum(),
            named_foreign_processes,
            excluded_kernel_pids: vec![0, 4],
            enumerated_process_count: 14,
            owned_process_count: 2,
            probe_complete: true,
            attribution_complete: true,
            total_foreign_private_commit_is_lower_bound: false,
            exited_processes: vec![],
            unreadable_processes: vec![],
            identity_conflicts: vec![],
        }
    }

    #[test]
    fn healthy_host_with_five_gib_foreign_process_is_observed_without_fence() {
        let five_gib = 5 * 1024 * 1024 * 1024;
        let census = ForeignProcessCensus {
            host_commit_total_bytes: 44 * 1024 * 1024 * 1024,
            host_commit_limit_bytes: 64 * 1024 * 1024 * 1024,
            host_commit_remaining_bytes: 20 * 1024 * 1024 * 1024,
            host_page_size_bytes: 4096,
            total_foreign_private_commit_bytes: five_gib,
            named_foreign_processes: vec![ForeignProcessIdentity {
                pid: 500,
                process_start_token: "00000000000001f4".into(),
                private_commit_bytes: five_gib,
                gpu_bytes: None,
                gpu_memory_unavailable_token: None,
                provider: None,
                candidate_classes: vec!["private_commit_attribution".into()],
                survived_end_probe: true,
            }],
            excluded_kernel_pids: vec![0, 4],
            enumerated_process_count: 3,
            owned_process_count: 0,
            probe_complete: true,
            attribution_complete: true,
            total_foreign_private_commit_is_lower_bound: false,
            exited_processes: vec![],
            unreadable_processes: vec![],
            identity_conflicts: vec![],
        };

        assert_eq!(
            foreign_pressure_transition(&census),
            ForeignPressureState::Observed
        );
    }

    #[test]
    fn host_floor_breach_fences_when_all_foreign_processes_are_below_attribution_cutoff() {
        let census = ForeignProcessCensus {
            host_commit_total_bytes: 55 * 1024 * 1024 * 1024,
            host_commit_limit_bytes: 64 * 1024 * 1024 * 1024,
            host_commit_remaining_bytes: 9 * 1024 * 1024 * 1024,
            host_page_size_bytes: 4096,
            total_foreign_private_commit_bytes: 42 * 1024 * 1024 * 1024,
            named_foreign_processes: vec![],
            excluded_kernel_pids: vec![0, 4],
            enumerated_process_count: 14,
            owned_process_count: 0,
            probe_complete: true,
            attribution_complete: true,
            total_foreign_private_commit_is_lower_bound: false,
            exited_processes: vec![],
            unreadable_processes: vec![],
            identity_conflicts: vec![],
        };

        assert_eq!(
            foreign_pressure_transition(&census),
            ForeignPressureState::Fenced
        );
    }

    #[test]
    fn host_commit_floor_is_inclusive_for_open_pressure_state() {
        let at_floor = ForeignProcessCensus {
            host_commit_total_bytes: 54 * 1024 * 1024 * 1024,
            host_commit_limit_bytes: 64 * 1024 * 1024 * 1024,
            host_commit_remaining_bytes: 10 * 1024 * 1024 * 1024,
            host_page_size_bytes: 4096,
            total_foreign_private_commit_bytes: 0,
            named_foreign_processes: vec![],
            excluded_kernel_pids: vec![0, 4],
            enumerated_process_count: 2,
            owned_process_count: 0,
            probe_complete: true,
            attribution_complete: true,
            total_foreign_private_commit_is_lower_bound: false,
            exited_processes: vec![],
            unreadable_processes: vec![],
            identity_conflicts: vec![],
        };
        let below_floor = ForeignProcessCensus {
            host_commit_remaining_bytes: at_floor.host_commit_remaining_bytes - 1,
            ..at_floor.clone()
        };

        assert_eq!(
            foreign_pressure_transition(&at_floor),
            ForeignPressureState::Clear
        );
        assert_eq!(
            foreign_pressure_transition(&below_floor),
            ForeignPressureState::Fenced
        );
    }

    #[test]
    fn census_probe_failure_maps_to_fail_closed_pressure_state() {
        let sample = Err(EmberLabError::InvalidDispatchManifest {
            detail: "process census incomplete".into(),
        });

        assert_eq!(
            foreign_pressure_state_from_sample(sample),
            ForeignPressureState::ProbeFailed
        );
    }

    #[test]
    fn persistence_transitions_probe_failed_observed_fenced_clear_without_clearing_sticky_guard() {
        let conn = pressure_test_connection();
        persist_foreign_process_census(
            &conn,
            10,
            Err(EmberLabError::InvalidDispatchManifest {
                detail: "synthetic census failure".into(),
            }),
        )
        .unwrap();
        assert_eq!(
            foreign_process_pressure_status_from_connection(&conn).unwrap()["state"],
            "probe_failed"
        );

        let named = ForeignProcessIdentity {
            pid: 500,
            process_start_token: "token-500".into(),
            private_commit_bytes: 5 * 1024 * 1024 * 1024,
            gpu_bytes: None,
            gpu_memory_unavailable_token: None,
            provider: None,
            candidate_classes: vec!["private_commit_attribution".into()],
            survived_end_probe: true,
        };
        persist_foreign_process_census(
            &conn,
            20,
            Ok(pressure_census(12 * 1024 * 1024 * 1024, vec![named])),
        )
        .unwrap();
        assert_eq!(
            foreign_process_pressure_status_from_connection(&conn).unwrap()["state"],
            "observed"
        );
        persist_foreign_process_census(
            &conn,
            30,
            Ok(pressure_census(9 * 1024 * 1024 * 1024, vec![])),
        )
        .unwrap();
        assert_eq!(
            foreign_process_pressure_status_from_connection(&conn).unwrap()["state"],
            "fenced"
        );
        persist_foreign_process_census(
            &conn,
            40,
            Ok(pressure_census(12 * 1024 * 1024 * 1024, vec![])),
        )
        .unwrap();
        let status = foreign_process_pressure_status_from_connection(&conn).unwrap();
        assert_eq!(status["state"], "clear");
        assert_eq!(
            status["effective_admission"]["resource_guard_state"],
            "frozen"
        );
        assert_eq!(status["effective_admission"]["admission_state"], "frozen");
    }

    #[test]
    fn foreign_pressure_observation_ledger_is_bounded() {
        let conn = pressure_test_connection();
        for observed_at_ms in 0..=FOREIGN_PRESSURE_OBSERVATION_LIMIT {
            persist_foreign_process_census(
                &conn,
                observed_at_ms,
                Ok(pressure_census(12 * 1024 * 1024 * 1024, vec![])),
            )
            .unwrap();
        }
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM foreign_process_pressure_observations",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, FOREIGN_PRESSURE_OBSERVATION_LIMIT);
    }
}

#[cfg(test)]
mod foreign_process_census_tests {
    use super::*;
    use std::collections::{BTreeMap, BTreeSet};

    const GIB: u64 = 1024 * 1024 * 1024;

    fn host() -> HostCommitSample {
        HostCommitSample {
            commit_total_bytes: 44 * GIB,
            commit_limit_bytes: 64 * GIB,
            commit_remaining_bytes: 20 * GIB,
            page_size_bytes: 4096,
        }
    }

    fn live(pid: u32, token: &str, private_commit_bytes: u64) -> ProcessCensusObservation {
        ProcessCensusObservation::Live(ProcessCommitSample {
            pid,
            process_start_token: token.into(),
            private_commit_bytes,
        })
    }

    #[test]
    fn gpu_pid_below_commit_cutoff_is_named() {
        let gpu = BTreeMap::from([(
            77,
            GpuComputeSample {
                bytes: Some(256 * 1024 * 1024),
                unavailable_token: None,
            },
        )]);
        let census =
            classify_foreign_samples(host(), vec![live(77, "aa", GIB)], &gpu, &BTreeSet::new())
                .unwrap();

        assert_eq!(census.named_foreign_processes.len(), 1);
        assert_eq!(
            census.named_foreign_processes[0].candidate_classes,
            vec!["gpu_compute"]
        );
    }

    #[test]
    fn nvidia_absent_memory_tokens_keep_gpu_context_pids_named_and_complete() {
        let gpu = parse_nvidia_compute_rows("2396, [N/A]\n7328, [n/a]\n7684, N/A\n").unwrap();
        assert_eq!(gpu.len(), 3);
        assert_eq!(gpu[&2396].bytes, None);
        assert_eq!(gpu[&2396].unavailable_token.as_deref(), Some("[N/A]"));

        let census = classify_foreign_samples(
            host(),
            vec![
                live(2396, "aa", GIB),
                live(7328, "bb", GIB),
                live(7684, "cc", GIB),
            ],
            &gpu,
            &BTreeSet::new(),
        )
        .unwrap();

        assert!(census.probe_complete);
        assert_eq!(census.named_foreign_processes.len(), 3);
        assert!(census.named_foreign_processes.iter().all(|process| {
            process.gpu_bytes.is_none()
                && process
                    .candidate_classes
                    .iter()
                    .any(|class| class == "gpu_compute")
        }));
    }

    #[test]
    fn owned_job_member_is_excluded_from_foreign_totals() {
        let owned = BTreeSet::from([(88, "bb".to_string())]);
        let census = classify_foreign_samples(
            host(),
            vec![live(88, "bb", 6 * GIB)],
            &BTreeMap::new(),
            &owned,
        )
        .unwrap();

        assert_eq!(census.total_foreign_private_commit_bytes, 0);
        assert!(census.named_foreign_processes.is_empty());
        assert_eq!(census.owned_process_count, 1);
    }

    #[test]
    fn many_subcutoff_foreign_processes_remain_visible_in_aggregate() {
        let observations = (100..112)
            .map(|pid| live(pid, &format!("token-{pid}"), 3 * GIB + GIB / 2))
            .collect();
        let census =
            classify_foreign_samples(host(), observations, &BTreeMap::new(), &BTreeSet::new())
                .unwrap();

        assert_eq!(census.total_foreign_private_commit_bytes, 42 * GIB);
        assert!(census.named_foreign_processes.is_empty());
    }

    #[test]
    fn foreign_private_commit_sum_overflow_fails_closed() {
        let result = classify_foreign_samples(
            host(),
            vec![live(201, "one", u64::MAX), live(202, "two", 1)],
            &BTreeMap::new(),
            &BTreeSet::new(),
        );

        assert!(matches!(
            foreign_pressure_state_from_sample(result),
            ForeignPressureState::ProbeFailed
        ));
    }

    #[test]
    fn exited_process_during_enumeration_keeps_census_complete() {
        let census = classify_foreign_samples(
            host(),
            vec![ProcessCensusObservation::Exited(ProcessExitObservation {
                pid: 301,
                phase: "enumeration".into(),
                win32_code: 87,
            })],
            &BTreeMap::new(),
            &BTreeSet::new(),
        )
        .unwrap();

        assert!(census.probe_complete);
        assert_eq!(census.total_foreign_private_commit_bytes, 0);
        assert_eq!(census.exited_processes[0].win32_code, 87);
    }

    #[test]
    fn denied_process_makes_attribution_a_lower_bound_but_does_not_fence_healthy_host() {
        let census = classify_foreign_samples(
            host(),
            vec![ProcessCensusObservation::Unreadable(ProcessReadFailure {
                pid: 302,
                phase: "enumeration".into(),
                win32_code: 5,
            })],
            &BTreeMap::new(),
            &BTreeSet::new(),
        )
        .unwrap();

        assert!(census.probe_complete);
        assert!(!census.attribution_complete);
        assert!(census.total_foreign_private_commit_is_lower_bound);
        assert_eq!(
            foreign_pressure_transition(&census),
            ForeignPressureState::Clear
        );
        assert_eq!(census.unreadable_processes[0].win32_code, 5);
    }

    #[test]
    fn named_process_exit_during_production_probe_is_recorded_and_dropped() {
        let census = classify_foreign_samples(
            host(),
            vec![ProcessCensusObservation::Exited(ProcessExitObservation {
                pid: 303,
                phase: "named_process_end_probe".into(),
                win32_code: 87,
            })],
            &BTreeMap::from([(
                303,
                GpuComputeSample {
                    bytes: Some(128 * 1024 * 1024),
                    unavailable_token: None,
                },
            )]),
            &BTreeSet::new(),
        )
        .unwrap();

        assert!(census.probe_complete);
        assert!(census.named_foreign_processes.is_empty());
        assert_eq!(census.exited_processes[0].phase, "named_process_end_probe");
    }

    #[test]
    fn named_pid_reuse_makes_attribution_incomplete_without_destroying_host_decision() {
        let census = classify_foreign_samples(
            host(),
            vec![ProcessCensusObservation::IdentityConflict(
                ProcessIdentityConflict {
                    pid: 304,
                    expected_start_token: "old".into(),
                    observed_start_token: "new".into(),
                    phase: "named_process_end_probe".into(),
                    win32_code: 0,
                },
            )],
            &BTreeMap::new(),
            &BTreeSet::new(),
        )
        .unwrap();

        assert!(census.probe_complete);
        assert!(!census.attribution_complete);
        assert!(census.total_foreign_private_commit_is_lower_bound);
        assert_eq!(census.identity_conflicts[0].expected_start_token, "old");
        assert_eq!(census.identity_conflicts[0].observed_start_token, "new");
    }

    #[cfg(windows)]
    #[test]
    fn foreign_process_open_mask_is_query_and_synchronize_only() {
        use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
        const SYNCHRONIZE_RIGHT: u32 = 0x0010_0000;

        assert_eq!(
            FOREIGN_PROCESS_OPEN_ACCESS_MASK,
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_RIGHT
        );
    }
}

#[cfg(all(test, windows))]
mod foreign_process_provider_integration_tests {
    use super::*;
    use std::os::windows::process::CommandExt;
    use std::process::{Command, Stdio};

    #[test]
    fn integration_foreign_fixture_survives_same_identity() {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let mut child = Command::new("cmd.exe")
            .args(["/d", "/s", "/c", "ping -n 20 127.0.0.1 >nul"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .unwrap();
        let pid = child.id();

        let result = (|| -> Result<()> {
            let start_token = process_start_token(pid)?;
            let (_, observations, _) = probe_windows_process_observations(&[])?;
            assert!(observations.iter().any(|observation| matches!(
                observation,
                ProcessCensusObservation::Live(sample)
                    if sample.pid == pid && sample.process_start_token == start_token
            )));

            let _census = sample_windows_foreign_process_census(&[])?;
            assert_eq!(process_start_token(pid)?, start_token);
            assert!(child.try_wait()?.is_none());
            Ok(())
        })();

        let _ = child.kill();
        let _ = child.wait();
        result.unwrap();
    }
}

#[cfg(test)]
mod foreign_pressure_probe_receipt_tests {
    use super::*;

    fn valid_receipt() -> Value {
        let observation = json!({
            "schema_version": "ember-lab-foreign-process-pressure-observation-v1",
            "result": "OBSERVED",
            "observed_at_ms": 100,
            "monitor_tier": "windows_process_private_commit_and_gpu_context",
            "host_commit_total_bytes": 44_u64 * 1024 * 1024 * 1024,
            "host_commit_limit_bytes": 64_u64 * 1024 * 1024 * 1024,
            "host_commit_remaining_bytes": 20_u64 * 1024 * 1024 * 1024,
            "host_page_size_bytes": 4096,
            "minimum_commit_remaining_bytes": RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES,
            "foreign_process_attribution_cutoff_bytes": FOREIGN_PROCESS_ATTRIBUTION_CUTOFF_BYTES,
            "total_foreign_private_commit_bytes": 5_u64 * 1024 * 1024 * 1024,
            "named_foreign_processes": [{
                "pid": 500,
                "process_start_token": "token-500",
                "private_commit_bytes": 5_u64 * 1024 * 1024 * 1024,
                "gpu_bytes": Value::Null,
                "gpu_memory_unavailable_token": Value::Null,
                "provider": Value::Null,
                "candidate_classes": ["private_commit_attribution"],
                "survived_end_probe": true,
            }],
            "excluded_kernel_pids": [0, 4],
            "enumerated_process_count": 3,
            "owned_process_count": 0,
            "probe_complete": true,
            "attribution_complete": true,
            "total_foreign_private_commit_is_lower_bound": false,
            "exited_processes": [],
            "unreadable_processes": [],
            "identity_conflicts": [],
            "counter_sources": {
                "host_commit": "GetPerformanceInfo.CommitLimit-CommitTotal",
                "process_private_commit": "K32GetProcessMemoryInfo.PROCESS_MEMORY_COUNTERS_EX.PrivateUsage",
                "gpu_compute_context": "nvidia-smi.query-compute-apps",
            },
            "foreign_process_control": false,
        });
        let observation_sha256 = hash_bytes(&serde_json::to_vec(&observation).unwrap());
        let mut receipt = json!({
            "schema_version": "ember-lab-foreign-process-pressure-probe-v1",
            "verdict": "EXECUTED",
            "state": "observed",
            "observed_at_ms": 100,
            "observation": observation,
            "observation_sha256": observation_sha256,
            "ember_lab_identity": {
                "binary_sha256": "a".repeat(64),
                "source_sha256": "b".repeat(64),
            },
            "foreign_process_control": false,
        });
        let self_hash = hash_bytes(&serde_json::to_vec(&receipt).unwrap());
        receipt
            .as_object_mut()
            .unwrap()
            .insert("receipt_sha256".into(), Value::String(self_hash));
        receipt
    }

    #[test]
    fn exact_verifier_accepts_bound_receipt_and_rejects_identity_aggregate_and_self_hash_tamper() {
        let receipt = valid_receipt();
        verify_foreign_process_pressure_probe_receipt(&serde_json::to_vec(&receipt).unwrap())
            .unwrap();

        let mut identity = receipt;
        identity["observation"]["named_foreign_processes"][0]["process_start_token"] =
            Value::String("token-reused".into());
        assert!(verify_foreign_process_pressure_probe_receipt(
            &serde_json::to_vec(&identity).unwrap()
        )
        .is_err());

        let mut aggregate = valid_receipt();
        aggregate["observation"]["total_foreign_private_commit_bytes"] =
            json!(4_u64 * 1024 * 1024 * 1024);
        assert!(verify_foreign_process_pressure_probe_receipt(
            &serde_json::to_vec(&aggregate).unwrap()
        )
        .is_err());

        let mut self_hash = valid_receipt();
        self_hash["receipt_sha256"] = Value::String("c".repeat(64));
        assert!(verify_foreign_process_pressure_probe_receipt(
            &serde_json::to_vec(&self_hash).unwrap()
        )
        .is_err());
    }
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

/// Delegates to `probe_host_commit_capacity()` rather than re-reading
/// `/proc/meminfo` a second time -- `HostSurvivalHeadroom` is exactly the
/// two live-headroom fields (`physical_available_bytes`,
/// `current_commit_remaining_bytes`) that probe already computes.
#[cfg(not(windows))]
fn probe_host_survival_headroom() -> Result<HostSurvivalHeadroom> {
    let capacity = probe_host_commit_capacity()?;
    Ok(HostSurvivalHeadroom {
        physical_available_bytes: capacity.physical_available_bytes,
        commit_remaining_bytes: capacity.current_commit_remaining_bytes,
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
/// Return the running jobs a survival-floor freeze should protectively stop.
///
/// Only `commit_remaining_below_survival_floor` and
/// `resource_guard_probe_failed` are host-SURVIVAL conditions: commit
/// exhaustion is what actually starves the host and has its own floor
/// (`RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES`); an unreadable probe means
/// the guard cannot see the host at all. A
/// `physical_available_below_survival_floor` freeze is an admission-quality
/// signal, not a survival one -- Windows pages a paging-heavy-but-healthy
/// workload under low physical availability and degrades gracefully; it
/// does not crash. Stopping a running job on a physical-only breach
/// destroys real run evidence (a live, otherwise-healthy training job) to
/// "protect" against a condition the host already handles on its own.
///
/// Receipted defect (#898, same-day amendment): the E8 dense A1 run was
/// protective-stopped at t+71s on `physical_available_below_survival_floor`
/// while `commit_remaining_bytes` stayed >= 35 GiB (floor 10 GiB) for the
/// entire trajectory -- the run was never in survival danger. A physical
/// breach still freezes ADMISSION (new dispatch is refused, and the sticky
/// freeze + oracle-evidence rearm protocol are unchanged); it must not stop
/// an already-running job.
#[cfg(windows)]
fn running_job_ids_for_protective_stop(conn: &Connection) -> Result<Vec<String>> {
    let status = resource_guard_status_from_connection(conn)?;
    if status.get("admission_state") != Some(&Value::String("frozen".into())) {
        return Ok(Vec::new());
    }
    let is_survival_breach = matches!(
        status.get("reason").and_then(Value::as_str),
        Some("commit_remaining_below_survival_floor") | Some("resource_guard_probe_failed")
    );
    if !is_survival_breach {
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
fn advance_vram_wall_debounce(
    contract: &VramWallContract,
    prior_observed_at_ms: i64,
    prior_consecutive: u32,
    prior_class: Option<&str>,
    observed_at_ms: i64,
    breach_class: Option<&str>,
) -> Result<(u32, bool)> {
    let mut adjacent = prior_observed_at_ms == 0;
    if prior_observed_at_ms > 0 {
        if observed_at_ms <= prior_observed_at_ms {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "persisted VRAM wall observation time is non-monotone".into(),
            });
        }
        let gap_ms = u64::try_from(observed_at_ms - prior_observed_at_ms).map_err(|_| {
            EmberLabError::InvalidDispatchManifest {
                detail: "persisted VRAM wall observation gap is invalid".into(),
            }
        })?;
        if gap_ms < contract.sample_interval_ms {
            return Err(EmberLabError::InvalidDispatchManifest {
                detail: "persisted VRAM wall observation arrived before its cadence".into(),
            });
        }
        adjacent = gap_ms <= contract.sample_interval_ms.saturating_mul(2);
    }
    let consecutive = match breach_class {
        Some(class) if adjacent && prior_class == Some(class) => {
            prior_consecutive.saturating_add(1)
        }
        Some(_) => 1,
        None => 0,
    };
    Ok((
        consecutive,
        breach_class.is_some() && consecutive >= contract.consecutive_breach_samples,
    ))
}

#[cfg(windows)]
struct VramWallObservationWrite<'a> {
    job_id: &'a str,
    contract: &'a VramWallContract,
    prior_observed_at_ms: i64,
    prior_consecutive: u32,
    prior_class: Option<&'a str>,
    observed_at_ms: i64,
    breach_class: Option<&'a str>,
    observation: Value,
}

#[cfg(windows)]
fn persist_vram_wall_observation(
    conn: &Connection,
    write: VramWallObservationWrite<'_>,
) -> Result<bool> {
    let VramWallObservationWrite {
        job_id,
        contract,
        prior_observed_at_ms,
        prior_consecutive,
        prior_class,
        observed_at_ms,
        breach_class,
        mut observation,
    } = write;
    let (consecutive, stop) = advance_vram_wall_debounce(
        contract,
        prior_observed_at_ms,
        prior_consecutive,
        prior_class,
        observed_at_ms,
        breach_class,
    )?;
    observation["active_breach_class"] = breach_class.map(Value::from).unwrap_or(Value::Null);
    observation["consecutive_observations"] = json!(consecutive);
    observation["required_observations"] = json!(contract.consecutive_breach_samples);
    observation["decision"] = json!(if stop {
        "PROTECTIVE_STOP"
    } else if breach_class.is_some() {
        "PENDING"
    } else {
        "HEALTHY"
    });
    let payload = serde_json::to_string(&observation)?;
    let tx = conn.unchecked_transaction()?;
    tx.execute(
        "INSERT INTO vram_wall_observations(job_id,observed_at_ms,outcome,payload_json) VALUES(?1,?2,?3,?4)",
        params![job_id, observed_at_ms, if stop { "protective_stop" } else if breach_class.is_some() { "pending" } else { "healthy" }, payload],
    )?;
    tx.execute(
        "UPDATE job_vram_walls SET consecutive_breach_observations=?2,active_breach_class=?3 WHERE job_id=?1",
        params![job_id, consecutive, breach_class],
    )?;
    if stop {
        // The durable observation row is inserted before authorization and
        // both become visible atomically; process control happens only after
        // this transaction commits and the exact job id is returned.
        tx.execute(
            "UPDATE resource_guard_state SET admission_state='frozen',reason='vram_wall_breach',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
            params![observed_at_ms, payload],
        )?;
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'vram_wall_protective_stop_authorized',?3)",
            params![job_id, observed_at_ms, payload],
        )?;
    }
    tx.execute(
        "DELETE FROM vram_wall_observations WHERE seq <= COALESCE((SELECT MAX(seq) FROM vram_wall_observations),0)-4096",
        [],
    )?;
    tx.commit()?;
    Ok(stop)
}

#[cfg(all(test, windows))]
mod vram_wall_debounce_tests {
    use super::*;

    fn contract() -> VramWallContract {
        VramWallContract {
            provider: "nvidia_smi_nvml".into(),
            device_uuid: "GPU-00000000-1111-2222-3333-444444444444".into(),
            maximum_process_fraction_millionths: 500_000,
            minimum_free_bytes: 1,
            consecutive_breach_samples: 3,
            sample_interval_ms: 2_000,
        }
    }

    #[test]
    fn persisted_debounce_requires_adjacent_monotone_observations() {
        let wall = contract();
        assert_eq!(
            advance_vram_wall_debounce(&wall, 0, 0, None, 1_000, Some("free_floor")).unwrap(),
            (1, false)
        );
        assert_eq!(
            advance_vram_wall_debounce(
                &wall,
                1_000,
                1,
                Some("free_floor"),
                3_000,
                Some("free_floor")
            )
            .unwrap(),
            (2, false)
        );
        assert_eq!(
            advance_vram_wall_debounce(
                &wall,
                3_000,
                2,
                Some("free_floor"),
                5_000,
                Some("free_floor")
            )
            .unwrap(),
            (3, true)
        );
        assert_eq!(
            advance_vram_wall_debounce(
                &wall,
                5_000,
                2,
                Some("free_floor"),
                20_000,
                Some("free_floor")
            )
            .unwrap(),
            (1, false),
            "a stale observation window resets instead of accumulating"
        );
        assert!(advance_vram_wall_debounce(
            &wall,
            5_000,
            2,
            Some("free_floor"),
            4_000,
            Some("free_floor")
        )
        .is_err());
    }

    #[test]
    fn third_bound_observation_is_durable_before_stop_authorization() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE job_vram_walls(job_id TEXT PRIMARY KEY, consecutive_breach_observations INTEGER NOT NULL, active_breach_class TEXT);
             CREATE TABLE vram_wall_observations(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, observed_at_ms INTEGER NOT NULL, outcome TEXT NOT NULL, payload_json TEXT NOT NULL);
             CREATE TABLE resource_guard_state(singleton INTEGER PRIMARY KEY, admission_state TEXT NOT NULL, reason TEXT, observed_at_ms INTEGER NOT NULL, oracle_evidence_required INTEGER NOT NULL, observation_json TEXT NOT NULL);
             CREATE TABLE events(job_id TEXT, ts_ms INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL);
             INSERT INTO job_vram_walls VALUES('owned-job',0,NULL);
             INSERT INTO resource_guard_state VALUES(1,'open',NULL,0,0,'{}');",
        )
        .unwrap();
        let wall = contract();
        let mut prior_at = 0;
        let mut prior_count = 0;
        for observed_at_ms in [1_000_i64, 3_000, 5_000] {
            let stop = persist_vram_wall_observation(
                &conn,
                VramWallObservationWrite {
                    job_id: "owned-job",
                    contract: &wall,
                    prior_observed_at_ms: prior_at,
                    prior_consecutive: prior_count,
                    prior_class: if prior_count == 0 {
                        None
                    } else {
                        Some("free_floor")
                    },
                    observed_at_ms,
                    breach_class: Some("free_floor"),
                    observation: json!({
                        "schema_version":"ember-lab-vram-wall-observation-v1",
                        "job_id":"owned-job",
                        "pid":4242,
                        "process_start_token":"bound-start-token",
                        "foreign_process_control":false,
                    }),
                },
            )
            .unwrap();
            prior_at = observed_at_ms;
            prior_count += 1;
            assert_eq!(stop, prior_count == 3);
        }
        let state: (String, Option<String>, String) = conn
            .query_row(
                "SELECT admission_state,reason,observation_json FROM resource_guard_state WHERE singleton=1",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(state.0, "frozen");
        assert_eq!(state.1.as_deref(), Some("vram_wall_breach"));
        assert_eq!(
            serde_json::from_str::<Value>(&state.2).unwrap()["decision"],
            "PROTECTIVE_STOP"
        );
        let observations: i64 = conn
            .query_row("SELECT COUNT(*) FROM vram_wall_observations", [], |row| {
                row.get(0)
            })
            .unwrap();
        let authorizations: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM events WHERE kind='vram_wall_protective_stop_authorized'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(observations, 3);
        assert_eq!(authorizations, 1);
    }
}

#[cfg(windows)]
fn sample_owned_vram_walls(
    db: &Arc<Mutex<Connection>>,
    live: &Arc<Mutex<HashMap<String, RetainedProcess>>>,
) -> Result<Vec<String>> {
    let rows = {
        let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
        let mut statement = conn.prepare(
            "SELECT j.job_id,j.pid,j.process_start_token,w.contract_json,w.maximum_process_vram_bytes,w.consecutive_breach_observations,w.active_breach_class,
                    COALESCE((SELECT MAX(observed_at_ms) FROM vram_wall_observations o WHERE o.job_id=j.job_id),0)
             FROM jobs j JOIN job_vram_walls w ON w.job_id=j.job_id
             WHERE j.state='running' ORDER BY j.job_id",
        )?;
        let collected = statement
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, u32>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, i64>(4)?,
                    row.get::<_, u32>(5)?,
                    row.get::<_, Option<String>>(6)?,
                    row.get::<_, i64>(7)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        collected
    };
    let mut protective_stops = Vec::new();
    for (
        job_id,
        pid,
        start_token,
        contract_json,
        maximum_process_vram_bytes,
        prior_consecutive,
        prior_class,
        last_observed_at_ms,
    ) in rows
    {
        let contract: VramWallContract = serde_json::from_str(&contract_json).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("persisted VRAM wall contract is invalid: {error}"),
            }
        })?;
        validate_vram_wall_contract(&contract)?;
        let observed_at_ms = now_ms();
        if last_observed_at_ms > 0
            && observed_at_ms > last_observed_at_ms
            && observed_at_ms.saturating_sub(last_observed_at_ms)
                < i64::try_from(contract.sample_interval_ms).unwrap_or(i64::MAX)
        {
            continue;
        }
        let identity_matches = {
            let retained = live.lock().map_err(|_| EmberLabError::Poisoned)?;
            retained
                .get(&job_id)
                .map(|entry| {
                    entry.live.pid == pid && entry.live.identity.start_token == start_token
                })
                .unwrap_or(false)
        };
        if !identity_matches {
            let observation = json!({
                "schema_version":"ember-lab-vram-wall-observation-v1",
                "result":"IDENTITY_CONFLICT_REFUSED",
                "job_id":job_id,
                "pid":pid,
                "process_start_token":start_token,
                "provider":contract.provider,
                "device_uuid":contract.device_uuid,
                "foreign_process_control":false,
            });
            let payload = serde_json::to_string(&observation)?;
            let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
            let tx = conn.unchecked_transaction()?;
            tx.execute(
                "INSERT INTO vram_wall_observations(job_id,observed_at_ms,outcome,payload_json) VALUES(?1,?2,'identity_conflict_refused',?3)",
                params![job_id, observed_at_ms, payload],
            )?;
            tx.execute(
                "UPDATE resource_guard_state SET admission_state='frozen',reason='vram_wall_identity_conflict',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
                params![observed_at_ms, payload],
            )?;
            tx.commit()?;
            continue;
        }

        let sampled = (|| -> Result<(VramDeviceCapacity, u64)> {
            let capacity = probe_vram_device_capacity(&contract)?;
            let used_bytes = probe_process_vram_bytes(pid, &contract.device_uuid)?;
            Ok((capacity, used_bytes))
        })();
        let (breach_class, observation) = match sampled {
            Ok((capacity, used_bytes)) => {
                let class = if capacity.free_bytes < contract.minimum_free_bytes {
                    Some("free_floor")
                } else if used_bytes > u64::try_from(maximum_process_vram_bytes).unwrap_or(0) {
                    Some("process_fraction")
                } else {
                    None
                };
                (
                    class,
                    json!({
                        "schema_version":"ember-lab-vram-wall-observation-v1",
                        "result":if class.is_some() { "BREACH_OBSERVED" } else { "HEALTHY" },
                        "observed_at_ms":observed_at_ms,
                        "job_id":job_id,
                        "pid":pid,
                        "process_start_token":start_token,
                        "provider":capacity.provider,
                        "device_uuid":capacity.device_uuid,
                        "total_bytes":capacity.total_bytes,
                        "available_free_bytes":capacity.free_bytes,
                        "minimum_free_bytes":contract.minimum_free_bytes,
                        "used_process_bytes":used_bytes,
                        "maximum_process_vram_bytes":maximum_process_vram_bytes,
                        "maximum_process_fraction_millionths":contract.maximum_process_fraction_millionths,
                        "consecutive_breach_samples":contract.consecutive_breach_samples,
                        "sample_interval_ms":contract.sample_interval_ms,
                        "claim_boundary":"torch_allocator_fraction_plus_load_bearing_external_sentinel_not_total_vram_guarantee",
                        "foreign_process_control":false,
                    }),
                )
            }
            Err(error) => (
                Some("provider_unavailable"),
                json!({
                    "schema_version":"ember-lab-vram-wall-observation-v1",
                    "result":"PROVIDER_UNAVAILABLE",
                    "observed_at_ms":observed_at_ms,
                    "job_id":job_id,
                    "pid":pid,
                    "process_start_token":start_token,
                    "provider":contract.provider,
                    "device_uuid":contract.device_uuid,
                    "error":error.to_string(),
                    "consecutive_breach_samples":contract.consecutive_breach_samples,
                    "sample_interval_ms":contract.sample_interval_ms,
                    "foreign_process_control":false,
                }),
            ),
        };
        let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
        let stop = persist_vram_wall_observation(
            &conn,
            VramWallObservationWrite {
                job_id: &job_id,
                contract: &contract,
                prior_observed_at_ms: last_observed_at_ms,
                prior_consecutive,
                prior_class: prior_class.as_deref(),
                observed_at_ms,
                breach_class,
                observation,
            },
        )?;
        if stop {
            protective_stops.push(job_id);
        }
    }
    Ok(protective_stops)
}

#[cfg(windows)]
fn disk_wall_duration_miss_transition(prior_misses: u32) -> (u32, bool) {
    let misses = prior_misses.saturating_add(1);
    (misses, misses >= 3)
}

#[cfg(windows)]
fn disk_wall_error_authorizes_protective_stop(error: &EmberLabError) -> bool {
    !matches!(error, EmberLabError::DiskWallMeasurementDuration { .. })
}

#[cfg(windows)]
fn sample_owned_disk_walls(
    db: &Arc<Mutex<Connection>>,
    live: &Arc<Mutex<HashMap<String, RetainedProcess>>>,
) -> Result<Vec<String>> {
    type DiskWallRow = (String, u32, String, String, String, i64, u32);
    let rows: Vec<DiskWallRow> = {
        let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
        let mut statement = conn.prepare(
            "SELECT j.job_id,j.pid,j.process_start_token,w.write_root,w.contract_json,w.baseline_tree_bytes,w.consecutive_duration_misses
             FROM jobs j JOIN job_disk_walls w ON w.job_id=j.job_id
             WHERE j.state='running' ORDER BY j.job_id,w.write_root",
        )?;
        let collected = statement
            .query_map([], |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        collected
    };
    if rows.is_empty() {
        return Ok(Vec::new());
    }
    let observed_at_ms = now_ms();
    let mut contracts = Vec::with_capacity(rows.len());
    let mut volume_floors = BTreeMap::<PathBuf, (u64, String)>::new();
    for row in &rows {
        let contract: DiskWriteWallContract = serde_json::from_str(&row.4).map_err(|error| {
            EmberLabError::InvalidDispatchManifest {
                detail: format!("persisted disk wall contract is invalid: {error}"),
            }
        })?;
        validate_disk_write_wall_contract(&contract)?;
        if !volume_floors.contains_key(&contract.volume_root) {
            let available_free_bytes = available_free_bytes(&contract.volume_root)?;
            let payload = json!({
                "schema_version":"ember-lab-disk-volume-floor-observation-v1",
                "observed_at_ms":observed_at_ms,
                "volume_root":contract.volume_root,
                "available_free_bytes":available_free_bytes,
                "observation_scope":"one_per_volume_per_tick",
                "foreign_write_attribution":false,
            });
            let payload_bytes = serde_json::to_vec(&payload)?;
            let payload_sha256 = hash_bytes(&payload_bytes);
            let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
            conn.execute(
                "INSERT INTO disk_volume_floor_observations(observed_at_ms,volume_root,available_free_bytes,payload_json) VALUES(?1,?2,?3,?4)",
                params![
                    observed_at_ms,
                    contract.volume_root.to_string_lossy(),
                    i64::try_from(available_free_bytes).map_err(|_| EmberLabError::InvalidDispatchManifest { detail: "disk volume free bytes exceed the durable integer range".into() })?,
                    String::from_utf8(payload_bytes).map_err(|error| EmberLabError::InvalidDispatchManifest { detail: format!("disk floor receipt encoding failed: {error}") })?,
                ],
            )?;
            volume_floors.insert(
                contract.volume_root.clone(),
                (available_free_bytes, payload_sha256),
            );
        }
        contracts.push(contract);
    }

    let mut protective_stops = Vec::new();
    for (row, contract) in rows.into_iter().zip(contracts) {
        let (job_id, pid, start_token, write_root, _, baseline_tree_bytes, prior_misses) = row;
        let identity_matches = {
            let retained = live.lock().map_err(|_| EmberLabError::Poisoned)?;
            retained
                .get(&job_id)
                .map(|entry| {
                    entry.live.pid == pid && entry.live.identity.start_token == start_token
                })
                .unwrap_or(false)
        };
        if !identity_matches {
            let payload = json!({
                "schema_version":"ember-lab-disk-wall-observation-v1",
                "result":"IDENTITY_CONFLICT_REFUSED",
                "job_id":job_id,
                "pid":pid,
                "process_start_token":start_token,
                "write_root":write_root,
                "foreign_process_control":false,
            })
            .to_string();
            let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
            let tx = conn.unchecked_transaction()?;
            tx.execute(
                "INSERT INTO disk_wall_observations(job_id,write_root,observed_at_ms,outcome,payload_json) VALUES(?1,?2,?3,'identity_conflict_refused',?4)",
                params![job_id, write_root, observed_at_ms, payload],
            )?;
            tx.execute(
                "UPDATE resource_guard_state SET admission_state='frozen',reason='disk_wall_identity_conflict',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
                params![observed_at_ms, payload],
            )?;
            tx.commit()?;
            continue;
        }
        let (available_free_bytes, floor_receipt_sha256) = volume_floors
            .get(&contract.volume_root)
            .cloned()
            .ok_or_else(|| EmberLabError::InvalidDispatchManifest {
                detail: "disk wall lost its per-volume floor observation".into(),
            })?;
        let baseline_tree_bytes = u64::try_from(baseline_tree_bytes).map_err(|_| {
            EmberLabError::InvalidDispatchManifest {
                detail: "persisted disk wall baseline is negative".into(),
            }
        })?;
        let sampled = measure_disk_write_wall_sample_with_available_free(
            &contract,
            baseline_tree_bytes,
            observed_at_ms,
            available_free_bytes,
        )
        .and_then(|sample| {
            let decision = evaluate_disk_write_wall(&contract, &sample)?;
            Ok((sample, decision))
        });
        let (outcome, stop, next_misses, payload) = match sampled {
            Err(EmberLabError::DiskWallMeasurementDuration {
                elapsed_ms,
                maximum_ms,
            }) => {
                let (misses, frozen) = disk_wall_duration_miss_transition(prior_misses);
                (
                    if frozen {
                        "monitor_fail_frozen"
                    } else {
                        "duration_miss_pending"
                    },
                    false,
                    misses,
                    json!({
                        "schema_version":"ember-lab-disk-wall-observation-v1",
                        "result":if frozen { "MONITOR_FAIL_FROZEN" } else { "DURATION_MISS_PENDING" },
                        "job_id":job_id,
                        "pid":pid,
                        "process_start_token":start_token,
                        "write_root":contract.write_root,
                        "elapsed_ms":elapsed_ms,
                        "maximum_ms":maximum_ms,
                        "consecutive_duration_misses":misses,
                        "required_duration_misses":3,
                        "owned_stop_authorized":false,
                        "foreign_process_control":false,
                    }),
                )
            }
            Err(error) => {
                debug_assert!(disk_wall_error_authorizes_protective_stop(&error));
                (
                    "protective_stop",
                    true,
                    0,
                    json!({
                    "schema_version":"ember-lab-disk-wall-observation-v1",
                    "result":"PROTECTIVE_STOP",
                    "breach_class":"contract_integrity",
                    "job_id":job_id,
                    "pid":pid,
                    "process_start_token":start_token,
                    "write_root":contract.write_root,
                    "error":error.to_string(),
                    "volume_floor_receipt_sha256":floor_receipt_sha256,
                    "owned_stop_authorized":true,
                    "foreign_process_control":false,
                    }),
                )
            }
            Ok((sample, decision)) => {
                let (stop, breach_class) = match decision {
                    DiskWallDecision::Healthy { .. } => (false, Value::Null),
                    DiskWallDecision::ProtectiveStop { breach_class, .. } => {
                        (true, json!(breach_class))
                    }
                };
                (
                    if stop { "protective_stop" } else { "healthy" },
                    stop,
                    0,
                    json!({
                        "schema_version":"ember-lab-disk-wall-observation-v1",
                        "result":if stop { "PROTECTIVE_STOP" } else { "HEALTHY" },
                        "breach_class":breach_class,
                        "job_id":job_id,
                        "pid":pid,
                        "process_start_token":start_token,
                        "volume_root":contract.volume_root,
                        "write_root":contract.write_root,
                        "baseline_tree_bytes":sample.baseline_tree_bytes,
                        "current_tree_bytes":sample.current_tree_bytes,
                        "growth_bytes":sample.current_tree_bytes - sample.baseline_tree_bytes,
                        "maximum_write_bytes":contract.maximum_write_bytes,
                        "minimum_free_bytes":contract.minimum_free_bytes,
                        "measurement_duration_ms":sample.measurement_duration_ms,
                        "maximum_measurement_duration_ms":contract.maximum_measurement_duration_ms,
                        "volume_floor_receipt_sha256":floor_receipt_sha256,
                        "claim_boundary":"immutable_named_root_growth_plus_per_volume_survival_floor_not_os_wide_write_quota",
                        "race_surface":"mid_walk_mutation_refuses_or_misses_deadline_fail_closed",
                        "owned_stop_authorized":stop,
                        "foreign_process_control":false,
                    }),
                )
            }
        };
        let payload = serde_json::to_string(&payload)?;
        let conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
        let tx = conn.unchecked_transaction()?;
        tx.execute(
            "INSERT INTO disk_wall_observations(job_id,write_root,observed_at_ms,outcome,payload_json) VALUES(?1,?2,?3,?4,?5)",
            params![job_id, write_root, observed_at_ms, outcome, payload],
        )?;
        tx.execute(
            "UPDATE job_disk_walls SET consecutive_duration_misses=?3 WHERE job_id=?1 AND write_root=?2",
            params![job_id, write_root, next_misses],
        )?;
        if outcome == "monitor_fail_frozen" {
            tx.execute(
                "UPDATE resource_guard_state SET admission_state='frozen',reason='disk_wall_measurement_unavailable',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
                params![observed_at_ms, payload],
            )?;
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'disk_wall_monitor_fail_frozen',?3)",
                params![job_id, observed_at_ms, payload],
            )?;
        } else if stop {
            tx.execute(
                "UPDATE resource_guard_state SET admission_state='frozen',reason='disk_wall_breach',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
                params![observed_at_ms, payload],
            )?;
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'disk_wall_protective_stop_authorized',?3)",
                params![job_id, observed_at_ms, payload],
            )?;
        }
        tx.execute(
            "DELETE FROM disk_wall_observations WHERE seq <= COALESCE((SELECT MAX(seq) FROM disk_wall_observations),0)-4096",
            [],
        )?;
        tx.execute(
            "DELETE FROM disk_volume_floor_observations WHERE seq <= COALESCE((SELECT MAX(seq) FROM disk_volume_floor_observations),0)-2048",
            [],
        )?;
        tx.commit()?;
        if stop {
            protective_stops.push(job_id);
        }
    }
    Ok(protective_stops)
}

#[cfg(all(test, windows))]
mod disk_wall_monitor_policy_tests {
    use super::*;

    fn contract() -> DiskWriteWallContract {
        DiskWriteWallContract {
            volume_root: PathBuf::from(r"B:\"),
            write_root: PathBuf::from(r"B:\ember-custody\run-898"),
            maximum_write_bytes: 100,
            minimum_free_bytes: 1,
            sample_interval_ms: DISK_WALL_SAMPLE_INTERVAL_MS,
            maximum_measurement_duration_ms: DISK_WALL_MAXIMUM_MEASUREMENT_DURATION_MS,
        }
    }

    #[test]
    fn duration_miss_waits_for_third_sample_and_never_authorizes_a_stop() {
        assert_eq!(disk_wall_duration_miss_transition(0), (1, false));
        assert_eq!(disk_wall_duration_miss_transition(1), (2, false));
        assert_eq!(disk_wall_duration_miss_transition(2), (3, true));
        assert_eq!(
            disk_wall_duration_miss_transition(u32::MAX),
            (u32::MAX, true)
        );
    }

    #[test]
    fn named_root_shrink_enters_the_non_duration_protective_stop_arm() {
        let sample = DiskWriteWallSample {
            observed_at_ms: 10_000,
            baseline_tree_bytes: 100,
            current_tree_bytes: 99,
            available_free_bytes: 1,
            measurement_duration_ms: 1,
        };
        let error = evaluate_disk_write_wall(&contract(), &sample).unwrap_err();
        assert!(disk_wall_error_authorizes_protective_stop(&error));
    }
}

#[cfg(windows)]
fn spawn_resource_guard_monitor(
    db: Weak<Mutex<Connection>>,
    live: Weak<Mutex<HashMap<String, RetainedProcess>>>,
    log_dir: PathBuf,
    shutdown: OwnedHandle,
    ownership: Weak<RwLock<bool>>,
    foreign_process_provider: Arc<dyn ForeignProcessCensusProvider>,
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
                let owned_jobs = {
                    let Ok(conn) = db.lock() else {
                        break;
                    };
                    owned_job_identities_from_connection(&conn)
                };
                let observed_at_ms = now_ms();
                let foreign_process_census = owned_jobs.and_then(|owned_jobs| {
                    sample_foreign_process_census(
                        foreign_process_provider.as_ref(),
                        &owned_jobs,
                    )
                });
                let mut job_ids = {
                    let Ok(conn) = db.lock() else {
                        break;
                    };
                    let resource_guard_result = persist_resource_guard_headroom(
                        &conn,
                        observed_at_ms,
                        probe_host_survival_headroom(),
                    );
                    let foreign_pressure_result = persist_foreign_process_census(
                        &conn,
                        observed_at_ms,
                        foreign_process_census,
                    );
                    if resource_guard_result.is_err() || foreign_pressure_result.is_err() {
                        Vec::new()
                    } else {
                        running_job_ids_for_protective_stop(&conn).unwrap_or_default()
                    }
                };
                let Some(live) = live.upgrade() else {
                    break;
                };
                match sample_owned_vram_walls(&db, &live) {
                    Ok(mut vram_job_ids) => job_ids.append(&mut vram_job_ids),
                    Err(error) => {
                        if let Ok(conn) = db.lock() {
                            let observed_at_ms = now_ms();
                            let payload = json!({
                                "schema_version":"ember-lab-vram-wall-monitor-failure-v1",
                                "error":error.to_string(),
                                "foreign_process_control":false,
                            })
                            .to_string();
                            let _ = conn.execute(
                                "UPDATE resource_guard_state SET admission_state='frozen',reason='vram_wall_monitor_failed',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
                                params![observed_at_ms, payload],
                            );
                            let _ = conn.execute(
                                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(NULL,?1,'vram_wall_monitor_failed',?2)",
                                params![observed_at_ms, payload],
                            );
                        }
                    }
                }
                match sample_owned_disk_walls(&db, &live) {
                    Ok(mut disk_job_ids) => job_ids.append(&mut disk_job_ids),
                    Err(error) => {
                        if let Ok(conn) = db.lock() {
                            let observed_at_ms = now_ms();
                            let payload = json!({
                                "schema_version":"ember-lab-disk-wall-monitor-failure-v1",
                                "error":error.to_string(),
                                "foreign_process_control":false,
                            })
                            .to_string();
                            let _ = conn.execute(
                                "UPDATE resource_guard_state SET admission_state='frozen',reason='disk_wall_monitor_failed',observed_at_ms=?1,oracle_evidence_required=1,observation_json=?2 WHERE singleton=1",
                                params![observed_at_ms, payload],
                            );
                            let _ = conn.execute(
                                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(NULL,?1,'disk_wall_monitor_failed',?2)",
                                params![observed_at_ms, payload],
                            );
                        }
                    }
                }
                job_ids.sort();
                job_ids.dedup();
                if job_ids.is_empty() {
                    continue;
                }
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
    completion_port: OwnedHandle,
    process: OwnedHandle,
    thread: OwnedHandle,
    stdout_log_guard: OwnedHandle,
    stderr_log_guard: OwnedHandle,
    pid: u32,
    main_thread_id: u32,
    identity: ProcessIdentity,
    applied_cpu_rate: Option<u32>,
    job_memory_contract: JobMemoryContract,
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
    fn applied_cpu_rate(&self) -> Option<u32> {
        self.applied_cpu_rate
    }
    fn stdout_child_handle(&self) -> i64 {
        self.stdout_log_guard.raw() as isize as i64
    }
    fn stderr_child_handle(&self) -> i64 {
        self.stderr_log_guard.raw() as isize as i64
    }
    /// Raw job-object handle, borrowed for the window-contract census
    /// (`IsProcessInJob`) -- ownership stays with `self.job`.
    fn job_handle(&self) -> windows_sys::Win32::Foundation::HANDLE {
        self.job.raw()
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
            completion_port: self.completion_port,
            process: self.process,
            _stdout_log_guard: self.stdout_log_guard,
            _stderr_log_guard: self.stderr_log_guard,
            pid: self.pid,
            identity: self.identity,
            job_memory_contract: self.job_memory_contract,
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

/// A snapshot of every visible top-level window on the desktop, as
/// (HWND-as-isize, owning PID) pairs. `HWND` is not `Send`; it is carried
/// as `isize` between the enumeration callback and the caller, and cast
/// back to `HWND` only at the point of a further Win32 call.
#[cfg(windows)]
type WindowCensus = Vec<(isize, u32)>;

/// Enumerate every visible top-level window system-wide (issue #898 L6:
/// window contract). This is a plain `EnumWindows`/`IsWindowVisible`
/// census, not the COM `IUIAutomation` subsystem -- issue #898's own
/// resolution ("no standing UIA subsystem required") calls for exactly
/// this weight class: a before/after snapshot, not a live automation tree.
#[cfg(windows)]
fn census_top_level_windows() -> WindowCensus {
    use windows_sys::Win32::Foundation::{BOOL, HWND, LPARAM};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetWindowThreadProcessId, IsWindowVisible,
    };

    unsafe extern "system" fn collect(hwnd: HWND, state: LPARAM) -> BOOL {
        if IsWindowVisible(hwnd) == 0 {
            return 1;
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, &mut pid);
        let windows = &mut *(state as *mut WindowCensus);
        windows.push((hwnd as isize, pid));
        1
    }

    let mut windows: WindowCensus = Vec::new();
    unsafe {
        EnumWindows(Some(collect), std::ptr::addr_of_mut!(windows) as LPARAM);
    }
    windows
}

/// A window-contract violation, carrying enough to debug a real one after
/// the fact -- the offending window is gone by the time anyone reads the
/// refusal (the job is terminated as part of the same fail-closed path),
/// so this is captured at detection time, not re-queryable later.
#[cfg(windows)]
struct ViolatingWindow {
    hwnd: isize,
    pid: u32,
    class_name: String,
    title: String,
}

#[cfg(windows)]
impl fmt::Display for ViolatingWindow {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "hwnd=0x{:x} pid={} class={:?} title={:?}",
            self.hwnd, self.pid, self.class_name, self.title
        )
    }
}

/// `GetWindowTextW`/`GetClassNameW` into an owned `String`, best-effort:
/// an empty result (no text, or the call fails) is a legitimate outcome for
/// plenty of real windows and is not itself part of the violation signal,
/// so failures here never suppress the detection this exists to debug.
#[cfg(windows)]
fn window_text_best_effort(
    hwnd: windows_sys::Win32::Foundation::HWND,
    call: unsafe extern "system" fn(windows_sys::Win32::Foundation::HWND, *mut u16, i32) -> i32,
) -> String {
    let mut buffer = [0u16; 256];
    let length = unsafe { call(hwnd, buffer.as_mut_ptr(), buffer.len() as i32) };
    if length <= 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buffer[..length as usize])
}

/// Windows present in `after` but not `before`, filtered to only those
/// owned by a process that is a member of `job` (`IsProcessInJob` --
/// covers the job's own process and any child it spawned, since jobs
/// inherit down the process tree by construction here). A window that is
/// new but belongs to an unrelated, pre-existing process on the desktop
/// (not this spawn's job) is not a contract violation and is excluded.
#[cfg(windows)]
fn new_windows_owned_by_job(
    before: &WindowCensus,
    after: &WindowCensus,
    job: windows_sys::Win32::Foundation::HANDLE,
) -> Vec<ViolatingWindow> {
    use windows_sys::Win32::Foundation::{CloseHandle, BOOL};
    use windows_sys::Win32::System::JobObjects::IsProcessInJob;
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION};
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetClassNameW, GetWindowTextW};

    let previously_seen: std::collections::HashSet<isize> =
        before.iter().map(|(hwnd, _)| *hwnd).collect();
    let mut owned = Vec::new();
    for (hwnd, pid) in after {
        if previously_seen.contains(hwnd) {
            continue;
        }
        let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, *pid) };
        if process.is_null() {
            continue;
        }
        let mut in_job: BOOL = 0;
        let queried = unsafe { IsProcessInJob(process, job, &mut in_job) };
        unsafe { CloseHandle(process) };
        if queried != 0 && in_job != 0 {
            let raw_hwnd = *hwnd as windows_sys::Win32::Foundation::HWND;
            owned.push(ViolatingWindow {
                hwnd: *hwnd,
                pid: *pid,
                class_name: window_text_best_effort(raw_hwnd, GetClassNameW),
                title: window_text_best_effort(raw_hwnd, GetWindowTextW),
            });
        }
    }
    owned
}

/// Poll for a window contract violation for up to `budget` after the
/// spawn's resume, checking every `interval`. Bounded, not instantaneous:
/// a window's creation is scheduled by the OS on the child's own thread,
/// so this is a receipted best-effort census, not a synchronous guarantee.
/// Returns any job-owned windows found; empty means no violation was
/// observed within the budget.
#[cfg(windows)]
fn poll_for_new_job_owned_windows(
    before: &WindowCensus,
    job: windows_sys::Win32::Foundation::HANDLE,
    budget: Duration,
    interval: Duration,
) -> Vec<ViolatingWindow> {
    let deadline = Instant::now() + budget;
    loop {
        let after = census_top_level_windows();
        let found = new_windows_owned_by_job(before, &after, job);
        if !found.is_empty() || Instant::now() >= deadline {
            return found;
        }
        std::thread::sleep(interval);
    }
}

#[cfg(test)]
mod window_census_budget_tests {
    use super::*;

    #[test]
    fn production_default_window_census_budget_is_unchanged_at_200ms() {
        // Issue #898 L6 / #1727 round 3: the census budget became
        // injectable so a test could widen it without racing production
        // admission timing. This pins the production default itself so a
        // future edit cannot silently loosen (or tighten) the real
        // admission-time budget while only touching the injectable path.
        assert_eq!(DEFAULT_WINDOW_CENSUS_BUDGET, Duration::from_millis(200));
    }
}

/// The full Windows/UI job-object restriction set (issue #898) applied to
/// every spawned job that has not declared `requires_ui_responsiveness`.
/// Bars cross-desktop UI surfaces: USER handles owned outside the job, the
/// shared clipboard (read and write), global system parameters, display
/// settings, global atoms, desktop creation/switching, and ExitWindows.
#[cfg(windows)]
fn managed_windows_ui_restrictions_all() -> u32 {
    use windows_sys::Win32::System::JobObjects::{
        JOB_OBJECT_UILIMIT_DESKTOP, JOB_OBJECT_UILIMIT_DISPLAYSETTINGS,
        JOB_OBJECT_UILIMIT_EXITWINDOWS, JOB_OBJECT_UILIMIT_GLOBALATOMS, JOB_OBJECT_UILIMIT_HANDLES,
        JOB_OBJECT_UILIMIT_READCLIPBOARD, JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS,
        JOB_OBJECT_UILIMIT_WRITECLIPBOARD,
    };

    JOB_OBJECT_UILIMIT_HANDLES
        | JOB_OBJECT_UILIMIT_READCLIPBOARD
        | JOB_OBJECT_UILIMIT_WRITECLIPBOARD
        | JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS
        | JOB_OBJECT_UILIMIT_DISPLAYSETTINGS
        | JOB_OBJECT_UILIMIT_GLOBALATOMS
        | JOB_OBJECT_UILIMIT_DESKTOP
        | JOB_OBJECT_UILIMIT_EXITWINDOWS
}

/// Applies the Windows job-object CPU hard cap. This is the host's blanket
/// defense-in-depth cap: it runs for every managed spawn, whatever pacing
/// class was declared, and a failure here fails the spawn.
#[cfg(windows)]
fn set_windows_cpu_rate(job: windows_sys::Win32::Foundation::HANDLE, percent: u32) -> Result<u32> {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::System::JobObjects::{
        JobObjectCpuRateControlInformation, SetInformationJobObject,
        JOBOBJECT_CPU_RATE_CONTROL_INFORMATION, JOB_OBJECT_CPU_RATE_CONTROL_ENABLE,
        JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    };

    if !(1..=100).contains(&percent) {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "cpu_rate_percent must be between 1 and 100".into(),
        });
    }
    let expected_rate = percent * 100;
    let mut configured: JOBOBJECT_CPU_RATE_CONTROL_INFORMATION = unsafe { zeroed() };
    configured.ControlFlags =
        JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP;
    configured.Anonymous.CpuRate = expected_rate;
    if unsafe {
        SetInformationJobObject(
            job,
            JobObjectCpuRateControlInformation,
            (&configured as *const JOBOBJECT_CPU_RATE_CONTROL_INFORMATION).cast(),
            size_of::<JOBOBJECT_CPU_RATE_CONTROL_INFORMATION>() as u32,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(expected_rate)
}

/// Applies the cap, then re-reads it back off the job object and refuses the
/// spawn unless the kernel reports exactly what was requested. This is the
/// extra proof a `Governed` pacing contract earns; `Unpaced` spawns get the
/// cap from [`set_windows_cpu_rate`] without this reopen.
#[cfg(windows)]
fn configure_and_verify_windows_cpu_rate(
    job: windows_sys::Win32::Foundation::HANDLE,
    percent: u32,
) -> Result<u32> {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::System::JobObjects::{
        JobObjectCpuRateControlInformation, QueryInformationJobObject,
        JOBOBJECT_CPU_RATE_CONTROL_INFORMATION, JOB_OBJECT_CPU_RATE_CONTROL_ENABLE,
        JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    };

    let expected_rate = set_windows_cpu_rate(job, percent)?;
    let expected_flags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP;
    let mut reopened: JOBOBJECT_CPU_RATE_CONTROL_INFORMATION = unsafe { zeroed() };
    if unsafe {
        QueryInformationJobObject(
            job,
            JobObjectCpuRateControlInformation,
            (&mut reopened as *mut JOBOBJECT_CPU_RATE_CONTROL_INFORMATION).cast(),
            size_of::<JOBOBJECT_CPU_RATE_CONTROL_INFORMATION>() as u32,
            std::ptr::null_mut(),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    let reopened_rate = unsafe { reopened.Anonymous.CpuRate };
    if reopened.ControlFlags != expected_flags || reopened_rate != expected_rate {
        return Err(EmberLabError::InvalidDispatchManifest {
            detail: "Windows job object CPU hard cap did not reopen with the requested value"
                .into(),
        });
    }
    Ok(reopened_rate)
}

#[cfg(windows)]
fn create_private_completion_port() -> Result<OwnedHandle> {
    use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
    use windows_sys::Win32::System::IO::CreateIoCompletionPort;

    let completion_port =
        unsafe { CreateIoCompletionPort(INVALID_HANDLE_VALUE, std::ptr::null_mut(), 0, 1) };
    if completion_port.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(OwnedHandle(completion_port))
}

#[cfg(windows)]
fn create_job_completion_port(job: windows_sys::Win32::Foundation::HANDLE) -> Result<OwnedHandle> {
    use std::mem::size_of;
    use windows_sys::Win32::System::JobObjects::{
        JobObjectAssociateCompletionPortInformation, SetInformationJobObject,
        JOBOBJECT_ASSOCIATE_COMPLETION_PORT,
    };

    let completion_port = create_private_completion_port()?;
    let association = JOBOBJECT_ASSOCIATE_COMPLETION_PORT {
        CompletionKey: JOB_COMPLETION_KEY as *mut std::ffi::c_void,
        CompletionPort: completion_port.raw(),
    };
    if unsafe {
        SetInformationJobObject(
            job,
            JobObjectAssociateCompletionPortInformation,
            (&association as *const JOBOBJECT_ASSOCIATE_COMPLETION_PORT).cast(),
            size_of::<JOBOBJECT_ASSOCIATE_COMPLETION_PORT>() as u32,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(completion_port)
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
        CreateJobObjectW, JobObjectBasicUIRestrictions, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_BASIC_UI_RESTRICTIONS,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_JOB_MEMORY,
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

    // The hard cap itself is unconditional -- it is the host's own floor and
    // does not depend on what the manifest declared. The pacing class only
    // decides whether the spawn additionally proves the cap took: `Governed`
    // re-reads it off the job object and refuses to spawn on a mismatch,
    // yielding the rate the kernel actually reported. `Unpaced` declared no
    // contract, so no proof is produced and `applied_cpu_rate` stays `None`
    // rather than asserting a value that was never read back.
    let applied_cpu_rate = match spec.cpu_rate_percent {
        Some(cpu_rate_percent) => {
            let outcome = match spec.cpu_pacing_class {
                DispatchCpuPacingClass::Governed => {
                    configure_and_verify_windows_cpu_rate(job, cpu_rate_percent).map(Some)
                }
                DispatchCpuPacingClass::Unpaced => {
                    set_windows_cpu_rate(job, cpu_rate_percent).map(|_| None)
                }
            };
            match outcome {
                Ok(applied) => applied,
                Err(error) => {
                    unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
                    return Err(error);
                }
            }
        }
        None => None,
    };

    // Windows/UI surface wall (issue #898): a job that has not declared
    // `requires_ui_responsiveness` (only the closed Cockpit workload profile
    // may declare it — enforced in `validate_dispatch_workload_profile`) is
    // barred from every cross-desktop UI surface: the shared clipboard,
    // global atoms, display settings, desktop creation/switching, and
    // ExitWindows, plus USER handles owned by processes outside this job.
    // This is an OS-enforced ceiling applied at spawn, not a best-effort
    // convention — an undeclared job is walled off by construction.
    if !spec.requires_ui_responsiveness {
        let mut ui: JOBOBJECT_BASIC_UI_RESTRICTIONS = unsafe { zeroed() };
        ui.UIRestrictionsClass = managed_windows_ui_restrictions_all();
        if unsafe {
            SetInformationJobObject(
                job,
                JobObjectBasicUIRestrictions,
                (&ui as *const JOBOBJECT_BASIC_UI_RESTRICTIONS).cast(),
                size_of::<JOBOBJECT_BASIC_UI_RESTRICTIONS>() as u32,
            )
        } == 0
        {
            let error = std::io::Error::last_os_error();
            unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
            return Err(error.into());
        }
    }

    let completion_port = match create_job_completion_port(job) {
        Ok(port) => port,
        Err(error) => {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(job) };
            return Err(error);
        }
    };

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
        completion_port,
        process: OwnedHandle(info.hProcess),
        thread: OwnedHandle(info.hThread),
        stdout_log_guard: inherited_stdout,
        stderr_log_guard: inherited_stderr,
        pid: info.dwProcessId,
        main_thread_id: info.dwThreadId,
        identity,
        applied_cpu_rate,
        job_memory_contract: JobMemoryContract {
            maximum_job_memory_bytes: spec.maximum_job_memory_bytes,
            simulated_peak_commit_bytes: spec.simulated_peak_commit_bytes,
            overshoot_allowance_basis_points: JOB_MEMORY_OVERSHOOT_ALLOWANCE_BASIS_POINTS,
            kernel_limit_signal_observation_available: true,
        },
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

/// Receipted natural-exit state flip shared by every platform: fence on
/// `state='running' AND pid=?`, seal log hashes, flip to `exited` with the
/// real exit code, release the lease, insert the `job_exited` event. Windows'
/// `record_natural_exit` and the Unix reaper thread both delegate here so the
/// two platforms can never diverge in DB shape.
fn record_process_exit(
    db: &Mutex<Connection>,
    job_id: &str,
    pid: u32,
    expected_lease_epoch: i64,
    exit_code: i64,
) -> Result<()> {
    let mut conn = db.lock().map_err(|_| EmberLabError::Poisoned)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let lease: Option<(String, i64)> = tx
        .query_row(
            "SELECT resource,lease_epoch FROM jobs WHERE job_id=?1 AND state='running' AND pid=?2 AND lease_epoch=?3",
            params![job_id, pid, expected_lease_epoch],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let Some((resource, lease_epoch)) = lease else {
        let current: Option<String> = tx
            .query_row(
                "SELECT state FROM jobs WHERE job_id=?1 AND pid=?2 AND lease_epoch=?3",
                params![job_id, pid, expected_lease_epoch],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(state) = current {
            if matches!(
                JobState::parse(&state)?,
                JobState::Stopping | JobState::Stopped | JobState::Exited
            ) {
                return Ok(());
            }
        }
        return Err(EmberLabError::InvalidTransition {
            job_id: job_id.into(),
            detail: "natural-exit monitor lost its running state fence".into(),
        });
    };
    let (stdout_sha256, stderr_sha256) = seal_log_hashes(&tx, job_id)?;
    let timestamp = now_ms();
    let changed = tx.execute(
        "UPDATE jobs SET state='exited',exit_code=?3,exited_at_ms=?4,stdout_log_sha256=?6,stderr_log_sha256=?7,outage_event_cutoff_seq=(SELECT COALESCE(MAX(seq),0) FROM outage_events),updated_at_ms=?4 WHERE job_id=?1 AND state='running' AND pid=?2 AND lease_epoch=?5",
        params![
            job_id,
            pid,
            exit_code,
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
fn query_job_memory_peak(job: windows_sys::Win32::Foundation::HANDLE) -> Result<u64> {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::System::JobObjects::{
        JobObjectExtendedLimitInformation, QueryInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    };

    let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
    if unsafe {
        QueryInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            (&mut info as *mut JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            std::ptr::null_mut(),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(info.PeakJobMemoryUsed as u64)
}

#[cfg(windows)]
fn job_memory_verification_payload(
    db: &Mutex<Connection>,
    job_id: &str,
    root_pid: u32,
    observed_pid: u32,
    job: windows_sys::Win32::Foundation::HANDLE,
    root_process: windows_sys::Win32::Foundation::HANDLE,
    expected_root_identity: &ProcessIdentity,
) -> Value {
    use windows_sys::Win32::Foundation::{CloseHandle, BOOL};
    use windows_sys::Win32::System::JobObjects::IsProcessInJob;
    use windows_sys::Win32::System::Threading::{
        GetProcessId, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    let opened = if observed_pid == root_pid {
        None
    } else {
        let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, observed_pid) };
        (!handle.is_null()).then_some(handle)
    };
    let process = opened.unwrap_or(root_process);
    let mut in_job: BOOL = 0;
    let membership = unsafe { IsProcessInJob(process, job, &mut in_job) };
    let membership_error = (membership == 0).then(|| std::io::Error::last_os_error().to_string());
    let membership_verified = membership != 0 && in_job != 0;
    let handle_pid = unsafe { GetProcessId(process) };
    let handle_pid_verified = handle_pid == observed_pid && handle_pid != 0;
    let identity = inspect_handle(process, observed_pid);
    if let Some(handle) = opened {
        unsafe { CloseHandle(handle) };
    }
    let identity_payload = match identity {
        Ok(observed) => {
            let root_identity_match = observed_pid == root_pid
                && handle_pid_verified
                && observed.start_token == expected_root_identity.start_token
                && observed.executable == expected_root_identity.executable;
            json!({
                "verified": membership_verified && (root_identity_match || (observed_pid != root_pid && handle_pid_verified)),
                "kind": if observed_pid == root_pid { "root_process" } else { "job_member_descendant" },
                "basis": "event_time_process_inspection",
                "handle_pid": handle_pid,
                "handle_pid_verified": handle_pid_verified,
                "inspected_at_event": true,
                "observed_start_token": observed.start_token,
                "observed_executable": observed.executable,
                "error": Value::Null,
            })
        }
        Err(error) if observed_pid == root_pid => json!({
            "verified": membership_verified && handle_pid_verified,
            "kind": "root_process",
            "basis": "retained_birth_handle_identity",
            "handle_pid": handle_pid,
            "handle_pid_verified": handle_pid_verified,
            "inspected_at_event": false,
            "bound_start_token": expected_root_identity.start_token,
            "bound_executable": expected_root_identity.executable,
            "event_inspection_error": format!("{error:?}"),
        }),
        Err(error) => json!({
            "verified": false,
            "kind": "job_member_descendant",
            "basis": "event_time_process_inspection",
            "handle_pid": handle_pid,
            "handle_pid_verified": handle_pid_verified,
            "inspected_at_event": false,
            "error": format!("{error:?}"),
        }),
    };
    let lease_verified = db
        .lock()
        .map_err(|_| EmberLabError::Poisoned)
        .and_then(|conn| {
            conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM jobs j JOIN leases l ON l.resource=j.resource AND l.owner_job_id=j.job_id AND l.lease_epoch=j.lease_epoch WHERE j.job_id=?1 AND j.pid=?2 AND j.state='running')",
                params![job_id, root_pid],
                |row| row.get::<_, i64>(0),
            )
            .map(|value| value == 1)
            .map_err(Into::into)
        });
    let lease_payload = match lease_verified {
        Ok(verified) => json!({"verified": verified, "error": Value::Null}),
        Err(error) => json!({"verified": false, "error": format!("{error:?}")}),
    };
    json!({
        "job_object_membership": {
            "verified": membership_verified,
            "error": membership_error,
        },
        "process_identity": identity_payload,
        "lease": lease_payload,
    })
}

#[cfg(windows)]
fn insert_job_memory_event(
    db: &Mutex<Connection>,
    job_id: &str,
    kind: &str,
    payload: &Value,
) -> Result<()> {
    db.lock().map_err(|_| EmberLabError::Poisoned)?.execute(
        "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
        params![job_id, now_ms(), kind, payload.to_string()],
    )?;
    Ok(())
}

#[cfg(windows)]
struct JobMemoryEventContext<'a> {
    db: &'a Mutex<Connection>,
    job_id: &'a str,
    root_pid: u32,
    job: windows_sys::Win32::Foundation::HANDLE,
    process: windows_sys::Win32::Foundation::HANDLE,
    expected_identity: &'a ProcessIdentity,
    contract: JobMemoryContract,
}

#[cfg(windows)]
fn job_memory_event_payload(
    context: &JobMemoryEventContext<'_>,
    observed_pid: u32,
    peak_job_memory_used_bytes: u64,
) -> Value {
    let simulated = context.contract.simulated_peak_commit_bytes;
    let margin = context
        .contract
        .maximum_job_memory_bytes
        .zip(simulated)
        .and_then(|(maximum, simulated)| maximum.checked_sub(simulated));
    json!({
        "schema_version": "ember-lab-job-memory-observation-v1",
        "scope": "windows_job_object",
        "root_pid": context.root_pid,
        "offending_pid": observed_pid,
        "maximum_job_memory_bytes": context.contract.maximum_job_memory_bytes,
        "simulated_peak_commit_bytes": simulated,
        "overshoot_allowance_basis": JOB_MEMORY_OVERSHOOT_ALLOWANCE_BASIS,
        "overshoot_allowance_bps": context.contract.overshoot_allowance_basis_points,
        "overshoot_margin_bytes": margin,
        "kernel_limit_signal_observation_available": context.contract.kernel_limit_signal_observation_available,
        "kernel_limit_signal_observation_reason": if context.contract.kernel_limit_signal_observation_available {
            Value::Null
        } else {
            json!("job_object_completion_port_already_associated_win32_5_after_daemon_handoff")
        },
        "peak_job_memory_used_bytes": peak_job_memory_used_bytes,
        "verification": job_memory_verification_payload(
            context.db,
            context.job_id,
            context.root_pid,
            observed_pid,
            context.job,
            context.process,
            context.expected_identity,
        ),
    })
}

#[cfg(windows)]
fn observe_job_memory_completion(
    context: &JobMemoryEventContext<'_>,
    message: u32,
    key: usize,
    value: *mut windows_sys::Win32::System::IO::OVERLAPPED,
    limit_signal_observed: &mut bool,
) -> Result<()> {
    use windows_sys::Win32::System::SystemServices::JOB_OBJECT_MSG_JOB_MEMORY_LIMIT;

    if key == JOB_COMPLETION_KEY
        && message == JOB_OBJECT_MSG_JOB_MEMORY_LIMIT
        && !*limit_signal_observed
    {
        *limit_signal_observed = true;
        let observed_pid = value as usize as u32;
        let peak = query_job_memory_peak(context.job)?;
        let mut payload = job_memory_event_payload(context, observed_pid, peak);
        payload["kernel_message_code"] = json!(JOB_OBJECT_MSG_JOB_MEMORY_LIMIT);
        payload["signal_latched"] = json!(true);
        insert_job_memory_event(
            context.db,
            context.job_id,
            "job_memory_limit_reached",
            &payload,
        )?;
    }
    Ok(())
}

#[cfg(windows)]
fn spawn_job_memory_observer(
    registration: JobMemoryObserverRegistration,
) -> std::io::Result<Arc<JobMemoryObserverBarrier>> {
    let JobMemoryObserverRegistration {
        db,
        job_id,
        root_pid,
        job,
        process,
        completion_port,
        expected_identity,
        contract,
    } = registration;
    let barrier = Arc::new(JobMemoryObserverBarrier::default());
    let thread_barrier = Arc::clone(&barrier);
    std::thread::Builder::new()
        .name(format!("ember-job-memory-{root_pid}"))
        .spawn(move || {
            use windows_sys::Win32::System::Threading::INFINITE;
            use windows_sys::Win32::System::IO::GetQueuedCompletionStatus;

            let outcome = (|| -> Result<()> {
                let db = db.upgrade().ok_or(EmberLabError::Poisoned)?;
                let context = JobMemoryEventContext {
                    db: &db,
                    job_id: &job_id,
                    root_pid,
                    job: job.raw(),
                    process: process.raw(),
                    expected_identity: &expected_identity,
                    contract,
                };
                let mut limit_signal_observed = false;
                loop {
                    let mut message = 0u32;
                    let mut key = 0usize;
                    let mut value = std::ptr::null_mut();
                    if unsafe {
                        GetQueuedCompletionStatus(
                            completion_port.raw(),
                            &mut message,
                            &mut key,
                            &mut value,
                            INFINITE,
                        )
                    } == 0
                    {
                        return Err(std::io::Error::last_os_error().into());
                    }
                    if key == JOB_OBSERVER_CANCEL_COMPLETION_KEY {
                        return Ok(());
                    }
                    if key == JOB_TERMINAL_COMPLETION_KEY {
                        // The exit monitor has already terminated the owned job and
                        // observed ActiveProcesses==0 before posting this sentinel.
                        // Drain anything the kernel queued ahead of or concurrently
                        // with the sentinel before snapshotting the terminal peak.
                        loop {
                            let mut drain_message = 0u32;
                            let mut drain_key = 0usize;
                            let mut drain_value = std::ptr::null_mut();
                            if unsafe {
                                GetQueuedCompletionStatus(
                                    completion_port.raw(),
                                    &mut drain_message,
                                    &mut drain_key,
                                    &mut drain_value,
                                    0,
                                )
                            } == 0
                            {
                                let error = std::io::Error::last_os_error();
                                if error.raw_os_error() == Some(258) {
                                    break;
                                }
                                return Err(error.into());
                            }
                            observe_job_memory_completion(
                                &context,
                                drain_message,
                                drain_key,
                                drain_value,
                                &mut limit_signal_observed,
                            )?;
                        }
                        let peak = query_job_memory_peak(job.raw())?;
                        let mut payload = job_memory_event_payload(&context, root_pid, peak);
                        payload["limit_signal_observed"] = json!(limit_signal_observed);
                        insert_job_memory_event(&db, &job_id, "job_memory_accounting", &payload)?;
                        return Ok(());
                    }
                    observe_job_memory_completion(
                        &context,
                        message,
                        key,
                        value,
                        &mut limit_signal_observed,
                    )?;
                }
            })();
            thread_barrier.complete(outcome.map_err(|error| format!("{error:?}")));
        })?;
    Ok(barrier)
}

/// Unix exit-code encoding for the shared `exit_code` column: the process's
/// real exit code when it exited normally, or the standard shell convention
/// of `128 + signal` when it was killed by a signal (`ExitStatus::code()`
/// returns `None` in that case).
#[cfg(not(windows))]
fn unix_exit_code(status: std::process::ExitStatus) -> i64 {
    use std::os::unix::process::ExitStatusExt;
    status
        .code()
        .map(|code| code as i64)
        .unwrap_or_else(|| 128 + status.signal().unwrap_or(0) as i64)
}

#[cfg(windows)]
fn spawn_exit_monitor(registration: ExitMonitorRegistration) {
    let ExitMonitorRegistration {
        db,
        retained,
        ownership,
        shutdown,
        job_id,
        pid,
        lease_epoch,
        waiter,
        terminal_job,
        terminal_process,
        terminal_port,
        memory_barrier,
    } = registration;
    std::thread::spawn(move || {
        use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
        use windows_sys::Win32::System::Threading::{
            GetExitCodeProcess, WaitForMultipleObjects, INFINITE,
        };
        use windows_sys::Win32::System::IO::PostQueuedCompletionStatus;

        let handles = [waiter.raw(), shutdown.raw()];
        let wait_result = unsafe { WaitForMultipleObjects(2, handles.as_ptr(), 0, INFINITE) };
        if wait_result != WAIT_OBJECT_0 && wait_result != WAIT_OBJECT_0 + 1 {
            return;
        }
        let process_exited = wait_result == WAIT_OBJECT_0;
        if !process_exited {
            let _ = unsafe {
                PostQueuedCompletionStatus(
                    terminal_port.raw(),
                    0,
                    JOB_OBSERVER_CANCEL_COMPLETION_KEY,
                    std::ptr::null(),
                )
            };
            let _ = memory_barrier.wait();
            return;
        }
        // Dedicated duplicates keep terminal accounting alive even when an
        // explicit stop path has removed the retained-map entry. Stop this
        // exact owned job to zero active processes before the sentinel.
        if terminate_handles(terminal_job.raw(), terminal_process.raw(), pid).is_err() {
            return;
        }
        if unsafe {
            PostQueuedCompletionStatus(
                terminal_port.raw(),
                0,
                JOB_TERMINAL_COMPLETION_KEY,
                std::ptr::null(),
            )
        } == 0
        {
            return;
        }
        if memory_barrier.wait().is_err() {
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
        if !retained.contains_key(&job_id) {
            return;
        }
        if record_process_exit(&db, &job_id, pid, lease_epoch, exit_code as i64).is_ok() {
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
    let completion_port = match create_job_completion_port(job) {
        Ok(port) => port,
        Err(EmberLabError::Io(error)) if error.raw_os_error() == Some(5) => {
            // Windows does not permit replacing a Job Object's original
            // completion-port association after daemon handoff. Preserve
            // custody with a private sentinel-only port; the terminal receipt
            // explicitly marks kernel limit-signal observation unavailable.
            match create_private_completion_port() {
                Ok(port) => port,
                Err(error) => {
                    unsafe {
                        windows_sys::Win32::Foundation::CloseHandle(process);
                        windows_sys::Win32::Foundation::CloseHandle(job);
                    }
                    return LiveStatus::IdentityConflict(format!(
                        "terminal-only job-memory port cannot be created: {error:?}"
                    ));
                }
            }
        }
        Err(error) => {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(process);
                windows_sys::Win32::Foundation::CloseHandle(job);
            }
            return LiveStatus::IdentityConflict(format!(
                "job-memory completion port cannot be re-established: {error:?}"
            ));
        }
    };
    LiveStatus::Verified(LiveProcess {
        job: OwnedHandle(job),
        completion_port,
        process: OwnedHandle(process),
        _stdout_log_guard: stdout_log_guard,
        _stderr_log_guard: stderr_log_guard,
        pid: row.pid,
        identity: current,
        job_memory_contract: JobMemoryContract {
            maximum_job_memory_bytes: None,
            simulated_peak_commit_bytes: None,
            overshoot_allowance_basis_points: JOB_MEMORY_OVERSHOOT_ALLOWANCE_BASIS_POINTS,
            kernel_limit_signal_observation_available: false,
        },
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
    fn applied_cpu_rate(&self) -> Option<u32> {
        None
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
    fn detach_reaper(mut self, db: Weak<Mutex<Connection>>, job_id: String, lease_epoch: i64) {
        if let Some(mut child) = self.child.take() {
            let pid = self.pid;
            std::thread::spawn(move || {
                let Ok(status) = child.wait() else {
                    return;
                };
                let Some(db) = db.upgrade() else {
                    return;
                };
                let _ = record_process_exit(&db, &job_id, pid, lease_epoch, unix_exit_code(status));
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

    #[test]
    fn dispatch_token_second_process_observation_mismatch_rolls_back_consumption_and_event() {
        let mut connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch(
                "CREATE TABLE jobs(job_id TEXT PRIMARY KEY,pid INTEGER NOT NULL,program TEXT NOT NULL,argv_sha256 TEXT NOT NULL,process_start_token TEXT NOT NULL,executable_identity TEXT NOT NULL,state TEXT NOT NULL);
                 CREATE TABLE dispatch_tokens(token_sha256 TEXT PRIMARY KEY,job_id TEXT NOT NULL,pid INTEGER NOT NULL,program TEXT NOT NULL,argv_sha256 TEXT NOT NULL,expires_at_ms INTEGER NOT NULL,consumed_at_ms INTEGER);
                 CREATE TABLE events(job_id TEXT NOT NULL,ts_ms INTEGER NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL);",
            )
            .unwrap();
        let job_id = "posix-second-observation-job";
        let token = "a".repeat(DISPATCH_TOKEN_BYTES * 2);
        let client_pid = 4242_u32;
        let initial_identity = ProcessIdentity {
            start_token: "initial-start-token".into(),
            executable: "/usr/bin/owned-worker".into(),
        };
        connection
            .execute(
                "INSERT INTO jobs(job_id,pid,program,argv_sha256,process_start_token,executable_identity,state) VALUES(?1,?2,?3,?4,?5,?6,'running')",
                params![
                    job_id,
                    client_pid,
                    "/usr/bin/owned-worker",
                    "argv-sha",
                    &initial_identity.start_token,
                    &initial_identity.executable,
                ],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO dispatch_tokens(token_sha256,job_id,pid,program,argv_sha256,expires_at_ms,consumed_at_ms) VALUES(?1,?2,?3,?4,?5,?6,NULL)",
                params![
                    hash_bytes(token.as_bytes()),
                    job_id,
                    client_pid,
                    "/usr/bin/owned-worker",
                    "argv-sha",
                    now_ms() + 60_000,
                ],
            )
            .unwrap();
        let final_identity = ProcessIdentity {
            start_token: "reused-start-token".into(),
            executable: "/usr/bin/reused-worker".into(),
        };
        let observation_calls = std::cell::Cell::new(0_usize);

        let result = consume_dispatch_token_with_process_observer(
            &mut connection,
            job_id,
            &token,
            client_pid,
            |_| {
                let call = observation_calls.get();
                observation_calls.set(call + 1);
                Ok(if call == 0 {
                    initial_identity.clone()
                } else {
                    final_identity.clone()
                })
            },
        );

        assert!(
            matches!(result, Err(EmberLabError::DispatchTokenRefused { .. })),
            "second process observation mismatch must refuse: {result:?}"
        );
        assert_eq!(observation_calls.get(), 2);
        assert_eq!(
            connection
                .query_row(
                    "SELECT consumed_at_ms FROM dispatch_tokens WHERE job_id=?1",
                    [job_id],
                    |row| row.get::<_, Option<i64>>(0),
                )
                .unwrap(),
            None
        );
        assert_eq!(
            connection
                .query_row(
                    "SELECT COUNT(*) FROM events WHERE job_id=?1 AND kind='dispatch_token_consumed'",
                    [job_id],
                    |row| row.get::<_, i64>(0),
                )
                .unwrap(),
            0
        );
    }

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

    #[cfg(windows)]
    #[test]
    fn managed_windows_ui_restrictions_cover_every_cross_desktop_surface() {
        use windows_sys::Win32::System::JobObjects::{
            JOB_OBJECT_UILIMIT_DESKTOP, JOB_OBJECT_UILIMIT_DISPLAYSETTINGS,
            JOB_OBJECT_UILIMIT_EXITWINDOWS, JOB_OBJECT_UILIMIT_GLOBALATOMS,
            JOB_OBJECT_UILIMIT_HANDLES, JOB_OBJECT_UILIMIT_READCLIPBOARD,
            JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS, JOB_OBJECT_UILIMIT_WRITECLIPBOARD,
        };

        let restrictions = managed_windows_ui_restrictions_all();
        for flag in [
            JOB_OBJECT_UILIMIT_HANDLES,
            JOB_OBJECT_UILIMIT_READCLIPBOARD,
            JOB_OBJECT_UILIMIT_WRITECLIPBOARD,
            JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS,
            JOB_OBJECT_UILIMIT_DISPLAYSETTINGS,
            JOB_OBJECT_UILIMIT_GLOBALATOMS,
            JOB_OBJECT_UILIMIT_DESKTOP,
            JOB_OBJECT_UILIMIT_EXITWINDOWS,
        ] {
            assert_ne!(
                restrictions & flag,
                0,
                "expected UI restriction flag {flag:#x} to be set"
            );
        }
        // Windows' own JOB_OBJECT_UILIMIT_ALL constant (winnt.h) is 0x000000FF —
        // every currently defined UI-limit bit. Pin the exact value so a future
        // windows-sys bump that adds a new bit is caught here, not silently
        // left unrestricted.
        assert_eq!(restrictions, 0x0000_00FF);
    }

    #[cfg(windows)]
    #[test]
    fn managed_windows_cpu_rate_is_reopened_from_job_object() {
        use windows_sys::Win32::Foundation::CloseHandle;
        use windows_sys::Win32::System::JobObjects::CreateJobObjectW;

        let job = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        assert!(!job.is_null());
        let applied = configure_and_verify_windows_cpu_rate(job, 25).unwrap();
        assert_eq!(applied, 2_500);
        unsafe { CloseHandle(job) };
    }

    #[test]
    fn registry_replacement_between_initial_hash_and_parse_is_rejected() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let scratch_root = std::env::var("CARGO_TARGET_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target"))
            .join("binding-snapshot-tests");
        let lease = scratch::ScratchLease::create_with_identity(
            scratch::ScratchPolicy {
                root: scratch_root,
                minimum_free_bytes: 1,
                stale_after: Duration::from_secs(60),
            },
            &format!("binding-snapshot-{nonce}"),
            std::process::id(),
            "unit-test-process",
            nonce.try_into().unwrap(),
        )
        .unwrap();
        let root = lease.path().to_path_buf();
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
        drop(lease);
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

    #[cfg(windows)]
    fn seed_one_running_job(conn: &Connection, job_id: &str) {
        conn.execute_batch("CREATE TABLE jobs(job_id TEXT PRIMARY KEY, state TEXT NOT NULL);")
            .unwrap();
        conn.execute(
            "INSERT INTO jobs(job_id, state) VALUES(?1, 'running')",
            params![job_id],
        )
        .unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn a_physical_only_breach_freezes_admission_but_leaves_running_jobs_alone() {
        let conn = Connection::open_in_memory().unwrap();
        create_resource_guard_tables(&conn).unwrap();
        seed_one_running_job(&conn, "e8-dense-a1-run");

        let mut low_physical = healthy_host_capacity();
        low_physical.physical_available_bytes = RESOURCE_GUARD_MIN_PHYSICAL_AVAILABLE_BYTES - 1;
        persist_resource_guard_sample(&conn, 100, Ok(low_physical)).unwrap();

        let frozen = resource_guard_status_from_connection(&conn).unwrap();
        assert_eq!(frozen["admission_state"], "frozen");
        assert_eq!(frozen["reason"], "physical_available_below_survival_floor");
        assert!(
            running_job_ids_for_protective_stop(&conn)
                .unwrap()
                .is_empty(),
            "a physical-only breach must not select a running job for protective stop \
             -- it is an admission-quality signal, not a host-survival condition (#898)"
        );
    }

    #[cfg(windows)]
    #[test]
    fn a_commit_breach_selects_the_running_job_for_protective_stop() {
        let conn = Connection::open_in_memory().unwrap();
        create_resource_guard_tables(&conn).unwrap();
        seed_one_running_job(&conn, "e8-dense-a1-run");

        let mut low_commit = healthy_host_capacity();
        low_commit.current_commit_remaining_bytes = RESOURCE_GUARD_MIN_COMMIT_REMAINING_BYTES - 1;
        persist_resource_guard_sample(&conn, 100, Ok(low_commit)).unwrap();

        let frozen = resource_guard_status_from_connection(&conn).unwrap();
        assert_eq!(frozen["admission_state"], "frozen");
        assert_eq!(frozen["reason"], "commit_remaining_below_survival_floor");
        assert_eq!(
            running_job_ids_for_protective_stop(&conn).unwrap(),
            vec!["e8-dense-a1-run".to_string()]
        );
    }

    #[cfg(windows)]
    #[test]
    fn a_probe_failure_also_selects_the_running_job_for_protective_stop() {
        let conn = Connection::open_in_memory().unwrap();
        create_resource_guard_tables(&conn).unwrap();
        seed_one_running_job(&conn, "e8-dense-a1-run");

        persist_resource_guard_headroom(
            &conn,
            100,
            Err(EmberLabError::InvalidDispatchManifest {
                detail: "probe unavailable".into(),
            }),
        )
        .unwrap();

        let frozen = resource_guard_status_from_connection(&conn).unwrap();
        assert_eq!(frozen["admission_state"], "frozen");
        assert_eq!(frozen["reason"], "resource_guard_probe_failed");
        assert_eq!(
            running_job_ids_for_protective_stop(&conn).unwrap(),
            vec!["e8-dense-a1-run".to_string()]
        );
    }

    #[cfg(windows)]
    #[test]
    fn no_freeze_selects_no_running_job_for_protective_stop() {
        let conn = Connection::open_in_memory().unwrap();
        create_resource_guard_tables(&conn).unwrap();
        seed_one_running_job(&conn, "e8-dense-a1-run");

        persist_resource_guard_sample(&conn, 100, Ok(healthy_host_capacity())).unwrap();

        assert_eq!(
            resource_guard_status_from_connection(&conn).unwrap()["admission_state"],
            "open"
        );
        assert!(running_job_ids_for_protective_stop(&conn)
            .unwrap()
            .is_empty());
    }
}
