# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""SLEEP-1 direct mode (#2119 ruling (b)): target choice, cursor, norms, and the CIA lineage rule it relies on."""
import importlib
import sys
from pathlib import Path

import pytest
import torch

TOOLS = Path(__file__).resolve().parents[2] / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parents[3]))
direct = importlib.import_module('sleep_direct_v1')
counter = importlib.import_module('parameter_counter')


def test_routed_targets_are_the_two_most_routed_trainable_layer23_experts():
    counts = {'23:5': 99, '23:8': 40, '23:1': 40, '23:0': 7, '21:0': 500}
    assert direct.pick_routed(counts, (0, 1, 8, 18)) == ['experts.1.layers.23.down.weight', 'experts.8.layers.23.down.weight']


def test_routed_targets_refuse_when_fewer_than_two_trainable_experts_route():
    with pytest.raises(ValueError):
        direct.pick_routed({'23:5': 9, '23:0': 3}, (0, 1, 8, 18))


def test_fixed_targets_are_the_layer11_shared_projections():
    assert direct.FIXED_TARGETS == ('layers.11.shared.up.weight', 'layers.11.shared.gate.weight', 'layers.11.shared.down.weight')


def test_cursor_keeps_shard_and_record_and_advances_step_and_tokens():
    c = dict(shard='7', record_index=11, global_step=100, tokens_seen=5000)
    assert direct.advance_cursor(c, 3, 288) == dict(shard='7', record_index=11, global_step=103, tokens_seen=5288)


def test_relative_norm():
    w0 = torch.ones(4, 4)
    inv = {'w': torch.nn.Parameter(w0 * 1.01)}
    assert abs(direct.relative_norms({'w': w0}, inv)['w'] - 0.01) < 1e-5


def test_receipt_carries_the_ruled_deviation_sentence():
    assert direct.DEVIATION == 'full-rank update on 5 weights, not rank-64 experts; paper-fidelity deferred to SLEEP-2'


def _facts(params, steps):
    return dict(parameters=params, elements={n: 1 for n in params}, optimizer={n: {'step': s} for n, s in steps.items()})


def _manifest(step, tokens, flags):
    return dict(architecture_config={}, model_config_sha256='m', contract_sha256='c', launch_seed=1,
                placement={n: dict(device='cuda:0', requires_grad=f) for n, f in flags.items()},
                optimizer_identity={'lr': 3e-4}, data_cursor=dict(global_step=step, tokens_seen=tokens),
                expert_genesis_sha256={}, checkpoint_manifest_sha256='p', _parent_counter_receipt_sha256='r')


FLAGS = {'t': True, 'u': True, 'f': False}


def test_lineage_admits_a_target_whose_bytes_and_clock_both_move():
    parent, child = _manifest(10, 0, FLAGS), _manifest(13, 288, FLAGS)
    got = counter._cia_derive_first_lineage('root', parent, _facts({'t': 'a', 'u': 'b', 'f': 'c'}, {'t': 10, 'u': 10}), child,
                                            _facts({'t': 'A', 'u': 'b', 'f': 'c'}, {'t': 13, 'u': 10}), owner_update_counts={'t': 3})
    assert got['changed_parameters'] == ['t'] and got['step_delta'] == 3 and got['token_delta'] == 288


def test_lineage_refuses_a_frozen_weight_whose_bytes_move():
    parent, child = _manifest(10, 0, FLAGS), _manifest(13, 288, FLAGS)
    with pytest.raises(ValueError, match='inactive parameter bytes differ'):
        counter._cia_derive_first_lineage('root', parent, _facts({'t': 'a', 'u': 'b', 'f': 'c'}, {'t': 10, 'u': 10}), child,
                                          _facts({'t': 'A', 'u': 'B', 'f': 'c'}, {'t': 13, 'u': 10}), owner_update_counts={'t': 3})


def test_lineage_refuses_a_placement_left_with_training_flags():
    """The driver restores every requires_grad flag before publish; a child left with non-target flags off differs."""
    parent, child = _manifest(10, 0, FLAGS), _manifest(13, 288, dict(FLAGS, u=False))
    with pytest.raises(ValueError, match='placement differ'):
        counter._cia_derive_first_lineage('root', parent, _facts({'t': 'a', 'u': 'b', 'f': 'c'}, {'t': 10, 'u': 10}), child,
                                          _facts({'t': 'A', 'u': 'b', 'f': 'c'}, {'t': 13, 'u': 10}), owner_update_counts={'t': 3})


def test_step_context_is_null_on_cpu_and_candidate_step_on_cuda():
    sleep = importlib.import_module('sleep_consolidate_v1')

    class Model:
        def candidate_step(self):
            raise AssertionError('cpu must not enter candidate_step')
    with sleep.step_context(Model(), 'cpu'):
        pass
    marker = object()

    class Cuda:
        def candidate_step(self):
            return marker
    assert sleep.step_context(Cuda(), 'cuda:0') is marker
