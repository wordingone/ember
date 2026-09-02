# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT\n/F1 12 Tf\n72 720 Td\n({escaped}) Tj\nET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n"
        + stream + b"\nendstream endobj\n",
    ]
    chunks = [b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"]
    offsets: list[int] = []
    for obj in objects:
        offsets.append(sum(map(len, chunks)))
        chunks.append(obj)
    xref_offset = sum(map(len, chunks))
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    trailer = f"trailer << /Root 1 0 R /Size 6 >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    return b"".join(chunks + xref + [trailer])


def _write_source_fixture(root: Path, *, text: str = "Hello PDF") -> tuple[Path, str, Path]:
    source_root = root / "source"
    source_root.mkdir(parents=True)
    pdf_path = source_root / "document.pdf"
    pdf_bytes = _minimal_pdf(text)
    pdf_path.write_bytes(pdf_bytes)
    receipt = {
        "canonical_url": "https://example.test/document.pdf",
        "connector": {"name": "http_fetch", "version": "v1"},
        "dest_root": str(source_root),
        "fetched_at": "2026-08-18T00:00:00Z",
        "files": [{"bytes": len(pdf_bytes), "path": "document.pdf", "sha256": _sha256(pdf_bytes)}],
        "l3_statement": "fetch-only; no external model authored/filtered/ranked/scored/selected any token",
        "license": "CC-BY-4.0",
        "license_evidence": "fixture publisher terms",
        "notes": "fixture",
        "revision": None,
        "schema": "corpus-connector-receipt-v1",
        "sha256_manifest": _sha256(_sha256(pdf_bytes).encode("utf-8")),
        "source": "http",
        "source_id": "https://example.test/document.pdf",
        "total_bytes": len(pdf_bytes),
    }
    receipt_path = root / "connector-receipt.json"
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    return receipt_path, _sha256(receipt_bytes), pdf_path


class PdfToUtf8Tests(unittest.TestCase):
    def test_pdf_extraction_producer_exists(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        self.assertTrue(callable(module.produce_pdf_text_receipt))

    def test_normalization_is_nfc_lf_and_one_trailing_newline(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        self.assertEqual(module.normalize_extracted_text(" A \r\nCafe\u0301\r\n\r\n"), " A\nCaf\u00e9\n")

    def test_v2_repairs_surrogate_pairs_and_escapes_only_isolated_units(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        repaired, paired, escaped = module.repair_extracted_surrogates(
            "pair=\ud83d\ude00 isolated=\ud800 literal=\\uD800"
        )
        self.assertEqual(repaired, "pair=\U0001f600 isolated=\\uD800 literal=\\uD800")
        self.assertEqual(paired, 1)
        self.assertEqual(escaped, 1)

    def test_v2_sanitizer_removes_only_exact_invalid_pgf_prefixes(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        sanitized, removed = module.sanitize_invalid_pgf_content(
            b"  obj @pgfcolorspaces bad\nnot obj @pgfcolorspaces keep\npagesize width bad\n"
        )
        self.assertEqual(sanitized, b"not obj @pgfcolorspaces keep\n")
        self.assertEqual(removed, 2)

    def test_v2_sanitizer_is_refusal_gated_and_receipts_triggered_pages(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")

        class FakePage:
            def __init__(self, *, refuses_once: bool) -> None:
                self.refuses_once = refuses_once
                self.calls = 0
                self.mutations = 0
                self.contents = SimpleNamespace(
                    get_data=lambda: b"obj @pgfcolorspaces bad\nBT (fine) Tj ET\n"
                )

            def get_contents(self):
                return self.contents

            def extract_text(self):
                self.calls += 1
                if self.refuses_once and self.calls == 1:
                    raise ValueError("invalid elementary object starting with b'@'")
                return "Recovered" if self.refuses_once else "Already valid"

            def raw_get(self, _name):
                return self.contents

            def __setitem__(self, _name, value):
                self.mutations += 1
                self.contents = value

        for refuses_once, expected_text, expected_triggered, expected_mutations in (
            (True, b"Recovered\n", True, 2),
            (False, b"Already valid\n", False, 0),
        ):
            with self.subTest(refuses_once=refuses_once):
                page = FakePage(refuses_once=refuses_once)
                fake_pypdf = SimpleNamespace(
                    PdfReader=lambda *_args, _page=page, **kwargs: SimpleNamespace(pages=[_page])
                )
                with mock.patch.object(module, "_load_pypdf", return_value=fake_pypdf):
                    output, pages, decoded, audit = module._extract_pdf(
                        Path("ignored.pdf"),
                        max_pages=4,
                        max_decoded_content_bytes=1_000_000,
                        max_output_bytes=1_000_000,
                    )
                self.assertEqual(output, expected_text)
                self.assertEqual(pages, 1)
                self.assertGreater(decoded, 0)
                self.assertEqual(bool(audit["sanitized_pages"]), expected_triggered)
                self.assertEqual(page.mutations, expected_mutations)
                self.assertEqual(audit["extractor_semantics_version"], "v2")

    def test_produce_and_independently_verify_real_pdf(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_receipt, source_receipt_sha256, pdf_path = _write_source_fixture(root)
            output = root / "output"
            receipt = module.produce_pdf_text_receipt(
                connector_receipt=source_receipt,
                connector_receipt_sha256=source_receipt_sha256,
                output_dir=output,
                max_pages=4,
                max_decoded_content_bytes=1_000_000,
                max_output_bytes=1_000_000,
            )
            self.assertEqual((output / "document.txt").read_bytes(), b"Hello PDF\n")
            self.assertEqual(receipt["result"], "VERIFIED")
            self.assertEqual(receipt["source"]["pdf_sha256"], _sha256(pdf_path.read_bytes()))
            self.assertEqual(receipt["extractor"]["pypdf_version"], "6.16.1")
            self.assertEqual(receipt["extractor"]["python_major_minor"], "3.10")
            self.assertEqual(receipt["extractor"]["extractor_semantics_version"], "v2")
            self.assertIs(receipt["extractor"]["reader_strict"], False)
            self.assertEqual(receipt["output"]["extractor_semantics_version"], "v2")
            self.assertEqual(receipt["output"]["sanitized_pages"], [])
            self.assertTrue(pdf_path.is_file(), "the immutable source PDF must be preserved")
            self.assertEqual(
                module.verify_pdf_text_receipt(
                    receipt_path=output / "pdf-text-extraction-receipt.json",
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                ),
                receipt,
            )

    def test_refuses_wrong_runtime_and_dependency_versions(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        with self.assertRaisesRegex(module.PdfExtractionRefusal, "Python 3.10"):
            module.require_runtime_contract(python_major_minor="3.12", pypdf_version="6.16.1")
        with self.assertRaisesRegex(module.PdfExtractionRefusal, "pypdf 6.16.1"):
            module.require_runtime_contract(python_major_minor="3.10", pypdf_version="6.1.3")

    def test_refuses_source_drift_output_overwrite_and_output_tamper(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_receipt, source_receipt_sha256, pdf_path = _write_source_fixture(root)
            pdf_path.write_bytes(pdf_path.read_bytes() + b"drift")
            with self.assertRaisesRegex(module.PdfExtractionRefusal, "source PDF"):
                module.produce_pdf_text_receipt(
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                    output_dir=root / "drift-output",
                )

            source_receipt, source_receipt_sha256, _ = _write_source_fixture(root / "fresh")
            output = root / "output"
            module.produce_pdf_text_receipt(
                connector_receipt=source_receipt,
                connector_receipt_sha256=source_receipt_sha256,
                output_dir=output,
            )
            with self.assertRaisesRegex(module.PdfExtractionRefusal, "already exists"):
                module.produce_pdf_text_receipt(
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                    output_dir=output,
                )
            (output / "document.txt").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(module.PdfExtractionRefusal, "output"):
                module.verify_pdf_text_receipt(
                    receipt_path=output / "pdf-text-extraction-receipt.json",
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                )

    def test_refuses_page_decoded_content_and_output_bounds(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_receipt, source_receipt_sha256, _ = _write_source_fixture(root, text="x" * 200)
            with self.assertRaisesRegex(module.PdfExtractionRefusal, "decoded content"):
                module.produce_pdf_text_receipt(
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                    output_dir=root / "decoded-bound",
                    max_decoded_content_bytes=16,
                )
            with self.assertRaisesRegex(module.PdfExtractionRefusal, "output byte"):
                module.produce_pdf_text_receipt(
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                    output_dir=root / "output-bound",
                    max_output_bytes=16,
                )

    def test_refuses_empty_extracted_text(self) -> None:
        module = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.pdf_to_utf8")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_receipt, source_receipt_sha256, _ = _write_source_fixture(root, text="   ")
            with self.assertRaisesRegex(module.PdfExtractionRefusal, "empty text"):
                module.produce_pdf_text_receipt(
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                    output_dir=root / "empty-output",
                )


if __name__ == "__main__":
    unittest.main()
