# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded CUDA one-batch sparse slice; invoke only through the disk budget runner."""

from __future__ import annotations

import json
from pathlib import Path

import torch
import torch.nn.functional as F

from batch import decode_owned_batch
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from train import run_launch


def load_authorized_record(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    """Consume the #812 launch-gate identity before reading training bytes."""

    packet, validation, input_receipt = run_launch(repo_root=root)
    if validation["decision"] != "ACCEPTED":
        raise RuntimeError("input launch gate did not accept the selected shard")
    shard = root / str(packet["input_identity"]["shard_path"])
    return json.loads(shard.read_text(encoding="utf-8")), input_receipt


def run() -> dict[str, object]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production vertical slice")
    root = Path(__file__).resolve().parents[2]
    config = RestartDecoderConfig.from_contract(root / "configs" / "ember-restart-3b.json")
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True)
    finally:
        torch.set_default_dtype(previous_dtype)
    model.train()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_134_515_200 or counts["active_parameters"] != 1_020_585_984:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    record, input_receipt = load_authorized_record(root)
    batch = decode_owned_batch(record, config, device=torch.device("cuda"))
    import bitsandbytes as bnb
    optimizer = bnb.optim.AdamW8bit((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
    torch.cuda.reset_peak_memory_stats()
    logits = model(batch["input_ids"], image_patches=batch["image_patches"].bfloat16(), audio_frames=batch["audio_frames"].bfloat16(), active_expert=batch["active_expert"])
    loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), batch["target_ids"].reshape(-1))
    loss.backward()
    optimizer.step()
    return {
        "loss": float(loss.detach().cpu()),
        "counts": counts,
        "expert_genesis_sha256": model.expert_bank_genesis_hashes(),
        "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "input_identity_receipt": input_receipt,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
