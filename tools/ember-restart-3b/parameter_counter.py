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
ARCHITECTURE_REVISION = "ember-sparse-3b-v1"


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
            prefix + "attention.output.weight": (hidden, hidden),
            prefix + "pre_ffn_norm.weight": (hidden,),
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
    def __init__(self, size: int) -> None:
        self.size = int(size)


class _TensorMetadata:
    def __init__(self, shape: object) -> None:
        self.shape = tuple(int(value) for value in shape)


def _rebuild_tensor(storage: _StorageRef, offset: object, shape: object, stride: object, *unused: object) -> _TensorMetadata:
    return _TensorMetadata(shape)


def _rebuild_parameter(value: _TensorMetadata, *unused: object) -> _TensorMetadata:
    return value


class _CheckpointMetadataUnpickler(pickle.Unpickler):
    """Read only tensor metadata from a Torch zip checkpoint."""

    def persistent_load(self, persistent_id: object) -> _StorageRef:
        if not isinstance(persistent_id, tuple) or len(persistent_id) != 5 or persistent_id[0] != "storage":
            raise ValueError("checkpoint contains an unsupported persistent reference")
        return _StorageRef(int(persistent_id[4]))

    def find_class(self, module: str, name: str) -> object:
        if module == "collections" and name == "OrderedDict":
            from collections import OrderedDict
            return OrderedDict
        if module == "torch._utils" and name.startswith("_rebuild_tensor"):
            return _rebuild_tensor
        if module == "torch._utils" and name == "_rebuild_parameter":
            return _rebuild_parameter
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
    return manifest

def _counts(shape: Mapping[str, int]) -> dict[str, int]:
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    shared = (
        vocab * hidden
        + layers * (4 * hidden * hidden + 2 * hidden)
        + hidden
        + (48 * 48 * 3) * hidden
        + 640 * hidden
    )
    expert = layers * 12 * hidden * hidden
    total = shared + len(EXPERT_NAMES) * expert
    active = shared + expert
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
    }


def execute_counter(*, model_config: Path, checkpoint_manifest: Path, active_expert: str) -> dict[str, Any]:
    if active_expert not in EXPERT_NAMES:
        raise ValueError("active expert must be one of the four authorized banks")
    config = _load_json(model_config)
    if config.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ValueError("model config revision is not ember-sparse-3b-v1")
    shape = _model_shape(config)
    manifest = _inspect_realization(checkpoint_manifest, active_expert=active_expert, shape=shape)
    config_sha256 = _sha256(model_config)
    if manifest.get("model_config_sha256") != config_sha256:
        raise ValueError("checkpoint model-config hash mismatch")
    return {
        "result": "MEASURED",
        "model_config_sha256": config_sha256,
        "subject_checkpoint_sha256": _sha256(checkpoint_manifest),
        "architecture_revision": ARCHITECTURE_REVISION,
        "counter_sha256": _sha256(Path(__file__)),
        **_counts(shape),
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
    args = parser.parse_args(argv)
    try:
        print(json.dumps(execute_counter(
            model_config=args.model_config,
            checkpoint_manifest=args.checkpoint_manifest,
            active_expert=args.active_expert,
        ), sort_keys=True))
    except Exception as error:
        print(f"parameter realization failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())