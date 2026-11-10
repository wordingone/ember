// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! Static guard: a test that hand-writes a row the resource-guard monitor also
//! writes must open its daemon WITHOUT the monitor.
//!
//! On Windows, `Daemon::open` and `Daemon::open_with_resource_guard_seed` start
//! `spawn_resource_guard_monitor`, which every 2s
//! (`RESOURCE_GUARD_SAMPLE_INTERVAL_MS`) appends a real `now_ms()` row to
//! `resource_guard_observations` and `foreign_process_pressure_observations`
//! and overwrites `foreign_process_pressure_state` unconditionally. A test that
//! seeds one of those rows by hand and then reads it back through the daemon
//! passes or fails depending on whether a monitor tick lands in between. That
//! is the flake class behind CI runs 41811136406 (fixed one test at a time in
//! #2393) and 41995641002. `open_with_resource_guard_seed_without_monitor`
//! exists for exactly these tests.
//!
//! `resource_guard_state` is owned only when a test writes something other
//! than `admission_state='frozen'`: the monitor's two UPDATEs on that row both
//! carry `WHERE admission_state='open'`, so a hand-frozen row is never
//! overwritten by it.
//!
//! The scan reports its residual (tests it could not classify) and refuses on
//! any, rather than reading an unclassified test as compliant.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

/// Tests that deliberately need the live monitor while hand-writing a
/// monitor-owned row, as `(file::test, why the race cannot change the asserted
/// outcome)`. An entry with an empty reason does not exempt its test.
const ALLOWED: &[(&str, &str)] = &[(
    "rpc_named_pipe.rs::resource_guard_rearm_cli_transitions_the_persistent_daemon_from_exact_evidence",
    "drives the production CLI daemon process, which cannot take the in-process seam; its \
     synthetic timeline is anchored at the real clock (transition = now, freeze = now - 63s), \
     so a monitor row is newer than every seeded row and no newer than the re-arm instant: \
     it cannot make the window stale or future. (A real row below 1.5x the floors would still \
     reset the window; that depends on runner headroom, not on this race.)",
)];

const MONITOR_STARTING: &[&str] = &["Daemon::open(", "open_with_resource_guard_seed("];
const MONITOR_FREE: &[&str] = &["open_with_resource_guard_seed_without_monitor("];
const OWNED_WRITES: &[&str] = &[
    "UPDATE foreign_process_pressure_state",
    "INSERT INTO foreign_process_pressure_observations",
    "DELETE FROM foreign_process_pressure_observations",
    "INSERT INTO resource_guard_observations",
    "DELETE FROM resource_guard_observations",
];
const RESOURCE_GUARD_STATE_UPDATE: &str = "UPDATE resource_guard_state";

#[derive(Default, Debug, Clone, Copy)]
struct Reach {
    monitor: bool,
    monitor_free: bool,
    owned_write: bool,
}

#[derive(Default, Debug)]
struct Scan {
    violations: Vec<String>,
    unclassified: Vec<String>,
    tests_seen: usize,
    test_attributes: usize,
}

fn writes_owned_row(body: &str) -> bool {
    if OWNED_WRITES.iter().any(|needle| body.contains(needle)) {
        return true;
    }
    // A resource_guard_state UPDATE is monitor-owned unless it freezes.
    let mut rest = body;
    while let Some(at) = rest.find(RESOURCE_GUARD_STATE_UPDATE) {
        let tail = &rest[at..];
        let statement_end = tail.find("WHERE").unwrap_or(tail.len());
        if !tail[..statement_end].contains("admission_state='frozen'") {
            return true;
        }
        rest = &tail[RESOURCE_GUARD_STATE_UPDATE.len()..];
    }
    false
}

fn calls(body: &str, name: &str) -> bool {
    let needle = format!("{name}(");
    body.match_indices(&needle).any(|(at, _)| {
        at == 0 || {
            let before = body.as_bytes()[at - 1];
            !(before.is_ascii_alphanumeric() || before == b'_')
        }
    })
}

fn reach(
    name: &str,
    functions: &BTreeMap<String, (bool, String)>,
    visiting: &mut BTreeSet<String>,
) -> Reach {
    let body = &functions[name].1;
    let mut out = Reach {
        monitor: MONITOR_STARTING.iter().any(|needle| body.contains(needle)),
        monitor_free: MONITOR_FREE.iter().any(|needle| body.contains(needle)),
        owned_write: writes_owned_row(body),
    };
    visiting.insert(name.to_string());
    for (other, (other_is_test, _)) in functions {
        if *other_is_test || visiting.contains(other) || !calls(body, other) {
            continue;
        }
        let inner = reach(other, functions, visiting);
        out.monitor |= inner.monitor;
        out.monitor_free |= inner.monitor_free;
        out.owned_write |= inner.owned_write;
    }
    visiting.remove(name);
    out
}

fn scan_source(file: &str, source: &str) -> Scan {
    let lines: Vec<&str> = source.lines().collect();
    let starts: Vec<usize> = lines
        .iter()
        .enumerate()
        .filter(|(_, line)| line.starts_with("fn ") || line.starts_with("pub fn "))
        .map(|(index, _)| index)
        .collect();
    let mut functions: BTreeMap<String, (bool, String)> = BTreeMap::new();
    for (k, &start) in starts.iter().enumerate() {
        let end = starts.get(k + 1).copied().unwrap_or(lines.len());
        let mut attribute_start = start;
        while attribute_start > 0 && lines[attribute_start - 1].starts_with("#[") {
            attribute_start -= 1;
        }
        let is_test = lines[attribute_start..start]
            .iter()
            .any(|line| line.trim() == "#[test]");
        let signature = lines[start]
            .trim_start_matches("pub ")
            .trim_start_matches("fn ");
        let name: String = signature
            .chars()
            .take_while(|c| c.is_ascii_alphanumeric() || *c == '_')
            .collect();
        functions.insert(name, (is_test, lines[start..end].join("\n")));
    }

    let mut scan = Scan {
        test_attributes: lines.iter().filter(|line| line.trim() == "#[test]").count(),
        ..Scan::default()
    };
    for (name, (is_test, _)) in &functions {
        if !is_test {
            continue;
        }
        scan.tests_seen += 1;
        let reached = reach(name, &functions, &mut BTreeSet::new());
        let qualified = format!("{file}::{name}");
        let allowed = ALLOWED
            .iter()
            .any(|(entry, reason)| *entry == qualified && !reason.trim().is_empty());
        if !reached.owned_write || allowed {
            continue;
        }
        if reached.monitor {
            scan.violations.push(qualified);
        } else if !reached.monitor_free {
            scan.unclassified.push(qualified);
        }
    }
    scan
}

#[test]
fn no_test_hand_writes_a_monitor_owned_row_under_a_running_monitor() {
    let tests_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests");
    let this_file = Path::new(file!())
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap();
    let mut violations = Vec::new();
    let mut unclassified = Vec::new();
    let mut unparsed_attributes = Vec::new();
    let mut files = 0usize;
    for entry in fs::read_dir(&tests_dir).unwrap() {
        let path = entry.unwrap().path();
        let file = path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap()
            .to_string();
        if path.extension().and_then(|ext| ext.to_str()) != Some("rs") || file == this_file {
            continue;
        }
        files += 1;
        let scan = scan_source(&file, &fs::read_to_string(&path).unwrap());
        if scan.tests_seen != scan.test_attributes {
            // A #[test] the top-level splitter did not attribute (nested
            // module, unusual layout) is residual, not a pass.
            unparsed_attributes.push(format!(
                "{file}: {} #[test] attributes, {} parsed",
                scan.test_attributes, scan.tests_seen
            ));
        }
        violations.extend(scan.violations);
        unclassified.extend(scan.unclassified);
    }
    assert!(
        files > 0,
        "scanned no test sources under {}",
        tests_dir.display()
    );
    assert!(
        violations.is_empty() && unclassified.is_empty() && unparsed_attributes.is_empty(),
        "monitor-owned row guard REFUSED.\n\
         violations (hand-write a monitor-owned row under a monitor-starting constructor; \
         use open_with_resource_guard_seed_without_monitor): {violations:#?}\n\
         unclassified (write a monitor-owned row, no constructor found in-file): \
         {unclassified:#?}\n\
         unparsed #[test] attributes: {unparsed_attributes:#?}"
    );
}

#[test]
fn guard_flags_the_race_shape_and_accepts_the_cure() {
    let racing = concat!(
        "#[test]\n",
        "fn racing() {\n",
        "    let daemon = Daemon::open_with_resource_guard_seed(&db, seed).unwrap();\n",
        "    seed_pressure(&db);\n",
        "}\n",
        "\n",
        "fn seed_pressure(db: &Path) {\n",
        "    conn.execute(\"UPDATE foreign_process_pressure_state SET state='fenced' WHERE singleton=1\");\n",
        "}\n",
    );
    let scan = scan_source("racing.rs", racing);
    assert_eq!(scan.violations, vec!["racing.rs::racing".to_string()]);

    let cured = racing.replace(
        "open_with_resource_guard_seed(",
        "open_with_resource_guard_seed_without_monitor(",
    );
    let scan = scan_source("cured.rs", &cured);
    assert!(scan.violations.is_empty() && scan.unclassified.is_empty());

    let frozen_only = concat!(
        "#[test]\n",
        "fn frozen_only() {\n",
        "    let daemon = Daemon::open(&db).unwrap();\n",
        "    conn.execute(\"UPDATE resource_guard_state SET admission_state='frozen' WHERE singleton=1\");\n",
        "}\n",
    );
    assert!(scan_source("frozen.rs", frozen_only).violations.is_empty());

    let thaws = frozen_only.replace("'frozen'", "'open'");
    assert_eq!(
        scan_source("thaws.rs", &thaws).violations,
        vec!["thaws.rs::frozen_only".to_string()]
    );

    let orphan = concat!(
        "#[test]\n",
        "fn orphan() {\n",
        "    conn.execute(\"INSERT INTO resource_guard_observations(observed_at_ms) VALUES(1)\");\n",
        "}\n",
    );
    assert_eq!(
        scan_source("orphan.rs", orphan).unclassified,
        vec!["orphan.rs::orphan".to_string()]
    );
}
