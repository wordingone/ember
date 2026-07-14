# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded CUDA one-batch sparse slice; invoke only through the disk budget runner."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from batch import decode_owned_batch
from checkpoint_artifacts import write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from train import run_launch


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def production_artifact_root(candidate: Path) -> Path:
    """Require B: for production bundles; manifests themselves stay portable."""

    resolved = candidate.resolve()
    if resolved.drive.upper() != "B:":
        raise ValueError("production artifact root must be an explicit B: path")
    return resolved


def _enforce_retention(parent: Path, *, max_count: int) -> None:
    """Reserve one bounded checkpoint slot before the next training step."""

    if max_count < 1:
        raise ValueError("checkpoint retention must retain at least one bundle")
    parent.mkdir(parents=True, exist_ok=True)
    bundles = sorted(
        (path for path in parent.iterdir() if path.is_dir() and path.name.startswith("checkpoint-")),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    while len(bundles) >= max_count:
        oldest = bundles.pop(0)
        shutil.rmtree(oldest)


def load_authorized_record(root: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Consume the #812 launch-gate identity before reading training bytes."""

    packet, validation, input_receipt = run_launch(repo_root=root)
    if validation["decision"] != "ACCEPTED":
        raise RuntimeError("input launch gate did not accept the selected shard")
    shard = root / str(packet["input_identity"]["shard_path"])
    return json.loads(shard.read_text(encoding="utf-8")), packet, input_receipt


def _rng_state_hash(device: torch.device) -> dict[str, str]:
    cpu = hashlib.sha256(torch.get_rng_state().cpu().numpy().tobytes()).hexdigest()
    cuda = hashlib.sha256(torch.cuda.get_rng_state(device).cpu().numpy().tobytes()).hexdigest()
    return {"cpu": cpu, "cuda": cuda}


def _execute_realization_counter(
    *,
    root: Path,
    config_path: Path,
    checkpoint_manifest_path: Path,
    active_expert: str,
    expected_counts: dict[str, object],
) -> dict[str, object]:
    counter_path = root / "tools" / "ember-restart-3b" / "parameter_counter.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(counter_path),
            "--model-config",
            str(config_path),
            "--checkpoint-manifest",
            str(checkpoint_manifest_path),
            "--active-expert",
            active_expert,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated parameter counter failed: {completed.stderr.strip()}")
    try:
        receipt = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("isolated parameter counter did not emit JSON") from error
    required = (
        "allocated_parameters",
        "unique_parameters",
        "trainable_parameters",
        "served_parameters",
        "active_parameters",
        "episode_trainable_parameters",
        "active_expert_ids",
    )
    if any(receipt.get(name) != expected_counts.get(name) for name in required):
        raise RuntimeError("isolated parameter counter disagrees with instantiated capacity")
    if receipt.get("counter_sha256") not in {None, _sha256(counter_path)}:
        raise RuntimeError("isolated parameter counter source hash is not self-consistent")
    return receipt


def run(*, seed: int, artifact_root: Path) -> dict[str, object]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production vertical slice")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("launch seed must be a nonnegative integer")
    artifact_root = production_artifact_root(artifact_root)
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    config = RestartDecoderConfig.from_contract(config_path)
    record, launch_packet, input_receipt = load_authorized_record(root)
    checkpoint_parent = artifact_root / "checkpoints"
    _enforce_retention(checkpoint_parent, max_count=8)
    checkpoint_root = checkpoint_parent / f"checkpoint-vertical-slice-seed-{seed}"

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng_state_before_init = _rng_state_hash(torch.device("cuda"))
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    finally:
        torch.set_default_dtype(previous_dtype)
    genesis_hashes = model.expert_bank_genesis_hashes()
    model.train()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_134_515_200 or counts["active_parameters"] != 1_020_585_984:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    batch = decode_owned_batch(record, config, device=torch.device("cuda"))
    import bitsandbytes as bnb

    optimizer = bnb.optim.AdamW8bit(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=1e-4,
    )
    torch.cuda.reset_peak_memory_stats()
    logits = model(
        batch["input_ids"],
        image_patches=batch["image_patches"].bfloat16(),
        audio_frames=batch["audio_frames"].bfloat16(),
        active_expert=batch["active_expert"],
    )
    loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), batch["target_ids"].reshape(-1))
    loss.backward()
    optimizer.step()
    rng_state_after_step = _rng_state_hash(torch.device("cuda"))
    data_cursor = {
        "record_index": 0,
        "input_identity_receipt_sha256": _json_sha256(input_receipt),
        "input_shard_path": str(launch_packet["input_identity"]["shard_path"]),
    }
    checkpoint = write_checkpoint_artifacts(
        model,
        optimizer,
        checkpoint_root,
        launch_seed=seed,
        rng_state_sha256=rng_state_after_step,
        data_cursor=data_cursor,
        model_config_sha256=_sha256(config_path),
        contract_sha256=_sha256(config_path),
        expert_genesis_sha256=genesis_hashes,
    )
    parameter_receipt = _execute_realization_counter(
        root=root,
        config_path=config_path,
        checkpoint_manifest_path=checkpoint_root / "checkpoint-manifest.json",
        active_expert=str(batch["active_expert"]),
        expected_counts=counts,
    )
    return {
        "loss": float(loss.detach().cpu()),
        "counts": counts,
        "launch_seed": seed,
        "rng_state_before_init_sha256": rng_state_before_init,
        "expert_genesis_sha256": genesis_hashes,
        "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "input_identity_receipt": input_receipt,
        "post_step_checkpoint": checkpoint,
        "parameter_receipt": parameter_receipt,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(seed=args.seed, artifact_root=args.artifact_root), sort_keys=True))