from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "manifests" / "authority" / "path-migrations"
ORIGINAL = MIGRATIONS / "issue2015-mega-carrier-001-original-500-v1.json"
LANDED = MIGRATIONS / "issue2015-mega-carrier-001-v1.json"

EXPECTED_EXCLUDED_FOURTEEN = {
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
    original = _rows(ORIGINAL)
    landed = _rows(LANDED)
    residual = original - landed
    ruled = {
        row
        for row in residual
        if row[0].startswith("tests/ember_restart_model/")
        and row[0] != "tests/ember_restart_model/test_a1_certified_launch.py"
    }
    excluded = residual - ruled
    return original, landed, ruled, excluded


def test_original_500_map_is_exact_and_partitioned_without_overlap() -> None:
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == (
        "a8225a623d0a08bb961266d762cbe65815623f6602c151ac2c6cb4b0da423d81"
    )
    original, landed, ruled, excluded = _partition()

    assert len(original) == 500
    assert len(landed) == 476
    assert len(ruled) == 10
    assert len(excluded) == 14
    assert {source for source, _target in excluded} == EXPECTED_EXCLUDED_FOURTEEN
    assert landed.isdisjoint(ruled)
    assert landed.isdisjoint(excluded)
    assert ruled.isdisjoint(excluded)
    assert landed | ruled | excluded == original


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


def test_excluded_targets_have_no_path_or_dotted_module_references() -> None:
    """Prevent consumers from silently treating excluded renames as performed."""
    _original, _landed, _ruled, excluded = _partition()
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    ignored = {ORIGINAL.resolve(), Path(__file__).resolve()}

    target_needles: dict[str, set[str]] = {}
    for _source, target in sorted(excluded):
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
