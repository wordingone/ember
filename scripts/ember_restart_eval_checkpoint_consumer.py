#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed structural verifier for corrected owned v3 sparse checkpoints."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


EXPERTS = ("vision", "audio", "reasoning", "tool")
SHARDS = {"shared.pt": "shared_model_and_optimizer", "replay-state.pt": "replay_state", **{f"expert-{name}.pt": f"expert_{name}" for name in EXPERTS}}
MANIFEST_FIELDS = {"schema_version", "launch_seed", "rng_state_sha256", "data_cursor", "model_config_sha256", "contract_sha256", "active_expert_ids", "expert_genesis_sha256", "expert_checkpoint_sha256", "shared_optimizer_shard_sha256", "optimizer_contract", "optimizer_realization", "shards"}

MANIFEST_FIELDS |= {"contract_version", "architecture_revision"}
MANIFEST_FIELDS |= {"architecture"}

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _verify(manifest_path: Path, model_config: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS or manifest.get("schema_version") != "ember-sparse-checkpoint-v3":
        raise ValueError("corrected checkpoint requires closed v3 manifest")
    if manifest.get("contract_version") != 3 or manifest.get("architecture_revision") != "ember-sparse-3b-v2":
        raise ValueError("corrected checkpoint central architecture contract mismatch")
    expected_architecture={"revision":"ember-sparse-3b-v2","allocated_parameters":3839161856,"unique_parameters":3839161856,"trainable_parameters":3839161856,"served_parameters":3839161856,"active_parameters":1725232640,"episode_trainable_parameters":1725232640,"shared_text_ffn":"always_active_SwiGLU_4H"}
    if manifest.get("architecture") != expected_architecture:
        raise ValueError("corrected checkpoint central architecture evidence mismatch")

    if not isinstance(manifest["launch_seed"], int) or manifest["launch_seed"] < 0:
        raise ValueError("checkpoint launch seed is invalid")
    rng = manifest["rng_state_sha256"]
    if not isinstance(rng, dict) or set(rng) != {"cpu", "cuda"} or not all(_digest(value) for value in rng.values()):
        raise ValueError("checkpoint replay RNG identity is invalid")
    cursor = manifest["data_cursor"]
    if not isinstance(cursor, dict) or not {"shard", "record_index", "global_step", "tokens_seen"}.issubset(cursor) or not isinstance(cursor["shard"], str) or not cursor["shard"] or any(not isinstance(cursor[field], int) or cursor[field] < 0 for field in ("record_index", "global_step", "tokens_seen")):
        raise ValueError("checkpoint replay cursor identity is invalid")
    if not all(_digest(manifest[field]) for field in ("model_config_sha256", "contract_sha256", "shared_optimizer_shard_sha256")):
        raise ValueError("checkpoint top-level identity is invalid")
    if _sha256(model_config) != manifest["model_config_sha256"]:
        raise ValueError("checkpoint model config hash mismatch")
    config = json.loads(model_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("training"), dict):
        raise ValueError("checkpoint model config training contract is invalid")
    active = manifest["active_expert_ids"]
    if not isinstance(active, list) or len(active) != 1 or active[0] not in EXPERTS:
        raise ValueError("checkpoint active expert identity is invalid")
    records: dict[str, dict[str, object]] = {}
    if not isinstance(manifest["shards"], list) or len(manifest["shards"]) != len(SHARDS):
        raise ValueError("checkpoint v3 shard set is incomplete")
    for record in manifest["shards"]:
        if not isinstance(record, dict) or set(record) != {"path", "role", "bytes", "sha256"}:
            raise ValueError("checkpoint shard schema mismatch")
        path, role, size, digest = record["path"], record["role"], record["bytes"], record["sha256"]
        if path not in SHARDS or role != SHARDS[path] or path in records or not isinstance(size, int) or size <= 0 or not _digest(digest):
            raise ValueError("checkpoint v3 shard mapping is invalid")
        shard = manifest_path.parent / path
        if not shard.is_file() or shard.stat().st_size != size or _sha256(shard) != digest:
            raise ValueError(f"checkpoint shard integrity mismatch: {path}")
        records[path] = record
    if set(records) != set(SHARDS):
        raise ValueError("checkpoint v3 shard paths are incomplete")
    if manifest["shared_optimizer_shard_sha256"] != records["shared.pt"]["sha256"]:
        raise ValueError("checkpoint shared optimizer shard binding mismatch")
    for field in ("expert_genesis_sha256", "expert_checkpoint_sha256"):
        mapping = manifest[field]
        if not isinstance(mapping, dict) or set(mapping) != set(EXPERTS) or not all(_digest(value) for value in mapping.values()) or (field == "expert_genesis_sha256" and len(set(mapping.values())) != len(EXPERTS)):
            raise ValueError(f"checkpoint {field} mapping is invalid")
    for expert in EXPERTS:
        if manifest["expert_checkpoint_sha256"][expert] != records[f"expert-{expert}.pt"]["sha256"]:
            raise ValueError(f"checkpoint expert shard binding mismatch: {expert}")
    for expert in EXPERTS:
        genesis = manifest_path.parent / "genesis" / f"{expert}.json"
        if not genesis.is_file() or _sha256(genesis) != manifest["expert_genesis_sha256"][expert]:
            raise ValueError(f"checkpoint expert genesis evidence mismatch: {expert}")
        evidence = json.loads(genesis.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict) or evidence != {"schema_version": "ember-expert-genesis-v1", "expert": expert}:
            raise ValueError(f"checkpoint expert genesis evidence schema mismatch: {expert}")

    contract = manifest["optimizer_contract"]
    if not isinstance(contract, dict) or set(contract) != {"name", "implementation", "hyperparameters", "state_format"} or not all(isinstance(contract[field], str) and contract[field] for field in ("name", "implementation", "state_format")) or not isinstance(contract["hyperparameters"], dict) or not contract["hyperparameters"]:
        raise ValueError("checkpoint optimizer contract is invalid")
    if config["training"].get("optimizer") != contract:
        raise ValueError("checkpoint optimizer contract drifts from model config")
    realization = manifest["optimizer_realization"]
    if not isinstance(realization, dict) or set(realization) != {"implementation", "implementation_source_sha256", "state_format", "optimizer_contract_sha256"} or realization.get("implementation") != contract["implementation"] or realization.get("state_format") != contract["state_format"] or not _digest(realization.get("implementation_source_sha256")) or realization.get("optimizer_contract_sha256") != _canonical_digest(contract):
        raise ValueError("checkpoint optimizer realization is invalid")
    import torch
    replay = torch.load(manifest_path.parent / "replay-state.pt", map_location="cpu", weights_only=True)
    if not isinstance(replay, dict) or not isinstance(replay.get("rng_state"), dict) or set(replay["rng_state"]) != {"cpu", "cuda"} or replay.get("data_cursor") != cursor:
        raise ValueError("checkpoint replay payload drifts from manifest")
    for name, state in replay["rng_state"].items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1 or hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest() != rng[name]:
            raise ValueError(f"checkpoint replay RNG payload mismatch: {name}")
    shared = torch.load(manifest_path.parent / "shared.pt", map_location="cpu", weights_only=True)
    if not isinstance(shared, dict) or not isinstance(shared.get("model"), dict) or not isinstance(shared.get("optimizer"), dict) or shared.get("optimizer_contract") != contract or shared.get("optimizer_realization") != realization:
        raise ValueError("checkpoint shared optimizer payload drifts from manifest")
    for expert in EXPERTS:
        payload = torch.load(manifest_path.parent / f"expert-{expert}.pt", map_location="cpu", weights_only=True)
        state = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("expert") != expert or payload.get("genesis_sha256") != manifest["expert_genesis_sha256"][expert] or not isinstance(state, dict) or any(f".experts.{expert}." not in key for key in state):
            raise ValueError(f"checkpoint expert payload identity mismatch: {expert}")
    return {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "checkpoint_manifest_sha256": _sha256(manifest_path), "model_config_sha256": manifest["model_config_sha256"], "result": "VERIFIED_CHECKPOINT_INPUT", "shard_count": len(records)}


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--model-config", required=True, type=Path)
    verify.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        receipt = _verify(arguments.manifest, arguments.model_config)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if arguments.output.exists(): parser.error("refusing to overwrite existing output")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as handle:
        json.dump(receipt, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = handle.name
    os.replace(temporary, arguments.output)


if __name__ == "__main__":
    main()
