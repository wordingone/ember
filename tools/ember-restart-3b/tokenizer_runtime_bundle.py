# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Temporary, content-addressed tokenizer runtime bundles for isolated P2B CLI use."""

from __future__ import annotations

import base64
import csv
import ctypes
from contextlib import contextmanager
import hashlib
import importlib
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import sysconfig
from typing import Any, Iterator
import uuid


SCHEMA_VERSION = "ember-p2b-tokenizer-runtime-bundle-v1"
_MANIFEST_NAME = "tokenizer-runtime-manifest.json"


def _after_final_validation_before_import_for_test(_bundle_root: Path) -> None:
    """Deterministic test seam; production has no caller-configurable hook."""


def _hold_windows_read_locks(paths: list[Path]) -> list[int]:
    """Keep every admitted byte read-share-only through the import boundary."""
    if os.name != "nt":
        raise ValueError("tokenizer runtime immutable import boundary requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    handles: list[int] = []
    invalid = ctypes.c_void_p(-1).value
    try:
        for path in paths:
            handle = create_file(str(path), 0x80000000, 0x00000001, None, 3, 0x80, None)
            if handle == invalid:
                raise OSError(ctypes.get_last_error(), "unable to hold tokenizer runtime byte")
            handles.append(int(handle))
    except Exception:
        for handle in handles:
            close_handle(ctypes.c_void_p(handle))
        raise
    return handles


def _release_windows_read_locks(handles: list[int]) -> list[OSError]:
    errors: list[OSError] = []
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        for handle in handles:
            if not kernel32.CloseHandle(ctypes.c_void_p(handle)):
                errors.append(OSError(ctypes.get_last_error(), "unable to release tokenizer runtime byte"))
    return errors


class _BoundRuntimeFinder:
    """Reject private-root imports whose byte is outside the admitted manifest."""

    def __init__(self, *, root: Path, allowed_files: set[Path]) -> None:
        self._root = root
        self._allowed_files = allowed_files

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        origin = getattr(spec, "origin", None)
        if not isinstance(origin, str) or origin in {"built-in", "frozen"}:
            return spec
        candidate = Path(origin).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            return spec
        if candidate not in self._allowed_files:
            raise ImportError("tokenizer runtime import resolved an unlisted private byte")
        return spec


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("tokenizer runtime file path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.parts == (".",):
        raise ValueError("tokenizer runtime file path is invalid")
    return value


def _root_commitment(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in files:
        digest.update(len(record["path"].encode("utf-8")).to_bytes(4, "big"))
        digest.update(record["path"].encode("utf-8"))
        digest.update(int(record["bytes"]).to_bytes(8, "big"))
        digest.update(bytes.fromhex(str(record["sha256"])))
    return digest.hexdigest()


def _compatibility() -> dict[str, str]:
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "cache_tag": sys.implementation.cache_tag or "",
        "abi_tag": sysconfig.get_config_var("SOABI") or "",
        "platform_tag": sysconfig.get_platform(),
    }


def _decode_record_sha256(encoded: object) -> bytes:
    """Accept only canonical unpadded URL-safe sha256 RECORD encodings."""
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("tokenizers RECORD hash is unsupported")
    try:
        decoded = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True,
        )
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("tokenizers RECORD hash is unsupported") from error
    if (base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != encoded
            or len(decoded) != hashlib.sha256().digest_size):
        raise ValueError("tokenizers RECORD hash is unsupported")
    return decoded


def _record_inventory() -> tuple[Path, str, str, bytes, list[dict[str, object]]]:
    """Use RECORD, not package-tree discovery, as the installed-file authority."""
    distribution = importlib.metadata.distribution("tokenizers")
    record_candidates = [
        item for item in distribution.files or ()
        if item.name == "RECORD" and any(part.endswith(".dist-info") for part in item.parts)
    ]
    if len(record_candidates) != 1:
        raise ValueError("tokenizers distribution lacks RECORD authority")
    record_relative = record_candidates[0]
    dist_info = PurePosixPath(str(record_relative)).parent
    metadata_candidates = [
        item for item in distribution.files or ()
        if item.name == "METADATA" and PurePosixPath(str(item)).parent == dist_info
    ]
    if len(metadata_candidates) != 1:
        raise ValueError("tokenizers distribution lacks matching METADATA authority")
    record_path = Path(distribution.locate_file(record_relative)).resolve()
    site_root = Path(distribution.locate_file("")).resolve()
    record_bytes = record_path.read_bytes()
    records: list[dict[str, object]] = []
    for row in csv.reader(record_bytes.decode("utf-8").splitlines()):
        if len(row) != 3:
            raise ValueError("tokenizers RECORD row is invalid")
        relative = _safe_relative(row[0])
        source = site_root.joinpath(*PurePosixPath(relative).parts)
        if not source.is_file() or source.is_symlink():
            raise ValueError("tokenizers RECORD file is missing")
        payload = source.read_bytes()
        if row[2] and (not row[2].isdigit() or int(row[2]) != len(payload)):
            raise ValueError("tokenizers RECORD size mismatch")
        if row[1]:
            algorithm, separator, encoded = row[1].partition("=")
            if algorithm != "sha256" or not separator:
                raise ValueError("tokenizers RECORD hash is unsupported")
            expected = _decode_record_sha256(encoded)
            if expected != hashlib.sha256(payload).digest():
                raise ValueError("tokenizers RECORD hash mismatch")
        elif source != record_path:
            # Wheel RECORDs may retain interpreter-generated pyc cache rows
            # without hashes.  They are not executable distribution authority
            # and must not enter the isolated closure.
            if "__pycache__" in PurePosixPath(relative).parts and relative.endswith(".pyc"):
                continue
            raise ValueError("tokenizers RECORD omits a file hash")
        records.append({"path": relative, "bytes": len(payload), "sha256": _sha256_bytes(payload)})
    if not records or len({item["path"] for item in records}) != len(records):
        raise ValueError("tokenizers RECORD inventory is invalid")
    records.sort(key=lambda item: str(item["path"]))
    return site_root, "tokenizers", distribution.version, record_bytes, records


def materialize_tokenizer_runtime_bundle(*, bundle_parent: Path) -> tuple[Path, Path, dict[str, object]]:
    """Copy exactly RECORD-listed bytes into one fresh private root."""
    bundle_parent = Path(bundle_parent).resolve()
    bundle_parent.mkdir(parents=True, exist_ok=True)
    bundle_root = bundle_parent / f"tokenizers-runtime-{uuid.uuid4().hex}"
    manifest_path = bundle_root / _MANIFEST_NAME
    site_root, name, version, record_bytes, records = _record_inventory()
    bundle_root.mkdir()
    try:
        for record in records:
            relative = str(record["path"])
            source = site_root.joinpath(*PurePosixPath(relative).parts)
            target = bundle_root.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "distribution": {"name": name, "version": version},
            "record_sha256": _sha256_bytes(record_bytes),
            "compatibility": _compatibility(),
            "files": records,
            "root_sha256": _root_commitment(records),
        }
        manifest_path.write_bytes(_canonical_bytes(manifest))
        return bundle_root, manifest_path, validate_tokenizer_runtime_bundle(bundle_root=bundle_root, manifest_path=manifest_path)
    except Exception:
        shutil.rmtree(bundle_root, ignore_errors=True)
        raise


def _bundled_record_inventory(root: Path, records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Reparse bundled RECORD and derive the exact trusted runtime file set."""
    record_candidates = [item for item in records if str(item["path"]).endswith(".dist-info/RECORD")]
    if len(record_candidates) != 1:
        raise ValueError("tokenizer runtime RECORD is missing")
    record = record_candidates[0]
    dist_info = PurePosixPath(str(record["path"])).parent
    metadata_candidates = [
        item for item in records
        if PurePosixPath(str(item["path"])).parent == dist_info
        and PurePosixPath(str(item["path"])).name == "METADATA"
    ]
    if len(metadata_candidates) != 1:
        raise ValueError("tokenizer runtime METADATA is missing")
    record_path = root.joinpath(*PurePosixPath(str(record["path"])).parts)
    payload = record_path.read_bytes()
    derived: list[dict[str, object]] = []
    for row in csv.reader(payload.decode("utf-8").splitlines()):
        if len(row) != 3:
            raise ValueError("tokenizer runtime RECORD row is invalid")
        relative = _safe_relative(row[0])
        if not row[1] and relative != record["path"] and "__pycache__" in PurePosixPath(relative).parts and relative.endswith(".pyc"):
            continue
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file() or target.is_symlink():
            raise ValueError("tokenizer runtime RECORD file is missing")
        content = target.read_bytes()
        if row[2] and (not row[2].isdigit() or int(row[2]) != len(content)):
            raise ValueError("tokenizer runtime RECORD size mismatch")
        if row[1]:
            algorithm, separator, encoded = row[1].partition("=")
            if algorithm != "sha256" or not separator:
                raise ValueError("tokenizer runtime RECORD hash is unsupported")
            expected = _decode_record_sha256(encoded)
            if expected != hashlib.sha256(content).digest():
                raise ValueError("tokenizer runtime RECORD hash mismatch")
        elif relative != record["path"]:
            raise ValueError("tokenizer runtime RECORD omits a file hash")
        derived.append({"path": relative, "bytes": len(content), "sha256": _sha256_bytes(content)})
    derived.sort(key=lambda item: str(item["path"]))
    return derived


def validate_tokenizer_runtime_bundle(*, bundle_root: Path, manifest_path: Path) -> dict[str, object]:
    """Validate every bundled byte before P2B adds its explicit root to sys.path."""
    bundle_root = Path(bundle_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    if manifest_path.parent != bundle_root or manifest_path.name != _MANIFEST_NAME:
        raise ValueError("tokenizer runtime manifest must be the exact bundle-root manifest")
    if not bundle_root.is_dir() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("tokenizer runtime bundle is unavailable")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("tokenizer runtime manifest is invalid") from error
    fields = {"schema_version", "distribution", "record_sha256", "compatibility", "files", "root_sha256"}
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("tokenizer runtime manifest is invalid")
    distribution = manifest.get("distribution")
    if not isinstance(distribution, dict) or set(distribution) != {"name", "version"} or distribution.get("name") != "tokenizers" or not isinstance(distribution.get("version"), str) or not distribution["version"]:
        raise ValueError("tokenizer runtime distribution binding is invalid")
    if manifest.get("compatibility") != _compatibility():
        raise ValueError("tokenizer runtime interpreter compatibility mismatch")
    if not isinstance(manifest.get("record_sha256"), str) or len(manifest["record_sha256"]) != 64 or any(character not in "0123456789abcdef" for character in manifest["record_sha256"]):
        raise ValueError("tokenizer runtime RECORD binding is invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("tokenizer runtime manifest has no import closure")
    normalized: list[dict[str, object]] = []
    expected_paths: set[str] = set()
    record_payload: bytes | None = None
    for record in files:
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
            raise ValueError("tokenizer runtime file record is invalid")
        relative = _safe_relative(record.get("path"))
        if relative in expected_paths or type(record.get("bytes")) is not int or record["bytes"] < 0:
            raise ValueError("tokenizer runtime file record is invalid")
        digest = record.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("tokenizer runtime file record is invalid")
        path = bundle_root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink():
            raise ValueError("tokenizer runtime file is missing")
        payload = path.read_bytes()
        if len(payload) != record["bytes"] or _sha256_bytes(payload) != digest:
            raise ValueError("tokenizer runtime file hash mismatch")
        if relative.endswith(".dist-info/RECORD"):
            record_payload = payload
        expected_paths.add(relative)
        normalized.append({"path": relative, "bytes": record["bytes"], "sha256": digest})
    if normalized != sorted(normalized, key=lambda item: str(item["path"])):
        raise ValueError("tokenizer runtime manifest file order is invalid")
    if manifest.get("root_sha256") != _root_commitment(normalized):
        raise ValueError("tokenizer runtime root commitment mismatch")
    if record_payload is None or _sha256_bytes(record_payload) != manifest["record_sha256"]:
        raise ValueError("tokenizer runtime RECORD binding mismatch")
    if _bundled_record_inventory(bundle_root, normalized) != normalized:
        raise ValueError("tokenizer runtime manifest does not match RECORD inventory")
    record_candidates = [item for item in normalized if str(item["path"]).endswith(".dist-info/RECORD")]
    if len(record_candidates) != 1:
        raise ValueError("tokenizer runtime RECORD is missing")
    record_parent = PurePosixPath(str(record_candidates[0]["path"])).parent
    metadata_candidates = [
        item for item in normalized
        if PurePosixPath(str(item["path"])).parent == record_parent
        and PurePosixPath(str(item["path"])).name == "METADATA"
    ]
    if len(metadata_candidates) != 1:
        raise ValueError("tokenizer runtime METADATA is missing")
    metadata = metadata_candidates[0]
    metadata_text = bundle_root.joinpath(*PurePosixPath(str(metadata["path"])).parts).read_text(encoding="utf-8")
    name = next((line.removeprefix("Name: ") for line in metadata_text.splitlines() if line.startswith("Name: ")), None)
    version = next((line.removeprefix("Version: ") for line in metadata_text.splitlines() if line.startswith("Version: ")), None)
    if name != distribution["name"] or version != distribution["version"]:
        raise ValueError("tokenizer runtime METADATA version mismatch")
    actual_paths: set[str] = set()
    for directory, _subdirectories, names in os.walk(bundle_root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("tokenizer runtime bundle contains a symlink")
            relative = path.relative_to(bundle_root).as_posix()
            if relative != _MANIFEST_NAME:
                actual_paths.add(relative)
    if actual_paths != expected_paths:
        raise ValueError("tokenizer runtime bundle contains unexpected files")
    return {
        "schema_version": SCHEMA_VERSION,
        "distribution": dict(distribution),
        "record_sha256": manifest["record_sha256"],
        "compatibility": dict(manifest["compatibility"]),
        "files": normalized,
        "root_sha256": manifest["root_sha256"],
        "manifest_sha256": _sha256_bytes(manifest_bytes),
    }


@contextmanager
def lease_tokenizer_runtime_bundle(*, bundle_root: Path, manifest_path: Path) -> Iterator[dict[str, object]]:
    """Lease one immutable private runtime through the whole stream consumer."""
    manifest = validate_tokenizer_runtime_bundle(bundle_root=bundle_root, manifest_path=manifest_path)
    root = Path(bundle_root).resolve()
    if any(name == "tokenizers" or name.startswith("tokenizers.") for name in sys.modules):
        raise ValueError("tokenizer runtime refuses a preloaded module")
    bound_files = [Path(manifest_path).resolve(), *[
        root.joinpath(*PurePosixPath(str(record["path"])).parts)
        for record in manifest["files"]
    ]]
    bound_paths = bound_files
    handles: list[int] = []
    inserted = False
    finder: _BoundRuntimeFinder | None = None
    previous_dont_write_bytecode = sys.dont_write_bytecode
    body_error: BaseException | None = None
    try:
        handles = _hold_windows_read_locks(bound_paths)
        # Re-read all bytes while Windows denies writes/deletes, then retain
        # the lease through the caller's real stream validation/selection.
        manifest = validate_tokenizer_runtime_bundle(bundle_root=bundle_root, manifest_path=manifest_path)
        sys.dont_write_bytecode = True
        _after_final_validation_before_import_for_test(root)
        sys.path.insert(0, str(root))
        inserted = True
        finder = _BoundRuntimeFinder(root=root, allowed_files=set(bound_files))
        sys.meta_path.insert(0, finder)
        module = importlib.import_module("tokenizers")
        native = importlib.import_module("tokenizers.tokenizers")
        for candidate in (module, native):
            origin = getattr(candidate, "__file__", None)
            if not isinstance(origin, str) or root not in Path(origin).resolve().parents:
                raise ValueError("tokenizer runtime import escaped the private bundle")
        post_import_manifest = validate_tokenizer_runtime_bundle(
            bundle_root=bundle_root, manifest_path=manifest_path,
        )
        if post_import_manifest != manifest:
            raise ValueError("tokenizer runtime authority changed during import")
        yield manifest
    except BaseException as error:
        body_error = error
        raise
    finally:
        if finder is not None:
            try:
                sys.meta_path.remove(finder)
            except ValueError:
                pass
        if inserted:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass
        for name, module in tuple(sys.modules.items()):
            origin = getattr(module, "__file__", None)
            if isinstance(origin, str):
                try:
                    if root in Path(origin).resolve().parents:
                        sys.modules.pop(name, None)
                except OSError:
                    sys.modules.pop(name, None)
        sys.dont_write_bytecode = previous_dont_write_bytecode
        try:
            release_errors = _release_windows_read_locks(handles)
        except BaseException as error:
            release_errors = [OSError(str(error))]
        if release_errors:
            message = "; ".join(str(error) for error in release_errors)
            cleanup_error = RuntimeError(f"tokenizer runtime handle cleanup failed: {message}")
            if body_error is not None:
                body_error._tokenizer_runtime_cleanup_error = str(cleanup_error)
                try:
                    sys.stderr.write(f"{cleanup_error}\n")
                except Exception:
                    pass
            else:
                raise cleanup_error
