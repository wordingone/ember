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
    operator_path = root / "q2_model_lineage.py"
    operator_path.write_bytes(MODULE_PATH.read_bytes())
    runtime_config_path = root / "runtime-config.json"
    runtime_config_path.write_text('{"schema":"q2-event-runtime-config-v1"}\n', encoding="utf-8")
    module = _load()
    grown = module.replay_b2_widen(
        seed,
        n_layers=1,
        eps_sigma=module.CANONICAL_B2_EPS_SIGMA,
        eps_seed=module.CANONICAL_B2_EPS_SEED,
    )
    grown_path = root / "grown.pt"
    torch.save(grown, grown_path)
    receipt = {
        "schema": "q2-b2-replay-remint-receipt-v1",
        "source_commit": "a" * 40,
        "lineage_run_id": module.CANONICAL_B2_LINEAGE_RUN_ID,
        "verdict": "B2_REPLAY_REMINTED",
        "historical": {
            "receipt_sha256": module.CANONICAL_B2_RECEIPT_SHA256,
            "operator_sha256": module.CANONICAL_B2_OPERATOR_SHA256,
            "ticket": "CBASE-GROW-RUNG2-EVENT-B2",
            "verdict": "B2_REALIZED_PASS",
        },
        "law": {
            "n_layers": 1,
            "eps_sigma": module.CANONICAL_B2_EPS_SIGMA,
            "eps_seed": module.CANONICAL_B2_EPS_SEED,
            "banned_zero_assertion_passed": True,
            "distinct_from_eps0_cache": True,
            "eta_band_pass": True,
            "twin_cosine_pass": True,
        },
        "inputs": {
            "seed_manifest_sha256": _sha(manifest_path),
            "seed_model_sha256": _sha(seed_path),
            "runtime_config_sha256": _sha(runtime_config_path),
        },
        "operator_sha256": _sha(operator_path),
        "output": {"grown_model_sha256": _sha(grown_path)},
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    receipt_path = root / "b2.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return seed, seed_path, manifest_path, operator_path, runtime_config_path, receipt_path


def test_replays_b2_widen_and_binds_live_state(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, runtime_config_path, receipt_path = _fixture(tmp_path / "lineage")
    grown = module.replay_b2_widen(seed, n_layers=1, eps_sigma=module.CANONICAL_B2_EPS_SIGMA, eps_seed=module.CANONICAL_B2_EPS_SEED)
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(grown, grown_path)

    result = module.validate_model_lineage(
        live_state={key: value.clone() for key, value in grown.items()},
        seed_manifest_path=manifest_path,
        seed_model_path=seed_path,
        grown_model_path=grown_path,
        b2_receipt_path=receipt_path,
        grow_operator_path=operator_path,
        runtime_config_path=runtime_config_path,
        expected_run_id=module.CANONICAL_B2_LINEAGE_RUN_ID,
        expected_source_commit="a" * 40,
        n_layers=1,
    )

    assert result["schema_version"] == "q2-model-lineage-binding-v1"
    assert result["seed_model_sha256"] == _sha(seed_path)
    assert result["grown_model_sha256"] == _sha(grown_path)
    assert result["b2_receipt_sha256"] == _sha(receipt_path)
    assert result["historical_grow_operator_sha256"] == module.CANONICAL_B2_OPERATOR_SHA256
    assert result["replay_operator_sha256"] == _sha(operator_path)
    assert result["live_state_matches_grown"] is True
    assert "path" not in json.dumps(result).lower()


def test_refuses_tampered_grown_state(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, runtime_config_path, receipt_path = _fixture(tmp_path / "lineage")
    grown = module.replay_b2_widen(seed, n_layers=1, eps_sigma=module.CANONICAL_B2_EPS_SIGMA, eps_seed=module.CANONICAL_B2_EPS_SEED)
    grown[next(iter(grown))] = grown[next(iter(grown))].clone().add(1)
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(grown, grown_path)

    with pytest.raises(module.ModelLineageRefusal, match="GROWN_MODEL_HASH_MISMATCH"):
        module.validate_model_lineage(
            live_state=grown,
            seed_manifest_path=manifest_path,
            seed_model_path=seed_path,
            grown_model_path=grown_path,
            b2_receipt_path=receipt_path,
            grow_operator_path=operator_path,
            runtime_config_path=runtime_config_path,
            expected_run_id=module.CANONICAL_B2_LINEAGE_RUN_ID,
            expected_source_commit="a" * 40,
            n_layers=1,
        )


def test_refuses_foreign_operator_before_loading_grown(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, runtime_config_path, receipt_path = _fixture(tmp_path / "lineage")
    operator_path.write_text("foreign operator\n", encoding="utf-8")
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(seed, grown_path)

    with pytest.raises(module.ModelLineageRefusal, match="B2_REPLAY_OPERATOR_HASH_MISMATCH"):
        module.validate_model_lineage(
            live_state=seed,
            seed_manifest_path=manifest_path,
            seed_model_path=seed_path,
            grown_model_path=grown_path,
            b2_receipt_path=receipt_path,
            grow_operator_path=operator_path,
            runtime_config_path=runtime_config_path,
            expected_run_id=module.CANONICAL_B2_LINEAGE_RUN_ID,
            expected_source_commit="a" * 40,
            n_layers=1,
        )


def test_refuses_tampered_remint_receipt_or_source_commit(tmp_path: Path):
    module = _load()
    seed, seed_path, manifest_path, operator_path, runtime_config_path, receipt_path = _fixture(tmp_path / "lineage")
    grown = module.replay_b2_widen(seed, n_layers=1, eps_sigma=module.CANONICAL_B2_EPS_SIGMA, eps_seed=module.CANONICAL_B2_EPS_SEED)
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(grown, grown_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["law"]["eps_seed"] = 18
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(module.ModelLineageRefusal, match="B2_REPLAY_RECEIPT_INVALID"):
        module.validate_model_lineage(
            live_state=grown,
            seed_manifest_path=manifest_path,
            seed_model_path=seed_path,
            grown_model_path=grown_path,
            b2_receipt_path=receipt_path,
            grow_operator_path=operator_path,
            runtime_config_path=runtime_config_path,
            expected_run_id=module.CANONICAL_B2_LINEAGE_RUN_ID,
            expected_source_commit="b" * 40,
            n_layers=1,
        )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("historical_receipt", "B2_HISTORICAL_BINDING_INVALID"),
        ("historical_operator", "B2_HISTORICAL_BINDING_INVALID"),
        ("eps_sigma", "B2_FROZEN_LAW_MISMATCH"),
        ("eps_seed", "B2_FROZEN_LAW_MISMATCH"),
    ],
)
def test_refuses_self_hashed_foreign_remint_authority(
    tmp_path: Path, mutation: str, code: str
):
    module = _load()
    seed, seed_path, manifest_path, operator_path, runtime_config_path, receipt_path = _fixture(
        tmp_path / "lineage"
    )
    grown = module.replay_b2_widen(
        seed,
        n_layers=1,
        eps_sigma=module.CANONICAL_B2_EPS_SIGMA,
        eps_seed=module.CANONICAL_B2_EPS_SEED,
    )
    grown_path = tmp_path / "lineage" / "grown.pt"
    torch.save(grown, grown_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "historical_receipt":
        receipt["historical"]["receipt_sha256"] = "6" * 64
    elif mutation == "historical_operator":
        receipt["historical"]["operator_sha256"] = "7" * 64
    elif mutation == "eps_sigma":
        receipt["law"]["eps_sigma"] = 0.1
    else:
        receipt["law"]["eps_seed"] = 17
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = hashlib.sha256(
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(module.ModelLineageRefusal, match=code):
        module.validate_model_lineage(
            live_state=grown,
            seed_manifest_path=manifest_path,
            seed_model_path=seed_path,
            grown_model_path=grown_path,
            b2_receipt_path=receipt_path,
            grow_operator_path=operator_path,
            runtime_config_path=runtime_config_path,
            expected_run_id=module.CANONICAL_B2_LINEAGE_RUN_ID,
            expected_source_commit="a" * 40,
            n_layers=1,
        )
