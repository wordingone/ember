// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//! Fail-closed host resource admission and exact owned-tree termination planning.
//!
//! This module is deliberately a policy boundary rather than a process-control
//! implementation. A future Ember supervisor may use the returned plan only
//! after recording the receipt and revalidating the exact PID/HWND/process-tree
//! identity. It never authorizes name-based or foreign-process termination.

use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GpuTenancy {
    Owned,
    None,
    Foreign,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ChildLiveness {
    Alive,
    Dead,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostResourceLimits {
    pub minimum_ram_available_bytes: u64,
    pub minimum_commit_available_bytes: u64,
    pub minimum_driver_locked_available_bytes: u64,
    pub minimum_c_free_bytes: u64,
    pub minimum_b_free_bytes: u64,
    pub maximum_process_count: u64,
    pub maximum_process_growth: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostResourceSample {
    pub observed_at_ms: u64,
    pub ram_available_bytes: Option<u64>,
    pub commit_available_bytes: Option<u64>,
    pub commit_limit_bytes: Option<u64>,
    pub driver_locked_available_bytes: Option<u64>,
    pub c_free_bytes: Option<u64>,
    pub b_free_bytes: Option<u64>,
    pub gpu_tenancy: GpuTenancy,
    pub process_count: Option<u64>,
    pub process_growth: Option<u64>,
    pub child_liveness: ChildLiveness,
    pub foreign_pressure: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnedProcessTree {
    pub lease_id: String,
    pub root_pid: u32,
    pub child_pids: BTreeSet<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedProcessTree {
    pub lease_id: Option<String>,
    pub root_pid: u32,
    pub pids: BTreeSet<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreflightReceipt {
    pub status: &'static str,
    pub scope: &'static str,
    pub observed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminationPlan {
    pub root_pid: u32,
    pub pids: Vec<u32>,
    pub scope: &'static str,
    pub receipt_required: bool,
    pub reason: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernorError {
    pub reason: String,
}

impl std::fmt::Display for GovernorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.reason)
    }
}

impl std::error::Error for GovernorError {}

type GovernorResult<T> = std::result::Result<T, GovernorError>;

fn error(reason: impl Into<String>) -> GovernorError {
    GovernorError {
        reason: reason.into(),
    }
}

fn require_metric<T: Copy>(value: Option<T>, name: &str) -> GovernorResult<T> {
    value.ok_or_else(|| error(format!("missing decisive metric: {name}")))
}

fn local_breach_reasons(
    sample: &HostResourceSample,
    limits: &HostResourceLimits,
) -> GovernorResult<Vec<String>> {
    let ram = require_metric(sample.ram_available_bytes, "ram_available_bytes")?;
    let commit = require_metric(sample.commit_available_bytes, "commit_available_bytes")?;
    let commit_limit = require_metric(sample.commit_limit_bytes, "commit_limit_bytes")?;
    let driver = require_metric(
        sample.driver_locked_available_bytes,
        "driver_locked_available_bytes",
    )?;
    let c_free = require_metric(sample.c_free_bytes, "c_free_bytes")?;
    let b_free = require_metric(sample.b_free_bytes, "b_free_bytes")?;
    let process_count = require_metric(sample.process_count, "process_count")?;
    let process_growth = require_metric(sample.process_growth, "process_growth")?;

    if commit > commit_limit {
        return Err(error(
            "invalid host sample: commit_available_bytes exceeds commit_limit_bytes",
        ));
    }

    let mut reasons = Vec::new();
    if ram < limits.minimum_ram_available_bytes {
        reasons.push(format!("ram_available_bytes below floor ({ram})"));
    }
    if commit < limits.minimum_commit_available_bytes {
        reasons.push(format!("commit_available_bytes below floor ({commit})"));
    }
    if driver < limits.minimum_driver_locked_available_bytes {
        reasons.push(format!(
            "driver_locked_available_bytes below floor ({driver})"
        ));
    }
    if c_free < limits.minimum_c_free_bytes {
        reasons.push(format!("c_free_bytes below floor ({c_free})"));
    }
    if b_free < limits.minimum_b_free_bytes {
        reasons.push(format!("b_free_bytes below floor ({b_free})"));
    }
    if process_count > limits.maximum_process_count {
        reasons.push(format!("process_count exceeds ceiling ({process_count})"));
    }
    if process_growth > limits.maximum_process_growth {
        reasons.push(format!("process_growth exceeds ceiling ({process_growth})"));
    }
    Ok(reasons)
}

fn require_owned_live_sample(sample: &HostResourceSample) -> GovernorResult<()> {
    if sample.foreign_pressure {
        return Err(error(
            "foreign/system pressure is not an owned-tree termination authorization",
        ));
    }
    if sample.gpu_tenancy != GpuTenancy::Owned {
        return Err(error(format!(
            "gpu tenancy is foreign/unknown/not owned: {:?}",
            sample.gpu_tenancy
        )));
    }
    if sample.child_liveness != ChildLiveness::Alive {
        return Err(error(format!(
            "owned child liveness is not proven: {:?}",
            sample.child_liveness
        )));
    }
    Ok(())
}

pub fn evaluate_preflight(
    sample: &HostResourceSample,
    limits: &HostResourceLimits,
) -> GovernorResult<PreflightReceipt> {
    require_owned_live_sample(sample)?;
    let reasons = local_breach_reasons(sample, limits)?;
    if let Some(reason) = reasons.first() {
        return Err(error(format!("host preflight refused: {reason}")));
    }
    Ok(PreflightReceipt {
        status: "ADMITTED",
        scope: "registered_owned_tree",
        observed_at_ms: sample.observed_at_ms,
    })
}

fn verify_exact_tree(
    owned: &OwnedProcessTree,
    observed: &ObservedProcessTree,
) -> GovernorResult<Vec<u32>> {
    if owned.lease_id.is_empty() || observed.lease_id.as_deref() != Some(owned.lease_id.as_str()) {
        return Err(error("owned-tree lease identity mismatch"));
    }
    if observed.root_pid != owned.root_pid || owned.root_pid == 0 {
        return Err(error("owned-tree root PID identity mismatch"));
    }
    if owned.child_pids.contains(&owned.root_pid) || owned.child_pids.contains(&0) {
        return Err(error("owned-tree PID set is malformed"));
    }
    let mut expected = owned.child_pids.clone();
    expected.insert(owned.root_pid);
    if observed.pids != expected || observed.pids.contains(&0) {
        return Err(error(
            "observed process tree contains an unowned or missing PID",
        ));
    }
    Ok(expected.into_iter().collect())
}

pub fn plan_termination(
    sample: &HostResourceSample,
    limits: &HostResourceLimits,
    owned: &OwnedProcessTree,
    observed: &ObservedProcessTree,
) -> GovernorResult<TerminationPlan> {
    require_owned_live_sample(sample)?;
    let reasons = local_breach_reasons(sample, limits)?;
    if reasons.is_empty() {
        return Err(error("no owned threshold breach requires termination"));
    }
    let pids = verify_exact_tree(owned, observed)?;
    Ok(TerminationPlan {
        root_pid: owned.root_pid,
        pids,
        scope: "exact_owned_process_tree",
        receipt_required: true,
        reason: reasons.join("; "),
    })
}
