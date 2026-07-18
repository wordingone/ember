# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Seekable, content-addressed owned specialist streams without a corpus payload."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer

from build_owned_audio_frames import record_at as audio_record_at
from build_owned_reasoning_tool_trajectories import record_at as trajectory_record_at
from build_owned_vision_scenes import record_at as vision_record_at
from specialist_semantics import verify_audio_supervision, verify_image_supervision
from verify_capability_record import verify_record as verify_capability_record

CAPABILITIES = ("image", "audio", "reasoning", "tool")
SCHEMA_VERSION = "ember-owned-specialist-stream-v1"
CURSOR_SCHEMA_VERSION = "ember-owned-specialist-stream-cursor-v1"
MEASURED_MIN_RECORDS = 512
SEMANTIC_MIN_RECORDS = 4096
_GENERATOR_SOURCES = {
    "image": "tools/ember-restart-3b/build_owned_vision_scenes.py",
    "audio": "tools/ember-restart-3b/build_owned_audio_frames.py",
    "reasoning_tool": "tools/ember-restart-3b/build_owned_reasoning_tool_trajectories.py",
}
_VERIFIER_SOURCES = {
    "semantics": "tools/ember-restart-3b/specialist_semantics.py",
    "capability": "tools/ember-restart-3b/verify_capability_record.py",
}


def canonical_record_bytes(record: object) -> bytes:
    if not isinstance(record, dict):
        raise ValueError("stream record must be an object")
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _frame(label: bytes, value: bytes) -> bytes:
    return len(label).to_bytes(2, "big") + label + len(value).to_bytes(8, "big") + value


def corpus_root_sha256(capability: str, hashes: list[str], *, chunk_size: int) -> str:
    """Commit canonical record hashes in index order; chunking never changes this root."""
    if capability not in CAPABILITIES or type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("invalid specialist stream root arguments")
    digest = hashlib.sha256(_frame(b"schema", SCHEMA_VERSION.encode("ascii")) + _frame(b"capability", capability.encode("ascii")))
    for index, value in enumerate(hashes):
        if not _is_sha256(value):
            raise ValueError("stream root requires lowercase SHA-256 record hashes")
        digest.update(_frame(b"index", index.to_bytes(8, "big")))
        digest.update(_frame(b"record", bytes.fromhex(value)))
    return digest.hexdigest()


def _chunk_sha256(capability: str, start: int, hashes: list[str]) -> str:
    digest = hashlib.sha256(_frame(b"schema", SCHEMA_VERSION.encode("ascii")) + _frame(b"chunk-capability", capability.encode("ascii")) + _frame(b"start", start.to_bytes(8, "big")))
    for index, value in enumerate(hashes, start):
        digest.update(_frame(b"index", index.to_bytes(8, "big")))
        digest.update(_frame(b"record", bytes.fromhex(value)))
    return digest.hexdigest()


def _canonical_path(repo_root: Path, candidate: Path) -> tuple[Path, str]:
    root = repo_root.resolve()
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("stream authority path escapes repository root") from error
    return resolved, relative


def _source_binding(repo_root: Path, relative: str) -> dict[str, str]:
    path, canonical = _canonical_path(repo_root, repo_root / relative)
    return {"path": canonical, "sha256": _sha256(path.read_bytes())}


def _require_binding(repo_root: Path, binding: object, label: str) -> bytes:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise ValueError(f"invalid {label} binding")
    relative, expected = binding["path"], binding["sha256"]
    if not isinstance(relative, str) or not _is_sha256(expected):
        raise ValueError(f"invalid {label} binding")
    path, canonical = _canonical_path(repo_root, repo_root / relative)
    if canonical != relative:
        raise ValueError(f"noncanonical {label} path")
    value = path.read_bytes()
    if _sha256(value) != expected:
        raise ValueError(f"{label} binding does not match")
    return value


class SpecialistStream:
    def __init__(self, tokenizer: Tokenizer, count: int, families: dict[str, Any], *, chunk_size: int | None = None, manifest_sha256: str | None = None) -> None:
        if manifest_sha256 is not None and not _is_sha256(manifest_sha256):
            raise ValueError("invalid specialist stream manifest identity")
        self.tokenizer = tokenizer
        self.count = count
        self.families = families
        self.chunk_size = chunk_size
        self.manifest_sha256 = manifest_sha256

    def record_at(self, capability: str, index: int) -> dict[str, Any]:
        if capability == "image":
            return vision_record_at(self.tokenizer, count=self.count, image_marker=31_998, index=index)
        if capability == "audio":
            return audio_record_at(self.tokenizer, count=self.count, audio_marker=31_999, index=index)
        if capability in {"reasoning", "tool"}:
            return trajectory_record_at(self.tokenizer, count=self.count, capability=capability, index=index)
        raise ValueError("unsupported specialist capability")

    def verify_record(self, record: dict[str, Any]) -> dict[str, str]:
        active_expert = record.get("active_expert")
        capability = "image" if active_expert == "vision" else active_expert
        if capability == "image":
            patches = [base64.b64decode(value, validate=True) for value in record["image_patches_u8_base64"]]
            verify_image_supervision(record, patches=patches, tokenizer=self.tokenizer, image_marker=31_998)
        elif capability == "audio":
            frames = [base64.b64decode(value, validate=True) for value in record["audio_frames_i16le_base64"]]
            verify_audio_supervision(record, frames=frames, tokenizer=self.tokenizer, audio_marker=31_999)
        elif capability in {"reasoning", "tool"}:
            verify_capability_record(record)
        else:
            raise ValueError("record lacks a specialist capability")
        return {"result": "VERIFIED", "capability": str(capability), "record_sha256": _sha256(canonical_record_bytes(record))}

    def _verify_chunk(self, capability: str, index: int, record_hash: str) -> None:
        if self.chunk_size is None:
            return
        family = self.families.get(capability)
        if not isinstance(family, dict):
            raise ValueError("missing capability commitment")
        chunks = family.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("missing chunk commitments")
        start = (index // self.chunk_size) * self.chunk_size
        hashes = [_sha256(canonical_record_bytes(self.record_at(capability, item))) for item in range(start, min(start + self.chunk_size, self.count))]
        if hashes[index - start] != record_hash:
            raise ValueError("record canonicalization changed")
        expected = next((item for item in chunks if isinstance(item, dict) and item.get("start") == start), None)
        if not isinstance(expected, dict) or expected.get("record_count") != len(hashes) or expected.get("sha256") != _chunk_sha256(capability, start, hashes):
            raise ValueError("chunk commitment does not match")

    def next_records(self, *, capability: str, cursor: object, limit: int) -> tuple[list[dict[str, Any]], dict[str, object]]:
        if capability not in CAPABILITIES:
            raise ValueError("unsupported specialist capability")
        if self.manifest_sha256 is None:
            raise ValueError("stream cursor requires an immutable manifest identity")
        if cursor is None:
            start = 0
        else:
            if not isinstance(cursor, dict) or set(cursor) != {"schema_version", "manifest_sha256", "capability", "next_index"}:
                raise ValueError("invalid stream cursor")
            if cursor["schema_version"] != CURSOR_SCHEMA_VERSION or cursor["manifest_sha256"] != self.manifest_sha256:
                raise ValueError("cursor manifest identity does not match requested stream")
            if cursor["capability"] != capability:
                raise ValueError("cursor capability does not match requested route")
            start = cursor["next_index"]
        if type(start) is not int or type(limit) is not int or limit <= 0 or not 0 <= start <= self.count:
            raise ValueError("invalid stream cursor")
        records = [self.record_at(capability, index) for index in range(start, min(start + limit, self.count))]
        for offset, record in enumerate(records):
            receipt = self.verify_record(record)
            self._verify_chunk(capability, start + offset, receipt["record_sha256"])
        return records, {"schema_version": CURSOR_SCHEMA_VERSION, "manifest_sha256": self.manifest_sha256, "capability": capability, "next_index": start + len(records)}

    def validate_capability_commitment(self, capability: str) -> dict[str, int]:
        """Recompute one route's raw records, execution targets, chunk and root commitments."""
        if capability not in CAPABILITIES:
            raise ValueError("unsupported specialist capability")
        hashes: list[str] = []
        token_count = 0
        serialized_bytes = 0
        for index in range(self.count):
            record = self.record_at(capability, index)
            receipt = self.verify_record(record)
            hashes.append(receipt["record_sha256"])
            token_ids = record.get("token_ids")
            if not isinstance(token_ids, list):
                raise ValueError("generated record lacks token ids")
            token_count += len(token_ids)
            serialized_bytes += len(canonical_record_bytes(record))
            self._verify_chunk(capability, index, receipt["record_sha256"])
        family = self.families[capability]
        root = corpus_root_sha256(capability, hashes, chunk_size=self.chunk_size or 1)
        if family.get("corpus_root_sha256") != root or family.get("token_count") != token_count or family.get("serialized_bytes") != serialized_bytes:
            raise ValueError("family commitment does not match regenerated records")
        return {"records": self.count, "tokens": token_count, "serialized_bytes": serialized_bytes}
    def validate_full_commitment(self, expected_corpus_root: str) -> dict[str, dict[str, int]]:
        """Recompute canonical records and commitments before a production launch."""
        if not _is_sha256(expected_corpus_root):
            raise ValueError("invalid expected corpus root")
        roots: dict[str, str] = {}
        measured: dict[str, dict[str, int]] = {}
        for capability in CAPABILITIES:
            hashes: list[str] = []
            token_count = 0
            serialized_bytes = 0
            for index in range(self.count):
                record = self.record_at(capability, index)
                receipt = self.verify_record(record)
                hashes.append(receipt["record_sha256"])
                token_ids = record.get("token_ids")
                if not isinstance(token_ids, list):
                    raise ValueError("generated record lacks token ids")
                token_count += len(token_ids)
                serialized_bytes += len(canonical_record_bytes(record))
                self._verify_chunk(capability, index, receipt["record_sha256"])
            family = self.families[capability]
            root = corpus_root_sha256(capability, hashes, chunk_size=self.chunk_size or 1)
            if family.get("corpus_root_sha256") != root or family.get("token_count") != token_count or family.get("serialized_bytes") != serialized_bytes:
                raise ValueError("family commitment does not match regenerated records")
            roots[capability] = root
            measured[capability] = {"records": self.count, "tokens": token_count, "serialized_bytes": serialized_bytes}
        actual = _sha256(b"".join(_frame(capability.encode("ascii"), bytes.fromhex(roots[capability])) for capability in CAPABILITIES))
        if actual != expected_corpus_root:
            raise ValueError("corpus root does not match regenerated records")
        return measured


def _family_commitment(stream: SpecialistStream, capability: str, record_count: int, chunk_size: int) -> dict[str, Any]:
    hashes: list[str] = []
    chunks: list[dict[str, Any]] = []
    token_count = 0
    serialized_bytes = 0
    for index in range(record_count):
        record = stream.record_at(capability, index)
        encoded = canonical_record_bytes(record)
        record_hash = _sha256(encoded)
        hashes.append(record_hash)
        token_ids = record.get("token_ids")
        if not isinstance(token_ids, list):
            raise ValueError("generated record lacks token ids")
        token_count += len(token_ids)
        serialized_bytes += len(encoded)
        if len(hashes) % chunk_size == 0 or index + 1 == record_count:
            start = index + 1 - (len(hashes) % chunk_size or chunk_size)
            part = hashes[start:index + 1]
            chunks.append({"start": start, "record_count": len(part), "sha256": _chunk_sha256(capability, start, part)})
    return {"record_count": record_count, "token_count": token_count, "serialized_bytes": serialized_bytes, "corpus_root_sha256": corpus_root_sha256(capability, hashes, chunk_size=chunk_size), "chunks": chunks}


def build_stream_manifest(*, repo_root: Path, output_path: Path, tokenizer_path: Path, model_config_path: Path, record_count: int, chunk_size: int, data_class: str) -> dict[str, Any]:
    if type(record_count) is not int or type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("invalid stream range")
    if data_class == "SEMANTIC_PRETRAINING":
        if record_count < SEMANTIC_MIN_RECORDS:
            raise ValueError("SEMANTIC_PRETRAINING requires at least 4096 records per family")
    elif data_class == "MEASURED_RUNG":
        if record_count < MEASURED_MIN_RECORDS:
            raise ValueError("MEASURED_RUNG requires at least 512 records per family")
    else:
        raise ValueError("unknown specialist stream data class")
    tokenizer_bytes = tokenizer_path.read_bytes()
    config_bytes = model_config_path.read_bytes()
    tokenizer = Tokenizer.from_str(tokenizer_bytes.decode("utf-8"))
    stream = SpecialistStream(tokenizer, record_count, {})
    families = {capability: _family_commitment(stream, capability, record_count, chunk_size) for capability in CAPABILITIES}
    root = _sha256(b"".join(_frame(capability.encode("ascii"), bytes.fromhex(str(families[capability]["corpus_root_sha256"]))) for capability in CAPABILITIES))
    tokenizer_resolved, tokenizer_relative = _canonical_path(repo_root, tokenizer_path)
    config_resolved, config_relative = _canonical_path(repo_root, model_config_path)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "lineage": "NEW_PREREGISTERED_STREAM",
        "legacy_materialized_compatibility": "UNAVAILABLE_NO_ACCEPTED_ARTIFACT_BOUND_AT_KNOWN_PATH",
        "data_class": data_class,
        "generator_contract": {
            "version": "owned-specialist-indexed-v1",
            "randomness": "INDEX_PURE_NO_PRNG",
            "seed": None,
        },
        "range": {"start": 0, "record_count_per_family": record_count},
        "chunk_size": chunk_size,
        "tokenizer": {"path": tokenizer_relative, "sha256": _sha256(tokenizer_bytes)},
        "model_config": {"path": config_relative, "sha256": _sha256(config_bytes)},
        "generator_sources": {name: _source_binding(repo_root, relative) for name, relative in _GENERATOR_SOURCES.items()},
        "verifier_sources": {name: _source_binding(repo_root, relative) for name, relative in _VERIFIER_SOURCES.items()},
        "families": families,
        "corpus_root_sha256": root,
    }
    output_path.write_bytes(canonical_record_bytes(manifest) + b"\n")
    return manifest


def write_stream_build_receipt(*, manifest_path: Path, output_path: Path, elapsed_ms: int) -> dict[str, Any]:
    """Write compact measured construction evidence; this is not training or capability credit."""
    if type(elapsed_ms) is not int or elapsed_ms < 0:
        raise ValueError("invalid stream build duration")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("invalid stream manifest receipt source") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid stream manifest receipt source")
    families = manifest.get("families")
    if not isinstance(families, dict) or set(families) != set(CAPABILITIES):
        raise ValueError("invalid stream manifest receipt families")
    receipt = {
        "schema_version": "ember-owned-specialist-stream-build-receipt-v1",
        "result": "MEASURED",
        "boundary": "STREAM_CONSTRUCTION_NOT_SUFFICIENT_PRETRAINING_OR_CAPABILITY",
        "stream_manifest_sha256": _sha256(manifest_bytes),
        "lineage": manifest["lineage"],
        "data_class": manifest["data_class"],
        "corpus_root_sha256": manifest["corpus_root_sha256"],
        "record_count_per_family": manifest["range"]["record_count_per_family"],
        "families": {
            capability: {
                "records": family["record_count"],
                "tokens": family["token_count"],
                "serialized_bytes_not_materialized": family["serialized_bytes"],
            }
            for capability, family in families.items()
        },
        "elapsed_ms": elapsed_ms,
    }
    output_path.write_bytes(canonical_record_bytes(receipt) + b"\n")
    return receipt


def emit_stream_manifest(**kwargs: Any) -> tuple[dict[str, Any], int]:
    """Convenience entry point returning a deterministic manifest plus elapsed construction time."""
    started = time.perf_counter()
    manifest = build_stream_manifest(**kwargs)
    return manifest, int((time.perf_counter() - started) * 1000)

def open_specialist_stream(*, repo_root: Path, manifest_path: Path) -> SpecialistStream:
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("invalid stream manifest") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid stream manifest")
    if manifest.get("lineage") != "NEW_PREREGISTERED_STREAM":
        raise ValueError("unsupported stream lineage")
    generator_contract = manifest.get("generator_contract")
    if generator_contract != {"version": "owned-specialist-indexed-v1", "randomness": "INDEX_PURE_NO_PRNG", "seed": None}:
        raise ValueError("invalid generator contract binding")
    stream_range = manifest.get("range")
    if not isinstance(stream_range, dict) or set(stream_range) != {"start", "record_count_per_family"} or stream_range.get("start") != 0:
        raise ValueError("invalid stream range")
    count = stream_range.get("record_count_per_family")
    chunk_size = manifest.get("chunk_size")
    data_class = manifest.get("data_class")
    if type(count) is not int or type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("invalid stream range")
    if data_class == "SEMANTIC_PRETRAINING" and count < SEMANTIC_MIN_RECORDS:
        raise ValueError("SEMANTIC_PRETRAINING range is too small")
    if data_class == "MEASURED_RUNG" and count < MEASURED_MIN_RECORDS:
        raise ValueError("MEASURED_RUNG range is too small")
    if data_class not in {"SEMANTIC_PRETRAINING", "MEASURED_RUNG"}:
        raise ValueError("unknown specialist stream data class")
    tokenizer_bytes = _require_binding(repo_root, manifest.get("tokenizer"), "tokenizer")
    _require_binding(repo_root, manifest.get("model_config"), "model config")
    sources = manifest.get("generator_sources")
    if not isinstance(sources, dict) or set(sources) != set(_GENERATOR_SOURCES):
        raise ValueError("invalid generator source bindings")
    for name in _GENERATOR_SOURCES:
        _require_binding(repo_root, sources[name], "generator source")
    verifiers = manifest.get("verifier_sources")
    if not isinstance(verifiers, dict) or set(verifiers) != set(_VERIFIER_SOURCES):
        raise ValueError("invalid verifier source bindings")
    for name in _VERIFIER_SOURCES:
        _require_binding(repo_root, verifiers[name], "verifier source")
    families = manifest.get("families")
    if not isinstance(families, dict) or set(families) != set(CAPABILITIES):
        raise ValueError("invalid family commitments")
    return SpecialistStream(Tokenizer.from_str(tokenizer_bytes.decode("utf-8")), count, families, chunk_size=chunk_size, manifest_sha256=_sha256(manifest_bytes))
