# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import copy
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "tools"
    / "ember-restart-3b"
    / "project_text_lab_custody_paths.py"
)

PARTITION_IDS = (
    "candidate-statistics-heldout-1",
    "candidate-training_infrastructure-train-1",
    "candidate-software_engineering-train-0",
    "candidate-software_engineering-train-1",
    "candidate-software_engineering-heldout-0",
    "candidate-software_engineering-heldout-1",
    "candidate-application_worlds-train-0",
    "candidate-application_worlds-train-1",
    "candidate-application_worlds-heldout-1",
)
PDF_IDS = (
    "candidate-physics-heldout-0",
    "candidate-computer_science-train-0",
    "candidate-scientific_method-heldout-0",
)


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "project_text_lab_custody_paths",
            MODULE_PATH,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def projection_fixture(root: pathlib.Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source_id in PARTITION_IDS:
        receipt = root / source_id / "partition-receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(b"partition\n")
        rows.append(
            {
                "source_id": source_id,
                "content_sha256": source_id.ljust(64, "0")[:64],
                "license_partition_receipt": str(receipt.resolve()),
                "license_partition_sha256": "a" * 64,
                "sentinel": source_id,
            }
        )
    for source_id in PDF_IDS:
        connector = root / source_id / "connector.json"
        transform = root / source_id / "transform.json"
        connector.parent.mkdir(parents=True)
        connector.write_bytes(b"connector\n")
        transform.write_text(
            json.dumps({"receipt_sha256": "c" * 64}),
            encoding="utf-8",
        )
        rows.append(
            {
                "source_id": source_id,
                "content_sha256": source_id.ljust(64, "0")[:64],
                "license_evidence": {
                    "kind": "publisher_terms",
                    "connector_receipt_path": str(connector.resolve()),
                    "connector_receipt_sha256": "b" * 64,
                    "transform_receipt_path": str(transform.resolve()),
                    "transform_receipt_sha256": "c" * 64,
                },
                "sentinel": source_id,
            }
        )
    return rows


def git(root: pathlib.Path, *args: str) -> str:
    kwargs = {
        "cwd": root,
        "capture_output": True,
        "check": True,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(["git", *args], **kwargs).stdout.strip()


def scratch_repository(root: pathlib.Path) -> tuple[str, str]:
    git(root, "init", "-q")
    git(root, "config", "user.email", "projection-test@example.invalid")
    git(root, "config", "user.name", "Projection Test")
    marker = root / "marker.txt"
    marker.write_text("one\n", encoding="utf-8")
    git(root, "add", "marker.txt")
    git(root, "commit", "-qm", "first")
    first = git(root, "rev-parse", "HEAD")
    marker.write_text("two\n", encoding="utf-8")
    git(root, "commit", "-qam", "second")
    second = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "--detach", second)
    return first, second


def projection_custody_fixture(module, root: pathlib.Path):
    receipt_root = root / "corpus"
    source = root / "source"
    source.mkdir()
    rows = projection_fixture(receipt_root)
    source_values = {
        "bundle": {"candidates": rows},
        "corpus": {"sources": rows},
        "identity": {"source_base_commit": "1" * 40},
        "index": {"schema_version": "fixture-index"},
    }
    source_raw = {}
    for role, name in module.ARTIFACTS.items():
        raw = module._canonical(source_values[role])
        (source / name).write_bytes(raw)
        source_raw[role] = raw
    predecessor_raw = module._canonical({"fixture": "immutable predecessor"})
    (source / "tranche-admission-receipt.json").write_bytes(predecessor_raw)
    projected_rows = module.project_rows(rows, receipt_custody_root=receipt_root)
    generated = {
        module.ARTIFACTS["bundle"]: module._canonical({"candidates": projected_rows}),
        module.ARTIFACTS["corpus"]: module._canonical({"sources": projected_rows}),
        module.ARTIFACTS["identity"]: module._canonical({"source_base_commit": "1" * 40}),
        module.ARTIFACTS["index"]: module._canonical({"schema_version": "fixture-index"}),
    }
    source_hashes = {role: module._sha(raw) for role, raw in source_raw.items()}
    return source, receipt_root, predecessor_raw, generated, source_hashes


class CustodyPathProjectionTests(unittest.TestCase):
    def test_mints_deterministic_closed_projection_receipt_and_reopens(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source, receipt_root, predecessor_raw, generated, source_hashes = projection_custody_fixture(module, root)
            authority_calls = []

            def validate_authority_index(repo, *, index_relative, external_authority_root):
                authority_calls.append(pathlib.Path(external_authority_root))
                self.assertEqual(index_relative, module.ARTIFACTS["index"])
                return {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"}

            with mock.patch.object(module, "SOURCE_SHA256", source_hashes), mock.patch.object(
                module, "build_projected_packet", return_value=generated
            ), mock.patch.object(module, "validate_authority_index", side_effect=validate_authority_index):
                first = module.mint_projection_custody(
                    repo=ROOT,
                    source_custody=source,
                    source_receipt_name="tranche-admission-receipt.json",
                    source_receipt_sha256=module._sha(predecessor_raw),
                    receipt_custody_root=receipt_root,
                    source_base_commit="1" * 40,
                    output=root / "first",
                )
                second = module.mint_projection_custody(
                    repo=ROOT,
                    source_custody=source,
                    source_receipt_name="tranche-admission-receipt.json",
                    source_receipt_sha256=module._sha(predecessor_raw),
                    receipt_custody_root=receipt_root,
                    source_base_commit="1" * 40,
                    output=root / "second",
                )
                self.assertEqual(
                    (root / "first" / module.PROJECTION_RECEIPT).read_bytes(),
                    (root / "second" / module.PROJECTION_RECEIPT).read_bytes(),
                )
                reopened = module.validate_projection_custody(
                    repo=ROOT,
                    projection_receipt_path=root / "first" / module.PROJECTION_RECEIPT,
                    expected_receipt_sha256=first["receipt_sha256"],
                    source_custody=source,
                    source_receipt_name="tranche-admission-receipt.json",
                    source_receipt_sha256=module._sha(predecessor_raw),
                )
                self.assertEqual(reopened["generated"], generated)
                self.assertEqual(len(reopened["receipt"]["row_mappings"]), 12)
                self.assertEqual(
                    reopened["receipt"]["validation_receipt"],
                    {"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"},
                )
                self.assertEqual(len(authority_calls), 5)
                self.assertTrue(authority_calls[0].name.startswith(".first.staging-"))
                self.assertEqual(authority_calls[1], root / "first")
                self.assertTrue(authority_calls[2].name.startswith(".second.staging-"))
                self.assertEqual(authority_calls[3:], [root / "second", root / "first"])

    def test_atomic_projection_publish_refuses_existing_destination(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            with self.assertRaises(FileExistsError):
                module.atomic_publish_no_replace(source, destination)
            self.assertTrue(source.is_dir())
            self.assertTrue(destination.is_dir())

    def test_projection_receipt_refuses_tamper_swap_root_and_row_set_drift(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source, receipt_root, predecessor_raw, generated, source_hashes = projection_custody_fixture(module, root)
            with mock.patch.object(module, "SOURCE_SHA256", source_hashes), mock.patch.object(
                module, "build_projected_packet", return_value=generated
            ), mock.patch.object(
                module,
                "validate_authority_index",
                return_value={"result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"},
            ):
                for mutation in ("artifact", "swap", "root", "absent", "extra"):
                    output = root / mutation
                    module.mint_projection_custody(
                        repo=ROOT, source_custody=source,
                        source_receipt_name="tranche-admission-receipt.json",
                        source_receipt_sha256=module._sha(predecessor_raw),
                        receipt_custody_root=receipt_root,
                        source_base_commit="1" * 40, output=output,
                    )
                    receipt_path = output / module.PROJECTION_RECEIPT
                    receipt = json.loads(receipt_path.read_bytes())
                    if mutation == "artifact":
                        (output / module.ARTIFACTS["bundle"]).write_bytes(b"tampered")
                    elif mutation == "swap":
                        receipt["row_mappings"][0], receipt["row_mappings"][1] = receipt["row_mappings"][1], receipt["row_mappings"][0]
                    elif mutation == "root":
                        receipt["receipt_custody_root"] = str((root / "other-root").resolve())
                    elif mutation == "absent":
                        receipt["row_mappings"].pop()
                    else:
                        receipt["row_mappings"].append(copy.deepcopy(receipt["row_mappings"][0]))
                    if mutation != "artifact":
                        receipt_path.write_bytes(module._canonical(receipt))
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        module.validate_projection_custody(
                            repo=ROOT,
                            projection_receipt_path=receipt_path,
                            expected_receipt_sha256=module._sha(receipt_path.read_bytes()),
                            source_custody=source,
                            source_receipt_name="tranche-admission-receipt.json",
                            source_receipt_sha256=module._sha(predecessor_raw),
                        )
    def test_write_source_base_commit_refuses_malformed_and_non_ancestor(self):
        """Catches caller-minted or unreachable source identity on a write."""
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "repo"
            other = pathlib.Path(directory) / "other"
            repo.mkdir()
            other.mkdir()
            first, _ = scratch_repository(repo)
            scratch_repository(other)
            (other / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
            git(other, "add", "unrelated.txt")
            git(other, "commit", "-qm", "unrelated")
            unrelated = git(other, "rev-parse", "HEAD")

            self.assertEqual(
                module.resolve_source_base_commit(
                    repo=repo,
                    write=True,
                    requested=first,
                ),
                first,
            )
            for candidate in ("not-a-sha", unrelated):
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    module.resolve_source_base_commit(
                        repo=repo,
                        write=True,
                        requested=candidate,
                    )

    def test_check_reuses_recorded_source_base_from_different_detached_head(self):
        """Catches check mode restamping the invoking checkout's live HEAD."""
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "repo"
            repo.mkdir()
            recorded, detached_head = scratch_repository(repo)
            identity = (
                repo
                / "data"
                / "ember-restart-3b"
                / "owned-text-lab-input-identity-v4.json"
            )
            identity.parent.mkdir(parents=True)
            identity.write_text(
                json.dumps({"source_base_commit": recorded}),
                encoding="utf-8",
            )

            self.assertNotEqual(recorded, detached_head)
            self.assertEqual(
                module.resolve_source_base_commit(
                    repo=repo,
                    write=False,
                    requested=None,
                ),
                recorded,
            )

    def test_projects_exact_twelve_paths_and_preserves_every_other_row_byte_value(self):
        """Catches path projection changing payload identity or skipping one class member."""
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            custody_root = pathlib.Path(directory) / "corpus"
            rows = projection_fixture(custody_root)
            before = copy.deepcopy(rows)
            projected = module.project_rows(
                rows,
                receipt_custody_root=custody_root,
            )

            self.assertEqual(len(projected), 12)
            for original, result in zip(before, projected, strict=True):
                self.assertEqual(result["source_id"], original["source_id"])
                self.assertEqual(result["content_sha256"], original["content_sha256"])
                self.assertEqual(result["sentinel"], original["sentinel"])
                if result["source_id"] in PARTITION_IDS:
                    self.assertNotIn(":", result["license_partition_receipt"])
                    self.assertNotIn("\\", result["license_partition_receipt"])
                else:
                    evidence = result["license_evidence"]
                    self.assertNotIn(":", evidence["connector_receipt_path"])
                    self.assertNotIn("\\", evidence["connector_receipt_path"])
                    self.assertNotIn(":", evidence["transform_receipt_path"])
                    self.assertNotIn("\\", evidence["transform_receipt_path"])
                    original_transform = pathlib.Path(
                        original["license_evidence"]["transform_receipt_path"]
                    )
                    self.assertEqual(
                        evidence["transform_receipt_raw_sha256"],
                        module._sha(original_transform.read_bytes()),
                    )

    def test_refuses_missing_extra_and_outside_projection_class(self):
        """Catches a partial, widened, or cross-root authority-row projection."""
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            custody_root = pathlib.Path(directory) / "corpus"
            rows = projection_fixture(custody_root)
            outside = pathlib.Path(directory) / "outside.json"
            outside.write_bytes(b"outside\n")
            for candidate in (
                rows[:-1],
                rows + [{"source_id": "candidate-extra-train-0"}],
                [
                    {
                        **row,
                        "license_partition_receipt": str(outside.resolve()),
                    }
                    if row["source_id"] == PARTITION_IDS[0]
                    else row
                    for row in rows
                ],
            ):
                with self.subTest(count=len(candidate)), self.assertRaises(ValueError):
                    module.project_rows(
                        candidate,
                        receipt_custody_root=custody_root,
                    )


if __name__ == "__main__":
    unittest.main()
