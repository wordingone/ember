// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use super::{CanaryHostSnapshot, CanaryProcessIdentity, EmberdError, Result};
use serde::Serialize;
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
#[cfg(windows)]
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_NO_MORE_FILES, FILETIME, INVALID_HANDLE_VALUE,
};
#[cfg(windows)]
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
#[cfg(windows)]
use windows_sys::Win32::System::Threading::{
    GetProcessTimes, OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
};

const MIB: u64 = 1024 * 1024;
const WSL_PROCESS_NAMES: [&str; 4] = ["wsl.exe", "wslhost.exe", "wslservice.exe", "vmmemwsl.exe"];
const DOCKER_PROCESS_NAMES: [&str; 4] = [
    "docker.exe",
    "docker desktop.exe",
    "com.docker.backend.exe",
    "com.docker.service",
];
const PERSISTENT_WORKER_PROCESS_NAMES: [&str; 2] = ["ember-worker.exe", "emberd-worker.exe"];

fn invalid(detail: &str) -> EmberdError {
    EmberdError::InvalidDispatchManifest {
        detail: detail.into(),
    }
}

fn parse_utf8_lines(stdout: &[u8]) -> Result<Vec<&str>> {
    let text = std::str::from_utf8(stdout)
        .map_err(|_| invalid("native NVIDIA probe output is not strict UTF-8"))?;
    Ok(text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect())
}

fn parse_gpu_uuid(raw: &str) -> Result<String> {
    let uuid = raw.trim();
    if !uuid.starts_with("GPU-")
        || uuid.len() <= 4
        || !uuid
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return Err(invalid("native NVIDIA probe returned an invalid GPU UUID"));
    }
    Ok(uuid.into())
}

fn mib_to_bytes(raw: &str) -> Result<u64> {
    raw.trim()
        .parse::<u64>()
        .ok()
        .filter(|value| *value > 0)
        .and_then(|value| value.checked_mul(MIB))
        .ok_or_else(|| invalid("native NVIDIA probe returned an invalid MiB value"))
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct GpuRow {
    pub uuid: String,
    pub free_vram_bytes: u64,
    pub total_vram_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ComputeRow {
    pub gpu_uuid: String,
    pub pid: u32,
    pub reported_name: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ProcessRecord {
    pub pid: u32,
    pub parent_pid: u32,
    pub start_token: u64,
    pub image_path: String,
    pub image_sha256: String,
}

pub(crate) fn snapshot_from_observations(
    observed_at_ms: i64,
    nvidia_smi_sha256: &str,
    gpu_stdout: &[u8],
    compute_stdout: &[u8],
    process_table: &[ProcessRecord],
    forbidden_process_names: &[String],
) -> Result<CanaryHostSnapshot> {
    if observed_at_ms < 0 || super::validate_hash(nvidia_smi_sha256).is_err() {
        return Err(invalid(
            "native canary snapshot lacks a valid observation or NVIDIA executable identity",
        ));
    }
    let gpu = parse_single_gpu_csv(gpu_stdout)?;
    let compute = parse_compute_apps_csv(compute_stdout, &gpu.uuid)?;
    let projection =
        project_relevant_processes(&compute, process_table, &gpu.uuid, forbidden_process_names)?;
    let gpu_query_bytes = serde_json::to_vec(&gpu)?;
    let compute_query_bytes = serde_json::to_vec(&compute)?;
    let process_inventory_bytes = serde_json::to_vec(&projection.processes)?;
    Ok(CanaryHostSnapshot {
        observed_at_ms,
        gpu_uuid: gpu.uuid,
        free_vram_bytes: gpu.free_vram_bytes,
        total_vram_bytes: gpu.total_vram_bytes,
        nvidia_smi_sha256: nvidia_smi_sha256.into(),
        gpu_query_sha256: super::hash_bytes(&gpu_query_bytes),
        compute_query_sha256: super::hash_bytes(&compute_query_bytes),
        process_inventory_sha256: super::hash_bytes(&process_inventory_bytes),
        processes: projection.processes,
        wsl_detected: projection.wsl_detected,
        docker_detected: projection.docker_detected,
        persistent_worker_detected: projection.persistent_worker_detected,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ProcessProjection {
    pub processes: Vec<CanaryProcessIdentity>,
    pub wsl_detected: bool,
    pub docker_detected: bool,
    pub persistent_worker_detected: bool,
}

pub(crate) fn parse_single_gpu_csv(stdout: &[u8]) -> Result<GpuRow> {
    let lines = parse_utf8_lines(stdout)?;
    if lines.len() != 1 {
        return Err(invalid(
            "governed canary requires exactly one native GPU row",
        ));
    }
    let fields = lines[0].split(',').map(str::trim).collect::<Vec<_>>();
    if fields.len() != 3 {
        return Err(invalid(
            "native GPU row must contain exactly UUID, free MiB, and total MiB",
        ));
    }
    let uuid = parse_gpu_uuid(fields[0])?;
    let free_vram_bytes = mib_to_bytes(fields[1])?;
    let total_vram_bytes = mib_to_bytes(fields[2])?;
    if free_vram_bytes > total_vram_bytes {
        return Err(invalid(
            "native GPU free VRAM exceeds the observed total VRAM",
        ));
    }
    Ok(GpuRow {
        uuid,
        free_vram_bytes,
        total_vram_bytes,
    })
}

pub(crate) fn parse_compute_apps_csv(
    stdout: &[u8],
    expected_gpu_uuid: &str,
) -> Result<Vec<ComputeRow>> {
    let expected_gpu_uuid = parse_gpu_uuid(expected_gpu_uuid)?;
    let mut seen_pids = BTreeSet::new();
    let mut rows = Vec::new();
    for line in parse_utf8_lines(stdout)? {
        let fields = line.split(',').map(str::trim).collect::<Vec<_>>();
        if fields.len() != 3 {
            return Err(invalid(
                "native compute row must contain exactly GPU UUID, PID, and name",
            ));
        }
        let gpu_uuid = parse_gpu_uuid(fields[0])?;
        let pid = fields[1]
            .parse::<u32>()
            .ok()
            .filter(|pid| *pid > 0)
            .ok_or_else(|| invalid("native compute row has an invalid PID"))?;
        let reported_name = fields[2];
        if gpu_uuid != expected_gpu_uuid
            || reported_name.is_empty()
            || reported_name.chars().any(char::is_control)
            || !seen_pids.insert(pid)
        {
            return Err(invalid(
                "native compute row is not uniquely bound to the expected GPU",
            ));
        }
        rows.push(ComputeRow {
            gpu_uuid,
            pid,
            reported_name: reported_name.into(),
        });
    }
    rows.sort_by_key(|row| row.pid);
    Ok(rows)
}

pub(crate) fn project_relevant_processes(
    compute_rows: &[ComputeRow],
    process_table: &[ProcessRecord],
    expected_gpu_uuid: &str,
    forbidden_process_names: &[String],
) -> Result<ProcessProjection> {
    let expected_gpu_uuid = parse_gpu_uuid(expected_gpu_uuid)?;
    let forbidden = forbidden_process_names
        .iter()
        .map(|name| name.trim().to_ascii_lowercase())
        .collect::<BTreeSet<_>>();
    if forbidden.len() != forbidden_process_names.len()
        || forbidden.iter().any(|name| name.is_empty())
    {
        return Err(invalid(
            "native process projection received an invalid forbidden-name policy",
        ));
    }
    let mut table = std::collections::BTreeMap::new();
    for process in process_table {
        if process.pid == 0 || table.insert(process.pid, process).is_some() {
            return Err(invalid(
                "native process inventory contains a missing or duplicate PID",
            ));
        }
    }
    let mut compute = std::collections::BTreeMap::new();
    for row in compute_rows {
        if row.gpu_uuid != expected_gpu_uuid || compute.insert(row.pid, row).is_some() {
            return Err(invalid(
                "native compute inventory is not uniquely GPU-bound",
            ));
        }
    }
    let mut processes = Vec::new();
    let mut wsl_detected = false;
    let mut docker_detected = false;
    let mut persistent_worker_detected = false;
    for process in process_table {
        let image_path = std::path::Path::new(&process.image_path);
        let image_name = image_path
            .file_name()
            .and_then(|value| value.to_str())
            .map(str::trim)
            .map(str::to_ascii_lowercase)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| invalid("native process image lacks a strict basename"))?;
        let is_compute = compute.contains_key(&process.pid);
        let is_forbidden = forbidden.contains(&image_name);
        let is_wsl = WSL_PROCESS_NAMES.contains(&image_name.as_str());
        let is_docker = DOCKER_PROCESS_NAMES.contains(&image_name.as_str());
        let is_persistent_worker = PERSISTENT_WORKER_PROCESS_NAMES.contains(&image_name.as_str());
        if !(is_compute || is_forbidden || is_wsl || is_docker || is_persistent_worker) {
            continue;
        }
        if process.start_token == 0
            || !image_path.is_absolute()
            || super::validate_hash(&process.image_sha256).is_err()
        {
            return Err(invalid(
                "relevant native process identity is incomplete or unhashable",
            ));
        }
        let gpu_uuid = if let Some(row) = compute.get(&process.pid) {
            let reported_name = std::path::Path::new(&row.reported_name)
                .file_name()
                .and_then(|value| value.to_str())
                .map(str::trim)
                .map(str::to_ascii_lowercase)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| invalid("native compute row lacks a strict process basename"))?;
            if reported_name != image_name {
                return Err(invalid(
                    "native compute PID image changed between GPU and process probes",
                ));
            }
            Some(expected_gpu_uuid.clone())
        } else {
            None
        };
        wsl_detected |= is_wsl;
        docker_detected |= is_docker;
        persistent_worker_detected |= is_persistent_worker;
        processes.push(CanaryProcessIdentity {
            pid: process.pid,
            parent_pid: process.parent_pid,
            start_token: process.start_token,
            image_name,
            image_sha256: process.image_sha256.clone(),
            gpu_uuid,
        });
    }
    for pid in compute.keys() {
        if !processes.iter().any(|process| process.pid == *pid) {
            return Err(invalid(
                "native compute PID disappeared before identity binding",
            ));
        }
    }
    processes.sort_by_key(|process| (process.pid, process.start_token));
    Ok(ProcessProjection {
        processes,
        wsl_detected,
        docker_detected,
        persistent_worker_detected,
    })
}

fn resolve_nvidia_smi() -> Result<PathBuf> {
    let path = std::env::var_os("PATH")
        .ok_or_else(|| invalid("native NVIDIA probe requires an explicit PATH"))?;
    let mut candidates = BTreeSet::new();
    for directory in std::env::split_paths(&path) {
        let candidate = directory.join("nvidia-smi.exe");
        if candidate.is_file() {
            let canonical = fs::canonicalize(candidate).map_err(|_| {
                invalid("native NVIDIA executable cannot be canonicalized from PATH")
            })?;
            candidates.insert(canonical);
        }
    }
    if candidates.len() != 1 {
        return Err(invalid(
            "governed canary requires exactly one canonical nvidia-smi.exe on PATH",
        ));
    }
    Ok(candidates.into_iter().next().expect("one candidate"))
}

fn run_nvidia_query(executable: &Path, args: &[&str]) -> Result<Vec<u8>> {
    let output = Command::new(executable)
        .args(args)
        .output()
        .map_err(|_| invalid("native NVIDIA query could not start"))?;
    if !output.status.success() || !output.stderr.is_empty() {
        return Err(invalid(
            "native NVIDIA query returned a failure or unexpected stderr",
        ));
    }
    std::str::from_utf8(&output.stdout)
        .map_err(|_| invalid("native NVIDIA query returned non-UTF-8 bytes"))?;
    Ok(output.stdout)
}

#[cfg(windows)]
fn filetime_token(value: FILETIME) -> u64 {
    (u64::from(value.dwHighDateTime) << 32) | u64::from(value.dwLowDateTime)
}

#[cfg(windows)]
fn wide_z_to_string(buffer: &[u16]) -> Result<String> {
    let end = buffer
        .iter()
        .position(|unit| *unit == 0)
        .unwrap_or(buffer.len());
    String::from_utf16(&buffer[..end])
        .map_err(|_| invalid("native process inventory contains invalid UTF-16"))
}

#[cfg(windows)]
fn process_image_identity(pid: u32) -> Result<(u64, PathBuf)> {
    let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
    if handle.is_null() {
        return Err(EmberdError::InvalidDispatchManifest {
            detail: format!(
                "relevant native process cannot be opened for identity binding: {}",
                std::io::Error::last_os_error()
            ),
        });
    }
    let result = (|| {
        let mut creation: FILETIME = unsafe { std::mem::zeroed() };
        let mut exit: FILETIME = unsafe { std::mem::zeroed() };
        let mut kernel: FILETIME = unsafe { std::mem::zeroed() };
        let mut user: FILETIME = unsafe { std::mem::zeroed() };
        if unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) } == 0
        {
            return Err(invalid(
                "relevant native process creation token is unavailable",
            ));
        }
        let start_token = filetime_token(creation);
        if start_token == 0 {
            return Err(invalid("relevant native process creation token is zero"));
        }
        let mut image = vec![0u16; 32_768];
        let mut length = image.len() as u32;
        if unsafe { QueryFullProcessImageNameW(handle, 0, image.as_mut_ptr(), &mut length) } == 0
            || length == 0
        {
            return Err(invalid("relevant native process image path is unavailable"));
        }
        image.truncate(length as usize);
        let path = PathBuf::from(
            String::from_utf16(&image)
                .map_err(|_| invalid("relevant native process image path is not UTF-16"))?,
        );
        let canonical = fs::canonicalize(path)
            .map_err(|_| invalid("relevant native process image path is not canonical"))?;
        Ok((start_token, canonical))
    })();
    unsafe {
        CloseHandle(handle);
    }
    result
}

#[cfg(windows)]
fn native_process_table(
    compute_rows: &[ComputeRow],
    forbidden_process_names: &[String],
) -> Result<Vec<ProcessRecord>> {
    let compute_pids = compute_rows
        .iter()
        .map(|row| row.pid)
        .collect::<BTreeSet<_>>();
    let forbidden = forbidden_process_names
        .iter()
        .map(|name| name.as_str())
        .collect::<BTreeSet<_>>();
    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(invalid("native process snapshot could not be created"));
    }
    let result = (|| {
        let mut entry: PROCESSENTRY32W = unsafe { std::mem::zeroed() };
        entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        if unsafe { Process32FirstW(snapshot, &mut entry) } == 0 {
            return Err(invalid("native process snapshot has no readable first row"));
        }
        let mut records = Vec::new();
        let mut seen = BTreeSet::new();
        loop {
            let pid = entry.th32ProcessID;
            let image_name = wide_z_to_string(&entry.szExeFile)?
                .trim()
                .to_ascii_lowercase();
            if pid != 0 && !seen.insert(pid) {
                return Err(invalid("native process snapshot contains a duplicate PID"));
            }
            let relevant = pid != 0
                && (compute_pids.contains(&pid)
                    || forbidden.contains(image_name.as_str())
                    || WSL_PROCESS_NAMES.contains(&image_name.as_str())
                    || DOCKER_PROCESS_NAMES.contains(&image_name.as_str())
                    || PERSISTENT_WORKER_PROCESS_NAMES.contains(&image_name.as_str()));
            if relevant {
                let (start_token, image_path) = process_image_identity(pid)?;
                let image_sha256 = super::hash_file(&image_path)?;
                records.push(ProcessRecord {
                    pid,
                    parent_pid: entry.th32ParentProcessID,
                    start_token,
                    image_path: image_path.to_string_lossy().into_owned(),
                    image_sha256,
                });
            }
            if unsafe { Process32NextW(snapshot, &mut entry) } == 0 {
                let last_error = unsafe { GetLastError() };
                if last_error != ERROR_NO_MORE_FILES {
                    return Err(invalid("native process snapshot terminated unexpectedly"));
                }
                break;
            }
        }
        Ok(records)
    })();
    unsafe {
        CloseHandle(snapshot);
    }
    result
}

#[cfg(windows)]
pub(crate) fn native_canary_host_snapshot(
    forbidden_process_names: &[String],
) -> Result<CanaryHostSnapshot> {
    let executable = resolve_nvidia_smi()?;
    let executable_sha256_before = super::hash_file(&executable)?;
    let gpu_stdout = run_nvidia_query(
        &executable,
        &[
            "--query-gpu=uuid,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
    )?;
    let gpu = parse_single_gpu_csv(&gpu_stdout)?;
    let compute_stdout = run_nvidia_query(
        &executable,
        &[
            "--query-compute-apps=gpu_uuid,pid,process_name",
            "--format=csv,noheader,nounits",
        ],
    )?;
    let compute = parse_compute_apps_csv(&compute_stdout, &gpu.uuid)?;
    let process_table = native_process_table(&compute, forbidden_process_names)?;
    let executable_sha256_after = super::hash_file(&executable)?;
    if executable_sha256_before != executable_sha256_after {
        return Err(invalid(
            "native NVIDIA executable changed during host probing",
        ));
    }
    snapshot_from_observations(
        super::now_ms(),
        &executable_sha256_before,
        &gpu_stdout,
        &compute_stdout,
        &process_table,
        forbidden_process_names,
    )
}

#[cfg(not(windows))]
pub(crate) fn native_canary_host_snapshot(
    _forbidden_process_names: &[String],
) -> Result<CanaryHostSnapshot> {
    Err(invalid(
        "native governed-canary host probing is Windows-only",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    const MIB: u64 = 1024 * 1024;

    #[test]
    fn parses_one_exact_gpu_and_compute_process_set() {
        let gpu = parse_single_gpu_csv(b"GPU-EMBER, 24576, 32768\r\n").unwrap();
        assert_eq!(
            gpu,
            GpuRow {
                uuid: "GPU-EMBER".into(),
                free_vram_bytes: 24_576 * MIB,
                total_vram_bytes: 32_768 * MIB,
            }
        );
        let rows = parse_compute_apps_csv(
            b"GPU-EMBER, 42, C:\\\\Python\\\\python.exe\r\nGPU-EMBER, 84, qwen.exe\r\n",
            "GPU-EMBER",
        )
        .unwrap();
        assert_eq!(
            rows,
            vec![
                ComputeRow {
                    gpu_uuid: "GPU-EMBER".into(),
                    pid: 42,
                    reported_name: r"C:\\Python\\python.exe".into(),
                },
                ComputeRow {
                    gpu_uuid: "GPU-EMBER".into(),
                    pid: 84,
                    reported_name: "qwen.exe".into(),
                },
            ]
        );
    }

    #[test]
    fn gpu_parser_rejects_ambiguous_or_impossible_observations() {
        for raw in [
            b"".as_slice(),
            b"GPU-A, 10, 20\nGPU-B, 10, 20\n".as_slice(),
            b"GPU-A, nope, 20\n".as_slice(),
            b"GPU-A, 21, 20\n".as_slice(),
            b"GPU-A, 0, 20\n".as_slice(),
            b"GPU-A, 10, 0\n".as_slice(),
            b"GPU-A, 10\n".as_slice(),
            b"GPU-A, 10, 20, extra\n".as_slice(),
        ] {
            assert!(parse_single_gpu_csv(raw).is_err(), "{raw:?}");
        }
    }

    #[test]
    fn compute_parser_is_closed_and_gpu_bound() {
        assert_eq!(
            parse_compute_apps_csv(b"\r\n", "GPU-EMBER").unwrap(),
            Vec::<ComputeRow>::new()
        );
        for raw in [
            b"GPU-OTHER, 42, python.exe\n".as_slice(),
            b"GPU-EMBER, 0, python.exe\n".as_slice(),
            b"GPU-EMBER, nope, python.exe\n".as_slice(),
            b"GPU-EMBER, 42,\n".as_slice(),
            b"GPU-EMBER, 42, python.exe, extra\n".as_slice(),
            b"GPU-EMBER, 42, python.exe\nGPU-EMBER, 42, python.exe\n".as_slice(),
        ] {
            assert!(parse_compute_apps_csv(raw, "GPU-EMBER").is_err(), "{raw:?}");
        }
    }

    fn process(pid: u32, name: &str) -> ProcessRecord {
        ProcessRecord {
            pid,
            parent_pid: 1,
            start_token: 1_000 + u64::from(pid),
            image_path: format!(r"C:\owned\{name}"),
            image_sha256: format!("{pid:064x}"),
        }
    }

    #[test]
    fn projects_compute_and_policy_relevant_windows_identities() {
        let compute = vec![ComputeRow {
            gpu_uuid: "GPU-EMBER".into(),
            pid: 42,
            reported_name: r"C:\owned\python.exe".into(),
        }];
        let table = vec![
            process(42, "python.exe"),
            process(84, "qwen.exe"),
            process(126, "wslhost.exe"),
            process(168, "com.docker.backend.exe"),
            process(210, "ember-worker.exe"),
            process(252, "unrelated.exe"),
        ];
        let projection = project_relevant_processes(
            &compute,
            &table,
            "GPU-EMBER",
            &["llama-server.exe".into(), "qwen.exe".into()],
        )
        .unwrap();
        assert_eq!(
            projection
                .processes
                .iter()
                .map(|process| (process.pid, process.image_name.as_str()))
                .collect::<Vec<_>>(),
            vec![
                (42, "python.exe"),
                (84, "qwen.exe"),
                (126, "wslhost.exe"),
                (168, "com.docker.backend.exe"),
                (210, "ember-worker.exe"),
            ]
        );
        assert_eq!(
            projection.processes[0].gpu_uuid.as_deref(),
            Some("GPU-EMBER")
        );
        assert!(projection.processes[1..]
            .iter()
            .all(|process| process.gpu_uuid.is_none()));
        assert!(projection.wsl_detected);
        assert!(projection.docker_detected);
        assert!(projection.persistent_worker_detected);
    }

    #[test]
    fn process_projection_fails_closed_on_missing_reused_or_mismatched_compute_pid() {
        let compute = vec![ComputeRow {
            gpu_uuid: "GPU-EMBER".into(),
            pid: 42,
            reported_name: "python.exe".into(),
        }];
        assert!(
            project_relevant_processes(&compute, &[], "GPU-EMBER", &["qwen.exe".into()]).is_err()
        );
        assert!(project_relevant_processes(
            &compute,
            &[process(42, "other.exe")],
            "GPU-EMBER",
            &["qwen.exe".into()]
        )
        .is_err());
        let mut reused = process(42, "python.exe");
        reused.start_token = 0;
        assert!(
            project_relevant_processes(&compute, &[reused], "GPU-EMBER", &["qwen.exe".into()])
                .is_err()
        );
    }

    #[test]
    fn assembles_a_content_addressed_native_host_snapshot() {
        let snapshot = snapshot_from_observations(
            12_345,
            &"a".repeat(64),
            b"GPU-EMBER, 24576, 32768\r\n",
            b"GPU-EMBER, 42, python.exe\r\n",
            &[process(42, "python.exe")],
            &["llama-server.exe".into(), "qwen.exe".into()],
        )
        .unwrap();
        assert_eq!(snapshot.observed_at_ms, 12_345);
        assert_eq!(snapshot.gpu_uuid, "GPU-EMBER");
        assert_eq!(snapshot.free_vram_bytes, 24_576 * MIB);
        assert_eq!(snapshot.total_vram_bytes, 32_768 * MIB);
        assert_eq!(snapshot.nvidia_smi_sha256, "a".repeat(64));
        assert_eq!(snapshot.gpu_query_sha256.len(), 64);
        assert_eq!(snapshot.compute_query_sha256.len(), 64);
        assert_eq!(snapshot.process_inventory_sha256.len(), 64);
        assert_eq!(snapshot.processes.len(), 1);
        assert!(!snapshot.wsl_detected);
        assert!(!snapshot.docker_detected);
        assert!(!snapshot.persistent_worker_detected);
    }

    #[cfg(windows)]
    #[test]
    fn native_toolhelp_probe_binds_or_refuses_the_current_process_without_fabrication() {
        let executable = std::env::current_exe().unwrap();
        let reported_name = executable
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap()
            .to_string();
        let result = native_process_table(
            &[ComputeRow {
                gpu_uuid: "GPU-EMBER".into(),
                pid: std::process::id(),
                reported_name,
            }],
            &["llama-server.exe".into(), "qwen.exe".into()],
        );
        match result {
            Ok(rows) => {
                let current = rows
                    .iter()
                    .find(|row| row.pid == std::process::id())
                    .unwrap();
                assert!(current.start_token > 0);
                assert_eq!(
                    current.image_sha256,
                    super::super::hash_file(&executable).unwrap()
                );
            }
            Err(EmberdError::InvalidDispatchManifest { detail }) => {
                assert!(
                    detail.contains("cannot be opened for identity binding"),
                    "{detail}"
                );
            }
            Err(other) => panic!("unexpected native process-probe outcome: {other}"),
        }
    }
}
