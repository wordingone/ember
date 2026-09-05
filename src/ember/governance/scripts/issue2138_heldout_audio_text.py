#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Admit one canonical reference-transcript text object per admitted heldout audio item (#2138).

The item set IS the #2120 admitted heldout audio set (64 LibriSpeech test-clean
utterances, ``selected_set_sha256`` frozen below).  There is no N and no sampling.
Per item this module reads exactly one ``.trans.txt`` line from the verified seed
tarball, canonicalizes it to ``{utterance_id, transcript}``, and binds the item to
its already-admitted audio payload (read from the #2120 connector custody, never
re-admitted) and its new transcript text object.  Speaker and chapter identities are
recorded as metadata only; the adapter never reads them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tarfile
from pathlib import Path
from typing import Any

CENSUS_SCHEMA = "ember-issue2138-heldout-audio-text-item-census-v1"
PLAN_SCHEMA = "ember-issue2138-heldout-audio-text-admission-plan-v1"
ADMISSION_RECEIPT_SCHEMA = "ember-issue2138-heldout-audio-text-admission-receipt-v1"
CONTRACT_SCHEMA = "ember-issue1947-protected-audio-text-contract-v1"
PREDECESSOR_CONTRACT_SCHEMA = "ember-issue1947-protected-audio-contract-v1"
AUDIO_CENSUS_SCHEMA = "ember-issue1947-heldout-audio-candidate-census-v1"
TASK_ID = "EXACT_AUDIO_TEXT_PAIR_IDENTITY"
FORBIDDEN_INPUTS = ["speaker_metadata", "chapter_metadata", "prediction_custody"]
AUDIO_CENSUS_RAW_SHA256 = "5f00319f595ef08d4bae6c7f4fb931a790e2b3add202f23d652801fa116e0da2"
AUDIO_CENSUS_SELF_SHA256 = "3a0f19cad44f0dc8b31bc80ac90c44550e3379cff0b2b3dd5702169932f1befb"
AUDIO_SELECTED_SET_SHA256 = "f335061f27342b062df2721dd72cfbc5328532405fbe5bad1357abc9a24f7ab0"
SEED_TAR_SHA256 = "39fde525e59672dc6d1551919b1478f724438a95aa55f874b576be21967e6c23"
LICENSE_SHA256 = "908b0b565ae9bf61b7b41447cb0b83564f320375723bcc884ec30e5537a0d5dc"
SOURCE_URL = "https://www.openslr.org/resources/12/test-clean.tar.gz"
SOURCE_SUBSET = "test-clean"
EXPECTED_ITEM_COUNT = 64
EXPECTED_ADMITTED_HELDOUT_AUDIO_COUNT = 64
# The catalog holds no admitted train audio object today; a drift in that count means
# the exclusion set this planner executes against is not the one the census assumed.
EXPECTED_ADMITTED_TRAIN_AUDIO_COUNT = 0
PREDECESSOR_AUDIO_SOURCE_ID = "librispeech-test-clean-heldout-audio-64"
TEXT_SOURCE_ID = "librispeech-test-clean-heldout-audio-text-transcripts"
CATALOG_TEXT_SOURCE_ID = "candidate-audio-text-transcripts-heldout-0"
AUDIO_MEDIA_TYPE = "audio/flac"
TEXT_MEDIA_TYPE = "application/json"
TEXT_KEYS = ("transcript", "utterance_id")
TEXT_CANONICALIZATION = (
    "json.dumps({'utterance_id','transcript'}, sort_keys=True, separators=(',',':'), "
    "ensure_ascii=True) + LF; transcript = the utterance's .trans.txt line after its "
    "first space, whitespace-collapsed to single spaces, stripped, uppercase as shipped; "
    "speaker and chapter identities are never members"
)
SELECTION_RULE = (
    "item set IS the #2120 admitted heldout audio set (selected_set_sha256 frozen); "
    "one canonical transcript text object per item; no N, no sampling; audio objects "
    "are referenced from the predecessor dataset and never re-admitted; exact exclusion "
    "of every admitted train object sha256 asserted; selected_set_sha256 of this carrier "
    "= sha256 of the sorted transcript text-object sha256 set"
)
CLAIM_BOUNDARY = (
    "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, "
    "OR GOAL CREDIT"
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def transcript_text_object(utterance_id: str, transcript: str) -> bytes:
    if not utterance_id or not transcript:
        raise ValueError(f"TRANSCRIPT_EMPTY_REFUSED:{utterance_id}")
    payload = {"transcript": transcript, "utterance_id": utterance_id}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def item_gold_sha256(audio_payload: bytes, text_payload: bytes) -> str:
    return sha(audio_payload + text_payload)


def _verified_audio_census(raw: bytes) -> dict[str, Any]:
    if sha(raw) != AUDIO_CENSUS_RAW_SHA256:
        raise ValueError("AUDIO_CENSUS_RAW_SHA256_DRIFT_REFUSED")
    try:
        census = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AUDIO_CENSUS_UNREADABLE_REFUSED") from error
    body = dict(census)
    if body.pop("self_sha256", None) != AUDIO_CENSUS_SELF_SHA256 or sha(canonical(body)) != AUDIO_CENSUS_SELF_SHA256:
        raise ValueError("AUDIO_CENSUS_SELF_SHA256_DRIFT_REFUSED")
    selected = census.get("selected")
    if (
        census.get("schema_version") != AUDIO_CENSUS_SCHEMA
        or census.get("selected_set_sha256") != AUDIO_SELECTED_SET_SHA256
        or not isinstance(selected, list)
        or len(selected) != EXPECTED_ITEM_COUNT
    ):
        raise ValueError("AUDIO_CENSUS_CONTRACT_DRIFT_REFUSED")
    return census


def utterance_from_member(member: str) -> tuple[str, str, str]:
    """`LibriSpeech/test-clean/<spk>/<chap>/<spk>-<chap>-<utt>.flac` -> (utterance_id, speaker, chapter)."""

    parts = member.split("/")
    if len(parts) < 3 or not parts[-1].lower().endswith(".flac"):
        raise ValueError(f"AUDIO_MEMBER_SHAPE_REFUSED:{member}")
    utterance_id = parts[-1][: -len(".flac")]
    speaker, chapter = parts[-3], parts[-2]
    if utterance_id.split("-")[:2] != [speaker, chapter]:
        raise ValueError(f"AUDIO_MEMBER_SHAPE_REFUSED:{member}")
    return utterance_id, speaker, chapter


def read_transcripts(seed_tar: Path, audio_census_raw: bytes) -> tuple[list[dict[str, Any]], int]:
    """Read ONLY the chapter transcript members the selected utterances belong to. Flac
    members are never opened here; the tar's own sha256 is verified before any read."""

    census = _verified_audio_census(audio_census_raw)
    digest = hashlib.sha256()
    with seed_tar.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 22), b""):
            digest.update(chunk)
    if digest.hexdigest() != SEED_TAR_SHA256:
        raise ValueError("SEED_TAR_SHA256_DRIFT_REFUSED")
    selected: dict[str, dict[str, Any]] = {}
    wanted_trans: dict[str, list[str]] = {}
    for row in census["selected"]:
        member = str(row["member"])
        utterance_id, speaker, chapter = utterance_from_member(member)
        if str(row.get("speaker_id")) != speaker or str(row.get("chapter_id")) != chapter:
            raise ValueError(f"AUDIO_CENSUS_METADATA_DRIFT_REFUSED:{utterance_id}")
        if utterance_id in selected:
            raise ValueError(f"UTTERANCE_ID_DUPLICATE_REFUSED:{utterance_id}")
        selected[utterance_id] = {
            "item_id": utterance_id,
            "speaker_id": speaker,
            "chapter_id": chapter,
            "audio_sha256": str(row["exact_sha256"]),
            "audio_byte_count": int(row["byte_count"]),
            "member": member,
        }
        trans_member = "/".join(member.split("/")[:-1] + [f"{speaker}-{chapter}.trans.txt"])
        wanted_trans.setdefault(trans_member, []).append(utterance_id)
    lines: dict[str, list[str]] = {}
    read_members: set[str] = set()
    with tarfile.open(seed_tar, "r:gz") as archive:
        for member in archive:
            if member.name not in wanted_trans or not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"TRANSCRIPT_MEMBER_MISSING_REFUSED:{member.name}")
            read_members.add(member.name)
            for line in handle.read().decode("utf-8").splitlines():
                head, _, rest = line.strip().partition(" ")
                if head in selected:
                    lines.setdefault(head, []).append(" ".join(rest.split()))
            if len(read_members) == len(wanted_trans):
                break
    missing_members = sorted(set(wanted_trans) - read_members)
    if missing_members:
        raise ValueError(f"TRANSCRIPT_MEMBER_MISSING_REFUSED:{missing_members[0]}")
    read_count = len(read_members)
    items: list[dict[str, Any]] = []
    for utterance_id in sorted(selected):
        found = lines.get(utterance_id, [])
        if len(found) != 1:
            raise ValueError(f"TRANSCRIPT_LINE_TOTALITY_REFUSED:{utterance_id}:{len(found)}")
        text_payload = transcript_text_object(utterance_id, found[0])
        item = dict(selected[utterance_id])
        item["transcript"] = found[0]
        item["text_payload"] = text_payload
        item["text_sha256"] = sha(text_payload)
        items.append(item)
    return items, read_count


def read_predecessor_audio_payloads(
    predecessor_connector_raw: bytes, items: list[dict[str, Any]],
) -> dict[str, bytes]:
    """Audio bytes come from the #2120 admitted custody (connector dest_root), verified
    per object against the census identity; the tar's flac members are never opened."""

    try:
        connector = json.loads(predecessor_connector_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("PREDECESSOR_CONNECTOR_UNREADABLE_REFUSED") from error
    if (
        not isinstance(connector, dict)
        or connector.get("schema") != "corpus-connector-receipt-v1"
        or connector.get("source_id") != PREDECESSOR_AUDIO_SOURCE_ID
    ):
        raise ValueError("PREDECESSOR_CONNECTOR_IDENTITY_REFUSED")
    root_value = connector.get("dest_root")
    files = connector.get("files")
    if not isinstance(root_value, str) or not isinstance(files, list):
        raise ValueError("PREDECESSOR_CONNECTOR_TOTALITY_REFUSED")
    root = Path(root_value)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("PREDECESSOR_CUSTODY_ROOT_MISSING_REFUSED")
    root = root.resolve()
    by_sha = {row["sha256"]: row for row in files if isinstance(row, dict) and isinstance(row.get("sha256"), str)}
    if set(by_sha) != {item["audio_sha256"] for item in items} or len(by_sha) != len(files):
        raise ValueError("PREDECESSOR_CONNECTOR_COVERAGE_REFUSED")
    payloads: dict[str, bytes] = {}
    for item in items:
        row = by_sha[item["audio_sha256"]]
        if row.get("bytes") != item["audio_byte_count"] or not isinstance(row.get("path"), str):
            raise ValueError(f"PREDECESSOR_AUDIO_IDENTITY_REFUSED:{item['item_id']}")
        physical = (root / Path(row["path"])).resolve()
        try:
            physical.relative_to(root)
        except ValueError as error:
            raise ValueError(f"PREDECESSOR_AUDIO_PATH_ESCAPE_REFUSED:{item['item_id']}") from error
        raw = physical.read_bytes()
        if sha(raw) != item["audio_sha256"] or len(raw) != item["audio_byte_count"]:
            raise ValueError(f"PREDECESSOR_AUDIO_PAYLOAD_DRIFT_REFUSED:{item['item_id']}")
        payloads[item["audio_sha256"]] = raw
    return payloads


def build_census(
    *,
    items: list[dict[str, Any]],
    trans_files_read: int,
    license_raw: bytes,
    audio_census_raw: bytes,
    predecessor_connector_raw: bytes,
    audio_payloads: dict[str, bytes],
    admitted_train_object_hashes: set[str],
    admitted_heldout_audio_hashes: set[str],
) -> dict[str, Any]:
    """Read-only census: identities, pairing, train exclusion. No custody is written."""

    if sha(license_raw) != LICENSE_SHA256:
        raise ValueError("LICENSE_SHA256_DRIFT_REFUSED")
    audio_census = _verified_audio_census(audio_census_raw)
    ids = [item["item_id"] for item in items]
    if ids != sorted(ids) or len(ids) != EXPECTED_ITEM_COUNT or len(set(ids)) != len(ids):
        raise ValueError(f"ITEM_COUNT_REFUSED:{len(ids)}")
    audio_hashes = {item["audio_sha256"] for item in items}
    # `selected_set_sha256` is the #2120 census's own identity (sha256 over its canonical `selected`
    # entries, verified against the frozen constant above); the item set is bound by set equality with
    # those entries, never by re-deriving the hash under a formula of this module's own.
    if audio_hashes != {str(entry["exact_sha256"]) for entry in audio_census["selected"]}:
        raise ValueError("AUDIO_SELECTED_SET_SHA256_DRIFT_REFUSED")
    if admitted_heldout_audio_hashes != audio_hashes:
        raise ValueError(
            f"HELDOUT_AUDIO_CATALOG_COVERAGE_REFUSED:{len(admitted_heldout_audio_hashes & audio_hashes)}/{len(audio_hashes)}"
        )
    if set(audio_payloads) != audio_hashes:
        raise ValueError("AUDIO_PAYLOAD_COVERAGE_REFUSED")
    text_objects: dict[str, str] = {}
    census_items: list[dict[str, Any]] = []
    for item in items:
        text_digest = item["text_sha256"]
        if sha(item["text_payload"]) != text_digest:
            raise ValueError(f"TEXT_OBJECT_IDENTITY_DRIFT_REFUSED:{item['item_id']}")
        if text_digest in text_objects or text_digest in audio_hashes:
            raise ValueError(f"TEXT_OBJECT_IDENTITY_CONFLICT_REFUSED:{text_digest}")
        text_objects[text_digest] = item["item_id"]
        census_items.append({
            "item_id": item["item_id"],
            "speaker_id": item["speaker_id"],
            "chapter_id": item["chapter_id"],
            "audio_object": {
                "sha256": item["audio_sha256"],
                "byte_count": item["audio_byte_count"],
                "media_type": AUDIO_MEDIA_TYPE,
            },
            "item_text_object": {
                "sha256": text_digest,
                "byte_count": len(item["text_payload"]),
                "media_type": TEXT_MEDIA_TYPE,
            },
            "gold_item_sha256": item_gold_sha256(audio_payloads[item["audio_sha256"]], item["text_payload"]),
        })
    referenced = sorted(audio_hashes | set(text_objects))
    for digest in referenced:
        if digest in admitted_train_object_hashes:
            raise ValueError(f"TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{digest}")
    admitted_here = sorted(text_objects)
    census: dict[str, Any] = {
        "schema_version": CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "benchmark_id": "LibriSpeech",
            "subset": SOURCE_SUBSET,
            "source_url": SOURCE_URL,
            "seed_tar_sha256": SEED_TAR_SHA256,
            "license_sha256": LICENSE_SHA256,
            "audio_census_raw_sha256": AUDIO_CENSUS_RAW_SHA256,
            "audio_census_self_sha256": AUDIO_CENSUS_SELF_SHA256,
            "audio_selected_set_sha256": AUDIO_SELECTED_SET_SHA256,
            "predecessor_source_id": PREDECESSOR_AUDIO_SOURCE_ID,
            "predecessor_connector_receipt_raw_sha256": sha(predecessor_connector_raw),
            "speaker_chapter_metadata_access": "identity_only; never_read_by_adapter",
        },
        "trans_files_read": trans_files_read,
        "item_count": len(ids),
        "selection_rule": SELECTION_RULE,
        "text_canonicalization": TEXT_CANONICALIZATION,
        "audio_object_count": len(audio_hashes),
        "item_text_object_count": len(text_objects),
        "train_intersection": {
            "executed": True,
            "admitted_train_object_count": len(admitted_train_object_hashes),
            "count": 0,
        },
        "referenced_object_count": len(referenced),
        "referenced_object_set_sha256": sha(canonical(referenced)),
        "admitted_object_count": len(admitted_here),
        "admitted_object_set_sha256": sha(canonical(admitted_here)),
        "items": census_items,
    }
    census["self_sha256"] = sha(canonical(census))
    return census


def verify_census(census: dict[str, Any]) -> None:
    body = dict(census)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError("CENSUS_SELF_SHA256_DRIFT_REFUSED")
    if (
        census.get("schema_version") != CENSUS_SCHEMA
        or census.get("result") != "PASS"
        or census.get("item_count") != EXPECTED_ITEM_COUNT
        or census.get("source", {}).get("audio_selected_set_sha256") != AUDIO_SELECTED_SET_SHA256
        or census.get("selection_rule") != SELECTION_RULE
        or census.get("train_intersection", {}).get("count") != 0
        or census.get("train_intersection", {}).get("executed") is not True
        or len(census.get("items", [])) != EXPECTED_ITEM_COUNT
    ):
        raise ValueError("CENSUS_CONTRACT_DRIFT_REFUSED")


def build_admission_plan(census: dict[str, Any], *, payloads_by_sha: dict[str, bytes]) -> dict[str, Any]:
    """Validate every transcript payload against the census before any custody path exists."""

    verify_census(census)
    text_files: list[dict[str, Any]] = []
    for item in census["items"]:
        text = item["item_text_object"]
        digest = text["sha256"]
        payload = payloads_by_sha.get(digest)
        if not isinstance(payload, bytes) or sha(payload) != digest or len(payload) != text["byte_count"]:
            raise ValueError(f"ITEM_TEXT_PAYLOAD_DRIFT_REFUSED:{item['item_id']}")
        text_files.append({
            "path": f"transcripts/{digest[:2]}/{digest}.json",
            "bytes": text["byte_count"],
            "sha256": digest,
            "source": {"utterance_id": item["item_id"]},
        })
    text_files.sort(key=lambda row: row["sha256"])
    if len(text_files) != EXPECTED_ITEM_COUNT:
        raise ValueError("ITEM_TEXT_TOTALITY_REFUSED")
    admitted = sorted(row["sha256"] for row in text_files)
    if sha(canonical(admitted)) != census["admitted_object_set_sha256"]:
        raise ValueError("ADMITTED_OBJECT_SET_DRIFT_REFUSED")
    return {
        "schema_version": PLAN_SCHEMA,
        "result": "PASS",
        "selection_rule": SELECTION_RULE,
        "census_self_sha256": census["self_sha256"],
        "license_sha256": LICENSE_SHA256,
        "seed_tar_sha256": SEED_TAR_SHA256,
        "audio_selected_set_sha256": AUDIO_SELECTED_SET_SHA256,
        "split": "heldout",
        "item_count": EXPECTED_ITEM_COUNT,
        "admitted_object_count": len(admitted),
        "selected_set_sha256": census["admitted_object_set_sha256"],
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "audio_objects_reference": "predecessor dataset; never re-admitted",
        "train_exclusion_assertion": "executed_pass",
        "rows": [
            {"domain": "text", "source_id": TEXT_SOURCE_ID, "catalog_source_id": CATALOG_TEXT_SOURCE_ID, "file_count": len(text_files)},
        ],
        "text_files": text_files,
    }


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _connector(
    *, source_id: str, files: list[dict[str, Any]], dest_root: Path,
    license_raw: bytes, upstream_url: str, fetched_at: str,
) -> bytes:
    rows = sorted(
        ({"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in files),
        key=lambda row: (row["path"], row["sha256"]),
    )
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "source_id": source_id,
        "canonical_url": upstream_url,
        "fetched_at": fetched_at,
        "license": license_raw.decode("utf-8"),
        "dest_root": str(dest_root.resolve()),
        "total_bytes": sum(row["bytes"] for row in rows),
        "sha256_manifest": sha("\n".join(sorted(row["sha256"] for row in rows)).encode()),
        "files": rows,
    }
    return json.dumps(connector, sort_keys=True, indent=2).encode() + b"\n"


def write_admission_artifacts(
    *,
    plan: dict[str, Any],
    payloads_by_sha: dict[str, bytes],
    license_raw: bytes,
    output_root: Path,
    text_connector_path: Path,
    admission_receipt_path: Path,
    fetched_at: str,
) -> tuple[bytes, bytes]:
    """Create custody only after the complete read-only plan has passed."""

    if output_root.exists() or text_connector_path.exists() or admission_receipt_path.exists():
        raise ValueError("NO_OVERWRITE_REFUSED")
    if not fetched_at or "T" not in fetched_at or not fetched_at.endswith("Z"):
        raise ValueError("FETCHED_AT_REFUSED")
    output_root.mkdir(parents=True, exist_ok=False)
    text_root = output_root / "transcripts"
    for row in plan["text_files"]:
        write_new(text_root / Path(row["path"]), payloads_by_sha[row["sha256"]])
    text_raw = _connector(
        source_id=TEXT_SOURCE_ID, files=plan["text_files"], dest_root=text_root,
        license_raw=license_raw, upstream_url=SOURCE_URL, fetched_at=fetched_at,
    )
    admission = dict(plan)
    admission["schema_version"] = ADMISSION_RECEIPT_SCHEMA
    admission["text_connector_receipt_raw_sha256"] = sha(text_raw)
    admission["total_bytes"] = json.loads(text_raw)["total_bytes"]
    admission["self_sha256"] = sha(canonical(admission))
    admission_raw = json.dumps(admission, sort_keys=True, indent=2).encode() + b"\n"
    write_new(text_connector_path, text_raw)
    write_new(admission_receipt_path, admission_raw)
    return text_raw, admission_raw


def build_projection_spec(
    *, text_connector_path: Path, text_connector_raw: bytes,
    admission_receipt_path: Path, admission_receipt_raw: bytes,
    census_path: Path, census_raw: bytes, audio_census_path: Path, license_path: Path,
    tokenizer_sha256: str, created_at_ms: int,
) -> bytes:
    if len(tokenizer_sha256) != 64 or any(c not in "0123456789abcdef" for c in tokenizer_sha256):
        raise ValueError("TOKENIZER_SHA256_REFUSED")
    if isinstance(created_at_ms, bool) or not isinstance(created_at_ms, int) or created_at_ms < 0:
        raise ValueError("CREATED_AT_MS_REFUSED")
    supporting = [
        {"path": str(admission_receipt_path.resolve()), "sha256": sha(admission_receipt_raw)},
        {"path": str(census_path.resolve()), "sha256": sha(census_raw)},
        {"path": str(audio_census_path.resolve()), "sha256": AUDIO_CENSUS_RAW_SHA256},
        {"path": str(license_path.resolve()), "sha256": LICENSE_SHA256},
    ]
    spec = {
        "schema_version": "ember-issue1581-catalog-projection-spec-v1",
        "tokenizer_sha256": tokenizer_sha256,
        "created_at_ms": created_at_ms,
        "rows": [{
            "receipt_path": str(text_connector_path.resolve()),
            "expected_receipt_sha256": sha(text_connector_raw),
            "source_id": CATALOG_TEXT_SOURCE_ID,
            "expected_source_selector": TEXT_SOURCE_ID,
            "expected_license_text_sha256": LICENSE_SHA256,
            "domain": "text",
            "split": "heldout",
            "supporting_receipts": supporting,
        }],
    }
    return json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"


def _catalog_binding(
    census: dict[str, Any], catalog_export_raw: bytes, dataset_ids: list[str],
) -> dict[str, Any]:
    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AUDIO_TEXT_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list) or not dataset_ids:
        raise ValueError("AUDIO_TEXT_CATALOG_EXPORT_SCHEMA_REFUSED")
    for dataset_id in dataset_ids:
        if not any(
            isinstance(row, dict)
            and row.get("kind") == "dataset_version"
            and row.get("id") == dataset_id
            and row.get("state") == "admitted"
            for row in records
        ):
            raise ValueError(f"AUDIO_TEXT_HELDOUT_DATASET_MISSING_REFUSED:{dataset_id}")
    membership_ids = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "version_membership"
        and edge.get("from_id") in dataset_ids
    }
    memberships = {
        row["id"]: row for row in records
        if isinstance(row, dict) and row.get("kind") == "membership" and row.get("id") in membership_ids
    }
    object_ids = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in membership_ids
    }
    expected_audio = {f"sha256:{item['audio_object']['sha256']}" for item in census["items"]}
    expected_texts = {f"sha256:{item['item_text_object']['sha256']}" for item in census["items"]}
    expected = expected_audio | expected_texts
    if (
        len(memberships) != len(membership_ids)
        or any(
            row.get("split") != "heldout"
            or row.get("admission_state") != "admitted"
            or row.get("domain") not in {"audio", "text"}
            for row in memberships.values()
        )
        or not expected <= object_ids
    ):
        missing = sorted(expected - object_ids)[:3]
        raise ValueError(f"AUDIO_TEXT_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:{len(expected & object_ids)}/{len(expected)}:{missing}")
    return {
        "dataset_ids": sorted(dataset_ids),
        "catalog_export_raw_sha256": sha(catalog_export_raw),
        "membership_count": len(memberships),
        "referenced_object_count": len(expected),
        "object_set_sha256": sha(canonical(sorted(expected))),
    }


def _verified_predecessor_contract(raw: bytes, census: dict[str, Any]) -> dict[str, Any]:
    try:
        contract = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("PREDECESSOR_CONTRACT_UNREADABLE_REFUSED") from error
    body = dict(contract) if isinstance(contract, dict) else {}
    claimed = body.pop("self_sha256", None)
    if not body or claimed != sha(canonical(body)):
        raise ValueError("PREDECESSOR_CONTRACT_SELF_SHA256_DRIFT_REFUSED")
    frozen = contract.get("frozen_items")
    if (
        contract.get("schema_version") != PREDECESSOR_CONTRACT_SCHEMA
        or contract.get("result") != "PASS"
        or not isinstance(frozen, list)
        or contract.get("totality") != {"expected": EXPECTED_ITEM_COUNT, "observed": EXPECTED_ITEM_COUNT, "complete": True}
    ):
        raise ValueError("PREDECESSOR_CONTRACT_TOTALITY_REFUSED")
    golds = {}
    for row in frozen:
        if not isinstance(row, dict) or not isinstance(row.get("gold_object_sha256"), str):
            raise ValueError("PREDECESSOR_CONTRACT_ITEM_SCHEMA_REFUSED")
        golds[row["gold_object_sha256"]] = row.get("byte_count")
    expected = {item["audio_object"]["sha256"]: item["audio_object"]["byte_count"] for item in census["items"]}
    if golds != expected:
        raise ValueError("PREDECESSOR_AUDIO_COVERAGE_REFUSED")
    return contract


def build_audio_text_contract(
    census: dict[str, Any], *, text_connector_raw: bytes, predecessor_connector_raw: bytes,
    predecessor_contract_raw: bytes, catalog_export_raw: bytes | None = None,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    verify_census(census)
    try:
        predecessor = json.loads(predecessor_connector_raw)
        text_connector = json.loads(text_connector_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AUDIO_TEXT_CONNECTOR_UNREADABLE_REFUSED") from error
    for connector, source_id in (
        (predecessor, PREDECESSOR_AUDIO_SOURCE_ID),
        (text_connector, TEXT_SOURCE_ID),
    ):
        if connector.get("schema") != "corpus-connector-receipt-v1" or connector.get("source_id") != source_id:
            raise ValueError(f"AUDIO_TEXT_CONNECTOR_IDENTITY_REFUSED:{source_id}")
    if sha(predecessor_connector_raw) != census["source"]["predecessor_connector_receipt_raw_sha256"]:
        raise ValueError("AUDIO_TEXT_PREDECESSOR_CONNECTOR_BINDING_REFUSED")
    audio = {item["audio_object"]["sha256"] for item in census["items"]}
    texts = {item["item_text_object"]["sha256"] for item in census["items"]}
    if {row["sha256"] for row in predecessor["files"]} != audio:
        raise ValueError("AUDIO_TEXT_PREDECESSOR_COVERAGE_REFUSED")
    if {row["sha256"] for row in text_connector["files"]} != texts:
        raise ValueError("AUDIO_TEXT_CONNECTOR_COVERAGE_REFUSED")
    predecessor_contract = _verified_predecessor_contract(predecessor_contract_raw, census)
    if (catalog_export_raw is None) != (dataset_ids is None):
        raise ValueError("AUDIO_TEXT_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
    frozen_items = [
        {
            "item_id": item["item_id"],
            "gold_item_sha256": item["gold_item_sha256"],
            "audio_object": dict(item["audio_object"]),
            "item_text_object": dict(item["item_text_object"]),
        }
        for item in census["items"]
    ]
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA,
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": TASK_ID,
            "consumes": ["audio_payload_bytes", "transcript_text_payload_bytes"],
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
            "prediction": "sha256(audio_payload_bytes + transcript_text_payload_bytes)",
            "scorer": "exact_match(prediction, gold_item_sha256)",
        },
        "source": {
            "benchmark_id": "LibriSpeech",
            "subset": SOURCE_SUBSET,
            "source_url": SOURCE_URL,
            "seed_tar_sha256": SEED_TAR_SHA256,
            "connector_receipt_raw_sha256s": sorted([sha(text_connector_raw), sha(predecessor_connector_raw)]),
            "connector_receipts": {
                "transcripts": sha(text_connector_raw),
                "predecessor_audio": sha(predecessor_connector_raw),
            },
            "predecessor_contract_self_sha256": predecessor_contract["self_sha256"],
            "census_self_sha256": census["self_sha256"],
            "license_sha256": LICENSE_SHA256,
            "audio_census_raw_sha256": AUDIO_CENSUS_RAW_SHA256,
            "audio_selected_set_sha256": AUDIO_SELECTED_SET_SHA256,
            "speaker_chapter_metadata_access": "identity_only; never_read_by_adapter",
            "prediction_custody_access": "forbidden",
        },
        "text_canonicalization": TEXT_CANONICALIZATION,
        "selection_rule": SELECTION_RULE,
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
        "frozen_items": frozen_items,
        "totality": {
            "expected": EXPECTED_ITEM_COUNT,
            "observed": len(frozen_items),
            "complete": len(frozen_items) == EXPECTED_ITEM_COUNT,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if catalog_export_raw is not None and dataset_ids is not None:
        contract["catalog_binding"] = _catalog_binding(census, catalog_export_raw, dataset_ids)
    contract["self_sha256"] = sha(canonical(contract))
    return contract


def _catalog_rows(catalog: Path, split: str) -> list[tuple[str, str | None]]:
    connection = sqlite3.connect(
        catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
    )
    try:
        return connection.execute(
            """
            SELECT json_extract(m.payload_json, '$.exact_sha256'),
                   lower(json_extract(o.payload_json, '$.media_type'))
            FROM data_catalog_records AS m
            JOIN data_catalog_records AS o
              ON o.kind = 'immutable_object'
             AND o.record_id = 'sha256:' || json_extract(m.payload_json, '$.exact_sha256')
            WHERE m.kind = 'membership'
              AND json_extract(m.payload_json, '$.admission_state') = 'admitted'
              AND json_extract(m.payload_json, '$.split') = ?
            """,
            (split,),
        ).fetchall()
    finally:
        connection.close()


def read_admitted_train_object_hashes(catalog: Path) -> set[str]:
    rows = _catalog_rows(catalog, "train")
    audio = {digest for digest, media in rows if isinstance(media, str) and media.startswith("audio/")}
    if len(audio) != EXPECTED_ADMITTED_TRAIN_AUDIO_COUNT:
        raise ValueError(f"TRAIN_AUDIO_CATALOG_COUNT_DRIFT_REFUSED:{len(audio)}")
    return {digest for digest, _media in rows}


def read_admitted_heldout_audio_hashes(catalog: Path) -> set[str]:
    hashes = {
        digest for digest, media in _catalog_rows(catalog, "heldout")
        if isinstance(media, str) and media.startswith("audio/")
    }
    if len(hashes) != EXPECTED_ADMITTED_HELDOUT_AUDIO_COUNT:
        raise ValueError(f"HELDOUT_AUDIO_CATALOG_COUNT_DRIFT_REFUSED:{len(hashes)}")
    return hashes


def payloads_from_items(items: list[dict[str, Any]]) -> dict[str, bytes]:
    return {item["text_sha256"]: item["text_payload"] for item in items}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-tar", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--audio-census", type=Path, required=True, help="the #2120 heldout audio candidate census")
    parser.add_argument("--predecessor-connector-receipt", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True, help="census output (admit) or existing census (contract)")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--text-connector-receipt", type=Path)
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--fetched-at")
    parser.add_argument("--projection-spec", type=Path)
    parser.add_argument("--tokenizer-sha256")
    parser.add_argument("--created-at-ms", type=int)
    parser.add_argument("--text-connector-for-contract", type=Path)
    parser.add_argument("--predecessor-contract", type=Path)
    parser.add_argument("--catalog-export", type=Path)
    parser.add_argument("--dataset-id", action="append")
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    try:
        license_raw = args.license.read_bytes()
        audio_census_raw = args.audio_census.read_bytes()
        predecessor_raw = args.predecessor_connector_receipt.read_bytes()
        items, trans_files_read = read_transcripts(args.seed_tar, audio_census_raw)
        audio_payloads = read_predecessor_audio_payloads(predecessor_raw, items)
        census = build_census(
            items=items,
            trans_files_read=trans_files_read,
            license_raw=license_raw,
            audio_census_raw=audio_census_raw,
            predecessor_connector_raw=predecessor_raw,
            audio_payloads=audio_payloads,
            admitted_train_object_hashes=read_admitted_train_object_hashes(args.catalog),
            admitted_heldout_audio_hashes=read_admitted_heldout_audio_hashes(args.catalog),
        )
        census_raw = json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"
        if args.census.exists():
            if args.census.read_bytes() != census_raw:
                raise ValueError("CENSUS_DRIFT_FROM_RECORDED_REFUSED")
        else:
            write_new(args.census, census_raw)
        payloads = payloads_from_items(items)
        plan = build_admission_plan(census, payloads_by_sha=payloads)
        if args.plan is not None:
            plan_for_receipt = dict(plan)
            plan_for_receipt["self_sha256"] = sha(canonical(plan_for_receipt))
            write_new(args.plan, json.dumps(plan_for_receipt, sort_keys=True, indent=2).encode() + b"\n")
        artifact_values = [args.output_root, args.text_connector_receipt, args.admission_receipt, args.fetched_at]
        text_raw = None
        if any(value is not None for value in artifact_values):
            if any(value is None for value in artifact_values):
                raise ValueError("ADMISSION_ARTIFACT_ARGUMENT_TOTALITY_REFUSED")
            text_raw, admission_raw = write_admission_artifacts(
                plan=plan,
                payloads_by_sha=payloads,
                license_raw=license_raw,
                output_root=args.output_root,
                text_connector_path=args.text_connector_receipt,
                admission_receipt_path=args.admission_receipt,
                fetched_at=args.fetched_at,
            )
            projection_values = [args.projection_spec, args.tokenizer_sha256, args.created_at_ms]
            if any(value is not None for value in projection_values):
                if any(value is None for value in projection_values):
                    raise ValueError("PROJECTION_SPEC_ARGUMENT_TOTALITY_REFUSED")
                write_new(args.projection_spec, build_projection_spec(
                    text_connector_path=args.text_connector_receipt,
                    text_connector_raw=text_raw,
                    admission_receipt_path=args.admission_receipt,
                    admission_receipt_raw=admission_raw,
                    census_path=args.census,
                    census_raw=census_raw,
                    audio_census_path=args.audio_census,
                    license_path=args.license,
                    tokenizer_sha256=args.tokenizer_sha256,
                    created_at_ms=args.created_at_ms,
                ))
        if args.contract is not None:
            if args.predecessor_contract is None:
                raise ValueError("AUDIO_TEXT_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
            if text_raw is None:
                if args.text_connector_for_contract is None:
                    raise ValueError("AUDIO_TEXT_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
                text_raw = args.text_connector_for_contract.read_bytes()
            if (args.catalog_export is None) != (args.dataset_id is None):
                raise ValueError("AUDIO_TEXT_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
            contract = build_audio_text_contract(
                census,
                text_connector_raw=text_raw,
                predecessor_connector_raw=predecessor_raw,
                predecessor_contract_raw=args.predecessor_contract.read_bytes(),
                catalog_export_raw=None if args.catalog_export is None else args.catalog_export.read_bytes(),
                dataset_ids=args.dataset_id,
            )
            write_new(args.contract, json.dumps(contract, sort_keys=True, indent=2).encode() + b"\n")
    except (OSError, TypeError, ValueError, KeyError) as error:
        print(f"error: {error!r}" if isinstance(error, KeyError) else f"error: {error}")
        return 2
    print(json.dumps({
        "result": "PASS",
        "item_count": census["item_count"],
        "trans_files_read": census["trans_files_read"],
        "item_text_object_count": census["item_text_object_count"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
