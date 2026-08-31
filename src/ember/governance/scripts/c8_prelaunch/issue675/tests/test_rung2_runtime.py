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


def _cfg(*, qat: bool = False) -> dict[str, object]:
    return {
        "precision": {"qat": {"enabled": qat}},
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


def test_runtime_cpu_snapshot_and_qat_restore_preserve_parameter_storage():
    module = _load()

    class TrackingTensor:
        def __init__(self) -> None:
            self.detached = False
            self.destination = None

        def detach(self):
            self.detached = True
            return self

        def to(self, *, device):
            self.destination = device
            return torch.tensor([1.0])

    tracked = TrackingTensor()
    snapshot = module._cpu_contiguous_clone(tracked)
    assert tracked.detached is True
    assert tracked.destination == "cpu"
    assert snapshot.device.type == "cpu" and snapshot.is_contiguous()

    torch.manual_seed(11)
    model = TinyEventModel()
    original = {
        name: (parameter, parameter.data_ptr(), parameter.detach().clone())
        for name, parameter in model.named_parameters()
    }
    saved = module._apply_fake_quant(model)
    assert saved and all(value.device.type == "cpu" for _layer, value in saved)
    for name, parameter in model.named_parameters():
        expected, pointer, _bytes = original[name]
        assert parameter is expected and parameter.data_ptr() == pointer
    module._restore_weights(saved)
    for name, parameter in model.named_parameters():
        expected, pointer, before = original[name]
        assert parameter is expected and parameter.data_ptr() == pointer
        assert torch.equal(parameter.detach(), before)


def test_runtime_restores_exact_storage_when_gradient_and_replay_raise():
    module = _load()

    class ExplodingEventModel(TinyEventModel):
        def backbone(self, ids: torch.Tensor) -> torch.Tensor:
            super().backbone(ids)
            raise RuntimeError("injected-runtime-failure")

    for operation in ("gradient", "replay"):
        torch.manual_seed(13)
        model = ExplodingEventModel()
        baseline = _state(model)
        identity = {
            name: (parameter, parameter.data_ptr())
            for name, parameter in model.named_parameters()
        }
        with pytest.raises(RuntimeError, match="injected-runtime-failure"):
            if operation == "gradient":
                module.compute_frozen_batch_gradient(
                    model=model,
                    microsteps=_batch(),
                    config=_cfg(qat=True),
                    target_name="gate_proj.weight",
                    device="cpu",
                )
            else:
                module.replay_target_only_loss(
                    model=model,
                    microsteps=_batch(),
                    config=_cfg(qat=True),
                    target_name="gate_proj.weight",
                    target=baseline["gate_proj.weight"].float() + 0.01,
                    expected_non_target_state={
                        key: value for key, value in baseline.items()
                        if key != "gate_proj.weight"
                    },
                    device="cpu",
                )
        after = _state(model)
        assert all(torch.equal(after[key], baseline[key]) for key in baseline)
        for name, parameter in model.named_parameters():
            expected, pointer = identity[name]
            assert parameter is expected and parameter.data_ptr() == pointer


def test_fake_quant_restores_prior_layers_when_snapshot_fails_mid_apply(monkeypatch):
    module = _load()
    torch.manual_seed(17)
    model = TinyEventModel()
    baseline = _state(model)
    identity = {
        name: (parameter, parameter.data_ptr())
        for name, parameter in model.named_parameters()
    }
    original_clone = module._cpu_contiguous_clone
    calls = 0

    def fail_on_second_linear(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected-snapshot-failure")
        return original_clone(value)

    monkeypatch.setattr(module, "_cpu_contiguous_clone", fail_on_second_linear)
    with pytest.raises(RuntimeError, match="injected-snapshot-failure"):
        module._apply_fake_quant(model)

    assert calls == 2
    after = _state(model)
    assert all(torch.equal(after[key], baseline[key]) for key in baseline)
    for name, parameter in model.named_parameters():
        expected, pointer = identity[name]
        assert parameter is expected and parameter.data_ptr() == pointer


def test_target_only_gradient_matches_full_backward_without_populating_parameter_grads():
    module = _load()
    torch.manual_seed(23)
    reference = TinyEventModel()
    candidate = TinyEventModel()
    candidate.load_state_dict(reference.state_dict())

    reference.zero_grad(set_to_none=True)
    reference_loss, _ = module._losses(
        model=reference,
        microsteps=_batch(),
        config=_cfg(),
        device="cpu",
        backward=True,
    )
    expected = reference.gate_proj.weight.grad.detach().float().clone()

    entered = []

    class SeenContext:
        def __enter__(self):
            entered.append(True)
        def __exit__(self, *_args):
            return False

    module._saved_tensor_context = lambda _device: SeenContext()
    actual, actual_loss, _ = module.compute_frozen_batch_gradient(
        model=candidate,
        microsteps=_batch(),
        config=_cfg(),
        target_name="gate_proj.weight",
        device="cpu",
    )

    assert entered == [True, True]
    assert torch.allclose(actual, expected, rtol=1e-6, atol=1e-7)
    assert actual_loss == pytest.approx(float(reference_loss.detach()), rel=1e-6)
    assert all(parameter.grad is None for parameter in candidate.parameters())


def test_target_only_gradient_failure_leaves_no_parameter_grads_and_restores_qat(monkeypatch):
    module = _load()
    torch.manual_seed(29)
    model = TinyEventModel()
    baseline = _state(model)
    original_grad = torch.autograd.grad
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected-target-grad-failure")
        return original_grad(*args, **kwargs)

    monkeypatch.setattr(torch.autograd, "grad", fail_second)
    with pytest.raises(RuntimeError, match="injected-target-grad-failure"):
        module.compute_frozen_batch_gradient(
            model=model,
            microsteps=_batch(),
            config=_cfg(qat=True),
            target_name="gate_proj.weight",
            device="cpu",
        )

    assert calls == 2
    assert all(parameter.grad is None for parameter in model.parameters())
    assert all(torch.equal(_state(model)[key], baseline[key]) for key in baseline)
