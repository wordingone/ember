# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_rung2_runtime.py"


def _load():
    assert MODULE_PATH.exists(), "q2_rung2_runtime.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_rung2_runtime", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TinyEventModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.embed = torch.nn.Embedding(16, 4)
        self.gate_proj = torch.nn.Linear(4, 4, bias=False)
        self.head = torch.nn.Linear(4, 16, bias=False)
        self.mtp_heads = torch.nn.ModuleList([torch.nn.Linear(4, 16, bias=False)])

    def backbone(self, ids: torch.Tensor) -> torch.Tensor:
        return torch.tanh(self.gate_proj(self.embed(ids)))


def _cfg() -> dict[str, object]:
    return {
        "precision": {"qat": {"enabled": False}},
        "objective": {"mtp_aux_heads": {"enabled": True, "weight": 0.1, "n_heads": 1}},
    }


def _batch() -> list[dict[str, object]]:
    return [
        {
            "x": torch.tensor([[1, 2, 3]], dtype=torch.int64),
            "y0": torch.tensor([[2, 3, 4]], dtype=torch.int64),
            "y_mtp": [torch.tensor([[3, 4, 5]], dtype=torch.int64)],
        },
        {
            "x": torch.tensor([[4, 5, 6]], dtype=torch.int64),
            "y0": torch.tensor([[5, 6, 7]], dtype=torch.int64),
            "y_mtp": [torch.tensor([[6, 7, 8]], dtype=torch.int64)],
        },
    ]


def _state(model: torch.nn.Module) -> dict[str, torch.Tensor]:
    return {key: value.detach().clone() for key, value in model.state_dict().items()}


def test_runtime_derives_deterministic_gradient_from_frozen_batch():
    module = _load()
    torch.manual_seed(7)
    model = TinyEventModel()
    first_gradient, first_loss, first_impl = module.compute_frozen_batch_gradient(
        model=model,
        microsteps=_batch(),
        config=_cfg(),
        target_name="gate_proj.weight",
        device="cpu",
    )
    second_gradient, second_loss, second_impl = module.compute_frozen_batch_gradient(
        model=model,
        microsteps=_batch(),
        config=_cfg(),
        target_name="gate_proj.weight",
        device="cpu",
    )
    assert first_impl == second_impl == "cut_ce_chunked"
    assert torch.equal(first_gradient, second_gradient)
    assert first_gradient.dtype == torch.float32
    assert torch.isfinite(first_gradient).all()
    assert first_loss == second_loss
    assert first_loss > 0


def test_runtime_replays_target_only_loss_and_restores_exact_state():
    module = _load()
    torch.manual_seed(9)
    model = TinyEventModel()
    baseline = _state(model)
    target = baseline["gate_proj.weight"].float() + 0.01
    non_target = {key: value for key, value in baseline.items() if key != "gate_proj.weight"}
    loss = module.replay_target_only_loss(
        model=model,
        microsteps=_batch(),
        config=_cfg(),
        target_name="gate_proj.weight",
        target=target,
        expected_non_target_state=non_target,
        device="cpu",
    )
    assert loss > 0
    assert _state(model).keys() == baseline.keys()
    assert all(torch.equal(_state(model)[key], baseline[key]) for key in baseline)


def test_runtime_refuses_non_target_drift_or_malformed_batch():
    module = _load()
    model = TinyEventModel()
    baseline = _state(model)
    non_target = {key: value for key, value in baseline.items() if key != "gate_proj.weight"}
    non_target["head.weight"] = non_target["head.weight"] + 1
    with pytest.raises(module.Rung2RuntimeRefusal, match="RUNTIME_NON_TARGET_STATE_MISMATCH"):
        module.replay_target_only_loss(
            model=model,
            microsteps=_batch(),
            config=_cfg(),
            target_name="gate_proj.weight",
            target=baseline["gate_proj.weight"].float(),
            expected_non_target_state=non_target,
            device="cpu",
        )

    malformed = _batch()
    malformed[0]["y_mtp"] = []
    with pytest.raises(module.Rung2RuntimeRefusal, match="RUNTIME_BATCH_SCHEMA_INVALID"):
        module.compute_frozen_batch_gradient(
            model=model,
            microsteps=malformed,
            config=_cfg(),
            target_name="gate_proj.weight",
            device="cpu",
        )
