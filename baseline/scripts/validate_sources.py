#!/usr/bin/env python3
"""Validate the baseline source ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_IDS = {
    "modded-nanogpt",
    "babylm-2026",
    "mlcommons-algoperf",
    "nvidia-rtx-4090",
    "chinchilla",
    "mle-bench",
    "mlagentbench",
    "ai-scientist",
    "agent-openai-codex",
    "agent-anthropic-claude-code",
    "agent-nvidia-nemo-agent-toolkit",
    "deepseek-deepspec-dspark",
    "deepseek-open-infra-index",
    "sapient-hrm",
    "modded-nanotabpfn",
    "ai-scientist-v2",
    "bitnet",
    "kosmos-ai-scientist",
    "hrm-critical-frontier",
    "bitsandbytes-8bit-optimizers",
    "pytorch-activation-checkpointing",
    "pytorch-sdpa-flashattention",
    "nvidia-cutlass",
    "triton-language",
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_line"] = line_no
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("sources.jsonl"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    rows = load_jsonl(args.sources)
    ids = [row.get("id") for row in rows]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    missing = sorted(REQUIRED_IDS - set(ids))
    malformed = []
    for row in rows:
        for field in ("id", "kind", "url", "status"):
            if not row.get(field):
                malformed.append({"line": row.get("_line"), "id": row.get("id"), "missing_field": field})
        if not (row.get("access_date") or row.get("accessed")):
            malformed.append({"line": row.get("_line"), "id": row.get("id"), "missing_field": "access_date/accessed"})

    verdict = "PASS" if not duplicates and not missing and not malformed else "INVALID-RUN"
    result = {
        "verdict": verdict,
        "source_count": len(rows),
        "missing_required_ids": missing,
        "duplicate_ids": duplicates,
        "malformed": malformed,
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())