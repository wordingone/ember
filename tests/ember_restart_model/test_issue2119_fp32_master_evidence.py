# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU reds for the fp32 master hour evidence (#2119, lead rulings 82495 / 82501): the trace, the changed fraction, the dtypes and the
refusal when an hour declares fp32_master_v1 and the evidence says otherwise. No GPU, tiny tensors."""
from pathlib import Path
import copy
import math
import sys
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import cia_fp32_evidence as E  # noqa: E402
import cia_fp32_master as M  # noqa: E402

ZERO = torch.zeros(())
NAMES = ('embedding.weight', 'layers.0.attention.q.weight', 'layers.0.shared.up.weight', 'experts.0.layers.1.up.weight', 'norm.weight')


def build(master, lr=1e-3, n=256):
    g = torch.Generator().manual_seed(3)
    inventory = {name: torch.nn.Parameter((torch.randn(n, generator=g) * 0.05).to(torch.bfloat16)) for name in NAMES}
    optimizer = torch.optim.AdamW(list(inventory.values()), lr=lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False,
                                  fused=True)
    if master:
        M.enable(optimizer)
    return inventory, optimizer


def step(optimizer, inventory, round_, master):
    gen = torch.Generator().manual_seed(100 + round_)
    for p in inventory.values():
        p.grad = (torch.randn(p.shape, generator=gen) * 0.1).to(torch.bfloat16)
    if master:
        for group in optimizer.param_groups:
            M.step(optimizer, group, [x for x in group['params'] if x.grad is not None], ZERO)
    else:
        optimizer.step()


def run(master, rounds=6):
    inventory, optimizer = build(master)
    step(optimizer, inventory, 99, master)       # a restored parent already carries state: the start row is read after it
    evidence = E.Evidence(optimizer, inventory, every=2, track=lambda n, p: True)
    evidence.observe(0)
    for r in range(rounds):
        step(optimizer, inventory, r, master)
        if evidence.due(r + 1):
            evidence.observe(r + 1)
    return evidence.finish(rounds, schema=E.V3 if master else 'ember-cia-placed-optimizer-state-v2')


class Groups(unittest.TestCase):
    def test_owner_groups(self):
        self.assertEqual([E.owner_group(n) for n in NAMES], ['embedding', 'attention', 'shared', 'experts', 'other'])


class Trace(unittest.TestCase):
    def test_master_hour_shows_residual_and_every_group_in_every_row(self):
        evidence = run(True)
        self.assertEqual([row['update'] for row in evidence['trace']], [0, 2, 4, 6, 6])
        for row in evidence['trace']:
            self.assertEqual(set(row['groups']), set(E.GROUPS))
            for group in row['groups'].values():
                self.assertGreater(group['mean_abs_update_over_lr'], 0)
                self.assertGreater(group['median_sqrt_v_ratio'], 0)
        self.assertGreater(evidence['trace'][-1]['groups']['embedding']['master_residual_fraction'], 0)
        self.assertEqual(evidence['dtypes'], {'master': ['torch.float32'], 'exp_avg': ['torch.float32'],
                                              'exp_avg_sq': ['torch.float32'], 'working': ['torch.bfloat16']})
        self.assertEqual(evidence['master_owner_count'], len(NAMES))
        self.assertGreater(evidence['changed']['all']['changed_fraction'], 0)

    def test_a_native_hour_has_no_masters_and_no_residual(self):
        evidence = run(False)
        self.assertEqual(evidence['master_owner_count'], 0)
        for row in evidence['trace']:
            for group in row['groups'].values():
                self.assertEqual(group['master_residual_fraction'], 0)

    def test_first_observation_is_the_denominator_of_the_v_ratio(self):
        inventory, optimizer = build(True)
        step(optimizer, inventory, 99, True)
        evidence = E.Evidence(optimizer, inventory, every=1, track=lambda n, p: True)
        first = evidence.observe(0)
        self.assertTrue(all(abs(g['median_sqrt_v_ratio'] - 1.0) < 1e-6 for g in first['groups'].values()))
        for r in range(40):
            step(optimizer, inventory, r, True)
        later = evidence.observe(40)
        self.assertTrue(all(g['median_sqrt_v_ratio'] != 1.0 for g in later['groups'].values()))


class SchemaReadBack(unittest.TestCase):
    def test_the_schema_is_read_from_the_written_optimizer_file_without_loading_its_tensors(self):
        import tempfile
        inventory, optimizer = build(True)
        step(optimizer, inventory, 99, True)
        evidence = E.Evidence(optimizer, inventory, every=2, track=lambda n, p: True)
        evidence.observe(0)
        step(optimizer, inventory, 0, True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'optimizer-state.pt'
            torch.save({'schema_version': E.V3, 'identity': {}, 'placement': {}, 'master_weights': {'a': torch.zeros(4)}, 'state': {}}, path)
            block = evidence.finish(1, child_optimizer_state_path=path)
        self.assertEqual(block['optimizer_schema'], E.V3)
        self.assertIsNone(E.require(None, declared=False))

    def test_a_written_v2_file_is_what_the_refusal_reports(self):
        import tempfile
        inventory, optimizer = build(True)
        step(optimizer, inventory, 99, True)
        evidence = E.Evidence(optimizer, inventory, every=2, track=lambda n, p: True)
        evidence.observe(0)
        step(optimizer, inventory, 0, True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'optimizer-state.pt'
            torch.save({'schema_version': 'ember-cia-placed-optimizer-state-v2', 'identity': {}, 'placement': {}, 'master_weights': None,
                        'state': {}}, path)
            block = evidence.finish(1, child_optimizer_state_path=path)
        with self.assertRaisesRegex(ValueError, 'v2'):
            E.require(block, declared=True)


class Refusals(unittest.TestCase):
    def setUp(self):
        self.good = run(True)

    def test_a_complete_master_hour_passes(self):
        self.assertIs(E.require(self.good, declared=True), self.good)

    def test_undeclared_hours_are_never_refused(self):
        self.assertIsNone(E.require(None, declared=False))

    def test_declared_without_evidence_refuses(self):
        for bad in (None, {}, {'schema': 'other'}):
            with self.assertRaises(ValueError):
                E.require(bad, declared=True)

    def test_an_empty_start_row_refuses(self):
        bad = copy.deepcopy(self.good)
        bad['trace'][0]['groups'] = {}
        with self.assertRaisesRegex(ValueError, 'empty start or end row'):
            E.require(bad, declared=True)

    def test_declared_but_v2_refuses(self):
        bad = copy.deepcopy(self.good)
        bad['optimizer_schema'] = 'ember-cia-placed-optimizer-state-v2'
        with self.assertRaisesRegex(ValueError, 'v2'):
            E.require(bad, declared=True)

    def test_declared_but_native_run_refuses(self):
        with self.assertRaises(ValueError):
            E.require(run(False), declared=True)

    def test_wrong_dtype_missing_row_or_no_residual_or_no_change_refuses(self):
        for mutate in (lambda e: e['dtypes'].update(exp_avg_sq=['torch.bfloat16']),
                       lambda e: e.update(trace=e['trace'][:1]),
                       lambda e: [g.update(master_residual_fraction=0.0) for g in e['trace'][-1]['groups'].values()],
                       lambda e: e['changed']['all'].update(changed_elements=0)):
            bad = copy.deepcopy(self.good)
            mutate(bad)
            with self.assertRaises(ValueError):
                E.require(bad, declared=True)


class SubHalfUlp(unittest.TestCase):
    def test_the_master_flips_a_weight_the_native_update_never_moves(self):
        """One weight at 1.0 with a positive gradient moves DOWN; below 1.0 the bf16 spacing is 2^-8, so a step must reach half of it, 2^-9
        = 0.00195, to change the weight. Every Adam step is ~lr = 1e-4, so the native in-place update never moves it (each step rounds
        back to 1.0) while the fp32 master accumulates them and flips the working weight at step ceil(2^-9 / lr) = 20, by arithmetic."""
        lr = 1e-4
        results = {}
        for master in (False, True):
            p = torch.nn.Parameter(torch.ones(1, dtype=torch.bfloat16))
            opt = torch.optim.AdamW([p], lr=lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0, foreach=False, fused=True)
            if master:
                M.enable(opt)
            flipped = None
            for k in range(1, 200):
                p.grad = torch.ones(1, dtype=torch.bfloat16)
                if master:
                    M.step(opt, opt.param_groups[0], [p], ZERO)
                else:
                    opt.step()
                if flipped is None and float(p.detach()) != 1.0:
                    flipped = k
            results[master] = flipped
        self.assertIsNone(results[False], 'native bf16 moved a weight by less than half a spacing')
        self.assertIsNotNone(results[True])
        self.assertEqual(results[True], math.ceil(2 ** -9 / lr))


if __name__ == '__main__':
    unittest.main()
