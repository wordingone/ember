# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Seekable, content-addressed owned specialist streams without a corpus payload."""
from __future__ import annotations

import ast
import builtins
import base64
import hashlib
import json
import sys
import time
from pathlib import Path
from types import ModuleType
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
SELECTION_RECEIPT_SCHEMA_VERSION = "ember-owned-specialist-stream-selection-receipt-v1"
SELECTION_CURSOR_SCHEMA_VERSION = "ember-owned-specialist-stream-selection-cursor-v1"
TRAINING_CURSOR_SCHEMA_VERSION = "ember-specialist-stream-training-cursor-v1"
MAX_RECORDS_PER_FAMILY = 65_536
MAX_CHUNK_RECORDS = 256
MAX_MANIFEST_BYTES = 1_048_576
MEASURED_MIN_RECORDS = 512
SEMANTIC_MIN_RECORDS = 4096
_GENERATOR_SOURCES = {
    "image": "src/ember/infrastructure/tools/ember-restart-3b/build_owned_vision_scenes.py",
    "audio": "src/ember/infrastructure/tools/ember-restart-3b/build_owned_audio_frames.py",
    "reasoning_tool": "src/ember/infrastructure/tools/ember-restart-3b/build_owned_reasoning_tool_trajectories.py",
}
_VERIFIER_SOURCES = {
    "semantics": "src/ember/infrastructure/tools/ember-restart-3b/specialist_semantics.py",
    "capability": "src/ember/infrastructure/tools/ember-restart-3b/verify_capability_record.py",
}

_BINDING_PATH_MIGRATIONS = {
    "tokenizer/tokenizer.json": "domains/model/tokenizer/tokenizer.json",
}

_BOUND_STANDARD_IMPORTS = {
    "__future__", "argparse", "ast", "base64", "dataclasses", "hashlib", "itertools", "json", "operator",
    "pathlib", "re", "struct", "sys", "typing",
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


def _reject_unbound_project_imports(
    repo_root: Path, source_bytes: bytes, source_path: Path, *, allowed_imports: set[str], source_kind: str,
) -> None:
    try:
        tree = ast.parse(source_bytes, filename=str(source_path))
    except SyntaxError as error:
        raise ValueError(f"bound {source_kind} source cannot be parsed") from error
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module.split(".", 1)[0]]
        elif isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "__import__"
            or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
        ):
            raise ValueError(f"bound {source_kind} source uses a dynamic import")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "builtins" and node.attr == "__import__":
            raise ValueError(f"bound {source_kind} source accesses an unrestricted importer")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "sys" and node.attr == "modules":
            raise ValueError(f"bound {source_kind} source accesses an ambient module registry")
        elif isinstance(node, ast.Name) and node.id == "__builtins__":
            raise ValueError(f"bound {source_kind} source accesses an unrestricted importer")
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "__import__" and (
            isinstance(node.value, ast.Name) and node.value.id == "builtins"
            or isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id == "builtins" and node.value.attr == "__dict__"
            or isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "vars" and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Name) and node.value.args[0].id == "builtins"
        ):
            raise ValueError(f"bound {source_kind} source accesses an unrestricted importer")
        for module_name in modules:
            project_module = source_path.parent / f"{module_name}.py"
            if project_module.is_file() and module_name not in allowed_imports:
                raise ValueError(f"bound {source_kind} source imports an unbound project module")


def _load_bound_module(
    repo_root: Path, source_bytes: bytes, source_path: Path, *, source_kind: str, imports: dict[str, ModuleType] | None = None,
) -> ModuleType:
    """Execute hash-bound bytes with per-module imports for every project-local dependency."""
    imports = imports or {}
    _reject_unbound_project_imports(
        repo_root, source_bytes, source_path, allowed_imports=set(imports), source_kind=source_kind,
    )

    def controlled_import(name: str, globals: object = None, locals: object = None, fromlist: object = (), level: int = 0) -> object:
        if level == 0:
            top_level = name.split(".", 1)[0]
            if top_level in imports:
                return imports[top_level]
            if top_level == "builtins":
                return bound_builtins
            if top_level == "sys":
                return bound_sys
            if top_level not in _BOUND_STANDARD_IMPORTS:
                raise ValueError(f"bound {source_kind} source imports a module outside the declared dependency contract")
            if (source_path.parent / f"{top_level}.py").is_file():
                raise ValueError(f"bound {source_kind} source imports an unbound project module")
        return builtins.__import__(name, globals, locals, fromlist, level)

    bound_builtins = ModuleType("builtins")
    for name, value in vars(builtins).items():
        setattr(bound_builtins, name, value)
    bound_builtins.__import__ = controlled_import
    bound_sys = ModuleType("sys")
    bound_sys.stdin = sys.stdin
    bound_sys.stdout = sys.stdout
    bound_sys.stderr = sys.stderr
    module_name = "_ember_specialist_stream_" + _sha256(source_bytes)
    if module_name in sys.modules:
        raise ValueError(f"bound {source_kind} module namespace is already occupied")
    module = ModuleType(module_name)
    module.__file__ = str(source_path)
    module.__package__ = None
    module.__dict__["__ember_bound_source_sha256__"] = _sha256(source_bytes)
    module.__dict__["__builtins__"] = {**vars(builtins), "__import__": controlled_import}
    sys.modules[module_name] = module
    try:
        exec(compile(source_bytes, str(source_path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    sys.modules.pop(module_name, None)
    return module

def _bound_callable(module: ModuleType, name: str, *, source_kind: str) -> Any:
    value = module.__dict__.get(name)
    if not callable(value):
        raise ValueError(f"bound {source_kind} source does not define required callable")
    return value


def _load_bound_runtime(
    repo_root: Path, generator_bindings: dict[str, Any], verifier_bindings: dict[str, Any],
) -> dict[str, Any]:
    verifier_modules: dict[str, ModuleType] = {}
    for name, relative in _VERIFIER_SOURCES.items():
        source_bytes = _require_binding(
            repo_root, verifier_bindings[name], "verifier source", expected_relative=relative,
        )
        source_path, _canonical = _canonical_path(repo_root, repo_root / relative)
        verifier_modules[name] = _load_bound_module(
            repo_root, source_bytes, source_path, source_kind="verifier",
        )
    generator_imports = {
        "specialist_semantics": verifier_modules["semantics"],
        "verify_capability_record": verifier_modules["capability"],
    }
    generator_modules: dict[str, ModuleType] = {}
    for name, relative in _GENERATOR_SOURCES.items():
        source_bytes = _require_binding(
            repo_root, generator_bindings[name], "generator source", expected_relative=relative,
        )
        source_path, _canonical = _canonical_path(repo_root, repo_root / relative)
        generator_modules[name] = _load_bound_module(
            repo_root, source_bytes, source_path, source_kind="generator", imports=generator_imports,
        )
    return {
        "image_generator": _bound_callable(generator_modules["image"], "record_at", source_kind="generator"),
        "audio_generator": _bound_callable(generator_modules["audio"], "record_at", source_kind="generator"),
        "trajectory_generator": _bound_callable(generator_modules["reasoning_tool"], "record_at", source_kind="generator"),
        "image_verifier": _bound_callable(verifier_modules["semantics"], "verify_image_supervision", source_kind="verifier"),
        "audio_verifier": _bound_callable(verifier_modules["semantics"], "verify_audio_supervision", source_kind="verifier"),
        "capability_verifier": _bound_callable(verifier_modules["capability"], "verify_record", source_kind="verifier"),
    }

def _source_binding(repo_root: Path, relative: str) -> dict[str, str]:
    path, canonical = _canonical_path(repo_root, repo_root / relative)
    return {"path": canonical, "sha256": _sha256(path.read_bytes())}


def _require_binding(repo_root: Path, binding: object, label: str, *, expected_relative: str | None = None) -> bytes:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise ValueError(f"invalid {label} binding")
    relative, expected = binding["path"], binding["sha256"]
    if not isinstance(relative, str) or not _is_sha256(expected):
        raise ValueError(f"invalid {label} binding")
    path, canonical = _canonical_path(repo_root, repo_root / relative)
    if canonical != relative:
        raise ValueError(f"noncanonical {label} path")
    if expected_relative is not None and canonical != expected_relative:
        raise ValueError(f"{label} role path does not match production authority")
    if not path.is_file() and canonical in _BINDING_PATH_MIGRATIONS:
        migrated_relative = _BINDING_PATH_MIGRATIONS[canonical]
        path, migrated_canonical = _canonical_path(
            repo_root, repo_root / migrated_relative,
        )
        if migrated_canonical != migrated_relative:
            raise ValueError(f"noncanonical migrated {label} path")
    value = path.read_bytes()
    if _sha256(value) != expected:
        raise ValueError(f"{label} binding does not match")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not _is_sha256(value):
        raise ValueError(f"invalid {label}")
    return str(value)


def _manifest_corpus_root_sha256(families: dict[str, Any]) -> str:
    return _sha256(b"".join(
        _frame(capability.encode("ascii"), bytes.fromhex(_require_sha256(families[capability]["corpus_root_sha256"], "family corpus root")))
        for capability in CAPABILITIES
    ))

def _validate_family_commitment(value: object, *, capability: str, count: int, chunk_size: int) -> None:
    if not isinstance(value, dict) or set(value) != {"record_count", "token_count", "serialized_bytes", "corpus_root_sha256", "chunks"}:
        raise ValueError("invalid stream manifest schema")
    if type(value.get("record_count")) is not int or value["record_count"] != count or type(value.get("token_count")) is not int or value["token_count"] < 1:
        raise ValueError("invalid stream manifest schema")
    if type(value.get("serialized_bytes")) is not int or value["serialized_bytes"] < 1:
        raise ValueError("invalid stream manifest schema")
    _require_sha256(value.get("corpus_root_sha256"), "family corpus root")
    chunks = value.get("chunks")
    expected_chunks = (count + chunk_size - 1) // chunk_size
    if not isinstance(chunks, list) or len(chunks) != expected_chunks:
        raise ValueError("invalid stream manifest schema")
    for index, chunk in enumerate(chunks):
        start = index * chunk_size
        expected_count = min(chunk_size, count - start)
        if not isinstance(chunk, dict) or set(chunk) != {"start", "record_count", "sha256"}:
            raise ValueError("invalid stream manifest schema")
        if type(chunk.get("start")) is not int or type(chunk.get("record_count")) is not int or chunk["start"] != start or chunk["record_count"] != expected_count:
            raise ValueError("invalid stream manifest schema")
        _require_sha256(chunk.get("sha256"), f"{capability} chunk")


class ExecutionSelection:
    """Sequential route/split iterator backed by at most one verified chunk."""

    def __init__(self, stream: "SpecialistStream", receipt: dict[str, object]) -> None:
        self._stream = stream
        self.receipt = receipt
        self._chunk_cache: dict[int, list[dict[str, Any]]] = {}
        self._validated_cursor_bytes: bytes | None = None
        self._validated_cursor_state: dict[str, object] | None = None

    def _record_at_source_index(self, source_index: int) -> dict[str, Any]:
        if type(source_index) is not int or not 0 <= source_index < self._stream.count:
            raise ValueError("invalid execution selection source index")
        if self._stream.chunk_size is None:
            raise ValueError("stream chunk size is required")
        capability = self.receipt["capability"]
        if not isinstance(capability, str):
            raise ValueError("invalid execution selection capability")
        start = (source_index // self._stream.chunk_size) * self._stream.chunk_size
        chunk = self._chunk_cache.get(start)
        if chunk is None:
            chunk = self._stream._materialize_verified_chunk(capability, start)
            self._chunk_cache = {start: chunk}
        return chunk[source_index - start]

    def _initial_cursor(self) -> dict[str, object]:
        return {
            "schema_version": SELECTION_CURSOR_SCHEMA_VERSION,
            "selection_receipt_sha256": _sha256(canonical_record_bytes(self.receipt)),
            "selection_rule_id": self.receipt["selection_rule_id"],
            "selected_ordinal": 0,
            "next_source_index": 0,
        }

    def _validated_cursor(self, cursor: object) -> dict[str, object]:
        if cursor is None:
            return self._initial_cursor()
        expected_fields = {"schema_version", "selection_receipt_sha256", "selection_rule_id", "selected_ordinal", "next_source_index"}
        if not isinstance(cursor, dict) or set(cursor) != expected_fields:
            raise ValueError("invalid selection cursor")
        if cursor.get("schema_version") != SELECTION_CURSOR_SCHEMA_VERSION or cursor.get("selection_receipt_sha256") != _sha256(canonical_record_bytes(self.receipt)):
            raise ValueError("selection cursor does not match receipt")
        if cursor.get("selection_rule_id") != self.receipt["selection_rule_id"]:
            raise ValueError("selection cursor does not match rule")
        for field in ("selected_ordinal", "next_source_index"):
            if type(cursor.get(field)) is not int or cursor[field] < 0:
                raise ValueError("invalid selection cursor")
        if cursor["selected_ordinal"] > self.receipt["selected_record_count"] or cursor["next_source_index"] > self._stream.count:
            raise ValueError("invalid selection cursor")
        return dict(cursor)

    def _validate_cursor_progress(self, cursor: object) -> dict[str, object]:
        """Prove the resumable cursor names exactly the generated selection prefix."""
        state = self._validated_cursor(cursor)
        capability = self.receipt["capability"]
        rule = self.receipt["selection_rule_id"]
        if not isinstance(capability, str) or not isinstance(rule, str):
            raise ValueError("invalid execution selection receipt")
        selected = 0
        for source_index in range(state["next_source_index"]):
            if self._stream._selection_rule_matches(capability, rule, self._record_at_source_index(source_index)):
                selected += 1
        if selected != state["selected_ordinal"]:
            raise ValueError("selection cursor progress does not match source prefix")
        if state["next_source_index"] and not self._stream._selection_rule_matches(
            capability, rule, self._record_at_source_index(state["next_source_index"] - 1),
        ):
            raise ValueError("selection cursor progress does not end after a selected record")
        if state["next_source_index"] == self._stream.count and selected != self.receipt["selected_record_count"]:
            raise ValueError("selection cursor progress does not reach selection end")
        return state

    def _cache_validated_cursor(self, cursor: object) -> dict[str, object]:
        state = self._validate_cursor_progress(cursor)
        self._validated_cursor_bytes = canonical_record_bytes(state)
        self._validated_cursor_state = dict(state)
        return state

    def _validated_or_cached_cursor(self, cursor: object) -> dict[str, object]:
        if cursor is not None and isinstance(cursor, dict) and self._validated_cursor_bytes is not None and self._validated_cursor_state is not None:
            if canonical_record_bytes(cursor) == self._validated_cursor_bytes and cursor.get("selection_receipt_sha256") == _sha256(canonical_record_bytes(self.receipt)):
                return dict(self._validated_cursor_state)
        return self._cache_validated_cursor(cursor)

    def iter_from(self, cursor: object = None):
        """Yield records and the exact resume cursor without retaining a family list."""
        state = self._validated_or_cached_cursor(cursor)
        capability = self.receipt["capability"]
        rule = self.receipt["selection_rule_id"]
        if not isinstance(capability, str) or not isinstance(rule, str):
            raise ValueError("invalid execution selection receipt")
        for source_index in range(state["next_source_index"], self._stream.count):
            record = self._record_at_source_index(source_index)
            if not self._stream._selection_rule_matches(capability, rule, record):
                continue
            next_state = dict(state)
            next_state["selected_ordinal"] += 1
            next_state["next_source_index"] = source_index + 1
            yield record, next_state
            state = next_state

    def __iter__(self):
        for record, _cursor in self.iter_from():
            yield record


class SpecialistStream:
    def __init__(self, tokenizer: Tokenizer, count: int, families: dict[str, Any], *, chunk_size: int | None = None, manifest_sha256: str | None = None, runtime: dict[str, Any] | None = None) -> None:
        if manifest_sha256 is not None and not _is_sha256(manifest_sha256):
            raise ValueError("invalid specialist stream manifest identity")
        self.tokenizer = tokenizer
        self.count = count
        self.families = families
        self.chunk_size = chunk_size
        self.manifest_sha256 = manifest_sha256
        self.runtime = runtime or {
            "image_generator": vision_record_at,
            "audio_generator": audio_record_at,
            "trajectory_generator": trajectory_record_at,
            "image_verifier": verify_image_supervision,
            "audio_verifier": verify_audio_supervision,
            "capability_verifier": verify_capability_record,
        }
        self._chunk_index = {
            capability: {int(chunk["start"]): chunk for chunk in family.get("chunks", [])}
            for capability, family in families.items()
            if isinstance(family, dict) and isinstance(family.get("chunks"), list)
        }

    def record_at(self, capability: str, index: int) -> dict[str, Any]:
        if capability == "image":
            return self.runtime["image_generator"](self.tokenizer, count=self.count, image_marker=31_998, index=index)
        if capability == "audio":
            return self.runtime["audio_generator"](self.tokenizer, count=self.count, audio_marker=31_999, index=index)
        if capability in {"reasoning", "tool"}:
            return self.runtime["trajectory_generator"](self.tokenizer, count=self.count, capability=capability, index=index)
        raise ValueError("unsupported specialist capability")

    def verify_record(self, record: dict[str, Any]) -> dict[str, str]:
        active_expert = record.get("active_expert")
        capability = "image" if active_expert == "vision" else active_expert
        if capability == "image":
            patches = [base64.b64decode(value, validate=True) for value in record["image_patches_u8_base64"]]
            self.runtime["image_verifier"](record, patches=patches, tokenizer=self.tokenizer, image_marker=31_998)
        elif capability == "audio":
            frames = [base64.b64decode(value, validate=True) for value in record["audio_frames_i16le_base64"]]
            self.runtime["audio_verifier"](record, frames=frames, tokenizer=self.tokenizer, audio_marker=31_999)
        elif capability in {"reasoning", "tool"}:
            self.runtime["capability_verifier"](record)
        else:
            raise ValueError("record lacks a specialist capability")
        return {"result": "VERIFIED", "capability": str(capability), "record_sha256": _sha256(canonical_record_bytes(record))}

    def _materialize_verified_chunk(self, capability: str, start: int) -> list[dict[str, Any]]:
        if self.chunk_size is None:
            raise ValueError("stream chunk size is required")
        family = self.families.get(capability)
        if not isinstance(family, dict):
            raise ValueError("missing capability commitment")
        chunks = family.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("missing chunk commitments")
        if type(start) is not int or start < 0 or start >= self.count or start % self.chunk_size:
            raise ValueError("invalid stream chunk start")
        records = [self.record_at(capability, item) for item in range(start, min(start + self.chunk_size, self.count))]
        hashes: list[str] = []
        for record in records:
            hashes.append(self.verify_record(record)["record_sha256"])
        expected = self._chunk_index.get(capability, {}).get(start)
        if not isinstance(expected, dict) or expected.get("record_count") != len(hashes) or expected.get("sha256") != _chunk_sha256(capability, start, hashes):
            raise ValueError("chunk commitment does not match")
        return records

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
        if self.chunk_size is None or limit > self.chunk_size:
            raise ValueError("stream request exceeds manifest chunk bound")
        end = min(start + limit, self.count)
        records: list[dict[str, Any]] = []
        chunk_start = (start // self.chunk_size) * self.chunk_size
        while chunk_start < end:
            chunk = self._materialize_verified_chunk(capability, chunk_start)
            first = max(start, chunk_start) - chunk_start
            last = min(end, chunk_start + len(chunk)) - chunk_start
            records.extend(chunk[first:last])
            chunk_start += self.chunk_size
        return records, {"schema_version": CURSOR_SCHEMA_VERSION, "manifest_sha256": self.manifest_sha256, "capability": capability, "next_index": start + len(records)}

    @staticmethod
    def _read_bound_build_receipt(
        path: Path, expected_sha256: str, *, receipt_bytes: bytes | None = None,
    ) -> dict[str, object]:
        if not _is_sha256(expected_sha256):
            raise ValueError("expected stream build receipt SHA-256 is required")
        if receipt_bytes is None:
            try:
                with path.open("rb") as receipt_file:
                    receipt_bytes = receipt_file.read(MAX_MANIFEST_BYTES + 1)
            except OSError as error:
                raise ValueError("stream build receipt cannot be read") from error
        elif not isinstance(receipt_bytes, bytes):
            raise ValueError("stream build receipt bytes are invalid")
        if len(receipt_bytes) > MAX_MANIFEST_BYTES or _sha256(receipt_bytes) != expected_sha256:
            raise ValueError("stream build receipt does not match caller authority")
        try:
            receipt = json.loads(receipt_bytes)
        except json.JSONDecodeError as error:
            raise ValueError("invalid stream build receipt") from error
        required = {"schema_version", "result", "boundary", "stream_manifest_sha256", "lineage", "data_class", "corpus_root_sha256", "record_count_per_family", "families", "elapsed_ms"}
        if not isinstance(receipt, dict) or set(receipt) != required:
            raise ValueError("invalid stream build receipt")
        if receipt.get("schema_version") != "ember-owned-specialist-stream-build-receipt-v1" or receipt.get("result") != "MEASURED":
            raise ValueError("invalid stream build receipt")
        if receipt.get("data_class") != "SEMANTIC_PRETRAINING":
            raise ValueError("invalid stream build receipt data class")
        if receipt.get("lineage") != "NEW_PREREGISTERED_STREAM" or receipt.get("boundary") != "STREAM_CONSTRUCTION_NOT_SUFFICIENT_PRETRAINING_OR_CAPABILITY":
            raise ValueError("invalid stream build receipt authority")
        if not _is_sha256(receipt.get("stream_manifest_sha256")) or not _is_sha256(receipt.get("corpus_root_sha256")):
            raise ValueError("invalid stream build receipt binding")
        if type(receipt.get("record_count_per_family")) is not int or type(receipt.get("elapsed_ms")) is not int or receipt["elapsed_ms"] < 0:
            raise ValueError("invalid stream build receipt")
        families = receipt.get("families")
        if not isinstance(families, dict) or set(families) != set(CAPABILITIES):
            raise ValueError("invalid stream build receipt families")
        for capability in CAPABILITIES:
            family = families[capability]
            if not isinstance(family, dict) or set(family) != {"records", "tokens", "serialized_bytes_not_materialized"}:
                raise ValueError("invalid stream build receipt families")
            if any(type(family[field]) is not int or family[field] < 1 for field in family):
                raise ValueError("invalid stream build receipt families")
        return receipt

    @staticmethod
    def _validate_selection_rule(capability: str, selection_rule_id: str) -> None:
        if capability == "image" and selection_rule_id == "image_scene_split_train_v1":
            return
        if capability in {"audio", "reasoning", "tool"} and selection_rule_id == "all_records_semantic_pretraining_v1":
            return
        raise ValueError("unsupported execution selection rule")

    @classmethod
    def _selection_rule_matches(cls, capability: str, selection_rule_id: str, record: dict[str, Any]) -> bool:
        cls._validate_selection_rule(capability, selection_rule_id)
        if capability == "image":
            return record.get("active_expert") == "vision" and record.get("scene_split") == "train"
        return record.get("active_expert") == capability

    def _derive_execution_selection(self, *, capability: str, selection_rule_id: str, build_receipt_sha256: str) -> ExecutionSelection:
        if capability not in CAPABILITIES or self.manifest_sha256 is None or self.chunk_size is None:
            raise ValueError("execution selection requires an immutable stream")
        self._validate_selection_rule(capability, selection_rule_id)
        family = self.families.get(capability)
        if not isinstance(family, dict) or not _is_sha256(family.get("corpus_root_sha256")):
            raise ValueError("execution selection requires family commitment")
        selected_records = hashlib.sha256(_frame(b"schema", SELECTION_RECEIPT_SCHEMA_VERSION.encode("ascii")))
        commitment = hashlib.sha256(
            _frame(b"schema", SELECTION_RECEIPT_SCHEMA_VERSION.encode("ascii"))
            + _frame(b"manifest", bytes.fromhex(self.manifest_sha256))
            + _frame(b"stream_build_receipt", bytes.fromhex(build_receipt_sha256))
            + _frame(b"corpus", bytes.fromhex(_manifest_corpus_root_sha256(self.families)))
            + _frame(b"family", bytes.fromhex(str(family["corpus_root_sha256"])))
            + _frame(b"capability", capability.encode("ascii"))
            + _frame(b"rule", selection_rule_id.encode("ascii"))
        )
        count = 0
        tokens = 0
        for start in range(0, self.count, self.chunk_size):
            for offset, record in enumerate(self._materialize_verified_chunk(capability, start)):
                if not self._selection_rule_matches(capability, selection_rule_id, record):
                    continue
                source_index = start + offset
                record_sha256 = _sha256(canonical_record_bytes(record))
                selected_records.update(_frame(b"ordinal", count.to_bytes(8, "big")))
                selected_records.update(_frame(b"record", bytes.fromhex(record_sha256)))
                commitment.update(_frame(b"ordinal", count.to_bytes(8, "big")))
                commitment.update(_frame(b"source", source_index.to_bytes(8, "big")))
                commitment.update(_frame(b"record", bytes.fromhex(record_sha256)))
                token_ids = record.get("token_ids")
                if not isinstance(token_ids, list):
                    raise ValueError("execution selection record lacks token ids")
                count += 1
                tokens += len(token_ids)
        if count < 1:
            raise ValueError("execution selection has no records")
        if selection_rule_id == "all_records_semantic_pretraining_v1" and count != self.count:
            raise ValueError("all-record execution selection is incomplete")
        receipt: dict[str, object] = {
            "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
            "stream_manifest_sha256": self.manifest_sha256,
            "stream_build_receipt_sha256": build_receipt_sha256,
            "corpus_root_sha256": _manifest_corpus_root_sha256(self.families),
            "family_root_sha256": family["corpus_root_sha256"],
            "capability": capability,
            "selection_rule_id": selection_rule_id,
            "selected_record_count": count,
            "selected_token_count": tokens,
            "selected_records_sha256": selected_records.hexdigest(),
            "selection_commitment_sha256": commitment.hexdigest(),
        }
        return ExecutionSelection(self, receipt)

    def prepare_execution_selection(
        self, *, capability: str, selection_rule_id: str, build_receipt_path: Path,
        expected_build_receipt_sha256: str, build_receipt_bytes: bytes | None = None,
    ) -> ExecutionSelection:
        receipt = self._read_bound_build_receipt(
            build_receipt_path, expected_build_receipt_sha256, receipt_bytes=build_receipt_bytes,
        )
        if self.manifest_sha256 is None or receipt.get("stream_manifest_sha256") != self.manifest_sha256:
            raise ValueError("stream build receipt manifest binding does not match")
        if receipt.get("corpus_root_sha256") != _manifest_corpus_root_sha256(self.families):
            raise ValueError("stream build receipt corpus binding does not match")
        if receipt.get("record_count_per_family") != self.count or not isinstance(receipt.get("families"), dict):
            raise ValueError("stream build receipt family binding does not match")
        for family_capability in CAPABILITIES:
            expected_family = self.families.get(family_capability)
            actual_family = receipt["families"].get(family_capability)
            if not isinstance(expected_family, dict) or not isinstance(actual_family, dict):
                raise ValueError("stream build receipt family binding does not match")
            if actual_family != {
                "records": expected_family.get("record_count"),
                "tokens": expected_family.get("token_count"),
                "serialized_bytes_not_materialized": expected_family.get("serialized_bytes"),
            }:
                raise ValueError("stream build receipt family binding does not match")
        return self._derive_execution_selection(
            capability=capability,
            selection_rule_id=selection_rule_id,
            build_receipt_sha256=expected_build_receipt_sha256,
        )

    def open_execution_selection(
        self, *, receipt: object, cursor: object, build_receipt_path: Path,
        expected_build_receipt_sha256: str, expected_selection_receipt_sha256: str,
        build_receipt_bytes: bytes | None = None,
    ) -> ExecutionSelection:
        expected_fields = {
            "schema_version", "stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256",
            "family_root_sha256", "capability", "selection_rule_id", "selected_record_count", "selected_token_count",
            "selected_records_sha256", "selection_commitment_sha256",
        }
        if not isinstance(receipt, dict) or set(receipt) != expected_fields:
            raise ValueError("invalid execution selection receipt")
        if not _is_sha256(expected_selection_receipt_sha256) or _sha256(canonical_record_bytes(receipt)) != expected_selection_receipt_sha256:
            raise ValueError("execution selection receipt does not match caller authority")
        build = self._read_bound_build_receipt(
            build_receipt_path, expected_build_receipt_sha256, receipt_bytes=build_receipt_bytes,
        )
        if (
            self.manifest_sha256 is None or build.get("stream_manifest_sha256") != self.manifest_sha256
            or receipt.get("stream_manifest_sha256") != self.manifest_sha256
            or receipt.get("stream_build_receipt_sha256") != expected_build_receipt_sha256
            or receipt.get("corpus_root_sha256") != _manifest_corpus_root_sha256(self.families)
            or build.get("corpus_root_sha256") != receipt.get("corpus_root_sha256")
        ):
            raise ValueError("execution selection build receipt does not match stream authority")
        capability = receipt.get("capability")
        selection_rule_id = receipt.get("selection_rule_id")
        family = self.families.get(capability) if isinstance(capability, str) else None
        if not isinstance(capability, str) or not isinstance(selection_rule_id, str) or not isinstance(family, dict):
            raise ValueError("invalid execution selection receipt")
        self._validate_selection_rule(capability, selection_rule_id)
        if receipt.get("family_root_sha256") != family.get("corpus_root_sha256"):
            raise ValueError("execution selection family authority does not match")
        for field in ("selected_record_count", "selected_token_count"):
            if type(receipt.get(field)) is not int or receipt[field] < 1:
                raise ValueError("invalid execution selection receipt")
        selection = ExecutionSelection(self, dict(receipt))
        selection._cache_validated_cursor(cursor)
        return selection

    def validate_capability_commitment(self, capability: str) -> dict[str, int]:
        """Recompute one route's raw records, execution targets, chunk and root commitments."""
        if capability not in CAPABILITIES:
            raise ValueError("unsupported specialist capability")
        hashes: list[str] = []
        token_count = 0
        serialized_bytes = 0
        if self.chunk_size is None:
            raise ValueError("stream chunk size is required")
        for start in range(0, self.count, self.chunk_size):
            for record in self._materialize_verified_chunk(capability, start):
                encoded = canonical_record_bytes(record)
                hashes.append(_sha256(encoded))
                token_ids = record.get("token_ids")
                if not isinstance(token_ids, list):
                    raise ValueError("generated record lacks token ids")
                token_count += len(token_ids)
                serialized_bytes += len(encoded)
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
            if self.chunk_size is None:
                raise ValueError("stream chunk size is required")
            for start in range(0, self.count, self.chunk_size):
                for record in self._materialize_verified_chunk(capability, start):
                    encoded = canonical_record_bytes(record)
                    hashes.append(_sha256(encoded))
                    token_ids = record.get("token_ids")
                    if not isinstance(token_ids, list):
                        raise ValueError("generated record lacks token ids")
                    token_count += len(token_ids)
                    serialized_bytes += len(encoded)
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
        stream.verify_record(record)
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
    if record_count > MAX_RECORDS_PER_FAMILY:
        raise ValueError("stream record count bound exceeded")
    if chunk_size > MAX_CHUNK_RECORDS or chunk_size > record_count:
        raise ValueError("stream chunk bound exceeded")
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
    generator_sources = {name: _source_binding(repo_root, relative) for name, relative in _GENERATOR_SOURCES.items()}
    verifier_sources = {name: _source_binding(repo_root, relative) for name, relative in _VERIFIER_SOURCES.items()}
    tokenizer = Tokenizer.from_str(tokenizer_bytes.decode("utf-8"))
    runtime = _load_bound_runtime(repo_root, generator_sources, verifier_sources)
    stream = SpecialistStream(tokenizer, record_count, {}, runtime=runtime)
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
        "consumer_limits": {"max_records_per_family": MAX_RECORDS_PER_FAMILY, "max_chunk_records": MAX_CHUNK_RECORDS},
        "model_config": {"path": config_relative, "sha256": _sha256(config_bytes)},
        "generator_sources": generator_sources,
        "verifier_sources": verifier_sources,
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

def open_specialist_stream(
    *, repo_root: Path, manifest_path: Path, expected_manifest_sha256: str | None = None,
    expected_corpus_root_sha256: str | None = None, manifest_bytes: bytes | None = None,
) -> SpecialistStream:
    if not _is_sha256(expected_manifest_sha256):
        raise ValueError("expected manifest SHA-256 is required")
    if not _is_sha256(expected_corpus_root_sha256):
        raise ValueError("expected corpus root SHA-256 is required")
    if manifest_bytes is None:
        try:
            with manifest_path.open("rb") as manifest_file:
                manifest_bytes = manifest_file.read(MAX_MANIFEST_BYTES + 1)
        except OSError as error:
            raise ValueError("stream manifest cannot be read") from error
    elif not isinstance(manifest_bytes, bytes):
        raise ValueError("stream manifest bytes are invalid")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError("stream manifest exceeds consumer byte bound")
    if _sha256(manifest_bytes) != expected_manifest_sha256:
        raise ValueError("stream manifest identity does not match caller authority")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("invalid stream manifest") from error
    required_top_level = {
        "schema_version", "lineage", "legacy_materialized_compatibility", "data_class",
        "generator_contract", "range", "chunk_size", "tokenizer", "consumer_limits",
        "model_config", "generator_sources", "verifier_sources", "families", "corpus_root_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != required_top_level:
        raise ValueError("invalid stream manifest schema")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("lineage") != "NEW_PREREGISTERED_STREAM":
        raise ValueError("invalid stream manifest")
    if manifest.get("legacy_materialized_compatibility") != "UNAVAILABLE_NO_ACCEPTED_ARTIFACT_BOUND_AT_KNOWN_PATH":
        raise ValueError("invalid stream manifest schema")
    if manifest.get("generator_contract") != {"version": "owned-specialist-indexed-v1", "randomness": "INDEX_PURE_NO_PRNG", "seed": None}:
        raise ValueError("invalid generator contract binding")
    stream_range = manifest.get("range")
    if not isinstance(stream_range, dict) or set(stream_range) != {"start", "record_count_per_family"} or type(stream_range.get("start")) is not int or stream_range["start"] != 0:
        raise ValueError("invalid stream range")
    count = stream_range.get("record_count_per_family")
    chunk_size = manifest.get("chunk_size")
    data_class = manifest.get("data_class")
    if type(count) is not int or type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("invalid stream range")
    if manifest.get("consumer_limits") != {"max_records_per_family": MAX_RECORDS_PER_FAMILY, "max_chunk_records": MAX_CHUNK_RECORDS}:
        raise ValueError("invalid consumer stream limits")
    if count > MAX_RECORDS_PER_FAMILY:
        raise ValueError("stream record count bound exceeded")
    if chunk_size > MAX_CHUNK_RECORDS or chunk_size > count:
        raise ValueError("stream chunk bound exceeded")
    if data_class == "SEMANTIC_PRETRAINING" and count < SEMANTIC_MIN_RECORDS:
        raise ValueError("SEMANTIC_PRETRAINING range is too small")
    if data_class == "MEASURED_RUNG" and count < MEASURED_MIN_RECORDS:
        raise ValueError("MEASURED_RUNG range is too small")
    if data_class not in {"SEMANTIC_PRETRAINING", "MEASURED_RUNG"}:
        raise ValueError("unknown specialist stream data class")
    if manifest.get("corpus_root_sha256") != expected_corpus_root_sha256:
        raise ValueError("stream corpus root does not match caller authority")
    _require_sha256(manifest.get("corpus_root_sha256"), "stream corpus root")
    tokenizer_bytes = _require_binding(repo_root, manifest.get("tokenizer"), "tokenizer")
    _require_binding(repo_root, manifest.get("model_config"), "model config")
    sources = manifest.get("generator_sources")
    if not isinstance(sources, dict) or set(sources) != set(_GENERATOR_SOURCES):
        raise ValueError("invalid generator source bindings")
    for name, relative in _GENERATOR_SOURCES.items():
        _require_binding(repo_root, sources[name], "generator source", expected_relative=relative)
    verifiers = manifest.get("verifier_sources")
    if not isinstance(verifiers, dict) or set(verifiers) != set(_VERIFIER_SOURCES):
        raise ValueError("invalid verifier source bindings")
    for name, relative in _VERIFIER_SOURCES.items():
        _require_binding(repo_root, verifiers[name], "verifier source", expected_relative=relative)
    families = manifest.get("families")
    if not isinstance(families, dict) or set(families) != set(CAPABILITIES):
        raise ValueError("invalid family commitments")
    for capability in CAPABILITIES:
        _validate_family_commitment(families[capability], capability=capability, count=count, chunk_size=chunk_size)
    if _manifest_corpus_root_sha256(families) != manifest["corpus_root_sha256"]:
        raise ValueError("stream corpus root does not bind family roots")
    runtime = _load_bound_runtime(repo_root, sources, verifiers)
    return SpecialistStream(Tokenizer.from_str(tokenizer_bytes.decode("utf-8")), count, families, chunk_size=chunk_size, manifest_sha256=_sha256(manifest_bytes), runtime=runtime)
