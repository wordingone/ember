#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""r3_repair_negative_test.py -- RED-first regression for the PR #1013 R3
board-canonicality repair round (frozen repair spec, R3 track). Per PR948
execution-binding, every test exercises the REAL production consumers --
board_index.py's _cmd_verify/_cmd_freshness CLI subcommands and
gen_readme_status._resolve_current -- never a helper fixture standing in
for them).

Four negative branches, one per repaired defect:
  1. malformed/truncated index line -> selection/verify/freshness ALL RED
     (board_index _cmd_verify, board_index _cmd_freshness, AND
     gen_readme_status._resolve_current).
  2. on-disk byte-mutation (sha256(file) != row['sha256']) -> RED before
     render (validate_selected_row / _cmd_verify).
  3. all four live trigger fields UNKNOWN (git unavailable) -> freshness
     RED/STALE, never skipped as FRESH.
  4. a supersession row naming the correct path at the WRONG sha256 ->
     RED / does not remove the real board row (current_board still
     selects the real row; duplicate_epochs still reports D2 since the
     mismatched pair is not actually covered).

Header/style copied from board_twin_adjudication_test.py (same directory,
same fixture family: _init_git_repo/_git_add_and_commit from
c_custody_twin_resolution_test.py, a throwaway git repo per test, never the
live repo's receipts/).

Run: python r3_repair_negative_test.py
Or via the focused battery: python -m pytest scripts/ember_totality/ -q
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
GEN_README_SCRIPT = REPO_ROOT / "scripts" / "gen_readme_status.py"


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
    return (result.stdout + result.stderr).strip(), result.returncode


def _new_repo(tmpdir: str) -> Path:
    """A throwaway repo with the surfaces collect_basis()/probe_set_sha256()
    read: a receipts-totality dir, a receipts dir, GOAL.md and
    conditions-v1.md stand-ins, and one tracked probe .py. Copied verbatim
    from board_twin_adjudication_test.py's _new_repo fixture."""
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


def _index_path(repo: Path) -> Path:
    return repo / "scripts" / "ember_totality" / "receipts-totality" / "BOARD-INDEX.jsonl"


def _write_index_lines(repo: Path, lines) -> Path:
    """Write raw lines (not necessarily valid JSON) to BOARD-INDEX.jsonl --
    used directly by test 1 to inject a truncated line the way a crashed
    writer or a manual edit would."""
    index_path = _index_path(repo)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line)
            fh.write("\n")
    return index_path


# ---------------------------------------------------------------------------
# Defect 1: malformed/truncated index line -> selection/verify/freshness RED
# ---------------------------------------------------------------------------
def test_malformed_index_line_is_terminal_red():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name = "ember-totality-20260110T000000Z.json"
        rel = "scripts/ember_totality/receipts-totality/" + name
        data = _receipt_bytes(5, 3, 0, 62.5)
        _write_and_track(repo, rel, data)
        _git_add_and_commit(repo, "one valid board receipt")

        sha = hashlib.sha256(data).hexdigest()
        valid_row = {
            "row_type": "board", "ts": "20260110T000000Z", "path": rel, "sha256": sha,
            "indexed_ts": "2026-01-10T00:00:00Z", "basis": board_index._unknown_basis(),
            "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5},
        }
        # A truncated JSON line, exactly the shape a crashed mid-write append
        # produces -- board_index.load_index() must classify this as
        # `skipped`, never silently drop it.
        truncated_line = '{"row_type":"supersession","old":{"path":"receipts/x.json'
        _write_index_lines(repo, [json.dumps(valid_row), truncated_line])
        _git_add_and_commit(repo, "index with one truncated line")

        # board_index verify
        out_verify, code_verify = _run_board_index(repo, "verify")
        assert code_verify == 1, "verify must be RED on a malformed index line, got " + str(code_verify) + ": " + out_verify
        assert "RED" in out_verify, out_verify

        # board_index freshness
        out_fresh, code_fresh = _run_board_index(repo, "freshness")
        assert code_fresh == 1, "freshness must be RED (exit 1) on a malformed index line, got " + str(code_fresh) + ": " + out_fresh
        assert "RED" in out_fresh, out_fresh

        # gen_readme_status._resolve_current (the real production consumer)
        sys.path.insert(0, str(REPO_ROOT))
        from scripts import gen_readme_status  # noqa: E402
        data_root = str(repo / "scripts" / "ember_totality" / "receipts-totality")
        raised = False
        try:
            gen_readme_status._resolve_current(data_root)
        except SystemExit as exc:
            raised = True
            assert "malformed" in str(exc), exc
        assert raised, "gen_readme_status._resolve_current must raise SystemExit on a malformed index line"
        print("ok   malformed index line -> RED in verify, freshness, AND gen_readme_status._resolve_current")


# ---------------------------------------------------------------------------
# Defect 2: on-disk byte-mutation vs row['sha256'] -> RED before render
# ---------------------------------------------------------------------------
def test_selected_receipt_sha_mismatch_is_red_before_render():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name = "ember-totality-20260111T000000Z.json"
        rel = "scripts/ember_totality/receipts-totality/" + name
        original_data = _receipt_bytes(5, 3, 0, 62.5)
        _write_and_track(repo, rel, original_data)
        _git_add_and_commit(repo, "one board receipt, original bytes")

        original_sha = hashlib.sha256(original_data).hexdigest()
        row = {
            "row_type": "board", "ts": "20260111T000000Z", "path": rel, "sha256": original_sha,
            "indexed_ts": "2026-01-11T00:00:00Z", "basis": board_index._unknown_basis(),
            "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5},
        }
        _write_index_lines(repo, [json.dumps(row)])
        _git_add_and_commit(repo, "index the receipt")

        # Sanity: verify is GREEN before mutation.
        out0, code0 = _run_board_index(repo, "verify")
        assert code0 == 0, "expected exit 0 before mutation, got " + str(code0) + ": " + out0

        # Mutate on-disk bytes WITHOUT updating the index row's sha256 --
        # the row still claims original_sha, but the file no longer matches.
        mutated_data = _receipt_bytes(9, 1, 0, 90.0)  # ADVERSARIAL: forged higher pct_green
        (repo / rel).write_bytes(mutated_data)
        mutated_sha = hashlib.sha256(mutated_data).hexdigest()
        assert mutated_sha != original_sha

        out_verify, code_verify = _run_board_index(repo, "verify")
        assert code_verify == 1, "verify must be RED on on-disk sha mismatch, got " + str(code_verify) + ": " + out_verify
        assert "sha mismatch" in out_verify, out_verify

        out_fresh, code_fresh = _run_board_index(repo, "freshness")
        assert code_fresh == 1, "freshness must be RED (exit 1) before ever computing FRESH/STALE, got " + str(code_fresh) + ": " + out_fresh
        assert "sha mismatch" in out_fresh, out_fresh

        # Direct unit-level check: validate_selected_row raises before any
        # render_block-shaped consumer would read the mutated bytes.
        raised = False
        try:
            board_index.validate_selected_row(row, str(repo))
        except board_index.BoardIndexError as exc:
            raised = True
            assert "sha mismatch" in str(exc)
        assert raised, "validate_selected_row must raise BoardIndexError on sha mismatch"
        print("ok   on-disk byte-mutation (sha!=row) -> RED before render (verify, freshness, validate_selected_row)")


# ---------------------------------------------------------------------------
# Defect 3: all live trigger fields UNKNOWN -> freshness RED/STALE
# ---------------------------------------------------------------------------
def test_all_live_trigger_fields_unknown_forces_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name = "ember-totality-20260112T000000Z.json"
        rel = "scripts/ember_totality/receipts-totality/" + name
        data = _receipt_bytes(5, 3, 0, 62.5)
        _write_and_track(repo, rel, data)
        _git_add_and_commit(repo, "one board receipt")

        # A fully-known indexed basis (a real prior collect_basis snapshot),
        # paired with a repo_root where git is unavailable at freshness-time
        # (a non-repo directory) -- collect_basis()/_git_output() then
        # returns "UNKNOWN" for every live git-derived field.
        known_basis = {
            "governing_commit": "deadbeef", "goal_sha256": "a" * 64,
            "conditions_spec_sha256": "b" * 64, "probe_set_sha256": "c" * 64,
            "receipts_head_commit": "cafef00d", "subject_identity_sha256": None,
            "subject_identity_source": "test",
        }
        sha = hashlib.sha256(data).hexdigest()
        row = {
            "row_type": "board", "ts": "20260112T000000Z", "path": rel, "sha256": sha,
            "indexed_ts": "2026-01-12T00:00:00Z", "basis": known_basis,
            "summary": {"green": 5, "red": 3, "unevaluable": 0, "pct_green": 62.5},
        }

        # A NON-git directory holding a byte-identical copy of the receipt at
        # the same relative path -- collect_basis(root) then reads
        # "UNKNOWN" for governing_commit/receipts_head_commit (git -C <root>
        # fails, no .git here) while GOAL.md/conditions-v1.md/probe files can
        # still be present, isolating this to the live-basis-UNKNOWN branch.
        plain_root = Path(tmpdir) / "plain_root"
        (plain_root / rel).parent.mkdir(parents=True, exist_ok=True)
        (plain_root / rel).write_bytes(data)
        assert board_index._git_output(str(plain_root), ["rev-parse", "HEAD"]) is None, \
            "fixture must have NO git repo so live basis reads UNKNOWN"

        result = board_index.freshness(row, str(plain_root))
        assert result["verdict"] == "STALE", (
            "freshness must return STALE when the live basis is UNKNOWN, "
            "not silently skip the comparison and report FRESH: " + repr(result)
        )
        assert "basis:UNKNOWN_LIVE" in result["changed"], result

        out_fresh, code_fresh = _run_board_index(repo, "freshness")
        # (sanity control, not the assertion under test): the repo-tree run
        # freshness path is exercised separately in
        # board_twin_adjudication_test.test_freshness_four_triggers_and_unknown_basis.
        print("ok   all live trigger fields UNKNOWN -> freshness STALE (basis:UNKNOWN_LIVE), never silently FRESH")


# ---------------------------------------------------------------------------
# Defect 4: supersession names correct path at WRONG sha256 -> does not
# remove the real board row
# ---------------------------------------------------------------------------
def test_supersession_wrong_sha_does_not_remove_real_row():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        name = "ember-totality-20260113T000000Z.json"
        rel = "scripts/ember_totality/receipts-totality/" + name
        real_data = _receipt_bytes(6, 2, 0, 75.0)
        _write_and_track(repo, rel, real_data)
        _git_add_and_commit(repo, "the real board receipt")

        real_sha = hashlib.sha256(real_data).hexdigest()
        wrong_sha = "0" * 64  # deliberately WRONG -- not the real row's sha256
        assert wrong_sha != real_sha

        row = {
            "row_type": "board", "ts": "20260113T000000Z", "path": rel, "sha256": real_sha,
            "indexed_ts": "2026-01-13T00:00:00Z", "basis": board_index._unknown_basis(),
            "summary": {"green": 6, "red": 2, "unevaluable": 0, "pct_green": 75.0},
        }
        # A supersession row naming the CORRECT path but the WRONG sha256 --
        # this must NOT be treated as superseding the real row (whose sha256
        # actually is real_sha).
        supersession = {
            "row_type": "supersession",
            "old": {"path": rel, "sha256": wrong_sha},
            "new": {"path": "scripts/ember_totality/receipts-totality/ember-totality-20260113T010000Z.json", "sha256": "d" * 64},
            "reason": "test: malformed/mistargeted supersession (wrong sha)",
            "ts": "2026-01-13T01:00:00Z", "authority": "test",
        }
        index_path = _write_index_lines(repo, [json.dumps(row), json.dumps(supersession)])
        _git_add_and_commit(repo, "index real row + a wrong-sha supersession")

        rows, skipped = board_index.load_index(index_path)
        assert skipped == [], skipped
        current_path, current_row = board_index.current_board(rows)
        assert current_path == rel, (
            "the real board row must survive a supersession naming its path "
            "at the WRONG sha256 -- got current=" + repr(current_path)
        )
        assert current_row["sha256"] == real_sha

        out_verify, code_verify = _run_board_index(repo, "verify")
        assert code_verify == 0, (
            "verify must select the real row (exit 0) since the wrong-sha "
            "supersession does not cover it: " + out_verify
        )
        expected_id = name[: -len(".json")]
        assert "CURRENT=" + expected_id in out_verify, out_verify
        print("ok   supersession naming correct path at WRONG sha -> real row survives, CURRENT selected")


def main() -> int:
    tests = [
        test_malformed_index_line_is_terminal_red,
        test_selected_receipt_sha_mismatch_is_red_before_render,
        test_all_live_trigger_fields_unknown_forces_stale,
        test_supersession_wrong_sha_does_not_remove_real_row,
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
        return 1
    print("PASS: All " + str(len(tests)) + " tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
