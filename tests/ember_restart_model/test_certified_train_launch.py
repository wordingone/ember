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

    def test_training_verify_receipt_path_is_the_only_optional_run_spec_key(
        self,
    ) -> None:
        module = load_module()
        self.assertEqual(
            module.OPTIONAL_RUN_SPEC_KEYS, {"training_verify_receipt_path"}
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


if __name__ == "__main__":
    unittest.main()
