# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-only custody-census contract for issue #1450."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import scratch_custody


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    scratch = root / "scratch"
    (scratch / "run-a").mkdir(parents=True)
    (scratch / "run-a" / "result.bin").write_bytes(b"abc")
    (scratch / "run-b").mkdir()
    (scratch / "run-b" / "notes.txt").write_text("owned\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Issue 1450 Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "scratch"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def test_census_is_closed_deterministic_and_path_free(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    assert set(manifest) == {
        "schema_version", "label", "target", "source_commit", "source_status_sha256",
        "policy", "entries", "top_level", "summary", "manifest_sha256",
    }
    assert manifest["schema_version"] == scratch_custody.SCHEMA_VERSION
    assert manifest["entries"][0]["path"] == "run-a/result.bin"
    assert manifest["summary"] == {"files": 2, "bytes": 10}
    assert manifest["manifest_sha256"] == scratch_custody.manifest_sha256(manifest)
    assert not any(str(root) in json.dumps(manifest) for _ in [0])
    assert scratch_custody.validate_manifest(root, manifest) == manifest


def test_census_refuses_cap_before_manifest(tmp_path: Path):
    root = _fixture(tmp_path)
    with pytest.raises(scratch_custody.CensusError, match="byte budget"):
        scratch_custody.build_manifest(root, label="issue-1450", max_bytes=8)


def test_guard_refuses_file_drift_and_manifest_tamper(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    (root / "scratch" / "run-a" / "result.bin").write_bytes(b"tampered")
    with pytest.raises(scratch_custody.CensusError, match="entry bytes|manifest drift"):
        scratch_custody.validate_manifest(root, manifest)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["entries"][0]["sha256"] = "0" * 64
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="entry bytes"):
        scratch_custody.validate_manifest(root, manifest)


def test_guard_rejects_unknown_or_aliased_inventory_rows(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["unexpected"] = True
    with pytest.raises(scratch_custody.CensusError, match="closed"):
        scratch_custody.validate_manifest(root, manifest)
    manifest = scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)
    manifest["entries"][0]["path"] = "../outside"
    manifest["manifest_sha256"] = scratch_custody.manifest_sha256(manifest)
    with pytest.raises(scratch_custody.CensusError, match="path"):
        scratch_custody.validate_manifest(root, manifest)


def test_guard_rejects_symlinked_entry(tmp_path: Path):
    root = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "scratch" / "run-a" / "escape").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(scratch_custody.CensusError, match="reparse|symlink"):
        scratch_custody.build_manifest(root, label="issue-1450", max_bytes=1024)


def test_cli_guard_has_no_success_on_tampered_root(tmp_path: Path):
    root = _fixture(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    assert scratch_custody.write_manifest(root, manifest_path, label="issue-1450", max_bytes=1024) == manifest_path
    (root / "scratch" / "run-b" / "notes.txt").write_text("drift\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" / "scratch_custody.py"),
            "guard",
            "--root",
            str(root),
            "--manifest",
            str(manifest_path),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "entry bytes" in result.stderr or "manifest drift" in result.stderr
