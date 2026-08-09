# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "ember-restart-3b" / "certified_train_launch.py"
CERTIFIED_TEST_PATH = ROOT / "tests" / "ember_restart_model" / "test_certified_train_launch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("certified_train_launch", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_battery():
    path = ROOT / "scripts" / "r1_exit_battery.py"
    spec = importlib.util.spec_from_file_location("r1_exit_battery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_frontier():
    path = ROOT / "scripts" / "frontier_receipt.py"
    spec = importlib.util.spec_from_file_location("frontier_receipt", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_certified_fixtures():
    spec = importlib.util.spec_from_file_location(
        "test_certified_train_launch_fixtures", CERTIFIED_TEST_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Issue1508AttemptRetentionTests(unittest.TestCase):
    def test_failed_attempt_retains_root_level_receipts_logs_and_telemetry(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            artifacts = root / "artifacts"
            artifacts.mkdir(parents=True)
            root_files = {
                "runner-receipt.json": "runner",
                "runner-receipt-child.log": "child",
                "runner-receipt-certified-launch.json": "execution",
                "telemetry.jsonl": '{"source":"ember-restart-3b","kind":"train_step"}\n',
            }
            for name, contents in root_files.items():
                (root / name).write_text(contents, encoding="utf-8")
            (artifacts / "checkpoint.json").write_text("checkpoint", encoding="utf-8")

            retained = module.retain_failed_attempt(
                root, reason="CHILD_FAILED", timestamp="20260808T230502Z"
            )

            for name in (*root_files, "artifacts/checkpoint.json"):
                self.assertTrue((retained / name).is_file(), name)
                self.assertFalse((root / name).exists(), name)
            self.assertTrue((root / "artifacts").is_dir())
            self.assertIn(
                retained / "telemetry.jsonl",
                load_battery().find_telemetry_files(root),
            )

    def test_failed_attempt_is_retained_under_root_and_layout_is_discoverable(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            artifacts = root / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "runner-receipt.json").write_text("{}", encoding="utf-8")
            (artifacts / "telemetry").mkdir()
            (artifacts / "telemetry" / "events.jsonl").write_text(
                '{"source":"ember-restart-3b","kind":"train_step"}\n',
                encoding="utf-8",
            )
            retained = module.retain_failed_attempt(
                root, reason="CHILD_FAILED", timestamp="20260808T230500Z"
            )
            self.assertTrue(retained.name.startswith("attempt-1-CHILD_FAILED-"))
            self.assertFalse(any(artifacts.iterdir()))
            self.assertTrue((retained / "artifacts" / "runner-receipt.json").is_file())
            self.assertTrue((retained / "artifacts" / "telemetry" / "events.jsonl").is_file())
            self.assertEqual(
                json.loads((retained / "attempt-retention.json").read_text())[
                    "schema_version"
                ],
                "ember-run-attempt-retention-v1",
            )
            self.assertTrue((ROOT / module.RUN_ROOT_LAYOUT_SPEC_PATH).is_file())

            retry = root / "artifacts" / "retry-marker.txt"
            retry.write_text("retry", encoding="utf-8")
            retained_again = module.retain_failed_attempt(
                root, reason="CHILD_FAILED", timestamp="20260808T230501Z"
            )
            self.assertTrue(retained_again.name.startswith("attempt-2-CHILD_FAILED-"))
            self.assertTrue((retained_again / "artifacts" / "retry-marker.txt").is_file())

    def test_retention_rejects_traversal_and_battery_keeps_telemetry(self):
        module = load_module()
        battery = load_battery()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            (root / "artifacts").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "closed uppercase token"):
                module.retain_failed_attempt(root, reason="../ESCAPE", timestamp="20260808T230500Z")
            retained = root / "attempt-1-CHILD_FAILED-20260808T230500Z"
            (retained / "telemetry").mkdir(parents=True)
            telemetry = retained / "telemetry" / "train.jsonl"
            telemetry.write_text(
                '{"source":"ember-restart-3b","kind":"train_step"}\n',
                encoding="utf-8",
            )
            evidence = retained / "disk-budget-runner-receipt.json"
            evidence.write_text("{}", encoding="utf-8")
            self.assertIn(telemetry, battery.find_telemetry_files(root))
            self.assertTrue(battery._evidence_excluded(evidence, root))
            self.assertTrue((ROOT / module.RUN_ROOT_LAYOUT_SPEC_PATH).is_file())

    def test_retention_rejects_external_artifact_without_staging_residue(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            (root / "artifacts").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "artifact_root must stay"):
                module.retain_failed_attempt(
                    root,
                    reason="CHILD_FAILED",
                    timestamp="20260808T230504Z",
                    artifact_root=pathlib.Path(directory) / "outside",
                )
            self.assertEqual(list(root.glob(".attempt-*.staging")), [])

    def test_retention_rolls_back_when_promotion_fails(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            artifacts = root / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "checkpoint.json").write_text("checkpoint", encoding="utf-8")
            original_rename = pathlib.Path.rename

            def fail_promotion(source, destination):
                if source.name.endswith(".staging"):
                    raise OSError("injected promotion failure")
                return original_rename(source, destination)

            with mock.patch.object(pathlib.Path, "rename", new=fail_promotion):
                with self.assertRaisesRegex(OSError, "promotion failure"):
                    module.retain_failed_attempt(
                        root,
                        reason="CHILD_FAILED",
                        timestamp="20260808T230505Z",
                    )
            self.assertTrue((artifacts / "checkpoint.json").is_file())
            self.assertEqual(list(root.glob(".attempt-*.staging")), [])
            self.assertEqual(list(root.glob("attempt-*")), [])

    def test_retention_binds_the_actual_launch_artifact_root(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            (outputs / "checkpoint.json").write_text("checkpoint", encoding="utf-8")
            retained = module.retain_failed_attempt(
                root,
                reason="CHILD_FAILED",
                timestamp="20260808T230506Z",
                artifact_root=outputs,
            )
            retention = json.loads(
                (retained / "attempt-retention.json").read_text(encoding="utf-8")
            )
            self.assertEqual(retention["source_relative"], "outputs")
            self.assertEqual(
                retention["retained_relative"],
                f"{retained.name}/outputs",
            )
            self.assertTrue((retained / "outputs" / "checkpoint.json").is_file())

    def test_retention_handles_a_nested_launch_artifact_root_once(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            outputs = root / "outputs"
            artifacts = outputs / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "checkpoint.json").write_text(
                "checkpoint", encoding="utf-8"
            )
            (outputs / "sibling.log").write_text("log", encoding="utf-8")

            retained = module.retain_failed_attempt(
                root,
                reason="CHILD_FAILED",
                timestamp="20260808T230507Z",
                artifact_root=artifacts,
            )

            self.assertTrue(
                (retained / "outputs" / "artifacts" / "checkpoint.json").is_file()
            )
            self.assertTrue((retained / "outputs" / "sibling.log").is_file())
            self.assertTrue(artifacts.is_dir())

    def test_layout_spec_names_the_battery_discovery_classes(self):
        module = load_module()
        spec = (ROOT / module.RUN_ROOT_LAYOUT_SPEC_PATH).read_text(encoding="utf-8")
        for required in (
            "frontier-receipt.json",
            "frozen-eval-results.json",
            "energy-proxy-receipt.json",
            "human-interventions.json",
            "walls-checklist.json",
            "receipts/run-attempts.jsonl",
        ):
            self.assertIn(required, spec)

    def test_frontier_registry_snapshot_changes_after_late_launch(self):
        frontier = load_frontier()
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "repo"
            registry = repo / "receipts" / "run-attempts.jsonl"
            run_root = repo / "run-1"
            registry.parent.mkdir(parents=True)
            run_root.mkdir(parents=True)
            registry.write_text('{"run_id":"run-1"}\n', encoding="utf-8")
            frontier.REPO_ROOT = repo
            frontier.RUN_ATTEMPTS_REGISTRY = "receipts/run-attempts.jsonl"

            coverage = frontier.ledger_all_compute_coverage(
                run_root, "run-1", "m" * 64
            )
            _, registry_prefix = frontier._read_registry_rows_and_prefix(registry)
            registry_prefix_sha256 = hashlib.sha256(registry_prefix).hexdigest()
            self.assertEqual(
                coverage["registry_prefix_sha256"], registry_prefix_sha256
            )
            self.assertEqual(coverage["registry_rows"], 1)

            # A launch after mint changes the closed registry snapshot, so the
            # previously minted receipt is no longer admissible to the battery.
            registry.write_text(
                '{"run_id":"run-1"}\n{"run_id":"late-launch"}\n',
                encoding="utf-8",
            )
            self.assertEqual(
                coverage["registry_prefix_sha256"], registry_prefix_sha256
            )
            self.assertEqual(coverage["registry_rows"], 1)
            self.assertNotEqual(
                coverage["registry_prefix_sha256"], frontier._sha256(registry)
            )

    def test_execute_failure_retains_certified_receipt_before_retry(self):
        module = load_module()
        battery = load_battery()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "run-root"
            artifacts = root / "artifacts"
            artifacts.mkdir(parents=True)
            runner_receipt = root / "runner-receipt.json"
            runner_receipt.write_text("runner", encoding="utf-8")
            (artifacts / "checkpoint.json").write_text("checkpoint", encoding="utf-8")
            launch = module.ValidatedLaunch(
                certificate_sha256="a" * 64,
                run_spec_sha256="b" * 64,
                public_master_sha="c" * 40,
                closure_sha256=None,
                artifact_root=artifacts,
                custody_root=root,
                runner_receipt=runner_receipt,
                seed=7,
                write_budget_bytes=4096,
                max_records=1,
                max_c_write_gib=1.0,
                max_b_write_gib=1.0,
            )

            class FailedChild:
                returncode = 23

            self.assertEqual(
                module.execute_validated_launch(
                    ROOT,
                    launch,
                    run_process=lambda *args, **kwargs: FailedChild(),
                ),
                23,
            )
            retained = next(root.glob("attempt-1-CHILD_FAILED-*"))
            self.assertTrue((retained / "runner-receipt-child.log").is_file())
            self.assertTrue((retained / "artifacts" / "checkpoint.json").is_file())
            retained_receipt = retained / "runner-receipt-certified-launch.json"
            self.assertTrue(
                retained_receipt.is_file(),
                "the failed execution receipt must be retained before retry",
            )
            self.assertEqual(
                json.loads(retained_receipt.read_text(encoding="utf-8"))[
                    "attempt_retention"
                ]["status"],
                "RETAINED",
            )
            self.assertEqual(
                pathlib.Path(
                    json.loads(retained_receipt.read_text(encoding="utf-8"))["child_log"]
                ).resolve(),
                (retained / "runner-receipt-child.log").resolve(),
            )
            self.assertEqual(
                pathlib.Path(
                    json.loads(retained_receipt.read_text(encoding="utf-8"))[
                        "runner_receipt"
                    ]
                ).resolve(),
                (retained / "runner-receipt.json").resolve(),
            )
            root_failure_receipt = json.loads(
                (root / "runner-receipt-certified-launch.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                pathlib.Path(root_failure_receipt["runner_receipt"]).resolve(),
                (retained / "runner-receipt.json").resolve(),
            )
            self.assertTrue((root / "artifacts").is_dir())
            self.assertTrue(
                battery._evidence_excluded(
                    retained / "runner-receipt-certified-launch.json", root
                )
            )

            class SuccessfulChild:
                returncode = 0

            self.assertEqual(
                module.execute_validated_launch(
                    ROOT,
                    launch,
                    run_process=lambda *args, **kwargs: SuccessfulChild(),
                ),
                0,
            )
            self.assertEqual(
                json.loads(
                    retained_receipt.read_text(
                        encoding="utf-8"
                    )
                )["exit_code"],
                23,
            )
            self.assertEqual(
                json.loads(
                    (root / "runner-receipt-certified-launch.json").read_text(
                        encoding="utf-8"
                    )
                )["exit_code"],
                0,
            )

    def test_failed_bundle_preserves_validated_authority_for_retry(self):
        module = load_module()
        fixtures = load_certified_fixtures()
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            paths = fixtures.write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(module, "read_current_master", return_value=fixtures.SHA):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )

            class FailedChild:
                returncode = 23

            self.assertEqual(
                module.execute_validated_launch(
                    paths["repo"],
                    launch,
                    run_process=lambda *args, **kwargs: FailedChild(),
                ),
                23,
            )
            for key in ("certificate", "ledger", "run_spec", "completion"):
                self.assertTrue(paths[key].is_file(), key)
            retained = next(paths["custody_root"].glob("attempt-1-CHILD_FAILED-*"))
            retention = json.loads(
                (retained / "attempt-retention.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(retention["protected_authority_relative"]),
                {
                    path.relative_to(paths["custody_root"]).as_posix()
                    for path in (
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                        paths["completion"],
                    )
                },
            )
            with mock.patch.object(module, "read_current_master", return_value=fixtures.SHA):
                reloaded = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(reloaded.authority_paths, launch.authority_paths)

            class SuccessfulChild:
                returncode = 0

            self.assertEqual(
                module.execute_validated_launch(
                    paths["repo"],
                    reloaded,
                    run_process=lambda *args, **kwargs: SuccessfulChild(),
                ),
                0,
            )

    def test_failed_resume_preserves_checkpoint_and_evidence_for_revalidation(self):
        module = load_module()
        fixtures = load_certified_fixtures()
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            paths = fixtures.write_valid_bundle(pathlib.Path(directory))
            fixtures.install_model_config(
                paths["repo"], fixtures.ARCHITECTURE_REVISION
            )
            checkpoint, evidence = fixtures.install_resume_material(
                paths["custody_root"]
            )
            fixtures.set_resume_paths(paths, checkpoint, evidence)
            fixtures.authorize_resume_roots(paths, paths["custody_root"])

            with mock.patch.object(
                module, "read_current_master", return_value=fixtures.SHA
            ):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertIn(checkpoint.resolve(), launch.authority_paths)
            self.assertIn(evidence.resolve(), launch.authority_paths)

            class FailedChild:
                returncode = 23

            self.assertEqual(
                module.execute_validated_launch(
                    paths["repo"],
                    launch,
                    run_process=lambda *args, **kwargs: FailedChild(),
                ),
                23,
            )
            self.assertTrue(checkpoint.is_dir())
            self.assertTrue(evidence.is_file())
            with mock.patch.object(
                module, "read_current_master", return_value=fixtures.SHA
            ):
                reloaded = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(reloaded.resume_checkpoint, checkpoint)
            self.assertEqual(reloaded.resume_evidence_path, evidence)

            class SuccessfulChild:
                returncode = 0

            self.assertEqual(
                module.execute_validated_launch(
                    paths["repo"],
                    reloaded,
                    run_process=lambda *args, **kwargs: SuccessfulChild(),
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
