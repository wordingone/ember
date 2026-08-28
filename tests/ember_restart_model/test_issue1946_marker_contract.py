# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import torch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import pretrain  # noqa: E402
import packed_specialist_run  # noqa: E402


def test_complete_update_marker_constants_are_used_by_the_timed_regions() -> None:
    source = (ROOT / "tools" / "ember-restart-3b" / "pretrain.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants = {
        "COMPLETE_UPDATE_REFERENCE_FORWARD_MARKER",
        "COMPLETE_UPDATE_FORWARD_LOSS_MARKER",
        "COMPLETE_UPDATE_BACKWARD_MARKER",
        "COMPLETE_UPDATE_GRADIENT_CLIPPING_MARKER",
        "COMPLETE_UPDATE_OPTIMIZER_MARKER",
        "COMPLETE_UPDATE_TELEMETRY_MARKER",
    }
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert constants <= assigned
    for name in constants:
        assert source.count(f"torch.profiler.record_function({name})") >= 1


def test_record_function_wrappers_are_bitwise_neutral_without_profiler() -> None:
    torch.manual_seed(1946)
    control = torch.nn.Linear(4, 3, bias=True)
    marked = torch.nn.Linear(4, 3, bias=True)
    marked.load_state_dict(control.state_dict())
    inputs = torch.randn(5, 4)
    targets = torch.randn(5, 3)

    control_loss = torch.nn.functional.mse_loss(control(inputs), targets)
    control_loss.backward()
    with torch.profiler.record_function(pretrain.COMPLETE_UPDATE_FORWARD_LOSS_MARKER):
        marked_loss = torch.nn.functional.mse_loss(marked(inputs), targets)
    with torch.profiler.record_function(pretrain.COMPLETE_UPDATE_BACKWARD_MARKER):
        marked_loss.backward()

    assert torch.equal(control_loss.detach(), marked_loss.detach())
    for control_parameter, marked_parameter in zip(control.parameters(), marked.parameters(), strict=True):
        assert torch.equal(control_parameter.grad, marked_parameter.grad)


def test_trace_owner_mapping_is_forward_marker_bound_and_shape_classified() -> None:
    marker = SimpleNamespace(key=pretrain.COMPLETE_UPDATE_FORWARD_LOSS_MARKER, cpu_parent=None)
    event = SimpleNamespace(key="aten::mm", cpu_parent=marker)
    assert packed_specialist_run._issue1946_event_inside_marker(
        event, pretrain.COMPLETE_UPDATE_FORWARD_LOSS_MARKER
    )
    assert packed_specialist_run._issue1946_forward_owner(
        "aten::mm", [[960, 4096], [4096, 16384]], hidden=4096, vocab_size=32_000
    ) == "mlp_routing"
    assert packed_specialist_run._issue1946_forward_owner(
        "aten::_log_softmax", [[960, 32_000]], hidden=4096, vocab_size=32_000
    ) == "loss"
    outside = SimpleNamespace(key="aten::mm", cpu_parent=None)
    assert not packed_specialist_run._issue1946_event_inside_marker(
        outside, pretrain.COMPLETE_UPDATE_FORWARD_LOSS_MARKER
    )

    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU], record_shapes=True
    ) as profiler:
        with torch.profiler.record_function(pretrain.COMPLETE_UPDATE_FORWARD_LOSS_MARKER):
            torch.ones(2, 3) @ torch.ones(3, 4)
    matrix_events = [event for event in profiler.events() if "mm" in str(event.key)]
    assert matrix_events
    assert any(
        packed_specialist_run._issue1946_event_inside_marker(
            event, pretrain.COMPLETE_UPDATE_FORWARD_LOSS_MARKER
        )
        for event in matrix_events
    )


def test_injected_arm_b_preallocation_refusal_yields_exact_safety_margin() -> None:
    injected = MemoryError(
        "BF16 production envelope requires 25000000000 bytes but only 24000000000 are free; refusing before allocation"
    )
    assert packed_specialist_run._issue1946_safety_margin_failure_bytes(injected) == (
        25_000_000_000,
        24_000_000_000,
    )
    source = (ROOT / "tools" / "ember-restart-3b" / "packed_specialist_run.py").read_text(encoding="utf-8")
    assert 'except MemoryError as error:' in source
    assert 'error_class="SAFETY_MARGIN_FAILURE"' in source
