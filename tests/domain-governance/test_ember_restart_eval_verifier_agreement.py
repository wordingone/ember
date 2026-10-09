# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The real scorer, the real trusted verifier and the real contract.py check agree (review 76202).

Each case runs the reasoning scorer as a hidden child, then contract.execute_evaluation_verifier,
which runs the pinned capability-evaluation verifier exactly as validate_manifest does and
compares every field it recomputes with the receipt.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "scripts" / "ember_restart_eval_reasoning_exact.py"
HELPER = ROOT / "scripts" / "ember_restart_eval_criterion.py"
VERIFIER = ROOT / "manifests" / "ember-02-admission" / "verifiers" / "capability-evaluation-verifier.py"
REGISTRY = ROOT / "manifests" / "ember-02-admission" / "trusted-verifiers-v1.json"
CRITERION = "ember-3b-reasoning-capability-v1"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = _module("ember_restart_contract_under_test", ROOT / "src/ember/governance/scripts/ember_restart/contract.py")
helper = _module("ember_restart_eval_criterion_under_test", HELPER)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pin(base: Path, name: str, value: float) -> dict:
    path = base / name
    path.write_text(json.dumps({"value": value}), encoding="utf-8")
    return {"path": name, "sha256": _sha(path)}


class Case:
    """One scored evaluation: protocol, evidence files, scorer output and the receipt contract.py reads."""

    def __init__(self, tmp: Path, answers: dict, categories: dict | None, criterion: dict):
        self.tmp = tmp
        refs = [{"id": k, "answer": "a", **({"category": categories[k]} if categories else {})} for k in answers]
        self.references = tmp / "references.jsonl"
        self.references.write_text("".join(json.dumps(r) + "\n" for r in refs), encoding="utf-8")
        self.scorer_predictions = tmp / "answers.jsonl"
        self.scorer_predictions.write_text(
            "".join(json.dumps({"id": k, "answer": v}) + "\n" for k, v in answers.items()), encoding="utf-8")
        self.frozen = tmp / "frozen.json"
        self.frozen.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "local-reasoning",
                                           "benchmark_version": "1", "references_sha256": _sha(self.references)}))
        self.protocol = tmp / "protocol.json"
        self.protocol.write_text(json.dumps({"criterion": criterion}), encoding="utf-8")
        # Canonical prediction envelope the verifier recounts (one row per scored item).
        self.predictions = tmp / "predictions.json"
        self.predictions.write_text(json.dumps({"rows": [{"id": k} for k in answers]}), encoding="utf-8")
        for name in ("checkpoint", "split", "harness", "inference"):
            (tmp / f"{name}.json").write_text(json.dumps({"artifact": name}), encoding="utf-8")
        self.score = tmp / "score.json"

    def run_scorer(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(SCORER), "--frozen-reasoning-manifest", str(self.frozen),
             "--references", str(self.references), "--predictions", str(self.scorer_predictions),
             "--score-output", str(self.score), "--protocol", str(self.protocol)],
            text=True, capture_output=True, timeout=60, creationflags=HIDDEN)

    def evidence(self) -> dict:
        return {"split": self.tmp / "split.json", "harness": self.tmp / "harness.json",
                "protocol": self.protocol, "inference_implementation": self.tmp / "inference.json",
                "predictions": self.predictions, "score_artifact": self.score}

    def receipt(self) -> dict:
        score = json.loads(self.score.read_text(encoding="utf-8"))
        receipt = {"capability": "reasoning", "result": "MEASURED",
                   "subject_checkpoint_sha256": _sha(self.tmp / "checkpoint.json"),
                   "benchmark_id": "local-reasoning", "benchmark_version": "1",
                   "sample_count": score["sample_count"], "metrics": score["metrics"],
                   "criterion_id": CRITERION, "criterion_statistic": score.get("criterion_statistic"),
                   "admission_margin": score.get("admission_margin"),
                   "criterion_result": score["criterion_result"]}
        for name, field in contract.EVALUATION_EVIDENCE.items():
            receipt[field] = _sha(self.evidence()[name])
        return receipt

    def contract_errors(self, receipt: dict | None = None) -> list[str]:
        return contract.execute_evaluation_verifier(
            ROOT, VERIFIER, "reasoning", self.tmp / "checkpoint.json", "local-reasoning", "1",
            CRITERION, self.evidence(), receipt if receipt is not None else self.receipt(), "evaluations[0]")


def _criterion(tmp: Path, reference: float, categories: list | None = None) -> dict:
    return {"criterion_id": CRITERION, "metric": "exact_match", "direction": "higher_is_better",
            "statistic": {"kind": "lower_confidence_bound", "level": 0.95, "method": "wilson_one_sided"},
            "comparator": {"kind": "max_of", "reference_factor": 0.8, "chance_factor": 2.0,
                           "reference": _pin(tmp, "reference.json", reference),
                           "chance": _pin(tmp, "chance.json", 0.05)},
            "categories": categories or []}


ALL_RIGHT = {f"r{i}": "a" for i in range(40)}
SEVEN_TENTHS = {f"r{i}": ("a" if i < 14 else "b") for i in range(20)}  # 0.7 of n=20


def test_verifier_pins_the_helper_bytes_and_the_registry_pins_the_verifier():
    source = VERIFIER.read_text(encoding="utf-8")
    assert f'CRITERION_HELPER_SHA256 = "{_sha(HELPER)}"' in source
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(v for v in registry["verifiers"] if v["path"].endswith("capability-evaluation-verifier.py"))
    assert entry["sha256"] == _sha(VERIFIER)


def test_positive_case_agrees_end_to_end(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    assert json.loads(case.score.read_text())["criterion_result"] == "PASSED"
    assert case.contract_errors() == []


def test_negative_margin_is_failed_by_scorer_and_verifier(tmp_path):
    # Review 76202 counterexample: 0.7 of 20, one-sided 95% Wilson lower bound 0.5162 < bar 0.6.
    case = Case(tmp_path, SEVEN_TENTHS, None, _criterion(tmp_path, reference=0.75))
    assert case.run_scorer().returncode == 0
    score = json.loads(case.score.read_text())
    assert score["criterion_result"] == "FAILED"
    assert score["admission_margin"] == pytest.approx(-0.0838037195924423)
    assert case.contract_errors() == []  # both say FAILED, so contract.py's PASSED gate refuses it


def test_legacy_min_value_in_the_protocol_is_refused_by_both(tmp_path):
    criterion = {**_criterion(tmp_path, reference=0.75), "min_value": 0.5}
    case = Case(tmp_path, SEVEN_TENTHS, None, criterion)
    result = case.run_scorer()
    assert result.returncode != 0 and "unknown field" in result.stderr
    case.protocol.write_text(json.dumps({"criterion": _criterion(tmp_path, reference=0.75)}), encoding="utf-8")
    assert case.run_scorer().returncode == 0
    case.protocol.write_text(json.dumps({"criterion": criterion}), encoding="utf-8")
    errors = case.contract_errors()
    assert any("exit code 1" in e for e in errors), errors


def test_tampered_margin_in_the_score_is_refused(tmp_path):
    case = Case(tmp_path, SEVEN_TENTHS, None, _criterion(tmp_path, reference=0.75))
    assert case.run_scorer().returncode == 0
    score = json.loads(case.score.read_text())
    score.update({"admission_margin": 0.01, "criterion_result": "PASSED"})
    case.score.write_text(json.dumps(score), encoding="utf-8")
    errors = case.contract_errors()
    assert any("exit code 1" in e for e in errors), errors


def test_tampered_margin_in_the_receipt_only_is_refused(tmp_path):
    case = Case(tmp_path, SEVEN_TENTHS, None, _criterion(tmp_path, reference=0.75))
    assert case.run_scorer().returncode == 0
    receipt = case.receipt()
    receipt["admission_margin"] = 0.01
    errors = case.contract_errors(receipt)
    assert errors == ["evaluations[0] receipt: verifier execution admission_margin mismatch"], errors


def test_tampered_reference_after_scoring_is_refused(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    (tmp_path / "reference.json").write_text(json.dumps({"value": 0.1}), encoding="utf-8")
    errors = case.contract_errors()
    assert any("exit code 1" in e for e in errors), errors


def test_wrong_population_is_refused(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    rows = [{"id": k} for k in ALL_RIGHT] + [{"id": "extra"}]
    case.predictions.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    errors = case.contract_errors()
    assert any("exit code 1" in e for e in errors), errors


def test_reasoning_categories_scorer_to_consumer_failing_category(tmp_path):
    # Composite 30/40 passes its bar; category "logic" (10/20) fails its own bar.
    answers = {f"r{i}": ("a" if i < 20 or i % 2 == 0 else "b") for i in range(40)}
    categories = {f"r{i}": ("arith" if i < 20 else "logic") for i in range(40)}
    cats = [{"name": n, "metric": f"exact_match:{n}", "count_metric": f"count:{n}",
             "reference": _pin(tmp_path, f"ref-{n}.json", 0.5), "reference_factor": 0.8} for n in ("arith", "logic")]
    case = Case(tmp_path, answers, categories, _criterion(tmp_path, reference=0.5, categories=cats))
    assert case.run_scorer().returncode == 0
    score = json.loads(case.score.read_text())
    assert score["metrics"]["count:arith"] == 20 and score["metrics"]["count:logic"] == 20
    assert score["composite_margin"] > 0 and score["category_margins"]["logic"] < 0
    assert score["criterion_result"] == "FAILED"
    assert case.contract_errors() == []


def test_reasoning_category_missing_from_the_population_is_undetermined(tmp_path):
    cats = [{"name": "geometry", "metric": "exact_match:geometry", "count_metric": "count:geometry",
             "reference": _pin(tmp_path, "ref-g.json", 0.5), "reference_factor": 0.8}]
    categories = {k: "arith" for k in ALL_RIGHT}
    case = Case(tmp_path, ALL_RIGHT, categories, _criterion(tmp_path, reference=0.5, categories=cats))
    assert case.run_scorer().returncode == 0
    assert json.loads(case.score.read_text())["criterion_result"] == "UNDETERMINED"
    assert case.contract_errors() == []


def test_reasoning_partial_category_membership_is_refused(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, {k: "arith" for k in ALL_RIGHT}, _criterion(tmp_path, reference=0.5))
    rows = [json.loads(x) for x in case.references.read_text().splitlines()]
    rows[0].pop("category")
    case.references.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    case.frozen.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "local-reasoning",
                                       "benchmark_version": "1", "references_sha256": _sha(case.references)}))
    result = case.run_scorer()
    assert result.returncode != 0 and "every reference row carries a category" in result.stderr


def test_lower_is_better_category_over_its_ceiling_fails(tmp_path):
    # Category WER 0.4 against a 0.2 ceiling must FAIL even when the composite is under its ceiling.
    criterion = {"criterion_id": "ember-3b-audio-capability-v1", "metric": "word_error_rate",
                 "direction": "lower_is_better", "statistic": {"kind": "point"},
                 "comparator": {"kind": "max_value", "value": 0.3},
                 "categories": [{"name": "noisy", "metric": "word_error_rate:noisy", "count_metric": "count:noisy",
                                 "reference": _pin(tmp_path, "ref-noisy.json", 0.2), "reference_factor": 1.0}]}
    helper.check_criterion(criterion, "ember-3b-audio-capability-v1")
    over = helper.admission({"word_error_rate": 0.25, "word_error_rate:noisy": 0.4, "count:noisy": 10},
                            30, criterion, tmp_path)
    assert over["criterion_result"] == "FAILED"
    assert over["category_margins"]["noisy"] == pytest.approx(-0.2)
    under = helper.admission({"word_error_rate": 0.25, "word_error_rate:noisy": 0.15, "count:noisy": 10},
                             30, criterion, tmp_path)
    assert under["criterion_result"] == "PASSED" and under["category_margins"]["noisy"] == pytest.approx(0.05)


@pytest.mark.parametrize("metric", sorted(helper.NON_BERNOULLI))
def test_audio_units_get_no_wilson_bound(tmp_path, metric):
    criterion = {"criterion_id": "ember-3b-audio-capability-v1", "metric": metric,
                 "direction": "higher_is_better",
                 "statistic": {"kind": "lower_confidence_bound", "level": 0.95, "method": "wilson_one_sided"},
                 "comparator": {"kind": "min_value", "value": 0.1}, "categories": []}
    helper.check_criterion(criterion, "ember-3b-audio-capability-v1")
    metrics = {"word_error_rate": 0.2, "weighted_recall": 0.9, "weighted_fpr": 0.1}
    result = helper.admission(metrics, 50, criterion, tmp_path)
    assert result["criterion_result"] == "UNDETERMINED" and result["admission_margin"] is None
