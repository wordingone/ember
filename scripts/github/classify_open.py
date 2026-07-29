#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed entrypoint for evidence-bound open-work classification."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.github import classify_open_engine as engine
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.github import classify_open_engine as engine


def classify(item: dict[str, Any]) -> dict[str, Any]:
    """Classify from body/comment evidence with an explicit area fallback."""
    body = item.get("body") or ""
    comments = "\n".join(row.get("body") or "" for row in item.get("comments", []))
    evidence = body + "\n" + comments
    if engine._signals(evidence, engine.AREA_SIGNALS):
        return engine.classify(item)

    staged = copy.deepcopy(item)
    staged["body"] = body + "\n__fallback_governance_area__"
    original = engine.AREA_SIGNALS["area:governance"]
    engine.AREA_SIGNALS["area:governance"] = original + (
        "__fallback_governance_area__",
    )
    try:
        row = engine.classify(staged)
    finally:
        engine.AREA_SIGNALS["area:governance"] = original
    if row["review_status"] == "MACHINE_CANDIDATE":
        row["basis"]["body_sha256"] = engine.digest_text(body)
        row["basis"]["area_signals"]["area:governance"] = [
            "full body has no narrower area signal"
        ]
    return row


def build(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = [classify(item) for item in snapshot["open_items"]]
    result = {
        "schema_version": "ember-open-work-classification/v1",
        "repository": snapshot["repository"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "rows": rows,
        "claim_boundary": (
            "candidate metadata only; no issue closure, scientific, training, "
            "model-capability, or acceptance-completion claim"
        ),
    }
    result["classification_sha256"] = hashlib.sha256(
        engine.canonical_bytes(result)
    ).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8", errors="strict"))
    result = build(snapshot)
    args.output.write_bytes(engine.canonical_bytes(result) + b"\n")
    counts: dict[str, int] = {}
    for row in result["rows"]:
        status = row["review_status"]
        counts[status] = counts.get(status, 0) + 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "counts": counts,
                "sha256": result["classification_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
