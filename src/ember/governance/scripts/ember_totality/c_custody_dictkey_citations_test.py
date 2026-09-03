#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_custody_dictkey_citations_test.py -- Regression fixtures for issue #437
(_extract_citations() dict-KEY blind spot).

Evidence: three publication-gate-*.json receipts (landed 2026-07-05) cited a
missing receipt path as a dict KEY ({"receipts/cgrow-superseded/...json":
true}) -- the pre-fix probe scanned dict VALUES only and never saw it. The
cure extends _extract_citations() to also scan dict keys through the same
`receipts/` substring match + _clean_citation() normalization used for
values, so key-form and value-form citations are classified identically.

Follows the c_custody_extraction_cures_test.py (#415) fixture pattern: each
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


def test_dictkey_citation_of_missing_path_is_reported():
    """A missing receipts/ path cited ONLY as a dict KEY (existence-map shape,
    the #437 evidence shape: {"receipts/...json": true}) must be counted
    cited_missing -- the pre-fix probe was blind to this and reported GREEN."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "receipts/key-only-missing-20260101T000000Z.json": True
        }))
        _git_add_and_commit(repo, "dict-key-only citation of a missing path")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (key-form citation of missing path detected), got: {output}"
        assert "cited_missing=1" in output, f"Expected cited_missing=1, got: {output}"
        sidecar = _sidecar_data(repo)
        assert any("key-only-missing-20260101T000000Z.json" in c for c in sidecar["offenders"]["cited_missing"])
        print("PASS: dict-key-only citation of a missing path is detected")


def test_dictkey_and_value_citations_of_missing_paths_both_reported():
    """Issue #437 acceptance: a receipt citing one missing path as a dict KEY
    and a DIFFERENT missing path as a string VALUE must report BOTH in the
    same run -- neither form suppresses the other."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "receipts/key-form-missing-20260101T000000Z.json": True,
            "value_ref": "receipts/value-form-missing-20260101T000000Z.json",
        }))
        _git_add_and_commit(repo, "one key-form + one value-form missing citation")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED, got: {output}"
        assert "cited_missing=2" in output, f"Expected cited_missing=2 (both forms), got: {output}"
        sidecar = _sidecar_data(repo)
        missing = sidecar["offenders"]["cited_missing"]
        assert any("key-form-missing-20260101T000000Z.json" in c for c in missing), missing
        assert any("value-form-missing-20260101T000000Z.json" in c for c in missing), missing
        print("PASS: key-form and value-form missing citations both reported in the same run")


def test_dictkey_citation_of_present_path_resolves_green():
    """A dict-key citation of a path that DOES exist resolves clean -- the
    key-scan must not manufacture a false positive on a present file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "target.json").write_text(json.dumps({"payload": "ok"}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "receipts/target.json": True
        }))
        _git_add_and_commit(repo, "dict-key citation, target present")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (key-cited target present), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        print("PASS: dict-key citation of a present path resolves GREEN, no false positive")


def test_dictkey_schema_constant_exempted_same_as_value_form():
    """The #415 schema-constant false-positive guard applies identically when
    the constant string appears as a dict KEY, not just as a value --
    classifies pattern_citation, never cited_missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "cycle-20260617T000000Z-0001.json").write_text(json.dumps({
            "receipts/benchmark/cycle-20260617T000000Z-0001.json": "benchmark-slot"
        }))
        _git_add_and_commit(repo, "schema-constant path used as a dict key")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (schema-constant key exempted), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert any("schema-constant" in p and "benchmark" in p for p in sidecar["offenders"]["pattern_citation"])
        print("PASS: schema-constant key-form citation classifies pattern_citation, same as value-form")


def test_dictkey_curly_brace_placeholder_is_pattern_same_as_value_form():
    """The #415 curly-brace-placeholder guard applies identically to a dict
    KEY -- a `{ts}`-style template used as a key classifies pattern_citation,
    not cited_missing (no regression from the key-scan addition)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "receipts/b-run-designation-{ts}.json": "template-slot"
        }))
        _git_add_and_commit(repo, "curly-brace template placeholder used as a dict key")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (curly-brace key is pattern), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert any("b-run-designation-{ts}.json" in p for p in sidecar["offenders"]["pattern_citation"])
        print("PASS: curly-brace placeholder key-form classifies pattern_citation, same as value-form")


if __name__ == "__main__":
    tests = [
        test_dictkey_citation_of_missing_path_is_reported,
        test_dictkey_and_value_citations_of_missing_paths_both_reported,
        test_dictkey_citation_of_present_path_resolves_green,
        test_dictkey_schema_constant_exempted_same_as_value_form,
        test_dictkey_curly_brace_placeholder_is_pattern_same_as_value_form,
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
