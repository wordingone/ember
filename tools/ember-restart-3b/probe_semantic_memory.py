# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded no-step shared-text forward probe for the clean-genesis sparse v2 decoder."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import torch

from batch import decode_owned_batch
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from semantic_stream import ManifestBoundTokenStream

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_receipt(
    *, model_config_sha256: str, stream_receipt_sha256: str, tokenizer_sha256: str,
    selected_expert: str, sequence_length: int, total_parameters: int,
    active_parameters: int, elapsed_seconds: float, peak_memory_bytes: int,
    reserved_memory_bytes: int,
) -> dict[str, Any]:
    return {
        "schema_version": "ember-shared-ffn-memory-probe-v1",
        "result": "MEASURED",
        "operation": "NO_STEP_SEMANTIC_FORWARD",
        "model_config_sha256": model_config_sha256,
        "stream_receipt_sha256": stream_receipt_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "selected_expert": selected_expert,
        "sequence_length": sequence_length,
        "total_parameters": total_parameters,
        "active_parameters": active_parameters,
        "elapsed_seconds": elapsed_seconds,
        "peak_memory_bytes": peak_memory_bytes,
        "reserved_memory_bytes": reserved_memory_bytes,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--sequence-length", type=int, default=1024)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.sequence_length < 1 or args.output.exists():
        parser.error("sequence length must be positive and output must be new")
    stream = ManifestBoundTokenStream.from_receipt(receipt_path=args.receipt, shards_root=args.shards_root, tokenizer_path=args.tokenizer)
    record, _ = stream.next_episode(shard_index=0, token_offset=0, sequence_length=args.sequence_length)
    config_path = ROOT / "configs" / "ember-restart-3b.json"
    config = RestartDecoderConfig.from_contract(config_path)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=args.seed).eval()
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("shared")
    counts = measure_parameter_counts(model)
    batch = decode_owned_batch(record, config, device=torch.device("cuda"))
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        logits = model(batch["input_ids"], active_expert="shared")
        if not torch.isfinite(logits.float()).all():
            raise RuntimeError("no-step semantic forward produced non-finite logits")
    torch.cuda.synchronize()
    receipt = probe_receipt(
        model_config_sha256=_sha256(config_path), stream_receipt_sha256=stream.receipt_sha256,
        tokenizer_sha256=stream.tokenizer_sha256, selected_expert="shared", sequence_length=args.sequence_length,
        total_parameters=counts["unique_parameters"], active_parameters=counts["active_parameters"],
        elapsed_seconds=time.perf_counter() - started, peak_memory_bytes=int(torch.cuda.max_memory_allocated()),
        reserved_memory_bytes=int(torch.cuda.max_memory_reserved()),
    )
    _atomic_json(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())