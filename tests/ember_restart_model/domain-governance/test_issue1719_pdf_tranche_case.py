# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
MINTER = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "mint_issue1719_tranche_admission.py"
EXISTING_MINTER_TEST = (
    ROOT
    / "tests"
    / "ember_restart_model"
    / "domain-governance"
    / "test_mint_issue1719_tranche_admission.py"
)
TOOLS = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import text_lab_corpus  # noqa: E402


ALLOWED = ["Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "MIT", "ODC-By-1.0", "PDDL-1.0"]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_minter():
    spec = importlib.util.spec_from_file_location("pdf_tranche_minter", MINTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _AdapterBoundary:
    @staticmethod
    def _is_reparse_or_symlink(_path: Path) -> bool:
        return False

    @staticmethod
    def adapt_pdf_extraction_receipt(**_kwargs):
        transform = json.loads(Path(_kwargs["receipt_path"]).read_bytes())
        if transform.get("source_connector_sha256") != _kwargs["connector_receipt_sha256"]:
            raise ValueError("PDF transform and connector receipts are from different rows")
        content_sha256 = _sha(b"governed pdf text\n")
        evidence = _kwargs["evidence"]
        return {
            "content_sha256": content_sha256,
            "license_spdx": "CC-BY-4.0",
            "license_evidence": evidence,
            "l4_receipt": {
                "schema_version": "ember-text-source-receipt-v3",
                "result": "VERIFIED",
                "source_sha256": content_sha256,
                "generator": "pdf-text-extraction-v1",
                "verifier": "local-license-provenance-v1",
                "model_mediated": False,
                "borrowed_labels": False,
                "license_spdx": "CC-BY-4.0",
                "evidence_sha256": _sha(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()),
            },
        }


class _AuthorityProxy:
    adapt_pdf_extraction_receipt = staticmethod(_AdapterBoundary.adapt_pdf_extraction_receipt)

    def __getattr__(self, name: str):
        return getattr(text_lab_corpus, name)


def _pdf_case(tmp_path: Path, name: str = "one") -> tuple[dict, dict, dict]:
    root = tmp_path / name
    root.mkdir()
    connector_path = root / "connector.json"
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "source_id": f"fixture/{name}",
        "files": [{"path": "source.pdf", "bytes": 11, "sha256": _sha(b"source-pdf") }],
        "total_bytes": 11,
        "sha256_manifest": _sha(b"connector-manifest"),
    }
    connector_path.write_text(json.dumps(connector, sort_keys=True), encoding="utf-8")
    connector_sha = _sha(connector_path.read_bytes())
    transform_path = root / "pdf-text-extraction-receipt.json"
    transform = {
        "schema": "ember-pdf-text-extraction-receipt-v1",
        "result": "VERIFIED",
        "source_connector_sha256": connector_sha,
        "output": {"path": "document.txt", "bytes": 18, "sha256": _sha(b"governed pdf text\n"), "pages": 1, "decoded_content_bytes": 18},
    }
    transform["receipt_sha256"] = _sha(
        json.dumps(transform, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    transform_path.write_text(json.dumps(transform, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    transform_raw_sha = _sha(transform_path.read_bytes())
    evidence = {
        "kind": "publisher_terms",
        "terms_url": "https://example.test/terms",
        "declared_spdx": "CC-BY-4.0",
        "connector_receipt_path": str(connector_path.resolve()),
        "connector_receipt_sha256": connector_sha,
        "transform_receipt_path": str(transform_path.resolve()),
        "transform_receipt_sha256": transform["receipt_sha256"],
    }
    old_row = {
        "source_id": "candidate-physics-heldout-0",
        "domain": "physics",
        "split": "heldout",
        "admission": "UNRESOLVED_CANDIDATE",
        "required_evidence": ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"],
        "allowed_license_spdx": ALLOWED,
    }
    case = {
        "source_id": old_row["source_id"],
        "connector_slot": "C-heldout-1",
        "connector_receipt_path": str(connector_path),
        "connector_receipt_sha256": connector_sha,
        "transform_receipt_path": str(transform_path),
        "transform_receipt_raw_sha256": transform_raw_sha,
        "transform_receipt_sha256": transform["receipt_sha256"],
        "expected_license_spdx": "CC-BY-4.0",
        "evidence": evidence,
    }
    return old_row, case, transform


def _apply(tmp_path: Path, case: dict, old_row: dict | None = None):
    if old_row is None:
        old_row, _, _ = _pdf_case(tmp_path, "default-row")
    return _load_minter()._apply_cases(
        module=_AdapterBoundary,
        repo=ROOT,
        rows=[old_row],
        cases=[case],
        predecessor_row_receipts=[],
        predecessor_file_count=0,
        predecessor_total_bytes=0,
    )


def test_pdf_case_binds_connector_and_transform_receipts_before_admission(tmp_path: Path) -> None:
    old_row, case, transform = _pdf_case(tmp_path)
    rows, receipts, file_count, byte_count = _load_minter()._apply_cases(
        module=_AdapterBoundary,
        repo=ROOT,
        rows=[old_row],
        cases=[case],
        predecessor_row_receipts=[],
        predecessor_file_count=0,
        predecessor_total_bytes=0,
    )
    assert rows[0]["admission"] == "ADMITTED"
    assert rows[0]["content_sha256"] == transform["output"]["sha256"]
    assert receipts[0]["connector_receipt_sha256"] == case["connector_receipt_sha256"]
    assert receipts[0]["transform_receipt_raw_sha256"] == case["transform_receipt_raw_sha256"]
    assert receipts[0]["transform_receipt_sha256"] == transform["receipt_sha256"]
    assert file_count == 1
    assert byte_count == 18


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("connector-sha", "connector receipt bytes changed"),
        ("transform-raw-sha", "PDF transform receipt bytes changed"),
        ("transform-self-sha", "PDF transform receipt identity changed"),
        ("evidence-extra", "PDF evidence hashes do not match"),
        ("license", "PDF source license does not match"),
    ],
)
def test_pdf_case_refuses_independent_binding_changes(
    tmp_path: Path, mutation: str, message: str,
) -> None:
    old_row, case, _ = _pdf_case(tmp_path)
    if mutation == "connector-sha":
        case["connector_receipt_sha256"] = "a" * 64
    elif mutation == "transform-raw-sha":
        case["transform_receipt_raw_sha256"] = "b" * 64
    elif mutation == "transform-self-sha":
        case["transform_receipt_sha256"] = "c" * 64
        case["evidence"]["transform_receipt_sha256"] = "c" * 64
    elif mutation == "evidence-extra":
        case["evidence"]["unbound_note"] = "not allowed"
    else:
        case["expected_license_spdx"] = "MIT"
    with pytest.raises(ValueError, match=message):
        _apply(tmp_path, case, old_row)


def test_pdf_case_refuses_connector_and_transform_from_different_rows(tmp_path: Path) -> None:
    old_row, case, _ = _pdf_case(tmp_path, "first")
    _, other, other_transform = _pdf_case(tmp_path, "second")
    case["transform_receipt_path"] = other["transform_receipt_path"]
    case["transform_receipt_raw_sha256"] = other["transform_receipt_raw_sha256"]
    case["transform_receipt_sha256"] = other["transform_receipt_sha256"]
    case["evidence"]["transform_receipt_path"] = str(Path(other["transform_receipt_path"]).resolve())
    case["evidence"]["transform_receipt_sha256"] = other_transform["receipt_sha256"]
    with pytest.raises(ValueError, match="different rows"):
        _apply(tmp_path, case, old_row)


def _load_existing_minter_test():
    spec = importlib.util.spec_from_file_location("existing_minter_test", EXISTING_MINTER_TEST)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_validator_accepts_minted_pdf_case(tmp_path: Path, monkeypatch) -> None:
    producer = _load_minter()
    fixture = _load_existing_minter_test()
    custody, predecessor_sha, _ = fixture._source_custody(tmp_path)
    old_row, case, _ = _pdf_case(tmp_path, "pdf")
    plan_path = tmp_path / "plan.json"
    plan = {
        "schema_version": "ember-issue1719-tranche-admission-plan-v1",
        "successor_id": "tranche6",
        "cases": [case],
    }
    plan_raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    plan_path.write_bytes(plan_raw)
    monkeypatch.setattr(producer, "load_authority_module", lambda _repo: _AuthorityProxy())

    output = tmp_path / "published"
    result = producer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=plan_path,
        plan_sha256=_sha(plan_raw),
        output=output,
    )
    reopened = text_lab_corpus.validate_authority_index(
        ROOT,
        index_relative="text-lab-authority-index-v2.json",
        external_authority_root=output,
    )
    rows = json.loads((output / "owned-text-lab-corpus-v3.json").read_bytes())["sources"]
    admitted = next(row for row in rows if row["source_id"] == old_row["source_id"])
    assert admitted["admission"] == "ADMITTED"
    assert reopened == result["validation_receipt"]
