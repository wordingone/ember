// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::{
    rollback_empty_artifact_custody_migration, rollback_empty_data_catalog_migration, Daemon,
    EmberLabError,
};
use serde_json::json;
use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn temp_root(name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!("ember-lab-{name}-{unique}"));
    fs::create_dir_all(&root).unwrap();
    root
}

#[test]
fn fresh_database_schema_seven_contains_foreign_pressure_tables() {
    let root = temp_root("foreign-pressure-schema");
    let db = root.join("ember-lab.sqlite3");
    drop(Daemon::open(&db).unwrap());

    let conn = rusqlite::Connection::open(&db).unwrap();
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, "7");

    let tables: Vec<String> = conn
        .prepare(
            "SELECT name FROM sqlite_master
             WHERE type='table' AND name LIKE 'foreign_process_pressure_%'
             ORDER BY name",
        )
        .unwrap()
        .query_map([], |row| row.get(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        tables,
        vec![
            "foreign_process_pressure_observations".to_string(),
            "foreign_process_pressure_state".to_string(),
        ]
    );

    let observation_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM foreign_process_pressure_observations",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(observation_count, 0);

    let seed: (String, i64, String) = conn
        .query_row(
            "SELECT state,observed_at_ms,observation_json
             FROM foreign_process_pressure_state WHERE singleton=1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(seed.0, "probe_failed");
    assert_eq!(seed.1, 0);
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&seed.2).unwrap(),
        json!({
            "schema_version": "ember-lab-foreign-process-pressure-observation-v1",
            "result": "NOT_YET_SAMPLED",
        })
    );

    drop(conn);
    fs::remove_dir_all(root).unwrap();
}

fn minimal_manifest_bytes() -> Vec<u8> {
    let source_id = "source:courtlistener:2026-08-08";
    let object_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    let receipt_sha = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
    serde_json::to_vec(&json!({
        "schema_version": "ember-data-catalog-manifest-v1",
        "records": [
            {
                "kind": "source",
                "id": source_id,
                "canonical_url": "https://www.courtlistener.com/api/rest/v4/bulk-data/opinions/",
                "revision": "2026-08-08",
                "license_text_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "license_verdict": "accepted",
                "access_class": "public",
                "acquired_at_ms": 1,
                "refusal_reason": null
            },
            {
                "kind": "immutable_object",
                "id": format!("sha256:{object_sha}"),
                "sha256": object_sha,
                "byte_count": 123,
                "media_type": "application/jsonl",
                "locator": format!("sha256/bb/{object_sha}"),
                "custody_state": "available"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{receipt_sha}"),
                "sha256": receipt_sha,
                "producing_authority": "corpus_connector",
                "receipt_class": "acquisition",
                "observed_at_ms": 2,
                "state": "accepted"
            }
        ],
        "edges": [
            {
                "kind": "source_object",
                "from_kind": "source",
                "from_id": source_id,
                "to_kind": "immutable_object",
                "to_id": format!("sha256:{object_sha}"),
                "ordinal": 0,
                "payload": {}
            },
            {
                "kind": "object_receipt",
                "from_kind": "immutable_object",
                "from_id": format!("sha256:{object_sha}"),
                "to_kind": "receipt",
                "to_id": format!("sha256:{receipt_sha}"),
                "ordinal": 0,
                "payload": {}
            }
        ]
    }))
    .unwrap()
}

fn complete_manifest_bytes() -> Vec<u8> {
    let sha = |byte: char| byte.to_string().repeat(64);
    let source_id = "source:courtlistener:2026-08-08";
    let raw_sha = sha('b');
    let output_sha = sha('c');
    let eval_sha = sha('d');
    let acquisition_receipt_sha = sha('e');
    let transform_receipt_sha = sha('f');
    let evaluation_receipt_sha = sha('1');
    let consumer_receipt_sha = sha('2');
    let experience_receipt_sha = sha('3');
    let superseded_receipt_sha = sha('4');
    serde_json::to_vec(&json!({
        "schema_version": "ember-data-catalog-manifest-v1",
        "records": [
            {
                "kind": "source",
                "id": source_id,
                "canonical_url": "https://www.courtlistener.com/api/rest/v4/bulk-data/opinions/",
                "revision": "2026-08-08",
                "license_text_sha256": sha('a'),
                "license_verdict": "accepted",
                "access_class": "public",
                "acquired_at_ms": 1,
                "refusal_reason": null
            },
            {
                "kind": "immutable_object",
                "id": format!("sha256:{raw_sha}"),
                "sha256": raw_sha,
                "byte_count": 123,
                "media_type": "application/jsonl",
                "locator": format!("sha256/bb/{raw_sha}"),
                "custody_state": "available"
            },
            {
                "kind": "immutable_object",
                "id": format!("sha256:{output_sha}"),
                "sha256": output_sha,
                "byte_count": 100,
                "media_type": "application/jsonl",
                "locator": format!("sha256/cc/{output_sha}"),
                "custody_state": "available"
            },
            {
                "kind": "immutable_object",
                "id": format!("sha256:{eval_sha}"),
                "sha256": eval_sha,
                "byte_count": 50,
                "media_type": "application/jsonl",
                "locator": format!("sha256/dd/{eval_sha}"),
                "custody_state": "available"
            },
            {
                "kind": "dataset_version",
                "id": "dataset:parent",
                "name": "owned-legal-parent",
                "manifest_sha256": sha('5'),
                "created_at_ms": 2,
                "version_class": "genesis",
                "state": "admitted"
            },
            {
                "kind": "dataset_version",
                "id": "dataset:child",
                "name": "owned-legal-child",
                "manifest_sha256": sha('6'),
                "created_at_ms": 3,
                "version_class": "derived",
                "state": "admitted"
            },
            {
                "kind": "transform",
                "id": "transform:normalize-legal-v1",
                "producer_identity": "corpus_connector:courtlistener",
                "code_sha256": sha('7'),
                "config_sha256": sha('8'),
                "parameters_sha256": sha('9'),
                "determinism_state": "deterministic"
            },
            {
                "kind": "membership",
                "id": "membership:legal-train-0",
                "domain": "legal",
                "register": "L4",
                "split": "train",
                "tokenizer_sha256": sha('a'),
                "shard_id": "shard:legal:0",
                "window_start": 0,
                "window_end": 100,
                "exact_sha256": output_sha,
                "near_dedup_cluster": "cluster:legal:0",
                "admission_state": "admitted"
            },
            {
                "kind": "protected_eval",
                "id": "evaluation:legal-heldout-v1",
                "frozen_manifest_sha256": sha('b'),
                "test_set_sha256": eval_sha,
                "ngram_ruling": "clear",
                "near_dup_ruling": "clear",
                "exclusion_reason": null,
                "overlap_state": "disjoint",
                "frozen_at_ms": 4
            },
            {
                "kind": "consumer_attempt",
                "id": "attempt:r1-owned-0001",
                "run_attempt_id": "attempt:r1-owned-0001",
                "model_sha256": sha('c'),
                "checkpoint_sha256": sha('d'),
                "tokenizer_sha256": sha('a'),
                "config_sha256": sha('e'),
                "source_tree_sha": "1234567890abcdef1234567890abcdef12345678",
                "evaluator_sha256": sha('f'),
                "state": "completed"
            },
            {
                "kind": "experience",
                "id": "experience:legal-tool-0001",
                "task_identity": "task:legal-retrieval",
                "observation_sha256": sha('1'),
                "action_sha256": sha('2'),
                "tool_call_sha256": sha('3'),
                "verifier_sha256": sha('4'),
                "outcome_sha256": sha('5'),
                "uncertainty_basis_points": 125,
                "observed_at_ms": 5,
                "sequence": 0,
                "model_sha256": sha('c'),
                "privacy_class": "public",
                "retention_class": "retained",
                "deletion_state": "active"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{acquisition_receipt_sha}"),
                "sha256": acquisition_receipt_sha,
                "producing_authority": "corpus_connector",
                "receipt_class": "acquisition",
                "observed_at_ms": 6,
                "state": "accepted"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{transform_receipt_sha}"),
                "sha256": transform_receipt_sha,
                "producing_authority": "ember_lab",
                "receipt_class": "transform",
                "observed_at_ms": 7,
                "state": "accepted"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{evaluation_receipt_sha}"),
                "sha256": evaluation_receipt_sha,
                "producing_authority": "evaluation",
                "receipt_class": "evaluation",
                "observed_at_ms": 8,
                "state": "accepted"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{consumer_receipt_sha}"),
                "sha256": consumer_receipt_sha,
                "producing_authority": "training",
                "receipt_class": "consumer",
                "observed_at_ms": 9,
                "state": "accepted"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{experience_receipt_sha}"),
                "sha256": experience_receipt_sha,
                "producing_authority": "ember_lab",
                "receipt_class": "experience",
                "observed_at_ms": 10,
                "state": "accepted"
            },
            {
                "kind": "receipt",
                "id": format!("sha256:{superseded_receipt_sha}"),
                "sha256": superseded_receipt_sha,
                "producing_authority": "ember_lab",
                "receipt_class": "consumer",
                "observed_at_ms": 0,
                "state": "superseded"
            }
        ],
        "edges": [
            {"kind":"source_object","from_kind":"source","from_id":source_id,"to_kind":"immutable_object","to_id":format!("sha256:{raw_sha}"),"ordinal":0,"payload":{}},
            {"kind":"object_receipt","from_kind":"immutable_object","from_id":format!("sha256:{raw_sha}"),"to_kind":"receipt","to_id":format!("sha256:{acquisition_receipt_sha}"),"ordinal":0,"payload":{}},
            {"kind":"dataset_parent","from_kind":"dataset_version","from_id":"dataset:child","to_kind":"dataset_version","to_id":"dataset:parent","ordinal":0,"payload":{}},
            {"kind":"transform_parent","from_kind":"transform","from_id":"transform:normalize-legal-v1","to_kind":"dataset_version","to_id":"dataset:parent","ordinal":0,"payload":{}},
            {"kind":"transform_input","from_kind":"transform","from_id":"transform:normalize-legal-v1","to_kind":"immutable_object","to_id":format!("sha256:{raw_sha}"),"ordinal":0,"payload":{}},
            {"kind":"transform_output","from_kind":"transform","from_id":"transform:normalize-legal-v1","to_kind":"immutable_object","to_id":format!("sha256:{output_sha}"),"ordinal":0,"payload":{}},
            {"kind":"transform_receipt","from_kind":"transform","from_id":"transform:normalize-legal-v1","to_kind":"receipt","to_id":format!("sha256:{transform_receipt_sha}"),"ordinal":0,"payload":{}},
            {"kind":"dataset_transform","from_kind":"dataset_version","from_id":"dataset:child","to_kind":"transform","to_id":"transform:normalize-legal-v1","ordinal":0,"payload":{}},
            {"kind":"version_membership","from_kind":"dataset_version","from_id":"dataset:child","to_kind":"membership","to_id":"membership:legal-train-0","ordinal":0,"payload":{}},
            {"kind":"membership_object","from_kind":"membership","from_id":"membership:legal-train-0","to_kind":"immutable_object","to_id":format!("sha256:{output_sha}"),"ordinal":0,"payload":{}},
            {"kind":"evaluation_object","from_kind":"protected_eval","from_id":"evaluation:legal-heldout-v1","to_kind":"immutable_object","to_id":format!("sha256:{eval_sha}"),"ordinal":0,"payload":{}},
            {"kind":"evaluation_receipt","from_kind":"protected_eval","from_id":"evaluation:legal-heldout-v1","to_kind":"receipt","to_id":format!("sha256:{evaluation_receipt_sha}"),"ordinal":0,"payload":{}},
            {"kind":"consumer_dataset","from_kind":"consumer_attempt","from_id":"attempt:r1-owned-0001","to_kind":"dataset_version","to_id":"dataset:child","ordinal":0,"payload":{}},
            {"kind":"consumer_evaluation","from_kind":"consumer_attempt","from_id":"attempt:r1-owned-0001","to_kind":"protected_eval","to_id":"evaluation:legal-heldout-v1","ordinal":0,"payload":{}},
            {"kind":"consumer_receipt","from_kind":"consumer_attempt","from_id":"attempt:r1-owned-0001","to_kind":"receipt","to_id":format!("sha256:{consumer_receipt_sha}"),"ordinal":0,"payload":{}},
            {"kind":"experience_consumer","from_kind":"experience","from_id":"experience:legal-tool-0001","to_kind":"consumer_attempt","to_id":"attempt:r1-owned-0001","ordinal":0,"payload":{}},
            {"kind":"experience_receipt","from_kind":"experience","from_id":"experience:legal-tool-0001","to_kind":"receipt","to_id":format!("sha256:{experience_receipt_sha}"),"ordinal":0,"payload":{}},
            {"kind":"receipt_supersession","from_kind":"receipt","from_id":format!("sha256:{consumer_receipt_sha}"),"to_kind":"receipt","to_id":format!("sha256:{superseded_receipt_sha}"),"ordinal":0,"payload":{}}
        ]
    }))
    .unwrap()
}

fn split_complete_manifest() -> (Vec<u8>, Vec<u8>) {
    let complete: serde_json::Value = serde_json::from_slice(&complete_manifest_bytes()).unwrap();
    let records = complete["records"].as_array().unwrap();
    let edges = complete["edges"].as_array().unwrap();
    let source_ids: BTreeSet<String> = records
        .iter()
        .filter(|record| record["kind"] == "source")
        .map(|record| record["id"].as_str().unwrap().to_string())
        .collect();
    let object_ids: BTreeSet<String> = edges
        .iter()
        .filter(|edge| {
            edge["kind"] == "source_object"
                && source_ids.contains(edge["from_id"].as_str().unwrap())
        })
        .map(|edge| edge["to_id"].as_str().unwrap().to_string())
        .collect();
    let receipt_ids: BTreeSet<String> = edges
        .iter()
        .filter(|edge| {
            edge["kind"] == "object_receipt"
                && object_ids.contains(edge["from_id"].as_str().unwrap())
        })
        .map(|edge| edge["to_id"].as_str().unwrap().to_string())
        .collect();
    let first_record_ids: BTreeSet<(String, String)> = records
        .iter()
        .filter(|record| {
            record["kind"] == "source"
                || (record["kind"] == "immutable_object"
                    && object_ids.contains(record["id"].as_str().unwrap()))
                || (record["kind"] == "receipt"
                    && receipt_ids.contains(record["id"].as_str().unwrap()))
        })
        .map(|record| {
            (
                record["kind"].as_str().unwrap().to_string(),
                record["id"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    let first_records: Vec<_> = records
        .iter()
        .filter(|record| {
            first_record_ids.contains(&(
                record["kind"].as_str().unwrap().to_string(),
                record["id"].as_str().unwrap().to_string(),
            ))
        })
        .cloned()
        .collect();
    let first_edges: Vec<_> = edges
        .iter()
        .filter(|edge| {
            matches!(
                edge["kind"].as_str(),
                Some("source_object" | "object_receipt")
            )
        })
        .cloned()
        .collect();
    let second_records: Vec<_> = records
        .iter()
        .filter(|record| {
            !first_record_ids.contains(&(
                record["kind"].as_str().unwrap().to_string(),
                record["id"].as_str().unwrap().to_string(),
            ))
        })
        .cloned()
        .collect();
    let second_edges: Vec<_> = edges
        .iter()
        .filter(|edge| {
            !matches!(
                edge["kind"].as_str(),
                Some("source_object" | "object_receipt")
            )
        })
        .cloned()
        .collect();
    (
        serde_json::to_vec(&json!({
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": first_records,
            "edges": first_edges,
        }))
        .unwrap(),
        serde_json::to_vec(&json!({
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": second_records,
            "edges": second_edges,
        }))
        .unwrap(),
    )
}

#[test]
fn same_manifest_import_is_idempotent_and_reopen_export_is_byte_identical() {
    let root = temp_root("catalog-idempotent");
    let db = root.join("ember-lab.sqlite3");
    let manifest = minimal_manifest_bytes();

    let first = {
        let daemon = Daemon::open(&db).unwrap();
        daemon.import_data_catalog_manifest(&manifest).unwrap()
    };
    assert_eq!(first.inserted_records, 3);
    assert_eq!(first.inserted_edges, 2);

    let reopened = Daemon::open(&db).unwrap();
    let second = reopened.import_data_catalog_manifest(&manifest).unwrap();
    assert_eq!(second.manifest_sha256, first.manifest_sha256);
    assert_eq!(second.inserted_records, 0);
    assert_eq!(second.inserted_edges, 0);
    assert_eq!(
        reopened.export_data_catalog_manifest().unwrap(),
        manifest,
        "canonical export must reproduce the exact imported graph bytes"
    );

    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn complete_data_graph_round_trips_every_required_record_class_and_relation() {
    let root = temp_root("catalog-complete-graph");
    let db = root.join("ember-lab.sqlite3");
    let manifest = complete_manifest_bytes();

    let daemon = Daemon::open(&db).unwrap();
    let first = daemon.import_data_catalog_manifest(&manifest).unwrap();
    assert_eq!(first.inserted_records, 17);
    assert_eq!(first.inserted_edges, 18);
    let canonical = daemon.export_data_catalog_manifest().unwrap();
    drop(daemon);

    let reopened = Daemon::open(&db).unwrap();
    let second = reopened.import_data_catalog_manifest(&manifest).unwrap();
    assert_eq!(second.inserted_records, 0);
    assert_eq!(second.inserted_edges, 0);
    assert_eq!(reopened.export_data_catalog_manifest().unwrap(), canonical);

    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn independently_produced_fragments_compose_into_the_same_catalog_identity() {
    let root = temp_root("incremental");
    let expected = Daemon::open(&root.join("expected.sqlite3")).unwrap();
    expected
        .import_data_catalog_manifest(&complete_manifest_bytes())
        .unwrap();
    let expected_export = expected.export_data_catalog_manifest().unwrap();

    let actual = Daemon::open(&root.join("actual.sqlite3")).unwrap();
    let (source_fragment, lineage_fragment) = split_complete_manifest();
    actual
        .import_data_catalog_manifest(&source_fragment)
        .unwrap();
    actual
        .import_data_catalog_manifest(&lineage_fragment)
        .unwrap();
    assert_eq!(
        actual.export_data_catalog_manifest().unwrap(),
        expected_export
    );
}

#[test]
fn missing_required_graph_relation_refuses_without_partial_catalog_state() {
    for missing_kind in [
        "source_object",
        "object_receipt",
        "dataset_parent",
        "transform_parent",
        "transform_input",
        "transform_output",
        "transform_receipt",
        "dataset_transform",
        "version_membership",
        "membership_object",
        "evaluation_object",
        "evaluation_receipt",
        "consumer_dataset",
        "consumer_evaluation",
        "consumer_receipt",
        "experience_consumer",
        "experience_receipt",
    ] {
        let root = temp_root(&format!("catalog-missing-{missing_kind}"));
        let db = root.join("ember-lab.sqlite3");
        let mut manifest: serde_json::Value =
            serde_json::from_slice(&complete_manifest_bytes()).unwrap();
        manifest["edges"]
            .as_array_mut()
            .unwrap()
            .retain(|edge| edge["kind"] != missing_kind);

        let daemon = Daemon::open(&db).unwrap();
        let error = daemon
            .import_data_catalog_manifest(&serde_json::to_vec(&manifest).unwrap())
            .unwrap_err();
        assert!(
            matches!(error, EmberLabError::InvalidDataCatalog { .. }),
            "missing {missing_kind} was not a catalog refusal: {error:?}"
        );
        assert_eq!(
            daemon.export_data_catalog_manifest().unwrap(),
            serde_json::to_vec(&json!({
                "schema_version": "ember-data-catalog-manifest-v1",
                "records": [],
                "edges": []
            }))
            .unwrap(),
            "missing {missing_kind} committed partial catalog state"
        );

        drop(daemon);
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn unknown_edge_payload_fields_refuse_without_partial_catalog_state() {
    let root = temp_root("catalog-edge-payload-schema");
    let db = root.join("ember-lab.sqlite3");
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&complete_manifest_bytes()).unwrap();
    manifest["edges"][0]["payload"]["foreign_field"] = json!("must-refuse");

    let daemon = Daemon::open(&db).unwrap();
    let error = daemon
        .import_data_catalog_manifest(&serde_json::to_vec(&manifest).unwrap())
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    assert_eq!(
        daemon.export_data_catalog_manifest().unwrap(),
        serde_json::to_vec(&json!({
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": [],
            "edges": []
        }))
        .unwrap()
    );

    drop(daemon);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn receipt_supersession_requires_non_stale_to_superseded_direction() {
    for case in [
        "accepted_to_accepted",
        "superseded_to_superseded",
        "self_cycle",
        "foreign_target",
    ] {
        let root = temp_root(&format!("catalog-supersession-{case}"));
        let db = root.join("ember-lab.sqlite3");
        let mut manifest: serde_json::Value =
            serde_json::from_slice(&complete_manifest_bytes()).unwrap();
        let supersession = manifest["edges"]
            .as_array()
            .unwrap()
            .iter()
            .find(|edge| edge["kind"] == "receipt_supersession")
            .unwrap();
        let source_id = supersession["from_id"].as_str().unwrap().to_string();
        let target_id = supersession["to_id"].as_str().unwrap().to_string();

        match case {
            "accepted_to_accepted" => {
                let target = manifest["records"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|record| record["id"] == target_id)
                    .unwrap();
                target["state"] = json!("accepted");
            }
            "superseded_to_superseded" => {
                let source = manifest["records"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|record| record["id"] == source_id)
                    .unwrap();
                source["state"] = json!("superseded");
                let mut reverse = manifest["edges"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|edge| edge["kind"] == "receipt_supersession")
                    .unwrap()
                    .clone();
                reverse["from_id"] = json!(target_id);
                reverse["to_id"] = json!(source_id);
                manifest["edges"].as_array_mut().unwrap().push(reverse);
            }
            "self_cycle" => {
                let edge = manifest["edges"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|edge| edge["kind"] == "receipt_supersession")
                    .unwrap();
                edge["from_id"] = json!(target_id);
            }
            "foreign_target" => {
                let edge = manifest["edges"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|edge| edge["kind"] == "receipt_supersession")
                    .unwrap();
                edge["to_id"] = json!(format!("sha256:{}", "9".repeat(64)));
            }
            _ => unreachable!(),
        }

        let daemon = Daemon::open(&db).unwrap();
        let error = daemon
            .import_data_catalog_manifest(&serde_json::to_vec(&manifest).unwrap())
            .unwrap_err();
        assert!(
            matches!(error, EmberLabError::InvalidDataCatalog { .. }),
            "malformed supersession case {case} was admitted: {error:?}"
        );
        assert_eq!(
            daemon.export_data_catalog_manifest().unwrap(),
            serde_json::to_vec(&json!({
                "schema_version": "ember-data-catalog-manifest-v1",
                "records": [],
                "edges": []
            }))
            .unwrap(),
            "malformed supersession case {case} committed partial catalog state"
        );

        drop(daemon);
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn object_hash_bindings_and_train_eval_isolation_refuse_drift() {
    for case in [
        "membership_hash_mismatch",
        "evaluation_hash_mismatch",
        "train_eval_overlap",
    ] {
        let root = temp_root(&format!("catalog-{case}"));
        let db = root.join("ember-lab.sqlite3");
        let mut manifest: serde_json::Value =
            serde_json::from_slice(&complete_manifest_bytes()).unwrap();
        match case {
            "membership_hash_mismatch" => {
                let membership = manifest["records"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|record| record["kind"] == "membership")
                    .unwrap();
                membership["exact_sha256"] = json!("0".repeat(64));
            }
            "evaluation_hash_mismatch" => {
                let evaluation = manifest["records"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|record| record["kind"] == "protected_eval")
                    .unwrap();
                evaluation["test_set_sha256"] = json!("0".repeat(64));
            }
            "train_eval_overlap" => {
                let training_object = manifest["records"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|record| record["kind"] == "membership")
                    .unwrap()["exact_sha256"]
                    .as_str()
                    .unwrap()
                    .to_string();
                let evaluation = manifest["records"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|record| record["kind"] == "protected_eval")
                    .unwrap();
                evaluation["test_set_sha256"] = json!(training_object.clone());
                let evaluation_object = manifest["edges"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|edge| edge["kind"] == "evaluation_object")
                    .unwrap();
                evaluation_object["to_id"] = json!(format!("sha256:{training_object}"));
            }
            _ => unreachable!(),
        }

        let daemon = Daemon::open(&db).unwrap();
        let error = daemon
            .import_data_catalog_manifest(&serde_json::to_vec(&manifest).unwrap())
            .unwrap_err();
        assert!(
            matches!(error, EmberLabError::InvalidDataCatalog { .. }),
            "{case} was not a catalog refusal: {error:?}"
        );
        assert_eq!(
            daemon.export_data_catalog_manifest().unwrap(),
            serde_json::to_vec(&json!({
                "schema_version": "ember-data-catalog-manifest-v1",
                "records": [],
                "edges": []
            }))
            .unwrap()
        );

        drop(daemon);
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn status_answers_domain_coverage_blockers_and_exact_consumers_from_sqlite() {
    let root = temp_root("catalog-status");
    let db = root.join("ember-lab.sqlite3");
    let daemon = Daemon::open(&db).unwrap();
    daemon
        .import_data_catalog_manifest(&complete_manifest_bytes())
        .unwrap();

    let status = daemon.data_catalog_status().unwrap();
    assert_eq!(status["schema_version"], "ember-data-catalog-status-v1");
    assert_eq!(status["record_counts"]["source"], 1);
    assert_eq!(status["record_counts"]["immutable_object"], 3);
    assert_eq!(status["record_counts"]["dataset_version"], 2);
    assert_eq!(status["record_counts"]["transform"], 1);
    assert_eq!(status["record_counts"]["membership"], 1);
    assert_eq!(status["record_counts"]["protected_eval"], 1);
    assert_eq!(status["record_counts"]["consumer_attempt"], 1);
    assert_eq!(status["record_counts"]["experience"], 1);
    assert_eq!(status["record_counts"]["receipt"], 6);
    assert_eq!(status["custody"]["total_object_bytes"], 273);
    assert_eq!(status["custody"]["available_object_bytes"], 273);
    assert_eq!(
        status["domains"],
        json!([{
            "domain": "legal",
            "admitted_bytes": 100,
            "admitted_memberships": 1,
            "exact_hashes": 1,
            "near_dedup_clusters": 1,
            "splits": {"train": 1}
        }])
    );
    assert_eq!(status["unresolved_blockers"], json!([]));
    assert_eq!(
        status["evaluations"],
        json!([{
            "evaluation_id": "evaluation:legal-heldout-v1",
            "exclusion_reason": null,
            "near_dup_ruling": "clear",
            "ngram_ruling": "clear",
            "object_ids": [format!("sha256:{}", "d".repeat(64))],
            "overlap_state": "disjoint",
            "receipt_ids": [format!("sha256:{}", "1".repeat(64))]
        }])
    );
    assert_eq!(
        status["consumers"],
        json!([{
            "attempt_id": "attempt:r1-owned-0001",
            "checkpoint_sha256": "d".repeat(64),
            "dataset_version_ids": ["dataset:child"],
            "evaluation_ids": ["evaluation:legal-heldout-v1"],
            "model_sha256": "c".repeat(64),
            "receipt_ids": [format!("sha256:{}", "2".repeat(64))],
            "state": "completed"
        }])
    );

    drop(daemon);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn absolute_object_locator_refuses_without_committing_any_catalog_rows() {
    let root = temp_root("catalog-path-refusal");
    let db = root.join("ember-lab.sqlite3");
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&minimal_manifest_bytes()).unwrap();
    manifest["records"][1]["locator"] = json!("C:/private/corpus.jsonl");

    let daemon = Daemon::open(&db).unwrap();
    let error = daemon
        .import_data_catalog_manifest(&serde_json::to_vec(&manifest).unwrap())
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    assert_eq!(
        daemon.export_data_catalog_manifest().unwrap(),
        serde_json::to_vec(&json!({
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": [],
            "edges": []
        }))
        .unwrap()
    );

    drop(daemon);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn conflicting_immutable_identity_rolls_back_other_new_rows() {
    let root = temp_root("catalog-conflict-rollback");
    let db = root.join("ember-lab.sqlite3");
    let original = minimal_manifest_bytes();
    let daemon = Daemon::open(&db).unwrap();
    daemon.import_data_catalog_manifest(&original).unwrap();

    let mut conflicting: serde_json::Value = serde_json::from_slice(&original).unwrap();
    conflicting["records"][0]["id"] = json!("source:new-fixture");
    conflicting["records"][0]["revision"] = json!("new-revision");
    conflicting["records"][1]["byte_count"] = json!(124);
    conflicting["edges"][0]["from_id"] = json!("source:new-fixture");
    let error = daemon
        .import_data_catalog_manifest(&serde_json::to_vec(&conflicting).unwrap())
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    assert_eq!(daemon.export_data_catalog_manifest().unwrap(), original);

    drop(daemon);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn unknown_database_schema_refuses_before_catalog_migration() {
    let root = temp_root("catalog-unknown-schema");
    let db = root.join("ember-lab.sqlite3");
    let conn = rusqlite::Connection::open(&db).unwrap();
    conn.execute_batch(
        "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
         INSERT INTO metadata(key,value) VALUES('schema_version','999');",
    )
    .unwrap();
    drop(conn);

    let error = match Daemon::open(&db) {
        Ok(_) => panic!("unknown schema unexpectedly opened"),
        Err(error) => error,
    };
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    let conn = rusqlite::Connection::open(&db).unwrap();
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, "999");
    let catalog_tables: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master
             WHERE type='table' AND name LIKE 'data_catalog_%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(catalog_tables, 0);

    drop(conn);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn noncanonical_database_schema_refuses_before_catalog_migration() {
    let root = temp_root("catalog-noncanonical-schema");
    let db = root.join("ember-lab.sqlite3");
    let conn = rusqlite::Connection::open(&db).unwrap();
    conn.execute_batch(
        "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
         INSERT INTO metadata(key,value) VALUES('schema_version','05');",
    )
    .unwrap();
    drop(conn);

    let error = match Daemon::open(&db) {
        Ok(_) => panic!("noncanonical schema unexpectedly opened"),
        Err(error) => error,
    };
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    let conn = rusqlite::Connection::open(&db).unwrap();
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, "05");
    let catalog_tables: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master
             WHERE type='table' AND name LIKE 'data_catalog_%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(catalog_tables, 0);

    drop(conn);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn failed_catalog_migration_rolls_back_all_schema_changes() {
    let root = temp_root("catalog-migration-rollback");
    let db = root.join("ember-lab.sqlite3");
    let conn = rusqlite::Connection::open(&db).unwrap();
    conn.execute_batch(
        "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
         INSERT INTO metadata(key,value) VALUES('schema_version','1');
         CREATE TABLE jobs(job_id TEXT PRIMARY KEY);
         CREATE VIEW data_catalog_records AS SELECT 1 AS incompatible;",
    )
    .unwrap();
    drop(conn);

    assert!(Daemon::open(&db).is_err());
    let conn = rusqlite::Connection::open(&db).unwrap();
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, "1");
    let job_columns: Vec<String> = conn
        .prepare("PRAGMA table_info(jobs)")
        .unwrap()
        .query_map([], |row| row.get(1))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(job_columns, vec!["job_id"]);
    let catalog_tables: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master
             WHERE type='table' AND name LIKE 'data_catalog_%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(catalog_tables, 0);

    drop(conn);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn empty_migration_can_roll_back_but_catalog_data_blocks_downgrade() {
    let root = temp_root("catalog-explicit-rollback");
    let empty_db = root.join("empty.sqlite3");
    drop(Daemon::open(&empty_db).unwrap());
    // A fresh Daemon::open lands at the current schema (6, #1721's artifact-custody tables
    // included), so a downgrade to 4 chains through each historical step in order.
    rollback_empty_artifact_custody_migration(&empty_db).unwrap();
    rollback_empty_data_catalog_migration(&empty_db).unwrap();
    let conn = rusqlite::Connection::open(&empty_db).unwrap();
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, "4");
    let catalog_tables: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master
             WHERE type='table' AND name LIKE 'data_catalog_%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(catalog_tables, 0);
    drop(conn);
    drop(Daemon::open(&empty_db).unwrap());

    let populated_db = root.join("populated.sqlite3");
    let populated = Daemon::open(&populated_db).unwrap();
    populated
        .import_data_catalog_manifest(&minimal_manifest_bytes())
        .unwrap();
    let before = populated.export_data_catalog_manifest().unwrap();
    drop(populated);
    // No artifact custody data exists in this fixture, so the 6 -> 5 step succeeds; the
    // 5 -> 4 step is the one this test actually exercises: the manifest's catalog data blocks
    // that downgrade.
    rollback_empty_artifact_custody_migration(&populated_db).unwrap();
    let error = rollback_empty_data_catalog_migration(&populated_db).unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    let reopened = Daemon::open(&populated_db).unwrap();
    assert_eq!(reopened.export_data_catalog_manifest().unwrap(), before);

    drop(reopened);
    fs::remove_dir_all(root).unwrap();
}
