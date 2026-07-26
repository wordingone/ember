# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed, path-free admission producer receipts."""

from __future__ import annotations

import hashlib
import json
import re
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from consumers import CONSUMER_COMMAND_CONTRACTS
from source_snapshot import SourceSnapshot


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

@dataclass(frozen=True)
class ProducerReceiptResult:
    receipt_sha256: str
    candidate_sha256: str


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def write_producer_receipt(
    candidate: Path,
    candidate_id: str,
    snapshots: Mapping[str, SourceSnapshot],
    consumer_results: Mapping[str, Mapping[str, Any]],
) -> ProducerReceiptResult:
    if (
        set(consumer_results) != {"identity", "restart"}
        or any(
            set(result) != {
                "accepted",
                "command",
                "returncode",
                "stdout_sha256",
                "validator_sha256",
            }
            or result.get("command") != list(CONSUMER_COMMAND_CONTRACTS[name])
            or result.get("accepted") is not True
            or result.get("returncode") != 0
            or not isinstance(result.get("stdout_sha256"), str)
            or SHA256_RE.fullmatch(result["stdout_sha256"]) is None
            or not isinstance(result.get("validator_sha256"), str)
            or SHA256_RE.fullmatch(result["validator_sha256"]) is None
            for name, result in consumer_results.items()
        )
    ):
        raise ValueError("receipt.consumers")
    role_sha256 = {
        role: snapshot.sha256
        for role, snapshot in sorted(snapshots.items())
    }
    digest_join = hashlib.sha256(
        _canonical_bytes({"role_sha256": role_sha256})
    ).hexdigest()
    payload = {
        "schema_version": "ember-owned-admission-producer-receipt-v1",
        "candidate_id": candidate_id,
        "source_identities": role_sha256,
        "output_identities": role_sha256,
        "cross_consumer_digest_join_sha256": digest_join,
        "consumers": {
            name: dict(result)
            for name, result in sorted(consumer_results.items())
        },
        "claim_boundary": [
            "candidate_produced",
            "identity_consumer_accepted",
            "restart_consumer_accepted",
        ],
        "selected": False,
        "loaded": False,
        "training_started": False,
        "training_claim": False,
        "benchmark_claim": False,
        "capability_claim": False,
    }
    receipt_bytes = _canonical_bytes(payload)
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_root = candidate / "producer-receipts"
    receipt_root.mkdir()
    receipt_path = receipt_root / f"{receipt_sha256}.json"
    with receipt_path.open("xb") as handle:
        handle.write(receipt_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    candidate_sha256 = hashlib.sha256(
        json.dumps(
            {
                "producer_receipt_sha256": receipt_sha256,
                "role_sha256": role_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ProducerReceiptResult(
        receipt_sha256=receipt_sha256,
        candidate_sha256=candidate_sha256,
    )


def verify_producer_receipt(
    candidate: Path,
    result: ProducerReceiptResult,
) -> bool:
    receipt_path = (
        candidate
        / "producer-receipts"
        / f"{result.receipt_sha256}.json"
    )
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError:
        return False
    return hashlib.sha256(receipt_bytes).hexdigest() == result.receipt_sha256
