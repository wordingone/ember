# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
PRODUCER = ROOT / "tools" / "corpus_connectors" / "mint_connector_license_sidecar.py"
CC0_URL = "http://creativecommons.org/publicdomain/zero/1.0/"
CC0_URL_RECEIPT_NAME = "20260818T202142Z-paper-list-paper-list.txt-939-ids.json"
CC0_URL_RECEIPT_SHA256 = "402ebb06f9763c33ed34d8d5a3c1dae58fbeed56afb8ccea55de0f980ad45848"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return _sha(raw)


def _manifest(hashes: list[str]) -> str:
    return _sha("\n".join(sorted(hashes)).encode("utf-8"))


def _fixture(tmp_path: Path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    payloads = {"one.json": b'{"one": 1}\n', "nested/two.json": b'{"two": 2}\n'}
    for name, raw in payloads.items():
        (source / name).write_bytes(raw)
    files = [
        {"path": name, "bytes": len(raw), "sha256": _sha(raw)}
        for name, raw in payloads.items()
    ]
    original = {
        "schema": "corpus-connector-receipt-v1",
        "source": "mendeley",
        "source_id": "fixture-dataset-v3",
        "canonical_url": "https://example.test/dataset/3",
        "license": "CC-BY-4.0",
        "license_evidence": "dataset metadata declares CC-BY-4.0",
        "revision": "3",
        "files": files,
        "total_bytes": sum(row["bytes"] for row in files),
        "sha256_manifest": _manifest([row["sha256"] for row in files]),
        "fetched_at": "2026-08-15T00:00:00Z",
        "connector": {"name": "fixture_fetch", "version": "v1"},
        "l3_statement": "fetch-only; no external model authored/filtered/ranked/scored/selected any token",
        "dest_root": str(source),
        "notes": "original connector receipt",
    }
    original_path = tmp_path / "original.json"
    original_sha = _write(original_path, original)

    license_root = tmp_path / "license"
    license_root.mkdir()
    license_raw = b"Creative Commons Attribution 4.0 International\n"
    license_path = license_root / "file_downloaded"
    license_path.write_bytes(license_raw)
    license_receipt = {
        **original,
        "source": "http",
        "source_id": "https://example.test/LICENCE.md",
        "canonical_url": "https://example.test/LICENCE.md",
        "revision": None,
        "files": [{"path": license_path.name, "bytes": len(license_raw), "sha256": _sha(license_raw)}],
        "total_bytes": len(license_raw),
        "sha256_manifest": _manifest([_sha(license_raw)]),
        "connector": {"name": "http_fetch", "version": "v1"},
        "dest_root": str(license_root),
        "notes": "canonical API filename=LICENCE.md",
    }
    license_receipt_path = tmp_path / "license-receipt.json"
    license_receipt_sha = _write(license_receipt_path, license_receipt)
    return {
        "original_receipt_path": original_path,
        "original_receipt_sha256": original_sha,
        "license_receipt_path": license_receipt_path,
        "license_receipt_sha256": license_receipt_sha,
        "license_payload_path": license_path,
        "license_payload_sha256": _sha(license_raw),
        "expected_spdx": "CC-BY-4.0",
        "output": tmp_path / "derived",
    }


def _load_producer():
    spec = importlib.util.spec_from_file_location("mint_connector_license_sidecar", PRODUCER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rewrite_receipt(path: Path, receipt: dict) -> str:
    return _write(path, receipt)


def _set_license_identities(inputs: dict, *, original: str, artifact: str) -> None:
    original_receipt = json.loads(inputs["original_receipt_path"].read_bytes())
    original_receipt["license"] = original
    inputs["original_receipt_sha256"] = _rewrite_receipt(
        inputs["original_receipt_path"], original_receipt
    )
    license_receipt = json.loads(inputs["license_receipt_path"].read_bytes())
    license_receipt["license"] = artifact
    inputs["license_receipt_sha256"] = _rewrite_receipt(
        inputs["license_receipt_path"], license_receipt
    )


def _add_license_receipt_file(inputs: dict, *, name: str = "NOTICE", raw: bytes = b"notice\n") -> None:
    path = inputs["license_payload_path"].parent / name
    path.write_bytes(raw)
    receipt = json.loads(inputs["license_receipt_path"].read_bytes())
    receipt["files"].append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    receipt["total_bytes"] += len(raw)
    receipt["sha256_manifest"] = _manifest([row["sha256"] for row in receipt["files"]])
    inputs["license_receipt_sha256"] = _rewrite_receipt(inputs["license_receipt_path"], receipt)


def _expect_refusal(inputs: dict, match: str) -> None:
    producer = _load_producer()
    with pytest.raises(producer.LicenseSidecarRefusal, match=match):
        producer.mint_license_sidecar(**inputs)
    assert not inputs["output"].exists()


def test_mint_license_sidecar_discloses_both_predecessors_and_reopens_every_byte(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    result = _load_producer().mint_license_sidecar(**inputs)
    output = inputs["output"]
    derived = json.loads(Path(result["connector_receipt_path"]).read_bytes())
    derivation = json.loads(Path(result["derivation_receipt_path"]).read_bytes())

    assert derived["source"] == "derived_connector_custody"
    assert inputs["original_receipt_sha256"] in derived["notes"]
    assert inputs["license_receipt_sha256"] in derived["notes"]
    assert derivation["original_connector_receipt_sha256"] == inputs["original_receipt_sha256"]
    assert derivation["license_connector_receipt_sha256"] == inputs["license_receipt_sha256"]
    assert derivation["license_payload_sha256"] == inputs["license_payload_sha256"]
    assert (output / "LICENSE.md").read_bytes() == inputs["license_payload_path"].read_bytes()
    assert derived["total_bytes"] == sum(row["bytes"] for row in derived["files"])
    assert result["result"] == "VERIFIED"


@pytest.mark.parametrize("which", ["original_receipt_sha256", "license_receipt_sha256"])
def test_mint_license_sidecar_refuses_predecessor_receipt_hash_drift(tmp_path: Path, which: str) -> None:
    inputs = _fixture(tmp_path)
    inputs[which] = "0" * 64
    _expect_refusal(inputs, "receipt bytes changed")


@pytest.mark.parametrize("which", ["original", "license"])
def test_mint_license_sidecar_refuses_predecessor_payload_drift(tmp_path: Path, which: str) -> None:
    inputs = _fixture(tmp_path)
    if which == "original":
        Path(tmp_path / "source" / "one.json").write_bytes(b"tampered\n")
        match = "original connector receipt file bytes changed"
    else:
        inputs["license_payload_path"].write_bytes(b"tampered license\n")
        match = "license connector receipt file bytes changed"
    _expect_refusal(inputs, match)


def test_mint_license_sidecar_refuses_spdx_swap(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    inputs["expected_spdx"] = "MIT"
    _expect_refusal(inputs, "canonical license identities differ")


def test_mint_license_sidecar_canonicalizes_equivalent_raw_license_identities(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    original_raw = CC0_URL
    artifact_raw = "CC0-1.0"
    assert original_raw != artifact_raw
    assert CC0_URL_RECEIPT_NAME == "20260818T202142Z-paper-list-paper-list.txt-939-ids.json"
    assert len(CC0_URL_RECEIPT_SHA256) == 64
    _set_license_identities(inputs, original=original_raw, artifact=artifact_raw)
    inputs["expected_spdx"] = "CC0-1.0"

    result = _load_producer().mint_license_sidecar(**inputs)
    derived = json.loads(Path(result["connector_receipt_path"]).read_bytes())
    derivation = json.loads(Path(result["derivation_receipt_path"]).read_bytes())

    assert derived["license"] == "CC0-1.0"
    assert derivation["expected_spdx"] == "CC0-1.0"
    assert derivation["original_license_identity_raw"] == original_raw
    assert derivation["license_artifact_identity_raw"] == artifact_raw


def test_mint_license_sidecar_refuses_canonically_different_license_identities(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    _set_license_identities(
        inputs,
        original="CC-BY-4.0",
        artifact="CC0-1.0",
    )
    inputs["expected_spdx"] = "CC0-1.0"
    _expect_refusal(inputs, "canonical license identities differ")


def test_mint_license_sidecar_selects_explicit_payload_from_multifile_receipt(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    _add_license_receipt_file(inputs)

    result = _load_producer().mint_license_sidecar(**inputs)
    derivation = json.loads(Path(result["derivation_receipt_path"]).read_bytes())

    assert derivation["license_payload_source_path"] == str(inputs["license_payload_path"].resolve())
    assert derivation["license_payload_sha256"] == inputs["license_payload_sha256"]


def test_mint_license_sidecar_refuses_unbound_multifile_license_receipt(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    _add_license_receipt_file(inputs)
    inputs["license_payload_path"] = None
    inputs["license_payload_sha256"] = None
    _expect_refusal(inputs, "license payload binding is missing")


def test_mint_license_sidecar_refuses_wrong_payload_sha_in_multifile_receipt(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    _add_license_receipt_file(inputs)
    inputs["license_payload_sha256"] = "0" * 64
    _expect_refusal(inputs, "license payload identity differs")


def test_mint_license_sidecar_refuses_payload_absent_from_multifile_receipt(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    _add_license_receipt_file(inputs)
    absent = tmp_path / "absent-license"
    absent.write_bytes(inputs["license_payload_path"].read_bytes())
    inputs["license_payload_path"] = absent
    _expect_refusal(inputs, "license payload identity differs")


def test_text_lab_license_authority_refuses_unreceipted_url_alias() -> None:
    authority = _load_path(
        "text_lab_corpus_unreceipted_license_alias_test",
        ROOT / "tools" / "ember-restart-3b" / "text_lab_corpus.py",
    )
    with pytest.raises(ValueError, match="whole conjunction is not on the text-lab allow-list"):
        authority._closed_connector_license("http://creativecommons.org/licenses/by-nc/4.0/")


def test_mint_license_sidecar_refuses_traversal_even_when_receipt_is_rehashed(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    receipt = json.loads(inputs["original_receipt_path"].read_bytes())
    receipt["files"][0]["path"] = "../one.json"
    inputs["original_receipt_sha256"] = _rewrite_receipt(inputs["original_receipt_path"], receipt)
    _expect_refusal(inputs, "closed relative path")


def test_mint_license_sidecar_refuses_existing_license_artifact(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    receipt = json.loads(inputs["original_receipt_path"].read_bytes())
    raw = b"unbound competing license\n"
    path = tmp_path / "source" / "LICENSE.txt"
    path.write_bytes(raw)
    receipt["files"].append({"path": "LICENSE.txt", "bytes": len(raw), "sha256": _sha(raw)})
    receipt["total_bytes"] += len(raw)
    receipt["sha256_manifest"] = _manifest([row["sha256"] for row in receipt["files"]])
    inputs["original_receipt_sha256"] = _rewrite_receipt(inputs["original_receipt_path"], receipt)
    _expect_refusal(inputs, "already contains a LICENSE")


def test_mint_license_sidecar_refuses_output_collision(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    inputs["output"].mkdir()
    producer = _load_producer()
    with pytest.raises(producer.LicenseSidecarRefusal, match="output already exists"):
        producer.mint_license_sidecar(**inputs)


def test_mint_license_sidecar_excludes_top_level_connector_logs(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    log = json.loads(inputs["original_receipt_path"].read_bytes())["dest_root"]
    log_path = Path(log) / "_logs" / "arxiv-fetch.log"
    log_path.parent.mkdir()
    log_path.write_text("operational fetch log\n", encoding="utf-8")

    result = _load_producer().mint_license_sidecar(**inputs)

    assert Path(result["connector_receipt_path"]).is_file()


def test_mint_license_sidecar_still_refuses_arbitrary_unreceipted_data(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    source = Path(json.loads(inputs["original_receipt_path"].read_bytes())["dest_root"])
    (source / "unreceipted-extra.bin").write_bytes(b"extra\n")

    _expect_refusal(inputs, "custody file set differs from its receipt")


def test_derived_receipt_is_accepted_by_real_text_lab_adapter(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    result = _load_producer().mint_license_sidecar(**inputs)
    receipt = json.loads(Path(result["connector_receipt_path"]).read_bytes())
    adapter_path = ROOT / "tools" / "ember-restart-3b" / "text_lab_corpus.py"
    spec = importlib.util.spec_from_file_location("text_lab_corpus_license_sidecar_test", adapter_path)
    assert spec and spec.loader
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapted = adapter.adapt_connector_receipt(
        receipt,
        evidence={
            "kind": "spdx_repo_license",
            "license_sha256": inputs["license_payload_sha256"],
            "declared_spdx": "CC-BY-4.0",
        },
    )
    assert adapted["license_spdx"] == "CC-BY-4.0"
    assert adapted["l4_receipt"]["result"] == "VERIFIED"
    assert adapted["l4_receipt"]["source_sha256"] == adapted["content_sha256"]


def test_derived_receipt_survives_canonical_successor_mint_and_index_reopen(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path / "connector-fixture")
    result = _load_producer().mint_license_sidecar(**inputs)
    connector_path = Path(result["connector_receipt_path"])
    connector_sha = _sha(connector_path.read_bytes())

    fixture_module = _load_path(
        "issue1719_tranche_fixture_helpers",
        ROOT / "tests" / "ember_restart_model" / "test_mint_issue1719_tranche_admission.py",
    )
    minter = _load_path(
        "issue1719_tranche_minter_license_sidecar_test",
        ROOT / "tools" / "ember-restart-3b" / "mint_issue1719_tranche_admission.py",
    )
    authority = _load_path(
        "text_lab_corpus_license_sidecar_index_test",
        ROOT / "tools" / "ember-restart-3b" / "text_lab_corpus.py",
    )
    authority_fixture = tmp_path / "authority-fixture"
    authority_fixture.mkdir()
    custody, predecessor_sha, _ = fixture_module._source_custody(authority_fixture)
    plan = {
        "schema_version": "ember-issue1719-tranche-admission-plan-v1",
        "successor_id": "tranche7",
        "cases": [
            {
                "source_id": "candidate-mathematics-train-0",
                "connector_slot": "candidate-mathematics-train-0",
                "connector_receipt_path": str(connector_path),
                "connector_receipt_sha256": connector_sha,
                "expected_license_spdx": "CC-BY-4.0",
                "evidence": {
                    "kind": "spdx_repo_license",
                    "license_sha256": inputs["license_payload_sha256"],
                    "declared_spdx": "CC-BY-4.0",
                },
            }
        ],
    }
    plan_path = tmp_path / "tranche7-plan.json"
    plan_sha = _write(plan_path, plan)
    output = tmp_path / "tranche7"
    minted = minter.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=plan_path,
        plan_sha256=plan_sha,
        output=output,
    )
    reopened = authority.validate_authority_index(
        ROOT,
        index_relative="text-lab-authority-index-v2.json",
        external_authority_root=output,
    )
    assert reopened == minted["validation_receipt"]
    receipt = json.loads((output / "tranche-admission-receipt.json").read_bytes())
    assert receipt["admitted_row_count"] == 1
    assert receipt["row_receipts"][0]["connector_receipt_sha256"] == connector_sha
