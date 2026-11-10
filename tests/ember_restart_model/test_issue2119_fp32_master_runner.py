# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU reds for the fp32 master treatment wiring (#2119): hour declaration, optimizer switch, byte caps, gated step."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

import torch

TOOLS = Path(__file__).resolve().parents[2] / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(TOOLS / 'cia_step_runner.py', 'tested_fp32_runner')
hour_module = load(TOOLS / 'cia_hour.py', 'tested_fp32_hour')
import cia_fp32_master as M  # noqa: E402


def hour(schema='governed-hour-v1', **extra):
    shape = {'governed-hour-v1': (3600, 1024), 'checkpoint-probe-v1': (0, 2), 'learning-comparison-v1': (0, 16383)}[schema]
    return dict(schema=schema, arm='control', minimum_wall_seconds=shape[0], minimum_measured_steps=shape[1], **extra)


def fused(params, lr=1e-4):
    return torch.optim.AdamW(params, lr=lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True)


class Declaration(unittest.TestCase):
    def test_hour_mode_admits_the_fp32_master_declaration_and_the_optimizer_identity_stays_equal(self):
        for schema in ('governed-hour-v1', 'checkpoint-probe-v1'):
            identity = dict(hour=hour(schema, precision_fix='fp32_master_v1'))
            self.assertTrue(runner.hour_mode(identity), schema)
        both = dict(hour=hour(declared_lr=1e-4, precision_fix='fp32_master_v1'))
        self.assertTrue(runner.hour_mode(both))
        self.assertEqual(runner.expected_optimizer(dict(hour=hour(precision_fix='fp32_master_v1'))),
                         runner.expected_optimizer(dict(hour=hour())))

    def test_other_values_and_schemas_refuse(self):
        for bad in ('fp32', '', None, True, 'fp32_master_v2'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                runner.hour_mode(dict(hour=hour(precision_fix=bad)))
        with self.assertRaises(ValueError):
            runner.hour_mode(dict(hour=hour('learning-comparison-v1', precision_fix='fp32_master_v1')))


class Switch(unittest.TestCase):
    def test_apply_precision_fix_enables_only_the_declared_treatment(self):
        p = torch.nn.Parameter(torch.zeros(4, dtype=torch.bfloat16))
        declared = runner.apply_precision_fix(fused([p]), dict(hour=hour(precision_fix='fp32_master_v1')))
        self.assertTrue(M.enabled(declared))
        for identity in (dict(hour=hour()), dict(), dict(hour=None)):
            self.assertFalse(M.enabled(runner.apply_precision_fix(fused([torch.nn.Parameter(torch.zeros(4, dtype=torch.bfloat16))]), identity)))

    def test_the_declared_treatment_refuses_an_unsupported_optimizer(self):
        plain = torch.optim.AdamW([torch.nn.Parameter(torch.zeros(4, dtype=torch.bfloat16))], foreach=False)
        with self.assertRaises(ValueError):
            runner.apply_precision_fix(plain, dict(hour=hour(precision_fix='fp32_master_v1')))

    def test_byte_cap_is_16_gib_for_the_master_treatment_and_10_otherwise(self):
        p = torch.nn.Parameter(torch.zeros(4, dtype=torch.bfloat16))
        native, master = fused([p]), M.enable(fused([torch.nn.Parameter(torch.zeros(4, dtype=torch.bfloat16))]))
        self.assertEqual(hour_module.checkpoint_cap(runner, native), 10 * runner.GIB)
        self.assertEqual(hour_module.checkpoint_cap(runner, master), 16 * runner.GIB)


class GatedStep(unittest.TestCase):
    def test_gated_step_runs_the_master_path_and_a_skipped_owner_stays_untouched(self):
        g = torch.Generator().manual_seed(7)
        dense = torch.nn.Parameter((torch.randn(64, generator=g) * .05).to(torch.bfloat16))
        hit = torch.nn.Parameter((torch.randn(64, generator=g) * .05).to(torch.bfloat16))
        miss = torch.nn.Parameter((torch.randn(64, generator=g) * .05).to(torch.bfloat16))
        optimizer = M.enable(fused([dense, hit, miss]))
        owners = {(0, 3): [hit], (0, 5): [miss]}
        buffers = types.SimpleNamespace(device=torch.device('cpu'), views={'winners': torch.tensor([[3, 7]])})
        start = {name: p.detach().clone() for name, p in (('dense', dense), ('hit', hit), ('miss', miss))}
        reference = [torch.nn.Parameter(start[name].float()) for name in ('dense', 'hit')]
        ref = fused(reference)
        for step in range(3):
            for p in (dense, hit, miss):
                p.grad = (torch.randn(p.shape, generator=g) * .1).to(torch.bfloat16)
            for r, p in zip(reference, (dense, hit)): r.grad = p.grad.float().clone()
            ref.step()
            keys, skip = runner.gated_optimizer_step(optimizer, owners, buffers, torch.tensor(False))
            self.assertEqual(keys, ((0, 3), (0, 5)))
            self.assertEqual(skip.tolist(), [0.0, 1.0])
        table = M.masters(optimizer)
        self.assertTrue(torch.equal(table[id(dense)], reference[0].detach()))
        self.assertTrue(torch.equal(table[id(hit)], reference[1].detach()))
        self.assertTrue(torch.equal(dense.detach(), reference[0].detach().to(torch.bfloat16)))
        self.assertTrue(torch.equal(hit.detach(), reference[1].detach().to(torch.bfloat16)))
        self.assertTrue(torch.equal(miss.detach(), start['miss']))
        self.assertTrue(torch.equal(table[id(miss)], start['miss'].float()))
        self.assertEqual(optimizer.state[miss]['step'].item(), 0)
        self.assertFalse(bool(optimizer.state[miss]['exp_avg'].any()) or bool(optimizer.state[miss]['exp_avg_sq'].any()))
        self.assertEqual(M.check_invariant(optimizer), [])

    def test_a_refused_update_leaves_every_owner_untouched(self):
        g = torch.Generator().manual_seed(9)
        p = torch.nn.Parameter((torch.randn(32, generator=g) * .05).to(torch.bfloat16))
        optimizer = M.enable(fused([p]))
        buffers = types.SimpleNamespace(device=torch.device('cpu'), views={'winners': torch.tensor([[1]])})
        before = p.detach().clone()
        p.grad = (torch.randn(32, generator=g) * .1).to(torch.bfloat16)
        runner.gated_optimizer_step(optimizer, {}, buffers, torch.tensor(True))
        self.assertTrue(torch.equal(p.detach(), before))
        self.assertTrue(torch.equal(M.masters(optimizer)[id(p)], before.float()))
        self.assertEqual(optimizer.state[p]['step'].item(), 0)


if __name__ == '__main__':
    unittest.main()
