# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sparse-capacity regressions for the owned checkpoint contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_contract import REPO_ROOT, VALIDATOR, _candidate_manifest, _write_json


TOTAL = 3_134_000_000
ACTIVE = 1_021_000_000
DOMAINS = ("vision", "audio", "reasoning", "tool")


def _make_sparse(tmp_path: Path) -> Path:
    source = _candidate_manifest(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    architecture = payload["architecture"]
    architecture.update(
        {
            "allocated_parameters": TOTAL,
            "unique_parameters": TOTAL,
            "trainable_parameters": TOTAL,
            "active_parameters": ACTIVE,
            "episode_trainable_parameters": ACTIVE,
            "served_parameters": TOTAL,
            "shared_core": True,
            "sparse_differentiated_capacity": True,
            "task_level_expert_routing": True,
            "asymmetric_expert_initialization": True,
            "active_expert_ids": ["reasoning"],
        }
    )
    _write_json(source, payload)
    return source


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "validate", str(path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_sparse_total_above_3b_with_one_active_expert_is_valid(tmp_path: Path) -> None:
    result = _run(_make_sparse(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_dense_shell_without_expert_banks_is_rejected(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    architecture = payload["architecture"]
    architecture["active_parameters"] = architecture["unique_parameters"]
    architecture["episode_trainable_parameters"] = architecture["unique_parameters"]
    architecture.pop("expert_banks")
    architecture.pop("active_expert_ids")
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    errors = json.loads(result.stdout)["errors"]
    assert any("expert_banks" in error for error in errors)
    assert any("active < unique" in error for error in errors)


def test_expert_genesis_hashes_must_be_distinct(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["architecture"]["expert_banks"][1]["genesis_sha256"] = (
        payload["architecture"]["expert_banks"][0]["genesis_sha256"]
    )
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    assert any("distinct" in error for error in json.loads(result.stdout)["errors"])


def test_only_one_expert_may_be_active_per_episode(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["architecture"]["active_expert_ids"] = ["vision", "audio"]
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    assert any("active_expert_ids" in error for error in json.loads(result.stdout)["errors"])


def test_expert_genesis_hash_must_bind_actual_bytes(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    expert = tmp_path / "checkpoint" / "reasoning-expert.bin"
    expert.write_bytes(b"reasoning expert genesis")
    payload = json.loads(path.read_text(encoding="utf-8"))
    bank = payload["architecture"]["expert_banks"][2]
    bank["path"] = str(expert.relative_to(tmp_path))
    bank["genesis_sha256"] = __import__("hashlib").sha256(expert.read_bytes()).hexdigest()
    _write_json(path, payload)
    expert.write_bytes(b"tampered reasoning expert")
    result = _run(path)
    assert result.returncode == 1
    assert any("content hash mismatch" in error for error in json.loads(result.stdout)["errors"])
