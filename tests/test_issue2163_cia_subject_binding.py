# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ember.governance.scripts.cia_conformance import build_subject_binding, verify_subject_binding, verify_loaded_sources


class SubjectBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = patch("ember.governance.scripts.cia_conformance.runtime_identity", return_value={"test_runtime": "fixture; not runtime qualification"})
        runtime.start()
        cls.addClassCleanup(runtime.stop)
        daemon = patch('ember.governance.scripts.cia_conformance.daemon_identity', return_value={'test_daemon': 'fixture; not authenticated dispatch'})
        daemon.start()
        cls.addClassCleanup(daemon.stop)
        cls.binding = build_subject_binding(ROOT)

    def test_current_exact_subject_recomputes(self):
        verify_subject_binding(ROOT, self.binding)
        self.assertEqual(self.binding['unique_parameters'], 3082539008)
        self.assertEqual(self.binding['applied_updates'], 1)
        self.assertEqual(self.binding['trained_token_credit'], 0)

    def test_forged_identity_or_scope_is_refused(self):
        for key, value in (
            ('config_sha256', '0' * 64), ('source_revision', '0' * 40),
            ('applied_updates', 2), ('trained_token_credit', 1025),
            ('unique_parameters', 3000000000), ('purpose', 'pretraining'),
            ('applied_updates', True), ('entry_argv', ['--live', '--steps', '2']),
        ):
            with self.subTest(key=key, value=value):
                altered = copy.deepcopy(self.binding)
                altered[key] = value
                with self.assertRaises(ValueError):
                    verify_subject_binding(ROOT, altered)

    def test_source_fixture_runtime_drift_is_refused(self):
        for field in ('sources', 'fixture', 'runtime', 'daemon'):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.binding)
                altered[field] = {}
                with self.assertRaises(ValueError):
                    verify_subject_binding(ROOT, altered)

    def test_foreign_loaded_module_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'foreign'):
            verify_loaded_sources(ROOT, self.binding, {'ember.model.ember_v0_decoder': SimpleNamespace(__file__=__file__)})

    def test_wrong_module_mapping_inside_declared_sources_is_refused(self):
        wrong = ROOT / 'src/ember/model/ember_v0_contract.py'
        with self.assertRaisesRegex(ValueError, 'module name'):
            verify_loaded_sources(ROOT, self.binding, {'ember.model.ember_v0_decoder': SimpleNamespace(__file__=str(wrong))})

    def test_actual_loaded_module_bytes_are_bound(self):
        verify_loaded_sources(ROOT, self.binding, {'ember.governance.scripts.cia_conformance': sys.modules['ember.governance.scripts.cia_conformance']})
        changed = copy.deepcopy(self.binding)
        changed['sources']['src/ember/governance/scripts/cia_conformance.py'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'bytes'):
            verify_loaded_sources(ROOT, changed, {'ember.governance.scripts.cia_conformance': sys.modules['ember.governance.scripts.cia_conformance']})


if __name__ == '__main__':
    unittest.main()
