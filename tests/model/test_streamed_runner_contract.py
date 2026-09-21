# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""K4 selection must reach the real caller and all three capture producers."""
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import torch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
TOOLS=ROOT/'src/ember/infrastructure/tools/ember-restart-3b'
spec=importlib.util.spec_from_file_location('k4_runner',TOOLS/'cia_step_runner.py')
runner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=runner;spec.loader.exec_module(runner)


class StreamedRunnerContract(unittest.TestCase):
    def test_native_and_captured_rows_share_independent_plan_binding(self):
        self.assertTrue(hasattr(runner,'step_experiment_fields'),'Row identity must not depend on the loss callback')
        binding=dict(plan_sha256='a'*64,candidate_function_id='1945-20260920-control')
        self.assertEqual(runner.step_experiment_fields(None,binding),binding)
        native=SimpleNamespace(loss_fn=lambda x,y: x)
        self.assertEqual(runner.step_experiment_fields(native,binding),binding)
        native.loss_fn.experiment_binding=dict(binding,plan_sha256='b'*64)
        with self.assertRaises(ValueError):runner.step_experiment_fields(native,binding)
    def test_selector_refuses_unknown_or_uncaptured_candidate(self):
        self.assertTrue(hasattr(runner,'training_head'),'Runner cannot represent K4')
        self.assertEqual(runner.training_head({}),'native')
        for identity in [{'training_head':'cce-document-v1'},
                         {'training_head':'other','execution_mode':'resident-dynamic-capture'}]:
            with self.assertRaises(ValueError):runner.training_head(identity)
        self.assertEqual(runner.training_head(dict(training_head='cce-document-v1',
                         execution_mode='resident-dynamic-capture')),'cce-document-v1')

    def test_bound_callback_uses_external_original_owner_and_full_denominator(self):
        self.assertTrue(hasattr(runner,'capture_loss_kwargs'),'Capture producers need one selected loss')
        import ember.model.ember_v0_streamed_loss as module
        original=module.document_streamed_loss;seen={}
        def inspect_call(hidden,owner,targets,lengths,denominator):
            seen.update(owner=owner,lengths=lengths,denominator=denominator)
            return hidden.sum()
        owner=torch.nn.Parameter(torch.ones(7,3))
        model=SimpleNamespace(_weight=lambda name:owner)
        try:
            module.document_streamed_loss=inspect_call
            selected=runner.capture_loss_kwargs(model,dict(training_head='cce-document-v1',
                execution_mode='resident-dynamic-capture'),(2,2,2,2))
            self.assertEqual(selected['head_output'],'hidden')
            selected['loss_fn'](torch.ones(8,3),torch.zeros(8,dtype=torch.long))
            self.assertIs(seen['owner'],owner)
            self.assertEqual((seen['lengths'],seen['denominator']),((2,2,2,2),8))
        finally:module.document_streamed_loss=original

    def test_all_real_capture_producers_bind_selected_loss(self):
        # Wiring check supplements the executed callback and decoder tests.
        for filename in ['cia_step_runner.py','cia_trajectory.py','cia_hour.py']:
            source=(TOOLS/filename).read_text(encoding='utf-8')
            self.assertTrue('**'+('' if filename=='cia_step_runner.py' else 'runner.')+
                          'capture_loss_kwargs(' in source,filename)
        self.assertIn('capture.loss(logits, targets)',(TOOLS/'cia_step_runner.py').read_text())


if __name__=='__main__':unittest.main()
