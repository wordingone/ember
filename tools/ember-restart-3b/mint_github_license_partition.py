#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mint and independently reopen an immutable per-repository GitHub license partition.

This producer consumes only already-frozen github_fetch v1 connector receipts.  It never
contacts GitHub, infers a license, follows an archive link, or normalizes source bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


SCHEMA = "ember-github-license-partition-receipt-v1"
CONNECTOR_EVIDENCE = "GitHub Search API per-repo `license.spdx_id` (LICENSE-file detection), filtered to allow-set"
L3_STATEMENT = "fetch-only; no external model authored/filtered/ranked/scored/selected any token"
LICENSES = frozenset(
    {"Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "MIT", "ODC-By-1.0", "PDDL-1.0"}
)
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
RECEIPT_KEYS = {
    "canonical_url", "connector", "dest_root", "fetched_at", "files", "l3_statement",
    "license", "license_evidence", "notes", "revision", "schema", "sha256_manifest",
    "source", "source_id", "total_bytes",
}
NOTES_KEYS = {"allowed_licenses", "budget_bytes", "candidates_considered", "excluded_for_license", "selected"}
SELECTED_KEYS = {"declared_size_bytes", "full_name", "license", "stars", "url"}
FILE_KEYS = {"path", "bytes", "sha256"}
PARTITION_KEYS = {
    "schema_version", "result", "source_connector_receipt_path", "source_connector_receipt_sha256",
    "connector", "source_id", "connector_slot", "split", "domain", "blob_root", "repositories",
    "partition_root_sha256", "repository_count", "file_count", "blob_bytes", "license_summary",
    "producer_path", "producer_sha256", "source_commit", "model_mediated", "borrowed_labels",
}
REPOSITORY_KEYS = {
    "source_repo", "source_url", "source_revision", "archive_path", "archive_bytes",
    "archive_sha256", "declared_spdx", "license_authority", "root_license_observations",
    "files", "excluded_members", "repository_content_root_sha256",
}
PARTITION_FILE_KEYS = {
    "path", "bytes", "sha256", "blob_path", "source_repo", "source_revision",
    "archive_sha256", "declared_spdx",
}
AUTHORITY_KEYS = {"connector_receipt_sha256", "selected_note_ordinal", "selected_note_sha256", "evidence"}
LICENSE_OBSERVATION_KEYS = {"path", "bytes", "sha256", "authoritative"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned or "source"


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.lstat().st_file_attributes & 0x400)
    except AttributeError:
        return False


def _contained_regular(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative or "\\" in relative:
        raise ValueError("connector file path is not a closed relative POSIX path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("connector file path is not a closed relative POSIX path")
    path = root.joinpath(*pure.parts)
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise ValueError("connector archive is absent or reparsed")
    if path.resolve(strict=True).parent != root.resolve(strict=True):
        raise ValueError("connector archive escapes destination root")
    return path


def _listed_payload_paths(root: Path) -> set[str]:
    found: set[str] = set()
    for child in root.iterdir():
        if child.name in {"_manifests", ".cache", "manifest.jsonl"}:
            continue
        if not child.is_file() or _is_reparse_or_symlink(child):
            raise ValueError("connector destination contains a non-regular payload")
        found.add(child.name)
    return found


def _load_connector(path: Path, expected_sha256: str, expected_topic: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(expected_sha256, str) or HEX64.fullmatch(expected_sha256) is None:
        raise ValueError("connector receipt hash is invalid")
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise ValueError("connector receipt path is absent or reparsed")
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_sha256:
        raise ValueError("connector receipt bytes changed")
    receipt = json.loads(raw)
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
        raise ValueError("connector receipt is not closed")
    if (
        receipt.get("schema") != "corpus-connector-receipt-v1"
        or receipt.get("source") != "github"
        or receipt.get("connector") != {"name": "github_fetch", "version": "v1"}
        or receipt.get("source_id") != f"topic:{expected_topic}"
        or receipt.get("revision") is not None
        or receipt.get("license_evidence") != CONNECTOR_EVIDENCE
        or receipt.get("l3_statement") != L3_STATEMENT
    ):
        raise ValueError("connector receipt identity is invalid")
    try:
        notes = json.loads(receipt["notes"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("connector notes are invalid") from exc
    if not isinstance(notes, dict) or set(notes) != NOTES_KEYS or notes.get("allowed_licenses") != sorted(LICENSES):
        raise ValueError("connector notes are not closed")
    if not isinstance(notes.get("selected"), list) or not notes["selected"]:
        raise ValueError("connector selected repositories are absent")
    return receipt, notes


def _join_selected(receipt: dict[str, Any], notes: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], int]]:
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("connector files are absent")
    by_path: dict[str, dict[str, Any]] = {}
    total = 0
    hashes: list[str] = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != FILE_KEYS:
            raise ValueError("connector file entry is malformed")
        path = entry["path"]
        size = entry["bytes"]
        digest = entry["sha256"]
        if (
            not isinstance(path, str)
            or path in by_path
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or HEX64.fullmatch(digest) is None
        ):
            raise ValueError("connector file entry is malformed")
        by_path[path] = entry
        total += size
        hashes.append(digest)
    if receipt.get("total_bytes") != total:
        raise ValueError("connector total bytes changed")
    if receipt.get("sha256_manifest") != sha256_bytes("\n".join(sorted(hashes)).encode("utf-8")):
        raise ValueError("connector manifest hash changed")

    joined: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    seen_repos: set[str] = set()
    seen_keys: set[str] = set()
    for ordinal, selected in enumerate(notes["selected"]):
        if not isinstance(selected, dict) or set(selected) != SELECTED_KEYS:
            raise ValueError("selected repository entry is malformed")
        repo = selected.get("full_name")
        url = selected.get("url")
        spdx = selected.get("license")
        if (
            not isinstance(repo, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is None
            or repo in seen_repos
            or url != f"https://github.com/{repo}"
        ):
            raise ValueError("selected repository identity is invalid")
        if not isinstance(spdx, str) or spdx not in LICENSES:
            raise ValueError("per-repository SPDX is absent or disallowed")
        key = safe_key(repo) + ".tar.gz"
        if key in seen_keys:
            raise ValueError("selected repository safe-key collision")
        seen_repos.add(repo)
        seen_keys.add(key)
        entry = by_path.get(key)
        if entry is None:
            raise ValueError("selected repository has no exact archive join")
        joined.append((selected, entry, ordinal))
    if seen_keys != set(by_path):
        raise ValueError("connector files and selected repositories are not bijective")
    summary = {item[0]["license"] for item in joined}
    expected_license = next(iter(summary)) if len(summary) == 1 else "mixed (see notes)"
    if receipt.get("license") != expected_license:
        raise ValueError("connector aggregate license does not match partitions")
    return joined


class _HashingReader:
    def __init__(self, raw: BinaryIO):
        self.raw = raw
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.raw.read(size)
        if chunk:
            self.digest.update(chunk)
            self.count += len(chunk)
        return chunk

    def readable(self) -> bool:
        return True


def _member_parts(name: str) -> list[str]:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise ValueError("archive member path is unsafe")
    parts = name.split("/")
    while parts and parts[-1] == "":
        parts.pop()
    if not parts or any(part in {"", ".", ".."} for part in parts) or re.match(r"^[A-Za-z]:", parts[0]):
        raise ValueError("archive member path is unsafe")
    return parts


def _is_root_license(path: str) -> bool:
    if "/" in path:
        return False
    return re.fullmatch(r"(?i)(LICENSE|LICENCE|COPYING|MIT-LICENSE)([-._].*)?", path) is not None


def _write_blob(stream: BinaryIO, incoming: Path, blobs: Path) -> tuple[int, str, str]:
    digest = hashlib.sha256()
    size = 0
    with incoming.open("xb") as target:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        target.flush()
        os.fsync(target.fileno())
    hex_digest = digest.hexdigest()
    relative = PurePosixPath("blobs", "sha256", hex_digest[:2], hex_digest).as_posix()
    final = blobs / hex_digest[:2] / hex_digest
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        if not final.is_file() or sha256_file(final) != hex_digest:
            raise ValueError("staged blob collision")
        incoming.unlink()
    else:
        incoming.rename(final)
    if final.stat().st_size != size or sha256_file(final) != hex_digest:
        raise ValueError("staged blob reopen failed")
    return size, hex_digest, relative


def _archive_partition(
    *, archive_path: Path, entry: dict[str, Any], selected: dict[str, Any], ordinal: int,
    receipt_sha256: str, staging: Path, sequence: int,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    license_observations: list[dict[str, Any]] = []
    seen_members: set[str] = set()
    comments: set[str] = set()
    top_root: str | None = None
    incoming_root = staging / "_incoming"
    incoming_root.mkdir(parents=True, exist_ok=True)
    with archive_path.open("rb") as raw:
        hashing = _HashingReader(raw)
        with tarfile.open(fileobj=hashing, mode="r|gz") as archive:
            for member_index, member in enumerate(archive):
                parts = _member_parts(member.name)
                if top_root is None:
                    top_root = parts[0]
                if parts[0] != top_root:
                    raise ValueError("archive has more than one top-level root")
                comment = member.pax_headers.get("comment")
                if comment is not None:
                    comments.add(comment)
                relative = "/".join(parts[1:])
                if not relative:
                    if not member.isdir():
                        raise ValueError("archive top-level root is not a directory")
                    continue
                if relative in seen_members:
                    raise ValueError("archive has a duplicate member path")
                seen_members.add(relative)
                if member.isfile():
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("archive regular member cannot be read")
                    incoming = incoming_root / f"{sequence}-{member_index}.blob"
                    size, digest, blob_path = _write_blob(source, incoming, staging / "blobs" / "sha256")
                    if size != member.size:
                        raise ValueError("archive member size changed")
                    row = {
                        "path": relative, "bytes": size, "sha256": digest, "blob_path": blob_path,
                        "source_repo": selected["full_name"], "source_revision": "__PENDING__",
                        "archive_sha256": entry["sha256"], "declared_spdx": selected["license"],
                    }
                    files.append(row)
                    if _is_root_license(relative):
                        license_observations.append(
                            {"path": relative, "bytes": size, "sha256": digest, "authoritative": False}
                        )
                elif member.isdir():
                    excluded.append({"path": relative, "type": "directory"})
                elif member.issym():
                    excluded.append({"path": relative, "type": "symlink", "link_target": member.linkname})
                elif member.islnk():
                    excluded.append({"path": relative, "type": "hardlink", "link_target": member.linkname})
                else:
                    excluded.append({"path": relative, "type": "special"})
        for chunk in iter(lambda: hashing.read(1024 * 1024), b""):
            pass
    if hashing.count != entry["bytes"] or hashing.digest.hexdigest() != entry["sha256"]:
        raise ValueError("archive bytes do not match connector receipt")
    if not files:
        raise ValueError("archive has no regular files")
    if len(comments) == 0:
        raise ValueError("archive revision is absent")
    if len(comments) != 1 or HEX40.fullmatch(next(iter(comments))) is None:
        raise ValueError("archive revision is malformed or conflicting")
    revision = next(iter(comments))
    for row in files:
        row["source_revision"] = revision
    files.sort(key=lambda row: row["path"].encode("utf-8"))
    excluded.sort(key=lambda row: (row["path"].encode("utf-8"), row["type"]))
    license_observations.sort(key=lambda row: row["path"].encode("utf-8"))
    repository = {
        "source_repo": selected["full_name"],
        "source_url": selected["url"],
        "source_revision": revision,
        "archive_path": entry["path"],
        "archive_bytes": entry["bytes"],
        "archive_sha256": entry["sha256"],
        "declared_spdx": selected["license"],
        "license_authority": {
            "connector_receipt_sha256": receipt_sha256,
            "selected_note_ordinal": ordinal,
            "selected_note_sha256": sha256_bytes(canonical(selected)),
            "evidence": CONNECTOR_EVIDENCE,
        },
        "root_license_observations": license_observations,
        "files": files,
        "excluded_members": excluded,
    }
    repository["repository_content_root_sha256"] = sha256_bytes(canonical(repository))
    return repository


def _validate_repository(repository: dict[str, Any], *, root: Path, receipt_sha256: str) -> int:
    if not isinstance(repository, dict) or set(repository) != REPOSITORY_KEYS:
        raise ValueError("partition receipt repository is invalid")
    root_digest = repository["repository_content_root_sha256"]
    payload = {key: value for key, value in repository.items() if key != "repository_content_root_sha256"}
    if not isinstance(root_digest, str) or root_digest != sha256_bytes(canonical(payload)):
        raise ValueError("partition receipt repository root changed")
    if (
        not isinstance(repository["source_repo"], str)
        or repository["source_url"] != f"https://github.com/{repository['source_repo']}"
        or not isinstance(repository["source_revision"], str)
        or HEX40.fullmatch(repository["source_revision"]) is None
        or repository["declared_spdx"] not in LICENSES
        or not isinstance(repository["archive_sha256"], str)
        or HEX64.fullmatch(repository["archive_sha256"]) is None
    ):
        raise ValueError("partition receipt repository identity is invalid")
    authority = repository["license_authority"]
    if (
        not isinstance(authority, dict)
        or set(authority) != AUTHORITY_KEYS
        or authority["connector_receipt_sha256"] != receipt_sha256
        or authority["evidence"] != CONNECTOR_EVIDENCE
    ):
        raise ValueError("partition receipt license authority is invalid")
    for observation in repository["root_license_observations"]:
        if not isinstance(observation, dict) or set(observation) != LICENSE_OBSERVATION_KEYS or observation["authoritative"] is not False:
            raise ValueError("partition receipt license observation is invalid")
    previous: bytes | None = None
    blob_bytes = 0
    for row in repository["files"]:
        if not isinstance(row, dict) or set(row) != PARTITION_FILE_KEYS:
            raise ValueError("partition receipt file is invalid")
        key = row["path"].encode("utf-8")
        if previous is not None and key <= previous:
            raise ValueError("partition receipt files are not strictly ordered")
        previous = key
        if (
            row["source_repo"] != repository["source_repo"]
            or row["source_revision"] != repository["source_revision"]
            or row["archive_sha256"] != repository["archive_sha256"]
            or row["declared_spdx"] != repository["declared_spdx"]
            or not isinstance(row["sha256"], str)
            or HEX64.fullmatch(row["sha256"]) is None
            or row["blob_path"] != f"blobs/sha256/{row['sha256'][:2]}/{row['sha256']}"
        ):
            raise ValueError("partition receipt file join is invalid")
        blob = root.joinpath(*PurePosixPath(row["blob_path"]).parts)
        if not blob.is_file() or _is_reparse_or_symlink(blob) or blob.stat().st_size != row["bytes"] or sha256_file(blob) != row["sha256"]:
            raise ValueError("partition receipt blob changed")
        blob_bytes += row["bytes"]
    return blob_bytes


def validate_partition_receipt(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise ValueError("partition receipt path is invalid")
    receipt = json.loads(path.read_bytes())
    if not isinstance(receipt, dict) or set(receipt) != PARTITION_KEYS or receipt.get("schema_version") != SCHEMA or receipt.get("result") != "VERIFIED":
        raise ValueError("partition receipt is invalid")
    source_sha = receipt["source_connector_receipt_sha256"]
    if not isinstance(source_sha, str) or HEX64.fullmatch(source_sha) is None:
        raise ValueError("partition receipt source digest is invalid")
    source_path = Path(receipt["source_connector_receipt_path"])
    if not source_path.is_file() or sha256_file(source_path) != source_sha:
        raise ValueError("partition receipt source bytes changed")
    root = path.parent
    repositories = receipt["repositories"]
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("partition receipt repositories are absent")
    previous: str | None = None
    blob_bytes = 0
    file_count = 0
    for repository in repositories:
        name = repository.get("source_repo") if isinstance(repository, dict) else None
        if not isinstance(name, str) or (previous is not None and name <= previous):
            raise ValueError("partition receipt repositories are not strictly ordered")
        previous = name
        blob_bytes += _validate_repository(repository, root=root, receipt_sha256=source_sha)
        file_count += len(repository["files"])
    if (
        receipt["repository_count"] != len(repositories)
        or receipt["file_count"] != file_count
        or receipt["blob_bytes"] != blob_bytes
        or receipt["license_summary"] != sorted({row["declared_spdx"] for row in repositories})
        or receipt["partition_root_sha256"] != sha256_bytes(canonical(repositories))
        or receipt["model_mediated"] is not False
        or receipt["borrowed_labels"] is not False
    ):
        raise ValueError("partition receipt aggregate changed")
    return receipt


def mint_partition(
    *, connector_receipt_path: Path, connector_receipt_sha256: str, output: Path,
    source_commit: str, source_id: str, connector_slot: str, split: str, domain: str,
    expected_topic: str,
) -> dict[str, Any]:
    connector_receipt_path = Path(connector_receipt_path).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if not isinstance(connector_receipt_sha256, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", connector_receipt_sha256) is None:
        raise ValueError("connector receipt hash is invalid")
    connector_receipt_sha256 = connector_receipt_sha256.lower()
    if HEX40.fullmatch(source_commit) is None or split not in {"train", "heldout"}:
        raise ValueError("partition plan identity is invalid")
    receipt, notes = _load_connector(connector_receipt_path, connector_receipt_sha256, expected_topic)
    joined = _join_selected(receipt, notes)
    custody = Path(receipt["dest_root"]).resolve(strict=True)
    if not custody.is_dir() or _is_reparse_or_symlink(custody):
        raise ValueError("connector destination root is invalid")
    if _listed_payload_paths(custody) != {entry["path"] for _, entry, _ in joined}:
        raise ValueError("connector destination has extra or missing archives")
    output.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_symlink(output.parent):
        raise ValueError("partition output parent is reparsed")
    staging = output.parent / f".{output.name}.staging-{secrets.token_hex(8)}"
    staging.mkdir()
    try:
        repositories = []
        for sequence, (selected, entry, ordinal) in enumerate(joined):
            archive_path = _contained_regular(custody, entry["path"])
            try:
                repositories.append(
                    _archive_partition(
                        archive_path=archive_path, entry=entry, selected=selected, ordinal=ordinal,
                        receipt_sha256=connector_receipt_sha256, staging=staging, sequence=sequence,
                    )
                )
            except tarfile.TarError as exc:
                raise ValueError("archive bytes are not a valid gzip tar stream") from exc
        repositories.sort(key=lambda row: row["source_repo"])
        receipt_out = {
            "schema_version": SCHEMA,
            "result": "VERIFIED",
            "source_connector_receipt_path": str(connector_receipt_path),
            "source_connector_receipt_sha256": connector_receipt_sha256,
            "connector": {"name": "github_fetch", "version": "v1"},
            "source_id": source_id,
            "connector_slot": connector_slot,
            "split": split,
            "domain": domain,
            "blob_root": "blobs/sha256",
            "repositories": repositories,
            "partition_root_sha256": sha256_bytes(canonical(repositories)),
            "repository_count": len(repositories),
            "file_count": sum(len(row["files"]) for row in repositories),
            "blob_bytes": sum(item["bytes"] for row in repositories for item in row["files"]),
            "license_summary": sorted({row["declared_spdx"] for row in repositories}),
            "producer_path": "tools/ember-restart-3b/mint_github_license_partition.py",
            "producer_sha256": sha256_file(Path(__file__)),
            "source_commit": source_commit,
            "model_mediated": False,
            "borrowed_labels": False,
        }
        receipt_path = staging / "partition-receipt.json"
        receipt_path.write_bytes(canonical(receipt_out) + b"\n")
        validate_partition_receipt(receipt_path)
        if output.exists():
            raise FileExistsError(f"output raced into existence: {output}")
        staging.rename(output)
        return validate_partition_receipt(output / "partition-receipt.json")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connector-receipt", type=Path, required=True)
    parser.add_argument("--connector-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--connector-slot", required=True)
    parser.add_argument("--split", choices=("train", "heldout"), required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--expected-topic", required=True)
    args = parser.parse_args()
    receipt = mint_partition(
        connector_receipt_path=args.connector_receipt,
        connector_receipt_sha256=args.connector_receipt_sha256,
        output=args.output,
        source_commit=args.source_commit,
        source_id=args.source_id,
        connector_slot=args.connector_slot,
        split=args.split,
        domain=args.domain,
        expected_topic=args.expected_topic,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
