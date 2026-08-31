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
MODULE_PATH = ROOT / "q2_gradient_lineage.py"


def _load():
    assert MODULE_PATH.exists(), "q2_gradient_lineage.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_gradient_lineage", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(root: Path) -> tuple[Path, Path, str, str]:
    run_id = "q2-gradient-test"
    target_name = "backbone_model.layers.0.mlp.gate_proj.weight"
    batch_sha = "b" * 64
    gradient_path = root / "cache" / f"{run_id}-grad-post-gate.pt"
    gradient_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(torch.arange(8, dtype=torch.float32).reshape(4, 2), gradient_path)
    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B3",
        "run_id": run_id,
        "batch_pin_check": {
            "b1m_sha256": batch_sha,
            "b3_recomputed_sha256": batch_sha,
            "match": True,
        },
        "cache_paths": {"grad_post_gate": gradient_path.relative_to(root).as_posix()},
        "cache_sha256": {
            "grad_post_gate": hashlib.sha256(gradient_path.read_bytes()).hexdigest()
        },
        "gradient_lineage": {
            "target_name": target_name,
            "dtype": "float32",
            "shape": [4, 2],
            "source": "pinned-batch-backward",
            "batch_sha256": batch_sha,
        },
        "verdict": "B3_CAPTURED",
    }
    receipt_path = root / "b3.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path, gradient_path, target_name, batch_sha


def _validate(module, root: Path, receipt: Path, gradient: Path, target: str, batch: str):
    return module.validate_gradient_lineage(
        b3_receipt_path=receipt,
        persisted_gradient_path=gradient,
        data_root=root,
        target_name=target,
        expected_run_id="q2-gradient-test",
        expected_batch_sha256=batch,
    )


def test_gradient_lineage_loads_only_hashed_pinned_batch_artifact(tmp_path: Path):
    module = _load()
    receipt, gradient, target, batch = _fixture(tmp_path)
    result = _validate(module, tmp_path, receipt, gradient, target, batch)
    assert torch.equal(result, torch.arange(8, dtype=torch.float32).reshape(4, 2))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("cache_sha256", None, "GRADIENT_HASH_MISSING"),
        ("batch_pin_check", {"b1m_sha256": "b" * 64, "b3_recomputed_sha256": "c" * 64, "match": True}, "GRADIENT_BATCH_BINDING_MISMATCH"),
        ("gradient_lineage", {"target_name": "foreign", "dtype": "float32", "shape": [4, 2], "source": "pinned-batch-backward", "batch_sha256": "b" * 64}, "GRADIENT_LINEAGE_MISMATCH"),
    ],
)
def test_gradient_lineage_refuses_missing_or_foreign_receipt_fields(
    tmp_path: Path, field: str, value: object, code: str
):
    module = _load()
    receipt, gradient, target, batch = _fixture(tmp_path)
    body = json.loads(receipt.read_text(encoding="utf-8"))
    if value is None:
        body.pop(field)
    else:
        body[field] = value
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(module.GradientLineageRefusal, match=code):
        _validate(module, tmp_path, receipt, gradient, target, batch)


def test_gradient_lineage_refuses_mutated_or_redirected_gradient(tmp_path: Path):
    module = _load()
    receipt, gradient, target, batch = _fixture(tmp_path)
    torch.save(torch.ones((4, 2), dtype=torch.float32), gradient)
    with pytest.raises(module.GradientLineageRefusal, match="GRADIENT_HASH_MISMATCH"):
        _validate(module, tmp_path, receipt, gradient, target, batch)

    receipt, gradient, target, batch = _fixture(tmp_path)
    body = json.loads(receipt.read_text(encoding="utf-8"))
    body["cache_paths"]["grad_post_gate"] = "other.pt"
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(module.GradientLineageRefusal, match="GRADIENT_PATH_MISMATCH"):
        _validate(module, tmp_path, receipt, gradient, target, batch)


def test_current_historical_b3_receipt_is_explicitly_refused(tmp_path: Path):
    module = _load()
    receipt, gradient, target, batch = _fixture(tmp_path)
    body = json.loads(receipt.read_text(encoding="utf-8"))
    body.pop("cache_sha256")
    body.pop("gradient_lineage")
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(module.GradientLineageRefusal, match="GRADIENT_HASH_MISSING"):
        _validate(module, tmp_path, receipt, gradient, target, batch)
