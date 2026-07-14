#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit the deterministic text receipt envelope consumed by the central contract."""

import argparse
import json
import re
from pathlib import Path


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--verifier-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not SHA256.fullmatch(args.checkpoint_sha256) or not SHA256.fullmatch(args.verifier_sha256):
        parser.error("checkpoint and verifier hashes must be lowercase SHA-256")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"capability": "text", "result": "MEASURED", "subject_checkpoint_sha256": args.checkpoint_sha256, "verifier_sha256": args.verifier_sha256}, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
