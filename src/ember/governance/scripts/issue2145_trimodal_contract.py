#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2145: protected image+audio+text contract over objects that are ALREADY admitted heldout.

Items = the 64 #2138 audio+transcript items in ascending ``item_id``; the image for item ``k`` is the
first image object (column order) of the #2130 frozen item at rank ``k`` when #2130's items are sorted
by ``gold_item_sha256``. No sampling, no N, no new admission: every referenced object must already be an
admitted heldout catalog member and absent from the admitted train set. The builder reads each payload,
verifies byte identity against the predecessor contracts, and freezes
``gold_item_sha256 = sha256(image_payload + audio_payload + transcript_text_payload)``.

Refusals are exceptions whose message starts with the refusal code; ``main`` writes a self-hashed
refusal receipt and exits 78 so a planted negative leaves evidence, never silence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

CONTRACT_SCHEMA = "ember-issue1947-protected-image-audio-text-contract-v1"
REFUSAL_SCHEMA = "ember-issue2145-trimodal-contract-refusal-v1"
AUDIO_TEXT_CONTRACT_SCHEMA = "ember-issue1947-protected-audio-text-contract-v1"
IMAGE_TEXT_CONTRACT_SCHEMA = "ember-protected-image-text-contract-v1"
CONNECTOR_SCHEMA = "corpus-connector-receipt-v1"
TASK_ID = "EXACT_IMAGE_AUDIO_TEXT_TRIPLE_IDENTITY"
CONSUMES = ["image_payload_bytes", "audio_payload_bytes", "transcript_text_payload_bytes"]
FORBIDDEN_INPUTS = ["speaker_metadata", "chapter_metadata", "mmmu_answer_dictionary", "prediction_custody"]
EXPECTED_ITEM_COUNT = 64
IMAGE_TEXT_ITEM_COUNT = 847
TEXT_KEYS = frozenset({"utterance_id", "transcript"})
SELECTION_RULE = (
    "items = the #2138 audio+text items in ascending item_id (64, frozen); image for item k = first image object "
    "(column order) of the #2130 frozen item at rank k when #2130 items are sorted by gold_item_sha256; no N, no "
    "sampling, no new admission; every referenced object is an admitted heldout catalog member and absent from the "
    "admitted train set; selected_set_sha256 = sha256 of the sorted 64 gold_item_sha256 values"
)
CLAIM_BOUNDARY = "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_self_hashed(path: Path, schema_version: str, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_UNREADABLE_REFUSED") from error
    body = dict(value) if isinstance(value, dict) else {}
    claimed = body.pop("self_sha256", None)
    if not body or claimed != sha(canonical(body)):
        raise ValueError(f"{label}_SELF_SHA256_DRIFT_REFUSED")
    if value.get("schema_version") != schema_version or value.get("result") != "PASS":
        raise ValueError(f"{label}_SCHEMA_REFUSED:{value.get('schema_version')}")
    return value, raw


def _object(value: object, label: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("sha256"), str)
        or not isinstance(value.get("byte_count"), int)
        or isinstance(value.get("byte_count"), bool)
        or not isinstance(value.get("media_type"), str)
    ):
        raise TypeError(f"{label}_OBJECT_SCHEMA_REFUSED")
    return {"sha256": value["sha256"], "byte_count": value["byte_count"], "media_type": value["media_type"]}


def audio_text_items(contract: dict[str, Any]) -> list[dict[str, Any]]:
    frozen = contract.get("frozen_items")
    if (
        contract.get("totality") != {"expected": EXPECTED_ITEM_COUNT, "observed": EXPECTED_ITEM_COUNT, "complete": True}
        or not isinstance(frozen, list)
        or len(frozen) != EXPECTED_ITEM_COUNT
    ):
        raise ValueError("AUDIO_TEXT_CONTRACT_TOTALITY_REFUSED")
    items = []
    for row in frozen:
        if not isinstance(row, dict) or not isinstance(row.get("item_id"), str) or not isinstance(row.get("gold_item_sha256"), str):
            raise TypeError("AUDIO_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        items.append({
            "item_id": row["item_id"],
            "audio_object": _object(row.get("audio_object"), "AUDIO_TEXT_AUDIO"),
            "item_text_object": _object(row.get("item_text_object"), "AUDIO_TEXT_TEXT"),
            "predecessor_gold_item_sha256": row["gold_item_sha256"],
        })
    if len({item["item_id"] for item in items}) != EXPECTED_ITEM_COUNT:
        raise ValueError("AUDIO_TEXT_CONTRACT_ITEM_ID_DUPLICATE_REFUSED")
    return sorted(items, key=lambda item: item["item_id"])


def image_text_ranked_images(contract: dict[str, Any]) -> list[dict[str, Any]]:
    frozen = contract.get("frozen_items")
    totality = contract.get("totality")
    if (
        not isinstance(frozen, list)
        or not isinstance(totality, dict)
        or totality.get("complete") is not True
        or totality.get("observed") != len(frozen)
        or len(frozen) < EXPECTED_ITEM_COUNT
    ):
        raise ValueError("IMAGE_TEXT_CONTRACT_TOTALITY_REFUSED")
    ranked = []
    for row in frozen:
        if not isinstance(row, dict) or not isinstance(row.get("gold_item_sha256"), str) or not isinstance(row.get("item_id"), str):
            raise TypeError("IMAGE_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        images = row.get("image_objects")
        if not isinstance(images, list) or not images:
            raise TypeError("IMAGE_TEXT_CONTRACT_ITEM_SCHEMA_REFUSED")
        ranked.append({
            "image_text_item_id": row["item_id"],
            "image_text_gold_item_sha256": row["gold_item_sha256"],
            "image_object": _object(images[0], "IMAGE_TEXT_IMAGE"),
        })
    if len({row["image_text_gold_item_sha256"] for row in ranked}) != len(ranked):
        raise ValueError("IMAGE_TEXT_CONTRACT_GOLD_DUPLICATE_REFUSED")
    ranked.sort(key=lambda row: row["image_text_gold_item_sha256"])
    return ranked[:EXPECTED_ITEM_COUNT]


def load_connectors(paths: list[Path]) -> tuple[dict[str, tuple[Path, dict[str, Any]]], dict[str, dict[str, Any]]]:
    """by_sha -> (custody root, file row); receipts -> raw sha -> {source_id, path, object_shas}."""
    by_sha: dict[str, tuple[Path, dict[str, Any]]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for path in paths:
        raw = path.read_bytes()
        try:
            receipt = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("TRIMODAL_CONNECTOR_UNREADABLE_REFUSED") from error
        if not isinstance(receipt, dict) or receipt.get("schema") != CONNECTOR_SCHEMA:
            observed = receipt.get("schema") if isinstance(receipt, dict) else None
            observed = observed or (receipt.get("schema_version") if isinstance(receipt, dict) else None)
            raise ValueError(f"TRIMODAL_FORBIDDEN_INPUT_REFUSED:source_schema:{observed}")
        digest = sha(raw)
        if digest in receipts:
            raise ValueError("TRIMODAL_CONNECTOR_DUPLICATE_REFUSED")
        root_value = receipt.get("dest_root")
        files = receipt.get("files")
        if not isinstance(root_value, str) or not isinstance(files, list) or not isinstance(receipt.get("source_id"), str):
            raise TypeError("TRIMODAL_CONNECTOR_TOTALITY_REFUSED")
        root = Path(root_value)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("TRIMODAL_CUSTODY_ROOT_MISSING_REFUSED")
        root = root.resolve()
        shas = set()
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("sha256"), str) or not isinstance(row.get("path"), str):
                raise TypeError("TRIMODAL_CONNECTOR_FILE_SCHEMA_REFUSED")
            if row["sha256"] in by_sha:
                raise ValueError("TRIMODAL_CONNECTOR_DUPLICATE_OBJECT_REFUSED")
            by_sha[row["sha256"]] = (root, row)
            shas.add(row["sha256"])
        receipts[digest] = {"source_id": receipt["source_id"], "path": str(path), "object_shas": shas}
    return by_sha, receipts


def bound_payload(by_sha: dict[str, tuple[Path, dict[str, Any]]], obj: dict[str, Any], item_id: str) -> bytes:
    entry = by_sha.get(obj["sha256"])
    if entry is None:
        raise ValueError(f"TRIMODAL_PAYLOAD_MISSING_REFUSED:{item_id}:{obj['sha256']}")
    root, row = entry
    if row.get("bytes") != obj["byte_count"]:
        raise ValueError(f"TRIMODAL_PAYLOAD_BYTE_COUNT_REFUSED:{item_id}:{obj['sha256']}")
    physical = (root / Path(row["path"])).resolve()
    try:
        physical.relative_to(root)
    except ValueError as error:
        raise ValueError(f"TRIMODAL_PAYLOAD_PATH_ESCAPE_REFUSED:{item_id}:{obj['sha256']}") from error
    if not physical.is_file():
        raise ValueError(f"TRIMODAL_PAYLOAD_MISSING_REFUSED:{item_id}:{obj['sha256']}")
    raw = physical.read_bytes()
    if len(raw) != obj["byte_count"] or sha(raw) != obj["sha256"]:
        raise ValueError(f"TRIMODAL_PAYLOAD_IDENTITY_REFUSED:{item_id}:{obj['sha256']}")
    return raw


def catalog_binding(export_raw: bytes, dataset_ids: list[str], referenced: set[str]) -> dict[str, Any]:
    try:
        catalog = json.loads(export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("TRIMODAL_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list) or not dataset_ids:
        raise ValueError("TRIMODAL_CATALOG_EXPORT_SCHEMA_REFUSED")
    for dataset_id in dataset_ids:
        if not any(
            isinstance(row, dict) and row.get("kind") == "dataset_version" and row.get("id") == dataset_id and row.get("state") == "admitted"
            for row in records
        ):
            raise ValueError(f"TRIMODAL_HELDOUT_DATASET_MISSING_REFUSED:{dataset_id}")
    memberships = {row["id"]: row for row in records if isinstance(row, dict) and row.get("kind") == "membership"}
    membership_of_dataset = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict) and edge.get("kind") == "version_membership" and edge.get("from_id") in dataset_ids
    }
    object_edges: dict[str, set[str]] = {}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("kind") == "membership_object":
            object_edges.setdefault(edge["from_id"], set()).add(edge["to_id"])
    heldout_objects: set[str] = set()
    for membership_id in membership_of_dataset:
        row = memberships.get(membership_id)
        if row is None or row.get("split") != "heldout" or row.get("admission_state") != "admitted" or row.get("domain") not in {"image", "audio", "text"}:
            raise ValueError(f"TRIMODAL_HELDOUT_MEMBERSHIP_STATE_REFUSED:{membership_id}")
        heldout_objects |= object_edges.get(membership_id, set())
    expected = {f"sha256:{digest}" for digest in referenced}
    if not expected <= heldout_objects:
        missing = sorted(expected - heldout_objects)[:3]
        raise ValueError(f"TRIMODAL_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:{len(expected & heldout_objects)}/{len(expected)}:{missing}")
    train_objects: set[str] = set()
    for membership_id, row in memberships.items():
        if row.get("split") == "train" and row.get("admission_state") == "admitted":
            train_objects |= object_edges.get(membership_id, set())
    overlap = sorted(expected & train_objects)
    if overlap:
        raise ValueError(f"TRIMODAL_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{overlap[0]}")
    return {
        "dataset_ids": sorted(dataset_ids),
        "catalog_export_raw_sha256": sha(export_raw),
        "membership_count": len(membership_of_dataset),
        "referenced_object_count": len(expected),
        "object_set_sha256": sha(canonical(sorted(expected))),
        "train_exclusion": {"executed": True, "admitted_train_object_count": len(train_objects), "overlap_count": 0},
    }


def build_contract(
    *,
    audio_text_contract_path: Path,
    image_text_contract_path: Path,
    connector_paths: list[Path],
    catalog_export_path: Path,
    planted_negative: str | None = None,
) -> dict[str, Any]:
    audio_text, audio_text_raw = load_self_hashed(audio_text_contract_path, AUDIO_TEXT_CONTRACT_SCHEMA, "AUDIO_TEXT_CONTRACT")
    image_text, image_text_raw = load_self_hashed(image_text_contract_path, IMAGE_TEXT_CONTRACT_SCHEMA, "IMAGE_TEXT_CONTRACT")
    at_items = audio_text_items(audio_text)
    ranked_images = image_text_ranked_images(image_text)
    if planted_negative == "pair-drift":
        # one item's audio object swapped with its neighbour's: the (audio, text) pair no longer restates #2138
        at_items[0]["audio_object"], at_items[1]["audio_object"] = at_items[1]["audio_object"], at_items[0]["audio_object"]
    by_sha, receipts = load_connectors(connector_paths)
    predecessor_pairs = {
        row["item_id"]: (row["audio_object"]["sha256"], row["item_text_object"]["sha256"], row["gold_item_sha256"])
        for row in audio_text["frozen_items"]
    }
    frozen_items = []
    referenced: set[str] = set()
    used_receipts: set[str] = set()
    for item, ranked in zip(at_items, ranked_images):
        item_id = item["item_id"]
        image_raw = bound_payload(by_sha, ranked["image_object"], item_id)
        audio_raw = bound_payload(by_sha, item["audio_object"], item_id)
        text_raw = bound_payload(by_sha, item["item_text_object"], item_id)
        expected_pair = predecessor_pairs[item_id]
        if (
            (item["audio_object"]["sha256"], item["item_text_object"]["sha256"]) != expected_pair[:2]
            or sha(audio_raw + text_raw) != expected_pair[2]
        ):
            raise ValueError(f"TRIMODAL_PREDECESSOR_PAIR_DRIFT_REFUSED:{item_id}")
        try:
            text_payload = json.loads(text_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"TRIMODAL_FORBIDDEN_INPUT_REFUSED:item_text_unreadable:{item_id}") from error
        if not isinstance(text_payload, dict) or set(text_payload) != TEXT_KEYS or text_payload.get("utterance_id") != item_id:
            raise ValueError(f"TRIMODAL_FORBIDDEN_INPUT_REFUSED:item_text_shape:{item_id}")
        for obj in (ranked["image_object"], item["audio_object"], item["item_text_object"]):
            referenced.add(obj["sha256"])
            for digest, receipt in receipts.items():
                if obj["sha256"] in receipt["object_shas"]:
                    used_receipts.add(digest)
        frozen_items.append({
            "item_id": item_id,
            "image_text_item_id": ranked["image_text_item_id"],
            "image_object": ranked["image_object"],
            "audio_object": item["audio_object"],
            "item_text_object": item["item_text_object"],
            "gold_item_sha256": sha(image_raw + audio_raw + text_raw),
        })
    unused = sorted(set(receipts) - used_receipts)
    if unused:
        raise ValueError(f"TRIMODAL_CONNECTOR_EXTRANEOUS_REFUSED:{unused[0]}")
    if len(frozen_items) != EXPECTED_ITEM_COUNT or len(referenced) != 3 * EXPECTED_ITEM_COUNT:
        raise ValueError("TRIMODAL_ITEM_TOTALITY_REFUSED")
    dataset_ids = sorted(
        set(audio_text.get("catalog_binding", {}).get("dataset_ids", []))
        | set(image_text.get("catalog_binding", {}).get("dataset_ids", []))
    )
    export_raw = catalog_export_path.read_bytes()
    binding = catalog_binding(export_raw, dataset_ids, referenced)
    golds = sorted(item["gold_item_sha256"] for item in frozen_items)
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA,
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": TASK_ID,
            "consumes": list(CONSUMES),
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
            "prediction": "sha256(image_payload_bytes + audio_payload_bytes + transcript_text_payload_bytes)",
            "scorer": "exact_match(prediction, gold_item_sha256)",
        },
        "source": {
            "audio_text_contract_raw_sha256": sha(audio_text_raw),
            "audio_text_contract_self_sha256": audio_text["self_sha256"],
            "image_text_contract_raw_sha256": sha(image_text_raw),
            "image_text_contract_self_sha256": image_text["self_sha256"],
            "connector_receipt_raw_sha256s": sorted(receipts),
            "connector_receipts": {receipts[d]["source_id"]: d for d in sorted(receipts)},
            "license_sha256s": sorted({
                str(audio_text.get("source", {}).get("license_sha256")),
                str(image_text.get("source", {}).get("license_sha256")),
            }),
            "speaker_chapter_metadata_access": "identity_only; never_read_by_adapter",
            "mmmu_answer_dictionary_access": "never_read",
            "prediction_custody_access": "forbidden",
        },
        "selection_rule": SELECTION_RULE,
        "selected_set_sha256": sha(canonical(golds)),
        "referenced_object_set_sha256": sha(canonical(sorted(referenced))),
        "frozen_items": frozen_items,
        "totality": {"expected": EXPECTED_ITEM_COUNT, "observed": len(frozen_items), "complete": len(frozen_items) == EXPECTED_ITEM_COUNT},
        "catalog_binding": binding,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    contract["self_sha256"] = sha(canonical(contract))
    return contract


def write_new(path: Path, value: dict[str, Any]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-text-contract", type=Path, required=True)
    parser.add_argument("--image-text-contract", type=Path, required=True)
    parser.add_argument("--connector-receipt", type=Path, action="append", required=True)
    parser.add_argument("--catalog-export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--planted-negative", choices=["pair-drift"], default=None)
    args = parser.parse_args()
    try:
        contract = build_contract(
            audio_text_contract_path=args.audio_text_contract,
            image_text_contract_path=args.image_text_contract,
            connector_paths=list(args.connector_receipt),
            catalog_export_path=args.catalog_export,
            planted_negative=args.planted_negative,
        )
    except (OSError, TypeError, ValueError) as error:
        refusal = {
            "schema_version": REFUSAL_SCHEMA,
            "result": "PLANTED_NEGATIVE_REFUSED" if args.planted_negative else "REFUSED",
            "planted_negative": args.planted_negative,
            "reason": str(error),
            "claim_boundary": CLAIM_BOUNDARY,
        }
        refusal["self_sha256"] = sha(canonical(refusal))
        write_new(args.output, refusal)
        print(json.dumps({"result": refusal["result"], "reason": refusal["reason"]}, sort_keys=True))
        return 78
    raw = write_new(args.output, contract)
    print(json.dumps({
        "result": "PASS",
        "raw_sha256": sha(raw),
        "self_sha256": contract["self_sha256"],
        "selected_set_sha256": contract["selected_set_sha256"],
        "totality": contract["totality"],
        "train_exclusion": contract["catalog_binding"]["train_exclusion"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
