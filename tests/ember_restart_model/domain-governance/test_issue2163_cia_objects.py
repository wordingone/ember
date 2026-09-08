# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fixed tensor checkpoint mechanics; no smaller learning model is constructed."""
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
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import checkpoint_artifacts
from src.ember.model.cia_inventory import equation_inventory


class CIAObjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'objects').mkdir()
        self.index = {'schema_version': 'ember-cia-expert-index-v1', 'candidate_revision': 'CIA3-R1-N61',
                      'experts': [{'expert_id': i, 'sha256': hashlib.sha256(str(i).encode()).hexdigest(), 'bytes': 1} for i in range(25)]}

    def publish(self, payload):
        path = self.root / 'pending.pt'
        torch.save(payload, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.index['experts'][0].update(sha256=digest, bytes=path.stat().st_size)
        path.rename(self.root / 'objects' / (digest + '.pt'))
        return digest

    def read(self):
        content = json.dumps(self.index).encode()
        index_path = self.root / 'index.json'
        index_path.write_bytes(content)
        return checkpoint_artifacts.read_cia_expert_object(index_path,
            expected_index_sha256=hashlib.sha256(content).hexdigest(), expert_id=0)

    def test_swapped_bytes_refused_before_deserialization(self):
        digest = self.publish({'anything': torch.ones(1)})
        torch.save({'substituted_valid_tensor_file': torch.zeros(7)}, self.root / 'objects' / (digest + '.pt'))
        with self.assertRaisesRegex(ValueError, 'digest or size'):
            self.read()

    def test_wrong_index_digest_refused(self):
        path = self.root / 'index.json'
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'index digest'):
            checkpoint_artifacts.read_cia_expert_object(path, expected_index_sha256='0'*64, expert_id=0)

    def test_reused_global_object_identity_refused(self):
        self.index['experts'][1]['sha256'] = self.index['experts'][0]['sha256']
        with self.assertRaisesRegex(ValueError, 'reused'):
            self.read()

    def test_missing_selected_object_refused(self):
        with self.assertRaisesRegex(ValueError, 'cannot be inspected'):
            self.read()

    def test_wrong_payload_expert_refused(self):
        self.publish({'schema_version': 'ember-cia-expert-object-v1', 'candidate_revision': 'CIA3-R1-N61', 'expert_id': 1, 'model': {}})
        with self.assertRaisesRegex(ValueError, 'payload identity'):
            self.read()

    def candidate(self):
        root = self.root / '.checkpoint-quarantine' / 'candidate-objects'
        root.mkdir(parents=True)
        (root / '.writer-lease.json').write_text(json.dumps({'pid': os.getpid(), 'started_at_ns': 1}))
        return root

    def test_index_refuses_missing_population_and_preserves_no_final_index(self):
        root = self.candidate()
        with self.assertRaisesRegex(ValueError, 'exactly 25'):
            checkpoint_artifacts.write_cia_expert_index(root, records=[], max_total_object_bytes=100)
        with self.assertRaisesRegex(ValueError, 'aggregate'):
            checkpoint_artifacts.write_cia_expert_index(root, records=self.index['experts'], max_total_object_bytes=1)
        with self.assertRaisesRegex(ValueError, 'cannot be inspected'):
            checkpoint_artifacts.write_cia_expert_index(root, records=self.index['experts'], max_total_object_bytes=100)
        self.assertEqual(list(root.glob('expert-index-*')), [])
        self.assertEqual(list(root.glob('.cia-index-*')), [])

    def test_writer_requires_quarantine_and_owned_lease(self):
        with self.assertRaisesRegex(ValueError, 'quarantine'):
            checkpoint_artifacts.write_cia_expert_object(self.root, expert_id=0, tensors={}, max_serialized_bytes=1)
        root = self.candidate()
        (root / '.writer-lease.json').write_text(json.dumps({'pid': -1}))
        with self.assertRaisesRegex(ValueError, 'writer lease'):
            checkpoint_artifacts.write_cia_expert_object(root, expert_id=0, tensors={}, max_serialized_bytes=1)
        self.assertFalse((root / 'objects').exists())

    def test_writer_rejects_overlapping_external_storages(self):
        root = self.candidate()
        tensors = {s.name: torch.full(s.shape, 0.125, dtype=torch.bfloat16)
                   for s in equation_inventory() if s.expert == 0}
        names = list(tensors)[:2]
        count = tensors[names[0]].numel()
        backing = bytearray(count * 2 + 2)
        for offset, name in enumerate(names):
            tensors[name] = torch.frombuffer(backing, dtype=torch.bfloat16, count=count, offset=offset * 2).view(tensors[name].shape)
        with self.assertRaisesRegex(ValueError, 'storage alias'):
            checkpoint_artifacts.write_cia_expert_object(root, expert_id=0, tensors=tensors, max_serialized_bytes=113246208*2+4194304)
        self.assertFalse((root / 'objects').exists())

    def test_durable_writer_never_replaces_existing_object(self):
        root = self.candidate()
        tensors = {s.name: torch.full(s.shape, 0.125, dtype=torch.bfloat16)
                   for s in equation_inventory() if s.expert == 0}
        allowance = 113246208 * 2 + 4194304
        record = checkpoint_artifacts.write_cia_expert_object(root, expert_id=0, tensors=tensors, max_serialized_bytes=allowance)
        original_path = root / 'objects' / (record['sha256'] + '.pt')
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), record['sha256'])
        with self.assertRaises(FileExistsError):
            checkpoint_artifacts.write_cia_expert_object(root, expert_id=0, tensors=tensors, max_serialized_bytes=allowance)
        with self.assertRaisesRegex(RuntimeError, 'transient scratch'):
            checkpoint_artifacts.write_cia_expert_object(root, expert_id=0, tensors=tensors, max_serialized_bytes=1)
        self.index['experts'][0] = record
        content = json.dumps(self.index).encode()
        index_path = root / 'index.json'
        index_path.write_bytes(content)
        loaded = checkpoint_artifacts.read_cia_expert_object(index_path, expected_index_sha256=hashlib.sha256(content).hexdigest(), expert_id=0)
        self.assertEqual(sum(t.numel() for t in loaded.values()), 113246208)
        del loaded
        tensors[next(iter(tensors))].view(-1)[0] = 0.25
        changed = checkpoint_artifacts.write_cia_expert_object(root, expert_id=0, tensors=tensors, max_serialized_bytes=allowance)
        self.assertNotEqual(changed['sha256'], record['sha256'])
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), record['sha256'])
        self.assertEqual(len(list((root / 'objects').iterdir())), 2)

    def test_hidden_backing_storage_refused(self):
        tensors = {s.name: torch.full(s.shape, 0.125, dtype=torch.bfloat16)
                   for s in equation_inventory() if s.expert == 0}
        name = next(iter(tensors))
        original = tensors[name]
        backing = torch.full((original.numel() + 1,), 0.125, dtype=torch.bfloat16)
        backing[-1] = float('nan')
        tensors[name] = backing[:-1].view(original.shape)
        self.publish({'schema_version': 'ember-cia-expert-object-v1', 'candidate_revision': 'CIA3-R1-N61', 'expert_id': 0, 'model': tensors})
        with self.assertRaisesRegex(ValueError, 'tensor mismatch'):
            self.read()

    def test_full_shape_bundle_reopened_and_verified(self):
        tensors = {s.name: torch.full(s.shape, 0.125, dtype=torch.bfloat16)
                   for s in equation_inventory() if s.expert == 0}
        self.publish({'schema_version': 'ember-cia-expert-object-v1', 'candidate_revision': 'CIA3-R1-N61', 'expert_id': 0, 'model': tensors})
        actual = self.read()
        self.assertEqual(sum(t.numel() for t in actual.values()), 113_246_208)
        for name in tensors:
            torch.testing.assert_close(actual[name], tensors[name], rtol=0, atol=0)


if __name__ == '__main__':
    torch.set_num_threads(1)
    unittest.main()
