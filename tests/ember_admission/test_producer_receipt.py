# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Path-free, content-addressed producer receipt coverage."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

from receipt import verify_producer_receipt, write_producer_receipt  # noqa: E402
from consumers import CONSUMER_COMMAND_CONTRACTS  # noqa: E402
from source_snapshot import SourceSnapshot  # noqa: E402


def test_receipt_is_content_addressed_and_discloses_no_host_path(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            content=b"checkpoint",
        ),
        "restart_model_config": SourceSnapshot(
            role="restart_model_config",
            relative_path="config.json",
            sha256=hashlib.sha256(b"{}").hexdigest(),
            content=b"{}",
        ),
    }

    result = write_producer_receipt(
        candidate,
        "candidate-one",
        snapshots,
        {
            "identity": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "returncode": 0,
                "stdout_sha256": "3" * 64,
                "validator_sha256": "1" * 64,
            },
            "restart": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "returncode": 0,
                "stdout_sha256": "4" * 64,
                "validator_sha256": "2" * 64,
            },
        },
    )

    receipt_path = candidate / "producer-receipts" / f"{result.receipt_sha256}.json"
    receipt_bytes = receipt_path.read_bytes()
    payload = json.loads(receipt_bytes)
    assert hashlib.sha256(receipt_bytes).hexdigest() == result.receipt_sha256
    assert payload["selected"] is False
    assert payload["loaded"] is False
    assert payload["training_started"] is False
    assert payload["claim_boundary"] == [
        "candidate_produced",
        "identity_consumer_accepted",
        "restart_consumer_accepted",
    ]
    assert payload["consumers"]["identity"]["command"] == list(
        CONSUMER_COMMAND_CONTRACTS["identity"]
    )
    assert str(tmp_path) not in receipt_bytes.decode("utf-8")
    assert result.candidate_sha256 == hashlib.sha256(
        json.dumps(
            {
                "producer_receipt_sha256": result.receipt_sha256,
                "role_sha256": {
                    role: snapshot.sha256
                    for role, snapshot in sorted(snapshots.items())
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def test_receipt_refuses_nonzero_or_malformed_consumer_authority(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            content=b"checkpoint",
        )
    }
    try:
        write_producer_receipt(
            candidate,
            "candidate-one",
            snapshots,
            {
                "identity": {
                    "accepted": True,
                    "returncode": 0,
                    "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                    "stdout_sha256": "3" * 64,
                    "validator_sha256": "1" * 64,
                },
                "restart": {
                    "accepted": True,
                    "returncode": 1,
                    "validator_sha256": "2" * 64,
                    "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                    "stdout_sha256": "4" * 64,
                },
            },
        )
    except ValueError as exc:
        assert str(exc) == "receipt.consumers"
    else:
        raise AssertionError("nonzero consumer result was accepted")


def test_written_receipt_drift_is_detected(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            content=b"checkpoint",
        )
    }
    result = write_producer_receipt(
        candidate,
        "candidate-one",
        snapshots,
        {
            "identity": {
                "accepted": True,
                "returncode": 0,
                "validator_sha256": "1" * 64,
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "stdout_sha256": "3" * 64,
            },
            "restart": {
                "accepted": True,
                "returncode": 0,
                "validator_sha256": "2" * 64,
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "stdout_sha256": "4" * 64,
            },
        },
    )
    assert verify_producer_receipt(candidate, result)
    receipt = candidate / "producer-receipts" / f"{result.receipt_sha256}.json"
    receipt.write_bytes(receipt.read_bytes() + b" ")
    assert not verify_producer_receipt(candidate, result)
