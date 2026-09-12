# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU verification of trajectory accounting and numerical comparisons; no model qualification claim."""
import importlib.util
import contextlib
import inspect
import os
from pathlib import Path
import sys
import unittest
import tempfile
import json
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import torch

SOURCE = Path(os.environ.get('CIA_TRAJECTORY_SOURCE', str(Path(__file__).resolve().parents[2] /
    'src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py')))
subject = None
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('tested_cia_trajectory', SOURCE)
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)

RUNNER = Path(os.environ.get('CIA_TRAJECTORY_RUNNER', str(SOURCE.with_name('cia_step_runner.py'))))
runner_spec = importlib.util.spec_from_file_location('tested_cia_trajectory_runner', RUNNER)
runner = importlib.util.module_from_spec(runner_spec)
sys.modules[runner_spec.name] = runner
runner_spec.loader.exec_module(runner)


class TrajectoryCoreTests(unittest.TestCase):
    def test_adjudicator_opens_complete_per_arm_tensor_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            roots, hashes = {}, {}
            rows = [dict(update=i + 1, loss=10.0, census=[[4096] + [0] * 24] * 12) for i in range(64)]
            inventory = {'owner': torch.nn.Parameter(torch.ones(3, dtype=torch.bfloat16))}
            for name in ('R1', 'R2', 'Tdynamic', 'R3'):
                root = Path(temporary) / name
                root.mkdir()
                snapshots = {str(i): subject.save_snapshot(inventory, root, update=i, budget_bytes=8192) for i in (1, 64)}
                arm = dict(arm=name, frozen_owners_unchanged=True, snapshot_updates=[1, 64], snapshots=snapshots,
                           start=dict(source_sha256={'model': 'a' * 64}, optimizer={'foreach': False},
                                      population_sha256='b' * 64, comparison_id='c' * 32,
                                      **(dict(document_permutation=[[1, 0, 3, 2]] * 64, executed_input_sha256='e' * 64)
                                         if name == 'R3' else {})), rows=rows)
                data = json.dumps(arm).encode()
                (root / ('t2-arm-' + name + '.json')).write_bytes(data)
                (root / 'worker-terminal.json').write_text(json.dumps(dict(status='completed', applied_positions=64 * 4096)))
                roots[name], hashes[name] = root, hashlib.sha256(data).hexdigest()
            verdict = subject.adjudicate_arms(roots, hashes)
            self.assertTrue(verdict['passed'])
            self.assertEqual(verdict['permuted_reference_floor']['census_difference_updates'], [])
            self.assertEqual(verdict['permuted_reference_floor']['worst_relative_l2_by_update'], {'1': 0.0, '64': 0.0})
            (roots['R2'] / 'worker-terminal.json').write_text(json.dumps(dict(status='failed', applied_positions=4096)))
            with self.assertRaisesRegex(ValueError, 'complete applied'):
                subject.adjudicate_arms(roots, hashes)

    def test_arm_start_identity_refuses_lineage_and_allows_only_declared_optimizer_treatment(self):
        reference = dict(population_sha256='a' * 64, source_commit='b' * 40,
                         source_sha256={'model.py': 'c' * 64}, optimizer={'foreach': False},
                         comparison_id='d' * 32, cursor={'token_offset': 0})
        treatment = dict(reference, source_sha256=dict(reference['source_sha256'], capture='e' * 64))
        subject.compare_start_identity(reference, treatment, arm='Tdynamic')
        with self.assertRaisesRegex(ValueError, 'starting'):
            subject.compare_start_identity(reference, dict(treatment, population_sha256='f' * 64), arm='Tdynamic')
        fused = dict(treatment, optimizer={'foreach': False, 'fused': True})
        subject.compare_start_identity(reference, fused, arm='Tfused')
        with self.assertRaises(ValueError):
            subject.compare_start_identity(reference, fused, arm='Tdynamic')

    def test_r3_permutation_reorders_documents_and_inverts_routing_reports(self):
        sequence = 1024
        pack = dict(index=0, phase='warm', document_starts=[d * sequence for d in range(4)],
                    token_ids=[d for d in range(4) for _ in range(sequence)],
                    target_ids=[10 + d for d in range(4) for _ in range(sequence)],
                    positions=[[p, 0, 0] for _ in range(4) for p in range(sequence)])
        order = [2, 0, 3, 1]
        permuted = subject.permute_pack(pack, order)
        self.assertEqual(permuted['document_starts'], pack['document_starts'])
        self.assertEqual(permuted['positions'], pack['positions'])
        self.assertEqual([permuted['token_ids'][s * sequence] for s in range(4)], order)
        self.assertEqual([permuted['target_ids'][s * sequence] for s in range(4)], [10 + d for d in order])
        inverse = [order.index(d) for d in range(4)]
        self.assertEqual(subject.permute_pack(permuted, inverse), pack)
        with self.assertRaisesRegex(ValueError, 'geometry'):
            subject.permute_pack(dict(pack, token_ids=pack['token_ids'][:-1]), order)
        with self.assertRaisesRegex(ValueError, 'geometry'):
            subject.permute_pack(pack, [0, 0, 1, 2])
        data = dict(priors=[[float(d)] * 25 for d in range(4)], ranked=[[d, d + 1] for d in range(4)],
                    candidates=[[d, d + 1] for d in range(4)],
                    winners=[[d + c % 2 for d in range(4) for c in range(4)] for _ in range(12)],
                    logits=[[[float(d), float(c)] for d in range(4) for c in range(4)] for _ in range(12)],
                    gates=[[(d + c / 10) / 4 for d in range(4) for c in range(4)] for _ in range(12)], valid=[True] * 12)
        executed = dict(data, priors=[data['priors'][d] for d in order], ranked=[data['ranked'][d] for d in order],
                        candidates=[data['candidates'][d] for d in order],
                        winners=[[row[d * 4 + c] for d in order for c in range(4)] for row in data['winners']],
                        logits=[[row[d * 4 + c] for d in order for c in range(4)] for row in data['logits']],
                        gates=[[row[d * 4 + c] for d in order for c in range(4)] for row in data['gates']])
        self.assertNotEqual(executed['winners'], data['winners'])
        self.assertEqual(subject.unpermute_routing(executed, order), data)
        self.assertEqual(subject.routing_metrics(subject.unpermute_routing(executed, order))['census'],
                         subject.routing_metrics(data)['census'])

    def test_r3_identity_is_pinned_and_exclusive(self):
        base = dict(schema='reference-noise-floor-64-v1', arm='R3', comparison_id='c' * 32)
        rows = [[0, 1, 2, 3]] * 63 + [[1, 0, 3, 2]]
        self.assertTrue(runner.trajectory_mode({'trajectory': dict(base, document_permutation=rows)}))
        for bad in (None, [[0, 1, 2, 3]] * 64, rows[:63], [[0, 1, 2, 2]] * 64, [[0, 1, 2, 3.0]] * 64, rows + [rows[-1]]):
            with self.assertRaises(ValueError):
                runner.trajectory_mode({'trajectory': dict(base, document_permutation=bad)})
        with self.assertRaises(ValueError):
            runner.trajectory_mode({'trajectory': base})
        with self.assertRaises(ValueError):
            runner.trajectory_mode({'trajectory': dict(base, arm='R1', document_permutation=rows)})
        with self.assertRaises(ValueError):
            runner.trajectory_mode({'trajectory': dict(base, document_permutation=rows),
                                    'execution_mode': 'resident-segmented-capture'})
        reference = dict(population_sha256='a' * 64, source_commit='b' * 40, source_sha256={'m': 'c' * 64},
                         optimizer={'foreach': False}, comparison_id='d' * 32, cursor={'token_offset': 0})
        reference['input_binding'] = {'input_sha256': 'f' * 64}
        permuted = dict(reference, document_permutation=rows, executed_input_sha256='e' * 64)
        subject.compare_start_identity(reference, permuted, arm='R3')
        with self.assertRaisesRegex(ValueError, 'R3 start'):
            subject.compare_start_identity(reference, reference, arm='R3')
        with self.assertRaisesRegex(ValueError, 'only the R3'):
            subject.compare_start_identity(reference, permuted, arm='R2')
        for bad in ([[0, 1, 2, 3]] * 64, rows[:63], rows[:63] + [[0, 1, 2, 2]], rows[:63] + [[0, 1, 2, '3']]):
            with self.assertRaisesRegex(ValueError, 'non-identity document permutation'):
                subject.compare_start_identity(reference, dict(permuted, document_permutation=bad), arm='R3')
        for digest in ('e' * 63, 'E' * 64, 'f' * 64, 123):
            with self.assertRaisesRegex(ValueError, '64-hex digest'):
                subject.compare_start_identity(reference, dict(permuted, executed_input_sha256=digest), arm='R3')
        with self.assertRaisesRegex(ValueError, 'identities differ'):
            subject.compare_start_identity(reference, dict(permuted, population_sha256='0' * 64), arm='R3')

    def test_snapshot_files_preserve_all_support_and_reject_changed_bytes(self):
        inventory = {'active': torch.nn.Parameter(torch.arange(5, dtype=torch.bfloat16)),
                     'currently_unrouted': torch.nn.Parameter(torch.ones(3)),
                     'frozen': torch.nn.Parameter(torch.ones(2), requires_grad=False)}
        inventory['active'].grad = torch.ones_like(inventory['active'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = subject.save_snapshot(inventory, root, update=1, budget_bytes=8192)
            self.assertEqual(set(manifest['tensors']), {'active', 'currently_unrouted'})
            loaded = subject.load_snapshot(root, manifest)
            self.assertIsNone(loaded['tensors']['currently_unrouted']['gradient'])
            self.assertEqual(loaded['tensors']['active']['parameter'].dtype, torch.bfloat16)
            self.assertTrue(subject.compare_snapshot(loaded, inventory, device=torch.device('cpu'))['passed'])
            del loaded
            target = root / manifest['tensors']['active']['file']
            raw = target.read_bytes()
            target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, 'snapshot.*hash'):
                subject.load_snapshot(root, manifest)

    def setUp(self):
        self.assertIsNotNone(subject, 'the bounded trajectory implementation is missing')

    def test_population_digest_binds_names_shapes_dtype_and_bytes(self):
        first = {'a': torch.nn.Parameter(torch.arange(7, dtype=torch.bfloat16))}
        second = {'a': torch.nn.Parameter(first['a'].detach().clone())}
        self.assertEqual(subject.inventory_sha256(first), subject.inventory_sha256(second))
        second['a'].data[-1] += 1
        self.assertNotEqual(subject.inventory_sha256(first), subject.inventory_sha256(second))
        self.assertNotEqual(subject.inventory_sha256(first), subject.inventory_sha256({'b': first['a']}))
        self.assertNotEqual(subject.inventory_sha256(first), subject.inventory_sha256({'a': first['a'].reshape(1, 7)}))

    def test_snapshot_plan_accounts_for_full_dtype_and_records_single_snapshot_reason(self):
        inventory = {'a': torch.nn.Parameter(torch.ones(10, dtype=torch.bfloat16)),
                     'frozen': torch.nn.Parameter(torch.ones(100), requires_grad=False)}
        both = subject.snapshot_plan(inventory, budget_bytes=80)
        self.assertEqual(both['updates'], [1, 64])
        self.assertEqual(both['maximum_snapshot_bytes'], 80)
        one = subject.snapshot_plan(inventory, budget_bytes=79)
        self.assertEqual(one['updates'], [64])
        self.assertTrue(one['reason'])
        with self.assertRaises(ValueError):
            subject.snapshot_plan(inventory, budget_bytes=39)

    def test_chunked_comparison_checks_tail_and_absent_gradient_semantics(self):
        parameter = torch.nn.Parameter(torch.arange(1, 12, dtype=torch.bfloat16))
        parameter.grad = torch.ones_like(parameter)
        snapshot = subject.take_snapshot({'p': parameter}, budget_bytes=100)
        self.assertTrue(subject.compare_snapshot(snapshot, {'p': parameter}, device='cpu', chunk_elements=3)['passed'])
        parameter.grad[-1] = 8
        result = subject.compare_snapshot(snapshot, {'p': parameter}, device='cpu', chunk_elements=3)
        self.assertFalse(result['passed'])
        self.assertGreater(result['tensors']['p']['gradient']['relative_l2'], 0.05)
        parameter.grad = None
        self.assertFalse(subject.compare_snapshot(snapshot, {'p': parameter}, device='cpu')['passed'])
        other = torch.nn.Parameter(parameter.detach().clone())
        no_grad = subject.take_snapshot({'p': other}, budget_bytes=100)
        self.assertTrue(subject.compare_snapshot(no_grad, {'p': other}, device='cpu')['passed'])

    def test_snapshot_is_an_owned_copy_and_dtype_changes_refuse(self):
        parameter = torch.nn.Parameter(torch.ones(4, dtype=torch.bfloat16))
        snapshot = subject.take_snapshot({'p': parameter}, budget_bytes=100)
        parameter.data[0] = 9
        self.assertEqual(float(snapshot['tensors']['p']['parameter'][0]), 1)
        with self.assertRaises(ValueError):
            subject.compare_snapshot(snapshot, {'p': torch.nn.Parameter(torch.ones(4))}, device='cpu')

    def test_loss_bound_is_max_of_observed_floor_and_ruled_0_05(self):
        exact = [10.0] * 64
        within = [10.2] * 64
        good = subject.compare_loss_trajectories(exact, exact, within)
        self.assertTrue(good['passed'])
        self.assertEqual(good['regime'], 'ruled-0.05')
        noisy = [10.01] * 64
        self.assertTrue(subject.compare_loss_trajectories(exact, noisy, within)['passed'])
        self.assertFalse(subject.compare_loss_trajectories(exact, exact, [10.6] * 64)['passed'])
        larger = subject.compare_loss_trajectories(exact, [10.8] * 64, [10.7] * 64)
        self.assertTrue(larger['passed'])
        self.assertEqual(larger['regime'], 'observed-reference-floor-exceeds-0.05')
        with self.assertRaises(ValueError):
            subject.compare_loss_trajectories(exact, exact, within[:-1])
        with self.assertRaises(ValueError):
            subject.compare_loss_trajectories(exact, exact, [float('nan')] * 64)

    def test_rows_require_all_64_ordered_updates_and_exact_census(self):
        rows = [dict(update=i + 1, loss=10.0, census=[[4096] + [0] * 24] * 12) for i in range(64)]
        self.assertTrue(subject.compare_rows(rows, rows, rows)['passed'])
        changed = [dict(row) for row in rows]
        changed[3] = dict(changed[3], census=[[4095, 1] + [0] * 23] * 12)
        self.assertFalse(subject.compare_rows(rows, rows, changed)['passed'])
        with self.assertRaises(ValueError):
            subject.compare_rows(rows, rows, changed + [changed[-1]])
        with self.assertRaises(ValueError):
            subject.compare_rows(rows, rows, [rows[0]] + rows[:-1])

    def test_routing_observer_covers_all_chunks_and_health_uses_actual_winners(self):
        self.assertTrue(hasattr(subject, 'ReferenceRouting'), 'the reference routing observation adapter is missing')
        observer = subject.ReferenceRouting()
        for document in range(4):
            observer(SimpleNamespace(document=document, epoch_start=0, experts=(0, 1),
                                     log_prior=torch.zeros(25)))
            for layer in range(1, 24, 2):
                for start in (0, 256, 512, 768):
                    observer(SimpleNamespace(document=document, layer=layer, segment_start=start,
                                             candidates=(0, 1), chosen=0, logits=(1.0, 0.0)))
        data = observer.finish()
        metrics = subject.routing_metrics(data)
        self.assertEqual(metrics['census'], [[4096] + [0] * 24] * 12)
        self.assertEqual(metrics['switch_rate'], [0.0] * 12)
        self.assertEqual(metrics['gate_entropy'], [0.0] * 12)
        changed = dict(data, winners=[[1] + row[1:] for row in data['winners']])
        self.assertEqual(subject.routing_metrics(changed, previous=data)['switch_rate'], [1/16] * 12)
        with self.assertRaises(ValueError):
            observer(SimpleNamespace(document=0, epoch_start=0, experts=(0, 1), log_prior=torch.zeros(25)))
        with self.assertRaises(ValueError):
            subject.ReferenceRouting().finish()

    def test_completed_update_is_counted_before_a_diagnostic_failure(self):
        self.assertTrue(hasattr(subject, 'execute_steps'), 'the counted trajectory loop is missing')
        parameter = torch.nn.Parameter(torch.ones(2))
        optimizer = torch.optim.AdamW([parameter], foreach=False)
        packs = [dict(index=i, phase='warm' if i == 0 else 'measured', token_ids=[0, 1], target_ids=[1, 2],
                      positions=[[0, 0, 0], [1, 0, 0]], document_starts=[0]) for i in range(64)]
        applied, recorded = [], []
        def step(index, pack):
            optimizer.zero_grad(set_to_none=True)
            loss = parameter.square().sum()
            loss.backward()
            optimizer.step()
            return dict(index=index, applied_positions=2, loss=float(loss.detach()))
        def observe(index, row):
            raise RuntimeError('diagnostic fixture failed after update')
        with self.assertRaisesRegex(RuntimeError, 'diagnostic fixture'):
            subject.execute_steps(packs, step=step, record=recorded.append, applied=applied.append, observe=observe)
        self.assertEqual(applied, [2])
        self.assertEqual(len(recorded), 1)
        self.assertEqual(float(optimizer.state[parameter]['step']), 1)

    def test_changed_later_pack_refuses_before_its_update(self):
        self.assertTrue(hasattr(subject, 'execute_steps'), 'the bound trajectory loop is missing')
        packs = [dict(index=i, phase='warm' if i == 0 else 'measured', token_ids=[0, 1], target_ids=[1, 2],
                      positions=[[0, 0, 0], [1, 0, 0]], document_starts=[0]) for i in range(64)]
        applied = []
        def observe(index, row):
            packs[1]['token_ids'][0] = 3
        with self.assertRaisesRegex(ValueError, 'input'):
            subject.execute_steps(packs, step=lambda i, p: dict(index=i, applied_positions=2),
                                  record=lambda row: None, applied=applied.append, observe=observe)
        self.assertEqual(applied, [2])


class RunnerTrajectoryTests(unittest.TestCase):
    def test_trajectory_requires_matching_native_disk_wall(self):
        identity = dict(trajectory=dict(schema='reference-noise-floor-64-v1', arm='R1', comparison_id='a' * 32),
                        dispatch_resources={'disk_write_walls': [{'volume_root': 'B:/', 'maximum_write_bytes': 2 * 1024 ** 3}]})
        with self.assertRaisesRegex(ValueError, 'eight GiB'):
            runner.validate_trajectory_resources(identity)
        identity['dispatch_resources']['disk_write_walls'][0]['maximum_write_bytes'] = 8 * 1024 ** 3
        runner.validate_trajectory_resources(identity)

    def test_trajectory_is_explicit_and_binds_its_source_without_expanding_default_geometry(self):
        self.assertTrue(hasattr(runner, 'trajectory_mode'), 'the explicit trajectory worker selection is missing')
        self.assertFalse(runner.trajectory_mode({}))
        identity = {'trajectory': dict(schema='reference-noise-floor-64-v1', arm='Tsegmented', comparison_id='c' * 32),
                    'execution_mode': 'resident-segmented-capture'}
        self.assertEqual(runner.resource_limits(identity)['max_b_write_gib'], 8)
        self.assertEqual(runner.resource_limits({})['max_b_write_gib'], 2)
        reference = {'trajectory': dict(identity['trajectory'], arm='R1')}
        self.assertTrue(runner.trajectory_mode(reference))
        with self.assertRaises(ValueError):
            runner.trajectory_mode(dict(reference, execution_mode='resident-dynamic-capture'))
        self.assertTrue(runner.trajectory_mode(identity))
        self.assertIn('src/ember/infrastructure/tools/ember-restart-3b/cia_trajectory.py', runner.required_sources(identity))
        for value in ('unknown', True, None):
            with self.assertRaises(ValueError):
                runner.trajectory_mode(dict(identity, trajectory=value))
        with self.assertRaises(ValueError):
            runner.trajectory_mode({'trajectory': 'reference-noise-floor-64-v1'})
        geometry = dict(sequence_length=1024, documents_per_step=4, warm_steps=1, measured_steps=63)
        self.assertEqual(runner.geometry_counts(geometry, trajectory=True), (1024, 4, 1, 63))
        with self.assertRaises(ValueError):
            runner.geometry_counts(geometry)
        with self.assertRaises(ValueError):
            runner.geometry_counts(dict(geometry, measured_steps=62), trajectory=True)

    def test_reference_observer_reaches_the_real_forward_and_count_follows_update(self):
        self.assertIn('route_observer', inspect.signature(runner.measure_step).parameters)
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(8, 3)
                self.output = torch.nn.Linear(3, 8)
                self._cuda_execution = SimpleNamespace(cache=SimpleNamespace(
                    lease_count=0, miss_count=0, eviction_count=0, transfer_bytes=0, transfer_seconds=0.0))
            def candidate_step(self):
                return contextlib.nullcontext()
            def embed_text(self, tokens):
                return self.embedding(tokens)
            def forward(self, embedded, positions, *, route_observer=None, **kwargs):
                if route_observer is not None:
                    route_observer('observed')
                return self.output(embedded), ()
        model = Model()
        optimizer = torch.optim.AdamW(model.parameters(), foreach=False)
        pack = dict(token_ids=[0, 1], target_ids=[1, 2], positions=[[0, 0, 0], [1, 0, 0]],
                    document_starts=[0], phase='measured')
        seen = []
        row = runner.measure_step(model, optimizer, pack, device=torch.device('cpu'), route_observer=seen.append)
        self.assertEqual(seen, ['observed'])
        self.assertEqual(row['applied_positions'], 2)
        self.assertTrue(all(float(state['step']) == 1 for state in optimizer.state.values()))

    def test_worker_records_applied_trajectory_updates_if_later_diagnostics_fail(self):
        self.assertTrue(hasattr(runner, 'load_trajectory_module'), 'the authenticated trajectory dispatch is missing')
        from ember.governance.scripts import cia_conformance_resources
        from ember.model import ember_v0_decoder, ember_v0_contract
        run_id = 'a' * 32
        identity = dict(run_id=run_id, gpu_uuid='GPU-fixture', seed=2163,
                        trajectory=dict(schema='reference-noise-floor-64-v1', arm='Tsegmented', comparison_id='c' * 32),
                        execution_mode='resident-segmented-capture')
        prediction = dict(identity=identity)
        launch = {'launch': {'prediction_sha256': 'b' * 64, 'gpu_uuid': 'GPU-fixture'}}
        terminal = []
        def execute(**kwargs):
            kwargs['applied'](4096)
            raise RuntimeError('trajectory diagnostic fixture failed')
        with contextlib.ExitStack() as stack:
            for owner, name, value in (
                (cia_conformance_resources, 'require_owned_job', lambda *a, **k: None),
                (runner, 'verify_worker', lambda *a: None),
                (runner, 'load_prediction', lambda *a: (prediction, b'')),
                (runner, 'prepare_execution', lambda *a: ({}, {})),
                (runner, 'run_readonly', lambda *a, **k: SimpleNamespace(stdout='GPU-fixture')),
                (runner, 'load_trajectory_module', lambda: SimpleNamespace(run_trajectory_arm=execute)),
                (runner, '_write_new', lambda path, value: terminal.append(value)),
                (ember_v0_decoder, 'bind_triton_c_compiler', lambda: {}),
                (ember_v0_contract, 'validate_cia_architecture', lambda config: None),
                (torch.cuda, 'is_available', lambda: True),
                (torch.cuda, 'device_count', lambda: 1),
                (torch.cuda, 'get_device_properties', lambda device: SimpleNamespace(total_memory=24*1024**3)),
                (torch.cuda, 'set_per_process_memory_fraction', lambda *a: None),
            ):
                stack.enter_context(patch.object(owner, name, value))
            stack.enter_context(patch.object(Path, 'read_bytes', return_value=runner.canonical(launch)))
            with self.assertRaisesRegex(RuntimeError, 'trajectory diagnostic fixture'):
                runner.worker(Path('B:/fixture') / ('measurement-' + run_id) / 'launch.json')
        self.assertEqual(terminal[-1]['status'], 'failed')
        self.assertEqual(terminal[-1]['applied_positions'], 4096)


if __name__ == '__main__':
    unittest.main()
