# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real-path closure test for #1464: fusing FullStateAdamWCPUOffload's update
into backward must be bit-identical to the non-fused path, including through
gradient checkpointing and the tied token-embedding / lm_head weight."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))


def _build(seed: int):
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    config = dense.DenseA1Config.small_for_tests()
    model = dense.DenseA1Decoder(config, genesis_seed=seed)
    contract = optimizer_module.load_a1_optimizer_contract()
    optimizer = optimizer_module.FullStateAdamWCPUOffload(model.parameters(), contract=contract)
    optimizer.initialize_state()
    return model, optimizer, config


def _run(model, optimizer, config, batches, targets) -> None:
    for input_ids, target_ids in zip(batches, targets):
        optimizer.zero_grad(set_to_none=True)
        logits = model(input_ids).reshape(-1, config.vocab_size)
        loss = F.cross_entropy(logits, target_ids.reshape(-1))
        loss.backward()
        optimizer.step()


def test_fused_backward_is_bit_identical_to_the_non_fused_path_over_three_steps() -> None:
    torch.manual_seed(410299)
    batches = [torch.randint(0, 64, (2, 5)) for _ in range(3)]
    targets = [torch.randint(0, 64, (2, 5)) for _ in range(3)]

    baseline_model, baseline_optimizer, config = _build(seed=90210)
    _run(baseline_model, baseline_optimizer, config, batches, targets)

    fused_model, fused_optimizer, _ = _build(seed=90210)
    fused_optimizer.enable_fused_backward()
    _run(fused_model, fused_optimizer, config, batches, targets)

    baseline_params = dict(baseline_model.named_parameters())
    fused_params = dict(fused_model.named_parameters())
    assert set(baseline_params) == set(fused_params)
    assert baseline_params  # non-empty: the equivalence claim is over real parameters
    for name in baseline_params:
        baseline_tensor = baseline_params[name]
        fused_tensor = fused_params[name]
        assert torch.equal(baseline_tensor, fused_tensor), f"parameter {name} diverged"
        assert baseline_tensor.detach().numpy().tobytes() == fused_tensor.detach().numpy().tobytes()

    used_parameter_names = {
        name for name, parameter in baseline_model.named_parameters()
        if not (name.startswith("image_projector.") or name.startswith("audio_projector."))
    }
    assert used_parameter_names  # the text-only path exercises at least these
    for name, baseline_parameter in baseline_params.items():
        fused_parameter = fused_params[name]
        baseline_state = baseline_optimizer.state[baseline_parameter]
        fused_state = fused_optimizer.state[fused_parameter]
        # Both paths must agree on every parameter's step count, including
        # the modality projectors this text-only path never touches (both
        # stay at 0) -- the equivalence claim is that fused and non-fused
        # agree, not a specific count.
        assert baseline_state["step"] == fused_state["step"]
        if name in used_parameter_names:
            assert baseline_state["step"] == len(batches)
        for field in ("master_copy", "exp_avg", "exp_avg_sq"):
            assert torch.equal(baseline_state[field], fused_state[field]), f"{name}.{field} diverged"


def test_fused_backward_tolerates_a_registered_parameter_that_never_gets_a_gradient() -> None:
    """The real DenseA1Decoder registers image_projector/audio_projector
    parameters that a text-only forward pass never touches. An earlier
    every-registered-parameter-applied invariant refused on step 1 of the
    real training loop for exactly this reason; this is the regression
    test for that defect."""
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    config = dense.DenseA1Config.small_for_tests()
    model = dense.DenseA1Decoder(config, genesis_seed=7)
    contract = optimizer_module.load_a1_optimizer_contract()
    optimizer = optimizer_module.FullStateAdamWCPUOffload(model.parameters(), contract=contract)
    optimizer.initialize_state()
    optimizer.enable_fused_backward()

    input_ids = torch.randint(0, 64, (1, 4))
    targets = torch.randint(0, 64, (1, 4))
    optimizer.zero_grad(set_to_none=True)
    logits = model(input_ids).reshape(-1, config.vocab_size)
    F.cross_entropy(logits, targets.reshape(-1)).backward()
    assert all(parameter.grad is None for parameter in model.parameters())
    optimizer.step()  # must not refuse despite unused modality projectors

    projector_parameters = [
        parameter for name, parameter in model.named_parameters()
        if name.startswith("image_projector.") or name.startswith("audio_projector.")
    ]
    assert projector_parameters  # the scenario this test guards against is real
    assert all(optimizer.state[parameter]["step"] == 0 for parameter in projector_parameters)


def test_step_refuses_when_a_registered_parameter_retains_an_unconsumed_gradient() -> None:
    """A leftover .grad at step() time in fused mode means a hook did not
    fire for an accumulation that happened -- simulated here by assigning
    .grad directly, which bypasses the autograd engine's accumulation path
    (and therefore the hook) entirely."""
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    parameter = torch.nn.Parameter(torch.tensor([1.0, -2.0]))
    contract = optimizer_module.load_a1_optimizer_contract()
    optimizer = optimizer_module.FullStateAdamWCPUOffload([parameter], contract=contract)
    optimizer.initialize_state()
    optimizer.enable_fused_backward()

    parameter.grad = torch.tensor([0.5, 0.5])
    with pytest.raises(dense.A1Refusal) as caught:
        optimizer.step()
    assert caught.value.code is dense.A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE


def test_enable_fused_backward_is_idempotent_and_registers_hooks_once() -> None:
    optimizer_module = importlib.import_module("a1_optimizer")
    parameter = torch.nn.Parameter(torch.tensor([1.0]))
    contract = optimizer_module.load_a1_optimizer_contract()
    optimizer = optimizer_module.FullStateAdamWCPUOffload([parameter], contract=contract)
    optimizer.initialize_state()
    optimizer.enable_fused_backward()
    optimizer.enable_fused_backward()
    assert len(optimizer._fused_hook_handles) == 1

    parameter.grad = torch.tensor([0.5])
    optimizer._fused_backward_hook(parameter)
    assert optimizer.state[parameter]["step"] == 1
    assert parameter.grad is None
    optimizer.step()  # single application this cycle satisfies completeness


def test_full_gradient_norm_accumulator_includes_one_dimensional_gradients() -> None:
    """Catches dropping 1-D parameters or summing norms instead of squares."""
    optimizer_module = importlib.import_module("a1_optimizer")
    accumulator = optimizer_module.FullGradientNormAccumulator()
    accumulator.accumulate(torch.tensor([3.0, 4.0]))
    accumulator.accumulate(torch.tensor([12.0]))
    assert accumulator.finish_step() == pytest.approx(13.0)


def test_full_gradient_norm_accumulator_refuses_empty_and_double_finish() -> None:
    """Catches publishing a vacuous or stale norm for a training step."""
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    empty = optimizer_module.FullGradientNormAccumulator()
    with pytest.raises(dense.A1Refusal):
        empty.finish_step()

    used = optimizer_module.FullGradientNormAccumulator()
    used.accumulate(torch.tensor([1.0]))
    assert used.finish_step() == pytest.approx(1.0)
    with pytest.raises(dense.A1Refusal):
        used.finish_step()


def test_fused_hook_captures_full_gradient_norm_before_gradient_release() -> None:
    """Catches measuring after the fused hook has cleared parameter.grad."""
    optimizer_module = importlib.import_module("a1_optimizer")
    parameter = torch.nn.Parameter(torch.tensor([1.0, -2.0]))
    contract = optimizer_module.load_a1_optimizer_contract()
    optimizer = optimizer_module.FullStateAdamWCPUOffload([parameter], contract=contract)
    optimizer.initialize_state()
    optimizer.enable_fused_backward()

    parameter.grad = torch.tensor([3.0, 4.0])
    optimizer._fused_backward_hook(parameter)
    assert parameter.grad is None
    optimizer.step()
    assert optimizer.finish_gradient_norm() == pytest.approx(5.0)
