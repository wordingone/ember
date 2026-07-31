#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_custody_extraction_cures_test.py -- Tests for the issue #415 custody-probe
cures (72/72 cited_missing enumeration + four-bucket addendum + DESIGN RULING).

Extends the c_custody_pattern_citation_test.py (#410/#414) fixture pattern:
each test builds a minimal throwaway git repo, installs the current probe,
runs it, and asserts on its emitted line + written sidecar. One test per new
cure class, plus one asserting the cited_missing count is never capped.

Cures covered (see test_c_custody.py module docstring for the full mechanism):
  1. extraction fixes -- trailing backtick, `::field` suffix, wrap_joined
     consumption, bare-directory (isdir + tracked-populated)
  2. relocation resolution -- unique-basename match / non-unique stays missing
  3. schema-constant exemption
  4. documented_absent honor
  5. non-path citations -- curly-brace placeholder, known prose fragment
  7. annex attestation
  + cited_missing uncapped total
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
REPO_ROOT = HERE.parent.parent


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


def test_trailing_backtick_stripped_resolves_present():
    """A citation with a swallowed trailing markdown-fence backtick resolves
    once stripped -- the real file exists, so no offense of any kind."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "target.json").write_text(json.dumps({"payload": "ok"}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "note": "see `receipts/target.json` for details"
        }))
        _git_add_and_commit(repo, "backtick-swallowed citation, target present")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (backtick-stripped citation resolves), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        print("PASS: trailing-backtick citation resolves once stripped")


def test_double_colon_field_suffix_stripped_resolves_present():
    """A `::field.path` compound-reference suffix is stripped before the
    existence check -- the base file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "target.json").write_text(json.dumps({"payload": "ok"}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "citation": "receipts/target.json::rows.gen"
        }))
        _git_add_and_commit(repo, "::field-suffix citation, base target present")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (::-suffix stripped, base resolves), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        print("PASS: ::field-suffix citation resolves once stripped to its base path")


def test_location_suffixes_strip_to_present_receipt():
    """Markdown line anchors are source locations, not filename bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "target.json").write_text(json.dumps({"payload": "ok"}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "range": "receipts/target.json:113-120",
            "lines": "receipts/target.json:84,85",
            "punctuation": "receipts/target.json:",
        }))
        _git_add_and_commit(repo, "line-location citations, target present")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (line suffixes stripped), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        print("PASS: numeric line/range/list suffixes resolve to the tracked base receipt")


def test_nonnumeric_colon_suffix_stays_missing():
    """Only closed numeric source locations may be stripped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "target.json").write_text(json.dumps({"payload": "ok"}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "citation": "receipts/target.json:foreign-field"
        }))
        _git_add_and_commit(repo, "nonnumeric colon suffix remains literal")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (nonnumeric suffix is not stripped), got: {output}"
        sidecar = _sidecar_data(repo)
        assert any("target.json:foreign-field" in c for c in sidecar["offenders"]["cited_missing"])
        print("PASS: nonnumeric colon suffix remains a concrete missing citation")


def test_wrap_joined_record_consumes_joined_not_ref():
    """A citation-check-shaped wrap_joined record ({"doc","ref","joined","line"})
    is consumed via its reconstructed `joined` value; the truncated `ref`
    fragment is never independently re-ingested as its own missing citation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "frag-full-20260101T000000Z.json").write_text(json.dumps({"payload": "ok"}))
        (repo / "receipts" / "citation-check-fixture.json").write_text(json.dumps({
            "wrap_joined": [{
                "doc": "docs/spec/example-v1.md",
                "ref": "receipts/frag-",
                "joined": "receipts/frag-full-20260101T000000Z.json",
                "line": 42,
            }]
        }))
        _git_add_and_commit(repo, "wrap_joined record, joined target present")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (wrap_joined consumed via joined), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        # the truncated fragment itself must never appear anywhere as an offense
        flat = json.dumps(sidecar["offenders"])
        assert "receipts/frag-\"" not in flat and '"receipts/frag-"' not in flat
        print("PASS: wrap_joined record resolves via its joined value, ref fragment never re-ingested")


def test_wrap_joined_still_reds_when_joined_target_absent():
    """The wrap_joined cure fixes the STRING RECONSTRUCTION problem only --
    it never fabricates existence. If the reconstructed `joined` path is
    genuinely absent, it still reports cited_missing (fail-closed preserved)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citation-check-fixture.json").write_text(json.dumps({
            "wrap_joined": [{
                "doc": "docs/spec/example-v1.md",
                "ref": "receipts/gone-",
                "joined": "receipts/gone-truly-20260101T000000Z.json",
                "line": 7,
            }]
        }))
        _git_add_and_commit(repo, "wrap_joined record, joined target absent")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (joined target genuinely absent), got: {output}"
        sidecar = _sidecar_data(repo)
        assert any("gone-truly-20260101T000000Z.json" in c for c in sidecar["offenders"]["cited_missing"])
        print("PASS: wrap_joined stays fail-closed when the reconstructed target is genuinely absent")


def test_documented_absent_record_honored():
    """A citation-check-shaped documented_absent record ({"doc","ref","marker",
    "line"}) is honored: the ref classifies documented_absent, not cited_missing,
    when the SAME path is also independently cited elsewhere in the corpus."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citation-check-fixture.json").write_text(json.dumps({
            "documented_absent": [{
                "doc": "docs/spec/example-v1.md",
                "ref": "receipts/gone-honestly-20260101T000000Z.json",
                "marker": "verified absent",
                "line": 12,
            }]
        }))
        (repo / "receipts" / "other-citing-receipt.json").write_text(json.dumps({
            "cross_ref": "receipts/gone-honestly-20260101T000000Z.json"
        }))
        _git_add_and_commit(repo, "documented_absent record + independent citation of the same path")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (documented_absent honored), got: {output}"
        assert "documented_absent=1" in output, f"Expected documented_absent=1, got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert "receipts/gone-honestly-20260101T000000Z.json" in sidecar["offenders"]["documented_absent"]
        print("PASS: documented_absent record honored, ref never counted cited_missing")


def test_bare_directory_tracked_populated_resolves():
    """A bare, no-extension citation naming a real, git-tracked-populated
    directory classifies pattern_citation (directory reference), not a
    missing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "some-dir").mkdir()
        (repo / "receipts" / "some-dir" / "inner.json").write_text(json.dumps({"x": 1}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "dir_ref": "receipts/some-dir"
        }))
        _git_add_and_commit(repo, "bare directory citation, tracked and populated")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (bare dir resolves via isdir+tracked), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert any("receipts/some-dir" in p for p in sidecar["offenders"]["pattern_citation"])
        print("PASS: bare tracked-populated directory citation resolves as pattern_citation")


def test_relocation_unique_basename_resolves():
    """A cited path that no longer exists at its cited location, but whose
    basename matches EXACTLY ONE tracked receipts/ file elsewhere, classifies
    relocated (sidecar records old->new)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "new-location").mkdir()
        (repo / "receipts" / "new-location" / "target-20260101T000000Z.json").write_text(json.dumps({"x": 1}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "citation": "receipts/old-location/target-20260101T000000Z.json"
        }))
        _git_add_and_commit(repo, "relocated file, unique basename match")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (unique-basename relocation resolves), got: {output}"
        assert "relocated=1" in output, f"Expected relocated=1, got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert sidecar["offenders"]["relocated"] == [{
            "old": "receipts/old-location/target-20260101T000000Z.json",
            "new": "receipts/new-location/target-20260101T000000Z.json",
        }]
        print("PASS: unique-basename relocation resolves and is recorded old->new")


def test_relocation_non_unique_basename_stays_missing():
    """A missing citation whose basename matches MULTIPLE tracked files is
    never guessed at -- it stays cited_missing (fail-closed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "dir-a").mkdir()
        (repo / "receipts" / "dir-b").mkdir()
        (repo / "receipts" / "dir-a" / "ambiguous.json").write_text(json.dumps({"x": 1}))
        (repo / "receipts" / "dir-b" / "ambiguous.json").write_text(json.dumps({"x": 2}))
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "citation": "receipts/dir-c/ambiguous.json"
        }))
        _git_add_and_commit(repo, "ambiguous basename, two real tracked candidates")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (non-unique basename, no guessing), got: {output}"
        assert "relocated=0" in output, f"Expected relocated=0 (no guess made), got: {output}"
        sidecar = _sidecar_data(repo)
        assert any("dir-c/ambiguous.json" in c for c in sidecar["offenders"]["cited_missing"])
        assert sidecar["offenders"]["relocated"] == []
        print("PASS: non-unique basename match stays cited_missing, never guessed")


def test_annex_attested_classifies_when_sha256_recorded():
    """A genuinely-missing citation whose sha256 was recorded by a historical
    spend-annex snapshot classifies annex_attested (weaker-but-honest
    evidence), not a bare unverified cited_missing claim."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        annex_dir = repo / "receipts" / "spend-annex"
        annex_dir.mkdir()
        (annex_dir / "spend-annex-20260101T000000Z.json").write_text(json.dumps({
            "rows": [{
                "path": "receipts/since-deleted-20260101T000000Z.json",
                "sha256": "deadbeef" * 8,
                "evidence_class": "script_scanned_clean",
            }]
        }))
        _git_add_and_commit(repo, "spend-annex snapshot citing a now-deleted receipt")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (annex-attested), got: {output}"
        assert "annex_attested=1" in output, f"Expected annex_attested=1, got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        hit = sidecar["offenders"]["annex_attested"][0]
        assert hit["path"] == "receipts/since-deleted-20260101T000000Z.json"
        assert hit["sha256"] == "deadbeef" * 8
        assert "spend-annex-20260101T000000Z.json" in hit["annex_source"]
        print("PASS: annex-attested citation classifies via historical spend-annex sha256")


def test_curly_brace_placeholder_is_pattern():
    """A `{ts}`-style curly-brace template placeholder classifies
    pattern_citation, same shape as the existing `<named>` case."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "template": "receipts/b-run-designation-{ts}.json"
        }))
        _git_add_and_commit(repo, "curly-brace template placeholder")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (curly-brace placeholder is pattern), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert any("b-run-designation-{ts}.json" in p for p in sidecar["offenders"]["pattern_citation"])
        print("PASS: curly-brace placeholder classifies pattern_citation")


def test_known_prose_fragment_is_pattern():
    """The one evidence-backed known prose fragment ('the existing
    receipts/ledger/view mechanism') classifies pattern_citation even though
    every path segment starts with a letter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "fix": "Specify ground truth source: either (a) a locally pinned "
                   "file with sha256 in the receipt, or (b) the existing "
                   "receipts/ledger/view mechanism (already local). Prohibit "
                   "runtime cloud fetch."
        }))
        _git_add_and_commit(repo, "known prose fragment, real receipt text")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (known prose fragment is pattern), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert any(p.endswith("receipts/ledger/view") for p in sidecar["offenders"]["pattern_citation"])
        print("PASS: known prose fragment classifies pattern_citation")


def test_known_custody_prose_fragment_is_pattern():
    """A historical statement about receipts/custody corrections is prose."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "reason": "Git log shows receipts/custody corrections merged to master."
        }))
        _git_add_and_commit(repo, "known custody prose fragment")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (custody prose is pattern), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        assert any(p.endswith("receipts/custody") for p in sidecar["offenders"]["pattern_citation"])
        print("PASS: receipts/custody prose fragment classifies pattern_citation")


def test_similar_custody_filename_stays_missing():
    """The prose exception must not hide a similarly named receipt file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "citing.json").write_text(json.dumps({
            "citation": "receipts/custody-proof.json"
        }))
        _git_add_and_commit(repo, "similar custody receipt genuinely absent")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (similar filename absent), got: {output}"
        sidecar = _sidecar_data(repo)
        assert any("receipts/custody-proof.json" in c for c in sidecar["offenders"]["cited_missing"])
        print("PASS: similar custody filename remains fail-closed")


def test_schema_constant_exempted():
    """A citation exactly matching a documented schema-example constant
    (the cycle-*/statecommit-* convention) classifies pattern_citation, not
    cited_missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        (repo / "receipts" / "cycle-20260617T000000Z-0001.json").write_text(json.dumps({
            "receipts": {
                "benchmark": "receipts/benchmark/cycle-20260617T000000Z-0001.json",
                "sandbox": "receipts/sandbox/cycle-20260617T000000Z-0001.json",
            }
        }))
        _git_add_and_commit(repo, "schema-constant example paths, real repo shape")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN (schema constants exempted), got: {output}"
        sidecar = _sidecar_data(repo)
        assert sidecar["offenders"]["cited_missing"] == [], sidecar["offenders"]["cited_missing"]
        pattern = sidecar["offenders"]["pattern_citation"]
        assert any("schema-constant" in p and "benchmark" in p for p in pattern)
        assert any("schema-constant" in p and "sandbox" in p for p in pattern)
        print("PASS: schema-constant citations classify pattern_citation, tagged schema-constant")


def test_cited_missing_uncapped_total():
    """cited_missing prints the TRUE uncapped total -- more than 10 genuinely
    missing citations must all be counted and all be listed, never truncated
    to the old [:10] cap."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _new_repo(tmpdir)
        n = 15
        citing = {f"ref_{i}": f"receipts/genuinely-missing-{i:02d}.json" for i in range(n)}
        (repo / "receipts" / "citing.json").write_text(json.dumps(citing))
        _git_add_and_commit(repo, f"{n} genuinely missing concrete citations")
        _install_probe(repo)

        output, _ = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED, got: {output}"
        assert f"cited_missing={n}" in output, f"Expected cited_missing={n} (uncapped), got: {output}"
        sidecar = _sidecar_data(repo)
        assert len(sidecar["offenders"]["cited_missing"]) == n, (
            f"Expected {n} cited_missing entries in sidecar (uncapped), "
            f"got {len(sidecar['offenders']['cited_missing'])}"
        )
        for i in range(n):
            assert any(f"genuinely-missing-{i:02d}.json" in c for c in sidecar["offenders"]["cited_missing"])
        print(f"PASS: {n} genuinely-missing citations all counted and listed, uncapped")


if __name__ == "__main__":
    tests = [
        test_trailing_backtick_stripped_resolves_present,
        test_double_colon_field_suffix_stripped_resolves_present,
        test_location_suffixes_strip_to_present_receipt,
        test_nonnumeric_colon_suffix_stays_missing,
        test_wrap_joined_record_consumes_joined_not_ref,
        test_wrap_joined_still_reds_when_joined_target_absent,
        test_documented_absent_record_honored,
        test_bare_directory_tracked_populated_resolves,
        test_relocation_unique_basename_resolves,
        test_relocation_non_unique_basename_stays_missing,
        test_annex_attested_classifies_when_sha256_recorded,
        test_curly_brace_placeholder_is_pattern,
        test_known_prose_fragment_is_pattern,
        test_known_custody_prose_fragment_is_pattern,
        test_similar_custody_filename_stays_missing,
        test_schema_constant_exempted,
        test_cited_missing_uncapped_total,
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
