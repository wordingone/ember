//! Ember Lab's rehearsal-first dispatch contract.
//!
//! This is the current implementation of the historical `emberd rehearse`
//! wording.  It deliberately reuses the Ember Lab dispatch authority instead
//! of creating another launcher, lease, or receipt authority.  The runner
//! trait is only a deterministic CPU/fake-runner seam for tests and dry-run
//! admission; a capability claim is never made by this module.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::path::Path;

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
            Self::MissingMeasurement => "measure_then_retry",
            Self::MemoryFloor => "increase_memory_headroom_or_reduce_scope",
            Self::StorageFloor => "free_storage_or_reduce_scope",
            Self::DurationBound => "measure_duration_then_reduce_scope",
            Self::PhaseFailed => "repair_or_rehearse",
            Self::StrictGateUnbound => "bind_gate_producer_and_consumer",
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
    pub evidence_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RehearsalManifest {
    pub schema_version: String,
    pub dispatch_id: String,
    pub bounds: AdmissionBounds,
    pub measurements: Measurement,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PhaseOutcome {
    Completed,
    Failed(String),
}

pub trait RehearsalRunner {
    fn run(&self, phase: Phase) -> PhaseOutcome;
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
            schema_version: "ember-lab-rehearsal-receipt-v1".into(),
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
        || manifest.measurements.observed_at_ms == 0
        || !valid_hash(&manifest.measurements.evidence_sha256)
    {
        return Err((RefusalCode::MissingMeasurement, None, None));
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
    runner: &R,
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
            schema_version: "ember-lab-rehearsal-receipt-v1".into(),
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
            manifest_sha256: None,
        },
    }
}

/// Persist a receipt only after the full result has been assembled.  The
/// caller owns the path under the declared custody root; no capability claim
/// is inferred from writing this file.
pub fn write_receipt(path: &Path, receipt: &RehearsalReceipt) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(receipt).map_err(|error| error.to_string())?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(path, bytes).map_err(|error| error.to_string())
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
