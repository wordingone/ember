# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS))
PARTITION_TEST = ROOT / "tests" / "ember_restart_model" / "test_mint_github_license_partition.py"
ALLOWED = ["Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "MIT", "ODC-By-1.0", "PDDL-1.0"]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _partition_fixture(tmp_path: Path):
    spec = importlib.util.spec_from_file_location("partition_fixture_helpers", PARTITION_TEST)
    assert spec and spec.loader
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    connector, connector_sha = helpers._connector(tmp_path)
    output = tmp_path / "partition"
    receipt = helpers._mint(helpers._load(), connector, connector_sha, output)
    receipt_path = output / "partition-receipt.json"
    receipt_sha = _sha(receipt_path.read_bytes())
    row = {
        "source_id": "candidate-software_engineering-train-1",
        "domain": "software_engineering",
        "split": "train",
        "admission": "ADMITTED",
        "required_evidence": ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"],
        "allowed_license_spdx": ALLOWED,
        "content_sha256": receipt["partition_root_sha256"],
        "license_partition_receipt": "partition/partition-receipt.json",
        "license_partition_sha256": receipt_sha,
        "l4_receipt": {
            "schema_version": "ember-text-source-partition-receipt-v1",
            "result": "VERIFIED",
            "source_sha256": receipt["partition_root_sha256"],
            "generator": "github-license-partition-v1",
            "verifier": "github-license-partition-reopen-v1",
            "model_mediated": False,
            "borrowed_labels": False,
            "license_partition_sha256": receipt_sha,
        },
    }
    return row, output, receipt


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partition_authority_row_reopens_every_join_and_is_schema_disjoint(tmp_path: Path):
    import text_lab_corpus

    row, _, receipt = _partition_fixture(tmp_path)
    reopened = text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, row)
    assert reopened["partition_root_sha256"] == receipt["partition_root_sha256"]
    assert reopened["license_summary"] == ["Apache-2.0", "MIT"]
    assert "license_spdx" not in row
    assert "license_evidence" not in row

    for name in ("text-lab-corpus-v4.schema.json", "text-lab-bundle-v4.schema.json"):
        schema = json.loads((ROOT / "data" / "ember-restart-3b" / name).read_bytes())
        candidate_schema = dict(
            schema["properties"]["sources" if "corpus" in name else "candidates"]["items"],
            **{"$defs": schema["$defs"]},
        )
        assert not list(Draft202012Validator(candidate_schema).iter_errors(row))
        mixed = dict(row, license_spdx="MIT")
        assert list(Draft202012Validator(candidate_schema).iter_errors(mixed))


def _checked_in_partition_row(source_id: str) -> dict:
    corpus = json.loads((ROOT / "data" / "ember-restart-3b" / "owned-text-lab-corpus-v4.json").read_bytes())
    return next(row for row in corpus["sources"] if row["source_id"] == source_id)


@pytest.mark.parametrize(
    ("source_id", "recorded_sha"),
    [
        (
            "candidate-training_infrastructure-train-1",
            "0bb5319534d565aa01ed6d65437da3683004ffb84f6234c680e0e46e75661f6d",
        ),
        (
            "candidate-statistics-heldout-1",
            "baf5d76975bf5c7ccc7e34c40bd7c55b7968841c28f39655a147bb37cd753d4f",
        ),
    ],
)
def test_closed_v2_supersession_reopens_both_exact_reviewed_producer_classes(
    source_id: str, recorded_sha: str
):
    import text_lab_corpus

    row = _checked_in_partition_row(source_id)
    current_sha = _sha(
        (ROOT / "tools" / "ember-restart-3b" / "mint_github_license_partition.py").read_bytes()
    )
    allows_v2 = getattr(
        text_lab_corpus,
        "_partition_producer_supersession_allows_v2",
        lambda *_args: False,
    )

    assert allows_v2(ROOT, row, recorded_sha, current_sha)


def test_partition_authority_refuses_unlisted_historical_receipt(tmp_path: Path):
    import text_lab_corpus

    row, output, receipt = _partition_fixture(tmp_path)
    receipt["producer_sha256"] = "0bb5319534d565aa01ed6d65437da3683004ffb84f6234c680e0e46e75661f6d"
    receipt_path = output / "partition-receipt.json"
    receipt_path.write_bytes(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode())
    receipt_sha = _sha(receipt_path.read_bytes())
    row["license_partition_sha256"] = receipt_sha
    row["l4_receipt"]["license_partition_sha256"] = receipt_sha

    with pytest.raises(ValueError, match="partition receipt producer bytes changed"):
        text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, row)


def test_partition_authority_refuses_producer_sha_absent_from_closed_table(tmp_path: Path):
    import text_lab_corpus

    row, output, receipt = _partition_fixture(tmp_path)
    receipt["producer_sha256"] = "f" * 64
    receipt_path = output / "partition-receipt.json"
    receipt_path.write_bytes(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode())
    receipt_sha = _sha(receipt_path.read_bytes())
    row["license_partition_sha256"] = receipt_sha
    row["l4_receipt"]["license_partition_sha256"] = receipt_sha

    with pytest.raises(ValueError, match="partition receipt producer bytes changed"):
        text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, row)


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_successor",
        "missing_row",
        "extra_row",
        "swapped_path",
        "swapped_hash",
        "changed_recorded_producer",
        "broken_chain",
        "unreachable_cause",
        "unreachable_resolved",
        "extra_field",
    ],
)
def test_partition_authority_refuses_tampered_closed_v2_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
):
    import text_lab_corpus

    row = _checked_in_partition_row("candidate-training_infrastructure-train-1")
    recorded_sha = "0bb5319534d565aa01ed6d65437da3683004ffb84f6234c680e0e46e75661f6d"
    current_sha = _sha(
        (ROOT / "tools" / "ember-restart-3b" / "mint_github_license_partition.py").read_bytes()
    )
    table = json.loads(
        (ROOT / "data" / "ember-restart-3b" / "partition-producer-supersessions-v2.json").read_bytes()
    )
    binding_index = next(
        index
        for index, binding in enumerate(table["row_bindings"])
        if binding["source_id"] == row["source_id"]
    )
    other_index = 0 if binding_index != 0 else 1
    if mutation == "stale_successor":
        table["transitions"][1]["successor_sha256"] = "0" * 64
    elif mutation == "missing_row":
        table["row_bindings"].pop()
    elif mutation == "extra_row":
        extra = dict(table["row_bindings"][-1], source_id="candidate-unreviewed-train-0")
        table["row_bindings"].append(extra)
    elif mutation == "swapped_path":
        bound = table["row_bindings"][binding_index]
        other = table["row_bindings"][other_index]
        bound["license_partition_receipt"], other["license_partition_receipt"] = (
            table["row_bindings"][other_index]["license_partition_receipt"],
            table["row_bindings"][binding_index]["license_partition_receipt"],
        )
    elif mutation == "swapped_hash":
        bound = table["row_bindings"][binding_index]
        other = table["row_bindings"][other_index]
        bound["license_partition_sha256"], other["license_partition_sha256"] = (
            table["row_bindings"][other_index]["license_partition_sha256"],
            table["row_bindings"][binding_index]["license_partition_sha256"],
        )
    elif mutation == "changed_recorded_producer":
        table["row_bindings"][binding_index]["recorded_producer_sha256"] = "f" * 64
    elif mutation == "broken_chain":
        table["transitions"][0]["successor_sha256"] = "f" * 64
    elif mutation == "unreachable_cause":
        table["transitions"][1]["cause_commit"] = "0" * 40
    elif mutation == "unreachable_resolved":
        table["transitions"][0]["resolved_source_commits"] = [
            "0f06bc87ecf3c18774a2bf1aeed54f3d2c0f1044"
        ]
    else:
        table["unexpected"] = True
    stale_table = tmp_path / "tampered-partition-producer-supersessions-v2.json"
    stale_table.write_bytes(json.dumps(table, sort_keys=True, separators=(",", ":")).encode())
    real_path = text_lab_corpus._path

    def stale_table_path(root: Path, relative: object):
        if relative == text_lab_corpus._PARTITION_PRODUCER_SUPERSESSIONS_V2:
            return stale_table
        return real_path(root, relative)

    monkeypatch.setattr(text_lab_corpus, "_path", stale_table_path)
    allows_v2 = getattr(
        text_lab_corpus,
        "_partition_producer_supersession_allows_v2",
        lambda *_args: False,
    )
    assert not allows_v2(ROOT, row, recorded_sha, current_sha)


def test_partition_authority_refuses_digest_swap_and_blob_tamper(tmp_path: Path):
    import text_lab_corpus

    row, output, receipt = _partition_fixture(tmp_path)
    swapped = dict(row, license_partition_sha256="0" * 64)
    with pytest.raises(ValueError, match="partition receipt bytes"):
        text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, swapped)

    blob = output / receipt["repositories"][0]["files"][0]["blob_path"]
    blob.write_bytes(blob.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="partition receipt blob changed"):
        text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, row)


def test_partition_authority_refuses_synthetic_license_scalar(tmp_path: Path):
    import text_lab_corpus

    row, _, _ = _partition_fixture(tmp_path)
    row["license_spdx"] = "MIT"
    with pytest.raises(ValueError, match="partition authority row"):
        text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, row)


def test_partition_authority_refuses_cross_bound_row_and_connector_slot(tmp_path: Path):
    import text_lab_corpus

    row, output, _ = _partition_fixture(tmp_path)
    for field, value in (
        ("source_id", "candidate-software_engineering-train-0"),
        ("split", "heldout"),
        ("domain", "computer_science"),
    ):
        swapped = dict(row, **{field: value})
        with pytest.raises(ValueError, match="partition receipt identity"):
            text_lab_corpus._validate_partition_authority_row(ROOT, tmp_path, swapped)

    receipt_path = output / "partition-receipt.json"
    consumer = _load_script(
        "mint_issue1719_cross_binding_consumer",
        TOOLS / "mint_issue1719_tranche_admission.py",
    )
    unresolved = {
        key: row[key]
        for key in ("source_id", "domain", "split", "required_evidence", "allowed_license_spdx")
    }
    unresolved["admission"] = "UNRESOLVED_CANDIDATE"
    with pytest.raises(ValueError, match="connector slot"):
        consumer._apply_cases(
            module=text_lab_corpus,
            repo=ROOT,
            rows=[unresolved],
            cases=[{
                "source_id": unresolved["source_id"],
                "connector_slot": "F-train-2",
                "license_partition_receipt_path": str(receipt_path),
                "license_partition_receipt_sha256": _sha(receipt_path.read_bytes()),
            }],
            predecessor_row_receipts=[],
            predecessor_file_count=0,
            predecessor_total_bytes=0,
        )


def test_first_downstream_consumer_admits_partition_without_corpus_copy(tmp_path: Path):
    import text_lab_corpus

    _, output, receipt = _partition_fixture(tmp_path)
    receipt_path = output / "partition-receipt.json"
    consumer = _load_script(
        "mint_issue1719_partition_consumer",
        TOOLS / "mint_issue1719_tranche_admission.py",
    )
    unresolved = {
        "source_id": "candidate-software_engineering-train-1",
        "domain": "software_engineering",
        "split": "train",
        "admission": "UNRESOLVED_CANDIDATE",
        "required_evidence": ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"],
        "allowed_license_spdx": ALLOWED,
    }
    rows, row_receipts, file_count, byte_count = consumer._apply_cases(
        module=text_lab_corpus,
        repo=ROOT,
        rows=[unresolved],
        cases=[{
            "source_id": unresolved["source_id"],
            "connector_slot": "H-train-2",
            "license_partition_receipt_path": str(receipt_path),
            "license_partition_receipt_sha256": _sha(receipt_path.read_bytes()),
        }],
        predecessor_row_receipts=[],
        predecessor_file_count=0,
        predecessor_total_bytes=0,
    )

    admitted = rows[0]
    assert admitted["content_sha256"] == receipt["partition_root_sha256"]
    assert admitted["license_partition_receipt"] == str(receipt_path)
    assert "license_spdx" not in admitted
    assert "license_evidence" not in admitted
    assert row_receipts[0]["repository_count"] == 2
    assert file_count == receipt["file_count"]
    assert byte_count == receipt["blob_bytes"]


def test_partition_plan_mints_v4_packet_and_reopens_partial_authority(tmp_path: Path):
    partition_fixture = tmp_path / "partition-fixture"
    partition_fixture.mkdir()
    _, partition_output, partition = _partition_fixture(partition_fixture)
    partition_receipt = partition_output / "partition-receipt.json"
    predecessor_tests = _load_script(
        "issue1719_predecessor_fixture",
        ROOT / "tests" / "ember_restart_model" / "test_mint_issue1719_tranche_admission.py",
    )
    custody, predecessor_sha, _ = predecessor_tests._source_custody(tmp_path)
    plan = {
        "schema_version": "ember-issue1719-tranche-admission-plan-v1",
        "successor_id": "tranche4p",
        "cases": [{
            "source_id": "candidate-software_engineering-train-1",
            "connector_slot": "H-train-2",
            "license_partition_receipt_path": str(partition_receipt),
            "license_partition_receipt_sha256": _sha(partition_receipt.read_bytes()),
        }],
    }
    plan_raw = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    plan_path = tmp_path / "partition-plan.json"
    plan_path.write_bytes(plan_raw)
    output = tmp_path / "published"
    consumer = _load_script(
        "mint_issue1719_partition_successor",
        TOOLS / "mint_issue1719_tranche_admission.py",
    )

    result = consumer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=custody,
        predecessor_receipt_name="tranche3-admission-receipt.json",
        predecessor_receipt_sha256=predecessor_sha,
        plan_path=plan_path,
        plan_sha256=_sha(plan_raw),
        output=output,
    )

    assert result["validation_receipt"]["result"] == "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"
    assert (output / "text-lab-source-receipt-bundle-v4.json").is_file()
    assert (output / "owned-text-lab-corpus-v4.json").is_file()
    index = json.loads((output / "text-lab-authority-index-v2.json").read_bytes())
    assert index["receipt_bundle"]["schema"]["path"].endswith("text-lab-bundle-v4.schema.json")
    assert index["corpus"]["schema"]["path"].endswith("text-lab-corpus-v4.schema.json")
    row = next(
        item for item in json.loads((output / "owned-text-lab-corpus-v4.json").read_bytes())["sources"]
        if item["source_id"] == "candidate-software_engineering-train-1"
    )
    assert row["content_sha256"] == partition["partition_root_sha256"]
    assert "license_spdx" not in row

    second_plan = {
        "schema_version": "ember-issue1719-tranche-admission-plan-v1",
        "successor_id": "tranche4q",
        "cases": [],
    }
    second_plan_raw = json.dumps(second_plan, sort_keys=True, separators=(",", ":")).encode()
    second_plan_path = tmp_path / "second-plan.json"
    second_plan_path.write_bytes(second_plan_raw)
    second_output = tmp_path / "published-second"
    first_receipt = output / "tranche-admission-receipt.json"
    second = consumer.mint_successor(
        repo=ROOT,
        source_commit="4a9b874d8a7418265f0f727ccecae59cf1de70f4",
        source_custody=output,
        predecessor_receipt_name=first_receipt.name,
        predecessor_receipt_sha256=_sha(first_receipt.read_bytes()),
        plan_path=second_plan_path,
        plan_sha256=_sha(second_plan_raw),
        output=second_output,
    )
    assert second["validation_receipt"]["result"] == "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"
    assert (second_output / "text-lab-source-receipt-bundle-v4.json").is_file()
    assert (second_output / "owned-text-lab-corpus-v4.json").is_file()
