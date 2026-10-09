# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds for the scorer verdict helper and its wiring into the seven local scorers (#1947)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
# Scorer children start hidden and owned (job object, CREATE_NO_WINDOW, hidden STARTUPINFO; review 75028), never bare.
sys.path.insert(0, str(ROOT / "tests" / "ember_restart_model"))
import owned_children  # noqa: E402
SCORERS = ("mmmu", "text_exact", "reasoning_exact", "audio_wer", "audiobench_bound", "browsergym", "terminal_bench")
CID = "ember-3b-reasoning-capability-v1"

_spec = importlib.util.spec_from_file_location("ember_restart_eval_criterion", SCRIPTS / "ember_restart_eval_criterion.py")
crit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crit)


def _criterion(**overrides):
    base = {
        "criterion_id": CID,
        "metric": "exact_match",
        "direction": "higher_is_better",
        "statistic": {"kind": "point"},
        "comparator": {"kind": "min_value", "value": 0.5},
        "categories": [],
    }
    base.update(overrides)
    return base


def _protocol(tmp_path: Path, criterion) -> Path:
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps({"criterion": criterion}), encoding="utf-8")
    return path


def _pinned(tmp_path: Path, name: str, value) -> dict:
    path = tmp_path / name
    path.write_text(json.dumps({"value": value}), encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_at_or_above_min_value_passes_and_below_fails(tmp_path):
    protocol = _protocol(tmp_path, _criterion())
    assert crit.verdict_fields(protocol, CID, {"exact_match": 0.5}, 2)["criterion_result"] == "PASSED"
    assert crit.verdict_fields(protocol, CID, {"exact_match": 0.49}, 2)["criterion_result"] == "FAILED"


def test_lower_is_better_uses_max_value(tmp_path):
    protocol = _protocol(tmp_path, _criterion(metric="word_error_rate", direction="lower_is_better",
                                               comparator={"kind": "max_value", "value": 0.2}))
    assert crit.verdict_fields(protocol, CID, {"word_error_rate": 0.2}, 9)["criterion_result"] == "PASSED"
    assert crit.verdict_fields(protocol, CID, {"word_error_rate": 0.21}, 9)["criterion_result"] == "FAILED"


def test_a_lower_confidence_bound_fails_a_point_estimate_that_would_pass(tmp_path):
    bound = {"kind": "lower_confidence_bound", "level": 0.95, "method": "wilson_one_sided"}
    point = _protocol(tmp_path, _criterion(comparator={"kind": "min_value", "value": 0.6}))
    assert crit.verdict_fields(point, CID, {"exact_match": 0.7}, 20)["criterion_result"] == "PASSED"
    lcb = _protocol(tmp_path, _criterion(statistic=bound, comparator={"kind": "min_value", "value": 0.6}))
    assert crit.verdict_fields(lcb, CID, {"exact_match": 0.7}, 20)["criterion_result"] == "FAILED"
    assert crit.verdict_fields(lcb, CID, {"exact_match": 0.7}, 2000)["criterion_result"] == "PASSED"


def test_wilson_lower_bound_matches_a_hand_value():
    statistic = {"kind": "lower_confidence_bound", "level": 0.95, "method": "wilson_one_sided"}
    # p=0.5, n=100, z=1.644854: centre 0.5 by symmetry; half = z*sqrt(0.0025+z^2/40000)/(1+z^2/100) = 0.081152
    assert crit.statistic_value(0.5, 100, statistic) == pytest.approx(0.418848, abs=1e-5)


def _max_of(tmp_path: Path, **overrides) -> dict:
    comparator = {"kind": "max_of", "reference": _pinned(tmp_path, "reference.json", 0.6),
                  "chance": _pinned(tmp_path, "chance.json", 0.25), "reference_factor": 0.8, "chance_factor": 2}
    comparator.update(overrides)
    return comparator


def test_max_of_bar_is_the_larger_scaled_term_and_binds_both_artifacts(tmp_path):
    # bar = max(0.8 x 0.6, 2 x 0.25) = 0.5
    protocol = _protocol(tmp_path, _criterion(comparator=_max_of(tmp_path)))
    at_bar = crit.verdict_fields(protocol, CID, {"exact_match": 0.5}, 50)
    assert at_bar["criterion_result"] == "PASSED" and at_bar["admission_margin"] == pytest.approx(0.0)
    below = crit.verdict_fields(protocol, CID, {"exact_match": 0.49}, 50)
    assert below["criterion_result"] == "FAILED" and below["admission_margin"] == pytest.approx(-0.01)
    (tmp_path / "reference.json").write_text(json.dumps({"value": 0.1}), encoding="utf-8")
    with pytest.raises(ValueError, match="do not match the pinned sha256"):
        crit.verdict_fields(protocol, CID, {"exact_match": 0.61}, 50)


@pytest.mark.parametrize("drop", ["reference_factor", "chance_factor", "reference", "chance"])
def test_max_of_requires_every_term(tmp_path, drop):
    comparator = _max_of(tmp_path)
    del comparator[drop]
    with pytest.raises(ValueError, match="max_of requires exactly"):
        crit.verdict_fields(_protocol(tmp_path, _criterion(comparator=comparator)), CID, {"exact_match": 1.0}, 2)


def test_margin_and_statistic_are_emitted_for_every_comparator(tmp_path):
    bound = {"kind": "lower_confidence_bound", "level": 0.95, "method": "wilson_one_sided"}
    fields = crit.verdict_fields(_protocol(tmp_path, _criterion(statistic=bound, comparator={"kind": "min_value", "value": 0.4})),
                                 CID, {"exact_match": 0.5}, 100)
    assert fields["criterion_statistic"] == pytest.approx(0.418848, abs=1e-5)
    assert fields["admission_margin"] == pytest.approx(0.018848, abs=1e-5) and fields["criterion_result"] == "PASSED"
    low = crit.verdict_fields(_protocol(tmp_path, _criterion(metric="word_error_rate", direction="lower_is_better",
                                                             comparator={"kind": "max_value", "value": 0.2})),
                              CID, {"word_error_rate": 0.25}, 9)
    assert low["admission_margin"] == pytest.approx(-0.05) and low["criterion_result"] == "FAILED"


@pytest.mark.parametrize("missing", ["metric", "direction", "statistic", "comparator", "categories"])
def test_every_criterion_field_is_required(tmp_path, missing):
    criterion = _criterion()
    del criterion[missing]
    with pytest.raises(ValueError, match=f"criterion.{missing}: required"):
        crit.verdict_fields(_protocol(tmp_path, criterion), CID, {"exact_match": 1.0}, 2)


@pytest.mark.parametrize("bad, match", [
    ({"statistic": {"kind": "lower_confidence_bound", "level": 0.95}}, "requires exactly kind, level and method"),
    ({"statistic": {"kind": "lower_confidence_bound", "level": 0.95, "method": "bootstrap"}}, "wilson_one_sided"),
    ({"statistic": {"kind": "upper_confidence_bound", "level": 0.95, "method": "wilson_one_sided"}}, "not valid for higher_is_better"),
    ({"comparator": {"kind": "max_value", "value": 1}}, "not valid for higher_is_better"),
    ({"comparator": {"kind": "min_value"}}, "requires exactly kind and value"),
    ({"direction": "up"}, "criterion.direction"),
])
def test_malformed_criteria_refuse(tmp_path, bad, match):
    with pytest.raises(ValueError, match=match):
        crit.verdict_fields(_protocol(tmp_path, _criterion(**bad)), CID, {"exact_match": 1.0}, 2)


def test_a_protocol_without_a_criterion_block_refuses(tmp_path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"benchmark": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="criterion block missing"):
        crit.verdict_fields(protocol, CID, {"exact_match": 1.0}, 2)


def test_no_protocol_is_diagnostic_with_no_verdict():
    assert crit.verdict_fields(None, CID, {"exact_match": 1.0}, 2) == {"criterion_id": CID, "evaluation_role": "diagnostic"}


def _run_reasoning(tmp_path: Path, protocol: Path | None):
    references, predictions = tmp_path / "references", tmp_path / "predictions"
    manifest, score = tmp_path / "manifest", tmp_path / "score.json"
    references.write_text('{"id":"r1","answer":"42"}\n{"id":"r2","answer":"red"}\n', encoding="utf-8")
    predictions.write_text('{"id":"r1","answer":"42"}\n{"id":"r2","answer":"blue"}\n', encoding="utf-8")
    manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "local-reasoning", "benchmark_version": "1",
                                    "references_sha256": hashlib.sha256(references.read_bytes()).hexdigest()}), encoding="utf-8")
    score.unlink(missing_ok=True)
    args = [str(SCRIPTS / "ember_restart_eval_reasoning_exact.py"), "--frozen-reasoning-manifest", str(manifest),
            "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)]
    if protocol is not None:
        args += ["--protocol", str(protocol)]
    result = owned_children.run_one(owned_children.python_argv(*args), timeout_s=120)
    assert result.status != "terminated", "scorer child timed out"
    return result, (json.loads(score.read_text(encoding="utf-8")) if result.returncode == 0 else None)


def test_scorer_children_start_hidden(monkeypatch):
    """Red for review 75028: read the flags the runner actually passes to Popen for a scorer child."""
    import owned_process
    seen = {}
    real = owned_process.subprocess.Popen

    def spy(argv, **kwargs):
        seen.update(kwargs, argv=list(argv))
        return real(argv, **kwargs)

    monkeypatch.setattr(owned_process.subprocess, "Popen", spy)
    result = owned_children.run_one(owned_children.python_argv("-c", "pass"), timeout_s=60)
    assert result.returncode == 0
    assert seen.get("shell") is False
    if sys.platform == "win32":
        assert seen["argv"][:2] == ["powershell.exe", "-NoLogo"] and "headless-python.ps1" in " ".join(seen["argv"])
        assert seen["creationflags"] & 0x08000000, "CREATE_NO_WINDOW not passed"
        info = seen.get("startupinfo")
        assert info is not None and info.wShowWindow == 0 and info.dwFlags & 0x1, "hidden STARTUPINFO not passed"


def test_scorer_without_protocol_writes_a_diagnostic_score(tmp_path):
    result, payload = _run_reasoning(tmp_path, None)
    assert result.returncode == 0, result.stderr
    assert payload["evaluation_role"] == "diagnostic" and "criterion_result" not in payload


def test_scorer_with_protocol_adjudicates_both_ways_and_pins_the_protocol(tmp_path):
    passing = _protocol(tmp_path, _criterion(comparator={"kind": "min_value", "value": 0.5}))
    result, payload = _run_reasoning(tmp_path, passing)
    assert result.returncode == 0, result.stderr
    assert payload["criterion_result"] == "PASSED" and payload["evaluation_role"] == "adjudicated"
    assert payload["protocol_sha256"] == hashlib.sha256(passing.read_bytes()).hexdigest()
    failing = _protocol(tmp_path, _criterion(comparator={"kind": "min_value", "value": 0.51}))
    result, payload = _run_reasoning(tmp_path, failing)
    assert result.returncode == 0, result.stderr
    assert payload["criterion_result"] == "FAILED"


def test_scorer_refuses_a_protocol_with_no_criterion(tmp_path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text("{}", encoding="utf-8")
    result, _ = _run_reasoning(tmp_path, protocol)
    assert result.returncode != 0 and "criterion block missing" in result.stderr


HARDCODED_VERDICT = re.compile(r"""['"]criterion_result['"]\s*:\s*['"](PASSED|FAILED)['"]""")


def test_no_scorer_hardcodes_a_verdict():
    offenders = [p.name for p in sorted(SCRIPTS.glob("ember_restart_eval_*.py"))
                 if p.name != "ember_restart_eval_criterion.py"  # the one module that derives a verdict
                 and HARDCODED_VERDICT.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_lint_sees_a_planted_hardcoded_verdict():
    assert HARDCODED_VERDICT.search("""payload={'criterion_result':'FAILED'}""")
    assert HARDCODED_VERDICT.search('''{"criterion_result": "PASSED"}''')


@pytest.mark.parametrize("name", SCORERS)
def test_every_scorer_takes_an_optional_protocol_and_uses_the_helper(name):
    source = (SCRIPTS / f"ember_restart_eval_{name}.py").read_text(encoding="utf-8")
    assert "from ember_restart_eval_criterion import verdict_fields" in source
    assert "--protocol" in source and "verdict_fields(" in source


def test_derived_quality_and_discrimination_are_criterion_metrics(tmp_path):
    q = _protocol(tmp_path, _criterion(metric="quality_one_minus_wer", comparator={"kind": "min_value", "value": 0.7}))
    assert crit.verdict_fields(q, CID, {"word_error_rate": 0.25}, 9)["admission_margin"] == pytest.approx(0.05)
    assert crit.verdict_fields(q, CID, {"word_error_rate": 1.5}, 9)["admission_margin"] == pytest.approx(-1.2)  # unclipped
    j = _protocol(tmp_path, _criterion(metric="discrimination_j", comparator={"kind": "min_value", "value": 0.0}))
    # always-positive policy: recall 1, fpr 1 -> J 0
    assert crit.verdict_fields(j, CID, {"weighted_recall": 1.0, "weighted_fpr": 1.0}, 4)["admission_margin"] == pytest.approx(0.0)
    with pytest.raises(ValueError, match="must not be supplied by the scorer"):
        crit.verdict_fields(j, CID, {"weighted_recall": 1.0, "weighted_fpr": 0.0, "discrimination_j": 1.0}, 4)


def _reasoning_with_category(tmp_path: Path) -> Path:
    # ruling 74883: composite point .70 vs 0.8 x ref .80 = +.06; category point .40 vs 0.7 x ref .80 = -.16
    comparator = {"kind": "max_of", "reference": _pinned(tmp_path, "reference.json", 0.8),
                  "chance": _pinned(tmp_path, "chance.json", 0.0), "reference_factor": 0.8, "chance_factor": 2}
    categories = [{"name": "counterfactual", "metric": "category:counterfactual:exact_match",
                   "count_metric": "category:counterfactual:count",
                   "reference": _pinned(tmp_path, "category-reference.json", 0.8), "reference_factor": 0.7}]
    return _protocol(tmp_path, _criterion(comparator=comparator, categories=categories))


def test_a_failing_category_sets_the_margin_even_when_the_composite_passes(tmp_path):
    fields = crit.verdict_fields(_reasoning_with_category(tmp_path), CID,
                                 {"exact_match": 0.70, "category:counterfactual:exact_match": 0.40,
                                  "category:counterfactual:count": 50}, 200)
    assert fields["composite_margin"] == pytest.approx(0.06)
    assert fields["category_margins"] == {"counterfactual": pytest.approx(-0.16)}
    assert fields["admission_margin"] == pytest.approx(-0.16) and fields["criterion_result"] == "FAILED"


def test_a_category_input_the_score_lacks_is_undetermined_never_passed(tmp_path):
    fields = crit.verdict_fields(_reasoning_with_category(tmp_path), CID, {"exact_match": 0.95}, 200)
    assert fields["criterion_result"] == "UNDETERMINED" and fields["admission_margin"] is None
    assert "counterfactual" in fields["undetermined_reason"]


def test_an_absent_criterion_metric_is_undetermined(tmp_path):
    fields = crit.verdict_fields(_protocol(tmp_path, _criterion()), CID, {"accuracy": 1.0}, 2)
    assert fields["criterion_result"] == "UNDETERMINED" and fields["admission_margin"] is None


def test_a_category_uses_its_own_count_for_the_bound(tmp_path):
    bound = {"kind": "lower_confidence_bound", "level": 0.95, "method": "wilson_one_sided"}
    categories = [{"name": "c", "metric": "m_c", "count_metric": "n_c",
                   "reference": _pinned(tmp_path, "category-reference.json", 0.5), "reference_factor": 0.7}]
    protocol = _protocol(tmp_path, _criterion(statistic=bound, comparator={"kind": "min_value", "value": 0.0},
                                              categories=categories))
    fields = crit.verdict_fields(protocol, CID, {"exact_match": 0.5, "m_c": 0.5, "n_c": 100}, 10_000)
    assert fields["category_margins"]["c"] == pytest.approx(0.418848 - 0.35, abs=1e-5)


@pytest.mark.parametrize("bad", [
    {"name": "c", "metric": "m", "count_metric": "n", "reference_factor": 0.7},
    "not-an-object",
])
def test_malformed_categories_refuse(tmp_path, bad):
    with pytest.raises(ValueError, match="categories"):
        crit.verdict_fields(_protocol(tmp_path, _criterion(categories=[bad])), CID, {"exact_match": 1.0}, 2)
