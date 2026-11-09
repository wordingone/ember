# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CIA eval v0 reds (lead ruling 82032 E3): model-only load, tensor adoption, ledger chain, adapter refusals.

Tiny physical fixtures on CPU only; no CUDA, no 3B object, no lm_eval dispatch. A scored run on a real checkpoint is a card
window and is never started from this file."""
import builtins
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'src/ember/governance/scripts'))
import test_issue2163_cia_transaction as fixture  # noqa: E402  (the tiny publish fixture)
import checkpoint_artifacts as artifacts  # noqa: E402
from ember.model import ember_v0_decoder as cia_decoder, ember_v0_inventory as cia_inventory  # noqa: E402
def _import_eval_module():
    """cia_eval_v0 imports the #757 scorer, whose only lm_eval use at import time is the abstract LM base class.

    Where lm_eval is installed the real one is used. Where it is not (the CI python job), a stub base class stands in
    for the duration of the import only and is removed again, so no other test in the process sees a fake lm_eval.
    The one path that needs the real harness (run_evaluation past its task check) is not exercised here.
    """
    import importlib.util
    if importlib.util.find_spec('lm_eval') is not None:
        import cia_eval_v0 as module
        return module, False
    names = ('lm_eval', 'lm_eval.api', 'lm_eval.api.model')
    stubs = {name: type(sys)(name) for name in names}
    stubs['lm_eval.api.model'].LM = type('LM', (), {})
    sys.modules.update(stubs)
    try:
        import cia_eval_v0 as module
    finally:
        for name in names:
            sys.modules.pop(name, None)
    return module, True


ev, LM_EVAL_STUBBED = _import_eval_module()


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
        self.assertEqual(load['objects_verified'], 26)
        self.assertEqual(load['parameter_count'], 208)
        self.assertEqual(load['tensor_count'], 26)
        self.assertEqual(load['checkpoint_manifest_sha256'], self.manifest_sha())
        self.assertEqual(load['global_step'], 0)
        del receipt

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


class AdoptCpuTensorsTests(unittest.TestCase):
    def setUp(self):
        self.specs = (cia_inventory.TensorSpec('embedding.weight', (4,), 'core'),
                      cia_inventory.TensorSpec('experts.0.weight', (3,), 'expert', 0))
        patcher = patch.object(cia_decoder, 'equation_inventory', return_value=self.specs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.model = SimpleNamespace(
            _parameter_device='meta', _execution_device=None, calls=0,
            weights={s.name.replace('.', '__'): torch.nn.Parameter(torch.empty(s.shape, device='meta', dtype=torch.bfloat16))
                     for s in self.specs})
        self.model.parameter_inventory = lambda: self.model.__setattr__('calls', self.model.calls + 1)

    def adopt(self, tensors):
        return cia_decoder.CIADecoder.adopt_cpu_tensors(self.model, tensors)

    def good(self):
        return {s.name: torch.full(s.shape, i + 1, dtype=torch.bfloat16) for i, s in enumerate(self.specs)}

    def test_adoption_moves_the_verified_tensors_in_without_initialisation(self):
        tensors = self.good()
        self.adopt(tensors)
        self.assertEqual(self.model._parameter_device, 'cpu')
        for spec in self.specs:
            value = self.model.weights[spec.name.replace('.', '__')]
            self.assertTrue(torch.equal(value.data, tensors[spec.name]))
        self.assertEqual(self.model.calls, 1)

    def test_extra_missing_wrong_dtype_wrong_shape_refuse(self):
        extra = self.good(); extra['rogue'] = torch.zeros(1, dtype=torch.bfloat16)
        missing = self.good(); del missing['experts.0.weight']
        wrong_dtype = self.good(); wrong_dtype['embedding.weight'] = wrong_dtype['embedding.weight'].float()
        wrong_shape = self.good(); wrong_shape['embedding.weight'] = torch.zeros(5, dtype=torch.bfloat16)
        for case in (extra, missing, wrong_dtype, wrong_shape):
            with self.assertRaises(ValueError):
                self.adopt(case)
            self.assertEqual(self.model._parameter_device, 'meta')

    def test_second_adoption_refuses(self):
        self.adopt(self.good())
        with self.assertRaisesRegex(ValueError, 'only once'):
            self.adopt(self.good())


class LedgerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'ledger.jsonl')

    def test_rows_chain_and_verify_and_zeros_are_kept(self):
        first = ev.append_ledger_row(self.path, {'task': 'arc_challenge', 'n': 5, 'metrics': {'acc,none': 0.0}})
        second = ev.append_ledger_row(self.path, {'task': 'hellaswag', 'n': 5, 'metrics': {'acc,none': 0.0}})
        self.assertIsNone(first['prev_row_sha256'])
        self.assertEqual(second['prev_row_sha256'], ev._row_sha256(first))
        self.assertEqual(ev.verify_ledger(self.path), 2)
        self.assertEqual(json.loads(Path(self.path).read_text().splitlines()[0])['metrics']['acc,none'], 0.0)

    def test_edited_or_dropped_row_breaks_the_chain(self):
        for i in range(3):
            ev.append_ledger_row(self.path, {'task': 't%d' % i, 'n': i})
        lines = Path(self.path).read_text().splitlines()
        Path(self.path).write_text('\n'.join([lines[0].replace('"n":0', '"n":9'), lines[1], lines[2]]) + '\n')
        with self.assertRaises(ev.CIAEvalRefusal):
            ev.verify_ledger(self.path)
        Path(self.path).write_text('\n'.join([lines[0], lines[2]]) + '\n')
        with self.assertRaises(ev.CIAEvalRefusal):
            ev.verify_ledger(self.path)

    def test_unreadable_last_row_refuses_the_append(self):
        ev.append_ledger_row(self.path, {'task': 'a'})
        with open(self.path, 'ab') as handle:
            handle.write(b'not json\n')
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'LAST_ROW_UNREADABLE'):
            ev.append_ledger_row(self.path, {'task': 'b'})


class AdapterTests(unittest.TestCase):
    def decoder(self, forward):
        class Decoder:
            def candidate_step(self):
                raise AssertionError('cpu run entered candidate_step')

            def embed_text(self, tokens):
                return tokens.float().unsqueeze(-1)

            __call__ = forward
        return Decoder()

    def test_adapter_returns_the_decoder_logits_with_a_batch_axis_and_records_what_ran(self):
        seen = {}

        def forward(self_decoder, embedded, positions, document_starts, batch_documents):
            seen.update(positions=positions.clone(), starts=document_starts, batch=batch_documents)
            return torch.zeros(embedded.shape[0], 7)
        adapter = ev.CIALogitsAdapter(self.decoder(forward), device='cpu')
        logits = adapter(torch.tensor([[5, 6, 7]]))
        self.assertEqual(tuple(logits.shape), (1, 3, 7))
        self.assertEqual(seen['positions'].tolist(), [[0, 0, 0], [1, 0, 0], [2, 0, 0]])
        self.assertEqual(seen['starts'], (0,))
        self.assertIs(seen['batch'], True)
        self.assertEqual(adapter.executed['forward_calls'], 1)
        self.assertIs(adapter.executed['candidate_step_entered'], False)
        self.assertEqual(adapter.executed['last_logits_shape'], [3, 7])

    def test_batch_other_than_one_and_out_of_range_lengths_refuse(self):
        adapter = ev.CIALogitsAdapter(self.decoder(lambda *a, **k: None), device='cpu')
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'BATCH_ONE'):
            adapter(torch.zeros((2, 3), dtype=torch.long))
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'POSITIONS_REFUSED'):
            adapter(torch.zeros((1, ev.MAX_POSITIONS + 1), dtype=torch.long))
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'POSITIONS_REFUSED'):
            adapter(torch.zeros((1, 0), dtype=torch.long))

    def test_a_failing_forward_is_wrapped_with_the_clause_and_never_swallowed(self):
        def forward(*args, **kwargs):
            raise RuntimeError('boom')
        adapter = ev.CIALogitsAdapter(self.decoder(forward), device='cpu')
        with self.assertRaises(ev.ForwardFailed) as caught:
            adapter(torch.tensor([[1, 2]]))
        self.assertIn('boom', str(caught.exception))
        self.assertEqual(ev.ForwardFailed.clause, 'inference-forward-actually-ran')
        self.assertEqual(adapter.executed['forward_calls'], 0)

    def test_generate_until_is_refused_in_v0(self):
        scorer = ev.CIALM.__new__(ev.CIALM)
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'GENERATE_UNTIL_NOT_IMPLEMENTED'):
            scorer.generate_until([])

    def test_unbound_task_refuses_before_anything_loads(self):
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'UNBOUND_EVALUATOR_TASK'):
            ev.run_evaluation(checkpoint_dir='x', manifest_sha256='0' * 64, tasks=['mmlu'], limit=5, device='cpu',
                              out_dir='x', ledger_path='x')


if __name__ == '__main__':
    unittest.main()
