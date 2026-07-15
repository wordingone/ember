#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path

from ember_restart_eval_checkpoint_consumer import _verify
from ember_restart.prediction_contract import validate_predictions

EXECUTION_AUTHORITY = Path(__file__).parents[1] / "manifests" / "ember-restart-execution-authorities-v1.json"

def require_execution_authority(arguments: argparse.Namespace) -> None:
    registry = json.loads(EXECUTION_AUTHORITY.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or set(registry) != {"schema_version", "goal_id", "workstream_id", "next_executed_outcome", "authorities", "disposition"} or registry.get("schema_version") != "ember-restart-execution-authorities-v1" or registry.get("goal_id") != "EMBER-02" or registry.get("workstream_id") != "EMBER-02C" or not isinstance(registry.get("authorities"), list):
        raise ValueError("committed execution authority registry is invalid")
    if registry.get("disposition") != "EXACT_OWNED_SHARED_ROUTE_EXECUTION_AUTHORIZED":
        raise ValueError("committed execution authority disposition is not authorized")
    expected = {"model_source_sha256": sha256(arguments.model_source), "model_config_sha256": sha256(arguments.model_config), "tokenizer_sha256": sha256(arguments.tokenizer), "inference_implementation_sha256": sha256(Path(__file__))}
    for authority in registry["authorities"]:
        if isinstance(authority, dict) and authority == expected:
            return
    raise ValueError("committed execution authority does not authorize supplied source/config/tokenizer/inference bytes")
from tokenizers import Tokenizer


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

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


def execute(arguments: argparse.Namespace, checkpoint: dict[str, object], bound_inputs: dict[str, object] | None = None) -> dict[str, object]:
    import torch

    require_execution_authority(arguments)
    for path, expected, label in ((arguments.model_source, arguments.model_source_sha256, "model source"), (arguments.model_config, arguments.model_config_sha256, "model config")):
        if sha256(path) != expected:
            raise ValueError(f"{label} SHA-256 does not match its argument")
    specification = importlib.util.spec_from_file_location("ember_restart_exact_model", arguments.model_source)
    if specification is None or specification.loader is None:
        raise ValueError("model source cannot be imported")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    config = module.RestartDecoderConfig.from_contract(arguments.model_config)
    model = module.UnifiedDecoder(config, device="meta", allow_production_allocation=True)
    active_route = require_active_route(checkpoint, str((bound_inputs or {}).get("active_expert", arguments.active_expert)))
    root = arguments.checkpoint_manifest.parent
    shared = torch.load(root / "shared.pt", map_location=arguments.device, weights_only=True)
    expert = None if active_route == "shared" else torch.load(root / f"expert-{active_route}.pt", map_location=arguments.device, weights_only=True)
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
    model.load_state_dict(shared["model"], strict=False, assign=True)
    if active_route != "shared":
        model.load_state_dict(expert["model"], strict=False, assign=True)
    model.eval()
    input_token_ids = (bound_inputs or {}).get("token_ids", [arguments.input_token_id])
    if not isinstance(input_token_ids, list) or not input_token_ids or any(not isinstance(token, int) or token < 0 for token in input_token_ids) or arguments.max_new_tokens <= 0 or arguments.max_new_tokens > 32:
        raise ValueError("input token and generation limit are invalid")
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
    return {"result": "NON_CLAIM_RAW_FORWARD", "active_expert": active_route, "generated_token_ids": generated, "stop_reason": "eos" if generated[-1] == arguments.stop_token_id else "max_new_tokens", "model_source_sha256": arguments.model_source_sha256, "model_config_sha256": arguments.model_config_sha256}


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
        tokenizer = Tokenizer.from_file(str(arguments.tokenizer))
        checkpoint = _verify(arguments.checkpoint_manifest, arguments.model_config)
        if arguments.execute and any(value is None for value in (arguments.model_source, arguments.model_source_sha256, arguments.model_config, arguments.model_config_sha256, arguments.max_new_tokens)):
            raise ValueError("execution requires model/config identities, active expert, input token, and limit")
        execution = execute(arguments, checkpoint, binding) if arguments.execute else {"result": "PREFLIGHT_ONLY"}
    except Exception as error:
        parser.error(str(error))
    checkpoint_sha256 = sha256(arguments.checkpoint_manifest)
    if checkpoint_sha256 != arguments.checkpoint_sha256:
        parser.error("checkpoint manifest SHA-256 does not match --checkpoint-sha256")
    if sha256(arguments.model_config) != arguments.model_config_sha256:
        parser.error("model config SHA-256 does not match --model-config-sha256")
    if arguments.canonical_output is not None:
        required = (arguments.execute, arguments.benchmark_id, arguments.benchmark_version, arguments.benchmark_capability, arguments.split_sha256, arguments.protocol_sha256)
        if any(value is None or value is False for value in required):
            parser.error("canonical output requires execution and benchmark identities")
        generated = execution["generated_token_ids"]
        envelope = {"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": checkpoint_sha256, "model_config_sha256": arguments.model_config_sha256, "tokenizer_sha256": sha256(arguments.tokenizer), "inference_implementation_sha256": sha256(Path(__file__)), "benchmark": {"id": arguments.benchmark_id, "version": arguments.benchmark_version, "capability": arguments.benchmark_capability, "split_sha256": arguments.split_sha256, "protocol_sha256": arguments.protocol_sha256}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": arguments.max_new_tokens, "temperature": 0, "top_p": 1, "stop_token_ids": [arguments.stop_token_id]}, "rows": [{"id": binding["row_id"], "input_sha256": binding["input_sha256"], "generated_token_ids": generated, "stop_reason": "eos" if generated[-1] == arguments.stop_token_id else "max_new_tokens", "output": {"kind": "text", "text": tokenizer.decode(generated)}}]}
        validate_predictions(envelope)
        arguments.canonical_output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.canonical_output.parent, delete=False) as handle:
            json.dump(envelope, handle, sort_keys=True); handle.write("\n"); temporary_canonical = handle.name
        os.replace(temporary_canonical, arguments.canonical_output)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "checkpoint_sha256": checkpoint_sha256, "checkpoint_model_config_sha256": checkpoint["model_config_sha256"], "shard_count": checkpoint["shard_count"], "tokenizer_sha256": sha256(arguments.tokenizer), **execution}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary_output = handle.name
    os.replace(temporary_output, arguments.output)


if __name__ == "__main__":
    main()
