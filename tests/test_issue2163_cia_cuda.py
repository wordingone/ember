from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
"""Opt-in full-population CUDA conformance, never trained capability or throughput."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import os
import sys
import time
import unittest
import torch
from ember.model.cia_decoder import CIADecoder
from ember.governance.scripts.cia_conformance import fixed_input_values, require_current_dispatch

LIVE = '--live' in sys.argv
if LIVE:
    sys.argv.remove('--live')
REQUESTED = os.environ.get('EMBER_CIA_CUDA_CONFORMANCE') == '1'
if REQUESTED and (not LIVE or os.environ.get('EMBER_GATE_AUTHORIZED') != '1'):
    raise RuntimeError('full CUDA conformance requires --live and existing launch authorization')


@unittest.skipUnless(REQUESTED, 'requires owned full-population CUDA resource window')
class FullPopulationCUDA(unittest.TestCase):
    def test_full_population_forward_backward_and_update(self):
        binding = json.loads(Path(os.environ["EMBER_CIA_SUBJECT_BINDING"]).read_text(encoding="utf-8"))
        require_current_dispatch(Path(__file__).resolve().parents[1], binding)
        torch.set_num_threads(1)
        self.assertTrue(torch.cuda.is_available(), 'CUDA unavailable in governed runtime')
        device = torch.device('cuda:0')
        total = torch.cuda.get_device_properties(device).total_memory
        limit = int(os.environ['EMBER_CIA_GPU_MAX_BYTES'])
        self.assertGreater(limit, 0)
        self.assertLess(limit, total)
        torch.cuda.set_per_process_memory_fraction(limit / total, device)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        started = time.perf_counter()
        print('CIA_CUDA_PHASE', {'phase': 'materialize_cpu', 'elapsed_seconds': 0}, flush=True)
        config_path = Path(__file__).resolve().parents[1] / "configs/ember-cia-3b.json"
        architecture_config = json.loads(config_path.read_text(encoding="utf-8"))
        model = CIADecoder(architecture_config=architecture_config).materialize_cpu(seed=2163)
        parameters = model.parameter_inventory()
        self.assertEqual(sum(value.numel() for value in parameters.values()), 3082539008)
        print('CIA_CUDA_PHASE', {'phase': 'cpu_reference', 'unique_parameters': 3082539008,
              'elapsed_seconds': time.perf_counter() - started}, flush=True)
        token_values, position_values = fixed_input_values()
        tokens = torch.tensor(token_values, dtype=torch.long)
        positions = torch.tensor(position_values, dtype=torch.long)
        cpu_logits, cpu_routes = model(model.embed_text(tokens), positions, return_routes=True)
        experts = tuple(sorted({row[-1] for row in cpu_routes}))
        self.assertGreater(len(experts), 2, 'fixture must exercise eviction beyond two global experts')
        loss = cpu_logits[:, :64].float().square().mean()
        loss.backward()
        last_layer_expert = next(row[-1] for row in reversed(cpu_routes) if row[1] == 23)
        names = ('layers.0.attention.q.weight', 'router.global_query.weight',
                 'router.local_query.weight', f'experts.{last_layer_expert}.layers.23.up.weight')
        reference_gradients = {}
        for name in names:
            self.assertIsNotNone(parameters[name].grad, name)
            self.assertTrue(torch.isfinite(parameters[name].grad).all(), name)
            self.assertGreater(float(parameters[name].grad.float().abs().sum()), 0, name)
            reference_gradients[name] = parameters[name].grad.detach().clone()
        reference_logits = cpu_logits.detach()
        del loss, cpu_logits
        for value in parameters.values():
            value.grad = None
        print('CIA_CUDA_PHASE', {'phase': 'activate_cuda', 'visited_experts': experts,
              'elapsed_seconds': time.perf_counter() - started}, flush=True)
        model.activate_cuda(device)
        tokens = tokens.to(device)
        positions = positions.to(device)
        torch.cuda.reset_peak_memory_stats(device)
        with model.candidate_step():
            logits, routes = model(model.embed_text(tokens), positions, return_routes=True)
            self.assertEqual(routes, cpu_routes)
            torch.testing.assert_close(logits.detach().cpu(), reference_logits, rtol=0.05, atol=0.05)
            logits[:, :64].float().square().mean().backward()
        for name, expected in reference_gradients.items():
            actual = parameters[name].grad.cpu()
            self.assertTrue(torch.isfinite(actual).all(), name)
            self.assertGreater(float(actual.float().abs().sum()), 0, name)
            relative_error = (actual.float() - expected.float()).norm() / expected.float().norm()
            self.assertLess(float(relative_error), 0.1, name)
        self.assertLessEqual(model._cuda_execution.cache.peak_resident_bundles, 2)
        self.assertEqual(model._cuda_execution.cache.resident_count, 0)
        print('CIA_CUDA_PHASE', {'phase': 'forward_backward_conforms',
              'elapsed_seconds': time.perf_counter() - started}, flush=True)
        del logits, reference_logits, reference_gradients
        # A subsequent explicit support changes actual parameters. No production
        # optimizer choice or full checkpoint/clock-recovery claim is made here.
        selected = model.apply_update_support('core+expert-set', experts=experts)
        optimizer = torch.optim.AdamW(selected, lr=1e-3, foreach=False)
        changed_name = 'layers.0.attention.q.weight'
        old = parameters[changed_name].detach().cpu().clone()
        inactive = next(expert for expert in range(25) if expert not in experts)
        inactive_name = f'experts.{inactive}.layers.1.up.weight'
        untouched = parameters[inactive_name].detach().clone()
        optimizer.zero_grad(set_to_none=True)
        update_started = time.perf_counter()
        with model.candidate_step():
            logits = model(model.embed_text(tokens), positions)
            logits[:, :64].float().square().mean().backward()
        optimizer.step()
        torch.cuda.synchronize(device)
        self.assertFalse(torch.equal(parameters[changed_name].detach().cpu(), old))
        self.assertTrue(torch.equal(parameters[inactive_name], untouched))
        self.assertIsNone(parameters[inactive_name].grad)
        peak = torch.cuda.max_memory_allocated(device)
        self.assertLessEqual(peak, limit)
        print('CIA_CUDA_CONFORMANCE', {'unique_parameters': 3082539008, 'visited_experts': experts,
              'memory_scope': 'PyTorch allocator only; external total-device supervision required',
              'gpu_peak_allocated_bytes': peak, 'gpu_peak_reserved_bytes': torch.cuda.max_memory_reserved(device),
              'gpu_limit_bytes': limit, 'complete_update_seconds': time.perf_counter() - update_started,
              'total_seconds': time.perf_counter() - started, 'claim': 'fixed-data correctness and update mechanics only'}, flush=True)


if __name__ == '__main__':
    unittest.main()
