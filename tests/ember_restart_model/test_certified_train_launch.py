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
SHA = "a" * 64


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
        "goal_id": "EMBER-01",
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
            "goal_id": "EMBER-01",
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
        "declared_by_role": "KAI_SOL",
        "declared_at_utc": "2026-07-23T08:00:00+00:00",
        "superseded_by": None,
        "completion_receipt_path": str(completion_path),
        "completion_receipt_sha256": completion_sha256,
        "public_master_sha256": SHA,
        "checkout_sha256": SHA,
        "config_sha256": SHA,
        "tokenizer_sha256": SHA,
        "input_authority_sha256": SHA,
        "cli_binary_sha256": SHA,
        "launch_packet_sha256": SHA,
        "board_receipt_sha256": SHA,
        "benchmark_registry_sha256": SHA,
        "failure_class_ledger_sha256": SHA,
        "subject_manifest_sha256": SHA,
        "seat_sha256": SHA,
        "root_summary_sha256": SHA,
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
                "declared_by_role": "KAI_SOL",
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
            "declared_by_role": "KAI_SOL",
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
            self.assertEqual(launch.public_master_sha256, SHA)
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
                        "declared_by_role", "NIKO"
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
                "b" * 64,
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


if __name__ == "__main__":
    unittest.main()
