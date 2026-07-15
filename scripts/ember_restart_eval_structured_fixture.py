#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score frozen reasoning/tool fixtures locally; output is not centrally admissible."""
import argparse
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", required=True, choices=("reasoning", "tool"))
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        fixture_bytes = args.fixture.read_bytes()
        prediction_bytes = args.predictions.read_bytes()
        fixture = json.loads(fixture_bytes.decode("utf-8"))
        predictions = json.loads(prediction_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        parser.error(f"invalid structured fixture input: {error}")
    if not isinstance(fixture, list) or not fixture or not isinstance(predictions, dict):
        parser.error("fixture must be non-empty and predictions must be an object")
    rows = []
    expected_field = "answer" if args.capability == "reasoning" else "expected_call"
    for row in fixture:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or expected_field not in row:
            parser.error("invalid structured fixture row")
        expected = row[expected_field]
        actual = predictions.get(row["id"])
        equal = actual == expected if args.capability == "reasoning" else canonical(actual) == canonical(expected)
        rows.append({"id": row["id"], "correct": equal})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "capability": args.capability, "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(), "predictions_sha256": hashlib.sha256(prediction_bytes).hexdigest(), "rows": rows, "correct": sum(row["correct"] for row in rows), "total": len(rows)}, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
