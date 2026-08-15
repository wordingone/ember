#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""openreview_fetch.py -- OpenReview API v2 connector CLI.

    openreview_fetch.py --venue VENUE_ID [--year Y] [--what meta|pdf]
                        [--dest DIR] [--allow-unverified-license]

Stdlib-only (the `openreview` package was confirmed ABSENT at build time --
see README "Dependency posture"): queries the public OpenReview API v2
(`https://api2.openreview.net/notes`) anonymously via `urllib.request` +
`json`, paginating with `offset`/`limit` until a short page ends the venue's
note set.

Per-note license handling: OpenReview venues do not have arXiv's fixed
default -- a note's `content.license` field (when present) is the license;
if that field is absent for a note, that note's license is UNVERIFIED (the
frozen §2 rule: absent/unclear license is never guessed). "PDFs only where
license-clean" (per spec): `--what pdf` downloads only notes with a resolved
(non-UNVERIFIED) license; UNVERIFIED notes are metadata-only regardless of
`--what`.

One receipt per invocation, same batching rationale as arxiv_fetch.py: a
single `license` field summarizes the eligible set, per-note detail lives in
`notes`.

NOTE (documented assumption, no live network exercised at build time): the
exact OpenReview API v2 query-parameter names for venue/year filtering are
implemented per the v2 REST docs as understood at build time
(`content.venueid`, `offset`, `limit`); this is NOT covered by the spec's
optional `--live` smoke (that smoke is hf_fetch-only) -- verify against a
real venue before a production pull if the venue's schema differs.

Token auth (fast-follow): anonymous requests to the public API can be
bot-challenged (403). `--token`/`OPENREVIEW_TOKEN` accepts an
already-obtained Bearer token (this connector never performs a login/account
flow -- get the token yourself, e.g. via the OpenReview web UI or a prior
`POST /login`) and forwards it as `Authorization: Bearer <token>` on both the
notes-query requests and any PDF download. Purely additive: with no token
supplied, behavior is byte-identical to before -- still anonymous.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import receipt as rcpt

CONNECTOR_NAME = "openreview_fetch"
API_BASE = "https://api2.openreview.net/notes"
PAGE_SIZE = 100


def _resolve_token(cli_token: Optional[str]) -> Optional[str]:
    """CLI flag wins; falls back to OPENREVIEW_TOKEN env var; None if neither
    is set (anonymous, unchanged default behavior)."""
    if cli_token:
        return cli_token
    return os.environ.get("OPENREVIEW_TOKEN") or None


def _auth_headers(token: Optional[str]) -> Optional[dict]:
    return {"Authorization": f"Bearer {token}"} if token else None


@dataclass
class OpenReviewNote:
    note_id: str
    title: str
    license_str: Optional[str]
    pdf_path: Optional[str]  # OpenReview-relative pdf path, e.g. /pdf/<id>.pdf

    @property
    def license_label(self) -> str:
        return self.license_str if self.license_str else rcpt.UNVERIFIED

    @property
    def license_evidence(self) -> str:
        return "note content.license field" if self.license_str else "no content.license field on note"


def _http_get_json(url: str, opener=None, headers: Optional[dict] = None) -> dict:
    urlopen = opener or urllib.request.urlopen
    req_headers = {"User-Agent": "ember-corpus-connector/1", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_content_field(content: dict, key: str) -> Optional[str]:
    val = content.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val


def query_venue(venue_id: str, year: Optional[int], opener=None, headers: Optional[dict] = None) -> List[OpenReviewNote]:
    notes: List[OpenReviewNote] = []
    offset = 0
    while True:
        params = {"content.venueid": venue_id, "offset": offset, "limit": PAGE_SIZE}
        if year is not None:
            params["content.year"] = year
        url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
        payload = _http_get_json(url, opener, headers=headers)
        page = payload.get("notes", [])
        if not page:
            break
        for raw in page:
            content = raw.get("content", {}) or {}
            notes.append(
                OpenReviewNote(
                    note_id=raw.get("id", "unknown"),
                    title=_extract_content_field(content, "title") or "",
                    license_str=_extract_content_field(content, "license"),
                    pdf_path=_extract_content_field(content, "pdf"),
                )
            )
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return notes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch OpenReview venue metadata/PDFs with an L4 receipt.")
    p.add_argument("--venue", required=True, dest="venue_id", help="OpenReview venue id")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--what", choices=["meta", "pdf"], default="meta")
    p.add_argument("--dest", default=None, help="local destination dir (default: ./corpus-downloads/openreview/<venue>)")
    p.add_argument("--token", default=None, help="OpenReview Bearer token (or set OPENREVIEW_TOKEN); anonymous if omitted")
    p.add_argument("--allow-unverified-license", action="store_true")
    return p


def fetch(args: argparse.Namespace, opener=None) -> Path:
    token = _resolve_token(getattr(args, "token", None))
    auth_headers = _auth_headers(token)
    notes = query_venue(args.venue_id, args.year, opener, headers=auth_headers)
    if not notes:
        raise rcpt.BlockedError(f"no OpenReview notes returned for venue {args.venue_id}")

    key = rcpt.safe_key(args.venue_id + (f"-{args.year}" if args.year else ""))
    dest_root = Path(args.dest) if args.dest else Path("corpus-downloads") / "openreview" / key
    dest_root.mkdir(parents=True, exist_ok=True)

    per_note_notes = "; ".join(f"{n.note_id}={n.license_label}" for n in notes)

    if args.what == "meta":
        meta_path = dest_root / f"meta-{key}.json"
        rcpt.check_no_collision(meta_path)
        meta_path.write_text(
            json.dumps(
                [{"note_id": n.note_id, "title": n.title, "license": n.license_label} for n in notes],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        files = rcpt.build_file_entries(dest_root, [meta_path.relative_to(dest_root)])
        downloaded_paths = [meta_path]
        license_str = "public (OpenReview API metadata only; per-note licenses in notes)"
        license_evidence = "OpenReview API metadata carries no separate reuse license"
    else:
        eligible = [n for n in notes if n.license_str and n.pdf_path]
        if not eligible:
            raise rcpt.BlockedError(
                f"no license-clean notes with a pdf available for venue {args.venue_id}; "
                f"per-note: {per_note_notes}"
            )
        downloaded_paths: List[Path] = []
        for n in eligible:
            url = f"https://openreview.net{n.pdf_path}"
            dest_file = dest_root / f"{rcpt.safe_key(n.note_id)}.pdf"
            rcpt.download_url(url, dest_file, opener=opener, headers=auth_headers)
            downloaded_paths.append(dest_file)
        files = rcpt.build_file_entries(dest_root, [p.relative_to(dest_root) for p in downloaded_paths])
        distinct_licenses = sorted({n.license_label for n in eligible})
        license_str = distinct_licenses[0] if len(distinct_licenses) == 1 else "mixed (see notes)"
        license_evidence = "note content.license field, per note (license-clean filter applied)"
        # eligible notes are pre-filtered to have a resolved license_str, so this
        # is a no-op safety net rather than a live gate -- kept for CLI-contract
        # consistency with the other connectors.
        rcpt.gate_license(eligible[0].license_label, args.allow_unverified_license)

    receipt = rcpt.Receipt(
        source="openreview",
        source_id=args.venue_id,
        canonical_url=f"https://openreview.net/group?id={args.venue_id}",
        license=license_str,
        license_evidence=license_evidence,
        revision=None,
        files=files,
        fetched_at=rcpt.utc_now_iso(),
        connector=rcpt.ConnectorInfo(name=CONNECTOR_NAME),
        dest_root=str(dest_root),
        notes=f"what={args.what}; year={args.year}; per_note: {per_note_notes}",
    )
    return rcpt.commit_receipt(receipt, dest_root, downloaded_paths)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return rcpt.run_cli(lambda: fetch(args))


if __name__ == "__main__":
    sys.exit(main())
