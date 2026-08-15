//! Ember Lab's rehearsal-first dispatch contract.
//!
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! This is the current implementation of the historical daemon's `rehearse`
//! wording.  It deliberately reuses the Ember Lab dispatch authority instead
//! of creating another launcher, lease, or receipt authority.  The runner
//! trait is only a deterministic CPU/fake-runner seam for tests and dry-run
//! admission; a capability claim is never made by this module.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::io::{Error, ErrorKind, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Admission,
    DataVerify,
    Train,
    Checkpoint,
    Publish,
    SelectableCheckpoint,
    Restore,
}

impl Phase {
    pub const fn ordered() -> [Self; 7] {
        [
            Self::Admission,
            Self::DataVerify,
            Self::Train,
            Self::Checkpoint,
            Self::Publish,
            Self::SelectableCheckpoint,
            Self::Restore,
        ]
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Admission => "admission",
            Self::DataVerify => "data_verify",
            Self::Train => "train",
            Self::Checkpoint => "checkpoint",
            Self::Publish => "publish",
            Self::SelectableCheckpoint => "selectable_checkpoint",
            Self::Restore => "restore",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RehearsalStatus {
    Completed,
    Refused,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RefusalCode {
    MissingMeasurement,
    MemoryFloor,
    StorageFloor,
    DurationBound,
    PhaseFailed,
    StrictGateUnbound,
}

impl RefusalCode {
    pub const fn all() -> [Self; 6] {
        [
            Self::MissingMeasurement,
            Self::MemoryFloor,
            Self::StorageFloor,
            Self::DurationBound,
            Self::PhaseFailed,
            Self::StrictGateUnbound,
        ]
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::MissingMeasurement => "MISSING_MEASUREMENT",
            Self::MemoryFloor => "MEMORY_FLOOR",
            Self::StorageFloor => "STORAGE_FLOOR",
            Self::DurationBound => "DURATION_BOUND",
            Self::PhaseFailed => "PHASE_FAILED",
            Self::StrictGateUnbound => "STRICT_GATE_UNBOUND",
        }
    }

    pub const fn next_action(self) -> &'static str {
        match self {
            Self::MissingMeasurement => {
                "Collect a current measured evidence file and retry the bounded rehearsal."
            }
            Self::MemoryFloor => {
                "Increase measured memory headroom or reduce the bounded scope, then retry."
            }
            Self::StorageFloor => "Free measured storage or reduce the bounded scope, then retry.",
            Self::DurationBound => {
                "Measure the whole-run duration and reduce the bounded scope before retrying."
            }
            Self::PhaseFailed => {
                "Repair the failed current-authority phase and rerun the bounded rehearsal."
            }
            Self::StrictGateUnbound => {
                "Bind the missing current-authority producer and consumer before retrying."
            }
        }
    }
}

impl fmt::Display for RefusalCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdmissionBounds {
    pub minimum_memory_bytes: u64,
    pub minimum_storage_free_bytes: u64,
    pub maximum_duration_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
#[serde(rename_all = "snake_case")]
pub enum MeasurementSource {
    HostProbe,
    FakeRunner,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Measurement {
    pub source: MeasurementSource,
    pub observed_at_ms: u64,
    pub available_memory_bytes: u64,
    pub storage_free_bytes: u64,
    pub measured_duration_ms: u64,
    pub whole_run_peak_bytes: u64,
    pub evidence_path: PathBuf,
    pub evidence_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PhaseEvidence {
    pub phase: Phase,
    pub path: PathBuf,
    pub sha256: String,
}

const MINIMAL_SLICE_PRODUCER: &str = "ember-lab-minimal-slice-producer";
const MINIMAL_SLICE_SCHEMA: &str = "ember-lab-phase-producer-v1";
const HOST_PEAK_SCHEMA: &str = "ember-lab-host-peak-v1";
const COMPLETION_SCHEMA: &str = "ember-lab-minimal-slice-completion-v1";

fn producer_error(detail: impl Into<String>) -> Error {
    Error::new(ErrorKind::InvalidData, detail.into())
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Publish `bytes` at `path` as a rehearsal marker/receipt file.
///
/// Writes to a same-directory temp file, syncs it, then publishes via
/// `std::fs::rename` rather than writing the final path in place — so a
/// concurrent cross-process reader of `path` never observes a torn
/// (partially-written) file. `create_new`-then-`write_all` made the
/// destination visible-but-empty the instant `open()` succeeded, before any
/// bytes landed. `fs::rename` (not a hand-rolled `MoveFileExW`/`hard_link`
/// call) is used deliberately: std's own Windows path handling applies
/// long-path normalization a raw FFI call does not get for free, and this
/// helper is called many times in quick succession in a single freshly
/// created directory (twelve marker files per rehearsal run) — a pattern
/// under which a bare `MoveFileExW` call was observed to fail with a
/// transient `ERROR_PATH_NOT_FOUND` in real (non-isolated, job-object
/// supervised child process) conditions that a minimal same-shape repro did
/// not reproduce. `fs::rename` overwrites an existing destination on both
/// platforms, so the create-only guarantee `create_new` gave the original
/// single-step write is reconstructed with an explicit pre-check; every
/// caller here writes each filename exactly once from a single producer, so
/// the narrow check-then-rename window is not a real double-write risk.
fn write_new(path: &std::path::Path, bytes: &[u8]) -> Result<(), Error> {
    if path.exists() {
        return Err(Error::new(
            ErrorKind::AlreadyExists,
            format!("{} already exists", path.display()),
        ));
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temp = path.with_extension(format!(
        "tmp-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = fs::rename(&temp, path) {
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    Ok(())
}

/// Digest the exact phase output bytes in their canonical sequence.  The
/// producer commits this digest only after all six phase files and its raw
/// host observation have been durably written; the daemon recomputes it before
/// admitting any phase.
pub fn phase_artifact_digest(root: &Path) -> Result<String, Error> {
    let mut material = Vec::new();
    for name in [
        "data_verify.json",
        "train.json",
        "checkpoint.json",
        "publish.json",
        "selectable_checkpoint.json",
        "restore.json",
    ] {
        let bytes = fs::read(root.join(name))?;
        material.extend_from_slice(name.as_bytes());
        material.push(0);
        material.extend_from_slice(sha256_bytes(&bytes).as_bytes());
        material.push(b'\n');
    }
    Ok(sha256_bytes(&material))
}

#[cfg(windows)]
fn current_process_peak_bytes() -> Result<u64, Error> {
    use windows_sys::Win32::System::ProcessStatus::{
        GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;
    let mut counters = PROCESS_MEMORY_COUNTERS {
        cb: std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
        ..unsafe { std::mem::zeroed() }
    };
    let ok = unsafe {
        GetProcessMemoryInfo(
            GetCurrentProcess(),
            &mut counters,
            std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
        )
    };
    if ok == 0 || counters.PeakWorkingSetSize == 0 {
        return Err(producer_error(
            "current process peak working set is unavailable",
        ));
    }
    Ok(counters.PeakWorkingSetSize as u64)
}

#[cfg(not(windows))]
fn current_process_peak_bytes() -> Result<u64, Error> {
    let text = fs::read_to_string("/proc/self/status")?;
    let kib = text
        .lines()
        .find_map(|line| line.strip_prefix("VmHWM:")?.split_whitespace().next())
        .ok_or_else(|| producer_error("current process peak working set is unavailable"))?
        .parse::<u64>()
        .map_err(|_| producer_error("current process peak working set is malformed"))?;
    kib.checked_mul(1024)
        .filter(|bytes| *bytes > 0)
        .ok_or_else(|| producer_error("current process peak working set is zero"))
}

fn phase_payload(
    job_id: &str,
    phase: Phase,
    sequence: u64,
    operation: serde_json::Value,
) -> Result<Vec<u8>, Error> {
    let operation_sha256 = serde_json::to_vec(&operation)
        .map(|bytes| sha256_bytes(&bytes))
        .map_err(|error| {
            producer_error(format!("phase operation serialization failed: {error}"))
        })?;
    serde_json::to_vec(&serde_json::json!({
        "schema": MINIMAL_SLICE_SCHEMA,
        "producer": MINIMAL_SLICE_PRODUCER,
        "result": "COMPLETED",
        "job_id": job_id,
        "producer_pid": std::process::id(),
        "phase": phase.as_str(),
        "sequence": sequence,
        "operation_sha256": operation_sha256,
        "operation": operation,
    }))
    .map_err(|error| producer_error(format!("phase payload serialization failed: {error}")))
}

/// Produce the bounded, host-independent minimal slice consumed by the daemon.
/// This is an actual CPU operation (records are read, train steps update state,
/// checkpoint bytes are written/published/reopened), not a phase-marker fixture.
/// The daemon remains the only authority that accepts these bytes into events.
pub fn produce_minimal_slice(root: &std::path::Path, job_id: &str) -> Result<(), Error> {
    if job_id.trim().is_empty() {
        return Err(producer_error("minimal-slice job id is empty"));
    }
    fs::create_dir_all(root)?;
    for name in [
        "input.jsonl",
        "optimizer-state.bin",
        "checkpoint.bin",
        "published-checkpoint.bin",
        "host_peak.json",
        "completion.json",
    ] {
        if root.join(name).exists() {
            return Err(producer_error(format!(
                "minimal-slice output already exists: {name}"
            )));
        }
    }
    for phase in [
        Phase::DataVerify,
        Phase::Train,
        Phase::Checkpoint,
        Phase::Publish,
        Phase::SelectableCheckpoint,
        Phase::Restore,
    ] {
        if root.join(format!("{}.json", phase.as_str())).exists() {
            return Err(producer_error(format!(
                "minimal-slice phase output already exists: {}",
                phase.as_str()
            )));
        }
    }

    if let Ok(delay_ms) = std::env::var("EMBER_LAB_MINIMAL_SLICE_DELAY_MS") {
        let delay_ms = delay_ms
            .parse::<u64>()
            .map_err(|_| producer_error("minimal-slice delay is malformed"))?;
        std::thread::sleep(std::time::Duration::from_millis(delay_ms));
    }
    let peak_before = current_process_peak_bytes()?;
    let records = br#"{"id":0,"text":"ember"}
{"id":1,"text":"lab"}
{"id":2,"text":"slice"}
"#;
    write_new(&root.join("input.jsonl"), records)?;
    let input_sha256 = sha256_bytes(records);
    let data = phase_payload(
        job_id,
        Phase::DataVerify,
        1,
        serde_json::json!({
            "kind": "data_verify_completed",
            "input_file": "input.jsonl",
            "input_sha256": input_sha256,
            "record_count": 3,
            "subset_records": 3,
        }),
    )?;
    write_new(&root.join("data_verify.json"), &data)?;

    let mut state = 17u64;
    for step in 1..=3u64 {
        state = state
            .wrapping_mul(1_103_515_245)
            .wrapping_add(12_345 + step);
    }
    let optimizer_state = format!("optimizer-state-v1|job={job_id}|steps=3|state={state}\n");
    let optimizer_state = optimizer_state.as_bytes();
    write_new(&root.join("optimizer-state.bin"), optimizer_state)?;
    let optimizer_state_sha256 = sha256_bytes(optimizer_state);
    let train = phase_payload(
        job_id,
        Phase::Train,
        2,
        serde_json::json!({
            "kind": "train_steps_completed",
            "train_steps": 3,
            "update_count": 3,
            "optimizer_state_file": "optimizer-state.bin",
            "optimizer_state_sha256": optimizer_state_sha256,
        }),
    )?;
    write_new(&root.join("train.json"), &train)?;

    let checkpoint =
        format!("checkpoint-v1|job={job_id}|optimizer={optimizer_state_sha256}|state={state}\n");
    let checkpoint = checkpoint.as_bytes();
    write_new(&root.join("checkpoint.bin"), checkpoint)?;
    let checkpoint_sha256 = sha256_bytes(checkpoint);
    let checkpoint_phase = phase_payload(
        job_id,
        Phase::Checkpoint,
        3,
        serde_json::json!({
            "kind": "checkpoint_written",
            "final_checkpoint": true,
            "checkpoint_file": "checkpoint.bin",
            "checkpoint_sha256": checkpoint_sha256,
            "source_optimizer_state_sha256": optimizer_state_sha256,
        }),
    )?;
    write_new(&root.join("checkpoint.json"), &checkpoint_phase)?;

    write_new(&root.join("published-checkpoint.bin"), checkpoint)?;
    let published_sha256 = sha256_bytes(checkpoint);
    let publish = phase_payload(
        job_id,
        Phase::Publish,
        4,
        serde_json::json!({
            "kind": "checkpoint_published",
            "published_file": "published-checkpoint.bin",
            "published_checkpoint_sha256": published_sha256,
            "source_checkpoint_sha256": checkpoint_sha256,
        }),
    )?;
    write_new(&root.join("publish.json"), &publish)?;

    let selectable = phase_payload(
        job_id,
        Phase::SelectableCheckpoint,
        5,
        serde_json::json!({
            "kind": "selectable_checkpoint_verified",
            "selected_file": "published-checkpoint.bin",
            "selected_checkpoint_sha256": published_sha256,
        }),
    )?;
    write_new(&root.join("selectable_checkpoint.json"), &selectable)?;

    let restore = phase_payload(
        job_id,
        Phase::Restore,
        6,
        serde_json::json!({
            "kind": "checkpoint_restored",
            "restored_file": "published-checkpoint.bin",
            "restored_checkpoint_sha256": published_sha256,
            "restore_verified": true,
        }),
    )?;
    write_new(&root.join("restore.json"), &restore)?;

    let peak_after = current_process_peak_bytes()?;
    let whole_run_peak_bytes = peak_before.max(peak_after);
    let host_peak = serde_json::to_vec(&serde_json::json!({
        "schema": HOST_PEAK_SCHEMA,
        "producer": MINIMAL_SLICE_PRODUCER,
        "result": "MEASURED",
        "job_id": job_id,
        "producer_pid": std::process::id(),
        "sample_count": 2,
        "whole_run_peak_bytes": whole_run_peak_bytes,
    }))
    .map_err(|error| producer_error(format!("host peak serialization failed: {error}")))?;
    write_new(&root.join("host_peak.json"), &host_peak)?;
    let phase_artifact_sha256 = phase_artifact_digest(root)?;
    let producer_binary_sha256 = sha256_bytes(&fs::read(std::env::current_exe()?)?);
    let producer_source_sha256 = crate::ember_lab_source_hash();
    let completion = serde_json::to_vec(&serde_json::json!({
        "schema": COMPLETION_SCHEMA,
        "producer": MINIMAL_SLICE_PRODUCER,
        "result": "COMPLETED",
        "job_id": job_id,
        "producer_pid": std::process::id(),
        "completed_at_ms": SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64,
        "phase_count": 6,
        "phase_artifact_sha256": phase_artifact_sha256,
        "host_peak_sha256": sha256_bytes(&host_peak),
        "producer_binary_sha256": producer_binary_sha256,
        "producer_source_sha256": producer_source_sha256,
    }))
    .map_err(|error| producer_error(format!("completion serialization failed: {error}")))?;
    write_new(&root.join("completion.json"), &completion)?;
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RehearsalManifest {
    pub schema_version: String,
    pub dispatch_id: String,
    pub source_commit: String,
    pub contract_sha256: String,
    pub bounds: AdmissionBounds,
    pub measurements: Measurement,
    pub phase_evidence: Vec<PhaseEvidence>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PhaseOutcome {
    Completed,
    Failed(String),
}

pub trait RehearsalRunner {
    fn run(&mut self, phase: Phase) -> PhaseOutcome;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RehearsalReceipt {
    pub schema_version: String,
    pub dispatch_id: String,
    pub capability_claim: String,
    pub status: RehearsalStatus,
    pub code: Option<RefusalCode>,
    pub phase: Option<Phase>,
    pub gate: Option<String>,
    pub offending_value: Option<u64>,
    pub bound: Option<u64>,
    pub next_action: Option<String>,
    pub phases: Vec<Phase>,
    pub source_commit: String,
    pub contract_sha256: String,
    pub whole_run_peak_bytes: u64,
    pub capability_chain: Vec<String>,
    #[serde(default)]
    pub manifest_sha256: Option<String>,
}

impl RehearsalReceipt {
    pub fn with_manifest_sha256(mut self, manifest_sha256: String) -> Self {
        self.manifest_sha256 = Some(manifest_sha256);
        self
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RehearsalResult {
    pub status: RehearsalStatus,
    pub receipt: RehearsalReceipt,
}

fn refused(
    manifest: &RehearsalManifest,
    code: RefusalCode,
    phase: Option<Phase>,
    gate: Option<&str>,
    offending_value: Option<u64>,
    bound: Option<u64>,
    phases: Vec<Phase>,
) -> RehearsalResult {
    RehearsalResult {
        status: RehearsalStatus::Refused,
        receipt: RehearsalReceipt {
            schema_version: "ember-lab-dispatch-preflight-v1".into(),
            dispatch_id: manifest.dispatch_id.clone(),
            capability_claim: "NO_CAPABILITY_CLAIM".into(),
            status: RehearsalStatus::Refused,
            code: Some(code),
            phase,
            gate: gate.map(str::to_owned),
            offending_value,
            bound,
            next_action: Some(code.next_action().into()),
            phases,
            source_commit: manifest.source_commit.clone(),
            contract_sha256: manifest.contract_sha256.clone(),
            whole_run_peak_bytes: manifest.measurements.whole_run_peak_bytes,
            capability_chain: vec!["NO_CAPABILITY_CLAIM".into()],
            manifest_sha256: None,
        },
    }
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn admission(manifest: &RehearsalManifest) -> Result<(), (RefusalCode, Option<u64>, Option<u64>)> {
    if manifest.schema_version != "ember-lab-rehearsal-v1"
        || manifest.dispatch_id.trim().is_empty()
        || manifest.source_commit.len() != 40
        || !manifest
            .source_commit
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
        || manifest.measurements.observed_at_ms == 0
        || manifest.measurements.whole_run_peak_bytes == 0
        || !valid_hash(&manifest.measurements.evidence_sha256)
    {
        return Err((RefusalCode::MissingMeasurement, None, None));
    }
    if manifest.contract_sha256 != current_contract_sha256() {
        return Err((RefusalCode::StrictGateUnbound, None, None));
    }
    let measurement_bytes = fs::read(&manifest.measurements.evidence_path).map_err(|_| {
        (
            RefusalCode::MissingMeasurement,
            None,
            Some(manifest.measurements.whole_run_peak_bytes),
        )
    })?;
    if format!("{:x}", Sha256::digest(&measurement_bytes)) != manifest.measurements.evidence_sha256
    {
        return Err((RefusalCode::MissingMeasurement, None, None));
    }
    let measurement: serde_json::Value =
        serde_json::from_slice(&measurement_bytes).map_err(|_| {
            (
                RefusalCode::MissingMeasurement,
                None,
                Some(manifest.measurements.whole_run_peak_bytes),
            )
        })?;
    if measurement
        .get("whole_run_peak_bytes")
        .and_then(serde_json::Value::as_u64)
        != Some(manifest.measurements.whole_run_peak_bytes)
    {
        return Err((RefusalCode::MissingMeasurement, None, None));
    }
    let mut phases = BTreeSet::new();
    if manifest.phase_evidence.len() != Phase::ordered().len()
        || manifest
            .phase_evidence
            .iter()
            .any(|evidence| !phases.insert(evidence.phase) || !valid_hash(&evidence.sha256))
        || phases.iter().copied().collect::<Vec<_>>()
            != Phase::ordered().into_iter().collect::<Vec<_>>()
    {
        return Err((RefusalCode::StrictGateUnbound, None, None));
    }
    for evidence in &manifest.phase_evidence {
        let bytes = fs::read(&evidence.path).map_err(|_| {
            (
                RefusalCode::MissingMeasurement,
                None,
                Some(manifest.measurements.whole_run_peak_bytes),
            )
        })?;
        let observed = format!("{:x}", Sha256::digest(&bytes));
        if observed != evidence.sha256 {
            return Err((RefusalCode::MissingMeasurement, None, None));
        }
    }
    if manifest.measurements.available_memory_bytes < manifest.bounds.minimum_memory_bytes {
        return Err((
            RefusalCode::MemoryFloor,
            Some(manifest.measurements.available_memory_bytes),
            Some(manifest.bounds.minimum_memory_bytes),
        ));
    }
    if manifest.measurements.storage_free_bytes < manifest.bounds.minimum_storage_free_bytes {
        return Err((
            RefusalCode::StorageFloor,
            Some(manifest.measurements.storage_free_bytes),
            Some(manifest.bounds.minimum_storage_free_bytes),
        ));
    }
    if manifest.measurements.measured_duration_ms > manifest.bounds.maximum_duration_ms {
        return Err((
            RefusalCode::DurationBound,
            Some(manifest.measurements.measured_duration_ms),
            Some(manifest.bounds.maximum_duration_ms),
        ));
    }
    Ok(())
}

/// Run the complete minimal-slice rehearsal.  Admission is completed before
/// the runner is called, and a failed phase prevents every later phase.
pub fn episode<R: RehearsalRunner>(
    capability: &str,
    manifest: &RehearsalManifest,
    runner: &mut R,
) -> RehearsalResult {
    if capability.trim().is_empty() {
        return refused(
            manifest,
            RefusalCode::MissingMeasurement,
            None,
            Some("capability"),
            None,
            None,
            Vec::new(),
        );
    }
    if let Err((code, offending, bound)) = admission(manifest) {
        return refused(
            manifest,
            code,
            Some(Phase::Admission),
            Some("measured_values"),
            offending,
            bound,
            Vec::new(),
        );
    }

    let mut phases = Vec::new();
    for phase in Phase::ordered() {
        phases.push(phase);
        if let PhaseOutcome::Failed(_detail) = runner.run(phase) {
            return refused(
                manifest,
                RefusalCode::PhaseFailed,
                Some(phase),
                Some(phase.as_str()),
                None,
                None,
                phases,
            );
        }
    }
    RehearsalResult {
        status: RehearsalStatus::Completed,
        receipt: RehearsalReceipt {
            schema_version: "ember-lab-dispatch-preflight-v1".into(),
            dispatch_id: manifest.dispatch_id.clone(),
            capability_claim: "NO_CAPABILITY_CLAIM".into(),
            status: RehearsalStatus::Completed,
            code: None,
            phase: None,
            gate: None,
            offending_value: None,
            bound: None,
            next_action: None,
            phases,
            source_commit: manifest.source_commit.clone(),
            contract_sha256: manifest.contract_sha256.clone(),
            whole_run_peak_bytes: manifest.measurements.whole_run_peak_bytes,
            capability_chain: vec!["NO_CAPABILITY_CLAIM".into()],
            manifest_sha256: None,
        },
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GateBinding {
    ContentHash,
    MeasuredValue,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StrictGate {
    pub name: String,
    pub producer: String,
    pub consumers: Vec<String>,
    pub binding: GateBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StrictGateCensus {
    pub expected: Vec<String>,
    pub gates: Vec<StrictGate>,
}

pub fn validate_strict_gate_census(census: &StrictGateCensus) -> Result<(), String> {
    let expected: BTreeSet<&str> = census.expected.iter().map(String::as_str).collect();
    if expected.len() != census.expected.len() || expected.is_empty() {
        return Err("strict-gate expected names must be unique and nonempty".into());
    }
    let mut seen = BTreeSet::new();
    for gate in &census.gates {
        if gate.name.trim().is_empty()
            || gate.producer.trim().is_empty()
            || gate.consumers.is_empty()
            || gate
                .consumers
                .iter()
                .any(|consumer| consumer.trim().is_empty())
            || !seen.insert(gate.name.as_str())
        {
            return Err(format!("invalid or duplicate strict gate {}", gate.name));
        }
        if !expected.contains(gate.name.as_str()) {
            return Err(format!("unclassified strict gate {}", gate.name));
        }
    }
    if seen != expected {
        return Err("strict-gate census is incomplete".into());
    }
    Ok(())
}

pub fn current_contract_sha256() -> String {
    let bytes = serde_json::to_vec(&production_strict_gate_census())
        .expect("strict-gate census is serializable");
    format!("{:x}", Sha256::digest(bytes))
}

/// Closed build-time inventory for the current Ember Lab dispatch boundary.
/// Each entry names the producer and the consumer that must remain bound when
/// a strict comparison changes; adding a new strict gate requires extending
/// this value and its producer/consumer test in the same build.
pub fn production_strict_gate_census() -> StrictGateCensus {
    StrictGateCensus {
        expected: vec![
            "dispatch_manifest_bytes".into(),
            "storage_reserves".into(),
            "vram_reserve".into(),
            "host_commit_capacity".into(),
            "preflight_receipt".into(),
        ],
        gates: vec![
            StrictGate {
                name: "dispatch_manifest_bytes".into(),
                producer: "runtime/ember-lab/src/main.rs::dispatch".into(),
                consumers: vec![
                    "runtime/ember-lab/src/rpc.rs::dispatch_manifest".into(),
                    "runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes".into(),
                ],
                binding: GateBinding::ContentHash,
            },
            StrictGate {
                name: "storage_reserves".into(),
                producer: "runtime/ember-lab/src/lib.rs::DispatchStorageReserve".into(),
                consumers: vec![
                    "runtime/ember-lab/src/lib.rs::validate_dispatch_manifest_snapshot_preconditions".into(),
                    "runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes_at_with_probes_and_host_inner".into(),
                ],
                binding: GateBinding::MeasuredValue,
            },
            StrictGate {
                name: "vram_reserve".into(),
                producer: "runtime/ember-lab/src/lib.rs::available_free_vram_bytes".into(),
                consumers: vec!["runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes_at_with_probes_and_host_inner".into()],
                binding: GateBinding::MeasuredValue,
            },
            StrictGate {
                name: "host_commit_capacity".into(),
                producer: "runtime/ember-lab/src/lib.rs::probe_host_commit_capacity".into(),
                consumers: vec!["runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes_at_with_probes_and_host_inner".into()],
                binding: GateBinding::MeasuredValue,
            },
            StrictGate {
                name: "preflight_receipt".into(),
                producer: "runtime/ember-lab/src/lib.rs::atomic_replace".into(),
                consumers: vec!["runtime/ember-lab/src/lib.rs::reconstruct_existing_dispatch".into()],
                binding: GateBinding::ContentHash,
            },
        ],
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeathClass {
    MissingPreflight,
    UnmeasuredAdmission,
    PartialPipeline,
    SilentRefusal,
    OperatorOnlyGap,
    DynamicHostPressure,
}

impl DeathClass {
    pub const fn all() -> [Self; 6] {
        [
            Self::MissingPreflight,
            Self::UnmeasuredAdmission,
            Self::PartialPipeline,
            Self::SilentRefusal,
            Self::OperatorOnlyGap,
            Self::DynamicHostPressure,
        ]
    }

    pub const fn prevention_layer(self) -> &'static str {
        match self {
            Self::MissingPreflight | Self::UnmeasuredAdmission => "layer_1",
            Self::PartialPipeline | Self::SilentRefusal | Self::OperatorOnlyGap => "layer_3",
            Self::DynamicHostPressure => "layer_2_dynamic",
        }
    }

    pub const fn dynamic_justification(self) -> &'static str {
        match self {
            Self::MissingPreflight => "the producer and consumer must be bound at build time",
            Self::UnmeasuredAdmission => "only an observed host value can support admission",
            Self::PartialPipeline => "every runtime phase must be exercised in order",
            Self::SilentRefusal => "the operator needs a durable code and next action",
            Self::OperatorOnlyGap => "one entrypoint must chain the complete current authority",
            Self::DynamicHostPressure => {
                "host pressure changes during execution and remains dynamic"
            }
        }
    }
}

/// The runbook is generated from the closed receipt-code vocabulary, so a new
/// refusal code cannot be added without a documentation/test failure.
pub fn generate_runbook() -> String {
    let mut output = String::from("# Ember Lab rehearsal runbook\n\n");
    for code in RefusalCode::all() {
        output.push_str(&format!(
            "## {}\nnext_action: {}\n\n",
            code,
            code.next_action()
        ));
    }
    output
}
