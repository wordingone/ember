#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""catalog-train-stream v1 (#2122, front unit of #2121).

`stage`: turn the admitted train dataset versions of one accepted catalog export into a
deterministic staging manifest -- every admitted train object in (dataset id, sha256) order,
classified into an extractor or an excluded media class, with the physical custody of each
object resolved through the connector receipts the catalog itself binds, and the leakage
assertion (staged objects vs heldout, quarantined and protected-evaluation objects) executed.

`fill`: tokenize the staged objects in manifest order under the token-shards-v0 encode contract
and write the first K little-endian uint16 shards plus a receipt that
`semantic_stream.ManifestBoundTokenStream.from_receipt` accepts unchanged. The cache is
content-addressed by (tokenizer sha256, staging manifest sha256); re-running with the same
inputs rewrites nothing and re-verifies what is there.

`plan` (#2135): the coverage arithmetic over an EXISTING staging manifest -- per admitted train
dataset version, `staged + excluded + unresolved == unique admitted objects` (first-occurrence
attribution, the manifest's own order rule), every extractable-and-resolvable object present in
the manifest rows, and the catalog token total (admitted train membership windows under the frozen
tokenizer, deduplicated by object) -- plus the pretraining-budget accounting hook that binds those
tokens to EMBER-02 item 17 and records UNFROZEN until a frozen budget artifact exists.

`produce` (#2135): extend an EXISTING stream ahead of any cursor without touching the stream
receipt. The receipt stays immutable (its raw sha256 is the cursor's `receipt_sha256`); new shards
are recorded in an append-only, self-chained shard ledger beside it whose first K rows restate the
receipt's shards, each later row carrying the shard identity, its object spans, and the exact
tokenization resume state the next row starts from. Consumers that read the ledger (the loader's
boundary refresh, the consumption emitter) verify the chain and every shard's bytes; a run that
opened the receipt before the ledger grew sees only what it verified.

Claim boundary: producer/loader compatibility only. No optimizer consumes anything here.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import os
import struct
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator

STAGING_SCHEMA = "ember-catalog-train-staging-manifest-v1"
STREAM_RECEIPT_SCHEMA = "ember-catalog-train-stream-receipt-v1"
BINDING_SCHEMA = "ember-catalog-train-stream-binding-v1"
STREAM_TICKET = "TOKEN-SHARDS-V0"
ENCODE_CONTRACT = "added-token-matching-disabled-v1"
SEPARATOR_ID = 0
RESERVED_IDS = (1, 2, 3, 4, 5, 6, 7)
MAX_ID_LT = 32000
DEFAULT_SHARD_TOKENS = 268_435_456
TRAIN_DATASET_PREFIX = "dataset:issue1581-bulk-train:"
COVERAGE_SCHEMA = "catalog-train-coverage-receipt-v1"
BUDGET_SCHEMA = "catalog-pretraining-budget-v1"
BUDGET_CLAUSE_INDEX = 17
BUDGET_CLAUSE_MARKER = "token budget"
LEDGER_SCHEMA = "ember-catalog-train-shard-ledger-v1"
LEDGER_GENESIS_PREV = "0" * 64

EXTRACTORS: dict[str, str] = {
    "text/plain; charset=utf-8": "text_utf8",
    "text/markdown; charset=utf-8": "text_utf8",
    "text/x-rst; charset=utf-8": "text_utf8",
    "text/x-cuda; charset=utf-8": "text_utf8",
    "text/x-c++src; charset=utf-8": "text_utf8",
    "text/x-c++hdr; charset=utf-8": "text_utf8",
    "text/x-python; charset=utf-8": "text_utf8",
    "text/x-sh; charset=utf-8": "text_utf8",
    "application/x-sh; charset=utf-8": "text_utf8",
    "text/css; charset=utf-8": "text_utf8",
    "text/x-msdos-batch; charset=utf-8": "text_utf8",
    "application/yaml; charset=utf-8": "text_utf8",
    "application/x-ndjson": "ndjson_text_field",
    "application/x-ndjson+zstd": "ndjson_zstd_text_field",
}
NDJSON_TEXT_FIELDS = ("text", "content")


class StreamError(ValueError):
    """Every refusal carries a stable UPPER_SNAKE code as its first token."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def self_hashed(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "self_sha256"}
    body["self_sha256"] = sha(canonical(body))
    return body


def verify_self_hash(payload: dict[str, Any], code: str) -> None:
    body = {key: value for key, value in payload.items() if key != "self_sha256"}
    if payload.get("self_sha256") != sha(canonical(body)):
        raise StreamError(f"{code}_SELF_SHA256_DRIFT_REFUSED")


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


# --------------------------------------------------------------------------- custody
def custody_index_from_receipt(raw: bytes) -> tuple[str, dict[str, Path]]:
    """Map object sha256 -> physical file for the receipt schemas the catalog binds.

    Returns (receipt_raw_sha256, index). Unknown schemas refuse; the caller decides whether
    an unresolved object is a counted exclusion or a hard refusal.
    """

    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StreamError("CUSTODY_RECEIPT_UNREADABLE_REFUSED") from error
    if not isinstance(receipt, dict):
        raise StreamError("CUSTODY_RECEIPT_SCHEMA_REFUSED")
    index: dict[str, Path] = {}
    if receipt.get("schema") == "corpus-connector-receipt-v1":
        root = Path(str(receipt.get("dest_root", "")))
        files = receipt.get("files")
        if not root.is_absolute() or not isinstance(files, list):
            raise StreamError("CUSTODY_RECEIPT_TOTALITY_REFUSED")
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("sha256"), str) or not isinstance(row.get("path"), str):
                raise StreamError("CUSTODY_RECEIPT_FILE_SCHEMA_REFUSED")
            relative = PurePosixPath(row["path"].replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise StreamError(f"CUSTODY_PATH_ESCAPE_REFUSED:{row['sha256']}")
            index.setdefault(row["sha256"], root.joinpath(*relative.parts))
        return sha(raw), index
    if receipt.get("schema_version") == "ember-github-license-partition-receipt-v1":
        blob_root = receipt.get("blob_root")
        if not isinstance(blob_root, str):
            raise StreamError("CUSTODY_RECEIPT_TOTALITY_REFUSED")
        # The partition receipt is content-addressed: blobs/sha256/<xx>/<sha256> beside it.
        return sha(raw), {"__blob_root__": Path(blob_root)}
    raise StreamError(f"CUSTODY_RECEIPT_SCHEMA_REFUSED:{receipt.get('schema') or receipt.get('schema_version')}")


def resolve_physical(sha256: str, indexes: list[tuple[Path, dict[str, Path]]]) -> Path | None:
    for receipt_path, index in indexes:
        blob_root = index.get("__blob_root__")
        if blob_root is not None:
            candidate = (receipt_path.parent / blob_root / sha256[:2] / sha256)
            if candidate.is_file():
                return candidate
            continue
        candidate = index.get(sha256)
        if candidate is not None and candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------- stage
def _export_views(export: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    records = export.get("records")
    edges = export.get("edges")
    if not isinstance(records, list) or not isinstance(edges, list):
        raise StreamError("CATALOG_EXPORT_SCHEMA_REFUSED")
    objects = {row["sha256"]: row for row in records if isinstance(row, dict) and row.get("kind") == "immutable_object"}
    memberships = [row for row in records if isinstance(row, dict) and row.get("kind") == "membership"]
    datasets = {row["id"]: row for row in records if isinstance(row, dict) and row.get("kind") == "dataset_version"}
    return objects, memberships, datasets, edges


def leakage_sets(export: dict[str, Any]) -> dict[str, set[str]]:
    objects, memberships, _, edges = _export_views(export)
    # An ADMITTED non-train membership protects its bytes. A quarantined non-train membership is
    # the catalog's own resolution of a train/heldout overlap (the bytes were withdrawn from the
    # evaluation side and stay adjudicated train); it is counted, never treated as heldout.
    heldout = {
        row["exact_sha256"]
        for row in memberships
        if row.get("split") != "train" and row.get("admission_state") == "admitted"
    }
    # A quarantined TRAIN membership withdraws those bytes from training.
    quarantined = {
        row["exact_sha256"]
        for row in memberships
        if row.get("split") == "train" and row.get("admission_state") != "admitted"
    }
    adjudicated_overlap = {
        row["exact_sha256"]
        for row in memberships
        if row.get("split") != "train" and row.get("admission_state") != "admitted"
    }
    protected = {
        edge["to_id"].split(":", 1)[1]
        for edge in edges
        if isinstance(edge, dict) and edge.get("kind") == "evaluation_object" and isinstance(edge.get("to_id"), str)
    }
    return {
        "heldout": heldout,
        "quarantined": quarantined,
        "protected_eval": protected,
        "_adjudicated_overlap": adjudicated_overlap,
    }


def build_staging_manifest(
    *,
    export_raw: bytes,
    dataset_ids: list[str] | None,
    tokenizer_sha256: str,
    custody_receipts: list[tuple[Path, bytes]],
) -> dict[str, Any]:
    try:
        export = json.loads(export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StreamError("CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    objects, memberships, datasets, edges = _export_views(export)
    if dataset_ids is None:
        dataset_ids = sorted(
            identifier for identifier, row in datasets.items()
            if identifier.startswith(TRAIN_DATASET_PREFIX) and row.get("state") == "admitted"
        )
    if not dataset_ids:
        raise StreamError("TRAIN_DATASET_TOTALITY_REFUSED")
    for identifier in dataset_ids:
        row = datasets.get(identifier)
        if row is None or row.get("state") != "admitted":
            raise StreamError(f"TRAIN_DATASET_NOT_ADMITTED_REFUSED:{identifier}")
    wanted = set(dataset_ids)
    membership_ids_by_dataset: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if isinstance(edge, dict) and edge.get("kind") == "version_membership" and edge.get("from_id") in wanted:
            membership_ids_by_dataset[str(edge["from_id"])].add(str(edge["to_id"]))
    membership_by_id = {row["id"]: row for row in memberships}
    receipt_by_object: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if isinstance(edge, dict) and edge.get("kind") == "object_receipt":
            receipt_by_object[str(edge["from_id"]).split(":", 1)[1]].add(str(edge["to_id"]).split(":", 1)[1])
    catalog_receipt_shas = {row["sha256"] for row in export["records"] if isinstance(row, dict) and row.get("kind") == "receipt"}

    indexes: list[tuple[Path, dict[str, Path]]] = []
    receipt_bindings: list[dict[str, Any]] = []
    for path, raw in custody_receipts:
        raw_sha, index = custody_index_from_receipt(raw)
        if raw_sha not in catalog_receipt_shas:
            raise StreamError(f"CUSTODY_RECEIPT_NOT_IN_CATALOG_REFUSED:{path.name}")
        indexes.append((path.resolve(), index))
        receipt_bindings.append({"path": str(path.resolve()), "raw_sha256": raw_sha})

    leakage = leakage_sets(export)
    rows: list[dict[str, Any]] = []
    excluded: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    unresolved = [0, 0]
    adjudicated_overlap_staged = 0
    seen: set[str] = set()
    for dataset_id in sorted(dataset_ids):
        shas: list[str] = []
        for membership_id in membership_ids_by_dataset.get(dataset_id, ()):
            membership = membership_by_id.get(membership_id)
            if membership is None:
                raise StreamError(f"MEMBERSHIP_MISSING_REFUSED:{membership_id}")
            if membership.get("split") != "train" or membership.get("admission_state") != "admitted":
                raise StreamError(f"TRAIN_MEMBERSHIP_STATE_REFUSED:{membership_id}")
            if membership.get("tokenizer_sha256") != tokenizer_sha256:
                raise StreamError(f"MEMBERSHIP_TOKENIZER_REFUSED:{membership_id}")
            shas.append(str(membership["exact_sha256"]))
        for digest in sorted(shas):
            if digest in seen:
                continue
            seen.add(digest)
            for name, hashes in leakage.items():
                if name.startswith("_"):
                    continue
                if digest in hashes:
                    raise StreamError(f"LEAKAGE_REFUSED:{name}:{digest}")
            if digest in leakage["_adjudicated_overlap"]:
                adjudicated_overlap_staged += 1
            obj = objects.get(digest)
            if obj is None:
                raise StreamError(f"OBJECT_MISSING_REFUSED:{digest}")
            media = str(obj.get("media_type"))
            extractor = EXTRACTORS.get(media)
            byte_count = int(obj["byte_count"])
            if extractor is None:
                excluded[media][0] += 1
                excluded[media][1] += byte_count
                continue
            physical = resolve_physical(digest, indexes)
            if physical is None:
                unresolved[0] += 1
                unresolved[1] += byte_count
                continue
            if physical.stat().st_size != byte_count:
                raise StreamError(f"CUSTODY_BYTE_COUNT_REFUSED:{digest}")
            rows.append({
                "dataset_id": dataset_id,
                "sha256": digest,
                "byte_count": byte_count,
                "media_type": media,
                "extractor": extractor,
                "physical_path": str(physical),
                "receipt_sha256s": sorted(receipt_by_object.get(digest, ())),
            })
    if not rows:
        raise StreamError("STAGED_OBJECT_TOTALITY_REFUSED")
    manifest = {
        "schema_version": STAGING_SCHEMA,
        "result": "PASS",
        "catalog_export_sha256": sha(export_raw),
        "dataset_ids": sorted(dataset_ids),
        "tokenizer_sha256": tokenizer_sha256,
        "encode_contract": ENCODE_CONTRACT,
        "order_rule": "dataset_id ascending, then object sha256 ascending; duplicates staged once at first occurrence; seed-free",
        "leakage_assertion": {
            "result": "executed_pass",
            "heldout_hashes": len(leakage["heldout"]),
            "quarantined_hashes": len(leakage["quarantined"]),
            "protected_eval_hashes": len(leakage["protected_eval"]),
            "staged_intersection": 0,
            "adjudicated_overlap_hashes": len(leakage["_adjudicated_overlap"]),
            "adjudicated_overlap_staged": adjudicated_overlap_staged,
            "rule": (
                "heldout = admitted non-train memberships; quarantined = quarantined train memberships; "
                "a quarantined non-train membership is the catalog's overlap resolution and is counted, not refused"
            ),
        },
        "custody_receipts": receipt_bindings,
        "staged_count": len(rows),
        "staged_bytes": sum(row["byte_count"] for row in rows),
        "excluded_media_classes": {media: {"objects": n, "bytes": b} for media, (n, b) in sorted(excluded.items())},
        "unresolved_custody": {"objects": unresolved[0], "bytes": unresolved[1]},
        "rows": rows,
        "claim_boundary": "STAGING ONLY; NO TOKENS CONSUMED; NO CAPABILITY, SUFFICIENCY, OR CAMPAIGN CREDIT",
    }
    return self_hashed(manifest)


# --------------------------------------------------------------------------- plan (#2135)
def _admitted_train_windows(
    export: dict[str, Any], dataset_ids: list[str], tokenizer_sha256: str
) -> tuple[dict[str, list[tuple[str, int]]], dict[str, int]]:
    """Per dataset: [(sha256, window_tokens)] for every admitted train membership; and per-object window."""

    _, memberships, datasets, edges = _export_views(export)
    for identifier in dataset_ids:
        row = datasets.get(identifier)
        if row is None or row.get("state") != "admitted":
            raise StreamError(f"TRAIN_DATASET_NOT_ADMITTED_REFUSED:{identifier}")
    membership_by_id = {row["id"]: row for row in memberships}
    per_dataset: dict[str, list[tuple[str, int]]] = {identifier: [] for identifier in dataset_ids}
    window_by_object: dict[str, int] = {}
    wanted = set(dataset_ids)
    for edge in edges:
        if not (isinstance(edge, dict) and edge.get("kind") == "version_membership" and edge.get("from_id") in wanted):
            continue
        membership = membership_by_id.get(str(edge.get("to_id")))
        if membership is None:
            raise StreamError(f"MEMBERSHIP_MISSING_REFUSED:{edge.get('to_id')}")
        if membership.get("split") != "train" or membership.get("admission_state") != "admitted":
            raise StreamError(f"TRAIN_MEMBERSHIP_STATE_REFUSED:{membership['id']}")
        if membership.get("tokenizer_sha256") != tokenizer_sha256:
            raise StreamError(f"MEMBERSHIP_TOKENIZER_REFUSED:{membership['id']}")
        start, end = membership.get("window_start"), membership.get("window_end")
        if type(start) is not int or type(end) is not int or start < 0 or end < start:
            raise StreamError(f"MEMBERSHIP_WINDOW_REFUSED:{membership['id']}")
        digest = str(membership["exact_sha256"])
        tokens = end - start
        previous = window_by_object.get(digest)
        if previous is not None and previous != tokens:
            raise StreamError(f"MEMBERSHIP_WINDOW_CONFLICT_REFUSED:{digest}")
        window_by_object[digest] = tokens
        per_dataset[str(edge["from_id"])].append((digest, tokens))
    return per_dataset, window_by_object


def build_coverage_receipt(
    *,
    export_raw: bytes,
    manifest: dict[str, Any],
    manifest_raw_sha256: str,
    custody_receipts: list[tuple[Path, bytes]],
) -> dict[str, Any]:
    """Coverage arithmetic of an existing staging manifest against the live export it was built from."""

    if manifest.get("schema_version") != STAGING_SCHEMA or manifest.get("result") != "PASS":
        raise StreamError("STAGING_MANIFEST_SCHEMA_REFUSED")
    verify_self_hash(manifest, "STAGING_MANIFEST")
    export_sha256 = sha(export_raw)
    if manifest.get("catalog_export_sha256") != export_sha256:
        raise StreamError("COVERAGE_EXPORT_DRIFT_REFUSED")
    try:
        export = json.loads(export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StreamError("CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    objects, _, _, _ = _export_views(export)
    dataset_ids = [str(item) for item in manifest.get("dataset_ids", [])]
    if not dataset_ids or dataset_ids != sorted(dataset_ids):
        raise StreamError("COVERAGE_DATASET_IDS_REFUSED")
    tokenizer_sha256 = str(manifest["tokenizer_sha256"])
    per_dataset, window_by_object = _admitted_train_windows(export, dataset_ids, tokenizer_sha256)

    catalog_receipt_shas = {row["sha256"] for row in export["records"] if isinstance(row, dict) and row.get("kind") == "receipt"}
    bound = {str(item["raw_sha256"]) for item in manifest.get("custody_receipts", [])}
    indexes: list[tuple[Path, dict[str, Path]]] = []
    for path, raw in custody_receipts:
        raw_sha, index = custody_index_from_receipt(raw)
        if raw_sha not in catalog_receipt_shas:
            raise StreamError(f"CUSTODY_RECEIPT_NOT_IN_CATALOG_REFUSED:{path.name}")
        indexes.append((path.resolve(), index))
        bound.discard(raw_sha)
    if bound:
        raise StreamError("COVERAGE_CUSTODY_RECEIPTS_INCOMPLETE_REFUSED")

    staged_by_object = {str(row["sha256"]): str(row["dataset_id"]) for row in manifest["rows"]}
    if len(staged_by_object) != len(manifest["rows"]):
        raise StreamError("STAGING_MANIFEST_DUPLICATE_ROW_REFUSED")
    seen: set[str] = set()
    excluded_total: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    unresolved_total = [0, 0]
    rows: list[dict[str, Any]] = []
    staged_seen: set[str] = set()
    for dataset_id in dataset_ids:
        members = per_dataset[dataset_id]
        unique_in_dataset = {digest for digest, _ in members}
        attributed = sorted(unique_in_dataset - seen)
        staged = excluded = unresolved = 0
        staged_tokens = excluded_tokens = unresolved_tokens = 0
        for digest in attributed:
            seen.add(digest)
            obj = objects.get(digest)
            if obj is None:
                raise StreamError(f"OBJECT_MISSING_REFUSED:{digest}")
            tokens = window_by_object[digest]
            media = str(obj.get("media_type"))
            byte_count = int(obj["byte_count"])
            if EXTRACTORS.get(media) is None:
                if digest in staged_by_object:
                    raise StreamError(f"COVERAGE_EXCLUDED_OBJECT_STAGED_REFUSED:{digest}")
                excluded += 1
                excluded_tokens += tokens
                excluded_total[media][0] += 1
                excluded_total[media][1] += byte_count
                continue
            if resolve_physical(digest, indexes) is None:
                if digest in staged_by_object:
                    raise StreamError(f"COVERAGE_UNRESOLVED_OBJECT_STAGED_REFUSED:{digest}")
                unresolved += 1
                unresolved_tokens += tokens
                unresolved_total[0] += 1
                unresolved_total[1] += byte_count
                continue
            staged_dataset = staged_by_object.get(digest)
            if staged_dataset is None:
                raise StreamError(f"COVERAGE_MISSING_OBJECT_REFUSED:{digest}")
            if staged_dataset != dataset_id:
                raise StreamError(f"COVERAGE_ATTRIBUTION_REFUSED:{digest}")
            staged_seen.add(digest)
            staged += 1
            staged_tokens += tokens
        if staged + excluded + unresolved != len(attributed):
            raise StreamError(f"COVERAGE_EQUALITY_REFUSED:{dataset_id}")
        rows.append({
            "dataset_id": dataset_id,
            "admitted_train_memberships": len(members),
            "unique_objects": len(unique_in_dataset),
            "duplicates_of_earlier_dataset": len(unique_in_dataset) - len(attributed),
            "attributed_objects": len(attributed),
            "staged": staged,
            "excluded": excluded,
            "unresolved": unresolved,
            "equality": f"{staged} + {excluded} + {unresolved} == {len(attributed)}",
            "window_tokens": {"attributed": staged_tokens + excluded_tokens + unresolved_tokens, "staged": staged_tokens, "excluded": excluded_tokens, "unresolved": unresolved_tokens},
        })
    extra = set(staged_by_object) - staged_seen
    if extra:
        raise StreamError(f"COVERAGE_FOREIGN_ROW_REFUSED:{sorted(extra)[0]}")
    excluded_classes = {media: {"objects": n, "bytes": b} for media, (n, b) in sorted(excluded_total.items())}
    if excluded_classes != manifest.get("excluded_media_classes"):
        raise StreamError("COVERAGE_EXCLUDED_CLASSES_DRIFT_REFUSED")
    if {"objects": unresolved_total[0], "bytes": unresolved_total[1]} != manifest.get("unresolved_custody"):
        raise StreamError("COVERAGE_UNRESOLVED_DRIFT_REFUSED")
    if len(staged_seen) != int(manifest.get("staged_count", -1)):
        raise StreamError("COVERAGE_STAGED_COUNT_DRIFT_REFUSED")
    catalog_tokens = sum(window_by_object.values())
    staged_tokens_total = sum(row["window_tokens"]["staged"] for row in rows)
    return self_hashed({
        "schema_version": COVERAGE_SCHEMA,
        "result": "PASS",
        "catalog_export_sha256": export_sha256,
        "staging_manifest_raw_sha256": manifest_raw_sha256,
        "staging_manifest_self_sha256": manifest["self_sha256"],
        "tokenizer_sha256": tokenizer_sha256,
        "dataset_ids": dataset_ids,
        "attribution_rule": "an object counts once, in the first dataset (dataset_id ascending) that carries it -- the staging manifest's own order rule",
        "per_dataset": rows,
        "totals": {
            "admitted_train_memberships": sum(row["admitted_train_memberships"] for row in rows),
            "unique_objects": len(window_by_object),
            "staged": len(staged_seen),
            "excluded": sum(row["excluded"] for row in rows),
            "unresolved": unresolved_total[0],
            "excluded_media_classes": excluded_classes,
            "unresolved_custody": {"objects": unresolved_total[0], "bytes": unresolved_total[1]},
            "catalog_window_tokens": catalog_tokens,
            "staged_window_tokens": staged_tokens_total,
            "excluded_window_tokens": sum(row["window_tokens"]["excluded"] for row in rows),
            "unresolved_window_tokens": sum(row["window_tokens"]["unresolved"] for row in rows),
        },
        "token_rule": "window_end - window_start of each admitted train membership under the manifest's tokenizer sha256, deduplicated by object sha256; catalog-side accounting, not stream tokens",
        "equality_assertion": {
            "result": "executed_pass",
            "rule": "per dataset: staged + excluded + unresolved == attributed unique admitted objects; every extractable, custody-resolvable object has exactly one manifest row in its attributed dataset; excluded classes, unresolved custody and staged count equal the manifest's own aggregates",
        },
        "claim_boundary": "COVERAGE ARITHMETIC ONLY; NO TOKENS CONSUMED; NO SUFFICIENCY, CAPABILITY, OR CAMPAIGN CREDIT",
    })


def _budget_clause(authority_text: str, clause_index: int, marker: str) -> str:
    prefix = f"{clause_index}. "
    for line in authority_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix) and marker in stripped:
            return stripped
    raise StreamError(f"BUDGET_CLAUSE_MISSING_REFUSED:{clause_index}")


def build_budget_receipt(
    *,
    coverage: dict[str, Any],
    coverage_raw_sha256: str,
    authority_path: Path,
    authority_raw: bytes,
    frozen_budget: dict[str, Any] | None,
    frozen_budget_raw_sha256: str | None,
) -> dict[str, Any]:
    """Bind available catalog tokens to EMBER-02 item 17; UNFROZEN until a frozen budget artifact exists."""

    if coverage.get("schema_version") != COVERAGE_SCHEMA or coverage.get("result") != "PASS":
        raise StreamError("COVERAGE_RECEIPT_SCHEMA_REFUSED")
    verify_self_hash(coverage, "COVERAGE_RECEIPT")
    try:
        authority_text = authority_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StreamError("BUDGET_AUTHORITY_UNREADABLE_REFUSED") from error
    clause = _budget_clause(authority_text, BUDGET_CLAUSE_INDEX, BUDGET_CLAUSE_MARKER)
    totals = coverage["totals"]
    available = int(totals["catalog_window_tokens"])
    staged_available = int(totals["staged_window_tokens"])
    payload: dict[str, Any] = {
        "schema_version": BUDGET_SCHEMA,
        "coverage_receipt_raw_sha256": coverage_raw_sha256,
        "coverage_receipt_self_sha256": coverage["self_sha256"],
        "catalog_export_sha256": coverage["catalog_export_sha256"],
        "tokenizer_sha256": coverage["tokenizer_sha256"],
        "authority": {
            "path": str(authority_path.resolve()),
            "raw_sha256": sha(authority_raw),
            "clause_index": BUDGET_CLAUSE_INDEX,
            "clause_sha256": sha(clause.encode("utf-8")),
            "clause_text": clause,
        },
        "available_tokens": {"catalog_window_tokens": available, "staged_window_tokens": staged_available},
    }
    if frozen_budget is None:
        payload.update({
            "status": "UNFROZEN",
            "budget_tokens": None,
            "minimum_token_floor": None,
            "epochs_required": None,
            "shortfall_tokens": None,
            "frozen_budget_artifact": None,
            "rule": "item 17 freezes the budget from the measured 3B learning curve before the claim-bearing run; no frozen artifact exists, so no epoch or shortfall is computed",
        })
    else:
        budget = frozen_budget.get("budget_tokens")
        floor = frozen_budget.get("minimum_token_floor")
        if type(budget) is not int or budget < 1 or type(floor) is not int or floor < 0 or floor > budget:
            raise StreamError("FROZEN_BUDGET_SHAPE_REFUSED")
        if staged_available < 1:
            raise StreamError("STAGED_TOKENS_EMPTY_REFUSED")
        payload.update({
            "status": "FROZEN",
            "budget_tokens": budget,
            "minimum_token_floor": floor,
            "epochs_required": {"over_catalog": -(-budget // available) if available else None, "over_staged": -(-budget // staged_available)},
            "shortfall_tokens": {"over_catalog": max(0, budget - available), "over_staged": max(0, budget - staged_available)},
            "frozen_budget_artifact": {"raw_sha256": frozen_budget_raw_sha256, "source": frozen_budget.get("source")},
            "rule": "epochs = ceil(budget / available); shortfall = max(0, budget - available); one pass over the staged tokens is one epoch",
        })
    payload["claim_boundary"] = "BUDGET ACCOUNTING HOOK ONLY; NOT A BUDGET RULING; NO SUFFICIENCY, CAPABILITY, OR CAMPAIGN CREDIT"
    return self_hashed(payload)



# --------------------------------------------------------------------------- encode
def load_frozen_tokenizer(tokenizer_path: Path, expected_sha256: str) -> tuple[Any, list[str]]:
    """Load tokenizer.json with its added_tokens table stripped in memory (v0 contract)."""

    raw = tokenizer_path.read_bytes()
    if sha(raw) != expected_sha256:
        raise StreamError("TOKENIZER_SHA256_DRIFT_REFUSED")
    try:
        from tokenizers import Tokenizer  # type: ignore
    except ImportError as error:  # pragma: no cover - documented dependency
        raise StreamError("TOKENIZERS_UNAVAILABLE_REFUSED") from error
    payload = json.loads(raw.decode("utf-8"))
    literals = [str(row.get("content")) for row in payload.get("added_tokens", []) if isinstance(row, dict)]
    payload["added_tokens"] = []
    tokenizer = Tokenizer.from_str(json.dumps(payload))
    return tokenizer, literals


def reserved_band_probe(tokenizer: Any, literals: list[str]) -> dict[str, Any]:
    """Every added-token literal must encode as ordinary pieces; ids 0..7 stay unreachable."""

    band = {SEPARATOR_ID, *RESERVED_IDS}
    reachable: list[str] = []
    for literal in literals:
        ids = tokenizer.encode(literal, add_special_tokens=False).ids
        if any(token in band for token in ids):
            reachable.append(literal)
    if reachable:
        raise StreamError(f"RESERVED_BAND_REACHABLE_REFUSED:{len(reachable)}")
    return {"reserved_ids": list(RESERVED_IDS), "separator_id": SEPARATOR_ID, "max_id_lt": MAX_ID_LT, "literals_probed": len(literals), "result": "PASS"}


def _ndjson_documents(lines: Iterable[bytes]) -> Iterator[str]:
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StreamError("NDJSON_ROW_UNREADABLE_REFUSED") from error
        if not isinstance(row, dict):
            raise StreamError("NDJSON_ROW_SCHEMA_REFUSED")
        for field in NDJSON_TEXT_FIELDS:
            if isinstance(row.get(field), str):
                yield row[field]
                break
        else:
            raise StreamError("NDJSON_TEXT_FIELD_MISSING_REFUSED")


def extract_documents(path: Path, extractor: str) -> Iterator[str]:
    raw = path.read_bytes()
    if extractor == "text_utf8":
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise StreamError("UTF8_DECODE_REFUSED") from error
        return
    if extractor == "ndjson_text_field":
        yield from _ndjson_documents(raw.splitlines())
        return
    if extractor == "ndjson_zstd_text_field":
        try:
            import zstandard  # type: ignore
        except ImportError as error:  # pragma: no cover - documented dependency
            raise StreamError("ZSTANDARD_UNAVAILABLE_REFUSED") from error
        decompressed = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
        yield from _ndjson_documents(io.TextIOWrapper(decompressed, encoding="utf-8").buffer)
        return
    raise StreamError(f"EXTRACTOR_UNKNOWN_REFUSED:{extractor}")


def encode_object(tokenizer: Any, row: dict[str, Any]) -> tuple[list[int], int]:
    """Tokens for one staged object; documents separated by the writer-inserted id 0."""

    path = Path(row["physical_path"])
    if sha_file(path) != row["sha256"]:
        raise StreamError(f"STAGED_OBJECT_DRIFT_REFUSED:{row['sha256']}")
    tokens: list[int] = []
    separators = 0
    for document in extract_documents(path, row["extractor"]):
        ids = tokenizer.encode(document, add_special_tokens=False).ids
        if any(token in RESERVED_IDS or token == SEPARATOR_ID or token >= MAX_ID_LT for token in ids):
            raise StreamError(f"RESERVED_BAND_REFUSED:{row['sha256']}")
        tokens.extend(ids)
        tokens.append(SEPARATOR_ID)
        separators += 1
    return tokens, separators


# --------------------------------------------------------------------------- fill
def cache_root_for(cache_root: Path, tokenizer_sha256: str, manifest_sha256: str) -> Path:
    return cache_root / tokenizer_sha256[:8] / manifest_sha256[:8]


def fill_shards(
    *,
    manifest: dict[str, Any],
    manifest_raw_sha256: str,
    tokenizer_path: Path,
    cache_root: Path,
    shard_tokens: int,
    shard_count: int,
    encoder: Callable[[Any, dict[str, Any]], tuple[list[int], int]] = encode_object,
) -> tuple[Path, dict[str, Any]]:
    if manifest.get("schema_version") != STAGING_SCHEMA or manifest.get("result") != "PASS":
        raise StreamError("STAGING_MANIFEST_SCHEMA_REFUSED")
    verify_self_hash(manifest, "STAGING_MANIFEST")
    if shard_tokens < 1 or shard_count < 1:
        raise StreamError("SHARD_GEOMETRY_REFUSED")
    tokenizer_sha256 = str(manifest["tokenizer_sha256"])
    tokenizer, literals = load_frozen_tokenizer(tokenizer_path, tokenizer_sha256)
    band = reserved_band_probe(tokenizer, literals)
    root = cache_root_for(cache_root, tokenizer_sha256, manifest["self_sha256"])
    receipt_path = root / f"catalog-train-stream-receipt-k{shard_count}-s{shard_tokens}.json"
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_bytes())
        verify_self_hash(existing, "STREAM_RECEIPT")
        for item in existing["shards"]:
            if sha_file(root / item["name"]) != item["sha256"]:
                raise StreamError(f"CACHED_SHARD_DRIFT_REFUSED:{item['name']}")
        return receipt_path, existing
    root.mkdir(parents=True, exist_ok=True)

    shards: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    buffer = bytearray()
    written_tokens = 0
    content_tokens = 0
    separator_tokens = 0
    cursor = 0
    exhausted = False

    def write_chunk(chunk: bytes) -> None:
        nonlocal separator_tokens
        digest = sha(chunk)
        name = f"v1-{len(shards):05d}-{digest[:12]}.bin"
        target = root / name
        if target.exists():
            if sha_file(target) != digest:
                raise StreamError(f"CACHED_SHARD_DRIFT_REFUSED:{name}")
        else:
            temp = root / f"{name}.partial"
            with temp.open("wb") as stream:
                stream.write(chunk)
            os.replace(temp, target)
        shards.append({"name": name, "sha256": digest, "n_tokens": len(chunk) // 2})
        # Separator id 0 is unreachable from text (band guard), so every 0 in a written shard is a
        # writer-inserted separator; counting them here keeps the accounting inside the covered prefix.
        written = array.array("H")
        written.frombytes(chunk)
        separator_tokens += written.count(SEPARATOR_ID)

    rows = manifest["rows"]
    while len(shards) < shard_count and cursor < len(rows):
        row = rows[cursor]
        tokens, separators = encoder(tokenizer, row)
        spans.append({"sha256": row["sha256"], "token_start": written_tokens, "token_end": written_tokens + len(tokens)})
        written_tokens += len(tokens)
        content_tokens += len(tokens) - separators
        buffer.extend(struct.pack(f"<{len(tokens)}H", *tokens))
        cursor += 1
        while len(buffer) >= shard_tokens * 2 and len(shards) < shard_count:
            chunk = bytes(buffer[: shard_tokens * 2])
            del buffer[: shard_tokens * 2]
            write_chunk(chunk)
    if cursor >= len(rows) and len(shards) < shard_count:
        exhausted = True
        if buffer:
            write_chunk(bytes(buffer))
            buffer = bytearray()
    if not shards:
        raise StreamError("STREAM_EMPTY_REFUSED")
    covered = sum(item["n_tokens"] for item in shards)
    # The last span may run past the covered prefix when the fill stopped mid-object.
    spans = [span for span in spans if span["token_start"] < covered]
    if spans:
        spans[-1]["token_end"] = min(spans[-1]["token_end"], covered)
    receipt = {
        "ticket": STREAM_TICKET,
        "schema_version": STREAM_RECEIPT_SCHEMA,
        "stream_format": "token-shards-v0 little-endian uint16; doc-boundary separator id 0 writer-inserted",
        "encode_semantics": ENCODE_CONTRACT,
        "premises": {"tokenizer_json": {"path": str(tokenizer_path.resolve()), "sha256": tokenizer_sha256}},
        "shards": shards,
        "total_stream_tokens": covered,
        "content_total_tokens": covered - separator_tokens,
        "separator_tokens": separator_tokens,
        "accounting_rule": "counted inside the written shards: separators = occurrences of id 0 (unreachable from text); content = total - separators",
        "reserved_band_guard": band,
        "catalog_binding": {
            "schema_version": BINDING_SCHEMA,
            "catalog_export_sha256": manifest["catalog_export_sha256"],
            "dataset_ids": manifest["dataset_ids"],
            "staging_manifest_raw_sha256": manifest_raw_sha256,
            "staging_manifest_self_sha256": manifest["self_sha256"],
            "shard_tokens": shard_tokens,
            "shard_count_requested": shard_count,
            "objects_consumed": cursor,
            "staged_objects_exhausted": exhausted,
        },
        "claim_boundary": "PRODUCER/LOADER COMPATIBILITY ONLY; NO TOKENS CONSUMED BY ANY OPTIMIZER; NO CAPABILITY, SUFFICIENCY, OR CAMPAIGN CREDIT",
    }
    receipt = self_hashed(receipt)
    write_new(receipt_path, json.dumps(receipt, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    write_new(root / f"object-spans-k{shard_count}-s{shard_tokens}.json", json.dumps({"schema_version": BINDING_SCHEMA, "receipt_self_sha256": receipt["self_sha256"], "spans": spans}, sort_keys=True).encode("utf-8") + b"\n")
    return receipt_path, receipt


# --------------------------------------------------------------------------- shard ledger (#2135)
def ledger_path_for(receipt_path: Path, shard_tokens: int) -> Path:
    return receipt_path.parent / f"shard-ledger-s{shard_tokens}.jsonl"


def ledger_row_sha256(row: dict[str, Any]) -> str:
    return sha(canonical({key: value for key, value in row.items() if key != "row_sha256"}))


def build_ledger_row(
    *,
    index: int,
    name: str,
    sha256: str,
    n_tokens: int,
    token_start: int,
    spans: list[dict[str, Any]],
    resume: dict[str, int],
    exhausted: bool,
    prev_row_sha256: str,
) -> dict[str, Any]:
    row = {
        "schema_version": LEDGER_SCHEMA,
        "index": index,
        "name": name,
        "sha256": sha256,
        "n_tokens": n_tokens,
        "token_start": token_start,
        "spans": spans,
        "resume": {"object_index": int(resume["object_index"]), "carry_tokens": int(resume["carry_tokens"])},
        "staged_objects_exhausted": exhausted,
        "prev_row_sha256": prev_row_sha256,
    }
    row["row_sha256"] = ledger_row_sha256(row)
    return row


def read_shard_ledger(path: Path) -> list[dict[str, Any]]:
    """Parse and verify the self-chained ledger; a missing file is an empty ledger."""

    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    prev = LEDGER_GENESIS_PREV
    running = 0
    for line_number, line in enumerate(path.read_bytes().split(b"\n")):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise StreamError(f"SHARD_LEDGER_ROW_UNREADABLE_REFUSED:{line_number}") from error
        if not isinstance(row, dict) or row.get("schema_version") != LEDGER_SCHEMA:
            raise StreamError(f"SHARD_LEDGER_SCHEMA_REFUSED:{line_number}")
        if row.get("index") != len(rows) or row.get("prev_row_sha256") != prev:
            raise StreamError(f"SHARD_LEDGER_CHAIN_REFUSED:{len(rows)}")
        if row.get("row_sha256") != ledger_row_sha256(row):
            raise StreamError(f"SHARD_LEDGER_ROW_HASH_REFUSED:{len(rows)}")
        if type(row.get("n_tokens")) is not int or row["n_tokens"] < 1 or row.get("token_start") != running:
            raise StreamError(f"SHARD_LEDGER_GEOMETRY_REFUSED:{len(rows)}")
        if not isinstance(row.get("name"), str) or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise StreamError(f"SHARD_LEDGER_IDENTITY_REFUSED:{len(rows)}")
        running += row["n_tokens"]
        prev = row["row_sha256"]
        rows.append(row)
    return rows


def verify_ledger_shards(root: Path, rows: list[dict[str, Any]], start: int = 0) -> None:
    for row in rows[start:]:
        target = root / str(row["name"])
        if not target.is_file() or target.stat().st_size != row["n_tokens"] * 2:
            raise StreamError(f"SHARD_LEDGER_BYTES_REFUSED:{row['name']}")
        if sha_file(target) != row["sha256"]:
            raise StreamError(f"SHARD_LEDGER_BYTES_REFUSED:{row['name']}")


def verify_ledger_genesis(rows: list[dict[str, Any]], receipt: dict[str, Any]) -> None:
    shards = receipt["shards"]
    if len(rows) < len(shards):
        raise StreamError("SHARD_LEDGER_GENESIS_REFUSED:short")
    for index, shard in enumerate(shards):
        row = rows[index]
        if (row["name"], row["sha256"], row["n_tokens"]) != (shard["name"], shard["sha256"], shard["n_tokens"]):
            raise StreamError(f"SHARD_LEDGER_GENESIS_REFUSED:{index}")


def merge_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concatenate contiguous span lists, merging a span split across a shard boundary."""

    merged: list[dict[str, Any]] = []
    for span in spans:
        if merged and merged[-1]["sha256"] == span["sha256"] and merged[-1]["token_end"] == span["token_start"]:
            merged[-1] = dict(merged[-1], token_end=span["token_end"])
        else:
            merged.append(dict(span))
    return merged


def extended_spans(receipt_spans: list[dict[str, Any]], rows: list[dict[str, Any]], receipt_shard_count: int) -> list[dict[str, Any]]:
    tail = [span for row in rows[receipt_shard_count:] for span in row["spans"]]
    return merge_spans([dict(span) for span in receipt_spans] + tail)


def _clip_spans(spans: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    out = []
    for span in spans:
        lo, hi = max(span["token_start"], start), min(span["token_end"], end)
        if lo < hi:
            out.append({"sha256": span["sha256"], "token_start": lo, "token_end": hi})
    return out


def _genesis_rows(receipt: dict[str, Any], receipt_spans: list[dict[str, Any]], manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restate the receipt's shards as ledger rows; the last row carries the tokenization resume state."""

    index_by_sha = {str(row["sha256"]): position for position, row in enumerate(manifest_rows)}
    rows: list[dict[str, Any]] = []
    prev = LEDGER_GENESIS_PREV
    running = 0
    shards = receipt["shards"]
    for index, shard in enumerate(shards):
        end = running + int(shard["n_tokens"])
        clipped = _clip_spans(receipt_spans, running, end)
        if not clipped:
            raise StreamError(f"RECEIPT_SPANS_EMPTY_FOR_SHARD_REFUSED:{index}")
        last = clipped[-1]
        object_index = index_by_sha.get(last["sha256"])
        if object_index is None:
            raise StreamError(f"RECEIPT_SPAN_OBJECT_NOT_IN_MANIFEST_REFUSED:{last['sha256']}")
        # The object that ends this shard has emitted (end - its start) tokens so far. Whether it is
        # finished is settled by re-encoding it at produce time: a carry equal to its length moves on.
        full_start = next(span["token_start"] for span in receipt_spans if span["sha256"] == last["sha256"] and span["token_end"] >= end)
        row = build_ledger_row(
            index=index, name=str(shard["name"]), sha256=str(shard["sha256"]), n_tokens=int(shard["n_tokens"]),
            token_start=running, spans=clipped, resume={"object_index": object_index, "carry_tokens": end - full_start},
            exhausted=bool(receipt["catalog_binding"].get("staged_objects_exhausted")) and index == len(shards) - 1,
            prev_row_sha256=prev,
        )
        rows.append(row)
        prev = row["row_sha256"]
        running = end
    return rows


def _append_ledger_row(path: Path, row: dict[str, Any]) -> None:
    line = json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    with path.open("ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _write_shard_atomic(root: Path, name: str, chunk: bytes) -> None:
    temp = root / f"{name}.partial"
    with temp.open("wb") as stream:
        stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, root / name)


def _produce_one(
    *,
    tokenizer: Any,
    manifest_rows: list[dict[str, Any]],
    resume: dict[str, int],
    shard_tokens: int,
    token_start: int,
    encoder: Callable[[Any, dict[str, Any]], tuple[list[int], int]],
) -> tuple[bytes, list[dict[str, Any]], dict[str, int], bool] | None:
    """Tokenize forward from `resume` until one shard is full or the staged objects run out."""

    buffer: list[int] = []
    spans: list[dict[str, Any]] = []
    object_index = int(resume["object_index"])
    carry = int(resume["carry_tokens"])
    while len(buffer) < shard_tokens and object_index < len(manifest_rows):
        row = manifest_rows[object_index]
        tokens, _ = encoder(tokenizer, row)
        if carry > len(tokens):
            raise StreamError(f"LEDGER_RESUME_CARRY_REFUSED:{object_index}")
        remaining = tokens[carry:]
        if not remaining:
            object_index += 1
            carry = 0
            continue
        take = min(shard_tokens - len(buffer), len(remaining))
        spans.append({"sha256": str(row["sha256"]), "token_start": token_start + len(buffer), "token_end": token_start + len(buffer) + take})
        buffer.extend(remaining[:take])
        carry += take
        if carry == len(tokens):
            object_index += 1
            carry = 0
    if not buffer:
        return None
    exhausted = object_index >= len(manifest_rows)
    return struct.pack(f"<{len(buffer)}H", *buffer), spans, {"object_index": object_index, "carry_tokens": carry}, exhausted


def produce_shards(
    *,
    manifest: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
    receipt_spans: list[dict[str, Any]],
    tokenizer_path: Path,
    shard_tokens: int,
    target_shards: int,
    regenerate: bool = False,
    encoder: Callable[[Any, dict[str, Any]], tuple[list[int], int]] = encode_object,
) -> tuple[Path, list[dict[str, Any]], int]:
    """Extend the ledger to `target_shards` rows (or exhaustion); the receipt is never rewritten."""

    if manifest.get("schema_version") != STAGING_SCHEMA or manifest.get("result") != "PASS":
        raise StreamError("STAGING_MANIFEST_SCHEMA_REFUSED")
    verify_self_hash(manifest, "STAGING_MANIFEST")
    if receipt.get("schema_version") != STREAM_RECEIPT_SCHEMA:
        raise StreamError("STREAM_RECEIPT_SCHEMA_REFUSED")
    verify_self_hash(receipt, "STREAM_RECEIPT")
    binding = receipt.get("catalog_binding") or {}
    if binding.get("staging_manifest_self_sha256") != manifest.get("self_sha256"):
        raise StreamError("PRODUCER_MANIFEST_BINDING_REFUSED")
    if binding.get("shard_tokens") != shard_tokens or shard_tokens < 1:
        raise StreamError("PRODUCER_SHARD_TOKENS_REFUSED")
    if target_shards < 1:
        raise StreamError("PRODUCER_TARGET_REFUSED")
    tokenizer_sha256 = str(manifest["tokenizer_sha256"])
    tokenizer, _ = load_frozen_tokenizer(tokenizer_path, tokenizer_sha256)
    root = receipt_path.resolve().parent
    ledger = ledger_path_for(receipt_path.resolve(), shard_tokens)
    lock = root / f"shard-ledger-s{shard_tokens}.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise StreamError(f"SHARD_LEDGER_LOCKED_REFUSED:{lock}") from error
    try:
        (lock / "owner").write_text(f"pid={os.getpid()}\n", encoding="utf-8")
        rows = read_shard_ledger(ledger)
        manifest_rows = manifest["rows"]
        if not rows:
            for row in _genesis_rows(receipt, receipt_spans, manifest_rows):
                _append_ledger_row(ledger, row)
            rows = read_shard_ledger(ledger)
        verify_ledger_genesis(rows, receipt)
        # Regeneration: a ledger row is authoritative identity; missing or drifted bytes are re-derived
        # from the previous row's resume state and must reproduce the recorded sha256 exactly.
        for position, row in enumerate(rows):
            target = root / str(row["name"])
            intact = target.is_file() and target.stat().st_size == row["n_tokens"] * 2 and sha_file(target) == row["sha256"]
            if intact:
                continue
            if not regenerate:
                raise StreamError(f"SHARD_LEDGER_BYTES_REFUSED:{row['name']}")
            if position < len(receipt["shards"]):
                raise StreamError(f"RECEIPT_SHARD_REGENERATION_REFUSED:{row['name']}")
            state = rows[position - 1]["resume"]
            produced = _produce_one(tokenizer=tokenizer, manifest_rows=manifest_rows, resume=state, shard_tokens=shard_tokens, token_start=row["token_start"], encoder=encoder)
            if produced is None or sha(produced[0]) != row["sha256"]:
                raise StreamError(f"SHARD_LEDGER_REGENERATION_DRIFT_REFUSED:{row['name']}")
            _write_shard_atomic(root, str(row["name"]), produced[0])
        produced_count = 0
        while len(rows) < target_shards and not rows[-1]["staged_objects_exhausted"]:
            previous = rows[-1]
            token_start = previous["token_start"] + previous["n_tokens"]
            produced = _produce_one(tokenizer=tokenizer, manifest_rows=manifest_rows, resume=previous["resume"], shard_tokens=shard_tokens, token_start=token_start, encoder=encoder)
            if produced is None:
                # Nothing left past the previous row: seal exhaustion on a zero-length note is not a
                # shard; mark by refusing further production without rewriting history.
                break
            chunk, spans, resume, exhausted = produced
            digest = sha(chunk)
            name = f"v1-{len(rows):05d}-{digest[:12]}.bin"
            _write_shard_atomic(root, name, chunk)
            row = build_ledger_row(
                index=len(rows), name=name, sha256=digest, n_tokens=len(chunk) // 2, token_start=token_start,
                spans=spans, resume=resume, exhausted=exhausted, prev_row_sha256=previous["row_sha256"],
            )
            _append_ledger_row(ledger, row)
            rows.append(row)
            produced_count += 1
        return ledger, rows, produced_count
    finally:
        try:
            (lock / "owner").unlink()
        except OSError:
            pass
        try:
            lock.rmdir()
        except OSError:
            pass



# --------------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("--catalog-export", type=Path, required=True)
    stage.add_argument("--dataset-id", action="append", default=None)
    stage.add_argument("--tokenizer-sha256", required=True)
    stage.add_argument("--custody-receipt", type=Path, action="append", default=[])
    stage.add_argument("--manifest", type=Path, required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--catalog-export", type=Path, required=True)
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--custody-receipt", type=Path, action="append", default=[])
    plan.add_argument("--authority", type=Path, required=True, help="EMBER-02.md (item 17 is the budget clause)")
    plan.add_argument("--frozen-budget", type=Path, default=None)
    plan.add_argument("--coverage", type=Path, required=True)
    plan.add_argument("--budget", type=Path, required=True)
    produce = sub.add_parser("produce")
    produce.add_argument("--manifest", type=Path, required=True)
    produce.add_argument("--stream-receipt", type=Path, required=True)
    produce.add_argument("--spans", type=Path, required=True)
    produce.add_argument("--tokenizer", type=Path, required=True)
    produce.add_argument("--shard-tokens", type=int, default=DEFAULT_SHARD_TOKENS)
    shape = produce.add_mutually_exclusive_group(required=True)
    shape.add_argument("--target-shards", type=int, help="ledger rows to guarantee (receipt shards count)")
    shape.add_argument("--ahead", type=int, help="shards to guarantee beyond --cursor-shard-index")
    produce.add_argument("--cursor-shard-index", type=int, default=0)
    produce.add_argument("--regenerate", action="store_true", help="re-derive missing or drifted ledger shard bytes")
    fill = sub.add_parser("fill")
    fill.add_argument("--manifest", type=Path, required=True)
    fill.add_argument("--tokenizer", type=Path, required=True)
    fill.add_argument("--cache-root", type=Path, required=True)
    fill.add_argument("--shard-tokens", type=int, default=DEFAULT_SHARD_TOKENS)
    fill.add_argument("--shards", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "stage":
            manifest = build_staging_manifest(
                export_raw=args.catalog_export.read_bytes(),
                dataset_ids=args.dataset_id,
                tokenizer_sha256=args.tokenizer_sha256,
                custody_receipts=[(path, path.read_bytes()) for path in args.custody_receipt],
            )
            write_new(args.manifest, json.dumps(manifest, sort_keys=True, indent=1).encode("utf-8") + b"\n")
            summary = {key: manifest[key] for key in ("result", "staged_count", "staged_bytes", "excluded_media_classes", "unresolved_custody", "leakage_assertion", "self_sha256")}
            print(json.dumps(summary, sort_keys=True))
            return 0
        if args.operation == "plan":
            manifest_raw = args.manifest.read_bytes()
            coverage = build_coverage_receipt(
                export_raw=args.catalog_export.read_bytes(),
                manifest=json.loads(manifest_raw),
                manifest_raw_sha256=sha(manifest_raw),
                custody_receipts=[(path, path.read_bytes()) for path in args.custody_receipt],
            )
            coverage_raw = json.dumps(coverage, sort_keys=True, indent=1).encode("utf-8") + b"\n"
            write_new(args.coverage, coverage_raw)
            frozen_raw = args.frozen_budget.read_bytes() if args.frozen_budget is not None else None
            budget = build_budget_receipt(
                coverage=coverage,
                coverage_raw_sha256=sha(coverage_raw),
                authority_path=args.authority,
                authority_raw=args.authority.read_bytes(),
                frozen_budget=json.loads(frozen_raw) if frozen_raw is not None else None,
                frozen_budget_raw_sha256=sha(frozen_raw) if frozen_raw is not None else None,
            )
            write_new(args.budget, json.dumps(budget, sort_keys=True, indent=1).encode("utf-8") + b"\n")
            print(json.dumps({"result": "PASS", "totals": coverage["totals"], "coverage_self_sha256": coverage["self_sha256"], "budget_status": budget["status"], "budget_self_sha256": budget["self_sha256"]}, sort_keys=True))
            return 0
        if args.operation == "produce":
            receipt = json.loads(args.stream_receipt.read_bytes())
            spans_doc = json.loads(args.spans.read_bytes())
            if spans_doc.get("receipt_self_sha256") != receipt.get("self_sha256"):
                raise StreamError("SPANS_RECEIPT_BINDING_REFUSED")
            target = args.target_shards if args.target_shards is not None else args.cursor_shard_index + 1 + args.ahead
            ledger, rows, produced = produce_shards(
                manifest=json.loads(args.manifest.read_bytes()), receipt_path=args.stream_receipt, receipt=receipt,
                receipt_spans=spans_doc["spans"], tokenizer_path=args.tokenizer, shard_tokens=args.shard_tokens,
                target_shards=target, regenerate=args.regenerate,
            )
            print(json.dumps({"result": "PASS", "ledger": str(ledger), "ledger_raw_sha256": sha_file(ledger), "rows": len(rows), "produced": produced,
                              "total_ledger_tokens": rows[-1]["token_start"] + rows[-1]["n_tokens"], "staged_objects_exhausted": rows[-1]["staged_objects_exhausted"],
                              "receipt_untouched_sha256": sha_file(args.stream_receipt)}, sort_keys=True))
            return 0
        manifest_raw = args.manifest.read_bytes()
        receipt_path, receipt = fill_shards(
            manifest=json.loads(manifest_raw),
            manifest_raw_sha256=sha(manifest_raw),
            tokenizer_path=args.tokenizer,
            cache_root=args.cache_root,
            shard_tokens=args.shard_tokens,
            shard_count=args.shards,
        )
        print(json.dumps({"result": "PASS", "receipt": str(receipt_path), "total_stream_tokens": receipt["total_stream_tokens"], "shards": len(receipt["shards"]), "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
