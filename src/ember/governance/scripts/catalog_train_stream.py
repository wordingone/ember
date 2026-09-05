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

Claim boundary: producer/loader compatibility only. No optimizer consumes anything here.
"""

from __future__ import annotations

import argparse
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

    rows = manifest["rows"]
    while len(shards) < shard_count and cursor < len(rows):
        row = rows[cursor]
        tokens, separators = encoder(tokenizer, row)
        spans.append({"sha256": row["sha256"], "token_start": written_tokens, "token_end": written_tokens + len(tokens)})
        written_tokens += len(tokens)
        content_tokens += len(tokens) - separators
        separator_tokens += separators
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
        "content_total_tokens": min(content_tokens, covered),
        "separator_tokens": separator_tokens,
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
