# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Adjudicate ember-sufficient-pretraining-v2 from training evidence bytes.

Evidence class: sufficient_pretraining. Invoked by scripts/ember_restart/contract.py as

    python -I sufficient-pretraining-verifier.py \
        --checkpoint-manifest <path> --criterion-id ember-sufficient-pretraining-v2 \
        --training-ledger <path> --stopping-evaluation <path> \
        --checkpoint-progression <path>

The numeric bar is not hardcoded here. It is read from the stopping evaluation's own
pre-registered `criterion` block, which is frozen and sha-pinned by the contract
before this verifier runs; a stopping evaluation that ships no pre-registered bar
fails closed. Hardcoding a threshold in the trust root would let an admission bar be
changed by editing the verifier, which is exactly the move the registry exists to
prevent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

CRITERION_ID = "ember-sufficient-pretraining-v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}: expected a finite number")
    return float(value)


def evidence_sha(node: object, field: str) -> str:
    if not isinstance(node, dict) or not isinstance(node.get("sha256"), str):
        raise ValueError(f"{field}: expected a sha256 binding")
    return node["sha256"]


def adjudicate(
    tokens_seen: int,
    genesis_loss: float,
    final_loss: float,
    checkpoint_count: int,
    criterion: object,
) -> str:
    """Return PASSED/FAILED against the stopping evaluation's pre-registered bar."""
    if not isinstance(criterion, dict):
        raise ValueError("stopping evaluation: pre-registered criterion block missing")
    if criterion.get("criterion_id") != CRITERION_ID:
        raise ValueError("stopping evaluation: criterion_id does not match the requested criterion")
    min_tokens = criterion.get("min_tokens_seen")
    min_checkpoints = criterion.get("min_checkpoint_count")
    max_final_loss = criterion.get("max_final_loss")
    min_loss_reduction = criterion.get("min_loss_reduction")
    for field, value in (
        ("min_tokens_seen", min_tokens),
        ("min_checkpoint_count", min_checkpoints),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"stopping evaluation criterion.{field}: expected a positive integer")
    max_final_loss = finite_number(max_final_loss, "stopping evaluation criterion.max_final_loss")
    min_loss_reduction = finite_number(
        min_loss_reduction, "stopping evaluation criterion.min_loss_reduction"
    )

    passed = (
        tokens_seen >= min_tokens
        and checkpoint_count >= min_checkpoints
        and final_loss <= max_final_loss
        and (genesis_loss - final_loss) >= min_loss_reduction
    )
    return "PASSED" if passed else "FAILED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--criterion-id", required=True)
    parser.add_argument("--training-ledger", required=True, type=Path)
    parser.add_argument("--stopping-evaluation", required=True, type=Path)
    parser.add_argument("--checkpoint-progression", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.criterion_id != CRITERION_ID:
        print(f"unsupported criterion: {args.criterion_id}", file=sys.stderr)
        return 1

    try:
        ledger = json.loads(args.training_ledger.read_text(encoding="utf-8"))
        stopping = json.loads(args.stopping_evaluation.read_text(encoding="utf-8"))
        progression = json.loads(args.checkpoint_progression.read_text(encoding="utf-8"))

        entries = progression.get("entries")
        if not isinstance(entries, list) or not entries:
            raise ValueError("checkpoint progression: expected a non-empty entries list")

        tokens_seen = ledger.get("tokens_seen")
        if not isinstance(tokens_seen, int) or isinstance(tokens_seen, bool) or tokens_seen < 1:
            raise ValueError("training ledger tokens_seen: expected a positive integer")
        gpu_hours = finite_number(ledger.get("gpu_hours"), "training ledger gpu_hours")
        modality_tokens = ledger.get("modality_tokens")
        if not isinstance(modality_tokens, dict):
            raise ValueError("training ledger modality_tokens: expected object")

        heldout_tokens = stopping.get("heldout_tokens")
        if (
            not isinstance(heldout_tokens, int)
            or isinstance(heldout_tokens, bool)
            or heldout_tokens < 1
        ):
            raise ValueError("stopping evaluation heldout_tokens: expected a positive integer")
        genesis_loss = finite_number(stopping.get("genesis_loss"), "stopping evaluation genesis_loss")
        final_loss = finite_number(stopping.get("final_loss"), "stopping evaluation final_loss")
        evidence = stopping.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("stopping evaluation evidence: expected object")

        result = adjudicate(
            tokens_seen,
            genesis_loss,
            final_loss,
            len(entries),
            stopping.get("criterion"),
        )

        attestation = {
            "criterion_id": CRITERION_ID,
            "result": result,
            "subject_checkpoint_sha256": sha256(args.checkpoint_manifest),
            "training_ledger_sha256": sha256(args.training_ledger),
            "stopping_evaluation_sha256": sha256(args.stopping_evaluation),
            "checkpoint_progression_sha256": sha256(args.checkpoint_progression),
            "tokens_seen": tokens_seen,
            "gpu_hours": ledger["gpu_hours"],
            "modality_tokens": modality_tokens,
            "checkpoint_count": len(entries),
            "genesis_checkpoint_sha256": evidence_sha(
                entries[0].get("checkpoint_manifest"), "progression entries[0].checkpoint_manifest"
            ),
            "terminal_checkpoint_sha256": evidence_sha(
                entries[-1].get("checkpoint_manifest"), "progression entries[-1].checkpoint_manifest"
            ),
            "heldout_tokens": heldout_tokens,
            "genesis_loss": stopping["genesis_loss"],
            "heldout_split_sha256": evidence_sha(evidence.get("heldout_split"), "evidence.heldout_split"),
            "heldout_harness_sha256": evidence_sha(evidence.get("harness"), "evidence.harness"),
            "heldout_protocol_sha256": evidence_sha(evidence.get("protocol"), "evidence.protocol"),
            "genesis_measurement_sha256": evidence_sha(
                evidence.get("genesis_measurement"), "evidence.genesis_measurement"
            ),
            "final_measurement_sha256": evidence_sha(
                evidence.get("final_measurement"), "evidence.final_measurement"
            ),
            "final_loss": stopping["final_loss"],
        }
    except (ValueError, KeyError, AttributeError, TypeError, json.JSONDecodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
