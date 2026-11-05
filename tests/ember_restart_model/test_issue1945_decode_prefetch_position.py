# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The image prefetch is keyed at the GLOBAL image-text position, and the hour asserts that it hit (#1945 H34).

CPU, fakes only, no model, no device: these pin software behaviour and make no throughput claim.

What is under test. HourPacks fills a chained hour's image document at image_start + index; the step's two-ahead
and one-ahead prefetches used to be keyed at the LOCAL index, so on every chained hour (image_start != 0) the
prefetch key never matched the pack, load_patches missed, the step thread decoded eight images synchronously, and
eight wrong images were decoded on the pool every update. H34 read image_patches_source 'decoded-in-this-step' on
68,269 of 68,269 rows with EMBER_DECODE_TWO_AHEAD=1 and nothing refused, because the flag was recorded and the
outcome field was never read. The cases below run the REAL HourPacks fill, the REAL image-text prefetch and
load_patches (with only the image decode replaced by a zero grid), and the REAL witness the hour now reads rows
through -- and the deliberate red reverts the cure by monkeypatch and shows the chained case failing while the
genesis case still passes, which is why a genesis test could never have caught this.
"""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy
import torch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(TOOLS / 'cia_step_runner.py', 'decode_prefetch_tested_runner')
hour = load(TOOLS / 'cia_hour.py', 'decode_prefetch_tested_hour')
# The SAME module object the runner's prefetch and load_patches resolve (load_image_text_module registers it once).
images = runner.load_image_text_module()

SEQUENCE, DOCUMENTS, PAIRS, COUNT = 32, 2, 8, 2
CHAINED_START = 1412220  # H34's bound start_pack (prediction.json image_text.start_pack)
CPU = torch.device('cpu')


class Stream:
    def next_episode(self, *, shard_index, token_offset, sequence_length):
        return (dict(token_ids=list(range(sequence_length)), target_ids=list(range(1, sequence_length + 1))),
                dict(shard_index=shard_index, token_offset=token_offset + sequence_length))


class ImageText:
    """pair_rows and document agree by construction: each object_sha256 encodes the GLOBAL position and the pair,
    exactly as the frozen manifest order makes ImageTextStream.pair_rows and .document agree."""
    def pair_rows(self, index):
        return [dict(path='object-%d-%d.png' % (index, k), object_sha256='%056x%08x' % (index, k)) for k in range(PAIRS)]

    def document(self, index):
        rows = self.pair_rows(index)
        tokens, targets = [7] * SEQUENCE, [1] * SEQUENCE  # every target loss-bearing: staged_inputs needs one per document
        positions = [[i, 0, 0] for i in range(SEQUENCE)]
        spans = [dict(row=1 + k * (COUNT + 1), count=COUNT, grid=[COUNT, 1], path=row['path'],
                      object_sha256=row['object_sha256'], manifest_row=k) for k, row in enumerate(rows)]
        return dict(token_ids=tokens, target_ids=targets, positions=positions, images=spans, wrapped=False)


def zero_grid(path, object_sha256):
    """Stands in for the PIL decode only; the prefetch keying, pool submit, pop and join are the real code."""
    return numpy.zeros((COUNT, 768), dtype=numpy.uint8)


def hour_packs(image_start, count):
    stream = ImageText()
    packs = hour.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=count, sequence=SEQUENCE,
                           documents=DOCUMENTS, image_text=stream, fill=runner.fill_pack, image_start=image_start)
    return stream, [packs.next_pack() for _ in range(count)]


def fill_key(pack):
    return tuple(span['object_sha256'] for span in pack['images'])


def prefetch_key(stream, position):
    return tuple(row['object_sha256'] for row in stream.pair_rows(position))


class PrefetchPositionTests(unittest.TestCase):
    """(a) the prefetch key equals the fill key on a chained start and on genesis."""

    def setUp(self):
        images._AHEAD.clear()
        self.addCleanup(images._AHEAD.clear)

    def test_prefetch_key_equals_fill_key_two_ahead_and_one_ahead_on_chained_and_genesis_starts(self):
        for image_start in (0, CHAINED_START):
            stream, packs = hour_packs(image_start, 6)
            self.assertEqual([pack['index'] for pack in packs], list(range(6)))
            for i in range(4):
                self.assertEqual(prefetch_key(stream, runner.prefetch_position(packs[i], image_start, 2)),
                                 fill_key(packs[i + 2]), (image_start, i, 'two-ahead'))
                self.assertEqual(prefetch_key(stream, runner.prefetch_position(packs[i], image_start, 1)),
                                 fill_key(packs[i + 1]), (image_start, i, 'one-ahead'))
            # The local arithmetic is only ever equal at genesis.
            local = prefetch_key(stream, packs[0]['index'] + 2)
            self.assertEqual(local == fill_key(packs[2]), image_start == 0)

    def assert_two_ahead_hits(self, image_start):
        """Stage update 1 inside update 0 (the real _stage_next_early), then load update 2's patches: a HIT."""
        stream, packs = hour_packs(image_start, 3)
        with patch.object(images, '_decode_uint8', zero_grid):
            staged = runner._stage_next_early(packs[1], CPU, stream, packs[0], True, image_start=image_start)
            self.assertEqual(staged[2], hour.DECODE_PREFETCH_MISS)  # nothing had prefetched update 1 yet (index 1 and 2 never hit)
            self.assertEqual(len(images._AHEAD), 1)
            rows, patches = images.load_patches(packs[2], CPU)
            images.join_prefetch()
        self.assertEqual(images.LAST_SOURCE, hour.DECODE_PREFETCH_HIT, image_start)
        self.assertEqual(images._AHEAD, {})
        self.assertEqual(tuple(patches.shape), (PAIRS * COUNT, 768))
        self.assertEqual(rows.tolist(), [r for span in packs[2]['images'] for r in range(span['row'], span['row'] + COUNT)])

    def test_two_ahead_prefetch_hits_through_the_real_stream_module_on_a_chained_start_and_at_genesis(self):
        for image_start in (0, CHAINED_START):
            images._AHEAD.clear()
            self.assert_two_ahead_hits(image_start)

    def test_one_ahead_prefetch_position_hits_on_a_chained_start(self):
        stream, packs = hour_packs(CHAINED_START, 3)
        with patch.object(images, '_decode_uint8', zero_grid):
            images.prefetch_index(stream, runner.prefetch_position(packs[1], CHAINED_START, 1))
            images.load_patches(packs[2], CPU)
            images.join_prefetch()
        self.assertEqual(images.LAST_SOURCE, hour.DECODE_PREFETCH_HIT)

    def test_deliberate_red_the_local_index_misses_every_chained_pack_and_still_passes_at_genesis(self):
        """(c) with the cure reverted by monkeypatch, (a)'s chained case fails; genesis passes regardless."""
        local = lambda pack, image_start, ahead: pack.get('index', 0) + ahead  # the defective arithmetic
        with patch.object(runner, 'prefetch_position', local):
            with self.assertRaises(AssertionError):
                self.assert_two_ahead_hits(CHAINED_START)
            images._AHEAD.clear()
            self.assert_two_ahead_hits(0)
        images._AHEAD.clear()
        self.assert_two_ahead_hits(CHAINED_START)  # the cure, restored

    def test_the_hour_reads_image_start_through_the_look_ahead_and_the_pushback(self):
        stream, _ = hour_packs(CHAINED_START, 1)
        packs = hour.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=3, sequence=SEQUENCE,
                               documents=DOCUMENTS, image_text=stream, fill=runner.fill_pack, image_start=CHAINED_START)
        ahead = runner.LookaheadPacks(packs)
        self.assertEqual(ahead.image_start, CHAINED_START)
        self.assertEqual(hour._HourPushback(ahead, ahead.next_pack()).image_start, CHAINED_START)
        self.assertEqual(hour.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=1,
                                        fill=runner.fill_pack).image_start, 0)

    def test_image_start_is_validated_at_the_step_and_at_the_position(self):
        for bad in (-1, 1.0, '3', None):
            with self.assertRaisesRegex(ValueError, 'non-negative integer'):
                runner.prefetch_position(dict(index=0), bad, 2)
            with self.assertRaisesRegex(ValueError, 'non-negative integer'):
                runner.measure_step(None, None, {}, device=CPU, image_start=bad)
        self.assertEqual(runner.prefetch_position(dict(index=5), 0, 2), 7)
        self.assertEqual(runner.prefetch_position({}, CHAINED_START, 1), CHAINED_START + 1)


def synthetic_rows(count, *, misses=(), without_field=()):
    """index 0 warm, then measured rows; updates 1 and 2 decode in-step by construction (nothing prefetched them)."""
    for index in range(count + 1):
        row = dict(index=index, phase='warm' if index == 0 else 'measured')
        if index not in without_field:
            row['image_patches_source'] = (hour.DECODE_PREFETCH_MISS if index in (1, 2) or index in misses
                                           else hour.DECODE_PREFETCH_HIT)
        yield row


def observe_all(witness, rows):
    measured = 0
    for row in rows:
        witness.observe(row, measured + 1)
        if row['phase'] == 'measured':
            measured += 1
    return witness


class DecodePrefetchWitnessTests(unittest.TestCase):
    """(b) the refusal fires on an in-step row inside the first 64 measured rows and never after."""

    def test_constants_are_the_contract(self):
        self.assertEqual(hour.DECODE_PREFETCH_CLAUSE, 'decode-prefetch-actually-hit')
        self.assertEqual(hour.DECODE_PREFETCH_ASSERTED_ROWS, 64)
        self.assertEqual(hour.DECODE_PREFETCH_FIRST_INDEX, 3)
        self.assertEqual((hour.DECODE_PREFETCH_HIT, hour.DECODE_PREFETCH_MISS),
                         ('decoded-in-previous-step-wall', 'decoded-in-this-step'))

    def test_refuses_on_an_in_step_row_inside_the_first_64_and_names_the_clause(self):
        for miss in (3, 10, 64):
            witness = hour.DecodePrefetchWitness(two_ahead=True)
            with self.assertRaisesRegex(ValueError, '^decode-prefetch-actually-hit: ') as refused:
                observe_all(witness, synthetic_rows(200, misses=(miss,)))
            self.assertIn('measured row %d (update index %d)' % (miss, miss), str(refused.exception))
            self.assertEqual(witness.counts[hour.DECODE_PREFETCH_MISS], 3)  # updates 1, 2 and the refusing row

    def test_updates_1_and_2_may_decode_in_step_and_a_clean_hour_counts_every_row(self):
        witness = observe_all(hour.DecodePrefetchWitness(two_ahead=True), synthetic_rows(200))
        receipt = witness.receipt()
        self.assertEqual(receipt['image_patches_source_counts'],
                         {hour.DECODE_PREFETCH_HIT: 198, hour.DECODE_PREFETCH_MISS: 2})
        self.assertEqual((receipt['rows_asserted'], receipt['measured_rows'], receipt['residual_rows_without_field']),
                         (62, 200, 0))
        self.assertEqual((receipt['clause'], receipt['two_ahead_requested']), ('decode-prefetch-actually-hit', True))

    def test_after_row_64_an_in_step_row_is_counted_and_reported_never_a_refusal(self):
        witness = observe_all(hour.DecodePrefetchWitness(two_ahead=True), synthetic_rows(300, misses=(65, 150, 300)))
        receipt = witness.receipt()
        self.assertEqual(receipt['image_patches_source_counts'][hour.DECODE_PREFETCH_MISS], 5)
        self.assertEqual(receipt['rows_asserted'], 62)

    def test_without_the_flag_nothing_refuses_and_everything_is_counted(self):
        witness = observe_all(hour.DecodePrefetchWitness(two_ahead=False), synthetic_rows(100, misses=(10,)))
        receipt = witness.receipt()
        self.assertEqual(receipt['image_patches_source_counts'][hour.DECODE_PREFETCH_MISS], 3)
        self.assertEqual((receipt['rows_asserted'], receipt['two_ahead_requested']), (0, False))

    def test_a_row_without_the_field_is_the_residual_and_the_warm_row_is_not_a_measured_row(self):
        witness = observe_all(hour.DecodePrefetchWitness(two_ahead=True), synthetic_rows(70, without_field=(0, 5, 66)))
        receipt = witness.receipt()
        self.assertEqual(receipt['residual_rows_without_field'], 2)
        self.assertEqual(receipt['measured_rows'], 70)
        self.assertEqual(sum(receipt['image_patches_source_counts'].values()) + receipt['residual_rows_without_field'], 70)


class HourAndStepWiringTests(unittest.TestCase):
    """The hour loop cannot run on the CPU; its wiring is pinned at the source, the way the gc-freeze tests pin theirs."""

    def test_the_hour_passes_the_global_image_start_and_asserts_before_it_counts(self):
        source = (TOOLS / 'cia_hour.py').read_text(encoding='utf-8')
        loop = source[source.index('with runner.GcPauseMeter().bind(**gc_identity) as gc_meter'):source.index('elapsed_before_checkpoint')]
        self.assertIn("image_start = prepared['packs'].image_start", loop)
        self.assertIn("decode_witness = DecodePrefetchWitness(two_ahead=os.environ.get('EMBER_DECODE_TWO_AHEAD') == '1')", loop)
        call = loop[loop.index('row = runner.measure_step('):loop.index('call_finished = time.perf_counter()')]
        self.assertIn('image_start=image_start)', call)
        self.assertLess(loop.index('call_finished = time.perf_counter()'), loop.index('decode_witness.observe(row, measured + 1)'))
        self.assertLess(loop.index("applied(row['applied_positions'])"), loop.index('decode_witness.observe(row, measured + 1)'))
        self.assertLess(loop.index('decode_witness.observe(row, measured + 1)'), loop.index('total_steps += 1'))
        self.assertLess(loop.index('decode_witness.observe(row, measured + 1)'), loop.index('measured += 1'))
        self.assertIn("runner._write_new(custody / 'decode-prefetch.json', dict(decode_witness.receipt(), refused=True))", loop)
        self.assertIn("runner._write_new(custody / 'decode-prefetch.json', dict(decode_witness.receipt(), refused=False))", loop)

    def test_the_step_threads_image_start_to_every_prefetch_and_evidences_the_prelaunch(self):
        source = (TOOLS / 'cia_step_runner.py').read_text(encoding='utf-8')
        start = source.index('\ndef measure_step(')
        body = source[start:source.index('\ndef ', start + 1)]
        self.assertEqual(body.count('_stage_next_early('), 2)
        self.assertEqual(body.count('image_start=image_start'), 2)
        self.assertIn('prefetch_position(pack, image_start, 1)', body)
        self.assertIn("'prelaunched': pre is not None", body)
        staging = source[source.index('\ndef _stage_next_early('):source.index('\ndef ', source.index('\ndef _stage_next_early(') + 1)]
        self.assertIn('prefetch_position(pack, image_start, 2)', staging)
        for local in ("pack.get('index', 0) + 1)", "pack.get('index', 0) + 2)", "pack['index'] + 1)", "pack['index'] + 2)"):
            self.assertNotIn(local, source, 'a local-index prefetch survives: ' + local)


if __name__ == '__main__':
    unittest.main()
