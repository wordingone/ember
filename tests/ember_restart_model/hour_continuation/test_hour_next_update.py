# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Exercise auxiliary accounting with a real sparse AdamW update and state facts."""
import hour_test_support
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hour_test_support import root, source
import torch
import checkpoint_artifacts as artifacts
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cia_hour
import cia_step_runner as step_runner


class NextUpdateTests(unittest.TestCase):
    def setUp(self):
        self.active = torch.nn.Parameter(torch.ones(8, dtype=torch.bfloat16))
        self.inactive = torch.nn.Parameter(torch.ones(8, dtype=torch.bfloat16))
        self.inventory = {'active': self.active, 'inactive': self.inactive}
        self.model = SimpleNamespace(parameter_inventory=lambda: self.inventory)
        self.optimizer = torch.optim.AdamW(list(self.inventory.values()), lr=.001, weight_decay=0, fused=True)
        self.device = torch.device('cpu')
        self.cursor = dict(shard='8', record_index=12, global_step=2, tokens_seen=12)
        self.child = dict(data_cursor=self.cursor)
        self.pack = dict(token_ids=list(range(6)), target_ids=list(range(6)),
            document_starts=[0, 3], positions=[[i, 0, 0] for i in range(6)],
            cursor_before=dict(shard_index=8, token_offset=12),
            cursor_after=dict(shard_index=8, token_offset=18))
        self.identity = dict(run_id='fixture', source_sha256={'source': 'digest'}, gpu_uuid='CPU-fixture',
            geometry=dict(sequence_length=3, documents_per_step=2), hour=dict(arm='treatment'))
        self.capture = SimpleNamespace(invalidate=Mock())
        self.applied = Mock()
        self.runner = SimpleNamespace(GIB=1024**3,
            attention_selection=lambda identity: step_runner.attention_selection(identity),
            INPUT_FIELDS=('token_ids', 'target_ids', 'positions', 'document_starts'),
            canonical=lambda value: json.dumps(value, sort_keys=True).encode(),
            document_lengths=lambda starts, total: (3, 3),
            execution_mode=lambda identity: 'resident-dynamic-capture',
            local_routing_mode=lambda identity: 'per-chunk',
            expert_owner_index=lambda inventory: {}, measure_step=Mock(side_effect=self.step))
        self.native_identity = patch.object(artifacts, 'cia_optimizer_identity',
            return_value={'param_groups': [{'params': list(self.inventory)}]})
        self.native_identity.start()
        self.addCleanup(self.native_identity.stop)
        self.terminal = cia_hour.continuation_state(self.runner, self.model, self.optimizer, self.cursor, self.device)

    def step(self, *args, **kwargs):
        self.active.grad = torch.zeros_like(self.active)
        self.optimizer.step()
        return dict(applied_positions=6, loss=1.25)

    def execute(self):
        with patch.object(cia_hour, 'bind_hour_capture', return_value=(self.capture, None)):
            return cia_hour.next_update_reference(self.runner, self.model, self.optimizer, self.inventory,
                self.identity, self.pack, self.child, self.terminal, self.device, self.applied)

    def test_real_zero_gradient_update_is_physical_but_uncredited(self):
        reference = self.execute()
        self.assertEqual(reference['geometry']['positions_per_update'], 6)
        self.assertEqual(reference['gradient_present'], ['active'])
        self.assertEqual(reference['before']['facts']['parameters'], reference['after']['facts']['parameters'])
        self.assertEqual(reference['after']['facts']['optimizer']['active']['step'], 1)
        self.assertNotIn('inactive', reference['after']['facts']['optimizer'])
        self.assertEqual(reference['after']['data_cursor']['global_step'], 3)
        self.assertEqual(self.child['data_cursor']['global_step'], 2)
        self.assertEqual(reference['accounting'], dict(positions_physically_applied=6,
            credited_toward_governed_hour=0, included_in_published_terminal_lineage=False))
        self.applied.assert_called_once_with(6)
        self.assertTrue(self.runner.measure_step.call_args.kwargs['record'])
        self.capture.invalidate.assert_called_once()
        self.assertTrue(all(p.grad is None for p in self.inventory.values()))

    def test_wrong_cursor_refuses_before_any_update(self):
        self.pack['cursor_before']['token_offset'] += 1
        with self.assertRaisesRegex(ValueError, 'published cursor'):
            self.execute()
        self.runner.measure_step.assert_not_called()
        self.applied.assert_not_called()

    def test_failed_update_releases_capture_and_gradient_storage(self):
        def fail(*args, **kwargs):
            self.active.grad = torch.zeros_like(self.active)
            raise RuntimeError('fixture update failure')
        self.runner.measure_step.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'fixture update failure'):
            self.execute()
        self.capture.invalidate.assert_called_once()
        self.applied.assert_not_called()
        self.assertIsNone(self.active.grad)

    def test_auxiliary_execution_records_explicit_attention_settings(self):
        self.identity.update(execution_mode='resident-dynamic-capture', optimizer={'fused': True},
            hour=dict(schema='governed-hour-v1', arm='treatment', minimum_wall_seconds=3600, minimum_measured_steps=1024),
            attention_backend='math', attention_recompute='non_reentrant_checkpoint')
        reference = self.execute()
        self.assertEqual(reference['execution_path'].get('attention_backend'), 'math')
        self.assertEqual(reference['execution_path'].get('attention_recompute'), 'non_reentrant_checkpoint')


if __name__ == '__main__':
    torch.set_num_threads(2)
    unittest.main()
