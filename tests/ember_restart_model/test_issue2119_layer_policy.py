"""CPU checks of the declared layer policy: explicit per-child selector env, worker env check, resolved-set check and emitted record."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
spec = importlib.util.spec_from_file_location('tested_layer_policy_runner', SOURCE)
runner = importlib.util.module_from_spec(spec)
sys.modules['tested_layer_policy_runner'] = runner
spec.loader.exec_module(runner)

ALL = ','.join(str(v) for v in range(24))
KEEP = dict(attention_keep='0,6,12,18,23', ffn_keep='11', expert_keep='23')
FULL = {'mode': 'full'}


def hour(template=None):
    value = dict(schema='governed-hour-v1', arm='control', minimum_wall_seconds=3600, minimum_measured_steps=1024)
    if template is not None:
        value['layer_template'] = template
    return dict(hour=value)


class CanonicalForm(unittest.TestCase):
    def test_all_24_in_any_spelling_is_full_and_keeps_are_sorted_strings(self):
        self.assertEqual(runner.canonical_layer_template(dict(attention_keep=ALL, ffn_keep=ALL, expert_keep=ALL)), FULL)
        self.assertEqual(runner.canonical_layer_template(FULL), FULL)
        self.assertEqual(runner.canonical_layer_template(dict(attention_keep=[23, 0, 6, 12, 18], ffn_keep=[11], expert_keep=[23])), KEEP)

    def test_malformed_templates_raise(self):
        for bad in (dict(attention_keep='0,99', ffn_keep='1', expert_keep='2'), dict(attention_keep='', ffn_keep='1', expert_keep='2'),
                    {'mode': 'none'}, None, 'full', dict(attention_keep='1', ffn_keep='2')):
            with self.assertRaises((ValueError, TypeError, AttributeError)):
                runner.canonical_layer_template(bad)


class HourIdentity(unittest.TestCase):
    def test_canonical_full_and_keep_are_accepted_and_absent_is_still_valid(self):
        for identity in (hour(), hour(FULL), hour(KEEP)):
            self.assertTrue(runner.hour_mode(identity))

    def test_non_canonical_or_malformed_template_refuses(self):
        for bad in (dict(attention_keep=ALL, ffn_keep=ALL, expert_keep=ALL), dict(attention_keep=[0], ffn_keep=[1], expert_keep=[2]),
                    dict(attention_keep='0,99', ffn_keep='1', expert_keep='2'), {'mode': 'other'}, 'full'):
            with self.assertRaises(ValueError):
                runner.hour_mode(hour(bad))

    def test_other_schemas_refuse_a_layer_template(self):
        identity = dict(hour=dict(schema='checkpoint-probe-v1', arm='control', minimum_wall_seconds=0, minimum_measured_steps=2,
                                  layer_template=FULL))
        with self.assertRaises(ValueError):
            runner.hour_mode(identity)


class ChildEnv(unittest.TestCase):
    AMBIENT = {'EMBER_SKIP_KEEP': '0,1', 'EMBER_SKIP_KEEP_FFN': '2', 'EMBER_SKIP_KEEP_EXPERT': '3', 'PATH': 'x'}

    def test_full_clears_an_ambient_selector_and_sets_the_receipt_path(self):
        env = runner.layer_child_env(hour(FULL), 'B:/custody/m', base_env=self.AMBIENT)
        for name in runner.LAYER_SELECTOR_ENV:
            self.assertNotIn(name, env)
        self.assertEqual(env['PATH'], 'x')
        self.assertTrue(env['EMBER_LAYER_TEMPLATE_RECEIPT'].replace('\\', '/').endswith('B:/custody/m/layer-template-counts.json'))

    def test_keep_sets_the_three_selectors_from_the_identity_not_the_ambient(self):
        env = runner.layer_child_env(hour(KEEP), 'B:/custody/m', base_env=self.AMBIENT)
        self.assertEqual([env[name] for name in runner.LAYER_SELECTOR_ENV], ['0,6,12,18,23', '11', '23'])

    def test_an_identity_without_a_declaration_refuses_at_launch(self):
        with self.assertRaises(ValueError):
            runner.layer_child_env(hour(), 'B:/custody/m', base_env={})

    def test_the_process_environment_is_never_mutated(self):
        before = dict(os.environ)
        runner.layer_child_env(hour(KEEP), 'B:/custody/m', base_env=None)
        self.assertEqual(dict(os.environ), before)

    def test_launch_passes_the_explicit_env_to_the_runner(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn('cwd=ROOT, env=child_env)', source)
        self.assertLess(source.index('child_env = layer_child_env('), source.index('reserve_diagnostic_dispatch('))


class WorkerChecks(unittest.TestCase):
    def test_env_matching_the_declaration_passes(self):
        runner.check_layer_env(hour(FULL), {'EMBER_LAYER_TEMPLATE_RECEIPT': 'x'})
        runner.check_layer_env(hour(KEEP), {'EMBER_SKIP_KEEP': '0,6,12,18,23', 'EMBER_SKIP_KEEP_FFN': '11', 'EMBER_SKIP_KEEP_EXPERT': '23',
                                            'EMBER_LAYER_TEMPLATE_RECEIPT': 'x'})

    def test_worker_side_mismatch_refuses(self):
        with self.assertRaises(ValueError):
            runner.check_layer_env(hour(FULL), {'EMBER_SKIP_KEEP': '0', 'EMBER_LAYER_TEMPLATE_RECEIPT': 'x'})
        with self.assertRaises(ValueError):
            runner.check_layer_env(hour(KEEP), {'EMBER_LAYER_TEMPLATE_RECEIPT': 'x'})
        with self.assertRaises(ValueError):
            runner.check_layer_env(hour(KEEP), {'EMBER_SKIP_KEEP': '0,6,12,18,22', 'EMBER_SKIP_KEEP_FFN': '11', 'EMBER_SKIP_KEEP_EXPERT': '23',
                                                'EMBER_LAYER_TEMPLATE_RECEIPT': 'x'})
        with self.assertRaises(ValueError):
            runner.check_layer_env(hour(FULL), {})

    def test_resolved_sets_must_equal_the_canonical_declaration_and_name_the_layer(self):
        full = dict(attention_keep=list(range(24)), ffn_keep=list(range(24)), expert_keep=list(range(24)))
        self.assertEqual(runner.check_resolved_layers(hour(FULL), full), [])
        short = dict(full, attention_keep=[v for v in range(24) if v != 5])
        failures = runner.check_resolved_layers(hour(FULL), short)
        self.assertTrue(failures and '5' in failures[0], failures)
        keep = dict(attention_keep=[0, 6, 12, 18, 23], ffn_keep=[11], expert_keep=[23])
        self.assertEqual(runner.check_resolved_layers(hour(KEEP), keep), [])
        self.assertTrue(runner.check_resolved_layers(hour(KEEP), full))
        self.assertEqual(runner.check_resolved_layers(hour(), full), [])

    def test_worker_order_env_check_then_import_then_resolved_check_then_emit(self):
        source = SOURCE.read_text(encoding='utf-8')
        env_check = source.index('check_layer_env(prediction')
        imported = source.index('import ember.model.ember_v0_decoder as resolved_decoder')
        resolved_check = source.index('mismatch = check_resolved_layers(')
        emitted = source.index('_write_new(custody / LAYER_RESOLVED_NAME')
        self.assertLess(env_check, source.index('from ember.model.ember_v0_decoder import CIADecoder'))
        self.assertLess(imported, resolved_check)
        self.assertLess(resolved_check, emitted)
        self.assertLess(emitted, source.index('raise ValueError(\'decoder resolved layer sets differ'))


PROBE = ('import json, os, sys; sys.path.insert(0, sys.argv[1]);'
         'import ember.model.ember_v0_decoder as d;'
         'print(json.dumps(dict(attention_keep=sorted(d._ATTENTION_KEEP), ffn_keep=sorted(d._FFN_KEEP), expert_keep=sorted(d._EXPERT_KEEP))))')


@unittest.skipUnless(importlib.util.find_spec('torch') is not None, 'decoder import needs torch')
class RealDecoderResolution(unittest.TestCase):
    """The real decoder module resolves exactly what the explicit child env declares, even with ambient selectors present."""

    def resolve(self, identity, ambient):
        with tempfile.TemporaryDirectory() as tmp:
            env = runner.layer_child_env(identity, tmp, base_env=dict(os.environ, **ambient))
            hidden = {}
            if os.name == 'nt':
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
                hidden = dict(creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
            out = subprocess.run([sys.executable, '-B', '-c', PROBE, str(ROOT / 'src')], env=env, capture_output=True, text=True, timeout=300,
                                 shell=False, **hidden)
            self.assertEqual(out.returncode, 0, out.stderr[-600:])
            receipt = Path(tmp) / 'layer-template-counts.json'
            self.assertTrue(receipt.exists(), 'decoder did not emit its receipt at the custody path')
            emitted = json.loads(receipt.read_text(encoding='utf-8'))
            return json.loads(out.stdout.strip().splitlines()[-1]), emitted

    def test_ambient_selector_with_full_declared_resolves_all_24(self):
        resolved, emitted = self.resolve(hour(FULL), {'EMBER_SKIP_KEEP': '0,1'})
        self.assertEqual(runner.check_resolved_layers(hour(FULL), resolved), [])
        self.assertEqual(emitted['attention_keep'], list(range(24)))

    def test_keep_declaration_produces_a_receipt_with_equal_sets(self):
        resolved, emitted = self.resolve(hour(KEEP), {'EMBER_SKIP_KEEP': '5'})
        self.assertEqual(runner.check_resolved_layers(hour(KEEP), resolved), [])
        self.assertEqual((emitted['attention_keep'], emitted['ffn_keep'], emitted['expert_keep']), ([0, 6, 12, 18, 23], [11], [23]))


if __name__ == '__main__':
    unittest.main()
