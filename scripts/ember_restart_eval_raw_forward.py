#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse
import hashlib
import json
import os
import sys
import tempfile
import types
from pathlib import Path

from ember_restart_eval_checkpoint_consumer import _verify
# issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/prediction_contract.py
import importlib.util as _ember_5fe35e3f50d06cc1_importlib
import sys as _ember_5fe35e3f50d06cc1_sys
from pathlib import Path as _ember_5fe35e3f50d06cc1_Path
_ember_5fe35e3f50d06cc1_path = _ember_5fe35e3f50d06cc1_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'prediction_contract.py')
if not _ember_5fe35e3f50d06cc1_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/prediction_contract.py')
_ember_5fe35e3f50d06cc1_aliases = ('_ember_issue2015_5fe35e3f50d06cc1', 'ember_restart.prediction_contract', 'prediction_contract', 'scripts.ember_restart.prediction_contract')
_ember_5fe35e3f50d06cc1_existing = []
for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
    _ember_5fe35e3f50d06cc1_candidate = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
    if _ember_5fe35e3f50d06cc1_candidate is not None and all(_ember_5fe35e3f50d06cc1_candidate is not item for item in _ember_5fe35e3f50d06cc1_existing):
        _ember_5fe35e3f50d06cc1_existing.append(_ember_5fe35e3f50d06cc1_candidate)
if len(_ember_5fe35e3f50d06cc1_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
if _ember_5fe35e3f50d06cc1_existing:
    _ember_5fe35e3f50d06cc1_module = _ember_5fe35e3f50d06cc1_existing[0]
    _ember_5fe35e3f50d06cc1_observed = getattr(_ember_5fe35e3f50d06cc1_module, '__file__', None)
    if _ember_5fe35e3f50d06cc1_observed is None or _ember_5fe35e3f50d06cc1_Path(_ember_5fe35e3f50d06cc1_observed).resolve() != _ember_5fe35e3f50d06cc1_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/prediction_contract.py')
else:
    _ember_5fe35e3f50d06cc1_spec = _ember_5fe35e3f50d06cc1_importlib.spec_from_file_location('_ember_issue2015_5fe35e3f50d06cc1', _ember_5fe35e3f50d06cc1_path)
    if _ember_5fe35e3f50d06cc1_spec is None or _ember_5fe35e3f50d06cc1_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/prediction_contract.py')
    _ember_5fe35e3f50d06cc1_module = _ember_5fe35e3f50d06cc1_importlib.module_from_spec(_ember_5fe35e3f50d06cc1_spec)
    for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
        _ember_5fe35e3f50d06cc1_prior = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
        if _ember_5fe35e3f50d06cc1_prior is not None and _ember_5fe35e3f50d06cc1_prior is not _ember_5fe35e3f50d06cc1_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
        _ember_5fe35e3f50d06cc1_sys.modules[_ember_5fe35e3f50d06cc1_alias] = _ember_5fe35e3f50d06cc1_module
    try:
        _ember_5fe35e3f50d06cc1_spec.loader.exec_module(_ember_5fe35e3f50d06cc1_module)
    except BaseException:
        for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
            if _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias) is _ember_5fe35e3f50d06cc1_module:
                _ember_5fe35e3f50d06cc1_sys.modules.pop(_ember_5fe35e3f50d06cc1_alias, None)
        raise
for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
    _ember_5fe35e3f50d06cc1_prior = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
    if _ember_5fe35e3f50d06cc1_prior is not None and _ember_5fe35e3f50d06cc1_prior is not _ember_5fe35e3f50d06cc1_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
    _ember_5fe35e3f50d06cc1_sys.modules[_ember_5fe35e3f50d06cc1_alias] = _ember_5fe35e3f50d06cc1_module
validate_predictions = getattr(_ember_5fe35e3f50d06cc1_module, 'validate_predictions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/prediction_contract.py

EXECUTION_AUTHORITY = Path(__file__).parents[1] / "manifests" / "ember-restart-execution-authorities-v1.json"

def require_execution_authority(arguments: argparse.Namespace, identities: dict[str, str] | None = None) -> dict[str, str]:
    registry, _registry_sha256, _registry_bytes = _read_json_snapshot(EXECUTION_AUTHORITY, "execution authority registry")
    if not isinstance(registry, dict) or set(registry) != {"schema_version", "goal_id", "workstream_id", "next_executed_outcome", "authorities", "disposition"} or registry.get("schema_version") != "ember-restart-execution-authorities-v1" or registry.get("goal_id") != "EMBER-02" or registry.get("workstream_id") != "EMBER-02C" or not isinstance(registry.get("authorities"), list):
        raise ValueError("committed execution authority registry is invalid")
    if registry.get("disposition") != "EXACT_OWNED_SHARED_ROUTE_EXECUTION_AUTHORIZED":
        raise ValueError("committed execution authority disposition is not authorized")
    if identities is None:
        expected = {"model_source_sha256": sha256(arguments.model_source), "model_config_sha256": sha256(arguments.model_config), "tokenizer_sha256": sha256(arguments.tokenizer), "inference_implementation_sha256": sha256(Path(__file__))}
    else:
        _implementation_bytes, implementation_sha256 = _read_snapshot(Path(__file__), "inference implementation")
        expected = {**identities, "inference_implementation_sha256": implementation_sha256}
    for authority in registry["authorities"]:
        if isinstance(authority, dict) and authority == expected:
            return expected
    raise ValueError("committed execution authority does not authorize supplied source/config/tokenizer/inference bytes")
from tokenizers import Tokenizer

EXPERTS = ("vision", "audio", "reasoning", "tool")
REALIZATION_COUNTS = {
    "allocated_parameters": 3_839_161_856,
    "unique_parameters": 3_839_161_856,
    "trainable_parameters": 3_839_161_856,
    "served_parameters": 3_839_161_856,
}
ACTIVE_COUNTS = {"shared": 1_020_589_568, **{name: 1_725_232_640 for name in EXPERTS}}
REALIZATION_RECEIPT_FIELDS = {
    "schema_version", "verification_boundary", "result", "model_config_sha256",
    "subject_checkpoint_sha256", "architecture_revision", "counter_sha256",
    *REALIZATION_COUNTS, "active_parameters", "episode_trainable_parameters",
    "active_expert_ids", "expert_genesis_sha256", "expert_parameter_sha256",
}



def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_snapshot(path: Path, label: str) -> tuple[bytes, str]:
    try:
        value = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{label} cannot be read: {error}") from error
    return value, hashlib.sha256(value).hexdigest()


def _read_json_snapshot(path: Path, label: str) -> tuple[dict[str, object], str, bytes]:
    value, digest = _read_snapshot(path, label)
    try:
        payload = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} JSON is invalid: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload, digest, value


def _digest_map(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(EXPERTS)
        and all(isinstance(digest, str) and len(digest) == 64 and set(digest) <= set("0123456789abcdef") for digest in value.values())
    )


def _trusted_counter(registry: dict[str, object], *, registry_root: Path, counter_source_path: Path, counter_sha256: str) -> bool:
    if set(registry) not in ({"schema_version", "verifiers"}, {"schema_version", "verifiers", "realization_receipts"}) or registry.get("schema_version") != "ember-trusted-verifiers-v1":
        return False
    entries = registry.get("verifiers")
    if not isinstance(entries, list) or not entries:
        return False
    resolved_counter = counter_source_path.resolve()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "evidence_classes", "criterion_ids"}:
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            continue
        candidate = (registry_root / relative).resolve()
        if (
            registry_root in candidate.parents
            and candidate == resolved_counter
            and entry.get("sha256") == counter_sha256
            and isinstance(entry.get("evidence_classes"), list)
            and "parameter_realization" in entry["evidence_classes"]
            and isinstance(entry.get("criterion_ids"), list)
            and "ember-sparse-step2-realization-v1" in entry["criterion_ids"]
        ):
            return True
    return False


def _trusted_receipt_binding(registry: dict[str, object], *, registry_root: Path, receipt_path: Path, receipt_sha256: str, subject_checkpoint_sha256: str, model_config_sha256: str, counter_sha256: str, active_expert: str) -> bool:
    bindings = registry.get("realization_receipts")
    if not isinstance(bindings, list) or not bindings:
        return False
    resolved_receipt = receipt_path.resolve()
    for entry in bindings:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "subject_checkpoint_sha256", "model_config_sha256", "counter_sha256", "active_expert"}:
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            continue
        candidate = (registry_root / relative).resolve()
        if (
            registry_root in candidate.parents
            and candidate == resolved_receipt
            and entry.get("sha256") == receipt_sha256
            and entry.get("subject_checkpoint_sha256") == subject_checkpoint_sha256
            and entry.get("model_config_sha256") == model_config_sha256
            and entry.get("counter_sha256") == counter_sha256
            and entry.get("active_expert") == active_expert
        ):
            return True
    return False


def load_verified_runtime_contract(*, manifest_path: Path, model_config_path: Path, parameter_receipt_path: Path, counter_source_path: Path, trusted_verifier_registry_path: Path, requested_route: str) -> dict[str, object]:
    """Bind runtime execution to one independently measured sparse realization."""

    if requested_route not in ("shared", *EXPERTS):
        raise ValueError("runtime route is invalid")
    manifest, manifest_sha256, manifest_bytes = _read_json_snapshot(manifest_path, "checkpoint manifest")
    config, config_sha256, config_bytes = _read_json_snapshot(model_config_path, "model config")
    receipt, receipt_sha256, receipt_bytes = _read_json_snapshot(parameter_receipt_path, "parameter receipt")
    registry, registry_sha256, registry_bytes = _read_json_snapshot(trusted_verifier_registry_path, "trusted verifier registry")
    counter_bytes, counter_sha256 = _read_snapshot(counter_source_path, "parameter counter source")

    if set(receipt) != REALIZATION_RECEIPT_FIELDS:
        raise ValueError("runtime receipt schema is not closed")
    if (
        receipt.get("schema_version") != "ember-sparse-realization-receipt-v1"
        or receipt.get("verification_boundary") != "VERIFIED_MEASURED"
        or receipt.get("result") != "MEASURED"
    ):
        raise ValueError("runtime receipt is not verified measured evidence")
    if receipt.get("subject_checkpoint_sha256") != manifest_sha256:
        raise ValueError("runtime receipt checkpoint subject mismatch")
    if receipt.get("model_config_sha256") != config_sha256 or manifest.get("model_config_sha256") != config_sha256:
        raise ValueError("runtime receipt or checkpoint config mismatch")
    if receipt.get("architecture_revision") != "ember-sparse-3b-v2" or manifest.get("architecture_revision") != "ember-sparse-3b-v2" or config.get("architecture_revision") != "ember-sparse-3b-v2":
        raise ValueError("runtime architecture revision mismatch")
    if receipt.get("counter_sha256") != counter_sha256:
        raise ValueError("runtime receipt counter mismatch")
    if not _trusted_counter(registry, registry_root=trusted_verifier_registry_path.resolve().parent, counter_source_path=counter_source_path, counter_sha256=counter_sha256):
        raise ValueError("runtime lacks a trusted parameter-realization counter")
    expected_route = [requested_route]
    if receipt.get("active_expert_ids") != expected_route or manifest.get("active_expert_ids") != expected_route:
        raise ValueError("runtime receipt route mismatch")
    expected_counts = {
        **REALIZATION_COUNTS,
        "active_parameters": ACTIVE_COUNTS[requested_route],
        "episode_trainable_parameters": ACTIVE_COUNTS[requested_route],
    }
    if any(receipt.get(field) != expected for field, expected in expected_counts.items()):
        raise ValueError("runtime receipt parameter count mismatch")
    genesis = manifest.get("expert_genesis_sha256")
    parameters = manifest.get("expert_parameter_sha256", genesis)
    if not _digest_map(genesis) or receipt.get("expert_genesis_sha256") != genesis:
        raise ValueError("runtime receipt expert genesis mismatch")
    if not _digest_map(parameters) or receipt.get("expert_parameter_sha256") != parameters:
        raise ValueError("runtime receipt expert parameter mismatch")

    records = manifest.get("shards")
    if not isinstance(records, list):
        raise ValueError("runtime checkpoint shard records are invalid")
    by_path: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "role", "bytes", "sha256"}:
            raise ValueError("runtime checkpoint shard record schema is invalid")
        relative = record.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts or relative in by_path:
            raise ValueError("runtime checkpoint shard path is invalid")
        by_path[relative] = record
    required_names = ["shared.pt"] if requested_route == "shared" else ["shared.pt", f"expert-{requested_route}.pt"]
    required_shards: dict[str, str] = {}
    for relative in required_names:
        record = by_path.get(relative)
        if record is None or not isinstance(record.get("sha256"), str):
            raise ValueError(f"runtime checkpoint lacks required shard: {relative}")
        required_shards[relative] = str(record["sha256"])
    if requested_route != "shared" and manifest.get("expert_checkpoint_sha256", {}).get(requested_route) != required_shards[f"expert-{requested_route}.pt"]:
        raise ValueError("runtime active expert shard is not checkpoint-bound")
    if not _trusted_receipt_binding(
        registry,
        registry_root=trusted_verifier_registry_path.resolve().parent,
        receipt_path=parameter_receipt_path,
        receipt_sha256=receipt_sha256,
        subject_checkpoint_sha256=manifest_sha256,
        model_config_sha256=config_sha256,
        counter_sha256=counter_sha256,
        active_expert=requested_route,
    ):
        raise ValueError("runtime lacks an exact content-addressed realization receipt binding")

    return {
        "checkpoint_manifest": manifest,
        "checkpoint_manifest_bytes": manifest_bytes,
        "checkpoint_manifest_sha256": manifest_sha256,
        "model_config": config,
        "model_config_bytes": config_bytes,
        "model_config_sha256": config_sha256,
        "parameter_receipt": receipt,
        "parameter_receipt_bytes": receipt_bytes,
        "parameter_receipt_sha256": receipt_sha256,
        "counter_source_bytes": counter_bytes,
        "counter_sha256": counter_sha256,
        "trusted_verifier_registry_bytes": registry_bytes,
        "trusted_verifier_registry_sha256": registry_sha256,
        "active_expert_ids": expected_route,
        "required_shards": required_shards,
        "shard_count": len(by_path),
    }


def hash_and_load_torch(torch_module, path: Path, expected_sha256: str, *, device: str):
    """Hash and deserialize one required shard through the same open handle."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError(f"runtime checkpoint shard hash mismatch: {path.name}")
        handle.seek(0)
        return torch_module.load(handle, map_location="cpu", weights_only=True)


def canonicalize_tied_embedding_state(
    torch_module,
    state: dict[str, object],
    *,
    tied_embeddings: bool,
) -> dict[str, object]:
    """Validate duplicate checkpoint copies and restore one tied tensor identity."""

    canonical = dict(state)
    if not tied_embeddings:
        return canonical
    embedding_key, head_key = "token_embedding.weight", "lm_head.weight"
    if embedding_key not in canonical or head_key not in canonical:
        raise ValueError("tied embedding checkpoint tensors are missing")
    embedding, head = canonical[embedding_key], canonical[head_key]
    if (
        tuple(embedding.shape) != tuple(head.shape)
        or embedding.dtype != head.dtype
        or not bool(torch_module.equal(embedding, head))
    ):
        raise ValueError("tied embedding checkpoint tensors differ")
    canonical[head_key] = embedding
    return canonical


def materialize_state_map(state: dict[str, object], device: str) -> dict[str, object]:
    """Move each unique validated model tensor onto the execution device once."""

    materialized: dict[str, object] = {}
    by_identity: dict[int, object] = {}
    for key, value in state.items():
        identity = id(value)
        if identity not in by_identity:
            by_identity[identity] = value.to(device=device)
        materialized[key] = by_identity[identity]
    return materialized


def rebind_tied_embeddings(model, *, tied_embeddings: bool) -> None:
    """Preserve the architecture's single embedding/output-head parameter."""

    if not tied_embeddings:
        return
    if not hasattr(model, "token_embedding") or not hasattr(model, "lm_head"):
        raise ValueError("tied embedding modules are missing")
    model.lm_head.weight = model.token_embedding.weight
    if model.lm_head.weight is not model.token_embedding.weight:
        raise ValueError("runtime failed to preserve tied embeddings")


def _load_model_module(source_bytes: bytes, source_path: Path):
    module_name = "ember_restart_exact_model"
    module = types.ModuleType(module_name)
    module.__file__ = str(source_path)
    sys.modules[module_name] = module
    try:
        exec(compile(source_bytes, str(source_path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _config_from_payload(module, contract: dict[str, object]):
    factory = getattr(module.RestartDecoderConfig, "from_contract_payload", None)
    if callable(factory):
        return factory(contract)
    if contract.get("architecture_revision") != "ember-sparse-3b-v2":
        raise ValueError("production contract must declare ember-sparse-3b-v2")
    model = contract.get("model")
    training = contract.get("training")
    if not isinstance(model, dict) or not isinstance(training, dict):
        raise ValueError("production model config schema is invalid")
    image, audio, routing = model.get("image_projection"), model.get("audio_projection"), model.get("expert_routing")
    if not isinstance(image, dict) or not isinstance(audio, dict) or not isinstance(routing, dict):
        raise ValueError("production modality/routing config is invalid")
    config = module.RestartDecoderConfig(
        hidden_size=int(model["hidden_size"]),
        layers=int(model["layers"]),
        attention_heads=int(model["attention_heads"]),
        vocab_size=int(model["vocab_size"]),
        image_input_shape=tuple(int(value) for value in image["input_shape"]),
        audio_frame_samples=int(audio["frame_samples"]),
        gradient_checkpointing=bool(training["gradient_checkpointing"]),
        tied_embeddings=bool(model["tied_embeddings"]),
        expert_names=tuple(routing["expert_names"]),
        default_active_expert=str(routing["default_active_expert"]),
        contract_name=str(contract["contract_name"]),
        contract_version=int(contract["contract_version"]),
        production=True,
        declared_total_unique_trainable_parameters=int(model["total_unique_trainable_parameters"]),
        lineage=dict(contract["lineage"]),
    )
    if config.declared_total_unique_trainable_parameters != config.structural_parameter_count():
        raise ValueError("production contract total does not match the sparse architecture")
    return config

def tied_embeddings_from_contract(config, contract: dict[str, object]) -> bool:
    """Resolve the committed tying declaration and reject model/config drift."""

    model = contract.get("model")
    if isinstance(model, dict) and "tied_embeddings" in model:
        declared = model["tied_embeddings"]
        if not isinstance(declared, bool):
            raise ValueError("production tied-embedding contract must be boolean")
        runtime = getattr(config, "tied_embeddings", declared)
        if not isinstance(runtime, bool) or runtime != declared:
            raise ValueError("runtime tied-embedding config does not match its contract")
        return declared
    return bool(getattr(config, "tied_embeddings", False))


def parameter_dtype_from_contract(torch_module, contract: dict[str, object]):
    training = contract.get("training")
    memory = training.get("memory") if isinstance(training, dict) else None
    if not isinstance(memory, dict) or memory.get("parameter_dtype") != "bfloat16" or memory.get("parameter_bytes") != 2:
        raise ValueError("production parameter dtype contract must be two-byte bfloat16")
    return torch_module.bfloat16


def construct_runtime_model(torch_module, model_module, config, contract: dict[str, object]):
    parameter_dtype = parameter_dtype_from_contract(torch_module, contract)
    previous_dtype = torch_module.get_default_dtype()
    try:
        torch_module.set_default_dtype(parameter_dtype)
        return model_module.UnifiedDecoder(config, device="meta", allow_production_allocation=True)
    finally:
        torch_module.set_default_dtype(previous_dtype)


def load_owned_prompt(path: Path) -> dict[str, object]:
    prompt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(prompt, dict) or "target_ids" in prompt:
        raise ValueError("owned inference prompt rejects target_ids")
    if set(prompt) != {"schema_version", "id", "active_expert", "token_ids"} or prompt.get("schema_version") != "ember-owned-inference-prompt-v1":
        raise ValueError("owned inference prompt schema is invalid")
    if not isinstance(prompt["id"], str) or not prompt["id"] or prompt["active_expert"] not in ("shared", "vision", "audio", "reasoning", "tool"):
        raise ValueError("owned inference prompt identity is invalid")
    tokens = prompt["token_ids"]
    if not isinstance(tokens, list) or not tokens or any(not isinstance(token, int) or isinstance(token, bool) or token < 0 for token in tokens):
        raise ValueError("owned inference prompt token ids are invalid")
    return {"id": prompt["id"], "active_expert": prompt["active_expert"], "token_ids": prompt["token_ids"]}


def load_canonical_prompt_binding(prompt_path: Path, split_path: Path, expected_split_sha256: str, benchmark_id: str, benchmark_version: str) -> dict[str, object]:
    prompt_bytes, split_bytes = prompt_path.read_bytes(), split_path.read_bytes()
    if hashlib.sha256(split_bytes).hexdigest() != expected_split_sha256:
        raise ValueError("frozen prompt split digest mismatch")
    try:
        prompt, split = json.loads(prompt_bytes), json.loads(split_bytes)
    except json.JSONDecodeError as error:
        raise ValueError(f"prompt binding JSON is invalid: {error}") from error
    if not isinstance(prompt, dict) or prompt.get("schema_version") != "ember-owned-inference-prompt-v1":
        raise ValueError("prompt schema is invalid")
    if not isinstance(split, dict) or split.get("schema_version") != "ember-owned-frozen-local-text-split-v1" or split.get("benchmark_id") != benchmark_id or split.get("benchmark_version") != benchmark_version or split.get("target_training_access") != "FORBIDDEN":
        raise ValueError("frozen prompt benchmark identity is invalid")
    loaded = load_owned_prompt_bytes(prompt)
    rows = split.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("frozen prompt row is invalid")
    row, prompt_sha = rows[0], hashlib.sha256(prompt_bytes).hexdigest()
    if row.get("id") != loaded["id"]: raise ValueError("frozen prompt row mismatch")
    if row.get("prompt_sha256") != prompt_sha: raise ValueError("frozen prompt hash mismatch")
    if row.get("active_expert") != loaded["active_expert"]: raise ValueError("frozen prompt route mismatch")
    token_sha = hashlib.sha256(json.dumps(loaded["token_ids"], separators=(",", ":")).encode()).hexdigest()
    if row.get("token_ids_sha256") != token_sha: raise ValueError("frozen prompt token mismatch")
    return {"row_id": loaded["id"], "active_expert": loaded["active_expert"], "token_ids": loaded["token_ids"], "input_sha256": prompt_sha}


def load_owned_prompt_bytes(prompt: object) -> dict[str, object]:
    if not isinstance(prompt, dict) or "target_ids" in prompt:
        raise ValueError("owned inference prompt rejects target_ids")
    if set(prompt) != {"schema_version", "id", "active_expert", "token_ids"} or prompt.get("schema_version") != "ember-owned-inference-prompt-v1":
        raise ValueError("owned inference prompt schema is invalid")
    if not isinstance(prompt["id"], str) or not prompt["id"] or prompt["active_expert"] not in ("shared", "vision", "audio", "reasoning", "tool"):
        raise ValueError("owned inference prompt identity is invalid")
    tokens = prompt["token_ids"]
    if not isinstance(tokens, list) or not tokens or any(not isinstance(token, int) or isinstance(token, bool) or token < 0 for token in tokens):
        raise ValueError("owned inference prompt token ids are invalid")
    return {"id": prompt["id"], "active_expert": prompt["active_expert"], "token_ids": tokens}

def validate_state_map(state: object, expected: dict[str, object], label: str) -> None:
    if not isinstance(state, dict):
        raise ValueError(f"{label} state is not a mapping")
    actual_keys, expected_keys = set(state), set(expected)
    if actual_keys - expected_keys:
        raise ValueError(f"{label} state has unexpected keys")
    if expected_keys - actual_keys:
        raise ValueError(f"{label} state has missing keys")
    for key in expected_keys:
        actual, reference = state[key], expected[key]
        if not hasattr(actual, "shape") or not hasattr(reference, "shape") or tuple(actual.shape) != tuple(reference.shape):
            raise ValueError(f"{label} state shape mismatch: {key}")
        if actual.dtype != reference.dtype:
            raise ValueError(f"{label} state dtype mismatch: {key}")


def require_active_route(checkpoint: dict[str, object], requested: str) -> str:
    active = checkpoint.get("active_expert_ids")
    if not isinstance(active, list) or len(active) != 1 or active[0] not in ("shared", "vision", "audio", "reasoning", "tool"):
        raise ValueError("verified checkpoint active route is invalid")
    if requested != active[0]:
        raise ValueError("active route does not match verified checkpoint manifest")
    return requested


def execute(arguments: argparse.Namespace, checkpoint: dict[str, object], bound_inputs: dict[str, object] | None = None, *, model_source_bytes: bytes | None = None) -> dict[str, object]:
    import torch

    if model_source_bytes is None:
        raise ValueError("verified execution requires captured model source bytes")
    source_sha256 = hashlib.sha256(model_source_bytes).hexdigest()
    if source_sha256 != arguments.model_source_sha256:
        raise ValueError("model source SHA-256 does not match its argument")
    identities = {
        "model_source_sha256": source_sha256,
        "model_config_sha256": str(checkpoint["model_config_sha256"]),
        "tokenizer_sha256": str(checkpoint["tokenizer_sha256"]),
        "checkpoint_manifest_sha256": str(checkpoint["checkpoint_manifest_sha256"]),
        "parameter_receipt_sha256": str(checkpoint["parameter_receipt_sha256"]),
        "parameter_counter_sha256": str(checkpoint["counter_sha256"]),
        "trusted_verifier_registry_sha256": str(checkpoint["trusted_verifier_registry_sha256"]),
    }
    authority = require_execution_authority(arguments, identities)
    module = _load_model_module(model_source_bytes, arguments.model_source)
    config = _config_from_payload(module, checkpoint["model_config"])
    input_token_ids = (bound_inputs or {}).get("token_ids", [arguments.input_token_id])
    if not isinstance(input_token_ids, list) or not input_token_ids or any(not isinstance(token, int) or isinstance(token, bool) or token < 0 for token in input_token_ids) or arguments.max_new_tokens <= 0 or arguments.max_new_tokens > 32:
        raise ValueError("input token and generation limit are invalid")
    if any(token >= config.vocab_size for token in input_token_ids):
        raise ValueError("input token is outside model vocabulary")
    model = construct_runtime_model(torch, module, config, checkpoint["model_config"])
    tied_embeddings = tied_embeddings_from_contract(config, checkpoint["model_config"])
    active_route = require_active_route(checkpoint, str((bound_inputs or {}).get("active_expert", arguments.active_expert)))
    root = arguments.checkpoint_manifest.parent
    required_shards = checkpoint["required_shards"]
    shared = hash_and_load_torch(torch, root / "shared.pt", required_shards["shared.pt"], device=arguments.device)
    expert = None if active_route == "shared" else hash_and_load_torch(torch, root / f"expert-{active_route}.pt", required_shards[f"expert-{active_route}.pt"], device=arguments.device)
    if not isinstance(shared, dict) or not isinstance(shared.get("model"), dict):
        raise ValueError("shared checkpoint lacks a model state")
    if active_route != "shared" and (not isinstance(expert, dict) or expert.get("expert") != active_route or not isinstance(expert.get("model"), dict)):
        raise ValueError("selected expert checkpoint is invalid")
    expected = model.state_dict()
    shared_expected = {key: value for key, value in expected.items() if ".experts." not in key}
    expert_marker = f".experts.{active_route}."
    expert_expected = {key: value for key, value in expected.items() if expert_marker in key}
    validate_state_map(shared["model"], shared_expected, "shared")
    if active_route != "shared":
        validate_state_map(expert["model"], expert_expected, f"expert {active_route}")
    if active_route != "shared" and not expert_expected:
        raise ValueError("selected expert has no expected model parameters")
    shared_model_state = canonicalize_tied_embedding_state(
        torch,
        shared["model"],
        tied_embeddings=tied_embeddings,
    )
    shared_state = materialize_state_map(shared_model_state, arguments.device)
    expert_state = None if active_route == "shared" else materialize_state_map(expert["model"], arguments.device)
    del shared, expert
    model.load_state_dict(shared_state, strict=False, assign=True)
    if active_route != "shared":
        model.load_state_dict(expert_state, strict=False, assign=True)
    rebind_tied_embeddings(model, tied_embeddings=tied_embeddings)
    model.eval()
    tokens = torch.tensor([input_token_ids], device=arguments.device, dtype=torch.long)
    generated: list[int] = []
    with torch.no_grad():
        for _ in range(arguments.max_new_tokens):
            logits = model(tokens, active_expert=active_route)
            token = int(torch.argmax(logits[:, -1, :], dim=-1).item())
            generated.append(token)
            if token == arguments.stop_token_id:
                break
            tokens = torch.cat((tokens, torch.tensor([[token]], device=arguments.device)), dim=1)
    return {"result": "NON_CLAIM_RAW_FORWARD", "active_expert": active_route, "generated_token_ids": generated, "stop_reason": "eos" if generated[-1] == arguments.stop_token_id else "max_new_tokens", "model_source_sha256": source_sha256, "model_config_sha256": checkpoint["model_config_sha256"], "tokenizer_sha256": checkpoint["tokenizer_sha256"], "inference_implementation_sha256": authority["inference_implementation_sha256"], "parameter_receipt_sha256": checkpoint["parameter_receipt_sha256"], "parameter_counter_sha256": checkpoint["counter_sha256"], "trusted_verifier_registry_sha256": checkpoint["trusted_verifier_registry_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--model-source", type=Path)
    parser.add_argument("--model-source-sha256")
    parser.add_argument("--model-config", required=True, type=Path)
    parser.add_argument("--model-config-sha256", required=True)
    parser.add_argument("--active-expert", choices=("shared", "vision", "audio", "reasoning", "tool"))
    parser.add_argument("--input-token-id", type=int)
    parser.add_argument("--max-new-tokens", type=int)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--canonical-output", type=Path)
    parser.add_argument("--benchmark-id")
    parser.add_argument("--benchmark-version")
    parser.add_argument("--benchmark-capability", choices=("text", "image", "audio", "reasoning", "tool"))
    parser.add_argument("--split-sha256")
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--row-id")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--frozen-split", type=Path)
    parser.add_argument("--parameter-receipt", type=Path)
    parser.add_argument("--counter-source", type=Path)
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--stop-token-id", type=int, default=2)
    arguments = parser.parse_args()
    if arguments.benchmark_capability not in (None, "text"):
        parser.error("generic raw forward accepts only text capability")
    if arguments.output.exists(): parser.error("refusing to overwrite existing output")
    if arguments.canonical_output is not None and arguments.canonical_output.exists(): parser.error("refusing to overwrite existing canonical output")
    if arguments.canonical_output is not None and arguments.canonical_output.resolve() == arguments.output.resolve(): parser.error("canonical output must differ from output")
    if arguments.canonical_output is not None and (arguments.prompt is None or arguments.frozen_split is None): parser.error("canonical output requires owned prompt and frozen split")
    if arguments.canonical_output is not None and any(value is not None for value in (arguments.input_token_id, arguments.active_expert, arguments.row_id)): parser.error("canonical output rejects detached manual prompt fields")
    try:
        binding = load_canonical_prompt_binding(arguments.prompt, arguments.frozen_split, arguments.split_sha256, arguments.benchmark_id, arguments.benchmark_version) if arguments.canonical_output is not None else None
        if arguments.execute and any(value is None for value in (arguments.model_source, arguments.model_source_sha256, arguments.model_config, arguments.model_config_sha256, arguments.max_new_tokens)):
            raise ValueError("execution requires model/config identities, active expert, input token, and limit")
        tokenizer_bytes, tokenizer_sha256 = _read_snapshot(arguments.tokenizer, "tokenizer")
        tokenizer = Tokenizer.from_str(tokenizer_bytes.decode("utf-8"))
        if arguments.execute:
            if any(value is None for value in (arguments.parameter_receipt, arguments.counter_source, arguments.trusted_verifier_registry)):
                raise ValueError("verified execution requires parameter receipt, counter source, and trusted verifier registry")
            requested_route = str((binding or {}).get("active_expert", arguments.active_expert))
            checkpoint = load_verified_runtime_contract(
                manifest_path=arguments.checkpoint_manifest,
                model_config_path=arguments.model_config,
                parameter_receipt_path=arguments.parameter_receipt,
                counter_source_path=arguments.counter_source,
                trusted_verifier_registry_path=arguments.trusted_verifier_registry,
                requested_route=requested_route,
            )
            model_source_bytes, model_source_sha256 = _read_snapshot(arguments.model_source, "model source")
            if model_source_sha256 != arguments.model_source_sha256:
                raise ValueError("model source SHA-256 does not match its argument")
            if checkpoint["model_config_sha256"] != arguments.model_config_sha256:
                raise ValueError("model config SHA-256 does not match --model-config-sha256")
            if checkpoint["checkpoint_manifest_sha256"] != arguments.checkpoint_sha256:
                raise ValueError("checkpoint manifest SHA-256 does not match --checkpoint-sha256")
            checkpoint["tokenizer_sha256"] = tokenizer_sha256
            execution = execute(arguments, checkpoint, binding, model_source_bytes=model_source_bytes)
        else:
            checkpoint = _verify(arguments.checkpoint_manifest, arguments.model_config)
            execution = {"result": "PREFLIGHT_ONLY"}
    except Exception as error:
        parser.error(str(error))
    checkpoint_sha256 = str(checkpoint["checkpoint_manifest_sha256"]) if "checkpoint_manifest_sha256" in checkpoint else sha256(arguments.checkpoint_manifest)
    if checkpoint_sha256 != arguments.checkpoint_sha256:
        parser.error("checkpoint manifest SHA-256 does not match --checkpoint-sha256")
    if checkpoint["model_config_sha256"] != arguments.model_config_sha256:
        parser.error("model config SHA-256 does not match --model-config-sha256")
    if arguments.canonical_output is not None:
        required = (arguments.execute, arguments.benchmark_id, arguments.benchmark_version, arguments.benchmark_capability, arguments.split_sha256, arguments.protocol_sha256)
        if any(value is None or value is False for value in required):
            parser.error("canonical output requires execution and benchmark identities")
        generated = execution["generated_token_ids"]
        envelope = {"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": checkpoint_sha256, "model_config_sha256": arguments.model_config_sha256, "tokenizer_sha256": execution["tokenizer_sha256"], "inference_implementation_sha256": execution["inference_implementation_sha256"], "benchmark": {"id": arguments.benchmark_id, "version": arguments.benchmark_version, "capability": arguments.benchmark_capability, "split_sha256": arguments.split_sha256, "protocol_sha256": arguments.protocol_sha256}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": arguments.max_new_tokens, "temperature": 0, "top_p": 1, "stop_token_ids": [arguments.stop_token_id]}, "rows": [{"id": binding["row_id"], "input_sha256": binding["input_sha256"], "generated_token_ids": generated, "stop_reason": "eos" if generated[-1] == arguments.stop_token_id else "max_new_tokens", "output": {"kind": "text", "text": tokenizer.decode(generated)}}]}
        validate_predictions(envelope)
        arguments.canonical_output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.canonical_output.parent, delete=False) as handle:
            json.dump(envelope, handle, sort_keys=True); handle.write("\n"); temporary_canonical = handle.name
        os.replace(temporary_canonical, arguments.canonical_output)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "checkpoint_sha256": checkpoint_sha256, "checkpoint_model_config_sha256": checkpoint["model_config_sha256"], "shard_count": checkpoint["shard_count"], "tokenizer_sha256": tokenizer_sha256, **execution}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary_output = handle.name
    os.replace(temporary_output, arguments.output)


if __name__ == "__main__":
    main()
