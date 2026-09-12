"""CPU checks of declared hour identity and completion accounting; no training claim."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import os
from pathlib import Path
import sys
import unittest
import tempfile

SOURCE = Path(os.environ.get('CIA_HOUR_SOURCE', str(Path(__file__).resolve().parents[2] /
    'src/ember/infrastructure/tools/ember-restart-3b/cia_hour.py')))
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
runner = load(SOURCE.with_name('cia_step_runner.py'), 'tested_hour_runner')
subject = load(SOURCE, 'tested_cia_hour') if SOURCE.is_file() else None


class HourContractTests(unittest.TestCase):
    def test_probe_execution_mode_cannot_differ_from_consuming_hour(self):
        identity = dict(source_commit='a'*40, source_sha256={}, config_sha256='b'*64,
                        data={}, seed=1, support={}, production_mixture={})
        for mode in (None, 'resident-segmented-capture', 'resident-dynamic-capture'):
            bound = dict(identity, **({'execution_mode': mode} if mode else {}))
            subject.validate_probe_inputs(runner, bound, bound)
            other = dict(identity, execution_mode='resident-dynamic-capture' if mode != 'resident-dynamic-capture'
                         else 'resident-segmented-capture')
            with self.assertRaisesRegex(ValueError, 'execution mode differs'):
                subject.validate_probe_inputs(runner, other, bound)

    def test_frozen_coverage_refuses_added_or_missing_dataset(self):
        proof = subject.map_ledger_spans([{'spans':[dict(sha256='a',token_start=0,token_end=4)]}],
                                        {'one':{'a'},'two':{'b'}}, set())
        self.assertEqual(proof['per_dataset'], {'one':dict(spans=1,tokens=4)})
        coverage = dict(declared_dataset_ids=['one','two'],covered_dataset_ids=['one'],uncovered_dataset_ids=['two'],
                        spans_total=1,spans_mapped=1,basis='fixture',claim='fixture')
        subject.validate_coverage(dict(dataset_ids=['one','two'],dataset_coverage=coverage),proof)
        for changed in ([],['one','two']):
            with self.assertRaisesRegex(ValueError, 'actual dataset coverage'):
                subject.validate_coverage(dict(dataset_ids=['one','two'],dataset_coverage=coverage),
                                          dict(proof,dataset_ids=changed))

    def test_unmapped_span_sha_refuses(self):
        with self.assertRaisesRegex(ValueError, 'span sha lacks admitted'):
            subject.map_ledger_spans([{'spans': [{'sha256': 'b'*64}]}], {'train': {'a'*64}}, set())
        with self.assertRaisesRegex(ValueError, 'protected evaluation'):
            subject.map_ledger_spans([{'spans': [{'sha256': 'a'*64}]}], {'train': {'a'*64}}, {'a'*64})

    def test_present_mismatched_manifest_never_uses_absent_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'manifest.json'
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'artifact bytes differ'):
                subject.read_staging(runner, dict(staging_manifest_path=str(path),
                    staging_manifest_sha256='0'*64, staging_manifest_bytes_absent=True))
        with self.assertRaisesRegex(ValueError, 'explicit export-derived'):
            subject.read_staging(runner, dict(staging_manifest_path=None))

    def test_probe_is_explicit_and_cannot_satisfy_hour_completion(self):
        identity = dict(hour=dict(schema='checkpoint-probe-v1', arm='treatment', minimum_wall_seconds=0,
                                 minimum_measured_steps=2))
        self.assertTrue(runner.hour_mode(identity))
        self.assertFalse(subject.hour_complete(measured_updates=2, elapsed_seconds=3600))
        with self.assertRaises(ValueError):
            runner.hour_mode(dict(hour=dict(identity['hour'], schema='governed-hour-v1')))
        subject.validate_checkpoint_probe(runner, identity)
        with self.assertRaisesRegex(ValueError, 'completed bound checkpoint probe'):
            subject.validate_checkpoint_probe(runner, dict(hour=dict(schema='governed-hour-v1')))
        with self.assertRaisesRegex(ValueError, 'cannot consume another'):
            subject.validate_checkpoint_probe(runner, dict(identity, checkpoint_probe={}))

    def test_hour_packs_are_lazy_complete_and_stop_at_declared_capacity(self):
        self.assertIsNotNone(subject)
        calls = []
        class Stream:
            def next_episode(self, *, shard_index, token_offset, sequence_length):
                calls.append(token_offset)
                return dict(token_ids=list(range(sequence_length)), target_ids=list(range(1, sequence_length + 1))), dict(shard_index=shard_index, token_offset=token_offset + sequence_length)
        packs = subject.HourPacks(Stream(), dict(shard_index=0, token_offset=0), maximum_steps=2, sequence=2, documents=2)
        self.assertEqual(calls, [])
        first = packs.next_pack()
        self.assertEqual(calls, [0, 2])
        self.assertEqual(first['phase'], 'warm')
        self.assertEqual(first['document_starts'], [0, 2])
        self.assertEqual(packs.next_pack()['cursor_after']['token_offset'], 8)
        with self.assertRaises(ValueError):
            packs.next_pack()

    def test_hour_selection_is_explicit_and_preserves_ordinary_limits(self):
        identity = dict(hour=dict(schema='governed-hour-v1', arm='control', minimum_wall_seconds=3600,
                                  minimum_measured_steps=1024))
        self.assertTrue(runner.hour_mode(identity))
        self.assertFalse(runner.hour_mode({}))
        self.assertEqual(runner.resource_limits({})['wall_seconds'], 600)
        self.assertEqual(runner.resource_limits(identity)['wall_seconds'], 4500)
        self.assertEqual(runner.resource_limits(identity)['max_b_write_gib'], 24)
        with self.assertRaises(ValueError):
            runner.hour_mode(dict(identity, trajectory={}))
        with self.assertRaises(ValueError):
            runner.hour_mode(dict(hour=dict(identity['hour'], minimum_wall_seconds=3599)))
        geometry = dict(sequence_length=1024, documents_per_step=4, warm_steps=1, measured_steps=32768)
        self.assertEqual(runner.geometry_counts(geometry, hour=True), (1024, 4, 1, 32768))
        with self.assertRaises(ValueError):
            runner.geometry_counts(geometry)

    def test_hour_completion_requires_both_observed_wall_and_updates(self):
        self.assertIsNotNone(subject)
        self.assertFalse(subject.hour_complete(measured_updates=1024, elapsed_seconds=3599.9))
        self.assertFalse(subject.hour_complete(measured_updates=1023, elapsed_seconds=3601))
        self.assertTrue(subject.hour_complete(measured_updates=1024, elapsed_seconds=3600))
        with self.assertRaises(ValueError):
            subject.hour_complete(measured_updates=1024, elapsed_seconds=float('nan'))


if __name__ == '__main__':
    unittest.main()
