// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! Training-scoped verify (issue #1400): a synchronous, GitHub-free check of EXACTLY the
//! training dependency closure -- not the ~234k-file EMBER-01 completion census. It reads
//! `manifests/training-dependency-closure.json` (the single closure declaration
//! `src/ember/governance/scripts/training_closure.py` also reads), proves every declared member exists, hashes
//! the declared set with the identical algorithm `src/ember/governance/scripts/training_closure.py::
//! compute_closure_hash` uses, then verifies the input-identity/admission chain, the
//! tokenizer/model-config identity, and (when a certificate is supplied) the certificate's
//! `closure_sha256` binding plus the verified-at commit's ancestry.
//!
//! What this module deliberately does NOT do: re-walk Python imports/exec edges to prove
//! the closure DECLARATION is honest (`src/ember/governance/scripts/training_closure.py::audit_closure`'s
//! reachability half). That is a boundary-drift guard that already runs in CI and again,
//! live, inside `tools/ember-restart-3b/certified_train_launch.py::read_live_closure_sha256`
//! immediately before a launch consumes this receipt. Porting a second Python-AST walker
//! into Rust would duplicate a check the launch path already makes, for no verification
//! this receipt needs to make on its own. See docs referenced in the #1400 PR body for the
//! full reasoning.
//!
//! Zero `gh`, zero network, anywhere in this module. The only subprocess ever spawned is
//! one local `git merge-base --is-ancestor` read (never a fetch/ls-remote), and only when a
//! `--certificate` was supplied. That call always carries `GIT_OPTIONAL_LOCKS=0` -- the same
//! discipline any read against a possibly-registered worktree observes -- and this module
//! never writes inside `root` at all, so it is unconditionally hands-off toward whatever
//! tree it is pointed at.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::path::Path;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

pub const CLOSURE_MANIFEST_RELATIVE_PATH: &str = "manifests/training-dependency-closure.json";
const CLOSURE_MANIFEST_SCHEMA_VERSION: &str = "ember-training-dependency-closure-v1";
const TRAINING_CONFIG_RELATIVE_PATH: &str = "configs/ember-restart-3b.json";
const TOKENIZER_RELATIVE_PATH: &str = "domains/model/tokenizer/tokenizer.json";
const INPUT_IDENTITY_SCHEMA_VERSION: &str = "ember-input-identity-v1";
const PRODUCTION_RUNG_ARTIFACT_ID: &str = "owned-four-domain-production-rung-v1";
// Mirrors tools/ember-restart-3b/production_rung.py's SHARD_RELATIVE/RECEIPT_RELATIVE
// constants -- ported by literal value, not by executing Python, exactly as this module's
// docstring above scopes the port (declaration+hash half only, no Python execution).
const PRODUCTION_RUNG_SHARD_RELATIVE: &str =
    "data/ember-restart-3b/owned-four-domain-production-rung-v1.json";
const PRODUCTION_RUNG_RECEIPT_RELATIVE: &str =
    "data/ember-restart-3b/owned-four-domain-production-rung-v1.receipt.json";

#[derive(Debug)]
pub enum TrainingVerifyError {
    Io(std::io::Error),
    Json(serde_json::Error),
    Manifest(String),
}

impl fmt::Display for TrainingVerifyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for TrainingVerifyError {}
impl From<std::io::Error> for TrainingVerifyError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
impl From<serde_json::Error> for TrainingVerifyError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

pub type Result<T> = std::result::Result<T, TrainingVerifyError>;

#[derive(Debug, Clone, Deserialize)]
pub struct ClosureManifest {
    pub schema_version: String,
    pub entrypoints: Vec<String>,
    pub dynamic_entrypoints: Vec<String>,
    pub code: Vec<String>,
    pub data: Vec<String>,
}

/// Load and shape-check the closure manifest at `root` -- the single declaration both this
/// module and `src/ember/governance/scripts/training_closure.py::load_manifest` read; a file entering the
/// closure is picked up here automatically the next time this runs (#1400 acceptance 1:
/// "derived from the #1332 closure definition, not hand-listed").
pub fn load_manifest(root: &Path) -> Result<ClosureManifest> {
    let path = root.join(CLOSURE_MANIFEST_RELATIVE_PATH);
    let bytes = fs::read(&path)?;
    let manifest: ClosureManifest = serde_json::from_slice(&bytes)?;
    if manifest.schema_version != CLOSURE_MANIFEST_SCHEMA_VERSION {
        return Err(TrainingVerifyError::Manifest(format!(
            "training dependency closure manifest schema_version mismatch: {}",
            manifest.schema_version
        )));
    }
    Ok(manifest)
}

/// Exactly `declared_paths()` in `src/ember/governance/scripts/training_closure.py`: the union of entrypoints,
/// dynamic_entrypoints, code, data, and the manifest's own relative path -- deduplicated and
/// sorted (Rust `String` `Ord` is byte-wise UTF-8, identical to Python's default string sort
/// for the ASCII repo-relative paths this manifest declares, so `BTreeSet` iteration order
/// matches Python's `sorted()` exactly).
pub fn declared_paths(manifest: &ClosureManifest) -> BTreeSet<String> {
    let mut set: BTreeSet<String> = BTreeSet::new();
    for group in [
        &manifest.entrypoints,
        &manifest.dynamic_entrypoints,
        &manifest.code,
        &manifest.data,
    ] {
        for path in group {
            set.insert(path.clone());
        }
    }
    set.insert(CLOSURE_MANIFEST_RELATIVE_PATH.to_string());
    set
}

/// Every declared path absent from `root` -- mirrors `audit_closure`'s `missing` half only
/// (the reachability half stays Python-only; see module docstring).
pub fn missing_members(root: &Path, declared: &BTreeSet<String>) -> Vec<String> {
    declared
        .iter()
        .filter(|relative| !root.join(relative).is_file())
        .cloned()
        .collect()
}

/// Exactly `compute_closure_hash()` in `src/ember/governance/scripts/training_closure.py`: sha256 over sorted
/// `"<relpath>\0<sha256(bytes)>\n"` records. Byte-parity with the Python implementation is
/// load-bearing -- the certificate's `closure_sha256` must mean the same thing regardless of
/// which implementation computed it -- and is pinned by a committed golden fixture plus a
/// python-shell-out test (see `tests/`), not asserted by inspection alone.
pub fn compute_closure_hash(root: &Path, declared: &BTreeSet<String>) -> Result<String> {
    let mut digest = Sha256::new();
    for relative in declared {
        let path = root.join(relative);
        let bytes = fs::read(&path).map_err(|error| {
            TrainingVerifyError::Manifest(format!(
                "training dependency closure file is unreadable: {relative}: {error}"
            ))
        })?;
        let file_sha256 = format!("{:x}", Sha256::digest(&bytes));
        digest.update(format!("{relative}\0{file_sha256}\n").as_bytes());
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn sha256_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path)?;
    Ok(format!("{:x}", Sha256::digest(&bytes)))
}

fn require_str<'a>(value: &'a Value, key: &str, what: &str) -> Result<&'a str> {
    value.get(key).and_then(Value::as_str).ok_or_else(|| {
        TrainingVerifyError::Manifest(format!("{what} missing or not a string: {key}"))
    })
}

#[derive(Debug, Clone, Serialize)]
pub struct InputIdentityResult {
    pub artifact_id: String,
    pub identity_manifest_path: String,
    pub shard_path: String,
    pub shard_sha256: String,
    pub shard_bytes: u64,
    pub admission_receipt_path: Option<String>,
    pub admission_receipt_sha256: Option<String>,
}

/// Ports `tools/ember-restart-3b/input_identity.py::resolve_input_identity` -- scoped to the
/// one `artifact_id` the repo currently declares (`owned-four-domain-production-rung-v1`);
/// a new artifact_id grows a new arm here exactly as the Python source would grow a new
/// `if artifact_id == "...":` block. Never executes Python; the production-rung path
/// constants are ported by literal value (see module-level consts).
pub fn resolve_input_identity(root: &Path) -> Result<InputIdentityResult> {
    let config_path = root.join(TRAINING_CONFIG_RELATIVE_PATH);
    let config: Value = serde_json::from_slice(&fs::read(&config_path)?)?;
    let training = config.get("training").ok_or_else(|| {
        TrainingVerifyError::Manifest("training config lacks a training object".into())
    })?;
    let identity_manifest_relative =
        require_str(training, "input_identity_manifest", "training config")?.to_string();
    let expected_artifact_id =
        require_str(training, "expected_input_artifact_id", "training config")?.to_string();

    let identity_manifest_path = root.join(&identity_manifest_relative);
    let identity: Value = serde_json::from_slice(&fs::read(&identity_manifest_path)?)?;
    if identity.get("schema_version").and_then(Value::as_str) != Some(INPUT_IDENTITY_SCHEMA_VERSION)
    {
        return Err(TrainingVerifyError::Manifest(
            "input identity schema is not admitted".into(),
        ));
    }
    let artifact_id = require_str(&identity, "artifact_id", "input identity manifest")?.to_string();
    if artifact_id != expected_artifact_id {
        return Err(TrainingVerifyError::Manifest(
            "input artifact identity does not match the training config contract".into(),
        ));
    }

    let shard_relative =
        require_str(&identity, "shard_path", "input identity manifest")?.to_string();
    let shard_path = root.join(&shard_relative);
    let actual_shard_sha256 = sha256_file(&shard_path)?;
    let actual_shard_bytes = fs::metadata(&shard_path)?.len();
    let expected_shard_sha256 = require_str(&identity, "sha256", "input identity manifest")?;
    if actual_shard_sha256 != expected_shard_sha256 {
        return Err(TrainingVerifyError::Manifest(
            "shard content hash differs from the selected identity (byte_drift)".into(),
        ));
    }
    let expected_shard_bytes = identity
        .get("bytes")
        .and_then(Value::as_u64)
        .ok_or_else(|| {
            TrainingVerifyError::Manifest("input identity manifest bytes field missing".into())
        })?;
    if actual_shard_bytes != expected_shard_bytes {
        return Err(TrainingVerifyError::Manifest(
            "shard byte count differs from the selected identity (byte_drift)".into(),
        ));
    }

    let mut admission_receipt_path = None;
    let mut admission_receipt_sha256 = None;
    if artifact_id == PRODUCTION_RUNG_ARTIFACT_ID {
        if shard_relative != PRODUCTION_RUNG_SHARD_RELATIVE {
            return Err(TrainingVerifyError::Manifest(
                "production rung identity does not bind the canonical owned shard".into(),
            ));
        }
        let receipt_relative = require_str(
            &identity,
            "admission_receipt_path",
            "input identity manifest",
        )?
        .to_string();
        if receipt_relative != PRODUCTION_RUNG_RECEIPT_RELATIVE {
            return Err(TrainingVerifyError::Manifest(
                "production rung identity lacks the canonical admission receipt".into(),
            ));
        }
        let expected_receipt_sha256 = require_str(
            &identity,
            "admission_receipt_sha256",
            "input identity manifest",
        )?;
        let actual_receipt_sha256 = sha256_file(&root.join(&receipt_relative))?;
        if actual_receipt_sha256 != expected_receipt_sha256 {
            return Err(TrainingVerifyError::Manifest(
                "production rung receipt hash differs from the selected identity (byte_drift)"
                    .into(),
            ));
        }
        admission_receipt_path = Some(receipt_relative);
        admission_receipt_sha256 = Some(actual_receipt_sha256);
    }

    Ok(InputIdentityResult {
        artifact_id,
        identity_manifest_path: identity_manifest_relative,
        shard_path: shard_relative,
        shard_sha256: actual_shard_sha256,
        shard_bytes: actual_shard_bytes,
        admission_receipt_path,
        admission_receipt_sha256,
    })
}

#[derive(Debug, Clone, Serialize)]
pub struct ModelTokenizerResult {
    pub tokenizer_sha256: String,
    pub config_sha256: String,
}

pub fn resolve_model_tokenizer(root: &Path) -> Result<ModelTokenizerResult> {
    Ok(ModelTokenizerResult {
        tokenizer_sha256: sha256_file(&root.join(TOKENIZER_RELATIVE_PATH))?,
        config_sha256: sha256_file(&root.join(TRAINING_CONFIG_RELATIVE_PATH))?,
    })
}

#[derive(Debug, Clone, Serialize)]
pub struct CertificateCheckResult {
    pub path: String,
    pub closure_sha256_matches: bool,
    pub pin_is_ancestor: bool,
}

fn validate_public_master_sha(public_master_sha: &str) -> Result<()> {
    let is_lower_hex_commit = public_master_sha.len() == 40
        && public_master_sha
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte));
    if !is_lower_hex_commit {
        return Err(TrainingVerifyError::Manifest(
            "certificate public_master_sha must be exactly 40 lowercase hexadecimal bytes".into(),
        ));
    }
    Ok(())
}

/// `git_program` is named explicitly rather than resolved from `PATH` so tests
/// can point at a stub by absolute path. Installing a stub on `PATH` instead
/// would mean `set_var("PATH")`, which is process-global: unit tests share one
/// process, so it strips the real `PATH` from every test spawning a child
/// concurrently.
fn local_git_pin_is_ancestor(
    root: &Path,
    public_master_sha: &str,
    git_program: &Path,
) -> Result<bool> {
    validate_public_master_sha(public_master_sha)?;
    let output = Command::new(git_program)
        .arg("-C")
        .arg(root)
        .args(["merge-base", "--is-ancestor", public_master_sha, "HEAD"])
        .env("GIT_OPTIONAL_LOCKS", "0")
        .output()?;
    Ok(output.status.success())
}

/// The certificate's `closure_sha256` must equal the live-computed hash, and its
/// `public_master_sha` must be an ancestor of live HEAD -- exactly the two checks
/// `tools/ember-restart-3b/certified_train_launch.py::validate_certified_request` makes for
/// a closure-carrying certificate. The `git merge-base --is-ancestor` call is the only
/// subprocess this module ever spawns: local-object-graph only, `GIT_OPTIONAL_LOCKS=0` set,
/// never a fetch/ls-remote/gh call.
pub fn check_certificate(
    root: &Path,
    certificate_path: &Path,
    live_closure_sha256: &str,
) -> Result<CertificateCheckResult> {
    check_certificate_with(
        root,
        certificate_path,
        live_closure_sha256,
        Path::new("git"),
    )
}

pub(crate) fn check_certificate_with(
    root: &Path,
    certificate_path: &Path,
    live_closure_sha256: &str,
    git_program: &Path,
) -> Result<CertificateCheckResult> {
    let certificate: Value = serde_json::from_slice(&fs::read(certificate_path)?)?;
    let certificate_closure_sha256 = certificate
        .get("closure_sha256")
        .and_then(Value::as_str)
        .unwrap_or("");
    let closure_sha256_matches = certificate_closure_sha256 == live_closure_sha256;

    let public_master_sha = certificate
        .get("public_master_sha")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            TrainingVerifyError::Manifest("certificate lacks public_master_sha".into())
        })?;

    let pin_is_ancestor = local_git_pin_is_ancestor(root, public_master_sha, git_program)?;

    Ok(CertificateCheckResult {
        path: certificate_path.to_string_lossy().into_owned(),
        closure_sha256_matches,
        pin_is_ancestor,
    })
}

pub struct TrainingVerifyOutcome {
    pub ok: bool,
    pub receipt: Value,
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

/// Top-level entry point: run every check and assemble the
/// `ember-lab-training-verify-receipt-v1` receipt. `ember_lab_binary_sha256` /
/// `ember_lab_source_sha256` are passed in from the caller (the daemon's own self-identity
/// hashing, reused here for the same provenance discipline applied to a one-shot command).
pub fn run(
    root: &Path,
    certificate_path: Option<&Path>,
    ember_lab_binary_sha256: &str,
    ember_lab_source_sha256: &str,
) -> Result<TrainingVerifyOutcome> {
    let started_at_ms = now_ms();
    let mut checks: Vec<Value> = Vec::new();
    let mut ok = true;

    let manifest = load_manifest(root)?;
    let declared = declared_paths(&manifest);
    let missing = missing_members(root, &declared);
    let closure_complete = missing.is_empty();
    checks.push(json!({
        "name": "closure_members_present",
        "ok": closure_complete,
        "detail": if closure_complete {
            format!("{} declared files present", declared.len())
        } else {
            format!("missing: {}", missing.join(", "))
        },
    }));
    ok = ok && closure_complete;

    let closure_sha256 = if closure_complete {
        compute_closure_hash(root, &declared)?
    } else {
        String::new()
    };

    let input_identity = resolve_input_identity(root);
    checks.push(json!({
        "name": "input_identity_admission_chain",
        "ok": input_identity.is_ok(),
        "detail": match &input_identity {
            Ok(result) => format!("artifact_id={}", result.artifact_id),
            Err(error) => error.to_string(),
        },
    }));
    ok = ok && input_identity.is_ok();

    let model_tokenizer = resolve_model_tokenizer(root);
    checks.push(json!({
        "name": "model_tokenizer_identity",
        "ok": model_tokenizer.is_ok(),
        "detail": match &model_tokenizer {
            Ok(_) => "tokenizer and config hashed".to_string(),
            Err(error) => error.to_string(),
        },
    }));
    ok = ok && model_tokenizer.is_ok();

    let certificate = match certificate_path {
        Some(path) if closure_complete => {
            let result = check_certificate(root, path, &closure_sha256);
            let check_ok = result
                .as_ref()
                .map(|r| r.closure_sha256_matches && r.pin_is_ancestor)
                .unwrap_or(false);
            checks.push(json!({
                "name": "certificate_closure_and_pin",
                "ok": check_ok,
                "detail": match &result {
                    Ok(r) => format!(
                        "closure_sha256_matches={} pin_is_ancestor={}",
                        r.closure_sha256_matches, r.pin_is_ancestor
                    ),
                    Err(error) => error.to_string(),
                },
            }));
            ok = ok && check_ok;
            result.ok()
        }
        Some(_) => {
            checks.push(json!({
                "name": "certificate_closure_and_pin",
                "ok": false,
                "detail": "skipped: closure was incomplete",
            }));
            ok = false;
            None
        }
        None => None,
    };

    let finished_at_ms = now_ms();
    let receipt = json!({
        "schema_version": "ember-lab-training-verify-receipt-v1",
        "ok": ok,
        "root": root.to_string_lossy(),
        "started_at_ms": started_at_ms,
        "finished_at_ms": finished_at_ms,
        "duration_ms": finished_at_ms - started_at_ms,
        "closure": {
            "declared_files": declared.len(),
            "closure_sha256": closure_sha256,
        },
        "input_identity": input_identity.as_ref().ok().map(|r| json!({
            "artifact_id": r.artifact_id,
            "identity_manifest_path": r.identity_manifest_path,
            "shard_path": r.shard_path,
            "shard_sha256": r.shard_sha256,
            "shard_bytes": r.shard_bytes,
            "admission_receipt_path": r.admission_receipt_path,
            "admission_receipt_sha256": r.admission_receipt_sha256,
        })),
        "model_tokenizer": model_tokenizer.as_ref().ok().map(|r| json!({
            "tokenizer_sha256": r.tokenizer_sha256,
            "config_sha256": r.config_sha256,
        })),
        "certificate": certificate.map(|c| json!({
            "path": c.path,
            "closure_sha256_matches": c.closure_sha256_matches,
            "pin_is_ancestor": c.pin_is_ancestor,
        })),
        "checks": checks,
        "ember_lab_binary_sha256": ember_lab_binary_sha256,
        "ember_lab_source_sha256": ember_lab_source_sha256,
    });

    Ok(TrainingVerifyOutcome { ok, receipt })
}

pub fn write_receipt(path: &Path, receipt: &Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(receipt)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsString;
    use std::fs;
    use std::path::PathBuf;
    use std::process::Command;
    const VALID_PUBLIC_MASTER_SHA: &str = "3ceada9dbf6b13b6153798a5fafc718ee052942d";

    /// Compiles a `git` stub that records its argv, and returns its absolute
    /// path for injection via `check_certificate_with`.
    ///
    /// Everything the stub needs is baked into its source at compile time. The
    /// earlier version passed this config through `EMBER_TEST_GIT_*` env vars
    /// and put the stub on `PATH`, both via `set_var` -- process-global writes
    /// that every concurrently-running unit test in this binary inherited,
    /// leaving them unable to resolve any program on the real `PATH`.
    fn build_recording_git_stub(tmp: &Path, root: &Path) -> PathBuf {
        let stub_source = tmp.join("git-stub.rs");
        let stub_exe = tmp.join(if cfg!(windows) { "git.exe" } else { "git" });
        let log = tmp.join("git-argv.log");
        write(
            &stub_source,
            format!(
                r#"use std::fs;
fn main() {{
    let args: Vec<String> = std::env::args().skip(1).collect();
    fs::write({log:?}, args.join("\n")).unwrap();
    let expected = vec!["-C", {root:?}, "merge-base", "--is-ancestor", {sha:?}, "HEAD"];
    if args.iter().map(String::as_str).eq(expected) {{
        std::process::exit(0);
    }}
    std::process::exit(97);
}}
"#,
                log = log.to_string_lossy(),
                root = root.to_string_lossy(),
                sha = VALID_PUBLIC_MASTER_SHA,
            )
            .as_bytes(),
        );
        let rustc = std::env::var_os("RUSTC").unwrap_or_else(|| OsString::from("rustc"));
        let status = Command::new(rustc)
            .arg(&stub_source)
            .arg("-o")
            .arg(&stub_exe)
            .status()
            .expect("recording git stub must compile");
        assert!(status.success(), "recording git stub compilation failed");

        stub_exe
    }

    fn write_certificate(path: &Path, public_master_sha: &str) {
        let certificate = json!({
            "closure_sha256": "closure",
            "public_master_sha": public_master_sha,
        });
        write(path, &serde_json::to_vec(&certificate).unwrap());
    }

    fn write(path: &Path, bytes: &[u8]) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, bytes).unwrap();
    }

    fn minimal_tree(tmp: &Path) {
        write(
            &tmp.join(CLOSURE_MANIFEST_RELATIVE_PATH),
            br#"{
  "schema_version": "ember-training-dependency-closure-v1",
  "entrypoints": ["a.py"],
  "dynamic_entrypoints": [],
  "code": ["b.py"],
  "data": ["c.json"]
}"#,
        );
        write(&tmp.join("a.py"), b"print('a')\n");
        write(&tmp.join("b.py"), b"print('b')\n");
        write(&tmp.join("c.json"), b"{}");
    }

    #[test]
    fn declared_paths_includes_manifest_itself() {
        let manifest = ClosureManifest {
            schema_version: CLOSURE_MANIFEST_SCHEMA_VERSION.to_string(),
            entrypoints: vec!["a.py".to_string()],
            dynamic_entrypoints: vec![],
            code: vec!["b.py".to_string()],
            data: vec!["c.json".to_string()],
        };
        let declared = declared_paths(&manifest);
        assert!(declared.contains(CLOSURE_MANIFEST_RELATIVE_PATH));
        assert_eq!(declared.len(), 4);
    }

    #[test]
    fn missing_member_is_reported_and_hash_fails_closed() {
        let tmp = std::env::temp_dir().join(format!("ember-lab-tv-missing-{}", now_ms()));
        minimal_tree(&tmp);
        fs::remove_file(tmp.join("b.py")).unwrap();
        let manifest = load_manifest(&tmp).unwrap();
        let declared = declared_paths(&manifest);
        let missing = missing_members(&tmp, &declared);
        assert_eq!(missing, vec!["b.py".to_string()]);
        assert!(compute_closure_hash(&tmp, &declared).is_err());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn closure_hash_is_deterministic_across_runs() {
        let tmp = std::env::temp_dir().join(format!("ember-lab-tv-det-{}", now_ms()));
        minimal_tree(&tmp);
        let manifest = load_manifest(&tmp).unwrap();
        let declared = declared_paths(&manifest);
        let first = compute_closure_hash(&tmp, &declared).unwrap();
        let second = compute_closure_hash(&tmp, &declared).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.len(), 64);
        let _ = fs::remove_dir_all(&tmp);
    }

    /// Golden-fixture parity pin (team-lead ruling 2026-08-04): a committed expected hash
    /// for a small, STABLE synthetic tree (never the live repo manifest, which changes with
    /// production data), so `cargo test --lib` -- the exact step `ci-pr.yml` already runs
    /// for ember-lab -- catches a `compute_closure_hash` algorithm change with no python
    /// dependency and no network. The companion python-shell-out parity test
    /// (`tests/training_closure_python_parity.rs`) is the second, slower half of the pin:
    /// it catches the case where this golden value itself drifted out of sync with a real
    /// `src/ember/governance/scripts/training_closure.py` edit that nobody regenerated it for.
    #[test]
    fn closure_hash_matches_committed_golden_fixture() {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let golden_path = manifest_dir.join("tests/fixtures/training-closure-golden.json");
        let golden: Value = serde_json::from_slice(&fs::read(&golden_path).unwrap()).unwrap();
        let fixture_root = manifest_dir.join(
            golden
                .get("fixture_root")
                .and_then(Value::as_str)
                .expect("golden fixture must declare fixture_root"),
        );
        let expected_hash = golden
            .get("expected_closure_sha256")
            .and_then(Value::as_str)
            .expect("golden fixture must declare expected_closure_sha256");
        let expected_declared: Vec<String> = golden
            .get("declared_files")
            .and_then(Value::as_array)
            .expect("golden fixture must declare declared_files")
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();

        let manifest = load_manifest(&fixture_root).unwrap();
        let declared = declared_paths(&manifest);
        let declared_vec: Vec<String> = declared.iter().cloned().collect();
        assert_eq!(
            declared_vec, expected_declared,
            "declared closure set drifted from the golden fixture"
        );
        assert!(missing_members(&fixture_root, &declared).is_empty());
        let actual_hash = compute_closure_hash(&fixture_root, &declared).unwrap();
        assert_eq!(
            actual_hash, expected_hash,
            "closure hash drifted from the committed golden fixture -- if this is an \
             INTENTIONAL algorithm change (in this module or src/ember/governance/scripts/training_closure.py), \
             regenerate per tests/fixtures/training-closure-golden.json's own _comment; \
             otherwise this is a real byte-parity regression"
        );
    }

    #[test]
    fn certificate_ancestor_check_invokes_only_the_local_git_allowlist() {
        let tmp = std::env::temp_dir().join(format!("ember-lab-tv-git-ok-{}", now_ms()));
        fs::create_dir_all(&tmp).unwrap();
        let root = tmp.join("repo");
        fs::create_dir_all(&root).unwrap();
        let certificate = tmp.join("certificate.json");
        write_certificate(&certificate, VALID_PUBLIC_MASTER_SHA);
        let git_stub = build_recording_git_stub(&tmp, &root);

        let result = check_certificate_with(&root, &certificate, "closure", &git_stub).unwrap();

        assert!(result.closure_sha256_matches);
        assert!(result.pin_is_ancestor);
        let argv = fs::read_to_string(tmp.join("git-argv.log")).unwrap();
        assert_eq!(
            argv,
            format!(
                "-C\n{}\nmerge-base\n--is-ancestor\n{}\nHEAD",
                root.display(),
                VALID_PUBLIC_MASTER_SHA
            )
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn certificate_rejects_network_or_option_like_pin_before_git_spawn() {
        for (case, invalid_pin) in [
            ("url", "https://example.invalid/ember.git"),
            ("option", "--upload-pack=https://example.invalid/escape"),
        ] {
            let tmp = std::env::temp_dir().join(format!("ember-lab-tv-git-{case}-{}", now_ms()));
            fs::create_dir_all(&tmp).unwrap();
            let root = tmp.join("repo");
            fs::create_dir_all(&root).unwrap();
            let certificate = tmp.join("certificate.json");
            write_certificate(&certificate, invalid_pin);
            let git_stub = build_recording_git_stub(&tmp, &root);

            let result = check_certificate_with(&root, &certificate, "closure", &git_stub);

            assert!(
                matches!(result, Err(TrainingVerifyError::Manifest(_))),
                "{case} pin must fail validation before spawning git: {result:?}"
            );
            assert!(
                !tmp.join("git-argv.log").exists(),
                "{case} pin reached the git subprocess"
            );
            let _ = fs::remove_dir_all(&tmp);
        }
    }
}
