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


def scenario(stepping, idle, rounds=4, every=2):
    """`stepping` owners train; `idle` owners hold optimizer state at step 0 (a gated first step: zero moments, step 0, master made)."""
    g = torch.Generator().manual_seed(5)
    inventory = {name: torch.nn.Parameter((torch.randn(256, generator=g) * 0.05).to(torch.bfloat16)) for name in tuple(stepping) + tuple(idle)}
    optimizer = torch.optim.AdamW(list(inventory.values()), lr=1e-3, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True)
    M.enable(optimizer)
    live = {n: inventory[n] for n in stepping}
    step(optimizer, live, 99, True)
    for name in idle:
        M._ensure(optimizer, inventory[name])
    evidence = E.Evidence(optimizer, inventory, every=every, track=lambda n, p: True)
    evidence.observe(0)
    for r in range(rounds):
        step(optimizer, live, r, True)
        if evidence.due(r + 1):
            evidence.observe(r + 1)
    return evidence, inventory, optimizer


class StepZeroOwner(unittest.TestCase):
    """Lead review 82546 item 1: an owner at step 0 gave 0/0 = NaN in a mid-hour trace row; the strict-JSON write then raised AFTER
    hour-result.json was created (an empty result, and the resume path refuses)."""

    def test_a_step_zero_owner_is_skipped_and_every_row_is_strict_json(self):
        import json
        evidence, _, _ = scenario(NAMES, ('layers.9.shared.gate.weight',))
        block = evidence.finish(4, schema=E.V3)
        json.dumps(block, allow_nan=False)
        for row in block['trace']:
            self.assertEqual(row['owners_at_step_zero'], 1)
            self.assertEqual(row['groups']['shared']['owners'], 1)
        self.assertIs(E.require(block, declared=True), block)

    def test_the_old_nan_is_refused_by_require_whatever_wrote_it(self):
        evidence, _, _ = scenario(NAMES, ())
        block = evidence.finish(4, schema=E.V3)
        for bad_value in (float('nan'), float('inf'), None):
            bad = copy.deepcopy(block)
            bad['trace'][1]['groups']['experts']['mean_abs_update_over_lr'] = bad_value
            with self.assertRaisesRegex(ValueError, 'not a finite number'):
                E.require(bad, declared=True)

    def test_a_group_whose_only_owner_is_at_step_zero_is_missing_from_the_rows_and_refused(self):
        evidence, _, _ = scenario(NAMES[:-1], ('norm.weight',))
        block = evidence.finish(4, schema=E.V3)
        self.assertIn('other', block['expected_groups'])
        self.assertNotIn('other', block['trace'][0]['groups'])
        with self.assertRaisesRegex(ValueError, r"start row lacks owner group\(s\) \['other'\]"):
            E.require(block, declared=True)


class MasterPathSteppedFixes(unittest.TestCase):
    """Lead review 82546 items 2 and 3: the master path must be shown to have stepped, and the trace must be complete and finite."""

    def setUp(self):
        self.good = run(True)

    def refuses(self, mutate, pattern):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaisesRegex(ValueError, pattern):
            E.require(bad, declared=True)

    def test_the_good_block_carries_the_new_fields(self):
        self.assertEqual(self.good['invariant_violations'], 0)
        self.assertEqual(self.good['expected_groups'], sorted(E.GROUPS))
        self.assertTrue(all(g['master_moved_fraction'] == 0 for g in self.good['trace'][0]['groups'].values()))
        self.assertTrue(all(g['master_moved_fraction'] > 0 for g in self.good['trace'][-1]['groups'].values()))
        self.assertTrue(all(row['seconds'] >= 0 for row in self.good['trace']))

    def test_a_group_whose_step_did_not_advance_is_refused(self):
        def mutate(e):
            e['trace'][-1]['groups']['attention']['step_max'] = e['trace'][0]['groups']['attention']['step_max']
        self.refuses(mutate, 'group attention optimizer step did not advance')

    def test_no_sampled_master_moved_is_refused(self):
        def mutate(e):
            for g in e['trace'][-1]['groups'].values():
                g['master_moved_fraction'] = 0.0
        self.refuses(mutate, 'no sampled master that moved')

    def test_the_invariant_is_read_back_and_a_violation_or_a_missing_key_is_refused(self):
        self.refuses(lambda e: e.update(invariant_violations=3), 'read back 3')
        self.refuses(lambda e: e.pop('invariant_violations'), 'read back None')

    def test_a_working_weight_that_is_not_bf16_of_its_master_is_counted(self):
        inventory, optimizer = build(True)
        step(optimizer, inventory, 99, True)
        evidence = E.Evidence(optimizer, inventory, every=2, track=lambda n, p: True)
        evidence.observe(0)
        step(optimizer, inventory, 0, True)
        with torch.no_grad():
            inventory['norm.weight'].add_(1)
        block = evidence.finish(1, schema=E.V3)
        self.assertEqual(block['invariant_violations'], 1)
        with self.assertRaisesRegex(ValueError, 'invariant'):
            E.require(block, declared=True)

    def test_every_expected_group_must_be_in_the_first_and_last_row(self):
        self.refuses(lambda e: e['trace'][0]['groups'].pop('experts'), r"start row lacks owner group\(s\) \['experts'\]")
        self.refuses(lambda e: e['trace'][-1]['groups'].pop('experts'), r"end row lacks owner group\(s\) \['experts'\]")
        self.refuses(lambda e: e.update(expected_groups=[]), 'expected owner groups')
        self.refuses(lambda e: e.update(expected_groups=['nonsense']), 'expected owner groups')

    def test_both_step_size_keys_must_be_present_and_finite_in_every_row(self):
        for key in ('mean_abs_update_over_lr', 'median_sqrt_v_ratio', 'master_residual_fraction', 'master_moved_fraction', 'step_max'):
            self.refuses(lambda e, key=key: e['trace'][1]['groups']['experts'].pop(key), key + ' is None')
        self.refuses(lambda e: e['trace'][1]['groups']['experts'].update(median_sqrt_v_ratio=float('nan')), 'not a finite number')

    def test_a_non_finite_evidence_seconds_or_changed_fraction_is_refused(self):
        self.refuses(lambda e: e.update(evidence_seconds=float('inf')), 'evidence_seconds')
        self.refuses(lambda e: e['changed']['experts'].update(changed_fraction=None), 'changed fraction')


class ProbeInLoopSample(unittest.TestCase):
    """Lead review 82546 item 4: the one GPU probe must run the in-loop path, and the device index is uploaded once per (numel, device)."""

    def test_a_probe_samples_once_at_update_two_and_an_hour_does_not(self):
        inventory, optimizer = build(True)
        step(optimizer, inventory, 99, True)
        evidence = E.Evidence(optimizer, inventory, track=lambda n, p: True)       # the default every = 10,000
        self.assertEqual([u for u in range(1, 6) if evidence.due(u, probe=True)], [2])
        self.assertEqual([u for u in range(1, 6) if evidence.due(u)], [])
        self.assertTrue(evidence.due(10000) and evidence.due(10000, probe=True))

    def test_a_probe_block_needs_a_row_between_start_and_end(self):
        good = run(True)
        self.assertIs(E.require(good, declared=True, probe=True), good)
        two = copy.deepcopy(good)
        two['trace'] = [two['trace'][0], two['trace'][-1]]
        self.assertIs(E.require(two, declared=True), two)
        with self.assertRaisesRegex(ValueError, 'in-loop sample row'):
            E.require(two, declared=True, probe=True)

    def test_the_sample_index_is_built_once_per_size_and_uploaded_once_per_device(self):
        from unittest import mock
        inventory, optimizer = build(True)
        step(optimizer, inventory, 99, True)
        with mock.patch.object(E, '_positions', wraps=E._positions) as spy:
            evidence = E.Evidence(optimizer, inventory, every=2, track=lambda n, p: True)
            for u in range(3):
                evidence.observe(u)
            evidence.changed_fraction()
        self.assertEqual(spy.call_count, 1)                       # five owners of 256 elements: one index
        self.assertEqual(len(evidence._device_index), 1)
        self.assertEqual(len(evidence._cpu_index), 1)


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
