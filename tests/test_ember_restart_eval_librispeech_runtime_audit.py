# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.ember_restart_eval_librispeech_runtime_audit import audit


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(protocol_sha256: str | None = None):
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([{"id": "utt-1", "text": "hello world"}]), sink)
    references = sink.getvalue().to_pybytes()
    split_sha = _digest(references)
    license_bytes = b"CC-BY-4.0\n"
    license_sha = _digest(license_bytes)
    scorer = b"audio wer scorer fixture\n"
    scorer_sha = _digest(scorer)
    version = "c" * 40
    custody = {
        "schema_version": "ember-restart-benchmark-custody-v1",
        "benchmark_id": "librispeech-clean-test",
        "target_execution_permitted": False,
        "target_training_access": "FORBIDDEN",
        "license_sha256": license_sha,
        "materialization": {"upstream_revision": version, "split_sha256": split_sha},
    }
    custody_bytes = json.dumps(custody, sort_keys=True, separators=(",", ":")).encode()
    expected = _digest(f"librispeech-clean-test:{version}:{split_sha}:{license_sha}:{scorer_sha}".encode())
    protocol = {
        "schema_version": "ember-restart-librispeech-clean-test-protocol-v1",
        "benchmark_id": "librispeech-clean-test",
        "benchmark_revision": version,
        "references_sha256": split_sha,
        "split_sha256": split_sha,
        "license_sha256": license_sha,
        "scoring_adapter": {"path": "scripts/ember_restart_eval_audio_wer.py", "sha256": scorer_sha},
        "protocol_sha256": expected if protocol_sha256 is None else protocol_sha256,
    }
    protocol_bytes = json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    return custody_bytes, protocol_bytes, references, license_bytes, scorer, expected


def test_librispeech_runtime_audit_derives_protocol_and_stays_preflight_only():
    custody, protocol, references, license_bytes, scorer, expected = _fixture()
    payload = audit(custody_bytes=custody, protocol_bytes=protocol, reference_bytes=references, license_bytes=license_bytes, scorer_bytes=scorer, expected_scorer_bytes=scorer)
    assert payload["result"] == "PREFLIGHT_ONLY"
    assert payload["target_execution_permitted"] is False
    assert payload["protocol_sha256"] == expected
    assert payload["sample_count"] == 1


def test_librispeech_runtime_audit_rejects_substituted_protocol_digest():
    custody, protocol, references, license_bytes, scorer, _ = _fixture("e" * 64)
    with pytest.raises(ValueError, match="derived"):
        audit(custody_bytes=custody, protocol_bytes=protocol, reference_bytes=references, license_bytes=license_bytes, scorer_bytes=scorer, expected_scorer_bytes=scorer)
