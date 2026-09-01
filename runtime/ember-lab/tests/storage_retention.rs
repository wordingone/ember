// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::storage_retention::{
    build_plan, build_plan_for_growth, canonical_json_sha256, census_filesystem, execute_plan,
    observe_file, parse_policy, recover_plan, reopen_remote_master, run_storage_reconcile, Census,
    CensusDeclaration, CensusRow, CheckpointIdentity, CustodyClass, Disposition, DuplicateWitness,
    ExecutionError, ExecutionFault, ExecutionMode, PlanError, ReconcileOperation, RecoveryAction,
    StorageReconcileRequest, TerminalKernelWitness,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

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
                "protected_predicates": ["active_process_root", "open_run_custody", "nonterminal_attempt", "registered_campaign_evidence", "independently_pinned_checkpoint", "receipt_dependency", "sole_verified_copy"],
                "eligibility_predicates": ["reproducible", "verified_duplicate_copy"],
                "compression_rule": "none",
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
                "protected_predicates": ["active_process_root", "open_run_custody", "nonterminal_attempt", "registered_campaign_evidence", "receipt_dependency"],
                "eligibility_predicates": ["reproducible", "terminal_receipt_kernel"],
                "compression_rule": "terminal_receipt_kernel_v1",
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

#[test]
fn issue1987_filed_policy_satisfies_the_strict_runtime_schema() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../manifests/issue1987-storage-retention-policy-v4.json");
    let filed = fs::read(path).expect("issue1987 v4 policy must be filed");
    parse_policy(&filed).expect("issue1987 v4 policy must satisfy the strict runtime schema");
}

#[test]
fn current_master_is_reopened_from_repository_authority() {
    let root = std::env::temp_dir().join(format!(
        "ember-storage-master-authority-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let remote_ref = root.join(".git/refs/remotes/origin/master");
    fs::create_dir_all(remote_ref.parent().unwrap()).unwrap();
    let expected = "0123456789abcdef0123456789abcdef01234567";
    fs::write(&remote_ref, format!("{expected}\n")).unwrap();
    assert_eq!(reopen_remote_master(&root).unwrap(), expected);

    fs::write(&remote_ref, "caller-controlled-not-a-commit\n").unwrap();
    assert!(reopen_remote_master(&root).is_err());
}

#[test]
fn direct_reconcile_refuses_a_pin_set_that_does_not_match_reopened_declarations() {
    let root = std::env::temp_dir().join(format!(
        "ember-storage-pin-reopen-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let models = root.join("models");
    let state = root.join("state");
    fs::create_dir_all(&models).unwrap();
    fs::create_dir_all(&state).unwrap();
    let policy = root.join("policy.json");
    fs::write(&policy, raw(&policy_value())).unwrap();
    let declarations = root.join("declarations.json");
    fs::write(&declarations, b"[]\n").unwrap();
    let custody = root.join("custody");
    let request = StorageReconcileRequest {
        repository_root: root,
        policy,
        declarations,
        models_root: models,
        state_root: state,
        custody: custody.clone(),
        pin_set_sha256: "a".repeat(64),
        current_master: "b".repeat(40),
        projected_growth: BTreeMap::from([(CustodyClass::Models, 0), (CustodyClass::State, 0)]),
        operation: ReconcileOperation::DryRun,
    };
    assert!(run_storage_reconcile(&request).is_err());
    assert!(!custody.exists());
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
        terminal_kernel_witness: None,
    }
}

#[test]
fn strict_policy_accepts_exact_derived_quotas() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    assert_eq!(policy.classes.len(), 2);
    assert_eq!(policy.classes[0].class, CustodyClass::Models);
    assert_eq!(policy.classes[1].class, CustodyClass::State);
    assert_eq!(policy.classes[1].hard_quota_bytes, 660);
    assert_eq!(policy.classes[0].compression_rule, "none");
    assert_eq!(
        policy.classes[1].compression_rule,
        "terminal_receipt_kernel_v1"
    );
}

#[test]
fn strict_policy_refuses_missing_or_cross_class_retention_predicates() {
    let mut missing = policy_value();
    missing["classes"][1]
        .as_object_mut()
        .unwrap()
        .remove("compression_rule");
    assert!(parse_policy(&raw(&missing)).is_err());

    let mut models_compression = policy_value();
    models_compression["classes"][0]["compression_rule"] = json!("terminal_receipt_kernel_v1");
    assert!(parse_policy(&raw(&models_compression))
        .unwrap_err()
        .to_string()
        .contains("models compression_rule"));

    let mut state_without_kernel = policy_value();
    state_without_kernel["classes"][1]["eligibility_predicates"] = json!(["reproducible"]);
    assert!(parse_policy(&raw(&state_without_kernel))
        .unwrap_err()
        .to_string()
        .contains("state eligibility_predicates"));
}

#[test]
fn projected_spawn_growth_accepts_exact_boundary_and_refuses_quota_plus_one() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let census = Census::new(vec![
        row(
            CustodyClass::Models,
            "protected.bin",
            500,
            Disposition::Protected,
            1,
        ),
        row(
            CustodyClass::Models,
            "eligible.bin",
            200,
            Disposition::Reproducible,
            2,
        ),
        row(
            CustodyClass::State,
            "protected.bin",
            600,
            Disposition::Protected,
            1,
        ),
    ])
    .unwrap();
    let exact = BTreeMap::from([(CustodyClass::Models, 200), (CustodyClass::State, 60)]);
    let plan =
        build_plan_for_growth(&policy, &census, &"a".repeat(64), &"b".repeat(40), &exact).unwrap();
    assert_eq!(
        plan.classes[&CustodyClass::Models].projected_growth_bytes,
        200
    );
    assert_eq!(
        plan.classes[&CustodyClass::Models].projected_after_bytes,
        500
    );
    let above = BTreeMap::from([(CustodyClass::Models, 201), (CustodyClass::State, 60)]);
    assert!(matches!(
        build_plan_for_growth(&policy, &census, &"a".repeat(64), &"b".repeat(40), &above,),
        Err(PlanError::InsufficientEligibleBytes {
            class: CustodyClass::Models,
            ..
        })
    ));
}

#[test]
fn planner_refuses_to_reclaim_rows_inside_the_declared_grace_interval() {
    let policy = parse_policy(&raw(&policy_value())).unwrap();
    let observed_at_ns = 200_000_000_000_000_u64;
    let recent_modified_ns = observed_at_ns - 1_000_000_000;
    let census = Census::new_at(
        vec![
            row(
                CustodyClass::Models,
                "protected.bin",
                500,
                Disposition::Protected,
                1,
            ),
            row(
                CustodyClass::Models,
                "recent.bin",
                300,
                Disposition::Reproducible,
                recent_modified_ns,
            ),
            row(
                CustodyClass::State,
                "protected.bin",
                600,
                Disposition::Protected,
                1,
            ),
        ],
        observed_at_ns,
    )
    .unwrap();
    assert!(matches!(
        build_plan(&policy, &census, &"a".repeat(64), &"b".repeat(40)),
        Err(PlanError::InsufficientEligibleBytes {
            class: CustodyClass::Models,
            eligible_bytes: 0,
            ..
        })
    ));
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
    let mut kernel = row(
        CustodyClass::State,
        "terminal-kernel.json",
        20,
        Disposition::Protected,
        31,
    );
    kernel
        .pin_reasons
        .push("terminal_receipt_kernel:receipt:determinism".into());
    let mut terminal = row(
        CustodyClass::State,
        "terminal-old.json",
        200,
        Disposition::TerminalCompressible,
        10,
    );
    terminal.terminal_kernel_witness = Some(TerminalKernelWitness {
        retained_relative_path: kernel.relative_path.clone(),
        retained_raw_sha256: kernel.raw_sha256.clone(),
        receipt_identity: "receipt:determinism".into(),
        independently_reopened: true,
    });
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
        kernel,
        terminal,
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
fn terminal_compression_requires_an_independently_reopened_receipt_kernel() {
    let mut envelope = row(
        CustodyClass::State,
        "terminal/run/payload.bin",
        200,
        Disposition::TerminalCompressible,
        10,
    );
    envelope.terminal_kernel_witness = Some(TerminalKernelWitness {
        retained_relative_path: "terminal/run/terminal.json".into(),
        retained_raw_sha256: format!("{:064x}", 20),
        receipt_identity: "receipt:terminal-run".into(),
        independently_reopened: true,
    });
    let mut kernel = row(
        CustodyClass::State,
        "terminal/run/terminal.json",
        20,
        Disposition::Protected,
        11,
    );
    kernel
        .pin_reasons
        .push("terminal_receipt_kernel:receipt:terminal-run".into());
    assert!(Census::new(vec![envelope.clone(), kernel]).is_ok());

    envelope
        .terminal_kernel_witness
        .as_mut()
        .unwrap()
        .independently_reopened = false;
    assert!(Census::new(vec![envelope]).is_err());
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
    assert!(matches!(
        Census::new(vec![
            row(
                CustodyClass::State,
                "Case.bin",
                1,
                Disposition::Reproducible,
                0
            ),
            row(
                CustodyClass::State,
                "case.bin",
                1,
                Disposition::Reproducible,
                0
            ),
        ]),
        Err(PlanError::DuplicatePath(_))
    ));
    assert!(Census::new(vec![row(
        CustodyClass::State,
        "empty.bin",
        0,
        Disposition::Protected,
        0,
    )])
    .is_ok());

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
fn filesystem_census_is_total_and_unknown_files_refuse_planning() {
    let fixture = Fixture::new("total-filesystem-census");
    fs::write(fixture.root.join("models/declared.bin"), b"model").unwrap();
    fs::write(fixture.root.join("models/empty.bin"), b"").unwrap();
    fs::write(fixture.root.join("state/unknown.bin"), b"state").unwrap();
    let declarations = vec![
        CensusDeclaration {
            class: CustodyClass::Models,
            relative_path: "declared.bin".into(),
            disposition: Disposition::Protected,
            pin_reasons: vec!["active-model".into()],
            checkpoint: None,
            duplicate_witness: None,
            terminal_kernel_witness: None,
        },
        CensusDeclaration {
            class: CustodyClass::Models,
            relative_path: "empty.bin".into(),
            disposition: Disposition::Protected,
            pin_reasons: vec!["empty-marker".into()],
            checkpoint: None,
            duplicate_witness: None,
            terminal_kernel_witness: None,
        },
    ];
    let census = census_filesystem(&fixture.roots(), declarations).unwrap();
    assert_eq!(census.rows.len(), 3);
    assert_eq!(census.rows.iter().map(|row| row.bytes).sum::<u64>(), 10);
    assert!(census
        .rows
        .iter()
        .any(|row| row.relative_path == "unknown.bin" && row.disposition == Disposition::Unknown));
    assert!(matches!(
        build_plan(
            &parse_policy(&raw(&policy_value())).unwrap(),
            &census,
            &"a".repeat(64),
            &"b".repeat(40),
        ),
        Err(PlanError::RefusalRows(_))
    ));
}

#[test]
fn duplicate_witness_identity_encoding_refuses_before_full_census() {
    let fixture = Fixture::new("duplicate-witness-encoding-preflight");
    let retained = fixture.root.join("models/retained.bin");
    fs::write(&retained, b"same immutable payload").unwrap();
    fs::write(
        fixture.root.join("models/duplicate.bin"),
        b"same immutable payload",
    )
    .unwrap();
    // This unrelated payload proves the malformed declaration is rejected by
    // the declaration preflight, before a recursive census can hash the tree.
    fs::write(
        fixture.root.join("state/unrelated.bin"),
        vec![7_u8; 8 * 1024 * 1024],
    )
    .unwrap();
    let observed = observe_file(&retained).unwrap();
    let malformed = "windows:506082675:1688849860269113".to_string();
    let declarations = vec![
        CensusDeclaration {
            class: CustodyClass::Models,
            relative_path: "retained.bin".into(),
            disposition: Disposition::Protected,
            pin_reasons: vec!["sole-verified-copy".into()],
            checkpoint: None,
            duplicate_witness: None,
            terminal_kernel_witness: None,
        },
        CensusDeclaration {
            class: CustodyClass::Models,
            relative_path: "duplicate.bin".into(),
            disposition: Disposition::DuplicateReclaimable,
            pin_reasons: Vec::new(),
            checkpoint: None,
            duplicate_witness: Some(DuplicateWitness {
                retained_relative_path: "retained.bin".into(),
                retained_raw_sha256: observed.raw_sha256,
                retained_physical_identity: malformed,
                authority_identity: "readonly-census:test".into(),
                independently_reopened: true,
            }),
            terminal_kernel_witness: None,
        },
    ];
    let started = Instant::now();
    let error = census_filesystem(&fixture.roots(), declarations).unwrap_err();
    assert!(started.elapsed().as_secs() < 5);
    assert!(error
        .to_string()
        .contains("windows physical identity must match windows:8-lower-hex:16-lower-hex"));
}

#[test]
fn duplicate_witness_preflight_binds_canonical_retained_identity_and_refuses_drift() {
    let fixture = Fixture::new("duplicate-witness-retained-preflight");
    let retained = fixture.root.join("models/retained.bin");
    fs::write(&retained, b"same immutable payload").unwrap();
    fs::write(
        fixture.root.join("models/duplicate.bin"),
        b"same immutable payload",
    )
    .unwrap();
    let observed = observe_file(&retained).unwrap();
    let declarations = |physical_identity: String| {
        vec![
            CensusDeclaration {
                class: CustodyClass::Models,
                relative_path: "retained.bin".into(),
                disposition: Disposition::Protected,
                pin_reasons: vec!["sole-verified-copy".into()],
                checkpoint: None,
                duplicate_witness: None,
                terminal_kernel_witness: None,
            },
            CensusDeclaration {
                class: CustodyClass::Models,
                relative_path: "duplicate.bin".into(),
                disposition: Disposition::DuplicateReclaimable,
                pin_reasons: Vec::new(),
                checkpoint: None,
                duplicate_witness: Some(DuplicateWitness {
                    retained_relative_path: "retained.bin".into(),
                    retained_raw_sha256: observed.raw_sha256.clone(),
                    retained_physical_identity: physical_identity,
                    authority_identity: "readonly-census:test".into(),
                    independently_reopened: true,
                }),
                terminal_kernel_witness: None,
            },
        ]
    };
    let census = census_filesystem(
        &fixture.roots(),
        declarations(observed.physical_identity.clone()),
    )
    .unwrap();
    assert_eq!(census.rows.len(), 2);

    let mut drifted = observed.physical_identity;
    let replacement = if drifted.ends_with('0') { '1' } else { '0' };
    drifted.pop();
    drifted.push(replacement);
    let started = Instant::now();
    let error = census_filesystem(&fixture.roots(), declarations(drifted)).unwrap_err();
    assert!(started.elapsed().as_secs() < 5);
    assert!(error
        .to_string()
        .contains("duplicate witness retained observation mismatch"));
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
fn keep_last_n_preserves_every_file_in_the_retained_checkpoint_group() {
    let mut value = policy_value();
    value["classes"][0]["filing_total_bytes"] = json!(2_000);
    value["classes"][0]["protected_lower_bound_bytes"] = json!(600);
    value["classes"][0]["admitted_growth_envelope_bytes"] = json!(100);
    value["classes"][0]["hard_quota_bytes"] = json!(700);
    value["classes"][0]["keep_last_n"] = json!(1);
    value["classes"][0]["maximum_reconcile_bytes"] = json!(600);
    let policy = parse_policy(&raw(&value)).unwrap();
    let mut rows = Vec::new();
    for sequence in 1..=2 {
        for file in ["model.pt", "optimizer.pt"] {
            let mut checkpoint = row(
                CustodyClass::Models,
                &format!("series/checkpoint-{sequence}/{file}"),
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
    }
    let plan = build_plan(
        &policy,
        &Census::new(rows).unwrap(),
        &"a".repeat(64),
        &"b".repeat(40),
    )
    .unwrap();
    assert_eq!(
        plan.rows
            .iter()
            .map(|row| row.relative_path.as_str())
            .collect::<Vec<_>>(),
        vec![
            "series/checkpoint-1/model.pt",
            "series/checkpoint-1/optimizer.pt"
        ]
    );
    assert_eq!(plan.classes[&CustodyClass::Models].protected_bytes, 600);
}

#[test]
fn one_checkpoint_identity_cannot_span_multiple_directories() {
    let mut left = row(
        CustodyClass::Models,
        "series/checkpoint-1/model.pt",
        300,
        Disposition::Reproducible,
        1,
    );
    left.checkpoint = Some(CheckpointIdentity {
        series: "series-a".into(),
        sequence: 1,
    });
    let mut right = row(
        CustodyClass::Models,
        "other/checkpoint-1/optimizer.pt",
        300,
        Disposition::Reproducible,
        1,
    );
    right.checkpoint = left.checkpoint.clone();
    assert!(matches!(
        Census::new(vec![left, right]),
        Err(PlanError::InvalidIdentity(_))
    ));
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

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new(name: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "ember-issue1987-{name}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(root.join("models")).unwrap();
        fs::create_dir_all(root.join("state")).unwrap();
        Self { root }
    }

    fn roots(&self) -> BTreeMap<CustodyClass, PathBuf> {
        BTreeMap::from([
            (CustodyClass::Models, self.root.join("models")),
            (CustodyClass::State, self.root.join("state")),
        ])
    }

    fn custody(&self) -> PathBuf {
        self.root.join("custody")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        assert!(self.root.starts_with(std::env::temp_dir()));
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn observed_row(
    root: &Path,
    class: CustodyClass,
    relative_path: &str,
    disposition: Disposition,
) -> CensusRow {
    let observation = observe_file(&root.join(relative_path)).unwrap();
    CensusRow {
        class,
        relative_path: relative_path.into(),
        bytes: observation.bytes,
        raw_sha256: observation.raw_sha256,
        physical_identity: observation.physical_identity,
        modified_ns: observation.modified_ns,
        disposition,
        pin_reasons: Vec::new(),
        checkpoint: None,
        duplicate_witness: None,
        terminal_kernel_witness: None,
    }
}

fn census_after_fixture_grace(rows: Vec<CensusRow>) -> Census {
    let observed_at_ns = rows
        .iter()
        .map(|row| row.modified_ns)
        .max()
        .unwrap()
        .checked_add(86_400_000_000_001)
        .unwrap();
    Census::new_at(rows, observed_at_ns).unwrap()
}

fn fixture_plan(fixture: &Fixture) -> ember_lab::storage_retention::StoragePlan {
    let models = fixture.root.join("models");
    fs::write(models.join("protected.bin"), vec![1_u8; 700]).unwrap();
    fs::write(models.join("eligible.bin"), vec![2_u8; 300]).unwrap();
    fs::write(fixture.root.join("state/protected.bin"), vec![3_u8; 600]).unwrap();
    let census = census_after_fixture_grace(vec![
        observed_row(
            &models,
            CustodyClass::Models,
            "protected.bin",
            Disposition::Protected,
        ),
        observed_row(
            &models,
            CustodyClass::Models,
            "eligible.bin",
            Disposition::Reproducible,
        ),
        observed_row(
            &fixture.root.join("state"),
            CustodyClass::State,
            "protected.bin",
            Disposition::Protected,
        ),
    ]);
    build_plan(
        &parse_policy(&raw(&policy_value())).unwrap(),
        &census,
        &"a".repeat(64),
        &"b".repeat(40),
    )
    .unwrap()
}

#[test]
fn dry_run_publishes_receipts_but_mutates_zero_payload_bytes() {
    let fixture = Fixture::new("dry-run");
    let plan = fixture_plan(&fixture);
    let receipt = execute_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        ExecutionMode::DryRun,
        None,
    )
    .unwrap();
    assert_eq!(receipt.result, "DRY_RUN_PASS");
    assert_eq!(receipt.classes[&CustodyClass::Models].before_bytes, 1000);
    assert_eq!(receipt.classes[&CustodyClass::Models].after_bytes, 1000);
    assert_eq!(receipt.classes[&CustodyClass::State].before_bytes, 600);
    assert_eq!(receipt.classes[&CustodyClass::State].after_bytes, 600);
    assert!(fixture.root.join("models/eligible.bin").is_file());
    assert!(fixture.custody().join("precommit.json").is_file());
    assert!(fixture.custody().join("terminal.json").is_file());
}

#[test]
fn growth_bound_commit_reconciles_present_bytes_before_future_spawn_growth() {
    let fixture = Fixture::new("growth-bound-commit");
    let models = fixture.root.join("models");
    fs::write(models.join("protected.bin"), vec![1_u8; 500]).unwrap();
    fs::write(models.join("eligible.bin"), vec![2_u8; 300]).unwrap();
    fs::write(fixture.root.join("state/protected.bin"), vec![3_u8; 600]).unwrap();
    let census = census_after_fixture_grace(vec![
        observed_row(
            &models,
            CustodyClass::Models,
            "protected.bin",
            Disposition::Protected,
        ),
        observed_row(
            &models,
            CustodyClass::Models,
            "eligible.bin",
            Disposition::Reproducible,
        ),
        observed_row(
            &fixture.root.join("state"),
            CustodyClass::State,
            "protected.bin",
            Disposition::Protected,
        ),
    ]);
    let growth = BTreeMap::from([(CustodyClass::Models, 200), (CustodyClass::State, 60)]);
    let plan = build_plan_for_growth(
        &parse_policy(&raw(&policy_value())).unwrap(),
        &census,
        &"a".repeat(64),
        &"b".repeat(40),
        &growth,
    )
    .unwrap();
    let receipt = execute_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        ExecutionMode::Commit,
        None,
    )
    .unwrap();
    assert_eq!(receipt.classes[&CustodyClass::Models].after_bytes, 500);
    assert_eq!(receipt.classes[&CustodyClass::State].after_bytes, 600);
    assert_eq!(
        receipt.classes[&CustodyClass::Models].after_bytes,
        plan.classes[&CustodyClass::Models].projected_after_bytes
    );
    assert_eq!(
        receipt.classes[&CustodyClass::Models].after_bytes
            + plan.classes[&CustodyClass::Models].projected_growth_bytes,
        plan.classes[&CustodyClass::Models].hard_quota_bytes
    );
}

#[test]
fn terminal_envelope_is_reduced_to_its_exact_receipt_bound_kernel() {
    let fixture = Fixture::new("terminal-kernel-compress");
    let models = fixture.root.join("models");
    let state = fixture.root.join("state");
    fs::write(models.join("protected.bin"), vec![1_u8; 500]).unwrap();
    fs::create_dir_all(state.join("terminal/run")).unwrap();
    fs::write(state.join("protected.bin"), vec![3_u8; 600]).unwrap();
    fs::write(state.join("terminal/run/terminal.json"), vec![4_u8; 20]).unwrap();
    fs::write(state.join("terminal/run/payload.bin"), vec![5_u8; 200]).unwrap();
    let mut kernel = observed_row(
        &state,
        CustodyClass::State,
        "terminal/run/terminal.json",
        Disposition::Protected,
    );
    kernel
        .pin_reasons
        .push("terminal_receipt_kernel:receipt:terminal-run".into());
    let mut envelope = observed_row(
        &state,
        CustodyClass::State,
        "terminal/run/payload.bin",
        Disposition::TerminalCompressible,
    );
    envelope.terminal_kernel_witness = Some(TerminalKernelWitness {
        retained_relative_path: kernel.relative_path.clone(),
        retained_raw_sha256: kernel.raw_sha256.clone(),
        receipt_identity: "receipt:terminal-run".into(),
        independently_reopened: true,
    });
    let census = census_after_fixture_grace(vec![
        observed_row(
            &models,
            CustodyClass::Models,
            "protected.bin",
            Disposition::Protected,
        ),
        observed_row(
            &state,
            CustodyClass::State,
            "protected.bin",
            Disposition::Protected,
        ),
        kernel,
        envelope,
    ]);
    let plan = build_plan(
        &parse_policy(&raw(&policy_value())).unwrap(),
        &census,
        &"a".repeat(64),
        &"b".repeat(40),
    )
    .unwrap();
    assert_eq!(plan.rows.len(), 1);
    assert_eq!(
        plan.rows[0].action,
        ember_lab::storage_retention::PlanAction::Compress
    );
    let receipt = execute_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        ExecutionMode::Commit,
        None,
    )
    .unwrap();
    assert_eq!(receipt.result, "COMMITTED_PASS");
    assert!(!state.join("terminal/run/payload.bin").exists());
    assert_eq!(
        fs::read(state.join("terminal/run/terminal.json")).unwrap(),
        vec![4_u8; 20]
    );
}

#[test]
fn unexplained_class_bytes_refuse_before_precommit_or_mutation() {
    let fixture = Fixture::new("unexplained-bytes");
    let plan = fixture_plan(&fixture);
    fs::write(fixture.root.join("state/unfiled.bin"), vec![7_u8; 1]).unwrap();
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            None,
        ),
        Err(ExecutionError::ObservationDrift(_))
    ));
    assert!(!fixture.custody().exists());
    assert!(fixture.root.join("models/eligible.bin").is_file());
}

#[test]
fn changed_after_plan_refuses_before_precommit_or_mutation() {
    let fixture = Fixture::new("changed");
    let plan = fixture_plan(&fixture);
    fs::write(fixture.root.join("models/eligible.bin"), vec![9_u8; 301]).unwrap();
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            None,
        ),
        Err(ExecutionError::ObservationDrift(_))
    ));
    assert!(!fixture.custody().exists());
    assert!(fixture.root.join("models/eligible.bin").is_file());
}

#[test]
fn protected_row_changed_after_plan_refuses_before_precommit_or_mutation() {
    let fixture = Fixture::new("protected-changed");
    let plan = fixture_plan(&fixture);
    fs::write(fixture.root.join("models/protected.bin"), vec![8_u8; 700]).unwrap();
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            None,
        ),
        Err(ExecutionError::ObservationDrift(_))
    ));
    assert!(!fixture.custody().exists());
    assert!(fixture.root.join("models/eligible.bin").is_file());
}

#[test]
fn interruption_after_quarantine_rolls_back_without_residue() {
    let fixture = Fixture::new("rollback");
    let plan = fixture_plan(&fixture);
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            Some(ExecutionFault::AfterQuarantines(1)),
        ),
        Err(ExecutionError::InjectedInterruption)
    ));
    assert!(!fixture.root.join("models/eligible.bin").exists());
    recover_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        RecoveryAction::Rollback,
    )
    .unwrap();
    assert!(fixture.root.join("models/eligible.bin").is_file());
    assert!(!fixture
        .root
        .join("models/.ember-retention-quarantine")
        .exists());
}

#[test]
fn recovery_refuses_tampered_precommit_receipt() {
    let fixture = Fixture::new("precommit-tamper");
    let plan = fixture_plan(&fixture);
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            Some(ExecutionFault::AfterQuarantines(1)),
        ),
        Err(ExecutionError::InjectedInterruption)
    ));
    let precommit = fixture.custody().join("precommit.json");
    let raw = fs::read_to_string(&precommit).unwrap();
    fs::write(
        &precommit,
        raw.replace("ember-storage-retention-precommit-v1", "tampered"),
    )
    .unwrap();
    assert!(matches!(
        recover_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            RecoveryAction::Rollback,
        ),
        Err(ExecutionError::ObservationDrift(_))
    ));
}

#[test]
fn recovery_refuses_tampered_journal_before_mutation() {
    let fixture = Fixture::new("journal-tamper");
    let plan = fixture_plan(&fixture);
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            Some(ExecutionFault::AfterQuarantines(1)),
        ),
        Err(ExecutionError::InjectedInterruption)
    ));
    fs::write(fixture.custody().join("journal.jsonl"), "{}\n").unwrap();
    assert!(matches!(
        recover_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            RecoveryAction::Rollback,
        ),
        Err(ExecutionError::Serialization(_))
    ));
    assert!(!fixture.root.join("models/eligible.bin").exists());
}

#[test]
fn crash_after_purge_before_terminal_recovers_from_journal_without_double_purge() {
    let fixture = Fixture::new("purge-recovery");
    let plan = fixture_plan(&fixture);
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            Some(ExecutionFault::AfterPurges(1)),
        ),
        Err(ExecutionError::InjectedInterruption)
    ));
    assert!(!fixture.root.join("models/eligible.bin").exists());
    assert!(!fixture.custody().join("terminal.json").exists());
    let recovered = recover_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        RecoveryAction::Resume,
    )
    .unwrap();
    assert_eq!(recovered.result, "RECOVERED_COMMITTED_PASS");
    assert!(fixture.custody().join("recovery.json").is_file());
}

#[test]
fn resume_after_partial_quarantine_finishes_every_unstarted_plan_row() {
    let fixture = Fixture::new("multi-row-quarantine-recovery");
    let models = fixture.root.join("models");
    let state = fixture.root.join("state");
    fs::write(models.join("protected.bin"), vec![1_u8; 700]).unwrap();
    fs::write(models.join("eligible-a.bin"), vec![2_u8; 150]).unwrap();
    fs::write(models.join("eligible-b.bin"), vec![3_u8; 150]).unwrap();
    fs::write(state.join("protected.bin"), vec![4_u8; 600]).unwrap();
    let census = census_after_fixture_grace(vec![
        observed_row(
            &models,
            CustodyClass::Models,
            "protected.bin",
            Disposition::Protected,
        ),
        observed_row(
            &models,
            CustodyClass::Models,
            "eligible-a.bin",
            Disposition::Reproducible,
        ),
        observed_row(
            &models,
            CustodyClass::Models,
            "eligible-b.bin",
            Disposition::Reproducible,
        ),
        observed_row(
            &state,
            CustodyClass::State,
            "protected.bin",
            Disposition::Protected,
        ),
    ]);
    let plan = build_plan(
        &parse_policy(&raw(&policy_value())).unwrap(),
        &census,
        &"a".repeat(64),
        &"b".repeat(40),
    )
    .unwrap();
    assert_eq!(plan.rows.len(), 2);
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            Some(ExecutionFault::AfterQuarantines(1)),
        ),
        Err(ExecutionError::InjectedInterruption)
    ));
    let recovered = recover_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        RecoveryAction::Resume,
    )
    .unwrap();
    assert_eq!(recovered.result, "RECOVERED_COMMITTED_PASS");
    assert!(!models.join("eligible-a.bin").exists());
    assert!(!models.join("eligible-b.bin").exists());
    assert_eq!(recovered.classes[&CustodyClass::Models].after_bytes, 700);
}

#[test]
fn commit_purges_exact_plan_members_and_second_publication_refuses_overwrite() {
    let fixture = Fixture::new("commit");
    let plan = fixture_plan(&fixture);
    let receipt = execute_plan(
        &plan,
        &fixture.roots(),
        &fixture.custody(),
        ExecutionMode::Commit,
        None,
    )
    .unwrap();
    assert_eq!(receipt.result, "COMMITTED_PASS");
    assert_eq!(receipt.classes[&CustodyClass::Models].before_bytes, 1000);
    assert_eq!(receipt.classes[&CustodyClass::Models].after_bytes, 700);
    assert_eq!(receipt.classes[&CustodyClass::State].after_bytes, 600);
    assert_eq!(receipt.policy_raw_sha256, plan.policy_raw_sha256);
    assert_eq!(receipt.census_self_sha256, plan.census_self_sha256);
    assert_eq!(receipt.pin_set_raw_sha256, plan.pin_set_raw_sha256);
    assert_eq!(receipt.current_master, plan.current_master);
    assert!(receipt.cleanup_verified);
    assert_eq!(receipt.rows.len(), plan.rows.len() + plan.kept_rows.len());
    assert!(receipt.rows.iter().any(|row| {
        row.class == CustodyClass::Models
            && row.relative_path == "eligible.bin"
            && row.terminal_disposition == "purged"
            && row.raw_sha256 == plan.rows[0].raw_sha256
            && row.physical_identity == plan.rows[0].physical_identity
    }));
    assert!(receipt.rows.iter().any(|row| {
        row.class == CustodyClass::Models
            && row.relative_path == "protected.bin"
            && row.terminal_disposition == "kept"
    }));
    assert!(!fixture.root.join("models/eligible.bin").exists());
    assert!(fixture.root.join("models/protected.bin").is_file());
    assert!(matches!(
        execute_plan(
            &plan,
            &fixture.roots(),
            &fixture.custody(),
            ExecutionMode::Commit,
            None,
        ),
        Err(ExecutionError::ObservationDrift(_)) | Err(ExecutionError::NoOverwrite(_))
    ));
}
