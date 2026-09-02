# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed, path-free admission producer receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.ember.governance.scripts.ember_admission.consumers import (
    CONSUMER_COMMAND_CONTRACTS,
    CONSUMER_ENTRYPOINTS,
)
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


def _identity(snapshot: SourceSnapshot) -> dict[str, Any]:
    return {
        "relative_path": snapshot.relative_path,
        "sha256": snapshot.sha256,
        "bytes": len(snapshot.content),
    }


def _valid_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.parts[0] != "producer-receipts"
    )


def _valid_identity(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"relative_path", "sha256", "bytes"}
        and _valid_relative_path(value.get("relative_path"))
        and isinstance(value.get("sha256"), str)
        and SHA256_RE.fullmatch(value["sha256"]) is not None
        and isinstance(value.get("bytes"), int)
        and not isinstance(value.get("bytes"), bool)
        and value["bytes"] >= 0
    )

def _valid_consumer_result(name: str, result: Any) -> bool:
    if not isinstance(result, dict) or set(result) != {
        "accepted",
        "command",
        "returncode",
        "stdout_sha256",
        "validator_sha256",
        "validator_closure",
    }:
        return False
    closure = result.get("validator_closure")
    if (
        name not in CONSUMER_COMMAND_CONTRACTS
        or result.get("command") != list(CONSUMER_COMMAND_CONTRACTS[name])
        or result.get("accepted") is not True
        or result.get("returncode") != 0
        or not isinstance(result.get("stdout_sha256"), str)
        or SHA256_RE.fullmatch(result["stdout_sha256"]) is None
        or not isinstance(result.get("validator_sha256"), str)
        or SHA256_RE.fullmatch(result["validator_sha256"]) is None
        or not isinstance(closure, dict)
        or not closure
        or not all(
            isinstance(relative, str)
            and _valid_identity(identity)
            and identity["relative_path"] == relative
            for relative, identity in closure.items()
        )
        or CONSUMER_ENTRYPOINTS[name] not in closure
        or closure[CONSUMER_ENTRYPOINTS[name]]["sha256"]
        != result["validator_sha256"]
    ):
        return False
    return True



def write_producer_receipt(
    candidate: Path,
    candidate_id: str,
    descriptor_snapshot: SourceSnapshot,
    snapshots: Mapping[str, SourceSnapshot],
    consumer_results: Mapping[str, Mapping[str, Any]],
) -> ProducerReceiptResult:
    if (
        set(consumer_results) != {"identity", "restart"}
        or any(not _valid_consumer_result(name, result)
               for name, result in consumer_results.items())
    ):
        raise ValueError("receipt.consumers")
    descriptor_identity = _identity(descriptor_snapshot)
    role_identities = {
        role: _identity(snapshot)
        for role, snapshot in sorted(snapshots.items())
    }
    if (
        descriptor_snapshot.role != "input_descriptor"
        or not _valid_identity(descriptor_identity)
        or not all(_valid_identity(value) for value in role_identities.values())
        or len({value["relative_path"] for value in role_identities.values()})
        != len(role_identities)
    ):
        raise ValueError("receipt.identities")
    digest_join = hashlib.sha256(
        _canonical_bytes({"output_identities": role_identities})
    ).hexdigest()
    payload = {
        "schema_version": "ember-owned-admission-producer-receipt-v1",
        "candidate_id": candidate_id,
        "source_identities": {
            "descriptor": descriptor_identity,
            "roles": role_identities,
        },
        "output_identities": role_identities,
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
                "descriptor_identity": descriptor_identity,
                "output_identities": role_identities,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ProducerReceiptResult(
        receipt_sha256=receipt_sha256,
        candidate_sha256=candidate_sha256,
    )


def _candidate_tree_matches(
    candidate: Path,
    output_identities: Mapping[str, Mapping[str, Any]],
    receipt_relative_path: str,
) -> bool:
    expected_files = {
        value["relative_path"] for value in output_identities.values()
    } | {receipt_relative_path}
    expected_directories = {"producer-receipts"}
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    try:
        for path in candidate.rglob("*"):
            relative = path.relative_to(candidate).as_posix()
            info = path.stat(follow_symlinks=False)
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or attributes & 0x400:
                return False
            if stat.S_ISREG(info.st_mode):
                actual_files.add(relative)
            elif stat.S_ISDIR(info.st_mode):
                actual_directories.add(relative)
            else:
                return False
    except OSError:
        return False
    return actual_files == expected_files and actual_directories == expected_directories


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
        payload = json.loads(receipt_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if (
        hashlib.sha256(receipt_bytes).hexdigest() != result.receipt_sha256
        or not isinstance(payload, dict)
        or receipt_bytes != _canonical_bytes(payload)
        or set(payload)
        != {
            "schema_version",
            "candidate_id",
            "source_identities",
            "output_identities",
            "cross_consumer_digest_join_sha256",
            "consumers",
            "claim_boundary",
            "selected",
            "loaded",
            "training_started",
            "training_claim",
            "benchmark_claim",
            "capability_claim",
        }
        or payload.get("schema_version")
        != "ember-owned-admission-producer-receipt-v1"
        or payload.get("claim_boundary")
        != [
            "candidate_produced",
            "identity_consumer_accepted",
            "restart_consumer_accepted",
        ]
        or any(
            payload.get(key) is not False
            for key in (
                "selected",
                "loaded",
                "training_started",
                "training_claim",
                "benchmark_claim",
                "capability_claim",
            )
        )
    ):
        return False
    sources = payload.get("source_identities")
    outputs = payload.get("output_identities")
    consumers = payload.get("consumers")
    if (
        not isinstance(sources, dict)
        or set(sources) != {"descriptor", "roles"}
        or not _valid_identity(sources.get("descriptor"))
        or not isinstance(sources.get("roles"), dict)
        or sources["roles"] != outputs
        or not isinstance(outputs, dict)
        or not outputs
        or not all(
            isinstance(role, str) and role and _valid_identity(identity)
            for role, identity in outputs.items()
        )
        or len({identity["relative_path"] for identity in outputs.values()})
        != len(outputs)
        or not isinstance(consumers, dict)
        or set(consumers) != {"identity", "restart"}
        or any(not _valid_consumer_result(name, result)
               for name, result in consumers.items())
    ):
        return False
    digest_join = hashlib.sha256(
        _canonical_bytes({"output_identities": outputs})
    ).hexdigest()
    if payload.get("cross_consumer_digest_join_sha256") != digest_join:
        return False
    for identity in outputs.values():
        path = candidate / Path(identity["relative_path"])
        try:
            content = path.read_bytes()
        except OSError:
            return False
        if (
            len(content) != identity["bytes"]
            or hashlib.sha256(content).hexdigest() != identity["sha256"]
        ):
            return False
    receipt_relative_path = f"producer-receipts/{result.receipt_sha256}.json"
    if not _candidate_tree_matches(candidate, outputs, receipt_relative_path):
        return False
    candidate_sha256 = hashlib.sha256(
        json.dumps(
            {
                "producer_receipt_sha256": result.receipt_sha256,
                "descriptor_identity": sources["descriptor"],
                "output_identities": outputs,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return candidate_sha256 == result.candidate_sha256
