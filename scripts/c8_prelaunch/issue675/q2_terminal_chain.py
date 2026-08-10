# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Conserve one #675 job identity across the complete terminal receipt chain.

This validator performs no execution, cleanup, publication, or issue closure.
It proves only that already-produced capture, operational, adjudication,
independent-review, and cleanup receipts are mutually bound.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Mapping


_SHA256 = re.compile(r"[0-9a-f]{64}")
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_REVIEW_FIELDS = {
    "schema_version",
    "job_id",
    "reviewer",
    "verdict",
    "reviewed",
    "no_new_parallel_authority",
    "receipt_sha256",
}
_REVIEWED_FIELDS = {
    "capture_file_sha256",
    "adjudication_file_sha256",
    "terminal_receipt_sha256",
}


class TerminalChainRefusal(ValueError):
    """Named refusal for a cross-run, unreviewed, or incomplete chain."""


def _refuse(code: str) -> None:
    raise TerminalChainRefusal(code)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def receipt_sha256(receipt: Mapping[str, Any]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    return _sha_bytes(_canonical(unsigned))


def _read(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse(code)
    if not isinstance(value, dict):
        _refuse(code)
    return value, raw


def _require_sha(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _refuse(code)
    return value


def _self_hash(value: Mapping[str, Any], field: str, code: str) -> str:
    supplied = _require_sha(value.get(field), code)
    unsigned = dict(value)
    unsigned.pop(field, None)
    if _sha_bytes(_canonical(unsigned)) != supplied:
        _refuse(code)
    return supplied


def _reopen_capture(
    capture_path: Path, dispatch_path: Path, terminal_path: Path
) -> dict[str, object]:
    """Invoke the canonical capture loader without creating a second schema."""
    module_path = Path(__file__).with_name("q2_capture_loader.py")
    try:
        spec = importlib.util.spec_from_file_location("q2_terminal_capture_loader", module_path)
        if spec is None or spec.loader is None:
            _refuse("TERMINAL_CHAIN_CAPTURE_ADMISSION_REFUSED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load_capture(capture_path, dispatch_path, terminal_path)
    except TerminalChainRefusal:
        raise
    except Exception:
        _refuse("TERMINAL_CHAIN_CAPTURE_ADMISSION_REFUSED")


def validate_terminal_chain(
    *,
    capture_path: Path,
    dispatch_path: Path,
    terminal_path: Path,
    adjudication_path: Path,
    review_path: Path,
    cleanup_path: Path,
) -> dict[str, Any]:
    """Return a path-free chain receipt, or refuse before terminal selection."""

    admitted = _reopen_capture(capture_path, dispatch_path, terminal_path)
    capture, capture_raw = _read(capture_path, "TERMINAL_CHAIN_CAPTURE_MALFORMED")
    job_id = admitted.get("run_id")
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        _refuse("TERMINAL_CHAIN_JOB_INVALID")
    capture_manifest_sha = admitted["capture_manifest_sha256"]
    capture_file_sha = _sha_bytes(capture_raw)

    terminal, terminal_raw = _read(terminal_path, "TERMINAL_CHAIN_TERMINAL_MALFORMED")
    if (
        terminal.get("schema") != "ember-lab-operational-receipt-v1"
        or terminal.get("job_id") != job_id
        or terminal.get("state") != "exited"
        or terminal.get("exit_code") != 0
        or terminal.get("scientific_capability_evidence") is not False
    ):
        _refuse("TERMINAL_CHAIN_TERMINAL_FAILED")
    terminal_sha = _sha_bytes(terminal_raw)
    if Path(terminal_path).name != f"{terminal_sha}.json":
        _refuse("TERMINAL_CHAIN_TERMINAL_CONTENT_ADDRESS_INVALID")

    adjudication, adjudication_raw = _read(
        adjudication_path, "TERMINAL_CHAIN_ADJUDICATION_MALFORMED"
    )
    _self_hash(
        adjudication, "receipt_sha256", "TERMINAL_CHAIN_ADJUDICATION_HASH_INVALID"
    )
    custody = adjudication.get("event_custody")
    if not isinstance(custody, dict):
        _refuse("TERMINAL_CHAIN_ADJUDICATION_CUSTODY_INVALID")
    if custody.get("job_id") != job_id:
        _refuse("TERMINAL_CHAIN_JOB_MISMATCH")
    if (
        custody.get("capture_manifest_sha256") != capture_manifest_sha
        or custody.get("terminal_receipt_sha256") != terminal_sha
        or custody.get("dispatch_manifest_sha256")
        != admitted["dispatch_manifest_sha256"]
        or custody.get("preflight_receipt_sha256")
        != admitted["preflight_receipt_sha256"]
        or custody.get("ember_lab_identity") != admitted["ember_lab_identity"]
    ):
        _refuse("TERMINAL_CHAIN_ADJUDICATION_CUSTODY_MISMATCH")
    if (
        adjudication.get("schema_version") != "q2-actual-update-successor-receipt-v1"
        or adjudication.get("verdict") not in {"NON_NULL_ORIENTATION", "INCONCLUSIVE_ORIENTATION"}
        or adjudication.get("no_new_parallel_authority") is not True
    ):
        _refuse("TERMINAL_CHAIN_ADJUDICATION_INVALID")
    credits = adjudication.get("credits")
    if (
        not isinstance(credits, dict)
        or credits.get("whole_step") is not False
        or credits.get("material_loss_bridge") is not False
    ):
        _refuse("TERMINAL_CHAIN_FALSE_CREDIT")
    adjudication_file_sha = _sha_bytes(adjudication_raw)

    review, review_raw = _read(review_path, "TERMINAL_CHAIN_REVIEW_MALFORMED")
    if set(review) != _REVIEW_FIELDS:
        _refuse("TERMINAL_CHAIN_REVIEW_SCHEMA_INVALID")
    _self_hash(review, "receipt_sha256", "TERMINAL_CHAIN_REVIEW_HASH_INVALID")
    if (
        review.get("schema_version") != "q2-independent-event-review-v1"
        or review.get("job_id") != job_id
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or review.get("verdict") != "PASS"
        or review.get("no_new_parallel_authority") is not True
    ):
        _refuse("TERMINAL_CHAIN_REVIEW_NOT_PASS")
    reviewed = review.get("reviewed")
    if not isinstance(reviewed, dict) or set(reviewed) != _REVIEWED_FIELDS:
        _refuse("TERMINAL_CHAIN_REVIEW_SCHEMA_INVALID")
    expected_reviewed = {
        "capture_file_sha256": capture_file_sha,
        "adjudication_file_sha256": adjudication_file_sha,
        "terminal_receipt_sha256": terminal_sha,
    }
    if reviewed != expected_reviewed:
        _refuse("TERMINAL_CHAIN_REVIEW_MISMATCH")
    review_file_sha = _sha_bytes(review_raw)

    cleanup, cleanup_raw = _read(cleanup_path, "TERMINAL_CHAIN_CLEANUP_MALFORMED")
    _self_hash(cleanup, "receipt_sha256", "TERMINAL_CHAIN_CLEANUP_HASH_INVALID")
    if (
        cleanup.get("schema_version") != "q2-cleanup-receipt-v1"
        or cleanup.get("job_id") != job_id
        or cleanup.get("authority") != "ember-lab"
        or cleanup.get("cleanup_complete") is not True
        or cleanup.get("event_credit") is not False
        or cleanup.get("scientific_credit") is not False
        or cleanup.get("issue_completion_credit") is not False
        or cleanup.get("no_new_parallel_authority") is not True
    ):
        _refuse("TERMINAL_CHAIN_CLEANUP_INVALID")
    expected_preconditions = {
        "terminal_receipt_sha256": terminal_sha,
        "consumer_receipt_sha256": adjudication_file_sha,
        "independent_review_receipt_sha256": review_file_sha,
    }
    if cleanup.get("preconditions") != expected_preconditions:
        _refuse("TERMINAL_CHAIN_CLEANUP_MISMATCH")
    cleanup_file_sha = _sha_bytes(cleanup_raw)

    result: dict[str, Any] = {
        "schema_version": "q2-terminal-chain-receipt-v1",
        "job_id": job_id,
        "verdict": adjudication["verdict"],
        "chain": {
            "capture_file_sha256": capture_file_sha,
            "capture_manifest_sha256": capture_manifest_sha,
            "terminal_receipt_sha256": terminal_sha,
            "adjudication_file_sha256": adjudication_file_sha,
            "independent_review_file_sha256": review_file_sha,
            "cleanup_file_sha256": cleanup_file_sha,
        },
        "event_chain_complete": True,
        "event_credit": False,
        "scientific_credit": False,
        "issue_completion_credit": False,
        "no_new_parallel_authority": True,
    }
    result["receipt_sha256"] = receipt_sha256(result)
    return result
