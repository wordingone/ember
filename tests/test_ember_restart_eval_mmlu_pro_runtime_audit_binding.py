# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.ember_restart_eval_mmlu_pro_runtime_audit import audit, digest




ROOT = Path(__file__).resolve().parents[1]


def test_mmlu_pro_custody_binds_repeatable_runtime_audit():
    manifest = json.loads(
        (ROOT / "manifests" / "ember-restart-mmlu-pro-custody-v1.json").read_text(
            encoding="utf-8"
        )
    )
    audit = manifest["runtime_audit"]
    assert audit == {
        "path": "scripts/ember_restart_eval_mmlu_pro_runtime_audit.py",
        "sha256": hashlib.sha256(
            (ROOT / "scripts" / "ember_restart_eval_mmlu_pro_runtime_audit.py").read_bytes()
        ).hexdigest(),
        "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE",
    }


def _runtime_fixture(protocol_sha256: str | None = None):
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.table(
            {
                "question_id": [7],
                "options": [["A", "B"]],
                "answer": ["A"],
                "answer_index": [0],
            }
        ),
        sink,
    )
    references = sink.getvalue().to_pybytes()
    split_sha256 = digest(references)
    scorer = b"frozen-mmlu-pro-scorer-v1\n"
    scorer_sha256 = digest(scorer)
    license_sha256 = "a" * 64
    custody = {
        "schema_version": "ember-restart-benchmark-custody-v1",
        "benchmark_id": "mmlu-pro",
        "benchmark_version": "fixture-v1",
        "target_execution_permitted": False,
        "target_training_access": "FORBIDDEN",
        "license_sha256": license_sha256,
        "scoring_adapter_sha256": scorer_sha256,
        "materialization": {
            "split_sha256": split_sha256,
            "artifact_sha256": "b" * 64,
        },
    }
    custody_bytes = json.dumps(custody, sort_keys=True, separators=(",", ":")).encode()
    expected = digest(f"mmlu-pro:fixture-v1:{split_sha256}:{license_sha256}:{scorer_sha256}".encode())
    protocol = {
        "scoring_adapter_sha256": scorer_sha256,
        "schema_version": "ember-restart-mmlu-pro-protocol-v1",
        "benchmark_id": "mmlu-pro",
        "benchmark_version": "fixture-v1",
        "custody_manifest_path": "manifests/ember-restart-mmlu-pro-custody-v1.json",
        "custody_manifest_sha256": digest(custody_bytes),
        "references_sha256": split_sha256,
        "license_sha256": license_sha256,
        "protocol_sha256": expected if protocol_sha256 is None else protocol_sha256,
    }
    protocol_bytes = json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    return custody_bytes, protocol_bytes, references, scorer, expected


def test_mmlu_pro_runtime_audit_derives_protocol_from_frozen_inputs():
    custody_bytes, protocol_bytes, references, scorer, expected = _runtime_fixture()
    payload = audit(
        custody_bytes=custody_bytes,
        protocol_bytes=protocol_bytes,
        reference_bytes=references,
        scorer_bytes=scorer,
        expected_scorer_bytes=scorer,
    )
    assert payload["protocol_sha256"] == expected


def test_mmlu_pro_runtime_audit_rejects_substituted_protocol_digest():
    custody_bytes, protocol_bytes, references, scorer, _ = _runtime_fixture("c" * 64)
    with pytest.raises(ValueError, match="derived"):
        audit(
            custody_bytes=custody_bytes,
            protocol_bytes=protocol_bytes,
            reference_bytes=references,
            scorer_bytes=scorer,
            expected_scorer_bytes=scorer,
        )
