// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// NO-TEMP policy (per operator direction): none of ember's stack, current, past, or
// future, may live in system temp. This module is the Rust-side twin of
// tools/ember-cli/src/utils/ember-scratch.ts (emberScratchDir) -- the one canonical
// ember-owned scratch root for ember-lab call sites. See src/ember/infrastructure/tools/no_temp_allowlist and
// src/ember/infrastructure/tools/check_no_temp.py for the enforcement gate covering the rest of the stack.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const SCRATCH_OWNER_SCHEMA: &str = "ember-scratch-owner-v1";

#[derive(Clone, Debug)]
pub struct ScratchPolicy {
    pub root: PathBuf,
    pub minimum_free_bytes: u64,
    pub stale_after: Duration,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ScratchOwner {
    schema_version: String,
    purpose: String,
    pid: u32,
    process_start_token: String,
    created_at_ms: u64,
}

#[derive(Debug)]
pub struct ScratchLease {
    path: PathBuf,
}

impl ScratchLease {
    pub fn create(policy: ScratchPolicy, purpose: &str) -> io::Result<Self> {
        let pid = std::process::id();
        Self::create_with_identity(
            policy,
            purpose,
            pid,
            &current_process_start_token(pid)?,
            now_ms()?,
        )
    }

    #[doc(hidden)]
    pub fn create_with_identity(
        policy: ScratchPolicy,
        purpose: &str,
        pid: u32,
        process_start_token: &str,
        created_at_ms: u64,
    ) -> io::Result<Self> {
        validate_policy(&policy)?;
        if purpose.is_empty()
            || !purpose
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
            || process_start_token.trim().is_empty()
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "scratch purpose or process identity is invalid",
            ));
        }
        fs::create_dir_all(&policy.root)?;
        let root = fs::canonicalize(&policy.root)?;
        let identity_hash = sha256(process_start_token.as_bytes());
        let path = root
            .join(purpose)
            .join(format!("{pid}-{created_at_ms}-{}", &identity_hash[..16]));
        fs::create_dir_all(&path)?;
        let owner = ScratchOwner {
            schema_version: SCRATCH_OWNER_SCHEMA.into(),
            purpose: purpose.into(),
            pid,
            process_start_token: process_start_token.into(),
            created_at_ms,
        };
        let bytes = serde_json::to_vec(&owner).map_err(io::Error::other)?;
        let marker = path.join(format!("{}.owner.json", sha256(&bytes)));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&marker)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        Ok(Self { path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for ScratchLease {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.path);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScratchSweepDisposition {
    DeletedStaleOwner,
    LiveOwner,
    FreshOwner,
    MalformedOwner,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ScratchSweepEntry {
    pub path: PathBuf,
    pub owner_marker_sha256: Option<String>,
    pub disposition: ScratchSweepDisposition,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ScratchRootMeasurement {
    pub entry_count: u64,
    pub bytes: u64,
    pub free_bytes: u64,
    pub minimum_free_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ScratchSweepReceipt {
    pub schema_version: String,
    pub root: PathBuf,
    pub observed_at_ms: u64,
    pub before: ScratchRootMeasurement,
    pub after: ScratchRootMeasurement,
    pub deleted: Vec<ScratchSweepEntry>,
    pub retained: Vec<ScratchSweepEntry>,
    pub live_entries_deleted: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ScratchSweepPlan {
    schema_version: String,
    phase: String,
    root: PathBuf,
    observed_at_ms: u64,
    before: ScratchRootMeasurement,
    planned_deletions: Vec<ScratchSweepEntry>,
    retained: Vec<ScratchSweepEntry>,
}

pub fn sweep_scratch_root_to_receipt(
    policy: &ScratchPolicy,
    receipt_path: &Path,
) -> io::Result<ScratchSweepReceipt> {
    let mut free_space = available_space_bytes;
    let plan = plan_scratch_sweep(policy, now_ms()?, &mut free_space, process_identity_is_live)?;
    let mut receipt = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(receipt_path)?;
    write_json_line_and_sync(&mut receipt, &plan)?;
    let outcome = execute_scratch_sweep(policy, plan, &mut free_space, |path| {
        fs::remove_dir_all(path)
    })?;
    write_json_line_and_sync(
        &mut receipt,
        &serde_json::json!({"phase":"completed","outcome":&outcome}),
    )?;
    Ok(outcome)
}

#[cfg(test)]
fn sweep_scratch_root_with<F, G>(
    policy: &ScratchPolicy,
    observed_at_ms: u64,
    mut free_space: F,
    owner_is_live: G,
) -> io::Result<ScratchSweepReceipt>
where
    F: FnMut(&Path) -> io::Result<u64>,
    G: FnMut(u32, &str) -> io::Result<bool>,
{
    let plan = plan_scratch_sweep(policy, observed_at_ms, &mut free_space, owner_is_live)?;
    execute_scratch_sweep(policy, plan, &mut free_space, |path| {
        fs::remove_dir_all(path)
    })
}

fn plan_scratch_sweep<F, G>(
    policy: &ScratchPolicy,
    observed_at_ms: u64,
    free_space: &mut F,
    mut owner_is_live: G,
) -> io::Result<ScratchSweepPlan>
where
    F: FnMut(&Path) -> io::Result<u64>,
    G: FnMut(u32, &str) -> io::Result<bool>,
{
    validate_policy(policy)?;
    fs::create_dir_all(&policy.root)?;
    let root = fs::canonicalize(&policy.root)?;
    let before_entries = scratch_entries(&root)?;
    let before = measurement(policy, &root, &before_entries, free_space)?;
    let mut planned_deletions = Vec::new();
    let mut retained = Vec::new();

    for path in before_entries {
        let marker = read_owner_marker(&path);
        let (owner, marker_sha256) = match marker {
            Ok(value) => value,
            Err(_) => {
                retained.push(ScratchSweepEntry {
                    path,
                    owner_marker_sha256: None,
                    disposition: ScratchSweepDisposition::MalformedOwner,
                });
                continue;
            }
        };
        let live = owner_is_live(owner.pid, &owner.process_start_token)?;
        if live {
            retained.push(ScratchSweepEntry {
                path,
                owner_marker_sha256: Some(marker_sha256),
                disposition: ScratchSweepDisposition::LiveOwner,
            });
            continue;
        }
        let age_ms = observed_at_ms.saturating_sub(owner.created_at_ms);
        if age_ms < policy.stale_after.as_millis().min(u64::MAX as u128) as u64 {
            retained.push(ScratchSweepEntry {
                path,
                owner_marker_sha256: Some(marker_sha256),
                disposition: ScratchSweepDisposition::FreshOwner,
            });
            continue;
        }
        planned_deletions.push(ScratchSweepEntry {
            path,
            owner_marker_sha256: Some(marker_sha256),
            disposition: ScratchSweepDisposition::DeletedStaleOwner,
        });
    }

    Ok(ScratchSweepPlan {
        schema_version: "ember-scratch-sweep-v1".into(),
        phase: "planned".into(),
        root,
        observed_at_ms,
        before,
        planned_deletions,
        retained,
    })
}

fn execute_scratch_sweep<F, R>(
    policy: &ScratchPolicy,
    plan: ScratchSweepPlan,
    free_space: &mut F,
    mut remove_entry: R,
) -> io::Result<ScratchSweepReceipt>
where
    F: FnMut(&Path) -> io::Result<u64>,
    R: FnMut(&Path) -> io::Result<()>,
{
    for entry in &plan.planned_deletions {
        remove_entry(&entry.path)?;
    }
    let after_entries = scratch_entries(&plan.root)?;
    let after = measurement(policy, &plan.root, &after_entries, free_space)?;
    Ok(ScratchSweepReceipt {
        schema_version: "ember-scratch-sweep-v1".into(),
        root: plan.root,
        observed_at_ms: plan.observed_at_ms,
        before: plan.before,
        after,
        deleted: plan.planned_deletions,
        retained: plan.retained,
        live_entries_deleted: 0,
    })
}

fn write_json_line_and_sync<T: Serialize>(file: &mut fs::File, value: &T) -> io::Result<()> {
    serde_json::to_writer(&mut *file, value).map_err(io::Error::other)?;
    file.write_all(b"\n")?;
    file.flush()?;
    file.sync_all()
}

fn validate_policy(policy: &ScratchPolicy) -> io::Result<()> {
    if policy.minimum_free_bytes == 0 || policy.stale_after.is_zero() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "scratch policy requires positive floor and stale age",
        ));
    }
    #[cfg(all(windows, not(test)))]
    if policy
        .root
        .components()
        .next()
        .map(|component| {
            component
                .as_os_str()
                .to_string_lossy()
                .eq_ignore_ascii_case("c:")
        })
        .unwrap_or(false)
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "configured scratch root must not use protected C:",
        ));
    }
    Ok(())
}

fn scratch_entries(root: &Path) -> io::Result<Vec<PathBuf>> {
    let mut entries = Vec::new();
    for purpose in fs::read_dir(root)? {
        let purpose = purpose?;
        if !purpose.file_type()?.is_dir() {
            continue;
        }
        let purpose_path = fs::canonicalize(purpose.path())?;
        if !purpose_path.starts_with(root) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "scratch purpose escapes the configured root",
            ));
        }
        for entry in fs::read_dir(purpose_path)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                let path = fs::canonicalize(entry.path())?;
                if !path.starts_with(root) {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        "scratch entry escapes the configured root",
                    ));
                }
                entries.push(path);
            }
        }
    }
    entries.sort();
    Ok(entries)
}

fn measurement<F>(
    policy: &ScratchPolicy,
    root: &Path,
    entries: &[PathBuf],
    free_space: &mut F,
) -> io::Result<ScratchRootMeasurement>
where
    F: FnMut(&Path) -> io::Result<u64>,
{
    let bytes = entries.iter().try_fold(0_u64, |total, entry| {
        total
            .checked_add(directory_bytes(entry)?)
            .ok_or_else(|| io::Error::other("scratch byte count overflowed"))
    })?;
    Ok(ScratchRootMeasurement {
        entry_count: entries.len() as u64,
        bytes,
        free_bytes: free_space(root)?,
        minimum_free_bytes: policy.minimum_free_bytes,
    })
}

fn directory_bytes(path: &Path) -> io::Result<u64> {
    fs::read_dir(path)?.try_fold(0_u64, |total, entry| {
        let entry = entry?;
        let kind = entry.file_type()?;
        let bytes = if kind.is_dir() {
            directory_bytes(&entry.path())?
        } else if kind.is_file() {
            entry.metadata()?.len()
        } else {
            0
        };
        total
            .checked_add(bytes)
            .ok_or_else(|| io::Error::other("scratch byte count overflowed"))
    })
}

fn read_owner_marker(path: &Path) -> io::Result<(ScratchOwner, String)> {
    let mut markers = fs::read_dir(path)?
        .filter_map(|entry| entry.ok())
        .filter(|entry| {
            entry
                .file_type()
                .map(|kind| kind.is_file())
                .unwrap_or(false)
                && entry.file_name().to_string_lossy().ends_with(".owner.json")
        })
        .collect::<Vec<_>>();
    if markers.len() != 1 {
        return Err(io::Error::other(
            "scratch owner marker cardinality is not one",
        ));
    }
    let marker = markers.pop().expect("one marker exists");
    let bytes = fs::read(marker.path())?;
    let digest = sha256(&bytes);
    if marker.file_name().to_string_lossy() != format!("{digest}.owner.json") {
        return Err(io::Error::other("scratch owner marker hash mismatch"));
    }
    let owner: ScratchOwner = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
    if owner.schema_version != SCRATCH_OWNER_SCHEMA
        || owner.purpose.trim().is_empty()
        || owner.pid == 0
        || owner.process_start_token.trim().is_empty()
    {
        return Err(io::Error::other("scratch owner marker is invalid"));
    }
    Ok((owner, digest))
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn now_ms() -> io::Result<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(io::Error::other)?
        .as_millis()
        .try_into()
        .map_err(io::Error::other)
}

#[cfg(windows)]
fn available_space_bytes(path: &Path) -> io::Result<u64> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
    let wide = path
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let mut available = 0_u64;
    let ok = unsafe {
        GetDiskFreeSpaceExW(
            wide.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if ok == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(available)
}

#[cfg(not(windows))]
fn available_space_bytes(path: &Path) -> io::Result<u64> {
    use std::process::Command;
    let output = Command::new("df")
        .args(["--output=avail", "-B1"])
        .arg(path)
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other("scratch free-space probe failed"));
    }
    let text = std::str::from_utf8(&output.stdout).map_err(io::Error::other)?;
    let mut values = text.lines().map(str::trim).filter(|line| !line.is_empty());
    let _header = values.next();
    let value = values
        .next()
        .ok_or_else(|| io::Error::other("scratch free-space probe returned no value"))?;
    if values.next().is_some() {
        return Err(io::Error::other(
            "scratch free-space probe returned extra values",
        ));
    }
    value.parse::<u64>().map_err(io::Error::other)
}

#[cfg(windows)]
fn process_identity_is_live(pid: u32, expected_start_token: &str) -> io::Result<bool> {
    use std::mem::zeroed;
    use windows_sys::Win32::Foundation::{CloseHandle, FILETIME, WAIT_OBJECT_0, WAIT_TIMEOUT};
    use windows_sys::Win32::System::Threading::{
        GetProcessTimes, OpenProcess, WaitForSingleObject, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
    if process.is_null() {
        let error = io::Error::last_os_error();
        return if error.raw_os_error() == Some(87) {
            Ok(false)
        } else {
            Err(error)
        };
    }
    let wait = unsafe { WaitForSingleObject(process, 0) };
    if wait == WAIT_OBJECT_0 {
        unsafe { CloseHandle(process) };
        return Ok(false);
    }
    if wait != WAIT_TIMEOUT {
        unsafe { CloseHandle(process) };
        return Err(io::Error::last_os_error());
    }
    let (mut creation, mut exit, mut kernel, mut user): (FILETIME, FILETIME, FILETIME, FILETIME) =
        unsafe { zeroed() };
    let ok = unsafe { GetProcessTimes(process, &mut creation, &mut exit, &mut kernel, &mut user) };
    unsafe { CloseHandle(process) };
    if ok == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(expected_start_token
        == format!(
            "{:08x}{:08x}",
            creation.dwHighDateTime, creation.dwLowDateTime
        ))
}

#[cfg(not(windows))]
fn process_identity_is_live(pid: u32, expected_start_token: &str) -> io::Result<bool> {
    let stat = match fs::read_to_string(format!("/proc/{pid}/stat")) {
        Ok(stat) => stat,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    let observed = stat
        .rsplit_once(") ")
        .and_then(|(_, suffix)| suffix.split_whitespace().nth(19))
        .ok_or_else(|| io::Error::other("process start token is unavailable"))?;
    Ok(observed == expected_start_token)
}

#[cfg(windows)]
fn current_process_start_token(pid: u32) -> io::Result<String> {
    use std::mem::zeroed;
    use windows_sys::Win32::Foundation::{CloseHandle, FILETIME};
    use windows_sys::Win32::System::Threading::{
        GetProcessTimes, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
    if process.is_null() {
        return Err(io::Error::last_os_error());
    }
    let (mut creation, mut exit, mut kernel, mut user): (FILETIME, FILETIME, FILETIME, FILETIME) =
        unsafe { zeroed() };
    let ok = unsafe { GetProcessTimes(process, &mut creation, &mut exit, &mut kernel, &mut user) };
    unsafe { CloseHandle(process) };
    if ok == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(format!(
        "{:08x}{:08x}",
        creation.dwHighDateTime, creation.dwLowDateTime
    ))
}

#[cfg(not(windows))]
fn current_process_start_token(pid: u32) -> io::Result<String> {
    let stat = fs::read_to_string(format!("/proc/{pid}/stat"))?;
    stat.rsplit_once(") ")
        .and_then(|(_, suffix)| suffix.split_whitespace().nth(19))
        .map(str::to_owned)
        .ok_or_else(|| io::Error::other("process start token is unavailable"))
}

/// Resolves the user's home directory without an extra crate dependency:
/// `USERPROFILE` on Windows, `HOME` elsewhere, falling back to `.` only if
/// neither is set.
fn home_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(profile) = std::env::var("USERPROFILE") {
            if !profile.is_empty() {
                return PathBuf::from(profile);
            }
        }
    }
    #[cfg(not(windows))]
    {
        if let Ok(home) = std::env::var("HOME") {
            if !home.is_empty() {
                return PathBuf::from(home);
            }
        }
    }
    PathBuf::from(".")
}

/// Returns the ember-owned scratch directory for `purpose`, creating it if
/// necessary. Never touches system temp. Mirrors the TypeScript
/// `emberScratchDir` contract exactly:
///
/// Path shape: `<EMBER_HOME>/.runtime/<purpose>/<pid>`
/// - `EMBER_HOME` = the `EMBER_HOME` env var if set, else `~/.ember`.
/// - The directory is created recursively before returning.
/// - The returned path is canonicalized so downstream path comparisons are
///   case-correct on case-insensitive filesystems (Windows/macOS).
pub fn ember_scratch_dir(purpose: &str) -> io::Result<PathBuf> {
    let ember_home = std::env::var("EMBER_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| home_dir().join(".ember"));
    ember_scratch_dir_under(&ember_home, purpose)
}

/// `ember_scratch_dir` with the root supplied explicitly.
///
/// Exists so the path contract can be tested without `set_var("EMBER_HOME")`:
/// unit tests share one process, so mutating that variable retargets
/// `ember_scratch_dir` for every test running concurrently.
pub(crate) fn ember_scratch_dir_under(ember_home: &Path, purpose: &str) -> io::Result<PathBuf> {
    let scratch_path = ember_home
        .join(".runtime")
        .join(purpose)
        .join(std::process::id().to_string());
    std::fs::create_dir_all(&scratch_path)?;
    std::fs::canonicalize(&scratch_path)
}

#[cfg(test)]
mod ember_scratch_dir_tests {
    use super::{
        ember_scratch_dir_under, sweep_scratch_root_to_receipt, sweep_scratch_root_with,
        ScratchLease, ScratchPolicy, ScratchSweepDisposition,
    };
    use std::fs;
    use std::path::PathBuf;
    use std::time::Duration;

    /// In-tree (never system-temp) scratch root for THIS test's own EMBER_HOME
    /// fixture -- consistent with the policy this module enforces.
    fn test_fixture_root(test_name: &str) -> PathBuf {
        std::env::var("CARGO_TARGET_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target"))
            .join("no-temp-gate-test-fixtures")
            .join(format!("ember-home-{}", std::process::id()))
            .join(test_name)
    }

    // This test used to prove its point by pointing %TEMP%/%TMP% at a bogus
    // wrongly-cased path and setting %EMBER_HOME%, all via `env::set_var`.
    // Those writes are process-global and unit tests share one process, so
    // every test running concurrently saw them: `std::env::temp_dir()` started
    // returning the bogus root, and the teardown's `remove_dir_all` deleted
    // scratch directories out from under other tests mid-run. It was also
    // proving nothing -- `ember_scratch_dir` reads `EMBER_HOME`, never
    // `TEMP`/`TMP`, so the bogus override could not have leaked even in
    // principle. Source-level enforcement of the NO-TEMP policy is
    // `src/ember/infrastructure/tools/check_no_temp.py`; the path contract is checked here against an
    // explicit root instead.
    #[test]
    fn scratch_dir_lands_under_its_root() {
        let ember_home = test_fixture_root("path-contract");
        let _ = std::fs::remove_dir_all(&ember_home);

        let dir = ember_scratch_dir_under(&ember_home, "binding-snapshot-test")
            .expect("scratch dir creation must succeed");
        assert!(dir.exists(), "scratch dir must exist after creation");

        let dir_lower = dir.to_string_lossy().to_ascii_lowercase();
        let ember_home_lower = ember_home.to_string_lossy().to_ascii_lowercase();
        assert!(
            dir_lower.contains(&ember_home_lower),
            "scratch dir {dir_lower} did not land under root {ember_home_lower}"
        );

        let _ = std::fs::remove_dir_all(&ember_home);
    }

    fn policy(root: PathBuf) -> ScratchPolicy {
        ScratchPolicy {
            root,
            minimum_free_bytes: 1024,
            stale_after: Duration::from_secs(60),
        }
    }

    #[test]
    fn scratch_lease_removes_its_directory_on_drop_and_unwind() {
        let fixture = test_fixture_root("lease-cleanup");
        let root = fixture.join("root");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();

        let normal_path = {
            let lease = ScratchLease::create_with_identity(
                policy(root.clone()),
                "normal",
                101,
                "start-normal",
                1_000,
            )
            .unwrap();
            let path = lease.path().to_path_buf();
            assert!(path.is_dir());
            path
        };
        assert!(!normal_path.exists());

        let mut panic_path = None;
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let lease = ScratchLease::create_with_identity(
                policy(root.clone()),
                "panic",
                102,
                "start-panic",
                2_000,
            )
            .unwrap();
            panic_path = Some(lease.path().to_path_buf());
            panic!("exercise unwind cleanup");
        }));
        assert!(outcome.is_err());
        assert!(!panic_path.unwrap().exists());
        let _ = fs::remove_dir_all(fixture);
    }

    #[test]
    fn sweep_preserves_live_and_removes_only_stale_dead_residue() {
        let fixture = test_fixture_root("sweep");
        let root = fixture.join("root");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let live = ScratchLease::create_with_identity(
            policy(root.clone()),
            "live",
            201,
            "live-start",
            1_000,
        )
        .unwrap();
        let dead = ScratchLease::create_with_identity(
            policy(root.clone()),
            "dead",
            202,
            "dead-start",
            1_000,
        )
        .unwrap();
        let dead_path = dead.path().to_path_buf();
        std::mem::forget(dead);
        fs::write(dead_path.join("residue.bin"), b"hard-kill-residue").unwrap();

        let receipt = sweep_scratch_root_with(
            &policy(root.clone()),
            62_000,
            |_| Ok(10_000),
            |pid, token| Ok(pid == 201 && token == "live-start"),
        )
        .unwrap();
        assert!(live.path().exists());
        assert!(!dead_path.exists());
        assert_eq!(receipt.before.entry_count, 2);
        assert_eq!(receipt.after.entry_count, 1);
        assert_eq!(receipt.deleted.len(), 1);
        assert_eq!(receipt.retained.len(), 1);
        assert_eq!(
            receipt.retained[0].disposition,
            ScratchSweepDisposition::LiveOwner
        );
        assert_eq!(receipt.live_entries_deleted, 0);
        drop(live);
        let _ = fs::remove_dir_all(fixture);
    }

    #[test]
    fn governed_sweep_persists_plan_before_deletion_and_refuses_overwrite() {
        let fixture = test_fixture_root("journal");
        let root = fixture.join("root");
        fs::create_dir_all(&root).unwrap();
        let residue = ScratchLease::create_with_identity(
            policy(root.clone()),
            "hard-kill",
            u32::MAX,
            "dead-start",
            1,
        )
        .unwrap();
        let residue_path = residue.path().to_path_buf();
        std::mem::forget(residue);
        let receipt_path = fixture.join("sweep.jsonl");

        let receipt = sweep_scratch_root_to_receipt(&policy(root), &receipt_path).unwrap();
        assert!(!residue_path.exists());
        assert_eq!(receipt.deleted.len(), 1);
        let lines = fs::read_to_string(&receipt_path).unwrap();
        let records = lines
            .lines()
            .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0]["phase"], "planned");
        assert_eq!(
            records[0]["planned_deletions"][0]["path"],
            residue_path.to_string_lossy().as_ref()
        );
        assert_eq!(records[1]["phase"], "completed");
        assert!(
            sweep_scratch_root_to_receipt(&policy(fixture.join("root")), &receipt_path).is_err()
        );
        let _ = fs::remove_dir_all(fixture);
    }
}
