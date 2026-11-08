"""CPU reds for the declared hour learning rate (#2119 H43); no training claim."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import torch

SOURCE = Path(__file__).resolve().parents[2] / 'src/ember/infrastructure/tools/ember-restart-3b/cia_hour.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(SOURCE.with_name('cia_step_runner.py'), 'tested_lr_runner')
subject = load(SOURCE, 'tested_lr_hour')


def hour(**extra):
    return dict(schema='governed-hour-v1', arm='control', minimum_wall_seconds=3600, minimum_measured_steps=1024, **extra)


class FakeRunner:
    def __init__(self):
        self.written = {}

    def _write_new(self, path, value):
        if path in self.written:
            raise AssertionError('written twice')
        self.written[path] = value


def parent_at(lr, groups=1):
    return dict(optimizer_identity=dict(param_groups=[dict(params=['p%d' % i], hyperparameters=dict(lr=lr))
                                                      for i in range(groups)]))


def world(lr):
    params = [torch.nn.Parameter(torch.ones(4)), torch.nn.Parameter(torch.ones(3))]
    optimizer = torch.optim.AdamW([{'params': [params[0]]}, {'params': [params[1]]}], lr=lr, foreach=False)
    return params, optimizer


class DeclaredLrTests(unittest.TestCase):
    def test_hour_mode_admits_declared_lr_and_expected_optimizer_carries_it(self):
        identity = dict(hour=hour(declared_lr=3e-4))
        self.assertTrue(runner.hour_mode(identity))
        self.assertEqual(runner.expected_optimizer(identity)['lr'], 3e-4)
        self.assertEqual(runner.expected_optimizer(dict(hour=hour()))['lr'], 0.001)

    def test_declared_lr_type_range_and_schema_refuse(self):
        for bad in (3, 0.0, 1e-2, float('nan'), '3e-4'):
            with self.assertRaisesRegex(ValueError, 'declared_lr'):
                runner.hour_mode(dict(hour=hour(declared_lr=bad)))
        with self.assertRaises(ValueError):
            runner.hour_mode(dict(hour=dict(schema='learning-comparison-v1', arm='control', minimum_wall_seconds=0,
                                            minimum_measured_steps=16383, declared_lr=3e-4)))

    def test_undeclared_lr_change_refuses_before_any_load(self):
        _, optimizer = world(3e-4)
        loads = []
        with self.assertRaisesRegex(ValueError, 'without a declared_lr'):
            subject.restore_at_parent_lr(optimizer, parent_at(0.001), dict(lr=3e-4), hour(), Path('c'), FakeRunner(),
                                         lambda: loads.append(1))
        self.assertEqual(loads, [])
        self.assertTrue(all(group['lr'] == 3e-4 for group in optimizer.param_groups))

    def test_declared_lr_restores_at_parent_lr_then_applies_declared(self):
        params, optimizer = world(3e-4)
        source_params, source = world(0.001)
        for p in source_params:
            p.grad = torch.full_like(p, 0.5)
        source.step()
        saved = source.state_dict()
        seen = []

        def load():
            seen.append([optimizer.defaults['lr']] + [group['lr'] for group in optimizer.param_groups])
            optimizer.load_state_dict(saved)
            return {'data_cursor': 'c'}

        fake = FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            out = subject.restore_at_parent_lr(optimizer, parent_at(0.001, 2), dict(lr=3e-4), hour(declared_lr=3e-4),
                                               Path(tmp), fake, load)
        self.assertEqual(out, {'data_cursor': 'c'})
        self.assertEqual(seen, [[0.001, 0.001, 0.001]])  # restore compared like with like
        self.assertTrue(all(group['lr'] == 3e-4 for group in optimizer.param_groups))
        self.assertEqual(optimizer.defaults['lr'], 3e-4)
        receipt = next(iter(fake.written.values()))
        self.assertEqual((receipt['parent_lr'], receipt['declared_lr'], receipt['groups']), (0.001, 3e-4, 2))
        # moment tensors are the loaded ones, bit for bit
        for mine, theirs in zip(params, source_params):
            for key in ('exp_avg', 'exp_avg_sq'):
                self.assertTrue(torch.equal(optimizer.state[mine][key], source.state[theirs][key]))

    def test_same_lr_is_a_plain_restore_with_no_receipt(self):
        _, optimizer = world(3e-4)
        fake = FakeRunner()
        self.assertEqual(subject.restore_at_parent_lr(optimizer, parent_at(3e-4), dict(lr=3e-4), hour(declared_lr=3e-4),
                                                      Path('c'), fake, lambda: 'r'), 'r')
        self.assertEqual(fake.written, {})

    def test_parent_with_mixed_group_lrs_refuses(self):
        parent = dict(optimizer_identity=dict(param_groups=[dict(params=['a'], hyperparameters=dict(lr=0.001)),
                                                            dict(params=['b'], hyperparameters=dict(lr=3e-4))]))
        with self.assertRaisesRegex(ValueError, 'one learning rate'):
            subject.parent_learning_rate(parent)


if __name__ == '__main__':
    unittest.main()
