#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score local audio transcript fixtures; output is never capability evidence."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{64}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rows(data: bytes) -> dict[str, str]:
    try:
        raw = data.decode("utf-8")
        parsed = json.loads(raw)
        values = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        values = [json.loads(line) for line in raw.splitlines() if line.strip()]
    output = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"] or not isinstance(value.get("transcript"), str) or value["id"] in output:
            raise ValueError("each row needs a unique non-empty id and transcript")
        output[value["id"]] = value["transcript"]
    if not output:
        raise ValueError("rows must be non-empty")
    return output


def distance(left: list[str], right: list[str]) -> int:
    prior = list(range(len(right) + 1))
    for index, token in enumerate(left, 1):
        current = [index]
        for right_index, candidate in enumerate(right, 1):
            current.append(min(prior[right_index] + 1, current[right_index - 1] + 1, prior[right_index - 1] + (token != candidate)))
        prior = current
    return prior[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-audio-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        manifest_bytes = args.frozen_audio_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        prediction_bytes = args.predictions.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        references, predictions = rows(reference_bytes), rows(prediction_bytes)
        if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "local-audio-wer" or manifest.get("benchmark_version") != "1" or manifest.get("references_sha256") != digest(reference_bytes) or not HASH.fullmatch(manifest.get("references_sha256", "")):
            raise ValueError("frozen audio manifest does not bind supplied references")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid local transcript artifacts: {error}")
    if references.keys() != predictions.keys():
        parser.error("predictions must exactly cover frozen reference ids")
    words = sum(len(value.split()) for value in references.values())
    if words <= 0:
        parser.error("frozen references must contain at least one word")
    payload = {"result": "SELFTEST", "claim_status": "SELFTEST_ONLY_FIXTURE_AUDIO_TRANSCRIPTS", "criterion_id": "ember-3b-audio-capability-v1", "criterion_result": "FAILED", "metrics": {"word_error_rate": sum(distance(references[key].split(), predictions[key].split()) for key in references) / words}, "sample_count": len(references), "references_sha256": digest(reference_bytes), "predictions_sha256": digest(prediction_bytes), "frozen_audio_manifest_sha256": digest(manifest_bytes), "upstream": "fixture-only local word-error-rate scorer"}
    args.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.score_output.parent, delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, args.score_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())