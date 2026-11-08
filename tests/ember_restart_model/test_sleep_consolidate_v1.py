# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""SLEEP-1 CPU reds on a tiny random model (#2119): zero experts are bit-identical, only A/B train, the teacher stays
frozen, and every sample is ledgered as self-generated."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parents[2] / 'src/ember/infrastructure/tools/ember-restart-3b'
_spec = importlib.util.spec_from_file_location('sleep_consolidate_v1', HERE / 'sleep_consolidate_v1.py')
sc = importlib.util.module_from_spec(_spec)
sys.modules['sleep_consolidate_v1'] = sc
_spec.loader.exec_module(sc)

V, D, H = 11, 8, 16


def tiny(seed):
    g = torch.Generator().manual_seed(seed)
    return {'emb': torch.randn(V, D, generator=g), 'up': torch.randn(H, D, generator=g) * 0.3,
            'down': torch.randn(D, H, generator=g) * 0.3, 'head': torch.randn(V, D, generator=g)}


def logits_fn(params):
    def f(tokens):
        x = params['emb'][torch.tensor(tokens)].cumsum(0) / torch.arange(1, len(tokens) + 1)[:, None]
        return (x + torch.relu(x @ params['up'].t()) @ params['down'].t()) @ params['head'].t()
    return f


class SleepReds(unittest.TestCase):
    def setUp(self):
        self.teacher = tiny(1)
        self.student = {k: v.clone() for k, v in self.teacher.items()}
        with torch.no_grad():
            self.student['up'] += 0.05
        sc.freeze_except(self.teacher, ())
        sc.freeze_except(self.student, {'up', 'down'})
        self.experts = [sc.LowRankExpert(n, self.student[n], rank=2, seed=i) for i, n in enumerate(('up', 'down'))]
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = sc.Ledger(Path(self.tmp.name) / 'l.jsonl', dict(teacher='t' * 64, student='s' * 64))
        self.prefixes = [[1, 2, 3], [4, 5], [6, 7, 8, 9]]

    def tearDown(self):
        self.tmp.cleanup()

    def steps(self, n=3):
        opt = sc.make_optimizer(self.experts, lr=1e-2)
        for s in range(n):
            sc.consolidation_step(logits_fn(self.student), logits_fn(self.teacher), self.experts, opt, self.prefixes,
                                  cont_len=4, seed=s, ledger=self.ledger)

    def test_zero_experts_are_bit_identical(self):
        before = logits_fn(self.student)([1, 2, 3, 4])
        for e in self.experts:
            e.write()
        self.assertTrue(torch.equal(before, logits_fn(self.student)([1, 2, 3, 4])))

    def test_only_a_b_train(self):
        frozen = {k: self.student[k].clone() for k in ('emb', 'head')}
        self.steps()
        for k, v in frozen.items():
            self.assertTrue(torch.equal(v, self.student[k]), k)
            self.assertIsNone(self.student[k].grad, k)
        moved = False
        for e in self.experts:
            self.assertIsNone(e.weight.grad)
            self.assertTrue(torch.equal(e.weight, (e.w0 + e.b @ e.a).to(e.weight.dtype)), e.name)
            moved |= bool(e.b.abs().sum() > 0)
        self.assertTrue(moved, 'no expert moved: A/B received no gradient')

    def test_teacher_frozen(self):
        before = {k: v.clone() for k, v in self.teacher.items()}
        self.steps()
        for k, v in before.items():
            self.assertTrue(torch.equal(v, self.teacher[k]), k)
            self.assertIsNone(self.teacher[k].grad, k)

    def test_samples_ledgered_self_generated(self):
        self.steps(2)
        rows = [json.loads(l) for l in (Path(self.tmp.name) / 'l.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 2 * len(self.prefixes) * 3)
        self.assertEqual(self.ledger.rows, len(rows))
        for r in rows:
            self.assertEqual(r['provenance'], 'ember-self-dream')
            self.assertEqual(r['generator_checkpoint_sha256'], ('t' if r['role'] == 'teacher' else 's') * 64)
            self.assertTrue(r['tokens'])


if __name__ == '__main__':
    unittest.main()
