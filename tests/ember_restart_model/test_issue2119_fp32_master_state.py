# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp32 master checkpoint state (#2119): the counter's torch-free narrowing and lineage rules, and the v3 payload round trip.
CPU only, tiny tensors; no training claim."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path[:0] = [str(BASE), str(ROOT / 'src'), str(ROOT)]
import checkpoint_artifacts as artifacts  # noqa: E402
import cia_fp32_master as M  # noqa: E402
import parameter_counter as counter  # noqa: E402

ZERO = torch.zeros(())
V3 = 'ember-cia-placed-optimizer-state-v3'


def raw(tensor):
    return tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def finite_fp32(seed, n=20000):
    """Random fp32 bit patterns with a finite exponent, plus forced round-to-nearest-even ties."""
    g = torch.Generator().manual_seed(seed)
    bits = torch.randint(-2**31, 2**31, (n,), generator=g, dtype=torch.int64)
    exponent = (bits >> 23) & 0xFF
    bits = torch.where(exponent == 0xFF, bits & ~(1 << 23), bits)
    ties = bits[:2000] & ~0xFFFF | 0x8000
    bits = torch.cat([bits, ties, (bits[2000:4000] & ~0xFFFF) | 0x7FFF, (bits[2000:4000] & ~0xFFFF) | 0x8001])
    bits = torch.where(((bits >> 23) & 0xFF) == 0xFF, bits & ~(1 << 23), bits)
    return bits.to(torch.int32).view(torch.float32)


class CounterNarrowing(unittest.TestCase):
    def test_rne_equals_torch_bfloat16_on_ties_and_random_bits(self):
        for seed in (1, 2, 3):
            values = finite_fp32(seed)
            self.assertEqual(counter._cia_f32_rne_bf16(raw(values)), raw(values.to(torch.bfloat16)))

    def test_nonfinite_master_is_refused(self):
        for value in (float('inf'), float('-inf'), float('nan')):
            data = raw(torch.tensor([1.0, value, 2.0]))
            with self.assertRaises(ValueError):
                counter._cia_f32_rne_bf16(data)

    def test_exactness_flag_and_view_digest(self):
        exact = torch.randn(4096, generator=torch.Generator().manual_seed(5)).to(torch.bfloat16).float()
        total, high, is_exact = counter._cia_f32_facts_from_raw(raw(exact))
        self.assertTrue(is_exact)
        self.assertEqual(total, sha(raw(exact)))
        self.assertEqual(high, sha(raw(exact.to(torch.bfloat16))))
        poked = exact.clone().view(torch.int32)
        poked[7] |= 1
        self.assertFalse(counter._cia_f32_facts_from_raw(raw(poked.view(torch.float32)))[2])


class Lineage(unittest.TestCase):
    """The derive over synthetic parent and child facts built with the same builders the writer and the counter use."""
    NAMES = ('dense', 'idle', 'cold')

    def make(self, mutate=None, parent_master=False, child_master=True):
        g = torch.Generator().manual_seed(11)
        weights = {name: (torch.randn(64, generator=g) * .05).to(torch.bfloat16) for name in self.NAMES}
        def moment_pair():
            return ((torch.randn(64, generator=g) * .01).to(torch.bfloat16),
                    (torch.rand(64, generator=g) * .01 + 1e-4).to(torch.bfloat16))
        parent_state = {}
        for name in ('dense', 'idle'):
            avg, sq = moment_pair()
            parent_state[name] = {'step': torch.tensor(5.), 'exp_avg': avg, 'exp_avg_sq': sq}
        child_weights = dict(weights)
        child_state, child_masters = {}, {}
        dense_master = weights['dense'].float() + torch.randn(64, generator=g) * 1e-3
        child_weights['dense'] = dense_master.to(torch.bfloat16)
        child_masters['dense'] = dense_master
        child_state['dense'] = {'step': torch.tensor(8.), 'exp_avg': torch.randn(64, generator=g) * .01,
                                'exp_avg_sq': torch.rand(64, generator=g) * .01 + 1e-4}
        child_masters['idle'] = weights['idle'].float()
        child_state['idle'] = {'step': torch.tensor(5.), 'exp_avg': parent_state['idle']['exp_avg'].float(),
                               'exp_avg_sq': parent_state['idle']['exp_avg_sq'].float()}
        if mutate is not None:
            mutate(child_weights, child_state, child_masters)
        parent_masters = None
        if parent_master:
            parent_masters = {n: weights[n].float() for n in parent_state}
            parent_state = {n: {k: (v.float() if k != 'step' else v) for k, v in s.items()} for n, s in parent_state.items()}
        parent_facts = artifacts._cia_lineage_facts(weights, parent_state, parent_masters)
        if child_master:
            child_facts = artifacts._cia_lineage_facts(child_weights, child_state, child_masters)
        else:
            native = {n: {k: (v.to(torch.bfloat16) if k != 'step' else v) for k, v in s.items()} for n, s in child_state.items()}
            child_facts = artifacts._cia_lineage_facts(child_weights, native)
        placement = {name: {'requires_grad': True} for name in self.NAMES}
        parent = dict(data_cursor=dict(global_step=5, tokens_seen=20), expert_genesis_sha256={},
                      checkpoint_manifest_sha256='a' * 64, _parent_counter_receipt_sha256='b' * 64, placement=placement)
        child = copy.deepcopy(parent)
        child['data_cursor'] = dict(global_step=8, tokens_seen=32)
        return [Path('fixture'), parent, parent_facts, child, child_facts]

    def test_exact_upcast_of_an_inactive_owner_from_a_native_parent_is_accepted(self):
        result = counter._cia_derive_first_lineage(*self.make())
        self.assertEqual(result['updated_parameters'], ['dense'])
        self.assertEqual(result['changed_parameters'], ['dense'])
        self.assertEqual(result['schema_version'], 'ember-cia-first-descendant-v1')

    def test_master_chain_with_unchanged_inactive_owner_is_accepted(self):
        result = counter._cia_derive_first_lineage(*self.make(parent_master=True))
        self.assertEqual(result['updated_parameters'], ['dense'])

    def test_native_parent_rejections(self):
        def inexact_moment(w, s, m): s['idle']['exp_avg'] = (s['idle']['exp_avg'].view(torch.int32) | 1).view(torch.float32)
        def changed_moment(w, s, m): s['idle']['exp_avg_sq'] = (s['idle']['exp_avg_sq'] * 2).to(torch.bfloat16).float()
        def inexact_master(w, s, m): m['idle'] = (m['idle'].view(torch.int32) | 1).view(torch.float32)
        def master_not_param(w, s, m): m['idle'] = (w['idle'].float() + 1.0).to(torch.bfloat16).float()
        def clock_moved_without_update(w, s, m): s['idle']['step'] = torch.tensor(4.)
        def broken_invariant(w, s, m): w['dense'] = (w['dense'].float() * 2).to(torch.bfloat16)
        def master_missing(w, s, m): del m['idle']
        def master_extra(w, s, m): m['cold'] = w['cold'].float()
        for mutate in (inexact_moment, changed_moment, inexact_master, master_not_param, clock_moved_without_update,
                       broken_invariant, master_missing, master_extra):
            with self.assertRaises(ValueError, msg=mutate.__name__):
                counter._cia_derive_first_lineage(*self.make(mutate))

    def test_master_chain_rejections(self):
        def moment_drift(w, s, m): s['idle']['exp_avg'] = s['idle']['exp_avg'] + 2.0 ** -20
        def master_drift(w, s, m): m['idle'] = m['idle'] + 2.0 ** -20
        for mutate in (moment_drift, master_drift):
            with self.assertRaises(ValueError, msg=mutate.__name__):
                counter._cia_derive_first_lineage(*self.make(mutate, parent_master=True))

    def test_master_lineage_cannot_return_to_native_state(self):
        with self.assertRaisesRegex(ValueError, 'cannot return'):
            counter._cia_derive_first_lineage(*self.make(parent_master=True, child_master=False))


class RoundTrip(unittest.TestCase):
    def build(self, master=True, seed=0):
        g = torch.Generator().manual_seed(seed)
        params = {'a': torch.nn.Parameter((torch.randn(256, generator=g) * .05).to(torch.bfloat16)),
                  'b': torch.nn.Parameter((torch.randn(128, generator=g) * .01).to(torch.bfloat16))}
        model = type('Fixture', (), {'parameter_inventory': lambda _: params})()
        optimizer = torch.optim.AdamW(list(params.values()), lr=1e-4, foreach=False, fused=True)
        if master: M.enable(optimizer)
        return params, model, optimizer

    def grads(self, params, step):
        g = torch.Generator().manual_seed(100 + step)
        for p in params.values(): p.grad = (torch.randn(p.shape, generator=g) * .1).to(torch.bfloat16)

    def step(self, params, optimizer, step):
        self.grads(params, step)
        for group in optimizer.param_groups:
            M.step(optimizer, group, [p for p in group['params'] if p.grad is not None], None)

    def setUp(self):
        self.identity = {'param_groups': [{'params': ['a', 'b']}]}
        patcher = patch.object(artifacts, 'cia_optimizer_identity', return_value=self.identity)
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self, model, optimizer, cap=1 << 20):
        return artifacts.capture_cia_placed_optimizer_state(model, optimizer, max_state_bytes=cap)

    def trained(self):
        params, model, optimizer = self.build()
        for s in range(3): self.step(params, optimizer, s)
        return params, model, optimizer

    def test_v3_capture_holds_fp32_moments_and_masters_that_round_to_the_weights(self):
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        self.assertEqual(payload['schema_version'], V3)
        self.assertEqual(set(payload['master_weights']), {'a', 'b'})
        for name, master in payload['master_weights'].items():
            self.assertEqual(master.dtype, torch.float32)
            self.assertTrue(torch.equal(master.to(torch.bfloat16), params[name].detach()))
            self.assertEqual(payload['state'][name]['exp_avg'].dtype, torch.float32)
            self.assertEqual(payload['state'][name]['exp_avg_sq'].dtype, torch.float32)
        self.assertNotEqual(payload['master_weights']['a'].data_ptr(), M.masters(optimizer)[id(params['a'])].data_ptr())

    def test_native_optimizer_still_captures_v2_with_no_master(self):
        params, model, optimizer = self.build(master=False)
        self.grads(params, 0)
        optimizer.step()
        payload = self.capture(model, optimizer)
        self.assertEqual(payload['schema_version'], 'ember-cia-placed-optimizer-state-v2')
        self.assertIsNone(payload['master_weights'])

    def test_restore_is_bit_exact_and_the_next_update_matches(self):
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        fresh_params, fresh_model, fresh = self.build(seed=99)
        with torch.no_grad():
            for name, value in params.items(): fresh_params[name].copy_(value)
        prepared = artifacts.prepare_cia_placed_optimizer_state(fresh_model, fresh, payload, max_state_bytes=1 << 20)
        self.assertEqual(set(prepared['masters']), {0, 1})
        fresh.load_state_dict({'state': {}, 'param_groups': prepared['param_groups']})
        M.install(fresh, prepared['state'], prepared['masters'])
        self.assertEqual(M.check_invariant(fresh), [])
        for name in ('a', 'b'):
            for key in ('step', 'exp_avg', 'exp_avg_sq'):
                self.assertTrue(torch.equal(fresh.state[fresh_params[name]][key], optimizer.state[params[name]][key]), (name, key))
                self.assertEqual(fresh.state[fresh_params[name]][key].dtype, torch.float32)
            self.assertTrue(torch.equal(M.masters(fresh)[id(fresh_params[name])], M.masters(optimizer)[id(params[name])]))
        self.step(params, optimizer, 3)
        self.step(fresh_params, fresh, 3)
        for name in ('a', 'b'):
            self.assertTrue(torch.equal(fresh_params[name].detach(), params[name].detach()))
            self.assertTrue(torch.equal(M.masters(fresh)[id(fresh_params[name])], M.masters(optimizer)[id(params[name])]))

    def test_torch_load_state_dict_would_narrow_the_moments(self):
        """The reason restore installs v3 state directly: torch casts a floating moment to the parameter dtype."""
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        fresh_params, fresh_model, fresh = self.build(seed=99)
        prepared = artifacts.prepare_cia_placed_optimizer_state(fresh_model, fresh, payload, max_state_bytes=1 << 20)
        fresh.load_state_dict({'state': prepared['state'], 'param_groups': prepared['param_groups']})
        self.assertEqual(fresh.state[fresh_params['a']]['exp_avg'].dtype, torch.bfloat16)

    def test_v3_payload_refuses_a_native_runtime(self):
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        _, native_model, native = self.build(master=False)
        with self.assertRaisesRegex(ValueError, 'requires the fp32 master treatment'):
            artifacts.prepare_cia_placed_optimizer_state(native_model, native, payload, max_state_bytes=1 << 20)

    def test_v2_payload_prepares_for_a_master_runtime_and_converts_exactly(self):
        params, model, optimizer = self.build(master=False)
        self.grads(params, 0)
        optimizer.step()
        payload = self.capture(model, optimizer)
        fresh_params, fresh_model, fresh = self.build(seed=99)
        prepared = artifacts.prepare_cia_placed_optimizer_state(fresh_model, fresh, payload, max_state_bytes=1 << 20)
        self.assertNotIn('masters', prepared)
        with torch.no_grad():
            for name, value in params.items(): fresh_params[name].copy_(value)
        fresh.load_state_dict(prepared)
        M.convert_loaded(fresh)
        for name in ('a', 'b'):
            state = fresh.state[fresh_params[name]]
            self.assertEqual(state['exp_avg'].dtype, torch.float32)
            self.assertTrue(torch.equal(state['exp_avg'], optimizer.state[params[name]]['exp_avg'].float()))
            self.assertTrue(torch.equal(M.masters(fresh)[id(fresh_params[name])], params[name].detach().float()))

    def test_corrupt_v3_payloads_are_refused(self):
        params, model, optimizer = self.trained()
        original = self.capture(model, optimizer)
        def prepare(payload, cap=1 << 20):
            return artifacts.prepare_cia_placed_optimizer_state(model, optimizer, payload, max_state_bytes=cap)
        cases = {}
        for label in ('missing_master', 'extra_master', 'bf16_master', 'nan_master', 'v3_without_masters', 'v2_with_masters',
                      'bf16_moment', 'shape'):
            payload = copy.deepcopy(original)
            if label == 'missing_master': del payload['master_weights']['b']
            elif label == 'extra_master': payload['master_weights']['c'] = payload['master_weights']['a'].clone()
            elif label == 'bf16_master': payload['master_weights']['a'] = payload['master_weights']['a'].to(torch.bfloat16)
            elif label == 'nan_master': payload['master_weights']['a'][3] = float('nan')
            elif label == 'v3_without_masters': payload['master_weights'] = None
            elif label == 'v2_with_masters': payload['schema_version'] = 'ember-cia-placed-optimizer-state-v2'
            elif label == 'bf16_moment': payload['state']['a']['exp_avg'] = payload['state']['a']['exp_avg'].to(torch.bfloat16)
            else: payload['master_weights']['a'] = payload['master_weights']['a'][:100].clone()
            cases[label] = payload
        for label, payload in cases.items():
            with self.assertRaises(ValueError, msg=label):
                prepare(payload)
        with self.assertRaisesRegex(ValueError, 'byte cap'):
            prepare(copy.deepcopy(original), cap=(256 + 128) * 12 + 2 * 4 - 1)
        self.assertEqual(set(prepare(copy.deepcopy(original), cap=(256 + 128) * 12 + 2 * 4)['masters']), {0, 1})

    def read_back(self, payload):
        """The counter's own file read of a saved payload, torch-free (zip + restricted pickle)."""
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'optimizer-state.pt'
            torch.save(payload, path)
            with zipfile.ZipFile(path) as archive:
                loaded = counter._load_checkpoint_metadata(archive)
                inventory = {'a': (256,), 'b': (128,)}
                groups = {'a': {'amsgrad': False}, 'b': {'amsgrad': False}}
                return counter._cia_counter_optimizer_facts(archive, loaded, inventory, groups,
                                                            loaded['schema_version'] == V3)

    def test_counter_file_read_equals_the_writers_in_memory_facts_for_v3_and_v2(self):
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        in_memory = artifacts._cia_lineage_facts(params, payload['state'], payload['master_weights'])
        read, extra = self.read_back(payload)
        self.assertEqual(read, in_memory['optimizer'])
        self.assertEqual({k: v for k, v in extra.items()},
                         {k: in_memory[k] for k in ('optimizer_schema', 'master', 'master_bf16', 'master_exact', 'optimizer_view')})
        native_params, native_model, native = self.build(master=False)
        for s in range(2):
            self.grads(native_params, s)
            native.step()
        native_payload = self.capture(native_model, native)
        read, extra = self.read_back(native_payload)
        self.assertIsNone(extra)
        self.assertEqual(read, artifacts._cia_lineage_facts(native_params, native_payload['state'])['optimizer'])

    def test_counter_file_read_refuses_wrong_dtype_and_uncovered_masters(self):
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        bad = copy.deepcopy(payload)
        bad['master_weights']['a'] = bad['master_weights']['a'].to(torch.bfloat16)
        with self.assertRaises(ValueError): self.read_back(bad)
        bad = copy.deepcopy(payload)
        del bad['master_weights']['b']
        with self.assertRaises(ValueError): self.read_back(bad)
        bad = copy.deepcopy(payload)
        bad['state']['a']['exp_avg'] = bad['state']['a']['exp_avg'].to(torch.bfloat16)
        with self.assertRaises(ValueError): self.read_back(bad)

    def test_lineage_facts_of_the_payload_carry_the_counter_fields(self):
        params, model, optimizer = self.trained()
        payload = self.capture(model, optimizer)
        facts = artifacts._cia_lineage_facts(params, payload['state'], payload['master_weights'])
        self.assertEqual(facts['optimizer_schema'], 'fp32_master_v1')
        for name in ('a', 'b'):
            self.assertEqual(facts['master_bf16'][name], facts['parameters'][name])
            self.assertEqual(facts['master'][name], sha(raw(payload['master_weights'][name])))
            self.assertFalse(facts['master_exact'][name])
            self.assertEqual(facts['optimizer_view'][name], {'step': 3, 'exp_avg': None, 'exp_avg_sq': None})
        counter._cia_master_check(facts)


if __name__ == '__main__':
    unittest.main()
