# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys

import pytest
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))
pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA-only Tier-2 checkpoint")


class _Small(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.matrix = torch.nn.Parameter(torch.arange(35, device="cuda", dtype=torch.float32).reshape(7, 5))
        self.bias = torch.nn.Parameter(torch.ones(5, device="cuda"))


def _identity() -> dict[str, object]:
    return {
        "comparison_id": "r1-e8-tier2-test",
        "matched_identity": {
            "comparison_id": "r1-e8-tier2-test",
            "corpus_authority_sha256": "1" * 64,
            "shard_sequence_sha256": "2" * 64,
            "tokenizer_sha256": "3" * 64,
            "seed": 410299,
            "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
            "schedule_sha256": "4" * 64,
            "genesis_sha256": "5" * 64,
        },
        "config_sha256": "6" * 64,
        "tier2_contract_sha256": "7" * 64,
        "liveness_sha256": "8" * 64,
        "source_commit": "9" * 40,
        "certified_launch_sha256": "a" * 64,
        "tier": "TIER_2",
        "mechanism": "OWNED_Q_GALORE_PROJECTED_GRADIENT",
        "predecessor": None,
    }


def _built():
    optimizer_module = importlib.import_module("a1_tier2_optimizer")
    model = _Small()
    optimizer = optimizer_module.ProjectedQuantizedAdamWCUDA(
        model.named_parameters(),
        contract=optimizer_module.Tier2OptimizerContract.for_tests(max_rank=2, refresh_gap=2),
    )
    optimizer.initialize_state()
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        loss = sum(parameter.square().sum() for parameter in model.parameters())
        loss.backward()
        optimizer.step()
        optimizer.finish_gradient_norm()
    finally:
        torch.use_deterministic_algorithms(previous)
    return model, optimizer


def test_tier2_checkpoint_round_trip_reopens_every_shard_on_cpu(tmp_path: Path) -> None:
    module = importlib.import_module("a1_tier2_checkpoint")
    model, optimizer = _built()
    root = tmp_path / "checkpoint"
    manifest_path, digest = module.write_tier2_checkpoint(
        root,
        model=model,
        optimizer=optimizer,
        global_step=1,
        tokens_seen=32,
        identity=_identity(),
    )
    assert len(digest) == 64
    manifest = module.verify_tier2_checkpoint(manifest_path, expected_identity=_identity())
    assert manifest["schema_version"] == "ember-a1-tier2-checkpoint-v1"
    assert manifest["optimizer_inventory"]["complete"] is True
    assert manifest["optimizer_inventory"]["persistent_state_device"] == "cuda"
    assert manifest["parameter_names"] == ["matrix", "bias"]
    assert all(row["path"].startswith("a1-tier2-shard-") for row in manifest["payload_shards"])


def test_tier2_checkpoint_refuses_shard_tamper(tmp_path: Path) -> None:
    module = importlib.import_module("a1_tier2_checkpoint")
    model, optimizer = _built()
    manifest_path, _ = module.write_tier2_checkpoint(
        tmp_path / "checkpoint",
        model=model,
        optimizer=optimizer,
        global_step=1,
        tokens_seen=32,
        identity=_identity(),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shard = manifest_path.parent / manifest["payload_shards"][0]["path"]
    shard.write_bytes(shard.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="raw bytes"):
        module.verify_tier2_checkpoint(manifest_path, expected_identity=_identity())


def test_tier2_checkpoint_refuses_cross_tier_identity(tmp_path: Path) -> None:
    module = importlib.import_module("a1_tier2_checkpoint")
    wrong = copy.deepcopy(_identity())
    wrong["tier"] = "TIER_1"
    model, optimizer = _built()
    with pytest.raises(ValueError, match="tier/mechanism"):
        module.write_tier2_checkpoint(
            tmp_path / "checkpoint",
            model=model,
            optimizer=optimizer,
            global_step=1,
            tokens_seen=32,
            identity=wrong,
        )


def test_tier2_checkpoint_refuses_incomplete_optimizer_inventory(tmp_path: Path) -> None:
    module = importlib.import_module("a1_tier2_checkpoint")
    model, optimizer = _built()
    optimizer.state.pop(next(iter(model.parameters())))
    with pytest.raises(ValueError, match="inventory"):
        module.write_tier2_checkpoint(
            tmp_path / "checkpoint",
            model=model,
            optimizer=optimizer,
            global_step=1,
            tokens_seen=32,
            identity=_identity(),
        )


def test_tier2_checkpoint_is_no_overwrite(tmp_path: Path) -> None:
    module = importlib.import_module("a1_tier2_checkpoint")
    model, optimizer = _built()
    root = tmp_path / "checkpoint"
    module.write_tier2_checkpoint(
        root,
        model=model,
        optimizer=optimizer,
        global_step=1,
        tokens_seen=32,
        identity=_identity(),
    )
    with pytest.raises(FileExistsError):
        module.write_tier2_checkpoint(
            root,
            model=model,
            optimizer=optimizer,
            global_step=1,
            tokens_seen=32,
            identity=_identity(),
        )
