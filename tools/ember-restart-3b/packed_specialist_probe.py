# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Governed observation-only census for issue #1413's fixed audio-64 pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import torch

from batch import decode_owned_packed_batch
from model import RestartDecoderConfig
from specialist_stream import canonical_record_bytes, open_specialist_stream
from training_acceleration import TrainingSignatureCensus, training_step_signature


_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_BOUNDARY = "STREAM_CONSTRUCTION_NOT_SUFFICIENT_PRETRAINING_OR_CAPABILITY"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 64hex")
    return value


def take_exact_pack(selection: object, *, cursor: object, pack_records: int) -> tuple[list[dict[str, Any]], dict[str, object]]:
    if type(pack_records) is not int or pack_records < 1:
        raise ValueError("pack_records must be positive")
    iterator_factory = getattr(selection, "iter_from", None)
    if not callable(iterator_factory):
        raise ValueError("packed census requires a sequential selection")
    iterator = iter(iterator_factory(cursor))
    records: list[dict[str, Any]] = []
    end_cursor: dict[str, object] | None = None
    for _ in range(pack_records):
        try:
            item = next(iterator)
        except StopIteration as error:
            raise ValueError("packed census selection ended before the fixed pack") from error
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], Mapping) or not isinstance(item[1], Mapping):
            raise ValueError("packed census selection yielded a malformed row")
        records.append(dict(item[0]))
        end_cursor = dict(item[1])
    if end_cursor is None:
        raise RuntimeError("packed census retained no end cursor")
    return records, end_cursor


def build_packed_density_receipt(
    *,
    selection_receipt: Mapping[str, object],
    records: list[dict[str, Any]],
    end_cursor: Mapping[str, object],
    batch_shape: Mapping[str, object],
    source_commit: str,
    stream_manifest_sha256: str,
    stream_build_receipt_sha256: str,
    model_config_sha256: str,
) -> dict[str, object]:
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("packed density source commit must be lowercase 40hex")
    for value, label in (
        (stream_manifest_sha256, "stream manifest"),
        (stream_build_receipt_sha256, "stream build receipt"),
        (model_config_sha256, "model config"),
    ):
        _require_sha(value, label)
    if selection_receipt.get("capability") != "audio" or selection_receipt.get("selection_rule_id") != "all_records_semantic_pretraining_v1":
        raise ValueError("packed density admits only the audio all-records selection")
    lengths = [len(record.get("token_ids", [])) for record in records]
    expected_shape = {
        "record_count": 64, "true_source_tokens": 960,
        "processed_padded_tokens": 960, "padding_tokens": 0,
    }
    if len(records) != 64 or lengths != [15] * 64 or any(batch_shape.get(key) != value for key, value in expected_shape.items()):
        raise ValueError("packed density requires the fixed zero-padding audio-64 shape")
    for field in ("record_order_sha256", "tokens_sha256", "pack_signature_sha256"):
        _require_sha(batch_shape.get(field), f"packed density {field}")
    selection_sha256 = hashlib.sha256(canonical_record_bytes(dict(selection_receipt))).hexdigest()
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1413-packed-density-v1",
        "status": "OBSERVED_NOT_ACTIVATED",
        "claim_boundary": "THROUGHPUT_SHAPE_ONLY_NO_TRAINING_OR_CAPABILITY_CLAIM",
        "stream_boundary": _BOUNDARY,
        "source_commit": source_commit,
        "model_config_sha256": model_config_sha256,
        "stream_manifest_sha256": stream_manifest_sha256,
        "stream_build_receipt_sha256": stream_build_receipt_sha256,
        "selection_receipt": dict(selection_receipt),
        "selection_receipt_sha256": selection_sha256,
        "end_selection_cursor": dict(end_cursor),
        "fixed_shape": {"capability": "audio", "pack_records": 64, "tokens_per_record": 15},
        "true_source_tokens": 960,
        "processed_padded_tokens": 960,
        "padding_tokens": 0,
        "max_step_seconds_for_1000_true_tps": 0.96,
        "record_order_sha256": batch_shape["record_order_sha256"],
        "tokens_sha256": batch_shape["tokens_sha256"],
        "pack_signature_sha256": batch_shape["pack_signature_sha256"],
        "quoted_records": [
            {
                "sample_id": record.get("sample_id"), "token_count": len(record["token_ids"]),
                "record_sha256": hashlib.sha256(canonical_record_bytes(record)).hexdigest(),
            }
            for record in records[:3]
        ],
    }
    receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def _write_no_replace(path: Path, value: Mapping[str, object]) -> tuple[str, str]:
    raw = json.dumps(dict(value), sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest(), str(value["self_sha256"])


def _open_selection(
    *, repo_root: Path, manifest_path: Path, manifest_sha256: str,
    build_receipt_path: Path, build_receipt_sha256: str,
) -> object:
    manifest_raw = manifest_path.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != manifest_sha256:
        raise ValueError("packed census stream manifest raw hash mismatch")
    manifest = json.loads(manifest_raw)
    stream = open_specialist_stream(
        repo_root=repo_root, manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
        expected_corpus_root_sha256=manifest["corpus_root_sha256"],
        manifest_bytes=manifest_raw,
    )
    return stream.prepare_execution_selection(
        capability="audio", selection_rule_id="all_records_semantic_pretraining_v1",
        build_receipt_path=build_receipt_path,
        expected_build_receipt_sha256=build_receipt_sha256,
    )


def run_census(args: argparse.Namespace, *, write: bool) -> dict[str, object]:
    repo_root = args.repo_root.resolve(strict=True)
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    selection = _open_selection(
        repo_root=repo_root, manifest_path=args.stream_manifest.resolve(strict=True),
        manifest_sha256=args.stream_manifest_sha256,
        build_receipt_path=args.stream_build_receipt.resolve(strict=True),
        build_receipt_sha256=args.stream_build_receipt_sha256,
    )
    records, end_cursor = take_exact_pack(selection, cursor=None, pack_records=args.pack_records)
    device = torch.device("cuda" if write else "cpu")
    if write and not torch.cuda.is_available():
        raise RuntimeError("packed signature census requires CUDA")
    config = RestartDecoderConfig.from_contract(config_path)
    batch = decode_owned_packed_batch(records, config, device=device, expected_records=args.pack_records)
    density = build_packed_density_receipt(
        selection_receipt=selection.receipt, records=records, end_cursor=end_cursor,
        batch_shape=batch, source_commit=args.source_commit,
        stream_manifest_sha256=args.stream_manifest_sha256,
        stream_build_receipt_sha256=args.stream_build_receipt_sha256,
        model_config_sha256=config_sha256,
    )
    if not write:
        return {"decision": "PREFLIGHT_ONLY", "density": density}
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    census = TrainingSignatureCensus(
        source_commit=args.source_commit, model_config_sha256=config_sha256,
        input_identity_sha256=str(density["selection_receipt_sha256"]),
        runner_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    census.observe(training_step_signature(batch, gradient_checkpointing=bool(config.gradient_checkpointing)))
    census_path = output_root / "training-signature-census.json"
    census_value = census.write_receipt(census_path)
    density_path = output_root / "packed-density-receipt.json"
    density_raw_sha256, density_self_sha256 = _write_no_replace(density_path, density)
    return {
        "result": "OBSERVED_NOT_ACTIVATED",
        "density_path": str(density_path), "density_raw_sha256": density_raw_sha256,
        "density_self_sha256": density_self_sha256,
        "census_path": str(census_path),
        "census_raw_sha256": hashlib.sha256(census_path.read_bytes()).hexdigest(),
        "census_self_sha256": census_value["self_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "census"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--stream-manifest", type=Path, required=True)
    parser.add_argument("--stream-manifest-sha256", required=True)
    parser.add_argument("--stream-build-receipt", type=Path, required=True)
    parser.add_argument("--stream-build-receipt-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--pack-records", type=int, required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.command == "census" and args.output_root is None:
        parser.error("census requires --output-root")
    if args.command == "preflight" and args.output_root is not None:
        parser.error("preflight cannot write --output-root")
    print(json.dumps(run_census(args, write=args.command == "census"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
