# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CIA model-only load reds (lead ruling 82032 E3, #2119): one generation, no lineage walk, no optimizer, no replay.

Tiny physical fixtures on CPU only; no CUDA, no 3B object. The scorer that consumes the loader is a separate change."""
import builtins
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_issue2163_cia_transaction as fixture  # noqa: E402  (the tiny publish fixture)
import checkpoint_artifacts as artifacts  # noqa: E402


class ModelOnlyLoadTests(fixture.TransactionTests):
    # Inherits setUp (publishes nothing yet) but none of the parent's tests: they are skipped by overriding the names below.
    def manifest_sha(self):
        return hashlib.sha256((self.root / 'checkpoint-manifest.json').read_bytes()).hexdigest()

    def expert_objects(self):
        return sorted(p for p in (self.root / 'objects').rglob('*') if p.is_file())

    def test_model_only_tensors_equal_the_full_loader_bit_for_bit(self):
        receipt = self.publish()
        original = {name: value.detach().clone() for name, value in self.parameters.items()}
        tensors, load = artifacts.load_cia_checkpoint_model_only(self.root, expected_manifest_sha256=self.manifest_sha())
        self.assertEqual(set(tensors), set(original))
        for name, value in original.items():
            self.assertTrue(torch.equal(tensors[name], value), name)
            self.assertEqual(tensors[name].dtype, torch.bfloat16)
        self.assertIs(load['parent_walk_skipped'], True)
        self.assertIs(load['optimizer_loaded'], False)
        self.assertIs(load['replay_loaded'], False)
        self.assertIs(load['lineage_verified'], False)
        self.assertEqual(load['objects_verified'], 26)  # counted from the reads that completed: 1 core + 25 experts
        self.assertEqual(load['parameter_count'], 208)
        self.assertEqual(load['tensor_count'], 26)
        self.assertEqual(load['checkpoint_manifest_sha256'], self.manifest_sha())
        self.assertEqual(load['global_step'], 0)
        del receipt

    def test_objects_verified_equals_the_completed_reads(self):
        self.publish()
        real = artifacts.read_cia_expert_object
        calls = []

        def counting(*args, **kwargs):
            calls.append(kwargs.get('expert_id'))
            return real(*args, **kwargs)
        with patch.object(artifacts, 'read_cia_expert_object', counting):
            _, load = artifacts.load_cia_checkpoint_model_only(self.root)
        self.assertEqual(sorted(calls), list(range(25)))
        self.assertEqual(load['objects_verified'], 1 + len(calls))
        # a failed read raises and leaves no receipt, so on success the count is always the whole generation (1 + 25)
        victim = self.expert_objects()[3]
        victim.unlink()
        with self.assertRaises(ValueError):
            artifacts.load_cia_checkpoint_model_only(self.root)

    def test_never_opens_optimizer_or_replay_payloads(self):
        self.publish()
        forbidden = ('optimizer-state.pt', 'replay-state.pt')
        real_open = builtins.open
        real_path_open = Path.open
        opened = []

        def guarded_open(file, *args, **kwargs):
            opened.append(str(file))
            if any(name in str(file) for name in forbidden):
                raise AssertionError('model-only load opened ' + str(file))
            return real_open(file, *args, **kwargs)

        def guarded_path_open(self_path, *args, **kwargs):
            opened.append(str(self_path))
            if any(name in str(self_path) for name in forbidden):
                raise AssertionError('model-only load opened ' + str(self_path))
            return real_path_open(self_path, *args, **kwargs)
        with patch.object(builtins, 'open', guarded_open), patch.object(Path, 'open', guarded_path_open):
            artifacts.load_cia_checkpoint_model_only(self.root)
        self.assertTrue(any('checkpoint-manifest.json' in name for name in opened))

    def test_wrong_manifest_pin_refuses_before_any_object_read(self):
        self.publish()
        with patch.object(artifacts, 'read_cia_core_object', side_effect=AssertionError('object read before the pin check')):
            with self.assertRaisesRegex(ValueError, 'differs from the caller pin'):
                artifacts.load_cia_checkpoint_model_only(self.root, expected_manifest_sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'lowercase SHA-256'):
                artifacts.load_cia_checkpoint_model_only(self.root, expected_manifest_sha256='ABC')

    def test_tampered_manifest_refuses_under_its_old_pin(self):
        self.publish()
        pin = self.manifest_sha()
        path = self.root / 'checkpoint-manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['launch_seed'] = 8
        path.write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'differs from the caller pin'):
            artifacts.load_cia_checkpoint_model_only(self.root, expected_manifest_sha256=pin)

    def test_unknown_manifest_field_refuses(self):
        self.publish()
        path = self.root / 'checkpoint-manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['surprise'] = 1
        path.write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'schema mismatch'):
            artifacts.load_cia_checkpoint_model_only(self.root)

    def test_missing_expert_object_refuses(self):
        self.publish()
        objects = self.expert_objects()
        self.assertGreaterEqual(len(objects), 26)
        victim = objects[-1]
        victim.unlink()
        with self.assertRaisesRegex(ValueError, 'cannot be inspected'):
            artifacts.load_cia_checkpoint_model_only(self.root)

    def test_corrupted_expert_byte_refuses(self):
        self.publish()
        victim = self.expert_objects()[3]
        data = bytearray(victim.read_bytes())
        data[len(data) // 2] ^= 0x01
        victim.write_bytes(bytes(data))
        with self.assertRaisesRegex(ValueError, 'digest or size mismatch'):
            artifacts.load_cia_checkpoint_model_only(self.root)

    def test_placement_inventory_that_differs_from_the_tensors_refuses(self):
        self.publish()
        path = self.root / 'checkpoint-manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['placement']['rogue.weight'] = {'device': 'cpu', 'requires_grad': True}
        path.write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'placement inventory mismatch'):
            artifacts.load_cia_checkpoint_model_only(self.root)

    def test_byte_bound_below_payload_refuses_and_exact_bound_passes(self):
        self.publish()
        _, load = artifacts.load_cia_checkpoint_model_only(self.root)
        with self.assertRaisesRegex(ValueError, 'exceeds the caller byte bound'):
            artifacts.load_cia_checkpoint_model_only(self.root, max_model_bytes=load['model_object_bytes'] - 1)
        artifacts.load_cia_checkpoint_model_only(self.root, max_model_bytes=load['model_object_bytes'])
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            artifacts.load_cia_checkpoint_model_only(self.root, max_model_bytes=0)


# the parent's tests are not this file's business: keep only the model-only ones collectable here
for _name in [n for n in dir(fixture.TransactionTests) if n.startswith('test_')]:
    if _name not in ModelOnlyLoadTests.__dict__:
        setattr(ModelOnlyLoadTests, _name, None)


if __name__ == '__main__':
    unittest.main()
