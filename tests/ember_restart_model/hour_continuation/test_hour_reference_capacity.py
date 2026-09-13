# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Preflight a real extra input pack without crediting an extra measured update."""
import hour_test_support
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cia_hour


class Stream:
    def check_cursor_span(self, **kwargs):
        self.span = kwargs
        return dict(kwargs)

    def next_episode(self, *, shard_index, token_offset, sequence_length):
        return (dict(token_ids=[1]*sequence_length, target_ids=[2]*sequence_length),
                dict(shard_index=shard_index, token_offset=token_offset+sequence_length))


class ReferenceCapacityTests(unittest.TestCase):
    def test_reference_pack_is_reserved_and_bound_without_extending_measured_geometry(self):
        with tempfile.TemporaryDirectory(prefix='reference-capacity-', dir=Path(__file__).parent) as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(root.parent, Path(__file__).resolve().parent)
            paths = [root/name for name in ('receipt.json', 'tokenizer.json', 'ledger.json')]
            for path in paths:
                path.write_bytes(b'{}')
            sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            stream = Stream()
            data = dict(shard_ledger_path=str(paths[2]), shard_ledger_sha256=sha(paths[2]),
                        receipt_sha256=sha(paths[0]), tokenizer_sha256=sha(paths[1]),
                        cursor=dict(shard_index=0, token_offset=0))
            geometry = dict(measured_steps=2)
            runner = SimpleNamespace(geometry_counts=lambda geometry, hour: (1024, 4, 1, 2),
                open_input_stream=lambda data: (stream, *paths), file_sha256=sha,
                canonical=lambda value: json.dumps(value, sort_keys=True).encode())
            prepared = cia_hour.prepare_inputs(runner, data, geometry)
            self.assertEqual(stream.span['tokens'], 4*4096)
            self.assertEqual(prepared['geometry'], geometry)
            self.assertEqual(prepared['binding']['maximum_planned_positions'], 4*4096)
            self.assertEqual(prepared['binding']['reference_positions_reserved'], 4096)
            packs = [prepared['first']] + [prepared['packs'].next_pack() for _ in range(3)]
            self.assertEqual([pack['cursor_before']['token_offset'] for pack in packs],
                             [0, 4096, 8192, 12288])
            with self.assertRaisesRegex(ValueError, 'capacity exhausted'):
                prepared['packs'].next_pack()


if __name__ == '__main__':
    unittest.main()
