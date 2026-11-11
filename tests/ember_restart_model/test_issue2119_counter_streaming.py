# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The counter reads a checkpoint component in bounded, chunk-verified pieces (#2119 post-train memory).

The H50 hour died in its restore verify because the counter read the whole 5.3 GiB optimizer-state.pt into one bytes object. The
reader is now `_CIAVerifiedFile` over a file-backed ZipFile, and the fp32 facts run on windows. This file proves, platform independent
and standard library only (no torch), that: every guarantee of the whole-file reader is kept (symlink refusal, the byte bound and its
+1 read, digest mismatch, ZIP_STORED only, duplicate names, declared size beyond the bound); the single-snapshot property holds (a file
changed after the digest pass is refused at the first chunk that differs); the streamed facts are byte-identical to the verbatim
whole-file counters kept in counter-history/; and the working set is a fraction of the component and of one tensor. The real Windows
Job Object red is test_issue2119_post_train_memory_job.py (not in the wiring manifest: it cannot run on the ubuntu job).
"""
import hashlib
import importlib.util
import os
import random
import shutil
import struct
import sys
import tempfile
import tracemalloc
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path[:0] = [str(TOOL), str(ROOT / 'src'), str(Path(__file__).resolve().parent)]

import cia_component_fixture as fixture  # noqa: E402
import parameter_counter as counter  # noqa: E402

PREVIOUS = 'b8704a16d577a9ce90edbbb2835ff85e04fcec62c95d45085ab4c396d895f1ba'   # the verbatim whole-file counter this change replaced
HISTORY = TOOL / 'counter-history'
KIB = 1024


def load_verbatim(digest):
    """A kept counter exactly as its receipts were written: no bounded reader bound in (`_counter_for` binds it)."""
    path = HISTORY / ('parameter_counter-%s.py' % digest)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    spec = importlib.util.spec_from_file_location('verbatim_counter_%s' % digest[:16], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_of(path):
    data = Path(path).read_bytes()
    return {'path': Path(path).name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def peak_traced(function):
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        function()
        return tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()


def finite_words(seed, count):
    rng, out = random.Random(seed), bytearray()
    for _ in range(count):
        word = rng.getrandbits(32)
        if (word >> 23) & 0xFF == 0xFF: word &= ~(1 << 23)
        out += struct.pack('<I', word)
    return bytes(out)


class Small(unittest.TestCase):
    """A ~0.4 MiB v3 component read in 8 KiB chunks and 4 KiB windows, so every boundary is exercised."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        owners = [('experts.%d.up.weight' % i, (128, 64) if i % 3 == 0 else (64, 64), i % 2 == 0) for i in range(6)]
        cls.built = fixture.build_component(cls.base / 'optimizer-state.pt', owners, tile_words=4096)
        cls.inventory = {name: tuple(shape) for name, shape in cls.built['inventory'].items()}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for name, value in (('_CIA_READ_CHUNK', 8 * KIB), ('_CIA_MATH_WINDOW', 4 * KIB)):
            patcher = mock.patch.object(counter, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, True)
        self.path = self.work / 'optimizer-state.pt'
        shutil.copyfile(self.base / 'optimizer-state.pt', self.path)
        self.record = dict(self.built['record'])

    def facts(self, module=counter, root=None, record=None):
        with module._cia_counter_component(root or self.work, 'optimizer-state.pt', record or self.record) as (archive, payload):
            return module._cia_counter_optimizer_facts(archive, payload, self.inventory, self.built['groups'], True)

    def expected(self):
        return tuple(self.built['expected'])

    # -- the facts -----------------------------------------------------------------------------------------------------------
    def test_streamed_facts_match_the_independently_computed_expected(self):
        self.assertEqual(self.facts(), self.expected())

    def test_streamed_facts_equal_the_verbatim_whole_file_counter(self):
        self.assertEqual(self.facts(load_verbatim(PREVIOUS)), self.facts())

    def test_a_kept_counter_is_served_the_bounded_reader_with_identical_facts(self):
        module = counter._counter_for(PREVIOUS)
        verbatim = load_verbatim(PREVIOUS)
        self.assertIsNot(module._cia_counter_component, verbatim._cia_counter_component)
        self.assertIs(module._cia_f32_rne_bf16, counter._cia_f32_rne_bf16)
        self.assertEqual(self.facts(module), self.expected())

    def test_every_kept_counter_reads_every_tensor_identically_through_the_bounded_reader(self):
        digests = sorted(p.name[len('parameter_counter-'):-len('.py')] for p in HISTORY.glob('parameter_counter-*.py'))
        self.assertGreaterEqual(len(digests), 5)
        for digest in digests:
            with self.subTest(counter=digest[:8]):
                def every_tensor(module):
                    seen = {}
                    with module._cia_counter_component(self.work, 'optimizer-state.pt', self.record) as (archive, payload):
                        stack = [('', payload)]
                        while stack:
                            where, value = stack.pop()
                            if type(value).__name__ == '_TensorMetadata':
                                seen[where] = hashlib.sha256(module._tensor_raw_bytes(archive, value)).hexdigest()
                            elif isinstance(value, dict):
                                stack.extend((where + '/' + str(key), item) for key, item in value.items())
                    return seen
                before, after = every_tensor(load_verbatim(digest)), every_tensor(counter._counter_for(digest))
                self.assertEqual(len(before), 24)       # 6 masters + 6 x (step, exp_avg, exp_avg_sq)
                self.assertEqual(before, after)

    # -- every guarantee of the whole-file reader ----------------------------------------------------------------------------
    def refuses(self, text, record=None, path=None, relative='optimizer-state.pt'):
        with self.assertRaisesRegex(ValueError, text):
            with counter._cia_counter_component(path or self.work, relative, record or self.record) as (archive, payload):
                self.fail('the component was accepted')

    def test_a_symlink_or_reparse_point_is_refused(self):
        link = self.work / 'link.pt'
        try:
            link.symlink_to(self.path)
        except (OSError, NotImplementedError):
            self.skipTest('this platform cannot create a symlink without privilege')
        self.refuses('symlink or reparse point', relative='link.pt')

    def test_a_longer_file_is_refused_after_reading_at_most_one_byte_past_the_bound(self):
        size = self.record['bytes']
        with self.path.open('ab') as handle: handle.write(b'x' * (3 * size))
        reads, real = [], Path.open

        class Counting:
            def __init__(self, handle): self.handle = handle
            def read(self, count=-1):
                data = self.handle.read(count)
                reads.append(len(data))
                return data
            def __enter__(self): return self
            def __exit__(self, *error): self.handle.close()
            def __getattr__(self, name): return getattr(self.handle, name)

        def spy(path, mode='r', *args, **kwargs):
            handle = real(path, mode, *args, **kwargs)
            return Counting(handle) if path.name == 'optimizer-state.pt' and 'b' in mode else handle
        with mock.patch.object(Path, 'open', spy):
            self.refuses('digest mismatch')
        self.assertEqual(sum(reads), size + 1)

    def test_a_shorter_file_is_refused(self):
        self.path.write_bytes(self.path.read_bytes()[:-1])
        self.refuses('digest mismatch')

    def test_a_changed_byte_of_the_same_size_is_refused(self):
        data = bytearray(self.path.read_bytes())
        data[len(data) // 2] ^= 1
        self.path.write_bytes(bytes(data))
        self.refuses('digest mismatch')

    def test_the_byte_bound_must_be_a_positive_integer(self):
        for bound in (0, -5, '9', 1.0, None):
            with self.subTest(bound=bound):
                self.refuses('byte bound mismatch', record=dict(self.record, bytes=bound))

    def forged(self, build):
        path = self.work / 'forged.pt'
        build(path)
        return path, record_of(path)

    def test_a_compressed_member_is_refused(self):
        def build(path):
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('archive/data.pkl', b'\x80\x02}.' * 200)
        path, record = self.forged(build)
        self.refuses('ZIP storage exceeds its bound', record=record, relative=path.name)

    def test_a_duplicate_member_name_is_refused(self):
        def build(path):
            with warnings.catch_warnings(), zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as archive:
                warnings.simplefilter('ignore')
                archive.writestr('archive/data.pkl', b'\x80\x02}.')
                archive.writestr('archive/data.pkl', b'\x80\x02}.')
        path, record = self.forged(build)
        self.refuses('ZIP storage exceeds its bound', record=record, relative=path.name)

    def test_declared_member_sizes_beyond_the_bound_are_refused(self):
        def build(path):
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as archive:
                archive.writestr('archive/data.pkl', b'\x80\x02}.')
            data = bytearray(path.read_bytes())
            central = data.rfind(b'PK\x01\x02')
            struct.pack_into('<I', data, central + 24, 10 * len(data))     # uncompressed size of the one member
            path.write_bytes(bytes(data))
        path, record = self.forged(build)
        self.refuses('ZIP storage exceeds its bound', record=record, relative=path.name)

    # -- the single-snapshot property ----------------------------------------------------------------------------------------
    def middle_chunk_offset(self):
        size = self.record['bytes']
        offset = size // 2
        chunk = offset // counter._CIA_READ_CHUNK
        self.assertTrue(0 < chunk < (size - 1) // counter._CIA_READ_CHUNK, 'the mutated chunk must be neither the first nor the last')
        return offset

    def read_all_tensors(self, archive, payload):
        for name, tensor in payload['master_weights'].items():
            counter._cia_counter_sha256(archive, tensor, self.inventory[name], 'FloatStorage')

    def test_a_file_changed_after_the_digest_pass_is_refused_at_the_chunk_that_differs(self):
        offset = self.middle_chunk_offset()
        with counter._cia_counter_component(self.work, 'optimizer-state.pt', self.record) as (archive, payload):
            with self.path.open('r+b') as handle:                # the digest pass is over; now the file changes under the reader
                handle.seek(offset)
                byte = handle.read(1)
                handle.seek(offset)
                handle.write(bytes([byte[0] ^ 0xFF]))
            with self.assertRaisesRegex(ValueError, 'changed after its digest was verified'):
                self.read_all_tensors(archive, payload)
                for name, tensor in payload['state'].items():
                    for key, field in tensor.items():
                        if key != 'step': counter._cia_counter_sha256(archive, field, self.inventory[name], 'FloatStorage')

    def test_a_change_that_is_put_back_before_the_read_is_the_same_snapshot(self):
        offset = self.middle_chunk_offset()
        with counter._cia_counter_component(self.work, 'optimizer-state.pt', self.record) as (archive, payload):
            with self.path.open('r+b') as handle:
                handle.seek(offset)
                byte = handle.read(1)
                handle.seek(offset)
                handle.write(bytes([byte[0] ^ 0xFF]))
                handle.seek(offset)
                handle.write(byte)
            self.read_all_tensors(archive, payload)

    def test_a_file_truncated_after_the_digest_pass_is_refused(self):
        with counter._cia_counter_component(self.work, 'optimizer-state.pt', self.record) as (archive, payload):
            with self.path.open('r+b') as handle: handle.truncate(self.record['bytes'] // 2)
            with self.assertRaisesRegex(ValueError, 'changed after its digest was verified'):
                self.read_all_tensors(archive, payload)

    def test_bytes_appended_after_the_digest_pass_are_never_read(self):
        with counter._cia_counter_component(self.work, 'optimizer-state.pt', self.record) as (archive, payload):
            with self.path.open('ab') as handle: handle.write(b'tail' * 5000)
            self.read_all_tensors(archive, payload)

    def test_no_file_handle_is_held_between_reads(self):
        # A handle held across the caller's with-body would block a rename or delete on Windows; the chunk digest is the guard instead.
        moved = self.work / 'moved.pt'
        with counter._cia_counter_component(self.work, 'optimizer-state.pt', self.record) as (archive, payload):
            os.replace(self.path, moved)
            os.replace(moved, self.path)
            self.read_all_tensors(archive, payload)

    # -- bounded helpers ------------------------------------------------------------------------------------------------------
    def test_the_fp32_helpers_equal_the_verbatim_ones_on_edge_inputs(self):
        verbatim = load_verbatim(PREVIOUS)
        window = counter._CIA_MATH_WINDOW
        for size in (0, 4, 8, window - 4, window, window + 4, 3 * window, 3 * window + 8, 10 * window - 4):
            with self.subTest(size=size):
                raw = finite_words(size, size // 4)
                self.assertEqual(counter._cia_f32_rne_bf16(raw), verbatim._cia_f32_rne_bf16(raw))
                self.assertEqual(counter._cia_f32_facts_from_raw(raw), verbatim._cia_f32_facts_from_raw(raw))
        ties = b''.join(struct.pack('<I', (high << 16) | low) for high in (0x3F80, 0x4049, 0xC2F7, 0x0001) for low in (0, 1, 0x7FFF, 0x8000, 0x8001, 0xFFFF))
        self.assertEqual(counter._cia_f32_rne_bf16(ties), verbatim._cia_f32_rne_bf16(ties))
        exact = b''.join(struct.pack('<I', high << 16) for high in range(0x3F00, 0x3F00 + 3000))
        self.assertTrue(counter._cia_f32_facts_from_raw(exact)[2])
        self.assertEqual(counter._cia_f32_facts_from_raw(exact), verbatim._cia_f32_facts_from_raw(exact))
        self.assertFalse(counter._cia_f32_facts_from_raw(exact + struct.pack('<I', 0x3F800001))[2])

    def test_a_non_finite_value_or_a_ragged_length_is_refused_as_before(self):
        verbatim = load_verbatim(PREVIOUS)
        good = finite_words(1, 3 * counter._CIA_MATH_WINDOW // 4)
        for bad in (struct.pack('<I', 0x7F800000), struct.pack('<I', 0xFF800000), struct.pack('<I', 0x7FC00000)):
            for where in (0, len(good) // 2, len(good) - 4):
                data = good[:where] + bad + good[where + 4:]
                with self.subTest(value=bad.hex(), where=where):
                    with self.assertRaisesRegex(ValueError, 'must be finite'): counter._cia_f32_rne_bf16(data)
                    with self.assertRaisesRegex(ValueError, 'must be finite'): verbatim._cia_f32_rne_bf16(data)
        for function in ('_cia_f32_rne_bf16', '_cia_f32_facts_from_raw'):
            for size in (1, 2, 3, 5, 4097):
                with self.subTest(function=function, size=size):
                    with self.assertRaisesRegex(ValueError, 'byte length mismatch'): getattr(counter, function)(b'\0' * size)

    def test_streamed_facts_do_not_depend_on_how_the_bytes_are_split(self):
        raw = finite_words(7, 5000)
        whole = counter._cia_f32_facts_from_raw(raw)
        for cut in (1, 3, 5, 4093, 4096, 4099):
            facts = counter._CiaF32Facts(bf16=True)
            for start in range(0, len(raw), cut): facts.update(raw[start:start + cut])
            done = facts.finish()
            self.assertEqual(done[:3], whole)
            self.assertEqual(done[3], hashlib.sha256(counter._cia_f32_rne_bf16(raw)).hexdigest())
        ragged = counter._CiaF32Facts()
        ragged.update(raw + b'\0')
        with self.assertRaisesRegex(ValueError, 'byte length mismatch'): ragged.finish()


class Bounded(unittest.TestCase):
    """Working sets, measured with tracemalloc (every bytes and bytearray the reader allocates is a traced allocation)."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        owners = [('experts.%d.up.weight' % i, (256, 256), i % 2 == 0) for i in range(4)]       # 256 KiB per tensor, 12 tensors, ~3 MiB
        cls.built = fixture.build_component(cls.base / 'optimizer-state.pt', owners, tile_words=65536)
        cls.inventory = {name: tuple(shape) for name, shape in cls.built['inventory'].items()}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for name in ('_CIA_READ_CHUNK', '_CIA_MATH_WINDOW'):
            patcher = mock.patch.object(counter, name, 64 * KIB)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_facts(self, module):
        def run():
            with module._cia_counter_component(self.base, 'optimizer-state.pt', self.built['record']) as (archive, payload):
                module._cia_counter_optimizer_facts(archive, payload, self.inventory, self.built['groups'], True)
        return run

    def test_the_component_is_never_held_whole(self):
        size = self.built['record']['bytes']
        streamed = peak_traced(self.run_facts(counter))
        whole_file = peak_traced(self.run_facts(load_verbatim(PREVIOUS)))
        self.assertGreater(whole_file, size, 'the measure must see the old whole-file read')
        self.assertLess(streamed, size // 3, 'streamed peak %d bytes against a %d byte component' % (streamed, size))

    def test_the_fp32_helpers_hold_a_few_windows_not_a_few_copies_of_the_tensor(self):
        raw = finite_words(3, 1024 * KIB)                         # 4 MiB, one tensor's worth
        verbatim = load_verbatim(PREVIOUS)
        old_rne = peak_traced(lambda: verbatim._cia_f32_rne_bf16(raw))
        new_rne = peak_traced(lambda: counter._cia_f32_rne_bf16(raw))
        old_facts = peak_traced(lambda: verbatim._cia_f32_facts_from_raw(raw))
        new_facts = peak_traced(lambda: counter._cia_f32_facts_from_raw(raw))
        self.assertGreater(old_rne, 4 * len(raw))                 # measured 5.3x: the big-integer lanes and slices of the whole tensor
        self.assertLess(new_rne, 1.2 * len(raw))                  # the bf16 result is half the tensor and bytes() copies it once
        self.assertGreater(old_facts, 0.9 * len(raw))
        self.assertLess(new_facts, 0.1 * len(raw))                # measured 0.03x: a few windows


if __name__ == '__main__':
    unittest.main()
