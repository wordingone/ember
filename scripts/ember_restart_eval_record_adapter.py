#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Assemble one central-contract evaluation record from a finalized receipt."""
import argparse, hashlib, json, re
from pathlib import Path

SHA256 = re.compile(r"^[0-9a-f]{64}$")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--receipt", required=True, type=Path)
    p.add_argument("--benchmark-id", required=True)
    p.add_argument("--checkpoint-sha256", required=True)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    if not a.benchmark_id.strip() or not SHA256.fullmatch(a.checkpoint_sha256): p.error("benchmark id and checkpoint hash are required")
    payload = json.loads(a.receipt.read_text(encoding="utf-8"))
    if payload.get("result") != "MEASURED" or payload.get("subject_checkpoint_sha256") != a.checkpoint_sha256: p.error("receipt is not a matching measured result")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({"capability":payload.get("capability"),"benchmark_id":a.benchmark_id,"receipt_path":a.receipt.name,"sha256":hashlib.sha256(a.receipt.read_bytes()).hexdigest(),"subject_checkpoint_sha256":a.checkpoint_sha256}, sort_keys=True)+"\n", encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
