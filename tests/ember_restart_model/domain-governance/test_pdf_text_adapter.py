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

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from tools.corpus_connectors import pdf_to_utf8
# issue2015 exact-local-import:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py
import importlib.util as _ember_29820f39de2914fc_importlib
import sys as _ember_29820f39de2914fc_sys
from pathlib import Path as _ember_29820f39de2914fc_Path
_ember_29820f39de2914fc_path = _ember_29820f39de2914fc_Path(__file__).resolve().parents[3].joinpath('src', 'ember', 'infrastructure', 'tools', 'corpus_connectors', 'tests', 'test_pdf_to_utf8.py')
if not _ember_29820f39de2914fc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py')
_ember_29820f39de2914fc_aliases = ('_ember_issue2015_29820f39de2914fc', 'src.ember.infrastructure.tools.corpus_connectors.tests.test_pdf_to_utf8', 'test_pdf_to_utf8', 'tools.corpus_connectors.tests.test_pdf_to_utf8')
_ember_29820f39de2914fc_existing = []
for _ember_29820f39de2914fc_alias in _ember_29820f39de2914fc_aliases:
    _ember_29820f39de2914fc_candidate = _ember_29820f39de2914fc_sys.modules.get(_ember_29820f39de2914fc_alias)
    if _ember_29820f39de2914fc_candidate is not None and all(_ember_29820f39de2914fc_candidate is not item for item in _ember_29820f39de2914fc_existing):
        _ember_29820f39de2914fc_existing.append(_ember_29820f39de2914fc_candidate)
if len(_ember_29820f39de2914fc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py')
if _ember_29820f39de2914fc_existing:
    _ember_29820f39de2914fc_module = _ember_29820f39de2914fc_existing[0]
    _ember_29820f39de2914fc_observed = getattr(_ember_29820f39de2914fc_module, '__file__', None)
    if _ember_29820f39de2914fc_observed is None or _ember_29820f39de2914fc_Path(_ember_29820f39de2914fc_observed).resolve() != _ember_29820f39de2914fc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py')
else:
    _ember_29820f39de2914fc_spec = _ember_29820f39de2914fc_importlib.spec_from_file_location('_ember_issue2015_29820f39de2914fc', _ember_29820f39de2914fc_path)
    if _ember_29820f39de2914fc_spec is None or _ember_29820f39de2914fc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py')
    _ember_29820f39de2914fc_module = _ember_29820f39de2914fc_importlib.module_from_spec(_ember_29820f39de2914fc_spec)
    for _ember_29820f39de2914fc_alias in _ember_29820f39de2914fc_aliases:
        _ember_29820f39de2914fc_prior = _ember_29820f39de2914fc_sys.modules.get(_ember_29820f39de2914fc_alias)
        if _ember_29820f39de2914fc_prior is not None and _ember_29820f39de2914fc_prior is not _ember_29820f39de2914fc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py')
        _ember_29820f39de2914fc_sys.modules[_ember_29820f39de2914fc_alias] = _ember_29820f39de2914fc_module
    try:
        _ember_29820f39de2914fc_spec.loader.exec_module(_ember_29820f39de2914fc_module)
    except BaseException:
        for _ember_29820f39de2914fc_alias in _ember_29820f39de2914fc_aliases:
            if _ember_29820f39de2914fc_sys.modules.get(_ember_29820f39de2914fc_alias) is _ember_29820f39de2914fc_module:
                _ember_29820f39de2914fc_sys.modules.pop(_ember_29820f39de2914fc_alias, None)
        raise
for _ember_29820f39de2914fc_alias in _ember_29820f39de2914fc_aliases:
    _ember_29820f39de2914fc_prior = _ember_29820f39de2914fc_sys.modules.get(_ember_29820f39de2914fc_alias)
    if _ember_29820f39de2914fc_prior is not None and _ember_29820f39de2914fc_prior is not _ember_29820f39de2914fc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py')
    _ember_29820f39de2914fc_sys.modules[_ember_29820f39de2914fc_alias] = _ember_29820f39de2914fc_module
_write_source_fixture = getattr(_ember_29820f39de2914fc_module, '_write_source_fixture')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/corpus_connectors/tests/test_pdf_to_utf8.py

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
