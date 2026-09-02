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
import issue1947_release_execute as execute  # noqa: E402
import issue1947_release_recompute as subject  # noqa: E402


def write_bundle(root: Path, *, score: float = 1.0) -> Path:
    bindings = []
    for index, row_id in enumerate(execute.ROWS):
        row = {"row_id": row_id, "items": [{"item_id": "one", "gold_item_sha256": "d" * 64, "prediction": "x", "score": score}]}
        row["self_sha256"] = execute.sha(execute.canonical(row))
        raw = json.dumps(row, sort_keys=True).encode()
        path = root / f"{row_id}.json"; path.write_bytes(raw)
        bindings.append({"row_id": row_id, "path": path.name, "bytes": len(raw), "raw_sha256": execute.sha(raw), "self_sha256": row["self_sha256"], "threshold": 0.5})
    bundle = {"schema_version": "ember-issue1947-redacted-release-bundle-v1", "result": "COMPLETE", "designation_manifest_raw_sha256": "a" * 64, "matrix_self_sha256": "b" * 64, "analysis_self_sha256": "c" * 64, "rows": bindings, "protected_bytes_present": False}
    bundle["self_sha256"] = execute.sha(execute.canonical(bundle))
    path = root / "release-bundle.json"; path.write_text(json.dumps(bundle), encoding="utf-8"); return path


def thresholds(value: float = 0.5) -> dict:
    return {row_id: value for row_id in execute.ROWS}


def test_independently_recomputes_all_rows_and_cert_predicates(tmp_path: Path) -> None:
    receipt = subject.recompute(write_bundle(tmp_path), thresholds())
    assert receipt["result"] == "PASS"
    assert receipt["cert_007_all_required_rows_pass"] is True
    assert receipt["cert_009_independent_raw_row_recomputation"] is True
    subject.verify_self(receipt, "receipt")


def test_negative_score_recomputes_fail_not_copied_pass(tmp_path: Path) -> None:
    receipt = subject.recompute(write_bundle(tmp_path, score=0.0), thresholds())
    assert receipt["result"] == "FAIL"
    assert receipt["cert_007_all_required_rows_pass"] is False


def test_missing_row_and_corrupt_raw_binding_refuse(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text()); bundle["rows"].pop(); bundle.pop("self_sha256"); bundle["self_sha256"] = execute.sha(execute.canonical(bundle)); bundle_path.write_text(json.dumps(bundle))
    with pytest.raises(subject.ReleaseRecomputeRefusal, match="MISSING_DUPLICATE_EXTRA_OR_REORDERED"):
        subject.recompute(bundle_path, thresholds())
    other = tmp_path / "other"; other.mkdir(); bundle_path = write_bundle(other); (other / f"{execute.ROWS[0]}.json").write_text("{}")
    with pytest.raises(subject.ReleaseRecomputeRefusal, match="RAW_ROW_BINDING_DRIFT"):
        subject.recompute(bundle_path, thresholds())


def test_protected_bytes_and_threshold_drift_refuse(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text()); bundle["gold_bytes"] = "secret"; bundle.pop("self_sha256"); bundle["self_sha256"] = execute.sha(execute.canonical(bundle)); bundle_path.write_text(json.dumps(bundle))
    with pytest.raises(execute.ReleaseExecutionRefusal, match="PROTECTED_BYTES_IN_BUNDLE"):
        subject.recompute(bundle_path, thresholds())
    clean = tmp_path / "clean"; clean.mkdir(); bundle_path = write_bundle(clean)
    with pytest.raises(subject.ReleaseRecomputeRefusal, match="THRESHOLD_ROW_SET_DRIFT"):
        subject.recompute(bundle_path, {execute.ROWS[0]: 0.5})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_thresholds_refuse(tmp_path: Path, value: float) -> None:
    bundle_path = write_bundle(tmp_path)
    with pytest.raises(subject.ReleaseRecomputeRefusal, match="THRESHOLD_NONFINITE"):
        subject.recompute(bundle_path, thresholds(value))


def test_non_finite_recomputed_mean_refuses(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path, score=float("nan"))
    with pytest.raises(execute.ReleaseExecutionRefusal, match="ITEM_SCORE_NONFINITE"):
        subject.recompute(bundle_path, thresholds())


@pytest.mark.parametrize(
    ("mutation", "refusal"),
    [
        ("schema", "BUNDLE_SCHEMA_DRIFT"),
        ("row_path", "ROW_PATH_DRIFT"),
        ("row_self", "ROW_SELF_HASH_BINDING_DRIFT"),
    ],
)
def test_bundle_schema_and_row_bindings_fail_closed(
    tmp_path: Path, mutation: str, refusal: str,
) -> None:
    bundle_path = write_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if mutation == "schema":
        bundle["schema_version"] = "wrong"
    elif mutation == "row_path":
        bundle["rows"][0]["path"] = "../outside.json"
    else:
        bundle["rows"][0]["self_sha256"] = "0" * 64
    bundle.pop("self_sha256")
    bundle["self_sha256"] = execute.sha(execute.canonical(bundle))
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(subject.ReleaseRecomputeRefusal, match=refusal):
        subject.recompute(bundle_path, thresholds())
