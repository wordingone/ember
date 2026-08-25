// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use ember_lab::data_catalog::ArtifactLocationInput;
use ember_lab::{
    rollback_empty_artifact_custody_migration, rollback_empty_foreign_process_pressure_migration,
    Daemon, EmberLabError,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn temp_root(name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!("ember-lab-artifact-custody-{name}-{unique}"));
    fs::create_dir_all(&root).unwrap();
    root
}

/// Writes a real file to disk and returns its (sha256, byte_count, path). Every test in this
/// file verifies against genuine on-disk bytes and real `fs::metadata`/hashing calls -- no
/// mocked filesystem -- so the custody-verify code path under test is the real one.
fn write_real_shard(dir: &Path, name: &str, content: &[u8]) -> (String, i64, PathBuf) {
    let path = dir.join(name);
    fs::write(&path, content).unwrap();
    (
        format!("{:x}", Sha256::digest(content)),
        content.len() as i64,
        path,
    )
}

fn location(volume: &str, locator: &str) -> ArtifactLocationInput {
    ArtifactLocationInput {
        volume: volume.to_string(),
        locator: locator.to_string(),
    }
}

#[test]
fn register_artifact_is_idempotent_by_hash() {
    let root = temp_root("idempotent");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let (sha256, byte_count, _path) = write_real_shard(&root, "shard-0.bin", b"shard bytes 0");

    let first = daemon
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("local:A", "checkpoints/shard-0.bin")],
        )
        .unwrap();
    assert!(first.object_newly_registered);
    assert_eq!(first.locations.len(), 1);
    assert!(first.locations[0].newly_registered);

    // Duplicate registration of the exact same object+location is idempotent: no error, no
    // second location event, nothing newly registered the second time.
    let second = daemon
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("local:A", "checkpoints/shard-0.bin")],
        )
        .unwrap();
    assert!(!second.object_newly_registered);
    assert!(!second.locations[0].newly_registered);

    let event_count: i64 = {
        let conn = rusqlite::Connection::open(root.join("ember-lab.sqlite3")).unwrap();
        conn.query_row(
            "SELECT COUNT(*) FROM data_catalog_location_events",
            [],
            |row| row.get(0),
        )
        .unwrap()
    };
    assert_eq!(
        event_count, 1,
        "idempotent re-registration must not append a second event"
    );
}

#[test]
fn register_artifact_refuses_conflicting_byte_count_for_the_same_hash() {
    let root = temp_root("conflict");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let (sha256, byte_count, _path) = write_real_shard(&root, "shard.bin", b"immutable content");

    daemon
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("local:A", "a.bin")],
        )
        .unwrap();

    let error = daemon
        .register_artifact(
            &sha256,
            byte_count + 1,
            "application/octet-stream",
            &[location("local:A", "a.bin")],
        )
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
}

#[test]
fn register_artifact_refuses_zero_locations() {
    let root = temp_root("no-locations");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let (sha256, byte_count, _path) = write_real_shard(&root, "shard.bin", b"content");
    let error = daemon
        .register_artifact(&sha256, byte_count, "application/octet-stream", &[])
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
}

#[test]
fn register_artifact_registers_exactly_its_declared_shard_set() {
    let root = temp_root("shard-set");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let shards = [
        write_real_shard(&root, "shard-0.bin", b"shard content zero"),
        write_real_shard(&root, "shard-1.bin", b"shard content one, longer"),
        write_real_shard(&root, "shard-2.bin", b"shard content two, longer still"),
    ];
    for (index, (sha256, byte_count, _path)) in shards.iter().enumerate() {
        daemon
            .register_artifact(
                sha256,
                *byte_count,
                "application/octet-stream",
                &[location(
                    "local:A",
                    &format!("checkpoints/shard-{index}.bin"),
                )],
            )
            .unwrap();
    }
    let status = daemon.data_catalog_status().unwrap();
    assert_eq!(
        status.pointer("/record_counts/immutable_object"),
        Some(&Value::from(shards.len()))
    );
}

#[test]
fn retire_artifact_location_is_an_explicit_event_never_a_silent_delete() {
    let root = temp_root("retire");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let (sha256, byte_count, path) = write_real_shard(&root, "shard.bin", b"retirable content");
    daemon
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("local:A", "shard.bin")],
        )
        .unwrap();

    let mut roots = BTreeMap::new();
    roots.insert("local:A".to_string(), root.clone());
    let receipt = daemon
        .custody_verify(std::slice::from_ref(&sha256), &roots, false)
        .unwrap();
    assert_eq!(receipt["results"][0]["verdict"], "verified");

    daemon
        .retire_artifact_location(&sha256, "local:A", "shard.bin", "superseded by re-copy")
        .unwrap();

    // Retiring is an event, not a deletion: the underlying file is untouched, but the location
    // is no longer active, so custody verify now reports no_registered_location.
    assert!(path.exists());
    let receipt_after = daemon
        .custody_verify(std::slice::from_ref(&sha256), &roots, false)
        .unwrap();
    assert_eq!(
        receipt_after["results"][0]["verdict"],
        "no_registered_location"
    );
    assert_eq!(receipt_after["admitted"], false);

    // Retiring an already-retired location refuses (fail closed on malformed sequencing).
    let error = daemon
        .retire_artifact_location(&sha256, "local:A", "shard.bin", "again")
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));

    // Re-registering after retirement is allowed -- an explicit new event, never blocked by
    // history -- and custody verify reflects it as active again.
    let re_registered = daemon
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("local:A", "shard.bin")],
        )
        .unwrap();
    assert!(re_registered.locations[0].newly_registered);
    let receipt_reactivated = daemon.custody_verify(&[sha256], &roots, false).unwrap();
    assert_eq!(receipt_reactivated["results"][0]["verdict"], "verified");
}

#[test]
fn custody_verify_distinguishes_all_four_verdicts_against_real_files() {
    let root = temp_root("verdicts");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();

    // A: registered, real file present, correct size -> verified.
    let (sha_verified, bytes_verified, _) = write_real_shard(&root, "a.bin", b"verified content");
    daemon
        .register_artifact(
            &sha_verified,
            bytes_verified,
            "application/octet-stream",
            &[location("local:A", "a.bin")],
        )
        .unwrap();

    // B: registered, real file present, but the ON-DISK bytes are shorter than declared ->
    // size_mismatch. byte_count is declared as if the file were 5 bytes larger than it is.
    let (sha_mismatch, bytes_mismatch, _) = write_real_shard(&root, "b.bin", b"short");
    daemon
        .register_artifact(
            &sha_mismatch,
            bytes_mismatch + 5,
            "application/octet-stream",
            &[location("local:A", "b.bin")],
        )
        .unwrap();

    // C: registered, but no file exists at the registered locator -> absent_at_registered_location.
    let sha_absent = format!("{:x}", Sha256::digest(b"never written to disk"));
    daemon
        .register_artifact(
            &sha_absent,
            123,
            "application/octet-stream",
            &[location("local:A", "does-not-exist.bin")],
        )
        .unwrap();

    // D: never registered at all -> no_registered_location.
    let sha_unregistered = format!("{:x}", Sha256::digest(b"nothing ever registered this"));

    let mut roots = BTreeMap::new();
    roots.insert("local:A".to_string(), root.clone());
    let receipt = daemon
        .custody_verify(
            &[
                sha_verified.clone(),
                sha_mismatch.clone(),
                sha_absent.clone(),
                sha_unregistered.clone(),
            ],
            &roots,
            false,
        )
        .unwrap();

    let verdict_for = |hash: &str| -> String {
        receipt["results"]
            .as_array()
            .unwrap()
            .iter()
            .find(|entry| entry["sha256"] == hash)
            .unwrap()["verdict"]
            .as_str()
            .unwrap()
            .to_string()
    };
    assert_eq!(verdict_for(&sha_verified), "verified");
    assert_eq!(verdict_for(&sha_mismatch), "size_mismatch");
    assert_eq!(verdict_for(&sha_absent), "absent_at_registered_location");
    assert_eq!(verdict_for(&sha_unregistered), "no_registered_location");
    assert_eq!(receipt["admitted"], false);
}

#[test]
fn custody_verify_fails_closed_when_a_registered_volume_has_no_supplied_root() {
    let root = temp_root("missing-root");
    let daemon = Daemon::open(&root.join("ember-lab.sqlite3")).unwrap();
    let (sha256, byte_count, _path) = write_real_shard(&root, "shard.bin", b"content");
    daemon
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("hf:ember-checkpoints", "shard.bin")],
        )
        .unwrap();

    let empty_roots = BTreeMap::new();
    let error = daemon
        .custody_verify(&[sha256], &empty_roots, false)
        .unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
}

#[test]
fn empty_artifact_custody_migration_can_roll_back_but_registered_data_blocks_downgrade() {
    let root = temp_root("custody-rollback");
    let empty_db = root.join("empty.sqlite3");
    drop(Daemon::open(&empty_db).unwrap());
    rollback_empty_foreign_process_pressure_migration(&empty_db).unwrap();
    rollback_empty_artifact_custody_migration(&empty_db).unwrap();
    let conn = rusqlite::Connection::open(&empty_db).unwrap();
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key='schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, "5");
    drop(conn);

    let populated_db = root.join("populated.sqlite3");
    let populated = Daemon::open(&populated_db).unwrap();
    let (sha256, byte_count, _path) = write_real_shard(&root, "shard.bin", b"populated");
    populated
        .register_artifact(
            &sha256,
            byte_count,
            "application/octet-stream",
            &[location("local:A", "shard.bin")],
        )
        .unwrap();
    drop(populated);
    rollback_empty_foreign_process_pressure_migration(&populated_db).unwrap();
    let error = rollback_empty_artifact_custody_migration(&populated_db).unwrap_err();
    assert!(matches!(error, EmberLabError::InvalidDataCatalog { .. }));
    // The registration survives the refused rollback attempt untouched.
    let reopened = Daemon::open(&populated_db).unwrap();
    let mut roots = BTreeMap::new();
    roots.insert("local:A".to_string(), root.clone());
    let receipt = reopened.custody_verify(&[sha256], &roots, false).unwrap();
    assert_eq!(receipt["results"][0]["verdict"], "verified");
}

fn sandbox() -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "ember-lab-artifact-custody-cli-{}-{unique}",
        std::process::id()
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

/// The gate-wiring pattern (#1721 item 4), executed end-to-end through the real compiled CLI --
/// exactly the shape a real preflight (rung entry, evaluation binding, adjudication, certified
/// launch) shells out to: `ember-lab custody-verify`. This is the acceptance criterion's literal
/// text: "a rung-entry preflight against an unregistered hash refuses with the receipt, and the
/// same preflight passes after backfill registration -- both executed on this host and
/// receipted in the PR." No mocking: a real subprocess, a real file on disk, a real receipt
/// file read back after each run.
///
/// Both verify passes run while a live `Daemon` holds the state-writer lock -- the real shape, in
/// which the ember-lab daemon is up and a preflight shells out beside it. Only the backfill
/// registration (a write) takes the lock, so the daemon is dropped across it and reopened after.
#[test]
fn preflight_refuses_unregistered_hash_and_passes_after_backfill_registration_via_real_cli() {
    let root = sandbox();
    let db = root.join("ember-lab.sqlite3");
    let live_writer = Daemon::open(&db).unwrap();

    let subject_path = root.join("subject-shard.bin");
    let content = b"the 2026-08-13 style recovered subject shard bytes";
    fs::write(&subject_path, content).unwrap();
    let sha256 = format!("{:x}", Sha256::digest(content));
    let receipt_path = root.join("preflight-receipt.json");

    // Pass 1: the hash was never registered. The preflight must refuse, and it must be able to
    // quote a receipt naming the fact -- not merely "searched and did not find."
    let refusal = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "custody-verify",
            "--db",
            db.to_str().unwrap(),
            "--hash",
            &sha256,
            "--root",
            &format!("local:A={}", root.to_str().unwrap()),
            "--receipt",
            receipt_path.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        !refusal.status.success(),
        "preflight must fail closed on an unregistered hash"
    );
    // A refusal without a receipt is not a refusal this gate can quote. The likely cause is
    // custody-verify having been rerouted through a writer-lock-taking path (Daemon::open), which
    // errors out before writing anything while the ember-lab daemon holds the lock.
    assert!(
        receipt_path.exists(),
        "custody-verify refused without writing a receipt; stderr: {}",
        String::from_utf8_lossy(&refusal.stderr)
    );
    let refusal_receipt: Value = serde_json::from_slice(&fs::read(&receipt_path).unwrap()).unwrap();
    assert_eq!(refusal_receipt["admitted"], false);
    assert_eq!(
        refusal_receipt["results"][0]["verdict"],
        "no_registered_location"
    );

    // Backfill: register the real bytes at their real location, through the real CLI. Writes take
    // the state-writer lock, so the live daemon stands down across this step only.
    drop(live_writer);
    let registration = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "register-artifact",
            "--db",
            db.to_str().unwrap(),
            "--sha256",
            &sha256,
            "--byte-count",
            &content.len().to_string(),
            "--media-type",
            "application/octet-stream",
            "--location",
            &format!(
                "local:A={}",
                subject_path.file_name().unwrap().to_str().unwrap()
            ),
        ])
        .output()
        .unwrap();
    assert!(
        registration.status.success(),
        "backfill registration failed: {}",
        String::from_utf8_lossy(&registration.stderr)
    );

    // Pass 2: the exact same preflight now resolves and passes -- again with the daemon live.
    let _relive_writer = Daemon::open(&db).unwrap();
    let admission = Command::new(env!("CARGO_BIN_EXE_ember-lab"))
        .args([
            "custody-verify",
            "--db",
            db.to_str().unwrap(),
            "--hash",
            &sha256,
            "--root",
            &format!("local:A={}", root.to_str().unwrap()),
            "--receipt",
            receipt_path.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        admission.status.success(),
        "preflight must pass after backfill registration: {}",
        String::from_utf8_lossy(&admission.stderr)
    );
    let admission_receipt: Value =
        serde_json::from_slice(&fs::read(&receipt_path).unwrap()).unwrap();
    assert_eq!(admission_receipt["admitted"], true);
    assert_eq!(admission_receipt["results"][0]["verdict"], "verified");
}
