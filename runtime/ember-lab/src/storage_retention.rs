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
use std::path::{Component, Path};

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
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Census {
    pub rows: Vec<CensusRow>,
    pub self_sha256: String,
}

#[derive(Serialize)]
struct CensusWithoutSelf<'a> {
    rows: &'a [CensusRow],
}

impl Census {
    pub fn new(mut rows: Vec<CensusRow>) -> Result<Self, PlanError> {
        let mut seen = BTreeSet::new();
        let mut checkpoint_sequences = BTreeSet::new();
        for row in &rows {
            validate_relative_path(&row.relative_path)?;
            if row.bytes == 0 {
                return Err(PlanError::InvalidIdentity(format!(
                    "{}:{} has zero bytes",
                    row.class, row.relative_path
                )));
            }
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
                if !checkpoint_sequences.insert((checkpoint.series.clone(), checkpoint.sequence)) {
                    return Err(PlanError::InvalidIdentity(format!(
                        "duplicate checkpoint sequence {}:{}",
                        checkpoint.series, checkpoint.sequence
                    )));
                }
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
            let identity = (row.class, row.relative_path.clone());
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
        rows.sort_by(|left, right| {
            (left.class, &left.relative_path).cmp(&(right.class, &right.relative_path))
        });
        let self_sha256 = canonical_json_sha256(&CensusWithoutSelf { rows: &rows })?;
        Ok(Self { rows, self_sha256 })
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
        }
    }
}

pub fn build_plan(
    policy: &StoragePolicy,
    census: &Census,
    pin_set_raw_sha256: &str,
    current_master: &str,
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
        let required = before.saturating_sub(class_policy.hard_quota_bytes);
        let mut candidates: Vec<_> = class_rows
            .into_iter()
            .filter(|row| {
                row.disposition.eligible()
                    && row.pin_reasons.is_empty()
                    && !keep_last_paths.contains(&row.relative_path)
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
            });
        }
        let projected = before
            .checked_sub(selected)
            .ok_or(PlanError::ArithmeticOverflow)?;
        if projected > class_policy.hard_quota_bytes {
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
                selected_bytes: selected,
                projected_after_bytes: projected,
                hard_quota_bytes: class_policy.hard_quota_bytes,
            },
        );
    }
    let without = StoragePlanWithoutSelf {
        schema_version: "ember-storage-retention-plan-v1".into(),
        policy_raw_sha256: policy.raw_sha256.clone(),
        census_self_sha256: census.self_sha256.clone(),
        pin_set_raw_sha256: pin_set_raw_sha256.into(),
        current_master: current_master.into(),
        classes: summaries,
        rows: plan_rows,
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
        self_sha256,
    })
}

fn keep_last_paths(class_policy: &ClassPolicy, rows: &[&CensusRow]) -> BTreeSet<String> {
    let keep = class_policy.keep_last_n.unwrap_or(0) as usize;
    if keep == 0 {
        return BTreeSet::new();
    }
    let mut series: BTreeMap<&str, Vec<&CensusRow>> = BTreeMap::new();
    for row in rows {
        if let Some(checkpoint) = &row.checkpoint {
            series.entry(&checkpoint.series).or_default().push(row);
        }
    }
    let mut retained = BTreeSet::new();
    for mut group in series.into_values() {
        group.sort_by(|left, right| {
            let left_checkpoint = left.checkpoint.as_ref().expect("grouped checkpoint");
            let right_checkpoint = right.checkpoint.as_ref().expect("grouped checkpoint");
            (right_checkpoint.sequence, &right.relative_path)
                .cmp(&(left_checkpoint.sequence, &left.relative_path))
        });
        retained.extend(
            group
                .into_iter()
                .take(keep)
                .map(|row| row.relative_path.clone()),
        );
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

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn canonical_json_sha256(value: &impl Serialize) -> Result<String, PlanError> {
    serde_json::to_vec(value)
        .map(|bytes| sha256_hex(&bytes))
        .map_err(|error| PlanError::Serialization(error.to_string()))
}
