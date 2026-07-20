#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score fixture predictions locally; output is deliberately non-admissible."""
import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.fixture.read_text(encoding="utf-8"))
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    scored = []
    for row in rows:
        if not isinstance(row, dict) or "id" not in row or "answer" not in row:
            parser.error("invalid frozen text row")
        scored.append({"id": row["id"], "correct": predictions.get(row["id"]) == row["answer"]})
    args.output.write_text(json.dumps({"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "benchmark_id": "frozen-text-fixture-v1", "rows": scored, "correct": sum(x["correct"] for x in scored), "total": len(scored)}, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
