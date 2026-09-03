#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_custody_pattern_citation_test.py -- Tests for citation-extraction pattern
classification (issue #410).

Verifies:
  (a) each of the 10 real-world false-positive strings (from the #409 sidecar,
      scripts/ember_totality/receipts-custody/custody-20260708T054456Z.json)
      classifies as pattern_citation, never cited_missing -> overall GREEN
  (b) a concrete missing citation still causes RED (fail-closed unchanged)
  (c) a concrete present citation causes neither cited_missing nor
      pattern_citation
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
    """Initialize a minimal git repo."""
    subprocess.run(["git", "init"], cwd=str(repo_root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_root), capture_output=True, check=True)


def _git_add_and_commit(repo_root: Path, message: str):
    """Stage all changes and commit."""
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


# The 10 real-world false-positive strings enumerated in the #409 sidecar
# (scripts/ember_totality/receipts-custody/custody-20260708T054456Z.json),
# each embedded in prose exactly as it occurs in the live receipts that
# produced them (grep-verified against receipts/*.json in the main tree).
_PATTERN_PROSE = {
    "note_bare_dir": "everything must be tracked under receipts/, no exceptions",
    "note_recursive_glob": "wildcard sweep matches receipts/**/*e2b*.json entries",
    "note_star_glob": "single-file glob receipts/*.json for staging",
    "note_plus_star": "alt form receipts/+*.json accepted here",
    "note_prose_style": "this is a tensor artifact index, not a receipts/-style gate receipt",
    "note_regex_single_bs": "regex receipts/.*\\.json'; emitted=ok",
    "note_regex_double_bs": "regex receipts/.*\\\\.json'; emitted=ok",
    "note_placeholder": "template path receipts/<named>.json for placeholders",
    "note_paren_quarantine": "Define quarantine path (e.g. receipts/_quarantine/) and note",
    "note_paren_sandbox": "Name the absolute path (e.g. receipts/_sandbox/STATE-test.md) in the ep",
}

# Expected classified citation string (post rstrip(",;.")) for each prose field above.
_EXPECTED_PATTERNS = [
    "receipts/",
    "receipts/**/*e2b*.json",
    "receipts/*.json",
    "receipts/+*.json",
    "receipts/-style",
    "receipts/.*\\.json",
    "receipts/.*\\\\.json",
    "receipts/<named>.json",
    "receipts/_quarantine/)",
    "receipts/_sandbox/STATE-test.md)",
]


def test_pattern_citations_classify_and_stay_green():
    """All 10 known false-positive shapes classify as pattern_citation, never
    cited_missing, and the probe is GREEN overall (no genuine missing citations)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        _init_git_repo(repo)

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()
        citing_file = receipts_dir / "citing.json"
        citing_file.write_text(json.dumps(_PATTERN_PROSE, indent=2))
        _git_add_and_commit(repo, "Add receipt citing only pattern-shaped strings")

        _install_probe(repo)

        output, exit_code = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (patterns excluded), got: {output}"
        assert f"pattern={len(_EXPECTED_PATTERNS)}" in output, \
            f"Expected pattern={len(_EXPECTED_PATTERNS)} in emit line, got: {output}"

        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        sidecar_files = sorted(sidecar_dir.glob("custody-*.json"))
        assert sidecar_files, "No custody sidecar written"
        sidecar_data = json.loads(sidecar_files[-1].read_text())

        assert sidecar_data["offenders"]["cited_missing"] == [], \
            f"Expected zero cited_missing, got: {sidecar_data['offenders']['cited_missing']}"

        pattern_citation = sidecar_data["offenders"]["pattern_citation"]
        assert len(pattern_citation) == len(_EXPECTED_PATTERNS), \
            f"Expected {len(_EXPECTED_PATTERNS)} pattern_citation entries, got {len(pattern_citation)}: {pattern_citation}"
        for expected in _EXPECTED_PATTERNS:
            assert any(expected == p[len("PATTERN: "):] for p in pattern_citation), \
                f"Expected pattern citation {expected!r} not found in {pattern_citation}"

        print(f"PASS: all {len(_EXPECTED_PATTERNS)} false-positive shapes classified pattern_citation, GREEN overall")


def test_concrete_missing_citation_still_reds():
    """A concrete (non-pattern) cited path that does not exist must still fail
    (fail-closed unchanged, issue #410 acceptance #3)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        _init_git_repo(repo)

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()
        citing_file = receipts_dir / "citing.json"
        citing_file.write_text(json.dumps({
            "citation": "receipts/definitely-missing-fixture-9910.json"
        }))
        _git_add_and_commit(repo, "Add receipt citing a genuinely missing concrete path")

        _install_probe(repo)

        output, exit_code = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (concrete cited_missing), got: {output}"
        assert "cited_missing=1" in output, f"Expected cited_missing=1, got: {output}"
        assert "pattern=0" in output, f"Expected pattern=0 (no pattern shapes here), got: {output}"

        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        sidecar_files = sorted(sidecar_dir.glob("custody-*.json"))
        sidecar_data = json.loads(sidecar_files[-1].read_text())

        cited_missing = sidecar_data["offenders"]["cited_missing"]
        assert any("definitely-missing-fixture-9910.json" in c for c in cited_missing), \
            f"Expected missing fixture in cited_missing, got: {cited_missing}"
        assert sidecar_data["offenders"]["pattern_citation"] == [], \
            f"Expected zero pattern_citation, got: {sidecar_data['offenders']['pattern_citation']}"

        print(f"PASS: concrete missing citation still REDs: {cited_missing}")


def test_concrete_present_citation_passes():
    """A concrete cited path that exists on disk causes neither cited_missing
    nor pattern_citation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()
        _init_git_repo(repo)

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()

        target_file = receipts_dir / "present-target.json"
        target_file.write_text(json.dumps({"payload": "ok"}))

        citing_file = receipts_dir / "citing.json"
        citing_file.write_text(json.dumps({
            "citation": "receipts/present-target.json"
        }))
        _git_add_and_commit(repo, "Add receipt citing a present concrete path")

        _install_probe(repo)

        output, exit_code = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (citation exists), got: {output}"
        assert "pattern=0" in output, f"Expected pattern=0, got: {output}"

        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        sidecar_files = sorted(sidecar_dir.glob("custody-*.json"))
        sidecar_data = json.loads(sidecar_files[-1].read_text())

        assert sidecar_data["offenders"]["cited_missing"] == []
        assert sidecar_data["offenders"]["pattern_citation"] == []

        print("PASS: concrete present citation causes no offender entries")


if __name__ == "__main__":
    test_pattern_citations_classify_and_stay_green()
    test_concrete_missing_citation_still_reds()
    test_concrete_present_citation_passes()
    print("\nPASS: All tests passed")
