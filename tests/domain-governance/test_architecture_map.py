# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
import warnings
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
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
        "rollback_unit_strategy": (
            "NOT_A_SWITCH"
            if disposition in {"RETAIN_STABLE", "DEFERRED_DEPENDENCY"}
            else "PER_AUTHORITATIVE_SWITCH_TARGET"
        ),
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
    def test_post_issue2015_canonical_paths_remain_covered_by_original_authority(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        rows = {
            row["path"]: row
            for row in compiler.classify_paths(
                [
                    "domains/governance/notes/1371-slice2-fingerprint-cache.md",
                    "domains/governance/schemas/architecture/domain-authority-v1.schema.json",
                    "domains/model/tokenizer/tokenizer.json",
                    "src/ember/governance/scripts/owned_process.py",
                    "src/ember/governance/scripts/r1_frozen_eval_runner.py",
                    "src/ember/infrastructure/tools/check_no_temp.py",
                ],
                policy,
            )
        }
        expected = {
            "domains/governance/notes/1371-slice2-fingerprint-cache.md": ("Governance", "RETAIN_STABLE", "governance-notes"),
            "domains/governance/schemas/architecture/domain-authority-v1.schema.json": ("Governance", "RETAIN_STABLE", "governance-schemas"),
            "domains/model/tokenizer/tokenizer.json": ("Model", "RETAIN_STABLE", "model-tokenizer"),
            "src/ember/governance/scripts/owned_process.py": ("Governance", "RETAIN_STABLE", "governance-script-census"),
            "src/ember/governance/scripts/r1_frozen_eval_runner.py": ("Evaluation", "DEFERRED_DEPENDENCY", "evaluation-current"),
            "src/ember/infrastructure/tools/check_no_temp.py": ("Infrastructure", "RETAIN_STABLE", "infrastructure-tools"),
        }
        self.assertEqual(
            {
                path: (row["owner"], row["disposition"], row["touch_set_id"])
                for path, row in rows.items()
            },
            expected,
        )

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
                    "rollback_unit_strategy": "NOT_A_SWITCH",
                    "deferral_id": None,
                },
                {
                    "path": "scripts/train.py",
                    "owner": "Governance",
                    "disposition": "MOVE",
                    "rule_id": "scripts",
                    "touch_set_id": "governance-script-census",
                    "rollback_unit_strategy": "PER_AUTHORITATIVE_SWITCH_TARGET",
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
            "src/ember/infrastructure/tools/ember-cli/src/a.ts", "import runtime from './runtime';\n"
        )

        self.assertEqual(
            rust,
            [{"consumer_path": "runtime/a.rs", "target": "rust:crate::model", "discovery_class": "rust-import", "line": 1}],
        )
        self.assertEqual(
            typescript,
            [{"consumer_path": "src/ember/infrastructure/tools/ember-cli/src/a.ts", "target": "typescript:./runtime", "discovery_class": "typescript-import", "line": 1}],
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


class ColoringFailureTests(unittest.TestCase):
    def test_capacity_blind_k_minus_one_certificate_refuses(self) -> None:
        compiler = load_compiler()
        graph = {
            "nodes": ["a", "b"],
            "edges": [],
            "precedence": [],
            "node_weights": {
                "a": {"path_count": 1, "consumers": ["a-1", "a-2", "a-3"]},
                "b": {"path_count": 1, "consumers": ["b-1", "b-2", "b-3"]},
            },
            "capacities": {"max_paths_per_carrier": 64, "max_consumers_per_carrier": 5},
        }
        result = compiler.solve_minimum_coloring(
            graph["nodes"], [], [], max_states=100, node_weights=graph["node_weights"], capacities=graph["capacities"]
        )
        altered = {**result, "capacity_sha256": compiler.canonical_sha256({})}

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.verify_coloring_certificate(graph, altered, max_states=100)

        self.assertEqual(raised.exception.code, "COLORING_CERTIFICATE_MISMATCH")

    def test_oversized_atomic_touch_set_refuses(self) -> None:
        compiler = load_compiler()
        touch_sets = [
            {"id": "too-large", "paths": ["a.py", "b.py"], "consumers": []},
        ]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.build_conflict_graph(
                touch_sets,
                {"max_paths_per_carrier": 1, "max_consumers_per_carrier": 10},
            )

        self.assertEqual(raised.exception.code, "OVERSIZED_ATOMIC_TOUCH_SET")
        self.assertIn("too-large", raised.exception.detail)

    def test_altered_graph_or_k_refuses(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "solve_minimum_coloring", "verify_coloring_certificate")
        graph = {
            "nodes": ["a", "b"],
            "edges": [["a", "b"]],
            "precedence": [],
        }
        result = compiler.solve_minimum_coloring(
            graph["nodes"], [("a", "b")], [], max_states=100
        )
        altered = {
            **result,
            "graph_sha256": "0" * 64,
        }

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.verify_coloring_certificate(graph, altered, max_states=100)

        self.assertEqual(raised.exception.code, "COLORING_CERTIFICATE_MISMATCH")

    def test_invalid_k_minus_one_unsat_certificate_refuses(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "solve_minimum_coloring", "verify_coloring_certificate")
        graph = {
            "nodes": ["a", "b"],
            "edges": [["a", "b"]],
            "precedence": [],
        }
        result = compiler.solve_minimum_coloring(
            graph["nodes"], [("a", "b")], [], max_states=100
        )
        altered = {
            **result,
            "k_minus_one_unsat": {**result["k_minus_one_unsat"], "complete_exhaustion": False},
        }

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.verify_coloring_certificate(graph, altered, max_states=100)

        self.assertEqual(raised.exception.code, "K_MINUS_ONE_NOT_PROVEN")

    def test_exact_search_budget_exceeded_refuses_without_heuristic(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "solve_minimum_coloring")

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.solve_minimum_coloring(
                ["a", "b", "c"],
                [("a", "b"), ("b", "c"), ("a", "c")],
                [],
                max_states=1,
            )

        self.assertEqual(raised.exception.code, "EXACT_COLORING_BUDGET_EXCEEDED")


class ColoringContractTests(unittest.TestCase):
    def test_disconnected_capacity_packing_is_exact_and_certified(self) -> None:
        compiler = load_compiler()
        consumers = {
            "a": [f"a-{index:03d}" for index in range(115)],
            "b": [f"b-{index:03d}" for index in range(115)],
        }
        capacities = {
            "max_paths_per_carrier": 64,
            "max_consumers_per_carrier": 128,
            "consumer_counting_rule": "UNIQUE_CONSUMER_PATHS_PER_CARRIER",
        }

        result = compiler.solve_minimum_coloring(
            ["a", "b"],
            [],
            [],
            max_states=100,
            node_weights={
                node: {"path_count": 1, "consumers": rows}
                for node, rows in consumers.items()
            },
            capacities=capacities,
        )

        self.assertEqual(result["algorithm"], "stable-exact-branch-and-bound-v1")
        self.assertEqual(result["k"], 2)
        self.assertNotEqual(result["assignment"]["a"], result["assignment"]["b"])
        self.assertEqual(result["decomposition"]["component_count"], 2)
        self.assertEqual(result["decomposition"]["packing_item_count"], 2)
        self.assertEqual(result["k_minus_one_unsat"]["proof_kind"], "GLOBAL_PACKING_EXHAUSTION")

    def test_cross_component_precedence_refuses_decomposition(self) -> None:
        compiler = load_compiler()

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.solve_minimum_coloring(
                ["a", "b"], [], [("a", "b")], max_states=100
            )

        self.assertEqual(raised.exception.code, "CROSS_COMPONENT_PRECEDENCE")

    def test_nonconflicting_nodes_over_capacity_require_two_colors(self) -> None:
        compiler = load_compiler()
        weights = {
            "a": {"path_count": 1, "consumers": ["a-1", "a-2", "a-3"]},
            "b": {"path_count": 1, "consumers": ["b-1", "b-2", "b-3"]},
        }
        capacities = {"max_paths_per_carrier": 64, "max_consumers_per_carrier": 5}

        result = compiler.solve_minimum_coloring(
            ["a", "b"], [], [], max_states=100, node_weights=weights, capacities=capacities
        )

        self.assertEqual(result["k"], 2)
        self.assertNotEqual(result["assignment"]["a"], result["assignment"]["b"])
        self.assertEqual(result["k_minus_one_unsat"]["proof_kind"], "GLOBAL_PACKING_EXHAUSTION")
    def test_shared_consumer_creates_conflict_edge(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "build_conflict_graph")
        touch_sets = [
            {"id": "a", "paths": ["src/a.py"], "consumers": ["tests/shared.py"]},
            {"id": "b", "paths": ["src/b.py"], "consumers": ["tests/shared.py"]},
        ]

        graph = compiler.build_conflict_graph(
            touch_sets,
            {"max_paths_per_carrier": 20, "max_consumers_per_carrier": 20},
        )

        self.assertIn(["a", "b"], graph["edges"])

    def test_dependency_precedence_orders_carriers(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "solve_minimum_coloring")

        result = compiler.solve_minimum_coloring(
            ["a", "b"], [("a", "b")], [("a", "b")], max_states=100
        )

        self.assertLess(result["assignment"]["a"], result["assignment"]["b"])

    def test_reverse_lexical_precedence_remains_satisfiable(self) -> None:
        compiler = load_compiler()

        result = compiler.solve_minimum_coloring(
            ["a", "b"], [("a", "b")], [("b", "a")], max_states=100
        )

        self.assertEqual(result["k"], 2)
        self.assertLess(result["assignment"]["b"], result["assignment"]["a"])

    def test_touch_sets_are_stable_and_preserve_consumers(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "build_touch_sets")
        path_rows = [
            {"path": "src/b.py", "owner": "Model", "disposition": "MOVE", "touch_set_id": "model", "rollback_unit_strategy": "EXPLICIT_KEY", "rollback_unit_key": "model-pair"},
            {"path": "src/a.py", "owner": "Model", "disposition": "MOVE", "touch_set_id": "model", "rollback_unit_strategy": "EXPLICIT_KEY", "rollback_unit_key": "model-pair"},
        ]
        consumers = [
            {"consumer_path": "tests/z.py", "target": "src/a.py", "touch_set_id": "model"},
            {"consumer_path": "tests/z.py", "target": "src/b.py", "touch_set_id": "model"},
        ]

        result = compiler.build_touch_sets(path_rows, consumers)

        self.assertEqual(result[0]["paths"], ["src/a.py", "src/b.py"])
        self.assertEqual(result[0]["consumers"], ["tests/z.py"])

    def test_retain_stable_and_deferred_paths_are_not_nodes(self) -> None:
        compiler = load_compiler()
        path_rows = [
            {"path": "receipts/a.json", "owner": "Governance", "disposition": "RETAIN_STABLE", "touch_set_id": "stable", "rollback_unit_strategy": "NOT_A_SWITCH"},
            {"path": "data/a.json", "owner": "Data", "disposition": "DEFERRED_DEPENDENCY", "touch_set_id": "data", "rollback_unit_strategy": "NOT_A_SWITCH"},
            {"path": "scripts/a.py", "owner": "Governance", "disposition": "MOVE", "touch_set_id": "scripts", "rollback_unit_strategy": "PER_AUTHORITATIVE_SWITCH_TARGET"},
        ]

        result = compiler.build_touch_sets(path_rows, [])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["paths"], ["scripts/a.py"])

    def test_hub_consumer_does_not_fuse_authoritative_targets(self) -> None:
        compiler = load_compiler()
        path_rows = [
            {"path": "scripts/a.py", "owner": "Governance", "disposition": "MOVE", "touch_set_id": "scripts", "rollback_unit_strategy": "PER_AUTHORITATIVE_SWITCH_TARGET"},
            {"path": "scripts/b.py", "owner": "Governance", "disposition": "MOVE", "touch_set_id": "scripts", "rollback_unit_strategy": "PER_AUTHORITATIVE_SWITCH_TARGET"},
        ]
        consumers = [
            {"consumer_path": "tests/hub.py", "target": "scripts/a.py", "touch_set_id": "tests"},
            {"consumer_path": "tests/hub.py", "target": "scripts/b.py", "touch_set_id": "tests"},
        ]

        first = compiler.build_touch_sets(path_rows, consumers)
        second = compiler.build_touch_sets(list(reversed(path_rows)), list(reversed(consumers)))
        graph = compiler.build_conflict_graph(
            first,
            {"max_paths_per_carrier": 64, "max_consumers_per_carrier": 128},
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0]["consumers"], ["tests/hub.py"])
        self.assertEqual(first[1]["consumers"], ["tests/hub.py"])
        self.assertEqual(graph["edges"], [[first[0]["id"], first[1]["id"]]])

    def test_owner_dependency_becomes_target_before_source_precedence(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "build_touch_set_precedence")
        touch_sets = [
            {"id": "model", "owner": "Model"},
            {"id": "training", "owner": "Training"},
        ]
        dependencies = {"nodes": ["Model", "Training"], "edges": [["Training", "Model"]]}

        result = compiler.build_touch_set_precedence(touch_sets, dependencies)

        self.assertEqual(result, [["model", "training"]])

    def test_carrier_specs_are_ordered_and_complete(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "build_carrier_specs")
        touch_sets = [
            {"id": "a", "paths": ["a.py"], "consumers": []},
            {"id": "b", "paths": ["b.py"], "consumers": ["tests/b.py"]},
        ]
        coloring = {"k": 2, "assignment": {"a": 1, "b": 0}}

        result = compiler.build_carrier_specs(
            touch_sets,
            coloring,
            {"max_paths_per_carrier": 64, "max_consumers_per_carrier": 128},
        )

        self.assertEqual([row["carrier_id"] for row in result], ["carrier-001", "carrier-002"])
        self.assertEqual(result[0]["touch_set_ids"], ["b"])
        self.assertEqual(result[1]["touch_set_ids"], ["a"])
        self.assertEqual(result[0]["path_count"], 1)
        self.assertEqual(result[0]["unique_consumer_count"], 1)
        self.assertTrue(result[0]["within_capacity"])

    def test_carrier_specs_refuse_capacity_overrun(self) -> None:
        compiler = load_compiler()
        touch_sets = [
            {"id": "a", "paths": ["a.py"], "consumers": ["tests/a.py"]},
            {"id": "b", "paths": ["b.py"], "consumers": ["tests/b.py"]},
        ]

        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.build_carrier_specs(
                touch_sets,
                {"k": 1, "assignment": {"a": 0, "b": 0}},
                {"max_paths_per_carrier": 1, "max_consumers_per_carrier": 10},
            )

        self.assertEqual(raised.exception.code, "CARRIER_CAPACITY_EXCEEDED")

    def test_equivalent_colorings_choose_lexicographic_assignment(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "solve_minimum_coloring")

        result = compiler.solve_minimum_coloring(["b", "a"], [], [], max_states=100)

        self.assertEqual(list(result["assignment"]), ["a", "b"])
        self.assertEqual(result["assignment"], {"a": 0, "b": 0})

    def test_two_runs_are_byte_identical(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "solve_minimum_coloring")
        args = (["c", "a", "b"], [("a", "b"), ("b", "c")], [("a", "c")])

        first = compiler.solve_minimum_coloring(*args, max_states=1000)
        second = compiler.solve_minimum_coloring(*args, max_states=1000)

        self.assertEqual(compiler.canonical_json(first), compiler.canonical_json(second))

    def test_current_tree_exact_coloring_and_carriers_verify(self) -> None:
        compiler = load_compiler()
        policy = policy_fixture()
        path_rows = compiler.classify_paths(compiler.tracked_paths(ROOT), policy)
        census = compiler.discover_consumers(ROOT, path_rows)
        dependencies = compiler.build_dependency_graph(census["rows"], policy)
        touch_sets = compiler.build_touch_sets(path_rows, census["rows"])
        conflict_graph = compiler.build_conflict_graph(touch_sets, policy["reviewability"])
        precedence = compiler.build_touch_set_precedence(touch_sets, dependencies)
        graph = {**conflict_graph, "precedence": precedence}

        coloring = compiler.solve_minimum_coloring(
            graph["nodes"],
            [tuple(edge) for edge in graph["edges"]],
            [tuple(edge) for edge in precedence],
            max_states=policy["reviewability"]["max_exact_search_states"],
            node_weights=graph["node_weights"],
            capacities=graph["capacities"],
        )
        verified = compiler.verify_coloring_certificate(
            graph,
            coloring,
            max_states=policy["reviewability"]["max_exact_search_states"],
        )
        carriers = compiler.build_carrier_specs(touch_sets, coloring, graph["capacities"])

        self.assertEqual(verified, coloring)
        self.assertEqual(len(carriers), coloring["k"])
        self.assertEqual(
            sorted(item for carrier in carriers for item in carrier["touch_set_ids"]),
            sorted(graph["nodes"]),
        )


class ReceiptCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "receipt.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unexecuted_leg_is_skip_never_pass(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "red_row")
        row = compiler.red_row("linux_cpu", executed=False, reason="runner absent")
        self.assertEqual(row["status"], "SKIP")
        self.assertEqual(row["reason"], "runner absent")

    def test_missing_domain_api_remains_fail(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "adjudicate_red_leg")
        row = compiler.adjudicate_red_leg(
            "direct_chain", returncode=2, failure_class="DOMAIN_API_ABSENT"
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["failure_class"], "DOMAIN_API_ABSENT")

    def test_existing_destination_refuses_overwrite(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "write_no_overwrite_receipt")
        self.output.write_text("owned", encoding="utf-8")
        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.write_no_overwrite_receipt(self.output, {"k": 1})
        self.assertEqual(raised.exception.code, "OUTPUT_EXISTS")

    def test_baseline_preflight_refuses_existing_stream_sibling(self) -> None:
        compiler = load_compiler()
        sibling = self.output.parent / "linux.stdout"
        sibling.write_text("owned", encoding="utf-8")
        paths = compiler._baseline_stream_paths(self.output, ["linux"])
        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler._refuse_existing_outputs(
                [self.output] + [path for pair in paths.values() for path in pair]
            )
        self.assertEqual(raised.exception.code, "OUTPUT_EXISTS")

    def test_write_receipt_uses_raw_and_self_conventions(self) -> None:
        compiler = load_compiler()
        raw_sha, self_sha = compiler.write_no_overwrite_receipt(
            self.output, {"schema_version": "fixture", "k": 1}
        )
        raw = self.output.read_bytes()
        payload = json.loads(raw)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw_sha, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self_sha, payload["self_sha256"])
        self.assertEqual(self_sha, compiler.derive_self_sha256(payload))

    def test_mutated_receipt_self_refuses_before_recompute(self) -> None:
        compiler = load_compiler()
        compiler.write_no_overwrite_receipt(
            self.output, {"schema_version": "fixture", "k": 1}
        )
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        payload["k"] = 2
        self.output.write_bytes(compiler.canonical_json(payload) + b"\n")
        with self.assertRaises(compiler.ArchitectureMapError) as raised:
            compiler.verify_receipt(ROOT, POLICY_PATH, self.output)
        self.assertEqual(raised.exception.code, "RECEIPT_SELF_MISMATCH")

    def test_compile_receipt_is_deterministic_and_verifies_from_source(self) -> None:
        compiler = load_compiler()
        require_functions(compiler, "compile_receipt", "verify_receipt")
        policy = policy_fixture()
        red_matrix = [compiler.red_row("fixture", executed=False, reason="not requested")]
        first = compiler.compile_receipt(ROOT, policy, red_matrix)
        second = compiler.compile_receipt(ROOT, policy, red_matrix)
        self.assertEqual(compiler.canonical_json(first), compiler.canonical_json(second))
        self.assertEqual(
            first["declared_host_envelope"]["identity_rule"],
            "EMBER_PROJECT_IDENTITY_IS_HARDWARE_INDEPENDENT",
        )
        self.assertEqual(first["verifier_cost_contract"]["gate_placement"], "PR_WAVE")
        self.assertEqual(
            first["consumer_reference_bound"]["regex_sha256"],
            hashlib.sha256(compiler._REFERENCE_RE.pattern.encode("utf-8")).hexdigest(),
        )
        compiler.write_no_overwrite_receipt(self.output, first)
        verdict = compiler.verify_receipt(ROOT, POLICY_PATH, self.output)
        self.assertEqual(verdict["result"], "PASS")
        self.assertEqual(
            verdict["self_sha256"],
            json.loads(self.output.read_text(encoding="utf-8"))["self_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
