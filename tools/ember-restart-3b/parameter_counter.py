# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed and isolated sparse checkpoint-realization counter."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping


EXPERT_NAMES = ("vision", "audio", "reasoning", "tool")
ARCHITECTURE_REVISION = "ember-sparse-3b-v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_value(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _model_shape(config: Mapping[str, Any]) -> dict[str, int]:
    model = config.get("model")
    if not isinstance(model, dict):
        raise ValueError("model config lacks model shape")
    routing = model.get("expert_routing")
    image = model.get("image_projection")
    audio = model.get("audio_projection")
    if not isinstance(routing, dict) or not isinstance(image, dict) or not isinstance(audio, dict):
        raise ValueError("model config lacks sparse modality/routing declarations")
    if tuple(routing.get("expert_names", ())) != EXPERT_NAMES:
        raise ValueError("model config must declare the four authorized experts")
    if tuple(image.get("input_shape", ())) != (48, 48, 3) or int(image.get("output_size", -1)) != int(model.get("hidden_size", -2)):
        raise ValueError("model config must declare raw 48x48x3 projection")
    if int(audio.get("frame_samples", -1)) != 640 or int(audio.get("output_size", -1)) != int(model.get("hidden_size", -2)):
        raise ValueError("model config must declare raw 640-sample projection")
    shape = {
        "hidden_size": int(model["hidden_size"]),
        "layers": int(model["layers"]),
        "attention_heads": int(model["attention_heads"]),
        "vocab_size": int(model["vocab_size"]),
    }
    if any(value <= 0 for value in shape.values()) or shape["hidden_size"] % shape["attention_heads"]:
        raise ValueError("model config has an invalid decoder shape")
    if model.get("tied_embeddings") is not True:
        raise ValueError("model config must require tied embeddings")
    return shape


def _expected_shared(shape: Mapping[str, int]) -> dict[str, tuple[int, ...]]:
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    head_dim = hidden // shape["attention_heads"]
    expected = {
        "token_embedding.weight": (vocab, hidden),
        "lm_head.weight": (vocab, hidden),
        "image_projector.linear.weight": (hidden, 48 * 48 * 3),
        "audio_projector.linear.weight": (hidden, 640),
        "final_norm.weight": (hidden,),
    }
    for layer in range(layers):
        prefix = f"layers.{layer}."
        expected.update({
            prefix + "pre_attention_norm.weight": (hidden,),
            prefix + "attention.qkv.weight": (3 * hidden, hidden),
            prefix + "attention.q_norm.weight": (head_dim,),
            prefix + "attention.k_norm.weight": (head_dim,),
            prefix + "attention.output.weight": (hidden, hidden),
            prefix + "pre_ffn_norm.weight": (hidden,),
            prefix + "shared_ffn.up_gate.weight": (8 * hidden, hidden),
            prefix + "shared_ffn.down.weight": (hidden, 4 * hidden),
        })
    return expected


def _expected_expert(shape: Mapping[str, int], name: str) -> dict[str, tuple[int, ...]]:
    hidden, layers = shape["hidden_size"], shape["layers"]
    return {
        f"layers.{layer}.experts.{name}.up_gate.weight": (8 * hidden, hidden)
        for layer in range(layers)
    } | {
        f"layers.{layer}.experts.{name}.down.weight": (hidden, 4 * hidden)
        for layer in range(layers)
    }


class _StorageRef:
    def __init__(self, size: int, key: str = "", storage_type: str = "") -> None:
        self.size = int(size)
        self.key = key
        self.storage_type = storage_type


class _TensorMetadata:
    def __init__(self, storage: _StorageRef, offset: object, shape: object, stride: object) -> None:
        self.storage = storage
        self.offset = int(offset)
        self.shape = tuple(int(value) for value in shape)
        self.stride = tuple(int(value) for value in stride)


def _rebuild_tensor(storage: _StorageRef, offset: object, shape: object, stride: object, *unused: object) -> _TensorMetadata:
    if not isinstance(storage, _StorageRef):
        raise ValueError("checkpoint tensor lacks an authorized storage reference")
    return _TensorMetadata(storage, offset, shape, stride)


def _rebuild_parameter(value: _TensorMetadata, *unused: object) -> _TensorMetadata:
    return value


class _TensorTypeSentinel:
    """Non-executable placeholder for the exact torch.Tensor pickle global."""


def _rebuild_tensor_from_type(func: object, new_type: object, args: object, state: object) -> _TensorMetadata:
    """Extract only shape metadata from PyTorch's tensor-subtype pickle wrapper."""

    if func is not _rebuild_tensor or new_type is not _TensorTypeSentinel or not isinstance(args, tuple):
        raise ValueError("checkpoint tensor subtype wrapper is not an authorized metadata form")
    value = _rebuild_tensor(*args)
    if not isinstance(value, _TensorMetadata):
        raise ValueError("checkpoint tensor subtype wrapper did not produce tensor metadata")
    return value


class _CheckpointMetadataUnpickler(pickle.Unpickler):
    """Read only tensor metadata from a Torch zip checkpoint."""

    def persistent_load(self, persistent_id: object) -> _StorageRef:
        if not isinstance(persistent_id, tuple) or len(persistent_id) != 5 or persistent_id[0] != "storage":
            raise ValueError("checkpoint contains an unsupported persistent reference")
        storage_type = persistent_id[1]
        return _StorageRef(int(persistent_id[4]), str(persistent_id[2]), getattr(storage_type, "__name__", ""))

    def find_class(self, module: str, name: str) -> object:
        if module == "collections" and name == "OrderedDict":
            from collections import OrderedDict
            return OrderedDict
        if module == "torch._utils" and name.startswith("_rebuild_tensor"):
            return _rebuild_tensor
        if module == "torch._utils" and name == "_rebuild_parameter":
            return _rebuild_parameter
        if module == "torch._tensor" and name == "_rebuild_from_type_v2":
            return _rebuild_tensor_from_type
        if module == "torch" and name == "Tensor":
            return _TensorTypeSentinel
        if module == "torch" and name.endswith("Storage"):
            return type(name, (), {})
        raise ValueError(f"checkpoint references disallowed global {module}.{name}")


def _load_checkpoint_metadata(path: Path) -> Any:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [name for name in archive.namelist() if name.endswith("data.pkl")]
            if len(candidates) != 1:
                raise ValueError("checkpoint zip lacks exactly one data.pkl")
            return _CheckpointMetadataUnpickler(io.BytesIO(archive.read(candidates[0]))).load()
    except (OSError, pickle.PickleError, zipfile.BadZipFile, ValueError) as error:
        raise ValueError(f"checkpoint realization cannot be safely inspected: {error}") from error


def _validate_state(state: Any, expected: Mapping[str, tuple[int, ...]], *, label: str) -> None:
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError(f"{label} state keys do not realize the authorized architecture")
    for key, tensor in state.items():
        if not isinstance(tensor, _TensorMetadata) or tensor.shape != expected[key]:
            raise ValueError(f"{label} tensor shape mismatch: {key}")


def _contiguous_stride(shape: tuple[int, ...]) -> tuple[int, ...]:
    stride: list[int] = []
    next_stride = 1
    for dimension in reversed(shape):
        stride.append(next_stride)
        next_stride *= dimension
    return tuple(reversed(stride))


def _storage_element_bytes(storage_type: str) -> int:
    widths = {"BFloat16Storage": 2, "FloatStorage": 4, "DoubleStorage": 8, "HalfStorage": 2, "LongStorage": 8, "IntStorage": 4, "ShortStorage": 2, "CharStorage": 1, "ByteStorage": 1, "BoolStorage": 1}
    if storage_type not in widths:
        raise ValueError("shared expert genesis uses an unsupported storage type")
    return widths[storage_type]


def _tensor_raw_bytes(archive: zipfile.ZipFile, tensor: _TensorMetadata) -> bytes:
    if tensor.offset != 0 or tensor.stride != _contiguous_stride(tensor.shape):
        raise ValueError("shared expert genesis tensor is not a contiguous base storage")
    width = _storage_element_bytes(tensor.storage.storage_type)
    candidates = [name for name in archive.namelist() if name.endswith(f"data/{tensor.storage.key}")]
    if len(candidates) != 1:
        raise ValueError("shared expert genesis storage entry is ambiguous")
    raw = archive.read(candidates[0])
    expected = tensor.storage.size * width
    if len(raw) != expected:
        raise ValueError("shared expert genesis storage byte size mismatch")
    required = width
    for dimension in tensor.shape:
        required *= dimension
    if required != len(raw):
        raise ValueError("shared expert genesis tensor does not own its full storage")
    return raw


def _verify_shared_expert_genesis(manifest_path: Path, manifest: Mapping[str, Any], shape: Mapping[str, int]) -> None:
    """For shared-text episodes, prove every frozen specialist is still its genesis bank."""

    genesis = manifest["expert_genesis_sha256"]
    for name in EXPERT_NAMES:
        payload = _load_checkpoint_metadata(manifest_path.parent / f"expert-{name}.pt")
        state = payload.get("model") if isinstance(payload, dict) else None
        expected = _expected_expert(shape, name)
        if not isinstance(state, dict) or set(state) != set(expected):
            raise ValueError(f"shared expert genesis payload state mismatch: {name}")
        digest = hashlib.sha256()
        with zipfile.ZipFile(manifest_path.parent / f"expert-{name}.pt") as archive:
            for layer in range(shape["layers"]):
                for suffix in ("up_gate.weight", "down.weight"):
                    tensor = state.get(f"layers.{layer}.experts.{name}.{suffix}")
                    if not isinstance(tensor, _TensorMetadata):
                        raise ValueError(f"shared expert genesis payload tensor mismatch: {name}")
                    digest.update(_tensor_raw_bytes(archive, tensor))
        if digest.hexdigest() != genesis[name]:
            raise ValueError(f"shared expert genesis hash mismatch: {name}")

def _inspect_realization(manifest_path: Path, *, active_expert: str, shape: Mapping[str, int]) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    records = manifest.get("shards")
    if not isinstance(records, list):
        raise ValueError("checkpoint manifest lacks shard records")
    by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("checkpoint shard record is invalid")
        relative = record.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("checkpoint shard path is not bundle-relative")
        if relative in by_path:
            raise ValueError("checkpoint manifest repeats a shard")
        shard = manifest_path.parent / relative
        if not shard.is_file():
            raise ValueError(f"checkpoint shard missing: {relative}")
        if shard.stat().st_size != record.get("bytes"):
            raise ValueError(f"checkpoint shard byte-size mismatch: {relative}")
        if _sha256(shard) != record.get("sha256"):
            raise ValueError(f"checkpoint shard hash mismatch: {relative}")
        by_path[relative] = record
    required = {"shared.pt", "replay-state.pt", *(f"expert-{name}.pt" for name in EXPERT_NAMES)}
    if set(by_path) != required:
        raise ValueError("checkpoint realization must have one shared and four expert shards")
    if manifest.get("active_expert_ids") != [active_expert]:
        raise ValueError("checkpoint active expert does not match executed counter argument")
    if active_expert != "shared" and manifest.get("schema_version") != "ember-sparse-checkpoint-v4":
        raise ValueError("specialist-active realization requires a v4 lineage manifest")
    genesis = manifest.get("expert_genesis_sha256")
    if not isinstance(genesis, dict) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError("checkpoint lacks the four expert genesis hashes")
    for name, digest in genesis.items():
        _sha256_value(digest, label=f"{name} genesis hash")

    shared = _load_checkpoint_metadata(manifest_path.parent / "shared.pt")
    if not isinstance(shared, dict) or "optimizer" not in shared:
        raise ValueError("shared checkpoint lacks optimizer realization")
    _validate_state(shared.get("model"), _expected_shared(shape), label="shared")
    expert_hashes = manifest.get("expert_checkpoint_sha256")
    if not isinstance(expert_hashes, dict) or set(expert_hashes) != set(EXPERT_NAMES):
        raise ValueError("checkpoint lacks expert checkpoint hashes")
    for name in EXPERT_NAMES:
        shard = f"expert-{name}.pt"
        if expert_hashes[name] != by_path[shard]["sha256"]:
            raise ValueError(f"checkpoint expert hash is not bound: {name}")
        payload = _load_checkpoint_metadata(manifest_path.parent / shard)
        if not isinstance(payload, dict) or payload.get("expert") != name:
            raise ValueError(f"expert realization identifies the wrong bank: {name}")
        _validate_state(payload.get("model"), _expected_expert(shape, name), label=f"expert {name}")
    if active_expert == "shared":
        _verify_shared_expert_genesis(manifest_path, manifest, shape)
    return manifest

def _counts(shape: Mapping[str, int], *, active_expert: str) -> dict[str, int]:
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    head_dim = hidden // shape["attention_heads"]
    shared = (
        vocab * hidden
        + layers * (4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim)
        + hidden
        + (48 * 48 * 3) * hidden
        + 640 * hidden
    )
    expert = layers * 12 * hidden * hidden
    total = shared + len(EXPERT_NAMES) * expert
    active = shared if active_expert == "shared" else shared + expert
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
    }


def execute_counter(*, model_config: Path, checkpoint_manifest: Path, active_expert: str, parent_manifest: Path | None = None, root_manifest: Path | None = None) -> dict[str, Any]:
    if active_expert not in {*EXPERT_NAMES, "shared"}:
        raise ValueError("active expert must be shared or one of the four authorized banks")
    config = _load_json(model_config)
    if config.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ValueError("model config revision is not ember-sparse-3b-v2")
    shape = _model_shape(config)
    manifest = _inspect_realization(checkpoint_manifest, active_expert=active_expert, shape=shape)
    if active_expert != "shared" and (parent_manifest is None or root_manifest is None):
        raise ValueError("specialist-active realization requires external parent and root manifests")
    if active_expert != "shared":
        lineage = manifest.get("lineage")
        if not isinstance(lineage, Mapping):
            raise ValueError("specialist-active realization lacks v4 lineage")
        parent_manifest = Path(parent_manifest).resolve()
        root_manifest = Path(root_manifest).resolve()
        if lineage.get("parent_checkpoint_sha256") != _sha256(parent_manifest):
            raise ValueError("specialist lineage parent checkpoint hash does not match external manifest")
        if lineage.get("root_genesis_checkpoint_sha256") != _sha256(root_manifest):
            raise ValueError("specialist lineage root checkpoint hash does not match external manifest")
        external_manifests: dict[str, dict[str, Any]] = {}
        for external_manifest, label in ((parent_manifest, "parent"), (root_manifest, "root")):
            external = _load_json(external_manifest)
            external_active = external.get("active_expert_ids")
            if not isinstance(external_active, list) or len(external_active) != 1:
                raise ValueError(f"external {label} manifest lacks one active expert")
            external_manifests[label] = _inspect_realization(external_manifest, active_expert=external_active[0], shape=shape)
        parent_external, root_external = external_manifests["parent"], external_manifests["root"]
        parent_lineage = parent_external.get("lineage")
        if parent_external.get("schema_version") == "ember-sparse-checkpoint-v3":
            if _sha256(parent_manifest) != _sha256(root_manifest):
                raise ValueError("first specialist successor requires matching external parent and root")
            parent_history: list[str] = []
        else:
            if not isinstance(parent_lineage, Mapping) or parent_lineage.get("root_genesis_checkpoint_sha256") != _sha256(root_manifest):
                raise ValueError("external parent does not bind the supplied immutable root")
            parent_history = parent_lineage.get("trained_expert_ids")
            if not isinstance(parent_history, list):
                raise ValueError("external parent has invalid trained expert history")
        if any(name not in EXPERT_NAMES for name in parent_history) or len(set(parent_history)) != len(parent_history):
            raise ValueError("external parent has invalid trained expert history")
        expected_history = [*parent_history, *([] if active_expert in parent_history else [active_expert])]
        episode = lineage.get("episode")
        receipt_fields = {"schema_version", "result", "capability", "data_manifest_sha256", "tokenizer_sha256", "verifier_sha256", "data_class", "record_count", "token_count", "source_manifest_sha256", "records_artifact_sha256", "semantic_checks"}
        capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
        if (not isinstance(episode, Mapping) or set(episode) != {"active_expert", "data_verification_receipt", "data_verification_receipt_sha256"}
                or episode.get("active_expert") != active_expert or not isinstance(episode.get("data_verification_receipt"), Mapping)):
            raise ValueError("specialist v4 lineage lacks a closed active episode")
        verification = episode["data_verification_receipt"]
        if (set(verification) != receipt_fields or verification.get("schema_version") != "ember-training-data-verification-v1"
                or verification.get("result") != "VERIFIED" or verification.get("data_class") != "SEMANTIC_PRETRAINING"
                or capability_experts.get(verification.get("capability")) != active_expert):
            raise ValueError("specialist v4 lineage has an invalid data verification receipt")
        canonical = hashlib.sha256(json.dumps(dict(verification), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if episode.get("data_verification_receipt_sha256") != canonical:
            raise ValueError("specialist v4 lineage data verification receipt hash does not match")
        candidate_parameters = manifest.get("expert_parameter_sha256")
        parent_parameters = parent_external.get("expert_parameter_sha256", parent_external.get("expert_genesis_sha256"))
        root_parameters = root_external.get("expert_parameter_sha256", root_external.get("expert_genesis_sha256"))
        candidate_files = manifest.get("expert_checkpoint_sha256")
        parent_files = parent_external.get("expert_checkpoint_sha256")
        history = lineage.get("trained_expert_ids")
        if (not isinstance(candidate_parameters, dict) or set(candidate_parameters) != set(EXPERT_NAMES)
                or not isinstance(parent_parameters, dict) or set(parent_parameters) != set(EXPERT_NAMES)
                or not isinstance(root_parameters, dict) or set(root_parameters) != set(EXPERT_NAMES)
                or not isinstance(candidate_files, dict) or not isinstance(parent_files, dict)
                or history != expected_history):
            raise ValueError("specialist v4 lineage lacks closed expert accretion fields")
        for name in EXPERT_NAMES:
            _sha256_value(candidate_parameters[name], label=f"candidate {name} parameter hash")
        if candidate_parameters[active_expert] == parent_parameters[active_expert]:
            raise ValueError("active expert parameter content does not differ from parent")
        for name in EXPERT_NAMES:
            if name == active_expert:
                continue
            if candidate_files.get(name) != parent_files.get(name):
                raise ValueError(f"inactive expert file does not match parent: {name}")
            if candidate_parameters[name] != parent_parameters[name]:
                raise ValueError(f"inactive expert parameter content does not match parent: {name}")
            if name not in history and candidate_parameters[name] != root_parameters[name]:
                raise ValueError(f"untrained expert parameter content does not match root: {name}")
    config_sha256 = _sha256(model_config)
    if manifest.get("model_config_sha256") != config_sha256:
        raise ValueError("checkpoint model-config hash mismatch")
    return {
        "result": "MEASURED",
        "model_config_sha256": config_sha256,
        "subject_checkpoint_sha256": _sha256(checkpoint_manifest),
        "architecture_revision": ARCHITECTURE_REVISION,
        "counter_sha256": _sha256(Path(__file__)),
        **_counts(shape, active_expert=active_expert),
        "active_expert_ids": [active_expert],
        "expert_genesis_sha256": dict(manifest["expert_genesis_sha256"]),
    }


def measure_parameter_counts(model: Any) -> dict[str, Any]:
    """Measure total allocated capacity and one active episode path in-process."""

    total = model.count_unique_trainable_parameters(include_frozen=True)
    active = model.count_unique_trainable_parameters()
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
        "active_expert_ids": [model.active_expert],
    }


def write_parameter_receipt(
    model: Any,
    config_path: Path,
    checkpoint_manifest_path: Path,
    expert_genesis_sha256: dict[str, str],
) -> dict[str, Any]:
    """Emit an in-process receipt; production must also execute this file under -I."""

    counts = measure_parameter_counts(model)
    return {
        "schema_version": "ember-sparse-parameter-receipt-v1",
        "result": "MEASURED",
        "model_config_sha256": _sha256(config_path),
        "counter_sha256": _sha256(Path(__file__)),
        "subject_checkpoint_sha256": _sha256(checkpoint_manifest_path),
        "architecture_revision": ARCHITECTURE_REVISION,
        **counts,
        "expert_genesis_sha256": dict(expert_genesis_sha256),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a sparse checkpoint realization and emit its measured capacity.")
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--checkpoint-manifest", type=Path, required=True)
    parser.add_argument("--active-expert", required=True)
    parser.add_argument("--parent-manifest", type=Path)
    parser.add_argument("--root-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(execute_counter(
            model_config=args.model_config,
            checkpoint_manifest=args.checkpoint_manifest,
            active_expert=args.active_expert,
            parent_manifest=args.parent_manifest,
            root_manifest=args.root_manifest,
        ), sort_keys=True))
    except Exception as error:
        print(f"parameter realization failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
