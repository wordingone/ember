# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ember_ceff_closure_confirmation  # noqa: E402
import v0_config_check  # noqa: E402
import v0_pretrain_launch_gate  # noqa: E402


class MtpParameterAccountingContractTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (ROOT / "configs" / "v0-pretrain-config.json").read_text(
                encoding="utf-8"
            )
        )

    def test_config_distinguishes_base_auxiliary_and_realized_parameters(self):
        accounting = self.config["model"]["parameter_accounting"]

        self.assertEqual(accounting["base_excluding_mtp"], 368_354_304)
        self.assertEqual(accounting["mtp_aux"], 65_536_000)
        self.assertEqual(accounting["realized"], 433_890_304)
        self.assertEqual(
            accounting["base_excluding_mtp"] + accounting["mtp_aux"],
            accounting["realized"],
        )

    def test_config_identifies_the_actual_independent_head_mechanism(self):
        mechanism = self.config["objective"]["mtp_aux_heads"]["mechanism_identity"]

        self.assertEqual(mechanism["implementation"], "independent_vocab_projection_heads")
        self.assertTrue(mechanism["shared_hidden_state"])
        self.assertFalse(mechanism["sequential_state_transition"])
        self.assertFalse(mechanism["deepseek_sequential_mtp_equivalent"])
        self.assertFalse(mechanism["speculative_decode_drafter"])

    def test_validator_rejects_a_self_consistent_but_wrong_split(self):
        wrong = copy.deepcopy(self.config)
        wrong["model"]["parameter_accounting"] = {
            "base_excluding_mtp": 400_000_000,
            "mtp_aux": 33_890_304,
            "realized": 433_890_304,
        }

        violations = v0_config_check.check(wrong)

        self.assertTrue(
            any("base_excluding_mtp" in violation for violation in violations),
            violations,
        )
        self.assertTrue(
            any("mtp_aux" in violation for violation in violations),
            violations,
        )

    def test_validator_rejects_arithmetic_and_mechanism_conflation(self):
        wrong = copy.deepcopy(self.config)
        wrong["model"]["parameter_accounting"]["realized"] += 1
        mechanism = wrong["objective"]["mtp_aux_heads"]["mechanism_identity"]
        mechanism["sequential_state_transition"] = True
        mechanism["deepseek_sequential_mtp_equivalent"] = True
        mechanism["speculative_decode_drafter"] = True

        violations = v0_config_check.check(wrong)

        self.assertTrue(
            any("base_excluding_mtp + mtp_aux" in violation for violation in violations),
            violations,
        )
        self.assertTrue(
            any("mechanism_identity" in violation for violation in violations),
            violations,
        )

    def test_validator_refuses_malformed_dimension_types_without_crashing(self):
        wrong = copy.deepcopy(self.config)
        wrong["objective"]["mtp_aux_heads"]["n_heads"] = None
        wrong["model"]["parameter_accounting"]["base_excluding_mtp"] = True

        try:
            violations = v0_config_check.check(wrong)
        except (TypeError, ValueError) as error:
            self.fail(f"validator crashed instead of refusing malformed types: {error}")

        self.assertTrue(
            any("integer" in violation for violation in violations),
            violations,
        )

    def test_launch_budget_is_derived_from_realized_parameters(self):
        self.assertEqual(v0_pretrain_launch_gate.V0_BASE_EXCLUDING_MTP_PARAMS, 368_354_304)
        self.assertEqual(v0_pretrain_launch_gate.V0_MTP_AUX_PARAMS, 65_536_000)
        self.assertEqual(v0_pretrain_launch_gate.V0_REALIZED_PARAMS, 433_890_304)
        self.assertEqual(
            v0_pretrain_launch_gate.MICRO_FIT_CEILING_FLOPS,
            28_636_760_064_000_000.0,
        )

    def test_synthetic_confirmation_descriptor_uses_realized_parameters(self):
        result = ember_ceff_closure_confirmation.run_confirmation_dry(1.0)

        self.assertTrue(result["synthetic"])
        self.assertEqual(result["requested_run"]["params"], 433_890_304)


if __name__ == "__main__":
    unittest.main()
