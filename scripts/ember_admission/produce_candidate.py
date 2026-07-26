#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Produce an immutable owned-admission candidate without selecting or loading it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from candidate import (
    publish_staged_candidate,
    quarantine_candidate,
    stage_candidate,
)
from consumers import (
    CONSUMER_COMMAND_CONTRACTS,
    run_identity_consumer,
    run_restart_consumer,
    snapshot_consumer_validators,
    verify_consumer_validators,
)
from descriptor import validate_descriptor
from receipt import verify_producer_receipt, write_producer_receipt
from source_snapshot import (
    resolve_workspace_descriptor,
    snapshot_descriptor,
    snapshot_sources,
    verify_descriptor_snapshot,
    verify_published_snapshots,
    verify_source_snapshots,
)


DESCRIPTOR_SCHEMA = "ember-owned-admission-input-v1"
DESCRIPTOR_KEYS = {"schema_version", "candidate_id", "roles"}
REQUIRED_ROLES = {
    "artifact_bundle",
    "checkpoint",
    "identity_trusted_verifier_registry",
    "identity_manifest",
    "receipt_bundle",
    "restart_model_config",
    "restart_run_manifest",
    "tensor_hashes",
    "tensor_manifest",
    "restart_trusted_verifier_registry",
}


class AdmissionProducerError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _DuplicateKey(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) != len({key for key, _ in pairs}):
        raise _DuplicateKey("duplicate JSON object key")
    return dict(pairs)


def _load_descriptor(content: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateKey) as exc:
        raise AdmissionProducerError("descriptor.invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != DESCRIPTOR_KEYS
        or payload.get("schema_version") != DESCRIPTOR_SCHEMA
    ):
        raise AdmissionProducerError("descriptor.schema")
    roles = payload.get("roles")
    if not isinstance(roles, list):
        raise AdmissionProducerError("descriptor.roles")
    role_names = {
        row.get("role")
        for row in roles
        if isinstance(row, dict) and isinstance(row.get("role"), str)
    }
    if not REQUIRED_ROLES.issubset(role_names):
        raise AdmissionProducerError("descriptor.roles")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        descriptor_path = resolve_workspace_descriptor(args.workspace, args.descriptor)
        descriptor_snapshot = snapshot_descriptor(args.workspace, descriptor_path)
        descriptor = _load_descriptor(descriptor_snapshot.content)
        validate_descriptor(descriptor)
        snapshots = snapshot_sources(args.workspace, descriptor)
        consumer_validators = snapshot_consumer_validators()
        candidate, published_paths, destination = stage_candidate(
            args.output_root,
            descriptor["candidate_id"],
            snapshots,
        )
    except (AdmissionProducerError, ValueError) as exc:
        code = exc.code if isinstance(exc, AdmissionProducerError) else str(exc)
        print(json.dumps({"code": code, "ok": False}, sort_keys=True))
        return 2

    identity_result = run_identity_consumer(published_paths, consumer_validators["identity"])
    if identity_result.returncode != 0:
        quarantine_candidate(candidate)
        print(json.dumps({"code": "identity.refused", "ok": False}, sort_keys=True))
        return 2
    restart_result = run_restart_consumer(published_paths, consumer_validators["restart"])
    if restart_result.returncode != 0:
        quarantine_candidate(candidate)
        print(json.dumps({"code": "restart.refused", "ok": False}, sort_keys=True))
        return 2
    if not verify_consumer_validators(consumer_validators):
        quarantine_candidate(candidate)
        print(json.dumps({"code": "consumer.validator_drift", "ok": False}, sort_keys=True))
        return 2
    if not verify_source_snapshots(
        args.workspace, snapshots
    ) or not verify_descriptor_snapshot(
        args.workspace, descriptor_snapshot
    ) or not verify_published_snapshots(published_paths, snapshots):
        quarantine_candidate(candidate)
        print(json.dumps({"code": "candidate.drift", "ok": False}, sort_keys=True))
        return 2

    receipt = write_producer_receipt(
        candidate,
        descriptor["candidate_id"],
        descriptor_snapshot,
        snapshots,
        {
            "identity": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "returncode": identity_result.returncode,
                "stdout_sha256": hashlib.sha256(
                    identity_result.stdout.encode("utf-8")
                ).hexdigest(),
                "validator_sha256": consumer_validators["identity"].sha256,
            },
            "restart": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "stdout_sha256": hashlib.sha256(
                    restart_result.stdout.encode("utf-8")
                ).hexdigest(),
                "returncode": restart_result.returncode,
                "validator_sha256": consumer_validators["restart"].sha256,
            },
        },
    )
    if not verify_source_snapshots(
        args.workspace, snapshots
    ) or not verify_descriptor_snapshot(
        args.workspace, descriptor_snapshot
    ) or not verify_consumer_validators(consumer_validators
    ) or not verify_published_snapshots(
        published_paths, snapshots
    ) or not verify_producer_receipt(candidate, receipt):
        quarantine_candidate(candidate)
        print(json.dumps({"code": "candidate.drift", "ok": False}, sort_keys=True))
        return 2

    try:
        candidate, published_paths = publish_staged_candidate(
            candidate,
            destination,
            snapshots,
        )
    except ValueError as exc:
        quarantine_candidate(candidate)
        print(json.dumps({"code": str(exc), "ok": False}, sort_keys=True))
        return 2
    if not verify_source_snapshots(
        args.workspace, snapshots
    ) or not verify_descriptor_snapshot(
        args.workspace, descriptor_snapshot
    ) or not verify_consumer_validators(consumer_validators
    ) or not verify_published_snapshots(
        published_paths, snapshots
    ) or not verify_producer_receipt(candidate, receipt):
        quarantine_candidate(candidate)
        print(json.dumps({"code": "candidate.drift", "ok": False}, sort_keys=True))
        return 2

    print(
        json.dumps(
            {
                "candidate_sha256": receipt.candidate_sha256,
                "candidate_id": descriptor["candidate_id"],
                "producer_receipt_sha256": receipt.receipt_sha256,
                "loaded": False,
                "ok": True,
                "selected": False,
                "training_started": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
