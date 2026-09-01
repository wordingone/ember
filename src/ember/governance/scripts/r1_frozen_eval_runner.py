#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute the #1498 frozen R1 battery through the owned FROZEN_EVAL seat.

This module never loads a model or launches a server.  It admits only the
loopback-only owned serving authority, binds that authority to independently
rehashed checkpoint-manifest and shard bytes, executes each closed suite row
once with no tools, and publishes the exact suite plus a result receipt by one
directory rename.  Merely importing or testing this module carries no model,
GPU, capability, or result claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

try:
    from scripts.r1_cheap_probe_suite import SuiteRefusal, load_source_manifest
except ModuleNotFoundError:  # Direct ``python src/ember/governance/scripts/r1_frozen_eval_runner.py`` execution.
    from r1_cheap_probe_suite import SuiteRefusal, load_source_manifest


RESULT_SCHEMA = "r1-frozen-eval-results/v1"
_DIGEST_CHARS = frozenset("0123456789abcdef")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_RESULT_KEYS = {
    "schema",
    "eval_suite_id",
    "eval_suite_sha256",
    "checkpoint_manifest_sha256",
    "checkpoint_file_sha256s",
    "owned_identity",
    "rows",
    "results",
    "tool_access",
    "retry_count",
    "execution_claim",
    "result_credit",
    "claim_boundary",
    "receipt_sha256",
}
_RESULT_ROW_KEYS = {"row_id", "judge", "passed", "output", "output_sha256"}
_MAX_OUTPUT_BYTES = 4096
_RESULT_METRIC_KEYS = {
    "value",
    "n_items",
    "correct",
    "minimum_correct",
    "chance_rate",
    "passed",
}
_IDENTITY_KEYS = {
    "seat",
    "checkpoint_sha256",
    "model_name",
    "model_config_sha256",
    "tokenizer_sha256",
    "server_source_sha256",
}
_SEAT_MODEL_PREFIXES = {
    "OWNED_ADMITTED": "ember-owned:",
    "OWNED_DEVELOPMENT": "ember-owned-development:",
}
R1_ENDPOINT_SEATS = frozenset(_SEAT_MODEL_PREFIXES)
_CLAIM_BOUNDARY = (
    "MEASURED_NOT_ADJUDICATED; no capability, R1, training, or issue-closure credit"
)


class FrozenEvalRefusal(Exception):
    """Named pre-publication refusal; callers must not convert it to credit."""


class JsonTransport(Protocol):
    def get_json(self, url: str) -> dict: ...

    def post_json(self, url: str, payload: dict) -> dict: ...


class UrlTransport:
    """Small standard-library client; endpoint admission happens separately."""

    @staticmethod
    def _decode(response) -> dict:
        try:
            value = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FrozenEvalRefusal("ENDPOINT_RESPONSE_INVALID") from exc
        if not isinstance(value, dict):
            raise FrozenEvalRefusal("ENDPOINT_RESPONSE_INVALID")
        return value

    def get_json(self, url: str) -> dict:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return self._decode(response)
        except (OSError, urllib.error.URLError) as exc:
            raise FrozenEvalRefusal("ENDPOINT_UNREACHABLE") from exc

    def post_json(self, url: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return self._decode(response)
        except (OSError, urllib.error.URLError) as exc:
            raise FrozenEvalRefusal("ENDPOINT_REQUEST_FAILED") from exc


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _DIGEST_CHARS for character in value)
    )


def _canonical_bytes(value: dict, *, omit: str | None = None) -> bytes:
    payload = {key: item for key, item in value.items() if key != omit}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _load_suite(path: Path, expected_sha256: str) -> tuple[bytes, dict]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FrozenEvalRefusal("EVAL_SUITE_UNREADABLE") from exc
    if not _is_digest(expected_sha256) or _sha256_bytes(raw) != expected_sha256:
        raise FrozenEvalRefusal("EVAL_SUITE_SHA_MISMATCH")
    try:
        authority = load_source_manifest(path, expected_sha256)
    except SuiteRefusal as exc:
        code = "EVAL_SUITE_POLICY_INVALID" if "POLICY" in str(exc) else "EVAL_SUITE_SCHEMA_INVALID"
        raise FrozenEvalRefusal(code) from exc
    suite = {
        "eval_suite_id": authority["suite_id"],
        "context_limit_tokens": authority["context_limit_tokens"],
        "output_budget_tokens": authority["output_budget_tokens"],
        "probes": authority["probes"],
        "thresholds": authority["thresholds"],
        "tasks": [{
            "row_id": task["row_id"],
            "probe_id": task["probe_id"],
            "prompt": task["prompt"],
            "expected_output": task["expected_output"],
            "judge": task["judge"],
            "max_output_tokens": task["max_output_tokens"],
        } for task in authority["tasks"]],
    }
    return raw, suite


def _safe_shard(checkpoint_dir: Path, relative_value: object) -> Path:
    if not isinstance(relative_value, str) or not relative_value:
        raise FrozenEvalRefusal("CHECKPOINT_SHARD_PATH_INVALID")
    relative = Path(relative_value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise FrozenEvalRefusal("CHECKPOINT_SHARD_PATH_INVALID")
    try:
        root = checkpoint_dir.resolve(strict=True)
        current = root
        for part in relative.parts:
            current /= part
            stat_result = os.lstat(current)
            if current.is_symlink() or (
                getattr(stat_result, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise FrozenEvalRefusal("CHECKPOINT_SHARD_PATH_INVALID")
        resolved = current.resolve(strict=True)
    except FrozenEvalRefusal:
        raise
    except OSError as exc:
        raise FrozenEvalRefusal("CHECKPOINT_SHARD_PATH_INVALID") from exc
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise FrozenEvalRefusal("CHECKPOINT_SHARD_PATH_INVALID")
    return resolved


def _checkpoint_identity(checkpoint_dir: Path) -> tuple[str, dict[str, str]]:
    manifest_path = checkpoint_dir / "checkpoint-manifest.json"
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenEvalRefusal("CHECKPOINT_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("shards"), list) or not manifest["shards"]:
        raise FrozenEvalRefusal("CHECKPOINT_MANIFEST_INVALID")
    hashes: dict[str, str] = {}
    seen_paths: set[str] = set()
    for row in manifest["shards"]:
        if not isinstance(row, dict):
            raise FrozenEvalRefusal("CHECKPOINT_MANIFEST_INVALID")
        role, relative_value, declared = row.get("role"), row.get("path"), row.get("sha256")
        if (
            not isinstance(role, str)
            or not role
            or role in hashes
            or not isinstance(relative_value, str)
            or relative_value in seen_paths
            or not _is_digest(declared)
        ):
            raise FrozenEvalRefusal("CHECKPOINT_MANIFEST_INVALID")
        shard = _safe_shard(checkpoint_dir, relative_value)
        try:
            actual = _sha256_bytes(shard.read_bytes())
        except OSError as exc:
            raise FrozenEvalRefusal("CHECKPOINT_SHARD_UNREADABLE") from exc
        if actual != declared:
            raise FrozenEvalRefusal("CHECKPOINT_SHARD_SHA_MISMATCH")
        hashes[role] = actual
        seen_paths.add(relative_value)
    return _sha256_bytes(raw), hashes


def _endpoint_base(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise FrozenEvalRefusal("ENDPOINT_NOT_OWNED_LOOPBACK") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise FrozenEvalRefusal("ENDPOINT_NOT_OWNED_LOOPBACK")
    return f"http://127.0.0.1:{port}"


def _validate_identity(
    identity: object,
    checkpoint_sha256: str,
    expected_endpoint_seat: str = "OWNED_ADMITTED",
) -> dict:
    model_prefix = _SEAT_MODEL_PREFIXES.get(expected_endpoint_seat)
    if model_prefix is None:
        raise FrozenEvalRefusal("EXPECTED_ENDPOINT_SEAT_INVALID")
    if not isinstance(identity, dict):
        raise FrozenEvalRefusal("ENDPOINT_IDENTITY_INVALID")
    if (
        identity.get("mode") != "FROZEN_EVAL"
        or identity.get("seat") != expected_endpoint_seat
        or identity.get("checkpoint_sha256") != checkpoint_sha256
        or identity.get("model_name") != model_prefix + checkpoint_sha256[:12]
        or any(not _is_digest(identity.get(key)) for key in (
            "model_config_sha256", "tokenizer_sha256", "server_source_sha256"
        ))
    ):
        if isinstance(identity, dict) and identity.get("checkpoint_sha256") != checkpoint_sha256:
            raise FrozenEvalRefusal("ENDPOINT_CHECKPOINT_MISMATCH")
        raise FrozenEvalRefusal("ENDPOINT_IDENTITY_INVALID")
    return {key: identity[key] for key in sorted(_IDENTITY_KEYS)}


def _response_text(response: object, expected_identity: dict) -> str:
    if not isinstance(response, dict) or response.get("model") != expected_identity["model_name"]:
        raise FrozenEvalRefusal("RESPONSE_SHAPE_INVALID")
    response_identity = response.get("owned_identity")
    if not isinstance(response_identity, dict) or any(
        response_identity.get(key) != value for key, value in expected_identity.items()
    ):
        raise FrozenEvalRefusal("RESPONSE_IDENTITY_MISMATCH")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise FrozenEvalRefusal("RESPONSE_SHAPE_INVALID")
    message = choices[0].get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(message.get("content"), str):
        raise FrozenEvalRefusal("RESPONSE_SHAPE_INVALID")
    return message["content"]


def _normalized(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _probe_results(suite: dict, rows: list[dict]) -> dict:
    tasks = suite.get("tasks")
    probes = suite.get("probes")
    thresholds = suite.get("thresholds")
    minimums = thresholds.get("minimum_correct") if isinstance(thresholds, dict) else None
    if (
        not isinstance(tasks, list)
        or not isinstance(probes, list)
        or not isinstance(minimums, dict)
        or len(tasks) != len(rows)
    ):
        raise FrozenEvalRefusal("RESULT_RECEIPT_METRICS_INVALID")
    by_probe: dict[str, list[bool]] = {}
    for task, row in zip(tasks, rows):
        probe_id = task.get("probe_id") if isinstance(task, dict) else None
        if not isinstance(probe_id, str) or not isinstance(row, dict) or type(row.get("passed")) is not bool:
            raise FrozenEvalRefusal("RESULT_RECEIPT_METRICS_INVALID")
        by_probe.setdefault(probe_id, []).append(row["passed"])
    results: dict[str, dict] = {}
    for probe in probes:
        if not isinstance(probe, dict):
            raise FrozenEvalRefusal("RESULT_RECEIPT_METRICS_INVALID")
        probe_id = probe.get("probe_id")
        dataset = probe.get("dataset")
        outcomes = by_probe.pop(probe_id, None) if isinstance(probe_id, str) else None
        minimum = minimums.get(dataset) if isinstance(dataset, str) else None
        chance_rate = probe.get("chance_rate")
        if (
            not isinstance(outcomes, list)
            or len(outcomes) != probe.get("n_items")
            or not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or isinstance(chance_rate, bool)
            or not isinstance(chance_rate, (int, float))
        ):
            raise FrozenEvalRefusal("RESULT_RECEIPT_METRICS_INVALID")
        correct = sum(outcomes)
        results[probe_id] = {
            "value": correct / len(outcomes),
            "n_items": len(outcomes),
            "correct": correct,
            "minimum_correct": minimum,
            "chance_rate": chance_rate,
            "passed": correct >= minimum,
        }
    if by_probe:
        raise FrozenEvalRefusal("RESULT_RECEIPT_METRICS_INVALID")
    return results


def validate_results_receipt(
    receipt: object,
    *,
    suite: dict,
    suite_sha256: str,
    checkpoint_manifest_sha256: str,
    checkpoint_file_sha256s: dict[str, str],
    accepted_endpoint_seats: frozenset[str] = frozenset({"OWNED_ADMITTED"}),
) -> dict:
    """Reopen the exact result contract consumed by frontier/R1 authority."""

    if not isinstance(receipt, dict) or set(receipt) != _RESULT_KEYS:
        raise FrozenEvalRefusal("RESULT_RECEIPT_SCHEMA_INVALID")
    if (
        receipt.get("schema") != RESULT_SCHEMA
        or receipt.get("eval_suite_id") != suite.get("eval_suite_id")
        or receipt.get("eval_suite_sha256") != suite_sha256
        or receipt.get("checkpoint_manifest_sha256") != checkpoint_manifest_sha256
        or receipt.get("checkpoint_file_sha256s") != checkpoint_file_sha256s
        or receipt.get("tool_access") != "none"
        or receipt.get("retry_count") != 0
        or receipt.get("execution_claim") is not True
        or receipt.get("result_credit") is not False
        or receipt.get("claim_boundary") != _CLAIM_BOUNDARY
    ):
        raise FrozenEvalRefusal("RESULT_RECEIPT_BINDING_INVALID")
    if (
        not accepted_endpoint_seats
        or not accepted_endpoint_seats.issubset(R1_ENDPOINT_SEATS)
    ):
        raise FrozenEvalRefusal("RESULT_RECEIPT_IDENTITY_INVALID")
    identity = receipt.get("owned_identity")
    identity_seat = identity.get("seat") if isinstance(identity, dict) else None
    model_prefix = _SEAT_MODEL_PREFIXES.get(identity_seat)
    if (
        not isinstance(identity, dict)
        or set(identity) != _IDENTITY_KEYS
        or identity_seat not in accepted_endpoint_seats
        or model_prefix is None
        or identity.get("checkpoint_sha256") != checkpoint_manifest_sha256
        or identity.get("model_name") != model_prefix + checkpoint_manifest_sha256[:12]
        or any(
            not _is_digest(identity.get(key))
            for key in ("model_config_sha256", "tokenizer_sha256", "server_source_sha256")
        )
    ):
        raise FrozenEvalRefusal("RESULT_RECEIPT_IDENTITY_INVALID")
    tasks = suite.get("tasks")
    rows = receipt.get("rows")
    if not isinstance(tasks, list) or not isinstance(rows, list) or len(rows) != len(tasks):
        raise FrozenEvalRefusal("RESULT_RECEIPT_ROWS_INVALID")
    for task, row in zip(tasks, rows):
        output = row.get("output") if isinstance(row, dict) else None
        output_raw = output.encode("utf-8") if isinstance(output, str) else b""
        expected_passed = (
            _normalized(output) == _normalized(task.get("expected_output", ""))
            if isinstance(output, str) and isinstance(task, dict)
            else None
        )
        if (
            not isinstance(task, dict)
            or not isinstance(row, dict)
            or set(row) != _RESULT_ROW_KEYS
            or row.get("row_id") != task.get("row_id")
            or row.get("judge") != task.get("judge")
            or type(row.get("passed")) is not bool
            or not isinstance(output, str)
            or len(output_raw) > _MAX_OUTPUT_BYTES
            or not _is_digest(row.get("output_sha256"))
            or row.get("output_sha256") != _sha256_bytes(output_raw)
            or row.get("passed") is not expected_passed
        ):
            raise FrozenEvalRefusal("RESULT_RECEIPT_ROWS_INVALID")
    results = receipt.get("results")
    expected_results = _probe_results(suite, rows)
    if not isinstance(results, dict) or results != expected_results or any(
        not isinstance(metric, dict)
        or set(metric) != _RESULT_METRIC_KEYS
        or not math.isfinite(float(metric["value"]))
        or not math.isfinite(float(metric["chance_rate"]))
        for metric in results.values()
    ):
        raise FrozenEvalRefusal("RESULT_RECEIPT_METRICS_INVALID")
    if (
        not _is_digest(receipt.get("receipt_sha256"))
        or receipt["receipt_sha256"]
        != _sha256_bytes(_canonical_bytes(receipt, omit="receipt_sha256"))
    ):
        raise FrozenEvalRefusal("RESULT_RECEIPT_SELF_HASH_INVALID")
    return receipt


def _publish(output_dir: Path, suite_raw: bytes, receipt: dict) -> None:
    if output_dir.exists():
        raise FrozenEvalRefusal("OUTPUT_ALREADY_EXISTS")
    parent = output_dir.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=parent))
        (staging / "frozen-eval-suite.json").write_bytes(suite_raw)
        (staging / "frozen-eval-results.json").write_bytes(_canonical_bytes(receipt))
        os.replace(staging, output_dir)
    except OSError as exc:
        if "staging" in locals():
            shutil.rmtree(staging, ignore_errors=True)
        raise FrozenEvalRefusal("OUTPUT_PUBLICATION_FAILED") from exc


def execute_frozen_eval(
    *,
    suite_path: Path,
    expected_suite_sha256: str,
    checkpoint_dir: Path,
    endpoint: str,
    output_dir: Path,
    transport: JsonTransport | None = None,
    expected_endpoint_seat: str = "OWNED_ADMITTED",
) -> dict:
    """Run a closed suite once against the exact owned loaded checkpoint."""

    if output_dir.exists():
        raise FrozenEvalRefusal("OUTPUT_ALREADY_EXISTS")
    suite_raw, suite = _load_suite(suite_path, expected_suite_sha256)
    checkpoint_sha256, checkpoint_file_sha256s = _checkpoint_identity(checkpoint_dir)
    base = _endpoint_base(endpoint)
    client = transport if transport is not None else UrlTransport()
    identity = _validate_identity(
        client.get_json(base + "/v1/models"),
        checkpoint_sha256,
        expected_endpoint_seat,
    )
    rows = []
    for task in suite["tasks"]:
        request = {
            "model": identity["model_name"],
            "messages": [{"role": "user", "content": task["prompt"]}],
            "ember_frozen_row_id": task["row_id"],
            "ember_context_limit_tokens": suite["context_limit_tokens"],
            "max_tokens": task["max_output_tokens"],
            "stream": False,
        }
        text = _response_text(client.post_json(base + "/v1/chat/completions", request), identity)
        text_raw = text.encode("utf-8")
        if len(text_raw) > _MAX_OUTPUT_BYTES:
            raise FrozenEvalRefusal("RESPONSE_OUTPUT_TOO_LARGE")
        passed = _normalized(text) == _normalized(task["expected_output"])
        rows.append({
            "row_id": task["row_id"],
            "judge": task["judge"],
            "passed": passed,
            "output": text,
            "output_sha256": _sha256_bytes(text_raw),
        })
    results = _probe_results(suite, rows)
    receipt = {
        "schema": RESULT_SCHEMA,
        "eval_suite_id": suite["eval_suite_id"],
        "eval_suite_sha256": expected_suite_sha256,
        "checkpoint_manifest_sha256": checkpoint_sha256,
        "checkpoint_file_sha256s": checkpoint_file_sha256s,
        "owned_identity": identity,
        "rows": rows,
        "results": results,
        "tool_access": "none",
        "retry_count": 0,
        "execution_claim": True,
        "result_credit": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    receipt["receipt_sha256"] = _sha256_bytes(_canonical_bytes(receipt, omit="receipt_sha256"))
    validate_results_receipt(
        receipt,
        suite=suite,
        suite_sha256=expected_suite_sha256,
        checkpoint_manifest_sha256=checkpoint_sha256,
        checkpoint_file_sha256s=checkpoint_file_sha256s,
        accepted_endpoint_seats=frozenset({expected_endpoint_seat}),
    )
    _publish(output_dir, suite_raw, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--expected-suite-sha256", required=True)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--expected-endpoint-seat",
        choices=sorted(R1_ENDPOINT_SEATS),
        default="OWNED_ADMITTED",
    )
    args = parser.parse_args(argv)
    try:
        execute_frozen_eval(
            suite_path=args.suite,
            expected_suite_sha256=args.expected_suite_sha256,
            checkpoint_dir=args.checkpoint_dir,
            endpoint=args.endpoint,
            output_dir=args.output_dir,
            expected_endpoint_seat=args.expected_endpoint_seat,
        )
    except FrozenEvalRefusal as exc:
        print(f"R1_FROZEN_EVAL_REFUSED:{exc}")
        return 3
    print("R1_FROZEN_EVAL_RESULTS_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
