use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn sandbox() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("ember-lab-rehearsal-cli-{nonce}"));
    fs::create_dir_all(&path).unwrap();
    path
}

fn manifest(path: &std::path::Path) {
    fs::write(
        path,
        serde_json::to_vec(&json!({
            "schema_version": "ember-lab-rehearsal-v1",
            "dispatch_id": "cli-fixture",
            "bounds": {
                "minimum_memory_bytes": 1,
                "minimum_storage_free_bytes": 1,
                "maximum_duration_ms": 100
            },
            "measurements": {
                "source": "fake_runner",
                "observed_at_ms": 1,
                "available_memory_bytes": 2,
                "storage_free_bytes": 2,
                "measured_duration_ms": 1,
                "evidence_sha256": "a".repeat(64)
            }
        }))
        .unwrap(),
    )
    .unwrap();
}

#[test]
fn operator_alone_episode_entrypoint_writes_a_bound_refusal_or_success_receipt() {
    let root = sandbox();
    let manifest_path = root.join("manifest.json");
    let receipt_path = root.join("receipt.json");
    manifest(&manifest_path);
    let binary = env!("CARGO_BIN_EXE_ember-lab");
    let output = Command::new(binary)
        .args([
            "episode",
            "--capability",
            "fixture",
            "--manifest",
            manifest_path.to_str().unwrap(),
            "--receipt",
            receipt_path.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let receipt: Value = serde_json::from_slice(&fs::read(receipt_path).unwrap()).unwrap();
    assert_eq!(receipt["schema_version"], "ember-lab-rehearsal-receipt-v1");
    assert_eq!(receipt["status"], "completed");
    assert_eq!(receipt["capability_claim"], "NO_CAPABILITY_CLAIM");
    assert_eq!(receipt["manifest_sha256"].as_str().unwrap().len(), 64);
}
