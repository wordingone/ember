# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Opt-in full-population expert-bank roundtrip; not complete checkpoint recovery."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import checkpoint_artifacts
from ember.model.ember_v0_decoder import CIADecoder


@unittest.skipUnless(os.environ.get('EMBER_CIA_CPU_CONFORMANCE') == '1', 'full population RAM/disk envelope required')
class CIAIndexTests(unittest.TestCase):
    def test_complete_population_is_written_indexed_and_reopened(self):
        torch.set_num_threads(1)
        model = CIADecoder().materialize_cpu(seed=2163)
        model.apply_update_support('memory-only')
        weights = model.parameter_inventory()
        self.assertEqual(sum(p.numel() for p in weights.values()), 3_082_539_008)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / '.checkpoint-quarantine' / 'candidate-full-index'
            candidate.mkdir(parents=True)
            (candidate / '.writer-lease.json').write_text(json.dumps({'pid': os.getpid(), 'started_at_ns': 1}))
            records = []
            for expert in range(25):
                tensors = {name: tensor.detach() for name, tensor in weights.items() if name.startswith(f'experts.{expert}.')}
                records.append(checkpoint_artifacts.write_cia_expert_object(candidate, expert_id=expert,
                    tensors=tensors, max_serialized_bytes=113246208*2+4194304))
            actual_object_bytes = sum(record['bytes'] for record in records)
            self.assertLess(actual_object_bytes, 6 * 1024**3)
            index = checkpoint_artifacts.write_cia_expert_index(candidate, records=records, max_total_object_bytes=6*1024**3)
            index_path = candidate / index['path']
            self.assertEqual(hashlib.sha256(index_path.read_bytes()).hexdigest(), index['sha256'])
            recovered_elements = 0
            for expert in range(25):
                restored = checkpoint_artifacts.read_cia_expert_object(index_path, expected_index_sha256=index['sha256'], expert_id=expert)
                for name, tensor in restored.items():
                    torch.testing.assert_close(tensor, weights[name], rtol=0, atol=0)
                    recovered_elements += tensor.numel()
                del restored
            self.assertEqual(recovered_elements, 2_831_155_200)
            print(json.dumps({'physical_model_elements': 3_082_539_008, 'expert_elements_reopened': recovered_elements,
                              'expert_object_bytes': actual_object_bytes, 'index': index, 'objects': records}), flush=True)
            # A valid but wrong object's bytes cannot be substituted under the old identity.
            victim = candidate / 'objects' / (records[0]['sha256'] + '.pt')
            victim.write_bytes(b'changed-after-index')
            with self.assertRaisesRegex(ValueError, 'digest or size'):
                checkpoint_artifacts.read_cia_expert_object(index_path, expected_index_sha256=index['sha256'], expert_id=0)


if __name__ == '__main__':
    unittest.main()
