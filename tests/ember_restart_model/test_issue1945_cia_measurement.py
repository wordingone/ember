"""CPU checks of the declared 1,024-update long-measurement identity; no throughput or qualification claim."""
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
import unittest

SOURCE = Path(os.environ.get('CIA_MEASUREMENT_RUNNER', str(Path(__file__).resolve().parents[2] /
    'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py')))
ROOT = SOURCE.resolve().parents[5]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(SOURCE, 'tested_measurement_runner')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


GEOMETRY = dict(sequence_length=1024, documents_per_step=4, warm_steps=1, measured_steps=1024)


def measurement_identity(arm):
    identity = dict(measurement=dict(schema='governed-1024-v1', arm=arm))
    if runner.MEASUREMENT_ARMS[arm] is not None:
        identity['execution_mode'] = runner.MEASUREMENT_ARMS[arm]
    return identity


class MeasurementGeometryTests(unittest.TestCase):
    def test_measurement_geometry_is_exact_and_exclusive(self):
        self.assertEqual(runner.geometry_counts(GEOMETRY, measurement=True), (1024, 4, 1, 1024))
        for changed in (dict(measured_steps=1023), dict(measured_steps=1025), dict(warm_steps=0), dict(warm_steps=2),
                        dict(documents_per_step=2), dict(sequence_length=512)):
            with self.assertRaises(ValueError):
                runner.geometry_counts(dict(GEOMETRY, **changed), measurement=True)
        with self.assertRaises(ValueError):  # the ordinary bound of eight measured steps is unchanged
            runner.geometry_counts(GEOMETRY)
        with self.assertRaises(ValueError):  # the trajectory bound is unchanged
            runner.geometry_counts(GEOMETRY, trajectory=True)
        for flags in (dict(measurement=True, hour=True), dict(measurement=True, trajectory=True), dict(measurement=1)):
            with self.assertRaises(ValueError):
                runner.geometry_counts(GEOMETRY, **flags)
        ordinary = dict(sequence_length=1024, documents_per_step=4, warm_steps=1, measured_steps=8)
        self.assertEqual(runner.geometry_counts(ordinary), (1024, 4, 1, 8))


class MeasurementIdentityTests(unittest.TestCase):
    def test_measurement_identity_is_explicit_arm_bound_and_exclusive(self):
        self.assertFalse(runner.measurement_mode({}))
        for arm in ('eager', 'segmented', 'dynamic', 'fused'):
            self.assertTrue(runner.measurement_mode(measurement_identity(arm)))
        wrong = [
            dict(measurement=dict(schema='governed-1024-v1', arm='fused')),  # fused without its dynamic regime
            dict(measurement=dict(schema='governed-1024-v1', arm='eager'), execution_mode='resident-segmented-capture'),
            dict(measurement=dict(schema='governed-1024-v0', arm='eager')),
            dict(measurement=dict(schema='governed-1024-v1', arm='treatment')),
            dict(measurement=dict(schema='governed-1024-v1', arm='eager', measured_steps=1024)),
            dict(measurement=['governed-1024-v1', 'eager']),
            dict(measurement_identity('eager'), hour=dict(schema='governed-hour-v1', arm='control',
                                                          minimum_wall_seconds=3600, minimum_measured_steps=1024)),
            dict(measurement_identity('dynamic'), trajectory=dict(schema='reference-noise-floor-64-v1', arm='Tdynamic',
                                                                  comparison_id='0' * 32)),
        ]
        for identity in wrong:
            with self.assertRaises(ValueError):
                runner.measurement_mode(identity)
        hour = dict(hour=dict(schema='governed-hour-v1', arm='control', minimum_wall_seconds=3600,
                              minimum_measured_steps=1024))
        self.assertTrue(runner.hour_mode(hour))
        with self.assertRaises(ValueError):
            runner.hour_mode(dict(hour, measurement=dict(schema='governed-1024-v1', arm='eager')))

    def test_measurement_resource_envelope_is_the_ordinary_one_with_a_bounded_wall(self):
        limits = runner.resource_limits(measurement_identity('fused'))
        self.assertEqual(limits['wall_seconds'], 3000)
        self.assertEqual({k: v for k, v in limits.items() if k != 'wall_seconds'},
                         {k: v for k, v in runner.LIMITS.items() if k != 'wall_seconds'})
        self.assertEqual(runner.resource_limits({})['wall_seconds'], 600)
        self.assertEqual(runner.resource_limits(dict(hour=dict(schema='governed-hour-v1', arm='treatment',
            minimum_wall_seconds=3600, minimum_measured_steps=1024)))['wall_seconds'], 4500)

    def test_fused_optimizer_is_a_declared_treatment_never_a_request(self):
        base = {'name': 'AdamW', 'foreach': False, 'lr': 0.001, 'betas': [0.9, 0.999],
                'eps': 1e-8, 'weight_decay': 0.01, 'membership': 'complete_parameter_inventory'}
        fused = dict(base, fused=True)
        self.assertEqual(runner.expected_optimizer({}), base)
        self.assertEqual(runner.expected_optimizer(measurement_identity('fused')), fused)
        for arm in ('eager', 'segmented', 'dynamic'):
            self.assertEqual(runner.expected_optimizer(measurement_identity(arm)), base)
        self.assertEqual(runner.expected_optimizer(dict(trajectory=dict(schema='reference-noise-floor-64-v1',
            arm='Tfused', comparison_id='0' * 32), execution_mode='resident-dynamic-capture')), fused)
        self.assertEqual(runner.expected_optimizer(dict(trajectory=dict(schema='reference-noise-floor-64-v1',
            arm='Tdynamic', comparison_id='0' * 32), execution_mode='resident-dynamic-capture')), base)
        self.assertEqual(runner.expected_optimizer(dict(hour=dict(schema='governed-hour-v1', arm='treatment',
            minimum_wall_seconds=3600, minimum_measured_steps=1024))), fused)
        self.assertEqual(runner.expected_optimizer(dict(hour=dict(schema='governed-hour-v1', arm='control',
            minimum_wall_seconds=3600, minimum_measured_steps=1024))), base)
        # The executed constructor receives the fused flag exactly when the validated definition declares it.
        self.assertEqual(runner.optimizer_kwargs(base),
                         dict(lr=0.001, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False))
        self.assertEqual(runner.optimizer_kwargs(fused),
                         dict(lr=0.001, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True))
        self.assertNotIn('fused', runner.optimizer_kwargs(dict(base, fused=False)))
        import torch
        parameter = torch.zeros(2, requires_grad=True)
        optimizer = torch.optim.AdamW([parameter], **runner.optimizer_kwargs(base))
        self.assertEqual(optimizer.defaults['foreach'], False)
        self.assertFalse(optimizer.defaults.get('fused'))


class MeasurementInputTests(unittest.TestCase):
    def test_measurement_packs_are_lazy_and_carry_their_cursor(self):
        calls = []

        class Stream:
            def next_episode(self, *, shard_index, token_offset, sequence_length):
                calls.append(token_offset)
                return (dict(token_ids=list(range(sequence_length)), target_ids=list(range(1, sequence_length + 1))),
                        dict(shard_index=shard_index, token_offset=token_offset + sequence_length))

        packs = runner.MeasurementPacks(Stream(), dict(shard_index=3, token_offset=0), maximum_steps=3, sequence=2,
                                        documents=2, warm=1)
        self.assertEqual(calls, [])
        first = packs.next_pack()
        self.assertEqual(calls, [0, 2])
        self.assertEqual((first['index'], first['phase'], first['document_starts']), (0, 'warm', [0, 2]))
        self.assertEqual(first['positions'], [[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]])
        self.assertEqual(first['cursor_before'], dict(shard_index=3, token_offset=0))
        self.assertEqual(first['cursor_after'], dict(shard_index=3, token_offset=4))
        second = packs.next_pack()
        self.assertEqual((second['index'], second['phase'], second['cursor_before']), (1, 'measured', first['cursor_after']))
        third = packs.next_pack()
        self.assertEqual(third['cursor_after']['token_offset'], 12)
        with self.assertRaises(ValueError):
            packs.next_pack()
        prepared = dict(packs=runner.MeasurementPacks(Stream(), dict(shard_index=0, token_offset=0),
                                                      maximum_steps=2, sequence=2, documents=2, warm=1))
        prepared['first'] = prepared['packs'].next_pack()
        self.assertEqual([pack['index'] for pack in runner.measurement_packs(prepared)], [0, 1])
        counts = dict(sequence=2, documents=2, warm=1, measured=2)
        runner.verify_measurement_pack(first, 0, **counts)
        runner.verify_measurement_pack(second, 1, **counts)
        for pack, index in ((first, 1), (dict(first, phase='measured'), 0), (dict(second, token_ids=[1, 2, 3]), 1),
                            (dict(second, document_starts=[0, 1]), 1), (third, 3)):
            with self.assertRaises(ValueError):
                runner.verify_measurement_pack(pack, index, **counts)

    def test_measurement_binding_is_a_declaration_digest_over_the_real_stream(self):
        base = ROOT / 'target' / 'cia-measurement-tests'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            root = Path(temporary)
            tokenizer = canonical({'model': {'vocab': {str(i): i for i in range(16)}}})
            (root / 'tokenizer.json').write_bytes(tokenizer)
            planned = 1025 * 4 * 1024
            tokens = planned + 4096 + 1  # one spare pack beyond the plan plus the final target
            (root / 'shard.bin').write_bytes(b'\x01\x00' * tokens)
            receipt = canonical({
                'ticket': 'TOKEN-SHARDS-V0',
                'premises': {'tokenizer_json': {'path': 'tokenizer.json', 'sha256': digest(tokenizer)}},
                'shards': [{'name': 'shard.bin', 'sha256': digest((root / 'shard.bin').read_bytes()), 'n_tokens': tokens}],
                'total_stream_tokens': tokens, 'catalog_binding': {'shard_tokens': tokens}})
            (root / 'receipt.json').write_bytes(receipt)
            data = {'receipt_path': str(root / 'receipt.json'), 'receipt_sha256': digest(receipt),
                    'tokenizer_path': str(root / 'tokenizer.json'), 'tokenizer_sha256': digest(tokenizer),
                    'shards_root': str(root), 'shard_ledger_path': None, 'shard_ledger_sha256': None,
                    'cursor': {'shard_index': 0, 'token_offset': 0}}
            prepared = runner.prepare_measurement_inputs(data, GEOMETRY)
            binding = prepared['binding']
            declaration = {key: binding[key] for key in ('receipt_sha256', 'tokenizer_sha256', 'shard_ledger_sha256',
                                                         'cursor_start', 'geometry', 'span', 'planned_positions')}
            self.assertEqual(binding['input_sha256'], digest(canonical(declaration)))
            self.assertEqual(binding['input_digest_grammar'], 'measurement-receipt-cursor-span-v1')
            self.assertEqual(binding['planned_positions'], planned)
            self.assertEqual(binding['cursor_start'], {'shard_index': 0, 'token_offset': 0})
            self.assertIsNone(binding['shard_ledger_path'])
            self.assertTrue(prepared['measurement'])
            first = prepared['first']
            self.assertEqual((first['index'], first['phase'], len(first['token_ids'])), (0, 'warm', 4096))
            self.assertEqual(first['document_starts'], [0, 1024, 2048, 3072])
            self.assertEqual(first['cursor_after'], {'shard_index': 0, 'token_offset': 4096})
            self.assertEqual(prepared['packs'].maximum_steps, 1025)
            self.assertEqual(prepared['packs'].index, 1)
            runner.verify_measurement_pack(first, 0, sequence=1024, documents=4, warm=1, measured=1024)
            moved = runner.prepare_measurement_inputs(dict(data, cursor={'shard_index': 0, 'token_offset': 4096}), GEOMETRY)
            self.assertNotEqual(moved['binding']['input_sha256'], binding['input_sha256'])
            with self.assertRaises(ValueError):  # the plan must fit the admitted span
                runner.prepare_measurement_inputs(dict(data, cursor={'shard_index': 0, 'token_offset': 8192}), GEOMETRY)
            with self.assertRaises(ValueError):  # ordinary geometry is not a long measurement
                runner.prepare_measurement_inputs(data, dict(GEOMETRY, measured_steps=8))

    def test_measurement_summary_is_nearest_rank_over_measured_rates(self):
        rates = [float(value) for value in range(100, 0, -1)]
        summary = runner.measurement_summary(rates)
        self.assertEqual(summary['measured_updates'], 100)
        self.assertEqual(summary['estimator'], 'nearest-rank-lower')
        self.assertEqual(summary['positions_per_second'],
                         {'min': 1.0, 'p10': 10.0, 'p50': 50.0, 'p90': 90.0, 'max': 100.0, 'mean': 50.5})
        for bad in ([], [1.0, float('nan')], [0.0], [1.0, 2]):
            with self.assertRaises(ValueError):
                runner.measurement_summary(bad)


if __name__ == '__main__':
    unittest.main()
