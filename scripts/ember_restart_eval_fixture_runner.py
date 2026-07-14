#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic fixture-only scorer; its output cannot be centrally admitted."""
import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = json.loads(args.fixture.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        parser.error("fixture must be non-empty list")
    scored = []
    for row in rows:
        if not isinstance(row, dict) or row.get("capability") not in ("text", "image", "audio", "reasoning", "tool") or "expected" not in row or "actual" not in row:
            parser.error("invalid fixture selftest row")
        scored.append({"id": row.get("id"), "capability": row["capability"], "correct": row["actual"] == row["expected"]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "rows": scored, "correct": sum(x["correct"] for x in scored), "total": len(scored)}, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
