# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Core-component custody tests; not a complete model checkpoint or admission."""
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
import checkpoint_artifacts as artifacts
from src.ember.model.cia_contract import cia_architecture_config
from src.ember.model.cia_inventory import equation_inventory


class CIACoreTests(unittest.TestCase):
    def test_core_roundtrip_and_identity_refusals(self):
        torch.set_num_threads(1)
        config = cia_architecture_config()
        # A fixed non-learning component payload, not a smaller model subject.
        tensors = {s.name: torch.full(s.shape, 0.125, dtype=torch.bfloat16)
                   for s in equation_inventory() if s.expert is None}
        self.assertEqual(sum(t.numel() for t in tensors.values()), 251_383_808)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / '.checkpoint-quarantine' / 'candidate-core'
            candidate.mkdir(parents=True)
            (candidate / '.writer-lease.json').write_text(json.dumps({'pid': os.getpid()}))
            kwargs = dict(tensors=tensors, architecture_config=config, max_serialized_bytes=251383808*2+4194304)
            missing = dict(tensors)
            del missing['router.global_query.weight']
            with self.assertRaisesRegex(ValueError, 'inventory'):
                artifacts.write_cia_core_object(candidate, **{**kwargs, 'tensors': missing})
            with self.assertRaises((ValueError, RuntimeError)):
                artifacts.write_cia_core_object(candidate, **{**kwargs, 'max_serialized_bytes': 1})
            record = artifacts.write_cia_core_object(candidate, **kwargs)
            def read(selected=record, selected_config=config):
                return artifacts.read_cia_core_object(candidate, record=selected, architecture_config=selected_config)
            restored = read()
            self.assertEqual(set(restored), set(tensors))
            for name in tensors:
                torch.testing.assert_close(restored[name], tensors[name], rtol=0, atol=0)
            del restored
            with self.assertRaises(FileExistsError):
                artifacts.write_cia_core_object(candidate, **kwargs)
            with self.assertRaisesRegex(ValueError, 'architecture'):
                read({**record, 'architecture_sha256': '0'*64})
            path = candidate / 'objects' / (record['sha256'] + '.pt')
            torch.save({'substituted': torch.zeros(1)}, path)
            with self.assertRaisesRegex(ValueError, 'digest or size'):
                read()
            payload = {'schema_version': 'ember-cia-core-object-v1',
                       'architecture_sha256': record['architecture_sha256'], 'model': tensors}
            # Even newly pinned bytes cannot substitute the wrong payload identity.
            payload['architecture_sha256'] = '0'*64
            temporary = candidate / 'wrong.pt'
            torch.save(payload, temporary)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            wrong_record = {**record, 'sha256': digest, 'bytes': temporary.stat().st_size}
            temporary.rename(candidate / 'objects' / (digest + '.pt'))
            with self.assertRaisesRegex(ValueError, 'payload identity'):
                read(wrong_record)


if __name__ == '__main__':
    unittest.main()
