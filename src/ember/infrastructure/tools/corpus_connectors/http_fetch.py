#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""http_fetch.py -- plain HTTP(S) connector CLI for named-source pulls
(OpenStax, archive.org dumps, NIST, and similar single-URL textbook/dump
sources that have no dedicated API).

    http_fetch.py URL [--sha256 EXPECTED] [--license STR --license-evidence STR]
                  [--dest DIR] [--allow-unverified-license]

Stdlib-only (`urllib.request`). License is a human/lead judgment about the
named source -- this tool never guesses it from the URL or response headers.
`--license` and `--license-evidence` must be supplied together (design
choice, see README "Implementation notes"); if omitted, license is recorded
UNVERIFIED and gated by the same --allow-unverified-license flag every other
connector uses, rather than a one-off required-argument shape.
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path
from typing import List, Optional

# Direct execution appends the repository root so the package import resolves
# without publishing connector-local bare names or shadowing earlier imports.
_REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from tools.corpus_connectors import receipt as rcpt  # noqa: E402

CONNECTOR_NAME = "http_fetch"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch a single URL with an L4 receipt.")
    p.add_argument("url")
    p.add_argument("--sha256", dest="expected_sha256", default=None, metavar="EXPECTED")
    p.add_argument("--license", dest="license_str", default=None, metavar="STR")
    p.add_argument("--license-evidence", dest="license_evidence", default=None, metavar="STR")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/http/<key>)")
    p.add_argument("--allow-unverified-license", action="store_true")
    p.add_argument("--allow-content-mismatch", action="store_true")
    return p


def _dest_filename(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = Path(path).name
    return name or "download.bin"


def fetch(args: argparse.Namespace, opener=None) -> Path:
    if (args.license_str is None) != (args.license_evidence is None):
        raise rcpt.BlockedError("--license and --license-evidence must be supplied together")

    license_str = args.license_str if args.license_str else rcpt.UNVERIFIED
    license_evidence = (
        args.license_evidence if args.license_evidence else "no --license/--license-evidence supplied by caller"
    )
    rcpt.gate_license(license_str, args.allow_unverified_license)

    key = rcpt.safe_key(urllib.parse.urlparse(args.url).netloc + "-" + _dest_filename(args.url))
    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "http" / key
    dest_root.mkdir(parents=True, exist_ok=True)
    dest_file = dest_root / _dest_filename(args.url)

    size, digest = rcpt.download_url(args.url, dest_file, expected_sha256=args.expected_sha256, opener=opener)

    with dest_file.open("rb") as fh:
        head = fh.read(1024)
    try:
        rcpt.gate_content_type(args.url, head, args.allow_content_mismatch)
    except rcpt.ContentTypeMismatchError:
        dest_file.unlink(missing_ok=True)
        raise

    downloaded_paths = [dest_file]

    files = rcpt.build_file_entries(dest_root, [dest_file.relative_to(dest_root)])

    receipt = rcpt.Receipt(
        source="http",
        source_id=args.url,
        canonical_url=args.url,
        license=license_str,
        license_evidence=license_evidence,
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=f"sha256_verified={'yes' if args.expected_sha256 else 'no'}",
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
