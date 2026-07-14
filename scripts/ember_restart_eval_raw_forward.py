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
from tokenizers import Tokenizer


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(arguments: argparse.Namespace, checkpoint: dict[str, object]) -> dict[str, object]:
    import torch

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
    root = arguments.checkpoint_manifest.parent
    shared = torch.load(root / "shared.pt", map_location=arguments.device, weights_only=True)
    expert = torch.load(root / f"expert-{arguments.active_expert}.pt", map_location=arguments.device, weights_only=True)
    if not isinstance(shared, dict) or not isinstance(shared.get("model"), dict):
        raise ValueError("shared checkpoint lacks a model state")
    if not isinstance(expert, dict) or expert.get("expert") != arguments.active_expert or not isinstance(expert.get("model"), dict):
        raise ValueError("selected expert checkpoint is invalid")
    model.load_state_dict(shared["model"], strict=False, assign=True)
    model.load_state_dict(expert["model"], strict=False, assign=True)
    model.eval()
    if arguments.input_token_id < 0 or arguments.max_new_tokens <= 0 or arguments.max_new_tokens > 32:
        raise ValueError("input token and generation limit are invalid")
    tokens = torch.tensor([[arguments.input_token_id]], device=arguments.device, dtype=torch.long)
    generated: list[int] = []
    with torch.no_grad():
        for _ in range(arguments.max_new_tokens):
            logits = model(tokens, active_expert=arguments.active_expert)
            token = int(torch.argmax(logits[:, -1, :], dim=-1).item())
            generated.append(token)
            tokens = torch.cat((tokens, torch.tensor([[token]], device=arguments.device)), dim=1)
    return {"result": "NON_CLAIM_RAW_FORWARD", "active_expert": arguments.active_expert, "generated_token_ids": generated, "stop_reason": "max_new_tokens", "model_source_sha256": arguments.model_source_sha256, "model_config_sha256": arguments.model_config_sha256}


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
    parser.add_argument("--active-expert", choices=("vision", "audio", "reasoning", "tool"))
    parser.add_argument("--input-token-id", type=int)
    parser.add_argument("--max-new-tokens", type=int)
    parser.add_argument("--device", default="cuda")
    arguments = parser.parse_args()
    try:
        Tokenizer.from_file(str(arguments.tokenizer))
        checkpoint = _verify(arguments.checkpoint_manifest, arguments.model_config)
        if arguments.execute and any(value is None for value in (arguments.model_source, arguments.model_source_sha256, arguments.model_config, arguments.model_config_sha256, arguments.active_expert, arguments.input_token_id, arguments.max_new_tokens)):
            raise ValueError("execution requires model/config identities, active expert, input token, and limit")
        execution = execute(arguments, checkpoint) if arguments.execute else {"result": "PREFLIGHT_ONLY"}
    except Exception as error:
        parser.error(str(error))
    checkpoint_sha256 = sha256(arguments.checkpoint_manifest)
    if checkpoint_sha256 != arguments.checkpoint_sha256:
        parser.error("checkpoint manifest SHA-256 does not match --checkpoint-sha256")
    if sha256(arguments.model_config) != arguments.model_config_sha256:
        parser.error("model config SHA-256 does not match --model-config-sha256")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "checkpoint_sha256": checkpoint_sha256, "checkpoint_model_config_sha256": checkpoint["model_config_sha256"], "shard_count": checkpoint["shard_count"], "tokenizer_sha256": sha256(arguments.tokenizer), **execution}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary_output = handle.name
    os.replace(temporary_output, arguments.output)


if __name__ == "__main__":
    main()
