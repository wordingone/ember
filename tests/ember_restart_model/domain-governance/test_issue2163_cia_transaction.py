# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tiny physical transaction fixtures; no full-model qualification credit."""
import hashlib
import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import checkpoint_artifacts as artifacts
import parameter_counter as counter
from ember.model import ember_v0_inventory as cia_inventory, ember_v0_decoder as cia_decoder
from ember.model.ember_v0_contract import cia_architecture_config, validate_cia_architecture


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'published'
        self.config_path = Path(self.temp.name)/'config.json'
        self.config_path.write_text(json.dumps(cia_architecture_config()),encoding='utf-8')
        specs = (cia_inventory.TensorSpec('embedding.weight', (8,), 'core'),) + tuple(
            cia_inventory.TensorSpec(f'experts.{i}.weight', (8,), 'expert', i) for i in range(25))
        self.parameters = {spec.name: torch.nn.Parameter(torch.full(spec.shape, i, dtype=torch.bfloat16))
                           for i, spec in enumerate(specs)}
        self.model = type('Fixture', (), {'parameter_inventory': lambda _: self.parameters})()
        self.model.config = validate_cia_architecture(cia_architecture_config())
        self.model._cuda_execution = None
        dispatch = patch.object(cia_decoder,'CIADecoder',type(self.model))
        dispatch.start()
        self.addCleanup(dispatch.stop)
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=.01, foreach=False)
        self.identity = {'param_groups': [{'params': list(self.parameters), 'hyperparameters': {'amsgrad':False}}]}
        for target, attr, value in ((cia_inventory, 'equation_inventory', specs),
                                    (artifacts, 'cia_optimizer_identity', self.identity)):
            mocking = patch.object(target, attr, return_value=value)
            mocking.start()
            self.addCleanup(mocking.stop)
        self.kwargs = dict(launch_seed=7, rng_state={'cpu': torch.get_rng_state(), 'cuda': torch.empty(0, dtype=torch.uint8)},
            data_cursor={'shard':'fixture', 'record_index':0, 'global_step':0, 'tokens_seen':0},
            model_config_sha256=hashlib.sha256(self.config_path.read_bytes()).hexdigest(), contract_sha256='2'*64,
            expert_genesis_sha256={},
            max_serialized_bytes=4*1024*1024, max_transient_scratch_bytes=1024*1024,
            pre_publish_verifier=self.verifier)

    def verifier(self, candidate, receipt):
        result = counter.execute_counter(model_config=self.config_path,checkpoint_manifest=candidate/'checkpoint-manifest.json',active_expert='all')
        (candidate/'parameter-counter-receipt.json').write_text(json.dumps(result), encoding='utf-8')
        return result

    def publish(self):
        return artifacts.write_checkpoint_artifacts(self.model, self.optimizer, self.root, **self.kwargs)

    def test_publish_reopen_preserves_all_25_experts_and_replay(self):
        receipt = self.publish()
        original = {name: value.detach().clone() for name,value in self.parameters.items()}
        with torch.no_grad():
            for value in self.parameters.values(): value.add_(50)
        replay = artifacts.load_checkpoint_artifacts(self.model, self.optimizer, self.root, receipt, max_transient_scratch_bytes=1024*1024)
        for name, value in self.parameters.items(): torch.testing.assert_close(value, original[name], rtol=0, atol=0)
        self.assertEqual(replay['data_cursor'], self.kwargs['data_cursor'])

    def test_wrong_optimizer_identity_refused_before_parameter_mutation(self):
        receipt = self.publish()
        self.identity['param_groups'][0]['params'].reverse()
        original = {name: value.detach().clone() for name,value in self.parameters.items()}
        with self.assertRaisesRegex(ValueError, 'identity'):
            artifacts.load_checkpoint_artifacts(self.model, self.optimizer, self.root, receipt, max_transient_scratch_bytes=1024*1024)
        for name,value in self.parameters.items(): torch.testing.assert_close(value, original[name], rtol=0, atol=0)
        self.assertEqual(dict(self.optimizer.state), {})

    def test_missing_25th_object_prevents_admission(self):
        called = []
        def incomplete(candidate, receipt):
            called.append(True)
            index = json.loads((candidate/receipt['expert_index']['path']).read_bytes())
            (candidate/'objects'/(index['experts'][24]['sha256']+'.pt')).unlink()
            return self.verifier(candidate, receipt)
        self.kwargs['pre_publish_verifier'] = incomplete
        with self.assertRaisesRegex(ValueError, 'closure'):
            self.publish()
        self.assertEqual(called, [True])
        self.assertFalse(self.root.exists())


    def test_native_moments_and_frozen_membership_restore_without_dtype_conversion(self):
        parameter = self.parameters['experts.24.weight']
        parameter.requires_grad_(False)
        self.optimizer.state[parameter] = {'step':torch.tensor(3.),
            'exp_avg':torch.full_like(parameter,.25), 'exp_avg_sq':torch.full_like(parameter,.5)}
        receipt = self.publish()
        self.optimizer.state.clear()
        artifacts.load_checkpoint_artifacts(self.model,self.optimizer,self.root,receipt,
            max_transient_scratch_bytes=1024*1024)
        state=self.optimizer.state[parameter]
        self.assertEqual(state['step'].dtype,torch.float32)
        self.assertEqual(state['exp_avg'].dtype,torch.bfloat16)
        torch.testing.assert_close(state['exp_avg'],torch.full_like(parameter,.25),rtol=0,atol=0)
        self.assertFalse(parameter.requires_grad)
        self.assertEqual(len(self.optimizer.param_groups[0]['params']),26)

    def test_reopen_requires_caller_bound_before_component_deserialization(self):
        receipt=self.publish()
        with patch.object(artifacts,'read_cia_core_object',side_effect=AssertionError('deserialized above caller bound')):
            with self.assertRaisesRegex(ValueError,'caller byte bound'):
                artifacts.load_checkpoint_artifacts(self.model,self.optimizer,self.root,receipt,
                    max_transient_scratch_bytes=1)

    def test_unfinished_paging_state_refused_before_candidate_creation(self):
        from types import SimpleNamespace
        self.model._cuda_execution=SimpleNamespace(cache=SimpleNamespace(
            active=False,pending=1,entries={},leased=set(),poisoned=False))
        with self.assertRaisesRegex(ValueError,'quiescent'):
            self.publish()
        self.assertFalse(self.root.parent.joinpath('.checkpoint-quarantine').exists())

    def test_runtime_update_during_capture_refuses_publication(self):
        original=artifacts.write_cia_expert_index
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            with torch.no_grad(): self.parameters['embedding.weight'].add_(1)
            return result
        with patch.object(artifacts,'write_cia_expert_index',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed during checkpoint capture'):
                self.publish()
        self.assertFalse(self.root.exists())


    def test_genesis_map_is_derived_from_objects_without_qualification(self):
        receipt=self.publish()
        index=json.loads((self.root/receipt['expert_index']['path']).read_bytes())
        self.assertEqual(receipt['expert_genesis_sha256'],{str(i):record['sha256'] for i,record in enumerate(index['experts'])})
        self.assertEqual(receipt['qualification'],{'clean_genesis':False,'trained':False,'served':False})

    def test_caller_genesis_map_cannot_replace_actual_zero_step_objects(self):
        self.kwargs['expert_genesis_sha256']={str(i):'3'*64 for i in range(25)}
        with self.assertRaisesRegex(ValueError,'genesis map differs'):
            self.publish()
        self.assertFalse(self.root.exists())

    def test_descendant_cursor_requires_verified_parent_consumer(self):
        self.kwargs['data_cursor'].update(global_step=1,tokens_seen=8)
        with self.assertRaisesRegex(ValueError,'verified parent-lineage'):
            self.publish()
        self.assertFalse(self.root.parent.joinpath('.checkpoint-quarantine').exists())

    def prepare_first_descendant(self):
        parent = self.publish()
        parent_root = self.root
        self.root = self.root.parent / 'descendant'
        parameter = self.parameters['embedding.weight']
        parameter.grad = torch.ones_like(parameter)
        self.optimizer.step()
        self.optimizer.zero_grad(set_to_none=True)
        self.kwargs['data_cursor'] = dict(self.kwargs['data_cursor'], global_step=1)
        self.kwargs['cia_parent_checkpoint'] = parent_root
        return parent_root, parent

    def test_first_descendant_reopens_admitted_parent_and_preserves_zero_tokens(self):
        parent_root, parent = self.prepare_first_descendant()
        receipt = self.publish()
        self.assertEqual(receipt['data_cursor']['tokens_seen'], 0)
        self.assertEqual(receipt['expert_genesis_sha256'], parent['expert_genesis_sha256'])
        self.assertEqual(receipt['lineage']['parent_manifest_sha256'], parent['checkpoint_manifest_sha256'])
        self.assertEqual(receipt['lineage']['updated_parameters'], ['embedding.weight'])
        self.assertEqual(receipt['lineage']['updated_parameter_elements'], 8)
        expected = self.parameters['embedding.weight'].detach().clone()
        moments = self.optimizer.state[self.parameters['embedding.weight']]['exp_avg'].clone()
        with torch.no_grad(): self.parameters['embedding.weight'].add_(50)
        self.optimizer.state.clear()
        replay = artifacts.load_checkpoint_artifacts(self.model,self.optimizer,self.root,receipt,
            max_transient_scratch_bytes=1024*1024)
        torch.testing.assert_close(self.parameters['embedding.weight'],expected,rtol=0,atol=0)
        torch.testing.assert_close(self.optimizer.state[self.parameters['embedding.weight']]['exp_avg'],moments,rtol=0,atol=0)
        self.assertEqual(replay['data_cursor'],self.kwargs['data_cursor'])

    def test_first_descendant_refuses_unadmitted_parent(self):
        parent_root, _ = self.prepare_first_descendant()
        (parent_root/'parameter-counter-receipt.json').unlink()
        with self.assertRaisesRegex(ValueError,'admitted parent'):
            self.publish()

    def test_first_descendant_refuses_changed_parent_object(self):
        parent_root, parent = self.prepare_first_descendant()
        path = parent_root/'objects'/(parent['core']['sha256']+'.pt')
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ValueError): self.publish()

    def test_first_descendant_refuses_second_descendant(self):
        self.prepare_first_descendant()
        self.publish()
        self.kwargs['cia_parent_checkpoint'] = self.root
        self.root = self.root.parent/'second-descendant'
        self.kwargs['data_cursor']['global_step'] = 2
        with self.assertRaisesRegex(ValueError,'zero-step parent'):
            self.publish()

    def test_first_descendant_refuses_unadvanced_optimizer_clock(self):
        self.prepare_first_descendant()
        self.optimizer.state.clear()
        with self.assertRaisesRegex(ValueError,'inactive parameter bytes'):
            self.publish()

    def test_first_descendant_refuses_cursor_regression(self):
        self.prepare_first_descendant()
        self.kwargs['data_cursor']['tokens_seen'] = -1
        with self.assertRaises(ValueError): self.publish()

    def test_first_descendant_refuses_v2_parent_manifest(self):
        parent_root, _ = self.prepare_first_descendant()
        path = parent_root/'checkpoint-manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['schema_version'] = 'ember-sparse-checkpoint-v1'
        path.write_text(json.dumps(manifest),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'zero-step parent'): self.publish()

    def test_first_descendant_refuses_parent_counter_drift(self):
        parent_root, _ = self.prepare_first_descendant()
        path=parent_root/'parameter-counter-receipt.json'
        receipt=json.loads(path.read_bytes())
        receipt['counter_sha256']='3'*64
        path.write_text(json.dumps(receipt),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'counter receipt differs'): self.publish()

    def test_first_descendant_refuses_parent_rng_even_with_recomputed_counter(self):
        parent_root, _ = self.prepare_first_descendant()
        manifest_path=parent_root/'checkpoint-manifest.json'
        manifest=json.loads(manifest_path.read_bytes())
        replay_path=parent_root/'replay-state.pt'
        replay=torch.load(replay_path,weights_only=True)
        replay['rng_state']['cpu']=torch.zeros(1,dtype=torch.uint8)
        torch.save(replay,replay_path)
        raw=replay_path.read_bytes()
        manifest['replay']['sha256']=hashlib.sha256(raw).hexdigest()
        manifest['replay']['bytes']=len(raw)
        manifest['rng_state_sha256']['cpu']=hashlib.sha256(bytes([0])).hexdigest()
        manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
        self.verifier(parent_root,{})
        with self.assertRaisesRegex((ValueError,RuntimeError),'RNG|state'):
            self.publish()

    def test_first_descendant_refuses_changed_inactive_expert(self):
        self.prepare_first_descendant()
        with torch.no_grad(): self.parameters['experts.24.weight'].add_(1)
        with self.assertRaisesRegex(ValueError,'inactive parameter bytes'): self.publish()

    def test_first_descendant_refuses_parent_contract_mismatch(self):
        self.prepare_first_descendant()
        self.kwargs['contract_sha256']='3'*64
        with self.assertRaisesRegex(ValueError,'contract_sha256 differ'): self.publish()

    def test_first_descendant_loader_reopens_parent_before_runtime_mutation(self):
        parent_root, parent = self.prepare_first_descendant()
        receipt=self.publish()
        path=parent_root/'objects'/(parent['core']['sha256']+'.pt')
        path.write_bytes(path.read_bytes()+b'changed')
        original={name:value.detach().clone() for name,value in self.parameters.items()}
        with self.assertRaises(ValueError):
            artifacts.load_checkpoint_artifacts(self.model,self.optimizer,self.root,receipt,
                max_transient_scratch_bytes=1024*1024)
        for name,value in self.parameters.items(): torch.testing.assert_close(value,original[name],rtol=0,atol=0)

    def test_first_descendant_restore_checks_caller_bound_before_parent_read(self):
        self.prepare_first_descendant()
        receipt=self.publish()
        with patch.object(counter,'_cia_parent_snapshot',side_effect=AssertionError('parent opened before caller bound')):
            with self.assertRaisesRegex(ValueError,'caller byte bound'):
                artifacts.load_checkpoint_artifacts(self.model,self.optimizer,self.root,receipt,max_transient_scratch_bytes=1)

    def test_first_descendant_counter_recomputes_declared_update_support(self):
        self.prepare_first_descendant()
        self.publish()
        path=self.root/'checkpoint-manifest.json'
        manifest=json.loads(path.read_bytes())
        manifest['lineage']['updated_parameters']=['experts.24.weight']
        path.write_text(json.dumps(manifest),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'lineage differs'):
            counter.execute_counter(model_config=self.config_path,checkpoint_manifest=path,active_expert='all')


    def test_isolated_counter_reaches_cia_inventory_validation(self):
        self.publish()
        arguments=['-I',str(ROOT/'src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py'),
            '--model-config',str(self.config_path),'--checkpoint-manifest',str(self.root/'checkpoint-manifest.json'),
            '--active-expert','all']
        options={}
        if os.name == 'nt':
            launcher=os.environ.get('EMBER_HEADLESS_PYTHON_LAUNCHER')
            if not launcher: self.skipTest('explicit headless Python launcher required on Windows')
            command=['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-File',launcher,'--',*arguments]
            startup=subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow=subprocess.SW_HIDE
            options={'creationflags':subprocess.CREATE_NO_WINDOW,'startupinfo':startup}
        else:
            command=[sys.executable,*arguments]
        completed=subprocess.run(command,shell=False,capture_output=True,text=True,timeout=30,**options)
        # The independent process uses the actual full CIA inventory. This tiny
        # physical fixture must be refused for inventory, never qualified.
        self.assertNotEqual(completed.returncode,0)
        self.assertIn('tensor inventory mismatch',completed.stderr)
        self.assertNotIn('ModuleNotFoundError',completed.stderr)


if __name__ == '__main__':
    unittest.main()
