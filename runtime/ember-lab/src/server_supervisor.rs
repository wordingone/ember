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

use crate::{atomic_create, hash_bytes, Daemon, EmberLabError, Result};
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::time::{Duration, Instant};

pub const SERVER_AUTHORITY_SCHEMA: &str = "ember-lab-server-authority-v1";

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
    pub restarts_last_hour: u32,
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
    pub restarts_last_hour: u32,
    pub required_headroom_bytes: u64,
    pub now_ms: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServerCycleReceipt {
    pub authority_sha256: String,
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
        if self.lease_owner(&authority.resource_lease)?.as_deref() != Some(&authority.job_id) {
            return Err(EmberLabError::LeaseNotOwned {
                resource: authority.resource_lease.clone(),
                job_id: authority.job_id.clone(),
            });
        }
        if request.now_ms < 0 || request.restarts_last_hour > 10_000 {
            return Err(invalid("server cycle clock/restart count is invalid"));
        }
        let outage = planned_outage_state(self, &authority.resource_lease, request.now_ms)?;
        if outage == PlannedOutageState::Expired {
            sweep_expired_outage(self, &authority.resource_lease, request.now_ms)?;
        }
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
            Some(cause) if request.restarts_last_hour >= 3 => (
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
                Err(_) => (
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
            restarts_last_hour: request.restarts_last_hour,
            activity_event: activity_event.into(),
        };
        let receipt_bytes = serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "ember-lab-operational-receipt-v1",
            "ember_lab_identity": {
                "binary_sha256": &self.ember_lab_binary_sha256,
                "source_sha256": &self.ember_lab_source_sha256,
            },
            "job_id": &authority.job_id,
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
        let cycle = ServerCycleRequest {
            authority_path: request.authority_path,
            authority_sha256: request.authority_sha256,
            receipt_path: request.receipt_path,
            observation,
            restarts_last_hour: request.restarts_last_hour,
            available_headroom_bytes,
            required_headroom_bytes: request.required_headroom_bytes,
            now_ms: request.now_ms,
        };
        let manifest_path = request.restore_manifest_path;
        self.supervise_server_cycle(cycle, |authority| {
            let started = Instant::now();
            let _outcome = self.dispatch_manifest(&manifest_path)?;
            let health = probe_endpoint(authority);
            Ok(RestoreEvidence {
                restore_cost_s: started.elapsed().as_secs_f64(),
                health_status: if health == EndpointHealth::Healthy {
                    200
                } else {
                    503
                },
            })
        })
    }
}
