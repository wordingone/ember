# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Continuation facts preserve sparse clocks and observed zero-gradient participation."""
import hour_test_support
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hour_test_support import root, source
import torch
import checkpoint_artifacts as artifacts
import parameter_counter as counter
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cia_hour


class ContinuationStateTests(unittest.TestCase):
    def test_live_state_mismatch_refuses_before_restore_can_replace_it(self):
        child = dict(data_cursor={'global_step': 1}, rng_state_sha256={'cpu': 'a', 'cuda': 'b'})
        live = dict(facts={'parameters': {'weight': 'different'}},
                    data_cursor=child['data_cursor'], rng_state_sha256=child['rng_state_sha256'])
        def reopened(*args, **kwargs):
            kwargs['_facts'].update(parameters={'weight': 'published'})
        with patch.object(counter, '_cia_realization_receipt', side_effect=reopened), \
                patch.object(artifacts, 'load_checkpoint_artifacts') as restore:
            with self.assertRaisesRegex(ValueError, 'live state differs'):
                cia_hour.verify_checkpoint_restore(SimpleNamespace(GIB=1024**3), None, None,
                    {}, {'config_sha256': 'c'}, Path('fixture'), child, before=live)
            restore.assert_not_called()

    def test_zero_gradient_advances_clock_without_inventing_inactive_state(self):
        active = torch.nn.Parameter(torch.ones(8, dtype=torch.bfloat16))
        inactive = torch.nn.Parameter(torch.ones(8, dtype=torch.bfloat16))
        inventory = {'active': active, 'inactive': inactive}
        model = SimpleNamespace(parameter_inventory=lambda: inventory)
        optimizer = torch.optim.AdamW(list(inventory.values()), lr=.001, weight_decay=0, fused=True)
        cursor = dict(shard='0', record_index=4096, global_step=1, tokens_seen=4096)
        identity = {'param_groups': [{'params': list(inventory)}]}
        runner = SimpleNamespace(GIB=1024**3)
        with patch.object(artifacts, 'cia_optimizer_identity', return_value=identity):
            before = cia_hour.continuation_state(runner, model, optimizer, cursor, torch.device('cpu'))
            active.grad = torch.zeros_like(active)
            optimizer.step()
            after = cia_hour.continuation_state(runner, model, optimizer, cursor, torch.device('cpu'))
        self.assertEqual(before['facts']['parameters'], after['facts']['parameters'])
        self.assertEqual(before['facts']['optimizer'], {})
        self.assertEqual(after['facts']['optimizer']['active']['step'], 1)
        self.assertNotIn('inactive', after['facts']['optimizer'])
        self.assertEqual(after['data_cursor'], cursor)
        self.assertIsNot(after['data_cursor'], cursor)
        self.assertEqual(before['rng_state_sha256'], after['rng_state_sha256'])
        self.assertEqual(sorted(name for name, value in inventory.items() if value.grad is not None), ['active'])


if __name__ == '__main__':
    torch.set_num_threads(2)
    unittest.main()
