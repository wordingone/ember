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

from scripts.ember_admission.consumers import (  # noqa: E402
    CONSUMER_COMMAND_CONTRACTS,
    CONSUMER_ENTRYPOINTS,
)
from scripts.ember_admission.receipt import (  # noqa: E402
    verify_producer_receipt,
    write_producer_receipt,
)
from source_snapshot import SourceSnapshot  # noqa: E402

def _validator_closure(name: str, digest: str) -> dict[str, dict[str, object]]:
    relative = CONSUMER_ENTRYPOINTS[name]
    return {
        relative: {"relative_path": relative, "sha256": digest, "bytes": 1}
    }



def _descriptor_snapshot() -> SourceSnapshot:
    content = b'{"schema_version":"ember-owned-admission-input-v1"}\n'
    return SourceSnapshot(
        role="input_descriptor",
        relative_path="admission.json",
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def _materialize_outputs(
    candidate: Path,
    snapshots: dict[str, SourceSnapshot],
) -> None:
    for snapshot in snapshots.values():
        path = candidate / snapshot.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot.content)


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
    descriptor_snapshot = _descriptor_snapshot()
    _materialize_outputs(candidate, snapshots)

    result = write_producer_receipt(
        candidate,
        "candidate-one",
        descriptor_snapshot,
        snapshots,
        {
            "identity": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "returncode": 0,
                "stdout_sha256": "3" * 64,
                "validator_sha256": "1" * 64,
                "validator_closure": _validator_closure("identity", "1" * 64),
            },
            "restart": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "returncode": 0,
                "stdout_sha256": "4" * 64,
                "validator_sha256": "2" * 64,
                "validator_closure": _validator_closure("restart", "2" * 64),
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
    assert payload["source_identities"]["descriptor"] == {
        "relative_path": "admission.json",
        "sha256": descriptor_snapshot.sha256,
        "bytes": len(descriptor_snapshot.content),
    }
    assert payload["output_identities"]["checkpoint"]["relative_path"] == "checkpoint.bin"
    assert result.candidate_sha256 == hashlib.sha256(
        json.dumps(
            {
                "producer_receipt_sha256": result.receipt_sha256,
                "descriptor_identity": payload["source_identities"]["descriptor"],
                "output_identities": payload["output_identities"],
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
    _materialize_outputs(candidate, snapshots)
    try:
        write_producer_receipt(
            candidate,
            "candidate-one",
            _descriptor_snapshot(),
            snapshots,
            {
                "identity": {
                    "accepted": True,
                    "returncode": 0,
                    "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                    "stdout_sha256": "3" * 64,
                    "validator_sha256": "1" * 64,
                    "validator_closure": _validator_closure("identity", "1" * 64),
                },
                "restart": {
                    "accepted": True,
                    "returncode": 1,
                    "validator_sha256": "2" * 64,
                    "validator_closure": _validator_closure("restart", "2" * 64),
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
    _materialize_outputs(candidate, snapshots)
    result = write_producer_receipt(
        candidate,
        "candidate-one",
        _descriptor_snapshot(),
        snapshots,
        {
            "identity": {
                "accepted": True,
                "returncode": 0,
                "validator_sha256": "1" * 64,
                "validator_closure": _validator_closure("identity", "1" * 64),
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "stdout_sha256": "3" * 64,
            },
            "restart": {
                "accepted": True,
                "returncode": 0,
                "validator_sha256": "2" * 64,
                "validator_closure": _validator_closure("restart", "2" * 64),
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "stdout_sha256": "4" * 64,
            },
        },
    )
    assert verify_producer_receipt(candidate, result)
    receipt = candidate / "producer-receipts" / f"{result.receipt_sha256}.json"
    receipt.write_bytes(receipt.read_bytes() + b" ")
    assert not verify_producer_receipt(candidate, result)

    receipt.write_bytes(receipt.read_bytes()[:-1])
    (candidate / "unbound-extra.json").write_text("{}\n", encoding="utf-8")
    assert not verify_producer_receipt(candidate, result)
