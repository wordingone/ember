# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_momentum_lineage.py"


def _load():
    assert MODULE_PATH.exists(), "q2_momentum_lineage.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_momentum_lineage", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path):
    root.mkdir()
    gate = "backbone_model.layers.0.mlp.gate_proj.weight"
    model_state = {
        "backbone_model.embed_tokens.weight": torch.ones(3, 2),
        gate: torch.ones(2, 2),
        "backbone_model.layers.0.mlp.up_proj.weight": torch.ones(2, 2),
        "backbone_model.norm.weight": torch.ones(2),
    }
    pre = torch.tensor([[0.5, -0.25], [0.125, 0.75]], dtype=torch.float32)
    optimizer_state = {"muon": {"state": {0: {"momentum_buffer": pre.clone()}}}}
    model_path = root / "model.pt"
    optimizer_path = root / "optimizer.pt"
    torch.save(model_state, model_path)
    torch.save(optimizer_state, optimizer_path)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": {"model.pt": _sha(model_path), "optimizer.pt": _sha(optimizer_path)}}),
        encoding="utf-8",
    )
    pre_path = root / "run-pre-momentum.pt"
    torch.save(pre, pre_path)
    receipt_path = root / "b1m.json"
    receipt_path.write_text(
        json.dumps(
            {
                "ticket": "CBASE-GROW-RUNG2-EVENT-B1M",
                "run_id": "q2-momentum-test",
                "u_pre": {
                    "gate_key": gate,
                    "momentum_buffer_source": "B1 snapshot pre-grow momentum_buffer (parent-carried)",
                },
                "cache_paths": {"pre_momentum": pre_path.name},
                "verdict": "B1M_CAPTURED",
            }
        ),
        encoding="utf-8",
    )
    return gate, pre, manifest_path, model_path, optimizer_path, pre_path, receipt_path


def test_resolves_muon_local_buffer_and_exact_pushforward(tmp_path: Path):
    module = _load()
    gate, pre, manifest, model, optimizer, pre_path, receipt = _fixture(tmp_path / "momentum")
    transplanted = torch.cat([pre, pre], dim=0)

    result = module.validate_momentum_lineage(
        seed_manifest_path=manifest,
        seed_model_path=model,
        seed_optimizer_path=optimizer,
        b1m_receipt_path=receipt,
        persisted_pre_momentum_path=pre_path,
        target_name=gate,
        reset_momentum=torch.zeros_like(transplanted),
        transplant_momentum=transplanted,
        expected_run_id="q2-momentum-test",
    )

    assert result["schema_version"] == "q2-momentum-lineage-binding-v1"
    assert result["seed_optimizer_sha256"] == _sha(optimizer)
    assert result["b1m_receipt_sha256"] == _sha(receipt)
    assert result["transplant_matches_pushforward"] is True
    assert "path" not in json.dumps(result).lower()


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("reset", "RESET_MOMENTUM_NOT_ZERO"),
        ("transplant", "TRANSPLANT_MOMENTUM_PUSHFORWARD_MISMATCH"),
        ("persisted", "B1M_PERSISTED_MOMENTUM_MISMATCH"),
    ],
)
def test_refuses_substituted_momentum(tmp_path: Path, target: str, code: str):
    module = _load()
    gate, pre, manifest, model, optimizer, pre_path, receipt = _fixture(tmp_path / "momentum")
    reset = torch.zeros(4, 2)
    transplanted = torch.cat([pre, pre], dim=0)
    if target == "reset":
        reset[0, 0] = 1
    elif target == "transplant":
        transplanted[0, 0] += 1
    else:
        torch.save(pre.add(1), pre_path)

    with pytest.raises(module.MomentumLineageRefusal, match=code):
        module.validate_momentum_lineage(
            seed_manifest_path=manifest,
            seed_model_path=model,
            seed_optimizer_path=optimizer,
            b1m_receipt_path=receipt,
            persisted_pre_momentum_path=pre_path,
            target_name=gate,
            reset_momentum=reset,
            transplant_momentum=transplanted,
            expected_run_id="q2-momentum-test",
        )


def test_refuses_bfloat16_arm_buffer_even_when_values_match(tmp_path: Path):
    module = _load()
    gate, pre, manifest, model, optimizer, pre_path, receipt = _fixture(tmp_path / "momentum")
    transplanted = torch.cat([pre, pre], dim=0)

    with pytest.raises(module.MomentumLineageRefusal, match="RESET_MOMENTUM_INVALID"):
        module.validate_momentum_lineage(
            seed_manifest_path=manifest,
            seed_model_path=model,
            seed_optimizer_path=optimizer,
            b1m_receipt_path=receipt,
            persisted_pre_momentum_path=pre_path,
            target_name=gate,
            reset_momentum=torch.zeros_like(transplanted, dtype=torch.bfloat16),
            transplant_momentum=transplanted,
            expected_run_id="q2-momentum-test",
        )
