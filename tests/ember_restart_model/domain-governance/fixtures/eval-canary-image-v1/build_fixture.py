#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build the deterministic EVAL-CANARY-IMAGE-V1 committed fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import torch


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODEL_ROOT = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
LAYOUT_ROOT = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(MODEL_ROOT))
sys.path.insert(0, str(LAYOUT_ROOT))

from model import RestartDecoderConfig, UnifiedDecoder
from repository_layout import resolve_repository_authority  # noqa: E402


SEED = 1948
AUTHORITY_SCOPE = "MECHANICS_CANARY_ONLY"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_tensor_hash(name: str, tensor: torch.Tensor) -> str:
    if sys.byteorder != "little":
        raise RuntimeError("canonical tensor hashes require little-endian raw bytes")
    value = tensor.detach().cpu().contiguous()
    raw = bytes(value.view(torch.uint8).reshape(-1).tolist())
    header = json.dumps(
        {"dtype": str(value.dtype), "name": name, "shape": list(value.shape)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(header + b"\n" + raw)


def tokenizer_vocab_size(tokenizer_payload: dict[str, object]) -> int:
    model = tokenizer_payload.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("vocab"), dict):
        raise ValueError("real tokenizer authority must carry model.vocab")
    vocab = model["vocab"]
    ids = sorted(int(value) for value in vocab.values())
    if ids != list(range(len(ids))):
        raise ValueError("real tokenizer vocabulary IDs must be contiguous from zero")
    return len(ids)


def image_bytes(index: int) -> bytes:
    pixels = bytearray()
    for y in range(48):
        for x in range(48):
            pixels.extend(
                (
                    (17 * index + 5 * x) % 256,
                    (31 * index + 7 * y) % 256,
                    (47 * index + 3 * (x + y)) % 256,
                )
            )
    return b"P6\n48 48\n255\n" + bytes(pixels)


def write_json(path: Path, payload: object) -> bytes:
    data = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def build(output_dir: Path) -> None:
    existing = {path.name for path in output_dir.iterdir()} if output_dir.exists() else set()
    if existing - {"build_fixture.py"}:
        raise FileExistsError(f"refusing to overwrite nonempty fixture directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer_path = resolve_repository_authority(ROOT, "tokenizer").path
    tokenizer_raw = tokenizer_path.read_bytes()
    tokenizer_payload = json.loads(tokenizer_raw)
    vocab_size = tokenizer_vocab_size(tokenizer_payload)

    config = RestartDecoderConfig.small_for_tests(
        hidden_size=32,
        layers=1,
        attention_heads=4,
        vocab_size=vocab_size,
        gradient_checkpointing=False,
    )
    config_payload = {
        "attention_heads": config.attention_heads,
        "gradient_checkpointing": config.gradient_checkpointing,
        "hidden_size": config.hidden_size,
        "image_input_shape": list(config.image_input_shape),
        "image_token_id": config.image_token_id,
        "layers": config.layers,
        "vocab_size": config.vocab_size,
    }
    config_raw = write_json(output_dir / "config.json", config_payload)

    torch.manual_seed(SEED)
    model = UnifiedDecoder(config, genesis_seed=SEED).eval()
    state_dict = {name: tensor.detach().cpu().contiguous() for name, tensor in model.state_dict().items()}
    checkpoint_path = output_dir / "checkpoint.pt"
    torch.save({"genesis_seed": SEED, "state_dict": state_dict}, checkpoint_path)

    items = []
    for index in range(8):
        name = f"image-{index:02d}.ppm"
        raw = image_bytes(index)
        (output_dir / name).write_bytes(raw)
        items.append(
            {
                "asset": name,
                "asset_sha256": sha256_bytes(raw),
                "gold_label": "even" if index % 2 == 0 else "odd",
                "item_id": f"canary-image-{index:02d}",
                "split": "canary",
            }
        )

    checkpoint_raw = checkpoint_path.read_bytes()
    manifest = {
        "authority_scope": AUTHORITY_SCOPE,
        "canary_id": "EVAL-CANARY-IMAGE-V1",
        "checkpoint": {
            "file": "checkpoint.pt",
            "sha256": sha256_bytes(checkpoint_raw),
            "tensor_hashes": {name: canonical_tensor_hash(name, tensor) for name, tensor in sorted(state_dict.items())},
        },
        "config": {
            "file": "config.json",
            "sha256": sha256_bytes(config_raw),
            "vocab_size": vocab_size,
        },
        "declared_deletion_paths": [],
        "items": items,
        "license": "CC0-1.0",
        "seed": SEED,
        "tokenizer": {
            "file": "repository-authority:tokenizer",
            "sha256": sha256_bytes(tokenizer_raw),
            "vocab_size": vocab_size,
        },
    }
    write_json(output_dir / "manifest.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    build(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
