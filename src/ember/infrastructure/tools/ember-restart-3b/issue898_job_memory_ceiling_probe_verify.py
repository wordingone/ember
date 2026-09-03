#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Fail-closed adjudicator for the paired issue #898 Job Object memory probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any

SCHEMA = "ember-issue898-job-memory-ceiling-probe-verdict-v1"
OPERATIONAL_SCHEMA = "ember-lab-operational-receipt-v1"
OBSERVATION_SCHEMA = "ember-lab-job-memory-observation-v1"
JOB_OBJECT_MSG_JOB_MEMORY_LIMIT = 10
TOLERANCE_BYTES = 64 * 1024 * 1024


class Inconclusive(ValueError):
    pass


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Inconclusive(f"{label} is not an object")
    return value


def _exact_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Inconclusive(f"{label} is not an exact integer")
    return value


def _verified(payload: dict[str, Any]) -> bool:
    verification = _object(payload.get("verification"), "verification")
    return all(
        _object(verification.get(key), f"verification.{key}").get("verified") is True
        for key in ("job_object_membership", "process_identity", "lease")
    )


def _events(receipt: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    raw = receipt.get("events")
    if not isinstance(raw, list):
        raise Inconclusive("operational receipt events is not an array")
    selected: list[dict[str, Any]] = []
    for index, event_raw in enumerate(raw):
        event = _object(event_raw, f"events[{index}]")
        if event.get("kind") == kind:
            selected.append(_object(event.get("payload"), f"events[{index}].payload"))
    return selected


def _observation(
    payload: dict[str, Any], receipt: dict[str, Any], maximum: int, target: int
) -> tuple[int, int]:
    if payload.get("schema_version") != OBSERVATION_SCHEMA:
        raise Inconclusive("job-memory observation schema mismatch")
    if payload.get("scope") != "windows_job_object":
        raise Inconclusive("job-memory observation scope mismatch")
    root_pid = _exact_int(payload.get("root_pid"), "root_pid")
    offending_pid = _exact_int(payload.get("offending_pid"), "offending_pid")
    if root_pid <= 0 or offending_pid != root_pid or receipt.get("pid") != root_pid:
        raise Inconclusive("job-memory observation does not name the governed root process")
    if _exact_int(payload.get("maximum_job_memory_bytes"), "maximum") != maximum:
        raise Inconclusive("job-memory observation maximum mismatch")
    if _exact_int(payload.get("simulated_peak_commit_bytes"), "target") != target:
        raise Inconclusive("job-memory observation target mismatch")
    peak = _exact_int(payload.get("peak_job_memory_used_bytes"), "peak")
    if peak < 0 or not _verified(payload):
        raise Inconclusive("job-memory observation lacks verified custody")
    return peak, root_pid


def _load(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Inconclusive(f"cannot read operational receipt {path}: {error}") from error
    receipt = _object(value, "operational receipt")
    if receipt.get("schema") != OPERATIONAL_SCHEMA:
        raise Inconclusive("operational receipt schema mismatch")
    if receipt.get("scientific_capability_evidence") is not False:
        raise Inconclusive("operational receipt overclaims scientific evidence")
    if not isinstance(receipt.get("job_id"), str) or not receipt["job_id"]:
        raise Inconclusive("operational receipt lacks job_id")
    if receipt.get("state") not in {"exited", "failed"}:
        raise Inconclusive("operational receipt is not in an autonomous terminal state")
    logs = _object(receipt.get("logs"), "operational receipt logs")
    for stream in ("stdout", "stderr"):
        evidence = _object(logs.get(stream), f"logs.{stream}")
        digest = evidence.get("sha256")
        if (
            evidence.get("sealed") is not True
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise Inconclusive(f"operational receipt {stream} log is not hash-sealed")
    return receipt


def adjudicate_leg(
    path: pathlib.Path,
    *,
    maximum: int,
    signed_delta: int,
) -> dict[str, Any]:
    target = maximum + signed_delta
    if maximum <= 0 or signed_delta == 0 or target <= 0:
        raise Inconclusive("invalid composed probe quantities")
    receipt = _load(path)
    accounting = _events(receipt, "job_memory_accounting")
    limits = _events(receipt, "job_memory_limit_reached")
    if len(accounting) != 1:
        raise Inconclusive("expected exactly one terminal job_memory_accounting event")
    accounting_peak, root_pid = _observation(accounting[0], receipt, maximum, target)

    if signed_delta < 0:
        if receipt.get("exit_code") != 0:
            raise Inconclusive("negative control did not exit zero")
        if limits or accounting[0].get("limit_signal_observed") is not False:
            raise Inconclusive("negative control observed a limit signal")
        floor = max(target - TOLERANCE_BYTES, 0)
        if not floor <= accounting_peak < maximum:
            raise Inconclusive("negative control did not reach the near-wall target below the ceiling")
        leg = "negative_control"
    else:
        exit_code = receipt.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code == 0:
            raise Inconclusive("positive death leg did not terminate non-zero")
        if len(limits) != 1:
            raise Inconclusive("positive death leg lacks exactly one kernel limit event")
        limit_peak, limit_root_pid = _observation(limits[0], receipt, maximum, target)
        if limit_root_pid != root_pid:
            raise Inconclusive("positive leg event identities disagree")
        if (
            limits[0].get("kernel_message_code") != JOB_OBJECT_MSG_JOB_MEMORY_LIMIT
            or limits[0].get("signal_latched") is not True
            or accounting[0].get("limit_signal_observed") is not True
        ):
            raise Inconclusive("positive death leg lacks the exact latched Job Object signal")
        floor = max(maximum - TOLERANCE_BYTES, 0)
        if min(limit_peak, accounting_peak) < floor:
            raise Inconclusive("positive death leg peak is not within tolerance of the ceiling")
        leg = "positive_death"

    return {
        "leg": leg,
        "verdict": "PASS",
        "job_id": receipt["job_id"],
        "root_pid": root_pid,
        "exit_code": receipt.get("exit_code"),
        "maximum_job_memory_bytes": maximum,
        "signed_delta_bytes": signed_delta,
        "target_job_commit_bytes": target,
        "peak_job_memory_used_bytes": accounting_peak,
        "operational_receipt": str(path.resolve()),
        "operational_receipt_sha256": _sha256(path),
    }


def compose_verdict(
    negative_path: pathlib.Path,
    positive_path: pathlib.Path,
    *,
    maximum: int,
    maximum_absolute_delta: int,
    negative_delta: int,
    positive_delta: int,
) -> dict[str, Any]:
    if maximum_absolute_delta <= 0:
        raise Inconclusive("maximum absolute delta must be positive")
    if not (
        -maximum_absolute_delta <= negative_delta < 0 < positive_delta <= maximum_absolute_delta
    ):
        raise Inconclusive("signed probe deltas exceed the independent authority")
    negative = adjudicate_leg(negative_path, maximum=maximum, signed_delta=negative_delta)
    positive = adjudicate_leg(positive_path, maximum=maximum, signed_delta=positive_delta)
    if negative["job_id"] == positive["job_id"]:
        raise Inconclusive("probe legs reused one job identity")
    return {
        "schema_version": SCHEMA,
        "verdict": "PASS",
        "tolerance_bytes": TOLERANCE_BYTES,
        "maximum_job_memory_bytes": maximum,
        "maximum_absolute_delta_bytes": maximum_absolute_delta,
        "legs": [negative, positive],
        "scientific_capability_evidence": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-receipt", required=True, type=pathlib.Path)
    parser.add_argument("--positive-receipt", required=True, type=pathlib.Path)
    parser.add_argument("--maximum-job-memory-bytes", required=True, type=int)
    parser.add_argument("--maximum-absolute-delta-bytes", required=True, type=int)
    parser.add_argument("--negative-delta-bytes", required=True, type=int)
    parser.add_argument("--positive-delta-bytes", required=True, type=int)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        verdict = compose_verdict(
            args.negative_receipt,
            args.positive_receipt,
            maximum=args.maximum_job_memory_bytes,
            maximum_absolute_delta=args.maximum_absolute_delta_bytes,
            negative_delta=args.negative_delta_bytes,
            positive_delta=args.positive_delta_bytes,
        )
        payload = json.dumps(verdict, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as handle:
            handle.write(payload)
            handle.flush()
        print(json.dumps({"verdict": "PASS", "output": str(args.output.resolve()), "sha256": _sha256(args.output)}))
        return 0
    except (Inconclusive, FileExistsError) as error:
        print(json.dumps({"verdict": "INCONCLUSIVE", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
