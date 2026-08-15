// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// NO-TEMP policy (per operator direction): none of ember's stack, current, past, or
// future, may live in system temp. This module is the Rust-side twin of
// tools/ember-cli/src/utils/ember-scratch.ts (emberScratchDir) -- the one canonical
// ember-owned scratch root for ember-lab call sites. See tools/no_temp_allowlist and
// tools/check_no_temp.py for the enforcement gate covering the rest of the stack.

use std::io;
use std::path::{Path, PathBuf};

/// Resolves the user's home directory without an extra crate dependency:
/// `USERPROFILE` on Windows, `HOME` elsewhere, falling back to `.` only if
/// neither is set.
fn home_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(profile) = std::env::var("USERPROFILE") {
            if !profile.is_empty() {
                return PathBuf::from(profile);
            }
        }
    }
    #[cfg(not(windows))]
    {
        if let Ok(home) = std::env::var("HOME") {
            if !home.is_empty() {
                return PathBuf::from(home);
            }
        }
    }
    PathBuf::from(".")
}

/// Returns the ember-owned scratch directory for `purpose`, creating it if
/// necessary. Never touches system temp. Mirrors the TypeScript
/// `emberScratchDir` contract exactly:
///
/// Path shape: `<EMBER_HOME>/.runtime/<purpose>/<pid>`
/// - `EMBER_HOME` = the `EMBER_HOME` env var if set, else `~/.ember`.
/// - The directory is created recursively before returning.
/// - The returned path is canonicalized so downstream path comparisons are
///   case-correct on case-insensitive filesystems (Windows/macOS).
pub fn ember_scratch_dir(purpose: &str) -> io::Result<PathBuf> {
    let ember_home = std::env::var("EMBER_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| home_dir().join(".ember"));
    ember_scratch_dir_under(&ember_home, purpose)
}

/// `ember_scratch_dir` with the root supplied explicitly.
///
/// Exists so the path contract can be tested without `set_var("EMBER_HOME")`:
/// unit tests share one process, so mutating that variable retargets
/// `ember_scratch_dir` for every test running concurrently.
pub(crate) fn ember_scratch_dir_under(ember_home: &Path, purpose: &str) -> io::Result<PathBuf> {
    let scratch_path = ember_home
        .join(".runtime")
        .join(purpose)
        .join(std::process::id().to_string());
    std::fs::create_dir_all(&scratch_path)?;
    std::fs::canonicalize(&scratch_path)
}

#[cfg(test)]
mod ember_scratch_dir_tests {
    use super::ember_scratch_dir_under;
    use std::path::PathBuf;

    /// In-tree (never system-temp) scratch root for THIS test's own EMBER_HOME
    /// fixture -- consistent with the policy this module enforces.
    fn test_fixture_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target")
            .join("no-temp-gate-test-fixtures")
            .join(format!("ember-home-{}", std::process::id()))
    }

    // This test used to prove its point by pointing %TEMP%/%TMP% at a bogus
    // wrongly-cased path and setting %EMBER_HOME%, all via `env::set_var`.
    // Those writes are process-global and unit tests share one process, so
    // every test running concurrently saw them: `std::env::temp_dir()` started
    // returning the bogus root, and the teardown's `remove_dir_all` deleted
    // scratch directories out from under other tests mid-run. It was also
    // proving nothing -- `ember_scratch_dir` reads `EMBER_HOME`, never
    // `TEMP`/`TMP`, so the bogus override could not have leaked even in
    // principle. Source-level enforcement of the NO-TEMP policy is
    // `tools/check_no_temp.py`; the path contract is checked here against an
    // explicit root instead.
    #[test]
    fn scratch_dir_lands_under_its_root() {
        let ember_home = test_fixture_root();
        let _ = std::fs::remove_dir_all(&ember_home);

        let dir = ember_scratch_dir_under(&ember_home, "binding-snapshot-test")
            .expect("scratch dir creation must succeed");
        assert!(dir.exists(), "scratch dir must exist after creation");

        let dir_lower = dir.to_string_lossy().to_ascii_lowercase();
        let ember_home_lower = ember_home.to_string_lossy().to_ascii_lowercase();
        assert!(
            dir_lower.contains(&ember_home_lower),
            "scratch dir {dir_lower} did not land under root {ember_home_lower}"
        );

        let _ = std::fs::remove_dir_all(&ember_home);
    }
}
