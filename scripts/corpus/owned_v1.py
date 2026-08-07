# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic, receipt-bound owned-corpus v1 builder.

The builder consumes already-receipted raw bytes.  It never downloads, uses a
learned filter, or writes an absolute source path into a public manifest.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence


SCHEMA_VERSION = "ember-owned-corpus-manifest-v1"
STATE_SCHEMA_VERSION = "ember-owned-corpus-build-state-v1"
DEFAULT_MAX_TEMP_BYTES = 4 * 1024 * 1024 * 1024
ALLOWED_LICENSES = {
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY 4.0",
    "CC-BY-SA-4.0",
    "CC-BY-SA 4.0",
    "Public Domain",
    "public domain",
}
_HEX = re.compile(r"[0-9a-f]{64}\Z", re.IGNORECASE)
_LOWER_HEX = re.compile(r"[0-9a-f]{64}\Z")
_BANNED_RULE_MARKERS = ("fasttext", "classifier", "embedding", "llm", "model-derived", "model derived")
_MANIFEST_FIELDS = {
    "relative_path",
    "source_url",
    "sha256",
    "bytes",
    "license",
    "human_provenance_basis",
    "fetched_ts",
    "selection_rule",
}
_SOURCE_BINDING_FIELDS = {
    "source_name",
    "relative_path",
    "source_url",
    "sha256",
    "bytes",
    "license",
    "human_provenance_basis",
    "fetched_ts",
    "selection_rule",
    "manifest_sha256",
}


class CorpusBuildError(ValueError):
    """A fail-closed source or deterministic-build violation."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CorpusBuildError(f"{label} path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise CorpusBuildError(f"{label} path escapes source custody")
    return value


def _resolve_receipted_file(source_root: Path, row: dict[str, Any]) -> tuple[str, Path]:
    relative = row.get("relative_path")
    if relative is not None:
        relative = _safe_relative(relative, label="source")
        candidate = (source_root / relative).resolve()
        if source_root.resolve() not in candidate.parents or not candidate.is_file():
            raise CorpusBuildError("source receipt points to an absent file")
        return relative, candidate
    candidates = []
    for candidate in sorted(source_root.rglob("*")):
        if candidate.is_file() and candidate.name != "manifest.jsonl":
            if candidate.stat().st_size == row["bytes"] and _sha_file(candidate) == row["sha256"]:
                candidates.append(candidate)
    if len(candidates) != 1:
        raise CorpusBuildError("source receipt without relative_path is ambiguous")
    return candidates[0].relative_to(source_root).as_posix(), candidates[0]


def _validate_manifest_row(row: object) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise CorpusBuildError("source receipt row must be an object")
    if set(row) not in (_MANIFEST_FIELDS, _MANIFEST_FIELDS - {"relative_path"}):
        raise CorpusBuildError("source receipt row is not closed")
    source_url = row.get("source_url")
    if not isinstance(source_url, str) or not source_url.startswith(("https://", "http://")):
        raise CorpusBuildError("source receipt source_url is missing or invalid")
    digest = row.get("sha256")
    if not isinstance(digest, str) or _HEX.fullmatch(digest) is None:
        raise CorpusBuildError("source receipt sha256 is invalid")
    size = row.get("bytes")
    if type(size) is not int or size < 0:
        raise CorpusBuildError("source receipt bytes is invalid")
    license_name = row.get("license")
    if not isinstance(license_name, str) or not license_name.strip() or license_name not in ALLOWED_LICENSES:
        raise CorpusBuildError("source receipt license is not permitted")
    basis = row.get("human_provenance_basis")
    if not isinstance(basis, str) or not basis.strip():
        raise CorpusBuildError("source receipt human provenance is missing")
    fetched = row.get("fetched_ts")
    if not isinstance(fetched, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^ ]+Z", fetched):
        raise CorpusBuildError("source receipt fetched_ts is invalid")
    rule = row.get("selection_rule")
    if not isinstance(rule, str) or not rule.strip() or any(marker in rule.lower() for marker in _BANNED_RULE_MARKERS):
        raise CorpusBuildError("source receipt selection rule is not deterministic and human-authored")
    normalized = dict(row)
    normalized["sha256"] = digest.lower()
    return normalized


def load_source_inventory(raw_root: Path, *, source_names: Sequence[str]) -> list[dict[str, Any]]:
    """Validate and resolve the exact, already-receipted source files."""
    root = Path(raw_root).resolve()
    if not root.is_dir():
        raise CorpusBuildError("raw custody root is absent")
    if isinstance(source_names, (str, bytes)):
        raise CorpusBuildError("source inventory must be a sequence of names")
    names = list(source_names)
    if not names or len(set(names)) != len(names):
        raise CorpusBuildError("source inventory is empty or duplicated")
    for source_name in names:
        if not isinstance(source_name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source_name):
            raise CorpusBuildError("source name is invalid")
    inventory: list[dict[str, Any]] = []
    for source_name in sorted(names):
        source_root = root / source_name
        manifest_path = source_root / "manifest.jsonl"
        if not source_root.is_dir() or not manifest_path.is_file():
            raise CorpusBuildError(f"source {source_name} lacks a receipt manifest")
        manifest_bytes = manifest_path.read_bytes()
        try:
            lines = manifest_bytes.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError as error:
            raise CorpusBuildError("source receipt manifest is not UTF-8") from error
        rows = []
        receipt_keys: set[tuple[str, int]] = set()
        for line in lines:
            if line.strip():
                try:
                    normalized = _validate_manifest_row(json.loads(line))
                except json.JSONDecodeError as error:
                    raise CorpusBuildError("source receipt manifest contains malformed JSON") from error
                receipt_key = (normalized["sha256"], normalized["bytes"])
                if receipt_key in receipt_keys:
                    raise CorpusBuildError("source receipt rows are duplicated")
                receipt_keys.add(receipt_key)
                rows.append(normalized)
        if not rows:
            raise CorpusBuildError(f"source {source_name} has no receipt rows")
        resolved_rows = []
        for row in rows:
            relative, path = _resolve_receipted_file(source_root, row)
            if path.stat().st_size != row["bytes"] or _sha_file(path) != row["sha256"]:
                raise CorpusBuildError(f"source {source_name} bytes do not match its receipt")
            resolved_rows.append((relative, path, row))
        for relative, path, row in sorted(resolved_rows, key=lambda item: (item[0], item[2]["sha256"])):
            inventory.append({
                "source_name": source_name,
                "relative_path": relative,
                "source_url": row["source_url"],
                "sha256": row["sha256"],
                "bytes": row["bytes"],
                "license": row["license"],
                "human_provenance_basis": row["human_provenance_basis"],
                "fetched_ts": row["fetched_ts"],
                "selection_rule": row["selection_rule"],
                "manifest_sha256": _sha_bytes(manifest_bytes),
                "path": path,
            })
    return inventory


def _iter_records(item: dict[str, Any]) -> Iterator[tuple[str, str]]:
    path = item["path"]
    if path.name.endswith(".gz"):
        opener = gzip.open
    elif path.name.endswith(".bz2"):
        opener = __import__("bz2").open
    else:
        opener = open
    try:
        with opener(path, "rt", encoding="utf-8", errors="strict") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                if path.name.endswith((".jsonl", ".jsonl.gz")):
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise CorpusBuildError(f"malformed JSON record at {path.name}:{number}") from error
                    if not isinstance(value, dict):
                        raise CorpusBuildError("corpus record must be an object")
                    record_id = value.get("id", value.get("record_id"))
                    text = value.get("text", value.get("content", value.get("body")))
                    if not isinstance(record_id, str) or not record_id or not isinstance(text, str):
                        raise CorpusBuildError("JSON record needs string id and text")
                else:
                    record_id = str(number)
                    text = line.rstrip("\r\n")
                    if not text:
                        continue
                yield record_id, text
    except (UnicodeDecodeError, EOFError, OSError) as error:
        raise CorpusBuildError(f"source file cannot be decoded or read: {path.name}") from error


def _split_for(content_sha256: str, seed: str, heldout_modulus: int) -> str:
    value = int(_sha_bytes(f"{seed}\0{content_sha256}".encode())[:8], 16)
    return "heldout" if value % heldout_modulus == 0 else "train"


def _root(records: Iterable[dict[str, Any]], split: str) -> str:
    digest = hashlib.sha256(f"ember-owned-corpus-v1\0{split}\0".encode())
    selected = sorted((row for row in records if row["split"] == split), key=lambda row: (row["source_name"], row["record_id"], row["content_sha256"]))
    for row in selected:
        encoded = bytes.fromhex(row["content_sha256"])
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(_json_bytes(value))
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_shard(output_root: Path, split: str, index: int, rows: list[dict[str, Any]], max_temp_bytes: int) -> dict[str, Any]:
    payload = b"".join(_json_bytes(row) for row in rows)
    if len(payload) > max_temp_bytes:
        raise CorpusBuildError("serialized shard exceeds max_transient_scratch_bytes")
    directory = output_root / split
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"shard-{index:06d}.jsonl"
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        if temporary.stat().st_size > max_temp_bytes:
            raise CorpusBuildError("temporary shard exceeds max_transient_scratch_bytes")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"path": f"{split}/{target.name}", "bytes": len(payload), "sha256": _sha_bytes(payload), "records": len(rows)}


def _load_state(output_root: Path) -> dict[str, Any] | None:
    path = output_root / ".build-state.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusBuildError("build state is unreadable") from error
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise CorpusBuildError("build state schema is invalid")
    return value


def build_owned_corpus(*, raw_root: Path, output_root: Path, source_names: Sequence[str], shard_records: int = 4096, split_seed: str = "owned-corpus-v1", heldout_modulus: int = 2, max_records: int | None = None, resume: bool = False, max_temp_bytes: int = DEFAULT_MAX_TEMP_BYTES) -> dict[str, Any]:
    if type(shard_records) is not int or shard_records <= 0 or type(heldout_modulus) is not int or heldout_modulus <= 1:
        raise CorpusBuildError("shard and split bounds are invalid")
    if max_records is not None and (type(max_records) is not int or max_records <= 0):
        raise CorpusBuildError("max_records is invalid")
    if type(max_temp_bytes) is not int or max_temp_bytes <= 0:
        raise CorpusBuildError("max_transient_scratch_bytes is invalid")
    raw_root = Path(raw_root).resolve()
    output_root = Path(output_root).resolve()
    if output_root == raw_root or raw_root in output_root.parents:
        raise CorpusBuildError("output root must not be inside raw custody")
    output_root.mkdir(parents=True, exist_ok=True)
    inventory = load_source_inventory(raw_root, source_names=source_names)
    source_binding = [
        {key: item[key] for key in ("source_name", "relative_path", "source_url", "sha256", "bytes", "license", "human_provenance_basis", "fetched_ts", "selection_rule", "manifest_sha256")}
        for item in inventory
    ]
    source_manifest_sha256 = _sha_bytes(_json_bytes(source_binding))
    state = _load_state(output_root) if resume else None
    if state is not None and (state.get("source_manifest_sha256") != source_manifest_sha256 or state.get("shard_records") != shard_records or state.get("split_seed") != split_seed):
        raise CorpusBuildError("resume authority does not match source bytes or transform")
    processed_input = int(state.get("processed_input_records", 0)) if state else 0
    shard_info = {"train": list(state.get("shards", {}).get("train", [])) if state else [], "heldout": list(state.get("shards", {}).get("heldout", [])) if state else []}
    records_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "heldout": []}
    seen: set[str] = set()
    for split in ("train", "heldout"):
        for descriptor in shard_info[split]:
            path = output_root / descriptor["path"]
            if not path.is_file() or _sha_file(path) != descriptor["sha256"]:
                raise CorpusBuildError("resume shard bytes do not match state")
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    records_by_split[split].append(row)
                    seen.add(row["content_sha256"])
    pending = state.get("pending", {}) if state else {}
    buffers: dict[str, list[dict[str, Any]]] = {
        split: [dict(row) for row in pending.get(split, [])]
        for split in ("train", "heldout")
    }
    for split in ("train", "heldout"):
        records_by_split[split].extend(buffers[split])
        seen.update(row["content_sha256"] for row in buffers[split])
    input_seen = 0
    emitted = len(seen)
    for item in inventory:
        for record_id, text in _iter_records(item):
            if input_seen < processed_input:
                input_seen += 1
                continue
            input_seen += 1
            content_sha256 = _sha_bytes(text.encode("utf-8"))
            if content_sha256 in seen:
                continue
            split = _split_for(content_sha256, split_seed, heldout_modulus)
            row = {"source_name": item["source_name"], "source_sha256": item["sha256"], "record_id": record_id, "content_sha256": content_sha256, "text": text, "split": split}
            seen.add(content_sha256)
            buffers[split].append(row)
            records_by_split[split].append(row)
            emitted += 1
            if len(buffers[split]) >= shard_records:
                shard_info[split].append(_write_shard(output_root, split, len(shard_info[split]), buffers[split], max_temp_bytes))
                buffers[split] = []
            if max_records is not None and input_seen >= processed_input + max_records:
                state_value = {"schema_version": STATE_SCHEMA_VERSION, "source_manifest_sha256": source_manifest_sha256, "shard_records": shard_records, "split_seed": split_seed, "processed_input_records": input_seen, "shards": shard_info, "pending": buffers}
                _write_json(output_root / ".build-state.json", state_value)
                return {"schema_version": SCHEMA_VERSION, "result": "INTERRUPTED", "processed_input_records": input_seen, "shard_count": sum(len(values) for values in shard_info.values())}
    for split in ("train", "heldout"):
        if buffers[split]:
            shard_info[split].append(_write_shard(output_root, split, len(shard_info[split]), buffers[split], max_temp_bytes))
    manifest = {"schema_version": SCHEMA_VERSION, "result": "MEASURED", "source_manifest_sha256": source_manifest_sha256, "sources": source_binding, "split_seed": split_seed, "heldout_modulus": heldout_modulus, "shard_records": shard_records, "train_shards": shard_info["train"], "heldout_shards": shard_info["heldout"], "train_record_count": len(records_by_split["train"]), "heldout_record_count": len(records_by_split["heldout"]), "train_content_sha256": sorted(row["content_sha256"] for row in records_by_split["train"]), "heldout_content_sha256": sorted(row["content_sha256"] for row in records_by_split["heldout"]), "train_root_sha256": _root(records_by_split["train"], "train"), "heldout_root_sha256": _root(records_by_split["heldout"], "heldout"), "transform": "utf8-jsonl-normalize-exact-content-dedup-v1"}
    _write_json(output_root / "manifest.json", manifest)
    (output_root / ".build-state.json").unlink(missing_ok=True)
    return manifest


def validate_manifest(manifest_path: Path, *, output_root: Path) -> dict[str, Any]:
    """Re-open and verify every public manifest/shard binding before consumption."""
    manifest_path = Path(manifest_path).resolve()
    output_root = Path(output_root).resolve()
    if manifest_path.parent != output_root or not manifest_path.is_file():
        raise CorpusBuildError("manifest path is not the declared output root")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusBuildError("manifest is unreadable JSON") from error
    expected = {"schema_version", "result", "source_manifest_sha256", "sources", "split_seed", "heldout_modulus", "shard_records", "train_shards", "heldout_shards", "train_record_count", "heldout_record_count", "train_content_sha256", "heldout_content_sha256", "train_root_sha256", "heldout_root_sha256", "transform"}
    if not isinstance(manifest, dict) or set(manifest) != expected or manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("result") != "MEASURED":
        raise CorpusBuildError("manifest schema is not closed")
    if not isinstance(manifest["sources"], list) or not manifest["sources"]:
        raise CorpusBuildError("manifest sources are invalid")
    source_bindings: dict[tuple[str, str], dict[str, Any]] = {}
    for source in manifest["sources"]:
        if not isinstance(source, dict) or set(source) != _SOURCE_BINDING_FIELDS:
            raise CorpusBuildError("manifest source binding is not closed")
        source_name = source.get("source_name")
        if not isinstance(source_name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source_name):
            raise CorpusBuildError("manifest source name is invalid")
        relative = _safe_relative(source.get("relative_path"), label="source")
        source_url = source.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith(("https://", "http://")):
            raise CorpusBuildError("manifest source URL is invalid")
        digest = source.get("sha256")
        manifest_digest = source.get("manifest_sha256")
        if not isinstance(digest, str) or _LOWER_HEX.fullmatch(digest) is None or not isinstance(manifest_digest, str) or _LOWER_HEX.fullmatch(manifest_digest) is None:
            raise CorpusBuildError("manifest source hash is invalid")
        if type(source.get("bytes")) is not int or source["bytes"] < 0:
            raise CorpusBuildError("manifest source byte count is invalid")
        if source.get("license") not in ALLOWED_LICENSES:
            raise CorpusBuildError("manifest source license is not permitted")
        if not isinstance(source.get("human_provenance_basis"), str) or not source["human_provenance_basis"].strip():
            raise CorpusBuildError("manifest source provenance is missing")
        if not isinstance(source.get("fetched_ts"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^ ]+Z", source["fetched_ts"]):
            raise CorpusBuildError("manifest source fetched_ts is invalid")
        if not isinstance(source.get("selection_rule"), str) or any(marker in source["selection_rule"].lower() for marker in _BANNED_RULE_MARKERS):
            raise CorpusBuildError("manifest source selection rule is invalid")
        key = (source_name, digest)
        if key in source_bindings:
            raise CorpusBuildError("manifest source binding is duplicated")
        source_bindings[key] = dict(source)
    if not isinstance(manifest["source_manifest_sha256"], str) or _LOWER_HEX.fullmatch(manifest["source_manifest_sha256"]) is None:
        raise CorpusBuildError("manifest source authority hash is invalid")
    if manifest["source_manifest_sha256"] != _sha_bytes(_json_bytes(manifest["sources"])):
        raise CorpusBuildError("manifest source authority hash does not match canonical source bindings")
    if not isinstance(manifest["split_seed"], str) or not manifest["split_seed"] or type(manifest["heldout_modulus"]) is not int or manifest["heldout_modulus"] <= 1 or type(manifest["shard_records"]) is not int or manifest["shard_records"] <= 0 or manifest["transform"] != "utf8-jsonl-normalize-exact-content-dedup-v1":
        raise CorpusBuildError("manifest transform parameters are invalid")
    all_rows: dict[str, list[dict[str, Any]]] = {"train": [], "heldout": []}
    expected_paths: dict[str, set[str]] = {"train": set(), "heldout": set()}
    for split, descriptors in (("train", manifest["train_shards"]), ("heldout", manifest["heldout_shards"])):
        if not isinstance(descriptors, list):
            raise CorpusBuildError("manifest shard list is invalid")
        for descriptor in descriptors:
            if not isinstance(descriptor, dict) or set(descriptor) != {"path", "bytes", "sha256", "records"}:
                raise CorpusBuildError("manifest shard descriptor is not closed")
            relative = _safe_relative(descriptor["path"], label="shard")
            if PurePosixPath(relative).parts[0] != split:
                raise CorpusBuildError("manifest shard split is inconsistent")
            if relative in expected_paths[split]:
                raise CorpusBuildError("manifest shard path is duplicated")
            expected_paths[split].add(relative)
            path = (output_root / relative).resolve()
            if output_root not in path.parents or not path.is_file():
                raise CorpusBuildError("manifest shard path escapes output root")
            payload = path.read_bytes()
            if type(descriptor["bytes"]) is not int or descriptor["bytes"] < 0 or descriptor["bytes"] != len(payload) or not isinstance(descriptor["sha256"], str) or _LOWER_HEX.fullmatch(descriptor["sha256"]) is None or descriptor["sha256"] != _sha_bytes(payload) or type(descriptor["records"]) is not int or descriptor["records"] < 0:
                raise CorpusBuildError("manifest shard bytes do not match")
            try:
                lines = payload.decode("utf-8").splitlines()
            except UnicodeDecodeError as error:
                raise CorpusBuildError("manifest shard is not UTF-8") from error
            rows = []
            for line in lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise CorpusBuildError("manifest record JSON is malformed") from error
                if not isinstance(row, dict) or set(row) != {"source_name", "source_sha256", "record_id", "content_sha256", "text", "split"} or row["split"] != split:
                    raise CorpusBuildError("manifest record schema is invalid")
                if not isinstance(row["source_name"], str) or not isinstance(row["source_sha256"], str) or _LOWER_HEX.fullmatch(row["source_sha256"]) is None or (row["source_name"], row["source_sha256"]) not in source_bindings:
                    raise CorpusBuildError("manifest record source binding is unresolved")
                if not isinstance(row["record_id"], str) or not row["record_id"] or not isinstance(row["text"], str) or not isinstance(row["content_sha256"], str) or _LOWER_HEX.fullmatch(row["content_sha256"]) is None or row["content_sha256"] != _sha_bytes(row["text"].encode("utf-8")):
                    raise CorpusBuildError("manifest record content hash is invalid")
                rows.append(row)
            if descriptor["records"] != len(rows):
                raise CorpusBuildError("manifest shard record count does not match")
            all_rows[split].extend(rows)
        actual_paths = {path.relative_to(output_root).as_posix() for path in (output_root / split).rglob("*") if path.is_file()}
        if actual_paths != expected_paths[split]:
            raise CorpusBuildError("manifest output contains extra or missing shard files")
    train_hashes = sorted(row["content_sha256"] for row in all_rows["train"])
    heldout_hashes = sorted(row["content_sha256"] for row in all_rows["heldout"])
    for label, values in (("train", manifest["train_content_sha256"]), ("heldout", manifest["heldout_content_sha256"])):
        if not isinstance(values, list) or any(not isinstance(value, str) or _LOWER_HEX.fullmatch(value) is None for value in values) or len(values) != len(set(values)):
            raise CorpusBuildError(f"manifest {label} content index is invalid")
    if set(train_hashes) & set(heldout_hashes):
        raise CorpusBuildError("train and heldout content overlap")
    if manifest["train_content_sha256"] != train_hashes or manifest["heldout_content_sha256"] != heldout_hashes:
        raise CorpusBuildError("manifest content index does not match shards")
    if type(manifest["train_record_count"]) is not int or type(manifest["heldout_record_count"]) is not int or manifest["train_record_count"] != len(train_hashes) or manifest["heldout_record_count"] != len(heldout_hashes):
        raise CorpusBuildError("manifest record counts do not match shards")
    if not isinstance(manifest["train_root_sha256"], str) or _LOWER_HEX.fullmatch(manifest["train_root_sha256"]) is None or not isinstance(manifest["heldout_root_sha256"], str) or _LOWER_HEX.fullmatch(manifest["heldout_root_sha256"]) is None or manifest["train_root_sha256"] != _root(all_rows["train"], "train") or manifest["heldout_root_sha256"] != _root(all_rows["heldout"], "heldout"):
        raise CorpusBuildError("manifest split root does not match shards")
    return manifest


_CURSOR_SCHEMA_VERSION = "ember-owned-corpus-cursor-v1"
_CURSOR_FIELDS = {"schema_version", "manifest_sha256", "split", "root_sha256", "record_index"}


def iter_owned_records(manifest_path: Path, *, output_root: Path, cursor: dict[str, Any], max_records: int | None = None) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Validate a closed cursor, then stream records with one-step cursors."""
    manifest_path = Path(manifest_path).resolve()
    output_root = Path(output_root).resolve()
    if manifest_path.parent != output_root:
        raise CorpusBuildError("manifest path is not the declared output root")
    manifest_bytes = manifest_path.read_bytes()
    manifest = validate_manifest(manifest_path, output_root=output_root)
    if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS or cursor.get("schema_version") != _CURSOR_SCHEMA_VERSION:
        raise CorpusBuildError("cursor schema is not closed")
    if not isinstance(cursor.get("manifest_sha256"), str) or _LOWER_HEX.fullmatch(cursor["manifest_sha256"]) is None or cursor["manifest_sha256"] != _sha_bytes(manifest_bytes):
        raise CorpusBuildError("cursor manifest authority does not match bytes")
    split = cursor.get("split")
    if split not in ("train", "heldout"):
        raise CorpusBuildError("cursor split is invalid")
    expected_root = manifest[f"{split}_root_sha256"]
    if cursor.get("root_sha256") != expected_root:
        raise CorpusBuildError("cursor root authority does not match manifest")
    if type(cursor.get("record_index")) is not int or cursor["record_index"] < 0:
        raise CorpusBuildError("cursor record index is invalid")
    if max_records is not None and (type(max_records) is not int or max_records <= 0):
        raise CorpusBuildError("cursor max_records is invalid")
    total = manifest[f"{split}_record_count"]
    if cursor["record_index"] > total:
        raise CorpusBuildError("cursor record index is out of range")
    skipped = 0
    emitted = 0
    for descriptor in manifest[f"{split}_shards"]:
        path = (output_root / descriptor["path"]).resolve()
        with path.open("rb") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise CorpusBuildError("manifest record JSON is malformed") from error
                if skipped < cursor["record_index"]:
                    skipped += 1
                    continue
                if max_records is not None and emitted >= max_records:
                    return
                skipped += 1
                emitted += 1
                next_cursor = dict(cursor)
                next_cursor["record_index"] = skipped
                yield row, next_cursor
    if skipped != total:
        raise CorpusBuildError("cursor record count does not match manifest")



OWNED_SELECTION_SCHEMA_VERSION = "ember-owned-corpus-selection-receipt-v1"
OWNED_SELECTION_RULE = "owned_corpus_text_tokenize_v1"


class OwnedCorpusSelection:
    """Lazy owned-v1 selection adapter for the merged P2B pretrain consumer."""

    def __init__(
        self,
        manifest_path: Path,
        *,
        output_root: Path,
        tokenizer_path: Path,
        split: str,
        max_records: int,
    ) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.output_root = Path(output_root).resolve()
        if self.manifest_path.parent != self.output_root:
            raise CorpusBuildError("selection manifest path is not the declared output root")
        manifest = validate_manifest(self.manifest_path, output_root=self.output_root)
        if split not in ("train", "heldout"):
            raise CorpusBuildError("selection split is invalid")
        if type(max_records) is not int or max_records <= 0:
            raise CorpusBuildError("selection max_records is invalid")
        self.split = split
        self._manifest_bytes = self.manifest_path.read_bytes()
        self._manifest_sha256 = _sha_bytes(self._manifest_bytes)
        self._root_sha256 = manifest[f"{split}_root_sha256"]
        total = manifest[f"{split}_record_count"]
        self._selected_record_count = min(max_records, total)
        if self._selected_record_count <= 0:
            raise CorpusBuildError("selection has no records")
        self.tokenizer_path = Path(tokenizer_path).resolve()
        if not self.tokenizer_path.is_file():
            raise CorpusBuildError("selection tokenizer is missing")
        self._tokenizer_sha256 = _sha_file(self.tokenizer_path)
        try:
            from tokenizers import Tokenizer
            self._tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
        except Exception as error:
            raise CorpusBuildError("selection tokenizer is unreadable") from error
        self.receipt = {
            "schema_version": OWNED_SELECTION_SCHEMA_VERSION,
            "manifest_sha256": self._manifest_sha256,
            "split": self.split,
            "root_sha256": self._root_sha256,
            "selected_record_count": self._selected_record_count,
            "tokenizer_sha256": self._tokenizer_sha256,
            "selection_rule": OWNED_SELECTION_RULE,
        }

    def _validate_cursor(self, cursor: object) -> dict[str, Any]:
        if cursor is None:
            cursor = {
                "schema_version": _CURSOR_SCHEMA_VERSION,
                "manifest_sha256": self._manifest_sha256,
                "split": self.split,
                "root_sha256": self._root_sha256,
                "record_index": 0,
            }
        if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
            raise CorpusBuildError("selection cursor schema is not closed")
        if cursor.get("schema_version") != _CURSOR_SCHEMA_VERSION:
            raise CorpusBuildError("selection cursor schema is invalid")
        if cursor.get("manifest_sha256") != self._manifest_sha256 or cursor.get("split") != self.split or cursor.get("root_sha256") != self._root_sha256:
            raise CorpusBuildError("selection cursor authority does not match receipt")
        if type(cursor.get("record_index")) is not int or not 0 <= cursor["record_index"] <= self._selected_record_count:
            raise CorpusBuildError("selection cursor is out of range")
        return dict(cursor)

    def _semantic_record(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            token_ids = [int(value) for value in self._tokenizer.encode(row["text"]).ids]
        except Exception as error:
            raise CorpusBuildError("selection text tokenization failed") from error
        token_ids = token_ids[:128]
        if len(token_ids) < 2:
            token_ids = (token_ids + [0, 0])[:2]
        return {
            "schema_version": "ember-owned-semantic-text-v1",
            "active_expert": "shared",
            "token_ids": token_ids,
            "target_ids": token_ids[1:] + token_ids[:1],
            "image_coordinates": [],
            "multimodal_spans": [],
            "source_name": row["source_name"],
            "source_sha256": row["source_sha256"],
            "record_id": row["record_id"],
            "content_sha256": row["content_sha256"],
        }

    def iter_from(self, cursor: object = None) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
        current = self._validate_cursor(cursor)
        if _sha_file(self.tokenizer_path) != self._tokenizer_sha256:
            raise CorpusBuildError("selection tokenizer authority changed")
        if current["record_index"] >= self._selected_record_count:
            return
        remaining = self._selected_record_count - current["record_index"]
        for row, next_cursor in iter_owned_records(
            self.manifest_path,
            output_root=self.output_root,
            cursor=current,
            max_records=remaining,
        ):
            yield self._semantic_record(row), next_cursor


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build the receipt-bound owned corpus v1")
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source", action="append", dest="sources", required=True)
    parser.add_argument("--shard-records", type=int, default=4096)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = build_owned_corpus(raw_root=args.raw_root, output_root=args.output_root, source_names=tuple(args.sources), shard_records=args.shard_records, max_records=args.max_records, resume=args.resume)
    print(json.dumps(result, sort_keys=True))
