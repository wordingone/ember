# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU checks of explicit trajectory checkpoint admission and custody ordering."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'src/ember/infrastructure/tools/ember-restart-3b'
sys.path[:0] = [str(BASE),str(ROOT/'src')]
SOURCE = Path(os.environ.get('CIA_TRAJECTORY_CHECKPOINT_SOURCE',str(BASE)))
import torch
import checkpoint_artifacts as artifacts
import parameter_counter as counter
from ember.model import ember_v0_decoder

def load(name):
    spec = importlib.util.spec_from_file_location('checkpoint_emission_'+name,SOURCE/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

runner = real_runner = load('cia_step_runner')
hour = load('cia_hour')
trajectory = load('cia_trajectory')

class ChildEmissionAdmissionTests(unittest.TestCase):
    def identity(self, arm='R1'):
        value = dict(trajectory=dict(schema='reference-noise-floor-64-v1', arm=arm,
                                     comparison_id='a'*32, checkpoint_emission=True))
        if arm == 'Tfused':
            value['execution_mode'] = 'resident-dynamic-capture'
        return value

    def test_explicit_mode_binds_all_executed_checkpoint_helpers(self):
        self.assertTrue(callable(getattr(runner, 'trajectory_checkpoint_emission', None)))
        identity = self.identity()
        self.assertTrue(runner.trajectory_checkpoint_emission(identity))
        sources = runner.required_sources(identity)
        for name in ('cia_hour.py', 'checkpoint_artifacts.py', 'parameter_counter.py'):
            self.assertIn('src/ember/infrastructure/tools/ember-restart-3b/'+name, sources)
        self.assertEqual(len(sources), len(set(sources)))

    def test_resource_change_is_explicit_and_defaults_stay_fixed(self):
        ordinary = self.identity()
        del ordinary['trajectory']['checkpoint_emission']
        self.assertEqual(runner.resource_limits(ordinary)['wall_seconds'], 600)
        self.assertEqual(runner.resource_limits(ordinary)['max_b_write_gib'], 8)
        for arm in ('R1', 'Tfused'):
            with self.subTest(arm=arm):
                limits = runner.resource_limits(self.identity(arm))
                self.assertEqual(limits['wall_seconds'], 1800)
                self.assertEqual(limits['max_b_write_gib'], 32)
                self.assertEqual(limits['host_memory_bytes'], 40*runner.GIB)
                self.assertEqual(limits['total_gpu_bytes'], 20*runner.GIB)
                self.assertEqual(limits['min_b_free_bytes'], 250*runner.GIB)

    def test_non_true_emission_and_unrelated_modes_refuse(self):
        self.assertTrue(callable(getattr(runner, 'trajectory_checkpoint_emission', None)))
        for value in (False, None, 1, 'true', {}):
            identity = self.identity()
            identity['trajectory']['checkpoint_emission'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.trajectory_mode(identity)
        with self.assertRaises(ValueError):
            runner.trajectory_checkpoint_emission({'checkpoint_emission': True})
        self.assertFalse(runner.trajectory_checkpoint_emission({}))

    def test_native_disk_wall_must_match_emission_reservation(self):
        identity = self.identity()
        identity['dispatch_resources'] = dict(disk_write_walls=[dict(volume_root='B:/', maximum_write_bytes=8*runner.GIB)])
        with self.assertRaises(ValueError):
            runner.validate_trajectory_resources(identity)
        identity['dispatch_resources']['disk_write_walls'][0]['maximum_write_bytes'] = 32*runner.GIB
        runner.validate_trajectory_resources(identity)
        identity['dispatch_resources']['disk_write_walls'][0]['volume_root'] = 'C:/'
        with self.assertRaises(ValueError):
            runner.validate_trajectory_resources(identity)

class SharedCheckpointPublisherTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(hour, 'checkpoint_publisher', None)))
        self.assertTrue(callable(getattr(hour, 'verify_checkpoint_restore', None)))
        self.events = []
        self.runner = SimpleNamespace(ROOT=ROOT, CONFIG='configs/fixture.json', GIB=1024**3,
                                      file_sha256=lambda path: 'a'*64,
                                      hidden_kwargs=lambda: {},
                                      _write_new=lambda path, value: self.events.append((path, value)))
        self.parameter = torch.nn.Parameter(torch.ones(2))
        self.optimizer = torch.optim.AdamW([self.parameter], foreach=False)
        self.inventory = {'dense': self.parameter}
        self.identity = dict(seed=1945, config_sha256='b'*64,
                             source_sha256={'src/ember/model/ember_v0_contract.py': 'c'*64})
        self.helper = Path.home()/'.codex/headless-python.ps1'
        self.binding = dict(launch=dict(helpers={str(self.helper.resolve()): 'a'*64}))

    def test_counter_refusal_propagates_and_does_not_publish_success(self):
        publish, counts = hour.checkpoint_publisher(self.runner, object(), self.optimizer, self.inventory,
            self.identity, self.binding, Path('fixture'), torch.device('cuda'))
        def writer(model, optimizer, target, **kwargs):
            kwargs['pre_publish_verifier'](target, {})
            self.fail('Counter refusal must prevent this point')
        with patch.object(torch.cuda, 'synchronize'), patch.object(torch.cuda, 'get_rng_state', return_value=torch.ones(1)), \
                patch.object(artifacts, 'write_checkpoint_artifacts', side_effect=writer), \
                patch.object(hour.subprocess, 'run', return_value=SimpleNamespace(returncode=2, stderr=b'counter refused')):
            with self.assertRaisesRegex(ValueError, 'independent checkpoint counter refused'):
                publish('zero-parent', steps=0, tokens=0, cursor=dict(shard_index=0, token_offset=0))
        self.assertEqual(self.events, [])

    def test_sparse_counts_are_copied_and_existing_codec_bounds_are_preserved(self):
        seen = {}
        publish, counts = hour.checkpoint_publisher(self.runner, object(), self.optimizer, self.inventory,
            self.identity, self.binding, Path('fixture'), torch.device('cuda'))
        counts.update(dense=64, sparse=17)
        def writer(model, optimizer, target, **kwargs):
            seen.update(kwargs)
            return dict(checkpoint_manifest_sha256='d'*64)
        self.parameter.grad = torch.ones_like(self.parameter)
        with patch.object(torch.cuda, 'synchronize'), patch.object(torch.cuda, 'get_rng_state', return_value=torch.ones(1)), \
                patch.object(artifacts, 'write_checkpoint_artifacts', side_effect=writer):
            child = publish('trained-child', steps=64, tokens=262144,
                            cursor=dict(shard_index=8, token_offset=262144), parent=Path('fixture/zero-parent'))
        counts['sparse'] = 18
        self.assertEqual(seen['cia_owner_update_counts'], dict(dense=64, sparse=17))
        self.assertEqual(seen['data_cursor'], dict(shard='8', record_index=262144, global_step=64, tokens_seen=262144))
        self.assertEqual(seen['max_serialized_bytes'], 10*self.runner.GIB)
        self.assertEqual(seen['max_transient_scratch_bytes'], 10*self.runner.GIB)
        self.assertEqual(seen['host_commit_reserve_bytes'], 16*self.runner.GIB)
        self.assertIsNone(self.parameter.grad)
        self.assertEqual(child['checkpoint_manifest_sha256'], 'd'*64)

    def test_changed_counter_launcher_refuses_before_codec_or_cuda(self):
        self.binding['launch']['helpers'][str(self.helper.resolve())] = 'e'*64
        with patch.object(artifacts, 'write_checkpoint_artifacts') as writer, patch.object(torch.cuda, 'synchronize') as sync:
            with self.assertRaisesRegex(ValueError, 'launcher differs'):
                hour.checkpoint_publisher(self.runner, object(), self.optimizer, self.inventory,
                    self.identity, self.binding, Path('fixture'), torch.device('cuda'))
        writer.assert_not_called()
        sync.assert_not_called()

    def test_reopened_state_disagreement_refuses_even_when_cursor_matches(self):
        child = dict(data_cursor=dict(global_step=64, tokens_seen=262144))
        def independent(*args, **kwargs):
            kwargs['_facts'].update(parameter='expected', optimizer='expected')
        with patch.object(artifacts, 'load_checkpoint_artifacts', return_value=child), \
                patch.object(artifacts, 'capture_cia_placed_optimizer_state', return_value={'state': {}}), \
                patch.object(artifacts, '_cia_lineage_facts', return_value=dict(parameter='changed', optimizer='expected')), \
                patch.object(counter, '_cia_realization_receipt', side_effect=independent):
            with self.assertRaisesRegex(ValueError, 'restored model or optimizer differs'):
                hour.verify_checkpoint_restore(self.runner, object(), self.optimizer, self.inventory,
                                               self.identity, Path('fixture'), child)

class TrajectoryEmissionTests(unittest.TestCase):
    def execute(self, *, free_gib=282, fail_restore=False, emission=True, captured=False, start_offset=0):
        self.events, self.applied, self.written, self.counts = [], [], {}, {}
        dense = torch.nn.Parameter(torch.ones(1))
        sparse = torch.nn.Parameter(torch.ones(1))
        inventory = dict(dense=dense, sparse=sparse)
        model = SimpleNamespace(materialize_cpu=lambda **kwargs: model)
        def clear(**kwargs):
            self.events.append('clear')
            for p in inventory.values():
                p.grad = None
        optimizer = SimpleNamespace(param_groups=[dict(params=list(inventory.values()))], zero_grad=clear)
        capture = SimpleNamespace(zero_grad=lambda:self.events.append('capture-clear'),
            capture=lambda **k:self.events.append('capture-build'),receipt=lambda:{},
            invalidate=lambda:self.events.append('capture-invalidate'))
        model.bind_segmented_capture = lambda **k:capture
        def publish(name, **kwargs):
            self.events.append(name)
            if name == 'trained-child':
                self.child_args = dict(kwargs, counts=dict(self.counts))
            clear()
            return dict(checkpoint_manifest_sha256=('a' if name == 'zero-parent' else 'b')*64,
                        data_cursor=dict(global_step=kwargs['steps'],tokens_seen=kwargs['tokens']))
        def publisher(*args):
            return publish, self.counts
        def verify(*args):
            self.events.append('restore')
            if fail_restore:
                raise ValueError('restored model differs')
        hour = SimpleNamespace(checkpoint_publisher=publisher, verify_checkpoint_restore=verify)
        def measure(model, optimizer, pack, **kwargs):
            i = pack['index']
            self.events.append('update-'+str(i+1))
            dense.grad = torch.ones_like(dense)
            sparse.grad = torch.ones_like(sparse) if i % 2 == 0 else None
            return dict(index=i, applied_positions=4096, phase=pack['phase'], loss=1., wall_seconds=.1)
        def write(path,value):
            self.written[path.name] = value
            self.events.append(path.name)
        runner = SimpleNamespace(POPULATION=2, CLAIM='CPU fixture', GIB=1024**3,
            LIMITS=dict(min_b_free_bytes=250*1024**3), verify_prepared_inputs=real_runner.verify_prepared_inputs,
            trajectory_checkpoint_emission=real_runner.trajectory_checkpoint_emission,
            resource_limits=real_runner.resource_limits,
            headroom=lambda: dict(free_disk_bytes=dict(B=free_gib*1024**3)),
            load_hour_module=lambda: hour, document_lengths=lambda *a: (1024,)*4,
            routing_buffers=lambda *a:SimpleNamespace(collector={},raw=None,capturing=False),
            prepare_model=lambda *a, **k: (inventory,optimizer), local_routing_mode=lambda i: 'per-chunk',
            expert_owner_index=lambda i: {}, measure_step=measure, _write_new=write)
        identity = dict(seed=1945, optimizer={}, trajectory=dict(schema='reference-noise-floor-64-v1',arm='R1',comparison_id='c'*32),
            data=dict(cursor=dict(shard_index=8,token_offset=start_offset),shard_ledger_sha256='d'*64),
            support=dict(experts=[]), geometry={}, source_commit='e'*40, source_sha256={}, run_id='f'*32)
        if emission:
            identity['trajectory']['checkpoint_emission'] = True
        arm_name = 'Tdynamic' if captured else 'R1'
        identity['trajectory']['arm'] = arm_name
        mode = 'resident-dynamic-capture' if captured else None
        if mode:
            identity['execution_mode'] = mode
        # Exercise the production pack producer; ordinary trajectories bind the
        # final cursor once, rather than placing cursor_after in each pack.
        def next_episode(*, shard_index, token_offset, sequence_length):
            return (dict(token_ids=[0]*sequence_length,target_ids=[1]*sequence_length),
                    dict(shard_index=shard_index,token_offset=token_offset+sequence_length))
        stream = SimpleNamespace(check_cursor_span=lambda **k:{},next_episode=next_episode)
        data = dict(identity['data'],receipt_sha256='0'*64,tokenizer_sha256='0'*64)
        geometry = dict(sequence_length=1024,documents_per_step=4,warm_steps=1,measured_steps=63)
        with patch.object(real_runner,'open_input_stream',return_value=(stream,Path('receipt'),Path('tokenizer'),None)), \
                patch.object(real_runner,'file_sha256',return_value='0'*64):
            prepared = real_runner.prepare_inputs(data,geometry,trajectory=True)
        self.assertTrue(all('cursor_after' not in pack for pack in prepared['packs']))
        real_runner.verify_prepared_inputs(prepared)
        def snapshot(inventory,custody,*,update,budget_bytes):
            self.assertIsNotNone(dense.grad)
            self.events.append('snapshot-'+str(update))
            return dict(bytes=2,update=update,tensors={})
        with contextlib.ExitStack() as stack:
            for obj,name,value in (
                (ember_v0_decoder,'CIADecoder',lambda **k:model),
                (trajectory,'inventory_sha256',lambda i:'0'*64),
                (trajectory,'snapshot_plan',lambda i:dict(parameter_bytes=2,updates=[1,64])),
                (trajectory,'ReferenceRouting',lambda:SimpleNamespace(finish=lambda:{})),
                (trajectory,'routing_metrics',lambda *a,**k:{}),
                (trajectory,'device_routing',lambda **k:{}),
                (trajectory,'_update_delta',lambda *a,**k:0.),
                (trajectory,'save_snapshot',snapshot),
                (trajectory,'_stream_row',lambda stream,row:None),
                (torch.cuda,'synchronize',lambda *a:None),
            ):
                stack.enter_context(patch.object(obj,name,value))
            return trajectory._run_arm(runner=runner,config={},prepared=prepared,
                prediction=dict(identity=identity),binding=dict(launch=dict(prediction_sha256='2'*64)),
                custody=Path('B:/fixture'),device=torch.device('cpu'),compiler={},name=arm_name,mode=mode,
                row_stream=io.BytesIO(),metric_stream=io.BytesIO(),applied=self.applied.append)

    def test_checkpoints_follow_updates_and_preserve_snapshots_and_sparse_counts(self):
        result = self.execute()
        self.assertIn('zero-parent',self.events)
        self.assertLess(self.events.index('zero-parent'),self.events.index('update-1'))
        self.assertLess(self.events.index('snapshot-64'),self.events.index('trained-child'))
        self.assertLess(self.events.index('restore'),self.events.index('t2-arm-R1.json'))
        self.assertEqual(self.child_args['steps'],64)
        self.assertEqual(self.child_args['tokens'],262144)
        self.assertEqual(self.child_args['cursor'],dict(shard_index=8,token_offset=262144))
        self.assertEqual(self.child_args['counts'],dict(dense=64,sparse=32))
        self.assertEqual(sum(self.applied),262144)
        self.assertEqual(result['zero_parent_manifest_sha256'],'a'*64)
        self.assertEqual(result['child_manifest_sha256'],'b'*64)

    def test_checkpoint_cursor_preserves_nonzero_input_origin(self):
        self.execute(start_offset=4096)
        self.assertEqual(self.child_args['cursor'],dict(shard_index=8,token_offset=266240))
        self.assertEqual(self.child_args['tokens'],262144)

    def test_restore_failure_keeps_applied_count_without_successful_arm_record(self):
        with self.assertRaisesRegex(ValueError,'restored model differs'):
            self.execute(fail_restore=True)
        self.assertEqual(sum(self.applied),262144)
        self.assertNotIn('t2-arm-R1.json',self.written)

    def test_inadequate_reservation_refuses_before_any_checkpoint_or_update(self):
        with self.assertRaisesRegex(ValueError,'reservation'):
            self.execute(free_gib=281)
        self.assertEqual(self.applied,[])
        self.assertNotIn('zero-parent',self.events)

    def test_ordinary_trajectory_does_not_publish_or_need_checkpoint_reservation(self):
        result = self.execute(free_gib=250,emission=False)
        self.assertNotIn('zero-parent',self.events)
        self.assertNotIn('child_manifest_sha256',result)
        self.assertEqual(sum(self.applied),262144)

    def test_captured_arm_preserves_both_snapshots_before_capture_storage_release(self):
        self.execute(captured=True)
        self.assertLess(self.events.index('snapshot-1'),self.events.index('capture-clear'))
        self.assertLess(self.events.index('snapshot-64'),self.events.index('capture-invalidate'))
        self.assertLess(self.events.index('capture-invalidate'),self.events.index('trained-child'))
        self.assertEqual(self.child_args['counts'],dict(dense=64,sparse=32))

if __name__ == '__main__':
    torch.set_num_threads(1)
    unittest.main()
