# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate Ember Lab cleanup evidence for the #675 governed event.

The validator has no deletion capability.  Ember Lab remains the sole cleanup
authority; this module only converts its closed evidence into a path-free,
non-credit receipt after all terminal prerequisites already exist.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


_TOP_FIELDS = {
    "schema_version",
    "job_id",
    "authority",
    "preconditions",
    "deleted",
    "post_delete_absent",
    "preserved",
    "cleanup_exit_code",
}
_PRECONDITIONS = {
    "terminal_receipt_sha256",
    "consumer_receipt_sha256",
    "independent_review_receipt_sha256",
}
_PRESERVED = {
    "seed_checkpoint_sha256",
    "threshold_sha256",
    "historical_receipts_index_sha256",
}
_ROW_FIELDS = {"logical_class", "pre_delete_sha256", "bytes"}
_CLASSES = ("temp", "tmp", "torch", "triton", "cuda", "hf", "xdg", "b3_fork")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class CleanupRefusal(ValueError):
    """Named refusal for unsafe, incomplete, or unreviewed cleanup evidence."""


def _refuse(code: str) -> None:
    raise CleanupRefusal(code)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def receipt_sha256(receipt: Mapping[str, Any]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hash_map(value: object, fields: set[str], code: str) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or any(not isinstance(item, str) or _SHA256.fullmatch(item) is None for item in value.values())
    ):
        _refuse(code)
    return dict(value)


def validate_cleanup_evidence(evidence_path: Path) -> dict[str, Any]:
    """Seal complete Ember Lab cleanup evidence without granting event credit."""

    try:
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("CLEANUP_EVIDENCE_UNREADABLE")
    if not isinstance(evidence, dict) or set(evidence) != _TOP_FIELDS:
        _refuse("CLEANUP_EVIDENCE_SCHEMA_INVALID")
    if evidence["schema_version"] != "q2-cleanup-evidence-v1":
        _refuse("CLEANUP_EVIDENCE_SCHEMA_INVALID")
    if not isinstance(evidence["job_id"], str) or _JOB_ID.fullmatch(evidence["job_id"]) is None:
        _refuse("CLEANUP_JOB_ID_INVALID")
    if evidence["authority"] != "ember-lab":
        _refuse("CLEANUP_AUTHORITY_INVALID")
    preconditions = _hash_map(
        evidence["preconditions"], _PRECONDITIONS, "CLEANUP_PRECONDITIONS_INVALID"
    )
    preserved = _hash_map(
        evidence["preserved"], _PRESERVED, "CLEANUP_PRESERVED_BINDINGS_INVALID"
    )
    if evidence["cleanup_exit_code"] != 0:
        _refuse("CLEANUP_FAILED")

    rows = evidence["deleted"]
    if not isinstance(rows, list) or len(rows) != len(_CLASSES):
        _refuse("CLEANUP_CLASS_SET_INVALID")
    deleted: list[dict[str, Any]] = []
    for expected_class, row in zip(_CLASSES, rows):
        if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
            _refuse("CLEANUP_ROW_SCHEMA_INVALID")
        if row["logical_class"] != expected_class:
            _refuse("CLEANUP_CLASS_SET_INVALID")
        if not isinstance(row["pre_delete_sha256"], str) or _SHA256.fullmatch(row["pre_delete_sha256"]) is None:
            _refuse("CLEANUP_PREDELETE_HASH_INVALID")
        if not isinstance(row["bytes"], int) or isinstance(row["bytes"], bool) or row["bytes"] <= 0:
            _refuse("CLEANUP_PREDELETE_SIZE_INVALID")
        deleted.append(dict(row))

    absent = evidence["post_delete_absent"]
    if not isinstance(absent, list) or absent != list(_CLASSES):
        _refuse("CLEANUP_POSTDELETE_INCOMPLETE")

    receipt: dict[str, Any] = {
        "schema_version": "q2-cleanup-receipt-v1",
        "job_id": evidence["job_id"],
        "authority": "ember-lab",
        "preconditions": preconditions,
        "deleted": deleted,
        "deleted_logical_classes": list(_CLASSES),
        "post_delete_absent": list(_CLASSES),
        "preserved": preserved,
        "cleanup_complete": True,
        "cleanup_evidence_sha256": _sha256_file(evidence_path),
        "event_credit": False,
        "scientific_credit": False,
        "issue_completion_credit": False,
        "no_new_parallel_authority": True,
    }
    receipt["receipt_sha256"] = receipt_sha256(receipt)
    return receipt
