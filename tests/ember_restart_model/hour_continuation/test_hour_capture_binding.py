# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Use the actual decoder binding to prepare a fresh reference exemplar."""
import hour_test_support
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from hour_test_support import root, source
import torch
from test_issue1945_dynamic_capture_integration import Model
import cia_hour


class HourCaptureTests(unittest.TestCase):
    def test_reference_binding_replaces_invalidated_capture_with_same_execution_settings(self):
        model = Model()
        lengths = model._cuda_execution._geometry_lengths
        raw = torch.zeros(3, dtype=torch.int32)
        collector = lambda *args: None
        buffers = SimpleNamespace(raw=raw, collector=collector)
        runner = SimpleNamespace(MODE_SOURCES={'resident-dynamic-capture': ()},
            execution_mode=lambda identity: identity['execution_mode'],
            local_routing_mode=lambda identity: identity['local_routing_mode'],
            capture_loss_kwargs=lambda model, identity, lengths: dict(loss_fn=lambda x,y: x.sum()),
            routing_buffers=lambda lengths, device: buffers)
        identity = dict(execution_mode='resident-dynamic-capture', local_routing_mode='per-chunk')
        first, _ = cia_hour.bind_hour_capture(runner, model, identity, lengths, torch.device('cpu'))
        first._recorded = {0: object()}
        fresh, actual_buffers = cia_hour.bind_hour_capture(runner, model, identity, lengths, torch.device('cpu'))
        self.assertIsNot(fresh, first)
        self.assertIs(model._cuda_execution.segmented, fresh)
        self.assertEqual(first._recorded, {})
        self.assertEqual(fresh._recorded, {})
        self.assertIs(actual_buffers, buffers)
        self.assertTrue(fresh._cia_capture_experts)
        self.assertEqual(fresh._cia_lengths, lengths)
        self.assertIs(fresh._cia_collector, collector)
        self.assertTrue(all(segment.fn.keywords['local_routing_mode'] == 'per-chunk'
                            for segment in fresh.segments))

    def test_control_does_not_bind_capture(self):
        runner = SimpleNamespace(MODE_SOURCES={}, execution_mode=lambda identity: None)
        self.assertEqual(cia_hour.bind_hour_capture(runner, None, {}, (), None), (None, None))


if __name__ == '__main__':
    torch.set_num_threads(2)
    unittest.main()
