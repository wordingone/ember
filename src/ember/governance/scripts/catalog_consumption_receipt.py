#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind one governed semantic run to the exact catalog objects and token count it consumed.

Consumer of ``catalog_train_stream`` v1 (#2122 / #2124): reads the runner's terminal result,
the disk-budget runner receipt, the pinned stream receipt, its per-object span file, and the
catalog export the staging was built from, and writes a self-hashed
``catalog-consumption-receipt-v1`` whose every number is cross-checked against the run's own
cursor.  A second subcommand turns that receipt into a ``data-catalog-import`` fragment that
binds one ``consumer_attempt`` per consumed dataset version.

Every refusal is a ``ConsumptionError`` whose first token is a stable UPPER_SNAKE code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog_train_stream import (  # noqa: E402
    StreamError,
    canonical,
    extended_spans,
    leakage_sets,
    read_shard_ledger,
    verify_ledger_genesis,
    verify_ledger_shards,
    self_hashed,
    sha,
    sha_file,
    verify_self_hash,
    write_new,
)

RECEIPT_SCHEMA = "catalog-consumption-receipt-v1"
FRAGMENT_SCHEMA = "ember-data-catalog-manifest-v1"
STREAM_RECEIPT_SCHEMA = "ember-catalog-train-stream-receipt-v1"
SPANS_SCHEMA = "ember-catalog-train-stream-binding-v1"
ATTEMPT_PREFIX = "attempt:issue2124-catalog-consumption"
# Each semantic episode reads sequence_length + 1 tokens (the last position's target) and
# advances the cursor by sequence_length, so the bytes the optimizer saw end one token past
# the cursor.
LOOKAHEAD_TOKENS = 1


class ConsumptionError(ValueError):
    """Refusal; the first token of the message is the stable code."""


def _load_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ConsumptionError(f"{code}: {path}") from error


def _int(value: object, code: str) -> int:
    if type(value) is not int or value < 0:
        raise ConsumptionError(code)
    return value


def _sha_arg(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ConsumptionError(code)
    return value


def runner_result_from_child_log(path: Path) -> dict[str, Any]:
    """The runner prints exactly one JSON object as its final stdout line."""
    result: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict) and "segment" in candidate:
                result = candidate
    if result is None:
        raise ConsumptionError("RUNNER_RESULT_MISSING_REFUSED")
    return result


def shard_prefix_tokens(stream_receipt: dict[str, Any]) -> list[int]:
    prefix = [0]
    for shard in stream_receipt["shards"]:
        prefix.append(prefix[-1] + _int(shard.get("n_tokens"), "STREAM_RECEIPT_SHARD_TOKENS_REFUSED"))
    return prefix


def consumed_spans(spans: list[dict[str, Any]], window_end: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous_end = 0
    for row in spans:
        start = _int(row.get("token_start"), "SPAN_ROW_REFUSED")
        end = _int(row.get("token_end"), "SPAN_ROW_REFUSED")
        if start != previous_end or end <= start:
            raise ConsumptionError("SPAN_CONTIGUITY_REFUSED")
        previous_end = end
        if start >= window_end:
            continue
        rows.append(
            {
                "sha256": _sha_arg(row.get("sha256"), "SPAN_ROW_REFUSED"),
                "token_start": start,
                "token_end": min(end, window_end),
                "partial": end > window_end,
            }
        )
    return rows


def build_receipt(
    *,
    runner_result: dict[str, Any],
    runner_receipt: dict[str, Any],
    run_spec: dict[str, Any],
    run_spec_sha256: str,
    stream_receipt: dict[str, Any],
    stream_receipt_raw_sha256: str,
    expected_stream_receipt_sha256: str,
    spans_document: dict[str, Any],
    spans_raw_sha256: str,
    catalog_export: dict[str, Any],
    catalog_export_raw_sha256: str,
    run_id: str,
    merged_head: str,
    shard_ledger: list[dict[str, Any]] | None = None,
    shard_ledger_raw_sha256: str | None = None,
    shards_root: Path | None = None,
) -> dict[str, Any]:
    if runner_receipt.get("schema_version") != 7:
        raise ConsumptionError("RUNNER_RECEIPT_SCHEMA_REFUSED")
    if runner_receipt.get("runner_exit_code") != 0 or runner_receipt.get("child_exit_code") != 0:
        raise ConsumptionError("RUNNER_EXIT_REFUSED")
    if stream_receipt.get("schema_version") != STREAM_RECEIPT_SCHEMA:
        raise ConsumptionError("STREAM_RECEIPT_SCHEMA_REFUSED")
    try:
        verify_self_hash(stream_receipt, "STREAM_RECEIPT")
    except StreamError as error:
        raise ConsumptionError(str(error)) from error
    if stream_receipt_raw_sha256 != expected_stream_receipt_sha256:
        raise ConsumptionError("STREAM_RECEIPT_SHA256_DRIFT_REFUSED")
    if spans_document.get("schema_version") != SPANS_SCHEMA:
        raise ConsumptionError("SPANS_SCHEMA_REFUSED")
    if spans_document.get("receipt_self_sha256") != stream_receipt.get("self_sha256"):
        raise ConsumptionError("SPANS_RECEIPT_BINDING_REFUSED")
    binding = stream_receipt.get("catalog_binding")
    if not isinstance(binding, dict):
        raise ConsumptionError("STREAM_RECEIPT_CATALOG_BINDING_REFUSED")
    if binding.get("catalog_export_sha256") != catalog_export_raw_sha256:
        raise ConsumptionError("CATALOG_EXPORT_SHA256_DRIFT_REFUSED")
    if len(merged_head) != 40 or any(c not in "0123456789abcdef" for c in merged_head):
        raise ConsumptionError("MERGED_HEAD_REFUSED")

    segment = runner_result.get("segment")
    if not isinstance(segment, dict):
        raise ConsumptionError("RUNNER_RESULT_SEGMENT_REFUSED")
    cursor = segment.get("data_cursor")
    if not isinstance(cursor, dict):
        raise ConsumptionError("RUNNER_RESULT_CURSOR_REFUSED")
    if runner_result.get("stream_receipt_sha256") != stream_receipt_raw_sha256:
        raise ConsumptionError("RUNNER_STREAM_RECEIPT_SHA256_REFUSED")
    if cursor.get("receipt_sha256") != stream_receipt_raw_sha256:
        raise ConsumptionError("CURSOR_STREAM_RECEIPT_SHA256_REFUSED")
    tokenizer_sha256 = _sha_arg(runner_result.get("tokenizer_sha256"), "RUNNER_TOKENIZER_SHA256_REFUSED")
    if cursor.get("tokenizer_sha256") != tokenizer_sha256 or binding.get("tokenizer_sha256", tokenizer_sha256) != tokenizer_sha256:
        raise ConsumptionError("TOKENIZER_SHA256_DRIFT_REFUSED")

    steps = _int(segment.get("global_step"), "RUNNER_RESULT_STEPS_REFUSED")
    tokens_seen = _int(segment.get("tokens_seen"), "RUNNER_RESULT_TOKENS_REFUSED")
    if cursor.get("global_step") != steps or cursor.get("tokens_seen") != tokens_seen:
        raise ConsumptionError("CURSOR_COUNTER_DRIFT_REFUSED")
    sequence_length = _int(run_spec.get("semantic_canary_sequence_length"), "RUN_SPEC_SEQUENCE_LENGTH_REFUSED")
    scope = run_spec.get("requested_scope")
    requested_steps = _int((scope or {}).get("optimizer_steps") if isinstance(scope, dict) else None, "RUN_SPEC_STEPS_REFUSED")
    if steps != requested_steps:
        raise ConsumptionError(f"STEP_COUNT_MISMATCH_REFUSED:{steps}!={requested_steps}")
    micro_batch = 1  # the semantic segment trains one episode per optimizer step
    expected_tokens = steps * micro_batch * sequence_length
    if tokens_seen != expected_tokens:
        raise ConsumptionError(f"CONSUMED_COUNT_MISMATCH_REFUSED:{tokens_seen}!={expected_tokens}")

    receipt_shards = [dict(shard) for shard in stream_receipt["shards"]]
    receipt_total = _int(stream_receipt.get("total_stream_tokens"), "STREAM_RECEIPT_TOTAL_REFUSED")
    spans = spans_document.get("spans")
    if not isinstance(spans, list) or not spans:
        raise ConsumptionError("SPANS_EMPTY_REFUSED")
    if spans[-1].get("token_end") != receipt_total:
        raise ConsumptionError("SPANS_TOTAL_MISMATCH_REFUSED")
    shards = receipt_shards
    ledger_block: dict[str, Any] | None = None
    if shard_ledger is not None:
        # The receipt is immutable; production past it lives in the ledger, whose first K rows must
        # restate the receipt's shards and whose later rows carry verified bytes and their spans.
        try:
            verify_ledger_genesis(shard_ledger, stream_receipt)
            if shards_root is None:
                raise ConsumptionError("SHARD_LEDGER_ROOT_REFUSED")
            verify_ledger_shards(shards_root, shard_ledger, start=len(receipt_shards))
        except StreamError as error:
            raise ConsumptionError(str(error)) from error
        shards = receipt_shards + [
            {"name": row["name"], "sha256": row["sha256"], "n_tokens": row["n_tokens"]} for row in shard_ledger[len(receipt_shards):]
        ]
        spans = extended_spans(spans, shard_ledger, len(receipt_shards))
        ledger_block = {"raw_sha256": shard_ledger_raw_sha256, "rows": len(shard_ledger), "rows_beyond_receipt": len(shard_ledger) - len(receipt_shards)}
    prefix = shard_prefix_tokens({"shards": shards})
    shard_index = _int(cursor.get("shard_index"), "CURSOR_SHARD_INDEX_REFUSED")
    token_offset = _int(cursor.get("token_offset"), "CURSOR_TOKEN_OFFSET_REFUSED")
    if shard_index >= len(shards) or token_offset > prefix[shard_index + 1] - prefix[shard_index]:
        raise ConsumptionError("CURSOR_OUT_OF_RANGE_REFUSED")
    cursor_position = prefix[shard_index] + token_offset
    if cursor_position != tokens_seen:
        raise ConsumptionError(f"CURSOR_POSITION_MISMATCH_REFUSED:{cursor_position}!={tokens_seen}")
    total_stream_tokens = prefix[-1]
    window_end = min(tokens_seen + LOOKAHEAD_TOKENS, total_stream_tokens)
    if tokens_seen > total_stream_tokens:
        raise ConsumptionError("CONSUMED_BEYOND_STREAM_REFUSED")
    consumed = consumed_spans(spans, window_end)
    if spans[-1].get("token_end") != total_stream_tokens:
        raise ConsumptionError("SPANS_TOTAL_MISMATCH_REFUSED")
    if ledger_block is not None:
        ledger_block["rows_consumed"] = min(shard_index + 1, len(shards))

    leakage = leakage_sets(catalog_export)
    objects = {
        row["sha256"]
        for row in catalog_export.get("records", [])
        if isinstance(row, dict) and row.get("kind") == "immutable_object"
    }
    admitted_train = {
        row["exact_sha256"]
        for row in catalog_export.get("records", [])
        if isinstance(row, dict)
        and row.get("kind") == "membership"
        and row.get("split") == "train"
        and row.get("admission_state") == "admitted"
    }
    consumed_hashes = [row["sha256"] for row in consumed]
    for digest in consumed_hashes:
        for name in ("heldout", "quarantined", "protected_eval"):
            if digest in leakage[name]:
                raise ConsumptionError(f"LEAKAGE_REFUSED:{name}:{digest}")
        if digest not in objects or digest not in admitted_train:
            raise ConsumptionError(f"CONSUMED_OBJECT_NOT_ADMITTED_TRAIN_REFUSED:{digest}")
    dataset_ids = binding.get("dataset_ids")
    if not isinstance(dataset_ids, list) or not dataset_ids or dataset_ids != sorted(dataset_ids):
        raise ConsumptionError("STREAM_RECEIPT_DATASET_IDS_REFUSED")

    return self_hashed(
        {
            "schema_version": RECEIPT_SCHEMA,
            "claim_boundary": "consumption accounting only; no capability, sufficiency, throughput, or campaign credit",
            "run": {
                "run_id": run_id,
                "merged_head": merged_head,
                "run_spec_sha256": run_spec_sha256,
                "launch_seed": runner_result.get("launch_seed"),
                "optimizer_steps": steps,
                "micro_batch": micro_batch,
                "sequence_length": sequence_length,
                "runner_exit_code": 0,
            },
            "stream": {
                "receipt_raw_sha256": stream_receipt_raw_sha256,
                "receipt_self_sha256": stream_receipt["self_sha256"],
                "spans_raw_sha256": spans_raw_sha256,
                "staging_manifest_raw_sha256": binding.get("staging_manifest_raw_sha256"),
                "tokenizer_sha256": tokenizer_sha256,
                "total_stream_tokens": total_stream_tokens,
                "receipt_total_stream_tokens": receipt_total,
                "receipt_shard_count": len(receipt_shards),
                "shards": shards,
                "shard_ledger": ledger_block,
            },
            "catalog": {
                "export_raw_sha256": catalog_export_raw_sha256,
                "dataset_ids": list(dataset_ids),
            },
            "consumption": {
                "window_token_start": 0,
                "window_token_end": window_end,
                "lookahead_tokens": window_end - tokens_seen,
                "consumed_token_count": tokens_seen,
                "final_cursor": {"shard_index": shard_index, "token_offset": token_offset, "position": cursor_position},
                "consumed_object_count": len(consumed),
                "partial_object_count": sum(1 for row in consumed if row["partial"]),
                "consumed_object_spans": consumed,
            },
            "leakage_assertion": {
                "result": "executed_pass",
                "consumed_hashes_checked": len(consumed_hashes),
                "heldout_hashes": len(leakage["heldout"]),
                "quarantined_hashes": len(leakage["quarantined"]),
                "protected_eval_hashes": len(leakage["protected_eval"]),
                "rule": "every consumed object sha256 is absent from heldout, quarantined-train, and protected-eval sets and carries an admitted train membership",
            },
        }
    )


def build_fragment(
    *,
    receipt: dict[str, Any],
    receipt_raw_sha256: str,
    catalog_export: dict[str, Any],
    evaluation_id: str,
    checkpoint_manifest_sha256: str,
    architecture_config_sha256: str,
    evaluator_sha256: str,
) -> dict[str, Any]:
    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ConsumptionError("CONSUMPTION_RECEIPT_SCHEMA_REFUSED")
    try:
        verify_self_hash(receipt, "CONSUMPTION_RECEIPT")
    except StreamError as error:
        raise ConsumptionError(str(error)) from error
    records_in_export = catalog_export.get("records", [])
    if not any(
        isinstance(row, dict) and row.get("kind") == "protected_eval" and row.get("id") == evaluation_id
        for row in records_in_export
    ):
        raise ConsumptionError("EVALUATION_ID_ABSENT_REFUSED")
    admitted_datasets = {
        row.get("id")
        for row in records_in_export
        if isinstance(row, dict) and row.get("kind") == "dataset_version" and row.get("state") == "admitted"
    }
    dataset_ids = receipt["catalog"]["dataset_ids"]
    for dataset_id in dataset_ids:
        if dataset_id not in admitted_datasets:
            raise ConsumptionError(f"DATASET_ABSENT_REFUSED:{dataset_id}")
    for label, value in (
        ("checkpoint", checkpoint_manifest_sha256),
        ("architecture", architecture_config_sha256),
        ("evaluator", evaluator_sha256),
    ):
        _sha_arg(value, f"{label.upper()}_SHA256_REFUSED")
    receipt_id = f"sha256:{receipt_raw_sha256}"
    records: list[dict[str, Any]] = [
        {
            "kind": "receipt",
            "id": receipt_id,
            "sha256": receipt_raw_sha256,
            "producing_authority": "training",
            "receipt_class": "consumer",
            "observed_at_ms": 0,
            "state": "accepted",
        }
    ]
    edges: list[dict[str, Any]] = []
    for ordinal, dataset_id in enumerate(dataset_ids):
        dataset_sha = dataset_id.rsplit(":", 1)[1]
        attempt_id = f"{ATTEMPT_PREFIX}:{receipt_raw_sha256[:32]}:{dataset_sha[:16]}"
        records.append(
            {
                "kind": "consumer_attempt",
                "id": attempt_id,
                "run_attempt_id": attempt_id,
                "model_sha256": architecture_config_sha256,
                "checkpoint_sha256": checkpoint_manifest_sha256,
                "tokenizer_sha256": receipt["stream"]["tokenizer_sha256"],
                "config_sha256": receipt["run"]["run_spec_sha256"],
                "source_tree_sha": receipt["run"]["merged_head"],
                "evaluator_sha256": evaluator_sha256,
                "state": "completed",
            }
        )
        for kind, to_kind, to_id in (
            ("consumer_dataset", "dataset_version", dataset_id),
            ("consumer_evaluation", "protected_eval", evaluation_id),
            ("consumer_receipt", "receipt", receipt_id),
        ):
            edges.append(
                {
                    "kind": kind,
                    "from_kind": "consumer_attempt",
                    "from_id": attempt_id,
                    "to_kind": to_kind,
                    "to_id": to_id,
                    "ordinal": 0,
                    "payload": {},
                }
            )
        del ordinal
    records.sort(key=lambda row: (row["kind"], row["id"]))
    edges.sort(key=lambda row: (row["kind"], row["from_id"], row["to_id"], row["ordinal"]))
    return {"schema_version": FRAGMENT_SCHEMA, "records": records, "edges": edges}


def _emit(args: argparse.Namespace) -> int:
    runner_result = (
        runner_result_from_child_log(args.child_log)
        if args.child_log is not None
        else _load_json(args.runner_result, "RUNNER_RESULT_UNREADABLE_REFUSED")
    )
    stream_raw = args.stream_receipt.read_bytes()
    spans_raw = args.spans.read_bytes()
    export_raw_sha = sha_file(args.catalog_export)
    ledger_rows = None
    ledger_raw_sha = None
    if args.shard_ledger is not None:
        try:
            ledger_rows = read_shard_ledger(args.shard_ledger)
        except StreamError as error:
            raise ConsumptionError(str(error)) from error
        ledger_raw_sha = sha_file(args.shard_ledger)
    receipt = build_receipt(
        runner_result=runner_result,
        runner_receipt=_load_json(args.runner_receipt, "RUNNER_RECEIPT_UNREADABLE_REFUSED"),
        run_spec=_load_json(args.run_spec, "RUN_SPEC_UNREADABLE_REFUSED"),
        run_spec_sha256=sha_file(args.run_spec),
        stream_receipt=json.loads(stream_raw),
        stream_receipt_raw_sha256=sha(stream_raw),
        expected_stream_receipt_sha256=args.expected_stream_receipt_sha256,
        spans_document=json.loads(spans_raw),
        spans_raw_sha256=sha(spans_raw),
        catalog_export=_load_json(args.catalog_export, "CATALOG_EXPORT_UNREADABLE_REFUSED"),
        catalog_export_raw_sha256=export_raw_sha,
        run_id=args.run_id,
        merged_head=args.merged_head,
        shard_ledger=ledger_rows,
        shard_ledger_raw_sha256=ledger_raw_sha,
        shards_root=(args.shards_root or args.stream_receipt.resolve().parent) if ledger_rows is not None else None,
    )
    raw = canonical(receipt) + b"\n"
    write_new(args.output, raw)
    print(json.dumps({"result": "CATALOG_CONSUMPTION_RECEIPTED", "output": str(args.output), "raw_sha256": sha(raw), "self_sha256": receipt["self_sha256"], "consumed_token_count": receipt["consumption"]["consumed_token_count"], "consumed_object_count": receipt["consumption"]["consumed_object_count"]}, sort_keys=True))
    return 0


def _fragment(args: argparse.Namespace) -> int:
    receipt_raw = args.receipt.read_bytes()
    fragment = build_fragment(
        receipt=json.loads(receipt_raw),
        receipt_raw_sha256=sha(receipt_raw),
        catalog_export=_load_json(args.catalog_export, "CATALOG_EXPORT_UNREADABLE_REFUSED"),
        evaluation_id=args.evaluation_id,
        checkpoint_manifest_sha256=sha_file(args.checkpoint_manifest),
        architecture_config_sha256=sha_file(args.architecture_config),
        evaluator_sha256=sha_file(Path(__file__).resolve()),
    )
    raw = canonical(fragment) + b"\n"
    write_new(args.output, raw)
    print(json.dumps({"result": "CATALOG_CONSUMPTION_FRAGMENT_WRITTEN", "output": str(args.output), "raw_sha256": sha(raw), "records": len(fragment["records"]), "edges": len(fragment["edges"])}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit", help="write catalog-consumption-receipt-v1 for one governed semantic run")
    source = emit.add_mutually_exclusive_group(required=True)
    source.add_argument("--child-log", type=Path, help="runner child log whose final JSON line is the semantic result")
    source.add_argument("--runner-result", type=Path, help="the semantic runner's result JSON object")
    emit.add_argument("--runner-receipt", type=Path, required=True, help="disk-budget runner receipt (schema 7)")
    emit.add_argument("--run-spec", type=Path, required=True)
    emit.add_argument("--stream-receipt", type=Path, required=True)
    emit.add_argument("--expected-stream-receipt-sha256", required=True)
    emit.add_argument("--spans", type=Path, required=True)
    emit.add_argument("--catalog-export", type=Path, required=True)
    emit.add_argument("--run-id", required=True)
    emit.add_argument("--merged-head", required=True)
    emit.add_argument("--shard-ledger", type=Path, default=None, help="append-only shard ledger beside the stream receipt (#2135)")
    emit.add_argument("--shards-root", type=Path, default=None, help="directory holding the shard files (default: the stream receipt's directory)")
    emit.add_argument("--output", type=Path, required=True)
    emit.set_defaults(func=_emit)
    fragment = sub.add_parser("fragment", help="write the data-catalog-import fragment binding consumer attempts")
    fragment.add_argument("--receipt", type=Path, required=True)
    fragment.add_argument("--catalog-export", type=Path, required=True)
    fragment.add_argument("--evaluation-id", required=True, help="existing protected_eval id the attempts bind")
    fragment.add_argument("--checkpoint-manifest", type=Path, required=True)
    fragment.add_argument("--architecture-config", type=Path, required=True)
    fragment.add_argument("--output", type=Path, required=True)
    fragment.set_defaults(func=_fragment)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConsumptionError as error:
        print(json.dumps({"result": "CATALOG_CONSUMPTION_REFUSED", "code": str(error)}, sort_keys=True))
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
