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


def _row(row_id: str, answer: str) -> dict:
    return {"id": row_id, "output": {"kind": "text", "text": answer}}


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
        # Canonical prediction rows the verifier recounts and re-scores (one row per scored item).
        self.predictions = tmp / "predictions.json"
        self.predictions.write_text(json.dumps({"rows": [_row(k, v) for k, v in answers.items()]}), encoding="utf-8")
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
                "predictions": self.predictions, "score_artifact": self.score, "references": self.references}

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

    def run_verifier(self, benchmark_id: str = "local-reasoning") -> subprocess.CompletedProcess:
        command = [sys.executable, "-I", str(VERIFIER), "--capability", "reasoning",
                   "--checkpoint-manifest", str(self.tmp / "checkpoint.json"), "--benchmark-id", benchmark_id,
                   "--benchmark-version", "1", "--criterion-id", CRITERION]
        for name, path in self.evidence().items():
            command += [f"--{name.replace('_', '-')}", str(path)]
        return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60, creationflags=HIDDEN)

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
    rows = [_row(k, "a") for k in ALL_RIGHT] + [_row("extra", "a")]
    case.predictions.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    errors = case.contract_errors()
    assert any("exit code 1" in e for e in errors), errors


def test_verifier_rescores_and_marks_the_metrics_rescored(tmp_path):
    case = Case(tmp_path, SEVEN_TENTHS, None, _criterion(tmp_path, reference=0.75))
    assert case.run_scorer().returncode == 0
    result = case.run_verifier()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["metric_verification"] == "RESCORED"


def test_one_flipped_predicted_answer_is_refused_by_the_rescore(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    rows = [_row(k, "a") for k in ALL_RIGHT]
    rows[0] = _row("r0", "b")
    case.predictions.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    result = case.run_verifier()
    assert result.returncode == 1 and "re-score" in result.stderr, result.stderr
    assert any("exit code 1" in e for e in case.contract_errors())


def test_a_swapped_id_at_the_same_count_is_refused(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    rows = [_row(k, "a") for k in ALL_RIGHT]
    rows[0] = _row("not-a-reference-id", "a")
    case.predictions.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    result = case.run_verifier()
    assert result.returncode == 1 and "exactly cover the frozen reference ids" in result.stderr, result.stderr


def test_a_tampered_metric_the_adjudication_ignores_is_refused_by_the_rescore(tmp_path):
    # An extra category count changes no verdict field, so only the re-score can see it.
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    score = json.loads(case.score.read_text())
    score["metrics"]["count:arith"] = 40
    case.score.write_text(json.dumps(score), encoding="utf-8")
    result = case.run_verifier()
    assert result.returncode == 1 and "re-score" in result.stderr, result.stderr


def test_references_changed_after_scoring_are_refused(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    case.references.write_text("".join(json.dumps({"id": k, "answer": "a "}) + "\n" for k in ALL_RIGHT),
                               encoding="utf-8")
    result = case.run_verifier()
    assert result.returncode == 1 and "references_sha256" in result.stderr, result.stderr


def test_a_benchmark_without_a_rescore_is_reported_unverified_and_never_admitted(tmp_path):
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    score = json.loads(case.score.read_text())
    score["benchmark_id"] = "remote-benchmark"
    case.score.write_text(json.dumps(score), encoding="utf-8")
    result = case.run_verifier(benchmark_id="remote-benchmark")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["metric_verification"] == "METRIC_REPORTED_UNVERIFIED"
    receipt = {**case.receipt(), "benchmark_id": "remote-benchmark"}
    errors = contract.execute_evaluation_verifier(
        ROOT, VERIFIER, "reasoning", tmp_path / "checkpoint.json", "remote-benchmark", "1",
        CRITERION, case.evidence(), receipt, "evaluations[0]")
    assert errors == ["evaluations[0] receipt: metrics are METRIC_REPORTED_UNVERIFIED (not re-scored by the verifier)"]


def test_an_unrescored_criterion_metric_is_never_admitted_even_when_exact_match_rescores(tmp_path):
    # Review 76764 R1: reference 'a', prediction 'b' (honest exact_match 0) plus an unrescored
    # reported_accuracy 1 that the criterion reads. It must not PASS as RESCORED.
    answers = {f"r{i}": "b" for i in range(40)}
    case = Case(tmp_path, answers, None, _criterion(tmp_path, reference=0.5))
    assert case.run_scorer().returncode == 0
    criterion = {**_criterion(tmp_path, reference=0.5), "metric": "reported_accuracy"}
    case.protocol.write_text(json.dumps({"criterion": criterion}), encoding="utf-8")
    score = json.loads(case.score.read_text())
    assert score["metrics"]["exact_match"] == 0
    score["metrics"]["reported_accuracy"] = 1.0
    score["protocol_sha256"] = _sha(case.protocol)
    checked = helper.check_criterion(criterion, CRITERION)
    verdict = helper.admission(score["metrics"], score["sample_count"], checked, case.protocol.parent)
    assert verdict["criterion_result"] == "PASSED"  # the reported metric alone would pass
    score.update({field: verdict[field] for field in ("criterion_statistic", "admission_margin", "criterion_result")})
    case.score.write_text(json.dumps(score), encoding="utf-8")
    result = case.run_verifier()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["metric_verification"] == "METRIC_REPORTED_UNVERIFIED"
    assert case.contract_errors() == [
        "evaluations[0] receipt: metrics are METRIC_REPORTED_UNVERIFIED (not re-scored by the verifier)"]


TEXT_SCORER = ROOT / "scripts" / "ember_restart_eval_text_exact.py"
TEXT_CRITERION = "ember-3b-text-capability-v1"


def _text_case(tmp: Path) -> tuple[dict, list[str]]:
    """The real local-text scorer's output, and the verifier command for it (review 76764 R2)."""
    answers = {f"t{i}": "yes" for i in range(40)}
    references = tmp / "references.jsonl"
    references.write_text("".join(json.dumps({"id": k, "answer": "yes"}) + "\n" for k in answers), encoding="utf-8")
    manifest = tmp / "frozen-text.json"
    manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "local-text", "benchmark_version": "1",
                                    "references_sha256": _sha(references), "checkpoint_manifest_sha256": "a" * 64,
                                    "model_config_sha256": "b" * 64, "split_sha256": "e" * 64,
                                    "protocol_sha256": "f" * 64}), encoding="utf-8")
    predictions = tmp / "predictions.json"
    predictions.write_text(json.dumps({
        "schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {"id": "local-text", "version": "1", "capability": "text", "split_sha256": "e" * 64,
                      "protocol_sha256": "f" * 64},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1,
                     "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": k, "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos",
                  "output": {"kind": "text", "text": v}} for k, v in answers.items()]}), encoding="utf-8")
    protocol = tmp / "protocol.json"
    protocol.write_text(json.dumps({"criterion": {**_criterion(tmp, reference=0.5), "criterion_id": TEXT_CRITERION}}),
                        encoding="utf-8")
    score = tmp / "score.json"
    produced = subprocess.run(
        [sys.executable, "-B", str(TEXT_SCORER), "--frozen-text-manifest", str(manifest), "--references",
         str(references), "--predictions", str(predictions), "--score-output", str(score), "--protocol", str(protocol)],
        text=True, capture_output=True, timeout=60, creationflags=HIDDEN)
    assert produced.returncode == 0, produced.stderr
    for name in ("checkpoint", "split", "harness", "inference"):
        (tmp / f"{name}.json").write_text(json.dumps({"artifact": name}), encoding="utf-8")
    command = [sys.executable, "-I", str(VERIFIER), "--capability", "text",
               "--checkpoint-manifest", str(tmp / "checkpoint.json"), "--benchmark-id", "local-text",
               "--benchmark-version", "1", "--criterion-id", TEXT_CRITERION, "--split", str(tmp / "split.json"),
               "--harness", str(tmp / "harness.json"), "--protocol", str(protocol),
               "--inference-implementation", str(tmp / "inference.json"), "--predictions", str(predictions),
               "--score-artifact", str(score), "--references", str(references)]
    return json.loads(score.read_text(encoding="utf-8")), command


def test_text_scorer_output_is_rescored_by_the_verifier(tmp_path):
    score, command = _text_case(tmp_path)
    assert (score["benchmark_id"], score["benchmark_version"]) == ("local-text", "1")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60, creationflags=HIDDEN)
    assert result.returncode == 0, result.stderr
    attestation = json.loads(result.stdout)
    assert attestation["metric_verification"] == "RESCORED" and attestation["criterion_result"] == "PASSED"


def test_text_scorer_output_for_another_benchmark_version_is_refused(tmp_path):
    _, command = _text_case(tmp_path)
    command[command.index("--benchmark-version") + 1] = "2"
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60, creationflags=HIDDEN)
    assert result.returncode == 1 and "benchmark_version mismatch" in result.stderr, result.stderr


CUSTODY_EVIDENCE = {"upstream_tree_git_sha1": "1" * 40, "license_sha256": "2" * 64,
                    "answer_dictionary_sha256": "3" * 64, "eligible_id_set_sha256": "4" * 64,
                    "evaluator_sha256": "5" * 64}


def _custody_root(tmp: Path, benchmarks: dict[str, str]) -> Path:
    """A root carrying the shared protected registry and one custody manifest per benchmark,
    in the exact shape the train-side screen (text_lab_corpus._protected_identifier_sets) validates."""
    root = tmp / "custody-root"
    entries = []
    for benchmark_id, digest in benchmarks.items():
        manifest = root / "custody" / f"{benchmark_id}.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({
            "benchmark_id": benchmark_id, "upstream_tree_git_sha1": CUSTODY_EVIDENCE["upstream_tree_git_sha1"],
            "license_sha256": CUSTODY_EVIDENCE["license_sha256"],
            "split": {"answer_dictionary_sha256": CUSTODY_EVIDENCE["answer_dictionary_sha256"],
                      "eligible_id_set_sha256": CUSTODY_EVIDENCE["eligible_id_set_sha256"]},
            "evaluator": {"sha256": CUSTODY_EVIDENCE["evaluator_sha256"]}}), encoding="utf-8")
        entries.append({"benchmark_id": benchmark_id, "custody_manifest_path": f"custody/{benchmark_id}.json",
                        "custody_manifest_sha256": _sha(manifest), "custody_state": "protected",
                        "evidence": dict(CUSTODY_EVIDENCE),
                        "protected_identifiers": [{"kind": "content_sha256", "value": digest}]})
    registry = root / contract.PROTECTED_EVAL_REGISTRY
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"schema_version": contract.PROTECTED_EVAL_REGISTRY_SCHEMA, "protected": entries}),
                        encoding="utf-8")
    return root


def test_references_must_be_a_protected_identifier_of_their_benchmark_in_the_validated_registry(tmp_path):
    digest, other = "a" * 64, "b" * 64
    # The real registry does not list these bytes: refused.
    assert contract.protected_reference_errors(ROOT, digest, "local-reasoning", "e") == [
        "e receipt: references are not a protected identifier of benchmark local-reasoning"]
    root = _custody_root(tmp_path, {"local-reasoning": digest, "local-text": other})
    assert contract.protected_reference_errors(root, digest, "local-reasoning", "e") == []


def test_references_missing_from_the_registry_are_refused(tmp_path):
    root = _custody_root(tmp_path, {"local-reasoning": "b" * 64})
    assert contract.protected_reference_errors(root, "a" * 64, "local-reasoning", "e") == [
        "e receipt: references are not a protected identifier of benchmark local-reasoning"]


def test_references_registered_under_another_benchmark_are_refused(tmp_path):
    # Swapped: the digest is protected, but for local-text, not for the benchmark being admitted.
    root = _custody_root(tmp_path, {"local-reasoning": "b" * 64, "local-text": "a" * 64})
    assert contract.protected_reference_errors(root, "a" * 64, "local-reasoning", "e") == [
        "e receipt: references are not a protected identifier of benchmark local-reasoning"]


@pytest.mark.parametrize("corruption", ["custody_bytes", "evidence", "entry_shape", "registry_json", "schema"])
def test_a_corrupt_registry_or_custody_binding_is_refused(tmp_path, corruption):
    digest = "a" * 64
    root = _custody_root(tmp_path, {"local-reasoning": digest})
    registry_path = root / contract.PROTECTED_EVAL_REGISTRY
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry["protected"][0]
    if corruption == "custody_bytes":
        manifest = root / entry["custody_manifest_path"]
        manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif corruption == "evidence":
        entry["evidence"]["evaluator_sha256"] = "6" * 64
    elif corruption == "entry_shape":
        del entry["custody_state"]
    elif corruption == "schema":
        registry["schema_version"] = "ember-protected-eval-registry-v1"
    if corruption == "registry_json":
        registry_path.write_text("{", encoding="utf-8")
    else:
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
    errors = contract.protected_reference_errors(root, digest, "local-reasoning", "e")
    assert len(errors) == 1 and "protected evaluation registry or custody invalid" in errors[0], errors


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
    # The criterion reads exact_match:geometry, which the re-score cannot produce (no geometry rows):
    # an unrescored dependency is METRIC_REPORTED_UNVERIFIED and never admitted (review 76764 R1).
    assert case.contract_errors() == [
        "evaluations[0] receipt: metrics are METRIC_REPORTED_UNVERIFIED (not re-scored by the verifier)"]


def test_a_reported_unknown_category_that_would_pass_is_never_admitted_while_the_rescore_succeeds(tmp_path):
    # Review 78811 R1: every row is arith and right, so exact_match and exact_match:arith re-score.
    # The criterion also reads a geometry category no row carries; the score is forged to report it
    # (1.0 over 40) so the reported metrics alone give PASSED. The verifier must not admit it.
    cats = [{"name": n, "metric": f"exact_match:{n}", "count_metric": f"count:{n}",
             "reference": _pin(tmp_path, f"ref-{n}.json", 0.5), "reference_factor": 0.8} for n in ("arith", "geometry")]
    criterion = _criterion(tmp_path, reference=0.5, categories=cats)
    case = Case(tmp_path, ALL_RIGHT, {k: "arith" for k in ALL_RIGHT}, criterion)
    assert case.run_scorer().returncode == 0
    score = json.loads(case.score.read_text())
    assert score["criterion_result"] == "UNDETERMINED" and "exact_match:geometry" not in score["metrics"]
    control = case.run_verifier()  # unforged: the rescore succeeds, the geometry input stays unverified
    assert control.returncode == 0, control.stderr
    assert json.loads(control.stdout)["metric_verification"] == "METRIC_REPORTED_UNVERIFIED"
    score["metrics"].update({"exact_match:geometry": 1.0, "count:geometry": 40})
    verdict = helper.admission(score["metrics"], score["sample_count"], helper.check_criterion(criterion, CRITERION),
                               case.protocol.parent)
    assert verdict["criterion_result"] == "PASSED"  # the forged report alone would pass
    score.update({field: verdict[field] for field in ("criterion_statistic", "admission_margin", "criterion_result")})
    case.score.write_text(json.dumps(score), encoding="utf-8")
    result = case.run_verifier()
    assert result.returncode == 1 and "differ from the verifier's re-score" in result.stderr, result.stderr
    assert case.contract_errors() == ["evaluations[0] receipt: verifier execution failed with exit code 1"]


def _text_contract_errors(tmp: Path, benchmark_version: str) -> list[str]:
    """The real text scorer's output, read by contract.execute_evaluation_verifier (review 78811 R2)."""
    score, _ = _text_case(tmp)
    evidence = {"split": tmp / "split.json", "harness": tmp / "harness.json", "protocol": tmp / "protocol.json",
                "inference_implementation": tmp / "inference.json", "predictions": tmp / "predictions.json",
                "score_artifact": tmp / "score.json", "references": tmp / "references.jsonl"}
    receipt = {"capability": "text", "result": "MEASURED", "subject_checkpoint_sha256": _sha(tmp / "checkpoint.json"),
               "benchmark_id": "local-text", "benchmark_version": benchmark_version,
               "sample_count": score["sample_count"], "metrics": score["metrics"], "criterion_id": TEXT_CRITERION,
               "criterion_statistic": score.get("criterion_statistic"), "admission_margin": score.get("admission_margin"),
               "criterion_result": score["criterion_result"]}
    for name, field in contract.EVALUATION_EVIDENCE.items():
        receipt[field] = _sha(evidence[name])
    return contract.execute_evaluation_verifier(ROOT, VERIFIER, "text", tmp / "checkpoint.json", "local-text",
                                                benchmark_version, TEXT_CRITERION, evidence, receipt, "evaluations[0]")


def test_text_scorer_output_passes_the_contract_verifier(tmp_path):
    assert _text_contract_errors(tmp_path, "1") == []


def test_text_scorer_output_for_another_benchmark_version_is_refused_by_the_contract(tmp_path):
    assert _text_contract_errors(tmp_path, "2") == [
        "evaluations[0] receipt: verifier execution failed with exit code 1"]


def test_the_eval_registry_is_the_training_authority_registry_and_the_train_screen_refuses_its_references(tmp_path):
    # Review 78811 R3. (a) The training text authority binds exactly the registry contract.py reads.
    index = json.loads((ROOT / "data/ember-restart-3b/text-lab-authority-index-v2.json").read_text(encoding="utf-8"))
    assert Path(index["registry"]["path"]) == contract.PROTECTED_EVAL_REGISTRY
    real = json.loads((ROOT / contract.PROTECTED_EVAL_REGISTRY).read_text(encoding="utf-8"))
    assert real["schema_version"] == contract.PROTECTED_EVAL_REGISTRY_SCHEMA
    # (b) The same reference bytes the evaluation side admits are refused by the executed train screen.
    case = Case(tmp_path, ALL_RIGHT, None, _criterion(tmp_path, reference=0.5))
    digest = _sha(case.references)
    root = _custody_root(tmp_path, {"local-reasoning": digest})
    assert contract.protected_reference_errors(root, digest, "local-reasoning", "e") == []
    screen = sys.modules["ember_train_screen_text_lab_corpus"]  # the module contract.py just executed
    assert Path(screen.__file__).resolve() == contract.TRAIN_SCREEN.resolve()
    registry = json.loads((root / contract.PROTECTED_EVAL_REGISTRY).read_text(encoding="utf-8"))
    protected = screen._protected_identifier_sets(root, registry["protected"])["content_sha256"]
    row = {"source_id": "candidate-x", "domain": screen.DOMAINS[0], "license_spdx": sorted(screen.LICENSES)[0],
           "content_sha256": digest, "l4_receipt": {}, "split": "train"}
    with pytest.raises(ValueError, match="source contaminates frozen eval"):
        screen._validate([row], protected, require_domain_floor=False)
    # Control: the same row with unregistered bytes passes the contamination check (fails later, on its receipt).
    with pytest.raises(ValueError, match="source L4 provenance receipt is invalid"):
        screen._validate([{**row, "content_sha256": "0" * 64}], protected, require_domain_floor=False)


BOUNDARY_FILES = (Path(__file__), ROOT / "tests" / "test_ember_restart_eval_criterion.py",
                  ROOT / "tests" / "domain-governance" / "test_ember_restart_eval_text_exact.py")


def _child_calls_missing_boundary(path: Path) -> list[str]:
    import ast
    missing = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"run", "Popen"}
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
            keywords = {k.arg: k.value for k in node.keywords}
            flags, timeout = keywords.get("creationflags"), keywords.get("timeout")
            # Values, not names: a literal 0 opens a console, a literal None never times out.
            if (flags is None or (isinstance(flags, ast.Constant) and not flags.value)
                    or timeout is None or (isinstance(timeout, ast.Constant) and timeout.value is None)):
                missing.append(f"{path.name}:{node.lineno}")
    return missing


def test_every_child_in_these_suites_is_hidden_and_bounded():
    # Review 78811 R4: a direct subprocess child must carry creationflags and a finite timeout;
    # the text_exact scorer child runs through owned_process.OwnedProcessRunner instead.
    assert [m for path in BOUNDARY_FILES for m in _child_calls_missing_boundary(path)] == []


@pytest.mark.parametrize("keywords", ["capture_output=True", "creationflags=0, timeout=60",
                                      "creationflags=HIDDEN, timeout=None", "creationflags=HIDDEN"])
def test_the_boundary_guard_sees_a_bare_or_unbounded_child(tmp_path, keywords):
    bare = tmp_path / "bare.py"
    bare.write_text(f"import subprocess, sys\nsubprocess.run([sys.executable], {keywords})\n", encoding="utf-8")
    assert _child_calls_missing_boundary(bare) == ["bare.py:2"]


def test_the_boundary_guard_admits_a_hidden_bounded_child(tmp_path):
    ok = tmp_path / "ok.py"
    ok.write_text("import subprocess, sys\nsubprocess.run([sys.executable], creationflags=HIDDEN, timeout=60)\n",
                  encoding="utf-8")
    assert _child_calls_missing_boundary(ok) == []


def test_the_text_exact_child_starts_through_the_mandatory_wrapper():
    import ast
    tree = ast.parse(BOUNDARY_FILES[2].read_text(encoding="utf-8"))
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert {"owned_children.run_one", "owned_children.python_argv"} <= calls
    assert not any(c.startswith("subprocess.") for c in calls), calls


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
