#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from tokenizers import Tokenizer


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        Tokenizer.from_file(str(arguments.tokenizer))
    except Exception as error:
        parser.error(f"invalid tokenizer: {error}")
    checkpoint_sha256 = sha256(arguments.checkpoint_manifest)
    if checkpoint_sha256 != arguments.checkpoint_sha256:
        parser.error("checkpoint manifest SHA-256 does not match --checkpoint-sha256")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02C",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "result": "PREFLIGHT_ONLY",
        "checkpoint_sha256": checkpoint_sha256,
        "tokenizer_sha256": sha256(arguments.tokenizer),
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary_output = handle.name
    os.replace(temporary_output, arguments.output)


if __name__ == "__main__":
    main()
