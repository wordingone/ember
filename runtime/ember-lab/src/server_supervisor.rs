// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! Ember Lab's receipt-bound server supervision control law.
//!
//! Historical issue language called this a watchdog/daemon.  The current
//! authority is the Ember Lab `Daemon`: identity, lease, planned-outage,
//! activity-event, and atomic-receipt primitives remain the single source of
//! truth.  This module only adds the server leg to that authority; it does not
//! create a second launcher, registry, ledger, or receipt family.

use crate::{
    atomic_create, hash_bytes, Daemon, DispatchManifest, DispatchOutcome, EmberLabError, Result,
};
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::time::{Duration, Instant};

pub const SERVER_AUTHORITY_SCHEMA: &str = "ember-lab-server-authority-v1";
pub const SERVER_SUPERVISION_ID_SCHEMA: &str = "ember-lab-server-supervision-v1";

fn supervision_identity(resource_lease: &str) -> String {
    format!("{SERVER_SUPERVISION_ID_SCHEMA}:{resource_lease}")
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServerAuthority {
    pub schema_version: String,
    pub job_id: String,
    pub resource_lease: String,
    pub target: String,
    pub host: String,
    pub port: u16,
    pub pid: u32,
    pub identity_sha256: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EndpointHealth {
    Healthy,
    Dead,
    Hung,
}

impl EndpointHealth {
    fn as_str(self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Dead => "dead",
            Self::Hung => "hung",
        }
    }
}

#[derive(Clone, Debug)]
pub struct ServerObservation {
    pub process_alive: bool,
    pub endpoint: EndpointHealth,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannedOutageState {
    None,
    Open,
    Expired,
    Closed,
}

impl PlannedOutageState {
    fn as_str(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Open => "open",
            Self::Expired => "expired",
            Self::Closed => "closed",
        }
    }
}

#[derive(Clone, Debug)]
pub struct RestoreEvidence {
    pub restore_cost_s: f64,
    pub health_status: u16,
}

#[derive(Clone, Debug)]
pub struct ServerCycleRequest {
    pub authority_path: PathBuf,
    pub authority_sha256: String,
    pub receipt_path: PathBuf,
    pub observation: ServerObservation,
    pub available_headroom_bytes: u64,
    pub required_headroom_bytes: u64,
    pub now_ms: i64,
}

#[derive(Clone, Debug)]
pub struct ServerLiveCycleRequest {
    pub authority_path: PathBuf,
    pub authority_sha256: String,
    pub receipt_path: PathBuf,
    pub restore_manifest_path: PathBuf,
    pub required_headroom_bytes: u64,
    pub now_ms: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServerCycleReceipt {
    pub authority_sha256: String,
    pub supervision_id: String,
    pub job_id: String,
    pub target: String,
    pub endpoint: String,
    pub observed_at_ms: i64,
    pub process_alive: bool,
    pub endpoint_health: String,
    pub outage_state: String,
    pub decision: String,
    pub death_cause: Option<String>,
    pub restore_cost_s: Option<f64>,
    pub health_status: Option<u16>,
    pub restarts_last_hour: u32,
    pub activity_event: String,
}

fn valid_sha(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn invalid(detail: impl Into<String>) -> EmberLabError {
    EmberLabError::InvalidTransition {
        job_id: String::new(),
        detail: detail.into(),
    }
}

fn load_authority(path: &std::path::Path, expected_sha256: &str) -> Result<ServerAuthority> {
    if !valid_sha(expected_sha256) {
        return Err(invalid("server authority hash is not lowercase sha256"));
    }
    let bytes = fs::read(path)?;
    if hash_bytes(&bytes) != expected_sha256 {
        return Err(invalid(
            "server authority bytes do not match supplied sha256",
        ));
    }
    let authority: ServerAuthority = serde_json::from_slice(&bytes)
        .map_err(|error| invalid(format!("server authority is not closed JSON: {error}")))?;
    if authority.schema_version != SERVER_AUTHORITY_SCHEMA
        || authority.job_id.trim().is_empty()
        || authority.resource_lease.trim().is_empty()
        || authority.target.trim().is_empty()
        || authority.host.trim().is_empty()
        || !matches!(authority.host.as_str(), "127.0.0.1" | "localhost" | "::1")
        || authority.port == 0
        || authority.pid == 0
        || !valid_sha(&authority.identity_sha256)
    {
        return Err(invalid("server authority fields are invalid"));
    }
    Ok(authority)
}

fn validate_receipt_destination(
    authority_path: &std::path::Path,
    receipt_path: &std::path::Path,
) -> Result<()> {
    let authority_root = authority_path
        .parent()
        .ok_or_else(|| invalid("server authority has no custody root"))?
        .canonicalize()?;
    let receipt_parent = receipt_path
        .parent()
        .ok_or_else(|| invalid("server receipt has no custody root"))?
        .canonicalize()?;
    if !receipt_parent.starts_with(&authority_root) {
        return Err(invalid("server receipt is outside authority custody"));
    }
    Ok(())
}

pub fn probe_endpoint(authority: &ServerAuthority) -> EndpointHealth {
    let address = format!("{}:{}", authority.host, authority.port);
    let Ok(mut addresses) = address.to_socket_addrs() else {
        return EndpointHealth::Dead;
    };
    let Some(address) = addresses.next() else {
        return EndpointHealth::Dead;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(500)) else {
        return EndpointHealth::Dead;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(750)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return EndpointHealth::Dead;
    }
    let mut bytes = [0u8; 256];
    match stream.read(&mut bytes) {
        Ok(0) => EndpointHealth::Dead,
        Ok(length) => {
            let line = String::from_utf8_lossy(&bytes[..length]);
            if line.starts_with("HTTP/1.1 200") || line.starts_with("HTTP/1.0 200") {
                EndpointHealth::Healthy
            } else {
                EndpointHealth::Dead
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::TimedOut => EndpointHealth::Hung,
        Err(_) => EndpointHealth::Dead,
    }
}

fn planned_outage_state(
    daemon: &Daemon,
    resource: &str,
    now_ms: i64,
) -> Result<PlannedOutageState> {
    let conn = daemon.conn()?;
    let row: Option<(i64, i64, Option<i64>)> = conn
        .query_row(
            "SELECT starts_at_ms,ends_at_ms,cancelled_at_ms FROM planned_outages WHERE resource=?1 ORDER BY outage_id DESC LIMIT 1",
            [resource],
            |record| Ok((record.get(0)?, record.get(1)?, record.get(2)?)),
        )
        .optional()?;
    let Some((starts_at_ms, ends_at_ms, cancelled_at_ms)) = row else {
        return Ok(PlannedOutageState::None);
    };
    if cancelled_at_ms.is_some() {
        return Ok(PlannedOutageState::Closed);
    }
    if now_ms < starts_at_ms || now_ms >= ends_at_ms {
        return Ok(PlannedOutageState::Expired);
    }
    Ok(PlannedOutageState::Open)
}

fn sweep_expired_outage(daemon: &Daemon, resource: &str, now_ms: i64) -> Result<()> {
    let conn = daemon.conn()?;
    let changed = conn.execute(
        "DELETE FROM planned_outages WHERE resource=?1 AND cancelled_at_ms IS NULL AND ends_at_ms<=?2",
        rusqlite::params![resource, now_ms],
    )?;
    if changed > 0 {
        conn.execute(
            "INSERT INTO outage_events(resource,ts_ms,kind,payload_json) VALUES(?1,?2,'outage_expired',?3)",
            rusqlite::params![resource, now_ms, serde_json::json!({"count": changed}).to_string()],
        )?;
    }
    Ok(())
}

impl Daemon {
    fn ensure_server_supervisions_table(&self) -> Result<()> {
        self.conn()?.execute_batch(
            "CREATE TABLE IF NOT EXISTS server_supervisions(
               job_id TEXT PRIMARY KEY,
               authority_path TEXT NOT NULL,
               authority_sha256 TEXT NOT NULL,
               receipt_path TEXT NOT NULL,
               restore_manifest_path TEXT NOT NULL,
               required_headroom_bytes INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL
             );",
        )?;
        Ok(())
    }

    pub fn register_server_supervision(&self, request: &ServerLiveCycleRequest) -> Result<()> {
        validate_receipt_destination(&request.authority_path, &request.receipt_path)?;
        let authority = load_authority(&request.authority_path, &request.authority_sha256)?;
        self.ensure_server_supervisions_table()?;
        self.conn()?.execute(
            "INSERT INTO server_supervisions(
               job_id,authority_path,authority_sha256,receipt_path,
               restore_manifest_path,required_headroom_bytes,updated_at_ms
             ) VALUES(?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(job_id) DO UPDATE SET
               authority_path=excluded.authority_path,
               authority_sha256=excluded.authority_sha256,
               receipt_path=excluded.receipt_path,
               restore_manifest_path=excluded.restore_manifest_path,
               required_headroom_bytes=excluded.required_headroom_bytes,
               updated_at_ms=excluded.updated_at_ms",
            rusqlite::params![
                authority.job_id,
                request.authority_path.to_string_lossy(),
                request.authority_sha256,
                request.receipt_path.to_string_lossy(),
                request.restore_manifest_path.to_string_lossy(),
                request.required_headroom_bytes,
                request.now_ms,
            ],
        )?;
        Ok(())
    }

    fn restart_count_last_hour(&self, supervision_id: &str, now_ms: i64) -> Result<u32> {
        if supervision_id.trim().is_empty() {
            return Err(invalid("server supervision identity is missing"));
        }
        let conn = self.conn()?;
        let mut statement = conn.prepare(
            "SELECT payload_json FROM events
             WHERE ts_ms>?1 AND ts_ms<=?2
               AND kind IN ('server_restored','server_restore_failed')",
        )?;
        let rows = statement.query_map(
            rusqlite::params![now_ms.saturating_sub(3_600_000), now_ms],
            |row| row.get::<_, String>(0),
        )?;
        let mut count = 0_u32;
        for row in rows {
            let payload = row?;
            let payload: Value = serde_json::from_str(&payload).map_err(|error| {
                invalid(format!("server restart event is not valid JSON: {error}"))
            })?;
            let recorded = payload
                .get("supervision_id")
                .and_then(Value::as_str)
                .ok_or_else(|| invalid("server restart event lacks stable supervision identity"))?;
            if recorded != supervision_id {
                return Err(invalid(
                    "server restart event has a foreign supervision identity",
                ));
            }
            count = count
                .checked_add(1)
                .ok_or_else(|| invalid("server restart event count overflowed"))?;
        }
        Ok(count)
    }

    fn release_exited_server_lease(&self, authority: &ServerAuthority) -> Result<()> {
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let row: (String, i64, u32, String) = tx.query_row(
            "SELECT state,lease_epoch,pid,resource FROM jobs WHERE job_id=?1",
            [&authority.job_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )?;
        if row.2 != authority.pid {
            return Err(EmberLabError::ProcessIdentityMismatch {
                job_id: authority.job_id.clone(),
                pid: authority.pid,
            });
        }
        if matches!(
            row.0.as_str(),
            "starting" | "prepared" | "running" | "stopping"
        ) {
            return Err(invalid(
                "active server requires a verified stop before handoff",
            ));
        }
        let changed = tx.execute(
            "DELETE FROM leases WHERE resource=?1 AND owner_job_id=?2 AND lease_epoch=?3",
            rusqlite::params![row.3, authority.job_id, row.1],
        )?;
        if changed == 1 {
            tx.execute(
                "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'server_handoff_lease_released','{}')",
                rusqlite::params![authority.job_id, crate::now_ms()],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    fn rebind_server_supervision(
        &self,
        previous: &ServerAuthority,
        request: &ServerLiveCycleRequest,
        outcome: &DispatchOutcome,
    ) -> Result<ServerAuthority> {
        let manifest_bytes = fs::read(&request.restore_manifest_path)?;
        let manifest: DispatchManifest = serde_json::from_slice(&manifest_bytes)
            .map_err(|error| invalid(format!("restore manifest is not closed JSON: {error}")))?;
        if manifest.job_id == previous.job_id {
            return Err(invalid(
                "restore manifest must dispatch a fresh job authority",
            ));
        }
        if manifest.resource_lease != previous.resource_lease {
            return Err(invalid(
                "restore manifest changed the supervised resource lease",
            ));
        }
        if self.job_pid(&manifest.job_id)? != Some(outcome.handle.pid) {
            return Err(EmberLabError::ProcessIdentityMismatch {
                job_id: manifest.job_id,
                pid: outcome.handle.pid,
            });
        }
        if self.lease_owner(&previous.resource_lease)?.as_deref() != Some(manifest.job_id.as_str())
        {
            return Err(EmberLabError::LeaseNotOwned {
                resource: previous.resource_lease.clone(),
                job_id: manifest.job_id,
            });
        }
        let identity_sha256 = self
            .identity_hash(&manifest.job_id)?
            .ok_or_else(|| invalid("restored job has no bound identity"))?;
        let rebound = ServerAuthority {
            schema_version: SERVER_AUTHORITY_SCHEMA.into(),
            job_id: manifest.job_id,
            resource_lease: previous.resource_lease.clone(),
            target: previous.target.clone(),
            host: previous.host.clone(),
            port: previous.port,
            pid: outcome.handle.pid,
            identity_sha256,
        };
        let authority_root = request
            .authority_path
            .parent()
            .ok_or_else(|| invalid("server authority has no custody root"))?;
        let authority_stem = request
            .authority_path
            .file_stem()
            .and_then(|value| value.to_str())
            .ok_or_else(|| invalid("server authority name is invalid"))?;
        let rebound_path = authority_root.join(format!(
            "{authority_stem}-rebound-{}.json",
            &hash_bytes(rebound.job_id.as_bytes())[..16]
        ));
        let rebound_bytes = serde_json::to_vec(&rebound)?;
        atomic_create(&rebound_path, &rebound_bytes)?;
        validate_receipt_destination(&rebound_path, &request.receipt_path)?;
        let rebound_sha256 = hash_bytes(&rebound_bytes);
        self.ensure_server_supervisions_table()?;
        let mut conn = self.conn()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        tx.execute(
            "DELETE FROM server_supervisions WHERE job_id=?1",
            [&previous.job_id],
        )?;
        tx.execute(
            "INSERT INTO server_supervisions(
               job_id,authority_path,authority_sha256,receipt_path,
               restore_manifest_path,required_headroom_bytes,updated_at_ms
             ) VALUES(?1,?2,?3,?4,?5,?6,?7)",
            rusqlite::params![
                &rebound.job_id,
                rebound_path.to_string_lossy(),
                rebound_sha256,
                request.receipt_path.to_string_lossy(),
                request.restore_manifest_path.to_string_lossy(),
                request.required_headroom_bytes,
                request.now_ms,
            ],
        )?;
        tx.commit()?;
        Ok(rebound)
    }

    fn fence_server_for_recovery(
        &self,
        authority: &ServerAuthority,
        process_alive: bool,
    ) -> Result<()> {
        if self.job_pid(&authority.job_id)? != Some(authority.pid) {
            return Err(EmberLabError::ProcessIdentityMismatch {
                job_id: authority.job_id.clone(),
                pid: authority.pid,
            });
        }
        if process_alive {
            if self.lease_owner(&authority.resource_lease)?.as_deref() != Some(&authority.job_id) {
                return Err(EmberLabError::LeaseNotOwned {
                    resource: authority.resource_lease.clone(),
                    job_id: authority.job_id.clone(),
                });
            }
            self.stop_job(&authority.job_id)
        } else {
            self.release_exited_server_lease(authority)
        }
    }

    pub fn supervise_registered_server_once(&self, now_ms: i64) -> Result<Vec<ServerCycleReceipt>> {
        if now_ms < 0 {
            return Err(invalid("server supervision clock is invalid"));
        }
        self.ensure_server_supervisions_table()?;
        let registrations: Vec<ServerLiveCycleRequest> = {
            let conn = self.conn()?;
            let mut statement = conn.prepare(
                "SELECT authority_path,authority_sha256,receipt_path,
                        restore_manifest_path,required_headroom_bytes
                 FROM server_supervisions ORDER BY job_id",
            )?;
            let rows = statement
                .query_map([], |row| {
                    Ok(ServerLiveCycleRequest {
                        authority_path: PathBuf::from(row.get::<_, String>(0)?),
                        authority_sha256: row.get(1)?,
                        receipt_path: PathBuf::from(row.get::<_, String>(2)?),
                        restore_manifest_path: PathBuf::from(row.get::<_, String>(3)?),
                        required_headroom_bytes: row.get(4)?,
                        now_ms,
                    })
                })?
                .collect::<std::result::Result<_, _>>()?;
            rows
        };
        registrations
            .into_iter()
            .map(|mut request| {
                let parent = request
                    .receipt_path
                    .parent()
                    .ok_or_else(|| invalid("server receipt has no custody root"))?;
                let stem = request
                    .receipt_path
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .ok_or_else(|| invalid("server receipt name is invalid"))?;
                request.receipt_path = parent.join(format!("{stem}-{now_ms}.json"));
                self.supervise_server_live_cycle(request)
            })
            .collect()
    }

    pub fn record_supervision_error(&self, now_ms: i64, error: &EmberLabError) -> Result<()> {
        if now_ms < 0 {
            return Err(invalid("server supervision clock is invalid"));
        }
        let directory = self.log_dir.join("server-supervision-errors");
        fs::create_dir_all(&directory)?;
        let path = directory.join(format!("{now_ms}.json"));
        let bytes = serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "ember-lab-supervision-error-v1",
            "observed_at_ms": now_ms,
            "error": error.to_string(),
            "scientific_capability_evidence": false,
        }))?;
        atomic_create(&path, &bytes)?;
        self.conn()?.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,'server_supervision_error',?3)",
            rusqlite::params![
                "ember-lab-supervisor",
                now_ms,
                serde_json::to_string(&serde_json::json!({
                    "receipt_sha256": hash_bytes(&bytes),
                    "error": error.to_string(),
                }))?,
            ],
        )?;
        Ok(())
    }

    /// Run one receipt-bound server supervision cycle through Ember Lab's
    /// identity/lease/activity/atomic-receipt authority.  `restore` is the
    /// current owned-server restore seam; production callers connect it to the
    /// existing governed dispatch path, while tests inject a deterministic
    /// local callback.
    pub fn supervise_server_cycle<F>(
        &self,
        request: ServerCycleRequest,
        restore: F,
    ) -> Result<ServerCycleReceipt>
    where
        F: FnOnce(&ServerAuthority) -> Result<RestoreEvidence>,
    {
        self.supervise_server_cycle_inner(request, restore, false)
    }

    fn supervise_server_cycle_inner<F>(
        &self,
        request: ServerCycleRequest,
        restore: F,
        allow_released_lease: bool,
    ) -> Result<ServerCycleReceipt>
    where
        F: FnOnce(&ServerAuthority) -> Result<RestoreEvidence>,
    {
        let authority = load_authority(&request.authority_path, &request.authority_sha256)?;
        self.verify_identity(&authority.job_id)?;
        let stored_identity = self.identity_hash(&authority.job_id)?.ok_or_else(|| {
            EmberLabError::IdentityNotFound {
                job_id: authority.job_id.clone(),
            }
        })?;
        if stored_identity != authority.identity_sha256 {
            return Err(EmberLabError::IdentityMismatch {
                job_id: authority.job_id.clone(),
                expected: stored_identity,
                actual: authority.identity_sha256.clone(),
            });
        }
        if request.now_ms < 0 {
            return Err(invalid("server cycle clock is invalid"));
        }
        let outage = planned_outage_state(self, &authority.resource_lease, request.now_ms)?;
        if outage == PlannedOutageState::Expired {
            sweep_expired_outage(self, &authority.resource_lease, request.now_ms)?;
        }
        if !allow_released_lease
            && outage != PlannedOutageState::Open
            && self.lease_owner(&authority.resource_lease)?.as_deref() != Some(&authority.job_id)
        {
            return Err(EmberLabError::LeaseNotOwned {
                resource: authority.resource_lease.clone(),
                job_id: authority.job_id.clone(),
            });
        }
        let supervision_id = supervision_identity(&authority.resource_lease);
        let restarts_last_hour = self.restart_count_last_hour(&supervision_id, request.now_ms)?;
        let endpoint = format!("{}:{}", authority.host, authority.port);
        let failure = if request.observation.process_alive {
            match request.observation.endpoint {
                EndpointHealth::Healthy => None,
                EndpointHealth::Dead => Some("endpoint_dead"),
                EndpointHealth::Hung => Some("endpoint_hung"),
            }
        } else {
            Some("process_dead")
        };
        let (decision, death_cause, restore_cost_s, health_status) = match failure {
            None => ("HEALTHY".to_string(), None, None, None),
            Some(cause) if outage == PlannedOutageState::Open => (
                "WAIT_PLANNED_OUTAGE".to_string(),
                Some(cause.to_string()),
                None,
                None,
            ),
            Some(cause) if restarts_last_hour >= 3 => (
                "ALARM_BACKOFF".to_string(),
                Some(cause.to_string()),
                None,
                None,
            ),
            Some(cause) if request.available_headroom_bytes < request.required_headroom_bytes => (
                "RESTORE_REFUSED_HEADROOM".to_string(),
                Some(cause.to_string()),
                None,
                None,
            ),
            Some(cause) => match restore(&authority) {
                Ok(evidence)
                    if evidence.restore_cost_s.is_finite()
                        && evidence.restore_cost_s >= 0.0
                        && evidence.health_status == 200 =>
                {
                    (
                        "RESTORED".to_string(),
                        Some(cause.to_string()),
                        Some(evidence.restore_cost_s),
                        Some(evidence.health_status),
                    )
                }
                Ok(evidence) => (
                    "RESTORE_FAILED".to_string(),
                    Some(cause.to_string()),
                    Some(evidence.restore_cost_s),
                    Some(evidence.health_status),
                ),
                Err(_error) => (
                    "RESTORE_FAILED".to_string(),
                    Some(cause.to_string()),
                    None,
                    None,
                ),
            },
        };
        let activity_event = match decision.as_str() {
            "HEALTHY" => "server_healthy",
            "WAIT_PLANNED_OUTAGE" => "server_wait_planned_outage",
            "ALARM_BACKOFF" => "server_alarm_backoff",
            "RESTORE_REFUSED_HEADROOM" => "server_restore_refused_headroom",
            "RESTORED" => "server_restored",
            _ => "server_restore_failed",
        };
        let receipt = ServerCycleReceipt {
            authority_sha256: request.authority_sha256,
            supervision_id: supervision_id.clone(),
            job_id: authority.job_id.clone(),
            target: authority.target.clone(),
            endpoint,
            observed_at_ms: request.now_ms,
            process_alive: request.observation.process_alive,
            endpoint_health: request.observation.endpoint.as_str().into(),
            outage_state: outage.as_str().into(),
            decision,
            death_cause,
            restore_cost_s,
            health_status,
            restarts_last_hour,
            activity_event: activity_event.into(),
        };
        let receipt_bytes = serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "ember-lab-operational-receipt-v1",
            "ember_lab_identity": {
                "binary_sha256": &self.ember_lab_binary_sha256,
                "source_sha256": &self.ember_lab_source_sha256,
            },
            "job_id": &authority.job_id,
            "supervision_id": &supervision_id,
            "identity_sha256": &authority.identity_sha256,
            "resource_lease": &authority.resource_lease,
            "state": "running",
            "events": [{
                "kind": activity_event,
                "payload": receipt,
            }],
            "outage_events": [],
            "scientific_capability_evidence": false,
        }))?;
        validate_receipt_destination(&request.authority_path, &request.receipt_path)?;
        atomic_create(&request.receipt_path, &receipt_bytes)?;
        self.conn()?.execute(
            "INSERT INTO events(job_id,ts_ms,kind,payload_json) VALUES(?1,?2,?3,?4)",
            rusqlite::params![
                &authority.job_id,
                request.now_ms,
                activity_event,
                serde_json::to_string(&receipt)?
            ],
        )?;
        Ok(receipt)
    }

    /// Production Ember Lab bridge: derive process/endpoint state, then invoke
    /// the existing governed dispatch path as the restore callback. No
    /// historical launcher or parallel supervisor is created here.
    pub fn supervise_server_live_cycle(
        &self,
        request: ServerLiveCycleRequest,
    ) -> Result<ServerCycleReceipt> {
        self.supervise_server_live_cycle_with_dispatch(request, |daemon, path| {
            daemon.dispatch_manifest(path)
        })
    }

    fn supervise_server_live_cycle_with_dispatch<F>(
        &self,
        request: ServerLiveCycleRequest,
        dispatch: F,
    ) -> Result<ServerCycleReceipt>
    where
        F: FnOnce(&Daemon, &std::path::Path) -> Result<DispatchOutcome>,
    {
        self.register_server_supervision(&request)?;
        let authority = load_authority(&request.authority_path, &request.authority_sha256)?;
        if let Some(pid) = self.job_pid(&authority.job_id)? {
            if pid != authority.pid {
                return Err(EmberLabError::ProcessIdentityMismatch {
                    job_id: authority.job_id.clone(),
                    pid: authority.pid,
                });
            }
        }
        let process_alive = matches!(
            self.job_state(&authority.job_id)?,
            Some(crate::JobState::Starting | crate::JobState::Prepared | crate::JobState::Running)
        );
        let observation = ServerObservation {
            process_alive,
            endpoint: probe_endpoint(&authority),
        };
        let available_headroom_bytes = self
            .resource_guard_status()?
            .get("observation")
            .and_then(|observation| observation.get("physical_available_bytes"))
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(0);
        let outage = planned_outage_state(self, &authority.resource_lease, request.now_ms)?;
        if outage == PlannedOutageState::Expired {
            sweep_expired_outage(self, &authority.resource_lease, request.now_ms)?;
        }
        let supervision_id = supervision_identity(&authority.resource_lease);
        let restarts_last_hour = self.restart_count_last_hour(&supervision_id, request.now_ms)?;
        let restore_authorized = outage != PlannedOutageState::Open
            && restarts_last_hour < 3
            && available_headroom_bytes >= request.required_headroom_bytes
            && (!process_alive
                || matches!(
                    observation.endpoint,
                    EndpointHealth::Dead | EndpointHealth::Hung
                ));
        if restore_authorized {
            self.fence_server_for_recovery(&authority, process_alive)?;
        }
        let registration = request.clone();
        let cycle = ServerCycleRequest {
            authority_path: request.authority_path,
            authority_sha256: request.authority_sha256,
            receipt_path: request.receipt_path,
            observation,
            available_headroom_bytes,
            required_headroom_bytes: request.required_headroom_bytes,
            now_ms: request.now_ms,
        };
        let manifest_path = request.restore_manifest_path;
        self.supervise_server_cycle_inner(
            cycle,
            |authority| {
                let started = Instant::now();
                let outcome = dispatch(self, &manifest_path)?;
                let rebound = self.rebind_server_supervision(authority, &registration, &outcome)?;
                let health = probe_endpoint(&rebound);
                Ok(RestoreEvidence {
                    restore_cost_s: started.elapsed().as_secs_f64(),
                    health_status: if health == EndpointHealth::Healthy {
                        200
                    } else {
                        503
                    },
                })
            },
            true,
        )
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    use crate::{Daemon, JobSpec, ReceiptArtifact};
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::fs;
    use std::net::TcpListener;
    use std::path::{Path, PathBuf};
    use std::thread;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn sandbox(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "ember-lab-supervisor-{name}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    fn sha256(path: &Path) -> String {
        format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
    }

    #[test]
    fn successful_dispatch_rebinds_authority_before_next_tick() {
        let root = sandbox("rebind");
        let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
        let old_identity = root.join("old-identity.json");
        fs::write(&old_identity, br#"{"schema":"old"}"#).unwrap();
        let old_identity_sha = sha256(&old_identity);
        daemon
            .bind_identity("old-server-job", &old_identity, &old_identity_sha)
            .unwrap();
        let manifest_path = root.join("restore-manifest.json");
        let manifest = json!({
            "schema_version": "ember-lab-dispatch-manifest-v3",
            "job_id": "restored-server-job",
            "source_commit": "5326043c344227c1b145a4ddbb3519cfa62d4943",
            "not_before_ms": 0,
            "expires_at_ms": 60_000,
            "resource_lease": "server:8082",
            "program": {"path": "C:\\Windows\\System32\\cmd.exe", "sha256": "a".repeat(64)},
            "args": ["/C", "ping", "127.0.0.1", "-n", "30"],
            "workload_profile": {
                "profile_id": "evidence_verifier",
                "pinned_host_producers": [{"kind": "receipt_verifier", "maximum_bytes": 1}],
                "requires_ui_responsiveness": false
            },
            "env": {},
            "bindings": [],
            "custody_root": root,
            "storage_reserves": [],
            "minimum_free_vram_bytes": 1,
            "required_available_maximum_commit_bytes": 1,
            "maximum_job_memory_bytes": 1,
            "simulated_peak_commit_bytes": 1,
            "preflight_receipt": root.join("preflight.json")
        });
        let manifest_bytes = serde_json::to_vec(&manifest).unwrap();
        fs::write(&manifest_path, &manifest_bytes).unwrap();
        let manifest_sha = sha256(&manifest_path);
        daemon
            .bind_identity("restored-server-job", &manifest_path, &manifest_sha)
            .unwrap();
        daemon
            .acquire_lease("server:8082", "restored-server-job")
            .unwrap();
        let started = daemon
            .start_job(JobSpec::new(
                "restored-server-job",
                std::env::var("COMSPEC").unwrap(),
                ["/C", "ping", "127.0.0.1", "-n", "30"],
                "server:8082",
            ))
            .unwrap();
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let _ = std::io::Write::write_all(
                    &mut stream,
                    b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
                );
            }
        });
        let old_authority = ServerAuthority {
            schema_version: SERVER_AUTHORITY_SCHEMA.into(),
            job_id: "old-server-job".into(),
            resource_lease: "server:8082".into(),
            target: "llama-server".into(),
            host: "127.0.0.1".into(),
            port,
            pid: 1,
            identity_sha256: old_identity_sha,
        };
        let old_authority_path = root.join("server-authority.json");
        let old_authority_bytes = serde_json::to_vec(&old_authority).unwrap();
        fs::write(&old_authority_path, &old_authority_bytes).unwrap();
        let request = ServerLiveCycleRequest {
            authority_path: old_authority_path,
            authority_sha256: hash_bytes(&old_authority_bytes),
            receipt_path: root.join("supervision-receipt.json"),
            restore_manifest_path: manifest_path,
            required_headroom_bytes: 1,
            now_ms: 1_000,
        };
        daemon.register_server_supervision(&request).unwrap();
        let rebound = daemon
            .rebind_server_supervision(
                &old_authority,
                &request,
                &DispatchOutcome {
                    handle: crate::JobHandle { pid: started.pid },
                    receipt: ReceiptArtifact {
                        path: root.join("dispatch-receipt.json"),
                        sha256: "a".repeat(64),
                    },
                },
            )
            .unwrap();
        assert_eq!(rebound.job_id, "restored-server-job");
        let receipt = daemon
            .supervise_registered_server_once(2_000)
            .unwrap()
            .pop()
            .unwrap();
        assert_eq!(receipt.decision, "HEALTHY");
        assert_eq!(receipt.job_id, "restored-server-job");
        daemon.stop_job("restored-server-job").unwrap();
        server.join().unwrap();
    }
}
