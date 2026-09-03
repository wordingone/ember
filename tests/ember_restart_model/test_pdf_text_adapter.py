# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from tools.corpus_connectors import pdf_to_utf8
from tools.corpus_connectors.tests.test_pdf_to_utf8 import _write_source_fixture

import text_lab_corpus


EVIDENCE = {
    "kind": "publisher_terms",
    "terms_url": "https://example.test/terms",
    "declared_spdx": "CC-BY-4.0",
}


class PdfTextAdapterContractTests(unittest.TestCase):
    def test_pdf_transform_generator_is_a_closed_l4_route_on_every_python(self) -> None:
        content_sha256 = hashlib.sha256(b"canonical PDF text\n").hexdigest()
        receipt = text_lab_corpus.local_license_provenance_v1(
            content_sha256=content_sha256,
            license_spdx="CC-BY-4.0",
            evidence=EVIDENCE,
            generator="pdf-text-extraction-v1",
        )
        self.assertEqual(receipt["schema_version"], "ember-text-source-receipt-v3")
        self.assertEqual(receipt["generator"], "pdf-text-extraction-v1")
        self.assertEqual(receipt["source_sha256"], content_sha256)

    @unittest.skipUnless(
        sys.version_info[:2] == (3, 10),
        "approved PDF extraction integration requires named Python 3.10; pure L4/refusal contract still runs",
    )
    def test_adapter_reopens_real_transform_and_returns_existing_admitted_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_receipt, source_receipt_sha256, _ = _write_source_fixture(root)
            output = root / "output"
            transform = pdf_to_utf8.produce_pdf_text_receipt(
                connector_receipt=source_receipt,
                connector_receipt_sha256=source_receipt_sha256,
                output_dir=output,
            )
            admitted = text_lab_corpus.adapt_pdf_extraction_receipt(
                receipt_path=output / pdf_to_utf8.RECEIPT_NAME,
                connector_receipt=source_receipt,
                connector_receipt_sha256=source_receipt_sha256,
                evidence=EVIDENCE,
            )
            self.assertEqual(
                set(admitted),
                {"content_sha256", "license_spdx", "license_evidence", "l4_receipt"},
            )
            self.assertEqual(admitted["content_sha256"], transform["output"]["sha256"])
            self.assertEqual(admitted["license_spdx"], "CC-BY-4.0")
            self.assertEqual(admitted["l4_receipt"]["generator"], "pdf-text-extraction-v1")

    @unittest.skipUnless(
        sys.version_info[:2] == (3, 10),
        "approved PDF extraction integration requires named Python 3.10; pure L4/refusal contract still runs",
    )
    def test_adapter_refuses_receipt_drift_before_admission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_receipt, source_receipt_sha256, _ = _write_source_fixture(root)
            output = root / "output"
            pdf_to_utf8.produce_pdf_text_receipt(
                connector_receipt=source_receipt,
                connector_receipt_sha256=source_receipt_sha256,
                output_dir=output,
            )
            receipt_path = output / pdf_to_utf8.RECEIPT_NAME
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source"]["source_id"] = "https://foreign.test/document.pdf"
            payload = dict(receipt)
            payload.pop("receipt_sha256")
            receipt["receipt_sha256"] = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source identity"):
                text_lab_corpus.adapt_pdf_extraction_receipt(
                    receipt_path=receipt_path,
                    connector_receipt=source_receipt,
                    connector_receipt_sha256=source_receipt_sha256,
                    evidence=EVIDENCE,
                )


if __name__ == "__main__":
    unittest.main()
