# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "manifests" / "architecture" / "domain-authority-v1.json"
COMPILER_PATH = ROOT / "scripts" / "architecture_map.py"


def load_compiler() -> ModuleType:
    if not COMPILER_PATH.is_file():
        raise AssertionError(
            "architecture map compiler is absent; the planted RED must fire before production code"
        )
    spec = importlib.util.spec_from_file_location("architecture_map_under_test", COMPILER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("architecture map compiler could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policy_fixture() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def one_rule(
    rule_id: str,
    pattern: str,
    *,
    disposition: str = "MOVE",
    deferral_id: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": rule_id,
        "include": [pattern],
        "exclude": [],
        "owner": "Governance",
        "disposition": disposition,
        "touch_set_id": f"touch-{rule_id}",
    }
    if deferral_id is not None:
        row["deferral_id"] = deferral_id
    return row


class PolicyFailureTests(unittest.TestCase):
    def test_uncovered_path_refuses(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        policy["path_rules"] = []

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.classify_paths(["orphan.bin"], policy)

        self.assertEqual(raised.exception.code, "UNCOVERED_PATH")
        self.assertEqual(raised.exception.detail, "orphan.bin")

    def test_overlapping_rules_refuse_instead_of_using_precedence(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        policy["path_rules"] = [
            one_rule("docs-a", "docs/**"),
            one_rule("docs-b", "docs/**"),
        ]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.classify_paths(["docs/a.md"], policy)

        self.assertEqual(raised.exception.code, "OVERLAPPING_PATH_RULES")
        self.assertIn("docs-a", raised.exception.detail)
        self.assertIn("docs-b", raised.exception.detail)

    def test_undeclared_deferral_refuses(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        policy["path_rules"] = [
            one_rule(
                "data",
                "data/**",
                disposition="DEFERRED_DEPENDENCY",
                deferral_id="missing-deferral",
            )
        ]
        policy["deferrals"] = []

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.classify_paths(["data/a.json"], policy)

        self.assertEqual(raised.exception.code, "UNDECLARED_DEFERRAL")
        self.assertEqual(raised.exception.detail, "missing-deferral")

    def test_deferral_without_predicate_selector_and_failure_refuses(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        malformed = deepcopy(policy["deferrals"][0])
        del malformed["predicate"]
        del malformed["evidence_selector"]
        del malformed["failure_state"]
        policy["deferrals"] = [malformed, policy["deferrals"][1]]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.validate_policy(policy)

        self.assertEqual(raised.exception.code, "MALFORMED_DEFERRAL")
        self.assertEqual(raised.exception.detail, "data-1581")

    def test_backend_substitution_refuses(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.validate_backend_artifact("0" * 64, policy)

        self.assertEqual(raised.exception.code, "BACKEND_ARTIFACT_REFUSED")
        self.assertEqual(
            raised.exception.detail,
            "expected 51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670, got "
            + "0" * 64,
        )


class ClassificationTests(unittest.TestCase):
    def test_each_path_has_one_owner_and_disposition(self) -> None:
        compiler = load_compiler()

        rows = compiler.classify_paths(
            ["scripts/train.py", "receipts/run.json"], policy_fixture()
        )

        self.assertEqual(
            rows,
            [
                {
                    "path": "receipts/run.json",
                    "owner": "Governance",
                    "disposition": "RETAIN_STABLE",
                    "rule_id": "receipts-stable",
                    "touch_set_id": "governance-stable-receipts",
                    "deferral_id": None,
                },
                {
                    "path": "scripts/train.py",
                    "owner": "Governance",
                    "disposition": "MOVE",
                    "rule_id": "scripts",
                    "touch_set_id": "governance-script-census",
                    "deferral_id": None,
                },
            ],
        )

    def test_classification_order_is_posix_lexicographic(self) -> None:
        compiler = load_compiler()

        rows = compiler.classify_paths(
            ["tools/z.py", "docs/z.md", "docs/a.md"], policy_fixture()
        )

        self.assertEqual(
            [row["path"] for row in rows],
            ["docs/a.md", "docs/z.md", "tools/z.py"],
        )

    def test_receipts_and_manifests_retain_stable_bytes(self) -> None:
        compiler = load_compiler()

        rows = compiler.classify_paths(
            ["receipts/a.json", "manifests/b.json"], policy_fixture()
        )

        self.assertEqual(
            [row["disposition"] for row in rows],
            ["RETAIN_STABLE", "RETAIN_STABLE"],
        )

    def test_data_and_evaluation_carrier_membership_is_deferred(self) -> None:
        compiler = load_compiler()

        rows = compiler.classify_paths(
            ["data/a.json", "scripts/eval_probe.py"], policy_fixture()
        )

        self.assertEqual(
            [(row["owner"], row["disposition"], row["deferral_id"]) for row in rows],
            [
                ("Data", "DEFERRED_DEPENDENCY", "data-1581"),
                ("Evaluation", "DEFERRED_DEPENDENCY", "evaluation-api"),
            ],
        )

    def test_current_git_tree_has_exactly_one_classification_per_path(self) -> None:
        compiler = load_compiler()
        paths = compiler.tracked_paths(ROOT)

        rows = compiler.classify_paths(paths, policy_fixture())

        self.assertEqual(len(rows), len(paths))
        self.assertEqual([row["path"] for row in rows], sorted(set(paths)))


if __name__ == "__main__":
    unittest.main()
