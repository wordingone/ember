# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "ember-restart-3b" / "certified_train_launch.py"
SHA = "a" * 40
EVIDENCE_SHA256 = "b" * 64
CERTIFICATE_EVIDENCE_FIELDS = (
    "config_sha256",
    "input_identity_sha256",
    "input_shard_sha256",
    "input_admission_receipt_sha256",
    "certified_consumer_sha256",
    "disk_budget_runner_sha256",
    "governed_runner_sha256",
    "input_identity_validator_sha256",
)


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
        "completed_goal_id": "EMBER-01",
        # Production verify_ember01_completion.py runs after the authority
        # selector has advanced to EMBER-02.  Its receipt records the active
        # goal/workstream while the schema names the completed EMBER-01 spine.
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "certificate_legs": {str(index): "RESOLVED_TRUE" for index in range(1, 10)},
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
            "goal_id": "EMBER-02",
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

    evidence_paths: dict[str, pathlib.Path] = {}
    evidence_entries: dict[str, dict[str, str]] = {}
    evidence_hashes: dict[str, str] = {}
    for field in CERTIFICATE_EVIDENCE_FIELDS:
        if field == "config_sha256":
            path = repo / "configs" / "ember-restart-3b.json"
            scope = "repo"
            relative = "configs/ember-restart-3b.json"
        elif field == "input_identity_sha256":
            path = repo / "data" / "ember-restart-3b" / "input-identity.json"
            scope = "repo"
            relative = "data/ember-restart-3b/input-identity.json"
        elif field == "input_shard_sha256":
            relative = (
                "data/ember-restart-3b/"
                "owned-four-domain-production-rung-v1.json"
            )
            path = repo / pathlib.PurePosixPath(relative)
            scope = "repo"
        elif field == "input_admission_receipt_sha256":
            relative = (
                "data/ember-restart-3b/"
                "owned-four-domain-production-rung-v1.receipt.json"
            )
            path = repo / pathlib.PurePosixPath(relative)
            scope = "repo"
        elif field == "certified_consumer_sha256":
            relative = "tools/ember-restart-3b/certified_train_launch.py"
            path = repo / pathlib.PurePosixPath(relative)
            scope = "repo"
        elif field == "disk_budget_runner_sha256":
            relative = "tools/ember-restart-3b/disk_budget_runner.py"
            path = repo / pathlib.PurePosixPath(relative)
            scope = "repo"
        elif field == "governed_runner_sha256":
            relative = "tools/ember-restart-3b/run_vertical_slice.py"
            path = repo / pathlib.PurePosixPath(relative)
            scope = "repo"
        elif field == "input_identity_validator_sha256":
            relative = "tools/ember-restart-3b/input_identity.py"
            path = repo / pathlib.PurePosixPath(relative)
            scope = "repo"
        else:
            relative = f"evidence/{field}.json"
            path = custody_root / relative
            scope = "certificate"
        write_json(path, {"field": field, "result": "BOUND"})
        evidence_paths[field] = path
        evidence_entries[field] = {"scope": scope, "path": relative}
        evidence_hashes[field] = sha256_bytes(path.read_bytes())

    evidence_bundle_path = custody_root / "certificate-evidence-bundle.json"
    write_json(
        evidence_bundle_path,
        {
            "schema_version": "ember-spine-certificate-evidence-bundle-v1",
            "evidence": evidence_entries,
        },
    )

    certificate = {
        "schema_version": "ember-spine-certified-declaration-v1",
        "event_kind": "SPINE_CERTIFIED",
        "declared_by_role": "EMBER_CERTIFICATE_AUTHORITY",
        "declared_at_utc": "2026-07-23T08:00:00+00:00",
        "superseded_by": None,
        "completion_receipt_path": "ember-01-completion.json",
        "completion_receipt_sha256": completion_sha256,
        "evidence_bundle_path": "certificate-evidence-bundle.json",
        "evidence_bundle_sha256": sha256_bytes(evidence_bundle_path.read_bytes()),
        "public_master_sha": SHA,
        **evidence_hashes,
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
        "evidence_bundle": evidence_bundle_path,
        "evidence_paths": evidence_paths,
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
            "arbitrary valid config hash": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "config_sha256", EVIDENCE_SHA256
                    ),
                ),
                "certificate evidence hash mismatch: config_sha256",
                SHA,
            ),
            "evidence bytes changed after certification": (
                lambda paths: paths["evidence_paths"][
                    "governed_runner_sha256"
                ].write_bytes(b"changed after certification"),
                "certificate evidence hash mismatch: governed_runner_sha256",
                SHA,
            ),
            "absolute completion receipt path": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "completion_receipt_path",
                        str(paths["completion"].resolve()),
                    ),
                ),
                "completion receipt path must be a portable relative path",
                SHA,
            ),
            "evidence bundle path escape": (
                lambda paths: rewrite_certificate(
                    paths,
                    lambda certificate: certificate.__setitem__(
                        "evidence_bundle_path", "../certificate-evidence-bundle.json"
                    ),
                ),
                "certificate evidence bundle path must be a portable relative path",
                SHA,
            ),
            "missing evidence bundle role": (
                lambda paths: _rewrite_evidence_bundle(
                    paths,
                    lambda bundle: bundle["evidence"].pop(
                        "governed_runner_sha256"
                    ),
                ),
                "certificate evidence bundle entry keys mismatch",
                SHA,
            ),
            "config role points at another repo artifact": (
                lambda paths: _rewrite_evidence_bundle(
                    paths,
                    lambda bundle: bundle["evidence"][
                        "config_sha256"
                    ].__setitem__(
                        "path",
                        "data/ember-restart-3b/input-identity.json",
                    ),
                ),
                "certificate evidence canonical path mismatch: config_sha256",
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
            "stale EMBER-01 active identity": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt.__setitem__("goal_id", "EMBER-01"),
                ),
                "completed/active authority identity",
                SHA,
            ),
            "wrong active workstream": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt.__setitem__(
                        "workstream_id", "EMBER-02B"
                    ),
                ),
                "completed/active authority identity",
                SHA,
            ),
            "wrong completed goal": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt.__setitem__(
                        "completed_goal_id", "EMBER-00"
                    ),
                ),
                "completed/active authority identity",
                SHA,
            ),
            "missing active workstream": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt.pop("workstream_id"),
                ),
                "completion receipt schema keys mismatch",
                SHA,
            ),
            "stale EMBER-01 selection": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["selection"].__setitem__(
                        "goal_id", "EMBER-01"
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
            "linked checkout head differs from declared master": (
                lambda paths: _rewrite_completion(
                    paths,
                    lambda receipt: receipt["checkout"].__setitem__(
                        "head", "c" * 40
                    ),
                ),
                "completion checkout head does not match",
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

    def test_invalid_dead_scope_values_refuse_before_child_spawn(self) -> None:
        module = load_module()
        cases = {
            "optimizer_steps": lambda request: request[
                "requested_scope"
            ].__setitem__("optimizer_steps", 0),
            "active_expert_families": lambda request: request[
                "requested_scope"
            ].__setitem__("active_expert_families", 0),
            "gpu_vram_gib": lambda request: request[
                "requested_scope"
            ].__setitem__("gpu_vram_gib", 0),
            "gpu_vram_gib NaN": lambda request: request[
                "requested_scope"
            ].__setitem__("gpu_vram_gib", float("nan")),
            "transient_checkpoint_gib": lambda request: request[
                "requested_scope"
            ].__setitem__("transient_checkpoint_gib", 0),
            "wall_minutes": lambda request: request[
                "requested_scope"
            ].__setitem__("wall_minutes", 0),
            "max_records": lambda request: request[
                "requested_scope"
            ].__setitem__("max_records", 0),
            "write_budget_bytes": lambda request: request[
                "requested_scope"
            ].__setitem__("write_budget_bytes", 0),
            "negative seed": lambda request: request.__setitem__("seed", -1),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    paths = write_valid_bundle(pathlib.Path(directory))
                    request = json.loads(
                        paths["run_spec"].read_text(encoding="utf-8")
                    )
                    mutate(request)
                    write_json(paths["run_spec"], request)
                    calls: list[object] = []
                    with mock.patch.object(
                        module, "read_current_master", return_value=SHA
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "positive|nonnegative|finite"
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
            self.assertEqual(
                argv[argv.index("--max-wall-seconds") + 1],
                "900.0",
            )
            self.assertEqual(
                argv[argv.index("--gpu-vram-gib") + 1],
                "20.0",
            )
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
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            for command in (
                ["git", "init", str(paths["repo"])],
                [
                    "git",
                    "-C",
                    str(paths["repo"]),
                    "config",
                    "user.email",
                    "ember-test@example.invalid",
                ],
                [
                    "git",
                    "-C",
                    str(paths["repo"]),
                    "config",
                    "user.name",
                    "Ember Test",
                ],
                ["git", "-C", str(paths["repo"]), "add", "."],
                [
                    "git",
                    "-C",
                    str(paths["repo"]),
                    "commit",
                    "-m",
                    "test fixture",
                ],
            ):
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    shell=False,
                )
            current_master = subprocess.run(
                ["git", "-C", str(paths["repo"]), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                shell=False,
            ).stdout.strip()
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
                    str(paths["repo"]),
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


def _rewrite_evidence_bundle(
    paths: dict[str, pathlib.Path],
    mutate,
) -> None:
    bundle = json.loads(paths["evidence_bundle"].read_text(encoding="utf-8"))
    mutate(bundle)
    write_json(paths["evidence_bundle"], bundle)
    bundle_sha256 = sha256_bytes(paths["evidence_bundle"].read_bytes())
    rewrite_certificate(
        paths,
        lambda certificate: certificate.__setitem__(
            "evidence_bundle_sha256", bundle_sha256
        ),
    )


if __name__ == "__main__":
    unittest.main()
