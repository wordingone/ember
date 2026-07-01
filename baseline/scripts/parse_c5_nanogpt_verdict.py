#!/usr/bin/env python3
"""Emit a governed C5-0B nanoGPT_lite improvement verdict.

The parser compares a governed baseline run receipt against a governed Ember or
candidate run receipt. It intentionally rejects smoke-reduced receipts so a fast
wiring check cannot be laundered into a baseline completion gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def metric_from(receipt: dict[str, Any], dataset: str) -> float | None:
    parsed = receipt.get("parsed_final_info")
    if not isinstance(parsed, dict):
        return None
    row = parsed.get(dataset)
    if not isinstance(row, dict):
        return None
    means = row.get("means")
    if not isinstance(means, dict):
        return None
    value = means.get("best_val_loss_mean")
    return float(value) if isinstance(value, (int, float)) else None


def is_smoke(receipt: dict[str, Any]) -> bool:
    text = json.dumps(receipt, sort_keys=True).lower()
    explicit_smoke_markers = (
        "smoke_reduced",
        "smoke-reduced",
        "smoke reduced",
        "smoke_run",
        "smoke run",
        "smoke copy",
        "deliberately reduced 3-iteration smoke",
    )
    return any(marker in text for marker in explicit_smoke_markers)


def governed_ok(receipt: dict[str, Any]) -> bool:
    return receipt.get("governed_run") is True and receipt.get("verdict") == "PASS" and not is_smoke(receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-receipt", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--dataset", default="shakespeare_char")
    parser.add_argument("--min-improvement-pct", type=float, default=1.0)
    parser.add_argument("--claim-id", default="C5-0B-AI-Scientist-nanoGPT-lite")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    errors = []
    baseline = load(args.baseline_receipt)
    candidate = load(args.candidate_receipt)

    if not governed_ok(baseline):
        errors.append("baseline_receipt_is_not_a_governed_non_smoke_PASS_run")
    if not governed_ok(candidate):
        errors.append("candidate_receipt_is_not_a_governed_non_smoke_PASS_run")

    baseline_loss = metric_from(baseline, args.dataset)
    candidate_loss = metric_from(candidate, args.dataset)
    if baseline_loss is None:
        errors.append("baseline_best_val_loss_mean_missing")
    if candidate_loss is None:
        errors.append("candidate_best_val_loss_mean_missing")

    improvement_pct = None
    if baseline_loss is not None and candidate_loss is not None and baseline_loss > 0:
        improvement_pct = ((baseline_loss - candidate_loss) / baseline_loss) * 100.0

    if errors:
        verdict = "INVALID-RUN"
    elif improvement_pct is not None and improvement_pct >= args.min_improvement_pct:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    result = {
        "claim_id": args.claim_id,
        "verdict": verdict,
        "contract": "C5-0B nanoGPT_lite governed local research-loop comparison",
        "metric": {
            "name": "best_val_loss_mean_improvement_pct",
            "dataset": args.dataset,
            "baseline_best_val_loss_mean": baseline_loss,
            "candidate_best_val_loss_mean": candidate_loss,
            "improvement_pct": improvement_pct,
        },
        "threshold": {
            "min_improvement_pct": args.min_improvement_pct,
            "direction": "higher improvement is better; validation loss lower is better",
        },
        "evidence": {
            "baseline_receipt": str(args.baseline_receipt),
            "candidate_receipt": str(args.candidate_receipt),
            "rejects_smoke_receipts": True,
            "errors": errors,
        },
        "generated_at": "2026-06-29T00:00:00Z",
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if verdict in {"PASS", "FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())