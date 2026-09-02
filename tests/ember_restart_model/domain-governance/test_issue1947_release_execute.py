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


def raw_spec(value: dict) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def preflight(value: dict) -> dict:
    return self_hashed({
        "schema_version": "ember-issue1947-release-tier-preflight-v1",
        "result": "PASS",
        "checkpoint_manifest": {"raw_sha256": "a" * 64},
        "matrix": {"self_sha256": "b" * 64},
        "analysis": {"self_sha256": "c" * 64},
        "tiers": [{
            "tier": "release",
            "execution_spec": {
                "raw_sha256": subject.sha(raw_spec(value)),
                "self_sha256": value["self_sha256"],
            },
        }],
    })


def spec(tmp_path: Path) -> dict:
    return self_hashed({
        "schema_version": "ember-issue1947-release-execution-spec-v1",
        "rows": [
        {"row_id": row_id, "command": ["fake", str(tmp_path / f"{index}.json"), row_id], "result_path": str(tmp_path / f"{index}.json"), "threshold": 0.5}
        for index, row_id in enumerate(subject.ROWS)
        ],
    })


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
    value = spec(tmp_path)
    bundle = subject.execute(
        value, preflight(value), tmp_path / "out",
        spec_raw_sha256=subject.sha(raw_spec(value)),
    )
    assert bundle["result"] == "COMPLETE"
    assert [row["row_id"] for row in bundle["rows"]] == list(subject.ROWS)
    assert bundle["protected_bytes_present"] is False
    subject.verify_self(json.loads((tmp_path / "out" / "release-bundle.json").read_text()), "bundle")


def test_missing_or_reordered_row_refuses_before_execution(tmp_path: Path) -> None:
    value = spec(tmp_path); value["rows"].reverse()
    value["self_sha256"] = subject.sha(
        subject.canonical({key: item for key, item in value.items() if key != "self_sha256"})
    )
    with pytest.raises(subject.ReleaseExecutionRefusal, match="MISSING_DUPLICATE_EXTRA_OR_REORDERED"):
        subject.execute(
            value, preflight(value), tmp_path / "out",
            spec_raw_sha256=subject.sha(raw_spec(value)),
        )


def test_protected_bytes_and_item_schema_refuse(tmp_path: Path) -> None:
    row = {"row_id": subject.ROWS[0], "items": [{"item_id": "one", "gold_item_sha256": "c" * 64, "prediction": "x", "score": 1.0, "gold_bytes": "secret"}]}
    with pytest.raises(subject.ReleaseExecutionRefusal, match="PROTECTED_BYTES_IN_BUNDLE|ITEM_SCHEMA_DRIFT"):
        subject.validate_row(row, subject.ROWS[0])


def test_preflight_self_hash_is_mandatory(tmp_path: Path) -> None:
    execution_spec = spec(tmp_path)
    value = preflight(execution_spec); value["self_sha256"] = "0" * 64
    with pytest.raises(subject.ReleaseExecutionRefusal, match="SELF_HASH_DRIFT"):
        subject.execute(
            execution_spec, value, tmp_path / "out",
            spec_raw_sha256=subject.sha(raw_spec(execution_spec)),
        )


def test_execution_spec_raw_and_self_identity_are_bound(tmp_path: Path) -> None:
    value = spec(tmp_path)
    authority = preflight(value)
    with pytest.raises(subject.ReleaseExecutionRefusal, match="EXECUTION_SPEC_RAW_HASH_DRIFT"):
        subject.execute(value, authority, tmp_path / "raw", spec_raw_sha256="0" * 64)
    value["rows"][0]["threshold"] = 0.75
    with pytest.raises(subject.ReleaseExecutionRefusal, match="SELF_HASH_DRIFT:execution_spec"):
        subject.execute(
            value, authority, tmp_path / "self",
            spec_raw_sha256=authority["tiers"][0]["execution_spec"]["raw_sha256"],
        )


@pytest.mark.parametrize(
    ("field", "value", "refusal"),
    [
        ("gold_item_sha256", "z" * 64, "GOLD_ITEM_HASH_DRIFT"),
        ("score", float("nan"), "ITEM_SCORE_NONFINITE"),
        ("score", float("inf"), "ITEM_SCORE_NONFINITE"),
    ],
)
def test_non_hex_identity_and_non_finite_scores_refuse(
    field: str, value: object, refusal: str,
) -> None:
    item = {
        "item_id": "one",
        "gold_item_sha256": "c" * 64,
        "prediction": "x",
        "score": 1.0,
    }
    item[field] = value
    row = {"row_id": subject.ROWS[0], "items": [item]}
    with pytest.raises(subject.ReleaseExecutionRefusal, match=refusal):
        subject.validate_row(row, subject.ROWS[0])


def test_non_finite_execution_threshold_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    value = spec(tmp_path)
    value["rows"][0]["threshold"] = float("inf")
    value["self_sha256"] = subject.sha(subject.canonical({k: v for k, v in value.items() if k != "self_sha256"}))
    with pytest.raises(subject.ReleaseExecutionRefusal, match="THRESHOLD_NONFINITE"):
        subject.execute(
            value, preflight(value), tmp_path / "out",
            spec_raw_sha256=subject.sha(raw_spec(value)),
        )


def test_all_result_paths_are_preflighted_before_any_execution(
    tmp_path: Path, monkeypatch,
) -> None:
    value = spec(tmp_path)
    Path(value["rows"][-1]["result_path"]).write_text("occupied", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )
    with pytest.raises(subject.ReleaseExecutionRefusal, match="ROW_RESULT_EXISTS_REFUSED"):
        subject.execute(
            value, preflight(value), tmp_path / "out",
            spec_raw_sha256=subject.sha(raw_spec(value)),
        )
    assert calls == []
    assert not (tmp_path / "out").exists()


def test_duplicate_result_path_and_invalid_json_refuse_by_name(
    tmp_path: Path, monkeypatch,
) -> None:
    value = spec(tmp_path)
    value["rows"][1]["result_path"] = value["rows"][0]["result_path"]
    value["self_sha256"] = subject.sha(
        subject.canonical({key: item for key, item in value.items() if key != "self_sha256"})
    )
    with pytest.raises(subject.ReleaseExecutionRefusal, match="DUPLICATE_ROW_RESULT_PATH"):
        subject.execute(
            value, preflight(value), tmp_path / "duplicate",
            spec_raw_sha256=subject.sha(raw_spec(value)),
        )

    value = spec(tmp_path / "invalid")
    def invalid_json(command, **_kwargs):
        class Completed:
            returncode = 0
        Path(command[1]).parent.mkdir(parents=True, exist_ok=True)
        Path(command[1]).write_text("not-json", encoding="utf-8")
        return Completed()
    monkeypatch.setattr(subject.subprocess, "run", invalid_json)
    with pytest.raises(subject.ReleaseExecutionRefusal, match="ROW_RESULT_INVALID_JSON"):
        subject.execute(
            value, preflight(value), tmp_path / "invalid-out",
            spec_raw_sha256=subject.sha(raw_spec(value)),
        )
