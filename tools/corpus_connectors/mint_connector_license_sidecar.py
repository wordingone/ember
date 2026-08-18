# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mint immutable connector custody with one externally receipted LICENSE sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


HEX64 = re.compile(r"[0-9a-f]{64}")
CONNECTOR_RECEIPT = "_manifests/derived-connector-receipt.json"
DERIVATION_RECEIPT = "_manifests/license-sidecar-derivation-receipt.json"
SIDECARS = {"manifest.jsonl"}


class LicenseSidecarRefusal(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _normalize(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise LicenseSidecarRefusal("connector file path is not a closed relative path")
    portable = value.replace("\\", "/")
    parts = portable.split("/")
    if portable.startswith("/") or re.match(r"^[A-Za-z]:", portable) or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise LicenseSidecarRefusal("connector file path is not a closed relative path")
    return "/".join(parts)


def _regular_contained(root: Path, relative: str) -> Path:
    cursor = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError as error:
            raise LicenseSidecarRefusal(f"connector file is missing: {relative}") from error
        if _is_reparse_or_symlink(cursor):
            raise LicenseSidecarRefusal("connector file path crosses a symlink or reparse point")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LicenseSidecarRefusal("connector file path is not a closed relative path")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise LicenseSidecarRefusal("connector file is not regular")
    try:
        cursor.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise LicenseSidecarRefusal("connector file escapes its custody root") from error
    return cursor


def _data_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative.split("/", 1)[0] == "_manifests" or relative in SIDECARS:
            continue
        if path.is_dir() and not _is_reparse_or_symlink(path):
            continue
        if not path.is_file() or _is_reparse_or_symlink(path):
            raise LicenseSidecarRefusal("connector custody contains a non-regular data path")
        paths.add(relative)
    return paths


def _read_bound_receipt(path: Path, expected_sha256: str, label: str) -> tuple[dict[str, Any], bytes]:
    if not isinstance(expected_sha256, str) or HEX64.fullmatch(expected_sha256) is None:
        raise LicenseSidecarRefusal(f"{label} receipt hash is invalid")
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise LicenseSidecarRefusal(f"{label} receipt is not a regular file")
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_sha256:
        raise LicenseSidecarRefusal(f"{label} receipt bytes changed")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema") != "corpus-connector-receipt-v1":
        raise LicenseSidecarRefusal(f"{label} receipt schema is invalid")
    return value, raw


def _reopen_files(receipt: dict[str, Any], label: str) -> tuple[Path, list[dict[str, Any]]]:
    root_value = receipt.get("dest_root")
    files = receipt.get("files")
    if not isinstance(root_value, str) or not root_value or not isinstance(files, list) or not files:
        raise LicenseSidecarRefusal(f"{label} receipt custody is incomplete")
    root = Path(root_value)
    if not root.is_dir() or _is_reparse_or_symlink(root):
        raise LicenseSidecarRefusal(f"{label} custody root is not a regular directory")
    reopened: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise LicenseSidecarRefusal(f"{label} receipt file entry is malformed")
        relative = _normalize(item["path"])
        if relative in seen:
            raise LicenseSidecarRefusal(f"{label} receipt has a duplicate path")
        seen.add(relative)
        path = _regular_contained(root, relative)
        size = item["bytes"]
        digest = item["sha256"]
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or HEX64.fullmatch(digest) is None
            or path.stat().st_size != size
            or sha256_file(path) != digest
        ):
            raise LicenseSidecarRefusal(f"{label} receipt file bytes changed")
        reopened.append({"path": relative, "bytes": size, "sha256": digest, "source_path": path})
    if _data_paths(root) != seen:
        raise LicenseSidecarRefusal(f"{label} custody file set differs from its receipt")
    if receipt.get("total_bytes") != sum(item["bytes"] for item in reopened):
        raise LicenseSidecarRefusal(f"{label} receipt total bytes changed")
    manifest = sha256_bytes("\n".join(sorted(item["sha256"] for item in reopened)).encode("utf-8"))
    if receipt.get("sha256_manifest") != manifest:
        raise LicenseSidecarRefusal(f"{label} receipt manifest changed")
    return root, reopened


def _write_json(path: Path, value: object) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return raw


def mint_license_sidecar(
    *,
    original_receipt_path: Path,
    original_receipt_sha256: str,
    license_receipt_path: Path,
    license_receipt_sha256: str,
    license_payload_path: Path,
    license_payload_sha256: str,
    expected_spdx: str,
    output: Path,
) -> dict[str, Any]:
    original_receipt_path = Path(original_receipt_path)
    license_receipt_path = Path(license_receipt_path)
    license_payload_path = Path(license_payload_path)
    output = Path(output).absolute()
    if output.exists():
        raise LicenseSidecarRefusal(f"output already exists: {output}")
    if not isinstance(expected_spdx, str) or not expected_spdx:
        raise LicenseSidecarRefusal("expected SPDX identity is missing")
    original, _ = _read_bound_receipt(original_receipt_path, original_receipt_sha256, "original connector")
    license_receipt, _ = _read_bound_receipt(license_receipt_path, license_receipt_sha256, "license connector")
    _, original_files = _reopen_files(original, "original connector")
    license_root, license_files = _reopen_files(license_receipt, "license connector")
    if original.get("license") != expected_spdx or license_receipt.get("license") != expected_spdx:
        raise LicenseSidecarRefusal("connector and license SPDX identities differ")
    if any(PurePosixPath(item["path"]).name.upper().startswith("LICENSE") for item in original_files):
        raise LicenseSidecarRefusal("original custody already contains a LICENSE artifact")
    if len(license_files) != 1:
        raise LicenseSidecarRefusal("license connector must bind exactly one payload")
    if (
        not isinstance(license_payload_sha256, str)
        or HEX64.fullmatch(license_payload_sha256) is None
        or not license_payload_path.is_file()
        or _is_reparse_or_symlink(license_payload_path)
        or license_payload_path.resolve(strict=True) != license_files[0]["source_path"].resolve(strict=True)
        or sha256_file(license_payload_path) != license_payload_sha256
        or license_files[0]["sha256"] != license_payload_sha256
    ):
        raise LicenseSidecarRefusal("license payload identity differs from its connector receipt")
    try:
        license_payload_path.resolve(strict=True).relative_to(license_root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise LicenseSidecarRefusal("license payload escapes its connector custody") from error

    output.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_symlink(output.parent):
        raise LicenseSidecarRefusal("output parent is reparsed")
    staging = output.with_name(f".{output.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    published = False
    try:
        derived_files: list[dict[str, Any]] = []
        for item in original_files:
            target = staging / Path(item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item["source_path"], target)
            if target.stat().st_size != item["bytes"] or sha256_file(target) != item["sha256"]:
                raise LicenseSidecarRefusal("derived payload copy changed bytes")
            derived_files.append({key: item[key] for key in ("path", "bytes", "sha256")})
        license_target = staging / "LICENSE.md"
        shutil.copyfile(license_payload_path, license_target)
        if sha256_file(license_target) != license_payload_sha256:
            raise LicenseSidecarRefusal("derived LICENSE copy changed bytes")
        derived_files.append({
            "path": "LICENSE.md",
            "bytes": license_target.stat().st_size,
            "sha256": license_payload_sha256,
        })
        derived_files.sort(key=lambda item: item["path"])
        derived_at = datetime.now(timezone.utc).isoformat()
        derived_receipt = {
            **original,
            "source": "derived_connector_custody",
            "source_id": f"{original.get('source_id')}+license-sidecar",
            "license": expected_spdx,
            "license_evidence": (
                "derived immutable custody; exact original and canonical license connector receipts "
                "are bound in notes and the derivation receipt"
            ),
            "revision": f"{original.get('revision')}+license-sidecar-v1",
            "files": derived_files,
            "total_bytes": sum(item["bytes"] for item in derived_files),
            "sha256_manifest": sha256_bytes(
                "\n".join(sorted(item["sha256"] for item in derived_files)).encode("utf-8")
            ),
            "fetched_at": derived_at,
            "connector": {"name": "license_sidecar_derivation", "version": "v1"},
            "l3_statement": "deterministic local derivation; no network fetch and no model-mediated selection",
            "dest_root": str(output),
            "notes": (
                f"DERIVED_CUSTODY original_connector_receipt_sha256={original_receipt_sha256}; "
                f"license_connector_receipt_sha256={license_receipt_sha256}; "
                f"derivation_receipt={DERIVATION_RECEIPT}; original_source={original.get('source')}"
            ),
        }
        connector_path = staging / CONNECTOR_RECEIPT
        connector_raw = _write_json(connector_path, derived_receipt)
        derivation = {
            "schema_version": "ember-connector-license-sidecar-derivation-v1",
            "result": "VERIFIED",
            "derived_at": derived_at,
            "output_root": str(output),
            "original_connector_receipt_path": str(original_receipt_path.resolve(strict=True)),
            "original_connector_receipt_sha256": original_receipt_sha256,
            "license_connector_receipt_path": str(license_receipt_path.resolve(strict=True)),
            "license_connector_receipt_sha256": license_receipt_sha256,
            "license_payload_source_path": str(license_payload_path.resolve(strict=True)),
            "license_payload_sha256": license_payload_sha256,
            "license_output_path": "LICENSE.md",
            "expected_spdx": expected_spdx,
            "derived_connector_receipt_path": CONNECTOR_RECEIPT,
            "derived_connector_receipt_sha256": sha256_bytes(connector_raw),
            "derived_file_count": len(derived_files),
            "derived_total_bytes": derived_receipt["total_bytes"],
            "derived_manifest_sha256": derived_receipt["sha256_manifest"],
            "producer_path": "tools/corpus_connectors/mint_connector_license_sidecar.py",
            "producer_sha256": sha256_file(Path(__file__).resolve(strict=True)),
            "claim_boundary": "DERIVED_CONNECTOR_CUSTODY_ONLY_NO_ACQUISITION_NO_ADMISSION_NO_TRAINING",
        }
        derivation["receipt_sha256"] = sha256_bytes(canonical(derivation))
        derivation_path = staging / DERIVATION_RECEIPT
        derivation_raw = _write_json(derivation_path, derivation)
        os.rename(staging, output)
        published = True

        published_connector = output / CONNECTOR_RECEIPT
        published_derivation = output / DERIVATION_RECEIPT
        if (
            sha256_file(published_connector) != sha256_bytes(connector_raw)
            or sha256_file(published_derivation) != sha256_bytes(derivation_raw)
            or _data_paths(output) != {item["path"] for item in derived_files}
        ):
            raise LicenseSidecarRefusal("published derived custody changed on reopen")
        _, published_files = _reopen_files(json.loads(published_connector.read_bytes()), "derived connector")
        if len(published_files) != len(derived_files):
            raise LicenseSidecarRefusal("published derived file count changed")
        reopened_derivation = json.loads(published_derivation.read_bytes())
        embedded = reopened_derivation.pop("receipt_sha256", None)
        if embedded != sha256_bytes(canonical(reopened_derivation)):
            raise LicenseSidecarRefusal("published derivation receipt self-hash changed")
        return {
            "result": "VERIFIED",
            "custody_path": str(output),
            "connector_receipt_path": str(published_connector),
            "connector_receipt_sha256": sha256_file(published_connector),
            "derivation_receipt_path": str(published_derivation),
            "derivation_receipt_sha256": sha256_file(published_derivation),
            "derivation_receipt_self_sha256": embedded,
        }
    except BaseException:
        if published:
            shutil.rmtree(output, ignore_errors=True)
        else:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-receipt", type=Path, required=True)
    parser.add_argument("--original-receipt-sha256", required=True)
    parser.add_argument("--license-receipt", type=Path, required=True)
    parser.add_argument("--license-receipt-sha256", required=True)
    parser.add_argument("--license-payload", type=Path, required=True)
    parser.add_argument("--license-payload-sha256", required=True)
    parser.add_argument("--expected-spdx", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = mint_license_sidecar(
        original_receipt_path=args.original_receipt,
        original_receipt_sha256=args.original_receipt_sha256,
        license_receipt_path=args.license_receipt,
        license_receipt_sha256=args.license_receipt_sha256,
        license_payload_path=args.license_payload,
        license_payload_sha256=args.license_payload_sha256,
        expected_spdx=args.expected_spdx,
        output=args.output,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
