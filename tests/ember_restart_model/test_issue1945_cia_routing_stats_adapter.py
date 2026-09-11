# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue 1945: device routing-statistics buffers and receipt adapter in the CIA step runner.

CPU fixtures only. These tests establish the adapter's software behavior (buffer geometry, collector
copies without host reads, one-copy digest, legacy-row equivalence, runner row fields); they carry no
CIA-3B throughput, learning or routing-quality claim.
"""
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy
import torch


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SUBJECT_PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('issue1945_routing_stats_cia_step_runner', SUBJECT_PATH)
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)

LAYERS = tuple(range(1, 24, 2))


def reference_geometry(lengths):
    """Independent re-statement of the resident decoder's chunk/epoch enumeration."""
    chunks, offset, epoch = [], 0, 0
    for document, length in enumerate(lengths):
        for start in range(0, length, 1024):
            for segment in range(start, min(start + 1024, length), 256):
                chunks.append((document, offset, segment, min(256, length - segment), epoch))
            epoch += 1
        offset += length
    return SimpleNamespace(chunks=tuple(chunks), lengths=tuple(lengths)), epoch, len(chunks)


def fixture_payloads(lengths, seed):
    geometry, epochs, chunk_count = reference_geometry(lengths)
    generator = torch.Generator().manual_seed(seed)
    priors = torch.rand((epochs, 25), generator=generator)
    ranked = torch.argsort(priors, dim=1, descending=True)[:, :2]
    candidates = torch.sort(ranked, dim=1).values
    global_payload = dict(geometry=geometry, priors=priors, ranked=ranked, candidates=candidates)
    locals_ = {}
    for layer in LAYERS:
        pick = torch.randint(0, 2, (chunk_count,), generator=generator)
        epoch_of_chunk = torch.tensor([chunk[4] for chunk in geometry.chunks])
        winners = candidates[epoch_of_chunk].gather(1, pick[:, None])[:, 0]
        locals_[layer] = dict(layer=layer, winners=winners, logits=torch.rand((chunk_count, 2), generator=generator),
                              gates=torch.rand((chunk_count,), generator=generator), valid=torch.tensor(True))
    return geometry, global_payload, locals_


def reference_rows(geometry, global_payload, locals_):
    ranked = global_payload['ranked'].tolist()
    rows = [(document, layer, start, tuple(ranked[epoch]), int(locals_[layer]['winners'][index]))
            for layer in LAYERS
            for index, (document, offset, start, size, epoch) in enumerate(geometry.chunks)]
    return tuple(sorted(rows, key=lambda row: row[:3]))


def feed(buffers, global_payload, locals_):
    buffers.begin_step()
    buffers.collector('global', global_payload)
    for layer in LAYERS:
        buffers.collector('local', locals_[layer])


class DeviceOnly(torch.Tensor):
    """A tensor that refuses every host read; the collector must copy it without one."""
    @staticmethod
    def __new__(cls, data):
        return torch.Tensor._make_subclass(cls, data.detach(), False)

    def _refuse(self, *args, **kwargs):
        raise AssertionError('host read of a device routing statistic')

    cpu = tolist = item = numpy = __float__ = __int__ = __index__ = __bool__ = _refuse


def device_only(payload):
    return {key: (DeviceOnly(value) if isinstance(value, torch.Tensor) else value) for key, value in payload.items()}


class GeometryTests(unittest.TestCase):
    def test_static_geometry_and_layout(self):
        for lengths, epochs, chunks in (((1024,) * 4, 4, 16), ((1000, 2048, 300), 4, 14), ((2, 3), 2, 2), ((4096,), 4, 16)):
            with self.subTest(lengths=lengths):
                buffers = subject.RoutingStatisticsBuffers(lengths, device='cpu')
                geometry, ref_epochs, ref_chunks = reference_geometry(lengths)
                self.assertEqual((buffers.epochs, buffers.chunk_count), (epochs, chunks))
                self.assertEqual((ref_epochs, ref_chunks), (epochs, chunks))
                self.assertEqual(buffers.chunks, geometry.chunks)
                self.assertEqual(buffers.raw.numel(), buffers.nbytes)
                for name, dtype, shape, start, nbytes in buffers.layout:
                    self.assertEqual(start % 8, 0)
                    self.assertEqual(tuple(buffers.views[name].shape), tuple(shape))
                    self.assertEqual(str(buffers.views[name].dtype).replace('torch.', ''), dtype)
                    self.assertEqual(buffers.views[name].data_ptr(), buffers.raw.data_ptr() + start)

    def test_geometry_refusals(self):
        for bad in ((), (0,), (1024, -1), (4097,), [1024], (1024.0,)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                subject.RoutingStatisticsBuffers(bad, device='cpu')

    def test_document_lengths_and_cache(self):
        self.assertEqual(subject.document_lengths((0, 300), 820), (300, 520))
        self.assertEqual(subject.document_lengths((0,), 7), (7,))
        subject._ROUTING_BUFFERS.clear()
        first = subject.routing_buffers((300, 520), 'cpu')
        self.assertIs(first, subject.routing_buffers((300, 520), torch.device('cpu')))
        self.assertIsNot(first, subject.routing_buffers((520, 300), 'cpu'))
        subject._ROUTING_BUFFERS.clear()


class CollectorTests(unittest.TestCase):
    def test_rows_equal_reference_on_three_geometries(self):
        for seed, lengths in enumerate(((1024,) * 4, (1000, 2048, 300), (300, 520))):
            with self.subTest(lengths=lengths):
                geometry, global_payload, locals_ = fixture_payloads(lengths, seed)
                buffers = subject.RoutingStatisticsBuffers(lengths, device='cpu')
                feed(buffers, global_payload, locals_)
                snapshot = buffers.snapshot()
                self.assertEqual(len(snapshot), buffers.nbytes)
                self.assertEqual(buffers.routes(snapshot), reference_rows(geometry, global_payload, locals_))
                statistics = buffers.statistics(snapshot)
                self.assertEqual(statistics['valid'], [True] * 12)
                self.assertEqual([sum(row) for row in statistics['winner_histogram']], [buffers.chunk_count] * 12)
                self.assertEqual(statistics['ranked_pairs'], global_payload['ranked'].tolist())
                for depth, layer in enumerate(LAYERS):
                    self.assertAlmostEqual(statistics['mean_gate'][depth], float(locals_[layer]['gates'].mean()), places=6)

    def test_digest_is_deterministic_and_sensitive(self):
        lengths = (1000, 2048, 300)
        geometry, global_payload, locals_ = fixture_payloads(lengths, 7)
        a, b = (subject.RoutingStatisticsBuffers(lengths, device='cpu') for _ in range(2))
        feed(a, global_payload, locals_)
        feed(b, global_payload, locals_)
        digest = a.digest(a.snapshot())
        self.assertEqual(digest, b.digest(b.snapshot()))
        header = json.loads(a.header)
        self.assertEqual((header['grammar'], header['lengths']), ('device-buffers-v1', list(lengths)))
        self.assertEqual(digest, hashlib.sha256(a.header + b'\0' + a.snapshot()).hexdigest())
        changed = dict(locals_)
        winners = locals_[13]['winners'].clone()
        winners[0] = global_payload['candidates'][geometry.chunks[0][4]][1 - int(winners[0] == global_payload['candidates'][geometry.chunks[0][4]][1])]
        changed[13] = dict(locals_[13], winners=winners)
        feed(b, global_payload, changed)
        self.assertNotEqual(digest, b.digest(b.snapshot()))
        other = subject.RoutingStatisticsBuffers((2048, 1000, 300), device='cpu')
        self.assertNotEqual(other.header, a.header)

    def test_incomplete_or_duplicate_reports_refuse(self):
        lengths = (300, 520)
        geometry, global_payload, locals_ = fixture_payloads(lengths, 3)
        buffers = subject.RoutingStatisticsBuffers(lengths, device='cpu')
        buffers.begin_step()
        with self.assertRaises(RuntimeError):
            buffers.snapshot()
        buffers.collector('global', global_payload)
        with self.assertRaises(ValueError):
            buffers.collector('global', global_payload)
        for layer in LAYERS[:-1]:
            buffers.collector('local', locals_[layer])
        with self.assertRaises(RuntimeError):
            buffers.complete()
        with self.assertRaises(ValueError):
            buffers.collector('local', locals_[LAYERS[0]])
        buffers.collector('local', locals_[LAYERS[-1]])
        buffers.complete()
        buffers.begin_step()
        with self.assertRaises(RuntimeError):
            buffers.complete()

    def test_malformed_reports_refuse(self):
        lengths = (300, 520)
        geometry, global_payload, locals_ = fixture_payloads(lengths, 5)
        buffers = subject.RoutingStatisticsBuffers(lengths, device='cpu')
        buffers.begin_step()
        other, _, _ = reference_geometry((520, 300))
        with self.assertRaises(ValueError):
            buffers.collector('global', dict(global_payload, geometry=other))
        with self.assertRaises(ValueError):
            buffers.collector('global', dict(global_payload, priors=global_payload['priors'][:, :24]))
        with self.assertRaises(ValueError):
            buffers.collector('local', dict(locals_[1], layer=2))
        with self.assertRaises(ValueError):
            buffers.collector('local', dict(locals_[1], winners=locals_[1]['winners'][:-1]))
        with self.assertRaises(ValueError):
            buffers.collector('routes', {})
        with self.assertRaises(ValueError):
            buffers.collector('global', [global_payload])

    def test_collector_performs_no_host_read(self):
        lengths = (1000, 2048, 300)
        geometry, global_payload, locals_ = fixture_payloads(lengths, 11)
        buffers = subject.RoutingStatisticsBuffers(lengths, device='cpu')
        buffers.begin_step()
        buffers.collector('global', device_only(global_payload))
        for layer in LAYERS:
            buffers.collector('local', device_only(locals_[layer]))
        self.assertEqual(buffers.routes(buffers.snapshot()), reference_rows(geometry, global_payload, locals_))
        self.assertEqual(buffers.route_host_reads, 0)

        def host_reading_collector(kind, payload):  # the planted negative: the guard fires on a host read
            if kind == 'local':
                payload['winners'].tolist()
            buffers.collector(kind, payload)

        buffers.begin_step()
        host_reading_collector('global', device_only(global_payload))
        with self.assertRaises(AssertionError):
            host_reading_collector('local', device_only(locals_[1]))


class Cache:
    lease_count = miss_count = eviction_count = transfer_bytes = 0
    transfer_seconds = 0.0


class FakeTrace:
    def __init__(self, rows):
        self.rows = rows

    def materialize(self):
        return self.rows


class ResidentModel:
    """Stands in for the resident decoder's forward contract: device collector in, provisional trace out."""
    def __init__(self, lengths, seed, *, corrupt_trace=False):
        self.lengths, self.seed, self.corrupt_trace = lengths, seed, corrupt_trace
        self._resident_experts = (0, 1, 2, 3)
        self._cuda_execution = SimpleNamespace(cache=Cache())
        self.weight = torch.nn.Parameter(torch.zeros(8))
        self.calls = []

    @contextlib.contextmanager
    def candidate_step(self):
        yield

    def embed_text(self, tokens):
        return torch.zeros((len(tokens), 4))

    def __call__(self, embedded, positions, *, document_starts, return_routes, batch_documents,
                 return_device_routes=False, device_route_collector=None):
        self.calls.append(dict(document_starts=document_starts, return_routes=return_routes,
                               return_device_routes=return_device_routes, collector=device_route_collector))
        if not return_device_routes or device_route_collector is None:
            raise ValueError('resident execution requires explicit device route returns')
        geometry, global_payload, locals_ = fixture_payloads(self.lengths, self.seed)
        device_route_collector('global', device_only(global_payload))
        for layer in LAYERS:
            device_route_collector('local', device_only(locals_[layer]))
        rows = reference_rows(geometry, global_payload, locals_)
        if self.corrupt_trace:
            rows = rows[1:] + rows[:1]
        logits = self.weight.expand(len(embedded), 8) + 0.0
        return (logits, FakeTrace(rows)) if return_routes else logits


class LegacyModel(ResidentModel):
    def __init__(self):
        super().__init__((3, 4), 0)
        self._resident_experts = ()

    def __call__(self, embedded, positions, *, document_starts, return_routes, batch_documents, **unexpected):
        if unexpected:
            raise ValueError('device routing options require explicit resident execution')
        logits = self.weight.expand(len(embedded), 8) + 0.0
        return logits, ((0, 1, 0, (2, 5), 5), (1, 1, 0, (1, 3), 1))


def pack_for(lengths):
    total = sum(lengths)
    starts, offset = [], 0
    for length in lengths:
        starts.append(offset)
        offset += length
    return {'token_ids': list(range(total)), 'target_ids': [i % 8 for i in range(total)],
            'positions': [[i, 0, 0] for i in range(total)], 'document_starts': starts, 'phase': 'measured', 'index': 0}


class MeasureStepTests(unittest.TestCase):
    def setUp(self):
        subject._ROUTING_BUFFERS.clear()

    def test_resident_step_row_uses_device_buffers(self):
        lengths = (300, 520)
        model = ResidentModel(lengths, 21)
        optimizer = torch.optim.SGD([model.weight], lr=0.1)
        row = subject.measure_step(model, optimizer, pack_for(lengths), device=torch.device('cpu'), verify_routes=True)
        geometry, global_payload, locals_ = fixture_payloads(lengths, 21)
        expected = subject.RoutingStatisticsBuffers(lengths, device='cpu')
        feed(expected, global_payload, locals_)
        self.assertEqual(row['routes_digest_grammar'], 'device-buffers-v1')
        self.assertEqual(row['routes_sha256'], expected.digest(expected.snapshot()))
        self.assertEqual(row['route_host_reads'], 0)
        self.assertEqual(row['routing_statistics']['chunks'], 5)
        self.assertGreaterEqual(row['routing_digest_seconds'], 0.0)
        self.assertEqual(model.calls[0]['return_device_routes'], True)
        self.assertIs(model.calls[0]['collector'].__self__, subject.routing_buffers(lengths, 'cpu'))
        second = subject.measure_step(model, optimizer, pack_for(lengths), device=torch.device('cpu'))
        self.assertEqual(second['routes_sha256'], row['routes_sha256'])
        self.assertEqual(len(subject._ROUTING_BUFFERS), 1)

    def test_verify_routes_refuses_a_trace_that_differs(self):
        lengths = (300, 520)
        model = ResidentModel(lengths, 4, corrupt_trace=True)
        optimizer = torch.optim.SGD([model.weight], lr=0.1)
        with self.assertRaises(ValueError):
            subject.measure_step(model, optimizer, pack_for(lengths), device=torch.device('cpu'), verify_routes=True)
        row = subject.measure_step(model, optimizer, pack_for(lengths), device=torch.device('cpu'))
        self.assertEqual(row['routes_digest_grammar'], 'device-buffers-v1')

    def test_legacy_model_keeps_legacy_grammar(self):
        model = LegacyModel()
        optimizer = torch.optim.SGD([model.weight], lr=0.1)
        row = subject.measure_step(model, optimizer, pack_for((3, 4)), device=torch.device('cpu'))
        self.assertEqual(row['routes_digest_grammar'], 'legacy-rows-v1')
        self.assertEqual(row['routes_sha256'], hashlib.sha256(subject.canonical(
            ((0, 1, 0, (2, 5), 5), (1, 1, 0, (1, 3), 1)))).hexdigest())
        self.assertIsNone(row['routing_statistics'])
        self.assertIsNone(row['route_host_reads'])
        self.assertEqual(subject._ROUTING_BUFFERS, {})


if __name__ == '__main__':
    unittest.main()
