# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed model-only bridge between optimizer semantic contracts."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from checkpoint_artifacts import _validated_records
from semantic_contract import semantic_model_contract_sha256
from step2_realization_registry import validate_step2_realization_registry_bundle

_ADMISSION_KIND = "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION"
_SOURCE_OPTIMIZER = {
    "name": "paged_8bit_adamw",
    "implementation": "bitsandbytes.optim.PagedAdamW8bit",
    "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
}
_TARGET_OPTIMIZER = {
    "name": "device_resident_8bit_adamw",
    "implementation": "bitsandbytes.optim.AdamW8bit",
    "placement": "cuda_non_paged",
    "state_format": "bitsandbytes-device-resident-8bit-adamw-state-dict-v1",
}


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"cannot read transition artifact: {path.name}") from error


def _json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _bound_path(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} path is invalid")
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError(f"{label} path escapes transition bundle")
    return candidate


def _historical_config_path(source_registry_path: Path) -> Path:
    registry, _ = _json(source_registry_path, "source realization registry")
    configs = registry.get("model_configs")
    if not isinstance(configs, list) or len(configs) != 1 or not isinstance(configs[0], dict):
        raise ValueError("source realization registry lacks one historical config")
    return _bound_path(source_registry_path.parent.resolve(), configs[0].get("path"), "historical config")


def _require_closed_source_authority(source_registry_path: Path) -> None:
    registry, _ = _json(source_registry_path, "source realization registry")
    expected = {"trusted-verifiers.json"}
    for field in ("verifiers", "realization_receipts", "model_configs"):
        entries = registry.get(field)
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            raise ValueError("source realization authority is not a closed v2 bundle")
        relative = entries[0].get("path")
        _bound_path(source_registry_path.parent.resolve(), relative, f"source {field}")
        expected.add(Path(relative).as_posix())
    actual = {
        path.relative_to(source_registry_path.parent).as_posix()
        for path in source_registry_path.parent.rglob("*") if path.is_file()
    }
    if actual != expected:
        raise ValueError("source realization authority contains unrecorded files")


def _exact_optimizer(config: Mapping[str, Any], expected: Mapping[str, str], label: str) -> dict[str, Any]:
    training = config.get("training")
    optimizer = training.get("optimizer") if isinstance(training, Mapping) else None
    if not isinstance(optimizer, dict) or set(optimizer) != set(expected) | {"hyperparameters"}:
        raise ValueError(f"{label} optimizer contract shape is invalid")
    if any(optimizer.get(field) != value for field, value in expected.items()):
        raise ValueError(f"{label} optimizer contract is not exact")
    if not isinstance(optimizer.get("hyperparameters"), dict):
        raise ValueError(f"{label} optimizer hyperparameters are invalid")
    return optimizer


def validate_optimizer_transition_registry(
    registry_path: Path, *, checkpoint_root: Path, current_target_config_path: Path,
) -> dict[str, Any]:
    """Admit one exact model-only transition; optimizer state never crosses it."""

    registry_path = registry_path.resolve()
    root = registry_path.parent
    if {path.name for path in root.iterdir()} != {"source-authority", "target-config.json", "optimizer_transition.py", "optimizer-transition-receipt.json", "trusted-transitions.json"}:
        raise ValueError("optimizer transition bundle contains unrecorded entries")
    registry, _ = _json(registry_path, "optimizer transition registry")
    if set(registry) != {"schema_version", "verifiers", "transitions"} or registry.get("schema_version") != "ember-optimizer-transition-registry-v1":
        raise ValueError("optimizer transition registry must be closed")
    verifiers = registry.get("verifiers")
    transitions = registry.get("transitions")
    if not isinstance(verifiers, list) or len(verifiers) != 1 or not isinstance(transitions, list) or len(transitions) != 1:
        raise ValueError("optimizer transition registry must bind one verifier and transition")
    verifier = verifiers[0]
    binding = transitions[0]
    if not isinstance(verifier, dict) or set(verifier) != {"path", "sha256", "evidence_classes", "criterion_ids"}:
        raise ValueError("optimizer transition verifier binding is invalid")
    if verifier.get("evidence_classes") != ["optimizer_contract_transition"] or verifier.get("criterion_ids") != ["ember-model-only-optimizer-transition-v1"]:
        raise ValueError("optimizer transition verifier authority is not exact")
    verifier_path = _bound_path(root, verifier.get("path"), "transition verifier")
    if _sha256(verifier_path) != verifier.get("sha256") or verifier.get("sha256") != _sha256(Path(__file__).resolve()):
        raise ValueError("optimizer transition verifier bytes are not current and trusted")
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "admission_kind", "source_checkpoint_manifest_sha256", "target_model_config_sha256"}:
        raise ValueError("optimizer transition receipt binding is invalid")
    receipt_path = _bound_path(root, binding.get("path"), "transition receipt")
    receipt, receipt_sha256 = _json(receipt_path, "optimizer transition receipt")
    if receipt_sha256 != binding.get("sha256"):
        raise ValueError("optimizer transition receipt hash mismatch")
    expected_receipt_keys = {"schema_version", "verification_boundary", "result", "admission_kind", "source", "target", "model_state_reused", "optimizer_state_reused", "optimizer_state_disposition", "model_shards"}
    if set(receipt) != expected_receipt_keys or receipt.get("schema_version") != "ember-optimizer-transition-v1" or receipt.get("verification_boundary") != "VERIFIED_MODEL_ONLY_TRANSITION" or receipt.get("result") != "ADMITTED" or receipt.get("admission_kind") != _ADMISSION_KIND:
        raise ValueError("optimizer transition receipt has an invalid closed boundary")
    if receipt.get("model_state_reused") is not True or receipt.get("optimizer_state_reused") is not False or receipt.get("optimizer_state_disposition") != "MEMORY_MAPPED_WITH_SOURCE_SHARED_SHARD_AND_DISCARDED_WITHOUT_REUSE":
        raise ValueError("optimizer transition state disposition is not model-only")
    if binding.get("admission_kind") != _ADMISSION_KIND:
        raise ValueError("optimizer transition admission kind mismatch")

    source_registry_path = (root / "source-authority" / "trusted-verifiers.json").resolve()
    _require_closed_source_authority(source_registry_path)
    historical_config_path = _historical_config_path(source_registry_path)
    source_admission = validate_step2_realization_registry_bundle(
        source_registry_path, (checkpoint_root.resolve() / "checkpoint-manifest.json"), historical_config_path,
    )
    manifest_path = checkpoint_root.resolve() / "checkpoint-manifest.json"
    manifest, manifest_sha256 = _json(manifest_path, "source checkpoint manifest")
    source_config, source_config_sha256 = _json(historical_config_path, "source model config")
    target_bundle_path = root / "target-config.json"
    target_config, target_config_sha256 = _json(target_bundle_path, "target model config")
    current_target, current_target_sha256 = _json(current_target_config_path.resolve(), "current target config")
    if target_config_sha256 != current_target_sha256 or target_config != current_target:
        raise ValueError("target config bytes drift from the admitted transition")
    source_optimizer = _exact_optimizer(source_config, _SOURCE_OPTIMIZER, "source")
    target_optimizer = _exact_optimizer(target_config, _TARGET_OPTIMIZER, "target")
    if source_optimizer["hyperparameters"] != target_optimizer["hyperparameters"]:
        raise ValueError("optimizer transition must preserve exact parent/successor hyperparameters")
    if manifest.get("optimizer_contract") != source_optimizer:
        raise ValueError("source checkpoint optimizer contract is not the admitted paged contract")
    source_semantic = semantic_model_contract_sha256(source_config)
    target_semantic = semantic_model_contract_sha256(target_config)
    if source_semantic == target_semantic:
        raise ValueError("optimizer transition does not change semantic identity")
    source = receipt.get("source")
    target = receipt.get("target")
    expected_source = {
        "checkpoint_manifest_sha256": manifest_sha256,
        "model_config_sha256": source_config_sha256,
        "semantic_model_contract_sha256": source_semantic,
        "optimizer_contract_sha256": _canonical_sha256(source_optimizer),
        "optimizer_implementation": source_optimizer["implementation"],
        "realization_receipt_sha256": source_admission["receipt_sha256"],
    }
    expected_target = {
        "model_config_sha256": target_config_sha256,
        "semantic_model_contract_sha256": target_semantic,
        "optimizer_contract_sha256": _canonical_sha256(target_optimizer),
        "optimizer_implementation": target_optimizer["implementation"],
        "optimizer_placement": target_optimizer["placement"],
    }
    if source != expected_source or target != expected_target:
        raise ValueError("optimizer transition source/target identity mismatch")
    records = _validated_records(checkpoint_root.resolve(), {**manifest, "checkpoint_manifest_sha256": manifest_sha256})
    expected_shards = {path: {"sha256": row["sha256"], "bytes": row["bytes"]} for path, row in sorted(records.items())}
    if receipt.get("model_shards") != expected_shards:
        raise ValueError("optimizer transition model shard binding mismatch")
    if binding.get("source_checkpoint_manifest_sha256") != manifest_sha256 or binding.get("target_model_config_sha256") != target_config_sha256:
        raise ValueError("optimizer transition registry identity mismatch")
    return {**receipt, "receipt_sha256": receipt_sha256, "registry_sha256": _sha256(registry_path)}


def write_optimizer_transition_registry(
    bundle_path: Path, *, source_registry_path: Path, checkpoint_root: Path, target_config_path: Path,
) -> Path:
    """Atomically publish a portable transition authority and self-validate it."""

    bundle_path = bundle_path.resolve()
    if bundle_path.exists():
        raise FileExistsError(f"optimizer transition bundle already exists: {bundle_path}")
    source_registry_path = source_registry_path.resolve()
    checkpoint_root = checkpoint_root.resolve()
    target_config_path = target_config_path.resolve()
    historical_config_path = _historical_config_path(source_registry_path)
    _require_closed_source_authority(source_registry_path)
    source_admission = validate_step2_realization_registry_bundle(
        source_registry_path, checkpoint_root / "checkpoint-manifest.json", historical_config_path,
    )
    manifest, manifest_sha256 = _json(checkpoint_root / "checkpoint-manifest.json", "source checkpoint manifest")
    source_config, source_config_sha256 = _json(historical_config_path, "source model config")
    target_config, target_config_sha256 = _json(target_config_path, "target model config")
    source_optimizer = _exact_optimizer(source_config, _SOURCE_OPTIMIZER, "source")
    target_optimizer = _exact_optimizer(target_config, _TARGET_OPTIMIZER, "target")
    if source_optimizer["hyperparameters"] != target_optimizer["hyperparameters"]:
        raise ValueError("optimizer transition must preserve exact parent/successor hyperparameters")
    if manifest.get("optimizer_contract") != source_optimizer:
        raise ValueError("source checkpoint optimizer contract is not the admitted paged contract")
    records = _validated_records(checkpoint_root, {**manifest, "checkpoint_manifest_sha256": manifest_sha256})
    receipt = {
        "schema_version": "ember-optimizer-transition-v1",
        "verification_boundary": "VERIFIED_MODEL_ONLY_TRANSITION",
        "result": "ADMITTED",
        "admission_kind": _ADMISSION_KIND,
        "source": {
            "checkpoint_manifest_sha256": manifest_sha256,
            "model_config_sha256": source_config_sha256,
            "semantic_model_contract_sha256": semantic_model_contract_sha256(source_config),
            "optimizer_contract_sha256": _canonical_sha256(source_optimizer),
            "optimizer_implementation": source_optimizer["implementation"],
            "realization_receipt_sha256": source_admission["receipt_sha256"],
        },
        "target": {
            "model_config_sha256": target_config_sha256,
            "semantic_model_contract_sha256": semantic_model_contract_sha256(target_config),
            "optimizer_contract_sha256": _canonical_sha256(target_optimizer),
            "optimizer_implementation": target_optimizer["implementation"],
            "optimizer_placement": target_optimizer["placement"],
        },
        "model_state_reused": True,
        "optimizer_state_reused": False,
        "optimizer_state_disposition": "MEMORY_MAPPED_WITH_SOURCE_SHARED_SHARD_AND_DISCARDED_WITHOUT_REUSE",
        "model_shards": {path: {"sha256": row["sha256"], "bytes": row["bytes"]} for path, row in sorted(records.items())},
    }
    staging = bundle_path.parent / f".{bundle_path.name}.{uuid.uuid4().hex}.staging"
    try:
        staging.mkdir(parents=True)
        shutil.copytree(source_registry_path.parent, staging / "source-authority")
        shutil.copyfile(target_config_path, staging / "target-config.json")
        shutil.copyfile(Path(__file__).resolve(), staging / "optimizer_transition.py")
        receipt_path = staging / "optimizer-transition-receipt.json"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        registry = {
            "schema_version": "ember-optimizer-transition-registry-v1",
            "verifiers": [{
                "path": "optimizer_transition.py", "sha256": _sha256(staging / "optimizer_transition.py"),
                "evidence_classes": ["optimizer_contract_transition"],
                "criterion_ids": ["ember-model-only-optimizer-transition-v1"],
            }],
            "transitions": [{
                "path": receipt_path.name, "sha256": _sha256(receipt_path), "admission_kind": _ADMISSION_KIND,
                "source_checkpoint_manifest_sha256": manifest_sha256, "target_model_config_sha256": target_config_sha256,
            }],
        }
        registry_path = staging / "trusted-transitions.json"
        registry_path.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
        validate_optimizer_transition_registry(registry_path, checkpoint_root=checkpoint_root, current_target_config_path=target_config_path)
        staging.rename(bundle_path)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return bundle_path / "trusted-transitions.json"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write")
    write.add_argument("--bundle", type=Path, required=True)
    write.add_argument("--source-registry", type=Path, required=True)
    write.add_argument("--checkpoint", type=Path, required=True)
    write.add_argument("--target-config", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--registry", type=Path, required=True)
    verify.add_argument("--checkpoint", type=Path, required=True)
    verify.add_argument("--target-config", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "write":
        registry = write_optimizer_transition_registry(
            args.bundle,
            source_registry_path=args.source_registry,
            checkpoint_root=args.checkpoint,
            target_config_path=args.target_config,
        )
        admitted = validate_optimizer_transition_registry(
            registry, checkpoint_root=args.checkpoint, current_target_config_path=args.target_config,
        )
    else:
        registry = args.registry.resolve()
        admitted = validate_optimizer_transition_registry(
            registry, checkpoint_root=args.checkpoint, current_target_config_path=args.target_config,
        )
    print(json.dumps({"registry": str(registry), **admitted}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
