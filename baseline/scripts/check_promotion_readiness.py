#!/usr/bin/env python3
"""Report whether the staging baseline is ready for dual-repo promotion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NOT_READY_STATUSES = {
    "needs_exact_spec_pin",
    "needs_local_zero_spend_subset",
    "needs_source_pin",
    "needs_metric_row",
    "draft",
}

REQUIRED_PATHS = [
    "README.md",
    "anchors.md",
    "sources.jsonl",
    "contracts/B0-modded-nanogpt-training-efficiency.md",
    "contracts/C1-4090-1B-feasibility.md",
    "contracts/C5-self-improvement-loop.md",
    "contracts/C6-C7-cli-goal-mode.md",
    "contracts/C8-agent-loop-baselines.md",
    "protocols/protocol-v0.md",
    "protocols/c5-zero-spend-subset-v0.md",
    "protocols/compute-spend-c5-baseline-readiness-v0.md",
    "schemas/verdict-schema.json",
    "scripts/emit_verdict.py",
    "scripts/check_line_endings.py",
    "scripts/check_c5_subset_static.py",
    "scripts/check_c5_baseline_readiness.py",
    "scripts/make_manifest.py",
    "scripts/validate_sources.py",
    "reports/report-v0.md",
    "line-endings/README.md",
]


def load_sources(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fail-on-not-ready", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    missing_paths = [path for path in REQUIRED_PATHS if not (root / path).exists()]
    sources = load_sources(root / "sources.jsonl") if (root / "sources.jsonl").exists() else []
    not_ready_sources = [
        {"id": row.get("id"), "status": row.get("status")}
        for row in sources
        if row.get("status") in NOT_READY_STATUSES or "needs" in str(row.get("status", ""))
    ]
    report_text = (root / "reports" / "report-v0.md").read_text(encoding="utf-8", errors="replace") if (root / "reports" / "report-v0.md").exists() else ""
    explicit_incomplete = "NOT COMPLETE" in report_text or "Missing Before Completion" in report_text
    ready = not missing_paths and not not_ready_sources and not explicit_incomplete
    result = {
        "ready_for_promotion": ready,
        "verdict": "PASS" if ready else "INVALID-RUN",
        "root": str(root),
        "missing_paths": missing_paths,
        "not_ready_sources": not_ready_sources,
        "report_declares_incomplete": explicit_incomplete,
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    if args.fail_on_not_ready and not ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())