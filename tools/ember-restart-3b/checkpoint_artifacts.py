# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Atomically publish and fail-closed restore sparse checkpoint artifacts."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import torch

from model import EXPERT_NAMES, UnifiedDecoder


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
) -> dict[str, Any]:
    """Publish complete post-step artifacts, manifest last, with replay bindings."""

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
    published_root = root
    if published_root.exists():
        raise FileExistsError(f"published checkpoint bundle already exists: {published_root}")
    published_root.parent.mkdir(parents=True, exist_ok=True)
    root = published_root.parent / f".{published_root.name}.{uuid.uuid4().hex}.staging"
    root.mkdir()
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

    manifest = {
        "schema_version": "ember-sparse-checkpoint-v3",
        "launch_seed": launch_seed,
        "rng_state_sha256": {name: hashlib.sha256(state.detach().cpu().numpy().tobytes()).hexdigest() for name, state in rng_state.items()},
        "data_cursor": dict(data_cursor),
        "model_config_sha256": model_config_sha256,
        "contract_sha256": contract_sha256,
        "active_expert_ids": [model.active_expert],
        "expert_genesis_sha256": dict(expert_genesis_sha256),
        "expert_checkpoint_sha256": expert_checkpoint_sha256,
        "shared_optimizer_shard_sha256": shards[0]["sha256"],
        "optimizer_contract": optimizer_contract,
        "optimizer_realization": optimizer_realization,
        "shards": shards,
    }
    manifest_path = _write_json_atomic(root, "checkpoint-manifest.json", manifest)
    receipt = {**manifest, "checkpoint_manifest_sha256": _sha256(manifest_path)}
    os.replace(root, published_root)
    return receipt


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

    if receipt.get("schema_version") != "ember-sparse-checkpoint-v3":
        raise ValueError("checkpoint optimizer contract requires v3 manifest")
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
    if not isinstance(active, list) or len(active) != 1 or active[0] not in EXPERT_NAMES:
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