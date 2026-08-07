// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::rehearsal::{
    episode, generate_runbook, production_strict_gate_census, validate_strict_gate_census,
    AdmissionBounds, DeathClass, GateBinding, Measurement, MeasurementSource, Phase, PhaseEvidence,
    PhaseOutcome, RefusalCode, RehearsalManifest, RehearsalRunner, RehearsalStatus, StrictGate,
    StrictGateCensus,
};
use sha2::{Digest, Sha256};
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

struct Runner {
    fail: Option<Phase>,
}

impl RehearsalRunner for Runner {
    fn run(&mut self, phase: Phase) -> PhaseOutcome {
        if self.fail == Some(phase) {
            PhaseOutcome::Failed("fixture refusal".into())
        } else {
            PhaseOutcome::Completed
        }
    }
}

fn manifest() -> RehearsalManifest {
    let root = std::env::temp_dir().join(format!(
        "ember-lab-rehearsal-evidence-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir_all(&root).unwrap();
    let measurement_path = root.join("measurement.json");
    let measurement_bytes = br#"{"whole_run_peak_bytes":512}"#;
    fs::write(&measurement_path, measurement_bytes).unwrap();
    let phase_evidence = Phase::ordered()
        .iter()
        .map(|phase| {
            let path = root.join(format!("{}.json", phase.as_str()));
            let bytes = format!("{{\"phase\":\"{}\"}}", phase.as_str()).into_bytes();
            fs::write(&path, &bytes).unwrap();
            PhaseEvidence {
                phase: *phase,
                path,
                sha256: format!("{:x}", Sha256::digest(bytes)),
            }
        })
        .collect::<Vec<_>>();
    RehearsalManifest {
        schema_version: "ember-lab-rehearsal-v1".into(),
        dispatch_id: "fixture-dispatch".into(),
        source_commit: "a".repeat(40),
        contract_sha256: ember_lab::rehearsal::current_contract_sha256(),
        bounds: AdmissionBounds {
            minimum_memory_bytes: 100,
            minimum_storage_free_bytes: 200,
            maximum_duration_ms: 300,
        },
        measurements: Measurement {
            source: MeasurementSource::FakeRunner,
            observed_at_ms: 1,
            available_memory_bytes: 1_000,
            storage_free_bytes: 2_000,
            measured_duration_ms: 50,
            whole_run_peak_bytes: 512,
            evidence_path: measurement_path,
            evidence_sha256: format!("{:x}", Sha256::digest(measurement_bytes)),
        },
        phase_evidence,
    }
}

#[test]
fn measured_values_admit_and_rehearse_every_minimal_slice_phase() {
    let result = episode(
        "fixture-capability",
        &manifest(),
        &mut Runner { fail: None },
    );
    assert_eq!(result.status, RehearsalStatus::Completed);
    assert_eq!(result.receipt.phases, Phase::ordered());
    assert!(result.receipt.next_action.is_none());
}

#[test]
fn phase_refusal_is_self_diagnosing_and_stops_before_later_phases() {
    let result = episode(
        "fixture-capability",
        &manifest(),
        &mut Runner {
            fail: Some(Phase::Checkpoint),
        },
    );
    assert_eq!(result.status, RehearsalStatus::Refused);
    assert_eq!(result.receipt.code, Some(RefusalCode::PhaseFailed));
    assert_eq!(result.receipt.phase, Some(Phase::Checkpoint));
    assert_eq!(
        result.receipt.next_action.as_deref(),
        Some(RefusalCode::PhaseFailed.next_action())
    );
    assert_eq!(result.receipt.phases, Phase::ordered()[..4].to_vec());
}

#[test]
fn missing_or_estimated_measurement_refuses_before_runner() {
    let mut invalid = manifest();
    invalid.measurements.evidence_sha256.clear();
    let result = episode("fixture-capability", &invalid, &mut Runner { fail: None });
    assert_eq!(result.status, RehearsalStatus::Refused);
    assert_eq!(result.receipt.code, Some(RefusalCode::MissingMeasurement));
    assert_eq!(
        result.receipt.next_action.as_deref(),
        Some(RefusalCode::MissingMeasurement.next_action())
    );
    assert!(result.receipt.phases.is_empty());
}

#[test]
fn phase_evidence_mutation_refuses_before_any_phase() {
    let mut invalid = manifest();
    fs::write(&invalid.phase_evidence[0].path, b"mutated").unwrap();
    let result = episode("fixture-capability", &invalid, &mut Runner { fail: None });
    assert_eq!(result.status, RehearsalStatus::Refused);
    assert_eq!(result.receipt.code, Some(RefusalCode::MissingMeasurement));
    assert!(result.receipt.phases.is_empty());
}

#[test]
fn stale_contract_binding_refuses_before_any_phase() {
    let mut invalid = manifest();
    invalid.contract_sha256 = "c".repeat(64);
    let result = episode("fixture-capability", &invalid, &mut Runner { fail: None });
    assert_eq!(result.status, RehearsalStatus::Refused);
    assert_eq!(result.receipt.code, Some(RefusalCode::StrictGateUnbound));
    assert!(result.receipt.phases.is_empty());
}

#[test]
fn every_measured_admission_bound_refuses_before_any_phase() {
    let cases = [
        ("memory", RefusalCode::MemoryFloor),
        ("storage", RefusalCode::StorageFloor),
        ("duration", RefusalCode::DurationBound),
    ];
    for (kind, expected) in cases {
        let mut invalid = manifest();
        match kind {
            "memory" => invalid.measurements.available_memory_bytes = 0,
            "storage" => invalid.measurements.storage_free_bytes = 0,
            "duration" => invalid.measurements.measured_duration_ms = 301,
            _ => unreachable!(),
        }
        let result = episode("fixture-capability", &invalid, &mut Runner { fail: None });
        assert_eq!(result.receipt.code, Some(expected));
        assert!(result.receipt.phases.is_empty());
        assert!(result.receipt.next_action.is_some());
    }
}

#[test]
fn strict_gate_census_is_closed_and_binds_real_producers_to_consumers() {
    validate_strict_gate_census(&production_strict_gate_census()).unwrap();
    let gates = vec![
        StrictGate {
            name: "manifest_bytes".into(),
            producer: "runtime::rehearsal::manifest_bytes".into(),
            consumers: vec!["runtime::rehearsal::admit".into()],
            binding: GateBinding::ContentHash,
        },
        StrictGate {
            name: "measurement_snapshot".into(),
            producer: "runtime::rehearsal::measure".into(),
            consumers: vec!["runtime::rehearsal::admit".into()],
            binding: GateBinding::MeasuredValue,
        },
    ];
    let census = StrictGateCensus {
        expected: vec!["manifest_bytes".into(), "measurement_snapshot".into()],
        gates,
    };
    validate_strict_gate_census(&census).unwrap();

    let mut missing = census.clone();
    missing.gates.pop();
    assert!(validate_strict_gate_census(&missing).is_err());
}

#[test]
fn generated_runbook_is_exhaustive_over_closed_refusal_codes() {
    let runbook = generate_runbook();
    for code in RefusalCode::all() {
        assert!(runbook.contains(code.as_str()), "missing {code:?}");
        assert_eq!(runbook.matches(code.next_action()).count(), 1);
    }
}

#[test]
fn six_historical_deaths_have_explicit_prevention_layers() {
    let deaths = DeathClass::all();
    assert_eq!(deaths.len(), 6);
    assert!(deaths
        .iter()
        .all(|death| !death.prevention_layer().is_empty()));
    assert!(deaths
        .iter()
        .all(|death| death.dynamic_justification().len() > 20));
}
