# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Inventory rebuilding stays live while avoiding duplicate schema construction."""
import cProfile
import pytest
import torch
from ember.model.ember_v0_decoder import CIADecoder
from ember.model.ember_v0_inventory import TensorSpec


def test_inventory_constructs_one_fresh_schema_per_call():
    model = CIADecoder()
    for _ in range(2):
        with cProfile.Profile() as profiler:
            inventory = model.parameter_inventory()
        builds = sum(row.callcount for row in profiler.getstats()
                     if row.code is TensorSpec.__init__.__code__)
        assert len(inventory) == 1195
        assert builds == 1195, 'inventory must construct one fresh schema, without duplicate work'


@pytest.mark.parametrize('change', ['shape', 'dtype', 'missing', 'extra_registered', 'alias'])
def test_inventory_revalidates_changes_between_calls(change):
    model = CIADecoder()
    before = model.parameter_inventory()
    key = 'modality__weight'
    if change == 'shape':
        model.weights[key] = torch.nn.Parameter(torch.empty((7, 1024), dtype=torch.bfloat16, device='meta'))
    elif change == 'dtype':
        model.weights[key] = torch.nn.Parameter(torch.empty((8, 1024), dtype=torch.float32, device='meta'))
    elif change == 'missing':
        del model.weights[key]
    elif change == 'extra_registered':
        model.register_parameter('additional', torch.nn.Parameter(torch.empty(1, device='meta')))
    elif change == 'alias':
        model.weights['layers__0__attention_norm__weight'] = model.weights['final_norm__weight']
    with pytest.raises(ValueError):
        model.parameter_inventory()
    assert len(before) == 1195
