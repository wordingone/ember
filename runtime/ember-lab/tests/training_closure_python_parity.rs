// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! Second half of the #1400 byte-parity pin (team-lead ruling 2026-08-04): shells out to
//! the REAL `src/ember/governance/scripts/training_closure.py --print-hash` against the same golden fixture tree
//! `src/training_verify.rs`'s `closure_hash_matches_committed_golden_fixture` unit test
//! checks, and asserts the two hashes agree. The committed golden fixture
//! (`tests/fixtures/training-closure-golden.json`) is the fast, always-on, python-free half
//! (covered by `cargo test --lib`, the exact step `ci-pr.yml` already runs for ember-lab);
//! THIS test is the drift-cannot-hide-behind-a-stale-fixture half -- it catches the case
//! where the golden value itself fell out of sync with a real edit to
//! `src/ember/governance/scripts/training_closure.py` that nobody regenerated the fixture for.
//!
//! Not run in `ci-pr.yml`'s default `cargo test --locked --lib` step (same tier as this
//! crate's existing fixed-pagefile-only tests in `tests/`) since GitHub-hosted Windows
//! runner python availability for this repo layout is unconfirmed; run locally as part of
//! this PR's receipted test evidence, and left available to any CI lane that opts into
//! `--all-targets` / `--tests` with python on PATH.
//!
//! Requires `python` on `PATH` and a checkout where `../../../src/ember/governance/scripts/training_closure.py`
//! resolves relative to this crate (`runtime/ember-lab/`) -- true both in the real repo and
//! in this build's sandbox copy, where `src/ember/governance/scripts/training_closure.py` was copied to the
//! sandbox root as `<sandbox>/src/ember/governance/scripts/training_closure.py`, three levels above
//! `runtime/ember-lab/`.

use std::path::Path;
use std::process::Command;

#[test]
fn closure_hash_matches_python_training_closure_script() {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let golden_path = manifest_dir.join("tests/fixtures/training-closure-golden.json");
    let golden: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&golden_path).unwrap()).unwrap();
    let fixture_root = manifest_dir.join(
        golden
            .get("fixture_root")
            .and_then(serde_json::Value::as_str)
            .expect("golden fixture must declare fixture_root"),
    );
    let expected_hash = golden
        .get("expected_closure_sha256")
        .and_then(serde_json::Value::as_str)
        .expect("golden fixture must declare expected_closure_sha256")
        .to_string();

    // runtime/ember-lab/../../src/ember/governance/scripts/training_closure.py -- the repo-root-relative script,
    // reached the same way whether this crate sits at the real repo's
    // runtime/ember-lab/ or this build's sandbox copy at <sandbox>/runtime/ember-lab/.
    let script_path = manifest_dir.join("../../src/ember/governance/scripts/training_closure.py");
    assert!(
        script_path.is_file(),
        "src/ember/governance/scripts/training_closure.py not found at {}; this test requires the real \
         closure-hash implementation on disk two levels above runtime/ember-lab/",
        script_path.display()
    );

    let output = Command::new("python")
        .arg("-B")
        .arg(&script_path)
        .arg("--root")
        .arg(&fixture_root)
        .arg("--print-hash")
        .output()
        .expect("python must be on PATH to run this parity test");
    assert!(
        output.status.success(),
        "src/ember/governance/scripts/training_closure.py --print-hash failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let python_hash = String::from_utf8_lossy(&output.stdout).trim().to_string();
    assert_eq!(
        python_hash, expected_hash,
        "the Rust golden fixture's expected_closure_sha256 no longer matches what \
         src/ember/governance/scripts/training_closure.py computes for the same tree -- regenerate the golden \
         fixture per its own _comment"
    );
}
