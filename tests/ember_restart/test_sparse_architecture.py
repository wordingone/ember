# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sparse-capacity regressions for the owned checkpoint contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_contract import (
    REPO_ROOT,
    VALIDATOR,
    _candidate_manifest,
    _register_checkpoint_custody,
    _write_json,
)


TOTAL = 3_839_161_856
ACTIVE = 1_725_232_640
SHARED_ACTIVE = 1_020_589_568
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


def _run(path: Path, *, custody_db: Path | None = None) -> subprocess.CompletedProcess[str]:
    argv = [
        sys.executable,
        str(VALIDATOR),
        "validate",
        str(path),
        "--trusted-verifier-registry",
        str(path.parent / "trusted-verifiers.json"),
    ]
    if custody_db is not None:
        argv += ["--custody-db", str(custody_db)]
    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_sparse_total_above_3b_with_one_active_expert_is_valid(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    custody_db = _register_checkpoint_custody(path.parent)
    result = _run(path, custody_db=custody_db)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_semantic_route_uses_the_always_active_nonlinear_ffn(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    architecture = payload["architecture"]
    architecture["active_expert_ids"] = ["shared"]
    architecture["active_parameters"] = SHARED_ACTIVE
    architecture["episode_trainable_parameters"] = SHARED_ACTIVE
    receipt_ref = architecture["parameter_receipt"]
    receipt_path = tmp_path / receipt_ref["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["active_expert_ids"] = ["shared"]
    receipt["active_parameters"] = SHARED_ACTIVE
    receipt["episode_trainable_parameters"] = SHARED_ACTIVE
    receipt_ref["sha256"] = _write_json(receipt_path, receipt)
    _write_json(path, payload)
    custody_db = _register_checkpoint_custody(path.parent)
    result = _run(path, custody_db=custody_db)
    assert result.returncode == 0, result.stdout + result.stderr


def test_v2_config_requires_the_shared_text_ffn_declaration(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    model_config_ref = payload["architecture"]["model_config"]
    model_config_path = tmp_path / model_config_ref["path"]
    model_config = json.loads(model_config_path.read_text(encoding="utf-8"))
    model_config["model"]["expert_routing"].pop("shared_text_ffn")
    _write_json(model_config_path, model_config)
    result = _run(path)
    assert result.returncode == 1
    assert any("expert routing mismatch" in error for error in json.loads(result.stdout)["errors"])


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


def test_parameter_counts_require_checkpoint_bound_counter_receipt(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["architecture"].pop("parameter_receipt", None)
    payload["architecture"].pop("parameter_counter", None)
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    assert any("parameter_receipt" in error for error in json.loads(result.stdout)["errors"])

def test_parameter_receipt_rehashed_count_mismatch_is_rejected(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    receipt_ref = payload["architecture"]["parameter_receipt"]
    receipt_path = tmp_path / receipt_ref["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["unique_parameters"] += 1
    receipt_ref["sha256"] = _write_json(receipt_path, receipt)
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    assert any(
        "unique_parameters mismatch" in error
        for error in json.loads(result.stdout)["errors"]
    )


def test_parameter_counter_bytes_are_content_addressed(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    counter_path = tmp_path / payload["architecture"]["parameter_counter"]["path"]
    counter_path.write_text("# tampered counter\n", encoding="utf-8")
    result = _run(path)
    assert result.returncode == 1
    assert any(
        "architecture.parameter_counter.sha256: content hash mismatch" in error
        for error in json.loads(result.stdout)["errors"]
    )

def test_self_consistent_fabricated_counts_fail_config_recomputation(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    architecture = payload["architecture"]
    receipt_ref = architecture["parameter_receipt"]
    receipt_path = tmp_path / receipt_ref["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters"):
        architecture[field] += 1_000
        receipt[field] += 1_000
    receipt_ref["sha256"] = _write_json(receipt_path, receipt)
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    assert any(
        "config-derived" in error
        for error in json.loads(result.stdout)["errors"]
    )

def test_hashed_counter_must_execute_successfully(tmp_path: Path) -> None:
    path = _make_sparse(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    architecture = payload["architecture"]
    counter_path = tmp_path / architecture["parameter_counter"]["path"]
    counter_path.write_text("raise SystemExit(9)\n", encoding="utf-8")
    counter_hash = __import__("hashlib").sha256(counter_path.read_bytes()).hexdigest()
    architecture["parameter_counter"]["sha256"] = counter_hash
    registry_path = tmp_path / "trusted-verifiers.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["verifiers"][0]["sha256"] = counter_hash
    _write_json(registry_path, registry)
    receipt_ref = architecture["parameter_receipt"]
    receipt_path = tmp_path / receipt_ref["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["counter_sha256"] = counter_hash
    receipt_ref["sha256"] = _write_json(receipt_path, receipt)
    _write_json(path, payload)
    result = _run(path)
    assert result.returncode == 1
    assert any(
        "counter execution" in error
        for error in json.loads(result.stdout)["errors"]
    )
