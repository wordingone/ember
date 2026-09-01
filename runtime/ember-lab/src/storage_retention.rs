// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! Pure, mutation-free policy, census, and planning core for daemon-owned storage retention.
//!
//! This module deliberately stops before filesystem mutation.  The executor may consume a
//! [`StoragePlan`] only after durably publishing it and must re-open every [`PlanRow`] identity
//! immediately before quarantine.  Keeping the parser and planner pure makes every deliberate-red
//! refusal reproducible without touching operator custody.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const POLICY_SCHEMA: &str = "ember-storage-retention-policy-v1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlanError {
    Policy(String),
    DuplicatePath(String),
    RefusalRows(Vec<String>),
    ProtectedBytesExceedQuota {
        class: CustodyClass,
        protected_bytes: u64,
        hard_quota_bytes: u64,
    },
    InsufficientEligibleBytes {
        class: CustodyClass,
        required_bytes: u64,
        eligible_bytes: u64,
        maximum_reconcile_bytes: u64,
    },
    InvalidIdentity(String),
    ArithmeticOverflow,
    Serialization(String),
}

impl fmt::Display for PlanError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Policy(detail) => write!(f, "storage policy refused: {detail}"),
            Self::DuplicatePath(path) => write!(f, "duplicate census path: {path}"),
            Self::RefusalRows(rows) => write!(f, "storage census contains refusal rows: {}", rows.join(", ")),
            Self::ProtectedBytesExceedQuota { class, protected_bytes, hard_quota_bytes } => write!(
                f,
                "{class} protected bytes {protected_bytes} exceed hard quota {hard_quota_bytes}"
            ),
            Self::InsufficientEligibleBytes {
                class,
                required_bytes,
                eligible_bytes,
                maximum_reconcile_bytes,
            } => write!(
                f,
                "{class} requires {required_bytes} reclaimable bytes, has {eligible_bytes}, maximum reconciliation {maximum_reconcile_bytes}"
            ),
            Self::InvalidIdentity(detail) => write!(f, "invalid storage identity: {detail}"),
            Self::ArithmeticOverflow => write!(f, "storage byte accounting overflowed"),
            Self::Serialization(detail) => write!(f, "storage receipt serialization failed: {detail}"),
        }
    }
}

impl std::error::Error for PlanError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CustodyClass {
    Models,
    State,
}

impl fmt::Display for CustodyClass {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Models => write!(f, "models"),
            Self::State => write!(f, "state"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClassPolicy {
    pub class: CustodyClass,
    pub canonical_root: String,
    pub filing_total_bytes: u64,
    pub protected_lower_bound_bytes: u64,
    pub admitted_growth_envelope_bytes: u64,
    pub hard_quota_bytes: u64,
    pub keep_last_n: Option<u64>,
    pub protected_predicates: Vec<String>,
    pub eligibility_predicates: Vec<String>,
    pub compression_rule: String,
    pub grace_seconds: u64,
    pub maximum_reconcile_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoragePolicy {
    pub schema_version: String,
    pub filing_source_commit: String,
    pub classes: Vec<ClassPolicy>,
    #[serde(skip)]
    pub raw_sha256: String,
}

pub fn parse_policy(raw: &[u8]) -> Result<StoragePolicy, PlanError> {
    let mut policy: StoragePolicy =
        serde_json::from_slice(raw).map_err(|error| PlanError::Policy(error.to_string()))?;
    if policy.schema_version != POLICY_SCHEMA {
        return Err(PlanError::Policy(format!(
            "schema_version must be {POLICY_SCHEMA}"
        )));
    }
    if !is_lower_hex(&policy.filing_source_commit, 40) {
        return Err(PlanError::Policy(
            "filing_source_commit must be lowercase 40-hex".into(),
        ));
    }
    let classes: Vec<_> = policy.classes.iter().map(|item| item.class).collect();
    if classes != [CustodyClass::Models, CustodyClass::State] {
        return Err(PlanError::Policy(
            "classes must contain exactly models and state in canonical order".into(),
        ));
    }
    let roots: Vec<_> = policy
        .classes
        .iter()
        .map(|item| normalize_root(&item.canonical_root))
        .collect::<Result<_, _>>()?;
    if roots_overlap(&roots[0], &roots[1]) {
        return Err(PlanError::Policy(
            "canonical roots overlap or are identical".into(),
        ));
    }
    for item in &policy.classes {
        validate_class_policy(item)?;
    }
    policy.raw_sha256 = sha256_hex(raw);
    Ok(policy)
}

fn validate_class_policy(item: &ClassPolicy) -> Result<(), PlanError> {
    if item.filing_total_bytes == 0
        || item.protected_lower_bound_bytes == 0
        || item.maximum_reconcile_bytes == 0
        || item.grace_seconds == 0
    {
        return Err(PlanError::Policy(format!(
            "{} byte, grace, and reconciliation fields must be positive",
            item.class
        )));
    }
    if item.class == CustodyClass::Models && item.keep_last_n.unwrap_or(0) == 0 {
        return Err(PlanError::Policy(
            "models keep_last_n must be positive".into(),
        ));
    }
    if item.class == CustodyClass::State && item.keep_last_n.is_some() {
        return Err(PlanError::Policy("state keep_last_n must be null".into()));
    }
    let expected_protected: &[&str] = match item.class {
        CustodyClass::Models => &[
            "active_process_root",
            "open_run_custody",
            "nonterminal_attempt",
            "registered_campaign_evidence",
            "independently_pinned_checkpoint",
            "receipt_dependency",
            "sole_verified_copy",
        ],
        CustodyClass::State => &[
            "active_process_root",
            "open_run_custody",
            "nonterminal_attempt",
            "registered_campaign_evidence",
            "receipt_dependency",
        ],
    };
    let expected_eligible: &[&str] = match item.class {
        CustodyClass::Models => &["reproducible", "verified_duplicate_copy"],
        CustodyClass::State => &["reproducible", "terminal_receipt_kernel"],
    };
    if item
        .protected_predicates
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        != expected_protected
    {
        return Err(PlanError::Policy(format!(
            "{} protected_predicates must match the canonical ordered set",
            item.class
        )));
    }
    if item
        .eligibility_predicates
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        != expected_eligible
    {
        return Err(PlanError::Policy(format!(
            "{} eligibility_predicates must match the canonical ordered set",
            item.class
        )));
    }
    let expected_compression = match item.class {
        CustodyClass::Models => "none",
        CustodyClass::State => "terminal_receipt_kernel_v1",
    };
    if item.compression_rule != expected_compression {
        return Err(PlanError::Policy(format!(
            "{} compression_rule must be {expected_compression}",
            item.class
        )));
    }
    let ten_percent = item
        .protected_lower_bound_bytes
        .checked_add(9)
        .ok_or(PlanError::ArithmeticOverflow)?
        / 10;
    let reserve = item.admitted_growth_envelope_bytes.max(ten_percent);
    let derived = item
        .protected_lower_bound_bytes
        .checked_add(reserve)
        .ok_or(PlanError::ArithmeticOverflow)?;
    if item.hard_quota_bytes != derived {
        return Err(PlanError::Policy(format!(
            "{} hard quota does not equal the independently derived quota",
            item.class
        )));
    }
    if item.hard_quota_bytes >= item.filing_total_bytes {
        return Err(PlanError::Policy(format!(
            "{} hard quota must be strictly below filing total",
            item.class
        )));
    }
    Ok(())
}

fn normalize_root(raw: &str) -> Result<String, PlanError> {
    if raw.is_empty() || raw.contains('\\') || Path::new(raw).is_absolute() {
        return Err(PlanError::Policy(
            "canonical roots must be non-empty repository-relative slash paths".into(),
        ));
    }
    let mut parts = Vec::new();
    for component in Path::new(raw).components() {
        match component {
            Component::Normal(part) => parts.push(part.to_string_lossy().into_owned()),
            _ => {
                return Err(PlanError::Policy(
                    "canonical roots may not contain dot or parent components".into(),
                ))
            }
        }
    }
    Ok(parts.join("/"))
}

fn roots_overlap(left: &str, right: &str) -> bool {
    left == right
        || left
            .strip_prefix(right)
            .is_some_and(|tail| tail.starts_with('/'))
        || right
            .strip_prefix(left)
            .is_some_and(|tail| tail.starts_with('/'))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    Protected,
    Reproducible,
    TerminalCompressible,
    DuplicateReclaimable,
    Unknown,
    PathEscape,
    ReparsePoint,
    HardlinkAmbiguous,
}

impl Disposition {
    fn is_refusal(self) -> bool {
        matches!(
            self,
            Self::Unknown | Self::PathEscape | Self::ReparsePoint | Self::HardlinkAmbiguous
        )
    }

    fn eligible(self) -> bool {
        matches!(
            self,
            Self::Reproducible | Self::TerminalCompressible | Self::DuplicateReclaimable
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CheckpointIdentity {
    pub series: String,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DuplicateWitness {
    pub retained_relative_path: String,
    pub retained_raw_sha256: String,
    pub retained_physical_identity: String,
    pub authority_identity: String,
    pub independently_reopened: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TerminalKernelWitness {
    pub retained_relative_path: String,
    pub retained_raw_sha256: String,
    pub receipt_identity: String,
    pub independently_reopened: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CensusRow {
    pub class: CustodyClass,
    pub relative_path: String,
    pub bytes: u64,
    pub raw_sha256: String,
    pub physical_identity: String,
    pub modified_ns: u64,
    pub disposition: Disposition,
    pub pin_reasons: Vec<String>,
    pub checkpoint: Option<CheckpointIdentity>,
    pub duplicate_witness: Option<DuplicateWitness>,
    pub terminal_kernel_witness: Option<TerminalKernelWitness>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CensusDeclaration {
    pub class: CustodyClass,
    pub relative_path: String,
    pub disposition: Disposition,
    pub pin_reasons: Vec<String>,
    pub checkpoint: Option<CheckpointIdentity>,
    pub duplicate_witness: Option<DuplicateWitness>,
    pub terminal_kernel_witness: Option<TerminalKernelWitness>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Census {
    pub observed_at_ns: u64,
    pub rows: Vec<CensusRow>,
    pub self_sha256: String,
}

#[derive(Serialize)]
struct CensusWithoutSelf<'a> {
    observed_at_ns: u64,
    rows: &'a [CensusRow],
}

impl Census {
    pub fn new(rows: Vec<CensusRow>) -> Result<Self, PlanError> {
        let observed_at_ns = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?
            .as_nanos()
            .try_into()
            .map_err(|_| PlanError::ArithmeticOverflow)?;
        Self::new_at(rows, observed_at_ns)
    }

    pub fn new_at(mut rows: Vec<CensusRow>, observed_at_ns: u64) -> Result<Self, PlanError> {
        if observed_at_ns == 0 {
            return Err(PlanError::InvalidIdentity(
                "census observation time must be positive".into(),
            ));
        }
        let mut seen = BTreeSet::new();
        let mut checkpoint_roots = BTreeMap::new();
        for row in &rows {
            validate_relative_path(&row.relative_path)?;
            if !is_lower_hex(&row.raw_sha256, 64) || row.physical_identity.trim().is_empty() {
                return Err(PlanError::InvalidIdentity(format!(
                    "{}:{} has invalid content or physical identity",
                    row.class, row.relative_path
                )));
            }
            if row
                .pin_reasons
                .iter()
                .any(|reason| reason.trim().is_empty())
            {
                return Err(PlanError::InvalidIdentity(format!(
                    "{}:{} contains an empty pin reason",
                    row.class, row.relative_path
                )));
            }
            if let Some(checkpoint) = &row.checkpoint {
                if row.class != CustodyClass::Models
                    || checkpoint.series.trim().is_empty()
                    || checkpoint.sequence == 0
                {
                    return Err(PlanError::InvalidIdentity(format!(
                        "{}:{} has invalid checkpoint identity",
                        row.class, row.relative_path
                    )));
                }
                let checkpoint_root = Path::new(&row.relative_path)
                    .parent()
                    .filter(|path| !path.as_os_str().is_empty())
                    .ok_or_else(|| {
                        PlanError::InvalidIdentity(format!(
                            "{}:{} checkpoint row has no checkpoint directory",
                            row.class, row.relative_path
                        ))
                    })?
                    .to_string_lossy()
                    .replace('\\', "/");
                let identity = (checkpoint.series.clone(), checkpoint.sequence);
                if checkpoint_roots
                    .get(&identity)
                    .is_some_and(|existing| existing != &checkpoint_root)
                {
                    return Err(PlanError::InvalidIdentity(format!(
                        "checkpoint sequence {}:{} spans multiple directories",
                        checkpoint.series, checkpoint.sequence
                    )));
                }
                checkpoint_roots.insert(identity, checkpoint_root);
            }
            match (row.disposition, &row.duplicate_witness) {
                (Disposition::DuplicateReclaimable, Some(witness))
                    if witness.independently_reopened
                        && witness.retained_raw_sha256 == row.raw_sha256
                        && witness.retained_physical_identity != row.physical_identity
                        && !witness.authority_identity.trim().is_empty() =>
                {
                    validate_relative_path(&witness.retained_relative_path)?;
                }
                (Disposition::DuplicateReclaimable, _) => {
                    return Err(PlanError::InvalidIdentity(format!(
                        "{}:{} lacks an independently reopened duplicate witness",
                        row.class, row.relative_path
                    )));
                }
                (_, Some(_)) => {
                    return Err(PlanError::InvalidIdentity(format!(
                        "{}:{} carries a duplicate witness for a non-duplicate disposition",
                        row.class, row.relative_path
                    )));
                }
                (_, None) => {}
            }
            match (row.disposition, &row.terminal_kernel_witness) {
                (Disposition::TerminalCompressible, Some(witness))
                    if witness.independently_reopened
                        && is_lower_hex(&witness.retained_raw_sha256, 64)
                        && !witness.receipt_identity.trim().is_empty() =>
                {
                    validate_relative_path(&witness.retained_relative_path)?;
                }
                (Disposition::TerminalCompressible, _) => {
                    return Err(PlanError::InvalidIdentity(format!(
                        "{}:{} lacks an independently reopened terminal kernel witness",
                        row.class, row.relative_path
                    )));
                }
                (_, Some(_)) => {
                    return Err(PlanError::InvalidIdentity(format!(
                        "{}:{} carries a terminal kernel witness for a non-terminal disposition",
                        row.class, row.relative_path
                    )));
                }
                (_, None) => {}
            }
            let identity = (row.class, row.relative_path.to_lowercase());
            if !seen.insert(identity) {
                return Err(PlanError::DuplicatePath(format!(
                    "{}:{}",
                    row.class, row.relative_path
                )));
            }
        }
        for row in &rows {
            let Some(witness) = &row.duplicate_witness else {
                continue;
            };
            let retained = rows.iter().find(|candidate| {
                candidate.class == row.class
                    && candidate.relative_path == witness.retained_relative_path
            });
            if retained.is_none_or(|candidate| {
                candidate.raw_sha256 != witness.retained_raw_sha256
                    || candidate.physical_identity != witness.retained_physical_identity
                    || candidate.bytes != row.bytes
            }) {
                return Err(PlanError::InvalidIdentity(format!(
                    "{}:{} duplicate witness does not bind a matching retained row",
                    row.class, row.relative_path
                )));
            }
        }
        for row in &rows {
            let Some(witness) = &row.terminal_kernel_witness else {
                continue;
            };
            let retained = rows.iter().find(|candidate| {
                candidate.class == CustodyClass::State
                    && candidate.relative_path == witness.retained_relative_path
            });
            let expected_pin = format!("terminal_receipt_kernel:{}", witness.receipt_identity);
            if row.class != CustodyClass::State
                || retained.is_none_or(|candidate| {
                    candidate.raw_sha256 != witness.retained_raw_sha256
                        || candidate.disposition != Disposition::Protected
                        || !candidate.pin_reasons.contains(&expected_pin)
                })
            {
                return Err(PlanError::InvalidIdentity(format!(
                    "{}:{} terminal kernel witness does not bind a protected receipt-pinned row",
                    row.class, row.relative_path
                )));
            }
        }
        rows.sort_by(|left, right| {
            (left.class, &left.relative_path).cmp(&(right.class, &right.relative_path))
        });
        let self_sha256 = canonical_json_sha256(&CensusWithoutSelf {
            observed_at_ns,
            rows: &rows,
        })?;
        Ok(Self {
            observed_at_ns,
            rows,
            self_sha256,
        })
    }
}

pub fn census_filesystem(
    roots: &BTreeMap<CustodyClass, PathBuf>,
    declarations: Vec<CensusDeclaration>,
) -> Result<Census, PlanError> {
    let mut declared = BTreeMap::new();
    for declaration in declarations {
        validate_relative_path(&declaration.relative_path)?;
        let key = (declaration.class, declaration.relative_path.to_lowercase());
        if declared.insert(key, declaration).is_some() {
            return Err(PlanError::DuplicatePath(
                "duplicate case-folded census declaration".into(),
            ));
        }
    }
    let canonical_models = fs::canonicalize(
        roots
            .get(&CustodyClass::Models)
            .ok_or_else(|| PlanError::InvalidIdentity("missing models root".into()))?,
    )
    .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
    let canonical_state = fs::canonicalize(
        roots
            .get(&CustodyClass::State)
            .ok_or_else(|| PlanError::InvalidIdentity("missing state root".into()))?,
    )
    .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
    if canonical_models == canonical_state
        || canonical_models.starts_with(&canonical_state)
        || canonical_state.starts_with(&canonical_models)
    {
        return Err(PlanError::InvalidIdentity("census roots overlap".into()));
    }
    let mut rows = Vec::new();
    for class in [CustodyClass::Models, CustodyClass::State] {
        let root = roots
            .get(&class)
            .ok_or_else(|| PlanError::InvalidIdentity(format!("missing {class} root")))?;
        let canonical = fs::canonicalize(root)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
        if !canonical.is_dir() {
            return Err(PlanError::InvalidIdentity(format!(
                "{class} root is not a directory"
            )));
        }
        census_directory(class, &canonical, &canonical, &mut declared, &mut rows)?;
    }
    if let Some((_, missing)) = declared.into_iter().next() {
        return Err(PlanError::InvalidIdentity(format!(
            "declared census path is missing: {}:{}",
            missing.class, missing.relative_path
        )));
    }
    Census::new(rows)
}

fn census_directory(
    class: CustodyClass,
    root: &Path,
    directory: &Path,
    declarations: &mut BTreeMap<(CustodyClass, String), CensusDeclaration>,
    rows: &mut Vec<CensusRow>,
) -> Result<(), PlanError> {
    let entries =
        fs::read_dir(directory).map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
    for entry in entries {
        let path = entry
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?
            .path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
        let relative_path = path
            .strip_prefix(root)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?
            .to_string_lossy()
            .replace('\\', "/");
        if metadata.file_type().is_symlink() {
            rows.push(refusal_census_row(
                class,
                relative_path,
                metadata.len(),
                Disposition::ReparsePoint,
            ));
        } else if metadata.is_dir() {
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if metadata.file_attributes() & 0x400 != 0 {
                    rows.push(refusal_census_row(
                        class,
                        relative_path,
                        metadata.len(),
                        Disposition::ReparsePoint,
                    ));
                    continue;
                }
            }
            census_directory(class, root, &path, declarations, rows)?;
        } else if metadata.is_file() {
            let observation = observe_file(&path).map_err(|error| {
                PlanError::InvalidIdentity(format!("{class}:{relative_path}: {error}"))
            })?;
            let declaration = declarations.remove(&(class, relative_path.to_lowercase()));
            let disposition = if observation.link_count != 1 {
                Disposition::HardlinkAmbiguous
            } else {
                declaration
                    .as_ref()
                    .map_or(Disposition::Unknown, |item| item.disposition)
            };
            rows.push(CensusRow {
                class,
                relative_path,
                bytes: observation.bytes,
                raw_sha256: observation.raw_sha256,
                physical_identity: observation.physical_identity,
                modified_ns: observation.modified_ns,
                disposition,
                pin_reasons: declaration
                    .as_ref()
                    .map_or_else(Vec::new, |item| item.pin_reasons.clone()),
                checkpoint: declaration
                    .as_ref()
                    .and_then(|item| item.checkpoint.clone()),
                duplicate_witness: declaration
                    .as_ref()
                    .and_then(|item| item.duplicate_witness.clone()),
                terminal_kernel_witness: declaration
                    .as_ref()
                    .and_then(|item| item.terminal_kernel_witness.clone()),
            });
        } else {
            rows.push(refusal_census_row(
                class,
                relative_path,
                metadata.len(),
                Disposition::Unknown,
            ));
        }
    }
    Ok(())
}

fn refusal_census_row(
    class: CustodyClass,
    relative_path: String,
    bytes: u64,
    disposition: Disposition,
) -> CensusRow {
    CensusRow {
        class,
        physical_identity: format!("refusal:{disposition:?}:{relative_path}"),
        relative_path,
        bytes,
        raw_sha256: "0".repeat(64),
        modified_ns: 0,
        disposition,
        pin_reasons: Vec::new(),
        checkpoint: None,
        duplicate_witness: None,
        terminal_kernel_witness: None,
    }
}

fn validate_relative_path(path: &str) -> Result<(), PlanError> {
    if path.is_empty() || path.contains('\\') || Path::new(path).is_absolute() {
        return Err(PlanError::InvalidIdentity(format!(
            "unsafe relative path {path:?}"
        )));
    }
    for component in Path::new(path).components() {
        if !matches!(component, Component::Normal(_)) {
            return Err(PlanError::InvalidIdentity(format!(
                "unsafe relative path {path:?}"
            )));
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlanAction {
    Compress,
    PurgeAfterQuarantine,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanRow {
    pub class: CustodyClass,
    pub relative_path: String,
    pub bytes: u64,
    pub raw_sha256: String,
    pub physical_identity: String,
    pub modified_ns: u64,
    pub action: PlanAction,
    pub terminal_kernel_witness: Option<TerminalKernelWitness>,
}

impl PlanRow {
    pub fn matches_observation(
        &self,
        bytes: u64,
        raw_sha256: &str,
        physical_identity: &str,
        modified_ns: u64,
    ) -> bool {
        self.bytes == bytes
            && self.raw_sha256 == raw_sha256
            && self.physical_identity == physical_identity
            && self.modified_ns == modified_ns
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClassPlanSummary {
    pub before_bytes: u64,
    pub protected_bytes: u64,
    pub projected_growth_bytes: u64,
    pub selected_bytes: u64,
    pub projected_after_bytes: u64,
    pub hard_quota_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoragePlan {
    pub schema_version: String,
    pub policy_raw_sha256: String,
    pub census_self_sha256: String,
    pub pin_set_raw_sha256: String,
    pub current_master: String,
    pub classes: BTreeMap<CustodyClass, ClassPlanSummary>,
    pub rows: Vec<PlanRow>,
    pub kept_rows: Vec<CensusRow>,
    pub self_sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StoragePlanWithoutSelf {
    pub schema_version: String,
    pub policy_raw_sha256: String,
    pub census_self_sha256: String,
    pub pin_set_raw_sha256: String,
    pub current_master: String,
    pub classes: BTreeMap<CustodyClass, ClassPlanSummary>,
    pub rows: Vec<PlanRow>,
    pub kept_rows: Vec<CensusRow>,
}

impl StoragePlan {
    pub fn without_self_hash(&self) -> StoragePlanWithoutSelf {
        StoragePlanWithoutSelf {
            schema_version: self.schema_version.clone(),
            policy_raw_sha256: self.policy_raw_sha256.clone(),
            census_self_sha256: self.census_self_sha256.clone(),
            pin_set_raw_sha256: self.pin_set_raw_sha256.clone(),
            current_master: self.current_master.clone(),
            classes: self.classes.clone(),
            rows: self.rows.clone(),
            kept_rows: self.kept_rows.clone(),
        }
    }
}

pub fn build_plan(
    policy: &StoragePolicy,
    census: &Census,
    pin_set_raw_sha256: &str,
    current_master: &str,
) -> Result<StoragePlan, PlanError> {
    build_plan_for_growth(
        policy,
        census,
        pin_set_raw_sha256,
        current_master,
        &BTreeMap::from([(CustodyClass::Models, 0), (CustodyClass::State, 0)]),
    )
}

pub fn build_plan_for_growth(
    policy: &StoragePolicy,
    census: &Census,
    pin_set_raw_sha256: &str,
    current_master: &str,
    projected_growth: &BTreeMap<CustodyClass, u64>,
) -> Result<StoragePlan, PlanError> {
    if !is_lower_hex(pin_set_raw_sha256, 64) {
        return Err(PlanError::InvalidIdentity(
            "pin set must be lowercase SHA-256".into(),
        ));
    }
    if !is_lower_hex(current_master, 40) {
        return Err(PlanError::InvalidIdentity(
            "current master must be lowercase 40-hex".into(),
        ));
    }
    if projected_growth.len() != 2
        || !projected_growth.contains_key(&CustodyClass::Models)
        || !projected_growth.contains_key(&CustodyClass::State)
    {
        return Err(PlanError::Policy(
            "projected growth must name exactly models and state".into(),
        ));
    }
    let refusal_rows: Vec<_> = census
        .rows
        .iter()
        .filter(|row| row.disposition.is_refusal())
        .map(|row| format!("{}:{}:{:?}", row.class, row.relative_path, row.disposition))
        .collect();
    if !refusal_rows.is_empty() {
        return Err(PlanError::RefusalRows(refusal_rows));
    }

    let mut summaries = BTreeMap::new();
    let mut plan_rows = Vec::new();
    for class_policy in &policy.classes {
        let class_rows: Vec<_> = census
            .rows
            .iter()
            .filter(|row| row.class == class_policy.class)
            .collect();
        let before = sum_bytes(class_rows.iter().map(|row| row.bytes))?;
        let keep_last_paths = keep_last_paths(class_policy, &class_rows);
        let protected = sum_bytes(
            class_rows
                .iter()
                .filter(|row| {
                    row.disposition == Disposition::Protected
                        || !row.pin_reasons.is_empty()
                        || keep_last_paths.contains(&row.relative_path)
                })
                .map(|row| row.bytes),
        )?;
        if protected > class_policy.hard_quota_bytes {
            return Err(PlanError::ProtectedBytesExceedQuota {
                class: class_policy.class,
                protected_bytes: protected,
                hard_quota_bytes: class_policy.hard_quota_bytes,
            });
        }
        let growth = projected_growth[&class_policy.class];
        let projected_before = before
            .checked_add(growth)
            .ok_or(PlanError::ArithmeticOverflow)?;
        let required = projected_before.saturating_sub(class_policy.hard_quota_bytes);
        let mut candidates: Vec<_> = class_rows
            .into_iter()
            .filter(|row| {
                let grace_ns = class_policy.grace_seconds.saturating_mul(1_000_000_000);
                let old_enough = row
                    .modified_ns
                    .checked_add(grace_ns)
                    .is_some_and(|eligible_at| eligible_at <= census.observed_at_ns);
                row.disposition.eligible()
                    && row.pin_reasons.is_empty()
                    && !keep_last_paths.contains(&row.relative_path)
                    && old_enough
            })
            .collect();
        candidates.sort_by(|left, right| {
            (left.modified_ns, &left.relative_path).cmp(&(right.modified_ns, &right.relative_path))
        });
        let eligible = sum_bytes(candidates.iter().map(|row| row.bytes))?;
        if required > class_policy.maximum_reconcile_bytes || eligible < required {
            return Err(PlanError::InsufficientEligibleBytes {
                class: class_policy.class,
                required_bytes: required,
                eligible_bytes: eligible,
                maximum_reconcile_bytes: class_policy.maximum_reconcile_bytes,
            });
        }
        let mut selected = 0_u64;
        for row in candidates {
            if selected >= required {
                break;
            }
            selected = selected
                .checked_add(row.bytes)
                .ok_or(PlanError::ArithmeticOverflow)?;
            if selected > class_policy.maximum_reconcile_bytes {
                return Err(PlanError::InsufficientEligibleBytes {
                    class: class_policy.class,
                    required_bytes: required,
                    eligible_bytes: eligible,
                    maximum_reconcile_bytes: class_policy.maximum_reconcile_bytes,
                });
            }
            plan_rows.push(PlanRow {
                class: row.class,
                relative_path: row.relative_path.clone(),
                bytes: row.bytes,
                raw_sha256: row.raw_sha256.clone(),
                physical_identity: row.physical_identity.clone(),
                modified_ns: row.modified_ns,
                action: if row.disposition == Disposition::TerminalCompressible {
                    PlanAction::Compress
                } else {
                    PlanAction::PurgeAfterQuarantine
                },
                terminal_kernel_witness: row.terminal_kernel_witness.clone(),
            });
        }
        let projected = before
            .checked_sub(selected)
            .ok_or(PlanError::ArithmeticOverflow)?;
        let projected_with_growth = projected
            .checked_add(growth)
            .ok_or(PlanError::ArithmeticOverflow)?;
        if projected_with_growth > class_policy.hard_quota_bytes {
            return Err(PlanError::InsufficientEligibleBytes {
                class: class_policy.class,
                required_bytes: required,
                eligible_bytes: selected,
                maximum_reconcile_bytes: class_policy.maximum_reconcile_bytes,
            });
        }
        summaries.insert(
            class_policy.class,
            ClassPlanSummary {
                before_bytes: before,
                protected_bytes: protected,
                projected_growth_bytes: growth,
                selected_bytes: selected,
                projected_after_bytes: projected,
                hard_quota_bytes: class_policy.hard_quota_bytes,
            },
        );
    }
    let selected_keys = plan_rows
        .iter()
        .map(|row| (row.class, row.relative_path.as_str()))
        .collect::<BTreeSet<_>>();
    let kept_rows = census
        .rows
        .iter()
        .filter(|row| !selected_keys.contains(&(row.class, row.relative_path.as_str())))
        .cloned()
        .collect();
    let without = StoragePlanWithoutSelf {
        schema_version: "ember-storage-retention-plan-v2".into(),
        policy_raw_sha256: policy.raw_sha256.clone(),
        census_self_sha256: census.self_sha256.clone(),
        pin_set_raw_sha256: pin_set_raw_sha256.into(),
        current_master: current_master.into(),
        classes: summaries,
        rows: plan_rows,
        kept_rows,
    };
    let self_sha256 = canonical_json_sha256(&without)?;
    Ok(StoragePlan {
        schema_version: without.schema_version,
        policy_raw_sha256: without.policy_raw_sha256,
        census_self_sha256: without.census_self_sha256,
        pin_set_raw_sha256: without.pin_set_raw_sha256,
        current_master: without.current_master,
        classes: without.classes,
        rows: without.rows,
        kept_rows: without.kept_rows,
        self_sha256,
    })
}

fn keep_last_paths(class_policy: &ClassPolicy, rows: &[&CensusRow]) -> BTreeSet<String> {
    let keep = class_policy.keep_last_n.unwrap_or(0) as usize;
    if keep == 0 {
        return BTreeSet::new();
    }
    let mut series: BTreeMap<&str, BTreeMap<u64, Vec<&CensusRow>>> = BTreeMap::new();
    for row in rows {
        if let Some(checkpoint) = &row.checkpoint {
            series
                .entry(&checkpoint.series)
                .or_default()
                .entry(checkpoint.sequence)
                .or_default()
                .push(row);
        }
    }
    let mut retained = BTreeSet::new();
    for checkpoints in series.into_values() {
        for rows in checkpoints
            .into_iter()
            .rev()
            .take(keep)
            .map(|(_, rows)| rows)
        {
            retained.extend(rows.into_iter().map(|row| row.relative_path.clone()));
        }
    }
    retained
}

fn sum_bytes(mut values: impl Iterator<Item = u64>) -> Result<u64, PlanError> {
    values.try_fold(0_u64, |total, value| {
        total
            .checked_add(value)
            .ok_or(PlanError::ArithmeticOverflow)
    })
}

fn is_lower_hex(value: &str, width: usize) -> bool {
    value.len() == width
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Reopen the repository's locally fetched public master ref without trusting a caller-supplied
/// commit string. Supports both a primary checkout and a linked worktree, including packed refs.
pub fn reopen_remote_master(repository_root: &Path) -> Result<String, PlanError> {
    let dot_git = repository_root.join(".git");
    let git_dir = if dot_git.is_dir() {
        dot_git
    } else {
        let marker = fs::read_to_string(&dot_git)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
        let target = marker.trim().strip_prefix("gitdir: ").ok_or_else(|| {
            PlanError::InvalidIdentity("repository .git marker is invalid".into())
        })?;
        let target = PathBuf::from(target);
        if target.is_absolute() {
            target
        } else {
            repository_root.join(target)
        }
    };
    let common_dir_marker = git_dir.join("commondir");
    let common_dir = if common_dir_marker.is_file() {
        let target = fs::read_to_string(&common_dir_marker)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
        let target = PathBuf::from(target.trim());
        if target.is_absolute() {
            target
        } else {
            git_dir.join(target)
        }
    } else {
        git_dir
    };
    let loose_ref = common_dir.join("refs/remotes/origin/master");
    let reopened = if loose_ref.is_file() {
        fs::read_to_string(&loose_ref)
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?
            .trim()
            .to_owned()
    } else {
        let packed = fs::read_to_string(common_dir.join("packed-refs"))
            .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
        packed
            .lines()
            .filter(|line| !line.starts_with('#') && !line.starts_with('^'))
            .find_map(|line| {
                let (sha, name) = line.split_once(' ')?;
                (name == "refs/remotes/origin/master").then(|| sha.to_owned())
            })
            .ok_or_else(|| {
                PlanError::InvalidIdentity("repository lacks refs/remotes/origin/master".into())
            })?
    };
    if !is_lower_hex(&reopened, 40) {
        return Err(PlanError::InvalidIdentity(
            "reopened origin/master is not lowercase 40-hex".into(),
        ));
    }
    Ok(reopened)
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn canonical_json_sha256(value: &impl Serialize) -> Result<String, PlanError> {
    serde_json::to_vec(value)
        .map(|bytes| sha256_hex(&bytes))
        .map_err(|error| PlanError::Serialization(error.to_string()))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExecutionError {
    Io(String),
    ObservationDrift(String),
    NoOverwrite(String),
    UnsafePath(String),
    UnsupportedAction(String),
    InjectedInterruption,
    Serialization(String),
}

impl fmt::Display for ExecutionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(detail) => write!(f, "storage execution I/O failure: {detail}"),
            Self::ObservationDrift(detail) => write!(f, "storage observation drift: {detail}"),
            Self::NoOverwrite(path) => write!(f, "storage receipt already exists: {path}"),
            Self::UnsafePath(detail) => {
                write!(f, "storage execution refused unsafe path: {detail}")
            }
            Self::UnsupportedAction(detail) => {
                write!(f, "storage execution action is not implemented: {detail}")
            }
            Self::InjectedInterruption => write!(f, "injected interruption after quarantine"),
            Self::Serialization(detail) => {
                write!(f, "storage execution serialization failed: {detail}")
            }
        }
    }
}

impl std::error::Error for ExecutionError {}

impl From<std::io::Error> for ExecutionError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileObservation {
    pub bytes: u64,
    pub raw_sha256: String,
    pub physical_identity: String,
    pub modified_ns: u64,
    pub link_count: u64,
}

pub fn observe_file(path: &Path) -> Result<FileObservation, ExecutionError> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(ExecutionError::UnsafePath(format!(
            "{} is not an ordinary file",
            path.display()
        )));
    }
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let (physical_identity, modified_ns, link_count) = platform_file_identity(&file, &metadata)?;
    Ok(FileObservation {
        bytes: metadata.len(),
        raw_sha256: format!("{:x}", hasher.finalize()),
        physical_identity,
        modified_ns,
        link_count,
    })
}

#[cfg(windows)]
fn platform_file_identity(
    file: &File,
    metadata: &fs::Metadata,
) -> Result<(String, u64, u64), ExecutionError> {
    use std::os::windows::fs::MetadataExt;
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(ExecutionError::UnsafePath(
            "file is a Windows reparse point".into(),
        ));
    }
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe { GetFileInformationByHandle(file.as_raw_handle().cast(), &mut information) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    const WINDOWS_TO_UNIX_EPOCH_100NS: u64 = 116_444_736_000_000_000;
    let modified_ns = metadata
        .last_write_time()
        .checked_sub(WINDOWS_TO_UNIX_EPOCH_100NS)
        .and_then(|ticks| ticks.checked_mul(100))
        .ok_or_else(|| {
            ExecutionError::ObservationDrift(
                "file modification time cannot be represented as Unix nanoseconds".into(),
            )
        })?;
    Ok((
        format!(
            "windows:{:08x}:{:08x}{:08x}",
            information.dwVolumeSerialNumber, information.nFileIndexHigh, information.nFileIndexLow
        ),
        modified_ns,
        u64::from(information.nNumberOfLinks),
    ))
}

#[cfg(unix)]
fn platform_file_identity(
    _file: &File,
    metadata: &fs::Metadata,
) -> Result<(String, u64, u64), ExecutionError> {
    use std::os::unix::fs::MetadataExt;
    let seconds = u64::try_from(metadata.mtime()).unwrap_or(0);
    let nanos = u64::try_from(metadata.mtime_nsec()).unwrap_or(0);
    Ok((
        format!("unix:{}:{}", metadata.dev(), metadata.ino()),
        seconds.saturating_mul(1_000_000_000).saturating_add(nanos),
        metadata.nlink(),
    ))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionMode {
    DryRun,
    Commit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionFault {
    AfterQuarantines(usize),
    AfterPurges(usize),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecoveryAction {
    Resume,
    Rollback,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionReceipt {
    pub schema_version: String,
    pub result: String,
    pub plan_self_sha256: String,
    pub policy_raw_sha256: String,
    pub census_self_sha256: String,
    pub pin_set_raw_sha256: String,
    pub current_master: String,
    pub selected_rows: u64,
    pub selected_bytes: u64,
    pub classes: BTreeMap<CustodyClass, ExecutionClassReceipt>,
    pub rows: Vec<ExecutionRowReceipt>,
    pub cleanup_verified: bool,
    pub self_sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionClassReceipt {
    pub before_bytes: u64,
    pub after_bytes: u64,
    pub hard_quota_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionRowReceipt {
    pub class: CustodyClass,
    pub relative_path: String,
    pub bytes: u64,
    pub raw_sha256: String,
    pub physical_identity: String,
    pub terminal_disposition: String,
}

/// Independently reopen and authenticate a terminal execution receipt.
pub fn verify_execution_receipt(receipt: &ExecutionReceipt) -> Result<(), ExecutionError> {
    let expected = canonical_json_sha256(&ExecutionReceiptWithoutSelf {
        schema_version: &receipt.schema_version,
        result: &receipt.result,
        plan_self_sha256: &receipt.plan_self_sha256,
        policy_raw_sha256: &receipt.policy_raw_sha256,
        census_self_sha256: &receipt.census_self_sha256,
        pin_set_raw_sha256: &receipt.pin_set_raw_sha256,
        current_master: &receipt.current_master,
        selected_rows: receipt.selected_rows,
        selected_bytes: receipt.selected_bytes,
        classes: &receipt.classes,
        rows: &receipt.rows,
        cleanup_verified: receipt.cleanup_verified,
    })
    .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    if receipt.self_sha256 != expected {
        return Err(ExecutionError::ObservationDrift(
            "terminal execution receipt self hash mismatch".into(),
        ));
    }
    Ok(())
}

#[derive(Serialize)]
struct ExecutionReceiptWithoutSelf<'a> {
    schema_version: &'a str,
    result: &'a str,
    plan_self_sha256: &'a str,
    policy_raw_sha256: &'a str,
    census_self_sha256: &'a str,
    pin_set_raw_sha256: &'a str,
    current_master: &'a str,
    selected_rows: u64,
    selected_bytes: u64,
    classes: &'a BTreeMap<CustodyClass, ExecutionClassReceipt>,
    rows: &'a [ExecutionRowReceipt],
    cleanup_verified: bool,
}

pub fn execute_plan(
    plan: &StoragePlan,
    roots: &BTreeMap<CustodyClass, PathBuf>,
    custody: &Path,
    mode: ExecutionMode,
    fault: Option<ExecutionFault>,
) -> Result<ExecutionReceipt, ExecutionError> {
    verify_roots_and_rows(plan, roots)?;
    let before = measure_roots(roots)?;
    require_class_totals(plan, &before, false)?;
    fs::create_dir_all(custody)?;
    let precommit = custody.join("precommit.json");
    let terminal = custody.join("terminal.json");
    let journal = custody.join("journal.jsonl");
    let precommit_payload = self_hashed_value(serde_json::json!({
        "schema_version":"ember-storage-retention-precommit-v1",
        "plan_self_sha256":plan.self_sha256,
        "mode":mode,
        "rows":plan.rows,
    }))?;
    write_new_json(&precommit, &precommit_payload)?;
    if mode == ExecutionMode::DryRun {
        let receipt = execution_receipt("DRY_RUN_PASS", plan, &before)?;
        write_new_json(&terminal, &receipt)?;
        return Ok(receipt);
    }
    let mut journal_file = open_new(&journal)?;
    let mut quarantined = 0_usize;
    for row in &plan.rows {
        let root = roots
            .get(&row.class)
            .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {} root", row.class)))?;
        let source = safe_member(root, &row.relative_path)?;
        let quarantine = quarantine_path(root, plan, row)?;
        if quarantine.exists() {
            return Err(ExecutionError::NoOverwrite(
                quarantine.display().to_string(),
            ));
        }
        let parent = quarantine
            .parent()
            .ok_or_else(|| ExecutionError::UnsafePath("quarantine target has no parent".into()))?;
        fs::create_dir_all(parent)?;
        ensure_directory_chain_is_safe(root, parent)?;
        let observation = observe_file(&source)?;
        require_matching_observation(row, &observation)?;
        fs::rename(&source, &quarantine)?;
        append_journal(
            &mut journal_file,
            &serde_json::json!({
                "event":"quarantined",
                "class":row.class,
                "relative_path":row.relative_path,
                "raw_sha256":row.raw_sha256,
                "physical_identity":row.physical_identity,
            }),
        )?;
        quarantined += 1;
        if fault == Some(ExecutionFault::AfterQuarantines(quarantined)) {
            return Err(ExecutionError::InjectedInterruption);
        }
    }
    let mut purged = 0_usize;
    for row in &plan.rows {
        let root = roots
            .get(&row.class)
            .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {} root", row.class)))?;
        let quarantine = quarantine_path(root, plan, row)?;
        let observation = observe_file(&quarantine)?;
        require_matching_observation(row, &observation)?;
        append_journal(
            &mut journal_file,
            &serde_json::json!({
                "event":"purge_intent",
                "class":row.class,
                "relative_path":row.relative_path,
                "raw_sha256":row.raw_sha256,
            }),
        )?;
        fs::remove_file(&quarantine)?;
        let terminal_event = if row.action == PlanAction::Compress {
            "compressed_to_kernel"
        } else {
            "purged"
        };
        append_journal(
            &mut journal_file,
            &serde_json::json!({
                "event":terminal_event,
                "class":row.class,
                "relative_path":row.relative_path,
                "raw_sha256":row.raw_sha256,
                "terminal_kernel_witness":row.terminal_kernel_witness,
            }),
        )?;
        purged += 1;
        if fault == Some(ExecutionFault::AfterPurges(purged)) {
            return Err(ExecutionError::InjectedInterruption);
        }
    }
    cleanup_quarantine_roots(plan, roots)?;
    verify_kept_rows(plan, roots)?;
    let after = measure_roots(roots)?;
    require_class_totals(plan, &after, true)?;
    let receipt = execution_receipt("COMMITTED_PASS", plan, &after)?;
    write_new_json(&terminal, &receipt)?;
    Ok(receipt)
}

pub fn recover_plan(
    plan: &StoragePlan,
    roots: &BTreeMap<CustodyClass, PathBuf>,
    custody: &Path,
    action: RecoveryAction,
) -> Result<ExecutionReceipt, ExecutionError> {
    let precommit = custody.join("precommit.json");
    if !precommit.is_file() {
        return Err(ExecutionError::ObservationDrift(
            "recovery lacks the durable precommit receipt".into(),
        ));
    }
    verify_precommit(&precommit, plan)?;
    let journal_path = custody.join("journal.jsonl");
    let journal_events = read_journal_events(&journal_path)?;
    let mut journal_file = OpenOptions::new().append(true).open(&journal_path)?;
    for row in &plan.rows {
        let root = roots
            .get(&row.class)
            .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {} root", row.class)))?;
        let source = safe_member(root, &row.relative_path)?;
        let quarantine = quarantine_path(root, plan, row)?;
        match (source.exists(), quarantine.exists(), action) {
            (true, false, RecoveryAction::Rollback) => {}
            (true, false, RecoveryAction::Resume) => {
                let observation = observe_file(&source)?;
                require_matching_observation(row, &observation)?;
                let parent = quarantine.parent().ok_or_else(|| {
                    ExecutionError::UnsafePath("quarantine target has no parent".into())
                })?;
                fs::create_dir_all(parent)?;
                ensure_directory_chain_is_safe(root, parent)?;
                fs::rename(&source, &quarantine)?;
                append_journal(
                    &mut journal_file,
                    &serde_json::json!({
                        "event":"quarantined",
                        "class":row.class,
                        "relative_path":row.relative_path,
                        "raw_sha256":row.raw_sha256,
                        "physical_identity":row.physical_identity,
                    }),
                )?;
                append_journal(
                    &mut journal_file,
                    &serde_json::json!({
                        "event":"purge_intent",
                        "class":row.class,
                        "relative_path":row.relative_path,
                        "raw_sha256":row.raw_sha256,
                    }),
                )?;
                fs::remove_file(&quarantine)?;
                append_journal(
                    &mut journal_file,
                    &serde_json::json!({
                        "event":if row.action == PlanAction::Compress { "compressed_to_kernel" } else { "purged" },
                        "class":row.class,
                        "relative_path":row.relative_path,
                        "raw_sha256":row.raw_sha256,
                        "terminal_kernel_witness":row.terminal_kernel_witness,
                    }),
                )?;
            }
            (false, true, RecoveryAction::Rollback) => {
                require_journal_event(&journal_events, "quarantined", row)?;
                let observation = observe_file(&quarantine)?;
                require_matching_observation(row, &observation)?;
                if let Some(parent) = source.parent() {
                    fs::create_dir_all(parent)?;
                }
                fs::rename(&quarantine, &source)?;
                append_journal(
                    &mut journal_file,
                    &serde_json::json!({
                        "event":"restored",
                        "class":row.class,
                        "relative_path":row.relative_path,
                        "raw_sha256":row.raw_sha256,
                        "physical_identity":row.physical_identity,
                    }),
                )?;
            }
            (false, true, RecoveryAction::Resume) => {
                require_journal_event(&journal_events, "quarantined", row)?;
                let observation = observe_file(&quarantine)?;
                require_matching_observation(row, &observation)?;
                append_journal(
                    &mut journal_file,
                    &serde_json::json!({
                        "event":"purge_intent",
                        "class":row.class,
                        "relative_path":row.relative_path,
                        "raw_sha256":row.raw_sha256,
                    }),
                )?;
                fs::remove_file(&quarantine)?;
                append_journal(
                    &mut journal_file,
                    &serde_json::json!({
                        "event":if row.action == PlanAction::Compress { "compressed_to_kernel" } else { "purged" },
                        "class":row.class,
                        "relative_path":row.relative_path,
                        "raw_sha256":row.raw_sha256,
                        "terminal_kernel_witness":row.terminal_kernel_witness,
                    }),
                )?;
            }
            (false, false, RecoveryAction::Resume) => {
                if !has_journal_event(&journal_events, "purge_intent", row)
                    && !has_journal_event(&journal_events, "purged", row)
                {
                    return Err(ExecutionError::ObservationDrift(format!(
                        "{}:{} is absent without a durable purge intent",
                        row.class, row.relative_path
                    )));
                }
            }
            (false, false, RecoveryAction::Rollback) => {
                return Err(ExecutionError::ObservationDrift(format!(
                    "{}:{} was already purged and cannot be rolled back",
                    row.class, row.relative_path
                )));
            }
            (true, true, _) => {
                return Err(ExecutionError::ObservationDrift(format!(
                    "{}:{} exists in both source and quarantine",
                    row.class, row.relative_path
                )));
            }
        }
    }
    drop(journal_file);
    cleanup_quarantine_roots(plan, roots)?;
    verify_kept_rows(plan, roots)?;
    let result = match action {
        RecoveryAction::Resume => "RECOVERED_COMMITTED_PASS",
        RecoveryAction::Rollback => "RECOVERED_ROLLBACK_PASS",
    };
    let after = measure_roots(roots)?;
    require_class_totals(plan, &after, action == RecoveryAction::Resume)?;
    let receipt = execution_receipt(result, plan, &after)?;
    write_new_json(&custody.join("recovery.json"), &receipt)?;
    Ok(receipt)
}

type JournalEvent = (String, CustodyClass, String);

fn read_journal_events(path: &Path) -> Result<BTreeSet<JournalEvent>, ExecutionError> {
    let raw = fs::read_to_string(path)?;
    let mut events = BTreeSet::new();
    for (index, line) in raw.lines().enumerate() {
        let value: serde_json::Value = serde_json::from_str(line).map_err(|error| {
            ExecutionError::Serialization(format!("journal line {}: {error}", index + 1))
        })?;
        let event = value
            .get("event")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| {
                ExecutionError::Serialization(format!("journal line {} lacks event", index + 1))
            })?;
        let class: CustodyClass =
            serde_json::from_value(value.get("class").cloned().ok_or_else(|| {
                ExecutionError::Serialization(format!("journal line {} lacks class", index + 1))
            })?)
            .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
        let relative_path = value
            .get("relative_path")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| {
                ExecutionError::Serialization(format!(
                    "journal line {} lacks relative_path",
                    index + 1
                ))
            })?;
        events.insert((event.into(), class, relative_path.into()));
    }
    Ok(events)
}

fn has_journal_event(events: &BTreeSet<JournalEvent>, event: &str, row: &PlanRow) -> bool {
    events.contains(&(event.into(), row.class, row.relative_path.clone()))
}

fn require_journal_event(
    events: &BTreeSet<JournalEvent>,
    event: &str,
    row: &PlanRow,
) -> Result<(), ExecutionError> {
    if !has_journal_event(events, event, row) {
        return Err(ExecutionError::ObservationDrift(format!(
            "{}:{} lacks durable {event} journal evidence",
            row.class, row.relative_path
        )));
    }
    Ok(())
}

fn verify_roots_and_rows(
    plan: &StoragePlan,
    roots: &BTreeMap<CustodyClass, PathBuf>,
) -> Result<(), ExecutionError> {
    verify_compression_bindings(plan)?;
    let mut canonical_roots = Vec::new();
    for class in [CustodyClass::Models, CustodyClass::State] {
        let root = roots
            .get(&class)
            .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {class} root")))?;
        let canonical = fs::canonicalize(root)?;
        if !canonical.is_dir() {
            return Err(ExecutionError::UnsafePath(format!(
                "{} root is not a directory",
                class
            )));
        }
        ensure_directory_chain_is_safe(&canonical, &canonical)?;
        canonical_roots.push(canonical);
    }
    if canonical_roots[0] == canonical_roots[1]
        || canonical_roots[0].starts_with(&canonical_roots[1])
        || canonical_roots[1].starts_with(&canonical_roots[0])
    {
        return Err(ExecutionError::UnsafePath("execution roots overlap".into()));
    }
    for row in &plan.rows {
        let root = roots
            .get(&row.class)
            .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {} root", row.class)))?;
        let path = safe_member(root, &row.relative_path)?;
        let observation = match observe_file(&path) {
            Ok(observation) => observation,
            Err(ExecutionError::UnsafePath(detail)) => {
                return Err(ExecutionError::UnsafePath(detail));
            }
            Err(error) => {
                return Err(ExecutionError::ObservationDrift(format!(
                    "{}:{} could not be reopened: {error}",
                    row.class, row.relative_path
                )));
            }
        };
        require_matching_observation(row, &observation)?;
        if observation.link_count != 1 {
            return Err(ExecutionError::UnsafePath(format!(
                "{}:{} has ambiguous hard links",
                row.class, row.relative_path
            )));
        }
    }
    verify_kept_rows(plan, roots)?;
    Ok(())
}

fn verify_compression_bindings(plan: &StoragePlan) -> Result<(), ExecutionError> {
    for row in &plan.rows {
        match (row.action, &row.terminal_kernel_witness) {
            (PlanAction::Compress, Some(witness)) => {
                let expected_pin = format!("terminal_receipt_kernel:{}", witness.receipt_identity);
                let retained = plan.kept_rows.iter().find(|candidate| {
                    candidate.class == CustodyClass::State
                        && candidate.relative_path == witness.retained_relative_path
                });
                if row.class != CustodyClass::State
                    || !witness.independently_reopened
                    || retained.is_none_or(|candidate| {
                        candidate.raw_sha256 != witness.retained_raw_sha256
                            || candidate.disposition != Disposition::Protected
                            || !candidate.pin_reasons.contains(&expected_pin)
                    })
                {
                    return Err(ExecutionError::ObservationDrift(format!(
                        "{}:{} compression lacks its kept receipt kernel",
                        row.class, row.relative_path
                    )));
                }
            }
            (PlanAction::PurgeAfterQuarantine, None) => {}
            _ => {
                return Err(ExecutionError::ObservationDrift(format!(
                    "{}:{} action and terminal-kernel witness disagree",
                    row.class, row.relative_path
                )));
            }
        }
    }
    Ok(())
}

fn verify_kept_rows(
    plan: &StoragePlan,
    roots: &BTreeMap<CustodyClass, PathBuf>,
) -> Result<(), ExecutionError> {
    for row in &plan.kept_rows {
        let root = roots
            .get(&row.class)
            .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {} root", row.class)))?;
        let path = safe_member(root, &row.relative_path)?;
        let observation = observe_file(&path).map_err(|error| {
            ExecutionError::ObservationDrift(format!(
                "kept {}:{} could not be reopened: {error}",
                row.class, row.relative_path
            ))
        })?;
        if row.bytes != observation.bytes
            || row.raw_sha256 != observation.raw_sha256
            || row.physical_identity != observation.physical_identity
            || row.modified_ns != observation.modified_ns
        {
            return Err(ExecutionError::ObservationDrift(format!(
                "kept {}:{} no longer matches its plan identity",
                row.class, row.relative_path
            )));
        }
        if observation.link_count != 1 {
            return Err(ExecutionError::UnsafePath(format!(
                "kept {}:{} has ambiguous hard links",
                row.class, row.relative_path
            )));
        }
    }
    Ok(())
}

fn require_matching_observation(
    row: &PlanRow,
    observation: &FileObservation,
) -> Result<(), ExecutionError> {
    if !row.matches_observation(
        observation.bytes,
        &observation.raw_sha256,
        &observation.physical_identity,
        observation.modified_ns,
    ) {
        return Err(ExecutionError::ObservationDrift(format!(
            "{}:{} no longer matches the immutable plan row",
            row.class, row.relative_path
        )));
    }
    Ok(())
}

fn safe_member(root: &Path, relative_path: &str) -> Result<PathBuf, ExecutionError> {
    validate_relative_path(relative_path)
        .map_err(|error| ExecutionError::UnsafePath(error.to_string()))?;
    let path = root.join(relative_path);
    if !path.starts_with(root) {
        return Err(ExecutionError::UnsafePath(relative_path.into()));
    }
    Ok(path)
}

fn quarantine_path(
    root: &Path,
    plan: &StoragePlan,
    row: &PlanRow,
) -> Result<PathBuf, ExecutionError> {
    Ok(root
        .join(".ember-retention-quarantine")
        .join(&plan.self_sha256)
        .join(safe_member(Path::new(""), &row.relative_path)?))
}

fn ensure_directory_chain_is_safe(root: &Path, target: &Path) -> Result<(), ExecutionError> {
    if !target.starts_with(root) {
        return Err(ExecutionError::UnsafePath(target.display().to_string()));
    }
    let mut current = PathBuf::from(root);
    for component in target
        .strip_prefix(root)
        .map_err(|_| {
            ExecutionError::UnsafePath(format!("{} escaped {}", target.display(), root.display()))
        })?
        .components()
    {
        current.push(component);
        let metadata = fs::symlink_metadata(&current)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(ExecutionError::UnsafePath(current.display().to_string()));
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
            if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
                return Err(ExecutionError::UnsafePath(current.display().to_string()));
            }
        }
    }
    Ok(())
}

fn open_new(path: &Path) -> Result<File, ExecutionError> {
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                ExecutionError::NoOverwrite(path.display().to_string())
            } else {
                error.into()
            }
        })
}

fn write_new_json(path: &Path, value: &impl Serialize) -> Result<(), ExecutionError> {
    let mut bytes = serde_json::to_vec(value)
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    bytes.push(b'\n');
    let mut file = open_new(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn self_hashed_value(mut value: serde_json::Value) -> Result<serde_json::Value, ExecutionError> {
    let object = value.as_object_mut().ok_or_else(|| {
        ExecutionError::Serialization("self-hashed receipt must be an object".into())
    })?;
    if object.contains_key("self_sha256") {
        return Err(ExecutionError::Serialization(
            "self-hashed receipt input already has self_sha256".into(),
        ));
    }
    let raw = serde_json::to_vec(&object)
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    object.insert(
        "self_sha256".into(),
        serde_json::Value::String(sha256_hex(&raw)),
    );
    Ok(value)
}

fn verify_precommit(path: &Path, plan: &StoragePlan) -> Result<(), ExecutionError> {
    let raw = fs::read(path)?;
    let mut value: serde_json::Value = serde_json::from_slice(&raw)
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    let object = value.as_object_mut().ok_or_else(|| {
        ExecutionError::Serialization("precommit receipt must be an object".into())
    })?;
    let stored = object
        .remove("self_sha256")
        .and_then(|item| item.as_str().map(str::to_owned))
        .ok_or_else(|| ExecutionError::Serialization("precommit self hash is absent".into()))?;
    let canonical = serde_json::to_vec(&object)
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    if stored != sha256_hex(&canonical)
        || object
            .get("plan_self_sha256")
            .and_then(serde_json::Value::as_str)
            != Some(plan.self_sha256.as_str())
    {
        return Err(ExecutionError::ObservationDrift(
            "precommit receipt identity does not reopen".into(),
        ));
    }
    Ok(())
}

fn append_journal(file: &mut File, value: &impl Serialize) -> Result<(), ExecutionError> {
    let mut bytes = serde_json::to_vec(value)
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    bytes.push(b'\n');
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn execution_receipt(
    result: &str,
    plan: &StoragePlan,
    after: &BTreeMap<CustodyClass, u64>,
) -> Result<ExecutionReceipt, ExecutionError> {
    let selected_rows = u64::try_from(plan.rows.len())
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    let selected_bytes = plan.rows.iter().try_fold(0_u64, |total, row| {
        total
            .checked_add(row.bytes)
            .ok_or_else(|| ExecutionError::Serialization("selected byte total overflowed".into()))
    })?;
    let classes = plan
        .classes
        .iter()
        .map(|(class, summary)| {
            let after_bytes = after.get(class).copied().ok_or_else(|| {
                ExecutionError::Serialization(format!("missing {class} measured total"))
            })?;
            Ok((
                *class,
                ExecutionClassReceipt {
                    before_bytes: summary.before_bytes,
                    after_bytes,
                    hard_quota_bytes: summary.hard_quota_bytes,
                },
            ))
        })
        .collect::<Result<BTreeMap<_, _>, ExecutionError>>()?;
    let mut rows = plan
        .rows
        .iter()
        .map(|row| ExecutionRowReceipt {
            class: row.class,
            relative_path: row.relative_path.clone(),
            bytes: row.bytes,
            raw_sha256: row.raw_sha256.clone(),
            physical_identity: row.physical_identity.clone(),
            terminal_disposition: match result {
                "DRY_RUN_PASS" => match row.action {
                    PlanAction::Compress => "planned_compress",
                    PlanAction::PurgeAfterQuarantine => "planned_purge",
                },
                "RECOVERED_ROLLBACK_PASS" => "restored",
                _ => match row.action {
                    PlanAction::Compress => "compressed_to_kernel",
                    PlanAction::PurgeAfterQuarantine => "purged",
                },
            }
            .into(),
        })
        .collect::<Vec<_>>();
    rows.extend(plan.kept_rows.iter().map(|row| ExecutionRowReceipt {
        class: row.class,
        relative_path: row.relative_path.clone(),
        bytes: row.bytes,
        raw_sha256: row.raw_sha256.clone(),
        physical_identity: row.physical_identity.clone(),
        terminal_disposition: "kept".into(),
    }));
    let without = ExecutionReceiptWithoutSelf {
        schema_version: "ember-storage-retention-terminal-v2",
        result,
        plan_self_sha256: &plan.self_sha256,
        policy_raw_sha256: &plan.policy_raw_sha256,
        census_self_sha256: &plan.census_self_sha256,
        pin_set_raw_sha256: &plan.pin_set_raw_sha256,
        current_master: &plan.current_master,
        selected_rows,
        selected_bytes,
        classes: &classes,
        rows: &rows,
        cleanup_verified: true,
    };
    let raw = serde_json::to_vec(&without)
        .map_err(|error| ExecutionError::Serialization(error.to_string()))?;
    Ok(ExecutionReceipt {
        schema_version: without.schema_version.into(),
        result: without.result.into(),
        plan_self_sha256: without.plan_self_sha256.into(),
        policy_raw_sha256: without.policy_raw_sha256.into(),
        census_self_sha256: without.census_self_sha256.into(),
        pin_set_raw_sha256: without.pin_set_raw_sha256.into(),
        current_master: without.current_master.into(),
        selected_rows,
        selected_bytes,
        classes,
        rows,
        cleanup_verified: true,
        self_sha256: sha256_hex(&raw),
    })
}

fn require_class_totals(
    plan: &StoragePlan,
    measured: &BTreeMap<CustodyClass, u64>,
    projected: bool,
) -> Result<(), ExecutionError> {
    for (class, summary) in &plan.classes {
        let expected = if projected {
            summary.projected_after_bytes
        } else {
            summary.before_bytes
        };
        let actual = measured.get(class).copied().ok_or_else(|| {
            ExecutionError::ObservationDrift(format!("missing {class} measured total"))
        })?;
        if actual != expected {
            return Err(ExecutionError::ObservationDrift(format!(
                "{class} measured total {actual} does not match expected {expected}"
            )));
        }
    }
    Ok(())
}

fn measure_roots(
    roots: &BTreeMap<CustodyClass, PathBuf>,
) -> Result<BTreeMap<CustodyClass, u64>, ExecutionError> {
    [CustodyClass::Models, CustodyClass::State]
        .into_iter()
        .map(|class| {
            let root = roots
                .get(&class)
                .ok_or_else(|| ExecutionError::UnsafePath(format!("missing {class} root")))?;
            Ok((class, measure_tree_bytes(root, root)?))
        })
        .collect()
}

fn measure_tree_bytes(root: &Path, directory: &Path) -> Result<u64, ExecutionError> {
    ensure_directory_chain_is_safe(root, directory)?;
    let mut total = 0_u64;
    for entry in fs::read_dir(directory)? {
        let path = entry?.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() {
            return Err(ExecutionError::UnsafePath(path.display().to_string()));
        }
        if metadata.is_dir() {
            total = total
                .checked_add(measure_tree_bytes(root, &path)?)
                .ok_or_else(|| {
                    ExecutionError::Serialization("measured byte total overflowed".into())
                })?;
        } else if metadata.is_file() {
            let file = File::open(&path)?;
            let (_, _, link_count) = platform_file_identity(&file, &metadata)?;
            if link_count != 1 {
                return Err(ExecutionError::UnsafePath(format!(
                    "{} has ambiguous hard links",
                    path.display()
                )));
            }
            total = total.checked_add(metadata.len()).ok_or_else(|| {
                ExecutionError::Serialization("measured byte total overflowed".into())
            })?;
        } else {
            return Err(ExecutionError::UnsafePath(path.display().to_string()));
        }
    }
    Ok(total)
}

fn cleanup_quarantine_roots(
    plan: &StoragePlan,
    roots: &BTreeMap<CustodyClass, PathBuf>,
) -> Result<(), ExecutionError> {
    for root in roots.values() {
        let base = root.join(".ember-retention-quarantine");
        let plan_root = base.join(&plan.self_sha256);
        if plan_root.exists() {
            let canonical_root = fs::canonicalize(root)?;
            let canonical_plan = fs::canonicalize(&plan_root)?;
            if !canonical_plan.starts_with(&canonical_root) {
                return Err(ExecutionError::UnsafePath(
                    canonical_plan.display().to_string(),
                ));
            }
            fs::remove_dir_all(&plan_root)?;
        }
        if base.is_dir() && fs::read_dir(&base)?.next().is_none() {
            fs::remove_dir(&base)?;
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReconcileOperation {
    DryRun,
    Commit,
    Resume,
    Rollback,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StorageReconcileRequest {
    pub repository_root: PathBuf,
    pub policy: PathBuf,
    pub declarations: PathBuf,
    pub models_root: PathBuf,
    pub state_root: PathBuf,
    pub custody: PathBuf,
    pub pin_set_sha256: String,
    pub current_master: String,
    pub projected_growth: BTreeMap<CustodyClass, u64>,
    pub operation: ReconcileOperation,
}

fn read_bound_plan(
    path: &Path,
    policy_sha256: &str,
    pin_set_sha256: &str,
    current_master: &str,
    projected_growth: &BTreeMap<CustodyClass, u64>,
) -> Result<StoragePlan, Box<dyn std::error::Error>> {
    let plan: StoragePlan = serde_json::from_slice(&fs::read(path)?)?;
    let computed = canonical_json_sha256(&plan.without_self_hash())?;
    if computed != plan.self_sha256
        || plan.policy_raw_sha256 != policy_sha256
        || plan.pin_set_raw_sha256 != pin_set_sha256
        || plan.current_master != current_master
        || plan.classes.len() != projected_growth.len()
        || plan.classes.iter().any(|(class, summary)| {
            projected_growth.get(class) != Some(&summary.projected_growth_bytes)
        })
    {
        return Err(
            PlanError::InvalidIdentity("persisted storage plan authority mismatch".into()).into(),
        );
    }
    Ok(plan)
}

fn verify_reconcile_authority(request: &StorageReconcileRequest) -> Result<(), PlanError> {
    let reopened_pin_set_sha256 = fs::read(&request.declarations)
        .map(|bytes| sha256_hex(&bytes))
        .map_err(|error| PlanError::InvalidIdentity(error.to_string()))?;
    if reopened_pin_set_sha256 != request.pin_set_sha256 {
        return Err(PlanError::InvalidIdentity(
            "reopened declarations do not match the requested pin-set hash".into(),
        ));
    }
    let reopened_master = reopen_remote_master(&request.repository_root)?;
    if reopened_master != request.current_master {
        return Err(PlanError::InvalidIdentity(
            "reopened origin/master does not match the requested current master".into(),
        ));
    }
    Ok(())
}

pub fn run_storage_reconcile(
    request: &StorageReconcileRequest,
) -> Result<ExecutionReceipt, Box<dyn std::error::Error>> {
    verify_reconcile_authority(request)?;
    let policy = parse_policy(&fs::read(&request.policy)?)?;
    let plan_path = request.custody.join("plan.json");
    let terminal_path = request.custody.join("terminal.json");
    let roots = BTreeMap::from([
        (CustodyClass::Models, request.models_root.clone()),
        (CustodyClass::State, request.state_root.clone()),
    ]);
    if terminal_path.is_file() {
        let plan = read_bound_plan(
            &plan_path,
            &policy.raw_sha256,
            &request.pin_set_sha256,
            &request.current_master,
            &request.projected_growth,
        )?;
        let receipt: ExecutionReceipt = serde_json::from_slice(&fs::read(&terminal_path)?)?;
        verify_execution_receipt(&receipt)?;
        if receipt.plan_self_sha256 != plan.self_sha256 {
            return Err(PlanError::InvalidIdentity("terminal receipt plan mismatch".into()).into());
        }
        return Ok(receipt);
    }
    if matches!(
        request.operation,
        ReconcileOperation::Resume | ReconcileOperation::Rollback
    ) {
        let plan = read_bound_plan(
            &plan_path,
            &policy.raw_sha256,
            &request.pin_set_sha256,
            &request.current_master,
            &request.projected_growth,
        )?;
        return Ok(recover_plan(
            &plan,
            &roots,
            &request.custody,
            if request.operation == ReconcileOperation::Resume {
                RecoveryAction::Resume
            } else {
                RecoveryAction::Rollback
            },
        )?);
    }
    if request.custody.exists() {
        return Err(ExecutionError::NoOverwrite(request.custody.display().to_string()).into());
    }
    let declarations: Vec<CensusDeclaration> =
        serde_json::from_slice(&fs::read(&request.declarations)?)?;
    let census = census_filesystem(&roots, declarations)?;
    let plan = build_plan_for_growth(
        &policy,
        &census,
        &request.pin_set_sha256,
        &request.current_master,
        &request.projected_growth,
    )?;
    fs::create_dir(&request.custody)?;
    write_new_json(&request.custody.join("census.json"), &census)?;
    write_new_json(&plan_path, &plan)?;
    // Reopen both mutable authorities after the plan is durable and immediately
    // before execute_plan publishes its precommit. A new pin or master advance
    // therefore invalidates the stale plan before the first payload mutation.
    verify_reconcile_authority(request)?;
    Ok(execute_plan(
        &plan,
        &roots,
        &request.custody,
        if request.operation == ReconcileOperation::DryRun {
            ExecutionMode::DryRun
        } else {
            ExecutionMode::Commit
        },
        None,
    )?)
}
