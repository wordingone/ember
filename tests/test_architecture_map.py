# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import warnings
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


def require_functions(compiler: ModuleType, *names: str) -> None:
    missing = [name for name in names if not hasattr(compiler, name)]
    if missing:
        raise AssertionError("production functions absent: " + ", ".join(missing))


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


class CensusFailureTests(unittest.TestCase):
    def test_omitted_consumer_refuses(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "verify_consumer_completeness")
        discovered = [
            {
                "consumer_path": "scripts/a.py",
                "target": "scripts/b.py",
                "discovery_class": "python-import",
            }
        ]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.verify_consumer_completeness(discovered, [])

        self.assertEqual(raised.exception.code, "OMITTED_CONSUMER")
        self.assertEqual(raised.exception.detail, "scripts/a.py -> scripts/b.py")

    def test_sys_path_surgery_is_a_named_consumer_finding(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "scan_python_source")
        source = "import sys\nsys.path.insert(0, '../sibling')\n"

        result = compiler.scan_python_source("scripts/a.py", source)

        self.assertEqual(
            result["findings"],
            [
                {
                    "path": "scripts/a.py",
                    "finding": "SYS_PATH_SURGERY",
                    "line": 2,
                }
            ],
        )

    def test_ambient_cwd_and_drive_roots_are_named_findings(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "scan_root_signals")
        drive_path = "Q" + ":" + "/cache"
        source = f"root = Path.cwd()\ncache = {drive_path!r}\n"

        findings = compiler.scan_root_signals("scripts/a.py", source)

        self.assertEqual(
            [(row["finding"], row["line"]) for row in findings],
            [("AMBIENT_CWD", 1), ("IMPLICIT_DRIVE_ROOT", 2)],
        )

    def test_forbidden_dependency_refuses(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "build_dependency_graph")
        consumers = [
            {
                "consumer_path": "src/ember/model/a.py",
                "target": "src/ember/lab/b.py",
                "owner": "Model",
                "target_owner": "Lab",
            }
        ]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.build_dependency_graph(consumers, policy_fixture())

        self.assertEqual(raised.exception.code, "FORBIDDEN_DEPENDENCY")
        self.assertEqual(raised.exception.detail, "Model -> Lab")

    def test_dependency_cycle_refuses(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "build_dependency_graph")
        policy = policy_fixture()
        policy["allowed_dependencies"] = [["Model", "Data"], ["Data", "Model"]]
        consumers = [
            {"consumer_path": "a.py", "target": "b.py", "owner": "Model", "target_owner": "Data"},
            {"consumer_path": "b.py", "target": "a.py", "owner": "Data", "target_owner": "Model"},
        ]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.build_dependency_graph(consumers, policy)

        self.assertEqual(raised.exception.code, "DEPENDENCY_CYCLE")
        self.assertEqual(raised.exception.detail, "Data -> Model -> Data")

    def test_package_authority_blob_drift_refuses(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "validate_package_authorities")
        policy = policy_fixture()
        policy["package_authorities"][0]["expected_blob_oid"] = "0" * 40

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.validate_package_authorities(ROOT, policy)

        self.assertEqual(raised.exception.code, "PACKAGE_AUTHORITY_DRIFT")
        self.assertEqual(raised.exception.detail, "pyproject.toml")


class CensusContractTests(unittest.TestCase):
    def test_rust_and_typescript_imports_have_executable_classes(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "scan_rust_source", "scan_typescript_source")

        rust = compiler.scan_rust_source("runtime/a.rs", "use crate::model;\n")
        typescript = compiler.scan_typescript_source(
            "tools/ember-cli/src/a.ts", "import runtime from './runtime';\n"
        )

        self.assertEqual(
            rust,
            [{"consumer_path": "runtime/a.rs", "target": "rust:crate::model", "discovery_class": "rust-import", "line": 1}],
        )
        self.assertEqual(
            typescript,
            [{"consumer_path": "tools/ember-cli/src/a.ts", "target": "typescript:./runtime", "discovery_class": "typescript-import", "line": 1}],
        )

    def test_dynamic_python_loader_is_an_executable_consumer(self) -> None:
        compiler = load_compiler()
        source = "import importlib\nimportlib.import_module('ember.runtime')\n"

        result = compiler.scan_python_source("scripts/a.py", source)

        dynamic = [row for row in result["consumers"] if row["discovery_class"] == "python-dynamic-loader"]
        self.assertEqual(
            dynamic,
            [{"consumer_path": "scripts/a.py", "target": "module:ember.runtime", "discovery_class": "python-dynamic-loader", "line": 2}],
        )

    def test_receipt_manifest_and_mutable_state_references_have_distinct_classes(self) -> None:
        compiler = load_compiler()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "scripts" / "a.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "manifest = 'manifests/example.json'\nmutable = 'state/run.json'\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "path": "scripts/a.py",
                    "owner": "Governance",
                    "disposition": "MOVE",
                    "touch_set_id": "governance-script-census",
                }
            ]

            result = compiler.discover_consumers(root, rows)

        self.assertEqual(
            [(row["target"], row["discovery_class"]) for row in result["rows"]],
            [
                ("manifests/example.json", "receipt-manifest-schema-config-consumer"),
                ("state/run.json", "mutable-state-reference"),
            ],
        )

    def test_python_deprecation_warning_is_captured_as_a_finding(self) -> None:
        compiler = load_compiler()
        source = '"""' + "\\." + '"""\n'

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            result = compiler.scan_python_source("scripts/escape.py", source)

        self.assertEqual(observed, [])
        self.assertEqual(result["findings"][0]["finding"], "PYTHON_DEPRECATION_WARNING")

    def test_python_scanner_accepts_a_standard_utf8_bom(self) -> None:
        compiler = load_compiler()
        source = chr(0xFEFF) + "import json\n"

        try:
            result = compiler.scan_python_source("scripts/bom.py", source)
        except compiler.ArchitectureMapError as exc:
            self.fail(f"standard UTF-8 BOM was rejected: {exc}")

        self.assertEqual(result["consumers"][0]["target"], "module:json")

    def test_typed_roots_and_current_package_blobs_verify(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()

        roots = compiler.validate_typed_roots(policy)
        packages = compiler.validate_package_authorities(ROOT, policy)

        self.assertEqual(
            [row["id"] for row in roots],
            ["application_state", "cache", "data", "evidence", "model_checkpoint", "source", "worktree"],
        )
        self.assertEqual(len(packages), 5)
        self.assertEqual({row["role"] for row in packages}, {"package", "lock"})

    def test_discovery_emits_real_import_owner_and_root_finding(self) -> None:
        compiler = load_compiler()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "scripts" / "a.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "from ember.data import shard\nroot = Path.cwd()\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "path": "scripts/a.py",
                    "owner": "Governance",
                    "disposition": "MOVE",
                    "touch_set_id": "governance-script-census",
                }
            ]

            result = compiler.discover_consumers(root, rows)

        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["target"], "module:ember.data")
        self.assertEqual(result["rows"][0]["target_owner"], "Data")
        self.assertEqual(result["findings"][0]["finding"], "AMBIENT_CWD")

    def test_current_tree_consumer_census_has_complete_row_shape(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        paths = compiler.tracked_paths(ROOT)
        path_rows = compiler.classify_paths(paths, policy)

        result = compiler.discover_consumers(ROOT, path_rows)

        self.assertGreater(len(result["rows"]), 0)
        self.assertEqual(
            set(result),
            {"rows", "findings", "class_counts"},
        )
        required = {
            "consumer_path",
            "target",
            "discovery_class",
            "line",
            "owner",
            "disposition",
            "touch_set_id",
            "target_owner",
        }
        self.assertTrue(all(set(row) == required for row in result["rows"]))

    def test_current_tree_owner_dependency_graph_is_allowed_and_acyclic(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        paths = compiler.tracked_paths(ROOT)
        path_rows = compiler.classify_paths(paths, policy)
        consumers = compiler.discover_consumers(ROOT, path_rows)["rows"]

        try:
            graph = compiler.build_dependency_graph(consumers, policy)
        except compiler.ArchitectureMapError as exc:
            self.fail(f"current-tree dependency graph refused: {exc}")

        self.assertEqual(graph["nodes"], policy["owners"])
        self.assertEqual(graph["edges"], sorted(graph["edges"]))


if __name__ == "__main__":
    unittest.main()
