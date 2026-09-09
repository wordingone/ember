"""The closed purpose changes eligibility, never standalone launch authority."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cia_test_registry_gate', ROOT / 'src/ember/governance/scripts/registry_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ConformanceAuthority(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'configs/ember-cia-3b.json').read_text())
        self.goal, self.outcome = gate.load_goal_binding(ROOT)

    def check(self, purpose='numerical_conformance'):
        return gate.check_dispatch_authority(self.config, self.goal, self.outcome, purpose=purpose)

    def test_exact_candidate_is_eligible_for_conformance_only(self):
        self.assertTrue(self.check()[0])
        self.assertFalse(self.check('standard')[0])
        self.assertFalse(gate.check_dispatch_authority(self.config, self.goal, self.outcome)[0])

    def test_no_other_purpose_or_reference_uses_this_exception(self):
        for purpose in ('training', 'serving', '', None):
            with self.subTest(purpose=purpose):
                self.assertFalse(self.check(purpose)[0])
        for role in ('model_milestone', 'borrowed_reference', 'historical_only'):
            with self.subTest(role=role):
                self.config['authority']['artifact_class'] = role
                self.assertFalse(self.check()[0])

    def test_conservation_requirements_remain_binding(self):
        original = copy.deepcopy(self.config)
        changes = {
            'total_parameters': 2999999999,
            'native_capabilities': ['text'],
            'published_family_backbone': 'borrowed',
            'model_mediated_signals': ['teacher'],
            'goal_id': 'other',
            'next_executed_outcome': 'other',
            'execution_authority': 'allowed',
            'capability_credit': 'earned',
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                self.config = copy.deepcopy(original)
                self.config['authority'][key] = value
                self.assertFalse(self.check()[0])

    def test_standard_allowed_candidate_behavior_is_preserved(self):
        self.config['authority']['execution_authority'] = 'allowed'
        self.assertTrue(self.check('standard')[0])


if __name__ == '__main__':
    unittest.main()
