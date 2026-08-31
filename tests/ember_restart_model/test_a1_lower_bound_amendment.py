# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations


import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AMENDMENT = ROOT / "docs/spec/ember02-a1-lower-bound-only-amendment-v2.json"
PREREG = ROOT / "docs/domains/governance/spec/ember02-preregistration-v1.md"
THRESHOLDS = ROOT / "docs/spec/ember02-preregistration-thresholds-v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class A1LowerBoundAmendmentContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.amendment = json.loads(AMENDMENT.read_bytes())

    def test_amendment_binds_frozen_authority_and_executed_trigger(self) -> None:
        self.assertEqual(
            set(self.amendment),
            {
                "schema", "status", "issue", "supersedes", "thresholds",
                "trigger_evidence", "decision", "change_control",
                "execution_boundary", "rollback",
            },
        )
        self.assertEqual(self.amendment["schema"], "ember02-a1-lower-bound-only-amendment/v2")
        self.assertEqual(self.amendment["status"], "FROZEN")
        self.assertEqual(self.amendment["issue"], 1116)
        self.assertEqual(
            self.amendment["supersedes"],
            {
                "path": "docs/domains/governance/spec/ember02-preregistration-v1.md",
                "sha256": sha256(PREREG),
                "preregistration_pin": "3d48d3870919bd04cec735f68d0fad45fcfae0b2",
                "scope": "section-4-A1-both-tiers-fail-only",
            },
        )
        self.assertEqual(
            self.amendment["thresholds"],
            {
                "path": "docs/spec/ember02-preregistration-thresholds-v1.json",
                "sha256": sha256(THRESHOLDS),
                "change": "NO_THRESHOLD_CHANGE",
            },
        )
        evidence = self.amendment["trigger_evidence"]
        self.assertEqual(
            set(evidence),
            {
                "condition", "source_commit", "comparison_id", "charged_budget_contract_sha256",
                "liveness_receipt_sha256", "parity_receipt_sha256", "battery_receipt_sha256",
                "public_adjudication",
            },
        )
        self.assertEqual(evidence["condition"], "BOTH_R1_E8_TIERS_FAIL")
        self.assertEqual(evidence["source_commit"], "24decc312c771ec0e9309882f24f2a3ba82ea156")
        self.assertEqual(evidence["comparison_id"], "e8-pair-24de-20260822T1230Z")
        self.assertEqual(evidence["charged_budget_contract_sha256"], "61c7b28b6b85d623b73ca30b057dc08a44428f96391bc98c796409625535c8f0")
        self.assertEqual(evidence["liveness_receipt_sha256"], "4d92cfeee4d7e4134a226641176cbc7d097aeaf0840f0b52423781a32a62577c")
        self.assertEqual(evidence["parity_receipt_sha256"], "4322f089a286438bb7329959ec7027348c81c9c43125aa1aba35d13d5b320ac3")
        self.assertEqual(evidence["battery_receipt_sha256"], "a583bedc6d7706f53b31d3156a5cb91e36852f2a035770d9aa6d925390674c00")
        self.assertEqual(
            evidence["public_adjudication"],
            {
                "issue": 1464,
                "state": "CLOSED",
                "state_reason": "COMPLETED",
                "comment_id": 5380707076,
                "url": "https://github.com/wordingone/ember/issues/1464#issuecomment-5380707076",
            },
        )

    def test_decision_is_lower_bound_only_and_grants_no_null_or_credit(self) -> None:
        decision = self.amendment["decision"]
        self.assertEqual(
            set(decision),
            {
                "arm", "arm_scope", "disclosure", "tier1_mechanism",
                "tier2_candidate_mechanism", "tier1",
                "tier2", "r2_funding_allowed", "dense_null_claim_allowed",
                "beaten_null_citation_allowed", "capability_credit_allowed",
                "result_credit_allowed", "capacity_matching",
            },
        )
        self.assertEqual(decision["arm"], "A1")
        self.assertEqual(decision["arm_scope"], "LOWER_BOUND_ONLY")
        self.assertEqual(decision["disclosure"], "dense as best-achievable on this boundary")
        self.assertEqual(decision["tier1_mechanism"], "FULL_STATE_ADAMW_CPU_OFFLOAD")
        self.assertEqual(decision["tier2_candidate_mechanism"], "OWNED_Q_GALORE_PROJECTED_GRADIENT")
        self.assertEqual(decision["tier1"], "REJECTED_LIVENESS_BELOW_T08")
        self.assertEqual(decision["tier2"], "NOT_ADMITTED_PARITY_OUTSIDE_F11")
        for field in (
            "r2_funding_allowed", "dense_null_claim_allowed", "beaten_null_citation_allowed",
            "capability_credit_allowed", "result_credit_allowed",
        ):
            self.assertIs(decision[field], False)
        self.assertEqual(
            decision["capacity_matching"],
            {
                "total_capacity": "MATCHED",
                "active_capacity": "MISMATCH_DISCLOSED",
                "sub_3b_control_allowed": False,
            },
        )

    def test_change_control_adds_no_threshold_or_parallel_authority(self) -> None:
        self.assertEqual(
            self.amendment["change_control"],
            {
                "thresholds": "NO_THRESHOLD_CHANGE",
                "authority": "NO_NEW_PARALLEL_AUTHORITY",
                "prior_version_mutated": False,
                "runtime_consumer_added": False,
            },
        )
        serialized = json.dumps(self.amendment, sort_keys=True)
        self.assertIsNone(re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", serialized))


if __name__ == "__main__":
    unittest.main()
