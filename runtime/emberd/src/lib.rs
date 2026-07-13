// goal_id: EMBER-01
// workstream_id: EMBER-01A
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

#[derive(Clone, Debug)]
pub struct JobSpec {
    job_id: String,
    program: String,
    args: Vec<String>,
    resource_lease: String,
    env: BTreeMap<String, String>,
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
        }
    }
    pub fn with_env<K: Into<String>, V: Into<String>>(mut self, key: K, value: V) -> Self {
        self.env.insert(key.into(), value.into());
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
    pid: u32,
}

#[cfg(windows)]
struct RetainedProcess {
    live: LiveProcess,
    monitored: bool,
}

pub struct Daemon {
    _state_writer_lock: fs::File,
    db: Arc<Mutex<Connection>>,
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
        #[cfg(windows)]
        let monitor_shutdown = create_monitor_shutdown()?;
        let conn = Connection::open(path)?;
        conn.busy_timeout(Duration::from_secs(10))?;
        conn.execute_batch("PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version','1');
            CREATE TABLE IF NOT EXISTS identities(job_id TEXT PRIMARY KEY, canonical_path TEXT NOT NULL, sha256 TEXT NOT NULL, identity_blob BLOB NOT NULL, bound_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS lease_generations(resource TEXT PRIMARY KEY, generation INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS leases(resource TEXT PRIMARY KEY, owner_job_id TEXT NOT NULL, lease_epoch INTEGER NOT NULL, acquired_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, program TEXT NOT NULL, args_json TEXT NOT NULL, env_json TEXT NOT NULL, resource TEXT NOT NULL, lease_epoch INTEGER NOT NULL, pid INTEGER NOT NULL DEFAULT 0, main_thread_id INTEGER NOT NULL DEFAULT 0, job_object_name TEXT NOT NULL, process_start_token TEXT NOT NULL DEFAULT '', executable_identity TEXT NOT NULL DEFAULT '', argv_sha256 TEXT NOT NULL, state TEXT NOT NULL, exit_code INTEGER, exited_at_ms INTEGER, started_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, ts_ms INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL);")?;
        Ok(Self {
            _state_writer_lock: state_writer_lock,
            db: Arc::new(Mutex::new(conn)),
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

    pub fn acquire_lease(&self, resource: &str, job_id: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
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

    pub fn start_job(&self, spec: JobSpec) -> Result<JobHandle> {
        self.verify_identity(&spec.job_id)?;
        let argv_json = serde_json::to_string(&spec.args)?;
        let env_json = serde_json::to_string(&spec.env)?;
        let argv_sha = hash_bytes(argv_json.as_bytes());
        let job_object_name = job_object_name(&spec.job_id);
        {
            let mut conn = self.conn()?;
            let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
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
                "INSERT INTO jobs(job_id,program,args_json,env_json,resource,lease_epoch,job_object_name,argv_sha256,state,started_at_ms,updated_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,'starting',?9,?9)",
                params![spec.job_id, spec.program, argv_json, env_json, spec.resource_lease, lease_epoch, job_object_name, argv_sha, now_ms()],
            )?;
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_start_reserved',?3)",
                params![spec.job_id, now_ms(), json!({"job_object_name":job_object_name}).to_string()],
            )?;
            tx.commit()?;
        }
        let mut spawned = match spawn_managed(&spec, &job_object_name) {
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
                "UPDATE jobs SET pid=?2,main_thread_id=?3,process_start_token=?4,executable_identity=?5,state='prepared',updated_at_ms=?6 WHERE job_id=?1 AND state='starting' AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
                params![spec.job_id, pid, spawned.main_thread_id(), identity.start_token, identity.executable, now_ms()],
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
        if let Err(error) = spawned.resume() {
            let _ = spawned.terminate_and_wait();
            let _ = self.mark_failed(&spec.job_id, "job_resume_failed");
            return Err(error);
        }
        let running = (|| -> Result<()> {
            let mut conn = self.conn()?;
            let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let changed = tx.execute(
                "UPDATE jobs SET state='running',updated_at_ms=?2 WHERE job_id=?1 AND state='prepared' AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
                params![spec.job_id, now_ms()],
            )?;
            if changed != 1 {
                return Err(EmberdError::InvalidTransition {
                    job_id: spec.job_id.clone(),
                    detail: "prepared start lost its lease fence".into(),
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
            let _ = self.mark_failed(&spec.job_id, "job_running_commit_failed");
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
                let _ = self.mark_dead(job_id, &row, "job_reconciled_dead");
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
                self.finalize_stopped(job_id, &row)?;
                return Ok(());
            }
            LiveStatus::Dead => {
                self.mark_dead(job_id, &row, "job_dead_before_stop")?;
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
        self.finalize_stopped(job_id, &row)
    }

    pub fn export_receipt(&self, job_id: &str, path: &Path) -> Result<()> {
        self.verify_identity(job_id)?;
        if path.exists() {
            return Err(EmberdError::ReceiptAlreadyExists {
                path: path.to_path_buf(),
            });
        }
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Deferred)?;
        let row: (String,String,String,String,i64) = tx.query_row("SELECT j.state,j.resource,i.sha256,j.executable_identity,j.pid FROM jobs j JOIN identities i ON i.job_id=j.job_id WHERE j.job_id=?1", [job_id], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?.ok_or_else(|| EmberdError::JobNotFound { job_id: job_id.into() })?;
        let mut stmt = tx.prepare(
            "SELECT seq,ts_ms,kind,payload_json FROM events WHERE job_id=?1 ORDER BY seq",
        )?;
        let raw_events: Vec<(i64, i64, String, String)> = stmt
            .query_map([job_id], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?))
            })?
            .collect::<std::result::Result<_, _>>()?;
        drop(stmt);
        tx.commit()?;
        let events: Vec<Value> = raw_events.into_iter().map(|(seq,ts,kind,payload)| Ok(json!({"seq":seq,"ts_ms":ts,"kind":kind,"payload":serde_json::from_str::<Value>(&payload)?}))).collect::<Result<_>>()?;
        let receipt = json!({"schema":"emberd-operational-receipt-v1","job_id":job_id,"identity_sha256":row.2,"resource_lease":row.1,"state":row.0,"pid":row.4,"executable_identity":row.3,"events":events,"scientific_capability_evidence":false});
        atomic_create(path, &serde_json::to_vec_pretty(&receipt)?)
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
                    resume_thread_id(row.main_thread_id)?;
                    self.transition_prepared_running(&job_id, &row)?;
                    self.retain_and_monitor(&job_id, live)?;
                }
                (JobState::Prepared, LiveStatus::Dead) | (JobState::Running, LiveStatus::Dead) => {
                    self.mark_dead(&job_id, &row, "job_reconciled_dead")?
                }
                (JobState::Running, LiveStatus::Verified(live)) => {
                    self.commit_adoption(&job_id, &row)?;
                    self.retain_and_monitor(&job_id, live)?;
                }
                (JobState::Stopping, LiveStatus::Verified(live)) => {
                    terminate_live(&live)?;
                    self.finalize_stopped(&job_id, &row)?;
                    self.live
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner())
                        .remove(&job_id);
                }
                (JobState::Stopping, LiveStatus::Dead) => {
                    self.finalize_stopped(&job_id, &row)?;
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

    fn transition_prepared_running(&self, job_id: &str, row: &JobProcessRow) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET state='running',updated_at_ms=?2 WHERE job_id=?1 AND state='prepared' AND lease_epoch=?3 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
            params![job_id, now_ms(), row.lease_epoch],
        )?;
        if changed != 1 {
            return Err(EmberdError::InvalidTransition {
                job_id: job_id.into(),
                detail: "prepared reconciliation lost its state or lease fence".into(),
            });
        }
        tx.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'job_started',?3)",
            params![
                job_id,
                now_ms(),
                json!({"pid":row.pid,"reconciled":true}).to_string()
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    fn finalize_stopped(&self, job_id: &str, row: &JobProcessRow) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET state='stopped',updated_at_ms=?2 WHERE job_id=?1 AND state='stopping' AND lease_epoch=?3",
            params![job_id, now_ms(), row.lease_epoch],
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
            "UPDATE jobs SET state='failed',updated_at_ms=?2 WHERE job_id=?1 AND state='starting' AND lease_epoch=?3",
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

    fn mark_dead(&self, job_id: &str, row: &JobProcessRow, kind: &str) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE jobs SET state='failed',updated_at_ms=?2 WHERE job_id=?1 AND state=?3 AND lease_epoch=?4 AND EXISTS(SELECT 1 FROM leases l WHERE l.resource=jobs.resource AND l.owner_job_id=jobs.job_id AND l.lease_epoch=jobs.lease_epoch)",
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
        self.conn()?.query_row("SELECT pid,process_start_token,executable_identity,resource,state,job_object_name,main_thread_id,lease_epoch FROM jobs WHERE job_id=?1", [job_id], |r| { let state:String=r.get(4)?; Ok((r.get::<_,u32>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,state,r.get::<_,String>(5)?,r.get::<_,u32>(6)?,r.get::<_,i64>(7)?)) }).optional()?.ok_or_else(|| EmberdError::JobNotFound { job_id: job_id.into() }).and_then(|r| Ok(JobProcessRow { pid:r.0,start_token:r.1,executable:r.2,resource:r.3,state:JobState::parse(&r.4)?,job_object_name:r.5,main_thread_id:r.6,lease_epoch:r.7 }))
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
            pid: self.pid,
        }
    }
}

#[cfg(windows)]
struct ProcThreadAttributeList {
    _storage: Vec<u8>,
    _jobs: Box<[windows_sys::Win32::Foundation::HANDLE; 1]>,
    ptr: windows_sys::Win32::System::Threading::LPPROC_THREAD_ATTRIBUTE_LIST,
}
#[cfg(windows)]
impl ProcThreadAttributeList {
    fn for_job(job: windows_sys::Win32::Foundation::HANDLE) -> Result<Self> {
        use windows_sys::Win32::System::Threading::{
            InitializeProcThreadAttributeList, UpdateProcThreadAttribute,
            PROC_THREAD_ATTRIBUTE_JOB_LIST,
        };
        let mut bytes = 0usize;
        unsafe { InitializeProcThreadAttributeList(std::ptr::null_mut(), 1, 0, &mut bytes) };
        if bytes == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let mut storage = vec![0u8; bytes];
        let ptr = storage.as_mut_ptr().cast();
        if unsafe { InitializeProcThreadAttributeList(ptr, 1, 0, &mut bytes) } == 0 {
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
        Ok(Self {
            _storage: storage,
            _jobs: jobs,
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
fn spawn_managed(spec: &JobSpec, job_name: &str) -> Result<SpawnedProcess> {
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::{DuplicateHandle, DUPLICATE_SAME_ACCESS};
    use windows_sys::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, GetCurrentProcess, WaitForSingleObject, CREATE_NEW_PROCESS_GROUP,
        CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT,
        PROCESS_INFORMATION, STARTUPINFOEXW,
    };

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

    let attributes = match ProcThreadAttributeList::for_job(job) {
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
    startup.lpAttributeList = attributes.ptr;
    let mut info: PROCESS_INFORMATION = unsafe { zeroed() };
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            0,
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
    let timestamp = now_ms();
    let changed = tx.execute(
        "UPDATE jobs SET state='exited',exit_code=?3,exited_at_ms=?4,updated_at_ms=?4 WHERE job_id=?1 AND state='running' AND pid=?2 AND lease_epoch=?5",
        params![job_id, pid, exit_code as i64, timestamp, lease_epoch],
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
        OpenProcess, WaitForSingleObject, PROCESS_QUERY_LIMITED_INFORMATION,
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
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_RIGHT,
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
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_RIGHT,
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
    LiveStatus::Verified(LiveProcess {
        job: OwnedHandle(job),
        process: OwnedHandle(process),
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
fn spawn_managed(spec: &JobSpec, _job_name: &str) -> Result<SpawnedProcess> {
    let child = Command::new(&spec.program)
        .args(&spec.args)
        .envs(&spec.env)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
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
