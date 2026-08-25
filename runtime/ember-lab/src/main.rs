// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::data_catalog::ArtifactLocationInput;
use ember_lab::rehearsal::{self, Phase, PhaseOutcome, RehearsalManifest, RehearsalRunner};
use ember_lab::{
    ember_lab_source_hash, hash_file, read_custody_verify, read_data_catalog_status,
    rpc::serve_named_pipe, training_verify, Daemon, DispatchManifest, DispatchOutcome,
    MAX_DISPATCH_MANIFEST_BYTES,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command as ProcessCommand, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const DISPATCH_TOKEN_ENV: &str = "EMBER_LAB_DISPATCH_TOKEN";
const DISPATCH_JOB_ID_ENV: &str = "EMBER_LAB_DISPATCH_JOB_ID";
const DISPATCH_DAEMON_PID_ENV: &str = "EMBER_LAB_DISPATCH_DAEMON_PID";
const DISPATCH_PIPE_ENV: &str = "EMBER_LAB_PIPE";
const DISPATCH_MAXIMUM_JOB_MEMORY_ENV: &str = "EMBER_LAB_DISPATCH_MAXIMUM_JOB_MEMORY_BYTES";
const GIB: u64 = 1024 * 1024 * 1024;
const CERTIFIED_LAUNCH_OVERSHOOT_MARGIN_BYTES: u64 = 2 * GIB;
const HOST_COMMIT_SURVIVAL_RESERVE_BYTES: u64 = 10 * GIB;

struct PreparedCertifiedLaunch {
    manifest_path: PathBuf,
    job_id: String,
    receipt_path: PathBuf,
    run_custody_root: PathBuf,
}

struct CertifiedLaunchRequest {
    root: PathBuf,
    certificate: PathBuf,
    declaration_ledger: PathBuf,
    run_spec: PathBuf,
    custody_receipt_sha256: String,
    pipe: String,
    receipt: PathBuf,
    python_executable: PathBuf,
    now_ms: i64,
}

struct CertifiedLaunchCliArgs {
    root: PathBuf,
    certificate: PathBuf,
    declaration_ledger: PathBuf,
    run_spec: PathBuf,
    custody_receipt_sha256: String,
    db: Option<PathBuf>,
    pipe: Option<String>,
    receipt: PathBuf,
}

struct CertifiedLaunchDaemonDefaults {
    db: PathBuf,
    pipe: String,
}

struct LaunchDaemon {
    child: Option<Child>,
    mode: &'static str,
    pid: u32,
}

fn certified_launch_run_custody_root(
    run_spec_path: &Path,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let run_spec: Value = serde_json::from_slice(&std::fs::read(run_spec_path)?)?;
    let object = run_spec.as_object().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch run spec must be an object",
        )
    })?;
    let run_id = required_string(object, "run_id")?;
    let requested_scope = required_object(&run_spec, "requested_scope")?;
    let custody_root = PathBuf::from(required_string(requested_scope, "custody_root")?);
    Ok(std::fs::canonicalize(custody_root.join(run_id))?)
}

fn certified_launch_daemon_defaults(
    run_custody_root: &Path,
    db: Option<PathBuf>,
    pipe: Option<String>,
) -> Result<CertifiedLaunchDaemonDefaults, Box<dyn std::error::Error>> {
    let canonical_root = std::fs::canonicalize(run_custody_root)?;
    let identity = format!(
        "{:x}",
        Sha256::digest(canonical_root.to_string_lossy().as_bytes())
    );
    let db = db.unwrap_or_else(|| canonical_root.join("ember-lab.sqlite3"));
    if !db.is_absolute() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch daemon database path must be absolute",
        )
        .into());
    }
    let pipe = pipe.unwrap_or_else(|| format!(r"\\.\pipe\ember-lab-certified-{}", &identity[..16]));
    if !pipe.starts_with(r"\\.\pipe\") || pipe.len() <= r"\\.\pipe\".len() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch daemon pipe must be a non-empty Windows named-pipe path",
        )
        .into());
    }
    Ok(CertifiedLaunchDaemonDefaults { db, pipe })
}

fn resolve_certified_launch_request(
    cli: CertifiedLaunchCliArgs,
    python_executable: PathBuf,
    now_ms: i64,
) -> Result<(CertifiedLaunchRequest, CertifiedLaunchDaemonDefaults), Box<dyn std::error::Error>> {
    let run_custody_root = certified_launch_run_custody_root(&cli.run_spec)?;
    let daemon = certified_launch_daemon_defaults(&run_custody_root, cli.db, cli.pipe)?;
    let request = CertifiedLaunchRequest {
        root: cli.root,
        certificate: cli.certificate,
        declaration_ledger: cli.declaration_ledger,
        run_spec: cli.run_spec,
        custody_receipt_sha256: cli.custody_receipt_sha256,
        pipe: daemon.pipe.clone(),
        receipt: cli.receipt,
        python_executable,
        now_ms,
    };
    Ok((request, daemon))
}

#[derive(Debug)]
struct CertifiedLaunchCompletion {
    exit_code: i32,
    stderr: String,
}

#[cfg(test)]
fn launch_certified_with<F, S>(
    request: &CertifiedLaunchRequest,
    rpc: F,
    wait: S,
) -> Result<CertifiedLaunchCompletion, Box<dyn std::error::Error>>
where
    F: FnMut(&Value) -> Result<Value, Box<dyn std::error::Error>>,
    S: FnMut(),
{
    let prepared = prepare_certified_launch(request)?;
    launch_prepared_certified_with(&prepared, "existing", 0, rpc, wait)
}

fn launch_prepared_certified_with<F, S>(
    prepared: &PreparedCertifiedLaunch,
    daemon_mode: &str,
    daemon_pid: u32,
    mut rpc: F,
    wait: S,
) -> Result<CertifiedLaunchCompletion, Box<dyn std::error::Error>>
where
    F: FnMut(&Value) -> Result<Value, Box<dyn std::error::Error>>,
    S: FnMut(),
{
    let manifest_bytes = std::fs::read(&prepared.manifest_path)?;
    let manifest_utf8 = String::from_utf8(manifest_bytes.clone())?;
    let manifest_sha256 = format!("{:x}", Sha256::digest(&manifest_bytes));
    let dispatched = rpc(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "dispatch_manifest",
        "params": {
            "manifest_utf8": manifest_utf8,
            "manifest_sha256": manifest_sha256
        }
    }))?;
    if dispatched.get("pid").and_then(Value::as_u64).is_none()
        || dispatched
            .get("preflight_receipt_sha256")
            .and_then(Value::as_str)
            .is_none()
    {
        return Err(std::io::Error::other(
            "certified launch dispatch response lacks owned child evidence",
        )
        .into());
    }
    let recorded = rpc(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "record_launch_context",
        "params": {
            "job_id": prepared.job_id,
            "daemon_mode": daemon_mode,
            "daemon_pid": daemon_pid
        }
    }))?;
    if recorded.get("recorded") != Some(&Value::Bool(true)) {
        return Err(std::io::Error::other(
            "certified launch daemon ownership context was not recorded",
        )
        .into());
    }
    complete_certified_launch(
        &prepared.job_id,
        &prepared.receipt_path,
        |request| rpc(request),
        wait,
    )
}

fn complete_certified_launch<F, S>(
    job_id: &str,
    receipt_path: &Path,
    mut rpc: F,
    mut wait: S,
) -> Result<CertifiedLaunchCompletion, Box<dyn std::error::Error>>
where
    F: FnMut(&Value) -> Result<Value, Box<dyn std::error::Error>>,
    S: FnMut(),
{
    loop {
        let state = rpc(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "job_state",
            "params": {"job_id": job_id}
        }))?;
        match state.get("state").and_then(Value::as_str) {
            Some("exited" | "failed" | "stopped") => break,
            Some("starting" | "running" | "stopping") => wait(),
            Some(other) => {
                return Err(std::io::Error::other(format!(
                    "certified launch job returned unknown state {other}"
                ))
                .into())
            }
            None => {
                return Err(std::io::Error::other(
                    "certified launch job disappeared before terminal evidence",
                )
                .into())
            }
        }
    }
    let result = rpc(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "job_result",
        "params": {"job_id": job_id}
    }))?;
    let exit_code = result
        .get("exit_code")
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok())
        .ok_or_else(|| {
            std::io::Error::other("certified launch terminal result lacks an i32 exit code")
        })?;
    let stderr = result
        .get("stderr")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            std::io::Error::other("certified launch terminal result lacks UTF-8 stderr")
        })?
        .to_string();
    let exported = rpc(&json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "export_receipt",
        "params": {"job_id": job_id, "path": receipt_path}
    }))?;
    if exported.get("exported") != Some(&Value::Bool(true)) {
        return Err(
            std::io::Error::other("certified launch operational receipt was not exported").into(),
        );
    }
    Ok(CertifiedLaunchCompletion { exit_code, stderr })
}

fn required_object<'a>(
    value: &'a Value,
    key: &str,
) -> Result<&'a serde_json::Map<String, Value>, Box<dyn std::error::Error>> {
    value.get(key).and_then(Value::as_object).ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("certified launch {key} must be an object"),
        )
        .into()
    })
}

fn required_string<'a>(
    value: &'a serde_json::Map<String, Value>,
    key: &str,
) -> Result<&'a str, Box<dyn std::error::Error>> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                format!("certified launch {key} must be a non-empty string"),
            )
            .into()
        })
}

fn required_gib(
    value: &serde_json::Map<String, Value>,
    key: &str,
) -> Result<u64, Box<dyn std::error::Error>> {
    let gib = value
        .get(key)
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite() && *value > 0.0)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                format!("certified launch {key} must be a positive finite number"),
            )
        })?;
    let bytes = gib * GIB as f64;
    if bytes > u64::MAX as f64 || bytes.fract() != 0.0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("certified launch {key} is not an exact byte quantity"),
        )
        .into());
    }
    Ok(bytes as u64)
}

fn required_u64(
    value: &serde_json::Map<String, Value>,
    key: &str,
) -> Result<u64, Box<dyn std::error::Error>> {
    value
        .get(key)
        .and_then(Value::as_u64)
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                format!("certified launch {key} must be a positive integer"),
            )
            .into()
        })
}

fn prepare_certified_launch(
    request: &CertifiedLaunchRequest,
) -> Result<PreparedCertifiedLaunch, Box<dyn std::error::Error>> {
    let root = &request.root;
    let certificate_path = &request.certificate;
    let declaration_ledger_path = &request.declaration_ledger;
    let run_spec_path = &request.run_spec;
    let custody_receipt_sha256 = &request.custody_receipt_sha256;
    let pipe = &request.pipe;
    let receipt_path = &request.receipt;
    let python_executable = &request.python_executable;
    let now_ms = request.now_ms;
    let certificate: Value = serde_json::from_slice(&std::fs::read(certificate_path)?)?;
    let run_spec: Value = serde_json::from_slice(&std::fs::read(run_spec_path)?)?;
    let certificate_object = certificate.as_object().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch certificate must be an object",
        )
    })?;
    let run_spec_object = run_spec.as_object().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch run spec must be an object",
        )
    })?;
    if required_string(run_spec_object, "schema_version")? != "ember-certified-train-run-v1" {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch run spec schema is not ember-certified-train-run-v1",
        )
        .into());
    }
    let source_commit = required_string(certificate_object, "public_master_sha")?;
    if source_commit.len() != 40 || !source_commit.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch public_master_sha is invalid",
        )
        .into());
    }
    let execution_scope = required_object(&certificate, "execution_scope")?;
    let requested_scope = required_object(&run_spec, "requested_scope")?;
    if required_string(requested_scope, "mode")? != "governed-vertical" {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch requested mode is not governed-vertical",
        )
        .into());
    }
    let run_id = required_string(run_spec_object, "run_id")?;
    if run_id
        .bytes()
        .any(|byte| !(byte.is_ascii_alphanumeric() || b"-_.".contains(&byte)))
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch run_id is not path-safe",
        )
        .into());
    }
    let requested_custody_root = PathBuf::from(required_string(requested_scope, "custody_root")?);
    if !requested_custody_root.is_absolute() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch custody root must be absolute",
        )
        .into());
    }
    let run_custody_root = requested_custody_root.join(run_id);
    let canonical_run_custody_root = std::fs::canonicalize(&run_custody_root)?;
    let receipt_parent = std::fs::canonicalize(receipt_path.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch receipt lacks a parent",
        )
    })?)?;
    if !receipt_path.is_absolute()
        || !receipt_parent.starts_with(&canonical_run_custody_root)
        || receipt_path.exists()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch receipt must be a new absolute path inside the run custody root",
        )
        .into());
    }
    let validator = root.join("tools/ember-restart-3b/certified_train_launch.py");
    let readme = root.join("README.md");
    let custody_receipt = certificate_path
        .parent()
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch certificate lacks a packet directory",
            )
        })?
        .join("launch-authority-custody.json");
    let required_files: [(&str, &Path); 7] = [
        ("python executable", python_executable.as_path()),
        ("certified validator", validator.as_path()),
        ("repository root binding", readme.as_path()),
        ("certificate", certificate_path.as_path()),
        ("declaration ledger", declaration_ledger_path.as_path()),
        ("run spec", run_spec_path.as_path()),
        ("custody receipt", custody_receipt.as_path()),
    ];
    for (label, path) in required_files {
        if !path.is_file() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                format!(
                    "certified launch {label} is unavailable at {}",
                    path.display()
                ),
            )
            .into());
        }
    }
    let actual_custody_sha256 = hash_file(&custody_receipt)?;
    if custody_receipt_sha256.len() != 64
        || !custody_receipt_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
        || actual_custody_sha256 != custody_receipt_sha256.as_str()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch custody receipt SHA-256 mismatch",
        )
        .into());
    }

    let gpu_vram_bytes = required_gib(requested_scope, "gpu_vram_gib")?;
    let checkpoint_bytes = required_gib(requested_scope, "transient_checkpoint_gib")?;
    let telemetry_bytes = 4 * GIB;
    let loader_bytes = gpu_vram_bytes.checked_mul(4).ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch host-memory model overflow",
        )
    })?;
    let simulated_peak_commit_bytes = loader_bytes
        .checked_add(checkpoint_bytes)
        .and_then(|value| value.checked_add(telemetry_bytes))
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch host-memory model overflow",
            )
        })?;
    let maximum_job_memory_bytes = simulated_peak_commit_bytes
        .checked_add(CERTIFIED_LAUNCH_OVERSHOOT_MARGIN_BYTES)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch job-memory model overflow",
            )
        })?;
    let is_a1_route = run_spec_object
        .get("a1_family")
        .is_some_and(|value| !value.is_null());
    let a1_storage_floor = execution_scope.get("a1_b_custody_floor_gib");
    let a1_host_reserve = execution_scope.get("a1_host_commit_reserve_gib");
    if is_a1_route && (a1_storage_floor.is_none() || a1_host_reserve.is_none()) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch A1 route lacks its declared resource authority",
        )
        .into());
    }
    if !is_a1_route && (a1_storage_floor.is_some() || a1_host_reserve.is_some()) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch non-A1 route carries A1-only resource authority",
        )
        .into());
    }
    let host_commit_reserve_bytes = if is_a1_route {
        required_gib(execution_scope, "a1_host_commit_reserve_gib")?
            .max(HOST_COMMIT_SURVIVAL_RESERVE_BYTES)
    } else {
        HOST_COMMIT_SURVIVAL_RESERVE_BYTES
    };
    let required_available_maximum_commit_bytes = maximum_job_memory_bytes
        .checked_add(host_commit_reserve_bytes)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch host-commit model overflow",
            )
        })?;
    let write_budget_bytes = required_u64(requested_scope, "write_budget_bytes")?;
    let storage_floor_bytes = if is_a1_route {
        required_gib(execution_scope, "a1_b_custody_floor_gib")?.max(write_budget_bytes)
    } else {
        write_budget_bytes
    };

    let receipt_stem = receipt_path
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch receipt has no UTF-8 stem",
            )
        })?;
    let cache_root = receipt_parent.join(format!(".{receipt_stem}-dispatch-{now_ms}"));
    std::fs::create_dir(&cache_root)?;
    let mut env = BTreeMap::new();
    for key in [
        "TEMP",
        "TMP",
        "TORCH_HOME",
        "TRITON_CACHE_DIR",
        "CUDA_CACHE_PATH",
        "HF_HOME",
        "XDG_CACHE_HOME",
    ] {
        let directory = cache_root.join(key.to_ascii_lowercase());
        std::fs::create_dir(&directory)?;
        env.insert(key.to_string(), directory.to_string_lossy().into_owned());
    }
    env.insert("EMBER_LAB_PIPE".into(), pipe.into());
    env.insert("PYTHONDONTWRITEBYTECODE".into(), "1".into());
    env.insert("PYTHONFAULTHANDLER".into(), "1".into());
    env.insert("PYTHONUNBUFFERED".into(), "1".into());
    let preflight_receipt = receipt_parent.join(format!("{receipt_stem}.preflight.json"));
    if preflight_receipt.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "certified launch preflight receipt already exists",
        )
        .into());
    }
    let job_id = format!("{run_id}-launch-{now_ms}");
    let bindings = [
        ("config", validator.as_path()),
        ("config", readme.as_path()),
        ("config", certificate_path),
        ("input", declaration_ledger_path),
        ("manifest", run_spec_path),
        ("input", custody_receipt.as_path()),
    ]
    .into_iter()
    .map(
        |(kind, path)| -> Result<Value, Box<dyn std::error::Error>> {
            Ok(json!({"kind": kind, "path": path, "sha256": hash_file(path)?}))
        },
    )
    .collect::<Result<Vec<_>, _>>()?;
    let manifest = json!({
        "schema_version": "ember-lab-dispatch-manifest-v3",
        "job_id": job_id,
        "source_commit": source_commit,
        "not_before_ms": now_ms,
        "expires_at_ms": now_ms + 3_600_000,
        "resource_lease": format!("gpu:{job_id}"),
        "program": {"path": python_executable, "sha256": hash_file(python_executable)?},
        "args": [
            validator.to_string_lossy(),
            "--root", root.to_string_lossy(),
            "--certificate", certificate_path.to_string_lossy(),
            "--declaration-ledger", declaration_ledger_path.to_string_lossy(),
            "--run-spec", run_spec_path.to_string_lossy(),
            "--custody-receipt-sha256", custody_receipt_sha256
        ],
        "workload_profile": {
            "profile_id": "governed_vertical",
            "pinned_host_producers": [
                {"kind": "training_data_loader", "maximum_bytes": loader_bytes},
                {"kind": "checkpoint_writer", "maximum_bytes": checkpoint_bytes},
                {"kind": "telemetry_buffer", "maximum_bytes": telemetry_bytes}
            ],
            "requires_ui_responsiveness": false,
            "cpu_rate_percent": 90
        },
        "cpu_pacing_class": "unpaced",
        "window_contract": "headless_no_windows",
        "env": env,
        "bindings": bindings,
        "custody_root": &canonical_run_custody_root,
        "storage_reserves": [{"root": requested_custody_root, "minimum_free_bytes": storage_floor_bytes}],
        "minimum_free_vram_bytes": gpu_vram_bytes,
        "required_available_maximum_commit_bytes": required_available_maximum_commit_bytes,
        "maximum_job_memory_bytes": maximum_job_memory_bytes,
        "simulated_peak_commit_bytes": simulated_peak_commit_bytes,
        "preflight_receipt": preflight_receipt
    });
    let manifest_path = cache_root.join("dispatch-manifest.json");
    let mut manifest_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&manifest_path)?;
    manifest_file.write_all(&serde_json::to_vec_pretty(&manifest)?)?;
    manifest_file.sync_all()?;
    Ok(PreparedCertifiedLaunch {
        manifest_path,
        job_id,
        receipt_path: receipt_path.to_path_buf(),
        run_custody_root: canonical_run_custody_root,
    })
}

fn usage() -> &'static str {
    "usage:\n  ember-lab serve --db <path> --pipe <\\\\.\\pipe\\name>\n  ember-lab dispatch --pipe <\\\\.\\pipe\\name> --manifest <path>\n  ember-lab launch --root <path> --certificate <path> --declaration-ledger <path> --run-spec <path> --custody-receipt-sha256 <hex> --receipt <path> [--db <path>] [--pipe <\\\\.\\pipe\\name>]\n  ember-lab resource-guard-rearm --pipe <\\\\.\\pipe\\name> --frozen-observation-sha256 <hex> --breach-class <class> --diagnostic-receipt <path> --diagnostic-receipt-sha256 <hex>\n  ember-lab data-catalog-status --db <path>\n  ember-lab register-artifact --db <path> --sha256 <hex> --byte-count <n> --media-type <type> --location <volume>=<locator> [--location <volume>=<locator> ...]\n  ember-lab retire-artifact-location --db <path> --sha256 <hex> --volume <volume> --locator <locator> --reason <text>\n  ember-lab custody-verify --db <path> --hash <sha256> [--hash <sha256> ...] --root <volume>=<path> [--root <volume>=<path> ...] --receipt <path> [--rehash]\n  ember-lab produce-minimal-slice --root <path> --job-id <id>\n  ember-lab verify-training --root <path> --receipt <path> [--certificate <path>]\n  ember-lab rehearse --db <path> --dispatch-manifest <path> --manifest <path> --receipt <path>\n  ember-lab episode --capability <name> --db <path> --dispatch-manifest <path> --manifest <path> --receipt <path>\n  ember-lab runbook --output <path>"
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
    Launch(CertifiedLaunchCliArgs),
    ResourceGuardRearm {
        pipe: String,
        frozen_observation_sha256: String,
        breach_class: String,
        diagnostic_receipt: PathBuf,
        diagnostic_receipt_sha256: String,
    },
    DataCatalogStatus {
        db: PathBuf,
    },
    RegisterArtifact {
        db: PathBuf,
        sha256: String,
        byte_count: i64,
        media_type: String,
        locations: Vec<(String, String)>,
    },
    RetireArtifactLocation {
        db: PathBuf,
        sha256: String,
        volume: String,
        locator: String,
        reason: String,
    },
    CustodyVerify {
        db: PathBuf,
        hashes: Vec<String>,
        roots: Vec<(String, PathBuf)>,
        rehash: bool,
        receipt: PathBuf,
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

fn parse_launch_arguments<I>(mut args: I) -> Result<Command, String>
where
    I: Iterator<Item = String>,
{
    let mut root = None;
    let mut certificate = None;
    let mut declaration_ledger = None;
    let mut run_spec = None;
    let mut custody_receipt_sha256 = None;
    let mut db = None;
    let mut pipe = None;
    let mut receipt = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        match flag.as_str() {
            "--root" => root = Some(PathBuf::from(value)),
            "--certificate" => certificate = Some(PathBuf::from(value)),
            "--declaration-ledger" => declaration_ledger = Some(PathBuf::from(value)),
            "--run-spec" => run_spec = Some(PathBuf::from(value)),
            "--custody-receipt-sha256" => custody_receipt_sha256 = Some(value),
            "--db" => db = Some(PathBuf::from(value)),
            "--pipe" => pipe = Some(value),
            "--receipt" => receipt = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument {flag}\n{}", usage())),
        }
    }
    Ok(Command::Launch(CertifiedLaunchCliArgs {
        root: root.ok_or_else(|| format!("missing --root\n{}", usage()))?,
        certificate: certificate.ok_or_else(|| format!("missing --certificate\n{}", usage()))?,
        declaration_ledger: declaration_ledger
            .ok_or_else(|| format!("missing --declaration-ledger\n{}", usage()))?,
        run_spec: run_spec.ok_or_else(|| format!("missing --run-spec\n{}", usage()))?,
        custody_receipt_sha256: custody_receipt_sha256
            .ok_or_else(|| format!("missing --custody-receipt-sha256\n{}", usage()))?,
        db,
        pipe,
        receipt: receipt.ok_or_else(|| format!("missing --receipt\n{}", usage()))?,
    }))
}

fn parse_args() -> Result<Command, String> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or_else(|| usage().to_string())?;

    if command == "launch" {
        return parse_launch_arguments(args);
    }

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

    if command == "resource-guard-rearm" {
        let mut pipe = None;
        let mut frozen_observation_sha256 = None;
        let mut breach_class = None;
        let mut diagnostic_receipt = None;
        let mut diagnostic_receipt_sha256 = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--pipe" => pipe = Some(value),
                "--frozen-observation-sha256" => frozen_observation_sha256 = Some(value),
                "--breach-class" => breach_class = Some(value),
                "--diagnostic-receipt" => diagnostic_receipt = Some(PathBuf::from(value)),
                "--diagnostic-receipt-sha256" => diagnostic_receipt_sha256 = Some(value),
                _ => return Err(format!("unknown argument {flag}\n{}", usage())),
            }
        }
        return Ok(Command::ResourceGuardRearm {
            pipe: pipe.ok_or_else(|| format!("missing --pipe\n{}", usage()))?,
            frozen_observation_sha256: frozen_observation_sha256
                .ok_or_else(|| format!("missing --frozen-observation-sha256\n{}", usage()))?,
            breach_class: breach_class
                .ok_or_else(|| format!("missing --breach-class\n{}", usage()))?,
            diagnostic_receipt: diagnostic_receipt
                .ok_or_else(|| format!("missing --diagnostic-receipt\n{}", usage()))?,
            diagnostic_receipt_sha256: diagnostic_receipt_sha256
                .ok_or_else(|| format!("missing --diagnostic-receipt-sha256\n{}", usage()))?,
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

    if command == "data-catalog-status" {
        let flag = args
            .next()
            .ok_or_else(|| format!("missing --db\n{}", usage()))?;
        let db = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        if flag != "--db" || args.next().is_some() {
            return Err(format!(
                "arguments do not match data-catalog-status\n{}",
                usage()
            ));
        }
        return Ok(Command::DataCatalogStatus {
            db: PathBuf::from(db),
        });
    }

    if command == "register-artifact" {
        let mut db = None;
        let mut sha256 = None;
        let mut byte_count = None;
        let mut media_type = None;
        let mut locations = Vec::new();
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--db" => db = Some(PathBuf::from(value)),
                "--sha256" => sha256 = Some(value),
                "--byte-count" => {
                    byte_count = Some(
                        value
                            .parse::<i64>()
                            .map_err(|_| format!("--byte-count must be an integer\n{}", usage()))?,
                    )
                }
                "--media-type" => media_type = Some(value),
                "--location" => {
                    let (volume, locator) = value
                        .split_once('=')
                        .ok_or_else(|| format!("--location must be VOLUME=LOCATOR\n{}", usage()))?;
                    locations.push((volume.to_string(), locator.to_string()));
                }
                _ => return Err(format!("unknown flag {flag}\n{}", usage())),
            }
        }
        return Ok(Command::RegisterArtifact {
            db: db.ok_or_else(|| format!("missing --db\n{}", usage()))?,
            sha256: sha256.ok_or_else(|| format!("missing --sha256\n{}", usage()))?,
            byte_count: byte_count.ok_or_else(|| format!("missing --byte-count\n{}", usage()))?,
            media_type: media_type.ok_or_else(|| format!("missing --media-type\n{}", usage()))?,
            locations,
        });
    }

    if command == "retire-artifact-location" {
        let mut db = None;
        let mut sha256 = None;
        let mut volume = None;
        let mut locator = None;
        let mut reason = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--db" => db = Some(PathBuf::from(value)),
                "--sha256" => sha256 = Some(value),
                "--volume" => volume = Some(value),
                "--locator" => locator = Some(value),
                "--reason" => reason = Some(value),
                _ => return Err(format!("unknown flag {flag}\n{}", usage())),
            }
        }
        return Ok(Command::RetireArtifactLocation {
            db: db.ok_or_else(|| format!("missing --db\n{}", usage()))?,
            sha256: sha256.ok_or_else(|| format!("missing --sha256\n{}", usage()))?,
            volume: volume.ok_or_else(|| format!("missing --volume\n{}", usage()))?,
            locator: locator.ok_or_else(|| format!("missing --locator\n{}", usage()))?,
            reason: reason.ok_or_else(|| format!("missing --reason\n{}", usage()))?,
        });
    }

    if command == "custody-verify" {
        let mut db = None;
        let mut hashes = Vec::new();
        let mut roots = Vec::new();
        let mut receipt = None;
        let mut rehash = false;
        while let Some(flag) = args.next() {
            if flag == "--rehash" {
                rehash = true;
                continue;
            }
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--db" => db = Some(PathBuf::from(value)),
                "--hash" => hashes.push(value),
                "--root" => {
                    let (volume, path) = value
                        .split_once('=')
                        .ok_or_else(|| format!("--root must be VOLUME=PATH\n{}", usage()))?;
                    roots.push((volume.to_string(), PathBuf::from(path)));
                }
                "--receipt" => receipt = Some(PathBuf::from(value)),
                _ => return Err(format!("unknown flag {flag}\n{}", usage())),
            }
        }
        if hashes.is_empty() {
            return Err(format!(
                "custody-verify requires at least one --hash\n{}",
                usage()
            ));
        }
        return Ok(Command::CustodyVerify {
            db: db.ok_or_else(|| format!("missing --db\n{}", usage()))?,
            hashes,
            roots,
            rehash,
            receipt: receipt.ok_or_else(|| format!("missing --receipt\n{}", usage()))?,
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

fn call_rpc(
    pipe: &str,
    request: &Value,
    operation: &str,
) -> Result<Value, Box<dyn std::error::Error>> {
    call_rpc_with_server(pipe, request, operation, None)
}

fn call_rpc_with_server(
    pipe: &str,
    request: &Value,
    operation: &str,
    expected_server_pid: Option<u32>,
) -> Result<Value, Box<dyn std::error::Error>> {
    let encoded = serde_json::to_string(request)?;
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
    if let Some(expected_server_pid) = expected_server_pid {
        authenticate_pipe_server(&stream, expected_server_pid)?;
    }
    writeln!(stream, "{encoded}")?;
    stream.flush()?;
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line)?;
    let response: Value = serde_json::from_str(&line)?;
    if let Some(error) = response.get("error") {
        return Err(std::io::Error::other(format!("ember-lab {operation} failed: {error}")).into());
    }
    response.get("result").cloned().ok_or_else(|| {
        std::io::Error::other(format!("ember-lab {operation} response lacks result")).into()
    })
}

#[cfg(windows)]
fn authenticate_pipe_server(
    stream: &std::fs::File,
    expected_server_pid: u32,
) -> Result<(), Box<dyn std::error::Error>> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::Pipes::GetNamedPipeServerProcessId;
    use windows_sys::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    let pipe = stream.as_raw_handle().cast();
    let mut server_pid = 0u32;
    if unsafe { GetNamedPipeServerProcessId(pipe, &mut server_pid) } == 0
        || server_pid == 0
        || server_pid != expected_server_pid
    {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_DAEMON_IDENTITY_REFUSED").into());
    }
    let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, server_pid) };
    if process.is_null() {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_DAEMON_IDENTITY_REFUSED").into());
    }
    let mut path = vec![0u16; 32768];
    let mut size = path.len() as u32;
    let queried = unsafe { QueryFullProcessImageNameW(process, 0, path.as_mut_ptr(), &mut size) };
    unsafe { CloseHandle(process) };
    if queried == 0 {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_DAEMON_IDENTITY_REFUSED").into());
    }
    let server_path = std::fs::canonicalize(PathBuf::from(String::from_utf16_lossy(
        &path[..size as usize],
    )))?;
    let current_path = std::fs::canonicalize(std::env::current_exe()?)?;
    if !server_path
        .to_string_lossy()
        .eq_ignore_ascii_case(&current_path.to_string_lossy())
        || hash_file(&server_path)? != hash_file(&current_path)?
    {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_DAEMON_IDENTITY_REFUSED").into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn authenticate_pipe_server(
    _stream: &std::fs::File,
    _expected_server_pid: u32,
) -> Result<(), Box<dyn std::error::Error>> {
    Err(std::io::Error::other("VERIFIER_DISPATCH_DAEMON_IDENTITY_UNSUPPORTED").into())
}

fn consume_verifier_dispatch_token() -> Result<(), Box<dyn std::error::Error>> {
    let required = |name: &str| {
        std::env::var(name).map_err(|_| {
            std::io::Error::other(format!("VERIFIER_DISPATCH_TOKEN_REQUIRED: missing {name}"))
        })
    };
    let pipe = required(DISPATCH_PIPE_ENV)?;
    let job_id = required(DISPATCH_JOB_ID_ENV)?;
    let token = required(DISPATCH_TOKEN_ENV)?;
    let maximum_job_memory_bytes = required(DISPATCH_MAXIMUM_JOB_MEMORY_ENV)?;
    if job_id.trim().is_empty()
        || token.len() != 64
        || !token
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_TOKEN_INVALID").into());
    }
    if maximum_job_memory_bytes
        .parse::<u64>()
        .ok()
        .filter(|value| *value > 0)
        .is_none()
    {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_TOKEN_INVALID").into());
    }
    let daemon_pid = required(DISPATCH_DAEMON_PID_ENV)?;
    let daemon_pid = daemon_pid
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)
        .ok_or_else(|| std::io::Error::other("VERIFIER_DISPATCH_DAEMON_IDENTITY_REFUSED"))?;
    let request = json!({"jsonrpc":"2.0","id":1,"method":"consume_verifier_dispatch_token","params":{"job_id":job_id,"token":token}});
    let result = call_rpc_with_server(
        &pipe,
        &request,
        "dispatch-token consumption",
        Some(daemon_pid),
    )?;
    let expected_binary_sha256 = hash_file(&std::env::current_exe()?)?;
    let expected_source_sha256 = ember_lab_source_hash();
    let identity = result.get("daemon_identity");
    if result.get("consumed") != Some(&Value::Bool(true))
        || identity.and_then(|value| value.get("schema_version"))
            != Some(&Value::String("ember-lab-runtime-identity-v1".into()))
        || identity
            .and_then(|value| value.get("pid"))
            .and_then(Value::as_u64)
            != Some(daemon_pid as u64)
        || identity
            .and_then(|value| value.get("binary_sha256"))
            .and_then(Value::as_str)
            != Some(expected_binary_sha256.as_str())
        || identity
            .and_then(|value| value.get("source_sha256"))
            .and_then(Value::as_str)
            != Some(expected_source_sha256.as_str())
    {
        return Err(std::io::Error::other("VERIFIER_DISPATCH_TOKEN_REFUSED").into());
    }
    std::env::remove_var(DISPATCH_TOKEN_ENV);
    std::env::remove_var(DISPATCH_JOB_ID_ENV);
    std::env::remove_var(DISPATCH_DAEMON_PID_ENV);
    std::env::remove_var(DISPATCH_MAXIMUM_JOB_MEMORY_ENV);
    Ok(())
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
    let dispatch_id = manifest.dispatch_id.clone();
    let execution_manifest = manifest.clone();
    let completed = finalize_after_dispatch(
        daemon,
        dispatch_outcome,
        &dispatch_id,
        &manifest_sha256,
        receipt_path,
        |runner| {
            // The dispatched child emits the current minimal-slice operation outputs.
            // Ember Lab only reopens, validates, hashes, and fences those bytes below;
            // the rehearsal adapter never creates phase evidence.
            runner.daemon.execute_minimal_episode(
                &dispatch_id,
                execution_manifest.measurements.whole_run_peak_bytes,
                dispatch.expires_at_ms,
            )?;
            let (authoritative_peak_path, authoritative_peak_sha256, authoritative_peak_bytes) =
                runner.daemon.authoritative_whole_run_peak(&dispatch_id)?;
            let phase_evidence = runner.daemon.load_authorized_phase_evidence(&dispatch_id)?;
            let mut execution_manifest = execution_manifest.clone();
            execution_manifest.phase_evidence = phase_evidence.clone();
            execution_manifest.measurements.evidence_path = authoritative_peak_path;
            execution_manifest.measurements.evidence_sha256 = authoritative_peak_sha256;
            execution_manifest.measurements.whole_run_peak_bytes = authoritative_peak_bytes;
            runner.phase_evidence = phase_evidence;
            Ok(rehearsal::episode(capability, &execution_manifest, runner))
        },
    )?;
    println!(
        "rehearse: {} -- receipt written to {}",
        if completed { "completed" } else { "refused" },
        receipt_path.display()
    );
    Ok(completed)
}

fn finalize_after_dispatch<F>(
    daemon: Daemon,
    dispatch: DispatchOutcome,
    job_id: &str,
    manifest_sha256: &str,
    receipt_path: &Path,
    operation: F,
) -> Result<bool, Box<dyn std::error::Error>>
where
    F: FnOnce(
        &mut CurrentAuthorityRunner,
    ) -> Result<rehearsal::RehearsalResult, Box<dyn std::error::Error>>,
{
    let mut runner = CurrentAuthorityRunner {
        daemon,
        job_id: job_id.into(),
        dispatch: Some(dispatch),
        phase_evidence: Vec::new(),
    };
    let attempt = operation(&mut runner);
    let (completed, observation) = match attempt {
        Ok(result) => (
            result.status == rehearsal::RehearsalStatus::Completed,
            json!({
                "manifest_sha256": manifest_sha256,
                "result": result.receipt,
            }),
        ),
        Err(error) => (
            false,
            json!({
                "manifest_sha256": manifest_sha256,
                "status": "REFUSED",
                "result": "REFUSED",
                "next_action": "Inspect the operational receipt failure and fix the named readiness or evidence gate before retrying.",
                "failure": {
                    "stage": "post_dispatch",
                    "code": "POST_DISPATCH_REFUSED",
                    "detail": error.to_string(),
                },
            }),
        ),
    };
    let stop_error = runner.daemon.stop_job(job_id).err();
    let operational = runner
        .daemon
        .export_content_addressed_receipt_with_observation(
            job_id,
            receipt_path.parent().unwrap_or_else(|| Path::new(".")),
            &observation,
        );
    if let Some(error) = stop_error {
        return Err(std::io::Error::other(format!(
            "post-dispatch cleanup failed after one owned stop attempt: {error:?}"
        ))
        .into());
    }
    let operational = operational?;
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
    Ok(completed)
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
    call_rpc(pipe, &request, "dispatch")
}

fn resource_guard_rearm(
    pipe: &str,
    frozen_observation_sha256: &str,
    breach_class: &str,
    diagnostic_receipt: &Path,
    diagnostic_receipt_sha256: &str,
) -> Result<Value, Box<dyn std::error::Error>> {
    let request = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "resource_guard_rearm",
        "params": {
            "frozen_observation_sha256": frozen_observation_sha256,
            "breach_class": breach_class,
            "diagnostic_receipt_path": diagnostic_receipt,
            "diagnostic_receipt_sha256": diagnostic_receipt_sha256,
        },
    });
    call_rpc(pipe, &request, "resource-guard-rearm")
}

fn resolve_python_executable() -> Result<PathBuf, Box<dyn std::error::Error>> {
    let mut candidates = Vec::new();
    if let Some(explicit) = std::env::var_os("EMBER_PYTHON") {
        candidates.push(PathBuf::from(explicit));
    }
    if let Some(home) = std::env::var_os("PYTHONHOME") {
        candidates.push(PathBuf::from(home).join("python.exe"));
    }
    if let Some(path) = std::env::var_os("PATH") {
        for directory in std::env::split_paths(&path) {
            candidates.push(directory.join("python.exe"));
            candidates.push(directory.join("python3.exe"));
        }
    }
    for candidate in candidates {
        if candidate.is_file() {
            return Ok(std::fs::canonicalize(candidate)?);
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::NotFound,
        "certified launch could not resolve a Python executable from EMBER_PYTHON, PYTHONHOME, or PATH",
    )
    .into())
}

fn probe_launch_daemon(pipe: &str) -> Result<Option<u32>, Box<dyn std::error::Error>> {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        match OpenOptions::new().read(true).write(true).open(pipe) {
            Ok(mut stream) => {
                let request = serde_json::to_string(&json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "runtime_identity",
                    "params": {}
                }))?;
                writeln!(stream, "{request}")?;
                stream.flush()?;
                let mut line = String::new();
                BufReader::new(stream).read_line(&mut line)?;
                let response: Value = serde_json::from_str(&line)?;
                let pid = response
                    .get("result")
                    .and_then(|result| result.get("pid"))
                    .and_then(Value::as_u64)
                    .and_then(|pid| u32::try_from(pid).ok())
                    .filter(|pid| *pid != 0)
                    .ok_or_else(|| {
                        std::io::Error::other(
                            "certified launch named pipe is not an Ember Lab daemon",
                        )
                    })?;
                return Ok(Some(pid));
            }
            Err(error)
                if matches!(error.raw_os_error(), Some(2 | 3 | 231))
                    && Instant::now() < deadline =>
            {
                std::thread::sleep(Duration::from_millis(20));
            }
            Err(error) if matches!(error.raw_os_error(), Some(2 | 3 | 231)) => return Ok(None),
            Err(error) => return Err(error.into()),
        }
    }
}

fn ensure_launch_daemon(
    defaults: &CertifiedLaunchDaemonDefaults,
    log_root: &Path,
) -> Result<LaunchDaemon, Box<dyn std::error::Error>> {
    if let Some(pid) = probe_launch_daemon(&defaults.pipe)? {
        return Ok(LaunchDaemon {
            child: None,
            mode: "existing",
            pid,
        });
    }
    let stdout_path = log_root.join("daemon.stdout.log");
    let stderr_path = log_root.join("daemon.stderr.log");
    let stdout = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&stdout_path)?;
    let stderr = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&stderr_path)?;
    let mut command = ProcessCommand::new(std::env::current_exe()?);
    command
        .arg("serve")
        .arg("--db")
        .arg(&defaults.db)
        .arg("--pipe")
        .arg(&defaults.pipe)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let mut child = command.spawn()?;
    let expected_pid = child.id();
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(status) = child.try_wait()? {
            return Err(std::io::Error::other(format!(
                "certified launch owned daemon exited before readiness with {status}; inspect {} and {}",
                stdout_path.display(),
                stderr_path.display()
            ))
            .into());
        }
        if let Some(observed_pid) = probe_launch_daemon(&defaults.pipe)? {
            if observed_pid != expected_pid {
                return Err(std::io::Error::other(format!(
                    "certified launch pipe became owned by unexpected daemon PID {observed_pid}, expected {expected_pid}"
                ))
                .into());
            }
            return Ok(LaunchDaemon {
                child: Some(child),
                mode: "owned_started",
                pid: expected_pid,
            });
        }
        if Instant::now() >= deadline {
            return Err(std::io::Error::other(format!(
                "certified launch owned daemon did not become ready; inspect {} and {}",
                stdout_path.display(),
                stderr_path.display()
            ))
            .into());
        }
    }
}

fn shutdown_owned_launch_daemon(
    pipe: &str,
    daemon: &mut LaunchDaemon,
) -> Result<(), Box<dyn std::error::Error>> {
    let Some(child) = daemon.child.as_mut() else {
        return Ok(());
    };
    call_rpc(
        pipe,
        &json!({"jsonrpc":"2.0","id":1,"method":"shutdown","params":{}}),
        "launch-owned-daemon-shutdown",
    )?;
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if child.try_wait()?.is_some() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(std::io::Error::other(
                "certified launch owned daemon did not exit after shutdown",
            )
            .into());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
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
        Command::Launch(cli) => {
            let python = resolve_python_executable()?;
            let now_ms = i64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
            let (request, daemon_defaults) = resolve_certified_launch_request(cli, python, now_ms)?;
            let receipt = request.receipt.clone();
            let run_custody_root = certified_launch_run_custody_root(&request.run_spec)?;
            let prepared = prepare_certified_launch(&request)?;
            if prepared.run_custody_root != run_custody_root {
                return Err(std::io::Error::other(
                    "certified launch run custody changed between daemon resolution and dispatch",
                )
                .into());
            }
            let log_root = prepared.manifest_path.parent().ok_or_else(|| {
                std::io::Error::other("certified launch manifest lacks a custody parent")
            })?;
            let mut daemon = ensure_launch_daemon(&daemon_defaults, log_root)?;
            let attempt = launch_prepared_certified_with(
                &prepared,
                daemon.mode,
                daemon.pid,
                |rpc_request| call_rpc(&daemon_defaults.pipe, rpc_request, "launch"),
                || std::thread::sleep(Duration::from_millis(100)),
            );
            let shutdown = shutdown_owned_launch_daemon(&daemon_defaults.pipe, &mut daemon);
            let completion = match (attempt, shutdown) {
                (Ok(completion), Ok(())) => completion,
                (Err(error), Ok(())) => return Err(error),
                (Ok(_), Err(error)) => return Err(error),
                (Err(operation), Err(cleanup)) => {
                    return Err(std::io::Error::other(format!(
                        "certified launch failed: {operation}; owned daemon cleanup also failed: {cleanup}"
                    ))
                    .into())
                }
            };
            if !completion.stderr.is_empty() {
                eprint!("{}", completion.stderr);
                std::io::stderr().flush()?;
            }
            println!(
                "{}",
                serde_json::to_string(&json!({
                    "exit_code": completion.exit_code,
                    "operational_receipt": receipt
                }))?
            );
            if completion.exit_code != 0 {
                std::process::exit(completion.exit_code);
            }
        }
        Command::ResourceGuardRearm {
            pipe,
            frozen_observation_sha256,
            breach_class,
            diagnostic_receipt,
            diagnostic_receipt_sha256,
        } => {
            println!(
                "{}",
                serde_json::to_string(&resource_guard_rearm(
                    &pipe,
                    &frozen_observation_sha256,
                    &breach_class,
                    &diagnostic_receipt,
                    &diagnostic_receipt_sha256,
                )?)?
            );
        }
        Command::DataCatalogStatus { db } => {
            println!(
                "{}",
                serde_json::to_string(&read_data_catalog_status(&db)?)?
            );
        }
        Command::RegisterArtifact {
            db,
            sha256,
            byte_count,
            media_type,
            locations,
        } => {
            let daemon = Daemon::open(&db)?;
            let locations: Vec<ArtifactLocationInput> = locations
                .into_iter()
                .map(|(volume, locator)| ArtifactLocationInput { volume, locator })
                .collect();
            let outcome = daemon.register_artifact(&sha256, byte_count, &media_type, &locations)?;
            println!(
                "register-artifact: object {} ({}), {} location(s) newly registered",
                outcome.object_id,
                if outcome.object_newly_registered {
                    "new"
                } else {
                    "already present, identical"
                },
                outcome
                    .locations
                    .iter()
                    .filter(|location| location.newly_registered)
                    .count()
            );
        }
        Command::RetireArtifactLocation {
            db,
            sha256,
            volume,
            locator,
            reason,
        } => {
            let daemon = Daemon::open(&db)?;
            daemon.retire_artifact_location(&sha256, &volume, &locator, &reason)?;
            println!("retire-artifact-location: {volume}/{locator} for sha256:{sha256} retired");
        }
        Command::CustodyVerify {
            db,
            hashes,
            roots,
            rehash,
            receipt,
        } => {
            let root_map: BTreeMap<String, PathBuf> = roots.into_iter().collect();
            let outcome = read_custody_verify(&db, &hashes, &root_map, rehash)?;
            std::fs::write(&receipt, serde_json::to_vec_pretty(&outcome)?)?;
            println!("{}", serde_json::to_string(&outcome)?);
            // Mirrors verify-training's own convention (see its comment above): a completed-
            // but-refused verdict is exit 1, distinct from an infra-level Err (unreadable db,
            // missing root mapping) that main() already turns into exit 1 on its own -- a
            // caller that needs to tell them apart reads the receipt's `admitted` field, not
            // the exit code alone. The receipt is always written before this check, so a
            // refusal is never reported without one.
            let admitted = outcome
                .get("admitted")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            if !admitted {
                std::process::exit(1);
            }
        }
        Command::ProduceMinimalSlice { root, job_id } => {
            rehearsal::produce_minimal_slice(&root, &job_id)?;
        }
        Command::VerifyTraining {
            root,
            receipt,
            certificate,
        } => {
            consume_verifier_dispatch_token()?;
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
    use ember_lab::{JobSpec, ReceiptArtifact};

    #[test]
    fn certified_launch_manifest_is_derived_and_pins_the_exact_validator_inputs() {
        let root = std::env::temp_dir().join(format!(
            "ember-lab-certified-launch-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let repo = root.join("repo");
        let packet = root.join("custody").join("run-1").join("launch-authority");
        std::fs::create_dir_all(repo.join("tools/ember-restart-3b")).unwrap();
        std::fs::create_dir_all(&packet).unwrap();
        std::fs::write(repo.join("README.md"), b"bound root").unwrap();
        let validator = repo.join("tools/ember-restart-3b/certified_train_launch.py");
        std::fs::write(&validator, b"print('validator')\n").unwrap();
        let python = root.join("python.exe");
        std::fs::write(&python, b"python fixture").unwrap();
        let certificate = packet.join("certificate.json");
        std::fs::write(
            &certificate,
            serde_json::to_vec(&json!({
                "public_master_sha": "0123456789abcdef0123456789abcdef01234567",
                "execution_scope": {}
            }))
            .unwrap(),
        )
        .unwrap();
        let ledger = packet.join("declaration-ledger.jsonl");
        std::fs::write(&ledger, b"{}\n").unwrap();
        let run_spec = packet.join("run-spec.json");
        std::fs::write(
            &run_spec,
            serde_json::to_vec(&json!({
                "schema_version": "ember-certified-train-run-v1",
                "run_id": "run-1",
                "requested_scope": {
                    "mode": "governed-vertical",
                    "gpu_vram_gib": 20.0,
                    "transient_checkpoint_gib": 8.0,
                    "write_budget_bytes": 123_480_309_760_u64,
                    "custody_root": root.join("custody")
                }
            }))
            .unwrap(),
        )
        .unwrap();
        let custody = packet.join("launch-authority-custody.json");
        std::fs::write(&custody, b"custody receipt").unwrap();
        let custody_sha256 = hash_file(&custody).unwrap();
        let receipt = root.join("custody/run-1/certified-launch.json");
        let daemon_defaults =
            certified_launch_daemon_defaults(&root.join("custody/run-1"), None, None).unwrap();
        assert_eq!(daemon_defaults.db.file_name().unwrap(), "ember-lab.sqlite3");
        assert_eq!(
            std::fs::canonicalize(daemon_defaults.db.parent().unwrap()).unwrap(),
            std::fs::canonicalize(root.join("custody/run-1")).unwrap()
        );
        assert!(daemon_defaults
            .pipe
            .starts_with(r"\\.\pipe\ember-lab-certified-"));
        let alternate_defaults = certified_launch_daemon_defaults(
            &root.join("custody").join(".").join("run-1").join("."),
            None,
            None,
        )
        .unwrap();
        assert_eq!(alternate_defaults.db, daemon_defaults.db);
        assert_eq!(alternate_defaults.pipe, daemon_defaults.pipe);
        let daemon_db = rusqlite::Connection::open(&daemon_defaults.db).unwrap();
        daemon_db.execute_batch("PRAGMA user_version=0;").unwrap();
        drop(daemon_db);
        let (resolved_request, resolved_defaults) = resolve_certified_launch_request(
            CertifiedLaunchCliArgs {
                root: repo.clone(),
                certificate: certificate.clone(),
                declaration_ledger: ledger.clone(),
                run_spec: run_spec.clone(),
                custody_receipt_sha256: custody_sha256.clone(),
                db: None,
                pipe: None,
                receipt: receipt.clone(),
            },
            python.clone(),
            1_800_000_000_000,
        )
        .unwrap();
        assert_eq!(resolved_defaults.db, daemon_defaults.db);
        assert_eq!(resolved_defaults.pipe, daemon_defaults.pipe);
        assert_eq!(resolved_request.pipe, daemon_defaults.pipe);
        let explicit_db = root.join("explicit.sqlite3");
        let explicit_pipe = r"\\.\pipe\explicit-launch-test".to_string();
        let (resolved_override_request, resolved_overrides) = resolve_certified_launch_request(
            CertifiedLaunchCliArgs {
                root: repo.clone(),
                certificate: certificate.clone(),
                declaration_ledger: ledger.clone(),
                run_spec: run_spec.clone(),
                custody_receipt_sha256: custody_sha256.clone(),
                db: Some(explicit_db.clone()),
                pipe: Some(explicit_pipe.clone()),
                receipt: receipt.clone(),
            },
            python.clone(),
            1_800_000_000_000,
        )
        .unwrap();
        assert_eq!(resolved_overrides.db, explicit_db);
        assert_eq!(resolved_overrides.pipe, explicit_pipe);
        assert_eq!(resolved_override_request.pipe, explicit_pipe);

        let mut refused_rpc_calls = 0;
        let refused_request = CertifiedLaunchRequest {
            root: repo.clone(),
            certificate: certificate.clone(),
            declaration_ledger: ledger.clone(),
            run_spec: run_spec.clone(),
            custody_receipt_sha256: "0".repeat(64),
            pipe: r"\\.\pipe\ember-lab-test".into(),
            receipt: receipt.clone(),
            python_executable: python.clone(),
            now_ms: 1_800_000_000_000,
        };
        let refusal = launch_certified_with(
            &refused_request,
            |_request| {
                refused_rpc_calls += 1;
                Ok(Value::Null)
            },
            || {},
        )
        .unwrap_err();
        assert!(refusal
            .to_string()
            .contains("custody receipt SHA-256 mismatch"));
        assert_eq!(
            refused_rpc_calls, 0,
            "no dispatch RPC means no child and no job row"
        );

        let request = CertifiedLaunchRequest {
            root: repo.clone(),
            certificate: certificate.clone(),
            declaration_ledger: ledger.clone(),
            run_spec: run_spec.clone(),
            custody_receipt_sha256: custody_sha256.clone(),
            pipe: r"\\.\pipe\ember-lab-test".into(),
            receipt: receipt.clone(),
            python_executable: python.clone(),
            now_ms: 1_800_000_000_000,
        };
        let prepared = prepare_certified_launch(&request).unwrap();
        let manifest: Value =
            serde_json::from_slice(&std::fs::read(&prepared.manifest_path).unwrap()).unwrap();
        assert_eq!(manifest["schema_version"], "ember-lab-dispatch-manifest-v3");
        assert_eq!(
            manifest["source_commit"],
            "0123456789abcdef0123456789abcdef01234567"
        );
        assert_eq!(
            manifest["program"]["path"],
            python.to_string_lossy().as_ref()
        );
        assert_eq!(manifest["program"]["sha256"], hash_file(&python).unwrap());
        assert_eq!(manifest["args"][0], validator.to_string_lossy().as_ref());
        assert_eq!(manifest["args"][1], "--root");
        assert_eq!(manifest["args"][3], "--certificate");
        assert_eq!(manifest["args"][5], "--declaration-ledger");
        assert_eq!(manifest["args"][7], "--run-spec");
        assert_eq!(manifest["args"][9], "--custody-receipt-sha256");
        assert_eq!(manifest["args"][10], custody_sha256);
        assert_eq!(
            manifest["workload_profile"]["profile_id"],
            "governed_vertical"
        );
        assert_eq!(
            manifest["simulated_peak_commit_bytes"],
            92_u64 * 1024 * 1024 * 1024
        );
        assert_eq!(
            manifest["maximum_job_memory_bytes"],
            94_u64 * 1024 * 1024 * 1024
        );
        assert_eq!(
            manifest["required_available_maximum_commit_bytes"],
            104_u64 * 1024 * 1024 * 1024
        );
        assert_eq!(
            manifest["minimum_free_vram_bytes"],
            20_u64 * 1024 * 1024 * 1024
        );
        assert_eq!(
            manifest["storage_reserves"][0]["minimum_free_bytes"],
            123_480_309_760_u64
        );
        assert!(manifest["bindings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|binding| {
                binding["path"] == validator.to_string_lossy().as_ref()
                    && binding["sha256"] == hash_file(&validator).unwrap()
            }));
        assert_eq!(prepared.job_id, manifest["job_id"]);
        assert_eq!(prepared.receipt_path, receipt);
    }

    #[test]
    fn certified_launch_completion_exports_receipt_and_propagates_exact_child_result() {
        let receipt = PathBuf::from(r"B:\custody\certified-launch.json");
        let mut methods = Vec::new();
        let mut state_samples = 0;
        let completion = complete_certified_launch(
            "run-1-launch-1800000000000",
            &receipt,
            |request| {
                let method = request["method"].as_str().unwrap().to_string();
                methods.push(method.clone());
                Ok(match method.as_str() {
                    "job_state" => {
                        state_samples += 1;
                        json!({"state": if state_samples == 1 { "running" } else { "exited" }})
                    }
                    "job_result" => json!({
                        "exit_code": 2,
                        "stderr": "error: declaration-ledger membership failed\r\n"
                    }),
                    "export_receipt" => json!({"exported": true}),
                    _ => panic!("unexpected method {method}"),
                })
            },
            || {},
        )
        .unwrap();
        assert_eq!(completion.exit_code, 2);
        assert_eq!(
            completion.stderr,
            "error: declaration-ledger membership failed\r\n"
        );
        assert_eq!(
            methods,
            ["job_state", "job_state", "job_result", "export_receipt"]
        );
    }

    #[test]
    fn certified_launch_cli_accepts_zero_daemon_arguments() {
        let command = parse_launch_arguments(
            [
                "--root",
                "C:\\repo",
                "--certificate",
                "B:\\run\\certificate.json",
                "--declaration-ledger",
                "B:\\run\\declaration-ledger.jsonl",
                "--run-spec",
                "B:\\run\\run-spec.json",
                "--custody-receipt-sha256",
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "--receipt",
                "B:\\run\\launch.json",
            ]
            .into_iter()
            .map(str::to_string),
        )
        .unwrap();
        let Command::Launch(cli) = command else {
            panic!("launch parser returned another command");
        };
        assert!(cli.db.is_none());
        assert!(cli.pipe.is_none());

        let command = parse_launch_arguments(
            [
                "--root",
                "C:\\repo",
                "--certificate",
                "B:\\run\\certificate.json",
                "--declaration-ledger",
                "B:\\run\\declaration-ledger.jsonl",
                "--run-spec",
                "B:\\run\\run-spec.json",
                "--custody-receipt-sha256",
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "--receipt",
                "B:\\run\\launch.json",
                "--db",
                "B:\\run\\explicit.sqlite3",
                "--pipe",
                r"\\.\pipe\explicit",
            ]
            .into_iter()
            .map(str::to_string),
        )
        .unwrap();
        let Command::Launch(cli) = command else {
            panic!("launch parser returned another command");
        };
        assert_eq!(cli.db.unwrap(), PathBuf::from(r"B:\run\explicit.sqlite3"));
        assert_eq!(cli.pipe.as_deref(), Some(r"\\.\pipe\explicit"));
    }

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

    #[test]
    fn rehearsal_orchestration_fixture_child() {
        if std::env::var("EMBER_LAB_ORCHESTRATION_FIXTURE").as_deref() != Ok("1") {
            return;
        }
        std::thread::sleep(Duration::from_secs(30));
    }

    #[test]
    fn post_dispatch_failure_stops_owned_job_once_and_exports_refusal() {
        let root = std::env::temp_dir().join(format!(
            "ember-lab-orchestration-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let db = root.join("ember-lab.sqlite3");
        let identity = std::env::current_exe().unwrap();
        let identity_sha256 = hash_file(&identity).unwrap();
        let daemon = Daemon::open(&db).unwrap();
        daemon
            .bind_identity("orchestration-failure", &identity, &identity_sha256)
            .unwrap();
        daemon
            .acquire_lease("cpu-fixture", "orchestration-failure")
            .unwrap();
        let spec = JobSpec::new(
            "orchestration-failure",
            identity.to_string_lossy(),
            [
                "--exact",
                // Single `tests::` -- this binary's only test module. The old
                // `tests::tests::` path matched zero tests, so the fixture's
                // 30s sleep never ran and the child exited during startup,
                // leaving the stop to race the child's own exit.
                "tests::rehearsal_orchestration_fixture_child",
                "--nocapture",
            ],
            "cpu-fixture",
        )
        .with_env("EMBER_LAB_ORCHESTRATION_FIXTURE", "1");
        let handle = daemon.start_job(spec).unwrap();
        let dispatch = DispatchOutcome {
            handle,
            receipt: ReceiptArtifact {
                path: root.join("dispatch.json"),
                sha256: "0".repeat(64),
            },
        };
        let receipt_path = root.join("rehearsal-receipt.json");
        let completed = finalize_after_dispatch(
            daemon,
            dispatch,
            "orchestration-failure",
            "m".repeat(64).as_str(),
            &receipt_path,
            |_runner| Err(std::io::Error::other("completion marker expired").into()),
        )
        .unwrap();
        assert!(!completed);
        let reopened = Daemon::open(&db).unwrap();
        assert_eq!(
            reopened.job_state("orchestration-failure").unwrap(),
            Some(ember_lab::JobState::Stopped)
        );
        let events = reopened.job_event_kinds("orchestration-failure").unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|kind| kind.as_str() == "job_stop_requested")
                .count(),
            1
        );
        assert_eq!(
            events
                .iter()
                .filter(|kind| kind.as_str() == "job_stopped")
                .count(),
            1
        );
        let receipt: Value = serde_json::from_slice(&std::fs::read(receipt_path).unwrap()).unwrap();
        assert_eq!(receipt["rehearsal"]["status"], "REFUSED");
        assert_eq!(
            receipt["rehearsal"]["next_action"],
            "Inspect the operational receipt failure and fix the named readiness or evidence gate before retrying."
        );
        assert_eq!(receipt["rehearsal"]["failure"]["stage"], "post_dispatch");
    }
}
