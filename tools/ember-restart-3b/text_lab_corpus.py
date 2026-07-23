# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""L4 manifest gate for planned, non-acquired AI-lab shared-text sources."""
from __future__ import annotations
import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from jsonschema import Draft202012Validator
from typing import Any, Iterable

DOMAINS = ("mathematics", "statistics", "physics", "computer_science", "ml_ai", "training_infrastructure", "formal_logic", "software_engineering", "data_evaluation", "scientific_method", "application_worlds")
LICENSES = {"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-3-Clause", "PDDL-1.0"}
_UNRESOLVED_EVIDENCE = ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"]

def _root(rows: Iterable[dict[str, Any]], split: str) -> str:
    digest=hashlib.sha256(f"ember-text-lab-corpus-v2\0{split}\0".encode())
    for row in sorted((x for x in rows if x["split"] == split), key=lambda x:(x["domain"],x["source_id"])):
        encoded = _admitted_record_bytes(row)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()

_ADMITTED_ROW_KEYS = {"source_id", "domain", "license_spdx", "content_sha256", "l4_receipt", "split", "provenance_origin_id"}
_ADMITTED_RECEIPT_KEYS = {"schema_version", "result", "source_sha256", "provenance_origin_id", "source_descriptor_sha256", "license_evidence_sha256", "policy_sha256", "verifier_sha256", "model_mediated", "borrowed_labels"}

def _admitted_record_bytes(row: dict[str, Any]) -> bytes:
    payload = {name: row[name] for name in ("domain", "split", "source_id", "license_spdx", "content_sha256", "provenance_origin_id", "l4_receipt")}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

_SOURCE_CUSTODY_DESCRIPTOR_KEYS = {
    "source_id", "domain", "split", "source_url", "license_spdx",
    "provenance_origin_id", "human_provenance_basis", "fetched_ts", "selection_rule",
    "expected_source_sha256", "expected_source_bytes",
}
_SOURCE_CUSTODY_RECEIPT_KEYS = {
    "schema_version", "result", "source_id", "domain", "split", "source_url",
    "license_spdx", "provenance_origin_id", "human_provenance_basis", "fetched_ts",
    "selection_rule", "source_descriptor_sha256", "source_sha256", "source_bytes",
    "license_evidence_sha256", "policy_sha256", "verifier_sha256",
}
_WAVE_LICENSES = {
    "public domain": "PDDL-1.0", "cc0-1.0": "CC0-1.0", "cc-by-4.0": "CC-BY-4.0",
    "cc-by-sa 4.0": "CC-BY-SA-4.0", "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-nc 4.0": "CC-BY-NC-4.0", "cc-by-nc-4.0": "CC-BY-NC-4.0",
}
_WAVE_RECEIPT_KEYS = {"source_url", "sha256", "bytes", "license", "human_provenance_basis", "fetched_ts", "selection_rule"}

def source_inventory_descriptor(*, source_id: str, domain: str, split: str, provenance_origin_id: str, receipt_entry: dict[str, Any]) -> dict[str, Any]:
    """Close one operator-authorized wave receipt into a content-bound descriptor."""
    if not isinstance(receipt_entry, dict) or set(receipt_entry) != _WAVE_RECEIPT_KEYS:
        raise ValueError("wave source receipt is not closed")
    license_label = receipt_entry.get("license")
    license_spdx = _WAVE_LICENSES.get(license_label.casefold() if isinstance(license_label, str) else "")
    if license_spdx not in LICENSES:
        raise ValueError("wave source license is not permitted")
    if (not isinstance(source_id, str) or PurePosixPath(source_id).name != source_id
            or "\\" in source_id or source_id in {"", ".", ".."}):
        raise ValueError("wave source ID is invalid")
    if domain not in DOMAINS or split not in {"train", "heldout"} or not isinstance(provenance_origin_id, str) or not provenance_origin_id:
        raise ValueError("wave source identity is invalid")
    raw_sha256 = receipt_entry.get("sha256")
    if not isinstance(raw_sha256, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", raw_sha256) is None or type(receipt_entry.get("bytes")) is not int or receipt_entry["bytes"] <= 0:
        raise ValueError("wave source byte binding is invalid")
    for field in ("source_url", "human_provenance_basis", "fetched_ts", "selection_rule"):
        if not isinstance(receipt_entry.get(field), str) or not receipt_entry[field]:
            raise ValueError("wave source receipt field is invalid")
    timestamp = re.fullmatch(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.[0-9]+)?Z", receipt_entry["fetched_ts"])
    if timestamp is None:
        raise ValueError("wave source timestamp is invalid")
    return {
        "source_id": source_id, "domain": domain, "split": split,
        "source_url": receipt_entry["source_url"], "license_spdx": license_spdx,
        "provenance_origin_id": provenance_origin_id,
        "human_provenance_basis": receipt_entry["human_provenance_basis"],
        "fetched_ts": timestamp.group(1) + "Z", "selection_rule": receipt_entry["selection_rule"],
        "expected_source_sha256": raw_sha256.lower(), "expected_source_bytes": receipt_entry["bytes"],
    }

def record_source_custody(
    *, descriptor: dict[str, Any], raw_bytes: bytes, license_evidence_bytes: bytes,
    policy_bytes: bytes, verifier_bytes: bytes,
) -> dict[str, Any]:
    """Bind acquired source bytes without treating acquisition as L4 admission."""
    if not isinstance(descriptor, dict) or set(descriptor) != _SOURCE_CUSTODY_DESCRIPTOR_KEYS:
        raise ValueError("source custody descriptor is not closed")
    source_id = descriptor.get("source_id")
    if (not isinstance(source_id, str) or PurePosixPath(source_id).name != source_id
            or "\\" in source_id or source_id in {"", ".", ".."}):
        raise ValueError("source custody source ID is invalid")
    if descriptor.get("domain") not in DOMAINS or descriptor.get("split") not in {"train", "heldout"}:
        raise ValueError("source custody domain or split is invalid")
    if descriptor.get("license_spdx") not in LICENSES:
        raise ValueError("source custody license is not permitted")
    for field in ("source_url", "provenance_origin_id", "human_provenance_basis", "fetched_ts", "selection_rule"):
        if not isinstance(descriptor.get(field), str) or not descriptor[field]:
            raise ValueError("source custody descriptor field is invalid")
    if not descriptor["source_url"].startswith("https://"):
        raise ValueError("source custody URL is not HTTPS")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", descriptor["fetched_ts"]):
        raise ValueError("source custody fetched timestamp is invalid")
    if any(not isinstance(value, bytes) or not value for value in (raw_bytes, license_evidence_bytes, policy_bytes, verifier_bytes)):
        raise ValueError("source custody evidence bytes are invalid")
    if not _valid_hash(descriptor.get("expected_source_sha256")) or type(descriptor.get("expected_source_bytes")) is not int or descriptor["expected_source_bytes"] <= 0:
        raise ValueError("source custody expected byte binding is invalid")
    if descriptor["expected_source_sha256"] != _sha_bytes(raw_bytes) or descriptor["expected_source_bytes"] != len(raw_bytes):
        raise ValueError("source custody raw bytes do not match source inventory")
    return {
        "schema_version": "ember-owned-source-custody-v1",
        "result": "ACQUIRED_NOT_ADMITTED",
        **{field: descriptor[field] for field in (
            "source_id", "domain", "split", "source_url", "license_spdx", "provenance_origin_id",
            "human_provenance_basis", "fetched_ts", "selection_rule",
        )},
        "source_descriptor_sha256": _sha_bytes(_canonical_json_bytes(descriptor)),
        "source_sha256": _sha_bytes(raw_bytes),
        "source_bytes": len(raw_bytes),
        "license_evidence_sha256": _sha_bytes(license_evidence_bytes),
        "policy_sha256": _sha_bytes(policy_bytes),
        "verifier_sha256": _sha_bytes(verifier_bytes),
    }

def record_source_custody_file(
    *, descriptor: dict[str, Any], raw_path: Path, license_evidence_bytes: bytes,
    policy_bytes: bytes, verifier_bytes: bytes,
) -> dict[str, Any]:
    """Stream a source file into the same path-free, non-admission custody receipt."""
    if not isinstance(descriptor, dict) or set(descriptor) != _SOURCE_CUSTODY_DESCRIPTOR_KEYS:
        raise ValueError("source custody descriptor is not closed")
    source_id = descriptor.get("source_id")
    if (not isinstance(source_id, str) or PurePosixPath(source_id).name != source_id
            or "\\" in source_id or source_id in {"", ".", ".."}):
        raise ValueError("source custody source ID is invalid")
    if descriptor.get("domain") not in DOMAINS or descriptor.get("split") not in {"train", "heldout"}:
        raise ValueError("source custody domain or split is invalid")
    if descriptor.get("license_spdx") not in LICENSES:
        raise ValueError("source custody license is not permitted")
    for field in ("source_url", "provenance_origin_id", "human_provenance_basis", "fetched_ts", "selection_rule"):
        if not isinstance(descriptor.get(field), str) or not descriptor[field]:
            raise ValueError("source custody descriptor field is invalid")
    if not descriptor["source_url"].startswith("https://"):
        raise ValueError("source custody URL is not HTTPS")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", descriptor["fetched_ts"]):
        raise ValueError("source custody fetched timestamp is invalid")
    if any(not isinstance(value, bytes) or not value for value in (license_evidence_bytes, policy_bytes, verifier_bytes)):
        raise ValueError("source custody evidence bytes are invalid")
    if not _valid_hash(descriptor.get("expected_source_sha256")) or type(descriptor.get("expected_source_bytes")) is not int or descriptor["expected_source_bytes"] <= 0:
        raise ValueError("source custody expected byte binding is invalid")
    path = Path(raw_path)
    if not path.is_file():
        raise ValueError("source custody raw file is unavailable")
    digest = hashlib.sha256(); count = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk); count += len(chunk)
    source_sha256 = digest.hexdigest()
    if descriptor["expected_source_sha256"] != source_sha256 or descriptor["expected_source_bytes"] != count:
        raise ValueError("source custody raw bytes do not match source inventory")
    return {
        "schema_version": "ember-owned-source-custody-v1", "result": "ACQUIRED_NOT_ADMITTED",
        **{field: descriptor[field] for field in (
            "source_id", "domain", "split", "source_url", "license_spdx", "provenance_origin_id",
            "human_provenance_basis", "fetched_ts", "selection_rule",
        )},
        "source_descriptor_sha256": _sha_bytes(_canonical_json_bytes(descriptor)),
        "source_sha256": source_sha256, "source_bytes": count,
        "license_evidence_sha256": _sha_bytes(license_evidence_bytes),
        "policy_sha256": _sha_bytes(policy_bytes), "verifier_sha256": _sha_bytes(verifier_bytes),
    }

_PRE_ADMISSION_SOURCE_KEYS = {"source_id", "split", "transform_id"}
_PRE_ADMISSION_CURSOR_KEYS = {"schema_version", "next_source_id", "next_source_record_index"}
_PRE_ADMISSION_TRANSFORMS = {"utf8_nonblank_lines_v1", "csv_case_citation_v1"}

def _stream_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); count = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk); count += len(chunk)
    return digest.hexdigest(), count

def _pre_admission_sources(*, sources: list[dict[str, Any]], raw_paths: dict[str, Path], source_custody_receipts: dict[str, dict[str, Any]]) -> list[tuple[dict[str, Any], Path, dict[str, Any]]]:
    if not isinstance(sources, list) or not isinstance(raw_paths, dict) or not isinstance(source_custody_receipts, dict):
        raise ValueError("pre-admission source arguments are invalid")
    contexts = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != _PRE_ADMISSION_SOURCE_KEYS:
            raise ValueError("pre-admission source is not closed")
        source_id = source.get("source_id")
        if (not isinstance(source_id, str) or PurePosixPath(source_id).name != source_id or "\\" in source_id
                or source_id in {"", ".", ".."} or source_id in seen):
            raise ValueError("pre-admission source ID is invalid")
        if source.get("split") not in {"train", "heldout"} or source.get("transform_id") not in _PRE_ADMISSION_TRANSFORMS:
            raise ValueError("pre-admission source split or transform is invalid")
        receipt = source_custody_receipts.get(source_id)
        if not isinstance(receipt, dict) or set(receipt) != _SOURCE_CUSTODY_RECEIPT_KEYS or receipt.get("result") != "ACQUIRED_NOT_ADMITTED":
            raise ValueError("pre-admission source custody receipt is invalid")
        if receipt.get("source_id") != source_id or receipt.get("split") != source["split"] or not _valid_hash(receipt.get("source_sha256")) or type(receipt.get("source_bytes")) is not int:
            raise ValueError("pre-admission source receipt binding is invalid")
        path = raw_paths.get(source_id)
        if not isinstance(path, Path) or not path.is_file():
            raise ValueError("pre-admission raw source is unavailable")
        actual_sha256, actual_bytes = _stream_sha256(path)
        if actual_sha256 != receipt["source_sha256"] or actual_bytes != receipt["source_bytes"]:
            raise ValueError("pre-admission raw source bytes do not match custody receipt")
        contexts.append((source, path, receipt)); seen.add(source_id)
    if set(raw_paths) != seen or set(source_custody_receipts) != seen:
        raise ValueError("pre-admission source mapping is not closed")
    return sorted(contexts, key=lambda value: value[0]["source_id"])

def _transform_records(source: dict[str, Any], path: Path, receipt: dict[str, Any]):
    transform_id = source["transform_id"]
    try:
        if transform_id == "utf8_nonblank_lines_v1":
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                text = line.strip()
                if text:
                    yield index, text
        else:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None or set(("case_name", "citations")) - set(reader.fieldnames):
                    raise ValueError("pre-admission CSV source lacks required text fields")
                for index, row in enumerate(reader):
                    case_name = row.get("case_name")
                    citations = row.get("citations")
                    if not isinstance(case_name, str) or not isinstance(citations, str):
                        raise ValueError("pre-admission CSV source has malformed row")
                    text = "\n".join(part.strip() for part in (case_name, citations) if part.strip())
                    if text:
                        yield index, text
    except UnicodeError as error:
        raise ValueError("pre-admission source encoding is invalid") from error

def iter_pre_admission_text_records(*, sources: list[dict[str, Any]], raw_paths: dict[str, Path], source_custody_receipts: dict[str, dict[str, Any]], cursor: dict[str, Any] | None = None, emit_cursor: bool = False, max_records_per_source: int | None = None):
    """Yield canonical records from bounded authorized sources, optionally with a resumable cursor."""
    contexts = _pre_admission_sources(sources=sources, raw_paths=raw_paths, source_custody_receipts=source_custody_receipts)
    if max_records_per_source is not None and (type(max_records_per_source) is not int or not 1 <= max_records_per_source <= 65536):
        raise ValueError("pre-admission record bound is invalid")
    if cursor is None:
        next_source_id, next_index = contexts[0][0]["source_id"] if contexts else None, 0
    else:
        if not isinstance(cursor, dict) or set(cursor) != _PRE_ADMISSION_CURSOR_KEYS or cursor.get("schema_version") != "ember-owned-text-transform-cursor-v1" or (cursor.get("next_source_id") is not None and not isinstance(cursor.get("next_source_id"), str)) or type(cursor.get("next_source_record_index")) is not int or cursor["next_source_record_index"] < 0:
            raise ValueError("pre-admission transform cursor is invalid")
        next_source_id, next_index = cursor["next_source_id"], cursor["next_source_record_index"]
        if next_source_id is not None and next_source_id not in {source["source_id"] for source, _, _ in contexts}:
            raise ValueError("pre-admission transform cursor source is invalid")
    active = next_source_id is None
    for position, (source, path, receipt) in enumerate(contexts):
        source_id = source["source_id"]
        if not active:
            if source_id != next_source_id:
                continue
            active = True
        start_index = next_index if source_id == next_source_id else 0
        emitted = 0
        for record_index, text in _transform_records(source, path, receipt):
            if record_index < start_index:
                continue
            if max_records_per_source is not None and emitted >= max_records_per_source:
                break
            emitted += 1
            record = {
                "schema_version": "ember-owned-text-record-v1", "source_id": source_id,
                "split": source["split"], "transform_id": source["transform_id"],
                "source_sha256": receipt["source_sha256"], "source_record_index": record_index,
                "text": text,
            }
            future_source = source_id
            future_index = record_index + 1
            yield (record, {"schema_version": "ember-owned-text-transform-cursor-v1", "next_source_id": future_source, "next_source_record_index": future_index}) if emit_cursor else record
        next_index = 0

def _pre_admission_root(records: list[dict[str, Any]], split: str) -> str:
    digest = hashlib.sha256(f"ember-owned-pre-admission-tranche-v1\0{split}\0".encode("utf-8"))
    for record in records:
        if record["split"] == split:
            encoded = _canonical_json_bytes(record)
            digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
    return digest.hexdigest()

def build_pre_admission_text_tranche(*, sources: list[dict[str, Any]], raw_paths: dict[str, Path], source_custody_receipts: dict[str, dict[str, Any]], output_root: Path, build_id: str, max_records_per_source: int = 4096) -> dict[str, Any]:
    """Write manifest-last deterministic pre-admission JSONL without training admission."""
    if PurePosixPath(build_id).name != build_id or "\\" in build_id or build_id in {"", ".", ".."}:
        raise ValueError("pre-admission build ID is invalid")
    contexts = _pre_admission_sources(sources=sources, raw_paths=raw_paths, source_custody_receipts=source_custody_receipts)
    if type(max_records_per_source) is not int or not 1 <= max_records_per_source <= 65536:
        raise ValueError("pre-admission record bound is invalid")
    root = output_root.resolve(); root.mkdir(parents=True, exist_ok=True)
    staging, final = root / f".{build_id}.staging", root / build_id
    if staging.exists() or final.exists():
        raise ValueError("pre-admission output destination already exists")
    staging.mkdir(); records: list[dict[str, Any]] = []; seen_text: dict[str, str] = {}
    try:
        handles = {split: (staging / f"{split}.jsonl").open("wb") for split in ("train", "heldout")}
        try:
            for record in iter_pre_admission_text_records(sources=sources, raw_paths=raw_paths, source_custody_receipts=source_custody_receipts, max_records_per_source=max_records_per_source):
                text_sha256 = _sha_bytes(record["text"].encode("utf-8"))
                previous = seen_text.get(text_sha256)
                if previous is not None:
                    if previous != record["split"]:
                        raise ValueError("pre-admission cross-split duplicate record")
                    continue
                seen_text[text_sha256] = record["split"]
                encoded = _canonical_json_bytes(record) + b"\n"; handles[record["split"]].write(encoded); records.append(record)
        finally:
            for handle in handles.values(): handle.close()
        source_bindings = [{"source_id": source["source_id"], "split": source["split"], "transform_id": source["transform_id"], "source_custody_receipt_sha256": _sha_bytes(_canonical_json_bytes(receipt)), "source_sha256": receipt["source_sha256"], "source_bytes": receipt["source_bytes"]} for source, _, receipt in contexts]
        manifest = {"schema_version": "ember-owned-pre-admission-tranche-v1", "result": "PRE_ADMISSION_ONLY", "boundary": "NO_L4_ADMISSION_NO_TRAINING", "build_id": build_id, "sources": source_bindings, "train_record_count": sum(record["split"] == "train" for record in records), "heldout_record_count": sum(record["split"] == "heldout" for record in records), "train_root_sha256": _pre_admission_root(records, "train"), "heldout_root_sha256": _pre_admission_root(records, "heldout")}
        if not records or not manifest["train_record_count"] or not manifest["heldout_record_count"]:
            raise ValueError("pre-admission tranche requires train and heldout records")
        (staging / "manifest.json").write_bytes(_canonical_json_bytes(manifest)); staging.replace(final)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True); raise

_PRE_ADMISSION_MANIFEST_KEYS = {
    "schema_version", "result", "boundary", "build_id", "sources",
    "train_record_count", "heldout_record_count", "train_root_sha256", "heldout_root_sha256",
}
_L4_TRANSFORM_RECEIPT_KEYS = {
    "schema_version", "result", "boundary", "pre_admission_manifest_sha256",
    "train_records_sha256", "train_records_bytes", "heldout_records_sha256",
    "heldout_records_bytes", "train_record_count", "heldout_record_count",
    "train_root_sha256", "heldout_root_sha256", "source_custody_receipts",
    "policy_sha256", "verifier_sha256", "model_mediated", "borrowed_labels",
}

def _read_pre_admission_records(path: Path, split: str) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("pre-admission tranche records are invalid") from error
    exact = {"schema_version", "source_id", "split", "transform_id", "source_sha256", "source_record_index", "text"}
    if not rows or any(not isinstance(row, dict) or set(row) != exact or row.get("schema_version") != "ember-owned-text-record-v1" or row.get("split") != split or not isinstance(row.get("text"), str) or not row["text"] or not _valid_hash(row.get("source_sha256")) or type(row.get("source_record_index")) is not int or row["source_record_index"] < 0 for row in rows):
        raise ValueError("pre-admission tranche records are invalid")
    return rows

def admit_pre_admission_text_tranche(*, tranche_root: Path, source_custody_receipts: dict[str, dict[str, Any]], policy_bytes: bytes, verifier_bytes: bytes) -> dict[str, Any]:
    """Issue an L4 transform receipt only after revalidating one manifest-last tranche."""
    if not isinstance(source_custody_receipts, dict) or any(not isinstance(value, dict) or set(value) != _SOURCE_CUSTODY_RECEIPT_KEYS for value in source_custody_receipts.values()):
        raise ValueError("L4 transform custody receipt map is invalid")
    if any(not isinstance(value, bytes) or not value for value in (policy_bytes, verifier_bytes)):
        raise ValueError("L4 transform evidence bytes are invalid")
    root = Path(tranche_root).resolve()
    manifest_path = root / "manifest.json"
    if not root.is_dir() or not manifest_path.is_file() or any(path.name not in {"manifest.json", "train.jsonl", "heldout.jsonl"} for path in root.iterdir() if path.is_file()):
        raise ValueError("L4 transform tranche layout is invalid")
    try:
        manifest_bytes = manifest_path.read_bytes(); manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("L4 transform manifest is invalid") from error
    if not isinstance(manifest, dict) or set(manifest) != _PRE_ADMISSION_MANIFEST_KEYS or manifest.get("schema_version") != "ember-owned-pre-admission-tranche-v1" or manifest.get("result") != "PRE_ADMISSION_ONLY" or manifest.get("boundary") != "NO_L4_ADMISSION_NO_TRAINING":
        raise ValueError("L4 transform manifest is invalid")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources or {item.get("source_id") for item in sources if isinstance(item, dict)} != set(source_custody_receipts):
        raise ValueError("L4 transform custody receipt map is invalid")
    expected_source = {"source_id", "split", "transform_id", "source_custody_receipt_sha256", "source_sha256", "source_bytes"}
    for binding in sources:
        if not isinstance(binding, dict) or set(binding) != expected_source:
            raise ValueError("L4 transform source binding is invalid")
        receipt = source_custody_receipts.get(binding["source_id"])
        if receipt is None or receipt.get("result") != "ACQUIRED_NOT_ADMITTED" or receipt.get("split") != binding.get("split") or receipt.get("source_sha256") != binding.get("source_sha256") or receipt.get("source_bytes") != binding.get("source_bytes") or binding.get("source_custody_receipt_sha256") != _sha_bytes(_canonical_json_bytes(receipt)):
            raise ValueError("L4 transform custody receipt does not match tranche")
    train_path, heldout_path = root / "train.jsonl", root / "heldout.jsonl"
    if not train_path.is_file() or not heldout_path.is_file():
        raise ValueError("L4 transform tranche records are missing")
    train, heldout = _read_pre_admission_records(train_path, "train"), _read_pre_admission_records(heldout_path, "heldout")
    records = train + heldout
    if manifest.get("train_record_count") != len(train) or manifest.get("heldout_record_count") != len(heldout) or manifest.get("train_root_sha256") != _pre_admission_root(records, "train") or manifest.get("heldout_root_sha256") != _pre_admission_root(records, "heldout"):
        raise ValueError("L4 transform manifest records do not match")
    text_hashes = [ _sha_bytes(row["text"].encode("utf-8")) for row in records ]
    if len(text_hashes) != len(set(text_hashes)):
        raise ValueError("L4 transform records overlap")
    train_sha, train_bytes = _stream_sha256(train_path); heldout_sha, heldout_bytes = _stream_sha256(heldout_path)
    return {
        "schema_version": "ember-owned-text-l4-transform-receipt-v1", "result": "VERIFIED",
        "boundary": "L4_TRANSFORM_ADMITTED_NO_TRAINING",
        "pre_admission_manifest_sha256": _sha_bytes(manifest_bytes),
        "train_records_sha256": train_sha, "train_records_bytes": train_bytes,
        "heldout_records_sha256": heldout_sha, "heldout_records_bytes": heldout_bytes,
        "train_record_count": len(train), "heldout_record_count": len(heldout),
        "train_root_sha256": manifest["train_root_sha256"], "heldout_root_sha256": manifest["heldout_root_sha256"],
        "source_custody_receipts": [
            {"source_id": binding["source_id"], "sha256": binding["source_custody_receipt_sha256"]}
            for binding in sorted(sources, key=lambda item: item["source_id"])
        ],
        "policy_sha256": _sha_bytes(policy_bytes), "verifier_sha256": _sha_bytes(verifier_bytes),
        "model_mediated": False, "borrowed_labels": False,
    }

def _validate_admitted_receipt(receipt: object, *, content_sha256: str, origin_id: str) -> None:
    expected_hashes = ("source_descriptor_sha256", "license_evidence_sha256", "policy_sha256", "verifier_sha256")
    if not isinstance(receipt, dict) or set(receipt) != _ADMITTED_RECEIPT_KEYS:
        raise ValueError("source L4 provenance receipt is invalid")
    if receipt.get("schema_version") != "ember-text-source-receipt-v2" or receipt.get("result") != "VERIFIED":
        raise ValueError("source L4 provenance receipt is invalid")
    if receipt.get("source_sha256") != content_sha256 or receipt.get("provenance_origin_id") != origin_id:
        raise ValueError("source L4 provenance receipt does not bind source origin")
    for name in expected_hashes:
        if not _valid_hash(receipt.get(name)):
            raise ValueError("source L4 provenance receipt hash is invalid")
    if receipt.get("model_mediated") is not False or receipt.get("borrowed_labels") is not False:
        raise ValueError("source L4 provenance receipt permits forbidden signal")

def _validate(rows: list[dict[str, Any]], frozen: set[str]) -> None:
    if not rows: raise ValueError("text corpus source set is empty")
    seen=set(); source_ids=set(); by_domain_split={(domain, split):0 for domain in DOMAINS for split in ("train", "heldout")}; origins={(domain, split):set() for domain in DOMAINS for split in ("train", "heldout")}
    for row in rows:
        if not isinstance(row,dict) or set(row) != _ADMITTED_ROW_KEYS: raise ValueError("source row schema is invalid")
        domain=row["domain"]; content=row["content_sha256"]; receipt=row["l4_receipt"]
        source_id=row["source_id"]; origin_id=row["provenance_origin_id"]
        if not isinstance(source_id, str) or not source_id or source_id in source_ids: raise ValueError("source ID is not globally unique")
        if not isinstance(origin_id, str) or not origin_id: raise ValueError("source provenance origin is invalid")
        if domain not in DOMAINS or row["split"] not in {"train","heldout"}: raise ValueError("source domain or split is invalid")
        if row["license_spdx"] not in LICENSES: raise ValueError("source license is not permitted")
        if not isinstance(content,str) or len(content)!=64 or content.lower()!=content: raise ValueError("source content hash is invalid")
        if content in seen: raise ValueError("duplicate source content is forbidden")
        if content in frozen: raise ValueError("source contaminates frozen eval")
        _validate_admitted_receipt(receipt, content_sha256=content, origin_id=origin_id)
        seen.add(content); source_ids.add(source_id); by_domain_split[(domain, row["split"])] += 1; origins[(domain, row["split"])].add(origin_id)
    if any(count < 2 for count in by_domain_split.values()): raise ValueError("each charter domain requires two sources in train and heldout")
    if any(len(values) < 2 for values in origins.values()): raise ValueError("each charter split requires two independent provenance origins")
    if any(origins[(domain, "train")] & origins[(domain, "heldout")] for domain in DOMAINS): raise ValueError("train and heldout provenance origins overlap")

def build_manifest(entries: Iterable[dict[str, Any]], *, frozen_eval_hashes: set[str]) -> dict[str, Any]:
    rows=[dict(x) for x in entries]; _validate(rows,frozen_eval_hashes)
    return {"schema_version":"ember-text-lab-corpus-manifest-v2","result":"PREFLIGHT_ONLY","boundary":"NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM","domains":list(DOMAINS),"sources":sorted(rows,key=lambda x:(x["domain"],x["source_id"])),"frozen_eval_hashes":sorted(frozen_eval_hashes),"train_root_sha256":_root(rows,"train"),"heldout_root_sha256":_root(rows,"heldout")}

def validate_manifest(manifest: dict[str, Any], *, frozen_eval_hashes: set[str]) -> dict[str,str]:
    if not isinstance(manifest,dict) or manifest.get("schema_version")!="ember-text-lab-corpus-manifest-v2" or manifest.get("result")!="PREFLIGHT_ONLY": raise ValueError("text corpus manifest is not preflight-only")
    rows=manifest.get("sources")
    if manifest.get("domains") != list(DOMAINS) or not isinstance(rows,list) or set(manifest.get("frozen_eval_hashes",[])) != frozen_eval_hashes: raise ValueError("text corpus manifest binding is invalid")
    _validate(rows,frozen_eval_hashes)
    if manifest.get("train_root_sha256") != _root(rows,"train") or manifest.get("heldout_root_sha256") != _root(rows,"heldout"): raise ValueError("text corpus split root does not match")
    return {"result":"PREFLIGHT_ONLY","train_root_sha256":manifest["train_root_sha256"],"heldout_root_sha256":manifest["heldout_root_sha256"]}

def admitted_token_shard_sources(manifest: dict[str, Any], *, raw_root: Path) -> list[tuple[str, list[Path]]]:
    """Resolve only hash-bound admitted JSONL sources in canonical source-ID order."""
    frozen = manifest.get("frozen_eval_hashes") if isinstance(manifest, dict) else None
    if not isinstance(frozen, list) or any(not _valid_hash(value) for value in frozen):
        raise ValueError("admitted source manifest frozen evaluation binding is invalid")
    validate_manifest(manifest, frozen_eval_hashes=set(frozen))
    root = raw_root.resolve()
    if not root.is_dir():
        raise ValueError("admitted source root is unavailable")
    resolved: list[tuple[str, list[Path]]] = []
    for row in sorted(manifest["sources"], key=lambda item: item["source_id"]):
        source_id = row["source_id"]
        if PurePosixPath(source_id).name != source_id or "\\" in source_id or source_id in {"", ".", ".."}:
            raise ValueError("admitted source ID is not a single safe filename")
        path = (root / f"{source_id}.jsonl").resolve()
        if path.parent != root or not path.is_file():
            raise ValueError("admitted raw source is missing or escapes its root")
        payload = path.read_bytes()
        if _sha_bytes(payload) != row["content_sha256"]:
            raise ValueError("admitted raw source bytes do not match provenance receipt")
        try:
            documents = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("admitted raw source is not valid UTF-8 JSONL") from error
        if not documents or any(not isinstance(document, dict) or not isinstance(document.get("text"), str) or not document["text"] for document in documents):
            raise ValueError("admitted raw source lacks nonempty text documents")
        resolved.append((source_id, [path]))
    return resolved


def build_admitted_token_shards(manifest: dict[str, Any], *, raw_root: Path, shard_writer: Any, writer_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Feed the canonical TOKEN-SHARDS-V0 producer only verified raw bytes."""
    if not callable(shard_writer) or not isinstance(writer_kwargs, dict):
        raise ValueError("admitted token shard builder arguments are invalid")
    if "sources" in writer_kwargs:
        raise ValueError("admitted token shard builder does not permit source override")
    sources = admitted_token_shard_sources(manifest, raw_root=raw_root)
    source_manifest_premise = {
        "schema_version": manifest["schema_version"],
        "sha256": _sha_bytes(_canonical_json_bytes(manifest)),
        "source_ids": [source_id for source_id, _ in sources],
        "train_root_sha256": manifest["train_root_sha256"],
        "heldout_root_sha256": manifest["heldout_root_sha256"],
    }
    result = shard_writer(sources=sources, source_manifest_premise=source_manifest_premise,
                          **writer_kwargs)
    if not isinstance(result, dict):
        raise ValueError("admitted token shard writer returned an invalid receipt")
    if result.get("ticket") != "TOKEN-SHARDS-V0" or not isinstance(result.get("per_source"), dict) or set(result["per_source"]) != {name for name, _ in sources}:
        raise ValueError("admitted token shard writer receipt does not bind the canonical source set")
    return result

def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def publish_admitted_token_shards(manifest: dict[str, Any], *, raw_root: Path, output_root: Path, build_id: str, shard_writer: Any, writer_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Publish a verified shard set only by manifest-last atomic promotion."""
    if PurePosixPath(build_id).name != build_id or "\\" in build_id or build_id in {"", ".", ".."}:
        raise ValueError("admitted shard build ID is not a single safe filename")
    if not isinstance(writer_kwargs, dict) or "out_dir" in writer_kwargs:
        raise ValueError("admitted shard publication controls its staging output")
    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{build_id}.staging"
    final = root / build_id
    if staging.exists() or final.exists():
        raise ValueError("admitted shard publication destination already exists")
    staging.mkdir()
    try:
        produced = build_admitted_token_shards(manifest, raw_root=raw_root, shard_writer=shard_writer, writer_kwargs={**writer_kwargs, "out_dir": staging})
        shards = produced.get("shards")
        if not isinstance(shards, list) or not shards:
            raise ValueError("admitted token shard receipt lacks shard records")
        checked = []
        for row in shards:
            if not isinstance(row, dict) or set(row) != {"name", "sha256", "n_tokens"}:
                raise ValueError("admitted token shard record is not closed")
            name, digest, count = row["name"], row["sha256"], row["n_tokens"]
            if PurePosixPath(name).name != name or "\\" in name or not _valid_hash(digest) or type(count) is not int or count < 0:
                raise ValueError("admitted token shard record is invalid")
            payload = (staging / name)
            if payload.parent != staging or not payload.is_file() or _sha_bytes(payload.read_bytes()) != digest:
                raise ValueError("admitted token shard bytes do not match receipt")
            checked.append({"name": name, "sha256": digest, "n_tokens": count})
        receipt = {"schema_version": "ember-owned-text-shard-build-v1", "result": "MEASURED", "build_id": build_id, "source_manifest_sha256": _sha_bytes(_canonical_json_bytes(manifest)), "token_shards_receipt_sha256": _sha_bytes(_canonical_json_bytes(produced)), "shards": checked}
        (staging / "token-shards-v0.json").write_bytes(_canonical_json_bytes(produced))
        (staging / "build-receipt.json").write_bytes(_canonical_json_bytes(receipt))
        staging.replace(final)
        return receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_AUTHORITY_INDEX = "data/ember-restart-3b/text-lab-authority-index-v1.json"

def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _authority_split_root(rows: Iterable[dict[str, Any]], split: str) -> str:
    digest = hashlib.sha256(f"ember-text-lab-candidate-descriptor-v2\0{split}\0".encode("utf-8"))
    fields = ("domain", "split", "source_id", "admission", "required_evidence", "allowed_license_spdx")
    for row in sorted((item for item in rows if item.get("split") == split), key=lambda item: (item.get("domain", ""), item.get("source_id", ""))):
        descriptor = {field: row.get(field) for field in fields}
        encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()

def _path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("authority path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("authority path is not exact repository-relative")
    path = (root / relative).resolve()
    if not path.is_file() or root.resolve() not in path.parents:
        raise ValueError("authority path is absent or escapes root")
    return path

def _bound_json(root: Path, binding: object) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema"}:
        raise ValueError("authority artifact binding is invalid")
    expected = binding["sha256"]
    if not isinstance(expected, str) or _HEX.fullmatch(expected) is None:
        raise ValueError("authority hash is invalid")
    payload = _path(root, binding["path"]).read_bytes()
    if _sha_bytes(payload) != expected:
        raise ValueError("authority bytes do not match the bound hash")
    value = json.loads(payload)
    if not isinstance(value, dict): raise ValueError("authority JSON must be an object")
    schema = binding["schema"]
    if not isinstance(schema, dict): raise ValueError("authority schema binding is invalid")
    schema_bytes = _path(root, schema.get("path")).read_bytes()
    if _sha_bytes(schema_bytes) != schema.get("sha256"): raise ValueError("authority schema bytes are not bound")
    schema_value=json.loads(schema_bytes)
    if schema_value.get("$schema") != "https://json-schema.org/draft/2020-12/schema": raise ValueError("authority schema is not Draft 2020-12")
    errors=sorted(Draft202012Validator(schema_value).iter_errors(value),key=str)
    if errors: raise ValueError("authority schema rejects bytes: "+errors[0].message)
    return payload,value

def _commit(root: Path) -> str:
    value=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],text=True,capture_output=True,check=False).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}",value) is None: raise ValueError("exact source commit is unavailable")
    return value

def _protected_identifier_sets(root: Path, protected: list[object]) -> dict[str, set[str]]:
    if not protected:
        raise ValueError("protected evaluation registry is empty")
    expected = {"benchmark_id", "custody_manifest_path", "custody_manifest_sha256", "custody_state", "evidence", "protected_identifiers"}
    result = {"origin_id": set(), "snapshot_sha256": set(), "chunk_sha256": set(), "content_sha256": set()}
    seen: set[str] = set()
    for entry in protected:
        if not isinstance(entry, dict) or set(entry) != expected or not isinstance(entry["benchmark_id"], str) or entry["benchmark_id"] in seen:
            raise ValueError("protected evaluation registry entry is invalid")
        seen.add(entry["benchmark_id"])
        path = _path(root, entry["custody_manifest_path"])
        payload = path.read_bytes()
        if _sha_bytes(payload) != entry["custody_manifest_sha256"]:
            raise ValueError("protected custody manifest bytes changed")
        manifest = json.loads(payload)
        evidence = entry["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {"upstream_tree_git_sha1", "license_sha256", "answer_dictionary_sha256", "eligible_id_set_sha256", "evaluator_sha256"}:
            raise ValueError("protected custody evidence is invalid")
        split = manifest.get("split", {}) if isinstance(manifest, dict) else {}
        evaluator = manifest.get("evaluator", {}) if isinstance(manifest, dict) else {}
        observed = {
            "upstream_tree_git_sha1": manifest.get("upstream_tree_git_sha1"),
            "license_sha256": manifest.get("license_sha256"),
            "answer_dictionary_sha256": split.get("answer_dictionary_sha256") if isinstance(split, dict) else None,
            "eligible_id_set_sha256": split.get("eligible_id_set_sha256") if isinstance(split, dict) else None,
            "evaluator_sha256": evaluator.get("sha256") if isinstance(evaluator, dict) else None,
        }
        if manifest.get("benchmark_id") != entry["benchmark_id"] or observed != evidence:
            raise ValueError("protected custody evidence does not match its manifest")
        identifiers = entry["protected_identifiers"]
        if not isinstance(identifiers, list):
            raise ValueError("protected identifiers are invalid")
        for identifier in identifiers:
            if not isinstance(identifier, dict) or set(identifier) != {"kind", "value"} or identifier["kind"] not in result or not isinstance(identifier["value"], str):
                raise ValueError("protected identifier is invalid")
            result[identifier["kind"]].add(identifier["value"])
    return result

def validate_authority_index(repo_root: Path, *, index_relative: str = _AUTHORITY_INDEX) -> dict[str, Any]:
    """Validate the non-acquired, exact-byte text authority before shared-text use."""
    root=repo_root.resolve(); index_bytes=_path(root,index_relative).read_bytes(); index=json.loads(index_bytes)
    if not isinstance(index,dict) or set(index)!={"schema_version","result","boundary","registry","receipt_bundle","corpus","input_identity"}: raise ValueError("text authority index is not closed")
    if index["schema_version"]!="ember-text-lab-authority-index-v1" or index["result"]!="PREFLIGHT_ONLY": raise ValueError("text authority index is not preflight-only")
    registry_bytes,registry=_bound_json(root,index["registry"]); bundle_bytes,bundle=_bound_json(root,index["receipt_bundle"]); corpus_bytes,corpus=_bound_json(root,index["corpus"]); _,identity=_bound_json(root,index["input_identity"])
    if corpus.get("registry_sha256")!=_sha_bytes(registry_bytes) or corpus.get("receipt_bundle_sha256")!=_sha_bytes(bundle_bytes): raise ValueError("corpus does not bind external authority")
    if identity.get("corpus_sha256")!=_sha_bytes(corpus_bytes) or not isinstance(identity.get("source_base_commit"),str) or re.fullmatch(r"[0-9a-f]{40}",identity["source_base_commit"]) is None: raise ValueError("input identity does not bind exact authority")
    base_check = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", identity["source_base_commit"], "HEAD"], capture_output=True, check=False)
    if base_check.returncode != 0: raise ValueError("input identity source-base commit is not a live ancestor")
    code_files = identity.get("code_files")
    expected_code = {
        "text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py",
        "train": "tools/ember-restart-3b/train.py",
        "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py",
        "token_shards_v0": "scripts/token_shards_v0.py",
    }
    if not isinstance(code_files, dict) or set(code_files) != set(expected_code): raise ValueError("input identity code binding is invalid")
    for name, relative in expected_code.items():
        if code_files[name] != _sha_bytes(_path(root, relative).read_bytes()): raise ValueError("input identity code bytes changed")

    rows = corpus.get("sources"); candidates = bundle.get("candidates"); protected = registry.get("protected")
    if bundle.get("result") != "UNRESOLVED_CANDIDATE":
        raise ValueError("unresolved candidate bundle result is invalid")
    if not isinstance(rows, list) or not isinstance(candidates, list) or not isinstance(protected, list):
        raise ValueError("authority payload is incomplete")
    _protected_identifier_sets(root, protected)
    expected_fields = {"source_id", "domain", "split", "admission", "required_evidence", "allowed_license_spdx"}
    candidate_map = {item.get("source_id"): item for item in candidates if isinstance(item, dict)}
    if len(candidate_map) != len(candidates):
        raise ValueError("candidate source mapping is ambiguous")
    by_domain: dict[tuple[str, str], int] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_fields or not isinstance(row.get("source_id"), str) or row["source_id"] in seen:
            raise ValueError("candidate descriptor is invalid or duplicated")
        if not row["source_id"].startswith("candidate-") or row.get("domain") not in DOMAINS or row.get("split") not in {"train", "heldout"}:
            raise ValueError("candidate slot, domain, or split is invalid")
        if row.get("admission") != "UNRESOLVED_CANDIDATE" or row.get("required_evidence") != _UNRESOLVED_EVIDENCE or row.get("allowed_license_spdx") != sorted(LICENSES):
            raise ValueError("candidate descriptor has unverified authority claims")
        if candidate_map.get(row["source_id"]) != row:
            raise ValueError("candidate bundle does not bind exact descriptor bytes")
        seen.add(row["source_id"])
        by_domain[(row["domain"], row["split"])] = by_domain.get((row["domain"], row["split"]), 0) + 1
    if len(rows) != 44 or {row.get("domain") for row in rows} != set(DOMAINS):
        raise ValueError("authority corpus lacks eleven-domain source matrix")
    for domain in DOMAINS:
        if by_domain.get((domain, "train")) != 2 or by_domain.get((domain, "heldout")) != 2:
            raise ValueError("domain requires two train and two heldout candidate slots")
    if corpus.get("train_root_sha256") != _authority_split_root(rows, "train") or corpus.get("heldout_root_sha256") != _authority_split_root(rows, "heldout"):
        raise ValueError("authority corpus split root does not match")

    return {
        "result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING",
        "authority_index_sha256": _sha_bytes(index_bytes),
        "registry_sha256": _sha_bytes(registry_bytes),
        "receipt_bundle_sha256": _sha_bytes(bundle_bytes),
        "corpus_sha256": _sha_bytes(corpus_bytes),
        "input_identity_sha256": _sha_bytes(_path(root, index["input_identity"]["path"]).read_bytes()),
        "train_root_sha256": corpus["train_root_sha256"],
        "heldout_root_sha256": corpus["heldout_root_sha256"],
        "domain_count": 11,
        "train_source_count": sum(x["split"] == "train" for x in rows),
        "heldout_source_count": sum(x["split"] == "heldout" for x in rows),
        "source_base_commit": identity["source_base_commit"],
        "code_files": code_files,
    }