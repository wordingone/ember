# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""What `cert_007_all_required_rows_pass` is allowed to count.

Today's release execution produced the first fully verifiable bundle for the nine protected rows and
showed what that bar currently measures. Six of the seven rows reporting a perfect score compute
`prediction = sha(admitted_asset.read_bytes())` and score `1.0 if prediction == gold`, where `gold`
is that same asset's recorded digest. Those comparisons cannot return anything but 1.0 unless the
file on disk is corrupt: they are asset-integrity checks wearing an evaluation row's schema, and
they were being counted toward a bar named "all required rows pass".

The cure derives each row's evidence kind from what its producer computes the prediction from, has
the bar read only checkpoint-derived rows, and fails when that set is empty rather than passing on
it. `all([])` is True, so the empty case is the one that has to be written down explicitly; without
it the corrected bar would still certify a matrix containing no model evidence at all.

Three properties are worth testing here, and none of them existed before:
  - a bar with no model-evidence row FAILS rather than passing vacuously,
  - the bar follows the model-evidence rows in both directions once one exists,
  - a bundle cannot promote its own row by writing a kind the producer table does not derive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src" / "ember" / "governance" / "scripts"))
import issue1947_release_execute as execute  # noqa: E402
import issue1947_release_recompute as subject  # noqa: E402


def write_bundle(root: Path, *, score: float = 1.0) -> Path:
    """A bundle whose row bindings carry the DERIVED kind, never a chosen one.

    The fixture derives the kind exactly the way the producer does. A fixture free to choose the
    kind would be testing a label rather than the property the label is supposed to stand for.
    """
    bindings = []
    for row_id in execute.ROWS:
        row = {
            "row_id": row_id,
            "items": [
                {"item_id": "one", "gold_item_sha256": "d" * 64, "prediction": "x", "score": score}
            ],
        }
        row["self_sha256"] = execute.sha(execute.canonical(row))
        raw = json.dumps(row, sort_keys=True).encode()
        path = root / f"{row_id}.json"
        path.write_bytes(raw)
        bindings.append(
            {
                "row_id": row_id,
                "path": path.name,
                "bytes": len(raw),
                "raw_sha256": execute.sha(raw),
                "self_sha256": row["self_sha256"],
                "threshold": 0.5,
                "evidence_kind": execute.evidence_kind(row_id),
            }
        )
    bundle = {
        "schema_version": "ember-issue1947-redacted-release-bundle-v1",
        "result": "COMPLETE",
        "designation_manifest_raw_sha256": "a" * 64,
        "matrix_self_sha256": "b" * 64,
        "analysis_self_sha256": "c" * 64,
        "rows": bindings,
        "protected_bytes_present": False,
    }
    bundle["self_sha256"] = execute.sha(execute.canonical(bundle))
    path = root / "release-bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def thresholds(value: float = 0.5) -> dict:
    return {row_id: value for row_id in execute.ROWS}


def test_every_current_row_derives_as_an_integrity_placeholder() -> None:
    """No row in the present matrix computes its prediction from an owned checkpoint."""
    kinds = {row_id: execute.evidence_kind(row_id) for row_id in execute.ROWS}
    assert set(kinds.values()) == {execute.INTEGRITY_PLACEHOLDER}


def test_an_unclassified_row_refuses_instead_of_defaulting() -> None:
    """A row nobody has classified is a row whose evidence nobody has examined.

    Defaulting it either way is a guess: to placeholder it silently drops real evidence, to model
    evidence it silently certifies an unexamined scorer. The refusal is the only honest branch.
    """
    with pytest.raises(execute.ReleaseExecutionRefusal, match="UNCLASSIFIED_PREDICTION_SOURCE"):
        execute.evidence_kind("E-MATRIX-NOT-A-ROW")


def test_all_placeholder_rows_scoring_one_do_not_satisfy_the_bar(tmp_path: Path) -> None:
    """The defect this change exists for, stated as a test.

    Every row scores 1.0 and none of them can fail. Before the derived evidence kind that produced
    cert_007 True. It has to produce False: a bar met by rows that cannot fail is met by nothing.
    """
    receipt = subject.recompute(write_bundle(tmp_path), thresholds())
    assert all(row["mean_score"] == 1.0 and row["passed"] for row in receipt["rows"])
    assert receipt["model_evidence_row_count"] == 0
    assert receipt["integrity_placeholder_row_count"] == len(execute.ROWS)
    assert receipt["integrity_placeholder_rows_pass"] is True
    assert receipt["cert_007_all_required_rows_pass"] is False
    assert receipt["result"] == "FAIL"


def test_the_bar_follows_the_model_evidence_rows_once_one_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One row promoted at the PRODUCER table, the only place a promotion is legitimate.

    The placeholders keep scoring 1.0 throughout, so if the bar moved with them it would not move
    here at all. It follows the single model-evidence row in both directions, which is what makes
    the count load-bearing rather than decorative.
    """
    monkeypatch.setitem(execute.PREDICTION_SOURCE, execute.ROWS[0], "owned_checkpoint_inference")

    passing = tmp_path / "passing"
    passing.mkdir()
    receipt = subject.recompute(write_bundle(passing), thresholds())
    assert receipt["model_evidence_row_count"] == 1
    assert receipt["integrity_placeholder_row_count"] == len(execute.ROWS) - 1
    assert receipt["cert_007_all_required_rows_pass"] is True

    failing = tmp_path / "failing"
    failing.mkdir()
    receipt = subject.recompute(write_bundle(failing, score=0.0), thresholds())
    assert receipt["model_evidence_row_count"] == 1
    assert receipt["cert_007_all_required_rows_pass"] is False


def test_a_bundle_cannot_promote_its_own_row(tmp_path: Path) -> None:
    """A kind written into a bundle is checked against the derivation, never trusted.

    Without this the cure would be defeatable by the artifact it certifies: a producer could emit
    MODEL_PREDICTION beside an integrity scorer and the bar would read the label, not the source.
    """
    bundle_path = write_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["rows"][0]["evidence_kind"] = execute.MODEL_PREDICTION
    bundle.pop("self_sha256")
    bundle["self_sha256"] = execute.sha(execute.canonical(bundle))
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(subject.ReleaseRecomputeRefusal, match="EVIDENCE_KIND_BINDING_DRIFT"):
        subject.recompute(bundle_path, thresholds())


def test_a_bundle_predating_the_cure_is_refused_rather_than_recertified(tmp_path: Path) -> None:
    """A binding with no kind at all is drift, not an implied placeholder.

    Bundles produced before this change carry no `evidence_kind`, and their recorded verdict was
    computed under the rule being replaced. Reading a missing field as "placeholder" would let an
    old bundle's cert_007 be silently recomputed under semantics it was never executed against.
    """
    bundle_path = write_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    for binding in bundle["rows"]:
        binding.pop("evidence_kind")
    bundle.pop("self_sha256")
    bundle["self_sha256"] = execute.sha(execute.canonical(bundle))
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(subject.ReleaseRecomputeRefusal, match="EVIDENCE_KIND_BINDING_DRIFT"):
        subject.recompute(bundle_path, thresholds())


def test_independent_recomputation_still_holds_for_every_row(tmp_path: Path) -> None:
    """The mechanism this change does not touch, asserted so a regression in it is visible here."""
    receipt = subject.recompute(write_bundle(tmp_path), thresholds())
    assert receipt["cert_009_independent_raw_row_recomputation"] is True
    assert [row["row_id"] for row in receipt["rows"]] == list(execute.ROWS)
    subject.verify_self(receipt, "receipt")
