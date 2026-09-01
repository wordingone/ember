# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Re-derive an owned-tokenizer freeze attestation from the frozen bytes.

Evidence class: tokenizer_freeze. Invoked by src/ember/governance/scripts/ember_restart/contract.py as

    python -I tokenizer-freeze-verifier.py \
        --tokenizer <path> --training-script <path> --training-corpus-manifest <path>

Scope of the attestation, stated plainly because it bounds what the registry is
claiming: vocabulary size and every sha256 binding are measured directly from the
supplied bytes. `borrowed_tokenizer` is decided by scanning the tokenizer artifact
for external-origin markers. `frozen_pre_step0` is the one leg this verifier cannot
observe for itself -- a tokenizer file carries no record of when training started --
so it is inherited from the frozen corpus manifest's own declaration, and absence of
that declaration fails closed rather than defaulting to true.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Keys an HF-format tokenizer carries only when it was pulled from an external hub
# or derived from someone else's checkpoint.
EXTERNAL_ORIGIN_KEYS = ("name_or_path", "_name_or_path", "hub_id", "pretrained_model_name_or_path")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_external_origin(node: object) -> bool:
    if isinstance(node, dict):
        if any(key in node for key in EXTERNAL_ORIGIN_KEYS):
            return True
        return any(has_external_origin(value) for value in node.values())
    if isinstance(node, list):
        return any(has_external_origin(value) for value in node)
    return False


def vocab_size(tokenizer: dict) -> int:
    model = tokenizer.get("model")
    if isinstance(model, dict) and isinstance(model.get("vocab"), dict):
        added = tokenizer.get("added_tokens")
        added_ids = {
            entry["id"]
            for entry in (added if isinstance(added, list) else [])
            if isinstance(entry, dict) and isinstance(entry.get("id"), int)
        }
        return len(set(model["vocab"].values()) | added_ids)
    raise ValueError("tokenizer artifact does not carry a model.vocab table")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--training-script", required=True, type=Path)
    parser.add_argument("--training-corpus-manifest", required=True, type=Path)
    args = parser.parse_args(argv)

    tokenizer = json.loads(args.tokenizer.read_text(encoding="utf-8"))
    corpus = json.loads(args.training_corpus_manifest.read_text(encoding="utf-8"))

    frozen_pre_step0 = corpus.get("frozen_pre_step0")
    if frozen_pre_step0 is not True:
        print(
            "training corpus manifest does not declare frozen_pre_step0: true",
            file=sys.stderr,
        )
        return 1

    try:
        vocab = vocab_size(tokenizer)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    attestation = {
        "schema_version": "ember-owned-tokenizer-freeze-v1",
        "result": "FROZEN",
        "tokenizer_sha256": sha256(args.tokenizer),
        "vocab_size": vocab,
        "training_script_sha256": sha256(args.training_script),
        "training_corpus_sha256": sha256(args.training_corpus_manifest),
        "verifier_sha256": sha256(Path(__file__).resolve()),
        "borrowed_tokenizer": has_external_origin(tokenizer),
        "frozen_pre_step0": True,
    }
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
