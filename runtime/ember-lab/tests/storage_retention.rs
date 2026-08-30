// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::storage_retention::{
    build_plan, canonical_json_sha256, parse_policy, Census, CensusRow, CheckpointIdentity,
    CustodyClass, Disposition, DuplicateWitness, PlanError,
};
use serde_json::{json, Value};

fn policy_value() -> Value {
    json!({
        "schema_version": "ember-storage-retention-policy-v1",
        "filing_source_commit": "9da57fa0ed806936901564ed9d01a97b6b6afcfa",
        "classes": [
            {
                "class": "models",
                "canonical_root": "models",
                "filing_total_bytes": 1_000,
                "protected_lower_bound_bytes": 500,
                "admitted_growth_envelope_bytes": 200,
                "hard_quota_bytes": 700,
                "keep_last_n": 2,
                "grace_seconds": 86_400,
                "maximum_reconcile_bytes": 300
            },
            {
                "class": "state",
                "canonical_root": "state",
                "filing_total_bytes": 1_000,
                "protected_lower_bound_bytes": 600,
                "admitted_growth_envelope_bytes": 10,
                "hard_quota_bytes": 660,
                "keep_last_n": null,
                "grace_seconds": 86_400,
                "maximum_reconcile_bytes": 300
            }
        ]
    })
}

fn raw(value: &Value) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(value).unwrap();
    bytes.push(b'\n');
    bytes
}

fn row(
    class: CustodyClass,
    path: &str,
    bytes: u64,
    disposition: Disposition,
    modified_ns: u64,
) -> CensusRow {
    CensusRow {
        class,
        relative_path: path.into(),
        bytes,
        raw_sha256: format!("{:064x}", bytes),
        physical_identity: format!("volume-1:file-{path}"),
        modified_ns,
        disposition,
        pin_reasons: Vec::new(),
        checkpoint: None,
        duplicate_witness: None,
    }
}

#[test]
fn strict_policy_accepts_exact_derived_quotas() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    assert_eq!(policy.classes.len(), 2);
    assert_eq!(policy.classes[0].class, CustodyClass::Models);
    assert_eq!(policy.classes[1].class, CustodyClass::State);
    assert_eq!(policy.classes[1].hard_quota_bytes, 660);
}

#[test]
fn strict_policy_refuses_unknown_fields_missing_classes_overlap_and_post_result_quota_edits() {
    let mut unknown = policy_value();
    unknown["classes"][0]["surprise"] = json!(true);
    assert!(parse_policy(&raw(&unknown))
        .unwrap_err()
        .to_string()
        .contains("unknown field"));

    let mut missing = policy_value();
    missing["classes"].as_array_mut().unwrap().pop();
    assert!(parse_policy(&raw(&missing))
        .unwrap_err()
        .to_string()
        .contains("exactly models and state"));

    let mut overlap = policy_value();
    overlap["classes"][1]["canonical_root"] = json!("models/child");
    assert!(parse_policy(&raw(&overlap))
        .unwrap_err()
        .to_string()
        .contains("overlap"));

    let mut quota = policy_value();
    quota["classes"][0]["hard_quota_bytes"] = json!(701);
    assert!(parse_policy(&raw(&quota))
        .unwrap_err()
        .to_string()
        .contains("derived quota"));

    let mut vacuous = policy_value();
    vacuous["classes"][0]["hard_quota_bytes"] = json!(1_000);
    vacuous["classes"][0]["protected_lower_bound_bytes"] = json!(800);
    vacuous["classes"][0]["admitted_growth_envelope_bytes"] = json!(200);
    assert!(parse_policy(&raw(&vacuous))
        .unwrap_err()
        .to_string()
        .contains("strictly below filing total"));
}

#[test]
fn identical_inputs_produce_byte_identical_plan_and_hash() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let census = Census::new(vec![
        row(
            CustodyClass::Models,
            "latest.bin",
            500,
            Disposition::Protected,
            30,
        ),
        row(
            CustodyClass::Models,
            "cache-old.bin",
            300,
            Disposition::Reproducible,
            10,
        ),
        row(
            CustodyClass::Models,
            "cache-new.bin",
            200,
            Disposition::Reproducible,
            20,
        ),
        row(
            CustodyClass::State,
            "active.json",
            600,
            Disposition::Protected,
            30,
        ),
        row(
            CustodyClass::State,
            "terminal-old.json",
            200,
            Disposition::TerminalCompressible,
            10,
        ),
        row(
            CustodyClass::State,
            "cache.json",
            100,
            Disposition::Reproducible,
            20,
        ),
    ])
    .unwrap();
    let a = build_plan(
        &policy,
        &census,
        "a".repeat(64).as_str(),
        "b".repeat(40).as_str(),
    )
    .unwrap();
    let b = build_plan(
        &policy,
        &census,
        "a".repeat(64).as_str(),
        "b".repeat(40).as_str(),
    )
    .unwrap();
    assert_eq!(a, b);
    assert_eq!(
        a.self_sha256,
        canonical_json_sha256(&a.without_self_hash()).unwrap()
    );
    assert_eq!(a.rows[0].relative_path, "cache-old.bin");
    assert_eq!(a.rows[1].relative_path, "terminal-old.json");
}

#[test]
fn total_census_and_planner_refuse_unknown_duplicate_or_unsafe_rows() {
    assert!(matches!(
        Census::new(vec![
            row(CustodyClass::State, "same", 1, Disposition::Reproducible, 0),
            row(CustodyClass::State, "same", 1, Disposition::Reproducible, 0),
        ]),
        Err(PlanError::DuplicatePath(_))
    ));

    let policy = parse_policy(&raw(&policy_value())).unwrap();
    for disposition in [
        Disposition::Unknown,
        Disposition::PathEscape,
        Disposition::ReparsePoint,
        Disposition::HardlinkAmbiguous,
    ] {
        let census =
            Census::new(vec![row(CustodyClass::State, "unsafe", 1, disposition, 0)]).unwrap();
        assert!(matches!(
            build_plan(&policy, &census, &"a".repeat(64), &"b".repeat(40)),
            Err(PlanError::RefusalRows(_))
        ));
    }
}

#[test]
fn protected_bytes_and_exact_boundary_are_enforced_before_selection() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let over = Census::new(vec![row(
        CustodyClass::Models,
        "sole.bin",
        701,
        Disposition::Protected,
        0,
    )])
    .unwrap();
    assert!(matches!(
        build_plan(&policy, &over, &"a".repeat(64), &"b".repeat(40)),
        Err(PlanError::ProtectedBytesExceedQuota { .. })
    ));

    let exact = Census::new(vec![row(
        CustodyClass::Models,
        "sole.bin",
        700,
        Disposition::Protected,
        0,
    )])
    .unwrap();
    let plan = build_plan(&policy, &exact, &"a".repeat(64), &"b".repeat(40)).unwrap();
    assert!(plan.rows.is_empty());
}

#[test]
fn pin_reasons_override_reclaimable_disposition_and_maximum_reconcile_is_fail_closed() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let mut pinned = row(
        CustodyClass::Models,
        "pinned.bin",
        500,
        Disposition::Reproducible,
        0,
    );
    pinned.pin_reasons.push("receipt:abc".into());
    let census = Census::new(vec![
        row(
            CustodyClass::Models,
            "live.bin",
            500,
            Disposition::Protected,
            10,
        ),
        pinned,
    ])
    .unwrap();
    assert!(matches!(
        build_plan(&policy, &census, &"a".repeat(64), &"b".repeat(40)),
        Err(PlanError::ProtectedBytesExceedQuota { .. })
    ));

    let over_cap = Census::new(vec![
        row(
            CustodyClass::Models,
            "protected.bin",
            700,
            Disposition::Protected,
            10,
        ),
        row(
            CustodyClass::Models,
            "eligible.bin",
            350,
            Disposition::Reproducible,
            0,
        ),
    ])
    .unwrap();
    assert!(matches!(
        build_plan(&policy, &over_cap, &"a".repeat(64), &"b".repeat(40)),
        Err(PlanError::InsufficientEligibleBytes { .. })
    ));
}

#[test]
fn changed_after_plan_identity_is_detectable_from_bound_row() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let census = Census::new(vec![
        row(
            CustodyClass::Models,
            "live.bin",
            500,
            Disposition::Protected,
            10,
        ),
        row(
            CustodyClass::Models,
            "old.bin",
            300,
            Disposition::Reproducible,
            0,
        ),
    ])
    .unwrap();
    let plan = build_plan(&policy, &census, &"a".repeat(64), &"b".repeat(40)).unwrap();
    assert_eq!(plan.rows.len(), 1);
    assert!(plan.rows[0].matches_observation(
        300,
        &format!("{:064x}", 300),
        "volume-1:file-old.bin",
        0
    ));
    assert!(!plan.rows[0].matches_observation(
        301,
        &format!("{:064x}", 300),
        "volume-1:file-old.bin",
        0
    ));
}

#[test]
fn keep_last_n_is_enforced_by_the_planner_even_if_classifier_marks_rows_reclaimable() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let mut rows = Vec::new();
    for sequence in 1..=3 {
        let mut checkpoint = row(
            CustodyClass::Models,
            &format!("series/checkpoint-{sequence}.bin"),
            300,
            Disposition::Reproducible,
            sequence,
        );
        checkpoint.checkpoint = Some(CheckpointIdentity {
            series: "series-a".into(),
            sequence,
        });
        rows.push(checkpoint);
    }
    let plan = build_plan(
        &policy,
        &Census::new(rows).unwrap(),
        &"a".repeat(64),
        &"b".repeat(40),
    )
    .unwrap();
    assert_eq!(plan.rows.len(), 1);
    assert_eq!(plan.rows[0].relative_path, "series/checkpoint-1.bin");
    assert_eq!(plan.classes[&CustodyClass::Models].protected_bytes, 600);
}

#[test]
fn duplicate_reclamation_requires_an_independently_reopened_matching_copy() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let mut duplicate = row(
        CustodyClass::Models,
        "duplicate.bin",
        300,
        Disposition::DuplicateReclaimable,
        0,
    );
    let missing = Census::new(vec![duplicate.clone()]);
    assert!(matches!(missing, Err(PlanError::InvalidIdentity(_))));

    duplicate.duplicate_witness = Some(DuplicateWitness {
        retained_relative_path: "retained.bin".into(),
        retained_raw_sha256: duplicate.raw_sha256.clone(),
        retained_physical_identity: "volume-1:file-retained.bin".into(),
        authority_identity: "checkpoint-authority:series-a:1".into(),
        independently_reopened: true,
    });
    let plan = build_plan(
        &policy,
        &Census::new(vec![
            row(
                CustodyClass::Models,
                "protected.bin",
                400,
                Disposition::Protected,
                1,
            ),
            row(
                CustodyClass::Models,
                "retained.bin",
                300,
                Disposition::Protected,
                1,
            ),
            duplicate,
        ])
        .unwrap(),
        &"a".repeat(64),
        &"b".repeat(40),
    )
    .unwrap();
    assert_eq!(plan.rows[0].relative_path, "duplicate.bin");
}
