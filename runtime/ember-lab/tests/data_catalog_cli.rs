// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::Daemon;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn sandbox() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "ember-lab-data-catalog-cli-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn data_catalog_status_uses_the_current_ember_lab_cli_authority() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let _live_writer = Daemon::open(&db).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args(["data-catalog-status", "--db", db.to_str().unwrap()])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "status command failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let status: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        status.get("schema_version").and_then(Value::as_str),
        Some("ember-data-catalog-status-v1")
    );
    assert_eq!(
        status
            .pointer("/custody/available_object_bytes")
            .and_then(Value::as_u64),
        Some(0)
    );
    assert!(status
        .get("domains")
        .and_then(Value::as_array)
        .unwrap()
        .is_empty());
    assert!(status
        .get("unresolved_blockers")
        .and_then(Value::as_array)
        .unwrap()
        .is_empty());
    assert!(status
        .get("consumers")
        .and_then(Value::as_array)
        .unwrap()
        .is_empty());
}

fn minimal_manifest_bytes() -> Vec<u8> {
    let object_sha = "b".repeat(64);
    let receipt_sha = "c".repeat(64);
    serde_json::to_vec(&json!({
        "schema_version": "ember-data-catalog-manifest-v1",
        "records": [
            {
                "kind": "source",
                "id": "source:issue1581:test",
                "canonical_url": "https://example.test/issue1581",
                "revision": "v1",
                "license_text_sha256": "a".repeat(64),
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
                "media_type": "application/pdf",
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
            {"kind":"source_object","from_kind":"source","from_id":"source:issue1581:test","to_kind":"immutable_object","to_id":format!("sha256:{object_sha}"),"ordinal":0,"payload":{}},
            {"kind":"object_receipt","from_kind":"immutable_object","from_id":format!("sha256:{object_sha}"),"to_kind":"receipt","to_id":format!("sha256:{receipt_sha}"),"ordinal":0,"payload":{}}
        ]
    }))
    .unwrap()
}

fn heldout_manifest_bytes() -> Vec<u8> {
    let object_sha = "b".repeat(64);
    let receipt_sha = "c".repeat(64);
    let manifest_sha = "d".repeat(64);
    serde_json::to_vec(&json!({
        "schema_version": "ember-data-catalog-manifest-v1",
        "records": [
            {
                "kind": "source",
                "id": "source:candidate-mathematics-heldout-0",
                "canonical_url": "https://example.test/issue1581-heldout",
                "revision": "v1",
                "license_text_sha256": "a".repeat(64),
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
                "media_type": "text/plain; charset=utf-8",
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
            },
            {
                "kind": "dataset_version",
                "id": format!("dataset:issue1581-bulk-heldout:{manifest_sha}"),
                "name": "issue1581-bulk-heldout-front",
                "manifest_sha256": manifest_sha,
                "created_at_ms": 3,
                "version_class": "genesis",
                "state": "admitted"
            },
            {
                "kind": "membership",
                "id": format!("membership:candidate-mathematics-heldout-0:{object_sha}"),
                "domain": "mathematics",
                "register": "L4",
                "split": "heldout",
                "tokenizer_sha256": "e".repeat(64),
                "shard_id": format!("shard:sha256:{object_sha}"),
                "window_start": 0,
                "window_end": 123,
                "exact_sha256": object_sha,
                "near_dedup_cluster": format!("sha256:{object_sha}"),
                "admission_state": "admitted"
            }
        ],
        "edges": [
            {"kind":"source_object","from_kind":"source","from_id":"source:candidate-mathematics-heldout-0","to_kind":"immutable_object","to_id":format!("sha256:{object_sha}"),"ordinal":0,"payload":{}},
            {"kind":"object_receipt","from_kind":"immutable_object","from_id":format!("sha256:{object_sha}"),"to_kind":"receipt","to_id":format!("sha256:{receipt_sha}"),"ordinal":0,"payload":{}},
            {"kind":"version_membership","from_kind":"dataset_version","from_id":format!("dataset:issue1581-bulk-heldout:{manifest_sha}"),"to_kind":"membership","to_id":format!("membership:candidate-mathematics-heldout-0:{object_sha}"),"ordinal":0,"payload":{}},
            {"kind":"membership_object","from_kind":"membership","from_id":format!("membership:candidate-mathematics-heldout-0:{object_sha}"),"to_kind":"immutable_object","to_id":format!("sha256:{object_sha}"),"ordinal":0,"payload":{}}
        ]
    }))
    .unwrap()
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[test]
fn data_catalog_import_is_no_overwrite_and_idempotent_with_a_self_hashed_receipt() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let manifest = root.join("manifest.json");
    let first_receipt = root.join("first-receipt.json");
    let second_receipt = root.join("second-receipt.json");
    let first_export = root.join("first-export.json");
    let second_export = root.join("second-export.json");
    fs::write(&manifest, minimal_manifest_bytes()).unwrap();

    let run = |receipt: &PathBuf, export: &PathBuf| {
        Command::new(env!("CARGO_BIN_EXE_ember-lab"))
            .args([
                "data-catalog-import",
                "--db",
                db.to_str().unwrap(),
                "--manifest",
                manifest.to_str().unwrap(),
                "--receipt",
                receipt.to_str().unwrap(),
                "--export",
                export.to_str().unwrap(),
                "--source-commit",
                "1234567890abcdef1234567890abcdef12345678",
            ])
            .output()
            .unwrap()
    };

    let first = run(&first_receipt, &first_export);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first_payload: Value = serde_json::from_slice(&fs::read(&first_receipt).unwrap()).unwrap();
    assert_eq!(
        first_payload["schema_version"],
        "ember-data-catalog-import-receipt-v1"
    );
    assert_eq!(first_payload["result"], "PASS");
    assert_eq!(first_payload["inserted_records"], 3);
    assert_eq!(first_payload["inserted_edges"], 2);
    assert_eq!(
        first_payload["canonical_export_sha256"],
        sha256(&fs::read(&first_export).unwrap())
    );
    assert_eq!(
        first_payload["source_commit"],
        "1234567890abcdef1234567890abcdef12345678"
    );
    let mut without_self = first_payload.clone();
    let claimed_self = without_self
        .as_object_mut()
        .unwrap()
        .remove("self_sha256")
        .unwrap();
    assert_eq!(
        claimed_self,
        sha256(&serde_json::to_vec(&without_self).unwrap())
    );

    let second = run(&second_receipt, &second_export);
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    let second_payload: Value =
        serde_json::from_slice(&fs::read(&second_receipt).unwrap()).unwrap();
    assert_eq!(second_payload["inserted_records"], 0);
    assert_eq!(second_payload["inserted_edges"], 0);
    assert_eq!(
        second_payload["canonical_export_sha256"],
        first_payload["canonical_export_sha256"]
    );
    assert_eq!(
        second_payload["canonical_manifest_sha256"],
        first_payload["canonical_manifest_sha256"]
    );
    assert_eq!(
        fs::read(&second_export).unwrap(),
        fs::read(&first_export).unwrap()
    );

    let overwrite = run(&second_receipt, &second_export);
    assert!(!overwrite.status.success());
    assert_eq!(
        fs::read(&second_receipt).unwrap(),
        serde_json::to_vec_pretty(&second_payload).unwrap()
    );
}

#[test]
fn data_catalog_import_accepts_split_honest_heldout_membership() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let manifest = root.join("heldout-manifest.json");
    let receipt = root.join("heldout-receipt.json");
    let export = root.join("heldout-export.json");
    fs::write(&manifest, heldout_manifest_bytes()).unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "data-catalog-import",
            "--db",
            db.to_str().unwrap(),
            "--manifest",
            manifest.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
            "--export",
            export.to_str().unwrap(),
            "--source-commit",
            "1234567890abcdef1234567890abcdef12345678",
        ])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let exported: Value = serde_json::from_slice(&fs::read(&export).unwrap()).unwrap();
    let memberships = exported["records"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|row| row["kind"] == "membership")
        .collect::<Vec<_>>();
    assert_eq!(memberships.len(), 1);
    assert_eq!(memberships[0]["split"], "heldout");
}

#[test]
fn preexisting_import_receipt_refuses_before_catalog_mutation() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let manifest = root.join("manifest.json");
    let receipt = root.join("receipt.json");
    let export = root.join("export.json");
    fs::write(&manifest, minimal_manifest_bytes()).unwrap();
    fs::write(&receipt, b"do not overwrite").unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "data-catalog-import",
            "--db",
            db.to_str().unwrap(),
            "--manifest",
            manifest.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
            "--export",
            export.to_str().unwrap(),
            "--source-commit",
            "1234567890abcdef1234567890abcdef12345678",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert_eq!(fs::read(&receipt).unwrap(), b"do not overwrite");
    assert!(!export.exists());

    let daemon = Daemon::open(&db).unwrap();
    assert_eq!(
        daemon.export_data_catalog_manifest().unwrap(),
        br#"{"edges":[],"records":[],"schema_version":"ember-data-catalog-manifest-v1"}"#
    );
}

#[test]
fn preexisting_import_export_refuses_before_catalog_mutation() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let manifest = root.join("manifest.json");
    let receipt = root.join("receipt.json");
    let export = root.join("export.json");
    fs::write(&manifest, minimal_manifest_bytes()).unwrap();
    fs::write(&export, b"do not overwrite").unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "data-catalog-import",
            "--db",
            db.to_str().unwrap(),
            "--manifest",
            manifest.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
            "--export",
            export.to_str().unwrap(),
            "--source-commit",
            "1234567890abcdef1234567890abcdef12345678",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(!receipt.exists());
    assert_eq!(fs::read(&export).unwrap(), b"do not overwrite");

    let daemon = Daemon::open(&db).unwrap();
    assert_eq!(
        daemon.export_data_catalog_manifest().unwrap(),
        br#"{"edges":[],"records":[],"schema_version":"ember-data-catalog-manifest-v1"}"#
    );
}

#[test]
fn invalid_source_commit_refuses_before_receipt_or_catalog_creation() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let manifest = root.join("manifest.json");
    let receipt = root.join("receipt.json");
    let export = root.join("export.json");
    fs::write(&manifest, minimal_manifest_bytes()).unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "data-catalog-import",
            "--db",
            db.to_str().unwrap(),
            "--manifest",
            manifest.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
            "--export",
            export.to_str().unwrap(),
            "--source-commit",
            "NOT-A-COMMIT",
        ])
        .output()
        .unwrap();

    assert!(!output.status.success());
    assert!(!receipt.exists());
    assert!(!export.exists());
    assert!(!db.exists());
    assert!(String::from_utf8_lossy(&output.stderr)
        .contains("--source-commit must be a lowercase 40-hex SHA"));
}

#[test]
fn invalid_manifest_removes_reserved_receipt_without_reporting_pass() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let manifest = root.join("manifest.json");
    let receipt = root.join("receipt.json");
    let export = root.join("export.json");
    fs::write(&manifest, br#"{"schema_version":"wrong"}"#).unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "data-catalog-import",
            "--db",
            db.to_str().unwrap(),
            "--manifest",
            manifest.to_str().unwrap(),
            "--receipt",
            receipt.to_str().unwrap(),
            "--export",
            export.to_str().unwrap(),
            "--source-commit",
            "1234567890abcdef1234567890abcdef12345678",
        ])
        .output()
        .unwrap();

    assert!(!output.status.success());
    assert!(!receipt.exists());
    assert!(!export.exists());
}
