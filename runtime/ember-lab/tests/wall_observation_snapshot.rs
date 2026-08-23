// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 J

use ember_lab::Daemon;
use serde_json::Value;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn sandbox() -> PathBuf {
    let root = std::env::var("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target"))
        .join("wall-observation-snapshot-tests")
        .join(format!(
            "{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_millis()
        ));
    std::fs::create_dir_all(&root).unwrap();
    root
}

#[test]
fn wall_snapshot_is_read_only_closed_and_identity_bound() {
    let root = sandbox();
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let snapshot = daemon.wall_observation_snapshot(0, 0).unwrap();
    let value: Value = serde_json::to_value(snapshot).unwrap();
    assert_eq!(
        value["schema_version"],
        "ember-lab-wall-observation-snapshot-v1"
    );
    assert_eq!(value["after_vram_seq"], 0);
    assert_eq!(value["after_disk_seq"], 0);
    assert_eq!(value["vram_observations"], serde_json::json!([]));
    assert_eq!(value["disk_observations"], serde_json::json!([]));
    assert_eq!(value["next_vram_seq"], 0);
    assert_eq!(value["next_disk_seq"], 0);
    assert!(value["daemon_identity"]["binary_sha256"].as_str().is_some());
    assert!(value["daemon_identity"]["source_sha256"].as_str().is_some());
    assert_eq!(value.as_object().unwrap().len(), 9);
    assert!(daemon.wall_observation_snapshot(-1, 0).is_err());
    assert!(daemon.wall_observation_snapshot(0, -1).is_err());
}
