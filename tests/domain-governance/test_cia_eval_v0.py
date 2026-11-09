# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CIA eval v0 reds (lead ruling 82032 E3): tensor adoption, ledger chain, adapter refusals, bound-task loading.

Tiny physical fixtures on CPU only; no CUDA, no 3B object, no lm_eval dispatch. A scored run on a real checkpoint is a card
window and is never started from this file. The model-only loader these runs consume is tested in
tests/ember_restart_model/domain-governance/test_cia_model_only_load.py."""
import hashlib
import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
sys.path.insert(0, str(ROOT / 'src/ember/governance/scripts'))
from ember.model import ember_v0_decoder as cia_decoder, ember_v0_inventory as cia_inventory  # noqa: E402

IMPORT_CHAIN = ('cia_eval_v0', 'legb_inprocess_scorer', 'a1_predicate_scan', 'build_decontam_batch_mp')


def _importable(name):
    """False when the module cannot be imported, including when sys.modules[name] is None (the blocked shape)."""
    return importlib.util.find_spec(name) is not None


def _import_eval_module(stub_psutil=True):
    """cia_eval_v0 imports the #757 scorer, whose import chain needs two modules the CI python job does not install.

    lm_eval: the only use at import time is the abstract LM base class. psutil: build_decontam_batch_mp imports it at
    module level and calls psutil.cpu_count() once at import (DEFAULT_MP_WORKERS); every other call is in code this file never runs. Where a module is installed the real one is used. Where
    it is not, a stub stands in for the duration of the import only and is removed again, so no other test in the
    process sees a fake. The one path that needs the real harness (run_evaluation past its task check) is not exercised here.
    """
    stubs = {}
    if not _importable('lm_eval'):
        for name in ('lm_eval', 'lm_eval.api', 'lm_eval.api.model'):
            stubs[name] = type(sys)(name)
        stubs['lm_eval.api.model'].LM = type('LM', (), {})
    if stub_psutil and not _importable('psutil'):
        stubs['psutil'] = type(sys)('psutil')
        stubs['psutil'].cpu_count = lambda *args, **kwargs: 8  # the one module-level call (DEFAULT_MP_WORKERS)
    previous = {name: sys.modules.get(name, False) for name in stubs}
    sys.modules.update(stubs)
    try:
        module = importlib.import_module('cia_eval_v0')
    finally:
        for name, old in previous.items():
            if old is False:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    return module, bool(stubs)


ev, LM_EVAL_STUBBED = _import_eval_module()


class ImportShapeTests(unittest.TestCase):
    """The CI python job has no psutil: the import chain must be reproducible here, and the helper must cover it."""

    def setUp(self):
        self.saved = {name: sys.modules.pop(name, False) for name in IMPORT_CHAIN + ('psutil',)}
        sys.modules['psutil'] = None  # `import psutil` now raises ModuleNotFoundError, as on the runner

    def tearDown(self):
        for name, old in self.saved.items():
            if old is False:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

    def test_the_runner_shape_fails_without_the_stub_and_loads_with_it(self):
        with self.assertRaises(ModuleNotFoundError) as caught:
            _import_eval_module(stub_psutil=False)
        self.assertEqual(caught.exception.name, 'psutil')
        for name in IMPORT_CHAIN:
            sys.modules.pop(name, None)
        module, stubbed = _import_eval_module()
        self.assertTrue(stubbed)
        self.assertEqual(module.BOUND_TASKS, ev.BOUND_TASKS)
        self.assertIsNone(sys.modules['psutil'])  # the blocked entry is restored, no stub left behind


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


class _Lm0412FakeManager:
    """The one lm_eval 0.4.12 behaviour that broke the first real run: _build_group_members gives a bare-string member the
    group's OWN override dict (which carries "task": [members]); a dict member re-sets its own "task" name over it. The member
    name is then used as a dict key, so a list name is unhashable."""

    def load(self, spec):
        overrides = dict(spec)
        names = {}
        for member in spec['task']:
            item_overrides = {**overrides, **member} if isinstance(member, dict) else dict(overrides)
            names[item_overrides['task']] = member   # TypeError: unhashable type: 'list' for a string member
        return {'tasks': {name: SimpleNamespace(member=member) for name, member in names.items()}, 'groups': {}}


class BoundTaskLoadTests(unittest.TestCase):
    TASKS = ['arc_challenge', 'hellaswag']

    def test_every_member_is_a_dict_that_names_its_own_task(self):
        spec = ev.dict_member_task_specs(self.TASKS)
        self.assertEqual([member['task'] for member in spec['task']], self.TASKS)
        self.assertTrue(all(isinstance(member, dict) for member in spec['task']))
        self.assertIn('dataset_kwargs', spec['task'][1])   # hellaswag keeps its revision pin

    def test_the_shared_spec_with_a_string_member_is_the_failing_shape_and_the_dict_spec_loads(self):
        with self.assertRaises(TypeError):
            _Lm0412FakeManager().load(ev.build_bound_task_specs(self.TASKS))
        tasks, by_name = ev.load_bound_tasks_dict_members(self.TASKS, _Lm0412FakeManager())
        self.assertEqual(sorted(by_name), sorted(self.TASKS))
        self.assertEqual(len(tasks), 2)

    def test_a_manager_that_returns_other_tasks_refuses(self):
        class Other:
            def load(self, spec):
                return {'tasks': {'piqa': object()}}
        with self.assertRaisesRegex(ev.CIAEvalRefusal, 'EVALUATOR_TASK_LOAD_CHANGED'):
            ev.load_bound_tasks_dict_members(self.TASKS, Other())

    @unittest.skipIf(LM_EVAL_STUBBED, 'the real lm_eval is not installed here')
    def test_real_task_manager_loads_both_bound_tasks_offline(self):
        import os
        cache = Path.home() / '.cache/huggingface/datasets'
        if not ((cache / 'allenai___ai2_arc').is_dir() and (cache / 'Rowan___hellaswag').is_dir()):
            self.skipTest('arc_challenge / hellaswag are not in the offline dataset cache')
        from lm_eval.tasks import TaskManager
        with patch.dict(os.environ, {'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'}):
            tasks, by_name = ev.load_bound_tasks_dict_members(self.TASKS, TaskManager())
        self.assertEqual(sorted(by_name), sorted(self.TASKS))
        self.assertEqual(by_name['arc_challenge'].config.dataset_name, 'ARC-Challenge')
        self.assertEqual(by_name['hellaswag'].config.dataset_kwargs.get('revision'),
                         ev.build_bound_task_specs(['hellaswag'])['task'][0]['dataset_kwargs']['revision'])


if __name__ == '__main__':
    unittest.main()
