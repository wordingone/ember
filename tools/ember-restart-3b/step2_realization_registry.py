# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed admission of a one-time step-2 realization receipt."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

_EXPERTS = {"vision", "audio", "reasoning", "tool"}
_COUNTS = {
    "allocated_parameters": 3839161856,
    "unique_parameters": 3839161856,
    "trainable_parameters": 3839161856,
    "served_parameters": 3839161856,
    "active_parameters": 1020589568,
    "episode_trainable_parameters": 1020589568,
}


def _snapshot_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value, hashlib.sha256(payload).hexdigest()


def _sha256_bytes(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"{label} cannot be read") from error


def validate_step2_realization_receipt(receipt_path: Path, registry_path: Path, *, subject_checkpoint_sha256: str, model_config_sha256: str, counter_path: Path) -> dict[str, Any]:
    receipt, receipt_sha256 = _snapshot_json(receipt_path, "realization receipt")
    registry, _registry_sha256 = _snapshot_json(registry_path, "trusted verifier registry")
    if registry.get("schema_version") != "ember-trusted-verifiers-v1" or not isinstance(registry.get("verifiers"), list):
        raise ValueError("trusted verifier registry has an invalid schema")
    counter_sha256 = _sha256_bytes(counter_path, "counter source")
    trusted = False
    root = registry_path.resolve().parent
    for entry in registry["verifiers"]:
        if not isinstance(entry, dict) or entry.get("sha256") != counter_sha256:
            continue
        relative = entry.get("path")
        candidate = (root / relative).resolve() if isinstance(relative, str) and relative and not Path(relative).is_absolute() else None
        if candidate is None or root not in candidate.parents or candidate != counter_path.resolve() or "parameter_realization" not in entry.get("evidence_classes", []) or "ember-sparse-step2-realization-v1" not in entry.get("criterion_ids", []):
            continue
        trusted = True
    if not trusted:
        raise ValueError("counter source is not trusted for step-2 realization")
    bindings = registry.get("realization_receipts")
    if not isinstance(bindings, list) or not any(
        isinstance(entry, dict)
        and isinstance(entry.get("path"), str)
        and entry["path"]
        and not Path(entry["path"]).is_absolute()
        and root in (root / entry["path"]).resolve().parents
        and (root / entry["path"]).resolve() == receipt_path.resolve()
        and entry.get("sha256") == receipt_sha256
        and entry.get("subject_checkpoint_sha256") == subject_checkpoint_sha256
        and entry.get("model_config_sha256") == model_config_sha256
        and entry.get("counter_sha256") == counter_sha256
        and entry.get("active_expert") == "shared"
        for entry in bindings
    ):
        raise ValueError("trusted verifier registry lacks an exact realization receipt binding")
    if receipt.get("schema_version") != "ember-sparse-realization-receipt-v1" or receipt.get("verification_boundary") != "VERIFIED_MEASURED" or receipt.get("result") != "MEASURED":
        raise ValueError("realization receipt has an invalid closed boundary")
    if receipt.get("subject_checkpoint_sha256") != subject_checkpoint_sha256 or receipt.get("model_config_sha256") != model_config_sha256 or receipt.get("counter_sha256") != counter_sha256:
        raise ValueError("realization receipt identity does not match its bound subject/config/counter")
    if receipt.get("architecture_revision") != "ember-sparse-3b-v2" or receipt.get("active_expert_ids") != ["shared"]:
        raise ValueError("realization receipt does not bind the shared step-2 route")
    for field, expected in _COUNTS.items():
        if receipt.get(field) != expected:
            raise ValueError(f"realization receipt {field} is not exact")
    for field in ("expert_genesis_sha256", "expert_parameter_sha256"):
        banks = receipt.get(field)
        if not isinstance(banks, dict) or set(banks) != _EXPERTS or any(not isinstance(value, str) or len(value) != 64 for value in banks.values()):
            raise ValueError(f"realization receipt {field} is invalid")
    return {**receipt, "receipt_sha256": receipt_sha256}

def write_step2_realization_registry(
    bundle_path: Path, *, receipt_path: Path, counter_path: Path,
) -> Path:
    """Atomically materialize a portable registry bound to exact local bytes."""
    bundle_path = bundle_path.resolve()
    if bundle_path.exists():
        raise FileExistsError(f"step-2 realization registry already exists: {bundle_path}")
    receipt, receipt_sha256 = _snapshot_json(receipt_path, "realization receipt")
    counter_sha256 = _sha256_bytes(counter_path, "counter source")
    subject = receipt.get("subject_checkpoint_sha256")
    config = receipt.get("model_config_sha256")
    if not isinstance(subject, str) or not isinstance(config, str):
        raise ValueError("realization receipt lacks subject/config identity")
    staging = bundle_path.parent / f".{bundle_path.name}.{uuid.uuid4().hex}.staging"
    try:
        staging.mkdir(parents=True)
        staged_counter = staging / "parameter_counter.py"
        staged_receipt = staging / "step2-realization-receipt.json"
        shutil.copyfile(counter_path, staged_counter)
        shutil.copyfile(receipt_path, staged_receipt)
        registry = {
            "schema_version": "ember-trusted-verifiers-v1",
            "verifiers": [{
                "path": staged_counter.name,
                "sha256": counter_sha256,
                "evidence_classes": ["parameter_realization"],
                "criterion_ids": ["ember-sparse-step2-realization-v1"],
            }],
            "realization_receipts": [{
                "path": staged_receipt.name,
                "sha256": receipt_sha256,
                "subject_checkpoint_sha256": subject,
                "model_config_sha256": config,
                "counter_sha256": counter_sha256,
                "active_expert": "shared",
            }],
        }
        registry_path = staging / "trusted-verifiers.json"
        registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
        validate_step2_realization_receipt(
            staged_receipt, registry_path,
            subject_checkpoint_sha256=subject, model_config_sha256=config,
            counter_path=staged_counter,
        )
        staging.rename(bundle_path)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return bundle_path / "trusted-verifiers.json"
