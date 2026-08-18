# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.corpus_connectors.tests.test_pdf_to_utf8 import _minimal_pdf


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _write_tree_fixture(
    root: Path, *, empty_second: bool = False, malformed_second: bool = False
) -> tuple[Path, str, Path]:
    source = root / "source"
    source.mkdir()
    rows = []
    for relative, text in (
        ("alpha/document.pdf", "Alpha text"),
        ("beta/document.pdf", "   " if empty_second else "Beta text"),
    ):
        path = source / relative
        path.parent.mkdir()
        raw = _minimal_pdf(text)
        if malformed_second and relative.startswith("beta/"):
            start = raw.index(b"3 0 obj")
            end = raw.index(b"4 0 obj")
            malformed = (
                b"3 0 obj\nconcordance:chapter.tex:chapter.Rnw:1 33 1 1 0 "
                b"7 1 1 17 270 "
            )
            raw = raw[:start] + malformed.ljust(end - start, b" ") + raw[end:]
        path.write_bytes(raw)
        rows.append({"path": relative, "bytes": len(raw), "sha256": _sha256(raw)})
    rows.sort(key=lambda row: row["path"])
    receipt = {
        "canonical_url": "https://export.arxiv.org/api/query",
        "connector": {"name": "arxiv_fetch", "version": "v2"},
        "dest_root": str(source),
        "fetched_at": "2026-08-18T00:00:00Z",
        "files": rows,
        "l3_statement": "fetch-only; no external model authored/filtered/ranked/scored/selected any token",
        "license": "http://creativecommons.org/licenses/by/4.0/",
        "license_evidence": "fixture exact CC-BY-4.0",
        "notes": "fixture",
        "revision": None,
        "schema": "corpus-connector-receipt-v1",
        "sha256_manifest": _sha256("\n".join(sorted(row["sha256"] for row in rows)).encode()),
        "source": "arxiv",
        "source_id": "fixture:two-pdf-tree",
        "total_bytes": sum(row["bytes"] for row in rows),
    }
    receipt_path = root / "connector-receipt.json"
    raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    receipt_path.write_bytes(raw)
    return receipt_path, _sha256(raw), source


def _write_pass_census(module: object, root: Path, receipt: Path, receipt_sha256: str) -> tuple[Path, str]:
    report = root / "refusal-census.json"
    module.census_pdf_tree_refusals(
        connector_receipt=receipt,
        connector_receipt_sha256=receipt_sha256,
        report_path=report,
    )
    return report, _sha256(report.read_bytes())


def _write_exclusion_set(
    root: Path,
    census: Path,
    census_sha256: str,
    files: list[dict[str, str]],
) -> tuple[Path, str]:
    exclusion_path = root / "pdf-exclusion-set.json"
    payload = {
        "schema": "ember-pdf-tree-exclusion-set-v1",
        "census_report_sha256": census_sha256,
        "files": files,
    }
    payload["receipt_sha256"] = _sha256(_canonical(payload))
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    exclusion_path.write_bytes(raw)
    return exclusion_path, _sha256(raw)


class PdfTreeToUtf8Tests(unittest.TestCase):
    def test_produces_collision_free_closed_tree_and_reextracts_every_pdf(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, source = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            output = root / "output"

            receipt = module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                output_dir=output,
            )

            self.assertEqual(receipt["result"], "VERIFIED")
            self.assertEqual(receipt["source"]["file_count"], 2)
            self.assertEqual(
                [row["output_path"] for row in receipt["files"]],
                ["documents/alpha/document.pdf.txt", "documents/beta/document.pdf.txt"],
            )
            self.assertEqual((output / "documents/alpha/document.pdf.txt").read_bytes(), b"Alpha text\n")
            self.assertEqual((output / "documents/beta/document.pdf.txt").read_bytes(), b"Beta text\n")
            self.assertTrue((source / "alpha/document.pdf").is_file())
            self.assertEqual(
                module.verify_pdf_tree_receipt(
                    receipt_path=output / "_manifests/pdf-tree-extraction-receipt.json",
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                ),
                receipt,
            )

    def test_refuses_one_empty_pdf_without_publishing_partial_custody(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root, empty_second=True)
            census = root / "refusal-census.json"
            module.census_pdf_tree_refusals(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                report_path=census,
            )
            output = root / "output"
            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "requires an explicit exclusion set"):
                module.produce_pdf_tree_receipt(
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                    census_report=census,
                    census_report_sha256=_sha256(census.read_bytes()),
                    output_dir=output,
                )
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".output.staging-*")), [])

    def test_exact_census_refusal_partition_transforms_only_pass_rows(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root, empty_second=True)
            census = root / "refusal-census.json"
            census_receipt = module.census_pdf_tree_refusals(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                report_path=census,
            )
            census_sha256 = _sha256(census.read_bytes())
            refused = census_receipt["files"][1]
            exclusion, exclusion_sha256 = _write_exclusion_set(
                root,
                census,
                census_sha256,
                [{"source_path": refused["source_path"], "source_sha256": refused["source_sha256"]}],
            )
            output = root / "output"

            receipt = module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                exclusion_set=exclusion,
                exclusion_set_sha256=exclusion_sha256,
                output_dir=output,
            )

            self.assertEqual(receipt["result"], "VERIFIED")
            self.assertEqual(receipt["totals"]["source_file_count"], 2)
            self.assertEqual(receipt["totals"]["file_count"], 1)
            self.assertEqual(receipt["totals"]["excluded_file_count"], 1)
            self.assertEqual(receipt["exclusions"]["requested_files"], [
                {"source_path": refused["source_path"], "source_sha256": refused["source_sha256"]}
            ])
            self.assertEqual(receipt["exclusions"]["census_refusal_rows"], [refused])
            self.assertEqual([row["source_path"] for row in receipt["files"]], ["alpha/document.pdf"])
            self.assertTrue((output / "documents/alpha/document.pdf.txt").is_file())
            self.assertFalse((output / "documents/beta/document.pdf.txt").exists())
            self.assertEqual(
                module.verify_pdf_tree_receipt(
                    receipt_path=output / "_manifests/pdf-tree-extraction-receipt.json",
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                ),
                receipt,
            )

    def test_exclusion_set_must_equal_exact_census_refusal_set(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root, empty_second=True)
            census = root / "refusal-census.json"
            module.census_pdf_tree_refusals(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                report_path=census,
            )
            census_sha256 = _sha256(census.read_bytes())
            for label, files in (
                ("omits refused row", []),
                ("names PASS row", [{"source_path": "alpha/document.pdf", "source_sha256": json.loads(connector_receipt.read_bytes())["files"][0]["sha256"]}]),
            ):
                with self.subTest(label=label):
                    exclusion, exclusion_sha256 = _write_exclusion_set(
                        root,
                        census,
                        census_sha256,
                        files,
                    )
                    with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "exactly equal census refusal"):
                        module.produce_pdf_tree_receipt(
                            connector_receipt=connector_receipt,
                            connector_receipt_sha256=connector_sha256,
                            census_report=census,
                            census_report_sha256=census_sha256,
                            exclusion_set=exclusion,
                            exclusion_set_sha256=exclusion_sha256,
                            output_dir=root / f"output-{len(files)}",
                        )
                    exclusion.unlink()

    def test_census_records_every_refusal_without_writing_transform_custody(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root, empty_second=True)
            report_path = root / "refusal-census.json"

            report = module.census_pdf_tree_refusals(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                report_path=report_path,
            )

            self.assertEqual(report["result"], "REFUSED")
            self.assertEqual(report["totals"]["pass_count"], 1)
            self.assertEqual(report["totals"]["refusal_count"], 1)
            self.assertEqual(
                [(row["source_path"], row["result"], row.get("refusal_class")) for row in report["files"]],
                [
                    ("alpha/document.pdf", "PASS", None),
                    ("beta/document.pdf", "REFUSED", "EMPTY_TEXT"),
                ],
            )
            self.assertEqual(json.loads(report_path.read_bytes()), report)
            self.assertEqual({path.name for path in root.iterdir()}, {"source", "connector-receipt.json", "refusal-census.json"})

    def test_census_seals_valid_and_unwrapped_malformed_pdf_rows(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(
                root, malformed_second=True
            )
            report_path = root / "refusal-census.json"

            report = module.census_pdf_tree_refusals(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                report_path=report_path,
            )

            self.assertEqual(report["result"], "REFUSED")
            self.assertEqual(report["totals"], {
                "file_count": 2, "pass_count": 1, "refusal_count": 1,
            })
            self.assertEqual(report["files"][0]["result"], "PASS")
            refusal = report["files"][1]
            self.assertEqual(refusal["source_path"], "beta/document.pdf")
            self.assertEqual(refusal["result"], "REFUSED")
            self.assertEqual(refusal["refusal_class"], "UNWRAPPED_EXTRACTOR_ERROR")
            self.assertEqual(refusal["exception_class"], "PdfReadError")
            self.assertLessEqual(len(refusal["detail"]), 320)
            self.assertEqual(json.loads(report_path.read_bytes()), report)

    def test_census_does_not_convert_memory_exhaustion_into_a_file_refusal(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            report_path = root / "refusal-census.json"
            with patch.object(module, "_extract_one", side_effect=MemoryError("fatal")):
                with self.assertRaises(MemoryError):
                    module.census_pdf_tree_refusals(
                        connector_receipt=connector_receipt,
                        connector_receipt_sha256=connector_sha256,
                        report_path=report_path,
                    )
            self.assertFalse(report_path.exists())

    def test_produce_structurally_requires_a_census(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            with self.assertRaisesRegex(TypeError, "census_report"):
                module.produce_pdf_tree_receipt(
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                    output_dir=root / "output",
                )

    def test_produce_refuses_a_census_for_another_connector_receipt(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            first_receipt, first_sha256, _ = _write_tree_fixture(first)
            second_receipt, second_sha256, _ = _write_tree_fixture(second)
            census, census_sha256 = _write_pass_census(module, root, first_receipt, first_sha256)

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "census connector"):
                module.produce_pdf_tree_receipt(
                    connector_receipt=second_receipt,
                    connector_receipt_sha256=second_sha256,
                    census_report=census,
                    census_report_sha256=census_sha256,
                    output_dir=root / "output",
                )

    def test_produce_refuses_a_bound_census_relocated_inside_source_custody(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, source = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            relocated = source / "_manifests/refusal-census.json"
            relocated.parent.mkdir()
            relocated.write_bytes(census.read_bytes())

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "outside connector custody"):
                module.produce_pdf_tree_receipt(
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                    census_report=relocated,
                    census_report_sha256=census_sha256,
                    output_dir=root / "output",
                )

    def test_cli_exposes_census_without_requiring_an_output_directory(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            report_path = root / "refusal-census.json"
            with redirect_stdout(io.StringIO()):
                returncode = module.main([
                    "--connector-receipt",
                    str(connector_receipt),
                    "--connector-receipt-sha256",
                    connector_sha256,
                    "--census-report",
                    str(report_path),
                ])
            self.assertEqual(returncode, 0)
            self.assertEqual(json.loads(report_path.read_bytes())["result"], "PASS")

    def test_verify_refuses_a_reordered_file_map_even_when_self_hash_is_reminted(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            output = root / "output"
            module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                output_dir=output,
            )
            receipt_path = output / "_manifests/pdf-tree-extraction-receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["files"].reverse()
            payload = dict(receipt)
            payload.pop("receipt_sha256")
            receipt["receipt_sha256"] = _sha256(_canonical(payload))
            receipt_path.write_bytes((json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "file map order"):
                module.verify_pdf_tree_receipt(
                    receipt_path=receipt_path,
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                )

    def test_verify_refuses_an_open_extractor_shape_before_using_its_bounds(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            output = root / "output"
            module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                output_dir=output,
            )
            receipt_path = output / "_manifests/pdf-tree-extraction-receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["extractor"].pop("max_files")
            payload = dict(receipt)
            payload.pop("receipt_sha256")
            receipt["receipt_sha256"] = _sha256(_canonical(payload))
            receipt_path.write_bytes((json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "extractor identity"):
                module.verify_pdf_tree_receipt(
                    receipt_path=receipt_path,
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                )

    def test_derived_tree_composes_with_license_sidecar_and_real_adapter(self) -> None:
        from tools.corpus_connectors import mint_connector_license_sidecar as license_sidecar
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            transform_root = root / "transform"
            module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                output_dir=transform_root,
            )
            transformed_receipt = transform_root / "_manifests/derived-connector-receipt.json"

            license_root = root / "license"
            license_root.mkdir()
            license_payload = license_root / "LICENSE.md"
            license_payload.write_bytes(b"Creative Commons Attribution 4.0 International\n")
            license_digest = _sha256(license_payload.read_bytes())
            license_receipt = {
                "canonical_url": "https://creativecommons.org/licenses/by/4.0/legalcode",
                "connector": {"name": "http_fetch", "version": "v1"},
                "dest_root": str(license_root),
                "fetched_at": "2026-08-18T00:00:00Z",
                "files": [{"path": "LICENSE.md", "bytes": license_payload.stat().st_size, "sha256": license_digest}],
                "l3_statement": "fetch-only",
                "license": "CC-BY-4.0",
                "license_evidence": "canonical license text",
                "notes": "fixture",
                "revision": None,
                "schema": "corpus-connector-receipt-v1",
                "sha256_manifest": _sha256(license_digest.encode()),
                "source": "http",
                "source_id": "cc-by-4.0-license",
                "total_bytes": license_payload.stat().st_size,
            }
            license_receipt_path = root / "license-receipt.json"
            license_receipt_raw = (json.dumps(license_receipt, sort_keys=True, indent=2) + "\n").encode()
            license_receipt_path.write_bytes(license_receipt_raw)

            licensed = license_sidecar.mint_license_sidecar(
                original_receipt_path=transformed_receipt,
                original_receipt_sha256=_sha256(transformed_receipt.read_bytes()),
                license_receipt_path=license_receipt_path,
                license_receipt_sha256=_sha256(license_receipt_raw),
                license_payload_path=license_payload,
                license_payload_sha256=license_digest,
                expected_spdx="CC-BY-4.0",
                output=root / "licensed",
            )
            adapter_path = Path(__file__).resolve().parents[3] / "tools/ember-restart-3b/text_lab_corpus.py"
            spec = importlib.util.spec_from_file_location("pdf_tree_text_lab_adapter", adapter_path)
            assert spec and spec.loader
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            adapted = adapter.adapt_connector_receipt(
                json.loads(Path(licensed["connector_receipt_path"]).read_bytes()),
                evidence={
                    "kind": "spdx_repo_license",
                    "license_sha256": license_digest,
                    "declared_spdx": "CC-BY-4.0",
                },
            )
            self.assertEqual(adapted["license_spdx"], "CC-BY-4.0")
            self.assertEqual(adapted["l4_receipt"]["result"], "VERIFIED")

    def test_verify_refuses_an_extra_manifest_sidecar(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            output = root / "output"
            module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                output_dir=output,
            )
            (output / "_manifests/rogue.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "missing or extra paths"):
                module.verify_pdf_tree_receipt(
                    receipt_path=output / "_manifests/pdf-tree-extraction-receipt.json",
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                )

    def test_verify_refuses_an_extra_empty_directory(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            output = root / "output"
            module.produce_pdf_tree_receipt(
                connector_receipt=connector_receipt,
                connector_receipt_sha256=connector_sha256,
                census_report=census,
                census_report_sha256=census_sha256,
                output_dir=output,
            )
            (output / "rogue-empty-directory").mkdir()

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "missing or extra paths"):
                module.verify_pdf_tree_receipt(
                    receipt_path=output / "_manifests/pdf-tree-extraction-receipt.json",
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                )

    def test_produce_rolls_back_an_extra_manifest_added_at_publish_boundary(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, _ = _write_tree_fixture(root)
            census, census_sha256 = _write_pass_census(module, root, connector_receipt, connector_sha256)
            output = root / "output"
            real_rename = module.os.rename

            def rename_then_inject(source: Path, destination: Path) -> None:
                real_rename(source, destination)
                (Path(destination) / "_manifests/rogue.json").write_text("{}\n", encoding="utf-8")

            module.os.rename = rename_then_inject
            try:
                with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "published PDF tree custody"):
                    module.produce_pdf_tree_receipt(
                        connector_receipt=connector_receipt,
                        connector_receipt_sha256=connector_sha256,
                        census_report=census,
                        census_report_sha256=census_sha256,
                        output_dir=output,
                    )
            finally:
                module.os.rename = real_rename
            self.assertFalse(output.exists())

    def test_census_refuses_to_write_inside_source_custody(self) -> None:
        from tools.corpus_connectors import pdf_tree_to_utf8 as module

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            connector_receipt, connector_sha256, source = _write_tree_fixture(root)
            manifest_root = source / "_manifests"
            manifest_root.mkdir()
            report_path = manifest_root / "refusal-census.json"

            with self.assertRaisesRegex(module.PdfTreeExtractionRefusal, "outside connector custody"):
                module.census_pdf_tree_refusals(
                    connector_receipt=connector_receipt,
                    connector_receipt_sha256=connector_sha256,
                    report_path=report_path,
                )
            self.assertFalse(report_path.exists())


if __name__ == "__main__":
    unittest.main()
