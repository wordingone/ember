# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""staged_inputs and loss_selection apply ONE whole-document predicate (#2410).

A document is whole only when its loss-bearing rows, after answer weighting, are exactly range(lo, hi). The
count-only test it replaces called a partly loss-bearing document whole whenever k + (weight - 1) * a == hi - lo,
so the consumer trained its IGNORE_TARGET rows (clamped to target 0). The deliberate red is a named mutation that
restores the count-only predicate in a copy of staged_inputs and is asserted to fail the same checks.
"""
import importlib.util
import inspect
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SUBJECT_PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('bound_checkout_cia_step_runner_2410', SUBJECT_PATH)
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
assert Path(subject.__file__).resolve(strict=True) == SUBJECT_PATH.resolve(strict=True)

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from ember.model.ember_v0_streamed_loss import document_streamed_loss  # noqa: E402

IGNORE = subject.IGNORE_TARGET
CPU = torch.device('cpu')
FIXED_PREDICATE = 'if rows.shape[0] == hi - lo and numpy.array_equal(rows, numpy.arange(lo, hi)):'
COUNT_ONLY_PREDICATE = 'if rows.shape[0] == hi - lo:'

# weight, documents (length, ignored offsets, answer offsets). Document 0 meets k + (weight - 1) * a == L with at
# least one ignored row, the case the count-only predicate called whole; document 1 is whole by any predicate.
DISAGREEMENT_CASES = {
    'production-weight-200': (200, [(200, set(range(200)) - {7}, (7,)), (5, set(), ())]),
    'small-weight-3': (3, [(6, {1, 4}, (2,)), (4, set(), ())]),
}
# packs on which both predicates already agreed: the fix must leave every output byte of these unchanged.
AGREEING_CASES = (
    (3, [(5, set(), ()), (4, {3}, (1,))]),
    (3, [(4, set(), (1,)), (3, {0}, ())]),
    (200, [(6, {0, 2}, (3,)), (2, set(), ())]),
)


def count_only_staged_inputs():
    """MUTATION count-only-whole-document: staged_inputs with the pre-#2410 predicate, built from its own source."""
    source = inspect.getsource(subject.staged_inputs)
    if source.count(FIXED_PREDICATE) != 1:
        raise AssertionError('the fixed predicate is not present exactly once; the mutation would be vacuous')
    namespace = dict(vars(subject))
    exec(compile(source.replace(FIXED_PREDICATE, COUNT_ONLY_PREDICATE), '<count-only-staged-inputs>', 'exec'),
         namespace)
    return namespace['staged_inputs']


def micro_batch(documents):
    targets, answers, starts = [], [], []
    for length, ignored, answer in documents:
        lo = len(targets)
        starts.append(lo)
        targets.extend(IGNORE if offset in ignored else (lo + offset) % 7 for offset in range(length))
        answers.extend(lo + offset for offset in answer)
    n = len(targets)
    return {'token_ids': [(i * 3) % 7 for i in range(n)], 'target_ids': targets, 'positions': list(range(n)),
            'document_starts': starts, 'answer_rows': tuple(answers)}


def normal(selection):
    return {'denominator': selection['denominator'],
            'selections': [None if entry is None else (entry[0].tolist(), entry[1])
                           for entry in selection['selections']]}


def run(staged_inputs, weight, micro):
    with patch.dict(os.environ, {'EMBER_ANSWER_WEIGHT': str(weight)}):
        return staged_inputs(micro, CPU), subject.loss_selection(micro, CPU)


def hidden_gradient(micro, selection):
    torch.manual_seed(0)
    n = len(micro['target_ids'])
    hidden = torch.randn(n, 4, requires_grad=True)
    classifier = torch.randn(7, 4)
    targets = torch.tensor(micro['target_ids'], dtype=torch.int64).clamp(min=0)  # as measure_step clamps them
    starts = list(micro['document_starts']) + [n]
    lengths = tuple(hi - lo for lo, hi in zip(starts, starts[1:]))
    loss = document_streamed_loss(hidden, classifier, targets, lengths, selection['denominator'],
                                  operator=lambda e, c, y: F.cross_entropy(e @ c.T, y, reduction='sum'),
                                  selections=selection['selections'])
    loss.backward()
    return hidden.grad


def disagreements(staged_inputs):
    """Every way staged_inputs departs from loss_selection, or trains an ignored row, on the disagreement cases."""
    found = []
    for name, (weight, documents) in DISAGREEMENT_CASES.items():
        micro = micro_batch(documents)
        (tokens, targets, positions, staged), expected = run(staged_inputs, weight, micro)
        if [tokens.tolist(), targets.tolist(), positions.tolist()] != [
                micro['token_ids'], micro['target_ids'], micro['positions']]:
            found.append((name, 'staged pack bytes'))
        if staged['selections'][0] is None:
            found.append((name, 'count-match document staged whole'))
        if normal(staged) != normal(expected):
            found.append((name, 'selection differs from loss_selection'))
        gradient = hidden_gradient(micro, staged)
        rows = sorted(documents[0][1])
        if not torch.equal(gradient[rows], torch.zeros_like(gradient[rows])):
            found.append((name, 'ignored rows receive hidden gradient'))
        if not torch.equal(gradient, hidden_gradient(micro, expected)):
            found.append((name, 'hidden gradient differs from loss_selection'))
    return found


class WholeDocumentPredicateTests(unittest.TestCase):
    def test_disagreement_cases_are_well_formed(self):
        for weight, documents in DISAGREEMENT_CASES.values():
            length, ignored, answer = documents[0]
            self.assertTrue(ignored)
            self.assertEqual((length - len(ignored)) + (weight - 1) * len(answer), length)

    def test_count_match_document_is_an_explicit_selection_equal_to_loss_selection(self):
        self.assertEqual(disagreements(subject.staged_inputs), [])

    def test_exact_range_document_stays_whole_in_both(self):
        micro = micro_batch([(5, set(), ()), (4, {3}, (1,))])
        (*_, staged), expected = run(subject.staged_inputs, 3, micro)
        self.assertIsNone(staged['selections'][0])
        self.assertIsNone(expected['selections'][0])
        self.assertEqual(normal(staged), normal(expected))

    def test_whole_document_with_answer_repeat_is_explicit_in_both(self):
        micro = micro_batch([(4, set(), (1,)), (3, {0}, ())])
        (*_, staged), expected = run(subject.staged_inputs, 3, micro)
        self.assertEqual(normal(staged), normal(expected))
        self.assertEqual(staged['selections'][0][1], 6)
        self.assertEqual(staged['denominator'], 6 + 2)

    def test_agreeing_packs_are_byte_identical_to_the_count_only_predicate(self):
        mutant = count_only_staged_inputs()
        for weight, documents in AGREEING_CASES:
            with self.subTest(weight=weight, documents=documents):
                micro = micro_batch(documents)
                fixed, expected = run(subject.staged_inputs, weight, micro)
                old, _ = run(mutant, weight, micro)
                for new_tensor, old_tensor in zip(fixed[:3], old[:3]):
                    self.assertTrue(torch.equal(new_tensor, old_tensor))
                self.assertEqual(normal(fixed[3]), normal(old[3]))
                self.assertEqual(normal(fixed[3]), normal(expected))

    def test_deliberate_red_count_only_mutation_is_refused(self):
        found = {(name, what) for name, what in disagreements(count_only_staged_inputs())}
        for name in DISAGREEMENT_CASES:
            self.assertIn((name, 'count-match document staged whole'), found)
            self.assertIn((name, 'selection differs from loss_selection'), found)
            self.assertIn((name, 'ignored rows receive hidden gradient'), found)


if __name__ == '__main__':
    unittest.main()
