"""CPU checks that a chained hour resumes the image-text order at its parent's global step; no training claim."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

SOURCE = Path(os.environ.get('CIA_HOUR_SOURCE', str(Path(__file__).resolve().parents[2] /
    'src/ember/infrastructure/tools/ember-restart-3b/cia_hour.py')))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(SOURCE.with_name('cia_step_runner.py'), 'tested_image_resume_runner')
subject = load(SOURCE, 'tested_image_resume_hour')


class Stream:
    def next_episode(self, *, shard_index, token_offset, sequence_length):
        return (dict(token_ids=[0] * sequence_length, target_ids=[1] * sequence_length),
                dict(shard_index=shard_index, token_offset=token_offset + sequence_length))


class ImageText:
    """Records which global image position each pack asked for."""
    def __init__(self):
        self.asked = []

    def document(self, index):
        self.asked.append(index)
        return index


class ImageResumeTests(unittest.TestCase):
    def setUp(self):
        # append_document only has to keep the pack complete; the index it was given is what is under test.
        def append_document(pack, document):
            pack['document_starts'].append(len(pack['token_ids']))
            pack['token_ids'].extend([document] * 2)
            pack['target_ids'].extend([document] * 2)
            pack['positions'].extend([[0, 0, 0], [1, 0, 0]])
        self._saved = runner.load_image_text_module
        runner.load_image_text_module = lambda: types.SimpleNamespace(append_document=append_document)

    def tearDown(self):
        runner.load_image_text_module = self._saved

    def hour(self, image_text, steps, **start):
        packs = subject.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=steps, sequence=2,
                                  documents=2, image_text=image_text, fill=runner.fill_pack, **start)
        return [packs.next_pack() for _ in range(steps)]

    def test_genesis_hour_asks_the_local_indices_unchanged(self):
        image_text = ImageText()
        self.hour(image_text, 3)
        self.assertEqual(image_text.asked, [0, 1, 2])

    def test_chained_hour_continues_where_its_parent_stopped(self):
        parent, child = ImageText(), ImageText()
        self.hour(parent, 3)
        # The parent published global step 3 (warm + measured), so the child starts at image position 3.
        packs = self.hour(child, 2, image_start=3)
        self.assertEqual(child.asked, [3, 4])
        self.assertFalse(set(parent.asked) & set(child.asked), 'a chained hour replayed parent image documents')
        self.assertEqual([pack['index'] for pack in packs], [0, 1], 'local pack index stays hour-local')

    def test_start_must_be_a_non_negative_integer(self):
        for bad in (-1, True, 1.0, '3'):
            with self.assertRaises(ValueError):
                subject.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=1, image_start=bad)

    def test_text_only_hour_is_untouched(self):
        packs = subject.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=1, sequence=2,
                                  documents=2, fill=runner.fill_pack, image_start=7)
        self.assertEqual(len(packs.next_pack()['token_ids']), 4)

    def test_chained_start_reads_the_digest_bound_parent_step(self):
        self.assertEqual(subject.chained_image_start(runner, {}), 0)
        with tempfile.TemporaryDirectory() as root:
            raw = json.dumps(dict(data_cursor=dict(global_step=79103))).encode()
            (Path(root) / 'checkpoint-manifest.json').write_bytes(raw)
            chain = dict(root=root, manifest_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(subject.chained_image_start(runner, dict(parent_checkpoint=chain)), 79103)
            with self.assertRaises(ValueError):
                subject.chained_image_start(runner, dict(parent_checkpoint=dict(chain, manifest_sha256='0' * 64)))

    def test_worker_refuses_a_start_that_differs_from_the_restored_step(self):
        subject.check_image_start(dict(image_text=dict(start_pack=5)), 5)
        subject.check_image_start({}, 5)
        for binding, restored in ((dict(start_pack=0), 5), (dict(start_pack=5), 0), ({}, 0)):
            with self.assertRaises(ValueError):
                subject.check_image_start(dict(image_text=binding), restored)


if __name__ == '__main__':
    unittest.main()
