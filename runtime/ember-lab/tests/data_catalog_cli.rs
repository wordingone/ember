// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::Daemon;
use serde_json::Value;
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
