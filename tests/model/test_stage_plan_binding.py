# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""One immutable plan must span actual trajectory/measurement/hour source sets."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
ENTRY=ROOT/'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
spec=importlib.util.spec_from_file_location('stage_plan_subject',str(ENTRY))
runner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=runner;spec.loader.exec_module(runner)
runner.ROOT=ROOT

class StagePlan(unittest.TestCase):
    def setUp(self):
        base=dict(training_head='cce-document-v1',execution_mode='resident-dynamic-capture',
                  source_commit='a'*40,geometry=dict(documents_per_step=4,sequence_length=1024),
                  optimizer=dict(name='AdamW',fused=True),support={},seed=2163,data={})
        self.stages=[dict(base,trajectory=dict(schema='reference-noise-floor-64-v1',arm='Tfused',
                           comparison_id='b'*32,checkpoint_emission=True)),
                     dict(base,measurement=dict(schema='governed-1024-v1',arm='fused')),
                     dict(base,hour=dict(schema='governed-hour-v1',arm='treatment',
                           minimum_wall_seconds=3600,minimum_measured_steps=1024))]
        for stage in self.stages:
            stage['source_sha256']={name:runner.file_sha256(ROOT/name) for name in runner.required_sources(stage)}
        self.closure={name:digest for stage in self.stages for name,digest in stage['source_sha256'].items()}
        self.plan={key:base[key] for key in ('source_commit','optimizer','support','seed','data','geometry')}
        self.plan.update(candidate_function_id='1945-20260920-K4',source_sha256=self.closure,
            selectors=dict(training_head='cce-document-v1',execution_mode='resident-dynamic-capture',
                           local_routing_mode='batched',attention_backend='unforced',attention_recompute='none'))
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'plan.json'
    def bind(self,plan=None):
        self.path.write_text(json.dumps(self.plan if plan is None else plan),encoding='utf-8')
        return dict(path=str(self.path),sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
                    candidate_function_id=self.plan['candidate_function_id'])
    def test_one_file_and_digest_accept_all_three_real_source_sets(self):
        binding=self.bind();raw=self.path.read_bytes()
        self.assertGreater(len(set(tuple(sorted(s['source_sha256'])) for s in self.stages)),1)
        for stage in self.stages:
            runner.validate_experiment_plan(dict(stage,experiment_plan=binding))
            self.assertEqual(self.path.read_bytes(),raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),binding['sha256'])
    def test_missing_active_source_refuses(self):
        plan=copy.deepcopy(self.plan);del plan['source_sha256'][next(iter(self.stages[1]['source_sha256']))]
        with self.assertRaises(ValueError):runner.validate_experiment_plan(dict(self.stages[1],experiment_plan=self.bind(plan)))
    def test_execution_source_digest_must_match_plan(self):
        stage=copy.deepcopy(self.stages[1]);stage['source_sha256'][next(iter(stage['source_sha256']))]='0'*64
        with self.assertRaises(ValueError):runner.validate_experiment_plan(dict(stage,experiment_plan=self.bind()))
    def test_inactive_hour_source_is_opened_and_checked(self):
        inactive=next(iter(set(self.stages[2]['source_sha256'])-set(self.stages[1]['source_sha256'])))
        plan=copy.deepcopy(self.plan);plan['source_sha256'][inactive]='0'*64
        with self.assertRaises(ValueError):runner.validate_experiment_plan(dict(self.stages[1],experiment_plan=self.bind(plan)))
    def test_unknown_source_key_refuses(self):
        plan=copy.deepcopy(self.plan);plan['source_sha256']['../unbound.py']='0'*64
        with self.assertRaises(ValueError):runner.validate_experiment_plan(dict(self.stages[1],experiment_plan=self.bind(plan)))
    def test_resolved_source_outside_root_refuses(self):
        binding=self.bind();original=Path.resolve
        name=next(iter(self.closure));escaped=ROOT.parent/'unbound.py'
        def resolve(path,*args,**kwargs):
            if path==ROOT/name:return escaped
            return original(path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve),self.assertRaises(ValueError):
            runner.validate_experiment_plan(dict(self.stages[1],experiment_plan=binding))
if __name__=='__main__':unittest.main()
