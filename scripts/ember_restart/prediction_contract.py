#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate and adapt checkpoint-bound raw predictions without capability credit."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "ember-owned-predictions-v1"
CLAIM_STATUS = "NON_ADMISSIBLE_RAW_PREDICTIONS"
CAPABILITIES = {"text", "image", "audio", "reasoning", "tool"}
STOP_REASONS = {"eos", "max_new_tokens", "stop_sequence"}
VOCAB_SIZE = 32_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ROOT_FIELDS = {
    "schema_version",
    "claim_status",
    "checkpoint_manifest_sha256",
    "model_config_sha256",
    "tokenizer_sha256",
    "inference_implementation_sha256",
    "benchmark",
    "decoding",
    "rows",
}
BENCHMARK_FIELDS = {
    "id",
    "version",
    "capability",
    "split_sha256",
    "protocol_sha256",
}
DECODING_FIELDS = {
    "strategy",
    "teacher_forcing",
    "max_new_tokens",
    "temperature",
    "top_p",
    "stop_token_ids",
}
ROW_FIELDS = {
    "id",
    "input_sha256",
    "generated_token_ids",
    "stop_reason",
    "output",
}
OUTPUT_FIELDS = {
    "text": {"kind", "text"},
    "transcript": {"kind", "text"},
    "choice": {"kind", "value"},
    "sql": {"kind", "sql"},
    "tool_call": {"kind", "name", "arguments"},
}
CAPABILITY_OUTPUTS = {
    "text": {"text"},
    "image": {"text", "choice"},
    "audio": {"text", "transcript"},
    "reasoning": {"text"},
    "tool": {"text", "sql", "tool_call"},
}
ADAPTER_CAPABILITIES = {
    "text": "text",
    "reasoning": "reasoning",
    "audio": "audio",
    "mmmu": "image",
    "spider": "tool",
    "tool": "tool",
}


class ContractError(ValueError):
    """A fail-closed prediction-contract violation."""


def _exact_fields(value: Any, expected: set[str], prefix: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{prefix}: expected object")
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    if missing:
        raise ContractError(f"{prefix}: missing field {missing[0]}")
    if unexpected:
        raise ContractError(f"{prefix}: unexpected field {unexpected[0]}")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ContractError(f"{field}: expected lowercase SHA-256")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field}: expected non-empty string")
    return value


def _validate_output(value: Any, capability: str, prefix: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{prefix}: expected object")
    kind = value.get("kind")
    if kind not in OUTPUT_FIELDS:
        raise ContractError(f"{prefix}.kind: unsupported output kind")
    output = _exact_fields(value, OUTPUT_FIELDS[kind], prefix)
    if kind not in CAPABILITY_OUTPUTS[capability]:
        raise ContractError(f"{prefix}.kind: {kind} is invalid for capability {capability}")
    if kind in {"text", "transcript"}:
        if not isinstance(output["text"], str):
            raise ContractError(f"{prefix}.text: expected string")
    elif kind == "choice":
        _nonempty_string(output["value"], f"{prefix}.value")
    elif kind == "sql":
        if not isinstance(output["sql"], str):
            raise ContractError(f"{prefix}.sql: expected string")
    else:
        _nonempty_string(output["name"], f"{prefix}.name")
        if not isinstance(output["arguments"], dict):
            raise ContractError(f"{prefix}.arguments: expected object")
    return output


def validate_predictions(value: Any) -> dict[str, Any]:
    envelope = _exact_fields(value, ROOT_FIELDS, "predictions")
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version: must equal {SCHEMA_VERSION}")
    if envelope["claim_status"] != CLAIM_STATUS:
        raise ContractError(f"claim_status: must equal {CLAIM_STATUS}")
    for field in (
        "checkpoint_manifest_sha256",
        "model_config_sha256",
        "tokenizer_sha256",
        "inference_implementation_sha256",
    ):
        _sha256(envelope[field], field)

    benchmark = _exact_fields(envelope["benchmark"], BENCHMARK_FIELDS, "benchmark")
    _nonempty_string(benchmark["id"], "benchmark.id")
    _nonempty_string(benchmark["version"], "benchmark.version")
    capability = benchmark["capability"]
    if capability not in CAPABILITIES:
        raise ContractError("benchmark.capability: unsupported capability")
    _sha256(benchmark["split_sha256"], "benchmark.split_sha256")
    _sha256(benchmark["protocol_sha256"], "benchmark.protocol_sha256")

    decoding = _exact_fields(envelope["decoding"], DECODING_FIELDS, "decoding")
    if decoding["strategy"] != "GREEDY_AUTOREGRESSIVE":
        raise ContractError("decoding.strategy: must equal GREEDY_AUTOREGRESSIVE")
    if decoding["teacher_forcing"] is not False:
        raise ContractError("decoding.teacher_forcing: must be false")
    max_new_tokens = decoding["max_new_tokens"]
    if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool) or max_new_tokens <= 0:
        raise ContractError("decoding.max_new_tokens: expected positive integer")
    if decoding["temperature"] != 0:
        raise ContractError("decoding.temperature: greedy decoding requires 0")
    if decoding["top_p"] != 1:
        raise ContractError("decoding.top_p: greedy decoding requires 1")
    stops = decoding["stop_token_ids"]
    if (
        not isinstance(stops, list)
        or not stops
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item < 0
            or item >= VOCAB_SIZE
            for item in stops
        )
        or len(stops) != len(set(stops))
    ):
        raise ContractError(
            f"decoding.stop_token_ids: expected unique token ids in [0, {VOCAB_SIZE})"
        )

    rows = envelope["rows"]
    if not isinstance(rows, list) or not rows:
        raise ContractError("rows: expected non-empty list")
    seen: set[str] = set()
    for index, raw_row in enumerate(rows):
        prefix = f"rows[{index}]"
        row = _exact_fields(raw_row, ROW_FIELDS, prefix)
        row_id = _nonempty_string(row["id"], f"{prefix}.id")
        if row_id in seen:
            raise ContractError(f"{prefix}.id: duplicate id {row_id}")
        seen.add(row_id)
        _sha256(row["input_sha256"], f"{prefix}.input_sha256")
        token_ids = row["generated_token_ids"]
        if (
            not isinstance(token_ids, list)
            or not token_ids
            or len(token_ids) > max_new_tokens
            or any(
                not isinstance(item, int)
                or isinstance(item, bool)
                or item < 0
                or item >= VOCAB_SIZE
                for item in token_ids
            )
        ):
            raise ContractError(
                f"{prefix}.generated_token_ids: expected 1..max_new_tokens integers in [0, {VOCAB_SIZE})"
            )
        stop_reason = row["stop_reason"]
        if stop_reason not in STOP_REASONS:
            raise ContractError(f"{prefix}.stop_reason: unsupported stop reason")
        if stop_reason in {"eos", "stop_sequence"} and token_ids[-1] not in stops:
            raise ContractError(
                f"{prefix}.stop_reason: last generated token must be a declared stop token"
            )
        if stop_reason == "max_new_tokens" and len(token_ids) != max_new_tokens:
            raise ContractError(
                f"{prefix}.stop_reason: max_new_tokens stop requires exactly "
                f"{max_new_tokens} generated tokens"
            )
        _validate_output(row["output"], capability, f"{prefix}.output")
    return envelope


def load_predictions(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"predictions: {exc}") from exc
    return validate_predictions(value)


def materialize(envelope: dict[str, Any], adapter: str) -> object:
    capability = envelope["benchmark"]["capability"]
    required = ADAPTER_CAPABILITIES[adapter]
    if capability != required:
        raise ContractError(f"adapter {adapter} requires capability {required}")
    rows = envelope["rows"]
    if adapter in {"text", "reasoning"}:
        if any(row["output"]["kind"] != "text" for row in rows):
            raise ContractError(f"adapter {adapter} requires text outputs")
        return [{"id": row["id"], "answer": row["output"]["text"]} for row in rows]
    if adapter == "audio":
        if any(row["output"]["kind"] != "transcript" for row in rows):
            raise ContractError("adapter audio requires transcript outputs")
        return [{"id": row["id"], "transcript": row["output"]["text"]} for row in rows]
    if adapter == "mmmu":
        if any(row["output"]["kind"] != "choice" for row in rows):
            raise ContractError("adapter mmmu requires choice outputs")
        return [{"id": row["id"], "prediction": row["output"]["value"]} for row in rows]
    if adapter == "spider":
        if any(row["output"]["kind"] != "sql" for row in rows):
            raise ContractError("adapter spider requires sql outputs")
        return [{"index": index, "sql": row["output"]["sql"]} for index, row in enumerate(rows)]
    if any(row["output"]["kind"] != "tool_call" for row in rows):
        raise ContractError("adapter tool requires tool_call outputs")
    return {
        row["id"]: {
            "name": row["output"]["name"],
            "arguments": row["output"]["arguments"],
        }
        for row in rows
    }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("predictions", type=Path)
    adapt = commands.add_parser("materialize")
    adapt.add_argument("predictions", type=Path)
    adapt.add_argument("--adapter", required=True, choices=tuple(ADAPTER_CAPABILITIES))
    adapt.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        envelope = load_predictions(args.predictions)
        if args.command == "materialize":
            _atomic_json(args.output, materialize(envelope, args.adapter))
            return 0
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"],
                "benchmark_id": envelope["benchmark"]["id"],
                "capability": envelope["benchmark"]["capability"],
                "row_count": len(envelope["rows"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
