#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""bulk_fetch.py -- resumable, chunked HTTP(S) bulk transport CLI (issue
#1440) for named-source dumps that exceed http_fetch.py's 512 MiB
single-shot cap (Wikipedia XML dumps, PMC OA packages, Stack Exchange 7z
dumps, USPTO bulk grants, and similar).

    bulk_fetch.py URL --budget-bytes N [--chunk-size-bytes N]
                  [--disk-margin-bytes N] [--sha256 EXPECTED]
                  [--license STR --license-evidence STR]
                  [--dest DIR] [--allow-unverified-license] [--timeout N]

Stdlib-only (`urllib.request` via chunked_download.py). `--budget-bytes` is
required -- the caller always states the total byte budget up front; the
fetch refuses to start (or continue, on resume) if the remote size would
exceed it, and the budget declared here is entirely independent of
`receipt.py`'s 512 MiB `MAX_DOWNLOAD_BYTES` (that cap is untouched and still
governs the ordinary single-fetch connectors).

Resumability is automatic: re-running the identical command (same URL, same
--dest, same --chunk-size-bytes, same --budget-bytes) against a destination
that has an in-progress `<file>.bulkstate.json` sidecar resumes from the
last durably-committed chunk rather than refetching it. See
chunked_download.py for the full resume/fail-closed contract.

License is a human/lead judgment about the named source, exactly like
http_fetch.py: `--license`/`--license-evidence` must be supplied together or
not at all (absent = UNVERIFIED, gated by --allow-unverified-license).

`--transport {range,streaming}` (fast-follow, default `range`, byte-identical
to prior behavior when omitted): `range` is the resumable Range-chunked
engine above; `streaming` (chunked_download.fetch_streaming) is a sequential
GET with incremental hashing, for sources that do not honour HTTP Range at
all (e.g. Dolma's actual host) -- Range is a resume convenience, never a
transport requirement. `streaming` does not resume; every other fail-closed
contract (budget enforcement, disk margin, whole-file --sha256, size-
mismatch-at-completion) is identical between the two transports.
`--chunk-size-bytes` is shared between them: for `range` it is the Range
request size; for `streaming` it is the per-`read()` I/O buffer size (there
is no Range chunk to size).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path
from typing import List, Optional

# Direct execution appends the repository root so the package import resolves
# without publishing connector-local bare names or shadowing earlier imports.
_REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

import chunked_download as bulk  # noqa: E402
from tools.corpus_connectors import receipt as rcpt  # noqa: E402

CONNECTOR_NAME = "bulk_fetch"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Resumable chunked-Range HTTP(S) fetch for bulk sources, with an explicit byte budget."
    )
    p.add_argument("url")
    p.add_argument(
        "--budget-bytes", type=int, required=True, metavar="N",
        help="declared total byte budget for this transfer; refuses to start or continue "
             "if the remote size would exceed it (independent of the 512 MiB single-fetch cap)",
    )
    p.add_argument("--chunk-size-bytes", type=int, default=bulk.DEFAULT_CHUNK_SIZE, metavar="N")
    p.add_argument("--disk-margin-bytes", type=int, default=bulk.DEFAULT_DISK_MARGIN_BYTES, metavar="N")
    p.add_argument("--max-retries", type=int, default=bulk.DEFAULT_MAX_RETRIES, metavar="N")
    p.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=bulk.DEFAULT_RETRY_BACKOFF_SECONDS,
        metavar="N",
    )
    p.add_argument(
        "--transport", choices=["range", "streaming"], default="range",
        help="range (default, resumable HTTP Range chunks) or streaming (sequential GET, "
             "for sources that do not honour Range at all; not resumable)",
    )
    p.add_argument("--sha256", dest="expected_sha256", default=None, metavar="EXPECTED")
    p.add_argument("--license", dest="license_str", default=None, metavar="STR")
    p.add_argument("--license-evidence", dest="license_evidence", default=None, metavar="STR")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/bulk/<key>)")
    p.add_argument("--allow-unverified-license", action="store_true")
    p.add_argument("--timeout", type=int, default=60)
    return p


def _dest_filename(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = Path(path).name
    return name or "download.bin"


def _write_chunk_manifest(dest_root: Path, url: str, budget_bytes: int, result: "bulk.BulkFetchResult") -> Path:
    manifests_dir = dest_root / "_manifests"
    try:
        manifests_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise rcpt.ReceiptWriteError(f"could not create manifests dir: {exc}") from exc

    ts = rcpt.utc_stamp_compact()
    key = rcpt.safe_key(url)
    out_path = manifests_dir / f"{ts}-{key}.chunks.json"
    if out_path.exists():
        raise rcpt.DestCollisionError(f"chunk manifest already exists at {out_path}")

    tmp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(result.chunk_manifest_dict(url, budget_bytes), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(out_path)
    except OSError as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise rcpt.ReceiptWriteError(f"could not write chunk manifest json: {exc}") from exc
    return out_path


def fetch(args: argparse.Namespace, opener=None, disk_usage_fn=None) -> Path:
    if (args.license_str is None) != (args.license_evidence is None):
        raise rcpt.BlockedError("--license and --license-evidence must be supplied together")

    license_str = args.license_str if args.license_str else rcpt.UNVERIFIED
    license_evidence = (
        args.license_evidence if args.license_evidence else "no --license/--license-evidence supplied by caller"
    )
    rcpt.gate_license(license_str, args.allow_unverified_license)

    key = rcpt.safe_key(urllib.parse.urlparse(args.url).netloc + "-" + _dest_filename(args.url))
    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "bulk" / key
    dest_root.mkdir(parents=True, exist_ok=True)
    dest_file = dest_root / _dest_filename(args.url)

    transport = getattr(args, "transport", "range")
    if transport == "streaming":
        result = bulk.fetch_streaming(
            args.url,
            dest_file,
            budget_bytes=args.budget_bytes,
            read_chunk_bytes=args.chunk_size_bytes,
            disk_margin_bytes=args.disk_margin_bytes,
            expected_sha256=args.expected_sha256,
            timeout=args.timeout,
            opener=opener,
            disk_usage_fn=disk_usage_fn,
        )
    else:
        result = bulk.fetch_chunked(
            args.url,
            dest_file,
            budget_bytes=args.budget_bytes,
            chunk_size=args.chunk_size_bytes,
            disk_margin_bytes=args.disk_margin_bytes,
            expected_sha256=args.expected_sha256,
            timeout=args.timeout,
            opener=opener,
            disk_usage_fn=disk_usage_fn,
            max_retries=getattr(args, "max_retries", bulk.DEFAULT_MAX_RETRIES),
            backoff_base_seconds=getattr(
                args, "retry_backoff_seconds", bulk.DEFAULT_RETRY_BACKOFF_SECONDS
            ),
        )

    downloaded_paths = [dest_file]

    # The chunk manifest is itself a file this fetch attempt wrote -- if writing it
    # fails, treat that the same as any other receipt-write failure: fail-closed,
    # clean up the (otherwise unreceipted) downloaded file before re-raising.
    try:
        chunk_manifest_path = _write_chunk_manifest(dest_root, args.url, args.budget_bytes, result)
    except rcpt.BlockedError:
        for p in downloaded_paths:
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        raise
    downloaded_paths.append(chunk_manifest_path)

    files = rcpt.build_file_entries(dest_root, [dest_file.relative_to(dest_root)])

    receipt = rcpt.Receipt(
        source="http-bulk",
        source_id=args.url,
        canonical_url=args.url,
        license=license_str,
        license_evidence=license_evidence,
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=(
            (
                f"resumable chunked-bulk transfer; {len(result.chunks)} chunks of "
                f"{result.chunk_size} bytes; resumed={'yes' if result.resumed else 'no'}; "
                f"retry_attempts={result.retry_attempts}; "
                if transport == "range"
                else f"streaming (non-Range) sequential transfer; {result.chunk_size}-byte read buffer; "
            )
            + f"budget_bytes={args.budget_bytes}; "
            f"chunk_manifest={chunk_manifest_path.relative_to(dest_root).as_posix()}; "
            f"sha256_verified={'yes' if args.expected_sha256 else 'no'}"
        ),
        retry_attempts=result.retry_attempts,
        retry_events=result.retry_events,
    )
    # commit_receipt's own fail-closed cleanup covers both dest_file and the chunk
    # manifest (both are in downloaded_paths) if the receipt write itself fails.
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
