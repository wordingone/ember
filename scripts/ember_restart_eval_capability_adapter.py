#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit deterministic central-contract receipt envelopes for frozen evaluators."""
import argparse
import json
import re
from pathlib import Path

CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--capability", required=True, choices=CAPABILITIES)
    p.add_argument("--checkpoint-sha256", required=True)
    p.add_argument("--verifier-sha256", required=True)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    if not SHA256.fullmatch(a.checkpoint_sha256) or not SHA256.fullmatch(a.verifier_sha256):
        p.error("checkpoint and verifier hashes must be lowercase SHA-256")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({"capability": a.capability, "result": "MEASURED", "subject_checkpoint_sha256": a.checkpoint_sha256, "verifier_sha256": a.verifier_sha256}, sort_keys=True) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
