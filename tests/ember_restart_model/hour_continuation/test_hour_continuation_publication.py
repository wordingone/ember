# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Restore the published state and cursor after auxiliary success or failure."""
import hour_test_support
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_hour_next_update import NextUpdateTests, cia_hour


class PublicationTests(NextUpdateTests):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.custody = Path(temporary.name)
        (self.custody/'source').write_bytes(b'fixture source')
        self.runner.ROOT = self.custody
        self.runner.file_sha256 = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.runner.checked_sha = lambda value: value
        self.runner._write_new = self.write
        self.identity['source_sha256'] = {'source': self.runner.file_sha256(self.custody/'source')}
        self.identity['geometry']['warm_steps'] = 1
        self.identity['data'] = {'receipt_sha256': 'receipt'}
        self.child['checkpoint_manifest_sha256'] = 'manifest'
        self.packs = SimpleNamespace(cursor=dict(self.pack['cursor_before']), index=2, next_pack=self.next_pack)
        self.prepared = dict(packs=self.packs)

    def write(self, path, value):
        with path.open('x') as f:
            json.dump(value, f)

    def next_pack(self):
        self.packs.cursor = dict(self.pack['cursor_after'])
        self.packs.index += 1
        return copy.deepcopy(self.pack)

    def publish(self):
        # Codec restoration is a separate production-path test. This fixture
        # isolates whether orchestration always calls it and restores the pack cursor.
        with patch.object(cia_hour, 'verify_checkpoint_restore', side_effect=lambda *a: self.optimizer.state.clear()), \
                patch.object(cia_hour, 'bind_hour_capture', return_value=(self.capture, None)):
            return cia_hour.publish_continuation_reference(self.runner, self.model, self.optimizer,
                self.inventory, self.identity, self.custody, self.child, self.terminal, self.prepared,
                self.device, self.applied, 3601.0, {'joules': 123.0})

    def test_publication_keeps_terminal_step_and_reconciles_separate_physical_count(self):
        descriptor = self.publish()
        reference = json.loads((self.custody/'continuation-reference.json').read_bytes())
        self.assertEqual(reference['before'], self.terminal)
        self.assertEqual(reference['restored_from']['global_step'], 2)
        self.assertEqual(reference['after']['data_cursor']['global_step'], 3)
        self.assertEqual(self.packs.cursor, self.pack['cursor_before'])
        self.assertEqual(self.packs.index, 2)
        self.assertEqual(cia_hour.continuation_state(self.runner, self.model, self.optimizer,
            self.cursor, self.device), self.terminal)
        hour = dict(continuation=descriptor, applied_positions=12, measured_updates=1,
                    child_manifest_sha256='manifest')
        self.assertEqual(cia_hour.verify_continuation_accounting(self.runner, self.custody,
            hour, self.identity, 18), 6)
        with self.assertRaisesRegex(ValueError, 'physical positions differ'):
            cia_hour.verify_continuation_accounting(self.runner, self.custody, hour, self.identity, 24)
        reference['accounting']['positions_physically_applied'] = 12
        (self.custody/'continuation-reference.json').write_text(json.dumps(reference))
        descriptor['reference_sha256'] = self.runner.file_sha256(self.custody/'continuation-reference.json')
        with self.assertRaisesRegex(ValueError, 'auxiliary accounting differs'):
            cia_hour.verify_continuation_accounting(self.runner, self.custody, hour, self.identity, 24)

    def test_pack_write_failure_restores_cursor_without_publishing_reference(self):
        def write(path, value):
            if path.name == 'continuation-next-pack.json':
                raise OSError('fixture write failure')
            self.write(path, value)
        self.runner._write_new = write
        with self.assertRaisesRegex(OSError, 'fixture write failure'):
            self.publish()
        self.assertEqual(self.packs.cursor, self.pack['cursor_before'])
        self.assertEqual(self.packs.index, 2)
        self.runner.measure_step.assert_not_called()
        self.assertFalse((self.custody/'continuation-reference.json').exists())

    def test_legacy_hour_requires_exact_physical_count(self):
        hour = dict(applied_positions=12)
        self.assertEqual(cia_hour.verify_continuation_accounting(self.runner, self.custody, hour, self.identity, 12), 0)
        with self.assertRaisesRegex(ValueError, 'legacy hour physical positions differ'):
            cia_hour.verify_continuation_accounting(self.runner, self.custody, hour, self.identity, 18)

    def test_restore_failure_still_restores_input_cursor_and_refuses_publication(self):
        with patch.object(cia_hour, 'verify_checkpoint_restore', side_effect=ValueError('fixture restore failure')), \
                patch.object(cia_hour, 'bind_hour_capture', return_value=(self.capture, None)):
            with self.assertRaisesRegex(ValueError, 'fixture restore failure'):
                cia_hour.publish_continuation_reference(self.runner, self.model, self.optimizer,
                    self.inventory, self.identity, self.custody, self.child, self.terminal, self.prepared,
                    self.device, self.applied, 3601.0, {})
        self.assertEqual(self.packs.cursor, self.pack['cursor_before'])
        self.assertEqual(self.packs.index, 2)
        self.assertFalse((self.custody/'continuation-reference.json').exists())

    def test_rehashed_reference_or_terminal_attention_change_refuses(self):
        descriptor = self.publish()
        ref_path, terminal_path = (self.custody/name for name in
            ('continuation-reference.json', 'continuation-hour.json'))
        original_reference = json.loads(ref_path.read_bytes())
        original_terminal = json.loads(terminal_path.read_bytes())
        self.assertEqual(original_reference['execution_path'].get('attention_backend'), 'unforced')
        self.assertEqual(original_terminal.get('attention_recompute'), 'none')
        hour = dict(continuation=descriptor, applied_positions=12, measured_updates=1,
                    child_manifest_sha256='manifest')
        for target in ('reference', 'terminal'):
            for key, value in (('attention_backend', 'math'),
                               ('attention_recompute', 'non_reentrant_checkpoint')):
                reference, terminal = copy.deepcopy(original_reference), copy.deepcopy(original_terminal)
                if target == 'reference':
                    reference['execution_path'][key] = value
                else:
                    terminal[key] = value
                terminal_path.write_text(json.dumps(terminal))
                descriptor['hour_binding_sha256'] = self.runner.file_sha256(terminal_path)
                reference['hour_binding_sha256'] = descriptor['hour_binding_sha256']
                ref_path.write_text(json.dumps(reference))
                descriptor['reference_sha256'] = self.runner.file_sha256(ref_path)
                with self.subTest(target=target, key=key), self.assertRaisesRegex(ValueError, 'attention'):
                    cia_hour.verify_continuation_accounting(self.runner, self.custody, hour, self.identity, 18)


if __name__ == '__main__':
    unittest.main()
