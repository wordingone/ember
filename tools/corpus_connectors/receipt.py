"""receipt.py -- shared receipt core for the corpus connector CLIs.

Every connector (hf_fetch.py, arxiv_fetch.py, openreview_fetch.py, kaggle_fetch.py,
http_fetch.py) builds a `Receipt`, hands it plus the list of files it wrote to
`commit_receipt()`, and prints exactly one of:

    RECEIPT <path-to-manifest-json>          (success)
    BLOCKED <reason>                         (refusal; nonzero exit)

Fail-closed: a fetch whose receipt write fails is a FAILED fetch. `commit_receipt()`
deletes any files the caller downloaded for this attempt before re-raising, so a
receipt-write failure never leaves an unreceipted file behind.

Compatibility shim (coordinator requirement, 2026-07-09): the pre-existing
`<domain>/manifest.jsonl` rows under the local data root use one flat schema per
file:

    {"source_url", "sha256", "bytes", "license", "human_provenance_basis",
     "fetched_ts", "selection_rule"}

`to_manifest_row()` maps a Receipt onto that template (one legacy-shaped row per
file in `receipt.files`), so a new connector pull normalizes onto the existing
template rather than introducing a parallel schema. Field mapping:

    source_url             <- receipt.canonical_url
    sha256 / bytes         <- per-file values
    license                <- receipt.license
    human_provenance_basis <- receipt.notes if set, else a machine-fetched default
                              that points at license_evidence for the human to audit
    fetched_ts             <- receipt.fetched_at
    selection_rule         <- receipt.source_id (the canonical id used to select
                              this acquisition)

`append_manifest_rows()` appends those rows to `<dest_root>/manifest.jsonl`,
alongside the connector's own `<dest_root>/_manifests/<ts>-<key>.json` receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

SCHEMA_NAME = "corpus-connector-receipt-v1"
L3_STATEMENT = "fetch-only; no external model authored/filtered/ranked/scored/selected any token"
UNVERIFIED = "UNVERIFIED"


# ---------------------------------------------------------------------------
# Errors -- every one of these is caught by run_cli() and printed as a single
# `BLOCKED <reason>` line with a nonzero exit. ReceiptWriteError is a BlockedError
# too: a receipt that can't be written is defined as a failed fetch (fail-closed),
# not a partial success.
# ---------------------------------------------------------------------------
class BlockedError(Exception):
    """Base class for any refusal condition a connector CLI can hit."""


class DestCollisionError(BlockedError):
    pass


class HashMismatchError(BlockedError):
    pass


class MissingCredentialsError(BlockedError):
    pass


class UnverifiedLicenseError(BlockedError):
    pass


class ReceiptWriteError(BlockedError):
    pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class FileEntry:
    path: str  # relative to dest_root, forward-slash separated
    bytes: int
    sha256: str

    def to_dict(self) -> dict:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass
class ConnectorInfo:
    name: str
    version: str = "v1"

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version}


@dataclass
class Receipt:
    source: str
    source_id: str
    canonical_url: str
    license: str
    license_evidence: str
    revision: Optional[str]
    files: List[FileEntry]
    fetched_at: str
    connector: ConnectorInfo
    dest_root: str
    notes: str = ""
    schema: str = SCHEMA_NAME
    l3_statement: str = L3_STATEMENT

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes for f in self.files)

    @property
    def sha256_manifest(self) -> str:
        return sha256_of_manifest([f.sha256 for f in self.files])

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source": self.source,
            "source_id": self.source_id,
            "canonical_url": self.canonical_url,
            "license": self.license,
            "license_evidence": self.license_evidence,
            "revision": self.revision,
            "files": [f.to_dict() for f in self.files],
            "total_bytes": self.total_bytes,
            "sha256_manifest": self.sha256_manifest,
            "fetched_at": self.fetched_at,
            "connector": self.connector.to_dict(),
            "l3_statement": self.l3_statement,
            "dest_root": self.dest_root,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_manifest(hashes: Sequence[str]) -> str:
    """Hash over sorted file hashes, per spec sha256_manifest definition."""
    joined = "\n".join(sorted(hashes))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Time / naming helpers
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_key(s: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")
    return cleaned or "source"


# ---------------------------------------------------------------------------
# License / credential gates
# ---------------------------------------------------------------------------
def gate_license(license_str: str, allow_unverified: bool) -> None:
    """Raise UnverifiedLicenseError unless license_str is resolved or the caller
    explicitly passed --allow-unverified-license. Never guesses a license."""
    if license_str == UNVERIFIED and not allow_unverified:
        raise UnverifiedLicenseError(
            "license UNVERIFIED; pass --allow-unverified-license to proceed "
            "(tranche will be recorded UNVERIFIED and excluded from training "
            "use until resolved)"
        )


def kaggle_credentials_present(env: Optional[dict] = None) -> bool:
    env = env if env is not None else os.environ
    if env.get("KAGGLE_USERNAME") and env.get("KAGGLE_KEY"):
        return True
    cfg_dir = env.get("KAGGLE_CONFIG_DIR") or str(Path.home() / ".kaggle")
    return (Path(cfg_dir) / "kaggle.json").is_file()


# ---------------------------------------------------------------------------
# Filesystem-level dest checks
# ---------------------------------------------------------------------------
def check_no_collision(path: Path) -> None:
    if path.exists():
        raise DestCollisionError(f"destination already exists: {path}")


def relative_files_under(root: Path, exclude_dirnames: Iterable[str] = ("_manifests",)) -> List[Path]:
    """Enumerate files under root (recursively), excluding named directories and
    the compatibility manifest.jsonl / temp files, returned relative to root."""
    exclude = set(exclude_dirnames)
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for name in filenames:
            if name in ("manifest.jsonl",) or name.endswith(".partial") or name.endswith(".tmp"):
                continue
            full = Path(dirpath) / name
            out.append(full.relative_to(root))
    return out


def build_file_entries(root: Path, paths: Iterable[Path]) -> List[FileEntry]:
    entries = []
    for rel in paths:
        full = root / rel
        entries.append(
            FileEntry(
                path=rel.as_posix(),
                bytes=full.stat().st_size,
                sha256=sha256_file(full),
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Download helper (stdlib-only; used directly by http_fetch.py and by any
# connector fetching individual files over plain HTTP(S), e.g. arXiv/OpenReview
# PDFs). Downloads to a `.partial` sibling first; verifies hash if given;
# never leaves a partial file behind on failure or mismatch.
# ---------------------------------------------------------------------------
def download_url(
    url: str,
    dest_path: Path,
    expected_sha256: Optional[str] = None,
    timeout: int = 60,
    headers: Optional[dict] = None,
    opener: Optional[Callable] = None,
) -> Tuple[int, str]:
    check_no_collision(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".partial")
    req_headers = {"User-Agent": "ember-corpus-connector/1"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, headers=req_headers)
    urlopen = opener or urllib.request.urlopen
    try:
        with urlopen(request, timeout=timeout) as resp, tmp_path.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    digest = sha256_file(tmp_path)
    size = tmp_path.stat().st_size
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        tmp_path.unlink()
        raise HashMismatchError(f"expected {expected_sha256}, got {digest} for {url}")
    tmp_path.replace(dest_path)
    return size, digest


# ---------------------------------------------------------------------------
# Manifest compatibility shim
# ---------------------------------------------------------------------------
def to_manifest_row(receipt: Receipt) -> List[dict]:
    default_provenance = (
        f"machine-fetched via {receipt.connector.name}; provenance basis not "
        f"independently asserted by the connector (see license_evidence: "
        f"{receipt.license_evidence})"
    )
    rows = []
    for f in receipt.files:
        rows.append(
            {
                "source_url": receipt.canonical_url,
                "sha256": f.sha256,
                "bytes": f.bytes,
                "license": receipt.license,
                "human_provenance_basis": receipt.notes or default_provenance,
                "fetched_ts": receipt.fetched_at,
                "selection_rule": receipt.source_id,
            }
        )
    return rows


def append_manifest_rows(dest_root: Path, rows: List[dict]) -> Path:
    manifest_path = dest_root / "manifest.jsonl"
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        return manifest_path
    except OSError as exc:
        raise ReceiptWriteError(f"could not append manifest.jsonl rows: {exc}") from exc


# ---------------------------------------------------------------------------
# Receipt write + orchestration
# ---------------------------------------------------------------------------
def write_receipt(receipt: Receipt, dest_root: Path) -> Path:
    manifests_dir = dest_root / "_manifests"
    try:
        manifests_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReceiptWriteError(f"could not create manifests dir: {exc}") from exc

    ts = utc_stamp_compact()
    key = safe_key(receipt.source_id)
    out_path = manifests_dir / f"{ts}-{key}.json"
    if out_path.exists():
        raise DestCollisionError(f"manifest already exists at {out_path}")

    tmp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        tmp_path.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(out_path)
    except OSError as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise ReceiptWriteError(f"could not write manifest json: {exc}") from exc
    return out_path


def _cleanup_partial(paths: Iterable[Path]) -> None:
    for p in paths:
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass  # best-effort cleanup; never mask the original failure


def commit_receipt(receipt: Receipt, dest_root: Path, downloaded_paths: Sequence[Path]) -> Path:
    """Write the connector receipt JSON + append compatibility manifest.jsonl
    rows. On ANY failure in either step, best-effort delete the files this
    fetch attempt wrote and re-raise -- a fetch whose receipt write fails is a
    failed fetch, never a partial success."""
    try:
        receipt_path = write_receipt(receipt, dest_root)
        rows = to_manifest_row(receipt)
        append_manifest_rows(dest_root, rows)
        return receipt_path
    except BlockedError:
        _cleanup_partial(downloaded_paths)
        raise


# ---------------------------------------------------------------------------
# CLI plumbing shared by every connector
# ---------------------------------------------------------------------------
def run_cli(fn: Callable[[], Path]) -> int:
    """fn() must return the receipt Path on success or raise BlockedError (or
    any Exception, treated as fail-closed) on refusal. Prints exactly one
    `RECEIPT <path>` or `BLOCKED <reason>` line, per the shared CLI contract."""
    try:
        receipt_path = fn()
    except BlockedError as exc:
        print(f"BLOCKED {exc}")
        return 1
    except Exception as exc:  # last-resort fail-closed: never a bare traceback
        print(f"BLOCKED unexpected error: {exc}")
        return 1
    print(f"RECEIPT {receipt_path}")
    return 0
