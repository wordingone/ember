# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 GAP-4: the research benchmark harness must validate the SUBJECT identity, fail-closed.

Drives the REAL production entry point --
``src.ember.governance.scripts.ember_research_benchmark_harness.build_admission_receipt`` (the exact callable
``main()``/the CLI wire into) -- with production-shaped inputs: a real benchmark
admission manifest + operator receipt (the same shape
``ember_research_benchmark_harness_selftest.py`` already exercises) plus a SUBJECT
identity manifest validated through the real
``ember_01_identity.validate_identity.validate_manifest`` with ``require_resolved=True``.

Positive: a valid, resolved OWNED_CANDIDATE subject manifest -> the admission receipt
carries ``subject_checkpoint_sha256`` equal to the manifest's own
``checkpoint.byte_sha256`` (never hand-typed).

Negative (three subject-identity failure shapes, each asserting the OBSERVABLE fail-closed
effect -- no admission receipt is written to disk, not merely that a helper returns
False):
  1. tampered subject manifest (checkpoint bytes changed post-signing so
     ``evaluation.subject_checkpoint_sha256`` no longer matches ``checkpoint.byte_sha256``)
  2. borrowed subject (an eval-result receipt signed for a DIFFERENT checkpoint than the
     subject manifest declares, routed through
     ``evaluation_identity_binding.bind_evaluation_identity``)
  3. absent subject manifest (path does not exist on disk)
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPTS_DIR = ROOT / "scripts"
IDENTITY_DIR = SCRIPTS_DIR / "ember_01_identity"
for _extra in (SCRIPTS_DIR, IDENTITY_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import ember_research_benchmark_harness as harness  # noqa: E402
from ember_research_benchmark_harness_selftest import (  # noqa: E402
    _SUBJECT_CHECKPOINT_SHA256,
    _SUBJECT_MANIFEST_PAYLOAD,
    _operator_receipt,
    _write,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _benchmark_manifest(root: Path) -> Path:
    """The real production benchmark-admission manifest shape (unchanged by GAP-4)."""
    evaluator = root / "eval.py"
    evaluator.write_text("print('ok')\n", encoding="utf-8")
    tasks = _write(
        root / "tasks.json",
        {
            "tasks": [
                {
                    "id": "sab-fixture-001",
                    "paper_source": "peer-reviewed-publication",
                    "heldout_input_sha256": "sha256:input",
                    "expected_output_sha256": "sha256:output",
                }
            ]
        },
    )
    return _write(
        root / "manifest.json",
        {
            "benchmark_id": "ScienceAgentBench",
            "family": "research_journal",
            "source_url": "https://arxiv.org/abs/2410.05080",
            "license_or_access_basis": "public research benchmark",
            "tasks_path": str(tasks),
            "evaluator_path": str(evaluator),
            "scoring_metric": "execution_accuracy",
            "heldout_frozen": True,
        },
    )


def test_valid_resolved_subject_admits_and_stamps_receipt() -> None:
    """POSITIVE: a valid resolved subject manifest -> receipt carries its checkpoint hash."""
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-subject-") as td:
        root = Path(td)
        manifest = _benchmark_manifest(root)
        subject_path = _write_json(root / "subject.json", _SUBJECT_MANIFEST_PAYLOAD)

        receipt = harness.build_admission_receipt(
            manifest, _operator_receipt(root), subject_path
        )

        assert receipt["verdict"] == "RESEARCH_BENCHMARK_ADMITTED"
        assert receipt["errors"] == []
        assert receipt["subject_checkpoint_sha256"] == _SUBJECT_MANIFEST_PAYLOAD["checkpoint"]["byte_sha256"]
        assert receipt["subject_checkpoint_sha256"] == _SUBJECT_CHECKPOINT_SHA256
        assert receipt["comparator_identity"] == _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["comparator_identity"]
        assert receipt["comparator_sha256"] == _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["comparator_sha256"]
        assert receipt["harness_sha256"]
        assert harness.validate_admission_receipt(receipt) == []


def test_tampered_subject_checkpoint_refuses_admission_no_receipt_written() -> None:
    """NEGATIVE 1: tampered subject (checkpoint bytes changed, subject hash now stale)."""
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-subject-") as td:
        root = Path(td)
        manifest = _benchmark_manifest(root)
        tampered = copy.deepcopy(_SUBJECT_MANIFEST_PAYLOAD)
        # Borrow-in-place: swap the checkpoint identity but leave the evaluation's
        # claimed subject pointing at the ORIGINAL (now-stale) checkpoint hash -- exactly
        # the laundering shape GAP-4 exists to block.
        tampered["checkpoint"]["byte_sha256"] = "8" * 64
        subject_path = _write_json(root / "subject-tampered.json", tampered)

        with pytest.raises(harness.SubjectIdentityRefused):
            harness.build_admission_receipt(manifest, _operator_receipt(root), subject_path)

        # Observable fail-closed effect: no admission receipt is ever written to disk.
        out_path = root / "admission-receipt.json"
        with pytest.raises(harness.SubjectIdentityRefused):
            harness.write_admission_receipt(
                out_path, manifest, _operator_receipt(root), subject_path
            )
        assert not out_path.exists()


def test_borrowed_subject_via_eval_receipt_refuses_binding() -> None:
    """NEGATIVE 2: an eval-result receipt signed for a DIFFERENT checkpoint (borrowed subject)."""
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-subject-") as td:
        root = Path(td)
        manifest = _benchmark_manifest(root)
        subject_path = _write_json(root / "subject.json", _SUBJECT_MANIFEST_PAYLOAD)

        borrowed_eval_receipt = {
            "evidence_class": "evaluation_result",
            "result": "VERIFIED",
            # Borrowed: this receipt's subject is a DIFFERENT checkpoint than the
            # subject manifest's own checkpoint.byte_sha256.
            "subject_checkpoint_sha256": "7" * 64,
            "benchmark_id": _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["benchmark_id"],
            "version": _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["version"],
            "split": _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["split"],
            "harness_sha256": _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["harness_sha256"],
            "comparator_identity": _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["comparator_identity"],
            "comparator_sha256": _SUBJECT_MANIFEST_PAYLOAD["evaluation"]["comparator_sha256"],
            "score": {"value": 1.0, "unit": "borrowed-score"},
            "uncertainty": {"value": 0.0, "unit": "borrowed-score"},
            "counts_toward_owned_completion": True,
        }
        eval_receipt_path = _write_json(root / "eval-result.json", borrowed_eval_receipt)

        with pytest.raises(harness.SubjectIdentityRefused):
            harness.build_admission_receipt(
                manifest, _operator_receipt(root), subject_path, eval_receipt_path
            )

        out_path = root / "admission-receipt.json"
        with pytest.raises(harness.SubjectIdentityRefused):
            harness.write_admission_receipt(
                out_path, manifest, _operator_receipt(root), subject_path, eval_receipt_path
            )
        assert not out_path.exists()


def test_absent_subject_manifest_refuses_admission_no_receipt_written() -> None:
    """NEGATIVE 3: subject manifest path does not exist on disk (absent subject)."""
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-subject-") as td:
        root = Path(td)
        manifest = _benchmark_manifest(root)
        missing_subject_path = root / "no-such-subject.json"

        with pytest.raises(harness.SubjectIdentityRefused):
            harness.build_admission_receipt(
                manifest, _operator_receipt(root), missing_subject_path
            )

        out_path = root / "admission-receipt.json"
        with pytest.raises(harness.SubjectIdentityRefused):
            harness.write_admission_receipt(
                out_path, manifest, _operator_receipt(root), missing_subject_path
            )
        assert not out_path.exists()
