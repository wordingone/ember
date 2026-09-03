#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_custody_twin_resolution_test.py -- Regression fixtures for issue #535
(_resolve_redaction_twin() / cited-path redaction-rename citation drift).

Evidence: several receipts were renamed with a `-redacted-edition` suffix at
landing time (repo-guard's local-path/name scrub applied post-hoc), e.g.
`receipts/ceff-RESOLVED-20260703T124623Z-import-edition.json` ->
`...-import-edition-redacted-edition.json`. Downstream citers still cite the
pre-rename filename, so the pre-cure probe reported these as `cited_missing`
even though the (redacted) content is present and tracked at HEAD. The cure
adds a same-directory, same-stem, fixed-suffix twin check ahead of the
relocation/annex cures in the existing ladder.

Follows the c_custody_dictkey_citations_test.py (#437) fixture pattern: each
test builds a minimal throwaway git repo, installs the current probe, runs
it, and asserts on its emitted line + written sidecar.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))


def _run_custody_probe(repo_root: Path) -> tuple[str, int]:
    """Run test_c_custody.py, return (stdout, exit_code)."""
    script = repo_root / "scripts" / "ember_totality" / "test_c_custody.py"
    if not script.exists():
        return f"Script {script} not found", 1

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "EMBER_TOTALITY_ROOT": str(repo_root),
            "PYTHONPATH": str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
    )
    return result.stdout.strip(), result.returncode


def _init_git_repo(repo_root: Path):
    subprocess.run(["git", "init"], cwd=str(repo_root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_root), capture_output=True, check=True)


def _git_add_and_commit(repo_root: Path, message: str):
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), capture_output=True, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _install_probe(repo_root: Path):
    scripts_dir = repo_root / "scripts" / "ember_totality"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    probe_src = REPO_ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
    probe_dst = scripts_dir / "test_c_custody.py"
    shutil.copy(probe_src, probe_dst)


def _sidecar_data(repo: Path):
    sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
    sidecar_files = sorted(sidecar_dir.glob("custody-*.json"))
    assert sidecar_files, "No custody sidecar written"
    return json.loads(sidecar_files[-1].read_text())


def _new_repo(tmpdir: str) -> Path:
    repo = Path(tmpdir) / "test_repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "receipts").mkdir()
    return repo


def test_cited_missing_with_tracked_redacted_twin_resolves_green():
    """A cited path X.json that is absent, but whose same-directory
    X-redacted-edition.json twin exists and is tracked, resolves
    `resolved_redacted` -- not `cited_missing` (issue #535 acceptance)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "target-redacted-edition.json").write_text(
            json.dumps({"redaction_note": "local paths stripped"})
        )
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "ref": "receipts/target.json",
        }))
        _git_add_and_commit(repo, "citation of a redaction-renamed twin")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (twin resolves), got: {output}"
        assert "resolved_redacted=1" in output, f"Expected resolved_redacted=1, got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        twins = sidecar["offenders"]["resolved_redacted"]
        assert any(
            t["old"] == "receipts/target.json" and t["new"] == "receipts/target-redacted-edition.json"
            for t in twins
        ), twins
        print("PASS: cited path with a tracked redacted-edition twin resolves GREEN, not cited_missing")


def test_cited_missing_with_no_twin_still_counts():
    """Negative control (issue #535 AC item 3): a cited-missing path with NO
    redacted-edition twin anywhere still counts cited_missing unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "ref": "receipts/genuinely-missing-20260101T000000Z.json",
        }))
        _git_add_and_commit(repo, "citation of a path with no twin at all")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (no twin, stays missing), got: {output}"
        assert "cited_missing=1" in output, f"Expected cited_missing=1, got: {output}"
        sidecar = _sidecar_data(repo)
        assert any(
            "genuinely-missing-20260101T000000Z.json" in c for c in sidecar["offenders"]["cited_missing"]
        ), sidecar["offenders"]["cited_missing"]
        assert sidecar["offenders"]["resolved_redacted"] == [], sidecar["offenders"]["resolved_redacted"]
        print("PASS: cited path with no twin at all still counts cited_missing, unresolved")


def test_untracked_redacted_twin_does_not_resolve():
    """A same-name -redacted-edition file that exists on disk but is NOT
    git-tracked must NOT resolve the citation -- the rule requires the twin
    to be tracked at HEAD, matching #535's frozen AC exactly (untracked
    content is not yet custody-safe evidence). Its mtime is backdated below
    the repo's last-landing time so it classifies as a plain untracked
    violation rather than the unrelated pending_landing age-window bucket
    (test_c_custody_sidecar_agewindow_test.py already covers that bucket)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "ref": "receipts/target2.json",
        }))
        _git_add_and_commit(repo, "citation with only an untracked twin present")

        twin_path = repo / "receipts" / "target2-redacted-edition.json"
        twin_path.write_text(json.dumps({"redaction_note": "local paths stripped"}))
        old_time = 1577836800  # 2020-01-01T00:00:00Z -- well before the commit above
        os.utime(twin_path, (old_time, old_time))

        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (untracked twin doesn't count), got: {output}"
        sidecar = _sidecar_data(repo)
        assert any(
            "target2.json" in c and "target2-redacted-edition" not in c
            for c in sidecar["offenders"]["cited_missing"]
        ), sidecar["offenders"]["cited_missing"]
        assert sidecar["offenders"]["resolved_redacted"] == [], sidecar["offenders"]["resolved_redacted"]
        assert any("target2-redacted-edition.json" in u for u in sidecar["offenders"]["untracked"]), sidecar["offenders"]["untracked"]
        print("PASS: an untracked redacted-edition twin does not resolve the citation")


def test_twin_in_different_directory_does_not_resolve():
    """The twin-resolution rule is same-DIRECTORY only (distinct from cure 2
    relocation, which is basename-uniqueness across the whole tree) -- a
    same-stem redacted-edition file in a DIFFERENT directory must not
    resolve the citation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "sub").mkdir()
        (repo / "receipts" / "sub" / "target3-redacted-edition.json").write_text(
            json.dumps({"redaction_note": "local paths stripped"})
        )
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "ref": "receipts/target3.json",
        }))
        _git_add_and_commit(repo, "same-stem twin in a different directory")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (twin is out-of-directory), got: {output}"
        sidecar = _sidecar_data(repo)
        assert any("target3.json" in c and "sub/" not in c for c in sidecar["offenders"]["cited_missing"]), sidecar["offenders"]["cited_missing"]
        assert sidecar["offenders"]["resolved_redacted"] == [], sidecar["offenders"]["resolved_redacted"]
        print("PASS: a same-stem twin in a different directory does not resolve the citation")


if __name__ == "__main__":
    tests = [
        test_cited_missing_with_tracked_redacted_twin_resolves_green,
        test_cited_missing_with_no_twin_still_counts,
        test_untracked_redacted_twin_does_not_resolve,
        test_twin_in_different_directory_does_not_resolve,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
            print(f"FAIL: {t.__name__}: {e}")
    print()
    if failures:
        print(f"FAIL: {len(failures)}/{len(tests)} tests failed")
        sys.exit(1)
    print(f"PASS: All {len(tests)} tests passed")
