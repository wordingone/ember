# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The checkpoint component loader no longer holds a second whole copy of the file (#2119; the H50 restore verify died of that copy).

`_cia_read_component` (and the expert and core object readers, which share `_cia_load_verified`) used to read the whole file into one
bytes object, hash it, and torch.load it from a BytesIO: peak = file + tensors. They now hash the file in one streaming pass, keep a
digest per chunk, and let torch read through `_CIAVerifiedFile`, which re-verifies each chunk it serves. These tests pin the three
things that must not change (same payload, every refusal, the single-snapshot property: a file that changes between the digest pass and
the load is refused) and the one thing that must (no read of the whole file in one piece). CPU only, platform independent."""
import hashlib
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', message='`torch.jit.script_method` is deprecated', category=DeprecationWarning)
    import checkpoint_artifacts as artifacts  # noqa: E402
    import parameter_counter as counter  # noqa: E402

MIB = 1024 * 1024
MESSAGE = 'CIA checkpoint component digest mismatch'


def make_payload():
    generator = torch.Generator().manual_seed(11)
    return {'state': {'w%d' % index: torch.randn(MIB // 4 * (index + 1), generator=generator) for index in range(4)},
            'step': 5, 'name': 'component', 'small': torch.arange(7, dtype=torch.int64)}


def same(left, right):
    if isinstance(left, dict):
        return isinstance(right, dict) and left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if isinstance(left, torch.Tensor):
        return isinstance(right, torch.Tensor) and left.dtype == right.dtype and torch.equal(left, right)
    return left == right


class VerifiedLoad(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = make_payload()
        self.path = self.root / 'optimizer-state.pt'
        torch.save(self.payload, self.path)
        data = self.path.read_bytes()
        self.record = {'path': self.path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        # small chunks so a 10 MiB file spans many of them
        shrink = patch.object(counter, '_CIA_READ_CHUNK', MIB)
        shrink.start()
        self.addCleanup(shrink.stop)

    def read(self, record=None):
        return artifacts._cia_read_component(self.root, dict(self.record if record is None else record))

    def test_returns_exactly_what_the_whole_file_load_returned(self):
        self.assertGreater(self.record['bytes'], 9 * MIB)
        import io
        old = torch.load(io.BytesIO(self.path.read_bytes()), map_location='cpu', weights_only=True)
        self.assertTrue(same(self.read(), old))
        self.assertTrue(same(self.read(), self.payload))

    def test_refuses_each_way_the_bytes_can_differ_from_the_record(self):
        data = bytearray(self.path.read_bytes())
        changed = bytearray(data)
        changed[len(changed) // 2] ^= 1
        self.path.write_bytes(bytes(changed))
        with self.assertRaisesRegex(ValueError, MESSAGE):
            self.read()
        self.path.write_bytes(bytes(data) + b'x')
        with self.assertRaisesRegex(ValueError, MESSAGE):
            self.read()
        self.path.write_bytes(bytes(data[:-1]))
        with self.assertRaisesRegex(ValueError, MESSAGE):
            self.read()
        self.path.write_bytes(bytes(data))
        self.assertTrue(same(self.read(), self.payload))

    def test_the_record_schema_and_byte_bound_checks_are_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'schema mismatch'):
            self.read({'path': self.path.name, 'sha256': self.record['sha256']})
        with self.assertRaisesRegex(ValueError, 'byte bound mismatch'):
            self.read({**self.record, 'bytes': 0})
        with self.assertRaisesRegex(ValueError, MESSAGE):
            self.read({**self.record, 'bytes': self.record['bytes'] - 1})
        with self.assertRaisesRegex(ValueError, MESSAGE):
            self.read({**self.record, 'bytes': self.record['bytes'] + 1})

    def test_a_symlink_component_is_still_refused(self):
        link = self.root / 'replay-state.pt'  # a name the component reader accepts, so the refusal is the link check
        try:
            link.symlink_to(self.path)
        except (OSError, NotImplementedError):
            self.skipTest('this account cannot create a symlink')
        with self.assertRaisesRegex(ValueError, 'symlink or reparse point'):
            self.read({**self.record, 'path': link.name})

    def test_a_file_changed_after_its_digest_pass_is_refused_not_loaded(self):
        # The digest pass hashes the file; the load then re-reads it chunk by chunk. A byte changed in between must be refused, even
        # though the whole file no longer matches only in the middle (the attack a check-then-reopen loader loses).
        real = counter._cia_counter_digest_pass
        mutated = []

        def pass_then_mutate(path, size):
            result = real(path, size)
            data = bytearray(Path(path).read_bytes())
            data[len(data) // 3] ^= 0xFF
            Path(path).write_bytes(bytes(data))
            mutated.append(True)
            return result

        with patch.object(counter, '_cia_counter_digest_pass', pass_then_mutate):
            with self.assertRaisesRegex(ValueError, 'changed after its digest was verified'):
                self.read()
        self.assertEqual(mutated, [True])

    def test_the_file_is_never_read_in_one_piece(self):
        reads, original = [], Path.open

        def watched(path, *args, **kwargs):
            handle = original(path, *args, **kwargs)
            if Path(path) != self.path:
                return handle
            real_read = handle.read

            def read(size=-1):
                data = real_read(size)
                reads.append(len(data))
                return data
            handle.read = read
            return handle

        with patch.object(Path, 'open', watched):
            self.assertTrue(same(self.read(), self.payload))
        size = self.record['bytes']
        self.assertTrue(reads)
        self.assertLessEqual(max(reads), MIB, 'a single read of %d bytes: the whole-file snapshot is back' % max(reads))
        # one digest pass plus one verified serve: about two file's worth, never the old read(size + 1) in one go
        self.assertLessEqual(sum(reads), 2 * size + 4 * MIB)
        self.assertGreaterEqual(sum(reads), size)


if __name__ == '__main__':
    unittest.main()
