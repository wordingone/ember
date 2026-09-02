#![cfg_attr(windows, windows_subsystem = "windows")]
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::data_catalog::ArtifactLocationInput;
use ember_lab::rehearsal::{self, Phase, PhaseOutcome, RehearsalManifest, RehearsalRunner};
use ember_lab::{
    ember_lab_source_hash, hash_file, probe_single_vram_device_capacity, read_custody_verify,
    read_data_catalog_status, rpc::serve_named_pipe, training_verify, Daemon, DispatchManifest,
    DispatchOutcome, DispatchVramWall, VramDeviceCapacity, VramWallContract,
    MAX_DISPATCH_MANIFEST_BYTES,
};
use serde::{Deserialize, Serialize};
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
const CERTIFIED_LAUNCH_VRAM_HEADROOM_RESERVE_BYTES: u64 = 256 * 1024 * 1024;
const CERTIFIED_LAUNCH_PROBE_STORAGE_RESERVE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct JobMemoryCeilingProbeAuthority {
    maximum_job_memory_bytes: u64,
    maximum_absolute_delta_bytes: u64,
    signed_delta_bytes: i64,
    allocation_target_bytes: u64,
}

#[derive(Clone, Debug, Deserialize)]
struct ResourceMechanismProjection {
    total_parameters: u64,
    active_parameters: u64,
    parameter_bytes_all: u64,
    gradient_bytes_active: u64,
    optimizer_state_bytes_active: u64,
    activation_reserve_bytes: u64,
    runtime_reserve_bytes: u64,
    mechanism_peak_bytes: u64,
    checkpoint_publication_host_commit_reserve_bytes: u64,
}

struct HostCommitModel {
    simulated_peak_commit_bytes: u64,
    maximum_job_memory_bytes: u64,
    required_available_maximum_commit_bytes: u64,
}

struct PreparedCertifiedLaunch {
    manifest_path: PathBuf,
    job_id: String,
    receipt_path: PathBuf,
    run_custody_root: PathBuf,
    terminal_contract: CertifiedLaunchTerminalContract,
}

#[derive(Debug)]
enum CertifiedLaunchTerminalContract {
    None,
    Artifacts(Vec<PathBuf>),
    JobMemoryProbeStdout,
}

const CERTIFIED_LAUNCH_PYTHON_TRAMPOLINE: &str = "import importlib.util,pathlib,sys;script=pathlib.Path(sys.argv[1]);sys.path[:0]=[sys.argv[2],sys.argv[3]];spec=importlib.util.spec_from_file_location('ember_certified_train_launch',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);raise SystemExit(module.main(sys.argv[4:]))";

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
    receipt: Option<PathBuf>,
}

struct CockpitCliArgs {
    root: PathBuf,
    application: PathBuf,
    source_commit: String,
    state_root: PathBuf,
    db: Option<PathBuf>,
    pipe: Option<String>,
    receipt: Option<PathBuf>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum StorageRetentionOperation {
    DryRun,
    Commit,
    Resume,
    Rollback,
}

struct StorageRetentionCliArgs {
    pipe: String,
    repository_root: PathBuf,
    policy: PathBuf,
    declarations: PathBuf,
    models_root: PathBuf,
    state_root: PathBuf,
    custody: PathBuf,
    pin_set_sha256: String,
    current_master: String,
    projected_models_bytes: u64,
    projected_state_bytes: u64,
    operation: StorageRetentionOperation,
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CockpitPlacement {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
}

fn left_half_placement(left: i32, top: i32, right: i32, bottom: i32) -> Option<CockpitPlacement> {
    let width = right.checked_sub(left)?;
    let height = bottom.checked_sub(top)?;
    if width <= 1 || height <= 0 {
        return None;
    }
    Some(CockpitPlacement {
        x: left,
        y: top,
        width: width / 2,
        height,
    })
}

#[cfg(windows)]
fn place_cockpit_window_left(governed_pid: u32) -> Result<(), Box<dyn std::error::Error>> {
    use windows_sys::Win32::Foundation::{BOOL, HWND, LPARAM, RECT};
    use windows_sys::Win32::Graphics::Gdi::{
        GetMonitorInfoW, MonitorFromWindow, MONITORINFO, MONITOR_DEFAULTTONEAREST,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetWindowThreadProcessId, IsWindowVisible, SetWindowPos, SWP_NOACTIVATE,
        SWP_NOZORDER,
    };

    struct Search {
        pid: u32,
        hwnd: HWND,
    }

    unsafe extern "system" fn visit(hwnd: HWND, parameter: LPARAM) -> BOOL {
        let search = &mut *(parameter as *mut Search);
        let mut owner_pid = 0u32;
        GetWindowThreadProcessId(hwnd, &mut owner_pid);
        if owner_pid == search.pid && IsWindowVisible(hwnd) != 0 {
            search.hwnd = hwnd;
            return 0;
        }
        1
    }

    let deadline = Instant::now() + Duration::from_secs(5);
    let hwnd = loop {
        let mut search = Search {
            pid: governed_pid,
            hwnd: std::ptr::null_mut(),
        };
        unsafe {
            EnumWindows(Some(visit), (&mut search as *mut Search) as LPARAM);
        }
        if !search.hwnd.is_null() {
            break search.hwnd;
        }
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!(
                    "no visible top-level window appeared for governed cockpit PID {governed_pid}"
                ),
            )
            .into());
        }
        std::thread::sleep(Duration::from_millis(50));
    };

    let monitor = unsafe { MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) };
    if monitor.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        rcMonitor: RECT {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        },
        rcWork: RECT {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        },
        dwFlags: 0,
    };
    if unsafe { GetMonitorInfoW(monitor, &mut info) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let placement = left_half_placement(
        info.rcWork.left,
        info.rcWork.top,
        info.rcWork.right,
        info.rcWork.bottom,
    )
    .ok_or_else(|| std::io::Error::other("cockpit monitor work area is invalid"))?;
    if unsafe {
        SetWindowPos(
            hwnd,
            std::ptr::null_mut(),
            placement.x,
            placement.y,
            placement.width,
            placement.height,
            SWP_NOZORDER | SWP_NOACTIVATE,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
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

const DEFAULT_CERTIFIED_LAUNCH_RECEIPT: &str = "ember-lab-certified-launch-operational.json";

fn resolve_certified_launch_request(
    cli: CertifiedLaunchCliArgs,
    python_executable: PathBuf,
    now_ms: i64,
) -> Result<(CertifiedLaunchRequest, CertifiedLaunchDaemonDefaults), Box<dyn std::error::Error>> {
    let run_custody_root = certified_launch_run_custody_root(&cli.run_spec)?;
    let receipt = cli
        .receipt
        .unwrap_or_else(|| run_custody_root.join(DEFAULT_CERTIFIED_LAUNCH_RECEIPT));
    let daemon = certified_launch_daemon_defaults(&run_custody_root, cli.db, cli.pipe)?;
    let request = CertifiedLaunchRequest {
        root: cli.root,
        certificate: cli.certificate,
        declaration_ledger: cli.declaration_ledger,
        run_spec: cli.run_spec,
        custody_receipt_sha256: cli.custody_receipt_sha256,
        pipe: daemon.pipe.clone(),
        receipt,
        python_executable,
        now_ms,
    };
    Ok((request, daemon))
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
struct CertifiedLaunchStart {
    schema_version: &'static str,
    job_id: String,
    governed_pid: u32,
    preflight_receipt: PathBuf,
    preflight_receipt_sha256: String,
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
    launch_prepared_certified_with(&prepared, "existing", 0, rpc, |_| Ok(()), wait)
}

fn launch_prepared_certified_with<F, T, S>(
    prepared: &PreparedCertifiedLaunch,
    daemon_mode: &str,
    daemon_pid: u32,
    mut rpc: F,
    started: T,
    wait: S,
) -> Result<CertifiedLaunchCompletion, Box<dyn std::error::Error>>
where
    F: FnMut(&Value) -> Result<Value, Box<dyn std::error::Error>>,
    T: FnOnce(&CertifiedLaunchStart) -> Result<(), Box<dyn std::error::Error>>,
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
    let governed_pid = dispatched
        .get("pid")
        .and_then(Value::as_u64)
        .and_then(|pid| u32::try_from(pid).ok())
        .filter(|pid| *pid != 0)
        .ok_or_else(|| {
            std::io::Error::other("certified launch dispatch response lacks governed child PID")
        })?;
    let preflight_receipt = dispatched
        .get("preflight_receipt_path")
        .and_then(Value::as_str)
        .filter(|path| !path.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| {
            std::io::Error::other("certified launch dispatch response lacks preflight receipt path")
        })?;
    let preflight_receipt_sha256 = dispatched
        .get("preflight_receipt_sha256")
        .and_then(Value::as_str)
        .filter(|sha256| sha256.len() == 64 && sha256.bytes().all(|byte| byte.is_ascii_hexdigit()))
        .ok_or_else(|| {
            std::io::Error::other(
                "certified launch dispatch response lacks preflight receipt SHA-256",
            )
        })?
        .to_ascii_lowercase();
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
    started(&CertifiedLaunchStart {
        schema_version: "ember-lab-certified-launch-start-v1",
        job_id: prepared.job_id.clone(),
        governed_pid,
        preflight_receipt,
        preflight_receipt_sha256,
    })?;
    complete_certified_launch(
        &prepared.job_id,
        &prepared.receipt_path,
        &prepared.terminal_contract,
        |request| rpc(request),
        wait,
    )
}

fn complete_certified_launch<F, S>(
    job_id: &str,
    receipt_path: &Path,
    terminal_contract: &CertifiedLaunchTerminalContract,
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
    let stdout = result
        .get("stdout")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            std::io::Error::other("certified launch terminal result lacks UTF-8 stdout")
        })?;
    let stderr = result
        .get("stderr")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            std::io::Error::other("certified launch terminal result lacks UTF-8 stderr")
        })?
        .to_string();
    let refusal = if exit_code == 0 {
        validate_certified_launch_terminal_contract(terminal_contract, stdout).err()
    } else {
        None
    };
    if let Some((evidence_locator, _)) = refusal.as_ref() {
        let recorded = rpc(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "record_launch_artifact_refusal",
            "params": {"job_id": job_id, "evidence_locator": evidence_locator}
        }))?;
        if recorded.get("recorded") != Some(&Value::Bool(true)) {
            return Err(std::io::Error::other(
                "certified launch artifact refusal was not recorded durably",
            )
            .into());
        }
    }
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
    if let Some((_, error)) = refusal {
        return Err(error.into());
    }
    Ok(CertifiedLaunchCompletion { exit_code, stderr })
}

fn validate_certified_launch_terminal_contract(
    contract: &CertifiedLaunchTerminalContract,
    stdout: &str,
) -> Result<(), (String, std::io::Error)> {
    match contract {
        CertifiedLaunchTerminalContract::None => Ok(()),
        CertifiedLaunchTerminalContract::Artifacts(paths) => {
            for path in paths {
                let metadata = std::fs::symlink_metadata(path).map_err(|error| {
                    (
                        path.to_string_lossy().into_owned(),
                        std::io::Error::other(format!(
                            "certified launch required terminal artifact is missing at {}: {error}",
                            path.display()
                        )),
                    )
                })?;
                if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() == 0 {
                    return Err((
                        path.to_string_lossy().into_owned(),
                        std::io::Error::other(format!(
                            "certified launch required terminal artifact is not a non-empty regular file: {}",
                            path.display()
                        )),
                    ));
                }
            }
            Ok(())
        }
        CertifiedLaunchTerminalContract::JobMemoryProbeStdout => {
            let mut phases = Vec::new();
            for line in stdout.lines().filter(|line| !line.trim().is_empty()) {
                let record: Value = serde_json::from_str(line).map_err(|error| {
                    (
                        "daemon-captured-stdout".into(),
                        std::io::Error::other(format!(
                            "certified launch probe stdout contains invalid JSON: {error}"
                        )),
                    )
                })?;
                if record.get("schema_version")
                    == Some(&Value::String("ember-job-memory-ceiling-probe-v1".into()))
                {
                    phases.push(
                        record
                            .get("phase")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                    );
                }
            }
            if phases != ["allocation_start", "allocation_complete"] {
                return Err((
                    "daemon-captured-stdout".into(),
                    std::io::Error::other(
                        "certified launch probe stdout lacks its ordered allocation records",
                    ),
                ));
            }
            Ok(())
        }
    }
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

const CERTIFIED_LAUNCH_REQUIRED_RUN_SPEC_KEYS: &[&str] = &[
    "certificate_sha256",
    "requested_scope",
    "run_id",
    "runner_receipt",
    "schema_version",
    "seed",
];
const CERTIFIED_LAUNCH_REQUIRED_EXECUTION_SCOPE_KEYS: &[&str] = &[
    "allowed_artifact_roots",
    "allowed_custody_roots",
    "allowed_modes",
    "max_active_expert_families",
    "max_b_write_gib",
    "max_c_write_gib",
    "max_gpu_vram_gib",
    "max_optimizer_steps",
    "max_records",
    "max_transient_checkpoint_gib",
    "max_wall_minutes",
    "max_write_budget_bytes",
    "model_server_allowed",
    "persistent_worker_allowed",
    "purpose",
    "wsl_allowed",
];
const CERTIFIED_LAUNCH_REQUIRED_REQUESTED_SCOPE_KEYS: &[&str] = &[
    "active_expert_families",
    "artifact_root",
    "custody_root",
    "gpu_vram_gib",
    "max_b_write_gib",
    "max_c_write_gib",
    "max_records",
    "mode",
    "optimizer_steps",
    "transient_checkpoint_gib",
    "wall_minutes",
    "write_budget_bytes",
];

fn parse_job_memory_ceiling_probe_authority(
    execution_scope: &serde_json::Map<String, Value>,
    run_spec: &serde_json::Map<String, Value>,
    requested_mode: &str,
) -> Result<Option<JobMemoryCeilingProbeAuthority>, Box<dyn std::error::Error>> {
    let authorized_raw = execution_scope.get("allowed_job_memory_ceiling_probe");
    let requested_raw = run_spec.get("job_memory_ceiling_probe");
    if authorized_raw.is_none() && requested_raw.is_none() {
        return Ok(None);
    }
    if requested_mode != "governed-vertical" || authorized_raw.is_none() || requested_raw.is_none()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "job-memory ceiling probe authority and request must be present together on governed-vertical",
        )
        .into());
    }
    let mut permitted_run_spec_keys = CERTIFIED_LAUNCH_REQUIRED_RUN_SPEC_KEYS
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    permitted_run_spec_keys.insert("job_memory_ceiling_probe");
    let mut permitted_execution_scope_keys = CERTIFIED_LAUNCH_REQUIRED_EXECUTION_SCOPE_KEYS
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    permitted_execution_scope_keys.insert("allowed_job_memory_ceiling_probe");
    let permitted_requested_scope_keys = CERTIFIED_LAUNCH_REQUIRED_REQUESTED_SCOPE_KEYS
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    let actual_run_spec_keys = run_spec
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    if let Some(unexpected) = actual_run_spec_keys
        .difference(&permitted_run_spec_keys)
        .next()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("job-memory ceiling probe run spec has unexpected key `{unexpected}`"),
        )
        .into());
    }
    if let Some(missing) = permitted_run_spec_keys
        .difference(&actual_run_spec_keys)
        .next()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("job-memory ceiling probe run spec lacks required key `{missing}`"),
        )
        .into());
    }
    let actual_execution_scope_keys = execution_scope
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    if let Some(unexpected) = actual_execution_scope_keys
        .difference(&permitted_execution_scope_keys)
        .next()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("job-memory ceiling probe certificate scope has unexpected key `{unexpected}`"),
        )
        .into());
    }
    if let Some(missing) = permitted_execution_scope_keys
        .difference(&actual_execution_scope_keys)
        .next()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("job-memory ceiling probe certificate scope lacks required key `{missing}`"),
        )
        .into());
    }
    let requested_scope = run_spec
        .get("requested_scope")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "job-memory ceiling probe requested_scope must be an object",
            )
        })?;
    let actual_requested_scope_keys = requested_scope
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    if let Some(unexpected) = actual_requested_scope_keys
        .difference(&permitted_requested_scope_keys)
        .next()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("job-memory ceiling probe requested scope has unexpected key `{unexpected}`"),
        )
        .into());
    }
    if let Some(missing) = permitted_requested_scope_keys
        .difference(&actual_requested_scope_keys)
        .next()
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            format!("job-memory ceiling probe requested scope lacks required key `{missing}`"),
        )
        .into());
    }
    let requested_zero_keys = [
        "active_expert_families",
        "gpu_vram_gib",
        "max_b_write_gib",
        "max_c_write_gib",
        "max_records",
        "optimizer_steps",
        "transient_checkpoint_gib",
        "write_budget_bytes",
    ];
    let authorized_zero_keys = [
        "max_active_expert_families",
        "max_b_write_gib",
        "max_c_write_gib",
        "max_gpu_vram_gib",
        "max_optimizer_steps",
        "max_records",
        "max_transient_checkpoint_gib",
        "max_write_budget_bytes",
    ];
    let allowed_modes_are_exact = execution_scope
        .get("allowed_modes")
        .and_then(Value::as_array)
        .is_some_and(|modes| modes.len() == 1 && modes[0].as_str() == Some("governed-vertical"));
    if !allowed_modes_are_exact
        || requested_zero_keys
            .iter()
            .any(|key| requested_scope.get(*key).and_then(Value::as_u64) != Some(0))
        || authorized_zero_keys
            .iter()
            .any(|key| execution_scope.get(*key).and_then(Value::as_u64) != Some(0))
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "job-memory ceiling probe is mutually exclusive with training scope",
        )
        .into());
    }
    let authorized = authorized_raw.and_then(Value::as_object).ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "allowed_job_memory_ceiling_probe must be an object",
        )
    })?;
    let requested = requested_raw.and_then(Value::as_object).ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "job_memory_ceiling_probe must be an object",
        )
    })?;
    let authorized_keys = ["maximum_absolute_delta_bytes", "maximum_job_memory_bytes"]
        .into_iter()
        .collect::<std::collections::BTreeSet<_>>();
    let requested_keys = ["maximum_job_memory_bytes", "signed_delta_bytes"]
        .into_iter()
        .collect::<std::collections::BTreeSet<_>>();
    if authorized
        .keys()
        .map(String::as_str)
        .collect::<std::collections::BTreeSet<_>>()
        != authorized_keys
        || requested
            .keys()
            .map(String::as_str)
            .collect::<std::collections::BTreeSet<_>>()
            != requested_keys
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "job-memory ceiling probe objects must use the exact closed key sets",
        )
        .into());
    }
    let maximum_job_memory_bytes = required_u64(authorized, "maximum_job_memory_bytes")?;
    let requested_maximum = required_u64(requested, "maximum_job_memory_bytes")?;
    let maximum_absolute_delta_bytes = required_u64(authorized, "maximum_absolute_delta_bytes")?;
    let signed_delta_bytes = requested
        .get("signed_delta_bytes")
        .and_then(Value::as_i64)
        .filter(|value| *value != 0)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "job-memory ceiling probe signed_delta_bytes must be a non-zero exact i64",
            )
        })?;
    let magnitude = signed_delta_bytes.unsigned_abs();
    if requested_maximum != maximum_job_memory_bytes || magnitude > maximum_absolute_delta_bytes {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "job-memory ceiling probe request exceeds its independent authenticated authority",
        )
        .into());
    }
    let allocation_target_bytes = if signed_delta_bytes > 0 {
        maximum_job_memory_bytes.checked_add(magnitude)
    } else {
        maximum_job_memory_bytes.checked_sub(magnitude)
    }
    .filter(|value| *value > 0)
    .ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "job-memory ceiling probe allocation target is invalid",
        )
    })?;
    Ok(Some(JobMemoryCeilingProbeAuthority {
        maximum_job_memory_bytes,
        maximum_absolute_delta_bytes,
        signed_delta_bytes,
        allocation_target_bytes,
    }))
}

fn parse_resource_projection(
    bytes: &[u8],
) -> Result<ResourceMechanismProjection, Box<dyn std::error::Error>> {
    let value: Value = serde_json::from_slice(bytes)?;
    if value.get("schema_version")
        != Some(&Value::String(
            "ember-issue898-resource-projection-v1".into(),
        ))
        || value.get("authority")
            != Some(&Value::String(
                "tools/ember-restart-3b/launch_packet.py::preflight_resource".into(),
            ))
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "certified launch resource producer returned an invalid authority binding",
        )
        .into());
    }
    let projection: ResourceMechanismProjection = serde_json::from_value(value)?;
    if projection.total_parameters == 0
        || projection.active_parameters == 0
        || projection.active_parameters > projection.total_parameters
        || projection.parameter_bytes_all == 0
        || projection.gradient_bytes_active == 0
        || projection.optimizer_state_bytes_active == 0
        || projection.activation_reserve_bytes == 0
        || projection.runtime_reserve_bytes == 0
        || projection.mechanism_peak_bytes == 0
        || projection.checkpoint_publication_host_commit_reserve_bytes == 0
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "certified launch resource producer returned an invalid projection",
        )
        .into());
    }
    Ok(projection)
}

fn resource_projection_from_producer(
    request: &CertifiedLaunchRequest,
) -> Result<ResourceMechanismProjection, Box<dyn std::error::Error>> {
    let producer = request
        .root
        .join("runtime/ember-lab/issue898_resource_projection.py");
    let config = request.root.join("configs/ember-restart-3b.json");
    if !producer.is_file() || !config.is_file() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "certified launch resource producer or bound config is unavailable",
        )
        .into());
    }
    let mut command = ProcessCommand::new(&request.python_executable);
    command
        .arg(&producer)
        .arg("--config")
        .arg(&config)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let output = command.output()?;
    if !output.status.success() {
        return Err(std::io::Error::other(format!(
            "certified launch resource projection producer refused: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ))
        .into());
    }
    parse_resource_projection(&output.stdout)
}

fn non_a1_host_commit_model(
    projection: &ResourceMechanismProjection,
    checkpoint_bytes: u64,
) -> Result<HostCommitModel, Box<dyn std::error::Error>> {
    let simulated_peak_commit_bytes = projection
        .mechanism_peak_bytes
        .checked_add(checkpoint_bytes)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch host-commit projection overflow",
            )
        })?;
    let maximum_job_memory_bytes = simulated_peak_commit_bytes;
    let required_available_maximum_commit_bytes = maximum_job_memory_bytes
        .checked_add(HOST_COMMIT_SURVIVAL_RESERVE_BYTES)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch host-survival reserve overflow",
            )
        })?;
    Ok(HostCommitModel {
        simulated_peak_commit_bytes,
        maximum_job_memory_bytes,
        required_available_maximum_commit_bytes,
    })
}

fn certified_launch_vram_wall(
    required_process_bytes: u64,
    capacity: VramDeviceCapacity,
) -> Result<DispatchVramWall, Box<dyn std::error::Error>> {
    if capacity.provider != "nvidia_smi_nvml"
        || capacity.device_uuid.trim().is_empty()
        || capacity.total_bytes == 0
        || capacity.free_bytes > capacity.total_bytes
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "certified launch observed an invalid VRAM device capacity",
        )
        .into());
    }
    if capacity.total_bytes < required_process_bytes {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!(
                "certified launch requires {required_process_bytes} VRAM bytes but measured device capacity is {} bytes",
                capacity.total_bytes
            ),
        )
        .into());
    }
    let fraction = required_process_bytes
        .checked_mul(1_000_000)
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch VRAM fraction derivation overflow",
            )
        })?
        / capacity.total_bytes;
    let maximum_process_fraction_millionths = u32::try_from(fraction)
        .ok()
        .filter(|value| (1..=1_000_000).contains(value))
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch VRAM fraction is outside the enforceable range",
            )
        })?;
    Ok(DispatchVramWall::Required(VramWallContract {
        provider: capacity.provider,
        device_uuid: capacity.device_uuid,
        maximum_process_fraction_millionths,
        minimum_free_bytes: CERTIFIED_LAUNCH_VRAM_HEADROOM_RESERVE_BYTES,
        consecutive_breach_samples: 3,
        sample_interval_ms: 2_000,
    }))
}

fn prepare_certified_launch(
    request: &CertifiedLaunchRequest,
) -> Result<PreparedCertifiedLaunch, Box<dyn std::error::Error>> {
    prepare_certified_launch_with(request, resource_projection_from_producer, |_| {
        probe_single_vram_device_capacity().map_err(Into::into)
    })
}

fn prepare_certified_launch_with<F, G>(
    request: &CertifiedLaunchRequest,
    load_resource_projection: F,
    load_vram_capacity: G,
) -> Result<PreparedCertifiedLaunch, Box<dyn std::error::Error>>
where
    F: FnOnce(
        &CertifiedLaunchRequest,
    ) -> Result<ResourceMechanismProjection, Box<dyn std::error::Error>>,
    G: FnOnce(&CertifiedLaunchRequest) -> Result<VramDeviceCapacity, Box<dyn std::error::Error>>,
{
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
    let is_a1_route = run_spec_object
        .get("a1_family")
        .is_some_and(|value| !value.is_null());
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
    let requested_mode = required_string(requested_scope, "mode")?;
    if requested_mode != "governed-vertical" {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "certified launch requested mode is unsupported",
        )
        .into());
    }
    let job_memory_probe =
        parse_job_memory_ceiling_probe_authority(execution_scope, run_spec_object, requested_mode)?;
    let is_job_memory_probe = job_memory_probe.is_some();
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
    let terminal_contract = if is_job_memory_probe {
        CertifiedLaunchTerminalContract::JobMemoryProbeStdout
    } else {
        let runner_receipt = PathBuf::from(required_string(run_spec_object, "runner_receipt")?);
        let runner_parent = runner_receipt.parent().ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch runner receipt lacks a parent",
            )
        })?;
        let canonical_runner_parent = std::fs::canonicalize(runner_parent)?;
        let runner_name = runner_receipt.file_name().ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch runner receipt lacks a file name",
            )
        })?;
        let runner_receipt = canonical_runner_parent.join(runner_name);
        let runner_stem = runner_receipt
            .file_stem()
            .and_then(|stem| stem.to_str())
            .filter(|stem| !stem.is_empty())
            .ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "certified launch runner receipt lacks a UTF-8 stem",
                )
            })?;
        let execution_receipt =
            runner_receipt.with_file_name(format!("{runner_stem}-certified-launch.json"));
        if !runner_receipt.is_absolute()
            || !runner_receipt.starts_with(&canonical_run_custody_root)
            || runner_receipt.exists()
            || execution_receipt.exists()
        {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch terminal artifacts must be new absolute paths inside the run custody root",
            )
            .into());
        }
        CertifiedLaunchTerminalContract::Artifacts(vec![runner_receipt, execution_receipt])
    };
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
    let validator = root.join("src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py");
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
    let resource_projection_producer =
        root.join("runtime/ember-lab/issue898_resource_projection.py");
    let resource_projection_config = root.join("configs/ember-restart-3b.json");
    if !is_a1_route && !is_job_memory_probe {
        for (label, path) in [
            (
                "resource projection producer",
                resource_projection_producer.as_path(),
            ),
            (
                "resource projection config",
                resource_projection_config.as_path(),
            ),
        ] {
            if !path.is_file() {
                let normalized_path = path.to_string_lossy().replace('\\', "/");
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    format!(
                        "certified launch {label} is unavailable at {normalized_path}; this bound repository root may predate the daemon binary",
                    ),
                )
                .into());
            }
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

    let (gpu_vram_bytes, vram_wall) = if is_job_memory_probe {
        (0, DispatchVramWall::NotApplicable)
    } else {
        let gpu_vram_bytes = required_gib(requested_scope, "gpu_vram_gib")?;
        let vram_capacity = load_vram_capacity(request).map_err(|error| {
            std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!(
                    "certified launch requires the nvidia-smi VRAM provider to measure and enforce its required VRAM wall: {error}"
                ),
            )
        })?;
        (
            gpu_vram_bytes,
            certified_launch_vram_wall(gpu_vram_bytes, vram_capacity)?,
        )
    };
    let checkpoint_bytes = if is_job_memory_probe {
        0
    } else {
        required_gib(requested_scope, "transient_checkpoint_gib")?
    };
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
    let resource_projection = if is_a1_route || is_job_memory_probe {
        None
    } else {
        Some(load_resource_projection(request)?)
    };
    let (
        simulated_peak_commit_bytes,
        maximum_job_memory_bytes,
        required_available_maximum_commit_bytes,
        pinned_host_producers,
        memory_model_authority,
    ) = if let Some(probe) = job_memory_probe {
        let required = probe
            .maximum_job_memory_bytes
            .checked_add(HOST_COMMIT_SURVIVAL_RESERVE_BYTES)
            .ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "job-memory ceiling probe host-commit requirement overflow",
                )
            })?;
        (
            probe.allocation_target_bytes,
            probe.maximum_job_memory_bytes,
            required,
            json!([{
                "kind": "job_memory_probe_allocator",
                "maximum_bytes": probe.allocation_target_bytes
            }]),
            json!({
                "route": "job_memory_ceiling_probe",
                "maximum_job_memory_bytes": probe.maximum_job_memory_bytes,
                "maximum_absolute_delta_bytes": probe.maximum_absolute_delta_bytes,
                "signed_delta_bytes": probe.signed_delta_bytes,
                "allocation_target_bytes": probe.allocation_target_bytes
            }),
        )
    } else if let Some(projection) = resource_projection.as_ref() {
        let model = non_a1_host_commit_model(projection, checkpoint_bytes)?;
        let training_mechanism_bytes = projection
            .mechanism_peak_bytes
            .checked_sub(projection.runtime_reserve_bytes)
            .filter(|value| *value > 0)
            .ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "certified launch resource projection has no training mechanism budget",
                )
            })?;
        (
            model.simulated_peak_commit_bytes,
            model.maximum_job_memory_bytes,
            model.required_available_maximum_commit_bytes,
            json!([
                {"kind": "training_data_loader", "maximum_bytes": training_mechanism_bytes},
                {"kind": "checkpoint_writer", "maximum_bytes": checkpoint_bytes},
                {"kind": "telemetry_buffer", "maximum_bytes": projection.runtime_reserve_bytes}
            ]),
            json!({
                "route": "non_a1_device_resident",
                "producer": {
                    "path": &resource_projection_producer,
                    "sha256": hash_file(&resource_projection_producer)?,
                },
                "config": {
                    "path": &resource_projection_config,
                    "sha256": hash_file(&resource_projection_config)?,
                },
                "mechanism": "device_resident_training",
                "mechanism_authority": "tools/ember-restart-3b/launch_packet.py::preflight_resource",
                "projection_kind": "host_commit_projection_from_device_resident_mechanism_plus_transient_checkpoint",
                "zero_overshoot_allowance": true,
                "total_parameters": projection.total_parameters,
                "active_parameters": projection.active_parameters,
                "parameter_bytes_all": projection.parameter_bytes_all,
                "gradient_bytes_active": projection.gradient_bytes_active,
                "optimizer_state_bytes_active": projection.optimizer_state_bytes_active,
                "activation_reserve_bytes": projection.activation_reserve_bytes,
                "runtime_reserve_bytes": projection.runtime_reserve_bytes,
                "mechanism_peak_bytes": projection.mechanism_peak_bytes,
                "transient_checkpoint_bytes": checkpoint_bytes,
                "checkpoint_publication_host_commit_reserve_bytes": projection.checkpoint_publication_host_commit_reserve_bytes,
                "checkpoint_publication_reserve_role": "writer_staging_headroom_enforced_at_checkpoint_publication",
                "daemon_host_survival_reserve_bytes": HOST_COMMIT_SURVIVAL_RESERVE_BYTES,
                "daemon_host_survival_reserve_role": "headroom_outside_the_job_maximum_for_windows_and_ember_lab_survival"
            }),
        )
    } else {
        let telemetry_bytes = 4 * GIB;
        let loader_bytes = gpu_vram_bytes.checked_mul(4).ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch A1 host-memory model overflow",
            )
        })?;
        let simulated = loader_bytes
            .checked_add(checkpoint_bytes)
            .and_then(|value| value.checked_add(telemetry_bytes))
            .ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "certified launch A1 host-memory model overflow",
                )
            })?;
        let maximum = simulated
            .checked_add(CERTIFIED_LAUNCH_OVERSHOOT_MARGIN_BYTES)
            .ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "certified launch A1 job-memory model overflow",
                )
            })?;
        let reserve = required_gib(execution_scope, "a1_host_commit_reserve_gib")?
            .max(HOST_COMMIT_SURVIVAL_RESERVE_BYTES);
        let required = maximum.checked_add(reserve).ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "certified launch A1 host-commit model overflow",
            )
        })?;
        (
            simulated,
            maximum,
            required,
            json!([
                {"kind": "training_data_loader", "maximum_bytes": loader_bytes},
                {"kind": "checkpoint_writer", "maximum_bytes": checkpoint_bytes},
                {"kind": "telemetry_buffer", "maximum_bytes": telemetry_bytes}
            ]),
            json!({
                "route": "a1_declared_mechanism",
                "mechanism": "a1_cpu_offload",
                "overshoot_allowance_bytes": CERTIFIED_LAUNCH_OVERSHOOT_MARGIN_BYTES,
                "daemon_host_survival_reserve_bytes": reserve
            }),
        )
    };
    let write_budget_bytes = if is_job_memory_probe {
        0
    } else {
        required_u64(requested_scope, "write_budget_bytes")?
    };
    let storage_floor_bytes = if is_job_memory_probe {
        CERTIFIED_LAUNCH_PROBE_STORAGE_RESERVE_BYTES
    } else if is_a1_route {
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
    let mut binding_inputs = vec![
        ("config", validator.as_path()),
        ("config", readme.as_path()),
        ("config", certificate_path),
        ("input", declaration_ledger_path),
        ("manifest", run_spec_path),
        ("input", custody_receipt.as_path()),
    ];
    if !is_a1_route && !is_job_memory_probe {
        binding_inputs.push(("config", resource_projection_producer.as_path()));
        binding_inputs.push(("config", resource_projection_config.as_path()));
    }
    let bindings = binding_inputs
        .into_iter()
        .map(
            |(kind, path)| -> Result<Value, Box<dyn std::error::Error>> {
                Ok(json!({"kind": kind, "path": path, "sha256": hash_file(path)?}))
            },
        )
        .collect::<Result<Vec<_>, _>>()?;
    let manifest = json!({
        "schema_version": "ember-lab-dispatch-manifest-v4",
        "job_id": job_id,
        "source_commit": source_commit,
        "not_before_ms": now_ms,
        "expires_at_ms": now_ms + 3_600_000,
        "resource_lease": if is_job_memory_probe {
            format!("host-memory:{job_id}")
        } else {
            format!("gpu:{job_id}")
        },
        "program": {"path": python_executable, "sha256": hash_file(python_executable)?},
        "args": [
            "-c",
            CERTIFIED_LAUNCH_PYTHON_TRAMPOLINE,
            validator.to_string_lossy(),
            root.to_string_lossy(),
            validator.parent().expect("certified validator has a parent").to_string_lossy(),
            "--root", root.to_string_lossy(),
            "--certificate", certificate_path.to_string_lossy(),
            "--declaration-ledger", declaration_ledger_path.to_string_lossy(),
            "--run-spec", run_spec_path.to_string_lossy(),
            "--custody-receipt-sha256", custody_receipt_sha256
        ],
        "workload_profile": {
            "profile_id": if is_job_memory_probe {
                "job_memory_ceiling_probe"
            } else {
                "governed_vertical"
            },
            "pinned_host_producers": pinned_host_producers,
            "requires_ui_responsiveness": false,
            "cpu_rate_percent": 90
        },
        "memory_model_authority": memory_model_authority,
        "cpu_pacing_class": "unpaced",
        "window_contract": "headless_no_windows",
        "env": env,
        "bindings": bindings,
        "custody_root": &canonical_run_custody_root,
        "storage_reserves": [{"root": requested_custody_root, "minimum_free_bytes": storage_floor_bytes}],
        "vram_wall": vram_wall,
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
        terminal_contract,
    })
}

fn prepare_cockpit_launch(
    cli: &CockpitCliArgs,
    now_ms: i64,
) -> Result<(PreparedCertifiedLaunch, CertifiedLaunchDaemonDefaults), Box<dyn std::error::Error>> {
    prepare_cockpit_launch_with(cli, now_ms, probe_single_vram_device_capacity()?)
}

fn prepare_cockpit_launch_with(
    cli: &CockpitCliArgs,
    now_ms: i64,
    vram_capacity: VramDeviceCapacity,
) -> Result<(PreparedCertifiedLaunch, CertifiedLaunchDaemonDefaults), Box<dyn std::error::Error>> {
    if cli.source_commit.len() != 40
        || !cli
            .source_commit
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "cockpit source commit must be exact lowercase Git identity",
        )
        .into());
    }
    let root = std::fs::canonicalize(&cli.root)?;
    let application = std::fs::canonicalize(&cli.application)?;
    if !application.is_file() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "cockpit application is not a file",
        )
        .into());
    }
    std::fs::create_dir_all(&cli.state_root)?;
    let state_root = std::fs::canonicalize(&cli.state_root)?;
    let job_id = format!("cockpit-{}-{}", now_ms, std::process::id());
    let custody_root = state_root.join("cockpit-launches").join(&job_id);
    std::fs::create_dir_all(&custody_root)?;
    let custody_root = std::fs::canonicalize(custody_root)?;
    let daemon = certified_launch_daemon_defaults(&state_root, cli.db.clone(), cli.pipe.clone())?;
    let application_sha256 = hash_file(&application)?;
    let config_path = custody_root.join("cockpit-config.json");
    let authority_path = custody_root.join("cockpit-authority.json");
    std::fs::write(
        &config_path,
        serde_json::to_vec_pretty(&json!({
            "schema_version":"ember-cockpit-dispatch-config-v1",
            "source_root":root,
            "state_root":state_root,
            "requires_ui_responsiveness":true,
            "window_contract":"cockpit_hosted"
        }))?,
    )?;
    std::fs::write(
        &authority_path,
        serde_json::to_vec_pretty(&json!({
            "schema_version":"ember-cockpit-launch-authority-v1",
            "source_commit":cli.source_commit,
            "application":{"path":application,"sha256":application_sha256}
        }))?,
    )?;
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
        let directory = custody_root.join(key.to_ascii_lowercase());
        std::fs::create_dir(&directory)?;
        env.insert(key.to_string(), directory.to_string_lossy().into_owned());
    }
    env.insert(
        "EMBER_SOURCE_ROOT".into(),
        root.to_string_lossy().into_owned(),
    );
    env.insert(
        "EMBER_STATE_ROOT".into(),
        state_root.to_string_lossy().into_owned(),
    );
    env.insert("EMBER_GPU_FREE".into(), "1".into());
    let receipt_path = cli
        .receipt
        .clone()
        .unwrap_or_else(|| custody_root.join("cockpit-operational.json"));
    let preflight_receipt = custody_root.join("cockpit-preflight.json");
    let telemetry_bytes = 512 * 1024 * 1024_u64;
    let maximum_job_memory_bytes = GIB;
    let vram_wall = certified_launch_vram_wall(GIB, vram_capacity)?;
    let manifest = json!({
        "schema_version":"ember-lab-dispatch-manifest-v4",
        "job_id":job_id,
        "source_commit":cli.source_commit,
        "not_before_ms":now_ms,
        "expires_at_ms":now_ms + 3_600_000,
        "resource_lease":format!("cockpit:{job_id}"),
        "program":{"path":application,"sha256":application_sha256},
        "args":[],
        "workload_profile":{
            "profile_id":"cockpit",
            "pinned_host_producers":[{"kind":"telemetry_buffer","maximum_bytes":telemetry_bytes}],
            "requires_ui_responsiveness":true,
            "cpu_rate_percent":90
        },
        "cpu_pacing_class":"governed",
        "window_contract":"cockpit_hosted",
        "env":env,
        "bindings":[
            {"kind":"config","path":config_path,"sha256":hash_file(&config_path)?},
            {"kind":"manifest","path":authority_path,"sha256":hash_file(&authority_path)?}
        ],
        "custody_root":custody_root,
        "storage_reserves":[{"root":state_root,"minimum_free_bytes":64 * 1024 * 1024_u64}],
        "vram_wall":vram_wall,
        "required_available_maximum_commit_bytes":maximum_job_memory_bytes + HOST_COMMIT_SURVIVAL_RESERVE_BYTES,
        "maximum_job_memory_bytes":maximum_job_memory_bytes,
        "simulated_peak_commit_bytes":telemetry_bytes,
        "preflight_receipt":preflight_receipt
    });
    let manifest_path = custody_root.join("dispatch-manifest.json");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&manifest_path)?;
    file.write_all(&serde_json::to_vec_pretty(&manifest)?)?;
    file.sync_all()?;
    Ok((
        PreparedCertifiedLaunch {
            manifest_path,
            job_id,
            receipt_path,
            run_custody_root: custody_root,
            terminal_contract: CertifiedLaunchTerminalContract::None,
        },
        daemon,
    ))
}

fn usage() -> &'static str {
    "usage:\n  ember-lab serve --db <path> --pipe <\\\\.\\pipe\\name>\n  ember-lab dispatch --pipe <\\\\.\\pipe\\name> --manifest <path>\n  ember-lab launch --root <path> --certificate <path> --declaration-ledger <path> --run-spec <path> --custody-receipt-sha256 <hex> [--receipt <path>] [--db <path>] [--pipe <\\\\.\\pipe\\name>]\n  ember-lab storage-reconcile --pipe <\\\\.\\pipe\\name> --repository-root <path> --policy <path> --declarations <path> --models-root <path> --state-root <path> --custody <path> --pin-set-sha256 <hex> --current-master <sha> --projected-models-bytes <n> --projected-state-bytes <n> --mode <dry-run|execute>\n  ember-lab resource-guard-rearm --pipe <\\\\.\\pipe\\name> --frozen-observation-sha256 <hex> --breach-class <class> --diagnostic-receipt <path> --diagnostic-receipt-sha256 <hex>\n  ember-lab data-catalog-status --db <path>\n  ember-lab data-catalog-import --db <path> --manifest <path> --receipt <path> --export <path> --source-commit <lowercase-40-hex>\n  ember-lab register-artifact --db <path> --sha256 <hex> --byte-count <n> --media-type <type> --location <volume>=<locator> [--location <volume>=<locator> ...]\n  ember-lab retire-artifact-location --db <path> --sha256 <hex> --volume <volume> --locator <locator> --reason <text>\n  ember-lab custody-verify --db <path> --hash <sha256> [--hash <sha256> ...] --root <volume>=<path> [--root <volume>=<path> ...] --receipt <path> [--rehash]\n  ember-lab produce-minimal-slice --root <path> --job-id <id>\n  ember-lab verify-training --root <path> --receipt <path> [--certificate <path>]\n  ember-lab rehearse --db <path> --dispatch-manifest <path> --manifest <path> --receipt <path>\n  ember-lab episode --capability <name> --db <path> --dispatch-manifest <path> --manifest <path> --receipt <path>\n  ember-lab runbook --output <path>"
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
    Cockpit(CockpitCliArgs),
    StorageReconcile(StorageRetentionCliArgs),
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
    DataCatalogImport {
        db: PathBuf,
        manifest: PathBuf,
        receipt: PathBuf,
        export: PathBuf,
        source_commit: String,
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
        receipt,
    }))
}

fn parse_cockpit_arguments<I>(mut args: I) -> Result<Command, String>
where
    I: Iterator<Item = String>,
{
    let mut root = None;
    let mut application = None;
    let mut source_commit = None;
    let mut state_root = None;
    let mut db = None;
    let mut pipe = None;
    let mut receipt = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        match flag.as_str() {
            "--root" => root = Some(PathBuf::from(value)),
            "--application" => application = Some(PathBuf::from(value)),
            "--source-commit" => source_commit = Some(value),
            "--state-root" => state_root = Some(PathBuf::from(value)),
            "--db" => db = Some(PathBuf::from(value)),
            "--pipe" => pipe = Some(value),
            "--receipt" => receipt = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument {flag}\n{}", usage())),
        }
    }
    Ok(Command::Cockpit(CockpitCliArgs {
        root: root.ok_or_else(|| format!("missing --root\n{}", usage()))?,
        application: application.ok_or_else(|| format!("missing --application\n{}", usage()))?,
        source_commit: source_commit
            .ok_or_else(|| format!("missing --source-commit\n{}", usage()))?,
        state_root: state_root.ok_or_else(|| format!("missing --state-root\n{}", usage()))?,
        db,
        pipe,
        receipt,
    }))
}

fn parse_storage_retention_arguments<I>(mut args: I) -> Result<Command, String>
where
    I: Iterator<Item = String>,
{
    let mut policy = None;
    let mut pipe = None;
    let mut repository_root = None;
    let mut declarations = None;
    let mut models_root = None;
    let mut state_root = None;
    let mut custody = None;
    let mut pin_set_sha256 = None;
    let mut current_master = None;
    let mut projected_models_bytes = None;
    let mut projected_state_bytes = None;
    let mut operation = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        match flag.as_str() {
            "--pipe" => pipe = Some(value),
            "--repository-root" => repository_root = Some(PathBuf::from(value)),
            "--policy" => policy = Some(PathBuf::from(value)),
            "--declarations" => declarations = Some(PathBuf::from(value)),
            "--models-root" => models_root = Some(PathBuf::from(value)),
            "--state-root" => state_root = Some(PathBuf::from(value)),
            "--custody" => custody = Some(PathBuf::from(value)),
            "--pin-set-sha256" => pin_set_sha256 = Some(value),
            "--current-master" => current_master = Some(value),
            "--projected-models-bytes" => {
                projected_models_bytes = Some(value.parse::<u64>().map_err(|_| {
                    format!("invalid --projected-models-bytes {value:?}\n{}", usage())
                })?)
            }
            "--projected-state-bytes" => {
                projected_state_bytes = Some(value.parse::<u64>().map_err(|_| {
                    format!("invalid --projected-state-bytes {value:?}\n{}", usage())
                })?)
            }
            "--mode" => {
                operation = Some(match value.as_str() {
                    "dry-run" => StorageRetentionOperation::DryRun,
                    "commit" => StorageRetentionOperation::Commit,
                    "resume" => StorageRetentionOperation::Resume,
                    "rollback" => StorageRetentionOperation::Rollback,
                    _ => {
                        return Err(format!(
                            "unknown storage reconciliation mode {value}\n{}",
                            usage()
                        ))
                    }
                })
            }
            _ => return Err(format!("unknown argument {flag}\n{}", usage())),
        }
    }
    Ok(Command::StorageReconcile(StorageRetentionCliArgs {
        pipe: pipe.ok_or_else(|| format!("missing --pipe\n{}", usage()))?,
        repository_root: repository_root
            .ok_or_else(|| format!("missing --repository-root\n{}", usage()))?,
        policy: policy.ok_or_else(|| format!("missing --policy\n{}", usage()))?,
        declarations: declarations.ok_or_else(|| format!("missing --declarations\n{}", usage()))?,
        models_root: models_root.ok_or_else(|| format!("missing --models-root\n{}", usage()))?,
        state_root: state_root.ok_or_else(|| format!("missing --state-root\n{}", usage()))?,
        custody: custody.ok_or_else(|| format!("missing --custody\n{}", usage()))?,
        pin_set_sha256: pin_set_sha256
            .ok_or_else(|| format!("missing --pin-set-sha256\n{}", usage()))?,
        current_master: current_master
            .ok_or_else(|| format!("missing --current-master\n{}", usage()))?,
        projected_models_bytes: projected_models_bytes
            .ok_or_else(|| format!("missing --projected-models-bytes\n{}", usage()))?,
        projected_state_bytes: projected_state_bytes
            .ok_or_else(|| format!("missing --projected-state-bytes\n{}", usage()))?,
        operation: operation.ok_or_else(|| format!("missing --mode\n{}", usage()))?,
    }))
}

fn parse_args() -> Result<Command, String> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or_else(|| usage().to_string())?;

    if command == "launch" {
        return parse_launch_arguments(args);
    }
    if command == "cockpit" {
        return parse_cockpit_arguments(args);
    }
    if command == "storage-reconcile" {
        return parse_storage_retention_arguments(args);
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

    if command == "data-catalog-import" {
        let mut db = None;
        let mut manifest = None;
        let mut receipt = None;
        let mut export = None;
        let mut source_commit = None;
        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
            match flag.as_str() {
                "--db" => db = Some(PathBuf::from(value)),
                "--manifest" => manifest = Some(PathBuf::from(value)),
                "--receipt" => receipt = Some(PathBuf::from(value)),
                "--export" => export = Some(PathBuf::from(value)),
                "--source-commit" => source_commit = Some(value),
                _ => return Err(format!("unknown argument {flag}\n{}", usage())),
            }
        }
        let source_commit = source_commit
            .filter(|value| {
                value.len() == 40
                    && value
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            .ok_or_else(|| {
                format!(
                    "--source-commit must be a lowercase 40-hex SHA\n{}",
                    usage()
                )
            })?;
        return Ok(Command::DataCatalogImport {
            db: db.ok_or_else(|| format!("missing --db\n{}", usage()))?,
            manifest: manifest.ok_or_else(|| format!("missing --manifest\n{}", usage()))?,
            receipt: receipt.ok_or_else(|| format!("missing --receipt\n{}", usage()))?,
            export: export.ok_or_else(|| format!("missing --export\n{}", usage()))?,
            source_commit,
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

fn import_data_catalog_with_receipt(
    db: &Path,
    manifest: &Path,
    receipt: &Path,
    export: &Path,
    source_commit: &str,
) -> Result<Value, Box<dyn std::error::Error>> {
    let mut receipt_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(receipt)?;
    let mut export_file = match OpenOptions::new().write(true).create_new(true).open(export) {
        Ok(file) => file,
        Err(error) => {
            drop(receipt_file);
            let _ = std::fs::remove_file(receipt);
            return Err(error.into());
        }
    };
    let attempt = (|| -> Result<Value, Box<dyn std::error::Error>> {
        let input_bytes = std::fs::read(manifest)?;
        let input_manifest_raw_sha256 = format!("{:x}", Sha256::digest(&input_bytes));
        let daemon = Daemon::open(db)?;
        let outcome = daemon.import_data_catalog_manifest(&input_bytes)?;
        let canonical_export = daemon.export_data_catalog_manifest()?;
        export_file.write_all(&canonical_export)?;
        export_file.sync_all()?;
        let canonical_export_sha256 = hash_file(export)?;
        let binary_sha256 = hash_file(&std::env::current_exe()?)?;
        let mut payload = json!({
            "schema_version": "ember-data-catalog-import-receipt-v1",
            "result": "PASS",
            "source_commit": source_commit,
            "ember_lab_source_sha256": ember_lab_source_hash(),
            "ember_lab_binary_sha256": binary_sha256,
            "input_manifest_raw_sha256": input_manifest_raw_sha256,
            "canonical_manifest_sha256": outcome.manifest_sha256,
            "canonical_export_sha256": canonical_export_sha256,
            "inserted_records": outcome.inserted_records,
            "inserted_edges": outcome.inserted_edges,
        });
        let self_sha256 = format!("{:x}", Sha256::digest(serde_json::to_vec(&payload)?));
        payload
            .as_object_mut()
            .expect("catalog import receipt is an object")
            .insert("self_sha256".into(), Value::String(self_sha256));
        receipt_file.write_all(&serde_json::to_vec_pretty(&payload)?)?;
        receipt_file.sync_all()?;
        Ok(payload)
    })();
    if attempt.is_err() {
        drop(receipt_file);
        drop(export_file);
        let _ = std::fs::remove_file(receipt);
        let _ = std::fs::remove_file(export);
    }
    attempt
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
                |start| {
                    println!("{}", serde_json::to_string(start)?);
                    std::io::stdout().flush()?;
                    Ok(())
                },
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
                    "schema_version": "ember-lab-certified-launch-completion-v1",
                    "exit_code": completion.exit_code,
                    "operational_receipt": receipt
                }))?
            );
            if completion.exit_code != 0 {
                std::process::exit(completion.exit_code);
            }
        }
        Command::Cockpit(cli) => {
            let now_ms = i64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
            let (prepared, daemon_defaults) = prepare_cockpit_launch(&cli, now_ms)?;
            let receipt = prepared.receipt_path.clone();
            let log_root = prepared.manifest_path.parent().ok_or_else(|| {
                std::io::Error::other("cockpit dispatch manifest lacks a custody parent")
            })?;
            let mut daemon = ensure_launch_daemon(&daemon_defaults, log_root)?;
            let attempt = launch_prepared_certified_with(
                &prepared,
                daemon.mode,
                daemon.pid,
                |rpc_request| call_rpc(&daemon_defaults.pipe, rpc_request, "cockpit"),
                |start| {
                    #[cfg(windows)]
                    if let Err(error) = place_cockpit_window_left(start.governed_pid) {
                        eprintln!(
                            "WARNING: cockpit window placement was not applied for governed PID {}: {error}",
                            start.governed_pid
                        );
                    }
                    println!("{}", serde_json::to_string(start)?);
                    std::io::stdout().flush()?;
                    Ok(())
                },
                || std::thread::sleep(Duration::from_millis(100)),
            );
            let shutdown = shutdown_owned_launch_daemon(&daemon_defaults.pipe, &mut daemon);
            let completion = match (attempt, shutdown) {
                (Ok(completion), Ok(())) => completion,
                (Err(error), Ok(())) => return Err(error),
                (Ok(_), Err(error)) => return Err(error),
                (Err(operation), Err(cleanup)) => {
                    return Err(std::io::Error::other(format!(
                        "cockpit launch failed: {operation}; owned daemon cleanup also failed: {cleanup}"
                    )).into())
                }
            };
            if !completion.stderr.is_empty() {
                eprint!("{}", completion.stderr);
                std::io::stderr().flush()?;
            }
            println!(
                "{}",
                serde_json::to_string(&json!({
                    "schema_version":"ember-lab-certified-launch-completion-v1",
                    "exit_code":completion.exit_code,
                    "operational_receipt":receipt
                }))?
            );
            if completion.exit_code != 0 {
                std::process::exit(completion.exit_code);
            }
        }
        Command::StorageReconcile(cli) => {
            let operation = match cli.operation {
                StorageRetentionOperation::DryRun => "dry-run",
                StorageRetentionOperation::Commit => "commit",
                StorageRetentionOperation::Resume => "resume",
                StorageRetentionOperation::Rollback => "rollback",
            };
            let result = call_rpc(
                &cli.pipe,
                &json!({
                    "jsonrpc":"2.0",
                    "id":1,
                    "method":"storage_reconcile",
                    "params":{
                        "repository_root":cli.repository_root,
                        "policy":cli.policy,
                        "declarations":cli.declarations,
                        "models_root":cli.models_root,
                        "state_root":cli.state_root,
                        "custody":cli.custody,
                    "pin_set_sha256":cli.pin_set_sha256,
                    "current_master":cli.current_master,
                    "projected_growth":{
                        "models":cli.projected_models_bytes,
                        "state":cli.projected_state_bytes
                    },
                    "operation":operation,
                    }
                }),
                "storage-reconcile",
            )?;
            println!("{}", serde_json::to_string(&result)?);
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
        Command::DataCatalogImport {
            db,
            manifest,
            receipt,
            export,
            source_commit,
        } => {
            let payload = import_data_catalog_with_receipt(
                &db,
                &manifest,
                &receipt,
                &export,
                &source_commit,
            )?;
            println!("{}", serde_json::to_string(&payload)?);
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
                // Mirrors src/ember/governance/scripts/training_closure.py's own CLI convention: a completed-but-
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
    use ember_lab::storage_retention::{CensusDeclaration, CustodyClass};
    use ember_lab::{JobSpec, ReceiptArtifact};
    use std::fs;

    fn fixture_probe_execution_scope() -> Value {
        json!({
            "purpose": "BOUNDED_CANARY",
            "allowed_modes": ["governed-vertical"],
            "max_optimizer_steps": 0,
            "max_records": 0,
            "max_active_expert_families": 0,
            "max_gpu_vram_gib": 0,
            "max_transient_checkpoint_gib": 0,
            "max_wall_minutes": 5,
            "max_b_write_gib": 0,
            "max_c_write_gib": 0,
            "max_write_budget_bytes": 0,
            "allowed_artifact_roots": ["B:/probe-artifacts"],
            "allowed_custody_roots": ["B:/probe-custody"],
            "model_server_allowed": false,
            "wsl_allowed": false,
            "persistent_worker_allowed": false,
            "allowed_job_memory_ceiling_probe": {
                "maximum_job_memory_bytes": 100,
                "maximum_absolute_delta_bytes": 20
            }
        })
    }

    fn fixture_probe_run_spec(signed_delta_bytes: i64) -> Value {
        json!({
            "schema_version": "ember-certified-train-run-v1",
            "certificate_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "run_id": "issue898-probe",
            "seed": 1,
            "runner_receipt": "B:/probe-receipt.json",
            "requested_scope": {
                "mode": "governed-vertical",
                "optimizer_steps": 0,
                "max_records": 0,
                "active_expert_families": 0,
                "gpu_vram_gib": 0,
                "transient_checkpoint_gib": 0,
                "wall_minutes": 5,
                "max_b_write_gib": 0,
                "max_c_write_gib": 0,
                "write_budget_bytes": 0,
                "artifact_root": "B:/probe-artifacts",
                "custody_root": "B:/probe-custody"
            },
            "job_memory_ceiling_probe": {
                "maximum_job_memory_bytes": 100,
                "signed_delta_bytes": signed_delta_bytes
            }
        })
    }

    #[test]
    fn job_memory_probe_composer_requires_the_exact_independent_signed_pair() {
        let certificate = fixture_probe_execution_scope();
        let positive = fixture_probe_run_spec(10);
        let parsed = parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            positive.as_object().unwrap(),
            "governed-vertical",
        )
        .unwrap()
        .unwrap();
        assert_eq!(parsed.allocation_target_bytes, 110);

        let negative = fixture_probe_run_spec(-10);
        assert_eq!(
            parse_job_memory_ceiling_probe_authority(
                certificate.as_object().unwrap(),
                negative.as_object().unwrap(),
                "governed-vertical",
            )
            .unwrap()
            .unwrap()
            .allocation_target_bytes,
            90
        );

        assert!(parse_job_memory_ceiling_probe_authority(
            &serde_json::Map::new(),
            positive.as_object().unwrap(),
            "governed-vertical",
        )
        .is_err());
        let overbound = fixture_probe_run_spec(21);
        assert!(parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            overbound.as_object().unwrap(),
            "governed-vertical",
        )
        .is_err());
    }

    #[test]
    fn job_memory_probe_rejects_unknown_run_and_certificate_scope_keys() {
        let certificate = fixture_probe_execution_scope();
        let mut run_spec = fixture_probe_run_spec(-10);
        run_spec
            .as_object_mut()
            .unwrap()
            .insert("unrecognized_probe_key".into(), Value::Bool(true));
        let error = parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            run_spec.as_object().unwrap(),
            "governed-vertical",
        )
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "job-memory ceiling probe run spec has unexpected key `unrecognized_probe_key`"
        );

        let mut certificate = fixture_probe_execution_scope();
        certificate
            .as_object_mut()
            .unwrap()
            .insert("unrecognized_probe_key".into(), Value::Bool(true));
        let run_spec = fixture_probe_run_spec(-10);
        let error = parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            run_spec.as_object().unwrap(),
            "governed-vertical",
        )
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "job-memory ceiling probe certificate scope has unexpected key `unrecognized_probe_key`"
        );

        let certificate = fixture_probe_execution_scope();
        let mut run_spec = fixture_probe_run_spec(-10);
        run_spec["requested_scope"]
            .as_object_mut()
            .unwrap()
            .insert("unrecognized_probe_key".into(), Value::Bool(true));
        let error = parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            run_spec.as_object().unwrap(),
            "governed-vertical",
        )
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "job-memory ceiling probe requested scope has unexpected key `unrecognized_probe_key`"
        );
    }

    #[test]
    fn job_memory_probe_rejects_nonzero_training_scope() {
        let certificate = fixture_probe_execution_scope();
        let mut run_spec = fixture_probe_run_spec(-10);
        run_spec["requested_scope"]["optimizer_steps"] = Value::from(1);
        assert!(parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            run_spec.as_object().unwrap(),
            "governed-vertical",
        )
        .is_err());

        let mut certificate = fixture_probe_execution_scope();
        certificate["max_optimizer_steps"] = Value::from(1);
        let run_spec = fixture_probe_run_spec(-10);
        assert!(parse_job_memory_ceiling_probe_authority(
            certificate.as_object().unwrap(),
            run_spec.as_object().unwrap(),
            "governed-vertical",
        )
        .is_err());
    }

    fn fixture_resource_projection() -> ResourceMechanismProjection {
        parse_resource_projection(
            br#"{"schema_version":"ember-issue898-resource-projection-v1","authority":"tools/ember-restart-3b/launch_packet.py::preflight_resource","total_parameters":3839161856,"active_parameters":1725232640,"parameter_bytes_all":7678323712,"gradient_bytes_active":3450465280,"optimizer_state_bytes_active":3450465280,"activation_reserve_bytes":4294967296,"runtime_reserve_bytes":2147483648,"mechanism_peak_bytes":21021705216,"checkpoint_publication_host_commit_reserve_bytes":8589934592}"#,
        )
        .unwrap()
    }

    fn fixture_vram_capacity() -> VramDeviceCapacity {
        VramDeviceCapacity {
            provider: "nvidia_smi_nvml".into(),
            device_uuid: "GPU-certified-launch-fixture".into(),
            total_bytes: 24 * GIB,
            free_bytes: 23 * GIB,
        }
    }

    #[test]
    fn non_a1_host_commit_model_consumes_the_producer_projection_without_overshoot() {
        let projection = fixture_resource_projection();
        let model = non_a1_host_commit_model(&projection, 8 * GIB).unwrap();

        assert_eq!(model.simulated_peak_commit_bytes, 29_611_639_808);
        assert_eq!(
            model.maximum_job_memory_bytes,
            model.simulated_peak_commit_bytes
        );
        assert_eq!(
            model.required_available_maximum_commit_bytes,
            model.maximum_job_memory_bytes + 10 * GIB
        );
        assert_eq!(
            projection.checkpoint_publication_host_commit_reserve_bytes,
            8 * GIB
        );
    }

    #[test]
    fn certified_launch_derives_required_vram_wall_and_refuses_a_smaller_device() {
        let wall = certified_launch_vram_wall(20 * GIB, fixture_vram_capacity()).unwrap();
        let DispatchVramWall::Required(contract) = wall else {
            panic!("certified launch did not require a VRAM wall");
        };
        assert_eq!(contract.device_uuid, "GPU-certified-launch-fixture");
        assert_eq!(contract.maximum_process_fraction_millionths, 833_333);
        assert_eq!(
            contract.minimum_free_bytes,
            CERTIFIED_LAUNCH_VRAM_HEADROOM_RESERVE_BYTES
        );
        assert_eq!(contract.consecutive_breach_samples, 3);
        assert_eq!(contract.sample_interval_ms, 2_000);

        let mut smaller = fixture_vram_capacity();
        smaller.total_bytes = 16 * GIB;
        smaller.free_bytes = 15 * GIB;
        let refusal = certified_launch_vram_wall(20 * GIB, smaller).unwrap_err();
        assert!(refusal.to_string().contains("measured device capacity"));
    }

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
        std::fs::create_dir_all(repo.join("runtime/ember-lab")).unwrap();
        std::fs::create_dir_all(repo.join("configs")).unwrap();
        std::fs::create_dir_all(&packet).unwrap();
        std::fs::write(repo.join("README.md"), b"bound root").unwrap();
        let validator = repo.join("src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py");
        std::fs::write(&validator, b"print('validator')\n").unwrap();
        let resource_projection_producer =
            repo.join("runtime/ember-lab/issue898_resource_projection.py");
        std::fs::write(&resource_projection_producer, b"# projection fixture\n").unwrap();
        let resource_projection_config = repo.join("configs/ember-restart-3b.json");
        std::fs::write(&resource_projection_config, b"{}\n").unwrap();
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
                "runner_receipt": root.join("custody/run-1/runner-receipt.json"),
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
                receipt: Some(receipt.clone()),
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
                receipt: Some(receipt.clone()),
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
        let provider_refusal = match prepare_certified_launch_with(
            &request,
            |_| Ok(fixture_resource_projection()),
            |_| {
                Err(std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "nvidia-smi program not found",
                )
                .into())
            },
        ) {
            Ok(_) => panic!("certified launch accepted an unavailable VRAM provider"),
            Err(error) => error.to_string(),
        };
        assert!(provider_refusal.contains("certified launch requires the nvidia-smi VRAM provider"));
        assert!(provider_refusal.contains("measure and enforce its required VRAM wall"));
        assert!(provider_refusal.contains("program not found"));

        let prepared = prepare_certified_launch_with(
            &request,
            |_| Ok(fixture_resource_projection()),
            |_| Ok(fixture_vram_capacity()),
        )
        .unwrap();
        let manifest: Value =
            serde_json::from_slice(&std::fs::read(&prepared.manifest_path).unwrap()).unwrap();
        let parsed_manifest: DispatchManifest = serde_json::from_value(manifest.clone()).unwrap();
        let authority = parsed_manifest.memory_model_authority.unwrap();
        match authority {
            ember_lab::DispatchMemoryModelAuthority::NonA1DeviceResident(authority) => {
                let ember_lab::DispatchNonA1MemoryModelAuthority {
                    producer,
                    config,
                    mechanism,
                    total_parameters,
                    active_parameters,
                    mechanism_peak_bytes,
                    zero_overshoot_allowance,
                    ..
                } = *authority;
                assert_eq!(producer.path, resource_projection_producer);
                assert_eq!(producer.sha256, hash_file(&producer.path).unwrap());
                assert_eq!(config.path, resource_projection_config);
                assert_eq!(config.sha256, hash_file(&config.path).unwrap());
                assert!(matches!(
                    mechanism,
                    ember_lab::DispatchMemoryMechanism::DeviceResidentTraining
                ));
                assert_eq!(total_parameters, 3_839_161_856);
                assert_eq!(active_parameters, 1_725_232_640);
                assert_eq!(mechanism_peak_bytes, 21_021_705_216);
                assert!(zero_overshoot_allowance);
            }
            _ => panic!("non-A1 certified launch parsed the wrong memory authority route"),
        }
        assert_eq!(manifest["schema_version"], "ember-lab-dispatch-manifest-v4");
        assert_eq!(
            manifest["source_commit"],
            "0123456789abcdef0123456789abcdef01234567"
        );
        assert_eq!(
            manifest["program"]["path"],
            python.to_string_lossy().as_ref()
        );
        assert_eq!(manifest["program"]["sha256"], hash_file(&python).unwrap());
        assert_eq!(manifest["args"][0], "-c");
        assert_eq!(manifest["args"][1], CERTIFIED_LAUNCH_PYTHON_TRAMPOLINE);
        assert_eq!(manifest["args"][2], validator.to_string_lossy().as_ref());
        assert_eq!(manifest["args"][3], repo.to_string_lossy().as_ref());
        assert_eq!(
            manifest["args"][4],
            repo.join("tools/ember-restart-3b")
                .to_string_lossy()
                .as_ref()
        );
        assert_eq!(manifest["args"][5], "--root");
        assert_eq!(manifest["args"][7], "--certificate");
        assert_eq!(manifest["args"][9], "--declaration-ledger");
        assert_eq!(manifest["args"][11], "--run-spec");
        assert_eq!(manifest["args"][13], "--custody-receipt-sha256");
        assert_eq!(manifest["args"][14], custody_sha256);
        assert_eq!(
            manifest["workload_profile"]["profile_id"],
            "governed_vertical"
        );
        assert_eq!(manifest["simulated_peak_commit_bytes"], 29_611_639_808_u64);
        assert_eq!(manifest["maximum_job_memory_bytes"], 29_611_639_808_u64);
        assert_eq!(
            manifest["required_available_maximum_commit_bytes"],
            40_349_058_048_u64
        );
        assert_eq!(manifest["vram_wall"]["applicability"], "required");
        assert_eq!(
            manifest["vram_wall"]["contract"]["device_uuid"],
            "GPU-certified-launch-fixture"
        );
        assert_eq!(
            manifest["vram_wall"]["contract"]["maximum_process_fraction_millionths"],
            833_333
        );
        assert_eq!(
            manifest["vram_wall"]["contract"]["minimum_free_bytes"],
            CERTIFIED_LAUNCH_VRAM_HEADROOM_RESERVE_BYTES
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
        let CertifiedLaunchTerminalContract::Artifacts(required_terminal_artifacts) =
            &prepared.terminal_contract
        else {
            panic!("governed vertical lacks its artifact contract")
        };
        assert_eq!(
            required_terminal_artifacts,
            &[
                std::fs::canonicalize(root.join("custody/run-1"))
                    .unwrap()
                    .join("runner-receipt.json"),
                std::fs::canonicalize(root.join("custody/run-1"))
                    .unwrap()
                    .join("runner-receipt-certified-launch.json")
            ]
        );
    }

    #[test]
    fn certified_launch_completion_exports_receipt_and_propagates_exact_child_result() {
        let receipt = PathBuf::from(r"B:\custody\certified-launch.json");
        let mut methods = Vec::new();
        let mut state_samples = 0;
        let completion = complete_certified_launch(
            "run-1-launch-1800000000000",
            &receipt,
            &CertifiedLaunchTerminalContract::None,
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
                        "stdout": "",
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
    fn certified_launch_completion_refuses_zero_exit_without_each_declared_artifact() {
        let root = std::env::temp_dir().join(format!(
            "ember-lab-certified-launch-artifact-red-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let operational_receipt = root.join("operational.json");
        let runner_receipt = root.join("runner-receipt.json");
        let execution_receipt = root.join("runner-receipt-certified-launch.json");

        for missing in [&runner_receipt, &execution_receipt] {
            std::fs::write(&runner_receipt, b"{}\n").unwrap();
            std::fs::write(&execution_receipt, b"{}\n").unwrap();
            std::fs::remove_file(missing).unwrap();
            let result = complete_certified_launch(
                "silent-zero-exit",
                &operational_receipt,
                &CertifiedLaunchTerminalContract::Artifacts(vec![
                    runner_receipt.clone(),
                    execution_receipt.clone(),
                ]),
                |request| {
                    Ok(match request["method"].as_str().unwrap() {
                        "job_state" => json!({"state": "exited"}),
                        "job_result" => json!({"exit_code": 0, "stdout": "", "stderr": ""}),
                        "record_launch_artifact_refusal" => json!({"recorded": true}),
                        "export_receipt" => json!({"exported": true}),
                        method => panic!("unexpected method {method}"),
                    })
                },
                || {},
            );
            assert!(
                result
                    .unwrap_err()
                    .to_string()
                    .contains("required terminal artifact"),
                "an exit-zero child with a missing declared artifact false-passed"
            );
        }
        std::fs::write(&runner_receipt, b"{}\n").unwrap();
        std::fs::write(&execution_receipt, b"{}\n").unwrap();
        let completion = complete_certified_launch(
            "artifact-complete-zero-exit",
            &operational_receipt,
            &CertifiedLaunchTerminalContract::Artifacts(vec![runner_receipt, execution_receipt]),
            |request| {
                Ok(match request["method"].as_str().unwrap() {
                    "job_state" => json!({"state": "exited"}),
                    "job_result" => json!({"exit_code": 0, "stdout": "", "stderr": ""}),
                    "export_receipt" => json!({"exported": true}),
                    method => panic!("unexpected method {method}"),
                })
            },
            || {},
        )
        .unwrap();
        assert_eq!(completion.exit_code, 0);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn certified_launch_probe_refuses_silent_zero_exit_and_consumes_both_schema_records() {
        let receipt = PathBuf::from(r"B:\custody\probe-operational.json");
        let mut refused_methods = Vec::new();
        let refusal = complete_certified_launch(
            "silent-probe",
            &receipt,
            &CertifiedLaunchTerminalContract::JobMemoryProbeStdout,
            |request| {
                let method = request["method"].as_str().unwrap().to_string();
                refused_methods.push(method.clone());
                Ok(match method.as_str() {
                    "job_state" => json!({"state": "exited"}),
                    "job_result" => json!({"exit_code": 0, "stdout": "", "stderr": ""}),
                    "record_launch_artifact_refusal" => json!({"recorded": true}),
                    "export_receipt" => json!({"exported": true}),
                    _ => panic!("unexpected method {method}"),
                })
            },
            || {},
        )
        .unwrap_err();
        assert!(refusal
            .to_string()
            .contains("lacks its ordered allocation records"));
        assert_eq!(
            refused_methods,
            [
                "job_state",
                "job_result",
                "record_launch_artifact_refusal",
                "export_receipt"
            ]
        );

        let probe_stdout = concat!(
            "{\"schema_version\":\"ember-job-memory-ceiling-probe-v1\",\"phase\":\"allocation_start\"}\n",
            "{\"schema_version\":\"ember-job-memory-ceiling-probe-v1\",\"phase\":\"allocation_complete\"}\n",
            "{\"outcome\":\"COMPLETED\",\"execution_receipt\":null,\"exit_code\":0}\n"
        );
        let completion = complete_certified_launch(
            "complete-probe",
            &receipt,
            &CertifiedLaunchTerminalContract::JobMemoryProbeStdout,
            |request| {
                Ok(match request["method"].as_str().unwrap() {
                    "job_state" => json!({"state": "exited"}),
                    "job_result" => {
                        json!({"exit_code": 0, "stdout": probe_stdout, "stderr": ""})
                    }
                    "export_receipt" => json!({"exported": true}),
                    method => panic!("unexpected method {method}"),
                })
            },
            || {},
        )
        .unwrap();
        assert_eq!(completion.exit_code, 0);
    }

    #[test]
    fn certified_launch_start_names_governed_child_after_context_recording() {
        let root =
            std::env::temp_dir().join(format!("ember-lab-streaming-start-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let manifest_path = root.join("dispatch-manifest.json");
        std::fs::write(&manifest_path, b"{}\n").unwrap();
        let prepared = PreparedCertifiedLaunch {
            manifest_path,
            job_id: "run-1-launch-1800000000000".into(),
            receipt_path: root.join("operational.json"),
            run_custody_root: root.clone(),
            terminal_contract: CertifiedLaunchTerminalContract::None,
        };
        let context_recorded = std::rc::Rc::new(std::cell::Cell::new(false));
        let rpc_recorded = context_recorded.clone();
        let start_recorded = context_recorded.clone();

        let completion = launch_prepared_certified_with(
            &prepared,
            "owned_started",
            91,
            move |request| {
                let method = request["method"].as_str().unwrap();
                Ok(match method {
                    "dispatch_manifest" => json!({
                        "pid": 4321,
                        "preflight_receipt_path": r"B:\custody\launch.preflight.json",
                        "preflight_receipt_sha256": "a".repeat(64),
                    }),
                    "record_launch_context" => {
                        rpc_recorded.set(true);
                        json!({"recorded": true})
                    }
                    "job_state" => json!({"state": "exited"}),
                    "job_result" => json!({"exit_code": 0, "stdout": "", "stderr": ""}),
                    "export_receipt" => json!({"exported": true}),
                    _ => panic!("unexpected method {method}"),
                })
            },
            move |evidence| {
                assert!(
                    start_recorded.get(),
                    "start preceded launch-context recording"
                );
                assert_eq!(
                    evidence.schema_version,
                    "ember-lab-certified-launch-start-v1"
                );
                assert_eq!(evidence.job_id, "run-1-launch-1800000000000");
                assert_eq!(evidence.governed_pid, 4321);
                assert_eq!(
                    evidence.preflight_receipt,
                    PathBuf::from(r"B:\custody\launch.preflight.json")
                );
                assert_eq!(evidence.preflight_receipt_sha256, "a".repeat(64));
                Ok(())
            },
            || {},
        )
        .unwrap();

        assert_eq!(completion.exit_code, 0);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cockpit_entry_requires_exact_application_source_and_state_authority() {
        let command = parse_cockpit_arguments(
            [
                "--root",
                "C:\\repo",
                "--application",
                "C:\\app\\Ember.exe",
                "--source-commit",
                "0123456789abcdef0123456789abcdef01234567",
                "--state-root",
                "C:\\state",
            ]
            .into_iter()
            .map(str::to_string),
        )
        .unwrap();
        let Command::Cockpit(cli) = command else {
            panic!("cockpit command not parsed")
        };
        assert_eq!(cli.application, PathBuf::from(r"C:\app\Ember.exe"));
        assert_eq!(
            cli.source_commit,
            "0123456789abcdef0123456789abcdef01234567"
        );
        assert_eq!(cli.state_root, PathBuf::from(r"C:\state"));
    }

    #[test]
    fn cockpit_left_half_placement_uses_monitor_work_area_without_focus_or_z_order_math() {
        assert_eq!(
            left_half_placement(-1920, 40, 0, 1080),
            Some(CockpitPlacement {
                x: -1920,
                y: 40,
                width: 960,
                height: 1040,
            })
        );
        assert_eq!(left_half_placement(0, 0, 1, 1080), None);
    }

    #[test]
    fn cockpit_manifest_is_closed_and_daemon_refuses_caller_owned_identity() {
        let root =
            std::env::temp_dir().join(format!("ember-cockpit-manifest-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let repo = root.join("repo");
        let state = root.join("state");
        std::fs::create_dir_all(&repo).unwrap();
        let application = root.join("Ember.exe");
        std::fs::write(&application, b"fixture application").unwrap();
        let cli = CockpitCliArgs {
            root: repo,
            application,
            source_commit: "0123456789abcdef0123456789abcdef01234567".into(),
            state_root: state,
            db: None,
            pipe: None,
            receipt: None,
        };
        let (prepared, _) = prepare_cockpit_launch_with(
            &cli,
            1_800_000_000_000,
            VramDeviceCapacity {
                provider: "nvidia_smi_nvml".into(),
                device_uuid: "GPU-cockpit-fixture".into(),
                total_bytes: 24 * GIB,
                free_bytes: 20 * GIB,
            },
        )
        .unwrap();
        let mut manifest: Value =
            serde_json::from_slice(&std::fs::read(&prepared.manifest_path).unwrap()).unwrap();
        assert_eq!(manifest["workload_profile"]["profile_id"], "cockpit");
        assert_eq!(manifest["window_contract"], "cockpit_hosted");
        assert_eq!(manifest["cpu_pacing_class"], "governed");
        manifest["env"]["EMBER_LAB_DISPATCH_JOB_OBJECT_NAME"] =
            Value::String("caller-forgery".into());
        let bytes = serde_json::to_vec(&manifest).unwrap();
        let digest = format!("{:x}", Sha256::digest(&bytes));
        let daemon = Daemon::open(&root.join("daemon.sqlite3")).unwrap();
        let error = daemon.dispatch_manifest_bytes(&bytes, &digest).unwrap_err();
        assert!(error.to_string().contains("daemon-owned"), "{error}");
        drop(daemon);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn cockpit_rpc_refuses_when_daemon_is_absent() {
        let pipe = format!(r"\\.\pipe\ember-cockpit-absent-{}", std::process::id());
        let error = call_rpc(
            &pipe,
            &json!({"jsonrpc":"2.0","id":1,"method":"ping"}),
            "cockpit",
        )
        .unwrap_err();
        assert!(!error.to_string().is_empty());
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
        assert!(cli.receipt.is_some());
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

    #[test]
    fn storage_reconcile_cli_is_one_closed_command_and_second_dry_run_is_idempotent() {
        let root = std::env::temp_dir().join(format!(
            "ember-storage-cli-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let repository_root = root.join("immutable-source-worktree");
        let models = root.join("external-storage").join("models");
        let state = root.join("external-storage").join("state");
        fs::create_dir_all(&models).unwrap();
        fs::create_dir_all(&state).unwrap();
        let remote_master = repository_root.join(".git/refs/remotes/origin/master");
        fs::create_dir_all(remote_master.parent().unwrap()).unwrap();
        fs::write(&remote_master, format!("{}\n", "b".repeat(40))).unwrap();
        fs::write(models.join("kept.bin"), b"m").unwrap();
        fs::write(state.join("kept.bin"), b"s").unwrap();
        let policy = root.join("policy.json");
        fs::write(
            &policy,
            serde_json::to_vec(&json!({
                "schema_version":"ember-storage-retention-policy-v1",
                "filing_source_commit":"b".repeat(40),
                "classes":[
                    {"class":"models","canonical_root":"models","filing_total_bytes":12,
                     "protected_lower_bound_bytes":10,"admitted_growth_envelope_bytes":1,
                     "hard_quota_bytes":11,"keep_last_n":1,"grace_seconds":1,
                     "protected_predicates":["active_process_root","open_run_custody","nonterminal_attempt","registered_campaign_evidence","independently_pinned_checkpoint","receipt_dependency","sole_verified_copy"],
                     "eligibility_predicates":["reproducible","verified_duplicate_copy"],
                     "compression_rule":"none",
                     "maximum_reconcile_bytes":1},
                    {"class":"state","canonical_root":"state","filing_total_bytes":12,
                     "protected_lower_bound_bytes":10,"admitted_growth_envelope_bytes":1,
                     "hard_quota_bytes":11,"keep_last_n":null,"grace_seconds":1,
                     "protected_predicates":["active_process_root","open_run_custody","nonterminal_attempt","registered_campaign_evidence","receipt_dependency"],
                     "eligibility_predicates":["reproducible","terminal_receipt_kernel"],
                     "compression_rule":"terminal_receipt_kernel_v1",
                     "maximum_reconcile_bytes":1}
                ]
            }))
            .unwrap(),
        )
        .unwrap();
        let declarations = root.join("declarations.json");
        fs::write(
            &declarations,
            serde_json::to_vec(&vec![
                CensusDeclaration {
                    class: CustodyClass::Models,
                    relative_path: "kept.bin".into(),
                    disposition: ember_lab::storage_retention::Disposition::Protected,
                    pin_reasons: vec!["fixture".into()],
                    checkpoint: None,
                    duplicate_witness: None,
                    terminal_kernel_witness: None,
                },
                CensusDeclaration {
                    class: CustodyClass::State,
                    relative_path: "kept.bin".into(),
                    disposition: ember_lab::storage_retention::Disposition::Protected,
                    pin_reasons: vec!["fixture".into()],
                    checkpoint: None,
                    duplicate_witness: None,
                    terminal_kernel_witness: None,
                },
            ])
            .unwrap(),
        )
        .unwrap();
        let custody = root.join("custody");
        let make_request = || ember_lab::storage_retention::StorageReconcileRequest {
            repository_root: repository_root.clone(),
            policy: policy.clone(),
            declarations: declarations.clone(),
            models_root: models.clone(),
            state_root: state.clone(),
            custody: custody.clone(),
            pin_set_sha256: ember_lab::hash_file(&declarations).unwrap(),
            current_master: "b".repeat(40),
            projected_growth: std::collections::BTreeMap::from([
                (CustodyClass::Models, 0),
                (CustodyClass::State, 0),
            ]),
            operation: ember_lab::storage_retention::ReconcileOperation::DryRun,
        };
        let first = ember_lab::storage_retention::run_storage_reconcile(&make_request()).unwrap();
        fs::write(&remote_master, format!("{}\n", "c".repeat(40))).unwrap();
        let second = ember_lab::storage_retention::run_storage_reconcile(&make_request()).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.result, "DRY_RUN_PASS");
        assert_eq!(fs::read(models.join("kept.bin")).unwrap(), b"m");
        assert_eq!(fs::read(state.join("kept.bin")).unwrap(), b"s");

        let mut changed_root = make_request();
        changed_root.models_root = root.join("substituted-storage").join("models");
        fs::create_dir_all(&changed_root.models_root).unwrap();
        fs::write(changed_root.models_root.join("kept.bin"), b"m").unwrap();
        assert!(ember_lab::storage_retention::run_storage_reconcile(&changed_root).is_err());
        let mut changed_operation = make_request();
        changed_operation.operation = ember_lab::storage_retention::ReconcileOperation::Commit;
        assert!(ember_lab::storage_retention::run_storage_reconcile(&changed_operation).is_err());
    }

    #[test]
    fn storage_reconcile_cli_requires_and_preserves_projected_growth() {
        let models_pin = "a".repeat(64);
        let master_pin = "b".repeat(40);
        let command = parse_storage_retention_arguments(
            [
                "--pipe",
                "ember-storage-test",
                "--repository-root",
                "repo",
                "--policy",
                "policy.json",
                "--declarations",
                "declarations.json",
                "--models-root",
                "models",
                "--state-root",
                "state",
                "--custody",
                "custody",
                "--pin-set-sha256",
                &models_pin,
                "--current-master",
                &master_pin,
                "--projected-models-bytes",
                "123",
                "--projected-state-bytes",
                "456",
                "--mode",
                "dry-run",
            ]
            .into_iter()
            .map(str::to_owned),
        )
        .unwrap();
        let Command::StorageReconcile(args) = command else {
            panic!("expected storage reconcile command");
        };
        assert_eq!(args.projected_models_bytes, 123);
        assert_eq!(args.projected_state_bytes, 456);

        let missing = match parse_storage_retention_arguments(
            [
                "--pipe",
                "ember-storage-test",
                "--repository-root",
                "repo",
                "--policy",
                "policy.json",
                "--declarations",
                "declarations.json",
                "--models-root",
                "models",
                "--state-root",
                "state",
                "--custody",
                "custody",
                "--pin-set-sha256",
                &models_pin,
                "--current-master",
                &master_pin,
                "--mode",
                "dry-run",
            ]
            .into_iter()
            .map(str::to_owned),
        ) {
            Ok(_) => panic!("missing projected growth unexpectedly parsed"),
            Err(error) => error,
        };
        assert!(missing.contains("missing --projected-models-bytes"));
    }
}
