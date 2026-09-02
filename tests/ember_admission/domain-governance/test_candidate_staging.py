# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Candidate bytes remain private until validation and receipt completion."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ember_admission"))

from candidate import publish_staged_candidate, stage_candidate  # noqa: E402
from source_snapshot import SourceSnapshot  # noqa: E402


def test_candidate_is_invisible_until_explicit_final_publish(tmp_path: Path) -> None:
    output_root = tmp_path / "candidates"
    content = b"checkpoint"
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )
    }

    staging, staged_paths, destination = stage_candidate(
        output_root,
        "candidate-one",
        snapshots,
    )

    assert staging.name.startswith(".candidate-one.staging-")
    assert staged_paths["checkpoint"].read_bytes() == content
    assert destination == output_root / "candidate-one"
    assert not destination.exists()

    candidate, published_paths = publish_staged_candidate(
        staging,
        destination,
        snapshots,
    )

    assert candidate == destination
    assert published_paths["checkpoint"].read_bytes() == content


def test_partial_staging_write_leaves_no_candidate_or_staging_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import candidate as candidate_module

    output_root = tmp_path / "candidates"
    snapshots = {
        role: SourceSnapshot(
            role=role,
            relative_path=f"{role}.bin",
            sha256=hashlib.sha256(role.encode()).hexdigest(),
            content=role.encode(),
        )
        for role in ("checkpoint", "tensor_hashes")
    }
    original_write = candidate_module._write_snapshot
    writes = 0

    def fail_second_write(path: Path, content: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("synthetic partial write")
        original_write(path, content)

    monkeypatch.setattr(candidate_module, "_write_snapshot", fail_second_write)

    with pytest.raises(OSError, match="synthetic partial write"):
        stage_candidate(output_root, "candidate-one", snapshots)

    assert not (output_root / "candidate-one").exists()
    assert list(output_root.glob(".candidate-one.staging-*")) == []



def test_output_root_reparse_point_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    output_root = tmp_path / "linked-candidates"
    target.mkdir()
    if os.name == "nt":
        result = subprocess.run(
            [
                "cmd",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(output_root),
                str(target),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        output_root.symlink_to(target, target_is_directory=True)
    content = b"checkpoint"
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )
    }
    try:
        stage_candidate(output_root, "candidate-one", snapshots)
    except ValueError as exc:
        assert str(exc) == "output.reparse"
    else:
        raise AssertionError("reparse-point output root was accepted")
