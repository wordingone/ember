# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('plan_test_runner',ROOT/'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py')
runner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=runner;spec.loader.exec_module(runner)
class PlanBinding(unittest.TestCase):
    def test_opened_plan_must_match_source_selector_and_geometry(self):
        self.assertTrue(hasattr(runner,'validate_experiment_plan'),'Producer cannot bind a frozen experiment plan')
        identity=dict(training_head='cce-document-v1',execution_mode='resident-dynamic-capture',
            geometry=dict(documents_per_step=4,sequence_length=1024),source_commit='a'*40,
            source_sha256={},optimizer={'kind':'fixture'},support={},seed=2163,data={})
        identity['source_sha256']={name:runner.file_sha256(ROOT/name) for name in runner.required_sources(identity)}
        plan=dict(candidate_function_id='1945-20260920-K4',geometry=dict(identity['geometry']),
            selectors=dict(training_head='cce-document-v1',execution_mode='resident-dynamic-capture',
                           local_routing_mode='batched',attention_backend='unforced',attention_recompute='none'),
            source_commit=identity['source_commit'],source_sha256=identity['source_sha256'],
            optimizer=identity['optimizer'],support={},seed=2163,data={})
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'plan.json'
            def bind(value):
                path.write_text(json.dumps(value),encoding='utf-8')
                return dict(identity,experiment_plan=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),candidate_function_id=plan['candidate_function_id']))
            runner.validate_experiment_plan(bind(plan))
            for field,value in [('source_commit','c'*40),('geometry',dict(documents_per_step=8,sequence_length=1024)),
                ('candidate_function_id','1945-20260920-J4'),('selectors',dict(plan['selectors'],training_head='native'))]:
                changed=copy.deepcopy(plan);changed[field]=value
                with self.subTest(field=field),self.assertRaises(ValueError):runner.validate_experiment_plan(bind(changed))
            bound=bind(plan);path.write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):runner.validate_experiment_plan(bound)
        with self.assertRaises(ValueError):runner.validate_experiment_plan(identity)
if __name__=='__main__':unittest.main()
