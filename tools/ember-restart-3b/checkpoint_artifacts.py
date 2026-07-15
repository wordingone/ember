# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Atomically publish and fail-closed restore sparse checkpoint artifacts."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import torch

from model import EXPERT_NAMES, UnifiedDecoder
from parameter_counter import measure_parameter_counts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, root: Path, *, role: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _write_atomic(root: Path, filename: str, writer: Callable[[Any], None]) -> Path:
    """Write, fsync, and rename one artifact without publishing partial bytes."""

    target = root / filename
    temporary = root / f".{filename}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("wb") as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return target
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(root: Path, filename: str, payload: Mapping[str, Any]) -> Path:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return _write_atomic(root, filename, lambda handle: handle.write(encoded))


def _sha256_value(value: str, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _default_optimizer_contract(optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    cls = type(optimizer)
    return {
        "name": cls.__name__,
        "implementation": f"{cls.__module__}.{cls.__qualname__}",
        "hyperparameters": {"param_group_count": len(optimizer.param_groups), "learning_rate": float(optimizer.param_groups[0]["lr"]), "weight_decay": float(optimizer.param_groups[0]["weight_decay"])},
        "state_format": "torch-optimizer-state-dict-v1",
    }


def _validate_optimizer_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    required = {"name", "implementation", "hyperparameters", "state_format"}
    if not isinstance(contract, Mapping) or set(contract) != required:
        raise ValueError("checkpoint optimizer contract has an invalid shape")
    if not isinstance(contract["name"], str) or not contract["name"]:
        raise ValueError("checkpoint optimizer contract name is invalid")
    if not isinstance(contract["implementation"], str) or not contract["implementation"]:
        raise ValueError("checkpoint optimizer contract implementation is invalid")
    if not isinstance(contract["hyperparameters"], Mapping) or not contract["hyperparameters"]:
        raise ValueError("checkpoint optimizer contract hyperparameters are invalid")
    if not isinstance(contract["state_format"], str) or not contract["state_format"]:
        raise ValueError("checkpoint optimizer contract state format is invalid")
    return {"name": contract["name"], "implementation": contract["implementation"], "hyperparameters": dict(contract["hyperparameters"]), "state_format": contract["state_format"]}


def _runtime_optimizer_contract(optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    """Derive the optimizer identity from the supplied runtime, never its receipt."""

    cls = type(optimizer)
    runtime_implementation = f"{cls.__module__}.{cls.__qualname__}"
    if runtime_implementation == "bitsandbytes.optim.adamw.PagedAdamW8bit":
        if not optimizer.param_groups or not hasattr(optimizer, "args"):
            raise ValueError("runtime PagedAdamW8bit lacks required state")
        group = optimizer.param_groups[0]
        args = optimizer.args
        required_group = ("lr", "weight_decay")
        required_args = ("percentile_clipping", "block_wise", "optim_bits")
        if any(field not in group for field in required_group) or any(not hasattr(args, field) for field in required_args):
            raise ValueError("runtime PagedAdamW8bit lacks required hyperparameters")
        if int(args.optim_bits) != 8:
            raise ValueError("runtime PagedAdamW8bit does not use 8-bit optimizer state")
        implementation = "bitsandbytes.optim.PagedAdamW8bit"
        name = "paged_8bit_adamw"
        hyperparameters = {
            "learning_rate": float(group["lr"]),
            "weight_decay": float(group["weight_decay"]),
            "percentile_clipping": int(args.percentile_clipping),
            "block_wise": bool(args.block_wise),
        }
        state_format = "bitsandbytes-paged-8bit-adamw-state-dict-v1"
    else:
        implementation = runtime_implementation
        name = cls.__name__
        if not optimizer.param_groups or any("lr" not in group or "weight_decay" not in group for group in optimizer.param_groups):
            raise ValueError("runtime optimizer lacks required hyperparameters")
        hyperparameters = {"param_group_count": len(optimizer.param_groups), "learning_rate": float(optimizer.param_groups[0]["lr"]), "weight_decay": float(optimizer.param_groups[0]["weight_decay"])}
        state_format = "torch-optimizer-state-dict-v1"
    return {
        "name": name,
        "implementation": implementation,
        "hyperparameters": hyperparameters,
        "state_format": state_format,
    }


def _optimizer_realization(optimizer: torch.optim.Optimizer, contract: Mapping[str, Any]) -> dict[str, str]:
    runtime_contract = _runtime_optimizer_contract(optimizer)
    if runtime_contract != _validate_optimizer_contract(contract):
        raise ValueError("runtime optimizer realization does not match the declared contract")
    source = inspect.getsourcefile(type(optimizer))
    if source is None or not Path(source).is_file():
        raise ValueError("optimizer implementation source cannot be content-addressed")
    return {
        "implementation": runtime_contract["implementation"],
        "implementation_source_sha256": _sha256(Path(source)),
        "state_format": runtime_contract["state_format"],
        "optimizer_contract_sha256": _canonical_sha256(runtime_contract),
    }


def _validate_runtime_optimizer_realization(
    optimizer: torch.optim.Optimizer,
    contract: Mapping[str, Any],
    realization: Mapping[str, Any],
) -> None:
    """Recompute the receipt from live optimizer code and reject self-consistent forgeries."""

    runtime_realization = _optimizer_realization(optimizer, contract)
    if runtime_realization != dict(realization):
        raise ValueError("runtime optimizer realization does not match the checkpoint receipt")

def _validate_optimizer_realization(contract: Mapping[str, Any], realization: Any) -> dict[str, str]:
    required = {"implementation", "implementation_source_sha256", "state_format", "optimizer_contract_sha256"}
    if not isinstance(realization, Mapping) or set(realization) != required:
        raise ValueError("checkpoint optimizer realization has an invalid shape")
    if realization.get("implementation") != contract["implementation"] or realization.get("state_format") != contract["state_format"]:
        raise ValueError("checkpoint optimizer realization drifts from its contract")
    for field in ("implementation_source_sha256", "optimizer_contract_sha256"):
        _sha256_value(str(realization.get(field, "")), name=f"optimizer realization {field}")
    if realization["optimizer_contract_sha256"] != _canonical_sha256(contract):
        raise ValueError("checkpoint optimizer realization contract hash mismatch")
    return dict(realization)

def _validate_replay_bindings(
    *,
    launch_seed: int,
    rng_state: Mapping[str, torch.Tensor],
    data_cursor: Mapping[str, Any],
    model_config_sha256: str,
    contract_sha256: str,
    expert_genesis_sha256: Mapping[str, str],
) -> None:
    if not isinstance(launch_seed, int) or launch_seed < 0:
        raise ValueError("launch_seed must be a nonnegative integer")
    if set(rng_state) != {"cpu", "cuda"}:
        raise ValueError("checkpoint requires CPU and CUDA RNG states")
    for name, state in rng_state.items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError(f"{name} RNG state must be a one-dimensional uint8 tensor")
    if not isinstance(data_cursor, Mapping):
        raise ValueError("checkpoint requires a nonempty data cursor")
    required_cursor = {"shard", "record_index", "global_step", "tokens_seen"}
    if not required_cursor.issubset(data_cursor):
        raise ValueError("checkpoint data cursor must bind shard, record_index, global_step, and tokens_seen")
    if not isinstance(data_cursor["shard"], str) or not data_cursor["shard"]:
        raise ValueError("checkpoint data cursor shard must be a nonempty string")
    for field in ("record_index", "global_step", "tokens_seen"):
        if not isinstance(data_cursor[field], int) or data_cursor[field] < 0:
            raise ValueError(f"checkpoint data cursor {field} must be a nonnegative integer")
    _sha256_value(model_config_sha256, name="model_config_sha256")
    _sha256_value(contract_sha256, name="contract_sha256")
    if set(expert_genesis_sha256) != set(EXPERT_NAMES):
        raise ValueError("checkpoint requires genesis hashes for all four experts")
    for name, digest in expert_genesis_sha256.items():
        _sha256_value(digest, name=f"{name} expert genesis hash")


def _external_checkpoint_manifest(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    """Verify an externally supplied parent/root bundle without serializing its path."""

    path = Path(path).resolve()
    if not path.is_file() or path.name != "checkpoint-manifest.json":
        raise ValueError(f"{label} manifest must be an externally supplied checkpoint manifest")
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} manifest is not JSON") from error
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest.get("schema_version") not in {"ember-sparse-checkpoint-v3", "ember-sparse-checkpoint-v4"}:
        raise ValueError(f"{label} manifest has an unsupported schema")
    _validated_records(path.parent, {**manifest, "checkpoint_manifest_sha256": manifest_sha256})
    experts = manifest.get("expert_checkpoint_sha256")
    genesis = manifest.get("expert_genesis_sha256")
    if not isinstance(experts, Mapping) or set(experts) != set(EXPERT_NAMES):
        raise ValueError(f"{label} manifest lacks the four expert checkpoint hashes")
    if not isinstance(genesis, Mapping) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError(f"{label} manifest lacks the four expert genesis hashes")
    for name in EXPERT_NAMES:
        _sha256_value(experts[name], name=f"{label} {name} expert hash")
        _sha256_value(genesis[name], name=f"{label} {name} expert genesis hash")
    return dict(manifest), manifest_sha256


def preflight_specialist_lineage_sources(*, parent_manifest: Path, root_manifest: Path) -> dict[str, Any]:
    """Verify immutable parent/root bundles and history before CUDA allocation or staging."""

    parent, parent_sha256 = _external_checkpoint_manifest(Path(parent_manifest), label="parent")
    root, root_sha256 = _external_checkpoint_manifest(Path(root_manifest), label="root genesis")
    if parent.get("schema_version") == "ember-sparse-checkpoint-v3":
        if parent_sha256 != root_sha256:
            raise ValueError("first specialist successor requires exact parent and root checkpoint hashes")
        history = []
    else:
        lineage = parent.get("lineage")
        if not isinstance(lineage, Mapping) or lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
            raise ValueError("specialist lineage root must match the immutable parent root genesis")
        history = lineage.get("trained_expert_ids")
        if not isinstance(history, list):
            raise ValueError("parent lineage has invalid trained expert history")
    if any(name not in EXPERT_NAMES for name in history) or len(set(history)) != len(history):
        raise ValueError("parent lineage has invalid trained expert history")
    return {
        "parent_checkpoint_sha256": parent_sha256,
        "root_genesis_checkpoint_sha256": root_sha256,
        "parent_history": list(history),
    }

def _specialist_lineage(
    lineage: Mapping[str, Any], *, active_expert: str, candidate_parameter_sha256: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Close one-family accretion against independently supplied parent/root bundles."""

    if active_expert not in EXPERT_NAMES:
        raise ValueError("specialist lineage requires one specialist active expert")
    required = {"parent_manifest", "root_manifest", "trained_expert_ids", "data_verification_receipt"}
    if not isinstance(lineage, Mapping) or set(lineage) != required:
        raise ValueError("specialist lineage has an invalid shape")
    parent_source, root_source = lineage["parent_manifest"], lineage["root_manifest"]
    if not isinstance(parent_source, (str, Path)) or not isinstance(root_source, (str, Path)):
        raise ValueError("specialist lineage requires content-addressed external manifests")
    parent_path = Path(parent_source).resolve()
    root_path = Path(root_source).resolve()
    parent, parent_sha256 = _external_checkpoint_manifest(parent_path, label="parent")
    root, root_sha256 = _external_checkpoint_manifest(root_path, label="root genesis")
    parent_lineage = parent.get("lineage")
    if parent.get("schema_version") == "ember-sparse-checkpoint-v3":
        if parent_sha256 != root_sha256:
            raise ValueError("first specialist successor requires exact parent and root checkpoint hashes")
        parent_history = []
    else:
        if not isinstance(parent_lineage, Mapping) or parent_lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
            raise ValueError("specialist lineage root must match the immutable parent root genesis")
        parent_history = parent_lineage.get("trained_expert_ids")
        if not isinstance(parent_history, list):
            raise ValueError("parent lineage has invalid trained expert history")
    if any(name not in EXPERT_NAMES for name in parent_history) or len(set(parent_history)) != len(parent_history):
        raise ValueError("parent lineage has invalid trained expert history")
    trained = lineage["trained_expert_ids"]
    expected_history = [*parent_history, *([] if active_expert in parent_history else [active_expert])]
    if trained != expected_history:
        raise ValueError("specialist lineage trained experts must be parent history union active expert")
    parent_experts = parent["expert_checkpoint_sha256"]
    root_experts = root["expert_checkpoint_sha256"]
    parent_parameters = parent.get("expert_parameter_sha256", parent["expert_genesis_sha256"])
    root_parameters = root.get("expert_parameter_sha256", root["expert_genesis_sha256"])
    if candidate_parameter_sha256[active_expert] == parent_parameters[active_expert]:
        raise ValueError("active expert parameter content must change from parent")
    for name in EXPERT_NAMES:
        if name == active_expert:
            continue
        if candidate_parameter_sha256[name] != parent_parameters[name]:
            raise ValueError(f"inactive expert parameter content changed from parent: {name}")
        if name not in trained and candidate_parameter_sha256[name] != root_parameters[name]:
            raise ValueError(f"not-yet-trained expert must remain equal to root genesis: {name}")
    verification = lineage["data_verification_receipt"]
    verification_fields = {"schema_version", "result", "capability", "data_manifest_sha256", "tokenizer_sha256", "verifier_sha256", "data_class", "record_count", "token_count", "source_manifest_sha256", "records_artifact_sha256", "semantic_checks", "generator_replay_verified"}
    capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    if not isinstance(verification, Mapping) or set(verification) != verification_fields:
        raise ValueError("specialist lineage requires the exact executed data verification receipt")
    if verification.get("schema_version") != "ember-training-data-verification-v1" or verification.get("result") != "VERIFIED" or verification.get("data_class") != "SEMANTIC_PRETRAINING" or verification.get("generator_replay_verified") is not True:
        raise ValueError("specialist lineage data verification was not replay-verified")
    expected_checks = {"image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"], "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"], "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"], "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"]}
    if capability_experts.get(verification.get("capability")) != active_expert:
        raise ValueError("specialist lineage verification capability does not map to active expert")
    if verification.get("semantic_checks") != expected_checks[verification["capability"]]:
        raise ValueError("specialist lineage verification semantic checks are not canonical")
    for field in ("data_manifest_sha256", "tokenizer_sha256", "verifier_sha256", "source_manifest_sha256", "records_artifact_sha256"):
        _sha256_value(verification.get(field), name=f"specialist verification {field}")
    if type(verification.get("record_count")) is not int or verification["record_count"] <= 0 or type(verification.get("token_count")) is not int or verification["token_count"] <= 0:
        raise ValueError("specialist lineage verification has no training evidence")
    return ({
        "parent_checkpoint_sha256": parent_sha256,
        "root_genesis_checkpoint_sha256": root_sha256,
        "trained_expert_ids": list(trained),
        "episode": {
            "active_expert": active_expert,
            "data_verification_receipt": dict(verification),
            "data_verification_receipt_sha256": _canonical_sha256(verification),
        },
    }, dict(root["expert_genesis_sha256"]), dict(parent_experts), parent_path.parent)
def _link_or_copy_verified(source: Path, target: Path, expected_sha256: str) -> Path:
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
    if _sha256(target) != expected_sha256:
        raise ValueError("parent expert shard hash mismatch during inactive-bank reuse")
    return target

def write_checkpoint_artifacts(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    *,
    launch_seed: int,
    rng_state: Mapping[str, torch.Tensor],
    data_cursor: Mapping[str, Any],
    model_config_sha256: str,
    contract_sha256: str,
    expert_genesis_sha256: Mapping[str, str],
    optimizer_contract: Mapping[str, Any] | None = None,
    specialist_lineage: Mapping[str, Any] | None = None,
    max_serialized_bytes: int | None = None,
) -> dict[str, Any]:
    """Publish complete post-step artifacts, manifest last, with replay bindings."""

    if max_serialized_bytes is not None and (type(max_serialized_bytes) is not int or max_serialized_bytes < 1):
        raise ValueError("max_serialized_bytes must be a positive integer")
    _validate_replay_bindings(
        launch_seed=launch_seed,
        rng_state=rng_state,
        data_cursor=data_cursor,
        model_config_sha256=model_config_sha256,
        contract_sha256=contract_sha256,
        expert_genesis_sha256=expert_genesis_sha256,
    )
    optimizer_contract = _validate_optimizer_contract(optimizer_contract or _default_optimizer_contract(optimizer))
    optimizer_realization = _optimizer_realization(optimizer, optimizer_contract)
    expert_parameter_sha256 = model.expert_bank_genesis_hashes()
    preflight_lineage = None
    preflight_genesis = None
    if specialist_lineage is not None:
        preflight_lineage, preflight_genesis, preflight_parent_shards, preflight_parent_root = _specialist_lineage(specialist_lineage, active_expert=model.active_expert, candidate_parameter_sha256=expert_parameter_sha256)
    published_root = root
    if published_root.exists():
        raise FileExistsError(f"published checkpoint bundle already exists: {published_root}")
    published_root.parent.mkdir(parents=True, exist_ok=True)
    root = published_root.parent / f".{published_root.name}.{uuid.uuid4().hex}.staging"
    root.mkdir()
    try:
        shared_state = {
            name: value.detach().cpu()
            for name, value in model.state_dict().items()
            if ".experts." not in name
        }
        shared = _write_atomic(
            root,
            "shared.pt",
            lambda handle: torch.save({"model": shared_state, "optimizer": optimizer.state_dict(), "optimizer_contract": optimizer_contract, "optimizer_realization": optimizer_realization}, handle),
        )
        shards = [_record(shared, root, role="shared_model_and_optimizer")]
        replay = _write_atomic(root, "replay-state.pt", lambda handle: torch.save({"rng_state": {name: state.detach().cpu() for name, state in rng_state.items()}, "data_cursor": dict(data_cursor)}, handle))
        shards.append(_record(replay, root, role="replay_state"))
        expert_checkpoint_sha256: dict[str, str] = {}
        for name in EXPERT_NAMES:
            state = {
                key: value.detach().cpu()
                for key, value in model.state_dict().items()
                if f".experts.{name}." in key
            }
            if specialist_lineage is not None and name != model.active_expert:
                path = _link_or_copy_verified(preflight_parent_root / f"expert-{name}.pt", root / f"expert-{name}.pt", preflight_parent_shards[name])
            else:
                path = _write_atomic(
                    root,
                    f"expert-{name}.pt",
                    lambda handle, selected=name, selected_state=state: torch.save(
                        {"expert": selected, "model": selected_state}, handle
                    ),
                )
            record = _record(path, root, role=f"expert_{name}")
            shards.append(record)
            expert_checkpoint_sha256[name] = record["sha256"]

        counts = measure_parameter_counts(model)
        expert_parameter_sha256 = model.expert_bank_genesis_hashes()
        lineage = None
        manifest_genesis = dict(expert_genesis_sha256)
        if specialist_lineage is not None:
            lineage, manifest_genesis = preflight_lineage, preflight_genesis
        manifest = {
            "schema_version": "ember-sparse-checkpoint-v4" if lineage is not None else "ember-sparse-checkpoint-v3",
            "contract_version": 4 if lineage is not None else 3,
            "architecture_revision": "ember-sparse-3b-v2",
            "architecture": {
                "revision": "ember-sparse-3b-v2",
                "allocated_parameters": int(counts["allocated_parameters"]),
                "unique_parameters": int(counts["unique_parameters"]),
                "trainable_parameters": int(counts["trainable_parameters"]),
                "served_parameters": int(counts["served_parameters"]),
                "active_parameters": int(counts["active_parameters"]),
                "episode_trainable_parameters": int(counts["episode_trainable_parameters"]),
                "shared_text_ffn": "always_active_SwiGLU_4H",
            },
            "launch_seed": launch_seed,
            "rng_state_sha256": {name: hashlib.sha256(state.detach().cpu().numpy().tobytes()).hexdigest() for name, state in rng_state.items()},
            "data_cursor": dict(data_cursor),
            "model_config_sha256": model_config_sha256,
            "contract_sha256": contract_sha256,
            "active_expert_ids": [model.active_expert],
            "expert_genesis_sha256": manifest_genesis,
            "expert_checkpoint_sha256": expert_checkpoint_sha256,
            "expert_parameter_sha256": expert_parameter_sha256,
            "shared_optimizer_shard_sha256": shards[0]["sha256"],
            "optimizer_contract": optimizer_contract,
            "optimizer_realization": optimizer_realization,
            "shards": shards,
        }
        if lineage is not None:
            manifest["lineage"] = lineage
        manifest_path = _write_json_atomic(root, "checkpoint-manifest.json", manifest)
        actual_serialized_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        if max_serialized_bytes is not None and actual_serialized_bytes > max_serialized_bytes:
            raise ValueError("serialized checkpoint exceeds the derived byte bound")
        receipt = {**manifest, "checkpoint_manifest_sha256": _sha256(manifest_path), "serialized_bytes": actual_serialized_bytes}
        os.replace(root, published_root)
        return receipt
    except Exception:
        if root.exists():
            shutil.rmtree(root)
        raise


def _validated_records(root: Path, receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_path = root / "checkpoint-manifest.json"
    expected_manifest = _sha256_value(str(receipt.get("checkpoint_manifest_sha256", "")), name="checkpoint_manifest_sha256")
    if _sha256(manifest_path) != expected_manifest:
        raise ValueError("checkpoint manifest hash mismatch")
    records: dict[str, dict[str, Any]] = {}
    for item in receipt.get("shards", []):
        if not isinstance(item, dict):
            raise ValueError("checkpoint shard record is invalid")
        relative = item.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("checkpoint shard path is not bundle-relative")
        if relative in records:
            raise ValueError("checkpoint contains duplicate shard paths")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"checkpoint shard is missing: {relative}")
        expected_size = item.get("bytes")
        expected_hash = item.get("sha256")
        if not isinstance(expected_size, int) or expected_size <= 0 or not isinstance(expected_hash, str):
            raise ValueError(f"checkpoint shard record is invalid: {relative}")
        if path.stat().st_size != expected_size or _sha256(path) != expected_hash:
            if relative.startswith("expert-") and relative.endswith(".pt"):
                name = relative[len("expert-"):-len(".pt")]
                raise ValueError(f"checkpoint expert shard hash mismatch: {name}")
            raise ValueError(f"checkpoint shard hash mismatch: {relative}")
        records[relative] = item
    expected_paths = {"shared.pt", "replay-state.pt", *(f"expert-{name}.pt" for name in EXPERT_NAMES)}
    if set(records) != expected_paths:
        raise ValueError("checkpoint does not contain exactly the shared and four expert shards")
    return records


def _validate_model_state(expected: Mapping[str, torch.Tensor], actual: Any, *, label: str) -> dict[str, torch.Tensor]:
    if not isinstance(actual, dict) or set(actual) != set(expected):
        raise ValueError(f"{label} model state keys do not match this architecture")
    for key, tensor in actual.items():
        if not isinstance(tensor, torch.Tensor) or tuple(tensor.shape) != tuple(expected[key].shape):
            raise ValueError(f"{label} tensor shape does not match this architecture: {key}")
    return actual


def load_checkpoint_artifacts(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    receipt: Mapping[str, Any],
) -> None:
    """Verify every manifest/shard/payload before mutating model or optimizer."""

    if receipt.get("schema_version") not in {"ember-sparse-checkpoint-v3", "ember-sparse-checkpoint-v4"}:
        raise ValueError("checkpoint optimizer contract requires a v3 or v4 manifest")
    optimizer_contract = _validate_optimizer_contract(receipt.get("optimizer_contract", {}))
    optimizer_realization = _validate_optimizer_realization(optimizer_contract, receipt.get("optimizer_realization"))
    if optimizer is not None:
        _validate_runtime_optimizer_realization(optimizer, optimizer_contract, optimizer_realization)
    expected = receipt.get("expert_checkpoint_sha256")
    genesis = receipt.get("expert_genesis_sha256")
    active = receipt.get("active_expert_ids")
    if not isinstance(expected, dict) or set(expected) != set(EXPERT_NAMES):
        raise ValueError("checkpoint receipt lacks the four expert hashes")
    if not isinstance(genesis, dict) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError("checkpoint receipt lacks the four expert genesis hashes")
    if not isinstance(active, list) or len(active) != 1 or active[0] not in {*EXPERT_NAMES, "shared"}:
        raise ValueError("checkpoint receipt lacks exactly one declared active expert")
    records = _validated_records(root, receipt)

    payloads: dict[str, Any] = {}
    for relative in records:
        payloads[relative] = torch.load(root / relative, map_location="cpu", weights_only=False)
    replay_payload = payloads["replay-state.pt"]
    if (not isinstance(replay_payload, dict) or not isinstance(replay_payload.get("rng_state"), dict) or set(replay_payload["rng_state"]) != {"cpu", "cuda"} or replay_payload.get("data_cursor") != receipt.get("data_cursor")):
        raise ValueError("checkpoint replay state is incomplete or cursor-mismatched")
    for name, state in replay_payload["rng_state"].items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError(f"checkpoint replay RNG state is invalid: {name}")
    shared_payload = payloads["shared.pt"]
    if not isinstance(shared_payload, dict) or not isinstance(shared_payload.get("optimizer"), dict):
        raise ValueError("shared checkpoint does not contain optimizer state")
    if shared_payload.get("optimizer_contract") != optimizer_contract or shared_payload.get("optimizer_realization") != optimizer_realization:
        raise ValueError("shared checkpoint optimizer realization does not match manifest")
    expected_state = model.state_dict()
    shared_expected = {key: value for key, value in expected_state.items() if ".experts." not in key}
    shared_state = _validate_model_state(shared_expected, shared_payload.get("model"), label="shared")
    expert_states: dict[str, dict[str, torch.Tensor]] = {}
    for name in EXPERT_NAMES:
        relative = f"expert-{name}.pt"
        payload = payloads[relative]
        if not isinstance(payload, dict) or payload.get("expert") != name:
            raise ValueError(f"checkpoint expert payload does not identify {name}")
        if records[relative]["sha256"] != expected[name]:
            raise ValueError(f"checkpoint expert receipt does not bind {name}")
        expert_expected = {
            key: value for key, value in expected_state.items() if f".experts.{name}." in key
        }
        expert_states[name] = _validate_model_state(expert_expected, payload.get("model"), label=f"expert {name}")

    model.load_state_dict(shared_state, strict=False)
    for state in expert_states.values():
        model.load_state_dict(state, strict=False)
    if optimizer is not None:
        optimizer.load_state_dict(shared_payload["optimizer"])
    model._activate_expert(active[0])
    torch.set_rng_state(replay_payload["rng_state"]["cpu"])
    if torch.cuda.is_available():
            torch.cuda.set_rng_state(replay_payload["rng_state"]["cuda"])
    return {"data_cursor": dict(replay_payload["data_cursor"])}
