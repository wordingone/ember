# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Adjudicate a per-capability ember-3b-<capability>-capability-v1 criterion.

Evidence class: evaluation. Invoked by src/ember/governance/scripts/ember_restart/contract.py as

    python -I capability-evaluation-verifier.py \
        --capability <capability> --checkpoint-manifest <path> \
        --benchmark-id <id> --benchmark-version <version> --criterion-id <id> \
        --split <path> --harness <path> --protocol <path> \
        --inference-implementation <path> --predictions <path> --score-artifact <path> \
        --references <path>

For local-text and local-reasoning the verifier re-scores the frozen answers itself
(references vs the canonical prediction rows, exact id-set match) and refuses a score
whose metrics differ; any other benchmark is reported METRIC_REPORTED_UNVERIFIED.

`sample_count` is recounted from the predictions envelope rather than read from the
score artifact, so a score computed over fewer rows than were predicted is caught
here. As with the sufficiency verifier, the pass bar is not hardcoded: it comes from
the frozen protocol's pre-registered `criterion` block, and a protocol without one
fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import types
import sys
from pathlib import Path

CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_count(predictions: Path) -> int:
    payload = json.loads(predictions.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("predictions: expected a non-empty rows list")
    return len(rows)


# Benchmarks this verifier re-scores itself from the frozen references and the canonical
# prediction rows. Any other benchmark's metrics are only reported by its scorer, and the
# output says so; contract.py never admits a METRIC_REPORTED_UNVERIFIED receipt.
RESCORED_BENCHMARKS = frozenset({"local-text", "local-reasoning"})
RESCORED = "RESCORED"
METRIC_REPORTED_UNVERIFIED = "METRIC_REPORTED_UNVERIFIED"


def read_references(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Frozen reference answers (JSON list or JSONL of {id, answer[, category]})."""
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
        values = value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        values = [json.loads(line) for line in raw.splitlines() if line.strip()]
    answers: dict[str, str] = {}
    categories: dict[str, str] = {}
    for row in values:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or not isinstance(row.get("answer"), str) or row["id"] in answers):
            raise ValueError("references: each row needs a unique non-empty id and an answer")
        answers[row["id"]] = row["answer"]
        if "category" in row:
            if not isinstance(row["category"], str) or not row["category"]:
                raise ValueError("references: a category must be a non-empty string")
            categories[row["id"]] = row["category"]
    if not answers:
        raise ValueError("references: rows must be non-empty")
    if categories and len(categories) != len(answers):
        raise ValueError("references: either every row carries a category or none does")
    return answers, categories


def read_predicted_answers(predictions: Path) -> dict[str, str]:
    """Answer per id from the canonical prediction rows (output text, transcript or choice)."""
    rows = json.loads(predictions.read_text(encoding="utf-8")).get("rows")
    answers: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        output = row.get("output") if isinstance(row, dict) else None
        kind = output.get("kind") if isinstance(output, dict) else None
        answer = output.get("value" if kind == "choice" else "text") if kind in {"text", "transcript", "choice"} else None
        if not isinstance(row.get("id"), str) or not row["id"] or row["id"] in answers or not isinstance(answer, str):
            raise ValueError("predictions: every row needs a unique id and a text or choice output")
        answers[row["id"]] = answer
    if not answers:
        raise ValueError("predictions: expected a non-empty rows list")
    return answers


def rescore(score: dict, references: Path, predictions: Path) -> dict | None:
    """Recompute exact_match (and per-category exact_match/count) and refuse any reported metric that differs.

    Returns the recomputed metrics, or None for a benchmark this verifier cannot re-score.
    """
    if score.get("benchmark_id") not in RESCORED_BENCHMARKS:
        return None
    if score.get("references_sha256") != sha256(references):
        raise ValueError("score artifact: references_sha256 does not bind the supplied references")
    expected, categories = read_references(references)
    predicted = read_predicted_answers(predictions)
    if predicted.keys() != expected.keys():
        raise ValueError("predictions: ids must exactly cover the frozen reference ids")
    correct = {key: predicted[key] == expected[key] for key in expected}
    recomputed: dict[str, float] = {"exact_match": sum(correct.values()) / len(correct)}
    for name in sorted(set(categories.values())):
        ids = [key for key in expected if categories[key] == name]
        recomputed[f"exact_match:{name}"] = sum(correct[key] for key in ids) / len(ids)
        recomputed[f"count:{name}"] = len(ids)
    reported = score.get("metrics")
    if not isinstance(reported, dict):
        raise ValueError("score artifact: metrics missing")
    reported_scored = {k: v for k, v in reported.items() if k == "exact_match" or k.startswith(("exact_match:", "count:"))}
    if reported_scored != recomputed:
        raise ValueError("score artifact metrics: differ from the verifier's re-score of the frozen answers")
    return recomputed


def criterion_dependencies(criterion: dict, helper) -> set[str]:
    """Every score metric the verdict reads: the criterion metric (or a derived metric's inputs),
    and each category's metric and count."""
    names = {criterion["metric"]}
    for category in criterion.get("categories") or []:
        names |= {category["metric"], category["count_metric"]}
    out: set[str] = set()
    for name in names:
        out |= set(helper.DERIVED[name][0]) if name in helper.DERIVED else {name}
    return out


# The adjudication rule has ONE implementation: the scorers' criterion helper. This
# verifier executes exactly the helper bytes whose sha256 it pins, so re-pinning this
# file in trusted-verifiers-v1.json transitively pins the rule (review 76202 D1).
CRITERION_HELPER = Path("scripts") / "ember_restart_eval_criterion.py"
CRITERION_HELPER_SHA256 = "dda574c2df75fe37cd7509276399e45a683f6a68be8d0e023f7fed420ad8e192"
ADJUDICATION_FIELDS = ("criterion_statistic", "admission_margin", "criterion_result")


def load_criterion_helper(root: Path):
    raw = (root / CRITERION_HELPER).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CRITERION_HELPER_SHA256:
        raise ValueError(f"{CRITERION_HELPER.as_posix()}: bytes do not match the pinned sha256")
    module = types.ModuleType("ember_restart_eval_criterion")
    module.__file__ = str(root / CRITERION_HELPER)
    sys.modules[module.__name__] = module  # dataclass/typing lookups resolve by name
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return module


def load_criterion(score: dict, protocol: Path, criterion_id: str, count: int, helper) -> dict:
    """Bind the score to the protocol and the recounted predictions; return the checked criterion."""
    if score.get("evaluation_role") != helper.ADJUDICATED:
        raise ValueError("score artifact: evaluation_role must be adjudicated")
    raw = protocol.read_bytes()
    if score.get("protocol_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("score artifact: protocol_sha256 does not bind the supplied protocol")
    if score.get("sample_count") != count:
        raise ValueError("score artifact: sample_count differs from the recounted predictions")
    payload = json.loads(raw.decode("utf-8"))
    return helper.check_criterion(payload.get("criterion") if isinstance(payload, dict) else None, criterion_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability", required=True, choices=CAPABILITIES)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--benchmark-version", required=True)
    parser.add_argument("--criterion-id", required=True)
    parser.add_argument("--split", required=True, type=Path)
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--inference-implementation", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--score-artifact", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.criterion_id != f"ember-3b-{args.capability}-capability-v1":
        print("criterion does not match the requested capability", file=sys.stderr)
        return 1

    try:
        score = json.loads(args.score_artifact.read_text(encoding="utf-8"))
        if score.get("evaluation_role") == "diagnostic":
            raise ValueError("score artifact: diagnostic evaluation (no frozen protocol) is never admissible")
        if score.get("benchmark_id") != args.benchmark_id:
            raise ValueError("score artifact: benchmark_id mismatch")
        if score.get("benchmark_version") != args.benchmark_version:
            raise ValueError("score artifact: benchmark_version mismatch")
        metrics = score.get("metrics")
        count = sample_count(args.predictions)
        helper = load_criterion_helper(Path(__file__).resolve().parents[3])
        criterion = load_criterion(score, args.protocol, args.criterion_id, count, helper)
        # Re-score first; acceptance is then computed only from metrics this verifier recomputed.
        recomputed = rescore(score, args.references, args.predictions)
        if recomputed is not None and criterion_dependencies(criterion, helper) <= recomputed.keys():
            metric_verification = RESCORED
            verdict = helper.admission(recomputed, count, criterion, args.protocol.parent)
        else:
            metric_verification = METRIC_REPORTED_UNVERIFIED
            verdict = helper.admission(metrics, count, criterion, args.protocol.parent)
        for field in ADJUDICATION_FIELDS:
            if score.get(field) != verdict.get(field):
                raise ValueError(f"score artifact {field}: differs from the recomputed value")
    except (ValueError, json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    attestation = {
        "capability": args.capability,
        "result": "MEASURED",
        "subject_checkpoint_sha256": sha256(args.checkpoint_manifest),
        "benchmark_id": args.benchmark_id,
        "benchmark_version": args.benchmark_version,
        "split_sha256": sha256(args.split),
        "harness_sha256": sha256(args.harness),
        "protocol_sha256": sha256(args.protocol),
        "inference_implementation_sha256": sha256(args.inference_implementation),
        "predictions_sha256": sha256(args.predictions),
        "score_artifact_sha256": sha256(args.score_artifact),
        "references_sha256": sha256(args.references),
        "metric_verification": metric_verification,
        "sample_count": count,
        "metrics": metrics,
        "criterion_id": args.criterion_id,
        **{field: verdict[field] for field in ADJUDICATION_FIELDS},
    }
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
