#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Exact-match image/audio fixture scorer with media-byte custody checks."""
import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    prediction_bytes = args.predictions.read_bytes()
    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    predictions_sha256 = hashlib.sha256(prediction_bytes).hexdigest()
    rows = json.loads(fixture_bytes.decode("utf-8"))
    predictions = json.loads(prediction_bytes.decode("utf-8"))
    scored = []
    for row in rows:
        media = args.fixture.parent / row["media_path"]
        digest = hashlib.sha256(media.read_bytes()).hexdigest()
        if row.get("capability") not in ("image", "audio") or digest != row.get("media_sha256"):
            parser.error("invalid or changed media fixture")
        scored.append({"id": row["id"], "capability": row["capability"], "correct": predictions.get(row["id"]) == row["answer"]})
    args.output.write_text(json.dumps({"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "fixture_sha256": fixture_sha256, "predictions_sha256": predictions_sha256, "rows": scored, "correct": sum(x["correct"] for x in scored), "total": len(scored)}, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
