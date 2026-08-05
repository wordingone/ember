# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "ember-restart-3b" / "certified_train_launch.py"
SHA = "a" * 40
EVIDENCE_SHA256 = "b" * 64


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def load_module():
    spec = importlib.util.spec_from_file_location("certified_train_launch", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_completion_receipt() -> dict[str, object]:
    return {
        "schema": "ember-01-completion-receipt-v1",
        "ok": True,
        "verified_at_utc": "2026-07-23T08:00:00+00:00",
        "goal_id": "EMBER-02",
        "completion_subject_goal_id": "EMBER-01",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "certificate_legs": {str(index): "resolved-true" for index in range(1, 10)},
        "leg_detail": {},
        "leg_summary": {
            "resolved_true": [str(index) for index in range(1, 10)],
            "resolved_false": [],
            "unresolved": [],
        },
        "claim_scope": {
            "training_completed": False,
            "model_completed": False,
            "runtime_completed": False,
            "benchmark_completed": False,
            "note": "EMBER-01 spine only",
        },
        "checkout": {
            "head": SHA,
            "clean": True,
            "detached": True,
            "head_unchanged": True,
            "status": "",
            "status_before": "",
        },
        "selection": {
            "selected_goal_suffix": "EMBER-GOAL-GRAPH.json",
            "selector_sha256": "0" * 64,
            "unchanged_during_verification": True,
        },
        "authority_certificate": {"ok": True},
    }


def valid_scope(artifact_root: pathlib.Path, custody_root: pathlib.Path) -> dict[str, object]:
    return {
        "purpose": "BOUNDED_CANARY",
        "allowed_modes": ["governed-vertical"],
        "max_optimizer_steps": 200,
        "max_records": 1,
        "max_active_expert_families": 1,
        "max_gpu_vram_gib": 20.0,
        "max_transient_checkpoint_gib": 4.0,
        "max_wall_minutes": 15.0,
        "max_b_write_gib": 16.0,
        "max_c_write_gib": 0.0,
        "max_write_budget_bytes": 16 * 1024**3,
        "allowed_artifact_roots": [str(artifact_root)],
        "allowed_custody_roots": [str(custody_root)],
        "model_server_allowed": False,
        "wsl_allowed": False,
        "persistent_worker_allowed": False,
    }


def valid_run_spec(
    certificate_sha256: str,
    artifact_root: pathlib.Path,
    custody_root: pathlib.Path,
) -> dict[str, object]:
    return {
        "schema_version": "ember-certified-train-run-v1",
        "certificate_sha256": certificate_sha256,
        "run_id": "owned-3b-canary-test",
        "seed": 83,
        "runner_receipt": str(custody_root / "runner-receipt.json"),
        "requested_scope": {
            "mode": "governed-vertical",
            "optimizer_steps": 1,
            "max_records": 1,
            "active_expert_families": 1,
            "gpu_vram_gib": 20.0,
            "transient_checkpoint_gib": 4.0,
            "wall_minutes": 15.0,
            "max_b_write_gib": 16.0,
            "max_c_write_gib": 0.0,
            "write_budget_bytes": 16 * 1024**3,
            "artifact_root": str(artifact_root),
            "custody_root": str(custody_root),
        },
    }


def write_valid_bundle(root: pathlib.Path) -> dict[str, pathlib.Path]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    custody_root = root / "custody"
    artifact_root = custody_root / "artifacts"
    artifact_root.mkdir(parents=True)

    completion_path = custody_root / "ember-01-completion.json"
    write_json(completion_path, valid_completion_receipt())
    completion_sha256 = sha256_bytes(completion_path.read_bytes())

    certificate = {
        "schema_version": "ember-spine-certified-declaration-v1",
        "event_kind": "SPINE_CERTIFIED",
        "declared_by_role": "EMBER_CERTIFICATE_AUTHORITY",
        "declared_at_utc": "2026-07-23T08:00:00+00:00",
        "superseded_by": None,
        "completion_receipt_path": str(completion_path),
        "completion_receipt_sha256": completion_sha256,
        "public_master_sha": SHA,
        "checkout_sha256": EVIDENCE_SHA256,
        "config_sha256": EVIDENCE_SHA256,
        "tokenizer_sha256": EVIDENCE_SHA256,
        "input_authority_sha256": EVIDENCE_SHA256,
        "cli_binary_sha256": EVIDENCE_SHA256,
        "launch_packet_sha256": EVIDENCE_SHA256,
        "board_receipt_sha256": EVIDENCE_SHA256,
        "benchmark_registry_sha256": EVIDENCE_SHA256,
        "failure_class_ledger_sha256": EVIDENCE_SHA256,
        "subject_manifest_sha256": EVIDENCE_SHA256,
        "seat_sha256": EVIDENCE_SHA256,
        "root_summary_sha256": EVIDENCE_SHA256,
        "declaration_conjuncts": {
            "record_coherent": True,
            "nine_leg_completion": True,
            "birth_failure_classes_disposed": True,
        },
        "execution_scope": valid_scope(artifact_root, custody_root),
    }
    certificate_path = custody_root / "spine-certified.json"
    write_json(certificate_path, certificate)
    certificate_sha256 = sha256_bytes(certificate_path.read_bytes())

    ledger_path = custody_root / "declaration-ledger.jsonl"
    ledger_path.write_bytes(
        canonical_bytes(
            {
                "schema_version": "ember-spine-declaration-ledger-row-v1",
                "event_kind": "SPINE_CERTIFIED",
                "declared_by_role": "EMBER_CERTIFICATE_AUTHORITY",
                "certificate_sha256": certificate_sha256,
            }
        )
    )

    run_spec_path = custody_root / "run-spec.json"
    write_json(
        run_spec_path,
        valid_run_spec(certificate_sha256, artifact_root, custody_root),
    )
    return {
        "repo": repo,
        "certificate": certificate_path,
        "ledger": ledger_path,
        "run_spec": run_spec_path,
        "completion": completion_path,
        "artifact_root": artifact_root,
        "custody_root": custody_root,
    }


def rewrite_certificate(
    paths: dict[str, pathlib.Path],
    mutate,
) -> dict[str, object]:
    certificate = json.loads(paths["certificate"].read_text(encoding="utf-8"))
    mutate(certificate)
    write_json(paths["certificate"], certificate)
    certificate_sha256 = sha256_bytes(paths["certificate"].read_bytes())
    write_json(
        paths["ledger"],
        {
            "schema_version": "ember-spine-declaration-ledger-row-v1",
            "event_kind": "SPINE_CERTIFIED",
            "declared_by_role": "EMBER_CERTIFICATE_AUTHORITY",
            "certificate_sha256": certificate_sha256,
        },
    )
    run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
    run_spec["certificate_sha256"] = certificate_sha256
    write_json(paths["run_spec"], run_spec)
    return certificate


class CertifiedTrainLaunchTests(unittest.TestCase):
    def test_valid_declared_subset_is_accepted(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.public_master_sha, SHA)
            self.assertEqual(launch.max_records, 1)
            self.assertEqual(launch.artifact_root, paths["artifact_root"])

    def test_schema_valid_certificate_absent_from_declaration_ledger_fails(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            paths["ledger"].write_text("", encoding="utf-8")
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "declaration ledger membership"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_certificate_and_linked_receipt_negative_matrix(self) -> None:
        module = load_module()
        cases = {
            "wrong declaration role": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "declared_by_role", "UNAUTHORIZED_ROLE"
                    ),
                ),
                "declaration role",
                SHA,
            ),
            "wrong declaration event": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "event_kind", "SPINE_PROPOSED"
                    ),
                ),
                "declaration event",
                SHA,
            ),
            "superseded certificate": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "superseded_by", "b" * 64
                    ),
                ),
                "superseded",
                SHA,
            ),
            "wrong current master": (
                lambda paths: None,
                "current public master",
                "c" * 40,
            ),
            "tampered linked completion": (
                lambda paths: paths["completion"].write_text(
                    paths["completion"].read_text(encoding="utf-8") + " ",
                    encoding="utf-8",
                ),
                "completion receipt hash",
                SHA,
            ),
            "non-nine legs": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["certificate_legs"].pop("9"),
                ),
                "exactly nine",
                SHA,
            ),
            "checkout not detached": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["checkout"].__setitem__(
                        "detached", False
                    ),
                ),
                "checkout integrity",
                SHA,
            ),
            "wrong completion subject": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt.__setitem__(
                        "completion_subject_goal_id", "EMBER-02"
                    ),
                ),
                "completion subject is not EMBER-01",
                SHA,
            ),
            "selection changed": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["selection"].__setitem__(
                        "unchanged_during_verification", False
                    ),
                ),
                "selection integrity",
                SHA,
            ),
            "false B7 conjunct": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate[
                        "declaration_conjuncts"
                    ].__setitem__("record_coherent", False),
                ),
                "B7 declaration conjunct",
                SHA,
            ),
        }
        for label, (mutate, error, current_master) in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    paths = write_valid_bundle(pathlib.Path(directory))
                    mutate(paths)
                    with mock.patch.object(
                        module, "read_current_master", return_value=current_master
                    ):
                        with self.assertRaisesRegex(ValueError, error):
                            module.validate_certified_request(
                                paths["repo"],
                                paths["certificate"],
                                paths["ledger"],
                                paths["run_spec"],
                            )

    def test_raw_b6_receipt_cannot_substitute_for_b7_certificate(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            paths["certificate"].write_bytes(paths["completion"].read_bytes())
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "certificate schema"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_unknown_certificate_field_fails_closed(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            certificate = json.loads(
                paths["certificate"].read_text(encoding="utf-8")
            )
            certificate["unexpected"] = True
            write_json(paths["certificate"], certificate)
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "certificate schema keys"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_git_object_and_content_digest_widths_are_not_interchangeable(
        self,
    ) -> None:
        module = load_module()
        cases = {
            "git field carrying 64 hex": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "public_master_sha", EVIDENCE_SHA256
                    ),
                ),
                "40-hex Git object ID",
            ),
            "content field carrying 40 hex": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "config_sha256", SHA
                    ),
                ),
                "lowercase SHA-256",
            ),
            "linked checkout head carrying 64 hex": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["checkout"].__setitem__(
                        "head", EVIDENCE_SHA256
                    ),
                ),
                "completion checkout head",
            ),
            # Post-#1419 a differing head is checked for ANCESTRY instead of
            # equality; the fixture repo has no git history, so the check fails
            # CLOSED rather than silently accepting an unrelated head. The
            # ancestor-accepted and non-ancestor-refused paths are covered in
            # CompletionHeadAncestorTests.
            "linked checkout head differs from declared master": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["checkout"].__setitem__(
                        "head", "c" * 40
                    ),
                ),
                "ancestry is unprovable",
            ),
        }
        for label, (mutate, error) in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    paths = write_valid_bundle(pathlib.Path(directory))
                    mutate(paths)
                    with mock.patch.object(
                        module, "read_current_master", return_value=SHA
                    ):
                        with self.assertRaisesRegex(ValueError, error):
                            module.validate_certified_request(
                                paths["repo"],
                                paths["certificate"],
                                paths["ledger"],
                                paths["run_spec"],
                            )

    def test_every_scope_axis_fails_above_certificate(self) -> None:
        module = load_module()
        cases = {
            "mode": "semantic",
            "optimizer_steps": 201,
            "max_records": 2,
            "active_expert_families": 2,
            "gpu_vram_gib": 20.1,
            "transient_checkpoint_gib": 4.1,
            "wall_minutes": 15.1,
            "max_b_write_gib": 16.1,
            "max_c_write_gib": 0.1,
            "write_budget_bytes": 16 * 1024**3 + 1,
            "artifact_root": "B:/outside-artifacts",
            "custody_root": "B:/outside-custody",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    paths = write_valid_bundle(pathlib.Path(directory))
                    request = json.loads(
                        paths["run_spec"].read_text(encoding="utf-8")
                    )
                    request["requested_scope"][field] = value
                    write_json(paths["run_spec"], request)
                    with mock.patch.object(
                        module, "read_current_master", return_value=SHA
                    ):
                        with self.assertRaisesRegex(
                            ValueError, f"scope exceeds certificate: {field}"
                        ):
                            module.validate_certified_request(
                                paths["repo"],
                                paths["certificate"],
                                paths["ledger"],
                                paths["run_spec"],
                            )

    def test_run_spec_above_certificate_scope_fails_before_runner_construction(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            request = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            request["requested_scope"]["active_expert_families"] = 2
            write_json(paths["run_spec"], request)
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "scope exceeds certificate"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_valid_request_builds_exact_governed_vertical_disk_runner_argv(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            argv = module.build_runner_argv(paths["repo"], launch)
            self.assertEqual(argv[0], sys.executable)
            self.assertEqual(
                argv[1],
                str(
                    paths["repo"]
                    / "tools"
                    / "ember-restart-3b"
                    / "disk_budget_runner.py"
                ),
            )
            self.assertEqual(argv.count("governed-vertical"), 1)
            self.assertNotIn("semantic", argv)
            self.assertEqual(argv[argv.index("--max-records") + 1], "1")
            self.assertEqual(
                argv[argv.index("--write-budget-bytes") + 1],
                str(16 * 1024**3),
            )

    def test_scope_failure_occurs_before_run_process(self) -> None:
        module = load_module()
        calls: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            request = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            request["requested_scope"]["active_expert_families"] = 2
            write_json(paths["run_spec"], request)
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "scope exceeds certificate"):
                    module.certify_and_execute(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                        run_process=lambda *args, **kwargs: calls.append(
                            (args, kwargs)
                        ),
                    )
        self.assertEqual(calls, [])

    def test_valid_execution_uses_argv_without_shell_and_writes_receipt(self) -> None:
        module = load_module()
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0)

        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                exit_code = module.certify_and_execute(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                    run_process=fake_run,
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            argv, kwargs = calls[0]
            self.assertIsInstance(argv, list)
            self.assertIs(kwargs["shell"], False)
            self.assertIs(kwargs["check"], False)
            self.assertEqual(kwargs["cwd"], paths["repo"])
            self.assertEqual(
                kwargs["env"]["PYTHONDONTWRITEBYTECODE"],
                "1",
                "runner argv is certificate-visible (execution receipt pins "
                "argv[1]), so bytecode suppression must ride the spawn env "
                "rather than an -B argv insertion",
            )
            execution_receipt = (
                paths["custody_root"] / "runner-receipt-certified-launch.json"
            )
            receipt = json.loads(execution_receipt.read_text(encoding="utf-8"))
            self.assertEqual(receipt["exit_code"], 0)
            self.assertEqual(receipt["argv"], argv)
            self.assertFalse(
                any(receipt["claim_scope"].values()),
                "execution receipt must not claim capability or admission",
            )

    def test_child_stdout_is_redirected_to_a_custody_log_not_inherited(
        self,
    ) -> None:
        """Regression for #1408: the fixed runner must never inherit this
        consumer's stdout. A noisy child (training-log lines before any JSON)
        must not corrupt the consumer's own final stdout line, which the
        cockpit parses as the certified-launch handshake."""
        module = load_module()
        calls: list[dict[str, object]] = []

        def noisy_run(argv, **kwargs):
            calls.append(kwargs)
            child_stdout = kwargs.get("stdout")
            self.assertIsNotNone(
                child_stdout,
                "child stdout must be redirected (not inherited) so it "
                "cannot land in the consumer's own stdout stream",
            )
            child_stdout.write(b"epoch 1/10 loss=0.42\nepoch 2/10 loss=0.31\n")
            child_stdout.flush()
            self.assertEqual(
                kwargs.get("stderr"),
                subprocess.STDOUT,
                "child stderr must be merged into the same redirected log",
            )
            return subprocess.CompletedProcess(argv, 0)

        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with contextlib.redirect_stdout(io.StringIO()) as captured:
                    exit_code = module.certify_and_execute(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                        run_process=noisy_run,
                    )
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            # The consumer itself printed nothing to real stdout during the
            # child's run (main() prints its single JSON line separately) --
            # the noisy child lines never touched this process's stdout.
            self.assertEqual(captured.getvalue(), "")

            execution_receipt = (
                paths["custody_root"] / "runner-receipt-certified-launch.json"
            )
            receipt = json.loads(execution_receipt.read_text(encoding="utf-8"))
            self.assertIsInstance(receipt.get("child_log"), str)
            child_log_path = pathlib.Path(receipt["child_log"])
            self.assertTrue(
                child_log_path.is_relative_to(paths["custody_root"]),
                "child log must live under custody_root, not be devnulled",
            )
            self.assertIn("epoch 1/10", child_log_path.read_text(encoding="utf-8"))

    def test_child_failure_is_propagated_and_receipted(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))

            def fail(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 17)

            with mock.patch.object(module, "read_current_master", return_value=SHA):
                exit_code = module.certify_and_execute(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                    run_process=fail,
                )
            self.assertEqual(exit_code, 17)
            receipt = json.loads(
                (
                    paths["custody_root"]
                    / "runner-receipt-certified-launch.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["exit_code"], 17)

    def test_runner_receipt_outside_authorized_custody_fails_before_process(
        self,
    ) -> None:
        module = load_module()
        calls: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["runner_receipt"] = str(
                pathlib.Path(directory) / "outside" / "receipt.json"
            )
            write_json(paths["run_spec"], run_spec)
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(
                    ValueError, "scope exceeds certificate: runner_receipt"
                ):
                    module.certify_and_execute(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                        run_process=lambda *args, **kwargs: calls.append(
                            (args, kwargs)
                        ),
                    )
        self.assertEqual(calls, [])

    def test_cli_scope_escalation_exits_before_runner_receipt(self) -> None:
        current_master = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            _rewrite_completion(
                paths,
                lambda receipt: receipt["checkout"].__setitem__(
                    "head", current_master
                ),
            )
            rewrite_certificate(
                paths,
                lambda certificate: certificate.__setitem__(
                    "public_master_sha", current_master
                ),
            )
            request = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            request["requested_scope"]["active_expert_families"] = 2
            write_json(paths["run_spec"], request)

            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--root",
                    str(ROOT),
                    "--certificate",
                    str(paths["certificate"]),
                    "--declaration-ledger",
                    str(paths["ledger"]),
                    "--run-spec",
                    str(paths["run_spec"]),
                ],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "scope exceeds certificate: active_expert_families",
                result.stdout + result.stderr,
            )
            self.assertFalse(
                (paths["custody_root"] / "runner-receipt.json").exists()
            )


def _rewrite_completion(
    paths: dict[str, pathlib.Path],
    mutate,
) -> None:
    receipt = json.loads(paths["completion"].read_text(encoding="utf-8"))
    mutate(receipt)
    write_json(paths["completion"], receipt)
    completion_sha256 = sha256_bytes(paths["completion"].read_bytes())
    rewrite_certificate(
        paths,
        lambda certificate: certificate.__setitem__(
            "completion_receipt_sha256", completion_sha256
        ),
    )


class ProducerSchemaBindingTest(unittest.TestCase):
    """Bind the consumer's completion-receipt expectations to the REAL
    producer (scripts/verify_ember01_completion.py) so schema drift breaks CI
    instead of the launch (issue #1300)."""

    def test_leg_state_constant_matches_producer(self) -> None:
        # AST-read the producer source (importing it drags heavy deps): the
        # module-level RESOLVED_TRUE assignment is the emitted leg state.
        import ast

        producer_path = ROOT / "scripts" / "verify_ember01_completion.py"
        tree = ast.parse(producer_path.read_text(encoding="utf-8"))
        values = [
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "RESOLVED_TRUE"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(len(values), 1)
        module = load_module()
        self.assertEqual(module.COMPLETION_LEG_RESOLVED_TRUE, values[0])

    def test_fixture_keys_match_consumer_closed_set(self) -> None:
        module = load_module()
        self.assertEqual(
            set(valid_completion_receipt()), module.COMPLETION_RECEIPT_KEYS
        )

    def test_producer_payload_keys_match_consumer_closed_set(self) -> None:
        # AST-extract the producer's receipt payload dict literal (the one
        # containing the "schema" -> "ember-01-completion-receipt-v1" pair)
        # so PRODUCER-side key drift also breaks CI, not just fixture drift.
        import ast

        producer_path = ROOT / "scripts" / "verify_ember01_completion.py"
        tree = ast.parse(producer_path.read_text(encoding="utf-8"))
        payload_key_sets = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            if len(keys) != len(node.keys):
                continue
            values = dict(zip(keys, node.values))
            schema_value = values.get("schema")
            if (
                isinstance(schema_value, ast.Constant)
                and schema_value.value == "ember-01-completion-receipt-v1"
            ):
                payload_key_sets.append(set(keys))
        self.assertEqual(len(payload_key_sets), 1)
        module = load_module()
        self.assertEqual(payload_key_sets[0], module.COMPLETION_RECEIPT_KEYS)


def install_closure(repo: pathlib.Path) -> str:
    """Give a fixture repo a real closure module, manifest, and closure files."""

    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "scripts" / "training_closure.py", repo / "scripts" / "training_closure.py"
    )
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "tools" / "entrypoint.py").write_text("import json\n", encoding="utf-8")
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "training.json").write_text('{"steps": 1}\n', encoding="utf-8")
    manifest_path = repo / "manifests" / "training-dependency-closure.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "ember-training-dependency-closure-v1",
                "entrypoints": ["tools/entrypoint.py"],
                "dynamic_entrypoints": [],
                "code": ["scripts/training_closure.py"],
                "data": ["configs/training.json"],
                "dynamic_call_sites": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    module = load_module()
    return module.read_live_closure_sha256(repo)


class ClosureBoundCertificateTests(unittest.TestCase):
    """The certificate binds the training closure, not the whole repository tip."""

    def test_moved_tip_outside_the_closure_is_accepted(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            closure_sha256 = install_closure(paths["repo"])
            rewrite_certificate(
                paths, lambda cert: cert.update({"closure_sha256": closure_sha256})
            )
            # A docs-only merge landed: the tip moved, the closure did not.
            moved_tip = "c" * 40
            with mock.patch.object(
                module, "read_current_master", return_value=moved_tip
            ), mock.patch.object(
                module, "read_pin_is_ancestor", return_value=True
            ):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.closure_sha256, closure_sha256)
            self.assertEqual(launch.public_master_sha, moved_tip)

    def test_changed_closure_file_is_rejected_even_at_the_pinned_tip(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            closure_sha256 = install_closure(paths["repo"])
            rewrite_certificate(
                paths, lambda cert: cert.update({"closure_sha256": closure_sha256})
            )
            (paths["repo"] / "configs" / "training.json").write_text(
                '{"steps": 2}\n', encoding="utf-8"
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(
                    ValueError, "live training dependency closure"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_certificate_without_closure_sha256_still_binds_the_tip(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(
                module, "read_current_master", return_value="c" * 40
            ):
                with self.assertRaisesRegex(ValueError, "current public master"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_malformed_closure_sha256_is_rejected(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            install_closure(paths["repo"])
            rewrite_certificate(
                paths, lambda cert: cert.update({"closure_sha256": "NOT-A-HASH"})
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "closure_sha256"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_unknown_certificate_key_is_still_rejected(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            rewrite_certificate(
                paths, lambda cert: cert.update({"smuggled_key": "value"})
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "certificate schema keys"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_stale_closure_manifest_is_rejected_at_launch(self) -> None:
        """The boundary is re-audited live: matching bytes are not enough.

        Otherwise a manifest that went stale since the guard last ran in CI
        would let code outside the declared closure train under a green
        certificate -- worse than the blunt tip pin it replaced.
        """

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            closure_sha256 = install_closure(paths["repo"])
            rewrite_certificate(
                paths, lambda cert: cert.update({"closure_sha256": closure_sha256})
            )
            # An undeclared module enters the entrypoint's import graph, and the
            # certificate is re-minted over the new bytes so only the BOUNDARY
            # is wrong.
            (paths["repo"] / "tools" / "smuggled.py").write_text(
                "SECRET = 1\n", encoding="utf-8"
            )
            (paths["repo"] / "tools" / "entrypoint.py").write_text(
                "from smuggled import SECRET\n", encoding="utf-8"
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "boundary guard"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_verified_pin_off_the_live_history_is_rejected(self) -> None:
        """Closure equality alone must not accept a tree that never held the pin."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            closure_sha256 = install_closure(paths["repo"])
            rewrite_certificate(
                paths, lambda cert: cert.update({"closure_sha256": closure_sha256})
            )
            with mock.patch.object(
                module, "read_current_master", return_value="c" * 40
            ), mock.patch.object(
                module, "read_pin_is_ancestor", return_value=False
            ):
                with self.assertRaisesRegex(ValueError, "not an ancestor"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_read_pin_is_ancestor_answers_from_real_git_history(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "repo"
            repo.mkdir()

            def git(*arguments: str) -> str:
                return subprocess.run(
                    ["git", "-C", str(repo), *arguments],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "closure test")
            (repo / "first.txt").write_text("first\n", encoding="utf-8")
            git("add", "first.txt")
            git("commit", "-qm", "first")
            first = git("rev-parse", "HEAD")
            (repo / "second.txt").write_text("second\n", encoding="utf-8")
            git("add", "second.txt")
            git("commit", "-qm", "second")
            second = git("rev-parse", "HEAD")

            # The verified-at pin is behind live HEAD: a merge landed after
            # verification, which is exactly the case closure binding unblocks.
            self.assertTrue(module.read_pin_is_ancestor(repo, first))
            self.assertTrue(module.read_pin_is_ancestor(repo, second))
            self.assertFalse(module.read_pin_is_ancestor(repo, "d" * 40))

    def test_execution_receipt_records_the_closure_binding(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            closure_sha256 = install_closure(paths["repo"])
            rewrite_certificate(
                paths, lambda cert: cert.update({"closure_sha256": closure_sha256})
            )
            with mock.patch.object(
                module, "read_current_master", return_value=SHA
            ), mock.patch.object(
                module, "read_pin_is_ancestor", return_value=True
            ):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            module.execute_validated_launch(
                paths["repo"],
                launch,
                run_process=lambda *args, **kwargs: mock.Mock(returncode=0),
            )
            receipt = json.loads(
                module._execution_receipt_path(launch).read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["closure_sha256"], closure_sha256)


class ClosureCrossConsumerAgreementTest(unittest.TestCase):
    def test_closure_evidence_agrees_with_the_launch_consumer_at_this_tree(self) -> None:
        """Verify side and launch side must compute the identical closure hash."""
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        spec = importlib.util.spec_from_file_location(
            "verify_ember01_completion_under_test",
            ROOT / "scripts" / "verify_ember01_completion.py",
        )
        assert spec is not None and spec.loader is not None
        completion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(completion)

        launch = load_module()
        value, reason = completion.closure_evidence_at(ROOT)

        self.assertEqual(reason, "ok")
        self.assertEqual(value, launch.read_live_closure_sha256(ROOT))


class GuardFloorCertificateTests(unittest.TestCase):
    """Issue #1410: guard-floor keys accepted; unknown keys still refused;
    guard-floor certificates carry a relative completion_receipt_path."""

    GUARD_FLOOR = {
        "ticket": "issue-1410",
        "ts": "20260804T120000Z",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "goal_id": "EMBER-02",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    }

    def _mutate_guard_floor(self, paths: dict[str, pathlib.Path], extra=None) -> None:
        def mutate(certificate: dict) -> None:
            certificate.update(self.GUARD_FLOOR)
            certificate["completion_receipt_path"] = "ember-01-completion.json"
            if extra is not None:
                extra(certificate)

        rewrite_certificate(paths, mutate)

    def test_guard_floor_certificate_is_accepted(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            self._mutate_guard_floor(paths)
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.public_master_sha, SHA)

    def test_guard_floor_keys_are_optional_in_the_key_template(self) -> None:
        module = load_module()
        self.assertEqual(set(self.GUARD_FLOOR), module.GUARD_FLOOR_CERTIFICATE_KEYS)
        self.assertLessEqual(
            module.GUARD_FLOOR_CERTIFICATE_KEYS, module.OPTIONAL_CERTIFICATE_KEYS
        )

    def test_guard_floor_plus_unknown_key_is_still_rejected(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            self._mutate_guard_floor(
                paths, extra=lambda certificate: certificate.update({"surprise": "x"})
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(ValueError, "certificate schema keys"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_guard_floor_value_must_be_a_non_empty_string(self) -> None:
        module = load_module()
        for key, bad in (("ticket", ""), ("ts", 20260804), ("goal_id", None)):
            with tempfile.TemporaryDirectory() as directory:
                paths = write_valid_bundle(pathlib.Path(directory))
                self._mutate_guard_floor(
                    paths, extra=lambda certificate: certificate.update({key: bad})
                )
                with mock.patch.object(module, "read_current_master", return_value=SHA):
                    with self.assertRaisesRegex(
                        ValueError, f"certificate {key} must be a non-empty string"
                    ):
                        module.validate_certified_request(
                            paths["repo"],
                            paths["certificate"],
                            paths["ledger"],
                            paths["run_spec"],
                        )

    def test_guard_floor_certificate_refuses_absolute_completion_path(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            absolute = str(paths["completion"])

            def mutate(certificate: dict) -> None:
                certificate.update(self.GUARD_FLOOR)
                certificate["completion_receipt_path"] = absolute

            rewrite_certificate(paths, mutate)
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(
                    ValueError, "completion_receipt_path must be relative"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_guard_floor_certificate_refuses_parent_traversal(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            self._mutate_guard_floor(
                paths,
                extra=lambda certificate: certificate.update(
                    {"completion_receipt_path": "../custody/ember-01-completion.json"}
                ),
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(
                    ValueError, "must not traverse above"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_guard_floor_certificate_refuses_drive_root_relative_path(self) -> None:
        # On Windows "/M/ember/custody/x.json" is not is_absolute() and has no
        # ".." part, but resolves outside the certificate directory.
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            self._mutate_guard_floor(
                paths,
                extra=lambda certificate: certificate.update(
                    {"completion_receipt_path": "/M/ember/custody/x.json"}
                ),
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(
                    ValueError, "completion_receipt_path must not name a drive or root anchor"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_guard_floor_certificate_refuses_drive_relative_path(self) -> None:
        # "C:x.json" is drive-anchored: what it names depends on the drive the
        # certificate sits on, so it is not custody-portable.
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            self._mutate_guard_floor(
                paths,
                extra=lambda certificate: certificate.update(
                    {"completion_receipt_path": "C:x.json"}
                ),
            )
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                with self.assertRaisesRegex(
                    ValueError, "completion_receipt_path must not name a drive or root anchor"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_legacy_certificate_without_guard_floor_keeps_absolute_path(self) -> None:
        # Existing committed triples predate #1410 and stay digest-pinned; the
        # absolute-path refusal applies only to guard-floor certificates.
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(module, "read_current_master", return_value=SHA):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.public_master_sha, SHA)


ANCESTOR_SHA = "e" * 40


def valid_training_verify_receipt(
    repo: pathlib.Path, closure_sha256: str
) -> dict[str, object]:
    """Mirrors runtime/ember-lab/src/training_verify.rs::run's receipt."""

    return {
        "schema_version": "ember-lab-training-verify-receipt-v1",
        "ok": True,
        "root": str(repo),
        "started_at_ms": 1_754_300_000_000,
        "finished_at_ms": 1_754_300_000_112,
        "duration_ms": 112,
        "closure": {"declared_files": 4, "closure_sha256": closure_sha256},
        "input_identity": {
            "artifact_id": "owned-four-domain-production-rung-v1",
            "identity_manifest_path": "manifests/input-identity.json",
            "shard_path": "data/shard.json",
            "shard_sha256": EVIDENCE_SHA256,
            "shard_bytes": 1024,
            "admission_receipt_path": "data/shard.receipt.json",
            "admission_receipt_sha256": EVIDENCE_SHA256,
        },
        "model_tokenizer": {
            "tokenizer_sha256": EVIDENCE_SHA256,
            "config_sha256": EVIDENCE_SHA256,
        },
        "certificate": {
            "path": "spine-certified.json",
            "closure_sha256_matches": True,
            "pin_is_ancestor": True,
        },
        "checks": [
            {"name": "closure_members_present", "ok": True, "detail": "4 declared files present"},
            {"name": "input_identity_admission_chain", "ok": True, "detail": "artifact_id=owned"},
            {"name": "model_tokenizer_identity", "ok": True, "detail": "hashed"},
            {
                "name": "certificate_closure_and_pin",
                "ok": True,
                "detail": "closure_sha256_matches=true pin_is_ancestor=true",
            },
        ],
        "ember_lab_binary_sha256": EVIDENCE_SHA256,
        "ember_lab_source_sha256": EVIDENCE_SHA256,
    }


class CompletionHeadAncestorTests(unittest.TestCase):
    """Issue #1419: EMBER-01 completion is a historical fact validated at its own
    head (an ANCESTOR of the pin); pin freshness comes from the #1400/#1418
    training-scoped verify receipt, not from re-running the whole-repo census."""

    def _ancestor_bundle(
        self, directory: str, mutate_receipt=None, mutate_run_spec=None
    ) -> tuple[dict[str, pathlib.Path], str]:
        paths = write_valid_bundle(pathlib.Path(directory))
        closure_sha256 = install_closure(paths["repo"])
        _rewrite_completion(
            paths,
            lambda receipt: receipt["checkout"].__setitem__("head", ANCESTOR_SHA),
        )
        rewrite_certificate(
            paths, lambda cert: cert.update({"closure_sha256": closure_sha256})
        )

        receipt = valid_training_verify_receipt(paths["repo"], closure_sha256)
        if mutate_receipt is not None:
            mutate_receipt(receipt)
        receipt_path = paths["custody_root"] / "training-verify.json"
        write_json(receipt_path, receipt)

        run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
        run_spec["training_verify_receipt_path"] = str(receipt_path)
        if mutate_run_spec is not None:
            mutate_run_spec(run_spec)
        write_json(paths["run_spec"], run_spec)
        return paths, closure_sha256

    @contextlib.contextmanager
    def _patched(self, module, is_ancestor: bool = True):
        with mock.patch.object(
            module, "read_current_master", return_value=SHA
        ), mock.patch.object(
            module, "read_pin_is_ancestor", return_value=True
        ), mock.patch.object(
            module, "read_commit_is_ancestor", return_value=is_ancestor
        ):
            yield

    def test_ancestor_head_with_green_training_receipt_is_accepted(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, closure_sha256 = self._ancestor_bundle(directory)
            with self._patched(module):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.closure_sha256, closure_sha256)
            self.assertEqual(launch.public_master_sha, SHA)

    def test_equal_head_without_training_receipt_stays_accepted(self) -> None:
        """Back-compat: the pre-#1419 shape needs no new evidence and no git."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            with mock.patch.object(
                module, "read_current_master", return_value=SHA
            ), mock.patch.object(
                module,
                "read_commit_is_ancestor",
                side_effect=AssertionError(
                    "an equal head is an ancestor of itself; git must not be consulted"
                ),
            ):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.public_master_sha, SHA)

    def test_non_ancestor_completion_head_is_refused(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self._ancestor_bundle(directory)
            with self._patched(module, is_ancestor=False):
                with self.assertRaisesRegex(
                    ValueError, "head is not an ancestor of declared public master"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_ancestor_head_without_training_receipt_is_refused(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self._ancestor_bundle(
                directory,
                mutate_run_spec=lambda spec: spec.pop("training_verify_receipt_path"),
            )
            with self._patched(module):
                with self.assertRaisesRegex(
                    ValueError, "must supply training_verify_receipt_path"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_stale_or_red_training_receipt_is_refused(self) -> None:
        module = load_module()
        cases = {
            "red receipt": (
                lambda receipt: receipt.__setitem__("ok", False),
                "not green",
            ),
            "red check inside a green receipt": (
                lambda receipt: receipt["checks"][3].__setitem__("ok", False),
                "check is red: certificate_closure_and_pin",
            ),
            "stale closure": (
                lambda receipt: receipt["closure"].__setitem__(
                    "closure_sha256", "d" * 64
                ),
                "does not bind the certificate's training dependency closure",
            ),
            "receipt from another checkout": (
                lambda receipt: receipt.__setitem__("root", "B:/some-other-tree"),
                "produced against a different tree",
            ),
            "wrong schema": (
                lambda receipt: receipt.__setitem__(
                    "schema_version", "ember-01-completion-receipt-v1"
                ),
                "training verify receipt schema",
            ),
            "unknown receipt key": (
                lambda receipt: receipt.__setitem__("smuggled", True),
                "training verify receipt schema keys",
            ),
        }
        for label, (mutate, error) in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    paths, _ = self._ancestor_bundle(
                        directory, mutate_receipt=mutate
                    )
                    with self._patched(module):
                        with self.assertRaisesRegex(ValueError, error):
                            module.validate_certified_request(
                                paths["repo"],
                                paths["certificate"],
                                paths["ledger"],
                                paths["run_spec"],
                            )

    def test_missing_training_receipt_file_is_refused(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self._ancestor_bundle(directory)
            (paths["custody_root"] / "training-verify.json").unlink()
            with self._patched(module):
                with self.assertRaisesRegex(
                    ValueError, "training verify receipt is unreadable"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_training_receipt_without_closure_bound_certificate_is_refused(
        self,
    ) -> None:
        """A pre-#1332 certificate has no closure to bind the receipt to."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self._ancestor_bundle(directory)
            rewrite_certificate(paths, lambda cert: cert.pop("closure_sha256"))
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["training_verify_receipt_path"] = str(
                paths["custody_root"] / "training-verify.json"
            )
            write_json(paths["run_spec"], run_spec)
            with self._patched(module):
                with self.assertRaisesRegex(
                    ValueError, "requires a closure-bound certificate"
                ):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_relative_training_receipt_path_resolves_against_the_run_spec(
        self,
    ) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self._ancestor_bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "training_verify_receipt_path", "training-verify.json"
                ),
            )
            with self._patched(module):
                launch = module.validate_certified_request(
                    paths["repo"],
                    paths["certificate"],
                    paths["ledger"],
                    paths["run_spec"],
                )
            self.assertEqual(launch.public_master_sha, SHA)

    def test_unknown_run_spec_key_is_still_refused(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self._ancestor_bundle(
                directory,
                mutate_run_spec=lambda spec: spec.update({"smuggled_key": "x"}),
            )
            with self._patched(module):
                with self.assertRaisesRegex(ValueError, "run spec schema keys"):
                    module.validate_certified_request(
                        paths["repo"],
                        paths["certificate"],
                        paths["ledger"],
                        paths["run_spec"],
                    )

    def test_optional_run_spec_keys_are_a_closed_enumeration(self) -> None:
        """Every optional key is enumerated here, so a new one cannot slip in
        unvalidated: anything outside this set still hard-fails the schema."""

        module = load_module()
        self.assertEqual(
            module.OPTIONAL_RUN_SPEC_KEYS,
            {
                "training_verify_receipt_path",
                "resume_checkpoint",
                "resume_counter_receipt",
                "resume_realization_registry",
                "resume_optimizer_transition_registry",
                "resume_optimizer_transition_registry_sha256",
                "training_data_manifest",
                "training_capability",
                "training_checkpoint_interval",
                "training_telemetry_path",
                "training_model_chat_restore_not_before",
            },
        )

    def test_receipt_fixture_keys_match_the_rust_producer(self) -> None:
        """Bind the consumer's closed key set to runtime/ember-lab/src/
        training_verify.rs::run, so producer drift breaks CI, not the launch."""

        module = load_module()
        fixture_keys = set(
            valid_training_verify_receipt(pathlib.Path("."), "0" * 64)
        )
        self.assertEqual(fixture_keys, module.TRAINING_VERIFY_RECEIPT_KEYS)

        source = (
            ROOT / "runtime" / "ember-lab" / "src" / "training_verify.rs"
        ).read_text(encoding="utf-8")
        marker = f'"schema_version": "{module.TRAINING_VERIFY_RECEIPT_SCHEMA}"'
        self.assertIn(marker, source)
        body = source[source.index(marker) :]
        for key in module.TRAINING_VERIFY_RECEIPT_KEYS:
            self.assertIn(f'"{key}":', body, f"producer stopped emitting {key}")

    def test_read_commit_is_ancestor_answers_from_real_git_history(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "repo"
            repo.mkdir()

            def git(*arguments: str) -> str:
                return subprocess.run(
                    ["git", "-C", str(repo), *arguments],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "ancestor test")
            (repo / "first.txt").write_text("first\n", encoding="utf-8")
            git("add", "first.txt")
            git("commit", "-qm", "first")
            first = git("rev-parse", "HEAD")
            (repo / "second.txt").write_text("second\n", encoding="utf-8")
            git("add", "second.txt")
            git("commit", "-qm", "second")
            second = git("rev-parse", "HEAD")
            git("checkout", "-q", "-b", "sidebranch", first)
            (repo / "side.txt").write_text("side\n", encoding="utf-8")
            git("add", "side.txt")
            git("commit", "-qm", "side")
            side = git("rev-parse", "HEAD")

            self.assertTrue(module.read_commit_is_ancestor(repo, first, second))
            self.assertTrue(module.read_commit_is_ancestor(repo, first, first))
            self.assertFalse(module.read_commit_is_ancestor(repo, second, first))
            self.assertFalse(module.read_commit_is_ancestor(repo, side, second))
            # Fail CLOSED: an unresolvable commit yields no ancestry evidence.
            with self.assertRaisesRegex(ValueError, "unprovable"):
                module.read_commit_is_ancestor(repo, "d" * 40, second)


ARCHITECTURE_REVISION = "ember-sparse-3b-v2"
REGISTRY_SHA256 = "c" * 64


def install_model_config(
    repo: pathlib.Path, revision: str = ARCHITECTURE_REVISION
) -> None:
    write_json(
        repo / "configs" / "ember-restart-3b.json",
        {"architecture_revision": revision},
    )


def install_checkpoint(
    checkpoint: pathlib.Path,
    *,
    revision: str | None = ARCHITECTURE_REVISION,
    manifest: bool = True,
) -> pathlib.Path:
    checkpoint.mkdir(parents=True, exist_ok=True)
    if manifest:
        write_json(
            checkpoint / "checkpoint-manifest.json",
            {"architecture_revision": revision, "global_step": 100},
        )
    return checkpoint


def authorize_resume_roots(
    paths: dict[str, pathlib.Path], *roots: pathlib.Path
) -> None:
    """Give the bundle's certificate the #1426 resume allowlist.

    Kept OUT of valid_scope so the shared fixture stays the legacy shape: every
    non-resume test then proves a certificate without the key takes no new code
    path, and a test that wants the key opts into it explicitly.
    """

    rewrite_certificate(
        paths,
        lambda certificate: certificate["execution_scope"].__setitem__(
            "allowed_resume_roots", [str(root) for root in roots]
        ),
    )


def authorize_training_capabilities(
    paths: dict[str, pathlib.Path], *capabilities: str
) -> None:
    """Give the bundle's certificate the #1430 specialist-capability allowlist.

    Kept OUT of valid_scope for the same reason authorize_resume_roots is:
    every non-specialist test then proves a certificate without the key takes
    no new code path (test_plain_bundle_has_no_specialist_route), and a test
    that wants a specialist route opts in explicitly.
    """

    rewrite_certificate(
        paths,
        lambda certificate: certificate["execution_scope"].__setitem__(
            "allowed_training_capabilities", list(capabilities)
        ),
    )


def set_resume_paths(
    paths: dict[str, pathlib.Path],
    checkpoint: pathlib.Path,
    evidence: pathlib.Path,
) -> None:
    """Repoint an already-built bundle's resume triple.

    Safe after the certificate has been rewritten: the run spec's own digest is
    computed at validation time, and only certificate_sha256 binds it back.
    """

    run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
    run_spec["resume_checkpoint"] = str(checkpoint)
    run_spec["resume_counter_receipt"] = str(evidence)
    write_json(paths["run_spec"], run_spec)


def install_resume_material(directory: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A resumable checkpoint plus its realization evidence, under `directory`."""

    checkpoint = install_checkpoint(directory / "checkpoint-000100")
    evidence = directory / "counter-success.json"
    write_json(evidence, {"ok": True})
    return checkpoint, evidence


class _ResumeBundleMixin:
    """Bundle helpers shared by the #1425 plumbing and #1426 authorization
    suites; not a TestCase, so the cases are collected once each."""

    def _bundle(
        self,
        directory: str,
        *,
        mutate_run_spec=None,
        config_revision: str = ARCHITECTURE_REVISION,
        checkpoint_revision: str | None = ARCHITECTURE_REVISION,
        checkpoint_manifest: bool = True,
        resume_roots: list[pathlib.Path] | None = None,
        authorize_resume: bool = True,
    ) -> dict[str, pathlib.Path]:
        paths = write_valid_bundle(pathlib.Path(directory))
        install_model_config(paths["repo"], config_revision)
        checkpoint = install_checkpoint(
            paths["custody_root"] / "checkpoint-000100",
            revision=checkpoint_revision,
            manifest=checkpoint_manifest,
        )
        evidence = paths["custody_root"] / "counter-success.json"
        write_json(evidence, {"ok": True})
        paths["checkpoint"] = checkpoint
        paths["evidence"] = evidence

        run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
        run_spec["resume_checkpoint"] = str(checkpoint)
        run_spec["resume_counter_receipt"] = str(evidence)
        if mutate_run_spec is not None:
            mutate_run_spec(run_spec)
        write_json(paths["run_spec"], run_spec)
        if authorize_resume:
            authorize_resume_roots(
                paths,
                *(
                    [paths["custody_root"]]
                    if resume_roots is None
                    else resume_roots
                ),
            )
        return paths

    def _validate(self, module, paths: dict[str, pathlib.Path]):
        with mock.patch.object(module, "read_current_master", return_value=SHA):
            return module.validate_certified_request(
                paths["repo"],
                paths["certificate"],
                paths["ledger"],
                paths["run_spec"],
            )

    def _refused(self, paths: dict[str, pathlib.Path], pattern: str) -> None:
        module = load_module()
        with self.assertRaisesRegex(ValueError, pattern):
            self._validate(module, paths)


class ResumePlumbingTests(_ResumeBundleMixin, unittest.TestCase):
    """Issue #1425: the certified path built a FIXED argv with no resume flags,
    so a resumed rung could only be launched OFF the certified path. Resume is
    expressed as optional run-spec keys, validated fail-closed before argv."""

    def test_valid_resume_triple_is_accepted_and_reaches_the_runner_argv(
        self,
    ) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            launch = self._validate(module, paths)
            self.assertEqual(launch.resume_checkpoint, paths["checkpoint"])
            self.assertEqual(launch.resume_evidence_path, paths["evidence"])
            self.assertEqual(
                launch.resume_evidence_flag, "--resume-counter-receipt"
            )
            self.assertIsNone(
                launch.resume_optimizer_transition_registry_sha256
            )

            argv = module.build_runner_argv(paths["repo"], launch)
            # The flags ride AFTER --max-records, in the order the runner's
            # argparse declares them.
            self.assertEqual(
                argv[argv.index("--max-records") :],
                [
                    "--max-records",
                    "1",
                    "--resume-checkpoint",
                    str(paths["checkpoint"]),
                    "--resume-counter-receipt",
                    str(paths["evidence"]),
                ],
            )

    def test_each_evidence_key_maps_to_its_runner_flag(self) -> None:
        module = load_module()
        for key, flag in (
            ("resume_counter_receipt", "--resume-counter-receipt"),
            ("resume_realization_registry", "--resume-realization-registry"),
            (
                "resume_optimizer_transition_registry",
                "--resume-optimizer-transition-registry",
            ),
        ):
            with self.subTest(evidence=key), tempfile.TemporaryDirectory() as directory:
                paths = self._bundle(
                    directory,
                    mutate_run_spec=lambda spec, key=key: spec.update(
                        {key: spec.pop("resume_counter_receipt")}
                    ),
                )
                launch = self._validate(module, paths)
                argv = module.build_runner_argv(paths["repo"], launch)
                self.assertEqual(
                    argv[argv.index(flag) + 1], str(paths["evidence"])
                )

    def test_optimizer_transition_registry_sha256_rides_the_argv(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.update(
                    {
                        "resume_optimizer_transition_registry": spec.pop(
                            "resume_counter_receipt"
                        ),
                        "resume_optimizer_transition_registry_sha256": REGISTRY_SHA256,
                    }
                ),
            )
            launch = self._validate(module, paths)
            argv = module.build_runner_argv(paths["repo"], launch)
            self.assertEqual(
                argv[-4:],
                [
                    "--resume-optimizer-transition-registry",
                    str(paths["evidence"]),
                    "--resume-optimizer-transition-registry-sha256",
                    REGISTRY_SHA256,
                ],
            )

    def test_run_spec_without_resume_keys_builds_the_pre_1425_argv(self) -> None:
        """The clean-genesis shape must be byte-identical to what shipped
        before resume existed -- resume adds no new code path to it."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            launch = self._validate(module, paths)
            self.assertIsNone(launch.resume_checkpoint)
            self.assertEqual(
                module.build_runner_argv(paths["repo"], launch),
                [
                    sys.executable,
                    str(
                        paths["repo"]
                        / "tools"
                        / "ember-restart-3b"
                        / "disk_budget_runner.py"
                    ),
                    "--max-c-write-gib",
                    "0.0",
                    "--max-b-write-gib",
                    "16.0",
                    "--receipt",
                    str(paths["custody_root"] / "runner-receipt.json"),
                    "--write-root",
                    f"custody={paths['custody_root']}",
                    "--write-root",
                    f"artifacts={paths['artifact_root']}",
                    "--",
                    sys.executable,
                    str(
                        paths["repo"]
                        / "tools"
                        / "ember-restart-3b"
                        / "run_vertical_slice.py"
                    ),
                    "governed-vertical",
                    "--seed",
                    "83",
                    "--artifact-root",
                    str(paths["artifact_root"]),
                    "--write-budget-bytes",
                    str(16 * 1024**3),
                    "--max-records",
                    "1",
                ],
            )

    def test_checkpoint_without_evidence_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.pop("resume_counter_receipt"),
            )
            self._refused(paths, "exactly one resume evidence key")

    def test_two_evidence_keys_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.update(
                    {"resume_realization_registry": spec["resume_counter_receipt"]}
                ),
            )
            self._refused(paths, "exactly one resume evidence key")

    def test_evidence_without_checkpoint_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.pop("resume_checkpoint"),
            )
            self._refused(paths, "requires resume_checkpoint")

    def test_checkpoint_without_manifest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, checkpoint_manifest=False)
            self._refused(paths, "not a resumable checkpoint")

    def test_architecture_revision_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, checkpoint_revision="ember-sparse-3b-v1")
            self._refused(paths, "architecture_revision does not match")

    def test_checkpoint_manifest_without_revision_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, checkpoint_revision=None)
            self._refused(paths, "architecture_revision does not match")

    def test_lexically_quarantined_checkpoint_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            install_model_config(paths["repo"])
            checkpoint = install_checkpoint(
                paths["custody_root"] / ".checkpoint-quarantine" / "checkpoint-000100"
            )
            evidence = paths["custody_root"] / "counter-success.json"
            write_json(evidence, {"ok": True})
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["resume_checkpoint"] = str(checkpoint)
            run_spec["resume_counter_receipt"] = str(evidence)
            write_json(paths["run_spec"], run_spec)
            self._refused(paths, "quarantined checkpoint")

    def test_quarantined_checkpoint_behind_a_link_is_refused(self) -> None:
        """The lexical check alone is defeated by a link whose own name is
        clean; the resolved form is checked too."""

        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            install_model_config(paths["repo"])
            real = install_checkpoint(
                paths["custody_root"] / ".checkpoint-quarantine" / "checkpoint-000100"
            )
            link = paths["custody_root"] / "clean-looking-checkpoint"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                # Unprivileged Windows refuses symlinks but allows junctions,
                # which resolve() follows the same way -- and a junction is the
                # realistic shape here anyway.
                if sys.platform != "win32" or subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(real)],
                    capture_output=True,
                    check=False,
                ).returncode != 0:
                    self.skipTest("directory links unavailable in this environment")
            self.assertEqual(link.resolve(), real.resolve())
            evidence = paths["custody_root"] / "counter-success.json"
            write_json(evidence, {"ok": True})
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["resume_checkpoint"] = str(link)
            run_spec["resume_counter_receipt"] = str(evidence)
            write_json(paths["run_spec"], run_spec)
            self._refused(paths, "quarantined checkpoint")

    def test_quarantined_evidence_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "resume_counter_receipt",
                    str(
                        pathlib.Path(spec["resume_counter_receipt"]).parent
                        / ".checkpoint-quarantine"
                        / "counter-success.json"
                    ),
                ),
            )
            self._refused(paths, "quarantined checkpoint")

    def test_dangling_checkpoint_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "resume_checkpoint", spec["resume_checkpoint"] + "-absent"
                ),
            )
            self._refused(paths, "existing checkpoint directory")

    def test_checkpoint_pointing_at_a_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["resume_checkpoint"] = str(paths["evidence"])
            write_json(paths["run_spec"], run_spec)
            self._refused(paths, "existing checkpoint directory")

    def test_dangling_evidence_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "resume_counter_receipt",
                    spec["resume_counter_receipt"] + "-absent",
                ),
            )
            self._refused(paths, "resume_counter_receipt must name an existing file")

    def test_empty_resume_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "resume_checkpoint", ""
                ),
            )
            # An empty string is a DECLARED resume that names nothing, so it is
            # refused outright rather than read as an absent key.
            self._refused(paths, "resume_checkpoint must be a non-empty string")

    def test_registry_sha256_without_its_registry_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "resume_optimizer_transition_registry_sha256", REGISTRY_SHA256
                ),
            )
            self._refused(
                paths,
                "resume_optimizer_transition_registry_sha256 is only legal",
            )

    def test_malformed_registry_sha256_is_refused(self) -> None:
        for label, value in (
            ("too short", "c" * 63),
            ("uppercase", "C" * 64),
            ("non hex", "z" * 64),
        ):
            with self.subTest(sha=label), tempfile.TemporaryDirectory() as directory:
                paths = self._bundle(
                    directory,
                    mutate_run_spec=lambda spec, value=value: spec.update(
                        {
                            "resume_optimizer_transition_registry": spec.pop(
                                "resume_counter_receipt"
                            ),
                            "resume_optimizer_transition_registry_sha256": value,
                        }
                    ),
                )
                self._refused(paths, "must be a lowercase SHA-256")

    def test_relative_resume_paths_resolve_against_the_run_spec(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.update(
                    {
                        "resume_checkpoint": "checkpoint-000100",
                        "resume_counter_receipt": "counter-success.json",
                    }
                ),
            )
            launch = self._validate(module, paths)
            self.assertEqual(launch.resume_checkpoint, paths["checkpoint"])
            self.assertEqual(launch.resume_evidence_path, paths["evidence"])

    def test_resume_flags_match_the_runner_argparse(self) -> None:
        """Bind the consumer's flag spelling to run_vertical_slice's governed
        -vertical parser, so a renamed runner flag breaks CI, not a launch."""

        module = load_module()
        runner = (
            ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
        ).read_text(encoding="utf-8")
        for flag in (
            *module.RESUME_EVIDENCE_RUN_SPEC_FLAGS.values(),
            "--resume-checkpoint",
            "--resume-optimizer-transition-registry-sha256",
        ):
            self.assertIn(f'"{flag}"', runner)

    def test_config_revision_constant_matches_the_production_config(self) -> None:
        config = json.loads(
            (ROOT / "configs" / "ember-restart-3b.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["architecture_revision"], ARCHITECTURE_REVISION)


class ResumeRootAuthorizationTests(_ResumeBundleMixin, unittest.TestCase):
    """Issue #1426: the resume paths sat at run-spec TOP LEVEL, outside
    requested_scope, so they received none of the certificate authorization
    every other launch-shaping parameter gets -- a certificate scoped to custody
    X admitted a resume from any published bundle anywhere on the machine, and
    was checked only for coherence. The cure is a certificate-side ALLOWLIST,
    because containment ("inside this run's custody_root") would refuse the
    primary use case."""

    def test_resume_from_a_prior_runs_custody_is_accepted(self) -> None:
        """The case that forbids a containment rule: an R1->R2 rung resumes from
        a PRIOR run's custody, entirely outside this run's custody_root."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            prior = pathlib.Path(directory) / "prior-run-custody"
            checkpoint, evidence = install_resume_material(prior)
            paths = self._bundle(directory, resume_roots=[prior])
            set_resume_paths(paths, checkpoint, evidence)

            launch = self._validate(module, paths)
            self.assertEqual(launch.resume_checkpoint, checkpoint)
            self.assertEqual(launch.resume_evidence_path, evidence)
            self.assertFalse(
                checkpoint.resolve().is_relative_to(
                    paths["custody_root"].resolve()
                )
            )

    def test_resume_outside_every_allowed_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unlisted = pathlib.Path(directory) / "unlisted-bundle"
            checkpoint, evidence = install_resume_material(unlisted)
            paths = self._bundle(directory)
            set_resume_paths(paths, checkpoint, evidence)
            self._refused(
                paths, "run scope exceeds certificate: resume_checkpoint"
            )

    def test_parent_traversal_out_of_an_allowed_root_is_refused(self) -> None:
        """The executed probe that found the defect: a path whose LEXICAL form
        sits under the allowed root and whose RESOLVED form escapes it. The
        check therefore has to run on the resolved path, which is also the one
        the runner would open."""

        with tempfile.TemporaryDirectory() as directory:
            outside = pathlib.Path(directory) / "outside-custody"
            checkpoint, evidence = install_resume_material(outside)
            paths = self._bundle(directory)
            custody_root = paths["custody_root"]
            traversed_checkpoint = (
                custody_root / ".." / "outside-custody" / checkpoint.name
            )
            traversed_evidence = (
                custody_root / ".." / "outside-custody" / evidence.name
            )
            # Lexically inside the allowed root, resolves outside it.
            self.assertTrue(
                str(traversed_checkpoint).startswith(str(custody_root))
            )
            self.assertEqual(traversed_checkpoint.resolve(), checkpoint.resolve())

            set_resume_paths(paths, traversed_checkpoint, traversed_evidence)
            self._refused(
                paths, "run scope exceeds certificate: resume_checkpoint"
            )

    def test_evidence_outside_the_allowed_roots_is_refused(self) -> None:
        """Authorization covers the evidence path on the same basis as the
        checkpoint. An authorized checkpoint admitted on realization evidence
        fetched from anywhere is still an unauthorized resume."""

        with tempfile.TemporaryDirectory() as directory:
            unlisted = pathlib.Path(directory) / "unlisted-bundle"
            unlisted.mkdir(parents=True)
            evidence = unlisted / "counter-success.json"
            write_json(evidence, {"ok": True})
            paths = self._bundle(directory)
            set_resume_paths(paths, paths["checkpoint"], evidence)
            self._refused(
                paths, "run scope exceeds certificate: resume_counter_receipt"
            )

    def test_unauthorized_path_is_refused_before_it_is_opened(self) -> None:
        """Authorization precedes every coherence check, so an unauthorized
        path is refused without this process reading a byte of it -- the
        refusal names authorization, not the missing directory."""

        with tempfile.TemporaryDirectory() as directory:
            unlisted = pathlib.Path(directory) / "unlisted-bundle"
            paths = self._bundle(directory)
            set_resume_paths(
                paths,
                unlisted / "checkpoint-000100",
                unlisted / "counter-success.json",
            )
            self._refused(
                paths, "run scope exceeds certificate: resume_checkpoint"
            )

    def test_quarantine_outranks_authorization(self) -> None:
        """Quarantine is a property of the path itself, so it is settled before
        the certificate is consulted: a quarantined checkpoint stays
        unselectable even inside an authorized root."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            quarantined = install_checkpoint(
                paths["custody_root"]
                / ".checkpoint-quarantine"
                / "checkpoint-000100"
            )
            set_resume_paths(paths, quarantined, paths["evidence"])
            self._refused(paths, "quarantined checkpoint")

    def test_certificate_without_the_key_refuses_a_requested_resume(
        self,
    ) -> None:
        """Fail-closed on the population that carries the defect. A pre-#1426
        certificate authorizes no resume root, so it cannot express a certified
        resume -- and the refusal says which action fixes it."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, authorize_resume=False)
            certificate = json.loads(
                paths["certificate"].read_text(encoding="utf-8")
            )
            self.assertNotIn(
                "allowed_resume_roots", certificate["execution_scope"]
            )
            self._refused(paths, "declares no allowed_resume_roots")

    def test_certificate_without_the_key_still_launches_clean_genesis(
        self,
    ) -> None:
        """The other half of the decision: a certificate without the key is
        untouched for every launch that requests no resume, which is every
        launch that worked before #1425."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            certificate = json.loads(
                paths["certificate"].read_text(encoding="utf-8")
            )
            self.assertNotIn(
                "allowed_resume_roots", certificate["execution_scope"]
            )
            launch = self._validate(module, paths)
            self.assertIsNone(launch.resume_checkpoint)

    def test_empty_allowed_resume_roots_authorizes_nothing(self) -> None:
        """An explicitly empty allowlist is legal and authorizes nothing, the
        same way an empty allowed_artifact_roots does."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, resume_roots=[])
            self._refused(
                paths, "run scope exceeds certificate: resume_checkpoint"
            )

    def test_malformed_allowed_resume_roots_fails_closed(self) -> None:
        for declared in ("not-a-list", [""], [None], [str(pathlib.Path.cwd()), 7]):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as directory:
                paths = self._bundle(directory)
                rewrite_certificate(
                    paths,
                    lambda certificate, declared=declared: certificate[
                        "execution_scope"
                    ].__setitem__("allowed_resume_roots", declared),
                )
                self._refused(
                    paths,
                    "allowed_resume_roots must be a list of non-empty strings",
                )

    def test_unknown_execution_scope_key_is_still_refused(self) -> None:
        """The optional-key mechanism admits exactly the enumerated key and
        does not open the scope template (the #1410 property, one level down)."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            rewrite_certificate(
                paths,
                lambda certificate: certificate["execution_scope"].__setitem__(
                    "smuggled_key", "x"
                ),
            )
            self._refused(paths, "certificate execution scope schema keys")

    def test_optional_execution_scope_keys_are_a_closed_enumeration(
        self,
    ) -> None:
        module = load_module()
        self.assertEqual(
            module.OPTIONAL_AUTHORIZED_SCOPE_KEYS,
            {"allowed_resume_roots", "allowed_training_capabilities"},
        )
        self.assertFalse(
            module.OPTIONAL_AUTHORIZED_SCOPE_KEYS & module.AUTHORIZED_SCOPE_KEYS
        )


class SpecialistRoutingTests(_ResumeBundleMixin, unittest.TestCase):
    """Issue #1430: build_runner_argv could only ever emit "governed-vertical",
    so an admitted ember-owned-training-data-v1 manifest was reachable only by
    calling the runner directly -- training with no certificate. Specialist
    routing is expressed as optional run-spec keys, validated fail-closed
    before argv, mirroring how ResumePlumbingTests covers #1425. Reuses
    _ResumeBundleMixin (#1426) for the resume triple + allowlist authorization
    every specialist launch also requires -- a specialist fixture that skipped
    it would refuse on the allowlist instead of exercising the routing logic
    under test."""

    def _bundle(
        self,
        directory: str,
        *,
        mutate_run_spec=None,
        capability: str = "image",
        manifest_capability: str | None = None,
        manifest_schema: str = "ember-owned-training-data-v1",
        config_revision: str = ARCHITECTURE_REVISION,
        checkpoint_revision: str | None = ARCHITECTURE_REVISION,
        authorize_capability: bool = True,
        authorized_capabilities: list[str] | None = None,
    ) -> dict[str, pathlib.Path]:
        # The base mixin builds the resume triple AND authorizes it (default
        # authorize_resume=True roots the allowlist at custody_root, which is
        # exactly where it installs the checkpoint) -- specialist layers a
        # tokenizer, an admitted manifest, and its own run-spec keys on top,
        # applying mutate_run_spec AFTER those keys exist so a test can target
        # either the resume keys or the specialist keys.
        paths = super()._bundle(
            directory,
            config_revision=config_revision,
            checkpoint_revision=checkpoint_revision,
        )

        tokenizer_path = paths["repo"] / "tokenizer" / "tokenizer.json"
        write_json(tokenizer_path, {})
        paths["tokenizer"] = tokenizer_path

        # In-tree, mirroring build_specialist_bundle.py's OWN emission path
        # (output_root/manifests/<capability>.json, with output_root required
        # below repo_root) -- the only location the runner and the bundle
        # producer will ever accept. Issue #1430 review Defect 1/2: a
        # custody_root fixture location could never be a real admitted
        # manifest, so this fixture could not catch a launcher that resolved
        # relative manifests outside the tree (custody_root is by
        # construction outside repo_root -- see write_valid_bundle).
        manifest_path = paths["repo"] / "manifests" / f"{capability}.json"
        write_json(
            manifest_path,
            {
                "schema_version": manifest_schema,
                "capability": (
                    capability if manifest_capability is None else manifest_capability
                ),
                "data_class": "SEMANTIC_PRETRAINING",
            },
        )
        paths["manifest"] = manifest_path
        paths["telemetry"] = paths["custody_root"] / "telemetry.jsonl"

        run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
        run_spec["training_data_manifest"] = str(manifest_path)
        run_spec["training_capability"] = capability
        run_spec["training_checkpoint_interval"] = 8_192
        run_spec["training_telemetry_path"] = str(paths["telemetry"])
        run_spec["training_model_chat_restore_not_before"] = "2026-07-18T11:00:00-07:00"
        if mutate_run_spec is not None:
            mutate_run_spec(run_spec)
        write_json(paths["run_spec"], run_spec)

        # Issue #1430 review Defect 3: the certificate, not the run spec,
        # decides which capabilities may route to the specialist runner.
        # Default-authorize the capability this bundle declares (mirrors
        # authorize_resume=True's default in the base mixin) so every
        # existing routing/coherence test keeps exercising ITS OWN check
        # rather than tripping the new authorization gate; tests targeting
        # authorization itself opt out or override explicitly.
        if authorize_capability:
            authorize_training_capabilities(
                paths,
                *(
                    [capability]
                    if authorized_capabilities is None
                    else authorized_capabilities
                ),
            )
        return paths

    def test_valid_specialist_route_is_accepted_and_reaches_the_runner_argv(
        self,
    ) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            launch = self._validate(module, paths)
            parent_manifest = paths["checkpoint"] / "checkpoint-manifest.json"
            self.assertEqual(launch.specialist_capability, "image")
            self.assertEqual(launch.specialist_data_manifest, paths["manifest"])
            self.assertEqual(launch.specialist_tokenizer_path, paths["tokenizer"])
            self.assertEqual(launch.specialist_parent_manifest, parent_manifest)
            self.assertEqual(launch.specialist_root_manifest, parent_manifest)
            self.assertEqual(launch.specialist_checkpoint_interval, 8_192)
            self.assertEqual(launch.specialist_write_budget_gib, 16)
            self.assertEqual(launch.specialist_telemetry_path, paths["telemetry"])
            # Derived from run_spec["run_id"] (valid_run_spec's fixed value),
            # not a separately declared key -- see the reasoning note above
            # _validate_specialist_request.
            self.assertEqual(
                launch.specialist_telemetry_run_id, "owned-3b-canary-test"
            )
            self.assertEqual(
                launch.specialist_model_chat_restore_not_before,
                "2026-07-18T11:00:00-07:00",
            )

            self.assertEqual(
                module.build_runner_argv(paths["repo"], launch),
                [
                    sys.executable,
                    str(
                        paths["repo"]
                        / "tools"
                        / "ember-restart-3b"
                        / "disk_budget_runner.py"
                    ),
                    "--max-c-write-gib",
                    "0.0",
                    "--max-b-write-gib",
                    "16.0",
                    "--receipt",
                    str(paths["custody_root"] / "runner-receipt.json"),
                    "--write-root",
                    f"custody={paths['custody_root']}",
                    "--write-root",
                    f"artifacts={paths['artifact_root']}",
                    "--",
                    sys.executable,
                    str(
                        paths["repo"]
                        / "tools"
                        / "ember-restart-3b"
                        / "run_vertical_slice.py"
                    ),
                    "specialist",
                    "--seed",
                    "83",
                    "--artifact-root",
                    str(paths["artifact_root"]),
                    "--data-manifest",
                    str(paths["manifest"]),
                    "--tokenizer",
                    str(paths["tokenizer"]),
                    "--capability",
                    "image",
                    "--resume-checkpoint",
                    str(paths["checkpoint"]),
                    "--resume-counter-receipt",
                    str(paths["evidence"]),
                    "--parent-manifest",
                    str(parent_manifest),
                    "--root-manifest",
                    str(parent_manifest),
                    "--max-records",
                    "1",
                    "--checkpoint-interval",
                    "8192",
                    "--write-budget-gib",
                    "16",
                    "--telemetry-path",
                    str(paths["telemetry"]),
                    "--telemetry-run-id",
                    "owned-3b-canary-test",
                    "--model-chat-restore-not-before",
                    "2026-07-18T11:00:00-07:00",
                ],
            )

    def test_plain_bundle_has_no_specialist_route(self) -> None:
        """A run spec with neither training_data_manifest nor
        training_capability is the pre-#1430 shape -- ResumePlumbingTests'
        test_run_spec_without_resume_keys_builds_the_pre_1425_argv already
        proves this bundle's argv stays byte-identical; this pins the launch
        field driving that decision."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            launch = self._validate(module, paths)
            self.assertIsNone(launch.specialist_capability)

    def test_exactly_one_specialist_key_is_refused(self) -> None:
        for missing in ("training_data_manifest", "training_capability"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                paths = self._bundle(
                    directory,
                    mutate_run_spec=lambda spec, missing=missing: spec.pop(missing),
                )
                self._refused(paths, f"requires {missing}, which is absent")

    def test_specialist_companion_key_missing_is_refused(self) -> None:
        for missing in (
            "training_checkpoint_interval",
            "training_telemetry_path",
            "training_model_chat_restore_not_before",
        ):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                paths = self._bundle(
                    directory,
                    mutate_run_spec=lambda spec, missing=missing: spec.pop(missing),
                )
                self._refused(paths, f"requires {missing}, which is absent")

    def test_specialist_companion_without_pair_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: (
                    spec.pop("training_data_manifest"),
                    spec.pop("training_capability"),
                ),
            )
            self._refused(
                paths, "requires training_data_manifest and training_capability"
            )

    def test_invalid_capability_value_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "training_capability", "text"
                ),
            )
            self._refused(paths, "training_capability must be one of")

    def test_certificate_without_allowed_training_capabilities_is_refused(
        self,
    ) -> None:
        """Issue #1430 review Defect 3: allowed_modes == ["governed-vertical"]
        alone never stopped a specialist route (build_runner_argv reads only
        run-spec content), so a certificate carrying no
        allowed_training_capabilities at all is the pre-#1430 population --
        fail-closed on it, same reasoning #1426 applied to resume roots. A
        plain (non-specialist) bundle is unaffected: proven separately by
        test_plain_bundle_has_no_specialist_route, whose certificate also
        carries no allowed_training_capabilities."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, authorize_capability=False)
            certificate = json.loads(
                paths["certificate"].read_text(encoding="utf-8")
            )
            self.assertNotIn(
                "allowed_training_capabilities", certificate["execution_scope"]
            )
            self._refused(paths, "declares no allowed_training_capabilities")

    def test_empty_allowed_training_capabilities_authorizes_nothing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, authorized_capabilities=[])
            self._refused(
                paths, "run scope exceeds certificate: training_capability"
            )

    def test_capability_not_in_allowed_training_capabilities_is_refused(
        self,
    ) -> None:
        """A certificate that authorizes a DIFFERENT capability than the one
        the run spec requests -- not absent, not empty, just disagreeing."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory, capability="image", authorized_capabilities=["audio"]
            )
            self._refused(
                paths, "run scope exceeds certificate: training_capability"
            )

    def test_malformed_allowed_training_capabilities_fails_closed(self) -> None:
        for declared in ("not-a-list", [""], [None], ["image", 7]):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as directory:
                paths = self._bundle(directory)
                rewrite_certificate(
                    paths,
                    lambda certificate, declared=declared: certificate[
                        "execution_scope"
                    ].__setitem__("allowed_training_capabilities", declared),
                )
                self._refused(
                    paths,
                    "allowed_training_capabilities must be a list of "
                    "non-empty strings",
                )

    def test_manifest_schema_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory, manifest_schema="some-other-schema-v1")
            self._refused(
                paths, "not an ember-owned-training-data-v1 manifest"
            )

    def test_manifest_capability_mismatch_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory, capability="image", manifest_capability="audio"
            )
            self._refused(
                paths, "does not match the manifest's own declared capability"
            )

    def test_out_of_tree_manifest_is_refused(self) -> None:
        """Issue #1430 review Defect 1 (HIGH): the runner
        (run_vertical_slice.py::load_verified_specialist_records) and the
        bundle producer (build_specialist_bundle.py::emit_bundle) both refuse
        any manifest that does not resolve below repo_root. An
        operator-declared absolute path elsewhere must be refused before this
        process reads it -- not accepted into a perfect-looking argv the
        runner can never actually start."""

        with tempfile.TemporaryDirectory() as directory:
            # A sibling of repo/, not below it -- and also outside
            # custody_root, so this is unambiguously out-of-tree either way.
            outside_manifest = pathlib.Path(directory) / "outside-manifest.json"
            write_json(
                outside_manifest,
                {
                    "schema_version": "ember-owned-training-data-v1",
                    "capability": "image",
                    "data_class": "SEMANTIC_PRETRAINING",
                },
            )
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "training_data_manifest", str(outside_manifest)
                ),
            )
            self._refused(
                paths, "training_data_manifest must resolve below repo_root"
            )

    def test_relative_manifest_resolves_against_repo_root(self) -> None:
        """Issue #1430 review Defect 1: a RELATIVE training_data_manifest must
        resolve against repo_root, not run_spec_path.parent (the custody
        root) -- the custody root is outside the repo by construction (see
        write_valid_bundle), so resolving against it would build unusable
        argv for every relative-path launch, the exact defect found."""

        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "training_data_manifest", "manifests/image.json"
                ),
            )
            launch = self._validate(module, paths)
            self.assertEqual(launch.specialist_data_manifest, paths["manifest"])

    def test_specialist_without_resume_checkpoint_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: (
                    spec.pop("resume_checkpoint"),
                    spec.pop("resume_counter_receipt"),
                ),
            )
            self._refused(paths, "requires an authorized resume checkpoint")

    def test_write_budget_not_exact_gib_multiple_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["requested_scope"]["write_budget_bytes"] = 16 * 1024**3 - 1
            write_json(paths["run_spec"], run_spec)
            self._refused(paths, "exact GiB multiple")

    def test_write_budget_below_one_gib_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            run_spec = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            run_spec["requested_scope"]["write_budget_bytes"] = 0
            write_json(paths["run_spec"], run_spec)
            self._refused(paths, "at least 1 GiB")

    def test_run_id_over_128_characters_is_refused(self) -> None:
        """Issue #1430 review Defect 5 (LOW): run_id doubles as
        --telemetry-run-id, which run_vertical_slice.py bounds to 128
        characters ("training telemetry run id is invalid"); unbounded here
        would build argv the runner refuses at parse time."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "run_id", "r" * 129
                ),
            )
            self._refused(paths, "run_id must be at most 128 characters")

    def test_malformed_model_chat_restore_not_before_is_refused(self) -> None:
        """Issue #1430 review Defect 4 (LOW): the value is a cooldown floor
        telemetry orders against, so a malformed timestamp must be refused
        here rather than reaching a telemetry consumer as unparseable data."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "training_model_chat_restore_not_before", "not-a-timestamp"
                ),
            )
            self._refused(
                paths,
                "training_model_chat_restore_not_before must be an ISO 8601 "
                "timestamp",
            )

    def test_telemetry_path_outside_custody_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(
                directory,
                mutate_run_spec=lambda spec: spec.__setitem__(
                    "training_telemetry_path",
                    str(pathlib.Path(directory) / "outside-telemetry.jsonl"),
                ),
            )
            self._refused(
                paths, "run scope exceeds certificate: training_telemetry_path"
            )

    def test_missing_canonical_tokenizer_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bundle(directory)
            paths["tokenizer"].unlink()
            self._refused(paths, "canonical")

    def test_specialist_flags_match_the_runner_argparse(self) -> None:
        """Bind the consumer's flag spelling, required-ness, AND the
        --capability enum to run_vertical_slice's specialist parser,
        ast-parsed the way ProducerSchemaBindingTest binds completion-receipt
        keys to their real producer. Issue #1430 review test-quality note: a
        substring grep would still pass if a flag moved to another
        subparser, if required-ness changed, or if a new required flag
        appeared -- ast scoping by the (file-unique)
        `specialist`/`specialist_resume` argparse variable names closes all
        three, including the "shared with another subcommand" gap a
        whole-file substring check cannot close (--seed/--artifact-root/
        --resume-checkpoint/etc. also appear on vertical/governed-vertical;
        scoping by the OWNER object, not just the flag string, is what binds
        the check to THIS subparser's own requirements).

        Deliberately NOT asserted: each flag's argparse `type=`. Every argv
        element this launcher emits is already a plain string (build_runner_
        argv wraps every value in str(...) or takes an already-string field),
        so a `type=` change cannot alter what this launcher emits -- it would
        surface immediately as a runner-side parse failure on first use, not
        as a silent contract drift the way a required-ness or enum change
        would."""

        import ast

        runner_path = ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
        tree = ast.parse(runner_path.read_text(encoding="utf-8"))

        def call_owner_attr(node: ast.AST) -> tuple[str, str] | None:
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                return node.func.value.id, node.func.attr
            return None

        def is_required_kw(call: ast.Call) -> bool:
            return any(
                keyword.arg == "required"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            )

        # Pass 1: which group variables are a REQUIRED mutually-exclusive
        # group owned directly by `specialist` (e.g. specialist_resume).
        # Keyed off the literal owner name, not source order, so this does
        # not depend on where in main() the specialist block sits.
        required_groups: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            owner = call_owner_attr(node.value)
            if (
                owner == ("specialist", "add_mutually_exclusive_group")
                and is_required_kw(node.value)
                and isinstance(node.targets[0], ast.Name)
            ):
                required_groups.add(node.targets[0].id)
        self.assertTrue(
            required_groups,
            "no required mutually-exclusive group found on the specialist "
            "subparser -- the ast scoping below found nothing to bind",
        )

        # Pass 2: every --flag added directly to `specialist` with
        # required=True, plus every --flag added to one of its required
        # groups (argparse forbids required= on a group member -- membership
        # alone makes it required, as exactly one of the group). Also
        # extracts --capability's choices= tuple while we're already
        # visiting its add_argument call.
        required_flags: set[str] = set()
        capability_choices: set[str] | None = None
        for node in ast.walk(tree):
            owner = call_owner_attr(node)
            if owner is None or owner[1] != "add_argument":
                continue
            obj_name = owner[0]
            if obj_name != "specialist" and obj_name not in required_groups:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            flag = node.args[0].value
            if not isinstance(flag, str) or not flag.startswith("--"):
                continue
            if obj_name == "specialist":
                if is_required_kw(node):
                    required_flags.add(flag)
                if flag == "--capability":
                    choices_node = next(
                        (kw.value for kw in node.keywords if kw.arg == "choices"),
                        None,
                    )
                    if isinstance(choices_node, (ast.Tuple, ast.List)) and all(
                        isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                        for element in choices_node.elts
                    ):
                        capability_choices = {
                            element.value for element in choices_node.elts
                        }
            else:
                required_flags.add(flag)

        module = load_module()
        self.assertIsNotNone(
            capability_choices,
            "--capability's choices= could not be ast-extracted from the "
            "specialist subparser",
        )
        self.assertEqual(capability_choices, module.TRAINING_CAPABILITIES)
        # Every specialist launch emits exactly one of the three resume-
        # evidence flags (resume is mandatory -- _validate_specialist_request
        # refuses when absent, and exactly one evidence key is required by
        # _validate_resume_request), so the UNION across all three choices is
        # everything a specialist launch's argv can ever be required to
        # carry -- which must equal the runner's required set exactly.
        expected = {
            "--seed",
            "--artifact-root",
            "--data-manifest",
            "--tokenizer",
            "--capability",
            "--resume-checkpoint",
            "--parent-manifest",
            "--root-manifest",
            "--max-records",
            "--checkpoint-interval",
            "--write-budget-gib",
            "--telemetry-path",
            "--telemetry-run-id",
            "--model-chat-restore-not-before",
        } | set(module.RESUME_EVIDENCE_RUN_SPEC_FLAGS.values())
        self.assertEqual(required_flags, expected)


if __name__ == "__main__":
    unittest.main()
