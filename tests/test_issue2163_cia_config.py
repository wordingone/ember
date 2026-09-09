# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Strict canonical revision binding, not checkpoint admission or learning."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ember.model.cia_contract import validate_cia_architecture, cia_architecture_sha256


class CIAConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'configs/ember-cia-3b.json').read_text())

    def test_actual_decoder_consumes_the_validated_architecture(self):
        from ember.model.cia_decoder import CIADecoder
        model = CIADecoder(architecture_config=self.config)
        self.assertEqual(model.config, validate_cia_architecture(self.config))
        self.assertEqual(sum(p.numel() for p in model.parameter_inventory().values()), 3_082_539_008)

    def test_actual_decoder_rejects_changed_config_before_parameter_allocation(self):
        from ember.model.cia_decoder import CIADecoder
        from unittest.mock import patch
        self.config['model']['layers'] = 14
        with patch('ember.model.cia_decoder.torch.empty') as allocation:
            with self.assertRaises(ValueError):
                CIADecoder(architecture_config=self.config)
            allocation.assert_not_called()


    def test_exact_revision_resolves_complete_equation_inventory(self):
        contract = validate_cia_architecture(self.config)
        from ember.model.cia_contract import census
        from ember.model.cia_inventory import equation_inventory
        self.assertEqual(contract.revision, 'CIA3-R1-N61')
        self.assertEqual(census(contract).total_unique, 3_082_539_008)
        self.assertEqual(sum(spec.numel for spec in equation_inventory()), census(contract).total_unique)

    def test_v2_geometry_cannot_be_relabelled_as_cia(self):
        old = json.loads((ROOT / 'configs/ember-restart-3b.json').read_text())
        old['architecture_revision'] = 'CIA3-R1-N61'
        with self.assertRaises(ValueError):
            validate_cia_architecture(old)

    def test_changed_dimensions_routes_boundaries_or_numerics_need_revision(self):
        for field, value in [('hidden_size', 2048), ('layers', 14), ('global_experts', 24),
                             ('resident_experts', 3), ('selected_experts', 2),
                             ('global_epoch', 512), ('local_segment', 128),
                             ('image_patch_size', 48), ('audio_frame_size', 320),
                             ('parameter_dtype', 'float32'), ('routing', 'modality-named'),
                             ('norm_vectors', 64), ('total_unique_parameters', 3_082_542_080)]:
            with self.subTest(field=field):
                config = copy.deepcopy(self.config)
                config['model'][field] = value
                with self.assertRaises(ValueError):
                    validate_cia_architecture(config)

    def test_bool_float_unknown_missing_and_family_alias_refused(self):
        cases = []
        for value in (True, 25.0, '25', None):
            config = copy.deepcopy(self.config)
            config['model']['global_experts'] = value
            cases.append(config)
        for field in ('architecture_revision', 'model', 'schema_version', 'authority'):
            config = copy.deepcopy(self.config)
            del config[field]
            cases.append(config)
        for value in ('CIA', 'CIA3-R1', 'ember-sparse-3b-v2', 'CIA3-R2'):
            config = copy.deepcopy(self.config)
            config['architecture_revision'] = value
            cases.append(config)
        config = copy.deepcopy(self.config)
        config['model']['optimizer'] = 'undeclared'
        cases.append(config)
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_cia_architecture(config)

    def test_identity_is_order_independent_but_invalid_changes_cannot_mint_hash(self):
        reversed_config = dict(reversed(list(self.config.items())))
        reversed_config['model'] = dict(reversed(list(self.config['model'].items())))
        self.assertEqual(cia_architecture_sha256(self.config), cia_architecture_sha256(reversed_config))
        self.assertEqual(len(cia_architecture_sha256(self.config)), 64)
        self.config['model']['layers'] = 23
        with self.assertRaises(ValueError):
            cia_architecture_sha256(self.config)


if __name__ == '__main__':
    unittest.main()
