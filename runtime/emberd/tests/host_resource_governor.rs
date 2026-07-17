// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
use std::collections::BTreeSet;

use emberd::host_resource_governor::{
    evaluate_preflight, plan_termination, ChildLiveness, GpuTenancy, HostResourceLimits,
    HostResourceSample, ObservedProcessTree, OwnedProcessTree,
};

fn limits() -> HostResourceLimits {
    HostResourceLimits {
        minimum_ram_available_bytes: 8,
        minimum_commit_available_bytes: 16,
        minimum_driver_locked_available_bytes: 4,
        minimum_c_free_bytes: 150,
        minimum_b_free_bytes: 250,
        maximum_process_count: 100,
        maximum_process_growth: 2,
    }
}

fn healthy() -> HostResourceSample {
    HostResourceSample {
        observed_at_ms: 10,
        ram_available_bytes: Some(32),
        commit_available_bytes: Some(64),
        commit_limit_bytes: Some(128),
        driver_locked_available_bytes: Some(32),
        c_free_bytes: Some(500),
        b_free_bytes: Some(500),
        gpu_tenancy: GpuTenancy::Owned,
        process_count: Some(10),
        process_growth: Some(1),
        child_liveness: ChildLiveness::Alive,
        foreign_pressure: false,
    }
}

fn owned_tree() -> OwnedProcessTree {
    OwnedProcessTree {
        lease_id: "lease-1".into(),
        root_pid: 42,
        child_pids: BTreeSet::from([43, 44]),
    }
}

fn observed_tree() -> ObservedProcessTree {
    ObservedProcessTree {
        lease_id: Some("lease-1".into()),
        root_pid: 42,
        pids: BTreeSet::from([42, 43, 44]),
    }
}

#[test]
fn complete_preflight_admits_only_owned_live_resources() {
    let receipt = evaluate_preflight(&healthy(), &limits()).expect("healthy sample should admit");
    assert_eq!(receipt.status, "ADMITTED");
    assert_eq!(receipt.scope, "registered_owned_tree");
}

#[test]
fn missing_decisive_metric_fails_closed() {
    let mut sample = healthy();
    sample.commit_available_bytes = None;
    let error = evaluate_preflight(&sample, &limits()).expect_err("missing commit must refuse");
    assert!(error.reason.contains("commit_available_bytes"));
}

#[test]
fn foreign_gpu_tenancy_refuses_without_kill_plan() {
    let mut sample = healthy();
    sample.gpu_tenancy = GpuTenancy::Foreign;
    let error = evaluate_preflight(&sample, &limits()).expect_err("foreign GPU must refuse");
    assert!(error.reason.contains("foreign"));
    assert!(plan_termination(&sample, &limits(), &owned_tree(), &observed_tree()).is_err());
}

#[test]
fn foreign_or_system_pressure_never_authorizes_broad_termination() {
    let mut sample = healthy();
    sample.foreign_pressure = true;
    let error = plan_termination(&sample, &limits(), &owned_tree(), &observed_tree())
        .expect_err("system pressure is not an owned breach");
    assert!(error.reason.contains("foreign/system"));
}

#[test]
fn local_threshold_breach_plans_exact_owned_tree_only() {
    let mut sample = healthy();
    sample.ram_available_bytes = Some(2);
    let plan = plan_termination(&sample, &limits(), &owned_tree(), &observed_tree())
        .expect("owned RAM breach should plan exact-tree termination");
    assert_eq!(plan.root_pid, 42);
    assert_eq!(plan.pids, vec![42, 43, 44]);
    assert_eq!(plan.scope, "exact_owned_process_tree");
    assert!(plan.receipt_required);
    assert!(plan.reason.contains("ram_available_bytes"));
}

#[test]
fn process_growth_and_c_b_floor_are_real_breach_reasons() {
    let mut sample = healthy();
    sample.process_growth = Some(3);
    let plan = plan_termination(&sample, &limits(), &owned_tree(), &observed_tree()).unwrap();
    assert!(plan.reason.contains("process_growth"));

    sample.process_growth = Some(1);
    sample.c_free_bytes = Some(149);
    let plan = plan_termination(&sample, &limits(), &owned_tree(), &observed_tree()).unwrap();
    assert!(plan.reason.contains("c_free_bytes"));
}

#[test]
fn mismatched_lease_pid_or_foreign_child_refuses_fail_closed() {
    let mut observed = observed_tree();
    observed.lease_id = Some("other-lease".into());
    let mut sample = healthy();
    sample.ram_available_bytes = Some(2);
    assert!(plan_termination(&sample, &limits(), &owned_tree(), &observed).is_err());

    let mut observed = observed_tree();
    observed.pids.insert(99);
    assert!(plan_termination(&sample, &limits(), &owned_tree(), &observed).is_err());
}

#[test]
fn dead_or_unknown_child_liveness_is_not_a_kill_authorization() {
    let mut sample = healthy();
    sample.child_liveness = ChildLiveness::Dead;
    assert!(evaluate_preflight(&sample, &limits()).is_err());
    sample.child_liveness = ChildLiveness::Unknown;
    assert!(evaluate_preflight(&sample, &limits()).is_err());
}
