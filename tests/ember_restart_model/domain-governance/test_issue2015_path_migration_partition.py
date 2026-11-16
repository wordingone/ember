# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "manifests" / "authority" / "path-migrations"
RECORD = (
    ROOT
    / "manifests"
    / "authority"
    / "path-migration-records"
    / "issue2015-original-500-v1.json"
)
LANDED_001 = MIGRATIONS / "issue2015-mega-carrier-001-v1.json"
LANDED_002 = MIGRATIONS / "issue2015-mega-carrier-002-v1.json"

EXPECTED_ORIGINAL_EXCLUDED_FOURTEEN = {
    "docs/authority/INVARIANT.md",
    "runtime/ember-lab/src/lib.rs",
    "runtime/ember-lab/src/main.rs",
    "runtime/ember-lab/tests/artifact_custody.rs",
    "runtime/ember-lab/tests/control_plane.rs",
    "scripts/cond4_behavior_surface.py",
    "scripts/ember_01_custody/census.py",
    "scripts/ember_01_custody/issue_census.py",
    "scripts/ember_01_identity/census_consumers.py",
    "scripts/ember_01_identity/checkpoint_save_load_identity_binding.py",
    "scripts/ember_01_identity/parameter_identity_binding.py",
    "scripts/ember_01_identity/validate_identity.py",
    "scripts/verify_ember01_completion.py",
    "tests/ember_restart_model/test_a1_certified_launch.py",
}

LATE_PERFORMED_AFTER_RECORD = {
    (
        "scripts/ember_01_custody/issue_census.py",
        "src/ember/governance/scripts/ember_01_custody/issue_census.py",
    )
}


def _rows(path: Path) -> set[tuple[str, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document["renames"]
    assert len(rows) == len({row["source_path"] for row in rows})
    assert len(rows) == len({row["target_path"] for row in rows})
    return {(row["source_path"], row["target_path"]) for row in rows}


def _partition() -> tuple[
    set[tuple[str, str]],
    set[tuple[str, str]],
    set[tuple[str, str]],
    set[tuple[str, str]],
]:
    document = json.loads(RECORD.read_text(encoding="utf-8"))
    assert document["schema_version"] == "ember-exact-path-migration-record/v1"
    assert document["original_map_raw_sha256"] == (
        "a8225a623d0a08bb961266d762cbe65815623f6602c151ac2c6cb4b0da423d81"
    )
    rows = document["original_rows"]
    assert len(rows) == len({row["source_path"] for row in rows})
    assert len(rows) == len({row["target_path"] for row in rows})
    original = {(row["source_path"], row["target_path"]) for row in rows}
    landed = {
        (row["source_path"], row["target_path"])
        for row in rows
        if row["disposition"] == "performed-001"
    }
    ruled = {
        (row["source_path"], row["target_path"])
        for row in rows
        if row["disposition"] == "performed-002"
    }
    excluded = {
        (row["source_path"], row["target_path"])
        for row in rows
        if row["disposition"] == "excluded"
    }
    assert {row["disposition"] for row in rows} == {
        "performed-001", "performed-002", "excluded",
    }
    return original, landed, ruled, excluded


def test_original_500_map_is_exact_and_partitioned_without_overlap() -> None:
    original, landed, ruled, excluded = _partition()

    assert len(original) == 500
    assert len(landed) == 476
    assert len(ruled) == 10
    assert len(excluded) == 14
    assert {source for source, _target in excluded} == EXPECTED_ORIGINAL_EXCLUDED_FOURTEEN
    assert landed.isdisjoint(ruled)
    assert landed.isdisjoint(excluded)
    assert ruled.isdisjoint(excluded)
    assert landed | ruled | excluded == original
    assert _rows(LANDED_001) == landed
    assert _rows(LANDED_002) == ruled


def test_ruled_ten_are_the_only_residual_rows_materialized_by_this_carrier() -> None:
    _original, _landed, ruled, _excluded = _partition()
    for source, target in ruled:
        assert not (ROOT / source).exists()
        assert (ROOT / target).is_file()


def test_every_performed_row_has_exactly_the_target_materialized() -> None:
    _original, landed, ruled, _excluded = _partition()
    for source, target in landed | ruled:
        assert not (ROOT / source).exists(), source
        assert (ROOT / target).is_file(), target


def test_legacy_tool_prefix_is_only_a_non_executable_tombstone() -> None:
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "tools/ember-restart-3b",
            "src/ember/infrastructure/tools/ember-restart-3b",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    tracked = [path for path in tracked if path]
    legacy = [
        path for path in tracked if path.startswith("tools/ember-restart-3b/")
    ]
    assert legacy == [
        "tools/ember-restart-3b/README.md"
    ]

    runtime_files = [path for path in tracked if path not in legacy]
    assert runtime_files
    for path in runtime_files:
        assert path.startswith(
            "src/ember/infrastructure/tools/ember-restart-3b/"
        ), path
        assert (ROOT / path).is_file(), path


LAB_PREFIX = "runtime/ember-lab/"
CERTIFIED_LAUNCH = (
    ROOT
    / "src"
    / "ember"
    / "infrastructure"
    / "tools"
    / "ember-restart-3b"
    / "certified_train_launch.py"
)
DOCS_INFORMATION_SYSTEM = ROOT / "scripts" / "docs_information_system.py"


def test_every_excluded_row_preserves_only_its_original_source() -> None:
    """The nine excluded rows whose source is still in this tree keep only that source."""
    _original, _landed, _ruled, excluded = _partition()
    live_excluded = excluded - LATE_PERFORMED_AFTER_RECORD
    in_tree = {row for row in live_excluded if not row[0].startswith(LAB_PREFIX)}
    assert len(live_excluded) == 13
    assert len(in_tree) == 9
    for source, target in in_tree:
        assert (ROOT / source).is_file(), source
        assert not (ROOT / target).exists(), target
    for source, target in LATE_PERFORMED_AFTER_RECORD:
        assert not (ROOT / source).exists(), source
        assert (ROOT / target).is_file(), target


def test_c22_lab_source_rows_are_gone_and_the_release_manifest_is_the_authority() -> None:
    """Named successor of the lab rows of the test above (C22).

    The four excluded rows whose source was under runtime/ember-lab are not
    weakened into an optional case: their sources are asserted absent from the
    tree and from the index, and the replacing authority (the pinned
    ember-lab-release-v1 manifest) is asserted to be what the launch consumer and
    the docs reconciliation bind to.
    """
    _original, _landed, _ruled, excluded = _partition()
    lab_rows = {row for row in excluded if row[0].startswith(LAB_PREFIX)}
    assert {source for source, _target in lab_rows} == {
        "runtime/ember-lab/src/lib.rs",
        "runtime/ember-lab/src/main.rs",
        "runtime/ember-lab/tests/artifact_custody.rs",
        "runtime/ember-lab/tests/control_plane.rs",
    }
    for source, target in lab_rows:
        assert not (ROOT / source).exists(), source
        assert not (ROOT / target).exists(), target
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "runtime/ember-lab"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    assert [path for path in tracked if path] == []
    assert not (ROOT / "runtime" / "ember-lab").exists()

    launch = CERTIFIED_LAUNCH.read_text(encoding="utf-8")
    assert 'EMBER_LAB_RELEASE_MANIFEST_NAME = "ember-lab-release.json"' in launch
    assert 'EMBER_LAB_RELEASE_MANIFEST_SCHEMA = "ember-lab-release-v1"' in launch
    assert "_pinned_ember_lab_release()" in launch
    assert "EMBER_LAB_SOURCE_RELATIVE_PATHS" not in launch
    docs = DOCS_INFORMATION_SYSTEM.read_text(encoding="utf-8")
    assert 'MOVED_PRIVATE_PREFIXES = {"runtime/ember-lab": "wordingone/ember-lab"}' in docs


def test_excluded_targets_have_no_path_or_dotted_module_references() -> None:
    """Prevent consumers from silently treating excluded renames as performed."""
    _original, _landed, _ruled, excluded = _partition()
    live_excluded = excluded - LATE_PERFORMED_AFTER_RECORD
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    ignored = {RECORD.resolve(), Path(__file__).resolve()}

    target_needles: dict[str, set[str]] = {}
    for _source, target in sorted(live_excluded):
        target_needles[target] = {target}
        if target.endswith(".py"):
            target_needles[target].add(target[:-3].replace("/", "."))

    references: dict[str, list[str]] = {}
    for relative in tracked:
        path = ROOT / relative
        if not relative or path.resolve() in ignored or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for target, needles in target_needles.items():
            if any(needle in text for needle in needles):
                references.setdefault(target, []).append(relative)

    assert references == {}, json.dumps(references, indent=2, sort_keys=True)
