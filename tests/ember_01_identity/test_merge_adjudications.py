from __future__ import annotations

# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import json

import pytest

from scripts.ember_01_identity.merge_adjudications import merge_adjudication_lanes


SOURCE_COMMIT = "a" * 40


def _bytes(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _consumer(path: str, digest: str) -> dict:
    return {
        "path": path,
        "category": "checkpoint_save_load",
        "evidence_sha256": digest,
        "current_input": "checkpoint bytes",
        "derived_label": "checkpoint restore",
        "protocol": "torch.load",
        "failure_behavior": "fails closed",
        "claim_effect": "selects restored state",
        "conflict": "path is not identity",
        "integration_requirement": "bind the exact checkpoint manifest",
    }


def test_merge_expands_legacy_collapsed_selectors_into_line_bound_rows() -> None:
    digest = "b" * 64
    content = "c" * 64
    helper_content = "d" * 64
    source = {
        "roots": [{"root_id": "public-master", "source_commit": SOURCE_COMMIT}],
        "evidence": [
            {"path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
             "line_sha256": digest, "content_sha256": content,
             "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE"},
            {"path": "runtime.py", "line": 3, "category": "checkpoint_save_load",
             "line_sha256": digest, "content_sha256": content,
             "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE"},
            {"path": "helper.py", "line": 0, "category": "unclassified_file",
             "content_sha256": helper_content, "evidence_scope": "FILE_CATEGORY",
             "source_role": "EXECUTABLE_CANDIDATE"},
        ],
    }
    consumer_scope = '{"path_prefix":"runtime"}'
    consumer_lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": {"path_prefix": "runtime"},
        "coverage": {},
        "consumer_rows": [_consumer("runtime.py", digest)],
        "nonconsumer_rows": [],
        "nonconsumer_files": [],
    }
    helper_lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": "helper",
        "coverage": {},
        "consumer_rows": [],
        "nonconsumer_rows": [],
        "nonconsumer_files": [{
            "path": "helper.py", "content_sha256": helper_content,
            "review_basis": "INSPECTED_NO_IDENTITY_OPERATION",
        }],
    }
    merged = merge_adjudication_lanes(
        [(consumer_scope, _bytes(consumer_lane)), ("helper", _bytes(helper_lane))], source
    )
    assert [row["line"] for row in merged["consumer_rows"]] == [1, 3]
    assert merged["coverage"] == {
        "source_executable_rows": 3,
        "reviewed_consumer_rows": 2,
        "reviewed_nonconsumer_rows": 1,
        "unresolved_executable_rows": 0,
        "duplicate_dispositions": 0,
    }
    assert merged["lanes"] == [
        {"scope": "helper", "sha256": hashlib.sha256(_bytes(helper_lane)).hexdigest()},
        {"scope": consumer_scope, "sha256": hashlib.sha256(_bytes(consumer_lane)).hexdigest()},
    ]


def test_merge_rejects_a_line_selector_absent_from_the_source() -> None:
    digest = "b" * 64
    source = {
        "roots": [{"root_id": "public-master", "source_commit": SOURCE_COMMIT}],
        "evidence": [{
            "path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
            "line_sha256": digest, "content_sha256": "c" * 64,
            "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE",
        }],
    }
    row = {**_consumer("runtime.py", digest), "line": 2}
    lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": "runtime",
        "coverage": {},
        "consumer_rows": [row], "nonconsumer_rows": [], "nonconsumer_files": [],
    }
    with pytest.raises(ValueError, match="absent from source"):
        merge_adjudication_lanes([("runtime", _bytes(lane))], source)


def test_merge_preserves_verified_consumer_and_drops_lane_nonconsumer_override() -> None:
    digest = "b" * 64
    source = {
        "roots": [{"root_id": "public-master", "source_commit": SOURCE_COMMIT}],
        "evidence": [{
            "path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
            "line_sha256": digest, "content_sha256": "c" * 64,
            "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE",
            "record_class": "VERIFIED_CONSUMER",
        }],
    }
    lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": "runtime",
        "coverage": {},
        "consumer_rows": [],
        "nonconsumer_rows": [{
            "path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
            "evidence_sha256": digest, "review_basis": "INCORRECT_LANE_OVERRIDE",
        }],
        "nonconsumer_files": [],
    }
    merged = merge_adjudication_lanes([("runtime", _bytes(lane))], source)
    assert merged["consumer_rows"] == []
    assert merged["nonconsumer_rows"] == []
    assert merged["coverage"]["reviewed_consumer_rows"] == 1
    assert merged["coverage"]["reviewed_nonconsumer_rows"] == 0
