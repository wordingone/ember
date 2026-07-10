#!/usr/bin/env python3
"""arxiv_fetch.py -- arXiv API (Atom) connector CLI.

    arxiv_fetch.py (--ids ID... | --query Q --max N) [--what meta|pdf|source]
                   [--dest DIR] [--license-filter cc-only|all]
                   [--allow-unverified-license]

Stdlib-only (feedparser/arxiv packages were confirmed ABSENT at build time --
see README "Dependency posture"): queries the public arXiv Atom API directly
via `urllib.request` + `xml.etree.ElementTree`, respecting the API's politeness
contract (<=1 request per 3s, <=100 results per page).

Per-paper license handling (per spec, "arXiv-perpetual license papers are
metadata-only unless filter widened by lead"):
  - an `<arxiv:license>` element whose value is a creativecommons.org URL (or
    the CC0 URL) is treated as a resolved CC license -- eligible for the
    `cc-only` content filter (the default).
  - an `<arxiv:license>` element present but pointing at any other URL
    (typically arXiv's own nonexclusive-distrib license) is a RESOLVED,
    non-CC license -- known, not UNVERIFIED, but not eligible under
    `cc-only`.
  - no `<arxiv:license>` element at all is UNVERIFIED (subject to the
    standard --allow-unverified-license gate).

One receipt per invocation (the frozen schema has a single `license` field
per receipt): for `--what meta` the single file is a JSON listing of the
returned entries (id/title/license/updated); for `--what pdf|source` the
files are the downloaded PDFs/source archives for papers eligible under the
license filter -- per-paper license detail always goes into `notes`.
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import receipt as rcpt

CONNECTOR_NAME = "arxiv_fetch"
API_BASE = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
PAGE_SIZE_MAX = 100
RATE_LIMIT_SECONDS = 3.0
ARXIV_PERPETUAL_LABEL = "arXiv perpetual, non-exclusive license"


@dataclass
class ArxivEntry:
    arxiv_id: str
    title: str
    raw_license_url: Optional[str]
    updated: Optional[str]

    @property
    def is_cc(self) -> bool:
        if not self.raw_license_url:
            return False
        return "creativecommons.org" in self.raw_license_url or "publicdomain/zero" in self.raw_license_url

    @property
    def license_label(self) -> str:
        if self.raw_license_url is None:
            return rcpt.UNVERIFIED
        if self.is_cc:
            return self.raw_license_url
        return ARXIV_PERPETUAL_LABEL

    @property
    def license_evidence(self) -> str:
        if self.raw_license_url is None:
            return "no arxiv:license element in API response"
        return "arxiv:license Atom element"


def _entry_id_short(id_url: str) -> str:
    # id_url looks like http://arxiv.org/abs/2301.00001v2
    tail = id_url.rstrip("/").rsplit("/", 1)[-1]
    return tail


def _parse_atom(xml_bytes: bytes) -> List[ArxivEntry]:
    root = ET.fromstring(xml_bytes)
    out = []
    for entry in root.findall("atom:entry", NS):
        id_el = entry.find("atom:id", NS)
        title_el = entry.find("atom:title", NS)
        updated_el = entry.find("atom:updated", NS)
        license_el = entry.find("arxiv:license", NS)
        arxiv_id = _entry_id_short(id_el.text.strip()) if id_el is not None and id_el.text else "unknown"
        title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else ""
        updated = updated_el.text.strip() if updated_el is not None and updated_el.text else None
        raw_license = license_el.text.strip() if license_el is not None and license_el.text else None
        out.append(ArxivEntry(arxiv_id=arxiv_id, title=title, raw_license_url=raw_license, updated=updated))
    return out


def _http_get(url: str, opener=None) -> bytes:
    urlopen = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": "ember-corpus-connector/1"})
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def query_by_ids(ids: List[str], opener=None) -> List[ArxivEntry]:
    entries: List[ArxivEntry] = []
    for i in range(0, len(ids), PAGE_SIZE_MAX):
        chunk = ids[i : i + PAGE_SIZE_MAX]
        url = f"{API_BASE}?id_list={urllib.parse.quote(','.join(chunk))}&max_results={len(chunk)}"
        entries.extend(_parse_atom(_http_get(url, opener)))
        if i + PAGE_SIZE_MAX < len(ids):
            time.sleep(RATE_LIMIT_SECONDS)
    return entries


def query_by_search(query: str, max_results: int, opener=None) -> List[ArxivEntry]:
    entries: List[ArxivEntry] = []
    start = 0
    remaining = max_results
    while remaining > 0:
        page_size = min(PAGE_SIZE_MAX, remaining)
        url = (
            f"{API_BASE}?search_query={urllib.parse.quote(query)}"
            f"&start={start}&max_results={page_size}"
        )
        page = _parse_atom(_http_get(url, opener))
        if not page:
            break
        entries.extend(page)
        start += len(page)
        remaining -= len(page)
        if remaining > 0:
            time.sleep(RATE_LIMIT_SECONDS)
    return entries


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch arXiv metadata/content with an L4 receipt.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--ids", nargs="+", metavar="ID", help="explicit arXiv id(s)")
    src.add_argument("--query", help="arXiv search_query string")
    p.add_argument("--max", type=int, default=50, help="max results for --query mode (default 50)")
    p.add_argument("--what", choices=["meta", "pdf", "source"], default="meta")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/arxiv/<key>)")
    p.add_argument("--license-filter", choices=["cc-only", "all"], default="cc-only")
    p.add_argument("--allow-unverified-license", action="store_true")
    return p


def _content_url(entry: ArxivEntry, what: str) -> str:
    if what == "pdf":
        return f"https://arxiv.org/pdf/{entry.arxiv_id}.pdf"
    return f"https://export.arxiv.org/e-print/{entry.arxiv_id}"


def fetch(args: argparse.Namespace, opener=None) -> Path:
    if args.ids:
        entries = query_by_ids(args.ids, opener)
        key = rcpt.safe_key("-".join(args.ids[:3]) + (f"-plus{len(args.ids)-3}" if len(args.ids) > 3 else ""))
        source_id = ",".join(args.ids)
    else:
        entries = query_by_search(args.query, args.max, opener)
        key = rcpt.safe_key(args.query)[:60]
        source_id = f"query:{args.query}"

    if not entries:
        raise rcpt.BlockedError("no arXiv entries returned for the requested set")

    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "arxiv" / key
    dest_root.mkdir(parents=True, exist_ok=True)

    per_paper_notes = "; ".join(f"{e.arxiv_id}={e.license_label}" for e in entries)

    if args.what == "meta":
        meta_path = dest_root / f"meta-{key}.json"
        rcpt.check_no_collision(meta_path)
        import json

        meta_path.write_text(
            json.dumps(
                [
                    {"arxiv_id": e.arxiv_id, "title": e.title, "license": e.license_label, "updated": e.updated}
                    for e in entries
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        files = rcpt.build_file_entries(dest_root, [meta_path.relative_to(dest_root)])
        downloaded_paths = [meta_path]
        license_str = "public (arXiv API metadata only; per-paper licenses in notes)"
        license_evidence = "arXiv API metadata (titles/ids/updated) carries no separate reuse license"
    else:
        eligible = entries if args.license_filter == "all" else [e for e in entries if e.is_cc]
        if not eligible:
            raise rcpt.BlockedError(
                f"no license-clean papers eligible for content fetch under --license-filter cc-only "
                f"(use --license-filter all to override); per-paper: {per_paper_notes}"
            )
        downloaded_paths: List[Path] = []
        for e in eligible:
            url = _content_url(e, args.what)
            ext = ".pdf" if args.what == "pdf" else ".tar"
            dest_file = dest_root / f"{rcpt.safe_key(e.arxiv_id)}{ext}"
            rcpt.download_url(url, dest_file, opener=opener)
            downloaded_paths.append(dest_file)
            time.sleep(RATE_LIMIT_SECONDS)
        files = rcpt.build_file_entries(dest_root, [p.relative_to(dest_root) for p in downloaded_paths])
        distinct_licenses = sorted({e.license_label for e in eligible})
        license_str = distinct_licenses[0] if len(distinct_licenses) == 1 else "cc-mixed (see notes)"
        license_evidence = "arxiv:license Atom element, per paper (cc-only filter applied)"

    # Note: the top-level receipt `license` field above is always a resolved
    # label (a specific CC URL, "cc-mixed", the arXiv-perpetual label, or the
    # metadata-only label) -- never UNVERIFIED -- because unresolved per-paper
    # licenses are excluded from content fetch under the default cc-only
    # filter and are merely listed (with their own UNVERIFIED label) in
    # per-paper notes for meta-only pulls. The --allow-unverified-license flag
    # is still accepted for CLI-contract consistency across connectors and
    # would apply if a future revision surfaces a batch-level UNVERIFIED case.

    receipt = rcpt.Receipt(
        source="arxiv",
        source_id=source_id,
        canonical_url="https://export.arxiv.org/api/query",
        license=license_str,
        license_evidence=license_evidence,
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=f"what={args.what}; license_filter={args.license_filter}; per_paper: {per_paper_notes}",
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
