# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""File-level fp32 master round trip (#2119, lead review 82486 item 6): a v3 child is PUBLISHED by the real writer (the real counter runs as
the pre-publish verifier), its optimizer-state.pt is read back from disk, and the REAL loader (`load_checkpoint_artifacts` ->
`_load_cia_checkpoint_artifacts`) restores weights, fp32 masters and fp32 moments bit-exactly. The hour evidence reads the schema from that
same file, and an hour that declared fp32_master_v1 but wrote a native (v2) child is refused. CPU only, 26 tiny owners."""
import hashlib
import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
with warnings.catch_warnings():
    # see test_issue2119_fp32_master_state.py: the wiring gate accepts no warning, and the model stack warns once at first import
    warnings.filterwarnings('ignore', message='`torch.jit.script_method` is deprecated', category=DeprecationWarning)
    import checkpoint_artifacts as artifacts  # noqa: E402
    import parameter_counter as counter  # noqa: E402
    from ember.model import ember_v0_inventory as cia_inventory, ember_v0_decoder as cia_decoder  # noqa: E402
    from ember.model.ember_v0_contract import cia_architecture_config, validate_cia_architecture  # noqa: E402
import cia_fp32_evidence as E  # noqa: E402
import cia_fp32_master as M  # noqa: E402

ZERO = torch.zeros(())
V2 = 'ember-cia-placed-optimizer-state-v2'


class Published(unittest.TestCase):
    def build(self, master):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'published'
        self.config_path = Path(self.temp.name) / 'config.json'
        self.config_path.write_text(json.dumps(cia_architecture_config()), encoding='utf-8')
        specs = (cia_inventory.TensorSpec('embedding.weight', (8,), 'core'),) + tuple(
            cia_inventory.TensorSpec(f'experts.{i}.weight', (8,), 'expert', i) for i in range(25))
        self.parameters = {spec.name: torch.nn.Parameter(torch.full(spec.shape, i, dtype=torch.bfloat16)) for i, spec in enumerate(specs)}
        self.model = type('Fixture', (), {'parameter_inventory': lambda _: self.parameters})()
        self.model.config = validate_cia_architecture(cia_architecture_config())
        self.model._cuda_execution = None
        dispatch = patch.object(cia_decoder, 'CIADecoder', type(self.model))
        dispatch.start()
        self.addCleanup(dispatch.stop)
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=.01, foreach=False, fused=True)
        if master:
            M.enable(self.optimizer)
        self.identity = {'param_groups': [{'params': list(self.parameters), 'hyperparameters': {'amsgrad': False}}]}
        for target, attr, value in ((cia_inventory, 'equation_inventory', specs), (artifacts, 'cia_optimizer_identity', self.identity)):
            mocking = patch.object(target, attr, return_value=value)
            mocking.start()
            self.addCleanup(mocking.stop)
        self.kwargs = dict(launch_seed=7, rng_state={'cpu': torch.get_rng_state(), 'cuda': torch.empty(0, dtype=torch.uint8)},
            data_cursor={'shard': 'fixture', 'record_index': 0, 'global_step': 0, 'tokens_seen': 0},
            model_config_sha256=hashlib.sha256(self.config_path.read_bytes()).hexdigest(), contract_sha256='2' * 64,
            expert_genesis_sha256={}, max_serialized_bytes=4 * 1024 * 1024, max_transient_scratch_bytes=1024 * 1024,
            pre_publish_verifier=self.verifier)

    def verifier(self, candidate, receipt):
        result = counter.execute_counter(model_config=self.config_path, checkpoint_manifest=candidate / 'checkpoint-manifest.json',
                                         active_expert='all')
        (candidate / 'parameter-counter-receipt.json').write_text(json.dumps(result), encoding='utf-8')
        return result

    def step(self, round_):
        gen = torch.Generator().manual_seed(40 + round_)
        for p in self.parameters.values():
            p.grad = (torch.randn(p.shape, generator=gen) * 0.1).to(torch.bfloat16)
        for group in self.optimizer.param_groups:
            M.step(self.optimizer, group, [p for p in group['params'] if p.grad is not None], ZERO)

    def native_step(self, round_):
        gen = torch.Generator().manual_seed(40 + round_)
        for p in self.parameters.values():
            p.grad = (torch.randn(p.shape, generator=gen) * 0.1).to(torch.bfloat16)
        self.optimizer.step()

    def publish(self):
        self.optimizer.zero_grad(set_to_none=True)   # the hour clears gradients before it publishes (an update boundary)
        return artifacts.write_checkpoint_artifacts(self.model, self.optimizer, self.root, **self.kwargs)

    def snapshot(self):
        masters = {n: M.masters(self.optimizer)[p].clone() for n, p in self.parameters.items()} if M.enabled(self.optimizer) else {}
        return dict(weights={n: p.detach().clone() for n, p in self.parameters.items()}, masters=masters,
                    exp_avg={n: self.optimizer.state[p]['exp_avg'].clone() for n, p in self.parameters.items()},
                    exp_avg_sq={n: self.optimizer.state[p]['exp_avg_sq'].clone() for n, p in self.parameters.items()},
                    step={n: float(self.optimizer.state[p]['step']) for n, p in self.parameters.items()})


class V3RoundTrip(Published):
    def test_a_published_v3_child_reopens_bit_exact_through_the_real_loader(self):
        self.build(True)
        for r in range(3):
            self.step(r)
        before = self.snapshot()
        receipt = self.publish()
        payload = torch.load(self.root / 'optimizer-state.pt', map_location='cpu', weights_only=True, mmap=True)
        self.assertEqual(payload['schema_version'], E.V3)
        self.assertEqual(set(payload['master_weights']), set(self.parameters))
        self.assertTrue(all(v.dtype == torch.float32 for v in payload['master_weights'].values()))
        # destroy the live state, then restore it from the published bytes only
        with torch.no_grad():
            for p in self.parameters.values():
                p.add_(50)
        self.optimizer.state.clear()
        M.masters(self.optimizer).clear()
        artifacts.load_checkpoint_artifacts(self.model, self.optimizer, self.root, receipt, max_transient_scratch_bytes=1024 * 1024)
        after = self.snapshot()
        for key in ('weights', 'masters', 'exp_avg', 'exp_avg_sq', 'step'):
            for name in before[key]:
                self.assertTrue(torch.equal(torch.as_tensor(before[key][name]), torch.as_tensor(after[key][name])), (key, name))
        self.assertEqual(M.check_invariant(self.optimizer), [])
        for name, p in self.parameters.items():
            self.assertEqual(self.optimizer.state[p]['exp_avg_sq'].dtype, torch.float32)
            self.assertEqual(M.masters(self.optimizer)[p].dtype, torch.float32)

    def test_the_hour_evidence_reads_v3_from_the_published_file_and_passes(self):
        self.build(True)
        self.step(0)
        evidence = E.Evidence(self.optimizer, self.parameters, every=2, track=lambda n, p: True)
        evidence.observe(0)
        for r in range(1, 5):
            self.step(r)
            if evidence.due(r):
                evidence.observe(r)
        self.publish()
        block = evidence.finish(4, child_optimizer_state_path=self.root / 'optimizer-state.pt')
        self.assertEqual(block['optimizer_schema'], E.V3)
        self.assertIs(E.require(block, declared=True), block)
        self.assertGreater(block['trace'][-1]['groups']['experts']['master_residual_fraction'], 0)


class NativeChildRefused(Published):
    def test_a_declared_fp32_hour_that_wrote_a_native_child_is_refused_from_the_written_file(self):
        self.build(False)
        self.native_step(0)
        evidence = E.Evidence(self.optimizer, self.parameters, every=2, track=lambda n, p: True)
        evidence.observe(0)
        self.native_step(1)
        self.publish()
        block = evidence.finish(1, child_optimizer_state_path=self.root / 'optimizer-state.pt')
        self.assertEqual(block['optimizer_schema'], V2)
        with self.assertRaisesRegex(ValueError, 'v2'):
            E.require(block, declared=True)
        self.assertIsNone(E.require(block, declared=False) and None)


if __name__ == '__main__':
    unittest.main()
