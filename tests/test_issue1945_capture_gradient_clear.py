# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Captured/optimizer owner union clears once while preserving grad storage and absence."""
from collections import Counter
from pathlib import Path
import sys
from unittest import mock

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model import ember_v0_capture as subject


def harness(*owners):
    return subject.SegmentedStep((subject.SegmentSpec(0, lambda x: (x,), owners),), device="cpu")


def owner(value):
    result = torch.nn.Parameter(torch.full((3, 2), float(value)))
    result.grad = torch.full_like(result, value)
    return result


def test_optimizer_and_capture_union_clears_each_owner_once():
    shared, captured_only, optimizer_only, absent = [owner(i) for i in (1, 2, 3, 4)]
    absent.grad = None
    captured = harness(shared, captured_only, absent)
    optimizer = torch.optim.AdamW([shared, optimizer_only, absent], foreach=False)
    gradients = [p.grad for p in (shared, captured_only, optimizer_only)]
    addresses = [g.data_ptr() for g in gradients]
    calls = Counter()
    original = torch.Tensor.zero_

    def observed(tensor, *args, **kwargs):
        calls[id(tensor)] += 1
        return original(tensor, *args, **kwargs)

    with mock.patch.object(torch.Tensor, "zero_", observed):
        captured.zero_grad(optimizer=optimizer)
    assert [calls[id(g)] for g in gradients] == [1, 1, 1]
    assert [p.grad.data_ptr() for p in (shared, captured_only, optimizer_only)] == addresses
    assert all(torch.count_nonzero(g) == 0 for g in gradients)
    assert absent.grad is None


@pytest.mark.parametrize("foreach", [False, True])
def test_owner_membership_and_gradient_replacements_are_fresh(foreach):
    first, second = owner(1), owner(2)
    captured = harness(first, second)
    optimizer = torch.optim.AdamW([first], foreach=foreach)
    captured.zero_grad(optimizer=optimizer)
    optimizer.param_groups[0]["params"] = [second]
    first.grad = torch.full_like(first, 7)
    second.grad = torch.full_like(second, 9)
    addresses = [p.grad.data_ptr() for p in (first, second)]
    captured.zero_grad(optimizer=optimizer)
    assert [p.grad.data_ptr() for p in (first, second)] == addresses
    assert all(torch.count_nonzero(p.grad) == 0 for p in (first, second))


def test_standalone_capture_clear_retains_existing_behavior():
    present, absent = owner(3), owner(4)
    absent.grad = None
    captured = harness(present, absent)
    address = present.grad.data_ptr()
    captured.zero_grad()
    assert present.grad.data_ptr() == address
    assert torch.count_nonzero(present.grad) == 0
    assert absent.grad is None
