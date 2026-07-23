#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""board_twin_adjudication_test.py -- regression fixtures for R3 board
canonicality (fspec-R3-1436-20260722T213546Z): duplicate-epoch rules
D1/D2/D3, untracked-twin classification, supersession-chain precedence, and
the four mechanical freshness triggers.

Extends `c_custody_twin_resolution_test.py` (issue #535) rather than
duplicating it: reuses its git fixture helpers (`_init_git_repo`,
`_git_add_and_commit`) and carries forward the same twin DOCTRINE --
evidence must be tracked at HEAD, resolution scope is explicit (here:
same-basename cross-location, vs #535's same-directory same-stem), every
positive rule ships its negative control, nothing resolves by deletion --
extended from redaction-twins to BOARD-twins. Each test builds a throwaway
git repo with a synthetic canonical dir + index and exercises
`scripts/ember_totality/board_index.py`'s public API plus its CLI (for the
exit-code-facing assertions).

Full rule text: docs/spec/board-canonicality-v1.md
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import board_index  # noqa: E402
from c_custody_twin_resolution_test import _init_git_repo, _git_add_and_commit  # noqa: E402

BOARD_INDEX_SCRIPT = HERE / "board_index.py"


def _run_board_index(repo_root: Path, *args: str):
    """Run board_index.py --root <repo_root> <args>, return (stdout, exit_code)."""
    result = subprocess.run(
        [sys.executable, str(BOARD_INDEX_SCRIPT), "--root", str(repo_root)] + list(args),
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result.stdout.strip(), result.returncode


def _new_repo(tmpdir: str) -> Path:
    """A throwaway repo with the surfaces collect_basis()/probe_set_sha256()
    read: a receipts-totality dir, a receipts dir, GOAL.md and
    conditions-v1.md stand-ins, and one tracked probe .py."""
    repo = Path(tmpdir) / "test_repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "receipts").mkdir()
    (repo / "scripts" / "ember_totality" / "receipts-totality").mkdir(parents=True)
    (repo / "docs" / "spec").mkdir(parents=True)
    (repo / "GOAL.md").write_text("stand-in GOAL.md v1\n", encoding="utf-8")
    (repo / "docs" / "spec" / "conditions-v1.md").write_text(
        "stand-in conditions v1\n", encoding="utf-8"
    )
    (repo / "scripts" / "ember_totality" / "dummy_probe.py").write_text(
        "# dummy probe stand-in for probe_set_sha256 fixture\n", encoding="utf-8"
    )
    return repo


def _receipt_bytes(green: int, red: int, unevaluable: int, pct_green: float) -> bytes:
    return json.dumps(
        {"summary": {"green": green, "red": red, "unevaluable": unevaluable, "pct_green": pct_green}},
        indent=2,
    ).encode("utf-8") + b"\n"


def _write_and_track(repo: Path, rel: str, data: bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _write_index(repo: Path, rows) -> Path:
    index_path = repo / "scripts" / "ember_totality" / "receipts-totality" / "BOARD-INDEX.jsonl"
    with open(index_path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row))
            fh.write("\n")
    return index_path


def _append_index(index_path: Path, row) -> None:
    with open(index_path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row))
        fh.write("\n")


def test_d1_positive_byte_identical_location_twin_resolves():
    """D1: same-basename tracked in receipts/ and the canonical dir,
    byte-identical, with a byte_twin_of row -> verify exit 0 (the #535
    tracked-at-HEAD twin-resolution pattern extended to board twins)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        data = _receipt_bytes(5, 3, 0, 62.5)
        name = "ember-totality-20260101T000000Z.json"
        canonical_rel = "scripts/ember_totality/receipts-totality/" + name
        noncanonical_rel = "receipts/" + name
        _write_and_track(repo, canonical_rel, data)
        _write_and_track(repo, noncanonical_rel, data)
        _git_add_and_commit(repo, "twin board receipt, byte-identical, two locations")

        sha = hashlib.sha256(data).hexdigest()
        _write_index(repo, [
            {"row_type": "board", "ts": "20260101T000000Z", "path": canonical_rel,
             "sha256": sha, "indexed_ts": "2026-01-01T00:00:00Z",
             "basis": board_index._unknown_basis(),
             "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5}},
            {"row_type": "noncanonical", "ts": "20260101T000000Z", "path": noncanonical_rel,
             "sha256": sha, "indexed_ts": "2026-01-01T00:00:00Z",
             "location_class": "receipts", "kept_because": "test fixture",
             "byte_twin_of": canonical_rel},
        ])
        _git_add_and_commit(repo, "index the twin")

        output, code = _run_board_index(repo, "verify")
        assert code == 0, "expected exit 0, got " + str(code) + ": " + output
        expected_id = name[: -len(".json")]
        assert "CURRENT=" + expected_id in output, output
        print("PASS: D1 byte-identical location twin resolves, verify exit 0")


def test_d2_differing_bytes_requires_supersession():
    """D2 negative control: same basename, different bytes, no supersession
    -> verify exit 1 naming the pair; adding a supersession row -> exit 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name = "ember-totality-20260102T000000Z.json"
        canonical_rel = "scripts/ember_totality/receipts-totality/" + name
        noncanonical_rel = "receipts/" + name
        data_a = _receipt_bytes(5, 3, 0, 62.5)
        data_b = _receipt_bytes(6, 2, 0, 75.0)
        _write_and_track(repo, canonical_rel, data_a)
        _write_and_track(repo, noncanonical_rel, data_b)
        _git_add_and_commit(repo, "same-basename pair, differing bytes")

        sha_a = hashlib.sha256(data_a).hexdigest()
        sha_b = hashlib.sha256(data_b).hexdigest()
        index_path = _write_index(repo, [
            {"row_type": "board", "ts": "20260102T000000Z", "path": canonical_rel,
             "sha256": sha_a, "indexed_ts": "2026-01-02T00:00:00Z",
             "basis": board_index._unknown_basis(),
             "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5}},
            {"row_type": "noncanonical", "ts": "20260102T000000Z", "path": noncanonical_rel,
             "sha256": sha_b, "indexed_ts": "2026-01-02T00:00:00Z",
             "location_class": "receipts", "kept_because": "test fixture",
             "byte_twin_of": None},
        ])
        _git_add_and_commit(repo, "index the differing pair, no supersession")

        output, code = _run_board_index(repo, "verify")
        assert code == 1, "expected exit 1 (D2 red), got " + str(code) + ": " + output
        assert "D2" in output and canonical_rel in output and noncanonical_rel in output, output

        _append_index(index_path, {
            "row_type": "supersession",
            "old": {"path": noncanonical_rel, "sha256": sha_b},
            "new": {"path": canonical_rel, "sha256": sha_a},
            "reason": "test supersession",
            "ts": "2026-01-02T00:01:00Z",
            "authority": "test",
        })
        _git_add_and_commit(repo, "add covering supersession row")

        output2, code2 = _run_board_index(repo, "verify")
        assert code2 == 0, "expected exit 0 after supersession, got " + str(code2) + ": " + output2
        print("PASS: D2 differing bytes red without supersession, green with one")


def test_d3_identical_basis_rerun_requires_supersession():
    """D3: two board rows with identical non-UNKNOWN basis (a re-run with
    nothing changed) -> exit 1 without an edge; with an edge -> exit 0 and
    current_board returns the survivor."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name_a = "ember-totality-20260103T000000Z.json"
        name_b = "ember-totality-20260103T010000Z.json"
        rel_a = "scripts/ember_totality/receipts-totality/" + name_a
        rel_b = "scripts/ember_totality/receipts-totality/" + name_b
        data_a = _receipt_bytes(5, 3, 0, 62.5)
        data_b = _receipt_bytes(5, 3, 0, 62.5)
        _write_and_track(repo, rel_a, data_a)
        _write_and_track(repo, rel_b, data_b)
        _git_add_and_commit(repo, "two board runs, same basis")

        same_basis = {
            "governing_commit": "deadbeef", "goal_sha256": "a" * 64,
            "conditions_spec_sha256": "b" * 64, "probe_set_sha256": "c" * 64,
            "receipts_head_commit": "cafef00d", "subject_identity_sha256": None,
            "subject_identity_source": "test",
        }
        sha_a = hashlib.sha256(data_a).hexdigest()
        sha_b = hashlib.sha256(data_b).hexdigest()
        index_path = _write_index(repo, [
            {"row_type": "board", "ts": "20260103T000000Z", "path": rel_a, "sha256": sha_a,
             "indexed_ts": "2026-01-03T00:00:00Z", "basis": same_basis,
             "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5}},
            {"row_type": "board", "ts": "20260103T010000Z", "path": rel_b, "sha256": sha_b,
             "indexed_ts": "2026-01-03T01:00:00Z", "basis": same_basis,
             "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5}},
        ])
        _git_add_and_commit(repo, "index both, no edge")

        output, code = _run_board_index(repo, "verify")
        assert code == 1, "expected exit 1 (D3 red), got " + str(code) + ": " + output
        assert "D3" in output, output

        _append_index(index_path, {
            "row_type": "supersession",
            "old": {"path": rel_a, "sha256": sha_a},
            "new": {"path": rel_b, "sha256": sha_b},
            "reason": "same-basis re-run, second is the survivor",
            "ts": "2026-01-03T01:01:00Z",
            "authority": "test",
        })
        _git_add_and_commit(repo, "add D3 edge")

        output2, code2 = _run_board_index(repo, "verify")
        assert code2 == 0, "expected exit 0 after edge, got " + str(code2) + ": " + output2
        expected_id = name_b[: -len(".json")]
        assert "CURRENT=" + expected_id in output2, output2
        print("PASS: D3 identical-basis rerun red without edge, survivor selected with one")


def test_untracked_canonical_board_file_is_unlanded_never_current():
    """Untracked canonical-dir board file -> classify reports UNLANDED,
    current_board never selects it (mirrors #535's third test)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        tracked_name = "ember-totality-20260104T000000Z.json"
        tracked_rel = "scripts/ember_totality/receipts-totality/" + tracked_name
        tracked_data = _receipt_bytes(5, 3, 0, 62.5)
        _write_and_track(repo, tracked_rel, tracked_data)
        _git_add_and_commit(repo, "one tracked board receipt")

        untracked_name = "ember-totality-20260105T000000Z.json"  # newer ts, but untracked
        untracked_path = repo / "scripts" / "ember_totality" / "receipts-totality" / untracked_name
        untracked_path.write_bytes(_receipt_bytes(9, 1, 0, 90.0))
        # left untracked -- no git add

        result = board_index.classify(str(repo))
        unlanded_rel = "scripts/ember_totality/receipts-totality/" + untracked_name
        assert unlanded_rel in result["unlanded"], result["unlanded"]
        assert not any(b["path"] == unlanded_rel for b in result["board"]), result["board"]

        sha_tracked = hashlib.sha256(tracked_data).hexdigest()
        index_path = _write_index(repo, [
            {"row_type": "board", "ts": "20260104T000000Z", "path": tracked_rel,
             "sha256": sha_tracked, "indexed_ts": "2026-01-04T00:00:00Z",
             "basis": board_index._unknown_basis(),
             "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5}},
        ])
        _git_add_and_commit(repo, "index the tracked receipt only")

        rows, _skipped = board_index.load_index(index_path)
        current_path, _current_row = board_index.current_board(rows)
        assert current_path == tracked_rel, current_path
        print("PASS: untracked canonical-dir board file is UNLANDED, never current")


def test_supersession_old_side_never_current_even_if_newest():
    """The old side of a supersession edge is never current, even when its
    ts is literally the newest in the index -- supersession dominates
    ts-recency, never the reverse."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name_old = "ember-totality-20260106T120000Z.json"  # newest ts
        name_new = "ember-totality-20260106T090000Z.json"  # older ts, true survivor
        rel_old = "scripts/ember_totality/receipts-totality/" + name_old
        rel_new = "scripts/ember_totality/receipts-totality/" + name_new
        data_old = _receipt_bytes(4, 4, 0, 50.0)
        data_new = _receipt_bytes(6, 2, 0, 75.0)
        _write_and_track(repo, rel_old, data_old)
        _write_and_track(repo, rel_new, data_new)
        _git_add_and_commit(repo, "two board runs, older is the true survivor")

        sha_old = hashlib.sha256(data_old).hexdigest()
        sha_new = hashlib.sha256(data_new).hexdigest()
        _write_index(repo, [
            {"row_type": "board", "ts": "20260106T120000Z", "path": rel_old, "sha256": sha_old,
             "indexed_ts": "2026-01-06T12:00:00Z", "basis": board_index._unknown_basis(),
             "summary": {"green": 4, "red": 4, "unevaluable": 0, "pct_green": 50.0}},
            {"row_type": "board", "ts": "20260106T090000Z", "path": rel_new, "sha256": sha_new,
             "indexed_ts": "2026-01-06T09:00:00Z", "basis": board_index._unknown_basis(),
             "summary": {"green": 6, "red": 2, "unevaluable": 0, "pct_green": 75.0}},
            {"row_type": "supersession",
             "old": {"path": rel_old, "sha256": sha_old},
             "new": {"path": rel_new, "sha256": sha_new},
             "reason": "the newest-ts run was a botched re-run; the earlier run is the true record",
             "ts": "2026-01-06T12:30:00Z", "authority": "test"},
        ])
        _git_add_and_commit(repo, "index with an explicit reverse-chronology supersession")

        index_path = repo / "scripts" / "ember_totality" / "receipts-totality" / "BOARD-INDEX.jsonl"
        loaded_rows, _skipped = board_index.load_index(index_path)
        current_path, _current_row = board_index.current_board(loaded_rows)
        assert current_path == rel_new, current_path
        print("PASS: supersession old side never current, even when newest-ts")


def test_freshness_four_triggers_and_unknown_basis():
    """Build a repo, index a board row via a REAL collect_basis() snapshot;
    assert FRESH. Flip each of the four trigger surfaces one at a time
    (probe .py, conditions-v1.md stand-in, GOAL.md stand-in, a new receipts/
    commit), asserting STALE with the expected changed entry present each
    time. An UNKNOWN-basis row is always STALE regardless of the live tree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name = "ember-totality-20260107T000000Z.json"
        rel = "scripts/ember_totality/receipts-totality/" + name
        data = _receipt_bytes(5, 3, 0, 62.5)
        _write_and_track(repo, rel, data)
        # Seed receipts/ with a tracked file so receipts_head_commit is a
        # real hash at baseline, not "UNKNOWN" (git never tracks empty dirs).
        _write_and_track(repo, "receipts/seed.json", b'{"seed": true}\n')
        _git_add_and_commit(repo, "initial receipt + surfaces + receipts/ seed")

        basis = board_index.collect_basis(str(repo))
        for field in board_index._BASIS_FIELDS_UNKNOWN_CAPABLE:
            assert basis[field] != "UNKNOWN", (field, basis)
        sha = hashlib.sha256(data).hexdigest()
        row = {
            "row_type": "board", "ts": "20260107T000000Z", "path": rel, "sha256": sha,
            "indexed_ts": "2026-01-07T00:00:00Z", "basis": basis,
            "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5},
        }

        result = board_index.freshness(row, str(repo))
        assert result["verdict"] == "FRESH", result
        assert result["changed"] == [], result
        print("PASS: freshly-indexed board row reads FRESH")

        (repo / "scripts" / "ember_totality" / "dummy_probe.py").write_text(
            "# dummy probe stand-in, mutated\n", encoding="utf-8"
        )
        _git_add_and_commit(repo, "mutate a probe .py")
        result = board_index.freshness(row, str(repo))
        assert result["verdict"] == "STALE", result
        assert "probe_set_sha256" in result["changed"], result
        print("PASS: probe .py mutation -> STALE via probe_set_sha256 (condition code trigger)")

        (repo / "docs" / "spec" / "conditions-v1.md").write_text(
            "stand-in conditions v1, mutated\n", encoding="utf-8"
        )
        _git_add_and_commit(repo, "mutate conditions-v1.md")
        result = board_index.freshness(row, str(repo))
        assert result["verdict"] == "STALE", result
        assert "conditions_spec_sha256" in result["changed"], result
        print("PASS: conditions-v1.md mutation -> STALE via conditions_spec_sha256 (condition code trigger)")

        (repo / "GOAL.md").write_text("stand-in GOAL.md v1, mutated\n", encoding="utf-8")
        _git_add_and_commit(repo, "mutate GOAL.md")
        result = board_index.freshness(row, str(repo))
        assert result["verdict"] == "STALE", result
        assert "goal_sha256" in result["changed"], result
        print("PASS: GOAL.md mutation -> STALE via goal_sha256 (governing hashes trigger)")

        (repo / "receipts" / "new-evidence.json").write_text("{}\n", encoding="utf-8")
        _git_add_and_commit(repo, "new evidence under receipts/")
        result = board_index.freshness(row, str(repo))
        assert result["verdict"] == "STALE", result
        assert "receipts_head_commit" in result["changed"], result
        print("PASS: new receipts/ commit -> STALE via receipts_head_commit (evidence-index head trigger)")

        unknown_row = dict(row)
        unknown_row["basis"] = board_index._unknown_basis()
        result = board_index.freshness(unknown_row, str(repo))
        assert result["verdict"] == "STALE", result
        assert result["changed"] == ["basis:UNKNOWN_PRE_INDEX"], result
        print("PASS: UNKNOWN-basis row is always STALE (basis:UNKNOWN_PRE_INDEX)")


if __name__ == "__main__":
    tests = [
        test_d1_positive_byte_identical_location_twin_resolves,
        test_d2_differing_bytes_requires_supersession,
        test_d3_identical_basis_rerun_requires_supersession,
        test_untracked_canonical_board_file_is_unlanded_never_current,
        test_supersession_old_side_never_current_even_if_newest,
        test_freshness_four_triggers_and_unknown_basis,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
            print("FAIL: " + t.__name__ + ": " + str(e))
    print()
    if failures:
        print("FAIL: " + str(len(failures)) + "/" + str(len(tests)) + " tests failed")
        sys.exit(1)
    print("PASS: All " + str(len(tests)) + " tests passed")
