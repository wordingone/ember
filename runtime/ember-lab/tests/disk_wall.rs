// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 B disk wall

#![cfg(windows)]

use ember_lab::{
    evaluate_disk_write_wall, measure_disk_write_wall_sample, DiskWallBreachClass,
    DiskWallDecision, DiskWriteWallContract, DiskWriteWallSample, EmberLabError,
};
use std::path::{Path, PathBuf};

const MIB: u64 = 1024 * 1024;

fn contract() -> DiskWriteWallContract {
    DiskWriteWallContract {
        volume_root: PathBuf::from(r"B:\"),
        write_root: PathBuf::from(r"B:\ember-custody\run-898"),
        maximum_write_bytes: 100 * MIB,
        minimum_free_bytes: 500 * MIB,
        sample_interval_ms: 2_000,
        maximum_measurement_duration_ms: 250,
    }
}

fn sample(tree_bytes: u64, free_bytes: u64, duration_ms: u64) -> DiskWriteWallSample {
    DiskWriteWallSample {
        observed_at_ms: 10_000,
        baseline_tree_bytes: 1_000 * MIB,
        current_tree_bytes: tree_bytes,
        available_free_bytes: free_bytes,
        measurement_duration_ms: duration_ms,
    }
}

#[test]
fn admission_and_in_run_decisions_bind_named_root_growth_not_volume_delta() {
    let wall = contract();
    assert_eq!(
        evaluate_disk_write_wall(&wall, &sample(1_099 * MIB, 600 * MIB, 10)).unwrap(),
        DiskWallDecision::Healthy {
            growth_bytes: 99 * MIB,
        }
    );
    assert_eq!(
        evaluate_disk_write_wall(&wall, &sample(1_101 * MIB, 600 * MIB, 10)).unwrap(),
        DiskWallDecision::ProtectiveStop {
            breach_class: DiskWallBreachClass::NamedRootWriteBudget,
            growth_bytes: 101 * MIB,
        }
    );

    // A foreign writer can reduce volume free while this job's named root is
    // unchanged. That is a floor breach, never false attribution to child writes.
    assert_eq!(
        evaluate_disk_write_wall(&wall, &sample(1_000 * MIB, 499 * MIB, 10)).unwrap(),
        DiskWallDecision::ProtectiveStop {
            breach_class: DiskWallBreachClass::VolumeFreeFloor,
            growth_bytes: 0,
        }
    );
}

#[test]
fn measurement_cost_is_bounded_and_receiptable() {
    let error = evaluate_disk_write_wall(&contract(), &sample(1_001 * MIB, 600 * MIB, 251))
        .expect_err("an over-cadence full-tree walk must fail closed");
    assert!(matches!(
        error,
        EmberLabError::DiskWallMeasurementDuration {
            elapsed_ms: 251,
            maximum_ms: 250,
        }
    ));

    let mut caller_tuned = contract();
    caller_tuned.maximum_measurement_duration_ms = 251;
    assert!(evaluate_disk_write_wall(&caller_tuned, &sample(1_001 * MIB, 600 * MIB, 10)).is_err());
    let mut caller_tuned = contract();
    caller_tuned.sample_interval_ms = 1;
    assert!(evaluate_disk_write_wall(&caller_tuned, &sample(1_001 * MIB, 600 * MIB, 10)).is_err());
}

#[test]
fn shrinking_or_overlapping_accounting_inputs_refuse() {
    assert!(evaluate_disk_write_wall(&contract(), &sample(999 * MIB, 600 * MIB, 10)).is_err());
    let mut invalid = contract();
    invalid.write_root = invalid.volume_root.clone();
    assert!(evaluate_disk_write_wall(&invalid, &sample(1_000 * MIB, 600 * MIB, 10)).is_err());

    let mut invalid_time = sample(1_000 * MIB, 600 * MIB, 10);
    invalid_time.observed_at_ms = 0;
    assert!(evaluate_disk_write_wall(&contract(), &invalid_time).is_err());
}

struct TestRoot(PathBuf);

impl Drop for TestRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn measurement_contract(write_root: &Path) -> DiskWriteWallContract {
    let display = write_root.to_string_lossy();
    let volume_root = PathBuf::from(format!(r"{}\", &display[..2]));
    DiskWriteWallContract {
        volume_root,
        write_root: write_root.to_path_buf(),
        maximum_write_bytes: 100 * MIB,
        minimum_free_bytes: 1,
        sample_interval_ms: 2_000,
        maximum_measurement_duration_ms: 250,
    }
}

fn measurement_root(name: &str) -> TestRoot {
    let target = std::env::var_os("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    let path = target.join(format!(
        "disk-wall-{name}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&path).unwrap();
    TestRoot(path)
}

#[test]
fn canonical_named_root_measurement_counts_owned_bytes() {
    let root = measurement_root("counts");
    let write_root = root.0.join("custody");
    std::fs::create_dir(&write_root).unwrap();
    std::fs::write(write_root.join("artifact.bin"), b"ember").unwrap();
    let sample = measure_disk_write_wall_sample(&measurement_contract(&write_root), 0, 10_000)
        .expect("canonical owned tree must measure");
    assert_eq!(sample.current_tree_bytes, 5);
    assert!(sample.measurement_duration_ms <= 250);

    let mut non_volume = measurement_contract(&write_root);
    non_volume.volume_root = root.0.clone();
    assert!(measure_disk_write_wall_sample(&non_volume, 0, 10_000).is_err());
}

#[test]
fn hardlink_and_junction_escape_refuse_instead_of_double_counting() {
    let root = measurement_root("escapes");
    let write_root = root.0.join("custody");
    std::fs::create_dir(&write_root).unwrap();
    let external_file = root.0.join("foreign.bin");
    std::fs::write(&external_file, b"foreign").unwrap();
    std::fs::hard_link(&external_file, write_root.join("hardlink.bin")).unwrap();
    assert!(
        measure_disk_write_wall_sample(&measurement_contract(&write_root), 0, 10_000)
            .unwrap_err()
            .to_string()
            .contains("hard-linked")
    );
    std::fs::remove_file(write_root.join("hardlink.bin")).unwrap();

    let external_dir = root.0.join("foreign-dir");
    std::fs::create_dir(&external_dir).unwrap();
    std::os::windows::fs::symlink_dir(&external_dir, write_root.join("junction")).unwrap();
    assert!(
        measure_disk_write_wall_sample(&measurement_contract(&write_root), 0, 10_000)
            .unwrap_err()
            .to_string()
            .contains("reparse-point")
    );
}
