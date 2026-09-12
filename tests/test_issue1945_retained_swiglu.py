# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Retained dynamic arithmetic preserves exact owner gradients without recomputation."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ember.model.retained_residency', ROOT / 'src/ember/model/ember_v0_residency.py')
residency = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = residency
spec.loader.exec_module(residency)


def grouped(a, b, offsets):
    start, parts = 0, []
    for group, end in enumerate(offsets.tolist()):
        parts.append(a[start:end] @ b[group])
        start = end
    return torch.cat(parts)


@pytest.mark.parametrize('backend,calls', [('dynamic', 1), ('native', 2)])
@pytest.mark.parametrize('counts', [(3, 0, 1, 3), (0, 0, 0, 7), (1, 31, 33, 5)])
def test_exact_owner_gradients_and_forward_count(backend, calls, counts):
    torch.manual_seed(41)
    stores = [torch.randn(s, dtype=torch.float64) * .03 for s in ((4, 6, 4), (4, 6, 4), (4, 4, 6))]
    owners = [torch.nn.Parameter(store[g], requires_grad=(i % 3 != 1))
              for i, (store, g) in enumerate((s, g) for s in stores for g in range(4))]
    value = torch.randn(sum(counts), 4, dtype=torch.float64, requires_grad=True)
    offsets = torch.tensor(counts, dtype=torch.int32).cumsum(0).to(torch.int32)
    execution = SimpleNamespace(check=lambda: None, layer_groups=lambda layer: tuple(stores), pending=0, step_id=4)
    def arithmetic(a, up, gate, down, offs, selected='native', chunk_ends=None):
        return grouped(torch.nn.functional.silu(grouped(a, gate.transpose(1, 2), offs)) *
                       grouped(a, up.transpose(1, 2), offs), down.transpose(1, 2), offs)
    chunk_ends = offsets[:, None] if backend == 'dynamic' else None
    with patch.object(residency, '_grouped_swiglu', side_effect=arithmetic) as observed:
        result = residency._ResidentGroupedSwiGLU.apply(value, offsets, execution, 1, backend, chunk_ends, *owners)
        assert execution.pending == 1
        result.square().sum().backward()
        assert execution.pending == 0
        actual = [p.grad.clone() if p.grad is not None else None for p in [value, *owners]]
        assert observed.call_count == calls
        assert all(call.args[-1] is chunk_ends for call in observed.call_args_list)
    for p in [value, *owners]:
        p.grad = None
    groups = [torch.stack(owners[i:i+4]) for i in (0, 4, 8)]
    expected = arithmetic(value, *groups, offsets)
    expected.square().sum().backward()
    assert torch.equal(result, expected)
    for got, owner in zip(actual, [value, *owners]):
        assert (got is None) == (owner.grad is None)
        if got is not None:
            assert torch.equal(got, owner.grad)
