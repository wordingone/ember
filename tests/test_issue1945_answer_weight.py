# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""EMBER_ANSWER_WEIGHT repeats each answer-letter row in its document's loss selection and counts the repeats in the
denominator. Unset, every selection and denominator is the prior one. The loss must ACCUMULATE a repeated row's
gradient; a copy keeps one repeat's share and silently drops the weight."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(ROOT / 'src'))
from ember.model.ember_v0_streamed_loss import document_streamed_loss  # noqa: E402


def load(name, file):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summed_nll(hidden, classifier, targets):
    return torch.nn.functional.cross_entropy(hidden @ classifier.T, targets, reduction='sum')


I = -100


def micro():
    # doc 0: text, every target loss-bearing (rows 0-3); doc 1: image-text, rows 4-11 with answer row 9.
    targets = [1, 2, 3, 4, I, I, 5, 6, I, 7, 8, I]
    return {'token_ids': [0] * 12, 'target_ids': targets, 'positions': [[p, 0, 0] for p in range(12)],
            'document_starts': [0, 4], 'answer_rows': [9]}


class AnswerWeight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load('cia_step_runner_answer_weight', 'cia_step_runner.py')
        cls.stream = load('image_text_stream_answer_weight', 'image_text_stream.py')

    def tearDown(self):
        os.environ.pop('EMBER_ANSWER_WEIGHT', None)

    def selection(self):
        _, _, _, staged = self.runner.staged_inputs(micro(), torch.device('cpu'))
        eager = self.runner.loss_selection(micro(), torch.device('cpu'))
        return staged, eager

    def test_unset_is_the_prior_selection(self):
        staged, eager = self.selection()
        for sel in (staged, eager):
            self.assertEqual(sel['denominator'], 8)
            self.assertIsNone(sel['selections'][0])
            self.assertEqual(sel['selections'][1][0].tolist(), [6, 7, 9, 10])

    def test_weight_repeats_the_answer_row_and_counts_it(self):
        os.environ['EMBER_ANSWER_WEIGHT'] = '4'
        staged, eager = self.selection()
        for sel in (staged, eager):
            self.assertEqual(sel['denominator'], 11)
            self.assertIsNone(sel['selections'][0])
            self.assertEqual(sel['selections'][1][0].tolist(), [6, 7, 9, 10, 9, 9, 9])
            self.assertEqual(sel['selections'][1][1], 7)

    def test_weight_below_two_refuses(self):
        os.environ['EMBER_ANSWER_WEIGHT'] = '1'
        with self.assertRaises(ValueError):
            self.runner.answer_weight()

    def test_append_document_rebases_answer_rows(self):
        pack = {'document_starts': [0], 'token_ids': [0] * 5, 'target_ids': [0] * 5, 'positions': [[0, 0, 0]] * 5}
        document = {'token_ids': [0] * 3, 'target_ids': [0] * 3, 'positions': [[0, 0, 0]] * 3, 'images': [],
                    'answer_rows': [1]}
        self.stream.append_document(pack, document)
        self.assertEqual(pack['answer_rows'], [6])

    def test_repeated_rows_carry_the_weighted_gradient(self):
        torch.manual_seed(0)
        hidden = torch.randn(12, 8, dtype=torch.float64, requires_grad=True)
        classifier = torch.randn(16, 8, dtype=torch.float64, requires_grad=True)
        targets = torch.tensor([t if t != I else 0 for t in micro()['target_ids']])
        os.environ['EMBER_ANSWER_WEIGHT'] = '4'
        sel = self.runner.loss_selection(micro(), torch.device('cpu'))
        loss = document_streamed_loss(hidden, classifier, targets, (4, 8), sel['denominator'],
                                      operator=summed_nll, selections=sel['selections'])
        loss.backward()
        weights = torch.tensor([1, 1, 1, 1, 0, 0, 1, 1, 0, 4, 1, 0], dtype=torch.float64)
        h2 = hidden.detach().clone().requires_grad_(True)
        c2 = classifier.detach().clone().requires_grad_(True)
        per = torch.nn.functional.cross_entropy(h2 @ c2.T, targets, reduction='none')
        reference = (per * weights).sum() / weights.sum()
        reference.backward()
        self.assertTrue(torch.allclose(loss, reference))
        self.assertTrue(torch.allclose(hidden.grad, h2.grad))
        self.assertTrue(torch.allclose(classifier.grad, c2.grad))
        # The red: a copy into the answer row keeps one repeat's gradient, a quarter of the weighted one.
        copied = torch.zeros_like(h2.grad).index_copy_(0, torch.tensor([9, 9]), h2.grad[[9, 9]] / 4)
        self.assertFalse(torch.allclose(copied[9], h2.grad[9]))


if __name__ == '__main__':
    unittest.main()
