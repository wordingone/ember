# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "governance" / "scripts"))
import issue1947_release_execute as subject  # noqa: E402


def self_hashed(value: dict) -> dict:
    value = dict(value); value["self_sha256"] = subject.sha(subject.canonical(value)); return value


def preflight() -> dict:
    return self_hashed({
        "schema_version": "ember-issue1947-release-tier-preflight-v1",
        "result": "PASS",
        "checkpoint_manifest": {"raw_sha256": "a" * 64},
        "matrix": {"self_sha256": "b" * 64},
        "analysis": {"self_sha256": "c" * 64},
    })


def spec(tmp_path: Path) -> dict:
    return {"rows": [
        {"row_id": row_id, "command": ["fake", str(tmp_path / f"{index}.json"), row_id], "result_path": str(tmp_path / f"{index}.json"), "threshold": 0.5}
        for index, row_id in enumerate(subject.ROWS)
    ]}


def fake_run(command, **_kwargs):
    class Completed:
        returncode = 0
    path, row_id = Path(command[1]), command[2]
    path.write_text(json.dumps({
        "row_id": row_id,
        "items": [{"item_id": "one", "gold_item_sha256": "b" * 64, "prediction": "x", "score": 1.0}],
    }), encoding="utf-8")
    return Completed()


def test_executes_exact_nine_rows_and_emits_redacted_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    bundle = subject.execute(spec(tmp_path), preflight(), tmp_path / "out")
    assert bundle["result"] == "COMPLETE"
    assert [row["row_id"] for row in bundle["rows"]] == list(subject.ROWS)
    assert bundle["protected_bytes_present"] is False
    subject.verify_self(json.loads((tmp_path / "out" / "release-bundle.json").read_text()), "bundle")


def test_missing_or_reordered_row_refuses_before_execution(tmp_path: Path) -> None:
    value = spec(tmp_path); value["rows"].reverse()
    with pytest.raises(subject.ReleaseExecutionRefusal, match="MISSING_DUPLICATE_EXTRA_OR_REORDERED"):
        subject.execute(value, preflight(), tmp_path / "out")


def test_protected_bytes_and_item_schema_refuse(tmp_path: Path) -> None:
    row = {"row_id": subject.ROWS[0], "items": [{"item_id": "one", "gold_item_sha256": "c" * 64, "prediction": "x", "score": 1.0, "gold_bytes": "secret"}]}
    with pytest.raises(subject.ReleaseExecutionRefusal, match="PROTECTED_BYTES_IN_BUNDLE|ITEM_SCHEMA_DRIFT"):
        subject.validate_row(row, subject.ROWS[0])


def test_preflight_self_hash_is_mandatory(tmp_path: Path) -> None:
    value = preflight(); value["self_sha256"] = "0" * 64
    with pytest.raises(subject.ReleaseExecutionRefusal, match="SELF_HASH_DRIFT"):
        subject.execute(spec(tmp_path), value, tmp_path / "out")
