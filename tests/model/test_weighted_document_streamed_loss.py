# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cce-document-v2 (one weighted CCE call per update) against the cce-document-v1 repeated-row path, on CPU.

The v1 path repeats every answer row (weight - 1) extra times and calls the operator once per document; v2 calls it
once over unique rows with a per-row multiplier. In float64 with a dense operator the two are the same function, so
loss, hidden gradient and classifier gradient agree to rounding. Selections come from the runner's own
loss_selection / staged_inputs, so the runner plumbing is exercised too."""
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
spec = importlib.util.spec_from_file_location('v2_runner', TOOLS / 'cia_step_runner.py')
runner = importlib.util.module_from_spec(spec); sys.modules[spec.name] = runner; spec.loader.exec_module(runner)
loss_module = importlib.import_module('ember.model.ember_v0_streamed_loss')

IGNORE = runner.IGNORE_TARGET
WEIGHT = 7


def dense(e, c, y, w=None):
    if w is None:
        return F.cross_entropy(e @ c.T, y, reduction='sum')
    return (F.cross_entropy(e @ c.T, y, reduction='none') * w.to(e.dtype)).sum()


class Counting:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(len(args))
        return dense(*args)


def micro(order='image-first'):
    """Four documents; the answer-bearing (image-text style) document is FIRST, not last, to pin general order.
    Document 2 is fully loss-bearing but holds an answer row: it must still be weighted."""
    lengths = (6, 5, 7, 4)
    starts = [0, 6, 11, 18]
    targets = [3, IGNORE, 1, IGNORE, 4, 0,    # doc0: selected, answer rows 2 and 5
               2, 2, 9, 1, 0,                # doc1: whole, no answer
               IGNORE, 5, 6, IGNORE, 7, 8, 1,  # doc2: selected, no answer
               0, 3, 2, 4]                   # doc3: whole, answer row 20
    if order != 'image-first':
        raise ValueError(order)
    return dict(token_ids=list(range(22)), target_ids=targets, positions=list(range(22)),
                document_starts=starts, answer_rows=(2, 5, 20)), lengths


class WeightedDocumentLoss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls._env = os.environ.get('EMBER_ANSWER_WEIGHT')
        os.environ['EMBER_ANSWER_WEIGHT'] = str(WEIGHT)

    @classmethod
    def tearDownClass(cls):
        if cls._env is None:
            os.environ.pop('EMBER_ANSWER_WEIGHT', None)
        else:
            os.environ['EMBER_ANSWER_WEIGHT'] = cls._env

    def operands(self, seed=194599):
        torch.manual_seed(seed)
        hidden = torch.randn(22, 5, dtype=torch.float64, requires_grad=True)
        owner = torch.randn(11, 5, dtype=torch.float64, requires_grad=True)
        return hidden, owner

    def run_v1(self, m, lengths, targets):
        sel = runner.loss_selection(m, torch.device('cpu'))
        h, c = self.operands()
        loss = loss_module.document_streamed_loss(h, c, targets, lengths, sel['denominator'], operator=dense,
                                                  selections=sel['selections'])
        loss.backward()
        return loss.detach(), h.grad, c.grad, sel['denominator']

    def run_v2(self, sel, lengths, targets, operator=dense):
        h, c = self.operands()
        loss = loss_module.weighted_document_streamed_loss(h, c, targets, lengths, sel['denominator'],
                                                           operator=operator, selections=sel['selections'])
        loss.backward()
        return loss, h.grad, c.grad

    def test_merged_folded_forward_and_backward_equal_repeated_row_path(self):
        m, lengths = micro()
        targets = torch.tensor(m['target_ids']).clamp(min=0)
        v1_loss, v1_h, v1_c, denominator = self.run_v1(m, lengths, targets)
        for name, sel in (('loss_selection', runner.loss_selection(m, torch.device('cpu'), fold=True)),
                          ('staged_inputs', runner.staged_inputs(m, torch.device('cpu'), fold=True)[3])):
            with self.subTest(name):
                self.assertEqual(sel['denominator'], denominator)
                counting = Counting()
                loss, h, c = self.run_v2(sel, lengths, targets, counting)
                self.assertEqual(counting.calls, [4])  # ONE weighted call for all four documents
                torch.testing.assert_close(loss.detach(), v1_loss, atol=1e-13, rtol=1e-13)
                torch.testing.assert_close(h, v1_h, atol=1e-13, rtol=1e-13)
                torch.testing.assert_close(c, v1_c, atol=1e-13, rtol=1e-13)
                # unselected rows (ignored targets) receive an exact zero hidden gradient
                for row in (1, 3, 11, 14):
                    self.assertTrue(bool((h[row] == 0).all()))

    def test_staged_fold_carries_unique_rows_and_weights_through_one_array(self):
        m, _ = micro()
        sel = runner.staged_inputs(m, torch.device('cpu'), fold=True)[3]
        doc0, doc1, doc2, doc3 = sel['selections']
        self.assertIsNone(doc1)
        self.assertEqual(doc0[0].tolist(), [0, 2, 4, 5])
        self.assertEqual(doc0[1].tolist(), [1.0, float(WEIGHT), 1.0, float(WEIGHT)])
        self.assertEqual(doc0[2], 2 + 2 * WEIGHT)
        self.assertEqual(doc0[1].dtype, torch.float32)
        self.assertEqual(doc2[0].tolist(), [12, 13, 15, 16, 17])
        self.assertEqual(doc2[2], 5)
        self.assertEqual(doc3[0].tolist(), [18, 19, 20, 21])  # whole document, weighted: still a selection
        self.assertEqual(doc3[2], 3 + WEIGHT)
        # the v1 staging of the same micro-step is unchanged: repeated rows, (rows, count)
        v1 = runner.staged_inputs(m, torch.device('cpu'))[3]
        self.assertEqual(v1['denominator'], sel['denominator'])
        self.assertEqual(len(v1['selections'][0]), 2)
        self.assertEqual(v1['selections'][0][1], 2 + 2 * WEIGHT)

    def test_unweighted_text_only_update_is_one_call_without_multiplier(self):
        torch.manual_seed(194598)
        h = torch.randn(8, 5, dtype=torch.float64, requires_grad=True)
        c = torch.randn(11, 5, dtype=torch.float64, requires_grad=True)
        h1, c1 = h.detach().clone().requires_grad_(), c.detach().clone().requires_grad_()
        y = torch.arange(8) % 11
        counting = Counting()
        loss = loss_module.weighted_document_streamed_loss(h, c, y, (2, 2, 2, 2), 8, operator=counting)
        loss.backward()
        self.assertEqual(counting.calls, [3])
        reference = loss_module.document_streamed_loss(h1, c1, y, (2, 2, 2, 2), 8, operator=dense)
        reference.backward()
        torch.testing.assert_close(loss.detach(), reference.detach(), atol=1e-14, rtol=1e-14)
        torch.testing.assert_close(h.grad, h1.grad, atol=1e-14, rtol=1e-14)
        torch.testing.assert_close(c.grad, c1.grad, atol=1e-14, rtol=1e-14)
        self.assertEqual(loss.cce_executed, dict(cce_calls=1, cce_rows=8, cce_weight_total=8))

    def test_executed_receipt_is_read_back_from_the_call(self):
        m, lengths = micro()
        targets = torch.tensor(m['target_ids']).clamp(min=0)
        sel = runner.staged_inputs(m, torch.device('cpu'), fold=True)[3]
        loss, _, _ = self.run_v2(sel, lengths, targets)
        unique = sum(1 for t in m['target_ids'] if t != IGNORE)
        expected = dict(cce_calls=1, cce_rows=unique, cce_weight_total=unique + (WEIGHT - 1) * len(m['answer_rows']))
        # the weight total is the sum of the weight tensor the operator received, not the declared count
        self.assertIsInstance(loss.cce_executed['cce_weight_total'], torch.Tensor)
        self.assertEqual(loss_module.executed_values(loss.cce_executed), expected)
        self.assertEqual(expected['cce_weight_total'], sel['denominator'])
        self.assertEqual(runner._cce_executed_fields([loss.cce_executed]), expected)
        self.assertEqual(runner._cce_executed_fields([loss.cce_executed] * 2)['cce_calls'], 2)
        for missing in ([], [None], [loss.cce_executed, None], [{'cce_calls': 1}]):
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(ValueError, 'did not report its execution'):
                    runner._cce_executed_fields(missing)

    def test_executed_weight_total_comes_from_the_weights_not_the_declared_count(self):
        # A declared count that disagrees with the weights is refused by the count clause, so the only way to
        # see the receipt diverge is an operator-received weight vector: forge one after validation.
        m, lengths = micro()
        targets = torch.tensor(m['target_ids']).clamp(min=0)
        sel = runner.staged_inputs(m, torch.device('cpu'), fold=True)[3]
        def doubling(e, c, y, w=None):
            if w is not None:
                w.mul_(2)  # what the operator received is what the receipt must report
            return dense(e, c, y, w)
        h, c = self.operands()
        loss = loss_module.weighted_document_streamed_loss(h, c, targets, lengths, sel['denominator'],
                                                           operator=doubling, selections=sel['selections'])
        self.assertEqual(loss_module.executed_values(loss.cce_executed)['cce_weight_total'], 2 * sel['denominator'])

    def test_missing_receipt_refuses_before_backward(self):
        for bad in (None, {}, {'cce_calls': 0, 'cce_rows': 3, 'cce_weight_total': 3},
                    {'cce_calls': 1, 'cce_rows': 3, 'cce_weight_total': 3.0}):
            with self.subTest(bad=bad):
                loss = torch.zeros(())
                if bad is not None:
                    loss.cce_executed = bad
                with self.assertRaisesRegex(ValueError, 'did not report its execution'):
                    runner._require_cce_receipt(loss)
        source = (TOOLS / 'cia_step_runner.py').read_text(encoding='utf-8')
        body = source[source.index('def measure_step('):]
        body = body[:body.index('\ndef ')]
        self.assertLess(body.index('_require_cce_receipt(loss)'), body.index('loss.backward()'))
        self.assertLess(body.index('loss.backward()'), body.index('_cce_executed_fields(executed)'))

    def test_count_must_equal_weight_total_and_rows_must_be_unique(self):
        h, c = self.operands()
        y = torch.zeros(22, dtype=torch.long)
        lengths = (6, 5, 7, 4)
        def forbidden(*args):
            self.fail('invalid weighted selection reached the operator')
        rows = torch.tensor([0, 2, 4, 5])
        w = torch.tensor([1.0, 7.0, 1.0, 7.0])
        good = (rows, w, 16)
        cases = {
            'count below weight total': (rows, w, 15),
            'count above weight total': (rows, w, 17),
            'repeated row': (torch.tensor([0, 2, 2, 5]), w, 16),
            'descending rows': (torch.tensor([5, 4, 2, 0]), w, 16),
            'row outside document': (torch.tensor([0, 2, 4, 6]), w, 16),
            'weight below one': (rows, torch.tensor([1.0, 7.0, 0.5, 7.5]), 16),
            'v1 entry shape': (rows, 4),
            'fp64 weights': (rows, w.double(), 16),
            'length mismatch': (rows, w[:3], 16),
        }
        named = {
            'count below weight total': 'count differs from its weight total',
            'count above weight total': 'count differs from its weight total',
            'repeated row': 'rows are not unique and ascending',
            'descending rows': 'rows are not unique and ascending',
            'row outside document': 'row is outside its document',
            'weight below one': 'weight is below one',
        }
        for name, entry in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, named.get(name, '')):
                    loss_module.weighted_document_streamed_loss(h, c, y, lengths, 100, operator=forbidden,
                                                                selections=(entry, None, None, None))
        with self.assertRaises(ValueError):  # denominator below the weight total
            loss_module.weighted_document_streamed_loss(h, c, y, lengths, 16 + 5 + 7 + 4 - 1, operator=forbidden,
                                                        selections=(good, None, None, None))
        loss_module.weighted_document_streamed_loss(h, c, y, lengths, 16 + 5 + 7 + 4, operator=dense,
                                                    selections=(good, None, None, None))

    def test_runner_selects_v2_by_declared_head_and_keeps_v1(self):
        self.assertEqual(runner.training_head(dict(training_head='cce-document-v2',
                                                   execution_mode='resident-dynamic-capture')), 'cce-document-v2')
        with self.assertRaises(ValueError):
            runner.training_head({'training_head': 'cce-document-v2'})
        owner = torch.nn.Parameter(torch.ones(7, 3))
        model = SimpleNamespace(_weight=lambda name: owner)
        identity = dict(execution_mode='resident-dynamic-capture')
        v1 = runner.capture_loss_kwargs(model, dict(identity, training_head='cce-document-v1'), (2, 2))['loss_fn']
        v2 = runner.capture_loss_kwargs(model, dict(identity, training_head='cce-document-v2'), (2, 2))['loss_fn']
        self.assertEqual((v1.training_head, v2.training_head), ('cce-document-v1', 'cce-document-v2'))
        self.assertEqual(runner._row_training_head(None), 'native')
        self.assertEqual(runner._row_training_head(SimpleNamespace(_cia_head_output='logits', loss_fn=v2)), 'native')
        self.assertEqual(runner._row_training_head(SimpleNamespace(_cia_head_output='hidden', loss_fn=v2)), 'cce-document-v2')
        self.assertEqual(runner._row_training_head(SimpleNamespace(_cia_head_output='hidden', loss_fn=v1)), 'cce-document-v1')
        self.assertEqual(runner._row_training_head(SimpleNamespace(_cia_head_output='hidden', loss_fn=lambda x, y: x)),
                         'cce-document-v1')

    def test_folded_rows_sum_to_the_repeated_row_count(self):
        rows = [3, 4, 7, 9]
        for answers in ((), (4,), (4, 9), (4, 4), (8,)):
            with self.subTest(answers=answers):
                unique, weights = runner._folded_rows(rows, answers, WEIGHT)
                self.assertEqual(unique, rows)
                self.assertEqual(sum(weights), len(runner._weighted_rows(rows, answers, WEIGHT)))


# Each bad selection violates exactly ONE device clause. A device assert poisons the CUDA context, so every case
# runs in its own process.
_CUDA_CASE = r"""
import os, sys
import torch
import torch.nn.functional as F
sys.path.insert(0, sys.argv[1])
from ember.model import ember_v0_streamed_loss as m
case = sys.argv[2]
dev = torch.device('cuda')
h = torch.randn(22, 5, device=dev, requires_grad=True)
c = torch.randn(11, 5, device=dev, requires_grad=True)
y = torch.zeros(22, dtype=torch.long, device=dev)
rows, w, count = [0, 2, 4, 5], [1.0, 7.0, 1.0, 7.0], 16
if case == 'count': count = 15
if case == 'weight': w = [1.0, 7.0, 0.5, 7.5]
if case == 'ascending': rows = [0, 2, 2, 5]
if case == 'outside': rows = [0, 2, 4, 6]
entry = (torch.tensor(rows, device=dev), torch.tensor(w, device=dev), count)
def dense(e, cc, t, ww=None):
    nll = F.cross_entropy(e @ cc.T, t, reduction='sum' if ww is None else 'none')
    return nll if ww is None else (nll * ww).sum()
loss = m.weighted_document_streamed_loss(h, c, y, (6, 5, 7, 4), 32, operator=dense, selections=(entry, None, None, None))
loss.backward()
torch.cuda.synchronize()
print('EXECUTED', m.executed_values(loss.cce_executed))
"""


@unittest.skipUnless(torch.cuda.is_available(), 'needs a CUDA device')
class WeightedDocumentLossDeviceClauses(unittest.TestCase):
    def run_case(self, case, blocking):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env.pop('CUDA_LAUNCH_BLOCKING', None)
        if blocking:
            env['CUDA_LAUNCH_BLOCKING'] = '1'
        return subprocess.run([sys.executable, '-B', '-c', _CUDA_CASE, str(ROOT / 'src'), case], env=env,
                              capture_output=True, text=True, timeout=180)

    def test_each_device_clause_fires_and_names_itself_under_launch_blocking(self):
        for case, message in (('count', 'count differs from its weight total'),
                              ('weight', 'weight is below one'),
                              ('ascending', 'rows are not unique and ascending'),
                              ('outside', 'row is outside its document')):
            with self.subTest(case):
                result = self.run_case(case, blocking=True)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('EXECUTED', result.stdout)
                self.assertIn('device assertion failed: Weighted selection ' + message, result.stderr)

    def test_device_clause_fires_asynchronously_without_launch_blocking(self):
        result = self.run_case('count', blocking=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('EXECUTED', result.stdout)
        self.assertIn('device-side assert triggered', result.stderr)

    def test_valid_selection_reports_the_device_reduced_weight_total(self):
        result = self.run_case('good', blocking=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EXECUTED {'cce_calls': 1, 'cce_rows': 20, 'cce_weight_total': 32}", result.stdout)


if __name__ == '__main__':
    unittest.main()
