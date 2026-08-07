// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::rehearsal::{self, Phase, PhaseOutcome, RehearsalManifest, RehearsalRunner};
use ember_lab::{
    ember_lab_source_hash, hash_file, rpc::serve_named_pipe, training_verify, Daemon,
    DispatchManifest, DispatchOutcome, MAX_DISPATCH_MANIFEST_BYTES,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

fn usage() -> &'static str {
    "usage:\n  ember-lab serve --db <path> --pipe <\\\\.\\pipe\\name>\n  ember-lab dispatch --pipe <\\\\.\\pipe\\name> --manifest <path>\n  ember-lab produce-minimal-slice --root <path> --job-id <id>\n  ember-lab verify-training --root <path> --receipt <path> [--certificate <path>]\n  ember-lab rehearse --db <path> --dispatch-manifest <path> --manifest <path> --receipt <path>\n  ember-lab episode --capability <name> --db <path> --dispatch-manifest <path> --manifest <path> --receipt <path>\n  ember-lab runbook --output <path>"
}

enum Command {
    Serve {
        db: PathBuf,
        pipe: String,
    },
    Dispatch {
        pipe: String,
        manifest: PathBuf,
    },
    ProduceMinimalSlice {
        root: PathBuf,
        job_id: String,
    },
    VerifyTraining {
        root: PathBuf,
        receipt: PathBuf,
        certificate: Option<PathBuf>,
    },
    Rehearse {
        capability: String,
        db: PathBuf,
        dispatch_manifest: PathBuf,
        manifest: PathBuf,
        receipt: PathBuf,
    },
    Runbook {
        output: PathBuf,
    },
}

struct CurrentAuthorityRunner {
    daemon: Daemon,
    job_id: String,
    dispatch: Option<DispatchOutcome>,
    phase_evidence: Vec<rehearsal::PhaseEvidence>,
}

impl RehearsalRunner for CurrentAuthorityRunner {
    fn run(&mut self, phase: Phase) -> PhaseOutcome {
        if phase == Phase::Admission {
            return if self.dispatch.is_some() {
                PhaseOutcome::Completed
            } else {
                PhaseOutcome::Failed(
                    "current Ember Lab dispatch authority was not established before rehearsal"
                        .into(),
                )
            };
        }
        let Some(dispatch) = self.dispatch.as_ref() else {
            return PhaseOutcome::Failed("current Ember Lab dispatch receipt is absent".into());
        };
        let Some(evidence) = self.phase_evidence.iter().find(|e| e.phase == phase) else {
            return PhaseOutcome::Failed(format!(
                "current Ember Lab phase evidence is absent for {}",
                phase.as_str()
            ));
        };
        let Ok(bytes) = std::fs::read(&evidence.path) else {
            return PhaseOutcome::Failed(format!(
                "current Ember Lab phase evidence is unreadable for {}",
                phase.as_str()
            ));
        };
        if format!("{:x}", Sha256::digest(&bytes)) != evidence.sha256 {
            return PhaseOutcome::Failed(format!(
                "current Ember Lab phase evidence changed for {}",
                phase.as_str()
            ));
        }
        if !phase_evidence_shape_authorized(&bytes, &self.job_id, phase) {
            return PhaseOutcome::Failed(format!(
                "current Ember Lab phase evidence producer is not authorized for {}",
                phase.as_str()
            ));
        }
        let Ok(dispatch_receipt) = std::fs::read(&dispatch.receipt.path) else {
            return PhaseOutcome::Failed("current Ember Lab dispatch receipt is unreadable".into());
        };
        if format!("{:x}", Sha256::digest(&dispatch_receipt)) != dispatch.receipt.sha256 {
            return PhaseOutcome::Failed(
                "current Ember Lab dispatch receipt hash changed after admission".into(),
            );
        }
        let Ok(value) = serde_json::from_slice::<Value>(&dispatch_receipt) else {
            return PhaseOutcome::Failed("current Ember Lab dispatch receipt is malformed".into());
        };
        if value.get("schema_version")
            != Some(&Value::String("ember-lab-dispatch-preflight-v1".into()))
            || value.get("result") != Some(&Value::String("PREFLIGHT_PASSED".into()))
        {
            return PhaseOutcome::Failed("current Ember Lab dispatch receipt is not green".into());
        }
        if !self
            .daemon
            .phase_event_authorized(&self.job_id, phase.as_str(), &evidence.sha256)
            .unwrap_or(false)
        {
            return PhaseOutcome::Failed(format!(
                "current Ember Lab phase authority event is absent for {}",
                phase.as_str()
            ));
        }
        PhaseOutcome::Completed
    }
}

fn parse_args() -> Result<Command, String> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or_else(|| usage().to_string())?;

    if command == "verify-training" {
        let mut root = None;
        let mut receipt = None;
        let mut certificate = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--root" => root = Some(PathBuf::from(value)),
                "--receipt" => receipt = Some(PathBuf::from(value)),
                "--certificate" => certificate = Some(PathBuf::from(value)),
                _ => return Err(format!("unknown argument {flag}\n{}", usage())),
            }
        }
        return Ok(Command::VerifyTraining {
            root: root.ok_or_else(|| format!("missing --root\n{}", usage()))?,
            receipt: receipt.ok_or_else(|| format!("missing --receipt\n{}", usage()))?,
            certificate,
        });
    }

    if command == "produce-minimal-slice" {
        let mut root = None;
        let mut job_id = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--root" => root = Some(PathBuf::from(value)),
                "--job-id" => job_id = Some(value),
                _ => return Err(format!("unknown argument {flag}\n{}", usage())),
            }
        }
        return Ok(Command::ProduceMinimalSlice {
            root: root
                .or_else(|| std::env::var_os("EMBER_LAB_PHASE_OUTPUT_ROOT").map(PathBuf::from))
                .ok_or_else(|| {
                    format!("missing --root or producer output environment\n{}", usage())
                })?,
            job_id: job_id.ok_or_else(|| format!("missing --job-id\n{}", usage()))?,
        });
    }

    if command == "runbook" {
        let flag = args
            .next()
            .ok_or_else(|| format!("missing --output\n{}", usage()))?;
        let output = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        if flag != "--output" || args.next().is_some() {
            return Err(format!("arguments do not match runbook\n{}", usage()));
        }
        return Ok(Command::Runbook {
            output: PathBuf::from(output),
        });
    }

    if command == "rehearse" || command == "episode" {
        let mut capability = "rehearsal".to_string();
        let mut db = None;
        let mut dispatch_manifest = None;
        let mut manifest = None;
        let mut receipt = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--capability" => capability = value,
                "--db" => db = Some(PathBuf::from(value)),
                "--dispatch-manifest" => dispatch_manifest = Some(PathBuf::from(value)),
                "--manifest" => manifest = Some(PathBuf::from(value)),
                "--receipt" => receipt = Some(PathBuf::from(value)),
                _ => return Err(format!("unknown argument {flag}\n{}", usage())),
            }
        }
        return Ok(Command::Rehearse {
            capability,
            db: db.ok_or_else(|| format!("missing --db dispatch authority\n{}", usage()))?,
            dispatch_manifest: dispatch_manifest.ok_or_else(|| {
                format!(
                    "missing --dispatch-manifest dispatch authority\n{}",
                    usage()
                )
            })?,
            manifest: manifest.ok_or_else(|| format!("missing --manifest\n{}", usage()))?,
            receipt: receipt.ok_or_else(|| format!("missing --receipt\n{}", usage()))?,
        });
    }

    let mut db = None;
    let mut pipe = None;
    let mut manifest = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        match flag.as_str() {
            "--db" => db = Some(PathBuf::from(value)),
            "--pipe" => pipe = Some(value),
            "--manifest" => manifest = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument {flag}\n{}", usage())),
        }
    }
    let pipe = pipe.ok_or_else(|| format!("missing --pipe\n{}", usage()))?;
    match command.as_str() {
        "serve" if manifest.is_none() => Ok(Command::Serve {
            db: db.ok_or_else(|| format!("missing --db\n{}", usage()))?,
            pipe,
        }),
        "dispatch" if db.is_none() => Ok(Command::Dispatch {
            pipe,
            manifest: manifest.ok_or_else(|| format!("missing --manifest\n{}", usage()))?,
        }),
        "serve" | "dispatch" => Err(format!("arguments do not match {command}\n{}", usage())),
        _ => Err(format!("unknown command {command}\n{}", usage())),
    }
}

/// `verify-training`: synchronous, GitHub-free check of exactly the training dependency
/// closure (#1400). Never touches the daemon/named-pipe surface -- this is a stateless,
/// seconds-scale check with no reason to require a resident `ember-lab serve` process.
fn run_verify_training(
    root: &Path,
    receipt_path: &Path,
    certificate: Option<&Path>,
) -> Result<bool, Box<dyn std::error::Error>> {
    let ember_lab_binary_sha256 = hash_file(&std::env::current_exe()?)?;
    let ember_lab_source_sha256 = ember_lab_source_hash();
    let outcome = training_verify::run(
        root,
        certificate,
        &ember_lab_binary_sha256,
        &ember_lab_source_sha256,
    )?;
    training_verify::write_receipt(receipt_path, &outcome.receipt)?;
    Ok(outcome.ok)
}

fn run_rehearsal(
    capability: &str,
    db_path: &Path,
    dispatch_manifest_path: &Path,
    manifest_path: &Path,
    receipt_path: &Path,
) -> Result<bool, Box<dyn std::error::Error>> {
    let manifest_bytes = std::fs::read(manifest_path)?;
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let manifest: RehearsalManifest = serde_json::from_slice(&manifest_bytes)?;
    let dispatch_bytes = std::fs::read(dispatch_manifest_path)?;
    let dispatch: DispatchManifest = serde_json::from_slice(&dispatch_bytes)?;
    if dispatch.source_commit != manifest.source_commit || dispatch.job_id != manifest.dispatch_id {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "dispatch authority source commit does not match rehearsal manifest",
        )
        .into());
    }
    if dispatch
        .env
        .get("EMBER_LAB_MINIMAL_SLICE")
        .map(String::as_str)
        != Some("1")
        || dispatch.env.get("EMBER_LAB_MINIMAL_SLICE_JOB_ID") != Some(&manifest.dispatch_id)
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "dispatch authority does not bind the current minimal-slice producer/job",
        )
        .into());
    }
    if manifest.contract_sha256 != rehearsal::current_contract_sha256() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "rehearsal manifest contract is not the current Ember Lab contract",
        )
        .into());
    }
    if manifest.measurements.source != rehearsal::MeasurementSource::HostProbe {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "operator rehearsal requires a current HostProbe measurement",
        )
        .into());
    }
    let daemon = Daemon::open(db_path)?;
    let dispatch_outcome = daemon.dispatch_manifest(dispatch_manifest_path)?;
    // The dispatched child emits the current minimal-slice operation outputs.
    // Ember Lab only reopens, validates, hashes, and fences those bytes below;
    // the rehearsal adapter never creates phase evidence.
    daemon.execute_minimal_episode(
        &manifest.dispatch_id,
        manifest.measurements.whole_run_peak_bytes,
        dispatch.expires_at_ms,
    )?;
    let (authoritative_peak_path, authoritative_peak_sha256, authoritative_peak_bytes) =
        daemon.authoritative_whole_run_peak(&manifest.dispatch_id)?;
    let phase_evidence = match daemon.load_authorized_phase_evidence(&manifest.dispatch_id) {
        Ok(evidence) => evidence,
        Err(error) => {
            let _ = daemon.stop_job(&manifest.dispatch_id);
            return Err(error.into());
        }
    };
    let mut execution_manifest = manifest.clone();
    execution_manifest.phase_evidence = phase_evidence.clone();
    execution_manifest.measurements.evidence_path = authoritative_peak_path;
    execution_manifest.measurements.evidence_sha256 = authoritative_peak_sha256;
    execution_manifest.measurements.whole_run_peak_bytes = authoritative_peak_bytes;
    let mut runner = CurrentAuthorityRunner {
        daemon,
        job_id: manifest.dispatch_id.clone(),
        dispatch: Some(dispatch_outcome),
        phase_evidence,
    };
    let result = rehearsal::episode(capability, &execution_manifest, &mut runner);
    let _dispatch_outcome = runner.dispatch.take().ok_or_else(|| {
        std::io::Error::other(
            "current Ember Lab dispatch authority refused before producing an operational receipt",
        )
    })?;
    runner.daemon.stop_job(&manifest.dispatch_id)?;
    let observation = json!({
        "manifest_sha256": manifest_sha256,
        "result": result.receipt,
    });
    let operational = runner
        .daemon
        .export_content_addressed_receipt_with_observation(
            &manifest.dispatch_id,
            receipt_path.parent().unwrap_or_else(|| Path::new(".")),
            &observation,
        )?;
    if receipt_path != operational.path {
        if receipt_path.exists() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "requested rehearsal receipt path already exists",
            )
            .into());
        }
        std::fs::copy(&operational.path, receipt_path)?;
    }
    println!(
        "rehearse: {:?} -- receipt {} written to {}",
        result.status,
        operational.sha256,
        receipt_path.display()
    );
    Ok(result.status == rehearsal::RehearsalStatus::Completed)
}

fn phase_evidence_shape_authorized(bytes: &[u8], job_id: &str, phase: Phase) -> bool {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        return false;
    };
    let Some(operation) = value.get("operation") else {
        return false;
    };
    let Some(operation_sha256) = value.get("operation_sha256").and_then(Value::as_str) else {
        return false;
    };
    let Ok(operation_bytes) = serde_json::to_vec(operation) else {
        return false;
    };
    format!("{:x}", Sha256::digest(operation_bytes)) == operation_sha256
        && value.get("schema") == Some(&Value::String("ember-lab-phase-producer-v1".into()))
        && value.get("producer") == Some(&Value::String("ember-lab-minimal-slice-producer".into()))
        && value.get("result") == Some(&Value::String("COMPLETED".into()))
        && value.get("job_id") == Some(&Value::String(job_id.into()))
        && value.get("phase") == Some(&Value::String(phase.as_str().into()))
}

fn dispatch(pipe: &str, manifest: &Path) -> Result<Value, Box<dyn std::error::Error>> {
    let manifest_bytes = std::fs::read(manifest)?;
    if manifest_bytes.len() > MAX_DISPATCH_MANIFEST_BYTES {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "dispatch manifest exceeds the UTF-8 transport ceiling",
        )
        .into());
    }
    let manifest_utf8 = String::from_utf8(manifest_bytes.clone())?;
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let request = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "dispatch_manifest",
        "params": {"manifest_utf8": manifest_utf8, "manifest_sha256": manifest_sha256},
    });
    let encoded = serde_json::to_string(&request)?;
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut stream = loop {
        match OpenOptions::new().read(true).write(true).open(pipe) {
            Ok(stream) => break stream,
            Err(error) if Instant::now() < deadline => {
                let _ = error;
                std::thread::sleep(Duration::from_millis(20));
            }
            Err(error) => return Err(error.into()),
        }
    };
    writeln!(stream, "{encoded}")?;
    stream.flush()?;
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line)?;
    let response: Value = serde_json::from_str(&line)?;
    if let Some(error) = response.get("error") {
        return Err(std::io::Error::other(format!("ember-lab dispatch failed: {error}")).into());
    }
    response
        .get("result")
        .cloned()
        .ok_or_else(|| std::io::Error::other("ember-lab dispatch response lacks result").into())
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    match parse_args().map_err(std::io::Error::other)? {
        Command::Serve { db, pipe } => {
            let daemon = Arc::new(Daemon::open(&db)?);
            daemon.reconcile()?;
            serve_named_pipe(daemon, &pipe)?;
        }
        Command::Dispatch { pipe, manifest } => {
            println!("{}", serde_json::to_string(&dispatch(&pipe, &manifest)?)?);
        }
        Command::ProduceMinimalSlice { root, job_id } => {
            rehearsal::produce_minimal_slice(&root, &job_id)?;
        }
        Command::VerifyTraining {
            root,
            receipt,
            certificate,
        } => {
            let ok = run_verify_training(&root, &receipt, certificate.as_deref())?;
            println!(
                "verify-training: {} -- receipt written to {}",
                if ok { "PASS" } else { "FAIL" },
                receipt.display()
            );
            if !ok {
                // Mirrors scripts/training_closure.py's own CLI convention: a completed-but-
                // red run is exit 1, distinct from the process::exit(1) `main()` already
                // takes on an infra-level Err from run_verify_training above (a malformed
                // manifest, unreadable file, etc.) -- both currently read as exit 1 to the
                // shell, so a caller that needs to tell them apart reads the receipt's `ok`
                // field, not the exit code alone.
                std::process::exit(1);
            }
        }
        Command::Rehearse {
            capability,
            db,
            dispatch_manifest,
            manifest,
            receipt,
        } => {
            if !run_rehearsal(&capability, &db, &dispatch_manifest, &manifest, &receipt)? {
                std::process::exit(1);
            }
        }
        Command::Runbook { output } => {
            std::fs::write(&output, rehearsal::generate_runbook())?;
            println!("runbook written to {}", output.display());
        }
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("ember-lab: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arbitrary_phase_bytes_without_current_producer_refuse() {
        assert!(!phase_evidence_shape_authorized(
            br#"{"phase":"train"}"#,
            "dispatch-1",
            Phase::Train
        ));
        assert!(!phase_evidence_shape_authorized(
            br#"{"schema":"ember-lab-phase-evidence-v1","producer":"foreign","result":"COMPLETED","job_id":"dispatch-1","phase":"train"}"#,
            "dispatch-1",
            Phase::Train
        ));
        assert!(!phase_evidence_shape_authorized(
            br#"{"schema":"ember-lab-phase-evidence-v1","producer":"ember-lab-current-dispatch","result":"COMPLETED","job_id":"dispatch-1","phase":"train"}"#,
            "dispatch-1",
            Phase::Train
        ));
        let operation = json!({
            "kind": "train_steps_completed",
            "train_steps": 3,
            "update_count": 3,
        });
        let operation_sha256 = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&operation).unwrap())
        );
        let current = json!({
            "schema": "ember-lab-phase-producer-v1",
            "producer": "ember-lab-minimal-slice-producer",
            "result": "COMPLETED",
            "job_id": "dispatch-1",
            "phase": "train",
            "operation_sha256": operation_sha256,
            "operation": operation,
        });
        assert!(phase_evidence_shape_authorized(
            &serde_json::to_vec(&current).unwrap(),
            "dispatch-1",
            Phase::Train
        ));
    }
}
