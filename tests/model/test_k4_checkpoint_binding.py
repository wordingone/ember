# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
TOOLS=ROOT/'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0,str(ROOT/'src'))
def load(file,name):
    spec=importlib.util.spec_from_file_location(name,TOOLS/file)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module
runner=load('cia_step_runner.py','k4_custody_runner');hour=load('cia_hour.py','k4_custody_hour')
trajectory=load('cia_trajectory.py','k4_custody_trajectory')
class HeadCustody(unittest.TestCase):
    def test_legacy_comparison_does_not_admit_declared_loss_as_native(self):
        reference=dict(source_sha256={},optimizer={})
        candidate=dict(reference,training_head='cce-document-v1')
        with self.assertRaisesRegex(ValueError,'declared.*licence'):
            trajectory.compare_start_identity(reference,candidate,arm='Tdynamic')
    def test_checkpoint_probe_different_loss_function_is_refused(self):
        identity=dict(source_commit='a'*40,source_sha256={},config_sha256='b'*64,
             data={},seed=1,support={},production_mixture={},execution_mode='resident-dynamic-capture')
        changed=dict(identity,training_head='cce-document-v1')
        with self.assertRaisesRegex(ValueError,'training head'):
            hour.validate_probe_inputs(runner,identity,changed)
    def test_checkpoint_probe_same_declared_loss_function_is_admitted(self):
        identity=dict(source_commit='a'*40,source_sha256={},config_sha256='b'*64,
             data={},seed=1,support={},production_mixture={},execution_mode='resident-dynamic-capture',
             training_head='cce-document-v1')
        hour.validate_probe_inputs(runner,identity,identity)
if __name__=='__main__':unittest.main()
