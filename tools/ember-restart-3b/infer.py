# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Prompt-only, checkpoint-bound greedy inference emitting canonical raw predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import torch

from batch import decode_owned_batch
from checkpoint_artifacts import load_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ember_restart.prediction_contract import CLAIM_STATUS, SCHEMA_VERSION, validate_predictions  # noqa: E402


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def greedy_generate(
    *,
    model: Any,
    prompt_ids: torch.Tensor,
    model_kwargs: dict[str, Any],
    max_new_tokens: int,
    stop_token_ids: set[int],
) -> tuple[list[int], str]:
    """Append greedy tokens from a prompt only; targets are never accepted here."""

    if prompt_ids.ndim != 2 or prompt_ids.shape[0] != 1:
        raise ValueError("greedy generation requires one prompt sequence")
    if not isinstance(max_new_tokens, int) or max_new_tokens <= 0:
        raise ValueError("max_new_tokens must be positive")
    if not stop_token_ids or any(not isinstance(token, int) or token < 0 for token in stop_token_ids):
        raise ValueError("stop_token_ids must be nonempty nonnegative integers")
    current = prompt_ids
    generated: list[int] = []
    for _ in range(max_new_tokens):
        logits = model(current, **model_kwargs)
        token = int(logits[0, -1].argmax(dim=-1).item())
        generated.append(token)
        if token in stop_token_ids:
            return generated, "eos"
        current = torch.cat((current, torch.tensor([[token]], dtype=current.dtype, device=current.device)), dim=1)
    return generated, "max_new_tokens"


def canonical_prediction_envelope(
    *,
    checkpoint_manifest_sha256: str,
    model_config_sha256: str,
    tokenizer_sha256: str,
    inference_implementation_sha256: str,
    benchmark_id: str,
    benchmark_version: str,
    capability: str,
    split_sha256: str,
    protocol_sha256: str,
    max_new_tokens: int,
    stop_token_ids: list[int],
    row_id: str,
    input_sha256: str,
    generated_token_ids: list[int],
    stop_reason: str,
) -> dict[str, Any]:
    """Build the exact non-admissible central prediction envelope for one prompt."""

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "claim_status": CLAIM_STATUS,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "model_config_sha256": model_config_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "inference_implementation_sha256": inference_implementation_sha256,
        "benchmark": {
            "id": benchmark_id,
            "version": benchmark_version,
            "capability": capability,
            "split_sha256": split_sha256,
            "protocol_sha256": protocol_sha256,
        },
        "decoding": {
            "strategy": "GREEDY_AUTOREGRESSIVE",
            "teacher_forcing": False,
            "max_new_tokens": max_new_tokens,
            "temperature": 0,
            "top_p": 1,
            "stop_token_ids": stop_token_ids,
        },
        "rows": [{
            "id": row_id,
            "input_sha256": input_sha256,
            "generated_token_ids": generated_token_ids,
            "stop_reason": stop_reason,
            "output": {"kind": "text", "text": " ".join(str(token) for token in generated_token_ids)},
        }],
    }
    return validate_predictions(envelope)


def _prompt_batch(record: dict[str, Any], config: RestartDecoderConfig, *, device: torch.device) -> tuple[str, dict[str, Any]]:
    if record.get("schema_version") != "ember-owned-inference-prompt-v1":
        raise ValueError("inference input must use ember-owned-inference-prompt-v1")
    if "target_ids" in record:
        raise ValueError("prompt-only inference rejects target_ids")
    row_id = record.get("id")
    if not isinstance(row_id, str) or not row_id:
        raise ValueError("inference prompt requires a nonempty id")
    prompt_ids = record.get("token_ids")
    if not isinstance(prompt_ids, list) or not prompt_ids:
        raise ValueError("inference prompt requires nonempty token_ids")
    owned_record = dict(record)
    owned_record["schema_version"] = "ember-owned-semantic-text-v1" if record.get("active_expert") == "shared" else "ember-owned-bootstrap-batch-v1"
    owned_record["target_ids"] = list(prompt_ids)
    return row_id, decode_owned_batch(owned_record, config, device=device)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f"{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--benchmark-version", required=True)
    parser.add_argument("--capability", required=True, choices=("text", "image", "audio", "reasoning", "tool"))
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, required=True)
    parser.add_argument("--stop-token-id", type=int, action="append", required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("prediction output must not already exist")
    config_path = ROOT / "configs" / "ember-restart-3b.json"
    config = RestartDecoderConfig.from_contract(config_path)
    manifest_path = args.checkpoint / "checkpoint-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = {**manifest, "checkpoint_manifest_sha256": sha(manifest_path)}
    model = UnifiedDecoder(config, device=args.device, allow_production_allocation=True).eval()
    load_checkpoint_artifacts(model, None, args.checkpoint, receipt)
    record = json.loads(args.input.read_text(encoding="utf-8"))
    row_id, batch = _prompt_batch(record, config, device=torch.device(args.device))
    with torch.inference_mode():
        generated, stop_reason = greedy_generate(
            model=model,
            prompt_ids=batch["input_ids"],
            model_kwargs={
                "image_patches": batch["image_patches"],
                "audio_frames": batch["audio_frames"],
                "image_coordinates": batch["image_coordinates"],
                "spans": batch["spans"],
                "active_expert": batch["active_expert"],
            },
            max_new_tokens=args.max_new_tokens,
            stop_token_ids=set(args.stop_token_id),
        )
    output = canonical_prediction_envelope(
        checkpoint_manifest_sha256=receipt["checkpoint_manifest_sha256"],
        model_config_sha256=sha(config_path),
        tokenizer_sha256=sha(args.tokenizer),
        inference_implementation_sha256=sha(Path(__file__)),
        benchmark_id=args.benchmark_id,
        benchmark_version=args.benchmark_version,
        capability=args.capability,
        split_sha256=sha(args.split),
        protocol_sha256=sha(args.protocol),
        max_new_tokens=args.max_new_tokens,
        stop_token_ids=args.stop_token_id,
        row_id=row_id,
        input_sha256=sha(args.input),
        generated_token_ids=generated,
        stop_reason=stop_reason,
    )
    _atomic_json(args.output, output)
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())