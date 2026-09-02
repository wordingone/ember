# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


TOTALITY_DIR = Path(__file__).resolve().parents[1] / "ember_totality"
sys.path.insert(0, str(TOTALITY_DIR))

from _lane14_common import check_path_sha_pairs  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_historical_placeholders_are_distinct_redaction_degradation(tmp_path):
    for placeholder in (
        "<local-path>",
        "<REDACTED_PATH>",
        "<REDACTED_GOALFORGE_PATH>\\receipts\\x.json",
        "<LOCAL-ABS-PATH>/receipts/x.json",
    ):
        ok, count, detail = check_path_sha_pairs(
            {
                "artifact_path": placeholder,
                "artifact_sha256": "0" * 64,
            },
            tmp_path,
        )
        assert ok is False
        assert count == 1
        assert detail.startswith("REDACTION_DEGRADED:")
        assert "AUDIT-PENDING" in detail
        assert "OFF-TREE/missing" not in detail


def test_closed_content_locator_resolves_and_hash_verifies(tmp_path):
    artifact = tmp_path / "receipts" / "trace.json"
    artifact.parent.mkdir()
    artifact.write_bytes(b'{"result":"PASS"}')
    digest = _sha(artifact.read_bytes())

    ok, count, detail = check_path_sha_pairs(
        {
            "artifact_locator": {
                "schema_version": "ember-content-locator-v1",
                "repo_relative_path": "receipts/trace.json",
                "sha256": digest,
            }
        },
        tmp_path,
    )
    assert ok is True
    assert count == 1
    assert "content locator" in detail


def test_content_locator_is_closed_and_fail_closed(tmp_path):
    artifact = tmp_path / "trace.json"
    artifact.write_bytes(b"real")
    base = {
        "schema_version": "ember-content-locator-v1",
        "repo_relative_path": "trace.json",
        "sha256": _sha(b"real"),
    }
    invalid = [
        {**base, "extra": "not-closed"},
        {**base, "repo_relative_path": str(artifact.resolve())},
        {**base, "repo_relative_path": "../trace.json"},
        {**base, "repo_relative_path": "./trace.json"},
        {**base, "sha256": "0" * 64},
        {
            "schema_version": "ember-content-locator-v1",
            "repo_relative_path": "trace.json",
        },
    ]
    for locator in invalid:
        ok, count, detail = check_path_sha_pairs(
            {"artifact_locator": locator},
            tmp_path,
        )
        assert ok is False
        assert count == 1
        assert detail


def test_generic_placeholder_is_not_new_content_identity(tmp_path):
    ok, count, detail = check_path_sha_pairs(
        {
            "artifact_locator": {
                "schema_version": "ember-content-locator-v1",
                "repo_relative_path": "<REDACTED_PATH>",
                "sha256": "0" * 64,
            }
        },
        tmp_path,
    )
    assert ok is False
    assert count == 1
    assert detail.startswith("REDACTION_DEGRADED:")


def test_host_absolute_path_pair_is_not_post_fix_evidence(tmp_path):
    artifact = tmp_path / "absolute.json"
    artifact.write_bytes(b"real")
    ok, count, detail = check_path_sha_pairs(
        {
            "artifact_path": str(artifact.resolve()),
            "artifact_sha256": _sha(b"real"),
        },
        tmp_path,
    )
    assert ok is False
    assert count == 1
    assert "content locator required" in detail
