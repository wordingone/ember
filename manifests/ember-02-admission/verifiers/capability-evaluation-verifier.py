# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Adjudicate a per-capability ember-3b-<capability>-capability-v1 criterion.

Evidence class: evaluation. Invoked by src/ember/governance/scripts/ember_restart/contract.py as

    python -I capability-evaluation-verifier.py \
        --capability <capability> --checkpoint-manifest <path> \
        --benchmark-id <id> --benchmark-version <version> --criterion-id <id> \
        --split <path> --harness <path> --protocol <path> \
        --inference-implementation <path> --predictions <path> --score-artifact <path>

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


# The adjudication rule has ONE implementation: the scorers' criterion helper. This
# verifier executes exactly the helper bytes whose sha256 it pins, so re-pinning this
# file in trusted-verifiers-v1.json transitively pins the rule (review 76202 D1).
CRITERION_HELPER = Path("scripts") / "ember_restart_eval_criterion.py"
CRITERION_HELPER_SHA256 = "1f6e78eb035e78adba5995b7359e97a7905e2aa7a895c22f7f0d06a35a7a7106"
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


def adjudicate(score: dict, protocol: Path, criterion_id: str, count: int, helper) -> dict:
    """Recompute every adjudication field from the protocol and the recounted predictions."""
    if score.get("evaluation_role") != helper.ADJUDICATED:
        raise ValueError("score artifact: evaluation_role must be adjudicated")
    raw = protocol.read_bytes()
    if score.get("protocol_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("score artifact: protocol_sha256 does not bind the supplied protocol")
    if score.get("sample_count") != count:
        raise ValueError("score artifact: sample_count differs from the recounted predictions")
    payload = json.loads(raw.decode("utf-8"))
    criterion = helper.check_criterion(payload.get("criterion") if isinstance(payload, dict) else None,
                                       criterion_id)
    return helper.admission(score.get("metrics"), count, criterion, protocol.parent)


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
        verdict = adjudicate(score, args.protocol, args.criterion_id, count, helper)
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
        "sample_count": count,
        "metrics": metrics,
        "criterion_id": args.criterion_id,
        **{field: verdict[field] for field in ADJUDICATION_FIELDS},
    }
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
