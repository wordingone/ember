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
from typing import Any, Mapping

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


class FrozenTokenizer:
    """Content-addressed tokenizer bytes used for both prompt IDs and answer text."""

    def __init__(self, tokenizer: Any, *, sha256: str, eos_token_id: int) -> None:
        self._tokenizer = tokenizer
        self.sha256 = sha256
        self._eos_token_id = eos_token_id

    @property
    def eos_token_ids(self) -> set[int]:
        return {self._eos_token_id}

    def encode(self, text: str) -> list[int]:
        if not isinstance(text, str) or not text:
            raise ValueError("frozen split prompt must be a nonempty string")
        return list(self._tokenizer.encode(text).ids)

    def decode(self, token_ids: list[int]) -> str:
        if not isinstance(token_ids, list) or any(not isinstance(token, int) or token < 0 for token in token_ids):
            raise ValueError("generated token IDs must be nonnegative integers")
        return str(self._tokenizer.decode(token_ids, skip_special_tokens=False))


def load_frozen_tokenizer(path: Path, *, expected_sha256: str) -> FrozenTokenizer:
    """Load exact frozen tokenizer bytes and refuse substitutions or malformed bytes."""

    actual_sha256 = sha(path)
    if actual_sha256 != expected_sha256:
        raise ValueError("tokenizer sha256 does not match the frozen split")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        added_tokens = payload["added_tokens"]
        eos_ids = {
            item.get("id")
            for item in added_tokens
            if isinstance(item, Mapping)
            and item.get("content") == "<|endoftext|>"
            and item.get("special") is True
        }
        if (
            len(eos_ids) != 1
            or not isinstance(next(iter(eos_ids)), int)
            or isinstance(next(iter(eos_ids)), bool)
        ):
            raise ValueError("frozen tokenizer must declare one special <|endoftext|> ID")
        eos_token_id = next(iter(eos_ids))
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(path))
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("frozen tokenizer bytes lack a valid special EOS declaration") from error
    except Exception as error:
        raise ValueError("frozen tokenizer bytes are not loadable by the tokenizer runtime") from error
    if tokenizer.get_vocab().get("<|endoftext|>") != eos_token_id:
        raise ValueError("frozen tokenizer EOS declaration does not match its vocabulary")
    return FrozenTokenizer(tokenizer, sha256=actual_sha256, eos_token_id=eos_token_id)


def _contains_target_leak(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if "target" in normalized or "answer" in normalized or "label" in normalized:
                return True
            if _contains_target_leak(child):
                return True
    elif isinstance(value, list):
        return any(_contains_target_leak(child) for child in value)
    return False


def frozen_split_prompt(split_path: Path, row_id: str, tokenizer: FrozenTokenizer) -> tuple[str, dict[str, Any]]:
    """Select one target-free prompt from exact frozen split bytes and tokenize it."""

    payload = json.loads(split_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "ember-owned-frozen-inference-split-v1":
        raise ValueError("inference split must use ember-owned-frozen-inference-split-v1")
    if payload.get("tokenizer_sha256") != tokenizer.sha256:
        raise ValueError("frozen split tokenizer sha256 does not match loaded tokenizer")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("frozen inference split requires nonempty rows")
    selected = [row for row in rows if isinstance(row, Mapping) and row.get("id") == row_id]
    if len(selected) != 1:
        raise ValueError("frozen inference split must contain exactly one requested row")
    row = dict(selected[0])
    if _contains_target_leak(row):
        raise ValueError("frozen inference split row contains a target leak")
    prompt = row.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("frozen inference split row requires a nonempty prompt")
    if row.get("active_expert") != "shared":
        raise ValueError("frozen text inference row must route through the shared text path")
    return row_id, {
        "schema_version": "ember-owned-inference-prompt-v1",
        "id": row_id,
        "active_expert": "shared",
        "token_ids": tokenizer.encode(prompt),
        "frozen_row_sha256": hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }

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
    decoded_text: str,
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
            "output": {"kind": "text", "text": decoded_text},
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
    request = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("schema_version") != "ember-owned-inference-row-request-v1":
        parser.error("inference input must request one frozen split row")
    requested_row_id = request.get("row_id")
    if not isinstance(requested_row_id, str) or not requested_row_id:
        parser.error("inference request requires a nonempty row_id")
    split_payload = json.loads(args.split.read_text(encoding="utf-8"))
    expected_tokenizer_sha256 = split_payload.get("tokenizer_sha256") if isinstance(split_payload, dict) else None
    if not isinstance(expected_tokenizer_sha256, str):
        parser.error("frozen inference split must bind tokenizer_sha256")
    tokenizer = load_frozen_tokenizer(args.tokenizer, expected_sha256=expected_tokenizer_sha256)
    row_id, record = frozen_split_prompt(args.split, requested_row_id, tokenizer)
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
        input_sha256=record["frozen_row_sha256"],
        generated_token_ids=generated,
        stop_reason=stop_reason,
        decoded_text=tokenizer.decode(generated),
    )
    _atomic_json(args.output, output)
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())