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
MODULE_PATH = ROOT / "q2_model_lineage.py"


def _load():
    assert MODULE_PATH.exists(), "q2_model_lineage.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_model_lineage", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path):
    root.mkdir()
    prefix = "backbone_model.layers.0.mlp."
    seed = {
        prefix + "gate_proj.weight": torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.bfloat16),
        prefix + "up_proj.weight": torch.tensor([[0.5, 1.5], [2.5, 3.5]], dtype=torch.bfloat16),
        prefix + "down_proj.weight": torch.tensor([[1.0, 2.0], [4.0, 8.0]], dtype=torch.bfloat16),
        "backbone_model.norm.weight": torch.tensor([1.0, 2.0], dtype=torch.bfloat16),
    }
    seed_path = root / "model.pt"
    torch.save(seed, seed_path)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps({"files": {"model.pt": _sha(seed_path)}}), encoding="utf-8")
    operator_path = root / "cbase_grow_dryrun.py"
    operator_path.write_text("canonical grow operator\n", encoding="utf-8")
    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B2",
        "run_id": "q2-lineage-test",
        "eps": {"eps_sigma": 0.1, "eps_seed": 17, "banned_zero_assertion_passed": True},
        "operator_sha256": _sha(operator_path),
        "cache": {"cache_path": "grown.pt", "distinct_from_eps0_cache": True},
        "realized_proof": {"eta_band_pass": True, "twin_cosine_pass": True},
        "verdict": "B2_REALIZED_PASS",
    }
    receipt_path = root / "b2.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return seed, seed_path, manifest_path, operator_path, receipt_path


def test_replays_b2_widen_and_binds_live_state(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, receipt_path = _fixture(tmp_path / "lineage")
    grown = module.replay_b2_widen(seed, n_layers=1, eps_sigma=0.1, eps_seed=17)
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(grown, grown_path)

    result = module.validate_model_lineage(
        live_state={key: value.clone() for key, value in grown.items()},
        seed_manifest_path=manifest_path,
        seed_model_path=seed_path,
        grown_model_path=grown_path,
        b2_receipt_path=receipt_path,
        grow_operator_path=operator_path,
        expected_run_id="q2-lineage-test",
        n_layers=1,
    )

    assert result["schema_version"] == "q2-model-lineage-binding-v1"
    assert result["seed_model_sha256"] == _sha(seed_path)
    assert result["grown_model_sha256"] == _sha(grown_path)
    assert result["b2_receipt_sha256"] == _sha(receipt_path)
    assert result["live_state_matches_grown"] is True
    assert "path" not in json.dumps(result).lower()


def test_refuses_tampered_grown_state(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, receipt_path = _fixture(tmp_path / "lineage")
    grown = module.replay_b2_widen(seed, n_layers=1, eps_sigma=0.1, eps_seed=17)
    grown[next(iter(grown))] = grown[next(iter(grown))].clone().add(1)
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(grown, grown_path)

    with pytest.raises(module.ModelLineageRefusal, match="GROWN_MODEL_REPLAY_MISMATCH"):
        module.validate_model_lineage(
            live_state=grown,
            seed_manifest_path=manifest_path,
            seed_model_path=seed_path,
            grown_model_path=grown_path,
            b2_receipt_path=receipt_path,
            grow_operator_path=operator_path,
            expected_run_id="q2-lineage-test",
            n_layers=1,
        )


def test_refuses_foreign_operator_before_loading_grown(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, receipt_path = _fixture(tmp_path / "lineage")
    operator_path.write_text("foreign operator\n", encoding="utf-8")
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(seed, grown_path)

    with pytest.raises(module.ModelLineageRefusal, match="B2_OPERATOR_HASH_MISMATCH"):
        module.validate_model_lineage(
            live_state=seed,
            seed_manifest_path=manifest_path,
            seed_model_path=seed_path,
            grown_model_path=grown_path,
            b2_receipt_path=receipt_path,
            grow_operator_path=operator_path,
            expected_run_id="q2-lineage-test",
            n_layers=1,
        )
