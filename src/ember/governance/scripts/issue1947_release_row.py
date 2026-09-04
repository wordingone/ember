#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Produce a durable named refusal for a non-executable protected release row."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROWS = (
    "E-MATRIX-TEXT-LANGUAGE",
    "E-MATRIX-IMAGE",
    "E-MATRIX-AUDIO",
    "E-MATRIX-IMAGE-TEXT",
    "E-MATRIX-AUDIO-TEXT",
    "E-MATRIX-IMAGE-AUDIO-TEXT",
    "E-MATRIX-REASONING",
    "E-MATRIX-TOOL-USE",
    "E-MATRIX-ROUTING-PATHWAY",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_self_hashed(path: Path, schema_version: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema_version") != schema_version:
        raise ValueError(f"SCHEMA_DRIFT:{path}")
    claimed = payload.get("self_sha256")
    body = dict(payload)
    body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError(f"SELF_HASH_DRIFT:{path}")
    return payload, raw


def build_refusal(row_id: str, missing_predicates: list[str]) -> dict[str, object]:
    if row_id not in ROWS:
        raise ValueError(f"UNKNOWN_RELEASE_ROW:{row_id}")
    if not missing_predicates or any(
        not value.startswith("MISSING_") for value in missing_predicates
    ):
        raise ValueError(f"INVALID_MISSING_PREDICATES:{row_id}")
    if len(missing_predicates) != len(set(missing_predicates)):
        raise ValueError(f"DUPLICATE_MISSING_PREDICATE:{row_id}")
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1947-release-row-refusal-v1",
        "result": "REFUSED",
        "row_id": row_id,
        "missing_predicates": missing_predicates,
        "claim_boundary": "NAMED_NONEXECUTABLE_ROW_REFUSAL_ONLY; NO EXECUTION CAPABILITY RELEASE ISSUE_OR_GOAL_CREDIT",
    }
    receipt["self_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    return receipt


def adapt_text(contract_path: Path, source_path: Path) -> dict[str, object]:
    contract, _ = load_self_hashed(
        contract_path, "ember-issue1947-protected-text-contract-totality-v1"
    )
    source, source_raw = load_self_hashed(
        source_path, "ember-issue1964-statistics-child-row-carrier-v1"
    )
    binding = contract.get("source_child_receipt")
    if not isinstance(binding, dict) or binding.get("raw_sha256") != sha(source_raw):
        raise ValueError("TEXT_SOURCE_RECEIPT_BINDING_DRIFT")
    source_row = source["row"]
    frozen_items = contract.get("frozen_items")
    if not isinstance(frozen_items, list) or len(frozen_items) != 1:
        raise ValueError("TEXT_CONTRACT_ITEM_TOTALITY_DRIFT")
    frozen = frozen_items[0]
    expected = {
        "item_id": source_row["row_id"],
        "gold_item_sha256": source_row["target_token_id_sha256"],
        "source_text_sha256": source_row["source_text_sha256"],
        "content_sha256": source_row["content_sha256"],
        "prefix_token_ids_sha256": source_row["prefix_token_ids_sha256"],
    }
    if frozen != expected or contract.get("totality", {}).get("complete") is not True:
        raise ValueError("TEXT_CONTRACT_ITEM_IDENTITY_DRIFT")
    return {
        "row_id": "E-MATRIX-TEXT-LANGUAGE",
        "items": [{
            "item_id": source_row["row_id"],
            "gold_item_sha256": source_row["target_token_id_sha256"],
            "prediction": source_row["predicted_token_id"],
            "score": 1.0 if source_row["exact_id_match"] is True else 0.0,
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    refuse = subparsers.add_parser("refuse")
    refuse.add_argument("--row-id", required=True, choices=ROWS)
    refuse.add_argument("--missing-predicate", action="append", required=True)
    refuse.add_argument("--receipt", type=Path, required=True)
    text = subparsers.add_parser("adapt-text")
    text.add_argument("--contract", type=Path, required=True)
    text.add_argument("--source-receipt", type=Path, required=True)
    text.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "adapt-text":
        row = adapt_text(args.contract, args.source_receipt)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with args.result.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(row, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"result": "COMPLETE", "row_id": row["row_id"]}, sort_keys=True))
        return 0
    receipt = build_refusal(args.row_id, args.missing_predicate)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"result": "REFUSED", "row_id": args.row_id}, sort_keys=True))
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
